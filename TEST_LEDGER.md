# Test-results ledger

The owner's rule (2026-10-14): do not rerun a test that already passed on the same relevant code
unless something it depends on changed. This ledger records the last result of every test for
the current game, so each session can decide what to reuse and what to run. How each test is run
is in `TEST_PLAN.md`; problems are in `KNOWN_ISSUES.md`.

**Reuse a result** (mark it `PREVIOUSLY PASSED - EVIDENCE REUSED`) only when it ran on the same
relevant code and configuration, its evidence is on disk, and nothing it depends on (code,
data, dependencies, environment) changed since. Never present a reused result as a new run.
**Rerun** after a change to the code the test covers, a merge that brings in another branch's
changes to it, or a failure. Before an expensive run (the GBA suite: about 20-30 minutes; a
launcher proof: 5-20 minutes), write down why, whether it already ran, and what changed.

Environments: **L** cloud Linux (software OpenGL), **W** the Windows exe under Wine in the cloud,
**PC** the owner's Windows PC. Nothing has run on PC hardware except file checks.

## Update 31 (cloud, app `claude/dev-update31-rival` on U28 `a912f07`; engine not accessible)

| Test | Build / head | Where | Last result | Evidence | Changed since | Rerun? |
| --- | --- | --- | --- | --- | --- | --- |
| App suite, untouched U28 baseline (`pytest`, Python 3.12 + tkinter, xvfb) | app `a912f07` | L | 1827 passed, 4 failed (pre-existing U31-1), 50 skipped (Lua 5.3 subtests, private paths) | session log | - | Reuse as the baseline |
| App suite with Update 31 | app `claude/dev-update31-rival` | L | 1924 passed (97 new), 4 failed (the same pre-existing U31-1), 51 skipped (+1: engine re-derivation, passes with a checkout) | session log | - | Rerun after merging U29/U30 |
| `check_rival_catalogue.py --engine` on upstream expansion 1.17.1 | `bb1093a7c` | L | OK (5 checkpoints, intro table constants) | `docs/update31-rival-checkpoints.md` | - | **Run against the private engine** |
| Rival checkpoints on real PCs | - | PC | Never run | `docs/windows-test-update31.md` | - | Owner |

## Update 31 engine session (cloud, engine `claude/dev-update31-rival-engine` on U30 `8b8bb92a`; app `claude/dev-update31-rival`)

| Test | Build / head | Where | Last result | Evidence | Changed since | Rerun? |
| --- | --- | --- | --- | --- | --- | --- |
| `check_rival_catalogue.py --engine` on the real engine | engine `8ea2b8c9` (U29), `8b8bb92a` (U30), U31 engine branch | L | OK on all three; on the ported engine also the environment enum index, the preparation tag, the checkpoint numbering and every rival script's multiplayer hook (a removed hook is reported) | session log | - | After engine map-script changes |
| `make -f Makefile_pc NATIVE_LINUX=1 check-rival` (`--selftest-rival`) | U31 engine branch | L | 24 checks, 0 failed | `build/pc-linux/selftest-rival.log` | - | After `multiplayer_rival.c` changes |
| `tools/pc_port/rival_check.py` (headless, real scripts, simulated host record) | U31 engine branch, Classic 2D build | L | 21 scenarios: 21 passed (the two intro scenarios after a test-side correction; see the ledger) | session log | - | After rival/intro changes |
| GBA ROM | U31 engine branch | L | `f214735b…3387` byte-identical; `check_gba_lines.py --base HEAD` 0 moved lines in 8 files | session log | - | Every engine change |
| MinGW (Windows) objects of every changed C file, Classic 2D and 3D flags | U31 engine branch | L | compile; no new warnings (3 pre-existing in `sdl2.c`) | session log | - | - |
| App `tests/test_rival_environment.py` | app `312518a` | L | 14 passed | session log | - | - |
| App focused battle + rival suites (23 files) | app `312518a`, engine checkout set | L | all passed (incl. the catalogue re-derivation against the ported engine) | session log | - | - |
| App suite, trial integration U29 + U30 + U31 | app `claude/integration-u29-u30-u31-app` | L | 2072 passed, 4 failed (U31-1 fixture only), 9 skipped (Lua 5.3 installed this session, so the Lua subtests ran) | session log | - | After the owner's integration decision |
| `test_save_compat.py` with the Update 14 fixture regenerated locally (not committed) | app `ad254d0` | L | 6 passed: the 4 baseline failures are the missing fixture only | session log | - | Once the fixture question is decided |
| Every other PC selftest target (`check-native` … `check-graphics-mode`, 27 targets) | engine `7140c6bc` | L | 0 failures (`check-species-data` after listing Update 31's six PORTABLE map-script hooks as reviewed exceptions, as Update 29 did; 1571 species fingerprints equal) | session log | - | - |
| Update 26 `first_battle_check` (3D), `battle_end_check --kind wild` / `--kind trainer` (3D) | engine `22ce029d` Linux 3D build | L | ok, ok, ok | session log | - | - |
| Update 29 `economy_check.py` (3D + Classic 2D), Update 28 `dialogue_check.py` (boy, rescue; 3D + Classic 2D) | engine `22ce029d` | L | 0 failed; all ok (60/60 taps seen) | session log | - | - |
| Windows CI (`windows-package`) | - | W | Not run by this session (Actions not reachable) | - | - | **Owner / a session with Actions access** |

## Update 31 final integration (cloud; app `claude/integration-u31-final-app`, engine `claude/integration-u31-final-engine`)

| Test | Build / head | Where | Last result | Evidence | Changed since | Rerun? |
| --- | --- | --- | --- | --- | --- | --- |
| App suite (per-test timeout, real engine binary and checkout set) | app integration (workflow change excluded; code identical to the tested `6bdb0a5` apart from workflow YAML) | L | 2100 passed, 0 failed, 1 skipped (private save paths); was 2098/0/1 at `f70e315` | session log, junit | - | After code changes |
| App suite, Update 30 default + fixture fix | `3cf6a32` + `97e97a4` | L | 1975 passed, 0 failed, 8 skipped (7 shell-window tests then passed against the real U30 binary) | session log | - | - |
| `test_save_compat.py` (SQL fixture) | `claude/fix-compat-fixture` | L | 8 passed, 0 skipped; all 8 fail without the SQL; reproduction fails on a changed value | session log | - | - |
| Rival random walk soak (`RIVAL_SOAK_SEEDS=200 RIVAL_SOAK_STEPS=600`) | app integration | L | passed (77 s) | session log | - | - |
| Engine self-test targets (27) | engine integration | L | 0 failures (`check-rival` 26/0) | session log | - | After engine changes |
| `economy_check.py`, `dialogue_check.py` (3D + 2D) | engine integration | L | 0 failed; ok | session log | - | - |
| `rival_check.py` (25 scenarios) | engine integration | L / ASan | 25/25 native; 25/25 AddressSanitizer (only N23 and U31-10 reads) | session log | - | - |
| `save_safety_check.py` (12 checks) | engine integration | L | 12/12 | session log | - | - |
| 3D `first_battle_check`, `battle_end_check` wild / trainer | engine integration | L | ok / ok / ok | session log | - | - |
| Windows `.exe` under Wine 9.0: 17 self-test targets; `rival_check.py` | engine integration | W (Wine, cloud) | 0 failures; 25/25 and 9/9 on the final build | session log | - | - |
| GBA test ROM `make check` | engine integration | L | 6034 tests, 5532 passed, 39 failed = the 39 expected (0 new) | session log | - | After shared-code changes |
| Windows CI (`windows-package` full) | - | W | **Not run** (Actions unreachable from the session) | - | - | **Owner** |
| Windows CI (`windows-package` full), run 39013735925 | app `f70e315`, engine `e4252d4` | W (GitHub `windows-2022`) | Success as reported by the owner: package built, graphics check 16/16 (3D unsupported, Classic 2D supported), import disabled (no dump supplied), no sprite pack | owner's report (page not readable from the session) | one test, docs | After launcher/runtime/engine changes |
| Package inputs reproduced (manifest, `collect_native_bundle`, `audit_tree`, `build_launcher --preflight-only` without and with a stand-in base, importer end to end) | engine `e4252d4` build, app integration | L | all pass; BPS 33,554,461 bytes reconstructs `f214735b…3387` | session log, section 9 | - | - |
| `ci_graphics_check.py` on the Windows `.exe` | engine `e4252d4` | W (Wine 9.0, cloud) | 17/17 (3D forced unsupported), 12/12 (3D supported, llvmpipe) | session log | - | - |
| `ci_shell_check.py` | engine `e4252d4` | L (native Linux 3D + 2D) / Wine | Linux pass (both); Wine: keys/select/resize pass, picture black (U31-14) | session log | - | - |
| `tests/test_shell_game_files.py` | app integration | L | 2 passed | session log | - | - |
| `check-diorama` (renderer unit tests, compositor goldens 18,318 metatiles) | engine `e4252d4` | L | pass | session log | - | - |
| `check-diorama-tools` (each file run; `make` stops at the first failing file) | engine `e4252d4` | L | `test_compile_rules` 23/24 and `test_rules_parity` 0/1 = the known upstream V31 / V2 (same values); the other 12 files all pass | session log | - | Reuse (known failures) |
| `check-battlefx-bg` with the `BFX_TEST=1` build | engine `e4252d4` | L | 12 animations captured, 0 with a black block (without that build the check reports 0 captures and passes vacuously) | session log | - | - |
| `check-update26`: `battle_end_check` wild / trainer, `first_battle_check` | engine `e4252d4` (3D) | L | ok / ok / ok | session log | - | - |
| `party_menu_check.py` | engine `e4252d4`, AddressSanitizer 2D build | L | ok (entered, inspected, left twice; no memory error); the 3D ASan build was not made | session log | - | - |
| App suite after the merge (clean checkout of the merged default `662eccb`, engine default `e4252d4`, real binary and checkout set) | app default | L | 2100 passed, 0 failed, 1 skipped (private save paths); a first attempt lost its X server mid-run (11 Tk tests "couldn't connect to display"), rerun with a fresh Xvfb | junit | - | - |
| Engine after the merge: `check-abi`, `check-rival`, `check-rewards` | engine default `e4252d4` | L | OK (172 types); 26/0; 18/0 | session log | - | - |
| All tested binaries current with `e4252d4` | engine | L | `make -q` 0 for Linux 2D, 3D, ASan, Windows 2D, Windows 3D; GBA ROM `f214735b…3387` | session log | - | - |

## Real-PC gameplay repairs (2026-10-17; engine `claude/fix-windows-gameplay-engine`, app `claude/fix-windows-gameplay-app`)

`docs/windows-gameplay-repairs-20261017.md`. Environments as above; **W** here is Wine 9.0 with Mesa llvmpipe on Xvfb.

| Test | Build / head | Where | Last result | Evidence | Changed since | Rerun? |
| --- | --- | --- | --- | --- | --- | --- |
| `gameplay_repair_check.py` (fade at 21:00, battle grass, PC room, bag timing, link status x3, setup clock) | engine repair head | L | ok: 7 faded-out frames black, grass 0.7 %, room 0.7 %, pocket switch 2 frames, 3 link cases; fails on the pre-repair build | session log | - | - |
| `--selftest-catch-reconcile` case 7 (connected tick before the save exists) | engine repair head | L, W | 12 checks, 0 failed; without the guard: SIGSEGV | session log | - | - |
| `--selftest-rival` (Route 101 Zigzagoon +5) | engine repair head | L, W | 31/0 (L); exit 0 (W) | session log | - | - |
| Engine regression: builds 3D, 2D, ASan, BFX; GBA ROM; `check_gba_lines --base e4252d4 --changed` (4 files); `check-diorama` (`test_props` 7991); `first_battle_check`; `battle_end_check` wild, trainer; `rival_check`; `save_safety_check`; `bg_check`; party menu ASan; 28 self-test targets; economy and dialogue (2D) | engine repair head | L | all pass: builds ok; ROM `f214735b…3387`; 4 files, 0 moved lines; check-diorama ok (`test_props` 7991); first battle ok; battle end wild 22 / trainer 21 state changes ok; `rival_check` 25/25; `save_safety_check --app --load 3D` 11/11 (the U31 run also loaded with the Update 30 build: 12; without `--app` its validator case reports "no validator"); `bg_check` 12 animations, 0 black blocks; party menu ASan ok; 28 self-test targets exit 0 (`check-rival` 31/0, `check-catch-reconcile` 12/0, `check-clock` 58/0); economy 0 failed; dialogue ok | session log | - | - |
| GBA ROM sha256 | engine repair head | L | `f214735b…3387` (unchanged) | session log | - | - |
| Windows executables (mingw, 2D and 3D) under Wine: 21 self-test targets (2D) + rival, catch-reconcile (3D) | engine repair head | W | all exit 0 | session log | - | - |
| Character setup end to end (real Linux game, real app code: `create_world`, `create_character`, LauncherSession) | both repair heads | L | crash at boot before the engine fix; after: enrolled; with the enrollment game killed by SIGSEGV: `game_failed`, then "Continue" -> enrolled (attempt kept), then hosting: running, connected, is host, LINK HOSTING | `repro_resume.py` log | - | - |
| Resolution matrix: 1280x720, 1920x1080, 1024x768, 2560x1080, 1264x711, 3840x1080 x overworld, Pokemon Center, PC storage, wild battle, trainer battle; battle animation at 1280x720, 1920x1080, 1264x711 | Update 31 exe vs repair exe | W | before: plate missing at 1264x711 and 3840x1080, back pictures cut in mid-air at every size, PC room broken, grass striped; after: all fixed | `windows-gameplay-repairs-matrix/` (session outputs) | - | - |
| UI-ownership sweep (`PKMN_DIORAMA_UI_OWNER`): person, sign, item ball, nurse, PC + storage, mart, start menu, door, wild and trainer battle | engine repair head | L | no LEAK; transient game-window frames have 0 visible pixels | session log | - | - |
| App suite (`pytest tests`, real engine binary and checkout) | app repair head + engine repair head | L | 2109 passed, 0 failed, 1 skipped (private save paths), 2110 test cases | junit | - | - |
| Real PC: walk, doors at night, PC, battles at several window sizes, bag, hosting/joining LINK, a new world's setup at noon | - | PC | Never run | `docs/windows-gameplay-repairs-20261017.md` "Still to check" | - | Owner |

## Vehicles in 3D, the confirmed 12x clock, final integration (2026-10-18; engine `claude/fix-windows-gameplay-engine`, app `claude/fix-windows-gameplay-app`)

| Test | Build / head | Where | Last result | Evidence | Changed since | Rerun? |
| --- | --- | --- | --- | --- | --- | --- |
| `test_sprite_frame` composite vehicles (truck 48x48, S.S. Tidal 96x40, submarine 88x32, S.S. Anne 128x64 off-centre) | engine `cf7cba7676` | L | pass (in `check-diorama`, exit 0) | session log | - | - |
| `gameplay_repair_check.py` incl. 12 vehicle scenes (trucks; S.S. Tidal x3; submarine x2; Cable Car; Rayquaza x3; the submarine's escape to its end; the S.S. Tidal's departure to Lilycove) | engine `cf7cba7676` | L | ok: no object refused, 3D throughout (before the fix: truck, ferry, submarine "refused (unsupported sprite)", view 2D) | session log | - | - |
| Vehicles before/after (Update 31 exe vs repair exe) at 1280x720, 1920x1080, 2560x1080, borderless fullscreen 3840x2160 | Windows exes | W | before: refused, boxed 2D in every case; after: none refused, 3D | `vehicles-before-after.jpg` | - | - |
| Cable Car ride (Route 112 -> Mt. Chimney) | engine `cf7cba7676` | L | the cutscene plays, arrival scene, `VAR_CABLE_CAR_STATION_STATE` 1 -> 0, the station in 3D again | session log | - | - |
| Clock: `test_shared_world` (simulated whole day from noon at 12x, hours in order; damaged data repaired, valid kept; pause; restart), `test_world_companion` (both players get the host's time) | app `70536a5` | L | pass | junit | - | - |
| Clock end to end: new world, character setup, hosting (real Linux game, app code) | both heads | L | pause menu 12:05 PM, LINK HOSTING; setup crash -> `game_failed`; continue -> enrolled | `hosting-new-world-noon.png` | - | - |
| Lighting 06/12/19/22 h, Classic 2D and 3D | engine `cf7cba7676` | L | dawn, day, evening, night in both | session pictures | - | - |
| Windows executables under Wine: 21 self-test targets (2D) + rival, catch-reconcile (3D) | engine `cf7cba7676` | W | 23 exit 0 | session log | - | - |
| App suite (`pytest tests`, real engine binary and checkout) | app `43680a9` + engine `cf7cba7676` | L | 2114 passed, 0 failed, 1 skipped (private save paths), 2115 test cases | junit | - | - |
| Engine regression (builds 3D/2D/ASan/BFX, ROM, GBA lines, check-diorama, gameplay repair, first battle, battle end, rival, save safety, bg, party ASan, 28 self-test targets, economy, dialogue) | engine `cf7cba7676` | L | all pass: builds ok; ROM `f214735b…3387`; 4 files, 0 moved GBA lines; check-diorama exit 0 (`test_props` 7991); gameplay repair ok (grass 0.0 %, 12 vehicle scenes); first battle ok; battle end wild 22 / trainer 21 ok; `rival_check` 25/25; `save_safety_check --app --load 3D` 11/11; `bg_check` 12, 0 black; party menu ASan ok; 28 self-test targets exit 0 (`check-rival` 31, `check-clock` 58, `check-catch-reconcile` 12); economy 0 failed; dialogue ok | session log | - | - |
| After the merge: app suite on a clean checkout of the merged app default `50913fe` with the merged engine (`cf7cba7676`, binary and checkout); engine `check-abi` (172 types), `check-rival` 31/0, `check-catch-reconcile` 12/0, `check-clock` 58/0 at the merged engine head; ROM `f214735b…3387` | defaults | L | app 2114 passed, 0 failed, 1 skipped; engine all pass | junit, session log | - | - |

## Current game: Native 3D preview 14 (`emeraldtogether-combined-20261014-2`)

Engine `claude/emeraldtogether-combined` `f8dbffa88a` (the game exe; later commits are documents),
app `claude/emeraldtogether-combined-app` (launcher code unchanged since preview 13's `00bf8d6`:
the commits since are documents and proof scripts).

What preview 14 changed against preview 13's game code (`git diff --stat ee8d059a91 f8dbffa88a`):
`src/multiplayer_spawns.c` (M26, PC only) and its self-test; `src/battle_anim_effects_1.c` (Ally
Switch, PORTABLE only); `src/platform/gba_easy_draw.c`, `src/platform/battle_sprites.c`,
`include/platform/battle_sprites.h` (the carried-out line, PC only); `tools/battle_env/carried_edges.py`.
The GBA ROM is byte-identical, so the GBA test ROM's code did not change either. No save, mailbox,
battle packet, bridge, host, launcher, native UI or Battle FX code changed.

| Test | Build / commit | Env | Last result (date) | Evidence | Changes since that matter | Action |
| --- | --- | --- | --- | --- | --- | --- |
| GBA ROM sha256 f214735b...3387 | `a70687a2da`, `f8dbffa88a` | L | Pass (2026-10-14) | `CHECKPOINTS.md` ROM guard | - | Rerun after any engine change |
| `check_gba_lines.py` | `src/battle_anim_effects_1.c` at `a70687a2da` | L | Pass, 0 moved (2026-10-14) | commit message | - | Rerun after any GBA-file change |
| GBA test suite, full (`make check`) | `c98b38f26c` (code `ee8d059a91`) | L | 6000: 5498 pass, 39 = the upstream list (2026-10-14) | `proof/combined/gba-tests-3/` | none: the changes are PC only (PORTABLE / `src/platform`), the test ROM is built without them | PREVIOUSLY PASSED - EVIDENCE REUSED |
| GBA project tests (`TESTS="Multiplayer"`), G14 test | `ee8d059a91`, `ef121fad20` | L | Pass (2026-10-14) | TEST_PLAN 4, 7i | none (as above) | PREVIOUSLY PASSED - EVIDENCE REUSED |
| `check-native`, `check-abi` | `ee8d059a91` | L | Pass (2026-10-14) | `proof/combined/selftests-linux-2.txt` | none: neither compiles the changed files; `BattleSpriteBgCopy` is no ABI type | PREVIOUSLY PASSED - EVIDENCE REUSED |
| `check-decompress`, `check-party-order`, `check-battle-names`, `check-cry-stop`, `check-shake-anim`, `check-line-break`, `check-wild-weather`, `check-clock`, `check-coop-exp`, `check-coop-controller`, `check-game-sections`, `check-diorama` | `ee8d059a91` | L, W | Pass (2026-10-14) | `proof/combined/selftests-linux-2.txt`, `selftests-wine-2.txt` | none in the code they test (`check-diorama` compiles neither `gba_easy_draw.c` nor `battle_sprites.c`) | PREVIOUSLY PASSED - EVIDENCE REUSED |
| `check-spawn-claims` (23) | `11fe0ada6a` L; the package exe W | L, W | Pass (2026-10-14; Wine: exit 0) | commit `11fe0ada6a`; `scratchpad/winrun/wine-spawn-claims-p14.log` | M26 | Ran (changed code) |
| `check-mp-objects` (21) | `ee8d059a91` L; the package exe W | L, W | Pass (2026-10-14; Wine: exit 0) | as above | M26 touches the spawn objects' room | Ran on the package exe |
| Ally Switch gallery, no partner and with one | `a70687a2da` test build | L | Pass: before 3/3 exit 139, after exit 0, 211/211; with a partner 3 runs 211/211 (2026-10-14) | `proof/stability/allyswitch-*` | the fix | Ran (fixed bug) |
| Carried-out line (`carried_edges.py` on gallery shots) | `f8dbffa88a` test build | L | Pass: before 4/21 and 2/21; after 0/21, 0/21, 0/12 (960x540, both), 0/12 (1264x711) (2026-10-14) | `proof/stability/darkline-*` | the fix | Ran (fixed bug) |
| Battle FX galleries (621 moves, 651 animations) | Battle FX session's build | L | Pass (2026-10-13) | `battlefx-int-wip-20261013-1` report | Battle FX code and data unchanged; every gallery run after the renderer fix (42 animations, 7 runs) had parity exact | PREVIOUSLY PASSED - EVIDENCE REUSED |
| Mass outbreaks in a game (`native_outbreak_proof.py`) | `f8dbffa88a` 3D | L | Pass: native-outbreak-5 (2026-10-14; runs 1-4 failed on the proof's own notice check) | `scripts/multiplayer/native-outbreak-evidence.json` | - | Ran (never executed before) |
| Shared spawns, shiny, claim race, battle, rejoin (`native_spawn_proof.py --wine`) | the package's stripped exe (`44ecf36f...`) | W | Pass 28/28: native-spawns-wine-p14-1 (2026-10-14) | `proof/multiplayer-proof/native-spawns-wine-p14-1` | M26; the renderer change (the winner's battle is 3D, sprite pack loaded) | Ran (changed code, the shipped exe) |
| Multiplayer followers (`native_follower_proof.py`) | `11fe0ada6a` 3D | L | Pass: native-followers-m26-1 (2026-10-14) | same folder | none since (the later changes are battle-only) | PREVIOUSLY PASSED - EVIDENCE REUSED |
| Co-op Gym battle + EXP, 1v1 PvP, trade, host loss and rejoin, Exp. Share | `8f0e5ef44f` / `ee8d059a91` | L | Pass (2026-10-13/14) | preview 13 rows below | none in their code: battle-only renderer and animation changes are PC presentation (the controller, link and save paths are unchanged) | PREVIOUSLY PASSED - EVIDENCE REUSED |
| App suite (pytest) | app `00bf8d6` | L | 1522 pass, 1 skipped (2026-10-14) | `proof/combined/app-suite-3.log` | no app library code changed (documents, proof scripts) | PREVIOUSLY PASSED - EVIDENCE REUSED |
| Package launcher check ("Check installed game files") | preview 14 launcher (`025f52dd...`) | W | Pass: "Installed game and runtime match this package's pins" (2026-10-14) | checkpoint `evidence/1` | - | Ran (new package) |
| Package files on the PC (1036 files, SHA256SUMS) | preview 14 | PC (file check only) | Pass (2026-10-14): transfers match, SHA256SUMS 30/30, EmeraldTogether\ 1036/1036, no extra files | checkpoint `evidence/7-pc-file-check.txt` | - | Ran for this package |
| 2v2 PvP, four games (`native_launcher_multi_proof.py`) | `1579e7fd8` (older) | L | Pass: native-launcher-multi-10 (2026-10-10) | TEST_PLAN 6 | the combine and the co-op validator (`8f0e5ef44f`) | Still to rerun before a release (152 min); not needed for this preview's changes |
| UBSan build (`SANITIZE=1`) | - | - | Not run on the combined game | - | - | Run (never executed on this code) |
| Real GPU frame rates, Windows itself, two PCs, controller, audio | - | PC | Never run | `docs/expansion-windows-test.md` | - | Owner |

## Previous: Native 3D preview 13 (`emeraldtogether-combined-20261014-1`)

Engine `claude/emeraldtogether-combined` `c98b38f26c` (game code `ee8d059a91`; later commits are
documents), app `claude/emeraldtogether-combined-app` `00bf8d6`. Evidence paths are in the cloud
workspace (`/home/claude/proof/...`) and, where named, in the checkpoint folder on the PC.

What preview 13 changed against preview 12 (`git diff --stat 0834bed2f1 ee8d059a91`: 40 files):
multiplayer (spawns, world, co-op, battle validator, bridge), the clock and RTC, wild weather
weights, `battle_util.c` / `battle_script_commands.c` (Exp. Share, co-op and two-trainer EXP),
`battle_controller_opponent.c` (native co-op AI only), `line_break.c` (U13), `load_save.c`,
`event_object_movement.c`, `field_control_avatar.c`, `wild_encounter_ow.c`, self-tests and tests.
No native UI, Battle FX, 3D renderer, sprite-pack or character-customization file changed, so
preview 12's evidence for those is reused.

| Test | Build / commit | Env | Last result (date) | Evidence | Changes since that matter | Action |
| --- | --- | --- | --- | --- | --- | --- |
| GBA ROM sha256 f214735b...3387 | every engine commit | L | Pass (2026-10-14) | `CHECKPOINTS.md` ROM guard | - | Rerun after any engine change (cheap) |
| `check_gba_lines.py` | changed files | L | Pass, 0 moved (2026-10-14) | commit messages | - | Rerun after any GBA-file change (cheap) |
| GBA test suite, full (`make check`) | `c98b38f26c` (code `ee8d059a91`) | L | 6000: 5498 pass, 39 fail = the upstream list (2026-10-14, 1862 s) | `proof/combined/gba-tests-3/` | - | Reuse. Rerun only for shared battle logic changes or a release; otherwise targeted `TESTS=` |
| GBA suite, project tests (`TESTS="Multiplayer"`) | `ee8d059a91` | L | 133/133 pass (2026-10-14) | TEST_PLAN 4 | - | Reuse; rerun when multiplayer battle/reset code changes |
| GBA suite, 39 upstream failures | test ROM with `GEN_LATEST GEN_9` | L | All 39 pass (2026-10-14): expected differences of the GEN_6 profile (G10) | `proof/combined/gba-tests-2/gen9-classification.log` | - | Reuse; recheck only after an expansion upgrade or a config change |
| G14 test (`TESTS="Two opponents"`) | `ef121fad20` | L | Pass; before the fix 4156 vs 3043 (2026-10-14) | TEST_PLAN 7i | - | Reuse |
| `check-native` (1067 + bridge 4257 + 244 + 176) | `ee8d059a91` 2D, 3D | L | Pass (2026-10-14) | `proof/combined/selftests-linux-2.txt` | - | Reuse; rerun when `src/platform` changes |
| `check-abi` (172 types) | `ee8d059a91` | L | Pass (2026-10-14) | same | - | Rerun when save/mailbox/battle structs change |
| `check-decompress` (7682), `check-party-order` (1119), `check-battle-names` (1724), `check-cry-stop`, `check-shake-anim` | `ee8d059a91` 2D, 3D | L, W | Pass (2026-10-14) | same; `proof/combined/selftests-wine-2.txt` | - | Reuse |
| `check-line-break` (U13, 54) | `ee8d059a91` | L, W | Pass (2026-10-14) | same | - | Reuse |
| `check-wild-weather` (139), `check-clock` (58), `check-mp-objects` (21), `check-spawn-claims` (16) | `ee8d059a91` | L, W | Pass (2026-10-14) | same | - | Reuse; rerun when spawns/clock/weather code changes |
| `check-coop-exp` (24), `check-coop-controller` (14) | `ee8d059a91` | L, W | Pass (2026-10-14) | same | - | Reuse; rerun when co-op code changes |
| `check-game-sections`, `check-diorama` | `ee8d059a91` | L | Pass (2026-10-14) | same | - | Reuse |
| `check-diorama-tools` | combined `22f4d7ae4d` | L | 23/24, the known upstream V31 failure (2026-10-13) | `proof/combined/check-diorama-tools.log` | none in the rules compiler | Reuse (known failure) |
| App suite (pytest) | app `00bf8d6` | L | 1522 pass, 1 skipped (2026-10-14; needs `DISPLAY`) | `proof/combined/app-suite-3.log` | - | Reuse; rerun after any app code change |
| Co-op Gym battle + EXP, two games, launcher (`native_launcher_coop_proof.py`) | `8f0e5ef44f` 2D | L | Pass: native-launcher-coop-6 (2026-10-13) | `scripts/multiplayer/native-launcher-coop-evidence.json` | G14 (`ef121fad20`) changes `getexp`, not used by link battles | Reuse; other 7 Gyms never run |
| Co-op EXP award screens (`native_coop_exp_award_proof.py`) | `5a2e4f20c8` 3D, native UI | L | Pass: runs 2-5 (2026-10-13) | `proof/multiplayer-proof/native-coop-exp-award-5` | none in the award | Reuse |
| 1v1 PvP through the launcher, no EXP (`native_launcher_battle_proof.py`) | `8f0e5ef44f` 2D | L | Pass: combined-launcher-battle-1 (2026-10-13) | `proof/multiplayer-proof/combined-launcher-battle-1` | as above | Reuse |
| Permanent Exp. Share, solo wild battle (`native_exp_share_proof.py`) | `ee8d059a91` 3D, Battle FX | L | Pass: native-exp-share-combined-2 (2026-10-14) | same folder | - | Reuse |
| Trade (`native_trade_proof.py`) | `ee8d059a91` 2D | L | Pass: native-trade-combined-1 (2026-10-14) | same folder | - | Reuse |
| Host loss and rejoin (`native_launcher_reconnect_proof.py`) | `ee8d059a91` 2D | L | Pass: native-launcher-reconnect-combined-1 (2026-10-14) | same folder | - | Reuse |
| Multiplayer followers (`native_follower_proof.py`) | `ee8d059a91` 3D | L | Run 1 fail (M26), run 2 pass (2026-10-14) | native-followers-combined-1, -2 | - | Rerun after the M26 fix |
| Shared spawns, shiny, claim race, rejoin (`native_spawn_proof.py --wine`) | the package's stripped exe | W | Run 1 fail (M26), run 2 pass 28/28 (2026-10-14) | native-spawns-wine-combined-1, -2 | - | Rerun after the M26 fix |
| Package launcher check ("Check installed game files") | preview 13 launcher | W | Pass (2026-10-14) | checkpoint `evidence/1` | - | Rerun for each new package |
| Package files on the PC (1036 files, SHA256SUMS) | preview 13 | PC (file check only) | Pass (2026-10-14) | checkpoint `EmeraldTogether-SHA256SUMS.txt` | - | Rerun for each new package |
| 2v2 PvP, four games (`native_launcher_multi_proof.py`) | `1579e7fd8` (older) | L | Pass: native-launcher-multi-10 (2026-10-10) | TEST_PLAN 6 | the combine, co-op validator change (`8f0e5ef44f` touches the controller validator) | Rerun before a release (152 min) |
| Mass outbreaks in a game | - | - | Never run (host unit tests only) | `tests/test_outbreaks.py` | - | Run (never executed) |
| Battle FX galleries (621 moves, 651 animations) | Battle FX session's build | L | Pass (2026-10-13, Battle FX checkpoints) | `battlefx-int-wip-20261013-1` report | Battle FX code and data unchanged since (data byte-identical) | Reuse |
| Native UI menus, by hand | preview 12 `0834bed2f1` | L, W | Pass (2026-10-13) | `emeraldtogether-nativeui-20261013-1` evidence 2-9 | the expansion merge (no UI files changed by it) | Reuse; spot-check menus after UI-adjacent changes |
| Route 110 Psychic Edward in the game | expansion `ad3995ba64` 3D | L | Pass (2026-10-13) | KNOWN_ISSUES U13 | fix carried unchanged into the combine | Reuse |
| UBSan build (`SANITIZE=1`) | - | - | Not run on the combined game | - | - | Run (never executed on this code) |
| Real GPU frame rates (`run-benchmark.bat`) | - | PC | Never run | - | - | Owner |
| Windows itself, two PCs, controller, audio | - | PC | Never run | `docs/expansion-windows-test.md` | - | Owner |

## Updates 15-19 (cloud, engine `claude/dev-update15-20-engine`, app `claude/dev-update15-20`)

| Test | Build / head | Where | Last result | Evidence | Changed since | Rerun? |
| --- | --- | --- | --- | --- | --- | --- |
| GBA test ROM, full `make check` | engine `68ca2f02` | cloud | 5532 passed, 39 failed = the expected list (0 new), 6034 total, 1389 s (2026-10-15) | `docs/final-pc-audit.md` | only PC-only code (`src/region_map.c`) | Rerun at the final head (Update 20) |
| App suite (`pytest tests`, Python 3.12 + tkinter) | app `ed7c621` + audit edits | cloud | 1756 passed, 50 skipped, 0 failed | same | docs only | Rerun at the final head |
| Engine native self-tests (`check-native` + 20 selftest targets) | engine `998164d0` | cloud | all 0 failures (see the audit table) | same | - | Rerun at the final head |
| `--selftest-pokenav-map` | engine `998164d0` | cloud | 8/8 | `docs/graphical-pokenav-map.md` | - | Reuse |
| `--selftest-catch-reconcile` | engine `998164d0` | cloud | 11/11 | `docs/legendary-catch-resolution.md` | - | Reuse |
| `--selftest-rewards` | engine `998164d0` | cloud | 18/18 | `docs/battle-frontier.md` | - | Reuse |
| Town Map markers, rendered pictures looked at (debug scene) | engine `68ca2f02` | cloud, headless | markers, SELECT jump, zoom, scroll, live refresh seen | `docs/graphical-pokenav-map.md` | one palette guard (`998164d0`) | Reuse; real windows are the owner's |
| 2D and 3D game, headless cold boot to Birch's introduction | engine `998164d0` | cloud, headless | no crash, correct pictures | `docs/final-pc-audit.md` | - | Reuse |
| 1v1v1v1 free-for-all on four real PCs | - | PC | Never run | `docs/windows-test-update15-20.md` A | - | Owner |
| Battle Frontier BP/items/team selection on PCs | - | PC | Never run | same, B | - | Owner |
| Legendary catch race on two PCs | - | PC | Never run | same, C | - | Owner |
| Graphical PokéNav map on Windows / 3D window | - | PC | Never run | same, D | - | Owner |
| App suite at Update 30 (`pytest tests`, Python 3.12 + tkinter, xvfb) | app `claude/dev-update30` + engine `d3f4e4f7` | cloud | 1931 passed, 50 skipped (49 no Lua 5.3+, 1 no private save paths), 0 failed, 500 s (2026-10-17) | `docs/update30-main-menu.md` | - | Rerun at the final integrated head |
| `--selftest-breeding` (63 checks), `--selftest-shiny` (12) | engine `d3f4e4f7` | cloud | 0 failed | `docs/update30-gameplay.md` | - | Reuse |
| `economy_check.py` (28 scenarios, 3D and Classic) after the Mart viewport fix | engine `d3f4e4f7` | cloud | 0 failed in two complete runs (before the fix 2 of 3 runs failed) | `docs/update30-gameplay.md` section 9 | - | Rerun at the final head |
| In-game main menu, saved servers, world/character linking (20 end-to-end addendum tests) | app `claude/dev-update30` | cloud, simulated (scripted shell, real TLS server on loopback, temporary profiles) | all pass | `docs/update30-main-menu.md` | - | Rerun at the final head |
| Main menu, host/join with saved servers on two or more real PCs | - | PC | Never run | `docs/update30-main-menu.md` (checklist) | - | Owner |

## Next update (2026-10-18; app `claude/admiring-bohr-dpxzuy`, engine `claude/nu-engine` `6cd8af0f`)

| Test | Build / head | Where | Last result | Evidence | Changed since | Rerun? |
| --- | --- | --- | --- | --- | --- | --- |
| App suite, baseline in this container | app `27c43c7` + early character commits | L | 2093 passed, 7 failed (capability-version expectations, fixed), 119 skipped | session log | fixed | - |
| App suite, integrated (menu + networking + installation) | app `214da09` | L | 2232 passed, 0 failed, 119 skipped (Lua 5.3 subtests, private paths) | `docs/next-update-report.md` G | guides, 2 tests | Final run recorded in DEVELOPMENT_LEDGER |
| Menu flows, Join Friend (real server, TLS), end to end with the real registration (host + 2 friends, Solo then friend, friend -> Solo -> back, relay route) | app `76a27ca` | L, simulated PCs | all pass | `tests/test_shell_*.py` | - | Reuse |
| Networking: diagnostics, rejections, reachability, port mapping (fake IGD/NAT-PMP), relay, sessions via relay | `claude/nu-network` `6597062` and merged | L | 131 passed + 142 subtests | `docs/networking.md` | - | Reuse |
| Installation: game facts, check_installation, installer build (stand-ins), CI check logic | `claude/nu-install` `45703cb` and merged | L | 44 passed + 18 subtests | `docs/windows-installation.md` | - | Reuse |
| Windows package, smoke (synthetic game): installer build + fresh-runner silent install, files, start, repair, uninstall | app `76a27ca` | CI windows-2022 | success (run 39162293580) | run page | - | Reuse |
| Windows package, full (real game, engine `6cd8af0f`, ROM `f214735b...3387`) | app `76a27ca` | CI windows-2022 | success (run 39162322062): ROM verified, graphics and menu checks on the packaged games, installer, fresh-runner install/start/repair/uninstall | run page | docs only | Reuse |
| App suite, final head | app `955851d` | L | 2234 passed, 0 failed, 119 skipped (Lua 5.3 subtests, private paths), 2605 subtests | session log | - | Reuse |
| Engine native Linux build with the setup-text change | engine `6cd8af0f` | L | builds; title and main menu screenshots in setup mode show the new text | session scratch | - | Reuse |
| Two PCs, one network / two Internet connections / real router / Tailscale / relay on a real machine | - | PC | **Never run** | procedure: report G | - | Owner |


## Visual repairs (2026-10-18; app `claude/admiring-bohr-dpxzuy`, engine `claude/vr-repairs-engine` `47767264`; `docs/visual-repairs-20261018.md`)

| Test | Build / head | Where | Last result | Evidence | Changed since | Rerun? |
| --- | --- | --- | --- | --- | --- | --- |
| App suite with the battle-effects packaging | app `47045e9` + docs | L | 2242 passed, 0 failed, 51 skipped (Lua 5.3 bridge subtests, private paths) | session log | - | Reuse |
| `check-diorama` (renderer units, compositor goldens, rules) | engine `47767264` | L | all passed | session log | - | Reuse |
| GBA ROM rebuilt at the engine head | engine `47767264` | L | SHA-256 `f214735b...3387` (unchanged) | session log | - | Reuse |
| Battle effects: 7 moves in a 3D wild battle (Linux build beside `battlefx/`) | engine `47767264` | L | each move its own HD effect (fire, electric, ground, psychic background, grass, stat change, status) | scratchpad `vr/fx-linux.png` | - | Reuse |
| Battle effects: Windows exe in a bundle collected with `--battle-effects`, launched from another folder; control without the folder | engine `47767264`, app `47045e9` | W | with: "core ready ... runtime\battlefx", HD effects for 6 moves; without: "cannot read", GBA sprites | scratchpad `vr/fx-wine.png` | - | Reuse |
| Healing: GBA vs 3D frames through the effect (3 and 6 Pokemon); hurt party healed 3 runs (40/165 PSN -> 165/165) and walked away; trainer "!" over Calvin | engine `4e213ddf`+ | L | balls, glow, flash, monitor drawn in 3D; HP restored; control returned; "!" drawn | scratchpad `vr/heal-*`, `vr/excl` | - | Reuse |
| Area changes: 7-case transition matrix (PC x2, PC at 1920x1080 and 960x600, Mart, house, route->town, town->route), frames with the GBA picture over the 3D field | before `6cd8af0f`+heal, after `df5f960b` | L | before 13/5/8/7/7/4/3, after 0 in every case | scratchpad `vr/matrix-*`, `vr/issue3-before-after.png` | - | Reuse |
| Distant objects: Route 102 (Allen, Tiana), Rustboro; hand-over to the spawned object while walking; profile | engine `47767264` | L | drawn before spawning (missing before); continuous hand-over; object sync +0.03 ms, drawing +0.09 ms, 72 -> 84 draws | scratchpad `vr/popin-*`, `vr/rustboro-*` | - | Reuse |
| Windows package, smoke (synthetic game, synthetic battlefx) | app `1eadcd0` | CI windows-2022 | success (run 39178157419) | run page | - | Reuse |
| Windows package, full (engine `47767264`, ROM pinned `f214735b...3387`) | app `1eadcd0` | CI windows-2022 | success (run 39178174123): ROM pin, packaged games = engine build, "battle effects: 26 files pinned, 7393605 bytes", graphics checks 16/16, menu check, installer, fresh-runner install/repair/uninstall | run page, artifact `EmeraldTogether-Windows-Installer` | - | Reuse |
| Windows package, full, **from the merged defaults** (app `claude/emeraldtogether-combined-app` `5a99213`, engine `claude/emeraldtogether-combined` `47767264`) | app `5a99213` | CI windows-2022 | success (run 39180878911; run 39179651601 before it stopped at the version label, which may not contain parentheses): ROM pin `f214735b...3387`, packaged games = engine build, battle effects pinned, graphics checks 16/16, menu check, installer `EmeraldTogether-Setup-EmeraldTogether-2026-10-19-visual-repairs.exe` (artifact `EmeraldTogether-Windows-Installer`), fresh-runner install/repair/uninstall | run page | - | Reuse |
| The four repairs on a Windows PC with a real GPU at 60 fps | - | PC | **Never run** | checklist in `docs/visual-repairs-20261018.md` | - | Owner |

## Create World crash fix (2026-10-19; app `claude/admiring-bohr-dpxzuy` `04f5778`; `docs/world-creation-fix-20261019.md`)

| Test | Build / head | Where | Last result | Evidence | Changed since | Rerun? |
| --- | --- | --- | --- | --- | --- | --- |
| App suite with the fix (Tk tests under Xvfb) | app `04f5778`+ | L | 5008 cases (JUnit, subtests included): 4888 passed, 119 skipped (Lua 5.3 bridge subtests, private paths), 1 failed: the classic launcher's Tk test `test_worlds_are_listed_with_their_players_and_a_world_can_be_picked_for_hosting`, flaky (3 of 5 runs fail, also on `d7dbe1c` before the fix; KNOWN_ISSUES WC-5); an earlier full run under Xvfb had no failure | session log | - | Reuse |
| App suite in CI (python-tests) | app `9d11e7a`, `f87a4af`, `823afc3` | CI ubuntu | success (runs 39191905283, 39192332488, 39193129756) | run pages | - | Reuse |
| Menu tests with real `LocalAddress` values (test_shell_app, _join, _e2e, _migration, _game_files, _records) | app `04f5778` | L | 66 passed; on the old code 29 of them fail | session log | - | Reuse |
| `tests/test_world_creation.py` (18: create, save, reopen, host, address change, rename, Listen on, invite code, delete, crash leftover, earlier launcher, VPN, limit, failed save, readable refusals, strict validation, previous release's file) | app `04f5778` | L | 18 passed; on the old code 17 fail (the previous release's file loads on both) | session log | - | Reuse |
| Reported crash on the **installed** old build, through its menu window | installer of run 39180878911 (SHA-256 `800795c1...ab1e`) | CI windows-2022 | reproduced (installed-world-check runs 39192332500, 39193466499): default network refused, nothing created; public address: world on disk, owner's traceback line for line in last-error.txt; main menu fails again | run logs | - | Reuse |
| Windows package, full, with the fix | app `9d11e7a` (fix `04f5778`), engine `47767264` | CI windows-2022 | success (run 39191926490): ROM pin `f214735b...3387`, graphics checks, menu check, installer `EmeraldTogether-Setup-EmeraldTogether-2026-10-19-world-fix.exe` (SHA-256 `c84649c1...2fff`), fresh-runner install/repair/uninstall | run page, artifact `EmeraldTogether-Windows-Installer` 12160474011 | - | Reuse |
| Create World on the **installed** new build, over the old build's leftover data and on a fresh profile | installer of run 39191926490 | CI windows-2022 | passed both (run 39193466499): default network and public address created and listed with the LAN address as text, invite code decodes to it, rename, delete, hosting up to the game opening and loading the character's save, restart keeps them, no error | run log, artifact `EmeraldTogether-world-check` | - | Reuse |
| Windows package, full, **from the merged defaults** (app `claude/emeraldtogether-combined-app` `f136689`, engine `claude/emeraldtogether-combined` `47767264`), with Create World on its own installed build | app `f136689` | CI windows-2022 | success (run 39195679171): ROM pin `f214735b...3387`, graphics and menu checks, installer `EmeraldTogether-Setup-EmeraldTogether-2026-10-19-world-fix.exe` (SHA-256 `fd68a9fe...d318`, artifact `EmeraldTogether-Windows-Installer` 12162187817), fresh-runner install/repair/uninstall, world check on a fresh profile passed | run page | - | Reuse |
| Old installer, then that final installer over its leftover data and on a fresh profile | runs 39180878911 / 39195679171 | CI windows-2022 | passed (installed-world-check run 39197052414): crash reproduced on the old one; the new one listed the world the crash left ("Tester's world", this PC only) at start, created, invited, renamed, deleted, started hosting, and kept both worlds after a restart | run log | - | Reuse |
| Hosting for friends after the game's CONTINUE, a friend joining, on an installed build or a PC | - | PC | **Never run** (runner without GPU; CONTINUE not driven) | checklist in `docs/world-creation-fix-20261019.md` | - | Owner |


## Multiplayer session fix (2026-10-19; app `claude/admiring-bohr-dpxzuy`, engine `claude/mp-session-engine` `16d0aa55`; `docs/multiplayer-session-fix-20261019.md`)

| Test | Build / head | Where | Last result | Evidence | Changed since | Rerun? |
| --- | --- | --- | --- | --- | --- | --- |
| Reproduction through the production launcher (host and friend, rival checkpoints on), unchanged code | app `30dffa7`, engine `47767264` | L | **failure reproduced**: both games' bridges stopped on the first rival record ("invalid shared-world update"), PLAYERS refused, the others kept them listed and hidden | scratchpad `mp/multiplayer-proof/launcher-1` | - | Reuse |
| Engine `check-native` (all native suites; `test_mp_bridge` with `world_rival_record_accepted`, 8 failures on the old validator, and `presence_detail_rides_the_local_pose_only`) | engine `16d0aa55` | L | 0 failures | session log | - | Reuse |
| GBA ROM rebuilt at the engine head (`multiplayer.c`, `start_menu.c` recompiled; `multiplayer_presence.c` left out) | engine `16d0aa55` | L | SHA-256 `f214735b...3387` (unchanged) | session log | - | Reuse |
| `tests/test_session_persistence.py` (real server and companions over TCP, games as the bridge's binary protocol: 1, 2, 3 and 4 players with a battle at each count, battle longer than every timeout, menus and a door, a game without the capability, four players and a fifth refused as full, four enrolled players and the Players menu, a host refusing rival status, rival records) and the related suites (`test_companion`, `test_player_menu`, `test_mailbox`, `test_spawn_director`, manifests) | app `14b8ad1`, the 1-to-4 test `52cdc1e`+ | L | 82 passed; `test_session_persistence.py` alone 16 passed with 17 subtests, 5 runs in a row (players 1, 2, 3, 4 joining one by one, a battle at each count); the rival-refusal test fails on the old code | session log | - | Reuse |
| App suite in CI (python-tests) | app `14b8ad1` | CI ubuntu | success (run 39259722861) | run page | - | Reuse |
| Two players through the production launcher, native Linux 2D games (`native_session_persistence_proof.py`) | app `14b8ad1`+proof, engine `16d0aa55` | L | passed (session-2p-10): each player's wild battle held 25 s with both sessions unchanged (13 observations), the watcher's PLAYERS "<name> - In battle", back on the field in the same session; the other player in Littleroot listed, page "Field: LITTLEROOT TOWN"; a close: "Connected: 1/4" without them; rejoin: "Connected: 2/4"; store integrity | scratchpad `mp/multiplayer-proof/session-2p-10` | - | Reuse |
| Four players through the production launcher (`native_session_persistence_proof.py`, four sources and displays) | app `52cdc1e` (proof), engine `16d0aa55` | L | passed (session-4p-3): all four linked, each game drawing the other three, PLAYERS "Connected: 4/4"; the host fought a wild battle out and lost (whited out to the house in Littleroot), a friend ran, then two friends battled at the same time: each time 25 s with all four sessions unchanged (12 observations), the watcher's PLAYERS "<name> - In battle" (both at once), everyone back on the field in the same sessions; the fourth player in Littleroot listed, page "Field: LITTLEROOT TOWN"; a close: "Connected: 3/4"; rejoin: "Connected: 4/4"; store integrity. Earlier runs stopped on the proof's own driving (4p-1: two players talked to the same Pokemon; 4p-2: no Pokemon in a straight line within 240 s) | scratchpad `mp/multiplayer-proof/session-4p-3` | - | Reuse |
| Windows package, full (engine `16d0aa55`, ROM pinned `f214735b...3387`) | app `14b8ad1` | CI windows-2022 | success (run #71, 39259757031): ROM pin, packaged games = engine build, installer `EmeraldTogether-Setup-EmeraldTogether-2026-10-19-session-fix.exe` (SHA-256 `911c71ba...b36a`, artifact `EmeraldTogether-Windows-Installer` 12191757095), graphics-mode and in-game menu checks on the packaged games, fresh-runner install/start/repair/uninstall, Create World on the installed build through its menu window; the packaged game's log says "detail 1" (the new capability) | run page | - | Reuse |
| Engine `check-native` and the multiplayer checks after the outbreak and Lucky Trade fixes (bridge 4375 checks with `world_outbreak_marker_accepted`, 10 failures on the validator before it, and `trade_record_carries_the_lucky_bit`, 6 failures before it); `check-abi`, `check-rival` 31/0, `check-mp-objects` 21/0, `check-pokenav-map` 8/0, `check-spawn-claims` 23/0, `check-game-sections` | engine `3f06fd20` | L | 0 failures | session log | - | Reuse |
| 3D renderer suite `check-diorama` (renderer units, camera 403, far field 54618, props 7991, battle stage, compositor goldens 18318 metatiles, rules) | engine `3f06fd20` | L | all passed | session log | - | Reuse |
| GBA ROM at the engine head (only `src/platform` and tests changed since `16d0aa55`; `src/platform` is not in the ROM build) | engine `3f06fd20` | L | SHA-256 `f214735b...3387` (unchanged) | session log | - | Reuse |
| App suite under Xvfb with the session fix | app `2a5d982` | L | 2314 passed, 54 skipped, 1 failed: `test_launcher_menu` world list test (WC-5, flaky; passed 3 of 3 reruns), plus 2682 subtests | session log | - | Reuse |
| Outbreak through the production launcher, two players (the world's first outbreak after four active minutes) | engine `16d0aa55` (rival fix only) / `3f06fd20` | L | before: both games' bridges stopped when the outbreak started ("invalid shared-world update"), the host's game unlinked (outbreak-before-2p); after: both held the marker and stayed linked, and the whole proof passed, the host winning its battle (outbreak-after-2p) | scratchpad `mp/multiplayer-proof/outbreak-*` | - | Reuse |
| Two (or four) physical Windows PCs, a home network, the relay, the 3D build | - | PC | **Never run** | checklist in `docs/multiplayer-session-fix-20261019.md` | - | Owner |
