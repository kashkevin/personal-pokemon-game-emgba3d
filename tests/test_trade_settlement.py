"""A trade that fails part way is settled in the same session (the owner's report of 2026-10-20: a stuck trade left
the field frozen with saving disabled until a restart)."""
import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from emerald_multiplayer.launcher_session import LauncherSession


class TradeSettlementTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.cancelled, self.notices, self.abandoned = [], [], []
        async def trade_rpc(operation, **fields):
            self.cancelled.append((operation, fields))
            return {"trade": {"state": "aborted"}}
        self.companion = SimpleNamespace(connected=True, trade_rpc=trade_rpc)
        self.session = object.__new__(LauncherSession)
        self.session._companion = self.companion
        self.menu = SimpleNamespace(menu=SimpleNamespace(notice=self.notices.append),
                                    abandon_trade_dialog=lambda: self.abandoned.append(True))
        self.outcome = {"state": "aborted", "checkpoint": {"revision": 2}}
        async def cancel():
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
        self.assertEqual(self.cancelled, [("cancel", {"transaction_id": "t1", "generation": "g1"})])
        self.assertEqual(self.notices, ["Trade did not start: try again"])

    async def test_a_held_trade_is_settled_by_the_hosts_answer(self):
        self.coordinator.trade_path.write_text("{}")
        self.assertEqual(await self.settle(), self.outcome)
        self.assertEqual(self.abandoned, [True])            # the dead dialog queue is dropped
        self.assertEqual(self.notices, ["Trade cancelled: nothing changed"])
        self.outcome = {"state": "applied", "checkpoint": {"revision": 3}}   # the host had committed: applied
        self.notices.clear()
        self.assertEqual((await self.settle())["state"], "applied")
        self.assertEqual(self.notices, [])

    async def test_an_unsettled_trade_keeps_its_original_failure(self):
        self.coordinator.trade_path.write_text("{}")
        self.outcome = ConnectionError("host lost")
        original = ValueError("trade_offer_changed")
        with self.assertRaises(ValueError) as raised:
            await self.settle(original)
        self.assertIs(raised.exception, original)
        self.companion.connected = False                    # offline: cold start recovers it after a restart
        with self.assertRaises(ValueError):
            await self.settle(original)


if __name__ == "__main__":
    unittest.main()
