"""scripts/diagnostics/check_gba_test_failures.py: a new failure of the GBA test ROM is not hidden by the known 39."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("check_gba", ROOT / "scripts/diagnostics/check_gba_test_failures.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

LOG = """[0] Something: PASS

  FAILED tests:
  - test/battle/exp.c:217: Both opponent's Pokemon give experience: 234: EXPECT_EQ(4156, 2771) failed
  - \x1b[31mtest/battle/ability/keen_eye.c:10\x1b[0m: Keen Eye, Gen9: 10: Expected 1.0 passes
  - test/battle/ability/x.c:3: Title with: a colon: 9: ASSUME failed

  Tests with ASSUMPTIONS_FAILED:
  - test/battle/ability/forewarn.c:19: Forewarn: 23: ASSUME failed

- Tests FAILED:          3
"""


class GbaFailureListTests(unittest.TestCase):
    def test_only_the_failed_block_is_read_with_details_and_colours_removed(self):
        self.assertEqual(check.failed_tests(LOG), {
            "test/battle/exp.c: Both opponent's Pokemon give experience",
            "test/battle/ability/keen_eye.c: Keen Eye, Gen9",
            "test/battle/ability/x.c: Title with: a colon"})

    def test_new_and_fixed_failures_are_told_apart(self):
        new, fixed = check.compare({"a", "b"}, {"b", "c"})
        self.assertEqual((new, fixed), (["a"], ["c"]))

    def test_the_checked_in_list_matches_the_39_known_failures(self):
        expected = check.read_expected(ROOT / "docs/gba-test-expected-failures.txt")
        self.assertEqual(len(expected), 39)
        self.assertTrue(all(name.startswith("test/") for name in expected))

    def test_exit_status_follows_new_failures_and_an_incomplete_log(self):
        with tempfile.TemporaryDirectory() as temp:
            log, listed = Path(temp) / "log", Path(temp) / "list"
            log.write_text(LOG)
            listed.write_text("# comment\n" + "\n".join(sorted(check.failed_tests(LOG))) + "\n")
            self.assertEqual(check.main([str(log), "--expected", str(listed)]), 0)
            listed.write_text("test/battle/exp.c: Both opponent's Pokemon give experience\n")
            self.assertEqual(check.main([str(log), "--expected", str(listed)]), 1)
            log.write_text("make: *** nothing ran\n")
            self.assertEqual(check.main([str(log), "--expected", str(listed)]), 2)


if __name__ == "__main__":
    unittest.main()
