# N8: a legal way to give the game to other people (investigation of 2026-11-17)

**Status: investigation only. This is not legal advice, and nothing in the build changed.** The installer stays
private (`docs/owner-decisions.md` #70). Nothing here holds up local testing: the private installers from the CI
runs stay usable on the owner's own PCs. The earlier review is `docs/bios-licensing-review.md` (Update 7); this
document brings it up to date and adds the larger question it left out.

## The short answer

1. **No Nintendo BIOS is bundled, and none is needed.** The installer carries no BIOS dump, no ROM and no save (the
   package audit refuses them). N8 is about `src/platform/bios.c` in the engine: the native PC game's own
   replacement for 11 GBA BIOS calls. Most of it was **derived from VBA-M's source (GPL-2.0-or-later)**, and three
   functions were **taken from mGBA's source (MPL-2.0)**, as its own comments say (line 2 and line 445).
2. **GPL code inside the game's executables is the blocking part.** Handing someone a program that contains
   GPL-licensed code obliges you to offer the source of the whole program under the GPL. The rest of the game's code
   is not ours to put under the GPL (see 4), so the GPL obligation cannot be met.
3. **That part can be fixed with a small, well-tested engineering change and no gameplay change** (Part 1): replace
   the VBA-M-derived functions with an independent implementation. Then either keep mGBA's three functions in a file
   of their own under MPL-2.0, which only asks that this one file's source be offered, or replace them too.
4. **Fixing `bios.c` does not make the game distributable.** The two game executables are compiled from the Pokemon
   Emerald decompilation (pret/pokeemerald and pokeemerald-expansion, which grant no rights to the game's code or
   material) and contain the game's code, graphics, music, maps and text. The installer also carries the private
   battle sprite pack of official art. All of that is the copyrighted work of Nintendo, Creatures and GAME FREAK,
   and "Pokemon" and its names are their trademarks. No engineering change makes giving that away legal without the
   rights holders' permission (Part 2).
5. **The model ROM hacks use, where each player supplies their own game and the package carries only this project's
   own work, lowers the risk but does not remove it.** In December 2016 Nintendo sent a cease and desist to
   *Pokemon Prism*, a Pokemon Crystal ROM hack meant to be shared as a patch for players' own games, four days
   before its release. The same year *Pokemon Uranium*, a fan game, received takedown notices. **Before giving the
   game to anyone, friends included, the owner should get advice from a lawyer.**

## What the private installer contains today (CI-476)

| Part | What it is | Terms | Can it be given to others? |
| --- | --- | --- | --- |
| `EmeraldTogether.exe` (launcher), the host and companion | This project's own Python code, frozen with PyInstaller; CPython, Tk, `cryptography`, `cffi`, `pycparser` | Project-owned; PSF, Tcl/Tk, Apache-2.0/BSD, MIT-0, BSD-3; PyInstaller's GPL has an exception for bundled apps | Yes, with the notices (`docs/dependency-ledger.md`; its final notice audit is still to do) |
| `pokeemerald-mp-diorama.exe`, `pokeemerald-mp.exe` | The game compiled for Windows: the decompiled game's code and data; the PC port layer (voxel project lineage); this project's own code; `bios.c` | Game material: no licence; port layer: MIT, its notice kept; `bios.c`: GPL-2.0-or-later and MPL-2.0 | **No** (the game material, and the GPL in `bios.c`) |
| `SDL2.dll` | Window, input and sound library | zlib | Yes |
| `stb_image` (zlib decoder inside the game) | Sean Barrett's single-file library | Public domain or MIT | Yes |
| `battle-sprites.ebsp` | The animated battle sprite pack | Private official art (`docs/battle-sprites.md`) | **No** (the game runs without it, with the GBA's own sprites) |
| `battlefx/` | The 3D battle effects | Textures and meshes procedural; the animation data converted from the game's own battle animation scripts | The data, like the game, no |
| `game-facts.json` | Facts about the game build (hashes, addresses) for the launcher | Project-made | Yes |

The GBA ROM (`pokedev.gba`) is never copied into the package; the launcher's "Import my game" and the package
builder's `--create-patch` already support a player's own Emerald dump (SHA-256 `a9dec84d...85af`, checked before
use) and a BPS patch in place of the ROM (`docs/release-patch-creation.md`).

## Part 1: `bios.c`, the fixable part

What the game uses (call sites in the engine, the PC build only; the GBA ROM does not contain this file and stays
byte-identical):

| Function | From | Used by | Must stay exact? |
| --- | --- | --- | --- |
| `CpuSet`, `CpuFastSet` | VBA-M (GPL) | Copies and fills: battle transitions, the trainer card, evolution palettes, Mirage Tower, scanline effects, the link code (13 places) | Yes (data) |
| `LZ77UnCompWram`, `LZ77UnCompVram` | VBA-M (GPL) | Every compressed graphic and tilemap (`src/decompress.c`) | Yes (data); `--selftest-decompress` already checks every compressed asset against the original bytes |
| `RLUnCompWram`, `RLUnCompVram` | VBA-M (GPL) | Nothing: declared, never called | Can simply be dropped |
| `BgAffineSet`, `ObjAffineSet` | VBA-M (GPL) | Rotating and scaling backgrounds and sprites: sprites' affine animations, the intro, battle and Pokemon animations, the Pokedex cry screen (9 places) | Yes, or pictures move by a pixel |
| memory helpers and region definitions | VBA-M (GPL) | The functions above | - |
| `Sqrt` | mGBA (MPL) | **The catch formula** (`battle_script_commands.c`: a Poke Ball's shake odds) | Yes (gameplay): an integer square root has one right answer, so any correct version agrees |
| `ArcTan2` (with `ArcTan`) | mGBA (MPL) | Angles in battle animations (`battle_anim_mons.c`) | For identical pictures, yes; visual only |

Options:

* **A. An independent implementation of all eleven**, written from public hardware documentation (GBATEK) and the
  game's own declarations (`include/gba/syscall.h`), by someone who has not read `bios.c`, VBA-M or mGBA, and
  checked against today's results. Every function except `ArcTan` can be checked exhaustively or near-exhaustively
  in seconds (all 4 billion `Sqrt` inputs, every `CpuSet`/`CpuFastSet` mode, every rotation angle at many scales,
  every compressed asset). Comparing outputs does not copy code. Two caveats: **who writes it** - Claude has read
  `bios.c`, and a fresh Claude session without the file is still the same model, which may have seen VBA-M's and
  mGBA's public source in training; a person who has never read those emulators is the stronger clean room. And
  **`ArcTan`**: its results come from the real BIOS's polynomial, which GBATEK does not give; an independent version
  either reproduces the same results (the numbers are facts about the BIOS) or accepts angles a hair different in a
  few battle animations.
* **B. Replace the six VBA-M-derived functions the game calls and the helpers, dropping the two it never calls (the
  GPL part); keep mGBA's three in a file of their own under MPL-2.0**, with its notice, offering that one file's source with the game. MPL-2.0 applies file by
  file and does not reach the rest of the program. This removes the blocking GPL with the least change and keeps
  every result identical. **Recommended**, with A's process for the six functions and the author and sources
  recorded.
* **C. Comply with the GPL** by publishing the whole program's source under it: not possible, because the game's code
  is not ours to license.
* **D. Port a permissively licensed replacement BIOS.** For example the Cult-of-GBA BIOS, which its page describes as
  written from scratch in ARM assembly; its licence and its accuracy against the real BIOS would have to be confirmed
  first. Not checked here.

Effort for B: about a day, with the checks above; no gameplay or save change; the GBA ROM untouched. It is worth
doing only if the owner means to give the game to someone eventually, because on its own it does not make the
package distributable (Part 2). **Not started: waiting for the owner's choice of A, B or D and of who writes it.**

## Part 2: the game itself, the main obstacle

1. **Keep it private** (today): the owner's own PCs. Every package and artifact says it is a private build.
2. **"Bring your own game"**: the player supplies their own Emerald dump, the package contains only this project's
   own work, and everything made from the game is produced on the player's PC from that dump. Where this project
   stands: the GBA side is ready (`--create-patch`, the checked dump, no ROM in the package). The native executables
   are not: they contain the game's code and data. Loading the data from the player's own game instead would be a
   large change (thousands of graphics, sounds, maps and data tables, many written as C source, with the pointers
   between them), and the executables would still contain code compiled from the decompilation, which is derived
   from Nintendo's program. The 3D view's building models are made from the game's tile art and would have to be
   generated on the player's PC too, and the battle sprite pack left out. Projects that ship decompiled code without
   the game's assets and ask for the player's own ROM exist, but their legal position has not been settled, and
   Pokemon Prism shows that even a patch-only release has been stopped.
3. **Permission from the rights holders**: the only route to certainty; unlikely for a fan project.

## What this means now

* The installer stays private; the CI-476 installer (and each later full run's) remains available for the owner's
  own tests and the real-hardware release tests (`docs/owner-decisions.md` #74).
* Nothing in N8 blocks local testing or the engineering work queued after it.
* N8 stays open. If the owner wants the GPL removed now, Part 1 option B is ready to start on their word (and their
  choice of who writes it). Part 2 should wait for legal advice.

Sources for the two takedowns: [Pokemon Prism (Wikipedia)](https://en.wikipedia.org/wiki/Pok%C3%A9mon_Prism),
[PokeCommunity Daily, 2016-12-21](https://daily.pokecommunity.com/2016/12/21/rom-hack-pokemon-prism-receives-cease-desist),
[Nintendo Life, 2016-12](https://www.nintendolife.com/news/2016/12/nintendo_shuts_down_another_pokemon_fan_project).
The Cult-of-GBA BIOS: [its repository page](https://github.com/Cult-of-GBA/BIOS) (not read beyond its description).
