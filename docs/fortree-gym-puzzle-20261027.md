# The Flying-type Gym's puzzle in 3D (2026-10-27)

The owner's report: the Flying-type Gym's puzzle is invisible. Nothing here is packaged.

Where a result comes from: **L** this Linux machine (real game processes of the 3D and Classic 2D test builds; the 3D
view through Mesa's software OpenGL). Nothing here was tried on Windows or on a player's PC.

## Which gym

From the game's own data, not assumed: the gyms in `data/maps/map_groups.json` are Hoenn's eight and Kanto's eight
(the `_Frlg` maps). The only leader with a Flying-type team is Winona (`TRAINER_WINONA_1` in `src/data/trainers.party`:
Swablu, Tropius, Pelipper, Skarmory, Altaria), in **Fortree City Gym** (`MAP_FORTREE_CITY_GYM`, group 12 map 1). Its
puzzle is the rotating gates (`src/rotating_gate.c`, `PUZZLE_FORTREE_CITY_GYM`: eight gates). The Kanto gyms have no
Flying-type leader. The same gates make the Trick House's sixth puzzle (eleven gates).

## What was wrong

The gates are sprites that move with the map, not object events. The 3D view drew object events and a short list of
named effects (healing machines, a trainer's "!", a shiny's twinkle) and left every other map sprite out. In the
Classic 2D game the gates showed; in 3D the room looked open while invisible arms stopped the player or swung as they
walked. The GBA code also makes only the gates within its own screen and two tiles round it, while the 3D view sees
the whole room.

## What changed (engine `bb8ef78f`, PC only; the GBA ROM unchanged)

* The 3D snapshot takes the gate sprites (`scene_snapshot.c` CopyEffects, `RotatingGate_IsGateSprite`) as pictures
  laid on the ground, placed by their pivot (a corner between four cells), including those the GBA hides only for
  being off its screen.
* The 3D view draws each one flat on the floor (`gl_object_renderer.c` DrawOnGround), turned by the sprite's own
  rotation, so a gate swings in 3D exactly as it swings in 2D while being pushed. It is stacked in thin layers up to
  a low rail's height, darker below and lit on top, so the arms stand as rails rather than lines painted on the floor.
* On the PC every gate of the puzzle is made at once (the GBA's hiding of the off-screen ones is unchanged).

## Tests (L)

* Pictures before and after, the same place in both views: the gate left of the door was in the 2D picture and
  missing in 3D; after, it stands in 3D where 2D draws it. The Trick House's sixth puzzle: all of its gates drawn in
  3D (11), matching its 2D picture.
* **The puzzle played through in the real game**: a route from the door to Winona was found with the game's own gate
  rules ported (`CheckForRotatingGatePuzzleCollision`, `RotatingGate_CanRotate` with `BUGFIX` as this build has it)
  on the gym's own map blocks: 96 steps, pushing the gates. Walked in the 3D and the Classic 2D test builds with
  frame-exact keys (the gym's trainers marked as already beaten, so none walks into the path); in both the player
  reached the tile below Winona at the predicted frame, talked to her and her battle began (3D: her Swablu on the
  gym's 3D battle stage). With a level 100 lead using Ice Beam her battle was won in both views: Classic 2D "received
  the FEATHER BADGE from WINONA", 3D the prize money (3,000 to 6,300) and "Obtained the TM40!".
* `make -f Makefile_pc DIORAMA=1 check-diorama` passes; `check_gba_lines.py` 0 moved lines; GBA ROM `f214735b...`
  unchanged.

## Not done

* The rails are the gate's own picture stacked, not modelled posts and bars; a modelled gate would need art.
* Not tried with the gym's trainers battling along the way, on Windows, or on a player's PC.
