# Native singles development prototype

This is the ABI2 development implementation and source record, dated October 8, 2026. A controlled two-core native singles proof now covers ordinary Continue, authenticated session-local consent, canonical party routing, moves, fainting, forced switching, result return, exact restoration, ordinary checkpoints and fresh Continue. This is development acceptance for those paths; production battle admission, malformed live traffic, interruption recovery, Windows graphical behavior and full-party 2v2 remain separate gates. The accepted ABI1 diagnostic remains frozen at `8c839171e1070ba31d66e74aae35bb207fe39b4a`.

The new isolated source is `engine-native-singles`, branch `codex/native-singles`, initially based on that diagnostic. Presence ABI1, save ABI1, ownership records, ordinary Pokémon sizes and ordinary section layouts remain unchanged. This milestone targets two individually consented trainers with their full original six-slot parties. Four-human 2v2, with up to six Pokémon per trainer and twelve per side, remains the next native adaptation; it is not implemented by these singles hooks.

The frozen native source is `7efa2448ea19d8aca9946d6572931e97428f0c94`. It also includes the independently qualified read-only save-window source `d0db4f2f4eb4c5a47292960ff161d1a7ecf0dad6` and equivalent CRC-table optimization `54f977f59df03acad69973cde1bc3b37c5f3eea0`, cherry-picked as `d7ff46578d` and `392f9cefcc`. These retain the existing save ABI and optional READ_WINDOW capability.

## Reuse and source boundaries

The native battle calculation, move/party selection, sprites, animations, scripts and controller tasks come from the pinned RHH 1.17.1 baseline `bb1093a7c72d3961d9a37d8e02ad2abc2c866682`, through ownership, trade and the diagnostic adapter. The maintained RHH revision checked for the architecture audit is `6057b187f946094d614e9c34bc12731ea6a5b7bb`; its [controller implementation](https://github.com/rh-hideout/pokeemerald-expansion/blob/6057b187f946094d614e9c34bc12731ea6a5b7bb/src/battle_controllers.c) retains the same native block/controller architecture. No upstream or community source/assets are imported by this adaptation. The earlier [transport audit](battle-transport-design.md) records mGBA/Wired reference limitations and the full-party Multi work still required.

The channel replaces serial/RFU block movement for this explicitly bound session. It does not simulate battles in Python. Native slot 0 calculates the battle; both participants run their own native rendering/controller callbacks and provide their own choices. The future authoritative server must capture consent, immutable roster/generation and current lease/incarnation, and compare each original party against its authenticated canonical checkpoint. A caller-created roster or two authenticated TCP clients alone does not prove that server admission.

The dedicated path starts outside Cable Club after a field-safe owned checkpoint. It uses the engine's normal building battle environment, matching conventional native link arenas across different exploration maps. Legacy solo, Cable Club, wireless, Frontier and recording paths retain their existing behavior.

## ABI2 control contract

`gMultiplayerBattleAbiVersion` is the ROM constant 2. `gMultiplayerBattleMailbox` remains 512 bytes: header 24, external command generation at 24, command slot at 28, response generation at 268 and response slot at 272. The Lua bridge may write only the command generation and its 240-byte slot. IPC remains `D` command, `E` reply, `W` capability. There are no destination pointers, party addresses, save offsets or arbitrary controller writes in a request.

The unchanged 240-byte control format is `<II16sIIHHBBBBBBHI192s>`: incarnation, lease epoch, battle UUID, command sequence, block sequence, offset, whole block size, opcode, status, phase, source slot, kind, reserved zero, data length, CRC32 of meaningful data, and 192-byte zero-padded data. Phase 1 retains diagnostic semantics; phase 2 is native singles with exactly two slots. Global command sequence and exact-last-command retry rules remain per binding. In phase 2 only successful mutators advance the sequence/cache: a rejected command must reuse the same next sequence when retried or replaced. Read-only QUERY never advances either. Phase 1 retains its accepted diagnostic failure-sequence behavior.

The binding remains 116 bytes: generation UUID, four player UUID slots, four leases, four incarnations, player count, local slot, phase and reserved zero. Unused slots are zero. Native count is exactly two; C checks the local player against the enrolled ownership record. UUIDs are opaque 16 bytes. Server authentication and explicit roster consent are separate required checks.

| Opcode | Command data | Successful reply | Behavior |
| --- | --- | --- | --- |
| 1 BIND | Binding 116 | Query 64 | Admit idle field, hold callbacks/clocks/reset, exclude save/trade. |
| 2 QUERY | Empty | Query 64 | Read only; does not advance sequence/cache or deadline. A newer lease may observe the same incarnation/UUID, but cannot mutate it. |
| 4 READ_OUT | Empty | Up to 128 | Sequential read of a ROM-owned outbound block; response echoes requested offset. |
| 5 ACK_OUT | `<II>` full CRC, exact peer mask | Empty | Requires complete read and peer delivery before clearing pending output. |
| 6 RECEIVE | Up to 128 | Empty | Sequential typed chunks; native receive flag is set only after final complete validation. |
| 9 KEEP | Empty | Query 64 | Refresh current binding while it is healthy. |
| 10 PREPARE_SINGLES | `<IIII16sI>` revision, native counter, trainer ID, raw party CRC, issued SFC32 state, flags zero | Query 64 | Validate local original party; back up originals and personal RNG; emit trainer descriptor. |
| 11 START_SINGLES | Empty | Query 64 | Require both validated descriptors and outbound delivery, then enter native startup once. |
| 12 ABORT_PRE_START | Empty | Empty | Restore protected originals/RNG and release only before START. |
| 13 RELEASE_SINGLES | `<II>` original party CRC, fixed-slot-0 outcome | Empty | Release only after native field return and exact restoration checks. |

Native phase rejects diagnostic EMIT, external receive CLEAR and ordinary CLOSE. All error replies have zero data. Status numbers remain 0 OK, 1 BUSY, 2 UNSAFE, 3 MALFORMED, 4 SESSION, 5 ORDER, 6 CRC, 7 ROLE, 8 KIND, 9 TIMEOUT, 10 INTERNAL.

States are 0 UNBOUND, 1 IDLE, 2 CHANNEL, 3 EXPIRED, 4 PREPARED, 5 RUNNING, 6 RETURNING, 7 FIELD_READY_HELD, 8 RECOVERY_REQUIRED. States 2–8 remain active holds. Query stays `<I16sBBBB10I>` (64 bytes): flags, generation, count/local/phase/reserved, last command sequence, outbound sequence/kind/size/CRC/read offset, received mask, remaining frames, acknowledged checkpoint revision and fixed-side outcome. Flags are 1 held, 2 expired, 4 outbound pending, 8 prepared, 16 started, 32 restored, 64 recovery required. The final two fields remain zero for phase1.

## Typed blocks and startup ordering

The receive ceiling is 256 bytes. Read/write chunks are 128 bytes, with the final chunk shortened. No truncation is allowed. Each sender has a monotonically increasing block sequence and one bounded ROM receive row. A late exact retry of an already consumed block stays consumed and cannot re-create a controller callback. Startup kinds must occur in the following order:

1. Kind 2 TRAINER: native LinkPlayer, 28 bytes. Emerald version, fixed source ID and link battle type, canonical name/gender/language; unused/progress fields zero. This is emitted at PREPARE and exchanged before START.
2. Kind 3 START_HEADER: native LinkBattlerHeader, 32 bytes, Emerald signature, bounded party summary and Enigma Berry fields. Native startup owns consumption.
3. Kinds 4–6 PARTY_0/1/2: two original Pokémon per block, 200 bytes each. The bytes come from the protected ordinary six-slot party backup, rather than the local temporary battle-form roster. The server must compare all 600 bytes to the exact prepared canonical checkpoint before routing. C independently checks checksums, species/item/move/level/HP bounds and nonzero occupied ownership serials.
4. Kind 7 RNG: 16-byte SFC32 state, exactly matching the issued PREPARE state. Installation occurs once at the native startup barrier after incidental setup randomness.
5. Kind 8 CONTROLLER: an allowed native controller frame. Complete emitted frames are at most 156 bytes under the enabled schema.

After all three opponent party blocks arrive, the normal native form-change helper applies beginning-of-battle forms only to the temporary opponent roster and recalculates its count. Every participant's original party stays individually owned. There is no shared wallet, inventory or party.

## Controller dispatch constraints

`include/multiplayer_battle_schema.h` is the numeric raw-length table shared by the C validator and intended Python mirror. `src/multiplayer_battle_controller.c` validates the 8-byte native header, padded length, zero padding, source role, request/reply state and semantic array/string bounds before any native controller sees a block. Compiler-derived sizes/offsets use ARM7 Thumb/APCS GNU with `MODERN=1`; host struct layout is not evidence.

TO_CONTROLLER is accepted only from slot 0. TO_ENGINE choices/data are accepted only from the trainer owning that battler. Both participant ROMs send controller DONE for their rendered copy; only one DONE per participant is accepted. GET_MON_DATA, action, move and party requests require the owner's reply before its DONE. A request remains pending until both renderer DONE records arrive. Transport delivery alone does not complete the native controller.

GET ALL permits the active mon or one selected party slot, preventing the native 256-byte scratch buffer from collecting multiple 140-byte mons. Only the audited SetMonData field list is enabled. Raw-mon getters/setters, DMA destination transfers, debug handlers, arbitrary memory copies, variable recording data and unused opaque commands are rejected. Message validation checks full string IDs against the actual ROM table, bounded placeholders/expansion, move/species/item/ability/type IDs and battler/party indexes. Unsupported locally emitted commands enter recovery hold. Invalid incoming data is refused before dispatch; failure to make healthy progress then expires into recovery hold.

The virtual packing path also initializes native padding and blank text buffers. A fresh action prompt permits native `B_ACTION_NONE` (255), with the unused item argument zeroed; this sentinel is refused as an owner's chosen action reply. Reply/DONE headers zero auxiliary globals their handlers do not consume. An out-of-range effect index from an internal native loop is zeroed only for the known empty-string print and audited action/move/party selection UI; meaningful print and animation metadata retain strict battler bounds. Its DONE encoder copies the one actual player-ID byte; the legacy caller passes a one-byte stack object with size four. Nonowner mirrored data replies are suppressed while their normal render completion remains required. Native send/receive rings remain 4096 bytes each and have explicit capacity checks in the virtual path.

## Save, RNG and result return

Save, ownership mutations and trade stay excluded throughout binding, preparation, battle, return and result hold. Only deliberate read-only ownership/save diagnostics remain available. Callbacks and playtime are frozen before START and in result/recovery holds. During RUNNING and RETURNING, native callbacks/display/input and playtime advance; hardware cable/RFU callbacks remain suppressed. The dedicated battle state is installed once and the participant's primary and secondary personal RNG states are restored once after normal field readiness. Replays cannot reseed or start a second battle.

The result is normalized to slot 0's native win/loss/draw projection. This prototype does not create automatic forfeits, wagers, rewards or a disconnect winner. It suppresses network-only battle recording, TV and Cable Club save prompts. Legacy recordings remain unchanged. Before field return, C waits for drained controller execution/transport and checks the local outcome projection. It restores all six original raw Pokémon and the original count with a dedicated exact native restore helper; the legacy restore helper's HP normalization is retained for legacy callers.

Resource destruction is deferred until the current native controller loop finishes. Normal battle resource cleanup and `CB2_ReturnToField` rebuild the current field; no old Flash image is loaded to roll back world progress. At field readiness C verifies the original party bytes/count again, restores personal RNG and previous callback/flags, and enters FIELD_READY_HELD. RELEASE requires the verified original CRC and fixed-side outcome. PC/daycare/fusion, save counters, UID/OT/PID, money and unrelated progression are not rewritten by this path.

A 600-engine-frame idle deadline requires healthy progress/KEEP. Before start expiry remains held but explicit pre-start ABORT may restore and release. After start expiry or a validation failure enters RECOVERY_REQUIRED and never automatically resumes, declares a result or accepts ordinary BIND/CANCEL/CLOSE as an escape. New-lease QUERY is observational; new-lease mutation/release is refused.

Cold frontend reset still loses the volatile battle hold. A durable battle journal plus paused cold-start resolution is required before shipping this as playable interruption recovery. The existing trade recovery barrier does not establish a battle journal. A close-game canonical recovery in a controlled proof must be labelled separately from graceful native interrupted-battle recovery.

## Recorded controlled proof and remaining acceptance

All 51 focused C tests passed on the frozen source: ownership, trade, diagnostic channel, save windows/CRC and native lifecycle/controller boundaries. They include rejected-command ACK preservation, native fresh-turn sentinels, partial-party validation, owner reply/DONE barriers, unsupported commands, timeout holds, unused header normalization and complete field-ready restoration. The exact-source unfiltered engine regression also completed with exit 0: 5,465 passed, 18 known failing, 421 to do and 9 expected failing, totaling 5,913. There were no unexpected failures. The established known categories remain unchanged; the 22 additional passes cover native singles and the separately qualified save-window/CRC additions.

Private `native-singles-run-4` passed five recorded checks, routing 362 blocks between two actual mGBA cores through authenticated companions and a session-local BattleDesk plus explicit development router. Ordinary joypad input selected moves and the replacement Pokémon. The issued RNG state entered through PREPARE; bridge writes stayed within the dedicated mailbox, while direct core-memory/Flash reads were diagnostic. Both cores agreed on fixed-slot-0 outcome 2, returned to their individual current maps, restored their original 600-byte parties/counts and both personal RNG states, and preserved Flash and native save counters through the battle. Ordinary checkpoint revision 2 and closed-game canonical reconciliation followed, then fresh Continue verified the same party bytes. All four initial/fresh core processes closed; the original source saves remained unchanged. Native playtime advanced normally.

The actual occupied parties were two Pokémon against one. Routing/restoration covers all six original raw slots, including empty tails; six occupied Pokémon per trainer and additional move/ability/gimmick combinations have not been exercised by this run. Early failed runs are retained: the first exposed an action sentinel/unused item argument, the second exposed an unused effect loop index, and a third completed the native battle/checkpoints but caught a proof helper waiting for bridge closure without reauthentication. The final run uses the corrected source and helper.

Frozen fingerprints:

| Artifact | SHA-256 |
| --- | --- |
| Normal ROM | `195299be89b79bd2d3dbe178860c16895054c520fceb650a0a69ea28c071cdf4` |
| Normal ELF | `31af065713516874f6e88054b690ac6f1e9096d552cd8c9743076b899e55f9e1` |
| Build manifest | `2845125ee61b230b06a45e78b0e89b7b5f6532055162bf68fc0cb7f4f0a9286c` |
| Final proof evidence | `9fb4ba9810462b890cc61c9e249554de65612703ae7fc13b25b99867759a5779` |
| Final proof script | `48b6cbae4ca5871f906c3148b7307ae3b78aababb5977985b2db0f0044752bb7` |
| Exact proof bridge | `71e766d56da5ea49682a99b586248a9b95b190e3949c6e68868a264dbc69e208` |
| Focused C log | `8fb7ae9f1ba1aedf1cc742a92de6de30bf21fcaa7cd211096fe00ea0514c13a7` |
| Full unfiltered C log | `a686d47e304513db18b6d45cc50fec9fae2309c65f06f67ac27bb6e6cc64509b` |
| Combined source-only delta from ABI1 `8c83917` | `49c424b0e7705d00872e09d355e0174bd1f192bfce0c3cd50ca43e19866b6316` |

The subsequent `native-singles-observers-3` repeat passed with four actual cores on this same source: two completed the native battle while C and D moved, D used its menu, and C checkpointed. All four then saved and loaded fresh Continue; eight original/fresh cores closed and all source saves remained unchanged. The [four-core proof record](native-singles-proof.md#four-core-independence-repeat) pins the independent evidence/controller and 128 individually verified private files. Live malformed/stale/timeout/interrupt tests and broader native command coverage remain separate from these normal battle passes. Controlled closed-game canonical reconciliation does not prove graceful interrupted-battle recovery or settlement of a durable battle journal.

Full-six four-human Multi, Windows graphical acceptance, LAN/Internet loss/latency, production battle admission/authority, durable interruption handling, content/Gen6 configuration and final policies remain separate gates. This document records a bounded native integration, not completion of those requirements.
