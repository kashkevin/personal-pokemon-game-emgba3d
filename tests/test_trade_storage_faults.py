"""A world trade whose host refuses a database write (a full disk) at each of the trade's writes, and whose apply
receipt cannot be written on either player's PC: once there is room, every trade is made or not made on both sides,
nothing lost or doubled, every journal resolved and the database intact (TEST_LEDGER "Save integrity: the host's disk
full during a world trade", where a real full disk and every one of the trade's transactions were tried).

The trade fixture of test_live_trade: the real trade desk, store, codecs and coordinators and a strict simulated game.
"""
from __future__ import annotations

from contextlib import contextmanager
import errno
import sqlite3
import unittest
from unittest.mock import patch

from emerald_multiplayer import live_trade, storage
from emerald_multiplayer.flash import inspect_flash
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, inspect_ownership
from emerald_multiplayer.trade_storage import TradeCheckpointStore

import test_live_trade

# The store's methods a trade's host calls: those that write, then reads (a refused read is an I/O error rather than a
# full disk, but the trade must survive it the same way).
WRITES = ("commit_checkpoint", "commit_trade", "acknowledge_trade")
READS = ("read_checkpoint", "read_trade", "pending_trade_recovery")


def serials(payload):
    return sorted(record.serial for record in
                  inspect_ownership(inspect_flash(payload, save_profile=OWNERSHIP_PROFILE)).records)


class HostRefusals:
    """Numbers the host store's transactions by the store method that opened them (not those the simulated game opens
    for its own checks: the real game never reads the host's database) and refuses the target one at its COMMIT, as
    SQLite does when the write-ahead log cannot grow (SQLITE_FULL); the store rolls it back."""

    def __init__(self, target=None):
        self.target, self.seen, self.refused, self.methods, self.in_game = target, [], [], [], 0

    @contextmanager
    def installed(self):
        real_transaction = storage.CheckpointStore._transaction
        refusals = self

        @contextmanager
        def transaction(store):
            index = None
            if refusals.methods and not refusals.in_game:
                refusals.seen.append(refusals.methods[-1])
                index = len(refusals.seen) - 1
            with real_transaction(store):
                yield
                if index is not None and index == refusals.target:
                    refusals.refused.append(refusals.seen[index])
                    full = sqlite3.OperationalError("database or disk is full")
                    full.sqlite_errorcode, full.sqlite_errorname = sqlite3.SQLITE_FULL, "SQLITE_FULL"
                    raise full

        def labelled(name):
            real = getattr(TradeCheckpointStore, name)

            def method(store, *args, **kwargs):
                refusals.methods.append(name)
                try:
                    return real(store, *args, **kwargs)
                finally:
                    refusals.methods.pop()
            return method

        real_save_rpc = test_live_trade.TradeCompanion.save_rpc

        async def save_rpc(companion, *args, **kwargs):
            refusals.in_game += 1
            try:
                return await real_save_rpc(companion, *args, **kwargs)
            finally:
                refusals.in_game -= 1

        with patch.object(storage.CheckpointStore, "_transaction", transaction), \
                patch.object(test_live_trade.TradeCompanion, "save_rpc", save_rpc):
            patches = [patch.object(TradeCheckpointStore, name, labelled(name)) for name in WRITES + READS]
            for item in patches:
                item.start()
            try:
                yield self
            finally:
                for item in reversed(patches):
                    item.stop()


class TradeStorageFaultTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self):
        fixture = test_live_trade.LiveTradeTests("test_two_explicit_consents_then_own_canonical_apply_ack_and_release")
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        return fixture

    async def trade(self, fixture):
        """The two players' steps of a whole trade; returns the first failure (the trade stopping there), or None."""
        try:
            view = await fixture.ready()
            for coordinator in fixture.coordinators:
                await coordinator.confirm(view["fingerprint"])
            for coordinator in fixture.coordinators:
                await coordinator.prepare_recipient()
            for coordinator in fixture.coordinators:
                await coordinator.resume()
        except Exception as error:   # noqa: BLE001 - the refusal, as each step meets it
            return error
        return None

    async def settle(self, fixture):
        """With room again, as the trade window does: resume while a journal stands, then cancel a proposal still open."""
        for _ in range(4):
            for coordinator in fixture.coordinators:
                if coordinator.trade_path.exists():
                    await coordinator.resume()      # a proposal still open answers its state: cancelled below
            if not any(coordinator.trade_path.exists() for coordinator in fixture.coordinators):
                break
        for coordinator in fixture.coordinators:
            if coordinator.trade_path.exists():
                await coordinator.cancel()

    def assert_whole(self, fixture, before, case):
        heads = [serials(companion.head().payload) for companion in fixture.companions]
        traded = [sorted(before[0][1:] + before[1][:1]), sorted(before[1][1:] + before[0][:1])]
        self.assertIn(heads, (before, traded), case)                    # made or not made, on both sides
        for companion, coordinator, head in zip(fixture.companions, fixture.coordinators, heads):
            self.assertFalse(coordinator.trade_path.exists(), case)     # every journal resolved
            self.assertFalse(companion.active, case)                    # the game's hold ended
            self.assertEqual(serials(companion.rom_flash), head, case)  # the game's save is its world head
            self.assertEqual(fixture.store.pending_trade_recovery(companion.config.player_id,
                                                                  companion.session_epoch), (), case)
        fixture.store.integrity_check()
        return heads == traded

    async def test_a_host_write_refused_at_each_of_the_trades_writes_leaves_every_outcome_whole(self):
        fixture = self.fixture()
        with HostRefusals().installed() as counted:
            self.assertIsNone(await self.trade(fixture))
        targets = [index for index, name in enumerate(counted.seen) if name in WRITES]
        targets += [counted.seen.index(name) for name in READS]
        self.assertEqual(sorted(name for name in counted.seen if name in WRITES),
                         ["acknowledge_trade"] * 2 + ["commit_checkpoint"] * 4 + ["commit_trade"])
        outcomes = []
        for target in targets:
            fixture = self.fixture()
            before = [serials(companion.head().payload) for companion in fixture.companions]
            with HostRefusals(target).installed() as refusals:
                failure = await self.trade(fixture)
                case = f"{counted.seen[target]} (transaction {target})"
                self.assertEqual(refusals.refused, [counted.seen[target]], case)
                self.assertIsNotNone(failure, case)
                await self.settle(fixture)
            outcomes.append(self.assert_whole(fixture, before, case))
        # Refused before the trade's commit it is not made; after it, it is.
        self.assertIn(True, outcomes)
        self.assertIn(False, outcomes)

    async def test_a_players_disk_full_at_each_of_the_trades_journal_writes_leaves_every_outcome_whole(self):
        # The other side of it (KNOWN_ISSUES MS-215's section in TEST_LEDGER): each of the trade's local journal writes
        # (the journal and its immutable files, both players) refused in turn with ENOSPC, then room again.
        real = live_trade._atomic
        written = []

        def counting(path, payload, **kwargs):
            written.append(path.name)
            return real(path, payload, **kwargs)

        fixture = self.fixture()
        with patch.object(live_trade, "_atomic", counting):
            self.assertIsNone(await self.trade(fixture))
        self.assertGreater(len(written), 20)
        outcomes = []
        for target in range(len(written)):
            fixture = self.fixture()
            before = [serials(companion.head().payload) for companion in fixture.companions]
            seen = []

            def refusing(path, payload, **kwargs):
                seen.append(path.name)
                if len(seen) == target + 1:
                    raise OSError(errno.ENOSPC, "No space left on device")
                return real(path, payload, **kwargs)

            case = f"journal write {target + 1} of {len(written)}"
            with patch.object(live_trade, "_atomic", refusing):
                failure = await self.trade(fixture)
            self.assertIsInstance(failure, OSError, case)
            await self.settle(fixture)
            outcomes.append(self.assert_whole(fixture, before, case))
        self.assertIn(True, outcomes)
        self.assertIn(False, outcomes)

    async def test_the_apply_receipt_refused_on_either_side_finishes_on_resume(self):
        for side in (0, 1):
            fixture = self.fixture()
            before = [serials(companion.head().payload) for companion in fixture.companions]
            real = live_trade.record_live_apply
            refused = []

            def receipt(path, *args, **kwargs):
                if not refused and path.parent == fixture.coordinators[side].directory:
                    refused.append(path.name)
                    raise OSError(errno.ENOSPC, "No space left on device")
                return real(path, *args, **kwargs)

            with patch.object(live_trade, "record_live_apply", receipt):
                failure = await self.trade(fixture)
            self.assertIsInstance(failure, OSError, side)
            self.assertEqual(len(refused), 1, side)
            await self.settle(fixture)
            self.assertTrue(self.assert_whole(fixture, before, side))   # traded: the game held it, the host committed
            staging = [path.name for coordinator in fixture.coordinators for path in coordinator.directory.iterdir()
                       if path.name.endswith(".stage")]
            self.assertEqual(staging, [])
