"""The GitHub Actions workflows use the official actions at a major that runs on Node.js 24 (KNOWN_ISSUES U31-16).

GitHub's runners deprecate Node.js 20. Each action's own action.yml declares its runtime (`runs.using`); read at the
tags on github.com on 2026-11-05, the first major on node24 is checkout v5, setup-python v6, upload-artifact v6 and
download-artifact v7 (upload-artifact v5 and download-artifact v5 and v6 still declare node20). The workflows use the
current majors, read the same way: checkout v7, setup-python v7, upload-artifact v7, download-artifact v8. An action
that is not in the table fails this test: read its action.yml at the tag first, then add it here.

Text checks only (the suite's environment has no YAML parser); the workflows themselves run only on GitHub."""
from __future__ import annotations

from pathlib import Path
import re
import unittest

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"

# the first major whose action.yml declares `runs.using: node24` (checked at the tag, 2026-11-05)
FIRST_NODE24_MAJOR = {
    "actions/checkout": 5,
    "actions/setup-python": 6,
    "actions/upload-artifact": 6,
    "actions/download-artifact": 7,
}


def uses():
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = re.match(r"\s*(?:-\s+)?uses:\s*['\"]?([^'\"\s#]+)", line)
            if match:
                yield f"{path.name}:{number}", match.group(1)


class WorkflowActionTests(unittest.TestCase):
    def test_the_workflows_exist(self):
        names = {path.name for path in WORKFLOWS.glob("*.y*ml")}
        self.assertIn("windows-package.yml", names)
        self.assertIn("python-tests.yml", names)
        self.assertGreaterEqual(len(list(uses())), 100)

    def test_every_action_runs_on_node24(self):
        for where, reference in uses():
            with self.subTest(where=where, uses=reference):
                action, _, version = reference.partition("@")
                self.assertIn(action, FIRST_NODE24_MAJOR, "an action whose runtime was not checked")
                major = re.fullmatch(r"v(\d+)(?:\.\d+){0,2}", version)
                self.assertIsNotNone(major, "a version tag vN, vN.N or vN.N.N")
                self.assertGreaterEqual(int(major.group(1)), FIRST_NODE24_MAJOR[action],
                                        "this major still runs on Node.js 20")

    def test_a_pattern_downloads_lone_match_is_read_where_it_lands(self):
        # download-artifact v5 and later extract a pattern's only matching artifact straight into its path: the
        # shard merges read both layouts (tests/test_merge_gameplay_shards.py runs the Windows jobs' script)
        gameplay = (WORKFLOWS / "gameplay-check.yml").read_text(encoding="utf-8")
        self.assertIn("pattern: gameplay-shard-*", gameplay)
        self.assertIn('glob.glob("shards/gameplay_check.json") + glob.glob("shards/*/gameplay_check.json")', gameplay)
        windows = (WORKFLOWS / "windows-package.yml").read_text(encoding="utf-8")
        for pattern in ("gameplay-windows-shard-*", "gameplay-windows-3d-shard-*"):
            self.assertRegex(windows, rf"pattern: {re.escape(pattern)}\n\s+path: shards\n(?:.*\n){{1,3}}"
                                      r"\s+python3 scripts/qa/merge_gameplay_shards\.py --shards shards")
        merge = (WORKFLOWS.parents[1] / "scripts" / "qa" / "merge_gameplay_shards.py").read_text(encoding="utf-8")
        self.assertIn('os.path.join(args.shards, "gameplay_check.json")', merge)


if __name__ == "__main__":
    unittest.main()
