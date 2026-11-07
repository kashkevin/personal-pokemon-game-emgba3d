"""One launcher at a time on a player's files (KNOWN_ISSUES MS-220).

The launcher runs one game at a time ("A game is already running.") and keeps what it knows of the player's characters
(which one last played which world account) in memory while it runs. Nothing stopped a second launcher on the same files:
a second click on the desktop icon while the first was still opening started another menu, which knew nothing of the
first's game - a second game of the same character could be started beside it, two games each saving the character (the
progress of the one that closed first replaced by the other's), and each launcher's record of the characters written
over the other's.

The launcher now holds a lock on a file among the player's files (``launcher.lock`` in its private folder) while it runs.
The operating system lets it go when the process ends, however it ends (Exit, a crash, End task), so a lock left behind
never keeps the launcher closed. A second launcher on the same files finds it held, tells the player the first is open
and ends. A lock file that cannot be made or opened (an unusual folder, a security program) starts the launcher as
before, without the lock. Another Windows user, or another profile folder, has files of its own and a lock of its own.
"""
from __future__ import annotations

import errno
import os
import sys
from pathlib import Path

LOCK_NAME = "launcher.lock"
TITLE = "EmeraldTogether"
ALREADY_OPEN = ("EmeraldTogether is already open on this PC. Its window may be behind other windows or minimized on the "
                "taskbar.")
# What the lock calls return when another process holds it (Windows' _locking: EACCES; flock: EWOULDBLOCK/EAGAIN).
_HELD = {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK, errno.EDEADLK, getattr(errno, "EDEADLOCK", errno.EDEADLK)}


class AlreadyOpen(Exception):
    """Another launcher holds this player's files."""


class LauncherLock:
    """The held lock; the process keeps it until release() or its end."""

    def __init__(self, handle, path):
        self._handle, self.path = handle, path

    @property
    def held(self):
        return self._handle is not None

    def release(self):
        handle, self._handle = self._handle, None
        if handle is not None:
            handle.close()                      # closing the file lets the lock go


def hold_launcher(private_root) -> LauncherLock | None:
    """Take this player's launcher lock. Raises AlreadyOpen when another launcher holds it; None when the lock file
    cannot be used (the launcher then starts without it, as before this lock)."""
    path = Path(private_root) / LOCK_NAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "a+b")              # not inherited by the games the launcher starts (Python's default)
    except OSError:
        return None
    try:
        if os.name == "nt":
            import msvcrt
            if handle.seek(0, 2) == 0:          # _locking locks bytes that exist: the file holds one
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        handle.close()
        if error.errno in _HELD:
            raise AlreadyOpen(str(path)) from None
        return None
    return LauncherLock(handle, path)


def tell_already_open():
    """The second launcher's word to the player before it ends: a message box on Windows (the launcher has no console),
    a line on its standard error elsewhere."""
    try:
        print(ALREADY_OPEN, file=sys.stderr)
    except (OSError, ValueError):
        pass
    if os.name == "nt":
        try:
            import ctypes
            # MB_OK | MB_ICONINFORMATION | MB_SETFOREGROUND | MB_TOPMOST
            ctypes.windll.user32.MessageBoxW(None, ALREADY_OPEN, TITLE, 0x00000040 | 0x00010000 | 0x00040000)
        except Exception:                       # noqa: BLE001 - no message is better than no exit
            pass
