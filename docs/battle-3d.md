# 3D battles (the Emerald 3DS battle scene on one PC screen)

Recorded 2026-10-10. Owner directive: "INTEGRATE EMERALD 3DS BATTLE GRAPHICS ONLY"
(reuse ZallaxDev/pokeemerald-3Ds-dualscreen's 3D battle presentation in the native
Windows game, single screen, graphics only: no move-animation, battle-engine or
mechanics changes).

## Where it is

| Engine branch | Base | Commits | What |
| --- | --- | --- | --- |
| `claude/battle-3d` | `claude/native-graphics` `b02cf0e97` | `5a4772ff0` 3D battles; `31d15a804` four native NULL faults; `dce1a991a` Windows build fix; `02d580fe1` Poké Ball crash; `68669dd62` Trainer Card crash; `b752d8e48` stage search sees the voxel trees | The port, on the overworld as it was when this work started |
| `claude/battle-3d-integration` | `claude/native-graphics` `8920f1f67`, then `3e39f2b15` merged in (the other graphics session's checkpoint `native-wip-20261010-3`) | First round: `6caa1922c` merge; `0c553430e` integration; `177efdefc` battle transitions over the 3D field; `f1e5f5ea3`, `a5e3aa903`, `925b47933` (the three fixes above); `e7f6285f5` merge of `3e39f2b15` (four conflicts, resolved by hand); `732fbef43` 3DS trees in battles (tag `battle3d-wip-20261010-1`). Second round: `389d744b6`, `fae86b6c1` PC box crashes (N35, N36); `79fc306f3` field tile animations into a copy; `90c15d594` the GBA renderer keeps the scenery's own picture; `13fea91ef` transition mosaic captured; `ae08acbf3` stage search measures what the camera sees; `0fa2bf87a` water and flowers, scenery past a room's edge, transitions (tag `battle3d-wip-20261010-2`) | The 3D battles' working line |
| `claude/native-graphics-3d-battles` | `claude/native-graphics` `edd1f5105` (`graphics-wip-20261010-4`, the newest 3D overworld: 3DS camera and trees as defaults, live-save pacing, XInput at run time) | `7bf42d267`: merge of `claude/battle-3d-integration` (no conflicts) | First merge candidate (second round), superseded by the third below |
| `claude/native-pc-box-fixes` | `claude/native-pc` `1579e7fd8` | `ae6533e25` opening the PC's boxes crashed (N35); `aa2841d7a` leaving them crashed (N36) | The two crash fixes found since the first round, for the 2D game; merges cleanly into `claude/native-graphics` too. `claude/native-pc` itself was fast-forwarded to `aa2841d7a` on 2026-10-10 (the owner's go); tag `native-wip-20261010-4` stays on `1579e7fd8` |
| `claude/native-graphics-3d-battles-2` | `claude/native-graphics` `b86ea813a` (`graphics-wip-20261010-5`, the resolution work) | `7a9ca1e42`: merge of `claude/battle-3d-integration` | Second merge candidate, superseded |
| `claude/battle-3d-next` | `7a9ca1e42` | Third round: `061dcaf1b` a move's own background past the picture (V13); `e1903a302` water and flowers paced by measured frame times; `f671c8dd1` the world at the render size and antialiasing the display settings choose; `1efe205dc` a move's background repeated only where the move filled it, or mirrored; `1ee0245ce` Diorama README; `7fc944377`, `5c897ff7c` log lines (the graphics card and the 3D view's size) | The 3D battles' working line since the third round |
| `claude/native-graphics-3d-battles-3` | `claude/native-graphics` `6743bc1e5` (`graphics-wip-20261010-6`: the Adventure and Diorama cameras, photo mode, the 49 x 49 scene) | `2a368fd8d`: merge of `claude/battle-3d-next`; two conflicts (`gl_compositor.c`, `sdl2.c`) and the field camera's new interface, resolved by hand (the commit message lists them) | **Merge candidate**: the owner's `claude/native-graphics` with the 3D battles; `claude/native-graphics` is fast-forwarded to it once the owner's graphics-card logs show no significant regression |

The first round's five crash fixes (N26-N32) are already on `claude/native-pc`
(`8f32fa79e`, `52844189f`, `fb6ee9455`, cherry-picked by the native session with the
same patches) and in `claude/native-graphics` (merge `5a4431686`). Local tag
`battle3d-integ-on-8920f1f67` (`925b47933`) marks the integration before `3e39f2b15`.
Nothing of the 3D battles is merged into `claude/native-graphics` yet: the merge
candidate is a branch of its own, waiting for the owner's graphics-card logs, and the
other sessions' branches were only read (from the checkpoint bundles).
`claude/native-pc` got the two PC box fixes (a fast-forward to `aa2841d7a`). Files and
provenance: engine `src/diorama/README.md` ("3D battles"). Compiled only with
`DIORAMA=1`; the GBA ROM is unchanged (`f214735b…3387`).

## What the player sees

* A battle started from the 3D view (walking into a visible wild Pokémon, a random
  encounter, a trainer spotting the player, a scripted battle) keeps the 3D world:
  the battle transition plays over the 3D field (its waves, slices, bars and flashes
  move and tint the 3D picture as they did the flat one), then the camera glides from
  the field's view down to the battle's (the 3DS camera: crane up, dolly zoom, a push
  and a short quake on landing, speed lines, vignette, cinema bars, a flash).
* The battle is drawn on the map where it started: the 3DS stage search picks a spot
  within 6 tiles of the player where both sides stand on fitting ground (grass for a
  wild Pokémon met in grass, sand on a beach, water when surfing). Since the second
  round it scores what the battle camera actually sees from each spot: nothing tall
  in front of any battler's own picture (singles or the four of a double battle; the
  3DS trees' crowns as far as they lean), no wall pressed right behind a battler,
  and as little of the world's end in view as possible.
* The battle's own picture is unchanged and drawn over the world: the Pokémon sprites
  (front/back, shiny, Mega forms, every species the game has), healthboxes, text box,
  move/bag/party/run menus, Mega trigger, status and stat effects, move animations
  and sounds. Only the scenery layer (BG3) is replaced by the world, pixel for pixel,
  with the GBA's own blending and brightness against it kept (a move that darkens or
  tints the background darkens or tints the world; one that shakes it shakes the
  camera). A move that loads its own background (Psychic, Feint Attack, the
  terrains...) shows that background as it is, then the world comes back; since the
  third round that background fills the whole window, not only the picture's
  area: the GBA renderer draws how its screen would go on past the picture - the
  part of the tilemap the move filled repeated where it repeats without a seam,
  mirrored at the picture's edges where it would show one - with its scroll,
  palette cycling, fades and flashes as on screen, nothing stretched (KNOWN_ISSUES
  V13).
* Soft contact shadows under the battlers (the opponent's Gen 4 style shadow sprite,
  when the game draws one, is kept instead).
* Single screen: the battle picture at the field's whole-number scale (6x at 1080p,
  8x at 1440p, 12x at 4K; the display settings' rule) on the bottom edge, the world
  filling the whole window above and beside it; the scenery's colour at the
  picture's edges is carried out to a wide window's sides (curtains and fades reach
  the whole window). The world is drawn at the render size and with the
  antialiasing the display settings choose (F10), as the field is; the picture,
  text and menus stay sharp at the window's own resolution. The F10 menu and the
  frame-rate corner show over battles too.
* The overworld's looks carry into the battle: the trees the player chose with F8
  (voxel or 3DS) stand in the battle's world; the sun, shadows and weather light are
  the field's. The F7 camera choice only changes the field's view, so the glide
  starts from whichever framing the field shows. A dark cave's battle shows the cave
  lit, as the GBA's cave battle background is; the transition into it plays over the
  dark field. Fog banks stay out of the battle (the GBA battle has no fog either).
* Water and flowers keep moving in the battle's world as often as the measured
  frame times allow (third round): every battle frame is timed; the glide's frames
  (each a redraw of the world) choose how often the tiles may redraw it - at every
  change while such frames stay within a 60 Hz frame, every 4 or 16 game frames
  when they take up to two or four times that, not at all beyond - and every later
  redraw frame moves that up or down. On software graphics they stand still as
  before; tile animations the GBA itself does not have (Route 102's pond) stay
  still too.
* Where the world ends - past a room's or a cave's edge, or past the scene - the
  battle's own scenery shows instead of black, as the GBA would show it there (the
  building, cave, gym or Elite Four background, its edges carried out to a wide
  window's); indoors and in caves it stands as a curtain on the map's edge, so the
  room's walls stay in front of it (second round).
* During a battle transition the people, the weather and a dark cave's light stay
  where they are while the field's ground slices, waves and slides (on the GBA
  they are sprites and windows, which the transition does not move); the Blur
  transition (dark caves) blurs the 3D field in the GBA's mosaic blocks (second
  round).
* After the battle the field fades back in in 3D, its camera where it was.
* F4 switches between the 3D and the classic view at any time, also in the middle of
  a battle (no second glide).

Switches (environment variables, for tests): `PKMN_DIORAMA_BATTLE=0` every battle 2D
as before; `PKMN_DIORAMA_TRANSITION_2D=1` battle transitions in 2D as before;
`PKMN_DIORAMA_BATTLE_KEEP=0` world redrawn every frame (see Performance);
`PKMN_BATTLE3D_PITCH`, `_DISTANCE`, `_FOCAL`, `_ROW` camera tuning;
`PKMN_DIORAMA_LOG=1` logs the stage choice with a map of the ground round the player
and what the camera sees from it, how long the world takes to redraw, and each
composed transition, the water's pacing decisions and each battle's frame times;
`PKMN_DIORAMA_BATTLE_TILES=0` water and flowers still, `=1` moving at every change
whatever the cost; `PKMN_DIORAMA_BATTLE_FRAME_BUDGET=<ms>` the frame budget the
pacing keeps to (16.67, a test switch); test tools: `PKMN_DIORAMA_STAGE_SURVEY=1` logs, for each
map the field shows in 3D, what the stages chosen round the player would show
(singles and doubles, against the 3DS scoring alone), and with
`PKMN_DIORAMA_STAGE_DUMP=<folder>` writes the cells the stage search reads.

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
* Water and flowers (second round): `tileset_anims.c` runs the field's own tile
  animation callbacks into the battle world's copy of the BG tiles
  (`DioramaBattle_AnimateFieldTiles`: no VRAM, no queue, the counters left as the
  field left them, the Battle Dome's palette lights skipped);
  `DioramaGL_SetBattleTiles` updates the atlas slots whose tiles changed, and the
  kept world is redrawn. Third round: the pacing comes from measured frame times
  (present to present, by kind: glide, redrawn, kept) instead of the second round's
  `glFinish` timing of the first eight redraws; the changes between two allowed
  redraws are gathered into one.
* A move's own background (third round): `LoadMoveBg` notes how much of BG3's
  tilemap the move filled (`DioramaBattle_NoteMoveBg`); while the world is not shown
  the battle asks the GBA renderer for the margins round the picture
  (`gDioramaSceneWide`), which it draws per line with that line's BG3 registers,
  the window state of the nearest picture column and BG3's and the backdrop's
  blending and brightness; repeat or mirror is decided once a load from the
  background's unfaded colours (the seam's colour step against the steps between
  neighbours). The battle draws it GBA pixel for GBA pixel at the picture's scale
  and carries out only the text box's rows from the picture's edges.
* Render size and antialiasing (third round): the battle's world goes through the
  display settings' render target (`gl_target.h`, `DioramaGLTarget_Begin/End`) as
  the field's scene does; the kept copy, the fade, the shadows and the picture are
  drawn at the window's resolution.
* The world's end (second round): `gba_easy_draw.c` also draws BG3, the scenery the
  world stands in for, into `gDioramaSceneArt` in its unfaded colours; caught while
  the scenery is at rest, it is drawn just short of the far plane after the world
  (only where nothing was drawn) and, for indoor maps, on curtains standing on the
  map's north, east and west edges (where the snapshot's cells turn to the border
  block), with the terrain shader's camera so depths agree. It is kept with the
  world, and the battle's fade applies to both.
* Transitions (second round): `DioramaGLBattle_ComposeFieldBands` copies the field's
  ground and models and lays them band by band; the compositor then draws its
  objects, air and dark-cave light unmoved, and `DioramaGLBattle_ComposeFieldPicture`
  lays the transition's picture over all of it. With the Blur transition's mosaic
  (`REG_MOSAIC` captured with BG1's mosaic bit) the bands sample the field in the
  GBA's blocks. If the compositor refuses this frame's field after the picture was
  made see-through for it (`DioramaGLBattle_WantsField`), it draws the last field.

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

Second round (2026-10-10 afternoon; `claude/battle-3d-integration` `0fa2bf87a`,
then the merge candidate `claude/native-graphics-3d-battles` `7bf42d267`, debug-menu
test builds):

| Check | Result |
| --- | --- |
| Stage survey: every walkable spot within 8 tiles of 1-3 spots on each of 44 maps (all gyms, the Elite Four, 26 caves, Weather Institute, Oceanic Museum, Space Center, Trick House, Trainer Hill; cells dumped by the game, `PKMN_DIORAMA_STAGE_DUMP`), singles and doubles: 20,428 stage choices, measured as the camera sees them | Against the 3DS scoring alone: stages with something over a battler 1,872 -> 771 (-59%), with a wall pressed behind a battler 1,012 -> 535 (-47%), showing over 2% black 5,872 -> 5,750 (-2%). Petalburg Woods has no 3D view (Diorama), so no survey there |
| Water and flowers in a battle | Pass with `PKMN_DIORAMA_BATTLE_TILES=1`: Oldale Town trainer battle, the flower beds change between screenshots half a second apart (pixel diff only on the flowers); Route 110 wild battle (the merge candidate's player build), the sea behind the opponent: its waves change between screenshots (pixel diff on the water and the bobbing healthbox only). Water the GBA keeps still stays still (Route 102's pond uses tiles no animation touches). By cost here: "the world takes 248 ms to draw ... water and flowers stand still (too slow to redraw)" (Oldale), 30 ms (Petalburg Gym), 215 ms (Route 101) - all over the 12 ms limit on software OpenGL, so still, as designed |
| Scenery where the world ends | Pass: Petalburg Gym (Roxanne's gym room) and Sidney's room: the black above and beside the room is now the gym's cream background and Sidney's teal one, the walls in front of it; Granite Cave B1F: the cave background (`scenery caught ... top left ffc5b483`) |
| Slice transition (Route 101, walking into the Shinx; 3DS camera) | Pass: the field's ground and trees slice and slide, the player, follower, the Shinx and the NPCs stay put and are cut only by the transition's windows, as on the GBA |
| Blur transition (Granite Cave B1F, dark, wild Sunkern) | Pass: "the field in mosaic blocks of 2 x 2" and coarser; the lit floor turns to blocks, the people stay sharp |
| Double battle with Mega Evolution | Pass: Kate & Joy (Spinda, Slaking) in Oldale Town, Gardevoir's Mega reaction, Imprison, Feint Attack with its own background |
| Crash scenarios in 3D (Trainer Card, Fly map, PC boxes: cursor, close, summary, summary and back, Poké Ball, Mega Evolution) | Pass: all alive |
| PC box crashes (2D, `claude/native-crash-fixes` and `claude/native-pc-box-fixes`) | Reproduced with gdb before the fixes (`SpriteCB_CursorShadow` after `FreePokeStorageData`, closing the boxes and opening a summary); alive after, the summary round trip back to the boxes and out of the PC too |
| Unit tests | `check-diorama` passes (stage-search tests: trees in front of the opponent, doubles, rooms with high and low walls, a wall right behind, a leaning crown) |
| Native checks | `check-native` (1063 + 4186), `check-abi` (172 types), `check-game-sections`, `check-decompress` (7469 assets) pass |
| Windows build (Wine), the merge candidate's exe as packed for the owner | Pass: `run-3d-battle-cave.bat`'s save (Granite Cave 1F), a wild Durant in 3D, the cost check ("the world takes 69.18 ms to draw ... water and flowers stand still"), the cave's scenery caught, Run, back to the 3D field; `run-3d-battle-water.bat`'s save (Route 110), a wild Diglett in 3D with the sea behind it (still by cost, 60.76 ms); the debug-menu test exe: a wild battle on Route 101 in 3D |
| GBA ROM | unchanged (`f214735b…3387`) on every branch, the merge candidate `7bf42d267` included |

Third round (2026-10-10 evening; `claude/battle-3d-next`, then the merge candidate
`claude/native-graphics-3d-battles-3` `2a368fd8d` on graphics `6743bc1e5`, debug-menu
test builds; the Windows player exe of `2a368fd8d` as packed for the owner):

| Check | Result |
| --- | --- |
| Builds and automated checks on the merge candidate | Pass: Linux 3D, 2D and debug-menu test builds; Windows 3D, 2D and debug-menu test builds; `check-game-sections` (Linux 3D and 2D, Windows 3D), `check-decompress` (7469 assets), `check-native` (1063 + 4186 + 139 + 176), `check-abi` (172 types), `check-diorama` (the camera's 403 checks, the stage-search tests, the compositor goldens); `claude/native-pc` `aa2841d7a` merges into it with no file changed |
| A move's own background over the whole window (KNOWN_ISSUES V13) | Pass: Psychic at 960x540 (its psychic background mirrored at the picture's edges; the attacker's colour cycle and the target's shake as before), Feint Attack at 1280x720 (its dark background), Future Sight at 960x540; on `claude/battle-3d-next` also Future Sight at 1280x720 and Imprison in a double battle. The log: "a move's own background, carried past the picture (40, 40 and 20 pixels left, right and above)". The moves were given to the test team's Gardevoir with gdb at the action menu (test only) |
| Water and flowers paced by measured frame times | Pass on software OpenGL: Route 110, a glide of 44.8 ms a frame: every 16 game frames; then redraw frames of 31 ms: every 32, then still; at 1280x720 (glide 67 ms) still from the start. Forced on (`PKMN_DIORAMA_BATTLE_TILES=1`): Route 110's sea changes between shots half a second apart (45,603-67,014 pixels), Oldale Town's flowers (4,531-12,750) |
| The glide from the new cameras (graphics `6743bc1e5`) | Pass: Route 101 wild battle through the Slice transition from the Adventure camera (the default) and from the Diorama camera (F7, `cameraMode=diorama`): the transition over the field as shown, then the glide from that view down to the battle's |
| Render size and antialiasing (`claude/battle-3d-next`) | Pass: Ultra (4x MSAA): "3D view: drawn at 960x540, 4x MSAA" and the battle's world antialiased like the field (edge colours counted, zoomed crop) |
| Petalburg Woods (in 3D since graphics `6743bc1e5`) | Pass: a wild Diglett in the grass south of the north gate, the battle on the forest path with the woods' shade light; glide 67.6 ms a frame: water and flowers still |
| Every battle transition over the 3D field | Pass: each of the 37 field transitions forced in turn on a Route 101 wild battle (test only: gdb sets `BattleTransition_StartOnField`'s argument) - Blur, Swirl, Shuffle, Big Poké Ball, Poké Balls trail, Clockwise wipe, Ripple, Wave, Slice, White bars, Grid squares, Angled wipes, Aqua, Magma, Regice, Registeel, Regirock, Kyogre, Groudon, Rayquaza, Shred split, both black holes, Rectangular spiral and the 13 Battle Frontier ones: each composed over the 3D field, the battle in 3D, Run, back to the field, no crash; and Sidney's own battle (talking to him in his room): the Elite Four's mugshot banners slide in over the 3D room. Compared with the classic view where it mattered: Swirl, Shuffle and Ripple move the field's lines as the GBA does (Ripple repeats rows at its peak, as the GBA's does), Kyogre's and Groudon's patterns leave the map's people showing, as on the GBA, and Rayquaza's black hole shows the field half dark, as the GBA's palette blend does |
| Rooms, caves, double battle, transitions, crash scenarios (as in the second round) | Pass: Petalburg Gym and Sidney's room (the room's background past its edge), Kate & Joy double battle with Mega Evolution in Oldale Town, the Blur transition's mosaic in Granite Cave B1F, Trainer Card, Fly map, PC boxes (cursor, close, summary, summary and back), Poké Ball, Mega Evolution: all alive |
| Windows player exe as packed for the owner (Wine) | Pass: Granite Cave 1F, a wild battle in 3D (the new log line names Wine's software renderer, the window and the 3D view at 1280x720), the cave's scenery caught, glide 50.5 ms a frame: every 16 game frames, then 32; Run; back to the 3D field |
| The overworld's frame rate with the battles merged (no regression) | Pass: `--benchmark 5` in Littleroot Town (no wild Pokémon to start a battle mid-run), three runs each, alternating, same machine: graphics `6743bc1e5` against the merge candidate - 1280x720 9.9 / 9.7 fps, 1920x1080 5.9 / 6.2, 2560x1440 4.1 / 4.1, 3840x2160 2.3 / 2.2: within the runs' own spread (up to 0.8 fps). Outside a battle the merge adds only flag checks and small buffers to each frame. (On Route 101, where visible wild Pokémon roam, the same benchmark varied by up to 30% at one size and one run of the base build left the 3D view altogether - a wild Pokémon reaching the player starts a battle; Littleroot Town has none) |
| GBA ROM | Unchanged (`f214735b…3387`) built from the merge candidate |

Not tested: multiplayer battles (1v1, 2v2, co-op, Twin Gym Leaders, Championship)
in the native build - their transport is Milestone C3, not done yet; the 3D
presentation only reads the battle and does not take part in it (link battles keep
their VS intro on BG1/BG2). Battles on a real graphics card (the owner's run is
wanted: see Performance). Flash being used in a dark cave before a battle.

## Performance

Software OpenGL here (Mesa llvmpipe, 2 cores): a battle runs at 60 game frames a
second; while the camera stands still the world is copied, not redrawn (e.g. "world
drawn 69 times, kept 5626" in one wild battle), a frame then taking about 5-9 ms
present to present; a frame that redraws the world takes 30-67 ms (960x540 to
1280x720), and the glide's 1.5 s redraws it every frame (38-67 ms a frame here; the
game slows with it, by design).

Water and flowers are paced by those measured frame times (third round; the second
round timed the first eight redraws with `glFinish` against a fixed 12 ms limit).
Each battle frame is timed present to present and counted as a glide frame, a frame
that redrew the world or a kept one. The glide's average decides how often the tile
animations may redraw the world: at every change while its frames keep within the
budget give or take a tenth (a 60 Hz frame, 16.67 ms, or the kept frames' own pace
if that is slower), every 4 game frames up to twice that, every 16 up to four times,
not at all beyond; afterwards a running average of the frames that redraw the world
moves that up (over 1.25 times the budget: half as often, still past every 32 game
frames) or back down (eight such frames in a row within 1.05 times: twice as often).
The changes in between are gathered into one redraw, so up to every 16 game frames
the GBA's tile animations (most change once in 16 frames) keep their pace. A graphics card at 60 Hz should therefore
keep them moving at every change, and a slow one reduces them instead of the battle
slowing down. `PKMN_DIORAMA_LOG=1` logs each decision and, at the battle's end, the
frame times by kind ("kept world ... world redrawn ... glide ..."); the first 3D
battle of a run also logs the graphics card, the window's and the 3D view's size and
the multisampling.

A real graphics card has not been measured yet (KNOWN_ISSUES V3): the owner's logs
from `battle3d-test-runs\wip-20261010-3` (`run-3d-battle-water.bat`,
`run-3d-battle-flowers.bat`, `run-3d-battle-cave.bat`) decide it. No claim is made
that the renderer is optimized.

## Review of the visual problems (second round, 2026-10-10)

The first round's list, item by item (numbers as they were), with what the second
round did:

| # | Problem (first round) | Now | Evidence |
| --- | --- | --- | --- |
| 1 | The stage can be a few tiles from the player; in cramped rooms walls close behind the opponent | **Improved.** The search scores what the battle camera sees from each spot, a wall pressed behind any battler included, against each battler's own picture (singles or doubles). Still up to 6 tiles from the player when that buys fitting ground and a clear view, and in maze-like rooms (Rustboro Gym) every spot has a wall nearby | Survey of 44 maps: walls pressed behind 47% fewer, things over a battler 59% fewer than the 3DS scoring alone; unit tests |
| 2 | Black past a room's or a cave's edge | **Fixed.** The battle's own scenery shows wherever the world ends: just short of the far plane where nothing is drawn, and on curtains on an indoor map's edge where its border block would show as black ground | Petalburg Gym, Sidney's room, Granite Cave screenshots |
| 3 | Water and flowers stand still | **Fixed where practical.** They move when a redraw of the world takes under 12 ms (a graphics card; to be confirmed by the owner's run), and stand still on slow (software) graphics as before; `PKMN_DIORAMA_BATTLE_TILES` forces either way | Forced run: flower beds change between frames; cost check logs 25-250 ms here |
| 4 | The map's people and Pokémon are not in the battle's world | **Unchanged, by design** (the 3DS project leaves them out too; the battle's own sprites are its picture) | - |
| 5 | During a transition the map's sprites move with the field's bands | **Fixed.** The people, the weather and a dark cave's light stay where they are and are cut only by the transition's windows, as on the GBA; the Blur transition's mosaic is drawn on the 3D field | Slice (Route 101) and Blur (Granite Cave B1F) frame sequences |
| 6 | A refused first transition frame shows the field's layers black | **Fixed** (the last 3D field is drawn under that frame's picture) | Code path; not provoked on purpose |
| 7 | Tall sprites can seem to float over uneven ground | **Unchanged.** The battlers stay at the battle's own GBA coordinates (camera and animations preserved) | - |
| 8 | A crown's edge can touch a battler's picture | **Improved.** Crowns are measured as far as they lean north (the 3DS large crown 0.10 tile past its cell, the small one 0.46), each column projected corner by corner against each battler's picture; the voxel trees already lay inside their boxes. A slight overlap can still be chosen when every spot within reach has something in front | Unit test (leaning crown: 34% covered where an upright box saw 23%); survey |
| 9 | Camera framing is the 3DS project's | **Unchanged, as asked** (the 3D battle camera and the move animations are preserved) | - |

Found in the second round: Petalburg Woods has no 3D view (the Diorama's map
support), so its battles are 2D; on a graphics card the cost check stalls the
glide's first eight redraws for their completion (`glFinish`), a few milliseconds;
a move that brings its own background (Psychic, Feint Attack...) shows it in the
GBA picture's area only, with the rest of a wide window black meanwhile (as in the
first round; its edges could be carried out as the scenery's are: KNOWN_ISSUES V13).

Third round (2026-10-10 evening), the owner's priorities: (1) the move backgrounds'
black past the picture is fixed (V13) by drawing BG3 on past the picture's edges -
repeated or mirrored, never stretched, the move animations untouched; (2) water and
flowers are paced by measured frame times, and the `glFinish` stall of the second
round is gone (every frame is timed present to present instead); their cost on a
real graphics card is still to be measured (the owner's logs); (3) the presentation:
the battle's world is drawn at the display settings' render size and antialiasing
like the field, the picture at the same whole-number scale, and the glide starts
from the new Adventure or Diorama camera exactly as shown. Petalburg Woods is drawn
in 3D since graphics `6743bc1e5`, so its battles are 3D too (checked: a wild Diglett on
the forest path, the woods' shade light in the battle's world).

