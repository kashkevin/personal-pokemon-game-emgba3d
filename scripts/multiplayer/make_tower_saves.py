"""Battle Tower: Legends' launcher proof sources (native_launcher_tower_proof.py), made by the game itself (Linux or
Windows): each is a save the game wrote at the end of its own short introduction (make_intro_saves.py), to which the
engine's test build gives a party and, for some, a Tower record (PKMN_TEST_BATTLE=save:1 with PKMN_TEST_PARTY and
PKMN_TEST_TOWER_RECORD: the game loads the save, sets them and saves through its own save code). Never a player build.

  tower-strong-a / -b   six level-100 Mewtwo, Dazzling Gleam first (above every Tower experience cap without badges;
                        no type is immune to the move: Psychic first stalled against floor 6's Carvanha, a Dark type)
  tower-fast-a / -b     as strong, the save's options fast text and battle scene off (a player's own OPTION choices,
                        PKMN_TEST_FAST_OPTIONS): the 100-floor climb, which otherwise ran past four hours
  tower-strong25-a      as strong-a, its record floor 24 cleared, 25 next: the milestone Pokemon (Giovanni's floor)
  tower-weak-b          a level-1 Magikarp (Splash only): it loses any floor
  tower-weak25-b        as weak-b, its record floor 24 cleared, 25 next: the special boss's loss (Giovanni)
  tower-mega-a / -b     as strong, the record floor 40 cleared, 41 next: the Mega Duo (Norman's Kangaskhan)
  tower-forfeit-a / -b  as strong, the record floor 12 cleared, 13 next: the forfeit (player 2's, -b: the
                        world's host stays up)
  tower-duo-a / -b      six level-100 Xerneas, Dazzling Gleam first (it hits both foes; no type is immune to it),
                        Choice Specs: the Duo climb
  tower-join-a          three level-10 Mewtwo, Dazzling Gleam first (below the Tower experience cap without badges,
                        15: they gain experience and levels), the record floor 11 cleared, 12 next: the player who has
                        climbed higher and joins (--scenario join)
  tower-join-b          as strong, the record floor 9 cleared, 10 next: the Duo's host, on its own floor (Brock)
  abandon-a / -b / -c / -d  one level-5 starter each (Treecko, Torchic, Mudkip, Treecko): the interrupted battle proof
                        (native_launcher_abandon_proof.py; players 3 and 4 from --source-c and --source-d)
  knockout-a / -b / -c / -d  a level-2 Torchic; two level-30 Mudkip with Earthquake first; two level-30 Zigzagoon
                        with Tackle first; four more: the interrupted battle proof's ffa-knockout and multi-knockout
                        (the host knocked out on the first turn of a battle that goes on; KNOWN_ISSUES MS-57). The
                        host's is the Torchic: Ground is super effective on it, so the first Earthquake knocks it out
                        whoever is targeted and whatever the roll. Every other trainer lasts several turns, so the
                        battle goes on with battler 0 out whoever partners the host: each turn of a double battle the
                        game decides at random (AI_REVERSE_BATTLER_LOGIC_ORDER_CHANCE, 50%) whether battler 0's action
                        menu is settled before battlers 2 and 3's, and only battler 1's, settled after battler 0's
                        either way, carries B_ACTION_NOTHING_FAINTED every turn (L knockout-2v2-2, with a level-2
                        Pokemon at battler 1 too: both turns after the knockout drew the order without it).
  mega2-a / -b          a level-50 Charizard holding Charizardite X / Y, the Mega Ring in the bag: the Mega Evolution
                        proof's 1v1 (native_launcher_mega_proof.py --scenario two)
  mega2-noring-b        as mega2-b without the Mega Ring (--scenario no-ring: never offered the Mega)
  rival-a / -b / -c / -d  one level-5 Pokemon each (Treecko, Torchic, Mudkip, Poochyena) on Route 110 just south of
                        its rival line (34,57 / 35,57 / 33,57 / 34,57: the line has three tiles, and each game is its
                        own copy of the world; the test build's PKMN_TEST_WARP): the rival checkpoint proof
                        (native_launcher_rival_proof.py; --players 4 is its 2v2)
  crush-a / -b / -c / -d  one level-5 Pokemon each (Treecko, Torchic, Mudkip, Poochyena), a POWDER JAR, 5 Cheri and
                        5 Chesto Berries and the POKEDEX's flag (the attendants talk of linking only after it), each
                        below the Direct Corner's attendant of a Pokemon Center 2F (10,3: Oldale Town's, Petalburg
                        City's, Rustboro City's, Slateport City's): the wireless minigame proof
                        (native_launcher_minigame_proof.py, KNOWN_ISSUES MS-141c; -c and -d its --players 3 and 4)
  jump-a / -b / -c / -d  a level-5 Pikachu or Marill (Pokemon Jump takes both), each in Mossdeep City's minigame
                        building across the counter from the old man (6,4): the same proof's Pokemon Jump
                        (--activity pokemon_jump)
  dodrio-a / -b / -c / -d  a level-5 Dodrio each, where jump-a and -b are: the same proof's Dodrio Berry Picking (three
                        players, its least; --activity dodrio; -d its --players 4)
  coop-a / -b           a level-5 Treecko and a Zigzagoon, a level-5 Torchic, each at its own spot in Littleroot Town
                        (4,3 and 7,3): the co-op Gym proof (native_launcher_coop_proof.py raises each lead to Lv. 60
                        with Crunch itself; --close-during-award 1, KNOWN_ISSUES MS-190)
  trade-forms-a / -b    a level-30 Female Meowstic, a level-50 Origin Giratina holding its Griseous Orb: a world trade
                        of two reviewed forms (native_launcher_newcomers_proof.py --scenario trade-forms, KNOWN_ISSUES
                        MS-194)
  trade-evolve-a / -b   a level-30 Small Pumpkaboo, a level-30 Large Pumpkaboo: each game evolves the one it receives
                        into the Gourgeist of its size (--scenario trade-evolve; MS-151's trade evolution of a form)

    python scripts/multiplayer/make_tower_saves.py --exe <Makefile_pc BFX_TEST=1 build> \\
        --mega-check <engine>/tools/battle_env/mega_check.py --source-a boy-1.sav --source-b girl-1.sav --out DIR \\
        [--only tower-strong-a,tower-weak25-b] [--display :93]

Player A's fixtures come from --source-a, player B's from --source-b, so the two players stay different trainers.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys
import types

from make_intro_saves import load

STRONG = ",".join(["150:100:v605"] * 6)                # SPECIES_MEWTWO, MOVE_DAZZLING_GLEAM first
WEAK = "129:1"                                         # SPECIES_MAGIKARP
DUO = ",".join(["716:100:v605i443"] * 6)               # SPECIES_XERNEAS, MOVE_DAZZLING_GLEAM, ITEM_CHOICE_SPECS
CRUSH_BAG = "719:1,514:5,515:5"                       # ITEM_POWDER_JAR, ITEM_CHERI_BERRY x5, ITEM_CHESTO_BERRY x5
FIXTURES = (  # (name, source, party, record "highest:progress" or None[, bag "item:count,..."[, warp G:N:W:X:Y[,
#              fast options[, flags to set "0x...,..."]]]])
    ("tower-strong-a", "a", STRONG, None),
    ("tower-strong-b", "b", STRONG, None),
    ("tower-fast-a", "a", STRONG, None, "", "", True),
    ("tower-fast-b", "b", STRONG, None, "", "", True),
    ("tower-strong25-a", "a", STRONG, (24, 25)),
    ("tower-weak-b", "b", WEAK, None),
    ("tower-weak25-b", "b", WEAK, (24, 25)),
    ("tower-mega-a", "a", STRONG, (40, 41)),
    ("tower-mega-b", "b", STRONG, (40, 41)),
    ("tower-forfeit-a", "a", STRONG, (12, 13)),
    ("tower-forfeit-b", "b", STRONG, (12, 13)),
    ("tower-duo-a", "a", DUO, None),
    ("tower-duo-b", "b", DUO, None),
    ("tower-join-a", "a", ",".join(["150:10:v605"] * 3), (11, 12)),   # SPECIES_MEWTWO at level 10: experience to gain
    ("tower-join-b", "b", STRONG, (9, 10)),
    ("abandon-a", "a", "252:5", None),                 # SPECIES_TREECKO
    ("abandon-b", "b", "255:5", None),                 # SPECIES_TORCHIC
    ("abandon-c", "c", "258:5", None),                 # SPECIES_MUDKIP
    ("abandon-d", "d", "252:5", None),
    ("knockout-a", "a", "255:2", None),                # SPECIES_TORCHIC: Ground is super effective, Earthquake KOs it
    ("knockout-b", "b", ",".join(["258:30:v89"] * 2), None),   # SPECIES_MUDKIP, MOVE_EARTHQUAKE: it hits every other trainer
    ("knockout-c", "c", ",".join(["263:30:v33"] * 2), None),   # SPECIES_ZIGZAGOON, MOVE_TACKLE
    ("knockout-d", "d", ",".join(["263:30:v33"] * 4), None),   # SPECIES_ZIGZAGOON, MOVE_TACKLE
    ("mega2-a", "a", "6:50:i293", None, "703:1"),     # SPECIES_CHARIZARD, ITEM_CHARIZARDITE_X; ITEM_MEGA_RING
    ("mega2-b", "b", "6:50:i294", None, "703:1"),     # ITEM_CHARIZARDITE_Y
    ("mega2-noring-b", "b", "6:50:i294", None, ""),
    ("rival-a", "a", "252:5", None, "", "0:25:0:34:57"),      # MAP_ROUTE110 (group 0, map 25): south of its line
    ("rival-b", "b", "255:5", None, "", "0:25:0:35:57"),
    ("rival-c", "c", "258:5", None, "", "0:25:0:33:57"),
    ("rival-d", "d", "261:5", None, "", "0:25:0:34:57"),      # SPECIES_POOCHYENA
    # MAP_OLDALE_TOWN_POKEMON_CENTER_2F (2.3), MAP_PETALBURG_CITY_POKEMON_CENTER_2F (8.5); FLAG_SYS_POKEDEX_GET
    ("crush-a", "a", "252:5", None, CRUSH_BAG, "2:3:-1:10:3", False, "0x861"),
    ("crush-b", "b", "255:5", None, CRUSH_BAG, "8:5:-1:10:3", False, "0x861"),
    # MAP_RUSTBORO_CITY_POKEMON_CENTER_2F (11.6), MAP_SLATEPORT_CITY_POKEMON_CENTER_2F (9.12); SPECIES_MUDKIP, POOCHYENA
    ("crush-c", "c", "258:5", None, CRUSH_BAG, "11:6:-1:10:3", False, "0x861"),
    ("crush-d", "d", "261:5", None, CRUSH_BAG, "9:12:-1:10:3", False, "0x861"),
    # MAP_MOSSDEEP_CITY_GAME_CORNER_1F (14.11), across the counter from the old man; SPECIES_PIKACHU, SPECIES_MARILL
    ("jump-a", "a", "25:5", None, "", "14:11:-1:6:4"),
    ("jump-b", "b", "183:5", None, "", "14:11:-1:6:4"),
    ("jump-c", "c", "25:5", None, "", "14:11:-1:6:4"),
    ("jump-d", "d", "183:5", None, "", "14:11:-1:6:4"),
    ("dodrio-a", "a", "85:5", None, "", "14:11:-1:6:4"),       # SPECIES_DODRIO
    ("dodrio-b", "b", "85:5", None, "", "14:11:-1:6:4"),
    ("dodrio-c", "c", "85:5", None, "", "14:11:-1:6:4"),
    ("dodrio-d", "d", "85:5", None, "", "14:11:-1:6:4"),
    # MAP_LITTLEROOT_TOWN (0.9), the spots native_launcher_multi_proof.py gives players 0 and 1; SPECIES_TREECKO with
    # a SPECIES_ZIGZAGOON (two Pokemon: one sent out, one not), SPECIES_TORCHIC
    ("coop-a", "a", "252:5,263:5", None, "", "0:9:-1:4:3"),
    ("coop-b", "b", "255:5", None, "", "0:9:-1:7:3"),
    # engine form IDs (species_national.py): SPECIES_MEOWSTIC_F, SPECIES_GIRATINA_ORIGIN with ITEM_GRISEOUS_ORB,
    # SPECIES_PUMPKABOO_SMALL and _LARGE
    ("trade-forms-a", "a", "1155:30", None),
    ("trade-forms-b", "b", "1071:50:i403", None),
    ("trade-evolve-a", "a", "1157:30", None),
    ("trade-evolve-b", "b", "1158:30", None),
)


def make_one(mega_check, exe, display, source, out, name, party, record, bag="", warp="", fast=False, flags=""):
    """The test build loads `source`, gives it `party` (and `record`, and `bag`'s items; at `warp` first; with `fast`
    the options fast text and battle scene off; `flags` set) and saves; the copy is OUT/name.sav."""
    rundir = out / f"run-{name}"
    env = dict(PKMN_TEST_BATTLE="save:1", PKMN_TEST_PARTY=party, PKMN_TEST_BAG=bag, PKMN_TEST_AUTOPILOT="1",
               PKMN_TEST_BATTLE_DELAY="60", PKMN_TEST_FREEZE_FIELD="1")
    if record is not None:
        env["PKMN_TEST_TOWER_RECORD"] = f"{record[0]}:{record[1]}"
    if warp:
        env["PKMN_TEST_WARP"] = warp
    if fast:
        env["PKMN_TEST_FAST_OPTIONS"] = "1"
    if flags:
        env["PKMN_TEST_SET_FLAGS"] = flags
    args = types.SimpleNamespace(exe=str(exe), save=str(source), display=display)
    process, output = mega_check.start(args, str(rundir), env)
    code = mega_check.finish(process, output, 240)
    lines = mega_check.driver_lines(str(rundir / "test.log"))
    problems = []
    if code != 0:
        problems.append(f"exit {code}")
    if not any(line.startswith("the save is written") for line in lines):
        problems.append("the game wrote no save")
    party_size = len(party.split(","))
    if sum(1 for line in lines if line.startswith("test Pokemon ")) != party_size:
        problems.append(f"not {party_size} test Pokemon")
    if record is not None and f"the Tower record: highest {record[0]}, progress {record[1]} (valid 1)" not in lines:
        problems.append(f"no Tower record {record}")
    if fast and "the options: text speed fast, battle scene off" not in lines:
        problems.append("the options were not set (a test build without PKMN_TEST_FAST_OPTIONS)")
    for flag in filter(None, flags.split(",")):
        if f"flag {flag} set" not in lines:
            problems.append(f"flag {flag} was not set")
    if problems:
        sys.exit(f"{name}: {'; '.join(problems)}; see {rundir}")
    shutil.copy(rundir / "test.sav", out / f"{name}.sav")
    print(f"{name}: {party_size} Pokemon" + (f", Tower record floor {record[0]} cleared" if record else ""))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--exe", type=Path, required=True, help="a test build (Makefile_pc BFX_TEST=1)")
    parser.add_argument("--mega-check", required=True, help="the engine's tools/battle_env/mega_check.py")
    parser.add_argument("--source-a", type=Path, required=True, help="player A's short-introduction save")
    parser.add_argument("--source-b", type=Path, required=True, help="player B's short-introduction save")
    parser.add_argument("--source-c", type=Path, help="player C's short-introduction save (abandon-c, rival-c, crush-c, ...)")
    parser.add_argument("--source-d", type=Path, help="player D's short-introduction save (abandon-d, knockout-d, rival-d, crush-d, ...)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", default="", help="comma-separated fixture names (default: all)")
    parser.add_argument("--display", default=None, help="Linux: an X display for the game")
    args = parser.parse_args()
    mega_check = load(args.mega_check)
    only = {name for name in args.only.split(",") if name}
    unknown = only - {fixture[0] for fixture in FIXTURES}
    if unknown:
        sys.exit(f"unknown fixtures {sorted(unknown)}")
    args.out.mkdir(parents=True, exist_ok=True)
    sources = dict(a=args.source_a.resolve(), b=args.source_b.resolve())
    sources.update({key: path.resolve() for key, path in (("c", args.source_c), ("d", args.source_d)) if path})
    for name, source, party, record, *bag in FIXTURES:
        if not only or name in only:
            if source not in sources:
                sys.exit(f"{name}: --source-{source} is needed")
            make_one(mega_check, args.exe.resolve(), args.display, sources[source], args.out.resolve(), name, party,
                     record, *bag)
    return 0


if __name__ == "__main__":
    sys.exit(main())
