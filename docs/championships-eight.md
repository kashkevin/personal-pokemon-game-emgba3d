# Eight-place Championships with computer trainers (step 18)

The owner's choice of 2026-11-03 ([owner decisions](owner-decisions.md) #32, "Computer trainers (Recommended)"):

> Battle Frontier trainers under the same entry rules fill the empty places. A player against one is a normal battle in
> that player's own game. Two players still use the existing challenge flow. If two computer trainers meet, the
> higher-ranked one goes through without a battle. Bracket 8 → 4 → final.

The world stays at four players. Engine `a978b0c5` and `2550e1ba` (the game's bridge takes the new command), app
`3851488`, `eb0680a` (the battle connection takes protocol version 2), `7ee7dff` (PLAYER reopens on the bracket) and this record's (the menu's texts within the status line). Engine `ec53763a`: a battle between players starts with a fresh game's battle text buffers (KNOWN_ISSUES MS-180, found by the final's proof).
PC only; the GBA ROM is unchanged (`f214735b…3387`).
The four players' bracket of before is still described in [championships.md](championships.md).

## The bracket

* **Places.** Two to four of the connected players: the proposer first, then the others in the order they are
  proposed. The player picks who takes part on the "New Championship" page (+/- per player). Computer trainers take the
  other places of the eight.
* **Computer trainers** are the solo trainers of the Battle Tower: Legends floors (`tower_floors.py`; floor N's team is
  all level N, 1 to 6 Pokémon). Only a trainer whose team passes the bracket's entry rule may take a place
  (`frontier_rules.check_party`: Level 50 / Level 30, Species Clause, Item Clause, No Legendaries, or Open). The rule is
  the one in force when the bracket is proposed (Open when the host has no Frontier rules), and it stays with the
  bracket: a rule that rotates later does not change it.
* **Which floors:** an even spread from the strongest player's best level down to the weakest player's (each player's
  best level is from their last save). Each place takes the eligible floor nearest its level, and no floor is used
  twice. Example: players at levels 40 and 20 give floors 40, 36, 32, 28, 24, 20. Four players around level 47 give 50,
  48, 47, 45.
* **Seeds:** the players hold places 1 to N (the proposer first). The computer trainers hold the rest, the higher floor
  first (a higher floor ranks higher).
* **Matches:** quarterfinals 1 v 8, 4 v 5, 2 v 7, 3 v 6. Then the semifinals (the first two quarterfinals' winners,
  then the last two) and the final. So places 1 and 2 can only meet in the final.

## The three kinds of match

| Match | How it is played | What decides it |
| --- | --- | --- |
| Two players | Exactly the existing challenge: the host records the match before inviting; normal Accept and Enter in PLAYER > Challenges; native recovery | Only the released battle result (as before) |
| A player and a computer trainer | The player's own game. In PLAYER > Championship the player chooses "Battle <name> now". The host records a ticket and answers with the battle command (the Tower's solo command in mode 2). The game closes the menu, shows the round's intro ("QUARTERFINAL! TUBER / LARRY wants to battle!"), fights the floor's solo trainer and shows the result ("You won the QUARTERFINAL!") | The result that game reports for the host's ticket (world action 7) |
| Two computer trainers | No battle | The higher seed goes on as soon as the bracket is active and both are known |

A match against a computer trainer is a solo Tower floor in every way that matters to the game:

* The party is healed afterwards and held items come back.
* No money changes hands, and there is no whiteout.
* The result is kept in the save's Tower record until the host's state word clears it.
* There is no "go on to floor N?" afterwards (the launcher's host save runs instead, as after NO).
* One Tower battle at a time: no Championship match while a Tower floor, a Duo or an unsettled result is open, and no
  Tower battle while a Championship match is out.

**Interrupted matches:**

* A command the game never starts within 120 s is void; ask again.
* The game refused it (another Tower result still unsettled, no Pokémon able to battle): ask again.
* Started, but no result ever came: the menu offers "Give up: count a loss", which counts once the player's game has
  been connected for 15 s (its kept result is posted right after it connects). After 24 hours it is a loss anyway.
  These are the Battle Tower's own rules. The 120 s and the 24 hours are measured on the host's clock, which leaves
  out any change made to the PC's clock while the host runs (set forward or back by hand, a time sync's
  correction): such a change is not time passed (KNOWN_ISSUES MS-219).
* A draw is played again.

## Defaults the owner can change

| Default | Now | Where |
| --- | --- | --- |
| Experience in a match against a computer trainer | **None** (neither experience nor effort values; a link battle between two players gives none either, and level-capped rules stay fair) | `championship8.EXPERIENCE`; the command's flag byte carries it, so the game needs no change |
| Fewest players in an eight-place bracket | 2 (a single player could otherwise win a Championship against computers alone) | `championship8_protocol.MIN_PLAYERS` |
| Which floors | the spread between the players' best levels, under the rule | `championship8.computer_places` |
| A started match with no result | a loss when the player gives it up, or after 24 h (the Tower's rule) | `championship8.CONNECTION_SECONDS`, `STARTED_SECONDS` |
| The entry rule | checked at proposal, at acceptance and before every match, from the last save, under the bracket's own rule | `server._championship_eligibility` |

## Storage and compatibility

* The eight-place brackets have their own sidecar, `<world>.championships8.sqlite3`, with the four players' bracket's
  safeguards: explicit transactions, hashed records, the issued match identity committed before the invitation or the
  ticket, and the whole archive verified at host start.
* A build without step 18 never opens this file, so it never refuses its world over it.
* The four players' sidecar is not changed. Its brackets are still played to the end and counted (Trainer Card
  counters, history).
* One bracket at a time per world, over both files.
* A host whose game cannot fight a computer match (no `championship_abi_version` in its manifest) offers four players
  the bracket of before.
* Protocol version 2 (`championship8_protocol.py`) shows both shapes. Version 1 requests still reach the four players'
  sidecar unchanged.
* The Trainer Card counters (entries, completed, wins) count both kinds of bracket. An entry needs every player's
  acceptance; a win is a player's (a computer trainer can win a bracket, and nobody's win counter moves).

## How it was verified

Where each result comes from: **L** this Linux machine. Nothing here ran on Windows or on the owner's PCs.

| Where | What ran | Result |
| --- | --- | --- |
| L, engine test build | `selftest-tower` (the command's new checks) | 2099 checks, 0 failed (2090 before) |
| L, engine test build, real game processes | `tools/battle_env/championship_check.py`: a quarterfinal won with no experience (exp 156250 → 156250, effort values 0), a semifinal lost, a final won with experience asked (exp gained), a plain Tower floor as the control | 4/4 passed; the texts read from the game's own log |
| L | GBA ROM rebuilt; `check_gba_lines.py`; Windows 3D build with MinGW | ROM sha256 `f214735b…3387` unchanged; no moved lines; compiles |
| L, app | `test_championship_eight` (19), the Tower routing test, the manifest marker test, the network tests over the real server (2), the Championship/Tower/menu/companion/server modules | all passed |
| L, two native games through the whole launcher | `native_launcher_tower_proof.py --scenario championship` (TEST_LEDGER, step 18; the test build's advantage, as the Tower's climb proof, because the fixture players are level 100 and meet floors 95-100): the proposal and the acceptance in the games' own Players menus, the computer trainers' quarterfinals decided at once, both players' quarterfinals and semifinals against computer trainers from their own pages to the host's settlement (floors 95, 96, 99 and 100: the kept result cleared, money unchanged, the parties healed), then the final between the two players by the existing challenge flow ("Propose 1v1 match", the host's invitation, Accept, both Enter battle) | **passed** (run 9; the final given up by player 2 at their first action - Run, the forfeit between players - so the bracket completed, player 1 its champion in both players' history and the Trainer Card counters). Runs 4 to 8 found and fixed four gaps: the battle connection's protocol version, the game's bridge, the menu reopening deep on a match page, and a battle between players stopping at its intro after the players' earlier battles (MS-180) |

## Not verified

* Windows, the owner's PCs, a real graphics card, two PCs over the internet.
* A final played to a knockout between players in real games: in the proof player 2 gives up the final (Run, the
  forfeit between players); played on, run 8's final went 22 minutes and the scripted players could not finish six
  level-100 Mewtwo against six.
* The no-experience rule in the launcher proof: its players are level 100. `championship_check.py` shows it at a lower
  level.
