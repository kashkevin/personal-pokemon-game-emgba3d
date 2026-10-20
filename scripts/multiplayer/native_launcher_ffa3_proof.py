"""Three native games through the whole launcher: a three-player free-for-all (1v1v1) from the Players menu.

Update 32 (feature 8): three players in one battle, every trainer on a side of their own (engine phase 6: the
free-for-all's four battlers with the fourth place empty, never two sides). The four-player proof's steps
(native_launcher_ffa_proof.py), for three:

    1. Everyone linked: each game has the other two as peers, every Players tab says "Connected: 3/4".
    2. The host opens PLAYERS > Challenges > New battle > "Free-for-All - 3 Players" (offered when exactly three are connected);
       the two others open PLAYERS, the pending challenge, and accept; all three press Enter battle.
    3. One native 1v1v1 (phase 6, three cores) runs with default moves to its end: every launcher reports
       battle_finished with its original game, bridge and native identity; each trainer's exact party is back in
       memory; the host's free-for-all book has the result (one of the three slots, or a draw).
    4. Back in the world: every game on the field, linked to the other two, the same server sessions as before.
    5. The harness's own end: all three save, each save's party is the canonical one, the store passes its integrity
       check, a normal close and a fresh Continue; money, coins, items, flags and variables unchanged by the battle.

    PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime \\
      python scripts/multiplayer/native_launcher_ffa3_proof.py \\
        --game ../engine/pokeemerald-mp --rom pokedev.gba --manifest manifest.json \\
        --source a.sav --source b.sav --source c.sav --display :94 --display :95 --display :96 \\
        --output /private/multiplayer-proof/native-launcher-ffa3-1
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows-runtime"))
from native_launcher_battle_proof import launcher_proof  # noqa: E402
from native_launcher_ffa_proof import MATCH_SECONDS, FreeForAll, into_littleroot  # noqa: E402
from qualify_admission_cleanup import require  # noqa: E402

PLAYER_NAMES = ("FFA3 Host", "FFA3 Friend 1", "FFA3 Friend 2")


class ThreePlayerFreeForAll(FreeForAll):
    PLAYERS, MODE = 3, 6


async def run(args):
    require(len(args.source) == 3 and len(args.display) == 3, "three sources and three displays, one per player")
    ffa = ThreePlayerFreeForAll(args.match_seconds)
    await launcher_proof(args, names=PLAYER_NAMES, sources=args.source, party_counts=(1,) * 3, match=ffa.match,
                         version="Native 1v1v1 proof", settings="windowScale=2\n",
                         scope=__doc__.split("\n\n")[0], after_boot=into_littleroot, after_save=ffa.after_save,
                         environment=dict(SDL_FRAMEBUFFER_ACCELERATION="0"),
                         on_harness=lambda harness: setattr(ffa, "harness", harness))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True, help="native Linux executable, unstripped")
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source", type=Path, action="append", required=True, help="a save per player (three)")
    parser.add_argument("--display", action="append", required=True, help="an X display per player (three)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0)
    parser.add_argument("--match-seconds", type=float, default=MATCH_SECONDS)
    parser.add_argument("--wine", type=Path, action="append", help="(not used)")
    parser.add_argument("--sdl", type=Path)
    parser.add_argument("--elf", type=Path)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
