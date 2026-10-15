# `src/platform/bios.c`: licensing review (Update 7)

**Status: NOT resolved. This is a review, not legal advice and not a decision.** Nothing in this build changes the
licensing position of the file. Do not hand a build to anyone outside the owner until the owner decides (option B or C below).

## Facts (read from the engine repository, `claude/dev-update2-7-engine`)

* `src/platform/bios.c` (545 lines) is the native PC build's replacement for the GBA's BIOS calls. Line 2 says its
  implementations "are based on the VBA-M source code" (VBA-M is **GPL-2.0-or-later**). Line 445 says `ArcTan`,
  `ArcTan2` and `Sqrt` were "taken from mGBA's source" (mGBA is **MPL-2.0**). The platform layer's README and
  `docs/dependency-ledger.md` already list this as open.
* It reached this project through the "voxel project" port lineage (MIT for that lineage's own changes); the MIT
  notice does not relicense third-party code inside the file.
* The GBA ROM build does not use this file (it is excluded from `Makefile`'s source list; the ROM stays byte-identical
  `f214735b…3387`). **Only the native PC game (both Windows executables, the Linux builds) contains it.**
* What the file implements: `CpuSet`, `CpuFastSet`, `LZ77UnCompWram/Vram`, `RLUnCompWram/Vram`, `BgAffineSet`,
  `ObjAffineSet`, `ArcTan`, `ArcTan2`, `Sqrt`, plus memory access helpers and the memory-region definitions at the top.

## What the licences would require

| Material | Licence | If the exe is given to someone |
| --- | --- | --- |
| VBA-M derived functions (most of the file) | GPL-2.0-or-later (strong copyleft) | The whole program that links it is a combined work: its complete corresponding source would have to be offered under GPL-compatible terms. The rest of the game is pret/pokeemerald-derived code of unclear redistributable status and cannot simply be put under the GPL. This is the blocking issue. |
| `ArcTan`, `ArcTan2`, `Sqrt` | MPL-2.0 (file-level copyleft) | The source of that file (with the notices) must be available to recipients; weaker, but it applies to the same file. |

A private copy that stays with its owner (or friends the owner personally shares the *source* with) is a different
question from distributing binaries; that line is for the owner, and ideally a lawyer, to draw.

## Options

* **A. Keep it private** (current state). No new obligation; the package is "for the owner's own PCs" and must not be
  passed on. The GitHub Actions artifact is private (7 days) and unsigned.
* **B. Replace the file with an independent implementation** written from public hardware documentation (GBATEK) by
  someone who has not copied VBA-M/mGBA code. The surface is small (12 functions) and unusually well covered by the existing
  checks: `make check-decompress` compares every compressed asset the game ships with the original bytes (this covers
  LZ77 and run-length, WRAM and VRAM entry points, with an overrun guard); the 4096-combination style of check used for
  the gamepad would work for `CpuSet/CpuFastSet` and the affine functions; `ArcTan/ArcTan2/Sqrt` can be checked against the
  documented BIOS behaviour (and, only on the owner's own PC, against a real BIOS dump, which must not be committed).
  **Caveat:** the assistant that would write it has read this file; strictly clean-room it should be done by someone
  else, or the owner must accept a "written from the specification, but by someone who has seen the old code" risk.
  `ArcTan`'s polynomial constants are the real BIOS routine's, recovered by reverse engineering; GBATEK does not give them,
  so an independent version would be a different (approximating) formula and could change the game's results slightly
  (it is used for a few angle calculations).
* **C. Comply with the licences**: publish the engine source under GPL-2.0-or-later terms with the binaries. Not recommended:
  it conflicts with the status of the remaining game code and with keeping the project private.
* **D. Link a licensed BIOS replacement library** whose licence permits it (none vetted here).

## Recommendation

Keep to option A now. If the project is ever to be given to friends as binaries, do option B (independent
implementation, validated by the checks above) *before* the first handover, and record who wrote it and from what.
Until the owner chooses, every package and artifact says "private build, not for redistribution". The engine
repository must stay private as well.

## What this build did

No change to `bios.c`. This review, the artifact naming ("private"), and the open item in
`docs/owner-decisions.md` (#1) are the only changes. Nothing was committed that would publish the file.
