# Legendary persistence, spawn timers and shiny odds (2026-10-27)

The owner's "Two Additional Small-Fix Queue Tasks" (legendary persistence, the spawn timer audit) and the expanded shiny
odds audit ("4 shiny Trubbish in about 10 minutes" in the Safari Zone). Nothing here is packaged.

Where a result comes from: **L** this Linux machine (real game processes of the Classic 2D test build, the game's own
code in self-tests, the host's code in unit tests). Nothing here was tried on Windows, on the owner's PCs or between two
real PCs.

Engine: `claude/feature-update-engine` `11f8be05` (PC only; the GBA ROM unchanged). App: `claude/admiring-bohr-dpxzuy`.

## 1. Legendary and Mythical Pokemon stay until somebody meets them

**Done**, for the two places a Legendary or Mythical appears in the wild by itself:

* **A world's shared Pokemon** (the host, `shared_spawns.py`): a shared Pokemon becomes a Legendary or Mythical at its
  first claim (Update 29's 1 in 6000). Before, it then aged like any other: it could expire after its 3 to 6 minutes,
  be retired when everybody walked 18 tiles away, or be trimmed when an outbreak ended. Now `Slot.kept` includes it,
  as for a shiny: no lifetime, never retired or trimmed.
* **The player's own visible Pokemon** (offline, the Safari Zone, and the water in a world; engine
  `src/wild_encounter_ow.c`, PC only): the roll is made when a battle with a visible Pokemon starts, and replaces that
  battle's Pokemon. Before, the object on the field stayed the Pokemon the roll replaced: run from, the Legendary
  came back as (say) a Fletchling, so the Legendary was gone after one look. Now the battle remembers the roll
  (`MPLegend_TakeBattleLegend`), and unless the battle caught or knocked it out, the Pokemon standing there **is** the
  Legendary from then on: it comes back as itself where it stood, is never despawned (off screen, by replacement, on
  entering a town, in a world when the player leaves the water), and is put back on its map whenever the player is
  there again (the shiny keep list, MS-79). A Legendary is also never rolled again into another one.

| Requirement | Shared (host) | Own visible Pokemon (engine) |
| --- | --- | --- |
| Not removed by its lifetime | Yes (`kept`); unit test | Yes (no-despawn flag; replacement never takes it) |
| Not removed by distance or no players nearby | Yes (never retired); unit test | Yes (kept off screen); **L** real game: drawn while off screen |
| Leaving and coming back | Yes (the host keeps it) | Yes; **L** real game: into Littleroot Town and back, "owe keep: back" with the same species |
| Host restart | Yes (saved with its `legend` flag, restored once); unit test | Not applicable |
| Closing and starting the game again | Not applicable | **No**: the keep list is not saved (MS-145) |
| Species, form, shiny, level | Kept (only the species and form change, at the claim) | Species, shiny, gender and level kept; nature and IVs are made again for each battle, as for every visible Pokemon |
| No duplicates, one at a time | First claim wins, a second claimant gets BUSY; unit test | One object; **L** real game: one local id while it was out |
| Caught or knocked out | Removed for good; unit test | Removed for good; **L** real game: "won", never drawn again |
| Run from, fled, lost, battle cancelled | Stays; unit test | Stays (only a win or a catch lets go); **L** real game: run from |
| Disconnecting during the battle | Kept for the claimant 10 minutes, then open again; unit test | Not applicable |

Real game runs (Classic 2D test build, `PKMN_TEST_LEGEND=1` forces the 1 in 6000 roll, `PKMN_TEST_OWE_REBUMP` walks
into the Pokemon again): a Latias rolled from a Fletchling, run from, came back as Latias (on the field in 19 one-second
samples, also past the GBA's picture), fought again and knocked out, never drawn again; a Groudon run from was put back from the
keep list ("owe keep: back") after its object's place was taken by a new spawn; an Arceus rolled from a Lotad stayed
away while the player walked into Littleroot Town and back, was put back on Route 101 ("owe keep: back local 252
species 493"), one object, and after it was knocked out nothing came back in the remaining 14 seconds.

Not run in a real game: a Legendary caught (the same branch as a shiny caught, which was run in the Safari Zone,
section 3), the player's team beaten by one, one fleeing on its own; on the host side, a real connected world (unit
tests only).

**World Events are left as they are** (an owner decision, reported): a legendary World Event is an announced, timed
event (its countdown shows in the PokeNav, "The legend slipped away..."), not a Legendary appearing by itself. A shiny
World Event already has no timer.

## 2. Spawn timers

The game has two spawners, each with one set of timers for every region, species and habitat; they differ from each
other by design.

| | The player's own visible Pokemon (`src/wild_encounter_ow.c`) | A world's shared Pokemon (host `spawn_director.py`, `shared_spawns.py`) |
| --- | --- | --- |
| Where | Offline everywhere; the Safari Zone always; the water (surfing, under the water) also in a world | Land of a connected world (not the Safari Zone or the Pokemon Tower) |
| At once | 4 | 8 (12 during an outbreak) |
| Next spawn | 30 frames + 30 per Pokemon out (0.5 to 2 s) | every 2.5 active seconds per map |
| Life | When 4 are out, the oldest is replaced every 240 frames (4 s): about 16 s each while the player stands still; gone when off screen; all gone on entering a town | 180 to 360 active seconds; retired at 45 s or more when 18 tiles from every player |
| Kept (never despawned) | shiny; Legendary/Mythical (new) | shiny, shiny for a Shiny Charm owner, Legendary/Mythical (new) |
| Clock | game frames; the encounter-rate items and abilities scale the waits (the wild item audit) | only while somebody is online; saved with the slots |

Measured in real game processes (Classic 2D test build, `PKMN_TEST_OWE_COUNT`, the player standing still for 64 s):
12 Pokemon made on Route 101, 12 on the Safari Zone's south map with the Safari flag off, 15 with it on; 4 out at once
in each. The same timer runs in the Safari Zone as everywhere else.

What the audit found and changed:

1. **Safari Zone battles skipped the end of a wild battle** (MS-142, fixed). `CB2_EndSafariBattle` never called
   `MPOWE_OnWildBattleEnd`, which every other wild battle calls. A shiny (or Legendary) caught there stayed on the keep
   list, so it was put back on the map after the next battle: a second copy of a Pokemon already caught. A Safari
   Pokemon run from also never came back, unlike anywhere else. The Safari battle now ends like any wild battle.
2. **Nothing else resets or duplicates a timer**: the countdown is one for the map, the replacement takes only Pokemon
   that are not kept, a battle's Pokemon is removed when the battle starts, and the run-return puts back only one with
   its local id free (no second copy).

Reported, not changed:

* **The two spawners' timers differ** (MS-146, owner decision). Making the visible spawner's Pokemon live 3 to 6
  minutes would cut how many different Pokemon a player meets a minute (and so the shinies a minute); making the
  shared ones live 16 s would make other players' Pokemon vanish before they arrive. Either changes encounter rates,
  which the request rules out. Recommended: keep both as they are.
* **Intentional exceptions**: some species' movement makes them leave when they notice the player (30 frames) or
  when a flight is blocked (upstream behaviours); a Lure makes the next spawn immediate while fewer than 4 are out;
  the encounter-rate items and abilities speed or slow the waits; the run-return remembers only the last Pokemon run
  from (a second battle before walking 3 tiles away lets the first one go, as a despawn would; kept ones are on the
  keep list instead).

## 3. Shiny odds

**The owner's report** (4 shiny Trubbish in about 10 minutes in the Safari Zone) **has a cause, now fixed (MS-142)**:
a shiny caught in the Safari Zone stayed on the keep list (the battle's end was skipped there), so after the next
battle it was put back where it had been caught, a second shiny of a Pokemon already in the party or the PC, and it
could be caught again. Reproduced in real game processes of the Classic 2D test build made without the fix (every
visible Pokemon made shiny with `PKMN_TEST_OWE_SHINY=2`, so the test does not wait for the 1 in 1024): a shiny Loudred
was caught (in the party afterwards), the next Safari battle ended, the player walked four tiles, and "owe keep: back
local 250 species 294" put a shiny Loudred back on the map; it walked into the player and started another battle. With
the fix the same catch logs "owe keep: caught" (the same shiny Meowth caught in the build without the fix and the build
with it, from the same start) and the Pokemon is gone. The odds themselves were right (below). At random, with the Shiny Charm in the Safari
Zone (1 in 1024.4), 4 shinies in 10 minutes would be about 1 chance in 59,000 at the 150 Pokemon the spawner makes
standing still (12 to 15 a minute, measured), and still 1 in 324 if walking made four times as many (not measured);
4 shiny **Trubbish** (0.29% of the Zone's Pokemon in the simulation below) would be about 1 in 3 x 10^12. The same
Pokemon coming back explains it; the odds do not.

Pokemon already caught are not touched: nothing here reads or changes a party, a box or a save. Any duplicates a
player already caught stay theirs.

**Every way a Pokemon is made**, through the game's own code (`--selftest-shiny-paths`, new;
`make -f Makefile_pc check-shiny-paths`): millions of Pokemon each, the shiny share against the documented odds
(4.5 sigma). The visible spawner's species come from the same generator as a hidden encounter
(`CreateEnemyPartyOWE` calls `TryGenerateWildMon`), and its shininess is one `ComputePlayerShinyOdds` call
(`SetSpeciesInfoForOWE`): the test makes exactly those two calls.

| Path | Intended | Observed | |
| --- | --- | --- | --- |
| Grass, a hidden encounter (Route 101) | 1 in 4096 | 970 of 4,000,000 (1 in 4124) | -0.2 sigma |
| Grass, a visible Pokemon | 1 in 4096 | 957 of 4,000,000 (1 in 4180) | -0.6 sigma |
| Surfing, a visible Pokemon (Route 109) | 1 in 4096 | 508 of 2,000,000 (1 in 3937) | +0.9 sigma |
| Under the water (Dive, Route 124) | 1 in 4096 | 526 of 2,000,000 (1 in 3802) | +1.7 sigma |
| Rock Smash (Route 111) | 1 in 4096 | 498 of 2,000,000 (1 in 4016) | +0.4 sigma |
| Fishing (chain fishing is off in this game) | 1 in 4096 | 497 of 2,000,000 (1 in 4024) | +0.4 sigma |
| A static Pokemon (Kyogre's script) | 1 in 4096 | 471 of 2,000,000 (1 in 4246) | -0.8 sigma |
| A gift Pokemon (Castform's script) | 1 in 4096 | 467 of 2,000,000 (1 in 4283) | -1.0 sigma |
| A roamer (Latios or Latias, made once per game) | 1 in 4096 | 247 of 1,000,000 (1 in 4049) | +0.2 sigma |
| A random Legendary/Mythical (keeps the replaced encounter's roll) | 1 in 4096 | 496 of 2,000,000 (1 in 4032); 200,000 forced rolls all kept the encounter's shiny status | +0.3 sigma |
| Grass, visible, Shiny Charm | 1 in 2500 | 1,657 of 4,000,000 (1 in 2414) | +1.4 sigma |
| A static Pokemon, Shiny Charm | 1 in 2500 | 808 of 2,000,000 (1 in 2475) | +0.3 sigma |
| Grass, visible, a Lure on (one extra roll) | 1 in 2048 | 2,049 of 4,000,000 (1 in 1952) | +2.2 sigma |
| A DexNav battle, chain 0 (4% get 4 extra rolls) | 1 in 3531 | 1,154 of 4,000,000 (1 in 3466) | +0.6 sigma |
| A DexNav battle, chain 50 (5 extra rolls) | 1 in 665 | 3,000 of 2,000,000 (1 in 667) | -0.1 sigma |
| A DexNav battle, chain 100 (10 extra rolls) | 1 in 367.5 | 5,480 of 2,000,000 (1 in 365) | +0.5 sigma |
| Safari Zone, visible (one extra roll) | 1 in 2048 | 1,877 of 4,000,000 (1 in 2131) | -1.7 sigma |
| Safari Zone + Shiny Charm (four rolls) | 1 in 1024.4 | 11,927 of 12,000,000 (1 in 1006) | within 4.5 sigma |
| Safari Zone + Charm, each of the 395 species against its own count | the same for every species | the most different species 3.4 sigma (expected for 395 species); **Trubbish** 34,748 made (0.29% of the Pokemon), 43 shiny (1 in 808, expected 34 +- 6) | |

Covered by earlier self-tests, unchanged here: Day Care Eggs (1 in 4096; 1 in 1365.7 with a shiny parent or the Charm;
1 in 682.8 with both: `--selftest-breeding`), Local Soft Reset hunts (1 in 4096, 1 in 2500 with the Charm:
`--selftest-wild-items`), the Charm's bonus on a world's shared Pokemon (a pure function of the Pokemon, 1 in 2500 in
all: `--selftest-shiny`).

The host's own rolls, through its own code (`SpawnDirector._fill`, the function every shared Pokemon comes from, a million Pokemon on Route 101): **1 in 4651** for everybody (documented 1 in 4096, -1.9 sigma) and **1 in 2618** for a Shiny Charm owner (documented 1 in 2500, -0.9 sigma). An outbreak's Pokemon use its `shiny_odds` (4096 by default, `outbreaks.py`): **1 in 4016** in a million (+0.3 sigma), **1 in 2494** for a Charm owner (+0.0 sigma); a World Event is shiny 1 time in 64 (`balance.py` `event_shiny_chance`), by design.

Not changed (reported before, still open): a Lure's extra roll also reaches gift and static Pokemon made while it lasts
(MS-132, inherited from pokeemerald-expansion). In-game trades use their fixed trainer ids (never shiny unless the data
says so), and the Battle Tower: Legends rewards are shiny by design.
