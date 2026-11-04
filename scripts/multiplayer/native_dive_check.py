"""Another player under the water (after Dive) as this game draws them (KNOWN_ISSUES MS-181), end to end: a real world
server, real companions and two game processes of an engine **test build** (`make -f Makefile_pc NATIVE_LINUX=1
BFX_TEST=1`, 2D `pokeemerald-mp-bfxtest` or 3D `pokeemerald-mp-diorama-bfxtest`), whose battle-environment driver starts
both games under the water of Route 124 (a map the game always enters diving), presses keys and takes pictures on exact
game frames.

Player A (client 0) faces east. Player B (client 1), four tiles east of A, swims two tiles east, one south, back west
and north, then opens the START menu and closes it. A takes a picture every 6 frames from frame 900 (OUT/client-0/
shot-50.png ...; frame = 900 + 6 * (n - 50)): B under the water, swimming, and standing in their menu. The pictures are
to be looked at; the script checks what the network carried:

  1. both games run to their end (exit 0) and stay connected to their companions;
  2. B publishes its presence under the water as the movement "dive" on the field ("overworld"), and in its START menu
     as "dive" in a "menu" - never "walk" while drawn (the record before MS-181's fix said "unavailable" on the field,
     and "walk" in a menu, which every other game drew standing as on land);
  3. A's companion receives B's presence as "dive" and gives A's game the underwater movement (the mailbox's mode 4),
     drawn, on the field and in the menu alike;
  4. A's pictures were all taken.

    PYTHONPATH=src python scripts/multiplayer/native_dive_check.py \\
        --game ../engine/pokeemerald-mp-bfxtest --rom ../engine/pokeemerald.gba --manifest manifest.json \\
        --save route101.sav --display :94 --display :95 --output /private/multiplayer-proof/native-dive-1
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

UNDERWATER_ROUTE_124 = (0, 50)
A_AT, B_AT = (38, 16), (42, 16)                 # an open stretch of the sea floor (rows 16-18, x 36-50)
FRAMES = 1500
LAPRAS = 131
A_KEYS = ",".join(["600:RIGHT"])                # face east, toward B
B_KEYS = ",".join([
    "700:RIGHT", "712:RIGHT", "724:RIGHT",      # turn east, two tiles
    "800:DOWN", "812:DOWN",                     # one tile south
    "900:LEFT", "912:LEFT", "924:LEFT",         # turn west, two tiles
    "1000:UP", "1012:UP",                       # one tile north, back where B began
    "1100:START", "1250:B",                     # the START menu open for a while, closed
])
A_SHOTS = ",".join(str(f) for f in range(900, 1360, 6))
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
    evidence = dict(scope="another player under the water: a real world server, real companions, two test-build clients",
                    checks=[], passed=False)

    def record(name: str, **fields) -> None:
        evidence["checks"].append(dict(verified=name, **fields))
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps(evidence["checks"][-1]), flush=True)

    try:
        for i, display in enumerate(args.display):
            copy = root / f"client-{i}.sav"
            shutil.copyfile(args.save, copy)
            companion = Companion(CompanionConfig(args.rom, args.manifest, str(uuid4()), f"Diver {'AB'[i]}",
                                                  secrets.token_bytes(32), server_port=server.address[1], ipc_port=0))
            await companion.start()
            companions.append(companion)
            bridge = root / f"bridge-{i}.txt"
            bridge.write_text(f"port={companion.ipc_address[1]}\ntoken={companion.config.token.hex()}\n")
            bridge.chmod(0o600)
            rundir = root / f"client-{i}"
            rundir.mkdir()
            (rundir / "pokeemerald.cfg").write_text(CONFIG)
            x, y = A_AT if i == 0 else B_AT
            environment = dict(os.environ, DISPLAY=display, SDL_AUDIODRIVER="dummy", PKMN_NOSCENE="1",
                               PKMN_TEST_EXIT="1", PKMN_TEST_BATTLE=f"field:{FRAMES}", PKMN_TEST_AUTOPILOT="1",
                               PKMN_TEST_BATTLE_DELAY="100", PKMN_TEST_PARTY=f"{LAPRAS}:40:v57",
                               PKMN_TEST_WARP=f"{UNDERWATER_ROUTE_124[0]}:{UNDERWATER_ROUTE_124[1]}:-1:{x}:{y}",
                               PKMN_TEST_BADGES="8", PKMN_TEST_OWE_NO_BATTLE="1",
                               PKMN_TEST_LOG=str(rundir / "test.log"),
                               PKMN_TEST_MEGA_SHOT_STEM=str(rundir / "shot"),
                               PKMN_TEST_FIELD_KEYS=B_KEYS if i == 1 else A_KEYS,
                               PKMN_TEST_FIELD_SHOTS=A_SHOTS if i == 0 else "")
            log = (root / f"client-{i}.log").open("wb")
            processes.append(subprocess.Popen([str(args.game), "--save", str(copy), "--bridge", str(bridge)],
                                              cwd=rundir, env=environment, stdout=log, stderr=subprocess.STDOUT))
            await asyncio.sleep(1.2)    # the game seeds its random numbers from the clock's seconds
        b_id = companions[1].config.player_id
        started, last = time.monotonic(), None
        while any(p.poll() is None for p in processes) and time.monotonic() - started < FRAMES / 60 * args.slow + 200:
            pose = companions[1]._local_pose
            published = None if pose is None else pose.network_fields(True)
            seen = next((player.get("presence") for player in companions[0]._players
                         if player.get("player_id") == b_id), None)
            # what A's companion writes into A's game for B: (mailbox movement mode, drawn on the field)
            peer_modes = sorted((peer.pose.movement_mode, peer.pose.activity) for peer in companions[0].snapshot.peers)
            row = (None if published is None else (published["movement_mode"], published["activity"],
                                                   published["map_group"], published["map_number"],
                                                   published["x"], published["y"]),
                   None if seen is None else (seen["movement_mode"], seen["activity"], seen["map_group"], seen["map_number"],
                                              seen["x"], seen["y"]),
                   peer_modes)
            if row != last:
                timeline.append(dict(t=round(time.monotonic() - started, 3), b_publishes=row[0], a_receives=row[1],
                                     a_game_modes=row[2]))
                last = row
            await asyncio.sleep(.02)
        (root / "timeline.json").write_text(json.dumps(timeline, indent=1) + "\n")
        exits = [p.poll() for p in processes]
        if exits != [0, 0]:
            raise AssertionError(f"the games did not both run to their end: {exits}")
        record("both games ran to their end", exits=exits)
        for i in range(2):
            text = (root / f"client-{i}.log").read_text(errors="replace")
            if "bridge disconnected" in text:
                raise AssertionError(f"client {i}'s bridge disconnected: "
                                     f"{text[text.index('bridge disconnected'):].splitlines()[0]}")
        record("both games stayed connected to their companions")
        under = [r for r in timeline if r["b_publishes"] and tuple(r["b_publishes"][2:4]) == UNDERWATER_ROUTE_124]
        if not under:
            raise AssertionError("B never published a pose under the water of Route 124")
        # Only the states the other games draw count: arriving through the warp, B's first pose on the new map can still
        # say "walk" for a frame, as a "transition" nobody draws (mailbox.DRAWN_ACTIVITIES).
        modes = sorted({tuple(r["b_publishes"][:2]) for r in under})
        drawn = [mode for mode in modes if mode[1] in ("overworld", "menu")]
        if ("dive", "overworld") not in drawn or any(mode != "dive" for mode, _ in drawn):
            raise AssertionError(f"B under the water published {modes}")
        if ("dive", "menu") not in drawn:
            raise AssertionError(f"B's START menu under the water was not published as dive in a menu: {modes}")
        record("B published dive on the field and in its menu", modes=modes)
        # B walks on land (the save's place) until the warp under the water: only the underwater part is checked
        below = [r for r in timeline if r["a_receives"] and tuple(r["a_receives"][2:4]) == UNDERWATER_ROUTE_124]
        received = sorted({tuple(r["a_receives"][:2]) for r in below})
        drawn = [mode for mode in received if mode[1] in ("overworld", "menu")]
        if ("dive", "overworld") not in drawn or ("dive", "menu") not in drawn \
                or any(mode != "dive" for mode, _ in drawn):
            raise AssertionError(f"A received B under the water as {received}")
        moved = sorted({tuple(r["a_receives"][4:]) for r in below})
        record("A's companion received B diving", received=received, places=moved)
        given = sorted({tuple(mode) for r in below if r["a_game_modes"] for mode in r["a_game_modes"]})
        if (4, 1) not in given or any(mode != 4 for mode, drawn_flag in given if drawn_flag):
            raise AssertionError(f"A's game was given B as {given} (mailbox mode, drawn), not the underwater mode 4")
        record("A's game was given B under the water (mailbox mode 4, drawn)", given=given)
        pictures = sorted(p.name for p in (root / "client-0").glob("shot-*.png"))
        if len(pictures) != len(A_SHOTS.split(",")):
            raise AssertionError(f"{len(pictures)} of {len(A_SHOTS.split(','))} pictures")
        record("A's pictures of B", count=len(pictures), folder=str(root / "client-0"),
               frames="frame = 900 + 6 * (n - 50) for shot-n.png")
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
    parser.add_argument("--save", type=Path, required=True, help="a test save (any; both games are moved under the water)")
    parser.add_argument("--display", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0, help="stretch the time limit (3D on software OpenGL: 2)")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
