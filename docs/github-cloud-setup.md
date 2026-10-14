# GitHub and cloud-session setup (prepared 2026-10-14)

What a fresh clone of the two repositories contains, what it deliberately does not, and how to
supply the rest. Written for moving development from the owner's PC and the cloud workspaces to
Claude cloud sessions working from GitHub.

## The two repositories

| Repo | Branch to continue from | Tag of the last build | Head (2026-10-14) |
| --- | --- | --- | --- |
| App (host, companion, launcher, docs, tests, proofs) | `claude/emeraldtogether-combined-app` | `emeraldtogether-combined-20261014-2` = `8e21e46` | `7481b02` (docs after the tag) |
| Engine (pokeemerald-expansion 1.17.1 fork: GBA game, native PC port, Diorama 3D, native UI, Battle FX, sprites, multiplayer) | `claude/emeraldtogether-combined` | `emeraldtogether-combined-20261014-2` = `e1105565eb` (game code `f8dbffa88a`) | `e1105565eb` |

Every other project branch (`claude/*`, `codex/*`) is an ancestor of these two heads, so they are
history, not open work. Other sessions' branches that were fetched from checkpoint bundles are kept
as tags `archive/<checkpoint>/<branch>` on the engine so nothing is lost and no branch names collide.

Remotes: the app's GitHub home is `kashkevin/personal-pokemon-game-emgba3d` (its only branch
there, `codex/multiplayer-delivery` `31e5bf9`, is an ancestor of the combined app branch). The
engine's `origin` is the public upstream `rh-hideout/pokeemerald-expansion`: **never push there**.
The engine needs its own private repository; rename the upstream remote to `upstream` and add the
private one as `origin`.

## Not in Git, on purpose

| Item | Why | How to supply it |
| --- | --- | --- |
| `battle-sprites.ebsp` (12,372,036 bytes, sha256 `3fd5ce37…7435`) | Official Black/White sprite art, permission-gated private export (docs/battle-sprites.md) | Copy from any `emeraldtogether-*` checkpoint folder's `battle-sprites-pack.zip` (`%LOCALAPPDATA%\PokemonPrivate\claude-checkpoints\`), or `artifacts\sprite-integration-v2\` on the PC. Place beside the game exe (`runtime\`) or pass `PKMN_BATTLE_SPRITES_PACK=<path>` |
| GBA ROM `pokeemerald.gba` (sha256 `f214735b…3387`) and `pokedev.elf` | A build output of the engine (not a commercial ROM); the launcher checks it, the companion's `manifest.json` is derived from it | `make -j2` in the engine rebuilds it byte for byte; `scripts/multiplayer/generate_manifest.py` makes `manifest.json` from the ELF and ROM |
| Test saves (`route101.sav`, `menu-a.sav`, `menu-b.sav`, `battle-test.sav`, the `proof/scenes/*.sav` set) | Private player saves | Copy from the PC (`benchmark\saves\battle-test.sav` in `battlefx-int-wip-20261013-1`; the others from the owner's private folders) or create new ones in the game; the proofs take any save standing on Route 101 |
| Worlds, launcher data, `*.sqlite3` | Player data | Never needed for development |
| `src/platform/bios.c` | GPL/MPL-derived code (KNOWN_ISSUES N8) — it IS in Git | Keep the engine repository private until it is replaced |
| Build outputs (`build/`, `*.o`, generated `.inc`/`.4bpp`/`.s`, the exes) | Generated | The build makes them |

Nothing in either repository contains credentials, tokens or keys (scanned 2026-10-14; the two
"password" hits are `cryptography` API arguments).

## What a fresh clone needs installed

| Need | Used by | Source |
| --- | --- | --- |
| `arm-none-eabi-gcc` (devkitARM or a system cross compiler), `make`, `gcc` (32-bit able: `gcc-multilib`), `python3` | GBA build, tools | distro packages / devkitPro |
| `libsdl2-dev` (32-bit: `libsdl2-dev:i386`), Mesa/`libgl1-mesa-dev:i386` | native Linux builds `Makefile_pc NATIVE_LINUX=1` | distro packages |
| `i686-w64-mingw32-gcc` + SDL2 2.30.7 mingw development package (`SDL2-devel-2.30.7-mingw.tar.gz`, its `i686-w64-mingw32` tree) | Windows exe `Makefile_pc SDL_DIR=<that tree>` | `mingw-w64` packages; SDL2 from libsdl.org releases |
| Python 3.12 venv with `requirements-dev.txt` | host/companion/launcher tests, proofs, engine tools (Pillow, numpy) | pip |
| Xvfb, xdotool, ImageMagick `import` | in-game proofs (`DISPLAY=:98`, `:97`) | distro packages |
| Wine (32-bit prefix) + WinPython 3.14 + PyInstaller | the launcher package check and `build_launcher.py` under Wine | Wine from distro; WinPython from winpython.github.io; the pinned wheels in `requirements-host-provisioning.txt` |
| mGBA 0.10.5 (`tools/mgba/mgba-rom-test` binaries are in the engine) | GBA test suite `make check` | in repo |

Paths in `AGENTS.md`, `TEST_PLAN.md` and the proof commands assume the two clones at
`/home/claude/pokemon` (app) and `/home/claude/engine` (engine) with worktrees beside them; any
other layout works by passing `--game`, `--rom`, `--manifest` and `--save` explicitly.

## Checkpoints and rollback points

Every checkpoint is a tag on both repositories (`emeraldtogether-*`, `native-wip-*`,
`graphics-wip-*`, `ui-native-*`, `battle3d-*`, `character-integration-*`, `emulator-baseline-*`) and a
folder with the built package under `%LOCALAPPDATA%\PokemonPrivate\claude-checkpoints\` on the
owner's PC (bundles, zips, evidence). Pushing the tags preserves the code side; the package folders
stay on the PC (they hold the private sprite pack and built games).
