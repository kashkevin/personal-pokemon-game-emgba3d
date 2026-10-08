# Actual-core battle interruption controllers

These controllers prepare bounded qualification of the optional `battle_resume_abi_version=1` implementation. They are separate from the preserved uninterrupted battle and native trade-menu proofs. Completed-run evidence is recorded below; each controller's scope needs its own acceptance. Their presence, import checks and the related Python/native fixture passes do not establish resumed gameplay acceptance.

Both require exact ROM/ELF/manifest pins, the existing private mGBA harness and independently obtained source saves. They run only in a new private `multiplayer-proof` directory, copy the saves and build inputs, archive/hash the actual Python and bridge sources, and refuse changed source files during a run. Invoke them from a frozen application tree. They operate ordinary joypad input and production RPC/mailbox paths. Memory, ELF symbols and Flash dumps provide read-only diagnostics; there are no RAM writes, savestates, injected party data, debug warps or selected battle outcomes. Only the controllers' own disposable child processes and mirrors are closed during cleanup.

## Four original cores and wait-all recovery

`scripts/multiplayer/native_resume_proof.py` uses four independent originals and the production `NativeBattleSession`, host executor/journal, `NativeBattleRecoverySession`, emergency controllers and terminal handoff. `--require-full-parties` requires all six ordinary party members per trainer and an actual sixth-slot switch. It imports the pinned frame pump from the separate baseline proof rather than inventing another native transport.

The `--scenario` choices are `pre-bind`, `mid-battle`, `post-release` or `all`. The `all` selector queues the three faults during one original battle, preserving original full-intent bytes across repeated authentication renewals. A pre-bind fault withholds the first full BIND after all full intents are durable; it does **not** qualify the earlier Players Enter/provisional-only boundary. The mid-battle fault waits for actual START and routed controller activity. The post-release fault withholds one actual successful RELEASE receipt from the client journal. No fabricated response is substituted.

The controller closes the host transport/service, reopens the real SQLite store on the original port, and retains every original emulator process, bridge, incarnation and native runtime ID. Only three explicit recovery clients reconnect first. Sustained ordinary input, native hold markers and read-only party/RNG/clock/gameplay diagnostics must show that all originals continue waiting for the fourth. Replacing a retained mirror must be refused. The fourth explicit action then lets the production recovery protocol continue the same battle.

The read-only `gMultiplayerBattleHoldFlags` compiler symbol must have size four in the exact ELF. State 10 requires provisional bit `0x2`, state 9 requires suspended bit `0x4`, and terminal state 1 requires `0x8` or `0x10`. A plain idle state cannot satisfy a terminal hold. RELEASE and RETIRE responses have their own formats; the controller never interprets them as a query or issues a query outside production authority merely to obtain evidence.

After verified closure, original party/count/RNG restoration and Flash identity are checked. Old emergency controllers retire only through exact durable terminal evidence. New controllers arm before production HANDOFF. Ordinary checkpoints must preserve each owner's inventory and map. The retained Companions are then closed through their public lifecycle and fresh Companions authenticate for ColdStartRecovery and a real fresh Continue; the proof never clears a retained reconnect fence.

## Earliest Enter and host-loss race

`scripts/multiplayer/native_battle_entry_proof.py` is a shorter two-core boundary exercise. It navigates the actual Players menu to invite, accept and choose Enter. It delays one exact marked CHOOSE before `MenuSession.feed`, closes the host, and requires a real native emergency BEGIN response with `BATTLE_ADMISSION` status 14 while no provisional intent has yet been published. The other original core must finish ordinary emergency preservation, with its local candidate independently read back.

The selected core must retain the native Enter-latch bit `0x1` through sustained Right, B and the traditional reset-button combination. Party bytes/count, both RNGs, position, clock, save counter and Flash must remain unchanged. The same delayed IPC bytes are then delivered to production MenuSession. A synchronous callback uses the original authenticated session captured when Enter was displayed to publish the admission; production offline preparation must provide an exact durable ADMIT receipt and atomic native CLOSE. The same checks repeat with provisional bit `0x2` on the same original core. No execution readiness or full BIND is issued in this admission-only scope.

The entry controller uses explicit callbacks around production admission helpers. It is **not** a launcher playthrough and does not prove complete battle resumption, outcomes, fresh Continue, Windows packaging or Internet connectivity. It intentionally ends with its disposable original core held after admission. This narrower result must remain distinct from the four-core battle completion proof.

## Current verification

The first main controller import and `--help` check completed successfully. The private log `native-resume-proof-help-1.log` has SHA-256 `0a73e446f85a5ce28710577354f672469fad483198c377f7875984353c408b22`. Source review then corrected assumed retained-Companion automatic reconnect to use fresh public cold-start clients, and the separate entry controller's pre-invitation emergency capture now uses ordinary session pins before a battle runtime ID exists. Both final controllers imported and displayed `--help` successfully in 1.21 seconds. The private log `resume-entry-proof-help-2.log` has SHA-256 `feb8c05fc9ba88c5d1f0f8b809c9eb26d1764fd8d11e44f1db93bf3470244202`. This is syntax/import/argument wiring evidence only; actual-run evidence must still identify the frozen application and exact native manifest.

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
