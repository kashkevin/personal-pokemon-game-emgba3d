"""Multiplayer following Pokemon (EmeraldTogether Phase 5), end to end: a real
world server, real companions and two native game clients on Route 101, each
player followed by its lead Pokemon (a copy of the test save with its
strongest Pokemon in front, as in native_spawn_proof.py).

The proof checks, from the companions' records (the 'G' shared-world records
the native bridge publishes, the inbound records the companions build for the
games), the host's sessions and the games' own spawn records ('g'):

  1. each game publishes its following Pokemon (species, the form being its
     own species ID, the shiny and female flags, visibility) and the host
     relays it: each game's inbound record carries the other player's follower
     with exactly those values;
  2. the players walk apart; each game draws the other player's follower
     behind that player (screenshots);
  3. talking to the other player's follower, and to the other player, does
     nothing: no script, no battle, no claim, no crash (they cannot be claimed);
  4. a battle: the other player claims and defeats a shared wild Pokemon; while
     it battles, its avatar and follower leave this game's field (its presence
     says battle), and they come back after; followers never occupy a shared
     spawn slot (every object a game reports as a shared spawn is one of the
     host's slots, and the host's board holds only spawns).

Buildings, caves and surfing follow from the same code (a player on another
map or surfing has no follower drawn; large Pokemon wait outside indoors) and
are covered by docs/shared-spawn-architecture.md (engine) and the procedure
for the Windows test, not by this script.

    PYTHONPATH=src python scripts/multiplayer/native_follower_proof.py \\
        --game ../engine-graphics/pokeemerald-mp-diorama --rom ../engine-graphics/pokeemerald.gba \\
        --manifest manifest.json --save route101.sav --display :98 --display :97 \\
        --output /private/multiplayer-proof/native-followers-1
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import struct
import subprocess
from uuid import uuid4

from emerald_multiplayer.companion import Companion, CompanionConfig
from emerald_multiplayer.flash import POKEMON_SIZE, SAVED_PARTY_OFFSET
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.world_mailbox import FOLLOWER_FEMALE, FOLLOWER_SHINY, FOLLOWER_VISIBLE

_spec = importlib.util.spec_from_file_location("native_spawn_proof", Path(__file__).with_name("native_spawn_proof.py"))
_spawn_proof = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_spawn_proof)
_focus, _hold, _screenshot, _xdotool = (_spawn_proof._focus, _spawn_proof._hold, _spawn_proof._screenshot,
                                         _spawn_proof._xdotool)

ROUTE101 = "0.16"
ACTIVITY_OVERWORLD = 1


def lead_of(save: Path) -> dict:
    """The save's first party Pokemon (the follower): its species and
    personality. Its shiny and female flags are the game's own (the
    expansion also stores a shiny bit), compared between the two games."""
    from emerald_multiplayer.flash import _box_species, inspect_flash
    snapshot = inspect_flash(save.read_bytes())
    mon = snapshot.save_block1[SAVED_PARTY_OFFSET:SAVED_PARTY_OFFSET + POKEMON_SIZE]
    personality, _ = struct.unpack_from("<II", mon)
    return dict(species=_box_species(mon[:80], "lead"), personality=personality)


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
    # As the spawn proof: a copy with the save's strongest Pokemon (it knows a
    # damaging first move) in front, which is then also the follower.
    save = root / "route101-strongest-first.sav"
    _spawn_proof.strongest_first(args.save, save)
    lead = lead_of(save)
    evidence = dict(scope="multiplayer following Pokemon: a real world server, real companions, two native clients",
                    game_sha256=hashlib.sha256(game.read_bytes()).hexdigest(), build_id=manifest["rom_sha256"],
                    lead=lead, checks=[], passed=False)

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
                command = ["wine"] + command
                environment.update(WINEPREFIX=str(args.wine[i % len(args.wine)]), WINEDEBUG="-all")
            processes.append(subprocess.Popen(command, cwd=root, env=environment, stdout=log,
                                              stderr=subprocess.STDOUT))
        loop = asyncio.get_running_loop()
        ids = [c.config.player_id for c in companions]

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

        def pose(i: int):
            return companions[i]._local_pose

        def in_overworld(i: int) -> bool:
            p = pose(i)
            return p is not None and p.activity == ACTIVITY_OVERWORLD

        def where(i: int):
            p = pose(i)
            return None if p is None else (p.map_group, p.map_number, p.x, p.y, p.direction)

        def published(i: int):
            state = companions[i]._local_world
            return None if state is None else (state.follower_species, state.follower_flags)

        def relayed(i: int):
            """The follower the other player's game receives for player i."""
            other = companions[1 - i]
            for _, state in other.world_inbound().peers:
                if state.follower_species:
                    return state.follower_species, state.follower_flags
            return None

        def host_follower(i: int):
            presence = server.sessions[ids[i]].presence if ids[i] in server.sessions else None
            return None if presence is None else (presence.get("follower_species"), presence.get("follower_flags"))

        def shown(i: int) -> dict[int, tuple[int, int]]:
            local = companions[i]._local_spawn
            if local is None or (local.map_group, local.map_number) != (0, 16):
                return {}
            return {spawn_id: (x, y) for spawn_id, x, y in local.shown}

        async def hold_until(i: int, key: str, condition, timeout: float) -> None:
            await asyncio.to_thread(_focus, args.display[i])
            await asyncio.to_thread(_xdotool, args.display[i], "keydown", key)
            try:
                deadline = loop.time() + timeout
                while not condition() and loop.time() < deadline:
                    await asyncio.sleep(.05)
            finally:
                await asyncio.to_thread(_xdotool, args.display[i], "keyup", key)

        await wait_for("native bridges authenticated to their companions",
                       lambda: all(c._bridge is not None for c in companions), 90)
        await wait_for("companions joined the world server",
                       lambda: all(c.connected for c in companions) and len(server.sessions) == 2, 60)
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
                       lambda: all(in_overworld(i) and where(i)[:2] == (0, 16) for i in range(2)), 30,
                       poses=lambda: [where(i) for i in range(2)])
        start = [where(i) for i in range(2)]

        # 1-2. Walk apart: client 1 three tiles north, client 0 one tile north
        # (it then faces client 1's follower, which trails one tile behind).
        x0, y0 = start[0][2], start[0][3]
        await hold_until(1, "Up", lambda: where(1)[3] <= y0 - 3, 30 * args.slow)
        await asyncio.sleep(2 * args.slow)
        await hold_until(0, "Up", lambda: where(0)[3] <= y0 - 1, 20 * args.slow)
        await asyncio.sleep(4 * args.slow)
        record("the players walked apart", poses=[where(i) for i in range(2)], start=start)
        if where(1)[2:4] != (x0, y0 - 3) or where(0)[2:4] != (x0, y0 - 1) or where(0)[4] != 2:
            raise AssertionError(f"unexpected positions: {[where(i) for i in range(2)]}")

        await wait_for("each game publishes its follower: the save's lead, visible",
                       lambda: all(published(i) is not None and published(i)[0] == lead["species"]
                                   and published(i)[1] & FOLLOWER_VISIBLE for i in range(2)), 30,
                       published=lambda: [published(i) for i in range(2)], lead=lead["species"])
        flags = [published(i)[1] for i in range(2)]
        if flags[0] != flags[1]:  # two copies of one save: the same lead, the same flags
            raise AssertionError(f"the two games publish different follower flags: {flags}")
        await wait_for("the host relays them: each game's inbound record carries the other's follower",
                       lambda: all(relayed(i) == published(i) and host_follower(i) == published(i) for i in range(2)),
                       30, host=lambda: [host_follower(i) for i in range(2)],
                       relayed=lambda: [relayed(i) for i in range(2)],
                       shiny=bool(flags[0] & FOLLOWER_SHINY), female=bool(flags[0] & FOLLOWER_FEMALE))
        await shots("01-followers")

        # 3. Talking to the other player's follower, then to the other player.
        def quiet(i: int, action_seq: int):
            local = companions[i]._local_spawn
            return in_overworld(i) and (local is None or local.action.seq == action_seq)

        seq0 = companions[0]._local_spawn.action.seq if companions[0]._local_spawn else 0
        await press("z", .5, clients=(0,))
        await asyncio.sleep(4 * args.slow)
        await shots("02-talk-to-their-follower")
        await wait_for("talking to the other player's follower does nothing (no script, claim or battle)",
                       lambda: quiet(0, seq0), 5, pose=lambda: where(0))
        await hold_until(0, "Up", lambda: where(0)[3] <= y0 - 2, 20 * args.slow)
        await asyncio.sleep(3 * args.slow)
        record("player 0 stepped onto the follower's tile (other players' objects do not block)",
               poses=[where(i) for i in range(2)])
        await press("z", .5, clients=(0,))
        await asyncio.sleep(4 * args.slow)
        await shots("03-talk-to-the-other-player")
        await wait_for("talking to the other player does nothing either", lambda: quiet(0, seq0), 5,
                       pose=lambda: where(0))

        # 4. Battle: client 1 claims a shared wild Pokemon placed in front of it.
        board = world.spawn_boards.board(ROUTE101)
        target = (x0, y0 - 4)
        for slot in list(board.live()):
            if (slot.x, slot.y) == target or board.live_count() >= board.limit():
                board.retire(slot.spawn_id, "proof")
        spawn = board.create(species=263, level=3, personality=0x2468ACE0, shiny=False, x=target[0], y=target[1],
                             lifetime=900, facing=1)
        server._broadcast_world()
        await wait_for("both games draw the wild Pokemon in front of player 1",
                       lambda: shown(1).get(spawn) == target and shown(0).get(spawn) == target, 30 * args.slow,
                       spawn_id=spawn, tile=target)
        await press("z", .5, clients=(1,))
        await wait_for("player 1 claimed it and battles", lambda: board.get(spawn) is not None
                       and board.get(spawn).claimant == ids[1] and not in_overworld(1), 60 * args.slow,
                       presence=lambda: (server.sessions[ids[1]].presence or {}).get("activity"))
        # A wild battle is not the overworld: the game reports itself
        # unavailable (only link battles are "battle"), and every other game
        # stops drawing that player and its follower (multiplayer.c PeerVisible).
        def relayed_activity():
            return next((p["presence"]["activity"] for p in companions[0]._players
                         if p["player_id"] == ids[1] and p["presence"]), None)

        await wait_for("player 0's game is told player 1 left the overworld (its avatar and follower leave the field)",
                       lambda: relayed_activity() not in (None, "overworld"), 60 * args.slow,
                       host=lambda: (server.sessions[ids[1]].presence or {}).get("activity"),
                       relayed_activity=relayed_activity)
        await asyncio.sleep(3 * args.slow)
        await shots("04-other-player-in-battle")
        deadline = loop.time() + 180 * args.slow
        while board.get(spawn) is not None and loop.time() < deadline:
            await press("z", .5, clients=(1,))
            await asyncio.sleep(1.2 * args.slow)
        await wait_for("player 1 won: the host removed the Pokemon", lambda: board.get(spawn) is None, 30)
        deadline = loop.time() + 90 * args.slow
        while not in_overworld(1) and loop.time() < deadline:
            await press("z", .5, clients=(1,))
            await asyncio.sleep(1.5 * args.slow)
        await wait_for("player 1 is back on the overworld with its follower",
                       lambda: in_overworld(1) and relayed(1) == published(1)
                       and published(1)[1] & FOLLOWER_VISIBLE, 60 * args.slow,
                       published=lambda: published(1))
        await asyncio.sleep(4 * args.slow)
        await shots("05-back-from-battle")
        host_ids = {s.spawn_id for s in board.live()}
        await wait_for("followers never use shared spawn slots: every drawn spawn is a host slot",
                       lambda: set(shown(0)) <= {s.spawn_id for s in board.live()}
                       and set(shown(1)) <= {s.spawn_id for s in board.live()}, 10,
                       host=sorted(host_ids), client_a=lambda: sorted(shown(0)), client_b=lambda: sorted(shown(1)))
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
    parser.add_argument("--wine", type=Path, action="append",
                        help="Wine prefix, one per client: run the Windows executable under Wine")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
