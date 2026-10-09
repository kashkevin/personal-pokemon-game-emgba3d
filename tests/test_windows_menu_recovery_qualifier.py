"""Proof diagnostic/integrity tests; no native game, server or GUI is launched."""
import copy
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest

SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts" / "windows-runtime")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
from qualify_menu_recovery import (GAMEPLAY_SYMBOLS, HOLD_HEADER, HOLD_SIZE,
    decode_hold, verify_source_index, verify_stable_hold)


def snapshot(frame=100, state=9, hold=4):
    return (HOLD_HEADER.pack(frame, state, hold, 7, 2) + bytes(range(32))
            + b"timer" + bytes(range(200))*3
            + b"".join(bytes([n+1])*size for n, size in enumerate(GAMEPLAY_SYMBOLS.values())))


class HoldTests(unittest.TestCase):
    def test_exact_layout_keeps_both_full_rng_states_and_personal_party(self):
        raw = snapshot()
        self.assertEqual(len(raw), HOLD_SIZE)
        value = decode_hold(raw)
        self.assertEqual((value["frame"], value["state"], value["hold"], value["counter"], value["count"]),
                         (100, 9, 4, 7, 2))
        self.assertEqual(value["rng"], bytes(range(16)).hex())
        self.assertEqual(value["rng2"], bytes(range(16, 32)).hex())
        self.assertEqual(value["playtime"], b"timer".hex())
        self.assertEqual(value["party_sha256"], hashlib.sha256(bytes(range(200))*3).hexdigest())
        self.assertEqual(value["gameplay"]["gBattleMons"], hashlib.sha256(bytes([3])*560).hexdigest())
        verify_stable_hold(value, decode_hold(snapshot(280)))

    def test_partial_stale_wrong_marker_and_each_progress_field_refused(self):
        raw = snapshot()
        for invalid in (raw[:-1], raw+b"x", snapshot(state=11),
                        HOLD_HEADER.pack(100, 9, 4, 7, 7)+raw[HOLD_HEADER.size:]):
            with self.subTest(length=len(invalid)), self.assertRaises(AssertionError):
                decode_hold(invalid)
        first = decode_hold(raw)
        for invalid in (snapshot(219), snapshot(280, state=5), snapshot(280, hold=2)):
            with self.assertRaises(AssertionError):
                verify_stable_hold(first, decode_hold(invalid))
        for field in ("counter", "count", "rng", "rng2", "playtime", "party_sha256", "gameplay"):
            after = copy.deepcopy(decode_hold(snapshot(280)))
            after[field] = "changed"
            with self.subTest(field=field), self.assertRaises(AssertionError):
                verify_stable_hold(first, after)


class SourceIndexTests(unittest.TestCase):
    def test_source_pin_covers_current_production_bridge_and_proof_helpers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            index = {}
            for name in ("src/emerald_multiplayer/session.py", "bridge/mgba.lua",
                         "scripts/windows-runtime/qualify.py", "docs/readme.md"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(name.encode())
                index[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(len(verify_source_index(root, index)), 4)
            incomplete = dict(index)
            del incomplete["bridge/mgba.lua"]
            with self.assertRaises(AssertionError):
                verify_source_index(root, incomplete)
            (root / "src/emerald_multiplayer/session.py").write_bytes(b"changed")
            with self.assertRaises(AssertionError):
                verify_source_index(root, index)

    def test_parent_escape_and_added_unindexed_helper_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "README.md").write_bytes(b"readme")
            digest = hashlib.sha256(b"readme").hexdigest()
            for name in ("../README.md", str(root / "README.md")):
                with self.subTest(name=name), self.assertRaises(AssertionError):
                    verify_source_index(root, {name: digest})
            index = {"README.md": digest}
            verify_source_index(root, index)
            (root / "scripts/windows-runtime").mkdir(parents=True)
            (root / "scripts/windows-runtime/new_helper.py").write_bytes(b"unindexed")
            with self.assertRaises(AssertionError):
                verify_source_index(root, index)


if __name__ == "__main__":
    unittest.main()
