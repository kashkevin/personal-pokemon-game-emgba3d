# Held native trade record transport

October 9 source implementation only. No tests, builds, project imports, emulator,
game or UI runs were performed. This connects the existing private native record
helper to the retained live trade through a separately advertised capability.
It does **not** complete player-facing trade evolution or effectful publication.

The subsequent [full-save transport](native-trade-save-transport.md) extends this
record-only snapshot with optional candidate windows and durable full-container
validation. Its source hashes and new capability are recorded separately below
that document; the original patch/hash table here remains historical evidence.

## Connected implementation

`LiveTradeCoordinator.native_effect_preparation(history, refresh_handler=...,
profile_game_version=..., engine_source_sha256=...)` creates a
`HeldTradeEffectClient` in `src/emerald_multiplayer/trade_effect_session.py`.
Its asynchronous `begin()`/`resume()`, `choose(move, slot)` and `discard()` use the
actual companion/native save mailbox. Slots 0–3 replace that move; 4 explicitly
declines learning. `PreparedRecord` returns the native candidate, pending move,
state and exact choice transcript. There is no automatic move choice.

Before computation the client requires the original completed frozen trade
export, unchanged native CRC and retained SHA-256, exact world/recipient/source
ownership and outgoing serial, same game/companion incarnation, current lease,
and the host's existing uncommitted `recipient_preparation` descriptor. Incoming
bytes and both offered identities come from that authenticated descriptor;
the original local fingerprint consent must still match. Source bytes are read
from the coordinator's retained export, never from a peer-supplied whole save.

Complete typed incoming `FriendshipHistory` and explicit handler-refresh/origin
adaptation inputs are mandatory. The pinned Gen 6 base table supplies friendship;
unknown legacy opposite-handler history is refused. These inputs are trusted
application inputs, **not newly authenticated host history**. The supplied engine
source digest is retained provenance, while the verified ROM build/capability
binds actual execution. A future publication service must independently establish
history/policy authority and replay the result; this client cannot do that.

The generation-scoped `.native-record.json` retains the exact descriptor, consent
binding, incoming/sent records, source/engine/table/history inputs, resulting
history, commands and move transcript. An explicit decision and command reach
disk before dispatch. Responses must retain immutable Pokémon identity/protected
fields and the resolved friendship/item bounds. Those masks supplement native
computation; they are not a server's acceptance of arbitrary allowed fields.

The dedicated `Companion.trade_effect_rpc` requires the exact typed client,
current save-lock task, unchanged original trade intent and durably retained
command. Ordinary `save_rpc` rejects all four new operations. No method here can
import, acknowledge a candidate, release a hold, commit a trade or edit a save.

## Optional ABI

The existing 512-byte save mailbox and its 240-byte control are unchanged.
`gMultiplayerTradeEffectPrepareAbiVersion = 1` advertises only private record
preparation. Manifest fields are `trade_effect_prepare_abi_version` and
`trade_effect_prepare_abi_address`; generation requires explicit
`--trade-effect-prepare`. Absence defaults to disabled. Validators require the
ownership profile, save ABI 1, trade ABI 1 and menu ABI 2; the ROM marker and
build hash are verified. Existing manifests are not rewritten or auto-enabled.

The bridge advertises `K` plus little-endian `u16(1), u16(192)`. Commands still
use `C` and responses `R`. The bridge and companion independently gate this
capability. Raising the maximum save opcode does not enable absent emergency
or export-window capabilities.

Every command uses the held transaction UUID, original prepared revision,
exact native incarnation/current lease, ordinary monotonic save-command sequence,
Flash size 131072 and offset zero. Native processing requires `TRADE_HELD`,
unexpired original export, full exported stream, no import/emergency/battle.

| Opcode | Input bytes | Successful output |
| --- | --- | --- |
| 23 `BEGIN_EFFECT_RECORD` | 192: generation UUID16, pair-preparation SHA32, source SHA32, outgoing slot u32, friendship u32, incoming Pokémon100, original full-Flash CRC u32 | Native record state192 |
| 24 `CHOOSE_EFFECT_MOVE` | 56: generation16, pair SHA32, choice index u32, move u16, slot u8, reserved zero u8 | Native record state192 |
| 25 `QUERY_EFFECT_RECORD` | 48: generation16, pair SHA32 | Native record state192 |
| 26 `DISCARD_EFFECT_RECORD` | Same48 | Empty acknowledgement; field remains held |

All fields use little endian except UUID bytes and raw digests. Nonzero
generation/digests, bounds and padding are validated. Source SHA is retained
context, not computed by the ROM; the client checks the actual retained SHA and
native full-export CRC before sending. CRC alone grants no ownership authority.

The native response is the existing 192-byte
`MultiplayerTradeRecordPreparation`: version/serials, received/evolved species,
items before/after, pending move/learnset cursor, state/friendship/count/reserved,
candidate100 and sixteen four-byte choices. States 1/2 mean waiting for a move
decision/ready. The codec rejects nonzero unused choices and mismatched outputs.

Native scratch adds a 192-byte state, 192-byte immutable BEGIN input and one
active byte (up to 388 bytes including alignment). The ROM calls
`MultiplayerTradeEffects_BeginRecord`/`ChooseMove` on copies; live party, save
blocks, Flash, RNG and hold ownership remain unchanged. The ordinary import and
publication path is untouched. Source static assertions bind response size.

## Retry and cancellation boundaries

An identical BEGIN returns the current private state, including pending choices;
it never restarts evolution. Different inputs while active refuse. The client
uses that response to reconcile zero or one pending durable choice, checking
the exact native transcript before sending the next command. Renewed leases
first use the existing exact trade REBIND; native preparation survives that
same-core handoff. A replaced companion/core remains refused by the original
trade intent. Queries do not grant recovery of replaced cores.

Discard is durably staged. The native input/context remains until ordinary
trade release, allowing an identical discard retry after a lost receipt or
REBIND. A discarded local preparation cannot silently restart. Discard never
aborts the trade or resumes play. Trade expiry, host loss and any validation
failure keep the original hold and evidence; ordinary coordinator recovery
still owns canonical fate. No timeout becomes consent or publication.

## Preserved sources and exact delta

Editable engine: `/home/kevin/src/pokemon/engine-admission-cleanup-20261008-1`,
base `aef47e4b28fd6d0e84376961e0cc6632996bb0be` **plus existing uncommitted
patches**, including record preparation and save-wide effects. Bare base does
not reproduce this source. Reuse/attribution remains the existing
[native effect audit](native-trade-effects.md); no external dependency was added.

The additive [transport patch](../engine-patches/phase3-held-trade-record-transport.patch)
changes only `include/multiplayer_save.h` and `src/multiplayer_save.c`; it applies
after the preserved save/admission changes and depends on the
[private record helper](native-trade-record-preparation.md). All previous patches
and frozen builds remain intact. Before-source copies are retained at
`/home/kevin/src/pokemon/trade-record-transport-source-before-20261009-1` and
`C:\Users\kashh\AppData\Local\PokemonPrivate\trade-record-transport-source-before-20261009-1`.
The Windows backup also contains preceding application/bridge/codegen files.

| Source | SHA-256 |
| --- | --- |
| Transport patch | `176006a7aa8b26a5ab7e8a3a1d42b9833fcc1a3ec0347d94ec48d73bb67474b9` |
| Native save C | `73afbad4e98a9ea96b46ab45e0fdc4d1903a7ac3aab410db310e2e0e1af44a9a` |
| Native save header | `e88c9b0bed6b88554e859fd938d9f76484d43a41b91cad7ab559298d92fc1227` |
| `trade_effect_mailbox.py` | `c9e6ba7bbb50edbaf8cdaaacd62a0226498d236fa3e4ef8caec6d3aad4a3f27c` |
| `trade_effect_session.py` | `e7f3b17f732b5bdb5c18bfe48903e068ba0c817318374e72e72cd5f1fde990ae` |

## Remaining work and evidence limits

Ordinary `simple-owned-party-exchange-v1` eligibility and atomic exact-swap
validation remain in force. The current host descriptor therefore cannot offer
otherwise excluded trade-evolving Pokémon through this client. Eligible
ordinary records can use the internal callable path; there is no player-facing
effect menu or automatic invocation. Native record logic supports evolution,
but public effectful offers require a distinct complete publication capability.

Still required: transport for full saved-block replay/candidate validation;
native evolution/move-choice presentation; independently authoritative handler
history and unresolved geographic/legacy policy; both recipients' exact
prepared save/history consent and atomic durable publication; effect recovery
and actual-core qualification. The existing
[save-wide helper](native-trade-save-effects.md) is not connected to this mailbox
yet. Mail, eggs and Lucky rules remain gated independently.

Independent source reviews found no concrete blocker in source/consent
binding, typed authority, durable choice/discard reconciliation, native hold
guards, binary layouts or optional bridge/manifest gates. This is not
execution evidence. Future checks must cover old-build refusal, malformed ABI,
native immutable state/RNG/Flash, every interruption boundary, exact choice
replay, changed input refusal and eventual paired publication. No historical
test or build is claimed to cover this new transport.
