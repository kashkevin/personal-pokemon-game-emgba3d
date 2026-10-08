"""Two real ROMs: live checkpoint, isolated staging faults, and live recovery.

Joypad input drives gameplay. The production Lua bridge writes only allocated
mailboxes; the official core's read-only Flash clone is diagnostic evidence.
All output lives in a new private multiplayer-proof directory.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import secrets
import struct
import time
from unittest.mock import patch
from uuid import uuid4
import zlib

from control_proof import Core, objects, verify_expected
from configure_bridge import configure
from emerald_multiplayer.checkpoint_client import CheckpointClient
from emerald_multiplayer.checkpoint_mirror import MirrorLease
from emerald_multiplayer.companion import Companion, CompanionConfig
from emerald_multiplayer.flash import LAYOUT_ID, inspect_flash
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator, LiveSaveError
from emerald_multiplayer.mailbox import inspect_mailbox
from emerald_multiplayer.save_mailbox import Opcode, SaveControl, State, Status, inspect_save_mailbox
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.storage import CheckpointStore


class LockedCore(Core):
    def __init__(self, process, log):
        super().__init__(process, log)
        self.command_lock = asyncio.Lock()

    async def command(self, command):
        async with self.command_lock:
            return await super().command(command)


class Pump:
    def __init__(self, cores, companions):
        self.cores, self.companions = cores, companions
        self.keys = [0] * len(cores)
        self.frames = 0
        self.visited_b = set()
        self.task = None
        self.wander_task = None

    async def _run(self):
        while True:
            await asyncio.gather(*(core.command(f"F {key:x} 6") for core, key in zip(self.cores, self.keys)))
            self.frames += 6
            pose = self.companions[1]._local_pose
            if pose is not None and pose.activity:
                self.visited_b.add((pose.x, pose.y))
            await asyncio.sleep(.003)

    def start(self):
        self.task = asyncio.create_task(self._run(), name="two-real-ROM-frame-pump")

    async def advance(self, count):
        target = self.frames + count
        while self.frames < target:
            if self.task.done():
                await self.task
            await asyncio.sleep(.005)

    async def press(self, client, keys, count=18, release=30):
        self.keys[client] = keys
        await self.advance(count)
        self.keys[client] = 0
        await self.advance(release)

    async def _wander(self):
        while True:
            await self.press(1, 32, 18, 24)
            await self.press(1, 16, 18, 24)

    def wander(self):
        self.wander_task = asyncio.create_task(self._wander(), name="other-player-independent-movement")

    async def stop_wander(self):
        if self.wander_task is not None:
            self.wander_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.wander_task
            self.wander_task = None
        self.keys[1] = 0
        await self.advance(60)

    async def close(self):
        if self.wander_task is not None:
            self.wander_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.wander_task
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task


async def run(args):
    root = args.output.resolve()
    if "/multiplayer-proof/" not in str(root) + "/" or root.exists():
        raise ValueError("choose a new private multiplayer-proof output directory")
    root.mkdir(mode=0o700, parents=True)
    manifest = json.loads(args.manifest.read_text())
    if manifest.get("save_mailbox_size") != 512:
        raise ValueError("this proof requires the newly verified live-save ROM")
    store = CheckpointStore(root / "world.sqlite3", manifest["rom_sha256"], manifest["ruleset_id"], LAYOUT_ID)
    identities = [store.create_player("Live " + label) for label in ("A", "B")]
    (root / "profiles.json").write_text(json.dumps([{"player_id": p.player_id, "display_name": p.display_name, "credential": p.credential.hex()} for p in identities]))
    server = WorldServer(ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"], heartbeat_interval=.2, idle_timeout=5), store=store)
    await server.start(port=0)
    cores, companions, leases = [], [], []
    pump = None
    evidence = {"build_id": manifest["rom_sha256"], "engine_commit": manifest["engine_commit"],
                "ruleset_id": manifest["ruleset_id"], "save_profile": LAYOUT_ID,
                "scope": "two actual running cores with live Flash mailbox", "checks": [], "snapshots": []}

    def record(name, **fields):
        evidence["checks"].append({"name": name, **fields})
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps({"verified": name, **fields}), flush=True)

    async def wait_ready():
        for _ in range(300):
            if all(c.connected and c._bridge is not None and c._bridge.save_capable for c in companions):
                return
            await asyncio.sleep(.02)
        raise AssertionError([(c.connected, c.last_error) for c in companions])

    async def boot():
        async def frames(count, keys=0, repeat=1):
            for _ in range(repeat):
                await asyncio.gather(*(c.command(f"F {keys:x} {count}") for c in cores))
                await asyncio.sleep(.02)
        await frames(50, repeat=20)
        await frames(8, 8)
        await frames(48, repeat=10)
        await frames(8, 8)
        await frames(6, repeat=30)
        await frames(8, 1)
        await frames(6, repeat=50)

    async def launch(i, save):
        lease = MirrorLease(save)
        lease.__enter__()
        leases.append(lease)
        companion = companions[i]
        script = root / f"bridge-{i}.lua"
        script.write_text(configure(manifest, companion.config.token.hex(), companion.ipc_address[1], args.bridge.read_text()))
        process = await asyncio.create_subprocess_exec(str(args.harness), str(args.rom), str(save), str(script),
                  stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        core = LockedCore(process, root / f"core-{i}-{len(evidence['snapshots'])}.log")
        cores.append(core)
        ready = await asyncio.wait_for(process.stdout.readline(), 20)
        if not ready.startswith(b"READY"):
            raise RuntimeError(f"game failed to launch; inspect {core.log}")

    async def clone(label, index=0):
        destination = root / f"{label}-{index}.flash"
        response = await cores[index].command(f"D {destination}")
        if not response.startswith("FLASH OK 131072 "):
            raise AssertionError(response)
        return destination.read_bytes()

    async def snapshot(label):
        result = {"clients": []}
        for i, core in enumerate(cores):
            pose, inbound = inspect_mailbox(await core.read(manifest["mailbox_address"], 128))
            save_state = inspect_save_mailbox(await core.read(manifest["save_mailbox_address"], 512))
            raw = await core.read(manifest["debug_object_events_address"], manifest["debug_object_events_size"])
            sprites = await core.read(manifest["debug_sprites_address"], manifest["debug_sprites_size"])
            party = await core.read(manifest["debug_parties_address"], manifest["debug_party_size"])
            sb1 = int.from_bytes(await core.read(manifest["debug_save_block1_ptr_address"], 4), "little")
            saved = await core.read(sb1 + manifest["debug_saved_objects_offset"], 576)
            sb2 = int.from_bytes(await core.read(manifest["debug_save_block2_ptr_address"], 4), "little")
            play_time = await core.read(sb2 + manifest["debug_play_time_offset"], manifest["debug_play_time_size"])
            result["clients"].append({"pose": asdict(pose), "inbound": asdict(inbound), "save_state": int(save_state.state),
                "objects": objects(raw, sprites), "party_sha256": hashlib.sha256(party).hexdigest(),
                "play_time_hex": play_time.hex(),
                "saved_object_local_ids": [saved[j * 36 + 8] for j in range(16)], "server_connected": companions[i].connected,
                "core_pid": core.process.pid, "lease_epoch": companions[i].session_epoch})
            await core.command(f"P {root / (label + '-' + str(i) + '.png')}")
        evidence["snapshots"].append({"label": label, **result})
        return result

    try:
        saves = [root / "client-a.sav", root / "client-b.sav"]
        original = [args.save_a.read_bytes(), args.save_b.read_bytes()]
        for i, identity in enumerate(identities):
            saves[i].write_bytes(original[i])
            config = CompanionConfig(args.rom, args.manifest, identity.player_id, identity.display_name, secrets.token_bytes(32),
                                     server_port=server.address[1], ipc_port=0, server_credential=identity.credential)
            companion = Companion(config)
            await companion.start()
            companions.append(companion)
        for _ in range(200):
            if all(c.connected for c in companions):
                break
            await asyncio.sleep(.02)
        clients = [CheckpointClient(c) for c in companions]
        initial = [await client.upload(data, 0) for client, data in zip(clients, original)]
        for i, save in enumerate(saves):
            await launch(i, save)
        await boot()
        await wait_ready()
        first = await snapshot("01-live-ready")
        verify_expected(first, {"remotes": [1, 1], "activity": [1, 1], "coordinates": [[6, 11], [5, 9]], "peer_positions_match": True})
        original_pids = [c.process.pid for c in cores]
        original_epochs = [c.session_epoch for c in companions]
        record("two-real-live-mailbox-clients", core_pids=original_pids, epochs=original_epochs)
        pump = Pump(cores, companions)
        pump.start()
        coordinator = LiveCheckpointCoordinator(companions[0], root / "private-a")

        # Lose a real completed BIND response at the coordinator boundary, then
        # resend exactly the retained request to the running ROM.
        rpc = companions[0].save_rpc
        async def lose_bind_ack(control, **kwargs):
            await rpc(control, **kwargs)
            raise asyncio.TimeoutError("injected lost BIND acknowledgement")
        async with coordinator._own():
            session = coordinator._session()
            with patch.object(companions[0], "save_rpc", side_effect=lose_bind_ack):
                try:
                    await coordinator._bind(session)
                except asyncio.TimeoutError:
                    pass
                else:
                    raise AssertionError("BIND acknowledgement fault was not injected")
            await coordinator._bind(session)

        # An open menu is refused before an export can mutate/save the game.
        await pump.press(0, 8, 12, 100)
        before = await clone("menu-before")
        try:
            await coordinator.checkpoint(expected_revision=1)
        except LiveSaveError as error:
            assert error.code == "rom_unsafe", error.code
        else:
            raise AssertionError("menu checkpoint was incorrectly admitted")
        assert await clone("menu-after") == before
        assert await clients[0].info() == initial[0]
        await pump.press(0, 2, 12, 150)
        record("unsafe-menu-refused-without-Flash-or-server-change")
        rejected_bind = await companions[0].save_rpc(SaveControl(session[2], session[1], str(uuid4()),
            1, 0, 131072, 0, Opcode.BIND))
        assert rejected_bind.status == Status.ORDER
        record("lost-BIND-ACK-exact-retry-and-stale-rebinding-fenced")

        # Observe frozen individual RNG/time through read-only diagnostics.
        pump.wander()
        async with coordinator._own():
            session = coordinator._session()
            await coordinator._bind(session)
            operation_id = str(uuid4())
            await coordinator._command(session, operation_id, 2, Opcode.BEGIN_EXPORT)
            query1 = await coordinator._command(session, operation_id, 2, Opcode.QUERY)
            held1 = await snapshot("02-export-held")
            await pump.advance(240)
            query2 = await coordinator._command(session, operation_id, 2, Opcode.QUERY)
            held2 = await snapshot("03-export-still-held")
            assert query1.data[16:] == query2.data[16:]
            assert held1["clients"][0]["play_time_hex"] == held2["clients"][0]["play_time_hex"]
            assert held1["clients"][0]["pose"]["x"] == held2["clients"][0]["pose"]["x"]
            assert held2["clients"][0]["pose"]["activity"] == 0
            await coordinator._cancel(session, operation_id, 2)
        await pump.advance(120)
        assert len(pump.visited_b) > 1
        record("export-freezes-own-RNG-playtime-and-gameplay-other-player-moves", other_positions=sorted(pump.visited_b))

        await pump.press(0, 32, 18, 100)
        start = time.monotonic()
        exported = await coordinator.checkpoint(expected_revision=1)
        duration = time.monotonic() - start
        assert exported.metadata["revision"] == 2
        canonical = await clients[0].download()
        parsed = inspect_flash(canonical.payload)
        assert (parsed.metadata.x, parsed.metadata.y) == (5, 11)
        assert await clients[1].info() == initial[1]
        assert [c.session_epoch for c in companions] == original_epochs
        record("live-export-server-commit-with-other-player-running", seconds=round(duration, 3), checkpoint=exported.metadata, state_sha256=exported.state_sha256)

        # Unsaved movement gives recovery a visible effect without a new server revision.
        await pump.press(0, 16, 18, 80)
        await pump.press(0, 16, 18, 80)
        before_stage = await snapshot("04-before-import-cancel")
        assert before_stage["clients"][0]["pose"]["x"] > 5
        flash_before = await clone("stage-before")
        params = struct.pack("<IIII", zlib.crc32(parsed.flash), parsed.metadata.counter,
                             (-struct.unpack_from("<H", parsed.flash, parsed.metadata.bank * 14 * 4096 + 4084)[0]) % 14,
                             parsed.metadata.trainer_id)
        async with coordinator._own():
            session = coordinator._session()
            operation_id = str(uuid4())
            await coordinator._command(session, operation_id, 2, Opcode.BEGIN_IMPORT, data=params)
            for offset in range(0, 4096, 128):
                await coordinator._command(session, operation_id, 2, Opcode.WRITE, offset=offset, data=parsed.flash[offset:offset + 128])
            partial = await clone("stage-partial")
            assert partial != flash_before
            # Replay the exact last command and verify that Flash does not change.
            replay = SaveControl(session[2], session[1], operation_id, companions[0]._live_sequence,
                                 3968, 131072, 2, Opcode.WRITE, data=parsed.flash[3968:4096])
            duplicate = await companions[0].save_rpc(replay)
            assert duplicate.status == Status.OK and duplicate.offset == 4096
            assert await clone("stage-duplicate") == partial
            bad = replace(replay, data=bytes([replay.data[0] ^ 1]) + replay.data[1:])
            rejected = await companions[0].save_rpc(bad)
            assert rejected.status == Status.ORDER
            await coordinator._cancel(session, operation_id, 2)
        await pump.advance(120)
        after_cancel = await snapshot("05-import-canceled")
        assert after_cancel["clients"][0]["pose"]["x"] == before_stage["clients"][0]["pose"]["x"]
        assert after_cancel["clients"][0]["party_sha256"] == before_stage["clients"][0]["party_sha256"]
        assert inspect_flash(await clone("stage-canceled")).state_sha256 == inspect_flash(flash_before).state_sha256
        assert await clients[0].info() == exported.metadata
        record("partial-import-cancel-and-exact-duplicate-preserve-current-player")

        # A lost controller stops issuing commands; the ROM's advancing-frame watchdog cleans staging.
        async with coordinator._own():
            session = coordinator._session()
            operation_id = str(uuid4())
            await coordinator._command(session, operation_id, 2, Opcode.BEGIN_IMPORT, data=params)
            for offset in range(0, 4096, 128):
                await coordinator._command(session, operation_id, 2, Opcode.WRITE, offset=offset, data=parsed.flash[offset:offset + 128])
            await pump.advance(1800)
        timed_out = await snapshot("06-staging-timeout")
        assert timed_out["clients"][0]["save_state"] == State.BOUND
        assert timed_out["clients"][0]["pose"]["activity"] == 1
        assert inspect_flash(await clone("stage-timeout")).state_sha256 == inspect_flash(flash_before).state_sha256
        record("ROM-idle-watchdog-discards-staging-and-resumes-only-own-game")

        # Ownership is checked before staging, and the final whole-stream CRC is
        # checked before any bank signatures can publish the imported state.
        protected = await clone("ownership-before")
        async with coordinator._own():
            session = coordinator._session()
            operation_id = str(uuid4())
            try:
                await coordinator._command(session, operation_id, 2, Opcode.BEGIN_IMPORT,
                    data=params[:12] + struct.pack("<I", inspect_flash(original[1]).metadata.trainer_id))
            except LiveSaveError as error:
                assert error.code == "rom_ownership", error.code
            else:
                raise AssertionError("another trainer's import was admitted")
            assert await clone("ownership-rejected") == protected
            operation_id = str(uuid4())
            await coordinator._command(session, operation_id, 2, Opcode.BEGIN_IMPORT,
                data=struct.pack("<I", zlib.crc32(parsed.flash) ^ 1) + params[4:])
            for offset in range(0, 131072, 128):
                await coordinator._command(session, operation_id, 2, Opcode.WRITE,
                    offset=offset, data=parsed.flash[offset:offset + 128])
            try:
                await coordinator._command(session, operation_id, 2, Opcode.COMMIT, offset=131072)
            except LiveSaveError as error:
                assert error.code == "rom_crc", error.code
            else:
                raise AssertionError("incorrect whole-stream CRC was published")
            await coordinator._cancel(session, operation_id, 2)
        await pump.advance(120)
        rejected = await snapshot("06b-invalid-import-rejected")
        assert rejected["clients"][0]["pose"]["x"] == before_stage["clients"][0]["pose"]["x"]
        assert rejected["clients"][0]["party_sha256"] == before_stage["clients"][0]["party_sha256"]
        assert inspect_flash(await clone("crc-rejected")).state_sha256 == inspect_flash(protected).state_sha256
        assert await clients[0].info() == exported.metadata
        record("wrong-trainer-and-whole-stream-CRC-rejected-before-publication")

        start = time.monotonic()
        receipt = await coordinator.recover()
        duration = time.monotonic() - start
        await pump.stop_wander()
        await pump.advance(180)
        restored = await snapshot("07-live-canonical-recovery")
        verify_expected(restored, {"remotes": [1, 1], "activity": [1, 1], "peer_positions_match": True,
                                  "party_sha256": [c["party_sha256"] for c in first["clients"]], "saved_remote_ids_empty": True})
        assert [restored["clients"][0]["pose"][axis] for axis in ("x", "y")] == [5, 11]
        assert [c.process.pid for c in cores] == original_pids
        assert [c.session_epoch for c in companions] == original_epochs
        assert await clients[1].info() == initial[1]
        assert receipt.normalized_state_sha256 == parsed.state_sha256
        record("canonical-recovery-without-core-restart-or-lease-change", seconds=round(duration, 3), receipt=asdict(receipt))

        # mGBA's mapped save flushes its own native RTC footer after quiet frames.
        await pump.advance(180)
        await pump.close()
        pump = None
        for core in cores:
            await core.close()
        cores = []
        for lease in leases:
            lease.__exit__(None, None, None)
        leases = []
        local = inspect_flash(saves[0].read_bytes())
        assert local.state_sha256 == parsed.state_sha256
        assert len(local.rtc_footer) == 16
        record("normal-mGBA-writeback-preserves-applied-Flash-and-native-RTC-footer", container_sha256=local.container_sha256)
        for i, save in enumerate(saves):
            await launch(i, save)
        await boot()
        await wait_ready()
        fresh = await snapshot("08-fresh-continue-after-live-recovery")
        verify_expected(fresh, {"remotes": [1, 1], "activity": [1, 1], "coordinates": [[5, 11], [5, 9]],
                               "peer_positions_match": True, "party_sha256": [c["party_sha256"] for c in first["clients"]], "saved_remote_ids_empty": True})
        store.integrity_check()
        record("fresh-Continue-confirms-durable-live-recovery")

        # This is the game's existing full soft reboot, not the planned local
        # encounter reset. Its fresh ROM mailbox must get a fresh IPC binding.
        pump = Pump(cores, companions)
        pump.start()
        pump.wander()
        async with coordinator._own():
            await coordinator._bind(coordinator._session())
        old_incarnation = companions[0].save_incarnation
        restart_pids = [c.process.pid for c in cores]
        await pump.press(0, 15, 12, 1000)  # A+B+Select+Start
        await pump.press(0, 8, 8, 480)
        await pump.press(0, 8, 8, 180)
        await pump.press(0, 1, 8, 300)
        await wait_ready()
        assert companions[0].save_incarnation > old_incarnation
        after_restart = await coordinator.checkpoint(expected_revision=2)
        assert after_restart.metadata["revision"] == 3
        await pump.stop_wander()
        await pump.advance(120)
        restarted = await snapshot("09-native-soft-reboot-rebound")
        verify_expected(restarted, {"remotes": [1, 1], "activity": [1, 1], "peer_positions_match": True,
            "party_sha256": [c["party_sha256"] for c in first["clients"]], "saved_remote_ids_empty": True})
        assert [c.process.pid for c in cores] == restart_pids
        assert [c.session_epoch for c in companions] == original_epochs
        assert await clients[1].info() == initial[1]
        assert len(pump.visited_b) > 1
        record("native-game-soft-reboot-rebinds-live-save-without-dropping-other-player",
            previous_incarnation=old_incarnation, current_incarnation=companions[0].save_incarnation,
            revisions=[3, 1])
        evidence["passed"] = True
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    finally:
        if pump is not None:
            await pump.close()
        await asyncio.gather(*(c.close() for c in cores), return_exceptions=True)
        for lease in leases:
            lease.__exit__(None, None, None)
        await asyncio.gather(*(c.close() for c in companions), return_exceptions=True)
        await server.close()
        store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rom", "manifest", "harness", "save-a", "save-b", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--bridge", type=Path, default=Path(__file__).parents[2] / "bridge/mgba.lua")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
