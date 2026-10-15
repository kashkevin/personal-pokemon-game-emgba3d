# The cooperative Pokémon League (Update 10)

**Status: built and tested in the cloud only (simulated).** It reuses the Battle Frontier's machinery
(`docs/battle-frontier.md`): the host's durable run/attempt book, the native co-op battle, the wallet, reconciliation.

## What the players get
PLAYERS > World and my base > Frontier and League > **Pokémon League**. A host-formed team of two, **each with all 8 Gym
badges** (read from each player's last saved game), challenges the League together:

| Round | Opponents (co-op, three Pokémon each, their own levels) | Prize to each player |
| --- | --- | --- |
| 1 | Elite Four Sidney & Phoebe | $4,000 |
| 2 | Elite Four Glacia & Drake | $6,000 |
| 3 | Champion Wallace & Steven | $12,000, plus $20,000 the first time that player clears the League |

* Each round is a real native co-op battle (same synchronisation, recovery and 2-core relay as a co-op Gym). Parties are
  restored exactly after every battle (the host's invariant), so there is no attrition between rounds.
* A loss or a draw ends the run (the League starts over, as after a whiteout); a battle that never started changes nothing.
* **Individual progress:** per player, host-side and durable: clears, best round, first and last clear, money. A veteran who
  helps a newcomer gets a tenth of the prizes, the newcomer their own first-time prizes and bonus. **Experience** is awarded in the
  League's battles while at least one of the two is clearing it for the first time (the host sets it per battle).
* **Hall of Fame:** every cleared run is entered once with the team's names and the party as last saved (page "Cleared Nx" > Hall of Fame).
* **No duplicated rewards:** the same ledger as the Frontier: outcome durable before the battle closes, one settlement per
  attempt, one wallet row per (player, battle), payment and Hall entry completed (never repeated) after a crash.

## What it does not touch
The Emerald story, the Elite Four rooms, the Hall of Fame machine and `FLAG_SYS_GAME_CLEAR` in anyone's save. The co-op League is an
extra way to fight the same trainers; each player still beats the League alone in their own game for their own story.

## Choices the owner may change
The partner for Wallace (Steven, the previous Champion), the prizes and the first-clear bonus, the 8-badge requirement, the
experience rule, three Pokémon per trainer, a draw ending the run. Constants in `frontier.py` (`LEAGUE`, `LEAGUE_PRIZES`).

## Endgame audit (what exists, what has no specification)
Vanilla and unchanged: the Battle Frontier facilities, Mossdeep/Steven's postgame, Sky Pillar, the Regis, Southern Island, the
Game Corner, the Shiny Charm (Mauville prize), Mega Ring and Stones. Missing and **unspecified** (no spec beyond a name in the
checklist: "expanded endgame systems"): none were invented. Personal static legendaries still need a ticket path (owner decision 11).
