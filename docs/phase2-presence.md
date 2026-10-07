# Phase 2 presence prototype

This milestone connects actual Emerald clients through an allocated ROM mailbox, a pinned mGBA Lua bridge, a loopback companion, and a four-player world server. The transport and companion are implemented. Real two-ROM rendering, movement, map, save-exclusion, and reconnect checks remain pending; transport tests alone do not accept Phase 2.

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

`scripts/multiplayer/control_proof.py` runs two real cores, two verified-ROM companions, and one server. It uses different copied flash saves and different UUIDs, records inputs/state in a private transcript, and captures the emulator framebuffers. Actual ROM assertions and results must be recorded before marking this milestone complete.

## Private build and data boundaries

The original engine checkout and its archived baseline remain unchanged. ROM changes belong in the separate `/home/kevin/src/pokemon/engine-multiplayer` worktree on `codex/multiplayer-poc`. ROMs, test flash saves, bridge tokens, logs, and screenshots stay outside Git in the private `multiplayer-proof` directory. Remote avatars must be removed before the engine's ordinary object-save snapshot, so transient actors cannot enter a saved character.

The eventual delivery remains one Windows download with Host Game / Join Game. Development commands, manual script loading, Python, and WSL are not requirements for friends. This prototype is not ready to distribute.
