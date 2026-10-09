"""Disposable persistence/protocol fixtures, not native gameplay acceptance."""
import asyncio
from dataclasses import replace
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from emerald_multiplayer.flash import inspect_flash, SAVED_PARTY_OFFSET
from emerald_multiplayer.ownership import inspect_ownership
from emerald_multiplayer.storage import StorageError
from emerald_multiplayer.trade_desk import TradeDesk
from emerald_multiplayer.trade_effect_backend import TradeEffectsBackend
from emerald_multiplayer.trade_effect_flash import prepare_effect_pair, _private_blocks
from emerald_multiplayer.trade_effect_preparation import decode_effect_plan, validate_effect_preparation
from emerald_multiplayer.trade_effect_storage import enable_trade_effects, read_effect_policy
from emerald_multiplayer.trade_flash import _party_record
from emerald_multiplayer.trade_friendship_migration import enable_friendship_history, FriendshipHistoryLedger
from emerald_multiplayer.trade_storage import TradeCheckpointStore
from test_flash import _rewrite
from test_trade_friendship import decode_fixture, encode_fixture
import test_trade_storage as storage_fixture
from test_trade_storage import BUILD, RULESET

POLICY = "gen6-stable-world-region-v1"


class NonEvolvingFixtureReplay:
    """Emulates only fixture species265 for transaction tests; never native proof."""
    engine_source_sha256 = "a" * 64
    profile_game_version = 3

    def __init__(self):
        self.calls = 0
        self.entered = asyncio.Event()
        self.gate = None
        self.corrupt = False

    async def prepare_pair(self, a, pa, b, pb, **arguments):
        self.calls += 1
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        snapshots = [inspect_flash(cp.payload, save_profile=cp.save_profile) for cp in (a, b)]
        def record(incoming, sent, friendship, choices):
            if choices:
                raise ValueError("fixture never evolves")
            logical = decode_fixture(incoming)
            logical[0][9] = friendship
            return encode_fixture(incoming, logical)
        def blocks(block1, block2, peer, outgoing, incoming, friendship, choices):
            i = next(i for i, snapshot in enumerate(snapshots) if snapshot.save_block1 == block1)
            received = peer[SAVED_PARTY_OFFSET + incoming * 100:SAVED_PARTY_OFFSET + (incoming + 1) * 100]
            sent = block1[SAVED_PARTY_OFFSET + outgoing * 100:SAVED_PARTY_OFFSET + (outgoing + 1) * 100]
            return _private_blocks(snapshots[i], snapshots[1-i], SAVED_PARTY_OFFSET + outgoing * 100,
                                   received, record(received, sent, friendship, choices))
        pair = prepare_effect_pair(a, pa, b, pb, engine_source_sha256=self.engine_source_sha256,
            profile_game_version=3, replay_native=record, replay_save_native=blocks, **arguments)
        if self.corrupt:
            pair = replace(pair, after_a=pair.after_a[:-1] + bytes([pair.after_a[-1] ^ 1]))
        return pair

    async def close(self):
        pass


class PublicEffectBackendTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = storage_fixture.TradeStorageTests(); self.fixture.setUp()
        self.store = self.fixture.store
        self.root = Path(self.fixture.temp.name)
        for i, cp in enumerate(self.fixture.heads):
            payload = _rewrite(cp.payload, 0, 0, 0, (b"ALICE" if i == 0 else b"BOB") + b"\xff" * (3 if i == 0 else 5))
            self.fixture.heads[i] = self.store.commit_checkpoint(cp.player_id, self.fixture.leases[i], str(uuid4()), cp.revision,
                payload, BUILD, RULESET, self.store.save_profile)
        for p, lease in zip(self.fixture.players, self.fixture.leases):
            self.store.release_lease(p.player_id, lease)
        enable_friendship_history(self.store, self.root / "before-history.sqlite3")
        enable_trade_effects(self.store, self.root / "before-effects.sqlite3", policy_id=POLICY)
        self.leases = {p.player_id: self.store.acquire_lease(p.player_id, p.credential) for p in self.fixture.players}
        self.adapter = NonEvolvingFixtureReplay()
        self.backend = TradeEffectsBackend(TradeDesk(self.store, self.leases.get), self.adapter, POLICY)
        await self.backend.start()
        self.tx = str(uuid4())

    async def asyncTearDown(self):
        await self.backend.close()
        self.fixture.store = self.store
        self.fixture.tearDown()

    def actor(self, i):
        p = self.fixture.players[i].player_id
        return p, self.leases[p]

    def prepare(self):
        view = self.backend.open(*self.actor(0), self.actor(1)[0], self.tx)
        for i in (0, 1):
            cp = self.store.read_checkpoint(*self.actor(i))
            view = self.backend.offer(*self.actor(i), self.tx, view["generation"], cp.revision, cp.sha256,
                                      self.fixture.grants[i].start)
        for i in (0, 1):
            view = self.backend.confirm(*self.actor(i), self.tx, view["generation"], view["fingerprint"])
        self.view = view
        self.proposal = self.backend.desk._proposals[self.tx]
        return self.proposal

    async def receipts(self):
        proposal = self.proposal
        descriptions = proposal.preparations
        first = descriptions[0]
        sources = tuple(proposal.offers[p].checkpoint for p in proposal.players)
        plans = tuple(decode_effect_plan(v) for v in first["effects"]["offers"])
        pair = await NonEvolvingFixtureReplay().prepare_pair(sources[0], plans[0], sources[1], plans[1],
            transaction_id=self.tx, generation=proposal.generation, fingerprint=first["fingerprint"],
            leases=proposal.leases, choices_a=(), choices_b=())
        return {p: dict(choices=[], candidate_sha256=hashlib.sha256(payload).hexdigest(), candidate_size=len(payload),
            record_sha256=hashlib.sha256(witness.candidate).hexdigest()) for p, payload, witness in
            zip(proposal.players, (pair.after_a, pair.after_b), (pair.recipient_a, pair.recipient_b))}

    def submit(self, actor, receipt):
        description = self.proposal.preparations[0]
        return self.backend.prepared(actor, self.leases[actor], self.tx, self.proposal.generation,
            description["fingerprint"], description["preparation_id"], receipt)

    async def finish(self):
        jobs = tuple(self.backend.jobs.values())
        await asyncio.gather(*jobs, return_exceptions=True)
        await asyncio.sleep(0)

    async def test_atomic_effects_histories_and_fresh_restart_replay_barrier(self):
        proposal = self.prepare()
        for description in proposal.preparations:
            validate_effect_preparation(description)
        receipts = await self.receipts()
        before = [self.store.read_checkpoint(*self.actor(i)) for i in (0, 1)]
        self.submit(proposal.players[0], receipts[proposal.players[0]])
        self.assertEqual([self.store.read_checkpoint(*self.actor(i)) for i in (0, 1)], before)
        self.assertEqual(self.adapter.calls, 0)
        self.submit(proposal.players[1], receipts[proposal.players[1]])
        await self.finish()
        self.assertEqual(self.backend.errors, {})
        self.assertEqual(self.backend.status(*self.actor(0), self.tx)["state"], "committed")
        self.assertEqual(self.store._connection.execute("SELECT COUNT(*) FROM trade_effect_commits").fetchone()[0], 1)
        self.store.integrity_check()
        for i in (0, 1):
            incoming = self.fixture.grants[1-i].start
            history = FriendshipHistoryLedger(self.store).read_current(*self.actor(i), incoming)
            self.assertEqual(history.handling_friendship, 70)
        await self.backend.close(); self.store.close()
        self.store = TradeCheckpointStore(self.fixture.path, BUILD, RULESET)
        self.store.begin_server_boot()
        self.leases = {p.player_id: self.store.acquire_lease(p.player_id, p.credential) for p in self.fixture.players}
        cp = self.store.read_checkpoint(*self.actor(0))
        with self.assertRaises(StorageError) as caught:
            self.store.commit_checkpoint(*self.actor(0), str(uuid4()), cp.revision, cp.payload, BUILD, RULESET, self.store.save_profile)
        self.assertEqual(caught.exception.code, "trade_effect_replay_required")
        self.adapter = NonEvolvingFixtureReplay()
        self.backend = TradeEffectsBackend(TradeDesk(self.store, self.leases.get), self.adapter, read_effect_policy(self.store))
        await self.backend.start()
        self.assertEqual(self.adapter.calls, 1)
        self.assertEqual(self.backend.status(*self.actor(1), self.tx)["state"], "committed")
        self.store.integrity_check()

    async def test_cancel_during_native_replay_prevents_both_publications(self):
        proposal = self.prepare(); receipts = await self.receipts()
        self.adapter.gate = asyncio.Event()
        for p in proposal.players:
            self.submit(p, receipts[p])
        await self.adapter.entered.wait()
        self.backend.cancel(*self.actor(0), self.tx, proposal.generation)
        self.adapter.gate.set(); await self.finish()
        self.assertEqual(self.store._connection.execute("SELECT COUNT(*) FROM trade_transactions").fetchone()[0], 0)
        self.assertEqual(self.backend.status(*self.actor(1), self.tx)["state"], "aborted")
        self.store.integrity_check()

    async def test_second_membership_failure_rolls_back_saves_effect_and_handler_rows(self):
        proposal = self.prepare(); receipts = await self.receipts()
        counts = {name: self.store._connection.execute("SELECT COUNT(*) FROM " + name).fetchone()[0] for name in self.store._schema}
        original, calls = self.store._membership, 0
        def fail(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("fixture second membership refusal")
            return original(*args)
        with patch.object(self.store, "_membership", fail):
            for p in proposal.players:
                self.submit(p, receipts[p])
            await self.finish()
        self.assertIn(self.tx, self.backend.errors)
        self.assertEqual(counts, {name: self.store._connection.execute("SELECT COUNT(*) FROM " + name).fetchone()[0] for name in self.store._schema})
        self.assertEqual(self.backend._saved(self.tx)["state"], "active")
        self.store.integrity_check()

    async def test_bad_native_candidate_refuses_without_single_recipient_commit(self):
        proposal = self.prepare(); receipts = await self.receipts()
        self.adapter.corrupt = True
        for p in proposal.players:
            self.submit(p, receipts[p])
        await self.finish()
        self.assertIn(self.tx, self.backend.errors)
        self.assertEqual(self.store._connection.execute("SELECT COUNT(*) FROM trade_transactions").fetchone()[0], 0)
        self.store.integrity_check()

    async def test_uncertain_open_commit_restores_same_durable_generation(self):
        saved = self.backend._save
        def uncertain(proposal, state="active"):
            saved(proposal, state)
            raise OSError("fixture receipt lost after durable commit")
        with patch.object(self.backend, "_save", uncertain), self.assertRaises(OSError):
            self.backend.open(*self.actor(0), self.actor(1)[0], self.tx)
        retained = self.backend._saved(self.tx)
        view = self.backend.open(*self.actor(0), self.actor(1)[0], self.tx)
        self.assertEqual(view["generation"], retained["generation"])
        self.assertEqual(view["state"], "offering")
        self.assertEqual(self.store._connection.execute("SELECT COUNT(*) FROM trade_effect_proposals").fetchone()[0], 1)

    async def test_denied_wrong_generation_does_not_invalidate_running_native_replay(self):
        proposal = self.prepare(); receipts = await self.receipts()
        self.adapter.gate = asyncio.Event()
        for p in proposal.players:
            self.submit(p, receipts[p])
        await self.adapter.entered.wait()
        with self.assertRaises(StorageError):
            self.backend.cancel(*self.actor(0), self.tx, str(uuid4()))
        self.assertIs(self.backend.desk._proposals[self.tx], proposal)
        self.adapter.gate.set(); await self.finish()
        self.assertEqual(self.backend.errors, {})
        self.assertEqual(self.backend.status(*self.actor(0), self.tx)["state"], "committed")

    async def test_original_single_receipt_survives_host_restart_and_new_leases(self):
        proposal = self.prepare(); receipts = await self.receipts()
        original = proposal.preparations
        self.submit(proposal.players[0], receipts[proposal.players[0]])
        await self.backend.close(); self.store.close()
        self.store = TradeCheckpointStore(self.fixture.path, BUILD, RULESET)
        self.store.begin_server_boot()
        self.leases = {p.player_id: self.store.acquire_lease(p.player_id, p.credential) for p in self.fixture.players}
        self.adapter = NonEvolvingFixtureReplay()
        self.backend = TradeEffectsBackend(TradeDesk(self.store, self.leases.get), self.adapter, POLICY)
        await self.backend.start()
        self.proposal = self.backend.desk._proposals[self.tx]
        self.assertEqual(self.proposal.preparations, original)
        self.assertEqual(self.proposal.prepared, {proposal.players[0]})
        self.submit(proposal.players[1], receipts[proposal.players[1]])
        await self.finish()
        self.assertEqual(self.backend.status(*self.actor(0), self.tx)["state"], "committed")
        self.store.integrity_check()

    async def test_reconnect_before_mutual_consent_requires_new_fingerprint(self):
        view = self.backend.open(*self.actor(0), self.actor(1)[0], self.tx)
        for i in (0, 1):
            cp = self.store.read_checkpoint(*self.actor(i))
            view = self.backend.offer(*self.actor(i), self.tx, view["generation"], cp.revision, cp.sha256,
                                      self.fixture.grants[i].start)
        self.backend.confirm(*self.actor(0), self.tx, view["generation"], view["fingerprint"])
        actor, lease = self.actor(1)
        self.store.release_lease(actor, lease)
        self.leases[actor] = self.store.acquire_lease(actor, self.fixture.players[1].credential)
        with self.assertRaises(StorageError) as caught:
            self.backend.confirm(*self.actor(1), self.tx, view["generation"], view["fingerprint"])
        self.assertEqual(caught.exception.code, "trade_offer_changed")
        current = self.backend.status(*self.actor(0), self.tx)
        self.assertEqual(current["confirmations"], [])
        self.assertNotEqual(current["fingerprint"], view["fingerprint"])
        for i in (0, 1):
            current = self.backend.confirm(*self.actor(i), self.tx, current["generation"], current["fingerprint"])
        self.assertEqual(current["state"], "preparing")

    async def test_failed_historical_native_replay_keeps_all_persistent_mutations_fenced(self):
        proposal = self.prepare(); receipts = await self.receipts()
        for p in proposal.players:
            self.submit(p, receipts[p])
        await self.finish(); await self.backend.close()
        self.adapter = NonEvolvingFixtureReplay(); self.adapter.corrupt = True
        self.backend = TradeEffectsBackend(TradeDesk(self.store, self.leases.get), self.adapter, POLICY)
        with self.assertRaises(StorageError):
            await self.backend.start()
        cp = self.store.read_checkpoint(*self.actor(0))
        for callback, args in ((self.store.commit_checkpoint, (*self.actor(0), str(uuid4()), cp.revision, cp.payload, BUILD, RULESET, self.store.save_profile)),
                               (self.store.reserve_instances, (*self.actor(0), str(uuid4()), cp.revision, 1, 1))):
            with self.assertRaises(StorageError) as caught:
                callback(*args)
            self.assertEqual(caught.exception.code, "trade_effect_replay_required")
