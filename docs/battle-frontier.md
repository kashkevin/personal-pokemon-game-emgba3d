# The cooperative Battle Frontier (Update 8)

**Status: built and tested in the cloud only (simulated); never played on a PC.** Engine `multiplayer_ladder.[ch]`, app
`frontier.py`, `frontier_service.py`, `coop_code.py`.

## What the players get
PLAYERS > World and my base > **Battle Frontier**. A host-formed team of two starts a **run**: rounds of real native co-op
battles (the same battle as a co-op Gym, with the same synchronisation, 2-core relay and interrupted-battle recovery) against
**pairs of in-game trainers**. Each round the page shows the opponents, their level and the prize; **Start round N** issues
the battle, both players accept it and Enter from PLAYERS > Challenges as for any native battle.
* A win clears the round (streak +1, prize); then start the next round or **Retire** (the streak is kept). A loss or a draw
  ends the run. A battle that never started (declined, expired, host restart before it began) changes nothing and the round
  is offered again.
* **Team selection:** the team is the host-formed pair (PLAYERS > player > Invite to team); each trainer brings the Pokémon
  in their *saved party*, at most `party_limit` (default 3, 1-6 in `<world>.frontier.json`); eggs do not count. Choose by
  arranging your party (deposit the others) and saving. Picking a subset from a larger party inside the battle is not
  possible (see "Not built").
* **Level scaling:** the opposing parties are cut to three Pokémon each and every Pokémon is set to the round's level (full
  HP, stats recomputed): the weaker player's average level + (round - 1) + 2 per finished set of 7. So a level-20 team and a
  level-60 team both face the whole ladder at their own level.
* **Increasing difficulty:** set 1 draws Gym Leader pairs, set 2 Juan, the Elite Four and Archie, set 3 and on the Champions
  and the Elite Four; every 7th round is a Frontier Brain pair (Tucker & Spenser, Greta & Noland, Lucy & Brandon, Anabel &
  Wallace). The draw is seeded per run, the same for both players and across a host restart.
* **Rewards:** money to each player for each cleared round: level x 25 x (2 + set) / 2, tripled for a Brain; in full the first
  time that player reaches that round, a tenth when repeated. Paid through the wallet adjustments (exactly once per save).
  No experience (as in the Battle Frontier). Records per player: best streak, runs, rounds won, money earned.

## Why a reward cannot be doubled or lost
1. The host writes the battle's **outcome durably before the battle closes** (`BattleDesk.on_publish`; co-op results are not
   in the PvP archive). A failed write keeps the battle open for the exact retry.
2. `settle` moves an attempt from `issued` to `won`/`lost` once, in one transaction with the run's round and the players'
   records. A repeated or contradicting result finds the attempt settled and changes nothing.
3. The prize is queued with `Wagers.grant(player, amount, battle_id)`: one wallet row per (player, battle). A crash between
   paying the first and second player, a restart, a reconnect or repeated reads only complete the missing payment.
4. A voided battle can never pay, even if a result for it appears later.

## Recovery
All state is in the world's SQLite file. `reconcile()` runs at every status read, when a co-op battle closes and every 5 s;
it settles results, voids battles proven never started (no reservation, no consent, or an aborted terminal) and pays what is
owed. An interrupted battle is recovered by the existing native recovery; the run waits.

## Not built (and why)
* **Choosing a subset of a larger party inside the battle.** The native battle presents the whole saved party and the host
  checks its CRC at every step; a subset would change the party blocks every core sends and the host's canonical comparison,
  the journal and the replay. That is a change to the native battle protocol, not to the Frontier; recorded for Opus-level
  design (ledger, Update 8).
* **Items or Battle Points as prizes.** Only money has a delivery channel (wallet adjustments). Items would need a new
  engine channel; money is what the Frontier pays.
* The Brains/pairs are existing trainers (no new storyline); their parties and AI are the game's own at the scaled level.

## Defaults the owner may change
Party limit 3; prize formula and the 10% repeat rate; no experience; a draw ends the run; a battle that starts and is then
aborted without a result is voided (no penalty). All are constants in `frontier.py` / `frontier_service.py`.
