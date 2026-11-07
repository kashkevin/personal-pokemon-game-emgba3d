"""Save integrity on a real full disk (KNOWN_ISSUES MS-214 and MS-215): the host's world database, and the player's save
journal, each on a small volume filled to its last byte; then room again.

TEST_LEDGER's runs of 2026-11-07 used a Linux tmpfs ("Save integrity: the host's disk full while a player saves", "...
the player's own disk full while saving to a world"). These tests repeat them on any small volume of its own: the
environment variable EMERALD_FULL_DISK_DIR names a directory on it (the Windows run's app tests attach a 64 MB NTFS
virtual disk for them: .github/workflows/windows-package.yml). The tests fill that volume with a file of zeros and
delete it again. Without the variable they are skipped, and they refuse a volume of more than 256 MB: a test must never
fill the disk it runs from.

What a full disk refuses depends on the file system (NTFS keeps a small file's bytes in its file record, so a short
journal or receipt can still be written when no cluster is free), so where a step may go either way the test accepts
both outcomes, checks what must hold in each (nothing lost, nothing doubled, nothing stray left), and prints which one
happened, for the run's log.
"""
from __future__ import annotations

import asyncio
import base64
import errno
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
import uuid

from emerald_multiplayer.companion import BASELINE_RULESET, verify_rom_manifest
from emerald_multiplayer.flash import LAYOUT_ID
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator, LiveSaveError
from emerald_multiplayer.protocol import CHECKPOINT_CHUNK_BYTES
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.storage import CheckpointStore

from test_checkpoint_server import Client, fingerprint
from test_companion import make_files
from test_flash import make_flash
from test_live_checkpoint import FakeCompanion

VOLUME_LIMIT = 256 * 1024 * 1024
DISK_FULL_WINERRORS = {39, 112}         # ERROR_HANDLE_DISK_FULL, ERROR_DISK_FULL


def small_volume() -> Path:
    """The directory on a small volume of its own the tests may fill (EMERALD_FULL_DISK_DIR), or the test is skipped."""
    name = os.environ.get("EMERALD_FULL_DISK_DIR")
    if not name:
        raise unittest.SkipTest("EMERALD_FULL_DISK_DIR is not set: no small volume of its own to fill")
    path = Path(name)
    path.mkdir(parents=True, exist_ok=True)
    total = shutil.disk_usage(path).total
    if total > VOLUME_LIMIT:
        raise AssertionError(f"EMERALD_FULL_DISK_DIR is on a volume of {total:,} bytes: refusing to fill it "
                             f"(at most {VOLUME_LIMIT:,})")
    return path


def disk_full(error: OSError) -> bool:
    return error.errno == errno.ENOSPC or getattr(error, "winerror", None) in DISK_FULL_WINERRORS


def fill(path: Path) -> int:
    """Write zeros to `path` until the volume refuses even a byte; returns the bytes written."""
    written = 0
    with open(path, "wb", buffering=0) as handle:
        for size in (1 << 20, 65536, 4096, 512, 1):
            block = bytes(size)
            while True:
                try:
                    written += handle.write(block)
                except OSError as error:
                    if not disk_full(error):
                        raise
                    break
    return written


def integrity(path: Path) -> str:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)     # file:///R:/... on Windows
    try:
        return connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()


class FullDiskCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.volume = small_volume()
        self.here = self.volume / f"{type(self).__name__}-{uuid.uuid4().hex[:8]}"
        self.here.mkdir()
        self.filler = self.volume / f"filler-{uuid.uuid4().hex[:8]}.bin"
        self.addCleanup(shutil.rmtree, self.here, True)
        self.addCleanup(self.free)

    def fill(self) -> int:
        written = fill(self.filler)
        with self.assertRaises(OSError, msg="the volume still takes 64 KB after the filler") as caught:
            with open(self.volume / "probe.bin", "wb", buffering=0) as probe:
                probe.write(bytes(65536))
        (self.volume / "probe.bin").unlink(missing_ok=True)
        self.assertTrue(disk_full(caught.exception), caught.exception)
        print(f"[{self.id().rsplit('.', 1)[-1]}] filled: {written:,} bytes written, "
              f"{shutil.disk_usage(self.volume).free:,} free as the volume says")
        return written

    def free(self):
        self.filler.unlink(missing_ok=True)

    def say(self, what):
        print(f"[{self.id().rsplit('.', 1)[-1]}] {what}")


class HostDiskFullTests(FullDiskCase):
    """KNOWN_ISSUES MS-214: the host's disk fills while a player saves. A real WorldServer and CheckpointStore with the
    world's database on the small volume, a real client over TCP speaking the checkpoint protocol."""

    async def stage(self, client, payload, revision, upload_id):
        values = fingerprint(payload, revision)
        result = await client.rpc("begin", request_id=upload_id, **values)
        if result["type"] != "checkpoint_result":
            return values, result
        for offset in range(result["next_offset"], len(payload), CHECKPOINT_CHUNK_BYTES):
            result = await client.rpc("chunk", upload_id=upload_id, offset=offset,
                                      data_b64=base64.b64encode(payload[offset:offset + CHECKPOINT_CHUNK_BYTES])
                                      .decode("ascii"))
            if result["type"] != "checkpoint_result":
                return values, result
        return values, None

    async def save(self, client, payload, revision):
        upload_id = str(uuid.uuid4())
        values, refused = await self.stage(client, payload, revision, upload_id)
        if refused is not None:
            return upload_id, values, refused
        return upload_id, values, await client.rpc("commit", upload_id=upload_id, **values)

    async def test_a_save_refused_while_the_hosts_disk_is_full_is_kept_and_committed_once_there_is_room(self):
        with tempfile.TemporaryDirectory() as fixtures:
            rom, manifest = make_files(fixtures)
            build = verify_rom_manifest(rom, manifest)[0]
            database = self.here / "world.sqlite3"
            store = CheckpointStore(database, build, BASELINE_RULESET, LAYOUT_ID)
            owner = store.create_player("Player A")
            server = WorldServer(ServerConfig(build, BASELINE_RULESET, heartbeat_interval=0.5, idle_timeout=30.0,
                                              monitor_interval=0.05), store=store)
            await server.start(port=0)
            client = None
            try:
                client, _ = await Client.connect(server.address, owner, build)
                first, second, third = make_flash(counter=2), make_flash(counter=3), make_flash(counter=4)
                _, _, result = await self.save(client, first, 0)
                self.assertEqual((result["type"], result["checkpoint"]["revision"]), ("checkpoint_result", 1), result)

                self.fill()
                upload_id, values, refused = await self.save(client, second, 1)
                # Every step the host could not store is refused as storage_error, the save staying unsent; nothing
                # else.
                self.assertNotEqual(refused["type"], "checkpoint_result", "a save committed on a full disk")
                self.assertEqual(refused.get("code"), "storage_error", refused)
                self.say(f"the save with the host's disk full: {refused.get('operation') or refused['type']} refused, "
                         f"{refused.get('code')}: {refused.get('message')}")
                info = await client.rpc("info")
                self.assertEqual((info["type"], info["checkpoint"]["revision"]), ("checkpoint_result", 1), info)
                head = store.read_checkpoint(owner.player_id, client.epoch)
                self.assertEqual((head.revision, head.payload), (1, first))
                self.assertEqual(integrity(database), "ok")

                self.free()
                retry = await client.rpc("commit", upload_id=upload_id, **values)
                if retry["type"] != "checkpoint_result":      # refused before the commit: staged again
                    upload_id, values, retry = await self.save(client, second, 1)
                self.assertEqual((retry["type"], retry["checkpoint"]["revision"]), ("checkpoint_result", 2), retry)
                head = store.read_checkpoint(owner.player_id, client.epoch)
                self.assertEqual((head.revision, head.payload, head.request_id), (2, second, upload_id))
                _, _, result = await self.save(client, third, 2)
                self.assertEqual((result["type"], result["checkpoint"]["revision"]), ("checkpoint_result", 3), result)
            finally:
                if client is not None:
                    await client.close()
                await server.close()
                store.close()
            self.assertEqual(integrity(database), "ok")
            reopened = CheckpointStore(database, build, BASELINE_RULESET, LAYOUT_ID)    # a host started again
            try:
                reopened.integrity_check()
                reopened.begin_server_boot()
                head = reopened.read_checkpoint(owner.player_id, reopened.acquire_lease(owner.player_id,
                                                                                        owner.credential))
                self.assertEqual((head.revision, head.payload), (3, third))
            finally:
                reopened.close()


class PlayerDiskFullTests(FullDiskCase):
    """KNOWN_ISSUES MS-215: the player's own disk fills while saving to a world (the host has room). The launcher's
    world save (LiveCheckpointCoordinator) with its folder on the small volume; the world's store on the ordinary disk
    behind the test suite's strict ROM endpoint and checkpoint replies (test_live_checkpoint.FakeCompanion: the real
    codecs and store)."""

    def setUp(self):
        super().setUp()
        self.ordinary = tempfile.TemporaryDirectory()
        self.addCleanup(self.ordinary.cleanup)
        self.companion = FakeCompanion(Path(self.ordinary.name))
        self.addCleanup(self.companion.close)
        self.coordinator = LiveCheckpointCoordinator(self.companion, self.here / "live")
        self.companion.pending_journal = self.coordinator.pending_path

    def folder(self):
        return sorted(path.name for path in self.coordinator.directory.iterdir()) \
            if self.coordinator.directory.exists() else []

    def assert_released(self):
        self.assertIsNone(self.companion.mode)                      # the game's export let go or ended
        self.assertIsNone(self.companion._live_save_owner)
        self.assertFalse(self.companion.live_checkpoint_lock.locked())

    async def test_a_save_this_pc_cannot_store_is_refused_definitely_and_the_next_one_saves(self):
        base = self.companion.head().revision
        self.fill()
        before = self.folder()
        with self.assertRaises(LiveSaveError) as refused:
            await self.coordinator.checkpoint(expected_revision=base)
        self.assertEqual(refused.exception.code, "local_storage")
        self.assertTrue(refused.exception.safe_to_retry)
        self.say(f"the save with this PC's disk full: {refused.exception.code} ({refused.exception})")
        self.assertEqual(self.companion.head().revision, base)      # nothing sent
        self.assertEqual(self.folder(), before)                     # nothing left: no journal, no stray save
        self.assertFalse(self.coordinator.pending_path.exists())
        self.assert_released()

        self.free()
        result = await self.coordinator.checkpoint(expected_revision=base)
        self.assertEqual(result.metadata["revision"], base + 1)
        self.assertEqual(self.companion.head().revision, base + 1)
        self.assert_released()

    async def test_a_disk_that_fills_once_the_world_has_the_save_is_resolved_exactly_when_there_is_room(self):
        base = self.companion.head().revision

        async def fill_now():
            self.companion.commit_hook = None
            self.fill()
        self.companion.commit_hook = fill_now
        try:
            result = await self.coordinator.checkpoint(expected_revision=base)
        except (OSError, LiveSaveError) as error:
            # The receipt could not be written: the journal stands, and the save is resolved from the world.
            self.say(f"the receipt with this PC's disk full: {type(error).__name__} {error}")
            self.assertTrue(self.coordinator.pending_path.exists(), "no journal left for a save the world holds")
            with self.assertRaises(LiveSaveError) as later:
                await self.coordinator.checkpoint(expected_revision=base + 1)
            self.assertEqual(later.exception.code, "pending_export")
            self.free()
            resolved = await self.coordinator.resolve_pending()
            self.assertEqual(resolved["revision"], base + 1, resolved)
        else:
            # The receipt was small enough to be written with no cluster free (NTFS keeps it in its file record).
            self.say(f"the receipt with this PC's disk full: written (revision {result.metadata['revision']})")
            self.assertEqual(result.metadata["revision"], base + 1)
            self.free()
        self.assertFalse(self.coordinator.pending_path.exists())
        self.assertEqual(self.companion.head().revision, base + 1)  # in the world exactly once
        # one save, its commit perhaps sent again with the same id while resolving (the world keeps it once), no other
        self.assertEqual(len({name for name, revision, _ in self.companion.upload_payloads if revision == base}), 1)
        self.assert_released()
        result = await self.coordinator.checkpoint(expected_revision=base + 1)
        self.assertEqual((result.metadata["revision"], self.companion.head().revision), (base + 2, base + 2))
        stray = [name for name in self.folder() if name.endswith(".flash")
                 and not (self.coordinator.directory / (name[:-len(".flash")] + ".export.json")).exists()]
        self.assertEqual(stray, [])


if __name__ == "__main__":
    unittest.main()
