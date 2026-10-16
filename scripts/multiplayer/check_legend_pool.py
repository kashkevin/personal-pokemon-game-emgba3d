"""Engine <-> host consistency of the random Legendary/Mythical pool (Update 29).

The game picks a random Legendary or Mythical for a wild encounter from the species whose habitat fits the area
(src/platform/mp_legend.c). The host makes the same roll for the shared land spawns (legend_rules.py). This check runs the
native game's --dump-legend-pool (its own pool for every map with land encounters, every weather, both times of day) and
compares it, list for list, with legend_rules.eligible() for every map of the shared spawn catalogue.

    PYTHONPATH=src python scripts/multiplayer/check_legend_pool.py --game ../engine/pokeemerald-mp

Exit status 0 when everything matches.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

from emerald_multiplayer import legend_pool, legend_rules
from emerald_multiplayer.shared_spawn_catalogue import CATALOGUE


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--game", type=Path, required=True)
    args = parser.parse_args()
    names = {value: name for name, value in CATALOGUE["weather"].items()}
    with tempfile.TemporaryDirectory() as work:
        out = Path(work) / "legend.txt"
        result = subprocess.run([str(args.game), "--dump-legend-pool", str(out)], capture_output=True, text=True, timeout=300)
        if result.returncode != 0 or not out.exists():
            sys.exit(f"--dump-legend-pool failed ({result.returncode}): {result.stdout}{result.stderr}")
        lines = out.read_text(encoding="ascii").splitlines()
    engine = {}
    for line in lines:
        parts = line.split()
        if parts and parts[0] == "L":
            group, number, weather, night, size = (int(v) for v in parts[1:6])
            species = [int(v) for v in parts[6:]]
            if len(species) != size:
                sys.exit(f"malformed dump line: {line[:80]}")
            engine[(f"{group}.{number}", weather, night)] = species
    species_in_engine = {species for pool in engine.values() for species in pool}
    checked = bad = 0
    for key, entry in CATALOGUE["maps"].items():
        for (map_key, weather, night), expected in engine.items():
            if map_key != key:
                continue
            tags = legend_rules.area_tags(entry["mapsec"], entry["map_type"], names.get(weather))
            got = legend_rules.eligible(tags, bool(night))
            checked += 1
            if got != expected:
                bad += 1
                if bad <= 10:
                    print(f"DIFFERENT {entry['name']} ({key}) weather {names.get(weather)} night={night}: game {expected} host {got}")
    # Kanto / Sevii maps of the catalogue are not built into an Emerald game: nobody can stand there (see
    # check_engine_spawn_weights.py), so only Hoenn maps must be listed by the game.
    missing = [key for key, entry in CATALOGUE["maps"].items()
               if entry.get("region") == "hoenn" and not any(k[0] == key for k in engine)]
    if missing:
        print("Hoenn catalogue maps the game's dump does not list:", missing[:10])
        bad += len(missing)
    table = {species for species, *_ in legend_pool.SPECIES}
    if not species_in_engine <= table:
        print("the game offers species the host's table lacks:", sorted(species_in_engine - table))
        bad += 1
    print(f"check_legend_pool: {checked} map/weather/time combinations compared, {bad} differences")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
