"""The battle structures' offsets and the Mega species numbers of one game build, read from its own debug information by
gdb (read only: nothing runs), for native_launcher_mega_proof.py. gdb reads a Linux build's and a MinGW Windows build's
alike, and the two layouts differ (MinGW's bitfields and 8-byte alignment), so a Windows proof takes its numbers from
the Windows build itself: the engine job writes them from the game before its strip (windows-package.yml).

    python scripts/multiplayer/mega_facts.py --game pokeemerald-mp.exe --out mega-facts.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

LEADS = ("SPECIES_CHARIZARD_MEGA_X", "SPECIES_CHARIZARD_MEGA_Y", "SPECIES_MEWTWO_MEGA_X", "SPECIES_MEWTWO_MEGA_Y")
QUERIES = {
    "mon_size": "sizeof(struct BattlePokemon)",
    "gimmick": "(int)&((struct BattleStruct*)0)->gimmick",
    "usable": "(int)&((struct BattleGimmickData*)0)->usableGimmick",
    "select": "(int)&((struct BattleGimmickData*)0)->playerSelect",
    "active": "(int)&((struct BattleGimmickData*)0)->activeGimmick",
    "active_size": "sizeof(((struct BattleGimmickData*)0)->activeGimmick)",
}


def game_facts(game) -> dict:
    """Offsets and the Mega species numbers from the game's debug information."""
    names = list(QUERIES) + list(LEADS)
    command = ["gdb", "-batch", "-nx"]
    for name in names:
        command += ["-ex", "print " + QUERIES.get(name, f"(int){name}")]
    out = subprocess.run(command + [str(game)], capture_output=True, text=True, timeout=300).stdout
    values = [int(line.split("=", 1)[1]) for line in out.splitlines() if line.startswith("$")]
    if len(values) != len(names):
        raise RuntimeError(f"gdb answered {out!r}")
    facts = dict(zip(names, values))
    facts["megas"] = [facts[name] for name in LEADS]
    return facts


def load_facts(path) -> dict:
    facts = json.loads(Path(path).read_text())
    facts["megas"] = tuple(facts["megas"])
    return facts


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True, help="a game build with its debug information")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    facts = game_facts(args.game)
    args.out.write_text(json.dumps(facts, indent=1))
    print(json.dumps(facts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
