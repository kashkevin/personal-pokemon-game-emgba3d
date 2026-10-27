# Item audit (2026-10-27): Poke Balls and healing items

The owner's request "Full item audit" (every item of Gen 1-6: Poke Balls and their capture math, healing, held items,
berries, TMs and HMs, evolution items, charms, mints, Mega Stones, key items and so on). It asks for an item-by-item
report, with each item's effect, usage conditions, consumption, interactions, multiplayer sync and saving checked
against real behaviour. Existing balance must not change silently. Nothing here is packaged.

Where a result comes from: **L** this Linux machine (the game's own functions in self-tests). Nothing here was tried
on Windows or on a player's PC.

## What this round covers

* **Poke Balls: done** (below), every ball of the game's list through the game's own capture code.
* **Healing items: done** (below), every healing item through the game's own item code.
* **Items that touch wild Pokemon: done earlier today**: the Shiny Charm, lures and Repels, the flutes, Cleanse Tag,
  Pure Incense, the encounter-rate abilities, Synchronize, Cute Charm, Magnet Pull and Static, Keen Eye, Hustle, Compound
  Eyes, the Catching and Oval Charms (`docs/gameplay-visual-updates-20261027.md` section 5).
* **Not audited yet** (kept for the next session): held items in battle, berries (beyond the status berries below),
  TMs and HMs, evolution items, mints, Mega Stones, key items, the other charms, and the battle items. A ball's consumption, its multiplayer
  sync and its save were not looked at either, nor was a real throw in a battle (see "Not done").

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

## Not done (this round)

* A ball thrown in a real battle (the self-test calls the same function the throw does; a battle's bag was not
  driven). A ball's consumption, its effect after the catch (Heal, Friend, Luxury), its multiplayer sync and its save
  were not checked in this round.
* Every other item category (listed at the top).
