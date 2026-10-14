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

Manual (`Run workflow`), two jobs:

1. **engine** (Ubuntu): checks out the private engine at `engine_ref`, builds the GBA ROM
   (`make BUILD_NAME=dev`) and the Windows 3D exe (`Makefile_pc DIORAMA=1`, MinGW, pinned SDL2),
   strips the exe, makes `manifest.json` with `generate_manifest.py`, and hands exe, SDL2.dll,
   ROM and manifest to job 2 in a one-day private artifact.
2. **package** (Windows, Python 3.14): installs the hashed wheels of
   `requirements-host-provisioning.txt` and `scripts/windows-runtime/requirements-launcher-build.txt`
   with `--require-hashes --only-binary=:all:`, runs `collect_native_bundle.py`, then
   `build_launcher.py --development-preview` (a native package is a development preview until the
   native trade replay exists). It uploads `EmeraldTogether.zip`, `package-hashes.json`,
   `package-audit.json` and the build log for 7 days. Private inputs and the work folder are deleted
   at the end.

The package contains the game exe, so it holds game data: for your own PC only. It contains no
ROM, save, invitation or world database.

### One-time setup (needs you)

| What | Where |
| --- | --- |
| `ENGINE_REPO_TOKEN` secret | A fine-grained personal access token for **only** the engine repository, permission *Contents: read*. Settings → Developer settings → Fine-grained tokens; then the app repository's Settings → Secrets and variables → Actions → New secret. |
| Actions enabled on the app repository | Settings → Actions → General. |

That alone produces a package **without** the animated Black/White battle sprites and **without**
game import. The launcher then needs a matching `game.gba` installed by hand, so it is not a
"download and play" ZIP.

### Private inputs (kept out of Git)

| Input | Pin | Effect when supplied |
| --- | --- | --- |
| `base-emerald.gba`: your own Emerald USA/Europe rev 0 dump (16,777,216 bytes) | SHA-256 `a9dec84d…85af`, already in the workflow | The launcher gets a BPS patch built from your dump and the built game (`--create-patch`) and shows **Import my game**: the package becomes playable by anyone who owns that dump, and the ROM itself is never in the ZIP |
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

### What is verified

* actionlint passes on the workflow.
* Run on Linux with the real engine build: strip, `generate_manifest.py` (ROM
  `f214735b…3387`), `collect_native_bundle.py` (its own launcher check passed).
* `tests/test_fetch_private_input.py` (hash, size bound, https only, masking) and
  `tests/test_scripts_compile.py`: 8 passed.
* **Not verified**: the Windows job (PyInstaller on a Windows runner, `build_launcher.py`, the
  `--create-patch` path with a real dump), the cross-repository checkout with the token, and any
  play of the resulting ZIP. Expect the first run to need small fixes.
