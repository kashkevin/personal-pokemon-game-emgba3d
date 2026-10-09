"""Durable, two-consent native trades with asynchronous trusted replay.

SQLite stays on its owning loop. Native work runs through the injected pinned
worker; after every await the original consent, heads, histories and current
leases are checked again before one paired save/history transaction.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from functools import wraps
from uuid import uuid4

from .flash import inspect_flash
from .ownership import inspect_ownership
from .storage import StorageError
from .trade_desk import _Proposal, _Offer
from .trade_effect_flash import EffectOfferPlan, PLAN_ID
from .trade_effect_preparation import (
    POLICIES, canonical, digest, describe_effect_pair, decode_effect_plan,
    validate_effect_preparation, validate_effect_receipt,
)
from .trade_effect_storage import (
    EffectCommitAuthority, parse_document, require, make_document, native_replay, read_effect_policy,
)
from .trade_effect_witness import _record
from .trade_flash import _party_record
from .trade_friendship_migration import FriendshipHistoryLedger
from .trade_storage import TradeSide


def durable_change(method):
    """After refusal or uncertain COMMIT, reload authority from durable bytes."""
    @wraps(method)
    def wrapped(self, actor, lease, *args, **kwargs):
        try:
            return method(self, actor, lease, *args, **kwargs)
        except BaseException:
            # Do not invalidate an unrelated pair's in-flight native replay.
            self._restore_transaction(args[0])
            raise
    return wrapped


class TradeEffectsBackend:
    def __init__(self, desk, adapter, policy_id):
        require(desk.store.trade_effects_enabled and desk.store.friendship_history_enabled,
                "native trades require explicit backed-up effect and handler extensions")
        require(policy_id in POLICIES and adapter is not None, "an approved geographic policy and native worker are required")
        require(read_effect_policy(desk.store) == policy_id, "host geographic policy differs from explicit world selection")
        self.desk, self.store, self.adapter, self.policy_id = desk, desk.store, adapter, policy_id
        self.ready, self.closed = False, False
        self.jobs, self.errors, self.receipts = {}, {}, {}
        self._native_lock = asyncio.Lock()
        self.owner = object()

    def _rows(self):
        return self.store._connection.execute("SELECT * FROM trade_effect_proposals ORDER BY transaction_id").fetchall()

    def _saved(self, tx):
        return self.store._connection.execute("SELECT * FROM trade_effect_proposals WHERE transaction_id=?", (tx,)).fetchone()

    def _restore_transaction(self, tx):
        row = self._saved(tx)
        current = self.desk._proposals.get(tx)
        if row is not None and row["state"] == "active":
            # A rejected authentication/generation request has changed nothing.
            # Keep the exact object used by a legitimate in-flight worker.
            if current is not None and current.effectful and self._document(current) == parse_document(row):
                return
            proposal = self._restore(row)
            self.desk._proposals[tx] = proposal
        elif current is not None and current.effectful:
            self.desk._proposals.pop(tx, None)

    def handles(self, tx):
        return self._saved(tx) is not None

    def _checkpoint(self, actor, revision):
        row = self.store._connection.execute("SELECT * FROM checkpoints WHERE player_id=? AND revision=?", (actor, revision)).fetchone()
        require(row is not None, "native preparation original checkpoint is missing")
        return self.store._checkpoint(row)

    def _document(self, proposal):
        return dict(transaction_id=proposal.transaction_id, generation=proposal.generation,
            players=list(proposal.players), leases=list(proposal.leases), edit=proposal.edit,
            offers=[dict(player_id=p, serial=o.serial, species=o.species, revision=o.checkpoint.revision, sha256=o.checkpoint.sha256)
                    for p, o in sorted(proposal.offers.items())], confirmed=sorted(proposal.confirmed),
            preparations=None if proposal.preparations is None else list(proposal.preparations),
            receipts=self.receipts.get(proposal.transaction_id, {}))

    def _save(self, proposal, state="active"):
        value = self._document(proposal)
        with self.store._transaction():
            old = self._saved(proposal.transaction_id)
            if old is not None:
                require(old["state"] == "active" and old["generation"] == proposal.generation,
                        "terminal native trade cannot be reopened or rewritten")
                self.store._connection.execute("UPDATE trade_effect_proposals SET state=?,document=?,sha256=? WHERE transaction_id=?",
                    (state, canonical(value), digest(value), proposal.transaction_id))
            else:
                self.store._connection.execute("INSERT INTO trade_effect_proposals VALUES (?,?,?,?,?)",
                    (proposal.transaction_id, proposal.generation, state, canonical(value), digest(value)))

    def _restore(self, row):
        value = parse_document(row)
        require(set(value) == {"transaction_id", "generation", "players", "leases", "edit", "offers", "confirmed", "preparations", "receipts"},
                "retained native consent fields differ")
        from .trade_protocol import _uuid
        _uuid(value["transaction_id"], "transaction_id"); _uuid(value["generation"], "generation")
        players, leases = value["players"], value["leases"]
        require(type(players) is list and len(players) == 2 and players == sorted(set(players))
                and type(leases) is list and len(leases) == 2 and all(type(v) is int and 1 <= v <= 2147483647 for v in leases),
                "retained native participant identities differ")
        for actor in players:
            _uuid(actor, "player_id")
        require(type(value["edit"]) is int and 0 <= value["edit"] <= 2147483647, "retained offer edit differs")
        proposal = _Proposal(value["transaction_id"], value["generation"], tuple(players), tuple(leases), float("inf"),
                             edit=value["edit"], effectful=True)
        require(type(value["offers"]) is list and len(value["offers"]) <= 2, "retained offers differ")
        for offer in value["offers"]:
            require(type(offer) is dict and set(offer) == {"player_id", "serial", "species", "revision", "sha256"}
                    and offer["player_id"] in players and offer["player_id"] not in proposal.offers, "retained offer owner differs")
            cp = self._checkpoint(offer["player_id"], offer["revision"])
            snap = inspect_flash(cp.payload, save_profile=cp.save_profile)
            mon = _party_record(snap, inspect_ownership(snap), offer["serial"])[1]
            info = _record(mon)[0]
            require(cp.sha256 == offer["sha256"] and info[3] == offer["species"], "retained offer source differs")
            proposal.offers[offer["player_id"]] = _Offer(cp, offer["serial"], offer["species"])
        confirmations = value["confirmed"]
        require(type(confirmations) is list and confirmations == sorted(set(confirmations))
                and set(confirmations) <= proposal.offers.keys() and (not confirmations or len(proposal.offers) == 2),
                "retained native consent differs")
        proposal.confirmed = set(confirmations)
        descriptions = value["preparations"]
        if descriptions is not None:
            require(type(descriptions) is list and len(descriptions) == 2 and proposal.confirmed == set(players),
                    "retained preparation lacks both confirmations")
            for i, description in enumerate(descriptions):
                validate_effect_preparation(description)
                require((description["transaction_id"], description["generation"], description["fingerprint"], description["recipient_id"]) ==
                    (proposal.transaction_id, proposal.generation, self.desk._fingerprint(proposal), players[i]), "retained preparation consent changed")
            plans = tuple(decode_effect_plan(p) for p in descriptions[0]["effects"]["offers"])
            expected = describe_effect_pair(self.store.metadata.world_id, proposal.transaction_id, proposal.generation,
                self.desk._fingerprint(proposal), tuple(proposal.offers[p].checkpoint for p in players), proposal.leases, plans,
                **{k: descriptions[0]["effects"][k] for k in ("engine_source_sha256", "profile_game_version", "policy_id")})
            require(tuple(descriptions) == expected, "retained descriptions differ from original offers")
            proposal.preparations = tuple(descriptions)
        receipts = value["receipts"]
        require(type(receipts) is dict and set(receipts) <= set(players) and (not receipts or descriptions is not None),
                "retained native acknowledgements differ")
        for receipt in receipts.values():
            validate_effect_receipt(receipt)
        proposal.prepared = set(receipts)
        self.receipts[proposal.transaction_id] = receipts
        require(self._document(proposal) == value, "retained consent is not a canonical complete proposal")
        return proposal

    async def start(self):
        require(not self.closed and not self.ready, "native trade backend was already started or closed")
        self.store._effect_replay_verified = False
        # Snapshot exact immutable bytes, then run native work without holding a
        # SQLite transaction or accepting a listener's mutation requests.
        rows = self.store._connection.execute("SELECT * FROM trade_effect_commits ORDER BY transaction_id").fetchall()
        for row in rows:
            document = parse_document(row)
            descriptions = document["descriptions"]
            before = tuple(self._checkpoint(p["player_id"], p["revision"]) for p in descriptions[0]["players"])
            pair = await native_replay(self.adapter, document, before)
            require(not self.closed, "native trade startup was closed")
            current = self.store._connection.execute("SELECT * FROM trade_effect_commits WHERE transaction_id=?", (row["transaction_id"],)).fetchone()
            require(current is not None and tuple(current) == tuple(row), "native history changed during replay")
            result = self.store._connection.execute("SELECT * FROM trade_transactions WHERE transaction_id=?", (row["transaction_id"],)).fetchone()
            require(result is not None, "native effect publication is missing")
            require(tuple(self._checkpoint(result[p + "_player"], result[p + "_revision"]).payload for p in ("a", "b")) ==
                    (pair.after_a, pair.after_b), "committed native saves differ from replay")
        active = [self._restore(row) for row in self._rows() if row["state"] == "active"]
        require(len(active) <= 2 and len({p for proposal in active for p in proposal.players}) == 2 * len(active),
                "durable native proposals overlap")
        self.desk._proposals.update((p.transaction_id, p) for p in active)
        self.store._effect_authority_owner = self.owner
        self.store._effect_replay_verified = True
        self.ready = True

    async def close(self):
        self.closed, self.ready = True, False
        self.store._effect_replay_verified = False
        self.store._effect_authority_owner = None
        for task in tuple(self.jobs.values()):
            task.cancel()
        if self.jobs:
            await asyncio.gather(*tuple(self.jobs.values()), return_exceptions=True)
        close = getattr(self.adapter, "close", None)
        if close is not None:
            await close()

    def _auth(self, actor, lease):
        require(self.ready and not self.closed, "native trade replay is unavailable")
        return self.desk._auth(actor, lease)

    def _pending(self, actor, lease, tx, generation=None):
        self._auth(actor, lease)
        row = self._saved(tx)
        require(row is not None, "native trade proposal is missing")
        value = parse_document(row)
        if actor not in value["players"]:
            raise StorageError("trade_not_participant", "this actor is not a native trade participant")
        if generation is not None and row["generation"] != generation:
            raise StorageError("trade_generation_mismatch", "native trade generation changed")
        if row["state"] != "active":
            raise StorageError("trade_aborted", "native trade has a terminal fate")
        proposal = self.desk._proposals.get(tx)
        require(proposal is not None and proposal.effectful and self._document(proposal) == value,
                "native trade memory differs from durable consent")
        return proposal

    def _heads(self, proposal):
        leases = []
        for actor, original in zip(proposal.players, proposal.leases):
            lease = self.desk.lease_for(actor)
            if lease is None:
                raise StorageError("player_offline", "both original recipients must reconnect before publication")
            require(lease >= original and self.desk._auth(actor, lease) == proposal.offers[actor].checkpoint,
                    "native trade canonical head changed")
            require(not self.store.pending_trade_recovery(actor, lease), "apply the previous trade before native preparation")
            leases.append(lease)
        return tuple(leases)

    def status(self, actor, lease, tx):
        self._auth(actor, lease)
        committed = self.store.read_trade(actor, lease, tx)
        if committed is not None:
            return self.desk._committed(actor, committed)
        row = self._saved(tx)
        if row is None:
            return dict(transaction_id=tx, state="aborted")
        if actor not in parse_document(row)["players"]:
            raise StorageError("trade_not_participant", "this actor is not a native trade participant")
        if row["state"] == "cancelled":
            return dict(transaction_id=tx, state="aborted")
        proposal = self._pending(actor, lease, tx)
        if tx in self.errors:
            raise self.errors[tx]
        self._schedule(proposal)
        return self.desk._public(proposal)

    def proposals(self, actor, lease):
        self._auth(actor, lease)
        return [self.desk._public(p) for p in self.desk._proposals.values() if p.effectful and actor in p.players]

    def open(self, actor, lease, peer, tx):
        self._auth(actor, lease)
        if self.handles(tx):
            value = parse_document(self._saved(tx))
            require(set(value["players"]) == {actor, peer}, "transaction belongs to another pair")
            return self.status(actor, lease, tx)
        view = self.desk.open(actor, lease, peer, tx)
        if view["state"] == "committed":
            return view
        proposal = self.desk._proposals[tx]
        require(not proposal.offers and not proposal.confirmed, "ordinary consent cannot be upgraded implicitly")
        proposal.effectful = True
        proposal.expires = float("inf")
        try:
            self._save(proposal)
        except BaseException:
            self._restore_transaction(tx)
            raise
        return self.desk._public(proposal)

    @durable_change
    def offer(self, actor, lease, tx, generation, revision, sha256, serial):
        proposal = self._pending(actor, lease, tx, generation)
        require(proposal.preparations is None, "confirmed native offers are frozen")
        cp = self._auth(actor, lease)
        require(cp is not None and (cp.revision, cp.sha256) == (revision, sha256), "offer must name the exact canonical head")
        try:
            snap = inspect_flash(cp.payload, save_profile=cp.save_profile)
            mon = _party_record(snap, inspect_ownership(snap), serial)[1]
            info = _record(mon)[0]
        except ValueError as error:
            raise StorageError("trade_effect_unsupported", "offer a supported assigned Gen1–6 party Pokemon without an egg or mail") from error
        FriendshipHistoryLedger(self.store).read_current(actor, lease, serial)
        offered = _Offer(cp, serial, info[3])
        if proposal.offers.get(actor) != offered:
            require(proposal.edit < 2147483647, "native offer edit capacity exhausted")
            proposal.offers[actor] = offered
            proposal.edit += 1
            proposal.confirmed.clear()
        self._save(proposal)
        return self.desk._public(proposal)

    @durable_change
    def confirm(self, actor, lease, tx, generation, fingerprint):
        proposal = self._pending(actor, lease, tx, generation)
        require(len(proposal.offers) == 2 and fingerprint == self.desk._fingerprint(proposal), "confirm the exact complete native offer")
        current = self._heads(proposal)
        if proposal.preparations is None:
            if current != proposal.leases:
                require(proposal.edit < 2147483647, "native offer edit capacity exhausted")
                proposal.leases = current
                proposal.edit += 1
                proposal.confirmed.clear()
                self._save(proposal)
                raise StorageError("trade_offer_changed", "reconnected participants must confirm the new exact offer fingerprint")
            proposal.confirmed.add(actor)
            if proposal.confirmed == set(proposal.players):
                plans = tuple(EffectOfferPlan(FriendshipHistoryLedger(self.store).read_current(p, epoch, proposal.offers[p].serial),
                    self.policy_id == "gen6-absent-geography-refresh-v1") for p, epoch in zip(proposal.players, current))
                proposal.preparations = describe_effect_pair(self.store.metadata.world_id, tx, generation, fingerprint,
                    tuple(proposal.offers[p].checkpoint for p in proposal.players), proposal.leases, plans,
                    engine_source_sha256=self.adapter.engine_source_sha256, profile_game_version=self.adapter.profile_game_version,
                    policy_id=self.policy_id)
            self._save(proposal)
        return self.desk._public(proposal)

    def preparation(self, actor, lease, tx, generation):
        proposal = self._pending(actor, lease, tx, generation)
        self._heads(proposal)
        require(proposal.preparations is not None, "both exact native offers must be confirmed")
        return dict(transaction_id=tx, state="recipient_preparation",
                    preparation=json.loads(canonical(proposal.preparations[proposal.players.index(actor)])))

    def inspect(self, actor, lease, tx, generation, fingerprint):
        import base64
        proposal = self._pending(actor, lease, tx, generation)
        require(len(proposal.offers) == 2 and fingerprint == self.desk._fingerprint(proposal), "inspect the exact complete effect pair")
        self._heads(proposal)
        offers = []
        for player in proposal.players:
            offer = proposal.offers[player]
            snap = inspect_flash(offer.checkpoint.payload, save_profile=self.store.save_profile)
            record = _party_record(snap, inspect_ownership(snap), offer.serial)[1]
            offers.append(dict(player_id=player, serial=offer.serial, record=base64.b64encode(record).decode("ascii")))
        return dict(transaction_id=tx, state="inspection", generation=generation, fingerprint=fingerprint, offers=offers)

    def effect_source(self, actor, lease, tx, generation, preparation_id):
        proposal = self._pending(actor, lease, tx, generation)
        self._heads(proposal)
        require(proposal.preparations is not None and proposal.preparations[0]["preparation_id"] == preparation_id,
                "effect source belongs to another preparation")
        from .trade_effect_source import describe_effect_source
        peer = next(p for p in proposal.players if p != actor)
        return dict(transaction_id=tx, state="effect_source", source=describe_effect_source(
            proposal.preparations[proposal.players.index(actor)], proposal.offers[peer].checkpoint))

    @durable_change
    def cancel(self, actor, lease, tx, generation):
        current = self.status(actor, lease, tx) if tx not in self.errors else None
        if current is not None and current["state"] in {"committed", "aborted"}:
            return current
        proposal = self._pending(actor, lease, tx, generation)
        self._save(proposal, "cancelled")
        self.desk._proposals.pop(tx, None)
        self.errors.pop(tx, None)
        task = self.jobs.get(tx)
        if task is not None:
            task.cancel()
        return dict(transaction_id=tx, state="aborted")

    @durable_change
    def prepared(self, actor, lease, tx, generation, fingerprint, preparation_id, receipt):
        self._auth(actor, lease)
        committed = self.store.read_trade(actor, lease, tx)
        if committed is not None:
            row = self.store._connection.execute("SELECT * FROM trade_effect_commits WHERE transaction_id=?", (tx,)).fetchone()
            require(row is not None, "this transaction used another trade capability")
            doc = parse_document(row)
            description = doc["descriptions"][0]
            i = [p["player_id"] for p in description["players"]].index(actor)
            require((generation, fingerprint, preparation_id, receipt) ==
                    (description["generation"], description["fingerprint"], description["preparation_id"], doc["receipts"][i]),
                    "native receipt differs from original committed acknowledgement")
            return self.desk._committed(actor, committed)
        proposal = self._pending(actor, lease, tx, generation)
        self._heads(proposal)
        require(proposal.preparations is not None, "native pair has not been prepared")
        first = proposal.preparations[0]
        require((fingerprint, preparation_id) == (first["fingerprint"], first["preparation_id"]), "native receipt belongs to another plan")
        validate_effect_receipt(receipt)
        receipts = self.receipts.setdefault(tx, {})
        require(actor not in receipts or receipts[actor] == receipt, "explicit native choice receipt cannot be overwritten")
        receipts[actor] = json.loads(canonical(receipt))
        proposal.prepared.add(actor)
        self._save(proposal)
        self.errors.pop(tx, None)
        self._schedule(proposal)
        return self.desk._public(proposal)

    def _schedule(self, proposal):
        tx = proposal.transaction_id
        if proposal.prepared == set(proposal.players) and tx not in self.jobs and tx not in self.errors:
            task = asyncio.create_task(self._publish(proposal), name="trade-native-" + tx)
            self.jobs[tx] = task
            def finished(done):
                if self.jobs.get(tx) is done:
                    self.jobs.pop(tx, None)
                if not done.cancelled():
                    error = done.exception()
                    if error is not None:
                        if isinstance(error, StorageError) and error.code in {"player_offline", "stale_lease"}:
                            # A reconnect does not invalidate the immutable plan
                            # or choices. The next status retries under new leases.
                            return
                        self.errors[tx] = error if isinstance(error, StorageError) else StorageError(
                            "trade_native_replay_failed", "native replay failed; the original trade remains held")
            task.add_done_callback(finished)

    async def _publish(self, proposal):
        self._heads(proposal)
        original = canonical(self._document(proposal))
        before = tuple(proposal.offers[p].checkpoint for p in proposal.players)
        descriptions = proposal.preparations
        first = descriptions[0]
        plans = tuple(decode_effect_plan(p) for p in first["effects"]["offers"])
        receipts = tuple(self.receipts[proposal.transaction_id][p] for p in proposal.players)
        choices = tuple(validate_effect_receipt(r) for r in receipts)
        async with self._native_lock:
            require(self.ready and not self.closed and self._saved(proposal.transaction_id)["state"] == "active",
                    "native trade stopped before replay")
            pair = await self.adapter.prepare_pair(before[0], plans[0], before[1], plans[1],
                transaction_id=proposal.transaction_id, generation=proposal.generation, fingerprint=first["fingerprint"],
                leases=proposal.leases, choices_a=choices[0], choices_b=choices[1])
        require(self.ready and not self.closed, "native trade host closed during replay")
        row = self._saved(proposal.transaction_id)
        require(row is not None and row["state"] == "active" and row["document"] == original
                and self.desk._proposals.get(proposal.transaction_id) is proposal, "native consent changed during replay")
        leases = self._heads(proposal)
        document = make_document(descriptions, receipts, before, pair)
        sides = tuple(TradeSide(p, epoch, cp.revision, plan.history.serial, payload)
            for p, epoch, cp, plan, payload in zip(proposal.players, leases, before, plans, (pair.after_a, pair.after_b)))
        self.store.commit_trade(proposal.transaction_id, *sides, self.store.build_id, self.store.ruleset_id,
            self.store.save_profile, _effect_authority=EffectCommitAuthority(self.owner, document, pair))
        self.desk._proposals.pop(proposal.transaction_id, None)
