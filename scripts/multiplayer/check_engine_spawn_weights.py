"""Engine <-> host consistency of the wild Pokemon species weights
(EmeraldTogether expansion Phase 2, used by the Phase 3 shared spawns).

The host's SpawnDirector ports src/mp_wild_random.c (MPWild_RandomizeSpecies)
so that the shared wild Pokemon on a map are chosen as the game would choose
its own. This check runs the native game's --dump-wild-weights for every map of
the shared spawn catalogue and compares, value for value:

  1. the game's family table (tiers, habitats, times of day, types, members and
     their levels) with the catalogue's;
  2. for every catalogue map, both times of day and all 20 weathers, the land
     weight of every family as the game computes it (the map's area types, no
     weather underground, the Phase 2 weather table) with
     SpawnDirector.species_weights;
  3. the game's time of day for every hour with the host's (SharedWorld uses
     the night weights in the evening and at night, like the game).

    PYTHONPATH=src python scripts/multiplayer/check_engine_spawn_weights.py \\
        --game ../engine-graphics/pokeemerald-mp-diorama [--engine ../engine-graphics] [--output DIR]

(--engine, the game's source tree, defaults to the game's folder: the type
numbers come from its include/constants/pokemon.h.)

Exit status 0 when everything matches; the first differences are printed.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from emerald_multiplayer.shared_spawn_catalogue import CATALOGUE
from emerald_multiplayer.shared_spawns import SpawnBoards
from emerald_multiplayer.shared_world import time_of_day_for_hour
from emerald_multiplayer.spawn_director import SpawnDirector

TIERS = ["COMMON", "UNCOMMON", "RARE", "VERY_RARE"]


def engine_types(engine: Path) -> dict[int, str]:
    text = (engine / "include" / "constants" / "pokemon.h").read_text(encoding="utf-8")
    body = text[text.index("enum __attribute__((packed)) Type"):]
    body = body[:body.index("};")]
    return {int(value): name for name, value in re.findall(r"\b(TYPE_[A-Z]+)\s*=\s*(\d+)", body)}


def run_dump(game: Path, keys: list[str], workdir: Path) -> Path:
    keys_path = workdir / "maps.txt"
    keys_path.write_text("".join(f"{key}\n" for key in keys), encoding="ascii")
    out = workdir / "wild-weights.txt"
    result = subprocess.run([str(game), "--dump-wild-weights", str(keys_path), str(out)],
                            capture_output=True, text=True, timeout=300)
    if result.returncode != 0 or not out.exists():
        sys.exit(f"--dump-wild-weights failed ({result.returncode}): {result.stdout}{result.stderr}")
    return out


def parse_dump(path: Path) -> dict:
    dump = {"families": [], "members": [], "hours": {}, "maps": {}, "weights": {}, "absent": []}
    for line in path.read_text(encoding="ascii").splitlines():
        parts = line.split()
        if not parts:
            continue
        kind, values = parts[0], parts[1:]
        if kind == "family":
            dump["families"].append([int(v) for v in values[1:]])
        elif kind == "member":
            dump["members"].append([int(v) for v in values[1:]])
        elif kind == "hour":
            dump["hours"][int(values[0])] = values[1]
        elif kind == "hours":
            dump["bounds"] = [int(v) for v in values]
        elif kind == "nomap":
            dump["absent"].append(values[0])
        elif kind == "map":
            dump["maps"][values[0]] = [int(v) for v in values[1:]]
        elif kind == "w":
            dump["weights"][(values[0], int(values[1]), int(values[2]))] = [int(v) for v in values[3:]]
    return dump


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--game", type=Path, required=True, help="the native game (Linux build)")
    parser.add_argument("--engine", type=Path, help="the game's source tree (default: the game's folder)")
    parser.add_argument("--output", type=Path, help="keep the dump and a summary here")
    args = parser.parse_args()
    types = engine_types(args.engine or args.game.resolve().parent)

    catalogue = CATALOGUE
    keys = sorted(catalogue["maps"], key=lambda k: tuple(int(p) for p in k.split(".")))
    with tempfile.TemporaryDirectory() as tmp:
        workdir = args.output or Path(tmp)
        workdir.mkdir(parents=True, exist_ok=True)
        dump = parse_dump(run_dump(args.game, keys, workdir))

    problems: list[str] = []
    checks = 0

    # 1. The family table.
    if len(dump["families"]) != len(catalogue["families"]):
        problems.append(f"families: game {len(dump['families'])}, catalogue {len(catalogue['families'])}")
    for index, (game, cat) in enumerate(zip(dump["families"], catalogue["families"])):
        first, count, tier, habitat, time, type1, type2 = game
        want = [first, count, TIERS[tier], habitat, time, types.get(type1), types.get(type2)]
        checks += 1
        if want != list(cat):
            problems.append(f"family {index}: game {want}, catalogue {cat}")
    for index, (game, cat) in enumerate(zip(dump["members"], catalogue["members"])):
        checks += 1
        if game != list(cat)[:len(game)]:
            problems.append(f"member {index}: game {game}, catalogue {cat}")
    if len(dump["members"]) != len(catalogue["members"]):
        problems.append(f"members: game {len(dump['members'])}, catalogue {len(catalogue['members'])}")

    # 2. The land weights, map by map, day and night, every weather.
    director = SpawnDirector(catalogue, SpawnBoards(clock=lambda: 0.0), clock=lambda: 0.0)
    weather_names = {value: name for name, value in catalogue["weather"].items()}
    compared = 0
    for (key, night, weather), game_weights in sorted(dump["weights"].items()):
        name = weather_names.get(weather)
        host = dict(director.species_weights(key, 10, bool(night), name))
        game = {index: weight for index, weight in enumerate(game_weights) if weight}
        checks += 1
        compared += len(game_weights)
        if host != game:
            diff = sorted(i for i in set(host) | set(game) if host.get(i) != game.get(i))
            problems.append(f"{key} {catalogue['maps'][key]['constant']} {'night' if night else 'day'} {name}: "
                            f"{len(diff)} families differ, first {diff[0]}: game {game.get(diff[0])}, "
                            f"host {host.get(diff[0])}")
    # Catalogue maps in map groups this game does not build (the Kanto maps of an
    # Emerald build): nobody can stand there, so the host never fills them.
    absent = dump["absent"]
    missing = [key for key in keys if key not in dump["maps"] and key not in absent]
    if missing:
        problems.append(f"maps the game did not dump: {missing[:5]}")
    for key in absent:
        if catalogue["maps"][key].get("region") == "hoenn":
            problems.append(f"{key} {catalogue['maps'][key]['constant']}: a Hoenn map this game does not build")

    # 3. The time of day, hour by hour (hour 0 from the game's night bounds).
    night_begin, night_end = dump["bounds"][6], dump["bounds"][7]
    game_hours = dict(dump["hours"])
    if 0 not in game_hours and (night_begin > night_end):
        game_hours[0] = "night"
    for hour, game_name in sorted(game_hours.items()):
        checks += 1
        if time_of_day_for_hour(hour) != game_name:
            problems.append(f"hour {hour}: game {game_name}, host {time_of_day_for_hour(hour)}")

    summary = (f"{len(keys) - len(absent)} maps ({len(absent)} more not in this game), {len(dump['families'])} families, {len(dump['members'])} members, "
               f"{len(dump['weights'])} map/time/weather tables ({compared} weights), 24 hours: "
               f"{checks} checks, {len(problems)} differences")
    for problem in problems[:40]:
        print("DIFF", problem)
    print(summary)
    if args.output:
        (args.output / "summary.txt").write_text("\n".join(["DIFF " + p for p in problems] + [summary]) + "\n",
                                                 encoding="utf-8")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
