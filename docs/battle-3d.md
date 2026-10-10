# 3D battles (the Emerald 3DS battle scene on one PC screen)

Recorded 2026-10-10. Owner directive: "INTEGRATE EMERALD 3DS BATTLE GRAPHICS ONLY"
(reuse ZallaxDev/pokeemerald-3Ds-dualscreen's 3D battle presentation in the native
Windows game, single screen, graphics only: no move-animation, battle-engine or
mechanics changes).

## Where it is

| Engine branch | Base | Commits | What |
| --- | --- | --- | --- |
| `claude/battle-3d` | `claude/native-graphics` `b02cf0e97` | `5a4772ff0` 3D battles; `31d15a804` four native NULL faults; `dce1a991a` Windows build fix; `02d580fe1` Poké Ball crash; `68669dd62` Trainer Card crash; `b752d8e48` stage search sees the voxel trees | The port, on the overworld as it was when this work started |
| `claude/battle-3d-integration` | `claude/native-graphics` `8920f1f67`, then `3e39f2b15` merged in (the other graphics session's newest, checkpoint `native-wip-20261010-3`) | `6caa1922c` merge; `0c553430e` integration; `177efdefc` battle transitions over the 3D field; `f1e5f5ea3`, `a5e3aa903`, `925b47933` (the three fixes above); `e7f6285f5` merge of `3e39f2b15` (four conflicts, resolved by hand); `732fbef43` 3DS trees in battles | **Current line**: the 3D battles on the newest 3D overworld (doors, fades in 3D, weather light, fog banks, dark caves, F7 camera and F8 trees) |

Local tag `battle3d-integ-on-8920f1f67` (`925b47933`) marks the integration before
`3e39f2b15` was merged. Neither branch is merged into `claude/native-graphics` or
`claude/native-pc`; the other session's overworld work is untouched (its branch was
only read, from the checkpoint bundles). Files and provenance: engine
`src/diorama/README.md` ("3D battles"). Compiled only with `DIORAMA=1`; the GBA ROM
is unchanged (`f214735b…3387`).

## What the player sees

* A battle started from the 3D view (walking into a visible wild Pokémon, a random
  encounter, a trainer spotting the player, a scripted battle) keeps the 3D world:
  the battle transition plays over the 3D field (its waves, slices, bars and flashes
  move and tint the 3D picture as they did the flat one), then the camera glides from
  the field's view down to the battle's (the 3DS camera: crane up, dolly zoom, a push
  and a short quake on landing, speed lines, vignette, cinema bars, a flash).
* The battle is drawn on the map where it started: the 3DS stage search picks a spot
  within 6 tiles of the player where both sides stand on fitting ground (grass for a
  wild Pokémon met in grass, sand on a beach, water when surfing) with nothing tall in
  front of them (buildings, the voxel trees as the model stands, the 3DS trees'
  crowns) and as little of the dark past the map as possible.
* The battle's own picture is unchanged and drawn over the world: the Pokémon sprites
  (front/back, shiny, Mega forms, every species the game has), healthboxes, text box,
  move/bag/party/run menus, Mega trigger, status and stat effects, move animations
  and sounds. Only the scenery layer (BG3) is replaced by the world, pixel for pixel,
  with the GBA's own blending and brightness against it kept (a move that darkens or
  tints the background darkens or tints the world; one that shakes it shakes the
  camera). A move that loads its own background (Psychic, Surf, terrains...) shows
  that background as it is, then the world comes back.
* Soft contact shadows under the battlers (the opponent's Gen 4 style shadow sprite,
  when the game draws one, is kept instead).
* Single screen: the battle picture at the 3D view's usual size on the bottom edge,
  the world filling the whole window above and beside it; the scenery's colour at the
  picture's edges is carried out to a wide window's sides (curtains and fades reach
  the whole window).
* The overworld's looks carry into the battle: the trees the player chose with F8
  (voxel or 3DS) stand in the battle's world; the sun, shadows and weather light are
  the field's. The F7 camera choice only changes the field's view, so the glide
  starts from whichever framing the field shows. A dark cave's battle shows the cave
  lit, as the GBA's cave battle background is; the transition into it plays over the
  dark field. Fog banks stay out of the battle (the GBA battle has no fog either).
* After the battle the field fades back in in 3D, its camera where it was.
* F4 switches between the 3D and the classic view at any time, also in the middle of
  a battle (no second glide).

Switches (environment variables, for tests): `PKMN_DIORAMA_BATTLE=0` every battle 2D
as before; `PKMN_DIORAMA_TRANSITION_2D=1` battle transitions in 2D as before;
`PKMN_DIORAMA_BATTLE_KEEP=0` world redrawn every frame (see Performance);
`PKMN_BATTLE3D_PITCH`, `_DISTANCE`, `_FOCAL`, `_ROW` camera tuning;
`PKMN_DIORAMA_LOG=1` logs the stage choice with a map of the ground round the player.

## How it works (engine)

* `battle_capture.c` reads the game at the frame boundary (game thread parked):
  battle flags, whether BG3 holds the scenery (`LoadBattleEnvironmentGfx` /
  `LoadMoveBg` hooks), the intro slide, BG3 scroll, the scenery palettes' fade
  (least-squares fit, the 3DS port's), the battlers' shadow positions, which OAM
  entries are map sprites. It writes nothing.
* `gba_easy_draw.c` (the software GBA renderer) draws the scenery layers
  see-through and records per pixel how much of the world shows (0..16, the GBA's
  own alpha/brightness blend), per line the edge colours, and per line how far a
  transition moved the field's layers. The picture is uploaded with that cover as
  premultiplied alpha.
* `gl_battle.c` draws the world from the battle camera with the Diorama's terrain,
  trees (voxel or 3DS), buildings, sun shadows and weather light (a camera rig sets
  the eye; with the rig off every shader uses the field's values, so the overworld
  draws exactly as before), then the fade, shadows, intro effects, the carried-out
  edges and the picture. The world is copied once drawn and reused while the camera
  stands still (all of a battle except the glide and scenery shakes).
* The battle stands on the field as last seen with steady palettes (the compositor
  keeps that snapshot), so a battle starting mid-fade still gets the full-colour
  world.

## Tests run (cloud workspace: Mesa llvmpipe, 2 cores, 960x540 window)

Test build: the same sources with the expansion's debug menu compiled in
(`DEBUG_OVERWORLD_MENU`, start-menu entry; build command in `TEST_PLAN.md`), for
testing only, never for players (player builds keep the debug menus compiled off,
`docs/player-build-guard.md`), used to warp, give Pokémon/items and start trainer
battles. Saves: the
owner-like progression save `lab.sav`, plus the debug menu's "Cheat start". Caveat:
the debug menu's "Try Battle" does not lock the field, so a visible wild Pokémon
spawning or walking into the player during its transition empties the opponent's
party or starts a wild battle instead (KNOWN_ISSUES N33, test build only); trainer
battles from the debug menu were therefore started in a town.

`claude/battle-3d` build:

| Check | Result |
| --- | --- |
| Wild battle near Littleroot (Route 101), walking into a visible Shinx in the 3D view | Pass: glide, intro, send-out, Fight (Scratch), damage both ways, Bag opened and closed, party opened and closed, F4 to classic and back mid-battle, Run, field faded back in 3D |
| Catch | Pass: Poké Ball thrown, caught, Pokédex page, nickname declined, back to the 3D field |
| Shiny Pokémon | Pass: shiny Gardevoir's sparkles on send-out over the world |
| Mega Evolution | Pass after fixing a native crash (KNOWN_ISSUES N26): Mega trigger, Gardevoir Mega Evolved, the animation over the world, Future Sight |
| Trainer battle | Pass: rival May on Route 101 (intro slide, send-outs, switch to Wailord, attacks, victory, prize money, return) |
| Double battle | Pass: Kate & Joy on Route 101: four battlers with their shadows, Surf hitting both opponents, victory, return |
| Defeat | Pass: Drake against a level 2 Magikarp: defeat, blacked out, home in Littleroot (3D) |
| Terrain types | Pass (stage log `wants` = ground kinds): grass (Route 101), sand (Route 109 beach), water (surfing on Route 109), cave (Granite Cave 1F), indoors (Rustboro Gym, Roxanne) |
| Return to the overworld | Pass after every battle above (run, catch, win, double, defeat) |
| Save and reload | Pass: saved on Route 101 with the 3D build, reloaded (several times, by both branches' builds), battled in 3D |
| Windows build | Pass under Wine (the `claude/battle-3d` exe): Route 101 save, wild battle in 3D, Run, back to 3D |

`claude/battle-3d-integration` build (on `8920f1f67`, then on `3e39f2b15`):

| Check | Result |
| --- | --- |
| Battle transitions over the 3D field | Pass: the wild battle's slices and Drake's white bars over the 3D field, then the glide |
| Catch (bag item in battle) | Pass after fixing a native crash (KNOWN_ISSUES N31); again after the merge with the R quick-throw: Caterpie caught with the 3DS trees on |
| F4 into 3D mid-battle | Pass: the stage is chosen then, no glide |
| Trainer battle | Pass: Drake to the end |
| Stage search and trees | Pass after a fix (`b752d8e48`): on Route 101 the double battle had put Kate & Joy behind a voxel tree drawn under them (a one-row tree's crown stands on the row above its trunk); now they stand in the grass with the trees behind. With the 3DS trees (F8) the crowns are seen as tall too (stage map log) |
| Double battle with Mega Evolution and an item | Pass: Kate & Joy in Oldale Town: Gardevoir Mega Evolved (animation over the world), Potion from the Bag on Gardevoir through the party menu ("Gardevoir had its HP restored"), Surf, Teeter Dance and confusion, victory, prize, back to the 3D field |
| After merging `3e39f2b15`: wild battle, voxel trees, wide camera | Pass: Route 101, glide, shiny Gardevoir's send-out, Run, back to 3D |
| After merging: 3DS trees (F8) and 3DS camera (F7) | Pass: the 3DS trees stand in the battle's world (drawn with the battle camera), glide from the close framing, catch, back to the 3D field |
| After merging: dark cave | Pass: Granite Cave B1F (no Flash): the transition over the dark field, the battle's world lit like the GBA's cave background, Run, back to the dark field with its circle of light |
| Trainer Card | Pass after fixing a native crash on closing it (KNOWN_ISSUES N32) |
| Unit tests | `check-diorama` passes on both branches, including the stage-search tests (open field, wall in front, surfing, indoor corner) |
| GBA ROM | `pokedev.gba` sha256 unchanged (`f214735b…3387`) on both branches |

Not tested: multiplayer battles (1v1, 2v2, co-op, Twin Gym Leaders, Championship)
in the native build - their transport is Milestone C3, not done yet; the 3D
presentation only reads the battle and does not take part in it (link battles keep
their VS intro on BG1/BG2). Battles on a real graphics card and at 1920x1080 on a
real display (see Performance). Flash being used in a dark cave before a battle.

## Performance

Software OpenGL here, 960x540: in a battle 60 game frames a second with about 200
presented (the world is copied, not redrawn: e.g. "world drawn 90 times, kept 8881"
in one wild battle); the glide's 1.5 s redraws the world every frame and runs at the
3D field's own rate (about 5 frames a second on this machine; the game slows with it,
by design). A real GPU has not been measured (KNOWN_ISSUES V3); the battle adds no
cost beyond the field's for the glide and almost none afterwards.

## Remaining visual problems (in rough order)

1. The stage can be a few tiles from where the player stood (the 3DS scoring:
   fitting ground and a clear view beat distance); in cramped rooms (Rustboro Gym)
   no spot is clear and the view may show walls close behind the opponent.
2. Indoors and in caves the view may show black past the room's or cave's edge
   at the top corners (scored, not prevented).
3. Animated tiles (water, flowers) stand still during a battle: the battle uses the
   field's last snapshot.
4. The map's people and Pokémon are not drawn in the battle's world (the 3DS world
   leaves them out too).
5. During a battle transition the map's sprites move with the 3D field's bands
   (on the GBA they stay put while the background slices); the 3DS port does the
   same.
6. If the 3D field cannot be drawn on the first frame of a transition (a frame the
   field refuses), that one frame shows the field's layers black.
7. Large Pokémon sprites are positioned by the battle's fixed GBA coordinates; the
   world under them is matched by projection, so a tall sprite can look as if it
   floats a little above uneven ground.
8. The stage search sees each tree as a box of the crown's height (the 3DS trees'
   leaning crowns are approximated); a crown's edge can still reach a battler's
   picture by a few pixels.
9. Camera framing in battles is the 3DS project's; the field's framing (F7, KNOWN_ISSUES
   V8) is the owner's choice.
