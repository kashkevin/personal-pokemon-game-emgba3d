# Live ROM checkpoint foundation

This Phase 3 slice adds explicit saving and canonical recovery while a game core remains running. It extends the [durable checkpoint foundation](phase3-checkpoints.md). The two-player development proof exercises actual modified ROMs through official libmGBA, ordinary joypad input, and the production Lua bridge. The downloadable Windows launcher and automatic-save policy remain future work.

## Transfer and recovery

The ELF manifest declares a separate 512-byte save mailbox alongside the existing 128-byte presence mailbox. The bridge verifies the ROM hash and allocated ranges. It writes only those inbound mailboxes; the ROM owns serialization, validation, Flash programming, and loading. Read-only harness diagnostics inspect RAM, framebuffer pixels, and an official core Flash clone. There are no emulator savestates or external writes to party/save RAM or an open `.sav` file.

Each command carries the current bridge incarnation, authenticated server lease epoch, operation UUID, sequence, revision, offset, size, and chunk CRC. The protocol bounds reliable queues and transfers 128-byte chunks. An exact duplicate of the last accepted command returns its cached response; conflicting or older commands are rejected. Save traffic shares the connection with presence and heartbeats.

An export starts only in a stable ordinary overworld scene. Menus, scripts, battles, transitions, link states, and timed challenge areas cannot begin this operation. The ROM holds that player's gameplay callbacks, playtime updates, and both 16-byte RNG streams while normal save code serializes the current character. The companion validates the complete Flash image and durably journals its exact bytes, expected revision, and transaction UUID before uploading. SQLite acknowledges the committed revision before the ROM is released. A lost acknowledgment leaves an exact retry journal; it never silently substitutes a newer base revision.

Recovery downloads and checks the player's canonical identity, build/profile, full-container SHA-256, save structure, and current revision. The ROM streams the selected logical save into the inactive ordinary Flash bank, using its existing sector buffer. It validates sections, trainer ownership, counters, rotation, and the complete stream CRC. Sector signatures remain unpublished until staging succeeds. Finalization publishes signatures, checks readback, and loads the save. The companion reads back the full Flash while the ROM is still held and verifies the normalized logical state. The final acknowledgment follows the normal Continue path reaching the overworld.

Canceling an incomplete import erases and verifies the staging bank, preserving the current RAM state and active save. A 600-frame idle-command watchdog performs the same cleanup. After publication, cancellation finishes canonical loading rather than pretending the committed save can be undone. Flash failures can keep the game held for recovery. The other player's core, presence connection, and canonical revision remain independent.

Initial binding rejects an older lease epoch, or a lower bridge incarnation within the same lease. A newer lease permits the incarnation counter to restart. An exact lost initial acknowledgment can be retried, but an old binding cannot reset the command sequence after it has progressed. Ordinary native game reboots are detected even if the frontend emits no reset callback; the local bridge reconnects with a fresh incarnation while the world lease remains active. A fatal Flash erase/load error stays held and requires closing the core and performing verified closed-game canonical recovery. A reconnect alone does not clear that error.

## Save mailbox ABI 1

All integers are little endian. `gMultiplayerSaveMailbox` is compiler-allocated EWRAM; derive its address from the matching ELF every build. Both control slots use odd/copy/even generation publication.

| Offset | Bytes | Field / writer |
| ---: | ---: | --- |
| 0 | 4 | `EMS1` magic / ROM |
| 4 | 2 | ABI 1 / ROM |
| 6 | 2 | Size 512 / ROM |
| 8 | 4 | Advancing frame counter / ROM |
| 12 | 4 | Operation state / ROM |
| 16 | 8 | Reserved zero / ROM |
| 24 | 4 | Command generation / bridge |
| 28 | 240 | Command / bridge |
| 268 | 4 | Response generation / ROM |
| 272 | 240 | Response / ROM |

Each 240-byte control is `<II16sIIIIBBHI192s>`: incarnation, session epoch, raw UUID, sequence, offset, total Flash size, revision, opcode, status, data length, CRC32, and zero-padded data. The 192-byte capacity carries fixed 128-byte Flash chunks. CRC32 covers the declared data length only. Commands have status zero; READ requests have empty data. READ replies echo the requested offset; WRITE replies return the next offset.

Opcodes are BIND=1, BEGIN_EXPORT=2, READ=3, END=4, BEGIN_IMPORT=5, WRITE=6, COMMIT=7, CANCEL=8, QUERY=9. Sequence increases across operations within a binding. BEGIN_EXPORT returns `<II32s>` (save counter, rotation, both RNG states). BEGIN_IMPORT takes `<IIII>` (whole-Flash CRC32, source counter, source rotation, trainer ID). QUERY returns `<IIII32s>` (state, next offset, running CRC32, save counter, both RNG states). END returns the readback CRC32. Import COMMIT holds the loaded canonical state until the complete READ/END acknowledgment path.

The existing length-prefixed loopback protocol adds capability `V` plus `<HHHH>(1,512,240,192)`, command `C` plus one control, and response `R` plus one control. Old presence-only manifests remain supported without advertising the new capability. The Python codec and C compile-time assertions define the full status/state enums and enforce sizes.

## Storage boundaries

Live transfers contain the cartridge's 131,072 Flash bytes. The emulator owns its optional 16-byte RTC footer, which is excluded from the live mailbox and left under normal mGBA handling. A live checkpoint therefore cannot back up or restore that frontend RTC metadata after total local-file loss. Earlier complete 131,088-byte closed-game snapshots remain supported in server history.

Import legitimately changes bank counters and rotation. Its actual Flash hash can differ from the server container hash while the normalized logical state matches. A separate immutable live-apply receipt records both hashes and the identity/revision bindings. It does not falsely label an open native save as an exact closed-game mirror. Normal core writeback must still persist the mapped Flash; a ROM acknowledgment alone does not promise a host filesystem flush.

The four special sectors outside the ordinary rollback banks must already match the imported image exactly. Imports that would change them are rejected. Hall of Fame and other features using those sectors need an additional recovery design before broader gameplay acceptance. This slice does not establish transactional trade safety, persistent per-Pokémon identities, or protection against arbitrary malicious ROM clients.

The live build uses a new ROM hash and fresh test world/profiles. The accepted baseline, presence build, earlier world databases, and original player saves are preserved. The structural profile remains `rhh-1.17.1-bb1093-presence-v1`; the exact ROM hash is also required. No silent database/build migration occurs.

## Verification and next work

The accepted live ROM source is `d18dd9320cc0fefab50855e55415260e82d69c65`, built in `/home/kevin/src/pokemon/engine-live-checkpoint`. ROM SHA-256 is `6aa83dbf923d8fda52dc6d81c92e6b6a6ed6678acb758423437baa4793b9944a`. The [source-only delta](../engine-patches/phase3-live-checkpoints.patch) applies after the Phase 2 presence patch at `37ca07e1c623dda5aea7ac7c68de588e48e52c94`; `git apply --check --whitespace=error` passed against that untouched checkout. The normal build uses 228,016 bytes EWRAM, 28,376 bytes IWRAM, and 26,755,628 bytes linked ROM. Compared with presence, that adds 1,356 EWRAM bytes and 4,872 ROM bytes, with no IWRAM increase. These are static linker measurements, not peak heap/stack measurements.

`scripts/multiplayer/live_checkpoint_proof.py` creates fresh private output and copies its input saves. It drives two actual cores, keeps player B moving while A transfers, and checks positions, full party hashes, remote avatars, leases, revisions, readback, and a fresh Continue. The source-only acceptance evidence records the completed checks; private databases, credentials, saves, ROM/ELF artifacts, logs, and screenshots stay outside Git.

On October 7, 2026, two complete runs on that exact final build passed all 12 recorded checks each. They verified menu refusal without save mutation, an exact lost-BIND retry, stale rebinding refusal, held playtime and both RNG streams, independent movement during export/recovery, partial-import cancellation, exact/conflicting duplicate handling, idle watchdog cleanup, wrong-trainer and whole-stream CRC rejection, normal native save writeback, fresh Continue, and live-save rebinding after ordinary A+B+Start+Select reboot. Player A's recovery preserved its two-Pokémon party and location `(5,11)`; player B retained its independent canonical revision. Both world leases survived. The final extra checkpoint after native reboot produced revisions A=3, B=1. [Recorded evidence](../scripts/multiplayer/live-checkpoint-evidence.json) contains the checks and hashes. Private Windows archives are under `C:\Users\kashh\AppData\Local\PokemonPrivate\artifacts\live-checkpoints`, including integrity-checked SQLite backups.

Measured headless transfers took roughly 17 seconds for export and 35 seconds for full recovery on this machine while the test suite also ran. These are development harness timings; no Windows player-experience performance target is claimed.

Run the Python suite with `PYTHONPATH=src` and `python -m unittest discover -s tests -q`. Coordinator fault tests use the real checkpoint client, SQLite store, and mailbox codecs with simulated ROM replies; they complement the actual ROM proof. They exercise unknown commit outcomes, lost final acknowledgments, stale heads, concurrent wrappers/writers, wrong bindings, cancellation, corrupt journals, and failed recovery receipts.

Next Phase 3 work is stable Pokémon ownership and mutation hooks, followed by the planned trade/battle proofs. Autosave timing, visible pending-save behavior, server-loss/offline play, and interrupted battle policy still need decisions. Four actual clients, Windows GUI integration, LAN/Internet acceptance, transport encryption, and the downloadable Host/Join package remain unverified.

The [Local Soft Reset feature](local-soft-reset.md) remains queued behind its encounter/RNG foundations. This change adds no encounter reset command, shiny-rate change, hunt counter, or event reroll path.
