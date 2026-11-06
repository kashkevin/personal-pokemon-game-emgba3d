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
- [ ] Setup run over the earlier build (run 322's or 334's): every character, save and world kept; a hosted world asks
      once to get ready for the new version (a backup first); the Solo world brings the character back; play on, save.
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

## Optional, at your own risk (backups first)

- [ ] Switch a PC off while the game saves: on the next start the save before or after loads (MS-196: the save is
      written to the disk before it replaces the old one); a power cut was not tried anywhere.
