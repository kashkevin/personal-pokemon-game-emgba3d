# 64-bit compatibility and memory audit (native PC game)

Performance work of 2026-10-11 (directive "8 GB RAM support, 4K 200 FPS
optimization"), engine branch `claude/graphics-overhaul` from
`graphics-wip-20261010-8` (d799c4a8a). Every number here was measured in the
development container (Linux, software OpenGL; Windows build under Wine) unless
it says otherwise. Nothing here was measured on the owner's PC.

## Answer in short

* The native Windows game is a **32-bit** program (PE32, i386). Until this work
  it was not large-address-aware: 2 GB of address space. It now is
  (`-Wl,--large-address-aware`): **4 GB of address space on 64-bit Windows**.
* It uses about **0.2 GB of RAM** and **35 to 45 MB of graphics memory** today
  (table below). Nothing in the game is short of memory; the renderer's caches can
  grow to about 2.6 GB of budget inside the 32-bit address space.
* A **full 64-bit conversion is not safe now** (inventory below: the save format,
  7,269 pointers in assembler data, 1,027 pointer/integer conversions). It is not
  needed for any measured problem. The isolated proof of concept shows the 3D
  renderer itself is 64-bit clean, which keeps the cheaper path open (a 64-bit
  renderer process) if a future feature ever needs more than ~2.5 GB.
* The memory budget is implemented (F10 "Memory budget", 512 MB to 8 GB or
  automatic): it sizes the renderer's caches. 8 GB is accepted as a budget; what
  can be used is held to the free address space and to half the PC's RAM.

## The executable

| | before | now |
| --- | --- | --- |
| Format | PE32, machine 0x14c (i386) | same |
| Characteristics | 0x106 (no LARGE_ADDRESS_AWARE) | 0x126 (LARGE_ADDRESS_AWARE) |
| User address space on 64-bit Windows | 2 GB | 4 GB |
| SDL2 | SDL2.dll 2.30.7, i686 (32-bit) | same |
| OpenGL | opengl32.dll (the driver's ICD), core profile 3.3 | same |

Test of the large-address-aware build: `PKMN_HIGH_ADDRESS_TEST=1` reserves all
free address space below 2 GB at startup, so everything allocated afterwards
(SDL, the graphics driver, the renderer, thread stacks) lies above 2 GB. Under
Wine the game booted, reached the title, Continued, drew the 3D field (Route 101)
and ran the benchmark that way (keys by hand and the benchmark's own). The 32-bit
Linux build has always run with addresses above 2 GB (its stacks and mappings sit
at 0xE0000000 and up), which also exercises the game code with high addresses.
Not yet run on real Windows.

## Memory measured

| where | process RAM | of which private | GPU memory the game allocated |
| --- | --- | --- | --- |
| Linux, title screen | 169 MB | 86 MB | (2D only) |
| Linux, Lilycove overworld, Adventure camera | 200 MB | 107 MB | 34.6 MB |
| Linux, after a camera switch | 208 MB | 114 MB | |
| Linux, wild battle (Route 101) | 189 MB | 104 MB | 34.7 MB |
| Linux, benchmark Route 101 at 720p | 205 MB | 115 MB | 43.0 MB (7 MB render targets) |
| Windows exe under Wine, Route 101 | 300 to 340 MB | (Wine does not say) | 35.6 to 43 MB |

Most of the resident memory is the executable's own image (graphics, maps and
music compiled in: 75 to 85 MB file-backed) and the graphics driver; the game's
dynamic memory is small. GPU memory: textures 26 to 28 MB (atlases, sprites,
building pages, props art), vertex buffers 8 MB (terrain chunks, buildings, props),
render targets only when the scene is drawn offscreen (render scale, MSAA, a
resolution other than the window's).

The game's own heap (`gHeap`, the GBA engine's allocator, 113.2 KB): 11.5 to
20 KB in use in the overworld, **87.6 KB (77 %) during a wild battle**. This is
the engine's own limit (battle data and temporary sprite sheets come from it). It
is kept: the GBA build must stay byte-identical, the multiplayer trade replay
names the heap in a fixed descriptor, and one block's size field is 18 bits
(256 KB at most). Raising it for the native build to 240 KB is possible and is
the recommended next step if a 2v2 battle measures above about 90 %; the profile
log now reports its use and peak.

## What limits memory, and what was changed

| limit | from | kept or changed |
| --- | --- | --- |
| 2 GB address space | the exe flag | changed: 4 GB (large-address-aware) |
| Game heap 113 KB | GBA engine | kept (above); measured |
| 16 object events, 64 sprites, BG/OBJ VRAM | GBA engine | kept: game rules, part of saves and scripts |
| 49 x 49 cell window around the camera | renderer (snapshot) | kept: a view-distance choice, not memory; the distant scenery draws beyond it |
| Terrain chunk cache: 100 chunks, emptied at every map change | renderer | changed: 100 to 1024 chunks by the budget, kept across map changes (least recently seen evicted first) |
| Pixel objects 256 per sync, tree instances 32 per chunk, prop art pieces | renderer | kept: sized for the content with headroom; the props pass logs if its art texture fills |
| 16 nearest lamps | renderer (uniform array) | kept: lamps light by distance, no lamp has its own shadow |
| Snapshot exchange (3 snapshots of ~232 KB) | renderer | kept |

## Memory budget (implemented)

* Setting: F10 "Memory budget" and `memoryBudget=` in `pokeemerald.cfg`:
  automatic (an eighth of the PC's RAM, 256 MB to 1 GB), 512 MB, 1, 2, 4 or 8 GB.
* In effect: held to half the PC's RAM and to the address space free at startup
  less 768 MB for the game itself. On a 64-bit Windows PC with 16 GB that is about
  2.6 GB; the menu shows the budget in effect and the memory in use.
* What it sizes today: the terrain chunk cache (budget / 2 MB chunks, 100 to
  1024). Each chunk is one vertex buffer of about 100 to 250 KB of **graphics
  memory**. Nothing is allocated up front: chunks are built as places are seen and
  evicted least recently seen first when the cache is full.
* Effect measured: walking from Oldale Town back to Route 101, 47 of 49 chunks came
  from the cache (2 built; before this work all 49 were built at every crossing);
  in and out of Oldale's Mart twice, 49 of 49 each time. No stale chunk in the
  checking mode.
* RAM and VRAM are separate: the budget is not a promise of graphics memory. The
  driver's own figures are logged where it reports them (NVIDIA
  `GL_NVX_gpu_memory_info`, AMD `GL_ATI_meminfo`).

## 64-bit: what a conversion involves

Compile scan (all 450 C files of the 3D Windows build, x86_64-w64-mingw32,
`-Wpointer-to-int-cast -Wint-to-pointer-cast`):

| part | files | pointer/integer size warnings | errors |
| --- | --- | --- | --- |
| game (pokeemerald-expansion and our game code) | 394 | 1,004 | 43 (tileset_anims.c 32, multiplayer_trade_effects.c 7, multiplayer_save.c 2, recorded_battle.c 1, list_menu.c 1) |
| native platform layer | 24 | 17 | 12 (crash_report.c: x86 register names) |
| 3D renderer | 32 | 6 (all in the snapshot producer, scene_snapshot.c) | 0 |

Assembler data: **7,269 `.4byte symbol` pointer words in 1,135 data files**
(maps, events, scripts, sounds). The script engine reads them as 32-bit words
(`ScriptReadWord`, `T1_READ_PTR`, `T2_READ_PTR`); a 64-bit build needs every one
widened or turned into an offset, and every reader changed.

Struct layout (GBA vs a 64-bit build, `tools/pc_port/abi_layout.py` with a 64-bit
target): 15 types change size: MapLayout, MapHeader, MapEvents, MapConnections,
ObjectEventTemplate, CoordEvent, BgEvent, Tileset, Song, SongHeader, ToneData,
EnigmaBerry, EnigmaBerryInfo, an event union, and **SaveBlock1 (15,568 to
15,840 bytes)**. SaveBlock1 is the save file: a 64-bit build would have to keep
the 32-bit layout on disk explicitly or every existing save stops loading.
Unchanged: SaveBlock2, SaveBlock3, Pokemon/BoxPokemon, PokemonStorage, and every
multiplayer mailbox and battle packet (they hold no pointers).

Other interfaces:

* Python host and multiplayer: a loopback socket protocol of bytes; independent
  of the game's pointer size.
* SDL2: 64-bit builds exist (2.30.7 x86_64); OpenGL: the 64-bit opengl32.dll.
* The trade replay descriptor (32 bytes with two pointers) would change size.

Paths, from cheapest:

1. **Stay 32-bit, large-address-aware (done).** 4 GB of address space; the game
   needs ~0.2 GB.
2. **A 64-bit renderer process** fed the snapshots the game already produces (the
   renderer only reads them). Moderate work (shared memory, process start and
   loss handling); only worth it if the renderer ever needs more than ~2.5 GB.
3. **A staged engine port**: 32-bit pointer storage types for data built in
   assembler, explicit 32-bit save layout, the 43 + 12 errors and ~1,000 casts
   reviewed one by one. Weeks of work across the game code, with real risk to
   saves, scripts and multiplayer; not justified by any measurement.

Proof of concept (isolated, nothing shipped): the renderer's unit tests built as
64-bit Linux programs (`make -f Makefile_pc NATIVE_LINUX=1 DIORAMA=1
check-diorama DIORAMA_TEST_DIR=build/pc-tests64/diorama
"DIORAMA_TEST_FLAGS=-m64 -std=gnu99 -Wall -Wextra -Werror -O1 -DENABLE_DIORAMA
-iquote include" DIORAMA_TEST_SDL=pkg-config`): snapshot exchange, map
connections, presentation, metatile atlas, terrain mesh, sprite frames, weather,
camera (403 checks), 3DS trees, far field (54,618 checks), props (1,714 checks),
UI overlay, rules, and the compositor goldens (18,318 metatiles in 75 tilesets)
all compile without a warning and pass.

**Decision: no 64-bit conversion now.** Revisit only if a feature needs more than
~2.5 GB of renderer memory; then path 2.
