"""Native game clients (no emulator): live checkpoints into the host's ownership store.

Two copies of the native executable (engine `src/platform/mp_bridge.c`) connect
to unchanged companions and an unchanged world server that keeps the ownership
store, as four_player_proof.py does for mGBA cores. Only ordinary key presses
drive the games (xdotool on their own X displays); every save byte moves
through the ROM's own save mailbox and 4 KiB save window, which the native
bridge serves from the executable's memory.

    1. Each player's legacy save is provisioned on the host, then enrolled
       through the running game (revision 1).
    2. Player A walks, then saves again (revision 2): the canonical save holds
       the position A's running game reported.
    3. Both games are closed. Each game's own save file holds its canonical
       player state.
    4. Both games are started again from those files: Continue restores the
       saved map and position, the companions rejoin the host with new leases,
       the players see each other again, and both save once more against
       their last revision (A revision 3, B revision 2).
    5. With --recover: A walks without saving, then the canonical save is
       applied to A's running game (the save mailbox's write path: 1024 staged
       128-byte chunks, commit, read-back); A's game is back at the saved
       position without a restart or a new lease.
    6. The host store passes its integrity check; the source saves are unchanged.

    PYTHONPATH=src python scripts/multiplayer/native_checkpoint_proof.py \\
        --game ../engine/pokeemerald-mp --rom ../engine/pokedev.gba \\
        --manifest manifest.json --save a.sav --save b.sav \\
        --display :98 --display :97 --output /private/multiplayer-proof/native-checkpoint-1
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess

from native_presence_proof import _focus, _hold, _screenshot, _xdotool
from emerald_multiplayer.checkpoint_client import CheckpointClient
from emerald_multiplayer.checkpoint_mirror import MirrorLease
from emerald_multiplayer.companion import Companion, CompanionConfig
from emerald_multiplayer.flash import inspect_flash
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, inspect_ownership
from emerald_multiplayer.ownership_storage import OwnershipCheckpointStore
from emerald_multiplayer.server import ServerConfig, WorldServer


def _position(metadata_or_pose) -> tuple[int, int, int, int]:
    p = metadata_or_pose
    return p.map_group, p.map_number, p.x, p.y


async def run(args: argparse.Namespace) -> None:
    root = args.output.resolve()
    if "/multiplayer-proof/" not in str(root) + "/" or root.exists():
        raise ValueError("choose a new private multiplayer-proof output directory")
    count = len(args.save)
    if count != 2 or len(args.display) != count:
        raise ValueError("two saves, one X display each")
    root.mkdir(mode=0o700, parents=True)
    manifest = json.loads(args.manifest.read_text())
    if hashlib.sha256(args.rom.read_bytes()).hexdigest() != manifest["rom_sha256"]:
        raise ValueError("ROM differs from its manifest")
    game = args.game.resolve()
    source_bytes = [p.read_bytes() for p in args.save]
    source_metadata = [inspect_flash(b).metadata for b in source_bytes]
    if len({m.trainer_id for m in source_metadata}) != count:
        raise ValueError("source trainers must be distinct")
    evidence = dict(scope="native clients through the native bridge: live checkpoints into the ownership store",
                    game_sha256=hashlib.sha256(game.read_bytes()).hexdigest(),
                    build_id=manifest["rom_sha256"], engine_commit=manifest.get("engine_commit"),
                    wine=bool(args.wine), hold=args.hold, slow=args.slow, recover=args.recover,
                    sources=[dict(path=str(p), sha256=hashlib.sha256(b).hexdigest())
                             for p, b in zip(args.save, source_bytes)],
                    checks=[], passed=False)

    def record(name: str, **fields) -> None:
        row = dict(verified=name, **fields)
        evidence["checks"].append(row)
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps(row), flush=True)

    store = OwnershipCheckpointStore(root / "world.sqlite3", manifest["rom_sha256"], manifest["ruleset_id"])
    identities = [store.create_player(f"Native {'AB'[i]}") for i in range(count)]
    for identity, payload in zip(identities, source_bytes):
        store.enroll_player(identity.player_id, payload)
    server = WorldServer(ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"],
                                      heartbeat_interval=.2, idle_timeout=12), store=store)
    await server.start(port=0)
    saves = [root / f"client-{i}.sav" for i in range(count)]
    bridges = [root / f"bridge-{i}.txt" for i in range(count)]
    companions: list[Companion] = []
    coordinators: list[LiveCheckpointCoordinator] = []
    processes: list[subprocess.Popen | None] = [None] * count
    leases: list[MirrorLease | None] = [None] * count
    revisions = [0] * count
    canonical: list = [None] * count
    loop = asyncio.get_running_loop()
    # A slow client (Wine, the 3D build on software OpenGL, several games on
    # two cores) may run one main-loop pass in more than 150 ms; a shorter
    # press is then lost between frames.
    default_hold = args.hold if args.hold is not None else .5 if args.wine else .15

    def launch(i: int, generation: int) -> None:
        lease = MirrorLease(saves[i])
        lease.__enter__()
        leases[i] = lease
        log = (root / f"client-{i}-{generation}.log").open("wb")
        command = [str(game), "--save", str(saves[i]), "--bridge", str(bridges[i])]
        environment = dict(os.environ, DISPLAY=args.display[i], SDL_AUDIODRIVER="dummy")
        if args.wine:
            # One prefix (wineserver) per client: see native_presence_proof.py.
            command = ["wine"] + command
            environment.update(WINEPREFIX=str(args.wine[i % len(args.wine)]), WINEDEBUG="-all")
        processes[i] = subprocess.Popen(command, cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT)

    def close_games() -> list[int | None]:
        codes = []
        for process in processes:
            if process is not None and process.poll() is None:
                process.terminate()  # SDL turns SIGTERM into an ordinary quit
        for i, process in enumerate(processes):
            if process is not None:
                try:
                    process.wait(15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(5)
                codes.append(process.returncode)
                processes[i] = None
            if leases[i] is not None:
                leases[i].__exit__(None, None, None)
                leases[i] = None
        return codes

    async def wait_for(name: str, condition, timeout: float, quiet: bool = False, **fields) -> None:
        deadline = loop.time() + timeout
        while not condition():
            if any(p is not None and p.poll() is not None for p in processes):
                raise AssertionError(f"{name}: a client exited ({[p and p.poll() for p in processes]})")
            if loop.time() >= deadline:
                for i, display in enumerate(args.display):
                    await asyncio.to_thread(_screenshot, display, root / f"timeout-{i}.png")
                raise AssertionError(f"{name}: timed out; " + json.dumps(
                    [dict(connected=c.connected, bridge=c._bridge is not None, error=c.last_error) for c in companions]))
            await asyncio.sleep(.25)
        if not quiet:
            record(name, **{k: (v() if callable(v) else v) for k, v in fields.items()})

    async def press(key: str, seconds: float | None = None, clients=None) -> None:
        seconds = default_hold if seconds is None else seconds
        await asyncio.gather(*(asyncio.to_thread(_hold, args.display[i], key, seconds)
                               for i in (clients if clients is not None else range(count))))

    def in_overworld(i: int) -> bool:
        pose = companions[i]._local_pose
        return pose is not None and pose.activity == 1

    def overworld_peers(i: int) -> int:
        return sum(1 for p in companions[i].snapshot.peers if p.pose.activity == 1)

    def save_ready(c: Companion) -> bool:
        b = c._bridge
        return c.connected and b is not None and b.save_capable and b.window_capable

    async def boot(phase: str) -> None:
        await wait_for(f"{phase}: native bridges authenticated to their companions",
                       lambda: all(c._bridge is not None for c in companions), 90)
        await wait_for(f"{phase}: companions joined the world server with their credentials",
                       lambda: all(c.connected for c in companions) and len(server.sessions) == count, 30,
                       epochs=lambda: [c.session_epoch for c in companions])
        # Title screen, main menu, Continue: the keys a player presses; A again
        # on any client whose own pose does not show the overworld yet.
        await asyncio.sleep(12 * args.slow)
        await press("Return")
        await asyncio.sleep(5 * args.slow)
        await press("Return")
        await asyncio.sleep(12 * args.slow)
        await press("z")
        for _ in range(12):
            waiting = [i for i in range(count) if not in_overworld(i)]
            if not waiting:
                break
            await asyncio.sleep(5)
            waiting = [i for i in range(count) if not in_overworld(i)]
            if waiting:
                await press("z", clients=waiting)
        await wait_for(f"{phase}: every client is in the overworld (its bridge's own pose)",
                       lambda: all(in_overworld(i) for i in range(count)), 20,
                       positions=lambda: [_position(companions[i]._local_pose) for i in range(count)])
        await wait_for(f"{phase}: every client sees the other in the overworld",
                       lambda: all(overworld_peers(i) == count - 1 for i in range(count)), 60)
        await wait_for(f"{phase}: each bridge announced the live-save mailbox and the 4 KiB save window",
                       lambda: all(save_ready(c) for c in companions), 30,
                       capabilities=lambda: [dict(save=c._bridge.save_capable, window=c._bridge.window_capable,
                                                  emergency=c._bridge.emergency_save_capable,
                                                  battle=c._bridge.battle_capable,
                                                  menu=c._bridge.menu_session is not None,
                                                  reset=c._bridge.reset_session is not None,
                                                  incarnation=c._bridge.incarnation) for c in companions])

    async def settle(i: int, seconds: float = 1.5, frames: int = 24) -> tuple[int, int, int, int]:
        """The position once the player has stopped walking: unchanged for
        `seconds` and for `frames` game frames (a step takes 16), so a slow
        game finishes its step before the save."""
        pose = companions[i]._local_pose
        current, since, since_frame = _position(pose), loop.time(), pose.frame
        while True:
            await asyncio.sleep(.1)
            pose = companions[i]._local_pose
            if _position(pose) != current:
                current, since, since_frame = _position(pose), loop.time(), pose.frame
            elif loop.time() - since >= seconds and (pose.frame - since_frame) % 2**32 >= frames:
                return current

    async def checkpoint(i: int, name: str, *, enroll: bool = False):
        live = await settle(i)
        started = loop.time()
        receipt = await (coordinators[i].enroll() if enroll
                         else coordinators[i].checkpoint(expected_revision=revisions[i]))
        seconds = round(loop.time() - started, 2)
        downloaded = await CheckpointClient(companions[i]).download()
        parsed = inspect_flash(downloaded.payload, save_profile=OWNERSHIP_PROFILE)
        owned = inspect_ownership(parsed)
        assert (owned.world_id, owned.player_id) == (store.metadata.world_id, identities[i].player_id)
        assert parsed.metadata.trainer_id == source_metadata[i].trainer_id
        assert receipt.metadata["revision"] == revisions[i] + 1, (receipt.metadata, revisions[i])
        assert downloaded.metadata == receipt.metadata
        assert _position(parsed.metadata) == live, (_position(parsed.metadata), live)
        revisions[i] = receipt.metadata["revision"]
        canonical[i] = (parsed, owned, downloaded)
        record(name, client=i, revision=revisions[i], seconds=seconds, trainer_id=parsed.metadata.trainer_id,
               saved_position=_position(parsed.metadata), live_position=live,
               ownership_records=len(owned.records), checkpoint_sha256=receipt.metadata["sha256"],
               state_sha256=parsed.state_sha256, lease_epoch=companions[i].session_epoch,
               incarnation=companions[i].save_incarnation)

    async def walk(i: int, directions=("Down", "Right", "Up", "Left")) -> tuple[int, int, int, int]:
        """Walk in the first open direction: the key is held until the client's
        own pose moves (a slow game needs seconds to turn and start a step).
        Returns the position before the walk."""
        before = await settle(i)
        for direction in directions:
            await asyncio.to_thread(_focus, args.display[i])
            await asyncio.to_thread(_xdotool, args.display[i], "keydown", direction)
            try:
                deadline = loop.time() + 8 * args.slow
                while _position(companions[i]._local_pose) == before and loop.time() < deadline:
                    await asyncio.sleep(.1)
            finally:
                await asyncio.to_thread(_xdotool, args.display[i], "keyup", direction)
            if _position(companions[i]._local_pose) != before:
                break
        return before

    async def compare_local_saves(phase: str) -> None:
        rows = []
        for i in range(count):
            local = saves[i].read_bytes()
            parsed_local = inspect_flash(local, save_profile=OWNERSHIP_PROFILE)
            parsed, owned, downloaded = canonical[i]
            assert parsed_local.state_sha256 == parsed.state_sha256, i
            assert inspect_ownership(parsed_local).records == owned.records, i
            assert _position(parsed_local.metadata) == _position(parsed.metadata), i
            rows.append(dict(client=i, size=len(local), sha256=hashlib.sha256(local).hexdigest(),
                             byte_identical_to_canonical=hashlib.sha256(local).hexdigest() == downloaded.metadata["sha256"],
                             state_sha256=parsed_local.state_sha256, position=_position(parsed_local.metadata)))
        record(f"{phase}: each game's own save file holds its canonical player state", saves=rows)

    try:
        for i, identity in enumerate(identities):
            saves[i].write_bytes(source_bytes[i])
            companion = Companion(CompanionConfig(args.rom, args.manifest, identity.player_id, identity.display_name,
                                                  secrets.token_bytes(32), server_port=server.address[1], ipc_port=0,
                                                  server_credential=identity.credential))
            await companion.start()
            companions.append(companion)
            coordinators.append(LiveCheckpointCoordinator(companion, root / f"private-{i}"))
            bridges[i].write_text(f"port={companion.ipc_address[1]}\ntoken={companion.config.token.hex()}\n")
            bridges[i].chmod(0o600)
            launch(i, 0)

        await boot("first start")
        for i, display in enumerate(args.display):
            await asyncio.to_thread(_screenshot, display, root / f"01-started-{i}.png")
        for i in range(count):
            await checkpoint(i, "legacy save enrolled through the running game", enroll=True)

        # A walks in whichever direction is open, then saves again.
        before = await walk(0)
        await wait_for("client A walked", lambda: _position(companions[0]._local_pose) != before, 10, before=before)
        await checkpoint(0, "checkpoint after walking holds the new position")
        for i, display in enumerate(args.display):
            await asyncio.to_thread(_screenshot, display, root / f"02-saved-{i}.png")

        # Close both games; the companions keep their host connections.
        epochs = [c.session_epoch for c in companions]
        incarnations = [c._bridge.incarnation for c in companions]
        await asyncio.sleep(2)
        codes = await asyncio.to_thread(close_games)
        await wait_for("games closed: the companions lost their bridges",
                       lambda: all(c._bridge is None for c in companions), 30, exit_codes=codes)
        await compare_local_saves("after closing")

        for i in range(count):
            launch(i, 1)
        await boot("restart")
        restored = [_position(companions[i]._local_pose) for i in range(count)]
        expected = [_position(canonical[i][0].metadata) for i in range(count)]
        assert restored == expected, (restored, expected)
        new_epochs = [c.session_epoch for c in companions]
        new_incarnations = [c._bridge.incarnation for c in companions]
        assert all(b > a for a, b in zip(epochs, new_epochs)), (epochs, new_epochs)
        assert all(b > a for a, b in zip(incarnations, new_incarnations)), (incarnations, new_incarnations)
        record("restart: Continue restored each saved map and position; new host leases and game incarnations",
               positions=restored, epochs_before=epochs, epochs_after=new_epochs,
               incarnations_before=incarnations, incarnations_after=new_incarnations)
        for i, display in enumerate(args.display):
            await asyncio.to_thread(_screenshot, display, root / f"03-restarted-{i}.png")
        for i in range(count):
            await checkpoint(i, "checkpoint after restart against the last revision")

        if args.recover:
            saved = _position(canonical[0][0].metadata)
            await walk(0, ("Up", "Left", "Right", "Down"))
            await wait_for("client A walked away from its saved position without saving",
                           lambda: _position(companions[0]._local_pose) != saved, 10, saved=saved)
            moved = await settle(0)
            pid, epoch, incarnation = processes[0].pid, companions[0].session_epoch, companions[0].save_incarnation
            started = loop.time()
            receipt = await coordinators[0].recover()
            seconds = round(loop.time() - started, 2)
            await wait_for("live recovery: A's running game is back at the saved position",
                           lambda: _position(companions[0]._local_pose) == saved, 60 * args.slow)
            assert processes[0].pid == pid and processes[0].poll() is None
            assert (companions[0].session_epoch, companions[0].save_incarnation) == (epoch, incarnation)
            assert receipt.normalized_state_sha256 == canonical[0][0].state_sha256
            assert receipt.revision == revisions[0]
            record("live recovery applied the canonical save to the running game (no restart, same lease)",
                   seconds=seconds, moved_position=moved, restored_position=saved, revision=receipt.revision,
                   state_sha256=receipt.normalized_state_sha256, game_pid_unchanged=True)
            for i, display in enumerate(args.display):
                await asyncio.to_thread(_screenshot, display, root / f"04-recovered-{i}.png")

        await asyncio.sleep(2)
        codes = await asyncio.to_thread(close_games)
        await wait_for("games closed again", lambda: all(c._bridge is None for c in companions), 30, exit_codes=codes)
        await compare_local_saves("final")
        assert revisions == [3, 2], revisions
        store.integrity_check()
        assert source_bytes == [p.read_bytes() for p in args.save]
        record("host store integrity check passed; source saves unchanged", revisions=revisions)
        evidence["passed"] = True
        record("passed")
    finally:
        close_games()
        for companion in companions:
            await companion.close()
        await server.close()
        store.close()


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
    parser.add_argument("--hold", type=float, help="seconds each key is held (default .15, Wine .5)")
    parser.add_argument("--slow", type=float, default=1.0, help="stretch the start-up waits (3D build: 1.5)")
    parser.add_argument("--recover", action="store_true",
                        help="also apply A's canonical save to its running game after unsaved walking "
                             "(about 1024 save commands: 35 s at 60 frames a second)")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
