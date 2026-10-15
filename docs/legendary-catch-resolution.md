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

## Limits (not hidden)
The host cannot take a Pokémon out of a save. If two games each finish the battle before either has reported, both saves hold a
copy, but only the first report is the recorded owner and gets the event's friendship credit. The old rule (a late catch is refused
while someone else battles) was replaced because it left exactly that duplicate for the player who had already caught it.
