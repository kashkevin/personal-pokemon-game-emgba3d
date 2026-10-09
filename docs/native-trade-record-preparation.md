# Native trade record preparation — source implementation

This addition computes a received Pokémon's candidate record, including native trade evolution and its move decisions, on private copies. It is **source-only, unbuilt and untested** under the owner's instruction to stop testing and continue implementation. It does not enable player-facing trade evolution, advertise a mailbox capability, modify a save or relax the existing exact-swap transaction/history validator.

## Reused native behavior

The later [save-wide candidate layer](native-trade-save-effects.md) extends these same native files with saved-block replay and complete paired Flash reconstruction. The hashes below preserve this earlier record-only delta; the new document records current hashes and its additional patch.

The source extends `include/multiplayer_trade_effects.h` and `src/multiplayer_trade_effects.c` in the existing engine worktree at `/home/kevin/src/pokemon/engine-admission-cleanup-20261008-1`, base `aef47e4b28fd6d0e84376961e0cc6632996bb0be`. The earlier read-only preview remains intact. The [effects audit](native-trade-effects.md) and [friendship plan](trade-friendship-plan.md) retain their source, licensing and compatibility findings. A current read-only upstream HEAD check again returned RHH `7b95be15d84a053948791ce91e5dec0b168947a5`; no upstream revision was imported or installed.

The pinned `GetEvolutionTargetSpecies` and `DoesMonMeetAdditionalConditions` provide trade target, held-item, counterpart and Everstone behavior. `CalculateMonStats`, native setters, `GiveMoveToMon`, `CannotForgetMove`, `RemoveMonPPBonus` and `SetMonMoveSlot` provide the actual record mutation rules. The native trade evolution scene's nickname/language check and evolution-move ordering are adapted locally. No external implementation or new dependency is added.

The whole `TradeEvolutionScene` remains unsuitable as a preparation callback: it owns live party references, graphics/link callbacks and immediate Pokédex/stat updates. `DO_EVO` can also consume a real bag item for some evolution conditions. The new record helper therefore accepts only the current held-item and trade-counterpart condition families, refusing unsupported conditions before mutation. It never invokes a native link save or writes the live party, bag, Pokédex or statistics.

## Actual candidate computation

`MultiplayerTradeEffects_BeginRecord` validates two distinct assigned party records and creates a private received copy. Eggs, mail, uncatalogued forms/species, native trade prohibitions and post-Gen6 moves are refused. The caller must supply friendship already resolved from trusted complete handler history; this helper does not initialize unknown legacy history or infer a geographic refresh policy.

The helper applies that resolved friendship, determines a native trade target, consumes only an applicable held item on the copy, updates species, clears the evolution tracker and recalculates party stats. The single shared `gBattleScripting.levelUpHP` scratch byte written by the stat helper is saved/restored. A local nickname buffer reproduces the existing same-language/default-species-name rule without modifying `gStringVar1`. Foreign-language names and actual nicknames retain the pinned engine's behavior. Growth-rate changes and inconsistent level/experience are refused rather than silently changing level.

Evolution moves are scanned in native learnset order using a private cursor. Existing moves are skipped and empty slots learn automatically, matching the native helper. A full moveset pauses at `CHOOSE_MOVE`. `MultiplayerTradeEffects_ChooseMove` requires the exact zero-based choice sequence and pending move. Slots 0–3 replace that move, preserving native unforgettability checks and clearing the selected PP Ups; slot 4 explicitly declines. Invalid, repeated, stale or out-of-order choices leave the current preparation unchanged. There is no invented default choice, evolution cancellation policy or automatic move deletion.

`FinishRecord` returns the complete 100-byte record only in `READY`, with assigned identity and species rechecked. `ReplayRecord` reconstructs from the original pair and every exact choice; missing and trailing decisions are refused. Output/input overlap is refused. Preparation owns 192 bytes of caller-provided scratch, with no persistent EWRAM allocation or heap use. Sixteen interactive choices, 256 learnset entries, 64 evolution entries and 16 conditions are explicit fail-closed adapter capacities. Exhaustion refuses the candidate instead of truncating decisions or publishing a partial result. Stack cost and performance have not been measured.

The helper reuses the compiled native rules. These adapter capacities are refusal limits for supported trusted-ROM content, not memory-safety validation of arbitrary replacement tables: the preserved preview calls native `CHECK_EVO` before the adapter's bounded condition scan. Restricting the roster and move IDs does not certify that all species tables/configuration already implement the complete accepted Gen6 rules. The separate Gen6 foundation and approved-form work remain necessary before enabling this capability.

## Strict record witness

`src/emerald_multiplayer/trade_effect_witness.py` supplies typed `EffectContext`, `EvolutionMoveChoice` and immutable `RecordEffectWitness` records. Context binds world, transaction/generation, recipient/preparation identity, original lease, canonical checkpoint revision/hash, paired preparation digest, build/rules and exact native source digest. The receipt additionally binds both complete original party records, the pinned Gen6 friendship table, retained original/handling history, recipient identity, explicit refresh decision, ordered move choices, resulting friendship history and complete candidate hash.

The UUID `checkpoint_request_id` corresponds to the recipient's frozen checkpoint request (`LiveTradeCoordinator` intent `prepare_id`, or descriptor `players[].request_id`). The separate 64-hex `pair_preparation_sha256` corresponds to the shared descriptor `preparation_id`. They are different identities and cannot replace each other.

`prepare_record_effect` derives friendship through the existing complete-history planner and pinned species-base table. Unknown history is refused. It **requires a trusted native recomputation callback** executing the adapter on copies; there is no fallback that accepts a client-supplied output or hash. `validate_record_effect` takes a separately authenticated expected context and repeats the calculation before comparing the entire immutable witness. A network reply cannot choose the engine, context or replay implementation.

An independent encrypted-record projection also rejects changes outside the permitted fields. Immutable serial/PID/OT, nature, ability slot, IVs, EVs, origin, ball, ribbons, shiny modifier, status, level, mail and ownership bits are preserved. Only resolved friendship may change without evolution. Evolution permits its exact native species/item/name/tracker/derived-stat changes and the replayed move/PP decisions. The projection is an additional guard, not authority for arbitrary values in those fields; exact native recomputation remains mandatory.

This witness is an internal prerequisite, not a new wire protocol or durable store schema. Its trusted native replay transport is not yet connected to the server. It cannot be supplied to `commit_trade` to bypass the existing exact-record validator.

## Remaining integration boundary

The [recipient preparation flow](trade-recipient-preparation.md) remains connected for exact swaps only. Native move-choice presentation under the original held transaction, a authenticated native command/receipt, completed save-wide candidate export, received/evolved Pokédex updates and exactly-once statistics still need integration. Those changes must have explicit permitted-byte reconstruction and durable history replay in the same atomic ownership transaction. Both recipients must finish before either canonical head changes; cancellation and interrupted recovery must retain the original authority.

Egg hatch origins, recipient-local mail, alternate forms and unresolved Gen6 handler-history/geographic policies remain explicit gates. No native scene, save mailbox, server dispatch, ownership history, launcher or eligibility gate was altered in this slice. It is incorrect to report completed playable trade evolution from this internal record engine.

## Preservation and evidence

Exact original native files are retained at `/home/kevin/src/pokemon/trade-record-source-before-20261008-1`. The source-only [additive patch](../engine-patches/phase3-trade-record-preparation.patch) contains only the two trade-effect files; other uncommitted engine features are preserved. Bare base `aef47e4` does not include this change.

| Record-only source snapshot | SHA-256 |
| --- | --- |
| `phase3-trade-record-preparation.patch` | `04cfc547f27c39d3ff8c4e64bff297c71e8ce801049a866a5d0092f90b18f296` |
| `include/multiplayer_trade_effects.h` | `974d9b68d6721ecede8ce987b3fadd6fc82cf116d4a4a739aff51fea8a7de61a` |
| `src/multiplayer_trade_effects.c` | `96637b8fb475983d7df87ff740256febe722c339fb347354f910e9580ee5ab9f` |
| `trade_effect_witness.py` | `8426471c1eff012fcafe585e4b98944bfc7a3ffb36830c6fa37603d0f8bca492` |

No test, build, application import, game launch, native replay, private save read, dependency install or commit was performed for this change. Existing preview/candidate proofs predate it. Compilation, ordinary choices, all encrypted permutations, aliases, capacity exhaustion, full global/RNG preservation and interrupted paired publication remain unverified until testing is authorized again.
