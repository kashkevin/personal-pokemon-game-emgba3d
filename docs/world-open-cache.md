# World-open cache: each save's checked reading, remembered (KNOWN_ISSUES MS-161, option (b))

The owner's decision of 2026-11-05 (MS-161): "Implement validated caching or an equivalent safe optimization. Revalidate
when world data changes or an integrity check becomes invalid. Prioritize save integrity over raw loading speed." Option
(b) of the MS-161 rows was chosen: remember each save's checked reading by its content hash and the reader's version, so a
save is read once in its life; the order and ownership replay still runs in full on every open. Code:
`src/emerald_multiplayer/save_readings.py`; tests: `tests/test_save_readings.py`.

## What is remembered

Opening a world runs `CheckpointStore.integrity_check`. For an ownership world it reads every save with the save reader
and replays the history from those readings:

* the ownership/order replay (`TradeCheckpointStore._audit_history`; schema 2: `OwnershipCheckpointStore`) reads each
  save with `inspect_flash` + `inspect_ownership` (its trainer, world, player, grant, allocation cursor, retirement
  journal, every owned Pokemon and the manifest digest);
* in a world with handler history (every new world of a replay-capable game), `FriendshipHistoryLedger._integrity` reads
  each save again with `checkpoint_observations` (each owned Pokemon's native friendship observation).

Both readings depend only on the save's bytes and on the reader's code. They are what is remembered: the first as the
ownership snapshot plus the trainer id, the second as the (serial, observation) pairs the ledger consumes. Everything
else runs on every open as before: SQLite's own integrity check, every save's stored SHA-256 against its bytes, every
replay (order, ownership, trades and their exact swaps, transfers, handler history, battle reservations, resets), and
every check that depends on more than the bytes (the enrolled or transferred trainer, the world, the player and its
grant, the checkpoint's fields).

## Key, storage, versioning

* **Key**: the SHA-256 of the save's bytes, computed from the bytes on every open (by the cache itself, not taken from
  the database). Only an exact match is used; a changed or damaged save has another hash and is read by the reader again.
* **Storage**: one file beside the world's database, `world.sqlite3.save-readings` (not a table: the store's schema
  check admits exactly its own tables, and a cache must not move the database's change marker). It is replaced whole
  (a temporary file in the same folder, fsynced, then `windows_files.replace_file`, which waits out a scanner's brief
  hold on Windows); readers open, read and close it at once. Identical Pokemon records and observations are stored once.
  Entries for saves no longer in the world (a restored backup) are dropped at the next write. A warm open writes nothing.
* **Versioning**: `READER_FINGERPRINT` is the SHA-256 of the reader's source (`flash.py`, `ownership.py`,
  `trade_friendship_observations.py`, and `save_readings.py` itself without that line), pinned as a constant.
  `tests/test_save_readings.py` recomputes it: any change to those files fails the suite until the pin is updated (the
  failure prints the new value), and a new pin discards every older file. No judgment call ("does this change answers?")
  is involved: every edit counts. The packaged app runs compiled modules and trusts the pin the suite checked; run from
  source with a stale pin, the cache turns itself off (reported once). The file is also bound to its format, the Python
  version, the save profile and the world's id.

## Validation and fallback

* The file is sealed: a SHA-256 over its whole body, checked before anything in it is used. Torn, truncated, damaged,
  hand-edited, or from another reader, format, Python, profile or world: it is ignored whole and rebuilt by that open.
* Each entry is decoded strictly (types, the reader's own bounds) and must reproduce the manifest digest the reader
  computed from the bytes (`ownership.manifest_sha256`); handler-history entries must name exactly the save's Pokemon. An
  entry that does not check out is ignored and that save read again.
* Only readings the reader accepted are remembered; a refusal never is, so a damaged save is refused by the reader on
  every open. On a hit, the trainer check the reader makes is made again, with its own refusal; observations are used
  only when every check `checkpoint_observations` makes before reading holds (and the checkpoint's player matches).
* Only integrity checks use it, and only for stores opened with `save_readings=True` (HostWorld's: a host's start and the
  launcher's world list). Saves, trades, transfers and migrations read saves themselves, as before.
* Nothing in it can stop a check: any trouble falls back to the reader. A file that cannot be written (read-only folder,
  full disk, a folder in its place) is reported once per process on stderr and every open reads every save, as before.
  The file is written only when the replays that use it got through without an error (it holds nothing but readings
  of bytes the reader accepted, so a later part of the check failing makes none of them wrong).

## Threat model: why a seal and not a keyed MAC

The seal catches damage (a torn write, a bad sector, a sync conflict, an edit that does not redo the seal). It is not a
secret-keyed MAC, deliberately: a key kept on this PC is readable by whoever can rewrite the world folder, and such a
person can rewrite the world database itself (its saves, memberships, events and stored hashes) consistently, which the
open check has never been a defense against: the host owns the world. What a deliberately forged entry (seal redone)
could add is narrow: an open accepting a save the reader would refuse, and only together with database rows forged to
match it. It goes no further than the open: a trade reads its saves with the reader itself, and deleting the file makes
the next open read every save again. A per-installation key outside the world folder would add protection only against
a world folder brought from elsewhere with a forged file, at the cost of a key to create, keep and lose; if wanted, it
is one function (`_seal`).

## Operation

Deleting `world.sqlite3.save-readings` is always safe: the next open reads every save and writes it again. Two processes
opening one world at once (a host's start and the launcher's list) each write a complete file; the last one stays.

## Measured (Linux, 2026-11-05; not Windows, not a player's PC)

`tools/perf/world_open_bench.py --saves 300 --repeat 5` (two players with 300 distinct saves each, 600 in all), on a
4-CPU Linux machine shared with other work (load 1.1 to 2.6), two samples. "Before" is the code before this change; cold
is an open with the readings file deleted first, warm the open right after it.

| World of 600 saves | Before | After, cold | After, warm | File |
| --- | --- | --- | --- | --- |
| Plain (the bench's default) | 0.70 to 0.96 s | 0.79 to 1.22 s | **0.39 to 0.52 s** | 174 KB |
| With handler history (`--handler-history`: what a replay-capable game's new world has) | 1.54 to 2.06 s | 1.69 to 1.98 s | **0.73 to 0.85 s** | 204 KB |

A warm open is about 2x faster; the first (cold) open costs one more SHA-256 per save (about 0.1 ms) and the file's
write (a few ms). What a warm open still spends grows with the saves too (about 0.65 ms a save, 1.25 ms with handler
history): the check's own work, which option (b) keeps on purpose: SQLite's integrity check, every save's bytes read
and hashed against their stored hash, and the replays' queries.
