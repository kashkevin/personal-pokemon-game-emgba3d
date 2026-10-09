"""Optional held record preparation; this is never an effect commit capability."""
from dataclasses import dataclass
from pathlib import Path
import struct
from uuid import UUID

FIELDS = {"trade_effect_prepare_abi_version", "trade_effect_prepare_abi_address"}
OPS = frozenset((23, 24, 25, 26, 27, 28, 29))
SAVE_FIELDS = {"trade_effect_save_abi_version", "trade_effect_save_abi_address"}
CHOICE_FIELDS = {"trade_effect_choice_abi_version", "trade_effect_choice_abi_address"}


def validate_effect_choice_manifest(manifest, rom_path=None):
    if not CHOICE_FIELDS.intersection(manifest):
        return False
    if (not CHOICE_FIELDS.issubset(manifest) or not validate_effect_prepare_manifest(manifest, rom_path)
            or type(manifest["trade_effect_choice_abi_version"]) is not int
            or manifest["trade_effect_choice_abi_version"] != 1):
        raise ValueError("move presentation requires matching held record preparation")
    marker = manifest["trade_effect_choice_abi_address"]
    if (type(marker) is not int or marker % 4
            or not 0x08000000 <= marker <= 0x08000000 + manifest["rom_size"] - 4):
        raise ValueError("native move presentation marker is outside verified ROM")
    if rom_path is not None:
        with Path(rom_path).open("rb") as stream:
            stream.seek(marker - 0x08000000)
            if stream.read(4) != b"\1\0\0\0":
                raise ValueError("native move presentation marker differs from verified ROM")
    return True


def validate_effect_save_manifest(manifest, rom_path=None):
    if not SAVE_FIELDS.intersection(manifest):
        return False
    from .save_window import validate_window_manifest
    if (not SAVE_FIELDS.issubset(manifest) or not validate_effect_prepare_manifest(manifest, rom_path)
            or not validate_window_manifest(manifest, rom_path)
            or type(manifest["trade_effect_save_abi_version"]) is not int
            or manifest["trade_effect_save_abi_version"] != 1):
        raise ValueError("full native candidate needs matching record/window capabilities")
    marker = manifest["trade_effect_save_abi_address"]
    if (type(marker) is not int or marker % 4
            or not 0x08000000 <= marker <= 0x08000000 + manifest["rom_size"] - 4):
        raise ValueError("full candidate marker is outside verified ROM")
    if rom_path is not None:
        with Path(rom_path).open("rb") as stream:
            stream.seek(marker - 0x08000000)
            if stream.read(4) != b"\1\0\0\0":
                raise ValueError("full candidate marker differs from verified ROM")
    return True


def validate_effect_prepare_manifest(manifest, rom_path=None):
    if not FIELDS.intersection(manifest):
        return False
    if not FIELDS.issubset(manifest):
        raise ValueError("incomplete native trade record preparation capability")
    for key, expected in (("trade_effect_prepare_abi_version", 1), ("trade_abi_version", 1),
                          ("ownership_abi_version", 1), ("save_abi_version", 1),
                          ("save_mailbox_size", 512), ("menu_abi_version", 2)):
        if type(manifest.get(key)) is not int or manifest[key] != expected:
            raise ValueError("record preparation requires the matching held trade/menu/ownership build")
    if manifest.get("save_profile") != "rhh-1.17.1-bb1093-ownership-v1":
        raise ValueError("record preparation profile differs")
    marker, size = manifest["trade_effect_prepare_abi_address"], manifest.get("rom_size")
    if (type(size) is not int or not 192 <= size <= 32*1024*1024 or type(marker) is not int
            or marker % 4 or not 0x08000000 <= marker <= 0x08000000 + size - 4):
        raise ValueError("record preparation marker is outside verified ROM")
    if rom_path is not None:
        with Path(rom_path).open("rb") as stream:
            stream.seek(marker - 0x08000000)
            if stream.read(4) != b"\1\0\0\0":
                raise ValueError("record preparation marker differs from verified ROM")
    return True


def capability_packet():
    return b"K" + struct.pack("<HH", 1, 192)


def save_capability_packet():
    return b"L" + struct.pack("<HH", 1, 4096)


def choice_capability_packet():
    return b"O" + struct.pack("<HH", 1, 84)


def context_bytes(generation, preparation_id):
    ident = UUID(generation)
    digest = bytes.fromhex(preparation_id)
    if str(ident) != generation or not ident.int or len(digest) != 32 or not any(digest):
        raise ValueError("record preparation lacks exact generation/pair identity")
    return ident.bytes + digest


def validate_command(opcode, data):
    lengths = {23: 192, 24: 56, 25: 48, 26: 48, 27: 88, 28: 48, 29: 48}
    if opcode not in lengths or len(data) != lengths[opcode] or not any(data[:16]) or not any(data[16:48]):
        raise ValueError("invalid native record preparation context")
    if opcode == 23:
        slot, friendship = struct.unpack_from("<II", data, 80)
        if not any(data[48:80]) or slot > 5 or friendship > 255:
            raise ValueError("invalid native record preparation input")
    if opcode == 24:
        index, move, slot, reserved = struct.unpack_from("<IHBB", data, 48)
        if index >= 16 or not 1 <= move <= 621 or slot > 4 or reserved:
            raise ValueError("invalid explicit evolution move decision")
    if opcode == 27 and (not any(data[48:80]) or data[87]):
        raise ValueError("full candidate requires its exact source context and zero padding")


@dataclass(frozen=True)
class PreparedRecord:
    received_serial: int
    sent_serial: int
    received_species: int
    evolved_species: int
    item_before: int
    item_after: int
    pending_move: int
    learnset_cursor: int
    state: int
    friendship: int
    candidate: bytes
    choices: tuple[tuple[int, int], ...]

    @classmethod
    def parse(cls, data):
        if type(data) is not bytes or len(data) != 192:
            raise ValueError("native prepared record must contain 192 bytes")
        version, received, sent, species, evolved, before, after, move, cursor, state, friendship, count, reserved = struct.unpack_from("<III6H4B", data)
        if (version != 1 or not 1 <= received <= 0xFFFFF or not 1 <= sent <= 0xFFFFF or received == sent
                or not 1 <= species <= 721 or not 0 <= evolved <= 721 or before > 1023 or after > 1023
                or cursor > 256 or state not in (1, 2) or count > 16 or reserved
                or (state == 1 and not 1 <= move <= 621) or (state == 2 and move != 0)):
            raise ValueError("invalid native prepared record state")
        choices = []
        for index in range(16):
            decision, slot, zero = struct.unpack_from("<HBB", data, 128 + index*4)
            if index >= count:
                if decision or slot or zero:
                    raise ValueError("prepared record has trailing decisions")
            elif not 1 <= decision <= 621 or slot > 4 or zero:
                raise ValueError("prepared record has an invalid move decision")
            else:
                choices.append((decision, slot))
        return cls(received, sent, species, evolved, before, after, move, cursor, state,
                   friendship, data[28:128], tuple(choices))
