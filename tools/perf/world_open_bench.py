#!/usr/bin/env python3
"""World loading on this PC (KNOWN_ISSUES MS-161): how long a host's start takes to open a world and check it as its
saves pile up.

A test world of two players with N distinct saves each is built through the checkpoint store's own API (enrollment, an
instance range, then one checkpoint after another) from synthetic saves (the tests' ownership builders: no real save,
no ROM), in a temporary folder that is removed afterwards. Then, --repeat times, a cold open and integrity check as a
host's start runs them (a new store, its remembered save readings deleted first: every save is read) and a warm one (a
new store, the readings the cold open remembered: save_readings.py, MS-161's option (b)). --no-cache opens without the
remembered readings (every open reads every save, as before option (b)); --handler-history gives the world what a new
world of a replay-capable game gets (character transfers, handler history and native trade effects), whose check also
replays the handler history from every save. Prints one JSON object; with --max-seconds it fails when the slowest cold
check takes longer (a guard against the check growing far beyond MS-161's measurements, not a target).

    python tools/perf/world_open_bench.py --saves 300 --repeat 3 [--handler-history] [--no-cache] [--out result.json]
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
from emerald_multiplayer.save_readings import SUFFIX  # noqa: E402
from emerald_multiplayer.trade_storage import TradeCheckpointStore  # noqa: E402
from test_ownership_storage import owned_flash, source_flash  # noqa: E402

BUILD, RULESET = "ownership-test-ROM-sha256", "baseline-test-rules-v1"
POLICY = "gen6-stable-world-region-v1"


def build_world(path: Path, saves: int, players: int = 2, *, handler_history: bool = False) -> dict:
    """The world: `players` enrolled players, each with `saves` checkpoints, each save distinct (its save counter)."""
    started = time.perf_counter()
    store = TradeCheckpointStore(path, BUILD, RULESET, OWNERSHIP_PROFILE)
    try:
        if handler_history:
            from emerald_multiplayer.character_transfers import enable_character_transfers
            from emerald_multiplayer.trade_effect_storage import enable_trade_effects
            from emerald_multiplayer.trade_friendship_migration import enable_friendship_history
            enable_character_transfers(store, path.with_name("before-character-transfers.sqlite3"))
            enable_friendship_history(store, path.with_name("before-handler-history.sqlite3"))
            enable_trade_effects(store, path.with_name("before-native-trade-effects.sqlite3"), policy_id=POLICY)
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
    return dict(players=players, saves_per_player=saves, checkpoints=players * saves, handler_history=handler_history,
                build_seconds=round(time.perf_counter() - started, 2), database_bytes=path.stat().st_size)


def timed_open(path: Path, cache: bool) -> float:
    started = time.perf_counter()
    store = TradeCheckpointStore(path, BUILD, RULESET, OWNERSHIP_PROFILE, save_readings=cache)
    try:
        store.integrity_check()
    finally:
        store.close()
    return round(time.perf_counter() - started, 3)


def checks(path: Path, repeat: int, cache: bool) -> tuple[list[float], list[float]]:
    """(cold, warm) seconds: each cold open after the remembered readings were deleted, each warm one right after it."""
    readings = path.with_name(path.name + SUFFIX)
    cold, warm = [], []
    for _ in range(repeat):
        readings.unlink(missing_ok=True)
        cold.append(timed_open(path, cache))
        warm.append(timed_open(path, cache))
    return cold, warm


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--saves", type=int, default=300, help="checkpoints for each of the two players")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--max-seconds", type=float, help="fail when the slowest cold check takes longer")
    parser.add_argument("--handler-history", action="store_true",
                        help="a world with character transfers, handler history and trade effects, as a new world gets")
    parser.add_argument("--no-cache", action="store_true", help="open without the remembered save readings")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="world-open-bench-") as folder:
        path = Path(folder) / "world.sqlite3"
        world = build_world(path, args.saves, handler_history=args.handler_history)
        cold, warm = checks(path, args.repeat, not args.no_cache)
        readings = path.with_name(path.name + SUFFIX)
        cache_bytes = readings.stat().st_size if readings.exists() else 0
    result = dict(world, cache=not args.no_cache, cache_bytes=cache_bytes,
                  cold_checks_seconds=cold, slowest=max(cold),
                  ms_per_checkpoint=round(1000 * min(cold) / world["checkpoints"], 2),
                  warm_checks_seconds=warm, warm_slowest=max(warm),
                  warm_ms_per_checkpoint=round(1000 * min(warm) / world["checkpoints"], 2),
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
