"""Exact compiled personal-source availability, separate from live eligibility."""
from pathlib import Path
import struct
from .reset_protocol import SOURCES

FIELDS = frozenset({"reset_catalogue_version", "reset_catalogue_address", "reset_source_mask", "reset_control_flags", "reset_build_flags"})
DESCRIPTOR = struct.Struct("<6I")
ALL_SOURCES = (1 << len(SOURCES)) - 1


def validate_reset_catalogue(manifest, rom_path=None):
    if not FIELDS.intersection(manifest):
        return False
    if not FIELDS <= set(manifest):
        raise ValueError("personal reset catalogue manifest is incomplete")
    version, address, mask, controls, build = (manifest[key] for key in
        ("reset_catalogue_version", "reset_catalogue_address", "reset_source_mask", "reset_control_flags", "reset_build_flags"))
    size = Path(rom_path).stat().st_size if rom_path is not None else manifest.get("rom_size")
    if (type(version) is not int or version != 1 or manifest.get("reset_abi_version") != 2
            or type(mask) is not int or mask not in (0, 1, ALL_SOURCES)
            or type(controls) is not int or controls not in (0, 3)
            or type(build) is not int or not 0 <= build <= 3
            or (build and not controls) or (build & 2 and mask != ALL_SOURCES)
            or bool(controls) != (manifest.get("reset_input_abi_version") == 1)
            or (mask and not controls)
            or type(size) is not int or not 192 <= size <= 32 * 1024 * 1024
            or type(address) is not int or address % 4
            or not 0x08000000 <= address <= 0x08000000 + size - DESCRIPTOR.size):
        raise ValueError("personal reset catalogue differs from the supported compiler contract")
    for key in ("reset_abi_address", "reset_input_abi_address"):
        if key in manifest:
            marker = manifest[key]
            if type(marker) is not int or not (marker + 4 <= address or address + DESCRIPTOR.size <= marker):
                raise ValueError("personal reset catalogue overlaps its capability marker")
    if rom_path is not None:
        with Path(rom_path).open("rb") as source:
            source.seek(address - 0x08000000)
            expected = DESCRIPTOR.pack(1, min(SOURCES), len(SOURCES), mask, controls, build)
            if source.read(DESCRIPTOR.size) != expected:
                raise ValueError("personal reset catalogue differs from the verified ROM")
    return True


def require_production_reset_manifest(manifest, rom_path=None):
    """Reject a release that silently omits production sources or recovery ABI."""
    from .reset_mailbox import validate_reset_manifest
    from .emergency_protocol import validate_emergency_manifest
    from .battle_manifest import validate_battle_manifest
    if (not validate_reset_manifest(manifest, rom_path) or not validate_reset_catalogue(manifest, rom_path)
            or not validate_emergency_manifest(manifest, rom_path)
            or not validate_battle_manifest(manifest, rom_path)
            or manifest["reset_source_mask"] != ALL_SOURCES or manifest["reset_control_flags"] != 3
            or manifest["reset_build_flags"] != 0 or manifest.get("emergency_save_abi_version") != 2
            or manifest.get("battle_execution_abi_version") != 1):
        raise ValueError("production Local Soft Reset requires all25 sources, normal controls, durable admission and emergency recovery")
    return True


def reset_source_catalogue(config):
    known = getattr(config, "reset_catalogue_version", 0) == 1
    mask = getattr(config, "reset_source_mask", None)
    return [dict(encounter_id=source, name=name,
        availability=("enabled" if mask & (1 << index) else "disabled") if known else "unknown",
        eligibility="UNKNOWN") for index, (source, name) in enumerate(sorted(SOURCES.items()))]


def reset_controls(config):
    known = getattr(config, "reset_catalogue_version", 0) == 1
    flags = getattr(config, "reset_control_flags", None)
    # Older builds can prove the input contract without proving their source mask.
    supported = getattr(config, "reset_input_abi_version", 0) == 1
    return dict(status=("enabled" if flags else "disabled") if known else ("enabled" if supported else "unknown"),
        entry="Interact with an eligible personal static encounter normally.",
        select="SELECT opens reset confirmation at the first battle action window.",
        chord="A + B + START + SELECT opens the same confirmation; release all four afterward.",
        confirmation="Starts on No. Up selects Yes; A confirms, B cancels.",
        window="Choosing an action or submenu closes this encounter's reset window.",
        exclusions="World Events, wild encounters and completed captures cannot be rerolled.")
