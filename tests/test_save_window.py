"""Optional sector reads retain the save binding and bounded transport."""
import asyncio
from dataclasses import replace
import hashlib
import json
import struct
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid
import zlib

from emerald_multiplayer.bridge_protocol import BridgeError, encode_packet, read_packet
from emerald_multiplayer.save_mailbox import Opcode, Status, capability_packet as save_capability
from emerald_multiplayer.save_window import FIELDS, WINDOW_FRAME_SIZE, capability_packet, parse_window_packet, validate_window_manifest
from test_save_mailbox import control
import test_save_manifest as manifests
import test_companion_battle as companion_fixture
from test_companion import wait_until
import test_live_bridge as lua_fixture
from test_live_checkpoint import FakeCompanion
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator, LiveSaveError


class WindowCodecTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_window_and_fragmented_bounded_frame(self):
        data = bytes(range(256)) * 16
        response = control(opcode=Opcode.READ_WINDOW, data=struct.pack("<I", zlib.crc32(data)))
        packet = b"F" + response.pack() + data
        self.assertEqual(parse_window_packet(packet), (response, data))
        with self.assertRaises(BridgeError):
            encode_packet(packet)
        reader = asyncio.StreamReader()
        task = asyncio.create_task(read_packet(reader, maximum=WINDOW_FRAME_SIZE))
        frame = encode_packet(packet, maximum=WINDOW_FRAME_SIZE)
        for offset in range(0, len(frame), 53):
            reader.feed_data(frame[offset:offset+53])
            await asyncio.sleep(0)
        self.assertEqual(await task, packet)

    async def test_bad_crc_size_kind_padding_alignment_and_upper_bound(self):
        data = bytes(4096)
        good = control(opcode=Opcode.READ_WINDOW, data=struct.pack("<I", zlib.crc32(data)))
        for payload in (b"F" + good.pack() + data[:-1], b"F" + good.pack() + data + b"x",
                        b"R" + good.pack() + data, b"F" + good.pack() + b"x" + data[1:],
                        b"F" + replace(good, opcode=Opcode.END).pack() + data):
            with self.subTest(length=len(payload)), self.assertRaises(ValueError):
                parse_window_packet(payload)
        for offset in (128, 4095, 131072):
            with self.assertRaises(ValueError):
                control(opcode=Opcode.READ_WINDOW, offset=offset).validate_command()
        control(opcode=Opcode.READ_WINDOW, offset=126976).validate_command()
        reader = asyncio.StreamReader()
        reader.feed_data(struct.pack("!I", WINDOW_FRAME_SIZE+1))
        with self.assertRaises(BridgeError):
            await read_packet(reader, maximum=WINDOW_FRAME_SIZE)


class WindowManifestTests(unittest.TestCase):
    tearDown = manifests.SaveManifestTests.tearDown
    generate = manifests.SaveManifestTests.generate
    configure = manifests.SaveManifestTests.configure

    def setUp(self):
        manifests.SaveManifestTests.setUp(self)
        self.window_symbols = ("02021000 00000200 B gMultiplayerSaveMailbox\n"
                        "080000c0 00000004 R gMultiplayerOwnershipAbi\n"
                        "080000c4 00000004 R gMultiplayerTradeAbiVersion\n"
                        "080000c8 00000004 R gMultiplayerSaveWindowAbiVersion\n"
                        "02023000 00001000 B gSaveDataBuffer\n")
        with self.rom.open("r+b") as stream:
            stream.seek(192)
            stream.write(b"\x01\0\0\0" * 3)

    def test_exact_elf_window_and_optional_configuration(self):
        manifest = self.generate(self.window_symbols)
        self.assertTrue(validate_window_manifest(manifest, self.rom))
        self.assertIn("window_address=33697792, window_size=4096", self.configure(manifest))
        self.assertFalse(validate_window_manifest({}))

    def test_missing_fields_overlaps_false_markers_and_bad_allocations(self):
        manifest = self.generate(self.window_symbols)
        for key in FIELDS | {"save_profile", "trade_abi_version", "mailbox_address"}:
            bad = dict(manifest); del bad[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_window_manifest(bad, self.rom)
        for changes in ({"save_window_abi_version": True}, {"save_window_size": 4092},
                        {"save_window_address": 0x0203F004}, {"save_window_address": 0x02023001},
                        {"save_window_address": 0x02020000}, {"save_window_address": 0x02021000},
                        {"battle_mailbox_address": 0x02023800}, {"save_window_abi_address": 0x080000CC}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_window_manifest({**manifest, **changes}, self.rom)
        for symbols in (self.window_symbols.replace("00001000", "00000FFF"),
                        self.window_symbols.replace("02023000", "02021000"),
                        self.window_symbols + "02024000 00001000 B gSaveDataBuffer\n"):
            with self.assertRaises(ValueError):
                self.generate(symbols)

    def test_import_window_marker_comes_from_the_native_executable_beside_the_read_window(self):
        def generate_native(symbols, native):
            with patch.object(manifests.generator.subprocess, "check_output", return_value=self.symbols + symbols):
                return manifests.generator.generate(self.rom, self.elf, "fixture-nm", "b" * 40, native_symbols=native)
        native = "00bd27a0 00000004 R gMultiplayerSaveImportWindowAbiVersion\n"
        self.assertNotIn("save_import_window_abi_version", self.generate(self.window_symbols))   # never from the GBA ELF
        self.assertEqual(generate_native(self.window_symbols, native)["save_import_window_abi_version"], 1)
        mingw = "00bd27a0 R _gMultiplayerSaveImportWindowAbiVersion\n"   # the Windows game's nm prints no size
        self.assertEqual(generate_native(self.window_symbols, mingw)["save_import_window_abi_version"], 1)
        no_read_window = self.window_symbols.replace("080000c8 00000004 R gMultiplayerSaveWindowAbiVersion\n", "")
        for symbols, marker in ((no_read_window, native),
                                (self.window_symbols, "00bd27a0 00000008 R gMultiplayerSaveImportWindowAbiVersion\n"),
                                (self.window_symbols, native + native)):
            with self.subTest(marker=marker), self.assertRaises(ValueError):
                generate_native(symbols, marker)

    def test_the_companion_takes_the_import_window_only_with_the_read_window(self):
        for window, value, expected in ((True, None, 0), (True, 1, 1), (True, 2, 0), (True, True, 0), (False, 1, 0)):
            with self.subTest(window=window, value=value), tempfile.TemporaryDirectory() as directory:
                rom, manifest = companion_fixture.make_files(directory)
                data = json.loads(manifest.read_text())
                raw = bytearray(rom.read_bytes()); raw[192:208] = b"\x01\0\0\0" * 4; rom.write_bytes(raw)
                data.update(rom_sha256=hashlib.sha256(raw).hexdigest(), rom_crc32=f"{zlib.crc32(raw):08x}",
                            save_abi_version=1, save_mailbox_size=512, save_mailbox_address=0x02021000,
                            ownership_abi_version=1, save_profile="rhh-1.17.1-bb1093-ownership-v1",
                            trade_abi_version=1, trade_abi_address=0x080000C4)
                if window:
                    data.update(save_window_abi_version=1, save_window_abi_address=0x080000CC,
                                save_window_address=0x02023000, save_window_size=4096)
                if value is not None:
                    data["save_import_window_abi_version"] = value
                manifest.write_text(json.dumps(data))
                config = companion_fixture.CompanionConfig(rom, manifest, str(uuid.uuid4()), "Alice",
                                                           bytes(32), ipc_port=0)
                self.assertEqual(config.save_import_window_abi_version, expected)


class CompanionWindowTests(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = companion_fixture.CompanionBattleTests.asyncTearDown

    async def asyncSetUp(self):
        original = companion_fixture.make_files
        def files(root):
            rom, manifest = original(root)
            raw = bytearray(rom.read_bytes()); raw[204:208] = b"\x01\0\0\0"
            rom.write_bytes(raw)
            value = json.loads(manifest.read_text())
            value.update(save_window_abi_version=1, save_window_abi_address=0x080000CC,
                         save_window_address=0x02023000, save_window_size=4096)
            manifest.write_text(json.dumps(value))
            return rom, manifest
        with patch.object(companion_fixture, "make_files", files):
            await companion_fixture.CompanionBattleTests.asyncSetUp(self)
        self.bridge.writer.write(encode_packet(save_capability()) + encode_packet(capability_packet()))
        await self.bridge.writer.drain()
        await wait_until(lambda: self.c._bridge.window_capable)

    def start(self, **changes):
        cmd = control(incarnation=self.c.save_incarnation, session_epoch=self.c.session_epoch,
                      opcode=Opcode.READ_WINDOW, **changes)
        task = asyncio.create_task(self.c.save_window_rpc(cmd, timeout=2))
        self.tasks.append(task)
        return cmd, task

    async def next_command(self):
        async with asyncio.timeout(3):
            while True:
                packet = await read_packet(self.bridge.reader)
                if packet[:1] == b"C":
                    return packet[1:]
                self.assertEqual(packet[:1], b"S")

    async def reply(self, response, data=None):
        packet = b"R" + response.pack() if data is None else b"F" + response.pack() + data
        frame = encode_packet(packet, maximum=WINDOW_FRAME_SIZE)
        for offset in range(0, len(frame), 97):
            self.bridge.writer.write(frame[offset:offset+97])
            await self.bridge.writer.drain()
            await asyncio.sleep(0)

    async def test_exact_window_one_pending_and_ordinary_error_response(self):
        cmd, task = self.start()
        self.assertEqual(await self.next_command(), cmd.pack())
        with self.assertRaises(ValueError):
            await self.c.save_window_rpc(replace(cmd, sequence=2))
        data = bytes(range(256))*16
        response = replace(cmd, data=struct.pack("<I", zlib.crc32(data)))
        await self.reply(response, data)
        self.assertEqual(await task, (response, data))
        cmd, task = self.start(sequence=2)
        await self.next_command()
        error = replace(cmd, status=Status.ORDER)
        await self.reply(error)
        self.assertEqual(await task, (error, b""))

    async def test_wrong_offset_closes_without_resolving_bytes(self):
        cmd, task = self.start()
        await self.next_command()
        data = bytes(4096)
        await self.reply(replace(cmd, offset=4096, data=struct.pack("<I", zlib.crc32(data))), data)
        with self.assertRaises(ConnectionError):
            await task

    async def test_ack_without_bytes_closes_instead_of_claiming_success(self):
        cmd, task = self.start()
        await self.next_command()
        await self.reply(replace(cmd, data=bytes(4)))
        with self.assertRaises(ConnectionError):
            await task

    async def test_pending_trade_and_missing_capability_fence_window(self):
        cmd = control(incarnation=self.c.save_incarnation, session_epoch=self.c.session_epoch, opcode=Opcode.READ_WINDOW)
        self.c._bridge.window_capable = False
        with self.assertRaises(ValueError):
            await self.c.save_window_rpc(cmd)
        self.c._bridge.window_capable = True
        pending = self.root / "pending-trade.json"; pending.write_text("retained intent")
        self.c._live_trade_pending_path = pending
        with self.assertRaisesRegex(ValueError, "pending trade recovery"):
            await self.c.save_window_rpc(cmd)
        self.assertFalse(self.c._save_pending)


class LuaWindowTests(unittest.TestCase):
    run_lua = lua_fixture.LuaBridgeTests.run_lua
    lua_path = staticmethod(lua_fixture.LuaBridgeTests.lua_path)

    def fixture(self):
        source = lua_fixture.LuaBridgeTests.fixture(self, live=True, trade=True)
        extra = """
EMERALD_BRIDGE.window_abi=1;EMERALD_BRIDGE.window_abi_address=0x080000c8
EMERALD_BRIDGE.window_address=0x02003000;EMERALD_BRIDGE.window_size=4096
loadBytes(0x080000c8,string.pack('<I4',1))
"""
        return source.replace("-- Project-owned presence/live-save bridge", extra + "-- Project-owned presence/live-save bridge", 1).replace(
            "assert(size>=1 and size<=256)", "assert(size>=1 and size<=4337)").replace(
            'assert(#wire-offset+1<=260,"unbounded partial frame")', 'assert(#wire-offset+1<=4341,"unbounded partial frame")')

    def test_window_is_read_only_and_full_bytes_match_after_partial_socket_sends(self):
        cmd = control(opcode=Opcode.READ_WINDOW)
        data = bytes(range(256))*16
        response = replace(cmd, data=struct.pack("<I", zlib.crc32(data)))
        self.run_lua(self.fixture() + f'''
advance(120);inbox=packet(unhex("{(b'C'+cmd.pack()).hex()}"));advance(30)
assert(range(0x0200201c,240)==unhex("{cmd.pack().hex()}"))
loadBytes(0x0200200c,string.pack("<I4",2));loadBytes(0x02003000,unhex("{data.hex()}"))
loadBytes(0x02002110,unhex("{response.pack().hex()}"));loadBytes(0x0200210c,string.pack("<I4",2))
advance(1800)
local found=false
for _,p in ipairs(decoded()) do if p:sub(1,1)=="F" then
 assert(p==unhex("{(b'F'+response.pack()+data).hex()}"));found=true end end
assert(found);assert(#console.errors==0)
''')

    def test_changed_window_closes_without_returning_inconsistent_data(self):
        cmd = control(opcode=Opcode.READ_WINDOW)
        response = replace(cmd, data=struct.pack("<I", zlib.crc32(bytes(4096))))
        self.run_lua(self.fixture() + f'''
advance(120);inbox=packet(unhex("{(b'C'+cmd.pack()).hex()}"));advance(30)
loadBytes(0x0200200c,string.pack("<I4",2));loadBytes(0x02003000,"x")
loadBytes(0x02002110,unhex("{response.pack().hex()}"));loadBytes(0x0200210c,string.pack("<I4",2))
advance(3);assert(closes==1);assert(console.errors[1]:find("save window changed"))
''')


class WindowCompanionFixture(FakeCompanion):
    def __init__(self, directory):
        super().__init__(directory)
        self.config.save_window_enabled = True
        self._bridge = SimpleNamespace(window_capable=True)
        self.bad_window = False

    async def save_window_rpc(self, command, *, timeout=12):
        command.validate_command()
        if self.mode not in {"export", "committed"} or command.request_id != self.operation:
            raise AssertionError("window outside held snapshot")
        self.commands.append(command)
        chunk = self.rom_flash[command.offset:command.offset+4096]
        response = replace(command, data=struct.pack("<I", zlib.crc32(chunk)))
        parsed = parse_window_packet(b"F" + response.pack() + chunk)
        return (parsed[0], b"x" + chunk[1:]) if self.bad_window else parsed


class WindowCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.c = WindowCompanionFixture(Path(self.temp.name))
        self.save = LiveCheckpointCoordinator(self.c, Path(self.temp.name)/"private")
        self.c.pending_journal = self.save.pending_path

    async def asyncTearDown(self):
        self.c.close()
        self.temp.cleanup()

    async def test_complete_canonical_export_uses_32_windows_and_same_crc_end(self):
        result = await self.save.checkpoint(expected_revision=1)
        self.assertEqual(result.metadata["revision"], 2)
        self.assertEqual(self.c.head().payload, self.c.rom_flash)
        self.assertEqual([c.offset for c in self.c.commands if c.opcode == Opcode.READ_WINDOW], list(range(0,131072,4096)))
        self.assertFalse(any(c.opcode == Opcode.READ for c in self.c.commands))
        self.assertEqual(self.c.commands[-1].opcode, Opcode.END)
        self.assertFalse(self.save.pending_path.exists())

    async def test_bad_readback_never_uploads_and_lost_commit_retains_same_journal(self):
        self.c.bad_window = True
        with self.assertRaises(LiveSaveError):
            await self.save.checkpoint(expected_revision=1)
        self.assertEqual(self.c.head().revision, 1)
        self.assertFalse(self.save.pending_path.exists())
        self.c.bad_window = False
        self.c.lose_commit_ack = True
        with self.assertRaises(asyncio.TimeoutError):
            await self.save.checkpoint(expected_revision=1)
        self.assertEqual(self.c.head().revision, 2)
        intent = json.loads(self.save.pending_path.read_text())
        self.assertEqual(intent["expected_revision"], 1)
        self.assertEqual((self.save.directory/(intent["operation_id"]+".flash")).read_bytes(), self.c.rom_flash)
