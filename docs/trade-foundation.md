# Safe trade implementation status

Work started October 7–8, 2026, on `codex/multiplayer-delivery`. This extends the accepted ownership foundation without modifying its tag, private source saves, or schema-2 worlds. The [delivery roadmap](development-roadmap.md) retains all seven requested milestones. Independent proof and integration work can run in parallel; playable acceptance still follows their dependencies.

## Persistence and consent

`TradeCheckpointStore` creates an explicitly selected schema-3 world. Both canonical save revisions, current ownership, transfer history, and two recovery receipts commit in one SQLite transaction. The immutable birth owner/allocation remain attached to each instance. A transfer never retires and recreates a Pokémon. Normal checkpoint rules still reject unexplained disappearances, foreign ownership, and retired identities.

The first transformation exchanges exactly the two offered 100-byte party records and the necessary section checksums. Party counts, other Pokémon, story, money, inventory, ownership metadata, old save bank, special sectors, and RTC footer remain byte-identical. This is a persistence primitive; native trade side effects remain separate work.

`TradeDesk` accepts each participant's confirmation only through that participant's authenticated connection. A consent fingerprint binds the world, transaction, a fresh proposal generation, edit number, both leases, revisions, save hashes, and offered identities. Editing either offer clears both confirmations, including when an offer is changed back. The second matching confirmation synchronously constructs and commits both results. Failed construction/commit clears consent.

An uncommitted proposal expires or disappears when a participant disconnects or its lease changes. Restart discards uncommitted consent. Committed fate is durable and retryable, even after a fresh authenticated lease. A successful authoritative lookup can establish absence; a timeout cannot. Reusing a committed transaction with different participants or contents is rejected.

Each affected player must apply and acknowledge its exact committed result before another ordinary save, allocation, or trade can mutate that character. Recovery replies expose only the requesting player's checkpoint metadata; full saves continue over the existing bounded checkpoint channel. Historical committed fate must never be mistaken for permission to restore an older revision over newer progress.

## ROM and transport integration

The isolated engine worktree starts from ownership commit `88c7ef798ab5f91a496099cc687252fa5c4b12a3`. The trade extension keeps the existing presence/save mailbox allocations separate and adds a verified `gMultiplayerTradeAbiVersion` constant. The generated manifest, companion, and Lua bridge gate the new commands using the capability and ROM identity.

Commands 12–17 support frozen preparation, keepalive, pre-import abort, verified release after import, rebinding to a newer authenticated lease, and a read-only recovery query. `TRADE_HELD` is state 8. An expired watchdog marks uncertainty while preserving the hold and successful response cache; it never resumes gameplay by itself. Ordinary cancel/bind cannot release a trade. Once import starts, abort is refused. Export and import retries reuse the same transaction and immutable data.

The intended sequence is: freeze and export an ordinary save, durably checkpoint that preparation, keep both games frozen while offers are confirmed, commit both ownership changes, import each player's canonical result, verify its complete readback, acknowledge recovery, and release through normal Continue. A durable client coordinator and its interruption tests still need to implement this complete sequence.

The authenticated trade RPCs are an explicit `development_trades=True` integration option requiring schema 3. They are disabled by default and absent from the current player UI. Requests cannot claim another actor or upload arbitrary trade post-images. A trade-capable companion closes its remote connection when its authenticated local game bridge is lost; the next connection obtains a new server lease so old consent cannot survive a changed emulator incarnation.

## Frozen engine verification

The storage/consent/transport checkpoint passes **285 Python tests with no skips on Windows Python 3.14.4 and WSL Python 3.12.3**, including read-only validation of the original A/B saves. The sequential runs completed in 96.861 and 164.016 seconds. Nine new real-TCP tests cover independent consent, changed offers, foreign actor rejection, a lost final confirmation reply, reconnection, server restart before/after commit, recovery acknowledgments, and the default-disabled/schema boundary. Their Flash inputs and ROM IPC are fixtures; actual-game evidence is separate. Earlier simultaneous aggregate runs encountered short heartbeat/reader timeouts under eight engine workers and gameplay load. Both suites passed unchanged when serialized; those stressed failures are not counted as passing results.

The exact extension source is `b2cdd466abb8b142c3b75384133b5e6b3c3b982c`, with a [source-only patch](../engine-patches/phase3-trade-hold.patch) against the accepted ownership engine. The patch SHA-256 is `c0f1aefc039803a9bf983c3a0aed2d8af102acfb77bb406e94e139cf3b4dbbb4`; apply-check passed against a clean ownership checkout. The existing ownership checkout and acceptance tag remain unchanged.

Six focused C tests exercise the real mailbox and Flash routines: admission and revision/lease fencing; expiration without release and cached acknowledgments; read-only query and lease rebinding; restartable frozen export without another save or RNG advance; corruption cleanup while retaining the hold followed by import retry; and full readback/release through normal Continue. Ordinary mailbox behavior has regression coverage. Synthetic Pokémon used by those tests are not evidence of ordinary gameplay.

The unfiltered engine suite exits zero with **5,435 PASSED, 18 KNOWN_FAILING, 421 TO_DO, and 9 EXPECT_FAILING; total 5,883**. The six new passes account for the increase from the accepted ownership engine; its exception categories are unchanged. The full log hash is `3dc99821b268634c08f3155d31e8abf97a7af1909f40947366a8936c50be8e97`, and the focused log hash is `8ffe27f1555a852b352eb36f59a52317326bfd92d8021e660f0b1d750438b206`.

The frozen normal ROM hash is `ee71194973092c9ccc395dd7ffeb203447e8854a13404c470b26e8f6235df7c8`; the ELF hash is `26aeeda2882ee797d0e9eb61b6ec7804cebe29e63db9247be9c0b5e03bff2a3e`; the manifest hash is `07ffdfd786c453952fde577a41884676498886803db64a390bff7ecbaf77f363`. The normal image uses 229,828 bytes EWRAM, 28,376 bytes IWRAM, and 26,762,000 bytes linked ROM, adding 4 bytes EWRAM and 1,204 linked ROM bytes to ownership. These are static link measurements; the cartridge remains padded to 32 MiB. Normal artifacts and test logs are hash-verified in the private Windows archive `trading\final-build-b2cdd46`. No playable trade acceptance tag is assigned.

## Reuse audit and remaining acceptance

The pinned engine already provides ordinary saving, Flash validation, trade animation/evolution, Pokédex updates, mail handling, and egg hatching. Its native cable/link-room trade path is coupled to link synchronization and also changes received non-egg happiness. The current server can reuse the existing checkpoint/authentication/lease transport, and the ROM extension reuses its owned Flash staging and normal Continue. No third-party networking implementation was imported.

The October 8 upstream check still resolves RHH `master` to `6057b187f946094d614e9c34bc12731ea6a5b7bb`; its [trade implementation](https://github.com/rh-hideout/pokeemerald-expansion/blob/6057b187f946094d614e9c34bc12731ea6a5b7bb/src/trade.c) remains the native link-coupled path. The earlier [network reuse audit](technical-foundation.md) records Wired-Ariel v1.7.2's vanilla-address Cable Club workaround, GPL terms, and lack of our canonical save transaction semantics. Its [pinned README](https://github.com/Wired-Ariel/gen3-poke-multiplayer/blob/v1.7.2/README.md) was rechecked; this reference has not been imported. Reuse engine effects deliberately while keeping the already tested allocated mailbox and durable server path.

Native `src/trade.c` around `TradeMons`/the trade evolution callback and `src/egg_hatch.c` still need deliberate adaptation. A party record's mail index references its owner's mail array; copying the index alone does not transfer mail. Native evolution, Pokédex/happiness effects, and a traded egg's hatching/original-trainer transition are not implemented by the exact swap primitive. These cases must not enter a player-facing trade path until supported. This is a temporary development limit, not a change to the accepted game rules.

The hold currently lives in ROM RAM. Frontend reset/cold restart bypasses it. The launcher therefore still needs a paused-start canonical recovery gate, or a separately designed persistent marker/migration, before live trading can be called safe. A changed IPC incarnation also requires that recovery path. Preserve the existing save profile until a tested migration is actually needed.

Remaining gates include the durable client coordinator, native trade effects/eligibility, offer/confirmation UI, actual-core paired trades, process/connection loss at each transition, fresh Continue from both results, and four-player trade/battle acceptance. Fixture and engine unit tests do not replace these gameplay checks. Battle/team implementation, Local Soft Reset, automatic saves, the Windows package, and real Wi-Fi/Internet delivery testing remain open on the roadmap.
