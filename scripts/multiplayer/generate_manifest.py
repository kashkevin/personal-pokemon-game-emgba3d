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


def native_marker(name, symbols):
    """[(address, size or None)] of a PC-only marker in `nm --print-size` output. GNU nm prints an ELF symbol's size, but a
    PE/COFF executable (the Windows game, MinGW nm) has no symbol sizes and its lines have none; the Windows package's
    manifest is generated from those, so a line without a size is taken on its address and data type alone. (Requiring
    the size dropped all three PC-only markers from every Windows manifest: 2026-10-19.)"""
    return [(address, size or None) for address, size in
            re.findall(rf"^([0-9a-fA-F]+)\s+(?:([0-9a-fA-F]+)\s+)?[RrDd]\s+_?{name}$", symbols, re.M)]


def four_byte_marker(found):
    """Exactly one marker, of four bytes where nm says its size."""
    return len(found) == 1 and (found[0][1] is None or int(found[0][1], 16) == 4)


def generate(rom: Path, elf: Path, nm: str, engine_commit: str, *, trade_effect_prepare=False, trade_effect_save=False, trade_effect_choice=False,
             native_symbols: str = "") -> dict:
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
    player_guard = [line for line in symbols.splitlines() if line.split()[-1:] == ["gMultiplayerPlayerBuildGuard"]]
    if player_guard:
        from emerald_multiplayer.player_build import DESCRIPTOR, validate_player_build_manifest
        match = re.fullmatch(r"([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[Rr]\s+gMultiplayerPlayerBuildGuard", player_guard[0])
        if len(player_guard) != 1 or match is None or int(match[2], 16) != len(DESCRIPTOR):
            raise ValueError("player build guard requires one exact read-only ROM descriptor")
        manifest.update(player_build_guard_abi_version=1, player_build_guard_address=int(match[1], 16))
        validate_player_build_manifest(manifest, rom)
    generation = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[Rr]\s+gMultiplayerGenerationProfile$", symbols, re.M)
    if generation:
        from emerald_multiplayer.gen6_profile import DESCRIPTOR, GEN6_DEFAULTS_RULESET, validate_generation_profile
        if len(generation) != 1 or int(generation[0][1], 16) != len(DESCRIPTOR):
            raise ValueError("generation profile requires one exact ROM descriptor")
        manifest.update(ruleset_id=GEN6_DEFAULTS_RULESET, generation_profile_version=1,
                        generation_profile_address=int(generation[0][0], 16))
        validate_generation_profile(manifest, rom)
    presentation = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[Rr]\s+gMultiplayerPresenceAnimationAbiVersion$", symbols, re.M)
    if presentation:
        from emerald_multiplayer.presence_animation import validate_presence_animation_manifest
        if len(presentation) != 1 or int(presentation[0][1], 16) != 4:
            raise ValueError("presence animation requires one exact ROM marker")
        manifest.update(presence_animation_abi_version=1, presence_animation_abi_address=int(presentation[0][0], 16))
        validate_presence_animation_manifest(manifest, rom)
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
        resume = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[Rr]\s+gMultiplayerBattleResumeAbiVersion$", symbols, re.M)
        if resume:
            if len(resume) != 1 or int(resume[0][1], 16) != 4:
                raise ValueError("native resume requires exactly one four-byte compiler-located marker")
            manifest.update(battle_resume_abi_version=1, battle_resume_abi_address=int(resume[0][0], 16))
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
    cleanup = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[Rr]\s+gMultiplayerBattleAdmissionCleanupAbiVersion$", symbols, re.M)
    if cleanup:
        from emerald_multiplayer.battle_manifest import validate_battle_manifest
        if len(cleanup) != 1 or int(cleanup[0][1], 16) != 4:
            raise ValueError("admission cleanup requires one four-byte compiler-located marker")
        manifest.update(battle_admission_cleanup_abi_version=1,
                        battle_admission_cleanup_abi_address=int(cleanup[0][0], 16))
        validate_battle_manifest(manifest, rom)
    coop = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[Rr]\s+gMultiplayerBattleCoopAbiVersion$", symbols, re.M)
    if coop:
        from emerald_multiplayer.battle_manifest import validate_battle_manifest
        if len(coop) != 1 or int(coop[0][1], 16) != 4 or not battle:
            raise ValueError("co-op Gym battles require one four-byte marker and the native battle channel")
        manifest.update(battle_coop_abi_version=1, battle_coop_abi_address=int(coop[0][0], 16))
        validate_battle_manifest(manifest, rom)
    # The four-player free-for-all exists in the native PC game only (the GBA ROM stays byte-identical), so its marker is read
    # from the symbols of the PC executable (`nm` of the unstripped exe), not from the GBA ELF.
    ffa = native_marker("gMultiplayerBattleFfaAbiVersion", symbols + native_symbols)
    if ffa:
        from emerald_multiplayer.battle_manifest import validate_battle_manifest
        if not four_byte_marker(ffa) or not battle:
            raise ValueError("free-for-all battles require one four-byte marker and the native battle channel")
        manifest.update(battle_ffa_abi_version=1)
        validate_battle_manifest(manifest, rom)
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
    reset_input = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[Rr]\s+gMultiplayerResetInputAbiVersion$", symbols, re.M)
    if reset_input:
        from emerald_multiplayer.reset_mailbox import validate_reset_manifest
        if len(reset_input) != 1 or int(reset_input[0][1], 16) != 4 or not reset:
            raise ValueError("reset input requires one four-byte compiler-located marker and reset support")
        manifest.update(reset_input_abi_version=1, reset_input_abi_address=int(reset_input[0][0], 16))
        validate_reset_manifest(manifest, rom)
    reset_catalogue = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[Rr]\s+gMultiplayerResetCatalogue$", symbols, re.M)
    if reset_catalogue:
        from emerald_multiplayer.reset_catalogue import DESCRIPTOR
        from emerald_multiplayer.reset_mailbox import validate_reset_manifest
        if len(reset_catalogue) != 1 or int(reset_catalogue[0][1], 16) != DESCRIPTOR.size or not reset:
            raise ValueError("personal reset catalogue requires one compiler-located descriptor and reset support")
        address = int(reset_catalogue[0][0], 16)
        if address % 4 or not 0x08000000 <= address <= 0x08000000 + rom.stat().st_size - DESCRIPTOR.size:
            raise ValueError("personal reset catalogue is outside ROM")
        with rom.open("rb") as source:
            source.seek(address - 0x08000000)
            version, first, count, enabled, controls, build_flags = DESCRIPTOR.unpack(source.read(DESCRIPTOR.size))
        manifest.update(reset_catalogue_version=version, reset_catalogue_address=address,
                        reset_source_mask=enabled, reset_control_flags=controls, reset_build_flags=build_flags)
        validate_reset_manifest(manifest, rom)  # Also verifies first/count/build bytes.
    world = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[Rr]\s+gMultiplayerWorldAbiVersion$", symbols, re.M)
    world_channel = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[BDbd]\s+gMultiplayerWorldMailbox$", symbols, re.M)
    if world or world_channel:
        from emerald_multiplayer.world_mailbox import validate_world_manifest
        if len(world) != 1 or len(world_channel) != 1 or int(world[0][1], 16) != 4:
            raise ValueError("shared world requires one marker and one allocated mailbox")
        manifest.update(world_abi_version=1, world_abi_address=int(world[0][0], 16),
                        world_mailbox_address=int(world_channel[0][0], 16),
                        world_mailbox_size=int(world_channel[0][1], 16))
        validate_world_manifest(manifest, rom)
    # Update 31: rival checkpoints (the RivalRecord in the world mailbox, a rival battle's environment in its preparation)
    # exist in the native PC game only, so the marker comes from the PC executable's symbols, like the free-for-all's.
    rival = native_marker("gMultiplayerRivalAbiVersion", symbols + native_symbols)
    if rival:
        if not four_byte_marker(rival) or not world:
            raise ValueError("rival checkpoints require one four-byte marker and the shared world mailbox")
        manifest.update(rival_abi_version=1)
    # Why a player is off the field (the PC game's pose: in battle, a menu, changing area), for the other players'
    # Players lists (docs/multiplayer-session-fix-20261019.md). Native PC game only, like the rival marker.
    detail = native_marker("gMultiplayerPresenceDetailAbiVersion", symbols + native_symbols)
    if detail:
        if not four_byte_marker(detail):
            raise ValueError("the presence detail needs one four-byte marker")
        manifest.update(presence_detail_abi_version=1)
    # A refused Enter battle releases the game's latched Players window (menu screens with flags 3): native PC game
    # only, like the presence detail (docs/multiplayer-battle-trade-repair-20261020.md).
    release = native_marker("gMultiplayerMenuReleaseAbiVersion", symbols + native_symbols)
    if release:
        if not four_byte_marker(release) or manifest.get("menu_abi_version") != 2 or manifest.get("battle_resume_abi_version") != 1:
            raise ValueError("the menu release needs one four-byte marker, the Players menu ABI 2 and native battle resume")
        manifest.update(menu_release_abi_version=1)
    # A trade's received save staged a 4 KiB sector per command ('i', WRITE_WINDOW) instead of 1024 WRITEs: native PC
    # game only (the GBA ROM is unchanged), and only beside the read-only save window it pairs with.
    import_window = native_marker("gMultiplayerSaveImportWindowAbiVersion", symbols + native_symbols)
    if import_window:
        if not four_byte_marker(import_window) or manifest.get("save_window_abi_version") != 1:
            raise ValueError("the save import window needs one four-byte marker and the read-only save window")
        manifest.update(save_import_window_abi_version=1)
    # Update 32: a Players menu OPEN may name the page it opens (1: START > PLAYER > RESET, the soft reset in a world).
    # Native PC game only; the launcher opts in (bridge.txt menu_open_page=1) only beside the Players menu ABI 2.
    open_page = native_marker("gMultiplayerMenuOpenPageAbiVersion", symbols + native_symbols)
    if open_page:
        if not four_byte_marker(open_page) or manifest.get("menu_abi_version") != 2:
            raise ValueError("the menu open page needs one four-byte marker and the Players menu ABI 2")
        manifest.update(menu_open_page_abi_version=1)
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
    # Internal computation transport is an explicit opt-in, never inferred from
    # the trade marker or enabled in an existing release manifest.
    if type(trade_effect_prepare) is not bool:
        raise ValueError("trade_effect_prepare must be an explicit boolean")
    if trade_effect_prepare:
        markers = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[Rr]\s+gMultiplayerTradeEffectPrepareAbiVersion$", symbols, re.M)
        if len(markers) != 1 or int(markers[0][1], 16) != 4:
            raise ValueError("missing native record preparation marker")
        from emerald_multiplayer.trade_effect_mailbox import validate_effect_prepare_manifest
        manifest.update(trade_effect_prepare_abi_version=1,
                        trade_effect_prepare_abi_address=int(markers[0][0], 16))
        validate_effect_prepare_manifest(manifest, rom)
    if type(trade_effect_save) is not bool or (trade_effect_save and not trade_effect_prepare):
        raise ValueError("full save preparation needs explicit record preparation opt-in")
    if trade_effect_save:
        markers = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[Rr]\s+gMultiplayerTradeEffectSaveAbiVersion$", symbols, re.M)
        if len(markers) != 1 or int(markers[0][1], 16) != 4:
            raise ValueError("missing full save preparation marker")
        from emerald_multiplayer.trade_effect_mailbox import validate_effect_save_manifest
        manifest.update(trade_effect_save_abi_version=1, trade_effect_save_abi_address=int(markers[0][0], 16))
        validate_effect_save_manifest(manifest, rom)
    if type(trade_effect_choice) is not bool or (trade_effect_choice and not trade_effect_prepare):
        raise ValueError("move presentation needs explicit record preparation opt-in")
    if trade_effect_choice:
        markers = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[Rr]\s+gMultiplayerTradeEffectChoiceAbiVersion$", symbols, re.M)
        if len(markers) != 1 or int(markers[0][1], 16) != 4:
            raise ValueError("missing native move presentation marker")
        from emerald_multiplayer.trade_effect_mailbox import validate_effect_choice_manifest
        manifest.update(trade_effect_choice_abi_version=1, trade_effect_choice_abi_address=int(markers[0][0], 16))
        validate_effect_choice_manifest(manifest, rom)
    replay = re.findall(r"^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+[Rr]\s+gMultiplayerTradeReplayDescriptor$", symbols, re.M)
    if replay and trade_effect_prepare and trade_effect_save and trade_effect_choice:
        from emerald_multiplayer.trade_replay_manifest import DESCRIPTOR, validate_trade_replay_manifest
        if len(replay) != 1 or int(replay[0][1], 16) != DESCRIPTOR.size:
            raise ValueError("native replay requires one exact ROM descriptor")
        manifest.update(trade_replay_abi_version=1, trade_replay_descriptor_address=int(replay[0][0], 16))
        validate_trade_replay_manifest(manifest, rom)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--engine-commit", required=True)
    parser.add_argument("--nm", default="arm-none-eabi-nm")
    parser.add_argument("--native-symbols", type=Path, default=None,
                        help="`nm --print-size --defined-only` of the unstripped native PC executable (advertises PC-only battle features)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trade-effect-prepare", action="store_true",
                        help="opt into internal held record preparation; does not enable effect publication")
    parser.add_argument("--trade-effect-save", action="store_true",
                        help="opt into complete private candidate windows; requires --trade-effect-prepare")
    parser.add_argument("--trade-effect-choice", action="store_true",
                        help="opt into native move presentation; requires --trade-effect-prepare")
    args = parser.parse_args()
    manifest = generate(args.rom, args.elf, args.nm, args.engine_commit,
                        trade_effect_prepare=args.trade_effect_prepare, trade_effect_save=args.trade_effect_save,
                        trade_effect_choice=args.trade_effect_choice,
                        native_symbols=args.native_symbols.read_text() if args.native_symbols else "")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Verified mailbox manifest: {args.output}; ROM {manifest['rom_sha256']}")


if __name__ == "__main__":
    main()
