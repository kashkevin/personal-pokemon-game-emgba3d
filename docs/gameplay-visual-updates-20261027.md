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

**Done** (engine `65940085`, PC only; the host's part in this app commit). Every item and ability that touches wild
Pokemon was traced through the code that actually makes the encounter (not the bag text), and each effect was measured
through the game's own functions (`--selftest-wild-items`, **76 checks, 0 failed**,
20 million rolls per shiny case, 1 million per ability case; `make -f Makefile_pc check-wild-items`). The game's wild
Pokemon come from four places, which matters for what an item can do:

* **Visible Pokemon of the player's own spawner** (`src/wild_encounter_ow.c`): all land and water Pokemon offline; in a
  connected world only on the water. Species from the randomized Gen 1-6 pool (`src/mp_wild_random.c`), level from the
  map's table; walking into one starts the battle, which makes its Pokemon again (`StartWildBattleWithOWE`).
* **A world's shared Pokemon** (host `shared_spawns.py`, engine `src/multiplayer_spawns.c`): land in a connected world.
  The host rolls species, level, personality (nature, gender, ability) and shininess once, the same for every player;
  a battle starts only when the player talks to one (it never starts by walking into it).
* **Random encounters** still happen only for Rock Smash, fishing, Sweet Scent and Honey (`WE_VANILLA_RANDOM` is off).
* **Static, gift and Egg Pokemon** have their own rules (Local Soft Reset hunts for the authored statics).

### What was wrong, and what changed

| # | Problem found | Cause | Fix |
|---|---|---|---|
| 1 | **Synchronize never worked on visible wild Pokemon** (offline, and on the water in a world); the Safari Zone's Pokeblock natures neither | the spawn was made with the right nature, then the battle made its Pokemon again with `NATURE_RANDOM` | the battle's Pokemon gets its nature as every wild encounter does (`PickWildMonNature`: Pokeblock, then Synchronize); engine, PC only |
| 2 | **The Shiny Charm gave Local Soft Reset hunts 1 in 1365.7**, not the approved 1 in 2500 | Update 30 retuned only the wild Charm (an extra roll made 41848/65536 of the time) and left these hunts at Update 29's two extra rolls; no rule allowed it (`PROJECT_SPEC.md`: one Charm value, 1/2500) | the same partial roll; `PROJECT_SPEC.md` updated; engine, PC only |
| 3 | **Magnet Pull and Static did nothing** (Steel 3.1 %, Electric 5.2 % of Route 101's spawns with or without them) | the map's table chose a Steel or Electric slot, but the randomizer then replaced its species | half the rolls are made among the families of that type that can appear there (Gen 6: half the encounters of that type when the area has any); land and water, not fishing or Rock Smash, as in the original; engine, PC only |
| 4 | **The encounter-rate items and abilities did nothing to visible Pokemon**: White and Black Flute, Cleanse Tag, Pure Incense, Stench, White Smoke, Quick Feet, Sand Veil, Snow Cloak, Illuminate, Arena Trap, No Guard (only Rock Smash used them) | visible Pokemon replace random encounters; only the lure had been adapted (by pokeemerald-expansion) | the player's own spawner waits at the same rate the original applies to random encounters (x2 halves every wait, x0.5 doubles it; the original multipliers, `MPWild_EncounterRateFactor`); the bike's x0.8 and the lure are not part of it; engine, PC only |
| 5 | **A Pokemon the Shiny Charm makes shiny on a world's shared spawns could despawn** (expire, wander off, be trimmed after an outbreak), against the owner's rule of 2026-10-24 that a shiny leaves only when caught or knocked out | the host keeps the shinies it rolled, but it cannot see bags, so it did not know | the host computes the Charm's hash too (the engine's, bit for bit: 48 vectors compared) and keeps every Pokemon that is shiny for a Charm owner like a shiny one (`Slot.kept`); app |
| 6 | Docs gave the old Charm price (100,000 coins; 15,000 since 2026-10-25) and said the Oval Charm and Pure Incense could not be had (the Game Corner's RARE GOODS sell them since 2026-10-24) | written before those changes | `PROJECT_SPEC.md`, `FEATURE_STATUS.md`, `update29/30` docs, `update-32` doc, the clerk script's comment corrected |

No balance value was changed: every multiplier above is the original's, and the Charm's 1/2500 is the approved value.

### Seen in the real game

`wild_items_check.py` (engine `tools/battle_env/`), real game processes of the Classic 2D test build on Route 101's grass,
offline (so every Pokemon there is the player's own spawner's), each run its own random seed (started a second apart):

| Case | Result |
|---|---|
| a Synchronize lead (Ralts, Timid) walks into the first visible Pokemon, 30 battles | **20 of 30** had the lead's nature (52 % expected; before the fix the battle's nature was random: 1 in 25) |
| the same lead with Trace, 30 battles | **0 of 30** (4 % expected) |
| the spawner over 74 s of standing still (a Pokemon that walks into the player starts no battle, a test switch), Pokemon made per run, 3 runs each | Black Flute (x0.5) 7, 8, 7; Cleanse Tag (x2/3) 10, 11, 9; nothing 16, 12, 12; White Flute (x1.5) 21, 18, 19; Illuminate (x2) 27, 26, 28: **the counts rise with the rate** |

### Item by item

Measured = `--selftest-wild-items` on this Linux machine through the game's own functions (expected value in brackets;
every check within 4.5 sigma). Where a source is "Rare Goods" it is the Game Corner prize clerk's coin shop (PC game).

| Item / ability | Intended effect (as implemented) | Worked before? | Found | Values and measured | Status |
|---|---|---|---|---|---|
| **Shiny Charm** (Game Corner, 15,000 coins; one per player) | the holder's own shiny odds: wild 1/2500, Safari 1/1024.4, Local Soft Reset hunts 1/2500, Eggs the player's Day Care makes 1/1365.7; never World Events | wild, Safari, Eggs, shared spawns: yes (`--selftest-shiny` 12/12, `--selftest-breeding`); LSR hunts: no | problems 2 and 5 | LSR + Charm: 8,186 shiny in 20M = 1 in 2443 (1 in 2500); LSR alone 1 in 4159 (4096); shared + Charm 1 in 2500.0 (`--selftest-shiny`) | **Fixed** |
| Shiny status kept | a shiny is stored in the Pokemon (never rolled again): capture, PC, trade, save | yes | - | a shiny put in the PC and read back is shiny, same personality; trades carry the Pokemon's data unchanged (trade proofs compare the boxes) | Works |
| **Lure / Super Lure / Max Lure** (Rare Goods, 75 / 150 / 225 coins) | 100 / 200 / 250 of the player's steps: the player's own visible Pokemon appear without the usual wait (until four are out); their level is the species' highest in that area plus one; one extra shiny roll for Pokemon made for the player; Rock Smash encounters twice as often | yes | the extra shiny roll also reaches gift and static Pokemon made while a lure lasts (inherited from pokeemerald-expansion; never documented); the original's 20 % common/rare slot swap only changes the level here (species are randomized); in a world, on land the Pokemon are the host's, so a lure's spawn effect does not apply there though its steps count | wild + lure 1 in 2026 (2048.3); lure + Charm 1 in 1542 (1552.7); LSR + lure 1 in 4024 (4096: no lure roll); levels max + 1 in 200,000 of 200,000 rolls; ends on its 100th step, once | Works as designed; the three notes are **owner decisions** (below) |
| Lure use | one item used per activation; a second Lure while one lasts is refused ("effects lingered"), not used up; wears off with a message and the offer to use another; counts only the player's own steps, not in the Battle Pike/Pyramid or Union Room; kept in the save | yes | a Repel used during a Lure ends the Lure at once (and the reverse), without a warning: they share one counter, so they never stack | one counter: with a Lure active no Repel, and the reverse (checked) | Works; the silent replacement is noted below |
| **Repel / Super Repel / Max Repel** (marts, item balls, Pickup) | 100 / 200 / 250 steps: wild Pokemon below the level of the first party member that is not an Egg (fainted or not, Gen 6) are kept away: the player's own visible ones are not made and those out go when it is used; Rock Smash and Sweet Scent likewise | yes | a world's shared Pokemon are not hidden (they never start a battle unless talked to) | level 19 kept away and 20, 21 met with a level-20 lead; a fainted lead counts; an Egg at the head is passed over; no shiny roll | Works |
| **Oval Charm** (Rare Goods, 15,000 coins) | Day Care Egg chance per 64-step check 20 / 50 / 70 % → 40 / 80 / 88 % | yes | - | 39.86 / 79.97 / 87.95 % (40 / 80 / 88) in 100,000 checks each; without it 19.79 / 50.08 / 70.08 % | Works |
| **Catching Charm** (Rare Goods, 15,000 coins) | doubles the chance of a critical capture | yes | - | ball odds 120, 40 Pokemon caught: 3.90 % → 7.79 % (3.91 → 7.81) | Works |
| **White Flute / Black Flute** (Route 113 Glass Workshop, 1,000 ash each) | encounter rate x1.5 / x0.5 until the map changes; not used up | Rock Smash only | problem 4 | the player's spawner's waits: 120 frames → 80 / 240 | **Fixed** |
| **Cleanse Tag** (Mt. Pyre 1F gift) / **Pure Incense** (Rare Goods, 750 coins) | held by the lead: encounter rate x2/3 | Rock Smash only | problem 4 | 120 → 180 frames | **Fixed** |
| Stench, White Smoke, Quick Feet; Sand Veil (sandstorm), Snow Cloak (snow) | lead: encounter rate x0.5 (Stench x0.75 in the Battle Pyramid) | Rock Smash only | problem 4 | 120 → 240 frames; Sand Veil in clear weather unchanged; an Egg at the head changes nothing | **Fixed** |
| Illuminate, Arena Trap, No Guard | lead: encounter rate x2 | Rock Smash only | problem 4 | 120 → 60 frames; combinations multiply (Black Flute + Cleanse Tag + Stench: x1/6, 720 frames) | **Fixed** |
| **Synchronize** | lead: the wild Pokemon has its nature half the time (Gen 6) | Rock Smash, fishing, Sweet Scent: yes; visible Pokemon: no | problem 1 | 51.92 % of natures are the lead's (52 %); Trace instead: 3.97 % (4 %); an Egg at the head: 4.04 % | **Fixed** (visible Pokemon); a world's shared Pokemon keep the host's nature (the same Pokemon for every player, by design) |
| Safari Zone Pokeblock | a nearby feeder's Pokeblock picks the nature 80 % of the time | not for visible Pokemon | problem 1 (same code) | not measured separately (the same function as Synchronize) | **Fixed** |
| **Cute Charm** | lead: the opposite gender two times in three | yes (the spawn keeps the gender it was made with) | - | a female lead: 83.35 % male (83.33 %); without: 50.45 % | Works |
| **Magnet Pull / Static** | lead: half the encounters on land and water are Steel / Electric when the area has any | no | problem 3 | Route 101: Steel 3.07 % → 51.61 % (51.54 %), Electric 5.17 % → 52.63 % (52.58 %) | **Fixed** |
| **Keen Eye / Intimidate** | lead: Pokemon 5 or more levels lower are kept away half the time | yes (the spawner asks) | - | level 25 against a level-30 lead: 50.04 % / 49.98 % kept away (50 %); level 26 never | Works |
| **Hustle / Pressure / Vital Spirit** | lead: the slot's highest level half the time | yes | - | 50.02 % (50 %); without 20.02 % (20 %, a 10-14 slot) | Works |
| **Compound Eyes / Super Luck** | lead: wild held items 50 / 5 % → 60 / 20 % | yes (every wild battle, visible and shared too) | - | 49.97 / 5.02 % → 59.96 / 20.01 % | Works |
| Sticky Hold / Suction Cups | lead: fishing bites twice as often (Gen 4+) | yes | - | code read (`fishing.c`), not measured | Works (unmeasured) |
| Flame Body / Magma Armor / Steam Engine | Egg cycles halved, once | yes | - | `--selftest-breeding` (party and, since today, PC Eggs) | Works |
| Honey / Sweet Scent | a wild encounter at once | yes | in a world, on land, it makes a personal encounter (not one of the host's Pokemon); the player's own items apply to it | not changed | Works as the original |
| Poke Doll / Fluffy Tail / Smoke Ball | a sure escape from a wild battle | yes (battle code unchanged) | - | not measured | Works (unmeasured) |
| Old / Good / Super Rod | fishing (species randomized) | yes | - | - | Works |
| Poke Radar | - | **not in the game**: no source, and its use is pokeemerald-expansion's "Todo" | - | - | Not available |

### Each player's items are that player's own

The bag, the Repel/Lure counter and the flutes' flags are in each player's own save and act only in that player's own game;
nothing about them is sent to the host or applied by it. A world's shared Pokemon are rolled once by the host (one roll for
everybody, never repeated on a reconnect); the Shiny Charm's bonus on one is computed only in the Charm owner's game, from
the Pokemon's own numbers, so claiming, releasing and claiming it again or reconnecting gives the same answer (no reroll),
and a player without the Charm sees the host's roll. An item is used up in the player's bag once, by the game's own item
code; a lost connection does not replay it.

### Owner decisions (reported, not changed)

1. **The lure's extra shiny roll** reaches every Pokemon made for the player while a lure lasts, gifts and static
   encounters included (not Eggs, not Local Soft Reset hunts, not a world's shared Pokemon). It comes from
   pokeemerald-expansion and was never written down. Keep it, or limit it to wild Pokemon?
2. **The lure's "rarer Pokemon" effect** (the original swaps common and rare table slots 20 % of the time) only changes
   the level here, because species are randomized. Restoring a rarity effect in the randomized pool would be a new lure
   effect, which the request says not to invent.
3. **Lures and Repels replace each other without a warning** (one counter): using a Repel during a Lure ends the Lure and
   its remaining steps are lost (and the reverse). A confirmation, or refusing it like a second Lure, are both possible.
4. **A lure used on land in a connected world** counts its steps although that land's Pokemon are the host's shared ones
   (only the water's are the player's own); a personal item cannot change Pokemon every player shares.

## 6. Testing and what remains unverified

(in progress)
