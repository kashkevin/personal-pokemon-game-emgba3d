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
* **Soft reset** (in progress): game globals are grouped into dedicated sections so
  a reset restores them in-process while the window, audio device, save image and
  multiplayer bridge survive, matching what the GBA cartridge keeps.
* **Native bridge** (Milestone C, not started): a C module in the platform layer
  replaces `bridge/mgba.lua`. It reads/writes the same mailbox structs directly in
  process memory and speaks the same local protocol to the existing companion, so
  the companion and host need no changes.
* **Renderer** (Milestone D, not started in this engine): the voxel project's
  Diorama renderer (OpenGL 3.3) builds a 3D scene from a per-frame snapshot of the
  game state (map, metatiles, object events, camera) and composites the 2D GBA frame
  for UI. 3DS-only features (buildings, relief, trees, lighting, shadows) are ported
  from ZallaxDev/pokeemerald-3Ds-dualscreen's portable C modules; its Citro3D
  backend is rewritten for OpenGL.

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
