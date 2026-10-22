"""Every game symbol a launcher proof reads by name is one the Windows symbol table holds. On Windows the harness builds
its table only from the names it asks for (native_launcher_battle_proof.NEEDED and EXTRA_NEEDED, pe_symbol_table), so a
name read elsewhere works on Linux and fails only on the runner: windows-package run 145's rival proof stopped at the
reward with KeyError 'gSaveBlock1Ptr' (VAR_ROUTE110_STATE), after the same steps had passed on Linux."""
from __future__ import annotations

from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "src", ROOT / "scripts" / "multiplayer", ROOT / "scripts" / "windows-runtime"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
import native_launcher_battle_proof as harness  # noqa: E402

READ = re.compile(r"""\.mem\("([A-Za-z_0-9]+)"|symbols\["([A-Za-z_0-9]+)"\]""")


class WindowsSymbolTableTests(unittest.TestCase):
    def test_every_name_a_launcher_proof_reads_is_asked_for(self):
        asked = set(harness.NEEDED) | set(harness.EXTRA_NEEDED)
        proofs = sorted((ROOT / "scripts" / "multiplayer").glob("native_launcher_*_proof.py"))
        self.assertGreater(len(proofs), 10)
        for proof in proofs:
            names = {a or b for a, b in READ.findall(proof.read_text())}
            with self.subTest(proof=proof.name):
                self.assertEqual(sorted(names - asked), [])

    def test_the_rival_proofs_save_block_read_is_there(self):
        self.assertIn("gSaveBlock1Ptr", harness.EXTRA_NEEDED)


if __name__ == "__main__":
    unittest.main()
