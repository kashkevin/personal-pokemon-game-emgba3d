# Championship abort reconciliation and recorded statistics

Status: the explicit unstarted-match recovery path is implemented and has
focused disposable SQLite and authenticated loopback coverage (2026-10-09).
The owner has since authorized tests. This is server/controller evidence, not
an actual-core or packaged Championship qualification. No private player world,
source save, native process or accepted build was modified by these checks.

## Explicit recovery of an unstarted match

Both the in-game Championship round page and the Windows Championship panel
offer **Recover waiting match** to an assigned player. The new nested `recover`
operation binds the exact championship ID, generation, fingerprint, round,
attempt number and issued battle ID. It never starts a replacement or supplies
a result. Stale/cross-round requests and stale launcher action tokens refuse;
after a proven cancellation the player must choose a separate rematch.

Two additional affirmative evidence paths can settle the original attempt:

1. New issue intents persist `issuance="pending"`. Before the synchronous
   invitation callback is entered, a separate durable transaction changes it
   to `"dispatching"`. A crash before that transition leaves positive evidence
   that this callback was never entered. Recovery can cancel that exact pending
   intent only when there is no contradictory Desk/result/reservation/original
   consent record. A contradiction is an integrity error, not a cancellation.
2. `BattleAdmissionHost.unentered_terminal` can revoke an original singles
   invitation whose validated durable consent and original identities contain
   only its sender, with no claim or native proof. Its exact original execution
   must have no reservation, route journal, BIND intent, bound/prepared/started
   participant or pending/acknowledged admission dispatch. Full consent is
   required before original Enter claims are possible. Recovery durably marks
   this existing original consent record canceled **before** archiving a
   volatile invitation. Existing capture/claim/first-BIND fences then reject
   delayed work for that ID. A lost reply or interruption between the durable
   tombstone and volatile archive is safe to retry after host restart.

The latter returns a distinct immutable `UnenteredInvitationTerminal`. It is
not an `ADMISSION_CANCEL_HOLD` or native HANDOFF receipt and cannot release a
core. Reconciliation validates its world/build/ruleset, original generation,
sender, singles roster, fingerprint and digest before recording no-winner
cancellation. Existing full-consent native cleanup still requires the original
HOLD/rearm/HANDOFF evidence; this helper never substitutes for it.

The format remains backward-readable: old attempt records with no `issuance`
field acquire no invented history. No sidecar schema or private world migration
is run. Neither pre-dispatch recovery nor partial invitation cancellation
changes canonical save bytes, leases, party ownership, rewards or odds.

## Durable terminal aborts

`BattleReservations.terminal(battle_id)` provides a frozen internal projection
of an existing terminal reservation. It validates the reservation schema,
world/build/ruleset/profile, original accepted roster, checkpoint references,
record hash, terminal digest and active participant barriers through the
existing `_read` and `_active` paths. It returns world/build/ruleset, battle and
generation identities, sender, mode, ordered players, consent fingerprint,
terminal kind and digest. It returns `None` for an absent or active reservation;
**neither case proves that no native admission occurred**.

This read API does not write a reservation, release a participant barrier,
clear a native hold, delete a journal or acknowledge cleanup. Only the existing
trusted `BattleReservations._finish` path publishes terminal facts. For an
`aborted` fact, that path requires the last outstanding pre-start abort and
successful matching receipts for every authorized original BIND participant,
checks the original reservation and authorization mask, and commits the terminal
record before removing its actor barriers. A started battle cannot use it.

`Championships.handle(..., reservations=...)` now accepts that trusted read
provider separately from the volatile Desk. This allows reconciliation when the
host has restarted, the Desk's bounded history has evicted the battle, or new
invitations are disabled. When omitted and a Desk is present, it uses the Desk's
own reservations. The server supplies its existing world-owned provider.

For each issued match, reconciliation checks exact world/build/ruleset,
battle/generation, sender, singles mode and both players. If an in-memory
challenge or released result also exists, its generation and fingerprint must
agree. A terminal abort conflicting with a released result, recorded win/draw
or started native challenge is an integrity error. A closed reservation is not
a substitute for a result and cannot supply a winner.

A verified durable abort records the current attempt as canceled with no
winner. It never issues a replacement automatically. An assigned participant
must explicitly request the next attempt; existing attempt-number retries still
return the already issued attempt. Outstanding bracket cancellation votes block
new matches. Whole-bracket cancellation still requires all four votes and no
unsettled match. No forfeit, prize or replacement result is inferred.

## Boundaries that remain waiting

A bare `BattleDesk` state of `aborted` is insufficient for a new cancellation
decision. `BattleDesk._abort` reaches that state whenever no authorized BIND
abort remains, including a never-reserved provisional admission whose original
Enter latch or saving handoff may still be held. Such attempts now remain
`waiting` unless a safe cancellation decision was already durably retained.
Existing retained `canceled=True` decisions, including the synchronous
invitation-refusal path, are preserved; this change does not rewrite old
decisions or invent retrospective receipt evidence.

The preceding admission-cleanup protocol did not close this host-evidence gap:
`BattleAdmissionHost.cancel_admission` persists its cancellation tombstone and
per-player successful `ADMISSION_CANCEL_HOLD` acknowledgment. That acknowledgment
proves the original core remains held for a fresh saver. The later
`ADMISSION_CANCEL_HANDOFF` receipt is persisted by the client's
`complete_cleanup_handoff`, after rearming. The subsequent
[durable handoff implementation](admission-terminal-handoff.md) now publishes
that exact historical receipt and reconciles fully consented, never-reserved
matches after every original participant has completed handoff. Partial consent
now has the narrowly proven unentered-invitation path above; accepted consent
with missing receipts still waits. Treating a host HOLD receipt as proof of
release remains incorrect.

The interval after the durable `"dispatching"` transition remains **UNKNOWN**
when there is no surviving original consent or terminal evidence: the callback
may have run before the host stopped. Legacy intents without a phase retain
the same limit. Recovery leaves these exact matches `waiting` and does not
claim that an empty directory means they were never entered. The existing
synchronous callback-refusal path can still record a cancellation when it
observes no Desk insertion in that same event-loop turn. A later restart cannot
recreate that observation. No timeout, automatic expiry, forced forfeit or
substituted match closes this ambiguous dispatch interval.

A declined invitation with only volatile abort state and no original durable
consent therefore remains unresolved. An accepted invitation, original Enter
claim, route record, reservation or native admission stays on the existing
original-core recovery path. Lost emulator processes are not reconstructed.

## Statistics interface

`Championships.statistics(actor)` returns a fresh dictionary containing only:

- `entries`: brackets accepted by all four players, including active brackets
  and subsequently canceled brackets. Proposals and declined proposals do not
  count.
- `completed`: accepted brackets with a final won result and terminal champion.
- `wins`: those completed brackets whose champion is the actor.

The archive validates every bracket and issued-attempt relationship at startup,
before the server listener opens, and derives an in-memory projection from
those verified rows. A successful actual bracket insert/update invalidates the
projection; an uncertain COMMIT also invalidates it. A transaction rolled back
before COMMIT does not count. The next statistics read rebuilds from verified
bracket rows. Unchanged status polls and attempt-only bookkeeping do not force a
lifetime archive scan. Callers receive copied counters, never mutable archived
rows, opponent names or private checkpoint details. These counters grant no
reward, wager, friendship progress or native ownership authority.

## Verification and provenance

`tests/test_championship_recovery.py` exercises real disposable SQLite and
original-consent files: pre-dispatch crash/restart, conservative ambiguous and
legacy intents, incomplete consent, full-consent/raw Enter refusal, route
evidence refusal, interruption after tombstone, exact retry/rematch identities,
all-four cancellation without a winner, contradictory evidence, reply
correlation, six-row native menu and consumed launcher action tokens.
`tests/test_championship_recovery_network.py` uses four authenticated TCP actors
and the real server handler to issue a match, disconnect/reconnect its sender,
recover from retained partial consent, request a separate rematch and refuse
stale cross-attempt/foreign-player recovery. It checks the unchanged canonical
checkpoint bytes and revision for all four synthetic fixture characters.

The first focused successful run was **14 tests in 8.414s**. The final affected
cohort passed **45 tests in 26.825s, no skips**:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='src;tests'
& "$env:LOCALAPPDATA/PokemonPrivate/host-provisioning-dev/venv/Scripts/python.exe" -m unittest test_championship_recovery test_championship_recovery_network test_admission_cleanup_host test_battle_challenge_network test_battle_protocol -v
```

The retained `final-regression.log` SHA-256 is
`2a81511de75f4c9f933d4a9895d0b777350bacc2113bb39d9b321e9ee1f08544`.
Two preceding focused runs had fixture-only expectation failures (wrapped
storage error and existing `battle_result` response name). The first broader
cohort found an older `test_battle_protocol` operation-table fixture missing
the existing `admission_handoff`; it was completed with an exact receipt/ACK
round trip and negative correlation checks. These failures and successful logs
are retained. Independent source review found no concrete blocker in the
dispatch fence, typed terminal proof, original consent checks or attempt
identity. These checks do not prove live native Championship play, simultaneous
semifinals, graphics, or Windows panel input delivery.

The current pre-edit originals and SHA-256 index are privately retained at
`%LOCALAPPDATA%/PokemonPrivate/artifacts/championship-recovery-completion-before-20261009-1`.
The implementation reuses the existing sidecar, original consent ledger,
protocol extension and menu controllers. No dependencies, native code, schema
migration, explicit winner/forfeit policy or accepted build are changed.

### Earlier source-only work

This composes the project's existing Championship sidecar, BattleDesk,
BattleReservations and BattleResults. No upstream code, assets, dependency,
database schema migration, protocol outcome claim or native save-layout change
is introduced. The prior reuse investigation remains in
[Championships](championships.md).

Exact pre-edit source and SHA-256 records are preserved privately at
`/home/kevin/src/pokemon/championship-recovery-source-before-1`. Owned source
changes are `src/emerald_multiplayer/championship.py` and the narrow read API in
`src/emerald_multiplayer/battle_reservations.py`. Server wiring and optional
Trainer Card versioning are coordinated separately.

That private directory also retains `after/`, `after-index.json` and
`source-delta.patch` (SHA-256
`269812164be1df4bf77a463756a921799184f6e10a1563aa76846b84a880a5ee`).
Pre-handoff source hashes were Championship
`ece6f6b410efeca4f3dcbe77d0641c72b78ea9179f83556dd51387b3133333fa`
and reservations
`88eb498112ab3f9b137f03aa54c048282edca0ba15183a659fdd2dd9bf969403`.
Independent source-only review found no concrete blocker in the terminal
identity checks, conservative waiting behavior or transaction/cache handling.
That review performed no execution.

The earlier review did not execute pre-start abort, statistics/uncertain-commit
or archive-scale checks. The current focused checks cover the specific new
unentered recovery boundaries above; they do not broaden those earlier result,
native handoff or gameplay acceptance claims.
