# Gameplay updates and visual fixes (2026-10-27)

The owner's request "Additional Gameplay Updates & Visual Fixes" (eggs hatching in the PC, riding, building
minigames, the real Pokemon for Surf, Fly and Dive, testing) and "Full Wild Pokemon Item Functionality Audit", done
as smaller updates before larger development; nothing here is packaged.

Where a result comes from, always: **L** this Linux machine (real game processes; the 3D view through Mesa's software
OpenGL); **simulated** the multiplayer proofs' internet; **W** a GitHub-hosted Windows runner. Nothing here was tried
on the owner's PCs or between two real PCs unless a line says so.

## 1. Eggs hatch while stored in the PC

**Done** (engine `c3506ff8`; the rule is written in `docs/update30-gameplay.md` and as decision 12 in `PROJECT_SPEC.md`).
Until now an Egg in the PC spent no cycles and never hatched.

How it works:

* The hook is the party's own egg cycle (`src/daycare.c` `TryToHatchEgg`, every 32 of the player's steps). At that moment every
  Egg in all 14 boxes (420 slots) spends the same cycles a party Egg spends: 1 normally, 2 with Flame Body or Magma Armor in
  the party (the same `GetEggCyclesToSubtract`). An Egg with no cycles left hatches at the next cycle, as in the party. So an
  Egg hatches after exactly the steps it would take in the party, never sooner, and all box Eggs progress together.
* It hatches **in its own slot** (`src/platform/mp_breeding.c` `HatchBoxEgg`): species, form, personality (nature, gender,
  ability, shininess), IVs, moves, Poke Ball and the ownership serial are untouched. It gets what the party's hatch gives
  (`egg_hatch.c` `AddHatchedMonToParty`): the species name, the game's language, friendship 120, "hatched at" the player's
  map, full PP, the Pokedex entry, the hatched-eggs count. One difference: the party's hatch writes the player's OT ID; the
  box hatch never changes the OT ID (the world's host refuses a save whose Pokemon changed personality or OT ID,
  `ownership_storage.py`), and every Egg a player can have was made with their own OT ID already, so the result is the same.
* A banner says it once the field is calm: "PC EGG HATCHED! / Pichu hatched in your PC."; several on one step: "3 PC EGGS
  HATCHED! / Pichu, Pikachu +1".
* Only the player's own steps count: the hook runs in the player's own game when that player steps; another player's
  movement is drawn from the network and never runs it, and the host runs no game. Nothing accumulates while the game is
  closed (the game has no offline progress; none was added).
* The progress is the Egg's own cycle counter (its friendship byte, as in the original), so it is saved with the box: quit,
  reload and the world's checkpoints keep it. Bad Eggs and non-Eggs are never touched.

Tests (**L**):

| Test | Result |
|---|---|
| `--selftest-breeding` section 5 (rewritten): steps to hatch in a box vs. in the party, for 0, 1, 7 and 20 cycles, with and without Flame Body | **Equal in all 8 cases** (32, 64, 256, 672 steps without; 32, 64, 160, 352 with) |
| the same: a shiny Togepi Egg with an Egg move in the last slot of the last box hatches | species, personality, IVs, moves, ball, shininess kept; nickname = species name; not an Egg |
| the same: Eggs in boxes 1, 6 and 14 hatch on one step; a non-Egg Zigzagoon and a Bad Egg in the boxes | three hatched; the other two unchanged |
| full `--selftest-breeding` | **77 checks, 0 failed** (2D game, engine `c3506ff8`) |
| `breed_check.py` steps 6-10, real game processes of the Classic 2D test build: a Day Care Egg moved to box 1 slot 1, walked | cycles 3 → 0 by walking; **saved and loaded with the same cycles**; walked again: **hatched in box 1 slot 1** (Pichu, same IVs, nature, ball, moves), banner "PC EGG HATCHED!\|Pichu hatched in your PC."; saved and loaded: box and Pokedex counts each +1; three Eggs in boxes 1, 8 and 14: all hatched in place, banner "3 PC EGGS HATCHED!\|Pichu, Pikachu +1". **All 10 steps passed** (steps 1-5, the older Day Care checks, also passed) |
| GBA ROM, `check_gba_lines.py`, 2D and 3D builds | ROM unchanged (`f214735b...`); 0 moved lines; both build |

Not tested: a PC hatch inside a connected world (the hook and the save path are the same as offline, and the host's rule it
must respect, unchanged personality and OT ID, is kept by construction); Windows; a player's PC.

## 2. Pokemon riding: animations and positioning

(in progress)

## 3. Building minigames: every one playable

(in progress)

## 4. The real Pokemon for Surf, Fly and Dive

(in progress)

## 5. Wild Pokemon item audit

(in progress)

## 6. Testing and what remains unverified

(in progress)
