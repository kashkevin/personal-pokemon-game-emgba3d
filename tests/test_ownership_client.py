from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator, LiveSaveError
from emerald_multiplayer.ownership_client import parse_status, grant_bytes
from emerald_multiplayer.save_mailbox import Opcode, SaveControl, SaveMailboxError

PROFILE = "rhh-1.17.1-bb1093-ownership-v1"


def status(*, flags=0, missing=2, remaining=0, retired=0, world=None, player=None,
           grant=None, next_id=0, end=0, lease=0, incarnation=0):
    ids = [bytes(16) if value is None else UUID(value).bytes for value in (world, player, grant)]
    return struct.pack("<IIII16s16s16sIIII", flags, missing, remaining, retired, *ids,
                       next_id, end, lease, incarnation)


class OwnershipControlTests(unittest.TestCase):
    def test_strict_status_and_control_lengths(self):
        self.assertEqual(parse_status(status()).missing, 2)
        for data in (bytes(79), status(flags=4), status(missing=433), status(retired=129),
                     status(flags=2), status(remaining=1), status(world=str(uuid4()))):
            with self.subTest(data=data[:16]), self.assertRaises(SaveMailboxError):
                parse_status(data)
        grant = dict(world_id=str(uuid4()), player_id=str(uuid4()), grant_id=str(uuid4()), start=1, end_exclusive=33)
        payload = grant_bytes(grant, enroll=True)
        self.assertEqual(len(payload), 60)
        control = SaveControl(2, 3, str(uuid4()), 4, 0, 131072, 0, Opcode.GRANT_OWNERSHIP, data=payload)
        self.assertEqual(SaveControl.unpack(control.pack()).validate_command(), control)
        self.assertEqual(struct.unpack_from("<III", payload, 48), (1, 33, 1))

    def test_inactive_grant_has_no_remaining_authority(self):
        fields = dict(world=str(uuid4()), player=str(uuid4()), grant=str(uuid4()), next_id=3, end=33, lease=7, incarnation=2)
        self.assertFalse(parse_status(status(flags=1, **fields)).active_grant)
        self.assertEqual(parse_status(status(flags=3, remaining=30, **fields)).remaining, 30)
        with self.assertRaises(SaveMailboxError):
            parse_status(status(flags=1, remaining=30, **fields))


class OwnershipPreparationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.world, self.player = str(uuid4()), str(uuid4())
        self.session = (self.world, 7, 2)
        self.c = SimpleNamespace(config=SimpleNamespace(player_id=self.player, ownership_enabled=True),
            save_profile=PROFILE, connected=True, world_id=self.world, session_epoch=7,
            save_incarnation=2, checkpoint_rpc=AsyncMock())
        self.coordinator = LiveCheckpointCoordinator(self.c, Path(self.temp.name))
        self.coordinator._command = AsyncMock(return_value=SimpleNamespace(data=status()))

    async def asyncTearDown(self):
        self.temp.cleanup()

    async def test_explicit_enrollment_required_before_allocation(self):
        with self.assertRaises(LiveSaveError) as error:
            await self.coordinator._prepare_ownership(self.session, 0, enroll=False)
        self.assertEqual(error.exception.code, "enrollment_required")
        self.c.checkpoint_rpc.assert_not_awaited()

    async def test_enrollment_records_range_before_sending_it_to_rom(self):
        grant = dict(world_id=self.world, player_id=self.player, grant_id=str(uuid4()), start=1,
                     end_exclusive=33, lease_epoch=7, incarnation=2, expected_revision=0)
        self.c.checkpoint_rpc.return_value = {"grant": grant}
        async def command(session, operation_id, revision, opcode, **fields):
            if opcode == Opcode.QUERY_OWNERSHIP:
                return SimpleNamespace(data=status())
            self.assertTrue((Path(self.temp.name) / (grant["grant_id"] + ".grant.json")).exists())
            self.assertEqual(fields["data"], grant_bytes(grant, enroll=True))
            return SimpleNamespace(data=status(flags=3, remaining=32, world=self.world, player=self.player,
                grant=grant["grant_id"], next_id=1, end=33, lease=7, incarnation=2))
        self.coordinator._command.side_effect = command
        await self.coordinator._prepare_ownership(self.session, 0, enroll=True)
        self.c.checkpoint_rpc.assert_awaited_once_with("ownership_grant", expected_revision=0, incarnation=2, count=32)

    async def test_stale_or_foreign_grant_never_reaches_rom(self):
        grant = dict(world_id=self.world, player_id=str(uuid4()), grant_id=str(uuid4()), start=1,
                     end_exclusive=33, lease_epoch=7, incarnation=2, expected_revision=0)
        self.c.checkpoint_rpc.return_value = {"grant": grant}
        with self.assertRaises(LiveSaveError) as error:
            await self.coordinator._prepare_ownership(self.session, 0, enroll=True)
        self.assertEqual(error.exception.code, "ownership_grant")
        self.assertEqual(self.coordinator._command.await_count, 1)

    async def test_active_grant_reused_without_issuing_more_ids(self):
        self.coordinator._command.return_value = SimpleNamespace(data=status(flags=3, remaining=29,
            world=self.world, player=self.player, grant=str(uuid4()), next_id=4, end=33, lease=7, incarnation=2))
        await self.coordinator._prepare_ownership(self.session, 3, enroll=False)
        self.c.checkpoint_rpc.assert_not_awaited()

    async def test_inactive_grant_refreshes_even_with_no_missing_mon(self):
        self.coordinator._command.return_value = SimpleNamespace(data=status(flags=1, missing=0,
            world=self.world, player=self.player, grant=str(uuid4()), next_id=4, end=33, lease=7, incarnation=2))
        self.c.checkpoint_rpc.side_effect = ConnectionError("server unavailable")
        with self.assertRaises(ConnectionError):
            await self.coordinator._prepare_ownership(self.session, 3, enroll=False)
        self.c.checkpoint_rpc.assert_awaited_once_with("ownership_grant", expected_revision=3, incarnation=2, count=32)

    async def test_rom_grant_reply_must_match_exact_issued_bounds_and_session(self):
        grant = dict(world_id=self.world, player_id=self.player, grant_id=str(uuid4()), start=1,
                     end_exclusive=33, lease_epoch=7, incarnation=2, expected_revision=0)
        self.c.checkpoint_rpc.return_value = {"grant": grant}
        for changes in (dict(lease=8), dict(incarnation=3), dict(end=34, remaining=33),
                        dict(next_id=2, remaining=31)):
            values = dict(flags=3, remaining=32, world=self.world, player=self.player,
                          grant=grant["grant_id"], next_id=1, end=33, lease=7, incarnation=2)
            self.coordinator._command.side_effect = [SimpleNamespace(data=status()),
                SimpleNamespace(data=status(**{**values, **changes}))]
            with self.subTest(changes=changes), self.assertRaises(LiveSaveError) as error:
                await self.coordinator._prepare_ownership(self.session, 0, enroll=True)
            self.assertEqual(error.exception.code, "ownership_grant")


class OwnershipPendingReplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_original_frozen_ownership_bytes_reconcile_after_new_lease(self):
        # Real coordinator journal, bounded checkpoint client, schema-2 SQLite;
        # only the ROM endpoint is simulated. No IDs or payload bytes are rebuilt.
        from test_live_checkpoint import FakeCompanion
        from test_ownership_storage import source_flash, owned_flash
        from emerald_multiplayer.ownership_storage import OwnershipCheckpointStore
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            c = FakeCompanion(path, enroll=False)
            c.store.close()
            c.store = OwnershipCheckpointStore(path / "owned.sqlite3", c.config.build_id, c.config.ruleset_id)
            c.world_id = c.store.begin_server_boot().world_id
            c.identity = c.store.create_player("Owned")
            c.config.player_id = c.identity.player_id
            c.session_epoch = c.store.acquire_lease(c.identity.player_id, c.identity.credential)
            c.save_profile = PROFILE
            c.store.enroll_player(c.identity.player_id, source_flash())
            grant = c.store.reserve_instances(c.identity.player_id, c.session_epoch, str(uuid4()), 0, c.save_incarnation, 32)
            payload = owned_flash(grant)
            coordinator = LiveCheckpointCoordinator(c, path / "live")
            operation = str(uuid4())
            intent = coordinator._intent(coordinator._session(), operation, 0, payload)
            coordinator._save_pending(intent, payload)
            old_epoch = c.session_epoch
            c.restart()
            self.assertNotEqual(old_epoch, c.session_epoch)
            try:
                metadata = await coordinator.resolve_pending()
                self.assertEqual(metadata["revision"], 1)
                self.assertEqual(c.head().payload, payload)
                self.assertEqual(c.upload_payloads, [(operation, 0, payload)])
                self.assertFalse(coordinator.pending_path.exists())
                self.assertEqual([item.opcode for item in c.commands], [Opcode.BIND, Opcode.CANCEL])
                self.assertEqual((path / "live" / (operation + ".flash")).read_bytes(), payload)
                c.store.integrity_check()
            finally:
                c.close()


class OwnershipPersistenceAdapterTests(unittest.TestCase):
    def checkpoint(self):
        from test_ownership_storage import owned_flash
        from emerald_multiplayer.checkpoint_client import DownloadedCheckpoint
        grant = SimpleNamespace(world_id=str(uuid4()), player_id=str(uuid4()), grant_id=str(uuid4()),
                                start=1, end_exclusive=33, lease_epoch=7, incarnation=2)
        payload = owned_flash(grant, with_rtc=True)
        metadata = dict(revision=1, request_id=str(uuid4()), size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(), build_id="a" * 64,
            ruleset_id="test-rules", save_profile=PROFILE)
        return DownloadedCheckpoint(grant.world_id, grant.player_id, metadata, payload)

    def test_owned_live_receipt_and_closed_mirror_preserve_identity(self):
        from emerald_multiplayer.checkpoint_mirror import restore_checkpoint, inspect_mirror
        from emerald_multiplayer.live_receipt import record_live_apply, read_live_receipt
        checkpoint = self.checkpoint()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            receipt = record_live_apply(path / "apply.json", checkpoint, checkpoint.payload[:131072],
                operation_id=str(uuid4()), session_epoch=8, incarnation=3)
            self.assertEqual(read_live_receipt(path / "apply.json"), receipt)
            self.assertEqual(receipt.save_profile, PROFILE)
            mirror = restore_checkpoint(path / "game.sav", checkpoint, checkpoint.world_id)
            self.assertEqual(inspect_mirror(path / "game.sav"), mirror)
            self.assertEqual((path / "game.sav").read_bytes(), checkpoint.payload)

    def test_owned_receipt_and_mirror_reject_foreign_envelope_before_writing(self):
        from dataclasses import replace
        from emerald_multiplayer.checkpoint_mirror import restore_checkpoint, MirrorError
        from emerald_multiplayer.live_receipt import record_live_apply, LiveReceiptError
        original = self.checkpoint()
        checkpoint = replace(original, player_id=str(uuid4()))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with self.assertRaises(LiveReceiptError):
                record_live_apply(path / "apply.json", checkpoint, checkpoint.payload[:131072],
                    operation_id=str(uuid4()), session_epoch=8, incarnation=3)
            with self.assertRaises(MirrorError):
                restore_checkpoint(path / "game.sav", checkpoint, checkpoint.world_id)
            self.assertFalse((path / "apply.json").exists())
            self.assertFalse((path / "game.sav").exists())

    def test_existing_mirror_checks_embedded_owner_against_sidecar(self):
        from emerald_multiplayer.checkpoint_mirror import restore_checkpoint, inspect_mirror, sidecar_path, MirrorError
        checkpoint = self.checkpoint()
        with tempfile.TemporaryDirectory() as directory:
            save = Path(directory) / "game.sav"
            restore_checkpoint(save, checkpoint, checkpoint.world_id)
            sidecar = sidecar_path(save)
            original = json.loads(sidecar.read_text())
            for field in ("world_id", "player_id"):
                sidecar.write_text(json.dumps({**original, field: str(uuid4())}))
                with self.subTest(field=field), self.assertRaises(MirrorError) as error:
                    inspect_mirror(save)
                self.assertEqual(error.exception.code, "ownership_mismatch")
            self.assertEqual(save.read_bytes(), checkpoint.payload)


if __name__ == "__main__":
    unittest.main()
