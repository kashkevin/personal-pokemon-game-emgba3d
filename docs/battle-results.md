# Durable completed battle history

The trusted `BattleDesk` can now archive a completed 1v1 or four-trainer 2v2 result. Every participant must first prove the same fixed-side outcome and exact restoration of their original party. Every correlated native RELEASE must then succeed. The final result commits before the server removes its last interaction barrier. A canceled invitation, partial release, conflicting outcome, timeout or disconnect does not create a result.

The history record contains the battle and generation IDs, exact consent fingerprint, ordered players, format, outcome, canonical checkpoint references, and a digest of all BIND/PREPARE/START/finish/RELEASE receipts. The even slots form side 1 and the odd slots side 2; outcome 3 is a draw. It contains no credentials, RNG, Pokémon bytes or monetary reward. The receipt digest identifies the trusted coordinator's evidence; it does not attest a hostile client or reconstruct missing receipts.

## Reuse and storage

This adapts the existing project-owned Desk, native receipt validation, authenticated challenge channel and SQLite storage conventions. The pinned engine and maintained upstream native link return paths supply the outcome/restoration foundation; they do not supply independent-player host history. The existing [battle and menu audits](native-players-menu.md) record the engine revisions and source reuse. No new third-party implementation is incorporated.

Python's existing [sqlite3 module](https://docs.python.org/3/library/sqlite3.html) supplies parameterized SQL and explicit transactions. The separate history database uses SQLite's existing [atomic commit](https://www.sqlite.org/atomiccommit.html) support with synchronous FULL. This avoids a migration of the accepted character/ownership/trade schema. Each connection checks the exact schema and world/build/rules identity. An existing schema-less archive is refused rather than recreated. The archive is `<world database name>.battle-results.sqlite3` beside the private world database. Include it in future world backups and release migrations; restoring only an older world database does not restore history to that earlier point.

The archive has one immutable row per battle ID. An exact uncertain-commit retry returns that row; changing the result or receipt digest is refused. A publication failure retains the final server barrier and permits the same receipt to retry. A new Desk refuses reuse of an already completed ID. The archive cannot authorize a second battle, clear a client journal, restore a save, release a hold, choose an interruption outcome, or pay currency. Its records survive host restart; in-progress native coordination still requires its separate durable lifecycle work.

## Player access

`battle_history` is an authenticated read-only operation with no caller-supplied actor. It returns at most the latest eight results involving the connected player, in decreasing sequence order. Existing history remains readable when new battle challenges are disabled. Strict client validation rejects wrong participants, changed slots, duplicated IDs/sequences, invalid outcomes and unsolicited private fields. The bounded reply fits the existing 16 KiB frame limit.

Players → Challenges → Recent battle results shows Win/Loss/Draw from the viewing trainer's fixed side, plus the two sides' participant names when still available in the connected roster. Historical display names are not yet stored. There are no automatic win streaks, rewards, wagers, tournament advancement or friendship effects.

## Acceptance boundary

The tests exercise real SQLite/Flash storage and authenticated TCP history, with simulated native receipts. The accepted native full-party battle and Players-menu proofs remain separate evidence. This implementation does not turn those development proofs into a public battle executor or resolve the owner's pending interrupted-battle policy. Actual-core history publication, packaged UI integration, crash recovery across the complete native lifecycle and backup/update composition remain acceptance work.

On October 8, the final WSL affected group passed **109 tests**, zero skips, in 183.087 seconds, including archive, protocol, four-client TCP, menu, Desk, arbitration and launcher regressions. On Windows, the 64 other cases passed and all ten archive cases passed a corrected recheck in 3.748 seconds. The first Windows group exposed two test-fixture SQLite handles left open at cleanup; explicit fixture connection closure corrected those errors. Production archive connections already closed in `finally`. Source review also caught and fixed silent initialization of an existing empty/truncated archive; that regression now refuses the damaged archive without overwriting it. These development test timings are not gameplay performance measurements.

Private logs were copied and hash-verified. SHA-256 values are `14cd45eb96ba227be81a09806324f639239a363a7db2229969d82bec5a38ccbc` (WSL), `2477230199f0ca3bd828bd8d4167918d16f2b211732f8e8bf1334d0ad17b2d08` (initial Windows group), and `09f37d6c2f174d4e616a2028a10b7ba1e9f6697ecd7ad773d4a248bd69ff2a72` (corrected Windows archive group).
