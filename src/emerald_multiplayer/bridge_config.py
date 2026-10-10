"""Render a private loopback bridge for a verified ROM manifest."""
import re

from .battle_manifest import validate_battle_manifest
from .save_window import validate_window_manifest


def configure_native(manifest: dict, token: str, port: int) -> str:
    """The native game's bridge file (engine src/platform/mp_bridge.c,
    MpBridge_Configure): the companion's loopback port and launch token, and
    the manifest's explicit trade-effect opt-ins. The native game takes its
    mailboxes and capability markers from its own symbols, so nothing else
    of the manifest goes in; the runtime bundle pairs it with the ROM build
    the companion verified (player_runtime.NativeGame)."""
    from .trade_effect_mailbox import (validate_effect_choice_manifest, validate_effect_prepare_manifest,
                                       validate_effect_save_manifest)
    if (not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{64}", token)
            or type(port) is not int or not 1 <= port <= 65535):
        raise ValueError("Invalid bridge token or port")
    lines = [f"port={port}", f"token={token}"]
    if validate_effect_prepare_manifest(manifest):
        lines.append("trade_effect_prepare=1")
    if validate_effect_save_manifest(manifest):
        lines.append("trade_effect_save=1")
    if validate_effect_choice_manifest(manifest):
        lines.append("trade_effect_choice=1")
    return "\n".join(lines) + "\n"


def configure(manifest: dict, token: str, port: int, bridge: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", token) or not 1 <= port <= 65535:
        raise ValueError("Invalid bridge token or port")
    address = manifest["mailbox_address"]
    if type(address) is not int or address % 4 or not 0x02000000 <= address <= 0x02040000 - 128:
        raise ValueError("Invalid mailbox address")
    if manifest["abi_version"] != 1 or manifest["mailbox_size"] != 128:
        raise ValueError("Unsupported mailbox ABI")
    crc = manifest["rom_crc32"]
    if not isinstance(crc, str) or not re.fullmatch(r"[0-9a-f]{8}", crc):
        raise ValueError("Invalid ROM CRC")
    size = manifest["rom_size"]
    if type(size) is not int or not 192 <= size <= 32 * 1024 * 1024:
        raise ValueError("Invalid ROM size")
    save_config = ""
    save_fields = {"save_abi_version", "save_mailbox_size", "save_mailbox_address"}
    if save_fields & set(manifest):
        if not save_fields <= set(manifest):
            raise ValueError("Incomplete save mailbox manifest")
        save_address = manifest["save_mailbox_address"]
        if (type(manifest["save_abi_version"]) is not int or manifest["save_abi_version"] != 1
                or type(manifest["save_mailbox_size"]) is not int or manifest["save_mailbox_size"] != 512
                or type(save_address) is not int or save_address % 4
                or not 0x02000000 <= save_address <= 0x02040000 - 512
                or not (save_address + 512 <= address or address + 128 <= save_address)):
            raise ValueError("Invalid or overlapping save mailbox")
        save_config = f", save_address={save_address}, save_size=512, save_abi=1"
    trade_config = ""
    trade_fields = {"trade_abi_version", "trade_abi_address"}
    if trade_fields & set(manifest):
        marker = manifest.get("trade_abi_address")
        if (not trade_fields <= set(manifest) or not save_config
                or type(manifest.get("ownership_abi_version")) is not int
                or manifest["ownership_abi_version"] != 1
                or manifest.get("save_profile") != "rhh-1.17.1-bb1093-ownership-v1"
                or type(manifest["trade_abi_version"]) is not int or manifest["trade_abi_version"] != 1
                or type(marker) is not int or marker % 4
                or not 0x08000000 <= marker <= 0x08000000 + size - 4):
            raise ValueError("Invalid or incomplete trade capability")
        trade_config = f", trade_abi=1, trade_abi_address={marker}"
    battle_config = ""
    if validate_battle_manifest(manifest):
        battle_config = (f", battle_abi={manifest['battle_abi_version']}, battle_abi_address={manifest['battle_abi_address']}"
                         f", battle_address={manifest['battle_mailbox_address']}, battle_size=512")
        if manifest.get("battle_resume_abi_version") == 1:
            battle_config += f", battle_resume_abi=1, battle_resume_abi_address={manifest['battle_resume_abi_address']}"
        if manifest.get("battle_admission_cleanup_abi_version") == 1:
            battle_config += (", battle_execution_abi=1, battle_admission_cleanup_abi=1"
                              f", battle_admission_cleanup_abi_address={manifest['battle_admission_cleanup_abi_address']}")
    window_config = ""
    if validate_window_manifest(manifest):
        window_config = (f", window_abi=1, window_abi_address={manifest['save_window_abi_address']}"
                         f", window_address={manifest['save_window_address']}, window_size=4096")
    from .menu_mailbox import validate_menu_manifest
    menu_config = ""
    if validate_menu_manifest(manifest):
        menu_config = (f", menu_abi={manifest['menu_abi_version']}, menu_abi_address={manifest['menu_abi_address']}"
                       f", menu_address={manifest['menu_mailbox_address']}, menu_size=512")
    from .emergency_protocol import validate_emergency_manifest
    from .reset_mailbox import validate_reset_manifest
    reset_config = ""
    if validate_reset_manifest(manifest):
        reset_config = (f", reset_abi={manifest['reset_abi_version']}, reset_abi_address={manifest['reset_abi_address']}"
                        f", reset_address={manifest['reset_mailbox_address']}, reset_size=128")
        if manifest.get("reset_input_abi_version") == 1:
            reset_config += f", reset_input_abi=1, reset_input_abi_address={manifest['reset_input_abi_address']}"
    emergency_config = ""
    if validate_emergency_manifest(manifest):
        emergency_config = f", emergency_save_abi={manifest['emergency_save_abi_version']}, emergency_save_abi_address={manifest['emergency_save_abi_address']}"
    from .trade_effect_mailbox import validate_effect_prepare_manifest, validate_effect_save_manifest, validate_effect_choice_manifest
    effect_config = ""
    if validate_effect_prepare_manifest(manifest):
        effect_config = f", trade_effect_prepare_abi=1, trade_effect_prepare_abi_address={manifest['trade_effect_prepare_abi_address']}"
    if validate_effect_save_manifest(manifest):
        effect_config += f", trade_effect_save_abi=1, trade_effect_save_abi_address={manifest['trade_effect_save_abi_address']}"
    if validate_effect_choice_manifest(manifest):
        effect_config += f", trade_effect_choice_abi=1, trade_effect_choice_abi_address={manifest['trade_effect_choice_abi_address']}"
    from .presence_animation import validate_presence_animation_manifest
    animation_config = ""
    if validate_presence_animation_manifest(manifest):
        animation_config = (", presence_animation_abi=1"
                            f", presence_animation_abi_address={manifest['presence_animation_abi_address']}")
    from .world_mailbox import validate_world_manifest
    world_config = ""
    if validate_world_manifest(manifest):
        world_config = (f", world_abi=1, world_abi_address={manifest['world_abi_address']}"
                        f", world_address={manifest['world_mailbox_address']}, world_size=256")
    return (
        f'EMERALD_BRIDGE = {{address={address}, rom_size={size}, rom_crc32="{crc}", '
        f'port={port}, token="{token}"{save_config}{trade_config}{battle_config}{window_config}{menu_config}{emergency_config}{reset_config}{effect_config}{animation_config}{world_config}}}\n' + bridge
    )
