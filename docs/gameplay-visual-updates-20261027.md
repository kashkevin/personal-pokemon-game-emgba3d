# Gameplay updates and visual fixes (2026-10-27)

The owner's request "Additional Gameplay Updates & Visual Fixes" (eggs hatching in the PC, riding, building
minigames, the real Pokemon for Surf, Fly and Dive, testing) and "Full Wild Pokemon Item Functionality Audit", done
as smaller updates before larger development; nothing here is packaged.

Where a result comes from, always: **L** this Linux machine (real game processes; the 3D view through Mesa's software
OpenGL); **simulated** the multiplayer proofs' internet; **W** a GitHub-hosted Windows runner. Nothing here was tried
on the owner's PCs or between two real PCs unless a line says so.

## 1. Eggs hatch while stored in the PC

**Done** (engine `c3506ff8`; the rule is written in `docs/update30-gameplay.md` and as decision 12 in `PROJECT_SPEC.md`).
Until now an Egg in the PC spent no cycles and never hatched.

How it works:

* The hook is the party's own egg cycle (`src/daycare.c` `TryToHatchEgg`, every 32 of the player's steps). At that moment every
  Egg in all 14 boxes (420 slots) spends the same cycles a party Egg spends: 1 normally, 2 with Flame Body or Magma Armor in
  the party (the same `GetEggCyclesToSubtract`). An Egg with no cycles left hatches at the next cycle, as in the party. So an
  Egg hatches after exactly the steps it would take in the party, never sooner, and all box Eggs progress together.
* It hatches **in its own slot** (`src/platform/mp_breeding.c` `HatchBoxEgg`): species, form, personality (nature, gender,
  ability, shininess), IVs, moves, Poke Ball and the ownership serial are untouched. It gets what the party's hatch gives
  (`egg_hatch.c` `AddHatchedMonToParty`): the species name, the game's language, friendship 120, "hatched at" the player's
  map, full PP, the Pokedex entry, the hatched-eggs count. One difference: the party's hatch writes the player's OT ID; the
  box hatch never changes the OT ID (the world's host refuses a save whose Pokemon changed personality or OT ID,
  `ownership_storage.py`), and every Egg a player can have was made with their own OT ID already, so the result is the same.
* A banner says it once the field is calm: "PC EGG HATCHED! / Pichu hatched in your PC."; several on one step: "3 PC EGGS
  HATCHED! / Pichu, Pikachu +1".
* Only the player's own steps count: the hook runs in the player's own game when that player steps; another player's
  movement is drawn from the network and never runs it, and the host runs no game. Nothing accumulates while the game is
  closed (the game has no offline progress; none was added).
* The progress is the Egg's own cycle counter (its friendship byte, as in the original), so it is saved with the box: quit,
  reload and the world's checkpoints keep it. Bad Eggs and non-Eggs are never touched.

Tests (**L**):

| Test | Result |
|---|---|
| `--selftest-breeding` section 5 (rewritten): steps to hatch in a box vs. in the party, for 0, 1, 7 and 20 cycles, with and without Flame Body | **Equal in all 8 cases** (32, 64, 256, 672 steps without; 32, 64, 160, 352 with) |
| the same: a shiny Togepi Egg with an Egg move in the last slot of the last box hatches | species, personality, IVs, moves, ball, shininess kept; nickname = species name; not an Egg |
| the same: Eggs in boxes 1, 6 and 14 hatch on one step; a non-Egg Zigzagoon and a Bad Egg in the boxes | three hatched; the other two unchanged |
| full `--selftest-breeding` | **77 checks, 0 failed** (2D game, engine `c3506ff8`) |
| `breed_check.py` steps 6-10, real game processes of the Classic 2D test build: a Day Care Egg moved to box 1 slot 1, walked | cycles 3 → 0 by walking; **saved and loaded with the same cycles**; walked again: **hatched in box 1 slot 1** (Pichu, same IVs, nature, ball, moves), banner "PC EGG HATCHED!\|Pichu hatched in your PC."; saved and loaded: box and Pokedex counts each +1; three Eggs in boxes 1, 8 and 14: all hatched in place, banner "3 PC EGGS HATCHED!\|Pichu, Pikachu +1". **All 10 steps passed** (steps 1-5, the older Day Care checks, also passed) |
| GBA ROM, `check_gba_lines.py`, 2D and 3D builds | ROM unchanged (`f214735b...`); 0 moved lines; both build |

Not tested: a PC hatch inside a connected world (the hook and the save path are the same as offline, and the host's rule it
must respect, unchanged personality and OT ID, is kept by construction); Windows; a player's PC.

## 2. Pokemon riding: animations and positioning

**Done** (engine `9d773a92`, PC only; the GBA ROM unchanged). Looked for in pictures of the running game (2D and 3D, every
facing, walking, hops, a ledge, a battle, a door) and in a session of two games through a real world server. What was
wrong and what changed:

| Seen | Cause | Now |
|---|---|---|
| The rider floated over small backs and sank into tall ones | one lift for every mount, from its picture's size: 7 px for all 67 rideable species (all have 32x32 pictures) | the seat is read from each mount's own picture: the top of its back in the rear half of the side view (the lower quartile of that edge, at most 68 % of the drawn height up, the rider 3 px into the back), per facing and per trainer picture: **6 to 18 px** (Tyranitar and Pyroar 6, Venusaur and Arcanine 13, Dodrio and Aerodactyl 17, Noivern 18) |
| Seen from the side the rider sat over the middle (over the head of some) | no sideways place | over the back, 1-5 px toward the tail, mirrored facing east |
| Facing the camera the rider was drawn over the mount's head | the rider always in front | the mount in front (the rider's head and shoulders show behind its head); facing away or sideways the rider in front |
| The rider popped onto the seat and off it | the lift applied at once | it rises over the hop on and comes down over the hop off (12 frames each) |
| Two shadows; a dust puff at the mount's feet as the rider landed on its back | the rider's own shadow and landing were the ground's | no shadow of the rider's own; no dust on the hop on (the hop off keeps it: that one lands on the ground) |
| 3D: the rider sank into the mount as the camera tilted, and the two could drift apart in a step | two separately placed cards; the lift was a height in the world | the rider's card is drawn on the mount's (same place and step, the seat along the card's lean), sorted just in front of it (just behind it facing the camera); mounts get the silhouette shown through walls, as the player and the follower do |
| Riding into a building: the rider went through the door and the mount stood outside until the screen faded; inside, the seated pose for a moment | a script's steps (the door's step in) were not taken by the mount; the seated look was put back on a map where riding is not allowed | the mount takes the step with its rider and hides in the same frame; inside, the walking look from the first frame (riding ends indoors, as before) |
| After a battle (the owner's report of 2026-10-23) the trainer walked on the ground, then popped onto the mount | the mount and the look came back once the field was calm | back on the mount from the first frame of the fade-in |
| **Another player** hopping on: their follower vanished and the mount appeared under them after their hop | the mount state was published after the hop | published as the hop starts; their Pokemon walks under them, then the seat rises; the walking look until then |
| Another player seated and standing still was **drawn as nothing** until they moved (older than this request) | their picture changed without a new animation frame | the new picture shows at once (also for their Pokemon) |
| Another player hopping off: the mount vanished for half a second, the rider dropped at once | their own follower is hidden during the hop, so the copy was removed | the Pokemon stays drawn, steps back as the local mount does, the seat comes down, the rider in front |
| A rider coming into view mid-step: the mount walked a tile past them and snapped back | the mount's step started from the rider's new tile | it starts from where the rider's step starts |

Unchanged: where riding is allowed, the riding pace, that riding grants no Surf or Fly, the multiplayer record (the
same two values), the camera (it follows the player as before; no fault found), the scale (the mounts are the
follower pictures, the rider the trainer's seated picture, as before). The rider's seated pose is the original surfing
pose, which has no walking frames: the rider sits still while the mount walks (not changed).

Tests (**L**). The door and the two-game 2D check used the final code (engine `9d773a92`'s test build); the others used
test builds from earlier in this work, before the door change (the frame-by-frame hop, the battle, the ledge, the 3D
captures and the 3D two-game run) or before the dust change too (the six-mount 2D captures); each change was tested on
its own after it was made.

| Test | Result |
|---|---|
| `--selftest-ride` (new; `make check-ride`): the 67 roster species' seats for both trainers, and a contact sheet of the old and the new seat in all four facings | **3 checks, 0 failed**; seats 6-18 px; the sheet looked over for all 67 species |
| Riding in the 2D game (Classic 2D test build), six mounts of different shapes (Arcanine, Rapidash, Dragonite, Tropius, Noivern, Rhyhorn): hop on, the four facings, walking, hop off; the hops frame by frame | as in the table above; no dust on the hop on |
| The same in the 3D game (Mesa software OpenGL) | the rider on the mount's card in every pose, in step while walking, hop off |
| Riding south over Route 101's ledge (2D) | rider and mount jump together, one shadow, dust only from the mount's landing |
| A visible wild Pokemon bumps into the rider; Run (2D) | back on the field on the mount from the first frame of the fade-in |
| Riding into a house in Oldale Town (2D and 3D) | the mount goes through the door with the rider, nothing left outside; inside in the walking look |
| Two games, a real world server, real companions (`scripts/multiplayer/native_ride_check.py`, 2D test build): B mounts north of A, rides two tiles west and back, dismounts; A takes 128 pictures | **passed** (one machine, no simulated internet): B's mount state reached A's game in 21 and 20 ms; the pictures show B's Pokemon walking under B, the seat rising, B seated standing and riding, the hop off with B in front |
| The same two-game run with the 3D test build (once, the same harness by hand) | the same, in 3D |
| GBA ROM, `check_gba_lines.py`, `check-native`, `check-diorama`, 2D and 3D builds | ROM **unchanged** (`f214735b...`); 0 moved lines; 1512 + 15 + 176 checks, 0 failures; compositor goldens passed; both build |

Not tested: bridges and other changes of level than a ledge; caves (riding is allowed underground where bikes are);
scripted moves other than a door's step (the same code takes them); a rider and a mount seen by three or four players;
Windows; a player's PC; two real PCs.

## 3. Building minigames: every one playable

**Done for every activity a PC can run** (engine `449914f7`, `ad70022f`, `8d44e91d`, `9d978d9b` and `11a70601`, PC
only; the GBA ROM unchanged). **Three wireless minigames need an owner decision** (below).

Every activity was played in the real game: the Classic 2D test build, the player put in front of the attendant, keys
pressed on exact frames, and pictures taken and looked at. The save was enrolled with a test world, as a connected
player's is, so a world's save rules applied. Hoenn only: the other regions are not in the game yet (its Kanto maps are empty, KNOWN_ISSUES M14). The
Game Corner's casino is left out, as asked. Nothing was replaced by a generic minigame; each activity is the original.

### What was wrong, and what changed

| # | Found | Cause | Fix |
|---|---|---|---|
| 1 | **No Battle Frontier or Battle Tent challenge could start with a world's save.** The attendant's save before the challenge failed ("Save error. Please exchange the backup memory."), so the challenge was called off. A save that had finished a challenge before joining a world could not save there at all. Offline saves were not affected. | The world's save guard keeps a save from writing a party of 3 chosen or rented Pokemon over the player's 6. It refused every save while a challenge's status or its paused flag was set. The lobby sets the status just before its own save, and every challenge leaves the paused flag set when it ends. Inside the Battle Pyramid (its floors run with the status cleared) the guard allowed a save with only the 3 chosen Pokemon. | During a challenge, a save is allowed exactly when the party in memory is the whole party the save keeps. Every save a challenge makes loads that party first: the lobby's, a rest's, and the Pike's and the Pyramid's pauses. Saves are refused while the chosen Pokemon or rentals are in play, and in battle. Inside the Pyramid counts as a challenge. The leftover paused flag no longer counts. Offline saves are unchanged. (`449914f7`) |
| 2 | **Battles in the Frontier, the Tents and the Pyramid closed the game**: the opponent's Pokemon announced "Time to Dynamax!" and the game crashed. Seen in the Battle Tower, the Battle Dome, the Battle Pyramid (a wild Wooper) and the Fallarbor Tent. | Dynamax and Terastallization are not part of this Gen 6 game (`PROJECT_SPEC.md`), and the player can never use them. A computer trainer's Pokemon made from trainer data are kept from them. Pokemon made any other way were not: the Frontier's and the Tents' trainers, Trainer Hill's and secret bases', and the Pyramid's wild Pokemon (which fight with the computer's battle logic). Those could Dynamax, and Terastallize after that. The Dynamax battle script reads memory address 0, which the GBA tolerates and the PC game does not. | Mega Evolution is the only battle gimmick the PC game allows. (`8d44e91d`) |
| 3 | **Contests closed the game during the appeals.** | 31 of the move-animation backgrounds are smaller than 2 KB. The contest version of the animation code unpacked them into a buffer of exactly their size, then wrote and copied 2 KB from it, past the end of the buffer. | The buffer is at least 2 KB. (`ad70022f`) |
| 4 | **Every contest closed the game as its results screen ended.** | The stars' flashing on the results screen keeps running until the field resets the tasks. In the screen's last frame it ran after the screen had freed its memory, and wrote through a pointer that was no longer valid. The winner's bouncing icon could also write into the freed background. | The results screen's leftover tasks (the flashing, the bouncing icon, the confetti) end with the screen. (`9d978d9b`) |
| 5 | **Every Berry Blender session closed the game at its end** ("Would you like to blend another BERRY?"). | The same kind of fault: in its last frame the blender screen freed its memory, then still ran its sprites (the players' arrows) and, at the next screen refresh, its own display interrupt. Both read the freed memory. | Once the memory is freed, the blender's screen stops for the rest of that frame, and its display interrupt does nothing until the next screen sets its own; the screen is black at that point. (`11a70601`) |

Fixes 2 to 5 stop crashes of the PC game only: the GBA build reads or writes memory it does not own there without
stopping, and the GBA ROM is unchanged. Fix 1 concerns only saves enrolled with a world.

### Every activity

**Seen** is what the pictures show (all on **L**: real game processes of the Classic 2D test build, the save enrolled
with a test world). *(before)* marks a run made before fix 2, 4 or 5 where that fix mattered to it.

| Activity | Where | What it is | Works? | Seen |
|---|---|---|---|---|
| **Battle Tower** | Battle Frontier | single, double and multi battles in a row; 3 or 4 chosen Pokemon | **Yes** (fixes 1, 2) | lobby → 3 chosen → the save before the challenge ("DARREN saved the game.") → elevator → corridor → battle room → a battle of many turns (Bug Maniac Clayton's Bellsprout: Stun Spore, Acid); *(before)* the same run closed when the opponent Dynamaxed; with the old save guard: "Save error. Please exchange the backup memory." |
| **Battle Dome** | Battle Frontier | tournament; 3 registered, 2 per match | **Yes** (fixes 1, 2) | lobby save → the opponent's card and the tourney menu (OPPONENT / TOURNEY TREE / READY TO START / REST / RETIRE) → "choose the two Pokemon" → the stadium ("Round 1 match! Let the battle begin!") → a battle of several turns (Ninja Boy Nestor's Zubat: Confuse Ray, Poison Fang). **REST**: "I am saving your data", the game restarts, Continue → "We've been waiting for you!" (the challenge resumes). *(before)* closed in the first match |
| **Battle Palace** | Battle Frontier | the Pokemon choose their own moves by nature | **Yes** (fixes 1, 2) | lobby save → corridor → battle room → a long battle in which Gardevoir picks its own moves (Future Sight, Hypnosis) against Pokefan Quinn's Exeggcute |
| **Battle Arena** | Battle Frontier | 3 turns, then the referee judges | **Yes** (fixes 1, 2) | lobby save → corridor → the referee ("Set KO Tourney! Begin!") → 3 turns → "We will now go to judging" → Mind / Skill / Body → "Gardevoir tied the opponent Eevee in a REFEREE's decision!" → the next Pokemon sent out |
| **Battle Factory** | Battle Frontier | battles with rented Pokemon | **Yes** (fixes 1, 2) | lobby save → the hint about the opponent → the rental screen: 3 rented (Mawile, Beautifly, Chinchou), "Are these three POKeMON OK?" → battle room → a battle with the rentals |
| **Battle Pike** | Battle Frontier | three doors, a room's event behind each | **Yes** (fixes 1, 2) | 3 chosen → lobby save → corridor → the three-path room → a room: a trainer's Kirlia uses Toxic on the party ("I do apologize for what happened") |
| **Battle Pyramid** | Battle Frontier | dark floors with trainers, items and wild Pokemon | **Yes** (fixes 1, 2) | 3 chosen → lobby save → "PYRAMID FLOOR 1" in the dark → an item ("DARREN found one Revive!") → a wild Plusle's battle of several turns (Encore, Thunder Wave); *(before)* a wild Wooper Dynamaxed and the game closed |
| **Slateport Tent** | Slateport City | Battle Factory rules (rentals) | **Yes** (fixes 1, 2) | lobby save → rental screen: 3 rented, confirmed → a battle; the opponent's first Pokemon knocked out, the next sent out |
| **Verdanturf Tent** | Verdanturf Town | Battle Palace rules | **Yes** (fix 1) | lobby save → the first battle, won |
| **Fallarbor Tent** | Fallarbor Town | Battle Arena rules | **Yes** (fixes 1, 2) | 3 chosen → lobby save → "REFEREE: Gardevoir VS Lombre! Commence battling!" → a battle of many turns (Rain Dance, Flash); *(before)* closed at "Time to Dynamax!" |
| **Contests** | Lilycove Contest Hall | 5 categories, Normal to Master rank | **Yes** (fixes 3, 4) | a whole Normal Cool contest: the reception, the appeals, "MC: That's it for judging!", the results screen ("Announcing the results!", "Round 2 results!", "MADISON's TATAY won!", "MADISON and TATAY, congratulations!") → back in the Contest Lobby; *(before fix 3)* closed in the appeals; *(before fix 4)* closed as the results ended |
| **Berry Blender** | Lilycove Contest Lobby | blending with 1-3 partners | **Yes** (fix 5) | a berry chosen (Pokeblock Case and berries given) → the blender with two partners (DUDE, LASSIE): countdown, arrows, hits and misses, the speed → the ranking → "BLACK POKeBLOCK was made!" → "Would you like to blend another BERRY?" yes → a second blend to its Pokeblock → yes again → the berry choice; a session answered "no" → back in the Contest Lobby; *(before)* closed at the play-again prompt |
| **Trainer Hill** | off Route 111 | timed climb of 4 floors of trainers (open after the Elite Four, as in the original) | **Yes** (start and floor 1) | "Welcome! This is the TRAINER HILL" → the save before the climb → "On your marks... Go!" → the timer → floor 1 (spinner tiles, two trainers seen); no floor battle reached in the runs (its trainers fight through the same battle code as the Frontier's, fix 2) |
| **Safari Zone** | Route 121 | Safari Balls instead of battling with your Pokemon | **Yes** | "That will be P500" → 30 Safari Balls → the zone with its counter → a wild Swinub's Safari battle → a ball thrown → "Gotcha! Swinub was caught!" → the Pokedex entry, the nickname → back in the zone |
| **Trick House** | Route 110 | find the Trick Master, then 8 puzzles (badges unlock them) | **Yes** (start and puzzle 1) | "You're being watched" → the desk searched → "How did you know I concealed myself beneath this desk? You're sharp!" → the Trick Master's challenge → "There is a big hole behind the scroll! Want to go in?" → puzzle 1's room; its trees need Cut, which the test save does not have (puzzles not solved) |
| **Seashore House** | Route 109 | beat its 3 trainers for 6 Soda Pops | **Yes** | the owner's challenge; Tuber Simon spots the player ("I'm going to show you how great my POKeMON are, but don't cry!") → his battle (Azurill) |
| **Glass Workshop** | Route 113 | trade gathered ash for flutes and glass furniture | **Yes** | "Have you collected ashes, huff-puff?" (1,000 ash given) → "Which one would you like?" (the five flutes) → "Obtained the Blue Flute!", four times |
| **Lottery Corner** | Lilycove Dept. Store 1F | a daily ID-number draw | **Yes** | "Would you like to draw a POKeMON LOTO TICKET?" → the check → "I'm sorry. None of..." → "Please come back tomorrow" |
| **Lilycove Lady** | Lilycove Pokemon Center | the Quiz, Favor or Contest Lady (one per save) | **Yes** (Contest Lady seen) | her dialogue; the Quiz and Favor Ladies not seen (another save's trainer ID) |
| **Mauville Old Man** | Mauville Pokemon Center | the Bard, Hipster, Trader, Storyteller or Giddy (one per save) | **Yes** (Storyteller seen) | "I'm the STORYTELLER. I'll tell you tales of legendary..."; the other four not seen |
| Winstrate family's house | Route 111 | the family at home | **Yes** (dialogue) | "You're the first TRAINER I've seen who deploys POKeMON so masterfully..."; their four battles happen outside on Route 111, not in the house (not run) |
| Pokemon Jump, Dodrio Berry Picking | Mossdeep City's minigame building | 2-5 (Dodrio 3-5) players linked by the GBA Wireless Adapter | **No: owner decision** | "Hi, welcome! Are you here to play games using Wireless Communication?" → "The Wireless Adapter isn't connected. Come back when it's hooked up!" (what a GBA without the adapter says) |
| Berry Crush | the Pokemon Centers' wireless club | 2-5 players, wireless only | **No: owner decision** | not offered without the adapter (the attendant goes straight to the cable club) |
| Union Room, Record Corner, link contests, link Berry Blender, cable trades and battles | Pokemon Centers 2F, Contest Lobby | GBA link cable or wireless | Not available (unchanged) | the multiplayer has its own trades and battles between players |
| Game Corner | Mauville City | slots, roulette | Excluded by the request | - |

### Owner decision: the wireless minigames

Pokemon Jump, Dodrio Berry Picking and Berry Crush exist only as games between GBAs linked by the Wireless Adapter.
The original has no single-player version and no computer partners. Making them playable means one of:

1. **Between the world's players**: a new network feature. The minigames exchange their state every frame through
   the link layer, which the PC game's multiplayer does not carry yet. The largest of the three.
2. **With computer partners**: new behaviour the originals never had (the Berry Blender is the only original minigame
   with computer players).
3. **Leave them as they are**: the attendants say what a GBA without the adapter says.

Nothing is changed until the owner chooses.

### Parts of the request not done in this round

* **Modernize the minigame interfaces to the current UI: not done.** The contest screens, the Berry Blender, the
  Pokeblock case and feeding, the Frontier's screens (the Frontier Pass, the Dome's tourney tree, the Factory's rental
  and swap, the Pyramid's bag, the Pike and Arena screens, the Ranking Hall, the Exchange Service Corner), the Battle
  Arena's judgment and Trainer Hill's records are still drawn as the GBA's (KNOWN_ISSUES MS-105). They belong to the
  larger task of replacing every remaining GBA screen, which comes after these smaller updates, as the owner asked.
  The Safari Zone's battle is already in the current UI.
* **All six regions**: only Hoenn is in the game (`PROJECT_SPEC.md`: Hoenn first, the other regions one at a time
  later), so only Hoenn's buildings exist to inspect.
* **Rewards**: seen for the Berry Blender (a Pokeblock), the Glass Workshop (a Blue Flute) and the Safari Zone (the
  caught Pokemon). Not reached in the runs: contest ribbons (the test contest was lost), Battle Points and symbols, the
  Trick House's prizes, the Seashore House's Soda Pops, a lottery prize (the draw did not match).
* **Finish, retry, exit**: a contest finished and returned to the lobby; the blender finished, blended again and was
  left; the Dome's rest saved and resumed. Not seen: retiring from or losing a Frontier challenge, leaving the Safari
  Zone when its steps run out, finishing a Trick House puzzle.
* **Multiplayer**: the original's multi-player versions (link contests, the link Berry Blender, the Union Room, the
  wireless minigames, the Battle Tower's multi battles with a linked friend) are not available on the PC game (above).
  The Tower's multi battles with a computer partner were not run.

### Tests

All on **L**. *(before)* runs used the test build of engine `ad70022f`; the reruns used the test build with fixes 2
to 5.

| Test | Result |
|---|---|
| `--selftest-frontier-saves` (new; `make check-frontier-saves`): the rule through each lobby's sequence (the opening save, the chosen three, a rest, rentals, the end, the leftover flag, the Pyramid's floors and rest), offline and enrolled | **21 checks, 0 failed** |
| Battle Tower, enrolled save, singles, Level 50: the challenge's start; the same with the old guard (a temporary build) | starts (save, elevator, battle room); with the old guard **"Save error"** and the challenge called off |
| The other six facilities and the three Tents, each from its attendant | all start *(before)*; Tower, Dome, Pyramid and Fallarbor Tent closed at a Dynamax |
| The same after fix 2, battles played: Tower, Dome, Palace, Arena, Factory (rentals), Pyramid, Fallarbor and Slateport Tents | battles of many turns, no Dynamax, no crash |
| Battle Dome REST in the middle of a challenge: save, restart, Continue | saved and resumed ("We've been waiting for you!") |
| Contest: the appeals for 18,000 frames (after fix 3); a whole contest (after fix 4) | no crash; the reception to the lobby after the results |
| Berry Blender: two sessions with "blend another" (after fix 5); a session answered "no" | no crash: two Pokeblocks made and the next berry chosen; after "no", back in the lobby |
| Safari Zone, Trainer Hill, Trick House, Seashore House, Glass Workshop, Lottery Corner, Lilycove Lady, Mauville Old Man, the Winstrates' house, Mossdeep's minigame building | as in the table above |
| A search of the engine for other screens that use their memory after freeing it in the same function | none in the activities' screens beyond fixes 4 and 5 (a search cannot see every case; the runs above are the test) |
| GBA ROM, `check_gba_lines.py`, `check-native`, `check-diorama`, 2D and 3D builds | ROM **unchanged** (`f214735b...`); 0 moved lines; every suite 0 failures; compositor goldens passed, rules valid; both build |

Not tested: a whole Frontier challenge to its Frontier Brain, symbols or Battle Points (only the first battles or rooms;
the saves of the rests and the end are covered by the self-test and the Dome's rest); the Factory's swap screen, the
Dome's tourney tree, the Pyramid's bag and the Pike's other rooms; doubles and multi battles in the Frontier; a Trainer
Hill floor's battle and its records; the Trick House's puzzles; Super, Hyper and Master rank contests and the Lilycove
Museum painting; feeding Pokeblocks; all five Mauville Old Men and three Lilycove Ladies; any activity in the 3D game;
inside a real connected world (a test world's enrollment, no host); Windows; a player's PC.

## 4. The real Pokemon for Surf, Fly and Dive

(in progress)

## 5. Wild Pokemon item audit

**Done** (engine `65940085`, PC only; the host's part in this app commit). Every item and ability that touches wild
Pokemon was traced through the code that actually makes the encounter (not the bag text), and each effect was measured
through the game's own functions (`--selftest-wild-items`, **76 checks, 0 failed**,
20 million rolls per shiny case, 1 million per ability case; `make -f Makefile_pc check-wild-items`). The game's wild
Pokemon come from four places, which matters for what an item can do:

* **Visible Pokemon of the player's own spawner** (`src/wild_encounter_ow.c`): all land and water Pokemon offline; in a
  connected world only on the water. Species from the randomized Gen 1-6 pool (`src/mp_wild_random.c`), level from the
  map's table; walking into one starts the battle, which makes its Pokemon again (`StartWildBattleWithOWE`).
* **A world's shared Pokemon** (host `shared_spawns.py`, engine `src/multiplayer_spawns.c`): land in a connected world.
  The host rolls species, level, personality (nature, gender, ability) and shininess once, the same for every player;
  a battle starts only when the player talks to one (it never starts by walking into it).
* **Random encounters** still happen only for Rock Smash, fishing, Sweet Scent and Honey (`WE_VANILLA_RANDOM` is off).
* **Static, gift and Egg Pokemon** have their own rules (Local Soft Reset hunts for the authored statics).

### What was wrong, and what changed

| # | Problem found | Cause | Fix |
|---|---|---|---|
| 1 | **Synchronize never worked on visible wild Pokemon** (offline, and on the water in a world); the Safari Zone's Pokeblock natures neither | the spawn was made with the right nature, then the battle made its Pokemon again with `NATURE_RANDOM` | the battle's Pokemon gets its nature as every wild encounter does (`PickWildMonNature`: Pokeblock, then Synchronize); engine, PC only |
| 2 | **The Shiny Charm gave Local Soft Reset hunts 1 in 1365.7**, not the approved 1 in 2500 | Update 30 retuned only the wild Charm (an extra roll made 41848/65536 of the time) and left these hunts at Update 29's two extra rolls; no rule allowed it (`PROJECT_SPEC.md`: one Charm value, 1/2500) | the same partial roll; `PROJECT_SPEC.md` updated; engine, PC only |
| 3 | **Magnet Pull and Static did nothing** (Steel 3.1 %, Electric 5.2 % of Route 101's spawns with or without them) | the map's table chose a Steel or Electric slot, but the randomizer then replaced its species | half the rolls are made among the families of that type that can appear there (Gen 6: half the encounters of that type when the area has any); land and water, not fishing or Rock Smash, as in the original; engine, PC only |
| 4 | **The encounter-rate items and abilities did nothing to visible Pokemon**: White and Black Flute, Cleanse Tag, Pure Incense, Stench, White Smoke, Quick Feet, Sand Veil, Snow Cloak, Illuminate, Arena Trap, No Guard (only Rock Smash used them) | visible Pokemon replace random encounters; only the lure had been adapted (by pokeemerald-expansion) | the player's own spawner waits at the same rate the original applies to random encounters (x2 halves every wait, x0.5 doubles it; the original multipliers, `MPWild_EncounterRateFactor`); the bike's x0.8 and the lure are not part of it; engine, PC only |
| 5 | **A Pokemon the Shiny Charm makes shiny on a world's shared spawns could despawn** (expire, wander off, be trimmed after an outbreak), against the owner's rule of 2026-10-24 that a shiny leaves only when caught or knocked out | the host keeps the shinies it rolled, but it cannot see bags, so it did not know | the host computes the Charm's hash too (the engine's, bit for bit: 48 vectors compared) and keeps every Pokemon that is shiny for a Charm owner like a shiny one (`Slot.kept`); app |
| 6 | Docs gave the old Charm price (100,000 coins; 15,000 since 2026-10-25) and said the Oval Charm and Pure Incense could not be had (the Game Corner's RARE GOODS sell them since 2026-10-24) | written before those changes | `PROJECT_SPEC.md`, `FEATURE_STATUS.md`, `update29/30` docs, `update-32` doc, the clerk script's comment corrected |

No balance value was changed: every multiplier above is the original's, and the Charm's 1/2500 is the approved value.

### Seen in the real game

`wild_items_check.py` (engine `tools/battle_env/`), real game processes of the Classic 2D test build on Route 101's grass,
offline (so every Pokemon there is the player's own spawner's), each run its own random seed (started a second apart):

| Case | Result |
|---|---|
| a Synchronize lead (Ralts, Timid) walks into the first visible Pokemon, 30 battles | **20 of 30** had the lead's nature (52 % expected; before the fix the battle's nature was random: 1 in 25) |
| the same lead with Trace, 30 battles | **0 of 30** (4 % expected) |
| the spawner over 74 s of standing still (a Pokemon that walks into the player starts no battle, a test switch), Pokemon made per run, 3 runs each | Black Flute (x0.5) 7, 8, 7; Cleanse Tag (x2/3) 10, 11, 9; nothing 16, 12, 12; White Flute (x1.5) 21, 18, 19; Illuminate (x2) 27, 26, 28: **the counts rise with the rate** |

### Item by item

Measured = `--selftest-wild-items` on this Linux machine through the game's own functions (expected value in brackets;
every check within 4.5 sigma). Where a source is "Rare Goods" it is the Game Corner prize clerk's coin shop (PC game).

| Item / ability | Intended effect (as implemented) | Worked before? | Found | Values and measured | Status |
|---|---|---|---|---|---|
| **Shiny Charm** (Game Corner, 15,000 coins; one per player) | the holder's own shiny odds: wild 1/2500, Safari 1/1024.4, Local Soft Reset hunts 1/2500, Eggs the player's Day Care makes 1/1365.7; never World Events | wild, Safari, Eggs, shared spawns: yes (`--selftest-shiny` 12/12, `--selftest-breeding`); LSR hunts: no | problems 2 and 5 | LSR + Charm: 8,186 shiny in 20M = 1 in 2443 (1 in 2500); LSR alone 1 in 4159 (4096); shared + Charm 1 in 2500.0 (`--selftest-shiny`) | **Fixed** |
| Shiny status kept | a shiny is stored in the Pokemon (never rolled again): capture, PC, trade, save | yes | - | a shiny put in the PC and read back is shiny, same personality; trades carry the Pokemon's data unchanged (trade proofs compare the boxes) | Works |
| **Lure / Super Lure / Max Lure** (Rare Goods, 75 / 150 / 225 coins) | 100 / 200 / 250 of the player's steps: the player's own visible Pokemon appear without the usual wait (until four are out); their level is the species' highest in that area plus one; one extra shiny roll for Pokemon made for the player; Rock Smash encounters twice as often | yes | the extra shiny roll also reaches gift and static Pokemon made while a lure lasts (inherited from pokeemerald-expansion; never documented); the original's 20 % common/rare slot swap only changes the level here (species are randomized); in a world, on land the Pokemon are the host's, so a lure's spawn effect does not apply there though its steps count | wild + lure 1 in 2026 (2048.3); lure + Charm 1 in 1542 (1552.7); LSR + lure 1 in 4024 (4096: no lure roll); levels max + 1 in 200,000 of 200,000 rolls; ends on its 100th step, once | Works as designed; the three notes are **owner decisions** (below) |
| Lure use | one item used per activation; a second Lure while one lasts is refused ("effects lingered"), not used up; wears off with a message and the offer to use another; counts only the player's own steps, not in the Battle Pike/Pyramid or Union Room; kept in the save | yes | a Repel used during a Lure ends the Lure at once (and the reverse), without a warning: they share one counter, so they never stack | one counter: with a Lure active no Repel, and the reverse (checked) | Works; the silent replacement is noted below |
| **Repel / Super Repel / Max Repel** (marts, item balls, Pickup) | 100 / 200 / 250 steps: wild Pokemon below the level of the first party member that is not an Egg (fainted or not, Gen 6) are kept away: the player's own visible ones are not made and those out go when it is used; Rock Smash and Sweet Scent likewise | yes | a world's shared Pokemon are not hidden (they never start a battle unless talked to) | level 19 kept away and 20, 21 met with a level-20 lead; a fainted lead counts; an Egg at the head is passed over; no shiny roll | Works |
| **Oval Charm** (Rare Goods, 15,000 coins) | Day Care Egg chance per 64-step check 20 / 50 / 70 % → 40 / 80 / 88 % | yes | - | 39.86 / 79.97 / 87.95 % (40 / 80 / 88) in 100,000 checks each; without it 19.79 / 50.08 / 70.08 % | Works |
| **Catching Charm** (Rare Goods, 15,000 coins) | doubles the chance of a critical capture | yes | - | ball odds 120, 40 Pokemon caught: 3.90 % → 7.79 % (3.91 → 7.81) | Works |
| **White Flute / Black Flute** (Route 113 Glass Workshop, 1,000 ash each) | encounter rate x1.5 / x0.5 until the map changes; not used up | Rock Smash only | problem 4 | the player's spawner's waits: 120 frames → 80 / 240 | **Fixed** |
| **Cleanse Tag** (Mt. Pyre 1F gift) / **Pure Incense** (Rare Goods, 750 coins) | held by the lead: encounter rate x2/3 | Rock Smash only | problem 4 | 120 → 180 frames | **Fixed** |
| Stench, White Smoke, Quick Feet; Sand Veil (sandstorm), Snow Cloak (snow) | lead: encounter rate x0.5 (Stench x0.75 in the Battle Pyramid) | Rock Smash only | problem 4 | 120 → 240 frames; Sand Veil in clear weather unchanged; an Egg at the head changes nothing | **Fixed** |
| Illuminate, Arena Trap, No Guard | lead: encounter rate x2 | Rock Smash only | problem 4 | 120 → 60 frames; combinations multiply (Black Flute + Cleanse Tag + Stench: x1/6, 720 frames) | **Fixed** |
| **Synchronize** | lead: the wild Pokemon has its nature half the time (Gen 6) | Rock Smash, fishing, Sweet Scent: yes; visible Pokemon: no | problem 1 | 51.92 % of natures are the lead's (52 %); Trace instead: 3.97 % (4 %); an Egg at the head: 4.04 % | **Fixed** (visible Pokemon); a world's shared Pokemon keep the host's nature (the same Pokemon for every player, by design) |
| Safari Zone Pokeblock | a nearby feeder's Pokeblock picks the nature 80 % of the time | not for visible Pokemon | problem 1 (same code) | not measured separately (the same function as Synchronize) | **Fixed** |
| **Cute Charm** | lead: the opposite gender two times in three | yes (the spawn keeps the gender it was made with) | - | a female lead: 83.35 % male (83.33 %); without: 50.45 % | Works |
| **Magnet Pull / Static** | lead: half the encounters on land and water are Steel / Electric when the area has any | no | problem 3 | Route 101: Steel 3.07 % → 51.61 % (51.54 %), Electric 5.17 % → 52.63 % (52.58 %) | **Fixed** |
| **Keen Eye / Intimidate** | lead: Pokemon 5 or more levels lower are kept away half the time | yes (the spawner asks) | - | level 25 against a level-30 lead: 50.04 % / 49.98 % kept away (50 %); level 26 never | Works |
| **Hustle / Pressure / Vital Spirit** | lead: the slot's highest level half the time | yes | - | 50.02 % (50 %); without 20.02 % (20 %, a 10-14 slot) | Works |
| **Compound Eyes / Super Luck** | lead: wild held items 50 / 5 % → 60 / 20 % | yes (every wild battle, visible and shared too) | - | 49.97 / 5.02 % → 59.96 / 20.01 % | Works |
| Sticky Hold / Suction Cups | lead: fishing bites twice as often (Gen 4+) | yes | - | code read (`fishing.c`), not measured | Works (unmeasured) |
| Flame Body / Magma Armor / Steam Engine | Egg cycles halved, once | yes | - | `--selftest-breeding` (party and, since today, PC Eggs) | Works |
| Honey / Sweet Scent | a wild encounter at once | yes | in a world, on land, it makes a personal encounter (not one of the host's Pokemon); the player's own items apply to it | not changed | Works as the original |
| Poke Doll / Fluffy Tail / Smoke Ball | a sure escape from a wild battle | yes (battle code unchanged) | - | not measured | Works (unmeasured) |
| Old / Good / Super Rod | fishing (species randomized) | yes | - | - | Works |
| Poke Radar | - | **not in the game**: no source, and its use is pokeemerald-expansion's "Todo" | - | - | Not available |

### Each player's items are that player's own

The bag, the Repel/Lure counter and the flutes' flags are in each player's own save and act only in that player's own game;
nothing about them is sent to the host or applied by it. A world's shared Pokemon are rolled once by the host (one roll for
everybody, never repeated on a reconnect); the Shiny Charm's bonus on one is computed only in the Charm owner's game, from
the Pokemon's own numbers, so claiming, releasing and claiming it again or reconnecting gives the same answer (no reroll),
and a player without the Charm sees the host's roll. An item is used up in the player's bag once, by the game's own item
code; a lost connection does not replay it.

### Owner decisions (reported, not changed)

1. **The lure's extra shiny roll** reaches every Pokemon made for the player while a lure lasts, gifts and static
   encounters included (not Eggs, not Local Soft Reset hunts, not a world's shared Pokemon). It comes from
   pokeemerald-expansion and was never written down. Keep it, or limit it to wild Pokemon?
2. **The lure's "rarer Pokemon" effect** (the original swaps common and rare table slots 20 % of the time) only changes
   the level here, because species are randomized. Restoring a rarity effect in the randomized pool would be a new lure
   effect, which the request says not to invent.
3. **Lures and Repels replace each other without a warning** (one counter): using a Repel during a Lure ends the Lure and
   its remaining steps are lost (and the reverse). A confirmation, or refusing it like a second Lure, are both possible.
4. **A lure used on land in a connected world** counts its steps although that land's Pokemon are the host's shared ones
   (only the water's are the player's own); a personal item cannot change Pokemon every player shares.

## 6. Testing and what remains unverified

(in progress)
