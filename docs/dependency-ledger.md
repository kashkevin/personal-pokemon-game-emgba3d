# Initial dependency and provenance ledger

Recorded October 7, 2026, for Phase 1. This records provenance and observed terms; it does not grant blanket rights to game code or assets.

## Engine and desktop emulator

| Dependency | Revision and role | Terms and status | Primary source |
| --- | --- | --- | --- |
| RHH pokeemerald-expansion | `expansion/1.17.1`, `bb1093a7c72d3961d9a37d8e02ad2abc2c866682`; unmodified engine baseline. Local `HEAD` verified. | No blanket root license found in the pinned tree. Preserve contributor/asset provenance and credits; distribution review remains pending. | [Pinned source](https://github.com/rh-hideout/pokeemerald-expansion/tree/bb1093a7c72d3961d9a37d8e02ad2abc2c866682), [credits](https://github.com/rh-hideout/pokeemerald-expansion/blob/bb1093a7c72d3961d9a37d8e02ad2abc2c866682/CREDITS.md) |
| pret/pokeemerald | Emerald decompilation inherited through the pinned RHH tree; no separate pret checkout is selected. | No blanket root license identified in upstream. Source availability and credits do not establish permission for every inherited game asset or contribution. | [pret source](https://github.com/pret/pokeemerald), [RHH overview](https://github.com/rh-hideout/pokeemerald-expansion/blob/bb1093a7c72d3961d9a37d8e02ad2abc2c866682/README.md) |
| mGBA desktop | `0.10.5`, source commit `26b7884bc25a5933960f3cdcd98bac1ae14d42e2`; selected Windows development emulator. | MPL 2.0 for covered source. Retain notices and give recipients access to corresponding covered source, including modifications, if packaged. Dependency notices require their own review. | [Pinned source](https://github.com/mgba-emu/mgba/tree/26b7884bc25a5933960f3cdcd98bac1ae14d42e2), [license](https://github.com/mgba-emu/mgba/blob/26b7884bc25a5933960f3cdcd98bac1ae14d42e2/LICENSE) |

The desktop emulator and the upstream test emulator are different builds. A source commit is not a binary checksum; installed/build artifact hashes belong in the build manifest.

## Bundled upstream test tools

The pinned local `tools/mgba/README.md` identifies the bundled test binaries' source commits:

- Linux, used by the WSL test workflow: [`dbffb46c4e7d2e7a2cbed7c3488cece4c2176d4c`](https://github.com/mgba-emu/mgba/tree/dbffb46c4e7d2e7a2cbed7c3488cece4c2176d4c).
- Windows: [`7ee2be6c96222dca12a9a579b747fe5ff1829def`](https://github.com/mgba-emu/mgba/tree/7ee2be6c96222dca12a9a579b747fe5ff1829def).
- macOS: [`daf01b03d5316dac966acd4b05318a225cab12f5`](https://github.com/mgba-emu/mgba/tree/daf01b03d5316dac966acd4b05318a225cab12f5).

Provenance: [pinned bundled-build README](https://github.com/rh-hideout/pokeemerald-expansion/blob/bb1093a7c72d3961d9a37d8e02ad2abc2c866682/tools/mgba/README.md). The Linux source has an [MPL 2.0 license](https://github.com/mgba-emu/mgba/blob/dbffb46c4e7d2e7a2cbed7c3488cece4c2176d4c/LICENSE). These are developer test dependencies, not selected player runtime binaries.

Hydra is bundled in RHH at the engine revision above. Its inspected `main.c` and directory contain no explicit standalone license notice; do not label the whole runner MIT or MPL. Its last recorded source change is `d80faeb97eb957a55ed1d6237122a8b21e50202e`.

- [Pinned Hydra runner](https://github.com/rh-hideout/pokeemerald-expansion/blob/bb1093a7c72d3961d9a37d8e02ad2abc2c866682/tools/mgba-rom-test-hydra/main.c).
- Its [bundled `elf.h`](https://github.com/rh-hideout/pokeemerald-expansion/blob/bb1093a7c72d3961d9a37d8e02ad2abc2c866682/tools/mgba-rom-test-hydra/elf.h) explicitly credits musl/Rich Felker and carries MIT-style permission terms. Retain that notice; it does not cover unrelated Hydra source.

## Developer toolchain

GNU Arm compiler/binutils, GNU make, newlib development files, Git, Python, and image build dependencies support the developer build. Friends will not need their compiler/tool executables in the eventual Windows game package. Record installed package versions and package-specific copyright/license notices in the build manifest; any linked library material needs separate review.

Primary references: [pinned upstream CI packages](https://github.com/rh-hideout/pokeemerald-expansion/blob/bb1093a7c72d3961d9a37d8e02ad2abc2c866682/.github/workflows/build.yml), [GNU GCC](https://gcc.gnu.org/), [GNU binutils](https://www.gnu.org/software/binutils/), [newlib](https://sourceware.org/newlib/).

## Incorporation and distribution status

- No additional third-party networking implementation or art has been imported beyond the unmodified upstream engine tree.
- Wired-Ariel, TheHunterManX, Celio, Quetzal, and native Emerald ports remain research references, not incorporated dependencies.
- The proposed launcher, companion/server, packaging tool, and mGBA frontend patch are not implemented or shipped yet.
- Before sending a package to friends, record every included binary, modified source component, and asset's revision, notices, applicable terms, and unresolved permission. Distribution review is pending; emulator licensing does not license Pokémon content.
