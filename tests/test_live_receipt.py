from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict
import hashlib
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from emerald_multiplayer.flash import LAYOUT_ID, inspect_flash
from emerald_multiplayer.live_receipt import (
    LiveReceiptError, MAX_RECEIPT_BYTES, RECEIPT_FORMAT, RTC_SEMANTICS,
    read_live_receipt, record_live_apply,
)
from emerald_multiplayer.checkpoint_mirror import MirrorLease
from emerald_multiplayer.storage import _ExclusiveFileLock
from test_flash import make_flash, _rewrite


class LiveReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "private" / "apply-receipt.json"
        self.payload = make_flash(with_rtc=True)
        self.applied = make_flash(counter=5, rotation=8)
        self.operation, self.rom_request = str(uuid.uuid4()), str(uuid.uuid4())
        self.download = SimpleNamespace(world_id=str(uuid.uuid4()), player_id=str(uuid.uuid4()),
            payload=self.payload, metadata=dict(revision=2, request_id=str(uuid.uuid4()),
            size=len(self.payload), sha256=hashlib.sha256(self.payload).hexdigest(),
            build_id="verified-build", ruleset_id="rules-v1", save_profile=LAYOUT_ID))

    def tearDown(self):
        self.temp.cleanup()

    def record(self, **changes):
        args = dict(path=self.path, downloaded=self.download, applied_flash=self.applied,
                    operation_id=self.operation, session_epoch=7, incarnation=2,
                    rom_request_id=self.rom_request)
        return record_live_apply(**{**args, **changes})

    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(LiveReceiptError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def packet(self, payload=None, **metadata_changes):
        data = self.payload if payload is None else payload
        metadata = {**self.download.metadata, "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(), **metadata_changes}
        return SimpleNamespace(world_id=self.download.world_id, player_id=self.download.player_id,
                               payload=data, metadata=metadata)

    def test_native_rotation_matches_state_but_records_distinct_actual_flash(self):
        receipt = self.record()
        self.assertEqual(receipt.canonical_container_sha256, hashlib.sha256(self.payload).hexdigest())
        self.assertEqual(receipt.canonical_flash_sha256, inspect_flash(self.payload).sha256)
        self.assertEqual(receipt.actual_rom_flash_sha256, hashlib.sha256(self.applied).hexdigest())
        self.assertNotEqual(receipt.canonical_flash_sha256, receipt.actual_rom_flash_sha256)
        self.assertEqual(receipt.normalized_state_sha256, inspect_flash(self.applied).state_sha256)
        self.assertEqual(receipt.normalized_state_sha256, inspect_flash(self.payload).state_sha256)
        self.assertEqual(receipt.trainer_id, 0x12345678)
        self.assertEqual((receipt.session_epoch, receipt.incarnation), (7, 2))
        self.assertEqual((receipt.operation_id, receipt.rom_request_id), (self.operation, self.rom_request))
        self.assertEqual(read_live_receipt(self.path), receipt)
        with self.assertRaises(FrozenInstanceError):
            receipt.revision = 99

    def test_rtc_footer_preserved_as_canonical_metadata_but_native_import_excluded(self):
        receipt = self.record()
        self.assertTrue(receipt.rtc_footer_present)
        self.assertEqual(receipt.canonical_container_size, 131088)
        self.assertEqual(receipt.rtc_semantics, RTC_SEMANTICS)
        self.assertNotEqual(receipt.canonical_container_sha256, receipt.canonical_flash_sha256)
        other = Path(self.temp.name) / "flash-only.json"
        raw = self.packet(make_flash())
        without = self.record(path=other, downloaded=raw)
        self.assertFalse(without.rtc_footer_present)
        self.assertEqual(without.canonical_container_size, 131072)
        self.assertEqual(without.canonical_container_sha256, without.canonical_flash_sha256)

    def test_default_rom_request_uuid_is_operation_uuid(self):
        receipt = self.record(rom_request_id=None)
        self.assertEqual(receipt.rom_request_id, self.operation)

    def test_exact_retry_is_idempotent_but_receipt_cannot_be_rebound(self):
        receipt = self.record()
        old = self.path.read_bytes()
        timestamp = self.path.stat().st_mtime_ns
        self.assertEqual(self.record(), receipt)
        self.assertEqual(self.path.stat().st_mtime_ns, timestamp)
        for changes in ({"operation_id": str(uuid.uuid4())}, {"session_epoch": 8},
                        {"incarnation": 3}, {"rom_request_id": str(uuid.uuid4())},
                        {"applied_flash": make_flash(counter=8)}):
            self.assert_code("receipt_conflict", self.record, **changes)
            self.assertEqual(self.path.read_bytes(), old)

    def test_wrong_trainer_or_normalized_state_never_publishes(self):
        self.assert_code("trainer_mismatch", self.record,
                         applied_flash=make_flash(trainer_id=0x87654321))
        changed = _rewrite(make_flash(), 0, 1, 0, struct.pack("<h", 7))
        inspect_flash(changed)  # Coherent checksum but different actual game state.
        self.assert_code("state_mismatch", self.record, applied_flash=changed)
        self.assertFalse(self.path.exists())
        self.assertFalse(self.path.parent.exists())

    def test_torn_blank_footer_or_non_bytes_readback_never_publishes(self):
        torn = _rewrite(make_flash(), 0, 1, 1500, b"\1", recompute=False)
        for invalid in (torn, bytes(131072), self.payload, self.applied[:-1], bytearray(self.applied)):
            self.assert_code("invalid_readback", self.record, applied_flash=invalid)
        self.assertFalse(self.path.exists())

    def test_canonical_metadata_and_whole_container_hash_are_verified(self):
        for packet, code in ((self.packet(sha256="0" * 64), "checkpoint_mismatch"),
                             (self.packet(size=131072), "checkpoint_mismatch"),
                             (self.packet(bytes(131072)), "invalid_checkpoint"),
                             (self.packet(save_profile="other-profile"), "save_profile_mismatch"),
                             (self.packet(extra=True), "invalid_metadata")):
            self.assert_code(code, self.record, downloaded=packet)
        self.assertFalse(self.path.exists())

    def test_invalid_identity_and_epoch_fields_never_publishes(self):
        for changes in ({"operation_id": "invalid"}, {"rom_request_id": "invalid"},
                        {"session_epoch": True}, {"session_epoch": 0},
                        {"incarnation": 0}, {"incarnation": 0x100000000}):
            self.assert_code("invalid_metadata", self.record, **changes)
        for field in ("revision", "request_id", "build_id", "ruleset_id"):
            bad = self.packet(**{field: True})
            self.assert_code("invalid_metadata", self.record, downloaded=bad)
        for field in ("world_id", "player_id"):
            packet = self.packet()
            setattr(packet, field, "invalid")
            self.assert_code("invalid_metadata", self.record, downloaded=packet)
        self.assertFalse(self.path.exists())
        receipt = self.record(incarnation=0xFFFFFFFF)
        self.assertEqual(read_live_receipt(self.path).incarnation, 0xFFFFFFFF)
        self.assertEqual(receipt.incarnation, 0xFFFFFFFF)

    def test_exact_bounded_envelope_and_checksum_reject_accidental_corruption(self):
        self.record()
        envelope = json.loads(self.path.read_text())
        self.assertEqual(set(envelope), {"format", "receipt", "receipt_sha256"})
        self.assertEqual(envelope["format"], RECEIPT_FORMAT)
        self.assertEqual(set(envelope["receipt"]), set(asdict(read_live_receipt(self.path))))
        envelope["receipt"]["session_epoch"] += 1
        self.path.write_text(json.dumps(envelope))
        self.assert_code("receipt_corrupt", read_live_receipt, self.path)
        self.assert_code("receipt_corrupt", self.record)

    def test_invalid_json_unknown_fields_duplicate_and_size_bounds(self):
        self.record()
        original = self.path.read_text()
        envelope = json.loads(original)
        cases = ("{broken", " " * (MAX_RECEIPT_BYTES + 1),
                 original.rstrip()[:-1] + ',"format":"' + RECEIPT_FORMAT + '"}',
                 json.dumps({**envelope, "extra": True}),
                 json.dumps({**envelope, "format": "schema1-mirror"}),
                 original.replace('"incarnation":2', '"incarnation":NaN'))
        for data in cases:
            self.path.write_text(data)
            self.assert_code("receipt_corrupt", read_live_receipt, self.path)

    def test_publication_failure_leaves_no_partial_receipt_and_retry_succeeds(self):
        import emerald_multiplayer.live_receipt as module
        with patch.object(module.os, "replace", side_effect=OSError("interrupted publication")):
            self.assert_code("receipt_io_error", self.record)
        self.assertFalse(self.path.exists())
        self.assertFalse(list(self.path.parent.glob("*.stage")))
        receipt = self.record()
        self.assertEqual(read_live_receipt(self.path), receipt)

    def test_receipt_path_lock_prevents_concurrent_overwrite(self):
        lock = _ExclusiveFileLock(self.path.with_name(self.path.name + ".receipt.lock"))
        lock.acquire()
        try:
            self.assert_code("receipt_active", self.record)
        finally:
            lock.release()
        self.assertFalse(self.path.exists())
        self.assertEqual(read_live_receipt(self.path) if self.path.exists() else None, None)
        self.record()

    def test_active_save_is_untouched_and_cannot_be_used_as_receipt_path(self):
        save = Path(self.temp.name) / "active.sav"
        sentinel = b"active game mapping must not be accessed"
        save.write_bytes(sentinel)
        with MirrorLease(save):
            receipt = self.record()
            self.assertEqual(receipt.rtc_semantics, RTC_SEMANTICS)
            self.assert_code("invalid_path", self.record, path=save)
        self.assertEqual(save.read_bytes(), sentinel)

    def test_missing_receipt_fails_closed_without_creating_file(self):
        self.assert_code("receipt_missing", read_live_receipt, self.path)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
