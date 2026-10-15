#!/usr/bin/env python3
"""Write a representative shared-world database with the code of an OLD checkout (Update 23, docs/save-compatibility.md).

Run it with PYTHONPATH pointing at the old tree's src:

    git worktree add /tmp/old e2a40d7          # Update 14, before Updates 15-20
    PYTHONPATH=/tmp/old/src python3 tools/compat/make_shared_world_fixture.py tests/fixtures/compat/shared_world_u14

It uses only calls that exist in both trees. The result is data, not a save: no ROM, no player save. tests/test_save_compat.py
copies it to a temporary folder before opening it with the current code, so the committed file is never modified.
"""
import json
import random
import sys
from pathlib import Path

from emerald_multiplayer.shared_world import SharedWorld

WORLD = "11111111-1111-4111-8111-111111111111"
CATALOGUE = {
    "rare": [{"name": "ABSOL", "species": 359, "types": ["dark"]}],
    "legendary": [{"name": "GROUDON", "species": 383, "types": ["ground"]}],
    "mega": [{"name": "VENUSAUR", "species": 3, "types": ["grass"], "mega": True, "held_item": 576}],
    "mythical": [], "mega_legendary": [],
}
LOCATIONS = [{"name": "ROUTE 101", "map_group": 0, "map_number": 16, "x": 10, "y": 7, "min_level": 0, "themes": ["normal"]}]
PLAYERS = ["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "cccccccc-cccc-4ccc-8ccc-cccccccccccc"]


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    path = out / "world.sqlite3.shared-world.sqlite3"
    if path.exists():
        path.unlink()
    clock = Clock()
    world = SharedWorld(path, WORLD, clock=clock, rng=random.Random(5), event_catalogue=CATALOGUE, locations=LOCATIONS,
                        event_condition_chance=0.0)
    a, b, c = PLAYERS
    world.set_active_players(3)
    for number, (category, catcher) in enumerate((("rare", a), ("legendary", b)), 1):
        event = world.spawn_event(progression_level=30, category=category)["event_id"]
        world.claim_event(catcher, event)
        world.event_result(catcher, event, "caught", f"TRAINER{number}")
    event = world.spawn_event(progression_level=30, category="mega")["event_id"]  # still on, claimed by a, not caught
    world.claim_event(a, event)
    world.close()
    (out / "README.txt").write_text(
        "Written by tools/compat/make_shared_world_fixture.py with the code of the checkout named in the folder.\n"
        "Two events caught (a rare by A, a legendary by B) and one claimed but not caught (a mega by A).\n"
        "Data only: no ROM, no save.\n")
    print("wrote", path, json.dumps({"events": 3}))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
