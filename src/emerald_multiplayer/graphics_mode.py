"""The launcher's Graphics mode: 3D Diorama or Classic 2D.

Two native games are built from the same engine source and share the save,
the ROM pairing, the multiplayer bridge and the settings file; they differ only in
how they draw (engine ``Makefile_pc``: ``DIORAMA=1`` is the 3D game). This module
holds what the launcher decides around them:

* the player's **preference** (``graphics-mode.json`` in the launcher's private
  folder: it belongs to this PC, not to a character or a world). 3D is the default.
  The preference is only ever changed by the player: a failed 3D check never
  rewrites it, so nobody is moved to 2D for good;
* a **probe** of the 3D game (``--probe-graphics``: the same checks the game's own
  start-up makes, on a hidden throwaway window; it reads and writes no save or
  setting) and the decision it feeds: which game to start this time and what to
  tell the player first.

Switching is restart based: the mode is chosen when a game starts and cannot change
while one is running (the two renderers are different programs). Nothing here
touches a save, a Pokémon, an inventory or multiplayer data.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess

from .live_checkpoint import _atomic, _json_bytes

MODE_3D = "3d"
MODE_2D = "2d"
MODES = (MODE_3D, MODE_2D)
DEFAULT_MODE = MODE_3D
MODE_LABELS = {MODE_3D: "3D Diorama (default when supported)", MODE_2D: "Classic 2D"}

#: What a game or a probe exits with when its renderer cannot start (engine sdl2.c).
EXIT_GRAPHICS_UNAVAILABLE = 78
PROBE_ARGUMENT = "--probe-graphics"
PROBE_TIMEOUT = 20.0
_PREFERENCE_FILE = "graphics-mode.json"
_FORMAT = "emerald-graphics-mode-v1"
_MAX_PROBE_BYTES = 4096


class GraphicsPreference:
    """The saved choice. Unreadable files are kept and the default is used for
    this run (like the launcher's display preferences)."""

    def __init__(self, directory=None):
        self.path = Path(directory) / _PREFERENCE_FILE if directory is not None else None
        self.mode = DEFAULT_MODE
        self.available = True
        if self.path is None:
            return
        try:
            with self.path.open("rb") as source:
                raw = source.read(513)
            if len(raw) > 512:
                raise ValueError("graphics preference file too large")
            record = json.loads(raw)
            if (type(record) is not dict or set(record) != {"format", "mode"}
                    or record["format"] != _FORMAT or record["mode"] not in MODES):
                raise ValueError("unknown graphics preference file")
            self.mode = record["mode"]
        except FileNotFoundError:
            pass
        except (OSError, ValueError, UnicodeError):
            self.available = False

    def set(self, mode):
        """Remember the player's choice; False if it could not be written (the
        choice still applies to this window)."""
        if mode not in MODES:
            raise ValueError("unknown graphics mode")
        self.mode = mode
        if self.path is None or not self.available:
            return False
        try:
            _atomic(self.path, _json_bytes(dict(format=_FORMAT, mode=mode)))
        except OSError:
            return False
        return True


@dataclass(frozen=True)
class ProbeResult:
    supported: bool
    reason: str = "ok"
    detail: str = ""
    renderer: str = ""
    version: str = ""


def parse_probe_output(output, exit_code):
    """The game's one JSON line; anything else (a crash, silence, another
    program's text) is an unusable check, never a pass."""
    try:
        if len(output) > _MAX_PROBE_BYTES:
            raise ValueError()
        line = [part for part in output.decode("utf-8", "replace").splitlines() if part.strip()][-1]
        value = json.loads(line)
        if (type(value) is not dict or type(value.get("supported")) is not bool
                or value.get("graphics") not in MODES):
            raise ValueError()
        text = {key: value.get(key, "") if type(value.get(key, "")) is str else "" for key in
                ("reason", "detail", "renderer", "version")}
    except (ValueError, IndexError, UnicodeError):
        return ProbeResult(False, "probe_failed", f"the graphics check gave no usable answer (exit code {exit_code})")
    # A pass needs both the line and a clean exit: a game that crashes after
    # printing is not usable.
    if value["supported"] and exit_code != 0:
        return ProbeResult(False, "probe_failed", f"the graphics check ended with exit code {exit_code}")
    return ProbeResult(value["supported"], text["reason"] or ("ok" if value["supported"] else "unavailable"),
                       text["detail"], text["renderer"], text["version"])


def probe_graphics(executable, *, timeout=PROBE_TIMEOUT, run=subprocess.run):
    """Ask a game executable whether its renderer can start on this PC.

    Never raises: a missing file, a hang or a crash is a failed check."""
    options = dict(capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        done = run([str(executable), PROBE_ARGUMENT], **options)
    except subprocess.TimeoutExpired:
        return ProbeResult(False, "probe_failed", "the graphics check did not finish in time")
    except OSError as error:
        return ProbeResult(False, "probe_failed", f"the game could not be started for the graphics check ({error.__class__.__name__})")
    return parse_probe_output(done.stdout or b"", done.returncode)


@dataclass(frozen=True)
class LaunchChoice:
    """What to start. ``ask`` is set when the player must decide first:
    3D was wanted and cannot start here."""
    mode: str | None
    ask: bool = False
    probe: ProbeResult | None = None
    note: str = ""


def choose_launch(preference_mode, probe_3d):
    """Decide the game for this start without asking anyone.

    ``probe_3d`` is called (once) only when 3D is wanted. The saved
    preference is never an input to change: falling back for one start is
    not a new preference."""
    if preference_mode == MODE_2D:
        return LaunchChoice(MODE_2D, note="Classic 2D, as chosen in Game display.")
    result = probe_3d()
    if result.supported:
        return LaunchChoice(MODE_3D, probe=result)
    return LaunchChoice(None, ask=True, probe=result)


_REASONS = {
    "context": "Your graphics driver could not create the OpenGL 3.3 view the 3D mode draws with.",
    "functions": "Your graphics driver is missing OpenGL features the 3D mode needs.",
    "shaders": "Your graphics driver could not compile the 3D mode's shaders.",
    "window": "A window for the 3D view could not be created.",
    "sdl_init": "The video system could not start.",
    "forced": "3D was switched off for a test.",
    "probe_failed": "The 3D graphics check could not complete.",
}


def explain_failure(result):
    """A plain-language explanation for a player, with the technical detail last."""
    why = _REASONS.get(result.reason, "The 3D mode cannot start on this PC.")
    lines = [why,
             "This is common on virtual machines, remote desktop sessions, or PCs whose graphics "
             "driver is missing or very old. Updating the graphics driver often fixes it.",
             "Classic 2D is the same game with the original look. Your saves, Pokémon, items, "
             "progress and multiplayer character stay exactly as they are, and you can switch back "
             "to 3D whenever you like."]
    detail = result.detail or result.reason
    shown = f"Technical detail: {detail}" + (f" ({result.renderer})" if result.renderer else "")
    return "\n\n".join(lines + [shown])
