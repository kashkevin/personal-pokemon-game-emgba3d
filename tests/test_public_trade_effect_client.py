"""Public client boundaries with fabricated native evidence, never emulator acceptance."""
import asyncio
import base64
from copy import deepcopy
from dataclasses import replace
import hashlib
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
import zlib

from emerald_multiplayer.companion import Companion, TradeError
from emerald_multiplayer.flash import inspect_flash
from emerald_multiplayer.gen6_friendship import base_friendship
from emerald_multiplayer.live_checkpoint import _json_bytes
from emerald_multiplayer.live_trade import LiveTradeCoordinator
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, inspect_ownership
from emerald_multiplayer.trade_effect_flash import EffectOfferPlan, _private_blocks_with_gifts, _write_blocks
from emerald_multiplayer.trade_effect_preparation import describe_effect_pair
from emerald_multiplayer.trade_effect_recovery import client_for_plan, retained_effect_candidate, completed_effect_summary
from emerald_multiplayer.trade_effect_source import effect_source_from_plan
from emerald_multiplayer.trade_friendship import TrainerIdentity, transform_received_party_record
from emerald_multiplayer.trade_flash import _party_record
from emerald_multiplayer.trade_inspection import summarize_record
import test_trade_friendship_flash as friendship_fixtures
import test_trade_menu as menu_fixtures
from test_trade_friendship import decode_fixture, encode_fixture
from test_flash import _rewrite


def capable(native=True):
    return SimpleNamespace(config=SimpleNamespace(menu_abi_version=2, trade_effect_prepare_abi_version=1,
        trade_effect_save_abi_version=1, trade_effect_choice_abi_version=1),
        _bridge=SimpleNamespace(save_capable=True, window_capable=True, trade_effect_prepare_capable=True,
            trade_effect_save_capable=True, trade_effect_choice_capable=True) if native else None,
        world_id=str(uuid4()), server_epoch=5, session_epoch=2, connected=True,
        _trade_rpc=AsyncMock(side_effect=[{"effects_version": 1}, {"trade": "answer"}]))


class EffectNegotiationTests(unittest.IsolatedAsyncioTestCase):
    async def test_positive_probe_precedes_mutation_and_cold_status_needs_no_native(self):
        for native, op in ((True, "open"), (False, "status")):
            c = capable(native)
            self.assertEqual(await Companion.trade_rpc(c, op), {"trade": "answer"})
            self.assertEqual(c._trade_rpc.await_args_list[0].args, ("proposals",))
            self.assertEqual(c._trade_rpc.await_args_list[1].kwargs["effects_version"], 1)

    async def test_old_host_fallback_is_explicit_and_never_retries_uncertain_mutation(self):
        c = capable()
        c._trade_rpc.side_effect = [TradeError("invalid_fields", "old host"), {"trade": "legacy"}]
        self.assertEqual(await Companion.trade_rpc(c, "open"), {"trade": "legacy"})
        self.assertNotIn("effects_version", c._trade_rpc.await_args_list[1].kwargs)
        for failure in (TimeoutError(), TradeError("trade_busy", "wait")):
            c = capable(); c._trade_rpc.side_effect = failure
            with self.assertRaises(type(failure)):
                await Companion.trade_rpc(c, "open")
            self.assertEqual(c._trade_rpc.await_count, 1)

    async def test_lease_change_invalidates_probe_and_prepared_requires_original_native(self):
        c = capable()
        async def changed(*args, **kwargs):
            c.session_epoch += 1
            return {"effects_version": 1}
        c._trade_rpc.side_effect = changed
        with self.assertRaises(ConnectionError):
            await Companion.trade_rpc(c, "open")
        self.assertEqual(c._trade_rpc.await_count, 1)
        c = capable(False)
        with self.assertRaises(TradeError):
            await Companion.trade_rpc(c, "effect_prepared")
        c._trade_rpc.assert_not_awaited()

    async def test_recovery_only_host_probes_exact_status_without_requiring_live_proposals(self):
        c = capable(False); transaction = str(uuid4())
        await Companion.trade_rpc(c, "status", transaction_id=transaction)
        self.assertEqual([call.args for call in c._trade_rpc.await_args_list], [("status",), ("status",)])
        self.assertEqual(c._trade_rpc.await_args_list[0].kwargs["transaction_id"], transaction)


class EffectMenuBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_effect_dialog_closes_before_same_task_preparation_and_terminal_apply(self):
        menu, dialog, co, c, proposal = menu_fixtures.TradeMenuTests().make()
        proposal["capability"] = "native-recipient-save-effects-v1"
        c.config = capable().config; c.config.player_id = "actor"; c._bridge = capable()._bridge
        preparing = dict(proposal, state="preparing", prepared=[], fingerprint="confirmed")
        co.status.side_effect = [proposal, preparing]
        order, owner = [], asyncio.current_task()
        async def close(screen): order.append("close")
        async def native(same_dialog):
            self.assertIs(asyncio.current_task(), owner)
            self.assertIs(same_dialog, dialog)
            self.assertEqual(order, ["close"])
            order.append("native-review")
            return {"state": "committed"}
        async def apply():
            self.assertEqual(order, ["close", "native-review"])
            return dict(state="applied", received=dict(species=65, evolved=True))
        dialog.close_dialog.side_effect = close
        co.prepare_effect_recipient = AsyncMock(side_effect=native)
        co.resume.side_effect = apply
        with patch("emerald_multiplayer.trade_menu.prepared_choices", return_value=()):
            result = await menu.run(proposal, 8)
        self.assertEqual(result["state"], "applied")
        self.assertEqual(dialog.menu._notice, "Evolved: Alakazam")

    async def test_paused_effect_review_reopens_new_revision_and_requires_new_action(self):
        menu, dialog, co, c, proposal = menu_fixtures.TradeMenuTests().make()
        proposal["capability"] = "native-recipient-save-effects-v1"
        c.config = capable().config; c.config.player_id = "actor"; c._bridge = capable()._bridge
        preparing = dict(proposal, state="preparing", prepared=[], fingerprint="confirmed")
        co.status.side_effect = [proposal, preparing, preparing, {"state": "aborted"}]
        dialog._last_request = SimpleNamespace(screen=40)
        co.prepare_effect_recipient = AsyncMock(return_value=None)
        dialog.dialog_choice = AsyncMock(side_effect=TimeoutError())
        with patch("emerald_multiplayer.trade_menu.prepared_choices", return_value=()):
            await menu.run(proposal, 8)
        self.assertEqual(co.prepare_effect_recipient.await_count, 1)
        reopened = dialog.open_trade_dialog.await_args_list[1].args[0]
        self.assertGreater(reopened.revision, 40)
        self.assertIn("Resume evolution review", [r.label for r in reopened.rows])


class RetainedEffectTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        a, pa, b, pb = friendship_fixtures.FriendshipFlashTests().sources(rtc=False)
        pair = sorted(((a, pa), (b, pb)), key=lambda p: p[0].player_id)
        normalized = []
        for cp, plan in pair:
            snapshot = inspect_flash(cp.payload, save_profile=OWNERSHIP_PROFILE)
            offset, mon = _party_record(snapshot, inspect_ownership(snapshot), plan.history.serial)
            logical = decode_fixture(mon)
            for slot, move in enumerate(summarize_record(mon).moves):
                if not move:
                    logical[1][8 + slot] = 0
            payload = _rewrite(cp.payload, snapshot.metadata.bank, 1, offset, encode_fixture(mon, logical))
            normalized.append((replace(cp, payload=payload, sha256=hashlib.sha256(payload).hexdigest()), plan))
        pair = normalized
        cps = tuple(p[0] for p in pair); plans = tuple(EffectOfferPlan(p[1].history, False) for p in pair)
        world = inspect_ownership(inspect_flash(cps[0].payload, save_profile=OWNERSHIP_PROFILE)).world_id
        self.desc = describe_effect_pair(world, str(uuid4()), str(uuid4()), "4"*64, cps, (2, 3), plans,
            engine_source_sha256="6"*64, profile_game_version=3, policy_id="gen6-stable-world-region-v1")[0]
        cp, peer = cps
        co = object.__new__(LiveTradeCoordinator); co.directory = Path(self.tmp.name)
        co.companion = SimpleNamespace(world_id=world, config=SimpleNamespace(player_id=cp.player_id,
            build_id=cp.build_id, ruleset_id=cp.ruleset_id))
        self.co, self.session = co, (world, 2, 7)
        self.intent = dict(schema=2, world_id=world, player_id=cp.player_id, transaction_id=self.desc["transaction_id"],
            generation=self.desc["generation"], prepare_id=cp.request_id, expected_revision=cp.revision-1,
            incarnation=7, runtime_id=str(uuid4()), frozen_sha256=cp.sha256, export_ended=True,
            prepared=dict(revision=cp.revision), build_id=cp.build_id, ruleset_id=cp.ruleset_id,
            canonical=None, save_profile=OWNERSHIP_PROFILE)
        self.prefix = self.intent["transaction_id"] + "." + self.intent["generation"]
        co._immutable(cp.request_id + ".flash", cp.payload)
        co._immutable(self.intent["transaction_id"] + ".consent-" + self.desc["fingerprint"] + ".json",
            _json_bytes(co._consent_record(self.intent, self.desc["fingerprint"], 2)))
        # _recipient_record compares only these exact prepared fields.
        self.intent["prepared"].update(request_id=cp.request_id, sha256=cp.sha256)
        client = client_for_plan(co, self.desc)
        client.bind_description(self.intent, self.session, self.desc, zlib.crc32(cp.payload))
        self.client = client
        source = inspect_flash(cp.payload, save_profile=OWNERSHIP_PROFILE)
        own, other = self.desc["players"]
        offset, sent = _party_record(source, inspect_ownership(source), own["serial"])
        incoming = base64.b64decode(self.desc["incoming_record"])
        trainer = TrainerIdentity(source.metadata.name, source.metadata.gender, source.metadata.trainer_id, 3)
        mon, transition = transform_received_party_record(incoming, plans[1].history, trainer,
            base_friendship=base_friendship(265), refresh_handler=False)
        # The fixture represents native READY, not an independent proof of native execution.
        summary = summarize_record(mon)
        ready = struct.pack("<III6H4B", 1, other["serial"], own["serial"], 265, 0, summary.held_item,
            summary.held_item, 0, 0, 2, transition.friendship, 0, 0) + mon + bytes(64)
        record = client._load(); record["response"] = base64.b64encode(ready).decode(); client._save(record)
        view = bytearray(struct.pack("<IIIIHHBBBB", 1, other["serial"], own["serial"], zlib.crc32(ready), 0, 0, 2, 0, 0, 0))
        for move, pp in zip(summary.moves, summary.pp):
            view.extend(struct.pack("<HBBHBBBBH", move, pp, max(pp, 40) if move else 0, 0, 0, 0, 1 if move else 0, 0, 0))
        view.extend(bytes(12))
        self.review = dict(format="emerald-held-trade-candidate-review-v1", binding=client.binding,
            record=record["response"], view=base64.b64encode(view).decode(), screen=8, request_sequence=12, session_epoch=2)
        self.ready = ready
        peer_source = effect_source_from_plan(self.desc)
        gifts = base64.b64decode(peer_source["gift_ribbons"])
        self.candidate = _write_blocks(source, *_private_blocks_with_gifts(source, gifts, offset, incoming, mon))
        context = dict(format="emerald-held-trade-save-context-v1", record_binding=client.binding,
            ready_record=record["response"], peer_source=peer_source,
            begin=base64.b64encode(base64.b64decode(client.binding["begin"])[:48] + bytes.fromhex(peer_source["sha256"]) + gifts + b"\0").decode())
        completion = dict(format="emerald-held-trade-save-candidate-v1", preparation_id=self.desc["preparation_id"],
            effect_source_sha256=peer_source["sha256"], record_sha256=hashlib.sha256(ready).hexdigest(),
            context_sha256=hashlib.sha256(_json_bytes(context)).hexdigest(),
            candidate_sha256=hashlib.sha256(self.candidate).hexdigest(), size=len(self.candidate))
        self.receipt = dict(choices=[], candidate_sha256=completion["candidate_sha256"],
            candidate_size=len(self.candidate), record_sha256=hashlib.sha256(mon).hexdigest())
        for suffix, data in ((".save-context.json", _json_bytes(context)), (".candidate.json", _json_bytes(completion)),
            (".candidate.flash", self.candidate), (".review.2.8.12.json", _json_bytes(self.review))):
            co._immutable(client.path.with_suffix(suffix).name, data)
        self.publication = dict(format="emerald-public-effect-receipt-v1", preparation_id=self.desc["preparation_id"],
            receipt=self.receipt, review=self.review)
        self.receipt_path = co.directory / (self.prefix + ".effect-receipt.json")
        self.receipt_path.write_bytes(_json_bytes(self.publication))

    def test_exact_original_receipt_recovers_offline_on_new_lease(self):
        candidate, receipt = retained_effect_candidate(self.co, self.intent, (self.session[0], 9, None), self.desc)
        self.assertEqual(candidate, self.candidate)
        self.assertEqual(receipt, self.receipt)
        self.assertNotEqual(receipt["record_sha256"], hashlib.sha256(self.ready).hexdigest())

    def test_publication_or_review_tampering_never_recovers(self):
        for key in ("record_sha256", "candidate_sha256"):
            changed = deepcopy(self.publication); changed["receipt"][key] = "0"*64
            self.receipt_path.write_bytes(_json_bytes(changed))
            with self.assertRaises(ValueError):
                retained_effect_candidate(self.co, self.intent, self.session, self.desc)
        self.receipt_path.write_bytes(_json_bytes(self.publication))
        self.client.path.with_suffix(".review.2.8.12.json").unlink()
        with self.assertRaises((ValueError, OSError)):
            retained_effect_candidate(self.co, self.intent, self.session, self.desc)

    def test_wrong_original_consent_and_unrelated_candidate_bytes_fail(self):
        path = self.co.directory / (self.intent["transaction_id"] + ".consent-" + self.desc["fingerprint"] + ".json")
        original = path.read_bytes(); path.write_bytes(original.replace(b'"session_epoch":2', b'"session_epoch":3'))
        with self.assertRaises(ValueError):
            retained_effect_candidate(self.co, self.intent, self.session, self.desc)
        path.write_bytes(original)
        self.client.path.with_suffix(".candidate.flash").write_bytes(bytes(131072))
        with self.assertRaises(ValueError):
            retained_effect_candidate(self.co, self.intent, self.session, self.desc)

    async def test_recipient_evidence_precedes_receipt_and_missing_review_never_sends(self):
        co = self.co
        co.client = SimpleNamespace(info=AsyncMock(return_value=self.intent["prepared"]))
        co._same_session = lambda session: self.assertEqual(session, self.session)
        co._held = AsyncMock()
        async def submit(session, op, **fields):
            self.assertEqual(op, "effect_prepared")
            self.assertEqual(fields["record_sha256"], self.receipt["record_sha256"])
            self.assertEqual(co._prepared_candidate(self.intent, session), self.candidate)
            return {"trade": {"state": "preparing"}}
        co._rpc = AsyncMock(side_effect=submit)
        self.assertEqual(await co._submit_effect_recipient(self.intent, self.session, self.desc), {"state": "preparing"})
        co._rpc.assert_awaited_once()
        self.receipt_path.unlink()
        with self.assertRaises(ValueError):
            await co._submit_effect_recipient(self.intent, self.session, self.desc)
        co._rpc.assert_awaited_once()

    def test_received_summary_is_bound_to_actual_canonical_candidate(self):
        co = self.co
        co._immutable(self.prefix + ".recipient-preparation.json", _json_bytes(
            co._recipient_record(self.intent, self.session, self.desc)))
        co._immutable(self.prefix + ".recipient-candidate.flash", self.candidate)
        revision = self.intent["expected_revision"] + 2
        self.intent["canonical"] = dict(sha256=hashlib.sha256(self.candidate).hexdigest(), revision=revision,
            request_id=self.intent["transaction_id"], size=len(self.candidate),
            build_id=co.companion.config.build_id, ruleset_id=co.companion.config.ruleset_id,
            save_profile=OWNERSHIP_PROFILE)
        result = completed_effect_summary(co, self.intent, self.session)
        self.assertEqual((result["species"], result["evolved"], result["revision"]), (265, False, revision))
        self.intent["canonical"]["sha256"] = "0"*64
        with self.assertRaises(ValueError):
            completed_effect_summary(co, self.intent, self.session)
