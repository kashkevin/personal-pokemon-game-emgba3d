# Local build inputs: the owner's own game files, kept out of Git

Written 2026-11-05 for KNOWN_ISSUES U31-13 (owner decision #48: "no game dumps in the repository; authorized local
build inputs"). This describes what the code does today; nothing here changes how a package is built or installed.

## 1. What never goes into Git

| Kind | Examples | Where it lives instead |
| --- | --- | --- |
| Game dumps, BIOS images | `base-emerald.gba`, the built `pokedev.gba`, `.gb`, `.gbc`, `.nds`, `.bin`, `.rom` | the owner's own folder; the engine checkout's build output |
| Saves and save states | `.sav`, `.srm`, `.sa1`, `.flash`, `.ss0`-`.ss9`, `.state`, a save's `.sav.*` records | `%LOCALAPPDATA%\PokemonPrivate\...` on the player's PC |
| The battle sprite pack | `battle-sprites.ebsp` (private official art, `docs/battle-sprites.md`) | beside the game in a package; the owner's folder |
| ROM patches | `game.bps` (made from the owner's dump; it carries most of the built game) | inside a package only |
| The decomp's binary graphics | `.1bpp`, `.4bpp`, `.8bpp`, `.gbapal`, `.lz` | the private engine repository |
| Built games and archives | `pokeemerald-mp(.exe)`, `pokeemerald-mp-diorama(.exe)`, `SDL2.dll`, `EmeraldTogether.zip`, `.7z` | CI artifacts (private to the repository) or the owner's PC |
| Worlds and their databases | `world.sqlite3`, `.db` (and a world's `host.json` and invitations, which hold its keys) | the player's private storage (`%LOCALAPPDATA%\PokemonPrivate\launcher\`) |

How this is enforced:

* `.gitignore` keeps every kind of game data above, and the world databases, out of a `git add` (its section
  "Proprietary game data never goes into Git"), also in an `inputs/` or `native-inputs/` folder copied into a checkout.
  The launcher keeps a world's `host.json` and invitations in its private storage, outside any checkout.
* `tests/test_no_game_data_tracked.py` fails when a tracked file is named as any of these, or holds one by its
  bytes whatever its name (a GBA, DS or Game Boy ROM header, the Nintendo logo of such a header, a BPS/UPS/IPS patch,
  an EBSP pack, an archive, an executable, an SQLite database, or the owner's dump by its SHA-256), or is any other
  binary file outside its allowlist. The allowlist is the eight launcher screenshots in `docs/update28-screenshots/`
  (the project's own Tk window; no game graphics). The test fixtures are text. A staged file counts before it is
  committed (the test reads the index).
* Packages: `scripts/windows-runtime/package_audit.py` refuses ROM, save, save-state, database and credential
  formats in a package and in archives inside it, and the `windows-package` workflow's "Check the package contents"
  step refuses `.gba`, `.sav`, `.sqlite3`, `.db`, `.pem` and `.key` in `EmeraldTogether.zip`.

Audit of 2026-11-05 (nothing found): every tracked file (911 at `1807d43`) and every blob of every branch and tag,
the remote's 13 tags that had not been fetched included (4,406 blobs, 955 commits, 33 annotated tags), checked by
name and by bytes for the formats above; history was read, not rewritten. The only binary files ever committed are the
eight launcher screenshots. `scripts/windows-runtime/source-fixtures.json` names ROM and save fixtures of the mGBA
source that the source
sanitizer removes (paths and hashes only), and `docs/graphics-file-inventory.json` counts the engine's graphics files
(paths, counts and sizes only); neither holds game data.

## 2. Where the game comes from: no dump needed to build or to play

* The game is built from the private engine repository (its source and the decomp's assets): `make BUILD_NAME=dev`
  makes `pokedev.gba`, `Makefile_pc` the native Windows and Linux games. CI checks the engine out with the
  `ENGINE_REPO_TOKEN` secret (`docs/windows-ci-packaging.md`). Nothing of the owner's dump is used for this build.
* A native package carries `game-facts.json` (`game_facts.py`): the built ROM's identity, its capability markers and
  the battle-message lengths, recorded when the package is built (`collect_native_bundle.py --manifest`) and pinned
  by the runtime bundle. `LauncherRelease.installation` uses the facts whenever the bundle names them, so a
  player's PC needs no `game.gba` (`docs/windows-installation.md`, KNOWN_ISSUES NU-6). The native game itself
  never reads a ROM: its data is compiled in.
* No GBA BIOS image is used anywhere: the native game implements the BIOS calls itself (engine
  `src/platform/bios.c`, whose licensing is owner decision #1, KNOWN_ISSUES N8).

## 3. Where the owner's own dump is used today (optional)

The dump is the owner's own, legally obtained copy of Pokemon Emerald (USA/Europe, revision 0): 16,777,216 bytes,
SHA-256 `a9dec84dfe7f62ab2220bafaef7479da0929d066ece16a6885f6226db19085af` (a public identity, pinned as
`BASE_ROM_SHA256` in `windows-package.yml`; `docs/release-patch-creation.md`). It is used for one thing: the
**game import patch**, so that a package can rebuild the game from a player's own dump.

1. **Building a package with import** (`scripts/windows-runtime/build_launcher.py`): `--base <dump> --base-sha256
   <pin> --create-patch`. The builder reads the dump (raw `.gba`, or a ZIP with exactly one `.gba`, read in memory
   with size, directory and header checks, nothing extracted: `game_import.read_game_source`), checks both pins,
   makes `game.bps` from the dump to the built game, applies it again and checks the result's SHA-256, and freezes
   the patch and its pins (source, patch and game SHA-256 and sizes) into the package. `--preflight-only` does the
   checks and makes nothing. Without a base the package is built with `--development-preview` and import disabled.
2. **Installing on a PC from such a package**, only when the package has no game facts (the mGBA runtime and older
   builds; a native package never asks): Settings, Game files ("Install your game": the full path of the player's
   own file) in the in-game menu, or "Import my game..." in the fallback window (a file dialog for `.gba` and
   `.zip`). `GameImporter.install` checks the dump's size and SHA-256 against the package's pin and the patch's
   SHA-256, applies the patch with its three CRCs, checks the result's size and SHA-256, and writes only the result,
   `%LOCALAPPDATA%\PokemonPrivate\launcher\games\<game SHA-256>\game.gba` (a new file, flushed and linked into
   place, never replacing a different one). The dump is not copied or changed.

## 4. How the owner supplies the dump and the sprite pack

Keep both files outside the repository folder (for example `C:\EmeraldPrivate\`) and check the dump first:
PowerShell `Get-FileHash C:\EmeraldPrivate\base-emerald.gba` must print the SHA-256 above. For a ZIP, the pin is the
`.gba` inside it.

* **On the owner's PC, by hand**: pass the path to `build_launcher.py --base ... --create-patch` (section 3.1), or
  to Settings, Game files of a package that offers the import (section 3.2).
* **CI on a self-hosted runner** (the owner's PC; most private): set the repository variable `PRIVATE_INPUT_DIR` to
  that folder, name the files exactly `base-emerald.gba` and `battle-sprites.ebsp`, and run `windows-package` with
  `mode = full`, `runner = self-hosted`. Only the `package` job runs there; it copies the files into its own `inputs`
  folder on that PC and deletes `inputs` and its work folder when it ends, whatever the result. The dump never leaves
  the PC; what the package built from it carries, and uploads, is in section 5.
* **CI on GitHub's runners**: the secrets `BASE_ROM_URL` and `SPRITE_PACK_URL`, each an expiring HTTPS link to
  storage the owner controls (a secret holds a link, never the file). The file passes through GitHub's runner.
* **The sprite pack** in either case also needs the repository variable `SPRITE_PACK_SHA256` (its 64-digit
  SHA-256); without it the pack is not fetched at all and battles draw the GBA sprites.

`scripts/windows-runtime/fetch_private_input.py` does the fetching: the local folder first, then the link (HTTPS
only; masked in the log; at most 32 MiB, streamed to a temporary file and kept only if its SHA-256 matches the pin).
It prints only the file name, size and hash. A missing input is not an error (exit 3: the job goes on without it); a
wrong one stops the job (exit 1).

## 5. What CI keeps of private inputs

* The dump itself is never uploaded. A package built with it carries `game.bps` (the patch to the built game), one
  built with the sprite pack carries the pack beside the game (pinned in the runtime bundle), and every package
  carries the game's executables, which hold the game's data: the installer and the developer package are uploaded as
  artifacts like any package, private builds for friends who own the game, never published
  (`docs/windows-ci-packaging.md`).
* Artifacts are private to the repository: the built game (`native-inputs`: the executables, `pokedev.gba` and its
  manifest) is kept for one day as the hand-off between jobs; the installer and the developer package for 7 days.
  `tests/test_windows_workflow.py` checks that no other upload of `windows-package.yml` names a `.gba`, `.sav` or
  database file.
* `smoke` mode needs no secret and no game data: `make_smoke_inputs.py` writes synthetic stand-ins.

## 6. Developer machines and tests

* The engine checkout lives beside the app repository, never inside it; tests that run the real game take its
  path from `EMERALD_ENGINE_BINARY` (or `EMERALD_ENGINE_CHECKOUT`) and are skipped without it.
* The owner's private saves are read only by path: `EMERALD_PRIVATE_SAVE_PATHS` (`tests/test_flash.py`, read-only,
  skipped without it). The other tests make synthetic stand-ins in temporary folders.

## 7. If game data is committed by mistake

`tests/test_no_game_data_tracked.py` fails until the file is out of the index (`git rm --cached <file>`). A file
that already reached a pushed commit stays in history until the owner decides otherwise: rewriting history changes
every later commit and is not done without the owner. Tell the owner which commit and file.
