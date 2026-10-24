import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from emerald_multiplayer.player_menu import MenuScreen
from emerald_multiplayer.trade_menu import NativeTradeMenu, PartyChoice


class TradeMenuTests(unittest.IsolatedAsyncioTestCase):
    def make(self):
        actor, peer = "actor", "peer"
        view = dict(state="offering", transaction_id="transaction", generation="generation",
                    players=[actor, peer], offers=[], confirmations=[], fingerprint=None)
        companion = SimpleNamespace(config=SimpleNamespace(player_id=actor), trade_rpc=AsyncMock())
        dialog = SimpleNamespace(menu=SimpleNamespace(screen=MenuScreen(1, "Players", "", ())),
            open_trade_dialog=AsyncMock(), close_dialog=AsyncMock(), show_dialog=lambda screen: None)
        coordinator = SimpleNamespace(prepare=AsyncMock(), status=AsyncMock(return_value=view),
            keepalive=AsyncMock(), offer=AsyncMock(), confirm=AsyncMock(), resume=AsyncMock(return_value="receipt"),
            trade_path=SimpleNamespace(exists=lambda: False))
        with patch("emerald_multiplayer.trade_menu.LiveTradeCoordinator", return_value=coordinator):
            menu = NativeTradeMenu(companion, ".", dialog)
        return menu, dialog, coordinator, companion, view

    def test_render_has_explicit_disabled_eligibility_and_exact_fingerprint(self):
        menu, _, _, _, view = self.make()
        screen = menu._render(view, (PartyChoice(41, 25, 7, True), PartyChoice(42, 64, 8, False)))
        self.assertEqual(menu.actions[screen.rows[1].action], ("blocked", 42))
        self.assertEqual(menu.actions[1], ("offer", 41))
        self.assertEqual(menu.actions[7], ("ask_cancel", None))   # B asks first (the owner's report of 2026-10-24)
        menu.page = "review"
        view.update(fingerprint="exact-fingerprint", offers=[{"player_id": "actor", "species": 25}, {"player_id": "peer", "species": 265}])
        old = menu._render(view, ())
        self.assertIn(("confirm", "exact-fingerprint"), menu.actions.values())
        view["fingerprint"] = "changed-fingerprint"
        new = menu._render(view, ())
        self.assertGreater(new.revision, old.revision)
        self.assertNotIn(("confirm", "exact-fingerprint"), menu.actions.values())

    async def test_peer_commit_closes_native_menu_before_applying_receipt(self):
        menu, dialog, coordinator, _, view = self.make()
        order = []
        coordinator.status.side_effect = [view, {"state": "committed"}]
        async def close(screen): order.append("closed")
        async def resume():
            self.assertEqual(order, ["closed"])
            order.append("applied")
            return "receipt"
        dialog.close_dialog.side_effect = close
        coordinator.resume.side_effect = resume
        with patch("emerald_multiplayer.trade_menu.prepared_choices", return_value=(PartyChoice(1, 25, 5, True),)):
            self.assertEqual(await menu.run(view, 8), "receipt")
        coordinator.prepare.assert_awaited_once_with("transaction", "generation", 8)
        coordinator.confirm.assert_not_awaited()

    async def test_uncertain_menu_close_never_imports_or_discards_pending_trade(self):
        menu, dialog, coordinator, _, view = self.make()
        coordinator.status.side_effect = [view, {"state": "committed"}]
        dialog.close_dialog.side_effect = ConnectionError("lost release acknowledgment")
        with patch("emerald_multiplayer.trade_menu.prepared_choices", return_value=()):
            with self.assertRaises(ConnectionError):
                await menu.run(view, 8)
        coordinator.resume.assert_not_awaited()

    async def test_stale_displayed_choice_never_confirms_new_offers(self):
        menu, dialog, coordinator, _, view = self.make()
        menu.page = "review"
        view.update(fingerprint="old", offers=[{"player_id": "actor", "species": 25}, {"player_id": "peer", "species": 265}])
        changed = deepcopy(view)
        changed["fingerprint"] = "new"
        coordinator.status.side_effect = [view, changed, {"state": "aborted"}]
        dialog.dialog_choice = AsyncMock(return_value=SimpleNamespace(screen=2, action=3))
        with patch("emerald_multiplayer.trade_menu.prepared_choices", return_value=()):
            await menu.run(view, 8)
        coordinator.confirm.assert_not_awaited()
        coordinator.offer.assert_not_awaited()

    async def test_B_asks_and_only_a_considered_yes_cancels_after_the_window_closes(self):
        # The owner's report of 2026-10-24 ("when trade was being done it kicked us out and said trade cancelled"):
        # B and the one row under the cursor were Cancel trade. B now opens "Cancel the trade?". B leaves the game's
        # cursor on whatever row it was (the second row would have been Yes), so the page first has No alone - the
        # cursor goes to it - and Yes comes below it once the grace has passed; then a considered Yes cancels.
        import emerald_multiplayer.trade_menu as trade_menu
        menu, dialog, coordinator, companion, view = self.make()
        closed = False
        async def close(screen):
            nonlocal closed
            closed = True
        async def cancel(**fields):
            self.assertTrue(closed)
            return 'cancellation receipt'
        events = iter((7, None, "grace over", None, 2))
        seen = []
        async def choose():
            event = next(events)
            seen.append((menu.page, [row.label for row in menu.screen.rows]))
            if event == "grace over":
                trade_menu.ASK_CANCEL_GRACE_SECONDS = 0
                event = None
            if event is None:
                raise TimeoutError
            return SimpleNamespace(screen=menu.screen.revision, action=event)
        dialog.close_dialog.side_effect = close
        dialog.dialog_choice = choose
        coordinator.cancel = AsyncMock(side_effect=cancel)
        with patch.object(trade_menu, "ASK_CANCEL_GRACE_SECONDS", 30):
            with patch('emerald_multiplayer.trade_menu.prepared_choices', return_value=(PartyChoice(1, 25, 5, True),)):
                self.assertEqual(await menu.run(view, 8), 'cancellation receipt')
        self.assertEqual(seen[0][0], "party")
        self.assertEqual(seen[1], ("ask_cancel", ["No, keep trading"]))       # No alone: the cursor goes to it
        self.assertEqual(seen[2], ("ask_cancel", ["No, keep trading"]))
        self.assertEqual(seen[4], ("ask_cancel", ["No, keep trading", "Yes, cancel trade"]))
        coordinator.cancel.assert_awaited_once()
        self.assertTrue(menu.cancelled_here)
        companion.trade_rpc.assert_not_awaited()
        coordinator.resume.assert_not_awaited()

    def test_the_cancel_question_never_puts_yes_where_the_asking_press_left_the_cursor(self):
        # The game keeps its cursor row when the next screen comes (back to the top when that one is shorter).
        menu, _, _, _, view = self.make()
        menu.page, menu.ask_cursor = "ask_cancel", 4          # Cancel trade... on the review page: row 5
        self.assertEqual([r.label for r in menu._render(view, ()).rows], ["No, keep trading", "Yes, cancel trade"])
        menu.signature, menu.ask_cursor = None, 1              # a second row's press: a row that does nothing there
        screen = menu._render(view, ())
        self.assertEqual([r.label for r in screen.rows], ["No, keep trading", "B or No keeps trading", "Yes, cancel trade"])
        self.assertEqual(screen.rows[1].action, 0)
        menu.signature, menu.ask_cursor, menu.ask_shown = None, None, None    # B: any row; No alone until the grace
        self.assertEqual([r.label for r in menu._render(view, ()).rows], ["No, keep trading"])

    async def test_the_grace_counts_from_the_question_to_the_press_not_to_its_handling(self):
        # A Yes pressed 0.1 s after "Cancel the trade?" appeared but handled after a slow host round trip used to count
        # as a considered Yes (the grace was measured when the loop took the press off its queue).
        import emerald_multiplayer.trade_menu as trade_menu
        menu, dialog, coordinator, _, view = self.make()
        menu.page = "review"
        view.update(fingerprint="f", offers=[{"player_id": "actor", "species": 25}, {"player_id": "peer", "species": 265}])
        coordinator.status.side_effect = [view, view, view, view, {"state": "aborted"}]
        presses = iter((5, 2))                                   # Cancel trade... (row 5), then Yes (row 2)
        async def choose():
            action = next(presses, None)
            if action is None:
                raise TimeoutError
            if action == 2:
                await asyncio.sleep(0.2)                         # the press waits behind a slow round trip
            return SimpleNamespace(screen=menu.screen.revision, action=action)
        dialog.dialog_choice = choose
        dialog.arrival = lambda choice: menu.ask_shown + 0.05 if choice.action == 2 else None
        coordinator.cancel = AsyncMock(return_value="cancelled")
        with patch.object(trade_menu, "ASK_CANCEL_GRACE_SECONDS", 0.1):
            with patch('emerald_multiplayer.trade_menu.prepared_choices', return_value=()):
                self.assertEqual(await menu.run(view, 8), "receipt")
        coordinator.cancel.assert_not_awaited()                  # pressed 0.05 s after it asked: nothing

    async def test_a_confirm_or_offer_that_races_the_friend_shows_the_trade_again_and_never_cancels_it(self):
        # Both on the review page; the friend changes their Pokemon as this Confirm goes, or confirms as this offer
        # goes: the host refuses it (trade_offer_changed, trade_preparing). That refusal escaped the window, and the
        # launcher then cancelled the whole trade for both ("Your friend cancelled the trade").
        from emerald_multiplayer.companion import TradeError
        menu, dialog, coordinator, _, view = self.make()
        menu.page = "review"
        view.update(fingerprint="f1", offers=[{"player_id": "actor", "species": 25}, {"player_id": "peer", "species": 265}])
        changed = deepcopy(view)
        changed.update(fingerprint="f2", offers=[{"player_id": "actor", "species": 25}, {"player_id": "peer", "species": 1}])
        answers = iter([view, view, changed, changed, changed, changed])
        coordinator.status.side_effect = lambda: next(answers, {"state": "aborted"})
        coordinator.confirm.side_effect = TradeError("trade_offer_changed", "confirm the current complete offer")
        coordinator.offer.side_effect = TradeError("trade_preparing", "both offers are frozen")
        coordinator.cancel = AsyncMock()
        shown = []
        dialog.show_dialog = lambda screen: shown.append(screen)
        presses = iter(("Confirm this trade", "Change your Pokemon", "Pikachu Lv5"))
        async def choose():
            label = next(presses, None)
            if label is None:
                raise TimeoutError
            row = next(r for r in menu.screen.rows if r.label == label)
            return SimpleNamespace(screen=menu.screen.revision, action=row.action)
        dialog.dialog_choice = choose
        with patch('emerald_multiplayer.trade_menu.prepared_choices', return_value=(PartyChoice(1, 25, 5, True),)):
            self.assertEqual(await menu.run(view, 8), "receipt")
        coordinator.confirm.assert_awaited_once_with("f1")
        coordinator.offer.assert_awaited_once_with(1)
        coordinator.cancel.assert_not_awaited()
        self.assertTrue(any(s.status == "Offers changed; review again" and "Theirs: Bulbasaur" in [r.label for r in s.rows]
                            for s in shown))

    async def test_the_end_reason_is_asked_with_version_2_then_1_for_an_older_host(self):
        from emerald_multiplayer.companion import TradeError
        menu, _, _, companion, _ = self.make()
        menu.transaction_id = "transaction"
        asked = []
        async def trade_rpc(operation, **fields):
            asked.append(fields["end_reason_version"])
            if fields["end_reason_version"] == 2:
                raise TradeError("invalid_field", "unsupported read-only trade feature negotiation")
            return {"trade": {"transaction_id": "transaction", "state": "aborted", "reason": "expired"}}
        companion.trade_rpc = trade_rpc
        self.assertEqual(await menu.fetch_end_reason(), "expired")
        self.assertEqual(asked, [2, 1])

    def test_no_row_a_confirmation_leaves_under_the_cursor_cancels(self):
        # The game keeps its cursor row when the next screen comes (back to the top when that one is shorter): after
        # Confirm (row 3) the review page's row 3 and the trading page's first three rows choose nothing, and B asks.
        menu, _, _, _, view = self.make()
        menu.page = "review"
        view.update(fingerprint="f", confirmations=["actor"],
                    offers=[{"player_id": "actor", "species": 25}, {"player_id": "peer", "species": 265}])
        screen = menu._render(view, ())
        self.assertEqual(screen.rows[2].action, 0)
        self.assertEqual(menu.actions[7], ("ask_cancel", None))
        self.assertNotIn(("cancel", None), menu.actions.values())
        view.update(state="preparing", prepared=[], confirmations=["actor", "peer"])
        screen = menu._render(view, ())
        self.assertEqual([row.action for row in screen.rows[:3]], [0, 0, 0])
        self.assertEqual(menu.actions[screen.rows[3].action], ("ask_cancel", None))
        self.assertEqual(menu.actions[7], ("ask_cancel", None))
        self.assertNotIn(("cancel", None), menu.actions.values())
