"""Actual ordinary Continue, lost host, held export and exact fresh recovery.

Uses the official headless libmGBA harness, ordinary joypad input and production
mailboxes. Diagnostics only read Flash/party/state. No savestate or RAM edits.
"""
import argparse
import asyncio
from contextlib import suppress
import hashlib
import json
from pathlib import Path
import secrets

from configure_bridge import configure
from live_checkpoint_proof import LockedCore
from emerald_multiplayer.checkpoint_mirror import MirrorLease
from emerald_multiplayer.cold_start import ColdStartRecovery
from emerald_multiplayer.companion import Companion, CompanionConfig
from emerald_multiplayer.emergency_save import EmergencySaveController
from emerald_multiplayer.emergency_protocol import validate_emergency_manifest
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator
from emerald_multiplayer.trade_storage import TradeCheckpointStore
from emerald_multiplayer.save_mailbox import inspect_save_mailbox, Opcode, State
from emerald_multiplayer.server import WorldServer, ServerConfig


async def run(args):
    root = args.output.resolve()
    if root.exists() or "/multiplayer-proof/" not in str(root) + "/":
        raise ValueError("use a fresh private multiplayer-proof output")
    manifest = json.loads(args.manifest.read_text())
    validate_emergency_manifest(manifest, args.rom)
    if manifest["emergency_save_abi_version"] != 2:
        raise ValueError("complete emergency preservation requires ABI2")
    original = args.save.read_bytes()
    root.mkdir(mode=0o700, parents=True)
    rom, manifest_path, save = root / "game.gba", root / "manifest.json", root / "character.sav"
    rom.write_bytes(args.rom.read_bytes())
    manifest_path.write_bytes(args.manifest.read_bytes())
    if hashlib.sha256(rom.read_bytes()).hexdigest() != manifest["rom_sha256"]:
        raise ValueError("frozen ROM does not match manifest")
    bridge_source = args.bridge.read_text()
    (root / "bridge-source.lua").write_text(bridge_source)
    (root / "controller.py").write_bytes(Path(__file__).read_bytes())
    evidence = dict(scope="one actual headless core, authenticated development loopback, ordinary Continue and exact host-loss preservation/rejoin; not Windows or four-client acceptance",
                    engine_commit=manifest["engine_commit"], rom_sha256=manifest["rom_sha256"],
                    source_sha256=hashlib.sha256(original).hexdigest(),
                    bridge_sha256=hashlib.sha256(bridge_source.encode()).hexdigest(),
                    harness_sha256=hashlib.sha256(args.harness.read_bytes()).hexdigest(), checks=[], passed=False)
    def record(name, **fields):
        value = dict(name=name, **fields)
        evidence["checks"].append(value)
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps(value), flush=True)
    store = TradeCheckpointStore(root / "world.sqlite3", manifest["rom_sha256"], manifest["ruleset_id"])
    player = store.create_player("Emergency proof")
    store.enroll_player(player.player_id, original)
    server = WorldServer(ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"], heartbeat_interval=.2, idle_timeout=8), store=store)
    companions = []
    core = pump = None
    pump_stop = asyncio.Event()
    generation = 0
    private = root / "private"

    async def companion():
        c = Companion(CompanionConfig(rom, manifest_path, player.player_id, player.display_name, secrets.token_bytes(32),
            server_host="127.0.0.1", server_port=server.address[1], server_credential=player.credential,
            ipc_port=0, reconnect_delay=.25, remote_timeout=8))
        companions.append(c)
        await c.start()
        async with asyncio.timeout(12):
            while not c.connected:
                await asyncio.sleep(.02)
        return c

    async def launch(c):
        nonlocal core, generation
        generation += 1
        script = root / f"bridge-{generation}.lua"
        script.write_text(configure(manifest, c.config.token.hex(), c.ipc_address[1], bridge_source))
        process = await asyncio.create_subprocess_exec(str(args.harness), str(rom), str(save), str(script),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        core = LockedCore(process, root / f"core-{generation}.log")
        if not (await asyncio.wait_for(process.stdout.readline(), 20)).startswith(b"READY"):
            raise RuntimeError("native core did not start")
        for keys, frames in ((0, 1000), (8, 8), (0, 480), (8, 8), (0, 180), (1, 8), (0, 300)):
            for offset in range(0, frames, 24):
                await core.command(f"F {keys:x} {min(24, frames-offset)}")
                await asyncio.sleep(.003)
        async with asyncio.timeout(12):
            while not (c._bridge and c._bridge.save_capable and c._bridge.emergency_save_capable and c._bridge.window_capable):
                await core.command("F 0 6")
                await asyncio.sleep(.02)
        assert c._local_pose.activity == 1

    async def pumping():
        while not pump_stop.is_set():
            await core.command("F 0 6")
            await asyncio.sleep(.005)

    def start_pump():
        nonlocal pump
        pump_stop.clear()
        pump = asyncio.create_task(pumping())

    async def stop_pumping():
        nonlocal pump
        if pump is not None:
            pump_stop.set()
            await pump
            pump = None

    async def stop_core():
        nonlocal core, pump
        await stop_pumping()
        if core is not None:
            await core.command("Q")
            code = await asyncio.wait_for(core.process.wait(), 15)
            assert code == 0
            await core.logs
            core = None

    async def diagnostic(c):
        party = await core.read(manifest["debug_parties_address"], manifest["debug_party_size"])
        mailbox = inspect_save_mailbox(await core.read(manifest["save_mailbox_address"], 512))
        pose = c._local_pose
        return dict(party_sha256=hashlib.sha256(party).hexdigest(), state=int(mailbox.state),
                    position=[pose.map_group, pose.map_number, pose.x, pose.y])

    try:
        await server.start(port=0)
        first = await companion()
        with MirrorLease(save):
            save.write_bytes(original)
            await launch(first)
            start_pump()
            enrolled = await LiveCheckpointCoordinator(first, private).enroll()
            assert enrolled.metadata["revision"] == 1
            await stop_core()
        await first.close()
        record("ordinary-native-enrollment", revision=1)
        c = await companion()
        async with ColdStartRecovery(c, private, save).open() as startup:
            assert startup.mirror.revision == 1
            await launch(c)
            start_pump()
            controller = EmergencySaveController(c, private)
            await controller.arm(1)
            old_epoch = c.session_epoch
            before = await diagnostic(c)
            save_before = hashlib.sha256(save.read_bytes()).hexdigest()
            ordinary = None
            promoted_bytes = promoted_operation = None
            if args.interrupt_export:
                ordinary = asyncio.create_task(LiveCheckpointCoordinator(c, private).checkpoint(expected_revision=1))
                async with asyncio.timeout(20):
                    while not any(command.opcode == Opcode.READ_WINDOW and command.offset >= 4096
                                  for command, _ in c._save_pending.values()):
                        if ordinary.done():
                            raise RuntimeError("ordinary export completed before controlled interruption")
                        await asyncio.sleep(.001)
                await stop_pumping()
                promoted_operation = controller.active_export[0]
                native = root / "ordinary-frozen.flash"
                assert (await core.command(f"D {native}")).startswith("FLASH OK 131072 ")
                promoted_bytes = native.read_bytes()
            await server.close()
            if ordinary is not None:
                start_pump()
                interrupted = await asyncio.gather(ordinary, return_exceptions=True)
                assert isinstance(interrupted[0], Exception)
            await asyncio.wait_for(controller.lost.wait(), 15)
            result = await asyncio.wait_for(controller.drain(), 60)
            assert result.can_close and result.state == "preserved", result
            assert not c.connected and c._reconnect_blocked
            after = await diagnostic(c)
            assert after["state"] == State.EMERGENCY_PRESERVED
            assert before["party_sha256"] == after["party_sha256"]
            clone = root / "native-preserved.flash"
            assert (await core.command(f"D {clone}")).startswith("FLASH OK 131072 ")
            preserved = (private / (result.operation_id + ".flash")).read_bytes()
            assert clone.read_bytes() == preserved
            if ordinary is not None:
                assert result.operation_id == promoted_operation and preserved == promoted_bytes
                record("interrupted-ordinary-export-promoted-with-identical-uuid-and-flash", operation_id=result.operation_id)
            # The ROM's ordinary serializer legitimately writes its mapped
            # Flash. The launcher never replaces this open save file.
            native_save_after = hashlib.sha256(save.read_bytes()).hexdigest()
            # No watchdog or ordinary joypad may release this preserved core.
            for _ in range(80):
                await core.command("F 10 24")
                await asyncio.sleep(.002)
            later = await diagnostic(c)
            assert later["state"] == State.EMERGENCY_PRESERVED
            assert later["party_sha256"] == after["party_sha256"]
            assert later["position"] == after["position"]
            record("host-loss-preserved-exact-native-flash-and-held-past-watchdog", operation_id=result.operation_id,
                   sha256=result.sha256, old_lease=old_epoch, before=before, after=later,
                   native_file_before=save_before, native_file_after=native_save_after)
            await stop_core()
        await c.close()
        await server.start(port=0)
        fresh = await companion()
        async with ColdStartRecovery(fresh, private, save).open() as startup:
            assert startup.mirror.revision == 2
            assert fresh.session_epoch > old_epoch
            assert save.read_bytes() == preserved
            await launch(fresh)
            state = await diagnostic(fresh)
            assert state["party_sha256"] == after["party_sha256"]
            assert not (private / "pending-export.json").exists()
            assert not (private / "pending-emergency.json").exists()
            record("fresh-authenticated-Continue-reconciled-exact-candidate", revision=2,
                   lease=fresh.session_epoch, party_sha256=state["party_sha256"])
            await stop_core()
        await fresh.close()
        assert args.save.read_bytes() == original
        store.integrity_check()
        evidence["passed"] = True
        record("original-private-source-unchanged-and-store-integrity-valid")
    except BaseException as error:
        evidence["failure"] = dict(type=type(error).__name__, message=str(error))
        record("failed-run-retained")
        raise
    finally:
        await stop_core()
        await asyncio.gather(*(c.close() for c in companions), return_exceptions=True)
        await server.close()
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rom", "manifest", "harness", "save", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--bridge", type=Path, default=Path(__file__).parents[2] / "bridge/mgba.lua")
    parser.add_argument("--interrupt-export", action="store_true")
    asyncio.run(run(parser.parse_args()))
