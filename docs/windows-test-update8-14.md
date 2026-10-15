# EmeraldTogether: Windows test checklist for the Update 8-14 build

Adds to `docs/windows-test-update2-7.md` (keep running its sections 0-9). **Nothing below has been run on a real PC.** The features
were tested only by unit tests, engine self-tests and a real host with scripted game bridges (`DEVELOPMENT_LEDGER.md` Updates 8-14,
`docs/automated-validation-matrix.md`). bios.c licensing is unresolved: this build is for the owner's private testing only.

## A. NEW: Battle Frontier (two PCs; PLAYERS > World and my base > Frontier and League > Battle Frontier)

Each player needs a saved party (play, save in game, stay connected so the host holds your last save).
- [ ] Player A **Start a Frontier run**: B sees "A invites you"; B **Join**; both see "Round 1" and the opponent (Lv50 by default) and the prize.
- [ ] **Start round 1**: both players get the co-op battle (each fights with their own party against a 3-Pokémon team). Win: the money prize arrives in each wallet **once**; round 2 is harder (a tougher pool every 7 rounds; a Frontier Brain pair closes each set of 7).
- [ ] Lose or draw a round: the run ends; the menu shows "Last: ... streak N" and the best streak. Close one game mid-battle, reopen it: the battle is recovered or the run is voided without a prize, and reconnecting never pays twice (check the money).
- [ ] **Retire (keep streak)** between rounds keeps the streak record. Restart the host: the run, streak and records are still there.
- [ ] Optional: `world.sqlite3.frontier.json` with `{"party_limit": 3}` limits the party each player brings (menu says "Bring up to 3").

## B. NEW: Pokémon League (needs 8 badges for both)

- [ ] Both players with 8 badges: **Pokemon League > Challenge the League**; 3 rounds (Sidney+Phoebe, Glacia+Drake, Wallace+Steven) at the trainers' own levels, individual prizes, first clear bonus once per player.
- [ ] A player with fewer than 8 badges is refused with the reason. After a clear, **Hall of Fame** lists the run once; clearing again gives no second first-clear bonus.
- [ ] Experience only while at least one of the pair is a first-timer (otherwise none).

## C. NEW: Legendary catch ownership (two PCs, a World Event)

- [ ] Two players race the same event Pokémon: exactly one keeps it (the first reported catch); the other is told it is gone. A shiny / Mega Stone is kept by the winner only. Restart the host: nobody can claim it again.

## D. NEW: PokéNav pages

- [ ] **World > This area's wild Pokemon**: level range, "Common: ..." species, "Favors:" types and "Now: <time>, <weather>" match what you meet on that map; in a town/building it says "No wild Pokemon data". The World page shows host time of day and "online n/4".
- [ ] Secret Base: after changing your party, wait ~10 s outside, then another player visiting your base meets that team. **Visible to: Everyone** (default) / Teammate / Nobody still work.
- [ ] No graphical map markers exist (not built, see `docs/secret-bases-and-pokenav.md`).

## E. NEW: Gen 6 rules

- [ ] In a trainer battle there is no way to run away or forfeit; a thunderstorm in the overworld does not create Electric Terrain in battle.

## F. Not built (so there is nothing to test)

- Four-player free-for-all (1v1v1v1): `docs/free-for-all-feasibility.md`. Choosing a subset of a larger party inside a Frontier battle, item/BP prizes, a ticket path for static legendaries: owner decisions in `docs/owner-decisions.md`.
