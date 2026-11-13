"""scripts/qa/ui_audit.py: the native interface's audit over a walk (KNOWN_ISSUES MS-105)."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "qa"))
import ui_audit  # noqa: E402

TABLE = """00401000 T _CB2_Overworld
00402000 T _CB2_EasyChatScreen
00402800 T _CB2_HallOfFame
00403000 T _SomeScript
"""


def write(directory, name, text):
    path = os.path.join(directory, name)
    with open(path, "w") as out:
        out.write(text)
    return path


class SummarizeTests(unittest.TestCase):
    def test_addresses_are_named_through_the_logged_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            table = write(tmp, "t.nm", TABLE)
            # loaded 0x10000 above the table's addresses
            log = write(tmp, "game.log", "\n".join([
                "INFO: Native UI audit: on (CB2_Overworld at 0x00411000)",
                "INFO: Native UI audit: frame 10, the game's own interface with no native screen: window 0: 18x2 at 6,0"
                " screen 0x00412010 script 0x00413000",
                "INFO: Native UI audit: frame 70, none (easy_chat)",
                "INFO: Native UI audit: frame 80, the game's own interface with no native screen: screen 0x00412800",
                "INFO: Native UI audit: frame 85, none (nothing shown)",
            ]))
            states = ui_audit.summarize([log], ui_audit.read_table(table), 20)
        self.assertEqual(list(states), ["window 0: 18x2 at 6,0 screen CB2_EasyChatScreen+0x10 script SomeScript"])
        self.assertEqual(states["window 0: 18x2 at 6,0 screen CB2_EasyChatScreen+0x10 script SomeScript"],
                         {"times": 1, "frames": 60, "logs": 1})

    def test_a_short_state_is_left_out_and_a_log_without_the_reference_uses_the_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            table = write(tmp, "t.nm", TABLE)
            log = write(tmp, "game.log", "\n".join([
                "INFO: Native UI audit: frame 1, the game's own interface with no native screen: screen 0x00402800",
                "INFO: Native UI audit: frame 30, none (hall_of_fame)",
                "INFO: Native UI audit: frame 40, the game's own interface with no native screen: transition 13",
                "INFO: Native UI audit: frame 45, none (transition)",
            ]))
            states = ui_audit.summarize([log], ui_audit.read_table(table), 20)
        self.assertEqual(states, {"screen CB2_HallOfFame": {"times": 1, "frames": 29, "logs": 1}})


class CompareTests(unittest.TestCase):
    def test_a_screen_never_uncovered_in_the_baseline_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = write(tmp, "base.json", json.dumps({"screen CB2_HallOfFame": {"times": 1, "frames": 30, "logs": 1}}))
            shard = write(tmp, "shard.json", json.dumps({
                "screen CB2_HallOfFame": {"times": 2, "frames": 60, "logs": 1},
                "window 0: 27x4 at 2,15 screen CB2_EasyChatScreen+0x10": {"times": 1, "frames": 40, "logs": 1}}))
            report = os.path.join(tmp, "report.json")
            code = ui_audit.main(["compare", "--baseline", base, "--out", report, shard])
            with open(report) as data:
                result = json.load(data)
        self.assertEqual(code, 1)
        self.assertEqual(result["new_screens"], ["CB2_EasyChatScreen"])

    def test_the_same_screens_pass_and_shards_are_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = write(tmp, "base.json", json.dumps({"screen CB2_HallOfFame": {"times": 1, "frames": 30, "logs": 1}}))
            one = write(tmp, "one.json", json.dumps({"screen CB2_HallOfFame": {"times": 1, "frames": 30, "logs": 1}}))
            two = write(tmp, "two.json", json.dumps({"screen CB2_HallOfFame+0x4": {"times": 1, "frames": 25, "logs": 1},
                                                     "window 0: 27x4 at 2,15": {"times": 3, "frames": 90, "logs": 2}}))
            self.assertEqual(ui_audit.main(["compare", "--baseline", base, one, two]), 0)
        merged = ui_audit.merge([{"a": {"times": 1, "frames": 2, "logs": 1}}, {"a": {"times": 2, "frames": 3, "logs": 1}}])
        self.assertEqual(merged, {"a": {"times": 3, "frames": 5, "logs": 2}})


if __name__ == "__main__":
    unittest.main()
