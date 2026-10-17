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

