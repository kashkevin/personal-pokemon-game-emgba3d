# Native emergency preservation prototype

The accepted host-loss policy is to save and disconnect, preserving an interrupted multiplayer battle until every participant reconnects. This prototype establishes only a native save-and-hold primitive for a game whose save mailbox is initially idle and bound. It is not yet enabled by the launcher. A rejected or unsafe save must remain visibly **unsaved and held**, with the process retained; it must not be described as a completed save or silently closed.

## Reuse audit and source boundary

The isolated native worktree starts from `84a4d1c1e906bd7340b9d08b231e485b0fa5c07c`, preserving the qualified Players/Multi source and all private proof inputs. The existing project serializer, ownership allocation, command mailbox, CRC/read window and callback/clock holds supply the implementation. No external code, assets, runtime or dependency is added. Existing save bytes and ownership schemas remain unchanged.

The audit also checked maintained [RHH save source](https://github.com/rh-hideout/pokeemerald-expansion/blob/master/src/save.c), [RHH main loop](https://github.com/rh-hideout/pokeemerald-expansion/blob/master/src/main.c), and the official [mGBA scripting API](https://mgba.io/docs/scripting.html). Ordinary native serialization and frame scheduling are reusable; the project's authenticated ownership and disconnected-preservation contract require custom integration. These are research references, not incorporated dependencies. Existing engine attribution and unresolved inherited asset terms remain as recorded in the [dependency ledger](dependency-ledger.md). No migration or performance claim follows from this source-only change; build memory usage and actual-core behavior require separate evidence.

The pinned implementation exposes concrete reasons not to reuse ordinary export completion unchanged. `MultiplayerOwnership_PrepareExport` requires an active grant after every load. Ordinary END acknowledges ownership retirement entries, while its watchdog releases the field after 600 emulated frames without commands. Existing trade holds have different settlement rules. Emergency preservation must neither acknowledge a nonexistent host commit nor use a trade opcode as a substitute.

## Optional native contract

The new build alone exports the retained `u32` marker `gMultiplayerEmergencySaveAbiVersion = 1`. The optional manifest fields are `emergency_save_abi_version` and `emergency_save_abi_address`. Existing save ABI, mailbox size and all old opcode numbers remain unchanged. The bridge advertises `Z` followed by little-endian `<HHHH>(1, 19, 21, 10)` only after verification; ordinary public `save_rpc` does not gain offline authority from that marker.

| Opcode | Command and result |
| --- | --- |
| 19 BEGIN_EMERGENCY_EXPORT | Empty data, offset 0, 128 KiB total, positive target revision equal to the launcher's verified base plus one. Requires the exact existing native binding. It permanently holds that core. A safe field with an accepted active grant uses ordinary native serialization and returns the existing 40-byte export metadata. Unsafe admission, absent grant or native save failure returns its error and retains an unsaved hold. |
| 20 PRESERVE_EMERGENCY | Empty data, offset and completed read cursor both 131072. Requires valid frozen bytes. Returns the complete-stream CRC32 and remains held. The caller must durably write and verify the payload and recovery intent before requesting this receipt. It proves neither disk persistence nor host acceptance by itself. |
| 21 QUERY_EMERGENCY | Empty data and offset 0. A 48-byte observation preserves the last mutating command's cached reply and does not consume its sequence. Active observations require the exact original binding, operation UUID and target revision. |

Successful export uses state 2 (EXPORTING) with an emergency latch, allowing the existing 128-byte READ and optional 4096-byte READ_WINDOW. State 9 is EMERGENCY_UNSAVED and exposes no export stream. State 10 is EMERGENCY_PRESERVED after a complete read and preservation request. No emergency path calls `MultiplayerOwnership_Acknowledge`. END, CANCEL, import, grant, BIND and trade controls cannot remove this latch, alter its binding or discard retirement entries. The emergency watchdog never releases it. Exact last-command replay remains idempotent.

The query payload is little-endian: flags at +0; native save state at +4; operation UUID at +8 (16 bytes); original session epoch at +24; incarnation at +28; target revision at +32; read cursor at +36; streamed CRC32 at +40; original failure status at +44. Flags are 1 for an unsaved hold, 3 for valid frozen export, and 7 for preserved export. Inactive observations contain only the current state, with every other payload byte zero. For active observations, binding and cursor fields must agree with the correlated outer response.

## Integration requirements and limits

Fresh Continue needs a durably recorded host allocation and exact native grant acknowledgement before emergency saving is considered armed. The local preservation capability must belong to that same authenticated session and exact bridge object/incarnation; a replacement bridge or core cannot inherit it. Generic server RPC authentication remains required. Missing authority or an unavailable bridge does not justify memory injection, save-file replacement, a new binding or a false success message.

Before host loss, record the original world/player/build/profile, authenticated binding, local canonical base and grant provenance. Preserve complete validated Flash bytes and an immutable operation UUID/hash/base intent under the character lease. Only then request native preservation. The existing closed-start pending-export path can reconcile those exact bytes under a new authenticated host lease; ownership storage already distinguishes historical grant provenance from the current RPC lease. Rejoin must settle that exact operation before canonical installation. A newer head is a conflict to resolve, not permission to rebase frozen bytes.

An already-running ordinary save is outside this first prototype: its existing watchdog can still release after emergency admission is refused. Enabling automatic host-loss handling therefore also requires exact promotion of that original frozen operation or another verified hold strategy. Active trade and native battle requests are rejected without changing their existing holds. A solo battle, script, menu or transition cannot be serialized as an ordinary field save; its core remains unsaved and held. Durable battle reconnection/resumption is a separate implementation and no battle is automatically cancelled, rebound or awarded.

## Validation and frozen evidence

Native commit `793ac4745d60afca2aecc8fdc3d0e610317747f5` is exported as [the isolated emergency patch](../engine-patches/phase7-emergency-save.patch), applied after the exact `84a4d1c` parent above. The normal build and all **90 focused multiplayer C tests passed**, including eleven new cases. They exercise a complete native Flash stream/CRC without clearing retirement entries, incomplete-read refusal, exact reply replay after observation, permanent timeout holds, unchanged ordinary watchdog behavior, malformed/foreign admission, unsaved solo-battle/script/missing-grant holds, and preservation of existing trade/native-battle state and receipts. Neither log contains compiler warnings. These tests use native fixtures, not ordinary player progression.

Both commands used `nice -n 19 make -j1` with `LOCAL_RESET_DEVELOPMENT=0`; the focused target was `check TESTS=Multiplayer`. Before reusing generated artifacts, 30,121 unchanged tracked files were compared byte for byte against the unmodified parent and received matching timestamps. All three changed tracked paths and the new test file were rebuilt. Private cache provenance records 38,692 copied ignored artifacts. Normal linked use is EWRAM **233,432 bytes**, IWRAM **28,376 bytes**, and ROM **26,782,588 bytes**. No new gameplay or pause-performance measurement is claimed.

The matching Python/Lua protocol is committed at `b60618b`. Its affected Windows group passed **64 tests** without skips in 7.199 seconds, including thirteen new protocol-module cases and one new companion case. These verify manifest/marker gates, exact command/response/query shapes, correlated active payloads, old-build rejection, bounded capability advertisement and refusal to expose emergency authority through ordinary `save_rpc`. The final protocol log SHA-256 is `5b526ed827650b6cbe9bad86078ef285c911be0faadd5489a4145fa70c6c3984`; evidence SHA-256 is `cfe610ae8627b1280d6a2b39e42b07e59dde3cd8d1d4f6d405f4220aa30c6913`. Three attempts remain archived under private `artifacts/emergency-save/protocol-1`, including the earlier fixture correction.

| Frozen native artifact | SHA-256 |
| --- | --- |
| Normal ROM, excluded from Git | `8b4ceb64af97287bf91cd29a9c09952b2e85e30f3e096194a59bad294ef448fc` |
| ELF | `a6de5aa07928976da4e002a73f21efbc1272a7c1b9df9f283a72938dd416f4c8` |
| Compiler-derived manifest | `da76d2feb273fcd829b1af062c4cf47ee4860f6baf796a8e2ebe9df2c8b61b63` |
| Normal build log | `f4f2bfb9f30554fc1a87338c01a693616de52aab0cc37b70df3340acfc30d92f` |
| Focused C log | `ccda9e0e894e757203c849f8817cf471be62b8b1a195c422003582575d7a1948` |
| Source patch | `2fd433608a10d8a22059c5e0472feda51ceb7fcf50d0824568ceabf144846c36` |
| Build evidence | `716dba7ad8ed10dac4022a6ba3305e362a1f10ea34751a146b405392d68c3007` |

Frozen files are under `/home/kevin/src/pokemon/multiplayer-proof/native-emergency-save-dev0-build-793ac474`, with a matching private Windows archive under `artifacts/emergency-save/`. All sixteen copied files, including the archive index, were hash-verified. The index SHA-256 is `7d86fe82a4f59b5e7a4aeb4f7037273a4fb9de242ee354badca1cd71f15c5417`. The qualified parent ROM hash remains unchanged, and package 4 was not rebuilt.

The dedicated offline controller, actual-core interruption/readback proof, immutable local journaling, exact authenticated rejoin and retained-process lifecycle checks remain pending. No emergency save is auto-enabled by the launcher, and compilation, fixtures or protocol tests do not establish that host-loss recovery is delivered.
