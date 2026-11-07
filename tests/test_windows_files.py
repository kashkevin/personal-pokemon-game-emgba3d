"""windows_files: a scanner's brief hold on a just-written file never fails a replace or a removal on Windows."""
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from emerald_multiplayer import windows_files


class WindowsFilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def held(self, real, times):
        calls = []

        def operation(*arguments):
            calls.append(arguments)
            if len(calls) <= times:
                raise PermissionError(13, "The process cannot access the file because it is being used by another process")
            return real(*arguments)
        return operation, calls

    def test_a_brief_hold_is_waited_out_on_windows(self):
        source, target = self.root / "a.stage", self.root / "a.json"
        source.write_text("new"); target.write_text("old")
        operation, calls = self.held(os.replace, 3)
        with patch.object(windows_files.os, "name", "nt"), patch.object(windows_files.os, "replace", operation), \
                patch.object(windows_files, "RETRY_SECONDS", 0):
            windows_files.replace_file(source, target)
        self.assertEqual((len(calls), target.read_text(), source.exists()), (4, "new", False))
        operation, calls = self.held(os.unlink, 2)
        with patch.object(windows_files.os, "name", "nt"), patch.object(windows_files.os, "unlink", operation), \
                patch.object(windows_files, "RETRY_SECONDS", 0):
            windows_files.unlink_file(target)
        self.assertEqual((len(calls), target.exists()), (3, False))

    def test_a_lasting_hold_still_fails_and_other_systems_never_retry(self):
        source, target = self.root / "b.stage", self.root / "b.json"
        source.write_text("new")
        operation, calls = self.held(os.replace, 10 ** 9)
        with patch.object(windows_files.os, "name", "nt"), patch.object(windows_files.os, "replace", operation), \
                patch.object(windows_files, "RETRY_SECONDS", 0), patch.object(windows_files, "WAIT_SECONDS", 0.05):
            with self.assertRaises(PermissionError):
                windows_files.replace_file(source, target)
        self.assertGreater(len(calls), 1)
        operation, calls = self.held(os.replace, 1)
        with patch.object(windows_files.os, "name", "posix"), patch.object(windows_files.os, "replace", operation):
            with self.assertRaises(PermissionError):
                windows_files.replace_file(source, target)
        self.assertEqual(len(calls), 1)


@unittest.skipUnless(os.name == "nt", "a real hold needs Windows' sharing rules (elsewhere these are the plain calls)")
class RealWindowsHoldTests(unittest.TestCase):
    """The hold itself, not a stand-in: another handle opened on the file the way a scanner's is (Python's open() does
    not let anyone delete or replace the file while it is open), let go after a moment, as a scanner does."""
    HOLD_SECONDS = .3

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def hold(self, path, seconds):
        """Open path from another handle and close it after seconds; returns (handle, the time it was let go)."""
        handle = open(path, "rb")
        self.addCleanup(handle.close)
        released = []

        def let_go():
            time.sleep(seconds)
            released.append(time.monotonic())
            handle.close()
        thread = threading.Thread(target=let_go, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        return handle, released

    def test_a_replace_waits_out_a_real_hold(self):
        source, target = self.root / "a.stage", self.root / "a.json"
        source.write_text("new")
        target.write_text("old")
        handle = open(target, "rb")
        try:
            with self.assertRaises(PermissionError):         # the hold is real: the plain call is refused
                os.replace(source, target)
        finally:
            handle.close()
        self.assertEqual((source.read_text(), target.read_text()), ("new", "old"))
        _, released = self.hold(target, self.HOLD_SECONDS)
        windows_files.replace_file(source, target)
        finished = time.monotonic()
        self.assertEqual(len(released), 1)                   # it went through only once the hold was let go
        self.assertGreaterEqual(finished, released[0])
        self.assertEqual((target.read_text(), source.exists()), ("new", False))

    def test_a_removal_waits_out_a_real_hold(self):
        target = self.root / "b.journal"
        target.write_text("journal")
        handle = open(target, "rb")
        try:
            with self.assertRaises(PermissionError):
                os.unlink(target)
        finally:
            handle.close()
        self.assertTrue(target.exists())
        _, released = self.hold(target, self.HOLD_SECONDS)
        windows_files.unlink_file(target)
        finished = time.monotonic()
        self.assertEqual(len(released), 1)
        self.assertGreaterEqual(finished, released[0])
        self.assertFalse(target.exists())

    def test_a_hold_longer_than_the_wait_still_fails_and_leaves_both_files(self):
        source, target = self.root / "c.stage", self.root / "c.json"
        source.write_text("new")
        target.write_text("old")
        handle = open(target, "rb")
        self.addCleanup(handle.close)
        started = time.monotonic()
        with patch.object(windows_files, "WAIT_SECONDS", .2):
            with self.assertRaises(PermissionError):
                windows_files.replace_file(source, target)
        self.assertGreaterEqual(time.monotonic() - started, .2)
        handle.close()
        self.assertEqual((source.read_text(), target.read_text()), ("new", "old"))


if __name__ == "__main__":
    unittest.main()
