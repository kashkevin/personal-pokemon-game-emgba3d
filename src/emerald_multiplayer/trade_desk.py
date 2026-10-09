"""Bounded two-party consent before the durable paired-trade primitive.

The server RPC and native menu use this synchronous component. Callers must
obtain actor ID/lease from the authenticated connection, never message
claims, and establish the ROM hold before offering its canonical snapshot.
Uncommitted proposals disappear on server restart; committed fate lives in
the store. Transport uncertainty must never be interpreted as an abort.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import base64
import json
import time
from typing import Callable
from uuid import uuid4

from .flash import inspect_flash
from .ownership import inspect_ownership
from .ownership_protocol import MAX_SERIAL
from .ownership_storage import _uuid
from .protocol import MAX_COUNTER
from .storage import Checkpoint, StorageError, _counter, _player_id
from .trade_flash import TradeFlashError
from .trade_eligibility import (
    TradeEligibilityError, validate_party_offer, validate_trade_pair,
)
from .trade_storage import TradeCheckpointStore, TradeResult, TradeSide
from .trade_preparation import TradePreparationError, prepare_pair


@dataclass(frozen=True)
class _Offer:
    checkpoint: Checkpoint = field(repr=False)
    serial: int
    species: int


@dataclass
class _Proposal:
    transaction_id: str
    generation: str
    players: tuple[str, str]
    leases: tuple[int, int]
    expires: float
    edit: int = 0
    offers: dict[str, _Offer] = field(default_factory=dict)
    confirmed: set[str] = field(default_factory=set)
    preparations: tuple[dict, dict] | None = None
    candidates: tuple[bytes, bytes] | None = field(default=None, repr=False)
    prepared: set[str] = field(default_factory=set)
    effectful: bool = False


class TradeDesk:
    """Each authenticated participant confirms only its own current offer view.

    ``lease_for`` returns the server's live connection lease, or None. No await
    separates final checks from commit. The SQLite store independently verifies
    current leases, heads, pending recovery and exact transformation atomically.
    """

    def __init__(self, store: TradeCheckpointStore,
                 lease_for: Callable[[str], int | None], *, timeout: float = 180,
                 clock: Callable[[], float] = time.monotonic):
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 1 <= timeout <= 3600:
            raise ValueError("trade proposal timeout must be between 1 and 3600 seconds")
        self.store, self.lease_for = store, lease_for
        self.timeout, self.clock = timeout, clock
        self._proposals: dict[str, _Proposal] = {}
        # Host friendship bookkeeping after a committed exact swap (no Lucky
        # conversion: an exact swap never changes either Pokémon).
        self.on_commit = None

    def _auth(self, player: str, lease: int) -> Checkpoint | None:
        checkpoint = self.store.read_checkpoint(player, lease)
        if self.lease_for(player) != lease:
            raise StorageError("stale_lease", "trade actor is not the current connected player")
        return checkpoint

    def _prune(self) -> None:
        now = self.clock()
        for key, proposal in tuple(self._proposals.items()):
            if proposal.effectful:
                # Persisted native-effect consent has an explicit terminal fate;
                # lease loss/timeout cannot erase it during original-core recovery.
                continue
            if (proposal.expires <= now or any(self.lease_for(player) != lease
                    for player, lease in zip(proposal.players, proposal.leases))):
                del self._proposals[key]

    def _fingerprint(self, proposal: _Proposal) -> str | None:
        if len(proposal.offers) != 2:
            return None
        material = [self.store.metadata.world_id, proposal.transaction_id,
            proposal.generation, proposal.edit, [[player, lease,
                proposal.offers[player].checkpoint.revision,
                proposal.offers[player].checkpoint.sha256,
                proposal.offers[player].serial]
                for player, lease in zip(proposal.players, proposal.leases)]]
        return hashlib.sha256(b"EM-TRADE-CONSENT-1\0" + json.dumps(
            material, separators=(",", ":")).encode("ascii")).hexdigest()

    def _committed(self, player: str, result: TradeResult) -> dict:
        checkpoint = next(cp for cp in (result.checkpoint_a, result.checkpoint_b) if cp.player_id == player)
        self._proposals.pop(result.transaction_id, None)
        # Never expose the other player's whole save through a consent response.
        return dict(transaction_id=result.transaction_id, state="committed",
            outcome_fingerprint=result.outcome_fingerprint,
            revision=checkpoint.revision, sha256=checkpoint.sha256)

    def _public(self, proposal: _Proposal) -> dict:
        value = dict(transaction_id=proposal.transaction_id, generation=proposal.generation,
            state="preparing" if proposal.preparations is not None else "offering", fingerprint=self._fingerprint(proposal),
            players=list(proposal.players), confirmations=sorted(proposal.confirmed),
            offers=[dict(player_id=player, serial=offer.serial, species=offer.species,
                revision=offer.checkpoint.revision, sha256=offer.checkpoint.sha256)
                for player, offer in sorted(proposal.offers.items())])
        if proposal.preparations is not None:
            value.update(preparation_id=proposal.preparations[0]["preparation_id"],
                         prepared=sorted(proposal.prepared))
        if proposal.effectful:
            from .trade_effect_flash import PLAN_ID
            value["capability"] = PLAN_ID
        return value

    def _pending(self, player: str, lease: int, transaction_id: str,
                 generation: str | None = None) -> _Proposal:
        _uuid(transaction_id, "transaction_id")
        self._auth(player, lease)
        self._prune()
        proposal = self._proposals.get(transaction_id)
        if proposal is None:
            raise StorageError("trade_aborted", "no uncommitted proposal remains")
        if proposal.effectful:
            raise StorageError("trade_effect_negotiation_required", "this proposal requires explicit native effect negotiation")
        if player not in proposal.players:
            raise StorageError("trade_not_participant", "this player is not a trade participant")
        if generation is not None and generation != proposal.generation:
            raise StorageError("trade_generation_mismatch", "this request refers to a superseded proposal")
        return proposal

    def open(self, player: str, lease: int, peer: str, transaction_id: str) -> dict:
        _uuid(transaction_id, "transaction_id"); _player_id(peer)
        self._auth(player, lease)
        committed = self.store.read_trade(player, lease, transaction_id)
        if committed is not None:
            participants = {committed.checkpoint_a.player_id, committed.checkpoint_b.player_id}
            if {player, peer} != participants:
                raise StorageError("request_conflict", "transaction ID belongs to different participants")
            return self._committed(player, committed)
        if player == peer:
            raise StorageError("invalid_trade", "a trade requires two distinct players")
        self._prune()
        existing = self._proposals.get(transaction_id)
        players = tuple(sorted((player, peer)))
        if existing is not None:
            if existing.effectful:
                raise StorageError("trade_effect_negotiation_required", "this proposal requires explicit native effect negotiation")
            if existing.players != players:
                raise StorageError("request_conflict", "transaction ID belongs to different participants")
            return self._public(existing)
        if len(self._proposals) >= 2 or any(set(players) & set(p.players) for p in self._proposals.values()):
            raise StorageError("trade_busy", "a participant already has a pending proposal")
        leases = []
        for participant in players:
            current = self.lease_for(participant)
            if current is None:
                raise StorageError("player_offline", "both trade participants must be connected")
            if self._auth(participant, current) is None:
                raise StorageError("checkpoint_required", "both players need an owned checkpoint")
            if self.store.pending_trade_recovery(participant, current):
                raise StorageError("trade_recovery_required", "apply the previous trade result before starting another")
            leases.append(current)
        proposal = _Proposal(transaction_id, str(uuid4()), players, tuple(leases), self.clock()+self.timeout)
        self._proposals[transaction_id] = proposal
        return self._public(proposal)

    def proposals(self, player: str, lease: int) -> list[dict]:
        """Discover only this authenticated actor's live offer, without consent.

        Reading does not extend proposal lifetime or reveal unrelated pairs.
        A new lease prunes the old proposal before it can reach a new menu.
        """
        self._auth(player, lease)
        self._prune()
        return [self._public(proposal) for proposal in self._proposals.values()
                if player in proposal.players and not proposal.effectful]

    def offer(self, player: str, lease: int, transaction_id: str, generation: str,
              revision: int, sha256: str, serial: int) -> dict:
        _counter(revision, "revision", 1)
        if type(serial) is not int or not 1 <= serial <= MAX_SERIAL:
            raise StorageError("invalid_field", "offered serial is outside identity bounds")
        proposal = self._pending(player, lease, transaction_id, generation)
        if proposal.preparations is not None:
            raise StorageError("trade_preparing", "both offers are frozen for recipient preparation")
        checkpoint = self._auth(player, lease)
        if checkpoint is None or (revision, sha256) != (checkpoint.revision, checkpoint.sha256):
            raise StorageError("revision_conflict", "offer must refer to the exact current owned checkpoint")
        if self.store.pending_trade_recovery(player, lease):
            raise StorageError("trade_recovery_required", "apply the previous trade before offering")
        owned = inspect_ownership(inspect_flash(checkpoint.payload, save_profile=self.store.save_profile))
        record = next((r for r in owned.records if r.serial == serial), None)
        if record is None or not record.location.startswith("party:"):
            raise StorageError("invalid_trade", "offered instance must be in this player's party")
        # Refuse unsupported native effects before changing an offer or its
        # confirmations. This capability remains a development exact exchange.
        try:
            validate_party_offer(checkpoint.payload, serial)
        except TradeEligibilityError as error:
            raise StorageError(error.code, str(error)) from error
        offered = _Offer(checkpoint, serial, record.species)
        if proposal.offers.get(player) != offered:
            if proposal.edit == MAX_COUNTER:
                raise StorageError("counter_exhausted", "start a new proposal")
            proposal.offers[player] = offered
            proposal.edit += 1
            proposal.confirmed.clear()
        proposal.expires = self.clock()+self.timeout
        return self._public(proposal)

    def status(self, player: str, lease: int, transaction_id: str) -> dict:
        _uuid(transaction_id, "transaction_id")
        self._auth(player, lease)
        committed = self.store.read_trade(player, lease, transaction_id)
        if committed is not None:
            return self._committed(player, committed)
        self._prune()
        if transaction_id not in self._proposals:
            return dict(transaction_id=transaction_id, state="aborted")
        return self._public(self._pending(player, lease, transaction_id))

    def cancel(self, player: str, lease: int, transaction_id: str, generation: str) -> dict:
        current = self.status(player, lease, transaction_id)
        if current["state"] not in {"offering", "preparing"}:
            return current
        self._pending(player, lease, transaction_id, generation)
        del self._proposals[transaction_id]
        return dict(transaction_id=transaction_id, state="aborted")

    def confirm(self, player: str, lease: int, transaction_id: str,
                generation: str, fingerprint: str) -> dict:
        current = self.status(player, lease, transaction_id)
        if current["state"] == "committed":
            return current
        proposal = self._pending(player, lease, transaction_id, generation)
        if not isinstance(fingerprint, str) or fingerprint != self._fingerprint(proposal):
            raise StorageError("trade_offer_changed", "confirm the current complete two-player offer")
        if proposal.preparations is not None:
            return self._public(proposal)
        for participant, current_lease in zip(proposal.players, proposal.leases):
            head = self._auth(participant, current_lease)
            if head != proposal.offers[participant].checkpoint:
                proposal.confirmed.clear()
                raise StorageError("revision_conflict", "a participant's checkpoint changed after offering")
        left, right = (proposal.offers[p] for p in proposal.players)
        try:
            validate_trade_pair(left.checkpoint.payload, left.serial,
                                right.checkpoint.payload, right.serial)
        except TradeEligibilityError as error:
            proposal.confirmed.clear()
            raise StorageError(error.code, str(error)) from error
        proposal.confirmed.add(player)
        if len(proposal.confirmed) < 2:
            return self._public(proposal)
        try:
            proposal.preparations, proposal.candidates = prepare_pair(
                self.store.metadata.world_id, transaction_id, generation, fingerprint,
                (left.checkpoint, right.checkpoint), proposal.leases, (left.serial, right.serial))
        except (TradeFlashError, TradePreparationError) as error:
            proposal.confirmed.clear()
            raise StorageError("invalid_trade", "the offered saves cannot form exact recipient candidates") from error
        except BaseException:
            proposal.confirmed.clear()
            raise
        return self._public(proposal)

    def preparation(self, player: str, lease: int, transaction_id: str, generation: str) -> dict:
        current = self.status(player, lease, transaction_id)
        if current["state"] == "committed":
            return current
        proposal = self._pending(player, lease, transaction_id, generation)
        if proposal.preparations is None or proposal.confirmed != set(proposal.players):
            raise StorageError("trade_consent_required", "both exact offers must be confirmed before preparing")
        self._check_preparation_heads(proposal)
        # Copy the bounded description so callers cannot mutate retained plans.
        description = proposal.preparations[proposal.players.index(player)]
        return dict(transaction_id=transaction_id, state="recipient_preparation",
                    preparation=json.loads(json.dumps(description)))

    def inspect(self, player, lease, transaction_id, generation, fingerprint):
        """Read the exact two offered party records without granting consent."""
        proposal = self._pending(player, lease, transaction_id, generation)
        if len(proposal.offers) != 2 or fingerprint != self._fingerprint(proposal):
            raise StorageError("trade_offer_changed", "inspect the current complete offered pair")
        self._check_preparation_heads(proposal)
        from .trade_flash import _party_record
        offers = []
        for participant in proposal.players:
            offer = proposal.offers[participant]
            snapshot = inspect_flash(offer.checkpoint.payload, save_profile=self.store.save_profile)
            _, record = _party_record(snapshot, inspect_ownership(snapshot), offer.serial)
            offers.append(dict(player_id=participant, serial=offer.serial,
                               record=base64.b64encode(record).decode("ascii")))
        return dict(transaction_id=transaction_id, state="inspection", generation=generation,
                    fingerprint=fingerprint, offers=offers)

    def effect_source(self, player, lease, transaction_id, generation, preparation_id):
        """Read seven peer ribbon-description bytes from the consented originals."""
        proposal = self._pending(player, lease, transaction_id, generation)
        if proposal.preparations is None or proposal.confirmed != set(proposal.players):
            raise StorageError("trade_consent_required", "both offers must be confirmed before native save preparation")
        self._check_preparation_heads(proposal)
        description = proposal.preparations[proposal.players.index(player)]
        if description["preparation_id"] != preparation_id:
            raise StorageError("trade_preparation_mismatch", "effect source belongs to another preparation")
        from .trade_effect_source import describe_effect_source
        peer = next(p for p in proposal.players if p != player)
        return dict(transaction_id=transaction_id, state="effect_source",
                    source=describe_effect_source(description, proposal.offers[peer].checkpoint))

    def _check_preparation_heads(self, proposal):
        for participant, current_lease in zip(proposal.players, proposal.leases):
            if self._auth(participant, current_lease) != proposal.offers[participant].checkpoint:
                raise StorageError("revision_conflict", "a frozen preparation checkpoint changed")
            if self.store.pending_trade_recovery(participant, current_lease):
                raise StorageError("trade_recovery_required", "a participant has an unapplied prior trade")

    def prepared(self, player: str, lease: int, transaction_id: str, generation: str,
                 fingerprint: str, preparation_id: str, candidate_sha256: str) -> dict:
        current = self.status(player, lease, transaction_id)
        if current["state"] == "committed":
            if current["sha256"] != candidate_sha256:
                raise StorageError("request_conflict", "prepared receipt differs from the committed recipient")
            return current
        proposal = self._pending(player, lease, transaction_id, generation)
        if proposal.preparations is None or proposal.candidates is None:
            raise StorageError("trade_preparation_required", "the exact consent pair has not been prepared")
        description = proposal.preparations[proposal.players.index(player)]
        own = next(p for p in description["players"] if p["player_id"] == player)
        if (fingerprint, preparation_id, candidate_sha256) != (
                description["fingerprint"], description["preparation_id"], own["candidate_sha256"]):
            raise StorageError("trade_preparation_mismatch", "receipt does not identify this exact recipient candidate")
        self._check_preparation_heads(proposal)
        if proposal.prepared | {player} != set(proposal.players):
            proposal.prepared.add(player)
            return self._public(proposal)
        # Publication remains one synchronous, independently validated SQLite
        # transaction. No recipient may publish alone or supply arbitrary bytes.
        offers = tuple(proposal.offers[p] for p in proposal.players)
        sides = tuple(TradeSide(p, lease, offer.checkpoint.revision, offer.serial, payload)
            for p, lease, offer, payload in zip(proposal.players, proposal.leases, offers, proposal.candidates))
        result = self.store.commit_prepared_trade(transaction_id, *sides,
            self.store.build_id, self.store.ruleset_id, self.store.save_profile,
            preparations=proposal.preparations)
        if callable(self.on_commit):
            try:
                self.on_commit(transaction_id, proposal.players, False)
            except Exception:  # noqa: BLE001 - never undo a committed trade
                pass
        return self._committed(player, result)
