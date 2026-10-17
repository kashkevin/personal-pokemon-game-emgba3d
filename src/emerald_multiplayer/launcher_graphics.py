"""The launcher window's side of Graphics mode: the check before a game starts,
the "3D cannot start" prompt, and the settings controls (graphics_mode.py holds
the rules; this module only drives them from the Tk window).

The check runs in a thread so the window stays responsive; its result is picked
up by polling on the Tk thread (Tk is not thread safe). Nothing here starts a
game itself: ``resolve`` hands the chosen mode ("3d" or "2d") to the caller, or
reports that the player cancelled.
"""
from __future__ import annotations

import queue
import threading

from .tk_threads import start_thread
from .graphics_mode import (EXIT_GRAPHICS_UNAVAILABLE, MODE_2D, MODE_3D, MODE_LABELS, MODES,
                            GraphicsPreference, choose_launch, explain_failure, probe_graphics)

__all__ = ["GraphicsGate", "ask_fallback", "graphics_page", "EXIT_GRAPHICS_UNAVAILABLE"]

TITLE = "3D graphics are not available on this PC"


def ask_fallback(root, explanation, can_launch_2d):
    """Modal prompt: returns "2d" for Launch in Classic 2D, None for Cancel
    (or a closed window). Cancel never changes any setting."""
    import tkinter as tk
    from tkinter import ttk
    answer = {"mode": None}
    window = tk.Toplevel(root)
    window.title(TITLE)
    window.transient(root)
    window.resizable(False, False)
    body = ttk.Frame(window, padding=18)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text=TITLE, font=("Segoe UI", 12, "bold")).pack(anchor="w")
    ttk.Label(body, text=explanation, wraplength=520, justify="left").pack(anchor="w", pady=(10, 4))
    if not can_launch_2d:
        ttk.Label(body, text="This package has no Classic 2D game, so the game cannot be started here.",
                  wraplength=520, justify="left").pack(anchor="w", pady=(6, 0))
    buttons = ttk.Frame(body)
    buttons.pack(anchor="e", pady=(14, 0))

    def choose(mode):
        answer["mode"] = mode
        window.destroy()

    play = ttk.Button(buttons, text="Launch in Classic 2D", command=lambda: choose(MODE_2D),
                      state="normal" if can_launch_2d else "disabled")
    play.pack(side="left", padx=(0, 8))
    ttk.Button(buttons, text="Cancel", command=lambda: choose(None)).pack(side="left")
    window.protocol("WM_DELETE_WINDOW", lambda: choose(None))
    window.bind("<Escape>", lambda _: choose(None))
    (play if can_launch_2d else buttons).focus_set()
    window.grab_set()
    root.wait_window(window)
    return answer["mode"]


class GraphicsGate:
    """Decide, before any game or character-setup game starts, which one to start."""

    def __init__(self, root, preference, bundle_source, *, probe=probe_graphics, ask=ask_fallback,
                 message=lambda code: None, busy=lambda value: None, poll_ms=60):
        self.root, self.preference, self._bundle_source = root, preference, bundle_source
        self.probe, self.ask, self.message, self.busy, self.poll_ms = probe, ask, message, busy, poll_ms
        self._checking = False

    @property
    def checking(self):
        return self._checking

    def _bundle(self):
        try:
            return self._bundle_source()
        except Exception:
            return None

    def effective_preference(self, has_classic):
        """The saved mode, except that a package without a Classic 2D game cannot
        honor 2D (the saved choice is kept as it is)."""
        return self.preference.mode if self.preference.mode != MODE_2D or has_classic else MODE_3D

    def resolve(self, proceed, cancelled=lambda: None):
        """Call ``proceed(mode)`` once the mode is known, or ``cancelled()``.

        Asynchronous only when a 3D check has to run."""
        if self._checking:
            return
        bundle = self._bundle()
        has_classic = bundle is not None and bundle.has_classic() if hasattr(bundle, "has_classic") else False
        wanted = self.effective_preference(has_classic)
        if wanted == MODE_2D:
            proceed(MODE_2D)
            return
        try:
            executable = bundle.verify(MODE_3D)[0]
        except Exception:
            # The package itself is not usable; the normal start reports that.
            proceed(MODE_3D)
            return
        self._checking = True
        self.busy(True)
        self.message("graphics_checking")
        results = queue.SimpleQueue()
        start_thread(threading.Thread(target=lambda: results.put(self.probe(executable)),
                         name="emerald-graphics-check", daemon=True))
        self.root.after(self.poll_ms, lambda: self._poll(results, proceed, cancelled, has_classic))

    def _poll(self, results, proceed, cancelled, has_classic):
        try:
            result = results.get_nowait()
        except queue.Empty:
            self.root.after(self.poll_ms, lambda: self._poll(results, proceed, cancelled, has_classic))
            return
        self._checking = False
        self.busy(False)
        choice = choose_launch(MODE_3D, lambda: result)
        if choice.mode is not None:
            proceed(choice.mode)
            return
        if self.ask(self.root, explain_failure(result), has_classic) == MODE_2D and has_classic:
            self.message("graphics_fallback")
            proceed(MODE_2D)
        else:
            self.message("graphics_cancelled")
            cancelled()


def graphics_page(page, preference, *, has_classic, running, probe_now, notify=lambda text: None):
    """The Graphics mode row of the launcher's Game display tab."""
    import tkinter as tk
    from tkinter import ttk
    ttk.Label(page, text=("Graphics mode chooses how the game is drawn. 3D Diorama is the default when your PC "
                          "supports it; Classic 2D is the original look and runs on almost any PC. Your choice "
                          "is remembered. Your saves, Pokémon, items, progress and multiplayer character are the "
                          "same in both, so you can switch back and forth."), wraplength=570,
              justify="left").pack(anchor="w", pady=(0, 8))
    labels = [MODE_LABELS[mode] for mode in MODES]
    variable = tk.StringVar(value=MODE_LABELS[preference.mode])
    row = ttk.Frame(page)
    row.pack(anchor="w")
    ttk.Label(row, text="Graphics mode").pack(side="left", padx=(0, 12))
    box = ttk.Combobox(row, textvariable=variable, values=labels, state="readonly", width=40)
    box.pack(side="left")
    feedback = tk.StringVar()

    def chosen(_=None):
        mode = MODES[labels.index(variable.get())]
        if mode == MODE_2D and not has_classic:
            variable.set(MODE_LABELS[preference.mode])
            feedback.set("This package has no Classic 2D game.")
            return
        saved = preference.set(mode)
        text = ("Saved. " if saved else "Applied for this window; the saved preference could not be updated. ")
        text += ("A game that is running keeps the graphics it started with. Close it, then start again to "
                 "switch." if running() else "The game uses this the next time it starts.")
        feedback.set(text)
        notify(text)

    box.bind("<<ComboboxSelected>>", chosen)
    test = ttk.Button(page, text="Test 3D graphics now", command=lambda: feedback.set(probe_now()))
    test.pack(anchor="w", pady=(8, 2))
    ttk.Label(page, textvariable=feedback, wraplength=570, justify="left").pack(anchor="w")
    ttk.Separator(page).pack(fill="x", pady=10)
