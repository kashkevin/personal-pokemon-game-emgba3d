# Diorama 3D vs the 3DS project: what we have, what is missing

Recorded 2026-10-09 for Milestone D (directive §15 item 7). Engine branch
`claude/native-graphics` at `65f44c42e`. Reference: ZallaxDev/pokeemerald-3Ds-dualscreen
`4a699e3` (`3ds_port/src/voxel/*`, `3ds_port/scripts/gen_voxel_*.py`). The 3DS
project's own README calls its voxel mode a work in progress ("Only some buildings,
trees, signposts and terrain relief are modelled today").

Status words follow `FEATURE_STATUS.md`: *Visually renders* means seen in screenshots
of the running game (Linux, and Windows under Wine), all on software OpenGL.

## Ported and visually rendering

| 3DS feature | Ours | Status | Notes |
| --- | --- | --- | --- |
| Buildings, furniture, hedges, railings modelled from their own drawing (`voxel_building.c`, `gen_voxel_buildings.py`) | Generator imported as `tools/diorama_buildings/`; 475 models, 136 pages, 3100 placements generated from our maps at build time; drawn by `gl_building_renderer.c` | Visually renders (Littleroot, Oldale Town, Oldale Pokémon Center, a house) | Coloured from the live palettes, so fades and the day/night tint reach them. The 3DS's railing footprint masks are not used. |
| Walkers drawn in front of the furniture they stand before (`ModelPush`) | Ported, plus an upright-card depth for the Diorama's leaning cards | Visually renders (counter, PC, house and Center walls, roof hiding a walker behind it) | Before this, the counter hid two thirds of a walker standing at it. |
| Fixed sun in the northwest, cast shadows, ambient 0.70 (`voxel_lighting.c`) | GPU shadow map (`gl_shadow.c`) for terrain, trees and buildings; one light sample per sprite | Visually renders | Different method: the 3DS bakes on the CPU. Off indoors and in rain/fog/ash/sand/overcast (as the 3DS effectively does), half strength at night (our own call, the 3DS has no clock). |

## Not ported yet (in rough order of value for the effort)

| 3DS feature | What it does there | Ours today | Effort |
| --- | --- | --- | --- |
| Doors on models (`PortDoor_Get`, `VoxelBuildings_DoorWall`) | An opening door is a black opening on the model's wall; the walker goes into the dark | The door animation plays only in the 2D view; in 3D the walker walks into a closed door before the warp | Small |
| Colour grade (`voxel_grade.c`) | 3D textures a little more saturated (1.30) | Not graded | Small (shader or atlas step, 3D only) |
| Cast sprite shadows (`voxel_entities.c`) | Each walker's own picture laid on the ground along the sun | The Diorama's round blob shadows | Small to medium |
| 3D signposts (`voxel_sign.c`) | Pixel-masked sign geometry, lamp heads | The Diorama's own sign handling | Medium |
| Tree style (`voxel_tree.c`) | Trunk plus a north-leaning cut-out crown textured from the tileset | The Diorama's voxel tree model | Medium; a look choice for the owner |
| Weather light (`ctr_voxel.c` `LightFor`) | Sun colour, haze, dappled light, rays, bloom, motes per weather | Weather particles only (the Diorama's rain/fog/ash) | Medium |
| Terrain relief read off the drawing (`voxel_relief.c`, `gen_voxel_relief.py`) | Cliffs, stairs, rocks at sea lifted to the height the art implies; everything on them lifted too | The Diorama's own rule-driven terraces, cliffs and ledges | Large: a second generator, lifting models and sprites, `CardPush` on stairs |
| 3D battle scenery (`voxel_battle.c`) | The map drawn behind the battle, low camera | 2D battle screen | Large |
| Camera options in the OPTION menu (angle, zoom) | Menu entries | The Diorama's pitch keys only; no menu entries | Small |

## Known visual issues of our own (see `KNOWN_ISSUES.md`)

- V1: the follower is refused during the Poké Ball animation frames.
- V3: frame rate on a real GPU is unmeasured; on software GL outdoors is about 7 fps.
- V5: the Diorama's 3D tree crowns stay brighter than the 2D view's night tint.
- A model with any cell in the scene is drawn whole, so one straddling the scene's edge
  can show over the dark (expected from the rule; not seen yet).

## Not going to be copied

The 3DS project's dual-screen interface (the directive keeps one screen), its 3DS-only
GPU code (Citro3D, PICA200 texel order, VRAM arena) and anything generated from a ROM
(`emerald3ds.pak`).
