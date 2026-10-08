"""Real child-process lifetime tests; the child is Python, not game acceptance."""
import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from emerald_multiplayer.checkpoint_mirror import MirrorError, MirrorLease
from emerald_multiplayer.player_runtime import PlayerRuntime, PlayerRuntimeError, RuntimeBundle
from test_cold_start import ClosedCompanion
from test_companion import make_files


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
        child = await self.real_spawn(sys.executable, "-c", "import time; time.sleep(60)", **kwargs)
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
