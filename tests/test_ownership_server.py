from __future__ import annotations

import asyncio
import base64
from contextlib import suppress
from dataclasses import asdict
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import uuid

from emerald_multiplayer.companion import BASELINE_RULESET
from emerald_multiplayer.ownership_protocol import OWNERSHIP_PROFILE, validate_ownership_reply
from emerald_multiplayer.ownership_storage import AllocationGrant, OwnershipCheckpointStore
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.storage import CheckpointStore
from test_checkpoint_server import Client
from test_ownership_storage import source_flash, owned_flash


BUILD = "synthetic-ownership-build"


class OwnedClient(Client):
    async def grant(self, *, request_id=None, revision=0, incarnation=1, count=32):
        request_id = request_id or str(uuid.uuid4())
        await self.send(dict(type="ownership_grant", session_epoch=self.epoch, request_id=request_id,
                             expected_revision=revision, incarnation=incarnation, count=count))
        while True:
            message = await self.next()
            if message is None:
                raise AssertionError("ownership connection unexpectedly closed")
            if message.get("request_id") == request_id:
                return message


class OwnershipServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = OwnershipCheckpointStore(Path(self.temp.name) / "owned.sqlite3", BUILD, BASELINE_RULESET)
        self.players = [self.store.create_player("Player " + label) for label in ("A", "B")]
        for index, owner in enumerate(self.players):
            self.store.enroll_player(owner.player_id, source_flash(personalities=(7 + index,)))
        self.server = WorldServer(ServerConfig(BUILD, BASELINE_RULESET, heartbeat_interval=.05, idle_timeout=3), store=self.store)
        await self.server.start(port=0)
        self.clients = []

    async def asyncTearDown(self):
        for client in self.clients:
            await client.close()
        await self.server.close()
        self.store.close()
        self.temp.cleanup()

    async def connect(self, owner):
        client, welcome = await OwnedClient.connect(self.server.address, owner, BUILD)
        self.clients.append(client)
        self.assertEqual(welcome["save_profile"], OWNERSHIP_PROFILE)
        return client, welcome

    async def allocation(self, client, welcome, **kwargs):
        response = await client.grant(**kwargs)
        validate_ownership_reply(response, SimpleNamespace(player_id=client.owner.player_id),
                                 OWNERSHIP_PROFILE, welcome["world_id"], client.epoch)
        self.assertEqual(response["type"], "checkpoint_result", response.get("code"))
        return AllocationGrant(**response["grant"])

    async def upload(self, client, payload, *, revision=0, request_id=None):
        request_id = request_id or str(uuid.uuid4())
        fingerprint = dict(expected_revision=revision, size=len(payload), sha256=hashlib.sha256(payload).hexdigest(),
                           save_profile=OWNERSHIP_PROFILE)
        begin = await client.rpc("begin", request_id=request_id, **fingerprint)
        self.assertEqual(begin["type"], "checkpoint_result", begin.get("code"))
        for offset in range(begin["next_offset"], len(payload), 4096):
            chunk = await client.rpc("chunk", upload_id=request_id, offset=offset,
                                     data_b64=base64.b64encode(payload[offset:offset + 4096]).decode("ascii"))
            self.assertEqual(chunk["type"], "checkpoint_result", chunk.get("code"))
        return await client.rpc("commit", upload_id=request_id, **fingerprint)

    async def test_two_real_tcp_players_grants_checkpoints_presence_and_heartbeat(self):
        a, welcome_a = await self.connect(self.players[0])
        b, welcome_b = await self.connect(self.players[1])
        grant_a = await self.allocation(a, welcome_a)
        grant_b = await self.allocation(b, welcome_b)
        self.assertLessEqual(grant_a.end_exclusive, grant_b.start)
        stop = asyncio.Event()
        async def other_player():
            seq = 0
            while not stop.is_set():
                seq += 1
                await b.move(seq=seq)
                info = await b.rpc("info")
                self.assertEqual(info["type"], "checkpoint_result")
                await asyncio.sleep(.01)
            return seq
        task = asyncio.create_task(other_player())
        try:
            result = await self.upload(a, owned_flash(grant_a))
            self.assertEqual(result["checkpoint"]["revision"], 1)
            await asyncio.sleep(.12)
        finally:
            stop.set()
            sequences = await task
        self.assertGreater(sequences, 1)
        self.assertGreater(a.pongs + b.pongs, 0)
        # The raw test client answers heartbeats while its peer transfers; real
        # companions always have a dedicated reader. WSL filesystem scheduling
        # can make a full SQLite-backed transfer exceed the short idle timeout.
        async def read_idle_a():
            while True:
                await a.next()
        reader_task = asyncio.create_task(read_idle_a())
        try:
            second = await self.upload(b, owned_flash(grant_b, personalities=(8,)))
        finally:
            reader_task.cancel()
            with suppress(asyncio.CancelledError):
                await reader_task
        self.assertEqual(second["checkpoint"]["revision"], 1)
        self.assertEqual([r["serial"] for r in self.store.read_ownership(self.players[0].player_id, a.epoch)], [grant_a.start])
        self.assertEqual([r["serial"] for r in self.store.read_ownership(self.players[1].player_id, b.epoch)], [grant_b.start])
        for world in a.worlds + b.worlds:
            self.assertNotIn("ownership", world)
            self.assertNotIn("grant", world)
        self.store.integrity_check()

    async def test_bad_allocation_and_invalid_ownership_keep_presence_connected(self):
        client, welcome = await self.connect(self.players[0])
        bad = await client.grant(count=True)
        self.assertEqual(bad["type"], "checkpoint_error")
        request = str(uuid.uuid4())
        first = await self.allocation(client, welcome, request_id=request)
        self.assertEqual(await self.allocation(client, welcome, request_id=request), first)
        conflicting = await client.grant(request_id=request, count=33)
        self.assertEqual(conflicting["code"], "request_conflict")
        changed = await self.upload(client, owned_flash(first, personalities=(8,)))
        self.assertEqual(changed["code"], "enrollment_inventory_mismatch")
        # The failed commit preserves the current bounded upload until abort.
        await client.rpc("abort", upload_id=self.server.sessions[client.owner.player_id].upload.upload_id)
        await client.move(seq=1)
        self.assertIsNone((await client.rpc("info"))["checkpoint"])
        accepted = await self.upload(client, owned_flash(first))
        self.assertEqual(accepted["checkpoint"]["revision"], 1)

    async def test_exact_commit_retry_after_server_restart_returns_history(self):
        client, welcome = await self.connect(self.players[0])
        grant = await self.allocation(client, welcome)
        payload, request = owned_flash(grant), str(uuid.uuid4())
        original = await self.upload(client, payload, request_id=request)
        await self.upload(client, owned_flash(grant, (), retirements=((grant.start, 1),)), revision=1)
        await client.close()
        self.clients.remove(client)
        await self.server.close()
        self.server = WorldServer(self.server.config, store=self.store)
        await self.server.start(port=0)
        fresh, welcome = await self.connect(self.players[0])
        self.assertGreater(fresh.epoch, client.epoch)
        replay = await self.upload(fresh, payload, request_id=request)
        self.assertEqual(replay["checkpoint"], original["checkpoint"])
        self.assertEqual((await fresh.rpc("info"))["checkpoint"]["revision"], 2)
        self.assertEqual(self.store.read_ownership(self.players[0].player_id, fresh.epoch), ())
        burned = await self.allocation(fresh, welcome, revision=2)
        self.assertEqual(burned.start, grant.end_exclusive)
        self.store.integrity_check()

    async def test_uncommitted_frozen_export_replays_unchanged_after_rejoin(self):
        client, welcome = await self.connect(self.players[0])
        grant = await self.allocation(client, welcome)
        payload, request = owned_flash(grant), str(uuid.uuid4())
        await client.close()
        self.clients.remove(client)
        await self.server.close()
        self.server = WorldServer(self.server.config, store=self.store)
        await self.server.start(port=0)
        fresh, _ = await self.connect(self.players[0])
        self.assertGreater(fresh.epoch, grant.lease_epoch)
        result = await self.upload(fresh, payload, request_id=request)
        self.assertEqual(result["checkpoint"]["revision"], 1)
        self.assertEqual(self.store.read_checkpoint(self.players[0].player_id, fresh.epoch).payload, payload)
        self.store.integrity_check()

    async def test_legacy_store_refuses_ownership_grant_without_breaking_checkpoint_rpc(self):
        await self.server.close()
        self.store.close()
        from emerald_multiplayer.flash import LAYOUT_ID
        self.store = CheckpointStore(Path(self.temp.name) / "legacy.sqlite3", BUILD, BASELINE_RULESET, LAYOUT_ID)
        player = self.store.create_player("Legacy")
        self.server = WorldServer(self.server.config, store=self.store)
        await self.server.start(port=0)
        client, _ = await OwnedClient.connect(self.server.address, player, BUILD)
        self.clients.append(client)
        response = await client.grant()
        self.assertEqual(response["code"], "ownership_disabled")
        self.assertIsNone((await client.rpc("info"))["checkpoint"])
