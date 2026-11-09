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
- [ ] From the first installer with app `310e470` on, EmeraldTogether ended while its game runs (MS-221; Task
      Manager > Details > EmeraldTogether.exe > End task, not the game): the game window closes too; start
      EmeraldTogether again and open the same world: the character has what was last saved, and only one game
      window opens.
      Earlier installers left the game running on its own, and a second one could open beside it. Tried on Linux;
      on GitHub's Windows runner by the installation check (run 391 on); not on a PC.
