# Update 26 — three bugs found on the Windows PC

Reported after the first real-PC test of the Update 21–25 package: (1) the original GBA battle UI flashes after battles, (2) a crash when leaving the Pokémon
menu, (3) a black background in the first battle. Engine branch `claude/dev-update26-fixes-engine`, app branch `claude/dev-update26-fixes` (both cut from the
Update 21–25 branches, which are untouched; nothing merged into a default branch).

**Everything below was found and checked in a simulation on Linux (headless, software OpenGL, scripted key presses). None of it has been run on a real Windows
PC, and the crash in bug 2 was not reproduced as a crash: its cause was found by AddressSanitizer on the same sequence.** The Windows package needs the same three
sequences played again by hand (see "To check on the PC").

## Bug 1 — the GBA UI flashes after a battle (3D game with the native interface)

**Cause: UI-layer lifecycle, not a frame-compositing or renderer-handoff problem.** The native battle screen (`src/native_ui/screens/ui_battle.c`) decided it was
the screen in front by the battle's data: `gBattleStruct`, `gBattleSpritesDataPtr`, `gBattleResources`. When a battle ends, `HandleEndTurn_FinishBattle` frees all of
that and starts the fade to the overworld, but the engine's callback stays `BattleMainCB2` until the fade is done and `FreeResetData_ReturnToOvOrDoEvolutions`
runs. For the whole fade (about a second) the native screen let go, nothing replaced it, and the GBA's own layers (healthbox, message panel) were drawn over the 3D
view. That is the picture in the report. **Classic 2D (the plain GBA
renderer, no native interface) does not have this bug**, and its end-of-battle frames were checked and are unchanged.

**Fix:** the native battle screen now remembers it was live and stays up (drawing nothing new, hiding the GBA backgrounds) while the engine is still in the battle's
callback after the data is gone (`sTeardown`). Nothing about the battle itself, its animations, text, HP bars, results or the link code changes.

**Regression test:** `tools/pc_port/battle_end_check.py [--kind wild|trainer]` runs the 3D game through a battle and reads the per-change frame log
(`PKMN_DEBUG_FRAMES`): while the battle's callback runs the native screen must be `battle` on every frame, including at least one frame with a fade running, and
must be gone after the battle. Checked both ways: with the fix, a wild battle and a trainer battle (TRAINER_CALVIN_1) pass; with `ui_battle.c` put back to the Update 21-25 version the wild run
**fails** on two game frames (1590, 1624: "the battle's callback runs but the native screen is '-'", one of them mid-fade). Before/after pictures (window screenshots
every few frames from the freeing of the battle data) were taken for the report and kept outside Git (they are game art).

## Bug 2 — crash leaving the Pokémon menu

Windows treats a bad read as fatal where Linux often survives it, so the sequence (START → POKéMON → first Pokémon → SUMMARY → B → B → B) was run under
AddressSanitizer in the 3D game, twice in a row. It reported, in order of how close they are to the reported sequence:

1. **Reading uninitialised party-menu state (the cause that fits the report).** When the party menu returns from the summary screen it is set up with
   `Task_TryCreateSelectionWindow`, which builds the "what do you want to do" action list one frame later. In that first frame the native interface read
   `sPartyMenuInternal->numActions` and `actions[]` from the freshly allocated, never-written memory, and used a garbage value as a field-move number:
   `gFieldMoveInfo[garbage]` and then `GetMoveName(garbage)`, a wild pointer that the interface then tried to read as text (`party_menu.c`
   `PartyMenu_NativeUiState`, global-buffer-overflow in `FieldMove_GetMoveId`). Whether that lands on mapped memory is luck, which is why it is a crash on one PC and
   invisible on another.
2. The 3D view's far scenery read metatile colours past the end of a smaller tileset's metatile array (`scene_snapshot.c`, global-buffer-overflow), when the
   field came back after the menu.
3. The weather-sprite test read `sprite->template` of a party mon icon, a template that lives on a stack frame long gone (`battle_capture.c IsMapSprite`,
   stack-use-after-return).

**Fixes:** the party state reports the action list only once the task that takes input is running, and every entry is checked against its table
(`party_menu.c`, `ui_party.c`; PC-only code, the GBA ROM is byte-identical); the far-scenery colours are looked up on demand within the tileset's own length;
`IsMapSprite` no longer dereferences the template (it uses the sprite sheet the sprite was created on). After the fixes the same sequence runs clean under
AddressSanitizer, (a NULL-access trap run of the sequence before the fixes logged no NULL access, so it was not a NULL pointer).

**Diagnostics:** `crash.log` (written by `src/platform/crash_report.c` on any crash, next to the game) now also names the native screen in front when it
crashed (`native screen = …`), next to the fault address, the game's callbacks and the stack addresses (symbolise with `addr2line` against the exact exe).

**Regression test:** `tools/pc_port/party_menu_check.py` (needs the AddressSanitizer build `make -f Makefile_pc NATIVE_LINUX=1 SANITIZE=address DIORAMA=1`) plays the
sequence twice and fails on any sanitizer report. Before the fixes it aborted at the first return from the summary screen.

## Bug 3 — the first battle has a black background

**Reproduced (3D, from a fresh game, through the real story script).** Cause: Route 101's bag script fades the screen to black (`fadescreen`) before the starter
choice, then the first battle starts. The 3D battle stands on "the field as last seen with steady palettes" (`gl_compositor.c DioramaGL_GetBattleWorld`), and the
snapshot only counted a palette as unsteady while a fade was *running* (`gPaletteFade.active`). The field faded out whole, with the fade finished, counted as steady,
so the last steady field was an all-black one and the battle's world — ground, trees, sky — was black. It only affects the first battle in that story path
(every other battle comes after a normal fade-in), which is why it looked like "the first battle".

**Fix:** a normal fade that has run to its end (`y >= 16`) is now also "not steady" (`scene_snapshot.c`). The last steady field is then the one before the fade, the
real Route 101. No generic background or fallback is used. Part-way fades that settled (time of day, a dimmed menu) still count as steady, as before.

**Not the cause (checked):** missing terrain/textures at the first battle, 3D scene initialisation, the battle environment number (the default is grass and the Classic 2D
game shows the grass background on this path), and wild/trainer battles started after a normal field (3D stage drawn correctly in the simulation). **Classic 2D** was run
through the same story path: the grass background is correct, no black.

The always-on log line `Diorama battle: 3D on map G.N (wild|trainer)` / `drawn in 2D (reason) on map G.N` (one per battle, in the game's console and log) was added so a bad
battle background can be traced from a report.

**Regression test:** `tools/pc_port/first_battle_check.py` plays the story path in the 3D game, screenshots inside the battle and fails when the scenery beside the wild
Pokémon is black (before the fix: 0 % lit pixels; after: 100 %).

## Not affected

All changes are in the PC presentation layer (native interface, 3D compositor, crash report, debug scene). The GBA ROM hash is unchanged
(`f214735b…3387`), save data and the multiplayer protocol/state code are not touched; see the check results in the ledger.

## To check on the PC (not done by this session)

1. Fresh game, walk to Route 101, take the bag: the first battle shows the route behind it (3D), then play it to the end: no old UI between the end of the battle and the field.
2. Wild and trainer battles: same, at the end of each.
3. START → POKéMON → a Pokémon → SUMMARY → B → B → B, several times; also in Classic 2D. If it still crashes, send `crash.log` and the exe's build id.
