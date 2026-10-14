# EmeraldTogether: two-player Windows test (Native 3D preview 13)

For the owner's PCs. What the cloud could not test: Windows on real hardware with a graphics
card, two PCs over a network, and playing it by hand. Everything below was tested in the cloud
with native Linux games and (where named) the Windows game under Wine; see `TEST_PLAN.md`.

Package: the checkpoint folder `emeraldtogether-combined-20261014-1` (launcher "Native 3D
preview 13": the expansion (shared wild Pokemon, outbreaks, followers, the permanent Exp. Share,
co-op battle experience) together with preview 12 (Battle FX, the original Poke Ball animations,
the new menus); its README names the engine and app commits). It replaces the expansion's
preview 2 (`emeraldtogether-expansion-20261013-2`) and preview 12
(`emeraldtogether-nativeui-20261013-1`); both stay as rollback points.

## Before you start

* **Both players need this package.** It speaks multiplayer protocol 3 (shared wild Pokémon);
  an older launcher is refused when it joins, with a message, and nothing is changed.
* Your worlds, characters and saves stay where they are
  (`%LOCALAPPDATA%\PokemonPrivate\launcher`). Going back to an older launcher (preview 10)
  still opens the same world; the new shared-spawn records in the world are simply ignored there.
* Two PCs on the same home network: the host uses **Host address on this PC** = its Wi-Fi/LAN
  address (not 127.0.0.1), and the friend joins with their personal invitation, as set up
  before (**Set up a world or character… → I'm joining a friend**, then the host exports the
  invitation). If the friend is not enrolled yet, do that first; this test does not change it.
* Optional, to see an outbreak quickly: close the launcher, then create a text file named
  `world.sqlite3.outbreaks.json` in your world's folder
  (`%LOCALAPPDATA%\PokemonPrivate\launcher\worlds\<world>\`, next to `world.sqlite3`) with

  ```json
  {"first_delay": [60, 60], "duration": [300, 300], "cooldown": [180, 180]}
  ```

  The first outbreak then starts after 1 minute online and lasts 5 minutes. Delete the file
  afterwards for the normal timing (first after 8-15 minutes online, 12-18 minutes long, 20-35
  minutes apart). A mistake in the file stops the host with a message naming the file.

Note the time of anything unexpected and take a screenshot (Win+Shift+S).

## A. One player (host alone)

1. **Host Game**, Continue, walk into the tall grass of a route (Route 101-104 are close to
   the start; any route with wild Pokémon works). Within about 10 seconds wild Pokémon appear
   in the grass with a rustle (a shiny one with a sparkle and sound), walk around and turn now
   and then. At most 8 on a map. *Expected:* none appear inside walls, buildings or water.
2. Walk up to one and press A: a normal wild battle with exactly that Pokémon (species, level,
   gender, shiny as shown). *Catch or defeat it:* it is gone after the battle and does not come
   back; another one appears later. *Run away:* it is still there.
3. Surf (if you can): water Pokémon still appear as before (they stay personal). Fishing and
   Rock Smash are unchanged.
4. If you can reach it: the **Safari Zone** keeps its own Pokémon and Safari battles (shared
   Pokémon are not used there).
5. **Outbreak** (with the quick file, or after 8-15 minutes): a notice "MASS OUTBREAK:
   <NAME>! / <ROUTE>  15:00 left". Go there: up to 12 wild Pokémon, most of them that species.
   A reminder at 5:00 left; at the end "The <NAME> outbreak / on <ROUTE> has ended." and the
   route goes back to at most 8 (a Pokémon you are battling is never taken away).
6. Close the game and the launcher normally, open it again and **Host Game**: the same wild
   Pokémon are still there (with their remaining time), and an outbreak continues where it was.
7. **Exp. Share** (Phase 1). With two or more Pokémon in the party, win a wild or trainer battle
   with only your lead: after "<lead> gained N Exp. Points!" the game says "The rest of your team
   gained Exp. Points thanks to the Exp. Share!" and every other Pokémon that can battle got half
   (Summary > the EXP. bar). No item is needed and there is no switch. Fainted Pokémon and eggs get
   none.

8. **Route 110** (if you are there): beat Psychic Edward; his defeat line used to crash the game
   (U13). *Expected:* no crash.
9. **Two trainers at once** (two trainers who see you at the same moment, a 2-against-2 battle):
   every Pokemon of both trainers gives experience (G14). *Expected:* an "Exp. Points" message
   after each opposing Pokemon faints, also the second trainer's.
10. **Battle FX and menus** (preview 12): any battle shows the HD move animations and the
   original Poke Ball animations; START, the party, the bag and the Trainer Card open and close.

## B. Two players (A hosts, B joins)

1. **Same Pokémon for both.** Stand near each other on a route with grass. Compare what you see
   (screenshots side by side): the same species at the same places, the same shiny colours and
   genders, moving the same way.
2. **Claim race.** Both stand next to the same Pokémon, facing it, and press A at the same
   moment. *Expected:* exactly one of you gets the battle; the other sees "Another TRAINER is
   battling this POKéMON right now!" and the Pokémon stays visible for them, standing still.
3. The winner **catches or defeats** it: it disappears for both of you and never comes back.
   Repeat with another one and **run away** instead: it is free again for both; the other
   player can now battle it.
4. **Followers.** Both have a Pokémon following. Each sees the other's follower behind the other
   player: the right species and form (for example an Unown's letter), shiny colours. Pressing A
   at the other player or at their follower does nothing; you can walk through them.
5. **Transitions.** B enters a building and comes out; B enters a cave; B surfs (B's follower
   is hidden while surfing and comes back after landing); B starts a wild battle (for A, B and
   B's follower disappear during the battle and come back after); B rides a Pokémon if
   available (A sees the mount). A large follower (for example Wailord) waits outside
   buildings.
6. **Outbreak together.** Both go to the outbreak route: the same 12 (at most) Pokémon for
   both. On a busy screen the farthest shared Pokémon may appear only when you come closer
   (the game keeps room for people and followers).
7. **Disconnect during a battle.** B starts a battle with a shared Pokémon, then closes the
   game window (Alt+F4) in the middle of it. *Expected for A:* the Pokémon stays "busy". B
   starts the launcher again and joins: within a few seconds the Pokémon is free again for
   everybody (B's game lets go of a Pokémon it is no longer battling). If B does not come back,
   it is free again after 10 minutes of play.
8. **Battles between you and co-op Gyms.** *PvP 1v1:* no experience for anyone (as in
   Emerald's link battles); both parties are exactly as before the battle. *Co-op Gym battle*
   (owner decision 2026-10-13): Players > team up, stand together in a Gym, challenge it
   together, fight to the end. *Expected:* after the battle each of you, in your own game, gets
   "<Pokemon> gained N Exp. Points!" for your own Pokemon only: the ones that fought get the full
   amount, the rest of your team half (Exp. Share), fainted ones and eggs none; level-ups, new
   moves ("forget a move?") and evolutions follow, then the game saves as usual. Nothing is
   given twice if you close and open the game again. The battle is slow to relay between the
   two games (KNOWN_ISSUES M25): note how long a turn takes on your PCs.
9. **Host restart.** A closes the host (everyone sees the host connection lost; follow the
   launcher's messages), opens it again and hosts; B joins again: the shared Pokémon and an
   outbreak continue.

## What to send back

For each step: OK, or what happened instead, with the time and a screenshot. Also the frame
rate you see on your graphics card (the cloud has none) and anything that looks wrong in 3D
around the wild Pokémon (sizes, shadows, placement on slopes).

## Known limits of this build

* At most 16 objects can be on the field at once (the GBA engine's limit), shared with the map's
  own people, the players and followers: the nearest shared Pokémon are drawn first.
* While you are in a menu or talking to someone, the other players and their followers are
  hidden (as before).
* A player who loses the connection during a battle, stays away for more than 10 minutes of
  play and then catches the Pokémon offline can end up with a copy that someone else also
  catches (the host cannot see an offline catch).
* The species weights follow the weather the first player on a map reports; players whose games
  show a different weather still see the same Pokémon.
* Outbreaks are announced by notices only; a PokéNav list comes later (Phase 7).
* Other players jumping down a ledge are drawn with quick steps, and so are their followers.
