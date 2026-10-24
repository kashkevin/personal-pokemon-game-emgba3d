import asyncio
from types import SimpleNamespace
import unittest

from emerald_multiplayer.battle_admission_session import BattleAdmissionRefused
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

    async def test_a_press_carries_when_it_arrived_and_a_stale_one_reshows_instead_of_closing(self):
        # A question's grace counts to when the press reached the launcher, not to when the menu got round to it; a
        # press on a screen a status refresh replaced shows the page again (it used to close the window).
        from emerald_multiplayer.player_menu import PlayerMenuError
        await self.open()
        seen = []
        async def choose(screen, action, *, pressed=None):
            seen.append(pressed)
            await asyncio.sleep(0.05)                  # handled a little later than it arrived
            raise PlayerMenuError("stale_menu")
        async def reshow():
            return MenuScreen(5, "Players", "Ready", (MenuRow(1, "Accept"),), 0)
        self.session.menu.choose, self.session.menu.reshow = choose, reshow
        before = asyncio.get_running_loop().time()
        self.feed(2, 1, 1, 2)
        await self.session._task
        self.assertTrue(before <= seen[0] <= before + 0.04)
        ack, screen, close = await self.result()
        self.assertEqual((ack, screen.revision, close), (2, 5, False))
        self.assertTrue(self.session.open)

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

    async def admission_menu(self, prepare=None, handoff=None):
        self.events = []
        self.bridge.battle_capable = True
        self.companion.config = SimpleNamespace(menu_abi_version=2,
            battle_resume_abi_version=1, emergency_save_abi_version=2)
        self.session.menu.screen = MenuScreen(1, "Battle", "All players accepted",
            (MenuRow(1, "Enter battle"),), 0, 1)
        def claim(revision, action):
            self.assertEqual((revision, action), (1, 1))
            self.events.append("claim")
            return {"battle_id": "original", "generation": 1}
        self.session.menu.claim_battle_admission = claim
        async def default_prepare(value, owner):
            self.assertIs(owner, self.session)
            self.assertTrue(owner._battle_preparing)
            self.assertIsNotNone(owner._close_waiter)
            self.events.append("prepare")
            self.feed(3, 1, 0, 3)
        async def default_handoff(kind, value, owner):
            self.assertEqual((kind, value), ("battle", {"battle_id": "original", "generation": 1}))
            self.assertTrue(owner._battle_preparing)
            self.events.append("handoff")
        def abandon(owner):
            self.assertTrue(owner._battle_preparing)
            self.events.append("abandon")
        self.companion._native_menu_prepare_battle = prepare or default_prepare
        def capture(value, owner):
            self.assertTrue(owner._battle_preparing)
            self.assertEqual(value, {"battle_id": "original", "generation": 1})
        self.companion._native_menu_capture_battle = capture
        self.companion._native_menu_handoff = handoff or default_handoff
        self.companion._native_menu_abandon_battle_preparation = abandon
        self.feed(1)
        await self.session._task
        frame = await asyncio.wait_for(self.bridge.outbox.get(), 1)
        self.assertEqual(unpack_screen(frame[5:], allow_battle_admission=True)[1].admission_action, 1)

    async def test_atomic_admission_consumes_before_await_and_accepts_close_during_prepare(self):
        await self.admission_menu()
        self.feed(2, 1, 1, 2)
        self.assertEqual(self.events, ["claim"])
        await self.session._task
        self.assertEqual(self.events, ["claim", "prepare", "handoff"])
        self.assertFalse(self.bridge.outbox.controls)  # No ordinary CLOSE or response.
        self.assertFalse(self.session._battle_latched)
        self.assertFalse(self.session._battle_preparing)
        self.assertEqual(self.session.menu.calls, 0)

    async def test_uncertain_atomic_admission_holds_and_does_not_close_or_reopen(self):
        async def prepare(*args):
            self.events.append("prepare")
            raise ConnectionError("ADMIT receipt uncertain")
        await self.admission_menu(prepare)
        self.feed(2, 1, 1, 2)
        await self.session._task
        self.assertEqual(self.events, ["claim", "prepare", "abandon"])
        self.assertTrue(self.session._battle_latched)
        self.assertTrue(self.session._battle_admission_failed)
        self.assertFalse(self.bridge.outbox.controls)
        self.assertFalse(self.closed)
        with self.assertRaises(ValueError): self.feed(3)
        self.assertEqual(self.session.menu.calls, 0)

    async def test_admission_failed_local_claim_preserves_native_latch(self):
        await self.admission_menu()
        def stale(*args): raise ValueError("displayed descriptor no longer available")
        self.session.menu.claim_battle_admission = stale
        self.feed(2, 1, 1, 2)
        await self.session._task
        self.assertEqual(self.events, ["abandon"])
        self.assertTrue(self.session._battle_admission_failed)
        self.assertFalse(self.bridge.outbox.controls)

    async def test_completed_exact_recovery_releases_only_the_original_menu_latch(self):
        async def prepare(*args):
            self.feed(3, 1, 0, 3)
            raise ConnectionError("held after uncertain receipt")
        await self.admission_menu(prepare)
        self.feed(2, 1, 1, 2)
        await self.session._task
        with self.assertRaises(ConnectionError): self.session.finish_battle_admission("other", 1)
        with self.assertRaises(ConnectionError): self.session.finish_battle_admission("original", 2)
        self.assertTrue(self.session._battle_latched)
        self.session.finish_battle_admission("original", 1)
        self.assertFalse(self.session._battle_latched)
        self.assertFalse(self.session._battle_admission_failed)
        self.assertIsNone(self.session._admission_identity)
        self.assertFalse(self.bridge.outbox.controls)
        self.feed(4)
        await self.session._task
        frame = await asyncio.wait_for(self.bridge.outbox.get(), 1)
        self.assertEqual(unpack_screen(frame[5:], allow_battle_admission=True)[0], 4)

    async def test_headless_battle_completion_does_not_require_menu_ownership(self):
        self.session.finish_battle_admission("headless", 1)
        self.assertFalse(self.session._battle_latched)

    async def test_retired_menu_battle_does_not_claim_a_later_headless_completion(self):
        async def handoff(kind, value, owner):
            owner.finish_battle_admission(value["battle_id"], value["generation"])
        await self.admission_menu(handoff=handoff)
        self.feed(2, 1, 1, 2)
        await self.session._task
        self.assertFalse(self.session._battle_latched)
        self.session.finish_battle_admission("later-headless", 1)
        self.assertFalse(self.bridge.outbox.controls)

    async def test_retired_battle_cannot_clear_a_new_menu_admission(self):
        async def handoff(kind, value, owner):
            owner.finish_battle_admission(value["battle_id"], value["generation"])
        await self.admission_menu(handoff=handoff)
        self.feed(2, 1, 1, 2)
        await self.session._task
        self.feed(4)
        await self.session._task
        frame = await asyncio.wait_for(self.bridge.outbox.get(), 1)
        self.assertEqual(unpack_screen(frame[5:], allow_battle_admission=True)[0], 4)
        self.session.menu.claim_battle_admission = lambda *_: {
            "battle_id": "next", "generation": 2}
        def capture(*_):
            raise OSError("publication uncertain")
        self.companion._native_menu_capture_battle = capture
        self.feed(5, 1, 1, 2)
        await self.session._task
        self.assertTrue(self.session._battle_latched)
        with self.assertRaises(ConnectionError):
            self.session.finish_battle_admission("original", 1)
        self.assertTrue(self.session._battle_latched)
        self.session.finish_battle_admission("next", 2)
        self.assertFalse(self.session._battle_latched)
        self.assertIsNone(self.session._admission_identity)

    async def test_synchronous_capture_failure_never_emits_ordinary_close(self):
        await self.admission_menu()
        def capture(*args): raise OSError("durable publication failed")
        self.companion._native_menu_capture_battle = capture
        self.feed(2, 1, 1, 2)
        self.assertEqual(self.events, ["claim"])
        await self.session._task
        self.assertEqual(self.events, ["claim", "abandon"])
        self.assertTrue(self.session._battle_latched)
        self.assertFalse(self.bridge.outbox.controls)

    async def test_delayed_native_enter_keeps_displayed_claim_across_host_loss_poll(self):
        await self.admission_menu()
        calls = []
        async def disconnected_refresh():
            calls.append("refresh")
            self.session.menu.screen = MenuScreen(2, "Players", "Connection lost", (), 0)
            return self.session.menu.screen
        self.session.menu.refresh = disconnected_refresh
        self.companion.connected = False
        await asyncio.sleep(2.1)  # Exercise the real independent status poll.
        self.assertEqual(calls, [])
        self.assertFalse(self.bridge.outbox.controls)
        self.feed(2, 1, 1, 2)
        await self.session._task
        self.assertEqual(self.events, ["claim", "prepare", "handoff"])

    async def test_native_close_retires_unselected_displayed_enter_claim(self):
        await self.admission_menu()
        self.feed(2, 1, 0, 3)
        self.assertIsNone(self.session._admission_display)
        self.assertFalse(self.session._battle_latched)
        self.assertEqual(self.events, [])

    async def test_admission_changed_bridge_cannot_start_and_still_abandons_safely(self):
        async def prepare(*args):
            self.companion._bridge = object()
            self.feed(3, 1, 0, 3)
        await self.admission_menu(prepare)
        self.feed(2, 1, 1, 2)
        await self.session._task
        self.assertEqual(self.events, ["claim", "abandon"])
        self.assertFalse(self.bridge.outbox.controls)

    async def test_admission_timeout_never_runs_handoff_or_sends_close(self):
        async def prepare(*args): pass
        await self.admission_menu(prepare)
        original = self.session.admit_for_handoff
        async def bounded(request): await original(request, timeout=.01)
        self.session.admit_for_handoff = bounded
        self.feed(2, 1, 1, 2)
        await self.session._task
        self.assertEqual(self.events, ["claim", "abandon"])
        self.assertIsNone(self.session._close_waiter)
        self.assertFalse(self.bridge.outbox.controls)

    async def test_admission_cancellation_releases_python_ownership_but_retains_core(self):
        entered = asyncio.Event()
        async def prepare(*args):
            entered.set()
            await asyncio.Event().wait()
        await self.admission_menu(prepare)
        self.feed(2, 1, 1, 2)
        await entered.wait()
        task = self.session._task
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.session._task = None
        self.assertEqual(self.events, ["claim", "abandon"])
        self.assertTrue(self.session._battle_latched)
        self.assertFalse(self.bridge.outbox.controls)

    async def test_resume_capability_never_uses_legacy_unmarked_battle_close(self):
        await self.open()
        self.companion.config = SimpleNamespace(battle_resume_abi_version=1)
        called = []
        async def handoff(*args): called.append(args)
        self.companion._native_menu_handoff = handoff
        self.session.menu.handoff = ("battle", {})
        self.feed(2, 1, 1, 2)
        self.session.menu.gate.set()
        await self.session._task
        self.assertTrue((await self.result())[2])
        self.assertEqual(called, [])


class AdmissionReleaseTests(MenuSessionTests):
    """The owner's report of 2026-10-20: both players chose Enter battle and both games stayed on "Waiting for
    server..." for good. An Enter the companion refuses before any ADMIT now releases the window with its reason."""

    async def release_menu(self, **kwargs):
        await self.admission_menu(**kwargs)
        self.companion.config.menu_release_abi_version = 1
        self.refused, self.notices = [], []
        self.companion._native_menu_refused_battle = self.refused.append
        self.session.menu.notice = self.notices.append

    async def released(self, ack):
        frame = await asyncio.wait_for(self.bridge.outbox.get(), 1)
        sequence, screen, flags = unpack_screen(frame[5:], allow_release=True)
        self.assertEqual((sequence, flags), (ack, 3))
        self.assertEqual(screen.admission_action, 0)      # a release never carries an Enter row
        return screen

    async def test_refused_enter_releases_the_latched_window_with_its_reason(self):
        await self.release_menu()
        def capture(*_): raise BattleAdmissionRefused("save_recovery_required", "saving stopped")
        self.companion._native_menu_capture_battle = capture
        self.feed(2, 1, 1, 2)
        await asyncio.wait_for(self.session._task, 2)
        await self.released(2)
        self.assertEqual(self.notices, ["Saving stopped: restart game"])
        self.assertEqual(self.events, ["claim"])          # no preparation, no abandon: nothing to recover
        self.assertEqual(self.refused, [self.session])
        self.assertFalse(self.session._battle_latched or self.session._battle_admission_failed)
        # Then the usual screen, whose Enter row works again once the reason is gone.
        frame = await asyncio.wait_for(self.bridge.outbox.get(), 1)
        self.assertEqual(unpack_screen(frame[5:], allow_battle_admission=True)[1].admission_action, 1)
        self.feed(3, 1, 0, 3)                             # the window takes input again (here, B: Close)

    async def test_host_refused_claim_releases_without_retention(self):
        async def prepare(*_):
            self.events.append("prepare")
            raise BattleAdmissionRefused("battle_not_ready", "the challenge expired")
        await self.release_menu(prepare=prepare)
        self.feed(2, 1, 1, 2)
        await asyncio.wait_for(self.session._task, 2)
        await self.released(2)
        self.assertEqual(self.notices, ["Challenge expired: try again"])
        self.assertEqual(self.events, ["claim", "prepare"])
        self.assertFalse(self.session._battle_latched)

    async def test_uncertain_failure_still_retains_with_the_release(self):
        async def prepare(*_):
            self.events.append("prepare")
            raise ConnectionError("ADMIT receipt uncertain")
        await self.release_menu(prepare=prepare)
        self.feed(2, 1, 1, 2)
        await self.session._task
        self.assertEqual(self.events, ["claim", "prepare", "abandon"])
        self.assertTrue(self.session._battle_latched)
        self.assertFalse(self.bridge.outbox.controls)

    async def test_refusal_without_the_release_keeps_the_old_retention(self):
        await self.admission_menu()
        def capture(*_): raise BattleAdmissionRefused("save_recovery_required", "saving stopped")
        self.companion._native_menu_capture_battle = capture
        self.feed(2, 1, 1, 2)
        await self.session._task
        self.assertEqual(self.events, ["claim", "abandon"])
        self.assertTrue(self.session._battle_latched)
        self.assertFalse(self.bridge.outbox.controls)


class BothPlayersEnterTests(unittest.IsolatedAsyncioTestCase):
    """Both clients choose Enter battle at the same moment and wait for the host: each must either reach its battle
    or get a clear, recoverable screen in bounded time, never wait forever (the owner's report of 2026-10-20)."""

    def player(self, name, host):
        test = self
        bridge = SimpleNamespace(outbox=BridgeOutbox(), writer=SimpleNamespace(close=lambda: None), battle_capable=True)
        companion = SimpleNamespace(_bridge=bridge, config=SimpleNamespace(menu_abi_version=2,
            battle_resume_abi_version=1, emergency_save_abi_version=2, menu_release_abi_version=1))
        session = MenuSession(companion, bridge)
        menu = FakeMenu()
        menu.gate.set()
        menu.screen = MenuScreen(1, "Rival Battle - 1v1", "Opponent accepted", (MenuRow(1, "Enter battle"),), 0, 1)
        menu.claim_battle_admission = lambda revision, action: {"battle_id": "b1", "generation": 1}
        menu.notice = lambda text: setattr(menu, "noticed", text)
        session.menu = menu
        outcome = {"name": name}
        def capture(descriptor, owner):
            refusal = host.refusals.get(name)
            if refusal is not None:
                raise BattleAdmissionRefused(refusal, "refused before any ADMIT")
        async def prepare(descriptor, owner):
            host.entered.add(name)
            session.feed(MenuRequest(3, 1, 0, 3).pack())   # ADMIT moved the window into the battle hold (native CLOSE)
        async def handoff(kind, descriptor, owner):
            # The battle starts when every trainer entered; it ends unstarted when one was refused.
            async with asyncio.timeout(5):
                while not (host.entered >= {"host", "friend"} or host.refusals):
                    await asyncio.sleep(.01)
            outcome["battle"] = "started" if not host.refusals else "entry cancelled"
            owner.finish_battle_admission("b1", 1)
        companion._native_menu_capture_battle = capture
        companion._native_menu_prepare_battle = prepare
        companion._native_menu_handoff = handoff
        companion._native_menu_abandon_battle_preparation = lambda owner: outcome.setdefault("abandoned", True)
        companion._native_menu_refused_battle = lambda owner: outcome.setdefault("refused", True)
        test.sessions.append(session)
        return session, bridge, outcome

    async def asyncSetUp(self):
        self.sessions = []

    async def asyncTearDown(self):
        for session in self.sessions:
            await session.close()

    async def both_enter(self, refusals):
        host = SimpleNamespace(refusals=dict(refusals), entered=set())
        players = [self.player(name, host) for name in ("host", "friend")]
        for session, bridge, _ in players:
            session.feed(MenuRequest(1, 0, 0, 1).pack())
            await session._task
            await asyncio.wait_for(bridge.outbox.get(), 1)
        for session, _, _ in players:   # the same moment: neither waits for the other's Enter to be handled
            session.feed(MenuRequest(2, 1, 1, 2).pack())
        await asyncio.wait_for(asyncio.gather(*(s._task for s, _, _ in players)), 10)
        return players

    async def test_both_enter_and_both_battle(self):
        for session, bridge, outcome in await self.both_enter({}):
            self.assertEqual(outcome.get("battle"), "started")
            self.assertFalse(session._battle_latched)
            self.assertFalse(bridge.outbox.controls)

    async def test_both_refused_both_windows_released(self):
        # The reproduction's condition on both PCs (a failed save each): both windows get their reason.
        for session, bridge, outcome in await self.both_enter({"host": "save_recovery_required",
                                                               "friend": "character_recovery_pending"}):
            frame = await asyncio.wait_for(bridge.outbox.get(), 1)
            self.assertEqual(unpack_screen(frame[5:], allow_release=True)[2], 3)
            self.assertTrue(outcome.get("refused"))
            self.assertNotIn("abandoned", outcome)
            self.assertFalse(session._battle_latched)
        self.assertEqual([s.menu.noticed for s in self.sessions],
                         ["Saving stopped: restart game", "Resolve the trade first"])

    async def test_one_refused_the_other_ends_unstarted(self):
        players = await self.both_enter({"friend": "save_not_ready"})
        (host, host_bridge, host_outcome), (friend, friend_bridge, friend_outcome) = players
        self.assertEqual(host_outcome.get("battle"), "entry cancelled")
        self.assertFalse(host._battle_latched)
        frame = await asyncio.wait_for(friend_bridge.outbox.get(), 1)
        self.assertEqual(unpack_screen(frame[5:], allow_release=True)[2], 3)
        self.assertFalse(friend._battle_latched)
