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
  4. B publishes the Pokemon carrying it under the water (the mount state "carrier", 2, with its species: the Lapras
     of the test party, which knows Surf) and A's companion receives it, so that A's game draws B on it as the
     silhouette, as each game draws its own diver (KNOWN_ISSUES MS-181's last part; engines before it published no
     carrier under the water and A drew B with the original's underwater look, the blob drawn in);
  5. A's pictures were all taken.

With --scenario surface (KNOWN_ISSUES MS-181's last part), both start on the deep water of Route 124's surface (A at
42,5, B at 43,6, each with a Wailord that knows Dive) and dive (the field's prompt answered with A), so that each has
the Pokemon that dove carrying them under the water; then B swims (south, west, back) and opens its START menu, and
A takes a picture every 6 frames from frame 700. Check 4 then requires B's carrier (Wailord) under the water.

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


def after_first_dive(timeline, key):
    """The rows from the first in which `key` (B as published, or as A received it) says "dive" under the water of
    Route 124 on the scenario's stretch of the sea floor."""
    rows = [r for r in timeline if r[key] and tuple(r[key][2:4]) == UNDERWATER_ROUTE_124 and on_sea_floor(r[key])]
    first = next((i for i, r in enumerate(rows) if r[key][0] == "dive"), len(rows))
    return rows[first:]


def arrival(timeline, key):
    """What `key` said under the water before its first "dive" there (the Dive's own arrival)."""
    rows = [r for r in timeline if r[key] and tuple(r[key][2:4]) == UNDERWATER_ROUTE_124]
    first = next((i for i, r in enumerate(rows) if r[key][0] == "dive"), len(rows))
    return sorted({tuple(r[key][:2]) for r in rows[:first]}), (round(rows[first]["t"] - rows[0]["t"], 3)
                                                                if rows and first < len(rows) else None)


def on_sea_floor(fields) -> bool:
    """A pose (movement, activity, group, number, x, y) on that stretch of the sea floor."""
    return SCENARIO["floor"][0] <= fields[4] <= SCENARIO["floor"][1] and SCENARIO["floor"][2] <= fields[5] <= SCENARIO["floor"][3]


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

# Diving from the surface (KNOWN_ISSUES MS-181's last part): Route 124's deep water at 42-43,5-6, a 2x2 patch of dive
# spots with the sea floor free under it; Wailord (321) knowing Dive (291) carries each player down.
ROUTE_124, WAILORD = (0, 39), 321
SURFACE_A, SURFACE_B = (42, 5), (43, 6)
DIVE_KEYS = ["130:A", "200:A", "270:A", "340:A"]          # the prompt: the sea is deep here, use Dive? yes; its text
SURFACE_A_KEYS = ",".join(DIVE_KEYS + ["600:DOWN"])       # down, face south toward B
SURFACE_B_KEYS = ",".join(DIVE_KEYS + [
    "700:DOWN", "712:DOWN",                               # turn south, one tile
    "800:LEFT", "812:LEFT",                               # turn west, one tile
    "900:RIGHT", "912:RIGHT",                             # back east
    "1000:UP", "1012:UP",                                 # back north, where B dove
    "1100:START", "1250:B",                               # the START menu open for a while, closed
])
SCENARIOS = {
    "warp": dict(at=(A_AT, B_AT), map=UNDERWATER_ROUTE_124, warp_id=-1, party=f"{LAPRAS}:40:v57", keys=(A_KEYS, B_KEYS),
                 shots=A_SHOTS, first=900, floor=(36, 50, 16, 18), carrier=LAPRAS),
    "surface": dict(at=(SURFACE_A, SURFACE_B), map=ROUTE_124, warp_id=0, party=f"{WAILORD}:40:v291",
                    keys=(SURFACE_A_KEYS, SURFACE_B_KEYS), shots=",".join(str(f) for f in range(700, 1360, 6)), first=700,
                    floor=(38, 48, 2, 10), carrier=WAILORD),
}
SCENARIO = SCENARIOS["warp"]


async def run(args: argparse.Namespace) -> None:
    global SCENARIO
    SCENARIO = SCENARIOS[args.scenario]
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
            companion.share_location = True   # A reads B's place under the water: both chose to share (docs/pokenav-privacy.md)
            await companion.start()
            companions.append(companion)
            bridge = root / f"bridge-{i}.txt"
            bridge.write_text(f"port={companion.ipc_address[1]}\ntoken={companion.config.token.hex()}\n")
            bridge.chmod(0o600)
            rundir = root / f"client-{i}"
            rundir.mkdir()
            (rundir / "pokeemerald.cfg").write_text(CONFIG)
            x, y = SCENARIO["at"][i]
            group, number = SCENARIO["map"]
            environment = dict(os.environ, DISPLAY=display, SDL_AUDIODRIVER="dummy", PKMN_NOSCENE="1",
                               PKMN_TEST_EXIT="1", PKMN_TEST_BATTLE=f"field:{FRAMES}", PKMN_TEST_AUTOPILOT="1",
                               PKMN_TEST_BATTLE_DELAY="100", PKMN_TEST_PARTY=SCENARIO["party"],
                               PKMN_TEST_WARP=f"{group}:{number}:{SCENARIO['warp_id']}:{x}:{y}",
                               PKMN_TEST_BADGES="8", PKMN_TEST_OWE_NO_BATTLE="1",
                               PKMN_TEST_LOG=str(rundir / "test.log"),
                               PKMN_TEST_MEGA_SHOT_STEM=str(rundir / "shot"),
                               PKMN_TEST_FIELD_KEYS=SCENARIO["keys"][i],
                               PKMN_TEST_FIELD_SHOTS=SCENARIO["shots"] if i == 0 else "")
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
                   peer_modes,
                   None if seen is None else (seen.get("mount_state"), seen.get("mount_species"), seen.get("mount_flags")))
            if row != last:
                timeline.append(dict(t=round(time.monotonic() - started, 3), b_publishes=row[0], a_receives=row[1],
                                     a_game_modes=row[2], a_receives_mount=row[3]))
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
        under = after_first_dive(timeline, "b_publishes")
        if not under:
            raise AssertionError("B never published a pose under the water of Route 124")
        # Only the states the other games draw count: arriving through the warp, B's first pose on the new map can still
        # say "walk" for a frame, as a "transition" nobody draws (mailbox.DRAWN_ACTIVITIES); the test's warp straight
        # from a menu on land (not a Dive) can name the new map with the land's place and activity for one sample (the
        # stretch of sea floor below leaves that out); and a Dive from the surface names the new map for a few samples
        # while its message box is still a "menu" and the movement still "surf" (about 0.1 s; recorded as
        # "arrival"): from B's first "dive" there on.
        modes = sorted({tuple(r["b_publishes"][:2]) for r in under})
        drawn = [mode for mode in modes if mode[1] in ("overworld", "menu")]
        if ("dive", "overworld") not in drawn or any(mode != "dive" for mode, _ in drawn):
            raise AssertionError(f"B under the water published {modes}")
        if ("dive", "menu") not in drawn:
            raise AssertionError(f"B's START menu under the water was not published as dive in a menu: {modes}")
        states, seconds = arrival(timeline, "b_publishes")
        record("B published dive on the field and in its menu", modes=modes,
               arrival=dict(before_first_dive=states, seconds=seconds))
        # B walks on land (the save's place) until the warp under the water: only the underwater part is checked
        below = after_first_dive(timeline, "a_receives")
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
        # B's carrier under the water (mount state 2, "carrier", with its species), as A's companion received it while B
        # was there on the field
        carriers = sorted({tuple(r["a_receives_mount"]) for r in below
                           if r["a_receives_mount"] and tuple(r["a_receives"][:2]) == ("dive", "overworld")})
        carried = any(mount[:2] == (2, SCENARIO["carrier"]) for mount in carriers)
        if args.expect_carrier and not carried:
            raise AssertionError(f"A received no carrier for B under the water: {carriers}")
        record("A's companion received B's carrier under the water" if carried
               else "no carrier received for B under the water (an engine before KNOWN_ISSUES MS-181's last part, or no "
                    "Pokemon carrying B: the warp scenario's party is made after its arrival)", mounts=carriers)
        pictures = sorted(p.name for p in (root / "client-0").glob("shot-*.png"))
        if len(pictures) != len(SCENARIO["shots"].split(",")):
            raise AssertionError(f"{len(pictures)} of {len(SCENARIO['shots'].split(','))} pictures")
        record("A's pictures of B", count=len(pictures), folder=str(root / "client-0"),
               frames=f"frame = {SCENARIO['first']} + 6 * (n - 50) for shot-n.png")
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
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="warp",
                        help="warp: both warped under the water (the party made after); surface: both dive from the surface")
    parser.add_argument("--no-expect-carrier", dest="expect_carrier", action="store_false",
                        help="an engine before MS-181's last part: B's carrier under the water is not required")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
