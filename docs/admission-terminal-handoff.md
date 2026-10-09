# Durable original admission handoff receipts

October 9 implementation in source only. No tests, builds, project imports,
game/UI runs, database migration or private save/world changes were performed.

## Connected behavior

The existing neutral admission cancellation leaves the original core held until
its fresh emergency saver is armed. A successful native
`ADMISSION_CANCEL_HANDOFF` then releases that hold. Its exact response is already
saved by `complete_cleanup_handoff` in
`<battle>.admission-cleanup-handoff.json`. This change makes that completed
release observable durably by the host and Championship service.

1. On a subsequent Championship request, the companion publishes any completed
   local admission handoff receipts before asking for the bracket. Launcher
   cold readiness performs the same publication before opening a game.
2. The new authenticated `battle_admission_handoff` operation checks the exact
   canceled original consent, generation, actor, incarnation, runtime, original
   lease, slot, mode and cancellation digest. It requires the existing host
   acknowledgment of the matching successful native HOLD under the receipt's
   lease. It refuses any reservation, route journal or possibly dispatched
   battle command.
3. The host durably records `<battle>.<actor>.cancel-handoff.json` before replying.
   Exact retries return the same acknowledgment. A contradictory receipt cannot
   replace the first recorded terminal fact.
4. `BattleAdmissionHost.terminal(battle_id)` returns a frozen internal projection
   only when the original accepted consent and native identities cover every
   participant and every participant has a valid HANDOFF record. It reconstructs
   each proof from the canceled consent and corresponding HOLD ACK on every read.
5. Championship reconciliation can mark that exact attempt canceled with no
   winner, including after host restart or volatile Desk history eviction. An
   assigned participant must explicitly request the next attempt. All-four
   bracket cancellation still requires all four votes and settled matches.

The host accepts an older receipt under the same player's newer authenticated
lease, bounded by the world's recorded lease counter. This is delivery of an
already completed historical operation, not permission for a replacement core
to resume, release or reconstruct the original battle. The canonical character
may have progressed since handoff; receipt publication never rolls it back.

## Durable delivery and unchanged ownership

`publish_cleanup_handoffs` validates the original local admission archive,
cleanup/HOLD proof, exact successful HANDOFF command/response, world/build/rules
and player identity before sending. If cleanup authentication was renewed, the
immutable archived cleanup record must match the handoff's original hash.
The local `.admission-cleanup-handoff.host-ack.json` must match the exact host
result. A lost host reply or local ACK write leaves the original receipt
available for an identical retry. No receipt, missing response or mere dispatched
command is treated as completion.

Publication first negotiates `admission_handoff_version=1` through the existing
`battle_pending` request. Older hosts can reject this optional field with their
normal `invalid_fields` reply; the client retains the receipt and permits normal
readiness instead of sending an unknown message type or discarding evidence.
Capability support is cached only for the exact world/server epoch/player lease.
Unsupported hosts cannot reconcile these new terminal facts, so their affected
Championship attempts remain waiting. Malformed or contradictory evidence is
still an error, not an unsupported-capability fallback.

The native-to-saver handoff function has no additional network await. Its old
ownership transition remains intact; a host outage during evidence delivery
cannot re-latch an already released core. Publication never calls a native
mailbox, imports Flash, starts a battle, changes a checkpoint, releases an actor
reservation or enables generic reconnect. Existing interrupted battles still
wait for all original participants through their own recovery protocol.

`Championships.handle(..., admission=...)` receives the world-owned admission
reader. The terminal projection is distinct from `BattleReservationTerminal`.
Conflicting reservation and unreserved terminal facts, generations, rosters,
fingerprints, started battles, released results or recorded winners fail closed.

## Boundaries still UNKNOWN

- A partial invitation without every original accepted identity has no aggregate
  terminal proof. A declined invitation or a disappeared volatile Desk row is
  not evidence that nobody entered.
- The persisted pre-invitation intent gap still cannot be cleared after restart
  from missing rows or files. Only the existing same-turn synchronous refusal
  observation remains an affirmative never-issued decision.
- A HOLD ACK proves the core was held; it does not substitute for HANDOFF.
- Missing or inconsistent original receipts keep the bracket waiting. No timeout,
  automatic forfeit, synthetic outcome or replacement match is introduced.
- Receipt authenticity follows the existing authenticated companion/native
  receipt trust boundary. This is not remote emulator attestation.

## Source and future evidence

This composes the existing `BattleAdmissionHost`, native cancellation opcodes,
client cleanup journal, Championship sidecar and authenticated battle RPC. No
upstream dependency, native ABI, save layout or probability/rule change is added.
See the original [Championship recovery boundary](championship-recovery.md) and
the existing [reuse audit](customization-and-reuse.md).

Pre-edit files and SHA-256 index are preserved privately in
`C:\Users\kashh\AppData\Local\PokemonPrivate\admission-terminal-source-before-20261009-1`.
Changes are limited to admission host/client/codecs, the Championship terminal
reader connection, battle dispatch, and the companion/launcher delivery hooks.
No prior evidence or frozen build was replaced.

Independent source-only reviews found no concrete blocker in the host terminal
identity checks, Championship composition, historical receipt/ACK replay or
older-host negotiation. Review removed a proposed publication await from the
native handoff completion boundary; delivery remains separate from ownership
transfer. The reviews ran no code.

Future verification must cover two/four original HANDOFFs, missing-one waits,
changed identity/digest/slot refusal, repeated and late delivery, newer leases,
host restart/history eviction, lost host reply/local ACK, malformed files,
canonical progression after handoff and conflicting execution/reservation facts.
All are **UNVERIFIED** for this new source; source review is not gameplay proof.
