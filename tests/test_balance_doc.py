"""docs/balance-defaults.md mirrors the host's balance values (KNOWN_ISSUES G2): a value changed in balance.py without
the page, or the page without the code, fails here."""
import re
import unittest
from dataclasses import fields
from pathlib import Path

from emerald_multiplayer.balance import BALANCE

DOC = Path(__file__).resolve().parents[1] / "docs" / "balance-defaults.md"


def _shown(value):
    """A value as the page writes it."""
    if isinstance(value, dict):
        return ", ".join(f"{name} {count}" for name, count in value.items())
    if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
        return ", ".join(value)
    if isinstance(value, float) and value < 1 and abs(1 / value - round(1 / value)) < 1e-9 and round(1 / value) > 10:
        return f"1/{round(1 / value)}"
    return str(value)


class BalanceDocTests(unittest.TestCase):
    def test_every_host_value_is_on_the_page_as_the_code_has_it(self):
        rows = dict(re.findall(r"^\| `(\w+)` \| ([^|]+?) \|", DOC.read_text(encoding="utf-8"), re.M))
        for item in fields(BALANCE):
            with self.subTest(item.name):
                self.assertIn(item.name, rows, "missing from docs/balance-defaults.md")
                self.assertEqual(rows[item.name], _shown(getattr(BALANCE, item.name)))


if __name__ == "__main__":
    unittest.main()
