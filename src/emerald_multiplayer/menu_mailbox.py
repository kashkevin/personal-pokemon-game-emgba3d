"""Strict 16-byte input and 240-byte display frames for the native Players menu."""
from dataclasses import dataclass
from pathlib import Path
import struct

from .player_menu import MenuRow, MenuScreen

ABI = 1
MAGIC = 0x31554D45
MAILBOX_SIZE = 512
SCREEN_SIZE = 240
REQUEST_SIZE = 16
FIELDS = frozenset({"menu_abi_version", "menu_abi_address", "menu_mailbox_address", "menu_mailbox_size"})
_REQUEST = struct.Struct("<IIHB5s")


def _uint(value, maximum, minimum=0):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("menu integer is outside its bounds")


def _string(value, size):
    if type(value) is not str or len(value) >= size or any(not 32 <= ord(c) <= 126 for c in value):
        raise ValueError("menu text must be bounded printable ASCII")
    return value.encode("ascii").ljust(size, b"\0")


def _read_string(value):
    end = value.find(b"\0")
    if end < 0 or any(value[end:]) or any(not 32 <= c <= 126 for c in value[:end]):
        raise ValueError("menu text has invalid padding or characters")
    return value[:end].decode("ascii")


@dataclass(frozen=True)
class MenuRequest:
    sequence: int
    screen: int
    action: int
    kind: int

    def pack(self):
        _uint(self.sequence, 0xFFFFFFFF, 1)
        _uint(self.screen, 0xFFFFFFFF)
        _uint(self.kind, 3, 1)
        _uint(self.action, 7)
        if self.kind == 2 and (not self.screen or not self.action):
            raise ValueError("menu selection needs a displayed action")
        if self.kind != 2 and self.action:
            raise ValueError("menu open/close cannot choose an action")
        if self.kind == 1 and self.screen:
            raise ValueError("menu open cannot claim a previous screen")
        return _REQUEST.pack(self.sequence, self.screen, self.action, self.kind, bytes(5))

    @classmethod
    def unpack(cls, value):
        if type(value) is not bytes or len(value) != REQUEST_SIZE:
            raise ValueError("menu request must have exactly 16 bytes")
        sequence, screen, action, kind, reserved = _REQUEST.unpack(value)
        if any(reserved):
            raise ValueError("menu request reserved bytes must be zero")
        result = cls(sequence, screen, action, kind)
        result.pack()
        return result


def pack_screen(request_sequence, screen, *, close=False, reopen_trade=False, allow_battle_admission=False,
                release=False):
    """`release` (flags 3, PC games with menu_release_abi_version 1): the reply to an Enter battle choice the
    companion refused before any ADMIT; the game's latched window takes it and shows it with its rows usable."""
    _uint(request_sequence, 0xFFFFFFFF, 1)
    if (not isinstance(screen, MenuScreen) or type(close) is not bool or type(release) is not bool
            or type(reopen_trade) is not bool or type(allow_battle_admission) is not bool
            or close + reopen_trade + release > 1):
        raise ValueError("menu response needs a typed screen and close flag")
    _uint(screen.revision, 0xFFFFFFFF, 1)
    if type(screen.back) is not int or screen.back not in (0, 7):
        raise ValueError("menu back action must be absent or seven")
    if type(screen.rows) is not tuple or len(screen.rows) > 6:
        raise ValueError("menu screen permits at most six rows")
    data = struct.pack("<IIBBH", request_sequence, screen.revision, 3 if release else 2 if reopen_trade else int(close),
                       len(screen.rows), screen.back)
    data += _string(screen.title, 24) + _string(screen.status, 32)
    used = set()
    for index, row in enumerate(screen.rows):
        if not isinstance(row, MenuRow) or type(row.action) is not int or row.action not in (0, index + 1):
            raise ValueError("menu actions must identify their own row")
        if row.action: used.add(row.action)
        data += struct.pack("<H", row.action) + _string(row.label, 26)
    if screen.back in used:
        raise ValueError("menu back action overlaps a row")
    _uint(screen.admission_action, 6)
    if screen.admission_action and (not allow_battle_admission or close or reopen_trade or release
            or screen.admission_action not in used):
        raise ValueError("battle admission requires an enabled row and verified capability")
    return data + bytes(SCREEN_SIZE - 4 - len(data)) + struct.pack("<HH", screen.admission_action, 0)


def unpack_screen(value, *, allow_trade_reopen=False, allow_battle_admission=False, allow_release=False):
    if type(value) is not bytes or len(value) != SCREEN_SIZE:
        raise ValueError("menu response must have exactly 240 bytes")
    ack, revision, flags, count, back = struct.unpack_from("<IIBBH", value)
    if (flags > (3 if allow_release else 2 if allow_trade_reopen else 1) or flags == 2 and not allow_trade_reopen
            or count > 6
            or any(value[68 + 28 * count:236]) or any(value[238:])):
        raise ValueError("menu response has invalid flags, count or padding")
    rows = tuple(MenuRow(struct.unpack_from("<H", value, 68 + i * 28)[0],
        _read_string(value[70 + i * 28:96 + i * 28])) for i in range(count))
    screen = MenuScreen(revision, _read_string(value[12:36]), _read_string(value[36:68]), rows, back,
                        struct.unpack_from("<H", value, 236)[0])
    if pack_screen(ack, screen, close=flags == 1, reopen_trade=flags == 2, release=flags == 3,
                   allow_battle_admission=allow_battle_admission) != value:
        raise ValueError("menu response is not canonical")
    return ack, screen, (flags if allow_trade_reopen or allow_release else bool(flags))


def validate_menu_manifest(manifest, rom_path=None):
    if not FIELDS.intersection(manifest):
        return False
    if not FIELDS <= set(manifest):
        raise ValueError("menu manifest is incomplete")
    if type(manifest["menu_abi_version"]) is not int or manifest["menu_abi_version"] not in (1, 2) or type(manifest["menu_mailbox_size"]) is not int or manifest["menu_mailbox_size"] != MAILBOX_SIZE:
        raise ValueError("unsupported menu mailbox")
    address, marker = manifest["menu_mailbox_address"], manifest["menu_abi_address"]
    if type(address) is not int or address % 4 or not 0x02000000 <= address <= 0x02040000 - MAILBOX_SIZE:
        raise ValueError("menu mailbox must be separately allocated in EWRAM")
    for key, size in (("mailbox_address", 128), ("save_mailbox_address", 512),
                      ("battle_mailbox_address", 512), ("save_window_address", 4096)):
        if key in manifest:
            start = manifest[key]
            if type(start) is not int or not (address + MAILBOX_SIZE <= start or start + size <= address):
                raise ValueError("menu mailbox overlaps another channel")
    size = Path(rom_path).stat().st_size if rom_path is not None else manifest.get("rom_size")
    if type(size) is not int or not 192 <= size <= 32 * 1024 * 1024:
        raise ValueError("menu marker requires a valid ROM size")
    if type(marker) is not int or marker % 4 or not 0x08000000 <= marker <= 0x08000000 + size - 4:
        raise ValueError("menu capability marker must be inside the verified ROM")
    if rom_path is not None:
        with Path(rom_path).open("rb") as source:
            source.seek(marker - 0x08000000)
            if source.read(4) != struct.pack("<I", manifest["menu_abi_version"]):
                raise ValueError("menu capability marker does not match the verified ROM")
    return True
