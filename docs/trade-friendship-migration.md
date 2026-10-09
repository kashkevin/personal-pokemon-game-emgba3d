# Approved legacy handler friendship initialization

On October 9 the owner explicitly selected: **“Initialize missing handler values
to Gen 6 base friendship.”** This resolves the earlier missing-value policy
question. The following implementation is source-only, untested, and has never
been invoked on a private player world. It does not enable effectful public trades.

## Values and provenance

`src/emerald_multiplayer/trade_friendship_migration.py::initialize_missing_history`
preserves a supplied known friendship value, including zero. A known active value
that conflicts with the exact native observation is rejected. The observed active
byte is already known; it is not replaced with a base value. Only an absent
opposite-handler value is initialized from `gen6_friendship.base_friendship`.
No arbitrary default of 70 or caller-selected species base is accepted.

The existing table is pinned to RHH
`bb1093a7c72d3961d9a37d8e02ad2abc2c866682`, table ID
`rhh-bb1093a7-gen6-standard-friendship-v1`, values SHA-256
`b42adddfb53bcd89cb5e38b8319287dfede0d87751e31ff2d985db51f3c8bfe6`.
It covers standard species 1–721. See [table provenance](gen6-friendship-table.md).
The pinned `include/constants/global.h` defines `VERSION_EMERALD = 3`; the
canonical owner identity uses that explicit profile game version.

`FriendshipHistory.initialized_fields` records which values originated from the
approved initialization. `handler_identity_unknown` distinguishes an absent
historical handling identity from a verified never-traded history. A missing name
is never invented. Selecting a real new handler clears that identity-unknown flag,
while the original initialization provenance remains. Both private preparation
digest encoders include the policy/provenance for initialized histories; existing
complete-history fingerprints retain their former representation.

Backfill follows globally ordered canonical checkpoints, including paired-trade
groups. At an instance's earliest supported non-egg observation, the active byte
is observed and the absent opposite value uses that observation's species base.
Later observations preserve the inactive value and update only the actual current
owner's observed active value. Thus initialized historical rows are a deterministic
policy baseline, **not recovered pre-project handler history**. Existing simple
trades are replayed as exact observed bytes, not retroactively transformed into
Gen6 trade effects. Subsequent evolutions do not silently reinitialize known values.

Egg rows remain `unknown / egg_hatch_cycles`, because their byte means hatch
cycles. A later genuinely non-egg observation can initialize its own friendship
history. An unsupported species with no prior usable history remains
`unknown / unmapped_species_base`. No form mapping, egg effect, balance choice,
Lucky bonus, friendship threshold or geographic-refresh decision is introduced.

## Same-database lifecycle

`enable_friendship_history(store, backup_path)` is an explicit administrative
function over the existing trade/ownership schema 3. It uses the established
exclusive-owner lock, requires no active character leases, creates a new consistent
backup, reopens and compares that backup, then creates/backfills the extension in
one transaction. Failure before commit rolls back the schema/backfill and retains
the backup. Merely opening an old database does not run this function.

Two tables are added at optional schema offset **+800**:

- `pokemon_friendship_policy` retains the exact approved policy ID, table ID/hash
  and profile game version.
- `pokemon_friendship_history` retains each occupied instance's canonical
  player/revision/group, value or explicit UNKNOWN reason, predecessor digest and
  source-bound digest. Its foreign key requires the actual ownership membership.

The strict schema recognizer accepts exact combinations with existing +100 battle,
+200 reset and +400 observation extensions. Ownership-only schema 2 does not gain
these trade-history tables. The +400 observations remain immutable facts with
unknown historical handler state; they are not rewritten to fabricate provenance.

`TradeCheckpointStore._write_checkpoint_extras` appends handler rows after the
ordinary checkpoint has a global order. The paired-trade hook runs after both
ownership memberships exist, inside the same canonical save transaction. Existing
exact-swap validation remains unchanged. No save bytes, ownership serials, party
stats, money or progression are changed by the ledger or migration.

Full store integrity independently reconstructs rows from all immutable canonical
checkpoints and the fixed policy, including predecessor links. `read_current`
requires the current lease, current active owner and latest canonical checkpoint;
it rechecks the current source/group and returns typed history only for a ready row.
This is an internal trusted-store API, not a network field supplied by a client.

## Remaining integration and evidence

Source review covered missing/known values, zero, identity provenance, eggs,
schema combinations, backup/transaction ordering, paired groups and digest use.
No automated tests or runtime measurements were performed. Historical tests in
the earlier [friendship plan](trade-friendship-plan.md) do not verify this extension.
Migration rollback/retry, tamper handling, large-world cost, all extension orders
and live canonical lifecycle acceptance remain UNKNOWN until testing is resumed.

Public Gen6 trade effects still require selected geographic adaptation, trusted
native effect recomputation, atomic effect-history publication and recovery,
native presentation and actual-core acceptance. The current ledger records the
existing exact-swap world faithfully; future effectful publication must supply and
replay its explicit transition rather than treating a new candidate as an ordinary
observed swap. The approved initialization is not authority to bypass those gates.
