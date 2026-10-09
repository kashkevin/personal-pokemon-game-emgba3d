# Recipient preparation before atomic trading

This is a **source-only implementation, not yet built or tested**. The owner stopped testing and requested continued implementation. Earlier trade, launcher and recovery proofs cover their frozen sources, not the changes described here. No accepted binary, private world, save, database schema or release pin was changed.

## Connected ordinary-trade flow

The qualified Host path now enables ordinary trading when its verified manifest has trade ABI1, Players menu ABI2 and the ownership save profile, and the opened world is a `TradeCheckpointStore`. Both initial hosting and retained-service restart use `LauncherSession._start_host_service`. Joining players retain the existing build/profile/authentication checks. The explicit development override remains available; the normal Host path no longer depends on it. See [host service restart](host-service-restart.md).

The only supported effect capability is still `simple-owned-party-exchange-v1`. Existing [eligibility exclusions](trade-eligibility.md) remain enforced on both offers and candidates. This does not enable trade evolution, eggs, mail, friendship transformations or other native effects.

The separate [save-wide effects builder](native-trade-save-effects.md) now reconstructs complete evolved candidates with native replay, Dex/stat/ribbon bookkeeping and strict full-container validation. It remains outside this published capability and has not been built or tested.

`TradeDesk.confirm` now freezes the exact offers after both players confirm their current fingerprint. It enters `preparing` instead of immediately publishing the exchange. `trade_preparation.prepare_pair` derives two complete immutable candidates from canonical checkpoints, using the existing exact party exchange implementation. Each recipient receives only the counterpart's 100-byte offered party record and a bounded descriptor; the other player's entire save is not sent.

The descriptor binds world, build, rules, save profile, transaction and generation, the confirmed fingerprint, both players and original leases, both checkpoint revisions/request IDs/hashes, both offered serials/record hashes and both complete candidate hashes/sizes. A shared preparation digest binds the pair. Strict validation rejects extra fields, duplicate or unordered players, unsupported effects and noncanonical or oversized incoming records.

`LiveTradeCoordinator.confirm` durably retains the exact original actor's consent before sending it. `prepare_recipient` checks the original held core and current canonical source, independently reconstructs its complete candidate, and writes the immutable candidate and descriptor before sending a receipt. The artifacts are keyed by transaction **and generation**, preserving canceled attempts if the same transaction UUID is reopened with a new proposal generation. Consent artifacts additionally bind the exact fingerprint, original lease, incarnation, runtime and frozen preparation.

`NativeTradeMenu` displays preparing/waiting states and drives each recipient's preparation. Offers cannot change once preparation begins. Cancel remains available before publication. The server authenticates every receipt as its own recipient, rechecks both leases, heads and prior recovery state, then publishes only after both exact candidate receipts exist. A failed final commit does not expose an impossible two-receipt uncommitted state.

## Atomic validation and history

`TradeCheckpointStore.commit_prepared_trade` runs inside the existing paired SQLite transaction. It reconstructs both descriptors and complete candidates again from canonical pre-images, then applies the existing exact-byte `validate_party_swap` rule before updating either head or ownership record. A client-supplied hash is never sufficient authority for changed save bytes.

The existing schema-3 history retains both complete before/after checkpoints, paired commit order, immutable acquisition provenance, ownership transfers and recovery receipts. Its `_audit_history` continues to reconstruct every historical exact exchange. No new table, automatic migration or friendship backfill is performed. This history **does not yet persist or authorize a native-effects choice witness**; a future effect capability must add that durable, replayable representation before accepting evolved or otherwise transformed candidates.

A successful prepared-store retry authenticates today's leases but verifies the original descriptor using its retained original leases, which cannot be newer than the authenticated leases. It returns the existing exact result without writing or replaying effects. New commits still require the exact current leases. Missing committed pre-images are treated as storage corruption.

## Recovery and compatibility

New proposals, offers, confirmations and preparation requests explicitly negotiate `preparation_version=1` on the application wire. Their successful replies must echo the supported version. This is separate from the native ROM/build identity, since old and new application clients can use the same native binary. Unsupported peers are refused before new consent; the Players menu treats preparation incompatibility as unavailable trading while retaining its other functions.

Legacy `status`, `pending`, `ack` and `cancel` requests retain their old envelope for interrupted committed-trade recovery. Local intent schema 2 requires retained consent, descriptor and candidate before applying a committed result. Schema-1 intents remain readable without new artifacts. Both same-core application and closed-start reconciliation reconstruct a schema-2 candidate and compare all downloaded bytes before native import or closed mirror restore/ACK. A missing or changed artifact leaves recovery unresolved; it cannot silently downgrade to schema 1.

Uncommitted host proposals remain in memory. After host loss their authoritative fate is aborted unless the existing immutable store already records the paired commit. Transport uncertainty alone is never treated as cancellation. Committed retries install the exact recorded canonical bytes; they do not rerun evolution, consume items or make new recipient choices.

## Remaining native dependencies

The production preparation seam currently creates exact-swap candidates in Python. The [native effects audit](native-trade-effects.md) identifies the remaining work: a held native preparation command, copied received-mon/evolution context, ordinary move-learning decisions, permitted item consumption, received/evolved Pokédex and statistics updates, exact exported candidate/choice evidence, and a separate qualified capability whose validator and immutable-history replay reconstruct every permitted change. Field progression and native link saves must stay blocked until paired fate is known. The existing native preview helper has no production mailbox caller and does not satisfy these requirements.

A later [source-only native record engine](native-trade-record-preparation.md) implements copy-based evolution/item/stat/name computation and exact move-decision replay. It is a reusable record-level implementation; held native presentation/transport and complete save/history integration are still required before this production flow can admit it.

Egg hatch origin transitions and recipient-local mail allocation remain separate missing integrations. The [Gen 6 friendship plan](trade-friendship-plan.md) still requires an explicit legacy-history policy and geographic adaptation; neither is guessed here. Existing eligibility exclusions are temporary implementation gates, not removal of accepted gameplay requirements.

## Source evidence and validation limits

The connected implementation is in `src/emerald_multiplayer/trade_preparation.py`, `trade_desk.py`, `trade_storage.py`, `trade_protocol.py`, `live_trade.py`, `trade_menu.py`, the trade dispatch/correlation paths of `server.py` and `companion.py`, `cold_start.py`, `player_menu.py`, and the ordinary-host capability gate in `launcher_session.py`.

Independent source review identified and corrected generation-scoped artifact reuse, closed-start candidate enforcement and prepared-store retry leases. Review alone does not establish runtime correctness. No tests, builds, application imports, native launches or gameplay checks were run for this slice after the owner's stop instruction. Future qualification must cover both recipients, cancellation/reopening, loss before and after either receipt, commit uncertainty, same-core/closed recovery, version mismatch and complete history replay before promoting these sources into a downloadable build.
