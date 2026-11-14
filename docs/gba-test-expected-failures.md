# The 39 upstream GBA test failures, classified (Gen 6 profile)

The owner's request of 2026-11-05: "Classify all 39 upstream GBA test failures and preserve intentional Gen 6
behavior." This document classifies each of the 39 tests in `docs/gba-test-expected-failures.txt`. No game, engine
or test change was made; where a test-side change could let a test run under Gen 6 without changing the game, it is
given as an option only.

## Evidence

* **Engine read:** `/home/user/engine-int`, branch `claude/integrate-1025` at `0d25e9c0` (read only). `GEN_LATEST` is
  `GEN_6` (`include/config/general.h:75`). Every `B_*` switch below is `GEN_LATEST` in `include/config/battle.h`, and
  the test configuration (`include/config/test.h`) overrides none of them. All paths below are in the engine.
* **Failing check and observed value of each test:** the "FAILED tests:" block of the last three saved full runs,
  all of 2026-10-27 (scratchpad `gbatests3/check.log`: engine `6320c77d`, 6,095 tests; `gbatests4/check.log`:
  `99b9a03d`, 6,101 tests; `final-checks13/gba-check.log`: `a5013203`, 6,108 tests). The three blocks are identical,
  line numbers included. `scripts/diagnostics/check_gba_test_failures.py` on each log: `39 failed, 39 expected, 0 new,
  0 listed but passing` (exit 0).
* **Still current:** every file:line in this document was re-read at `0d25e9c0` and still names the same test and the
  same failing check. TEST_LEDGER records the GBA ROM unchanged (`f214735b...3387`) from those runs through
  `0d25e9c0` (the MS-198 row), so the game code under test is the same. Nothing was rebuilt or re-run for this
  document.
* **Under Gen 9:** all 39 pass when the test ROM is built with upstream's `GEN_LATEST GEN_9` (2026-10-14, TEST_LEDGER
  row "GBA suite, 39 upstream failures", KNOWN_ISSUES G10; its log `proof/combined/gba-tests-2/gen9-classification.log`
  is not in this checkout).
* **Reach in this game:** the roster is National Dex 1-721 (`PROJECT_SPEC.md`); later species are compiled in only to
  keep the save layout (`docs/gen6-defaults-profile.md`). "Not in game content" below means the species or ability
  appears in none of `src/data/trainers.party`, `tower_legends.party`, `battle_partners.party`,
  `wild_encounters.json` or `mp_wild_pool.h`.
* **Outside references**, used only where the engine's Gen 6 result needed a second opinion: Pokemon Showdown's data
  on GitHub (`data/mods/gen6/moves.ts`, `data/mods/gen6/abilities.ts`, `data/abilities.ts`, `sim/battle-actions.ts`,
  `sim/battle-queue.ts`, read 2026-11-05). Bulbapedia is not reachable from this session.

**Reading the names.** A list entry is the file and the title as the runner prints it. `N/M` is parameter N of M and
`(t/T)` is trial t of T of a `PASSES_RANDOMLY` test (`test/test_runner_battle.c:342-355`). A parametrized test stops
at its first failing parameter: the next parameter starts only after one passes (`test/test_runner_battle.c:2168`,
`:2264`), so later parameters do not run while the test fails.

## The three classes

* **(A) Intended Gen 6 behavior.** The check that fails, or the setup step that breaks, is a rule that exists in Gen 6
  and that the profile sets to its Gen 6 value. The game does what Gen 6 does; the test expects a later generation.
  Keep the Gen 6 behavior.
* **(B) The test cannot express Gen 6.** The scenario itself needs something Gen 6 does not have (a Gen 7-9 ability,
  move, weather or rule). There is no Gen 6 result to compare with: under the Gen 6 profile the engine applies an
  older rule to a newer mechanic. None of these mechanics is in this game's content.
* **(C) Possible real defect.** Concrete evidence that the engine, under this profile, does not follow the rule it
  implements for that generation.

Precedence: C, then B, then A. A later species used only as scenery (Comfey in row 5, Farigiraf in rows 12-13) does
not make a row (B) when the rule that fails is a Gen 6 one.

## The switches involved

The quotes are the switches' own comments in `include/config/battle.h`. "Pin" says whether a test can select another
generation with `WITH_CONFIG` (`include/test/battle.h:1037`): it only works where the code reads the switch through
`GetConfig` (`include/config_changes.h:25-41`), not where it is compiled into a constant or into data.

| Id | Switch (battle.h line) | The switch's comment | Gen 6 value means | Code that branches on it | Pin |
| --- | --- | --- | --- | --- | --- |
| S1 | `B_OVERWORLD_WEATHER_OVERRIDE` (337) | "In Gen9+, overworld weather cannot be overridden." | abilities and moves replace overworld weather | `src/battle_util.c:2648` sets `overworldWeatherPresent` only at Gen 9+; only that flag makes a weather change fail (`src/battle_util.c:2133`) | yes |
| S2 | `B_CHARGE` (148) | "In Gen7 and earlier, Charge status is lost regardless of the typing of the next move." | Charge counts down every end of turn (the code applies this to every generation before 9) | `src/battle_end_turn.c:80` (countdown when `B_CHARGE < GEN_9`), `src/battle_move_resolution.c:5901` (the Gen 9 clearing skipped); the Charge move sets the timer to 2 (`src/battle_move_resolution.c:5702`), Electromorphosis and Wind Power set it to 1 (`data/battle_scripts_1.s:3575`); 2x damage while it is above 0 (`src/battle_util.c:6664`) | no: both lines compare the constant |
| S3 | `B_WEAK_ARMOR_SPEED` (210) | "In Gen7+, when hit by a physical move, Weak Armor raises Speed by 2 stages instead of 1." | Speed +1 | `src/battle_util.c:4014` | yes |
| S4 | `B_ILLUMINATE_EFFECT` (209) | "In Gen9+, Illuminate prevents accuracy from being lowered and ignores the target's evasion. Previously, it had no in-battle effect." | no in-battle effect | blocking the accuracy drop: `src/battle_stat_change.c:822` (`if (B_ILLUMINATE_EFFECT < GEN_9) return FALSE;`, a constant); ignoring evasion: `src/battle_util.c:10610` (`GetConfig`) | only the evasion half |
| S5 | `B_SNOW_WARNING` (335) | "In Gen9+, Snow Warning will summon snow instead of hail." | hail | `src/battle_util.c:3449` | yes |
| S6 | `B_RECALC_TURN_AFTER_ACTIONS` (66) | "In Gen8+, switching or using a move affects the current turn's order of actions, better known as dynamic Speed." | the order set at the start of the turn is kept; switches run in battler order (`src/battle_main.c:5070-5079`) and are never sorted by Speed (`src/battle_main.c:5109`) | `src/battle_util.c:1088`: after each action the remaining actions are re-sorted, moves by current priority and Speed, switches by Speed (`src/battle_util.c:1120-1123`) | yes |
| S7 | `B_TRAINER_EXP_MULTIPLIER` (16) | "In Gen7+, Trainer battles no longer increase total experience by 1.5x." | x1.5 in trainer battles | `src/battle_script_commands.c:2245` (applied while `<= GEN_7`) | yes |
| S8 | `B_DISGUISE_HP_LOSS` (214) | "In Gen8+, when a disguised Mimikyu's Disguise is busted, upon changing to its Busted Form, it loses 1/8 of its max HP." | no HP loss (the Gen 7 rule) | `src/battle_util.c:4552` | yes |
| S9 | `B_TELEPORT_BEHAVIOR` (122) | "In LGPE onwards (Gen8+ here), Teleport switches the user out instead of fleeing." | Teleport fails in trainer battles | `data/battle_scripts_1.s:2344` (`jumpifgenconfiglowerthan ... GEN_8`) and `:2349` (fails in a trainer battle) | yes |
| S10 | `B_UPDATED_ABILITY_DATA` (88) | "Affects flags." | Zen Mode can be swapped, suppressed and overwritten | `src/data/abilities.h:1271` (`cantBeSwapped`), `:1273` (`cantBeSuppressed`), `:1274` (`cantBeOverwritten`), all `>= GEN_7`; read by Skill Swap (`src/battle_script_commands.c:7503`, `:7508`) and Doodle (`:7347-7348`) | no: data |
| S11 | `B_ENCORE_PRIORITY` (186) | "In Champions, Encore uses the priority of the Encored move instead of the selected move" | the selected move's priority | `src/battle_main.c:4830` (when priorities are computed) | yes |
| S12 | `B_SHEER_COLD_IMMUNITY` (50) | "In Gen7+, Ice-types are immune to Sheer Cold." | Ice types are not immune | data flag `src/data/moves_info.h:9058`; checked at `src/battle_util.c:8445`; the test hook `include/move.h:515-517` can only switch the immunity off | one way only: it can remove the immunity from a Gen 7+ build, not add it to this one |
| S13 | `B_SHEER_COLD_ACC` (94) | "In Gen7+, Sheer Cold's accuracy is reduced to 20% if the user isn't an Ice-type." | 30% for every user | data flag `src/data/moves_info.h:9059`, applied at `src/battle_util.c:10774` | no: data |
| S14 | `B_PARTING_SHOT_SWITCH` (111) | "In Gen7+, the user won't switch out if Parting Shot fails to lower the target's stats." | the user switches out whenever it can | `src/battle_move_resolution.c:4779` (`CanPartingShotTrigger`), called by the move-end switch step (`:4813-4814`); also `:5656` | yes |
| S15 | `B_SPEED_BUFFING_RAPID_SPIN` (99) | "In Gen8+, Rapid Spin raises the user's Speed by 1 stage if it hits." | no Speed boost, so Rapid Spin has no secondary effect for Sheer Force | data `src/data/moves_info.h:6265-6279`; Sheer Force needs a secondary effect (`src/battle_util.c:9884-9894`) and then skips the move-end effects (`src/battle_move_resolution.c:4208-4213`), hazard removal among them (`:4424-4433`) | no: data |
| S16 | `B_MIRROR_ARMOR_STICKY_WEB` (222) | "In Gen9+, Mirror Armor does not reflect the Sticky Web stat change even if the original Sticky Web user is still on the field" | the Gen 8 rule: the drop is reflected onto the Sticky Web setter | `src/battle_stat_change.c:741-749`; the drop is queued on `gBattleScripting.battler` (`:766-767`) | yes |
| S17 | `B_UPDATED_MOVE_DATA` (73) | "Updates move data in gMovesInfo, including Power, Accuracy, PP, category, range, and additional effects." | Thunder Wave 100% accurate | `src/data/moves_info.h:2333` (`>= GEN_7 ? 90 : 100`); a 100% roll is never made (`include/random.h:285-287`, used by `src/battle_util.c:10801`) | no: data |

## The 39 tests

In the order of `docs/gba-test-expected-failures.txt`. "Check" is the failing line and what the log reports.

| # | Test (list entry) and declaration | What it asserts, and what the Gen 6 build gives | Switch: Gen 6 vs later, and the code | Class | Proposed handling |
| --- | --- | --- | --- | --- | --- |
| 1 | `test/battle/ability/delta_stream.c: Delta Stream fails if overworld weather is present (Gen9)`; `delta_stream.c:144` | With overworld sun from the start, Mega Rayquaza's Delta Stream must fail ("But it failed!") and the sun stay. Gen 6: Delta Stream replaces the sun. Check `:155` `MESSAGE("But it failed!")` unmatched. | S1 `B_OVERWORLD_WEATHER_OVERRIDE`: Gen 6 lets the ability replace overworld weather, Gen 9 does not; `battle_util.c:2648`, `:2133`. | A | Keep listed. Option: `WITH_CONFIG(B_OVERWORLD_WEATHER_OVERRIDE, GEN_9);` in GIVEN, as `sand_spit.c:83`, `teraform_zero.c:148` and `orichalcum_pulse.c:159` do (they pass in this build). The Gen 6 side is already covered: `starting_status/weather.c:63` (pinned Gen 8) passes. In play: Mega Rayquaza is Gen 6. |
| 2 | `test/battle/ability/desolate_land.c: Desolate Land fails if overworld weather is present (Gen9)`; `desolate_land.c:260` | Same with Primal Groudon (Red Orb). Check `:271` `MESSAGE("But it failed!")` unmatched. | S1, as row 1. | A | As row 1. In play: Groudon is in `trainers.party`. |
| 3 | `test/battle/ability/electromorphosis.c: Electromorphosis sets up Charge when hit by any move 1/2`; `electromorphosis.c:4` | Bellibolt (faster) uses Thunder Shock, is then hit (parameter 1: Scratch) and charged; its next turn's Thunder Shock must do 2x. Gen 6: no boost. Check `:52` `EXPECT_MUL_EQ(76, 2.0, 76) failed: 152 not in [74..78]`. Parameter 2/2 (Gust) does not run. | S2 `B_CHARGE`: before Gen 9 the timer counts down at the end of the turn (`battle_end_turn.c:80`) and the ability sets it to 1 (`battle_scripts_1.s:3575`), so the Charge lapses at the end of the turn it was set; in Gen 9 it lasts until the next Electric move (`battle_move_resolution.c:5901`). | B | Keep listed. No test-side fix: the switch is compiled in, so a pin has no effect; it would need `GetConfig(B_CHARGE)` at the two lines (behavior-neutral, but an engine change). Electromorphosis is a Gen 9 ability; Tadbulb and Bellibolt are not in game content. |
| 4 | `test/battle/ability/electromorphosis.c: Electromorphosis triggers on each multistrike hit but Charge does not stack`; `electromorphosis.c:72` | After a turn in which Bellibolt is hit by Scratch, the next turn's Thunder Shock must do 2x (and Double Hit's two triggers must not stack). Gen 6: no boost. Check `:106` `EXPECT_MUL_EQ(67, 2.0, 67) failed: 134 not in [65..69]`. | S2, as row 3. | B | As row 3. |
| 5 | `test/battle/ability/flower_veil.c: Flower Veil does not prevent self-inflicted stat drops - abilities`; `flower_veil.c:119` | Slugma (Weak Armor), made Grass-type by Forest's Curse next to Comfey (Flower Veil), is hit by Scratch: Defense -1, Speed +2, no Flower Veil popup. Gen 6: Speed +1. Check `:141` `EXPECT_EQ(7, 8)`. | S3 `B_WEAK_ARMOR_SPEED`: Gen 5-6 +1 Speed, Gen 7+ +2; `battle_util.c:4014`. | A | Keep listed. Option: `WITH_CONFIG(B_WEAK_ARMOR_SPEED, GEN_7);` as `weak_armor.c:146` and `:185` do. The Gen 6 side is covered by `weak_armor.c:10` (its Gen 6 parameter passes). Comfey is scenery: Flower Veil is a Gen 6 ability. |
| 6 | `test/battle/ability/keen_eye.c: Keen Eye, Gen9+ Illuminate & Minds Eye prevent accuracy stage reduction from moves 2/3 (2/2)`; `keen_eye.c:10` | Pinned to Gen 9 (`WITH_CONFIG(B_ILLUMINATE_EFFECT, GEN_9)`). Parameter 2: Staryu's Illuminate must block Sand Attack ("accuracy was not lowered"). Gen 6: the drop goes through. Check `:10` "Expected 1.0 passes/successes, observed 0.0". Parameter 3/3 (Mind's Eye) does not run. | S4 `B_ILLUMINATE_EFFECT`: no battle effect before Gen 9. The pin cannot take effect: the block reads the constant (`battle_stat_change.c:822`), while the evasion half reads `GetConfig` (`battle_util.c:10610`), which is why the sibling "... ignore target's evasion stat" passes. | A | Keep listed. No test-side fix (the test already pins Gen 9). A behavior-neutral engine change (`GetConfig(B_ILLUMINATE_EFFECT)` at `:822`) would let the pin work; out of scope. In play: Illuminate does nothing in battle, as in Gen 6. |
| 7 | `test/battle/ability/mega_sol.c: Mega Sol ignores Snow's Ice-type Defense boost`; `mega_sol.c:149` | Vanilluxe's Snow Warning sets snow; Mega Meganium's Scratch with Mega Sol must do 1.5x the damage of the same Scratch after Skill Swap took Mega Sol away. Gen 6: equal damage. Check `:172` `EXPECT_MUL_EQ(32, 1.5, 32) failed: 48 not in [30..34]`. | S5 `B_SNOW_WARNING`: Gen 6 Snow Warning makes hail, which has no Defense boost to ignore; Gen 9 makes snow; `battle_util.c:3449`. | B | Keep listed. Option: `WITH_CONFIG(B_SNOW_WARNING, GEN_9);` (`snow_warning.c` pins it both ways and passes). Gen 6 side covered: "Snow Warning sets up hail for 5 turns (Gen6-8)" passes. Mega Meganium is in play (`tower_legends.party`, Meganiumite), but in this profile only the Gen 9 moves Snowscape and Chilly Reception make snow. |
| 8 | `test/battle/ability/primordial_sea.c: Primordial Sea fails if overworld weather is present (Gen9)`; `primordial_sea.c:234` | As row 1 with Primal Kyogre (Blue Orb). Check `:245` `MESSAGE("But it failed!")` unmatched. | S1, as row 1. | A | As row 1. In play: Kyogre is in `trainers.party`. |
| 9 | `test/battle/ability/wind_power.c: Wind Power sets up Charge for opponent when hit by a wind move 2/2`; `wind_power.c:63` | The opponent's Wattrel (faster) uses Nuzzle and is hit by Air Cutter (parameter 2); its next Nuzzle must do 2x. Gen 6: no boost. Check `:100` `EXPECT_MUL_EQ(16, 2.0, 16) failed: 32 not in [14..18]`. | S2, as row 3. | B | As row 3 (Wind Power is a Gen 9 ability; the Wattrel line is not in game content). |
| 10 | `test/battle/ability/wind_power.c: Wind Power sets up Charge for player when hit by a wind move 2/2`; `wind_power.c:18` | The same on the player's side. Check `:55` `EXPECT_MUL_EQ(16, 2.0, 16) failed: 32 not in [14..18]`. | S2, as row 3. | B | As row 3. |
| 11 | `test/battle/ai/check_bad_move.c: AI will not try to lower opposing stats if target is protected by it's ability 4/7`; `check_bad_move.c:6` | Pinned to Gen 9 for Illuminate. Parameter 4: the AI must score Sand Attack against Staryu (Illuminate) below the default 100. Gen 6: 100. Check `:26` "Unmatched SCORE_LT_VAL Sand Attack 100, got 100". Parameters 5-7 do not run. | S4: the AI asks `AI_CanAnyStatChange` (`battle_ai_util.c:6552`), which goes through `CanStatChange`, `CanDecreaseStat` and `IsAbilityBlocked` to the same constant check at `battle_stat_change.c:822`. | A | As row 6. |
| 12 | `test/battle/battle_message.c: Battle Message: STRINGID_INTROMSG, STRINGID_INTROSENDOUT, STRINGID_RETURNMON, and STRINGID_SWITCHINMON (2v1)`; `battle_message.c:175` | In a 2v1 double, both opposing Pokemon and the partner's Haunter switch on one turn; the messages must come opponent left, opponent right, then partner. Gen 6: the partner's switch comes between the two opponents'. Check `:199` `MESSAGE("3 withdrew Haunter!")` unmatched. | S6 `B_RECALC_TURN_AFTER_ACTIONS`. The runner gives every Pokemon without `Speed()` a distinct speed in party order, player first, then opponent, then partner (`test_runner_battle.c:361-388`): Wynaut 10, Haunter 7. Gen 6 keeps battler order (left, partner, right; `battle_main.c:5070-5079`); Gen 8+ re-sorts the remaining switches by Speed after the first one (`battle_util.c:1120-1123`) and puts Wynaut before Haunter. The Multi variant, whose speeds put Haunter first anyway, passes. | A (uncertain, see below) | Keep listed. Option: `WITH_CONFIG(B_RECALC_TURN_AFTER_ACTIONS, GEN_8);` (as `tailwind.c:65` and `quash.c:29` do). Farigiraf is scenery. |
| 13 | `test/battle/battle_message.c: Battle Message: STRINGID_INTROMSG, STRINGID_INTROSENDOUT, STRINGID_RETURNMON, and STRINGID_SWITCHINMON (AI 2v1)`; `battle_message.c:204` | The same with an AI opponent. Check `:229` `MESSAGE(AI_PARTNER_NAME " withdrew Haunter!")` unmatched (the log prints it as "?? TRAINER 1 withdrew Haunter!"). | S6, as row 12 (same implicit speeds). | A (uncertain, see below) | As row 12. |
| 14 | `test/battle/exp.c: Both opponent's Pokemon give experience in battle against two opponents`; `exp.c:217` | Pins scaled EXP and the unevolved bonus to Gen 3, not the trainer multiplier. A level 1 Metapod must end with 1 + Wynaut 52x100/7 + Wobbuffet 142x100/7 = 2771 EXP. Gen 6: 4156 = 1 + 1113 + 3042, each share x1.5. Check `:234` `EXPECT_EQ(4156, 2771)`. | S7 `B_TRAINER_EXP_MULTIPLIER`: Gen 6 gives x1.5 in trainer battles, later generations do not; `battle_script_commands.c:2245`. | A | Keep listed. Option: `WITH_CONFIG(B_TRAINER_EXP_MULTIPLIER, GEN_8);` (the code applies x1.5 up to and including `GEN_7`, so a Gen 7 pin would not do). The project's own `exp_two_opponents.c` (both fainting orders give the same EXP) passes. |
| 15 | `test/battle/hold_effect/air_balloon.c: Air Balloon pops when Disguise is broken 1/2`; `air_balloon.c:156` | Parameter 1: Aerial Ace breaks Mimikyu's Disguise; Mimikyu must lose HP and its Air Balloon pop. Gen 6: no HP lost. Check `:171` `HP_BAR(player)` unmatched. Parameter 2/2 (Totem Mimikyu) does not run. | S8 `B_DISGUISE_HP_LOSS`: no HP loss before Gen 8 (the profile uses the Gen 7 rule); `battle_util.c:4552`. | B | Keep listed. Option: `WITH_CONFIG(B_DISGUISE_HP_LOSS, GEN_8);` (as `focus_punch.c:115` and `reflect_damage.c:253` do). The Gen 7 side is covered: "Disguised Mimikyu doesn't lose 1/8 of its max HP upon changing to its busted form (Gen7)" passes. Mimikyu is not in game content. |
| 16 | `test/battle/hold_effect/white_herb.c: White Herb wont have time to activate if Magician steals it`; `white_herb.c:162` | Fennekin's (Magician) Scratch triggers Slugma's Weak Armor; Magician must steal the White Herb before it restores Defense. Gen 6: Speed +1 ("rose!" rather than "rose sharply!"). Check `:174` `MESSAGE("Slugma's Speed rose sharply!")` unmatched. | S3, as row 5. | A | As row 5. Aside: the test's THEN lines use `=` instead of `==` (always true), so only the message decides it. |
| 17 | `test/battle/hold_effect/white_herb.c: White Herb wont have time to activate if it is knocked off or stolen by Thief 1/2`; `white_herb.c:127` | The same with Thief (parameter 1). Check `:146` `MESSAGE("Slugma's Speed rose sharply!")` unmatched. Parameter 2/2 (Knock Off) does not run. | S3, as row 5. | A | As row 16. |
| 18 | `test/battle/move_animations/all_anims.c: Move Animations work 4 25/222`; `all_anims.c:2576` | Plays every fourth move's animation (moves 4, 8, ... 844, with variations: 222 parameters) and checks for leaks. Parameter 25 is Teleport (move 100; moves 4 to 96 have one parameter each). For moves that switch the user out the test schedules `SEND_OUT` (`all_anims.c:146-150`, `:317-320`). Gen 6: Teleport does not switch. Check `:2576`, result INVALID: "SEND_OUT not required (is the send out random?)". Parameters 26-222 do not run. | S9 `B_TELEPORT_BEHAVIOR`: before Gen 8 Teleport fails in a trainer battle; Gen 8+ switches; `battle_scripts_1.s:2344`, `:2349`. | A | Keep listed. Option: `WITH_CONFIG(B_TELEPORT_BEHAVIOR, GEN_8);` in this test's GIVEN (only Teleport reads it). That would also run parameters 26-222 in this build for the first time, with unknown results. The Gen 6 side is covered: "Teleport fails in Trainer Battles (Gen 1-7)" passes. |
| 19 | `test/battle/move_effect/assurance.c: Assurance doubles in power if Disguise has been broken`; `assurance.c:461` | Assurance on a Mimikyu whose Disguise broke earlier the same turn must do 2x the Assurance on one broken the turn before. Gen 6: equal. Check `:490` `EXPECT_MUL_EQ(19, 2.0, 19) failed: 38 not in [17..21]`. | S8: from Gen 8 the 1/8 HP that busting costs counts as damage taken this turn; the profile's Gen 7 rule costs no HP; `battle_util.c:4552`. | B | As row 15. |
| 20 | `test/battle/move_effect/charge.c: Charge's effect does not stack with Electromorphosis or Wind Power 1/2`; `charge.c:76` | Parameter 1: Wattrel (Wind Power) uses Charge, then is hit by Air Cutter; the next turn's Thunderbolt must do exactly 2x (Charge and Wind Power not stacking). Gen 6: no boost at all. Check `:102` `EXPECT_MUL_EQ(93, 2.0, 93) failed: 186 not in [91..95]`. Parameter 2/2 (Tadbulb) does not run. | S2: Charge sets the timer to 2 (`battle_move_resolution.c:5702`); Wind Power then sets it to 1 (`battle_scripts_1.s:3575`) and the countdown before Gen 9 (`battle_end_turn.c:80`) clears it that turn. | B | As row 3. Worth knowing: under the old rule the ability cuts an existing Charge short, so the holder is worse off than without it. There is no Gen 1-8 game to compare with, and the combination is not in this game. |
| 21 | `test/battle/move_effect/chilly_reception.c: Chilly Reception fails if it can't switch the user out or change the weather`; `chilly_reception.c:125` | Against Alolan Ninetales (Snow Warning) and with no Pokemon to switch to, Chilly Reception must fail (no animation, "But it failed!"). Gen 6: it works. Check `:134` "Matched ANIMATION". | S5: Snow Warning makes hail in Gen 6, and Chilly Reception makes snow (`moves_info.h:21196`, since `B_PREFERRED_ICE_WEATHER` is "both"), so it can change the weather; `battle_util.c:3449`. | B | Keep listed. Option: `WITH_CONFIG(B_SNOW_WARNING, GEN_9);`. Chilly Reception is a Gen 9 move. |
| 22 | `test/battle/move_effect/chilly_reception.c: Chilly Reception switches the user out even if it can't change the weather`; `chilly_reception.c:108` | The weather part must fail ("But it failed!") and the user still switch. Gen 6: the hail becomes snow. Check `:119` `MESSAGE("But it failed!")` unmatched. | S5, as row 21. | B | As row 21. |
| 23 | `test/battle/move_effect/doodle.c: Doodle fails if ally's ability can't be suppressed 2/15`; `doodle.c:85` | Parameter 2: with Darmanitan (Zen Mode) as the user's ally, Doodle must fail. Gen 6: it works. Check `:114` "Matched ANIMATION". Parameters 3-15 do not run. | S10 `B_UPDATED_ABILITY_DATA`: Zen Mode cannot be suppressed only from Gen 7 (`src/data/abilities.h:1273`); Doodle reads that flag (`battle_script_commands.c:7347-7348`). Showdown's Gen 6 data agrees: its Zen Mode has no `cantsuppress` or `failskillswap` flag. | B | Keep listed. No pin (ability flags are data). Option: leave the Zen Mode parameter out when `B_UPDATED_ABILITY_DATA < GEN_7` (`#if` around that `PARAMETRIZE`); parameters 3-15 would then run here for the first time, results unknown. Doodle is a Gen 9 move; the Zen Mode rule itself is the Gen 6 one (row 31). |
| 24 | `test/battle/move_effect/encore.c: Encore uses the priority of the Encored move on the turn the target is Encored instead of the selected move (Champions)`; `encore.c:389` | Pinned to Champions. A Prankster Encore turns the foe's chosen Quick Attack (+1) into Scratch (0), which must then move after the ally's Celebrate. Gen 6: Scratch still goes first. Check `:414` `ANIMATION(ANIM_TYPE_MOVE, MOVE_SCRATCH, opponentLeft)` unmatched. | S11 `B_ENCORE_PRIORITY` (pinned; read when priorities are computed, `battle_main.c:4830`) needs S6: before Gen 8 the order set at the start of the turn, with Quick Attack's +1, is never recomputed (`battle_util.c:1088`), so the new priority never applies. Gen 6 uses the selected move's priority, exactly what the passing sibling "... (Gen9)" (`encore.c:359`) expects. | A | Keep listed. Option: add `WITH_CONFIG(B_RECALC_TURN_AFTER_ACTIONS, GEN_8);` beside the Champions pin. |
| 25 | `test/battle/move_effect/ohko.c: Sheer Cold doesn't affect Ice-type Pokémon (Gen7+)`; `ohko.c:210` | Pinned to Gen 7. Sheer Cold against Glalie must not play and print "It doesn't affect...". Gen 6: it hits. Check `:220` "Matched ANIMATION". | S12 `B_SHEER_COLD_IMMUNITY`: Ice types are immune from Gen 7. The immunity is a data flag compiled from the build's value (`moves_info.h:9058`); the test hook (`include/move.h:515-517`) can only turn it off, so the Gen 7 pin cannot turn it on here. | A | Keep listed. No test-side fix (the pin is already there). The Gen 6 side is covered by `ohko.c:194`, pinned to Gen 6, which asserts that Sheer Cold does hit Glalie (its title says "doesn't affect", the body checks the opposite) and passes. |
| 26 | `test/battle/move_effect/ohko.c: Sheer Cold's accuracy decreasaes by 10% if the user is not Ice type (2/2)`; `ohko.c:225` | A non-Ice user's Sheer Cold must hit 20% of the time. Gen 6: 30%. Check `:225` "Expected 0.199 passes/successes, observed 0.299" (trial 2 of 2). | S13 `B_SHEER_COLD_ACC`: 30% for everyone before Gen 7, 20% for non-Ice users from Gen 7; data flag `moves_info.h:9059`, applied at `battle_util.c:10774`. | A | Keep listed. No pin (data). Option: `ASSUME(MoveDecreasesAccIfUserNotSameType(MOVE_SHEER_COLD));` would turn it into an assumption skip in this build. |
| 27 | `test/battle/move_effect/parting_shot.c: Parting Shot: Magic Bounce bounces it and switches the target out and original user doesn't switch out`; `parting_shot.c:89` | Espeon's Magic Bounce reflects Parting Shot: the user's Attack and Sp. Atk drop, Espeon switches out (`SEND_OUT(opponent, 1)`), the user stays. Gen 6: the battle asks for an input the test did not script. Check `:89` "TURN 1 incomplete". | S14 `B_PARTING_SHOT_SWITCH`: before Gen 7 `CanPartingShotTrigger` returns TRUE whenever the user can switch (`battle_move_resolution.c:4779`), at the move-end switch step (`:4813-4814`), without asking whether the move hit, was blocked or was reflected. So the original user is sent to the party screen as well. | C | Keep listed for now and investigate (see "Possible defects"). Do not pin or rewrite the test: in Showdown's Gen 6 model its expectation holds for Gen 6 too. A fix would change game behavior (owner's decision). |
| 28 | `test/battle/move_effect/parting_shot.c: Parting Shot: Magic Coat bounces it and switches the target out and original user doesn't switch out`; `parting_shot.c:73` | The same with the target's Magic Coat (used first, priority +4). Check `:73` "TURN 1 incomplete". | S14, as row 27. | C | As row 27. |
| 29 | `test/battle/move_effect/parting_shot.c: Parting Shot: Soundproof and Good as Gold block Parting Shot 1/2`; `parting_shot.c:28` | Parameter 1: Exploud's Soundproof blocks Parting Shot ("It doesn't affect..."): no animation, no drops, the user stays. Gen 6: the turn wants an unscripted input. Check `:28` "TURN 1 incomplete". Parameter 2/2 (Good as Gold) does not run. | S14: Soundproof's block (`battle_util.c:2437-2439`) is a script call that returns (`data/battle_scripts_1.s:4913-4918`), so the move still reaches the move-end step where `:4779` switches the user out. | C | As row 27. |
| 30 | `test/battle/move_effect/rapid_spin.c: Rapid Spin doesn't blow away Wrap, hazards or raise Speed when Sheer Force boosted (Gen 9+)`; `rapid_spin.c:148` | Tauros (Sheer Force) uses Rapid Spin while Wrapped and with Stealth Rock on its side; nothing must be removed. Gen 6: it is freed and the rocks go. Check `:167` "Matched MESSAGE" ("Tauros was freed from Wrap!"). | S15 `B_SPEED_BUFFING_RAPID_SPIN`: before Gen 8 Rapid Spin has no secondary effect (`moves_info.h:6265-6279`), so Sheer Force does not apply to it (`battle_util.c:9884-9894`) and the hazard removal runs (`battle_move_resolution.c:4424-4433`). The test's own `#if` removes only the Speed part. | A | Keep listed. No pin (data). Option: `ASSUME(MoveIsAffectedBySheerForce(MOVE_RAPID_SPIN));` would make it an assumption skip, like its two "(Gen 8)" siblings already are in this build. "Rapid Spin blows away all hazards" passes. |
| 31 | `test/battle/move_effect/skill_swap.c: Skill Swap fails if user or target has an ability that can't be swapped 4/27`; `skill_swap.c:68` | Parameter 4: Skill Swap with Darmanitan (Zen Mode) must fail both ways. Gen 6: it works. Check `:107` "Matched ANIMATION". Parameters 5-27 do not run. | S10: Zen Mode cannot be swapped only from Gen 7 (`src/data/abilities.h:1271`); Skill Swap reads that flag (`battle_script_commands.c:7503`, `:7508`). Showdown's Gen 6 data agrees (no `failskillswap` on Zen Mode). | A | Keep listed. Option: the same `#if` as row 23; parameters 5-27 would then run here for the first time, results unknown. In play: Darmanitan and Skill Swap are both in Gen 6. |
| 32 | `test/battle/move_effect/sticky_web.c: Sticky Web has correct interactions with Mirror Armor - no one has their Speed lowered if the set upper fainted 1/2`; `sticky_web.c:192` | Parameter 1: Caterpie sets Sticky Web and faints (Memento); later Corviknight (Mirror Armor, Iron Ball) switches into the web; nobody's Speed may drop. Gen 6: playerLeft, the Corviknight's uninvolved ally, loses one Speed stage. Check `:240` `EXPECT_EQ(5, 6)`. Parameter 2/2 does not run. | S16 `B_MIRROR_ARMOR_STICKY_WEB`: Gen 9 reflects nothing. Before Gen 9 the drop goes to the setter recorded in `stickyWebBattlerId` (`battle_stat_change.c:741-749`), but that id is cleared when the setter leaves the field (`battle_main.c:3236-3237`); the branch then leaves `gBattleScripting.battler` as it was, and the drop is queued on whatever battler that names (`:766-767`). | C | Keep listed. Not reachable in this game: Mirror Armor belongs to the Corviknight line (Gen 8), not in game content. An upstream defect in the Gen 8 branch, worth reporting upstream. Do not pin to Gen 9: that would skip the defect rather than test it. Where the setter is still there, the Gen 8 tests pass ("... the battler which set up Sticky Web has its Speed lowered instead (Gen8)", `mirror_armor.c:267`). |
| 33 | `test/battle/move_effect/sticky_web.c: Sticky Web has correct interactions with Mirror Armor - no one has their Speed lowered if the set upper switched 1/2`; `sticky_web.c:148` | Parameter 1: both sides set Sticky Web, the opposing setter switches out, then Corviknight switches in; nobody's Speed may drop. Gen 6: playerLeft loses one stage. Check `:185` `EXPECT_EQ(5, 6)`. Parameter 2/2 does not run. | S16, as row 32. | C | As row 32. |
| 34 | `test/battle/spread_moves.c: Spread Moves: AOE move vs Eiscue and Mimikyu (Based on vanilla games)`; `spread_moves.c:224` | Earthquake breaks Mimikyu's Disguise (which must cost it 1/8 of its HP) and both Eiscue's Ice Face (no HP). Gen 6: no HP loss. Check `:240` `HP_BAR(opponentLeft, captureDamage: &disguiseDamage)` unmatched. | S8, as row 15. | B | As row 15 (Eiscue is Gen 8). |
| 35 | `test/battle/status1/paralysis.c: Thunder Wave prints an avoided attack message when it misses`; `paralysis.c:110` | Thunder Wave forced to miss (`hit: FALSE`) must print "The opposing Wobbuffet avoided the attack!". Gen 6: it hits. Check `:119` that message unmatched. | S17 `B_UPDATED_MOVE_DATA`: Thunder Wave is 100% accurate before Gen 7, 90% from Gen 7 (`moves_info.h:2333`); at 100% no roll is made (`include/random.h:285-287`), so a forced miss cannot happen. | A | Keep listed. No pin (data). Option: make a miss possible in every generation (for example the target holds a Bright Powder), or `ASSUME(GetMoveAccuracy(MOVE_THUNDER_WAVE) < 100)` to skip it. |
| 36 | `test/battle/trainer_slides.c: Trainer Slide: Doubles: Opponent Mon Unaffected`; `trainer_slides.c:642` | Pinned to Gen 7 for Sheer Cold. The trainer slide for "a move did not affect the opponent's Pokemon" must show after the AI's Sheer Cold fails against Glalie. Gen 6: Sheer Cold hits. Check `:656` "Matched ANIMATION". | S12, as row 25: the Gen 7 pin cannot add the immunity in this build. | A | Keep listed. Option: build the "unaffected" case on an immunity Gen 6 has (for example a Normal-type move into a Ghost-type, the only move the AI has), which would make the test meaningful here. These four tests are about trainer slides, not Sheer Cold; the "Mon Unaffected" slides have no passing test in this build. |
| 37 | `test/battle/trainer_slides.c: Trainer Slide: Doubles: Self Mon Unaffected`; `trainer_slides.c:619` | The same for the player's Sheer Cold against the opponent's Glalie. Check `:633` "Matched ANIMATION". | S12, as row 25. | A | As row 36. |
| 38 | `test/battle/trainer_slides.c: Trainer Slide: Singles: Opponent Mon Unaffected`; `trainer_slides.c:156` | Singles version of row 36. Check `:168` "Matched ANIMATION". | S12, as row 25. | A | As row 36. |
| 39 | `test/battle/trainer_slides.c: Trainer Slide: Singles: Self Mon Unaffected`; `trainer_slides.c:173` | Singles version of row 37. Check `:185` "Matched ANIMATION". | S12, as row 25. | A | As row 36. |

## Summary

| Class | Count | Rows |
| --- | --- | --- |
| (A) Intended Gen 6 behavior | 22 | 1, 2, 5, 6, 8, 11, 12, 13, 14, 16, 17, 18, 24, 25, 26, 30, 31, 35, 36, 37, 38, 39 |
| (B) Cannot express Gen 6 | 12 | 3, 4, 7, 9, 10, 15, 19, 20, 21, 22, 23, 34 |
| (C) Possible real defect | 5 | 27, 28, 29, 32, 33 |
| Total | 39 | |

No (A) or (B) row calls for a change to the game. For many rows, the older side of the switch is also pinned by an
upstream test that passes in this build:

| Rows | Older rule | Passing test |
| --- | --- | --- |
| 1, 2, 8 | Overworld weather can be replaced | `starting_status/weather.c:63` |
| 5, 16, 17 | Weak Armor gives +1 Speed | `weak_armor.c:10` |
| 7, 21, 22 | Snow Warning makes hail | "Snow Warning sets up hail for 5 turns (Gen6-8)" |
| 3, 4, 9, 10, 20 | Charge before Gen 9 | "Charge's effect is removed regardless if the next move is Electric or not (Gen 3-8)" |
| 15, 19, 34 | Disguise before Gen 8 | "Disguised Mimikyu doesn't lose 1/8 of its max HP upon changing to its busted form (Gen7)" |
| 18 | Teleport | "Teleport fails in Trainer Battles (Gen 1-7)" |
| 24 | Encore | `encore.c:359` |
| 25, 36-39 | Sheer Cold against Ice types | `ohko.c:194` |
| 27-29 | Parting Shot switches after failed drops | the three "(Gen6)" Parting Shot tests |
| 32-33 | Mirror Armor with the setter present | `mirror_armor.c:267` |

### Possible defects (C)

1. **Parting Shot switches its user out after being blocked or reflected (rows 27-29; reachable in this game).** **Decided 2026-11-14 (the owner's decision #63): the PC game follows the Gen 6 rule** - the user switches out only when the move reached its target (engine `9624a0a4`, PC only; tested in real games by `tools/battle_env/parting_shot_check.py`, KNOWN_ISSUES "Parting Shot (Gen 6)"). The GBA build keeps upstream's rule, so these three tests still fail there and stay listed. The
   pre-Gen 7 branch (`src/battle_move_resolution.c:4779`) lets the user switch whenever it can, at the move-end step
   (`:4813-4814`), even when Soundproof blocked the move or Magic Coat or Magic Bounce reflected it. With a reflection
   both the reflecting Pokemon and the original user switch out. Evidence:
   * the code above;
   * all three tests fail with "TURN 1 incomplete", the battle asking for an input the test did not script, and pass
     under Gen 7+, where the switch needs a stat change;
   * upstream's own Gen 6 tests (`parting_shot.c` "Switches if both stats are at minimum (Gen6)", "Switches if
     Contrary is at maximum stats (Gen6)", "Stat drop prevention by abilities/items switches (Gen6)", all passing)
     cover only a move that landed but whose stat drops failed;
   * Pokemon Showdown's Gen 6 model differs: its Gen 6 Parting Shot changes only `onHit` (`data/mods/gen6/moves.ts`),
     Soundproof and Magic Bounce return `null` from `onTryHit` (`data/abilities.ts`), and the user's switch flag is
     set only in `runMoveEffects` after a hit (`sim/battle-actions.ts`). So a blocked or reflected Parting Shot does
     not switch the original user out, and with Magic Coat or Bounce only the reflecting Pokemon switches.

   In play: a player's Pangoro learns Parting Shot at level 48 (`src/data/pokemon/level_up_learnsets/gen_6.h:15723`;
   Pancham is in the multiplayer wild pool, `src/data/mp_wild_pool.h:1007`); the Whismur line (Soundproof) is in the
   wild tables; a Tower Legends Xatu has Magic Bounce; Magic Coat is a Gen 3 move.
2. **Mirror Armor's pre-Gen 9 Sticky Web reflection hits a stale battler when the setter has left (rows 32-33; not
   reachable in this game).** When the Sticky Web setter has fainted or switched out, `stickyWebBattlerId` is cleared
   (`src/battle_main.c:3236-3237`), the branch at `src/battle_stat_change.c:741-749` sets no target, and the drop is
   queued on whatever `gBattleScripting.battler` last named (`:766-767`). In both tests that was the Mirror Armor
   holder's own ally (`EXPECT_EQ(5, 6)` on playerLeft). The expected result, nobody affected, is what both the Gen 8
   rule (as upstream implements it) and the Gen 9 rule give. No Mirror Armor Pokemon is in this game's content.

### Other engine findings (not game defects)

* **Pins that cannot take effect.** Seven tests already pin the later generation and still fail, because the engine
  reads the switch as a constant or as data: `B_ILLUMINATE_EFFECT` at `src/battle_stat_change.c:822` (rows 6, 11) and
  the one-way Sheer Cold test hook at `include/move.h:515-517` (rows 25, 36-39). `B_CHARGE` (rows 3, 4, 9, 10, 20),
  `B_UPDATED_ABILITY_DATA` (23, 31), `B_SHEER_COLD_ACC` (26), `B_SPEED_BUFFING_RAPID_SPIN` (30) and
  `B_UPDATED_MOVE_DATA` (35) cannot be pinned at all. The game is unaffected: outside tests `GetConfig` returns the same
  value.
* `B_TRAINER_EXP_MULTIPLIER`'s comment says Gen 7 dropped the x1.5, but the code applies it up to and including Gen 7
  (`src/battle_script_commands.c:2245`, `:12740`). That matters only for a Gen 7 profile; Gen 6 gets x1.5 either way.

### Coverage the list hides

A parametrized test stops at its first failing parameter, so these parameters never run in this build while their
test is listed:

* Move Animations work 4: parameters 26-222, the animations of every fourth move from 104 to 844.
* Skill Swap: 5-27.
* Doodle: 3-15.
* AI check_bad_move: 5-7.
* Keen Eye: 3/3.
* The second parameter of rows 3, 15, 17, 20, 29, 32 and 33.

The four "Mon Unaffected" trainer slides (rows 36-39) have no passing test either.

## How the list and its checker keep a new failure from going unnoticed

* `make check` exits non-zero whenever any test fails (2 with these 39), so its exit status cannot tell 39 failures
  from 40. The gate is `python scripts/diagnostics/check_gba_test_failures.py <make-check log>`.
* The checker reads the log's "FAILED tests:" block, with colours stripped. The runner reports every FAIL, INVALID,
  ERROR, TIMEOUT, CRASH and unexpected FLAKY result there (`test/test_runner.c:510`). It reduces each line to
  `file: title`, dropping the declaration line and the trailing `: <line>: <detail>` (checker lines 19-35). The title
  keeps the runner's `N/M` and `(t/T)`, so the failing parameter is part of the key.
* Any failing key that is not in `docs/gba-test-expected-failures.txt` is printed as `NEW FAILURE`, and the checker
  exits 1.
* A listed key that did not fail is printed as `no longer fails (remove it from the list)`, with exit 0.
* A log without the block gives exit 2, so an incomplete run cannot pass as clean.
* `--write` rewrites the list from a log. Use it only after an expansion upgrade or a deliberate configuration change.
* Every recorded full run since the list was added (2026-10-15) was compared name by name this way (TEST_LEDGER:
  "exactly the expected 39", exit 0).
* The checker's own unit test, `tests/test_gba_test_failures.py`, covers parsing and the three exit statuses. It
  passed (4 of 4) when run for this document.

What it does not catch:

* **A listed test that starts failing differently.** A new assertion or message still matches the key, because the
  detail is dropped. This matters most for the (C) rows and for the rows whose pin cannot take effect.
* **Later parameters.** A regression in a parameter after a listed test's first failing one is invisible (see
  "Coverage the list hides"). One in an earlier parameter changes the key's `N/M` and is caught as one new failure and
  one "no longer fails".
* **Skips and known failures.** Assumption skips (15), known-failing (19) and expected-failing (9) tests are not
  compared with a baseline. A test that newly hits an `ASSUME` drops out silently; only the counts in TEST_LEDGER
  would show it.
* **Long failure lists.** The runner lists at most 50 failures and then prints "and N more..."
  (`tools/mgba-rom-test-hydra/main.c:75`, `:855-856`). Past 50 the gate still fails, since at least 11 of the 50
  listed would be new, but not every new name is printed; the "Tests FAILED: N" line has the full count.

## Not classified with certainty

* **Rows 12-13 (2v1 messages), A or C.** That `B_RECALC_TURN_AFTER_ACTIONS` alone separates the Gen 6 and Gen 9
  results follows from the code and the runner's implicit speeds; the Multi variant, which passes, fits the same
  account. Two pieces of evidence would settle the class:
  * Confirm the cause: in a scratch copy, add `WITH_CONFIG(B_RECALC_TURN_AFTER_ACTIONS, GEN_8);` to the two tests and
    run `make check TESTS="Battle Message: STRINGID_INTROMSG"`; they should pass.
  * Decide A or C: a cartridge-accurate source for the order of simultaneous switches in Gen 6 doubles. Showdown sorts
    switches by Speed at the start of the turn in every generation (`sim/battle-queue.ts`: switches share one order
    and are sorted by Speed; the queue is "not sorted mid-turn in Gen 1-7"). That would give these tests' order
    without dynamic Speed. The engine keeps Emerald's battler order for every generation before 8. If Gen 6 sorts by
    Speed, these two rows are (C): an engine-wide pre-Gen 8 ordering that decides, in doubles, whose switch-in ability
    goes first.
* **Rows 27-29 (Parting Shot), C.** That the user is switched out is inferred from the code and from "TURN 1
  incomplete".
  * Engine side: in a scratch copy pinned `WITH_CONFIG(B_PARTING_SHOT_SWITCH, GEN_6)`, add `SEND_OUT(player, 1)` to
    the three tests and run `make check TESTS="Parting Shot"`. If the turn then completes and the user is Wynaut
    afterwards, the engine switches it out.
  * The rule: a Gen 6 cartridge reference for Parting Shot against Soundproof, Magic Coat and Magic Bounce. Showdown's
    Gen 6 model says no switch; Bulbapedia was not reachable from this session.
* **Rows 32-33 (Sticky Web), C.** The engine side is shown directly by playerLeft's lost Speed stage. The rule that
  nobody is affected once the setter has gone rests on upstream's design: the test titles, and the id cleared when
  the setter leaves. It was not checked against Sword and Shield; a reference for that would settle it. It has no
  bearing on this game.
* **Rows 3, 4, 9, 10, 20 (Charge with Electromorphosis or Wind Power), B.** The mechanism is certain. No Gen 1-8 game
  has these abilities, so there is no "correct" Gen 6 result to test against.
* **Row 18, parameter 25 = Teleport.** This is computed from the test's parametrization (`MOVES_COUNT` is 848; moves 4
  to 96 have one parameter each); the log does not print the move. To confirm, run `make check TESTS="Move Animations
  work 4"` with `WITH_CONFIG(B_TELEPORT_BEHAVIOR, GEN_8)` added: parameter 25 should then pass.

## Cross-check with docs/gba-test-expected-failures.txt

The 39 rows above use exactly the 39 entries of `docs/gba-test-expected-failures.txt` (copied verbatim, compared by
script): none missing, none extra, no duplicates. The same 39 are the "FAILED tests:" block of each of the three
saved runs (the checker: 0 new, 0 listed but passing). **No mismatch.**

## Where this differs from docs/gba-test-failures.md

That review grouped the 39 and marked several groups "title only". This document checks each test against the code:

* Parting Shot (rows 27-29) is a possible defect, not only a Gen 7 change.
* Sticky Web with Mirror Armor (rows 32-33) exposes a defect in the Gen 8 branch that this game cannot reach.
* The "title only" group is resolved:
  * 2v1 messages: dynamic Speed (S6);
  * trainer slides: the one-way Sheer Cold hook (S12);
  * Thunder Wave: 100% accuracy before Gen 7 (S17);
  * move animations: Teleport (S9);
  * AI check_bad_move: the constant Illuminate check (S4).
* Mega Sol fails over snow (S5) rather than a Champions rule.
* Encore fails for lack of dynamic Speed (S6) despite its Champions pin.
* Chilly Reception: Snow Warning makes hail in Gen 6 (S5).
* Doodle and Skill Swap: Zen Mode's Gen 5-6 flags (S10).
