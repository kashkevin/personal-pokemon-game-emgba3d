from dataclasses import replace
import hashlib
import json
import secrets
import socket
import struct
import tempfile
import unittest
from uuid import UUID
import zlib

from emerald_multiplayer.bridge_protocol import encode_packet
from emerald_multiplayer.emergency_protocol import EmergencyHold, capability_packet
from emerald_multiplayer.companion import Companion, CompanionConfig
from emerald_multiplayer.save_mailbox import (FLASH_SIZE, Opcode, SaveMailboxError, State, Status,
                                             capability_packet as save_capability, command_packet, response_packet)
from test_companion import BinaryBridge, wait_until
from test_host_world import make_trade_files
import test_live_bridge as lua_fixture
from test_save_mailbox import control
import test_save_manifest as manifest_fixture


class EmergencyCodecTests(unittest.TestCase):
    def query(self, *, flags=3, state=State.EXPORTING, offset=4096, crc=123,
              failure=Status.OK, epoch=2, incarnation=1, revision=4, request=None):
        request = request if request is not None else UUID(control().request_id).bytes
        return control(opcode=Opcode.QUERY_EMERGENCY, session_epoch=2, incarnation=1,
                       revision=4, offset=min(offset, FLASH_SIZE), data=struct.pack(
            "<II16sIIIIII", flags, state, request, epoch, incarnation, revision, offset, crc, failure))

    def test_observation_distinguishes_unsaved_stream_and_preserved(self):
        for response, expected in ((self.query(), (True, False)),
                (self.query(flags=1, state=9, offset=0, crc=0, failure=2), (False, False)),
                (self.query(flags=7, state=10, offset=FLASH_SIZE), (True, True))):
            held = EmergencyHold.parse(response)
            self.assertTrue(held.active)
            self.assertEqual((held.valid_flash, held.preserved), expected)
            self.assertEqual(held.operation_id, control().request_id)

    def test_inactive_observation_cannot_claim_an_emergency_state_or_bytes(self):
        empty = dict(flags=0, state=State.BOUND, offset=0, crc=0, epoch=0,
                     incarnation=0, revision=0, request=bytes(16))
        self.assertFalse(EmergencyHold.parse(self.query(**empty)).active)
        for update in ({"state": 9}, {"state": 10}, {"crc": 1}, {"epoch": 1},
                       {"request": UUID(control().request_id).bytes}):
            with self.subTest(update=update), self.assertRaises(SaveMailboxError):
                EmergencyHold.parse(self.query(**{**empty, **update}))

    def test_malformed_active_observations_fail_closed(self):
        for update in ({"flags": 2}, {"flags": 5}, {"flags": 8}, {"state": 8},
                {"epoch": 0}, {"incarnation": 0}, {"revision": 0}, {"request": bytes(16)},
                {"offset": 1}, {"offset": FLASH_SIZE + 128}, {"failure": 2},
                {"flags": 7, "state": 10, "offset": 4096}, {"failure": 14}):
            with self.subTest(update=update), self.assertRaises(SaveMailboxError):
                EmergencyHold.parse(self.query(**update))

    def test_held_payload_must_match_each_correlated_envelope_field(self):
        response = self.query()
        for update in ({"request_id": str(UUID(int=2))}, {"session_epoch": 3},
                       {"incarnation": 2}, {"revision": 5}, {"offset": 128}):
            with self.subTest(update=update), self.assertRaises(SaveMailboxError):
                EmergencyHold.parse(replace(response, **update))

    def test_emergency_controls_cannot_use_zero_revision_partial_end_or_payload(self):
        for opcode, offset in ((Opcode.BEGIN_EMERGENCY_EXPORT, 0),
                               (Opcode.PRESERVE_EMERGENCY, FLASH_SIZE), (Opcode.QUERY_EMERGENCY, 0)):
            valid = control(opcode=opcode, offset=offset, revision=2)
            self.assertEqual(valid.validate_command(), valid)
            for update in ({"offset": offset + 1 if offset == 0 else 0},
                           {"total_size": 0}, {"data": b"x"}):
                with self.subTest(opcode=opcode, update=update), self.assertRaises(SaveMailboxError):
                    replace(valid, **update).validate_command()
            if opcode != Opcode.QUERY_EMERGENCY:
                with self.assertRaises(SaveMailboxError):
                    replace(valid, revision=0).validate_command()


class EmergencyManifestTests(unittest.TestCase):
    setUp = manifest_fixture.SaveManifestTests.setUp
    tearDown = manifest_fixture.SaveManifestTests.tearDown
    generate = manifest_fixture.SaveManifestTests.generate
    configure = manifest_fixture.SaveManifestTests.configure
    verify = manifest_fixture.SaveManifestTests.verify

    def symbols_with_emergency(self):
        with self.rom.open("r+b") as source:
            source.seek(192)
            source.write(b"\x01\0\0\0" * 3)
        return ("02021000 00000200 B gMultiplayerSaveMailbox\n"
                "080000c0 00000004 R gMultiplayerOwnershipAbi\n"
                "080000c4 00000004 R gMultiplayerTradeAbiVersion\n"
                "080000c8 00000004 R gMultiplayerEmergencySaveAbiVersion\n")

    def test_generation_rom_marker_and_configuration_are_optional_and_exact(self):
        old = self.generate()
        self.assertNotIn("emergency_save_abi", self.configure(old))
        value = self.generate(self.symbols_with_emergency())
        self.verify(value)
        self.assertEqual(value["emergency_save_abi_address"], 0x080000C8)
        self.assertIn("emergency_save_abi=1", self.configure(value))

    def test_promotion_abi_two_is_compiler_marked_and_capability_distinct(self):
        symbols = self.symbols_with_emergency()
        with self.rom.open("r+b") as source:
            source.seek(200)
            source.write(b"\x02\0\0\0")
        value = self.generate(symbols)
        self.verify(value)
        self.assertEqual(value["emergency_save_abi_version"], 2)
        self.assertIn("emergency_save_abi=2", self.configure(value))
        self.assertEqual(capability_packet(2), b"Z" + struct.pack("<HHHH", 2, 19, 22, 10))
        with self.assertRaises(ValueError):
            self.verify({**value, "emergency_save_abi_version": 1})

    def test_incomplete_wrong_type_or_out_of_rom_marker_is_refused(self):
        value = self.generate(self.symbols_with_emergency())
        for key in ("emergency_save_abi_version", "emergency_save_abi_address", "trade_abi_version"):
            changed = dict(value)
            del changed[key]
            for operation in (self.verify, self.configure):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    operation(changed)
        for changed in ({"emergency_save_abi_version": True}, {"emergency_save_abi_version": 3},
                        {"emergency_save_abi_address": True}, {"emergency_save_abi_address": 0x080000C9},
                        {"emergency_save_abi_address": 0x09000000}):
            for operation in (self.verify, self.configure):
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    operation({**value, **changed})
        with self.assertRaises(ValueError):
            self.verify({**value, "emergency_save_abi_address": 0x080000CC})

    def test_duplicate_symbol_or_wrong_size_or_marker_cannot_enable_feature(self):
        symbols = self.symbols_with_emergency()
        for changed in (symbols + "080000c8 00000004 R gMultiplayerEmergencySaveAbiVersion\n",
                        symbols.replace("080000c8 00000004", "080000c8 00000008"),
                        symbols.replace("080000c8", "080000cc")):
            with self.assertRaises(ValueError):
                self.generate(changed)


class EmergencyLuaTests(unittest.TestCase):
    fixture = lua_fixture.LuaBridgeTests.fixture
    run_lua = lua_fixture.LuaBridgeTests.run_lua
    lua_path = staticmethod(lua_fixture.LuaBridgeTests.lua_path)

    def test_promotion_requires_abi_two_and_can_replace_a_lost_ordinary_reply(self):
        ordinary = control(opcode=Opcode.BEGIN_EXPORT, revision=2, sequence=2)
        promote = replace(ordinary, opcode=Opcode.PROMOTE_EMERGENCY_EXPORT, sequence=3)
        for version in (1, 2):
            script = self.fixture(live=True, trade=True, emergency=True)
            if version == 2:
                script = script.replace("EMERALD_BRIDGE.emergency_save_abi=1;", "EMERALD_BRIDGE.emergency_save_abi=2;")
                script = script.replace("loadBytes(0x080000c8,string.pack('<I4',1))", "loadBytes(0x080000c8,string.pack('<I4',2))")
            script += f'advance(80);inbox=unhex("{encode_packet(command_packet(ordinary)).hex()}");advance(80)\n'
            script += f'inbox=unhex("{encode_packet(command_packet(promote)).hex()}");advance(80)\n'
            script += (f'assert(range(0x0200201c,240)==unhex("{promote.pack().hex()}"));assert(#console.errors==0)\n'
                       if version == 2 else 'assert(#console.errors>0)\n')
            self.run_lua(script)

    def test_capability_and_begin_require_the_explicit_rom_marker(self):
        begin = control(opcode=Opcode.BEGIN_EMERGENCY_EXPORT, revision=2)
        for enabled in (False, True):
            script = self.fixture(live=True, trade=True, emergency=enabled)
            script += "advance(80)\nlocal caps=0;for _,p in ipairs(decoded()) do if p:sub(1,1)=='Z' then caps=caps+1 end end\n"
            script += f"assert(caps=={1 if enabled else 0})\n"
            script += f'inbox=unhex("{encode_packet(command_packet(begin)).hex()}");advance(80)\n'
            script += (f'assert(range(0x0200201c,240)==unhex("{begin.pack().hex()}"));assert(#console.errors==0)\n'
                       if enabled else 'assert(#console.errors>0)\n')
            self.run_lua(script)

    def test_emergency_held_states_keep_bridge_live_and_query_responses_correlate(self):
        query = control(opcode=Opcode.QUERY_EMERGENCY, sequence=3, revision=2)
        data = struct.pack("<II16sIIIIII", 7, 10, UUID(query.request_id).bytes,
                           query.session_epoch, query.incarnation, 2, FLASH_SIZE, 123, 0)
        response = replace(query, data=data, offset=FLASH_SIZE)
        script = self.fixture(live=True, trade=True, emergency=True)
        script += 'loadBytes(0x0200200c,string.pack("<I4",10));advance(80)\n'
        script += f'inbox=unhex("{encode_packet(command_packet(query)).hex()}");advance(80)\n'
        script += f'loadBytes(0x02002110,unhex("{response.pack().hex()}"));loadBytes(0x0200210c,string.pack("<I4",2));advance(100)\n'
        script += f'local found=false;for _,p in ipairs(decoded()) do if p==unhex("{response_packet(response).hex()}") then found=true end end\n'
        script += 'assert(found and #console.errors==0 and connects==1)\n'
        self.run_lua(script)

    def test_emergency_capability_does_not_implicitly_enable_read_window(self):
        read = control(opcode=Opcode.READ_WINDOW)
        script = self.fixture(live=True, trade=True, emergency=True)
        script += f'advance(80);inbox=unhex("{encode_packet(command_packet(read)).hex()}");advance(80);assert(#console.errors>0)\n'
        self.run_lua(script)


class EmergencyCapabilityTests(unittest.IsolatedAsyncioTestCase):
    async def check_capability(self, *, enabled, packet):
        with tempfile.TemporaryDirectory() as directory, socket.socket() as unused:
            # Hold a non-listening private ephemeral port; no other host is contacted.
            unused.bind(("127.0.0.1", 0))
            rom, manifest = make_trade_files(directory)
            if enabled:
                raw = bytearray(rom.read_bytes())
                raw[200:204] = b"\x01\0\0\0"
                rom.write_bytes(raw)
                value = json.loads(manifest.read_text())
                value.update(rom_sha256=hashlib.sha256(raw).hexdigest(), rom_crc32=f"{zlib.crc32(raw):08x}",
                             emergency_save_abi_version=1, emergency_save_abi_address=0x080000C8)
                manifest.write_text(json.dumps(value))
            companion = Companion(CompanionConfig(rom, manifest, str(UUID(int=3)), "Fixture", secrets.token_bytes(32),
                                  server_port=unused.getsockname()[1], ipc_port=0))
            bridge = None
            try:
                await companion.start()
                bridge = await BinaryBridge.connect(companion)
                bridge.writer.write(encode_packet(save_capability()))
                await bridge.writer.drain()
                await wait_until(lambda: companion._bridge is not None and companion._bridge.save_capable)
                bridge.writer.write(encode_packet(packet))
                await bridge.writer.drain()
                if enabled and packet == capability_packet():
                    await wait_until(lambda: companion._bridge is not None and companion._bridge.emergency_save_capable)
                    self.assertFalse(companion.connected)
                    with self.assertRaisesRegex(ValueError, "dedicated preservation controller"):
                        await companion.save_rpc(control(opcode=Opcode.BEGIN_EMERGENCY_EXPORT, revision=1))
                    self.assertFalse(companion._save_pending)
                else:
                    await wait_until(lambda: companion._bridge is None)
            finally:
                if bridge is not None:
                    await bridge.close()
                await companion.close()

    async def test_verified_advertisement_grants_no_disconnected_export_authority(self):
        await self.check_capability(enabled=True, packet=capability_packet())

    async def test_unpinned_or_altered_capability_closes_only_the_bridge(self):
        await self.check_capability(enabled=False, packet=capability_packet())
        await self.check_capability(enabled=True, packet=b"Z" + struct.pack("<HHHH", 2, 19, 21, 10))


if __name__ == "__main__":
    unittest.main()
