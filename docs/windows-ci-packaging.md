# Windows package by GitHub Actions, and the reproducible cloud environment

Prepared 2026-10-14. Replaces the hand-run Wine/WinPython steps of `TEST_PLAN.md` ("The
Windows launcher package with a native runtime") with a workflow on a real Windows runner.
Status: **written and linted, not yet run on GitHub** (no runner was available in the session
that wrote it; see "What is verified").

## Cloud environment (Claude sessions)

* `scripts/cloud/setup-env.sh` installs only what is missing: the ARM and MinGW toolchains,
  32-bit SDL2/GL, Tk/Xvfb/xdotool/ImageMagick, `uv`, a Python 3.12 venv from `requirements-dev.txt`
  (recreated only when that file changes) and the pinned SDL2 2.30.7 MinGW tree (SHA-256 checked).
  A second run takes under a second and uses no network. `EMERALD_WITH_WINE=1` adds Wine, needed
  only for in-game proofs of the `.exe`, not for building or packaging.
* `.claude/settings.json` + `.claude/hooks/session-start.sh` run it at the start of every cloud
  session (synchronously, cloud sessions only). It takes effect once these files are on the
  repository's default branch.
* Optional, one paste: the environment's **Setup script** box can hold
  `bash scripts/cloud/setup-env.sh` so the installed tools are cached in the environment image
  instead of being installed in each new container.
* After the script: `PATH` starts with the venv, `EMERALD_SDL_DIR` names the MinGW tree, so
  `make -f Makefile_pc SDL_DIR="$EMERALD_SDL_DIR" DIORAMA=1 -j4` builds the Windows exe.
* The private engine is not cloned by the script (it must not hold credentials): attach
  `kashkevin/personal-pokemon-game-emgba3d-engine` to the session, or clone it beside this checkout.
* Engine side: `data/diorama/maps/.gitkeep` and `data/diorama/buildings/.gitkeep` (branch
  `claude/cloud-setup-engine`) so a fresh clone's 3D build no longer fails on the missing directories.

## The workflow `.github/workflows/windows-package.yml`

Manual (`Run workflow`); its jobs:

1. **engine** (Ubuntu): checks out the private engine at `engine_ref`, builds the GBA ROM
   (`make BUILD_NAME=dev`) and the Windows 3D exe (`Makefile_pc DIORAMA=1`, MinGW, pinned SDL2),
   strips the exe, makes `manifest.json` with `generate_manifest.py`, and hands exe, SDL2.dll,
   ROM and manifest to job 2 in a one-day private artifact.
2. **package** (Windows, Python 3.14): installs the hashed wheels of
   `requirements-host-provisioning.txt` and `scripts/windows-runtime/requirements-launcher-build.txt`
   with `--require-hashes --only-binary=:all:`, runs `collect_native_bundle.py --manifest` (which
   pins `game-facts.json`, so the package needs no `game.gba`), then
   `build_launcher.py --development-preview --installer` (a native package is a development preview
   until the native trade replay exists). It uploads the player's installer
   (`EmeraldTogether-Windows-Installer`: the Setup file and QUICK-START.txt only) and the developer
   artifact (`EmeraldTogether.zip`, `package-hashes.json`, `package-audit.json`, `installer.json`,
   logs and screenshots) for 7 days. Private inputs and the work folder are deleted at the end.
3. **install-check** (fresh GitHub-hosted Windows): silent install, file check against
   `package-hashes.json`, start, repair, uninstall, player data kept. Details:
   [windows-installation.md](windows-installation.md).
4. **mega-check** (full, Windows): the engine job also builds the Classic 2D test build
   (`Makefile_pc BFX_TEST=1`, the battle test driver; never packaged); `tools/battle_env/mega_check.py` runs it in
   real Windows game processes: a character from the game's own short introduction, then the Mega Evolution cases,
   every Mega Stone holder, the parade of every Mega form and the stones through the menus, normal and shiny, each
   read from the game's own log (`EmeraldTogether-mega-check`, 7 days; Update 32 report, section 4).
5. **feature-check** (full, Windows): the same test build with `tools/battle_env/feature_check.py`: a new character,
   its save with no Pokemon, the starter claimed in Birch's lab and saved, that save loaded, and three claims each
   undone by the game's own soft reset, every one a new roll (`EmeraldTogether-feature-check`, 7 days; Update 32
   report, section 5.3).

The package contains the game exe, so it holds game data: a private build for friends who own the
game, not for publication. It contains no ROM file, save, invitation or world database.

### One-time setup (needs you)

| What | Where |
| --- | --- |
| `ENGINE_REPO_TOKEN` secret | A fine-grained personal access token for **only** the engine repository, permission *Contents: read*. Settings → Developer settings → Fine-grained tokens; then the app repository's Settings → Secrets and variables → Actions → New secret. |
| Actions enabled on the app repository | Settings → Actions → General. |

That alone produces a complete, installable package **without** the animated Black/White battle
sprites. No `game.gba` is needed on the player's PC: the package pins the game facts recorded from
the engine job's ROM (see [windows-installation.md](windows-installation.md)).

### Private inputs (kept out of Git)

| Input | Pin | Effect when supplied |
| --- | --- | --- |
| `base-emerald.gba`: your own Emerald USA/Europe rev 0 dump (16,777,216 bytes) | SHA-256 `a9dec84d…85af`, already in the workflow | Optional, no longer needed to play: the launcher also gets a BPS patch built from your dump and the built game (`--create-patch`) for the legacy **Import my game** path; the ROM itself is never in the ZIP |
| `battle-sprites.ebsp` (12,372,036 bytes) | Repository **variable** `SPRITE_PACK_SHA256` (the full 64 digits: `Get-FileHash battle-sprites.ebsp`) | Pinned into the runtime beside the exe; battles draw the animated sprites |

How to supply them, most private first (`scripts/windows-runtime/fetch_private_input.py` checks
the hash before accepting a file and refuses anything else):

1. **Self-hosted runner on your own PC.** Settings → Actions → Runners → New self-hosted runner
   (Windows), then set the repository variable `PRIVATE_INPUT_DIR` to a folder such as
   `C:\EmeraldPrivate` that holds the two files with those exact names, and run the workflow with
   `runner = self-hosted`. The files never leave the PC. The job reads only that folder.
2. **Private HTTPS links as secrets.** Put each file in storage you control, create a link that
   expires, and save it as the secret `BASE_ROM_URL` or `SPRITE_PACK_URL` (secrets hold at most
   48 KB, so a link, never the file). The runner downloads it, checks the hash, uses it and
   deletes it; the link is masked in logs. The file does pass through GitHub's runner.
3. **Never** commit them, put them in a release, or attach them to an issue.

### Smoke mode (proved on GitHub, 2026-10-14)

`mode = smoke` (the default, and what a push touching the packaging files runs) needs no engine,
secrets, ROM or sprite pack. `scripts/windows-runtime/make_smoke_inputs.py` writes stand-ins (a copy of
Python's own `python.exe` named like the game, a placeholder `SDL2.dll`, a few KiB of text as the
"ROM" and a manifest the companion's `verify_rom_manifest` accepts), then the real
`collect_native_bundle.py` and `build_launcher.py --development-preview` run on `windows-2022`.

Run 38643201252 (commit `286318a`, success, 70 s): CPython 3.14.8; all wheels installed with
`--require-hashes --only-binary=:all:` (PyInstaller 6.22.3); bundle collected and its launcher check
passed; package built (129 files, import disabled), package audit passed (tree 284 members, archive
345), no ROM/save/database/key in the archive; `EmeraldTogether.exe` stayed running for 20 s
(a modal error dialog would also keep it running; the run saves a screenshot in the artifact
for that reason); 21 MB artifact `EmeraldTogether-windows-smoke` uploaded.

### Reaching the private engine without a personal access token

Tested: with only the built-in `GITHUB_TOKEN`, a workflow in the app repository **cannot** use
the engine repository (`Unable to resolve action ... repository not found`). The Claude GitHub App's
credentials are not available to workflows. Options, narrowest first:

1. **Engine repo setting "Accessible from repositories owned by the user"** (Settings → Actions →
   General → Access). No secret and no expiry: a composite action stored in the engine repository
   can then be used by the app repository's workflows, and the runner downloads the engine files
   with it. Costs: the `uses:` reference must be a fixed branch/tag/SHA (not an input), and the
   engine commit is the reference, not a hash read from a checkout. Not adopted yet because it can't
   be turned on or tested from a cloud session.
2. A read-only **deploy key** on the engine repository (one repository, read only, no expiry,
   revocable).
3. A **fine-grained token** limited to the engine, *Contents: read*, with an expiry date (what the
   workflow uses now: secret `ENGINE_REPO_TOKEN`).
4. An own GitHub App with `actions/create-github-app-token` (one-hour tokens), the most setup.

### What is verified

* actionlint passes; smoke mode ran green on a Windows runner (above).
* On Linux with the real engine build: strip, `generate_manifest.py`, `collect_native_bundle.py`.
* `tests/test_fetch_private_input.py` and `tests/test_scripts_compile.py`: 9 passed.
* **Not verified**: the `full` mode (engine job on Ubuntu, cross-repository checkout, the artifact hand-over,
  the `--create-patch` path with a real dump, the sprite pack), and any play of a real ZIP.
