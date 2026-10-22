"""Battle Tower: Legends' launcher proof sources (native_launcher_tower_proof.py), made by the game itself (Linux or
Windows): each is a save the game wrote at the end of its own short introduction (make_intro_saves.py), to which the
engine's test build gives a party and, for some, a Tower record (PKMN_TEST_BATTLE=save:1 with PKMN_TEST_PARTY and
PKMN_TEST_TOWER_RECORD: the game loads the save, sets them and saves through its own save code). Never a player build.

  tower-strong-a / -b   six level-100 Mewtwo, Dazzling Gleam first (above every Tower experience cap without badges;
                        no type is immune to the move: Psychic first stalled against floor 6's Carvanha, a Dark type)
  tower-strong25-a      as strong-a, its record floor 24 cleared, 25 next: the milestone Pokemon (Giovanni's floor)
  tower-weak-b          a level-1 Magikarp (Splash only): it loses any floor
  tower-weak25-b        as weak-b, its record floor 24 cleared, 25 next: the special boss's loss (Giovanni)
  tower-mega-a / -b     as strong, the record floor 40 cleared, 41 next: the Mega Duo (Norman's Kangaskhan)
  tower-forfeit-a / -b  as strong, the record floor 12 cleared, 13 next: the forfeit (player 2's, -b: the
                        world's host stays up)
  tower-duo-a / -b      six level-100 Xerneas, Dazzling Gleam first (it hits both foes; no type is immune to it),
                        Choice Specs: the Duo climb

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
FIXTURES = (  # (name, source, party, record "highest:progress" or None)
    ("tower-strong-a", "a", STRONG, None),
    ("tower-strong-b", "b", STRONG, None),
    ("tower-strong25-a", "a", STRONG, (24, 25)),
    ("tower-weak-b", "b", WEAK, None),
    ("tower-weak25-b", "b", WEAK, (24, 25)),
    ("tower-mega-a", "a", STRONG, (40, 41)),
    ("tower-mega-b", "b", STRONG, (40, 41)),
    ("tower-forfeit-a", "a", STRONG, (12, 13)),
    ("tower-forfeit-b", "b", STRONG, (12, 13)),
    ("tower-duo-a", "a", DUO, None),
    ("tower-duo-b", "b", DUO, None),
)


def make_one(mega_check, exe, display, source, out, name, party, record):
    """The test build loads `source`, gives it `party` (and `record`) and saves; the copy is OUT/name.sav."""
    rundir = out / f"run-{name}"
    env = dict(PKMN_TEST_BATTLE="save:1", PKMN_TEST_PARTY=party, PKMN_TEST_BAG="", PKMN_TEST_AUTOPILOT="1",
               PKMN_TEST_BATTLE_DELAY="60", PKMN_TEST_FREEZE_FIELD="1")
    if record is not None:
        env["PKMN_TEST_TOWER_RECORD"] = f"{record[0]}:{record[1]}"
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
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", default="", help="comma-separated fixture names (default: all)")
    parser.add_argument("--display", default=None, help="Linux: an X display for the game")
    args = parser.parse_args()
    mega_check = load(args.mega_check)
    only = {name for name in args.only.split(",") if name}
    unknown = only - {name for name, *_ in FIXTURES}
    if unknown:
        sys.exit(f"unknown fixtures {sorted(unknown)}")
    args.out.mkdir(parents=True, exist_ok=True)
    sources = dict(a=args.source_a.resolve(), b=args.source_b.resolve())
    for name, source, party, record in FIXTURES:
        if not only or name in only:
            make_one(mega_check, args.exe.resolve(), args.display, sources[source], args.out.resolve(), name, party,
                     record)
    return 0


if __name__ == "__main__":
    sys.exit(main())
