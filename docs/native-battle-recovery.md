# Retained original-core battle recovery candidate

This is an optional, unpromoted extension of the qualified [production executor](native-battle-execution.md). Its compiler-located `battle_resume_abi_version=1` marker requires native battle ABI3 and execution metadata. Existing manifests and the qualified Windows preview remain unchanged. Compilation and synthetic protocol checks do not establish playable interruption recovery.

## Original entry and ownership

The host records each authenticated trainer's original incarnation and local runtime UUID when that trainer consents. Consent remains ordinarily cancelable until explicit entry. The optional Players screen marks its exact enabled Enter row; native joypad selection latches the menu before emitting its IPC request. The latch freezes field callbacks, clocks and soft reset, and survives delayed IPC, B, ordinary CLOSE and disconnection. Other menu/trade behavior retains its existing rules.

The client publishes an immutable provisional intent, claims entry and uses the exact ADMIT19 control to transfer the native menu hold into state10. ADMIT checks the original idle save binding and party ownership and does not consume the ordinary battle sequence. It can finish after connection loss under the same original authority. Native emergency BEGIN19 returns the distinct save status14 while the Enter latch owns the field, without exporting, changing grants, consuming the save sequence or taking another hold; unrelated save mutations cannot displace that latch. The client retains evidence of that exact refusal and continues the original admission lifecycle.

Every client must fsync its exact complete BIND intent and acknowledge its SHA-256 before the host publishes any native BIND for execution. The host records these acknowledgments in the route journal. Original ADMIT receipts can reconstruct undispatched BINDs after host loss, including a second restart that leaves some clients with complete BIND intents and others with provisional intents. This requires current authenticated ownership of every original canonical checkpoint and proof of every original native core; it does not admit replacement processes.

## Durable route and native suspension

The host's bounded, append-only route journal persists every issued command before publication and every native response before acknowledgment. Canonical records form a SHA-256 chain. Cold reconstruction refuses truncated, changed, reordered, foreign or oversized records. The live owner checks file identity, size, last-write metadata and the exact latest committed record before each append. The bounded tail comparison matters because the tested WSL filesystem can assign an in-place rewrite the same approximately 4 ms timestamp tick. Windows path and descriptor APIs disagree about deprecated `ctime`, so only POSIX uses that additional change-time check.

These live checks do not scan the whole file: an older-prefix edit hidden by identical metadata can remain undetected during appends. Before live or replay-complete terminal publication, a single full-file SHA-256 check compares every byte with the digest maintained from the exact validated load/append bytes, checking the open descriptor and path identities through the read. This prevents such a changed prefix from authorizing closure, without making each command reread the entire growing journal. Cold reconstruction separately validates every canonical record and hash link. These are integrity checks, not protection against a hostile process continuously rewriting the same file. File data is fsynced; the shared directory-sync helper does not issue a directory fsync on Windows, and these checks do not claim power-loss durability.

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

A further review found that provisional bootstrap could append missing first BINDs after an already-converted client opened the recovery journal. Commit `a13f6e6` reloads that strict journal before another admission acknowledgment while the recovery task has not yet started. Both mixed-restart network cases passed in **16.455 seconds**, including a valid durable prefix containing only one trainer's BIND. Log `battle-recovery-mixed-prefix-focus-8.log` has SHA-256 `78a60fd0ffeb92a59977a36378a8367a6d63a84b2dcc71fb4ec2bcbf65a651b4`.

The subsequent WSL regression exposed the equal-timestamp live-journal gap described above. The corrected ten-method codec/journal/terminal-integrity focus passed on WSL and on verified BelowNormal Windows (**0.089 seconds**, Windows log SHA-256 `9d6936102bc7915cd32e84a1c2548ead5fe47edaa7be513cdcfc09f19fbc5d2e`). A thirty-method WSL recovery/executor cohort imported from the Windows mount had twenty-nine passes and one provisional-bootstrap fixture timeout at its unchanged fifty-second bound (**382.267 seconds** total; failed log SHA-256 `b544dafd46116592b444976d74efd6badcbb670b2d28f7d437486aebd777d8ca`). That exact case then passed in **12.912 seconds** from a verified immutable ext4 snapshot with identical production/test bytes and the same timeout; log SHA-256 `86638b9a20e50a067a3d90fb7c4dc51e642a781a5b3bc0c22fc1ed4886ba7cd4`. The failed run is retained rather than treated as a passing cohort; filesystem/import latency is a plausible contributor, not a proven exclusive cause.

## Combined native source qualification

The isolated combined candidate `aef47e4b28fd6d0e84376961e0cc6632996bb0be` starts from the unchanged qualified combined source `1a7a0cdb5dadd2820a3b6c25c4ecafce1facd6eb`. Its composition preserves the trade-menu reopen path, emergency ABI2 and authored local-reset ABI2. The [reviewable delta](../engine-patches/phase5-native-retained-recovery.patch) is 57,370 bytes with SHA-256 `94ee6c7c62beb1c97f4d222a9f4a3c6aec1f329f994fdf2ec8c56a19de48b078`; a read-only application check passed against the unchanged base.

Normal and **129/129 focused native tests passed without warnings** using `DINFO=1 DEV=0 LOCAL_RESET_STATIC=1`, `nice -n 19` and `make -j1`. The fresh worktree regenerated headers and initially produced a clock-skew warning; that output is retained separately, and qualification uses the later warning-free incremental normal and focused runs. Native tests include suspension/repeated-loss fencing, provisional hold consumption, terminal retirement/handoff, the Enter latch and exact emergency-BEGIN refusal without party/ownership/RNG/save-counter mutation. They use the native test runner and do not establish ordinary-menu or four-human playable recovery.

Private bundle `combined-resume-native-aef47` retains these exact files:

| File | SHA-256 |
| --- | --- |
| `pokeemerald.gba` | `47b815b5625fc3db04e00fc976da981f282895328d20f4f650de17ed223e9f3e` |
| `pokeemerald.elf` | `b11751bd7cf3b3ac7757995197e781cd2a21d8cb370cd1db0d152f8577fda694` |
| `manifest.json` | `00e193485caac413cdad384fe96d285fd69af71844a735869b1f2fcaf54a256d` |
| `combined-resume-normal-4.log` | `9add31430c6923faf695905b10770262615c7a719a5006e9c5d9e4446e08495c` |
| `combined-resume-focused-4.log` | `8267dfd2b863dcdd2ac58c33d5ee875ea4d938578317bcf483ce2abf0171977a` |

The manifest came from the frozen `a13f6e6` compiler-symbol generator and verifies the exact ROM/ELF capability markers. Link usage is 233,764 bytes of EWRAM, 28,376 bytes of IWRAM and 26,791,424 bytes of ROM before padding. Original qualified sources, binaries and private saves remain untouched. This candidate remains excluded from the stable Windows preview pending actual combined-core acceptance.
