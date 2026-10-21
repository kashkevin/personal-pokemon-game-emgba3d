"""New characters from the game's own short introduction, for the multiplayer proofs (no save is brought or kept).

The game makes each save itself: a fresh boot through the real title screen and main menu, NEW GAME, a boy or a girl
(alternating: boy-1, girl-1, boy-2, girl-2), the offered name, the arrival in Littleroot and the game's own save
(the engine's tools/battle_env/mega_check.py make_save with a test build, which presses the keys through
PKMN_DEBUG_KEYS; the girl's DOWN is tools/pc_port/intro32_check.py's). The game seeds its random numbers from the
PC's clock, so every character is a different trainer.

    python scripts/multiplayer/make_intro_saves.py --exe <Makefile_pc BFX_TEST=1 build> \\
        --mega-check <engine>/tools/battle_env/mega_check.py --out DIR --count 4
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import sys


def girl(keys):
    """The boy's presses with GIRL chosen (DOWN, then A) where BOY is (intro32_check.short_intro_keys)."""
    at = keys.index("980:A")
    return keys[:at] + ["970:DOWN", "1010:A"] + keys[at + 1:]


def load(path):
    path = Path(path).resolve()
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("mega_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--exe", required=True, help="a test build (Makefile_pc BFX_TEST=1)")
    parser.add_argument("--mega-check", required=True, help="the engine's tools/battle_env/mega_check.py")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--count", type=int, default=4)
    parser.add_argument("--display", default=None, help="an X display (Linux)")
    args = parser.parse_args()
    check = load(args.mega_check)
    boy = check.short_intro_keys()
    args.out.mkdir(parents=True, exist_ok=True)
    made = []
    for n in range(args.count):
        gender = ("boy", "girl")[n % 2]
        keys = boy if gender == "boy" else girl(boy)
        check.short_intro_keys = lambda keys=keys: keys
        path = args.out / f"{gender}-{n // 2 + 1}.sav"
        # an absolute program: on Windows a relative one is not looked up from the game's own folder
        check.make_save(argparse.Namespace(exe=str(Path(args.exe).resolve()), out=str(args.out.resolve() / f"made-{n}"),
                                           display=args.display), str(path.resolve()))
        made.append(path)
        print(f"{path.name}: the short introduction's save ({gender})", flush=True)
    return made


if __name__ == "__main__":
    main()
