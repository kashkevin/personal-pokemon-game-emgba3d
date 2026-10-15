# The 39 upstream GBA test failures (Gen 6 profile)

`make check` in the engine builds the expansion's test ROM and runs it headless. Re-run on 2026-10-15 (engine
`claude/dev-stability-engine`, before the keybind commits' merge into anything): **6000 tests, 5498 passed, 39 failed,
15 assumption-skips, 18 known failing, 9 expected failing, 421 to do** — the same 39 as the 2026-10-14 run. The test
ROM is built from the GBA objects, which the keybind, clock and M27 work did not change (the GBA ROM stays
`f214735b…3387`).

## Verdict

**No genuine bug was found among the 39.** They fail because the game runs Gen 6 rules (`GEN_LATEST` is `GEN_6`
in `include/config/general.h`) and the upstream tests are written for later generations without pinning one.
Evidence: (1) on 2026-10-14 every one of them passed when the test ROM was built with upstream's `GEN_LATEST GEN_9`,
so none is a code regression; (2) the titles and test sources below name a rule of a later generation, a
Pokémon/ability/move that is not in a Gen 1-6 game, or text that differs by generation.

What this review does **not** show: that each Gen 6 result equals what the real Gen 6 games do. Where I know the rule
(marked *known*) the Gen 6 behaviour is the old one; where I only read the title it is marked *title*.

| Group (tests) | Why it fails under Gen 6 | Basis |
| --- | --- | --- |
| Overworld-weather abilities: Delta Stream, Desolate Land, Primordial Sea (3) | "fails if overworld weather is present" is Gen 9 | known |
| Electromorphosis ×2, Wind Power ×2, Charge not stacking (5) | Gen 8/9 abilities; Charge's stacking rule is Gen 9; no Gen 1-6 Pokémon has them | known |
| Disguise: Assurance, Air Balloon (2); Eiscue/Mimikyu spread moves (1) | Gen 7/8 species and the Gen 8+ Disguise rules | known |
| Sticky Web with Mirror Armor ×2 | Mirror Armor is a Gen 8 ability | known |
| Mega Sol (1), Encore priority (1) | marked "Champions" in the test titles | known |
| Sheer Cold ×2 (Ice immunity Gen 7+, 20% accuracy for non-Ice), Keen Eye Gen 9 (1), Rapid Spin Gen 9 (1) | later-generation rules | known |
| Chilly Reception ×2, Doodle (1), Skill Swap list (1) | Gen 9 / Gen 7 moves and abilities newer than Gen 6 | title |
| Flower Veil + Weak Armor (1), White Herb ×2 | the tests expect Weak Armor's Speed +2 (Gen 7); Gen 6 gives +1 (observed 7 vs 8 stages) | known |
| Parting Shot ×3 | Gen 7 changed when it switches the user out | title (not checked against Gen 6) |
| Trainer EXP, two opponents (1) | observed 4156 vs expected 2771 = ×1.5: the Gen 6 trainer multiplier (`B_TRAINER_EXP_MULTIPLIER <= GEN_7`); this game's own test (`exp_two_opponents.c`) covers the two-opponent slot fix and passes | known |
| Battle message 2v1 ×2, trainer slides ×4, Thunder Wave "avoided the attack" (1), move animations send-out (1), AI check_bad_move (1) | text, animation and trainer-feature defaults that depend on the generation setting | title only: the most likely to hide something, but each passed under Gen 9 |

(53 titles appear in the log: 39 failures and 14 assumption-skips; the skips — Howl, Forewarn, Gulp Missile, Throat Spray,
AI risky, Trainer Class Balls, Comatose, Rapid Spin Gen 8, Sheer Cold flags — are tests whose precondition (a move's or
species' data in this generation) is not met, and are not counted as failures.)

## Policy and the gate

**Recommendation (owner decision 13 in `owner-decisions.md`):** do not edit upstream tests. The failures are listed in
`docs/gba-test-expected-failures.txt`; `scripts/diagnostics/check_gba_test_failures.py make-check.log` fails if a test
outside that list fails and reports a listed test that now passes. Regenerate the list with `--write` only after an
expansion upgrade or a deliberate configuration change. The group "title only" above is the first place to look if
the Gen 6 behaviour of the game is questioned.
