"""Private New Game lifecycle; Python child and fixture save, not gameplay."""
import asyncio
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from emerald_multiplayer.checkpoint_mirror import MirrorError, MirrorLease
from emerald_multiplayer.draft_runtime import DRAFT_SCRIPT, DraftRuntime, DraftRuntimeError
from emerald_multiplayer.launcher_session import GameInstallation
from process_fixture import direct_python
from test_host_world import make_trade_files
from test_ownership import make_ownership_flash
from test_ownership_storage import source_flash
from test_player_runtime import write_bundle


class DraftRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        rom, manifest = make_trade_files(self.root)
        bundle = self.root / "bundle"
        bundle.mkdir()
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        self.installation = GameInstallation(rom, manifest, digest(rom), digest(manifest), write_bundle(bundle))
        self.runtime = DraftRuntime(self.installation, self.root / "private")
        self.children, self.calls = [], []
        self.real_spawn = asyncio.create_subprocess_exec
        self.child_code = "pass"
        self.spawn_gate = self.spawned = None
        self.payload = source_flash()

    async def asyncTearDown(self):
        for process in self.children:
            if process.returncode is None:
                process.kill()
            await process.wait()

    async def spawn(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        save = Path(args[4])
        self.assertFalse(save.exists(), "no old or synthetic save may seed a draft")
        self.assertEqual(Path(args[2]).read_text(), DRAFT_SCRIPT)
        self.assertEqual(args[1], "--multiplayer-script")
        self.assertEqual(args[3], "--multiplayer-save")
        self.assertEqual(args[5], str(self.installation.rom_path.resolve()))
        self.assertNotIn("shell", kwargs)
        with self.assertRaises(MirrorError):
            with MirrorLease(save):
                self.fail("child creation lost its private draft lease")
        child = await self.real_spawn(direct_python(), "-c", self.child_code, **kwargs)
        self.children.append(child)
        if self.payload is not None:
            # Only a native-game stand-in produces fixture save bytes. The
            # production runtime never creates or changes character contents.
            save.write_bytes(self.payload)
        if self.spawned is not None:
            self.spawned.set()
        if self.spawn_gate is not None:
            await self.spawn_gate.wait()
        return child

    def fixture(self):
        return patch("emerald_multiplayer.draft_runtime.asyncio.create_subprocess_exec", self.spawn)

    async def test_natural_exit_validates_source_under_lease_without_world_or_bridge(self):
        with self.fixture():
            async with self.runtime.open() as game:
                self.assertEqual(await game.wait(), 0)
                receipt = self.runtime.finish()
                self.assertEqual(receipt.source_path, self.runtime.save_path)
                self.assertEqual(receipt.sha256, hashlib.sha256(self.payload).hexdigest())
                self.assertEqual(receipt.party_count, 1)
                self.assertIsNone(game.startup)
                with self.assertRaises(MirrorError):
                    with MirrorLease(self.runtime.save_path):
                        self.fail("receipt released the lease before context exit")
        self.assertEqual(receipt.source_path.read_bytes(), self.payload)
        record = json.loads((self.runtime.directory / "draft-completed.json").read_bytes())
        self.assertEqual(record["sha256"], receipt.sha256)
        self.assertEqual(record["build_id"], self.installation.rom_sha256)
        self.assertFalse((self.root / "private" / "players").exists())
        self.assertFalse((self.root / "private" / "worlds").exists())
        self.assertFalse(list(self.runtime.directory.glob("*.grant.json")))
        self.assertFalse((self.runtime.directory / "pending-export.json").exists())
        with MirrorLease(self.runtime.save_path):
            pass

    async def test_living_game_cannot_publish_even_a_valid_fixture_save(self):
        self.child_code = "import time; time.sleep(60)"
        with self.fixture():
            async with self.runtime.open():
                with self.assertRaises(DraftRuntimeError) as caught:
                    self.runtime.finish()
                self.assertEqual(caught.exception.code, "game_running")
                self.assertFalse((self.runtime.directory / "draft-completed.json").exists())
        self.assertIsNotNone(self.children[0].returncode)
        self.assertIsNone(self.runtime.result)

    async def test_abnormal_exit_retains_save_but_cannot_publish_source(self):
        self.child_code = "raise SystemExit(7)"
        with self.fixture():
            async with self.runtime.open() as game:
                self.assertEqual(await game.wait(), 7)
                with self.assertRaises(DraftRuntimeError) as caught:
                    self.runtime.finish()
                self.assertEqual(caught.exception.code, "game_failed")
        self.assertEqual(self.runtime.save_path.read_bytes(), self.payload)
        self.assertIsNone(self.runtime.result)

    async def test_unsaved_corrupt_owned_or_starterless_source_is_refused(self):
        cases = ((None, "save_required"), (b"invalid", "invalid_source"),
                 (make_ownership_flash(), "invalid_source"),
                 (source_flash(locations=()), "starter_required"))
        for payload, code in cases:
            with self.subTest(code=code):
                self.runtime = DraftRuntime(self.installation, self.root / "private")
                self.payload = payload
                with self.fixture():
                    async with self.runtime.open() as game:
                        await game.wait()
                        with self.assertRaises(DraftRuntimeError) as caught:
                            self.runtime.finish()
                        self.assertEqual(caught.exception.code, code)
                self.assertFalse((self.runtime.directory / "draft-completed.json").exists())
                self.assertIsNone(self.runtime.result)

    async def test_closed_or_already_finished_draft_cannot_publish_again(self):
        with self.assertRaises(DraftRuntimeError) as caught:
            self.runtime.finish()
        self.assertEqual(caught.exception.code, "draft_closed")
        with self.fixture():
            async with self.runtime.open() as game:
                await game.wait()
                self.runtime.finish()
                original = (self.runtime.directory / "draft-completed.json").read_bytes()
                with self.assertRaises(DraftRuntimeError) as caught:
                    self.runtime.finish()
                self.assertEqual(caught.exception.code, "draft_finished")
        with self.assertRaises(DraftRuntimeError):
            self.runtime.finish()
        self.assertEqual((self.runtime.directory / "draft-completed.json").read_bytes(), original)
        with self.assertRaises(DraftRuntimeError) as caught:
            async with self.runtime.open():
                self.fail("a draft reopened an existing save")
        self.assertEqual(caught.exception.code, "draft_used")

    async def test_changed_installation_refused_before_private_draft_creation(self):
        self.installation.rom_path.write_bytes(b"changed")
        with self.fixture():
            with self.assertRaises(DraftRuntimeError) as caught:
                async with self.runtime.open():
                    self.fail("changed ROM launched")
        self.assertEqual(caught.exception.code, "installation_changed")
        self.assertFalse(self.runtime.directory.exists())
        self.assertEqual(self.calls, [])

    async def test_oversized_native_path_refuses_before_draft_directory_or_intent(self):
        private = self.root / ("a" * 100) / ("b" * 100) / ("c" * 100)
        runtime = DraftRuntime(self.installation, private)
        with patch("emerald_multiplayer.player_runtime._WINDOWS_NATIVE_PATHS", True), self.fixture():
            with self.assertRaises(DraftRuntimeError) as caught:
                async with runtime.open():
                    self.fail("unsupported draft path authorized a child")
        self.assertEqual(caught.exception.code, "runtime_path")
        self.assertFalse(private.exists())
        self.assertEqual(self.calls, [])

    async def test_changed_bundle_refused_before_private_draft_creation(self):
        (self.root / "bundle" / "game.exe").write_bytes(b"changed")
        with self.fixture():
            with self.assertRaises(DraftRuntimeError) as caught:
                async with self.runtime.open():
                    self.fail("changed runtime launched")
        self.assertEqual(caught.exception.code, "installation_changed")
        self.assertFalse(self.runtime.directory.exists())
        self.assertEqual(self.calls, [])

    async def test_canceled_creation_drains_late_child_and_retains_incomplete_source(self):
        self.child_code = "import time; time.sleep(60)"
        self.spawned, self.spawn_gate = asyncio.Event(), asyncio.Event()
        async def run():
            async with self.runtime.open():
                self.fail("canceled creation yielded")
        with self.fixture():
            task = asyncio.create_task(run())
            await asyncio.wait_for(self.spawned.wait(), 5)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            with self.assertRaises(MirrorError):
                with MirrorLease(self.runtime.save_path):
                    self.fail("cancel released lease before child creation returned")
            self.spawn_gate.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 10)
        self.assertIsNotNone(self.children[0].returncode)
        self.assertEqual(self.runtime.save_path.read_bytes(), self.payload)
        self.assertFalse((self.runtime.directory / "draft-completed.json").exists())
        with MirrorLease(self.runtime.save_path):
            pass

    async def test_context_cancellation_retains_draft_and_waits_for_child_exit(self):
        self.child_code = "import time; time.sleep(60)"
        entered = asyncio.Event()
        async def run():
            async with self.runtime.open():
                entered.set()
                await asyncio.Future()
        with self.fixture():
            task = asyncio.create_task(run())
            await asyncio.wait_for(entered.wait(), 5)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 10)
        self.assertIsNotNone(self.children[0].returncode)
        self.assertFalse((self.runtime.directory / "draft-completed.json").exists())
        self.assertTrue((self.runtime.directory / "draft-intent.json").exists())
        with MirrorLease(self.runtime.save_path):
            pass

    async def test_independent_drafts_have_distinct_paths_and_do_not_seed_from_previous(self):
        first = self.runtime
        with self.fixture():
            async with first.open() as game:
                await game.wait()
                first.finish()
            self.runtime = DraftRuntime(self.installation, self.root / "private")
            async with self.runtime.open() as game:
                await game.wait()
                self.runtime.finish()
        self.assertNotEqual(self.runtime.directory, first.directory)
        self.assertEqual(first.save_path.read_bytes(), self.payload)
        self.assertEqual(self.runtime.save_path.read_bytes(), self.payload)
        self.assertEqual(len(self.calls), 2)

    async def test_relative_verified_rom_becomes_absolute_for_isolated_child_directory(self):
        self.installation = replace(self.installation,
                                    rom_path=Path(os.path.relpath(self.installation.rom_path)))
        self.runtime = DraftRuntime(self.installation, self.root / "private")
        with self.fixture():
            async with self.runtime.open() as game:
                await game.wait()
                self.runtime.finish()
        self.assertTrue(Path(self.calls[0][0][5]).is_absolute())

    async def test_existing_draft_directory_is_preserved_without_any_launch(self):
        self.runtime.directory.mkdir(parents=True)
        self.runtime.save_path.write_bytes(b"retained private content")
        with self.fixture():
            with self.assertRaises(DraftRuntimeError) as caught:
                async with self.runtime.open():
                    self.fail("existing draft was reused")
        self.assertEqual(caught.exception.code, "draft_failed")
        self.assertEqual(self.runtime.save_path.read_bytes(), b"retained private content")
        self.assertEqual(self.calls, [])
