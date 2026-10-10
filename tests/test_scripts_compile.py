"""Every proof, qualifier and packaging script at least compiles.

Most of these run only on Windows or against real games, so no other test
imports them; a syntax error would otherwise surface only when the owner's
build or a proof run starts (as build_launcher.py's did once under Wine)."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ScriptCompileTests(unittest.TestCase):
    def test_all_scripts_compile(self):
        scripts = sorted((ROOT / "scripts").rglob("*.py"))
        self.assertGreater(len(scripts), 20)
        for path in scripts:
            with self.subTest(script=str(path.relative_to(ROOT))):
                compile(path.read_text(encoding="utf-8"), str(path), "exec")


if __name__ == "__main__":
    unittest.main()
