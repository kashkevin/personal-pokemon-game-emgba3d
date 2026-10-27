"""Another player's riding as this game draws it (the riding fixes of 2026-10-27), end to end: a real world server,
real companions and two game processes of an engine **test build** (`make -f Makefile_pc NATIVE_LINUX=1 BFX_TEST=1`,
2D `pokeemerald-mp-bfxtest` or 3D `pokeemerald-mp-diorama-bfxtest`), whose battle-environment driver sets the party,
starts both games on Route 101 and presses keys and takes pictures on exact game frames.

Player B (client 1) steps north of player A, mounts its lead with R (its follower walks under it, it hops on), rides
two tiles west and back, dismounts with R and walks on. Player A (client 0) stands still and takes 128 pictures of B,
one every 4 frames from frame 880 (OUT/client-0/shot-50.png ... shot-177.png; frame = 880 + 4 * (n - 50)): B's
Pokemon walking under B, B's seat rising, B seated while standing and while riding, B's hop off with B in front of
its Pokemon stepping back. The pictures are to be looked at; the script checks what the network carried:

  1. both games run to their end (exit 0);
  2. B publishes riding, then on foot (its mount state), and A's game receives each within a second;
  3. A's pictures were all taken.

The driver sets the party after the field is up, so until the first ride B's follower is still the save's old lead
(it turns into the mount when B mounts); with a save whose lead is rideable the two are the same Pokemon, as in play.

    PYTHONPATH=src python scripts/multiplayer/native_ride_check.py \\
        --game ../engine/pokeemerald-mp-bfxtest --rom ../engine/pokeemerald.gba --manifest manifest.json \\
        --save route101.sav --display :94 --display :95 --output /private/multiplayer-proof/native-ride-1
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import time
from uuid import uuid4

from emerald_multiplayer.companion import Companion, CompanionConfig
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.world_mailbox import MOUNT_RIDING

ROUTE_101 = "0:16:0:10:11"
FRAMES = 1700
B_KEYS = ",".join([
    "700:UP", "720:UP",                 # north of A (its follower trails between them)
    "900:R",                            # hop on: its follower walks under it
    "1000:LEFT", "1020:LEFT",           # riding west two tiles
    "1060:RIGHT", "1080:RIGHT",         # back east
    "1160:R",                           # hop off: its Pokemon steps back west
    "1400:UP",                          # on foot: its follower follows
])
A_SHOTS = ",".join(str(f) for f in range(880, 1392, 4))
CONFIG = "borderBackground=0\nbackgroundOrder=2\nfullscreen=0\nwindowScale=2\nintegerScale=0\nvsync=0\nborder=1\n" \
         "volume=0\ncryVolume=0\n"


async def run(args: argparse.Namespace) -> None:
    root = args.output.resolve()
    if "/multiplayer-proof/" not in str(root) + "/" or root.exists():
        raise ValueError("choose a new private multiplayer-proof output directory")
    if len(args.display) != 2:
        raise ValueError("two X displays, one per client")
    root.mkdir(mode=0o700, parents=True)
    manifest = json.loads(args.manifest.read_text())
    server = WorldServer(ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"], heartbeat_interval=.2,
                                      idle_timeout=12), store=None)
    await server.start(port=0)
    companions: list[Companion] = []
    processes: list[subprocess.Popen] = []
    timeline: list[dict] = []
    evidence = dict(scope="another player's riding: a real world server, real companions, two test-build clients",
                    species=args.species, checks=[], passed=False)

    def record(name: str, **fields) -> None:
        evidence["checks"].append(dict(verified=name, **fields))
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps(evidence["checks"][-1]), flush=True)

    try:
        for i, display in enumerate(args.display):
            copy = root / f"client-{i}.sav"
            shutil.copyfile(args.save, copy)
            companion = Companion(CompanionConfig(args.rom, args.manifest, str(uuid4()), f"Rider {'AB'[i]}",
                                                  secrets.token_bytes(32), server_port=server.address[1], ipc_port=0))
            await companion.start()
            companions.append(companion)
            bridge = root / f"bridge-{i}.txt"
            bridge.write_text(f"port={companion.ipc_address[1]}\ntoken={companion.config.token.hex()}\n")
            bridge.chmod(0o600)
            rundir = root / f"client-{i}"
            rundir.mkdir()
            (rundir / "pokeemerald.cfg").write_text(CONFIG)
            environment = dict(os.environ, DISPLAY=display, SDL_AUDIODRIVER="dummy", PKMN_NOSCENE="1",
                               PKMN_TEST_EXIT="1", PKMN_TEST_BATTLE=f"field:{FRAMES}", PKMN_TEST_AUTOPILOT="1",
                               PKMN_TEST_BATTLE_DELAY="100", PKMN_TEST_PARTY=f"{args.species}:30",
                               PKMN_TEST_WARP=ROUTE_101, PKMN_TEST_OWE_NO_BATTLE="1",
                               PKMN_TEST_LOG=str(rundir / "test.log"),
                               PKMN_TEST_MEGA_SHOT_STEM=str(rundir / "shot"),
                               PKMN_TEST_FIELD_KEYS=B_KEYS if i == 1 else "",
                               PKMN_TEST_FIELD_SHOTS=A_SHOTS if i == 0 else "")
            log = (root / f"client-{i}.log").open("wb")
            processes.append(subprocess.Popen([str(args.game), "--save", str(copy), "--bridge", str(bridge)],
                                              cwd=rundir, env=environment, stdout=log, stderr=subprocess.STDOUT))
            await asyncio.sleep(1.2)    # the game seeds its random numbers from the clock's seconds
        started, last = time.monotonic(), None
        while any(p.poll() is None for p in processes) and time.monotonic() - started < FRAMES / 60 * args.slow + 200:
            published = companions[1]._local_world
            received = None
            for _, state in companions[0].world_inbound().peers:
                received = state
            row = (None if published is None else (published.mount_state, published.mount_species,
                                                   published.follower_species, published.follower_flags),
                   None if received is None else (received.mount_state, received.mount_species,
                                                  received.follower_species, received.follower_flags))
            if row != last:
                timeline.append(dict(t=round(time.monotonic() - started, 3), b_published=row[0], a_receives=row[1]))
                last = row
            await asyncio.sleep(.02)
        (root / "timeline.json").write_text(json.dumps(timeline, indent=1) + "\n")
        exits = [p.poll() for p in processes]
        if exits != [0, 0]:
            raise AssertionError(f"the games did not both run to their end: {exits}")
        record("both games ran to their end", exits=exits)
        mounted = next((r["t"] for r in timeline if r["b_published"] and r["b_published"][0] == MOUNT_RIDING), None)
        seen = next((r["t"] for r in timeline if r["a_receives"] and r["a_receives"][0] == MOUNT_RIDING), None)
        if mounted is None or seen is None or seen - mounted > 1.0:
            raise AssertionError(f"riding: published at {mounted}, received at {seen}")
        off = next((r["t"] for r in timeline if r["t"] > mounted and r["b_published"]
                    and r["b_published"][0] != MOUNT_RIDING), None)
        off_seen = next((r["t"] for r in timeline if off is not None and r["t"] >= off and r["a_receives"]
                         and r["a_receives"][0] != MOUNT_RIDING), None)
        if off is None or off_seen is None or off_seen - off > 1.0:
            raise AssertionError(f"on foot again: published at {off}, received at {off_seen}")
        record("B's mount state reached A's game", riding_published=mounted, riding_received=seen,
               on_foot_published=off, on_foot_received=off_seen)
        pictures = sorted(p.name for p in (root / "client-0").glob("shot-*.png"))
        if len(pictures) != len(A_SHOTS.split(",")):
            raise AssertionError(f"{len(pictures)} of {len(A_SHOTS.split(','))} pictures")
        record("A's pictures of B", count=len(pictures), folder=str(root / "client-0"),
               frames="frame = 880 + 4 * (n - 50) for shot-n.png")
        evidence["passed"] = True
        record("passed")
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()
        for companion in companions:
            await companion.close()
        await server.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True, help="engine test build (BFX_TEST=1) with the bridge")
    parser.add_argument("--rom", type=Path, required=True, help="GBA ROM of the same engine commit")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--save", type=Path, required=True, help="a test save (both games start on Route 101)")
    parser.add_argument("--display", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--species", type=int, default=59, help="the rideable lead both players get (59 Arcanine)")
    parser.add_argument("--slow", type=float, default=1.0, help="stretch the time limit (3D on software OpenGL: 2)")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
