# Graphics handoff (`graphics-handoff-20261012`)

The 3D overworld's last graphics changes before it goes into the one EmeraldTogether game. The
owner (2026-10-12) approved `native-wip-20261012-2` (option B: roofs, recessed windows, doors,
cave levels) and asked for V29 (building heights) and V32 (windows dark at night) to be fixed
before the branch is handed to the main integration session, with everything approved kept,
nothing else in the UI, sprites, Battle FX or characters touched, and the 3D battle branch (Sky
Pillar's rubble) still working with it. With V29 and V32 resolved the graphics development phase
is ready for integration; the frame rate on a real graphics card (V39) is tracked separately.

While this was being finished the battle session delivered `combined-dev-20261012-1` (the 3D
battles merged onto `native-wip-20261012-2`) and reported, besides the battle line V46 (its E13),
one regression of `native-wip-20261012-2` in this branch's own terrain code: thin sky-coloured
lines along the Lavaridge relief's steps (its E14, here V47). It is fixed here too (`1d54639cf`),
as a small revert, not a new overhaul.

## The commits

Engine branch `claude/graphics-overhaul` = `claude/native-graphics` = `1d54639cf` (tag
`graphics-handoff-20261012`), on top
of `8e4604993` (`graphics-wip-20261012-2`, the engine of `native-wip-20261012-2`, which the
integration branch already has: `a9627cfe5` merged it).

| Commit | Issue | Files | What changes |
| --- | --- | --- | --- |
| `967437999` | V29 | `tools/diorama_buildings/auto_buildings.py`, `test_auto_buildings.py` | Building heights where the eave search was wrong: Sootopolis's 11 towers (wall up to the roof's outline, 28 rows, not the door's lintel at 20), the Cove Lily Motel (Lilycove, 64) and the Battle Dome (Battle Frontier west, 56; the commit's message calls it the Battle Factory) with their upper storey standing instead of laid back as roof, Route 113's glass workshop on its own four rows with its window's cell (facade 28; the trees over it were its roof, its window a hole). |
| `090cb428a` | V32 | `tools/diorama_buildings/window_glow.py`, `export_gl.py`, `test_window_glow.py` | The windows that stayed dark at night glow: found in each building's own drawing as well as over its page (a colour one building's walls are drawn in can be another's glass), every pane of a window, shop windows with a blind and a stripe across, Sootopolis's arched windows drawn in stone. |
| `61935f7eb` | V43 (the UI session's U12) | `src/diorama/scene/scene_snapshot.c` | The field's message box stays in the 3D view while the game waits after its last line (it vanished as soon as the line was printed), and the save prompt shows. |
| `c806a788c` | V29 | `auto_buildings.py`, `test_auto_buildings.py` | A comment and a test's name: the building at Battle Frontier west (19,17) is the Battle Dome (its door leads to the Dome's lobby), not the Battle Factory as `967437999`'s message says. Nothing it makes changes. |
| `1d54639cf` | V47 (the battle session's E14) | `src/diorama/terrain/terrain_mesh.c`, `tests/diorama/test_terrain_mesh.c` | The undersides on a cell's floor are kept again: dropping them (`9d63e60f5`, V37, in `graphics-wip-20261012-2`) let thin sky-coloured lines show along the Lavaridge relief's steps, in the field and in battles. |

Nothing else changed. The roofs, terrain, caves, props, lights, settings and the Players menu fix
(U11/V42, `main.c`) are as approved; V47 gives the relief back the undersides it had before
`native-wip-20261012-2` (the picture as approved, without the cracks). `buildings.bin` (made by the
build) differs from `native-wip-20261012-2`'s only in the V29 buildings: V32, V43 and V47 leave it
byte for byte. The GBA ROM is unchanged (sha256 `f214735b...3387`). No save, world or launcher data
changes.

## What the player sees

- Sootopolis's tower houses stand as tall as their drawing (the wall up to the octagonal roof);
  the Cove Lily Motel and the Battle Dome have their second storey; Route 113's glass workshop
  is one building with its window, no trees on its roof.
- At night: Slateport's, Petalburg's, Lavaridge's and Verdanturf's house windows, the white-barred
  sash windows with all their panes, Mauville's Game Corner's display windows and every bulb
  round its door, Lilycove's department store's arched windows and the windows under its
  awnings, the Battle Frontier's lounges' glass fronts and its exchange corner's glass door, and
  Sootopolis's arched windows glow; Sootopolis's
  emblems and doors (the same greys) stay dark.
- A sign's or a person's last line, and the save prompt, stay on screen in 3D until the player
  presses a button.
- No thin sky-coloured (underground: black) lines along the rock steps of Mt. Chimney, Jagged
  Pass, Fiery Path and Magma Hideout, in the field or in the battles there.

## How V32 finds the windows (`window_glow.find_page_windows`)

1. The page's windows exactly as before (`find_windows` over the whole page: the same pieces on
   all 137 pages, so `dimensional.py`'s recessed windows are the same and no window that glowed is
   lost).
2. Each building's own drawing (`model_rects`: its triangles' texture extent within the cells it
   stands on): a pane whose glass is a colour another building on the page uses for its walls
   (Slateport's houses beside its Pokemon Center). It must be at least 3 x 2, not run out to the
   drawing's side, and, when its glass is pale (`pale`: less than 96 more blue than red, the grey
   blue walls are shaded in), be closed in by a frame drawn in one colour (`enclosed`, as
   `dimensional.window_rects` finds the windows it sets back). Glass a drawing finds beside a
   window of step 1 joins that window.
3. Every pane of each window (`whole_window`): the panes its frame closes in past glazing bars of
   the frame's colour.
4. Shop windows (`shop_window`): glass a frame holds only at its sides (a blind over it, a stripe
   across it), if everything the frame closes in is a window at least 3 x 3 and mostly glass.
5. Windows drawn in stone (`stone_panes`): grey panes with glints of white in a dark blue outline,
   an arch over straight sides with a white sill under it.

On the 58 outdoor pages: 612 windows to 654, 17,297 lit texels to 22,785, 2,884 window runs to
3,842. Of the 260 windows `dimensional.py` sets back outdoors, 12 were dark and 2 are: two strips
of one shading band (V44), not windows.

## Merging into the one game

`git merge-tree --write-tree` (git 2.43) of `1d54639cf` with each branch (the newest checkpoints
on the owner's PC at the handoff, their bundles fetched into a private namespace):

| With | Result |
| --- | --- |
| `claude/emeraldtogether-integration` `8706f8f6c` (emeraldtogether-integration-20261012-3, "Native 3D preview 9") | **No conflict** (`scene_snapshot.c` auto-merges with the battle branch's lines). The same with `7a98bd4a5` (-2). |
| `claude/combined-dev` `22661c214` (the battle session's combined-dev-20261012-1) | No conflict. |
| `claude/battle-environments-3` `aa63a98a3` (battle3d-env-wip-20261012-2) | No conflict. |
| `claude/character-customization` `059dbc4b1` | No conflict. |
| `claude/native-ui` `23486f51` (ui-native-wip-20261013-1, the newest; also `035b263cc`, -4), on its own | `gl_compositor.c`, `sdl2.c`: the same two files as with `8e4604993` - not from this handoff; the integration resolved them (`2d1c85b60`, `5fccfde3f`) and has merged `035b263cc` (`8706f8f6c`). |
| `8706f8f6c` + this handoff, then the battle session's `5699d58b3` (cherry-pick) | No conflict (`battle_capture.c`, `gl_battle.c`). |
| `8706f8f6c` + this handoff + `5699d58b3`, then `claude/native-ui` `23486f51` | No conflict: the UI's next rounds merge after this handoff as they would without it. |

The app docs (`claude/native-pc`, Markdown only) conflict only where both sides wrote the same
spot. With the integration's app branch (`8934371`): `CHECKPOINTS.md` (both add rows at the end
of the table: keep both sides' rows) and `KNOWN_ISSUES.md` at V37 (the row before V38, which both
changed the same way - this branch takes the integration's V38 wording): take this branch's V37
(V47's numbers). With `claude/combined-dev`'s app branch (`d4c93ef`): `CHECKPOINTS.md` (keep both),
`KNOWN_ISSUES.md` V37 and V38 (take this branch's V37; either V38), `TEST_PLAN.md` (both add a
section numbered 7g after 7f: keep both, renumber one).

Generated data: `build/diorama/buildings.bin` and `src/data/diorama/buildings.generated.c` are
build outputs, not in Git; `make` makes them again from the merged tree.

For the native UI session: with your `field_text` screen up, `DIORAMA_PICTURE_HIDE_UI` hides the
game's box under yours as before; where your `Detect()` leaves the picture to the game, or with
`PKMN_NATIVE_UI=0`, the 3D view now shows the game's box (the fishing messages your COORDINATION
calls "U12's cousin" are window 0 without the field message box: shown now by the code; fishing
itself was not run here).
`scene_snapshot.c`'s `WindowShown` is a local copy of your `Window_NativeUiShown`'s test (in
`window.c` under `ENABLE_NATIVE_UI`), kept static so that no shared file changes; the two can be
made one later.

For the 3D battle session: nothing here touches props, the battle stage or your files; the
terrain change is your E14 (V47): the undersides are back, as on your round 4. The battles'
backdrops show the taller towers, the motel and the Battle Dome, and at night the windows.

### One line the integration needs (V46 = the battle session's E13; not from this handoff)

A battle on a map whose layout its scripts switched (`setmaplayoutindex`) is drawn in 2D
(`Diorama battle: drawn in 2D (no 3D field of map 24.79 to stand in)`): Sky Pillar's floors before
Rayquaza is woken (`VAR_SKY_PILLAR_STATE` under 2: the CLEAN layouts), Route 131 on every visit,
Route 111 on days without the Mirage Tower, Shoal Cave at high tide, Route 130 with Mirage Island,
Sootopolis in the legends' battle. Since `graphics-wip-20261012-2` (V40) the scene snapshot names
the layout the game draws (`scene_snapshot.c` `CurrentLayoutId`, the save's id); the battle
branch's `battle_capture.c`, written against `graphics-wip-20261012-1`, names the map's own
(`gMapHeader.mapLayoutId`), and the battle's world lookup (`DioramaGL_GetBattleWorld`) compares the
two. Both lines are in the integration branch (`7a98bd4a5`, `8706f8f6c`).

Found here on the first trial merge; the battle session found it too and fixed it on
`claude/combined-dev`: **`5699d58b3`** ("Diorama battle: a battle on a switched layout stands in its
3D world") - the frame takes `gSaveBlock1Ptr->mapLayoutId` as the snapshot does, and the battle's
log line names the layout. It is the same line as the one tried here (`battle-layout-fix.patch` in
the checkpoint):

```c
-    frame->mapLayoutId = gMapHeader.mapLayoutId;
+    frame->mapLayoutId = gSaveBlock1Ptr != NULL ? gSaveBlock1Ptr->mapLayoutId : gMapHeader.mapLayoutId;
```

Main session: cherry-pick `5699d58b3` (it applies to `8706f8f6c` with this handoff merged without a
conflict, checked). On that trial (`8706f8f6c` + `1d54639cf` + `5699d58b3`): Sky Pillar 1F, 3F, 5F
and the top (layouts 433, 435, 437, 438) and Route 131 (layout 319) drawn in 3D, the rubble standing
round Rayquaza. Not committed here: the file is the battle session's.

## Rollback

- Engine: `claude/native-graphics` back to `8e4604993` (tag `graphics-wip-20261012-2`) undoes all
  five; each commit also reverts on its own (`git revert`): V29 and V32 are generator changes
  (the data is made again by the build), V43 and V47 are one C file each (V47's revert brings the
  cracks back with the V37 saving).
- After a merge into the integration branch: `git revert -m 1 <the merge>`.
- App: the docs only (`claude/native-pc`, tag `graphics-handoff-20261012`); `native-wip-20261012-2`
  is the previous tag.
- Player side: nothing to undo. The launchers of `native-wip-20261012-2` (preview 7) and the
  integration's (previews 8 and 9) are unchanged and open the same worlds and saves.

## Verification

Checks on `c806a788c`, and `check-diorama` again on `1d54639cf` (V47 changes `terrain_mesh.c`
only); the V29, V32 and V43 pictures used `61935f7eb`'s builds, everything after V47 the final
builds. Results in detail: `docs/graphics-overhaul.md` (last section).

- Compile: Linux and Windows 3D, Linux 2D; the GBA ROM byte-identical (`f214735b...3387`). The
  final Windows exe imports only `SDL2.dll` and Windows' own DLLs.
- `check-native`, `check-diorama` (13 programs, compositor goldens), `check-abi`: pass. Python
  tests: 1399 passed, 1 skipped. Rules and building tools: all pass but V31 and V2, as before;
  `test_window_glow` 22, `test_auto_buildings` 16.
- The generator's proof: 573 of 573 models exact against their drawing, 50 rooms, 0 pixels differ.
- Before/after pictures on Linux: V29 (4 places, both cameras), V32 (11 at night), V43 (the
  sign's last line, the save prompt), V47 (5 places, both cameras: the cracks' colour on 0.7-2.3 %
  of the picture before, one lone pixel after); the Windows exe under Wine (Lilycove, Slateport's
  market; Jagged Pass before/after V47: 0.97 % and 0.87 % to none), both cameras.
- V47's cost: Jagged Pass (the benchmark's scene, 1280x720) builds 1,055,694 terrain vertices
  (948,870 without the undersides) and uploads 703,796 (632,580); 936.8k triangles a frame (842.5k).
- Multiplayer with the final builds: the Players menu over the 3D field with a trade, back-out and
  restart (2 Linux 3D clients; 2 clients of the final Windows exe under Wine); live saves and
  recovery (2 Linux 3D clients, native-checkpoint-3d-16).
- The trial with the integration -3 (`8706f8f6c` + `1d54639cf` + `5699d58b3`): no conflict, ROM
  byte-identical, 14 battles in 3D by day (Sky Pillar's four on their switched layouts with the
  rubble round Rayquaza, Route 131, the Lavaridge relief's five with no cracks) and 2 at night,
  Sky Pillar's rubble and Mt. Chimney in the field, the Gym sign's last line with the native UI on
  and off. (A first trial with the integration -2 found V46.)
- Not seen: any of it on a graphics card (V39).
