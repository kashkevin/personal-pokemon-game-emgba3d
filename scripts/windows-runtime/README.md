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
   line. Keep its complete log. The executable is `build-windows/mgba-sdl.exe`.
5. Run `python3 collect_bundle.py --source /absolute/path/to/worktree
   --dependencies /absolute/private/dependency-cache --output
   /absolute/new/private/bundle`, with the options on one command line. The
   output must be new. Copy the whole resulting directory to private Windows
   storage without adding ROMs/saves.

The collection contains `runtime.json` in the `emerald-windows-runtime-v1`
format. Supply its SHA256 as the application pin to `RuntimeBundle`, rather
than trusting an arbitrary manifest beside an executable. The executable,
SDL2 DLL, Winpthreads DLL, Lua bridge template and retained material have
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
import libraries and frontend objects. The retained blip_buf LGPL notice and
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
