# Graphical PokéNav map (Update 18)

**Status: built; checked by looking at the rendered game screen on a Linux build with a headless display, and by native
self-tests and app tests. Not verified on a real Windows PC, in 3D mode, or with real players.** The text pages stay as the fallback.

## What it is
The Hoenn map the game already has (PokéNav > HOENN MAP, the fly map, and the wall map in Pokémon Centers) now also shows:

| Marker | Drawn as | Where it comes from |
|---|---|---|
| **Your own place** | the game's own Brendan/May icon, unchanged | the game, as before |
| **Other players** | the same Brendan/May icon, per the other player's gender, with its accent colours (hat band, shirt) replaced by a ramp for the player's roster slot: **Blue, Yellow, Purple, Orange** | the poses the game already receives from the host (`gMultiplayerMailbox`): map, x, y, for every connected player on any map |
| **World Event** (visible, awake) | the original red outline from the Battle Frontier fly icon, flashing | the world mailbox's event (already sent to every game) |
| **Mass outbreak** | the original pink fly-destination dot, flashing | new: the outbreak's map in the world mailbox's reserved bytes (host → companion → game) |

Nothing new was drawn: every sprite is the game's own art, recoloured at run time from its own palette. The outbreak and event
markers are borrowed art (see "Art still missing").

## Using it
* **D-pad** moves the map cursor as always (keyboard arrows or the game's keys; the game's own keybinds and controller apply).
* **SELECT** (full view) jumps the cursor from marker to marker: each other player in roster order, then the World Event, then
  the outbreak. The map's name box then shows where it landed (for example ROUTE 110, LILYCOVE CITY).
* **A** zooms in and out as before; the markers follow the zoomed map and scroll with it. Markers off screen are hidden.
* The markers refresh about every 1.5 s while the map is open: players moving, coming or leaving are redrawn.
* Players on one square (yours included) are fanned out a few pixels so each shows.
* Text fallback: PLAYERS > World and my base > Players and weather still lists everyone's place; a player's page now also says
  which colour their map icon is ("Map icon: Blue"; "Map icon: your own"); the Outbreak and Event pages say "Marked on the PokeNav map".

## Where a player is drawn
Exactly like the game's own icon: the map section of the map the player stands on, and the position inside it scaled from the
map's tile size (Routes 114, 121 and 126 split by position, as the original does). Inside a building or a cave the original uses
that building's *entrance*, which the host does not know for another player, so the marker is drawn in the **middle of the
map section**. Maps whose section is "dynamic" or a Secret Base (the base's real location is not known to others) are not drawn;
players there appear only in the text list. Only the Hoenn map is drawn on (Kanto/Sevii maps of the original are not part of this game).

## Permissions
Every connected player's place is already visible to everyone (their avatar appears wherever they are, and the text page lists their
place). There is no hide-my-location setting and none was added; the map shows exactly what the text page shows. A dormant World
Event (one still waiting for its condition) is not drawn, as it is not shown in the world.

## What was added
Engine (PC build only; the GBA ROM is byte-identical, sha256 f214735b…3387): `src/region_map.c` (markers, SELECT jump, refresh),
one-line hooks in `pokenav_region_map.c` and `field_region_map.c`, `Multiplayer_GetRemotePose` in `multiplayer.c`. Map ids that
arrive from the network are checked against a per-group map count table (`tools/pc_port/map_group_counts.py --check`), so a bad id
cannot read outside the map table. App: the outbreak's map in the world frame (`nav.outbreak.map`, validated), the world mailbox's
reserved bytes (`WorldInbound.outbreak`), the colour lines in the Players menu.

## Evidence
* `--selftest-pokenav-map` (8 checks): every map in the game either lands inside the map and its own section for any coordinates
  (including extreme ones) or is refused; ids that are not maps are refused; Routes 121/126 split exactly like the original; indoor
  places are the middle of their section; negative coordinates clamp.
* App: `test_world_mailbox` (outbreak bytes), `test_secret_bases` (protocol + nav view + menu lines), `test_world_companion`
  (outbreak place reaches the game's reserved bytes through the real host and companion).
* **Looked at:** with the debug scene (`PKMN_DEBUG_SCENE=pokenav`, see `include/platform/debug_scene.h`) the real PokéNav
  main menu was driven to HOENN MAP with scripted keys and the rendered pictures were inspected: own icon, three coloured players,
  the flashing red event outline and pink outbreak dot at the right places; SELECT jumping through all five markers with the name
  box following; zoom in, scrolling (markers move with the map, off-screen ones hidden) and back out; four players on one square;
  a player moving and another arriving while the map was open. (Screenshots are not committed: they are the game's art.)
* **Not tested:** real Windows, the 3D (Diorama) window, a real host with real players, a controller.

## Art still missing (exactly)
Nothing blocks the feature, but these would make it better and cannot be made from the game's own art:
1. A dedicated **World Event glyph** (an exclamation or star): the red outline is the Battle Frontier's marker, so a player may read
   it as a Frontier site.
2. A dedicated **outbreak glyph**: the pink dot is the fly-destination dot; on the fly map it can look like a visited town.
3. **Number or initial badges** for each player (the game does not receive other players' names; colours stand in, and the Players
   page gives the key). A badge needs a small digit sprite sheet (4 tiles).
4. A **help-bar string** for SELECT ("SELECT: PLAYERS"): the existing strings are full width; a new one needs a layout decision.
5. A cave/indoor marker style (the original blinks the player's icon in caves); approximated here by the section's middle.

## Limits
* Marker colours are keyed to the roster slot, so they stay the same for a player for the whole session but can change between sessions.
* Zoomed view: SELECT does not jump (the zoomed map scrolls instead of moving a cursor); use A to zoom out first.
* Up to five markers (three other players, the event, the outbreak): that is all a four-player world has.
