# Public native trade publication

This source connects the previously private held-record/save preparation to
the ordinary trade coordinator, a separately packaged native replay worker,
and one canonical two-save/ownership/handler-history transaction. Source and
disposable fixture verification are recorded below. They do not establish
actual-game trade/evolution acceptance or a finished Windows release.

## Consent and preparation

`src/emerald_multiplayer/trade_effect_preparation.py` defines
`emerald-trade-recipient-effects-v2`. Existing exact-swap v1 descriptors remain
readable and continue to use their original validator and commit rules.

The v2 pair binds both original canonical checkpoints, serials, original
consent leases, complete authoritative handler histories, an explicitly
selected geographic policy, the verified ROM SHA256, and seven original peer
gift-ribbon bytes. Each actor receives only the incoming 100-byte party record,
bounded plan metadata, and its own subsequent candidate; no RPC exposes the
other player's full save. Candidate hashes are deliberately absent until
explicit native move decisions and final review have completed.

The client negotiates `effects_version=1` through an existing known read
operation. An effect proposal carries capability
`native-recipient-save-effects-v1`; old clients cannot accidentally consent
through the old receipt operation. Both actors must explicitly confirm the
same fingerprint. A lease change before mutual consent creates a new
fingerprint and clears confirmations. Once prepared, the original plan and
its consent leases are immutable, including across later reconnects.

The public `effect_prepared` receipt contains the bounded explicit
`[[move, replacement_slot_or_decline], ...]` transcript, full candidate SHA256
and size, and SHA256 of the final **100-byte** Pokémon candidate. This differs
from the private 192-byte native preparation-record digest. The client retains
its original consent, native decision-screen evidence, complete candidate and
final review before it can send the receipt. See
`trade_effect_session.py`, `trade_effect_menu.py`, `trade_effect_recovery.py`,
`live_trade.py`, and `trade_menu.py`.

## Host replay and atomic publication

`trade_effect_backend.py` owns durable proposals and receipts. A proposal does
not disappear on a timer, disconnect, or host restart. Cancellation writes an
explicit durable terminal fate; committed fate always wins a later cancel.
At most two disjoint pairs can be pending. Native jobs are serialized, keeping
SQLite and network heartbeats on their owning event loop.

After both receipts, the host independently runs `NativeTradeReplay` against
the verified ROM and packaged `emerald-trade-replay.exe`. The adapter calls the
native record and complete saved-block replay functions on fresh private VMs;
the client candidate is never used as native authority. `prepare_effect_pair`
also independently constrains protected Pokémon fields and reconstructs every
allowed full-save bookkeeping byte. Receipt hashes must match those results.
See `trade_native_replay.py`, `trade_effect_flash.py`,
`trade_effect_witness.py`, and `native/windows-runtime/trade-replay-worker.c`.

After asynchronous replay, the coordinator rechecks the exact durable plan,
both current connected leases, both canonical heads, ownership, unapplied
trade barriers, and battle reservations. `TradeCheckpointStore.commit_trade`
then writes both checkpoints, heads, ownership memberships/events, both apply
receipts, native outcome proof, terminal proposal fate, and resulting handler
histories in the **same SQLite transaction**. A failure writing the second
recipient rolls all of these back. Unrelated Pokémon/save bytes, original
instance identities, and original trainer attributes remain protected.

Handler-history entries use the native-authorized resulting opposite/active
values for traded instances, rather than reconstructing only the visible
friendship byte and losing the opposite value. Ordinary checkpoint observations
and old exact-swap trades preserve their previous semantics. The migration's
entry helper now reads metadata within the existing transaction rather than
opening a nested transaction.

## Restart and refusal boundaries

The explicit schema extension `1600` adds `trade_effect_policy`,
`trade_effect_proposals`, and `trade_effect_commits` to an already migrated
handler-history world. `enable_trade_effects(store, new_backup_path,
policy_id=...)` requires a fresh verified backup and no active characters.
Opening a world never creates or migrates these tables. Policy replacement is
refused. No private world was migrated while implementing this source.

Two supported explicit policy identifiers exist:

- `gen6-stable-world-region-v1`: retained virtual-world geography does not force
  a handler refresh.
- `gen6-absent-geography-refresh-v1`: absent geographic data explicitly forces
  the refresh condition.

Neither has an implicit default. Only the owner's selected policy may be used
for a real world. Missing legacy handler values use the separately approved,
backed-up Gen6 species-base migration; known values are preserved. Eggs remain
outside this history/effects path because their byte represents hatch cycles.

On startup, structural history replay checks original consent, immutable
checkpoint bytes, independent save changes, ownership and chained histories.
It is **not sufficient native authority**: `WorldServer.start` additionally
awaits fresh native replay of every committed effect before accepting clients.
An effect-enabled world without its worker refuses startup. The store itself
fences checkpoint, trade, ownership-allocation/enrollment and apply mutations
when native history has not passed this barrier. Worker failure cannot clear
the fence. Authenticated canonical reads remain separate from mutation rights.

Pending receipt records survive a restart. Already confirmed plans retain
their original context under newer authenticated leases; both original actors
must reconnect before paired publication. An uncertain open/write reloads its
durable row. A rejected foreign/stale request preserves an unchanged in-flight
proposal object. Cancellation while the worker is running stops publication,
drains the owned work, and leaves the original canonical saves unchanged.

Eggs, mail allocation, unlisted forms/later-generation records and native
evolution rules outside the existing audited local adapter remain explicit
refusals. The pipeline does not invent missing gameplay policy or broaden the
existing native whitelist. Native animation and actual input/transport/restart
behavior require separate game qualification; a fixture or successful compile
does not prove them.

## Verification record

The initial focused disposable Python run passed 64 tests in 43.555 seconds:
`test_trade_effect_backend`, existing trade storage, friendship planner/Flash,
friendship observations and generated Gen6 table cohorts. Its adapter is an
explicit non-evolving synthetic fixture, **not** a claimed native execution.
Log: `%LOCALAPPDATA%/PokemonPrivate/trade-effects-focused-20261009-1.log`.

A subsequent control/network run exposed stale tests that still treated the
second confirmation as immediate commit, omitted preparation negotiation, or
patched the removed builder name. It also exposed a real client regression:
historical status on a recovery-only host incorrectly probed disabled proposal
creation. The client now probes the exact known status operation for recovery.
The failed log is preserved as `trade-effects-control-20261009-1.log`.

Focused tests now cover durable single-receipt restart, refreshed pre-consent
leases, uncertain-open persistence, refusal during an unrelated native job,
failed historical replay, cancellation during replay, changed candidate
refusal and paired rollback. Existing v1 network tests now explicitly prepare
and acknowledge both recipients, including loss of the second prepared reply.
`test_trade_effect_network.py` additionally drives negotiated v2 operations
over real authenticated TCP against disposable SQLite with the explicit
fixture adapter.

The final backend/control cohort passed **46 tests in 46.805 seconds**, with
zero errors, failures or skips: `test_trade_effect_backend`,
`test_trade_effect_network`, `test_trade_desk`, `test_trade_protocol` and
`test_trade_network`. The nine backend lifecycle cases include both reviewed
uncertain-write/object-identity regressions. These tests exercise atomic
publication and protocol behavior with a synthetic non-evolving adapter;
they do not establish actual evolution, native move input or game acceptance.
Log: `%LOCALAPPDATA%/PokemonPrivate/trade-effects-control-20261009-2.log`,
SHA-256 `b8500f60ba14003f874a6d976be822fc598cdb15f08ef60bcbd3670cb83ca5ee`.

Before changes, seven backend/source files were copied privately under
`%LOCALAPPDATA%/PokemonPrivate/trade-public-effects-source-before-20261009-1`.
Root retained the complete pre-verification source snapshot separately. Native
trampoline/runtime patches and their compiled provenance are owned by the
native replay and packaging work; no prior accepted artifact was overwritten.
