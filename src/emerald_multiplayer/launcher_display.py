"""Local display choices, separate from autosave settings and character state."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from .live_checkpoint import _atomic, _json_bytes
from .reset_protocol import SOURCES


DEFAULTS = dict(text_size="Standard", favorite_hunts=[], hunt_show="All sources", hunt_order="Source order",
                favorites_only=False, history_mode="All formats", history_outcome="All outcomes")
FORMAT = "emerald-launcher-display-v1"


def _validate(value):
    if type(value) is not dict or set(value) != set(DEFAULTS):
        raise ValueError("invalid display preferences")
    for key, choices in (("text_size", ("Standard", "Larger", "Largest")),
            ("hunt_show", ("All sources", "Started", "No attempts yet")),
            ("hunt_order", ("Source order", "Most attempts", "Name")),
            ("history_mode", ("All formats", "1v1", "2v2")),
            ("history_outcome", ("All outcomes", "Win", "Loss", "Draw"))):
        if type(value[key]) is not str or value[key] not in choices:
            raise ValueError("invalid display preference")
    favorites = value["favorite_hunts"]
    if (type(value["favorites_only"]) is not bool or type(favorites) is not list or len(favorites) > len(SOURCES)
            or any(type(source) is not int or source not in SOURCES for source in favorites)
            or favorites != sorted(set(favorites))):
        raise ValueError("invalid favorite hunt catalogue")
    return deepcopy(value)


class DisplayPreferences:
    """Preserve unreadable files; callers can still use defaults for this window."""
    def __init__(self, directory=None):
        self.path = Path(directory) / "launcher-display.json" if directory is not None else None
        self.value = deepcopy(DEFAULTS)
        self.available = True
        if self.path is not None:
            try:
                with self.path.open("rb") as source:
                    raw = source.read(4097)
                if len(raw) > 4096:
                    raise ValueError("display file too large")
                record = json.loads(raw)
                if type(record) is not dict or set(record) != {"format", "display"} or record["format"] != FORMAT:
                    raise ValueError("unknown display file")
                self.value = _validate(record["display"])
            except FileNotFoundError:
                pass
            except (OSError, ValueError, UnicodeError):
                self.available = False

    def update(self, **changes):
        candidate = _validate(dict(self.value, **changes))
        if not self.available:
            self.value = candidate
            return False
        if self.path is not None:
            try:
                # The existing launcher owns/creates its private root; display
                # persistence must not invent a selected world or character.
                _atomic(self.path, _json_bytes(dict(format=FORMAT, display=candidate)))
            except OSError:
                self.value = candidate
                return False
        self.value = candidate
        return True


def scrollable_frame(parent, *, padding=12):
    import tkinter as tk
    from tkinter import ttk
    container = ttk.Frame(parent)
    container.pack(fill="both", expand=True)
    background = ttk.Style(parent).lookup("TFrame", "background") or None
    canvas = tk.Canvas(container, highlightthickness=0, **({"background": background} if background else {}))
    bar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
    bar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    canvas.configure(yscrollcommand=bar.set)
    frame = ttk.Frame(canvas, padding=padding)
    item = canvas.create_window((0, 0), window=frame, anchor="nw")
    frame.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda event: canvas.itemconfigure(item, width=event.width))
    # Keyboard scrolling is scoped to this focused canvas, never to the game.
    canvas.configure(takefocus=True)
    canvas.bind("<Prior>", lambda _: canvas.yview_scroll(-1, "pages"))
    canvas.bind("<Next>", lambda _: canvas.yview_scroll(1, "pages"))
    canvas.bind("<Home>", lambda _: canvas.yview_moveto(0))
    canvas.bind("<End>", lambda _: canvas.yview_moveto(1))
    return frame
