# Write-ups for the owner, 2026-11-05: MS-85, MS-149, U31-5, Battle Points, MS-9

For the owner's requests of 2026-11-05 (`docs/owner-decisions.md` #46, #48, #49): the exact descriptions and proposed
resolutions of MS-85, MS-149 and U31-5; a review of the Battle Points earned per hour, prices kept; and whether the
emulator's Lua fallback (MS-9) is needed at all.

**Nothing in the game, the app or the records was changed for this write-up. Every resolution below is a proposal; the
owner decides.**

Code is cited as it stands: the app at `c53e633` (paths without a prefix), the engine at `0d25e9c0` (paths starting
`engine:`); a bare file name is an app module in `src/emerald_multiplayer/` or a file whose full path was given above it. **Measured** = a run recorded in
`TEST_LEDGER.md`; **assumed** = an estimate made here, basis given. L = this Linux machine, W = GitHub's Windows runners.

## Summary

| Item | Today | Proposal |
| --- | --- | --- |
| MS-85: casino wins past 9,999 coins | Fixed on 2026-10-26 (the owner's "no cap"): no win is cut. The 3D tables show the whole Coin Case; the Classic 2D tables' four digits stop at 9,999 while the rest is kept | Close as fixed; correct stale records; add the banking to a self-test so Windows checks it |
| MS-149: a throw at catch odds 0 | About 1 catch in 64,500 throws (a Heavy Ball on a light Pokemon of catch rate 21 or less); no undefined division since `6a575072` | Close: the owner decided on 2026-10-27 to keep these odds; correct the row's numbers |
| U31-5: the original rival in Match Call | The Rustboro pass registers May or Brendan, as the original scene does | Keep; close as by design |
| Battle Points | 751 BP once from the Tower; about 7-43 BP an hour from the co-op Frontier; 5-30 from the game's own Frontier | No change needed |
| MS-9: the emulator's Lua bridge | Not shipped, not offered, not used by any supported path or CI job | Not needed: close as "fallback not shipped"; removal optional later |

## 1. MS-85: casino wins past 9,999 coins

Records: `KNOWN_ISSUES.md:432` (no later row); `docs/outstanding-issues.md:254` still lists it as an owner's call.

**What happens today** (engine `cc43a414`, the owner's "no cap" of 2026-10-26; engine `ef762adc`, MS-100):

- A Slot Machine or Roulette table plays a *stake*: the whole Coin Case below 9,999 coins, else 5,000; the rest waits in
  a reserve. The save is touched only when the player leaves the table, as on the GBA
  (`engine:include/platform/coin_wallet.h:3-12`, `engine:src/platform/coin_wallet.c:10-21`).
- The table's credit still stops at 9,999 (the GBA's four digits), but what a win brings past it goes into the reserve
  instead of being cut (`engine:src/slot_machine.c:2214-2225`; `engine:src/roulette.c:1903-1917`, `1949-1960`), and
  neither table stops there any more: the slot's "You've got 9,999 COINS." and the roulette's "Your COIN CASE is full!"
  are skipped on PC (`engine:src/slot_machine.c:1390-1397`; `engine:src/roulette.c:2021-2032`, `2067-2072`). Leaving
  writes reserve plus credit to the Coin Case, at most 999,999 (`coin_wallet.c:30-33`).
- **What the player sees.** In the 3D game (the default) both tables show COINS in six digits, stake and reserve
  together, counting with every bet and payout (`engine:src/native_ui/screens/ui_slot_machine.c:346-347`,
  `engine:src/native_ui/screens/ui_roulette.c:325`). In the Classic 2D game the tables are the GBA's: CREDIT shows the stake plus winnings, at most
  9,999 (`engine:src/slot_machine.c:4231-4242`, `engine:src/roulette.c:3791-3810`), so a Coin Case of 30,000 reads 5,000
  there; the true total shows in the Coin Case on leaving.
- **Checked:** L only, in the real game: from 9,990 coins, 20 slot wins balanced exactly (a 6,000 jackpot at 9,865 put
  5,866 in the reserve) and a 2,400 roulette win put 1,991 in it (`KNOWN_ISSUES.md:432`). No automated test calls
  `CoinWallet_Bank`: `--selftest-coins`, in the Windows self-test job (`.github/workflows/windows-package.yml:1700-1707`),
  covers the Coin Case, the stake and the 999,999 ceiling, not the banking.
- **Edge at the top:** past 999,999 the rest of a win is lost without a message (`coin_wallet.c:40-45`,
  `engine:src/coins.c:94-104`), and a 3D Coin Case above about 990,000 can count past 999,999 at the table (drawn as its
  first six digits) until leaving cuts it back. Reaching it takes about 33 hours of casino play.

**Why it is still listed:** only the records. `docs/outstanding-issues.md:254` still asks the row's old question (cap
what a table takes?), and `FEATURE_STATUS.md:127` ("a table cuts wins above 9,999 coins"; stale for MS-84 and MS-86 too)
and `docs/casino-economy.md:99-103` still describe the cut.

**Proposed (nothing changed; the owner decides): A.**

| Option | For players | Saves | Work and tests |
| --- | --- | --- | --- |
| **A. Close as fixed** (recommended) | Nothing changes | None | The records above. Test code only: `--selftest-coins` checks a 6,000 win at 9,865 (credit 9,999, reserve +5,866), a 2,400 win at 9,590 (+1,991), leaving, and the reserve stopping at 999,999 (`AddTableCoins` is static: a test hook like `MPTest_BallShakeOdds`); the Windows self-test job then covers it |
| B. The whole Coin Case at the Classic 2D tables | Real total shown while playing in 2D | None | A PC-only six-digit coin window on two GBA screens (layout work); ROM unchanged; pictures before and after; `engine:tools/battle_env/casino_check.py` on the 2D build; Windows feature checks |
| C. A message at 999,999 | "Your COIN CASE is full" again, only at the ceiling; the 3D counter held there | None | PC-only blocks in both tables; `--selftest-coins`; a real game started near 999,999 coins (`PKMN_TEST_COINS`) |
| D. Cap what a table takes (the row's first idea) | Shorter sessions for nothing: no win is cut now | None | Not recommended |

## 2. MS-149: a Poke Ball throw at catch odds 0

Records: `KNOWN_ISSUES.md:540` (no later row; MS-148 at `:539` is its cause), `docs/item-audit-20261027.md:102-141`,
`docs/outstanding-issues.md:255`.

**What happens today:**

- Catch odds are (3 x max HP - 2 x HP) x catch rate / (3 x max HP), then ball and status multipliers, in whole numbers
  (`engine:src/battle_script_commands.c:8253-8316`). A catch rate of 1 gives odds 0 at any HP and status.
- Who reaches it: the Heavy Ball takes 20 from the catch rate of a Pokemon under 204.8 kg, at least 1 since MS-148's fix
  (`battle_script_commands.c:8269-8275`). So every light Pokemon with a catch rate of 21 or less (about 50 Gen 1-6
  species: Latias, Latios, Jirachi, Deoxys, the lake trio, Beldum, Metang...) has odds 0 against a Heavy Ball, which
  Mauville's Game Corner sells. So does a Beast Ball (x0.1) on a low catch rate: no longer sold (engine `d0d57e2a`), but
  one already owned still works.
- The shake check divides by the odds. At 0 the source writes out what the GBA's division returns, 0xFFFFFFFF
  (`battle_script_commands.c:8368-8381`), as the PC's fault handler supplied before `6a575072`. Each of the four checks
  (three shakes and the click: `battle_script_commands.c:8434-8445`, `engine:include/battle_controllers.h:190`) holds
  4,112 times in 65,536: a throw catches about **0.0015%, 1 in 64,500**. Odds 1 (a Poke Ball on a catch-rate-3 Pokemon at
  full HP) catch 0.42%, 1 in 240.
- **What the player sees:** a Heavy Ball thrown at Latias breaks open almost every time; another ball is needed.
- **Tested:** `--selftest-balls` holds the 4,112 (`engine:src/platform/native_selftest_items.c:870-875`), in the Windows
  self-test job (`windows-package.yml:1700-1707`), passed in runs 277, 288, 297, 310 and 322.

**Why it is still listed:** only the records. The owner decided on 2026-10-27 that "the odds stay as they are"
(`docs/item-audit-20261027.md:136-141`), but `KNOWN_ISSUES.md:540` still calls a minimum the owner's decision and gives the
uncorrected chances ("about 0.025%" at odds 0, "about 1.6%" for the withdrawn floor; correct: 0.0015% and 0.42%,
`docs/item-audit-20261027.md:95-101`).

**Proposed (nothing changed; the owner decides): A.**

| Option | For players | Saves | Work and tests |
| --- | --- | --- | --- |
| **A. Close as decided on 2026-10-27** (recommended) | Nothing changes | None | Records (the row's numbers corrected); the existing self-test holds the result on L and W |
| B. A minimum: odds 0 counted as 1 | Those throws catch 1 in 240 instead of 1 in 64,500 (about 270 times as often), like a Poke Ball at full HP on a catch-rate-3 Pokemon: a balance change, what `4474883b` did and `6a575072` withdrew | None; Pokemon already caught untouched | One PC-only line in `ComputeBallShakeOdds`; `--selftest-balls`'s 4,112 becomes 16,643; run before and after; the Windows self-test job |
| C. The Heavy Ball never below the species' own catch rate | No worse than a Poke Ball on light Pokemon | None | Not a Gen 4-6 rule; changes every light Pokemon under catch rate 21; not recommended |

## 3. U31-5: the original rival in Match Call

Records: `KNOWN_ISSUES.md:214` (Update 31 session, 2026-10-16; no later row), `docs/outstanding-issues.md:256`,
`docs/update31-rival-checkpoints.md:75`, `249-250`.

**What happens today:**

- In a world whose host runs rival checkpoints, the five May/Brendan battles are battles between players; the original
  rival's figure is kept away from those scenes (`engine:src/multiplayer_rival.c:486-520`). The rival stays a story
  character elsewhere: Birch's lab after Route 103, Oldale, at home after Lilycove.
- The Rustboro City / Route 104 checkpoint's personal pass (after the players' battle, a catch-up or "Continue on my own")
  runs `engine:data/scripts/mp_rival.inc:180-197`: "You met your rivals in RUSTBORO!", the Match Call jingle, "Registered
  MAY in the POKéNAV." (BRENDAN for a female player), then sets `FLAG_MET_RIVAL_RUSTBORO`, `FLAG_ENABLE_RIVAL_MATCH_CALL`,
  `VAR_RUSTBORO_CITY_STATE` 8 and `VAR_ROUTE104_STATE` 2: the original scene's effects
  (`engine:data/maps/RustboroCity/scripts.inc:874`, `942`; `engine:data/maps/Route104/scripts.inc:113`, `199`), once
  (`engine:src/multiplayer_rival.c:219-235`).
- The flag does one thing: MAY or BRENDAN ("RAD NEIGHBOR") appears in the PokeNav's Match Call list
  (`engine:src/pokenav_match_call_data.c:274-327`, `766-773`). Calling them plays one of 15 lines chosen by story progress
  (`engine:data/text/match_call.inc:2338-2461` May, `2463-2587` Brendan): tips and small talk (Mr. Briney, the Mirage
  Tower, Mt. Pyre), among them "I'm on ROUTE 119 now." after the Petalburg Gym, though in a world the rival is never seen
  there.
  The rival never calls the player: incoming calls come only from registered rematch trainers
  (`engine:src/match_call.c:1100-1131`). Nothing else reads the flag.

**Why it is open:** a design question of 2026-10-16: keep the original story's flag, as built, or remove the original
rival's entry now that the rivals are the other players.

**Proposed (nothing changed; the owner decides): A.** The rival is still a character of a world's story, the entry
gates nothing and never rings, and a save behaves the same offline and in a world.

| Option | For players | Saves | Work and tests |
| --- | --- | --- | --- |
| **A. Keep; close as by design** (recommended) | As today | None | Records only |
| B. Do not register in a world | No jingle, message or entry for characters passing Rustboro in a world after the change; earlier ones keep theirs; such a save never gets the entry offline either (its Rustboro state has passed) | Flag unset for new passes; clearing it in older saves would also remove the entry offline | `mp_rival.inc:180-197` (drop the jingle, message and flag; keep `FLAG_MET_RIVAL_RUSTBORO` and the variables), `docs/update31-rival-checkpoints.md:250`; tests: `--selftest-rival` (flag unset after a pass in a world, set by the original scene offline), `engine:tools/pc_port/rival_check.py`'s Rustboro run watching the flag; the Windows self-test and rival-check jobs; ROM unchanged (PC-only script) |
| C. Hide it while in a world | Entry gone in worlds with rival checkpoints, back offline; no "Registered" message in a world | None (flag kept; reversible) | A PC-only condition in `engine:src/pokenav_match_call_data.c:766-773` from `multiplayer_rival.c`, and `mp_rival.inc`; tests: a self-test of the list in both modes, pictures of the list in 2D and 3D; the Windows self-test job |

## 4. Battle Points: earnings per hour (prices kept)

### Every way to earn BP

All add to one counter in the save, at most 9,999 (`engine:include/constants/battle_frontier.h:51`).

| Source | Amount | First clear and repeats | Code |
| --- | --- | --- | --- |
| Co-op Battle Frontier (a team of two, from the Players menu) | To each player per cleared round, in set *s* (rounds 1-7 are set 1): 1 + floor((*s* - 1) / 2) on its rounds 1-6, 2*s* + 1 on its 7th (the Brain round) | Full above that player's best streak, half (at least 1) at or below it; nothing for a loss, a draw or a void battle; every run starts at round 1 | `frontier_rewards.py:63-68`; `frontier.py:303`, `383`, `408-416` |
| ... item prize | First clear of each Brain round: Rare Candy, PP Up, 2 Max Revives, 2 Rare Candies, repeating by set | First clear only | `frontier_rewards.py:32`, `71-75` |
| Battle Tower: Legends (solo or Duo) | Per floor: (1 + floor(floor / 10)) x 3 on floors 10, 20, 30, 40, 60, 70, 80, 90; x 4 on 25, 50, 75; x 5 on 100; x 1 on the rest. **751 BP for floors 1-100** | Each floor once per player per world; replays, re-climbs and a Duo partner's lower floor pay nothing | `tower_rewards.py:106-112`; `tower_rules.py:13-16`, `144-163` |
| The game's own Battle Frontier (seven facilities, one player) | Per completed challenge (7 battles; the Dome a tournament, the Pike 14 rooms, the Pyramid 7 floors), rising along one streak: Battle Tower singles 1, 2, 3 ... 15, doubles from 2, multis from 3; Palace from 4, Factory from 3, Pyramid from 5; +10 for a Frontier Brain | Every challenge; a loss restarts the streak | `engine:src/frontier_util.c:665-702`, `1952-2009` |
| Scott | 1-4 BP | Once | `engine:data/maps/BattleFrontier_ScottsHouse/scripts.inc:150-190` |

Co-op Frontier totals from round 1, first time: 9 (round 7), 20 (14), 39 (21), 60 (28), 89 (35), 120 (42), 159 (49);
repeated: 7, 15, 24, 34, 45, 57, 76. The Tower: 15 BP by floor 10, 90 by 30, 210 by 50, 436 by 75, 751 by 100 (every CI
climb was paid exactly 751: `TEST_LEDGER.md:568`, `571`, `1072`, `1090`).

### Durations used

- **Tower climb, measured:** each player's floors 1-100 in 179-189 minutes, two players at once (L and W, same rows). The
  fastest possible: the test build heals the lead every turn and picks its best move, with fast text, the battle scene
  off and instant key presses (`engine:include/diorama/battle_env_test.h:61-64`).
- **Tower climb, assumed for a person:** 1 minute per opposing Pokemon (456 on the 100 floors, counted from
  `tower_floors.py`) plus 1 minute a floor for menus, settlement and healing: 556 minutes, 9.3 h; a quarter more for losses
  and re-climbs: 11.6 h.
- **Co-op Frontier round, assumed:** 10 minutes (a double battle, three Pokemon a player against three a trainer, plus
  offering, accepting and entering the round and its settlement); a fast pair, 6. Never measured: no co-op Frontier round
  has been played in a real game (`TEST_LEDGER.md:209`, `618`); the nearest, a co-op Gym battle with level-60 leads, took
  299 s (`TEST_LEDGER.md:471`).
- **The game's own Battle Tower, assumed:** 30 minutes a challenge (7 three-on-three battles of about 4 minutes, the lobby
  and its save). Not measured in the PC game (`TEST_LEDGER.md:818`).

### BP per hour

| Play style | BP | Time | BP an hour |
| --- | --- | --- | --- |
| A. A new co-op pair: rounds 1-21, first time | 39 | 21 x 10 min = 3.5 h (fast: 2.1 h) | 11 (fast 19) |
| B. The same pair running rounds 1-21 again | 24 | 3.5 h (2.1 h) | 7 (11) |
| C. A strong pair: rounds 22-49 for the first time, one run | 120 | 28 x 10 min = 4.7 h (2.8 h) | 26 (43) |
| D. The Tower climb, floors 1-100, once per player per world | 751 | 9.3-11.6 h assumed; 3.0-3.2 h measured (fastest) | 65-81 (fastest 238-252) |
| E. The game's own Battle Tower, singles, one streak | 1+2+3+4 = 10; later 15 a challenge | 2 h; 30 min each | 5; from the 15th challenge 30 (+10 a Brain) |

C is hard to reach: foes are the weaker player's average level + (round - 1) + 2 per finished set, at most 100
(`frontier.py:78-80`), so a level-50 pair meets level 77 at round 22 and level 100 from round 41, and one loss sends the
next run back to round 1 at the repeat rate.

### What the items cost in hours

The host's BP shop, the Tower Shop and the game's Exchange Service Corner spend the same counter, so a player buys each
item where it is cheapest. Coin prices: the Game Corner's item hub (`engine:data/scripts/mp_item_hub_lists.inc:100`,
`119`, `121`, `123`, `203`, `372`).

| Item | BP shop (`frontier_rewards.py:51-56`) | Exchange Service Corner (`engine:data/maps/BattleFrontier_ExchangeServiceCorner/scripts.inc:231-322`) | At A (11/h): shop / corner | At B (7/h) | At D (81/h) | Coins |
| --- | --- | --- | --- | --- | --- | --- |
| Protein, Iron, Calcium, Zinc, Carbos, HP Up | 16 | 1 | 1.4 h / 5 min | 2.3 h / 9 min | 12 / 1 min | 300 |
| Quick Claw | 32 | 48 | 2.9 h / 4.3 h | 4.7 h / 7.0 h | 24 / 36 min | 2,500 |
| King's Rock, Focus Band | 32 | 64 | 2.9 h / 5.7 h | 4.7 h / 9.3 h | 24 / 47 min | 1,500; 1,000 |
| Leftovers | 48 | 48 | 4.3 h | 7.0 h | 36 min | 10,000 |
| Choice Band | 64 | 64 | 5.7 h | 9.3 h | 47 min | 10,000 |

At the casino's reference rate, about 15,000 net coins in 30 minutes (`docs/casino-economy.md:3`; more since a payout's
count can be skipped, MS-86), 300 coins take under a minute and 10,000 coins 20 minutes. The Tower Shop's dearest items,
the Ability Patch (200 BP) and the Gold Bottle Cap (192 BP; `tower_rewards.py:135-144`), are 15,000 coins each in the
rare goods (`engine:src/platform/mp_rare_goods_prices.h:54`, `86`).

### Conclusion: no change needed

1. **BP gate nothing.** Every BP shop item is also sold for coins worth minutes of casino play, and the game's corner
   sells vitamins for 1 BP. A dear price (vitamins at 16) only sends players elsewhere; the three cheaper held items (32
   against 48 or 64) save at most 32 BP, about three hours of style A, once per item.
2. **Nothing can be farmed.** The Tower pays each floor once per player per world; the co-op Frontier pays in full only
   above a player's best streak, and its repeats earn about 7-11 BP an hour.
3. **The rates sit within the game's own.** Decision #24 found "39 BP for 21 rounds" generous next to "the original's 3 BP
   per 7-win streak" (`docs/balance-and-controls-review.md:36-37`). That is not this game's figure: its Battle Tower pays
   singles 1, 2, 3 ... BP for successive 7-win challenges (3 is where multis and the Factory start:
   `engine:src/frontier_util.c:670-691`). Per hour a new co-op pair (11-19 BP) earns two to four times a new player in
   the game's Tower (5) and less than a long streak there (30). The Tower's 751 BP is the largest source, paid once.

**Revisit only if** the Game Corner's coin rates or hub prices are cut (BP would then be the cheap route to these
items), an item of real power is sold for BP alone, or timed play shows co-op rounds much faster than assumed (none has
been timed). Prices stay as they are either way.

## 5. MS-9: the emulator fallback's Lua bridge

Records: `KNOWN_ISSUES.md:306` (no later row), `docs/outstanding-issues.md:38`, `78`; `docs/owner-decisions.md` #48 ("if it
is actually needed").

**What the row says:** `bridge/mgba.lua`, the script mGBA runs in the emulator build, wants bytes 192-207 of the
shared-world record all zero (`bridge/mgba.lua:278`), so the outbreak marker the companion puts at 192
(`src/emerald_multiplayer/world_mailbox.py:321`, `companion.py:796-806`) would stop its link, as it stopped the native
bridge before MS-8's fix; it also refuses reward words (`mgba.lua:274`).

**Verdict: not needed.**

1. **Shipped? No.** The package job accepts exactly one runtime, the native game
   (`.github/workflows/windows-package.yml:2475-2480`); a native runtime may not hold a `.lua` file
   (`src/emerald_multiplayer/player_runtime.py:238-240`); the launcher build packs the app's Python, not `bridge/`
   (`scripts/windows-runtime/build_launcher.py:300-341`). Run 322's installer holds the 3D and Classic 2D native games
   (`docs/package-20261105d.md:35-40`).
2. **Offered by the launcher? No.** Graphics mode picks one of the two native games (`graphics_mode.py:1-19`); the runtime
   is the one the release record pins (`launcher_gui.py:217-226`); an emulator runtime would also need the GBA ROM, which
   a packaged installation lacks (`player_runtime.py:361-363`). The owner's fallback for an old graphics card is the
   Classic 2D game (`docs/owner-decisions.md:12`).
3. **Used by a supported path? No.** Hosting, joining, battles, trades, the Tower and the Frontier run the native game's
   own bridge (`engine:src/platform/mp_bridge.c`). No workflow builds or runs mGBA; the one mention lets the Lua tests
   skip on Windows (`windows-package.yml:1478-1483`).
4. **Required by a test or document as a fallback? Only on paper.** Ten app test files run `bridge/mgba.lua` under Lua
   against a stand-in emulator (60 `run_lua` calls, e.g. `tests/test_live_bridge.py:101-120`; also
   `tests/test_mgba_bridge.lua`); without Lua 5.3+ they skip (119 skips in Windows run 311,
   `docs/outstanding-issues.md:164`). They test the script, not a path a player can take. The documents that still call
   the emulator build the fallback are the plan of 2026-10-09 (`AGENTS.md:21-22`, `39`; `ARCHITECTURE.md:7`;
   `PROJECT_SPEC.md:408`; `DEVELOPMENT_ROADMAP.md:64`, `304-310`, `416-424`, whose 6.3 says the Windows emulator runtime
   was never rebuilt). That fallback is the frozen tag `emulator-baseline-20261009` (app `7240c81`, engine `761c9c27f`;
   `CHECKPOINTS.md:9`): a rollback point whose own host never sends what its own bridge refuses (the outbreak marker and
   reward words came on 2026-10-15, Updates 18 and 16; the tag's `world_mailbox.py` has neither).
5. **It could not stand in for this game.** The GBA ROM an emulator runs is byte-identical to the 2026-10-09 baseline
   (sha256 `f214735b...3387`, checked by every engine job: `docs/package-20261105d.md:47`): the Tower, the co-op Frontier,
   rival checkpoints, the casino rates, the item hub and the TM catalogue are all PC-only. And the current Lua bridge
   refuses more than the row says: the outbreak marker and the rival record (`mgba.lua:278`), every reward word (BP,
   items, Tower words, a World Event catch kept or released: `mgba.lua:274` against `rewards.py:3-24`), and another
   player surfing on their own Pokemon (mount state 2, since 2026-10-27: `mgba.lua:259` against `world_mailbox.py:33`).
   Each stops its link: "invalid shared-world update" (`mgba.lua:877`).

**Proposed (nothing changed; the owner decides): close MS-9 as "not needed: the emulator fallback is not shipped or
offered".** No code change. In the records, call the emulator build a frozen rollback point (the tag), not a maintained
fallback, and close the roadmap's A16, G1-G3 and 6.3 as superseded: the native build is the only one tested since, its
whole gameplay plan included (3,612 targets in 3D on Windows, run 308: `docs/outstanding-issues.md:160-161`).

**Removing it later (optional; nothing is broken):** delete `bridge/mgba.lua` and `tests/test_mgba_bridge.lua`; drop or
port the Lua cases of the ten test files (the native bridge's rules are tested in
`engine:tools/pc_port/tests/test_mp_bridge.c`, 4,581 checks at MS-12's fix; port any case it lacks); remove the
`emerald-windows-runtime-v1` format from `player_runtime.py` (`208`, `241-244`, `361-363`, `380-382`), `configure` in
`bridge_config.py:124` and the mGBA key help (`launcher_gui.py:1681-1683`); retire the emulator's frontend
(`native/windows-runtime/sdl-multiplayer.c`, `scripts/windows-runtime/prepare_frontend.py`, `mgba-sdl.exe` in
`scripts/windows-runtime/collect_bundle.py`), `scripts/windows-runtime/smoke_player_runtime.py`, the six
`scripts/windows-runtime/qualify_*.py` that stage `mgba.lua`, and the `bridge/mgba.lua` default of 20 emulator-era proofs
in `scripts/multiplayer`. Keep the trade replay worker and its build (`native/windows-runtime/trade-replay-worker.c`,
`scripts/windows-runtime/build_runtime.sh`, `trade_native_replay.py`): it runs a headless mGBA core, not the Lua bridge
(`build_launcher.py:214-217`). Tests: the whole app suite on L and in the Windows `app-tests`
job, then a full package run.

**If the owner wanted the fallback anyway (not recommended):** make `mgba.lua` accept what the native bridge accepts
(`engine:src/platform/mp_bridge.c:284-303`, `349-369`: the outbreak marker, the rival record, reward words, mount state
2), or have the companion keep PC-only data from an emulator game; audit every other frame against the native validators
as MS-8, MS-10 and MS-11 did; rebuild the Windows emulator runtime (roadmap 6.3); test each case in the Lua tests (failing
before, passing after) and a real mGBA game through the launcher during an outbreak. Even then the emulator would run the
2026-10-09 game, without the PC-only features.
