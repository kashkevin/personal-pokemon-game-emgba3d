"""The launcher's native-game runtime (Milestone B3): bundle format, bridge file,
arguments. The child is Python, not the game; the native game's own handling of
--bridge and --config is tested in the engine and by the native proofs."""
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from emerald_multiplayer.bridge_config import configure_native
from emerald_multiplayer.checkpoint_mirror import MirrorLease
from emerald_multiplayer.draft_runtime import DraftRuntime
from emerald_multiplayer.launcher_session import GameInstallation
from emerald_multiplayer.player_runtime import (NativeGame, PlayerRuntime, PlayerRuntimeError, RuntimeBundle,
                                                SETTINGS_NAME)
from process_fixture import direct_python
from test_cold_start import ClosedCompanion
from test_companion import make_files
from test_host_world import make_trade_files
from test_ownership_storage import source_flash

TOKEN = bytes(range(32)).hex()


def write_native_bundle(root, rom_sha256, *, mutate=None, extra=()):
    (root / "pokeemerald-mp.exe").write_bytes(b"test fixture, never executed")
    (root / "SDL2.dll").write_bytes(b"test dependency")
    names = ["pokeemerald-mp.exe", "SDL2.dll", *extra]
    manifest = dict(format="emerald-native-runtime-v1", executable="pokeemerald-mp.exe", rom_sha256=rom_sha256,
                    files={name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names})
    if mutate:
        mutate(manifest)
    raw = json.dumps(manifest).encode()
    (root / "runtime.json").write_bytes(raw)
    return RuntimeBundle(root, hashlib.sha256(raw).hexdigest())


class NativeBridgeFileTests(unittest.TestCase):
    def test_port_and_token_only_without_effect_capabilities(self):
        self.assertEqual(configure_native({}, TOKEN, 8870), f"port=8870\ntoken={TOKEN}\n")

    def test_effect_opt_ins_follow_the_manifest(self):
        module = "emerald_multiplayer.trade_effect_mailbox."
        with patch(module + "validate_effect_prepare_manifest", return_value=True), \
                patch(module + "validate_effect_save_manifest", return_value=True), \
                patch(module + "validate_effect_choice_manifest", return_value=False):
            text = configure_native({}, TOKEN, 1)
        self.assertEqual(text.splitlines()[2:], ["trade_effect_prepare=1", "trade_effect_save=1"])

    def test_invalid_token_or_port_refused(self):
        for token, port in ((TOKEN.upper(), 1), (TOKEN[:-1], 1), (TOKEN, 0), (TOKEN, 65536), (TOKEN, "1")):
            with self.subTest(token=token, port=port):
                with self.assertRaises(ValueError):
                    configure_native({}, token, port)


class NativeBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rom = "ab" * 32

    def test_native_bundle_names_its_rom_build_instead_of_a_bridge(self):
        executable, bridge = write_native_bundle(self.root, self.rom).verify()
        self.assertEqual(executable, self.root / "pokeemerald-mp.exe")
        self.assertEqual(bridge, NativeGame(self.rom))

    def test_is_native_reads_the_record_for_display_only(self):
        self.assertTrue(write_native_bundle(self.root, self.rom).is_native())
        self.assertFalse(RuntimeBundle(self.root / "missing", "00" * 32).is_native())
        (self.root / "runtime.json").write_text(json.dumps(dict(format="emerald-windows-runtime-v1")))
        self.assertFalse(RuntimeBundle(self.root, "00" * 32).is_native())

    def test_lua_bridge_never_part_of_a_native_bundle(self):
        (self.root / "bridge.lua").write_text("-- not for the native game\n")
        with self.assertRaisesRegex(PlayerRuntimeError, "bounded format"):
            write_native_bundle(self.root, self.rom, extra=("bridge.lua",)).verify()
        with self.assertRaisesRegex(PlayerRuntimeError, "unlisted"):
            write_native_bundle(self.root, self.rom).verify()

    def test_malformed_native_records_refused(self):
        mutations = [
            lambda m: m.update(rom_sha256="AB" * 32),
            lambda m: m.update(rom_sha256=None),
            lambda m: m.pop("rom_sha256"),
            lambda m: m.update(bridge="bridge.lua"),
            lambda m: m.update(executable="SDL2.dll"),
            lambda m: m.update(format="emerald-native-runtime-v2"),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                with self.assertRaises(PlayerRuntimeError):
                    write_native_bundle(self.root, self.rom, mutate=mutate).verify()


class NativePlayerRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.c = ClosedCompanion(self.root)
        self.c.config.rom_path, self.c.config.manifest_path = make_files(self.root)
        manifest = json.loads(self.c.config.manifest_path.read_text())
        self.identity = patch("emerald_multiplayer.player_runtime.verify_rom_manifest",
                              return_value=(self.c.config.build_id, manifest))
        self.identity.start()
        self.c.config.token = bytes(range(32))
        self.c.ipc_address = ("127.0.0.1", 8870)
        (self.root / "bundle").mkdir()
        self.bundle = write_native_bundle(self.root / "bundle", self.c.config.build_id)
        self.save = self.root / "character.sav"
        self.launches = self.root / "launcher" / "launches"
        self.runtime = PlayerRuntime(self.c, self.bundle, self.root / "private", self.save, launch_root=self.launches)
        self.real_spawn = asyncio.create_subprocess_exec
        self.children, self.arguments = [], []

    async def asyncTearDown(self):
        for child in self.children:
            if child.returncode is None:
                child.kill()
            await child.wait()
        self.identity.stop()
        self.c.close()
        self.temp.cleanup()

    async def spawn(self, *args, **kwargs):
        self.arguments.append((args, kwargs))
        child = await self.real_spawn(direct_python(), "-c", "import time; time.sleep(60)", **kwargs)
        self.children.append(child)
        return child

    async def test_native_game_gets_its_bridge_file_save_and_settings(self):
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
            async with self.runtime.open() as game:
                args, options = self.arguments[0]
                self.assertEqual(args[0], str(self.bundle.directory.resolve() / "pokeemerald-mp.exe"))
                self.assertEqual(args[1::2], ("--save", "--bridge", "--config"))
                self.assertEqual(args[2], str(self.save.resolve()))
                bridge = Path(args[4])
                self.assertEqual(bridge.name, "bridge.txt")
                self.assertEqual(bridge.parent, options["cwd"])
                self.assertEqual(options["cwd"].parent, self.launches.resolve())
                self.assertEqual(bridge.read_text(), f"port=8870\ntoken={TOKEN}\n")
                self.assertEqual(Path(args[6]), self.launches.resolve().parent / SETTINGS_NAME)
                self.assertNotIn(str(self.c.config.rom_path), args)
                self.assertNotIn("shell", options)
                game.process.terminate()
                await game.wait()
        with MirrorLease(self.save):
            pass

    async def test_hosting_runtime_tells_the_game_its_role(self):
        for role in ("host", "join"):
            runtime = PlayerRuntime(self.c, self.bundle, self.root / "private", self.save, launch_root=self.launches,
                                    role=role)
            self.arguments.clear()
            with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
                async with runtime.open() as game:
                    args, _ = self.arguments[0]
                    # An argument (older games ignore it); the bridge file keeps only what every game reads.
                    self.assertEqual(args[-2:], ("--link-role", role))
                    self.assertEqual(Path(args[4]).read_text(), f"port=8870\ntoken={TOKEN}\n")
                    game.process.terminate()
                    await game.wait()
        for bad in ("HOST", "server", "", "host --bridge x"):
            with self.subTest(role=bad), self.assertRaises(PlayerRuntimeError):
                PlayerRuntime(self.c, self.bundle, self.root / "private", self.save, launch_root=self.launches, role=bad)

    async def test_native_game_of_another_rom_build_never_starts(self):
        (self.root / "other").mkdir()
        bundle = write_native_bundle(self.root / "other", "cd" * 32)
        runtime = PlayerRuntime(self.c, bundle, self.root / "private", self.save, launch_root=self.launches)
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
            with self.assertRaises(PlayerRuntimeError) as caught:
                async with runtime.open():
                    self.fail("a native game of another build may not launch")
        self.assertEqual(caught.exception.code, "game_changed")
        self.assertEqual(self.arguments, [])
        # Refused before closed-game recovery could install anything.
        self.assertFalse(self.save.exists())
        with MirrorLease(self.save):
            pass


class NativeDraftTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        rom, manifest = make_trade_files(self.root)
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        (self.root / "bundle").mkdir()
        self.bundle = write_native_bundle(self.root / "bundle", digest(rom))
        self.installation = GameInstallation(rom, manifest, digest(rom), digest(manifest), self.bundle)
        self.runtime = DraftRuntime(self.installation, self.root / "private")
        self.real_spawn = asyncio.create_subprocess_exec
        self.children, self.calls = [], []

    async def asyncTearDown(self):
        for process in self.children:
            if process.returncode is None:
                process.kill()
            await process.wait()

    async def spawn(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        child = await self.real_spawn(direct_python(), "-c", "pass", **kwargs)
        self.children.append(child)
        Path(args[2]).write_bytes(source_flash())
        return child

    async def test_new_character_starts_the_native_game_without_a_bridge(self):
        with patch("emerald_multiplayer.draft_runtime.asyncio.create_subprocess_exec", self.spawn):
            async with self.runtime.open() as game:
                self.assertEqual(await game.wait(), 0)
                self.runtime.finish()
        args, options = self.calls[0]
        self.assertEqual(args[1:5:2], ("--save", "--config"))
        self.assertEqual(args[2], str(self.runtime.save_path))
        self.assertEqual(Path(args[4]), (self.root / "private").resolve() / SETTINGS_NAME)
        self.assertEqual(args[5:], ("--setup",))   # the game shows "character setup, offline", not "not linked"
        self.assertNotIn("--bridge", args)
        self.assertFalse((self.runtime.directory / "draft.lua").exists())

    async def test_native_game_of_another_rom_build_refused(self):
        (self.root / "other").mkdir()
        bundle = write_native_bundle(self.root / "other", "cd" * 32)
        installation = GameInstallation(self.installation.rom_path, self.installation.manifest_path,
                                        self.installation.rom_sha256, self.installation.manifest_sha256, bundle)
        runtime = DraftRuntime(installation, self.root / "private")
        with patch("emerald_multiplayer.draft_runtime.asyncio.create_subprocess_exec", self.spawn):
            with self.assertRaises(Exception) as caught:
                async with runtime.open():
                    self.fail("a native game of another build may not start a draft")
        self.assertEqual(getattr(caught.exception, "code", None), "installation_changed")
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
