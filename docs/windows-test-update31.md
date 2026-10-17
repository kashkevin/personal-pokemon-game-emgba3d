# Update 31 — real Windows PC checklist (2–4 players)

Items marked **(engine)** need a package built from the engine branch `claude/dev-update31-rival-engine` (or a later
integration of it); with an older engine the original NPC rival scenes still play and only the menu-driven checkpoint exists.
The engine half is described in `docs/update31-rival-checkpoints.md` §11; every item below is still unverified on a real PC.
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

- [ ] New character: boy/girl and name (Birch's speech) → the 18-starter screen → spawns in front of own house in Littleroot facing down, "received the … from PROF. BIRCH", nickname offer, "saved the game"; no truck, no Birch rescue, no first battle; Route 101 open; Pokédex/Poké Balls only after Route 103; Running Shoes from Mom after that. START > STYLE still opens the character selection.
- [ ] The Update 30 first-time character (Host Server / Join Server): after the introduction's save, closing the game is enough; the character is enrolled (the draft needs a saved starter, which the introduction provides).
- [ ] Existing character loads without character creation.
- [ ] No NPC May/Brendan at the five checkpoints in multiplayer; other trainers unchanged.
- [ ] Route 110 / Route 119 trigger lines stop you (exclamation, message, one step back, the Players menu opens on its Rival checkpoint row) until done or passed; going back south, walking along the line and Fly/Surf around them are never blocked and never hold you on the line.
- [ ] Rustboro's optional line (after the Devon Goods) never holds you in multiplayer; arriving on a checkpoint's map shows its banner once.
- [ ] Countdown at a checkpoint: every player there gets the "!" mark with the encounter sound and a "RIVAL BATTLE!" banner; nobody is locked.
- [ ] After a pass, Dowsing Machine (Route 110) and HM02 Fly (Route 119, then Scott arrives and leaves) arrive exactly once each when you step on the line, also after reload; a checkpoint completed by the others while you were away shows "Continue the story" and gives nothing until you do.
- [ ] Route 103 pass: Birch's lab gives the Pokédex and Poké Balls (not before); Lilycove pass: the rival is home in Littleroot afterwards.
- [ ] Rival battle background: the route's plain background in Classic 2D (not the link arena) and the route in Native 3D; no black screen, no arena flicker, kept through moves, switching, Mega Evolution, fainting and the end of the battle; Nature Power / Camouflage / Secret Power behave as on a plain field on every player's screen alike; ordinary NPC trainer and ordinary PvP battles unchanged.
- [ ] Cutscene: the other players' real looks and names; camera and movement return after the scene and after a disconnect.
