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
