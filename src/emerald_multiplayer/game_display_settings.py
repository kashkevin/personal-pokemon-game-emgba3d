"""The native PC game's display settings in the launcher's game settings file.

The game (engine ``src/platform/display_settings.c``) reads and writes the same
keys in ``game-settings.cfg``: ``resolution=``, ``displayMode=`` and
``quality=``, plus ``fullscreen=``/``windowScale=`` for older game builds. The
launcher changes them only while no game is running and keeps every other
line (camera, trees, volume, ...) exactly as the game wrote it. While playing,
the 3D game's F10 menu changes the same settings (its Audio page the four
volumes at the end of this module); the Classic 2D game has no such menu.
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
_QUALITY_KEYS = ("quality=", "shadows=", "lighting=", "effects=", "details=", "antialiasing=")
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
        elif key in ("shadows", "lighting", "effects", "details", "antialiasing") and values["quality"] is None:
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


# ---- Audio: the game's four volume lines, each 0 to 10 (0-100% in 10% steps), read and written by the game as by this
# module (engine include/platform/audio_volume.h); the 3D game's F10 > Audio page changes the same ones while playing.
#   volume=       master: everything the game plays
#   musicVolume=  music, the fanfares and jingles included (a level-up, a Pokemon Center's heal, a new item)
#   sfxVolume=    sound effects
#   cryVolume=    Pokemon cries
# The owner's decision of 2026-11-05: music at 70% by default, sound effects at 100%; the cries at 100% as well.
AUDIO_KEYS = (("volume", "volume"), ("music_volume", "musicVolume"), ("sfx_volume", "sfxVolume"),
              ("cry_volume", "cryVolume"))
AUDIO_LABELS = {"volume": "Master volume", "music_volume": "Music", "sfx_volume": "Sound effects",
                "cry_volume": "Pokemon cries"}
DEFAULT_VOLUME = 10
DEFAULT_MUSIC_VOLUME = 7
DEFAULT_SFX_VOLUME = 10
DEFAULT_CRY_VOLUME = 10
AUDIO_DEFAULTS = {"volume": DEFAULT_VOLUME, "music_volume": DEFAULT_MUSIC_VOLUME, "sfx_volume": DEFAULT_SFX_VOLUME,
                  "cry_volume": DEFAULT_CRY_VOLUME}
# A file written before musicVolume= and sfxVolume= existed (no line of either): music and sound effects take the defaults
# above, volume= stays the master as it was, and cryVolume=5 reads as 10. Every game before them wrote cryVolume=5 as its
# default and never applied it, so the cries stay as loud as they always were; any other cryVolume= there is the
# player's own choice and is kept (now applied). The game reads such a file the same way (AudioVolumes_Finish).
OLD_UNAPPLIED_CRY_VOLUME = 5
_AUDIO_FILE_KEYS = {file_key: key for key, file_key in AUDIO_KEYS}


def volume_percent(value):
    """A volume's 0-10 as the game and the launcher show it: "70%"."""
    return f"{value * 10}%"


def read_audio_settings(path):
    """The four volumes, each 0-10 (keys ``volume``, ``music_volume``, ``sfx_volume``, ``cry_volume``): the file's
    values, the defaults where it says nothing, an older file as the game reads it (see ``OLD_UNAPPLIED_CRY_VOLUME``)."""
    values = dict(AUDIO_DEFAULTS)
    new_keys = False
    for line in _lines(path):
        file_key, _, value = line.strip().partition("=")
        key = _AUDIO_FILE_KEYS.get(file_key)
        if key is None:
            continue
        new_keys = new_keys or key in ("music_volume", "sfx_volume")
        if value.isdigit() and int(value) <= 10:
            values[key] = int(value)
    if not new_keys and values["cry_volume"] == OLD_UNAPPLIED_CRY_VOLUME:
        values["cry_volume"] = DEFAULT_CRY_VOLUME
    return values


def write_audio_settings(path, *, volume, cry_volume, music_volume=None, sfx_volume=None):
    """Write the four volumes (a music or sound effect volume left out keeps what the file says, or its default); every
    other line of the file stays as the game wrote it. Atomic."""
    current = read_audio_settings(path)
    chosen = {"volume": volume, "music_volume": current["music_volume"] if music_volume is None else music_volume,
              "sfx_volume": current["sfx_volume"] if sfx_volume is None else sfx_volume, "cry_volume": cry_volume}
    if any(type(value) is not int or not 0 <= value <= 10 for value in chosen.values()):
        raise ValueError("invalid audio settings")
    path = Path(path)
    owned = tuple(f"{file_key}=" for _, file_key in AUDIO_KEYS)
    kept = [line for line in _lines(path) if not line.strip().startswith(owned)]
    data = ("\n".join(kept + [f"{file_key}={chosen[key]}" for key, file_key in AUDIO_KEYS]) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as target:
        target.write(data)
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary, path)
    return read_audio_settings(path)
