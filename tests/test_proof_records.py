"""The launcher proofs' evidence records (LauncherHarness.record(name, **fields), native_launcher_battle_proof.py) never
pass a field that collides with the record's own parameter. Regression for windows-package run 121: the Tower proof's
milestone step recorded `name=` (the Pokemon's name) and stopped with "got multiple values for argument 'name'" right
after the game had made the milestone Pokemon."""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "src", ROOT / "scripts" / "multiplayer", ROOT / "scripts" / "windows-runtime"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
import native_launcher_battle_proof  # noqa: E402


class ProofRecordTests(unittest.TestCase):
    def test_no_record_field_collides_with_the_records_own_parameters(self):
        own = [p for p in inspect.signature(native_launcher_battle_proof.LauncherHarness.record).parameters
               if p not in ("self", "fields")]
        found = []
        for path in sorted((ROOT / "scripts" / "multiplayer").glob("*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == "record":
                    filled = own[:len(node.args)]           # the parameters the call already gives by position
                    found += [f"{path.name}:{node.lineno} {kw.arg}=" for kw in node.keywords if kw.arg in filled]
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
