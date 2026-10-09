"""Optional, read-only ROM sector window for a held Flash export."""
from pathlib import Path
import struct
import zlib

from .save_mailbox import Opcode, SaveControl, Status, SaveMailboxError

WINDOW_SIZE = 4096
WINDOW_FRAME_SIZE = 1 + 240 + WINDOW_SIZE
FIELDS = frozenset({"save_window_abi_version", "save_window_abi_address",
                    "save_window_address", "save_window_size"})


def validate_window_manifest(manifest, rom_path=None):
    if not FIELDS.intersection(manifest):
        return False
    if not FIELDS.issubset(manifest):
        raise ValueError("save window capability is incomplete")
    for key, expected in (("save_window_abi_version", 1), ("save_window_size", WINDOW_SIZE),
                          ("trade_abi_version", 1), ("ownership_abi_version", 1),
                          ("save_abi_version", 1), ("save_mailbox_size", 512),
                          ("abi_version", 1), ("mailbox_size", 128)):
        if type(manifest.get(key)) is not int or manifest[key] != expected:
            raise ValueError("save window requires a matching ownership/trade/save build")
    if manifest.get("save_profile") != "rhh-1.17.1-bb1093-ownership-v1":
        raise ValueError("save window profile is incompatible")
    marker, size = manifest["save_window_abi_address"], manifest.get("rom_size")
    if (type(size) is not int or not 192 <= size <= 32 * 1024 * 1024
            or type(marker) is not int or marker % 4 or not 0x08000000 <= marker <= 0x08000000 + size - 4):
        raise ValueError("save window marker is outside the verified ROM")
    regions = []
    names = [("mailbox_address", 128), ("save_mailbox_address", 512), ("save_window_address", WINDOW_SIZE)]
    if "battle_mailbox_address" in manifest:
        names.append(("battle_mailbox_address", 512))
    for key, length in names:
        address = manifest.get(key)
        if type(address) is not int or address % 4 or not 0x02000000 <= address <= 0x02040000 - length:
            raise ValueError("save window regions require aligned EWRAM allocations")
        if any(address < end and start < address + length for start, end in regions):
            raise ValueError("save window overlaps another mailbox")
        regions.append((address, address + length))
    if rom_path is not None:
        with Path(rom_path).open("rb") as stream:
            stream.seek(marker - 0x08000000)
            if stream.read(4) != b"\x01\x00\x00\x00":
                raise ValueError("save window marker differs from the verified ROM")
    return True


def capability_packet():
    return b"X" + struct.pack("<HH", 1, WINDOW_SIZE)


def parse_window_packet(packet, *, allow_effect_save=False):
    if not isinstance(packet, bytes) or len(packet) != WINDOW_FRAME_SIZE or packet[:1] != b"F":
        raise SaveMailboxError("expected one complete bounded Flash window")
    control = SaveControl.unpack(packet[1:241]).validate_response()
    data = packet[241:]
    allowed = {Opcode.READ_WINDOW, Opcode.READ_EFFECT_WINDOW} if allow_effect_save else {Opcode.READ_WINDOW}
    if (control.opcode not in allowed or control.status != Status.OK
            or struct.unpack("<I", control.data)[0] != zlib.crc32(data)):
        raise SaveMailboxError("Flash window does not match its ROM acknowledgement")
    return control, data
