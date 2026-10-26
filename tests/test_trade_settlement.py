"""A trade that fails part way is settled in the same session (the owner's report of 2026-10-20: a stuck trade left
the field frozen with saving disabled until a restart)."""
import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from emerald_multiplayer.launcher_session import LauncherSession


class TradeSettlementTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.cancelled, self.notices, self.abandoned, self.banners = [], [], [], []
        self.host_version = None          # the end_reason_version the host acknowledges (2: it records automatic cancels)
        async def trade_rpc(operation, **fields):
            self.cancelled.append((operation, fields))
            if operation == "status" and self.host_version is not None:
                return {"trade": {"state": "offering"}, "end_reason_version": self.host_version}
            return {"trade": {"state": "aborted"}}
        self.companion = SimpleNamespace(connected=True, trade_rpc=trade_rpc, show_local_notice=self.banners.append)
        self.session = object.__new__(LauncherSession)
        self.session._companion = self.companion
        self.menu = SimpleNamespace(menu=SimpleNamespace(notice=self.notices.append),
                                    abandon_trade_dialog=lambda: self.abandoned.append(True))
        self.outcome = {"state": "aborted", "checkpoint": {"revision": 2}}
        self.automatic = []
        self.failures = []                # raised by the first cancels, one each, before self.outcome
        async def cancel(*, automatic=False):
            self.automatic.append(automatic)
            if self.failures:
                raise self.failures.pop(0)
            if isinstance(self.outcome, Exception):
                raise self.outcome
            return self.outcome
        self.coordinator = SimpleNamespace(trade_path=self.directory / "pending-trade.json", cancel=cancel)
        self.trade_menu = SimpleNamespace(coordinator=self.coordinator, _completion=lambda result: result)
        self.descriptor = {"transaction_id": "t1", "generation": "g1"}

    def tearDown(self):
        for path in self.directory.iterdir():
            path.unlink()
        self.directory.rmdir()

    async def settle(self, error=None):
        return await self.session._settle_failed_trade(self.trade_menu, self.menu, self.descriptor,
                                                        error or ValueError("trade_offer_changed"))

    async def test_a_trade_that_never_held_cancels_its_proposal(self):
        self.assertIsNone(await self.settle())
        # The launcher's own cancel: an older host (no end_reason_version 2) gets the plain cancel it knows.
        self.assertEqual(self.cancelled, [("status", {"transaction_id": "t1", "end_reason_version": 2}),
                                          ("cancel", {"transaction_id": "t1", "generation": "g1"})])
        self.assertEqual(self.notices, ["Trade did not start: try again"])
        # The menu has closed: the game's banner says it at once (the owner's report of 2026-10-23, "it just kicks
        # you out of the screen"), and why (the error's code), within its two lines of 32 characters.
        self.assertEqual(self.banners, ["Trade did not start (retry).|Code: ValueError"])
        self.banners.clear()
        from emerald_multiplayer.live_trade import LiveTradeError
        self.assertIsNone(await self.settle(LiveTradeError("trade_preparation_mismatch", "changed")))
        self.assertEqual(self.banners, ["Trade did not start (retry).|Code: trade_preparation_mismatch"])
        self.assertTrue(all(len(line) <= 32 for line in self.banners[0].split("|")))

    async def test_an_automatic_cancel_is_never_sent_as_the_players_choice(self):
        # The owner's reports of 2026-10-24: a failure on one side made the other's banner say "Your friend cancelled
        # the trade" although nobody chose it. A host that records it (end_reason_version 2) is told the cause.
        self.host_version = 2
        self.assertIsNone(await self.settle())
        self.assertEqual(self.cancelled[-1], ("cancel", {"transaction_id": "t1", "generation": "g1", "cause": "automatic"}))
        self.coordinator.trade_path.write_text("{}")
        await self.settle()
        self.assertEqual(self.automatic, [True])         # the coordinator's cancel is marked as the launcher's own

    async def test_a_held_trade_is_settled_by_the_hosts_answer(self):
        self.coordinator.trade_path.write_text("{}")
        self.assertEqual(await self.settle(), self.outcome)
        self.assertEqual(self.abandoned, [True])            # the dead dialog queue is dropped
        self.assertEqual(self.notices, ["Trade cancelled: nothing changed"])
        self.assertEqual(self.banners, ["Trade cancelled; no change.|Code: ValueError"])
        self.outcome = {"state": "applied", "checkpoint": {"revision": 3}}   # the host had committed: applied
        self.notices.clear()
        self.banners.clear()
        self.trade_menu.peer_species = 1      # what the friend offered, as the trade window last showed it
        self.assertEqual((await self.settle())["state"], "applied")
        self.assertEqual(self.notices, [])
        self.assertEqual(self.banners, ["Trade complete!|You received Bulbasaur."])

    async def test_an_unsettled_trade_keeps_its_original_failure(self):
        self.coordinator.trade_path.write_text("{}")
        self.outcome = ConnectionError("host lost")
        original = ValueError("trade_offer_changed")
        with self.assertRaises(ValueError) as raised, \
                patch("emerald_multiplayer.launcher_session.TRADE_SETTLE_RETRY_SECONDS", 0):
            await self.settle(original)
        self.assertIs(raised.exception, original)
        self.assertEqual(self.automatic, [True, True, True])    # tried TRADE_SETTLE_ATTEMPTS times
        self.assertEqual(self.banners, ["Ending the trade: please wait|Code: ValueError",
                                        "Trade stopped; keep game open|Code: ValueError"])
        self.companion.connected = False                    # offline: cold start recovers it after a restart
        with self.assertRaises(ValueError):
            await self.settle(original)
        self.assertEqual(self.banners[-1], "Trade stopped: host lost.|Code: ValueError")
        self.assertTrue(all(len(line) <= 32 for text in self.banners for line in text.split("|")))

    async def test_a_passing_failure_of_the_settlement_is_tried_again(self):
        # 2026-10-26: one failed try (a reply too late, a reconnect it can resume after, a busy game) left the game held
        # with saving off until a restart. The cancel is journal-driven: the next try picks up where this one ended.
        from emerald_multiplayer.live_trade import LiveTradeError
        self.coordinator.trade_path.write_text("{}")
        self.failures = [TimeoutError(), LiveTradeError("rom_busy", "the game is busy")]
        with patch("emerald_multiplayer.launcher_session.TRADE_SETTLE_RETRY_SECONDS", 0):
            self.assertEqual(await self.settle(), self.outcome)
        self.assertEqual(self.automatic, [True, True, True])
        self.assertEqual(self.banners, ["Ending the trade: please wait|Code: ValueError",
                                        "Trade cancelled; no change.|Code: ValueError"])
        # A failure that another try cannot change (the journal or the game's hold disagree) is not tried again.
        self.automatic.clear()
        self.banners.clear()
        self.outcome = LiveTradeError("recovery_required", "ROM trade binding does not match this running game")
        with self.assertRaises(ValueError), patch("emerald_multiplayer.launcher_session.TRADE_SETTLE_RETRY_SECONDS", 0):
            await self.settle()
        self.assertEqual(self.automatic, [True])
        self.assertEqual(self.banners, ["Trade stopped; keep game open|Code: ValueError"])

    def test_every_finished_trade_says_how_it_ended(self):
        # After both confirmed, the trade window closes before the import: the banner says the outcome (it used to say
        # nothing at all, the owner's report of 2026-10-23).
        menu = SimpleNamespace(peer_species=25, cancelled_here=False)
        for result, expected in (({"state": "applied"}, "Trade complete!|You received Pikachu."),
                                 ({"state": "applied", "received": {"species": 1, "evolved": False}},
                                  "Trade complete!|You received Bulbasaur."),
                                 ({"state": "aborted"}, "Trade ended by friend or host.|Nothing changed.")):
            self.banners.clear()
            self.session._trade_outcome_banner(menu, result)
            self.assertEqual(self.banners, [expected])
            self.assertTrue(all(len(line) <= 32 for line in expected.split("|")))
        self.banners.clear()
        self.session._trade_outcome_banner(SimpleNamespace(peer_species=None, cancelled_here=True), {"state": "aborted"})
        self.assertEqual(self.banners, ["You cancelled the trade.|Nothing changed."])
        # Why the host ended it, when it could say (the owner's report of 2026-10-24: "it kicked us out and said trade
        # cancelled", with no word of who or why).
        for reason, first in (("partner_cancelled", "Your friend cancelled the trade."),
                              ("partner_stopped", "Trade stopped on friend's side."),
                              ("expired", "The trade timed out."),
                              ("partner_disconnected", "Your friend lost connection."),
                              ("you_disconnected", "Lost connection to the host.")):
            self.banners.clear()
            self.session._trade_outcome_banner(
                SimpleNamespace(peer_species=None, cancelled_here=False, end_reason=reason), {"state": "aborted"})
            self.assertEqual(self.banners, [first + "|Nothing changed."])
            self.assertTrue(all(len(line) <= 32 for line in self.banners[0].split("|")))

    async def test_a_trade_the_host_had_ended_says_why(self):
        self.coordinator.trade_path.write_text("{}")
        async def fetch_end_reason():
            return "expired"
        self.trade_menu.fetch_end_reason = fetch_end_reason
        from emerald_multiplayer.companion import TradeError
        await self.settle(TradeError("trade_aborted", "no uncommitted proposal remains"))
        self.assertEqual(self.banners, ["The trade timed out.|Code: trade_aborted"])
        # This side's own error keeps the generic line and its code.
        self.banners.clear()
        await self.settle(TradeError("revision_conflict", "a participant's checkpoint changed"))
        self.assertEqual(self.banners, ["Trade cancelled; no change.|Code: revision_conflict"])


if __name__ == "__main__":
    unittest.main()
