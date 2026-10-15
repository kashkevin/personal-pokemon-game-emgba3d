# Save and database compatibility (Update 23)

**Status: tested by simulation in the cloud (databases written by an older build, opened by the current one). The unchanged ROM
hash proves nothing about saves and is not used as evidence. No real save from a real player was available or touched.**

## What persists, and what changed since Update 14 (the last build before Updates 15-20)
| Store | Format | Changed since U14? | Evidence |
|---|---|---|---|
| Checkpoint store (`world.sqlite3`: each player's save, leases, trade/battle extensions) | SQLite, `user_version` capabilities | `storage.py`, `trade_storage.py`, `ownership_storage.py` **byte-identical** to U14 | `git diff e2a40d7..HEAD` empty for the three files |
| Shared world (`*.shared-world.sqlite3`: events, catch resolutions, frontier, league, bases) | SQLite, `CREATE TABLE IF NOT EXISTS` | additive only: `event_verdicts`, `frontier_rewards`, `frontier_bp`, `frontier_purchases`, `frontier_bring`, `ffa_results` | `tests/test_save_compat.py` (6 tests) on a database written by the U14 code |
| Launcher profile files | JSON with strict formats | `launcher-settings.json` untouched; the privacy choice is a **new separate file** so a newer file never breaks an older launcher | `tests/test_privacy.py` |
| The game's own save (flash) | the GBA layout | **no layout change**: the catch record uses five previously unused script variables; engine `abi_layout.py` and `check-abi` pass | engine `make check-abi` |

## The fixtures (data only: no ROM, no player save)
`tests/fixtures/compat/shared_world_u14/` and `checkpoints_u14/` were written by `tools/compat/make_*_fixture.py` run with the code of
the Update 14 checkout (`git worktree add /tmp/old e2a40d7`; `PYTHONPATH=/tmp/old/src ...`). The checkpoint fixture holds random bytes of
the real save size (no real save). **Every test copies the fixture to a temporary folder first** (the backup the migration works on)
and `tearDown` proves the committed bytes are unchanged.

## What the tests prove
* The old shared world opens, its two caught-event resolutions are unchanged, no old table's SQL is altered, the new tables appear.
* A repeated report from an old winner is answered "consumed"; nobody else wins an old event; an event claimed but not caught
  before the upgrade can still be caught **exactly once** after it, and a restart repeats the answer.
* The catch-verdict table gives an old catch exactly one `keep`, however often asked.
* Reopening 30 times changes no row and grows the file by less than one page-run.

## Not covered (stated)
Old **battle journals/pending JSON files** and old **player saves** from real games: formats unchanged by Updates 15-20 (the modules
that write them are untouched), but no fixture from a real older run exists in the cloud; the first real-PC session should keep its
`world` folder and `profile` folders as a backup before updating. Reward, streak, BP-ledger, journal-growth and restart behaviour have
focused tests from Updates 16-17 (`tests/test_frontier.py`, `tests/test_event_catch.py`, battle recovery tests).
