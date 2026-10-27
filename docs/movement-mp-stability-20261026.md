# Movement lag, multiplayer stability, trades and battles (2026-10-26)

The owner's request "8. Player Movement Lag, Multiplayer Stability, Trading & Battle Fixes", done as smaller updates
before any packaging; nothing here was packaged. KNOWN_ISSUES and TEST_LEDGER have entries of the same date.

Where a result comes from, always: **L** this Linux machine (real game processes; the 3D view through Mesa's software
OpenGL, so frame times are a CPU's, and every GPU cost - drawing, the air effects - is far higher than on a real
graphics card); **W** a GitHub-hosted Windows runner (real Windows game processes, no GPU, loopback); **simulated** the
proofs' internet (`scripts/multiplayer/proof_network.py`). Nothing here was tried on the owner's PCs or between two
real PCs, and no GPU result exists.

## 1. Lag when running (the 3D game)

### How it was measured

- `PKMN_PERF_FRAME_LOG=<file>` writes a row per drawn frame: the whole sync of a new snapshot and its parts (atlas,
  terrain, objects, buildings, trees, props), and inside the terrain's sync the chunk inputs built, the milliseconds in
  inputs, meshes, uploads and the sync's preparation (engine `18ad922c`).
- The walk: the debug scene's field in Mauville (`PKMN_DEBUG_HERE=0,2,20,8`), running west 200 frames into Route 117,
  east 400 frames through Mauville into Route 118, west 200 back; four map crossings at running speed.
- The chunk mesh builder alone: 1,694 chunk inputs dumped from 14 maps (Lilycove, Sootopolis, Ever Grande, Fallarbor,
  Pacifidlog, Routes 105, 111, 119 and 120, a gym, the department store, a cave, Petalburg Woods, Mt. Chimney), built by
  the old and the new code in a stand-alone program, the vertices compared byte for byte.

### What was found (L)

1. **A chunk with roofs, stairs, bridges, mountain art or tree hulls took about 20 ms to build**, 80% of it `qsort` and
   a binary search per span and neighbour in the occupancy shell. A step builds a couple of chunks; a map's edge built
   15 to 30 in one frame (185 ms).
2. **Every map crossing rebuilt the chunks on screen**: chunks were keyed by the current map's coordinates, so a
   crossing at a connection found none of them in the cache, though the cells both maps' views share are the same
   (4,040 of 4,040 shared cells the same, resolved the same, Mauville to Routes 117 and 118).
3. **The water's animation redrew the same atlas slots a thousand times**: when animated tiles moved on, every cell of
   a slot that used a changed tile drew the slot again - 1,000 to 2,000 cells of water drew the same 26 slots, 10 to 15
   ms every few frames, standing or running: the largest regular spike of a walk.
4. **The map name's popup redrew everything a frame after each crossing**: it loads background palette 14, and any
   change of the 16 background palettes redrew the whole atlas and looked at every terrain chunk and detail object
   again, though the map's art uses palettes 0 to 12.
5. **Another map redrew the whole atlas** even with the same tilesets.
6. **The camera and the walkers snapped after any slow frame**: they were drawn between two snapshots only when the
   second was exactly one game frame after the first; a drawn frame that caught up two or more game frames (after any
   slow frame, or when the display's beat drifts against the game's) drew them where the last game frame left them, a
   jolt, then went back to drawing between frames - uneven steps and a jumping camera.
7. **Route 111 rebuilt every chunk's input every 6 frames** on the half of the visits the Mirage Tower shows (the game
   picks at random each time the route loads, until the tower's event): the tower's shimmer pulses palette 6, and any
   change of the faded palettes made the terrain look at every chunk again (121 inputs, 10 to 18 ms) though only pixel
   objects take their colours from the faded palettes. Found because one run of the same walk was fast and the next
   slow: the tower showed in one and not the other.
8. **Off-screen chunks on the view's edge were rebuilt on every step**: the 3D view holds 81 x 81 cells round the
   camera; a chunk on that area's edge reads cells past it, so its input changed with each step and it was built
   again with the off-screen allowance, to change again a step later - 371 of the 540 chunk builds running across
   Granite Cave, one edge chunk built 17 times. They are 20 cells or more from the player (the view's cells reach
   further north than south) and out of sight.
9. **The commonest ground flipping re-checked every chunk**: tree hulls stand on the commonest flat ground in view;
   on the sea round Pacifidlog Town the two kinds of water took turns as the commonest every few steps, and each time
   all 81 chunks' inputs were built again, to change none (8 to 12 ms).

### What changed (engine, all PC only; the GBA ROM's SHA-256 unchanged)

| Commit | Change |
|---|---|
| `18ad922c` | Chunk meshes built about 5.3x faster with byte-identical meshes: counting and radix sorts into qsort's exact order, a column index for the shell's lookups (small chunks keep qsort); the game no longer hashes each mesh. The frame log's new columns. |
| `1636caa0` | Chunks keyed in a frame carried across map connections (map coordinates plus a shift, found by matching the cells' own map coordinates between the last snapshot and the new one); a warp starts a frame or takes up its map's last one. After a crossing the kept chunks stand where they belong: off screen, 8 a frame are looked at again; those that changed are built 4 a frame. Only a chunk whose atlas pages still hold the tilesets they held stands. |
| `83b81e7e` | Each atlas slot decided and drawn once a pass (from its first cell, as the full redraw always did). |
| `e3dcc49f` | The interface's palettes (13 to 15) count for the map's art only when a cell in view draws with one (two metatiles of Littleroot Town and the Petalburg Gym do: checked over every tileset); the atlas is redrawn on a map change only when page 0's tilesets change. |
| `0738fcaf` | The camera's target, every walker, the surf blob and the player's pose drawn between the two snapshots across up to 6 game frames (`DioramaSprite_GapAlpha`), not only across one. |
| `055a8e2a` | The terrain's sync key holds the map's unfaded palettes; a change of the faded ones alone (a fade, the time of day's tint, a palette's pulse) looks again only at the chunks with pixel objects. |
| `1868c1c4` | An off-screen chunk on the edge of the view's cells waits, its old mesh standing, until it is wholly inside, near the player or on screen (one that comes into view is built at once); a change of the commonest ground looks again only at the chunks with tree hulls. The waiting list holds every chunk of the view (none dropped). |

### Results (L, the walk above)

| | Before (`cf23908c`) | Mesh builder only (`18ad922c`) | All of the above |
|---|---|---|---|
| Worst sync at a map crossing | 180 to 185 ms (3 runs) | 44 to 65 ms (2 runs) | 24 ms |
| Syncs over 16 ms in the walk | - | 12 | 5 |
| Chunks built in a crossing's frame | 15 to 30 | 15 to 30 | 6 |
| Water's atlas update | 10 to 15 ms | 10 to 15 ms | 0.2 ms |

Checks on the build of the table's first five commits (L): no stale chunk in 32,818 checks
(`PKMN_DIORAMA_TERRAIN_CHECK`); every mesh the same as its voxel build (`PKMN_DIORAMA_MESH_CHECK`, 704 chunks);
screenshots after each crossing, a warp into Mauville's Pokemon Center and back, and a wild battle on a map reached by
a crossing the same as before the changes (only NPCs' wandering and the clouds' shadows differ between runs, as
between two runs of the same build); the 3D unit tests (`make -f Makefile_pc DIORAMA=1 check-diorama`) and the 2D
build pass.

**Route 111 with the Mirage Tower shown** (`055a8e2a`; the same walk, east and back): a snapshot's sync p50 21.9 ms
before, 1.4 and 1.8 ms after (two runs); p99 33.8 ms before, 12.0 and 13.1 ms after; chunk inputs built 9,838
before, 89 after. With the tower not shown both builds behave the same (p50 0.9 ms). A door warp and a wild
battle's start with the terrain and mesh checks on: 0 stale, 0 meshes differ.

**Seventeen maps of every kind** (`1868c1c4`; the region sweep: towns, cities, routes, caves, woods, the sea, each
run east then west along its longest walkable row; the build before it and the build with it, interleaved map by map):

| | Before | After |
|---|---|---|
| Chunks built | 4,072 | 720 |
| Chunk inputs built | 13,327 | 5,376 |
| Sync p50 / p90 | 1.41 / 8.54 ms | 1.08 / 5.78 ms |
| Sync p99 | 17.4 ms | 17.6 ms |
| Syncs over 16 ms / over 33 ms | 49 / 5 | 49 / 2 |
| Worst sync | 36.4 ms (Mossdeep) | 50.4 ms (Route 113: one full atlas redraw, 42 ms, as the volcanic ash's weather changed) |

The typical frame's work fell by about a quarter at the median and a third at p90, and the chunk builds by 82%; the
rare slow frames did not change: they are chunks coming into view all at once (a new area at a connection, 15 chunks
on Route 110 in both builds) and the atlas's redraw on a weather or tileset change. Part of this sweep ran while the
app's test suites ran on the same machine, which adds noise to single frames (both builds alike). Correctness on the
final build: 20 map crossings with the terrain and mesh checks on, 373,268 chunk checks, 0 stale, 3,936 meshes,
0 differ; 8 maps (tree-heavy ones too: Petalburg Woods, Routes 119 and 120, Fortree), 147,622 checks, 0 stale,
1,216 meshes, 0 differ.

**A long session** (a build with the first five commits; Mauville to Route 117 and back over and over at running
speed, 30,000 game frames, 121 map changes, 14 minutes on this machine): the game's memory 256 to 260 MB, flat from
start to end; sync p99 per fifth of the session 18.0, 17.4, 17.4, 16.5 and 17.6 ms (no growth). An hour-long session
on the final build is in section 6.

The running speed and the movement itself are unchanged: nothing above touches the game's movement, only how the 3D
view builds and draws what the game shows.

### Not verified, and what remains

- No frame time on a real graphics card or on the owner's PC: on this machine the drawing itself (software OpenGL)
  takes 40 to 130 ms a frame, so only the CPU's work per frame (the syncs above) is measured here.
- **Remaining**: 1% of the syncs still take more than 16 ms on this machine's CPU (a 60 fps frame's budget), when
  several chunks come into view at once (a new area) or the atlas is redrawn (a weather or tileset change). Building
  chunks that come into view over several frames would show them late; that has not been done.

## 2. Trades

### What was found (code reading of the trade's path, then tests)

A trade runs: the game (its save mailbox) - the native bridge - the companion - the host (TLS). The coordinator
(`live_trade.py`) freezes and exports the party, uploads it, waits for both players' consent, prepares the receipts,
the host commits both sides at once (one SQLite transaction), then each game imports its result and releases its
hold. The ownership rules (no Pokemon lost or duplicated whatever fails) were already sound: every step is journaled
and resumable. What made trades fail, freeze or end for both players:

1. **One host reply later than 5 s ended the trade.** Every host request the coordinator made (status, offer,
   confirm, the recipient's receipt, the canonical head) had one 5-second try; a late reply (a slow link, a busy
   host, a Wi-Fi stall) escaped the trade window, and the launcher then cancelled the whole trade for both players.
2. **That cancel had one try.** If it failed too (another late reply), the game stayed held - the field frozen,
   saving off - until a restart.
3. **The game's trade hold expired after 10 s without a command.** Between its commands the coordinator waits on
   the host; a few slow replies in a row, or a slow upload of the frozen party, passed 10 s: the expired hold closed
   the trade window and the trade ended.
4. **A trade that could not start left its proposal open.** Chosen while another operation (a save) was running, the
   trade was refused locally but its proposal stayed open at the host: the friend waited on it until the host's time
   limit.

### What changed

| Commit | Change |
|---|---|
| engine `cc897dda` | The PC game gives an active trade's hold 45 s (2,700 frames) without a command, not 10 s. The companion's loss is still seen within 3 s by the presence heartbeat, which closes the window as before. GBA ROM unchanged. |
| app `5955acb` | A host request without a reply in time is asked again every second for up to 40 s (each of these requests is a read, or idempotent at the host: the same offer, confirmation, receipt, cancel or acknowledgment again changes nothing), the game's hold kept alive between the tries. A new lease (a reconnect) is never asked again: the trade resumes against its fate, as before. A failed trade's settlement is tried up to 3 times, 5 s apart, on passing failures (no reply, a reconnect, a busy game), with a banner saying it is being ended. A trade that cannot start cancels its proposal (the friend is told it stopped on this side), and a save under way when it was chosen finishes first. |

Ownership and consent are untouched: the host's single commit decides every trade, the coordinator never confirms
for a player, and a retry repeats an identical request.

### Tests

- New: every kind of host reply lost once, on both sides: one exact exchange, each party holding the other's Pokemon,
  no reconnect, the hold kept alive (KEEP_TRADE) meanwhile; the patience ends with the error, and a reply lost as the
  lease changed is not asked again under the new lease; the settlement's retries (passing failures tried again, a
  permanent one not); a refused trade cancels its proposal, and one chosen during a save waits for it.
- The existing lost-reply tests keep their recovery coverage (they run with no patience).
- Trade, launcher, menu and recovery suites (L): 469 passed, 623 subtests, 43 skipped; the setup window's GUI tests,
  which need a display, pass under a virtual one (13 passed).
- End-to-end runs with real game processes: section 6.

## 3. Battles between players

### What was found

1. **Pausing stopped the battle for both players.** Ctrl+P, the survey view (F5) and photo mode (F9) stop the game's
   frames, and with them the bridge to the companion; in a link battle or a held trade the other player and the host
   wait on this game, and a long enough stop ended the battle or the trade.
2. **A response arriving while the bridge's queue to the companion was full stopped the bridge for good**
   ("save control backpressure"), and with it the battle or trade. The menu's and the encounter reset's responses
   already waited for the queue; the save's and the battle's did not.
3. **A battle core that stops itself** (a check fails, MS-71/MS-96) left the battle on screen with no message in the
   game; only the launcher's window said recovery is needed.

### What changed

| Commit | Change |
|---|---|
| engine `7dbbb1c8` | Ctrl+P, F5 and F9 are refused during a link battle or a held trade, with a notice in the 3D game; ending a pause always works. A save or battle response that arrives while the queue is full waits in the game's mailbox (the game leaves it there until its next command) and goes out when the queue drains. |
| engine `891b9e78` | A battle that stopped itself shows, in the 3D game, "This battle stopped. In the launcher: Recover battle, or Abandon battle." while it lasts (its drawing checked on a virtual display with a build that forced it; a battle core stopping itself was not reproduced for this). |

Tests: a bridge unit test (`save_response_waits_for_a_full_queue`) fails on the old code (the bridge closed, the
response never sent) and passes now; `check-native` passes (all native suites). The refusal of a pause during a link
battle was compiled and reviewed, not exercised in a running link battle (the scripted runs cannot press Ctrl+P).

### Open

- The 2D game still shows nothing when a battle stops itself (it has no PC overlay).
- No turn timer: a player who walks away holds the other player's battle until they come back or close the game.
- A battle's bridge lost mid-battle (the game and its companion disconnected locally) is not reconnected; the
  launcher keeps the battle for recovery (by design: the battle's state cannot be proved after it).

## 4. Network tolerance and latency

1. **A write that stalled for a second dropped the player** (app `89a27d5`). The host dropped a player as a slow
   consumer when one write could not drain within 1 s, and the companion gave up on the host (and on its game's
   bridge) the same way. On a lossy link TCP's retransmissions after a few lost packets stall a stream for seconds.
   Steady writes now wait up to 10 s (`drain_timeout`); closing and refusing connections keep 1 s; a dead peer is
   still found by the host's idle timeout (20 s) and the companion's remote timeout. Test: a player whose writes stall
   1.5 s stays connected (failed with the 1 s limit); server, companion, transport and persistence suites: 62 passed.
2. **Trades' late replies** are asked again instead of ending the trade (section 2).
3. Not changed: each save command still waits for its own disk sync, and a battle's blocks go one per acknowledgment
   round trip; measured costs and the risks of changing them are in section 6.

## 5. Stability: crashes, freezes, saves

What this round changed for "a failed multiplayer operation must not permanently freeze the game or corrupt saves":
a trade's late reply, a failed settlement and an expired hold no longer leave the game held (section 2); a pause, a
full bridge queue or a stalled network write no longer end a battle or trade (sections 3 and 4); a battle that stops
itself says what to do (3D game). Saves were never at risk in these paths (every step is journaled; the host's
single commit decides a trade), and every run in section 6 checked the saves and the host's store afterwards.

**MS-93** (a Windows proof's fresh Continue after a 180-minute Tower climb failed with "checkpoint transaction
failed"): run 230's log read again. Not a limit of the Tower's record (its `claims` reached 65535 and `progress` 101,
inside every bound, written during the climb; no CHECK constraint). The storage error wrapped every SQLite failure
except corruption without saying which; it now names SQLite's cause. The likeliest cause, not proved: the database
still locked by the closing session (6 s earlier) folding a large write-ahead log into the file on the runner's slow
disk. Open until the next occurrence names it.

**MS-71** (the owner's crash in a battle between two PCs): still not reproduced; its diagnostics stand.
