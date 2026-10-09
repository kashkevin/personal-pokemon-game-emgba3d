"""Verified optional cleanup wiring; synthetic ROM/memory, not gameplay proof."""
import json
import struct
import unittest
from uuid import UUID

from emerald_multiplayer.battle_manifest import ADMISSION_CLEANUP_FIELDS, validate_battle_manifest
from emerald_multiplayer.companion import CompanionConfig
import test_battle_manifest as manifest_fixtures
import test_battle_bridge as bridge_fixtures


class AdmissionCleanupManifestTests(unittest.TestCase):
    setUp = manifest_fixtures.BattleManifestTests.setUp
    tearDown = manifest_fixtures.BattleManifestTests.tearDown
    generate = manifest_fixtures.BattleManifestTests.generate
    configure = manifest_fixtures.BattleManifestTests.configure

    def cleanup_symbols(self):
        with self.rom.open("r+b") as rom:
            rom.seek(200)
            rom.write(struct.pack("<IIIII", 3, 1, 2, 2, 1))
            rom.seek(0x300)
            rom.write(bytes(721 * 4))
        return (self.base + self.battle
            + "08000300 00000b44 R gBattleStringsTable\n"
            + "080000cc 00000004 R gMultiplayerBattleResumeAbiVersion\n"
            + "080000d0 00000004 R gMultiplayerEmergencySaveAbiVersion\n"
            + "080000d4 00000004 R gMultiplayerMenuAbiVersion\n"
            + "02023000 00000200 B gMultiplayerMenuMailbox\n"
            + "080000d8 00000004 R gMultiplayerBattleAdmissionCleanupAbiVersion\n")

    def config(self, manifest):
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return CompanionConfig(self.rom, self.manifest_path, str(UUID(int=1)), "One", b"a" * 32)

    def test_compiler_marker_drives_bridge_and_companion_optional_capability(self):
        legacy = self.generate(self.base + self.battle)
        self.assertEqual(self.config(legacy).battle_admission_cleanup_abi_version, 0)
        self.assertNotIn("battle_admission_cleanup", self.configure(legacy))
        value = self.generate(self.cleanup_symbols())
        self.assertEqual(value["battle_admission_cleanup_abi_address"], 0x080000D8)
        self.assertEqual(self.config(value).battle_admission_cleanup_abi_version, 1)
        rendered = self.configure(value)
        self.assertIn("battle_execution_abi=1, battle_admission_cleanup_abi=1", rendered)
        self.assertIn("battle_admission_cleanup_abi_address=134217944", rendered)
        self.assertTrue(validate_battle_manifest(value, self.rom))

    def test_incomplete_or_changed_prerequisites_refuse_capability(self):
        value = self.generate(self.cleanup_symbols())
        keys = ADMISSION_CLEANUP_FIELDS | {
            "battle_abi_version", "battle_resume_abi_version", "battle_resume_abi_address",
            "battle_execution_abi_version", "battle_string_table_address", "battle_string_table_size",
            "menu_abi_version", "menu_abi_address", "menu_mailbox_address", "menu_mailbox_size",
            "emergency_save_abi_version", "emergency_save_abi_address"}
        for key in keys:
            changed = dict(value)
            del changed[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                validate_battle_manifest(changed, self.rom)
        for key, bad in (("battle_admission_cleanup_abi_version", True),
                         ("battle_admission_cleanup_abi_version", 2),
                         ("battle_resume_abi_version", 0), ("menu_abi_version", 1),
                         ("emergency_save_abi_version", 1),
                         ("battle_admission_cleanup_abi_address", True),
                         ("battle_admission_cleanup_abi_address", 0x080000D9),
                         ("battle_admission_cleanup_abi_address", 0x0A000000)):
            with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                validate_battle_manifest({**value, key: bad}, self.rom)

    def test_rom_and_exact_elf_marker_must_agree(self):
        symbols = self.cleanup_symbols()
        marker = "080000d8 00000004 R gMultiplayerBattleAdmissionCleanupAbiVersion\n"
        for changed in (symbols + marker, symbols.replace(marker, marker.replace("00000004", "00000008")),
                        symbols.replace(marker, marker.replace("080000d8", "080000d9")),
                        symbols.replace(marker, marker.replace("080000d8", "09000000"))):
            with self.subTest(symbols=changed), self.assertRaises(ValueError):
                self.generate(changed)
        value = self.generate(symbols)
        with self.rom.open("r+b") as rom:
            rom.seek(216)
            rom.write(struct.pack("<I", 2))
        with self.assertRaises(ValueError):
            validate_battle_manifest(value, self.rom)
        with self.assertRaises(ValueError):
            self.generate(symbols)

    def test_generator_refuses_cleanup_without_complete_dependencies(self):
        symbols = self.cleanup_symbols()
        for names in (("gMultiplayerMenuAbiVersion", "gMultiplayerMenuMailbox"),
                      ("gMultiplayerEmergencySaveAbiVersion",), ("gMultiplayerBattleResumeAbiVersion",),
                      ("gBattleStringsTable",), ("gMultiplayerBattleAbiVersion", "gMultiplayerBattleMailbox")):
            changed = "\n".join(line for line in symbols.splitlines() if not any(line.endswith(name) for name in names)) + "\n"
            with self.subTest(missing=names), self.assertRaises(ValueError):
                self.generate(changed)


class AdmissionCleanupBridgeTests(unittest.TestCase):
    lua_path = staticmethod(bridge_fixtures.BattleBridgeTests.lua_path)
    run_lua = bridge_fixtures.BattleBridgeTests.run_lua
    command = bridge_fixtures.BattleBridgeTests.command
    response = bridge_fixtures.BattleBridgeTests.response

    def fixture(self, *, cleanup=True):
        script = bridge_fixtures.BattleBridgeTests.fixture(self)
        script = script.replace("EMERALD_BRIDGE.battle_abi=1;", "EMERALD_BRIDGE.battle_abi=3;")
        script = script.replace('loadBytes(0x080000c8,string.pack("<I4",1))',
                                'loadBytes(0x080000c8,string.pack("<I4",3))')
        script = script.replace("0x31424D45,1,512", "0x31424D45,3,512")
        setup = '''
EMERALD_BRIDGE.battle_resume_abi=1;EMERALD_BRIDGE.battle_resume_abi_address=0x080000cc
EMERALD_BRIDGE.emergency_save_abi=2;EMERALD_BRIDGE.emergency_save_abi_address=0x080000d0
EMERALD_BRIDGE.menu_abi=2;EMERALD_BRIDGE.menu_abi_address=0x080000d4
EMERALD_BRIDGE.menu_address=0x02004000;EMERALD_BRIDGE.menu_size=512
loadBytes(0x080000cc,string.pack("<I4I4I4I4",1,2,2,1))
loadBytes(0x02004000,string.pack("<I4I2I2I4I4",0x31554D45,2,512,1,0)..string.rep("\\0",496))
'''
        if cleanup:
            setup += '''
EMERALD_BRIDGE.battle_execution_abi=1;EMERALD_BRIDGE.battle_admission_cleanup_abi=1
EMERALD_BRIDGE.battle_admission_cleanup_abi_address=0x080000d8
'''
        return script.replace("local cfg = assert", setup + "\nlocal cfg = assert", 1)

    @staticmethod
    def payload():
        return b"".join(UUID(int=i).bytes for i in (2, 3, 4)) + struct.pack("<I", 7) + b"x" * 32

    def test_both_native_modes_and_cleanup_controls_use_exact_channel_and_reply(self):
        for opcode in (22, 23, 24):
            for phase, source in ((2, 1), (3, 3)):
                data = self.payload()[:52] if opcode == 24 else self.payload()
                payload = bridge_fixtures.control(opcode, phase=phase, source=source, data=data)
                with self.subTest(opcode=opcode, phase=phase):
                    self.run_lua(self.fixture() + self.command(payload)
                        + f'assert(range(0x0200301c,240)==unhex("{payload.hex()}"))\n'
                        + self.response(payload) + '''
local replied=false;for _,p in ipairs(decoded()) do if p:sub(1,1)=="E" then replied=true end end
assert(replied and not stopped and #console.errors==0)
for _,address in ipairs(writes) do assert((address>=0x02001024 and address<=0x0200107c)
    or address==0x02003018 or (address>=0x0200301c and address<=0x02003108)) end
''')

    def test_legacy_build_and_malformed_commands_never_write_cleanup(self):
        valid = dict(opcode=22, phase=3, data=self.payload())
        cases = [(False, valid)]
        for change in ({"seq": 2}, {"phase": 1}, {"source": 4}, {"epoch": 6},
                       {"opcode": 25}, {"data": self.payload()[:-1]},
                       {"data": bytes(16) + self.payload()[16:]},
                       {"data": self.payload()[:16] + bytes(16) + self.payload()[32:]},
                       {"data": self.payload()[:32] + bytes(16) + self.payload()[48:]},
                       {"data": self.payload()[:48] + bytes(4) + self.payload()[52:]},
                       {"data": self.payload()[:52] + bytes(32)}, {"block": 1}):
            cases.append((True, {**valid, **change}))
        ready = {**valid, "opcode": 24, "data": self.payload()[:52]}
        cases.append((False, ready))
        for change in ({"seq": 2}, {"phase": 1}, {"source": 4}, {"epoch": 6},
                       {"data": self.payload()}, {"data": bytes(16) + self.payload()[16:52]},
                       {"data": self.payload()[:48] + bytes(4)}, {"data": self.payload()[:51]}, {"block": 1}):
            cases.append((True, {**ready, **change}))
        for enabled, args in cases:
            with self.subTest(enabled=enabled, args=args):
                self.run_lua(self.fixture(cleanup=enabled) + self.command(bridge_fixtures.control(**args)) + '''
assert(stopped and closes==1 and #console.errors==1)
assert(range(0x02003018,244)==string.rep("\\0",244))
''')

    def test_wrong_marker_or_prerequisite_fails_before_any_memory_write(self):
        for change in ("loadBytes(0x080000d8,string.pack('<I4',2))",
                       "EMERALD_BRIDGE.battle_admission_cleanup_abi_address=nil",
                       "EMERALD_BRIDGE.battle_execution_abi=nil",
                       "EMERALD_BRIDGE.menu_abi=1;loadBytes(0x080000d4,string.pack('<I4',1))",
                       "EMERALD_BRIDGE.emergency_save_abi=1;loadBytes(0x080000d0,string.pack('<I4',1))"):
            script = self.fixture().replace("local cfg = assert",
                change + "\nlocal initialized,failure=pcall(function()\nlocal cfg = assert", 1)
            script = script.replace("local function advance(count)",
                'end)\nassert(not initialized and tostring(failure):find("admission cleanup"))\nassert(#writes==0)\nlocal function advance(count)', 1)
            with self.subTest(change=change):
                self.run_lua(script)
