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
  abandon-a / -b / -c / -d  one level-5 starter each (Treecko, Torchic, Mudkip, Treecko): the interrupted battle proof
                        (native_launcher_abandon_proof.py; players 3 and 4 from --source-c and --source-d)
  knockout-a / -b / -c / -d  a level-2 Torchic; two level-30 Mudkip with Earthquake first; a level-2 Treecko; four
                        level-30 Zigzagoon with Tackle first: the interrupted battle proof's ffa-knockout and
                        multi-knockout (the host knocked out on the first turn of a battle that goes on; KNOWN_ISSUES
                        MS-57). The host's is the Torchic: Ground is super effective on it, so the first Earthquake
                        knocks it out whoever is targeted and whatever the roll. The battle then goes on for about eight
                        turns (Earthquake takes two turns per Zigzagoon): each turn of a double battle the game picks at
                        random (AI_REVERSE_BATTLER_LOGIC_ORDER_CHANCE, 50%) whether battler 0's action menu is settled
                        before the others' and so carries B_ACTION_NOTHING_FAINTED, and Windows run 145's 2v2s, two
                        turns long after the knockout, drew B_ACTION_NONE on every turn.
  mega2-a / -b          a level-50 Charizard holding Charizardite X / Y, the Mega Ring in the bag: the Mega Evolution
                        proof's 1v1 (native_launcher_mega_proof.py --scenario two)
  mega2-noring-b        as mega2-b without the Mega Ring (--scenario no-ring: never offered the Mega)
  rival-a / -b / -c / -d  one level-5 Pokemon each (Treecko, Torchic, Mudkip, Poochyena) on Route 110 just south of
                        its rival line (34,57 / 35,57 / 33,57 / 34,57: the line has three tiles, and each game is its
                        own copy of the world; the test build's PKMN_TEST_WARP): the rival checkpoint proof
                        (native_launcher_rival_proof.py; --players 4 is its 2v2)

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
FIXTURES = (  # (name, source, party, record "highest:progress" or None[, bag "item:count,..."[, warp G:N:W:X:Y[,
#              fast options]]])
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
    ("abandon-a", "a", "252:5", None),                 # SPECIES_TREECKO
    ("abandon-b", "b", "255:5", None),                 # SPECIES_TORCHIC
    ("abandon-c", "c", "258:5", None),                 # SPECIES_MUDKIP
    ("abandon-d", "d", "252:5", None),
    ("knockout-a", "a", "255:2", None),                # SPECIES_TORCHIC: Ground is super effective, Earthquake KOs it
    ("knockout-b", "b", ",".join(["258:30:v89"] * 2), None),   # SPECIES_MUDKIP, MOVE_EARTHQUAKE: it hits every other trainer
    ("knockout-c", "c", "252:2", None),                # SPECIES_TREECKO
    ("knockout-d", "d", ",".join(["263:30:v33"] * 4), None),   # SPECIES_ZIGZAGOON, MOVE_TACKLE
    ("mega2-a", "a", "6:50:i293", None, "703:1"),     # SPECIES_CHARIZARD, ITEM_CHARIZARDITE_X; ITEM_MEGA_RING
    ("mega2-b", "b", "6:50:i294", None, "703:1"),     # ITEM_CHARIZARDITE_Y
    ("mega2-noring-b", "b", "6:50:i294", None, ""),
    ("rival-a", "a", "252:5", None, "", "0:25:0:34:57"),      # MAP_ROUTE110 (group 0, map 25): south of its line
    ("rival-b", "b", "255:5", None, "", "0:25:0:35:57"),
    ("rival-c", "c", "258:5", None, "", "0:25:0:33:57"),
    ("rival-d", "d", "261:5", None, "", "0:25:0:34:57"),      # SPECIES_POOCHYENA
)


def make_one(mega_check, exe, display, source, out, name, party, record, bag="", warp="", fast=False):
    """The test build loads `source`, gives it `party` (and `record`, and `bag`'s items; at `warp` first; with `fast`
    the options fast text and battle scene off) and saves; the copy is OUT/name.sav."""
    rundir = out / f"run-{name}"
    env = dict(PKMN_TEST_BATTLE="save:1", PKMN_TEST_PARTY=party, PKMN_TEST_BAG=bag, PKMN_TEST_AUTOPILOT="1",
               PKMN_TEST_BATTLE_DELAY="60", PKMN_TEST_FREEZE_FIELD="1")
    if record is not None:
        env["PKMN_TEST_TOWER_RECORD"] = f"{record[0]}:{record[1]}"
    if warp:
        env["PKMN_TEST_WARP"] = warp
    if fast:
        env["PKMN_TEST_FAST_OPTIONS"] = "1"
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
    parser.add_argument("--source-c", type=Path, help="player C's short-introduction save (abandon-c, rival-c)")
    parser.add_argument("--source-d", type=Path, help="player D's short-introduction save (abandon-d, knockout-d, rival-d)")
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
