# Initial dependency and provenance ledger

Recorded October 7, 2026, for Phase 1. This records provenance and observed terms; it does not grant blanket rights to game code or assets.

## Engine and desktop emulator

| Dependency | Revision and role | Terms and status | Primary source |
| --- | --- | --- | --- |
| RHH pokeemerald-expansion | `expansion/1.17.1`, `bb1093a7c72d3961d9a37d8e02ad2abc2c866682`; unmodified engine baseline. Local `HEAD` verified. | No blanket root license found in the pinned tree. Preserve contributor/asset provenance and credits; distribution review remains pending. | [Pinned source](https://github.com/rh-hideout/pokeemerald-expansion/tree/bb1093a7c72d3961d9a37d8e02ad2abc2c866682), [credits](https://github.com/rh-hideout/pokeemerald-expansion/blob/bb1093a7c72d3961d9a37d8e02ad2abc2c866682/CREDITS.md) |
| pret/pokeemerald | Emerald decompilation inherited through the pinned RHH tree; no separate pret checkout is selected. | No blanket root license identified in upstream. Source availability and credits do not establish permission for every inherited game asset or contribution. | [pret source](https://github.com/pret/pokeemerald), [RHH overview](https://github.com/rh-hideout/pokeemerald-expansion/blob/bb1093a7c72d3961d9a37d8e02ad2abc2c866682/README.md) |
| mGBA desktop | `0.10.5`, source commit `26b7884bc25a5933960f3cdcd98bac1ae14d42e2`; selected Windows development emulator. | MPL 2.0 for covered source. Retain notices and give recipients access to corresponding covered source, including modifications, if packaged. Dependency notices require their own review. | [Pinned source](https://github.com/mgba-emu/mgba/tree/26b7884bc25a5933960f3cdcd98bac1ae14d42e2), [license](https://github.com/mgba-emu/mgba/blob/26b7884bc25a5933960f3cdcd98bac1ae14d42e2/LICENSE) |

The desktop emulator and the upstream test emulator are different builds. A source commit is not a binary checksum; installed/build artifact hashes belong in the build manifest.

The [generated Gen6 friendship table](gen6-friendship-table.md) extracts 721 standard-species numeric facts from that same incorporated RHH pin with a temporary `P_UPDATED_FRIENDSHIP=GEN_6` probe. Its [provenance](gen6-friendship-table.json) records exact input hashes and toolchain versions. It imports no new library, source implementation or artwork and changes no installed engine configuration. The inherited engine/asset distribution limits remain unchanged.

The [held trade record transport](native-trade-record-transport.md) reuses that
same incorporated native trade/evolution code through project-owned private
record helpers and the existing save mailbox. No external code, library or
artwork was imported. Its optional capability and additive source patch are
unbuilt and untested; existing distribution limits remain unchanged.

The optional retained-battle recovery candidate is a project-owned delta on combined native source `1a7a0cdb5dadd2820a3b6c25c4ecafce1facd6eb`. Its isolated source commit is `aef47e4b28fd6d0e84376961e0cc6632996bb0be`; the reviewable [source patch](../engine-patches/phase5-native-retained-recovery.patch) has SHA-256 `94ee6c7c62beb1c97f4d222a9f4a3c6aec1f329f994fdf2ec8c56a19de48b078`. It adapts existing project mailboxes, native field holds and ownership checks without importing another networking engine, library, art or save layout. Existing upstream terms remain unchanged. The [recovery audit](native-battle-recovery.md) records its qualification limits; it is excluded from the qualified non-resume preview.

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

The project-owned baseline and multiplayer headless frontends use the public core API of mGBA 0.10.5 at `26b7884bc25a5933960f3cdcd98bac1ae14d42e2`. The core's covered source is unchanged. These are private development builds. The multiplayer headless frontend uses a separate scripting-enabled core build with Ubuntu Lua 5.4.6 (`5.4.6-3build2`) and its development headers. Lua carries [MIT permission terms](https://www.lua.org/license.html). CMake and the native C compiler are development dependencies.

## Private Windows SDL runtime

Recorded October 8, 2026. The Windows development frontend uses the same pinned mGBA core. Only `src/platform/sdl/main.c` and `sdl-events.c` are adapted, with the project-owned adapter in `native/windows-runtime/`. The adapter loads the explicit isolated save and Lua bridge, initializes the public socket subsystem, and blocks rewind, state loading, patches, cheats, frontend reset and the BIOS reset chord in multiplayer mode. It does not patch the emulator core or game ROM. The pinned build recipe is in `scripts/windows-runtime/`.

| Component | Exact source / role | Terms and retained material |
| --- | --- | --- |
| mGBA 0.10.5 | `26b7884bc25a5933960f3cdcd98bac1ae14d42e2`; static core and adapted SDL frontend | MPL 2.0. Collection retains the complete pinned source archive, original license, two-file frontend patch and adapter source. [Pinned license](https://github.com/mgba-emu/mgba/blob/26b7884bc25a5933960f3cdcd98bac1ae14d42e2/LICENSE). |
| SDL2 2.32.10 | Official x64 MinGW SDK and `SDL2.dll`; official source retained separately | zlib license. SDK archive SHA256 `83a5d74012311edc3c0d40ea6faecbe57ad692aa033fa5dc273cc937e3938ff2`; source archive `5f5993c530f084535c65a6879e9b26ad441169b3e25d789d83287040a9ca5165`. [Official release](https://github.com/libsdl-org/SDL/releases/tag/release-2.32.10), [license](https://github.com/libsdl-org/SDL/blob/release-2.32.10/LICENSE.txt). |
| Lua 5.4.9 | Static scripting library compiled from official source; no Lua executable/DLL bundled | MIT. Source archive SHA256 `2335b6c582a52654f94612bf10d2f4672805d05329aa6568b1d8cd9e5c6fb8e6`; retained source and original README/license notice. [Official source](https://www.lua.org/ftp/), [terms](https://www.lua.org/license.html). |
| libepoxy 1.5.10 | Static Windows WGL dispatcher required by the upstream standalone Windows frontend | MIT plus the Khronos notice in `COPYING`. Source archive SHA256 `a7ced37f4102b745ac86d6a70a9da399cc139ff168ba6b8002b4d8d43c900c15`. [Pinned source](https://github.com/anholt/libepoxy/tree/1.5.10), [notices](https://github.com/anholt/libepoxy/blob/1.5.10/COPYING). |
| MinGW-w64 / GCC | Ubuntu `mingw-w64-x86-64-dev 11.0.1-3build1`, `gcc-mingw-w64-x86-64-posix-runtime 13.2.0-6ubuntu1+26.1`; x64 POSIX compiler, static GCC runtime and dynamic `libwinpthread-1.dll` | Retain the installed package copyright files. Winpthreads has MIT/BSD component notices; linked GCC runtime material uses its Runtime Library Exception. Compiler/tool copyright terms must not be confused with those of every library. [MinGW source](https://github.com/mingw-w64/mingw-w64/tree/v11.0.1), [GCC exception](https://www.gnu.org/licenses/gcc-exception-3.1.html). |
| Bundled blip_buf 1.1.0 | Compiled audio resampler at the pinned mGBA revision | LGPL 2.1 or later. Retain its license/source and the corresponding frontend object/static-library relink inputs; recipient packaging must preserve the ability to modify/relink this library. [Pinned source and notice](https://github.com/mgba-emu/mgba/blob/26b7884bc25a5933960f3cdcd98bac1ae14d42e2/src/third-party/blip_buf/blip_buf.c). |
| Bundled inih | Compiled configuration parser at the pinned mGBA revision | BSD 3-Clause. Retain original notice. [Pinned license](https://github.com/mgba-emu/mgba/blob/26b7884bc25a5933960f3cdcd98bac1ae14d42e2/src/third-party/inih/LICENSE.txt). |

`fetch_dependencies.py` verifies official archive hashes; `build_runtime.sh` keeps host Linux libraries out of the Windows dependency search, uses SDL's relocatable CMake configuration, and builds at most two workers at low priority. The qualified Windows configuration disables upstream LTO: GCC 13.2 with LTO caused all Lua bound-object method calls to fail; the same core, optimization level and dependencies pass those calls with LTO disabled. libepoxy is used through its normal upstream support; the Windows dependency guard is not removed.

`collect_bundle.py` refuses changes to tracked mGBA core files, records PE DLL imports, and creates a bounded hash-pinned runtime manifest with source archives, notices, build recipes and relink inputs. The imported non-system DLLs are SDL2 and Winpthreads; neither depends on another non-system DLL in the inspected build. Source/dependency pins make the recipe repeatable; this does not claim bit-identical output across arbitrary compilers, build directories or timestamps.

The actual Windows graphical smoke on frozen trade build `b2cdd46` used copied private ROM/save files, ordinary scripted Start/A inputs through native Continue, the real Lua socket bridge and local companion/server. It rendered the saved overworld, loaded the two-mon party, exchanged ROM presence and closed normally with original hashes unchanged. A separate, explicitly pinned proof bundle additionally exercised `PlayerRuntime.open()` with a cloned consistent schema3 world/profile: current head4 was verified/restored while closed; the exclusive save lease remained blocked through native Continue and owned-party Box CRC verification, then became available only after normal close. The cloned head/integrity and every original input hash remained unchanged. Keyboard pulse timing, audible playback, gamepad behavior, final launcher packaging and multi-machine acceptance are separate gates. These private binaries have not been sent to friends; game-content distribution review remains pending.

## Private host certificate provisioning

Recorded October 8, 2026. New `host_world.py` and `invitations.py` reuse the project's stdlib TLS/store transport and use maintained `cryptography` for X.509/key generation. Official documentation and license were reviewed before installation. Only isolated private Windows/WSL development virtual environments were installed; global Python and system certificate trust remain unchanged.

| Component | Exact development version | Terms / primary source |
| --- | --- | --- |
| cryptography | 50.0.2, official Windows x64 / manylinux x64 binary wheels | Apache-2.0 or BSD-3-Clause; original dual-license notices retained. [Release](https://pypi.org/project/cryptography/50.0.2/), [X.509 tutorial](https://cryptography.io/en/stable/x509/tutorial/), [official installation](https://cryptography.io/en/stable/installation/), [license](https://github.com/pyca/cryptography/blob/main/LICENSE). |
| cffi | 2.1.1, platform-specific official wheels | The downloaded wheel's original notice states MIT No Attribution (MIT-0), with separately marked components retaining their own terms. [Release](https://pypi.org/project/cffi/2.1.1/). |
| pycparser | 3.0, official universal Python wheel | BSD-3-Clause; original notice retained. [Release](https://pypi.org/project/pycparser/3.0/). |

All platform wheel SHA-256 values were compared to the official PyPI release API. The exact hashes and development install/API record are in [host-provisioning.md](host-provisioning.md) and `requirements-host-provisioning.txt`. Packaging still requires a complete notice audit of the actual final OpenSSL/Rust/transitive dependency bundle; these development installs and private certificate tests do not qualify distribution or Internet acceptance.

## Private Windows launcher packaging

Recorded October 8, 2026. The first actual `onedir` preview bundles the existing Python application and verified SDL runtime with a stdlib Tk Host/Join window. The [GUI audit and evidence](windows-launcher-gui.md) records its real release pins and limits. Python/Tk are runtime dependencies; PyInstaller and its analysis dependencies are private build tools. No Qt/PySide or external patcher implementation was incorporated. The BPS reader follows byuu's public-domain format specification; Flips and RomPatcher.js remain research references.

| Component | Exact version | Observed terms and role |
| --- | --- | --- |
| CPython | Windows x64 3.14.4 | PSF license plus the original distribution's component notices; installed `LICENSE.txt` is copied to the package. [Python license](https://docs.python.org/3/license.html). |
| Tcl/Tk | Official Python-bundled 8.6.15 runtime | Permissive Tcl/Tk terms with retained attribution; Python's notices and the installed Tk `license.terms` are retained. [Tcl/Tk terms](https://www.tcl-lang.org/software/tcltk/license.html). |
| PyInstaller | 6.22.3 Windows x64 wheel | GPL-2.0-or-later with application-bundling exception; certain runtime files are Apache-2.0. Original `COPYING.txt` retained; source unchanged. [Exact release](https://pypi.org/project/pyinstaller/6.22.3/), [license explanation](https://pyinstaller.org/en/stable/license.html). |
| pyinstaller-hooks-contrib | 2026.8 | Standard analysis hooks GPL-2.0-or-later; runtime hooks Apache-2.0. Original combined notice retained. [Exact release](https://pypi.org/project/pyinstaller-hooks-contrib/2026.8/). |
| altgraph | 0.17.5 | MIT; build graph analysis, original notice retained. [Release](https://pypi.org/project/altgraph/0.17.5/). |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause; original dual notices retained. [Release](https://pypi.org/project/packaging/26.3/). |
| pefile | 2024.8.26 | MIT; Windows PE build analysis, original notice retained. [Release](https://pypi.org/project/pefile/2024.8.26/). |
| pywin32-ctypes | 0.2.3 | BSD-3-Clause; Windows build support, original notice retained. [Release](https://pypi.org/project/pywin32-ctypes/0.2.3/). |
| setuptools | 84.0.0 | MIT for setuptools; vendored component licenses remain separate. Build environment only; its component notices were copied without asserting they are all MIT. [Release](https://pypi.org/project/setuptools/84.0.0/). |

Every build-tool wheel is pinned by version and SHA-256 in [`requirements-launcher-build.txt`](../scripts/windows-runtime/requirements-launcher-build.txt), compared to official PyPI release metadata, and installed with `--only-binary=:all: --require-hashes` into a separate private Windows virtual environment. Existing cryptography/cffi/pycparser pins are reused. Native runtime source/relink materials and all selected notices accompany the package. Package hashes and Python-source hashes are retained privately. This does not complete the final transitive binary/asset distribution review or qualify gameplay, audio/input, clean-machine installation or Internet transport.

## Runtime source archive derivative

The recursive packaging review subsequently found unused upstream `cinema/` ROM/save fixtures inside the original mGBA source tar. The original pinned source/build and private packages remain preserved. Recipient source packaging now uses the reviewed derivative recorded in [windows-runtime.md](windows-runtime.md#source-archive-packaging-derivative), created by the project-owned exact-inventory sanitizer in commit `7b02030`.

This is still mGBA commit `26b7884bc25a5933960f3cdcd98bac1ae14d42e2`: 193 binary test fixtures are omitted (154 GB ROMs, three GBA ROMs, five empty saves and 31 initial-state video logs), with every retained member byte and metadata unchanged. Production source, attribution/licenses, the SDL patch/adapter, all dependency source archives and the complete existing object/static-library relink inputs are retained. Tests/cinema/performance targets are disabled in the qualified production build; these omitted test assets are not production or relink inputs. No new third-party implementation was imported, no license was changed, and no executable/DLL/bridge was rebuilt.

The original source archive is `24e11bd15b49dcbd74513e8fd6acdcead005616c0e3f52b8e93413fb8f42725e`; the derivative is `d2648866d4cb01d1cdaf882d4a3b0f3764aba9ba5beb73cbd8896b54eac082e3`. The new runtime manifest is `dfd3b2d91e874b0823bfd04b5d48e6db64ff243671b4f954a055947e3baf6c21`. The bundled `source-packaging.json` records exact omitted paths/hashes and the preserved-source digest. The earlier table's “complete pinned source archive” describes the original private collection; the cleaned recipient archive intentionally excludes these test fixtures. This cleanup does not itself complete distribution review or playable acceptance.

## Incorporation and distribution status

The October 9 trusted trade replay worker is project-owned C linked against
the same incorporated mGBA `26b7884bc25a5933960f3cdcd98bac1ae14d42e2` core and
existing Lua/libepoxy/Winpthreads cache. No core source changes, PKHeX code or
additional dependency were imported. It uses the public core register/bus API
to execute only the verified ROM's bounded copy-only trade trampoline in an
isolated unbooted VM. Its separate executable is included in `runtime.json`;
the exact worker source/object are retained in `relink-inputs.tar.gz` with a
separate MinGW `-municode` command. Existing covered source, sanitizer provenance,
component notices and LGPL blip_buf relink inputs remain required. These source
and collection changes alone establish neither successful linking nor replay
correctness/performance; see [worker design and evidence](native-trade-replay-worker.md).

The bounded single-GBA ZIP reader uses Python's already bundled standard
`zipfile`/`zlib` modules and the existing project BPS implementation. It imports
no external patcher. The supplied owner dump remains private and read-only;
only a separately verified modification patch may enter a new package.

The October 8 source-only feature batch reuses the already incorporated pinned
RHH trade/evolution, authored encounter and object APIs plus the project's
existing host journals, menus and bundled Tk. No new third-party implementation,
asset, runtime or library was imported. Exact adaptations and inspected current
upstream references are recorded in [trade record preparation](native-trade-record-preparation.md),
[expanded personal sources](local-reset-expanded-sources.md) and
[Trainer Card/hunt records](player-card-and-hunt-records.md). Their new source
has not been built, tested or distributed; inherited source/asset terms remain.

The subsequent October 8–9 source batch adds project-owned [Championship
orchestration](championships.md), [five ticket/static reset adapters](local-reset-ticket-sources.md)
and [complete paired recipient save-effect preparation](native-trade-save-effects.md).
It reuses the same incorporated engine, project battle/recovery services and
Python standard-library SQLite; no external implementation, asset or dependency
was imported. The linked component notes retain exact upstream research pins,
save/multiplayer boundaries and unmeasured performance. Research references are
not incorporated dependencies. No build, dependency installation or distribution
was performed for this batch.

The October 9 [launcher Championship panel](windows-championship-panel.md),
[recovery reconciliation](championship-recovery.md), and [extended Trainer Cards](trainer-card-shared-records.md)
adapt the existing project services and bundled Tk/SQLite without importing new
dependencies or assets. The [species display labels](species-menu-labels.md) are
721 factual names extracted from the already incorporated engine source; the
[provenance manifest](species-labels-provenance.json) records native Git lineage,
all input hashes and the generated output hash. No native compilation or execution
was involved. This does not change the species roster or resolve asset-distribution
permissions. Existing attribution remains required.

The preceding [twelve-addition source continuation](feature-batch-20261009.md) extends
those same services and native/Tk controls. [Trade inspection](trade-offer-inspection.md)
uses source-derived move/item/nature/Latin-character display facts from the existing
engine; `trade-labels-provenance.json` records every input and generated-output hash.
No new roster, acquisition rule, third-party implementation or art is introduced.
[Full native save transport](native-trade-save-transport.md) adapts the already
incorporated trade/Dex/stat/ribbon and sector-window implementation; its exact
additive patch and private before-source snapshots are recorded there.
[Admission terminal delivery](admission-terminal-handoff.md), [launcher player
interactions](windows-player-interactions.md) and [record browsers](record-browsers.md)
are project-owned extensions with no new dependency or save schema. The linked
notes retain original pins, multiplayer/ownership boundaries and unknown runtime
performance. No build, dependency install or distribution occurred.

The [extended October 9 batch](large-feature-batch-20261009.md) reuses the same
project-owned history, consent, reset, native menu/save and bundled Tk/SQLite
components. [Held move presentation](native-trade-choice-presentation.md) reads
the pinned engine's move facts and `CannotForgetMove` predicate; the native
descriptor patch records exact lineage and hashes. The reset catalogue adds a
read-only descriptor without enabling encounters. The [approved legacy handler
policy](trade-friendship-migration.md) uses the existing generated Gen6 base table
and pinned `VERSION_EMERALD = 3`, adapting the established backed-up transaction
pattern. No PKHeX code/package, new dependency, art or third-party implementation
was imported. The +800 optional history schema is a project-owned source change,
not an executed migration. Existing license/attribution and distribution limits
remain; new runtime and storage performance are unmeasured.

The [customization and reuse audit](customization-and-reuse.md) additionally inspected current RHH upstream, Perfect Emerald's style/color system, Emerald Rogue's outfit/remote-profile system, and CFRU's customization code. These are research references with recorded revisions and integration limits; no source or assets from those candidates were imported. The new project-wide research rule requires component-level licensing, dependency, maintenance/issue, performance and save/network compatibility checks before integration.

- No additional third-party networking implementation or art has been imported beyond the unmodified upstream engine tree.
- Wired-Ariel, TheHunterManX, Celio, Quetzal, and native Emerald ports remain research references, not incorporated dependencies.
- The project-owned Python companion/server, Lua mailbox bridge, and headless test frontends are implemented for private development. They have not been shipped. No third-party networking source was copied into them.
- An adapted Windows SDL frontend and closed-save launcher lifecycle are now private development implementations. The Host/Join interface and final player package remain unfinished; automatic Lua loading alone does not establish release acceptance.
- Before sending a package to friends, record every included binary, modified source component, and asset's revision, notices, applicable terms, and unresolved permission. Distribution review is pending; emulator licensing does not license Pokémon content.

- The October 9 [graphics inventory](graphics-resource-inventory.md) records
  existing tracked art/tilesets and the exact requested community research pins.
  [Remote running](remote-running-animation.md) reuses existing RHH Brendan/May
  walking/running tiles and native movement/animation functions; no external art,
  new palette allocation or additional third-party component was introduced.
  Modern_Emerald, EmceeMikey's fork and the Gen VI DS-style resource remain
  research references only. Their component attribution/permission and measured
  combined multiplayer cost remain prerequisites to any later import.

- The [separate Gen6 defaults profile](gen6-defaults-profile.md) adapts existing
  pinned RHH generation settings and ORAS level-up data, retaining the compiled
  species/save layout. The new descriptor and exact-profile host/client checks
  are project-owned. Current upstream was inspected at the recorded revision;
  no additional third-party source/assets/dependency were imported. Five focused
  native tests and isolated Windows trade replay provide bounded evidence;
  complete Gen6 content, runtime peaks and combined multiplayer acceptance
  remain separate gates.
