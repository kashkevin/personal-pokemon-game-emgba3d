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
# Update 32 (PC games with menu_open_page_abi_version 1): the page an OPEN names in its action field. Page 2 (START >
# PLAYER > TOWER) exists only in games with the Battle Tower (tower_abi_version 1): a request naming it needs allow_tower.
OPEN_PAGES = {1: "soft_reset", 2: "tower"}
TOWER_PAGE = 2
FIELDS = frozenset({"menu_abi_version", "menu_abi_address", "menu_mailbox_address", "menu_mailbox_size"})
_REQUEST = struct.Struct("<IIHB5s")
# Battle Tower: Legends (docs/battle-tower-legends.md 8.2), only for a game with the Tower: a screen with flags 4 starts a
# solo Tower battle (count 0, admission 0, the TowerCommand at offset 68 and the rest of the rows area zero); flags 5 opens
# Hyper Training (count 0, rows area zero). Bytes 238-239 are the page's style and its argument (zero otherwise).
FLAG_TOWER_SOLO = 4
FLAG_HYPER_TRAINING = 5
TOWER_MAGIC = 0x31525754  # "TWR1"
TOWER_COMMAND_OFFSET = 68
TOWER_FLOORS = 100
# 0 none, 1 Tower home, 2 floor map (arg: the first floor shown), 3 floor or boss preview (arg: the floor), 4 shop,
# 5 Duo status, 6 records, 7 Hyper Training information, 8 prizes
TOWER_STYLES = range(9)
_COMMAND = struct.Struct("<IIIBB18s")


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

    def pack(self, *, allow_tower=False):
        """``allow_tower``: the game has the Battle Tower, so an OPEN may name its page (TOWER_PAGE)."""
        _uint(self.sequence, 0xFFFFFFFF, 1)
        _uint(self.screen, 0xFFFFFFFF)
        _uint(self.kind, 3, 1)
        _uint(self.action, 7)
        if self.kind == 2 and (not self.screen or not self.action):
            raise ValueError("menu selection needs a displayed action")
        if self.kind == 3 and self.action:
            raise ValueError("menu close cannot choose an action")
        if self.kind == 1 and self.action and (self.action not in OPEN_PAGES
                                               or self.action == TOWER_PAGE and allow_tower is not True):
            raise ValueError("menu open names an unknown page")
        if self.kind == 1 and self.screen:
            raise ValueError("menu open cannot claim a previous screen")
        return _REQUEST.pack(self.sequence, self.screen, self.action, self.kind, bytes(5))

    @classmethod
    def unpack(cls, value, *, allow_tower=False):
        if type(value) is not bytes or len(value) != REQUEST_SIZE:
            raise ValueError("menu request must have exactly 16 bytes")
        sequence, screen, action, kind, reserved = _REQUEST.unpack(value)
        if any(reserved):
            raise ValueError("menu request reserved bytes must be zero")
        result = cls(sequence, screen, action, kind)
        result.pack(allow_tower=allow_tower)
        return result


@dataclass(frozen=True)
class TowerCommand:
    """The solo Tower battle a flags-4 screen starts (32 bytes at screen offset 68): magic "TWR1", the host's ticket (low
    byte nonzero), the floor table's hash (the game refuses another table), the floor and mode 1 (solo), 18 zero bytes."""
    ticket: int
    table_hash: int
    floor: int
    mode: int = 1

    def pack(self):
        _uint(self.ticket, 0xFFFFFFFF, 1)
        if not self.ticket & 0xFF:
            raise ValueError("a Tower ticket's low byte is never zero")
        _uint(self.table_hash, 0xFFFFFFFF)
        _uint(self.floor, TOWER_FLOORS, 1)
        _uint(self.mode, 1, 1)
        return _COMMAND.pack(TOWER_MAGIC, self.ticket, self.table_hash, self.floor, self.mode, bytes(18))

    @classmethod
    def unpack(cls, value):
        if type(value) is not bytes or len(value) != _COMMAND.size:
            raise ValueError("a Tower command has exactly 32 bytes")
        magic, ticket, table_hash, floor, mode, reserved = _COMMAND.unpack(value)
        if magic != TOWER_MAGIC or any(reserved):
            raise ValueError("a Tower command needs its magic and zero reserved bytes")
        result = cls(ticket, table_hash, floor, mode)
        result.pack()
        return result


def pack_screen(request_sequence, screen, *, close=False, reopen_trade=False, allow_battle_admission=False,
                release=False, tower_command=None, hyper_training=False, allow_tower=False):
    """`release` (flags 3, PC games with menu_release_abi_version 1): the reply to an Enter battle choice the
    companion refused before any ADMIT; the game's latched window takes it and shows it with its rows usable.

    Battle Tower: Legends, only with ``allow_tower`` (the game's tower capability): ``tower_command`` (flags 4) starts a
    solo Tower battle, ``hyper_training`` (flags 5) opens the Hyper Training screens; both answer a choice with no rows.
    A screen's ``style`` and ``style_arg`` (bytes 238-239) are zero without it."""
    _uint(request_sequence, 0xFFFFFFFF, 1)
    tower = tower_command is not None or hyper_training is True
    if (not isinstance(screen, MenuScreen) or type(close) is not bool or type(release) is not bool
            or type(reopen_trade) is not bool or type(allow_battle_admission) is not bool
            or type(hyper_training) is not bool or type(allow_tower) is not bool
            or (tower_command is not None and not isinstance(tower_command, TowerCommand))
            or close + reopen_trade + release + (tower_command is not None) + hyper_training > 1):
        raise ValueError("menu response needs a typed screen and close flag")
    _uint(screen.revision, 0xFFFFFFFF, 1)
    if type(screen.back) is not int or screen.back not in (0, 7):
        raise ValueError("menu back action must be absent or seven")
    if type(screen.rows) is not tuple or len(screen.rows) > 6:
        raise ValueError("menu screen permits at most six rows")
    style, argument = screen.style, screen.style_arg
    if (type(style) is not int or style not in TOWER_STYLES or type(argument) is not int
            or not 0 <= argument <= TOWER_FLOORS or (style == 0 and argument)):
        raise ValueError("menu style is a Tower page style 0-8 and an argument 0-100")
    if (tower or style) and not allow_tower:
        raise ValueError("Tower screens and styles need the game's Tower capability")
    if tower and (screen.rows or screen.admission_action or style):
        raise ValueError("a Tower command or Hyper Training screen has no rows and no style")
    flags = (FLAG_TOWER_SOLO if tower_command is not None else FLAG_HYPER_TRAINING if hyper_training
             else 3 if release else 2 if reopen_trade else int(close))
    data = struct.pack("<IIBBH", request_sequence, screen.revision, flags, len(screen.rows), screen.back)
    data += _string(screen.title, 24) + _string(screen.status, 32)
    used = set()
    for index, row in enumerate(screen.rows):
        if not isinstance(row, MenuRow) or type(row.action) is not int or row.action not in (0, index + 1):
            raise ValueError("menu actions must identify their own row")
        if row.action: used.add(row.action)
        data += struct.pack("<H", row.action) + _string(row.label, 26)
    if screen.back in used:
        raise ValueError("menu back action overlaps a row")
    if tower_command is not None:
        data += tower_command.pack()
    _uint(screen.admission_action, 6)
    if screen.admission_action and (not allow_battle_admission or close or reopen_trade or release
            or screen.admission_action not in used):
        raise ValueError("battle admission requires an enabled row and verified capability")
    return data + bytes(SCREEN_SIZE - 4 - len(data)) + struct.pack("<HBB", screen.admission_action, style, argument)


def unpack_screen(value, *, allow_trade_reopen=False, allow_battle_admission=False, allow_release=False,
                  allow_tower=False):
    """(ack, screen, close) of a canonical screen; the close becomes the flags (2 trade reopen, 3 release) for a reader
    that expects those. A reader expecting Battle Tower screens (``allow_tower``) gets (ack, screen, flags, command): flags
    4 with its TowerCommand, 5 (Hyper Training) or any other, command None."""
    if type(value) is not bytes or len(value) != SCREEN_SIZE:
        raise ValueError("menu response must have exactly 240 bytes")
    ack, revision, flags, count, back = struct.unpack_from("<IIBBH", value)
    allowed = ({0, 1} | ({2} if allow_trade_reopen else set()) | ({3} if allow_release else set())
               | ({FLAG_TOWER_SOLO, FLAG_HYPER_TRAINING} if allow_tower else set()))
    rows_end = TOWER_COMMAND_OFFSET + _COMMAND.size if flags == FLAG_TOWER_SOLO else 68 + 28 * count
    if (flags not in allowed or count > 6 or flags in (FLAG_TOWER_SOLO, FLAG_HYPER_TRAINING) and count
            or any(value[rows_end:236]) or (any(value[238:]) and not allow_tower)):
        raise ValueError("menu response has invalid flags, count or padding")
    rows = tuple(MenuRow(struct.unpack_from("<H", value, 68 + i * 28)[0],
        _read_string(value[70 + i * 28:96 + i * 28])) for i in range(count))
    screen = MenuScreen(revision, _read_string(value[12:36]), _read_string(value[36:68]), rows, back,
                        struct.unpack_from("<H", value, 236)[0], value[238], value[239])
    command = TowerCommand.unpack(value[68:68 + _COMMAND.size]) if flags == FLAG_TOWER_SOLO else None
    if pack_screen(ack, screen, close=flags == 1, reopen_trade=flags == 2, release=flags == 3, tower_command=command,
                   hyper_training=flags == FLAG_HYPER_TRAINING, allow_battle_admission=allow_battle_admission,
                   allow_tower=allow_tower) != value:
        raise ValueError("menu response is not canonical")
    if allow_tower:
        return ack, screen, flags, command
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
