"""A running Windows game seen from outside, for the launcher proofs on a Windows PC (the CI runner).

The Linux proofs read a game's memory through /proc/PID/mem and press keys with xdotool on the game's own X display.
On Windows the same is ReadProcessMemory (the memory is only read, never written), the keyboard's own window messages
posted to the game's window (WM_KEYDOWN/WM_KEYUP with the key's scan code, what ci_play_check.py presses on the
installed game; each game gets its own keys whatever window has the focus) and, for the ordinary close, the window's
WM_CLOSE (SDL turns it into a quit, exit 0).

Windows may load the executable away from its preferred base (ASLR). The symbols' addresses come from the build's own
symbol table (the preferred base), so every read moves by the difference; the module found at the game's image base
must be its executable (the same COFF time stamp and image size as the file). ctypes only; nothing is installed.
"""
from __future__ import annotations

import ctypes
from pathlib import Path
import struct
import sys
import time

PROCESS_QUERY_INFORMATION, PROCESS_VM_READ = 0x0400, 0x0010
LIST_MODULES_32BIT = 0x01
WM_KEYDOWN, WM_KEYUP, WM_CLOSE = 0x0100, 0x0101, 0x0010
# The game's default keys (A = Z, B = X, Start = Enter, the arrows) as virtual-key codes, by the xdotool names the
# Linux proofs use; the arrows are extended keys (without the flag a scan code is the keypad's).
VK = {"z": 0x5A, "x": 0x58, "Return": 0x0D, "Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28}
EXTENDED = frozenset((0x25, 0x26, 0x27, 0x28))
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010


def pe_header(data):
    """(preferred image base, COFF time stamp, size of image) from an executable's first bytes (PE32 only)."""
    if data[:2] != b"MZ":
        raise ValueError("not an executable (no MZ header)")
    offset = struct.unpack_from("<I", data, 0x3C)[0]
    if data[offset:offset + 4] != b"PE\0\0":
        raise ValueError("no PE header")
    stamp = struct.unpack_from("<I", data, offset + 8)[0]
    optional = offset + 24
    magic = struct.unpack_from("<H", data, optional)[0]
    if magic != 0x10B:
        raise ValueError(f"not a 32-bit executable (optional header magic {magic:#x})")
    return struct.unpack_from("<I", data, optional + 28)[0], stamp, struct.unpack_from("<I", data, optional + 56)[0]


def _signed(value):
    """An LPARAM: a 32-bit Python passes it as a signed long."""
    from ctypes import wintypes
    return value - (1 << 32) if ctypes.sizeof(wintypes.LPARAM) == 4 and value >= 1 << 31 else value


def _kernel32():
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.LPVOID, ctypes.c_size_t,
                                           ctypes.POINTER(ctypes.c_size_t)]
    kernel32.ReadProcessMemory.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    return kernel32


def _psapi():
    from ctypes import wintypes
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.EnumProcessModulesEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD,
                                           ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
    psapi.EnumProcessModulesEx.restype = wintypes.BOOL
    return psapi


def _user32():
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    user32.MapVirtualKeyW.restype = wintypes.UINT
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL
    return user32


class ProcessMemory:
    """Reads of one game process at its executable's symbol addresses (moved to where Windows loaded it)."""

    def __init__(self, pid, exe, timeout=15):
        self.pid = pid
        self.preferred, stamp, size = pe_header(Path(exe).read_bytes()[:4096])
        self._kernel32 = _kernel32()
        self.handle = self._kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), f"cannot open the game process {pid}")
        self.base = self._image_base(timeout)
        self.delta = self.base - self.preferred
        loaded = pe_header(self._raw(self.base, 4096))
        if (loaded[1], loaded[2]) != (stamp, size):
            raise AssertionError(f"the module at {self.base:#x} in game process {pid} is not its executable")

    def _image_base(self, timeout):
        """The executable is the process's first module (its 32-bit modules: the game is a 32-bit program). Just after
        the start the list can be incomplete (ERROR_PARTIAL_COPY): asked again until it is there."""
        from ctypes import wintypes
        psapi = _psapi()
        modules, needed = (wintypes.HMODULE * 512)(), wintypes.DWORD()
        deadline = time.monotonic() + timeout
        while True:
            if psapi.EnumProcessModulesEx(self.handle, modules, ctypes.sizeof(modules), ctypes.byref(needed),
                                          LIST_MODULES_32BIT) and needed.value and modules[0]:
                return int(modules[0])
            if time.monotonic() >= deadline:
                raise OSError(ctypes.get_last_error(), f"no modules of the game process {self.pid}")
            time.sleep(.2)

    def _raw(self, address, size):
        buffer, done = ctypes.create_string_buffer(size), ctypes.c_size_t()
        if not self._kernel32.ReadProcessMemory(self.handle, ctypes.c_void_p(address), buffer, size,
                                                ctypes.byref(done)) or done.value != size:
            raise OSError(ctypes.get_last_error(), f"cannot read {size} bytes at {address:#x} of game {self.pid}")
        return buffer.raw

    def read(self, address, size):
        """`size` bytes at the build's own address of a symbol (plus an offset)."""
        return self._raw(address + self.delta, size)

    def close(self):
        if self.handle:
            self._kernel32.CloseHandle(self.handle)
            self.handle = None


def window_of(pid):
    """The game's visible top-level window (SDL's "SDL_app" first; IME helper windows are not visible), or None."""
    from ctypes import wintypes
    user32 = _user32()
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            name = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, name, 64)
            found.append((name.value != "SDL_app", int(hwnd)))
        return True

    user32.EnumWindows(visit, 0)
    return min(found)[1] if found else None


def press(hwnd, key, seconds):
    """One key held `seconds`, as the keyboard's messages to that window (the game's own keys: see VK)."""
    user32 = _user32()
    vk = VK[key]
    scan = user32.MapVirtualKeyW(vk, 0)                 # MAPVK_VK_TO_VSC
    lparam = 1 | (scan << 16) | ((1 << 24) if vk in EXTENDED else 0)
    if not user32.PostMessageW(hwnd, WM_KEYDOWN, vk, _signed(lparam)):
        raise OSError(ctypes.get_last_error(), "the game's window refused a key")
    time.sleep(seconds)
    user32.PostMessageW(hwnd, WM_KEYUP, vk, _signed(lparam | (1 << 30) | (1 << 31)))


def close(hwnd):
    """The window's close button: WM_CLOSE (SDL's quit; the game exits 0)."""
    _user32().PostMessageW(hwnd, WM_CLOSE, 0, 0)


def keep_on_top(hwnd, on_top=True):
    """The window above every other one (on_top) or back among them, without the focus: a picture of the desktop then
    shows this game where the players' windows overlap on the runner's one desktop. The order of the windows only: the
    keys still go to each game's own window."""
    return bool(_user32().SetWindowPos(hwnd, HWND_TOPMOST if on_top else HWND_NOTOPMOST, 0, 0, 0, 0,
                                       SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE))


def available():
    return sys.platform == "win32"
