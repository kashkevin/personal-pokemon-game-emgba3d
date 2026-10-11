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
* **Result 2026-10-10, launcher migration** (`claude/native-pc` `4f4691e` plus these
  documents): 1388 tests collected, exit code 0 (no failures, no errors), about 9 min.
  With `-q` on the command line as well as in `pytest.ini` pytest prints no summary
  line; the exit code is the record (1374 tests at the run below).
* Result 2026-10-10 (`claude/native-pc`, after the native checkpoint proof):
  3638 test cases in the JUnit report (the same 1373 tests + 2264 subtests + 1 skipped
  as 2026-10-09), 0 failures, 0 errors, 8 min 55 s (game proofs ran at the same time).
  The `-q` summary line was not printed in this run; the JUnit report and exit code 0
  are the record. Earlier: 2026-10-09 (`2dac312`), 1373 passed, 1 skipped, 2264
  subtests passed, 7 min 42 s.

## 2. Native platform unit tests (engine repo)

```sh
make -f Makefile_pc NATIVE_LINUX=1 check-native
```

Minimal C harness (`tools/pc_port/tests/minitest.h`; a C++ framework such as Catch2
would add a toolchain for no benefit in a C engine). Covers ARM shift semantics,
the flash driver (program/verify/erase/bounds), the host RTC (BCD, locking), BIOS
helpers (`Div`, `BitUnPack`), GBA division-by-zero results, that `Random32`
matches the GBA SFC32 sequence, and that a runaway HBlank DMA is stopped while a
re-armed one keeps running (N25).
**Result 2026-10-09**: 1063 checks, 0 failures. **2026-10-10** (`claude/native-pc`
`1579e7fd8`, with the battle branch's crash fixes, XInput loaded at run time and the
save-command query): 1063 checks and the bridge's 4186 checks, 0 failures.

## 3. GBA/native byte-layout parity

```sh
make -f Makefile_pc NATIVE_LINUX=1 check-abi    # python3 tools/pc_port/abi_layout.py
```

Compiles a probe for the GBA, Linux i386 and Windows (MinGW, converted to ELF to
read its DWARF) and compares the layouts of save blocks, Pokémon, storage, battle
link packets, all companion mailboxes, and map/sound data built by assembler macros.
The Windows build needs `-mno-ms-bitfields -mno-align-double` (MinGW otherwise uses
the MSVC layout, which already fails the engine's own static asserts).
**Result 2026-10-09**: 172 types, all match, on both Linux and Windows; again on
2026-10-10 at `1579e7fd8`.

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
debug overlay (triangles, draw calls). The native clock is the local time, so a POSIX
`TZ` offset moves the time of day for a run (`TZ=XXX+9` with the workspace at 21:00
UTC gives midday); Wine follows it too.

| Check | Linux | Windows (Wine) |
| --- | --- | --- |
| Continue into the 3D overworld (Route 101 save, Pokémon Center save) | Pass | Pass (Pokémon Center save) |
| Route 101, Oldale Town, Littleroot Town, Oldale Pokémon Center 1F drawn in 3D | Pass (screenshots) | Oldale Town and Pokémon Center: pass |
| Walk, door warps, map connections, ledges in the 3D view | Pass | Door out: pass |
| Player, NPCs, follower, visible wild Pokémon drawn | Pass; follower refused during Poké Ball animation (V1) | Player and NPCs: pass |
| Wild battle started in the classic view, fled, 3D view afterwards | Pass | Not run |
| Wild battle started while the 3D view shows; flee returns to 3D | Pass | Not run |
| Clear-save screen (wait 15 s), NO, soft reset, Continue into 3D | Pass (after N25) | 2D build: pass; 3D build: Continue into 3D pass |
| Modelled buildings and furniture drawn (D4) | Pass: Littleroot, Oldale Town, Oldale Pokémon Center, a house | Pass: Oldale Town, Pokémon Center |
| Walker whole at the Center counter and PC, beside a wall; nurse behind the counter; walker behind a roof hidden by it | Pass (screenshots) | Counter: pass |
| Sun shadows by day outdoors, fainter at night, none indoors; a sprite darkens as a whole in a building's shadow | Pass (screenshots; midday via `TZ`) | Day outdoors and none indoors: pass |
| No model drawn past the edge of the scene | Pass (Oldale Town, after `65f44c42e`) | Not looked for |
| Frame rate (llvmpipe, standing still) | Route 101 3-6 fps; Oldale Town 7.1 fps (7.6 shadows off); Pokémon Center about 44 fps | Oldale Town about 5 fps |
| F7 camera framing and F8 tree style while playing; `pokeemerald.cfg` keeps them and the zoom steps; `PKMN_DIORAMA_CAMERA` overrides one run without writing the file | Pass (Route 104, graphics `8750fd07b`); since `graphics-wip-20261010-6` F7 switches the Adventure and Diorama cameras, see 7b | Not run |
| A dark cave needing Flash: dark but for the circle round the player; menus over the dark; normal maps unchanged | Pass (Granite Cave B1F, debug-menu test save, wide and 3DS camera; Route 104; graphics `3e39f2b15`) | Not run |
| Flash used in a dark cave: the circle opens, Flash's glow | Not run | Not run |

3D battles (engine branch `claude/battle-3d-integration`, `docs/battle-3d.md`), same
setup. `PKMN_DIORAMA_LOG=1` also logs each battle's stage choice with a map of the
ground round the player (`#` tall, `g` grass, `s` sand, `~` water, `.` plain).
Trainer, double and warp checks use a debug-menu test build: the same sources with
the expansion's overworld debug menu compiled in, for testing only (player builds
keep it off), built from the engine tree with

```sh
make -f Makefile_pc NATIVE_LINUX=1 DIORAMA=1 -j2 \
  OBJ_DIR=build/pc-linux-diorama-debugmenu TARGET=pokeemerald-mp-diorama-debugmenu \
  CC="gcc -DGUARD_CONFIG_DEBUG_H -DDEBUG_OVERWORLD_MENU=TRUE -DDEBUG_OVERWORLD_HELD_KEYS=R_BUTTON \
      -DDEBUG_OVERWORLD_TRIGGER_EVENT=pressedStartButton -DDEBUG_OVERWORLD_IN_MENU=TRUE \
      -DDEBUG_BATTLE_MENU=FALSE -DDEBUG_AI_DELAY_TIMER=FALSE -DDEBUG_POKEMON_SPRITE_VISUALIZER=FALSE"
```

(Windows: `make -f Makefile_pc DIORAMA=1 SDL_DIR=...` with `i686-w64-mingw32-gcc` and
the same flags.) DEBUG is then the start menu's first entry. Start debug trainer
battles (Trainers > Trainer 1, Double Battle, Try Battle) in a town: on a route a
visible wild Pokémon can wipe the trainer's party during the transition (KNOWN_ISSUES
N33).

| Check | Linux | Windows (Wine) |
| --- | --- | --- |
| Wild battle from the 3D view: transition over the 3D field, glide, intro, moves, damage, Bag, party, Run, field back in 3D | Pass | Pass (move, Poké Ball from the Bag, Run) |
| Catch (Bag and R quick-throw), Pokédex page, nickname declined | Pass | Ball thrown (broke free) |
| Shiny send-out; Mega Evolution in a single and a double battle | Pass | Not run |
| Trainer battles: rival May (win), Drake (to the end; and a loss with a level 2 Magikarp: blackout home in 3D), Kate & Joy double (Route 101, Oldale Town) with a Potion through the party menu | Pass | Not run |
| Terrain: grass, sand, water (surf), cave 1F, dark cave B1F, town, gym | Pass | Route 101 |
| Stage search keeps trees and buildings out of the battlers' way (stage map log; Kate & Joy on Route 101) | Pass after `b752d8e48` / `732fbef43` | Not run |
| Voxel and 3DS trees (F8), wide and 3DS camera (F7), dark cave | Pass | Voxel, wide |
| F4 to classic and back during a battle; into 3D mid-battle | Pass | Not run |
| Save on the field, reload, battle in 3D | Pass | Not run |
| 1920x1080 window (`windowScale=6`): layout, battle frame rate | Pass (60 game frames a second in the battle) | Not run |
| Multiplayer battles in 3D | Not run (C3) | Not run |

UBSan reports now come only from real findings; a false positive from the engine's
`if_comptime` trick is avoided in the sanitizer build (`NATIVE_SANITIZE`).
AddressSanitizer build (`make -f Makefile_pc NATIVE_LINUX=1 SANITIZE=address`,
game and renderer code): first pass on 2026-10-09 (title, continue, party, summary,
Bag, Pokédex, wild battle, run) found N22 and the benign N23 over-reads.

## 6. Multiplayer: native clients, harness and network simulation (Milestone C)

Native bridge unit tests run in `check-native` (engine
`tools/pc_port/tests/test_mp_bridge.c`, 4186 checks: the cases of the app's
`tests/test_mgba_bridge.lua` and `tests/native/windows-input-guard.c`, plus save
command/response, CRC, shared-world and capability checks, and the frame-rate cases
of engine `edb755a26`: a slow frame drains a 2 KiB backlog and the save command
behind it; with a clock the pose and shared-world record follow real time at 60 and
at 2.5 frames a second; without one, mgba.lua's 6-frame cadence).

Native presence proof (real native clients, real companions, real world server, no
ownership store), one X display per client:

```sh
# companion identity: the GBA ROM and manifest of the same engine source
make -j2 BUILD_NAME=dev                                       # engine
PYTHONPATH=src python scripts/multiplayer/generate_manifest.py --rom <engine>/pokedev.gba \
    --elf <engine>/pokedev.elf --engine-commit <sha> --output manifest.json
PYTHONPATH=src python scripts/multiplayer/native_presence_proof.py \
    --game <engine>/pokeemerald-mp --rom <engine>/pokedev.gba --manifest manifest.json \
    --save a.sav --save b.sav --display :98 --display :97 \
    --output <private>/multiplayer-proof/native-presence-N
# Windows clients under Wine: --game pokeemerald-mp.exe --wine PREFIX_A --wine PREFIX_B
# (one prefix per client; KNOWN_ISSUES M3)
# optional: --enter 1:Up (client 1 walks through a door and back out; Littleroot saves:
# the lab door), --rejoin 0 (client 0's companion restarted while its game runs)
# 3D build: --game pokeemerald-mp-diorama --hold 1.0 --slow 1.5
```

Results 2026-10-09 (engine `e2e3917e2`, `scripts/multiplayer/native-presence-evidence.json`):

| Run | Clients | Result |
| --- | --- | --- |
| native-presence-2 | 2 Linux, Route 101 | Pass: bridges authenticated, both joined, each sees the other in the overworld, A's two steps reach B |
| native-presence-wine-7 | 2 Windows (Wine), Littleroot | Pass (same checks; Winsock bridge) |
| native-presence-four-1 | 4 Linux, Littleroot and Oldale Pokémon Center | Pass: 4 sessions, each sees 3 others, A's move reaches B |
| native-presence-3d-1 | 2 Linux, 3D (Diorama) build, Oldale Pokémon Center | Pass: same checks; remote player and follower drawn in the 3D view |
| native-presence-5 | 2 Linux, Littleroot, engine `edb755a26` | Pass: same checks; B walked into the lab and back out, A saw both map changes; A's companion restarted, A's game reconnected by itself, both saw each other again |
| native-presence-four-2 | 4 Linux, Littleroot and Oldale Pokémon Center, `edb755a26` | Pass: same checks; all three others saw B's door map change both ways |
| native-presence-3d-3 | 2 Linux, 3D build (graphics `b02cf0e97`), outdoors in Littleroot, about 2.4 frames a second | Pass: same checks as native-presence-5 |
| native-presence-wine3d-1 | 2 Windows 3D build under Wine (the checkpoint's stripped exe), Littleroot | Pass: same checks; B's door map change seen both ways |
| native-presence-3d-5 | 2 Linux, 3D build (graphics `398d486ef`: doors open, the warp stays 3D) | Pass: same checks as native-presence-5; the door warp took about 35 s at 2.4 frames a second (native-presence-3d-4 had timed out at 30 s, KNOWN_ISSUES V7) |
| native-presence-wine3d-3 | 2 Windows 3D build under Wine, the stripped exe of checkpoint native-wip-20261010-2 (graphics `8920f1f67`: weather light, dapples, dust, rays, bloom) | Pass: same checks; B's door map change seen both ways. native-presence-wine3d-2 had timed out waiting 30 s for the others to see B back outside (the 3D door exit at about 2 frames a second); the two door waits are now 60 x `--slow` |

Earlier attempts that did not pass were harness problems, not bridge problems: a key
press before the window existed, wild battles on Route 101 under slow Wine clients,
and the shared Wine prefix (M3). native-presence-3d-2: a fixed 1 s key hold is 2-3 game frames
at 2.4 frames a second, enough to turn but not to step; the proofs now hold a key until
the pose moves.

Native live-checkpoint proof (real native clients, real companions, real world server
with the ownership store and player credentials):

```sh
PYTHONPATH=src python scripts/multiplayer/native_checkpoint_proof.py \
    --game <engine>/pokeemerald-mp --rom <engine>/pokedev.gba --manifest manifest.json \
    --save a.sav --save b.sav --display :98 --display :97 \
    --output <private>/multiplayer-proof/native-checkpoint-N
# Wine: --game pokeemerald-mp.exe --wine PREFIX_A --wine PREFIX_B
# 3D build: --game pokeemerald-mp-diorama --hold 1.0 --slow 1.5
# --recover: also apply A's canonical save to its running game (live recovery)
```

Two distinct legacy saves are provisioned on the host; each is enrolled through the
running game (revision 1); A walks and saves (revision 2: the canonical save holds the
position A's game reported); both games are closed (each game's own save file must hold
its canonical player state); both start again (Continue restores each saved position,
new leases and incarnations, the players see each other) and save against their last
revision (A 3, B 2); the host store's integrity check passes and the source saves are
unchanged. Every save byte goes through the ROM's save mailbox and 4 KiB save window.

Results 2026-10-09/10 (`scripts/multiplayer/native-checkpoint-evidence.json`):

| Run | Clients | Result |
| --- | --- | --- |
| native-checkpoint-1 | 2 Linux, Littleroot, engine `e2e3917e2` | Pass; 1.3-1.5 s per save; each game's file byte-identical to its canonical save |
| native-checkpoint-wine-1 | 2 Windows (Wine), `e2e3917e2` | Pass; 1.4-1.7 s per save |
| native-checkpoint-3d-1 | 2 Linux, 3D build (graphics `2c063c9a8`), 2.4 frames a second | Fail: a save-window command timed out during enrollment (KNOWN_ISSUES M4) |
| native-checkpoint-2 | 2 Linux, `edb755a26` | Pass; 1.4 s per save |
| native-checkpoint-3d-2 | 2 Linux, 3D build (graphics `b02cf0e97`) | Both enrollments passed (26-28 s each); then the harness's fixed key hold did not make A walk (fixed in the script) |
| native-checkpoint-3d-3 | 2 Linux, 3D build (graphics `b02cf0e97`), 2.4 frames a second | Pass; 26-31 s per save (KNOWN_ISSUES M5) |
| native-checkpoint-wine-2 | 2 Windows (Wine), `edb755a26` | Pass; 1.4-1.5 s per save |
| native-checkpoint-3 | 2 Linux, `edb755a26`, `--recover` | Pass; live recovery 36.9 s: A walked off its saved tile, the canonical save was applied to the running game and A stood on the saved tile again, same process and lease |
| native-checkpoint-wine-3 | 2 Windows (Wine), `edb755a26`, `--recover` | Pass; live recovery 49.8 s (the test suite ran at the same time) |
| native-checkpoint-3d-4 | 2 Linux, 3D build (graphics `0ab8ee710`), 2.4 frames a second, before the M5 fix | Pass; 32.0-37.7 s per save |
| native-checkpoint-3d-5 | 2 Linux, 3D build (graphics `2f150c4db`, M5 fix), `--recover` | Pass; 4.0-6.4 s per save; live recovery 69.3 s, same process and lease |
| native-checkpoint-wine3d-1 | 2 Windows 3D exe under Wine, the stripped exe of checkpoint native-wip-20261010-3 (graphics `3e39f2b15`), `--recover` | Pass; 4.2-6.5 s per save; live recovery 72.9 s |
| native-checkpoint-3d-6 | 2 Linux, 3D build (graphics `edd1f5105`: a save's commands no longer wait for slow drawing), `--recover`, the same software-OpenGL setup as -3d-5 | Pass; 1.6-1.9 s per save (enrollment 1.7-1.8 s); live recovery 42.5 s (KNOWN_ISSUES M5) |
| native-checkpoint-wine3d-2 | 2 Windows 3D exes under Wine, the stripped exe of checkpoint native-wip-20261010-4 as shipped (graphics `edd1f5105`, the launcher package's runtime), `--recover` | Pass; 1.7-2.0 s per save (4.2-6.5 s in wine3d-1); live recovery 43.5 s (72.9 s) |

Under Wine the games end by signal (exit code -15) and their saves are still
intact, since the native build writes the save file at the frame after every Flash
write.

Trades between native clients through the Players menu (native_trade_menu_proof.py on
the native build; the harness reads the games' memory at the unstripped Linux
executable's symbols only to see the menus and compare parties):

```sh
PYTHONPATH=src:scripts/multiplayer python scripts/multiplayer/native_trade_proof.py \
    --game ../engine/pokeemerald-mp --rom pokedev.gba --manifest manifest.json \
    --save a.sav --save b.sav --display :98 --display :97 \
    --output /private/multiplayer-proof/native-trade-N
```

| Run | Clients | Result |
| --- | --- | --- |
| native-trade-1..4 | 2 Linux, engine `9e1de660f` | Failed on the harness before the trade (this build's Player submenu has Style; the players list shows the friendship level; a Python error); each fixed in the script |
| native-trade-5 | 2 Linux, engine `9e1de660f` | Pass: both offers shown, one confirmation commits nothing, trade applied in both games (43 s from the first confirmation), ownership conserved, parties in memory equal the canonical saves, backing out aborts, restart keeps both (`native-trade-evidence.json`) |
| native-trade-wine-1 | 2 Windows 2D exes under Wine, one prefix each, engine `9e1de660f` | Pass: the same checks; 46.7 s from the first confirmation; 0.5 s key holds |

Windows clients: add `--wine PREFIX1 --wine PREFIX2 --sdl SDL2.dll --elf ../engine/pokeemerald-mp`
and give `--game` the Windows exe built from the same commit (symbol table kept). The
harness reads the games' memory at the exe's symbols (Wine maps it at its preferred
base; checked) with the sizes of the Linux build.

The launcher's player runtime with the native game (Milestone B3):

```sh
PYTHONPATH=src python scripts/multiplayer/native_launcher_proof.py \
    --game ../engine/pokeemerald-mp.exe --sdl SDL2.dll --rom pokedev.gba \
    --manifest manifest.json --save a.sav --display :98 --wine PREFIX \
    --output /private/multiplayer-proof/native-launcher-N
```

It collects a native runtime bundle, enrolls the player through a directly started
game, then lets `PlayerRuntime` (the launcher's own code) recover and start the
game, reach the overworld, save through it and close it; a bundle naming another
ROM build must be refused before any process starts
(`scripts/multiplayer/native-launcher-evidence.json`). `tests/test_native_runtime.py`
covers the bundle format, the bridge file and the arguments without a game.

| Run | Client | Result |
| --- | --- | --- |
| native-launcher-1..3 | Windows 2D exe under Wine | Failed on the harness (no SDL2.dll beside the directly started game; started before the companion's new lease; a store without trades); each fixed in the script |
| native-launcher-4 | Windows 2D exe under Wine, engine `9e1de660f` | Pass: arguments `--save --bridge --config`, canonical save installed, overworld at the canonical position, live checkpoint 1.4 s, lease released, settings file kept, other-ROM bundle refused |

The whole launcher with native games: host and friend battle 1v1 from the Players
menu (the Windows qualifier `qualify_menu_battle.py` on the native build). The real
`LauncherWindow`, `SessionWorker` and `LauncherSession` start the games from a native
runtime bundle; on Linux the bundle holds the Linux executable under its `.exe` name
with a placeholder SDL2.dll. Each player's games open on their own X display. The
harness reads the games' menus, tasks and parties at the unstripped executable's
symbols (never writes them) and needs the genuine two- and one-Pokémon sources.

```sh
PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime \
  python scripts/multiplayer/native_launcher_battle_proof.py \
    --game ../engine/pokeemerald-mp --rom pokedev.gba --manifest manifest.json \
    --source-a a.sav --source-b b.sav --display :98 --display :97 \
    --output /private/multiplayer-proof/native-launcher-battle-N
```

| Run | Clients | Result |
| --- | --- | --- |
| native-launcher-battle-1 | 2 Linux, engine `9e1de660f` | Pass in 8 min 11 s: enrollment through bootstrap games, Challenge 1v1 / Accept / Enter battle through the Players menu, 362 routed blocks with the forced switch (as the emulator qualifier wqb1), the same durable result for both (the friend won), full parties restored in memory, Recent battle results on both games, manual saves (revision 2), normal close (exit 0), fresh Continue onto the same checkpoints; 632 key presses, no forced cleanup (`native-launcher-battle-evidence.json`) |
| native-launcher-battle-2 | 2 Linux, engine `9e1de660f`, harness with `--wine` support | Pass: the same checks, 362 blocks, the same result (8 min 28 s) |
| native-launcher-battle-wine-1 | 2 Windows 2D exes under Wine, one prefix each, engine `9e1de660f` | Pass in 9 min 5 s: the same checks, the same 362 blocks, forced switch and result; games closed with Alt+F4 (exit 0); enrollment's bootstrap games ended by the launcher's terminate (-15 under Wine); 478 key presses at 0.5 s holds |

Windows clients: add `--wine PREFIX1 --wine PREFIX2 --sdl SDL2.dll --elf ../engine/pokeemerald-mp`
with `--game` the Windows exe of the same commit. The bundle then holds the exe and
its SDL2.dll, the launcher's spawn is prefixed with `wine`, and a normal close is
Alt+F4.

Disconnect and reconnect through the launcher (the owner's rule: if the host is lost,
everyone saves and disconnects), on the same harness:

```sh
PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime \
  python scripts/multiplayer/native_launcher_reconnect_proof.py \
    --game ../engine/pokeemerald-mp --rom pokedev.gba --manifest manifest.json \
    --source-a a.sav --source-b b.sav --display :98 --display :97 \
    --output /private/multiplayer-proof/native-launcher-reconnect-N
# Windows clients: the same --wine/--sdl/--elf arguments as the battle proof
```

Both players Continue into Littleroot and see each other, walk two steps and save
(revision 2); the friend walks two more steps without saving; the host's game closes
normally, which ends the host's session and world server; the friend's launcher must
keep the running game's unsaved progress locally (`host_loss_preserved`,
`pending-emergency.json` and `pending-export.json`, closing allowed); the friend
closes; the host starts again (revision 2) and the friend joins again: its kept
progress becomes revision 3 and the game must continue on the tile where it stood;
both see each other, save (host 3, friend 4) and close; the host store's integrity
check passes (`scripts/multiplayer/native-launcher-reconnect-evidence.json`).

| Run | Clients | Result |
| --- | --- | --- |
| native-launcher-reconnect-1 | 2 Linux, engine `34ddb17a6` | Pass in 4.7 min: progress kept 1.5 s after the host closed; the friend rejoined at revision 3 on its unsaved tile; both saved again (3, 4); every game closed normally (exit 0); 30 key presses |
| native-launcher-reconnect-wine-1 | 2 Windows 2D exes under Wine | Failed on the harness after both saved: the game's one-time style hint banner (after 12 s in the field) kept the field busy and the walk refused to start. Fixed: the harness waits for the field before every step |
| native-launcher-reconnect-wine-2 | 2 Windows 2D exes under Wine, `34ddb17a6` | Pass in 5.2 min: the same checks; progress kept 4.0 s after the host closed; Alt+F4 closes (exit 0) |

Not covered: a network drop while the host keeps running (the companion does not
reconnect by itself after a loss; the player closes the game and joins again, as the
launcher says), a host loss during a battle or a trade, the 3D build, separate PCs.

Four players, 2v2 with full parties (`native_launcher_multi_proof.py`: `--source` and
`--display` four times each, `--match-seconds 12000`): each source walks out of
Route 101's grass into Littleroot and is enrolled; four launchers start their games;
two duos form from the Players menu; the host challenges, the three others accept,
all four enter; default moves and forced switches to the end; the same durable
result for all four, full parties back, result screens, saves, normal close, fresh
Continue (`scripts/multiplayer/native-launcher-multi-evidence.json`).

| Run | Clients | Result |
| --- | --- | --- |
| native-launcher-multi-1..9 | 4 Linux | Failed on the harness (timeouts, walks out of the grass, CPU with four games on two cores, a busy field during an enrollment walk) or on KNOWN_ISSUES M6 (fixed); multi-8 was stopped on purpose at 351 blocks with no failure |
| native-launcher-multi-10 | 4 Linux, engine `1579e7fd8` | Pass in 152 min: 5545 routed blocks in 8391.6 s, seventeen party selections (three trainers sent out their sixth Pokemon, the host its second), team 1 won for all four, results screens, revision 2 for all four, normal close (exit 0 x4) twice, fresh Continue; 48316 key presses, no forced cleanup |

The Windows launcher package with a native runtime (no Windows computer here, so
under Wine with a Windows Python; `docs/dependency-ledger.md` lists the exact
Python and wheels):

```sh
# one-time: a 64-bit Wine prefix with python-build-standalone 3.14.0 (Windows) and the
# pinned wheels of requirements-launcher-build.txt + requirements-host-provisioning.txt
WINEPREFIX=<prefix> wine <python>/python.exe scripts/windows-runtime/build_launcher.py \
    --rom pokedev.gba --manifest manifest.json --runtime <native runtime dir> \
    --rom-sha256 <sha> --manifest-sha256 <sha> --runtime-sha256 <sha> \
    --version "Native 3D preview 1" --development-preview \
    --output <private>/launcher-build < /dev/null 2>&1 | cat > build.log
```

Windows Python under Wine needs its input from /dev/null and its output piped
(redirecting it to a file gives "invalid handle"). A native runtime is accepted only
for a `--development-preview` package, and its QUICK-START.txt then lists the native
game's keys. Result 2026-10-10: built (PyInstaller 6.22.3), package audit passed, no
mGBA or Lua file in the package (its only executables: `EmeraldTogether.exe` and the
game); `EmeraldTogether.exe` started under Wine (its output piped, as above: a file
redirect stops the frozen Python with "can't initialize sys standard streams") and
"Check installed game files" accepted the native runtime, manifest and game file. Not
run: the package played through, real Windows.

`tests/test_scripts_compile.py` compiles every `scripts/**/*.py` (a syntax error in
`build_launcher.py` once reached a commit because no test imported it).

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
weather, UI overlay, rules) and, since graphics `graphics-wip-20261010-6`, the
overworld camera's (`tests/diorama/test_camera.c`, 403 checks), compares the C metatile compositor with the Python one
on all 18,318 logical metatiles of the 75 Emerald tilesets, validates the rule
sources and checks the generated tables are current. Result 2026-10-09: pass (again
after the D4 buildings, shadows and sprite-occlusion work); 2026-10-10: pass after the
weather light (graphics `23ad56924`) and after the dapples, dust, rays and bloom
(`8920f1f67`); again after the F7/F8 switches (`8750fd07b`) and the dark caves'
light (`3e39f2b15`); again at `edd1f5105` (the camera and tree defaults, the crash
fixes and XInput from `claude/native-pc`, the save pacing); again at
`graphics-wip-20261010-6` (cameras, 49 x 49 scene, edge fog; 11 programs).

Light checks done by hand (screenshots, 2026-10-10): `PKMN_DIORAMA_LIGHT=0` against
the default in the Oldale Pokemon Center must be pixel-identical (it was: 0 pixels
differ); in Littleroot by day the light's per-pixel ratio stays within the weather's
dapple range (0.94-1.07 for `WEATHER_SUNNY`); `PKMN_DIORAMA_AIR=0` against the default
brightens only the scene's top left (rays, +3.8 levels) and never the dark past the
scene's cells (0).
`check-diorama-tools`: 8 pass; `test_rules_parity` fails here and upstream
(KNOWN_ISSUES V2); `test_compile_rules` (about 9 minutes, 3.3 GB RAM; run it alone)
runs 23 tests, one fails (KNOWN_ISSUES V4).

Benchmark (since graphics `graphics-wip-20261010-5`): `pokeemerald-mp-diorama --save
<outdoor save> --benchmark [seconds]` boots and Continues by itself, then measures the
3D view at 1280x720, 1920x1080, 2560x1440 and 3840x2160 (VSync off, the player's
quality, 3 s warm-up, 15 s each by default) and writes `benchmark.log` (average fps,
1% low, median/99th/worst frame time, 3D frame count, GPU, CPU, RAM, display). Pass
when every measured frame is 3D. Real hardware numbers only from the owner's PC; the
cloud computer's are labelled software (llvmpipe). `PKMN_PERF_LOG=1` still logs frame
rates every 5 s. RenderDoc capture is set up once a real GPU run is available.

### 7a. Resolution and display (graphics `graphics-wip-20261010-5`)

Unit: `make -f Makefile_pc NATIVE_LINUX=1 check-native` builds and runs
`tools/pc_port/tests/test_display_settings.c` (139 checks: resolutions, modes,
presets, settings file keys and older files, window fitting, pixel scales, the F10
menu's confirmation, the benchmark's boot and statistics). Launcher: `pytest
tests/test_game_display_settings.py tests/test_launcher_gui.py`.

By hand (Xvfb, `xdotool`; openbox for the fullscreen kinds; then the Windows exe
under Wine), each with a copy of an outdoor save:

1. A fresh folder starts windowed at 1920x1080 (or the largest 16:9 window the
   display fits, logged).
2. F10 opens the menu (sharp at a whole scale); Left/Right on Resolution shows the
   new size with the keep/undo box; Esc and the 15 s timeout undo it; Enter keeps it
   and `pokeemerald.cfg` gets `resolution=`. No `windowScale=` unless kept.
3. Display mode: borderless and exclusive fullscreen under a window manager; F11.
4. Pixel art: the 240x160 picture at 4x/6x/8x/12x (whole steps; check edges with
   `convert` crops).
5. Show frame rate: the corner readout; kept in the settings file.
6. `--benchmark 5`: `benchmark.log` with every frame 3D.
7. Regression: `native_checkpoint_proof.py --slow 1.5 --recover` with the 3D build.
8. 3D battles (only with the battle branch merged or on a trial merge): walk into
   the wild Pokemon of `battle-test.sav` at 1280x720, 1920x1080, 2560x1440 and
   3840x2160; world, sprites, health box and text box aligned.

Result 2026-10-10: all pass (Linux and Wine for 1, 2, 5, 6; Linux for 3, 4, 7, 8).
Not testable here: Windows display scaling and several displays (KNOWN_ISSUES V21).

### 7b. Cameras, photo mode and the scene's edge (graphics `graphics-wip-20261010-6`)

Unit: `check-diorama` runs `tests/diorama/test_camera.c` (403 checks: each framing
against the shaders' projection, the modes' zoom and tilt limits, steps kept per
camera, the follow at 30 and 144 frames a second, look-ahead, warps, map crossings,
the ground's height, photo mode). `check-native` runs
`tools/pc_port/tests/test_png_write.c` (176 checks) and `check_png.py`, which decodes
its nine pictures with Python's zlib and compares every pixel.

By hand (Xvfb 4096x2304, 1920x1080 window; `capture-modes.sh` in the session's
scratch folder; then the Windows exe under Wine), with copies of the scene saves
(Route 101, Petalburg Woods, Rustboro City, Oldale Town):

1. Continue: the Adventure camera, the player in the middle, no black anywhere.
2. F7: the Diorama camera; the picture's edges fade into the sky's colour, no
   black; F7 again: Adventure.
3. F9: photo mode, the map name and text boxes hidden, the keys along the bottom;
   `-` `-` `-` `.` and arrows: zoomed out, steeper, moved; the game stands still.
4. F12: a message box names `screenshots/emerald-<date>-<time>.png`; the file opens
   (Python zlib), is the window's size and shows the frame without the hints.
5. Esc: back to the Adventure camera, the game running.
6. Petalburg Woods is drawn in 3D (not the 2D view).
7. Regression: `native_checkpoint_proof.py --slow 1.5 --recover` with the 3D build;
   `--benchmark 5` with the resolution test save (compare with 7a).

Result 2026-10-10: Linux pass for 1-7 (benchmark: 720p 6.6, 1080p 4.4, 1440p 3.1,
4K 1.6 fps, software; KNOWN_ISSUES V25); Wine (the Windows exe, Route 101): pass for 1-5 (Wine's clock gave evening light: the edge fog took the dusk colour; the F12 file decoded, the message box had gone by the capture 6 s later). Seen wrong: Petalburg
Woods' raised band (V23); the player hidden behind Birch's lab (V24, not new).

### 7c. Neighbours, silhouettes, weathers, distant scenery (graphics `graphics-wip-20261010-7`)

Unit (`check-diorama`, 13 programs): `test_metatile_atlas` (atlas slots of the
neighbour pages, page art and palettes, a page's dirty tiles, the palette mapping
for identity, black, a night tint, a fade to white, a contrast colour map, light
colours left out, interpolation and extrapolation), `test_weather` (every weather
has a 3D look), `test_tree_sprites` (the woods' `0x1F2`/`0x1F3`), `test_far_field`
(columns, mesh, seams with the scene's cells, sectors and their bounds, the rules'
static heights).

By hand (Xvfb 4096x2304, 1920x1080 window; scripts `scene-env.sh`, `walk-cross.sh`,
`photo-env.sh`, `wine-compare.sh` in the session's scratch folder), with copies of
scene saves made by `place_save.py`:

1. Neighbours: Slateport (18,4), Rustboro (21,4), Route 118 (58,3), Verdanturf
   (8,4) and Lilycove (75,15), Adventure and Diorama cameras, each with
   `PKMN_DIORAMA_NEIGHBOURS=0` (before) and without (after): the next map is drawn
   with its own tiles, hills and buildings instead of border tiles.
2. A crossing: from Slateport (18,4) hold Up into Route 110 with
   `PKMN_DIORAMA_LOG=1`: the log says "camera carried across from map 0.1 to 0.25",
   the pages swap (Slateport becomes a page), the pictures show no jump.
3. Silhouette: Littleroot, just north of Birch's lab: the player's blue outline
   through the roof (Adventure and Diorama), none in photo mode.
4. Woods: Petalburg Woods south east of the north gate: the 3DS crowns whole.
5. Weathers: Route 124 under water (bubbles), the Route 111 desert (sandstorm);
   `PKMN_DIORAMA_WEATHER=4` (snow), `8` (sandstorm), `13` (downpour), `5`
   (thunderstorm), `14` (bubbles) previews on a route.
6. Distant scenery: Route 101 and Slateport, Diorama camera and photo mode zoomed
   out (`-` eight times, `,` three times), with `PKMN_DIORAMA_FAR=0` (before) and
   without: the world goes on past the cells into the haze; nothing missing at the
   seam with the scene.
7. Benchmark: `--benchmark 5` with the resolution test save, Adventure and Diorama
   cameras, with and without `PKMN_DIORAMA_FAR=0` (the distant scenery must cost
   nothing measurable in the Adventure camera).
8. Before/after under Wine: the checkpoint -6 exe and the new one in Littleroot,
   Oldale, Rustboro, Route 101, Petalburg Woods, Granite Cave 1F and Dewford,
   Adventure and Diorama cameras.
9. Regression: `native_checkpoint_proof.py --slow 1.5 --recover` with the 3D build.

### 7d. World details, every building, lamps and lit windows (graphics `graphics-wip-20261010-8`)

Unit: `check-diorama` (13 test programs and the compositor goldens; `test_props`: the catalogue, art composition,
every form's build, lamp heads on their posts, north-south fences, the ground
under props, wind in each weather, rustle where someone stands, cells a model
owns left to it), `check-native` (`test_display_settings`: the World details key,
presets, the F10 row), `tools/diorama_buildings/test_window_glow.py` (panes, the
wall's own blue, stripes, roofs, glazing bars, runs and brightness) and
`test_auto_buildings.py` (Lilycove's houses and department store, no overlaps,
the woods' way in, Sootopolis, two houses side by side, the eave search); the
generator's `--verify` (every model, the seventy new ones included, reproduces its
drawing in the GBA projection); launcher `tests/test_game_display_settings.py`.

By hand (Xvfb, scripts `scene-env.sh`, `place-env.sh`, `door-test.sh`,
`menu-test.sh` in the session's scratch folder):

1. Props, both cameras: Route 101, Oldale, Littleroot, Rustboro (day and night),
   Petalburg Woods, Granite Cave, Dewford, Slateport (centre and market),
   Mauville, Lilycove, Mossdeep, Lavaridge, Fallarbor, Petalburg; against
   `PKMN_DIORAMA_PROPS=0`.
2. Wind and rustle: Route 101 with `PKMN_DIORAMA_WEATHER=13` (downpour).
3. Lamps and windows: Rustboro, Littleroot, Oldale, Lilycove, Mauville with the
   test saves' clock (`TZ=UTC` night, `TZ=UTC+3` evening, `TZ=UTC+8` day).
4. Buildings: Lilycove, Slateport, Mauville, Fortree, Mossdeep, Dewford (scene
   saves), Pacifidlog and the Battle Frontier (placed saves), Adventure and
   Diorama cameras; a door: Lilycove house (36,7), hold Up: the door opens on the
   model and the player walks in.
5. F10 > World details Off: the grass and signs lie flat, the terrain redraws,
   `details=0` and `quality=custom` in `pokeemerald.cfg`.
6. Benchmark: `--benchmark 5` from the Lilycove save with checkpoint -7's binary,
   this one, and this one with `PKMN_DIORAMA_PROPS=0`.
7. Before/after (Linux and Wine): the checkpoint -7 build and this one in the seven
   places of 7c, plus Lilycove, Slateport and Mauville on Linux (Lilycove under
   Wine), Adventure and Diorama (`ckpt8-verify.sh`). Look at the new buildings'
   roofs from the Diorama camera: one roof each, no eave repeated behind it.
8. Lamps and windows under Wine: Rustboro and Lilycove with a POSIX-style `TZ`
   (`EST5EDT`; Wine's C library takes a zone name like `America/New_York` as UTC)
   at an hour that is evening or night in the test saves.
9. Regression: `native_checkpoint_proof.py --slow 1.5 --recover` with the 3D build.

## 8. CI

Workflow files exist (`engine/.github/workflows/native-pc.yml`,
`.github/workflows/python-tests.yml`) but **have never run**: neither repository is
hosted on GitHub. They build/test only and never upload build outputs (they contain
game assets).
