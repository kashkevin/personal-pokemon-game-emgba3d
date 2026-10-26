# Game Corner casino economy (the owner's request of 2026-10-26)

The PC game's Slot Machines and Roulette were rebalanced so that a player earns about **15,000 net coins in 30 minutes** at each,
after the cost of every bet. Only coins changed: the bet costs and what a win pays. The bets themselves (1 to 3 tiles at the Slot
Machines; one bet of the table's minimum on a colour row, a Pokemon column or a single square at the Roulette), the tables, the
prizes and every prize-counter and coin-pack price are as they were (the Game Corner's own prices were cut to 15% on 2026-10-25
and are not touched here). The numbers live in the engine's `include/platform/casino_rates.h`; the GBA game keeps its own.

Engine commit: see `KNOWN_ISSUES.md` MS-84 to MS-86 and `TEST_LEDGER.md`. Not verified on Windows or on a real PC; every number
below comes from the Linux test builds and the simulations named in "How it was tested".

## The player the earnings are for

A number of coins in 30 minutes needs a player, so these are the reference players (their times are in `tools/pc_port/casino_econ.py`):

- **Slot Machines**: bets all three tiles with R, presses A for each reel half a second after the one before, and presses START
  when the win fanfare is over to take the payout without watching it counted (the game's own shortcut). About 5.2 seconds a spin,
  349 spins in 30 minutes. A player who holds A instead earns 8,088 and one who watches it counted 5,774, because counting a coin
  takes 5 or 9 frames and the payouts are now large.
- **Roulette**: places one bet a ball on anything open (the earnings do not depend much on what), 6 balls a round. A ball takes
  about 35 seconds on the left table because the payout is counted at 4 frames a coin with no way to skip it (a 2,400-coin win is
  2 minutes 40 seconds). A player who bets on the best odds each ball earns about 13% more.

Neither player is every player: how fast one presses, whether one knows START, and which machine one sits at (the six machines
differ in their luck: 9,776 to 23,064 for the same slot player) move the numbers.

## 1. to 5. Slot Machines

Bet cost per bet tile: 1 -> 5 coins (bets of 1, 2, 3 tiles: 1, 2, 3 -> 5, 10, 15).

| Result | Old pay | New pay | Net profit with 1/2/3 tiles bet (old) | Net profit with 1/2/3 tiles bet (new) | Per spin at 3 tiles |
|---|---:|---:|---|---|---:|
| Cherry (middle row) | 2 | 25 | +1 / +0 / -1 | +20 / +15 / +10 | 0.0229 lines |
| Cherry (top/bottom row) | 4 | 50 | +3 / +2 / +1 | +45 / +40 / +35 | 0.0521 lines |
| Replay | free spin | free spin | the bet is kept for the next spin | the bet is kept for the next spin | 0.0602 |
| Lotad | 6 | 75 | +5 / +4 / +3 | +70 / +65 / +60 | 0.0695 lines |
| Azurill | 12 | 150 | +11 / +10 / +9 | +145 / +140 / +135 | 0.0174 lines |
| Pikachu Power | 3 | 40 | +2 / +1 / +0 | +35 / +30 / +25 | 0.0279 lines |
| Mixed 7s | 90 | 1,800 | +89 / +88 / +87 | +1,795 / +1,790 / +1,785 | 0.0039 lines |
| Red 7s | 300 | 6,000 | +299 / +298 / +297 | +5,995 / +5,990 / +5,985 | 0.0035 lines |
| Blue 7s | 300 | 6,000 | +299 / +298 / +297 | +5,995 / +5,990 / +5,985 | 0.0032 lines |

Coins lost by a spin that wins nothing: 1 tile: 1 -> 5, 2 tiles: 2 -> 10, 3 tiles: 3 -> 15.

| Player | Bet | Old: net / 30 min | New: net / 30 min | New: spins / 30 min | New: expected net a spin |
|---|---|---:|---:|---:|---:|
| START skips the count | 1 | 38 | 4,143 | 356 | +11.6 |
| START skips the count | 2 | -243 | 3,383 | 355 | +9.5 |
| START skips the count | 3 | 115 | 15,525 | 349 | +44.4 |
| holds A while it counts | 1 | 38 | 3,326 | 286 | +11.6 |
| holds A while it counts | 2 | -247 | 2,630 | 276 | +9.5 |
| holds A while it counts | 3 | 114 | 8,088 | 182 | +44.4 |
| watches it count | 1 | 38 | 2,828 | 243 | +11.6 |
| watches it count | 2 | -242 | 2,192 | 230 | +9.5 |
| watches it count | 3 | 109 | 5,774 | 130 | +44.4 |

The six machines, three tiles, START: 9,776, 11,400, 13,476, 16,556, 18,811, 23,064.

## 1. to 5. Roulette

| Table | Old minimum bet (cost of every ball) | New minimum bet |
|---|---:|---:|
| Left table | 1 | 25 |
| Right table | 3 | 50 |
| Left table, special rate | 1 | 25 |
| Right table, special rate | 6 | 100 |

What a winning ball pays (the multiplier on the board when the bet is placed; a bet on a closed row or column pays 0):

| Bet on | Multiplier (old -> new) | Left table: pays (old -> new), net profit (new) | Right table: pays (old -> new), net profit (new) | Left table, special rate: pays (old -> new), net profit (new) | Right table, special rate: pays (old -> new), net profit (new) |
|---|---|---|---|---|---|
| Colour row (4 squares), none of its squares hit yet | x3 -> x36 | 3 -> 900, +875 | 9 -> 1,800, +1,750 | 3 -> 900, +875 | 18 -> 3,600, +3,500 |
| Colour row, 1 square hit | x4 -> x48 | 4 -> 1,200, +1,175 | 12 -> 2,400, +2,350 | 4 -> 1,200, +1,175 | 24 -> 4,800, +4,700 |
| Colour row, 2 squares hit | x6 -> x72 | 6 -> 1,800, +1,775 | 18 -> 3,600, +3,550 | 6 -> 1,800, +1,775 | 36 -> 7,200, +7,100 |
| Colour row, 3 squares hit | x12 -> x96 | 12 -> 2,400, +2,375 | 36 -> 4,800, +4,750 | 12 -> 2,400, +2,375 | 72 -> 9,600, +9,500 |
| Pokemon column (3 squares), none hit yet | x4 -> x48 | 4 -> 1,200, +1,175 | 12 -> 2,400, +2,350 | 4 -> 1,200, +1,175 | 24 -> 4,800, +4,700 |
| Pokemon column, 1 square hit | x6 -> x72 | 6 -> 1,800, +1,775 | 18 -> 3,600, +3,550 | 6 -> 1,800, +1,775 | 36 -> 7,200, +7,100 |
| Pokemon column, 2 squares hit | x12 -> x96 | 12 -> 2,400, +2,375 | 36 -> 4,800, +4,750 | 12 -> 2,400, +2,375 | 72 -> 9,600, +9,500 |
| A single square (not yet hit) | x12 -> x96 | 12 -> 2,400, +2,375 | 36 -> 4,800, +4,750 | 12 -> 2,400, +2,375 | 72 -> 9,600, +9,500 |

The chance of a hit on the first ball of a round: a colour row 4 in 12, a Pokemon column 3 in 12, a single square 1 in 12; a slot is never hit twice in a round, so every ball after the first is likelier to hit what is left.

A ball that misses loses its minimum bet: Left table: 1 -> 25, Right table: 3 -> 50, Left table, special rate: 1 -> 25, Right table, special rate: 6 -> 100.

| Player | Table | Old: net / 30 min | New: net / 30 min | New: balls / 30 min | New: expected net a ball | New: pay-out ratio |
|---|---|---:|---:|---:|---:|---:|
| bets on anything open, each ball | Left table | 40 | 14,994 | 52 | +288 | 12.51 |
| bets on anything open, each ball | Right table | 120 | 18,701 | 32 | +576 | 12.51 |
| bets on anything open, each ball | Left table, special rate | 40 | 14,994 | 52 | +288 | 12.51 |
| bets on anything open, each ball | Right table, special rate | 235 | 21,338 | 19 | +1,151 | 12.51 |
| bets on the best odds, each ball | Left table | 88 | 16,960 | 42 | +400 | 17.00 |
| bets on the best odds, each ball | Right table | 259 | 20,343 | 25 | +800 | 17.00 |
| bets on the best odds, each ball | Left table, special rate | 88 | 16,960 | 42 | +400 | 17.00 |
| bets on the best odds, each ball | Right table, special rate | 506 | 22,597 | 14 | +1,600 | 17.00 |


## Limits of these numbers

- **9,999 coins at a table.** The Slot Machine's credit and a Roulette table's hold 9,999 coins; a win that would pass it is
  cut off at 9,999 (the game then says its coin case is full). A 6,000-coin jackpot is cut if the machine already holds more than
  3,999 coins, a 2,400 win at the left roulette table above 7,599, and the right table's special-rate 9,600 above 399. The earnings
  above assume the player leaves a table before that and the rest of the wallet waits in reserve, as it does since Update 29. This
  was seen in the real game: a run that started with 5,000 coins stopped at 9,999 after its first 6,000-coin jackpots.
- **Payout counting.** The Roulette counts a payout at 4 frames a coin and cannot skip it, so earning 15,000 coins takes about
  18 of the 30 minutes watching coins count. The Slot Machine counts at 9 frames a coin (5 with A held) and skips with START.
  Speeding the Roulette up is not a bet cost or a payout and was not done.
- **The classic 2D Slot Machine's information panel (SELECT)** is a picture and still lists the old payouts (2, 4, 3, 6, 12,
  90, 300). The 3D game's own panel lists the new ones. The classic 2D Roulette's multiplier picture was redrawn (x36, x48, x72,
  x96) and checked in the real game.
- **Bets of 1 and 2 tiles** pay less than 3 tiles (as in the original): 4,143 and 3,383 net coins in 30 minutes for the
  START player.
- **A top or bottom row cherry** pays 50 and is not on the 3D payout panel (it was not on the original's either).

## How it was tested

- `tools/pc_port/casino_econ.py` (`make -f Makefile_pc check-casino`): the Slot Machine's own code (`src/slot_machine.c`, run
  by `tools/pc_port/casino_sim/slot_sim.c`: the bias draws, where the reels stop, the lines, Replay, ReelTime) for 2,000,000 spins a bet
  size and machine, and the Roulette's rules (12 slots, 6 balls, a slot never hit twice, the multipliers) for 60,000 rounds
  of 6 balls each. Exit 1 when either reference earning leaves 15,000 by more than 10%.
- 2,517 spins of the real game (the Linux 2D test build, random press timing): every paid spin cost 5 coins a tile
  (2,183 checked, none wrong); every win paid exactly the table's value; 19.1% of spins won against 18.7% simulated; each
  payout value was seen about as often as simulated (within 2 standard deviations, except Pikachu Power, 94 against 66: that
  machine's game was a lucky one, which raises it; the difference is worth under 1% of the earnings); 13 jackpots against 15.9
  expected. Only the first 5 seconds of a spin were timed in the real game (the machine's own frame counts); the player's
  reaction times are modelled.
- 90 Roulette balls of the real game on the left table: the coins after each ball were exact (bet taken, payout x minimum bet
  added, capped at 9,999), the multipliers and wins agreed with the model's board in all but the balls after a table was left and
  entered again, and the minimum bet text ("The minimum wager at this table is 25.") and the x36 picture were seen.
- The GBA ROM is unchanged (sha256 `f214735b64e113fd10730eacca5764d757f2c93a3685230aa905af7a7cdd3387`; `check_gba_lines.py`).
