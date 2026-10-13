# Combined development branch: the 3D battle environments in the newest 3D game

Recorded 2026-10-12. Owner request: put the completed 3D battles and battle environments into
the combined development game now, on a branch of its own, instead of leaving them isolated
until the graphics-card benchmarks are run; keep the stable graphics branch, the latest
graphics checkpoint and every battle branch as they are; keep the overworld's newest geometry,
objects, lighting, weather and cameras and the battle crash fixes; no UI, sprite or Battle FX
work; essential builds and automated checks; a Windows development build; real GPU
performance marked unverified.

## Where it is

| Branch | Base | Commits | What |
| --- | --- | --- | --- |
| engine `claude/combined-dev` | `8e4604993` (`graphics-wip-20261012-2`, `claude/native-graphics` and `claude/graphics-overhaul` now; checkpoint `native-wip-20261012-2`) | `717504b88` merges `claude/battle-environments-3` (`aa63a98a3`, checkpoint `battle3d-env-wip-20261012-2`); `5699d58b3` a battle on a switched layout stands in its 3D world (E13); `f86368c23` native multiplayer battles no longer freeze in the 3D build (E15, the EmeraldTogether integration's `bc7a3cfc7`); `397324ddf`, `1eaab97b4`, `22661c214` the survey tool, the report tool and the review (tools only) | **The combined development branch.** Tag `combined-dev-20261012-1` = `22661c214`; its code is `f86368c23`. |
| app `claude/combined-dev` | `claude/battle-environments-3` (`f64b21d`) | `f68866b` merges the overworld's docs (`claude/native-pc` `0c55dba`, `native-wip-20261012-2`); this document and the status files | The docs that go with it. Same tag. |

Nothing else moved: `claude/native-graphics`, `claude/graphics-overhaul`, `claude/native-pc`,
`claude/battle-environments-3` and every other battle branch, the 3D battles candidate
`e747ce106`, the other sessions' branches and every checkpoint folder are as they were.
`8e4604993` is an ancestor of `claude/combined-dev`: when the owner decides,
`claude/native-graphics` can take it as a fast-forward.

Another session's `claude/emeraldtogether-integration` (checkpoint
`emeraldtogether-integration-20261012-3`, the launcher's "Native 3D preview 9") puts the same
two lines together with the native UI, the character selection and the animated battle sprites.
This branch is the overworld and the battles alone, as the owner asked. That branch was only
read here (its bundles fetched into a private namespace); one fix of the battle code was taken
from it (E15), and it lacks this branch's E13 fix (COORDINATION.txt in the checkpoint).

## What is in it

* **The overworld's newest tip whole** (`8e4604993`): real roofs, recessed windows and framed
  doors, the last flat landmarks standing (the Battle Pyramid, the cable car stations, the
  Trick House, Trainer Hill), cave floors at their own levels, the layout a map's scripts switch
  to (Route 111 without the Mirage Tower), terrain chunks drawn from indices, the Players menu
  over the 3D field, and everything before it (detail objects, lighting, weather, the cameras,
  the F10 settings, the frame-rate limiter).
* **The 3D battles** (candidate 4, `e747ce106`) and **the battle environments, rounds 1 to 4**
  (`claude/battle-environments-3`): every battle place audited and made dimensional, the battle
  camera's glide between game frames. Classes now A 5, B 206, C 3, D 0 (below).
* **The native crash fixes the battle line carries**: N35 and N36 (the PC's boxes), N37 to N40
  (two-trainer battles, two trainers' names, a cry stopped before any played, a move's shake),
  the Poké Ball and Trainer Card crashes and four NULL faults; and E15 (native multiplayer
  battles in the 3D build).
* **Not in it**: the native UI session's `claude/native-ui`, the character selection's
  `claude/character-customization`, `claude/fix-player-menu-fade`, sprite and Battle FX work.

## The merge

The two sides' merge base is `c51769606`, which round 4 already held, so git merged them with
no conflict and kept both whole (their 13 commits since `c51769606`; the battle side's work).
Checked beyond git:

* **Terrain chunks**: the overworld now draws every terrain chunk from indices and asks that
  any new chunk draw go through `DrawChunk`; the battle side draws none of its own (the four
  chunk draws in `gl_terrain_renderer.c` are its, the far field's sector draw is not a chunk).
* **Buildings**: `buildings.bin` is made from both sets of specs: 1544 models, 4662
  placements (round 4: 1539 and 4634). The generator's report is round 4's line for line, but
  for the five landmarks it left flat before (now modelled); every battle room is as in
  round 4.
* **Found by the checks and fixed (E13)**: the overworld's 3D view now takes the layout the
  game draws (`CurrentLayoutId`, the save's id), the battle took `gMapHeader.mapLayoutId`
  (the map's own), and the battle's world is looked up by comparing the two. Every battle on a
  layout a map's scripts switch to was drawn in 2D: on Route 131 always (its scripts switch to
  its Sky Pillar layout on every visit), on Sky Pillar's floors until Rayquaza ends the legends'
  battle, in Shoal Cave at high tide, on Route 111 on a day the Mirage Tower is hidden (one run
  in four), in Sootopolis during the legends' battle, on Route 130 with Mirage Island. The battle
  frame now takes the layout the same way (`5699d58b3`). Route 111: four runs, two on the
  switched layout (392) and two on the map's own (27), all in 3D. Route 131: 2D with the build
  before the fix ("drawn in 2D (no 3D field of map 0.46 to stand in)"), 3D on layout 319 with
  it. Round 4 drew these battles in 3D but in the map's own layout, not the one the game shows.
* **Taken from the EmeraldTogether integration (E15)**: the 3D battle's backdrop read the
  trainer class of a link battle's opponent (`TRAINER_LINK_OPPONENT`), the engine's assertion
  stopped the game, and every native multiplayer battle in the 3D build froze at its first frame.
  That session found it with the launcher's 1v1 on the 3D build and fixed it (`bc7a3cfc7`: only a
  real trainer's class is read); it is cherry-picked here unchanged (`f86368c23`). Nothing else
  from that branch.
* **Docs**: CHECKPOINTS' two new rows both kept, the GBA ROM guard lists both sessions'
  confirmations; KNOWN_ISSUES V37 and V38 as the overworld wrote them, with Sky Pillar's rubble
  standing here.

## Validation

Builds and checks at `397324ddf` (the code of `5699d58b3`, from a fresh worktree), and again
at the tag (`22661c214`, the code of `f86368c23`) for what the freeze fix touches (the 3D
builds; `battle_capture.c` is in no 2D build):

* **GBA ROM**: built from the combined branch at both commits, byte-identical (`f214735b…3387`).
* **Builds**: Linux 3D and 2D, Windows 3D (MinGW), the TEST build; at the tag Linux 3D, Windows
  3D and the TEST build again. The player builds carry no test driver and no debug menu.
  Compiler warnings: the same 21 as before the merge.
* **Selftests, Linux 3D (both commits) and 2D**: `check-party-order` 1119 (N37),
  `check-battle-names` 1724 (N38), `check-cry-stop` 5 (N39), `check-shake-anim` 11 (N40), 0
  failed; `check-game-sections` (Linux 3D and 2D, Windows 3D); `check-decompress` 7469 assets;
  `check-native` 1067 + 4186 + 244 + 176 checks and 9 pictures; `check-abi` 172 types.
* **`check-diorama`** (both commits): every program passes (the terrain mesh with the
  overworld's new tests, the props' 7984 checks, the camera's 403, the far field's 54618, the
  battle stage, the rules, the compositor goldens over 18318 metatiles, `validate_rules`,
  `compile_rules --check`).
* **Tool tests**, each file on its own: the rules' ten test files and the building generator's
  three pass but for the two known upstream failures (`test_rules_parity.py`, V2;
  `test_compile_rules.py`'s mountain test, V4/V31), as before the merge.
* **The battles, photographed again** with the TEST build at round 4's spots, in round 4's
  battles: 138 maps - every cave, every outdoor map, the sea floor, the League's rooms, the
  rooms round 4 left at C, Birth Island and the Trick House's eighth puzzle (the places the
  overworld's round can change). All 138 drawn in 3D; each picture looked at beside round 4's
  (`tools/battle_env/review.json` `combined`, the checkpoint's report). 116 as round 4's
  picture; changed: the layouts the game shows (E13: Route 131's sea a level under the land as
  on every sea route, Sky Pillar's clean floors and top, Shoal Cave's entrance at high tide), the
  overworld's cave levels (Shoal Cave's inner room has its raised floor behind the battle, **C
  to B**; Meteor Falls' and Victory Road's battles stand on their floors with the steps round
  them), and thin lines along the Lavaridge relief (E14: Mt. Chimney, Jagged Pass, Fiery Path,
  Magma Hideout). **Classes now A 5, B 206, C 3, D 0**; the maps not photographed again (rooms
  the overworld's round does not change) keep round 4's class. No map moved down.
* **Fights to the end** with the combined TEST build (a strong party, the autopilot): all eight
  won and drawn in 3D, no crash - the four two-trainer battles (N37: Sootopolis Gym B1F, Victory
  Road 1F, the Abandoned Ship, the Trick House's seventh puzzle), Roxanne, Tate & Liza, the
  Multi battle beside Steven (N38) and a wild double on Route 102.
* **The freeze fix (E15)**: proved by the EmeraldTogether integration's launcher 1v1 on its 3D
  build (runs 8 to 11 passed with the same change); no link battle was run on this branch's own
  build here (the proof needs its two-trainer source saves, which this workspace does not have).
  Real trainers keep their backdrops: Roxanne's (a Leader's) and the Champion's battles
  photographed with the final TEST build.
* **The Windows game under Wine** (the checkpoint's stripped player exe, debug menus off): a
  wild battle in Granite Cave drawn in 3D, run from, back to the 3D field - no GL error, nothing
  in 2D, nothing refused; the field in Route 119's long grass, Slateport's roofs and Victory
  Road 1F's raised walkway (with the exe built before E15's one-line battle fix). At Jagged
  Pass beside the overworld's own exe (`native-wip-20261012-2`) and round 4's: the overworld's
  shows the same thin lines along the relief as this one (E14), round 4's none.

Levels, as AGENTS.md asks: compiled, launched, tested and working on the cloud computer
(software OpenGL; the Windows build under Wine). **Not verified on a graphics card**: no frame
rate is claimed - not the 200 frames a second at 1080p/1440p nor 180-200 at 4K (V39) - until the
owner's benchmarks run; the battle camera's glide has not been seen on a high-refresh display.

## Rollback

* The development game is a folder of its own (checkpoint `combined-dev-20261012-1`,
  `game\`): the launcher, its game and the saves elsewhere are not touched. The launcher
  (`EmeraldTogether`) still starts its own game.
* The overworld-only game: `native-wip-20261012-2` (its `EmeraldTogether` and `test-run`). The
  battle environments alone: `battle3d-env-wip-20261012-2`. The branches above are unchanged,
  so each restores from its own checkpoint's bundles.

## Next (the owner's decisions)

1. The graphics-card runs, whenever convenient: the overworld's benchmark
   (`native-wip-20261012-2\benchmark`) and the 3D battles' tests
   (`battle3d-test-runs\wip-20261010-4`). They no longer hold this branch back.
2. When the owner wants the combined game as the main line: `claude/native-graphics` can
   fast-forward to `claude/combined-dev` (if it has not moved; otherwise an ordinary merge).
3. E14 is the overworld session's (its relief's undersides). The EmeraldTogether integration
   can take E13's fix (`5699d58b3`, one line in `battle_capture.c`).
4. The UI and character branches meet this branch as they meet the overworld's and round 4's
   (their own COORDINATION notes and `battle3d-env-wip-20261012-2`'s).
