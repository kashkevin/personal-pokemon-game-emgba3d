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

Compiles a probe for both targets and compares DWARF layouts of save blocks,
Pokémon, storage, battle link packets, all companion mailboxes, and map/sound data
built by assembler macros. **Result 2026-10-09**: 172 types, all match.

## 4. Game mechanics (expansion test suite)

`make check` builds the expansion's test ROM and runs it headless in the bundled
`tools/mgba/mgba-rom-test` (battle mechanics, Gen rules, Mega Evolution, abilities,
items). It runs the GBA build, which shares all game logic with the native build.
**Not run yet in this session** (scheduled for Milestone B).

## 5. Native gameplay checks (manual/scripted, Linux under Xvfb)

```sh
PKMN_NULL_TRAP=1 ./pokeemerald-mp --save test.sav          # logs NULL accesses to null_trap.log
UBSAN_OPTIONS=print_stacktrace=1 ./pokeemerald-mp-san --save test.sav   # UB reports
SDL_AUDIODRIVER=disk SDL_DISKAUDIOFILE=audio.raw ./pokeemerald-mp       # capture audio
```

Driven with `xdotool` key events (helper scripts in the session scratch area). Every
new native crash class found this way gets a source fix and a note in
`KNOWN_ISSUES.md`.

| Check | Status 2026-10-09 |
| --- | --- |
| Launch, intro, title, main menu | Done (Linux) |
| New game: Birch speech, gender, naming | Done; found and fixed NULL accesses and a shift-by-32 glyph bug |
| Overworld, movement, menus | Not yet |
| Save, quit, continue; load an emulator `.sav` | Not yet |
| Wild and trainer battles, Mega Evolution | Not yet |
| Windows `.exe` (Wine here, then the owner's PC) | Not yet |

## 6. Multiplayer harness and network simulation (planned, Milestone C)

A harness will start the real host plus N simulated clients (and later native game
clients) and run the scenarios in the toolkit directive (2 and 4 clients, movement,
map changes, teams, trades, 1v1/2v2 and concurrent battles, World Events, reconnect,
server shutdown, client crash, save restore). Network conditions (50/100/200 ms
latency, jitter, stalls, forced disconnects, duplicated/replayed requests) will be
simulated in-process with a TCP proxy, never by changing system networking. The
transport is TCP, so packet loss and reordering appear to the game as delay or a
dropped connection; those are the cases the proxy produces.

## 7. Graphics benchmark scene (planned, Milestone D)

Repeatable scene at 1920x1080 measuring average FPS, frame-time distribution, 1%
low, CPU frame time, GPU time where measurable, RAM, draw calls and entity counts.
Real hardware specs and measured numbers only; nothing is reported until it runs.
RenderDoc capture is set up once the Diorama renderer runs in this engine.

## 8. CI

Workflow files exist (`engine/.github/workflows/native-pc.yml`,
`.github/workflows/python-tests.yml`) but **have never run**: neither repository is
hosted on GitHub. They build/test only and never upload build outputs (they contain
game assets).
