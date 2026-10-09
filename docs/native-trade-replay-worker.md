# Isolated native trade replay worker

The host must independently reproduce both recipient candidates before atomic
publication. `trade_native_replay.py` selects the application-pinned
`emerald-trade-replay.exe` and exact installed ROM/manifest. Participants cannot
select an executable, entry address, engine, save file or callback. Native work
runs off the owning event loop; SQLite remains on it. Complete output is compared
with the independently derived save changes and each recipient's retained
receipt. Closing/cancellation drains the owned subprocess before releasing the
worker slot. Native deadlines are refusal bounds, not performance claims.

The project-owned C frontend links the existing unmodified mGBA 0.10.5 pin
`26b7884bc25a5933960f3cdcd98bac1ae14d42e2`. It reuses the existing qualified
MinGW/cache configuration and public core APIs, rather than adding an SDL mode
or a general scripting/remote-memory service. The pinned `src/gba/core.c`
`_GBACoreWriteRegister` switches CPSR mode and refills PC prefetch;
`include/mgba/internal/arm/isa-inlines.h` `ThumbWritePC` retains `target + 2`.
These source semantics determine the worker's isolated Thumb call and return
sentinel. The existing Linux headless controllers supplied the core ownership,
audio-buffer and cleanup pattern; no new external implementation was copied.

Each process accepts `ROM DESCRIPTOR_HEX` and one binary stdin envelope. Windows
uses `wmain` and bounded UTF-8 conversion for mGBA's Windows VFS. The worker loads
no player save, Lua, user settings, patch, cheat or network service. It starts an
unbooted core, clears its RAM, disables interrupts, validates the ROM descriptor,
and places separate immutable input/output/sentinel buffers inside its declared
heap. ROM-side guards additionally require all live save-block pointers to be
null. A 64-million-instruction bound and the host's wall-clock subprocess bound
stop a nonreturning call; only an exact complete return can earn output.

The 32-byte descriptor contains little-endian words: magic `ETRW`, ABI1, Thumb
function pointer, `gHeap`, heap size `0x1C500`, input maximum 35116, output maximum
19452, and zero reserved. The input envelope is `ETRQ`, payload length, payload;
the payload begins with eight words: ABI1, operation, resolved friendship,
choice count, outgoing slot, incoming slot and two zeros. Operation 1 carries
received/sent 100-byte records; operation 2 carries recipient SaveBlock1 (15568),
recipient SaveBlock2 (3884) and partner SaveBlock1 (15568). Up to 16 explicit
`u16 move, u8 slot, u8 zero` choices follow. No live input pointer crosses the
process boundary. The output is `ETRS`, status, length and exactly 100 or 19452
bytes on success. Refusal has no candidate bytes. Fatal library logging is
bounded to one generic line and aborts replay without disclosing save contents.

`build_runtime.sh` builds the new console executable separately. `collect_bundle.py`
requires exact compiled worker source, checks its DLL imports, records source
and object hashes, and retains both in the existing relink archive. The fixed
worker joins the bounded runtime manifest without adding untracked neighboring
files. The original source archive derivative, notices, static libraries and
frontend objects remain; `relink-command.txt` includes the separate worker link
with `-municode`. The dependency ledger records inherited component terms.

Normal `build_launcher.py` packaging requires the validated ROM replay descriptor
and fixed worker plus the production reset descriptor and a reconstructing BPS.
`--development-preview` remains explicit. A manifest or successful collection
does not establish that replay works. This document records the source contract;
isolated compilation, exact native replay cases, real public trade flow and
performance evidence must be recorded separately. Accepted earlier bundles and
package 7 are unchanged.

## October 9 isolated Windows evidence

Testing resumed by explicit user instruction. The worker compiled with the
existing x64 POSIX MinGW 13.2.0 against the unchanged pinned core/cache. The first
link exposed required Windows `ole32`/`uuid` references; the build and retained
relink recipes now include them. Failed logs are preserved. Candidate 3 is
PE x86-64 and imports only Windows system DLLs plus the existing Winpthreads DLL.
Its executable SHA-256 is
`1874676fdb1cbb4a4dd2afca64a7e3197d8f18f1afd9bb9216ae68a5a9dcb4e6`;
compiled worker source is
`2c566a65929446f19ef30d61c0d9da04f7aa3eeb5543e1ab05d31c694b397ed6`.

The private `windows-trade-replay-worker-20261009-3/worker-check.json` records
eight successful loader/ABI assertions: version, genuine Thumb call/output/return
with a Unicode path, immutable-input refusal, even entry refusal, out-of-range
heap refusal, reserved-word refusal, partial input refusal and wrong output-size
refusal. Evidence SHA-256:
`1f114fab2e2ddfa34f699670020cad8afa59554550139146bb8bb89103a391b4`.
Invented 4 KiB fixture images were initially classified as multiboot by mGBA;
the corrected 512 KiB fixtures contain no commercial game data. This is an ABI
proof, not Pokémon gameplay.

The subsequent `windows-trade-replay-native-20261009-5/evidence.json` passed using
the real freshly built effects ROM
`344aca56bbdc5f98b47ed3def6fe320c5ea03046d9694af0bcedb95f50318c3f`,
its exact ELF/manifest, the real production Python adapter/backend and disposable
synthetic canonical save fixtures. Native record and complete paired save-block
results matched an independent non-evolution fixture expectation; the backend
performed a second real replay before paired atomic publication and integrity
validation. A separate actual ROM call evolved synthetic Machoke into Machamp,
preserving instance/OT identity and two HP of damage. Reopening the disposable
database retained the mutation fence until real historical native replay passed.
Evidence SHA-256:
`7a38c6276c59ab3f6bac06a7316a7b3ac4418b421faf4aaa8c8bd944aa792457`.
One paired call took 0.831 seconds on this machine/fixture; this is not a gameplay
latency guarantee. Original ROM/ELF/manifest and library inputs remained exact.

Earlier failed runs remain separately recorded: incompatible fixture build pin,
an inconsistent artificial level/experience pair, an overly strict test assertion
on evolution's derived `hpLost`, and the harness assuming an optional fence
attribute already existed. They are not retroactively marked passed. No live
player core, original save, visible trade/evolution scene, physical controls or
multiplayer network session participated. The private proof runtime mixes the
previous qualified SDL/bridge with the new worker solely for adapter pin checks;
it is not a new player runtime or release package.

## Packaged worker with the final visual ROM

The fresh private `artifacts/windows-trade-replay-packaged-20261009-1`
repeat passed using the complete collected `runtime-2` bundle intended for
packages 8/9, rather than the earlier mixed proof runtime. Exact pins:

| Input | SHA-256 |
| --- | --- |
| Windows worker | `43de0d1668a41c7e6c5aa6de2b43ba0228d3d719c5d528a62c3d2df9a0e6a14b` |
| Full runtime manifest | `698dff484ded620615d4002c0758bf14379cdb01cf25750d69499dc1cc6a5a84` |
| Final visual ROM | `f99bfa4e19ccb5ba998b54d2151986665c15bed3b2d28dab10340d59be3a1d65` |
| Game manifest | `f97dffa70c4edf93de4f90202f8fe08a5a3a499cb2113574c73881321b4bb7e1` |
| Evidence | `6c842bf59f4b48c5aecfb66d4771264068dad7fa754b2f68f2fe69f2f074a4e0` |

The unchanged substantive assertions reproduce both full recipient saves against
the independent non-evolution fixture, publish through the real host backend,
check SQLite integrity, evolve synthetic Machoke into Machamp while retaining
identity/OT and damage, and reopen the disposable database with mutations fenced
until real native historical replay succeeds. The existing production adapter
launched the copied worker; no live player game, save, controls or scene was used.
The complete fixture ran at BelowNormal priority under a 180-second outer async
bound; each native subprocess retained its existing production deadline.
The paired replay sample was 1.918 seconds, not a gameplay latency guarantee.

All 269 indexed original/copied source, fixture, runtime and ROM inputs remained
unchanged. The index SHA-256 is
`bff0e08fc6075e90bcbbe7ccc834738557089fad150a7e50b127d51508903554`;
the new harness is
`b7e35abbd95aa956fb3073b3f4c2eaf45eb5ecf6a697d08735cd42c215e1592f`.
The prior passing harness was preserved verbatim and separately indexed. The
new harness changes only isolated paths/full-bundle selection, input inventory,
the outer bound and preservation assertions; its old unused ELF file is not
required by the production ROM/manifest adapter. The run exited successfully,
its disposable fixture closed normally, and no worker from this output directory
remained. Independent source review found no harness scope or lifecycle blocker.

This closes the new-worker/final-ROM computation integration gap. It does not
qualify the frozen launcher executable, live public trade menus, evolution/move
choice presentation, interrupted gameplay or separate-PC networking. Those
remain distinct proofs with their own exact inputs.
