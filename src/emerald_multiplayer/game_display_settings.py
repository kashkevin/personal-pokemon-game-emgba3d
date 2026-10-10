"""The native PC game's display settings in the launcher's game settings file.

The game (engine ``src/platform/display_settings.c``) reads and writes the same
keys in ``game-settings.cfg``: ``resolution=``, ``displayMode=`` and
``quality=``, plus ``fullscreen=``/``windowScale=`` for older game builds. The
launcher changes them only while no game is running and keeps every other
line (camera, trees, volume, ...) exactly as the game wrote it. While playing,
F10 opens the same settings in the game itself.
"""
from __future__ import annotations

import os
from pathlib import Path
import re

RESOLUTIONS = ("1280x720", "1920x1080", "2560x1440", "3840x2160")
DEFAULT_RESOLUTION = "1920x1080"
MODES = ("windowed", "borderless", "fullscreen")
QUALITIES = ("low", "medium", "high", "ultra")
DEFAULT_QUALITY = "high"
MAX_FILE_BYTES = 65536

RESOLUTION_LABELS = {
    "1280x720": "1280 x 720 (performance)",
    "1920x1080": "1920 x 1080 (default)",
    "2560x1440": "2560 x 1440",
    "3840x2160": "3840 x 2160 (4K)",
}
MODE_LABELS = {
    "windowed": "Windowed",
    "borderless": "Borderless fullscreen",
    "fullscreen": "Exclusive fullscreen",
}
QUALITY_LABELS = {
    "low": "Low (fastest)",
    "medium": "Medium",
    "high": "High (default)",
    "ultra": "Ultra (4096 shadows, 4x anti-aliasing)",
    "custom": "Custom (chosen in the game)",
}

# Keys this module owns; every other line of the file is kept as it is.
_OWNED = ("resolution=", "displayMode=", "fullscreenMode=", "fullscreen=", "windowScale=")
_QUALITY_KEYS = ("quality=", "shadows=", "lighting=", "effects=", "antialiasing=")
_RESOLUTION = re.compile(r"^(\d{3,4})x(\d{3,4})$")


def _valid_resolution(value):
    match = _RESOLUTION.match(value or "")
    return bool(match) and 320 <= int(match[1]) <= 7680 and 180 <= int(match[2]) <= 4320


def _lines(path):
    try:
        with Path(path).open("rb") as source:
            raw = source.read(MAX_FILE_BYTES + 1)
    except FileNotFoundError:
        return []
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("the game settings file is too large")
    return raw.decode("utf-8", "replace").splitlines()


def read_display_settings(path):
    """The resolution, display mode and quality the game will use (its defaults
    where the file says nothing; older files' fullscreen=/windowScale= as the
    game reads them)."""
    values = dict(resolution=None, mode=None, quality=None)
    legacy_fullscreen = legacy_scale = None
    for line in _lines(path):
        key, _, value = line.strip().partition("=")
        if key == "resolution" and _valid_resolution(value):
            values["resolution"] = value
        elif key == "displayMode" and value in MODES:
            values["mode"] = value
        elif key == "quality" and value in QUALITIES + ("custom",):
            values["quality"] = value
        elif key in ("shadows", "lighting", "effects", "antialiasing") and values["quality"] is None:
            values["quality"] = "custom"  # a value without a preset is a custom choice
        elif key == "fullscreen" and value.isdigit():
            legacy_fullscreen = int(value) != 0
        elif key == "windowScale" and value.isdigit():
            legacy_scale = int(value)
    if values["mode"] is None:
        values["mode"] = "borderless" if legacy_fullscreen else "windowed"
    if values["resolution"] is None:
        # windowScale=4 (1280x720) was every older file's default, not a choice.
        values["resolution"] = (f"{320 * legacy_scale}x{180 * legacy_scale}"
                                if legacy_scale in (2, 3, 5, 6) else DEFAULT_RESOLUTION)
    if values["quality"] is None:
        values["quality"] = DEFAULT_QUALITY
    return values


def write_display_settings(path, *, resolution, mode, quality):
    """Writes the three settings; ``quality="custom"`` keeps the game's own
    quality lines. Other lines stay as they are. Atomic (temporary file, then
    replace)."""
    if not _valid_resolution(resolution) or mode not in MODES or quality not in QUALITIES + ("custom",):
        raise ValueError("invalid display settings")
    path = Path(path)
    # Windowed keeps the fullscreen kind F11 switches to; the others name it.
    owned = _OWNED if mode != "windowed" else tuple(key for key in _OWNED if key != "fullscreenMode=")
    kept = [line for line in _lines(path)
            if not line.strip().startswith(owned)
            and (quality == "custom" or not line.strip().startswith(_QUALITY_KEYS))]
    width, height = (int(part) for part in resolution.split("x"))
    lines = kept + [f"fullscreen={0 if mode == 'windowed' else 1}"]
    for scale in (2, 3, 5, 6):
        if (width, height) == (320 * scale, 180 * scale):
            lines.append(f"windowScale={scale}")
    lines += [f"resolution={resolution}", f"displayMode={mode}"]
    if mode != "windowed":
        lines.append(f"fullscreenMode={mode}")
    if quality != "custom":
        lines.append(f"quality={quality}")
    data = ("\n".join(lines) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as target:
        target.write(data)
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary, path)
    return read_display_settings(path)
