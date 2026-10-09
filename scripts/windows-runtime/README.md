# Private Windows runtime build

This builds the pinned mGBA SDL frontend with the project adapter. It downloads
official emulator dependencies, never game ROMs/assets. Outputs, source caches,
ROMs, saves and smoke evidence stay outside this repository.

The qualified build environment is Ubuntu in WSL with CMake, Git, Python 3.12,
Meson 1.3.2, Ninja, pkg-config, GNU make, and the x64 POSIX MinGW compiler
13.2.0 (`mingw-w64 11.0.1`). The script uses two workers at `nice 15`. The
adapter uses public core/script/thread/socket APIs; only the two SDL frontend
files change in the pinned upstream source. No ROM/core patch is made.

1. Create a clean separate mGBA worktree at
   `26b7884bc25a5933960f3cdcd98bac1ae14d42e2`.
2. Run `python3 prepare_frontend.py /absolute/path/to/worktree` from this
   checkout. It validates every replacement and adapter destination before
   changing files, and refuses existing SDL edits/adapters.
3. Run `python3 fetch_dependencies.py /absolute/private/dependency-cache`.
   Cached/downloaded official SDL2, Lua and libepoxy archives must match their
   recorded hashes before extraction.
4. Run `bash build_runtime.sh /absolute/path/to/worktree
   /absolute/private/dependency-cache`, with both arguments on the same command
   line. Keep its complete log. The executables are `build-windows/mgba-sdl.exe`
   and the separate `build-windows/emerald-trade-replay.exe`.
5. Run `python3 collect_bundle.py --source /absolute/path/to/worktree
   --dependencies /absolute/private/dependency-cache --output
   /absolute/new/private/bundle`, with the options on one command line. The
   output must be new. Copy the whole resulting directory to private Windows
   storage without adding ROMs/saves.

For an offline rebuild using the existing qualified dependency cache, set
`EMERALD_REUSE_BUILT_DEPS=1` when invoking `build_runtime.sh`. This explicitly
requires the existing Lua, libepoxy and SDL libraries/headers and skips dependency
compilation and installation. Preserve and compare their hashes against the
qualified cache record before using this mode. Collection still checks the
original dependency archive pins. The default dependency build remains unchanged;
runtime test, cinema and performance targets are explicitly disabled in both modes.

The dedicated replay worker uses the same unmodified pinned libmGBA and library
cache, with project-owned `native/windows-runtime/trade-replay-worker.c`. It
opens no window, player save, Lua script, user configuration or network socket.
It accepts one bounded request and calls only the entry point declared by the
verified game ROM in a fresh, unbooted core. The host adapter supplies canonical
checkpoint bytes and checks complete results; the worker is never a live-player
memory interface. Its Unicode Windows command line is converted to UTF-8 for
mGBA's VFS. The native ABI, link and performance need their own recorded evidence.

The collection contains `runtime.json` in the `emerald-windows-runtime-v1`
format. Supply its SHA256 as the application pin to `RuntimeBundle`, rather
than trusting an arbitrary manifest beside an executable. The executable,
replay worker, SDL2 DLL, Winpthreads DLL, Lua bridge template and retained material have
individual hashes. Recollect after a bridge/source/dependency change; a proof
bundle with appended input callbacks must have a separate pin.

The source archive is a packaging derivative of the exact upstream commit.
`sanitize_source.py` checks its pinned original archive hash and the explicit
`source-fixtures.json` inventory, then excludes only 193 unused cinema test
fixtures: 154 GB ROMs, three GBA ROMs, five empty save files, and 31 video logs
whose headers declare an initial saved state. Production test/cinema/performance
targets must be disabled. Every retained member's bytes and metadata are checked;
production sources, original notices, and binary relink inputs remain intact.
`source-packaging.json` records original/derivative hashes and each omitted
fixture's path, size, hash, and reason. This does not rebuild the executable.

To reproduce the source-only transformation, run `python sanitize_source.py
--source /path/to/original/mGBA-source.tar.gz --output /new/source.tar.gz
--provenance /new/source-packaging.json` on one line. Outputs must not exist.
A different upstream revision or archive hash requires a separate review and
explicit inventory update; unknown files are never automatically deleted.

For source rebuilding, retain this project's `scripts/windows-runtime/` and
`native/windows-runtime/` layout with the covered-source patch/archive. The
relink archive contains the static core/Lua/epoxy libraries, SDL/Winpthreads
import libraries and frontend objects, plus the replay worker's exact compiled
source/object and a separate `-municode` relink command. The retained blip_buf LGPL notice and
sources accompany these inputs. Inspect recipient-specific source/relink and
game-content obligations before a distribution; private collection is not a
release approval. See `docs/dependency-ledger.md` for component terms.

The Windows build uses SDL's relocatable CMake configuration and isolated
cross pkg-config paths. It retains upstream's required libepoxy WGL support.
`BUILD_LTO=OFF` is required by the qualified GCC build: the initial LTO build
compiled but failed every Lua bound-object method in Windows smoke tests.
Turning LTO off fixed those methods without changing mGBA core source.

`smoke_runtime.py` is a Windows-only development proof. Give it explicit
executable/bridge/ROM/manifest/save/output paths and `PYTHONPATH=src`. It copies
the ROM/save, runs a temporary loopback server/companion, and retains evidence.
`--scripted-start` adds ordinary timed Start/A inputs through native Continue;
it does not inject RAM, saves or states and does not test Windows keyboard
input. Close the game window normally. A pass only establishes this bounded
frontend/bridge proof. It does not qualify audio, gamepads, trade recovery,
Host/Join packaging or Internet connectivity.

`smoke_player_runtime.py` goes through the actual `PlayerRuntime.open()` gate
using a copied, closed consistent world backup and its private profile. It
creates a distinct proof bundle pin for the scripted inputs. It verifies the
current head before native launch, checks the exclusive lock while the core
runs, compares read-only native party Box CRCs after Continue, closes normally,
then checks that the lock is released and the canonical head/source hashes are
unchanged. The normal runtime bundle remains untouched. This is a development
lifecycle proof for an already enrolled character, not a Host/Join UI or
offline-play policy.

## Current source-launched GUI qualifiers

The October 9 visual/world amendment explicitly resumed isolated verification.
The tools below document bounded scenarios; each run needs fresh private outputs
and records its own pins and limits. Existing accepted artifacts stay unchanged.

Normal package builds now require the full production reset descriptor, the
isolated trade replay descriptor and pinned worker, and a reconstructing BPS.
`--development-preview` explicitly retains private preview mode without those
production gates. `--preflight-only` verifies inputs and reconstructs the patch
in memory without creating output or invoking PyInstaller; it still requires
the documented Windows builder environment. Neither mode proves gameplay.

The package builder also supports `--create-patch --base <path>
--base-sha256 <hash>` with its existing pinned game/runtime arguments. It creates
the installation BPS directly from the owner's raw GBA or bounded single-GBA ZIP,
checks the uncompressed source pin and exact
reconstructed release hash, and bundles only the patch. See
[patch creation](../../docs/release-patch-creation.md). The owner-supplied ZIP now
reconstructs the latest visual ROM exactly in a private BPS proof. That proof
does not exercise a packaged GUI import; existing packages remain unchanged.

These private tools require the existing qualified Windows Python environment,
explicit local artifact paths and their expected SHA-256 pins. Use a new private
output directory for each run. They copy source saves and append ordinary
joypad input/read-only diagnostics to a separate proof bundle; they do not
qualify physical keyboard/gamepad input or the packaged executable.

| Tool | Scope and evidence |
| --- | --- |
| `qualify_launcher_session.py --autosave` | Two real Host/Join sessions, the unchanged five-minute timer, independent off preference, manual checkpoints and exact fresh Continue. See [current timer evidence](../../docs/windows-controls-audit.md#timed-autosave-repeat-wqt2--complete-acceptance). |
| `qualify_admission_cleanup.py` | Actual native Challenge/Accept/Enter and the Tk **Cancel battle entry** action, neutral pre-BIND handoff, saving and fresh Continue. It uses an explicit proof preparation gate; see [scope and limits](../../docs/windows-admission-cleanup-proof.md). |
| `qualify_menu_battle.py` | Native menu entry through playable 1v1, a real second-slot switch, result/history, saver handoff, checkpoints and fresh Continue, using legitimate 2/1-member parties. See [passing run](../../docs/windows-menu-battle-proof.md). |
| `qualify_menu_multi.py` | Four real GUI workers, two native team invitations, all four consents/Enter, 2v2, result/history, saving and fresh Continue, using legitimate 2/1/1/1-member parties. Current acceptance is recorded in the [handoff report](../../PROJECT_STATUS_AND_HANDOFF.md). |

The menu qualifiers deliberately wait for **normal closure** at each
`ready_for_normal_close` event. Close only the reported test-owned native
windows, friends before host, within the printed phase's 120-second window.
The 2v2 event includes the exact reverse-player `close_order`. There are two
closure phases: after battle/save and after fresh Continue. A watchdog or forced
failure cleanup cannot earn acceptance. Preserve failed evidence and rerun in
a new directory after a justified correction; do not reinterpret partial
assertions as a passed scenario. The 2v2 envelope is 2,100 seconds, with a
2,220-second outer runner and an independent 2,340-second watchdog; native
request/RPC deadlines are not extended.
