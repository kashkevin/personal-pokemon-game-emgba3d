# The TM catalogue (2026-10-31)

The owner's request of 2026-10-31 ("complete TM system" in the Game Corner) and answers (`docs/owner-decisions.md` 26-29:
the price tiers, "any pokemon that can actually learn the tm, from gen 1-6", a PC-only save record, all TMs from the
start). Engines `9e033b5d` and `19bb9c63` (PC only: the GBA ROM's sha256 is unchanged), app (this change).

**L** below means the Linux test builds (the 3D one with Mesa's software OpenGL, and the Classic 2D one); **Wine** means
the Windows build run under Wine on Linux, not Windows. Nothing here was run on Windows or on a player's PC unless it
says so.

## What a player gets

* The Mauville Game Corner's TM clerk (the third clerk from the left at the prize counter) now asks first: **TM PRIZES** (the
  five TMs as before, at 225-600 coins) or the **TM CATALOGUE**: every TM of the game.
* The catalogue is every move that was a TM in any Gen 1-6 game: 168 TMs. TM01-TM50 keep Emerald's numbers; TM51-TM168
  are the rest (TM51 Roost ... TM168 Nightmare; the list below). They come in four kinds, each its own list: **PHYSICAL
  ATTACKS** (65), **SPECIAL ATTACKS** (52), **STATUS & SETUP** (28) and **DEFENSE & UTILITY** (23).
* Each TM shows its number, move, type and price: in the 3D shop on its row (the type as a badge beside the price); in
  the Classic 2D shop the list shows the number and price and the box below names the move and its type, with the
  move's words. The buy question names the move: "You wanted TM165 Detect? That'll be 7500 COINS."
* Prices are the owner's tiers by usefulness: 1,000 / 2,500 / 5,000 / 7,500 / 10,000 coins (40, 47, 36, 27 and 13 TMs).
  The five TMs the prize counter already sold cost the same at both counters (TM32 225, TM29 525, TM35, TM24 and TM13
  600). No other price changed.
* Every TM is sold from the start. TMs are never used up on PC (as since 2026-10-24), so a TM the player has, in the Bag
  or the PC's item storage, shows **SOLD OUT** and can't be bought again; the TM PRIZES refuse one too ("You already have
  ... A TM is never used up, so you won't need another one.").
* A TM is used from the Bag as before (ABLE / NOT ABLE, "... learned ...!"), and its move is on the Switch Moves list of
  any Pokemon that can learn it while the TM is in the Bag or the PC.

## Which Pokemon a TM teaches

The owner's rule: "any pokemon that can actually learn the tm, from gen 1-6 ik they change in gens but if it was able to
learn some from gen 1-6 they can learn it". So TM *n* teaches its move to a species that learned that move by TM in any
Gen 1-6 game (Red/Blue/Yellow, Gold/Silver/Crystal, Ruby/Sapphire/Emerald, FireRed/LeafGreen, XD, Diamond/Pearl/Platinum,
HeartGold/SoulSilver, Black/White, Black 2/White 2, X/Y, Omega Ruby/Alpha Sapphire), whatever TM number the move had
there. Pikachu learns Thunderbolt; Gyarados learns Dragon Rage (Gen 1's TM23); Chansey learns Soft-Boiled (Gen 1's TM41)
and Blissey does not (it never had it by TM); Mew learns all 168; Magikarp and Smeargle learn none.

* **The owner's extension:** Ferroseed and Ferrothorn learn TM76 Stealth Rock ("a documented custom compatibility
  extension, not an original official TM learnset", the owner's request). No Gen 1-6 TM taught them it. It is the only
  extension.
* **Forms** take their Gen 1-6 form's list: Megas, Primal Kyogre and Groudon and the other battle-only forms the form they
  return to; Origin Dialga and Palkia (the Adamant Crystal and Lustrous Globe, sold at RARE GOODS) and Zygarde's forms
  (the Zygarde Cube) Dialga's, Palkia's and Zygarde's, so holding or using the item never switches TMs off; Rotom's,
  Deoxys's, Wormadam's and the other forms with a Gen 1-6 list of their own use it.
* **Pokemon first seen after Gen 6** (decided here, see below): no Gen 1-6 game had them, so the rule cannot speak for
  them; they keep the TM moves they have today, their own games' TM and tutor list. None can be caught here; Kleavor
  (Scyther with the Black Augurite, sold at RARE GOODS) and Kingambit (Bisharp, after the Leader's Crest battles) can come
  from evolving. Kleavor's TMs: Calm Mind, Sunny Day, Hyper Beam, Light Screen, Protect, Rain Dance, Brick Break, Double
  Team, Sandstorm, Rock Tomb, Aerial Ace, Facade, Rest, Thief, Endure, Swords Dance, Rock Slide, Sleep Talk, Substitute,
  Double-Edge, Swift.
* **HMs and tutors** keep their lists (the 2026-10-27 rule): a tutor still teaches what its games' tutors taught, so the
  same move may come from the tutor and not from the TM (Body Slam: Emerald's tutor teaches Treecko; no Gen 1-6 TM did).
* **Pokemon that already know a move keep it.** Nothing in a save changes.

In numbers: 1,536 species constants (forms counted) learn at least one TM, 52,684 species-TM pairs, 25,058 of them from
TM51-TM168. For TM01-TM50 the rule takes away 1,203 pairs from 572 species constants that existed in Gen 1-6 and adds
none: moves only later games taught them by TM (686, e.g. Pikachu Calm Mind, Gardevoir Ice Beam, Metagross Focus Punch,
Breloom Aerial Ace) or that a Gen 1-6 tutor taught (517). The moves most often taken away are Iron Tail (113), Giga
Drain (109), Shock Wave (90), Skill Swap (80), Thief and Snatch (73 each). A Pokemon that knows such a move keeps it; if
it switches the move out, it can't switch it back in from the TM (the Switch Moves warning says so first).

## The save

The save's TM pocket has 64 slots (SaveBlock1, pinned since the game's start), too few for 168 TMs and 8 HMs. So the Bag's
TM pocket is a 176-slot case in memory; TM01-TM50 and the HMs are kept in the save's 64 slots as before, and TM51 and up
are one bit each in a 36-byte **TM record** after the Battle Tower record (SaveBlock3 bytes 1076-1111: magic "PTM1",
version 1, the bits' count, 24 bytes of bits, CRC-32 of the rest; all zeros when there is none). It is written before
every save and read after a load.

* A save from before the catalogue loads as it was; saved again with no TM past TM50 it is byte for byte as before.
* The launcher's save checker (`flash.py` `parse_tm_record`) reads the record like the egg queue and the Tower record:
  all zeros is no TM past TM50; anything but a sealed record (magic, version, reserved bytes, count, a bit past TM168,
  CRC) is refused, never repaired. A character leaving its world keeps its TMs.

## Decisions made here (the owner may change them)

1. **Pokemon first seen after Gen 6 keep their own games' list** (above). The literal rule would give them no TM at all,
   so an evolved Kleavor would lose every TM it can learn today. To change it: `make_tm_learnsets_pc.py`'s "after Gen 6".
2. **How the shops show a TM** (the request asked for its number, move, type and price): the 3D shop's rows show all
   four; the Classic 2D shop's list has room for the number and price only, so its box names the move and type above
   the move's words (wrapped to the box; they were cut off at its edge before, the move's words being written for wider
   boxes). Both shops' buy question names the move.
3. **A damaged TM record** (the CRC does not match) is not read by the game: the TMs past TM50 are then missing, never
   invented. The launcher refuses such a save before the game sees it.

## Tests

| Test | Where | Result |
| --- | --- | --- |
| `--selftest-tm-catalogue` (57 checks): the items (168 TMs and 8 HMs, numbers, moves, the TM pocket, never used up, names, descriptions); the four lists (sizes, order, kinds, the shop's prices); the owner's tiers and the five prize prices; buying, SOLD OUT in the Bag and in the PC; the table (1,536 species, 52,684 pairs) and samples (Pikachu, Magikarp, Smeargle, Mew, Chansey and Blissey, Gyarados, Ferrothorn and Ferroseed, Treecko's tutor Body Slam, the forms, Kleavor); HMs unchanged for every species; the Switch Moves list with TMs past TM100 and with all 176 machines; the record (an older save loaded and saved byte for byte, four TMs past TM50 saved and loaded, a new encryption key, a damaged record not read, all 176 machines saved and loaded) | L (3D and Classic 2D test builds); Wine (the Windows Classic 2D test build) | **57 of 57** in each |
| `--selftest-bag-items` (updated for 176 machines: TM01-TM50 and the HMs keep Emerald's moves; TMs checked by the new rule) | L, both | 127 of 127 |
| Every self-test of the game the Windows job and the Makefile run (50, the new one among them) | L (the 3D test build, engine `9e033b5d` with the shop's type badges) | **all passed** |
| `tools/battle_env/tm_catalogue_check.py`, keys a player presses: at the TM counter with 20,000 coins, TM CATALOGUE, DEFENSE & UTILITY, TM165 Detect (7,500), YES, then SOLD OUT on it, out, saved; loaded: 12,500 coins and TM165; TM PRIZES: TM32 (225), YES, a second refused twice, 19,775 coins and one TM32; a Pikachu knowing Thunder Shock taught TM165 from the Bag ("Pikachu learned Detect!"), TM165 still there, saved; loaded: Thunder Shock and Detect, TM165 | L, 3D and Classic 2D test builds (engine `19bb9c63`) | **passed** in both, every step; the pictures show the 3D rows with each TM's type, the 2D box ("Detect  Fighting", the move's words in two lines) and "You wanted TM165 Detect?" |
| The game's own save after buying TM165, read by the launcher's checker | L (the 3D test build's save, `flash.py`) | accepted; the record holds TM165; an older save's record is empty |
| `tools/battle_env/move_switch_check.py` (14 steps, TMs in the Bag among them) | L, 3D and Classic 2D | passed in both, every step |
| App tests: `tests/test_tm_record.py` (the record's place, older saves, sealed records in both profiles, everything else refused, padding after it, a character leaving its world keeps its TMs) and the save tests that pin the end of SaveBlock3 | L | passed |
| The GBA ROM; `check_gba_lines.py` | L | the ROM's sha256 `f214735b...3387` as pinned; no GBA line moved |
| The Windows builds (the 3D game, the Classic 2D game and its test build) | MinGW (built; the test build's TM self-test under Wine, above) | built |

## Not verified

* On Windows (the next Windows CI run has the self-test and the in-game check) or on the owner's PC.
* Every one of the 168 TMs bought and taught in a real game: one TM of each counter was, and the self-test checks all of
  them through the game's own tables.
* A world trade of a Pokemon after this change: a Pokemon's bytes do not change (the TM rule is read only to teach).
* Mixed versions: a launcher from before this change refuses a save that holds a TM past TM50 (its save checker
  does not know the record), so everyone in a world updates together, as with the Tower record before.

## The TMs

*Learners* counts species constants (forms counted) that can learn the TM.

| TM | Move | Type | Kind | Coins | Learners |
| ---: | --- | --- | --- | ---: | ---: |
| TM01 | Focus Punch | Fighting | Physical | 5,000 | 256 |
| TM02 | Dragon Claw | Dragon | Physical | 7,500 | 142 |
| TM03 | Water Pulse | Water | Special | 2,500 | 325 |
| TM04 | Calm Mind | Psychic | Status & setup | 10,000 | 426 |
| TM05 | Roar | Normal | Defense & utility | 2,500 | 326 |
| TM06 | Toxic | Poison | Status & setup | 10,000 | 1128 |
| TM07 | Hail | Ice | Status & setup | 2,500 | 249 |
| TM08 | Bulk Up | Fighting | Status & setup | 7,500 | 172 |
| TM09 | Bullet Seed | Grass | Physical | 5,000 | 157 |
| TM10 | Hidden Power | Normal | Special | 5,000 | 1124 |
| TM11 | Sunny Day | Fire | Status & setup | 5,000 | 944 |
| TM12 | Taunt | Dark | Status & setup | 7,500 | 448 |
| TM13 | Ice Beam | Ice | Special | 600 (prize price) | 409 |
| TM14 | Blizzard | Ice | Special | 7,500 | 351 |
| TM15 | Hyper Beam | Normal | Special | 5,000 | 920 |
| TM16 | Light Screen | Psychic | Defense & utility | 5,000 | 535 |
| TM17 | Protect | Normal | Defense & utility | 7,500 | 1502 |
| TM18 | Rain Dance | Water | Status & setup | 5,000 | 952 |
| TM19 | Giga Drain | Grass | Special | 5,000 | 293 |
| TM20 | Safeguard | Normal | Defense & utility | 2,500 | 484 |
| TM21 | Frustration | Normal | Physical | 2,500 | 1093 |
| TM22 | Solar Beam | Grass | Special | 5,000 | 552 |
| TM23 | Iron Tail | Steel | Physical | 5,000 | 348 |
| TM24 | Thunderbolt | Electric | Special | 600 (prize price) | 406 |
| TM25 | Thunder | Electric | Special | 7,500 | 340 |
| TM26 | Earthquake | Ground | Physical | 10,000 | 424 |
| TM27 | Return | Normal | Physical | 5,000 | 1093 |
| TM28 | Dig | Ground | Physical | 2,500 | 508 |
| TM29 | Psychic | Psychic | Special | 525 (prize price) | 460 |
| TM30 | Shadow Ball | Ghost | Special | 10,000 | 461 |
| TM31 | Brick Break | Fighting | Physical | 7,500 | 484 |
| TM32 | Double Team | Normal | Status & setup | 225 (prize price) | 1093 |
| TM33 | Reflect | Psychic | Defense & utility | 5,000 | 440 |
| TM34 | Shock Wave | Electric | Special | 2,500 | 287 |
| TM35 | Flamethrower | Fire | Special | 600 (prize price) | 323 |
| TM36 | Sludge Bomb | Poison | Special | 7,500 | 234 |
| TM37 | Sandstorm | Rock | Status & setup | 5,000 | 365 |
| TM38 | Fire Blast | Fire | Special | 7,500 | 272 |
| TM39 | Rock Tomb | Rock | Physical | 2,500 | 526 |
| TM40 | Aerial Ace | Flying | Physical | 2,500 | 480 |
| TM41 | Torment | Dark | Status & setup | 1,000 | 230 |
| TM42 | Facade | Normal | Physical | 5,000 | 1463 |
| TM43 | Secret Power | Normal | Physical | 2,500 | 932 |
| TM44 | Rest | Psychic | Defense & utility | 5,000 | 1478 |
| TM45 | Attract | Normal | Status & setup | 2,500 | 1097 |
| TM46 | Thief | Dark | Physical | 2,500 | 552 |
| TM47 | Steel Wing | Steel | Physical | 2,500 | 141 |
| TM48 | Skill Swap | Psychic | Defense & utility | 2,500 | 133 |
| TM49 | Snatch | Dark | Defense & utility | 1,000 | 123 |
| TM50 | Overheat | Fire | Special | 7,500 | 145 |
| TM51 | Roost | Flying | Defense & utility | 10,000 | 132 |
| TM52 | Focus Blast | Fighting | Special | 7,500 | 247 |
| TM53 | Energy Ball | Grass | Special | 7,500 | 266 |
| TM54 | False Swipe | Normal | Physical | 5,000 | 80 |
| TM55 | Brine | Water | Special | 2,500 | 96 |
| TM56 | Fling | Dark | Physical | 2,500 | 352 |
| TM57 | Charge Beam | Electric | Special | 2,500 | 230 |
| TM58 | Endure | Normal | Defense & utility | 2,500 | 1155 |
| TM59 | Dragon Pulse | Dragon | Special | 7,500 | 90 |
| TM60 | Drain Punch | Fighting | Physical | 7,500 | 70 |
| TM61 | Will-O-Wisp | Fire | Status & setup | 10,000 | 145 |
| TM62 | Silver Wind | Bug | Special | 2,500 | 63 |
| TM63 | Embargo | Dark | Status & setup | 1,000 | 99 |
| TM64 | Explosion | Normal | Physical | 5,000 | 146 |
| TM65 | Shadow Claw | Ghost | Physical | 5,000 | 187 |
| TM66 | Payback | Dark | Physical | 2,500 | 265 |
| TM67 | Recycle | Normal | Defense & utility | 1,000 | 95 |
| TM68 | Giga Impact | Normal | Physical | 5,000 | 541 |
| TM69 | Rock Polish | Rock | Status & setup | 7,500 | 105 |
| TM70 | Hone Claws | Dark | Status & setup | 5,000 | 213 |
| TM71 | Stone Edge | Rock | Physical | 10,000 | 213 |
| TM72 | Avalanche | Ice | Physical | 2,500 | 98 |
| TM73 | Thunder Wave | Electric | Status & setup | 7,500 | 421 |
| TM74 | Gyro Ball | Steel | Physical | 5,000 | 103 |
| TM75 | Swords Dance | Normal | Status & setup | 10,000 | 382 |
| TM76 | Stealth Rock | Rock | Defense & utility | 10,000 | 143 |
| TM77 | Psych Up | Normal | Status & setup | 2,500 | 488 |
| TM78 | Captivate | Normal | Status & setup | 1,000 | 511 |
| TM79 | Dark Pulse | Dark | Special | 7,500 | 207 |
| TM80 | Rock Slide | Rock | Physical | 5,000 | 541 |
| TM81 | X-Scissor | Bug | Physical | 7,500 | 110 |
| TM82 | Sleep Talk | Normal | Defense & utility | 5,000 | 1480 |
| TM83 | Natural Gift | Normal | Physical | 1,000 | 599 |
| TM84 | Poison Jab | Poison | Physical | 7,500 | 163 |
| TM85 | Dream Eater | Psychic | Special | 2,500 | 275 |
| TM86 | Grass Knot | Grass | Special | 5,000 | 357 |
| TM87 | Swagger | Normal | Status & setup | 2,500 | 1102 |
| TM88 | Pluck | Flying | Physical | 1,000 | 60 |
| TM89 | U-turn | Bug | Physical | 10,000 | 174 |
| TM90 | Substitute | Normal | Defense & utility | 10,000 | 1480 |
| TM91 | Flash Cannon | Steel | Special | 7,500 | 124 |
| TM92 | Trick Room | Psychic | Status & setup | 7,500 | 149 |
| TM93 | Psyshock | Psychic | Special | 7,500 | 132 |
| TM94 | Venoshock | Poison | Special | 2,500 | 98 |
| TM95 | Telekinesis | Psychic | Status & setup | 1,000 | 145 |
| TM96 | Smack Down | Rock | Physical | 2,500 | 122 |
| TM97 | Sludge Wave | Poison | Special | 7,500 | 61 |
| TM98 | Flame Charge | Fire | Physical | 2,500 | 84 |
| TM99 | Low Sweep | Fighting | Physical | 2,500 | 101 |
| TM100 | Round | Normal | Special | 1,000 | 918 |
| TM101 | Echoed Voice | Normal | Special | 1,000 | 277 |
| TM102 | Ally Switch | Psychic | Defense & utility | 1,000 | 21 |
| TM103 | Scald | Water | Special | 10,000 | 136 |
| TM104 | Sky Drop | Flying | Physical | 1,000 | 28 |
| TM105 | Incinerate | Fire | Special | 2,500 | 234 |
| TM106 | Quash | Dark | Status & setup | 1,000 | 41 |
| TM107 | Acrobatics | Flying | Physical | 5,000 | 105 |
| TM108 | Retaliate | Normal | Physical | 2,500 | 242 |
| TM109 | Volt Switch | Electric | Special | 10,000 | 66 |
| TM110 | Struggle Bug | Bug | Special | 1,000 | 94 |
| TM111 | Bulldoze | Ground | Physical | 2,500 | 321 |
| TM112 | Frost Breath | Ice | Special | 2,500 | 32 |
| TM113 | Dragon Tail | Dragon | Physical | 5,000 | 88 |
| TM114 | Work Up | Normal | Status & setup | 2,500 | 198 |
| TM115 | Wild Charge | Electric | Physical | 7,500 | 120 |
| TM116 | Snarl | Dark | Special | 2,500 | 96 |
| TM117 | Infestation | Bug | Special | 1,000 | 132 |
| TM118 | Nature Power | Normal | Defense & utility | 2,500 | 153 |
| TM119 | Power-Up Punch | Fighting | Physical | 5,000 | 250 |
| TM120 | Dazzling Gleam | Fairy | Special | 7,500 | 127 |
| TM121 | Confide | Normal | Status & setup | 1,000 | 920 |
| TM122 | Mega Punch | Normal | Physical | 2,500 | 135 |
| TM123 | Razor Wind | Normal | Special | 1,000 | 21 |
| TM124 | Whirlwind | Normal | Defense & utility | 2,500 | 20 |
| TM125 | Mega Kick | Normal | Physical | 2,500 | 145 |
| TM126 | Horn Drill | Normal | Physical | 2,500 | 21 |
| TM127 | Body Slam | Normal | Physical | 5,000 | 378 |
| TM128 | Take Down | Normal | Physical | 1,000 | 178 |
| TM129 | Double-Edge | Normal | Physical | 5,000 | 354 |
| TM130 | Bubble Beam | Water | Special | 1,000 | 71 |
| TM131 | Water Gun | Water | Special | 1,000 | 71 |
| TM132 | Pay Day | Normal | Physical | 1,000 | 32 |
| TM133 | Submission | Fighting | Physical | 1,000 | 78 |
| TM134 | Counter | Fighting | Physical | 2,500 | 70 |
| TM135 | Seismic Toss | Fighting | Physical | 5,000 | 95 |
| TM136 | Rage | Normal | Physical | 1,000 | 184 |
| TM137 | Mega Drain | Grass | Special | 1,000 | 36 |
| TM138 | Dragon Rage | Dragon | Special | 1,000 | 19 |
| TM139 | Fissure | Ground | Physical | 2,500 | 39 |
| TM140 | Teleport | Psychic | Defense & utility | 1,000 | 39 |
| TM141 | Mimic | Normal | Defense & utility | 1,000 | 214 |
| TM142 | Bide | Normal | Physical | 1,000 | 184 |
| TM143 | Metronome | Normal | Defense & utility | 1,000 | 147 |
| TM144 | Self-Destruct | Normal | Physical | 2,500 | 25 |
| TM145 | Egg Bomb | Normal | Physical | 1,000 | 4 |
| TM146 | Swift | Normal | Special | 1,000 | 382 |
| TM147 | Skull Bash | Normal | Physical | 1,000 | 130 |
| TM148 | Soft-Boiled | Normal | Defense & utility | 7,500 | 2 |
| TM149 | Sky Attack | Flying | Physical | 2,500 | 14 |
| TM150 | Psywave | Psychic | Special | 1,000 | 45 |
| TM151 | Tri Attack | Normal | Special | 5,000 | 27 |
| TM152 | Dynamic Punch | Fighting | Physical | 2,500 | 123 |
| TM153 | Headbutt | Normal | Physical | 2,500 | 215 |
| TM154 | Curse | Ghost | Status & setup | 5,000 | 291 |
| TM155 | Rollout | Rock | Physical | 1,000 | 98 |
| TM156 | Zap Cannon | Electric | Special | 2,500 | 100 |
| TM157 | Sweet Scent | Normal | Defense & utility | 1,000 | 40 |
| TM158 | Snore | Normal | Special | 1,000 | 672 |
| TM159 | Icy Wind | Ice | Special | 5,000 | 201 |
| TM160 | Dragon Breath | Dragon | Special | 2,500 | 28 |
| TM161 | Mud-Slap | Ground | Special | 1,000 | 277 |
| TM162 | Ice Punch | Ice | Physical | 5,000 | 127 |
| TM163 | Defense Curl | Normal | Status & setup | 1,000 | 118 |
| TM164 | Thunder Punch | Electric | Physical | 5,000 | 139 |
| TM165 | Detect | Fighting | Defense & utility | 7,500 | 130 |
| TM166 | Fire Punch | Fire | Physical | 5,000 | 118 |
| TM167 | Fury Cutter | Bug | Physical | 1,000 | 58 |
| TM168 | Nightmare | Ghost | Status & setup | 1,000 | 64 |
