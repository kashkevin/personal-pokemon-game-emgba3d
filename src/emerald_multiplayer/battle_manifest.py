"""Optional development battle capability; addresses come from the exact ELF."""
from pathlib import Path

BATTLE_FIELDS = frozenset({"battle_abi_version", "battle_abi_address",
                           "battle_mailbox_address", "battle_mailbox_size"})
EXECUTION_FIELDS = frozenset({"battle_execution_abi_version", "battle_string_table_address",
                              "battle_string_table_size"})
RESUME_FIELDS = frozenset({"battle_resume_abi_version", "battle_resume_abi_address"})
ADMISSION_CLEANUP_FIELDS = frozenset({"battle_admission_cleanup_abi_version", "battle_admission_cleanup_abi_address"})
COOP_FIELDS = frozenset({"battle_coop_abi_version", "battle_coop_abi_address"})
FFA_FIELDS = frozenset({"battle_ffa_abi_version"})   # advertised by the native PC game (not the GBA ROM, which stays byte-identical)
FFA3_FIELDS = frozenset({"battle_ffa3_abi_version"})  # Update 32: the 1v1v1, also native-PC-only; needs the free-for-all


def validate_battle_manifest(manifest, rom_path=None):
    if (EXECUTION_FIELDS | RESUME_FIELDS | ADMISSION_CLEANUP_FIELDS | COOP_FIELDS | FFA_FIELDS | FFA3_FIELDS).intersection(manifest) and not BATTLE_FIELDS.issubset(manifest):
        raise ValueError("native execution metadata requires the battle capability")
    if not BATTLE_FIELDS.intersection(manifest):
        return False
    if not BATTLE_FIELDS.issubset(manifest):
        raise ValueError("battle capability fields are incomplete")
    if type(manifest["battle_abi_version"]) is not int or manifest["battle_abi_version"] not in (1, 2, 3):
        raise ValueError("unsupported development battle ABI")
    for name, expected in (("battle_mailbox_size", 512),
                           ("ownership_abi_version", 1), ("trade_abi_version", 1),
                           ("save_abi_version", 1), ("save_mailbox_size", 512),
                           ("abi_version", 1), ("mailbox_size", 128)):
        if type(manifest.get(name)) is not int or manifest[name] != expected:
            raise ValueError("battle capability requires the matching ownership/trade/save build")
    if manifest.get("save_profile") != "rhh-1.17.1-bb1093-ownership-v1":
        raise ValueError("battle capability has an incompatible save profile")
    size, marker = manifest.get("rom_size"), manifest["battle_abi_address"]
    if (type(size) is not int or not 192 <= size <= 32 * 1024 * 1024
            or type(marker) is not int or marker % 4 or not 0x08000000 <= marker <= 0x08000000 + size - 4):
        raise ValueError("battle capability marker is outside its verified ROM")
    regions = []
    for name, length in (("mailbox_address", 128), ("save_mailbox_address", 512), ("battle_mailbox_address", 512)):
        address = manifest.get(name)
        if type(address) is not int or address % 4 or not 0x02000000 <= address <= 0x02040000 - length:
            raise ValueError("battle capability needs aligned EWRAM mailboxes")
        if any(address < high and low < address + length for low, high in regions):
            raise ValueError("battle capability mailboxes overlap")
        regions.append((address, address + length))
    if rom_path is not None:
        with Path(rom_path).open("rb") as source:
            source.seek(marker - 0x08000000)
            if source.read(4) != manifest["battle_abi_version"].to_bytes(4, "little"):
                raise ValueError("battle capability marker disagrees with the verified ROM")
    if EXECUTION_FIELDS.intersection(manifest):
        if (not EXECUTION_FIELDS.issubset(manifest)
                or type(manifest["battle_execution_abi_version"]) is not int
                or manifest["battle_execution_abi_version"] != 1
                or manifest["battle_abi_version"] not in (2, 3)
                or type(manifest["battle_string_table_size"]) is not int
                or manifest["battle_string_table_size"] != 721 * 4):
            raise ValueError("native execution metadata is incomplete or incompatible")
        address = manifest["battle_string_table_address"]
        if (type(address) is not int or address % 4
                or not 0x08000000 <= address <= 0x08000000 + size - 721 * 4):
            raise ValueError("native execution string table lies outside its exact ROM")
        if rom_path is not None:
            from .battle_controller import read_string_lengths
            read_string_lengths(rom_path, table_address=address)
    if RESUME_FIELDS.intersection(manifest):
        if (not RESUME_FIELDS.issubset(manifest) or not EXECUTION_FIELDS.issubset(manifest)
                or manifest["battle_abi_version"] != 3
                or type(manifest["battle_resume_abi_version"]) is not int
                or manifest["battle_resume_abi_version"] != 1):
            raise ValueError("resume metadata requires its complete ABI1 marker and native ABI3 executor")
        address = manifest["battle_resume_abi_address"]
        if (type(address) is not int or address % 4
                or not 0x08000000 <= address <= 0x08000000 + size - 4):
            raise ValueError("resume marker lies outside its exact ROM")
        if rom_path is not None:
            with Path(rom_path).open("rb") as source:
                source.seek(address - 0x08000000)
                if source.read(4) != b"\x01\0\0\0":
                    raise ValueError("resume marker disagrees with the verified ROM")
    if ADMISSION_CLEANUP_FIELDS.intersection(manifest):
        if (not ADMISSION_CLEANUP_FIELDS.issubset(manifest) or not RESUME_FIELDS.issubset(manifest)
                or any(type(manifest.get(key)) is not int or manifest[key] != expected for key, expected in (
                    ("battle_admission_cleanup_abi_version", 1), ("battle_resume_abi_version", 1),
                    ("battle_abi_version", 3), ("battle_execution_abi_version", 1),
                    ("menu_abi_version", 2), ("emergency_save_abi_version", 2)))):
            raise ValueError("admission cleanup requires its ABI1 marker, resume executor, menu ABI2 and emergency ABI2")
        from .menu_mailbox import validate_menu_manifest
        from .emergency_protocol import validate_emergency_manifest
        validate_menu_manifest(manifest, rom_path)
        validate_emergency_manifest(manifest, rom_path)
        address = manifest["battle_admission_cleanup_abi_address"]
        if (type(address) is not int or address % 4
                or not 0x08000000 <= address <= 0x08000000 + size - 4):
            raise ValueError("admission cleanup marker lies outside its exact ROM")
        if rom_path is not None:
            with Path(rom_path).open("rb") as source:
                source.seek(address - 0x08000000)
                if source.read(4) != b"\x01\0\0\0":
                    raise ValueError("admission cleanup marker disagrees with the verified ROM")
    if COOP_FIELDS.intersection(manifest):
        # Co-op Gym phase 4: two linked trainers against two in-game AI trainers.
        if (not COOP_FIELDS.issubset(manifest) or manifest["battle_abi_version"] != 3
                or type(manifest["battle_coop_abi_version"]) is not int or manifest["battle_coop_abi_version"] != 1):
            raise ValueError("co-op Gym metadata requires its ABI1 marker and the native ABI3 channel")
        address = manifest["battle_coop_abi_address"]
        if type(address) is not int or address % 4 or not 0x08000000 <= address <= 0x08000000 + size - 4:
            raise ValueError("co-op Gym marker lies outside its exact ROM")
        if rom_path is not None:
            with Path(rom_path).open("rb") as source:
                source.seek(address - 0x08000000)
                if source.read(4) != b"\x01\0\0\0":
                    raise ValueError("co-op Gym marker disagrees with the verified ROM")
    if FFA_FIELDS.intersection(manifest):
        # Free-for-all phase 5 is built into the native PC game only; the GBA ROM carries no marker for it, so there
        # is no address to verify, only the ABI generation and the native ABI3 channel it rides on.
        if (manifest["battle_abi_version"] != 3 or type(manifest["battle_ffa_abi_version"]) is not int
                or manifest["battle_ffa_abi_version"] != 1):
            raise ValueError("free-for-all metadata requires its ABI1 marker and the native ABI3 channel")
    if FFA3_FIELDS.intersection(manifest):
        # The three-player free-for-all (phase 6) is the free-for-all with its fourth place empty: it needs that marker.
        if (manifest["battle_abi_version"] != 3 or manifest.get("battle_ffa_abi_version") != 1
                or type(manifest["battle_ffa3_abi_version"]) is not int or manifest["battle_ffa3_abi_version"] != 1):
            raise ValueError("three-player free-for-all metadata requires its ABI1 marker and the free-for-all")
    return True
