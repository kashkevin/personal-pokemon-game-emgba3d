"""A game ends with the launcher that started it, however the launcher ends (KNOWN_ISSUES MS-221).

The launcher holds what a game needs to save into its world: the companion's connection and the lease on the
character's save file. A game the launcher left behind - the launcher crashed, or was ended in Task Manager's Details
while the game ran - played on without them: nothing it saved could reach its world (the next start puts the world's
save back and sets such a save aside: there is no offline progress), and EmeraldTogether started again could open a
second game of the same character on the same save file beside it.

Windows: each game joins a job object this launcher process holds, set to end its processes when its last handle is
closed; Windows closes the launcher's handle as the launcher ends, so the game ends with it. The handle is not
inheritable, so the game never holds one itself. Linux (the rehearsal platform): the game asks the kernel for SIGKILL
when the thread that started it ends (prctl PR_SET_PDEATHSIG); the launcher starts each game from the thread of the
session that waits for it to close.

A game ended this way keeps what it last saved, as when its window is closed (the save file is replaced whole, never
written in place). When this cannot be arranged (an older Windows refusing a nested job, no prctl) the game starts as
before.
"""
from __future__ import annotations

import ctypes
import os
import signal
import sys
import threading

_JOB = None                 # Windows: the job's handle (an int), False once creating it failed
_JOB_LOCK = threading.Lock()

# Windows constants
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001

# Linux constants
_PR_SET_PDEATHSIG = 1


def spawn_options() -> dict:
    """Keyword arguments to add to the spawn of a game (``subprocess.Popen``, ``asyncio.create_subprocess_exec``).

    Linux: a ``preexec_fn`` that asks for SIGKILL when the starting thread ends. Elsewhere none (Windows binds the
    process after it starts: ``bind``)."""
    if sys.platform.startswith("linux"):
        preexec = _linux_preexec()
        if preexec is not None:
            return {"preexec_fn": preexec}
    return {}


def bind(pid: int) -> bool:
    """After the spawn: on Windows the process joins this launcher's job. True when it did (elsewhere False: there
    ``spawn_options`` did the work)."""
    if os.name != "nt" or not isinstance(pid, int) or pid <= 0:
        return False
    job = _windows_job()
    if job is None:
        return False
    kernel32 = _kernel32()
    process = kernel32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
    if not process:
        return False
    try:
        return bool(kernel32.AssignProcessToJobObject(job, process))
    finally:
        kernel32.CloseHandle(process)


def _linux_preexec():
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        prctl = libc.prctl
    except (OSError, AttributeError):
        return None
    prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    prctl.restype = ctypes.c_int
    death = int(signal.SIGKILL)
    parent = os.getpid()

    def preexec():
        # In the child, between fork and exec: only the function resolved above, with plain numbers.
        prctl(_PR_SET_PDEATHSIG, death, 0, 0, 0)
        if os.getppid() != parent:          # the launcher ended before the request was made
            os.kill(os.getpid(), death)
    return preexec


def _kernel32():
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _BasicLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32), ("SchedulingClass", ctypes.c_uint32)]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _windows_job():
    """This launcher's job, made once and held until the process ends (its handle is never closed here)."""
    global _JOB
    with _JOB_LOCK:
        if _JOB is None:
            _JOB = False
            try:
                kernel32 = _kernel32()
                job = kernel32.CreateJobObjectW(None, None)
                if job:
                    limits = _ExtendedLimits()
                    limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                    if kernel32.SetInformationJobObject(job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                                                        ctypes.byref(limits), ctypes.sizeof(limits)):
                        _JOB = job
                    else:
                        kernel32.CloseHandle(job)
            except (AttributeError, OSError):
                _JOB = False
        return _JOB or None
