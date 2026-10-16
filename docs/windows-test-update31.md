# Update 31 — real Windows PC checklist (2–4 players)

Items marked **(engine)** need the engine work in `docs/update31-rival-checkpoints.md` §7 first; until
then the original NPC rival scenes still play in game and only the menu-driven checkpoint exists.
Back up first: copy each player's `.sav` and the host's world folder (`world.sqlite3` and every
`world.sqlite3.*` sidecar, including the new `world.sqlite3.rival-checkpoints.sqlite3`).

## Menu-driven checkpoint (testable with this app branch)

- [ ] Host + 2 clients; both stand on Route 110 → Players → **Rival checkpoint** row appears; it is absent elsewhere.
- [ ] One player alone: page says "Waiting for rival players..."; Start Now and Wait for Other Players shown.
- [ ] Both press **Start Now** → "Battle starts in 5s" → "Your rival battle is ready" → **Battle: A vs B** opens Challenges; the other player accepts in Challenges; no wager row; battle runs with each player's own party.
- [ ] Win, loss and (if possible) draw: both pages show the result; "Good battle! The story goes on" for the loser; Route 110 shows done on Rival checkpoints (Challenges page).
- [ ] Start Now + Wait: nothing starts; three players with one waiter: after 60 s the two Start Now players get a 1v1.
- [ ] Three players all Start Now: three 1v1 battles one after another (round robin); standings show W/L/D.
- [ ] Four players: one 2v2; teams are balanced by highest party level.
- [ ] Double-click / rapid A on Start Now, Battle, Refresh: only one vote/challenge happens.
- [ ] Decline the challenge in Challenges: page returns to the lobby; vote again works.
- [ ] Disconnect a player during the countdown: countdown stops. During the battle: it stays "in progress" and resolves through the normal battle recovery after reconnect (saved-server shortcut / invitation).
- [ ] A late player connects after completion: **Continue the story** appears and works once.
- [ ] Alone online at a checkpoint: **Continue on my own** appears.
- [ ] Restart the host mid-lobby: votes are gone, completed checkpoints remain.
- [ ] Close the game during the battle and reopen: no duplicate battle, no duplicate completion.

## (engine) Story, intro, rendering

- [ ] New character: appearance → name → starter → spawns in front of own house in Littleroot; no truck, no Birch rescue; Route 101 open; Pokédex/Poké Balls only after Route 103; Running Shoes from Mom after that.
- [ ] Existing character loads without character creation.
- [ ] No NPC May/Brendan at the five checkpoints in multiplayer; other trainers unchanged.
- [ ] Route 110 / Route 119 trigger lines stop you until done or passed; going back is never blocked; Fly/Surf around them do not soft-lock.
- [ ] After a pass, Dowsing Machine (Route 110) and HM02 Fly (Route 119) arrive exactly once each, also after reload.
- [ ] Rival battle background: the route's plain background in Classic 2D and the route in Native 3D; no black screen, no arena flicker, kept through moves, switching, Mega Evolution, fainting and the end of the battle; ordinary NPC trainer battles unchanged.
- [ ] Cutscene: the other players' real looks and names; camera and movement return after the scene and after a disconnect.
