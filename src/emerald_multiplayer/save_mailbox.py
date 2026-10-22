"""Pure codecs for the separately allocated live-save mailbox.

Presence ABI 1 remains unchanged. These functions choose no memory addresses.
The live payload is canonical 128 KiB Flash; emulator RTC footer bytes never
pass through this mailbox. CRC32 detects transport damage, not ownership.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import struct
import uuid
import zlib

from .protocol import MAX_COUNTER

SAVE_MAILBOX_MAGIC = 0x31534D45
SAVE_ABI_VERSION = 1
SAVE_MAILBOX_SIZE = 512
SAVE_SLOT_SIZE = 240
SAVE_DATA_SIZE = 192
SAVE_CHUNK_SIZE = 128
FLASH_SIZE = 131072
COMMAND_GEN_OFFSET = 24
COMMAND_OFFSET = 28
RESPONSE_GEN_OFFSET = 268
RESPONSE_OFFSET = 272
_UINT32 = 0xFFFFFFFF
_CONTROL = struct.Struct("<II16sIIIIBBHI192s")


class SaveMailboxError(ValueError):
    pass


class Opcode(IntEnum):
    BIND = 1
    BEGIN_EXPORT = 2
    READ = 3
    END = 4
    BEGIN_IMPORT = 5
    WRITE = 6
    COMMIT = 7
    CANCEL = 8
    QUERY = 9
    QUERY_OWNERSHIP = 10
    GRANT_OWNERSHIP = 11
    BEGIN_TRADE_EXPORT = 12
    KEEP_TRADE = 13
    ABORT_TRADE = 14
    RELEASE_TRADE = 15
    REBIND_TRADE = 16
    QUERY_TRADE = 17
    READ_WINDOW = 18
    BEGIN_EMERGENCY_EXPORT = 19
    PRESERVE_EMERGENCY = 20
    QUERY_EMERGENCY = 21
    PROMOTE_EMERGENCY_EXPORT = 22
    BEGIN_EFFECT_RECORD = 23
    CHOOSE_EFFECT_MOVE = 24
    QUERY_EFFECT_RECORD = 25
    DISCARD_EFFECT_RECORD = 26
    BEGIN_EFFECT_SAVE = 27
    READ_EFFECT_WINDOW = 28
    QUERY_EFFECT_CHOICE = 29
    WRITE_WINDOW = 30  # PC game with the import window: one 4 KiB sector, sent as 'i' with its bytes
    QUERY_PARTY = 31   # PC game (save_party_query_abi_version 1): what a battle preparation checks (KNOWN_ISSUES MS-60)


class Status(IntEnum):
    OK = 0
    BUSY = 1
    UNSAFE = 2
    MALFORMED = 3
    SESSION = 4
    ORDER = 5
    CRC = 6
    FLASH = 7
    SPECIAL = 8
    OWNERSHIP = 9
    VALIDATION = 10
    CANCELED = 11
    TIMEOUT = 12
    INTERNAL = 13
    BATTLE_ADMISSION = 14


class State(IntEnum):
    UNBOUND = 0
    BOUND = 1
    EXPORTING = 2
    IMPORTING = 3
    FINALIZING = 4
    RELOADING = 5
    COMMITTED = 6
    ERROR = 7
    TRADE_HELD = 8
    EMERGENCY_UNSAVED = 9
    EMERGENCY_PRESERVED = 10


def _integer(value: int, low: int, high: int, name: str) -> None:
    if type(value) is not int or not low <= value <= high:
        raise SaveMailboxError(f"{name} is outside its integer bounds")


@dataclass(frozen=True)
class SaveControl:
    incarnation: int
    session_epoch: int
    request_id: str
    sequence: int
    offset: int
    total_size: int
    revision: int
    opcode: int
    status: int = Status.OK
    data: bytes = b""

    def __post_init__(self) -> None:
        _integer(self.incarnation, 1, _UINT32, "bridge incarnation")
        _integer(self.session_epoch, 1, MAX_COUNTER, "session epoch")
        _integer(self.sequence, 1, _UINT32, "command sequence")
        _integer(self.offset, 0, FLASH_SIZE, "offset")
        _integer(self.revision, 0, MAX_COUNTER, "revision")
        if type(self.total_size) is not int or self.total_size not in (0, FLASH_SIZE):
            raise SaveMailboxError("live save size must be zero or canonical Flash")
        try:
            valid_uuid = isinstance(self.request_id, str) and str(uuid.UUID(self.request_id)) == self.request_id and uuid.UUID(self.request_id).int != 0
        except (ValueError, TypeError, AttributeError):
            valid_uuid = False
        if not valid_uuid:
            raise SaveMailboxError("request ID must be a nonzero canonical UUID")
        if isinstance(self.opcode, bool) or not isinstance(self.opcode, (int, Opcode)) or self.opcode not in tuple(Opcode):
            raise SaveMailboxError("unknown save opcode")
        if isinstance(self.status, bool) or not isinstance(self.status, (int, Status)) or self.status not in tuple(Status):
            raise SaveMailboxError("unknown save status")
        if not isinstance(self.data, bytes) or len(self.data) > SAVE_DATA_SIZE:
            raise SaveMailboxError("save control data is outside its bounds")

    @property
    def length(self) -> int:
        return len(self.data)

    def pack(self) -> bytes:
        return _CONTROL.pack(self.incarnation, self.session_epoch, uuid.UUID(self.request_id).bytes,
                             self.sequence, self.offset, self.total_size, self.revision,
                             self.opcode, self.status, len(self.data), zlib.crc32(self.data),
                             self.data + bytes(SAVE_DATA_SIZE - len(self.data)))

    @classmethod
    def unpack(cls, payload: bytes) -> SaveControl:
        if not isinstance(payload, bytes) or len(payload) != SAVE_SLOT_SIZE:
            raise SaveMailboxError("save control must contain exactly 240 bytes")
        incarnation, epoch, request, sequence, offset, size, revision, opcode, status, length, crc, data = _CONTROL.unpack(payload)
        if length > SAVE_DATA_SIZE or any(data[length:]) or zlib.crc32(data[:length]) != crc:
            raise SaveMailboxError("save control length, padding, or CRC32 is invalid")
        return cls(incarnation, epoch, str(uuid.UUID(bytes=request)), sequence, offset, size,
                   revision, opcode, status, data[:length])

    def validate_command(self) -> SaveControl:
        lengths = {Opcode.BIND: 0, Opcode.BEGIN_EXPORT: 0, Opcode.READ: 0,
                   Opcode.END: 0, Opcode.BEGIN_IMPORT: 16, Opcode.WRITE: 128,
                   Opcode.COMMIT: 0, Opcode.CANCEL: 0, Opcode.QUERY: 0,
                   Opcode.QUERY_OWNERSHIP: 0, Opcode.GRANT_OWNERSHIP: 60,
                   Opcode.BEGIN_TRADE_EXPORT: 0, Opcode.KEEP_TRADE: 0,
                   Opcode.ABORT_TRADE: 0, Opcode.RELEASE_TRADE: 0,
                   Opcode.REBIND_TRADE: 0, Opcode.QUERY_TRADE: 0, Opcode.READ_WINDOW: 0,
                   Opcode.BEGIN_EMERGENCY_EXPORT: 0, Opcode.PRESERVE_EMERGENCY: 0,
                   Opcode.QUERY_EMERGENCY: 0, Opcode.PROMOTE_EMERGENCY_EXPORT: 0,
                   Opcode.BEGIN_EFFECT_RECORD: 192, Opcode.CHOOSE_EFFECT_MOVE: 56,
                   Opcode.QUERY_EFFECT_RECORD: 48, Opcode.DISCARD_EFFECT_RECORD: 48,
                   Opcode.BEGIN_EFFECT_SAVE: 88, Opcode.READ_EFFECT_WINDOW: 48,
                   Opcode.QUERY_EFFECT_CHOICE: 48, Opcode.WRITE_WINDOW: 4, Opcode.QUERY_PARTY: 0}
        if self.status != Status.OK or self.length != lengths[self.opcode]:
            raise SaveMailboxError("save command status or data length is invalid")
        if self.opcode == Opcode.QUERY_PARTY and (self.total_size != FLASH_SIZE or self.offset or self.revision):
            raise SaveMailboxError("a party query names canonical Flash and nothing else")
        if self.opcode in (Opcode.READ, Opcode.WRITE) and (self.total_size != FLASH_SIZE
                or self.offset % SAVE_CHUNK_SIZE or self.offset >= FLASH_SIZE):
            raise SaveMailboxError("Flash chunks must be aligned and within canonical Flash")
        if self.opcode == Opcode.BEGIN_IMPORT:
            _, _, rotation, _ = struct.unpack("<IIII", self.data)
            if rotation >= 14 or self.total_size != FLASH_SIZE:
                raise SaveMailboxError("import source rotation or size is invalid")
        if Opcode.BEGIN_TRADE_EXPORT <= self.opcode <= Opcode.QUERY_TRADE and (self.total_size != FLASH_SIZE or self.offset != 0):
            raise SaveMailboxError("trade controls require canonical Flash size and zero request offset")
        if self.opcode == Opcode.BEGIN_TRADE_EXPORT and not 1 <= self.revision < MAX_COUNTER:
            raise SaveMailboxError("trade preparation must leave capacity for the paired revision")
        if self.opcode == Opcode.REBIND_TRADE and self.sequence != 1:
            raise SaveMailboxError("trade rebind must restart the command sequence")
        if self.opcode == Opcode.READ_WINDOW and (self.total_size != FLASH_SIZE or self.offset % 4096
                                                   or self.offset > FLASH_SIZE - 4096):
            raise SaveMailboxError("Flash window must be aligned and within canonical Flash")
        if self.opcode == Opcode.WRITE_WINDOW and (self.total_size != FLASH_SIZE or self.offset % 4096
                                                    or self.offset > FLASH_SIZE - 4096):
            raise SaveMailboxError("import window must be one aligned sector within canonical Flash")
        if Opcode.BEGIN_EMERGENCY_EXPORT <= self.opcode <= Opcode.PROMOTE_EMERGENCY_EXPORT:
            expected_offset = FLASH_SIZE if self.opcode == Opcode.PRESERVE_EMERGENCY else 0
            if self.total_size != FLASH_SIZE or self.offset != expected_offset:
                raise SaveMailboxError("emergency control has an invalid size or offset")
            if self.opcode != Opcode.QUERY_EMERGENCY and self.revision == 0:
                raise SaveMailboxError("emergency export needs a positive target revision")
        if Opcode.BEGIN_EFFECT_RECORD <= self.opcode <= Opcode.QUERY_EFFECT_CHOICE:
            from .trade_effect_mailbox import validate_command
            window = self.opcode == Opcode.READ_EFFECT_WINDOW
            if (self.total_size != FLASH_SIZE or not 1 <= self.revision < MAX_COUNTER
                    or (window and (self.offset % 4096 or self.offset > FLASH_SIZE - 4096))
                    or (not window and self.offset)):
                raise SaveMailboxError("record preparation needs an exact frozen trade revision")
            validate_command(self.opcode, self.data)
        return self

    def validate_response(self) -> SaveControl:
        lengths = {Opcode.BIND: 0, Opcode.BEGIN_EXPORT: 40, Opcode.READ: 128,
                   Opcode.END: 4, Opcode.BEGIN_IMPORT: 8, Opcode.WRITE: 0,
                   Opcode.COMMIT: 0, Opcode.CANCEL: 0, Opcode.QUERY: 48,
                   Opcode.QUERY_OWNERSHIP: 80, Opcode.GRANT_OWNERSHIP: 80,
                   Opcode.BEGIN_TRADE_EXPORT: 40, Opcode.KEEP_TRADE: 48,
                   Opcode.ABORT_TRADE: 0, Opcode.RELEASE_TRADE: 4,
                   Opcode.REBIND_TRADE: 48, Opcode.QUERY_TRADE: 48, Opcode.READ_WINDOW: 4,
                   Opcode.BEGIN_EMERGENCY_EXPORT: 40, Opcode.PRESERVE_EMERGENCY: 4,
                   Opcode.QUERY_EMERGENCY: 48, Opcode.PROMOTE_EMERGENCY_EXPORT: 40,
                   Opcode.BEGIN_EFFECT_RECORD: 192, Opcode.CHOOSE_EFFECT_MOVE: 192,
                   Opcode.QUERY_EFFECT_RECORD: 192, Opcode.DISCARD_EFFECT_RECORD: 0,
                   Opcode.BEGIN_EFFECT_SAVE: 8, Opcode.READ_EFFECT_WINDOW: 4,
                   Opcode.QUERY_EFFECT_CHOICE: 84, Opcode.WRITE_WINDOW: 0, Opcode.QUERY_PARTY: 20}
        if self.length != (lengths[self.opcode] if self.status == Status.OK else 0):
            raise SaveMailboxError("save response data length is invalid")
        if self.status == Status.OK and Opcode.BEGIN_EFFECT_RECORD <= self.opcode <= Opcode.QUERY_EFFECT_CHOICE:
            window = self.opcode == Opcode.READ_EFFECT_WINDOW
            if (self.total_size != FLASH_SIZE or (not window and self.offset)
                    or (window and (self.offset % 4096 or self.offset > FLASH_SIZE - 4096))):
                raise SaveMailboxError("prepared record response escaped the held context")
            if self.opcode in (Opcode.BEGIN_EFFECT_RECORD, Opcode.CHOOSE_EFFECT_MOVE, Opcode.QUERY_EFFECT_RECORD):
                from .trade_effect_mailbox import PreparedRecord
                PreparedRecord.parse(self.data)
            if self.opcode == Opcode.QUERY_EFFECT_CHOICE:
                from .trade_effect_choice import NativeChoiceView
                NativeChoiceView.parse(self.data)
        if self.status == Status.OK and self.opcode == Opcode.READ and (self.total_size != FLASH_SIZE
                or self.offset % SAVE_CHUNK_SIZE or self.offset > FLASH_SIZE - SAVE_CHUNK_SIZE):
            raise SaveMailboxError("read response does not contain one aligned Flash chunk")
        if self.status == Status.OK and self.opcode == Opcode.READ_WINDOW and (self.total_size != FLASH_SIZE
                or self.offset % 4096 or self.offset > FLASH_SIZE - 4096):
            raise SaveMailboxError("read window response is outside canonical Flash")
        if self.status == Status.OK and self.opcode == Opcode.WRITE_WINDOW and (self.total_size != FLASH_SIZE
                or self.offset % 4096 or not 4096 <= self.offset <= FLASH_SIZE):
            raise SaveMailboxError("import window response is not past one aligned sector")
        return self


def command_packet(control: SaveControl) -> bytes:
    if control.opcode == Opcode.WRITE_WINDOW:
        raise SaveMailboxError("an import window travels as 'i' with its sector")
    return b"C" + control.validate_command().pack()


IMPORT_WINDOW_SIZE = 4096


def import_window_packet(control: SaveControl, sector: bytes) -> bytes:
    """'i': WRITE_WINDOW and the sector it names by CRC (the PC game's bridge writes the sector, then the command)."""
    control.validate_command()
    if (control.opcode != Opcode.WRITE_WINDOW or not isinstance(sector, bytes) or len(sector) != IMPORT_WINDOW_SIZE
            or struct.unpack("<I", control.data)[0] != zlib.crc32(sector)):
        raise SaveMailboxError("import window needs WRITE_WINDOW and the exact sector it names")
    return b"i" + control.pack() + sector


def parse_import_window_packet(payload: bytes) -> tuple[SaveControl, bytes]:
    if not isinstance(payload, bytes) or payload[:1] != b"i" or len(payload) != 1 + SAVE_SLOT_SIZE + IMPORT_WINDOW_SIZE:
        raise SaveMailboxError("expected an import window packet")
    control = SaveControl.unpack(payload[1:1 + SAVE_SLOT_SIZE]).validate_command()
    sector = payload[1 + SAVE_SLOT_SIZE:]
    import_window_packet(control, sector)
    return control, sector


def response_packet(control: SaveControl) -> bytes:
    return b"R" + control.validate_response().pack()


def parse_command_packet(payload: bytes) -> SaveControl:
    if not isinstance(payload, bytes) or payload[:1] != b"C":
        raise SaveMailboxError("expected a save command packet")
    control = SaveControl.unpack(payload[1:]).validate_command()
    if control.opcode == Opcode.WRITE_WINDOW:
        raise SaveMailboxError("an import window travels as 'i' with its sector")
    return control


def parse_response_packet(payload: bytes) -> SaveControl:
    if not isinstance(payload, bytes) or payload[:1] != b"R":
        raise SaveMailboxError("expected a save response packet")
    return SaveControl.unpack(payload[1:]).validate_response()


def capability_packet() -> bytes:
    return b"V" + struct.pack("<HHHH", SAVE_ABI_VERSION, SAVE_MAILBOX_SIZE, SAVE_SLOT_SIZE, SAVE_DATA_SIZE)


def validate_capability_packet(payload: bytes) -> None:
    if payload != capability_packet():
        raise SaveMailboxError("live save capability is incompatible")


@dataclass(frozen=True)
class SaveMailbox:
    frame: int
    state: State
    command_generation: int
    response_generation: int
    command: SaveControl | None
    response: SaveControl | None


@dataclass(frozen=True)
class TradeHold:
    """Read-only recovery observation; expiry never authorizes an abort."""
    active: bool
    expired: bool
    import_started: bool
    phase: State
    transaction_id: str | None
    session_epoch: int
    incarnation: int
    revision: int
    next_offset: int
    crc32: int
    remaining_frames: int

    @classmethod
    def parse(cls, response: SaveControl) -> TradeHold:
        response.validate_response()
        if response.opcode != Opcode.QUERY_TRADE or response.status != Status.OK:
            raise SaveMailboxError("expected a successful trade recovery query")
        flags, phase, raw_id, epoch, incarnation, revision, offset, crc, remaining = struct.unpack(
            "<II16sIIIIII", response.data)
        if flags & ~7 or phase not in range(State.TRADE_HELD + 1) or epoch > MAX_COUNTER or revision > MAX_COUNTER:
            raise SaveMailboxError("invalid trade recovery state")
        if offset > FLASH_SIZE or offset % SAVE_CHUNK_SIZE:
            raise SaveMailboxError("invalid trade recovery stream position")
        transaction = uuid.UUID(bytes=raw_id)
        if flags & 1:
            if not transaction.int or not epoch or not incarnation or not revision or phase in (State.UNBOUND, State.BOUND):
                raise SaveMailboxError("active trade recovery lacks its binding")
        elif flags or transaction.int or remaining:
            raise SaveMailboxError("inactive trade recovery contains active hold fields")
        return cls(bool(flags & 1), bool(flags & 2), bool(flags & 4), State(phase),
                   str(transaction) if flags & 1 else None, epoch, incarnation,
                   revision, offset, crc, remaining)


def inspect_save_mailbox(payload: bytes) -> SaveMailbox:
    if not isinstance(payload, bytes) or len(payload) != SAVE_MAILBOX_SIZE:
        raise SaveMailboxError("save mailbox must contain exactly 512 bytes")
    magic, abi, size, frame, state, reserved_a, reserved_b = struct.unpack("<IHHIIII", payload[:24])
    if (magic, abi, size) != (SAVE_MAILBOX_MAGIC, SAVE_ABI_VERSION, SAVE_MAILBOX_SIZE) or reserved_a or reserved_b or state not in tuple(State):
        raise SaveMailboxError("save mailbox header is incompatible")
    command_gen = struct.unpack_from("<I", payload, COMMAND_GEN_OFFSET)[0]
    response_gen = struct.unpack_from("<I", payload, RESPONSE_GEN_OFFSET)[0]
    if command_gen & 1 or response_gen & 1:
        raise SaveMailboxError("save mailbox copy was made during an update")
    command_bytes = payload[COMMAND_OFFSET:RESPONSE_GEN_OFFSET]
    response_bytes = payload[RESPONSE_OFFSET:]
    return SaveMailbox(frame, State(state), command_gen, response_gen,
                       SaveControl.unpack(command_bytes).validate_command() if any(command_bytes) else None,
                       SaveControl.unpack(response_bytes).validate_response() if any(response_bytes) else None)
