from __future__ import annotations

import asyncio
from contextlib import suppress
import hashlib
import json
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
import zlib

from emerald_multiplayer.bridge_protocol import encode_packet
from emerald_multiplayer.checkpoint_client import CheckpointClient, CheckpointError
from emerald_multiplayer.companion import BASELINE_RULESET, Companion, CompanionConfig, TradeError
from emerald_multiplayer.flash import inspect_flash
from emerald_multiplayer.ownership import inspect_ownership, OWNERSHIP_PROFILE
from emerald_multiplayer.ownership_storage import OwnershipCheckpointStore
from emerald_multiplayer.protocol import encode_message, read_message
from emerald_multiplayer.save_mailbox import capability_packet
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.trade_storage import TradeCheckpointStore
from test_companion import BinaryBridge, make_files, make_pose
from test_ownership_storage import source_flash, owned_flash
from emerald_multiplayer.protocol import PROTOCOL_VERSION


async def wait_until(predicate, timeout=8):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


class RawClient:
    """Real TCP actor for deliberately invalid bodies bypassing client validation."""

    @classmethod
    async def connect(cls, address, player, build):
        self = cls()
        self.reader, self.writer = await asyncio.open_connection(*address)
        self.writer.write(encode_message(dict(type="hello", protocol=PROTOCOL_VERSION, build_id=build,
            ruleset_id=BASELINE_RULESET, player_id=player.player_id,
            display_name=player.display_name, credential=player.credential.hex())))
        await self.writer.drain()
        welcome = await self.next()
        assert welcome["type"] == "welcome"
        self.epoch = welcome["session_epoch"]
        return self

    async def next(self):
        async with asyncio.timeout(8):
            while True:
                message = await read_message(self.reader)
                if message is None:
                    raise ConnectionError("test TCP actor disconnected")
                if message["type"] == "ping":
                    self.writer.write(encode_message({**message, "type": "pong"}))
                    await self.writer.drain()
                elif message["type"] != "world":
                    return message

    async def rpc(self, operation, **fields):
        request_id = str(uuid4())
        from emerald_multiplayer.trade_protocol import PREPARATION_OPERATIONS
        if operation in PREPARATION_OPERATIONS:
            fields.setdefault("preparation_version", 1)
        self.writer.write(encode_message(dict(type="trade_" + operation,
            request_id=request_id, session_epoch=self.epoch, **fields)))
        await self.writer.drain()
        while True:
            result = await self.next()
            if result.get("request_id") == request_id:
                return result

    async def close(self):
        self.writer.close()
        with suppress(ConnectionError, OSError):
            await self.writer.wait_closed()


class TradeNetworkTests(unittest.IsolatedAsyncioTestCase):
    """Development-only transport proofs; synthetic saves are not game acceptance."""

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.rom, self.manifest = make_files(self.temp.name)
        data = b"\x01\x00\x00\x00" + self.rom.read_bytes()[4:]
        self.rom.write_bytes(data)
        value = json.loads(self.manifest.read_text())
        value.update(rom_sha256=hashlib.sha256(data).hexdigest(), rom_crc32=f"{zlib.crc32(data):08x}",
            save_abi_version=1, save_mailbox_size=512, save_mailbox_address=0x02021000,
            ownership_abi_version=1, save_profile=OWNERSHIP_PROFILE,
            trade_abi_version=1, trade_abi_address=0x08000000)
        self.manifest.write_text(json.dumps(value))
        self.build = value["rom_sha256"]
        self.path = Path(self.temp.name) / "world.sqlite3"
        self.store = TradeCheckpointStore(self.path, self.build, BASELINE_RULESET)
        self.store.begin_server_boot()
        self.players, self.heads, self.grants = [], [], []
        for index in range(3):
            player = self.store.create_player(f"Trade player {index}")
            lease = self.store.acquire_lease(player.player_id, player.credential)
            personalities = (index * 2 + 7, index * 2 + 8)
            self.store.enroll_player(player.player_id,
                source_flash(("party:0", "party:1"), personalities=personalities))
            grant = self.store.reserve_instances(player.player_id, lease, str(uuid4()), 0, 1, 32)
            payload = owned_flash(grant, (("party:0", grant.start), ("party:1", grant.start+1)),
                personalities=personalities, with_rtc=True)
            head = self.store.commit_checkpoint(player.player_id, lease, str(uuid4()), 0, payload,
                self.build, BASELINE_RULESET, OWNERSHIP_PROFILE)
            self.store.release_lease(player.player_id, lease)
            self.players.append(player); self.grants.append(grant); self.heads.append(head)
        self.config = ServerConfig(self.build, BASELINE_RULESET, heartbeat_interval=0.05,
            idle_timeout=10, monitor_interval=0.01)
        self.server = WorldServer(self.config, store=self.store, development_trades=True)
        await self.server.start(port=0)
        self.companions, self.bridges, self.raw = [], [], []
        for player in self.players:
            companion = Companion(CompanionConfig(self.rom, self.manifest, player.player_id,
                player.display_name, secrets.token_bytes(32), server_port=self.server.address[1],
                ipc_port=0, server_credential=player.credential, pose_interval=0.01,
                snapshot_interval=0.02, reconnect_delay=0.05, remote_timeout=15))
            self.companions.append(companion)
            await companion.start()
            await wait_until(lambda: companion.connected)
            self.bridges.append(await self.connect_bridge(companion))
        self.transaction = str(uuid4())

    async def asyncTearDown(self):
        for client in self.raw:
            await client.close()
        for bridge in self.bridges:
            with suppress(ConnectionError, OSError):
                await bridge.close()
        for companion in self.companions:
            await companion.close()
        await self.server.close()
        self.store.close()
        self.temp.cleanup()

    async def connect_bridge(self, companion):
        bridge = await BinaryBridge.connect(companion)
        bridge.writer.write(encode_packet(capability_packet()))
        await bridge.writer.drain()
        await wait_until(lambda: companion._bridge is not None and companion._bridge.save_capable)
        await bridge.pose(make_pose(frame=1, x=6))
        return bridge

    async def rpc(self, index, operation, **fields):
        return await self.companions[index].trade_rpc(operation, **fields)

    async def ready(self, transaction=None):
        transaction = transaction or self.transaction
        view = (await self.rpc(0, "open", transaction_id=transaction, peer=self.players[1].player_id))["trade"]
        for index in (0, 1):
            head = await CheckpointClient(self.companions[index]).info()
            view = (await self.rpc(index, "offer", transaction_id=transaction, generation=view["generation"],
                revision=head["revision"], sha256=head["sha256"], serial=self.grants[index].start))["trade"]
        return view

    async def confirm(self, index, view):
        return (await self.rpc(index, "confirm", transaction_id=view["transaction_id"],
            generation=view["generation"], fingerprint=view["fingerprint"]))["trade"]

    async def commit(self):
        view = await self.ready()
        await self.confirm(0, view)
        return await self.finish_preparation(await self.confirm(1, view))

    async def prepare_receipt(self, index, view):
        description = (await self.rpc(index, "prepare", transaction_id=view["transaction_id"],
            generation=view["generation"]))["trade"]["preparation"]
        own = next(p for p in description["players"] if p["player_id"] == self.players[index].player_id)
        return (await self.rpc(index, "prepared", transaction_id=view["transaction_id"], generation=view["generation"],
            fingerprint=description["fingerprint"], preparation_id=description["preparation_id"],
            candidate_sha256=own["candidate_sha256"]))["trade"]

    async def finish_preparation(self, view):
        self.assertEqual(view["state"], "preparing")
        await self.prepare_receipt(0, view)
        return await self.prepare_receipt(1, view)

    async def assert_trade_error(self, code, index, operation, **fields):
        with self.assertRaises(TradeError) as caught:
            await self.rpc(index, operation, **fields)
        self.assertEqual(caught.exception.code, code)

    async def ack(self, index):
        pending = (await self.rpc(index, "pending"))["recoveries"]
        self.assertEqual(len(pending), 1)
        cp = pending[0]["checkpoint"]
        result = (await self.rpc(index, "ack", transaction_id=pending[0]["transaction_id"],
            revision=cp["revision"], sha256=cp["sha256"]))["trade"]
        self.assertEqual(result["state"], "acknowledged")
        return result

    async def restart(self, *, enable_trades=True):
        port, world = self.server.address[1], self.store.metadata.world_id
        old_epochs = [c.session_epoch for c in self.companions]
        await self.server.close()
        self.store.close()
        self.store = TradeCheckpointStore(self.path, self.build, BASELINE_RULESET)
        self.server = (WorldServer(self.config, store=self.store, development_trades=True)
            if enable_trades else WorldServer(self.config, store=self.store))
        await self.server.start(port=port)
        await wait_until(lambda: all(c.connected and c.session_epoch != old for c, old in zip(self.companions, old_epochs)))
        self.assertEqual(self.store.metadata.world_id, world)

    async def test_two_distinct_consents_atomic_swap_own_recovery_and_ack_barrier(self):
        view = await self.ready()
        first = await self.confirm(0, view)
        self.assertEqual(first["confirmations"], [self.players[0].player_id])
        self.assertEqual(await self.confirm(0, view), first)
        self.assertEqual((await CheckpointClient(self.companions[0]).info())["revision"], 1)
        await self.bridges[1].pose(make_pose(frame=2, x=7))
        await wait_until(lambda: self.server.sessions[self.players[1].player_id].presence is not None
            and self.server.sessions[self.players[1].player_id].presence["x"] == 7
            and self.server.sessions[self.players[1].player_id].ping_nonce > 0)
        committed = await self.confirm(1, view)
        self.assertEqual(committed["state"], "preparing")
        self.assertEqual((await CheckpointClient(self.companions[0]).info())["revision"], 1)
        committed = await self.finish_preparation(committed)
        self.assertEqual(committed["state"], "committed")
        snapshots = []
        for index in (0, 1):
            recovery = (await self.rpc(index, "pending"))["recoveries"]
            self.assertEqual(len(recovery), 1)
            self.assertEqual(recovery[0]["transaction_id"], self.transaction)
            self.assertEqual(recovery[0]["checkpoint"]["revision"], 2)
            self.assertNotIn("payload", json.dumps(recovery))
            downloaded = await CheckpointClient(self.companions[index]).download()
            self.assertEqual(downloaded.player_id, self.players[index].player_id)
            owned = inspect_ownership(inspect_flash(downloaded.payload, save_profile=OWNERSHIP_PROFILE))
            self.assertEqual(owned.player_id, self.players[index].player_id)
            self.assertEqual({r.serial for r in owned.records},
                {self.grants[1-index].start, self.grants[index].start+1})
            self.assertEqual(downloaded.metadata, recovery[0]["checkpoint"])
            snapshots.append(downloaded)
        self.assertNotEqual(snapshots[0].metadata["sha256"], snapshots[1].metadata["sha256"])
        with self.assertRaises(CheckpointError) as caught:
            await CheckpointClient(self.companions[0]).upload(snapshots[0].payload, 2)
        self.assertEqual(caught.exception.code, "trade_recovery_required")
        await self.ack(0)
        self.assertEqual((await self.rpc(0, "pending"))["recoveries"], [])
        self.assertEqual(len((await self.rpc(1, "pending"))["recoveries"]), 1)
        await self.ack(1)
        self.store.integrity_check()

    async def test_third_actor_and_identity_injection_cannot_offer_confirm_or_read_fate(self):
        view = await self.ready()
        await self.companions[2].close()
        await wait_until(lambda: self.players[2].player_id not in self.server.sessions)
        client = await RawClient.connect(self.server.address, self.players[2], self.build)
        self.raw.append(client)
        for operation, fields in (
            ("status", {}),
            ("offer", dict(generation=view["generation"], revision=1, sha256=self.heads[2].sha256, serial=self.grants[2].start)),
            ("confirm", dict(generation=view["generation"], fingerprint=view["fingerprint"])),
        ):
            result = await client.rpc(operation, transaction_id=self.transaction, **fields)
            self.assertEqual((result["type"], result["code"]), ("trade_error", "trade_not_participant"))
            self.assertNotIn("trade", result)
        injected = await client.rpc("confirm", transaction_id=self.transaction,
            generation=view["generation"], fingerprint=view["fingerprint"], player_id=self.players[0].player_id)
        self.assertEqual(injected["type"], "trade_error")
        self.assertEqual(injected["code"], "invalid_fields")
        own_pending = await client.rpc("pending")
        self.assertEqual(own_pending["recoveries"], [])
        self.assertEqual((await self.rpc(0, "status", transaction_id=self.transaction))["trade"]["confirmations"], [])
        await self.confirm(0, view); await self.finish_preparation(await self.confirm(1, view))
        denied = await client.rpc("status", transaction_id=self.transaction)
        self.assertEqual(denied["code"], "trade_not_participant")
        self.assertEqual((await client.rpc("pending"))["recoveries"], [])

    async def test_lost_second_prepared_reply_has_committed_fate_on_fresh_lease(self):
        view = await self.ready()
        await self.confirm(0, view)
        view = await self.confirm(1, view)
        await self.prepare_receipt(0, view)
        old_epoch = self.companions[1].session_epoch
        original = self.server._trade_reply
        dropped = []
        def drop_committed_ack(session, request, **fields):
            if request["type"] == "trade_prepared" and fields.get("trade", {}).get("state") == "committed":
                dropped.append(fields["trade"])
                session.close("test_lost_commit_ack")
                return
            original(session, request, **fields)
        with patch.object(self.server, "_trade_reply", side_effect=drop_committed_ack):
            with self.assertRaises(ConnectionError):
                await self.prepare_receipt(1, view)
        self.assertEqual(len(dropped), 1)
        await wait_until(lambda: self.companions[1].connected and self.companions[1].session_epoch != old_epoch)
        fate = (await self.rpc(1, "status", transaction_id=self.transaction))["trade"]
        self.assertEqual(fate, dropped[0])
        self.assertEqual(await self.confirm(1, view), fate)
        self.assertEqual((await CheckpointClient(self.companions[0]).info())["revision"], 2)
        await self.ack(0); await self.ack(1)
        self.store.integrity_check()

    async def test_restart_aborts_uncommitted_proposal_and_requires_new_generation_consent(self):
        view = await self.ready()
        await self.confirm(0, view)
        await self.restart()
        self.assertEqual((await self.rpc(0, "status", transaction_id=self.transaction))["trade"]["state"], "aborted")
        self.assertEqual((await CheckpointClient(self.companions[0]).info())["revision"], 1)
        fresh = await self.ready()
        self.assertNotEqual(fresh["generation"], view["generation"])
        await self.assert_trade_error("trade_generation_mismatch", 1, "confirm", transaction_id=self.transaction,
            generation=view["generation"], fingerprint=view["fingerprint"])
        self.assertEqual((await self.confirm(1, fresh))["state"], "offering")
        self.assertEqual((await self.finish_preparation(await self.confirm(0, fresh)))["state"], "committed")
        self.store.integrity_check()

    async def test_a_trade_window_learns_why_its_trade_ended(self):
        # end_reason_version 1 (the owner's report of 2026-10-24: "it kicked us out and said trade cancelled"): the
        # host says who cancelled, from each side, to a status that asks, and acknowledges the feature.
        view = await self.ready()
        await self.confirm(0, view)
        cancelled = (await self.rpc(1, "cancel", transaction_id=self.transaction, generation=view["generation"]))["trade"]
        self.assertEqual(cancelled, {"transaction_id": self.transaction, "state": "aborted"})
        for index, reason in ((0, "partner_cancelled"), (1, "you_cancelled")):
            reply = await self.rpc(index, "status", transaction_id=self.transaction, end_reason_version=1)
            self.assertEqual(reply["end_reason_version"], 1)
            self.assertEqual(reply["trade"], {"transaction_id": self.transaction, "state": "aborted", "reason": reason})
        # A status that does not ask gets the reply as before.
        reply = await self.rpc(0, "status", transaction_id=self.transaction)
        self.assertNotIn("end_reason_version", reply)
        self.assertEqual(reply["trade"], {"transaction_id": self.transaction, "state": "aborted"})

    async def test_a_launchers_own_cancel_is_never_told_as_the_friends_choice(self):
        # end_reason_version 2: a launcher that cancels on its own after an error in its trade window says so (cause
        # "automatic"); the friend's window learns the trade stopped on the other side, not "Your friend cancelled the
        # trade" (the owner's reports of 2026-10-24). A window asking with version 1 is told no reason rather than a
        # wrong one, and the coordinator's helper only sends the cause to a host that acknowledged version 2.
        from emerald_multiplayer.live_trade import automatic_cancel_fields
        view = await self.ready()
        self.assertEqual(await automatic_cancel_fields(self.companions[1], self.transaction), {"cause": "automatic"})
        await self.rpc(1, "cancel", transaction_id=self.transaction, generation=view["generation"], cause="automatic")
        for index, reason in ((0, "partner_stopped"), (1, "you_stopped")):
            reply = await self.rpc(index, "status", transaction_id=self.transaction, end_reason_version=2)
            self.assertEqual(reply["end_reason_version"], 2)
            self.assertEqual(reply["trade"]["reason"], reason)
            reply = await self.rpc(index, "status", transaction_id=self.transaction, end_reason_version=1)
            self.assertEqual(reply["end_reason_version"], 1)
            self.assertNotIn("reason", reply["trade"])
        # A cause on anything but a cancel, or another cause, is refused before it reaches the host.
        from emerald_multiplayer.protocol import ProtocolError
        with self.assertRaises(ProtocolError):
            await self.rpc(0, "status", transaction_id=self.transaction, cause="automatic")
        with self.assertRaises(ProtocolError):
            await self.rpc(0, "cancel", transaction_id=self.transaction, generation=view["generation"], cause="player")

    async def test_restart_keeps_committed_fate_and_both_apply_receipts(self):
        result = await self.commit()
        await self.restart()
        self.assertEqual((await self.rpc(1, "status", transaction_id=self.transaction))["trade"], result)
        for index in (0, 1):
            pending = (await self.rpc(index, "pending"))["recoveries"]
            self.assertEqual(len(pending), 1)
            downloaded = await CheckpointClient(self.companions[index]).download()
            self.assertEqual(downloaded.metadata, pending[0]["checkpoint"])
            self.assertEqual(downloaded.metadata["revision"], 2)
            await self.ack(index)
        self.store.integrity_check()

    async def test_authenticated_bridge_loss_renews_lease_and_invalidates_old_consent(self):
        view = await self.ready()
        await self.confirm(0, view)
        companion = self.companions[0]
        old_epoch, old_incarnation = companion.session_epoch, companion.save_incarnation
        await self.bridges[0].close()
        await wait_until(lambda: companion.connected and companion.session_epoch != old_epoch and companion._bridge is None)
        bridge = await self.connect_bridge(companion)
        self.bridges.append(bridge)
        self.assertGreater(companion.save_incarnation, old_incarnation)
        self.assertGreater(companion.session_epoch, old_epoch)
        await self.assert_trade_error("trade_aborted", 1, "confirm", transaction_id=self.transaction,
            generation=view["generation"], fingerprint=view["fingerprint"])
        self.assertEqual((await self.rpc(0, "status", transaction_id=self.transaction))["trade"]["state"], "aborted")
        fresh = await self.ready()
        self.assertNotEqual(fresh["generation"], view["generation"])
        self.assertEqual((await self.confirm(1, fresh))["confirmations"], [self.players[1].player_id])
        self.assertEqual((await self.finish_preparation(await self.confirm(0, fresh)))["state"], "committed")
        self.store.integrity_check()

    async def test_changed_offer_clears_both_consents_and_old_fingerprint_is_rejected(self):
        view = await self.ready()
        await self.confirm(0, view)
        changed = (await self.rpc(0, "offer", transaction_id=self.transaction, generation=view["generation"],
            revision=1, sha256=self.heads[0].sha256, serial=self.grants[0].start+1))["trade"]
        self.assertEqual(changed["confirmations"], [])
        self.assertNotEqual(changed["fingerprint"], view["fingerprint"])
        await self.assert_trade_error("trade_offer_changed", 1, "confirm", transaction_id=self.transaction,
            generation=view["generation"], fingerprint=view["fingerprint"])
        self.assertEqual((await self.confirm(1, changed))["state"], "offering")
        self.assertEqual((await self.finish_preparation(await self.confirm(0, changed)))["state"], "committed")
        self.store.integrity_check()

    async def test_schema3_default_keeps_trade_disabled_without_disrupting_checkpoints(self):
        await self.restart(enable_trades=False)
        self.assertIsNone(self.server.trade_desk)
        for operation, fields in (
            ("open", dict(peer=self.players[1].player_id)),
            ("offer", dict(generation=str(uuid4()), revision=1, sha256=self.heads[0].sha256,
                          serial=self.grants[0].start)),
            ("confirm", dict(generation=str(uuid4()), fingerprint="a"*64)),
            ("cancel", dict(generation=str(uuid4()))),
        ):
            await self.assert_trade_error("trade_disabled", 0, operation, transaction_id=self.transaction, **fields)
        self.assertEqual((await self.rpc(0, "pending"))["recoveries"], [])
        self.assertEqual((await self.rpc(0, "status", transaction_id=self.transaction))["trade"]["state"], "aborted")
        for index in range(3):
            self.assertEqual((await CheckpointClient(self.companions[index]).info())["revision"], 1)
            self.assertTrue(self.companions[index].connected)
        self.store.integrity_check()


class TradeGateTests(unittest.TestCase):
    def test_explicit_development_gate_requires_schema3_and_boolean_opt_in(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy = OwnershipCheckpointStore(Path(directory)/"schema2.sqlite3", "build", BASELINE_RULESET)
            trade = TradeCheckpointStore(Path(directory)/"schema3.sqlite3", "build", BASELINE_RULESET)
            config = ServerConfig("build", BASELINE_RULESET)
            try:
                self.assertIsNone(WorldServer(config, store=legacy).trade_desk)
                self.assertIsNone(WorldServer(config, store=trade).trade_desk)
                self.assertIsNone(WorldServer(config, store=legacy)._trade_recovery_desk)
                self.assertIsNotNone(WorldServer(config, store=trade)._trade_recovery_desk)
                with self.assertRaisesRegex(ValueError, "schema-3"):
                    WorldServer(config, store=legacy, development_trades=True)
                with self.assertRaisesRegex(ValueError, "boolean"):
                    WorldServer(config, store=trade, development_trades=1)
            finally:
                legacy.close(); trade.close()
