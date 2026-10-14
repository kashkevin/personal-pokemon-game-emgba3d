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

## Current game: Native 3D preview 13 (`emeraldtogether-combined-20261014-1`)

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
