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
        # B and the one row under the cursor were Cancel trade. B now opens "Cancel the trade?" (No first), a Yes in the
        # moment that page appears is a second press and counts for nothing, a later Yes cancels.
        import emerald_multiplayer.trade_menu as trade_menu
        menu, dialog, coordinator, companion, view = self.make()
        closed = False
        async def close(screen):
            nonlocal closed
            closed = True
        async def cancel():
            self.assertTrue(closed)
            return 'cancellation receipt'
        presses = iter((7, 2, 2))
        seen = []
        async def choose():
            action = next(presses)
            seen.append((menu.page, [row.label for row in menu.screen.rows]))
            if len(seen) == 3:
                trade_menu.ASK_CANCEL_GRACE_SECONDS = 0
            return SimpleNamespace(screen=menu.screen.revision, action=action)
        dialog.close_dialog.side_effect = close
        dialog.dialog_choice = choose
        coordinator.cancel = AsyncMock(side_effect=cancel)
        with patch.object(trade_menu, "ASK_CANCEL_GRACE_SECONDS", 30):
            with patch('emerald_multiplayer.trade_menu.prepared_choices', return_value=(PartyChoice(1, 25, 5, True),)):
                self.assertEqual(await menu.run(view, 8), 'cancellation receipt')
        self.assertEqual(seen[0][0], "party")
        self.assertEqual(seen[1], ("ask_cancel", ["No, keep trading", "Yes, cancel trade"]))
        self.assertEqual(seen[2][0], "ask_cancel")          # the quick Yes changed nothing
        coordinator.cancel.assert_awaited_once()
        self.assertTrue(menu.cancelled_here)
        companion.trade_rpc.assert_not_awaited()
        coordinator.resume.assert_not_awaited()

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
