# Durable native battle reservations

The owner selected saving/disconnection on host loss and waiting for every participant to reconnect after an interrupted multiplayer battle. This change implements the host's durable reservation boundary. It does not resume a native battle, save its temporary party, choose an outcome, cancel an interrupted match, or release a native hold.

The first authorized BIND commits a reservation for every trainer in the fixed roster, before the trusted coordinator receives dispatch authority. A missing BIND acknowledgment therefore cannot make either side available for a checkpoint, ownership allocation, trade mutation, or another battle. Subsequent BIND authorizations extend a durable actor mask under the same immutable battle record. The reserve operation is idempotent; another generation, roster, original lease/incarnation, RNG seed, or consent fingerprint cannot reuse its ID.

The reservation is in the character database. Host restart, new authenticated leases, disabled battle creation, deadlines, invitations being canceled, and loss of the in-memory Desk do not delete it. Read-only canonical queries and authenticated waiting status remain available. Uninvolved characters retain their existing save and trade behavior.

## Explicit migration and backups

Legacy schema 2 and 3 remain the defaults of `OwnershipCheckpointStore` and `TradeCheckpointStore`. Opening an existing legacy world never enables this capability or migrates its database. New native battle coordination requires explicit activation first.

| Original schema | Enabled schema | Meaning |
| --- | --- | --- |
| 2 | 102 | Ownership foundation plus durable native battle reservations |
| 3 | 103 | Ownership/trade foundation plus durable native battle reservations |

The added 100 encodes this explicit capability. The classes recognize only their exact base schema plus the two specified reservation tables at the matching version. A missing table, unfamiliar version, changed SQL definition, malformed record, wrong world/build/rules/profile, bad digest, missing original canonical checkpoint, or inconsistent participant barrier is refused. Existing constructors cannot silently recreate a missing registry. Earlier application versions reject the extended schema rather than running without its barriers. This changes no ROM Save ABI, character payload, ownership identity, credential, or existing canonical revision.

The host calls `enable_battle_reservations(store, backup_path)` on an idle store. The function requires the existing exclusive host lock, or acquires it temporarily; it refuses active player leases. `backup_path` must name a new file. Before altering the source, it uses SQLite's backup API, reopens the backup using the original store class, performs full integrity checks, and compares its complete logical database and world metadata to the source. The backup remains a readable legacy world. An interrupted migration transaction rolls back both table creation and the version; the backup is retained.

For example, with a privately opened `TradeCheckpointStore` and a new private backup destination:

```python
from emerald_multiplayer.battle_reservations import enable_battle_reservations

enable_battle_reservations(store, backup_path)
```

Activation is a local host operation, never a network RPC. No accepted/private world is migrated merely by this source change. A normal future `store.backup()` includes active reservations and terminal records with the canonical checkpoints in one consistent database. Restore that complete backup; do not restore selected tables or downgrade an enabled world to escape an unresolved battle.

## Admission, authenticated observation, and terminal evidence

`BattleDesk.authorize_bind()` reserves the immutable roster before its in-memory dispatch intent is returned. `WorldServer` loads and checks the registry before opening a listener, even when `development_battles=False`. The server's mutation barrier and direct storage checkpoint/grant/trade APIs consult the same records. Dropping a local client journal does not remove the host's reservation.

The authenticated `battle_waiting` request uses the ordinary battle reply envelope. Its `result` is an empty list when no reservation exists, or one record with exactly:

```json
{
  "scope": "durable-native-battle-reservations-v1",
  "battle_id": "<UUID>",
  "generation": "<UUID>",
  "mode": 3,
  "players": ["<ordered participant UUIDs>"],
  "state": "waiting",
  "resume_supported": false
}
```

Mode 2 contains two participants; mode 3 contains four. Only an authenticated participant sees their reservation. The reply exposes no original lease/incarnation, RNG, credential, save bytes, or native command authority. New leases authorize this observation only. There is no public reservation cancel, acknowledge, clear, release, rebind, or resume operation. Existing invitation/status formats remain separate.

The trusted Desk can mark a reservation terminal only after its existing complete native checks: every authorized pre-start BIND has a correlated successful ABORT, or every participant has the agreed outcome, exact restored party, and successful RELEASE. Partial abort/release retains the entire roster. The terminal fact commits before the Desk frees the final barrier. Exact uncertain-commit retries are idempotent. Terminal IDs remain recorded and cannot start another lifecycle.

Completed history uses its existing separate archive. It commits before the final reservation terminal update. If the latter fails, history can already show the completed result while the conservative reservation remains. Retrying the same validated final receipt does not duplicate history and completes the terminal update. Restart alone does not infer authority to clear this conservative hold. The stored terminal digest records the trusted Desk's validated receipt set; it is not an independent durable replay of all original native commands or a battle-state snapshot.

The launcher must query authenticated waiting status before starting a fresh core, including when the local battle journal is missing. An unavailable/unknown waiting reply cannot be treated as proof of no reservation. That launcher gate is integrated separately from this storage slice.

## Reuse audit and remaining native work

This adapts the existing project-owned `BattleDesk`, native receipt validators, authenticated challenge protocol, ownership/trade guards, SQLite transactions, exclusive host lock, and backup/integrity functions. Python's existing [sqlite3 backup and transaction APIs](https://docs.python.org/3/library/sqlite3.html) and SQLite's [atomic commit guarantees](https://www.sqlite.org/atomiccommit.html) supply persistence; no new third-party dependency or imported implementation is added.

The qualified native Players source remains `84a4d1c1e906bd7340b9d08b231e485b0fa5c07c`'s existing engine lineage; this slice changes no native code or frozen ROM. The inspected maintained RHH source on October 8 was `12f292fe14871ca54bc2d73279912a17a921f24b`: its [link field lifecycle](https://github.com/rh-hideout/pokeemerald-expansion/blob/12f292fe14871ca54bc2d73279912a17a921f24b/src/overworld.c) resets link state or reports link failure. It does not implement this project's durable independent-world reconnect protocol. The inspected maintained mGBA revision was `143adf5aa2a60c6036810b0cd72445e13d74b0e6`; its [thread pause API](https://github.com/mgba-emu/mgba/blob/143adf5aa2a60c6036810b0cd72445e13d74b0e6/src/core/thread.c) retains a running process but does not persist battle semantics or router acknowledgments. The existing pinned mGBA implementation remains unchanged, with its existing license/attribution recorded in the dependency ledger.

The native protocol still refuses mutations under a replacement battle lease/incarnation and enters guarded recovery on watchdog expiry. Its frame callback must remain running to service bridge IPC. Actual resumption requires a same-core reconnect handshake, all-participant readiness, routing/acknowledgment reconciliation, and retained core/file-lease lifetime. Client process death or power loss requires additional native recovery work. No emulator savestates, arbitrary memory restoration, or automatic result/penalty policy is introduced here.

## Validation scope

The regression suite uses real SQLite, owned Flash fixtures, authenticated TCP reconnects, and simulated native receipts. It checks explicit legacy migrations/backups, rollback, active-owner refusal, uncertain BIND persistence, all-four reservations, disabled-host restart and new leases, waiting-reply secrecy, direct/server mutation barriers, corrupt/missing registry refusal, partial abort/release, and both sides of uncertain terminal publication. Build/actual-core interruption acceptance is separate; passing these tests does not establish native battle resume.

All **193 distinct affected tests passed on Windows and WSL**, including 16 dedicated reservation cases, with zero skips or unresolved failures. The WSL final run passed 192 tests in 227.688 seconds; its subsequent populated legacy-trade migration case passed in 1.199 seconds. After changing the complete backup comparison to stream its rows, all six migration cases passed again on Windows (1.766 seconds) and WSL (1.883 seconds). The Windows runs retain their complete provenance: seven initial TLS provisioning cases used the wrong interpreter without the already-installed cryptography dependency, and a newly added fixture initially called `HostWorld.load` instead of `HostWorld.open`. The existing pinned provisioning environment and corrected fixture passed every affected case; no production assertion failed in those runs.

The final private validation record has SHA256 `1666bb275afa7f7b3c131c870c390305abe52df0170bd89635ae67a3573e1c3c`. All three WSL logs were copied to the physical Windows battle archive and verified byte-for-byte against their originals. Log SHA256 values:

| Log | SHA256 |
| --- | --- |
| `battle-reservations-tests-windows-1.log` | `e17da01691cbe37c8b21b108a8dd289e38f3715eed82c72999455a828f817f5b` |
| `battle-reservations-tests-windows-2.log` | `183c746c43bd0ce87800f5b58258a348607640cfdaae195284797bb982f02acb` |
| `battle-reservations-tests-windows-3.log` | `760455a1c61e5659cd5fbccd807bafce177bc8113c788faefbf0d88db5243a88` |
| `battle-reservations-tests-windows-4.log` | `5060d0f1847814b862acd8b62a6bdc0149097baeea605fe1bd43b420603de23e` |
| `battle-reservations-tests-windows-5.log` | `9093229d53e8a291875dbb4e4b477e4f2b62c11c66232a846098cef80cded21c` |
| `battle-reservations-tests-wsl-1.log` | `a4d20abddfd6ee8f012e9f74f62d2ecdfcaecc5be499bdb936ce29311d136ea2` |
| `battle-reservations-tests-wsl-2.log` | `37188d265a25dd561dbe50ff848b02f550e1a9bdd6ce4e9aaae1802784e03a16` |
| `battle-reservations-tests-wsl-3.log` | `62e8400e1cfb5c1d7e43902fbad05e48c12b770ae27f30ad735dab8a0e9d71f6` |
