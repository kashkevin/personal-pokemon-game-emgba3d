# Automated validation matrix (Update 6, 2026-10-15)

What was run, by whom, on what, and how far it can be trusted. **Every row is a cloud/CI test.** No row is a real
Windows PC, a real GPU, a real speaker, a real controller, or two real machines on a real network. "Simulated" means a real
host and companion code driven by scripted game bridges over loopback TCP, or the engine's own code in a self-test or the
GBA test ROM. Hardware checks are in `docs/windows-test-update2-7.md`.

Commits: app `claude/dev-update2-7`, engine `claude/dev-update2-7-engine` (see `DEVELOPMENT_LEDGER.md` for hashes).
GBA ROM `pokedev.gba` built from this engine: sha256 `f214735b…3387` (byte-identical to before Update 2).

## Totals run for Update 5/6

| Suite | Result |
| --- | --- |
| App suite, `xvfb-run pytest tests` (Tk GUI tests need a display; without one 7 of them error with "no $DISPLAY", environmental) | **1598 passed, 118 skipped, 0 failed**, 2345 subtests (10 min 40 s) |
| Engine native checks, Linux 2D and 3D binaries: `check-native` (platform 4293 + display/menus 24154 + bridge 308 + keybinds 176 + gamepad 28216 checks), `check-abi` (172 types, GBA vs PC layout parity), game sections, party order 1119, battle names 1724, cry stop 5, shake anim 11, line break 54, wild weather 139, clock 58, mp objects 21, spawn claims 23, **secret base 24**, co-op EXP 26, co-op controller 14, keybinds 21, graphics mode (the fallback script, all PASS) | all pass, 0 failed |
| Windows cross-compile (mingw): both `pokeemerald-mp.exe` (Classic 2D) and `pokeemerald-mp-diorama.exe` (3D) link | builds (CI builds them again) |
| GBA test ROM, full `make check` compared with `docs/gba-test-expected-failures.txt` by `scripts/diagnostics/check_gba_test_failures.py` | 6006 tests: **5504 passed**, 39 failed = the 39 expected Gen 6 failures, **0 new, 0 listed-but-passing** (gate script exit 0), 18 known failing, 15 assumptions failed, 421 to do, 9 expected failing (one `Move Animations work 4 25/222` is the listed random send-out entry). The run took about 1 h 10 min on a loaded VM |
| New GBA tests this queue | `(EggHatch)` 4, `Multi battle` Mega 2: all pass; Daycare group 12, `GetChildNature` 11, `InheritIVs` 5, `InheritPokeball` 7, `InheritAbility` 3 pass; `Mega` 19 of 20 (the 20th is the listed Gen 9 expected failure) |

## By area (what the user asked to be covered)

| Area | Automated evidence | Gap (needs a human/PC) |
| --- | --- | --- |
| Start-up and import of the owner's own game | `test_game_import`, `test_launcher_setup(_gui)`, `test_player_build`, `test_package_audit`, `test_cold_start`; the Windows CI job builds the launcher, audits the package and starts the frozen launcher for 20 s. The import itself needs the owner's dump (sha256 `a9dec84d…85af`), which is never in CI. | Import with the real file on a clean PC. |
| 3D / Classic 2D selection and fallback | `test_graphics_mode`, `check-graphics-mode` (16 of 16 on the packaged Windows games in run 38672941750) | A real GPU, an old GPU, a driver without OpenGL 3.3. |
| Keyboard customization | engine `test_keybinds` (176) + `--selftest-keybinds` (21, real event loop) + `test_game_controls` + launcher GUI tests | Rebinding with a real keyboard; F10 page by hand. |
| Controller code path | **new** `test_gamepad` (28,216 checks: all 4096 button combinations equal the old arithmetic, stick/trigger thresholds, no stray bits) | A real XInput pad; non-XInput pads are unsupported (documented). |
| Audio code path | `check-cry-stop`, the decompress/sound-table builds; the audio device code is unchanged | Hearing it; fast-forward audio pause. Not testable in the cloud. |
| Solo play, saves | `make check` GBA ROM suite; save-layout parity `check-abi`; autosave/emergency save/checkpoint tests | Playing a real save to the end of a session. |
| Wild spawns, outbreaks, events, weather | `check-spawn-claims`, `check-wild-weather`, `test_outbreaks`, `test_shared_world`, `test_event_conditions` (**new**), `test_world_spawns_companion` | Watching them in two games. |
| Co-op battles and rewards (EXP, Exp. Share) | `check-coop-exp` (26), `check-coop-controller` (14), `test_coop_battle`, GBA tests `(Exp)`-related, `Multiplayer` group | A real co-op Gym fight on two PCs. |
| 4-player / 2v2 | `test_battle_multi_desk`, `test_native_multi`, GBA `Multi battle` tests (incl. **new** Mega), four-player recovery tests | Four PCs. |
| Trading and saving | `test_live_trade`, `test_trade_desk`, `test_trade_eligibility`, `test_autosave`, `test_emergency_save`, `test_checkpoint_server` | Trading between two real saves. |
| Disconnect / reconnect / host restart | `test_battle_recovery(_session)`, `test_native_battle_resume`, `test_journal_load`, `test_companion_live`, **new** `test_secret_bases` reconnect test, shared-world restart tests | Pulling a real network cable. |
| Secret Bases (new) | engine `--selftest-secret-base` 24; bridge frames in `test_mp_bridge` (4293); app `test_secret_bases` 27 incl. a real host with two companions | Entering a friend's base in the game. |
| PokéNav World pages (new) | `test_secret_bases` (nav view, menu pages, 6-row and 25-character limits) | How it looks in the 3D menu. |
| Dormant legendary events (new) | `test_event_conditions` 15 (mutation-checked) | Waiting for one in a game. |
| Championship entry rules (new) | `test_frontier_rules` 11 incl. real saved parties from the battle fixture | A real Championship. |
| Breeding and eggs | GBA tests listed above | Hatching one on a PC. |

## What none of this proves

Frame rate, input latency, audio quality, DPI/fullscreen behaviour, antivirus/SmartScreen behaviour, and anything that
depends on a real network (latency, packet loss, NAT) or a second human. Do not read "all pass" as "plays well".
