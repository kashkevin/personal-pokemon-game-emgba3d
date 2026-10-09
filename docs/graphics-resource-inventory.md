# Graphics inventory and visual reuse review

October 9, 2026. This is the starting asset audit required by the
[visual/world amendment](project-update-maximum-visuals-visible-wild-riding-time.txt).
Existing art is preserved. No community art, ROM or graphics dependency was
downloaded into the project or incorporated by this review.

## Reproducible existing inventory

[`graphics-file-inventory.json`](graphics-file-inventory.json) records **21,915
tracked files / 12,190,419 source bytes** under native `graphics/` and
`data/tilesets/`, including each relative path, size, SHA-256 and PNG dimensions.
The [generated summary](graphics-file-inventory.md) groups them and lists both
player state sheets. Source-byte size is not ROM or VRAM usage. The native base
is `aef47e4b28fd6d0e84376961e0cc6632996bb0be`, inherited RHH revision
`bb1093a7c72d3961d9a37d8e02ad2abc2c866682` plus project changes. The inventoried
art/tileset paths had no tracked or untracked changes. Ignored build products
are excluded; relevant current animation/configuration source hashes are also
recorded, so the base revision is not presented as the entire modified engine.

Generate with the existing Python/Git installation, substituting the engine
checkout and output paths:

```text
python scripts/inventory_graphics.py --engine ENGINE --json docs/graphics-file-inventory.json --markdown docs/graphics-file-inventory.md
```

Add `--check` to recompute and compare both outputs without writing them. This
checks reproducibility and file identity, not visual quality, palette correctness
or runtime animation. It does not import application code or edit engine files.

| Existing area | Evidence and interpretation |
| --- | --- |
| Pokémon battle/overworld art | 14,218 files under `graphics/pokemon`. Standard IDs 1–721 are enumerated independently from `include/constants/species.h`; 687 match direct directory names. The remaining 34 are explicitly listed form-qualified names such as `CASTFORM_NORMAL` and `MEOWSTIC_M`. They are unresolved directory mappings, **not 34 missing Pokémon**. Every candidate file is inventoried; complete Gen1–6 form/palette/animation coverage remains UNKNOWN. |
| Player/NPC objects | 501 files under `graphics/object_events`; current Brendan and May each have walking, running, both bikes, surfing, fishing, field move, watering, underwater and decorating sheets. Trainer battle art has 285 files. These are existing assets, not a component-based customization system. |
| Terrain/buildings | 2,804 tracked tileset files include tiles, palettes, animations, metatiles and their attributes. Collision/priority data are retained. No Hoenn redesign or authored depth pass has been applied. |
| Effects/environment | 683 battle-animation assets, 99 field-effect assets, 85 door-animation assets, 22 weather assets, 65 battle-environment assets and 55 battle transitions. File presence alone does not verify a specific effect under multiplayer. |
| Trade/evolution/UI | Existing trade, evolution, party, storage, summary, fonts, windows and other interface groups are enumerated separately. Their art does not establish that the new trade effect scene or all user flows run. |

## Player animation paths and first reuse

`src/data/object_events/object_event_graphics.h` concatenates the 144×32 walking
and 144×32 running PNG-derived tiles for each normal player. These are sheets,
not 144-pixel-wide actors: `object_event_graphics_info.h` uses the normal 16×32
player layout, with frame/picture tables in the adjacent object-event headers.
`src/field_player_avatar.c:PlayerRun` calls `GetPlayerRunMovementAction`;
`src/event_object_movement.c:StartRunningAnim` chooses the running-direction
animation and native movement speed. This supports reusing the existing run
frames rather than replacing art.

| Requested animation/state | Existing source evidence | Current multiplayer qualification |
| --- | --- | --- |
| Idle, turn, walk, run | Normal player sheet, object-event animation table; `PlayerFaceDirection`, `PlayerWalkNormal`, `PlayerRun` | Dedicated remote run propagation is now implemented. The separate [running proof](remote-running-animation.md) records two real cores and all four Brendan directions, walking/stop recovery and unchanged saves. |
| Mach/Acro bike | Separate 288×32 / 864×32 sheets and native state graphics selection | Full bike trick/direction/transition peer presentation UNKNOWN. |
| Surf/underwater | Separate 192×32 / 128×32 sheets and state graphics selection | Existing asset/runtime hooks only; full remote transition/load/palette qualification UNKNOWN. |
| Fishing | 384×32 sheets plus field-player fishing tasks | Full cast/splash/wait/bite/reel sequencing, peer visibility and cancellation UNKNOWN. |
| Ledges, doors, item/field actions | `PlayerJumpLedge`, native object movement/door effects, field-move/watering sheets | These need state-by-state qualification; not every action has its own sheet. |
| Battle/trade presentation | Existing native scenes and battle/summary/trade/evolution asset groups | Refer to exact battle/trade evidence; this inventory grants no new acceptance. |

The root agent visually inspected the existing Brendan run sheet and four actual
native observer captures. This inventory reads dimensions and code; it does not
claim visual inspection of all sheets, motion quality, or superiority to an
external art set. May and customized avatars remain outside that run proof.

## Already available engine systems and constraints

Current `include/config/overworld.h` has Pokémon object graphics enabled,
compressed overworld graphics enabled, followers disabled, shared battle/follower
palettes disabled with an upstream WIP warning, local day/night tint enabled and
time-dependent encounter tables disabled. `include/config/wild_encounter.h` keeps
traditional encounters enabled and visible overworld encounters disabled. Its
OWE comment recommends disabling graphics compression to prevent VRAM issues.
These exact definitions are copied as metadata in the inventory, not changed.

The engine already includes `follower_helper.c`, `follower_npc.c`,
`wild_encounter_ow.c`, `tileset_anims.c`, field effects, weather and palette
handling. Enabling them globally would not supply synchronized followers,
host-owned visible spawns, catch/defeat/run/disconnect arbitration, persistent
shared time or ride ownership. Existing local time tint is not the shared clock.

The current source has `MAX_SPRITES = 64` (`include/sprite.h`), and its all-object
shadow option documents two sprites per object. Object/palette/VRAM budgets must
include four players, shadows, followers, visible encounters and weather together.
The latest isolated visual build uses 235096/262144 EWRAM and 28376/32768 IWRAM
bytes; those linker figures are recorded with the [exact ROM proof](remote-running-animation.md).
They are not frame-time measurements. Peak frame time, sprite/palette exhaustion,
network load and memory cost of the requested combined world remain UNKNOWN.

## External references, checked October 9

Read-only GitHub repository/commit/tree APIs established the revisions below;
the trees were not truncated and all three repositories were unarchived. GitHub
reported no detected repository license. A tool subdirectory's license does not
license all artwork or game code. Preserve upstream credits and establish each
selected component's permission before copying; artist identity is UNKNOWN where
the inspected source does not map a file to a creator.

**Maintained RHH expansion:** current master
[`7b95be15d84a053948791ce91e5dec0b168947a5`](https://github.com/rh-hideout/pokeemerald-expansion/commit/7b95be15d84a053948791ce91e5dec0b168947a5),
October 8. Its latest commit repairs wild held-item restoration; this project
has not merged it. Existing RHH interfaces are the closest reuse target because
the project already derives from them. Current upstream still defaults followers
off and local tint on. Review a targeted upstream fix against our held battle,
trade, reset and saved ownership changes; wholesale replacement would discard
project integrations. Current credits are in `CREDITS.md` and `docs/CREDITS.md`.
[Upstream source](https://github.com/rh-hideout/pokeemerald-expansion),
[pinned overworld configuration](https://github.com/rh-hideout/pokeemerald-expansion/blob/7b95be15d84a053948791ce91e5dec0b168947a5/include/config/overworld.h).

**Modern_Emerald:** main
[`ff218fcf18679e87e61a2b2523c83aa9e3f0df69`](https://github.com/Mickosis/Modern_Emerald/commit/ff218fcf18679e87e61a2b2523c83aa9e3f0df69),
September 18. The Emerald Legacy derivative advertises 386 followers, normal/shiny
overworld art, dedicated surfing species and visible wild encounters. Its latest
fix concerns OWE despawn reentrancy and reflection palettes. Credits identify
Exclsior and other contributors for followers/surfing and Bivurnum/HashtagMarky
for OWE/speed work. It also changes gameplay and describes a Gen3 basis, so it
cannot replace this Gen6 multiplayer engine. Prefer examining individual fixes
and art layouts; its local encounter RNG/object logic needs host claim and save
adaptation. No actual motion/quality or performance comparison was run.
[Project/credits](https://github.com/Mickosis/Modern_Emerald),
[pinned OWE implementation](https://github.com/Mickosis/Modern_Emerald/blob/ff218fcf18679e87e61a2b2523c83aa9e3f0df69/src/wild_encounter_ow.c).

**EmceeMikey/pokeemerald:** master
[`080c75860eb4cf8164bf7ac20eb691eb538250a7`](https://github.com/EmceeMikey/pokeemerald/commit/080c75860eb4cf8164bf7ac20eb691eb538250a7),
September 19. The README describes 386 HGSS-style followers, dynamic palettes,
reflections, optional Gen6-style icons and lighting branches; it claims vanilla
save/object-size compatibility. The queried branch list did **not** contain the
README's named `followers-expanded-id` or `lighting-expanded-id` branches, so
those descriptions are not proof of a currently selectable branch/pin. Master
is pinned separately. Even the stated vanilla compatibility does not establish
compatibility with this project's expanded save, dynamic actors or multiplayer.
It is a reference for follower pose/palette behavior, not a verified Gen1–6 pack
or an approved import. Comparative quality and frame cost remain UNKNOWN.
[README and advertised branches](https://github.com/EmceeMikey/pokeemerald),
[actual branch API](https://api.github.com/repos/EmceeMikey/pokeemerald/branches?per_page=100).

**Gen VI DS-Style 64×64 resource:** MrDollSteak's
[primary resource thread](https://www.pokecommunity.com/threads/gen-vi-ds-style-64x64-pokemon-sprite-resource.314422/)
lists Gen6 front/back sprites, icons and Mega entries, with a detailed contributor
list. It permits hack reuse with credit to the thread; named outside contributors
require permission evidence under its contribution rules. It is not a blanket
license for every linked image. The thread has no immutable asset manifest or
commit pin; individual image hashes and permission/artist records are required
before selection. Static 64×64 battle artwork does not supply directional follower,
mount or multi-frame battle animation sheets. No linked art was downloaded,
visually compared or imported here; current-link availability, per-file palette
fit, motion quality and completeness remain UNKNOWN.

## Selection and implementation order

Reuse the current engine's art/layout and native animation functions first; the
completed remote running slice demonstrates that path. Next, define one bounded
synchronized entity representation and explicit spawn/claim outcomes before
adapting existing OWE or follower logic. Resolve shared encounter RNG/Charm rules
with the owner, then measure real four-client object/palette/frame budgets. Keep
world clock persistence and Gen6 time rules explicit rather than inheriting
`GEN_LATEST` settings. Stage ground mounts and map depth/lighting passes after
those foundations. Each selected asset requires a before copy, exact creator and
terms, source/converted hashes and an in-motion check in the actual engine.

No wholesale engine/asset replacement, new graphics pack, synchronized follower,
mount, shared wild encounter or shared clock is claimed by this audit.
