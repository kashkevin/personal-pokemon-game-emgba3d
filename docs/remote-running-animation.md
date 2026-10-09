# Dedicated remote running: first visual implementation stage

October 9, 2026. The [visual amendment](project-update-maximum-visuals-visible-wild-riding-time.txt)
requires research, preserved assets, multiplayer animation and actual-game checks.
This stage repairs a specific missing animation path. It is not the full player
animation overhaul, followers, mounts, visible encounters or a new art pack.

## Research and selection

The pinned RHH engine already supplies Brendan and May walking/running sheets.
`src/data/object_events/object_event_graphics.h` concatenates their walking and
running tiles into `NormalRunning`; `object_event_graphics_info.h` uses the normal
player animation table, whose dedicated running indices are 20–23 in
`include/constants/event_object_movement.h`. `src/field_player_avatar.c:PlayerRun`
uses `GetPlayerRunMovementAction`. Reusing these frames avoids another object,
sprite, palette, decompression cache or external asset dependency. No asset was
replaced. The separate [resource inventory](graphics-resource-inventory.md)
tracks broader coverage and future selection; inherited terms/credits remain.

Before this change, the ROM published walking for a runner, and the companion
converted network `run` back to the walking mode. Speeding up the remote walk
could not select the already available running artwork.

## Implemented path

An independently verified ROM capability permits movement mode 5 for running.
The main presence ABI remains version 1: 20-byte poses, 88-byte inbound payload,
128-byte mailbox and zero reserved bytes. Old ROMs retain the original strict
mode range and walking fallback. Exact build identity still gates world joins.

`src/multiplayer.c` publishes actual DASH state after bike/surf/underwater
precedence. Remote actors retain normal graphics and use native dedicated run
actions. Completed movement returns to the ordinary standing pose even when
direction has not changed. No speed, running-shoe progression, encounter rate,
ownership or save-layout rule changes.

`presence_animation.py`, `mailbox.py`, `companion.py`, `bridge_config.py`,
`bridge/mgba.lua` and `generate_manifest.py` carry and verify the capability
through the complete path. The Lua layer independently checks the ROM marker
before permitting the new mode. An initial actual-core check exposed its old
mode-4 limit; the repaired bridge and new Lua regression are included below.

The additive native patch is
`engine-patches/phase2-remote-running-animation.patch`, SHA-256
`db38981664160241324443486891d743cc4c11bfb9e868e4fd30ca90a027ddb7`.
Its inputs are preserved privately under
`%LOCALAPPDATA%/PokemonPrivate/artifacts/handoff-audit/remote-running-before-20261009`.
Native base: `aef47e4b28fd6d0e84376961e0cc6632996bb0be`, inherited RHH
`bb1093a7c72d3961d9a37d8e02ad2abc2c866682` plus existing project changes.

## Verification and limits

- Fresh separate `emerald-visual-20261009-1` build completed with `DEV=0`,
  `LOCAL_RESET_STATIC=1`. ROM SHA-256
  `f99bfa4e19ccb5ba998b54d2151986665c15bed3b2d28dab10340d59be3a1d65`;
  manifest `f97dffa70c4edf93de4f90202f8fe08a5a3a499cb2113574c73881321b4bb7e1`.
  Linker use: EWRAM 235096/262144 bytes, IWRAM 28376/32768, ROM 26805220/33554432.
  Compared with the immediately preceding effects build, EWRAM/IWRAM usage is
  unchanged and linked ROM use rises by 108 bytes. `arm-none-eabi-nm -S` reports
  `sRemotes` as 84 bytes and `gHeap` as 115968 bytes in both ELFs; the movement
  tracking byte uses existing struct padding. This measures allocation, not
  runtime frame pacing.
  Make reported clock skew; outputs were subsequently exercised, not accepted
  solely because make exited successfully.
- 31 Python codec/companion/setup-widget tests passed in 3.080s. Real Lua 5.4
  transport tests passed with mocked emulator/socket APIs, including legacy
  mode refusal, missing-marker refusal, running publication and snapshot commit.
  Tests: `test_presence_animation.py`, `test_companion.py`, `test_mailbox.py`,
  `test_launcher_setup_gui.py`, `test_mgba_bridge.lua`. These are not gameplay.
- Two actual pinned mGBA cores loaded copied saves through ordinary Continue and
  moved with ordinary joypad commands. The observer's real native sprite selected
  east 23, west 22, south 20 and north 21, remained visible, then settled at the
  sender's coordinates and matching relative pixels. All four framebuffers were
  visually inspected. Subsequent walking and stop states returned to the normal
  animation table. This is reused running artwork, not newly authored motion.
- All 28 recorded diagnostic actions preserved both party hashes. No remote
  actor IDs appeared in saved object slots. Original and copied save-file hashes
  remained unchanged. No in-memory party/position injection was used.

Private actual-core evidence:
`/home/kevin/src/pokemon/multiplayer-proof/remote-running-20261009-2/evidence-3`.
Receipt `../evidence.json` SHA-256
`3bbd49050a81c19387f8d124649b679ee1dea23f2170c8c261e5939bdc81948d`;
`actions.jsonl` SHA-256
`f57925a69ed6f3ef14417e80a35755dc8a73aa25c84248c3c20215cb7d07b5bd`.
Frozen source archive SHA-256
`5d8edc236c27fd4bd98ea2039cabb8a495b339e792dcd24b68b14805fcfcf7fe`;
harness SHA-256
`e37e6d125079c141fbaa5f02b4b55f3c0918ba5d5d24c97ba857dd01804350a5`.
Earlier evidence is retained: run 1 exposed the Lua limit; run 2's initial script
sent inputs during the title sequence and never entered the field. Neither is
retroactively marked passed. The inspected successful run is `evidence-3`.

Limits: Brendan on one map with two headless WSL cores over loopback. May,
customized bodies, four-client frame pacing, transitions, fishing, surfing,
weather pressure and physical Windows controls are not qualified by this run.
Wire sizes and configured update rates are unchanged; measured network/frame
cost under the requested full visual load remains UNKNOWN. Existing local
time tint visible in captures is not a synchronized world-clock implementation.
