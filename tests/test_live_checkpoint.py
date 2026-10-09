"""Live orchestration tests using real codecs, client transfers and SQLite.

The ROM endpoint is a strict in-memory Flash stage, rather than an emulator.
Actual ROM freeze/reload behavior is covered separately by the core proof.
"""
from __future__ import annotations

import asyncio
import base64
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
import zlib

from emerald_multiplayer.checkpoint_client import (
    CheckpointClient, CheckpointError, DownloadedCheckpoint,
    validate_checkpoint_reply,
)
from emerald_multiplayer.checkpoint_mirror import MirrorLease
from emerald_multiplayer.companion import Companion
from emerald_multiplayer.flash import FLASH_SIZE, LAYOUT_ID, FlashError, inspect_flash
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator, LiveSaveError
from emerald_multiplayer.live_receipt import read_live_receipt
from emerald_multiplayer.protocol import MAX_COUNTER, ProtocolError
from emerald_multiplayer.save_mailbox import Opcode, SaveControl, Status, SAVE_CHUNK_SIZE
from emerald_multiplayer.storage import CheckpointStore
from test_flash import make_flash, _rewrite
from emerald_multiplayer.protocol import PROTOCOL_VERSION


def checkpoint_metadata(checkpoint):
    if checkpoint is None:
        return None
    return dict(revision=checkpoint.revision, request_id=checkpoint.request_id,
                size=len(checkpoint.payload), sha256=checkpoint.sha256,
                build_id=checkpoint.build_id, ruleset_id=checkpoint.ruleset_id,
                save_profile=checkpoint.save_profile)


class FakeCompanion:
    """Strict mailbox endpoint plus bounded RPCs backed by the real store."""

    # A guard test invokes Companion.checkpoint_rpc unbound on this fixture;
    # retain its production pending-trade check as well as the lifecycle guard.
    _guard_pending_trade_mutation = Companion._guard_pending_trade_mutation

    def __init__(self, directory: Path, *, enroll=True):
        self.store = CheckpointStore(directory / "world.sqlite3", build_id="a" * 64,
                                     ruleset_id="rules-v1", save_profile=LAYOUT_ID)
        self.world_id = self.store.begin_server_boot().world_id
        self.identity = self.store.create_player("TEST")
        self.config = SimpleNamespace(build_id=self.store.build_id,
            ruleset_id=self.store.ruleset_id, player_id=self.identity.player_id)
        self.session_epoch = self.store.acquire_lease(self.identity.player_id, self.identity.credential)
        self.connected, self.save_profile, self.save_incarnation = True, LAYOUT_ID, 2
        self.live_checkpoint_lock = asyncio.Lock()
        self._live_save_owner = self._live_binding = None
        self._live_sequence = 0
        self.commands, self.server_calls, self.upload_payloads = [], [], []
        self.uploads = {}
        self.rom_flash = make_flash(counter=3, rotation=4)
        self.rng = bytes(range(32))
        self.mode, self.stage, self.operation = None, bytearray(), None
        self.rom_commits = 0
        self.lose_commit_ack = self.lose_end_ack = False
        self.bad_end_crc = self.bad_write_position = False
        self.control_hook = self.commit_hook = None
        self.pending_journal = None
        if enroll:
            self.advance_head(make_flash(with_rtc=True))

    def close(self):
        self.store.close()

    def head(self):
        return self.store.read_checkpoint(self.config.player_id, self.session_epoch)

    def advance_head(self, payload):
        old = self.head()
        return self.store.commit_checkpoint(self.config.player_id, self.session_epoch,
            str(uuid4()), 0 if old is None else old.revision, payload,
            self.config.build_id, self.config.ruleset_id, self.save_profile)

    def restart(self):
        self.store.begin_server_boot()
        self.session_epoch = self.store.acquire_lease(self.config.player_id, self.identity.credential)
        self.save_incarnation += 1

    @staticmethod
    def _rotation(payload):
        bank = inspect_flash(payload).metadata.bank
        return (-struct.unpack_from("<H", payload, bank * 14 * 4096 + 4084)[0]) % 14

    async def save_rpc(self, control, *, timeout=12.0):
        # Exercise the actual wire codecs, including CRC/padding/length checks.
        control = SaveControl.unpack(control.pack()).validate_command()
        if (control.incarnation, control.session_epoch) != (self.save_incarnation, self.session_epoch):
            raise ConnectionError("stale ROM command")
        self.commands.append(control)
        if self.control_hook is not None:
            await self.control_hook(control)
        data, status, offset = b"", Status.OK, control.offset
        op = control.opcode
        if op == Opcode.BIND:
            self.mode, self.stage, self.operation = None, bytearray(), None
        elif op == Opcode.BEGIN_EXPORT:
            if self.mode is not None:
                raise AssertionError("overlapping ROM lifecycles")
            self.mode, self.operation = "export", control.request_id
            parsed = inspect_flash(self.rom_flash)
            data = struct.pack("<II", parsed.metadata.counter, self._rotation(self.rom_flash)) + self.rng
        elif op == Opcode.READ:
            if self.mode not in ("export", "committed") or self.operation != control.request_id:
                raise AssertionError("read outside frozen operation")
            data = self.rom_flash[offset:offset + SAVE_CHUNK_SIZE]
        elif op == Opcode.BEGIN_IMPORT:
            if self.mode is not None:
                raise AssertionError("overlapping ROM lifecycles")
            self.mode, self.operation, self.stage = "import", control.request_id, bytearray()
            self.import_crc, _, _, self.import_trainer = struct.unpack("<IIII", control.data)
            data = struct.pack("<II", 0, 0)
        elif op == Opcode.WRITE:
            if self.mode != "import" or self.operation != control.request_id or offset != len(self.stage):
                raise AssertionError("nonsequential import stage")
            self.stage.extend(control.data)
            offset = len(self.stage) + (SAVE_CHUNK_SIZE if self.bad_write_position else 0)
        elif op == Opcode.COMMIT:
            if self.mode != "import" or len(self.stage) != FLASH_SIZE or zlib.crc32(self.stage) != self.import_crc:
                raise AssertionError("incomplete or damaged import commit")
            inspect_flash(bytes(self.stage), expected_trainer_id=self.import_trainer)
            self.rom_flash, self.mode = bytes(self.stage), "committed"
            self.rom_commits += 1
        elif op == Opcode.END:
            if self.lose_end_ack:
                self.lose_end_ack = False
                raise asyncio.TimeoutError("ROM END acknowledgement lost")
            data = struct.pack("<I", zlib.crc32(self.rom_flash) ^ int(self.bad_end_crc))
            self.mode, self.stage = None, bytearray()
        elif op == Opcode.CANCEL:
            # A completed import remains published. Cancel only releases it.
            self.mode, self.stage = None, bytearray()
            status = Status.CANCELED
        else:
            raise AssertionError(op)
        response = replace(control, offset=offset, data=data, status=status)
        return SaveControl.unpack(response.pack()).validate_response()

    async def checkpoint_rpc(self, operation, *, request_id=None, **fields):
        if (self._live_save_owner is not None and self._live_save_owner is not asyncio.current_task()
                and operation in {"begin", "chunk", "commit", "abort"}):
            raise ValueError("a live-save lifecycle owns checkpoint writes")
        if not self.connected:
            raise ConnectionError("disconnected")
        self.server_calls.append((operation, dict(fields, request_id=request_id)))
        result = dict(type="checkpoint_result", protocol=PROTOCOL_VERSION, session_epoch=self.session_epoch,
                      request_id=request_id or str(uuid4()), operation=operation,
                      checkpoint=checkpoint_metadata(self.head()))
        if operation == "info":
            pass
        elif operation == "read":
            head = self.head()
            if head.revision != fields["expected_revision"]:
                raise CheckpointError("revision_conflict", "checkpoint changed")
            offset = fields["offset"]
            chunk = head.payload[offset:offset + fields["length"]]
            result.update(offset=offset, data_b64=base64.b64encode(chunk).decode("ascii"),
                          eof=offset + len(chunk) == len(head.payload))
        elif operation == "begin":
            if self.pending_journal is not None:
                # Durable intent and exact bytes must precede the first upload RPC.
                intent = json.loads(self.pending_journal.read_text())
                assert intent["operation_id"] == request_id
                assert (self.pending_journal.parent / (request_id + ".flash")).read_bytes()
            fingerprint = tuple(fields[key] for key in ("expected_revision", "size", "sha256", "save_profile"))
            historical = self.store.read_checkpoint(self.config.player_id, self.session_epoch,
                                                     revision=fields["expected_revision"] + 1)
            if historical is not None and historical.request_id == request_id:
                if (len(historical.payload), historical.sha256, historical.save_profile) != fingerprint[1:]:
                    raise CheckpointError("request_conflict", "transaction bytes changed")
                self.uploads[request_id] = (fingerprint, historical.payload)
                result.update(checkpoint=checkpoint_metadata(historical), upload_id=request_id,
                              next_offset=len(historical.payload))
            else:
                head = self.head()
                if fields["expected_revision"] != (0 if head is None else head.revision):
                    raise CheckpointError("revision_conflict", "stale upload base")
                self.uploads[request_id] = (fingerprint, bytearray())
                result.update(checkpoint=None, upload_id=request_id, next_offset=0)
        elif operation == "chunk":
            upload_id = fields["upload_id"]
            fingerprint, data = self.uploads[upload_id]
            chunk = base64.b64decode(fields["data_b64"], validate=True)
            assert isinstance(data, bytearray) and len(chunk) <= 4096 and fields["offset"] == len(data)
            data.extend(chunk)
            result.update(upload_id=upload_id, next_offset=len(data))
        elif operation == "commit":
            upload_id = fields["upload_id"]
            fingerprint, data = self.uploads[upload_id]
            assert fingerprint == tuple(fields[key] for key in ("expected_revision", "size", "sha256", "save_profile"))
            payload = bytes(data)
            assert len(payload) == fields["size"] and hashlib.sha256(payload).hexdigest() == fields["sha256"]
            checkpoint = self.store.commit_checkpoint(self.config.player_id, self.session_epoch,
                upload_id, fields["expected_revision"], payload, self.config.build_id,
                self.config.ruleset_id, self.save_profile)
            self.upload_payloads.append((upload_id, fields["expected_revision"], payload))
            result.update(checkpoint=checkpoint_metadata(checkpoint), upload_id=upload_id)
            if self.commit_hook is not None:
                await self.commit_hook()
            if self.lose_commit_ack:
                self.lose_commit_ack = False
                raise asyncio.TimeoutError("durable server commit acknowledgement lost")
        else:
            raise AssertionError(operation)
        return validate_checkpoint_reply(result, self.config, self.session_epoch, self.save_profile)


class LiveCheckpointTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.companion = FakeCompanion(self.directory)
        self.coordinator = LiveCheckpointCoordinator(self.companion, self.directory / "live")
        self.companion.pending_journal = self.coordinator.pending_path

    def tearDown(self):
        self.companion.close()
        self.temp.cleanup()

    def assert_code(self, caught, code):
        self.assertEqual(caught.exception.code, code)

    def operations(self):
        return [command.opcode for command in self.companion.commands]

    async def test_existing_character_requires_known_local_revision_before_rom_mutation(self):
        original = self.companion.rom_flash
        with self.assertRaises(LiveSaveError) as caught:
            await self.coordinator.checkpoint()
        self.assert_code(caught, "revision_required")
        self.companion.advance_head(make_flash(counter=5))
        with self.assertRaises(LiveSaveError) as caught:
            await self.coordinator.checkpoint(expected_revision=1)
        self.assert_code(caught, "revision_conflict")
        self.assertEqual(self.companion.commands, [])
        self.assertEqual(self.companion.rom_flash, original)
        self.assertEqual(self.companion.head().revision, 2)
        self.assertFalse(self.coordinator.pending_path.exists())
        self.assertEqual([op for op, _ in self.companion.server_calls], ["info", "info"])

    async def test_only_no_head_first_enrollment_can_omit_local_revision(self):
        directory = self.directory / "unenrolled"
        directory.mkdir()
        companion = FakeCompanion(directory, enroll=False)
        try:
            coordinator = LiveCheckpointCoordinator(companion, directory / "live")
            self.assertIsNone(companion.head())
            result = await coordinator.checkpoint()
            self.assertEqual(result.metadata["revision"], 1)
            self.assertEqual(companion.upload_payloads[0][1], 0)
            self.assertEqual(companion.head().payload, companion.rom_flash)
        finally:
            companion.close()

    async def test_lost_bind_ack_retries_exact_request_across_coordinator_wrappers(self):
        original_rpc = self.companion.save_rpc
        async def lose_ack(control, **kwargs):
            await original_rpc(control, **kwargs)
            raise asyncio.TimeoutError("binding applied but acknowledgement lost")
        session = self.coordinator._session()
        with patch.object(self.companion, "save_rpc", side_effect=lose_ack):
            with self.assertRaises(asyncio.TimeoutError):
                await self.coordinator._bind(session)
        first = self.companion.commands[-1]
        replacement = LiveCheckpointCoordinator(self.companion, self.coordinator.directory)
        await replacement._bind(session)
        self.assertEqual(self.companion.commands[-1], first)
        self.assertEqual(self.companion._live_sequence, 1)
        self.assertIsNone(self.companion._live_bind_pending)
        self.companion.restart()
        await replacement._bind(replacement._session())
        self.assertNotEqual(self.companion.commands[-1].request_id, first.request_id)
        self.assertGreater(self.companion.commands[-1].session_epoch, first.session_epoch)

    async def test_export_durable_intent_precedes_real_client_upload_and_releases_rom(self):
        original = self.companion.rom_flash
        result = await self.coordinator.checkpoint(expected_revision=1)
        self.assertEqual(result.metadata, checkpoint_metadata(self.companion.head()))
        self.assertEqual(result.metadata["revision"], 2)
        self.assertEqual(result.frozen_rng_hex, self.companion.rng.hex())
        self.assertEqual(result.flash_sha256, inspect_flash(original).sha256)
        self.assertEqual(self.companion.upload_payloads, [(result.operation_id, 1, original)])
        self.assertFalse(self.coordinator.pending_path.exists())
        self.assertEqual((self.coordinator.directory / (result.operation_id + ".flash")).read_bytes(), original)
        completion = json.loads((self.coordinator.directory / (result.operation_id + ".export.json")).read_text())
        self.assertEqual(completion["outcome"], "server-acknowledged-and-ROM-released")
        self.assertEqual(self.operations(), [Opcode.BIND, Opcode.BEGIN_EXPORT] + [Opcode.READ] * 1024 + [Opcode.END])
        sequences = [command.sequence for command in self.companion.commands]
        self.assertEqual(sequences, list(range(1, len(sequences) + 1)))
        self.assertEqual(self.companion.mode, None)
        self.assertIsNone(self.companion._live_save_owner)
        self.assertFalse(self.companion.live_checkpoint_lock.locked())

    async def test_uncertain_server_ack_retains_exact_bytes_base_uuid_across_restart(self):
        original = self.companion.rom_flash
        self.companion.lose_commit_ack = True
        with self.assertRaises(asyncio.TimeoutError):
            await self.coordinator.checkpoint(expected_revision=1)
        journal_bytes = self.coordinator.pending_path.read_bytes()
        intent = json.loads(journal_bytes)
        self.assertEqual(intent["expected_revision"], 1)
        self.assertEqual(intent["sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual((self.coordinator.directory / (intent["operation_id"] + ".flash")).read_bytes(), original)
        committed = checkpoint_metadata(self.companion.head())
        self.assertEqual(committed["request_id"], intent["operation_id"])
        for action in (self.coordinator.checkpoint, self.coordinator.recover):
            with self.assertRaises(LiveSaveError) as caught:
                await action()
            self.assert_code(caught, "pending_export")
        # Even a newer canonical head cannot change the original retry base.
        self.companion.advance_head(make_flash(counter=6))
        self.companion.restart()
        self.companion.rom_flash = make_flash(counter=9)
        start = len(self.companion.server_calls)
        self.assertEqual(await self.coordinator.resolve_pending(), committed)
        self.assertEqual(self.companion.upload_payloads[-1], (intent["operation_id"], 1, original))
        self.assertEqual([op for op, _ in self.companion.server_calls[start:]], ["begin", "commit"])
        self.assertEqual(self.companion.head().revision, 3)
        self.assertEqual(self.companion.commands[-2].opcode, Opcode.BIND)
        self.assertEqual(self.companion.commands[-2].sequence, 1)
        self.assertFalse(self.coordinator.pending_path.exists())
        self.assertIsNone(await self.coordinator.resolve_pending())

    async def test_uncertain_rom_end_ack_keeps_server_transaction_reconcilable(self):
        self.companion.lose_end_ack = True
        with self.assertRaises(asyncio.TimeoutError):
            await self.coordinator.checkpoint(expected_revision=1)
        self.assertEqual(self.companion.head().revision, 2)
        self.assertTrue(self.coordinator.pending_path.exists())
        self.assertEqual(self.operations()[-1], Opcode.CANCEL)
        self.assertIsNone(self.companion.mode)
        metadata = await self.coordinator.resolve_pending()
        self.assertEqual(metadata["revision"], 2)
        self.assertEqual(self.companion.head().revision, 2)

    async def test_recover_uses_full_canonical_hash_but_only_native_flash_and_receipt(self):
        canonical = self.companion.head()
        old_epoch, old_incarnation = self.companion.session_epoch, self.companion.save_incarnation
        receipt = await self.coordinator.recover()
        self.assertEqual(self.companion.rom_flash, inspect_flash(canonical.payload).flash)
        self.assertEqual(self.companion.rom_commits, 1)
        self.assertEqual((self.companion.session_epoch, self.companion.save_incarnation), (old_epoch, old_incarnation))
        self.assertEqual(receipt.canonical_container_sha256, canonical.sha256)
        self.assertEqual(receipt.canonical_container_size, 131088)
        self.assertTrue(receipt.rtc_footer_present)
        self.assertEqual(receipt.rtc_semantics, "native-footer-excluded")
        self.assertEqual(receipt.normalized_state_sha256, inspect_flash(canonical.payload).state_sha256)
        self.assertEqual(read_live_receipt(self.coordinator.directory / (receipt.operation_id + ".live-apply.json")), receipt)
        self.assertEqual(self.operations(), [Opcode.BIND, Opcode.BEGIN_IMPORT] + [Opcode.WRITE] * 1024
                         + [Opcode.COMMIT] + [Opcode.READ] * 1024 + [Opcode.END])
        self.assertIsNone(self.companion.mode)

    async def test_download_bad_binding_metadata_hash_or_flash_cannot_begin_import(self):
        canonical = self.companion.head()
        good = DownloadedCheckpoint(self.companion.world_id, self.companion.config.player_id,
                                    checkpoint_metadata(canonical), canonical.payload)
        malformed = bytes(FLASH_SIZE)
        cases = [replace(good, world_id=str(uuid4())), replace(good, player_id=str(uuid4())),
                 replace(good, metadata={**good.metadata, "build_id": "b" * 64}),
                 replace(good, metadata={**good.metadata, "ruleset_id": "other-rules"}),
                 replace(good, metadata={**good.metadata, "save_profile": "other-profile"}),
                 replace(good, metadata={**good.metadata, "sha256": "0" * 64}),
                 replace(good, metadata={**good.metadata, "size": FLASH_SIZE}),
                 replace(good, metadata={**good.metadata, "revision": True}),
                 replace(good, payload=bytearray(good.payload)),
                 replace(good, payload=malformed, metadata={**good.metadata, "size": FLASH_SIZE,
                         "sha256": hashlib.sha256(malformed).hexdigest()})]
        for bad in cases:
            with self.subTest(bad=bad.metadata), patch.object(self.coordinator.client, "download", AsyncMock(return_value=bad)):
                with self.assertRaises((LiveSaveError, ProtocolError, FlashError)):
                    await self.coordinator.recover()
            self.assertEqual(self.companion.commands, [])
            self.assertEqual(list(self.coordinator.directory.iterdir()), [])
            self.assertFalse(self.companion.live_checkpoint_lock.locked())
        self.assertEqual(self.companion.rom_commits, 0)

    async def test_stale_canonical_head_before_commit_discards_complete_stage(self):
        original = self.companion.rom_flash
        async def change_head(control):
            if control.opcode == Opcode.WRITE and control.offset == FLASH_SIZE - SAVE_CHUNK_SIZE:
                self.companion.advance_head(make_flash(counter=5))
        self.companion.control_hook = change_head
        with self.assertRaises(LiveSaveError) as caught:
            await self.coordinator.recover()
        self.assert_code(caught, "revision_conflict")
        self.assertNotIn(Opcode.COMMIT, self.operations())
        self.assertEqual(self.companion.rom_flash, original)
        self.assertEqual(self.operations()[-1], Opcode.CANCEL)
        self.assertEqual(self.companion.stage, b"")
        self.assertFalse(list(self.coordinator.directory.glob("*.live-apply.json")))
        self.assertEqual(len(list(self.coordinator.directory.glob("*.recovery-intent.json"))), 1)

    async def test_incarnation_change_after_final_head_reply_never_publishes_receipt(self):
        original_info = self.coordinator.client.info
        replies = 0
        async def change_after_reply():
            nonlocal replies
            result = await original_info()
            replies += 1
            if replies == 3:  # Download head, pre-COMMIT head, final acknowledgement.
                self.companion.save_incarnation += 1
            return result
        with patch.object(self.coordinator.client, "info", change_after_reply):
            with self.assertRaises(ConnectionError):
                await self.coordinator.recover()
        self.assertEqual(self.companion.rom_commits, 1)
        self.assertEqual(self.operations()[-1], Opcode.END)
        self.assertFalse(list(self.coordinator.directory.glob("*.live-apply.json")))
        self.assertEqual(len(list(self.coordinator.directory.glob("*.recovery-intent.json"))), 1)
        self.assertIsNone(self.companion._live_save_owner)

    async def test_rotated_native_readback_accepts_equal_state_and_records_actual_hash(self):
        rotated = make_flash(counter=8, rotation=9)
        async def rotate_before_readback(control):
            if control.opcode == Opcode.READ and control.offset == 0:
                self.companion.rom_flash = rotated
        self.companion.control_hook = rotate_before_readback
        receipt = await self.coordinator.recover()
        self.assertNotEqual(receipt.canonical_flash_sha256, receipt.actual_rom_flash_sha256)
        self.assertEqual(receipt.actual_rom_flash_sha256, hashlib.sha256(rotated).hexdigest())
        self.assertEqual(receipt.normalized_state_sha256, inspect_flash(self.companion.head().payload).state_sha256)

    async def test_wrong_post_commit_state_fails_with_evidence_and_never_claims_rollback(self):
        changed = _rewrite(make_flash(), 0, 1, 0, struct.pack("<h", 7))
        async def wrong_readback(control):
            if control.opcode == Opcode.READ and control.offset == 0:
                self.companion.rom_flash = changed
        self.companion.control_hook = wrong_readback
        with self.assertRaises(LiveSaveError) as caught:
            await self.coordinator.recover()
        self.assert_code(caught, "applied_state")
        self.assertEqual(self.companion.rom_commits, 1)
        self.assertEqual(self.companion.rom_flash, changed)
        self.assertEqual(self.operations()[-1], Opcode.CANCEL)
        self.assertFalse(list(self.coordinator.directory.glob("*.live-apply.json")))
        self.assertEqual(len(list(self.coordinator.directory.glob("*.recovery-intent.json"))), 1)

    async def test_cancel_during_staging_releases_owner_and_never_commits(self):
        original = self.companion.rom_flash
        reached, resume = asyncio.Event(), asyncio.Event()
        async def pause(control):
            if control.opcode == Opcode.WRITE and control.offset == 256:
                reached.set()
                await resume.wait()
        self.companion.control_hook = pause
        task = asyncio.create_task(self.coordinator.recover())
        await asyncio.wait_for(reached.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.operations()[-1], Opcode.CANCEL)
        self.assertNotIn(Opcode.COMMIT, self.operations())
        self.assertEqual(self.companion.rom_flash, original)
        self.assertEqual(self.companion.stage, b"")
        self.assertIsNone(self.companion._live_save_owner)
        self.assertFalse(self.companion.live_checkpoint_lock.locked())
        self.companion.control_hook = None
        self.assertEqual((await self.coordinator.recover()).revision, 1)

    async def test_canceled_server_commit_ack_retains_intent_for_exact_resolution(self):
        reached, resume = asyncio.Event(), asyncio.Event()
        async def pause_ack():
            reached.set()
            await resume.wait()
        self.companion.commit_hook = pause_ack
        task = asyncio.create_task(self.coordinator.checkpoint(expected_revision=1))
        await asyncio.wait_for(reached.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        intent = json.loads(self.coordinator.pending_path.read_text())
        self.assertEqual(self.companion.head().request_id, intent["operation_id"])
        self.assertEqual(self.operations()[-1], Opcode.CANCEL)
        self.companion.commit_hook = None
        self.assertEqual((await self.coordinator.resolve_pending())["revision"], 2)
        self.assertEqual(self.companion.head().revision, 2)

    async def test_live_lifecycle_blocks_other_checkpoint_writers_and_wrappers(self):
        reached, resume = asyncio.Event(), asyncio.Event()
        async def pause(control):
            if control.opcode == Opcode.WRITE and control.offset == 0:
                reached.set()
                await resume.wait()
        self.companion.control_hook = pause
        recovery = asyncio.create_task(self.coordinator.recover())
        await asyncio.wait_for(reached.wait(), 2)
        try:
            for op in ("begin", "chunk", "commit", "abort"):
                # Invoke the real Companion guard before fake-network processing.
                with self.assertRaisesRegex(ValueError, "lifecycle owns"):
                    await Companion.checkpoint_rpc(self.companion, op)
            with self.assertRaises(ValueError):
                await CheckpointClient(self.companion).upload(make_flash(), 1)
            self.assertEqual((await CheckpointClient(self.companion).info())["revision"], 1)
            other = LiveCheckpointCoordinator(self.companion, self.coordinator.directory)
            queued = asyncio.create_task(other.checkpoint(expected_revision=1))
            await asyncio.sleep(0)
            self.assertFalse(queued.done())
            self.assertNotIn(Opcode.BEGIN_EXPORT, self.operations())
            queued.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await queued
        finally:
            recovery.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await recovery
        self.assertIsNone(self.companion._live_save_owner)

    async def test_bad_stage_ack_or_bad_export_crc_never_reports_success(self):
        original = self.companion.rom_flash
        self.companion.bad_write_position = True
        with self.assertRaises(LiveSaveError) as caught:
            await self.coordinator.recover()
        self.assert_code(caught, "write_position")
        self.assertEqual(self.companion.rom_flash, original)
        self.assertNotIn(Opcode.COMMIT, self.operations())
        self.companion.bad_write_position = False
        self.companion.bad_end_crc = True
        with self.assertRaises(LiveSaveError) as caught:
            await self.coordinator.checkpoint(expected_revision=1)
        self.assert_code(caught, "final_crc")
        self.assertTrue(self.coordinator.pending_path.exists())
        self.assertEqual(self.companion.head().revision, 2)
        self.companion.bad_end_crc = False
        self.assertEqual((await self.coordinator.resolve_pending())["revision"], 2)

    async def test_invalid_pending_journal_or_sidepath_never_sends_upload(self):
        session = self.coordinator._session()
        operation_id = str(uuid4())
        payload = self.companion.rom_flash
        intent = self.coordinator._intent(session, operation_id, 1, payload)
        self.coordinator._save_pending(intent, payload)
        original = self.coordinator.pending_path.read_bytes()
        cases = [(" " * 4097).encode(), b"{broken", original.rstrip()[:-1] + b',"schema":1}',
                 json.dumps({**intent, "operation_id": "../outside"}).encode(),
                 json.dumps({**intent, "expected_revision": True}).encode(),
                 json.dumps({**intent, "expected_revision": MAX_COUNTER}).encode(),
                 json.dumps({**intent, "size": FLASH_SIZE + 16}).encode(),
                 json.dumps({**intent, "world_id": str(uuid4())}).encode(),
                 json.dumps({**intent, "player_id": str(uuid4())}).encode(),
                 json.dumps({**intent, "build_id": "b" * 64}).encode(),
                 json.dumps({**intent, "save_profile": "other-profile"}).encode(),
                 json.dumps({**intent, "sha256": "0" * 64}).encode()]
        for raw in cases:
            with self.subTest(journal=raw[:80]):
                self.coordinator.pending_path.write_bytes(raw)
                with self.assertRaises(LiveSaveError):
                    await self.coordinator.resolve_pending()
                self.assertEqual(self.companion.server_calls, [])
                self.assertEqual(self.companion.commands, [])
        self.coordinator.pending_path.write_bytes(original)
        flash_path = self.coordinator.directory / (operation_id + ".flash")
        for raw in (payload[:-1], payload + b"x", b"x" * FLASH_SIZE):
            flash_path.write_bytes(raw)
            with self.assertRaises(LiveSaveError) as caught:
                await self.coordinator.resolve_pending()
            self.assert_code(caught, "journal_hash")
            self.assertEqual(self.companion.server_calls, [])

    async def test_core_disconnect_after_export_retains_journal_and_rebinds_new_incarnation(self):
        original_commit_hook = self.companion.commit_hook
        async def disconnect():
            self.companion.connected = False
        self.companion.commit_hook = disconnect
        with self.assertRaises(ConnectionError):
            await self.coordinator.checkpoint(expected_revision=1)
        self.assertTrue(self.coordinator.pending_path.exists())
        self.assertEqual(self.companion.head().revision, 2)
        # No command may be sent after the captured session becomes invalid.
        self.assertNotIn(Opcode.END, self.operations())
        self.assertNotIn(Opcode.CANCEL, self.operations())
        self.companion.connected = True
        self.companion.commit_hook = original_commit_hook
        self.companion.restart()
        self.assertEqual((await self.coordinator.resolve_pending())["revision"], 2)
        self.assertEqual(self.companion.commands[-2].opcode, Opcode.BIND)
        self.assertEqual(self.companion.commands[-2].incarnation, 3)

    async def test_active_save_and_its_mirror_sidecar_are_never_accessed_or_replaced(self):
        save = self.directory / "active.sav"
        sidecar = save.with_name(save.name + ".checkpoint.json")
        save.write_bytes(b"open emulator mapping sentinel")
        sidecar.write_bytes(b"closed-game mirror metadata sentinel")
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (save, sidecar)}
        original_open, original_replace = Path.open, __import__("os").replace
        def guarded_open(path, *args, **kwargs):
            if path in before:
                raise AssertionError("live coordinator accessed active save or mirror")
            return original_open(path, *args, **kwargs)
        def guarded_replace(source, target):
            if Path(target) in before:
                raise AssertionError("live coordinator replaced active save or mirror")
            return original_replace(source, target)
        with MirrorLease(save), patch.object(Path, "open", guarded_open), patch("os.replace", guarded_replace):
            await self.coordinator.checkpoint(expected_revision=1)
            await self.coordinator.recover()
        for path, state in before.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), state)

    async def test_revision_request_and_binding_sequence_fail_before_rom_export(self):
        for revision in (0, 2, True):
            with self.assertRaises(LiveSaveError) as caught:
                await self.coordinator.checkpoint(expected_revision=revision)
            self.assert_code(caught, "revision_conflict")
        self.assertEqual(self.companion.commands, [])
        self.companion._live_binding = self.coordinator._session()
        self.companion._live_sequence = MAX_COUNTER
        with self.assertRaises(LiveSaveError) as caught:
            await self.coordinator.checkpoint(expected_revision=1)
        self.assert_code(caught, "counter_exhausted")
        self.assertEqual(self.companion.commands, [])
        self.assertFalse(self.coordinator.pending_path.exists())


if __name__ == "__main__":
    unittest.main()
