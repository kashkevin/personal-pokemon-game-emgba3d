# EmeraldTogether development ledger

Persistent record of the autonomous work queue that follows `EMERALDTOGETHER_SIX_ISSUE_DIAGNOSIS.md`.
One task at a time; each entry names what was done, the evidence, the commits, what is unverified and the
next step. Never edited to hide a failure: a failed or reverted attempt stays recorded.

Branches (nothing merged into the combined branches; no force-pushes):

| Repo | Branch | Based on |
| --- | --- | --- |
| App | `claude/dev-m25-stability` | `claude/admiring-bohr-dpxzuy` (diagnosis, packaging) |
| Engine | `claude/dev-stability-engine` (created when the first engine change lands) | `claude/cloud-setup-engine` |
| Graphics mode (separate work, not duplicated here) | app `claude/graphics-mode-selector`, engine `claude/graphics-mode-engine` | CI run 38655648745 pending when this ledger began |

## Queue

| # | Task | Status |
| --- | --- | --- |
| P1 | M25 multiplayer battle performance | done for what is safe (−12 % to −28 %); two further levers need Opus (see entry) |
| P2 | Four-player 2v2 and recovery (journal growth) | queued |
| P3 | Co-op EXP / Exp. Share verification | queued |
| P4 | Stability: clock self-test, UBSan coverage, M27, GEN_6 test review | queued |
| K | Customizable keybinds (inspected: **does not exist**, implement) | queued |
| P5 | Incomplete features audit and partial completions | queued |

## P1 — M25 multiplayer battle performance

**Measured with** `tests/test_battle_throughput.py` (real host, server and client session; synthetic native
core; asyncio debug mode off; only the relay phase timed; `-s` prints the numbers; `BATTLE_BENCH_OLD_POLL=1`
emulates the old fixed 10 ms poll).

| Case (battle start-up: no gameplay turns) | Before | After | Change |
| --- | --- | --- | --- |
| 2 players, instant core | 2.1 s (96 native commands) | 1.5 s (96) | −28 % |
| 2 players, 16 ms game delay per command | 3.4 s | 3.0 s | −12 % |
| 4 players, 16 ms game delay | 8.1 s (264 commands) | 6.2 s (264) | −24 % |

(Five to six runs each; run-to-run noise about ±0.2 s. The command counts are unchanged: this is host and
client overhead per command, not fewer commands.)

**Corrections to the diagnosis (measured, not assumed).** The 10 ms client sleep is *not* the main cost: the
adaptive poll alone was worth about 10 %. Profiling the relay phase showed ~40 % of host time in repeated
canonical-checkpoint reads (SHA-256 of the whole save, SQLite, flash decoding): `battle_desk.refresh()` re-read
and re-hashed every participant's checkpoint on every RPC (about 15 reads per native command) only to compare
revision and hash. KEEP was sent every step although every accepted native command (QUERY included) already
refreshes the game's own deadline.

Changes (app only; no protocol, journal format or ABI change):
1. `battle_session.py`: client poll 1 ms right after activity, doubling to the old 10 ms when idle.
2. `storage.py` `checkpoint_head()` + `battle_desk.refresh()`: compare (revision, sha256) from the metadata row
   instead of reading and hashing the payload. Readers of the payload still verify it.

**Tried and reverted (recorded on purpose; both need Opus-level reading of the recovery flow).**
* A lease-only check in `battle_desk._get` (skipping the checkpoint read) broke seven host-restart recovery
  tests: the recovery flow reaches `_get` with a battle's original lease. `_get` still uses the full `_auth`.
* Throttling the per-step KEEP to once a second (it removed 18 of 20 KEEP round trips and gave another −15 %)
  made `test_battle_recovery.py::test_uncertain_successful_release_reconciles_without_replaying_gameplay` fail
  deterministically (the test client stalls after the first command); with `KEEP_INTERVAL = 0` it passes. The
  game's own deadline is refreshed by every accepted command, so the cause is a host-side dependency on a KEEP
  per step that I could not find in the time I allowed it. KEEP therefore stays one per step.

**Evidence:** the battle test group (arbitration, execution, desk, recovery, recovery session, admission intent,
protocol, native battle, launcher battle recovery/admission, native resume, co-op battle, the new throughput
tests): **182 passed, 1 skipped** (2026-10-15). Real game and real network are **not** measured here (the earlier cloud runs
and a real PC are the ground truth: expect the host-side gain, not the 1-2 game frames per command).

**Not done / next:** the remaining costs are per-command durable writes (about 20 % of the relay phase here),
128-byte READ_OUT/RECEIVE chunks and a QUERY every step. Both need a protocol or ABI change: only if a real run
shows the gain above is not enough. Fast-forwarding the game's frames while a command is outstanding (engine,
PC only) is the next cheap lever for real games; it needs a real-game measurement.
