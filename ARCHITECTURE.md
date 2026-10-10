# Architecture

Status: 2026-10-09. Two architectures exist side by side: the working emulator
build (fallback) and the native PC build being migrated to. Requirements are in
`PROJECT_SPEC.md`; progress in `FEATURE_STATUS.md`.

## 1. Emulator build (current fallback, `emulator-baseline-20261009`)

```
 player PC                                              host PC
 ┌──────────────────────────────────────────────┐      ┌─────────────────────┐
 │ customized mGBA 0.10.5 (native/windows-runtime)│      │ Python host         │
 │  ├ pokedev.gba  (engine repo, ARM)            │ TLS  │ (WorldServer,       │
 │  └ bridge/mgba.lua ── local TCP ──┐           │ JSON │  protocol 2,        │
 │                                    ▼          │◄────►│  SQLite stores)     │
 │                      Python companion ────────┼──────┤                     │
 │                      (src/emerald_multiplayer)│      └─────────────────────┘
 └──────────────────────────────────────────────┘
```

* **Engine**: pokeemerald-expansion 1.17.1 (`bb1093a7c`) plus project changes
  (`src/multiplayer_*.c` and edits across the engine), GEN_6 profile.
* **ROM ↔ companion**: EWRAM mailboxes (presence `EMP1`, save, battle, menu, reset,
  world `EMW1`), located through the ELF-derived `manifest.json`. The Lua bridge reads
  and writes them each frame and exchanges frames with the companion.
* **Companion ↔ host**: TLS JSON protocol 2. The host owns shared state (players,
  teams, trades, battles, world clock and events, friendship, wagers, saves,
  ownership) in SQLite.
* **Saves**: GBA 128 KiB flash image per character, plus host-side records.

## 2. Native PC build (target, branch `claude/native-pc`)

```
 player PC                                                 host PC
 ┌───────────────────────────────────────────────────┐    ┌──────────────┐
 │ pokeemerald-mp.exe (one process, no emulator)      │    │ Python host  │
 │  game thread: AgbMain (unchanged game C code)       │    │ (unchanged)  │
 │  main thread: SDL2 window/input/audio, frame pacing │TLS │              │
 │   ├ GBA PPU emulation renderer (2D, today)          │JSON│              │
 │   ├ Diorama renderer (3D overworld, Milestone D)    │◄──►│              │
 │   └ native bridge (C, Milestone C) ─ local TCP ─┐   │    │              │
 │                                                 ▼   │    │              │
 │                         Python companion (unchanged)┼────┤              │
 └───────────────────────────────────────────────────┘    └──────────────┘
```

* **Same game code**: the engine's C sources compile for 32-bit x86 with
  `-DPORTABLE` (`Makefile_pc`). Assembler data (maps, scripts, songs) is the same
  source converted to x86 syntax (`tools/pc_port/asm_to_x86.sed`). 32-bit is required
  because game data stores 32-bit pointers.
* **Platform layer** (`engine/src/platform/`, provenance in its README): SDL2 window,
  input, audio and timing; GBA PPU emulation (VRAM/OAM/palette/registers are ordinary
  arrays); DMA and BIOS calls in C; the m4a sound engine in C; flash save driver;
  host-clock RTC.
* **Threads**: the game runs `AgbMain` on its own thread and blocks in
  `VBlankIntrWait`; the main thread draws the frame, runs the VBlank interrupt
  handler and releases the game thread, so game memory is never touched by two
  threads at once.
* **Byte layout**: types that cross a boundary (save blocks, mailboxes, battle link
  packets, assembler-built map/sound data) keep the GBA layout via `ABI_ALIGN`,
  verified by `tools/pc_port/abi_layout.py`. Existing `.sav` files load unchanged.
* **Saves**: the same 128 KiB flash image, held in memory and written atomically
  (temp file + rename) at frame boundaries after any flash write; path via `--save`.
  Emulator `.sav` files load unchanged (the trailing mGBA RTC block is ignored).
* **Soft reset**: every game object's `.data`/`.bss` is moved into dedicated
  sections at build time; `game_memory.c` snapshots them just before the game thread
  starts and restores them when the game calls `SoftReset`, then restarts
  `AgbMain`. The window, audio device, save image, clock and (later) multiplayer
  bridge are in preserved objects and survive, as the cartridge does on a GBA.
  `check-game-sections` verifies the layout on both platforms.
* **Interrupts**: the GBA runs its VBlank interrupt in the middle of whatever the
  game is doing; natively it runs only between frames (in `VBlankIntrWait`). Game
  loops that busy-wait for interrupt work (the synchronous map loader waiting for
  DMA3 requests) call `Platform_SpinWaitForVBlank`, which ends the frame once a
  caller is clearly spinning, as a lag frame would on the GBA.
* **GBA-tolerated faults**: reads through NULL or far out of range are harmless on
  the GBA but fault natively. They are found with the NULL trap and UBSan builds
  and fixed in source under `PORTABLE` (KNOWN_ISSUES N1-N16); a crash writes
  `crash.log` with a stack trace.
* **Struct layout**: Linux i386 gcc and MinGW (with `-mno-ms-bitfields
  -mno-align-double`) both reproduce the GBA layout of every boundary type.
* **Native bridge** (Milestone C, not started): a C module in the platform layer
  replaces `bridge/mgba.lua`. It reads/writes the same mailbox structs directly in
  process memory and speaks the same local protocol to the existing companion, so
  the companion and host need no changes.
* **Renderer** (Milestone D, in progress on engine branch `claude/native-graphics`,
  build with `DIORAMA=1`): the voxel project's Diorama renderer (OpenGL 3.3 core).
  * *Snapshot*: hooks in `main.c` (frame begin/end), `overworld.c` (after the
    visible-spawn update) and `fieldmap.c` (map changed) copy what the 3D view needs
    on the game thread: metatiles and attributes around the camera, tileset graphics
    and palettes (so day/night tints and fades apply), object events with their
    current sprite frame, camera pan, weather. The snapshot is handed to the main
    thread through a double-buffered exchange; the renderer never writes game
    memory.
  * *Scene*: terrain mesh and voxel trees built from rule tables that
    `tools/diorama_rules` compiles from our own `data/maps`, `data/layouts` and
    tilesets at build time (classifying each metatile: ground, cliff, ledge, water,
    building part, tree, ...); objects are camera-facing sprites with shadows.
  * *Compositing*: the 2D GBA frame (text boxes, menus, map-name popup, battles) is
    drawn over or instead of the 3D view; battles and full-screen menus stay 2D. F4
    switches to the classic 2D view at any time.
  * *Pacing*: one presented frame per loop; when a frame takes longer than about 83
    ms (below 12 fps) the game advances one frame per presented frame, so a slow GPU
    slows the game instead of skipping input.
  * *Modelled buildings* (D4, from ZallaxDev/pokeemerald-3Ds-dualscreen): its
    generator (`tools/diorama_buildings`) models every house, Center, Mart, lab and
    piece of furniture from its own drawing at build time; `buildings.c` reads the
    table, `gl_building_renderer.c` draws the placements of the maps in the scene
    with the live BG palettes. Cells a model owns become flat ground for the
    Diorama's own terrain, so it does not extrude them a second time.
  * *Sprite depth*: sprite cards lean back to face the camera, but write the depth
    of an upright card at their feet, so everything north of the feet is behind a
    walker and everything south in front, as on the GBA; furniture whose model
    comes forward of the feet moves that upright stand-in in front of its face
    (the 3DS project's `ModelPush`).
  * *Sun shadows* (`gl_shadow.c`): a 2048x2048 depth map from a fixed sun in the
    northwest (the 3DS project's sun), drawn again only when its square steps or
    the terrain/buildings change; terrain and buildings are lit per pixel, a
    sprite from one point over its feet. Strength from the snapshot: none indoors
    or in bad weather, half at night.
  * Still to port from the 3DS project: `docs/diorama-3ds-gap-analysis.md`.
* **No GBA Wireless Adapter**: the wireless library is never set up natively;
  anything that would scan for adapter players (the Pokémon Center Union Room scan)
  is skipped under `PORTABLE` (KNOWN_ISSUES N24).

## 3. Boundaries (rules)

| Concern | Authoritative owner | Never decided by |
| --- | --- | --- |
| Pokémon, items, money, progress of one player | that player's game save (engine) | renderer, companion |
| Shared world: clock, World Events, claims, teams, friendship, wagers, trades, battle admission/results | Python host | game client alone, renderer |
| Battle simulation | engine battle code (link-battle master) | renderer, host (host validates/records) |
| How the game looks (2D/3D, camera, shadows, lighting) | platform renderer | — it only reads a snapshot of game state |
| Persistence | save flash image (per character) + host SQLite | renderer |

## 4. Repositories

* App repo (`/home/claude/pokemon`): host, companion, Lua bridge, Windows emulator
  runtime sources, launcher, proofs, tests, docs.
* Engine repo (`/home/claude/engine`): the game (GBA build via `Makefile`, native
  build via `Makefile_pc`), platform layer, PC-port tools.
