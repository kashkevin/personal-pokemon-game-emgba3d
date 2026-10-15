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
| 1v1v1v1 free-for-all (Update 15) | Engine rules in the GBA test ROM: `test/battle/ffa/*` **25 tests** (every trainer a foe, any foe targetable, spread moves, Reflect/hazards/Court Change per side, Intimidate on three, weather shared, Roar, Imprison, Helping Hand fails, replacement, elimination, last-trainer win, simultaneous draw), `test/multiplayer_battle.c` four-core FFA startup (all four local slots); PC `--selftest-coop-controller` 22 (FFA owners, targets, winner byte); app `test_battle_ffa_desk` 17, `test_native_ffa` 18 (envelope, controller, roster, journal, admission), `test_battle_protocol`/`controller`/`manifest`/`challenge_network`/`player_menu` additions, `FfaBook` | Four real PCs; the doubles-layout screen; a real disconnect mid-battle. |
| Trading and saving | `test_live_trade`, `test_trade_desk`, `test_trade_eligibility`, `test_autosave`, `test_emergency_save`, `test_checkpoint_server` | Trading between two real saves. |
| Disconnect / reconnect / host restart | `test_battle_recovery(_session)`, `test_native_battle_resume`, `test_journal_load`, `test_companion_live`, **new** `test_secret_bases` reconnect test, shared-world restart tests | Pulling a real network cable. |
| Secret Bases (new) | engine `--selftest-secret-base` 24; bridge frames in `test_mp_bridge` (4293); app `test_secret_bases` 27 incl. a real host with two companions | Entering a friend's base in the game. |
| PokéNav World pages (new) | `test_secret_bases` (nav view, menu pages, 6-row and 25-character limits) | How it looks in the 3D menu. |
| Dormant legendary events (new) | `test_event_conditions` 15 (mutation-checked) | Waiting for one in a game. |
| Championship entry rules (new) | `test_frontier_rules` 11 incl. real saved parties from the battle fixture | A real Championship. |
| Breeding and eggs | GBA tests listed above | Hatching one on a PC. |
| Battle Frontier / Pokémon League (Updates 8, 10) | `test_frontier` 43 (rules, book incl. restart, service against the real battle desk and real saved parties, menus, protocol), `test_coop_battle` (ladder code reaches the game); engine `--selftest-ladder` 20 (all 862 trainers build and scale) | Playing a ladder on two PCs; disconnect during a round on a real network. |
| Graphical PokéNav map (Update 18) | Engine: `--selftest-pokenav-map` (all maps locate inside the map or are refused, Routes 121/126 split like the original, indoor = middle of section, bounds-checked ids), `tools/pc_port/map_group_counts.py --check`; a headless debug scene drove the real PokéNav to the Hoenn map and the rendered pictures were inspected (markers, SELECT jump, zoom, scroll, live refresh); app: `test_world_mailbox`, `test_secret_bases`, `test_world_companion` (outbreak place reaches the game) | Real Windows, 3D (Diorama) window, a controller, a real host with players. |
| Legendary catch reconciliation (Update 17) | Engine: PC `--selftest-catch-reconcile` (record on catch, release only the matching Pokémon, last-member guard, keep, repeated/missing verdicts, no record), `--selftest-rewards`, `check-native` bridge accepts kinds 4/5; app: `test_event_catch` (single verdict, restart, retroactive winner, lapse), `test_rewards`, `test_world_server` (contested catch: second reporter gets release over the wire, nothing queued twice, receipt recorded) | A real two-PC race, a real save losing the copy, host restart mid-race on a PC. |
| Battle Frontier completion (Update 16) | Engine: GBA test ROM co-op team-selection tests (reduction in saved order, exact restore of all six slots, invalid selections refused before anything changes); PC `--selftest-rewards` 18 (Battle Points and items over the wallet stream: caps, partial debits, bag/PC, malformed words), `--selftest-coop-exp` 32 (slot remap), `check-native` incl. the bridge accepting reward words; app: `test_frontier` (rewards once, ledger, crash between settle and send, shop debit/grant/refund/partial, team selection and menus), `test_rewards`, `test_coop_battle` (selection through the roster, preparation, startup check, consent, reservation) | Real BP/items in a real save, the Team/BP pages on screen, a real round with a reduced party. |
| Legendary catch ownership (Update 11) | `test_event_catch` 11, `test_shared_world` | Two real games racing a catch. |
| Secret Base defender team, PokéNav habitat page (Update 12) | engine `--selftest-secret-base` 36; `test_secret_bases` 32 incl. real encounter tables | Meeting the team in a visited base; how the page looks. |
| Gen 6 rules (Update 13) | `check-native` (compiles the PC build with the new switches); `test_appearance_names` | A thunderstorm and a trainer battle in the game. |

## Update 15 (free-for-all) runs, 2026-10-15

| Suite | Result |
| --- | --- |
| GBA test ROM, full `make check` at engine `b7f82bda` (the commit before the native phase) | 6031 tests: **5529 passed (5504 + 25 new FFA tests)**, 39 failed = exactly the 39 expected Gen 6 failures (`docs/gba-test-expected-failures.txt`), 0 new |
| GBA test ROM, targeted re-run at the final Update 15 engine head: `test/battle/ffa`, `test/multiplayer*`, `exp.c`, `battle_message.c` | 197 passed, 3 failed = the 3 listed Gen 6 failures (the same 3 fail on the Update 14 head `c56e76a6`, checked in a clean worktree) |
| Release GBA ROM | rebuilt after every change: sha256 **`f214735b…3387`, byte-identical** (needed: macro forms of the helpers, `battle_ffa.c` excluded from the release link because even an empty object reorders the linker's veneers, `#line` markers) |
| PC `check-native`, `--selftest-ladder` 20, `--selftest-secret-base` 36, `--selftest-coop-controller` 22 | all pass |
| App suite, `xvfb-run pytest tests` (venv, Python 3.13) | all pass except the 24 Tk tests (run in the Python 3.12 + tkinter venv: all pass) and one timing test run under heavy machine load (re-run alone: see ledger) |

## What none of this proves

Frame rate, input latency, audio quality, DPI/fullscreen behaviour, antivirus/SmartScreen behaviour, and anything that
depends on a real network (latency, packet loss, NAT) or a second human. Do not read "all pass" as "plays well".
