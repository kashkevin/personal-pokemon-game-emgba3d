# The 3D object audit (2026-11-14)

The owner asked (2026-11-14) for the visual cleanup to go beyond terrain: railings, fences, bridges, stairs,
furniture, doors, windows, signs, posts, roofs and other indoor and outdoor objects - flat or blocky shapes that
should have depth, gaps, floating objects, clipping, mismatched heights, stretched textures, wrong shadows, objects
hiding the player - keeping the art direction, collision, walkable paths, interactions and gameplay, with targeted
models or rendering fixes rather than changes to terrain across the game. This is the audit; the fixes are listed
under each class as they land.

## How it was looked at

* **Places**: 363 - every place of the geometry check's tour that has objects (towns, routes, every room a player
  reaches, the Frontier's facility rooms through their facilities), one player position each.
* **Cameras**: `a` (the adventure camera's framing, pitch 42 degrees - what the player sees) and `c25` (the same
  framing at pitch 25 degrees - low, where a flat object shows as flat and a standing one keeps its height).
* **Build**: the Linux 3D test build (`NATIVE_LINUX=1 DIORAMA=1 BFX_TEST=1`), engine `2ebe2dca`, the default trees,
  Mesa's software OpenGL (llvmpipe) under Xvfb. **Not a graphics card and not Windows.**
* **Review**: each place's two pictures side by side (347 sheets) split among six reviewers, each reporting what
  it saw with a box per defect; the last 16 places (Frontier facility rooms, Trainer Hill) by me. A reviewer's
  report is a claim: below, **V** marks what I checked myself (from crops of the pictures, and for the flat walls
  the cells the renderer builds from), **R** what is so far only a reviewer's report.

## What was found, by class

### 1. Rooms with no 3D model: walls, doors, windows, counters and railings lie flat on the floor (V)

The renderer stands a room up from a model: the 3DS project's models (the Pokemon Centers, the Marts, the houses)
and the rooms cut by hand here since MS-164 (`tools/diorama_buildings/furnished_room_specs.py`: the Game Corners,
the Frontier's lounges and some lobbies, the reception gate, ...). A room with neither is drawn as its floor: its
back wall, the doors, lifts, windows, clocks and paintings on it, its counters and its railings are pictures on the
floor plane - they slant with the floor's perspective from the player's camera and shrink from a low one. Checked:
the cells of 59 rooms carry no model at all (the probe's `model` column), and the generated rules stand art up as
"pixel objects" in 14 layouts only (33 objects), none of these.

Seen (V: the Department Store's floors and rooftop, the Museum's 1F, the Battle Arena's corridor - its island wall
of shoji screens, impassable, laid flat around the player's path; R: the rest):

* Lilycove: Department Store 1F-5F (back wall with the lift and its floor sign, windows, stair doorways; the
  ankle-high counters and flat tills; 1F's stairs), the rooftop's railing, the Museum 1F/2F (gallery walls and
  paintings, statues, picture stands), the Harbor (railings round the dock, back wall), the Contest Lobby
  (counter, terminal, machine) and the Contest Hall, the Pokemon Trainer Fan Club (back wall, posters, panels).
* Slateport: the Harbor, the Oceanic Museum 1F/2F (glass cases flat under tall shadows), Stern's Shipyard 1F/2F
  (tables, desks, stools, girders - people stand on the flat stools), the Pokemon Fan Club (back wall, TV units),
  the Battle Tent's lobby and corridor (as Fallarbor's and Verdanturf's).
* The cable car stations (Route 112 and Mt. Chimney: railings round both pits, back wall, sign, ticket machine,
  bin), the Cycling Road's two gates (back wall, clock, notice), the Day Care (counter), the Safari Zone's entrance
  (counter, chairs), the Fossil Maniac's tunnel, the S.S. Tidal's corridor, the Trick House's corridor and puzzles
  5 and 8 (back wall, exit).
* The Battle Frontier: the Arena's corridor (V) and lobby, the Dome's corridor and lobby, the Palace's corridor, the
  Pyramid's lobby, the Tower's corridors, lift and multi partner room; Trainer Hill's entrance, floors, lift and
  roof. Ever Grande City's halls 1-5 (their stairs' levels stand since MS-164's update; walls and railings R).

**Fix**: cut these rooms by hand as MS-164 cut 24 rooms - each wall its drawn face, each counter and table its
drawn front's height (low enough to see who stands behind it), plants and posts cards, every piece proved pixel
for pixel against the drawing (`gen_voxel_buildings.py --verify`) and looked at from the game's camera. Most
visited first: the Department Store, the Museum, the harbors, the cable car stations, the Cycling Road gates, the
Contest rooms, the Battle Tents, then the Frontier's and Trainer Hill's rooms. Collision, warps and events are
not touched (a model is drawing only).

### 2. Furniture left flat inside modelled rooms (R unless marked)

Chairs, stools and beds in the Abandoned Ship's cabins (beds painted upright on an alcove's front in some), the
Rustboro Pokemon School's desks, the S.S. Tidal's cabin chairs and beds, Wanda's bed, the Pokemon League 1F's
counters (V: a low slab, the nurse seen whole above it), the Contest Lobby's counter (V), the Cove Lily Motel's
cup tables (V: a tall box with a thin strip on one end, unlike the room's other tables), the Space Center 1F's
stools on its tables, Professor Birch's Poke Balls sunk in the table, the Pretty Petal shop's counter, the Battle
Tent lobbies' PC (V, Fallarbor: lying with its screen up), the Lilycove Department Store's stands and tills (V).
**Fix**: per room, in its model's spec (the house kit's pieces or a hand-cut room).

### 3. Model artifacts (V unless marked)

* **Outline fragments by potted plants**: dark outline pixels of a plant's drawing left as loose bits on the floor
  or in the air beside it (V: Cozmo's house, the Move Relearner's house) - reported in about 25 houses (Petalburg,
  Rustboro, Lilycove, Mauville, Mossdeep, Oldale, Slateport, Verdanturf, Route 110/111/119/123/124 houses, both Game
  Corners); a plant card keeping its tile's floor colour behind it (R: Scott's house, the Frontier's lounges).
* **Smeared side faces**: the side of an extruded machine or piece dressed with its edge pixels run across it (V:
  the Pokemon Center 2F's link machine; R: the Fan Club's dresser, the bike shop's partition, the Oceanic Museum's
  console, the S.S. Tidal's table).
* **Cracks and slits**: the Lavaridge Pokemon Center's back wall (V: black diagonal cracks through its top band),
  the Marts' back corners (R), Brendan's and May's 1F at the stair alcove (R), a purple line off the Hall of Fame's
  back wall corners (V), Devon's lobby (R).
* **The Elite Four's rooms** (Sidney, Phoebe, Glacia, Drake; V): each side platform's arena-facing wall runs past
  its front as a spike, or stands apart from the top.

### 4. Flat or paper-thin outdoor objects (V unless marked)

The Battle Frontier's stone arches (V, Outside West: a U lying on the plaza) and the Battle Arena's gate (R,
Outside East); Fortree City's Gym sign (V: lying back nearly flat, where other towns' stand); the sea routes' rock
spires (V, Route 124: thin triangular cards at the formations' corners; R: Routes 125, 126, 128, 129, 133); the
white fence right of Route 112's cable car station (R); Route 109's beach umbrella floating, its 2D shadow on the
sand platform's face (R); Slateport's rowboat flat (R); the Safari Zone's Pokeblock feeders flat (R).

### 5. Geometry glitches (R unless marked)

The Safari Zone's stairs drawn as see-through slats (North), see-through ledge faces and ghost steps (Northwest),
its raised walkway under the bike rails see-through (South; V: it shows through); the Sootopolis Gym 1F's ice block
bent over the drop; the Trick House puzzles' partitions bending up into tall slabs at the back wall; the Trick
House end's wall hole a jagged slab; the Battle Dome's back-row audience over black; the Battle Pike room's curtain
gap; Lanette's house's two white pieces past the floor's edge.

### 6. Low

A magenta strip at the top of a few `c25` pictures (the probe's clear colour where the low camera sees past the
map; the game clears to black indoors - to be confirmed in the game build); the Ranking Hall's floor-edge streaks;
thin floor seams in tatami houses' entrances, the S.S. Tidal's black wall tops and Wanda's rug (R).

## What looks right

Outdoor buildings and roofs, the Pokemon Centers and Marts (but for the classes above), Pacifidlog's log walks and
their rails, Oldale's houses, the Frontier facility rooms cut by hand, the Battle Factory and Palace lobbies (MS-164),
the Battle Pike's rooms, the Pyramid's floors (their darkness is the game's), Trainer Hill's boulders.

## Status

| Class | Status |
| --- | --- |
| 1 | **In progress**: 51 layouts cut by hand or read off their cells, 63 places (engine `e0699d80`: Lanette's house, found with class 5's item - its walls and tables lay flat under the lab's furniture; engine `3835fbc9`: the six Contest Halls' stage rooms, the S.S. Tidal's corridor, the Trick House's corridor; engine `0ae0b91a`: Slateport's Fan Club, Lilycove's Trainer Fan Club, Stern's Shipyard 1F and 2F, the Oceanic Museum 2F; engine `3f46e75a`: the Pokemon League 1F, the Battle Dome's lobby, the Battle Palace's corridor; engine `048f9503`: the Department Store 1F-5F, its rooftop's railing, the Museum 1F/2F, the harbors, the Cycling Road gates, the cable car stations, the Battle Tents' lobby, the Contest Lobby, the Day Care and its fence, the Safari Zone entrance; engine `7033b9d5`: the Oceanic Museum 1F, the lifts, the Battle Tower's two corridors, the Battle Tents' corridor; engine `86949cd1`: the Battle Arena's corridor and its island, the Battle Dome's corridor, the Tower's multi partner room) - 26 layouts, 36 places; the cards' flat copies under them in these rooms (found in the pictures) fixed (`fb45cee3`); tried and left (engine `bafb1b9a`'s records): Trick House puzzles 5 and 8 and the Abandoned Ship's second B1F were read off their cells (`auto_rooms.py` proved all three, every model exact, each room 0 pixels different from its drawing) and left out: from the 3D cameras they stood worse than flat - puzzle 5's flat blue squares (impassable, drawn with no face) as plain blue blocks that hid the player, puzzle 8's rounded boulders as cubes with the boulders painted on their faces, the second B1F's wall between its cabins a black column above its back wall, its table's top doubled and its dark corners blocks. They need cutting by hand; the attempt was not committed; the Ever Grande halls cut by hand (`fb319e1c`: the back wall with its doorway standing on the landing, the railings one piece a row on the steps - a model stands on the ground under its door, so a raised landing needed no change to the proof); the Battle Arena's lobby's shoji back wall standing on its stage (`81ee66fb`); the Trick House puzzles 5 and 8's back wall with its exit door standing as the other puzzles' (`813adbe7`; the rest of each room the terrain's, as before); the Battle Pyramid's lobby's upper floor cut by hand (`0ff09c25`: its back wall, pillars, statues on their pedestals, braziers and little pyramids standing on it, the statues cards of their own pixels); the Abandoned Ship's hidden floor rooms read off their cells (`90265897`: found with the second B1F, their back walls, tables, desks and bins flat; read so once the desks against a back wall stood by hand); the Abandoned Ship's second B1F read off its cells (`5a0de0fa`: with the walls between two cabins standing apart, its table its drawn front and its floor's holes as drawn - what had made it stand worse than flat); the Fossil Maniac's tunnel looked at (2026-11-15: it stands as a cave, its rock and boulders standing - nothing lies flat that should stand); still open: Trainer Hill's entrance (pictured; a large room, its three-lane corridor's counters and walls read off their cells stand as slabs, so to cut by hand), its floors' back parts (each floor's first five rows, its back wall and stairs, are the layout's own - the maze under them is laid by the game at run time, `trainer_hill.c`), its lift and roof |
| 3 | **In progress**: fixed - the kit's cupboard's and chest's sides (`13903545`: the frame's column, not a tile of the drawers; the Fan Clubs' dressers and every house they stand in); the Marts' corner cracks, and the same dashed down the Champion's room's and the Battle Factory hall's corners (`fc3a6ccc`: each corner's end closed back to the wall's face), Brendan's and May's stair alcove (the step's slot closed); the bike shop's partition's and walls' sides (`bafb1b9a`: dressed with the back wall's bare columns, not a hung wrench); the potted plants' outline fragments (engine `84b9f2cb`: the house kit's plant its whole silhouette; Sootopolis's Mystery Events house's doorway behind its plants filled down its columns), the lounges' and Scott's house's plant cards' blue squares (`7033b9d5`), Lavaridge's Center's slits (`fb45cee3`: a lent wall to fill from), the Elite Four's cases' spikes, the Hall of Fame's purple hairlines and the Pokemon Centers' link machines' striped sides (`10ab9432`); the ship cabins' tables and bins (`5a0de0fa`: a table no longer a table stacked on a table, 20 rows with its top run down its front; a bin no longer a 20- or 24-row column; the S.S. Tidal's table with a bin under half of it whole, and those on a cabin's last row standing), the Abandoned Ship's floor holes (no longer dark blocks) and the wall between its 1F's lower cabins (two thin walls, no longer a 48-row black column); the S.S. Tidal's desks against the back wall (`90265897`: by hand, the desk its front's rows with a notch for the chair, the chair a card before it, the wall over it to its top row - no longer 48-row slabs with the desk drawn on them); open: the other smeared sides (R: the Oceanic Museum's console, the S.S. Tidal's table - both pictured 2026-11-15 and not seen smeared from cameras a, c25, c15, d); fixed since: Devon's lobby's dotted line (`e02ffd38`: the room's carpet under its alcoves' side walls showing at their decal's edge down the black between the alcoves; their cells keep their own drawing) |
| 4 | **In progress**: fixed - the Gym signs (engine `194aaa4c`: Fortree's and Dewford's stand, and Rustboro's top; Lavaridge's stands with its Gym's front, its letters gapped from low cameras - left, minor); the Frontier's stone arches, the Battle Arena's gate and the sea routes' corner spikes (`c00111d8`); the fences by Route 112's and Mt. Chimney's cable car stations, Route 109's parasol's shadow down the platform's face, Slateport's rowboat and the Safari Zone's feeders (`3326ef41`); open: the Frontier's yellow flags (V, found fixing the arches: their poles' feet are drawn in the low wall's cells) |
| 2 | **In progress**: the tea tables (`13903545`: one piece each for the table with a cup and without, the drawing's whole extent, standing in the ten tatami layouts that have them - the Cove Lily Motel's included - where before most lay flat and Mr. Briney's stood a box with a strip beside it); the S.S. Tidal's berth with a blue blanket (a bed, no longer painted up the wall; the cabins' bins on the carpet in shade, blocks with the bin drawn on them, each its own drawing (`8fbd114a`: the S.S. Tidal's three)); the Department Store's stands and tills, the Contest Lobby's counter and the Battle Tent lobby's PC stand in those rooms' models cut by hand (class 1, engine `048f9503`); the Pokemon League 1F's counters (`3f46e75a`: the room cut by hand); Birch's Poke Balls (`3835fbc9`: standing on the lab table); the Rustboro school's desks, Wanda's bed, the Pretty Petal shop's counter (`fae3bc9a`); the Space Center 1F's stools (`e0699d80`: on the floor behind its tables, not on them); the ship cabins' berths (`7d01c97a`: 19 in the S.S. Tidal's and the Abandoned Ship's rooms, beds before the wall, no longer painted up it); open: the rest of the class's list |
| 5 | **In progress**: the Battle Pike room's curtain gap (`e5831225`: its side wall stood a row in front of the curtained back wall over the shaded floor at its foot - and the same in seventeen more rooms; a side wall now runs on from the wall's foot on its cells' own drawing); Lanette's house's two white pieces past the floor's edge (`e0699d80`: the lab's machines over flat tables at the room's west edge - the room cut by hand, each machine on its table); the Trick House puzzles' partitions rising into tall slabs at the back wall (`78ab5e66`: the wall its two rows, the partitions the maze's height); the Trick House end's wall hole a jagged slab (`6f56b354`: the whole back wall was left out whenever the room's far door closed; the wall no longer answers for its doorways' cells); open: the rest of the class's list |
| 5, 6 | Open |

Nothing here is verified on Windows or a graphics card; every picture is Linux, Mesa's software renderer.
