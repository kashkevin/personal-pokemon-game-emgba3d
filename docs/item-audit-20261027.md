# Item audit (2026-10-27): Poke Balls, healing, bag items, TMs and HMs, mints, held items

The owner's request "Full item audit" (every item of Gen 1-6: Poke Balls and their capture math, healing, held items,
berries, TMs and HMs, evolution items, charms, mints, Mega Stones, key items and so on). It asks for an item-by-item
report, with each item's effect, usage conditions, consumption, interactions, multiplayer sync and saving checked
against real behaviour. Existing balance must not change silently. The 2026-10-27 package was first to be built from
engine `6320c77d` (the first candidate); the owner then made this audit the package's gate (19:28 UTC, "step 14"), so
the package is built from engine `a5013203`: that candidate with every later commit of this audit (tests, and the
fixes of MS-156, MS-157 and MS-158, PC only) and without the unfinished 3D ledge work. The sections marked "after the
first candidate" came after `6320c77d`; all of them are in the package.

Where a result comes from: **L** this Linux machine (the game's own functions in self-tests); **T** the engine's GBA
test ROM (`make check`, the expansion's own battle tests, run on this Linux machine). Nothing here was tried on
Windows or on a player's PC.

**Every item, one by one:** `docs/item-audit-20261027-items.md` lists all 873 items of the game's list, read out of
the built game, with what checked each one today (and which are not audited yet).

## What this round covers

* **Poke Balls: done** (below), every ball of the game's list through the game's own capture code.
* **Healing items: done** (below), every healing item through the game's own item code.
* **Items that touch wild Pokemon: done earlier today**: the Shiny Charm, lures and Repels, the flutes, Cleanse Tag,
  Pure Incense, the encounter-rate abilities, Synchronize, Cute Charm, Magnet Pull and Static, Keen Eye, Hustle, Compound
  Eyes, the Catching and Oval Charms (`docs/gameplay-visual-updates-20261027.md` section 5).
* **Berries, vitamins, wings, PP Up and PP Max, Rare Candy, evolution stones: done** (below), through the game's own
  item code.
* **TMs and HMs: done** (below): numbering, the HM moves, who can learn them. A TM's reuse, its sale and forgetting an
  HM move were checked earlier (`--selftest-move-switch`).
* **The EV-training held items and the Soothe Bell: done** (below): the Macho Brace, the Power items, Pokerus, the
  Soothe Bell's friendship.
* **Mints: done** (below): each mint's nature and what a mint does to the stats.
* **Trade evolution items: done** (below): the Gen 1-6 trade evolutions and the items held for them.
* **The Ability Capsule and the Ability Patch: done after the first candidate** (below): what each does to a Pokemon's ability.
* **Focus Band and the fishing rods: done after the first candidate** (below): the band's effect in battles of the test ROM;
  the rods' bites and slots through the game's code, and each rod cast from the Bag in the real game.
* **What a ball does to the Pokemon it catches (Heal Ball, Friend Ball): done after the first candidate** (below).
* **The form-change key items and the Itemfinder: done after the first candidate** (below): the Meteorite, the Gracidea, the
  Reveal Glass and the Prison Bottle through the game's code; the Itemfinder used from the Bag in the real game.
* **Held items no test checked: 18 new GBA tests** (below): the Plates, Light Clay, Wide Lens, Lax Incense, Bright
  Powder, Soul Dew, the confusion berries, the Macho Brace's and Power items' halved Speed, Focus Sash, Flame Orb,
  Toxic Orb, Amulet Coin and Luck Incense.
* **Held items, battle items, Mega Stones in battle: the expansion's own tests** (below): the GBA test ROM's 860 tests
  for them, run on this build (806 passed, 3 expected failures, the rest to do or known upstream); 32 held-item files
  there have no test yet (listed).
* **Key items** (in the table of every item): all 72 are "important" (they cannot be tossed or sold) and have no
  price. Where the Bikes and the Escape Rope can be used, read from the maps' data (below); what each does from the Bag
  or in the story was checked after the first candidate (below), and step 14 finished them.
* **Every row checked or classified** (step 14, below): nothing in the table of every item is left "not audited". What
  is still not done as such is under "Not done".

## Poke Balls

The game's rules are the expansion's with its generation switches (`include/config/battle.h`). Here `GEN_LATEST` is
Gen 6 (`include/config/general.h`), so every ball follows its Gen 6 rule. The capture odds are
(3 x max HP - 2 x HP) x catch rate / (3 x max HP) x the ball's multiplier, x2.5 asleep or frozen, x1.5 paralysed,
burned or poisoned. Odds of 255 catch at once; below that each of three shakes holds with the game's shake chance.
Critical captures depend on the Pokedex and the Catching Charm (section 5 of the gameplay report).

`--selftest-balls` (new; `make -f Makefile_pc check-balls`): each ball's odds through `ComputeCaptureOdds` (the
function every throw uses), in the situations its rule names. Each is compared with the odds worked out from the rule
with the game's own integer steps; the shake check through `ComputeBallShakeOdds`. **61 checks, 0 failed** on engine
`6a575072`. Before the fixes (an earlier 60-check version of the test, on a build with neither change): 5 failed, the
four Heavy Ball cases below (a sure catch) and a Beast Ball check that expected a floor later withdrawn (fix 2); the
other 55 printed exactly the same lines as on the fixed build (the two logs compared line by line).

| Ball | Rule (Gen 6) | Checked (odds in the game = the rule's) |
| --- | --- | --- |
| Poke, Premier, Luxury, Heal, Friend, Cherish | x1 (Luxury and Friend act on friendship, Heal heals, after the catch: not capture math) | x1 |
| Great Ball | x1.5 | x1.5 |
| Ultra Ball | x2 | x2 |
| Master Ball | a sure catch | sure |
| Safari Ball | x1.5 (inside the Safari Zone the battle uses the Zone's own catch factor) | x1.5 |
| Sport Ball | x1.5 | x1.5 |
| Park Ball | a sure catch only in the Pal Park (not in this game), else x1 | x1 |
| Dream Ball | x1 (its x4 on a sleeping Pokemon is Gen 8) | awake x1; asleep only the x2.5 every ball gets |
| Net Ball | x3 on Water or Bug types | Magikarp x3, Caterpie x3, Bulbasaur x1 |
| Nest Ball | (41 - level) / 10 below level 30, else x1 | level 5 x3.6, level 29 x1.2, level 30 x1 |
| Dive Ball | x3.5 under the water, surfing or fishing | land x1; surfing, fishing, Underwater Route 124 x3.5 |
| Dusk Ball | x3.5 at night or in a cave | Granite Cave x3.5 (the hour of day: the PC's clock, not set by the test) |
| Timer Ball | 1 + 1229/4096 a turn, at most x4 | turn 0 x1, 1 x1.3, 5 x2.5, 10 x4 (capped) |
| Quick Ball | x5 on the first turn | turn 0 x5, later x1 |
| Repeat Ball | x3 for a species caught before | not caught x1, caught x3 |
| Level Ball | x8 at four times the level, x4 over twice, x2 over it | 40 vs 10 x8, 25 vs 10 x4, 15 vs 10 x2, 10 vs 10 x1 |
| Lure Ball | x3 when fishing | fishing x3, else x1 |
| Moon Ball | x4 for a Pokemon that evolves with a Moon Stone | Nidorino x4, Bulbasaur x1 |
| Love Ball | x8 for the player's species of the other gender | other gender x8, same gender x1, other species x1 |
| Fast Ball | x4 at base Speed 100 or more | Electrode x4, Bulbasaur x1 |
| Heavy Ball | catch rate -20 under 204.8 kg, +20 to 307.1, +30 to 409.5, +40 from 409.6, at least 1 | Bulbasaur -20, Golem +20, Steelix +30, Snorlax +40; Latias, Jirachi, Uxie: catch rate 1 (**fixed**, below) |
| Beast Ball (Gen 7) | x410/4096 on a Pokemon that is not an Ultra Beast | x0.1 (Latias: odds 0, as before) |
| Status | x2.5 asleep or frozen, x1.5 paralysed, burned or poisoned | asleep x2.5, paralysed x1.5 |

What the odds mean in play, for a catch rate 45 Pokemon (the game's numbers): a Poke Ball catches 12.5% of throws at
full HP and 29.6% at 1 HP; a Great Ball 16.8% / 38.5%; an Ultra Ball 20.8% / 51.2%; a Quick Ball on the first turn
44.2% / about 100%. At odds 1 a throw catches 1.64%; at odds 0 about 0.025% (1 in 4,000).

### Fixed (MS-148, MS-149; engine `4474883b` and `6a575072`, PC only)

1. **The Heavy Ball caught many legendaries at once.** On a Pokemon under 204.8 kg the ball takes 20 from the catch
   rate, and Gen 4-6 keep the result at least 1. The game's code added the -20 a second time when the result was 0 or
   less. For a Pokemon whose catch rate is 20 or less, that left a negative rate, which the unsigned odds wrapped
   round to 11,930,452: a sure catch. Measured through the game's code, Latias, Jirachi and Uxie each had odds of
   11,930,452 before the fix (Uxie at 1 HP 11,930,427) and 0 after it: a catch rate of 1 gives odds of 0 at any HP,
   so about 1 throw in 4,000 catches (see 2). About 50 Gen 1-6 species qualify, among them the legendary birds,
   Mewtwo, the legendary beasts, Ho-Oh, Regice, Latias and Latios, Jirachi, Deoxys, the lake trio, Cresselia, Manaphy,
   Darkrai, Victini, Virizion, the forces of nature, Keldeo, Meloetta, Diancie, Hoopa, Volcanion, Beldum, Metang and
   Volcarona. Heavy Balls are sold in Mauville's Game Corner (the rare goods), so this was reachable in normal play,
   with the static legendaries and the random 1 in 6000 ones. Now the catch rate is at least 1, as the rule says.
2. **A throw at odds 0 divided by zero; now written out, with the same result.** The shake check divides by the
   odds. A Beast Ball (x0.1; also sold in Mauville's rare goods) on a catch rate 3 Pokemon at full HP gives 0, and so
   does the fixed Heavy Ball on the Pokemon above. The game did not close: the PC's fault handler (`fault_compat.c`)
   gives the GBA's result for the division (0xFFFFFFFF), so a shake holds 4112 times in 65536 and a throw catches
   about 0.025%. The source now writes that result out, so the chance is the same without the undefined division (the
   rule N7 sets for such sites). The same test on the old shake code gives the same results, with the fault handler
   logging the division. Correction: the first commit (`4474883b`) raised such odds to 1, believing the game closed;
   that made the chance 1.6%, a balance change, and was withdrawn in `6a575072`.

No other ball or situation changes. The GBA ROM is unchanged (the fixes are in the PC build only). Pokemon already
caught are not touched.

### Owner decisions (reported, not changed)

* **The Beast Ball, Dream Ball, Park Ball, Sport Ball and Cherish Ball are sold** in Mauville's rare goods. The Beast
  Ball is Gen 7 (x0.1 on anything but an Ultra Beast, which Gen 1-6 has none of), the Park Ball has no effect outside
  the Pal Park, and the Cherish Ball was an event ball. They behave as their rules say; whether to keep selling them
  is the owner's choice.
* The Moon, Love and Fast Balls use their corrected rules (Gen 7), not HeartGold/SoulSilver's bugged ones; the Level
  Ball's 8x applies from exactly four times the level.
* **A catch rate of 1 catches about 1 throw in 4,000.** After the Heavy Ball fix, a light Pokemon with a catch rate of
  21 or less has a catch rate of 1 with that ball, which the integer odds make 0 at any HP or status (the Beast Ball
  likewise on low catch rates). Giving such throws a minimum (odds 1: about 1 in 61) would be a balance change, so it
  was not made; the owner's choice.

## Healing items

`--selftest-healing` (new; `make -f Makefile_pc check-healing`; engine `000d7556`, test code only): each item used on a
party Pokemon (a level 100 Snorlax, 430 HP) through `PokemonUseItemEffects`, what the bag's USE calls out of battle,
against the Gen 6 rule this build is set to (`include/config/item.h`: `I_HEALTH_RECOVERY` = Gen 6). **70 checks,
0 failed.**

| Items | Rule (Gen 6) | Checked |
| --- | --- | --- |
| Potion, Berry Juice, Sweet Heart | 20 HP | 1 -> 21 HP |
| Super Potion, Fresh Water | 50 HP (Gen 7: 60 and 30) | 1 -> 51 |
| Soda Pop | 60 HP (Gen 7: 50) | 1 -> 61 |
| Lemonade | 80 HP (Gen 7: 70) | 1 -> 81 |
| Moomoo Milk | 100 HP | 1 -> 101 |
| Hyper Potion | 200 HP (Gen 7: 120) | 1 -> 201; 10 short of full: to the maximum |
| Energy Powder, Energy Root | 50 and 200 HP (Gen 7: 60 and 120); friendship -5 / -5 / -10 and -10 / -10 / -15 (under 100, 100-199, 200 and over) | as the rule, friendship never below 0 |
| Max Potion; Full Restore | all HP; all HP and the status | 430; 430 and paralysis cured |
| Antidote (and bad poison), Burn Heal, Ice Heal, Awakening, Paralyze Heal, Blue Flute; Pecha, Rawst, Aspear, Chesto, Cheri Berries | their one status | each cured; no effect on another status or a healthy Pokemon |
| Full Heal, Heal Powder (friendship -5 / -5 / -10), Lava Cookie, Rage Candy Bar, Old Gateau, Casteliacone, Lumiose Galette, Shalour Sable, Lum Berry | every status | sleep, poison, burn, freezing, paralysis and bad poison each cured |
| Revive; Max Revive, Revival Herb (friendship -15 / -15 / -20), Sacred Ash | a fainted Pokemon back with half; with all its HP | 0 -> 215; 0 -> 430 |
| Ether, Max Ether; Elixir, Max Elixir | 10 PP / all PP to one move; to every move | as the rule, never past a move's maximum |
| No effect | an item that would do nothing is not used | Potion or Max Potion at full HP, Potion or Full Restore on a fainted Pokemon, Revive on one that has not fainted, Ether on a full move: no effect |

**A finding (MS-150, not changed: the owner's decision).** The game's friendship bonuses for an item - +1 for a Pokemon
met on the map it is on, +1 in a Luxury Ball (`CalculateFriendshipBonuses`) - are also added to a friendship loss, so a
herbal medicine costs 1 less there (Energy Powder on a Pokemon met on the current map: 150 -> 146, the official
rule 145; Energy Root on one in a Luxury Ball: 150 -> 141, the rule 140). The official games add them only to a gain.
Following the rule would cost those players 1 friendship more per medicine; the other checks above use a Pokemon met
elsewhere, in a plain ball.

Not checked here: an item used in battle (the same function, with the battler's own HP and status), the bag taking the
item away, the multiplayer save of the result, and the berries a Pokemon eats by itself in battle (the berries part).

## Berries, vitamins, wings, PP Up and PP Max, Rare Candy, evolution stones

`--selftest-bag-items` (new; `make -f Makefile_pc check-bag-items`; engine `228dbada`, test code only): each item used
on a party Pokemon (a level 50 Snorlax, 220 HP) through `PokemonUseItemEffects`, what the bag's USE calls out of
battle; a stone through `GetEvolutionTargetSpecies`, the evolution that function asks for before it starts the
evolution scene (the Pokemon is left as it was). The rules are the ones this build is set to (`include/config/item.h`,
Gen 6). **121 checks, 0 failed** (with the TM and HM checks below).

| Items | Rule (this build, Gen 6) | Checked |
| --- | --- | --- |
| Oran Berry; Sitrus Berry | 10 HP; a quarter of the maximum (Gen 4+) | 1 -> 11; 1 -> 56 of 220; no effect at full HP |
| Leppa Berry | 10 PP to the move chosen | Tackle 0 -> 10, the other moves untouched; no effect on a full move |
| Persim Berry; Figy Berry | confusion, only in battle; eaten only when held (no use from the bag) | no effect from the bag |
| HP Up, Protein, Iron, Calcium, Zinc, Carbos | +10 effort values in the stat, up to 100 (Gen 8's cap of 252 is off), never past 510 in all | 0 -> 10 each; 95 -> 100; at 100 no effect; with 505 in the other stats +5 (to 510); with 510 no effect |
| Health, Muscle, Resist, Genius, Clever, Swift Wings; Pretty Wing | +1 up to 252, never past 510 in all; nothing | 0 -> 1 each; 100 -> 101 (past a vitamin's limit); 251 -> 252; at 252, or 510 in all, no effect; Pretty Wing no effect |
| Pomeg, Kelpsy, Qualot, Hondew, Grepa, Tamato Berries | -10 effort values (not Gen 4's drop to 100), not below 0; friendship +10 / +5 / +2 | 100 -> 90 each; 252 -> 242; 5 -> 0; at 0 only the friendship (150 -> 155); at 0 with friendship 255 nothing changes and the bag keeps the berry ("It won't have any effect") |
| Friendship (under 100 / 100-199 / 200 and over) | vitamins, PP Up, PP Max, Rare Candy +5 / +3 / +2; wings +3 / +2 / +1; those berries +10 / +5 / +2; never past 255 | each tier as the rule (HP Up, Health Wing and Pomeg Berry at 50, 150 and 250; PP Up, PP Max, Rare Candy once each); 254 -> 255 |
| PP Up; PP Max | a fifth of the move's base PP more, three times at most; all three at once; not on a move under 5 PP | Tackle 35 -> 42 -> 49 -> 56, a fourth no effect; Surf 15 -> 24 with PP Max, then PP Up no effect; Hyper Beam 5 -> 6 -> 8; Sketch (1 PP) no effect; the PP left rises by the same amount (10 -> 17) |
| Rare Candy | the next level's experience, the HP the level adds | level 50 -> 51 at level 51's experience, HP +4 with the maximum; 99 -> 100; at 100 no effect and no friendship |
| Evolution stones | the evolutions in the species data | Pikachu -> Raichu (not Alola's), Eevee -> Jolteon, Vaporeon, Flareon, Leafeon, Glaceon; Growlithe, Vulpix, Lombre, Staryu, Nuzleaf, Gloom (both stones), Sunkern, Skitty, Clefairy, Togetic, Roselia, Murkrow, Misdreavus, a male Kirlia, a female Snorunt each to its evolution; none for a female Kirlia or a male Snorunt (Dawn Stone), Eevee with a Moon Stone, Charmander, Pikachu with a Water Stone, Raichu, or a Pokemon holding an Everstone (Emerald's rule) |

Measured and reported, not changed (each as the game's own data has it):

* **A Rare Candy revives a fainted Pokemon** with the HP the level adds (level 50 -> 51, HP 0 -> 4): Emerald's own
  Rare Candy data (a revive with the level-up HP).
* **Eevee evolves with a Leaf Stone or an Ice Stone** (Gen 8's rule), besides the Hoenn places this build gives
  Leafeon and Glaceon (Petalburg Woods, Shoal Cave's ice room).
* A Soothe Bell makes a vitamin's +3 a +4 (half again, rounded down).

## TMs and HMs

The same self-test. TM01-TM50 and HM01-HM08 are Emerald's (TM01 Focus Punch to TM50 Overheat, HM01 Cut to HM08 Dive):
58 items, each teaching its number's move (checked against a separate list of Emerald's), each in the TM pocket. The
eight HM moves are the only moves the game treats as HMs. Mew can learn all 58; Magikarp, Ditto, Smeargle, Caterpie,
Metapod, Kakuna, Wurmple, Silcoon, Cascoon and Beldum none; Snorlax Surf and Earthquake, Machamp Strength, Pidgeot and
Charizard Fly, Gyarados Waterfall, Wailmer Dive, Geodude Rock Smash, Zigzagoon Cut and Pikachu Thunderbolt yes;
Gyarados, Bulbasaur and Pikachu not Fly. On PC a TM is never used up and cannot be sold (`I_REUSABLE_TMS`, as in
Gens 5-8), and an HM move can be switched out while the HM is in the bag: `--selftest-move-switch` (84 checks), run
again on `228dbada` (the engine checks in `TEST_LEDGER.md`).

**Reported, not changed (owner decision):** who can learn a TM comes from the expansion's learnsets, which are the
later games', not Emerald's: Pikachu can learn Surf, Wobbuffet TM20 Safeguard and Unown TM10 Hidden Power, none of
which Emerald allows. Going back to Emerald's lists would take moves away from players' Pokemon.

## The EV-training held items and the Soothe Bell: Macho Brace, the Power items, Pokerus

`--selftest-held-items` (new; `make -f Makefile_pc check-held-items`; engine `2ea6e093`, test code only): the effort
values a Pokemon gains for a defeated Pokemon, through `MonGainEVs` (what a battle calls for each Pokemon that gains
experience), against Gen 6's rules (`I_POWER_ITEM_BOOST` below Gen 7: a Power item adds 4). The defeated Pokemon, a
Zigzagoon, yields 1 Speed. With the Soothe Bell's friendship (engine `6320c77d`): **21 checks, 0 failed.** The
expansion's own tests have none for these items' effort values or the Soothe Bell (below).

| Held | Rule (Gen 6) | Checked |
| --- | --- | --- |
| Nothing | the defeated Pokemon's yield | Speed +1 |
| Macho Brace; Pokerus (also once cured) | doubled; both together four times | +2; +2 (cured too); +4 |
| Power Weight, Bracer, Belt, Anklet, Lens, Band | 4 more in the item's stat, on top of the yield | each +4 in its stat, and Speed +1 |
| A Power item and Pokerus | (yield + 4) x 2 | Power Anklet: Speed +10; Power Bracer: Attack +8, Speed +2 |
| Limits | 252 in a stat, 510 in all | at 252 nothing; 250 with a Power Anklet: to 252; 509 in all: +1; 510: nothing |
| Soothe Bell (`AdjustFriendship`) | a friendship gain half again, rounded down (Gen 4+); a loss unchanged | a level up +5 -> +7, +3 -> +4, +2 -> +3 by tier; fainting -1 stays -1 |

Not checked: the Speed these items halve in battle, the experience a Lucky Egg or an Exp. Share gives, and the money
an Amulet Coin doubles (all worked out in the battle's own scripts; no test of their own upstream either).

## Mints

`--selftest-mints` (new; `make -f Makefile_pc check-mints`; engine `9b8df5c3`, test code only). **7 checks, 0
failed.** Each of the 21 mints gives the nature it is named after (its item data, checked against a separate list).
What the bag does with a mint (`Task_Mint` in `party_menu.c`, after the YES: the Pokemon's stat nature set to the
mint's, its stats worked out again) was run on a Hardy level 100 Snorlax: an Adamant Mint raises Attack by a tenth and
lowers Sp. Atk by a tenth, rounded down (225 -> 247, 135 -> 121), the other stats unchanged; a Jolly, then a Modest
Mint move the changes to their stats; a Serious Mint (neutral) gives every stat back. The Pokemon's own nature, which
Synchronize and breeding read, stays Hardy, and the stat nature is kept in the Pokemon's stored data (its box form, as
saved). The menu's "It won't have any effect" for a mint of the nature the Pokemon already has was not run (it is a
comparison in the menu's task).

## Trade evolution items

`--selftest-evo-items` (new; `make -f Makefile_pc check-evo-items`; engine `acea1d3f`, test code only). **33 checks, 0
failed.** The evolution a trade starts, through `GetEvolutionTargetSpecies` in its trade mode (what the classic link
trade asks, and a world trade's read-only preview; the Pokemon is left as it was): Kadabra, Machoke, Graveler, Haunter, Boldore, Gurdurr
and Phantump evolve by trade alone; Onix and Scyther holding a Metal Coat, Poliwhirl and Slowpoke a King's Rock,
Seadra a Dragon Scale, Porygon an Up-Grade, Porygon2 a Dubious Disc, Rhydon a Protector, Electabuzz an Electirizer,
Magmar a Magmarizer, Dusclops a Reaper Cloth, Clamperl a Deep Sea Tooth or Scale, Feebas a Prism Scale, Swirlix a
Whipped Dream and Spritzee a Sachet each evolve; none evolves without its item or with another's, or holding an
Everstone, except Kadabra (Gen 4+); Karrablast and Shelmet evolve only when traded for each other. The GBA test ROM's
own tests of a world trade's evolution (the item kept by the preview, the Everstone and Kadabra, a partner-specific
evolution) passed: 8 of 8 (`test/multiplayer_trade_effects.c`, engine `000d7556`). **But a world trade does not
evolve anyone (MS-151, open):** its trade menu refuses the 29 species that can evolve by trade, with or without
their item ("Trade evolution is not enabled for this build", `trade_eligibility.py`), so these items do nothing in a
friend's trade today; mail is refused there too. Not checked: the evolutions that
need a held item at a level up (Happiny's Oval Stone by day, Gligar's Razor Fang and Sneasel's Razor Claw at night),
which depend on the game's clock.

## The Ability Capsule and the Ability Patch (after the first candidate)

`--selftest-ability-items` (new; `make -f Makefile_pc check-ability-items`; engine `8db6561e`, test code only, in the
2026-10-27 package). **16 checks, 0 failed.** What each item does to a Pokemon's ability, by the rules the party
menu checks before it changes it (`party_menu.c` `Task_AbilityCapsule` and `Task_AbilityPatch`; their conditions are
copied into the test, because the tasks ask and answer through the menu's windows), checked against the species'
data through `GetMonAbility`. The Capsule switches between a species' two abilities (Geodude's Rock Head and Sturdy,
both ways; Magnemite's Sturdy to Magnet Pull) and has no effect on a species with one ability (Bulbasaur, Unown,
Shedinja) or on a Pokemon that has its hidden ability. The Patch gives the hidden ability (Geodude's Sand Veil,
Magnemite's Analytic, Bulbasaur's Chlorophyll) and takes it back to the first, and has no effect where a species has
no hidden ability (Unown, Shedinja) or on an Egg. The new ability is kept in the Pokemon's stored data (its box form,
as saved). Not run: the menu's screens and the item leaving the bag.

## Focus Band (after the first candidate)

Three new GBA tests (`test/battle/hold_effect/item_audit_untested.c`, engine `fc8c5f76`, test code only, in the
2026-10-27 package): **3 of 3 passed**. The band's roll is a plain `Random() % 100` below its 10 (`battle_util.c`),
which the test runner cannot steer, and measured over the runner's 50 seeds it held on 7 times (14%; within chance of
10%, but outside the runner's 2% tolerance), so the tests fix the seed instead, as the expansion's own Final Gambit
test of the band does: on a seed whose roll succeeds, a holder below full HP hangs on at 1 HP ("... hung on using its
Focus Band!") and keeps the band (it is not used up, unlike the Focus Sash); a Pokemon without a band faints on the
same seed; on a seed whose roll fails, the holder faints. Its 10% is the item's data (checked by the test).

## The fishing rods (after the first candidate)

`--selftest-rods` (new; `make -f Makefile_pc check-rods`; engine `7054b688`, test code and two PC-only wrappers, in
the 2026-10-27 package): **41 checks, 0 failed.** Through the game's own code: the Old, Good and Super Rods get a bite
25, 50 and 75% of the time (the Gen 4+ odds the game is set to; Emerald had 50% for each), doubled by a lead with
Suction Cups or Sticky Hold (50, 100, 100), not by an Egg; each rod picks only its own slots of a map's fishing table
(Old 0-1, Good 2-4, Super 5-9) at Emerald's rates (70/30; 60/20/20; 40/40/15/4/1; 200,000 bites each), and with a lure
a fifth of them are swapped end for end (the expansion's lure rule); all 53 maps' fishing tables have a Pokemon in
every slot, its levels in order.

`tools/battle_env/rods_check.py` (new, engine `c624a2d4`, test builds only): each rod cast **from the Bag in real game
processes** (START > BAG > KEY ITEMS > the rod > USE, on Route 109's beach facing the sea; a test-only switch answers
"Oh! A bite!" in time, as a person reacting to it): every rod hooked a Pokemon and its battle started, at a level of the
rod's own slots (Old Rod a level-8 Tympole, Good Rod a level-18 Goldeen, Super Rod a level-25 Tentacool in the Classic
2D test build; a level-6 Barboach, a level-23 Basculin and a level-34 Goldeen in the 3D one), and the rod stayed in the
Bag: **PASS in both builds**. The species is not the map's own: the PC game draws a fished Pokemon from its fishing
pool (`mp_wild_random.c`), keeping the slot's level (a custom rule, unchanged).

## The form-change key items and the Itemfinder (after the first candidate)

`--selftest-form-items` (new; `make -f Makefile_pc check-form-items`; engine `993496aa`, test code only, in the
2026-10-27 package): **22 checks, 0 failed.** Through `TryFormChange` with the item as the one used, the call the party
menu makes before its animation: the Meteorite turns Deoxys Normal, Attack, Defense, Speed and back (ORAS), its stats
worked out again for each form (Attack 155 -> 185 as the Attack form) and the form kept in its stored data; the
Gracidea makes Shaymin its Sky Forme at noon but not at 22:00 or while it is frozen; the Reveal Glass turns Tornadus,
Thundurus and Landorus from Incarnate to Therian and back; the Prison Bottle unbinds Hoopa; each does nothing for
another species, another form species or an Egg. On Hoopa Unbound the Prison Bottle does nothing (it goes back by
being put in the PC or after three days: the Gen 6 rule, unchanged). Not run: the party menu's screens for these.

The DNA Splicers (a party-menu task of two Pokemon and the PC's fusion storage) **used from the Bag in real game
processes** (engine `c624a2d4`, the Classic 2D test build, the presses a person makes, the party read from the game's
log): Kyurem and Reshiram in the party, "Use on which POKeMON?" Kyurem, "Choose ... to fuse with." Reshiram, "Kyurem
transformed!": the party is White Kyurem alone (level 50); the Splicers again on White Kyurem: "Kyurem transformed!",
the party Kyurem and Reshiram again (scratchpad `splicers/`).

The Itemfinder (the Bag calls it the Dowsing Machine) **used from the Bag in real game processes** (engine `c624a2d4`,
the Classic 2D test build, the presses a person makes): two tiles from Route 104's hidden Potion, "Huh? The
ITEMFINDER's responding!", the player turning, "There's an item buried around here!"; on Route 101, which hides
nothing, "...Nope! There's no response." (pictures, scratchpad `itemfinder/`). Its messages still call it the
ITEMFINDER while the Bag names it the Dowsing Machine (text, not changed).

## What a ball does to the Pokemon it catches (after the first candidate)

Three new GBA tests (`test/battle/item_effect/item_audit_balls.c`, engine `99b9a03d`, test code only; the catch made
sure of as the expansion's own capture tests do): **3 of 3 passed.** A Caterpie caught in a Heal Ball at 1 HP,
paralysed, its move at 3 PP, has its HP full, no status and its PP full (35); caught in a Poke Ball it keeps all
three; a Friend Ball gives it 200 friendship (Gen 6; the expansion's Gen 8 rule would give 150), a Poke Ball the
species' own. The Luxury Ball's bonus to friendship gained is the healing self-test's (above, MS-150).

## The Go-Goggles in the real game (after the first candidate)

Route 111's desert in real game processes (engine `c624a2d4`, the Classic 2D test build), walking north into it from
its south edge: without Go-Goggles in the Bag, "The sandstorm is vicious. It's impossible to keep going." and the
player is pushed back; with them, the player walks on into the desert (pictures, scratchpad `goggles/`). The check is
the map's own script (`checkitem ITEM_GO_GOGGLES`).

## The Devon Scope and the Wailmer Pail in the real game, and MS-156 (after the first candidate)

A hidden Kecleon on Route 120 (20,11) talked to in real game processes (engine `c624a2d4`, the Classic 2D test build):
without the Devon Scope, "Something unseeable is in the way."; with it, "Want to use the DEVON SCOPE?", YES, "DARREN
used the DEVON SCOPE.", "An invisible POKeMON became completely visible!", "The startled POKeMON attacked!" (pictures,
scratchpad `devonscope/`). The battle that should follow did not start: the game was not connected to a world, and
these optional static encounters ask the Local Soft Reset's admission first, which refuses offline (**MS-156**, open,
in `KNOWN_ISSUES.md`: the same for the Regis, the weather legendaries, the Electrodes, Voltorbs, Sudowoodo, the
Latis, Lugia, Ho-Oh, Mew and Deoxys offline; the story's bridge Kecleon is not affected).

**Fixed after the first candidate** (engine `223d15e1`, PC only): a save no world has enrolled meets these as ordinary battles
(no admission, no reset in them); an enrolled save keeps the admission. In the same real-game run offline, the
Kecleon's battle then starts ("You encountered a wild Kecleon!"), and so does Sudowoodo's at the Battle Frontier after
the Wailmer Pail from the Bag ("The weird tree doesn't like the WAILMER PAIL!", "The weird tree attacked!", "You
encountered a wild Sudowoodo!"; scratchpad `ms156/`).

## The Soot Sack in the real game (after the first candidate)

Route 113 in real game processes, offline: the Classic 2D test build (engine `223d15e1`) and a 3D test build made at
16:46 UTC (the ash's code, `field_tasks.c`, and the Glass Workshop's script are the same in both, in the first
candidate `6320c77d` and in the package's `a5013203`). The Soot Sack in the Bag, the ash count set to 0 and the
workshop's state to "has the Soot Sack" (the test build's variable settings): five steps east through ash grass, the same five back over the tiles they
cleared (grass now), then into the Glass Workshop to its owner: "Let's see... 245 is the number of steps you'll need
to walk for me to make you a BLUE FLUTE", 250 less the 5 steps, the same in 2D and 3D; the steps back added nothing
(pictures, scratchpad `sootsack/`). A walk without the Soot Sack was not run (the owner then asks for the Soot Sack
and does not say the count).

## The Wailmer Pail on a berry tree (after the first candidate)

Route 104's empty soil plot (35,6) in real game processes, the Classic 2D test build (engine `223d15e1`), with an Oran
Berry and the Wailmer Pail in the Bag: "It's soft, loamy soil. Want to plant a BERRY?", YES, the Bag's Berries pocket,
the Oran Berry: "DARREN planted one Oran Berry in the soft, loamy soil."; talked to again: "One Oran Berry was planted
here.", "Want to water the Oran with the WAILMER PAIL?" (the berry's short name, as the script fills it in), YES:
"DARREN watered the Oran.", "The plant seems to be delighted."; then from the Bag (Key Items, the Wailmer Pail, USE)
facing the plant: the same watering and "The plant seems to be delighted." (pictures, scratchpad `berrypail/`).

What watering does takes hours of the game's clock, so it is checked with a self-test instead, `--selftest-berry-water`
(`make check-berry-water`, engine `bbf722b7`): a Pomeg Berry (Gen 3 yields, 2 to 6) planted as the field plants one,
grown stage by stage with the game's own `BerryTreeGrow` and watered through the function the tree's script and the
Bag call (`ObjectEventInteractionWaterBerryTree`), 500 trees for each number of watered stages: never watered, yields
2 to 2 (mean 2.00); one stage, 2 to 3 (2.56); two, 3 to 4 (3.57); three, 4 to 5 (4.63); all four, 5 to 6 (5.62), each
the band Gen 3's rule gives (the minimum plus a quarter of the range for each watered stage); watering twice in each of
two stages counts once (3 to 4); a tree with its berries and empty soil refuse water. 10 checks, 0 failed.

## The Mega Ring in the real game (after the first candidate)

Mega Evolution asks for the Mega Ring in the Bag (`battle_util.c` `CanMegaEvolve`); the GBA test ROM skips that
check, so its tests cannot show it. Two wild battles in real game processes (the Classic 2D test build, engine
`223d15e1`; `tools/battle_env/mega_check.py --only wild --only no-mega-ring`): a level-50 Charizard holding
Charizardite X against a wild Poochyena. With the Mega Ring in the Bag, the move menu offered Mega Evolution, the
trigger turned on and Charizard became Mega Charizard X (Fire/Dragon, Tough Claws), won, and was Charizard holding its
stone after the battle; without it, the menu did not offer Mega Evolution and Charizard fought as itself. 2 of 2 cases
passed (scratchpad `megaring/run2d/mega_check.json`).

## The Town Map and the Coin Case from the Bag, and MS-157 (after the first candidate)

Both used from the Bag's Key Items in real game processes (the Classic 2D test build, engine `223d15e1`, Route 104):
the Town Map, "DARREN took a closer look at the HOENN region map.", the region map at ROUTE 104, B back to the field;
the Coin Case with 123,456 coins (the test build's coin setting), "Your COINS: 123456", the PC wallet's six digits
(pictures, scratchpad `keyitems/`). Its description still said "A case that holds up to 9,999 Coins." although the PC
game's wallet holds up to 999,999 coins since Update 29 (**MS-157**, in `KNOWN_ISSUES.md`); fixed after the first candidate
(engine `4f841321`, PC only): "A case that holds up to 999,999 Coins."; the GBA ROM keeps its own text.

## The Exp. Charm (after the first candidate)

Two new GBA tests (`test/battle/item_effect/item_audit_key_items.c`, engine `aebcf98d`), made as the expansion's own
Lucky Egg test is: the same wild battle with and without the Exp. Charm in the Bag, the experience gained half again
as much with it; and with a held Lucky Egg in both, the charm's boost still applies on top of the egg's. 2 of 2 pass
(`make check TESTS="Exp. Charm"`). The co-op battles' rewards take the same path (`--selftest-coop-exp` compares
them with and without the charm).

## Step 14 finished: every item's row (after the first candidate)

The owner made the full item audit the package's gate (19:28 UTC): the package waits for it and includes it. Every
row of the items table that still said "not audited" is now checked or classified: 274 rows by a self-test or a
real-game check of today (L), 373 by the GBA test ROM (T), 15 story key items (code read), 47 not obtainable, 114 with
no use and 50 spare TM numbers; none left (`docs/item-audit-20261027-items.md`). Engine commits `47e47359` ..
`3c9e3088` (tests, and MS-158's fix, PC only); the GBA ROM is unchanged (`f214735b...`).

* **In the real game** (real game processes and the presses a person makes, the Classic 2D test build; pictures,
  scratchpad `field14/`, `keyitems/`): the Escape Rope used in Rusturf Tunnel, out by the tunnel on Route 116 and the
  rope gone from the Bag; Honey used in Route 101's grass, a wild battle as Sweet Scent's (both engine `4f841321`); the
  Mach Bike and the Acro Bike got on from the Bag and ridden; the Powder Jar ("POWDER QTY: 0") and the Pokeblock Case
  opened from the Bag; New Mauville's door, "Use the BASEMENT KEY?" and opened with the Basement Key, locked without
  it (engine `812d7bf3`).
* **Mail and MS-158** (found here): `--selftest-mail` (new, `check-mail`, engine `6dcc0760`): each of the twelve
  Mails given to a Pokemon and taken back into the PC; the party's six mail slots filled in turn and a seventh Mail
  refused; **27 checks, 0 failed**. In the real game
  (engine `6dcc0760`) CHECK on an Orange Mail in the Bag stopped the test build on an assert ("invalid species:
  12917"): the Bag handed the Mail screen a Mail on its stack, which the screen reads again after the Bag's function
  has returned. Fixed (engine `812d7bf3`, PC only): the Orange Mail's design shows and B returns to the Bag (scratchpad
  `ms158/mail-after-sheet.png`). A player's PC game logged that error to `errors.log` and went on (MS-71); the GBA ROM
  is unchanged (`KNOWN_ISSUES.md` MS-158).
* **The coin shop's items** (`--selftest-rare-goods`, new, `check-rare-goods`, engines `a6b653a8`, `3c9e3088`): the
  Exp. Candies, the Mochi and the Fresh-Start Mochi, the Linking Cord (a trade-alone evolution only), the Black
  Augurite, the Rotom Catalog's and the Zygarde Cube's choices, and the four Nectars a wild Oricorio holds, each to its
  style: **46 checks, 0 failed**. The Bottle Caps in the real game again (`train_check.py`, 8 of 8 steps).
* **Evolutions on a level up holding an item at a time of day** (`--selftest-evo-items`, engine `059e906e`, now 42
  checks, 0 failed): Happiny holding an Oval Stone by day, Sneasel holding a Razor Claw and Gligar holding a Razor
  Fang at night, none at the other time.
* **New GBA tests** (T, engine `47e47359`, 5 of 5 passed): a Plate does not boost a move of another type; each Plate
  is its own type's, with a 20% boost; each Memory is its own type's; Heavy-Duty Boots against Stealth Rock and
  against Toxic Spikes, a Pokemon switching in with and without them.
* **The story's key items** (15, code read): the scripts that give, check and take each one, traced; as in Emerald
  (the Scanner and the Storage Key are item balls, the rooms' keys are hidden items). None of the 15 was used in the
  real game: the S.S. Ticket, the Eon, Mystic and Aurora Tickets, the Old Sea Map, the Letter, the Devon Parts, the
  Scanner, the Storage Key, the Keys to Rooms 1, 2, 4 and 6, the Magma Emblem and the Contest Pass (the next session).
* **Not obtainable** (47): nothing gives, sells or drops them (the scripts, the maps' item balls and hidden items, the
  marts, the PC's shops and the wild Pokemon's held items, read out); Kanto's items need Kanto, whose maps this game
  never reaches. Two key items the GBA tests name, the Silph Scope and the Poke Flute, are also given only by Kanto's
  maps.
* **An item's multiplayer sync** (L, two native game processes through a real world server, engine `3c9e3088`;
  `scripts/multiplayer/native_trade_proof.py`): A's Torchic holding Leftovers traded for B's Treecko through the
  in-game Players menu. The proof's own checks passed: both offers shown, A's confirmation alone commits nothing, the
  trade applied in both running games, ownership conserved, each party equal to its canonical save. B's saved party
  after it: Torchic, level 5, holding Leftovers (species 255, item 472); A's: Treecko with no item (scratchpad
  `mp/multiplayer-proof/trade-held-4/`, `mpsync/trade-held-4-parties.txt`). The proof's next step, B backing out of a
  second trade, timed out: it presses B and waits, but since MS-68's fix (2026-10-24) backing out opens "Cancel the
  trade?" with No first, which the proof (last changed 2026-10-21) never answers. That step is for the next session;
  the trade above does not depend on it.

## A held item in a real battle of the PC game (after the first candidate)

A wild battle in the Classic 2D test build (engine `c624a2d4`; the battle the PC game runs, its screens and its
controller), the lead a level-14 Zigzagoon holding Leftovers against a wild Poochyena, both knowing Tackle (the test
build's own party and move settings), pictures every 15 frames: the Zigzagoon at 38/38 HP takes a Tackle (31/38),
the end of the turn shows "Zigzagoon's Leftovers" and its HP rises to 33/38, a sixteenth of 38 (scratchpad
`leftovers/`). The other held items' effects are the battle code's, tested in the GBA test ROM (above).

## The Bag in the real game (after the first candidate)

The game's existing real-game checks (`tools/battle_env/*_check.py`: real game processes, the presses a person makes,
the counts read from the game's own log) were run again on engine `c624a2d4` (the Classic 2D test build; not on
Windows): **all four passed**.

* `train_check.py` (8 steps): a Bottle Cap, a Gold Bottle Cap and an Ability Patch used from the Bag on the lead; each
  used item left the Bag (Bottle Caps 3 -> 2, the Gold Bottle Cap 1 -> 0, the patches 2 -> 1 -> 0); an item refused
  ("It won't have any effect": nothing left to train, every IV 31) left nothing used; the counts and the Pokemon the
  same after the save was loaded.
* `evolve_check.py` (8 steps): a Rare Candy (Zigzagoon 19 -> Linoone 20), the evolution stopped with B (still a level-20
  Zigzagoon), a Fire Stone (Vulpix -> Ninetales), an evolution after a won battle; each saved and loaded. (It reads the
  Pokemon, not the Bag's counts.)
* `catch_check.py` (4 steps): a Master Ball thrown from the battle's Bag at a wild Magikarp and Poochyena: caught, the
  ball used (1 -> 0), the catch in the party or sent to the PC, saved and loaded.
* `shop_check.py` (4 steps): a Potion bought at the Oldale Mart (money 3,000 -> 2,700, Potions 0 -> 1) and sold back
  (2,850, 0), each saved and loaded.

## Held items no test checked: new GBA tests

`test/battle/hold_effect/item_audit_untested.c` (new; the GBA test ROM only, engines `800015dd` and `6320c77d`):
**18 tests, all passing** (`make check TESTS="..."`; the first 15 also in the whole suite, below). Each checks a Gen 1-6 held item that no test of the expansion named or whose
own test is still "to do" upstream, against the Gen 6 rules. Three were also run with the item's effect taken away
(Light Clay, Wide Lens, Focus Sash) and then fail, so they test the item.

| Item | Checked (Gen 6) |
| --- | --- |
| The 17 Plates | 20% more power for their type's moves |
| Light Clay | Reflect lasts 8 turns (5 without it) |
| Wide Lens | the holder's accuracy x1.1 (Sing 55 -> 60%) |
| Lax Incense, Bright Powder | the accuracy against the holder x0.9 (Sing 55 -> 49%) |
| Soul Dew | Latios's special moves x1.5, another Pokemon's unchanged |
| Figy, Wiki, Mago, Aguav, Iapapa Berries | 1/8 of the maximum HP at half HP; not eaten above half |
| Macho Brace, the six Power items | the holder's Speed halved (100 moves after 60) |
| Focus Sash | at full HP survives a knock-out hit with 1 HP, used up; does nothing below full HP |
| Flame Orb, Toxic Orb | burns / badly poisons the holder at the end of the turn, not used up; not a Fire type / a Steel or Poison type |
| Amulet Coin, Luck Incense | a trainer battle's prize money doubled when the player's Pokemon holds one; once however many hold one; not for an opponent's |

Not testable this way: Focus Band's 10% (its roll is an untagged random number the test framework cannot steer).
Already tested elsewhere in the expansion: Smoke Ball (`ability/arena_trap.c`), Grip Claw
(`move_effect_secondary/wrap.c`), Power Herb (`geomancy.c` and others), Lucky Egg and Exp. Share (`exp.c`).

## Where the Bikes and the Escape Rope can be used (the maps' data)

The game lets a Bike be ridden where the map allows cycling (`Overworld_IsBikingAllowed`, the map's `allow_cycling`)
and an Escape Rope, or Dig, be used where it allows escaping (`CanUseDigOrEscapeRopeOnCurMap`, `allow_escaping`).
Read from all 520 Hoenn maps' `map.json` (the FRLG copies left out; **L**, data only, not run in a game):

| Maps | Count | Escape Rope | Bike |
| --- | --- | --- | --- |
| Caves and dungeons (underground) | 105 | yes in 85 | yes in 80 |
| Routes, towns, cities, the sea, under the water | 82 | no | yes in 80 |
| Buildings and rooms (indoor), secret bases | 333 | no | yes in 5 |

The exceptions follow the places' design: Navel Rock's 20 caves allow neither an Escape Rope nor a Bike;
the legendary chambers (Cave of Origin B1F, the ends of Marine Cave and Terra Cave, Seafloor Cavern's Room 9) and
Marine Cave's entrance allow no Bike; Sky Pillar's top and an unused prototype of Route 104 allow no Bike; the two
Cycling Road gatehouses, Faraway Island's two maps and Navel Rock's outside allow a Bike although they are counted as
indoor maps. Not checked in a game: riding, the Dad's advice when a Bike cannot be used, an Escape Rope's warp.

## Held items, battle items, Mega Stones in battle: the expansion's own tests

The engine carries the expansion's battle tests (`test/battle/`), built into a GBA test ROM with this build's rules
(Gen 6) and run by `make check`. On engine `000d7556` (2026-10-27, 1,077 s): **6,077 tests, 5,574 passed; the 39 that
failed are exactly the 39 expected** (tests written for later generations' rules, `docs/gba-test-expected-failures.txt`,
compared name by name by `scripts/diagnostics/check_gba_test_failures.py`: 0 new); 19 known failing upstream, 15
failed assumptions, 421 still to be written upstream, 9 expected to fail. The test ROM leaves out the PC-only code, so
the result stands for the later commits too (`228dbada`, `2ea6e093` and `9b8df5c3` add PC self-tests only).

The item tests among them (each test's title looked up in its file):

| Group | Files | Tests | Passed | Failed | Known failing | Failed assumption | To do |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Held items in battle (`test/battle/hold_effect`) | 129 | 454 | 415 | 3 | 0 | 1 | 35 |
| Items used from the bag in battle (`test/battle/item_effect`) | 11 | 84 | 78 | 0 | 0 | 0 | 6 |
| Moves that use or move items (Fling, Knock Off, Trick, Bestow, Recycle, Natural Gift, Embargo, Magic Room...) | 13 | 144 | 140 | 0 | 1 | 0 | 3 |
| Abilities that use or move items (Pickup, Harvest, Frisk, Klutz, Unburden, Pickpocket, Symbiosis...) | 13 | 119 | 115 | 0 | 1 | 0 | 3 |
| Mega Evolution and Primal Reversion (Mega Stones, the orbs) | 5 | 56 | 55 | 0 | 1 | 0 | 0 |
| The bag (sorting) | 1 | 3 | 3 | 0 | 0 | 0 | 0 |

The three failures are among the 39 expected: White Herb with Weak Armor (two tests), where the tests expect Gen 7's
+2 Speed and Gen 6 gives +1, and Air Balloon with Disguise (Gen 8's Disguise rules). Each file's numbers:
`docs/item-audit-20261027-tests.md`.

**Held items whose own upstream test file is still "to do"**: Smoke Ball; the five confusion berries; Amulet Coin and
Luck Incense; Bright Powder and Lax Incense; Exp. Share and Lucky Egg; Macho Brace and the Power items; Flame Orb and
Toxic Orb; Focus Band and Focus Sash; Soothe Bell; Grip Claw; Light Clay; Power Herb; Wide Lens; Soul Dew; the plates,
drives and memories; Everstone; Cleanse Tag; the Mega Stone and primal orb hold effects; Heavy-Duty Boots, Loaded Dice,
Punching Glove. Of these, today's new tests (above) cover the confusion berries, Bright Powder and Lax Incense, the
Macho Brace and Power items, Flame and Toxic Orb, Focus Sash, Light Clay, Wide Lens, Soul Dew, the plates, Amulet Coin
and Luck Incense; the Power items' and Macho Brace's effort values, the Soothe Bell, the Everstone and Cleanse Tag have
today's self-tests; other expansion tests cover Smoke Ball (`ability/arena_trap.c`), Exp. Share, Lucky Egg, Grip Claw
and Power Herb; Mega Evolution and Primal Reversion are tested in `form_change`. **Still with no test** (in the first candidate): Focus Band (its
roll cannot be steered by the tests; tested after the first candidate on fixed seeds, above), the drives and memories (Gen 5 and 7), and three later items (Heavy-Duty Boots,
Loaded Dice, Punching Glove). Step 14 (above) added tests of the Memories' types and of Heavy-Duty Boots; the drives',
Loaded Dice's and Punching Glove's own files are still "to do" upstream (other tests that name these items pass). The cure berries' and the HP berries' own files point
to `cure_status.c` and `restore_hp.c`, which are tested.

## Not done (this round)

* A ball thrown in a real battle (the self-test calls the same function the throw does; a battle's bag was not
  driven). A ball's consumption, its effect after the catch (Heal, Friend, Luxury), its multiplayer sync and its save
  were not checked in this round.
* The bag items, TMs and HMs above were used through the game's functions, not through the bag's screens; the bag
  taking the item away, an item's multiplayer sync and its save were not checked.
* The held items listed above as still with no test; a real battle in the PC game with any held item (the GBA test
  ROM runs the same battle code, without the PC parts).
* Key items and the other charms.

After the first candidate (above): a Master Ball thrown in a real battle and used up, items used from the Bag and
refused, bought and sold, each saved and loaded (the real-game checks), the rods cast from the Bag, Focus Band, the
form-change key items, the Itemfinder, the Heal Ball's and Friend Ball's effects on the Pokemon caught, Leftovers in a
real battle, the DNA Splicers, the Go-Goggles, the Devon Scope (MS-156 found and fixed), the Wailmer Pail on Sudowoodo
and on a berry tree, the Soot Sack, the Mega Ring, the Town Map, the Coin Case (MS-157 found and fixed); then step 14
(above): the Escape Rope, Honey, the Bikes, the Powder Jar, the Pokeblock Case, the Basement Key, Mail (MS-158 found
and fixed), the coin shop's items, the held-item evolutions, the Plates, the Memories and Heavy-Duty Boots, the story's
key items, the items nothing gives, and a held item carried by a trade between two running games. Nothing in the
items table is left unaudited. Still not done as such: the 15 story key items used in the real game (their scripts
were read, step 14 above); a real battle in the PC game with held items other than Leftovers (their effects are the
battle code's, tested in the GBA test ROM); the expansion's own hold-effect files
still "to do" for the drives, Loaded Dice and Punching Glove; the trade proof's later step that backs out of a second
trade (it predates MS-68's "Cancel the trade?" page and never answers it); nothing ran on Windows or a player's PC.
