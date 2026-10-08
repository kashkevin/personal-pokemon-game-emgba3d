# Development native singles lifecycle

`BattleDesk` is a session-local consent and lifecycle service for the [ABI2 native singles prototype](native-singles-prototype.md). It reuses the authenticated ownership store, immutable `CanonicalBattler` descriptors, and existing native mailbox codecs. The native engine and its link/controller seams remain the battle implementation; Python does not calculate moves, damage, rewards or a winner. The reuse audit and pinned source references are in [battle-transport-design.md](battle-transport-design.md).

This component has no network endpoint, ROM command executor or player menu. It writes no checkpoint, statistic, currency or reward. Its tests use genuine encrypted Flash fixtures and real SQLite heads with simulated correlated native receipts. Actual-ROM battle acceptance, controller routing, durable battle recovery and player-facing integration remain separate gates.

## Admission and consent

Construct `BattleDesk(store, lease_for, timeout=180, clock=time.monotonic)` with an explicit ownership store and the server's current connected-lease lookup. Authentication supplies each actor and lease; request bodies must never choose them. Up to two independent two-person lifecycles may coexist. An unresolved native hold retains both participants' busy slots. Terminal history is bounded to 64 challenges.

`invite(actor, lease, peer, battle_id)` captures both current canonical checkpoint revisions and full-container hashes, assigns fixed source slots by sorted player UUID, and issues one immutable generation and nonzero 16-byte RNG state. The sender consents only for itself. `accept(actor, lease, battle_id, generation, fingerprint)` accepts that exact challenge only for the recipient. Team membership does not confer consent. Edited heads, disconnected leases, deadline expiration or replaced registered incarnations invalidate preparation. Neither a timeout nor a disconnect declares a forfeit.

Both players need an acknowledged owned canonical checkpoint. The native PREPARE gate must still compare its actual live six-slot party, native counter and trainer identity with that descriptor; a server snapshot alone is insufficient. Pending committed trade recovery blocks admission. The eventual coordinator must also prevent overlapping live checkpoint, trade and battle holds before dispatching commands.

## Trusted coordinator sequence

All participant methods below take `(actor, lease, battle_id, generation, ...)`, except `status(actor, lease, battle_id)`. `descriptor(...)` returns only that actor's immutable canonical material to the trusted coordinator. Public status contains revisions, hashes, readiness and lifecycle state, without party bytes, trainer bytes or the issued RNG.

1. Call `register(..., incarnation)` for both actual bridges. Call `authorize_bind(...)` **before** each BIND dispatch; it records possible native hold ownership even if the reply is lost. Pass the exact request and response to `bound(..., request, response)`.
2. Obtain `preparation(...)`, dispatch PREPARE, assemble the native TRAINER block, then call `prepared(..., request, response, trainer28)`. It requires the issued preparation bytes and exact canonical trainer descriptor. PREPARE emits TRAINER only; it does not emit the full party.
3. Call trusted `authorize_start(battle_id, generation)` after both consent, binding and preparation barriers. This marks STARTING before either dispatch, so an uncertain START cannot become an ordinary pre-start cancellation. Register each correlated START acknowledgment with `started(..., request, response)`.
4. The native startup subsequently emits the three original PARTY blocks. Call `verify_startup(..., kind, block_sequence, bytes200)` in exact order for each actor. Every byte, including unused six-slot party tails, must match its canonical descriptor. Exact retransmission is observational; changed retransmission or a skipped block requires recovery.
5. The trusted router separately validates all HEADER/RNG/startup ordering and native controller roles. Only then may it call `authorize_running(battle_id, generation)`. That method independently requires both START acknowledgments and both complete canonical parties. Ordinary client requests cannot invoke either authorization hook.
6. Native KEEP receipts may be submitted with `keepalive(..., request, response)`. A new successful receipt extends the service deadline; an exact old receipt does not. KEEP cannot revive an expired, aborting or recovery-required lifecycle.
7. Call `finish(..., query_request, query_response, outcome=..., party=bytes600, party_count=...)` only after native restoration. The native query must still be held, started and restored, with the exact revision and normalized fixed-side outcome: 1 for slot 0, 2 for slot 1, 3 for a draw. Both actors must provide equal outcomes and their exact original parties/counts. These receipts authorize release; they do not close the lifecycle.
8. Dispatch native RELEASE with each actor's verified original-party CRC and agreed outcome. `released(..., request, response)` closes only after both exact successful acknowledgments. Once an actor's release is acknowledged, its later ordinary checkpoint may advance without stranding the still-held peer's release reply; both captured network leases remain fenced. Observational QUERY does not consume the native mutator sequence; a following RELEASE may use that same next sequence number.

The coordinator must retain exact controls when delivery or acknowledgment is uncertain. The service validates correlation and monotonic mutator receipt order, but it does not attest an adversarial client's memory or replace the C endpoint's admission and typed payload validation.

## Cancellation and recovery boundary

Before START authorization, `cancel(...)` or trusted `refused(...)` clears consent. If no BIND was ever authorized, the challenge can abort immediately. Otherwise it remains ABORTING until `aborted(..., request, response)` acknowledges native ABORT for every possible hold. A lost BIND reply or an inactive query is not proof that a hold never existed. Repeated refusal cannot resurrect an already acknowledged abort.

After START authorization, timeout, disconnect, changed canonical head or conflicting native data produces RECOVERY_REQUIRED. No automatic abort, winner, forfeit, generic reset or gameplay release follows. A freshly authenticated lease may inspect the retained state but cannot mutate the old captured lifecycle. Recovery-required rooms remain busy and are never evicted by the terminal-history limit.

This service is intentionally in memory. Restarting its host loses uncommitted service history; it therefore cannot be exposed as complete restart-safe battle coordination. Durable journals, canonical closed-core recovery, authoritative result policy and launch admission must be integrated before shipping. This first singles scope also does not implement four-human full-six-party Multi, teams as battle participants, Championship, wagers, statistics or rewards; those accepted requirements remain in the master specification.

## Verification

On October 8, 2026, all **27 focused desk tests passed** on Windows (8.424 seconds) and WSL (8.242 seconds), with zero skips. A preceding 40-test desk/canonical-roster/codec group also passed on both systems; the subsequent 27th desk case checks that exact acceptance replay cannot prolong a challenge deadline.

These tests exercise authenticated actor separation; immutable slots, heads and RNG; explicit consent; PREPARE/START ordering; lost BIND acknowledgments; partial aborts; exact and changed replay; malformed roles/generations; ordered full-party startup; equal and conflicting results; both release acknowledgments; legitimate checkpointing after one release; expiry/disconnect barriers; bounded history; and monotonic-clock/type validation. Fixture success establishes this service's state transitions, not a playable native battle.
