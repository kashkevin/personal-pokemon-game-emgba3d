# Retained original-core battle recovery candidate

This is an optional, unpromoted extension of the qualified [production executor](native-battle-execution.md). Its compiler-located `battle_resume_abi_version=1` marker requires native battle ABI3 and execution metadata. Existing manifests and the qualified Windows preview remain unchanged. Compilation and synthetic protocol checks do not establish playable interruption recovery.

## Original entry and ownership

The host records each authenticated trainer's original incarnation and local runtime UUID when that trainer consents. Consent remains ordinarily cancelable until explicit entry. The optional Players screen marks its exact enabled Enter row; native joypad selection latches the menu before emitting its IPC request. The latch freezes field callbacks, clocks and soft reset, and survives delayed IPC, B, ordinary CLOSE and disconnection. Other menu/trade behavior retains its existing rules.

The client publishes an immutable provisional intent, claims entry and uses the exact ADMIT19 control to transfer the native menu hold into state10. ADMIT checks the original idle save binding and party ownership and does not consume the ordinary battle sequence. It can finish after connection loss under the same original authority. Native emergency BEGIN19 returns the distinct save status14 while the Enter latch owns the field, without exporting, changing grants, consuming the save sequence or taking another hold; unrelated save mutations cannot displace that latch. The client retains evidence of that exact refusal and continues the original admission lifecycle.

Every client must fsync its exact complete BIND intent and acknowledge its SHA-256 before the host publishes any native BIND for execution. The host records these acknowledgments in the route journal. Original ADMIT receipts can reconstruct undispatched BINDs after host loss, including a second restart that leaves some clients with complete BIND intents and others with provisional intents. This requires current authenticated ownership of every original canonical checkpoint and proof of every original native core; it does not admit replacement processes.

## Durable route and native suspension

The host's bounded, append-only route journal persists every issued command before publication and every native response before acknowledgment. Canonical records form a SHA-256 chain. Cold reconstruction refuses truncated, changed, reordered, foreign or oversized records. The live owner also checks file identity, size and last-write metadata before each append. Windows path and descriptor APIs disagree about deprecated `ctime`, so only POSIX uses that additional change-time check. File data is fsynced; the shared directory-sync helper does not issue a directory fsync on Windows, and these checks do not claim power-loss durability.

An opted-in native watchdog suspends the existing battle instead of ending it. Native state9 preserves the original party, personal RNG, controller queues and sequence cursor while clocks and callbacks remain held. The host reconstructs its existing router from exact historical receipts. It then observes and suspends every retained original core, reauthorizes the same roster under current nondecreasing authenticated leases, fsyncs the full renewed quorum, and only then sends RESUME. A later loss requires a strictly newer quorum epoch; an old token cannot thaw another suspension episode. Uncertain commands are replayed only as the exact original dispatch under recorded lease lineage.

No reconnect timeout chooses a result, awards a win, forfeits, writes a guessed checkpoint or substitutes an emulator snapshot. Internal irrecoverable native state remains held. Process termination or power loss that destroys the original native core remains outside this recovery mechanism.

## Completion and save handoff

An opted-in RELEASE restores the original party and field, then keeps a terminal field hold until every participant's actual release receipt is durably settled. A lost acknowledgment can therefore reconcile the original receipt without allowing offline field progression. RETIRE20 names the exact generation, release sequence, party CRC and outcome; it retires that battle marker while keeping a separate handoff hold. HANDOFF21 can release that last hold only after the client has registered and armed its fresh emergency-save successor. Exact retries are inert and cannot relatch a completed battle or affect a later battle.

After global closure, one original trainer may retrieve the already-proven terminal receipt and retire locally without recalling peers who have already finished. The host rechecks that receipt against the committed terminal digest. This is terminal reconciliation, not another gameplay execution or quorum outcome.

`gMultiplayerBattleHoldFlags` is a compiler-symbol read-only diagnostic for actual proof observation: `0x1` Enter latch, `0x2` provisional admission, `0x4` suspension, `0x8` terminal release hold and `0x10` retired handoff hold. It is never an input or a substitute for authenticated production receipts. Production mailbox RELEASE and RETIRE replies are not decoded as generic QUERY responses.

## Reuse and limits

This adapts the project's original executor, battle desk, save ownership, same-database reservations and journal helpers. The exact engine/upstream/community investigation is recorded in [the execution audit](native-battle-execution.md#research-and-reuse). No new external implementation, dependency, asset, save layout or gameplay rule is incorporated.

Native admission-abort cleanup is not implemented in this candidate. An uncertain or refused entry after the local hold has begun remains held with its evidence. In particular, stale live party data relative to the accepted checkpoint, or an explicit cancellation racing entry, must not be represented as a successful resumed battle. Save now before challenging is the current preparation requirement; this does not replace the outstanding safe pre-start cleanup work.

Required acceptance remains a coherent combined-binary actual proof of pre-BIND, mid-battle and uncertain-release loss using all original cores, plus the native Players-menu entry boundary and Windows regression. Existing four-core full-party and two-core singles execution evidence covers the earlier non-resume executor and is not reused as proof of this extension.

The Windows focus passed **53/53 methods in 90.023 seconds**, with no skips and verified BelowNormal priority: seven recovery network cases, seven native codec/journal cases, eleven public protocol cases, six real-Lua menu bridge cases and twenty-two menu-session cases. The recovery cases use real authenticated TCP/SQLite with explicitly synthetic native responses. They cover original-core quorum replay, uncertain RELEASE, undispatched BIND, provisional bootstrap, mixed provisional/full-intent second restart, original consent/entry authentication and terminal retirement with a finished peer offline. Private log `battle-recovery-host-menu-focus-6.log` has SHA-256 `cbcaba4df5fda395f08493c4f87693310f112d3a0b5fe696d78bdde9d2b8b809`.
