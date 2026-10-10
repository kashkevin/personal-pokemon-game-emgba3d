"""The launcher's player runtime starts the native game (Milestone B3).

One player, the real world server with the ownership store, an unchanged
companion, and the launcher's own `PlayerRuntime` with a native runtime bundle
(`scripts/windows-runtime/collect_native_bundle.py`): no emulator and no Lua
bridge. Ordinary key presses on the game's own X display drive it.

    1. The player's legacy save is provisioned on the host and enrolled
       through a native game started directly (revision 1), as
       native_checkpoint_proof.py does; that game is closed.
    2. `PlayerRuntime.open()` verifies the pinned bundle and the ROM build it
       names, closed-game recovery installs the canonical save, and the native
       game starts with --save, --bridge (a private bridge.txt holding only the
       companion's port and token) and --config (the settings file beside the
       launch folders).
    3. The launched game's bridge authenticates, Continue reaches the
       overworld at the canonical position, and a live checkpoint through it
       makes revision 2.
    4. The game is closed: the save lease is released and the settings file
       stays for the next start.
    5. A bundle naming another ROM build is refused before any process starts.
    6. The host store passes its integrity check; the source save is unchanged.

    PYTHONPATH=src python scripts/multiplayer/native_launcher_proof.py \\
        --game ../engine/pokeemerald-mp.exe --sdl SDL2.dll --rom pokedev.gba \\
        --manifest manifest.json --save a.sav --display :98 --wine PREFIX \\
        --output /private/multiplayer-proof/native-launcher-1
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows-runtime"))
from collect_native_bundle import collect  # noqa: E402
from native_presence_proof import _hold, _screenshot  # noqa: E402
from emerald_multiplayer.checkpoint_client import CheckpointClient  # noqa: E402
from emerald_multiplayer.checkpoint_mirror import MirrorLease  # noqa: E402
from emerald_multiplayer.companion import Companion, CompanionConfig  # noqa: E402
from emerald_multiplayer.flash import inspect_flash  # noqa: E402
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator  # noqa: E402
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE  # noqa: E402
from emerald_multiplayer.trade_storage import TradeCheckpointStore  # noqa: E402
from emerald_multiplayer import player_runtime  # noqa: E402
from emerald_multiplayer.player_runtime import PlayerRuntime, PlayerRuntimeError, RuntimeBundle, SETTINGS_NAME  # noqa: E402
from emerald_multiplayer.server import ServerConfig, WorldServer  # noqa: E402


def _position(p) -> tuple[int, int, int, int]:
    return p.map_group, p.map_number, p.x, p.y


async def run(args: argparse.Namespace) -> None:
    root = args.output.resolve()
    if "/multiplayer-proof/" not in str(root) + "/" or root.exists():
        raise ValueError("choose a new private multiplayer-proof output directory")
    root.mkdir(mode=0o700, parents=True)
    manifest = json.loads(args.manifest.read_text())
    rom_sha256 = hashlib.sha256(args.rom.read_bytes()).hexdigest()
    if rom_sha256 != manifest["rom_sha256"]:
        raise ValueError("ROM differs from its manifest")
    source = args.save.read_bytes()
    bundle_info = collect(args.game, args.sdl, args.rom, root / "application" / "runtime")
    bundle = RuntimeBundle(Path(bundle_info["directory"]), bundle_info["manifest_sha256"])
    evidence = dict(scope="the launcher's PlayerRuntime starts the native game from a native runtime bundle",
                    bundle=bundle_info, game_sha256=hashlib.sha256(args.game.read_bytes()).hexdigest(),
                    build_id=rom_sha256, wine=bool(args.wine), checks=[], passed=False,
                    source=dict(path=str(args.save), sha256=hashlib.sha256(source).hexdigest()))

    def record(name: str, **fields) -> None:
        row = dict(verified=name, **fields)
        evidence["checks"].append(row)
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps(row), flush=True)

    # The child inherits the proof's environment, as the launcher's would.
    os.environ.update(DISPLAY=args.display, SDL_AUDIODRIVER="dummy")
    if args.wine:
        os.environ.update(WINEPREFIX=str(args.wine), WINEDEBUG="-all")
    # The launcher's host world: the trade-capable ownership store (host_world.py).
    store = TradeCheckpointStore(root / "world.sqlite3", manifest["rom_sha256"], manifest["ruleset_id"],
                                 OWNERSHIP_PROFILE)
    identity = store.create_player("Native L")
    store.enroll_player(identity.player_id, source)
    server = WorldServer(ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"],
                                      heartbeat_interval=.2, idle_timeout=12), store=store,
                         development_trades=True)
    await server.start(port=0)
    private = root / "launcher" / "players" / identity.player_id
    private.mkdir(mode=0o700, parents=True)
    companion = Companion(CompanionConfig(args.rom, args.manifest, identity.player_id, identity.display_name,
                                          secrets.token_bytes(32), server_port=server.address[1], ipc_port=0,
                                          server_credential=identity.credential))
    coordinator = LiveCheckpointCoordinator(companion, private)
    loop = asyncio.get_running_loop()
    direct = None

    async def wait_for(name, condition, timeout, quiet=False, **fields):
        deadline = loop.time() + timeout
        while not condition():
            if loop.time() >= deadline:
                await asyncio.to_thread(_screenshot, args.display, root / "timeout.png")
                raise AssertionError(f"{name}: timed out; " + json.dumps(
                    dict(connected=companion.connected, bridge=companion._bridge is not None,
                         error=companion.last_error)))
            await asyncio.sleep(.25)
        if not quiet:
            record(name, **{k: (v() if callable(v) else v) for k, v in fields.items()})

    def in_overworld():
        pose = companion._local_pose
        return pose is not None and pose.activity == 1

    async def press(key, seconds=None):
        await asyncio.to_thread(_hold, args.display, key, args.hold if seconds is None else seconds)

    async def boot(phase):
        await wait_for(f"{phase}: the game's bridge authenticated to the companion",
                       lambda: companion._bridge is not None, 90)
        await asyncio.sleep(10 * args.slow)
        await press("Return")
        await asyncio.sleep(4 * args.slow)
        await press("Return")
        await asyncio.sleep(8 * args.slow)
        await press("z")
        for _ in range(10):
            if in_overworld():
                break
            await asyncio.sleep(4)
            if not in_overworld():
                await press("z")
        await wait_for(f"{phase}: the game is in the overworld (its bridge's own pose)", in_overworld, 20,
                       position=lambda: _position(companion._local_pose))
        await wait_for(f"{phase}: the bridge announced the live-save mailbox and the 4 KiB save window",
                       lambda: companion._bridge.save_capable and companion._bridge.window_capable, 30)

    async def settle(seconds=1.5):
        current, since = _position(companion._local_pose), loop.time()
        while True:
            await asyncio.sleep(.1)
            if _position(companion._local_pose) != current:
                current, since = _position(companion._local_pose), loop.time()
            elif loop.time() - since >= seconds:
                return current

    def stop_direct():
        if direct is not None and direct.poll() is None:
            direct.terminate()
            try:
                direct.wait(15)
            except subprocess.TimeoutExpired:
                direct.kill()
                direct.wait(5)

    try:
        await companion.start()
        await wait_for("the companion joined the world server with the player's credentials",
                       lambda: companion.connected, 30, epoch=lambda: companion.session_epoch)

        # 1. Enrollment through a directly started native game (not the launcher).
        enroll_save = root / "enroll.sav"
        enroll_save.write_bytes(source)
        bridge = root / "enroll-bridge.txt"
        bridge.write_text(f"port={companion.ipc_address[1]}\ntoken={companion.config.token.hex()}\n")
        bridge.chmod(0o600)
        # The bundle's copy, which has its SDL2.dll beside it.
        command = [str(bundle.directory / args.game.name), "--save", str(enroll_save), "--bridge", str(bridge)]
        if args.wine:
            command = ["wine"] + command
        with MirrorLease(enroll_save), (root / "enroll.log").open("wb") as log:
            direct = subprocess.Popen(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
            await boot("enrollment game")
            live = await settle()
            receipt = await coordinator.enroll()
            record("legacy save enrolled through a directly started native game",
                   revision=receipt.metadata["revision"], position=live)
            stop_direct()
            await wait_for("enrollment game closed: the companion lost its bridge",
                           lambda: companion._bridge is None, 30, exit_code=direct.returncode)
        direct = None
        # A closed game's lease is never reused (companion.py): the launcher
        # starts the next game once the companion holds a new one.
        epoch = companion.session_epoch
        await wait_for("the companion rejoined the world server with a new lease",
                       lambda: companion.connected and companion.session_epoch not in (None, epoch), 60,
                       epoch=lambda: companion.session_epoch)

        # 2-4. The launcher's PlayerRuntime with the native bundle.
        save = private / "character.sav"
        launches = root / "launcher" / "launches"
        runtime = PlayerRuntime(companion, bundle, private, save, launch_root=launches)
        real_spawn = asyncio.create_subprocess_exec
        spawned = []

        async def spawn(program, *arguments, **options):
            spawned.append([program, *arguments])
            if args.wine:
                return await real_spawn("wine", program, *arguments, **options)
            return await real_spawn(program, *arguments, **options)

        with patch.object(player_runtime.asyncio, "create_subprocess_exec", spawn):
            async with runtime.open() as game:
                arguments = spawned[0]
                launch = Path(arguments[4]).parent
                record("the launcher started the native game with its save, bridge file and settings file",
                       arguments=[Path(arguments[0]).name, *arguments[1::2]],
                       executable_in_bundle=Path(arguments[0]).parent == bundle.directory.resolve(),
                       save_is_profile_save=Path(arguments[2]) == save.resolve(),
                       bridge_file=Path(arguments[4]).name, bridge_in_launch_folder=launch.parent == launches.resolve(),
                       bridge_lines=[line.split("=")[0] for line in Path(arguments[4]).read_text().splitlines()],
                       settings=str(Path(arguments[6]).relative_to(root)),
                       canonical_installed=hashlib.sha256(save.read_bytes()).hexdigest()
                       == game.startup.mirror.sha256)
                await boot("launched game")
                position = _position(companion._local_pose)
                canonical = inspect_flash(save.read_bytes(), save_profile=OWNERSHIP_PROFILE)
                assert position == _position(canonical.metadata), (position, _position(canonical.metadata))
                record("Continue restored the canonical position in the launched game", position=position)
                await asyncio.to_thread(_screenshot, args.display, root / "launched.png")
                live = await settle()
                started = loop.time()
                receipt = await coordinator.checkpoint(expected_revision=1)
                seconds = round(loop.time() - started, 2)
                downloaded = await CheckpointClient(companion).download()
                saved = inspect_flash(downloaded.payload, save_profile=OWNERSHIP_PROFILE)
                assert receipt.metadata["revision"] == 2 and _position(saved.metadata) == live
                record("live checkpoint through the launched game's bridge", revision=2, seconds=seconds,
                       position=live)
                game.process.terminate()
                code = await game.wait()
                await wait_for("launched game closed: the companion lost its bridge",
                               lambda: companion._bridge is None, 30, exit_code=code)
        settings = launches.resolve().parent / SETTINGS_NAME
        with MirrorLease(save):
            pass
        assert settings.is_file(), settings
        record("save lease released; the settings file stays beside the launch folders",
               settings_lines=len(settings.read_text().splitlines()))

        # 5. A bundle naming another ROM build never starts.
        other = collect(args.game, args.sdl, args.save, root / "application" / "other-runtime")
        refused = PlayerRuntime(companion, RuntimeBundle(Path(other["directory"]), other["manifest_sha256"]),
                                private, save, launch_root=launches)
        before = len(spawned)
        with patch.object(player_runtime.asyncio, "create_subprocess_exec", spawn):
            try:
                async with refused.open():
                    raise AssertionError("a game of another ROM build started")
            except PlayerRuntimeError as error:
                assert error.code == "game_changed", error.code
        assert len(spawned) == before
        record("a bundle naming another ROM build was refused before any process started", code="game_changed")

        store.integrity_check()
        assert hashlib.sha256(args.save.read_bytes()).hexdigest() == evidence["source"]["sha256"]
        record("host store integrity check passed; source save unchanged")
        evidence["passed"] = True
        record("passed")
    finally:
        stop_direct()
        await companion.close()
        await server.close()
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True, help="the native game's .exe (bridge and --config)")
    parser.add_argument("--sdl", type=Path, required=True, help="its SDL2.dll")
    parser.add_argument("--rom", type=Path, required=True, help="GBA ROM of the same engine source")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--save", type=Path, required=True, help="the player's legacy save (read only)")
    parser.add_argument("--display", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wine", type=Path, help="Wine prefix to run the .exe in (Linux)")
    parser.add_argument("--hold", type=float, default=.5, help="seconds each key is held")
    parser.add_argument("--slow", type=float, default=1.0, help="stretch the start-up waits")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
