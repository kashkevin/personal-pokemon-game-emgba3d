# Held full-save candidate transport

October 9 source implementation. This advances three connected capabilities:
bounded original peer metadata after mutual consent; native complete Flash
candidate readback; and durable client validation/retry. No tests, builds,
application imports, game/UI runs, installs, commits or private-world changes
were performed. This is not completed effectful trading or playable acceptance.

The subsequent [held native choice presentation](native-trade-choice-presentation.md)
connects explicit move review/decisions and READY-candidate review to the existing
held menu. Its optional source-only API still does not enable effect publication.

## Original peer source and compatibility

`TradeDesk.effect_source` reads only a current participant's mutually confirmed
preparation. Both original checkpoint heads, original leases, generation and
preparation digest must still match. It returns seven gift-ribbon description
bytes from the offered peer's original canonical checkpoint, bound to the
peer's ID, checkpoint request/revision/SHA, recipient, world and paired
preparation. It does not return a peer save, update consent, refresh a proposal
deadline, create a history value or acknowledge a candidate.

`trade_effect_source.py` defines the exact bounded `emerald-trade-effect-source-v1`
descriptor and its canonical context hash. Gift values outside the native
valid-description range remain source bytes; both implementations follow
native behavior and ignore those values rather than inventing replacements.

The companion probes `effect_source_version=1` on the already known
`trade_status` operation before sending `trade_effect_source`. An older host can
reject that optional field with a correlated error; it is not sent an unknown
operation during a speculative probe. The full-save client refuses without the
explicit success echo. Response identity/context is checked against the exact
previously authenticated preparation. `inspection_version=1` supplies the same
safe negotiation for the independent offer-details UI; `TradeDesk.inspect`
returns only the two current offered 100-byte records for the displayed complete
fingerprint, before consent, with both heads/current leases verified. Inspection
does not grant consent or use the effectful candidate path.

## Native complete candidate windows

This layer reuses the pinned native record helper and its READY state from
[held record preparation](native-trade-record-transport.md), the audited
[native save effects](native-trade-save-effects.md), and the existing 4096-byte
sector buffer/readback channel. The engine remains base
`aef47e4b28fd6d0e84376961e0cc6632996bb0be` plus preserved uncommitted patches.
No new external implementation or dependency was imported.

`MultiplayerTradeEffects_OverlaySaveSlice` changes a private slice only after
its original bytes exactly match the corresponding frozen recipient save block.
It requires a valid READY record, original sent/received serials, standard
species/National Dex agreement, bounded slots/slices and non-aliasing output.
All refusal checks precede output mutation. The function applies the same audited
operations as complete `ReplaySaveBlocks`: incoming/evolved seen and caught flags,
first-caught Unown/Spinda personality, encrypted saturated trade/evolution counts,
the ribbon presentation flag, missing valid gift descriptions and the prepared
Pokémon record. Repeated overlay always starts from the original slice, so it
does not accumulate counts. Existing full-block replay remains intact.

Two new operations use the original held save mailbox, transaction UUID,
prepared revision, incarnation/current bound lease and monotonic command cursor:

| Opcode | Command data | Successful response |
| --- | --- | --- |
| 27 `BEGIN_EFFECT_SAVE` | 88 bytes: generation UUID16, paired preparation SHA32, effect-source descriptor SHA32, original peer gifts7, reserved zero1; offset0 | Original save counter u32 and rotation u32 |
| 28 `READ_EFFECT_WINDOW` | 48 bytes: generation16, pair SHA32; offset aligned4096 in 0..126976 | CRC32 u32 plus the separately framed 4096-byte window |

Native BEGIN requires the original full export still held, no import, a READY
record, matching generation/pair and a valid original active Flash bank. It
pins all 88 source bytes and the original counter/rotation. Repeated identical
BEGIN returns that context; changed data refuses. No new save counter is created.

READ starts from the original physical Flash sector. Active-bank sectors must
match their original IDs, rotation, counter, signature and checksum. Only
logical sections 0–4 receive a private block overlay and regenerated native
checksum. The previous bank, ownership SaveBlock3/padding, PC and special sectors
are returned byte-for-byte. Source block comparison prevents silently building
from changed live recipient data. Neither Flash nor any live save block/party is
written. Original export offset/CRC remain unchanged. The scratch adds 88 source
bytes, two u32s and an active byte (up to 100 bytes including alignment), rather
than another pair of complete save blocks. Window storage is reused.

A duplicate READ receipt is valid only while the exact original hold is active,
unexpired, unimported and at its original counter/rotation, and the current
window's CRC still matches its cached receipt. Ordinary queries cannot authorize
reading a stale buffer. Discarding the record also discards full-save state;
ordinary Release/Init clear both. Neither discard nor failed read releases play.

## Explicit optional capability

New marker `gMultiplayerTradeEffectSaveAbiVersion = 1` is distinct from the
record marker. Manifest fields are `trade_effect_save_abi_version` and
`trade_effect_save_abi_address`. Both `--trade-effect-prepare` and
`--trade-effect-save` are required to generate it; defaults remain absent.
Validation requires the record capability, original window capability and their
prerequisites. Every ROM marker is checked against the verified ROM file.

The bridge announces `L` plus little-endian u16 values 1 and 4096 only after
record `K` and window `X`. Opcode28 uses the existing `F` frame containing the
correlated 240-byte response and 4096 bytes. The ordinary window decoder's default
still accepts only opcode18; opcode28 requires the separately verified flag.
Lua checks the native state is `TRADE_HELD`, offset, response generation and
window CRC before transmission. Companion checks capability, exact original
owner/task/intent/command, response fields, offset and framed bytes. Ordinary
`save_rpc`, normal `save_window_rpc` and emergency authority cannot call these
operations. New capability maxima do not enable absent emergency operations.

## Connected client and durable recovery

`HeldTradeEffectClient.prepare_save()` first reconciles the original record and
its explicit move decisions. If a choice is pending it refuses with
`effect_move_required`; it does not decline or choose a move automatically.
Existing `choose(move, slot)` and `resume()` retain their recorded-transcript
semantics. Full preparation then obtains the bound peer source, durably writes
the exact full-save context, sends BEGIN and verifies the original bank receipt.
It reads all 32 windows with per-window correlation/CRC and produces a
`HeldSaveCandidate` only after independent complete equality validation.

`trade_effect_candidate.validate_streamed_candidate` reconstructs the expected
recipient container from the original Flash and authenticated seven-byte peer
context. It checks source SHA/ownership, offered identity, protected Pokémon
fields, READY record and exact native bookkeeping, then compares **all 131072
bytes**. It reparses the result and requires unchanged world/player identity and
the exact reciprocal owned-serial replacement. The native record itself is
bound by the client's previous native response/history/choice transcript;
this validator alone is not authority to accept a network-supplied record.

After equality, the client retains generation-scoped immutable
`.native-record.save-context.json`, `.native-record.candidate.flash` and
`.native-record.candidate.json` artifacts beside the original trade intent.
They bind original record context/history, peer checkpoint/source hash, READY
record, candidate size/hash and exact commands. Every command is journaled before
dispatch. Candidate bytes reach disk before the completion evidence; replay
requires identical existing bytes. These files are private computation artifacts,
never imported or published canonical checkpoints.

`resume_save()` repeats preparation/readback from the same original inputs. A
lost BEGIN or window response therefore requires no rollback or probabilistic
recomputation. Partial read buffers are discarded; original bytes and pending
commands remain durable. A lost final local write retries immutable publication
of the same private candidate. Native scratch can survive same-core REBIND, but
the client still requires the host's exact uncommitted preparation. The current
TradeDesk drops uncommitted proposals on lease change/host restart: that case
**refuses new preparation** and must use existing authoritative ordinary trade
fate/abort recovery. Preserved scratch does not resurrect missing consent.
Replaced cores/companions remain refused. No timeout becomes a successful trade.

## Source artifacts and remaining gates

Before-source copies are retained in
`/home/kevin/src/pokemon/trade-save-transport-source-before-20261009-1` and
`C:\Users\kashh\AppData\Local\PokemonPrivate\trade-save-transport-source-before-20261009-1`.
The new [additive native patch](../engine-patches/phase3-held-trade-save-transport.patch)
changes the save/effect C/header files only and applies after the earlier record
transport patch and private save-effects helper. All prior patches and frozen
builds remain preserved. Bare base revision does not reproduce this dirty source.

| Source | SHA-256 |
| --- | --- |
| Full-save transport patch | `d45ecad065142ac020b5e77acac2a318d2d9df53982cd263d3737d89b7967356` |
| Native save C | `529ced75911ab7676b8f259ce2becf730e8b4132916f1125acf91d492c50cd97` |
| Native effects C | `d193eeea50c030ee2b60dc5055feb726efdaf41c07e4dfc2f740c1a3322cf499` |
| `trade_effect_session.py` | `ad75dd204c95168a342c8bc51498a43a8103d1c6a016b1e38b6b941d745be2a5` |
| `trade_effect_candidate.py` | `bf5f60bb1b307e6ac6252817e9451e5bd77a591dca6191ea4649fa7b689c6875` |
| `trade_effect_source.py` | `daa903d26cdc1331bb4a2e03fd804bf08f9b36147ec1f4e62531ed4cc7dcb90d` |
| `trade_effect_mailbox.py` | `ff185c59d0e6c771c09215a3d32920e2c1c5c32ac258657ed4d50b8d82e32fb8` |

Still required: authoritative durable handler history and a decision on legacy
opposite-handler/geographic adaptation, native evolution/move-choice presentation,
full Gen6 configuration qualification, both recipients' effect/history consent,
atomic durable publication and recovery of effectful outcomes. Existing
`simple-owned-party-exchange-v1` still rejects these modified candidates and
trade-evolving offers. The internal API is callable only within the existing
eligible trade context; this does not silently enable public evolution/egg/mail
or Lucky trades. Full-block replay/host publication authority is not inferred
from a client hash, local artifact or capability marker.

Two independent source reviews found no concrete blocker: one covered the host
source projection, client authority, immutable transcript and complete candidate
comparison; the other covered native overlays, BEGIN/window replay, capability
gates and Lua/codec correlation. Neither review executed project code or qualifies
runtime behavior.

Execution evidence remains UNKNOWN. Future authorized checks must cover original
bank/rotation permutations, checksum drift, windows/out-of-order retries, stale
buffer replay, expiry/rebind/import/lifecycle refusals, aliasing, Dex/PID/counter
saturation and encryption, both records in one Dex byte, ribbon range behavior,
whole-container tampering and interrupted disk writes. No test was run to answer
these questions during this implementation batch.
