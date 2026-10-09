"""Interrupted closure uses real disposable SQLite/Flash, never native controls."""
import asyncio
import json
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from emerald_multiplayer.live_trade import LiveTradeError
from emerald_multiplayer.trade_close_recovery import read_original_trade, review_with_observer
import test_cold_start as cold_fixtures


class TradeCloseRecoveryTests(IsolatedAsyncioTestCase):
    setUp = cold_fixtures.ColdTradeTests.setUp
    tearDown = cold_fixtures.ColdTradeTests.tearDown
    commit = cold_fixtures.ColdTradeTests.commit
    journal = cold_fixtures.ColdTradeTests.journal
    paired = cold_fixtures.ColdTradeTests.paired

    def new_observer(self, intent):
        c = self.c
        c.config.expected_world_id = c.world_id
        self.binding = (c.world_id, c.server_epoch, c.session_epoch, c.save_profile,
                        c.config.player_id, c.config.build_id, c.config.ruleset_id)
        self.identity = tuple(intent[key] for key in
            ("transaction_id", "generation", "expected_revision", "incarnation", "runtime_id"))
        self.original = self.gate.trade_path.read_bytes()
        self.store.release_lease(c.config.player_id, c.session_epoch)
        c.session_epoch = self.store.acquire_lease(c.config.player_id, c.identity.credential)
        self.current_leases[c.config.player_id] = c.session_epoch

    async def review(self):
        return await review_with_observer(self.c, self.private, self.binding, self.identity,
            check_original=lambda: self.assertEqual(self.gate.trade_path.read_bytes(), self.original))

    async def test_verified_abort_checks_source_without_ack_then_cold_launch_rechecks(self):
        intent, payload = self.journal(commit_prepare=True)
        self.new_observer(intent)
        result = await self.review()
        self.assertEqual(result.state, "aborted")
        self.assertEqual(result.checkpoint, intent["prepared"])
        self.assertEqual(self.gate.trade_path.read_bytes(), self.original)
        self.assertFalse(self.save.exists())
        record = json.loads(result.evidence_path.read_bytes())
        self.assertEqual(record["original_identity"], list(self.identity))
        self.assertEqual(record["observer_session"][2], self.c.session_epoch)
        calls = [op for op, fields in self.c.server_calls]
        # The legacy desk already durably aborts on old-lease loss.
        self.assertIn("trade_status", calls); self.assertNotIn("trade_ack", calls)
        self.assertFalse(self.c.commands)
        # Closure review grants no startup authority: the normal closed gate
        # repeats host fate/head/byte checks before retiring the original.
        async with self.gate.open() as closed:
            self.assertEqual(closed.trade_result["state"], "aborted")
            self.assertEqual(closed.trade_result["generation"], intent["generation"])
            self.assertEqual(self.save.read_bytes(), payload)
        self.assertFalse(self.gate.trade_path.exists())

    async def test_missing_or_corrupt_frozen_source_refuses_before_cancellation(self):
        intent, payload = self.journal(commit_prepare=True)
        self.new_observer(intent)
        path = self.private / (intent["prepare_id"] + ".flash")
        for altered in (None, bytes(len(payload))):
            if altered is None:
                path.unlink()
            else:
                path.write_bytes(altered)
            with self.assertRaises(LiveTradeError):
                await self.review()
            self.assertFalse(self.c.server_calls)
        self.assertFalse(list(self.private.glob("*.close-review.*")))

    async def test_disconnected_auth_fields_stay_cleared_during_strict_original_read(self):
        intent, _ = self.journal(commit_prepare=True)
        self.new_observer(intent)
        # Matches production Companion._disconnect_remote, unlike a live
        # observer. No fabricated current authentication is written back.
        self.c.world_id = self.c.server_epoch = self.c.session_epoch = self.c.save_profile = None
        reader, actual, raw = read_original_trade(self.c, self.private, self.binding, self.identity)
        self.assertEqual(actual, intent)
        self.assertEqual(raw, self.original)
        self.assertIsNone(self.c.world_id); self.assertIsNone(self.c.session_epoch)
        self.assertFalse(self.c.server_calls)
        self.c.config.expected_world_id = "00000000-0000-0000-0000-000000000001"
        with self.assertRaises(LiveTradeError):
            read_original_trade(self.c, self.private, self.binding, self.identity)

    async def test_retained_world_player_build_rules_and_observer_world_are_not_interchangeable(self):
        intent, _ = self.journal(commit_prepare=True)
        self.new_observer(intent)
        for index in (0, 4, 5, 6):
            changed = list(self.binding); changed[index] = "different"
            with self.subTest(binding_index=index), self.assertRaises(LiveTradeError):
                read_original_trade(self.c, self.private, tuple(changed), self.identity)
        self.c.world_id = "00000000-0000-0000-0000-000000000001"
        with self.assertRaises(LiveTradeError):
            await self.review()
        self.assertFalse(self.c.server_calls)

    async def test_incomplete_export_never_becomes_permission_to_close(self):
        intent, _ = self.journal()
        self.new_observer(intent)
        with self.assertRaises(LiveTradeError):
            await self.review()
        self.assertFalse(self.c.server_calls)

    async def test_uncertain_cancel_keeps_original_even_if_server_canceled(self):
        intent, _ = self.journal(commit_prepare=True)
        self.new_observer(intent)
        async def lost(op, response):
            if op == "status":
                # Model the v2 persisted preparation's waiting response. The
                # legacy store below still validates exact cancellation.
                response["trade"] = dict(transaction_id=intent["transaction_id"],
                    state="preparing", generation=intent["generation"])
            if op == "cancel":
                self.assertEqual(self.c.server_calls[-1][1], dict(
                    transaction_id=intent["transaction_id"], generation=intent["generation"]))
                raise asyncio.TimeoutError("lost cancellation acknowledgment")
        self.c.trade_hook = lost
        with self.assertRaises(asyncio.TimeoutError):
            await self.review()
        self.assertFalse(list(self.private.glob("*.close-review.*")))
        self.assertEqual(self.gate.trade_path.read_bytes(), self.original)
        self.c.trade_hook = None
        self.assertEqual((await self.review()).state, "aborted")

    async def test_observer_reconnect_or_native_bridge_refuses(self):
        intent, _ = self.journal(commit_prepare=True)
        self.new_observer(intent)
        async def changed(op, response):
            if op == "status":
                self.c.server_epoch += 1
        self.c.trade_hook = changed
        with self.assertRaises(LiveTradeError):
            await self.review()
        self.assertNotIn("trade_cancel", [op for op, _ in self.c.server_calls])
        self.c.trade_hook = None; self.c._bridge = object()
        with self.assertRaises(LiveTradeError):
            await self.review()

    async def test_committed_without_exact_retained_candidate_refuses_without_ack(self):
        intent, payload = self.journal(commit_prepare=True)
        self.paired(intent, payload)
        self.new_observer(intent)
        with self.assertRaises(LiveTradeError):
            await self.review()
        self.assertNotIn("trade_ack", [op for op, _ in self.c.server_calls])
        self.assertFalse(self.save.exists())

    async def test_altered_terminal_fate_or_newer_canonical_head_refuses(self):
        intent, _ = self.journal(commit_prepare=True)
        self.new_observer(intent)
        async def foreign(op, response):
            if op in {"status", "cancel"}:
                response["trade"]["transaction_id"] = "00000000-0000-0000-0000-000000000001"
        self.c.trade_hook = foreign
        with self.assertRaises(LiveTradeError):
            await self.review()
        self.c.trade_hook = None
        self.commit(self.players[0], self.c.session_epoch, self.c.head().payload, 2)
        with self.assertRaises(LiveTradeError):
            await self.review()
        self.assertFalse(list(self.private.glob("*.close-review.*")))

    async def test_committed_candidate_needs_matching_bytes_and_cold_result_is_retained(self):
        intent, payload = self.journal(commit_prepare=True)
        self.paired(intent, payload)
        self.new_observer(intent)
        # This legacy SQLite fixture has no native preparation transcript.
        # Its reader is substituted only to exercise canonical-byte binding;
        # real v2 transcript tampering is covered in RetainedEffectTests.
        with patch("emerald_multiplayer.cold_start._ClosedTradeReader._prepared_candidate",
                   return_value=self.c.head().payload):
            result = await self.review()
        self.assertEqual(result.state, "committed")
        self.assertNotIn("trade_ack", [op for op, _ in self.c.server_calls])
        with patch("emerald_multiplayer.cold_start._ClosedTradeReader._prepared_candidate",
                   return_value=bytes(131072)):
            with self.assertRaises(LiveTradeError):
                await self.review()
        async with self.gate.open() as closed:
            self.assertEqual(closed.trade_result["state"], "applied")
            self.assertEqual(closed.trade_result["checkpoint"]["revision"], 3)
            self.assertEqual(json.loads((closed.evidence_path.parent / "trade-result.json").read_bytes())
                             ["record"], closed.trade_result)
        self.assertIn("trade_ack", [op for op, _ in self.c.server_calls])
