"""Pinned native enum regression; synthetic mailbox facts, not gameplay proof."""
import struct
from types import SimpleNamespace
import unittest
from uuid import uuid4

from emerald_multiplayer.save_mailbox import Opcode, SaveControl
from emerald_multiplayer.trade_effect_choice import NativeChoiceView
from emerald_multiplayer.trade_effect_menu import HeldTradeEffectMenu


def view_bytes(category, *, move=45):
    # Native include/constants/pokemon.h DamageCategory: NONE0, PHYSICAL1,
    # SPECIAL2, STATUS3. Growl/String Shot in the actual proof exposed this.
    header = struct.pack("<IIIIHHBBBB", 1, 1, 2, 0x1234, 0, 0, 2, 0, 0, 0)
    first = struct.pack("<HBBHBBBBH", move, 40 if move else 0, 40 if move else 0,
                        0, 100 if move else 0, 1 if move else 0, category, 0, 0)
    return header + first + bytes(48)


class NativeMoveCategoryTests(unittest.TestCase):
    def test_actual_native_status_category_survives_save_response_validation(self):
        for category in (1, 2, 3):
            with self.subTest(category=category):
                response = SaveControl(1, 2, str(uuid4()), 3, 0, 131072, 4,
                    Opcode.QUERY_EFFECT_CHOICE, data=view_bytes(category))
                response.validate_response()
                self.assertEqual(NativeChoiceView.parse(response.data).moves[0].category, category)

    def test_none_only_belongs_to_empty_slots_and_unknown_categories_fail(self):
        for category in (0, 4, 255):
            with self.subTest(category=category), self.assertRaises(ValueError):
                NativeChoiceView.parse(view_bytes(category))
        self.assertEqual(NativeChoiceView.parse(view_bytes(0, move=0)).moves[0].category, 0)
        with self.assertRaises(ValueError):
            NativeChoiceView.parse(view_bytes(1, move=0))

    def test_native_category_names_are_not_shifted(self):
        for category, label in ((1, "Physical"), (2, "Special"), (3, "Status")):
            with self.subTest(category=category):
                menu = object.__new__(HeldTradeEffectMenu)
                menu.snapshot = SimpleNamespace(record=None, view=NativeChoiceView.parse(view_bytes(category)))
                menu.page, menu.move_index, menu.detail_page = "move_details", 0, 0
                menu.detail_return, menu.revision = "moves", 1
                screen = menu._render()
                self.assertIn(label + "; Normal", [row.label for row in screen.rows])


if __name__ == "__main__":
    unittest.main()
