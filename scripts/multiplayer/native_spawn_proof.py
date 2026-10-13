"""Shared visible wild Pokemon (EmeraldTogether Phase 3), end to end: a real
world server, real companions and two native game clients.

Both games stand on Route 101 (copies of one test save, its strongest Pokemon
moved to the front so a single attack wins). The proof checks, from the games'
own spawn records (the 'g' frames the native bridge publishes: the spawn
objects each game actually draws, with their tiles) and from the host:

  1. the host fills Route 101 and both games draw the same Pokemon (same spawn
     ids) on the same tiles as the host's slots;
  2. a Pokemon the host walks is redrawn on its new tile by both games;
  3. a shiny Pokemon the host places in front of both players is drawn by both;
  4. both players press A at the same moment: the host grants exactly one
     claim, that game starts the battle (it stops drawing the field) and the
     other game is told the Pokemon is busy;
  5. the winner defeats it: the host removes it and both games stop drawing it;
  6. optional --rejoin: one companion restarts while its game runs; the game
     reconnects, shared spawns come back, and both games again draw the same.

Each client runs on its own X display and gets ordinary key presses (xdotool).
With --wine (one prefix per client) the Windows executable runs under Wine.

    PYTHONPATH=src python scripts/multiplayer/native_spawn_proof.py \\
        --game ../engine-graphics/pokeemerald-mp-diorama --rom ../engine-graphics/pokeemerald.gba \\
        --manifest manifest.json --save route101.sav --display :98 --display :97 \\
        --output /private/multiplayer-proof/native-spawns-1
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import struct
import subprocess
import time
from uuid import uuid4

from emerald_multiplayer.companion import Companion, CompanionConfig
from emerald_multiplayer.flash import POKEMON_SIZE, SAVED_PARTY_OFFSET
from emerald_multiplayer.server import ServerConfig, WorldServer

ROUTE101 = "0.16"
SECTOR = 4096
SAVEBLOCK1_DATA = 3968


# ---------------------------------------------------------------- test save
def _save_slots(data: bytes) -> tuple[int, dict[int, int]]:
    best = None
    for slot in (0, 1):
        sectors, counter = {}, None
        for i in range(14):
            base = (slot * 14 + i) * SECTOR
            sector_id, _, signature, count = struct.unpack_from("<HHII", data, base + 0xFF4)
            if signature == 0x08012025:
                sectors[sector_id] = base
                counter = count
        if len(sectors) == 14 and (best is None or counter > best[0]):
            best = (counter, sectors)
    if best is None:
        raise ValueError("no complete save slot")
    return best


def _sector_checksum(data: bytes, base: int, length: int) -> int:
    total = 0
    for i in range(0, length, 4):
        total = (total + struct.unpack_from("<I", data, base + i)[0]) & 0xFFFFFFFF
    return ((total >> 16) + total) & 0xFFFF


def strongest_first(source: Path, target: Path) -> None:
    """A private test fixture: the copy's party slots 0 and 1 swap places (the
    second Pokemon knows a damaging first move), so mashing A wins a battle.
    Party records are self-contained; only the sector checksum changes."""
    data = bytearray(source.read_bytes())
    _, sectors = _save_slots(data)
    base = sectors[1]
    first = base + SAVED_PARTY_OFFSET
    second = first + POKEMON_SIZE
    if SAVED_PARTY_OFFSET + 2 * POKEMON_SIZE > SAVEBLOCK1_DATA:
        raise ValueError("party is outside the first SaveBlock1 sector")
    a, b = bytes(data[first:second]), bytes(data[second:second + POKEMON_SIZE])
    data[first:second], data[second:second + POKEMON_SIZE] = b, a
    struct.pack_into("<H", data, base + 0xFF6, _sector_checksum(data, base, SAVEBLOCK1_DATA))
    target.write_bytes(bytes(data))
    target.chmod(0o600)


# ---------------------------------------------------------------- X helpers
def _xdotool(display: str, *arguments: str) -> None:
    subprocess.run(["xdotool", *arguments], env=dict(os.environ, DISPLAY=display), check=True)


def _focus(display: str) -> None:
    environment = dict(os.environ, DISPLAY=display)
    found = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", "Pokemon Emerald"], env=environment,
                           capture_output=True, text=True)
    for window in reversed(found.stdout.split()):
        if subprocess.run(["xdotool", "windowfocus", window], env=environment, capture_output=True).returncode == 0:
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
    if len(args.display) != 2:
        raise ValueError("two X displays, one per client")
    root.mkdir(mode=0o700, parents=True)
    manifest = json.loads(args.manifest.read_text())
    if hashlib.sha256(args.rom.read_bytes()).hexdigest() != manifest["rom_sha256"]:
        raise ValueError("ROM differs from its manifest")
    game = args.game.resolve()
    evidence = dict(scope="shared visible wild Pokemon: a real world server, real companions, two native clients",
                    game_sha256=hashlib.sha256(game.read_bytes()).hexdigest(), build_id=manifest["rom_sha256"],
                    checks=[], passed=False)

    def record(name: str, **fields) -> None:
        row = dict(verified=name, **fields)
        evidence["checks"].append(row)
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps(row), flush=True)

    server = WorldServer(ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"],
                                      heartbeat_interval=.2, idle_timeout=12), store=None)
    await server.start(port=0)
    world = server.shared_world
    companions: list[Companion] = []
    processes: list[subprocess.Popen] = []
    try:
        save = root / "route101-strongest-first.sav"
        strongest_first(args.save, save)
        for i, display in enumerate(args.display):
            copy = root / f"client-{i}.sav"
            shutil.copyfile(save, copy)
            companion = Companion(CompanionConfig(args.rom, args.manifest, str(uuid4()), f"Native {'AB'[i]}",
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
                # The Windows executable under Wine (SDL2.dll beside it): one
                # prefix per client, as Wine keeps one foreground window per
                # wineserver (KNOWN_ISSUES M3).
                command = ["wine"] + command
                environment.update(WINEPREFIX=str(args.wine[i % len(args.wine)]), WINEDEBUG="-all")
            processes.append(subprocess.Popen(command, cwd=root, env=environment, stdout=log,
                                              stderr=subprocess.STDOUT))
        loop = asyncio.get_running_loop()

        async def shots(tag: str) -> None:
            for i, display in enumerate(args.display):
                await asyncio.to_thread(_screenshot, display, root / f"{tag}-{i}.png")

        async def wait_for(name: str, condition, timeout: float, **fields) -> None:
            deadline = loop.time() + timeout
            while not condition():
                if any(p.poll() is not None for p in processes):
                    raise AssertionError(f"{name}: a client exited ({[p.poll() for p in processes]})")
                if loop.time() >= deadline:
                    await shots("timeout")
                    raise AssertionError(f"{name}: timed out; " + json.dumps(
                        {k: (v() if callable(v) else v) for k, v in fields.items()}, default=str))
                await asyncio.sleep(.25)
            record(name, **{k: (v() if callable(v) else v) for k, v in fields.items()})

        async def press(key: str, seconds: float = .2, clients=(0, 1)) -> None:
            await asyncio.gather(*(asyncio.to_thread(_hold, args.display[i], key, seconds) for i in clients))

        def in_overworld(i: int) -> bool:
            pose = companions[i]._local_pose
            return pose is not None and pose.activity == 1

        def shown(i: int) -> dict[int, tuple[int, int]]:
            local = companions[i]._local_spawn
            if local is None or (local.map_group, local.map_number) != (0, 16):
                return {}
            return {spawn_id: (x, y) for spawn_id, x, y in local.shown}

        def host_slots() -> dict[int, tuple[int, int]]:
            board = world.spawn_boards.existing(ROUTE101)
            return {} if board is None else {s.spawn_id: (s.x, s.y) for s in board.live()}

        await wait_for("native bridges authenticated to their companions",
                       lambda: all(c._bridge is not None for c in companions), 90)
        await wait_for("both native games announced the shared-spawn mailbox ('w')",
                       lambda: all(c._bridge is not None and c._bridge.spawn_capable for c in companions), 60)
        await wait_for("companions joined the world server",
                       lambda: all(c.connected for c in companions) and len(server.sessions) == 2, 30)

        await asyncio.sleep(12 * args.slow)
        await press("Return")
        await asyncio.sleep(5 * args.slow)
        await press("Return")
        await asyncio.sleep(12 * args.slow)
        await press("z")
        for _ in range(12):
            waiting = [i for i in range(2) if not in_overworld(i)]
            if not waiting:
                break
            await asyncio.sleep(5)
            waiting = [i for i in range(2) if not in_overworld(i)]
            if waiting:
                await press("z", clients=waiting)
        await wait_for("both games are on Route 101's overworld",
                       lambda: all(in_overworld(i) for i in range(2))
                       and all((c._local_pose.map_group, c._local_pose.map_number) == (0, 16) for c in companions), 30,
                       poses=lambda: [(c._local_pose.map_group, c._local_pose.map_number, c._local_pose.x,
                                       c._local_pose.y, c._local_pose.direction) for c in companions])
        await wait_for("the host made shared spawns active for both games (inbound 'enabled')",
                       lambda: all(c.spawn_inbound().enabled for c in companions), 30)

        # 1. The same Pokemon on the same tiles in both games.
        def drawn_by_both_like_the_host() -> bool:
            host = host_slots()
            a, b = shown(0), shown(1)
            common = set(a) & set(b)
            return (len(common) >= 2 and all(a[s] == b[s] for s in common)
                    and all(s in host and host[s] == a[s] for s in common))

        await wait_for("both games draw the host's Pokemon: same spawn ids on the same tiles", drawn_by_both_like_the_host,
                       90 * args.slow, host=host_slots, client_a=lambda: shown(0), client_b=lambda: shown(1),
                       species=lambda: {s.spawn_id: s.species for s in world.spawn_boards.board(ROUTE101).live()})
        await shots("01-same-pokemon")

        # 2. Movement: a Pokemon the host walked is redrawn on its new tile.
        before = dict(host_slots())

        def a_move_redrawn() -> bool:
            host = host_slots()
            moved = [s for s in host if s in before and host[s] != before[s]]
            return any(shown(0).get(s) == host[s] and shown(1).get(s) == host[s] for s in moved)

        await wait_for("a Pokemon the host walked is redrawn on its new tile by both games", a_move_redrawn,
                       60 * args.slow, host=host_slots, client_a=lambda: shown(0), client_b=lambda: shown(1))

        # 3. A shiny Pokemon in front of both players: both walk one tile west
        # (the key is held until the game's own pose shows the step, then
        # released, so a slow game takes exactly one step) and face it.
        async def hold_until(i: int, key: str, condition, timeout: float) -> None:
            await asyncio.to_thread(_focus, args.display[i])
            await asyncio.to_thread(_xdotool, args.display[i], "keydown", key)
            try:
                deadline = loop.time() + timeout
                while not condition() and loop.time() < deadline:
                    await asyncio.sleep(.05)
            finally:
                await asyncio.to_thread(_xdotool, args.display[i], "keyup", key)

        start = [(c._local_pose.x, c._local_pose.y) for c in companions]
        await asyncio.gather(*(hold_until(i, "Left", lambda i=i: companions[i]._local_pose.x != start[i][0],
                                          20 * args.slow) for i in range(2)))
        await asyncio.sleep(4 * args.slow)
        poses = [(c._local_pose.x, c._local_pose.y, c._local_pose.direction) for c in companions]
        record("both players took one step west and face west", poses=poses, start=start)
        x, y, direction = poses[0]
        if poses[1] != poses[0] or direction != 3:
            raise AssertionError(f"the players do not stand together facing west: {poses}")
        board = world.spawn_boards.board(ROUTE101)
        target = (x - 1, y)
        for slot in list(board.live()):
            if (slot.x, slot.y) == target:
                board.retire(slot.spawn_id, "proof")
        # Make room: the map may already hold its eight Pokemon (the proof's one
        # direct host action; the director refills the slot as usual).
        for slot in list(board.live()):
            if board.live_count() < board.limit():
                break
            board.retire(slot.spawn_id, "proof")
        shiny = board.create(species=263, level=3, personality=0x12345678, shiny=True, x=target[0], y=target[1],
                             lifetime=900, facing=4)
        server._broadcast_world()
        await wait_for("both games draw the shiny Pokemon the host placed in front of them",
                       lambda: shown(0).get(shiny) == target and shown(1).get(shiny) == target, 30 * args.slow,
                       spawn_id=shiny, tile=target)
        await asyncio.sleep(1.5)
        await shots("02-shiny-in-front")

        # 4. Both press A at once: exactly one claim wins. (A slow game runs a
        # frame every few hundred milliseconds: the key is held long enough
        # for both to see it.)
        def claim_state() -> list[dict]:
            out = []
            for i, c in enumerate(companions):
                local = c._local_spawn
                flags = next((slot.flags for slot in c.spawn_inbound().slots if slot.spawn_id == shiny), None)
                out.append(dict(action=None if local is None else (local.action.seq, local.action.kind,
                                                                     local.action.spawn_id),
                                ack=c._spawn_action_ack, flags=flags, shown=shown(i),
                                overworld=in_overworld(i)))
            return out

        await press("z", .5)
        for second in range(6):
            await asyncio.sleep(1)
            record(f"claim race, after {second + 1} s", state=claim_state(),
                   claimant=board.get(shiny).claimant if board.get(shiny) else None)
            if second in (1, 4):
                await shots(f"03-claim-{second + 1}s")
        await wait_for("the host granted exactly one claim",
                       lambda: board.get(shiny) is not None and board.get(shiny).claimant is not None, 60,
                       claimant=lambda: board.get(shiny).claimant if board.get(shiny) else None,
                       state=claim_state)
        winner_id = board.get(shiny).claimant
        winner = next(i for i, c in enumerate(companions) if c.config.player_id == winner_id)
        loser = 1 - winner
        record("claim winner and loser", winner=winner, loser=loser)

        def busy_for_loser() -> bool:
            inbound = companions[loser].spawn_inbound()
            return any(slot.spawn_id == shiny and slot.flags & 4 for slot in inbound.slots)

        await wait_for("the other game's mailbox marks the Pokemon busy", busy_for_loser, 10)
        await wait_for("the winner's game left the field for the battle (it draws no spawn objects)",
                       lambda: not in_overworld(winner) and not shown(winner), 30 * args.slow)
        await asyncio.sleep(3 * args.slow)
        await shots("03-race")

        # 5. The winner defeats it (A through FIGHT, the first move and the
        # messages); the other player closes its "busy" message.
        async def close_messages(i: int, timeout: float) -> None:
            deadline = loop.time() + timeout
            while not in_overworld(i) and loop.time() < deadline:
                await press("z", .5, clients=(i,))
                await asyncio.sleep(1.5 * args.slow)

        record("the other game shows its message while the field waits",
               loser_in_overworld=in_overworld(loser))
        await close_messages(loser, 60 * args.slow)
        deadline = loop.time() + 180 * args.slow
        while board.get(shiny) is not None and loop.time() < deadline:
            await press("z", .5, clients=(winner,))
            await asyncio.sleep(1.2 * args.slow)
        await wait_for("the battle's result reached the host: the Pokemon is removed for everybody",
                       lambda: board.get(shiny) is None, 30,
                       removed=lambda: next((s.end_reason for i, s in board.slots.items() if i == shiny), "pruned"))
        await close_messages(winner, 90 * args.slow)
        await close_messages(loser, 30 * args.slow)
        await wait_for("both games stopped drawing it",
                       lambda: in_overworld(0) and in_overworld(1) and shiny not in shown(0) and shiny not in shown(1),
                       60 * args.slow, client_a=lambda: shown(0), client_b=lambda: shown(1))
        await shots("04-after-battle")
        await wait_for("both games still draw the same remaining Pokemon", drawn_by_both_like_the_host,
                       60 * args.slow, host=host_slots, client_a=lambda: shown(0), client_b=lambda: shown(1))

        if args.rejoin is not None:
            i = args.rejoin
            old, port = companions[i].config, companions[i].ipc_address[1]
            await companions[i].close()
            await wait_for(f"client {i}'s companion closed: the host dropped its session",
                           lambda: len(server.sessions) == 1, 30)
            await asyncio.sleep(3)
            companions[i] = Companion(replace(old, ipc_port=port))
            await companions[i].start()
            await wait_for(f"client {i}'s running game reconnected and announced its spawn mailbox again",
                           lambda: companions[i]._bridge is not None and companions[i]._bridge.spawn_capable, 60)
            await wait_for(f"client {i} rejoined the host",
                           lambda: companions[i].connected and len(server.sessions) == 2, 30)
            await wait_for("after the rejoin both games draw the same Pokemon again", drawn_by_both_like_the_host,
                           90 * args.slow, host=host_slots, client_a=lambda: shown(0), client_b=lambda: shown(1))
            await shots("05-rejoined")
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
    parser.add_argument("--save", type=Path, required=True, help="a test save standing on Route 101")
    parser.add_argument("--display", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.5, help="stretch the waits (3D build on software OpenGL)")
    parser.add_argument("--rejoin", type=int, help="CLIENT: restart that client's companion while its game runs")
    parser.add_argument("--wine", type=Path, action="append",
                        help="Wine prefix, one per client: run the Windows executable under Wine")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
