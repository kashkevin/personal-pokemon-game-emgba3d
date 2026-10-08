# Measured live checkpoint cost

Replacing the private multiplayer CRC32 bit loop with an equivalent constant ROM table reduced a paced, complete window checkpoint from **9.298 seconds to 6.328 seconds** on this development machine. The read portion fell from **4.592 to 1.611 seconds**. The remaining pause is dominated by the native save performed at BEGIN_EXPORT. This is useful transport progress, but autosave remains disabled in the normal runtime and Windows gameplay performance remains unqualified.

## Exact change and engine checks

The isolated engine worktree `engine-save-window-fast`, branch `codex/save-window-fast`, started at `d0db4f2f4eb4c5a47292960ff161d1a7ecf0dad6`. Commit `54f977f59df03acad69973cde1bc3b37c5f3eea0` changes only `src/multiplayer_save.c`, its test-only declaration in `include/multiplayer_save.h`, and `test/multiplayer_save_crc.c`.

The 256-entry `const u32` table is generated from the existing reflected IEEE polynomial `0xEDB88320`. The initial/final xor, seeded incremental result, input lengths, mailbox ABI, complete-stream CRC and replay behavior are unchanged. No dependency or imported implementation is added. Normal ELF symbol `sCrc32Table` is read-only ROM at `0x086d5648`, size 1,024 bytes. The test wrapper is absent from the normal ELF. EWRAM remains 231,016 bytes and IWRAM 28,376 bytes. Linked ROM is 26,767,644 bytes, an increase of 944 bytes over d0db; the distributed padded ROM remains 32 MiB.

Normal compilation passed at `nice 15`, maximum two workers. All **37 focused Multiplayer native tests passed**, including the existing 34 and three new CRC cases. The new tests cover empty inputs with nonzero seeds; fixed ASCII and binary CRC vectors; every split of the 256-byte binary vector; bytewise incremental use; and four seeds across every input length from zero through 256 compared with the retained independent bitwise reference. This is focused engine coverage, not an unfiltered full-suite result for the optimized revision.

## Actual-core comparison

The original `save_window_proof.py` remains byte-for-byte preserved at SHA256 `dc6df9d0debbbb5faa2d259302b7b8ae638f8b517f7f7f932f3c6095d28cdd`. New `save_window_profile.py` wraps its production coordinator operations with monotonic timers. It requires the accepted quiet d0db 60-frame/s evidence before starting. The two builds run in separate fresh authenticated worlds with copies of the same immutable source characters; an existing database or character is never silently migrated to the new build.

Each proof uses two official libmGBA cores with the real Lua bridge. Its paced driver advances one frame at a time, without catch-up bursts. Boot/Continue is completed before pacing begins. These measurements describe this purpose-built headless driver at 60 frames/s, not the native Windows SDL frontend or a released game.

| Measurement | d0db bitwise CRC | 54f977f ROM table |
| --- | ---: | ---: |
| A enrollment | 9.683 s | 6.575 s |
| B enrollment | 9.693 s | 6.600 s |
| Complete window checkpoint | 9.298 s / 554 driver frames | 6.328 s / 377 driver frames |
| 32-window read | 4.592 s / 274 frames | 1.611 s / 96 frames |
| Legacy fallback checkpoint | 39.254 s | 41.987 s |
| 1,024 legacy reads | 34.549 s / 2,072 frames | 37.308 s / 2,237 frames |
| Complete live recovery | 47.768 s | 45.034 s |

The single paired runs show a clear improvement for large-window CRC processing. They do not establish a faster legacy round-trip path: that measured fallback was slower in the new run. Scheduling and IPC phase affect small sequential commands, and these are observations rather than a statistical benchmark. The earlier unthrottled headless results must not be interpreted as normal-speed pauses.

## Where the time remains

The successful A revision-2 checkpoint has this stage profile:

| Stage | Wall time | Driver frames |
| --- | ---: | ---: |
| BIND, already bound | under 0.001 s | 0 |
| Ownership preflight/grant check | 0.113 s | 6 |
| BEGIN_EXPORT | 4.482 s | 269 |
| READ, 32 aligned windows | 1.611 s | 96 |
| Durable upload | 0.056 s | 2 |
| END | 0.019 s | 2 |

The full instrumented attempt was 6.327471 seconds. The small remainder includes head checks, parsing, journaling, receipt handling and proof read-only diagnostics. Stage timers are nested where appropriate and must not be added across separate attempts.

BEGIN_EXPORT accounts for roughly 71% of that checkpoint. In the audited native source it includes stable-field/ownership admission and `HandleSavingData(SAVE_NORMAL)`, which performs the ordinary native Flash save before export starts. This profile does not separately instrument every native Flash subroutine, so the entire 4.482 seconds should be attributed to the save/export phase rather than claimed as a pure Flash-programming timer. Upload is local loopback in this proof; Internet latency is not measured.

Recovery remains expensive: its 1,024 WRITE_IMPORT commands took 41.699 seconds across 2,502 driver frames. BEGIN_IMPORT took 0.305 seconds, COMMIT_IMPORT 0.722, the 32-window readback 1.609, and END 0.586. CRC optimization does not change the bounded import write protocol.

## Acceptance and private evidence

The optimized quiet run passed **all 13 actual-core checks** and closed all four initial/fresh core processes. It independently compares every exported Flash byte to read-only core Flash diagnostics, preserves held native party/RNG/playtime, checks exact 32-window and 1,024-fallback command sequences, refuses malformed/stale/replayed requests without stream or Flash advance, and refuses a corrupted response descriptor without a canonical checkpoint advance. The corrupt descriptor is a proof return-envelope seam, not an injected native memory write.

It also restores the canonical checkpoint while A retains its original live core and lease and B keeps walking with an unchanged canonical head. An ordinary joypad Save advances the native counter from 10 to 11 while retaining UID 1/2 and native party contents. Normal closure preserves the read-only Flash bytes; new core processes Continue with the expected distinct trainers, party contents, identities and coordinates. The original A/B source bytes and private database integrity are checked at completion. No savestate, raw RAM injection or active `.sav` replacement is used.

Frozen optimized build: `/home/kevin/src/pokemon/multiplayer-proof/save-window-fast-build-54f977f`.

- ROM SHA256: `d08ee91f0b2c4614a5e75adb8f42a937d063ccb4fa027a81d5d9f83b15642e06`
- ELF SHA256: `2463570830b3c850c6b9f9f29196b00685a147b5883da936666075c4b90e7d20`
- Manifest SHA256: `e201ca15d821c1d1cc618c66dca1f48888a5ad96c44d7d495b96f5ced2446f60`

Private run: `/home/kevin/src/pokemon/multiplayer-proof/save-window-fast-60fps-1`, containing 67 files including the preserved profiling controller, full evidence, stage profile, read-only Flash diagnostics and framebuffer PNGs.

- Evidence SHA256: `d99e2953a5b31a7cd89546ad37ebdadb91e78c865c673b4ca33313d23b0f82db`
- Stage profile SHA256: `4fdc2db18bbe40a7ad76af18cdec397ea09029a02b5eecacc9cabe80033d223a`
- Compact acceptance SHA256: `5625cd00a05b445f2eff0f864b94dc36e49147104f49958f1eb727acf2cc765a`
- Profiling controller SHA256: `e9220914636c9069380f89ecb6e0b12a7b3c187aaecd2bcbd2e15c0056d44eb9`
- Accepted baseline evidence SHA256: `0df2d49da00cbef6a0b38e2b38751e268a9ee402b81a54db3e218b5cef8b6eda`

Private ROMs, saves, credentials and databases stay outside Git. This acceptance covers the optimized CRC and existing checkpoint lifecycle. It does not enable autosave, choose a saving interval or offline policy, or establish Windows, Wi-Fi, Internet or package acceptance.
