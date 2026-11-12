"""Where the native 3D game puts its F12 pictures (KNOWN_ISSUES MS-241).

The launcher starts every game in a new folder of its own (``player_runtime.py``, ``draft_runtime.py``), and the game
put its pictures in a ``screenshots`` folder beside itself: a new hidden folder among the launch folders each time,
which the player could not find. The launcher now names ``EmeraldTogether`` in the player's Pictures folder
(``--screenshots``; a game older than this ignores it). The game makes that folder with the first picture; if it
cannot, it keeps the picture beside itself as before and logs why. Nothing here creates or changes a file.
"""

from __future__ import annotations

import os
from pathlib import Path

FOLDER_NAME = "EmeraldTogether"

# FOLDERID_Pictures (KnownFolders.h): the player's Pictures folder wherever it really is (moved by the player, or
# into OneDrive), which %USERPROFILE%\Pictures is not always.
_FOLDERID_PICTURES = "{33E28130-4E1E-4676-835A-98395C3BC3BB}"


def _windows_pictures():
    """The Pictures known folder (SHGetKnownFolderPath), or None."""
    import ctypes
    import uuid
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]

    known = uuid.UUID(_FOLDERID_PICTURES)
    guid = GUID(known.time_low, known.time_mid, known.time_hi_version,
                (ctypes.c_ubyte * 8).from_buffer_copy(known.bytes[8:]))
    shell32 = ctypes.WinDLL("shell32")
    ole32 = ctypes.WinDLL("ole32")
    get = shell32.SHGetKnownFolderPath
    get.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
    get.restype = ctypes.c_long
    path = ctypes.c_wchar_p()
    try:
        if get(ctypes.byref(guid), 0, None, ctypes.byref(path)) != 0 or not path.value:
            return None
        return Path(path.value)
    finally:
        if path:
            ole32.CoTaskMemFree(path)


def pictures_folder():
    """The player's Pictures folder when it is there, else None."""
    candidate = None
    if os.name == "nt":
        try:
            candidate = _windows_pictures()
        except (OSError, AttributeError, ValueError):
            candidate = None
    if candidate is None:
        try:
            candidate = Path.home() / "Pictures"
        except (KeyError, RuntimeError):
            return None
    try:
        return candidate if candidate.is_absolute() and candidate.is_dir() else None
    except OSError:
        return None


def folder():
    """The folder to name with ``--screenshots``: EmeraldTogether in the Pictures folder, or None (the game then keeps
    its pictures beside itself, as before). Never raises: a launch never waits on where pictures go."""
    try:
        pictures = pictures_folder()
    except Exception:  # noqa: BLE001 - any failure: the game's own default
        return None
    return None if pictures is None else pictures / FOLDER_NAME


def arguments():
    """The native game's arguments for the folder: ("--screenshots", path) or ()."""
    named = folder()
    return () if named is None else ("--screenshots", str(named))
