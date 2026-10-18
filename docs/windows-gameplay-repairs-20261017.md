# Real-PC gameplay repairs (2026-10-17)

The owner played the packaged game on Windows after the Update 31 merge and reported ten problems, then asked for one owner
per piece of interface (native or the game's, never both) and a resolution check. Branches (before integration):
app `claude/fix-windows-gameplay-app`, engine `claude/fix-windows-gameplay-engine`, both from the Update 31 defaults
(app `a9c7ca3`, engine `e4252d4`). Every change is PC-only (`PORTABLE` / Diorama / native interface code); the GBA ROM
stays `f214735b…3387`.

**Integration (final, 2026-10-18).** Engine default `claude/emeraldtogether-combined`: `e4252d4` -> `0493b77b79` (first
round, 2026-10-17) -> `cf7cba7676` (vehicles, 2026-10-18), fast-forwards. App default `claude/emeraldtogether-combined-app`:
`a9c7ca3` -> the tested repair branch `claude/fix-windows-gameplay-app` (fast-forward; the commit adding this note and its
descendants). Rollback tags: `rollback-before-gameplay-repairs-20261017` (engine `e4252d4`, app `a9c7ca3`) and
`rollback-before-vehicle-fixes-20261018` (engine `0493b77b79`). The first round's app merge was blocked by the session's
permissions (2026-10-17) and finished here; until then the engine default ran with the Update 31 app (compatible: the new launch
arguments are optional). No force push, no workflow file changed. After the merge: on a clean checkout of the merged app default
(`50913fe`) with the merged engine, the app suite passed (2114 passed, 0 failed, 1 skipped); `check-abi`, `check-rival`,
`check-catch-reconcile` and `check-clock` passed at the merged engine head; tags `emeraldtogether-gameplay-repairs-20261018` on
both heads.

**Windows package.** The cloud session cannot start or read GitHub Actions (the API answers 403). Owner: Actions ->
`windows-package` -> Run workflow: branch `claude/emeraldtogether-combined-app`, mode `full`, `engine_ref` `cf7cba7676fa951e9789433895f729446681b6a2` (the engine
default branch is that commit), version blank (or a label), runner `windows-2022`, `expected_rom_sha256`
`f214735b64e113fd10730eacca5764d757f2c93a3685230aa905af7a7cdd3387`. Not built or checked by CI yet. The Node.js 24 action change
(U31-16) is still the owner's patch; `bios.c` licensing is a separate open question.

How the problems were found: the engine's debug scene (`PKMN_DEBUG_SCENE=field`, `PKMN_DEBUG_HERE`, scripted keys,
`PKMN_DEBUG_GLSHOTS` window captures, game-frame timed) on the Linux 3D and Classic 2D builds of the same source under
Xvfb (Mesa llvmpipe), compared frame by frame. No real GPU was available; see "Still to check on the PC".

## 1. Map loading and rendering

| Cause found | Fix (engine) |
| --- | --- |
| **People, trainers and items popped into view mid-screen.** The GBA hides an object's sprite once it leaves its own 240x160 picture (`UpdateObjectEventSpriteVisibility`: invisible when off screen), about 6 rows ahead and 7 columns to the side; the 3D snapshot treated that as invisible although the 3D camera shows further. Measured on Route 110: a cyclist appeared between two captures 8 game frames apart on a bridge already in view. | `scene_snapshot.c`: an object hidden only by the GBA picture's edge stays visible; `gl_object_renderer.c`: such an object is optional (drawn when it can be, left out otherwise - it can never drop the 3D view). Spawning is unchanged: no trainer sees further, no object slot is used that the GBA would not use. |
| **Lit windows, the walkers' shadows and the see-through silhouette stayed on a black screen** through every door, warp and fade (about 3,650 lit pixels on frames the game had faded to black, in the evening). They are the renderer's own colours, not the palette's. | The snapshot carries the game's fade (`gPaletteFade`'s normal fade, or background palettes held uniformly faded while a warp loads the next map); window light (`gl_lamps` night strength) and the object shader's shadows and silhouette follow it. Night windows with no fade are unchanged. |
| **Using a PC took the Pokemon Center's modelled room apart** (black notches in the back wall, the counter's arm gone, the room flickering as the screen blinked on) - see 3. | `scene_snapshot.c` `SameObject`. |

Examined and not changed: terrain chunk streaming (an A/B of the deferred far-chunk builds against building every chunk at once
showed the same scenery; nothing missing); door warps stay in 3D (the brief boxed 2D frame appears only at a debug start);
black space outside a map's edge (interiors) is kept as it is.

Remaining (not fixed): objects still *spawn* only within the GBA's window (7 rows north), now near the top fifth of the 3D
picture instead of mid-screen - widening it would change trainer sight and the 16 object slots (a gameplay change). Seven
large objects (the moving truck, S.S. Tidal, Cable Car, Seagallop, S.S. Anne, submarine shadow, Rayquaza on Sky Pillar) use
composite sprites the 3D view refuses, and while one is on screen the whole view falls back to the boxed 2D picture
(KNOWN_ISSUES V1 family; none in the areas played so far).

## 2. Stuck Zigzagoon on Route 101

Cause: Birch's bag script hides the Zigzagoon with `removeobject` (its flag `FLAG_HIDE_ROUTE_101_ZIGZAGOON`). Update 31's
streamlined introduction applies the post-rescue state from the script's `setflag` lines only, so every new character found
the Zigzagoon jogging in place on Route 101 with Birch, the bag and the trigger gone - nothing could ever move it.

Fix: the introduction sets the flag (`multiplayer_rival.c ApplyIntroPostState`); characters already made are repaired when
the object would spawn (`MultiplayerRival_HidesObject`, offline too) or was restored from a save
(`MultiplayerRival_TryStartFieldScript`), only when Route 101's state is 3 or later (the original never shows it then).
Before the rescue (states 0-2, `PKMN_ORIGINAL_INTRO=1`) the original scene is untouched. App: the intro table
(`docs/update31/intro-post-state.json`) lists the flag, and `check_rival_catalogue.py` now requires the hide flag of every
object an original script it cites removes (it reports this omission on the old table). An audit of the other intro scripts'
`removeobject`/`addobject` found no other gap.

## 3. Pokemon Center PC

Cause: switching a PC on replaces its metatile with the lit one (`PCTurnOnEffect_SetMetatile`); the 3D snapshot counted that
as a change to the room's layout, and every modelled piece over those cells was dropped: the PC model, the counter's east arm,
the back wall (black notches), the lit screen standing flat right behind the player, who was then drawn as the blue see-through
ghost. The screen blinks while booting, so the room flickered.

Fix: a PC's on and off metatiles (Pokemon Center, Brendan's and May's PCs) are the same object for the building models. The
modelled PC keeps its drawn (unlit) screen while in use.

Storage itself was exercised through the native storage screen with a two-Pokemon party: deposit (Zigzagoon to Box 1, party
1/6), the "Continue BOX operations?" prompt, withdraw (back to the party), leaving the PC (party 2, Box 1 empty), the box list
(JUMP), cursor and box-title navigation. Data matched at each step (`PKMN_DEBUG_STORAGE_AT`). No defect found there; storage
rules are the engine's own (`pokemon_storage_system.c`) and the save format is unchanged.

## 4. Battle sprites and UI clipping

Cause: the GBA lays a battle out over its text box (rows 112-159): the trainer's back picture is drawn from row 48 to row 112
and its art ends there, cut at the waist, as large Pokemon back pictures end on that line too. With the native interface the
text box is gone, and the 3D battle placed the picture's bottom (row 160) on the window's bottom edge, so the player's trainer
- and any large back picture - ended cut off flat 48 rows above the bottom of the window, over the 3D ground.

Fix (`gl_battle.c BattleLayout`): when the native battle HUD replaces the text box (`NativeUi_ReplacesBattleTextBox`, decided
by the battle's type from its first frame), row 112 is the top edge of the HUD's bottom panel (the message plate, the commands,
the moves: the bottom 76 rows of the interface's 360-row design, `NativeUi_BattlePanelTop` at the window's size): back pictures
end behind it as they ended behind the GBA's box, and the world (laid out from the same layout) moves with them. Rows 112-159
only ever held what the opaque box covered. The GBA presentation (native interface off, or battle types the HUD does not
support) is unchanged.

A first version put row 112 on the window's bottom edge. It was checked at 1264x711, where the HUD's message plate was not
drawn at all (see 10), so it looked right; at 1280x720 and larger the lower half of the trainer and of the Pokemon stood behind
the plate. The resolution matrix found it; the panel anchor replaced it. Checked: trainer intro and send-out, a wild battle, the
action menu, at 1280x720, 1920x1080, 1024x768, 2560x1080, 1264x711 and 3840x1080 (see 10); earlier (first version): Swampert's
large back picture, a double battle (Kate & Joy), the four-player free-for-all.

## 5. Grass

| Cause found | Fix |
| --- | --- |
| **Overworld:** every tall-grass cell stood two half-tile cards over the same blades drawn flat on its ground, so each blade showed twice a quarter tile apart and a field of grass became dense dark stripes. | Tall grass is the flat GBA art, as the GBA, the 3DS port (the renderer's reference) and Classic 2D draw it; where someone stands in it, its front blades stand as one card in front of their feet (knee-deep and rustling, as the GBA's grass effect covers a walker). |
| **Battle:** the 3D battle keeps its world as a picture and redraws it only when animated tiles change (every 1-32 game frames, by the GPU's pace) while the grass swayed by a running clock, so its blades jumped between poses a few times a second (16-18% of a grass patch changed at each redraw). | The battle's world is drawn with still grass (0-0.7% change between captures: a floating glint). |

## 6. Bag pocket switching delay

Cause: the native bag draws the pocket from `gBagPosition.pocket`, which the game changes only when its own pocket switch ends:
`Task_SwitchBagPocket` first repaints the hidden GBA item list row by row, 16 frames (about 0.27 s), then switches. Every press
of left or right reached the player a quarter of a second late.

Fix (`item_menu.c`, PC only): with the native bag on screen the repaint runs at once (the same rows and pocket name are
written) and the switch completes in the same frame. The classic picture (2D, or the native interface off) keeps its slide.
Measured (`PKMN_DEBUG_BAG_LOG`): RIGHT at game frame 700 -> pocket changed at 702 in 3D (native bag), 718 in Classic 2D.
`gameplay_repair_check.py` checks at most 3 frames.

## 7. LINK OFFLINE while hosting

Cause: two. (a) Hosting never started: the setup crash (8) stopped the owner in the character-setup game, which runs without a
bridge by design, so its pause menu could only say OFFLINE. (b) The pause menu's LINK panel knew only "bridge or not" and
"connected or not": the setup game, a host still starting and a host whose session never came up all looked alike.

Fix: the game shows its own link status (engine `MpBridge_LinkState`): OFFLINE (no bridge: single play), SETUP (the launcher's
character setup: "Save, then close the game"), CONNECTING ("Starting the world..." for a host, "Joining the world..." for a
friend), NOT CONNECTED after 20 s without a world session ("See the launcher window"), HOSTING / CONNECTED ("Waiting for
friends" or the players nearby), LINK LOST after a session ended. The launcher passes the two facts the game cannot know as
arguments: `--link-role host|join` (PlayerRuntime, from LauncherSession) and `--setup` (DraftRuntime). Arguments, not
bridge-file lines: an older game ignores unknown arguments but refuses unknown bridge lines, so a newer launcher never stops an
older game from starting. Checked: the four offline states with the harness (`gameplay_repair_check.py`), and a real host
session (the app's LauncherSession and companion with the Linux game): "LINK HOSTING - Waiting for friends".

## 8. "Setting up your character could not finish"

Cause (reproduced with the real Linux game and the app's own code: `create_world`, `create_character`, LauncherSession): the
enrollment launch (the game opened on the new character, CONTINUE) crashed at boot, exit 139. The launcher connects the companion
before it starts the game, so the world's messages arrived while the game was still booting; `MultiplayerWorld_Tick` re-sent the
catch record and read a variable through the save pointer that did not exist yet (`VarGet` <- `CatchRecordEvent` <-
`RepostCatchRecord`). The app then made it worse three ways: every error inside the setup was flattened to `setup_failed`; nothing
was recorded; and the abandoned attempt (`pending-enrollment.json` and its copies) made every later try refuse with
`recovery_required`, shown as the same message - the player could never finish.

Fix (engine): `Multiplayer_Tick` waits until the save blocks exist (PORTABLE). Test: `--selftest-catch-reconcile` case 7 crashes
(SIGSEGV) without the guard and passes with it.

Fix (app): the game's end keeps its own code (`game_failed` for a non-zero exit, `game_closed` only for a game the player
closed); the menu writes `shell/last-error.txt` with the traceback, the newest launch folder, its `crash.log` and the end of its
`runtime.log` (never `bridge.txt`, which holds the launch token) and says the character made was kept; and the in-game menu's
setup (host and friend) restarts an abandoned attempt: when the profile holds only this exact approval's intent and copies (no
grant, export, trade or battle journal, no checkpoint sidecar, no receipt, nothing unknown) and the server has no character and no
pending trade, the attempt is moved into `abandoned-enrollments/<UTC time>/` (kept, never deleted) and enrollment starts again
from the approved source. Anything else still waits for recovery. The launcher's explicit setup window keeps the old behaviour.

End to end (real Linux game, real app code, `repro_resume.py`): first attempt with the enrollment game crashing -> `game_failed`
("The game closed unexpectedly...", not "could not finish"); the menu's "Continue setting up my character" -> enrolled, the
abandoned attempt kept; Host This World -> running, connected, is host, and the game shows LINK HOSTING. Before the engine fix the
same flow (no simulated crash) crashed at boot; after it, it enrolls.

## 9. Clock

What the game does: offline (single play, character setup) its clock is the PC's; connected it is the world's: the host's
persistent world clock, 12x real time (a world day every two real hours), running only while someone is connected (owner
decision of Oct 9, `balance.py`). The daily reset and berries follow real time (Phase 11). Checked: `check-clock` (45 checks),
`test_shared_world`.

Changed: a new world starts at 12:00 noon (it was 08:00): `BALANCE.clock_start_seconds`. Only a world without a clock gets it;
existing worlds keep their stored time (test). The character-setup game (`--setup`) now starts at 12:00 too, so a new world's
first scenes are at noon rather than at whatever the PC's clock says (engine `SiiRtcPc_StartAtHour`; only that run - the
introduction sets the save's clock offset to 0 from what it read, so the character's own clock offline is still the PC's).
Checked: the setup game reads 12:00 at game frame 300 (`gameplay_repair_check.py`).

Rate (owner-confirmed after the first report): **12x** - 1 real minute = 12 world minutes, 5 real minutes = 1 world hour,
10 real minutes = 2 world hours, a whole day and night = 2 real hours while the clock runs. `BALANCE.clock_rate = 12` (unchanged).
There is one clock: the host's `SharedWorld` keeps the world seconds and persists them; each companion forwards them to its game
(extrapolating at most 5 s at the same rate between records); the engine shows exactly those seconds (`RtcCalcLocalTime`:
`MultiplayerWorld_GetSeconds`) - it has no rate of its own. Offline the game's clock is the PC's; the daily reset and berries
follow real time (Phase 11).

Checked (final): `test_shared_world` simulates a whole day from noon (injected clock): +12 world minutes per real minute, +1 hour
per 5 real minutes, the game's own hours in order (day 13-17, evening 18-20, night 21-3, morning 4-10, day), noon again after 2
real hours; the clock pauses with nobody online, survives a host restart, an existing world's clock is never moved to the new
start, and damaged clock data (negative, text, fractional, beyond the 32 bits the game adds its day origin to) is repaired to
noon with the bad value kept in `metadata.clock_repaired_from` (a valid clock is never touched). `test_world_companion`: both
players' games get the host's time, marked valid. `check-clock` (58 checks): offline, connected, a world day in two real hours,
disconnected, reconnected. End to end (real Linux game, new world, hosting): the pause menu read **12:05 PM, LINK HOSTING**
(`hosting-new-world-noon.png`). Lighting at 06:00, 12:00, 19:00, 22:00 in Classic 2D and 3D: dawn, day, evening, night in both
(the same game time drives both; the 3D view adds its own light on top). The streamlined introduction sets the clock itself
(`FLAG_SET_WALL_CLOCK`, the offset from the time it shows); no bedroom clock scene is needed (`rival_check` intro cases).

## 11. The large vehicles (3D falling back to 2D)

The seven named in the first report, checked one by one in this Emerald build:

| Vehicle | How the GBA draws it | Before | After |
| --- | --- | --- | --- |
| Moving truck (Littleroot, 2) | 48x48 in 12 OAM parts | refused: whole view boxed 2D | 3D (one card) |
| S.S. Tidal (Slateport, Lilycove, Southern/Faraway/Birth Island, Navel Rock, Battle Frontier) | 96x40 in 15 parts | refused: 2D | 3D; sails off in 3D |
| Submarine's shadow (Slateport harbour, Aqua Hideout B2F) | 88x32 in parts | refused: 2D | 3D; the escape scene in 3D |
| Cable Car (both stations) | one 64x64 part, centred | already 3D | 3D (unchanged) |
| Rayquaza (Sky Pillar still and awake, Sootopolis) | one 64x64 part, centred | already 3D | 3D (unchanged) |
| Seagallop | FRLG graphics: not compiled into this Emerald game | - | its table (one centred part) is the supported path |
| S.S. Anne | FRLG graphics: not compiled into this Emerald game | - | 128x64, off-centre: covered by the same path (unit test) |

Root cause (one for all): the 3D view drew every object as one OAM frame of the sprite's own shape and refused a sprite whose
subsprite table is anything but that frame cut in strips; one refused object on the GBA's screen made the object pass fail and
the whole field fell back to the 2D picture while the vehicle was in view.

Fix (engine `62f086c0f1`, PC only): the parts are assembled into one picture (each part's tiles from the current frame image, or
VRAM for a sheet, put where the GBA puts the part about the sprite's centre, the first part in front), laid out as one OAM frame of
that size (up to 128x64; the frame buffer grew from 2048 to 4096 bytes), drawn as one card standing where the picture is
(an off-centre picture is shifted), mirrored as a whole for a flipped sprite, animated and moved as any object; the parts' OAM
entries count as the field's, never as interface under a text box. No vehicle is hidden, blanked or replaced; scripts are untouched.
Classic 2D is untouched (its executable is byte-identical to before this change).

Checked: `test_sprite_frame` (the four composite sizes, flips, refusals, frame keys, placement); `gameplay_repair_check.py` 12
vehicle scenes - each vehicle on the field, nothing refused, 3D throughout, the submarine's escape played to its end
(`VAR_SLATEPORT_HARBOR_STATE` 2) and the S.S. Tidal's departure from Southern Island to Lilycove; before/after under Wine with the
Update 31 exe and the new exe at 1280x720, 1920x1080, 2560x1080 and borderless fullscreen (3840x2160): before, every vehicle
"refused (unsupported sprite)" and boxed 2D; after, none refused, 3D (`vehicles-before-after.jpg`).

The Cable Car *ride* (talking to the attendant) is a separate full-screen GBA cutscene (`cable_car.c`: its own backgrounds and
sprites, no map), shown as the GBA picture like every other cutscene; it is not the 3D view falling back and it plays to its end
in the 3D game. A 3D ride would be new work.

## 10. Resolution

The 3D view fills the window; the game's 240x160 picture (text boxes, menus, 2D scenes) is drawn at a whole-number scale
(`DisplaySettings_PixelScale`: as large as fits within 8/9 of the height) - centred over the field, on the window's bottom edge
in a battle; the native interface is drawn at `min(W/640, H/360)` (at least 1) over a canvas of the window's own size.

Matrix (Xvfb, windowed, Linux 3D build; before = the Update 31 Windows exe under Wine, after = this branch): 1280x720,
1920x1080, 1024x768, 2560x1080, 1264x711 (a laptop's windowed client area), 3840x1080; overworld (Route 101), Pokemon Center
(Oldale), PC storage menu, wild battle (intro, send-out, a move), trainer battle. Pictures: `windows-gameplay-repairs-matrix/`
in the session outputs.

Found and fixed:
- At window heights under 720 (x1: 1264x711) and at 3840x1080 (x3, canvas 1280 wide) the battle's message plate was never
  drawn: a shape as wide as the canvas is larger than the interface's 1024-pixel atlas and its allocation failed silently. The
  battle's text stood on the 3D scene with no plate. `UiG_Mask` / `UiG_Paint` now draw such shapes as atlas-sized tiles of the
  same picture (engine `ui_draw.c`).
- The battle's back pictures stood under the HUD's bottom panel at 1280x720 and up (see 4).

Examined, no defect: the overworld, Pokemon Center and storage menus at every size (picture centred, interface within the
window, no stretching); 1024x768 (4:3, x2 interface with a 512-wide canvas: the bag and storage panels fit).

## UI ownership

Rule (as built, now checked): each piece of interface has one owner. With the native interface on, a native screen that takes a
state hides the game's own windows (`DIORAMA_PICTURE_HIDE_UI`) or the whole picture (`HIDE_ALL`); what no native screen draws
(the map name pop-up, a money box, lists, PokeNav calls, rows a script builds itself) keeps the game's window layer over the 3D
view - never both at once.

Diagnostic: `PKMN_DIORAMA_UI_OWNER=1` logs each change of owner (native screen, 3D drawn, the game's picture drawn, the game's
windows drawn and how many of their pixels show) and marks `LEAK` when the game's windows or picture show under a native screen.
Swept: talking to a person (Oldale Pokemon Center), a sign (Route 101), an item ball (Route 102), the nurse's healing (YES/NO),
the PC and its storage menu, the mart (menu, buy list, back), the start menu, a door, a wild and a trainer battle. Result: no
LEAK. At the first 1-5 frames of a message the game's window layer is drawn before the native box takes over, with 0 visible
pixels (the box is not on the layer yet); between the mart's menu and its buy list the game's picture shows for 3 frames while
the screen is faded to black (correct: black). The map name pop-up is the game's (no native one).

## Tests

See TEST_LEDGER.md, section "Real-PC gameplay repairs". New: `--selftest-rival` +5 checks (Route 101), `test_props`
tall-grass checks, `--selftest-catch-reconcile` case 7 (the boot crash), `tools/pc_port/gameplay_repair_check.py` (fade, battle
grass, PC room, bag timing, link status, setup clock; fails on the build before the repairs, passes after),
`check_rival_catalogue.py`'s removed-object rule, `tests/test_rival_catalogue.py`; app: `test_native_runtime` (link role and
setup arguments), `test_launcher_setup` (codes kept, abandoned attempts restarted only when safe), `test_character_creation`
(exit codes, a friend's retry), `test_shell_app` (the crash message, the crash report, the next try), `test_shared_world` (noon
start, existing worlds kept).

Second round (vehicles, clock, integration): `test_sprite_frame` composite vehicles; `gameplay_repair_check.py` 12 vehicle
scenes; `test_shared_world` (a simulated 12x day from noon; damaged clock data repaired); `test_world_companion` (one shared
time); `test_character_creation` (a crash mid-request is the game's end); the grass check's patch moved off the HUD. Results:
TEST_LEDGER.md, section "Vehicles in 3D, the confirmed 12x clock, final integration".

## Still to check on the PC (real GPU, real window)

- Vehicles in 3D: Littleroot's moving trucks (a new character does not see them: the introduction hides them), the S.S. Tidal
  at Slateport and Lilycove (after the Elite Four) and its departures, the submarine leaving Slateport's harbour, the Cable Car
  stations and ride, Rayquaza on Sky Pillar and in Sootopolis - the view should stay 3D, the vehicle whole and sharp, in
  front of what it is in front of; try a small window, a wide window and fullscreen.
- The clock: from a new world's noon, about 5 real minutes per game hour; evening near 18:00 (30 real minutes), night at
  21:00 (45 minutes); two players should see the same time; close and reopen the host: the time continues.

- Walk Littleroot -> Route 101 -> Oldale -> Route 103 and Route 102 in 3D: people, items and trainers should be on the ground
  before you reach them (they now appear near the top of the picture at the latest); no flashes at map edges.
- Go into and out of buildings in the evening: the screen should go fully black, with no lit windows or blue shadows left on it.
- Use a Pokemon Center PC: the room should stay whole (counter, wall, PC behind you); deposit, withdraw, move, change boxes;
  save, quit, continue: the boxes should be as left.
- Battles: your trainer's and Pokemon's backs should end just behind the top of the message panel, nothing cut in mid-air
  and nothing hidden under the panel; the message plate should be there at every window size (try a small window too);
  check a single, a double and (with friends) a free-for-all.
- Bag: left/right should change pockets instantly.
- Host a world: the pause menu's LINK should say CONNECTING, then HOSTING; a friend's: CONNECTING, then CONNECTED.
- Create a character in a new world: the setup game and the first hosted session should both be at 12:00 noon; if the game
  crashes during setup, the message should say so, `shell/last-error.txt` should name the launch folder and its `crash.log`,
  and choosing the world again should continue the same character.
- Tall grass should look like the GBA's, with grass in front of your feet when you stand in it; battle grass should not jitter.
- An existing character that saw the stuck Zigzagoon: walk onto Route 101 - it should be gone; a new character never sees it.
