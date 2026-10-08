"""Generate mailbox metadata from this exact ELF and ROM, never a fixed address."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zlib

RULESET = "baseline-rhh1.17.1-mailbox-v1"


def generate(rom: Path, elf: Path, nm: str, engine_commit: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", engine_commit):
        raise ValueError("engine_commit must be the exact Git commit")
    symbols = subprocess.check_output([nm, "--print-size", "--defined-only", str(elf)], text=True)
    matches = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[BDbd]\s+gMultiplayerMailbox$", symbols, re.M)
    if len(matches) != 1:
        raise ValueError("ELF must contain one allocated gMultiplayerMailbox symbol")
    address, size = (int(value, 16) for value in matches[0])
    if size != 128 or address % 4 or not 0x02000000 <= address <= 0x02040000 - size:
        raise ValueError("Mailbox is not the expected 128-byte aligned EWRAM allocation")
    sha, crc, rom_size = hashlib.sha256(), 0, 0
    with rom.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
            crc = zlib.crc32(block, crc)
            rom_size += len(block)
    if not 192 <= rom_size <= 32 * 1024 * 1024:
        raise ValueError("ROM size is outside the GBA build bounds")
    manifest = {
        "abi_version": 1, "mailbox_size": size, "mailbox_address": address,
        "rom_sha256": sha.hexdigest(), "rom_crc32": f"{crc:08x}",
        "rom_size": rom_size, "elf_sha256": hashlib.sha256(elf.read_bytes()).hexdigest(),
        "ruleset_id": RULESET, "engine_commit": engine_commit,
    }
    save = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[BDbd]\s+gMultiplayerSaveMailbox$", symbols, re.M)
    if save:
        if len(save) != 1:
            raise ValueError("ELF must contain one allocated save mailbox")
        save_address, save_size = (int(value, 16) for value in save[0])
        if save_size != 512 or save_address % 4 or not 0x02000000 <= save_address <= 0x02040000 - save_size:
            raise ValueError("Save mailbox is not the expected 512-byte EWRAM allocation")
        if not (save_address + save_size <= address or address + size <= save_address):
            raise ValueError("Save and presence mailboxes overlap")
        manifest.update(save_abi_version=1, save_mailbox_size=save_size, save_mailbox_address=save_address)
    ownership = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[Rr]\s+gMultiplayerOwnershipAbi$", symbols, re.M)
    if ownership:
        if len(ownership) != 1 or not save:
            raise ValueError("Ownership ABI requires one marker and the live save mailbox")
        marker, marker_size = (int(value, 16) for value in ownership[0])
        if marker_size != 4 or not 0x08000000 <= marker <= 0x08000000 + rom_size - 4:
            raise ValueError("Ownership ABI marker must be allocated in this ROM")
        with rom.open("rb") as stream:
            stream.seek(marker - 0x08000000)
            if stream.read(4) != b"\x01\x00\x00\x00":
                raise ValueError("Unsupported ownership ABI marker")
        manifest.update(ownership_abi_version=1, save_profile="rhh-1.17.1-bb1093-ownership-v1")
    trade = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[Rr]\s+gMultiplayerTradeAbiVersion$", symbols, re.M)
    if trade:
        if len(trade) != 1 or not ownership:
            raise ValueError("Trade ABI requires one marker and ownership support")
        marker, marker_size = (int(value, 16) for value in trade[0])
        if marker_size != 4 or marker % 4 or not 0x08000000 <= marker <= 0x08000000 + rom_size - 4:
            raise ValueError("Trade ABI marker must be aligned and allocated in this ROM")
        with rom.open("rb") as stream:
            stream.seek(marker - 0x08000000)
            if stream.read(4) != b"\x01\x00\x00\x00":
                raise ValueError("Unsupported trade ABI marker")
        manifest.update(trade_abi_version=1, trade_abi_address=marker)
    emergency = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[Rr]\s+gMultiplayerEmergencySaveAbiVersion$", symbols, re.M)
    if emergency:
        from emerald_multiplayer.emergency_protocol import validate_emergency_manifest
        if len(emergency) != 1 or int(emergency[0][1], 16) != 4 or not trade:
            raise ValueError("emergency save requires one ROM marker and ownership/trade support")
        marker = int(emergency[0][0], 16)
        if not 0x08000000 <= marker <= 0x08000000 + rom_size - 4:
            raise ValueError("emergency marker is outside the ROM")
        with rom.open("rb") as stream:
            stream.seek(marker - 0x08000000)
            version = int.from_bytes(stream.read(4), "little")
        manifest.update(emergency_save_abi_version=version, emergency_save_abi_address=marker)
        validate_emergency_manifest(manifest, rom)
    battle = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[Rr]\s+gMultiplayerBattleAbiVersion$", symbols, re.M)
    channel = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[BDbd]\s+gMultiplayerBattleMailbox$", symbols, re.M)
    if battle or channel:
        from emerald_multiplayer.battle_manifest import validate_battle_manifest
        if len(battle) != 1 or len(channel) != 1 or not trade or int(battle[0][1], 16) != 4:
            raise ValueError("Battle capability requires one ROM marker, one channel and trade support")
        marker = int(battle[0][0], 16)
        if marker % 4 or not 0x08000000 <= marker <= 0x08000000 + rom_size - 4:
            raise ValueError("Battle ABI marker must be aligned and allocated in this ROM")
        with rom.open("rb") as stream:
            stream.seek(marker - 0x08000000)
            version = int.from_bytes(stream.read(4), "little")
        manifest.update(battle_abi_version=version, battle_abi_address=marker,
                        battle_mailbox_address=int(channel[0][0], 16), battle_mailbox_size=int(channel[0][1], 16))
        strings = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[Rr]\s+gBattleStringsTable$", symbols, re.M)
        if strings and version in (2, 3):
            if len(strings) != 1:
                raise ValueError("native execution needs exactly one compiler-located battle string table")
            manifest.update(battle_execution_abi_version=1,
                battle_string_table_address=int(strings[0][0], 16),
                battle_string_table_size=int(strings[0][1], 16))
        validate_battle_manifest(manifest, rom)
    window = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[Rr]\s+gMultiplayerSaveWindowAbiVersion$", symbols, re.M)
    if window:
        from emerald_multiplayer.save_window import validate_window_manifest
        buffer = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[BDbd]\s+gSaveDataBuffer$", symbols, re.M)
        if len(window) != 1 or len(buffer) != 1 or int(window[0][1], 16) != 4 or not trade:
            raise ValueError("save window requires one marker and the pinned native sector buffer")
        manifest.update(save_window_abi_version=1, save_window_abi_address=int(window[0][0], 16),
                        save_window_address=int(buffer[0][0], 16), save_window_size=int(buffer[0][1], 16))
        validate_window_manifest(manifest, rom)
    menu = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[Rr]\s+gMultiplayerMenuAbiVersion$", symbols, re.M)
    menu_channel = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[BDbd]\s+gMultiplayerMenuMailbox$", symbols, re.M)
    if menu or menu_channel:
        from emerald_multiplayer.menu_mailbox import validate_menu_manifest
        if len(menu) != 1 or len(menu_channel) != 1 or int(menu[0][1], 16) != 4:
            raise ValueError("menu requires one marker and one allocated mailbox")
        marker = int(menu[0][0], 16)
        with rom.open("rb") as stream:
            stream.seek(marker - 0x08000000)
            version = int.from_bytes(stream.read(4), "little")
        manifest.update(menu_abi_version=version, menu_abi_address=marker,
                        menu_mailbox_address=int(menu_channel[0][0], 16), menu_mailbox_size=int(menu_channel[0][1], 16))
        validate_menu_manifest(manifest, rom)
    objects = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[BDbd]\s+gObjectEvents$", symbols, re.M)
    reset = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[Rr]\s+gMultiplayerResetAbiVersion$", symbols, re.M)
    reset_channel = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[BDbd]\s+gMultiplayerResetMailbox$", symbols, re.M)
    if reset or reset_channel:
        from emerald_multiplayer.reset_mailbox import validate_reset_manifest
        if len(reset) != 1 or len(reset_channel) != 1 or int(reset[0][1], 16) != 4 or not ownership:
            raise ValueError("personal reset requires one marker, mailbox and ownership support")
        reset_address = int(reset[0][0], 16)
        with rom.open("rb") as source:
            source.seek(reset_address - 0x08000000)
            reset_version = int.from_bytes(source.read(4), "little")
        manifest.update(reset_abi_version=reset_version, reset_abi_address=reset_address,
            reset_mailbox_address=int(reset_channel[0][0], 16), reset_mailbox_size=int(reset_channel[0][1], 16))
        validate_reset_manifest(manifest, rom)
    if len(objects) == 1:
        obj_address, obj_size = (int(value, 16) for value in objects[0])
        # Read-only test metadata for the pinned engine's 0x24-byte objects.
        if obj_size % 36 == 0 and 0x02000000 <= obj_address <= 0x02040000 - obj_size:
            manifest.update(debug_object_events_address=obj_address,
                            debug_object_events_size=obj_size, debug_object_event_size=36)
    sprites = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[BDbd]\s+gSprites$", symbols, re.M)
    if len(sprites) == 1:
        sprite_address, sprite_size = (int(value, 16) for value in sprites[0])
        if sprite_size % 68 == 0 and 0x02000000 <= sprite_address <= 0x02040000 - sprite_size:
            manifest.update(debug_sprites_address=sprite_address,
                            debug_sprites_size=sprite_size, debug_sprite_size=68)
    for name, key, expected_size in (
        ("gParties", "debug_parties", 2400),
        ("gPartiesCount", "debug_party_counts", 4),
        ("gSaveBlock1Ptr", "debug_save_block1_ptr", 4),
    ):
        match = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[BDbd]\s+" + name + "$", symbols, re.M)
        if len(match) != 1 or int(match[0][1], 16) != expected_size:
            raise ValueError(f"Unexpected pinned-engine debug symbol {name}")
        debug_address = int(match[0][0], 16)
        lower, upper = (0x03000000, 0x03008000) if name == "gSaveBlock1Ptr" else (0x02000000, 0x02040000)
        if not lower <= debug_address <= upper - expected_size:
            raise ValueError(f"Debug symbol outside expected RAM region: {name}")
        manifest[key + "_address"] = debug_address
    # Verified pinned-engine SaveBlock1 offsets; these are read-only diagnostics.
    save2 = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[BDbd]\s+gSaveBlock2Ptr$", symbols, re.M)
    if save2:
        if len(save2) != 1 or int(save2[0][1], 16) != 4 or not 0x03000000 <= int(save2[0][0], 16) <= 0x03007FFC:
            raise ValueError("Unexpected pinned-engine SaveBlock2 pointer")
        manifest.update(debug_save_block2_ptr_address=int(save2[0][0], 16), debug_play_time_offset=14, debug_play_time_size=5)
    manifest.update(debug_saved_objects_offset=0xA30,
                    debug_saved_party_count_offset=0x234,
                    debug_saved_party_offset=0x238, debug_party_size=600)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--engine-commit", required=True)
    parser.add_argument("--nm", default="arm-none-eabi-nm")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = generate(args.rom, args.elf, args.nm, args.engine_commit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Verified mailbox manifest: {args.output}; ROM {manifest['rom_sha256']}")


if __name__ == "__main__":
    main()
