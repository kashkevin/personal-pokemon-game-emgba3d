# Visual and audio audit (Update 22)

**Everything here is a headless simulation** (software OpenGL under xvfb, dummy audio device). It says what the renderer and the
mixer *do*; it cannot say how it looks on a real monitor or sounds on real speakers. Pictures are kept in the session's scratch
folder, not in Git (no game art in the repositories).

## Tools built (engine repository, PC only)
* `PKMN_DEBUG_SCENE=field` (+ `PKMN_DEBUG_HERE=group,num,x,y`, `x<0` = middle of the map, `PKMN_DEBUG_HOUR`, `PKMN_DEBUG_SPECIES`): the
  overworld of any map from a new game, in the Classic 2D or the 3D executable.
* `tools/pc_port/visual_audit.py`: sweeps maps through the 3D executable and reports per map `3D`, `2D-FALLBACK` (with the object that
  made the renderer refuse the frame), `BLANK` or `CRASH`.
* `PKMN_DEBUG_SCENE=audio` (`PKMN_DEBUG_AUDIO=first,last,frames`): plays every song and sound effect through the game's own m4a
  mixer and measures its output per song (peak, RMS, frames with sound, clipped samples).
* `PKMN_DEBUG_SCENE=ffa` (Update 21) and the F12-path window screenshots (`PKMN_DEBUG_GLSHOTS`).

## 3D diorama: sweep of 29 maps (towns, cities, routes, sea routes, desert, ash route, underwater)
Result: **29 of 29 drawn by the 3D renderer, 0 crashes, 0 blank frames** (Rustboro, Slateport, Lilycove, Fortree, Mossdeep, Sootopolis,
Ever Grande, Oldale, Dewford, Lavaridge, Fallarbor, Verdanturf, Pacifidlog, Routes 102 104 105 106 110 111 113 115 119 120 123 124 126 128 131 134,
Underwater 124). Looked at as a contact sheet: terrain, buildings with roofs, water, trees, grass, shadows, the player and NPCs present
everywhere; no missing models or untextured areas seen at that size. **Not examined:** interiors, caves, the other 800-odd maps, night, weather
effects in motion, long play sessions (the sweep tool exists; each 3D map takes about a minute on this 4-core machine).
Quality presets **Low and Medium** (open item V22) were run on Dewford: both draw in 3D, Low without shadows, Medium with.

## Confirmed rendering limitation (not fixed): vehicles made of several sprite pieces force the 2D view
`Littleroot Town` right after the intro: the 3D renderer refuses the frame ("object gfx 94 unsupported sprite", the moving truck) and the
whole scene is shown in 2D with the soft fade while the truck is on screen. The same holds for every object that the game draws from
several sprite pieces: **Truck, Cable Car, S.S. Tidal, Seagallop, S.S. Anne, Submarine Shadow, Rayquaza (Sky Pillar)**
(`HasUnsupportedSubsprites`, `scene_snapshot.c`). Effect: the first minutes of a new game in front of the house are 2D, and the cutscene
vehicles are 2D scenes. It is a designed fallback (correct picture, no 3D), not a crash. A fix means building one texture from the
sprite's subsprite table in the object renderer (moderate work, 3D only); **owner decision**: fix, or accept.

## Classic 2D and the native battle screens
Looked at (Update 21 and here): intro, send-out, menus, target selection, move animations, status and faint sequences of the four-player
battle in both renderers; a 2v2 for comparison (unchanged); the Town Map with markers and a hidden-location peer (no marker, no crash).

## Audio audit: all 558 song numbers through the mixer, 150 frames (2.5 s) each
* **No crash, no clipped sample, no stuck song.** 80 song numbers (270-349) are silent because they are **unused numbers** in the table (no
  `MUS_`/`SE_` constant exists for them); every one of the 479 defined sounds produced sound. Twelve very short effects have under 10 audible frames
  (as expected for clicks): 23, 34-36, 38, 42, 70, 108, 115, 116, 252, 254.
* **Level (confirmed by measurement, fixed):** before the platform's volume stage, music peaks at a median of 0.063 (max 0.115) and
  effects at 0.041 (max 0.103); median music RMS 0.011. The old make-up gain of 2 left the loudest music near -18 dBFS: **the game was
  quiet on a PC** at full volume. The gain is now 4 (`src/platform/sdl2.c`): the loudest music peaks at 0.46, music plus the loudest effect
  at 0.86, still below full scale. The volume setting is still relative to it. **Needs real ears:** whether +6 dB is the right loudness.
* Not checked (needs ears): musical correctness of each track (instrument mapping), cry volume balance, loop points, the transition
  between songs and fades, the PC cry-volume setting.

## Missing art / assets
No new gap found. Known and documented elsewhere: the PokeNav event/outbreak glyphs and number badges (`docs/graphical-pokenav-map.md`),
battle-sprite packs (the GBA sprites are drawn when no pack is present: the log says "Battle sprites: no pack"), the 3D background/border
bitmaps (`BG.bmp`, `Border.bmp`, optional: the log says they could not be loaded and the game continues). Nothing was downloaded or invented.
