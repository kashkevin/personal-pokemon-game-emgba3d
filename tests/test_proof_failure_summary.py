"""A failed launcher proof's diagnosis printed into the job's log (scripts/multiplayer/proof_failure_summary.py): a
stopped route's diagnosis, the loop stalls and the route timeline's counts, stall probes and last events, long lines
cut, and nothing raised whatever is missing or unreadable."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts" / "multiplayer") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts" / "multiplayer"))
import proof_failure_summary as summary  # noqa: E402


def printed(*paths):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = summary.main([str(path) for path in paths])
    return code, out.getvalue()


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "multiplayer-proof"
        self.proof = self.root / "abandon-ffa-exit"
        (self.proof / "application" / "world" / "battles").mkdir(parents=True)

    def test_the_diagnosis_the_stalls_and_the_timeline(self):
        (self.proof / "application" / "world" / "battles" / "b1.diagnosis.json").write_text(json.dumps(dict(
            reason="execution_interrupted", error="NativeBattleError: deadline", code="7",
            traceback=[f"frame {n}\n" for n in range(12)],
            players=[dict(slot=2, pending=None, polls=dict(count=40, last=0.1),
                          hops=[dict(dispatch=n, opcode=3, status="answered") for n in range(5)])])))
        (self.proof / "loop-stalls.jsonl").write_text(json.dumps(dict(slot=0, seconds=2.5, stack="x" * 5000)) + "\n")
        events = [dict(t=n, ev="command") for n in range(100)] + [dict(t=101, ev="stall", stacks="s" * 9000)]
        (self.proof / "route-timeline.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events) + "{broken\n")
        code, text = printed(self.root)
        self.assertEqual(code, 0)
        self.assertIn("reason execution_interrupted, error NativeBattleError: deadline, code 7", text)
        self.assertIn("frame 11", text)
        self.assertNotIn("frame 3\n", text)                       # the traceback's last eight lines only
        self.assertIn('"dispatch": 4', text)
        self.assertNotIn('"dispatch": 1', text)                   # each player's last three hops only
        self.assertIn("loop-stalls.jsonl: 1 stalls over 1.5 s", text)
        self.assertIn("command 100, stall 1, unreadable 1", text)
        self.assertIn("the last stall probes", text)
        self.assertIn("more characters)", text)                   # the long lines are cut
        self.assertLess(max(len(line) for line in text.splitlines()), summary.STALL + 100)

    def test_nothing_there_is_said_and_nothing_raised(self):
        code, text = printed(self.root / "missing", self.root)
        self.assertEqual(code, 0)
        self.assertIn("(not there)", text)
        (self.proof / "application" / "world" / "battles" / "b2.diagnosis.json").write_text("{not json")
        code, text = printed(self.root)
        self.assertEqual(code, 0)
        self.assertIn("unreadable", text)


if __name__ == "__main__":
    unittest.main()
