# Actual-core battle interruption controllers

These controllers prepare bounded qualification of the optional `battle_resume_abi_version=1` implementation. They are separate from the preserved uninterrupted battle and native trade-menu proofs. Completed-run evidence is recorded below; each controller's scope needs its own acceptance. Their presence, import checks and the related Python/native fixture passes do not establish resumed gameplay acceptance.

Both require exact ROM/ELF/manifest pins, the existing private mGBA harness and independently obtained source saves. They run only in a new private `multiplayer-proof` directory, copy the saves and build inputs, archive/hash the actual Python and bridge sources, and refuse changed source files during a run. Invoke them from a frozen application tree. They operate ordinary joypad input and production RPC/mailbox paths. Memory, ELF symbols and Flash dumps provide read-only diagnostics; there are no RAM writes, savestates, injected party data, debug warps or selected battle outcomes. Only the controllers' own disposable child processes and mirrors are closed during cleanup.

## Four original cores and wait-all recovery

`scripts/multiplayer/native_resume_proof.py` uses four independent originals and the production `NativeBattleSession`, host executor/journal, `NativeBattleRecoverySession`, emergency controllers and terminal handoff. `--require-full-parties` requires all six ordinary party members per trainer and an actual sixth-slot switch. It imports the pinned frame pump from the separate baseline proof rather than inventing another native transport.

The `--scenario` choices are `pre-bind`, `mid-battle`, `post-release` or `all`. The `all` selector queues the three faults during one original battle, preserving original full-intent bytes across repeated authentication renewals. A pre-bind fault withholds the first full BIND after all full intents are durable; it does **not** qualify the earlier Players Enter/provisional-only boundary. The mid-battle fault waits for actual START and routed controller activity. The post-release fault withholds one actual successful RELEASE receipt from the client journal. No fabricated response is substituted.

The controller closes the host transport/service, reopens the real SQLite store on the original port, and retains every original emulator process, bridge, incarnation and native runtime ID. Only three explicit recovery clients reconnect first. Sustained ordinary input, native hold markers and read-only party/RNG/clock/gameplay diagnostics must show that all originals continue waiting for the fourth. Replacing a retained mirror must be refused. The fourth explicit action then lets the production recovery protocol continue the same battle.

Before selecting a new reconnect set after each fault, the controller cancels and drains the prior explicit Python recovery operations. Production recovery intentionally retries a disconnected host, so awaiting those operations without cancellation would deadlock the second `all` stage before host restart. This bounded drain affects only operation tasks, never the original cores or immutable intents. A timeout refuses to start overlapping lifecycle owners.

The read-only `gMultiplayerBattleHoldFlags` compiler symbol must have size four in the exact ELF. State 10 requires provisional bit `0x2`, state 9 requires suspended bit `0x4`, and terminal state 1 requires `0x8` or `0x10`. A plain idle state cannot satisfy a terminal hold. RELEASE and RETIRE responses have their own formats; the controller never interprets them as a query or issues a query outside production authority merely to obtain evidence.

After verified closure, original party/count/RNG restoration and Flash identity are checked. Old emergency controllers retire only through exact durable terminal evidence. New controllers arm before production HANDOFF. Ordinary checkpoints must preserve each owner's inventory and map. The retained Companions are then closed through their public lifecycle and fresh Companions authenticate for ColdStartRecovery and a real fresh Continue; the proof never clears a retained reconnect fence.

## Earliest Enter and host-loss race

`scripts/multiplayer/native_battle_entry_proof.py` is a shorter two-core boundary exercise. It navigates the actual Players menu to invite, accept and choose Enter. It delays one exact marked CHOOSE before `MenuSession.feed`, closes the host, and requires a real native emergency BEGIN response with `BATTLE_ADMISSION` status 14 while no provisional intent has yet been published. The other original core must finish ordinary emergency preservation, with its local candidate independently read back.

The selected core must retain the native Enter-latch bit `0x1` through sustained Right, B and the traditional reset-button combination. Party bytes/count, both RNGs, position, clock, save counter and Flash must remain unchanged. The same delayed IPC bytes are then delivered to production MenuSession. A synchronous callback uses the original authenticated session captured when Enter was displayed to publish the admission; production offline preparation must provide an exact durable ADMIT receipt and atomic native CLOSE. The same checks repeat with provisional bit `0x2` on the same original core. No execution readiness or full BIND is issued in this admission-only scope.

The entry controller uses explicit callbacks around production admission helpers. It is **not** a launcher playthrough and does not prove complete battle resumption, outcomes, fresh Continue, Windows packaging or Internet connectivity. It intentionally ends with its disposable original core held after admission. This narrower result must remain distinct from the four-core battle completion proof.

## Current verification

The first main controller import and `--help` check completed successfully. The private log `native-resume-proof-help-1.log` has SHA-256 `0a73e446f85a5ce28710577354f672469fad483198c377f7875984353c408b22`. Source review then corrected assumed retained-Companion automatic reconnect to use fresh public cold-start clients, and the separate entry controller's pre-invitation emergency capture now uses ordinary session pins before a battle runtime ID exists. Both final controllers imported and displayed `--help` successfully in 1.21 seconds. The private log `resume-entry-proof-help-2.log` has SHA-256 `feb8c05fc9ba88c5d1f0f8b809c9eb26d1764fd8d11e44f1db93bf3470244202`. This is syntax/import/argument wiring evidence only; actual-run evidence must still identify the frozen application and exact native manifest.

The repeated-fault operation-drain correction passed **2/2 focused controller regressions in 0.049 seconds**, with no skips, followed by a successful updated import/`--help` check. The checks exercise a reconnecting task's lifecycle-lock drain without altering its original core/intent and refusal to proceed while cleanup remains unfinished. Private log `resume-proof-drain-windows-1.log` has SHA-256 `6b765fa5ebe276476a0242b5112a7fa8fc8dca4790cf156d205899d740a93cb0`. This remains controller behavior evidence, not resumed native gameplay acceptance.

The existing accepted combined native build `1a7a0cdb5dadd2820a3b6c25c4ecafce1facd6eb` has no resume marker. These controllers require a separately qualified combined native candidate; they do not modify the old build or its prior Windows/ownership evidence.

## Native entry run 1 — failed safely

The first two-core entry run used frozen application `2dba880`, combined native `aef47e4b28fd6d0e84376961e0cc6632996bb0be`, ROM SHA-256 `47b815b5625fc3db04e00fc976da981f282895328d20f4f650de17ed223e9f3e` and ELF SHA-256 `b11751bd7cf3b3ac7757995197e781cd2a21d8cb370cd1db0d152f8577fda694`. The actual menu reached the early host-loss boundary and native BEGIN returned status 14 before any provisional file existed. Python nevertheless reported `unsaved_held`, so the run failed before the delayed Enter transfer and did not qualify offline ADMIT or atomic CLOSE.

The response retained the previous completed stream cursor 131072 while request sequence 39 used cursor 0. Python had incorrectly included that diagnostic cursor in request identity comparison. [The cursor correction record](native-battle-client-recovery.md#actual-entry-refusal-cursor-correction) preserves the exact actual packet hashes, correction `d976ed6` and focused evidence; native source remains unchanged. This failed run's pending emergency intent and all diagnostics are retained as observed.

| Run 1 private evidence | SHA-256 |
| --- | --- |
| `native-battle-entry-run-1/evidence.json` | `7a4fd4aedd678057e07e63c7e3f6703a7a5abf9d7524543a2df5130568e75bd2` |
| `native-battle-entry-run-1.log` | `2fbf9160c1c747088382be480e2b07ab926ec65c739eb9f77599c57649f30ae5` |
| Native manifest | `00e193485caac413cdad384fe96d285fd69af71844a735869b1f2fcaf54a256d` |
| Bridge source | `2735e43b93dedc74a479add57d1ea8849f7e0976dea3dd745b060316681f45c4` |
| Controller | `53c0ccec024624c86db863b892e2eb0826cc555bd4fb424f18a9a8f7950ea5e4` |
| Private harness | `e37e6d125079c141fbaa5f02b4b55f3c0918ba5d5d24c97ba857dd01804350a5` |

Evidence confirms both disposable cores closed, original saves were unchanged and frozen Python sources were unchanged. Independent Windows copies reside under `%LOCALAPPDATA%\PokemonPrivate\artifacts\battles\resume-candidate-failed-evidence-1`, with every file verified against its unchanged WSL origin; the combined 134-file inventory is recorded in [the WSL regression archive](battle-resume-regression.md#complete-wsl-run-2). The failed run remains separate from subsequent reruns and establishes no complete battle, launcher, Windows or Internet acceptance.

## Native entry run 2 — qualified admission boundary

The corrected rerun **passed** using frozen application `d976ed684881c9a0168fa9e41014c4cf16d2ef6d`. The native `aef47e4` commit, ROM, ELF, manifest, bridge, controller and private harness hashes remain exactly those listed for run 1. The application milestone is preserved by annotated tag `NATIVE_BATTLE_ENTRY_HOLD_POC`; its peeled target was independently verified as the same full `d976ed6` commit.

Two ordinarily continued native cores enrolled and armed their real emergency controllers. On host loss, the selected core returned BEGIN status 14 before provisional publication, while the other core preserved its complete local emergency candidate. The selected original then resisted each of Right, B and the ordinary reset combination for 120 held frames plus release intervals. Its party bytes/count, position, play clock, both RNGs, save counter and Flash stayed unchanged. Delivering the original delayed Enter IPC event invoked the production synchronous publisher and offline admission helper, produced the exact durable ADMIT receipt, and atomically closed the native menu. The same input/state checks passed under the new provisional hold on the identical emulator process, bridge, incarnation and runtime ID.

The evidence records `passed`, `cores_closed`, `originals_unchanged` and `python_sources_unchanged` as true. Root inspection and a separate Windows archive independently agreed on the evidence hash. All **142 copied files, 39,443,181 bytes** in `%LOCALAPPDATA%\PokemonPrivate\artifacts\battles\native-battle-entry-qualification-2` matched their origin before and after copying. The archive contains this run's own private copies, source ZIP, runner and diagnostics; all remain outside Git.

| Run 2 private evidence | SHA-256 |
| --- | --- |
| `native-battle-entry-run-2/evidence.json` | `c1c739dc404d087130b615736be6a4654a60d1ef4a9073dd500290f3b197ef80` |
| `native-battle-entry-run-2.log` | `c7e4ce7717e01029167c05dc145bcbe5a073534b894ba612f289695f97fc2022` |
| `run-native-battle-entry-2.sh` | `d34b19e18b9e83f28c4286e2bf242fa283d5ed45c93d23eb4734711149ac8bb9` |
| `resume-candidate-source-d976ed6.zip` | `3950fd12ed0d547c37b5655201ef895384aa10705b608b102b62a8a9f88d9eba` |
| `copy-inventory.json` | `288baed154e35b0992790e9b80b7219ddd2bdee8679abce2367ced521a9c4da2` |

This qualifies only the two-core earliest Enter/host-loss/refusal/offline-ADMIT boundary and peer preservation. It uses explicit callbacks around production helpers and intentionally ends before execution readiness or a full BIND. It does not establish full battle resumption, four-player wait-all completion, terminal save handoff, launcher recovery, Windows execution, separate-PC connectivity or Internet acceptance. The later four-core evidence below has a separate scope.

## Handoff recovery run — all three faults with populated parties

The October 8, 2026 `native-resume-handoff-small-run-1` **passed** all three faults in one battle on four retained actual native cores. It used the unchanged combined native `aef47e4` artifacts listed above and frozen application `handoff-recovery-source-20261008-221630`: HEAD `31e5bf93ec8fb24e7cf522908b540b318890d365` plus the uncommitted [provisional BIND client correction](native-battle-client-recovery.md#original-provisional-bind-recovery-correction). The private source snapshot records the exact tracked/untracked files, hashes and dirty diff; a bare checkout of HEAD does not include this correction. Controller, bridge and native source were unchanged.

The four independently obtained source parties contained **2/1/1/1** Pokémon, with every populated member available. Ordinary native input caused one actual switch to the first trainer's second party slot and a completed outcome after 1,144 routed controller blocks. The proof used `--scenario all` without `--require-full-parties`; this result does **not** qualify the six-per-trainer interruption requirement. Separate full-six attempts must be judged by their own terminal evidence.

At pre-BIND, mid-battle and post-RELEASE host loss, all four original emulator processes, bridges, incarnations and runtime IDs were retained. Native held state and unchanged party/RNG/clock/gameplay diagnostics persisted during ordinary input. Cold replacements were refused; three original reconnects remained waiting for the fourth at every stage. After the fourth reconnected, production recovery completed the same battle, including the exact terminal receipts, old emergency-controller retirement, fresh save-controller arming and HANDOFF. Original party/count/RNG/Flash returned intact. Ordinary checkpoints preserved all owners' inventories and current maps, and fresh cores passed a real Continue. Execution including the three recovery stages took 1,304.470 seconds.

The final evidence records `passed`, `cores_closed`, `original_sources_unchanged` and `python_sources_unchanged` as true. All four original proof PIDs were independently confirmed absent afterward. The completed proof, its frozen Python snapshot, runner and log were copied into `%LOCALAPPDATA%\PokemonPrivate\artifacts\battles\native-resume-handoff-small-qualification-1`. Every one of **991 files, 67,981,026 bytes** matched its origin before and after copying; the four original private source saves were separately rehashed and unchanged. None of these private artifacts belongs in Git.

| Private evidence | SHA-256 |
| --- | --- |
| `native-resume-handoff-small-run-1/evidence.json` | `7a7fcbc5a317a1527672fe8560464d0164968c28cf337a0df148fe5b3e6d22c5` |
| `native-resume-handoff-small-run-1.log` | `083c22b888e829f8e320ef6a7ccf928cf4dde0b9c991e01cb83cadabaae84f09` |
| `run-native-resume-handoff-small-1.sh` | `9a5bcd414860e528d3b58726ae336fb9bce3a41cc2e025cb83674962f64c19a7` |
| Frozen `source-snapshot.json` | `2a8c6b9cf793199b3eade747647588892da8f28b20b209fd8f25de0e0cfa7b45` |
| `copy-inventory.json` | `9f05bfb1112ac44e30d36920fe7fe20cbb8bf4a6330f12953bb85155653c6379` |

This establishes actual-core recovery completion for the stated four-player populated-party scope through production authenticated RPC and binary IPC. It does not establish native Players-menu initiation, packaged launcher recovery, Windows execution, controls, six-per-trainer interruption completion, separate-PC networking or Internet acceptance. No released engine/build manifest is changed by this evidence.

## Handoff full-six run 3 — bounded timeout, preserved evidence

`native-resume-handoff-run-3` used the same frozen `handoff-recovery-source-20261008-221630` and native artifacts, with `--scenario all --require-full-parties --timeout 3600`. It verified all four ordinary six-member source parties, all-original holds, three-wait-for-four and resumed actual gameplay after both pre-BIND and mid-battle host loss. Ordinary input selected two trainers' sixth party slots. The match was still routing ordinary controller activity at its original one-hour execution limit: 3,858 blocks, last recorded elapsed time 3,599.616 seconds. The controller correctly failed with `authenticated full Multi execution did not close before timeout` before reaching the post-RELEASE fault or terminal save/Continue checks. This is incomplete qualification, not a completed resumed battle.

Final evidence records `passed=false`, `cores_closed=true`, `original_sources_unchanged=true` and `python_sources_unchanged=true`. The four original core PIDs were independently absent afterward. The closed run, frozen source, runner and log were copied into `%LOCALAPPDATA%\PokemonPrivate\artifacts\battles\native-resume-handoff-full-six-timeout-3`; all **1,883 files, 123,407,413 bytes** matched unchanged origins, and all four original source saves were rehashed successfully. The run and its one-hour limit were never altered in progress. A longer separately frozen run is required for terminal full-six qualification.

| Private evidence | SHA-256 |
| --- | --- |
| `native-resume-handoff-run-3/evidence.json` | `8be0d53591fe92c0b43f9fa9ba124196dbe66b57af474ba272a8086ad886b79c` |
| `native-resume-handoff-run-3.log` | `bffe5deeda905e92faeec919c8b409e2b34ea8dc637fc437c17d1cacd15d2965` |
| `run-native-resume-handoff-3.sh` | `aac7485742c5a16f1289344381bd6c05bff4e6a02f1f88025c84db2f8e25e7e8` |
| `copy-inventory.json` | `60993a568eb2ef1afa8cfc687c886c680f3327619f89ebea8bcc3de9c3efb8fe` |

## Final Python rerun — populated-party recovery completion

`native-resume-handoff-small-run-2` **passed** on frozen `handoff-recovery-final-source-20261008-230121` after the [waiting-journal parsing correction](native-battle-recovery.md#uncommitted-follow-up-waiting-journal-verification) and the other handoff Python changes. Its 333-file snapshot records HEAD `31e5bf9`, every exact working-source file hash and the uncommitted diff. The native `aef47e4` build, bridge, ordinary source saves and unchanged recovery controller are the same as small run 1. The controller SHA-256 is `6eaf0914018bb642923df15e2b9f86e2d9e9f7b4e681fdc61cd9342f45d5b97d` in both snapshots.

All three faults passed again on the same four originals, with cold replacements refused and three-wait-for-four verified at each boundary. Ordinary input completed the **2/1/1/1** populated-party battle after 1,189 routed blocks and one actual second-slot switch. Exact terminal receipts, emergency-controller retirement, fresh save arming, HANDOFF, original party/count/RNG/Flash preservation, ordinary checkpoints at current maps and fresh Continue all passed. Execution including recovery took 1,016.478 seconds. This is a correctness rerun on the changed Python source; different battle RNG and workloads prevent attributing the total runtime difference solely to the waiting-journal change.

Final `passed`, `cores_closed`, `original_sources_unchanged` and `python_sources_unchanged` are all true. Original proof PIDs 6325–6328 were independently absent after the controller exited successfully. The completed output, source snapshot, runner and log were independently copied into `%LOCALAPPDATA%\PokemonPrivate\artifacts\battles\native-resume-handoff-small-qualification-2`: **955 files, 68,317,553 bytes**, each verified against its unchanged origin. All four original save hashes were rechecked. The acceptance limits remain those of small run 1: no six-per-trainer interruption completion, native menu, launcher, Windows or external-network claim.

| Private evidence | SHA-256 |
| --- | --- |
| `native-resume-handoff-small-run-2/evidence.json` | `f0b86b2c43d15c010b3959495f65462a0ed0ad7653fda6230cbd0708c0584eb5` |
| `native-resume-handoff-small-run-2.log` | `f7e5d0666ee48afc4fa79c07dea56de09ee4c3f6642c4fc684d4ab4971c4a5d4` |
| `run-native-resume-handoff-small-2.sh` | `0edf1c4793886251d9dbdb0328498995cb246e12d8796ac2b57085ecfded5b9e` |
| Frozen `source-snapshot.json` | `f5e9aebc8076521b0a41d524b36129caf917cbf925a5a1ae29553afb3dfdf63b` |
| `copy-inventory.json` | `ca8aa0d58aae89d8a5d2a0bc5cc9dfed361aa5102394152596731c4322b49e26` |

## Full-six run 4 — post-RELEASE failure retained

The separately frozen `native-resume-handoff-full-run-4` used the same final Python snapshot as small run 2, the unchanged `aef47e4` native build and four legitimate six-member parties. Its execution limit was 7,200 seconds from launch. After 5,037 routed blocks, it reached the post-RELEASE host interruption and checked that three reconnected originals remained held. The controller then failed its `any(task.done())` assertion before connecting the fourth. No successful terminal handoff, final checkpoint or fresh Continue is claimed for this run.

A done task may have raised an exception. All three partial clients retained `executing/recovery` records with dispatch 0; no terminal completion record existed. The controller's cleanup discarded the task exceptions, so the original exception is **UNKNOWN**. The later [66 MB journal diagnostic](native-battle-recovery.md#uncommitted-follow-up-responsive-initial-journal-reconstruction) reproduced a five-second RPC timeout using separate copies of this exact closed world. It supports the journal-load timeout diagnosis, without retroactively proving the discarded exception or converting this failed actual-core run into a pass. The controller now preserves failed-task exceptions in future evidence.

The run records `passed=false`, `cores_closed=true`, `original_sources_unchanged=true` and `python_sources_unchanged=true`. It overlapped bounded CPU-15 low-priority compilation/tests and cancellation proofs after system resource measurements; no game-speed comparison is inferred. No running source, deadline or original save was changed.

The complete closed output, immutable source snapshot, runner and log were copied into `%LOCALAPPDATA%/PokemonPrivate/artifacts/battles/native-resume-handoff-full-six-failed-4`: **2,215 files, 146,508,719 bytes**. Every file matched its original before and after copying. The archive retains the failure, screenshots, exact commands and private diagnostic material outside Git.

| Private evidence | SHA-256 |
| --- | --- |
| `native-resume-handoff-full-run-4/evidence.json` | `c6c8a0d630cf648289b0b99976d6372ea9f735a0559184be449d05814bfd93e9` |
| `native-resume-handoff-full-run-4.log` | `c8b7b5379d6cc89b494ef234a600171830e6c2af32e33bc328b4a144c832d988` |
| `run-native-resume-handoff-full-4.sh` | `05ba081537426dbf166c040332d47ae6e6f3fea23870adb3d908e289d36ffbb2` |
| `copy-inventory.json` | `4c01af11f2b0d3eec198572abfcc6b6f681680cbea291d59117538a1ce75ad99` |


## Final combined candidate — populated-party all-fault recovery

`combined-recovery-final-20261008-1/run-small-all` **passed** one fresh four-original-core `--scenario all --timeout 3600` run after the [asynchronous initial journal reconstruction correction](native-battle-recovery.md#uncommitted-follow-up-responsive-initial-journal-reconstruction) and exact same-lease saver handoff correction. It used the legitimate **2/1/1/1** source parties from small run 2, including an ordinary switch to the first trainer's second slot. It did not use `--require-full-parties`; the failed full-six run above remains unqualified.

This run uses the newer combined native cleanup candidate: base **`aef47e4b28fd6d0e84376961e0cc6632996bb0be` plus the uncommitted seven-file source delta**, patch SHA-256 `9f73e474f7e48d99257c74cf1b051fc80ad4ca56af1757e2d73f11962e18c067`. Bare `aef47e4` does not reproduce this binary. Its reconstruction, native tests and narrower cleanup acceptance are documented in [neutral admission cleanup](native-admission-cleanup.md). ROM SHA-256 is `a46cb8ae950d6fcf15f15fd065d5fa2cd9be4daa6a69e113e9a48651716974a8`, ELF `1aa449932c40ea9011d5e8ce4723397fadacf560c6525b96f350ca760f41e534`, and manifest `6d117095cffcb40c4f2f6d60a6a7f869b1fd3497de123c11ae1c1808df17c766`.

The final frozen application/controller/bridge/test/native-patch snapshot contains **207 indexed files**, source-index SHA-256 `57d5fbdeec57365e18473cfee0a7c3af1e9daf496d8a26889ad53ef709db29b0`, with base HEAD and the dirty working diff retained beside it. The controller SHA-256 is `63be40e4229c6eeb45bf184c9da35c35b332a960714dd1c91e6f01ed55feed9a`; it includes the correction that reports a finished task's actual exception before asserting an unauthorized successful partial-quorum completion. Eight independently hashed inputs include copied ROM/ELF/manifest/harness and the four source saves. The harness remains `e37e6d125079c141fbaa5f02b4b55f3c0918ba5d5d24c97ba857dd01804350a5`.

All three interruptions passed: pre-BIND, mid-battle and post-RELEASE host loss retained the original processes, bridges, incarnations, runtime IDs and intents. Cold replacements were refused; three original reconnects waited for the fourth. The same actual battle finished after **1,189 routed controller blocks**. Exact terminal receipts, old saver retirement, fresh emergency arming and HANDOFF passed. Original personal party/count/RNG/Flash were restored; ordinary checkpoints preserved inventories and current maps; all four fresh cores passed native Continue. Battle execution including recovery took **1,195.338 seconds**, with **1,270.456 seconds** including outer setup/cleanup. Different native source, scheduling and workloads prevent a gameplay-speed comparison with prior runs.

Final controller `passed`, `cores_closed`, `original_sources_unchanged`, and `python_sources_unchanged` are true. The independent outer watchdog also passed: no timeout, no outer forced termination and no surviving owned process; all 207 original/frozen source hashes and eight original/copied input hashes matched. It ran at niceness 19 on CPU 15, with the unchanged 3,600-second execution limit and a separate 3,900-second outer bound plus 120 seconds for orderly cleanup. Other separately frozen Windows qualifications ran concurrently; no shared game core or world database was used.

A separate Windows archive at `%LOCALAPPDATA%/PokemonPrivate/artifacts/battles/final-combined-small-qualification-3` contains the complete closed proof, frozen sources, copied inputs, runner, base/diff, and bounded journal diagnostic evidence. All **922 files, 168,047,511 bytes** matched their unchanged originals and copies. None of the private ROM/save/database artifacts belongs in Git.

| Private evidence | SHA-256 |
| --- | --- |
| `run-small-all/evidence.json` | `7ef364142a031f274f2f7fa799d8a3c2e21c6b66bb882c5c0e6c7305581ee1c5` |
| `outer-small-all.json` | `c84e017beef972a01430e94212bbb452f36d76cb4f0b5062e07289a9c9b43139` |
| `outer-small-all.log` | `c620bc06e18b6b1f7e2f27a14150c50154b810ace537e90c4453bc3e0b1b8cbb` |
| `source-index.json` | `57d5fbdeec57365e18473cfee0a7c3af1e9daf496d8a26889ad53ef709db29b0` |
| Windows `copy-inventory.json` | `0305411c0c5eb7d2f96e8c2c2ed37fb09547bad36aeb3b710cde2308bed3f735` |

This qualifies the stated four-player populated-party recovery and terminal save handoff on the final combined candidate. It does not establish full-six interruption completion, native Players-menu match initiation, Windows gameplay, physical controls, a friend-installable download, separate-PC networking or Internet acceptance. Those remain separate evidence scopes.

## Final full-six retry — stopped at the owner's request

The subsequent private `combined-recovery-full-six-20261008-1` run reused the final 207-file immutable snapshot and combined native candidate above, with the four unchanged legitimate six-member source parties and `--scenario all --require-full-parties --timeout 7200`. The owner then explicitly stopped testing to prioritize implementation. This run is **interrupted and not accepted**, with no rerun implied.

The last retained outer snapshot reports 4,042.246 seconds elapsed, 3,885 routed blocks and frame 86,739. Pre-BIND and mid-battle interruption checks had retained the originals, refused replacements and required all four reconnects. Post-RELEASE interruption, terminal handoff, final checkpoint and fresh Continue were not reached. Partial progress cannot complete the full-six recovery qualification.

Controller PID 10637 and its original cores 10639–10642 were already absent when the stop instruction was handled. Identity checking stopped the guarded signal command before it sent any signal; subsequent exact PID/argument checks found no surviving owned worker or core. The process exit mechanism and ordinary exit codes are **UNKNOWN**. Do not describe this as a proven orderly native shutdown. Logs and partial evidence were preserved unchanged; all 207 original/frozen source hashes and eight original/copied input hashes matched at interruption, before later implementation edits.

The private interruption record explicitly sets `accepted=false`. SHA-256 values are `54afc7924a618a02156f5f0eb6d24ea5b35c5353acb68e7193daa3adbffd539b` for `user-directed-interruption.json`, `6d0e443a01fdca5e9f390c4a16ee23ef5533ef4dab5a1eb0aad90186583ac1f0` for the retained partial outer evidence, and `184ac97c95be411bdb9efb66d157b6b70a05ca3e3af9442fbda85de446d06dca` for its log. This evidence does not qualify the subsequent source-only trade, host restart, reset-input, encounter or installation changes.
