"""Optional, ROM-pinned running presentation without changing save layouts.

Mailbox ABI1 retains its 20-byte poses and reserved zero byte. The additional
mode is accepted only when this separate ROM capability has been verified.
Older builds keep the exact original 0..4 codec and safe walk fallback.
"""
import struct

FIELDS = frozenset({"presence_animation_abi_version", "presence_animation_abi_address"})


def validate_presence_animation_manifest(manifest, rom_path=None):
    if not FIELDS.intersection(manifest):
        return False
    address = manifest.get("presence_animation_abi_address")
    if (not FIELDS.issubset(manifest)
            or type(manifest.get("presence_animation_abi_version")) is not int
            or manifest["presence_animation_abi_version"] != 1
            or manifest.get("abi_version") != 1 or manifest.get("mailbox_size") != 128
            or type(address) is not int or address % 4
            or not 0x08000000 <= address <= 0x09FFFFFC):
        raise ValueError("presence animation capability is incompatible")
    if rom_path is not None:
        if address - 0x08000000 > rom_path.stat().st_size - 4:
            raise ValueError("presence animation marker is outside the ROM")
        with rom_path.open("rb") as source:
            source.seek(address - 0x08000000)
            if source.read(4) != struct.pack("<I", 1):
                raise ValueError("presence animation marker differs from the verified ROM")
    return True
