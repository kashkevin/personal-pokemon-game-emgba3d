"""Original retained ownership fences and guided close action, no emulator."""
import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from emerald_multiplayer.launcher_session import LauncherSession, LauncherSessionError


class RetainedTradeLauncherTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        s = self.s = object.__new__(LauncherSession)
        s._profile_directory = Path(self.tmp.name)
        (s._profile_directory / "pending-trade.json").write_bytes(b"retained test intent")
        s._open = True; s._closing = s._settings_busy = s._autosave_dispatched = False
        s._interaction = s._save_task = s._battle_retained = s._trade_recovery_task = None
        s._host_restart_task = s._trade_close_review = s._autosave_task = None
        s._game = SimpleNamespace(process=SimpleNamespace(returncode=None)); s._runtime = object()
        menu = SimpleNamespace(_task=None)
        bridge = SimpleNamespace(incarnation=7, menu_session=menu)
        s._binding = ("world", 4, 9, "profile", "player", "build", "rules")
        s._revision = 2
        identity = ("transaction", "generation", 2, 7, "runtime")
        s._companion = SimpleNamespace(connected=False, _bridge=bridge, _reconnect_blocked=True,
            _live_trade_runtime_id="runtime", _live_battle_owner=None, _live_save_owner=None)
        s._trade_retained = (s._game, s._runtime, bridge, s._binding, identity, menu, 2)
        result = SimpleNamespace(state="trade_waiting")
        future = asyncio.get_running_loop().create_future(); future.set_result(result)
        lost = asyncio.Event(); lost.set()
        s._emergency = SimpleNamespace(bridge=bridge, session=("world", 9, 7),
            lost=lost, task=future, result=result)
        s._stop_autosave = AsyncMock(); s._autosave_wake = asyncio.Event()
        s.installation = SimpleNamespace(verify=lambda: None); s._timeout = 5
        self.events = []; s._publish = lambda state, code, **kw: self.events.append(code)
        self.pending = patch("emerald_multiplayer.launcher_session.pending_battle", return_value=False)
        self.pending.start(); self.addCleanup(self.pending.stop)
        self.read = patch("emerald_multiplayer.trade_close_recovery.read_original_trade")
        self.reader = self.read.start(); self.addCleanup(self.read.stop)

    async def test_original_fences_and_naturally_finished_menu_task(self):
        s = self.s
        self.assertTrue(s.can_prepare_trade_recovery)
        menu = s._trade_retained[5]
        menu._task = asyncio.get_running_loop().create_future()
        self.assertFalse(s.can_prepare_trade_recovery)
        menu._task.set_result(None)
        self.assertTrue(s.can_prepare_trade_recovery)
        for obj, field, value in ((s._companion, "connected", True), (s, "_runtime", object()),
                (s._companion, "_live_trade_runtime_id", "different"),
                (s._companion, "_live_battle_owner", object()),
                (s._emergency.result, "state", "unsaved_held"), (s, "_revision", 3)):
            original = getattr(obj, field); setattr(obj, field, value)
            self.assertFalse(s.can_prepare_trade_recovery, field)
            setattr(obj, field, original)

    async def test_verified_observer_does_not_adopt_lease_or_clear_original(self):
        s = self.s; original = s._trade_retained; review = object()
        async def observe(companion, directory, binding, identity, *, check_original, timeout):
            check_original()
            self.assertIs(companion, s._companion)
            self.assertEqual((binding, identity), original[3:5])
            self.assertFalse(s.can_prepare_trade_recovery)
            self.assertTrue(s._save_failed)
            return review
        with patch("emerald_multiplayer.trade_close_recovery.review_interrupted_trade", side_effect=observe):
            self.assertIs(await s.prepare_trade_recovery(), review)
        self.assertIs(s._trade_retained, original)
        self.assertEqual((s._profile_directory / "pending-trade.json").read_bytes(), b"retained test intent")
        self.assertIs(s._trade_close_review, review)
        self.assertEqual(self.events, ["trade_recovery_checking", "trade_recovery_close"])
        self.assertIsNone(s._interaction)
        self.assertFalse(s.can_prepare_trade_recovery)

    async def test_replaced_game_or_unknown_fate_never_authorizes_close(self):
        s = self.s
        async def changed(*args, **kwargs):
            s._game = SimpleNamespace(process=SimpleNamespace(returncode=None))
            return object()
        with patch("emerald_multiplayer.trade_close_recovery.review_interrupted_trade", side_effect=changed):
            with self.assertRaises(LauncherSessionError):
                await s.prepare_trade_recovery()
        self.assertIsNone(s._trade_close_review)
        self.assertEqual(self.events[-1], "trade_recovery_held")
        self.assertIsNone(s._interaction)

    async def test_restart_retains_original_trade_ownership_across_service_tasks(self):
        s = self.s
        s._world_directory = s._profile_directory
        s._host_world = object(); s._host_restart_notice = None
        s._server = s._store = None
        s.installation.rom_path = s._profile_directory / "game.gba"
        s.installation.manifest_path = s._profile_directory / "game.json"
        s._start_host_service = AsyncMock()
        s._close_host_service = AsyncMock()
        with patch("emerald_multiplayer.launcher_session.HostWorld.open", return_value=s._host_world):
            self.assertTrue(s.can_restart_host_service)
            await s.restart_host_service()
        s._start_host_service.assert_awaited_once_with(s._host_world)
        self.assertFalse(s._companion.connected)
        self.assertIsNone(s._interaction)
        self.assertEqual(s._host_restart_notice, "host_service_restarted")
