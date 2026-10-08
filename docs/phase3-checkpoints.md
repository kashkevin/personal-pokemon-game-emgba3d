# Durable checkpoint foundation

This slice implements authenticated, revisioned server checkpoints and recovery of ordinary game saves while the emulator is closed. It advances the existing Phase 3 plan. It does not complete the live ROM export/import path or change the accepted save architecture and gameplay policies.

This is the preserved `DURABLE_CHECKPOINT_POC` record. The subsequent [live checkpoint slice](phase3-live-checkpoints.md) now verifies explicit ROM export/import with running cores; the closed-game tools and their boundaries below remain supported.

## Implemented boundaries

- Each provisioned player has a server-issued UUID and a private 32-byte credential. The server stores the credential hash. One active lease owns that player's checkpoint operations.
- SQLite retains a stable world identity, monotonic boot/session epochs, and complete per-player revision history. A process lock prevents a second live host from taking over the database. Restart fences abandoned leases.
- A checkpoint commit checks the expected revision and build/ruleset/save-layout bindings and commits before acknowledging success. Exact transaction retries return the original result; a different transaction cannot overwrite a newer revision using an older base.
- Bounded, sequential transfers share the companion connection with presence and heartbeats. Incomplete uploads are discarded on disconnect or timeout. Downloads check the complete container hash and current revision on every chunk.
- The pinned save parser validates both ordinary Flash banks, sector checksums, counters/rotation, trainer/party/PC/map bounds, Pokémon checksums, and absence of temporary remote avatar IDs. It preserves the full 128 KiB Flash and the optional known 16-byte mGBA RTC footer. Server hashes cover the entire container.
- The first accepted ordinary save establishes the player's trainer ID binding. Later uploads must retain it; changing the enrolled trainer requires a future explicit import/migration policy. Pokémon original-trainer fields remain independent so future legitimate trades are possible.
- Closed-game restoration stages and fsyncs the save and sidecar, archives changed/damaged local copies, and checks identity and revision bindings. A hash disagreement after interruption is detected rather than treated as a trusted mirror. The launcher/core must hold the cooperative save lease throughout gameplay.

The parser intentionally rejects an interrupted/malformed nonempty bank instead of silently choosing its older recovery bank. It cannot prove which ROM produced an otherwise compatible Flash layout; the verified ROM manifest and explicit checkpoint envelope supply the build binding. SaveBlock3's four bytes and the special opaque sentinel sections lack upstream semantic checksums; they are preserved and covered by the container hash. They are not newly authenticated by the parser.

## Development verification

Run the Python tests from the repository with `PYTHONPATH=src` and `python -m unittest discover -s tests -q`. The tests exercise interrupted database writes, host locking, revision conflicts, old leases, wrong credentials, exact retries, bounded transfers, corruption, and mirror recovery. Synthetic fixtures contain no real player saves.

`scripts/multiplayer/checkpoint_proof.py` is a WSL development tool using the existing official libmGBA core harness and the mailbox bridge. It starts two real games from separately enrolled ordinary saves, changes and saves player A through normal joypad inputs, checkpoints A without changing B's canonical save, restarts the host, restores a damaged local mirror while both games are closed, and boots fresh cores to verify positions, parties, and remote avatars. Its inputs are copies of the accepted movement saves. Private profiles, database, saves, logs, and screenshots stay outside Git.

On 2026-10-07, two complete real-core runs passed all eight recorded checks. Both restored player A at `(5,11)` and player B at `(5,9)` in Littleroot with their original complete party hashes, one visible remote avatar per core, and no serialized remote IDs. Player A advanced from revision 1 to 2 while player B remained at revision 1. [Source-only acceptance evidence](../scripts/multiplayer/checkpoint-evidence.json) records the checks and hashes. The complete Python suite passed 115 tests on Windows Python 3.14 and WSL Python 3.12, including read-only validation of the private accepted saves.

The current save profile is `rhh-1.17.1-bb1093-presence-v1`. This remains the baseline expansion plus the presence patch, not the completed Gen 6 game profile. Save-format changes require a new binding and explicit migration.

## Work remaining

The subsequent [live ROM handshake](phase3-live-checkpoints.md) now freezes ordinary field mutations, streams coherent state, applies a canonical revision, and acknowledges completion. Its special-sector and fatal-Flash-error limits remain explicit. Per-Pokémon ownership identities and transaction hooks remain necessary before trade, shared rewards, or economy changes. Do not infer a trade guarantee from ordinary save storage alone.

Autosave frequency, server-loss/local-play behavior, interrupted battle policy, and remote-avatar collision remain unresolved. This slice chooses none of those policies. Windows GUI integration, four actual ROM clients, LAN/Internet acceptance, transport encryption, and the downloadable Host/Join package still need implementation and testing.

The [Local Soft Reset amendment](local-soft-reset.md) stays queued behind these foundations and the encounter/RNG systems. No reset button, shiny-rate change, wild encounter change, or event reroll path is implemented by this checkpoint work.
