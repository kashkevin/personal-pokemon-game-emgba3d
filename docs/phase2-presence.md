# Phase 2 presence prototype

The localhost two-client movement prototype is verified as of October 7, 2026. Two actual Emerald ROM cores connect through an allocated mailbox, the pinned mGBA Lua bridge, separate loopback companions, and the world server. They render each other and pass independent movement, map/menu/battle, pause, disconnect/rejoin, server restart, and ordinary local save/reload checks. This accepts the local movement checkpoint; Windows GUI/LAN, four actual ROM clients, and Internet delivery remain unverified.

The ruleset identity is `baseline-rhh1.17.1-mailbox-v1`. It preserves the unchanged engine's default gameplay settings while testing networking. It does not claim the final Gen 6 profile, starters, encounters, followers, trades, or multiplayer battles.

## Implemented transport

- Four players total, including the host. Each has a different canonical UUID. Duplicate active identities and a fifth player are rejected.
- TCP carries bounded, four-byte-length-prefixed UTF-8 JSON objects. Protocol, exact ROM SHA-256, and ruleset must match before admission.
- Presence includes independent map identity, map epoch, coordinates, direction, elevation, appearance, movement mode, and activity. Older sequences and map epochs cannot overwrite a newer position.
- Every admission receives a new session epoch. Disconnect removes the transient player; rejoin creates a new lease. This is not durable character storage.
- Heartbeats and inactivity cleanup run in the companion/server independently of emulation. A paused game becomes unavailable and its remote avatar should disappear.
- Outbound presence is coalesced into one current snapshot. Reliable control queues and drain timeouts are bounded. Slow consumers cannot accumulate unlimited movement history.
- The server defaults to localhost. Explicit RFC1918/ULA LAN addresses are supported. Public binds and public-source clients are disabled in this development version. Authentication, TLS, player packaging, and Internet hosting are later work.

The companion validates the actual ROM against the generated manifest, and listens only on loopback for one emulator bridge. Its binary frames are at most 256 bytes. Authentication is `H` plus a private 32-byte token, outgoing game poses are `P` plus 20 bytes, and inbound snapshots are `S` plus 88 bytes. These local tokens are not Internet player authentication.

The 128-byte mailbox has separate odd/even generations for ROM publication and external updates. The external bridge writes only its inbound range, offsets 36–127. It checks ROM CRC/size, mailbox magic/version/size, and address bounds before those writes. The companion also checks ROM SHA-256. The address is extracted from `gMultiplayerMailbox` in this build's ELF, rather than copied from a vanilla ROM address table. No bridge writes to Pokémon, inventory, save blocks, or player controls.

This first ABI supports overworld/unavailable activity. Bike variants share a transport representation; underwater mode is unavailable. Full appearance and travel-mode fidelity still need gameplay testing and later extension.

Remote avatars in the controlled rendering prototype are nonblocking and noninteracting. This temporary development assumption does not finalize player collision or interaction behavior for the game.

## Development verification

October 7, 2026: **44 Python tests pass on Windows Python 3.14**. They include real TCP server/companion sessions, four-player capacity, fragmented/oversized messages, build/ruleset mismatch, duplicate identity, stale map/session data, pause, reconnect, malformed world snapshots, slow consumers, and closing listeners with active clients. The last check caught and fixed a shutdown deadlock under Python 3.14.

The same 44 tests also pass under Ubuntu WSL Python 3.12, which runs the real-core integration tools.

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
python -m unittest discover -s tests
```

The standalone Lua regression test verifies partial IPC sends/receives, authentication ordering, atomic snapshot writes, duplicate peer rejection, ABI/ROM identity rejection, and mailbox write boundaries:

```bash
lua5.4 tests/test_mgba_bridge.lua bridge/mgba.lua
```

`scripts/multiplayer/harness.c` is a separate project-owned frontend for the official mGBA 0.10.5 core. It loads real Lua and sends emulated joypad input; framebuffer PNGs and read-only memory inspection collect gameplay evidence. It has no generic RAM-write command. A core probe has confirmed scripting initialization, checksum reads, and frame callbacks. It is a development tool, not the Windows game package.

`scripts/multiplayer/control_proof.py` runs two real cores, two verified-ROM companions, and one server. It uses different copied flash saves and different UUIDs, records inputs/state in a private transcript, and captures the emulator framebuffers. Assertions compare actual ObjectEvent tiles and sprite visibility against the other ROM's local pose. Settled walking avatars must also have the exact relative pixel displacement, so correct network coordinates alone cannot hide a rendering error.

## Actual two-client results

The accepted ROM is engine commit `37ca07e1c623dda5aea7ac7c68de588e48e52c94`, based on the preserved baseline. Its SHA-256 is `28605b780d9154f5ff95fe76724d232ca198383bae127341ab2882316395e4a9`; the ELF SHA-256 is `2d1ae08176c584e4bfa66fef5b590f5a2b76b62773822f72fd2952fbdfdc2195`. The source delta is [phase2-presence.patch](../engine-patches/phase2-presence.patch), and the ABI is described in [rom-mailbox.md](rom-mailbox.md).

| Check | Observed result |
| --- | --- |
| Two real games | Different trainers and copied Flash files loaded through ordinary Continue. Each game rendered one visible remote avatar in Littleroot. |
| Independent movement | Moving either player left the other's local position unchanged. Simultaneous movement passed tile and relative pixel checks on both clients. |
| Walking animation | Successive captures show a remote step progressing through intermediate pixel positions before settling. Normal held movement remains active between network updates. |
| Menus | Opening A's Start menu removed temporary actors and marked A unavailable; B continued on the field. Closing the menu restored both avatars. |
| Pause | Advancing only A for over a second removed paused B from A's game without dropping either server session. Advancing both restored visibility. |
| Companion disconnect/rejoin | Closing B's companion removed both copies of its transient connection state. Rejoining the same identity restored one actor per game, with a new admission epoch. |
| Server restart | Stopping the server left both games playable with no remote actors. Restarting it on the same endpoint reconnected both companions and restored correctly placed avatars. |
| Interior and route transitions | B entered/exited Brendan's house; A walked between Littleroot and Route 101. Different-map actors disappeared and same-map actors returned without duplication. |
| Separate battle | A encountered a real level 3 Wurmple while B moved independently in Littleroot. A became unavailable, escaped normally, and later reunited with B; both avatars returned at the correct tiles and pixels. |
| Ordinary local save | A saved at Littleroot `(6,11)` using the ordinary Save menu and explicit overwrite confirmation. After waiting for completion, normal field play and both avatars resumed. |
| Save exclusion and reload | Saved object arrays contained no local IDs 241–243. Fresh processes restored A's `(6,11)` and B's independent `(5,9)` position, party counts 2/0, and the same complete 600-byte party hashes. Independent inspection also checked the actual Flash sector checksum, serialized party, and object IDs. |

The movement test exposed a persistent seven-pixel offset when an avatar spawned during a partial local camera step. The adapter now uses the engine's normal positioning API after spawning and after a completed movement action. Retests pass exact relative pixel checks during simultaneous local movement, menu returns, reconnects, and interior returns.

Early exploratory assertions also caught insufficient button holds and checking the field before ordinary Flash saving had finished. Those assertions are retained in private exploratory transcripts; they are not counted as passing checks. The final accepted run waits 1,200 emulated frames after overwrite confirmation, observes the returned field, and verifies a fresh Continue. No party/save RAM write, cheat, or savestate manufactured gameplay progress. The Lua bridge writes only its dedicated inbound mailbox range.

Final whole-file Flash SHA-256 values are A `8d611857e848f68ff3624d8540704d7e70ed4115326f82e304408587df9f3bf6` and B `5688844e0799be76a91183ef37429a52449f2104e9efbde6d2ac7a381ca9f910`. B remains an independent pre-starter character; this does not claim that both clients have completed the campaign or battle progression.

The private final evidence is in `/home/kevin/src/pokemon/multiplayer-proof/run-4` and `run-5`, archived under `C:\Users\kashh\AppData\Local\PokemonPrivate\artifacts\multiplayer`. [evidence.json](../scripts/multiplayer/evidence.json) stores source/build identities and sanitized results. Generated scripts contain private loopback tokens and stay outside Git. Read-only save offsets are specific to this pinned engine profile and must be reverified when its layouts change.

The harness advances emulation in controlled batches with network yields. These results establish behavior on this PC, not normal Windows GUI frame pacing or measured Internet latency. Four simultaneous ROM clients, dense-map sprite/palette pressure, bicycle/surfing/follower appearance, sustained play, LAN interruption/latency, and Windows automatic bridge loading need further runtime checks. The four-player capacity unit tests establish server admission limits, not four-player graphics performance.

## Private build and data boundaries

The original engine checkout and its archived baseline remain unchanged. ROM changes belong in the separate `/home/kevin/src/pokemon/engine-multiplayer` worktree on `codex/multiplayer-poc`. ROMs, test flash saves, bridge tokens, logs, and screenshots stay outside Git in the private `multiplayer-proof` directory. Remote avatars must be removed before the engine's ordinary object-save snapshot, so transient actors cannot enter a saved character.

The eventual delivery remains one Windows download with Host Game / Join Game. Development commands, manual script loading, Python, and WSL are not requirements for friends. This prototype is not ready to distribute.
