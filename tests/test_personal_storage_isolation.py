"""Update 30, phase 11: personal storage stays personal.

Two players share one world. Each player's party, PC boxes, Day Care eggs, bag (Shiny Charm, Mega items) and progress live in that
player's own canonical save, so the world must keep one head per player and never mix them: not on upload, not on read, not after a
disconnect and reconnect, not after the server restarts. These tests use the real server, store and strict flash validator; the saves
are synthetic (one differs from the other in trainer, counter and Day Care egg queue) because the server treats a save as opaque
bytes after validation. Whatever is in the bag or the boxes therefore cannot cross over unless a whole save does.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
from pathlib import Path
import tempfile
import unittest
import uuid

from emerald_multiplayer.companion import BASELINE_RULESET, verify_rom_manifest
from emerald_multiplayer.flash import LAYOUT_ID, inspect_flash
from emerald_multiplayer.protocol import CHECKPOINT_CHUNK_BYTES
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.storage import CheckpointStore

from test_checkpoint_server import Client, fingerprint
from test_companion import make_files
import test_flash
from test_flash import make_flash

EGG_OFFSET = 600
EGG_SIZE = 412


def save_with_eggs(trainer_id, counter, eggs):
    return test_flash.FlashTests._put_block3(make_flash(trainer_id=trainer_id, counter=counter), EGG_OFFSET, test_flash.FlashTests._egg_queue(eggs))


class PersonalStorageIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.rom, self.manifest = make_files(self.temp.name)
        self.build = verify_rom_manifest(self.rom, self.manifest)[0]
        self.path = Path(self.temp.name) / "world.sqlite3"
        self.store = CheckpointStore(self.path, self.build, BASELINE_RULESET, LAYOUT_ID)
        self.alice = self.store.create_player("Alice")
        self.bob = self.store.create_player("Bob")
        self.config = ServerConfig(self.build, BASELINE_RULESET, heartbeat_interval=0.15, idle_timeout=3.0, monitor_interval=0.005)
        self.server = WorldServer(self.config, store=self.store)
        await self.server.start(port=0)
        self.clients = []
        self.alice_save = save_with_eggs(0x11110001, 2, 3)
        self.bob_save = save_with_eggs(0x22220002, 2, 1)

    async def asyncTearDown(self):
        for client in self.clients:
            try:
                await client.close()
            except Exception:
                pass
        await self.server.close()
        self.store.close()
        self.temp.cleanup()

    async def connect(self, owner):
        client, result = await Client.connect(self.server.address, owner, self.build)
        self.assertEqual(result["type"], "welcome")
        self.clients.append(client)
        return client

    async def upload(self, client, payload, revision=0):
        upload_id = str(uuid.uuid4())
        values = fingerprint(payload, revision)
        self.assertEqual((await client.rpc("begin", request_id=upload_id, **values))["type"], "checkpoint_result")
        for offset in range(0, len(payload), CHECKPOINT_CHUNK_BYTES):
            chunk = payload[offset:offset + CHECKPOINT_CHUNK_BYTES]
            result = await client.rpc("chunk", upload_id=upload_id, offset=offset, data_b64=base64.b64encode(chunk).decode("ascii"))
            self.assertEqual(result["type"], "checkpoint_result")
        result = await client.rpc("commit", upload_id=upload_id, **values)
        self.assertEqual(result["type"], "checkpoint_result", result.get("code"))
        return result["checkpoint"]

    async def download(self, client, revision):
        data = bytearray()
        while True:
            result = await client.rpc("read", expected_revision=revision, offset=len(data), length=4096)
            self.assertEqual(result["type"], "checkpoint_result", result.get("code"))
            data.extend(base64.b64decode(result["data_b64"], validate=True))
            if result["eof"]:
                return bytes(data)

    async def test_each_player_has_an_independent_head_and_gets_only_their_own_save_back(self):
        alice, bob = await self.connect(self.alice), await self.connect(self.bob)
        a_head = await self.upload(alice, self.alice_save)
        self.assertIsNone((await bob.rpc("info"))["checkpoint"])
        b_head = await self.upload(bob, self.bob_save)
        self.assertEqual((a_head["revision"], b_head["revision"]), (1, 1))
        self.assertNotEqual(a_head["sha256"], b_head["sha256"])
        self.assertEqual((await alice.rpc("info"))["checkpoint"], a_head)
        self.assertEqual((await bob.rpc("info"))["checkpoint"], b_head)
        got_a, got_b = await self.download(alice, 1), await self.download(bob, 1)
        self.assertEqual(got_a, self.alice_save)
        self.assertEqual(got_b, self.bob_save)
        # Each save carries its own Day Care egg queue (SaveBlock3), and the one that came back is byte-identical to the one sent.
        self.assertNotEqual(got_a, got_b)
        self.assertNotIn(self.bob_save, (got_a,))
        self.assertTrue(inspect_flash(got_a).save_block3 is not None and inspect_flash(got_b).save_block3 is not None)
        # A save made for one trainer can never become the other player's next revision.
        upload_id = str(uuid.uuid4())
        values = fingerprint(self.alice_save, 1)
        await bob.rpc("begin", request_id=upload_id, **values)
        for offset in range(0, len(self.alice_save), CHECKPOINT_CHUNK_BYTES):
            chunk = self.alice_save[offset:offset + CHECKPOINT_CHUNK_BYTES]
            await bob.rpc("chunk", upload_id=upload_id, offset=offset, data_b64=base64.b64encode(chunk).decode("ascii"))
        refused = await bob.rpc("commit", upload_id=upload_id, **values)
        self.assertEqual(refused["type"], "checkpoint_error")
        self.assertEqual((await bob.rpc("info"))["checkpoint"], b_head)
        self.assertEqual((await alice.rpc("info"))["checkpoint"], a_head)

    async def test_disconnect_reconnect_and_the_other_players_progress_do_not_mix_saves(self):
        alice, bob = await self.connect(self.alice), await self.connect(self.bob)
        a_head = await self.upload(alice, self.alice_save)
        b_head = await self.upload(bob, self.bob_save)
        await alice.close()
        self.clients.remove(alice)
        # Bob keeps playing and saves again while Alice is away.
        bob_later = save_with_eggs(0x22220002, 3, 4)
        b_head2 = await self.upload(bob, bob_later, revision=1)
        self.assertEqual(b_head2["revision"], 2)
        for _ in range(100):
            if self.alice.player_id not in self.server.sessions:
                break
            await asyncio.sleep(0.02)
        alice = await self.connect(self.alice)
        self.assertEqual((await alice.rpc("info"))["checkpoint"], a_head)          # still her revision 1
        self.assertEqual(await self.download(alice, 1), self.alice_save)
        self.assertEqual((await bob.rpc("info"))["checkpoint"], b_head2)
        self.assertEqual(await self.download(bob, 2), bob_later)
        # Her stale view of Bob's revision is not available to her at all: reads are always of her own head.
        stale = await alice.rpc("read", expected_revision=2, offset=0, length=16)
        self.assertEqual(stale["type"], "checkpoint_error")
        self.assertEqual(b_head["revision"], 1)

    async def test_heads_survive_a_server_restart_per_player(self):
        alice, bob = await self.connect(self.alice), await self.connect(self.bob)
        a_head, b_head = await self.upload(alice, self.alice_save), await self.upload(bob, self.bob_save)
        for client in (alice, bob):
            await client.close()
        self.clients.clear()
        await self.server.close()
        self.store.close()
        self.store = CheckpointStore(self.path, self.build, BASELINE_RULESET, LAYOUT_ID)
        self.server = WorldServer(self.config, store=self.store)
        await self.server.start(port=0)
        alice, bob = await self.connect(self.alice), await self.connect(self.bob)
        self.assertEqual((await alice.rpc("info"))["checkpoint"]["sha256"], a_head["sha256"])
        self.assertEqual((await bob.rpc("info"))["checkpoint"]["sha256"], b_head["sha256"])
        self.assertEqual(hashlib.sha256(await self.download(alice, 1)).hexdigest(), a_head["sha256"])
        self.assertEqual(hashlib.sha256(await self.download(bob, 1)).hexdigest(), b_head["sha256"])

    async def test_a_player_without_credentials_cannot_reach_anyones_save(self):
        alice = await self.connect(self.alice)
        await self.upload(alice, self.alice_save)
        for changes in (dict(credential=None), dict(credential=self.bob.credential.hex())):
            client, result = await Client.connect(self.server.address, self.alice, self.build, **changes)
            self.clients.append(client)
            self.assertEqual(result["type"], "error")
            self.assertEqual(result["code"], "credentials_required" if changes["credential"] is None else "credentials_invalid")


class ProfileDirectoryTests(unittest.TestCase):
    """The PC side: a character's files live under players/<world>/<player>/, so two characters on one PC never share a folder."""

    def test_two_players_in_one_world_and_one_player_in_two_worlds_get_separate_profile_folders(self):
        from emerald_multiplayer.character_links import profile_directory
        root = Path("/private")
        w1, w2, p1, p2 = (str(uuid.uuid4()) for _ in range(4))
        folders = {profile_directory(root, w1, p1), profile_directory(root, w1, p2),
                   profile_directory(root, w2, p1), profile_directory(root, w2, p2)}
        self.assertEqual(len(folders), 4)
        for folder in folders:
            self.assertEqual(folder.parent.parent, root / "players")


if __name__ == "__main__":
    unittest.main()
