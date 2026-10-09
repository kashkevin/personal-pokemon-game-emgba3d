"""ROM-bound exclusion of the engine's player-accessible development controls.

This marker reports four compiled flags. It does not disable assertions, change
gameplay rules, or certify every aspect of a release. Legacy ROMs may omit it;
normal player packaging requires it and verifies the actual ROM bytes.
"""
from pathlib import Path
import struct


FIELDS = frozenset({"player_build_guard_abi_version", "player_build_guard_address"})
MAGIC = 0x31474250
FLAGS = ("DEBUG_OVERWORLD_MENU", "DEBUG_BATTLE_MENU",
         "DEBUG_POKEMON_SPRITE_VISUALIZER", "I_SHOW_NO_ID_TRAINER")
DESCRIPTOR = struct.pack("<6I", MAGIC, 1, 0, 0, 0, 0)


def validate_player_build_manifest(manifest, rom_path=None):
    """Validate an advertised marker; absence alone retains legacy support."""
    if not FIELDS.intersection(manifest):
        return False
    address = manifest.get("player_build_guard_address")
    size = Path(rom_path).stat().st_size if rom_path is not None else manifest.get("rom_size")
    if (not FIELDS.issubset(manifest)
            or type(manifest.get("player_build_guard_abi_version")) is not int
            or manifest["player_build_guard_abi_version"] != 1
            or type(size) is not int or not 192 <= size <= 32 * 1024 * 1024
            or type(address) is not int or address % 4
            or not 0x08000000 <= address <= 0x08000000 + size - len(DESCRIPTOR)):
        raise ValueError("player build guard is incomplete or outside the supported ROM")
    if rom_path is not None:
        with Path(rom_path).open("rb") as source:
            source.seek(address - 0x08000000)
            if source.read(len(DESCRIPTOR)) != DESCRIPTOR:
                raise ValueError("player build guard is malformed or enables development controls")
    return True


def require_production_player_build(manifest, rom_path):
    """Require compiled disabled controls, never metadata-only certification."""
    if rom_path is None:
        raise ValueError("normal player packaging requires the verified ROM bytes")
    if not validate_player_build_manifest(manifest, rom_path):
        raise ValueError("normal player packaging requires the compiled player build guard")
    return True
