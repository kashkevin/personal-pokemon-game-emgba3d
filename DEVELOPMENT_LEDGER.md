# EmeraldTogether development ledger

Persistent record of the autonomous work queue that follows `EMERALDTOGETHER_SIX_ISSUE_DIAGNOSIS.md`.
One task at a time; each entry names what was done, the evidence, the commits, what is unverified and the
next step. Never edited to hide a failure: a failed or reverted attempt stays recorded.

Branches (nothing merged into the combined branches; no force-pushes):

| Repo | Branch | Based on |
| --- | --- | --- |
| App | `claude/dev-m25-stability` | `claude/admiring-bohr-dpxzuy` (diagnosis, packaging) |
| Engine | `claude/dev-stability-engine` (created at P3; pushed) | `claude/cloud-setup-engine` |
| Graphics mode (separate work, not duplicated here) | app `claude/graphics-mode-selector`, engine `claude/graphics-mode-engine` | CI run 38655648745 pending when this ledger began |

## Queue

| # | Task | Status |
| --- | --- | --- |
| P1 | M25 multiplayer battle performance | done for what is safe (−12 % to −28 %); two further levers need Opus (see entry) |
| P2 | Four-player 2v2 and recovery (journal growth) | done for what is safe (reload −47 %); journal-format reduction and the full-six proof need Opus / owner data (see entry) |
| P3 | Co-op EXP / Exp. Share verification | verified; parity test added; no confirmed bug; persistence and farming are owner decisions |
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

## P2 — Four-player 2v2 and recovery (journal growth, reload cost)

**What the code already had (found, not built):** the 66 MB journal timeout from the diagnosis was already
addressed in this lineage by `BattleRecoveryService._journal_ready` (the load runs in a worker thread, with
exact-byte re-verification), recorded in `docs/native-battle-recovery.md` (copied-world loopback: 303 RPCs,
longest 0.153 s). What remained is the *cost* of the load itself.

**Measured** (synthetic two-player journal built with the recovery fixture's own encoder; 108,007 events,
65.2 MB, about the size of the failed full-six run's 110,048 events / 66.4 MB; this machine):

| | Before | After |
| --- | --- | --- |
| `RouteJournal` reload | 12.3 s (114 µs/event) | 6.5 s (60 µs/event), **−47 %** |
| `verify_current` | 0.2 s | unchanged |

Profile of the old load: about 60 % in `NativeControl` unpack/validation (a UUID parsed 5 times per event, a
tuple of every enum member rebuilt per field) and about 15 % in encoding each record twice.

Changes (no journal format, protocol, ABI or validation change):
1. `battle_mailbox.py`: `_uuid` and the UUID text of unpacked controls are cached (`lru_cache`, same accept/reject
   rules); `_enum` uses a per-enum frozenset with the same membership as `tuple(enum)`.
2. `battle_execution_journal.py` `_record`: the value is encoded once instead of twice; the bytes are identical
   (pinned by a test against the old formula, including non-ASCII and escaping).

**Evidence:** `tests/test_journal_load.py` (bytes unchanged vs the legacy encoder, growth bound ≤ 700 B/event,
reload ≤ 400 µs/event). The 34 battle/recovery/admission/native modules: **381 passed, 19 skipped** (2026-10-15).
Not a real game: a real run is the only proof that a full-six interrupted battle completes.

**Not done, and why:**
* **Fewer journal events per battle** (110k events for one full-six battle; each native command is 2 events plus
  a QUERY and KEEP every step) changes the journaled opcode set that recovery replays. That is the same
  protocol/recovery redesign as M25 F2: **recommend Opus** (invariants across journal, resume and admission). Not
  started. Snapshot-plus-tail loading has the same dependency.
* **The full-six `--scenario all --require-full-parties` proof** needs the owner's four private source parties and
  about two hours per run on the owner's machine; not runnable in this cloud environment, so it remains
  unverified. Likewise client (not host) disconnect mid-battle on a real core, Windows interrupted 2v2, and four
  real PCs.
* Turn order and targeting are covered by the engine's 66 focused tests (`docs/native-full-multi.md`); the engine
  suite is run at the P4 milestone.

## P3 — Co-op EXP and the permanent Exp. Share

**Result: verified by test and code reading; no confirmed bug; one test added; nothing in the game changed.**

Engine commit `8176fc07` on `claude/dev-stability-engine` (test only, `src/platform/native_selftest.c`).

* **Parity with the battle's own EXP path (new).** `MultiplayerCoop_ExpReward` repeats `Cmd_getexp` states 1-2.
  The old self-test compared it with a hand-written Gen 6 calculation that skipped Lucky Egg, traded, Exp. Charm
  and the level cap. The new check runs the multiplier chain through the **real** `ApplyExperienceMultipliers` and
  `GetSoftLevelCapExpValue` for 6 getter variants (plain, traded, Lucky Egg, past evolution level, four hearts,
  all together) x Exp. Charm in the bag x 5 foes (Lv. 1 to 100) x faced/shared: **120 of 120 equal**. Mutation
  check: changing the Lucky Egg multiplier in `MultiplayerCoop_ExpReward` from 150 to 140 makes it fail (100 of
  120), then restored. `--selftest-coop-exp`: **26 checks, 0 failed** (24 before). Limit: it replicates the
  first-stage arithmetic of `Cmd_getexp` (a state machine tied to battle controllers); it is not the whole
  state machine. The project's configuration is Gen 6 (`GEN_LATEST` is `GEN_6`), so the Gen 5/7+ "scaled EXP"
  branch is compiled out and not exercised.
* **Reviewed, no defect:** PvP awards nothing (link battles refuse EXP in `BattleTypeAllowsExp`; the self-test also
  checks that a non-co-op result records and awards nothing); the award is consumed once (`pending` cleared before
  `ApplyCoopExp`), and ending the same battle again finds nothing; the teammate's party is never touched; Eggs,
  fainted and Lv. 100 Pokémon behave per the self-test.
* **Not a bug, by design (documented in the source):** the pending award lives only in memory, so a reset in the
  few seconds between the battle's end and the award script loses it and never doubles it. Persisting it needs a
  save-layout change, which affects every save and the ABI check. **Owner decision** (accept the loss window, or
  approve a save field).
* **Rematch/farming (owner decision, not changed):** a Leader's co-op battle can be offered only by a player who has
  not beaten that Leader (`HasTrainerBeenFought`), and a win flags the Leader for the players' own games. So EXP is
  repeatable (a) by losing again and again after knocking out foes (a loss still awards the knocked-out foes), and
  (b) in a 3-4 player group, while someone who has not beaten that Leader still asks a helper who has (the helper
  keeps EXP and prize money). Like wild battles, this is bounded farming, not a duplicate award.
* **Cosmetic report from the diagnosis not changed:** the Exp. Share key item says "turned off" while the share is
  permanent (`item_use.c`). The item exists only in the FRLG maps that Emerald never loads, so a player cannot reach
  it; no change.
* **Not covered anywhere:** co-op NPC and Frontier rewards do not exist (rules are P5 owner decisions); a kill
  between result and award on a real game was not run; all eight Gyms' scripted awards on a real game were not run.
