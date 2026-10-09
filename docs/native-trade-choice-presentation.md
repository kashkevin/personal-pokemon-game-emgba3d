# Held native trade-effect presentation

October 9 source-only continuation of the [held full-save transport](native-trade-save-transport.md).
No tests, builds, application imports, game/UI runs, installs, commits or private
save/world mutations were performed. This is an internal callable presentation
path. The ordinary `NativeTradeMenu.run` still performs only the established
exact swap and does **not** call it. Public trade evolution is not delivered by
this change.

## Reused native behavior and connected path

The existing [trade reuse audit](native-trade-effects.md#reuse-audit) remains the
source decision. The pinned engine already provides `GetMove*`,
`CalculatePPWithBonus`, `CannotForgetMove`, private `ChooseMove`/record replay and
an ABI2 menu that can reopen while the original trade save remains held. This
batch adapts those exact components; it imports no new dependency or upstream
code. Engine base remains `aef47e4b28fd6d0e84376961e0cc6632996bb0be` plus preserved
uncommitted changes, including the preceding record/full-save patches.

`LiveTradeCoordinator.native_effect_preparation(...)` returns the existing gated
`HeldTradeEffectClient`. Its new `prepare_in_game(menu_session)` enters
`HeldTradeEffectMenu` inside the **original** native menu-owner task, after that
menu's previous dialog has acknowledged CLOSE. It requires the same companion,
bridge/incarnation and open authenticated session. It does not start a second
UI task, use a launcher side channel or take ownership away from the save/trade
lifecycle. Screen revisions start above both the player-menu revision and the
native last CLOSE revision, so reopening after a longer prior dialog cannot
regress the native generation.

The connected presentation supports:

- Review of the private received/evolved Pokémon, including the existing full
  summary pages for moves, saved stats, IVs, EVs, nature, item and origin.
- Selection of each current move, full-name paged move facts, current/maximum
  PP, native power/accuracy/type/category, and native cannot-forget status.
- Explicit replacement of an eligible slot or explicit decline of the pending
  evolution move. Protected slots remain inspectable but cannot be submitted.
- Complete-name decision review followed by a separate confirmation. The review
  Continue row is at index two or later; the two-row confirmation resets the
  pinned native cursor to **Back**. B never means decline or accept.
- Recorded decisions before native dispatch, same-core lost-reply reconciliation,
  and continued presentation for subsequent evolution moves.
- Explicit READY-record review before preparing and retaining the complete
  private Flash candidate. Builds without the full-save capability show it as
  unavailable instead of offering an action that cannot run.
- Explicit pause: close only this native dialog and return `state="paused"`.
  The original trade hold remains unresolved. The caller must resume or use the
  existing authoritative ordinary fate/abort path; pause never releases play.

`state="prepared"` means only that the full private candidate passed the
existing independent 131072-byte comparison. Neither result is a trade receipt,
ownership change, saved checkpoint, visual evolution animation or permission to
import/publish. The existing link evolution scene mutates global parties,
callbacks and save fields; it is deliberately not invoked on this private path.

## Native read-only choice view

`MultiplayerTradeEffects_DescribeRecord` reads a copy of the private candidate,
uses the pinned native move table and returns `MultiplayerTradeChoiceView`.
It does not choose moves or change scratch state, live parties, save blocks,
Flash, RNG or callbacks. Four current slots and the pending move use the same
native cannot-forget check as the existing `ChooseMove` implementation.

Opcode 29 `QUERY_EFFECT_CHOICE` uses the original save-control envelope and the
same 48-byte generation UUID plus paired-preparation SHA context. It requires the
original complete export, current lease/incarnation, prepared revision, exact
trade request, active scratch and no import. Successful output is exactly 84 bytes:

| Offset | Meaning |
| --- | --- |
| 0..15 | Version 1, received serial, sent serial, CRC32 of the exact 192-byte record |
| 16..23 | Pending move, learnset cursor, state, choice count, replacement mask, zero |
| 24..83 | Five 12-byte move records: ID, PP, max PP, power, accuracy, type, category, cannot-forget flag, zero padding |

Static native size assertions protect the ABI. Cached successful replies also
require the same active, unexpired, unimported native hold and unchanged record
CRC. Record context and full native response are retained by the client; CRC is
correlation, not independent permission to trust a supplied candidate.

`NativeChoiceView.parse/match` validates bounded fields, empty slots, exact
replacement flags, pending state, serials, cursor, decision count and complete
record CRC, and compares current move IDs/PP against the decoded candidate.
Move names come from the already pinned source-derived display catalogue.
Native type labels describe the pinned enum; they enable no new mechanics.

## Durable explicit decisions

`choice_view()` returns a `ChoiceSnapshot` bound to the exact original session,
transaction, generation and full preparation context. The client retains that
specific object. Presented actions additionally require the actual current
authenticated native CHOOSE and original menu-owner task, rather than caller
supplied screen numbers alone. `choose_presented` consumes the snapshot before the first await, rechecks
the current host preparation and native record, then atomically journals both
the exact choice and displayed record/view/screen/request-sequence evidence
**before** native dispatch. Reconstructing a snapshot or replaying a stale screen
cannot supply authority. Normal `choose()` still supports existing explicit
non-UI callers; it records no invented presentation evidence.

Historical journal shapes remain readable. Their decisions gain only `None`
presentation entries when rewritten, preserving the distinction between known
choices and unknown old UI evidence. New evidence must match the offered
protected fields and the exact prior choice prefix. A lost response reuses the
existing one-unacknowledged-choice replay; it neither silently declines nor
starts a second evolution.

`prepare_presented` consumes the exact READY snapshot, retains a generation-scoped
immutable `.review.<lease>.<screen>.<request>.json` record and then calls the
existing full-save preparation. Its final record SHA must equal the reviewed
record. UI cleanup on error attempts only an acknowledged dialog close, leaving
native hold and durable uncertain decision evidence intact. A host restart or
lease replacement that removes the original uncommitted host preparation still
refuses this path; old consent is never resurrected from a screen file.
An already authenticated unsolicited CLOSE can retire only its obsolete dialog
queue; it grants no native trade release or renewed consent.

## Capability and publication boundaries

New marker `gMultiplayerTradeEffectChoiceAbiVersion=1` supplies optional manifest
fields `trade_effect_choice_abi_version/address`. Generation requires explicit
`--trade-effect-choice` with `--trade-effect-prepare`; defaults remain absent.
The verified ROM marker, record prerequisite and ABI2 menu must agree. Lua sends
the distinct `O` frame with little-endian u16 values 1 and 84 after record `K`.
Existing `J` native-menu messages remain unchanged.

Both Lua and Companion require the new capability for opcode 29. Raising the
maximum opcode does not enable missing full-save 27/28, ordinary-window 18 or
emergency 19..22 capabilities. Ordinary `save_rpc`, emergency authority and
public trade submission still cannot dispatch private effect commands.

Unresolved dependencies for this slice remain authoritative complete handler
history, integration of the owner's selected missing-handler policy and the
geographic refresh mapping;
native animation ownership; complete Gen6 rules qualification; both recipients'
effect/history consent; and atomic durable effect publication/recovery. No odds,
IVs, friendship thresholds, legacy values or geography rule were chosen by this
presentation implementation.

## Preserved artifacts and source evidence

Before-source copies:
`C:\Users\kashh\AppData\Local\PokemonPrivate\trade-choice-source-before-20261009-1`
and `/home/kevin/src/pokemon/trade-choice-source-before-20261009-1`.

The [additive native patch](../engine-patches/phase3-held-trade-choice-presentation.patch)
changes the two trade/save C/header pairs after the full-save transport patch.
Earlier patches/builds are retained; bare base revision does not reproduce it.

| Source | SHA-256 |
| --- | --- |
| Choice presentation patch | `d45c2bef64a18931fe3c5ecf5e3826961ddd8b253c2ade294cd8efbc11368b61` |
| Native save C | `8d709fc8ce78421131ff1c1cca1a5e010f09429f6c2e568dceae0b4342630945` |
| Native effects C | `3156fcb4ee6b0761780609b4ef5fcb3c4731884407eb2df7adef3d447b480ab0` |
| `trade_effect_session.py` | `bd59def7b363a6dc7b0b951743271167905016a6bf31a0c9d9e7be31788033bb` |
| `trade_effect_choice.py` | `b6fe94c6ce5d691b2c4a8380bea6680459f682a236866e008742bb06541286a2` |
| `trade_effect_menu.py` | `57f8652355f1f687fa21791a2d8ed68c1c9665dbf19034ea7a2d2bea369504dd` |

An independent source review found no concrete blocker in the native view,
opcode, duplicate lifetime, codec correlation and independent capability gates.
The requested second review of the client/menu was interrupted by reviewer
availability; source self-review is not recorded as an independent review.
Root subsequently read the held client/menu integration, including original-task
ownership, current native event binding, consume-before-await decisions,
confirmation cursor behavior, retained journal replay and private-candidate
review. No additional concrete blocker was identified by that source inspection.
The separate approved missing-handler policy now has an [implemented migration](trade-friendship-migration.md);
it has not been run and does not enable this path in the public trade menu.
No execution evidence exists for this batch. Future authorized checks must cover
native cursor/navigation, protected slots, multiple sequential moves, malformed
views, stale screens, lost replies and interrupted journal/close/write boundaries.
