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
| Doors on models (`PortDoor_Get`, `EmitDoor`, `DoorLight`, `VoxelBuildings_DoorWall`) | Ported (graphics `398d486ef`); scripted scenes and fades now stay in 3D so the door is seen | Visually renders (Birch's lab, in and out, at night) | Swinging doors open too (the 3DS shows sliding ones only); no opening on an unmodelled building. |
| Colour grade (`voxel_grade.c`) | Ported (graphics `0d10b9936`): saturation 1.30 in the terrain, building and sprite shaders | Visually renders | `PKMN_DIORAMA_GRADE=0` to compare. |
| Cast sprite shadows (`EmitCastShadow`, `voxel_entities.c`) | Ported (graphics `fde3a5741`): the sprite's silhouette along the sun, dark blue, alpha 0.36 x sun x light on the walker | Visually renders (Littleroot by day) | Flat ground only; the round shadow stays where there is no sun. |
| Weather light (`ctr_voxel.c` `LightFor`, `FogLight`, `SetGrade`; `voxel.v.pica`) | Ported (graphics `23ad56924`): tint by brightness (cool at 0.62 or below, warm in full sun) and distance haze, per weather; neutral in buildings and secret bases | Visually renders (Littleroot by day and night; rain, fog and ash previewed) | Per fragment instead of per vertex; the haze colour follows the night tint and fades. |
| Sun dapples, sunlit dust, sun rays (`ctr_voxel.c`), bloom (`3ds_video.c`) | Ported (graphics `8920f1f67`): `gl_light.c` (dapples), `gl_air.c` (dust, rays, bloom) | Visually renders (Littleroot by day) | Dust kept inside the scene's 33x33 cells and rays only over the scene, because our wider camera shows the dark past the cells; at night dapples halve and there are no rays or dust (our call: the 3DS has no clock). |
| Tree style (`voxel_tree.c`, its own tree art) | Ported as an option (graphics `633be85c6`, `PKMN_DIORAMA_TREES=3ds`) | Visually renders (Littleroot, Dewford Town, Route 104) | The voxel trees stay the default until the owner picks; the 3DS trees are much cheaper to draw. |
| Fog banks and a cave's gloom (`ctr_voxel.c` `MakeFog`, `DrawFogBanks`, `MakeGloom`) | Ported (graphics `617e005d7`) in `gl_air.c`, replacing the flat fog overlay in 3D | Visually renders (Mt. Pyre summit, Rusturf Tunnel) | The banks fade out before the scene's cells end, like the dust. |
| Fixed sun in the northwest, cast shadows, ambient 0.70 (`voxel_lighting.c`) | GPU shadow map (`gl_shadow.c`) for terrain, trees and buildings; one light sample per sprite | Visually renders | Different method: the 3DS bakes on the CPU. Off indoors and in rain/fog/ash/sand/overcast (as the 3DS effectively does), half strength at night (our own call, the 3DS has no clock). |

## Not ported yet (in rough order of value for the effort)

| 3DS feature | What it does there | Ours today | Effort |
| --- | --- | --- | --- |
| 3D signposts (`voxel_sign.c`) | Pixel-masked sign geometry, lamp heads | The Diorama's own sign handling | Medium |
| Terrain relief read off the drawing (`voxel_relief.c`, `gen_voxel_relief.py`) | Cliffs, stairs, rocks at sea lifted to the height the art implies; everything on them lifted too | The Diorama's own rule-driven terraces, cliffs and ledges | Large: a second generator, lifting models and sprites, `CardPush` on stairs |
| 3D battle scenery (`voxel_battle.c`) | The map drawn behind the battle, low camera | 2D battle screen | Being done separately (owner, 2026-10-10): not in this branch's plan |
| Camera options in the OPTION menu (angle, zoom) | Menu entries | The Diorama's pitch keys only; no menu entries | Small |

## Known visual issues of our own (see `KNOWN_ISSUES.md`)

- V1: the follower is refused during the Poké Ball animation frames.
- V3: frame rate on a real GPU is unmeasured; on software GL outdoors is about 7 fps.
- V5 (fixed `398d486ef`): the voxel tree model's colours now follow the night tint and fades.
- A model with any cell in the scene is drawn whole, so one straddling the scene's edge
  can show over the dark (expected from the rule; not seen yet).

## Not going to be copied

The 3DS project's dual-screen interface (the directive keeps one screen), its 3DS-only
GPU code (Citro3D, PICA200 texel order, VRAM arena) and anything generated from a ROM
(`emerald3ds.pak`).
