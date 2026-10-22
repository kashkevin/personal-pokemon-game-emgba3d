"""The whole game's gameplay check's shard merge (scripts/qa/merge_gameplay_shards.py), as the Windows report job runs
it: every result and blocked target kept, a failed target or a missing shard fails the report."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "qa" / "merge_gameplay_shards.py"


def shard(root, name, results, blocked=(), seconds=10):
    folder = Path(root) / name
    folder.mkdir()
    (folder / "gameplay_check.json").write_text(json.dumps(dict(results=list(results), blocked=list(blocked),
                                                                seconds=seconds, runs={})))


def merge(root, expected):
    out = Path(root) / "merged.json"
    done = subprocess.run([sys.executable, str(SCRIPT), "--shards", str(root), "--expected", str(expected),
                           "--platform", "windows-2022", "--out", str(out)], capture_output=True, text=True)
    return done.returncode, json.loads(out.read_text()), done.stdout


class MergeGameplayShardsTests(unittest.TestCase):
    def test_all_passed(self):
        with tempfile.TemporaryDirectory() as root:
            shard(root, "s0", [dict(key="a", kind="trainer", passed=True, reason="")])
            shard(root, "s1", [dict(key="b", kind="warp", passed=True, reason="")],
                  [dict(key="c", kind="item", reason="no tile")])
            code, merged, _ = merge(root, 2)
        self.assertEqual(code, 0)
        self.assertEqual((merged["shards"], len(merged["results"]), len(merged["blocked"])), (2, 2, 1))
        self.assertEqual(merged["summary"], {"trainer": {"passed": 1}, "warp": {"passed": 1}, "item": {"blocked": 1}})
        self.assertEqual(merged["platform"], "windows-2022")

    def test_a_failed_target_or_a_missing_shard_fails(self):
        with tempfile.TemporaryDirectory() as root:
            shard(root, "s0", [dict(key="a", kind="trainer", passed=False, reason="the battle never ended")])
            code, _, out = merge(root, 1)
        self.assertEqual(code, 1)
        self.assertIn("FAILED a: the battle never ended", out)
        with tempfile.TemporaryDirectory() as root:
            shard(root, "s0", [dict(key="a", kind="trainer", passed=True, reason="")])
            code, _, out = merge(root, 8)
        self.assertEqual(code, 1)
        self.assertIn("MISSING 7 of 8 shards", out)


if __name__ == "__main__":
    unittest.main()
