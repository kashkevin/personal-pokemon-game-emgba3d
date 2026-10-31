# Switch Moves: form moves, and the audit of every species (2026-10-31)

The owner's reports of 2026-10-31: "Fix Rotom Form-Specific Moves — Switch Moves Menu" (a Rotom-Wash had no Hydro Pump
to choose in its Switch Moves menu) and "Global Learnset & Switch Moves System Audit and Fix" (every species and form; a
high-level caught Pokemon's moves to its level; evolution and form moves; the Mewtwo case: Mist, Calm Mind, Barrier, Aura
Sphere, Recover), then "Fix these bug fixes then publish them". Engine `987c9268` (PC only: the GBA ROM's sha256 is
unchanged), app (this change).

**L** below means the Linux test builds (the 3D one with Mesa's software OpenGL, and the Classic 2D one); nothing here
was run on Windows or on a player's PC unless it says so.

## How the Switch Moves lists work (unchanged)

MOVES in the party menu and the summary's relearner (Legends Z-A's move switching, 2026-10-24) offer, for the Pokemon as
it is now:

* **Level up**: every move of its own level-up learnset up to its current level, and each earlier form's up to the level
  it evolved at (a move learned on evolving first). Nothing is stored: the list is worked out from the species, level and
  moves each time it opens, so a Pokemon caught or received at a high level has every move to its level at once
  (retroactive by construction), and a level gained adds that level's moves.
* **Egg moves**: only for a Pokemon that hatched from an Egg.
* **TMs and HMs**: the TM and HM moves it can learn, of the TMs and HMs in the Bag (TMs are never used up on PC).
* **Tutor moves**: the one-time tutors the player has used.

This game's level-up learnsets are Gen 6's (`include/config/pokemon.h` `P_LVL_UP_LEARNSETS` = `GEN_LATEST` = Gen 6).

## The bug: a form's own move was on no list

Rotom's five appliance forms share Normal Rotom's level-up learnset. The game teaches their moves - Overheat (Heat),
Hydro Pump (Wash), Blizzard (Frost), Air Slash (Fan), Leaf Storm (Mow) - only at the moment the Rotom Catalog changes the
form (`src/party_menu.c`). A Rotom that did not learn the move then (it knew four moves and the question to make room was
declined), or that switched it out later, had no list with the move on it, and switching it out warned "can't be
switched back in later".

The same pattern, found by the audit below: Necrozma's Dusk Mane and Dawn Wings forms share Necrozma's learnset, and
Sunsteel Strike and Moongeist Beam come only from the fusion. Kyurem's and Calyrex's fused forms have their fusion moves
in learnsets of their own (Kyurem-Black: Fusion Bolt Lv 43, Freeze Shock Lv 50, the levels at which Kyurem learns the
Scary Face and Glaciate they replace; Kyurem-White likewise; Calyrex Ice and Shadow: Glacial Lance and Astral Barrage at
Lv 1), so their lists had them already.

## The fix (engine `987c9268`, PC only)

* `src/move_relearner.c` `MoveRelearner_FormMove`: the form's own move is on that form's level-up list, first (as a move
  learned on evolving), tagged **FORM** ("The move of its form: Rotom." on the 3D screen; "Form" in Classic 2D), and can
  be switched back in, so switching it out gives no warning. No other form's list has it: a Normal Rotom's list has none
  of the five, a Rotom-Wash's has Hydro Pump and not Overheat. Once known it is not on the list again.
* `src/party_menu.c` (the Rotom Catalog, PC only): the game's own steps are kept - every other form's move goes and the
  new form's is taught with the party menu's lines ("Rotom learned Hydro Pump!"); knowing four moves, none of them a
  form's, the game's question to make room - and whatever the answer, the move is on the Switch Moves list from then
  on. Two details changed: the new move takes the slot of the form's move it replaces (the game put it last), and a
  form's move Rotom knows already (a TM's Blizzard) stays where it is (the game deleted it and taught it again). Back to
  Normal Rotom the form's move goes; Thunder Shock is taught only when Rotom would know no move (as before; the game's
  rule before Gen 9).
* Saves, the PC, trades and world play: nothing new is stored. A form is its species number, which saves, the PC's
  storage and trades already carry (`docs/rotom-catalog-20261030.md`), and the list follows it; an old save needs
  nothing and loses nothing. The player's moves are never changed by opening the lists.
* The moves' battle data is the game's own, as Gen 6 has it: Overheat Fire 130 / 90% / 5 PP, Hydro Pump Water 110 / 80% /
  5, Blizzard Ice 110 / 70% / 5, Air Slash Flying 75 / 95% / 15, Leaf Storm Grass 130 / 90% / 5, all special; Sunsteel
  Strike Steel 100 / 100% / 5 physical, Moongeist Beam Ghost 100 / 100% / 5 special.

## Mewtwo (the owner's case)

Mewtwo's Gen 6 learnset (this game's): Confusion, Disable, Safeguard (Lv 1), Swift 8, Future Sight 15, Psych Up 22,
Miracle Eye 29, Psycho Cut 36, Power Swap and Guard Swap 43, **Recover 50**, Psychic 57, **Barrier 64**, **Aura Sphere
70**, Amnesia 79, **Mist 86**, Me First 93, Psystrike 100. **Calm Mind** is not a level-up move of Mewtwo in Gen 6; it is
TM04's.

So a level-70 Mewtwo's level-up list offers Recover, Barrier and Aura Sphere, each one it does not know already. A
Mewtwo met at Lv 70 knows the last four moves of its learnset to that level - Recover, Psychic, Barrier and Aura Sphere -
so those are in its moveset rather than on the list; its list then has the earlier ones (Confusion to Guard Swap). Mist
comes at Lv 86 and is not offered before; Calm Mind is on its TM list when TM04 is in the Bag. This is the game's
intended data, so nothing was unlocked early. (In the original Emerald, Gen 3's learnset, Mewtwo learned Mist
at Lv 55 and Recover at Lv 88; the learnsets' generation is a game rule and was not changed.)

## The audit of every species and form

`--selftest-move-switch` (127 checks) checks, among the list rules it checked before:

| Check | Result |
| --- | --- |
| Every enabled species and form (1571) at Lv 1, 5, 50 and 100, knowing Splash alone: its learnset's moves real and in level order; the level-up list never full (no move cut off; the longest 36 moves, Mr. Rime, the limit 60); every move of its own learnset up to its level on the list; nothing on the list it or an earlier form learns only later (but its form's move); each move once | passed |
| Every evolved species at the levels it can be (693): each earlier form's moves only up to the level it evolved at | passed |
| Every move a form change teaches (13: Rotom's five, Necrozma's two, Calyrex's two, Kyurem's four) on that form's level-up list at Lv 100 and switchable back in | passed (Rotom's and Necrozma's after the fix) |
| Each Rotom form: its move first, tagged FORM, switchable back in; no other form's move; not on the list again once known; Normal Rotom: none of the five | passed |
| The catalog's changes: Heat to Wash with Overheat third (Hydro Pump in its slot, full PP, the other three kept); Normal to Frost with two moves (Blizzard into the free slot); Frost to Mow with four moves (the question; declined: no move goes, Leaf Storm on the list); a stray form's move dropped; Fan to Normal; Wash to Normal with Hydro Pump alone (Thunder Shock); Heat to Frost knowing Blizzard (kept once); every form in turn twice and back; the Pokemon's bytes copied as a save or a trade copies them (the list the same) | passed |
| The forms' moves' battle data as Gen 6's | passed |
| Mewtwo at Lv 70 and 86 (above) | passed |

Issues found: the two above (Rotom's five forms, Necrozma's two fused forms), both fixed. No other species or form had a
missing, early, duplicated or cut-off move.

## Tests

| Test | Where | Result |
| --- | --- | --- |
| `--selftest-move-switch` (127 checks) and `--selftest-rotom-catalog` (73) | L (the Linux build) | passed |
| `tools/battle_env/move_switch_check.py`, 14 steps (the 11 before, and: a Rotom-Wash knowing four moves - Hydro Pump first on its level-up list, no other form's move, taught over Thunder Shock at 5/5; a level-70 Mewtwo's list; the same with TM04 in the Bag - Calm Mind on the TM list) | L, 3D and Classic 2D test builds | passed in both, every step: the Rotom-Wash's list Hydro Pump first (FORM), no other form's move, Hydro Pump taught over Thunder Shock at 5/5 (Thunder Shock then on the list); the Mewtwo's list with Recover, Barrier and Aura Sphere, without Mist, Psystrike or Calm Mind; with TM04, Calm Mind on its TM list |
| `tools/battle_env/rotom_check.py` (bought, every form and back with the game's lines, saved and loaded, the second Rotom, the paths that change nothing, four moves - the question declined, the six forms' battles with their moves) | L, 3D and Classic 2D test builds | passed in both: every form and back (each form's move in the third slot in the last one's place, none back at Normal), saved and loaded; four moves: the question, declined, a Heat Rotom with its four; the six battles won with each form's move |
| `check_gba_lines.py`, the GBA ROM, the Windows builds | L; MinGW (built only) | passed: no moved lines; ROM sha256 `f214735b...3387` as pinned; the Windows 3D and Classic 2D games built |
| The same self-tests and in-game checks in Windows game processes | Windows CI runs 256 (engine `987c9268`) and 257 (engine `1abfe554`), GitHub-hosted runners | **passed in both** (`docs/package-20261031.md`) |

## Not verified

* On the owner's PC.
* A battle between two players with a Rotom form, and a world trade of a Rotom after this change between two PCs (the
  bytes test above, and the Rotom form trade of 2026-10-30 between two real games through the real host, stand for it).
* Necrozma, Kyurem and Calyrex are not obtainable in normal play here; their lists were checked in the self-test only.
