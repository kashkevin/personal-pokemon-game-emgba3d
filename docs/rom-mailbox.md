# Phase 2 ROM presence mailbox

This adapter belongs to the independent-player movement proof. It adds a bounded volatile mailbox and up to three temporary remote avatars to the pinned, otherwise unchanged engine. It does not add generation rules, Pokémon, followers, battles, trades, party synchronization, inventory synchronization, or canonical server saves.

The adapter's localhost two-client checkpoint is verified at engine commit `37ca07e1c623dda5aea7ac7c68de588e48e52c94`. The actual mGBA/Lua/server results and their Windows/LAN/four-client limits are recorded in [the Phase 2 report](phase2-presence.md).

## Source and ownership

The source baseline is RHH commit `bb1093a7c72d3961d9a37d8e02ad2abc2c866682`, preserved at the `BASELINE_BUILD` tag. Presence work is isolated in `/home/kevin/src/pokemon/engine-multiplayer`, branch `codex/multiplayer-poc`. The normal baseline checkout and archived baseline ROM remain separate.

The reproducible source delta is [phase2-presence.patch](../engine-patches/phase2-presence.patch). Apply it to that exact upstream commit. Its files are `include/multiplayer.h`, `src/multiplayer.c`, and small hooks in `src/main.c`, `src/overworld.c`, `src/event_object_movement.c`, and `src/load_save.c`.

`gMultiplayerMailbox` is linker-visible EWRAM, allocated by the compiler. The bridge manifest must derive its address from the matching ELF and verify the exact ROM hash. It must never reuse an address from a different ROM build. No save block includes the mailbox.

## ABI version 1

All integers are little endian. A pose is 20 bytes, a remote peer is 24 bytes, and the mailbox is exactly 128 bytes. Compile-time size and offset assertions enforce the ABI.

| Mailbox byte offset | Size | Field | Writer |
| --- | ---: | --- | --- |
| 0 | 4 | `magic = 0x31504D45`, bytes `EMP1` | ROM |
| 4 | 2 | `abiVersion = 1` | ROM |
| 6 | 2 | `byteSize = 128` | ROM |
| 8 | 4 | `frame` | ROM |
| 12 | 4 | `localGeneration` | ROM |
| 16 | 20 | `local` pose | ROM |
| 36 | 4 | `inboundGeneration` | Bridge |
| 40 | 4 | `connectionFlags`, bit 0 means connected | Bridge |
| 44 | 4 | `heartbeat` counter | Bridge |
| 48 | 4 | `rosterEpoch` | Bridge |
| 52 | 1 | `selfSlot`, 0 through 3 | Bridge |
| 53 | 1 | `peerCount`, 0 through 3 | Bridge |
| 54 | 2 | Reserved, zero | Bridge |
| 56 | 24 | Remote peer 0 | Bridge |
| 80 | 24 | Remote peer 1 | Bridge |
| 104 | 24 | Remote peer 2 | Bridge |

Each peer begins with a nonzero 32-bit session `playerId`, followed by a pose. Entries after `peerCount` are ignored. The three peer identifiers must be distinct. They are ephemeral session identifiers, not Pokémon ownership identifiers or save identities.

| Pose byte offset | Size | Field |
| --- | ---: | --- |
| 0 | 4 | `mapEpoch` |
| 4 | 4 | `frame` |
| 8 | 2 | Signed tile `x`, without the engine's seven-tile `MAP_OFFSET` |
| 10 | 2 | Signed tile `y`, without `MAP_OFFSET` |
| 12 | 1 | `mapGroup` |
| 13 | 1 | `mapNum` |
| 14 | 1 | Direction: 1 south, 2 north, 3 west, 4 east |
| 15 | 1 | Elevation, 0 through 15 |
| 16 | 1 | Avatar gender: 0 male, 1 female |
| 17 | 1 | Movement mode: 0 walking, 1 Mach Bike, 2 Acro Bike, 3 surfing, 4 underwater |
| 18 | 1 | Activity: 0 unavailable, 1 ready overworld |
| 19 | 1 | Reserved, zero |

An unavailable pose retains its last valid coordinates and appearance, with map identity updated from the current save location when available. The initial direction defaults to south. Consumers must respect `activity`; retained coordinates do not mean the player is still active on the field. `mapEpoch` increases before every `ApplyCurrentWarp`, including transitions to a connected outdoor map and a warp to the same map. It also increases whenever the published map identity changes, covering a Continue load that updates the save location without the ordinary warp path. One warp may therefore advance the epoch twice; epochs are monotonic markers, not a count of visited maps. The ROM frame counter continues in title, menu, battle, and field scenes when emulation advances. A paused emulator does not invent frames or gameplay progress.

## Stable snapshot publication

The ROM publishes its local pose by writing an odd `localGeneration`, copying the pose, and writing the following even generation last. Readers accept a pose only when the generation is even and unchanged before and after the read.

The bridge follows the same contract for inbound state: write an odd `inboundGeneration`, write all fields at offsets 40 through 127, and commit the following even generation last. The ROM copies at most three peers and confirms the generation stayed unchanged before accepting the snapshot. An odd or torn snapshot does not replace the previous accepted state. Generation and frame comparisons support ordinary unsigned wraparound.

The bridge should publish a new heartbeat at least once every 30 emulated frames. After 180 advancing ROM frames without a changed heartbeat, the ROM removes all remote avatars. The external companion remains responsible for real-time connection and pause detection. A committed disconnect snapshot removes avatars immediately on the next ROM tick. A changed roster epoch clears old avatar ownership before rebuilding the accepted roster.

The ROM validates count, connection bits, reserved fields, distinct player IDs, directions, elevation, appearance, activity, and nonnegative coordinates. Network epoch zero is valid. It compares a peer's map identity with the currently loaded map before checking that map's bounds. Older frame data for the same peer is ignored until a new roster establishes a fresh session.

## Temporary avatar lifecycle

The adapter draws only when `CB2_Overworld` and `CB1_Overworld` are active, the player and its sprite are valid, palette fading is inactive, and script controls are unlocked. It removes avatars before callback changes away from the field, before map changes, during unavailable field states, and on stale or disconnected network state.

Remote objects use local IDs 241, 242, and 243. They are created from complete, zero-initialized local templates using `SpawnSpecialObjectEvent`, with `MOVEMENT_TYPE_NONE`. No NPC template is modified. The adapter checks for a free object slot, sprite slot, and required palette capacity before allocating. Pool exhaustion hides an avatar; it does not overwrite the player, an NPC, or a generated wild object. Objects outside the normal nearby rendering window are removed and can respawn when visible.

Movement uses normal held-movement actions. A one-tile update walks normally; a short backlog uses faster walking, one action at a time. A difference greater than four tiles or a map epoch change uses an absolute correction. After spawning and after a completed movement action, `MoveObjectEventToMapCoords` anchors the sprite using the engine's partial-camera offsets; an active step keeps its normal pixel interpolation. Network coalescing may approximate intermediate turns, so this proof does not guarantee exact remote route replay. Avatar movement mode selects the corresponding existing graphics; full bicycle, surfing, and environmental effects need later acceptance checks.

Remote avatars are nonblocking and have no interaction event in this controlled proof. Object collision and interaction searches explicitly skip owned remote objects. This is a temporary prototype assumption; production collision and player interaction rules remain undecided.

`SaveObjectEvents` normally copies every live object slot. Its hook removes and clears owned remote objects before that copy and suppresses redraw through the following frame. This prevents remote actors from being restored as ordinary NPCs after saving. Multiplayer code adds no save schema fields and never writes a party, inventory, flags, or NPC templates.

## Read-only test fields

The test harness must obtain symbol addresses from the matching ELF. It may read these stable fields for this pinned engine build:

| Structure | Stride | Useful offsets |
| --- | ---: | --- |
| `gObjectEvents` | `0x24` | Active bit 0 at 0; graphics ID at 4; local ID at 8; map number/group at 9/10; tile x/y at 16/18; facing direction low nibble at 24; sprite ID at 35 |
| `gSprites` | `0x44` | Pixel x/y at `0x20`/`0x22`; pixel offsets at `0x24`/`0x26`; animation number at `0x2A`; object index in `data[0]` at `0x2E`; in-use bit 0 and invisible bit 2 at `0x3E` |

`gSprites` has 64 usable sprites plus one dummy entry. Compare settled object tile coordinates minus seven against the expected peer pose, and inspect changing sprite pixels during a step to distinguish animated walking from teleport-only updates. Tests must not write party, save, NPC, or player structures to manufacture a passing result.

## First build budget

The current presence build uses 226,660 bytes of EWRAM, 28,376 bytes of IWRAM, and 26,750,756 bytes of ROM. Relative to the untouched baseline, this adds 244 bytes of static EWRAM and 2,336 bytes of ROM, with no IWRAM increase. These are linked static sizes, not measurements of every runtime heap or graphics allocation.

Two-client reconnect and ordinary local save lifecycle checks passed. Four-player rendering, dense maps, environmental effects, Windows GUI/LAN, and server persistence remain later acceptance checks. `MULTIPLAYER_POC` identifies the verified localhost two-client scope only.
