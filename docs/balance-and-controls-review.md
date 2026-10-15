# Balance and controls review (Update 24)

Confirmed bugs are listed first and separately from recommendations. **No established rule was changed.** All checks are
simulation (unit tests, selftests, reading the engine's own data); no real play.

## Confirmed defects (fixed)
1. **Xbox B did nothing.** `GAMEPAD_B` was defined but never mapped; only the left face button (X) was the GBA B. A player
   pressing the usual Cancel/Back button on an Xbox pad got no response in menus. Now both X and B are the GBA B (engine
   `src/platform/gamepad.c`; an older unit test had pinned "B: no game button" as the oracle, so this is a **deliberate change of a pinned behaviour**: revert it if you prefer the old layout; 9 new checks of the whole pad table in `--selftest-keybinds`: 30 checks, 0 failed).
2. **Documentation error:** `frontier_rewards.py` and `owner-decisions.md` said the host's BP shop is "priced like the game's Exchange
   Service Corners". It is not (table below). The numbers are unchanged; the text now states them.

## Controls verification
* Keyboard rebinding: engine self-test through the real SDL event loop (conflicts, swap, reserved keys F1-F12/Esc, Ctrl+R chord, file round
  trip, defaults when lines are missing) passes; menus never follow the bindings (their own arrows/Enter/Esc), F10 and the launcher's
  *Restore defaults* always recover a bad binding. Keyboard-only play needs nothing but a keyboard (every game and menu action is a key).
* Pad (Windows XInput / SDL controller): A→A, **B→B (new)**, X→B, Start, Back→Select, shoulders→L/R, d-pad and left stick→directions,
  Y→details, right trigger→fast forward. A pad is always combined with the keyboard, so rebinding never disables a pad.
* Not verified: a real pad on a real Windows machine; rebinding the pad (not a feature).

## Battle Points and the shop (balance review; recommendations, not changes)
Host rates (`frontier_rewards.py`): a normal round pays `1 + set//2` BP, a Brain round (every 7th) `3 + 2*set`, a repeat half (min 1).
Cumulative first-time BP: 9 after 7 rounds, 20 after 14, **39 after 21**, 60 after 28, 159 after 49 rounds.

| Item | Host shop | The game's own Exchange Service Corner |
|---|---|---|
| Vitamins (Protein, Iron, Calcium, Zinc, Carbos, HP Up) | 16 | **1** |
| Quick Claw | 32 | 48 |
| King's Rock | 32 | 64 |
| Focus Band | 32 | 64 |
| Leftovers | 48 | 48 |
| Choice Band | 64 | 64 |

Both shops spend **the same BP counter in the save**, so a player can buy a vitamin for 1 BP at the corner what costs 16 here.
Recommendations for the owner: (a) price vitamins at 1 BP (or accept that the host shop is the "expensive" one); (b) price Quick Claw
48 and King's Rock / Focus Band 64 to match; (c) with those prices a 21-round run (39 BP) buys about 39 vitamins or one held item,
which looks generous next to the original's 3 BP per 7-win streak: lowering the rates is the alternative to raising prices.
Pacing, first-clear items (Rare Candy / PP Up / Max Revive by set), the 10% repeat-money rule and exactly-once payment (tests) are
unchanged.

## Persistence checks relevant to rewards (no defect found)
BP, streaks and purchases are in the shared-world database (tables are additive; Update 23 compat tests), paid exactly once per
cleared round and per player across reconnects and host restarts (`tests/test_frontier.py`: incl. restart and
repeated-receipt tests); co-op Frontier uses one run per pair.

## Legendary catch ownership
Rule and reconciliation unchanged (`docs/legendary-catch-resolution.md`): first valid reported catch wins; the loser's copy is
removed only if it is still exactly that Pokémon (species + personality + trainer id), never the last party member; traded, evolved
or released copies are left alone; every verdict and report is logged durably (`event_resolutions`, `event_reports`,
`event_verdicts`). Compatibility with a database from before the verdicts: `tests/test_save_compat.py`.
