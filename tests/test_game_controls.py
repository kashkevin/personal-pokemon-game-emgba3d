"""The launcher's keyboard bindings (game_controls.py): the file lines shared with the game's
``key.*`` settings, conflicts, reserved keys, the Tk key mapping and the page's editor."""
import tempfile
import unittest
from pathlib import Path

from emerald_multiplayer import game_controls as gc


class ControlsFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "game-settings.cfg"

    def test_missing_file_and_empty_file_give_the_defaults(self):
        self.assertEqual(gc.read_controls(self.path), gc.DEFAULTS)
        self.path.write_text("volume=5\n")
        self.assertEqual(gc.read_controls(self.path), gc.DEFAULTS)

    def test_defaults_are_the_keys_of_every_earlier_build(self):
        self.assertEqual(gc.DEFAULTS, dict(a="Z", b="X", start="Return", select="\\", l="A", r="S", up="Up",
                                           down="Down", left="Left", right="Right", fastforward="Space"))
        self.assertEqual(len(set(gc.DEFAULTS.values())), len(gc.ACTIONS))

    def test_round_trip_writes_only_what_differs_and_keeps_other_lines(self):
        self.path.write_text("volume=7\nresolution=1920x1080\nkey.a=Q\nkey.future=ignored\n")
        bindings = dict(gc.DEFAULTS, b="E", fastforward="Left Shift", a="Z")
        gc.write_controls(self.path, bindings)
        lines = self.path.read_text().splitlines()
        self.assertEqual(lines, ["volume=7", "resolution=1920x1080", "key.future=ignored",
                                 "key.b=E", "key.fastforward=Left Shift"])   # key.a=Q replaced; Z is the default
        self.assertEqual(gc.read_controls(self.path), bindings)

    def test_restoring_the_defaults_leaves_no_key_lines(self):
        gc.write_controls(self.path, dict(gc.DEFAULTS, a="Q", b="E"))
        gc.write_controls(self.path, gc.DEFAULTS)
        self.assertEqual(self.path.read_text(), "")
        self.path.write_text("volume=3\nkey.a=Q\n")
        gc.write_controls(self.path, gc.DEFAULTS)
        self.assertEqual(self.path.read_text(), "volume=3\n")

    def test_game_spelling_is_read_case_insensitively(self):
        self.path.write_text("KEY.A=q\nkey.b=left shift\r\nkey.start = x\nkey.l=Keypad 5\n")
        bindings = gc.read_controls(self.path)
        self.assertEqual((bindings["a"], bindings["b"], bindings["l"]), ("Q", "Left Shift", "Keypad 5"))
        self.assertEqual(bindings["start"], "Return")   # " x" has a space before it: not the game's line

    def test_unknown_or_reserved_keys_in_the_file_are_ignored(self):
        self.path.write_text("key.a=Escape\nkey.b=F10\nkey.l=F1\nkey.r=Nonsense\nkey.up=\nkey.select\n")
        self.assertEqual(gc.read_controls(self.path), gc.DEFAULTS)

    def test_a_file_that_binds_a_key_twice_stays_playable_like_the_game(self):
        self.path.write_text("key.a=Q\nkey.b=Q\n")
        bindings = gc.read_controls(self.path)
        self.assertEqual((bindings["a"], bindings["b"]), ("Q", "X"))    # the later action goes back
        self.path.write_text("key.b=A\nkey.a=Q\n")                      # L's own default is taken by B
        self.assertEqual(gc.read_controls(self.path), gc.DEFAULTS)
        self.path.write_text("key.a=X\nkey.b=Z\n")                      # a deliberate swap is kept
        self.assertEqual((gc.read_controls(self.path)["a"], gc.read_controls(self.path)["b"]), ("X", "Z"))
        for text in ("key.a=Q\nkey.b=Q\nkey.start=Q\n", "key.up=Left\n", "key.fastforward=A\nkey.l=A\n"):
            self.path.write_text(text)
            self.assertEqual(len(set(gc.read_controls(self.path).values())), len(gc.ACTIONS))

    def test_write_refuses_anything_that_would_leave_the_game_unplayable(self):
        for bad in (dict(gc.DEFAULTS, a="Escape"), dict(gc.DEFAULTS, a="F10"), dict(gc.DEFAULTS, a="Nonsense"),
                    dict(gc.DEFAULTS, a="X"), {"a": "Z"}, dict(gc.DEFAULTS, extra="Q")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                gc.write_controls(self.path, bad)
        self.assertFalse(self.path.exists())

    def test_oversized_settings_file_is_refused(self):
        self.path.write_bytes(b"x" * (gc.MAX_FILE_BYTES + 1))
        with self.assertRaises(ValueError):
            gc.read_controls(self.path)


class AssignTests(unittest.TestCase):
    def test_conflict_is_reported_and_a_swap_exchanges_keys(self):
        bindings = dict(gc.DEFAULTS)
        self.assertEqual(gc.assign(bindings, "a", "q"), (gc.ASSIGNED, None))
        self.assertEqual(bindings["a"], "Q")
        self.assertEqual(gc.assign(bindings, "a", "Q"), (gc.UNCHANGED, None))
        self.assertEqual(gc.assign(bindings, "b", "Q"), (gc.CONFLICT, "a"))
        self.assertEqual(bindings["b"], "X")
        self.assertEqual(gc.assign(bindings, "b", "Q", swap=True), (gc.SWAPPED, "a"))
        self.assertEqual((bindings["a"], bindings["b"]), ("X", "Q"))
        gc.validate(bindings)

    def test_reserved_and_invalid_keys_are_refused(self):
        bindings = dict(gc.DEFAULTS)
        for key in ["Escape", "F10", "f1", "F12"]:
            self.assertEqual(gc.assign(bindings, "a", key, swap=True)[0], gc.RESERVED_KEY)
        self.assertEqual(gc.assign(bindings, "a", "Nonsense")[0], gc.INVALID)
        self.assertEqual(gc.assign(bindings, "nothing", "Q")[0], gc.INVALID)
        self.assertEqual(bindings, gc.DEFAULTS)
        self.assertTrue(gc.is_reserved("escape") and gc.is_reserved("F10") and not gc.is_reserved("Z"))

    def test_every_action_can_move_and_the_menu_keys_stay_free(self):
        ring = ["Q", "W", "E", "K", "J", "D", "L", "Tab", ",", "=", "Left Shift"]
        bindings = dict(gc.DEFAULTS)
        for action, key in zip(gc.ACTION_IDS, ring):
            self.assertEqual(gc.assign(bindings, action, key)[0], gc.ASSIGNED)
        gc.validate(bindings)
        self.assertFalse({"Escape", "F10"} & set(bindings.values()))


class KeyMappingTests(unittest.TestCase):
    def test_tk_key_symbols_become_sdl_names(self):
        cases = {"z": "Z", "Z": "Z", "5": "5", "Return": "Return", "KP_Enter": "Keypad Enter", "space": "Space",
                 "Tab": "Tab", "BackSpace": "Backspace", "Shift_L": "Left Shift", "Control_R": "Right Ctrl",
                 "Up": "Up", "Prior": "PageUp", "Next": "PageDown", "backslash": "\\", "comma": ",",
                 "equal": "=", "KP_7": "Keypad 7", "KP_Add": "Keypad +", "F10": "F10", "Escape": "Escape"}
        for symbol, expected in cases.items():
            with self.subTest(symbol=symbol):
                self.assertEqual(gc.key_from_tk(symbol), expected)
        for symbol in ("Caps_Lock", "dead_acute", "", None, "eacute", "XF86AudioMute"):
            with self.subTest(symbol=symbol):
                self.assertIsNone(gc.key_from_tk(symbol))

    def test_every_listed_key_is_canonical_and_distinct(self):
        self.assertEqual(len(set(map(str.lower, gc.KEY_NAMES))), len(gc.KEY_NAMES))
        for name in gc.KEY_NAMES:
            self.assertEqual(gc.canonical_key(name), name)
            self.assertEqual(gc.canonical_key(name.lower()), name)
        self.assertIn("Left Shift", gc.KEY_NAMES)

    def test_keys_the_game_already_uses_warn(self):
        for key in ("L", "H", ",", "Tab"):
            self.assertTrue(gc.shared_warning(key))
        self.assertIsNone(gc.shared_warning("Q"))
        self.assertEqual(gc.key_label("Return"), "Enter")


class EditorTests(unittest.TestCase):
    def test_rebinding_flow_with_conflict_swap_and_cancel(self):
        editor = gc.ControlsEditor()
        self.assertFalse(editor.press("q"))          # nothing waits for a key
        editor.start_capture("a")
        self.assertIn("Press the new key for A button (now Z)", editor.message)
        self.assertTrue(editor.press("q"))
        self.assertEqual(editor.bindings["a"], "Q")
        self.assertTrue(editor.dirty)
        self.assertIsNone(editor.capturing)
        editor.start_capture("b")
        editor.press("q")                            # A's key: a conflict, nothing changed yet
        self.assertEqual(editor.pending, ("b", "Q", "a"))
        self.assertEqual(editor.bindings["b"], "X")
        self.assertIn("already the key for A button", editor.message)
        editor.cancel()
        self.assertEqual((editor.bindings["a"], editor.bindings["b"]), ("Q", "X"))
        editor.start_capture("b")
        editor.press("q")
        self.assertTrue(editor.confirm_swap())
        self.assertEqual((editor.bindings["a"], editor.bindings["b"]), ("X", "Q"))
        gc.validate(editor.bindings)

    def test_reserved_unusable_and_escape_keys(self):
        editor = gc.ControlsEditor()
        editor.start_capture("a")
        editor.press("F10")
        self.assertEqual(editor.capturing, "a")      # still waiting
        self.assertIn("can't be a game button", editor.message)
        editor.press("Caps_Lock")
        self.assertEqual(editor.capturing, "a")
        self.assertIn("can't be used", editor.message)
        editor.press("Escape")
        self.assertIsNone(editor.capturing)
        self.assertEqual(editor.bindings, gc.DEFAULTS)
        self.assertFalse(editor.dirty)

    def test_shared_key_warning_and_restore_defaults(self):
        editor = gc.ControlsEditor()
        editor.start_capture("l")
        editor.press("h")
        self.assertIn("screen-reader hotkey", editor.message)
        editor.restore_defaults()
        self.assertEqual(editor.bindings, gc.DEFAULTS)
        self.assertFalse(editor.dirty)
        editor.start_capture("a")
        editor.press("q")
        editor.mark_saved()
        self.assertFalse(editor.dirty)
        editor.restore_defaults()
        self.assertTrue(editor.dirty)                # differs from what is saved until the page saves


if __name__ == "__main__":
    unittest.main()
