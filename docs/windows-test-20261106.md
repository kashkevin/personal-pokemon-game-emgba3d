# The builds of 2026-11-05 and 2026-11-06: a real Windows PC checklist (1-4 players)

What only the owner's PCs can show for this build's changes (`docs/outstanding-issues.md` section 4): a real graphics
card, a controller, two PCs on a home network and over the Internet, an installation and an update on a player's PC.
Every item below is unverified until it is ticked on a real PC; GitHub's Windows runners (no graphics card, one machine)
are not a player's PC. The issue in brackets is the row in KNOWN_ISSUES or `docs/owner-decisions.md`.

Back up first: each player's private folder `%LOCALAPPDATA%\PokemonPrivate` (characters, saves, worlds: `world.sqlite3`
and every `world.sqlite3.*` beside it). Neither Setup nor the uninstaller touches it.

If something fails, note the time and keep: `%LOCALAPPDATA%\PokemonPrivate\shell\last-error.txt`, the newest game launch
folder under `%LOCALAPPDATA%\PokemonPrivate\launcher\launches\` (its `runtime.log` and, after a crash, `crash.log`), and
on the host the world's folder.

## Installing and updating

- [ ] A fresh install on PC 1: the launcher starts, the graphics check picks the 3D view on the graphics card (or offers
      Classic 2D), a new character plays the short introduction and saves; close; Continue loads the same place and party.
- [ ] Setup run over the earlier build (any you installed before: run 322's, 334's or later, up to 380's): every
      character, save and world kept; a hosted world asks once to get ready for the new version (a backup first); the
      Solo world brings the character back; play on, save.
- [ ] Uninstall, then install again: the private folder and everything in it are still there.

## The 3D view on a graphics card

- [ ] F10 > Show frame rate on; walk from Mauville west into Route 117, back east through Mauville into Route 118 and
      back, running: no ground or buildings popping in at a map's edge, no hitch at the crossings (MS-118, #42).
- [ ] Battle transitions drawn sharp at the window's size (MS-108): a Team Aqua or Magma member's battle; a Regi; Kyogre,
      Groudon or Rayquaza where the story reaches them; a Battle Frontier battle (the logo and circles); an Elite Four
      member and the Champion (the banners' wavy edges smooth, the faces even pixel art, the white fade smooth).
- [ ] A double battle in which one side has a single Pokemon: the battle effects land on that Pokemon (MS-200).
- [ ] The S.S. Tidal's porthole scene shows the ship (3D vehicles, #44).
- [ ] Mr. Briney's boat (F10 > Show frame rate on), Dewford to Route 104 and Route 109 to Dewford: no hitch as the next
      map's ground comes into view, and the sea's edges keep moving with the rest of the water as they come back into view
      (MS-82, engines `c81da595` to `5b18ebf1`).
- [ ] A Battle Frontier transition with the logo or the circles (any Frontier facility's battle): the circles and the
      logo's outline smooth, without steps (MS-108's vector pieces).
- [ ] The Battle Pyramid's top (Brandon's battle): both Pokemon stand on the summit, none in front of a tier's brick face
      (E5).
- [ ] Team Magma's hideout: its machines (servers, consoles, the long machine, the dome and drill rigs) stand as boxes
      as drawn, and in a battle there no Pokemon stands on a machine (E9); from the build after run 355, none stands in
      the lava either and the small 4F console stands too (E13).
- [ ] The sea stacks on Routes 105-109 and 124-134: their foot meets the water with no pale band and the small round
      stacks no ring of grey (MS-102). From the build after run 365: the boulders on the sand (Dewford Town by the Gym,
      Route 111's desert) stand on the sand with no grey specks at their foot.
- [ ] From the build after run 354: the Battle Dome (Battle Frontier west): its ends curve back with the dome's drum, no
      thin strips standing a storey tall beside it (V45).
- [ ] From the build after run 355, in either view: on a route at dusk by the game's clock (19:00 to 21:00), stand still
      for five minutes: the picture darkens step by step toward night (MS-205); before, it stayed as it was until the
      next map.
- [ ] From the build of engine `d93170ef` (the full run after run 356), in the 3D view: accept a challenge where the
      attendant saves first (a Battle Tent, the Battle Frontier, Trainer Hill): the game asks to save and saves; in the
      builds before it the 3D game closed there (MS-206).
- [ ] From the build of engine `72518ddf` on (run 394's installer, CI-394), in the 3D view: Safari Zone South, north of the entrance: the white
      rails are a raised walkway from the enclosure on the west to the plateau on the east, the plateau stands a
      level up with cliffs round it, no white stairs at the rails' west end, no lone rock block; walk over the rails
      and up the path north into the next Safari area (MS-222). Earlier builds laid the rails on the ground.
- [ ] From the build of engine `5be0c872` on (run 400's installer, CI-400), in the 3D view: Fortree City: the six tree houses stand on porches a
      level over the forest floor, the plank bridges between them at the porches' level, a ladder from each porch
      down to the floor; walk the south bridge east over the path north of the Gym (the people on the path pass
      under it), then walk that path under the bridge (the planks over the player's head), and climb a ladder
      (MS-223). Earlier builds laid the bridges and porches on the ground, the ladders flat.
- [ ] From the build of engine `57c30448` on (in the installer CI-406, `docs/package-20261110b.md`), in the 3D view: Victory Road 1F,
      the stairs north of the entrance up to the raised floor: they climb as steps, no dark ledge at their top,
      and walking up them the player rises with them, not a tile at once at the top; the same at Artisan Cave's
      and Shoal Cave's stairs (MS-224). Earlier builds laid them flat on the lower floor.
- [ ] From the build of engine `4379b94a` on (in the installer CI-406), in the
      3D view: Battle Frontier east, from the Battle Tower's plaza walk south down either lane past the flower bed to
      the plaza beyond: the ground rises gently, no step a level high where the lanes meet the plaza, the flower bed
      whole with no notch in its north edge, the bank west of it and its fences as before (MS-225). Earlier builds
      stood the Tower's plaza a level under the lanes.
- [ ] From the build of engine `bdffd8ff` on (in the installer CI-406), in the 3D view:
      the Cave of Origin from Sootopolis: walk the entrance's corridor from the door to the stairs down - the player, and
      any following Pokemon, whole on its floor, no pale block round the body; in Shoal Cave's rooms and Victory Road,
      step onto the corners of the floors beside the rock walls: the player stands on them (MS-228). Earlier builds stood
      those cells up as rock round the player.
- [ ] From the build of engine `1963fd2a` on (in the installer CI-416, `docs/package-20261110c.md`), in the 3D
      view: surf to the south end of Route 109 (south of Slateport's beach) and look over the sea to the south: no dark
      line across it where the route's map ends; round Birth Island, Navel Rock's shore and Faraway Island's dock, no
      dark outline or raised band of sea round the map (MS-229). Earlier builds drew a thin dark line along the sea at
      the map's edge.
- [ ] From the build of engine `4824c439` on (in the installer CI-416), in the 3D view: surf past the south end of
      Faraway Island's east strip, and look at the boulders in Meteor Falls 1F's pools: each boulder sits in the water
      at the water's level, no half of it raised in a box of water (MS-230). Earlier builds sank half of such a boulder.
- [ ] From the build of engine `e997f89c` on (in the installer CI-416), in the 3D view: in the Shoal Cave at high
      tide, the Marine Cave's or the Seafloor Cavern's entrance, look along the edge of the shallow water: no thin dark
      line where it meets the deep water (MS-231). Earlier builds drew one.
- [ ] From the build of engine `a2f4aa6f` on (in the installer CI-416), in the 3D view: in the Mauville Gym no thin
      wall stands in the black either side of the leader's alcove (no yellow specks there), and in the Battle Tower's
      battle room no thin red spike rises over the back wall's corners (MS-232). Earlier builds drew both.
- [ ] From the build of engine `8b5856e9` on (in the installer CI-416), in the 3D view: in the Cove Lily Motel 1F
      with a TV show on the air, the back wall stands whole over the television and beside the stairs; in the Trick
      House's last room the back wall is whole right of the doorway (MS-233). Earlier builds showed the tatami floor
      through both walls.
- [ ] From the build of engine `cdbb1776` on (in the installer CI-422, `docs/package-20261110d.md`), in the 3D view:
      in the Fortree Gym the three lone hedges stand low with their green squares on top (not cubes topped with the
      floor's lattice); in the Sootopolis Gym 1F the ice rocks on the open ice all stand alike, small, no block
      standing out beside a ledge (MS-227). Earlier builds stood them as tall blocks.
- [ ] From the build of engine `5b75fc6b` on (in the installer CI-422), in the 3D view: in a Battle Factory battle, the
      hall's side walls are plain beige with a straight red band at their foot (not striped, no sawtooth band), and
      the white floor tiles beside the scientists along both walls and at the back wall's foot carry no orange
      dashes; dive at the Seafloor Cavern's way in: the parked submarine lies whole in its hollow, no part of it a
      rock block (MS-227). Earlier builds drew all three.
- [ ] From the build of engine `cb0978fd` on (in the installer CI-423, `docs/package-20261110e.md`): in the Battle
      Tower, a multi battle with a partner the game provides: choose two Pokemon, save in the partner room, close the
      game and continue; finish or give up the challenge and leave: all six of your Pokemon are back in your party
      (MS-234). Earlier builds could write over the saved party count in that room (a rare state; the six Pokemon
      themselves stayed in the save).
- [ ] From the build of engine `b405af22` on (installer CI-425), in the 3D view: in the Battle Dome's battle room the
      audience sit on the stands, not only their hair and hats over them; in the Fallarbor Battle Tent's battle room the
      attendant stands in front of the low back wall, not inside it; in the Aqua Hideout's B2F the grunt behind the
      desk stands whole, not only the cap over it (MS-226). Nobody's place, walk or talk changes: the 3D view only.
- [ ] From the build of engine `440a11cc` on (in the installer CI-426, `docs/package-20261111b.md`), in the 3D view: in the Pokemon League's lobby (Ever Grande City), the
      back wall's orange band and white trim run whole beside and behind the PC on the right of the nurse's counter;
      at the doors of the Dewford, Petalburg, Fortree, Lavaridge, Mauville, Mossdeep and Sootopolis gyms no grey line
      lies under the statues' feet (MS-227). Earlier builds cut a black notch out of the lobby's wall there.
- [ ] From the build of engine `a79bc263` on (in the installer CI-426), in the 3D view with the settings' Camera set to Diorama: in Pacifidlog's
      houses, Mr. Briney's house, your own house and Rustboro's flats, black over the back wall's top, as the 2D
      game draws it, and the stairs still seen through a doorway in the back wall (MS-227). Earlier builds showed
      a strip of the room's floor over the wall there. In the default camera nothing changes.
- [ ] From the build of engine `566719d3` on (in the installer CI-427, `docs/package-20261111c.md`), in the 3D view: dive at the Seafloor Cavern's way in: the parked
      submarine is drawn as one picture, no edge of the water's surface across its hull and its lower part as clear
      as its top (MS-227); the hollow round it keeps the water's surface. Earlier builds drew its lower part under
      the surface, faint.
- [ ] From the build of engine `4b9cf4e3` on, in the 3D view: in a Battle Palace challenge, the battle room's back
      wall is whole - its four pillars and its door drawn on it, no black beside the outer pillars or the door, in
      the room and in its battles (MS-235). Earlier builds stood the outer pillars out from the wall and the door's
      posts behind it, a black wedge beside each.
- [ ] From the build of engine `efac4985` on, in the 3D view: the Battle Tower lobby's four lifts and the S.S. Tidal's
      and the Abandoned Ship's cabin doors stand upright in their walls, no black over them, and open on the wall when
      someone goes through - a black opening widening, the walker gone into it (MS-236). Earlier builds laid those doors
      back under black and opened them flat. The Battle Pike's doors are as before.
- [ ] From the build of engine `01eb62cc` on, in the 3D view: in a Battle Pike challenge, the curtain in the back wall
      of the rooms with a trainer, a helper or wild Pokemon stands with the wall, no black over it, its opening a row
      deeper where you walk in to leave; while it moves (you leaving, the Pike Queen coming out) it lies back as
      earlier builds drew it (MS-236).

## Settings and controls

- [ ] Audio (#45): the launcher's Settings > Audio, F10 > Audio and the pre-game menu's Audio volumes: master, music
      (70% at first), sound effects (100% at first) and cries each change what you hear at once and are kept after a
      restart. Say whether music at 70% suits you, also for a player who had played before this build.
- [ ] An Xbox controller (#43): B goes back or answers No on every multiplayer question and never confirms one; in the
      held trade window B asks "Cancel the trade?".

## Two PCs (then three or four)

- [ ] PC 1 hosts, PC 2 joins on the home network; then over the Internet (the router's UPnP/NAT-PMP, or the relay). A PC
      with another version is refused with "Different game versions" (MS-28).
- [ ] Location privacy (#47): "Share my location with other players" is off on a new character; the other player sees
      you online but no place on their PokeNav map or Players list; ticking it shows your place; on the same map your
      avatar shows either way.
- [ ] Trades (#39): an Egg, and a Pokemon holding Mail, each way; read the Mail afterwards; hatch the traded Egg (its
      hatcher becomes its trainer, not a Bad Egg); close one game in the middle of a trade and start again: each Pokemon
      is on exactly one side, nothing is lost or doubled.
- [ ] A World Event Pokemon (G3, #38): PC 2 starts its battle, then PC 2's launcher is closed (or its network pulled):
      nobody else can claim it; PC 2 comes back within five minutes and can still claim it; after five minutes away it is
      released to the others.
- [ ] A battle between the two players: on the waiting screen ("Link standby...") B asks "Give up the battle?"; Yes, and
      the giver loses on both PCs (MS-126); Run on one's own turn is the same forfeit.
- [ ] Together: a co-op Gym battle (EXP only with the win that earns the badge), the Battle Tower Duo, a wireless
      minigame (Berry Crush, Pokemon Jump, Dodrio Berry Picking) with two to four players.
- [ ] The Battle Tower's own screens show the host's record right after a result is settled (MS-52).
- [ ] Postgame (#40): a Legendary Ticket arrives once when its source is met (PLAYERS > World and my base > Frontier and
      League > Legendary Tickets says GIVEN), also after closing the game before saving and joining again.
- [ ] Close a game in the middle of a battle, a trade and a save, and start it again: nothing lost, nothing doubled; the
      host's world opens as before.
- [ ] A busy Pokemon Center (MS-208, MS-210): all the players and their following Pokemon in one Pokemon Center, then
      each heals at the counter: the Poke Balls glow, nobody's game closes, and afterwards the Fly map, a save and a
      Continue work as before (from the build with engine `f22f8a54`; earlier builds could write past the palettes when
      every sprite palette was taken).

## Optional, at your own risk (backups first)

- [ ] Switch a PC off while the game saves: on the next start the save before or after loads (MS-196: the save is
      written to the disk before it replaces the old one); a power cut was not tried anywhere.
- [ ] From the build of engine `70cf7d18` on (run 364's installer and later), a save that cannot be written (MS-212), in
      the Solo world and in a window (not full screen): while the game runs, open
      `%LOCALAPPDATA%\PokemonPrivate\launcher\players` in File Explorer, find the `character.sav` changed last (in a
      folder per world and per player), and in its Properties tick Read-only. Save in the game: the window's title says
      "the save file could not be written: trying again" (the 3D pause menu's save says it failed). Untick Read-only:
      within half a minute the title is back to normal and the file's time changes. Close the game, Continue: the place
      of that save loads. Untick Read-only before closing the game in any case. Only the self-test (a folder standing in
      the file's place) has run on Windows so far, not a real lock or a full disk.
- [ ] From run 367's installer on, the host's disk full while a friend saves (MS-214; only if the host has a drive or a
      partition to fill and empty safely): the friend's launcher says the host's PC could not store this save (its
      disk may be full) and that the progress is kept on that PC; nothing is lost. Free the space, reopen the world:
      the save arrives and play goes on. Tried on a Linux test disk and on a 64 MB NTFS virtual disk on GitHub's
      Windows runner (run 375), not on a PC.
- [ ] From run 369's installer on, your own disk full while you save to a world (MS-215; only with a drive or a
      partition you can fill and empty safely, the player's folder on it): Save now says this PC could not store
      the save (its disk may be full), so it was not sent, and to keep the game open; nothing is lost and saving
      goes on. Free the space and press Save now (or wait a minute for the autosave): the save is sent. Tried on a
      Linux test disk and on the NTFS virtual disk of run 375, not on a PC.
- [ ] From the first installer with engine `7b9f6bfa` on, a Windows account whose user name has an accent or another
      script (MS-217; for example a new local account named José): install and play there - a new character, a
      save, Continue - and the game opens the character's save and connects as on any other account. Earlier
      installers start the game there on an empty save without its connection to the launcher. Checked under Wine
      with such a folder, and on GitHub's Windows runner (run 377: both games loaded a save under "José Zoë" and
      two Chinese characters); never with a real account.
- [ ] From the first installer with app `b77cb84` on, the PC's date set back (MS-218; set it right again afterwards):
      with the date a day or more earlier, play and save twice, then Characters > your character > Back up now, and
      save once more. Restore an earlier version lists the newest versions first, the copy made with Back up now
      among them. Earlier installers deleted each new version as soon as it was written once 40 were kept. Tried
      in the tests only (on Linux, and on GitHub's Windows runner from run 380 on), never on a PC.
- [ ] From the first installer with app `bfc288e` on, the host's date changed during a Battle Tower battle (MS-219;
      two PCs or two accounts: the friend starts a Tower floor, the host sets the PC's date a day forward while it
      runs, then back): the friend's battle counts as it ends (a win stays a win). Earlier installers counted it as a
      loss at once. Tried in the tests only (on Linux, and on GitHub's Windows runner from run 382
      on), never on a PC.
- [ ] From the first installer with app `6af8b76` on, a second click on the EmeraldTogether icon while it is open, or
      while it is still opening (MS-220): one menu stays; the second click says EmeraldTogether is already open, and
      after OK nothing else opens. Earlier installers opened a second menu on the same files. Tried on Linux, and on
      GitHub's Windows runner by the installation check; not on a PC.
- [ ] From the first installer with app `310e470` on (run 394's, CI-394), EmeraldTogether ended while its game runs (MS-221; Task
      Manager > Details > EmeraldTogether.exe > End task, not the game): the game window closes too; start
      EmeraldTogether again and open the same world: the character has what was last saved, and only one game
      window opens.
      Earlier installers left the game running on its own, and a second one could open beside it. Tried on Linux;
      on GitHub's Windows runner by the installation check (run 391 on); not on a PC.
