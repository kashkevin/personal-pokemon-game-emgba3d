# Players menu control and bridge

`PlayerMenu` supplies the native Players screen with connected players, two-person team invitations/acceptance/decline/cancel/leave, singles challenges, and challenges between two existing teams. All four Multi trainers must confirm individually. Choosing an action never declares a result or starts a native battle. The [challenge service](battle-challenge-network.md) keeps native execution and restoration with its separate trusted coordinator. Trade selection and native battle execution remain separate integration work.

Each immutable screen has a generation. An action refers to that exact screen and the captured authenticated world/server/player lease; stale screens and reconnects cannot imply consent. The controller consumes the displayed actions before awaiting a mutation. Unknown transport fate closes the local menu and requires an authoritative refresh, without automatically repeating an invitation or acceptance. Disabled server features produce no actionable controls. A live menu polls read-only status every two seconds for new invitations and consent changes.

The per-bridge `MenuSession` bounds outstanding choices to one, with at most one queued reopen. Closing and reopening discards late display replies while an already dispatched RPC drains. Shutdown owns a separate cleanup task and survives repeated caller cancellation until dispatched consent finishes. Replies cannot reach another bridge incarnation. The existing bounded reliable FIFO carries menu replies alongside saves, battles and presence; backpressure closes the bridge rather than growing a queue.

## Optional allocated ABI

The exact ROM marker and ELF allocation identify menu ABI 1. Older ROMs without this marker/configuration retain their existing behavior. The new volatile 512-byte EWRAM mailbox does not alter SaveBlocks, save formats, presence, save or battle packet ABIs.

| Offset | Owner | Content |
| --- | --- | --- |
| 0–15 | ROM | Magic `0x31554d45`, ABI/size, frame, local seqlock generation |
| 16–31 | ROM | Monotonic request sequence, displayed screen ID, selected action, OPEN/CHOOSE/CLOSE and zero reserved bytes |
| 32–35 | Bridge | Inbound seqlock generation |
| 36–275 | Bridge | Exact 240-byte display: request acknowledgment, screen generation, close flag, row count, back action, title/status and six bounded rows |
| 276–511 | ROM | Reserved zero bytes |

Requests have 16 bytes. A 240-byte screen holds title/status fields of 24/32 bytes, six rows of a two-byte action plus 26-byte label, and zero reserved padding. All text is printable, NUL-padded ASCII; native code maps it to font glyphs rather than interpreting external control sequences. Each row action is zero (disabled) or its own index 1–6. Back is zero (close) or seven. Lua and Python reject malformed padding, counts, text and field types, and manifest validation rejects overlap with any existing allocated channel. Lua writes only the dedicated inbound generation/display region. Stale acknowledgments never overwrite a new request's display.

The native shell uses the existing Start menu Player row, retaining a Trainer Card choice. Its own frame tick pauses ordinary callbacks and clocks while keeping bridge frames alive; save/battle admission excludes the open menu. Native close publishes a CLOSE request after releasing windows and field controls. First-version UI admission excludes native save/battle holds. This is required before adding in-game trade confirmation during a frozen export, and it must be qualified separately.

## Reuse and verification

The [existing pinned/upstream/community audit](customization-and-reuse.md) supplies the reuse decision: retain native menu/window/font primitives and the authenticated project services. No third-party UI library, network dependency, gameplay rule, probability or save-schema change was incorporated. Native code is developed against accepted combined source `afd92ce3a12204873e2f06a77a7bf1717d04f53b` plus the preview correction. Static mailbox space fits the measured EWRAM budget; frame/performance measurements and actual native menu acceptance are separate from these tests.

Python/Lua verification on October 8, 2026: 85 affected Windows tests passed in 16.293 seconds, followed by all six new session lifecycle cases in 0.142 seconds; all 91 passed together on WSL in 42.375 seconds, with no skips. They include real Lua with guarded memory/socket fixtures, ELF/ROM marker fixtures, four authenticated TCP companions and genuine SQLite ownership saves. Checks cover explicit team/challenge choices, exact generations, stale/repeated requests, independent consent, malformed writes, ROM/bridge restart, close/reopen with a pending choice, and repeated cleanup cancellation. Actual four-core menu/UI evidence is recorded separately when complete. This checkpoint alone does not qualify a player-ready release.
