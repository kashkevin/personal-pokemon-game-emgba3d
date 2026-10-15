"""The native PC game's keyboard bindings in the launcher's game settings file.

The game (engine ``src/platform/keybinds.c``) reads and writes ``key.<action>=<SDL key name>`` lines
of the same ``game-settings.cfg`` that holds the display settings: ``key.a=Z``, ``key.fastforward=Space``.
A binding is written only when it differs from the default, so "restore defaults" is simply no lines.
The launcher changes them only while no game is running and keeps every other line exactly as the
game wrote it. While playing, the 3D game's F10 menu has a Controls page for the same bindings.

What stays fixed on purpose, so the settings can always be reached again: F1-F12 and Esc are never
game buttons (F10 opens the game's settings menu, Esc leaves a menu or cancels a key capture), the
settings menus' own navigation does not follow the bindings, and the gamepad keeps working whatever
the keyboard is set to. The key names are SDL's own (the game reads them with ``SDL_GetKeyFromName``),
so a file can also be edited by hand.
"""
from __future__ import annotations

import os
from pathlib import Path

MAX_FILE_BYTES = 65536

# (id, the line's name, what the screens call it, the default key's SDL name). The order is the
# engine's (keybinds.c): the first ten are GBA buttons, the last is held for the speed-up.
ACTIONS = (
    ("a", "A button", "Z"),
    ("b", "B button", "X"),
    ("start", "Start", "Return"),
    ("select", "Select", "\\"),
    ("l", "L button", "A"),
    ("r", "R button", "S"),
    ("up", "Up", "Up"),
    ("down", "Down", "Down"),
    ("left", "Left", "Left"),
    ("right", "Right", "Right"),
    ("fastforward", "Fast forward (hold)", "Space"),
)
ACTION_IDS = tuple(action[0] for action in ACTIONS)
LABELS = {action[0]: action[1] for action in ACTIONS}
DEFAULTS = {action[0]: action[2] for action in ACTIONS}

RESERVED = frozenset(["Escape"] + [f"F{number}" for number in range(1, 13)])

_NAMED_KEYS = (
    "Up", "Down", "Left", "Right", "Return", "Keypad Enter", "Space", "Tab", "Backspace", "Delete", "Insert",
    "Home", "End", "PageUp", "PageDown", "Left Shift", "Right Shift", "Left Ctrl", "Right Ctrl", "Left Alt",
    "Right Alt", ",", ".", "/", ";", "'", "[", "]", "\\", "-", "=", "`", "Keypad +", "Keypad -", "Keypad *",
    "Keypad /", "Keypad .",
)
# The keys the launcher can capture and the game accepts, by SDL name (checked against SDL_GetKeyName).
KEY_NAMES = tuple([chr(code) for code in range(ord("A"), ord("Z") + 1)] + [str(digit) for digit in range(10)]
                  + list(_NAMED_KEYS) + [f"Keypad {digit}" for digit in range(10)])
_CANONICAL = {name.lower(): name for name in KEY_NAMES + tuple(RESERVED)}

# Tk key symbols that are not their SDL name.
_TK_NAMES = {
    "space": "Space", "BackSpace": "Backspace", "Prior": "PageUp", "Next": "PageDown", "KP_Enter": "Keypad Enter",
    "KP_Add": "Keypad +", "KP_Subtract": "Keypad -", "KP_Multiply": "Keypad *", "KP_Divide": "Keypad /",
    "KP_Decimal": "Keypad .", "Shift_L": "Left Shift", "Shift_R": "Right Shift", "Control_L": "Left Ctrl",
    "Control_R": "Right Ctrl", "Alt_L": "Left Alt", "Alt_R": "Right Alt", "comma": ",", "period": ".",
    "slash": "/", "semicolon": ";", "apostrophe": "'", "quoteright": "'", "bracketleft": "[",
    "bracketright": "]", "backslash": "\\", "minus": "-", "equal": "=", "grave": "`", "quoteleft": "`",
    "Escape": "Escape",
}
for _digit in range(10):
    _TK_NAMES[f"KP_{_digit}"] = f"Keypad {_digit}"

# Keys the game already uses for something else: allowed, but the player should know.
_SHARED = {
    **{key: "This key also moves the 3D camera." for key in (",", ".", "-", "=", "Keypad +", "Keypad -")},
    **{key: "This key is also a screen-reader hotkey." for key in ("L", "H", "U", "T", "Y")},
    "Tab": "This key also opens the details view in menus.",
}

ASSIGNED, UNCHANGED, SWAPPED, CONFLICT, RESERVED_KEY, INVALID = (
    "assigned", "unchanged", "swapped", "conflict", "reserved", "invalid")


def canonical_key(name):
    """SDL's spelling of a key name (the game compares them without case), or None."""
    return _CANONICAL.get(name.lower()) if isinstance(name, str) else None


def key_from_tk(keysym):
    """The SDL name of the key a Tk key press carries, or None for a key the game cannot use."""
    if not isinstance(keysym, str) or not keysym:
        return None
    name = _TK_NAMES.get(keysym)
    if name is None:
        if len(keysym) == 1 and keysym.isalnum() and keysym.isascii():
            name = keysym.upper()
        elif keysym[0] == "F" and keysym[1:].isdigit() or keysym in ("Up", "Down", "Left", "Right", "Return",
                                                                       "Tab", "Delete", "Insert", "Home", "End"):
            name = keysym
    return canonical_key(name) if name else None


def key_label(name):
    """What the screens show for a key."""
    return {"Return": "Enter", "Escape": "Esc", "Backspace": "Backspace"}.get(name, name)


def shared_warning(name):
    return _SHARED.get(name)


def is_reserved(name):
    return canonical_key(name) in RESERVED


def _lines(path):
    try:
        with Path(path).open("rb") as source:
            raw = source.read(MAX_FILE_BYTES + 1)
    except FileNotFoundError:
        return []
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("the game settings file is too large")
    return raw.decode("utf-8", "replace").splitlines()


def _line_action(line):
    # As the game reads it: the name runs straight up to the "=" (no spaces), case aside.
    key = line.partition("=")[0].lower()
    return key[4:] if key.startswith("key.") and key[4:] in ACTION_IDS and "=" in line else None


def resolve(bindings):
    """The engine's rule for a file that binds one key twice (``Keybinds_Finish``): the later action
    goes back to its default; if that is taken too, everything goes back to the defaults."""
    result = dict(bindings)
    seen = {}
    for action in ACTION_IDS:
        key = result[action]
        if key in seen:
            result[action] = DEFAULTS[action]
        seen.setdefault(result[action], action)
    if len(set(result.values())) != len(ACTION_IDS):
        return dict(DEFAULTS)
    return result


def read_controls(path):
    """The key of every action the game will use (its defaults where the file says nothing; a line
    naming an unknown or reserved key is ignored, as in the game)."""
    bindings = dict(DEFAULTS)
    for line in _lines(path):
        action = _line_action(line)
        if action is None:
            continue
        key = canonical_key(line.partition("=")[2].rstrip(" \r\n"))
        if key is not None and key not in RESERVED:
            bindings[action] = key
    return resolve(bindings)


def validate(bindings):
    if set(bindings) != set(ACTION_IDS):
        raise ValueError("every action needs a key")
    for key in bindings.values():
        if canonical_key(key) is None or canonical_key(key) in RESERVED:
            raise ValueError("invalid or reserved key")
    if len({canonical_key(key) for key in bindings.values()}) != len(ACTION_IDS):
        raise ValueError("two actions share a key")


def write_controls(path, bindings):
    """Writes the bindings that differ from the defaults; other lines stay as they are. Atomic
    (temporary file, then replace). ``bindings`` must be complete and conflict-free."""
    validate(bindings)
    path = Path(path)
    kept = [line for line in _lines(path) if _line_action(line) is None]
    changed = [f"key.{action}={canonical_key(bindings[action])}" for action in ACTION_IDS
               if canonical_key(bindings[action]) != DEFAULTS[action]]
    data = ("\n".join(kept + changed) + "\n").encode("utf-8") if kept or changed else b""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as target:
        target.write(data)
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary, path)


def assign(bindings, action, key, *, swap=False):
    """Binds ``key`` to ``action`` in ``bindings`` (changed in place). Returns ``(result, other)``:
    ``other`` is the action that already had the key. With a conflict and ``swap`` false nothing
    changes; with ``swap`` the two exchange keys, so no action is ever left without one."""
    key = canonical_key(key)
    if action not in DEFAULTS or key is None:
        return INVALID, None
    if key in RESERVED:
        return RESERVED_KEY, None
    if bindings[action] == key:
        return UNCHANGED, None
    holder = next((other for other, held in bindings.items() if held == key), None)
    if holder is not None:
        if not swap:
            return CONFLICT, holder
        bindings[holder] = bindings[action]
        bindings[action] = key
        return SWAPPED, holder
    bindings[action] = key
    return ASSIGNED, None


class ControlsEditor:
    """The Controls page's behaviour without a window: one action waits for a key, a key another
    action has is a conflict the player settles (swap or cancel), nothing reaches the file until the
    page saves. ``press`` takes a Tk key symbol."""

    def __init__(self, bindings=None):
        self.bindings = dict(DEFAULTS if bindings is None else bindings)
        self.saved = dict(self.bindings)
        self.capturing = None   # the action waiting for a key
        self.pending = None     # (action, key, other) waiting for "swap" or "cancel"
        self.message = ""

    @property
    def dirty(self):
        return self.bindings != self.saved

    def start_capture(self, action):
        if action not in DEFAULTS:
            raise ValueError("unknown action")
        self.capturing, self.pending = action, None
        self.message = f"Press the new key for {LABELS[action]} (now {key_label(self.bindings[action])}). Esc cancels."

    def cancel(self):
        self.capturing = self.pending = None
        self.message = "Cancelled. Nothing changed."

    def press(self, keysym):
        """A key pressed while an action waits for one. Returns True when the page should refresh."""
        if self.capturing is None:
            return False
        key = key_from_tk(keysym)
        if key == "Escape":
            self.cancel()
            return True
        action = self.capturing
        if key is None:
            self.message = "That key can't be used in the game. Press another key, or Esc to cancel."
            return True
        result, other = assign(self.bindings, action, key)
        if result == RESERVED_KEY:
            self.message = (f"{key_label(key)} can't be a game button (F1-F12 and Esc are kept for the menus). "
                            "Press another key, or Esc to cancel.")
            return True
        self.capturing = None
        if result == CONFLICT:
            self.pending = (action, key, other)
            self.message = (f"{key_label(key)} is already the key for {LABELS[other]}. "
                            f"Swap the two keys, or keep things as they were?")
        elif result == UNCHANGED:
            self.message = f"{LABELS[action]} stays {key_label(key)}."
        else:
            warning = shared_warning(key)
            self.message = f"{LABELS[action]} is now {key_label(key)}." + (f" {warning}" if warning else "")
        return True

    def confirm_swap(self):
        if self.pending is None:
            return False
        action, key, _ = self.pending
        self.pending = None
        result, other = assign(self.bindings, action, key, swap=True)
        if result == SWAPPED:
            self.message = f"{LABELS[action]} and {LABELS[other]} traded keys."
            return True
        self.message = "Nothing changed."
        return False

    def restore_defaults(self):
        self.bindings = dict(DEFAULTS)
        self.capturing = self.pending = None
        self.message = "Default keys restored here. Save to use them."

    def mark_saved(self):
        self.saved = dict(self.bindings)
