# World Event catch ownership (Update 11)

**Status: built and tested in the cloud only (simulated).** `shared_world.py` (`event_result`, `_resolve`, `resolutions`),
`tests/test_event_catch.py` (11 tests) and the rewritten late-catch test in `test_shared_world.py`.

## The rule
**The first valid reported catch wins**, decided by the host in the order the reports arrive (one event loop, so the order is
total), whoever holds the claim at that moment. A report is *valid* when its sender claimed that event at some point (the
claimant list is saved with the event, so it survives a host restart). Claims stay exclusive while they are held; the rule only
decides what happens when a claim lapsed (a long disconnect) and two games both battled the Pokémon.

## What is recorded, durably, before anything else changes
`event_resolutions`: event, winner, a global sequence number, time, species, level, **shiny**, **mega**, **held item** (the Mega
Stone), category and every claimant. `event_reports`: every "caught" report received, with its verdict (winner, replay, late,
expired, never_claimed). The winner is written first, then the event is closed; a host that stopped between the two closes the
event on restart. A dormant (not yet woken) event cannot be claimed or caught.

## Behaviour
* The winner's repeated reports (the game re-sends until acknowledged) are answered "consumed" every time and change nothing.
* Anyone else's report finds it "gone" (logged "late"); a trainer who never claimed it is refused ("never_claimed") and the
  Pokémon stays catchable by its real claimant; a report after the event expired is logged ("expired") and creates no owner.
* The trainer whose battle was overtaken gets a notice ("X caught it first! Your battle ends here."); everyone gets the usual
  "X caught the <Pokémon>!" banner; the world view is broadcast so every game drops the Pokémon.
* Friendship credit for the shared event is unchanged. Shiny status and the Mega Stone are as the event was created and are only
  *recorded* here; the catching game applies them (engine `PrepareEventBattle`/`RevertCaughtBattleForm`, unchanged).

## Reconciliation of the losing copy (Update 17)

**Status: built; host side and engine side tested in the cloud only (simulated). Not verified on a real PC or network.**

The Update 11 limit (two saves each holding a copy) is now closed by a verdict that travels back to the games.

1. **The game records the catch in its own save.** When a World Event battle ends in a catch, the engine stores a *catch record*
   in five previously unused script variables (`VAR_MP_CATCH_*`): the event, the party/box slot, species, personality and trainer
   id of the Pokémon. It survives saving and quitting, and it is re-reported to the host until a verdict arrives.
2. **The host decides once.** The first valid report wins (rule above). The host stores a `catch_verdict` per event in
   `event_verdicts`, so a restart repeats the same answer: the winner gets *keep*, every other claimant who reports "caught" gets
   *release*. A report that arrives after the event expired is still resolved (retroactive winner) rather than creating two owners.
3. **The verdict rides the existing private wallet stream** as a numbered reward word (kind 4 = keep, kind 5 = release, payload =
   the event's catch number), so it is delivered exactly once per player, survives disconnects (the player re-asks with its wallet
   number) and is acknowledged with `wallet_applied`. Repeated reports queue nothing new.
4. **Applying "release".** The engine finds the recorded Pokémon by *species + personality + trainer id* (not by slot alone), and
   removes only that Pokémon. If it is no longer there (traded, evolved, already released) nothing is removed. It never releases the
   last Pokémon in the party. Other Pokémon are never touched. "Keep" just clears the record.
5. **Shiny and event details** stay on the winner's Pokémon, as before; the host also records them in `event_resolutions`.

### Limits (not hidden)
* A Pokémon that was traded away or evolved before the verdict arrives cannot be recognised and is left alone (the duplicate stays).
* Saves made before this update have no catch record and ignore verdicts; their duplicates are not reconciled.
* The record needs the player's game to be running to learn the verdict; a player who never reconnects keeps the copy until they do.
* No arbitrary save bytes are rewritten: the engine acts through its normal party/box functions while the game is running.
* Everything above is exercised by simulated tests (engine native self-test `--selftest-catch-reconcile`, app unit and wire tests),
  not by real Windows play.
