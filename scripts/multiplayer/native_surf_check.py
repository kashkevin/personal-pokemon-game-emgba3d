"""Another player surfing on their own Pokemon as this game draws it (the relay of the real carriers, 2026-10-27), end
to end: a real world server, real companions and two game processes of an engine **test build**
(`make -f Makefile_pc NATIVE_LINUX=1 BFX_TEST=1`, 2D `pokeemerald-mp-bfxtest` or 3D `pokeemerald-mp-diorama-bfxtest`),
whose battle-environment driver sets the party, starts both games on Route 109's beach and presses keys and takes
pictures on exact game frames.

Player A (client 0) walks two tiles up the beach and turns to face the sea. Player B (client 1), with a shiny Lapras
that knows Surf, faces the sea, uses Surf (the field's prompt answered YES), swims two tiles south, two west and back
east. A takes a picture every 6 frames from frame 1000 (OUT/client-0/shot-50.png ...; frame = 1000 + 6 * (n - 50)):
B on their shiny Lapras, turning and swimming. The pictures are to be looked at; the script checks what the network
carried:

  1. both games run to their end (exit 0);
  2. B publishes its carrier (mount state 2, Lapras, the shiny flag) and A's game receives it within a second;
  3. A's pictures were all taken.

    PYTHONPATH=src python scripts/multiplayer/native_surf_check.py \\
        --game ../engine/pokeemerald-mp-bfxtest --rom ../engine/pokeemerald.gba --manifest manifest.json \\
        --save route101.sav --display :94 --display :95 --output /private/multiplayer-proof/native-surf-1
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
from emerald_multiplayer.world_mailbox import FOLLOWER_SHINY, MOUNT_CARRIER

ROUTE_109 = "0:24:0:20:24"                      # the beach, the sea south of it
FRAMES = 1600
LAPRAS = 131
A_KEYS = ",".join([
    "600:UP", "612:UP", "624:UP",               # turn north, two tiles up the beach
    "700:DOWN",                                 # turn to face the sea
])
B_KEYS = ",".join([
    "750:DOWN",                                 # face the sea
    "800:A", "860:A", "920:A", "980:A", "1040:A",   # the water's text, use Surf? YES, Lapras used Surf
    "1160:DOWN", "1172:DOWN",                   # swimming two tiles south
    "1260:LEFT", "1272:LEFT", "1284:LEFT",      # turn west, two tiles
    "1360:RIGHT", "1372:RIGHT", "1384:RIGHT",   # turn east, back
])
A_SHOTS = ",".join(str(f) for f in range(1000, 1460, 6))
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
    evidence = dict(scope="another player surfing on their own Pokemon: a real world server, real companions, two "
                          "test-build clients", species=LAPRAS, checks=[], passed=False)

    def record(name: str, **fields) -> None:
        evidence["checks"].append(dict(verified=name, **fields))
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps(evidence["checks"][-1]), flush=True)

    try:
        for i, display in enumerate(args.display):
            copy = root / f"client-{i}.sav"
            shutil.copyfile(args.save, copy)
            companion = Companion(CompanionConfig(args.rom, args.manifest, str(uuid4()), f"Surfer {'AB'[i]}",
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
                               PKMN_TEST_BATTLE_DELAY="100", PKMN_TEST_PARTY=f"{LAPRAS}:40:{'s' if i == 1 else ''}v57",
                               PKMN_TEST_WARP=ROUTE_109, PKMN_TEST_BADGES="8", PKMN_TEST_OWE_NO_BATTLE="1",
                               PKMN_TEST_LOG=str(rundir / "test.log"),
                               PKMN_TEST_MEGA_SHOT_STEM=str(rundir / "shot"),
                               PKMN_TEST_FIELD_KEYS=B_KEYS if i == 1 else A_KEYS,
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
                                                   published.mount_flags, published.follower_flags),
                   None if received is None else (received.mount_state, received.mount_species,
                                                  received.mount_flags, received.follower_flags))
            if row != last:
                timeline.append(dict(t=round(time.monotonic() - started, 3), b_published=row[0], a_receives=row[1]))
                last = row
            await asyncio.sleep(.02)
        (root / "timeline.json").write_text(json.dumps(timeline, indent=1) + "\n")
        exits = [p.poll() for p in processes]
        if exits != [0, 0]:
            raise AssertionError(f"the games did not both run to their end: {exits}")
        record("both games ran to their end", exits=exits)
        # a record a game's bridge refuses ends its session without stopping the game (the first run of this check:
        # the bridge still refused mount state 2), so each game's own log is read too
        for i in range(2):
            text = (root / f"client-{i}.log").read_text(errors="replace")
            if "bridge disconnected" in text:
                raise AssertionError(f"client {i}'s bridge disconnected: "
                                     f"{text[text.index('bridge disconnected'):].splitlines()[0]}")
        record("both games stayed connected to their companions")
        surfed = next((r["t"] for r in timeline if r["b_published"] and r["b_published"][0] == MOUNT_CARRIER), None)
        seen = next((r for r in timeline if r["a_receives"] and r["a_receives"][0] == MOUNT_CARRIER), None)
        if surfed is None or seen is None or seen["t"] - surfed > 1.0:
            raise AssertionError(f"the carrier: published at {surfed}, received {seen}")
        if seen["a_receives"][1] != LAPRAS or not seen["a_receives"][2] & FOLLOWER_SHINY:
            raise AssertionError(f"the carrier received as {seen['a_receives']}, not a shiny Lapras")
        record("B's carrier reached A's game", published=surfed, received=seen["t"], state=seen["a_receives"])
        pictures = sorted(p.name for p in (root / "client-0").glob("shot-*.png"))
        if len(pictures) != len(A_SHOTS.split(",")):
            raise AssertionError(f"{len(pictures)} of {len(A_SHOTS.split(','))} pictures")
        record("A's pictures of B", count=len(pictures), folder=str(root / "client-0"),
               frames="frame = 1000 + 6 * (n - 50) for shot-n.png")
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
    parser.add_argument("--save", type=Path, required=True, help="a test save (both games start on Route 109)")
    parser.add_argument("--display", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0, help="stretch the time limit (3D on software OpenGL: 2)")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
