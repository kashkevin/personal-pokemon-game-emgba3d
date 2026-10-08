# Development battle channel ABI 1

This first channel is a controlled native-block diagnostic, not a battle implementation. It accepts only the typed 40-byte diagnostic frame below. It never enters a battle, supplies a controller command, edits a party/save, changes a seed or chooses a winner. Native singles startup/controllers require a separate audited extension. Full-six four-human Multi remains required afterwards. The normal launcher must leave this development capability disabled.

Source is isolated in `/home/kevin/src/pokemon/engine-battle`, branch `codex/battle-channel`, from trade foundation `b2cdd466abb8b142c3b75384133b5e6b3c3b982c`. Existing presence/save profiles and their mailbox layouts remain unchanged. No external implementation or assets are imported. See [the architecture audit](battle-transport-design.md) for primary source pins and remaining battle work.

## Header and commit slots

The matching ELF exports `const u32 gMultiplayerBattleAbiVersion = 1` and `gMultiplayerBattleMailbox`, exactly 512 bytes in EWRAM. Derive its address and verify the ROM capability value/hash; never reuse an address from another build. Magic is `0x31424D45` (`EMB1`), ABI 1.

| Offset | Size | Meaning |
| --- | --- | --- |
| 0 | 4 | Magic |
| 4 | 2 | ABI version |
| 6 | 2 | Byte size 512 |
| 8 | 4 | Engine frame, advances in all scenes/holds |
| 12 | 4 | State: 0 UNBOUND, 1 IDLE after close, 2 CHANNEL held, 3 EXPIRED held |
| 16 | 8 | Reserved zero |
| 24 | 4 | Command generation, sole external commit word |
| 28 | 240 | Command slot, sole external payload region |
| 268 | 4 | Response generation, engine-owned |
| 272 | 240 | Response slot, engine-owned |

The bridge writes an odd command generation, the full zero-padded slot, then an even generation last. C consumes a stable new even generation. The first committed generation must differ from initialized zero. The response uses the same odd/write/even publication. External writes are confined to bytes 24-267. Each frame processes at most one command; no network/blocking wait runs in the ROM.

The little-endian control struct is `<II16sIIHHBBBBBBHI192s>`:

| Slot offset | Type | Field |
| --- | --- | --- |
| 0 | u32 | Local bridge incarnation, nonzero |
| 4 | u32 | Authenticated local lease/session epoch, 1..0x7FFFFFFF |
| 8 | 16 raw bytes | Nonzero battle UUID (`UUID.bytes`, not GBA little-endian UUID fields) |
| 24 | u32 | Command sequence, nonzero |
| 28 | u32 | Block sequence, zero for non-block commands |
| 32 | u16 | Block offset |
| 34 | u16 | Block total size, at most native 256-byte ceiling |
| 36 | u8 | Opcode |
| 37 | u8 | Status, commands require zero |
| 38 | u8 | Phase, currently only 1 DIAGNOSTIC |
| 39 | u8 | Source slot: local slot except RECEIVE's authenticated remote source |
| 40 | u8 | Kind: 0 NONE, 1 DIAGNOSTIC; other kinds refused |
| 41 | u8 | Reserved zero |
| 42 | u16 | Data length, at most 192 |
| 44 | u32 | Standard CRC32 of data[0:length], zero for empty data |
| 48 | 192 bytes | Data, unused tail must be zero |

Responses echo all correlation/header fields except status, length, CRC and data. READ_OUT echoes the requested offset, while the query reports the advanced read cursor. Errors have empty data and CRC zero. Statuses are 0 OK, 1 BUSY, 2 UNSAFE, 3 MALFORMED, 4 SESSION, 5 ORDER, 6 CRC, 7 ROLE, 8 KIND, 9 TIMEOUT, 10 INTERNAL.

The separate IPC packets are `D` + command240, `E` + response240, and capability `W` + little-endian `<HHHH>` (1, 512, 240, 192). All remain inside the existing 256-byte payload cap. Existing presence and save packet prefixes retain their behavior. The pure [Python codec](../src/emerald_multiplayer/battle_mailbox.py) chooses no memory address and rejects unsupported native kinds/phases.

## Binding and command sequence

BIND 1 carries exactly 116 bytes: generation UUID[16], player UUID[4][16], lease u32[4], incarnation u32[4], playerCount u8, localSlot u8, mode u8=1, reserved u8=0. Raw UUIDs are nonzero; players are unique; count is 2 or 4, local slot is in range. Unused slots and their counters are zero. Each active lease is 1..0x7FFFFFFF and incarnation is nonzero. The local player UUID must match the valid enrolled ownership record, and its lease/incarnation must match the command. Generation and battle UUID are separate fences. The current development caller constructs the roster using its authenticated companion sessions; WorldServer does not yet authorize a battle roster or route these diagnostic blocks. Server construction of a consented immutable roster is a future integration requirement. Local validation alone does not establish authority over remote slots.

The first/newer binding pair uses sequence 1. Pairs compare lexicographically by session epoch then incarnation; a lower pair is refused. Both mailboxes also retain each other's most recent binding fence, preventing an older save binding after diagnostic close or an older diagnostic binding after a save binding. A successful binding freezes at the existing safe field predicate, refuses an ordinary held save/trade, removes ephemeral presence objects, and disables ordinary callbacks, playtime, VBlank random advancement and classic soft reset. It does not reseed or serialize Flash. It accepts idle Center wireless scanning while refusing active cable/RFU/Union Room sessions. The public native link helpers use virtual IDs/counts during this hold.

Every ordinary command must match the bound battle UUID, incarnation, lease and phase and use the next global command sequence. A byte-identical last command is replayed with its cached reply and no side effect. Structurally invalid frames, bad CRC, stale sessions, sequence errors, refused BIND and QUERY preserve that cache/counter. Correctly ordered authenticated operation refusals consume their sequence. A later QUERY cannot destroy a lost successful acknowledgment. Reusing a closed battle UUID is refused; after close the same pair may bind a fresh UUID at the next sequence, or a strictly newer pair may bind at sequence 1. A higher binding cannot replace a held channel.

QUERY 2 is observational and does not consume sequence or refresh the watchdog. Before binding it reports empty state. Afterwards it requires the same battle UUID/local slot/incarnation and a lease at least as new as the held lease. It cannot rebind/release that old lease. A lost connection with a changed lease can inspect the hold, but this diagnostic slice requires close-game recovery if its original binding cannot be resumed; no persistent transaction marker or active battle is involved.

## Operations and flow control

All commands except RECEIVE use the local source slot. BIND/QUERY/EMIT_DIAGNOSTIC/KEEP return 64-byte query data. ACK_OUT/RECEIVE/CLEAR_RX/CLOSE return empty success. READ_OUT returns up to 128 bytes; the only supported diagnostic frame currently returns 40 bytes.

| Opcode | Request shape and behavior |
| --- | --- |
| 1 BIND | Data116 above; block sequence/offset/total/kind zero. Admits once at a safe enrolled field. |
| 2 QUERY | Empty data, block sequence/offset/total/kind zero. Observes without progression. |
| 3 EMIT_DIAGNOSTIC | Data4 token u32; block fields/kind zero. C constructs the typed frame and calls native SendBlock; one pending outbound block and one unconsumed local loopback are the maximum. |
| 4 READ_OUT | Empty data, exact outbound block sequence/kind1/size, offset equals current read cursor and is below size. Returns next bounded chunk at echoed offset; replay repeats that chunk. |
| 5 ACK_OUT | Data8 `<II>` full block CRC32 and exact delivered-peer mask. Block sequence/size/kind1 match pending output, offset=size; full output must have been read. Peer mask is all bound slots except local. Only then is native IsLinkTaskFinished true. |
| 6 RECEIVE | Data40 exact frame below; source is a bound remote slot, kind1, offset0, total40, block sequence nonzero. Per-source sequence begins1 and increments only on successful insertion. A pending received flag prevents overwrite. |
| 7 CLEAR_RX | Data4 nonzero mask restricted to bound slots; block fields/kind zero. Uses native ResetBlockReceivedFlag. Only consumption, not delivery, clears the native flags. |
| 8 CLOSE | Empty data/block fields/kind zero. Clears channel blocks/flags and resumes unchanged local callbacks/clocks/reset setting, including from EXPIRED. Diagnostic close has no result/reward/forfeit effect. |
| 9 KEEP | Empty data/block fields/kind zero. Refreshes the idle deadline while CHANNEL; cannot revive EXPIRED. |

QUERY data64 is `<I16sBBBBIIIIIIIIII>`: flags u32 (bit0 held, bit1 expired, bit2 outbound pending), generation UUID16, count/local/mode/reserved u8, last command sequence u32, outbound block sequence u32, outbound kind u32, size u32, CRC u32, read cursor u32, received mask u32, remaining idle frames u32, reserved u32[2]. Idle retains the previous binding for observation; unbound fields are zero. Native block buffers and the channel cache are bounded; no heap allocation or complete save copy is added.

The only native diagnostic frame is `<II16sIIII>` (40 bytes): magic `0x44424D45` (`EMBD`), version1, bound generation UUID16, source slot u32, token u32, source lease u32, source incarnation u32. Every field except the token must match the immutable binding supplied by the development coordinator. Arbitrary byte blocks, unsupported kinds/phases and controller payloads are rejected. SendBlock copies this validated frame into the existing native buffer and loopback receive slot; bridge READ_OUT never accepts an external source pointer. The development proof coordinator routes unchanged bytes between its bound authenticated companions and ACKs the exact delivery mask. Future server routing must independently authenticate the source and confine delivery to its approved roster. A consumed identical remote retry remains consumed; changed-content or skipped/old sequence is rejected.

After 600 idle engine frames, the state becomes EXPIRED and stays held. Successful non-query operations refresh the deadline; exact replay and failed/observational commands do not. No wall-clock timeout in the ROM can advance a paused emulator. QUERY and explicit CLOSE remain available. The companion/server must surface uncertainty; it must not interpret timeout as delivery, cancellation, acceptance or a battle outcome.

## Safety and acceptance limits

While held, native save mailbox mutators (including BIND/CANCEL and ownership operations) return BUSY; native party saving refuses before mutation. Read-only save QUERY/QUERY_TRADE remain subject to their original binding validation. Ownership mailbox queries are deliberately refused during this diagnostic hold. A held save/trade conversely refuses BIND before taking a second hold. Physical cable/RFU work and TryReceiveLinkBattleData are bypassed, so EMBD bytes never dispatch as battle-controller instructions.

This is not anti-cheat, Internet acceptance, native singles startup or four-human battle proof. Tests exercise the actual mailbox/native block seam, malformed/type/role/lease/replay/cursor/flow-control refusal, expiration, same-frame save/hold exclusions and unchanged personal RNG/party/ownership/save counters. Native battle entry stays disabled until separately audited controller allowlists, personal RNG restoration, original-party return, interruption recovery and full-six Multi adaptations are implemented.

## Frozen implementation checkpoint

Engine commit `8c839171e1070ba31d66e74aae35bb207fe39b4a` implements this diagnostic contract. The focused native `TESTS=Multiplayer` run passed 29/29 tests: eight channel tests, fifteen ownership tests and six trade-hold tests. After independent response-role/state review, the pure Python codec passed thirteen tests on Windows Python 3.14 and WSL Python 3.12, with no skips. The exact-source full unfiltered engine regression completed with exit zero: 5,443 passed, 18 known failing, 421 TODO, nine expected failing, 5,891 total. This adds the eight channel tests to the accepted trade baseline without a new failure. Its private final log SHA256 is `5370c854ef8c8bfc4d9e8ddff57e095f2334cca4cd731d4f188fbecd6e189920`.

The final normal build used two workers at nice 15. Link usage is EWRAM 231,016 bytes (+1,188 versus `b2cdd466`), IWRAM 28,376 bytes (unchanged) and ROM content 26,766,524 bytes (+4,524); the ROM file is padded to 33,554,432 bytes. There is no channel heap allocation. No emulator CPU/latency benchmark has been completed.

Matching ROM, ELF, map, manifest and final build/focused-test logs are preserved privately in `/home/kevin/src/pokemon/multiplayer-proof/battle-channel-build-8c83917`. Its ROM SHA256 is `f88158b4f0cd40a6e06ca17d453fdd64816de48f16755239ea1a6c200e2559ea`, ELF SHA256 `d93161b48c6609f395592ce6f98b0841fa8115e7c2268673aeb0b192ce6f4e6e`, and manifest SHA256 `9c54c297a35abffe9698da57d196f29e0b593a12ffadc2fde78af51abf7fe252`. The source-only `battle-channel.patch` in that directory covers the exact base-to-commit delta, SHA256 `63528928451caf6c529b36904a9404bdc6d7f8f4739b8eb399b9ef32597f519b`, and passes `git apply --check` against the clean preserved trade worktree at the base commit. Existing milestone worktrees remain unchanged.

Actual two-core `battle-channel-run-4` passed ten recorded checks on the same frozen ROM, exited zero and closed every core. It loaded independent original saves through ordinary Continue, explicitly enrolled each in a fresh owned world, exchanged native loopback and remote 40-byte frames in both directions, checked exact read replay/flow control and role/order/CRC refusals, refused ordinary save BIND during the hold, and verified that expiration/classic-reset input left RNG, playtime, parties, counters and the entire 128 KiB Flash unchanged. CLOSE restored normal movement and ordinary owned checkpoints. An authenticated lease change could QUERY the old hold but received SESSION on CLOSE; both games were then closed and the existing canonical startup gate installed current revision 2 under retained mirror leases before fresh ordinary Continue. The final evidence SHA256 is `1c4539144afc6abb505c29d59819922f671001fab1d0bfe972aa3cff9e89f3f2`, preserved privately with its exact controller and Lua source. This proves the local diagnostic and its documented close-game recovery boundary. Server battle-roster approval, native battle entry, battle results, remote Internet delivery and four-human Multi remain separate acceptance work.
