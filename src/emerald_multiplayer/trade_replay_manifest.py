"""Exact ROM-declared entry point for isolated native trade replay."""
from __future__ import annotations

import struct

DESCRIPTOR = struct.Struct("<8I")
MAGIC = 0x57525445
INPUT_MAX = 35116
OUTPUT_MAX = 19452
HEAP_SIZE = 0x1C500
FIELDS = frozenset({"trade_replay_abi_version", "trade_replay_descriptor_address"})


def validate_trade_replay_manifest(manifest, rom_path=None):
    if not FIELDS.intersection(manifest):
        return False
    address = manifest.get("trade_replay_descriptor_address")
    if (not FIELDS.issubset(manifest)
            or type(manifest.get("trade_replay_abi_version")) is not int
            or manifest["trade_replay_abi_version"] != 1
            or any(type(manifest.get(key)) is not int or manifest[key] != 1 for key in
                   ("trade_effect_prepare_abi_version", "trade_effect_save_abi_version",
                    "trade_effect_choice_abi_version"))
            or type(address) is not int or address % 4
            or not 0x08000000 <= address <= 0x09FFFFE0):
        raise ValueError("native trade replay descriptor is incompatible or incomplete")
    if rom_path is not None:
        size = rom_path.stat().st_size
        if not 192 <= size <= 32 * 1024 * 1024 or address - 0x08000000 > size - DESCRIPTOR.size:
            raise ValueError("native trade replay descriptor is outside this ROM")
        with rom_path.open("rb") as source:
            source.seek(address - 0x08000000)
            magic, version, entry, heap, heap_size, input_max, output_max, reserved = DESCRIPTOR.unpack(source.read(DESCRIPTOR.size))
        if (magic != MAGIC or version != 1 or not entry & 1
                or not 0x08000000 <= (entry & ~1) <= 0x08000000 + size - 2
                or heap % 4 or heap_size != HEAP_SIZE
                or not 0x02000000 <= heap <= 0x02040000 - HEAP_SIZE
                or input_max != INPUT_MAX or output_max != OUTPUT_MAX or reserved):
            raise ValueError("native trade replay descriptor differs from its fixed copy-only ABI")
    return True
