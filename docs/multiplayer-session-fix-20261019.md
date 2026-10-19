# A player in a battle disappeared and PLAYERS showed nobody (2026-10-19)

The owner and a friend played one hosted world on two Windows PCs (the installer from app `f136689`, engine `47767264`).
When one of them entered a battle, the other player disappeared, START > PLAYER > PLAYERS stopped working and behaved as
if nobody else was connected, and nothing said whether the player was disconnected or only hidden.

## What was reproduced

Two setups, both on this workspace's Linux build of the same engine (2D, Xvfb), real `WorldServer`, real `Companion`s,
real native games driven with ordinary key presses:

| Setup | Result |
| --- | --- |
| Presence only: a world server without a store, two companions, two games; one player walks to a shared wild Pokemon and talks to it | **No failure.** Both stay in the server's sessions and in both rosters for the whole 50 s battle; the battling player is hidden on the other screen (activity "unavailable") and drawn again afterwards. The bug needs the production configuration. |
| The production launcher (`LauncherWindow`, `SessionWorker`, `LauncherSession`: world creation, enrollment, hosting with the store, battles and rival checkpoints enabled), host and friend, unchanged code | **Reproduced.** Below. |

Timeline of the production reproduction (seconds of the harness; `scripts/multiplayer/native_session_persistence_proof.py`
grew out of it):

| s | What happened |
| --- | --- |
| 98.21 | The host's companion receives its first answer to the rival checkpoint status it polls every 1.5 s (Update 31). |
| 99.90 | The next shared-world frame to the game carries the rival record: bytes 192-207 `0000000000000000 0100000000000000` (the record's valid flag at 200). |
| 99.91 | The game's bridge refuses the frame and stops for good. `runtime.log`: `Multiplayer bridge disconnected: invalid shared-world update`. |
| 99.91 | The companion loses the game's link; with trades enabled that also ends its world session (by design: a new game incarnation must not inherit a trade). It reconnects without a game. |
| 239.97-241.80 | The same for the friend's game. |
| after | Both games: `sConnected` 0, no peers, no other player drawn, START > PLAYER > PLAYERS does not open (the menu needs the link) and closes without a word. The server and both companions still list both players, "unavailable". The launcher reports `save_recovery_required`. |

## Root cause

**The game's own bridge rejected the rival checkpoint record.** Update 31 added an 8-byte rival record to the shared-world
frame at offset 200 and taught the game (`multiplayer_world.c`, `multiplayer_rival.c`) to read it, but the native bridge's
`ValidWorldInbound` (`src/platform/mp_bridge.c`) still required bytes 192-207 to be zero. The first record the companion
relayed, which always has its valid flag set, made the bridge stop fatally. The game then ran unlinked for the rest of the
session.

Classification (the report's categories): for the game that lost its link, **disconnected** (its local roster emptied, its
Players menu refused to open); for everyone else, that player stayed **in the roster but was not rendered** (the
companion had reconnected without a game, presence "unavailable"). Battles did not remove anybody by themselves: the
presence-only run and the fixed production run both keep a battling player in every session.

**Why it looked tied to battles.** The trigger is the first successful rival status, which the companion asks for from the
moment its world session starts; in the reproduction that was within two seconds of the game connecting. A battle is the
first moment a player expects the other to be hidden and back, so it is where the loss is noticed; on the owner's PCs the
exact moment cannot be confirmed without their logs. Each game's `runtime.log` (in the launch folder under
`%LOCALAPPDATA%\PokemonPrivate\...\launches\`) says `Multiplayer bridge disconnected: invalid shared-world update` when
this happened.

### The same check, eight bytes earlier: mass outbreaks

The four-player runs of this fix found a second trigger of the same failure, after their checks had passed: 12-13
minutes into each run all four games logged `Multiplayer bridge disconnected: invalid shared-world update` at the same
moment (session-4p-1, -2 and -3). Update 18 (the Town Map) has the companion pack the running mass outbreak's place into
bytes 192-199 of the same frame (valid, map group, map number, a zero byte, an unused species word, two zero bytes;
`world_mailbox.py`), and the game's Town Map reads it (`region_map.c`), but `ValidWorldInbound` still required those
bytes to be zero too. The host starts the world's first outbreak 8-15 active minutes after the world starts, so with the
rival fix alone every game would still lose its link then, all at once, and a game joining during an outbreak would lose
it at once. The two-player runs ended before the first outbreak; the Town Map was only ever checked with the engine's
injected test marker, and the outbreak proof (native-outbreak-5) ran on an engine from before Update 18.

Reproduced through the launcher: the proof now gives the world an outbreak settings file (first outbreak after four
active minutes instead of 8-15). On the game with only the rival fix (engine `16d0aa55`), run outbreak-before-2p:
both games linked, PLAYERS "Connected: 2/4"; when the outbreak started both games logged `Multiplayer bridge
disconnected: invalid shared-world update` in the same second, and the host's game was left unlinked, without its
friend and without the marker. On the fixed game: running.

### A second defect found on the way

`Companion._remote_once` ended the world session whenever **any** of its tasks finished. The rival poller finishes by
design when a host refuses rival status (a host without rival checkpoints, such as the server that runs enrollment). The
companion then reconnected in a loop (every 0.25 s, its reconnect delay); with the launcher's terminal saver armed it would not reconnect at
all (`_disconnect_remote` blocks reconnecting and starts host-loss preservation). In the reproduction this made the host's
own character enrollment fail ("The authenticated host connection is unavailable", from a `ConnectionResetError`).

## Changes

Engine (`claude/mp-session-engine`, PC only; the release ROM rebuilt from it is still
`f214735b64e113fd10730eacca5764d757f2c93a3685230aa905af7a7cdd3387`):

- `src/platform/mp_bridge.c`: `ValidWorldInbound` accepts a well-formed rival record at 200 (the rules of
  `multiplayer_rival.c` `ValidRecord`) and a well-formed outbreak marker at 192 (the layout `world_mailbox.py` packs and
  `region_map.c` reads); anything malformed still closes the link.
- `src/multiplayer_presence.c` (new, PC only, left out of the ROM build): while the player is off the field the game's
  pose says why in its last byte: 1 battle, 2 menu (START, PLAYERS, bag, party, PC...), 3 transition (a warp, a door,
  stairs, Fly, a whiteout, the fade around them), 0 anything else (a dialogue, a cutscene, a save). Marker
  `gMultiplayerPresenceDetailAbiVersion`; the bridge accepts the byte only in the game's own pose (capability
  `presenceDetail`); other players' poses keep it zero.
- START > PLAYER > PLAYERS: when the menu cannot open it now says why in the field banner ("Link to the world was lost. See
  the launcher window.", "Not connected to the world.", "PLAYERS is not ready yet."), instead of closing silently.

App (`claude/admiring-bohr-dpxzuy`):

- `companion.py`: only the connection's reader and presence sender end a world session; optional pollers (rival status)
  can stop without ending it, and an unexpected reply shape never escapes the poller.
- `companion.py`: a roster player whose position is off the map's grid (a step over a map edge can report -1) reaches the
  game listed and hidden at the edge. The game refuses a whole snapshot for one such peer, which hid every player.
- `mailbox.py`, `companion.py`, `generate_manifest.py`: the pose's detail is read with the manifest capability
  `presence_detail_abi_version` 1 and sent as the protocol's existing activities `battle`, `menu`, `transition`
  (protocol 3 already allowed them; no new message or field, so an older host or friend still accepts them).
- `player_menu.py`: the Players list shows what each player is doing ("Friend Finn - In battle", "In a menu",
  "Changing area", "Busy"), on the field their friendship level as before; a player's page starts with what they are doing
  and where ("In battle: Route 101"). The list is the session's roster: only leaving the session removes a player.
- `server.py`: the co-op Gym's "teammate must be here" check and friendship time keep their previous rule (the teammate
  on the field). Before this change a teammate in a battle or a menu was "unavailable", so both keep exactly what they
  did.

### Behaviour that changes with the new activities

Server code written for these activities now receives them (until now every off-field player was "unavailable"):

- Shared wild Pokemon: a player battling one keeps the map populated and keeps the claim (as before; tested by
  `test_spawn_director` "claimant in battle keeps it"); a player in a menu on another map releases a claim.
- World Event conditions count a battling player as present ("Wakes when trainers gather").
- Rival checkpoint lobbies count a player in a menu at the checkpoint as present.

Battles, their rewards and saving are unchanged.

## Membership, link and drawing, separated

| Concern | Owner | Changes only when |
| --- | --- | --- |
| Network connection, identity | server sessions (TLS, credential, lease) | the connection ends (EOF, idle 20 s without anything from the client, protocol error) |
| Session membership (the roster) | server `sessions`, broadcast in every world message | a session is admitted or ends |
| Map and position | presence (map, epoch, x, y) | the player moves or changes map |
| Activity | presence `activity` | overworld / battle / menu / transition / unavailable |
| The game's link | the bridge to the local companion | the game or its companion stops |
| Drawing another player | the game (`PeerVisible`) | on the field, on the same map, near the camera |

A game publishes its pose every frame, battles and menus included, so a long battle never looks like a silent client
(the server's 3 s presence rule only applies when a game stops publishing).

## Tests

| Test | What | Result |
| --- | --- | --- |
| engine `check-native` | all native suites, including `test_mp_bridge` `world_rival_record_accepted` (8 failures on the old validator), `world_outbreak_marker_accepted` (10 failures on the validator with only the rival fix) and `presence_detail_rides_the_local_pose_only` | the bridge suite 4354 checks, 0 failures; the full `check-native` rerun is pending |
| `tests/test_session_persistence.py` | real server and companions over TCP, games as the binary bridge protocol: 1, 2, 3 and 4 players joining one by one with a battle at each count, a battle longer than the idle and presence timeouts, menus and a door, a game without the capability, four players with independent battle/menu/walk and a fifth refused as full who takes the free place, four enrolled players on an ownership world with the Players menu, a host refusing rival status (fails on the old code: sessions replaced dozens of times a second), rival records flowing | 16 passed (17 subtests), 5 runs in a row |
| `scripts/multiplayer/native_session_persistence_proof.py`, two and four players | see below | see below |

### The production proof (`scripts/multiplayer/native_session_persistence_proof.py`)

The same launcher path as the reproduction (world creation, enrollment of every character, hosting with the store,
battles and rival checkpoints on), native Linux 2D games of engine `16d0aa55`, one X display per player, ordinary key
presses only; the checks read the companions, the server and the games' memory. Each player starts on Route 101 from
its own save.

1. Everyone linked: every game's bridge up, each game drawing all the others; PLAYERS lists everyone ("Connected: N/4").
2. Wild battles, one player and then the next (four players: then two at once): a player talks to a shared wild Pokemon; for
   25 s, longer than the server's 20 s idle and 3 s presence rules, every other game keeps the player in its snapshot,
   hidden, every roster says "battle", no session is replaced; the watcher's PLAYERS shows "<name> - In battle". Then
   the player runs (the host fights its battle out instead); every game draws them again on the field, same sessions.
3. The last player walks south into Littleroot Town (a map change): still listed everywhere; the host's PLAYERS page for
   them says "Field: LITTLEROOT TOWN".
4. That player closes the game normally: gone from every roster, "Connected: N-1/4"; starts again: listed again.
5. The world store's integrity check; the players' source saves unchanged.

| Run | Players | Result |
| --- | --- | --- |
| session-2p-10 | host, friend | **passed**: both battles held 25 s (13 observations each) with the sessions unchanged (host 6, friend 7); "Host Hana - In battle", "Friend Finn - In battle"; back on the field in the same sessions; "Field: LITTLEROOT TOWN"; "Connected: 1/4" after the close, "Connected: 2/4" after the rejoin; store check passed |
| session-4p-3 | host and three friends | **passed**: all four linked, each game drawing the other three, "Connected: 4/4"; the host fought its wild battle out and **lost**: whited out to the house in Littleroot (a map change in the middle), same session; a friend ran; then **two friends battled at the same time**, both "In battle" on the host's PLAYERS; each battle 25 s with all four sessions unchanged (host 10, friends 11, 12, 13); everyone back on the field; the fourth player in Littleroot listed, "Field: LITTLEROOT TOWN"; "Connected: 3/4" after the close, "Connected: 4/4" after the rejoin; store check passed |
| session-4p-1, -2 | host and three friends | stopped on the proof's own driving, after the baseline and two battles passed: two players talked to the same wild Pokemon (4p-1; the battles now start one after the other), no wild Pokemon in a straight line within 240 s (4p-2; the proof now lines up with one) |

Pictures (not committed; the games' screens) show the battling player missing from the other screens during the battle
and back where they stood afterwards.

## What was not run

- Two (or four) physical Windows PCs, a real home network and the Internet relay: never. Everything above ran on this
  Linux workspace (and the Windows CI runner for the package).
- Battles other than wild ones (trainers, doubles, a Players-menu 1v1 or 2v2), catching, Surf, Fly and stairs were not
  driven in a game for this fix, and doors only in the simulated tests; wild battles ended by running and by losing (the
  whiteout warps into the house) and a route-to-town change were. The game reports every battle the same way
  (`gMain.inBattle`, or a multiplayer battle in progress) and every map load through the same callbacks, so they take
  the same path; the multiplayer battle proofs of earlier builds (`native-launcher-battle-1`, `native-launcher-multi-10`)
  were not rerun.
- The 3D build: the runner has no graphics card. The bridge, the presence detail and the Players menu are the same code
  in both builds.

## Checking on two PCs

1. Both PCs: install the new Setup over the old one; worlds and characters are kept.
2. Host: Host Multiplayer > your world > Host this world now; CONTINUE in the game. Friend: Join Friend with the invite;
   CONTINUE.
3. Both on Route 101: each sees the other walking. START > PLAYER > PLAYERS: "Connected: 2/4" and the other's name.
4. Host walks into the grass until a wild Pokemon battle starts. Friend: the host's character disappears from the field;
   START > PLAYER > PLAYERS lists "<host> - In battle"; open it: "In battle: Route 101".
5. Host runs from the battle. Friend: the host appears again where they stood, without anyone reconnecting.
6. Swap roles (friend battles, host checks).
7. Friend walks south into Littleroot Town and into a house (a door). Host: PLAYERS still lists the friend; their page says
   where they are.
8. Friend closes the game. Host: PLAYERS shows "Connected: 1/4" without the friend. Friend joins again: listed again.
9. With three or four PCs: each friend joins with their own invite (a character each; the same save file cannot be
   enrolled twice). PLAYERS shows "Connected: 3/4" or "4/4" and everyone else, the host included. Two players start
   battles at the same time: both are listed "In battle" on the other PCs and both come back; nobody else changes. A
   fifth PC trying to join is told "The world is full" and can join once someone leaves.
10. If anything disappears again: in the game's launch folder, `runtime.log`'s last lines say whether the game's link
   stopped (`Multiplayer bridge disconnected: ...`), and START > PLAYER > PLAYERS now says why it cannot open.
