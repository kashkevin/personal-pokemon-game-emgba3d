"""Real child-process lifetime tests; the child is Python, not game acceptance."""
import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path, PureWindowsPath
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from emerald_multiplayer.checkpoint_mirror import MirrorError, MirrorLease
from emerald_multiplayer.player_runtime import PlayerRuntime, PlayerRuntimeError, RuntimeBundle, _check_native_paths
from test_cold_start import ClosedCompanion
from test_companion import make_files
from process_fixture import direct_python


def write_bundle(root, *, mutate=None):
    (root / "game.exe").write_bytes(b"test fixture, never executed")
    (root / "bridge.lua").write_text("-- fixture bridge\n")
    (root / "SDL2.dll").write_bytes(b"test dependency")
    manifest = dict(format="emerald-windows-runtime-v1", executable="game.exe", bridge="bridge.lua",
        files={name: hashlib.sha256((root / name).read_bytes()).hexdigest()
               for name in ("game.exe", "bridge.lua", "SDL2.dll")})
    if mutate:
        mutate(manifest)
    raw = json.dumps(manifest).encode()
    (root / "runtime.json").write_bytes(raw)
    return RuntimeBundle(root, hashlib.sha256(raw).hexdigest())


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bundle = write_bundle(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_manifest_and_components_rechecked_each_use(self):
        executable, bridge = self.bundle.verify()
        self.assertEqual(executable, self.root / "game.exe")
        self.assertEqual(bridge, "-- fixture bridge\n")
        (self.root / "SDL2.dll").write_bytes(b"changed")
        with self.assertRaisesRegex(PlayerRuntimeError, "pinned hash"):
            self.bundle.verify()

    def test_manifest_pin_and_duplicate_fields(self):
        with self.assertRaises(PlayerRuntimeError):
            replace(self.bundle, manifest_sha256="0" * 64).verify()
        raw = b'{"format": "a", "format": "b"}'
        (self.root / "runtime.json").write_bytes(raw)
        with self.assertRaisesRegex(PlayerRuntimeError, "bounded format"):
            replace(self.bundle, manifest_sha256=hashlib.sha256(raw).hexdigest()).verify()

    def test_no_path_escape_case_collision_or_non_executable(self):
        mutations = [
            lambda m: m["files"].update({"../outside.dll": "0" * 64}),
            lambda m: m["files"].update({"GAME.exe": "0" * 64}),
            lambda m: m.update(executable="bridge.lua"),
            lambda m: m.update(executable=[]),
            lambda m: m.update(files={}),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                with self.assertRaises(PlayerRuntimeError):
                    write_bundle(self.root, mutate=mutate).verify()

    def test_unlisted_executable_components_refused(self):
        (self.root / "unexpected.DLL").write_bytes(b"not listed")
        with self.assertRaisesRegex(PlayerRuntimeError, "unlisted"):
            self.bundle.verify()

    def test_native_windows_limit_counts_utf16_units_and_includes_nul_space(self):
        prefix = "C:\\"
        for tail in ("x" * 256, "\U0001f600" * 128):
            # Both strings occupy 259 UTF-16 units including the drive prefix.
            path = PureWindowsPath(prefix + tail)
            with patch("emerald_multiplayer.player_runtime._WINDOWS_NATIVE_PATHS", True):
                _check_native_paths(path)
                with self.assertRaises(PlayerRuntimeError) as caught:
                    _check_native_paths(str(path) + "x")
            self.assertEqual(caught.exception.code, "runtime_path")
            self.assertNotIn(str(path), str(caught.exception))
        with patch("emerald_multiplayer.player_runtime._WINDOWS_NATIVE_PATHS", True):
            for path in ("C:\\bad\0path", "C:\\bad\ud800path"):
                with self.assertRaises(PlayerRuntimeError):
                    _check_native_paths(path)
        with patch("emerald_multiplayer.player_runtime._WINDOWS_NATIVE_PATHS", False):
            _check_native_paths("/" + "x" * 400)


class ProcessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.c = ClosedCompanion(self.root)
        self.c.config.rom_path, self.c.config.manifest_path = make_files(self.root)
        # ClosedCompanion's store/build is a separate Flash fixture. Only the
        # manifest identity check is substituted; real closed reconciliation,
        # OS save lock and subprocess operations remain active.
        manifest = json.loads(self.c.config.manifest_path.read_text())
        self.identity = patch("emerald_multiplayer.player_runtime.verify_rom_manifest",
                              return_value=(self.c.config.build_id, manifest))
        self.identity.start()
        self.c.config.token = bytes(range(32))
        self.c.ipc_address = ("127.0.0.1", 8870)
        bundle_root = self.root / "bundle"
        bundle_root.mkdir()
        self.bundle = write_bundle(bundle_root)
        self.save = self.root / "character.sav"
        self.runtime = PlayerRuntime(self.c, self.bundle, self.root / "private", self.save)
        self.real_spawn = asyncio.create_subprocess_exec
        self.children = []
        self.arguments = []

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
        self.assertEqual(self.save.read_bytes(), self.c.head().payload)
        self.assertFalse(self.c._bridge_admission_blocked)
        with self.assertRaises(MirrorError):
            with MirrorLease(self.save):
                self.fail("save lease was released before spawn")
        child = await self.real_spawn(direct_python(), "-c", "import time; time.sleep(60)", **kwargs)
        self.children.append(child)
        return child

    async def test_exact_arguments_and_lease_until_child_exit(self):
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
            async with self.runtime.open() as game:
                self.assertIsNone(game.process.returncode)
                self.assertTrue(game.startup.evidence_path.exists())
                with self.assertRaises(MirrorError):
                    with MirrorLease(self.save):
                        self.fail("running child lost its lease")
                with self.assertRaises(PlayerRuntimeError):
                    async with self.runtime.open():
                        self.fail("second core must not launch")
                args, options = self.arguments[0]
                self.assertEqual(args[1::2], ("--multiplayer-script", "--multiplayer-save", str(self.c.config.rom_path)))
                self.assertEqual(args[4], str(self.save))
                self.assertEqual(Path(args[2]).parent, options["cwd"])
                self.assertIn(self.c.config.token.hex(), Path(args[2]).read_text())
                self.assertNotIn("shell", options)
                game.process.terminate()
                await game.wait()
        with MirrorLease(self.save):
            pass
        self.assertFalse(self.runtime._active)

    async def test_context_error_stops_child_before_releasing_lease(self):
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
            with self.assertRaisesRegex(ValueError, "caller failure"):
                async with self.runtime.open():
                    raise ValueError("caller failure")
        self.assertIsNotNone(self.children[0].returncode)
        with MirrorLease(self.save):
            pass

    async def test_cancellation_during_spawn_waits_for_child_then_closes(self):
        spawned, return_child = asyncio.Event(), asyncio.Event()
        async def delayed(*args, **kwargs):
            child = await self.spawn(*args, **kwargs)
            spawned.set()
            await return_child.wait()
            return child
        async def run():
            async with self.runtime.open():
                self.fail("cancelled spawn may not authorize play")
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", delayed):
            task = asyncio.create_task(run())
            await asyncio.wait_for(spawned.wait(), 5)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(MirrorError):
                with MirrorLease(self.save):
                    self.fail("cancel released a lease around pending spawn")
            return_child.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
        self.assertIsNotNone(self.children[0].returncode)
        with MirrorLease(self.save):
            pass

    async def test_session_changed_during_spawn_never_yields(self):
        async def changed(*args, **kwargs):
            child = await self.spawn(*args, **kwargs)
            self.c.session_epoch += 1
            return child
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", changed):
            with self.assertRaises(ConnectionError):
                async with self.runtime.open():
                    self.fail("changed lease must never yield")
        self.assertIsNotNone(self.children[0].returncode)

    async def test_the_game_and_its_rom_are_hashed_off_the_event_loop(self):
        # A relaunch hashes the game and the ROM (tens of MB) on opening and again just before the spawn; on the
        # host the event loop also runs the world server and the battle router (newcomers-busy4-3: 2-3 s held).
        loop_thread, threads = threading.get_ident(), []
        identity = sys.modules["emerald_multiplayer.player_runtime"].verify_rom_manifest      # setUp's patch
        verify, manifest = RuntimeBundle.verify, identity.return_value
        def recorded_verify(bundle, *args):
            threads.append(("game", threading.get_ident()))
            return verify(bundle, *args)
        def recorded_identity(*args):
            threads.append(("rom", threading.get_ident()))
            return manifest
        identity.side_effect = recorded_identity
        with patch.object(RuntimeBundle, "verify", recorded_verify), \
                patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
            async with self.runtime.open() as game:
                game.process.terminate()
                await game.wait()
        self.assertEqual([kind for kind, _ in threads], ["game", "rom", "game", "rom"])
        self.assertNotIn(loop_thread, [thread for _, thread in threads])

    async def test_corrupt_bundle_prevents_any_spawn(self):
        (self.bundle.directory / "SDL2.dll").write_bytes(b"corrupt")
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
            with self.assertRaises(PlayerRuntimeError):
                async with self.runtime.open():
                    self.fail("corrupt runtime may not launch")
        self.assertEqual(self.arguments, [])

    async def test_bundle_changed_while_recovery_awaits_is_rechecked_before_spawn(self):
        async def change_bundle(operation, response):
            (self.bundle.directory / "SDL2.dll").write_bytes(b"changed during reconciliation")
        self.c.checkpoint_hook = change_bundle
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
            with self.assertRaises(PlayerRuntimeError):
                async with self.runtime.open():
                    self.fail("changed bundle may not launch")
        self.assertEqual(self.arguments, [])
        with MirrorLease(self.save):
            pass

    async def test_mailbox_manifest_changed_after_recovery_is_rejected(self):
        original = json.loads(self.c.config.manifest_path.read_text())
        changed = dict(original, mailbox_address=original["mailbox_address"] + 128)
        with patch("emerald_multiplayer.player_runtime.verify_rom_manifest", side_effect=[
                (self.c.config.build_id, original), (self.c.config.build_id, changed)]):
            with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
                with self.assertRaisesRegex(PlayerRuntimeError, "manifest changed"):
                    async with self.runtime.open():
                        self.fail("changed mailbox manifest may not launch")
        self.assertEqual(self.arguments, [])

    async def test_pending_recovery_prevents_any_spawn(self):
        (self.root / "private").mkdir()
        (self.root / "private" / "pending-trade.json").write_bytes(b"invalid")
        with patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
            with self.assertRaises(ValueError):
                async with self.runtime.open():
                    self.fail("uncertain recovery may not launch")
        self.assertEqual(self.arguments, [])

    async def test_short_launch_root_preserves_deep_private_save_and_unique_child_directories(self):
        # A valid character path can fit while /launches/UUID/bridge.lua does
        # not. Build that case without creating oversized path components.
        profile = self.root.resolve()
        while len(str(profile)) < 215:
            profile /= "profile-segment"
        self.save = profile / "character.sav"
        self.assertLessEqual(len(str(self.save).encode("utf-16-le")) // 2, 259)
        self.assertGreater(len(str(profile / "launches" / ("0" * 36) / "bridge.lua")), 259)
        runtime = PlayerRuntime(self.c, self.bundle, profile, self.save, launch_root=self.root / "launches")
        with patch("emerald_multiplayer.player_runtime._WINDOWS_NATIVE_PATHS", True), \
                patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
            for _ in range(2):
                async with runtime.open() as game:
                    args, options = self.arguments[-1]
                    self.assertEqual(options["cwd"].parent, (self.root / "launches").resolve())
                    self.assertEqual(Path(args[2]).parent, options["cwd"])
                    self.assertEqual(args[4], str(self.save))
                    self.assertTrue(Path(args[5]).is_absolute())
                    game.process.terminate()
                    await game.wait()
        self.assertNotEqual(self.arguments[0][1]["cwd"], self.arguments[1][1]["cwd"])
        self.assertFalse((profile / "launches").exists())
        self.assertEqual(self.save.read_bytes(), self.c.head().payload)
        with MirrorLease(self.save):
            pass

    async def test_oversized_launch_or_save_path_refuses_before_closed_recovery(self):
        long_root = self.root / ("a" * 100) / ("b" * 100) / ("c" * 100)
        cases = ((self.save, long_root), (long_root / "character.sav", self.root / "launches"))
        for save, launch_root in cases:
            with self.subTest(save=save == self.save):
                runtime = PlayerRuntime(self.c, self.bundle, self.root / "private", save, launch_root=launch_root)
                with patch("emerald_multiplayer.player_runtime._WINDOWS_NATIVE_PATHS", True), \
                        patch("emerald_multiplayer.player_runtime.ColdStartRecovery") as gate:
                    with self.assertRaises(PlayerRuntimeError) as caught:
                        async with runtime.open():
                            self.fail("unsupported paths authorized a child")
                    gate.assert_not_called()
                self.assertEqual(caught.exception.code, "runtime_path")
                self.assertFalse(save.exists())
                self.assertFalse(runtime._active)
        self.assertFalse((self.root / "private").exists())
        self.assertFalse(long_root.exists())

    async def test_actual_generated_script_path_is_rechecked_after_recovery(self):
        async def change_launch_root(operation, response):
            self.runtime.launch_root = self.root / ("a" * 100) / ("b" * 100) / ("c" * 100)
        self.c.checkpoint_hook = change_launch_root
        with patch("emerald_multiplayer.player_runtime._WINDOWS_NATIVE_PATHS", True), \
                patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn):
            with self.assertRaises(PlayerRuntimeError) as caught:
                async with self.runtime.open():
                    self.fail("unchecked generated script path reached spawn")
        self.assertEqual(caught.exception.code, "runtime_path")
        self.assertEqual(self.arguments, [])
        self.assertFalse((self.root / "private" / "launches").exists())
        self.assertFalse(self.runtime.launch_root.exists())
        with MirrorLease(self.save):
            pass
