# Wireless minigames between the world's players (KNOWN_ISSUES MS-141c)

Owner's decisions: both computer partners and the world's players (2026-10-27); computer partners first (done,
MS-141, engines `04079e45` and `6d9079d8`); the world's players now (2026-11-04, "ALL OF THEM"; engine `62dd22ae`). PC only: the GBA ROM
is unchanged (every engine change is under `PORTABLE` or in PC-only files).

## What a player sees

* **Berry Crush** at any Pokemon Center 2F's Direct Corner (the right-hand attendant), with the POWDER JAR and a Berry;
  **Pokemon Jump** and **Dodrio Berry Picking** in Mossdeep City's minigame building, after choosing the Pokemon for
  the game, as the lobby asks.
* In a world, the attendant first asks "Play BERRY CRUSH with players in this world, or with computers?" (Mossdeep:
  "Play with players in this world, or with computer partners?"): WORLD PLAYERS, COMPUTERS, NOT NOW. COMPUTERS goes on
  to the computer partners (MS-141) as before; outside a world only the computer partners are offered.
* WORLD PLAYERS: the game saves first (as the wireless lobby does on the GBA), then the **Players menu opens on the
  game's lobby page**:
  * nobody leading: "Lead a group" (and, for each group of that game not yet started and not full, "Join NAME n/4");
  * the leader: the players in the group, "End the group", and "Start with N players" once the game's minimum have
    joined (Berry Crush 2, Pokemon Jump 2, Dodrio Berry Picking 3); the page reads the host's groups every 2 seconds;
  * a member: the players, "Leave the group", "Waiting for NAME to start".
  B leaves the lobby (a leader's group ends; its members' pages say "The leader ended the group").
* The others hear of a new group in their banner ("NAME: BERRY CRUSH", "Join at a Direct Corner" / "Mossdeep's game
  house").
* Start: every player's window closes ("Off to the game!") and every game walks into the link room as after the
  wireless lobby, waits for everyone (the link's standby, now a real wait over the network) and the game begins. The
  rest is the original game: the leader's game decides what it always decides; every player's own Berry, presses,
  results, prizes and records, saved as the original saves them; the players' names are the players' own.
* If the group is lost during a game (a player's connection, game or window is gone, or the leader's game stops
  sending for 10 seconds), every other game shows the game's own communication error ("Move closer to your link
  partner"), and A returns to the last save, as on the GBA when the adapter loses its group.

## How it works

The GBA games run over the Wireless Adapter's RFU link: one parent (multiplayer id 0) and up to four children. Every
frame the parent sends the commands of all players of the frame before (`ReadAllPlayerRecvCmds`: 5 x 7 words, 70 bytes)
and each child answers once per parent frame with its own command (7 words, 14 bytes).

**Engine** (`src/link_rfu_2.c`, NetLink, beside MS-141's LocalLink): a virtual RFU group whose frames go through the
world server.

* Leader: each frame, the commands it handled the frame before go out to the members (sent every frame, an empty frame
  as nothing); one waiting command of each member goes into its slot; its own command comes back in slot 0; the
  commands are handled and the link's callback runs (`RfuMain1_Parent` and `RfuMain2_Parent` once the adapter has
  exchanged the frame's data).
* Member: on a frame with a leader frame waiting, its commands are handled, the link's callback runs and the member's
  own command goes out if it has one; on a frame without one nothing is handled and nothing goes out (its command waits
  in `gSendCmd`). A member more than 6 frames behind handles two frames a frame until it has caught up; one with no
  leader frame for 600 frames (10 s) has lost its group.
* Queues: a member's commands at the leader 32, the leader's frames at a member 64, outbound 64; a full queue drops its
  oldest packet-only entry (the games send their state again and again), never a handshake or a block piece.
* When the leader's game closes the link, its last frame (the closing, which the members' games wait for) still goes
  out, and only then does the game say it has left.

**Bridge** (`src/platform/mp_bridge.c`): the fifth native extension. Once the world mailbox is up the game announces
`u` (version 1, 5 players, a command of 14 bytes, a frame of 70); then `m` frames both ways: `[1, frame]` from the game,
`[1, source, frame]` to it; the lobby's `[2, HELLO, activity, link player]` (name, gender, language, version, trainer
id: 16 bytes), `[2, LEAVE, reason]` (0 the game closed the link at its end, 1 the link was lost, 2 it left the lobby),
and to the game `[2, STARTED, activity, players, own id, link players]` and `[2, CLOSED, reason]`. The Players menu's
OPEN may name pages 5-7 (the lobbies) only after `u`. **Glue** (`src/platform/mp_minigames.c`): the specials
`IsWorldMinigameAvailable` (a world, the menu's pages, a save of this world bound to it) and `OpenWorldMinigameLobby`
(the HELLO, the menu on the lobby page, then the group's start: NetLink as leader or member, every player's link
player, the room) and the frames.

**Companion** (`minigame_link.py`): the channel's frames to and from the world server, each on its own bounded lane
(the bridge's `put_minigame`, the server's per-session minigame queue), so the link never waits behind saves or menus;
a leave goes to the host after the link frames sent before it. The lobby page (`MinigameMenu`, drawn by
`player_menu.py`). **Host** (`minigame_groups.py`, `minigame_protocol.py`, `server.py`): session-local groups, nothing
saved; a leader and up to three members (a world has four players); `minigame_status/open/join/start/leave` requests;
the start pushes every player's link players and own number; a link frame from the leader goes to every member still
in, a member's to the leader, each tagged with its sender. A started group's player leaves quietly when its game closed
the link at its end (every game does); a player whose game is gone from a started group (link lost, window closed, the
start crossing its leaving the lobby) or who disconnects ends it for the others (`player_lost`).

## Not changed

The GBA ROM; the games' rules, prizes, records and saves; computer partners (MS-141); a game outside a world.

## Limits

* Berry Crush and Pokemon Jump have been played between two real games. Dodrio Berry Picking (three players at
  least) starts, links and ends the same way (the same lobby, the same NetLink); its three-game proof is the next run.
  Four players and Windows not run.

* A frozen member game whose launcher connection stays up is not noticed by the leader's game (members send only the
  commands they have; the leader cannot tell silence from a freeze); the games' own waits apply. A frozen leader is
  noticed by every member after 10 s.
* Up to four players, as a world (the GBA's groups take five).
* The 3D UI does not draw the three games' own screens (KNOWN_ISSUES MS-105): they are the game's pictures.

## Tests

* Engine: `--selftest-netlink` (make `check-netlink`): the leader's and a member's frames, refusals, catch-up,
  standby, blocks both ways, a full queue, closing, the lost group, the member's 10 s stall.
* App: `tests/test_minigame_groups.py` (the host's groups, the protocol, the game's frames),
  `tests/test_minigame_network.py` (a real world server, real companions and bridges that speak as the game does:
  start, 100 frames each way in order, the end, a game gone, a lost link, a lobby left as the start came, a
  disconnect, refusals).
* Real games: `scripts/multiplayer/native_launcher_minigame_proof.py` (native games through the whole launcher: the
  attendants, the lobby, the game to its "play again?", the launcher's saves and a fresh Continue), with the fixture
  saves of `make_tower_saves.py`. Linux, 2026-11-04:
  * Berry Crush (`crush-a`, `crush-b`), run 12 passed: the whole game between the two, both back on the field with no
    communication error, 3,719 link frames through the host, none dropped.
  * Pokemon Jump (`--activity pokemon_jump`, `jump-a`, `jump-b`: a Pikachu, a Marill at Mossdeep's counter), run 2
    passed: both players jumped the vine six swings running (A as the vine came down), each game showing the other
    player's six jumps, then the vine caught them; both games showed the leader's score (360, 6 in a row); the host
    YES and the friend NO to playing again, both links closed by the games, both out of the room; 2,241 link frames,
    none dropped. (Run 1 stopped at the old man's greeting: the proof did not press at its paragraphs.)
  * Dodrio Berry Picking (`--activity dodrio`, three games: `dodrio-a`, `-b`, `-c`): written, not yet passed.
  Results in TEST_LEDGER.

## Found on the way (by the launcher proof, all in this new code, fixed before it was committed)

* The bridge refused the lobby pages (5-7) and stopped: they are allowed once the game announced the minigame channel.
* The lobby never opened: the attendant's script, waiting for it, held the field's controls, and the Players menu opens
  only on a free field; and a player who pressed toward the counter before A was still "moving" for the menu's field
  test. The lobby frees the field for the moment the menu opens and holds the player standing at the counter.
* A session's first menu refresh replaced the lobby with the Players home: the page is set after the session's binding.
* At the start the leader's window stayed open: the answer to its own "Start" came right behind the window's close, and
  the game's menu mailbox holds one screen. A window the host closed takes no other screen.
* At the game's end a member's link never ended (a GBA child leaves its disconnect to the adapter): the member ends its
  link at once when every player is ready to close. The leader's last frame goes out before its game says it left.
* A lost group's communication error crashed in the adapter's VBlank work on PC: that work is skipped while it shows.
