"""Native game clients (no emulator) through the native bridge: presence proof.

Two to four copies of the native executable (engine `src/platform/mp_bridge.c`)
connect to unchanged companions and an unchanged world server. The companions
verify the GBA ROM and manifest built from the same engine commit as the
executable, exactly as they do for mGBA; the native bridge takes its mailboxes
from the executable itself. Each client runs on its own X display and gets
ordinary key presses (xdotool); results come from the companions' and the
server's state and from screenshots. Presence only: no ownership store, so
saves, trades and battles are out of scope here.

    PYTHONPATH=src python scripts/multiplayer/native_presence_proof.py \\
        --game ../engine/pokeemerald-mp --rom ../engine/pokedev.gba \\
        --manifest manifest.json --save a.sav --save b.sav \\
        --display :98 --display :97 --output /private/multiplayer-proof/native-presence-1
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
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


def _xdotool(display: str, *arguments: str) -> None:
    subprocess.run(["xdotool", *arguments], env=dict(os.environ, DISPLAY=display), check=True)


def _focus(display: str) -> None:
    """No window manager runs on the test displays: give the game's window
    the keyboard (Wine does not take it by itself)."""
    environment = dict(os.environ, DISPLAY=display)
    found = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", "Pokemon Emerald"], env=environment,
                           capture_output=True, text=True)
    for window in reversed(found.stdout.split()):
        # Wine also names a hidden helper window after the game; it refuses focus.
        if subprocess.run(["xdotool", "windowfocus", window], env=environment,
                          capture_output=True).returncode == 0:
            return


def _hold(display: str, key: str, seconds: float) -> None:
    _focus(display)
    _xdotool(display, "keydown", key)
    time.sleep(seconds)
    _xdotool(display, "keyup", key)


def _screenshot(display: str, path: Path) -> None:
    subprocess.run(["import", "-window", "root", str(path)], env=dict(os.environ, DISPLAY=display), check=True)


async def run(args: argparse.Namespace) -> None:
    root = args.output.resolve()
    if "/multiplayer-proof/" not in str(root) + "/" or root.exists():
        raise ValueError("choose a new private multiplayer-proof output directory")
    if not 2 <= len(args.save) <= 4 or len(args.display) != len(args.save):
        raise ValueError("two to four saves, one X display each")
    root.mkdir(mode=0o700, parents=True)
    manifest = json.loads(args.manifest.read_text())
    if hashlib.sha256(args.rom.read_bytes()).hexdigest() != manifest["rom_sha256"]:
        raise ValueError("ROM differs from its manifest")
    game = args.game.resolve()
    evidence = dict(scope="native clients through the native bridge: presence only (no ownership store)",
                    game_sha256=hashlib.sha256(game.read_bytes()).hexdigest(),
                    build_id=manifest["rom_sha256"], engine_commit=manifest.get("engine_commit"),
                    checks=[], passed=False)

    def record(name: str, **fields) -> None:
        row = dict(verified=name, **fields)
        evidence["checks"].append(row)
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps(row), flush=True)

    server = WorldServer(ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"],
                                      heartbeat_interval=.2, idle_timeout=12), store=None)
    await server.start(port=0)
    companions: list[Companion] = []
    processes: list[subprocess.Popen] = []
    try:
        for i, (save, display) in enumerate(zip(args.save, args.display)):
            copy = root / f"client-{i}.sav"
            shutil.copyfile(save, copy)
            companion = Companion(CompanionConfig(args.rom, args.manifest, str(uuid4()), f"Native {'ABCD'[i]}",
                                                  secrets.token_bytes(32), server_port=server.address[1], ipc_port=0))
            await companion.start()
            companions.append(companion)
            bridge = root / f"bridge-{i}.txt"
            bridge.write_text(f"port={companion.ipc_address[1]}\ntoken={companion.config.token.hex()}\n")
            bridge.chmod(0o600)
            log = (root / f"client-{i}.log").open("wb")
            command = [str(game), "--save", str(copy), "--bridge", str(bridge)]
            environment = dict(os.environ, DISPLAY=display, SDL_AUDIODRIVER="dummy")
            if args.wine:
                # The Windows executable under Wine: same arguments, Winsock bridge.
                # One prefix (wineserver) per client: Wine keeps one foreground
                # window per wineserver, so two clients sharing one lose keys.
                command = ["wine"] + command
                environment.update(WINEPREFIX=str(args.wine[i % len(args.wine)]), WINEDEBUG="-all")
            processes.append(subprocess.Popen(command, cwd=root, env=environment,
                                              stdout=log, stderr=subprocess.STDOUT))

        async def wait_for(name: str, condition, timeout: float, **fields) -> None:
            deadline = asyncio.get_running_loop().time() + timeout
            while not condition():
                if any(p.poll() is not None for p in processes):
                    raise AssertionError(f"{name}: a client exited ({[p.poll() for p in processes]})")
                if asyncio.get_running_loop().time() >= deadline:
                    for i, display in enumerate(args.display):
                        await asyncio.to_thread(_screenshot, display, root / f"timeout-{i}.png")
                    raise AssertionError(f"{name}: timed out; " + json.dumps(
                        [dict(connected=c.connected, bridge=c._bridge is not None, error=c.last_error) for c in companions]))
                await asyncio.sleep(.25)
            record(name, **fields)

        await wait_for("native bridges authenticated to their companions",
                       lambda: all(c._bridge is not None for c in companions), 90)
        await wait_for("companions joined the world server",
                       lambda: all(c.connected for c in companions) and len(server.sessions) == len(companions), 30,
                       sessions=len(server.sessions))

        # A slow client (Wine, several games on two cores) may run one main-loop
        # pass in more than 150 ms; a shorter press is then lost between frames.
        default_hold = .5 if args.wine else .15

        async def press(key: str, seconds: float | None = None, clients=None) -> None:
            seconds = default_hold if seconds is None else seconds
            await asyncio.gather(*(asyncio.to_thread(_hold, args.display[i], key, seconds)
                                   for i in (clients if clients is not None else range(len(processes)))))

        # Title screen, main menu, Continue: the same keys a player presses,
        # A again on any client whose game has not reached the overworld yet
        # (its own pose, as its bridge publishes it, says so).
        def in_overworld(i: int) -> bool:
            pose = companions[i]._local_pose
            return pose is not None and pose.activity == 1

        await asyncio.sleep(12)
        await press("Return")
        await asyncio.sleep(5)
        await press("Return")
        await asyncio.sleep(12)
        await press("z")
        for _ in range(12):
            waiting = [i for i in range(len(companions)) if not in_overworld(i)]
            if not waiting:
                break
            await asyncio.sleep(5)
            waiting = [i for i in range(len(companions)) if not in_overworld(i)]
            if waiting:
                await press("z", clients=waiting)
        await wait_for("every client is in the overworld (its bridge's own pose)",
                       lambda: all(in_overworld(i) for i in range(len(companions))), 20)
        others = len(companions) - 1

        def overworld_peers(i: int) -> int:
            return sum(1 for p in companions[i].snapshot.peers if p.pose.activity == 1)

        await wait_for("every client sees the others in the overworld",
                       lambda: all(overworld_peers(i) == others for i in range(len(companions))), 60,
                       peers=[overworld_peers(i) for i in range(len(companions))])
        await asyncio.sleep(3)
        for i, display in enumerate(args.display):
            await asyncio.to_thread(_screenshot, display, root / f"01-together-{i}.png")

        def seen_by(observer: int) -> list[tuple[int, int, int, int]]:
            return sorted((p.pose.map_group, p.pose.map_number, p.pose.x, p.pose.y)
                          for p in companions[observer].snapshot.peers)

        before = seen_by(1)
        # Two steps in whichever direction is open for A.
        for direction in ("Down", "Right", "Up", "Left"):
            await press(direction, max(default_hold, 2 * .267 - .12), clients=[0])
            deadline = asyncio.get_running_loop().time() + 8
            while seen_by(1) == before and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(.25)
            if seen_by(1) != before:
                break
        await wait_for("a move by client A reaches client B", lambda: seen_by(1) != before, 10, before=before)
        record("client B's view after the move", after=seen_by(1))
        await asyncio.sleep(2)
        for i, display in enumerate(args.display):
            await asyncio.to_thread(_screenshot, display, root / f"02-after-move-{i}.png")
        poses = [seen_by(i) for i in range(len(companions))]
        record("peer poses as each companion sees them", poses=poses)
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
    parser.add_argument("--game", type=Path, required=True, help="native executable built with the bridge")
    parser.add_argument("--rom", type=Path, required=True, help="GBA ROM of the same engine commit")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--save", type=Path, action="append", required=True)
    parser.add_argument("--display", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wine", type=Path, action="append",
                        help="Wine prefix, one per client: run the Windows executable under Wine")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
