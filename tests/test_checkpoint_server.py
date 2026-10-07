from __future__ import annotations

import asyncio
import base64
from dataclasses import replace
import hashlib
from pathlib import Path
import secrets
import tempfile
import unittest
import uuid

from emerald_multiplayer.checkpoint_client import CheckpointClient
from emerald_multiplayer.companion import BASELINE_RULESET, Companion, CompanionConfig, verify_rom_manifest
from emerald_multiplayer.flash import LAYOUT_ID
from emerald_multiplayer.protocol import (
    CHECKPOINT_CHUNK_BYTES, MAX_CHECKPOINT_BYTES, ProtocolError,
    encode_message, read_message, validate_checkpoint_request, validate_hello,
)
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.storage import CheckpointStore

from test_companion import BinaryBridge, make_files, make_pose
from test_flash import make_flash


async def wait_until(predicate, timeout=2.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


def fingerprint(payload, revision=0):
    return dict(expected_revision=revision, size=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(), save_profile=LAYOUT_ID)


class Client:
    def __init__(self, reader, writer, owner):
        self.reader, self.writer, self.owner = reader, writer, owner
        self.epoch = None
        self.worlds = []
        self.pongs = 0

    @classmethod
    async def connect(cls, address, owner, build, **changes):
        reader, writer = await asyncio.open_connection(*address)
        client = cls(reader, writer, owner)
        hello = dict(type="hello", protocol=1, build_id=build, ruleset_id=BASELINE_RULESET,
                     player_id=owner.player_id, display_name="Client-supplied name",
                     credential=owner.credential.hex())
        # None deliberately omits a field to exercise the actual hello gate.
        hello.update(changes)
        await client.send({key: value for key, value in hello.items() if value is not None})
        result = await client.next()
        if result["type"] == "welcome":
            client.epoch = result["session_epoch"]
        return client, result

    async def send(self, message):
        self.writer.write(encode_message(message))
        await self.writer.drain()

    async def next(self):
        async with asyncio.timeout(2.0):
            while True:
                message = await read_message(self.reader)
                if message is None:
                    return None
                if message["type"] == "ping":
                    await self.send({**message, "type": "pong"})
                    self.pongs += 1
                    continue
                if message["type"] == "world":
                    self.worlds.append(message)
                return message

    async def rpc(self, operation, *, request_id=None, **fields):
        request_id = request_id or str(uuid.uuid4())
        await self.send(dict(type="checkpoint_" + operation, session_epoch=self.epoch,
                             request_id=request_id, **fields))
        async with asyncio.timeout(2.0):
            while True:
                message = await self.next()
                if message is None or message["type"] == "error":
                    raise AssertionError("checkpoint connection unexpectedly closed")
                if message.get("request_id") == request_id:
                    return message

    async def move(self, seq=1, **changes):
        await self.send(dict(type="presence", session_epoch=self.epoch, seq=seq,
                             map_epoch=0, map_group=0, map_number=9, x=6, y=11,
                             direction=1, elevation=0, avatar_gender=0,
                             activity="overworld", **changes))

    async def close(self):
        self.writer.close()
        await self.writer.wait_closed()


class CheckpointProtocolTests(unittest.TestCase):
    def test_chunk_boundaries_and_strict_base64(self):
        request = dict(type="checkpoint_chunk", session_epoch=1, request_id=str(uuid.uuid4()),
                       upload_id=str(uuid.uuid4()), offset=0,
                       data_b64=base64.b64encode(bytes(CHECKPOINT_CHUNK_BYTES)).decode("ascii"))
        self.assertEqual(len(validate_checkpoint_request(request, 1)["data"]), CHECKPOINT_CHUNK_BYTES)
        self.assertLess(len(encode_message(request)), 16384)
        for changes in (dict(offset=True), dict(offset=MAX_CHECKPOINT_BYTES + 1),
                        dict(data_b64="Zg==\n"), dict(data_b64="Zh=="), dict(data_b64=""),
                        dict(data_b64=base64.b64encode(bytes(4097)).decode("ascii")),
                        dict(protocol=1), dict(upload_id="not-a-uuid")):
            with self.subTest(field=next(iter(changes))):
                with self.assertRaises(ProtocolError):
                    validate_checkpoint_request({**request, **changes}, 1)
        with self.assertRaises(ProtocolError) as caught:
            validate_checkpoint_request(request, 2)
        self.assertEqual(caught.exception.code, "session_epoch_mismatch")

    def test_hello_credential_optional_for_transient_required_for_durable(self):
        hello = dict(type="hello", protocol=1, build_id="build", ruleset_id="rules",
                     player_id=str(uuid.uuid4()), display_name="Player")
        validate_hello(hello, "build", "rules")
        with self.assertRaises(ProtocolError) as caught:
            validate_hello(hello, "build", "rules", require_credential=True)
        self.assertEqual(caught.exception.code, "credentials_required")
        validate_hello({**hello, "credential": "a" * 64}, "build", "rules", require_credential=True)
        for credential in ("A" * 64, "a" * 63, bytes(32), True):
            with self.assertRaises(ProtocolError):
                validate_hello({**hello, "credential": credential}, "build", "rules")


class CheckpointServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.rom, self.manifest = make_files(self.temp.name)
        self.build = verify_rom_manifest(self.rom, self.manifest)[0]
        self.path = Path(self.temp.name) / "world.sqlite3"
        self.store = CheckpointStore(self.path, self.build, BASELINE_RULESET, LAYOUT_ID)
        self.owner = self.store.create_player("Player A")
        self.other = self.store.create_player("Player B")
        self.config = ServerConfig(self.build, BASELINE_RULESET, heartbeat_interval=0.15,
                                   idle_timeout=3.0, monitor_interval=0.005,
                                   checkpoint_upload_timeout=0.3)
        self.server = WorldServer(self.config, store=self.store)
        await self.server.start(port=0)
        self.clients, self.companions, self.bridges = [], [], []

    async def asyncTearDown(self):
        for bridge in self.bridges:
            await bridge.close()
        for companion in self.companions:
            await companion.close()
        for client in self.clients:
            await client.close()
        await self.server.close()
        self.store.close()
        self.temp.cleanup()

    async def connect(self, owner=None, **changes):
        client, result = await Client.connect(self.server.address, owner or self.owner, self.build, **changes)
        self.clients.append(client)
        return client, result

    def assert_result(self, message):
        self.assertEqual(message["type"], "checkpoint_result", message.get("code"))

    def assert_error(self, message, code):
        self.assertEqual(message["type"], "checkpoint_error")
        self.assertEqual(message["code"], code)

    async def stage(self, client, payload, revision=0, *, upload_id=None, **changes):
        upload_id = upload_id or str(uuid.uuid4())
        values = {**fingerprint(payload, revision), **changes}
        result = await client.rpc("begin", request_id=upload_id, **values)
        self.assert_result(result)
        self.assertEqual(result["upload_id"], upload_id)
        for offset in range(result["next_offset"], len(payload), CHECKPOINT_CHUNK_BYTES):
            chunk = payload[offset:offset + CHECKPOINT_CHUNK_BYTES]
            result = await client.rpc("chunk", upload_id=upload_id, offset=offset,
                                      data_b64=base64.b64encode(chunk).decode("ascii"))
            self.assert_result(result)
            self.assertEqual(result["next_offset"], offset + len(chunk))
        return upload_id, values

    async def upload(self, client, payload, revision=0, **changes):
        upload_id, values = await self.stage(client, payload, revision, **changes)
        result = await client.rpc("commit", upload_id=upload_id, **values)
        self.assert_result(result)
        return result["checkpoint"]

    async def test_authenticated_hello_authoritative_name_and_no_secret_broadcast(self):
        for changes, code in ((dict(credential=None), "credentials_required"),
                              (dict(credential="0" * 64), "credentials_invalid"),
                              (dict(player_id=str(uuid.uuid4())), "credentials_invalid"),
                              (dict(build_id="other"), "build_mismatch")):
            client, result = await self.connect(**changes)
            self.assertEqual(result["type"], "error")
            self.assertEqual(result["code"], code)
            self.assertIsNone(await client.next())
        first, welcome = await self.connect()
        self.assertEqual(welcome["world_id"], self.store.metadata.world_id)
        self.assertEqual(welcome["save_profile"], LAYOUT_ID)
        self.assertTrue(welcome["checkpoint_enabled"])
        world = await first.next()
        self.assertEqual(world["players"][0]["display_name"], "Player A")
        self.assertEqual(set(world["players"][0]), {"player_id", "display_name", "session_epoch", "presence"})
        self.assertNotIn(self.owner.credential.hex().encode(), encode_message(world))
        duplicate, result = await self.connect()
        self.assertEqual(result["code"], "player_already_connected")
        self.assertIsNone(await duplicate.next())

    async def test_four_authenticated_leases_and_fifth_rejection(self):
        identities = [self.owner, self.other] + [self.store.create_player(f"Player {index}") for index in range(3, 6)]
        clients = []
        for owner in identities[:4]:
            client, result = await self.connect(owner)
            self.assertEqual(result["type"], "welcome")
            clients.append(client)
        _, rejected = await self.connect(identities[4])
        self.assertEqual(rejected["code"], "server_full")
        self.assertEqual(len({client.epoch for client in clients}), 4)
        self.assertEqual(len(self.server.sessions), 4)

    async def test_full_container_commit_pull_download_and_independent_head(self):
        first, _ = await self.connect()
        second, _ = await self.connect(self.other)
        payload = make_flash(with_rtc=True)
        self.assertIsNone((await first.rpc("info"))["checkpoint"])
        metadata = await self.upload(first, payload)
        self.assertEqual(metadata["revision"], 1)
        self.assertEqual(metadata["size"], 131088)
        self.assertEqual(metadata["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertIsNone((await second.rpc("info"))["checkpoint"])
        recovered = bytearray()
        while len(recovered) < len(payload):
            result = await first.rpc("read", expected_revision=1, offset=len(recovered), length=4096)
            self.assert_result(result)
            self.assertEqual(result["checkpoint"], metadata)
            self.assertEqual(result["offset"], len(recovered))
            chunk = base64.b64decode(result["data_b64"], validate=True)
            self.assertLessEqual(len(chunk), 4096)
            recovered.extend(chunk)
            self.assertEqual(result["eof"], len(recovered) == len(payload))
        self.assertEqual(bytes(recovered), payload)
        self.assert_error(await first.rpc("read", expected_revision=1, offset=len(payload), length=1), "invalid_checkpoint_offset")
        # Ordinary presence messages expose no snapshot or checkpoint metadata.
        await first.move()
        await wait_until(lambda: self.server.sessions[self.owner.player_id].presence is not None)
        world = await first.next()
        while world["type"] != "world":
            world = await first.next()
        self.assertEqual(set(world), {"type", "protocol", "world_seq", "players"})

    async def test_chunk_retries_conflicts_abort_and_schema_errors_preserve_presence(self):
        client, _ = await self.connect()
        payload = make_flash()
        upload_id = str(uuid.uuid4())
        result = await client.rpc("begin", request_id=upload_id, **fingerprint(payload))
        self.assert_result(result)
        data = base64.b64encode(payload[:100]).decode("ascii")
        for _ in range(2):
            result = await client.rpc("chunk", upload_id=upload_id, offset=0, data_b64=data)
            self.assertEqual(result["next_offset"], 100)
        result = await client.rpc("begin", request_id=upload_id, **fingerprint(payload))
        self.assertEqual(result["next_offset"], 100)
        self.assert_error(await client.rpc("begin", **fingerprint(payload)), "upload_active")
        self.assert_error(await client.rpc("chunk", upload_id=upload_id, offset=101, data_b64=data), "checkpoint_offset_conflict")
        self.assert_error(await client.rpc("chunk", upload_id=upload_id, offset=0, data_b64="!!!!"), "invalid_checkpoint_chunk")
        self.assert_error(await client.rpc("begin", **{**fingerprint(payload), "size": True}), "invalid_checkpoint_size")
        self.assert_error(await client.rpc("commit", upload_id=upload_id, **fingerprint(payload)), "upload_incomplete")
        self.assert_error(await client.rpc("commit", upload_id=upload_id, **{**fingerprint(payload), "sha256": "a" * 64}), "request_conflict")
        await client.move()
        await wait_until(lambda: self.server.sessions[self.owner.player_id].presence is not None)
        self.assert_result(await client.rpc("abort", upload_id=upload_id))
        self.assertIsNone(self.server.sessions[self.owner.player_id].upload)
        self.assert_result(await client.rpc("abort", upload_id=upload_id))
        self.assert_error(await client.rpc("chunk", upload_id=upload_id, offset=0, data_b64=data), "upload_not_found")
        self.assertIsNone((await client.rpc("info"))["checkpoint"])

    async def test_invalid_flash_hash_profile_and_trainer_binding(self):
        client, _ = await self.connect()
        payload = make_flash()
        self.assert_error(await client.rpc("begin", **{**fingerprint(payload), "save_profile": "other"}), "save_profile_mismatch")
        upload_id, values = await self.stage(client, payload, sha256="0" * 64)
        self.assert_error(await client.rpc("commit", upload_id=upload_id, **values), "checkpoint_hash_mismatch")
        broken = bytes(131072)
        upload_id, values = await self.stage(client, broken)
        self.assert_error(await client.rpc("commit", upload_id=upload_id, **values), "invalid_checkpoint")
        self.assertIsNone((await client.rpc("info"))["checkpoint"])
        first = await self.upload(client, payload)
        upload_id, values = await self.stage(client, make_flash(counter=3, trainer_id=0x87654321), revision=1)
        self.assert_error(await client.rpc("commit", upload_id=upload_id, **values), "invalid_checkpoint")
        self.assertEqual((await client.rpc("info"))["checkpoint"], first)
        second = await self.upload(client, make_flash(counter=3), revision=1)
        self.assertEqual(second["revision"], 2)
        self.assert_error(await client.rpc("begin", **fingerprint(payload)), "revision_conflict")
        self.assert_error(await client.rpc("read", expected_revision=1, offset=0, length=4096), "revision_conflict")

    async def test_partial_disconnect_and_timeout_discard_without_saving(self):
        client, _ = await self.connect()
        payload = make_flash()
        upload_id = str(uuid.uuid4())
        self.assert_result(await client.rpc("begin", request_id=upload_id, **fingerprint(payload)))
        self.assert_result(await client.rpc("chunk", upload_id=upload_id, offset=0,
                                           data_b64=base64.b64encode(payload[:4096]).decode("ascii")))
        old_epoch = client.epoch
        await client.close()
        await wait_until(lambda: self.owner.player_id not in self.server.sessions)
        rejoined, _ = await self.connect()
        self.assertGreater(rejoined.epoch, old_epoch)
        self.assertIsNone((await rejoined.rpc("info"))["checkpoint"])
        self.assert_error(await rejoined.rpc("commit", upload_id=upload_id, **fingerprint(payload)), "upload_not_found")
        self.assert_result(await rejoined.rpc("begin", request_id=upload_id, **fingerprint(payload)))
        self.server.sessions[self.owner.player_id].upload.last_activity -= 1
        await wait_until(lambda: self.server.sessions[self.owner.player_id].upload is None)
        self.assert_error(await rejoined.rpc("commit", upload_id=upload_id, **fingerprint(payload)), "upload_not_found")

    async def test_lost_ack_exact_retry_after_rejoin_newer_head_and_server_restart(self):
        client, welcome = await self.connect()
        payload = make_flash(with_rtc=True)
        upload_id, values = await self.stage(client, payload)
        await client.send(dict(type="checkpoint_commit", request_id=str(uuid.uuid4()),
                               session_epoch=client.epoch, upload_id=upload_id, **values))
        # Observe durability without consuming the commit acknowledgement.
        await wait_until(lambda: self.store.read_checkpoint(self.owner.player_id, client.epoch) is not None)
        await client.close()
        await wait_until(lambda: self.owner.player_id not in self.server.sessions)
        rejoined, _ = await self.connect()
        result = await rejoined.rpc("commit", upload_id=upload_id, **values)
        self.assert_result(result)
        original = result["checkpoint"]
        self.assertEqual(original["revision"], 1)
        newer = await self.upload(rejoined, make_flash(counter=3, with_rtc=True), revision=1)
        self.assertEqual(newer["revision"], 2)
        result = await rejoined.rpc("begin", request_id=upload_id, **values)
        self.assertEqual(result["next_offset"], len(payload))
        self.assertEqual(result["checkpoint"], original)
        self.assertEqual((await rejoined.rpc("commit", upload_id=upload_id, **values))["checkpoint"], original)
        self.assertEqual((await rejoined.rpc("info"))["checkpoint"], newer)
        self.assert_error(await rejoined.rpc("commit", upload_id=upload_id,
                                              **{**values, "sha256": "1" * 64}), "request_conflict")
        old_epoch = rejoined.epoch
        await self.server.close()
        self.store.close()
        self.store = CheckpointStore(self.path, self.build, BASELINE_RULESET, LAYOUT_ID)
        self.server = WorldServer(self.config, store=self.store)
        await self.server.start(port=0)
        restarted, new_welcome = await self.connect()
        self.assertEqual(new_welcome["world_id"], welcome["world_id"])
        self.assertGreater(new_welcome["server_epoch"], welcome["server_epoch"])
        self.assertGreater(restarted.epoch, old_epoch)
        self.assertEqual((await restarted.rpc("commit", upload_id=upload_id, **values))["checkpoint"], original)
        self.assertEqual((await restarted.rpc("info"))["checkpoint"], newer)
        self.store.integrity_check()

    async def test_old_wire_epoch_rejected_on_fresh_lease(self):
        old, _ = await self.connect()
        old_epoch = old.epoch
        await old.close()
        await wait_until(lambda: self.owner.player_id not in self.server.sessions)
        current, _ = await self.connect()
        await current.send(dict(type="checkpoint_info", session_epoch=old_epoch, request_id=str(uuid.uuid4())))
        message = await current.next()
        while message is not None and message["type"] == "world":
            message = await current.next()
        self.assertEqual(message["type"], "error")
        self.assertEqual(message["code"], "session_epoch_mismatch")
        self.assertIsNone(await current.next())

    async def test_failed_bind_does_not_increment_world_boot_epoch(self):
        before = self.store.metadata
        contender = WorldServer(self.config, store=self.store)
        with self.assertRaises(OSError):
            await contender.start(port=self.server.address[1])
        self.assertEqual(self.store.metadata, before)

    async def test_checkpoint_reply_backpressure_is_bounded_discards_partial_and_keeps_other_player(self):
        flooded, _ = await self.connect()
        observer, _ = await self.connect(self.other)
        payload = make_flash()
        upload_id = str(uuid.uuid4())
        self.assert_result(await flooded.rpc("begin", request_id=upload_id, **fingerprint(payload)))
        session = self.server.sessions[self.owner.player_id]
        stalled = asyncio.Event()

        async def blocked_drain():
            stalled.set()
            await asyncio.Event().wait()

        session.writer.drain = blocked_drain
        await flooded.send(dict(type="checkpoint_info", session_epoch=flooded.epoch, request_id=str(uuid.uuid4())))
        await asyncio.wait_for(stalled.wait(), 1)
        peak = 0
        original_control = self.server._control

        def record_control(target, message):
            nonlocal peak
            original_control(target, message)
            peak = max(peak, len(target.outbox.controls))

        self.server._control = record_control
        flooded.writer.write(b"".join(encode_message(dict(type="checkpoint_info", session_epoch=flooded.epoch,
                                                           request_id=str(uuid.uuid4()))) for _ in range(100)))
        await flooded.writer.drain()
        await wait_until(lambda: self.owner.player_id not in self.server.sessions)
        self.assertEqual(session.close_reason, "control_backpressure")
        self.assertLessEqual(peak, self.config.reliable_limit)
        self.assertIsNone(session.upload)
        await observer.move()
        self.assertIsNone((await observer.rpc("info"))["checkpoint"])
        self.assertIn(self.other.player_id, self.server.sessions)
        rejoined, _ = await self.connect()
        self.assertIsNone((await rejoined.rpc("info"))["checkpoint"])

    async def test_real_companions_upload_download_while_presence_and_heartbeat_continue(self):
        # Real TCP/IPC adapters, using explicitly synthetic ROM identity and Flash.
        async def add(owner):
            config = CompanionConfig(self.rom, self.manifest, owner.player_id, owner.display_name,
                                     secrets.token_bytes(32), server_port=self.server.address[1], ipc_port=0,
                                     server_credential=owner.credential, pose_interval=0.005,
                                     snapshot_interval=0.01, pause_timeout=0.2, reconnect_delay=0.025)
            companion = Companion(config)
            self.companions.append(companion)
            await companion.start()
            await wait_until(lambda: companion.connected and companion._roster_signature is not None)
            bridge = await BinaryBridge.connect(companion)
            self.bridges.append(bridge)
            return companion, bridge

        first, bridge_a = await add(self.owner)
        second, bridge_b = await add(self.other)
        self.server.config = replace(self.config, heartbeat_interval=0.02, idle_timeout=0.25)
        stop = asyncio.Event()

        async def move_second():
            frame = 1
            while not stop.is_set():
                await bridge_a.pose(make_pose(frame=frame, x=6))
                await bridge_b.pose(make_pose(frame=frame, x=4 + frame % 2, map_number=1))
                frame += 1
                await asyncio.sleep(0.005)

        movement = asyncio.create_task(move_second())
        try:
            epoch_a, epoch_b = first.session_epoch, second.session_epoch
            payload = make_flash(with_rtc=True)
            metadata = await CheckpointClient(first).upload(payload, 0)
            recovered = await CheckpointClient(first).download()
            self.assertEqual(recovered.payload, payload)
            self.assertEqual(recovered.metadata, metadata)
            self.assertIsNone(await CheckpointClient(second).download())
            # Run beyond idle timeout; automatic heartbeat replies must keep both leases.
            await asyncio.sleep(0.3)
            self.assertEqual((first.session_epoch, second.session_epoch), (epoch_a, epoch_b))
            self.assertTrue(first.connected and second.connected)
            self.assertGreater(self.server.sessions[self.other.player_id].presence["seq"], 10)
            self.assertGreater(self.server.sessions[self.owner.player_id].ping_nonce, 1)
            snapshot = await bridge_a.snapshot(lambda value: bool(value.peers))
            self.assertEqual(snapshot.peers[0].pose.map_number, 1)
        finally:
            stop.set()
            await movement


if __name__ == "__main__":
    unittest.main()
