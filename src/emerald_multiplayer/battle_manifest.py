"""Optional development battle capability; addresses come from the exact ELF."""
from pathlib import Path

BATTLE_FIELDS = frozenset({"battle_abi_version", "battle_abi_address",
                           "battle_mailbox_address", "battle_mailbox_size"})
EXECUTION_FIELDS = frozenset({"battle_execution_abi_version", "battle_string_table_address",
                              "battle_string_table_size"})


def validate_battle_manifest(manifest, rom_path=None):
    if EXECUTION_FIELDS.intersection(manifest) and not BATTLE_FIELDS.issubset(manifest):
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
    return True
