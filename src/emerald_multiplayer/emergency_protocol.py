"""Optional held emergency-export ABI; this grants no offline RPC authority."""
from dataclasses import dataclass
from pathlib import Path
import struct
from uuid import UUID

from .protocol import MAX_COUNTER
from .save_mailbox import FLASH_SIZE, Opcode, SaveControl, SaveMailboxError, State, Status

FIELDS = frozenset({"emergency_save_abi_version", "emergency_save_abi_address"})


def validate_emergency_manifest(manifest, rom_path=None):
    if not FIELDS.intersection(manifest):
        return False
    if not FIELDS.issubset(manifest):
        raise ValueError("emergency save capability is incomplete")
    for key, expected in (("emergency_save_abi_version", 1), ("ownership_abi_version", 1),
                          ("trade_abi_version", 1), ("save_abi_version", 1),
                          ("save_mailbox_size", 512), ("abi_version", 1), ("mailbox_size", 128)):
        if type(manifest.get(key)) is not int or manifest[key] != expected:
            raise ValueError("emergency save requires the matching ownership/trade/save build")
    if manifest.get("save_profile") != "rhh-1.17.1-bb1093-ownership-v1":
        raise ValueError("emergency save profile is incompatible")
    marker, size = manifest["emergency_save_abi_address"], manifest.get("rom_size")
    if (type(size) is not int or not 192 <= size <= 32 * 1024 * 1024
            or type(marker) is not int or marker % 4
            or not 0x08000000 <= marker <= 0x08000000 + size - 4):
        raise ValueError("emergency save marker is outside the verified ROM")
    if rom_path is not None:
        with Path(rom_path).open("rb") as source:
            source.seek(marker - 0x08000000)
            if source.read(4) != b"\x01\x00\x00\x00":
                raise ValueError("emergency save marker differs from the verified ROM")
    return True


def capability_packet():
    return b"Z" + struct.pack("<HHHH", 1, 19, 21, 10)


@dataclass(frozen=True)
class EmergencyHold:
    active: bool
    valid_flash: bool
    preserved: bool
    state: State
    operation_id: str | None
    session_epoch: int
    incarnation: int
    revision: int
    offset: int
    crc32: int
    failure: Status

    @classmethod
    def parse(cls, response: SaveControl):
        response.validate_response()
        if response.opcode != Opcode.QUERY_EMERGENCY or response.status != Status.OK:
            raise SaveMailboxError("expected a successful emergency observation")
        flags, state, request, epoch, incarnation, revision, offset, crc, failure = struct.unpack(
            "<II16sIIIIII", response.data)
        if state not in tuple(State) or failure not in tuple(Status):
            raise SaveMailboxError("unknown emergency state or failure")
        operation = UUID(bytes=request)
        if flags == 0:
            if any((operation.int, epoch, incarnation, revision, offset, crc, failure)):
                raise SaveMailboxError("inactive emergency observation contains held data")
            if state in (State.EMERGENCY_UNSAVED, State.EMERGENCY_PRESERVED):
                raise SaveMailboxError("emergency state lacks its active hold")
        else:
            if (not operation.int or not 1 <= epoch <= MAX_COUNTER or not incarnation
                    or not 1 <= revision <= MAX_COUNTER or offset > FLASH_SIZE or offset % 128):
                raise SaveMailboxError("active emergency observation lacks its bounded binding")
            if (str(operation), epoch, incarnation, revision, offset) != (
                    response.request_id, response.session_epoch, response.incarnation,
                    response.revision, response.offset):
                raise SaveMailboxError("emergency observation differs from its correlated response")
            if flags == 1:
                if state != State.EMERGENCY_UNSAVED or failure == Status.OK or offset or crc:
                    raise SaveMailboxError("unsaved emergency observation claims export bytes")
            elif flags == 3:
                if state != State.EXPORTING or failure != Status.OK:
                    raise SaveMailboxError("emergency read stream has an invalid state")
            elif flags == 7:
                if state != State.EMERGENCY_PRESERVED or failure != Status.OK or offset != FLASH_SIZE:
                    raise SaveMailboxError("preserved emergency observation lacks a complete read")
            else:
                raise SaveMailboxError("emergency observation flags are invalid")
        return cls(bool(flags & 1), bool(flags & 2), bool(flags & 4), State(state),
                   str(operation) if flags else None, epoch, incarnation, revision, offset, crc, Status(failure))
