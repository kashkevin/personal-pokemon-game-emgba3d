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


class State(IntEnum):
    UNBOUND = 0
    BOUND = 1
    EXPORTING = 2
    IMPORTING = 3
    FINALIZING = 4
    RELOADING = 5
    COMMITTED = 6
    ERROR = 7


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
                   Opcode.QUERY_OWNERSHIP: 0, Opcode.GRANT_OWNERSHIP: 60}
        if self.status != Status.OK or self.length != lengths[self.opcode]:
            raise SaveMailboxError("save command status or data length is invalid")
        if self.opcode in (Opcode.READ, Opcode.WRITE) and (self.total_size != FLASH_SIZE
                or self.offset % SAVE_CHUNK_SIZE or self.offset >= FLASH_SIZE):
            raise SaveMailboxError("Flash chunks must be aligned and within canonical Flash")
        if self.opcode == Opcode.BEGIN_IMPORT:
            _, _, rotation, _ = struct.unpack("<IIII", self.data)
            if rotation >= 14 or self.total_size != FLASH_SIZE:
                raise SaveMailboxError("import source rotation or size is invalid")
        return self

    def validate_response(self) -> SaveControl:
        lengths = {Opcode.BIND: 0, Opcode.BEGIN_EXPORT: 40, Opcode.READ: 128,
                   Opcode.END: 4, Opcode.BEGIN_IMPORT: 8, Opcode.WRITE: 0,
                   Opcode.COMMIT: 0, Opcode.CANCEL: 0, Opcode.QUERY: 48,
                   Opcode.QUERY_OWNERSHIP: 80, Opcode.GRANT_OWNERSHIP: 80}
        if self.length != (lengths[self.opcode] if self.status == Status.OK else 0):
            raise SaveMailboxError("save response data length is invalid")
        if self.status == Status.OK and self.opcode == Opcode.READ and (self.total_size != FLASH_SIZE
                or self.offset % SAVE_CHUNK_SIZE or self.offset > FLASH_SIZE - SAVE_CHUNK_SIZE):
            raise SaveMailboxError("read response does not contain one aligned Flash chunk")
        return self


def command_packet(control: SaveControl) -> bytes:
    return b"C" + control.validate_command().pack()


def response_packet(control: SaveControl) -> bytes:
    return b"R" + control.validate_response().pack()


def parse_command_packet(payload: bytes) -> SaveControl:
    if not isinstance(payload, bytes) or payload[:1] != b"C":
        raise SaveMailboxError("expected a save command packet")
    return SaveControl.unpack(payload[1:]).validate_command()


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
