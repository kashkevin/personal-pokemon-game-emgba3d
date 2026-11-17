# The next installer: the owner's release tests on real Windows PCs (2026-11-17)

The six release tests the owner asked for on 2026-11-17 (`docs/owner-decisions.md` #74) - a fresh install, an upgrade
over an existing save, a controller, a graphics-card benchmark, multiplayer on one network and over the Internet - for
the next installer: the one prepared from a full Windows run whose every job passes with engine `3821d2cb` or later
(its own `docs/package-*.md` names it; until then the newest prepared one is CI-476). Every item is unverified until it
is ticked on a real PC: GitHub's Windows runners have no graphics card, no controller and one machine, and nothing
here was tried on one. The installer stays private (N8, #70).

Back up first: each PC's private folder `%LOCALAPPDATA%\PokemonPrivate` (characters, saves, worlds: `world.sqlite3`
and every `world.sqlite3.*` beside it). Neither Setup nor the uninstaller touches it.

If something fails, note the time and keep: `%LOCALAPPDATA%\PokemonPrivate\shell\last-error.txt`, the newest game
launch folder under `%LOCALAPPDATA%\PokemonPrivate\launcher\launches\` (its `runtime.log` and, after a crash,
`crash.log`), and on the host the world's folder.

The earlier checklist (`docs/windows-test-20261106.md`) still holds for what it lists; below are the six tests and what
changed since it.

## 1. A fresh install

- [ ] On a PC (or a new Windows account) that never had EmeraldTogether: run Setup; the launcher starts; the graphics
      check picks the 3D view on the graphics card (or offers Classic 2D if the card's OpenGL is too old).
- [ ] A new character: the short introduction, the starter, the first save; close; Continue loads the same place and
      party. The one-time hint banner reads "Press START, then PLAYER, then STYLE" (M27, #68).
- [ ] Uninstall, then install again: the private folder and everything in it are still there.

## 2. An upgrade over an existing save

- [ ] Setup over the build installed now (CI-476's or earlier): every character, save and world kept; a hosted world
      asks once to get ready for the new version (a backup first); the Solo world brings the character back; play on,
      save, close, Continue.
- [ ] The old copies of world saves (MS-216, #72): before upgrading, count the `.flash` files in a world account's
      folder (`%LOCALAPPDATA%\PokemonPrivate\launcher\players\...`, one folder per world and player; a long-played world
      has hundreds). After the new launcher's first start: at most the newest 40 there (and their `.export.json`
      receipts); fewer than 40 before means none removed. Then open that world: the character comes back as last saved,
      and play and save there as before. The world keeps every save itself; only the PC's spare copies go.
- [ ] A world made before the upgrade with two players (if you have one): both join after both upgraded; a PC still on
      the old build is refused with "Different game versions" (MS-28).

## 3. A controller

- [ ] An Xbox-style controller plugged in before starting: the launcher's menu moves with the D-pad, A chooses and B
      goes back (U30-5).
- [ ] In the game: the D-pad and the stick walk; A, B (B cancels and answers No, never confirms a multiplayer question,
      #21, #43), Start and Select; in a held trade window B asks "Cancel the trade?".
- [ ] Unplug it mid-game and plug it back: it works again without restarting. Then (optional) a PlayStation controller.

## 4. The graphics card's benchmark

- [ ] With EmeraldTogether closed, copy a character's save that stands outdoors - `%LOCALAPPDATA%\PokemonPrivate\
      characters\<character>\current.sav` - to your Desktop as `bench.sav` (the benchmark never saves, the copy only
      keeps the original out of reach). In a Command Prompt:

      ```
      "%LOCALAPPDATA%\Programs\EmeraldTogether\_internal\runtime\pokeemerald-mp-diorama.exe" --save "%USERPROFILE%\Desktop\bench.sav" --benchmark 15 --bench-log "%USERPROFILE%\Desktop\benchmark.log"
      ```

      The game Continues by itself, measures the 3D field at 1280x720, 1920x1080, 2560x1440 and 3840x2160 (offscreen
      when the display is smaller) with VSync off and your quality settings, writes `benchmark.log` (average fps, 1 %
      and 0.1 % lows, frame-time percentiles, the GPU and CPU) and quits. Send the log. The directive's targets (V39):
      200+ fps at 1080p and 1440p, 180-200+ at 4K, 60+ on a low-end PC. The same command was run on GitHub's runner at
      720p only, through software OpenGL.
- [ ] Play ten minutes with F10 > Show frame rate on: Mauville west into Route 117 and east into Route 118, running (no
      ground popping in at a map's edge, no hitch at the crossings); a battle; Lilycove. F10's Graphics quality Low and
      Medium once each (V22: never looked at in the running game).

## 5. Multiplayer on one network (two PCs, then three or four)

- [ ] PC 1 hosts a world, PC 2 joins on the home network; the earlier checklist's items (privacy, Egg and Mail trades,
      World Events, a battle, a co-op Gym battle, the Tower Duo, a wireless minigame, a busy Pokemon Center) as before.
- [ ] Giving up in a battle together (#61): in a co-op Gym battle, the Tower Duo or a Frontier or League ladder battle,
      GIVE UP asks "Giving up ends this battle for both players." first; No goes back to the battle, Yes ends it as the
      team's loss on both PCs.
- [ ] Closing the game in a battle together (#61's second half, KNOWN_ISSUES MS-16's updates of 2026-11-14): close PC
      2's game 20 seconds into a co-op Gym battle (or a Tower Duo battle). For 3 minutes PC 1's launcher refuses Abandon
      and says why (PC 2 may come back: Recover battle); start PC 2 again: its launcher ends the battle as it opens the
      world, as the team's loss naming PC 2 ("BATTLE TOGETHER LOST" on both PCs; the Duo back to the floor after the
      last checkpoint, nothing paid); parties, items and money as before the battle. A crash counts as leaving too (a
      documented limit). Tried in real Linux games through real launchers, not on two PCs.
- [ ] The Legendary Tickets' co-op routes (#62): a co-op achievement a ticket names (`docs/legendary-tickets.md`)
      earns that ticket once for each player who took part, PLAYERS > World and my base > Frontier and League >
      Legendary Tickets says GIVEN; a player who was not there does not get it.

## 6. Multiplayer over the Internet

- [ ] The host's router lets the world in (UPnP/NAT-PMP, a forwarded port, or the relay); PC 2 on another network (a
      phone's hotspot) joins; a trade and a battle between the two: the battle's turns do not stall between actions
      (MS-62, M25: improved, never measured between two real PCs).

## What changed in the 3D view since the earlier checklist (look while playing)

- Rooms cut by hand or read off their cells (the object audit, #69): the Department Store, the museums, the harbors,
  the Contest Halls, the Fan Clubs, Stern's Shipyard, the Pokemon League 1F, Ever Grande's halls, the Battle Pyramid's
  lobby, Trainer Hill's entrance, floors and roof, the ship cabins - walls, counters and furniture stand.
- The dotted seams gone (class 6): the S.S. Tidal's and the Abandoned Ship's cabins, the Ranking Hall's corner, Wanda's
  house in Verdanturf (her rug by the chair, from a low camera), the tatami houses' entrances.
- The Acro Bike's bumpy slopes in four-pixel stone steps (Safari Zone North, Jagged Pass; #71 B); the Safari Zone
  South's rails on posts; Route 119's rails flat (#78, your choice).
- The tall grass's outlines softer (#59 C); the ground under the voxel trees matching (#60 B); the Ranking Hall's
  front without its two false windows (V44).
- With the sprite pack: Role Play's white silhouette and Snatch's runner are the animated sprites now (S7).

Choices waiting for your eyes while you play (`docs/owner-decisions.md`): #75 a tall Pokemon's head behind the foe's
lower databox in a double battle (Gardevoir in your left slot), #76 Spinda's spots, #77 a very tall Pokemon cut at the
Classic 2D battle's frame (Lugia or Rayquaza with Classic 2D), #78 Route 119's flat rails.

And one preview to try if you like (#71 C, smooth slopes; off unless asked for, never tried on Windows): close
EmeraldTogether, open a Command Prompt and type

```
set PKMN_DIORAMA_SMOOTH_SLOPES=1
"%LOCALAPPDATA%\Programs\EmeraldTogether\EmeraldTogether.exe"
```

The launcher started from that window passes the setting on to its game: Jagged Pass's bumpy slopes and Route 111's
mud are smooth ramps instead of steps - ride the Acro Bike up and down them and the Mach Bike up the mud, and look at
the rider on the slope. Starting EmeraldTogether the usual way is the steps again (B). Whether C becomes the default
(the bumpy slopes only, or the muddy ones too) is your choice, #71.
