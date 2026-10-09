# Test plan

How to run each test layer, what it proves, and the latest recorded result. Never
mark gameplay as working from compilation or fixtures alone; actual-game checks are
listed separately.

## 1. Python host and companion (app repo)

```sh
cd /home/claude/pokemon
DISPLAY=:99 /home/claude/venv312/bin/python -m pytest      # whole suite
/home/claude/venv312/bin/python -m pytest tests/test_world_server.py -k events   # subset
```

* Uses the private venv with the pinned, hashed `requirements-host-provisioning.txt`
  (cryptography) plus pytest 9.1.1 and pytest-timeout. `conftest.py` exports
  `PYTHONPATH` so tests that start real host/companion subprocesses work.
* Tkinter launcher tests need a display (`DISPLAY=:99` with Xvfb, or `xvfb-run`).
* Covers: protocol encoding, TLS transport, sessions and identity, presence,
  trading (offers, confirmation, effects, recovery), battles (admission,
  arbitration, journal, recovery), teams, world clock/events/claims, friendship and
  Lucky Trades, wagers, co-op Gyms, saves and checkpoints, local reset, launcher.
* **Result 2026-10-09** (`claude/native-pc`, app `2dac312` + docs): 1373 passed,
  1 skipped, 2264 subtests passed, 0 failed, 7 min 42 s.

## 2. Native platform unit tests (engine repo)

```sh
make -f Makefile_pc NATIVE_LINUX=1 check-native
```

Minimal C harness (`tools/pc_port/tests/minitest.h`; a C++ framework such as Catch2
would add a toolchain for no benefit in a C engine). Covers ARM shift semantics,
the flash driver (program/verify/erase/bounds), the host RTC (BCD, locking), BIOS
helpers (`Div`, `BitUnPack`), GBA division-by-zero results, and that `Random32`
matches the GBA SFC32 sequence.
**Result 2026-10-09**: 1057 checks, 0 failures.

## 3. GBA/native byte-layout parity

```sh
make -f Makefile_pc NATIVE_LINUX=1 check-abi    # python3 tools/pc_port/abi_layout.py
```

Compiles a probe for the GBA, Linux i386 and Windows (MinGW, converted to ELF to
read its DWARF) and compares the layouts of save blocks, Pokémon, storage, battle
link packets, all companion mailboxes, and map/sound data built by assembler macros.
The Windows build needs `-mno-ms-bitfields -mno-align-double` (MinGW otherwise uses
the MSVC layout, which already fails the engine's own static asserts).
**Result 2026-10-09**: 172 types, all match, on both Linux and Windows.

## 3a. Soft-reset memory layout

```sh
make -f Makefile_pc NATIVE_LINUX=1 check-game-sections   # Linux
make -f Makefile_pc SDL_DIR=... check-game-sections      # Windows
```

Fails if a game object keeps any writable section outside the memory that a soft
reset restores, if a preserved platform object is inside it, or if (by `nm` on the
linked program) a game global variable lies outside the restored range.
**Result 2026-10-09**: Linux 953 objects, 7 preserved, 518 globals checked, pass;
Windows 953 objects, 7 preserved, 521 globals checked, pass.

## 3b. Compressed graphics decode natively

```sh
make -f Makefile_pc NATIVE_LINUX=1 check-decompress
```

Runs every compressed graphic in `build/assets` (`.smol`, `.fastSmol`, `.smolTM`)
through the game's own decompressor inside the native binary, via both the WRAM and
VRAM entry points, and compares it byte for byte with the uncompressed file the GBA
build compressed it from (with an overrun guard).
**Result 2026-10-09 (Linux)**: 7469 assets, 0 failures (a deliberately wrong
reference is reported as a failure).

## 4. Game mechanics (expansion test suite)

`make check` builds the expansion's test ROM and runs it headless in the bundled
`tools/mgba/mgba-rom-test` (battle mechanics, Gen rules, Mega Evolution, abilities,
items). It runs the GBA build, which shares all game logic with the native build.
**Not run yet in this session** (scheduled for Milestone B).

## 5. Native gameplay checks (scripted, Linux under Xvfb and Windows under Wine)

```sh
PKMN_NULL_TRAP=1 ./pokeemerald-mp --save test.sav          # logs NULL accesses to null_trap.log
UBSAN_OPTIONS=print_stacktrace=1 ./pokeemerald-mp-san --save test.sav   # UB reports
ASAN_OPTIONS=halt_on_error=0:detect_leaks=0:log_path=asan.log ./pokeemerald-mp-asan --save test.sav  # out-of-range access
SDL_AUDIODRIVER=disk SDL_DISKAUDIOFILE=audio.raw ./pokeemerald-mp       # capture audio
WINEDEBUG=-all wine pokeemerald-mp.exe --save test.sav     # Windows build (SDL2.dll beside it)
```

Driven with `xdotool` key events and screenshots (helper scripts in the session
scratch area; under Wine the window must be given focus first). Emulator saves are
always copies of the staged read-only inputs. Every new native crash class found this
way gets a source fix and a row in `KNOWN_ISSUES.md`. A crash writes `crash.log`.

| Check | Linux | Windows (Wine) |
| --- | --- | --- |
| Launch, intro, title, main menu | Pass | Pass |
| New game: Birch speech, gender, naming, into the truck | Pass (after N9, N10) | Pass |
| Overworld, movement, start menu | Pass | Pass |
| Party menu, summary pages, Bag pockets, Pokédex (list, entry, area, cry, size) | Pass under UBSan (after N13-N16) | Not run |
| Save, quit, continue | Pass | Pass |
| Emulator `.sav` (mGBA) loads; native save over a copy reloads | Pass | Load and play: pass |
| Wild battle: Fight, Bag, switch, Run, win | Pass | Fight and win: pass |
| Soft reset (clear-save screen, answer NO) | Pass; save unchanged | Pass; save unchanged |
| Pokémon Center: enter, nurse heals, save, leave, re-enter | Pass (after N24) | Pass (after N24) |
| Trainer battle, Mega Evolution, evolution, PC storage | Not run | Not run |
| Controller, real audio device, owner's PC | Not run | Not run |

Diorama 3D build (`pokeemerald-mp-diorama`, graphics branch), software OpenGL in the
cloud workspace; `PKMN_DIORAMA_LOG=1` logs sprites the 3D view refuses,
`PKMN_PERF_LOG=1` logs frame rates; F4 switches 3D/classic, F3 shows the terrain
debug overlay (triangles, draw calls).

| Check | Linux | Windows (Wine) |
| --- | --- | --- |
| Continue into the 3D overworld (Route 101 save, Pokémon Center save) | Pass | Pass (Pokémon Center save) |
| Route 101, Oldale Town, Littleroot Town, Oldale Pokémon Center 1F drawn in 3D | Pass (screenshots) | Oldale Town and Pokémon Center: pass |
| Walk, door warps, map connections, ledges in the 3D view | Pass | Door out: pass |
| Player, NPCs, follower, visible wild Pokémon drawn | Pass; follower refused during Poké Ball animation (V1) | Player and NPCs: pass |
| Wild battle started in the classic view, fled, 3D view afterwards | Pass | Not run |
| Wild battle started while the 3D view shows | Not run | Not run |
| Frame rate | 3-6 fps outdoors, 40-60 fps indoors (llvmpipe) | Not measured |

UBSan reports now come only from real findings; a false positive from the engine's
`if_comptime` trick is avoided in the sanitizer build (`NATIVE_SANITIZE`).
AddressSanitizer build (`make -f Makefile_pc NATIVE_LINUX=1 SANITIZE=address`,
game and renderer code): first pass on 2026-10-09 (title, continue, party, summary,
Bag, Pokédex, wild battle, run) found N22 and the benign N23 over-reads.

## 6. Multiplayer harness and network simulation (planned, Milestone C)

A harness will start the real host plus N simulated clients (and later native game
clients) and run the scenarios in the toolkit directive (2 and 4 clients, movement,
map changes, teams, trades, 1v1/2v2 and concurrent battles, World Events, reconnect,
server shutdown, client crash, save restore). Network conditions (50/100/200 ms
latency, jitter, stalls, forced disconnects, duplicated/replayed requests) will be
simulated in-process with a TCP proxy, never by changing system networking. The
transport is TCP, so packet loss and reordering appear to the game as delay or a
dropped connection; those are the cases the proxy produces.

## 7. Graphics: renderer tests and benchmark scene (Milestone D)

Renderer unit tests (graphics branch, needs a `DIORAMA=1` build first so the
generated tables exist):

```sh
make -f Makefile_pc NATIVE_LINUX=1 DIORAMA=1 check-diorama        # ~1 min after the first build
make -f Makefile_pc NATIVE_LINUX=1 DIORAMA=1 check-diorama-tools  # slow; needs >3 GB free RAM
```

`check-diorama` runs the voxel project's 10 C test programs (snapshot exchange, map
connections, presentation transition, metatile atlas, terrain mesh, sprite frames,
weather, UI overlay, rules), compares the C metatile compositor with the Python one
on all 18,318 logical metatiles of the 75 Emerald tilesets, validates the rule
sources and checks the generated tables are current. Result 2026-10-09: pass.
`check-diorama-tools`: 8 pass; `test_rules_parity` fails here and upstream
(KNOWN_ISSUES V2); `test_compile_rules` was killed for lack of memory when run
alongside other jobs (rerun alone).

Benchmark scene (planned): repeatable scene at 1920x1080 measuring average FPS,
frame-time distribution, 1% low, CPU frame time, GPU time where measurable, RAM, draw
calls and entity counts. Real hardware specs and measured numbers only; nothing is
reported until it runs. RenderDoc capture is set up once the renderer is stable.
`PKMN_PERF_LOG=1` (frame rates every 5 s) is the first piece.

## 8. CI

Workflow files exist (`engine/.github/workflows/native-pc.yml`,
`.github/workflows/python-tests.yml`) but **have never run**: neither repository is
hosted on GitHub. They build/test only and never upload build outputs (they contain
game assets).
