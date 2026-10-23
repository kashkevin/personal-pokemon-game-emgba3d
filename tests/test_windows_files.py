"""windows_files: a scanner's brief hold on a just-written file never fails a replace or a removal on Windows."""
import os
from pathlib import Path
import tempfile
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


if __name__ == "__main__":
    unittest.main()
