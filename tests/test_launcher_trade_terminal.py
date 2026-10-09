"""Launcher terminal validation only; native menu results are explicit fixtures."""
import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from emerald_multiplayer.launcher_session import LauncherSession, LauncherSessionError
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE


class LauncherTradeTerminalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        bridge = object()
        self.session = object.__new__(LauncherSession)
        s = self.session
        s._assert_session = lambda: None
        s._battle_menu_preparation = None
        s._game = SimpleNamespace(process=SimpleNamespace(returncode=None))
        s._runtime = object(); s._binding = ("fixture-binding",)
        s._interaction = None; s._save_failed = False; s._save_task = None
        s._manifest = {}; s._revision = 8; s._autosave_wake = asyncio.Event()
        s._profile_directory = Path(self.temp.name)
        s._stop_autosave = AsyncMock()
        s._autosave_clock = lambda: 100
        s._publish = lambda *args, **kwargs: self.events.append((args, kwargs))
        s._fail_save = lambda: setattr(s, "_save_failed", True)
        s._companion = SimpleNamespace(_bridge=bridge, save_incarnation=3, save_profile=OWNERSHIP_PROFILE,
            config=SimpleNamespace(build_id="fixture-build", ruleset_id="fixture-rules"),
            _live_trade_runtime_id=str(uuid4()))
        self.menu = SimpleNamespace(bridge=bridge)
        self.descriptor = dict(transaction_id=str(uuid4()), generation=str(uuid4()))
        self.events = []

    def result(self, *, original=8, state="applied"):
        return dict(self.descriptor, expected_revision=original, state=state,
            checkpoint=dict(revision=original + (2 if state == "applied" else 1),
                request_id=self.descriptor["transaction_id"], size=131072, sha256="a"*64,
                build_id="fixture-build", ruleset_id="fixture-rules", save_profile=OWNERSHIP_PROFILE))

    async def invoke(self, result):
        owner = self.owner(result)
        with patch("emerald_multiplayer.trade_menu.NativeTradeMenu", return_value=owner):
            await self.session._native_menu_handoff("trade", self.descriptor, self.menu)
        owner.run.assert_awaited_once_with(self.descriptor, 8)

    def owner(self, result=None):
        return SimpleNamespace(run=AsyncMock(return_value=result), coordinator=SimpleNamespace(
            trade_path=self.session._profile_directory / "pending-trade.json",
            _session=lambda: None, _load=lambda session: dict(expected_revision=8)))

    async def test_fresh_applied_and_aborted_keep_exact_original_base(self):
        for state in ("applied", "aborted"):
            with self.subTest(state=state):
                self.session._revision = 8
                result = self.result(state=state)
                await self.invoke(result)
                self.assertEqual(self.session._revision, result["checkpoint"]["revision"])
                self.assertFalse(self.session._save_failed)
                self.assertIsNone(self.session._interaction)
                self.assertEqual(self.events[-1][0][1], "trade_finished" if state == "applied" else "trade_cancelled")

    async def test_resumed_prepared_revision_uses_original_base_for_both_terminal_fates(self):
        for state in ("applied", "aborted"):
            with self.subTest(state=state):
                self.session._revision = 8
                result = self.result(original=7, state=state)
                await self.invoke(result)
                self.assertEqual(self.session._revision, 9 if state == "applied" else 8)
                self.assertFalse(self.session._save_failed)

    async def test_foreign_transaction_generation_counter_and_pending_intent_refuse(self):
        changes = [dict(transaction_id=str(uuid4())), dict(generation=str(uuid4())),
            dict(expected_revision=True), dict(expected_revision=6), dict(expected_revision=9),
            dict(state="committed")]
        wrong_head = self.result(); wrong_head["checkpoint"]["revision"] = 11
        for result in [dict(self.result(), **change) for change in changes] + [wrong_head]:
            with self.subTest(result=result):
                self.session._save_failed = False
                with self.assertRaises(LauncherSessionError):
                    await self.invoke(result)
                self.assertTrue(self.session._save_failed)
                self.assertEqual(self.session._revision, 8)
                self.assertIsNone(self.session._interaction)
        self.session._save_failed = False
        pending = self.session._profile_directory / "pending-trade.json"
        pending.write_bytes(b"fixture unresolved original intent")
        with self.assertRaises(LauncherSessionError):
            await self.invoke(self.result())
        self.assertEqual(pending.read_bytes(), b"fixture unresolved original intent")

    async def test_replaced_original_incarnation_never_reports_success(self):
        owner = self.owner()
        async def replaced(*args):
            self.session._companion.save_incarnation = 4
            return self.result()
        owner.run.side_effect = replaced
        with patch("emerald_multiplayer.trade_menu.NativeTradeMenu", return_value=owner):
            with self.assertRaises(LauncherSessionError):
                await self.session._native_menu_handoff("trade", self.descriptor, self.menu)
        self.assertTrue(self.session._save_failed)
        self.assertEqual(self.session._revision, 8)
        self.assertEqual(len(self.events), 1)
