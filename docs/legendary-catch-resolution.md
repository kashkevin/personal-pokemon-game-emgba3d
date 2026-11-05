# World Event catch ownership (Update 11)

**Status: built and tested in the cloud only (simulated).** `shared_world.py` (`event_result`, `_resolve`, `resolutions`),
`tests/test_event_catch.py` (11 tests) and the rewritten late-catch test in `test_shared_world.py`. The five-minute
reservation and the no-duplicate-claims rule (2026-11-05, below): `shared_world.py` (`claim_event`, `player_connected`,
`player_disconnected`, `_holder`, `_claim_lapsed`, `event_result`, `catch_verdict`), `server.py` (`_catch_verdict`);
`EventReservationTests` in `tests/test_shared_world.py`, `tests/test_event_catch.py`, `tests/test_rewards.py`,
`tests/test_world_server.py` (over the wire) and `tests/test_save_compat.py` (a claim saved by an older build).

## The rule
**The first valid reported catch wins**, decided by the host in the order the reports arrive (one event loop, so the order is
total). A report is *valid* when its sender claimed that event at some point (the claimant list is saved with the event, so it
survives a host restart). **One claim at a time** (owner, 2026-11-05, KNOWN_ISSUES G3): while a trainer holds the claim, a catch
is accepted only from that trainer; an earlier claimant's catch counts only while nobody holds the claim. The rule decides what
happens when a claim lapsed (a long disconnect) and two games both battled the Pokémon.

## The claim and its five-minute reservation (owner, 2026-11-05)
"Reserve the encounter for five minutes after a player disconnects. Allow the original player to reconnect and reclaim it
during that period. Release it afterward. Prevent duplicate claims." (`docs/owner-decisions.md` #38.)

* **One holder.** A claim is granted only when nobody holds the claim (or to its holder again); everybody else is told it is
  busy ("Another TRAINER is battling it"). Claims are handled one after the other by the host's event loop, so two claims
  arriving together give one "granted" and one "busy".
* **Five minutes after a disconnect.** A claimant whose link drops keeps the Pokémon reserved for
  `BALANCE.event_claim_grace_seconds` = 300 s (it was 120 s). Reconnecting within them reclaims it (at once; talking to the
  Pokémon again is the same claim), and the claimant keeps it until it reports or walks away. At 300 s it is released,
  exactly: a reconnection, a claim, a report and the host's 0.1 s tick all check the same deadline, so a reconnection a moment
  late finds it released (the trainer may claim it again like anybody else if nobody was quicker), and a claim at that moment
  is granted.
* **Only time somebody is online counts** (as for every World Event timer since Phase 11). While nobody is online nobody can
  take the Pokémon, so the reservation waits: a trainer who joins an empty world later still sees the whole five minutes run
  before the Pokémon is free. This is kept on purpose; it never lets two trainers hold it.
* **Host restarts.** A restart disconnects everybody. A claimant that was connected gets the whole five minutes from when the
  host is back (counted once somebody is online); one that was already away gets what was left. A claim is saved the moment it
  is granted, reclaimed or released, and the reservation's time with the host's timers (every 30 s, when the last player
  leaves, at a clean stop); a clean stop keeps it exactly, a crash gives back to the claimant at most the time since the last
  save (never a claim to anybody else).
* **A connected claimant on another map** for 60 s of active time still lets the claim go (`event_claim_away_seconds`,
  unchanged, M20). Shared wild Pokémon keep their own 600 s grace (`shared_spawns.py`), unchanged.
* **A catch over another trainer's claim waits.** A catch reported by an earlier claimant (its game battled on offline after its
  claim lapsed) while another trainer holds the claim, battling it or within its own five minutes, is not accepted: the answer
  is "busy", the report is logged "deferred", and no verdict is decided for it. The game reports its recorded catch again
  (about every 20 s) until a verdict comes: once the holder catches the Pokémon, that report is "late" and the copy is released
  as a duplicate (Update 17); if the holder lets it go first (runs, loses, walks away, or its own five minutes end), the next
  report is the first valid one and keeps the Pokémon.
* **Older worlds.** A claim saved by an older build (counted against 120 s, no `grace_window` in the record) loads with the five
  minutes: a claimant saved while connected gets five minutes; one saved while away keeps the time it had already been away
  (120 s minus what was saved) and gets the rest of the five minutes. Records now carry `grace_window` (300) beside
  `grace_remaining`, which an older build still reads (it gives that remaining time, as before).

### Left open (existing rules apply; not decided here)
* **The event's own timer** (15 minutes) still ends the event whatever the claim. If it runs out while a trainer holds the claim,
  the after-expiry rule below applies (the first valid claimant report wins), so an earlier claimant whose reservation lapsed
  can still win over the trainer who held the claim when the event ended, if its report arrives first.
* **A shiny event** (no timer) knocked out by an earlier claimant's late report while another trainer holds the claim still ends
  the event (owner request, Oct 24, 2026, unchanged): nothing is caught twice, and the holder's own catch afterwards is still
  accepted.

## What is recorded, durably, before anything else changes
`event_resolutions`: event, winner, a global sequence number, time, species, level, **shiny**, **mega**, **held item** (the Mega
Stone), category and every claimant. `event_reports`: every "caught" report received, with its verdict (winner, replay, late,
expired, never_claimed). The winner is written first, then the event is closed; a host that stopped between the two closes the
event on restart. A dormant (not yet woken) event cannot be claimed or caught.

## Behaviour
* The winner's repeated reports (the game re-sends until acknowledged) are answered "consumed" every time and change nothing.
* Anyone else's report finds it "gone" (logged "late"); a trainer who never claimed it is refused ("never_claimed") and the
  Pokémon stays catchable by its real claimant; a report after the event expired is logged ("expired") and creates no owner.
* An earlier claimant's report while another trainer holds the claim waits ("busy", logged "deferred", no verdict yet; above).
* Everyone gets the usual "X caught the <Pokémon>!" banner; the world view is broadcast so every game drops the Pokémon. (Until
  2026-11-05 a catch could also be accepted from a trainer whose claim had lapsed while another trainer battled the Pokémon, who
  was then told "X caught it first! Your battle ends here."; a held claim can no longer be overtaken by a catch.)
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
   A report that waits for another trainer's claim (2026-11-05) gets no verdict yet: deciding then would have stored *keep* for a
   copy that may turn out to be the duplicate; the game's next report after the owner is decided gets the verdict.
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
