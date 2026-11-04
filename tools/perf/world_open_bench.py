#!/usr/bin/env python3
"""World loading on this PC (KNOWN_ISSUES MS-161): how long a host's start takes to open a world and check it as its
saves pile up.

A test world of two players with N distinct saves each is built through the checkpoint store's own API (enrollment, an
instance range, then one checkpoint after another) from synthetic saves (the tests' ownership builders: no real save,
no ROM), in a temporary folder that is removed afterwards. Then a cold open and integrity check, as a host's start runs
them (a new store, its caches empty), is timed --repeat times. Prints one JSON object; with --max-seconds it fails when
the slowest check takes longer (a guard against the check growing far beyond MS-161's measurements, not a target).

    python tools/perf/world_open_bench.py --saves 300 --repeat 3 [--out result.json]
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]      # the app and the tests' save builders, on any OS
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE  # noqa: E402
from emerald_multiplayer.trade_storage import TradeCheckpointStore  # noqa: E402
from test_ownership_storage import owned_flash, source_flash  # noqa: E402

BUILD, RULESET = "ownership-test-ROM-sha256", "baseline-test-rules-v1"


def build_world(path: Path, saves: int, players: int = 2) -> dict:
    """The world: `players` enrolled players, each with `saves` checkpoints, each save distinct (its save counter)."""
    started = time.perf_counter()
    store = TradeCheckpointStore(path, BUILD, RULESET, OWNERSHIP_PROFILE)
    try:
        store.begin_server_boot()
        for index in range(players):
            identity = store.create_player(f"Bench {index + 1}")
            lease = store.acquire_lease(identity.player_id, identity.credential)
            store.enroll_player(identity.player_id, source_flash(personalities=(7 + 100 * index,)))
            grant = store.reserve_instances(identity.player_id, lease, str(uuid.uuid4()), 0, 1, 32)
            for revision in range(saves):
                payload = owned_flash(grant, personalities=(7 + 100 * index,), counter=2 + revision)
                store.commit_checkpoint(identity.player_id, lease, str(uuid.uuid4()), revision, payload, BUILD,
                                        RULESET, OWNERSHIP_PROFILE)
    finally:
        store.close()
    return dict(players=players, saves_per_player=saves, checkpoints=players * saves,
                build_seconds=round(time.perf_counter() - started, 2), database_bytes=path.stat().st_size)


def cold_checks(path: Path, repeat: int) -> list[float]:
    times = []
    for _ in range(repeat):
        started = time.perf_counter()
        store = TradeCheckpointStore(path, BUILD, RULESET, OWNERSHIP_PROFILE)
        try:
            store.integrity_check()
        finally:
            store.close()
        times.append(round(time.perf_counter() - started, 3))
    return times


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--saves", type=int, default=300, help="checkpoints for each of the two players")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--max-seconds", type=float, help="fail when the slowest cold check takes longer")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="world-open-bench-") as folder:
        path = Path(folder) / "world.sqlite3"
        world = build_world(path, args.saves)
        checks = cold_checks(path, args.repeat)
    result = dict(world, cold_checks_seconds=checks, slowest=max(checks),
                  ms_per_checkpoint=round(1000 * min(checks) / world["checkpoints"], 2),
                  platform=sys.platform, machine=platform.machine(), python=platform.python_version(),
                  cpus=os.cpu_count())
    text = json.dumps(result)
    print(text)
    if args.out:
        args.out.write_text(text + "\n")
    if args.max_seconds is not None and result["slowest"] > args.max_seconds:
        print(f"the slowest cold check took {result['slowest']} s, over {args.max_seconds} s", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
