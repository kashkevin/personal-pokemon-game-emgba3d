#!/usr/bin/env python3
"""Re-derive the Update 31 rival catalogue from an engine or upstream checkout.

    python scripts/multiplayer/check_rival_catalogue.py --engine <checkout> [--json]

Reads only text/data files of the checkout (map JSON, scripts, constants,
layouts and tileset attributes); runs no game code. Checks, for every
checkpoint in ``rival_catalogue.CHECKPOINTS``:

* the map constant's (group, number) from data/maps/map_groups.json;
* each coordinate trigger's tiles, variable and value, and each talk object's
  position and script, in the map's map.json;
* every replaced trainer constant, flag and variable named exists;
* the battle environment the original NPC battle would draw at each trigger
  tile (``BattleSetup_GetEnvironmentId``: tile behaviour, then map type; the
  rival's trainer class has no special background), for talk triggers on the
  four tiles beside the object;
* the intro post-state table (docs/update31/intro-post-state.json): every
  flag/var/item/heal location named exists in the checkout;
* the enum index of each canonical battle environment (ENVIRONMENT_IDS), which
  the rival battle's preparation word carries;
* for an engine with the Update 31 port (include/constants/multiplayer_rival.h):
  the preparation tag, the checkpoint order, and that every original rival
  scene script asks the multiplayer layer first (under PORTABLE).

Exit status 0 when every check passes. Run it against the private engine
before porting the multiplayer scenes, since the fork may differ from upstream.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from emerald_multiplayer.rival_catalogue import CHECKPOINTS, ENVIRONMENT_IDS, PREPARATION_TAG  # noqa: E402

INTRO_TABLE = ROOT / "docs" / "update31" / "intro-post-state.json"
NUM_METATILES_IN_PRIMARY = 512


def _map_folders(engine):
    groups = json.loads((engine / "data/maps/map_groups.json").read_text())
    ids, folders = {}, {}
    for group_index, group in enumerate(groups["group_order"]):
        for number, folder in enumerate(groups[group]):
            data = json.loads((engine / "data/maps" / folder / "map.json").read_text())
            ids[data["id"]] = (group_index, number)
            folders[data["id"]] = folder
    return ids, folders


def _constants(engine):
    names = set()
    for header in ("include/constants/flags.h", "include/constants/vars.h", "include/constants/opponents.h",
                   "include/constants/items.h", "include/constants/heal_locations.h", "include/constants/species.h"):
        path = engine / header
        if path.exists():
            names.update(re.findall(r"\b((?:FLAG|VAR|TRAINER|ITEM|HEAL_LOCATION|SPECIES)_[A-Z0-9_]+)\b", path.read_text()))
    # Generated or enum-defined constants (trainers, heal locations) also appear in these sources.
    for extra in ("src/data/trainers.party", "src/data/heal_locations.json", "src/data/heal_locations.h"):
        path = engine / extra
        if path.exists():
            names.update(re.findall(r"\b((?:TRAINER|HEAL_LOCATION)_[A-Z0-9_]+)\b", path.read_text()))
    items = engine / "src/data/items.h"  # macro-generated item IDs (ITEM_HM_FLY) appear as table designators
    if items.exists():
        names.update(re.findall(r"\[(ITEM_[A-Z0-9_]+)\]", items.read_text()))
    return names


class _Behaviour:
    """Metatile behaviour lookup for one map, as MapGridGetMetatileBehaviorAt reads it."""

    def __init__(self, engine, map_data):
        layouts = {entry["id"]: entry for entry in json.loads((engine / "data/layouts/layouts.json").read_text())["layouts"]
                   if "id" in entry}
        layout = layouts[map_data["layout"]]
        self.width = layout["width"]
        self.blocks = (engine / layout["blockdata_filepath"]).read_bytes()
        headers = (engine / "src/data/tilesets/headers.h").read_text()
        metatiles = (engine / "src/data/tilesets/metatiles.h").read_text()

        def attributes(tileset):
            body = re.search(r"const struct Tileset %s\s*=\s*\{(.*?)\};" % re.escape(tileset), headers, re.S).group(1)
            symbol = re.search(r"\.metatileAttributes\s*=\s*(\w+)", body).group(1)
            path = re.search(r"%s\[\]\s*=\s*INCBIN_U16\(\"([^\"]+)\"\)" % re.escape(symbol), metatiles).group(1)
            raw = (engine / path).read_bytes()
            return struct.unpack("<%dH" % (len(raw) // 2), raw)

        self.primary = attributes(layout["primary_tileset"])
        self.secondary = attributes(layout["secondary_tileset"])
        names = re.findall(r"^\s*(MB_[A-Z0-9_]+)", (engine / "include/constants/metatile_behaviors.h").read_text(), re.M)
        self.names = {index: name for index, name in enumerate(names)}

    def at(self, x, y):
        block = struct.unpack_from("<H", self.blocks, (y * self.width + x) * 2)[0] & 0x3FF
        table = self.primary if block < NUM_METATILES_IN_PRIMARY else self.secondary
        index = block if block < NUM_METATILES_IN_PRIMARY else block - NUM_METATILES_IN_PRIMARY
        return self.names.get(table[index] & 0xFF, "MB_UNKNOWN")


def environment(behaviour, map_type):
    """BattleSetup_GetEnvironmentId for the cases a rival scene can stand on."""
    if behaviour in ("MB_TALL_GRASS", "MB_CYCLING_ROAD_PULL_DOWN_GRASS"):
        return "BATTLE_ENVIRONMENT_GRASS"
    if behaviour == "MB_LONG_GRASS":
        return "BATTLE_ENVIRONMENT_LONG_GRASS"
    if behaviour in ("MB_SAND", "MB_DEEP_SAND"):
        return "BATTLE_ENVIRONMENT_SAND"
    if map_type in ("MAP_TYPE_INDOOR", "MAP_TYPE_SECRET_BASE"):
        return "BATTLE_ENVIRONMENT_BUILDING"
    if map_type not in ("MAP_TYPE_TOWN", "MAP_TYPE_CITY", "MAP_TYPE_ROUTE"):
        return "UNSUPPORTED_MAP_TYPE"
    if behaviour in ("MB_OCEAN_WATER", "MB_INTERIOR_DEEP_WATER", "MB_DEEP_WATER"):
        return "BATTLE_ENVIRONMENT_WATER"
    if behaviour in ("MB_POND_WATER", "MB_SEMI_DEEP_WATER", "MB_SOOTOPOLIS_DEEP_WATER", "MB_WATERFALL",
                     "MB_NO_SURFACING", "MB_EASTWARD_CURRENT", "MB_WESTWARD_CURRENT",
                     "MB_NORTHWARD_CURRENT", "MB_SOUTHWARD_CURRENT"):
        return "BATTLE_ENVIRONMENT_POND"
    if behaviour == "MB_MOUNTAIN_TOP":
        return "BATTLE_ENVIRONMENT_MOUNTAIN"
    return "BATTLE_ENVIRONMENT_PLAIN"


def check(engine):
    engine = Path(engine).resolve()
    problems, report = [], []
    ids, folders = _map_folders(engine)
    names = _constants(engine)

    def known(text):
        for name in re.findall(r"\b((?:FLAG|VAR|TRAINER|ITEM|HEAL_LOCATION)_[A-Z0-9_]+)\b", text):
            if name not in names:
                problems.append(f"unknown constant {name}")

    for checkpoint in CHECKPOINTS:
        environments = set()
        for trigger in checkpoint.triggers:
            if ids.get(trigger.map) != trigger.map_id:
                problems.append(f"{checkpoint.checkpoint_id}: {trigger.map} is {ids.get(trigger.map)}, catalogue says {trigger.map_id}")
                continue
            data = json.loads((engine / "data/maps" / folders[trigger.map] / "map.json").read_text())
            behaviour = _Behaviour(engine, data)
            if trigger.kind == "coord":
                var, value = re.match(r"(VAR_\w+) == (\d+)", trigger.condition).groups()
                events = {(event["x"], event["y"]) for event in data.get("coord_events", [])
                          if event.get("type") == "trigger" and event.get("var") == var
                          and str(event.get("var_value")) == value
                          and event.get("script", "").startswith(trigger.script.split("..")[0].rstrip("0123456789"))}
                missing = set(trigger.tiles) - events
                if missing:
                    problems.append(f"{checkpoint.checkpoint_id}: no {var}=={value} trigger at {sorted(missing)}")
                stand = trigger.tiles
            else:
                objects = [(o["x"], o["y"]) for o in data.get("object_events", []) if o.get("script") == trigger.script]
                if list(trigger.tiles) != objects:
                    problems.append(f"{checkpoint.checkpoint_id}: rival object {trigger.script} at {objects}, catalogue says {trigger.tiles}")
                stand = tuple((x + dx, y + dy) for x, y in trigger.tiles for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)))
            for x, y in stand:
                environments.add(environment(behaviour.at(x, y), data["map_type"]))
        for trainer in checkpoint.trainers:
            if trainer not in names:
                problems.append(f"{checkpoint.checkpoint_id}: unknown trainer {trainer}")
        for text in checkpoint.prerequisites + checkpoint.cleared_when + checkpoint.completion_effects + checkpoint.personal_rewards:
            known(text.replace("<RIVAL>S_HOUSE", "BRENDANS_HOUSE"))
        if environments != set(checkpoint.battle_environments) or checkpoint.canonical_environment not in environments:
            problems.append(f"{checkpoint.checkpoint_id}: original NPC battle environment(s) {sorted(environments)}, "
                            f"catalogue says {sorted(checkpoint.battle_environments)} / {checkpoint.canonical_environment}")
        report.append(dict(checkpoint=checkpoint.checkpoint_id, maps=sorted(checkpoint.maps),
                           environments=sorted(environments)))
    battle_h = (engine / "include/constants/battle.h").read_text()
    body = re.search(r"enum BattleEnvironments\s*\{(.*?)\}", battle_h, re.S)
    order = re.findall(r"^\s*(BATTLE_ENVIRONMENT_[A-Z0-9_]+)\s*,", body.group(1), re.M) if body else []
    for name, index in ENVIRONMENT_IDS.items():
        if name not in order or order.index(name) != index:
            problems.append(f"{name} is enum index {order.index(name) if name in order else None}, catalogue says {index}")
    port = engine / "include/constants/multiplayer_rival.h"
    if port.exists():
        text = port.read_text()
        tag = re.search(r"#define MP_RIVAL_PREP_TAG\s+(0x[0-9A-Fa-f]+)", text)
        if not tag or int(tag.group(1), 16) != PREPARATION_TAG:
            problems.append("the engine's MP_RIVAL_PREP_TAG differs from rival_catalogue.PREPARATION_TAG")
        macro = {"route103": "ROUTE103", "rustboro": "RUSTBORO", "route110": "ROUTE110", "route119": "ROUTE119", "lilycove": "LILYCOVE"}
        for checkpoint in CHECKPOINTS:
            number = re.search(r"#define MP_RIVAL_%s\s+(\d+)" % macro[checkpoint.checkpoint_id], text)
            if not number or int(number.group(1)) != checkpoint.order - 1:
                problems.append(f"{checkpoint.checkpoint_id}: engine checkpoint number differs from the story order")
            for trigger in checkpoint.triggers:
                script = (engine / "data/maps" / folders[trigger.map] / "scripts.inc").read_text()
                blocks = dict(re.findall(r"^(\w+)::\n(.*?)(?=^\w+::|\Z)", script, re.M | re.S))
                stem = trigger.script.split("..")[0]
                entries = [label for label in blocks if label == stem
                           or (stem[-1].isdigit() and re.fullmatch(re.escape(stem.rstrip("0123456789")) + r"\d+", label))]
                for label in entries or [stem]:
                    # the check sits in the entry point or in the scene it goes to first
                    seen, block = label, blocks.get(label, "")
                    jump = re.search(r"^\tgoto (\w+)", block, re.M)
                    reached = block + (blocks.get(jump.group(1), "") if jump else "")
                    if "MP_RIVAL_%s" % macro[checkpoint.checkpoint_id] not in reached:
                        problems.append(f"{checkpoint.checkpoint_id}: {seen} does not ask the multiplayer layer first")
    if INTRO_TABLE.exists():
        table = json.loads(INTRO_TABLE.read_text())
        for section in ("set_flags", "set_flags_male_player", "set_flags_female_player", "clear_flags",
                        "vars", "items", "respawn", "must_not_be_set"):
            for entry in table.get(section, []):
                known(entry["name"] if type(entry) is dict else entry)
    return problems, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--engine", required=True, help="engine or pokeemerald-expansion checkout")
    parser.add_argument("--json", action="store_true", help="print the per-checkpoint report as JSON")
    args = parser.parse_args(argv)
    problems, report = check(args.engine)
    if args.json:
        print(json.dumps(dict(problems=problems, checkpoints=report), indent=2))
    else:
        for row in report:
            print(f"{row['checkpoint']:10} maps={row['maps']} original background={','.join(row['environments'])}")
        for problem in problems:
            print("PROBLEM:", problem)
        print("rival catalogue:", "OK" if not problems else f"{len(problems)} problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
