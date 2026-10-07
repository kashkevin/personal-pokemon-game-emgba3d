from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

from emerald_multiplayer.checkpoint_mirror import (
    MAX_SIDECAR_BYTES, MirrorError, MirrorInfo, MirrorLease, inspect_mirror,
    recoveries_path, restore_checkpoint, sidecar_path,
)
from emerald_multiplayer.flash import LAYOUT_ID, inspect_flash
from emerald_multiplayer.storage import Checkpoint
from test_flash import make_flash


BUILD = "test-build-sha256"
RULESET = "test-ruleset-v1"


class CheckpointMirrorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.save = Path(self.temp.name) / "private" / "player-a.sav"
        self.world, self.player = str(uuid.uuid4()), str(uuid.uuid4())
        self.payload = make_flash(with_rtc=True)
        self.download = self.downloaded(self.payload)

    def tearDown(self):
        self.temp.cleanup()

    def downloaded(self, payload, revision=1, *, world=None, player=None, **changes):
        metadata = dict(revision=revision, request_id=str(uuid.uuid4()), size=len(payload),
                        sha256=hashlib.sha256(payload).hexdigest(), build_id=BUILD,
                        ruleset_id=RULESET, save_profile=LAYOUT_ID)
        return SimpleNamespace(world_id=world or self.world, player_id=player or self.player,
                               metadata={**metadata, **changes}, payload=payload)

    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(MirrorError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def restore(self, checkpoint=None, path=None):
        return restore_checkpoint(path or self.save, checkpoint or self.download, world_id=self.world)

    def archives(self):
        root = recoveries_path(self.save)
        return list(root.iterdir()) if root.exists() else []

    def test_downloaded_full_container_exact_sidecar_and_inspection(self):
        info = self.restore()
        self.assertIsInstance(info, MirrorInfo)
        self.assertEqual(self.save.read_bytes(), self.payload)
        self.assertEqual(len(self.save.read_bytes()), 131088)
        self.assertEqual(info.sha256, hashlib.sha256(self.payload).hexdigest())
        self.assertEqual(inspect_flash(self.save.read_bytes()).rtc_footer, inspect_flash(self.payload).rtc_footer)
        self.assertEqual(json.loads(sidecar_path(self.save).read_text()), asdict(info))
        self.assertEqual(inspect_mirror(self.save), info)
        self.assertFalse(self.archives())

    def test_storage_checkpoint_adapter(self):
        meta = self.download.metadata
        checkpoint = Checkpoint(self.player, 1, meta["request_id"], self.payload,
                                meta["sha256"], BUILD, RULESET, LAYOUT_ID)
        self.assertEqual(self.restore(checkpoint).player_id, self.player)
        self.assertEqual(inspect_mirror(self.save).sha256, meta["sha256"])

    def test_exact_retry_does_not_rewrite_or_archive(self):
        info = self.restore()
        timestamp = self.save.stat().st_mtime_ns
        self.assertEqual(self.restore(), info)
        self.assertEqual(self.save.stat().st_mtime_ns, timestamp)
        self.assertFalse(self.archives())

    def test_newer_revision_archives_previous_payload_and_sidecar(self):
        old = self.restore()
        newer = self.downloaded(make_flash(counter=3, with_rtc=True), 2)
        new = self.restore(newer)
        self.assertEqual(new.revision, 2)
        self.assertEqual(self.save.read_bytes(), newer.payload)
        archive, = self.archives()
        self.assertEqual((archive / self.save.name).read_bytes(), self.payload)
        self.assertEqual(json.loads((archive / sidecar_path(self.save).name).read_text()), asdict(old))

    def test_verified_bindings_cannot_change(self):
        old = self.restore()
        for changes in ({"world": str(uuid.uuid4())}, {"player": str(uuid.uuid4())},
                        {"build_id": "other-build"}, {"ruleset_id": "other-rules"}):
            packet = self.downloaded(self.payload, 2, **changes)
            if "world" in changes:
                self.assert_code("identity_mismatch", restore_checkpoint,
                                 self.save, packet, world_id=packet.world_id)
            else:
                self.assert_code("identity_mismatch", self.restore, packet)
        self.assertEqual(inspect_mirror(self.save), old)
        self.assertFalse(self.archives())

    def test_older_and_same_revision_changed_content_rejected(self):
        newer = self.downloaded(make_flash(counter=3, with_rtc=True), 2)
        info = self.restore(newer)
        self.assert_code("revision_conflict", self.restore)
        self.assert_code("revision_conflict", self.restore, self.downloaded(self.payload, 2))
        self.assert_code("revision_conflict", self.restore,
                         self.downloaded(newer.payload, 2))  # Different committed request.
        self.assertEqual(inspect_mirror(self.save), info)
        self.assertFalse(self.archives())

    def test_damaged_payload_preserves_sidecar_owner_and_revision_guards(self):
        owner_b = str(uuid.uuid4())
        newer_b = self.downloaded(make_flash(counter=3, with_rtc=True), 2, player=owner_b)
        self.restore(newer_b)
        self.save.write_bytes(b"damaged B local save")
        self.assert_code("identity_mismatch", self.restore)
        older_b = self.downloaded(self.payload, 1, player=owner_b)
        self.assert_code("revision_conflict", self.restore, older_b)
        self.assertEqual(self.save.read_bytes(), b"damaged B local save")
        self.assertFalse(self.archives())
        repaired = self.restore(newer_b)
        self.assertEqual(inspect_mirror(self.save), repaired)
        archive, = self.archives()
        self.assertEqual((archive / self.save.name).read_bytes(), b"damaged B local save")

    def test_same_bound_revision_repairs_damaged_file(self):
        info = self.restore()
        self.save.write_bytes(b"damaged local container")
        self.assert_code("mirror_mismatch", inspect_mirror, self.save)
        self.assertEqual(self.restore(), info)
        self.assertEqual(inspect_mirror(self.save), info)
        archive, = self.archives()
        self.assertEqual((archive / self.save.name).read_bytes(), b"damaged local container")

    def test_unbound_local_and_corrupt_sidecar_preserved_before_recovery(self):
        self.save.parent.mkdir(parents=True)
        original = b"unbound corrupt ordinary local save"
        metadata = b"{broken sidecar"
        self.save.write_bytes(original)
        sidecar_path(self.save).write_bytes(metadata)
        self.restore()
        archive, = self.archives()
        self.assertEqual((archive / self.save.name).read_bytes(), original)
        self.assertEqual((archive / sidecar_path(self.save).name).read_bytes(), metadata)
        self.assertEqual(self.save.read_bytes(), self.payload)

    def test_unsaved_valid_local_change_is_preserved(self):
        info = self.restore()
        unsaved = make_flash(counter=8, with_rtc=True)
        self.save.write_bytes(unsaved)
        self.assert_code("mirror_mismatch", inspect_mirror, self.save)
        self.assertEqual(self.restore(), info)
        archive, = self.archives()
        self.assertEqual((archive / self.save.name).read_bytes(), unsaved)

    def test_exclusive_core_lifetime_lease_prevents_restore_and_inspection(self):
        info = self.restore()
        with MirrorLease(self.save):
            self.assert_code("mirror_active", self.restore)
            self.assert_code("mirror_active", inspect_mirror, self.save)
            other = Path(self.temp.name) / "private" / "player-b.sav"
            self.restore(path=other)
        self.assertEqual(inspect_mirror(self.save), info)
        lease = MirrorLease(self.save)
        with lease:
            self.assert_code("mirror_active", lease.__enter__)
        self.assertEqual(inspect_mirror(self.save), info)

    def test_crashed_core_releases_process_lifetime_lease(self):
        self.restore()
        child_code = """
import sys
from emerald_multiplayer.checkpoint_mirror import MirrorLease
with MirrorLease(sys.argv[1]):
    print('running', flush=True)
    sys.stdin.readline()
"""
        child = subprocess.Popen([sys.executable, "-u", "-c", child_code, str(self.save)],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "running")
            self.assert_code("mirror_active", self.restore)
            child.kill()
            child.wait(timeout=5)
            self.assertEqual(self.restore().sha256, self.download.metadata["sha256"])
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            child.stdin.close()
            child.stdout.close()
            child.stderr.close()

    def test_interrupted_payload_sidecar_pair_detected_and_recoverable(self):
        old = self.restore()
        newer = self.downloaded(make_flash(counter=3, with_rtc=True), 2)
        import emerald_multiplayer.checkpoint_mirror as mirror
        original_replace = mirror.os.replace
        calls = 0
        def interrupt_second(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated interrupted sidecar replacement")
            return original_replace(source, destination)
        with patch.object(mirror.os, "replace", side_effect=interrupt_second):
            self.assert_code("mirror_io_error", self.restore, newer)
        self.assertEqual(self.save.read_bytes(), newer.payload)
        self.assertEqual(json.loads(sidecar_path(self.save).read_text()), asdict(old))
        self.assert_code("mirror_mismatch", inspect_mirror, self.save)
        archive, = self.archives()
        self.assertEqual((archive / self.save.name).read_bytes(), self.payload)
        info = self.restore(newer)
        self.assertEqual(inspect_mirror(self.save), info)
        self.assertEqual(len(self.archives()), 2)

    def test_invalid_incoming_envelope_flash_and_profile_never_touch_local_file(self):
        info = self.restore()
        bad_hash = self.downloaded(self.payload, 2, sha256="0" * 64)
        self.assert_code("checkpoint_mismatch", self.restore, bad_hash)
        wrong_world = self.downloaded(self.payload, 2, world=str(uuid.uuid4()))
        self.assert_code("world_mismatch", self.restore, wrong_world)
        self.assert_code("invalid_flash", self.restore, self.downloaded(bytes(131072), 2))
        self.assert_code("save_profile_mismatch", self.restore,
                         self.downloaded(self.payload, 2, save_profile="unknown-profile"))
        self.assert_code("invalid_metadata", self.restore,
                         self.downloaded(self.payload, 2, request_id="invalid"))
        extra = self.downloaded(self.payload, 2, unexpected=True)
        self.assert_code("invalid_metadata", self.restore, extra)
        self.assertEqual(inspect_mirror(self.save), info)
        self.assertFalse(self.archives())

    def test_sidecar_json_is_bounded_exact_and_rejects_duplicates(self):
        info = self.restore()
        original = sidecar_path(self.save).read_text()
        for corrupted in (" " * (MAX_SIDECAR_BYTES + 1),
                          original.rstrip()[:-1] + ',"world_id":"' + self.world + '"}',
                          json.dumps({**asdict(info), "unexpected": True})):
            sidecar_path(self.save).write_text(corrupted)
            self.assert_code("invalid_metadata", inspect_mirror, self.save)
        self.restore()
        self.assertEqual(inspect_mirror(self.save), info)
        self.assertEqual(len(self.archives()), 1)

    def test_missing_payload_does_not_erase_valid_sidecar_identity(self):
        self.restore()
        self.save.unlink()
        wrong_player = self.downloaded(self.payload, 2, player=str(uuid.uuid4()))
        self.assert_code("identity_mismatch", self.restore, wrong_player)
        info = self.restore()
        self.assertEqual(inspect_mirror(self.save), info)
        archive, = self.archives()
        self.assertFalse((archive / self.save.name).exists())
        self.assertTrue((archive / sidecar_path(self.save).name).exists())


if __name__ == "__main__":
    unittest.main()
