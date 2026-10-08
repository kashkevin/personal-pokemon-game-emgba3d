import asyncio
from types import SimpleNamespace
import unittest

from emerald_multiplayer.bridge_protocol import BridgeOutbox
from emerald_multiplayer.menu_mailbox import MenuRequest, unpack_screen
from emerald_multiplayer.menu_session import MenuSession
from emerald_multiplayer.player_menu import MenuRow, MenuScreen


class FakeMenu:
    def __init__(self):
        self.screen = MenuScreen(1, "Players", "Ready", (MenuRow(1, "Accept"),), 0)
        self.gate, self.entered = asyncio.Event(), asyncio.Event()
        self.calls = 0

    async def refresh(self):
        return self.screen

    async def choose(self, screen, action):
        self.calls += 1
        self.entered.set()
        await self.gate.wait()
        return self.screen


class MenuSessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.closed = False
        def close(): self.closed = True
        self.bridge = SimpleNamespace(outbox=BridgeOutbox(), writer=SimpleNamespace(close=close))
        self.companion = SimpleNamespace(_bridge=self.bridge)
        self.session = MenuSession(self.companion, self.bridge)
        self.session.menu = FakeMenu()

    async def asyncTearDown(self):
        self.session.menu.gate.set()
        await self.session.close()

    def feed(self, seq, screen=0, action=0, kind=1):
        self.session.feed(MenuRequest(seq, screen, action, kind).pack())

    async def result(self):
        frame = await asyncio.wait_for(self.bridge.outbox.get(), 1)
        self.assertEqual(frame[4:5], b"M")
        return unpack_screen(frame[5:])

    async def open(self):
        self.feed(1)
        await self.session._task
        self.assertEqual((await self.result())[0], 1)

    async def test_close_then_reopen_drops_late_response_without_canceling_consent(self):
        await self.open()
        self.feed(2, 1, 1, 2)
        await self.session.menu.entered.wait()
        self.feed(3, 1, 0, 3)
        self.feed(4)
        self.session.menu.gate.set()
        await self.session._task
        self.assertEqual((await self.result())[0], 4)
        self.assertEqual(self.session.menu.calls, 1)
        self.assertFalse(self.bridge.outbox.controls)

    async def test_repeated_or_overlapping_choices_are_refused(self):
        await self.open()
        with self.assertRaises(ValueError): self.feed(1)
        self.feed(2, 1, 1, 2)
        await self.session.menu.entered.wait()
        with self.assertRaises(ValueError): self.feed(3, 1, 1, 2)
        self.assertEqual(self.session.menu.calls, 1)

    async def test_shutdown_drains_dispatched_choice_and_emits_no_reply(self):
        await self.open()
        self.feed(2, 1, 1, 2)
        await self.session.menu.entered.wait()
        close = asyncio.create_task(self.session.close())
        await asyncio.sleep(0)
        self.assertFalse(close.done())
        self.session.menu.gate.set()
        await close
        self.assertFalse(self.bridge.outbox.controls)

    async def test_old_bridge_incarnation_cannot_receive_screen(self):
        self.companion._bridge = object()
        self.feed(1)
        await self.session._task
        self.assertFalse(self.bridge.outbox.controls)

    async def test_repeated_close_cancellation_still_drains_dispatched_consent(self):
        await self.open()
        self.feed(2, 1, 1, 2)
        await self.session.menu.entered.wait()
        close = asyncio.create_task(self.session.close())
        await asyncio.sleep(0)
        close.cancel()
        await asyncio.sleep(0)
        close.cancel()
        await asyncio.sleep(0)
        self.assertFalse(close.done())
        self.session.menu.gate.set()
        with self.assertRaises(asyncio.CancelledError): await close
        self.assertTrue(self.session._task.done())
        self.assertTrue(self.session._cleanup_task.done())
        self.assertFalse(self.bridge.outbox.controls)

    async def test_dispatch_uncertainty_requests_local_close_without_auto_retry(self):
        await self.open()
        async def uncertain(*args):
            self.session.menu.calls += 1
            raise ConnectionError("private diagnostic with credential must not appear")
        self.session.menu.choose = uncertain
        self.feed(2, 1, 1, 2)
        await self.session._task
        ack, screen, close = await self.result()
        self.assertEqual(ack, 2)
        self.assertTrue(close)
        self.assertNotIn("credential", str(screen))
        self.assertEqual(self.session.menu.calls, 1)

    async def test_handoff_waits_for_native_release_and_runs_once(self):
        await self.open()
        calls = []
        async def handoff(kind, value, owner):
            calls.append((kind, value, owner))
        self.companion._native_menu_handoff = handoff
        self.session.menu.handoff = ("battle", {"id": "captured"})
        self.feed(2, 1, 1, 2)
        self.session.menu.gate.set()
        self.assertTrue((await self.result())[2])
        self.assertEqual(calls, [])
        self.feed(3, 1, 0, 3)
        await self.session._task
        self.assertEqual(calls, [("battle", {"id": "captured"}, self.session)])
        self.assertIsNone(self.session.menu.handoff)

    async def test_handoff_timeout_or_changed_bridge_cannot_dispatch(self):
        await self.open()
        request = self.session._last_request
        with self.assertRaises(TimeoutError):
            await self.session.close_for_handoff(request, self.session.menu.screen, timeout=.01)
        await self.result()
        self.assertIsNone(self.session._close_waiter)
        task = asyncio.create_task(self.session.close_for_handoff(request, self.session.menu.screen))
        await self.result()
        self.companion._bridge = object()
        self.feed(2, 0, 0, 3)
        with self.assertRaises(ConnectionError):
            await task

    async def test_bridge_cleanup_breaks_unacknowledged_handoff(self):
        await self.open()
        self.session.menu.handoff = ("battle", {})
        self.feed(2, 1, 1, 2)
        self.session.menu.gate.set()
        await self.result()
        await asyncio.wait_for(self.session.close(), 1)
        self.assertIsNone(self.session.menu.handoff)
        self.assertTrue(self.session._task.done())

    async def test_trade_reopen_requires_native_open_before_showing_consent(self):
        await self.open()
        self.feed(2, 1, 0, 3)
        self.companion.config = SimpleNamespace(menu_abi_version=2)
        screen = MenuScreen(3, "Trade", "Choose Pokemon", (MenuRow(1, "No.25 Lv5"),))
        opening = asyncio.create_task(self.session.open_trade_dialog(screen))
        frame = await asyncio.wait_for(self.bridge.outbox.get(), 1)
        ack, _, flag = unpack_screen(frame[5:], allow_trade_reopen=True)
        self.assertEqual((ack, flag), (2, 2))
        self.assertFalse(opening.done())
        self.feed(3)
        await opening
        self.assertEqual((await self.result())[:2], (3, screen))
        self.feed(4, 3, 1, 2)
        self.assertEqual((await self.session.dialog_choice()).action, 1)
        closing = asyncio.create_task(self.session.close_dialog(screen))
        self.assertTrue((await self.result())[2])
        self.assertFalse(closing.done())
        self.feed(5, 3, 0, 3)
        await closing
        self.assertIsNone(self.session._dialog_queue)
