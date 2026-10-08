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
            keepalive=AsyncMock(), offer=AsyncMock(), confirm=AsyncMock(), resume=AsyncMock(return_value="receipt"))
        with patch("emerald_multiplayer.trade_menu.LiveTradeCoordinator", return_value=coordinator):
            menu = NativeTradeMenu(companion, ".", dialog)
        return menu, dialog, coordinator, companion, view

    def test_render_has_explicit_disabled_eligibility_and_exact_fingerprint(self):
        menu, _, _, _, view = self.make()
        screen = menu._render(view, (PartyChoice(41, 25, 7, True), PartyChoice(42, 64, 8, False)))
        self.assertEqual(screen.rows[1].action, 0)
        self.assertEqual(menu.actions[1], ("offer", 41))
        self.assertEqual(menu.actions[7], ("cancel", None))
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

    async def test_B_cancellation_closes_window_before_existing_owner_resolves_fate(self):
        menu, dialog, coordinator, companion, view = self.make()
        closed = False
        async def close(screen):
            nonlocal closed
            closed = True
        async def cancel():
            self.assertTrue(closed)
            return 'cancellation receipt'
        async def choose():
            return SimpleNamespace(screen=menu.screen.revision, action=7)
        dialog.close_dialog.side_effect = close
        dialog.dialog_choice = choose
        coordinator.cancel = AsyncMock(side_effect=cancel)
        with patch('emerald_multiplayer.trade_menu.prepared_choices', return_value=(PartyChoice(1, 25, 5, True),)):
            self.assertEqual(await menu.run(view, 8), 'cancellation receipt')
        companion.trade_rpc.assert_not_awaited()
        coordinator.resume.assert_not_awaited()
