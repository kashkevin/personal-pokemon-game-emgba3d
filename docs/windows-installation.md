# Windows installation: package, game facts, installer and checks (developer view)

Status: implemented on branch `claude/nu-install` (app). Unit-tested on Linux; the Inno Setup
build, the installer itself and the workflow run only on Windows/GitHub and have **not** been run
from this branch yet (see "What was verified").

## What was wrong

Friends could not install the Windows package. The menu said *"The game files are missing or
changed, and this package cannot install them."* The launcher required a GBA ROM at
`%LOCALAPPDATA%\PokemonPrivate\launcher\games\<rom_sha256>\game.gba`
(`LauncherRelease.installation`, `GameInstallation.verify`). The package could only provide it
through *Import my game* (`game.bps`), which CI builds only when it has the owner's base ROM
(`HAVE_BASE`), which it never had. Players fell back to native-inputs artifacts, renaming
`pokedev.gba`, SHA-256 checks, PowerShell and hand-made folders.

## What the ROM was actually used for

Checked against the engine (`origin/claude/emeraldtogether-combined`) and this repository:

* The native game never reads a `.gba`. It is started with `--save`, `--bridge`, `--config`,
  `--link-role` (play), `--setup` (character draft) or `--shell` (menu)
  (`player_runtime._open_child`, `draft_runtime`, `shell_app.main`); `src/platform/sdl2.c`
  `ParseArguments` has no ROM argument, and all game data is compiled in (`Makefile_pc`).
  Screenshots go to the launch folder (the game's working directory in private storage), the
  sprite pack is read beside the exe.
* The Python side used the ROM for:
  1. **identity**: the world build id is the ROM SHA-256 (`verify_rom_manifest`'s return value;
     `host_world._build`, `Invitation.companion_config`, `CompanionConfig.build_id`), currently
     `f214735b64e113fd10730eacca5764d757f2c93a3685230aa905af7a7cdd3387`;
  2. **capability markers**: `verify_rom_manifest` and the validators it calls compare the ROM
     bytes at every marker/descriptor address the manifest names (trade, battle, resume, co-op,
     admission cleanup, save window, menu, reset, reset input, reset catalogue, emergency save,
     trade-effect markers, trade replay descriptor, presence animation, generation profile,
     player build guard, shared world);
  3. **battle message lengths** on the host (`battle_controller.read_string_lengths`, called
     from `LauncherSession._start_host_service`);
  4. the **mGBA trade replay worker** (`trade_native_replay`, needs the ROM itself; not packaged)
     and the legacy **mGBA runtime** (`emerald-windows-runtime-v1`, runs the ROM).

## The fix: pinned game facts

`src/emerald_multiplayer/game_facts.py`. When the runtime bundle is collected,
`collect_native_bundle.py --manifest manifest.json` runs the complete ROM verification
(`verify_rom_manifest(rom, manifest)`) and writes `runtime/game-facts.json`:

| Field | Content |
| --- | --- |
| `format` | `emerald-game-facts-v1` |
| `rom_sha256`, `rom_size`, `rom_crc32` | the ROM identity; must equal the manifest's |
| `manifest_sha256` | SHA-256 of the exact `game-manifest.json` bytes the facts belong to |
| `markers` | `{manifest field: hex}` - the ROM bytes at every ROM-resident `*_address` the manifest names (4 bytes, or the descriptor length for the player-build guard, generation profile, reset catalogue and trade replay descriptor), recorded after the full check |
| `battle_string_table_address`, `battle_string_lengths` | the 721 battle-message lengths (`null` for an empty slot), when the manifest has the battle string table |

It is about 3.3 KB for the real game (measured from `pokedev.gba` `f214735b...`).
`runtime.json` gains `"game_facts": "game-facts.json"` and lists the file in `files`, so
`runtime_sha256` (compiled into the launcher's entry point) pins it like every executable.
The game manifest itself is unchanged, and so is its pin.

How the runtime uses it:

* `verify_rom_manifest(source, manifest)` accepts a facts file (`*.json`) in place of a ROM. It
  binds the facts to the manifest bytes (`manifest_sha256`) and to the manifest's ROM identity
  (SHA-256, size, CRC32), checks that the recorded markers are exactly the manifest's ROM markers
  and that the battle lengths match the manifest's table, then runs every capability validator in
  its existing manifest-only mode (`rom_path=None`). It returns the facts' `rom_sha256` as the build
  id - the same value the ROM gives, so **every existing world, invitation, invite code and save
  keeps working** (tested: a world created from the ROM opens from the facts and back).
  The marker bytes are not compared again at run time: under the pins they are exactly what the
  build compared against the ROM, so a second comparison would add nothing.
* `GameInstallation.rom_path` is "what the manifest is checked against": the ROM, or the facts.
  `GameInstallation.verify()` in facts mode first runs `bundle.verify()` (hashes every pinned file,
  facts included), requires the facts to be the very file the pinned `runtime.json` names, then
  `verify_rom_manifest` and the build-id check. ROM mode is unchanged.
* `GameInstallation.battle_string_lengths(table_address)` reads the ROM, or returns the recorded
  lengths (after the manifest pin check); `LauncherSession` uses it.
* `LauncherRelease.installation()` uses the facts whenever the bundle's `runtime.json` names them,
  otherwise the imported `games/<rom_sha256>/game.gba` as before. A stray or wrong `game.gba` a
  player copied in earlier is therefore ignored by a native package.
* `RuntimeBundle.game_facts_path()` returns the pinned facts path; `runtime.json` accepts the
  optional `game_facts` key only in the native format and only naming `game-facts.json`.
* Refusals: the mGBA runtime never takes facts (`player_runtime._open_child`, and
  `GameInstallation.verify` finds no facts in a non-native bundle); `NativeTradeReplay` refuses facts
  (the replay worker runs the ROM). The existing integrity checks are untouched: exe/DLL pins, the
  unlisted-executable refusal, the manifest pin, the native/ROM pairing (`runtime.json`
  `rom_sha256`).

Development setups keep working: tests, the proof scripts, the mGBA replay worker and the old Tk
launcher pass a real ROM, which is verified byte for byte as before. `game_import.py` is unchanged:
a package that ships `game.bps` (and no facts) still installs the player's own game from Settings,
Game files.

## Verify and repair: `check_installation`

`src/emerald_multiplayer/installation_check.py`:

```python
from emerald_multiplayer.installation_check import check_installation
report = check_installation(installation, importer=importer)   # never raises, never writes
report.ok            # True when every pinned file matches (ends with installation.verify())
report.problems      # tuple of Problem(code, title, message, steps)
report.text()        # plain-English text for a message screen
```

| Code | Means |
| --- | --- |
| `manifest_missing` / `manifest_changed` | `game-manifest.json` |
| `runtime_record_missing` / `runtime_record_changed` | `runtime\runtime.json` |
| `game_missing` / `game_changed` | the game program (`runtime.json` `executable`) |
| `classic_game_missing` / `classic_game_changed` | the Classic 2D program |
| `sdl_missing` / `sdl_changed` | `SDL2.dll` |
| `sprites_missing` / `sprites_changed` | the battle picture pack (`*.ebsp`) |
| `game_facts_missing` / `game_facts_changed` | `game-facts.json` (also: facts that are not the pinned file) |
| `runtime_file_missing` / `runtime_file_changed` | any other pinned file |
| `runtime_unlisted` | an unknown `.exe`/`.dll`/`.lua` in the game folder |
| `rom_missing` / `rom_changed` | the player's `game.gba` (only installations without facts) |
| `path_unsupported` | the installation path is too long for the game |
| `unverified` | anything else the full check refused |

Package-file problems tell the player to close EmeraldTogether and run the Setup file again (it
repairs), or to uninstall and reinstall, and that saves and worlds in
`%LOCALAPPDATA%\PokemonPrivate` are kept; a missing `.exe`/`.dll` adds the antivirus-quarantine
hint. Messages name files, never private paths. The in-game menu (owned by the menu work) is
expected to call this from Settings, Game files; `shell_app.py` was not changed here.

## Package layout (after installation)

```
%LOCALAPPDATA%\Programs\EmeraldTogether\
  EmeraldTogether.exe          PyInstaller onedir launcher (release pins compiled into its entry)
  README.txt  QUICK-START.txt  RELEASE-LIMITS.txt
  unins000.exe  unins000.dat   Inno Setup uninstaller
  _internal\
    game-manifest.json         pinned by manifest_sha256
    package-provenance.json    build record (game_facts: true, needs_game_file: false)
    runtime\
      runtime.json             pinned by runtime_sha256; pins every file below
      pokeemerald-mp-diorama.exe  pokeemerald-mp.exe  SDL2.dll  [battle-sprites.ebsp]
      game-facts.json
%LOCALAPPDATA%\PokemonPrivate\launcher\   the player's data (never installed, replaced or removed)
```

## The installer

`scripts/windows-runtime/installer/EmeraldTogether.iss` (Inno Setup 6.3+; GitHub's
`windows-2022` image lists **InnoSetup 6.7.1**, image 20261012, and its own test finds `iscc` on
`PATH`; the workflow installs exactly 6.7.1 from Chocolatey on a runner without it).
`build_launcher.py --installer [--iscc PATH]` calls:

```
iscc /Qp /DAppVersion=<version> /DSetupVersion=<file-name-safe version> /DPackageDir=<dist\EmeraldTogether> /O<output\installer> EmeraldTogether.iss
```

* Per-user, no admin rights (`PrivilegesRequired=lowest`), default folder
  `{userpf}\EmeraldTogether` = `%LOCALAPPDATA%\Programs\EmeraldTogether`; x64 Windows only (the
  launcher is a 64-bit PyInstaller build). `/CURRENTUSER` is accepted and changes nothing.
* Start menu shortcut; optional (unchecked) desktop shortcut; optional "open the quick start
  guide" and "start now" on the last page.
* Fixed `AppId` `{CAC8954B-B6DB-4E29-AD98-412B39D18856}`: running the same or a newer Setup again
  finds the installation (same folder, no folder page), closes running copies through the Restart
  Manager, deletes `{app}\_internal` first (`[InstallDelete]`, so no file of an older version stays
  next to the new game - the launcher refuses unknown programs there) and writes the new files.
  This is the **Repair**: the welcome page says "Setup will repair or update it" when it finds the
  installation.
* The uninstaller removes only what Setup installed. There is no `[UninstallDelete]`, nothing
  refers to `PokemonPrivate`, and the app never writes into its program folder.
* Plain-English pages: welcome, the `RELEASE-LIMITS.txt` "please read" page (its top section is a
  short plain summary), finish, uninstall confirmation.
* Not code-signed (no certificate or secret exists): SmartScreen shows "Windows protected your PC"
  until the player chooses More info, Run anyway; QUICK-START explains it.

`build_launcher.py` writes `installer/EmeraldTogether-Setup-<version>.exe`, `installer.json`
(name, SHA-256, size, script hash) and `player/` with exactly the Setup file and the package's
`QUICK-START.txt` (the native keys substituted). A native package without game facts is refused
before PyInstaller runs, and the facts-mode installation is verified with the same code the
installed launcher runs.

## CI (`.github/workflows/windows-package.yml`)

Package job (smoke and full):

1. *Collect the native runtime bundle*: now with `--manifest inputs/manifest.json`.
2. *Inno Setup compiler*: `iscc` from `PATH`, else the standard folder, else
   `choco install innosetup --version=6.7.1`; prints its banner.
3. *Build the launcher package*: adds `--installer --iscc "$ISCC"`.
4. *Check the package contents*: additionally `game-facts.json` is hashed in the package, no
   `.gba/.sav/.sqlite3/.db`, and `player/` is exactly the Setup file plus `QUICK-START.txt`.
5. *Verify the packaged game files*: additionally `runtime.json` names the facts, and the facts
   verify against the packaged manifest with the runtime's `rom_sha256` (full: the engine job's ROM
   SHA-256) as the build id.
6. Unchanged: start the frozen launcher (full: one `--shell` child), graphics-mode check, in-game
   menu check, summary (now with the Setup file's name and SHA-256).
7. Uploads: **`EmeraldTogether-Windows-Installer`** (smoke: `...-smoke-test`) = `player/` only;
   `installer-check-inputs-<mode>` (package hashes, one day); the developer artifact
   `EmeraldTogether-windows-<mode>` as before plus `installer.json` and `installer.log`.

New **install-check** job on a fresh GitHub-hosted `windows-2022` (never self-hosted, so the
owner's PC is never installed to), `scripts/windows-runtime/ci_installer_check.py`:

1. refuses to run if EmeraldTogether is already installed for the user;
2. temporary profile: `LOCALAPPDATA` for everything it starts points into the work folder, and a
   sentinel is planted in its `PokemonPrivate`;
3. `Setup /VERYSILENT /SUPPRESSMSGBOXES /CURRENTUSER /NORESTART /DIR=<temp> /LOG=...` (exit 0);
4. every installed file matches `package-hashes.json` (only `unins000.*` extra), the uninstall
   entry and the Start menu shortcut exist;
5. the installed `EmeraldTogether.exe` stays up 20 s (full: exactly one `--shell` child) and made its
   private folder in the temporary profile;
6. repair: a stray DLL planted in the game folder and a deleted `README.txt` - after the silent
   re-run the stray is gone and the files match again;
7. silent uninstall (waits for the uninstaller's hand-off copy): no program files, shortcut or
   uninstall entry remain; the sentinel and the launcher's private files are unchanged.

It uploads `installer-check.json` and the Setup/uninstall logs (`EmeraldTogether-installer-check-<mode>`).

## Reproduce locally

Linux (what this branch was tested with):

```sh
/tmp/claude-0/venv312/bin/python -m pytest -p no:cacheprovider -o addopts="" \
  tests/test_packaged_installation.py tests/test_build_installer.py tests/test_ci_installer_check.py \
  tests/test_windows_workflow.py tests/test_shell_game_files.py
# Facts from a real engine build (read-only use of the engine tree; output in a scratch folder):
PYTHONPATH=src python scripts/multiplayer/generate_manifest.py --rom <engine>/pokedev.gba \
  --elf <engine>/pokedev.elf --engine-commit <commit> --output /tmp/x/manifest.json
PYTHONPATH=src python -c "from emerald_multiplayer.game_facts import write_facts; \
  write_facts('<engine>/pokedev.gba', '/tmp/x/manifest.json', '/tmp/x/game-facts.json')"
```

Windows (Python 3.14 venv with `requirements-host-provisioning.txt` and
`scripts/windows-runtime/requirements-launcher-build.txt`, Inno Setup 6.3+):

```bat
python scripts\windows-runtime\make_smoke_inputs.py --exe C:\Python314\python.exe --output inputs
python scripts\windows-runtime\collect_native_bundle.py --game inputs\pokeemerald-mp-diorama.exe ^
  --classic-game inputs\pokeemerald-mp.exe --sdl inputs\SDL2.dll --rom inputs\pokedev.gba ^
  --manifest inputs\manifest.json --output %TEMP%\et\runtime
rem --rom-sha256/--manifest-sha256/--runtime-sha256: Get-FileHash of pokedev.gba, manifest.json, runtime.json
python scripts\windows-runtime\build_launcher.py --rom inputs\pokedev.gba --manifest inputs\manifest.json ^
  --runtime %TEMP%\et\runtime --rom-sha256 ... --manifest-sha256 ... --runtime-sha256 ... ^
  --version "Local 1" --development-preview --installer --output %TEMP%\et\launcher
python scripts\windows-runtime\ci_installer_check.py --setup %TEMP%\et\launcher\player\EmeraldTogether-Setup-Local-1.exe ^
  --hashes %TEMP%\et\launcher\package-hashes.json --work %TEMP%\et\check
```

(`ci_installer_check.py` refuses to run where EmeraldTogether is already installed.)

## What was verified, and what was not

Verified on Linux: the new and updated unit tests and the full app suite; facts built from the real
`pokedev.gba` (`f214735b...3387`) and its generated manifest give the identical build id; the
packaging build (staging, pins, facts check, guides, hashes, zip, audit, installer record, player
folder) with PyInstaller and `iscc` replaced by stand-ins; the `.iss` references only files that
build produces; the installation-check logic against a simulated Inno Setup; the workflow's text.

Not verified here (needs Windows/GitHub): compiling the `.iss` with `iscc`, the real Setup and
uninstaller behaviour (Restart Manager, `[InstallDelete]`, shortcuts, uninstall registry entry),
SmartScreen and antivirus behaviour, and any run of the updated workflow. The first smoke run of the
workflow on a push is the first real test of the installer path.

## Open risks

* **Legal**: the native executables contain the game's graphics, music and text, so the package
  is a private build for friends who own Pokemon Emerald and must not be published. The
  `src/platform/bios.c` licensing question (`docs/bios-licensing-review.md`) is still open; its
  recommendation was to replace the file before any binary handover.
* **Unsigned installer**: SmartScreen warns on every new build until it gains reputation; there is
  no signing certificate.
* **Antivirus**: unsigned PyInstaller launchers and new executables are common false positives; a
  quarantined file shows up as `game_missing`/`sdl_missing` with the antivirus hint, and re-running
  Setup repairs it.
* **Inno Setup on the runner image** is not pinned by GitHub (6.7.1 today); the script requires
  6.3+ and fails clearly otherwise.
* The networking paragraph of QUICK-START describes this build (no automatic router setup); update
  it when the relay / port-mapping work lands.
