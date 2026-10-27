# Item audit (2026-10-27): every item, one by one

Every item in the game's item list (873, Gen 1-9 as the expansion has them), read out of the built game (engine
`9b8df5c3`, the 2D game's own item table, with gdb), and what checked it today. "After the first candidate" marks a
check made after engine `6320c77d`; the package (engine `a5013203`) has all of them. **L** this Linux
machine; **T** the GBA test ROM (`make check` on engine `6320c77d`, the expansion's own battle tests and today's new ones, Gen 6 rules).
Summary and findings: `docs/item-audit-20261027.md`; the test files' numbers: `docs/item-audit-20261027-tests.md`.

Columns: the item's number and name; its price (what a shop asks; it sells for half); what using it from the bag does
(the game's function, `ItemUseOutOfBattle_` left out; `-` none); its use in battle; its effect when held; what checked
it. "GBA tests that name it" counts the expansion's tests whose code names the item, with their results (a test may
name an item only in passing, as Embargo's names the items it blocks); "held:" and "in battle:" name the test file
for the item's effect, which tests it with one or more items, not always this one. "Not audited" is kept for the next
session.

| What checked it | Items |
| --- | --- |
| a self-test or a real-game check of today's audit (L), some also the expansion's tests | 274 |
| the GBA test ROM: the expansion's tests that name it or test its effect, and today's new ones (T) | 373 |
| a story key item: the scripts that give, check and take it read (code read) | 15 |
| not obtainable in this game (nothing gives, sells or drops it; Kanto's items: Kanto is never reached) | 47 |
| no use from the bag, in battle or held (sold, traded, or given to someone: fossils, shards, Heart Scales) | 114 |
| spare TM numbers (TM51-TM100): no move, given nowhere | 50 |
| all | 873 |

## Poke Balls (28)

| # | Item | Price | From the bag | In battle | Held | Checked by |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Poké Ball | 200 | - | throw | - | Poke Balls self-test; GBA tests that name it: 20 passed; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do |
| 2 | Great Ball | 600 | - | throw | - | Poke Balls self-test; GBA tests that name it: 7 passed; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do |
| 3 | Ultra Ball | 1200 | - | throw | - | Poke Balls self-test; GBA tests that name it: 7 passed; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do |
| 4 | Master Ball | 0 | - | throw | - | Poke Balls self-test; GBA tests that name it: 7 passed; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do |
| 5 | Premier Ball | 200 | - | throw | - | Poke Balls self-test; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do |
| 6 | Heal Ball | 300 | - | throw | - | Poke Balls self-test; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do; after the catch: a new GBA test (engine `99b9a03d`, after the first candidate) passed |
| 7 | Net Ball | 1000 | - | throw | - | Poke Balls self-test; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do |
| 8 | Nest Ball | 1000 | - | throw | - | Poke Balls self-test; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do |
| 9 | Dive Ball | 1000 | - | throw | - | Poke Balls self-test; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do |
| 10 | Dusk Ball | 1000 | - | throw | - | Poke Balls self-test; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do |
| 11 | Timer Ball | 1000 | - | throw | - | Poke Balls self-test; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do |
| 12 | Quick Ball | 1000 | - | throw | - | Poke Balls self-test; GBA tests that name it: 2 passed; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do |
| 13 | Repeat Ball | 1000 | - | throw | - | Poke Balls self-test; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do |
| 14 | Luxury Ball | 1000 | - | throw | - | Poke Balls self-test; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do; its friendship bonus: on a loss measured by the healing self-test (MS-150, an owner decision); on a gain, 1 more, the held-items self-test after the package (engine `e6c8f2d8`; its game code the same in the package) |
| 15 | Level Ball | 300 | - | throw | - | Poke Balls self-test; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do |
| 16 | Lure Ball | 300 | - | throw | - | Poke Balls self-test; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do |
| 17 | Moon Ball | 300 | - | throw | - | Poke Balls self-test; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do |
| 18 | Friend Ball | 300 | - | throw | - | Poke Balls self-test; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do; after the catch: a new GBA test (engine `99b9a03d`, after the first candidate) passed |
| 19 | Love Ball | 300 | - | throw | - | Poke Balls self-test; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do |
| 20 | Fast Ball | 300 | - | throw | - | Poke Balls self-test; GBA tests that name it: 1 passed; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do |
| 21 | Heavy Ball | 300 | - | throw | - | Poke Balls self-test; GBA tests that name it: 4 passed; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do |
| 22 | Dream Ball | 0 | - | throw | - | Poke Balls self-test; GBA tests that name it: 0 passed, 1 assumption failed; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do |
| 23 | Safari Ball | 0 | - | throw | - | Poke Balls self-test; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do |
| 24 | Sport Ball | 300 | - | throw | - | Poke Balls self-test; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do |
| 25 | Park Ball | 0 | - | throw | - | Poke Balls self-test; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do |
| 26 | Beast Ball | 0 | - | throw | - | Poke Balls self-test; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do |
| 27 | Cherish Ball | 0 | - | throw | - | Poke Balls self-test; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do |
| 828 | Strange Ball | 0 | - | throw | - | GBA tests that name it: 3 passed; in battle: `item_effect/throw_ball.c` 0 passed, 4 to do; sold in the PC game's coin shop; Poke Balls self-test after the package (engine `9842a793`): x1, the odds the rule gives (its game code the same in the package) |

## Items (597)

| # | Item | Price | From the bag | In battle | Held | Checked by |
| --- | --- | --- | --- | --- | --- | --- |
| 28 | Potion | 300 | Medicine | restore HP | - | healing self-test; GBA tests that name it: 53 passed, 1 known failing; in battle: `item_effect/restore_hp.c` 11 passed |
| 29 | Super Potion | 700 | Medicine | restore HP | - | healing self-test; GBA tests that name it: 2 passed; in battle: `item_effect/restore_hp.c` 11 passed |
| 30 | Hyper Potion | 1200 | Medicine | restore HP | - | healing self-test; GBA tests that name it: 7 passed; in battle: `item_effect/restore_hp.c` 11 passed |
| 31 | Max Potion | 2500 | Medicine | restore HP | - | healing self-test; GBA tests that name it: 1 passed; in battle: `item_effect/restore_hp.c` 11 passed |
| 32 | Full Restore | 3000 | Medicine | heal and cure | - | healing self-test; GBA tests that name it: 6 passed; in battle: `item_effect/heal_and_cure_status.c` 6 passed |
| 33 | Revive | 1500 | Medicine | revive | - | healing self-test; GBA tests that name it: 24 passed; in battle: `item_effect/revive.c` 13 passed |
| 34 | Max Revive | 4000 | Medicine | revive | - | healing self-test; GBA tests that name it: 2 passed; in battle: `item_effect/revive.c` 13 passed |
| 35 | Fresh Water | 200 | Medicine | restore HP | - | healing self-test; GBA tests that name it: 2 passed; in battle: `item_effect/restore_hp.c` 11 passed |
| 36 | Soda Pop | 300 | Medicine | restore HP | - | healing self-test; GBA tests that name it: 2 passed; in battle: `item_effect/restore_hp.c` 11 passed |
| 37 | Lemonade | 350 | Medicine | restore HP | - | healing self-test; GBA tests that name it: 2 passed; in battle: `item_effect/restore_hp.c` 11 passed |
| 38 | Moomoo Milk | 500 | Medicine | restore HP | - | healing self-test; GBA tests that name it: 2 passed; in battle: `item_effect/restore_hp.c` 11 passed |
| 39 | Energy Powder | 500 | Medicine | restore HP | - | healing self-test; GBA tests that name it: 2 passed; in battle: `item_effect/restore_hp.c` 11 passed |
| 40 | Energy Root | 800 | Medicine | restore HP | - | healing self-test; GBA tests that name it: 2 passed; in battle: `item_effect/restore_hp.c` 11 passed |
| 41 | Heal Powder | 450 | Medicine | cure status | - | healing self-test; GBA tests that name it: 4 passed; in battle: `item_effect/cure_status.c` 23 passed |
| 42 | Revival Herb | 2800 | Medicine | revive | - | healing self-test; GBA tests that name it: 1 passed; in battle: `item_effect/revive.c` 13 passed |
| 43 | Antidote | 100 | Medicine | cure status | - | healing self-test; GBA tests that name it: 4 passed; in battle: `item_effect/cure_status.c` 23 passed |
| 44 | Paralyze Heal | 200 | Medicine | cure status | - | healing self-test; GBA tests that name it: 1 passed; in battle: `item_effect/cure_status.c` 23 passed |
| 45 | Burn Heal | 250 | Medicine | cure status | - | healing self-test; GBA tests that name it: 1 passed; in battle: `item_effect/cure_status.c` 23 passed |
| 46 | Ice Heal | 250 | Medicine | cure status | - | healing self-test; GBA tests that name it: 2 passed; in battle: `item_effect/cure_status.c` 23 passed |
| 47 | Awakening | 250 | Medicine | cure status | - | healing self-test; GBA tests that name it: 2 passed; in battle: `item_effect/cure_status.c` 23 passed |
| 48 | Full Heal | 600 | Medicine | cure status | - | healing self-test; GBA tests that name it: 4 passed; in battle: `item_effect/cure_status.c` 23 passed |
| 49 | Ether | 1200 | PPRecovery | restore PP | - | healing self-test; GBA tests that name it: 1 passed; in battle: `item_effect/restore_pp.c` 4 passed, 2 to do |
| 50 | Max Ether | 2000 | PPRecovery | restore PP | - | healing self-test; GBA tests that name it: 1 passed; in battle: `item_effect/restore_pp.c` 4 passed, 2 to do |
| 51 | Elixir | 3000 | PPRecovery | restore PP | - | healing self-test; GBA tests that name it: 1 passed, 1 to do; in battle: `item_effect/restore_pp.c` 4 passed, 2 to do |
| 52 | Max Elixir | 4500 | PPRecovery | restore PP | - | healing self-test; GBA tests that name it: 1 passed; in battle: `item_effect/restore_pp.c` 4 passed, 2 to do |
| 53 | Berry Juice | 100 | Medicine | restore HP | restore hp | healing self-test; GBA tests that name it: 6 passed; held: `hold_effect/restore_hp.c` 7 passed; in battle: `item_effect/restore_hp.c` 11 passed |
| 54 | Sacred Ash | 200 | SacredAsh | - | - | healing self-test |
| 55 | Sweet Heart | 100 | Medicine | restore HP | - | healing self-test; GBA tests that name it: 2 passed; in battle: `item_effect/restore_hp.c` 11 passed |
| 56 | Max Honey | 8000 | Medicine | revive | - | GBA tests that name it: 1 passed; in battle: `item_effect/revive.c` 13 passed |
| 57 | Pewter Crunchies | 250 | Medicine | cure status | - | GBA tests that name it: 3 passed; in battle: `item_effect/cure_status.c` 23 passed |
| 58 | Rage Candy Bar | 300 | Medicine | cure status | - | healing self-test; GBA tests that name it: 3 passed; in battle: `item_effect/cure_status.c` 23 passed |
| 59 | Lava Cookie | 200 | Medicine | cure status | - | healing self-test; GBA tests that name it: 3 passed; in battle: `item_effect/cure_status.c` 23 passed |
| 60 | Old Gateau | 200 | Medicine | cure status | - | healing self-test; GBA tests that name it: 3 passed; in battle: `item_effect/cure_status.c` 23 passed |
| 61 | Casteliacone | 100 | Medicine | cure status | - | healing self-test; GBA tests that name it: 3 passed; in battle: `item_effect/cure_status.c` 23 passed |
| 62 | Lumiose Galette | 200 | Medicine | cure status | - | healing self-test; GBA tests that name it: 3 passed; in battle: `item_effect/cure_status.c` 23 passed |
| 63 | Shalour Sable | 200 | Medicine | cure status | - | healing self-test; GBA tests that name it: 3 passed; in battle: `item_effect/cure_status.c` 23 passed |
| 64 | Big Malasada | 350 | Medicine | cure status | - | GBA tests that name it: 3 passed; in battle: `item_effect/cure_status.c` 23 passed |
| 65 | HP Up | 9800 | Medicine | - | - | bag items self-test |
| 66 | Protein | 9800 | Medicine | - | - | bag items self-test |
| 67 | Iron | 9800 | Medicine | - | - | bag items self-test |
| 68 | Calcium | 9800 | Medicine | - | - | bag items self-test |
| 69 | Zinc | 9800 | Medicine | - | - | bag items self-test |
| 70 | Carbos | 9800 | Medicine | - | - | bag items self-test |
| 71 | PP Up | 9800 | PPUp | - | - | bag items self-test |
| 72 | PP Max | 9800 | PPUp | - | - | bag items self-test |
| 73 | Health Feather | 3000 | Medicine | - | - | bag items self-test |
| 74 | Muscle Feather | 3000 | Medicine | - | - | bag items self-test |
| 75 | Resist Feather | 3000 | Medicine | - | - | bag items self-test |
| 76 | Genius Feather | 3000 | Medicine | - | - | bag items self-test |
| 77 | Clever Feather | 3000 | Medicine | - | - | bag items self-test |
| 78 | Swift Feather | 3000 | Medicine | - | - | bag items self-test |
| 79 | Ability Capsule | 1000 | AbilityCapsule | - | - | Ability items self-test (engine `8db6561e`, after the first candidate) |
| 80 | Ability Patch | 20 | AbilityPatch | - | - | Ability items self-test (engine `8db6561e`, after the first candidate) |
| 81 | Lonely Mint | 20 | Mint | - | - | mints self-test |
| 82 | Adamant Mint | 20 | Mint | - | - | mints self-test |
| 83 | Naughty Mint | 20 | Mint | - | - | mints self-test |
| 84 | Brave Mint | 20 | Mint | - | - | mints self-test |
| 85 | Bold Mint | 20 | Mint | - | - | mints self-test |
| 86 | Impish Mint | 20 | Mint | - | - | mints self-test |
| 87 | Lax Mint | 20 | Mint | - | - | mints self-test |
| 88 | Relaxed Mint | 20 | Mint | - | - | mints self-test |
| 89 | Modest Mint | 20 | Mint | - | - | mints self-test |
| 90 | Mild Mint | 20 | Mint | - | - | mints self-test |
| 91 | Rash Mint | 20 | Mint | - | - | mints self-test |
| 92 | Quiet Mint | 20 | Mint | - | - | mints self-test |
| 93 | Calm Mint | 20 | Mint | - | - | mints self-test |
| 94 | Gentle Mint | 20 | Mint | - | - | mints self-test |
| 95 | Careful Mint | 20 | Mint | - | - | mints self-test |
| 96 | Sassy Mint | 20 | Mint | - | - | mints self-test |
| 97 | Timid Mint | 20 | Mint | - | - | mints self-test |
| 98 | Hasty Mint | 20 | Mint | - | - | mints self-test |
| 99 | Jolly Mint | 20 | Mint | - | - | mints self-test |
| 100 | Naive Mint | 20 | Mint | - | - | mints self-test |
| 101 | Serious Mint | 20 | Mint | - | - | mints self-test |
| 102 | Rare Candy | 4800 | RareCandy | - | - | bag items self-test |
| 103 | Exp. Candy XS | 20 | RareCandy | - | - | Exp. Candy XS: 100 experience, coin-shop self-test `check-rare-goods` (engine `3c9e3088`, after the first candidate) |
| 104 | Exp. Candy S | 240 | RareCandy | - | - | Exp. Candy S: 800 experience, coin-shop self-test `check-rare-goods` (engine `3c9e3088`, after the first candidate) |
| 105 | Exp. Candy M | 1000 | RareCandy | - | - | Exp. Candy M: 3,000 experience, coin-shop self-test `check-rare-goods` (engine `3c9e3088`, after the first candidate) |
| 106 | Exp. Candy L | 3000 | RareCandy | - | - | Exp. Candy L: 10,000 experience, coin-shop self-test `check-rare-goods` (engine `3c9e3088`, after the first candidate) |
| 107 | Exp. Candy XL | 10000 | RareCandy | - | - | Exp. Candy XL: 30,000 experience, none at level 100, coin-shop self-test `check-rare-goods` (engine `3c9e3088`, after the first candidate) |
| 108 | Dynamax Candy | 0 | DynamaxCandy | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 109 | Blue Flute | 100 | Medicine | cure status | - | healing self-test; in battle: `item_effect/cure_status.c` 23 passed |
| 110 | Yellow Flute | 300 | - | cure status | - | in battle: `item_effect/cure_status.c` 23 passed |
| 111 | Red Flute | 200 | - | cure status | - | in battle: `item_effect/cure_status.c` 23 passed |
| 112 | Black Flute | 400 | BlackWhiteFlute | - | - | wild item audit (gameplay report section 5) |
| 113 | White Flute | 500 | BlackWhiteFlute | - | - | wild item audit (gameplay report section 5) |
| 114 | Repel | 350 | Repel | - | - | wild item audit (gameplay report section 5) |
| 115 | Super Repel | 500 | Repel | - | - | wild item audit (gameplay report section 5) |
| 116 | Max Repel | 700 | Repel | - | - | wild item audit (gameplay report section 5) |
| 117 | Lure | 400 | Lure | - | - | wild item audit (gameplay report section 5) |
| 118 | Super Lure | 700 | Lure | - | - | wild item audit (gameplay report section 5) |
| 119 | Max Lure | 900 | Lure | - | - | wild item audit (gameplay report section 5) |
| 120 | Escape Rope | 550 | EscapeRope | - | - | used in Rusturf Tunnel in the real game: back on Route 116 by the tunnel, the rope used up (engine `4f841321`, after the first candidate) |
| 121 | X Attack | 500 | - | raise a stat | - | GBA tests that name it: 4 passed; in battle: `item_effect/increase_stat.c` 14 passed |
| 122 | X Defense | 550 | - | raise a stat | - | GBA tests that name it: 4 passed; in battle: `item_effect/increase_stat.c` 14 passed |
| 123 | X Sp. Atk | 350 | - | raise a stat | - | GBA tests that name it: 3 passed; in battle: `item_effect/increase_stat.c` 14 passed |
| 124 | X Sp. Def | 350 | - | raise a stat | - | GBA tests that name it: 3 passed; in battle: `item_effect/increase_stat.c` 14 passed |
| 125 | X Speed | 350 | - | raise a stat | - | GBA tests that name it: 3 passed; in battle: `item_effect/increase_stat.c` 14 passed |
| 126 | X Accuracy | 950 | - | raise a stat | - | GBA tests that name it: 9 passed; in battle: `item_effect/increase_stat.c` 14 passed |
| 127 | Dire Hit | 650 | - | Focus Energy | - | GBA tests that name it: 1 passed; in battle: `item_effect/dire_hit.c` 1 passed |
| 128 | Guard Spec. | 700 | - | Mist | - | GBA tests that name it: 1 passed; in battle: `item_effect/set_mist.c` 1 passed |
| 129 | Poké Doll | 1000 | - | escape | - | in battle: `item_effect/escape.c` 3 passed |
| 130 | Fluffy Tail | 1000 | - | escape | - | in battle: `item_effect/escape.c` 3 passed |
| 131 | Poké Toy | 1000 | - | escape | - | GBA tests that name it: 3 passed; in battle: `item_effect/escape.c` 3 passed |
| 132 | Max Mushrooms | 8000 | - | raise all stats | - | GBA tests that name it: 7 passed; in battle: `item_effect/increase_stat.c` 14 passed |
| 133 | Bottle Cap | 5000 | HyperTraining | - | - | Hyper Training in the real game, `train_check.py` 8 of 8 (one stat; refused at 31; saved and loaded; engine `812d7bf3`, after the first candidate) |
| 134 | Gold Bottle Cap | 10000 | HyperTraining | - | - | Hyper Training in the real game, `train_check.py` 8 of 8 (every stat; engine `812d7bf3`, after the first candidate) |
| 135 | Nugget | 10000 | - | - | - | GBA tests that name it: 2 passed |
| 136 | Big Nugget | 20000 | - | - | - | GBA tests that name it: 1 passed |
| 137 | Tiny Mushroom | 500 | - | - | - | GBA tests that name it: 1 passed |
| 138 | Big Mushroom | 5000 | - | - | - | GBA tests that name it: 1 passed |
| 139 | Balm Mushroom | 12500 | - | - | - | no use from the bag, in battle or held |
| 140 | Pearl | 1400 | - | - | - | GBA tests that name it: 1 passed |
| 141 | Big Pearl | 7500 | - | - | - | GBA tests that name it: 1 passed |
| 142 | Pearl String | 15000 | - | - | - | no use from the bag, in battle or held |
| 143 | Stardust | 2000 | - | - | - | no use from the bag, in battle or held |
| 144 | Star Piece | 9800 | - | - | - | no use from the bag, in battle or held |
| 145 | Comet Shard | 30000 | - | - | - | no use from the bag, in battle or held |
| 146 | Shoal Salt | 20 | - | - | - | no use from the bag, in battle or held |
| 147 | Shoal Shell | 20 | - | - | - | no use from the bag, in battle or held |
| 148 | Red Shard | 200 | - | - | - | no use from the bag, in battle or held |
| 149 | Blue Shard | 200 | - | - | - | no use from the bag, in battle or held |
| 150 | Yellow Shard | 200 | - | - | - | no use from the bag, in battle or held |
| 151 | Green Shard | 200 | - | - | - | no use from the bag, in battle or held |
| 152 | Heart Scale | 100 | - | - | - | no use from the bag, in battle or held |
| 153 | Honey | 100 | Honey | - | - | used in Route 101's grass in the real game: a wild battle, as Sweet Scent (engine `4f841321`, after the first candidate) |
| 154 | Rare Bone | 10000 | - | - | - | no use from the bag, in battle or held |
| 155 | Odd Keystone | 2100 | - | - | - | no use from the bag, in battle or held |
| 156 | Pretty Feather | 200 | - | - | - | bag items self-test |
| 157 | Relic Copper | 0 | - | - | - | no use from the bag, in battle or held |
| 158 | Relic Silver | 0 | - | - | - | no use from the bag, in battle or held |
| 159 | Relic Gold | 60000 | - | - | - | no use from the bag, in battle or held |
| 160 | Relic Vase | 0 | - | - | - | no use from the bag, in battle or held |
| 161 | Relic Band | 0 | - | - | - | no use from the bag, in battle or held |
| 162 | Relic Statue | 0 | - | - | - | no use from the bag, in battle or held |
| 163 | Relic Crown | 0 | - | - | - | no use from the bag, in battle or held |
| 164 | Strange Souvenir | 10 | - | - | - | no use from the bag, in battle or held |
| 165 | Helix Fossil | 1000 | - | - | - | no use from the bag, in battle or held |
| 166 | Dome Fossil | 1000 | - | - | - | no use from the bag, in battle or held |
| 167 | Old Amber | 1000 | - | - | - | no use from the bag, in battle or held |
| 168 | Root Fossil | 1000 | - | - | - | no use from the bag, in battle or held |
| 169 | Claw Fossil | 1000 | - | - | - | no use from the bag, in battle or held |
| 170 | Armor Fossil | 1000 | - | - | - | no use from the bag, in battle or held |
| 171 | Skull Fossil | 1000 | - | - | - | no use from the bag, in battle or held |
| 172 | Cover Fossil | 1000 | - | - | - | no use from the bag, in battle or held |
| 173 | Plume Fossil | 1000 | - | - | - | no use from the bag, in battle or held |
| 174 | Jaw Fossil | 1000 | - | - | - | no use from the bag, in battle or held |
| 175 | Sail Fossil | 1000 | - | - | - | no use from the bag, in battle or held |
| 176 | Fossilized Bird | 5000 | - | - | - | no use from the bag, in battle or held |
| 177 | Fossilized Fish | 5000 | - | - | - | no use from the bag, in battle or held |
| 178 | Fossilized Drake | 5000 | - | - | - | no use from the bag, in battle or held |
| 179 | Fossilized Dino | 5000 | - | - | - | no use from the bag, in battle or held |
| 180 | Growth Mulch | 200 | - | - | - | no use from the bag, in battle or held |
| 181 | Damp Mulch | 200 | - | - | - | no use from the bag, in battle or held |
| 182 | Stable Mulch | 200 | - | - | - | no use from the bag, in battle or held |
| 183 | Gooey Mulch | 200 | - | - | - | no use from the bag, in battle or held |
| 184 | Rich Mulch | 200 | - | - | - | no use from the bag, in battle or held |
| 185 | Surprise Mulch | 200 | - | - | - | no use from the bag, in battle or held |
| 186 | Boost Mulch | 200 | - | - | - | no use from the bag, in battle or held |
| 187 | Amaze Mulch | 200 | - | - | - | no use from the bag, in battle or held |
| 188 | Red Apricorn | 20 | - | - | - | no use from the bag, in battle or held |
| 189 | Blue Apricorn | 20 | - | - | - | no use from the bag, in battle or held |
| 190 | Yellow Apricorn | 20 | - | - | - | no use from the bag, in battle or held |
| 191 | Green Apricorn | 20 | - | - | - | no use from the bag, in battle or held |
| 192 | Pink Apricorn | 20 | - | - | - | no use from the bag, in battle or held |
| 193 | White Apricorn | 20 | - | - | - | no use from the bag, in battle or held |
| 194 | Black Apricorn | 20 | - | - | - | no use from the bag, in battle or held |
| 195 | Wishing Piece | 20 | - | - | - | no use from the bag, in battle or held |
| 196 | Galarica Twig | 20 | - | - | - | no use from the bag, in battle or held |
| 197 | Armorite Ore | 20 | - | - | - | no use from the bag, in battle or held |
| 198 | Dynite Ore | 20 | - | - | - | no use from the bag, in battle or held |
| 199 | Orange Mail | 50 | Mail | - | - | given to a Pokemon and taken back into the PC, the mail self-test `check-mail` (engine `6dcc0760`, after the first candidate); CHECK from the Bag in the real game, which asserted (MS-158, fixed on engine `812d7bf3`) |
| 200 | Harbor Mail | 50 | Mail | - | - | given to a Pokemon and taken back into the PC, the mail self-test `check-mail` (engine `6dcc0760`, after the first candidate) |
| 201 | Glitter Mail | 50 | Mail | - | - | given to a Pokemon and taken back into the PC, the mail self-test `check-mail` (engine `6dcc0760`, after the first candidate) |
| 202 | Mech Mail | 50 | Mail | - | - | given to a Pokemon and taken back into the PC, the mail self-test `check-mail` (engine `6dcc0760`, after the first candidate) |
| 203 | Wood Mail | 50 | Mail | - | - | given to a Pokemon and taken back into the PC, the mail self-test `check-mail` (engine `6dcc0760`, after the first candidate) |
| 204 | Wave Mail | 50 | Mail | - | - | given to a Pokemon and taken back into the PC, the mail self-test `check-mail` (engine `6dcc0760`, after the first candidate) |
| 205 | Bead Mail | 50 | Mail | - | - | given to a Pokemon and taken back into the PC, the mail self-test `check-mail` (engine `6dcc0760`, after the first candidate) |
| 206 | Shadow Mail | 50 | Mail | - | - | given to a Pokemon and taken back into the PC, the mail self-test `check-mail` (engine `6dcc0760`, after the first candidate) |
| 207 | Tropic Mail | 50 | Mail | - | - | given to a Pokemon and taken back into the PC, the mail self-test `check-mail` (engine `6dcc0760`, after the first candidate) |
| 208 | Dream Mail | 50 | Mail | - | - | given to a Pokemon and taken back into the PC, the mail self-test `check-mail` (engine `6dcc0760`, after the first candidate) |
| 209 | Fab Mail | 50 | Mail | - | - | given to a Pokemon and taken back into the PC, the mail self-test `check-mail` (engine `6dcc0760`, after the first candidate) |
| 210 | Retro Mail | 50 | Mail | - | - | given to a Pokemon and taken back into the PC, the mail self-test `check-mail` (engine `6dcc0760`, after the first candidate) (not obtainable in this game) |
| 211 | Fire Stone | 2100 | EvolutionStone | - | - | bag items self-test |
| 212 | Water Stone | 2100 | EvolutionStone | - | - | bag items self-test |
| 213 | Thunder Stone | 2100 | EvolutionStone | - | - | bag items self-test |
| 214 | Leaf Stone | 2100 | EvolutionStone | - | - | bag items self-test |
| 215 | Ice Stone | 2100 | EvolutionStone | - | - | bag items self-test |
| 216 | Sun Stone | 2100 | EvolutionStone | - | - | bag items self-test |
| 217 | Moon Stone | 2100 | EvolutionStone | - | - | bag items self-test |
| 218 | Shiny Stone | 2100 | EvolutionStone | - | - | bag items self-test |
| 219 | Dusk Stone | 2100 | EvolutionStone | - | - | bag items self-test |
| 220 | Dawn Stone | 2100 | EvolutionStone | - | - | bag items self-test |
| 221 | Sweet Apple | 2200 | EvolutionStone | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 222 | Tart Apple | 2200 | EvolutionStone | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 223 | Cracked Pot | 1600 | EvolutionStone | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 224 | Chipped Pot | 38000 | EvolutionStone | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 225 | Galarica Cuff | 6000 | EvolutionStone | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 226 | Galarica Wreath | 6000 | EvolutionStone | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 227 | Dragon Scale | 2100 | - | - | - | held in a trade: Seadra -> Kingdra, not without it or with another's (the trade evolutions' self-test `check-evo-items`, in the package) |
| 228 | Upgrade | 2100 | - | - | - | held in a trade: Porygon -> Porygon2, not without it or with another's (the trade evolutions' self-test `check-evo-items`, in the package) |
| 229 | Protector | 2100 | - | - | - | held in a trade: Rhydon -> Rhyperior, not without it or with another's (the trade evolutions' self-test `check-evo-items`, in the package) |
| 230 | Electirizer | 2100 | - | - | - | held in a trade: Electabuzz -> Electivire, not without it or with another's (the trade evolutions' self-test `check-evo-items`, in the package) |
| 231 | Magmarizer | 2100 | - | - | - | held in a trade: Magmar -> Magmortar, not without it or with another's (the trade evolutions' self-test `check-evo-items`, in the package) |
| 232 | Dubious Disc | 2100 | - | - | - | held in a trade: Porygon2 -> Porygon-Z, not without it or with another's (the trade evolutions' self-test `check-evo-items`, in the package) |
| 233 | Reaper Cloth | 2100 | - | - | - | held in a trade: Dusclops -> Dusknoir, not without it or with another's (the trade evolutions' self-test `check-evo-items`, in the package) |
| 234 | Prism Scale | 500 | - | - | - | held in a trade: Feebas -> Milotic, not without it or with another's (the trade evolutions' self-test `check-evo-items`, in the package) |
| 235 | Whipped Dream | 2100 | - | - | - | held in a trade: Swirlix -> Slurpuff, not without it or with another's (the trade evolutions' self-test `check-evo-items`, in the package) |
| 236 | Sachet | 2100 | - | - | - | held in a trade: Spritzee -> Aromatisse, not without it or with another's (the trade evolutions' self-test `check-evo-items`, in the package) |
| 237 | Oval Stone | 2100 | - | - | - | Happiny holding it evolves on a level up by day, not at night (evolution self-test `check-evo-items`, engine `059e906e`, after the first candidate) |
| 238 | Strawberry Sweet | 500 | - | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 239 | Love Sweet | 500 | - | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 240 | Berry Sweet | 500 | - | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 241 | Clover Sweet | 500 | - | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 242 | Flower Sweet | 500 | - | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 243 | Star Sweet | 500 | - | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 244 | Ribbon Sweet | 500 | - | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 245 | Everstone | 200 | - | - | prevent evolve | bag items self-test; GBA tests that name it: 15 passed; held: `hold_effect/prevent_evolve.c` 0 passed, 1 to do |
| 246 | Red Nectar | 300 | FormChange_ConsumedOnUse | - | - | Oricorio to Baile, coin-shop self-test `check-rare-goods` (engine `3c9e3088`, after the first candidate) |
| 247 | Yellow Nectar | 300 | FormChange_ConsumedOnUse | - | - | Oricorio to Pom-Pom, coin-shop self-test `check-rare-goods` (engine `3c9e3088`, after the first candidate) |
| 248 | Pink Nectar | 300 | FormChange_ConsumedOnUse | - | - | Oricorio to Pa'u, coin-shop self-test `check-rare-goods` (engine `3c9e3088`, after the first candidate) |
| 249 | Purple Nectar | 300 | FormChange_ConsumedOnUse | - | - | Oricorio to Sensu, coin-shop self-test `check-rare-goods` (engine `3c9e3088`, after the first candidate) |
| 250 | Flame Plate | 1000 | - | - | plate | GBA tests that name it: 1 passed; held: `hold_effect/plate.c` 0 passed, 1 to do |
| 251 | Splash Plate | 1000 | - | - | plate | GBA tests that name it: 2 passed; held: `hold_effect/plate.c` 0 passed, 1 to do |
| 252 | Zap Plate | 1000 | - | - | plate | GBA tests that name it: 7 passed; held: `hold_effect/plate.c` 0 passed, 1 to do |
| 253 | Meadow Plate | 1000 | - | - | plate | GBA tests that name it: 1 passed; held: `hold_effect/plate.c` 0 passed, 1 to do |
| 254 | Icicle Plate | 1000 | - | - | plate | GBA tests that name it: 1 passed; held: `hold_effect/plate.c` 0 passed, 1 to do |
| 255 | Fist Plate | 1000 | - | - | plate | GBA tests that name it: 1 passed; held: `hold_effect/plate.c` 0 passed, 1 to do |
| 256 | Toxic Plate | 1000 | - | - | plate | held: its type's moves x1.2 (`item_audit_untested.c`, in the package); its data and another type unboosted (engine `47e47359`, after the first candidate) |
| 257 | Earth Plate | 1000 | - | - | plate | held: its type's moves x1.2 (`item_audit_untested.c`, in the package); its data and another type unboosted (engine `47e47359`, after the first candidate) |
| 258 | Sky Plate | 1000 | - | - | plate | GBA tests that name it: 5 passed; held: `hold_effect/plate.c` 0 passed, 1 to do |
| 259 | Mind Plate | 1000 | - | - | plate | held: its type's moves x1.2 (`item_audit_untested.c`, in the package); its data and another type unboosted (engine `47e47359`, after the first candidate) |
| 260 | Insect Plate | 1000 | - | - | plate | held: its type's moves x1.2 (`item_audit_untested.c`, in the package); its data and another type unboosted (engine `47e47359`, after the first candidate) |
| 261 | Stone Plate | 1000 | - | - | plate | held: its type's moves x1.2 (`item_audit_untested.c`, in the package); its data and another type unboosted (engine `47e47359`, after the first candidate) |
| 262 | Spooky Plate | 1000 | - | - | plate | held: its type's moves x1.2 (`item_audit_untested.c`, in the package); its data and another type unboosted (engine `47e47359`, after the first candidate) |
| 263 | Draco Plate | 1000 | - | - | plate | held: its type's moves x1.2 (`item_audit_untested.c`, in the package); its data and another type unboosted (engine `47e47359`, after the first candidate) |
| 264 | Dread Plate | 1000 | - | - | plate | held: its type's moves x1.2 (`item_audit_untested.c`, in the package); its data and another type unboosted (engine `47e47359`, after the first candidate) |
| 265 | Iron Plate | 1000 | - | - | plate | held: its type's moves x1.2 (`item_audit_untested.c`, in the package); its data and another type unboosted (engine `47e47359`, after the first candidate) |
| 266 | Pixie Plate | 1000 | - | - | plate | GBA tests that name it: 1 passed; held: `hold_effect/plate.c` 0 passed, 1 to do |
| 267 | Douse Drive | 1000 | - | - | drive | GBA tests that name it: 2 passed; held: `hold_effect/drive.c` 0 passed, 1 to do |
| 268 | Shock Drive | 1000 | - | - | drive | GBA tests that name it: 7 passed; held: `hold_effect/drive.c` 0 passed, 1 to do |
| 269 | Burn Drive | 1000 | - | - | drive | GBA tests that name it: 3 passed; held: `hold_effect/drive.c` 0 passed, 1 to do |
| 270 | Chill Drive | 1000 | - | - | drive | GBA tests that name it: 1 passed; held: `hold_effect/drive.c` 0 passed, 1 to do |
| 271 | Fire Memory | 1000 | - | - | memory | GBA tests that name it: 3 passed; held: `hold_effect/memory.c` 0 passed, 1 to do |
| 272 | Water Memory | 1000 | - | - | memory | GBA tests that name it: 2 passed; held: `hold_effect/memory.c` 0 passed, 1 to do |
| 273 | Electric Memory | 1000 | - | - | memory | GBA tests that name it: 6 passed; held: `hold_effect/memory.c` 0 passed, 1 to do |
| 274 | Grass Memory | 1000 | - | - | memory | its type for Multi-Attack and RKS System: the data checked (`test/item_audit_data.c`, engine `47e47359`, after the first candidate); Multi-Attack's own test passes; not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 275 | Ice Memory | 1000 | - | - | memory | GBA tests that name it: 1 passed; held: `hold_effect/memory.c` 0 passed, 1 to do |
| 276 | Fighting Memory | 1000 | - | - | memory | GBA tests that name it: 1 passed; held: `hold_effect/memory.c` 0 passed, 1 to do |
| 277 | Poison Memory | 1000 | - | - | memory | its type for Multi-Attack and RKS System: the data checked (`test/item_audit_data.c`, engine `47e47359`, after the first candidate); Multi-Attack's own test passes; not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 278 | Ground Memory | 1000 | - | - | memory | its type for Multi-Attack and RKS System: the data checked (`test/item_audit_data.c`, engine `47e47359`, after the first candidate); Multi-Attack's own test passes; not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 279 | Flying Memory | 1000 | - | - | memory | its type for Multi-Attack and RKS System: the data checked (`test/item_audit_data.c`, engine `47e47359`, after the first candidate); Multi-Attack's own test passes; not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 280 | Psychic Memory | 1000 | - | - | memory | its type for Multi-Attack and RKS System: the data checked (`test/item_audit_data.c`, engine `47e47359`, after the first candidate); Multi-Attack's own test passes; not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 281 | Bug Memory | 1000 | - | - | memory | its type for Multi-Attack and RKS System: the data checked (`test/item_audit_data.c`, engine `47e47359`, after the first candidate); Multi-Attack's own test passes; not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 282 | Rock Memory | 1000 | - | - | memory | its type for Multi-Attack and RKS System: the data checked (`test/item_audit_data.c`, engine `47e47359`, after the first candidate); Multi-Attack's own test passes; not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 283 | Ghost Memory | 1000 | - | - | memory | its type for Multi-Attack and RKS System: the data checked (`test/item_audit_data.c`, engine `47e47359`, after the first candidate); Multi-Attack's own test passes; not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 284 | Dragon Memory | 1000 | - | - | memory | its type for Multi-Attack and RKS System: the data checked (`test/item_audit_data.c`, engine `47e47359`, after the first candidate); Multi-Attack's own test passes; not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 285 | Dark Memory | 1000 | - | - | memory | its type for Multi-Attack and RKS System: the data checked (`test/item_audit_data.c`, engine `47e47359`, after the first candidate); Multi-Attack's own test passes; not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 286 | Steel Memory | 1000 | - | - | memory | its type for Multi-Attack and RKS System: the data checked (`test/item_audit_data.c`, engine `47e47359`, after the first candidate); Multi-Attack's own test passes; not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 287 | Fairy Memory | 1000 | - | - | memory | its type for Multi-Attack and RKS System: the data checked (`test/item_audit_data.c`, engine `47e47359`, after the first candidate); Multi-Attack's own test passes; not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 288 | Rusted Sword | 0 | - | - | - | GBA tests that name it: 5 passed |
| 289 | Rusted Shield | 0 | - | - | - | GBA tests that name it: 7 passed |
| 290 | Red Orb | 0 | - | - | primal orb | GBA tests that name it: 41 passed, 1 failed (expected); Primal Reversion: `form_change/primal_reversion.c` 15 passed |
| 291 | Blue Orb | 0 | - | - | primal orb | GBA tests that name it: 28 passed, 1 failed (expected); Primal Reversion: `form_change/primal_reversion.c` 15 passed |
| 292 | Venusaurite | 60000 | - | - | mega stone | GBA tests that name it: 20 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 293 | Charizardite X | 60000 | - | - | mega stone | GBA tests that name it: 3 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 294 | Charizardite Y | 60000 | - | - | mega stone | GBA tests that name it: 3 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 295 | Blastoisinite | 60000 | - | - | mega stone | GBA tests that name it: 3 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 296 | Beedrillite | 60000 | - | - | mega stone | GBA tests that name it: 1 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 297 | Pidgeotite | 60000 | - | - | mega stone | GBA tests that name it: 1 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 298 | Alakazite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 299 | Slowbronite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 300 | Gengarite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 301 | Kangaskhanite | 60000 | - | - | mega stone | GBA tests that name it: 22 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 302 | Pinsirite | 60000 | - | - | mega stone | GBA tests that name it: 4 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 303 | Gyaradosite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 304 | Aerodactylite | 60000 | - | - | mega stone | GBA tests that name it: 2 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 305 | Mewtwonite X | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 306 | Mewtwonite Y | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 307 | Ampharosite | 60000 | - | - | mega stone | GBA tests that name it: 2 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 308 | Steelixite | 60000 | - | - | mega stone | GBA tests that name it: 1 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 309 | Scizorite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 310 | Heracronite | 60000 | - | - | mega stone | GBA tests that name it: 1 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 311 | Houndoominite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 312 | Tyranitarite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 313 | Sceptilite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 314 | Blazikenite | 60000 | - | - | mega stone | GBA tests that name it: 3 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 315 | Swampertite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 316 | Gardevoirite | 60000 | - | - | mega stone | GBA tests that name it: 13 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 317 | Sablenite | 60000 | - | - | mega stone | GBA tests that name it: 1 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 318 | Mawilite | 60000 | - | - | mega stone | GBA tests that name it: 1 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 319 | Aggronite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 320 | Medichamite | 60000 | - | - | mega stone | GBA tests that name it: 2 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 321 | Manectite | 60000 | - | - | mega stone | GBA tests that name it: 6 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 322 | Sharpedonite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 323 | Cameruptite | 60000 | - | - | mega stone | GBA tests that name it: 1 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 324 | Altarianite | 60000 | - | - | mega stone | GBA tests that name it: 1 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 325 | Banettite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 326 | Absolite | 60000 | - | - | mega stone | GBA tests that name it: 4 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 327 | Glalitite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 328 | Salamencite | 60000 | - | - | mega stone | GBA tests that name it: 9 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 329 | Metagrossite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 330 | Latiasite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 331 | Latiosite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 332 | Lopunnite | 60000 | - | - | mega stone | GBA tests that name it: 6 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 333 | Garchompite | 60000 | - | - | mega stone | GBA tests that name it: 1 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 334 | Lucarionite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 335 | Abomasite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 336 | Galladite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 337 | Audinite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 338 | Diancite | 60000 | - | - | mega stone | GBA tests that name it: 1 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 339 | Normal Gem | 200 | - | - | gems | GBA tests that name it: 10 passed; held: `hold_effect/gems.c` 5 passed |
| 340 | Fire Gem | 200 | - | - | gems | held: `hold_effect/gems.c` 5 passed |
| 341 | Water Gem | 200 | - | - | gems | GBA tests that name it: 1 passed; held: `hold_effect/gems.c` 5 passed |
| 342 | Electric Gem | 200 | - | - | gems | held: `hold_effect/gems.c` 5 passed |
| 343 | Grass Gem | 200 | - | - | gems | held: `hold_effect/gems.c` 5 passed |
| 344 | Ice Gem | 200 | - | - | gems | held: `hold_effect/gems.c` 5 passed |
| 345 | Fighting Gem | 200 | - | - | gems | GBA tests that name it: 1 passed; held: `hold_effect/gems.c` 5 passed |
| 346 | Poison Gem | 200 | - | - | gems | held: `hold_effect/gems.c` 5 passed |
| 347 | Ground Gem | 200 | - | - | gems | held: `hold_effect/gems.c` 5 passed |
| 348 | Flying Gem | 200 | - | - | gems | GBA tests that name it: 1 passed; held: `hold_effect/gems.c` 5 passed |
| 349 | Psychic Gem | 200 | - | - | gems | GBA tests that name it: 1 passed; held: `hold_effect/gems.c` 5 passed |
| 350 | Bug Gem | 200 | - | - | gems | held: `hold_effect/gems.c` 5 passed |
| 351 | Rock Gem | 200 | - | - | gems | held: `hold_effect/gems.c` 5 passed |
| 352 | Ghost Gem | 200 | - | - | gems | GBA tests that name it: 2 passed; held: `hold_effect/gems.c` 5 passed |
| 353 | Dragon Gem | 200 | - | - | gems | held: `hold_effect/gems.c` 5 passed |
| 354 | Dark Gem | 200 | - | - | gems | held: `hold_effect/gems.c` 5 passed |
| 355 | Steel Gem | 200 | - | - | gems | held: `hold_effect/gems.c` 5 passed |
| 356 | Fairy Gem | 200 | - | - | gems | held: `hold_effect/gems.c` 5 passed |
| 357 | Normalium Z | 0 | - | - | z crystal | GBA tests that name it: 56 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 358 | Firium Z | 0 | - | - | z crystal | GBA tests that name it: 2 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 359 | Waterium Z | 0 | - | - | z crystal | GBA tests that name it: 2 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 360 | Electrium Z | 0 | - | - | z crystal | GBA tests that name it: 2 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 361 | Grassium Z | 0 | - | - | z crystal | GBA tests that name it: 1 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 362 | Icium Z | 0 | - | - | z crystal | GBA tests that name it: 0 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 363 | Fightinium Z | 0 | - | - | z crystal | GBA tests that name it: 3 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 364 | Poisonium Z | 0 | - | - | z crystal | GBA tests that name it: 1 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 365 | Groundium Z | 0 | - | - | z crystal | GBA tests that name it: 0 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 366 | Flyinium Z | 0 | - | - | z crystal | GBA tests that name it: 4 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 367 | Psychium Z | 0 | - | - | z crystal | GBA tests that name it: 0 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 368 | Buginium Z | 0 | - | - | z crystal | GBA tests that name it: 0 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 369 | Rockium Z | 0 | - | - | z crystal | GBA tests that name it: 0 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 370 | Ghostium Z | 0 | - | - | z crystal | GBA tests that name it: 4 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 371 | Dragonium Z | 0 | - | - | z crystal | GBA tests that name it: 1 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 372 | Darkinium Z | 0 | - | - | z crystal | GBA tests that name it: 1 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 373 | Steelium Z | 0 | - | - | z crystal | GBA tests that name it: 0 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 374 | Fairium Z | 0 | - | - | z crystal | GBA tests that name it: 1 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 375 | Pikanium Z | 0 | - | - | z crystal | GBA tests that name it: 0 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 376 | Eevium Z | 0 | - | - | z crystal | GBA tests that name it: 3 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 377 | Snorlium Z | 0 | - | - | z crystal | GBA tests that name it: 0 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 378 | Mewnium Z | 0 | - | - | z crystal | GBA tests that name it: 2 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 379 | Decidium Z | 0 | - | - | z crystal | GBA tests that name it: 0 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 380 | Incinium Z | 0 | - | - | z crystal | GBA tests that name it: 0 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 381 | Primarium Z | 0 | - | - | z crystal | GBA tests that name it: 0 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 382 | Lycanium Z | 0 | - | - | z crystal | GBA tests that name it: 2 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 383 | Mimikium Z | 0 | - | - | z crystal | GBA tests that name it: 0 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 384 | Kommonium Z | 0 | - | - | z crystal | GBA tests that name it: 1 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 385 | Tapunium Z | 0 | - | - | z crystal | GBA tests that name it: 2 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 386 | Solganium Z | 0 | - | - | z crystal | GBA tests that name it: 1 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 387 | Lunalium Z | 0 | - | - | z crystal | GBA tests that name it: 0 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 388 | Marshadium Z | 0 | - | - | z crystal | GBA tests that name it: 0 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 389 | Aloraichium Z | 0 | - | - | z crystal | GBA tests that name it: 1 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 390 | Pikashunium Z | 0 | - | - | z crystal | GBA tests that name it: 2 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 391 | Ultranecrozium Z | 0 | - | - | z crystal | GBA tests that name it: 13 passed; held: `gimmick/zmove.c` 51 passed, 3 to do |
| 392 | Light Ball | 100 | - | - | light ball | GBA tests that name it: 8 passed; held: `hold_effect/light_ball.c` 2 passed |
| 393 | Leek | 200 | - | - | leek | GBA tests that name it: 1 passed; held: `hold_effect/leek.c` 1 passed |
| 394 | Thick Club | 500 | - | - | thick club | GBA tests that name it: 2 passed; held: `hold_effect/thick_club.c` 2 passed |
| 395 | Lucky Punch | 10 | - | - | lucky punch | GBA tests that name it: 1 passed; held: `hold_effect/lucky_punch.c` 1 passed |
| 396 | Metal Powder | 10 | - | - | metal powder | GBA tests that name it: 3 passed; held: `hold_effect/metal_powder.c` 3 passed |
| 397 | Quick Powder | 10 | - | - | quick powder | GBA tests that name it: 3 passed; held: `hold_effect/quick_powder.c` 3 passed |
| 398 | Deep Sea Scale | 200 | - | - | deep sea scale | GBA tests that name it: 2 passed; held: `hold_effect/deep_sea_scale.c` 2 passed; its evolution use: Clamperl -> Gorebyss in a trade (`check-evo-items`, in the package) |
| 399 | Deep Sea Tooth | 200 | - | - | deep sea tooth | GBA tests that name it: 2 passed; held: `hold_effect/deep_sea_tooth.c` 2 passed; its evolution use: Clamperl -> Huntail in a trade (`check-evo-items`, in the package) |
| 400 | Soul Dew | 200 | - | - | soul dew | GBA tests that name it: 1 passed; held: `hold_effect/soul_dew.c` 0 passed, 1 to do |
| 401 | Adamant Orb | 10000 | - | - | adamant orb | GBA tests that name it: 1 passed; held: `hold_effect/adamant_orb.c` 1 passed |
| 402 | Lustrous Orb | 10000 | - | - | lustrous orb | GBA tests that name it: 1 passed; held: `hold_effect/lustrous_orb.c` 1 passed |
| 403 | Griseous Orb | 10000 | - | - | griseous orb | GBA tests that name it: 1 passed; held: `hold_effect/griseous_orb.c` 1 passed |
| 404 | Sea Incense | 9600 | - | - | type power | held: `hold_effect/type_power.c` 2 passed |
| 405 | Lax Incense | 9600 | - | - | evasion up | GBA tests that name it: 1 passed; held: `hold_effect/evasion_up.c` 0 passed, 1 to do |
| 406 | Odd Incense | 9600 | - | - | type power | held: `hold_effect/type_power.c` 2 passed |
| 407 | Rock Incense | 9600 | - | - | type power | held: `hold_effect/type_power.c` 2 passed |
| 408 | Full Incense | 9600 | - | - | lagging tail | held: `hold_effect/lagging_tail.c` 1 passed |
| 409 | Wave Incense | 9600 | - | - | type power | held: `hold_effect/type_power.c` 2 passed |
| 410 | Rose Incense | 9600 | - | - | type power | held: `hold_effect/type_power.c` 2 passed |
| 411 | Luck Incense | 9600 | - | - | double prize | GBA tests that name it: 1 passed; held: `hold_effect/double_prize.c` 0 passed, 1 to do |
| 412 | Pure Incense | 9600 | - | - | repel | wild item audit (gameplay report section 5); held: `hold_effect/repel.c` 0 passed, 1 to do |
| 413 | Red Scarf | 100 | - | - | - | no use from the bag, in battle or held |
| 414 | Blue Scarf | 100 | - | - | - | no use from the bag, in battle or held |
| 415 | Pink Scarf | 100 | - | - | - | no use from the bag, in battle or held |
| 416 | Green Scarf | 100 | - | - | - | no use from the bag, in battle or held |
| 417 | Yellow Scarf | 100 | - | - | - | no use from the bag, in battle or held |
| 418 | Macho Brace | 3000 | - | - | macho brace | held items self-test (effort values); GBA tests that name it: 2 passed; held: `hold_effect/macho_brace.c` 0 passed, 1 to do |
| 419 | Power Weight | 3000 | - | - | power item | held items self-test (effort values); GBA tests that name it: 5 passed; held: `hold_effect/power_item.c` 0 passed, 1 to do |
| 420 | Power Bracer | 3000 | - | - | power item | held items self-test (effort values); GBA tests that name it: 1 passed; held: `hold_effect/power_item.c` 0 passed, 1 to do |
| 421 | Power Belt | 3000 | - | - | power item | held items self-test (effort values); GBA tests that name it: 1 passed; held: `hold_effect/power_item.c` 0 passed, 1 to do |
| 422 | Power Lens | 3000 | - | - | power item | held items self-test (effort values); GBA tests that name it: 1 passed; held: `hold_effect/power_item.c` 0 passed, 1 to do |
| 423 | Power Band | 3000 | - | - | power item | held items self-test (effort values); GBA tests that name it: 1 passed; held: `hold_effect/power_item.c` 0 passed, 1 to do |
| 424 | Power Anklet | 3000 | - | - | power item | held items self-test (effort values); GBA tests that name it: 4 passed; held: `hold_effect/power_item.c` 0 passed, 1 to do |
| 425 | Silk Scarf | 100 | - | - | type power | GBA tests that name it: 1 passed; held: `hold_effect/type_power.c` 2 passed |
| 426 | Charcoal | 9800 | - | - | type power | held: `hold_effect/type_power.c` 2 passed |
| 427 | Mystic Water | 100 | - | - | type power | GBA tests that name it: 1 passed; held: `hold_effect/type_power.c` 2 passed |
| 428 | Magnet | 100 | - | - | type power | held: `hold_effect/type_power.c` 2 passed |
| 429 | Miracle Seed | 100 | - | - | type power | held: `hold_effect/type_power.c` 2 passed |
| 430 | Never-Melt Ice | 100 | - | - | type power | held: `hold_effect/type_power.c` 2 passed |
| 431 | Black Belt | 100 | - | - | type power | held: `hold_effect/type_power.c` 2 passed |
| 432 | Poison Barb | 100 | - | - | type power | GBA tests that name it: 4 passed; held: `hold_effect/type_power.c` 2 passed |
| 433 | Soft Sand | 100 | - | - | type power | held: `hold_effect/type_power.c` 2 passed |
| 434 | Sharp Beak | 100 | - | - | type power | held: `hold_effect/type_power.c` 2 passed |
| 435 | Twisted Spoon | 100 | - | - | type power | GBA tests that name it: 1 passed; held: `hold_effect/type_power.c` 2 passed |
| 436 | Silver Powder | 100 | - | - | type power | held: `hold_effect/type_power.c` 2 passed |
| 437 | Hard Stone | 100 | - | - | type power | held: `hold_effect/type_power.c` 2 passed |
| 438 | Spell Tag | 100 | - | - | type power | held: `hold_effect/type_power.c` 2 passed |
| 439 | Dragon Fang | 100 | - | - | type power | held: `hold_effect/type_power.c` 2 passed |
| 440 | Black Glasses | 100 | - | - | type power | held: `hold_effect/type_power.c` 2 passed |
| 441 | Metal Coat | 100 | - | - | type power | held: `hold_effect/type_power.c` 2 passed; its evolution use: Onix -> Steelix, Scyther -> Scizor in a trade (`check-evo-items`, in the package) |
| 442 | Choice Band | 100 | - | - | choice band | GBA tests that name it: 25 passed; held: `hold_effect/choice_band.c` 3 passed |
| 443 | Choice Specs | 100 | - | - | choice specs | GBA tests that name it: 11 passed; held: `hold_effect/choice_specs.c` 3 passed |
| 444 | Choice Scarf | 100 | - | - | choice scarf | GBA tests that name it: 13 passed; held: `hold_effect/choice_scarf.c` 3 passed |
| 445 | Flame Orb | 200 | - | - | flame orb | GBA tests that name it: 11 passed; held: `hold_effect/flame_orb.c` 0 passed, 1 to do |
| 446 | Toxic Orb | 200 | - | - | toxic orb | GBA tests that name it: 19 passed; held: `hold_effect/toxic_orb.c` 0 passed, 1 to do |
| 447 | Damp Rock | 200 | - | - | damp rock | GBA tests that name it: 3 passed; held: `hold_effect/damp_rock.c` 1 passed |
| 448 | Heat Rock | 200 | - | - | heat rock | GBA tests that name it: 3 passed; held: `hold_effect/heat_rock.c` 1 passed |
| 449 | Smooth Rock | 200 | - | - | smooth rock | GBA tests that name it: 3 passed; held: `hold_effect/smooth_rock.c` 1 passed |
| 450 | Icy Rock | 200 | - | - | icy rock | GBA tests that name it: 4 passed; held: `hold_effect/icy_rock.c` 2 passed |
| 451 | Electric Seed | 4000 | - | - | terrain seed | GBA tests that name it: 8 passed; held: `hold_effect/terrain_seed.c` 7 passed |
| 452 | Psychic Seed | 4000 | - | - | terrain seed | GBA tests that name it: 2 passed; held: `hold_effect/terrain_seed.c` 7 passed |
| 453 | Misty Seed | 4000 | - | - | terrain seed | GBA tests that name it: 2 passed; held: `hold_effect/terrain_seed.c` 7 passed |
| 454 | Grassy Seed | 4000 | - | - | terrain seed | GBA tests that name it: 4 passed; held: `hold_effect/terrain_seed.c` 7 passed |
| 455 | Absorb Bulb | 200 | - | - | absorb bulb | GBA tests that name it: 5 passed; held: `hold_effect/absorb_bulb.c` 3 passed |
| 456 | Cell Battery | 200 | - | - | cell battery | GBA tests that name it: 4 passed; held: `hold_effect/cell_battery.c` 3 passed |
| 457 | Luminous Moss | 1000 | - | - | luminous moss | GBA tests that name it: 5 passed; held: `hold_effect/luminous_moss.c` 3 passed |
| 458 | Snowball | 200 | - | - | snowball | GBA tests that name it: 3 passed; held: `hold_effect/snowball.c` 3 passed |
| 459 | Bright Powder | 10 | - | - | evasion up | GBA tests that name it: 17 passed; held: `hold_effect/evasion_up.c` 0 passed, 1 to do |
| 460 | White Herb | 100 | - | - | white herb | GBA tests that name it: 14 passed, 2 failed (expected); held: `hold_effect/white_herb.c` 8 passed, 2 failed (expected) |
| 461 | Exp. Share | 3000 | ExpShare | - | exp share | GBA tests that name it: 1 passed; held: `hold_effect/exp_share.c` 0 passed, 1 to do |
| 462 | Quick Claw | 100 | - | - | quick claw | GBA tests that name it: 3 passed; held: `hold_effect/quick_claw.c` 1 passed |
| 463 | Soothe Bell | 100 | - | - | friendship up | GBA tests that name it: 1 passed; held: `hold_effect/friendship_up.c` 0 passed, 1 to do |
| 464 | Mental Herb | 100 | - | - | mental herb | GBA tests that name it: 10 passed; held: `hold_effect/mental_herb.c` 8 passed |
| 465 | King’s Rock | 100 | - | - | flinch | GBA tests that name it: 11 passed; held: `hold_effect/flinch.c` 5 passed; its evolution use: Poliwhirl -> Politoed, Slowpoke -> Slowking in a trade (`check-evo-items`, in the package) |
| 466 | Amulet Coin | 100 | - | - | double prize | GBA tests that name it: 4 passed; held: `hold_effect/double_prize.c` 0 passed, 1 to do |
| 467 | Cleanse Tag | 200 | - | - | repel | wild item audit (gameplay report section 5); held: `hold_effect/repel.c` 0 passed, 1 to do |
| 468 | Smoke Ball | 200 | - | - | can always run | GBA tests that name it: 1 passed; held: `hold_effect/can_always_run.c` 0 passed, 1 to do |
| 469 | Focus Band | 200 | - | - | focus band | GBA tests that name it: 4 passed, and 3 new (engine `fc8c5f76`, after the first candidate) passed; held: `hold_effect/focus_band.c` 0 passed, 1 to do |
| 470 | Lucky Egg | 200 | - | - | lucky egg | GBA tests that name it: 3 passed; held: `hold_effect/lucky_egg.c` 0 passed, 1 to do |
| 471 | Scope Lens | 100 | - | - | scope lens | GBA tests that name it: 4 passed; held: `hold_effect/scope_lens.c` 1 passed |
| 472 | Leftovers | 200 | - | - | leftovers | GBA tests that name it: 36 passed; held: `hold_effect/leftovers.c` 3 passed |
| 473 | Shell Bell | 200 | - | - | shell bell | GBA tests that name it: 18 passed; held: `hold_effect/shell_bell.c` 15 passed |
| 474 | Wide Lens | 200 | - | - | wide lens | GBA tests that name it: 1 passed; held: `hold_effect/wide_lens.c` 0 passed, 1 to do |
| 475 | Muscle Band | 200 | - | - | muscle band | GBA tests that name it: 6 passed; held: `hold_effect/muscle_band.c` 2 passed |
| 476 | Wise Glasses | 200 | - | - | wise glasses | GBA tests that name it: 2 passed; held: `hold_effect/wise_glasses.c` 2 passed |
| 477 | Expert Belt | 200 | - | - | expert belt | GBA tests that name it: 2 passed; held: `hold_effect/expert_belt.c` 2 passed |
| 478 | Light Clay | 200 | - | - | light clay | GBA tests that name it: 1 passed; held: `hold_effect/light_clay.c` 0 passed, 1 to do |
| 479 | Life Orb | 200 | - | - | life orb | GBA tests that name it: 29 passed, 1 known failing; held: `hold_effect/life_orb.c` 10 passed |
| 480 | Power Herb | 100 | - | - | power herb | GBA tests that name it: 12 passed; held: `hold_effect/power_herb.c` 0 passed, 1 to do |
| 481 | Focus Sash | 200 | - | - | focus sash | GBA tests that name it: 31 passed; held: `hold_effect/focus_sash.c` 0 passed, 1 to do |
| 482 | Zoom Lens | 200 | - | - | zoom lens | GBA tests that name it: 2 passed; held: `hold_effect/zoom_lens.c` 2 passed |
| 483 | Metronome | 200 | - | - | metronome | GBA tests that name it: 6 passed; held: `hold_effect/metronome.c` 6 passed |
| 484 | Iron Ball | 200 | - | - | iron ball | GBA tests that name it: 11 passed, 2 failed (expected), 1 known failing; held: `hold_effect/iron_ball.c` 1 passed |
| 485 | Lagging Tail | 200 | - | - | lagging tail | GBA tests that name it: 7 passed, 1 known failing; held: `hold_effect/lagging_tail.c` 1 passed |
| 486 | Destiny Knot | 200 | - | - | destiny knot | GBA tests that name it: 8 passed; held: `hold_effect/destiny_knot.c` 5 passed |
| 487 | Black Sludge | 200 | - | - | black sludge | GBA tests that name it: 13 passed; held: `hold_effect/black_sludge.c` 8 passed |
| 488 | Grip Claw | 200 | - | - | grip claw | GBA tests that name it: 1 passed; held: `hold_effect/grip_claw.c` 0 passed, 1 to do |
| 489 | Sticky Barb | 200 | - | - | sticky barb | GBA tests that name it: 4 passed; held: `hold_effect/sticky_barb.c` 2 passed |
| 490 | Shed Shell | 100 | - | - | shed shell | GBA tests that name it: 6 passed; held: `hold_effect/shed_shell.c` 4 passed |
| 491 | Big Root | 200 | - | - | big root | GBA tests that name it: 6 passed; held: `hold_effect/big_root.c` 3 passed |
| 492 | Razor Claw | 2100 | - | - | scope lens | GBA tests that name it: 9 passed; held: `hold_effect/scope_lens.c` 1 passed; its evolution use: Sneasel -> Weavile on a level up at night (`check-evo-items`, engine `059e906e`, after the first candidate) |
| 493 | Razor Fang | 2100 | - | - | flinch | GBA tests that name it: 2 passed; held: `hold_effect/flinch.c` 5 passed; its evolution use: Gligar -> Gliscor on a level up at night (`check-evo-items`, engine `059e906e`, after the first candidate) |
| 494 | Eviolite | 200 | - | - | eviolite | GBA tests that name it: 9 passed; held: `hold_effect/eviolite.c` 3 passed |
| 495 | Float Stone | 200 | - | - | float stone | GBA tests that name it: 2 passed; held: `hold_effect/float_stone.c` 2 passed |
| 496 | Rocky Helmet | 200 | - | - | rocky helmet | GBA tests that name it: 21 passed; held: `hold_effect/rocky_helmet.c` 2 passed, 1 to do |
| 497 | Air Balloon | 200 | - | - | air balloon | GBA tests that name it: 28 passed, 1 failed (expected); held: `hold_effect/air_balloon.c` 10 passed, 1 failed (expected) |
| 498 | Red Card | 200 | - | - | red card | GBA tests that name it: 44 passed; held: `hold_effect/red_card.c` 26 passed |
| 499 | Ring Target | 200 | - | - | ring target | GBA tests that name it: 3 passed; held: `hold_effect/ring_target.c` 3 passed |
| 500 | Binding Band | 200 | - | - | binding band | GBA tests that name it: 2 passed; held: `hold_effect/binding_band.c` 2 passed, 1 to do |
| 501 | Eject Button | 200 | - | - | eject button | GBA tests that name it: 42 passed, 1 assumption failed; held: `hold_effect/eject_button.c` 13 passed |
| 502 | Weakness Policy | 1000 | - | - | weakness policy | GBA tests that name it: 6 passed; held: `hold_effect/weakness_policy.c` 1 passed, 1 to do |
| 503 | Assault Vest | 1000 | - | - | assault vest | GBA tests that name it: 13 passed; held: `hold_effect/assault_vest.c` 5 passed |
| 504 | Safety Goggles | 1000 | - | - | safety goggles | GBA tests that name it: 12 passed; held: `hold_effect/safety_goggles.c` 4 passed |
| 505 | Adrenaline Orb | 300 | - | - | adrenaline orb | GBA tests that name it: 4 passed; held: `hold_effect/adrenaline_orb.c` 4 passed |
| 506 | Terrain Extender | 4000 | - | - | terrain extender | GBA tests that name it: 4 passed; held: `hold_effect/terrain_extender.c` 5 passed |
| 507 | Protective Pads | 4000 | - | - | protective pads | GBA tests that name it: 11 passed; held: `hold_effect/protective_pads.c` 5 passed |
| 508 | Throat Spray | 4000 | - | - | throat spray | GBA tests that name it: 15 passed, 1 assumption failed; held: `hold_effect/throat_spray.c` 10 passed, 1 assumption failed |
| 509 | Eject Pack | 4000 | - | - | eject pack | GBA tests that name it: 36 passed; held: `hold_effect/eject_pack.c` 16 passed |
| 510 | Heavy-Duty Boots | 4000 | - | - | heavy duty boots | held: no Stealth Rock damage and no Toxic Spikes poison on switching in (`item_audit_plates_boots.c`, engine `47e47359`, after the first candidate); sold in the PC game's coin shop |
| 511 | Blunder Policy | 4000 | - | - | blunder policy | GBA tests that name it: 11 passed; held: `hold_effect/blunder_policy.c` 11 passed |
| 512 | Room Service | 4000 | - | - | room service | GBA tests that name it: 5 passed; held: `hold_effect/room_service.c` 1 passed |
| 513 | Utility Umbrella | 4000 | - | - | utility umbrella | GBA tests that name it: 16 passed; held: `hold_effect/utility_umbrella.c` 2 passed |
| 758 | Ability Shield | 20000 | - | - | ability shield | GBA tests that name it: 23 passed; held: `hold_effect/ability_shield.c` 16 passed |
| 759 | Clear Amulet | 30000 | - | - | clear amulet | GBA tests that name it: 14 passed; held: `hold_effect/clear_amulet.c` 4 passed |
| 760 | Punching Glove | 15000 | - | - | punching glove | GBA tests that name it: 6 passed; held: `hold_effect/punching_glove.c` 0 passed, 1 to do |
| 761 | Covert Cloak | 20000 | - | - | covert cloak | GBA tests that name it: 15 passed; held: `hold_effect/covert_cloak.c` 7 passed |
| 762 | Loaded Dice | 20000 | - | - | loaded dice | GBA tests that name it: 9 passed; held: `hold_effect/loaded_dice.c` 0 passed, 1 to do |
| 763 | Auspicious Armor | 3000 | EvolutionStone | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 764 | Booster Energy | 0 | - | - | booster energy | GBA tests that name it: 26 passed; held: `hold_effect/booster_energy.c` 13 passed |
| 765 | Big Bamboo Shoot | 3000 | - | - | - | no use from the bag, in battle or held |
| 766 | Gimmighoul Coin | 400 | - | - | - | no use from the bag, in battle or held |
| 767 | Leader’s Crest | 3000 | - | - | - | GBA tests that name it: 7 passed |
| 768 | Malicious Armor | 3000 | EvolutionStone | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 769 | Mirror Herb | 30000 | - | - | mirror herb | GBA tests that name it: 16 passed; held: `hold_effect/mirror_herb.c` 9 passed |
| 773 | Tiny Bamboo Shoot | 750 | - | - | - | no use from the bag, in battle or held |
| 774 | Bug Tera Shard | 0 | - | - | - | no use from the bag, in battle or held |
| 775 | Dark Tera Shard | 0 | - | - | - | no use from the bag, in battle or held |
| 776 | Dragon Tera Shard | 0 | - | - | - | no use from the bag, in battle or held |
| 777 | Electric Tera Shard | 0 | - | - | - | GBA tests that name it: 1 passed |
| 778 | Fairy Tera Shard | 0 | - | - | - | no use from the bag, in battle or held |
| 779 | Fighting Tera Shard | 0 | - | - | - | GBA tests that name it: 1 passed |
| 780 | Fire Tera Shard | 0 | - | - | - | no use from the bag, in battle or held |
| 781 | Flying Tera Shard | 0 | - | - | - | no use from the bag, in battle or held |
| 782 | Ghost Tera Shard | 0 | - | - | - | no use from the bag, in battle or held |
| 783 | Grass Tera Shard | 0 | - | - | - | no use from the bag, in battle or held |
| 784 | Ground Tera Shard | 0 | - | - | - | no use from the bag, in battle or held |
| 785 | Ice Tera Shard | 0 | - | - | - | no use from the bag, in battle or held |
| 786 | Normal Tera Shard | 0 | - | - | - | no use from the bag, in battle or held |
| 787 | Poison Tera Shard | 0 | - | - | - | no use from the bag, in battle or held |
| 788 | Psychic Tera Shard | 0 | - | - | - | GBA tests that name it: 1 passed |
| 789 | Rock Tera Shard | 0 | - | - | - | no use from the bag, in battle or held |
| 790 | Steel Tera Shard | 0 | - | - | - | no use from the bag, in battle or held |
| 791 | Water Tera Shard | 0 | - | - | - | no use from the bag, in battle or held |
| 792 | Adamant Crystal | 0 | - | - | adamant orb | held: `hold_effect/adamant_orb.c` 1 passed |
| 793 | Griseous Core | 0 | - | - | griseous orb | GBA tests that name it: 4 passed; held: `hold_effect/griseous_orb.c` 1 passed |
| 794 | Lustrous Globe | 0 | - | - | lustrous orb | held: `hold_effect/lustrous_orb.c` 1 passed |
| 795 | Black Augurite | 8000 | EvolutionStone | - | - | Scyther -> Kleavor, coin-shop self-test `check-rare-goods` (engine `3c9e3088`, after the first candidate) |
| 796 | Linking Cord | 8000 | EvolutionStone | - | - | each trade-alone evolution (Kadabra, Machoke, Graveler, Haunter, Boldore, Gurdurr, Phantump), not a held item's, coin-shop self-test `check-rare-goods` (engine `3c9e3088`, after the first candidate) |
| 797 | Peat Block | 10000 | EvolutionStone | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 798 | Berserk Gene | 20 | - | - | berserk gene | GBA tests that name it: 13 passed; held: `hold_effect/berserk_gene.c` 12 passed |
| 799 | Fairy Feather | 1000 | - | - | type power | held: `hold_effect/type_power.c` 2 passed |
| 800 | Syrupy Apple | 2200 | EvolutionStone | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 801 | Unremarkable Teacup | 1600 | EvolutionStone | - | - | GBA tests that name it: 3 passed; its evolution use: not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 802 | Masterpiece Teacup | 38000 | EvolutionStone | - | - | GBA tests that name it: 1 passed; its evolution use: not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 803 | Cornerstone Mask | 0 | - | - | ogerpon mask | GBA tests that name it: 6 passed; held: `hold_effect/ogerpon_mask.c` 1 passed |
| 804 | Wellspring Mask | 0 | - | - | ogerpon mask | GBA tests that name it: 6 passed; held: `hold_effect/ogerpon_mask.c` 1 passed |
| 805 | Hearthflame Mask | 0 | - | - | ogerpon mask | GBA tests that name it: 9 passed; held: `hold_effect/ogerpon_mask.c` 1 passed |
| 806 | Health Mochi | 500 | Medicine | - | - | +10 HP base points, coin-shop self-test `check-rare-goods` (engine `3c9e3088`, after the first candidate) |
| 807 | Muscle Mochi | 500 | Medicine | - | - | +10 Attack base points, coin-shop self-test `check-rare-goods` (engine `3c9e3088`, after the first candidate) |
| 808 | Resist Mochi | 500 | Medicine | - | - | +10 Defense base points, coin-shop self-test `check-rare-goods` (engine `3c9e3088`, after the first candidate) |
| 809 | Genius Mochi | 500 | Medicine | - | - | +10 Sp. Atk base points, coin-shop self-test `check-rare-goods` (engine `3c9e3088`, after the first candidate) |
| 810 | Clever Mochi | 500 | Medicine | - | - | +10 Sp. Def base points, coin-shop self-test `check-rare-goods` (engine `3c9e3088`, after the first candidate) |
| 811 | Swift Mochi | 500 | Medicine | - | - | +10 Speed base points, up to 252, coin-shop self-test `check-rare-goods` (engine `3c9e3088`, after the first candidate) |
| 812 | Fresh-Start Mochi | 300 | ResetEVs | - | - | every base point to 0, coin-shop self-test `check-rare-goods` (engine `3c9e3088`, after the first candidate) |
| 814 | Metal Alloy | 6000 | EvolutionStone | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 815 | Stellar Tera Shard | 0 | - | - | - | no use from the bag, in battle or held |
| 816 | Jubilife Muffin | 250 | Medicine | cure status | - | GBA tests that name it: 3 passed; in battle: `item_effect/cure_status.c` 23 passed |
| 817 | Remedy | 150 | Medicine | restore HP | - | in battle: `item_effect/restore_hp.c` 11 passed |
| 818 | Fine Remedy | 150 | Medicine | restore HP | - | in battle: `item_effect/restore_hp.c` 11 passed |
| 819 | Superb Remedy | 750 | Medicine | restore HP | - | in battle: `item_effect/restore_hp.c` 11 passed |
| 820 | Aux Evasion | 800 | - | - | - | no use from the bag, in battle or held |
| 821 | Aux Guard | 400 | - | - | - | no use from the bag, in battle or held |
| 822 | Aux Power | 400 | - | - | - | no use from the bag, in battle or held |
| 823 | Aux Powerguard | 1200 | - | - | - | no use from the bag, in battle or held |
| 824 | Choice Dumpling | 1200 | - | - | - | no use from the bag, in battle or held |
| 825 | Swap Snack | 1200 | - | - | - | no use from the bag, in battle or held |
| 826 | Twice-Spiced Radish | 1600 | - | - | - | GBA tests that name it: 1 passed |
| 827 | Pokéshi Doll | 2000 | - | - | - | no use from the bag, in battle or held |
| 829 | Clefablite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 830 | Victreebelite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 831 | Starminite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 832 | Dragoninite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 833 | Meganiumite | 60000 | - | - | mega stone | GBA tests that name it: 16 passed, 1 failed (expected); Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 834 | Feraligite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 835 | Skarmorite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 836 | Froslassite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 837 | Emboarite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 838 | Excadrite | 60000 | - | - | mega stone | GBA tests that name it: 1 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 839 | Scolipite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 840 | Scraftinite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 841 | Eelektrossite | 60000 | - | - | mega stone | GBA tests that name it: 5 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 842 | Chandelurite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 843 | Chesnaughtite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 844 | Delphoxite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 845 | Greninjite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 846 | Pyroarite | 60000 | - | - | mega stone | GBA tests that name it: 1 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 847 | Floettite | 60000 | - | - | mega stone | GBA tests that name it: 1 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 848 | Malamarite | 60000 | - | - | mega stone | GBA tests that name it: 2 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 849 | Barbaracite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 850 | Dragalgite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 851 | Hawluchanite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 852 | Zygardite | 60000 | - | - | mega stone | GBA tests that name it: 2 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 853 | Drampanite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 854 | Falinksite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 855 | Heatranite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 856 | Darkranite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 857 | Zeraorite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 858 | Raichunite X | 60000 | - | - | mega stone | GBA tests that name it: 1 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 859 | Raichunite Y | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 860 | Chimechite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 861 | Absolite Z | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 862 | Staraptite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 863 | Garchompite Z | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 864 | Lucarionite Z | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 865 | Golurkite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 866 | Meowsticite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 867 | Crabominite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 868 | Golisopite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 869 | Magearnite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 870 | Scovillainite | 60000 | - | - | mega stone | GBA tests that name it: 7 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 871 | Baxcalibrite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 872 | Tatsugirinite | 60000 | - | - | mega stone | GBA tests that name it: 1 passed; Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |
| 873 | Glimmoranite | 60000 | - | - | mega stone | Mega Evolution: `form_change/mega_*.c` (4 files) 40 passed, 1 known failing |

## Berries (68)

| # | Item | Price | From the bag | In battle | Held | Checked by |
| --- | --- | --- | --- | --- | --- | --- |
| 514 | Cheri Berry | 20 | Medicine | cure status | cure par | held: `hold_effect/cure_status.c` 15 passed; in battle: `item_effect/cure_status.c` 23 passed |
| 515 | Chesto Berry | 20 | Medicine | cure status | cure slp | healing self-test; GBA tests that name it: 12 passed; held: `hold_effect/cure_status.c` 15 passed; in battle: `item_effect/cure_status.c` 23 passed |
| 516 | Pecha Berry | 20 | Medicine | cure status | cure psn | healing self-test; GBA tests that name it: 17 passed; held: `hold_effect/cure_status.c` 15 passed; in battle: `item_effect/cure_status.c` 23 passed |
| 517 | Rawst Berry | 20 | Medicine | cure status | cure brn | healing self-test; GBA tests that name it: 7 passed; held: `hold_effect/cure_status.c` 15 passed; in battle: `item_effect/cure_status.c` 23 passed |
| 518 | Aspear Berry | 20 | Medicine | cure status | cure frz | healing self-test; GBA tests that name it: 4 passed; held: `hold_effect/cure_status.c` 15 passed; in battle: `item_effect/cure_status.c` 23 passed |
| 519 | Leppa Berry | 20 | PPRecovery | restore PP | restore pp | bag items self-test; GBA tests that name it: 8 passed; held: `hold_effect/restore_pp.c` 3 passed; in battle: `item_effect/restore_pp.c` 4 passed, 2 to do |
| 520 | Oran Berry | 20 | Medicine | restore HP | restore hp | bag items self-test; GBA tests that name it: 57 passed; held: `hold_effect/restore_hp.c` 7 passed; in battle: `item_effect/restore_hp.c` 11 passed |
| 521 | Persim Berry | 20 | - | cure status | cure confusion | bag items self-test; GBA tests that name it: 4 passed; held: `hold_effect/cure_status.c` 15 passed; in battle: `item_effect/cure_status.c` 23 passed |
| 522 | Lum Berry | 20 | Medicine | cure status | cure status | healing self-test; GBA tests that name it: 36 passed; held: `hold_effect/cure_status.c` 15 passed; in battle: `item_effect/cure_status.c` 23 passed |
| 523 | Sitrus Berry | 20 | Medicine | restore HP | restore pct hp | bag items self-test; GBA tests that name it: 63 passed; held: `hold_effect/restore_hp.c` 7 passed; in battle: `item_effect/restore_hp.c` 11 passed |
| 524 | Figy Berry | 20 | - | - | confuse flavor | bag items self-test; GBA tests that name it: 2 passed; held: `hold_effect/confuse_*.c` (no test written yet) |
| 525 | Wiki Berry | 20 | - | - | confuse flavor | GBA tests that name it: 1 passed; held: `hold_effect/confuse_*.c` (no test written yet) |
| 526 | Mago Berry | 20 | - | - | confuse flavor | GBA tests that name it: 1 passed; held: `hold_effect/confuse_*.c` (no test written yet) |
| 527 | Aguav Berry | 20 | - | - | confuse flavor | GBA tests that name it: 1 passed; held: `hold_effect/confuse_*.c` (no test written yet) |
| 528 | Iapapa Berry | 20 | - | - | confuse flavor | GBA tests that name it: 1 passed; held: `hold_effect/confuse_*.c` (no test written yet) |
| 529 | Razz Berry | 20 | - | - | - | no use from the bag, in battle or held |
| 530 | Bluk Berry | 20 | - | - | - | GBA tests that name it: 9 passed |
| 531 | Nanab Berry | 20 | - | - | - | no use from the bag, in battle or held |
| 532 | Wepear Berry | 20 | - | - | - | no use from the bag, in battle or held |
| 533 | Pinap Berry | 20 | - | - | - | no use from the bag, in battle or held |
| 534 | Pomeg Berry | 20 | ReduceEV | - | - | bag items self-test; GBA tests that name it: 1 passed |
| 535 | Kelpsy Berry | 20 | ReduceEV | - | - | bag items self-test; GBA tests that name it: 1 passed |
| 536 | Qualot Berry | 20 | ReduceEV | - | - | bag items self-test |
| 537 | Hondew Berry | 20 | ReduceEV | - | - | bag items self-test |
| 538 | Grepa Berry | 20 | ReduceEV | - | - | bag items self-test |
| 539 | Tamato Berry | 20 | ReduceEV | - | - | bag items self-test |
| 540 | Cornn Berry | 20 | - | - | - | no use from the bag, in battle or held |
| 541 | Magost Berry | 20 | - | - | - | GBA tests that name it: 11 passed |
| 542 | Rabuta Berry | 20 | - | - | - | no use from the bag, in battle or held |
| 543 | Nomel Berry | 20 | - | - | - | no use from the bag, in battle or held |
| 544 | Spelon Berry | 20 | - | - | - | no use from the bag, in battle or held |
| 545 | Pamtre Berry | 20 | - | - | - | no use from the bag, in battle or held |
| 546 | Watmel Berry | 20 | - | - | - | no use from the bag, in battle or held |
| 547 | Durin Berry | 20 | - | - | - | no use from the bag, in battle or held |
| 548 | Belue Berry | 20 | - | - | - | no use from the bag, in battle or held |
| 549 | Chilan Berry | 20 | - | - | resist berry | GBA tests that name it: 8 passed; held: `hold_effect/resist_berry.c` 4 passed |
| 550 | Occa Berry | 20 | - | - | resist berry | GBA tests that name it: 2 passed; held: `hold_effect/resist_berry.c` 4 passed |
| 551 | Passho Berry | 20 | - | - | resist berry | GBA tests that name it: 2 passed; held: `hold_effect/resist_berry.c` 4 passed |
| 552 | Wacan Berry | 20 | - | - | resist berry | GBA tests that name it: 3 passed; held: `hold_effect/resist_berry.c` 4 passed |
| 553 | Rindo Berry | 20 | - | - | resist berry | GBA tests that name it: 3 passed; held: `hold_effect/resist_berry.c` 4 passed |
| 554 | Yache Berry | 20 | - | - | resist berry | GBA tests that name it: 1 passed; held: `hold_effect/resist_berry.c` 4 passed |
| 555 | Chople Berry | 20 | - | - | resist berry | GBA tests that name it: 5 passed, 1 known failing; held: `hold_effect/resist_berry.c` 4 passed |
| 556 | Kebia Berry | 20 | - | - | resist berry | GBA tests that name it: 1 passed; held: `hold_effect/resist_berry.c` 4 passed |
| 557 | Shuca Berry | 20 | - | - | resist berry | GBA tests that name it: 3 passed; held: `hold_effect/resist_berry.c` 4 passed |
| 558 | Coba Berry | 20 | - | - | resist berry | GBA tests that name it: 1 passed; held: `hold_effect/resist_berry.c` 4 passed |
| 559 | Payapa Berry | 20 | - | - | resist berry | GBA tests that name it: 1 passed; held: `hold_effect/resist_berry.c` 4 passed |
| 560 | Tanga Berry | 20 | - | - | resist berry | GBA tests that name it: 2 passed; held: `hold_effect/resist_berry.c` 4 passed |
| 561 | Charti Berry | 20 | - | - | resist berry | GBA tests that name it: 2 passed; held: `hold_effect/resist_berry.c` 4 passed |
| 562 | Kasib Berry | 20 | - | - | resist berry | GBA tests that name it: 1 passed; held: `hold_effect/resist_berry.c` 4 passed |
| 563 | Haban Berry | 20 | - | - | resist berry | GBA tests that name it: 1 passed; held: `hold_effect/resist_berry.c` 4 passed |
| 564 | Colbur Berry | 20 | - | - | resist berry | GBA tests that name it: 1 passed; held: `hold_effect/resist_berry.c` 4 passed |
| 565 | Babiri Berry | 20 | - | - | resist berry | GBA tests that name it: 2 passed; held: `hold_effect/resist_berry.c` 4 passed |
| 566 | Roseli Berry | 20 | - | - | resist berry | held: `hold_effect/resist_berry.c` 4 passed |
| 567 | Liechi Berry | 20 | - | - | attack up | GBA tests that name it: 26 passed; held: `hold_effect/attack_up.c` 3 passed |
| 568 | Ganlon Berry | 20 | - | - | defense up | GBA tests that name it: 6 passed; held: `hold_effect/defense_up.c` 3 passed |
| 569 | Salac Berry | 20 | - | - | speed up | GBA tests that name it: 9 passed; held: `hold_effect/speed_up.c` 4 passed |
| 570 | Petaya Berry | 20 | - | - | sp attack up | GBA tests that name it: 5 passed; held: `hold_effect/sp_attack_up.c` 3 passed |
| 571 | Apicot Berry | 20 | - | - | sp defense up | GBA tests that name it: 6 passed; held: `hold_effect/sp_defense_up.c` 3 passed |
| 572 | Lansat Berry | 20 | - | - | critical up | GBA tests that name it: 3 passed; held: `hold_effect/critical_up.c` 3 passed |
| 573 | Starf Berry | 20 | - | - | random stat up | GBA tests that name it: 12 passed; held: `hold_effect/random_stat_up.c` 4 passed |
| 574 | Enigma Berry | 20 | - | - | enigma berry | GBA tests that name it: 6 passed; held: `hold_effect/enigma_berry.c` 4 passed |
| 575 | Micle Berry | 20 | - | - | micle berry | GBA tests that name it: 6 passed; held: `hold_effect/micle_berry.c` 5 passed |
| 576 | Custap Berry | 20 | - | - | custap berry | GBA tests that name it: 3 passed; held: `hold_effect/custap_berry.c` 3 passed |
| 577 | Jaboca Berry | 20 | - | - | jaboca berry | GBA tests that name it: 5 passed; held: `hold_effect/jaboca_berry.c` 3 passed |
| 578 | Rowap Berry | 20 | - | - | rowap berry | GBA tests that name it: 6 passed; held: `hold_effect/rowap_berry.c` 3 passed |
| 579 | Kee Berry | 20 | - | - | kee berry | GBA tests that name it: 8 passed; held: `hold_effect/kee_berry.c` 5 passed |
| 580 | Maranga Berry | 20 | - | - | maranga berry | GBA tests that name it: 7 passed; held: `hold_effect/maranga_berry.c` 5 passed |
| 581 | Enigma Berry | 20 | EnigmaBerry | restore HP | - | in battle: `item_effect/restore_hp.c` 11 passed |

## TMs and HMs (108)

| # | Item | Price | From the bag | In battle | Held | Checked by |
| --- | --- | --- | --- | --- | --- | --- |
| 582 | TM01 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching); GBA tests that name it: 1 passed |
| 583 | TM02 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 584 | TM03 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 585 | TM04 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 586 | TM05 | 1000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching); GBA tests that name it: 1 passed |
| 587 | TM06 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 588 | TM07 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 589 | TM08 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 590 | TM09 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 591 | TM10 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 592 | TM11 | 2000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 593 | TM12 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 594 | TM13 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 595 | TM14 | 5500 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching); GBA tests that name it: 1 passed |
| 596 | TM15 | 7500 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 597 | TM16 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 598 | TM17 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 599 | TM18 | 2000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 600 | TM19 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 601 | TM20 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 602 | TM21 | 1000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 603 | TM22 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 604 | TM23 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 605 | TM24 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 606 | TM25 | 5500 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching); GBA tests that name it: 1 passed |
| 607 | TM26 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 608 | TM27 | 1000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 609 | TM28 | 2000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 610 | TM29 | 2000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 611 | TM30 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 612 | TM31 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 613 | TM32 | 2000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 614 | TM33 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 615 | TM34 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 616 | TM35 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 617 | TM36 | 1000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 618 | TM37 | 2000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 619 | TM38 | 5500 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 620 | TM39 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 621 | TM40 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 622 | TM41 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 623 | TM42 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching); GBA tests that name it: 1 passed |
| 624 | TM43 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 625 | TM44 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 626 | TM45 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 627 | TM46 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 628 | TM47 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 629 | TM48 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 630 | TM49 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 631 | TM50 | 3000 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 632 | TM51 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 633 | TM52 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 634 | TM53 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 635 | TM54 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 636 | TM55 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 637 | TM56 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 638 | TM57 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 639 | TM58 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 640 | TM59 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 641 | TM60 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 642 | TM61 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 643 | TM62 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 644 | TM63 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 645 | TM64 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 646 | TM65 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 647 | TM66 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 648 | TM67 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 649 | TM68 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 650 | TM69 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 651 | TM70 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 652 | TM71 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 653 | TM72 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 654 | TM73 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 655 | TM74 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 656 | TM75 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 657 | TM76 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 658 | TM77 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 659 | TM78 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 660 | TM79 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 661 | TM80 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 662 | TM81 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 663 | TM82 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 664 | TM83 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 665 | TM84 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 666 | TM85 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 667 | TM86 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 668 | TM87 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 669 | TM88 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 670 | TM89 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 671 | TM90 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 672 | TM91 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 673 | TM92 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 674 | TM93 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 675 | TM94 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 676 | TM95 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 677 | TM96 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 678 | TM97 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 679 | TM98 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 680 | TM99 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 681 | TM100 | 3000 | TMHM | - | - | a spare TM number: teaches no move (the self-test found 58 TMs and HMs with one), given nowhere in the game's data |
| 682 | HM01 | 0 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 683 | HM02 | 0 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching); GBA tests that name it: 1 passed |
| 684 | HM03 | 0 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 685 | HM04 | 0 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 686 | HM05 | 0 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching); GBA tests that name it: 1 passed |
| 687 | HM06 | 0 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |
| 688 | HM07 | 0 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching); GBA tests that name it: 1 passed |
| 689 | HM08 | 0 | TMHM | - | - | TM and HM checks (bag items self-test; reuse: move switching) |

## Key Items (72)

| # | Item | Price | From the bag | In battle | Held | Checked by |
| --- | --- | --- | --- | --- | --- | --- |
| 690 | Oval Charm | 0 | - | - | - | wild item audit (gameplay report section 5) |
| 691 | Shiny Charm | 0 | - | - | - | wild item audit (gameplay report section 5) |
| 692 | Catching Charm | 0 | - | - | - | wild item audit (gameplay report section 5) |
| 693 | Exp. Charm | 0 | - | - | - | 2 new GBA tests (engine `aebcf98d`, after the first candidate) passed: the experience gained half again as much with it in the Bag, alone and with a held Lucky Egg |
| 694 | Rotom Catalog | 0 | RotomCatalog | - | - | each of Rotom's six forms and back, coin-shop self-test `check-rare-goods` (engine `3c9e3088`, after the first candidate) |
| 695 | Gracidea | 0 | FormChange | - | - | Form items self-test (engine `993496aa`, after the first candidate) |
| 696 | Reveal Glass | 0 | FormChange | - | - | Form items self-test (engine `993496aa`, after the first candidate) |
| 697 | DNA Splicers | 0 | Fusion | - | - | used from the Bag in the real game: Kyurem and Reshiram fused and split again (engine `c624a2d4`, after the first candidate) |
| 698 | Zygarde Cube | 0 | ZygardeCube | - | - | Zygarde's two choices, coin-shop self-test `check-rare-goods` (engine `3c9e3088`, after the first candidate) |
| 699 | Prison Bottle | 0 | FormChange | - | - | Form items self-test (engine `993496aa`, after the first candidate) |
| 700 | N-Solarizer | 0 | Fusion | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 701 | N-Lunarizer | 0 | Fusion | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 702 | Reins of Unity | 0 | Fusion | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 703 | Mega Ring | 0 | - | - | - | Mega Evolution offered and done with it in the Bag, not offered without it, in the real game (`mega_check.py` cases `wild` and `no-mega-ring`, engine `223d15e1`, after the first candidate) |
| 704 | Z-Power Ring | 0 | - | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 705 | Dynamax Band | 0 | - | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 706 | Bike | 0 | Bike | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 707 | Mach Bike | 0 | Bike | - | - | ridden from the Bag in the real game, faster than walking (engine `812d7bf3`, after the first candidate) |
| 708 | Acro Bike | 0 | Bike | - | - | ridden from the Bag in the real game (engine `812d7bf3`, after the first candidate) |
| 709 | Old Rod | 0 | Rod | - | - | Rods self-test; cast from the Bag in the real game (engines `7054b688`, `c624a2d4`, after the first candidate) |
| 710 | Good Rod | 0 | Rod | - | - | Rods self-test; cast from the Bag in the real game (engines `7054b688`, `c624a2d4`, after the first candidate) |
| 711 | Super Rod | 0 | Rod | - | - | Rods self-test; cast from the Bag in the real game (engines `7054b688`, `c624a2d4`, after the first candidate) |
| 712 | Dowsing Machine | 0 | Itemfinder | - | - | used from the Bag in the real game, by a hidden item and away from any (engine `c624a2d4`, after the first candidate; its messages still call it the ITEMFINDER) |
| 713 | Town Map | 0 | TownMap | - | - | used from the Bag in the real game: "took a closer look at the HOENN region map", the map at Route 104, B back to the field (engine `223d15e1`, after the first candidate) |
| 714 | Vs. Seeker | 0 | - | - | - | not obtainable in this game: only Kanto's maps give it, and no map, warp or script of this game reaches Kanto (after the first candidate) |
| 715 | TM Case | 0 | - | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 716 | Berry Pouch | 0 | - | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 717 | Pokemon Box Link | 0 | PokemonBoxLink | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 718 | Coin Case | 0 | CoinCase | - | - | used from the Bag in the real game: "Your COINS: 123456" (the PC wallet's six digits); its description said 9,999 (MS-157, fixed on engine `4f841321`, after the first candidate) |
| 719 | Powder Jar | 0 | PowderJar | - | - | used from the Bag in the real game: "POWDER QTY: 0" (engine `812d7bf3`, after the first candidate) |
| 720 | Wailmer Pail | 0 | WailmerPail | - | - | used on Sudowoodo and on a planted Oran Berry (from the tree and from the Bag) in the real game (engine `223d15e1`); the yield each watered stage gives, a self-test (engine `bbf722b7`); after the first candidate |
| 721 | Poké Radar | 0 | - | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 722 | Pokeblock Case | 0 | PokeblockCase | - | - | used from the Bag in the real game: the case opens (engine `812d7bf3`, after the first candidate) |
| 723 | Soot Sack | 0 | - | - | - | five steps in Route 113's ash grass in the real game, 2D and 3D: the Glass Workshop counts 5 (engine `223d15e1`, after the first candidate) |
| 724 | Poké Flute | 0 | PokeFlute | Poke Flute | - | GBA tests that name it: 5 passed; in battle: `item_effect/poke_flute.c` 2 passed; not obtainable in this game: only Kanto's maps give it, and no map, warp or script of this game reaches Kanto (after the first candidate) |
| 725 | Fame Checker | 0 | - | - | - | not obtainable in this game: only Kanto's maps give it, and no map, warp or script of this game reaches Kanto (after the first candidate) |
| 726 | Teachy TV | 0 | - | - | - | not obtainable in this game: only Kanto's maps give it, and no map, warp or script of this game reaches Kanto (after the first candidate) |
| 727 | S.S. Ticket | 0 | - | - | - | story key item, the scripts read: given, checked and taken as in Emerald (code read, after the first candidate); in the real game (engine `a5013203`, the package's, Classic 2D test build): the Battle Frontier's ferry attendant, "DARREN flashed the TICKET.", "Perfect! That's all you need!"; without it "DARREN doesn't have the TICKET..." |
| 728 | Eon Ticket | 0 | - | - | - | story key item, the scripts read: given, checked and taken as in Emerald (code read, after the first candidate) |
| 729 | Mystic Ticket | 0 | - | - | - | story key item, the scripts read: given, checked and taken as in Emerald (code read, after the first candidate) |
| 730 | Aurora Ticket | 0 | - | - | - | story key item, the scripts read: given, checked and taken as in Emerald (code read, after the first candidate) |
| 731 | Old Sea Map | 0 | - | - | - | story key item, the scripts read: given, checked and taken as in Emerald (code read, after the first candidate) |
| 732 | Letter | 0 | - | - | - | story key item, the scripts read: given, checked and taken as in Emerald (code read, after the first candidate) |
| 733 | Devon Parts | 0 | - | - | - | story key item, the scripts read: given, checked and taken as in Emerald (code read, after the first candidate) |
| 734 | Go-Goggles | 0 | - | - | - | into Route 111's desert in the real game, refused without them (engine `c624a2d4`, after the first candidate) |
| 735 | Devon Scope | 0 | - | - | - | a hidden Kecleon revealed in the real game; its battle refused offline (MS-156), fixed on engine `223d15e1` (after the first candidate) |
| 736 | Basement Key | 0 | - | - | - | New Mauville's door in the real game: "Use the BASEMENT KEY?", "The door opened!", in; without it, locked (engine `812d7bf3`, after the first candidate) |
| 737 | Scanner | 0 | - | - | - | story key item, the scripts read: given, checked and taken as in Emerald (code read, after the first candidate) |
| 738 | Storage Key | 0 | - | - | - | story key item, the scripts read: given, checked and taken as in Emerald (code read, after the first candidate); in the real game (engine `a5013203`, the package's, Classic 2D test build): its Abandoned Ship door opened with it ("The inserted KEY stuck fast, but the door opened."), locked without it |
| 739 | Key to Room 1 | 0 | - | - | - | story key item, the scripts read: given, checked and taken as in Emerald (code read, after the first candidate); in the real game (engine `a5013203`, the package's, Classic 2D test build): its Abandoned Ship door opened with it ("The inserted KEY stuck fast, but the door opened."), locked without it |
| 740 | Key to Room 2 | 0 | - | - | - | story key item, the scripts read: given, checked and taken as in Emerald (code read, after the first candidate); in the real game (engine `a5013203`, the package's, Classic 2D test build): its Abandoned Ship door opened with it ("The inserted KEY stuck fast, but the door opened.") |
| 741 | Key to Room 4 | 0 | - | - | - | story key item, the scripts read: given, checked and taken as in Emerald (code read, after the first candidate); in the real game (engine `a5013203`, the package's, Classic 2D test build): its Abandoned Ship door opened with it ("The inserted KEY stuck fast, but the door opened.") |
| 742 | Key to Room 6 | 0 | - | - | - | story key item, the scripts read: given, checked and taken as in Emerald (code read, after the first candidate); in the real game (engine `a5013203`, the package's, Classic 2D test build): its Abandoned Ship door opened with it ("The inserted KEY stuck fast, but the door opened.") |
| 743 | Meteorite | 0 | FormChange | - | - | Form items self-test (engine `993496aa`, after the first candidate) |
| 744 | Magma Emblem | 0 | - | - | - | story key item, the scripts read: given, checked and taken as in Emerald (code read, after the first candidate) |
| 745 | Contest Pass | 0 | - | - | - | story key item, the scripts read: given, checked and taken as in Emerald (code read, after the first candidate) |
| 746 | Parcel | 0 | - | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 747 | Secret Key | 0 | - | - | - | not obtainable in this game: only Kanto's maps give it, and no map, warp or script of this game reaches Kanto (after the first candidate) |
| 748 | Bike Voucher | 0 | - | - | - | not obtainable in this game: only Kanto's maps give it, and no map, warp or script of this game reaches Kanto (after the first candidate) |
| 749 | Gold Teeth | 0 | - | - | - | not obtainable in this game: only Kanto's maps give it, and no map, warp or script of this game reaches Kanto (after the first candidate) |
| 750 | Card Key | 0 | - | - | - | not obtainable in this game: only Kanto's maps give it, and no map, warp or script of this game reaches Kanto (after the first candidate) |
| 751 | Lift Key | 0 | - | - | - | not obtainable in this game: only Kanto's maps give it, and no map, warp or script of this game reaches Kanto (after the first candidate) |
| 752 | Silph Scope | 0 | - | - | - | GBA tests that name it: 2 passed; not obtainable in this game: only Kanto's maps give it, and no map, warp or script of this game reaches Kanto (after the first candidate) |
| 753 | Tri-Pass | 0 | - | - | - | not obtainable in this game: only Kanto's maps give it, and no map, warp or script of this game reaches Kanto (after the first candidate) |
| 754 | Rainbow Pass | 0 | - | - | - | not obtainable in this game: only Kanto's maps give it, and no map, warp or script of this game reaches Kanto (after the first candidate) |
| 755 | Tea | 0 | - | - | - | not obtainable in this game: only Kanto's maps give it, and no map, warp or script of this game reaches Kanto (after the first candidate) |
| 756 | Ruby | 0 | - | - | - | not obtainable in this game: only Kanto's maps give it, and no map, warp or script of this game reaches Kanto (after the first candidate) |
| 757 | Sapphire | 0 | - | - | - | not obtainable in this game: only Kanto's maps give it, and no map, warp or script of this game reaches Kanto (after the first candidate) |
| 770 | Scroll of Darkness | 0 | EvolutionStone | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 771 | Scroll of Waters | 0 | EvolutionStone | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 772 | Tera Orb | 0 | - | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |
| 813 | Glimmering Charm | 0 | - | - | - | not obtainable in this game: nothing gives, sells or drops it (the scripts, the maps, the marts, the PC game's shops, wild Pokemon) (after the first candidate) |

