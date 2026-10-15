# The cooperative Battle Frontier (Update 8, completed in Update 16)

**Status: built and tested in the cloud only (simulated); never played on a PC.** Engine `multiplayer_ladder.[ch]`, app
`frontier.py`, `frontier_service.py`, `frontier_rewards.py`, `rewards.py`, `coop_code.py`.

## What the players get
PLAYERS > World and my base > **Battle Frontier**. A host-formed team of two starts a **run**: rounds of real native co-op
battles (the same battle as a co-op Gym, with the same synchronisation, 2-core relay and interrupted-battle recovery) against
**pairs of in-game trainers**. Each round the page shows the opponents, their level and the prize; **Start round N** issues
the battle, both players accept it and Enter from PLAYERS > Challenges as for any native battle.
* A win clears the round (streak +1, prize); then start the next round or **Retire** (the streak is kept). A loss or a draw
  ends the run. A battle that never started (declined, expired, host restart before it began) changes nothing and the round
  is offered again.
* **Team selection (Update 16):** the team is the host-formed pair (PLAYERS > player > Invite to team); each trainer brings at
  most `party_limit` Pokémon (default 3, 1-6 in `<world>.frontier.json`); eggs never count. A party of at most that many
  fights as it is. With a **larger party** you choose who fights: PLAYERS > World and my base > Frontier and League > Battle
  Frontier > *Team, BP shop* > *Team* (tap a Pokémon to bring it; a full team gives up its first member). Your choice is kept
  between rounds and runs; if your party changed so that it no longer fits, the first `party_limit` Pokémon go (one able to
  fight). The battle takes the chosen Pokémon in saved order; **your full party is restored exactly afterwards** (nothing is
  deposited or lost) and the host's canonical comparison covers the chosen team. See "How the team selection works".
* **Level scaling:** the opposing parties are cut to three Pokémon each and every Pokémon is set to the round's level (full
  HP, stats recomputed): the weaker player's average level + (round - 1) + 2 per finished set of 7. So a level-20 team and a
  level-60 team both face the whole ladder at their own level.
* **Increasing difficulty:** set 1 draws Gym Leader pairs, set 2 Juan, the Elite Four and Archie, set 3 and on the Champions
  and the Elite Four; every 7th round is a Frontier Brain pair (Tucker & Spenser, Greta & Noland, Lucy & Brandon, Anabel &
  Wallace). The draw is seeded per run, the same for both players and across a host restart.
* **Rewards:** money to each player for each cleared round: level x 25 x (2 + set) / 2, tripled for a Brain; in full the first
  time that player reaches that round, a tenth when repeated. **Battle Points (Update 16):** each player also gets BP for a
  cleared round (1 + set/2 for a normal round, 3 + 2 x set for a Frontier Brain round; half when repeated, at least 1), added to
  the Battle Points of *their own save* (`frontier.battlePoints`, the same counter the game's Battle Frontier Exchange Service
  Corners spend, capped at 9999). **Item prize:** the first time a player clears a Brain round they also get an item (set 1
  Rare Candy, set 2 PP Up, set 3 2 Max Revive, set 4 2 Rare Candy, then repeating), into the bag, else the PC's item storage.
  All paid through the same numbered wallet stream as money (exactly once per save). No experience (as in the Battle Frontier).
  Records per player: best streak, runs, rounds won, money earned, BP earned/spent.
* **Battle Points shop (Update 16):** *Team, BP shop* > *BP shop*: Protein, Iron, Calcium, Zinc, Carbos and HP Up cost 16 BP,
  Quick Claw, King's Rock and Focus Band 32, Leftovers 48, Choice Band 64. Buying first **takes the points from your save**
  (the game reports how many it really took), then gives the item; if your save had fewer points than the host's last-save
  view the partial points are returned and nothing is bought; if the bag and the PC cannot hold the item the points come
  back. One purchase at a time per player. You can also spend the same Battle Points at the game's own Exchange Service
  Corners in the Battle Frontier.

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

## How the team selection works (engine and host)
* The host stores each player's selection (`frontier_bring`) and validates it against the player's latest save (slots exist,
  no Egg, one able to fight, at most `party_limit`). When a round is issued it is part of the battle: `BattleDesk.invite_coop(...,
  brings=)`, the consent fingerprint names it, the roster (`CanonicalBattler.bring`) and the durable reservation keep it
  (`brings`), so a host restart or a recovery replays the identical team.
* The native preparation carries it in the **last byte of the seed** (`0x80 | slot mask`, or 0 for the whole party). The game
  reads and clears that byte before seeding, so every core still seeds identically (the opposing parties are generated from the
  seed). `PrepareSingles` checks the selection (`BringSelectionValid`), saves the original party exactly as before, then reduces
  the live party to the chosen Pokémon in saved order (`ApplyBringSelection`); `StartSingles` compares the reduced party's CRC;
  the end of the battle restores the original party with `RestorePlayerPartyExact`, unchanged. Co-op experience (League first
  clears) maps the battle's party slots back to the saved slots (`MultiplayerCoop_RemapBringSlots`).
* The code exists in the PC build and the GBA test ROM only (`MP_BRING_ENABLED`); the release GBA ROM stays byte-identical.

## Not built (and why)
* **Choosing inside the battle** (after it starts): the selection is made before each round, as in the Battle Frontier.
* **Item and BP prizes for the League:** the League stays money-only (its own first-clear bonus and Hall of Fame).
* **A BP balance read from the live game:** the page shows the Battle Points of your *last save*; the shop checks the live save
  itself at purchase time (the debit-first rule above).
* The Brains/pairs are existing trainers (no new storyline); their parties and AI are the game's own at the scaled level.

## Defaults the owner may change
Party limit 3; prize formula and the 10% repeat rate; the BP formula, the item prize table and the shop catalogue/prices
(`frontier_rewards.py`); no experience; a draw ends the run; a battle that starts and is then aborted without a result is voided
(no penalty). All are constants in `frontier.py` / `frontier_rewards.py` / `frontier_service.py`.
