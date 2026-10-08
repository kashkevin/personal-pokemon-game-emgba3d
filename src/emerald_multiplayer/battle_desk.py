"""Session-local consent and lifecycle barriers for development native battles.

No RPC, controller routing, ROM commands, rewards, saves or release run here.
The trusted coordinator supplies correlated native receipts and exact startup
bytes. Actor/lease always come from authentication, never request body claims.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
import json
import math
import secrets
import struct
import time
from uuid import uuid4

from .battle_mailbox import BattleMailboxError, _integer, _uuid
from .battle_roster import CanonicalBattler
from .native_battle import Kind, NativeBinding, NativeControl, NativeQuery, Opcode
from .ownership_storage import OwnershipCheckpointStore
from .protocol import MAX_COUNTER
from .storage import StorageError

MAX_ACTIVE = 2
MAX_HISTORY = 64
_POST_START = frozenset(("starting", "running", "finishing", "release_authorized", "recovery_required"))


class BattleError(StorageError):
    """A bounded native battle operation failed without releasing a game."""


@dataclass
class _Battle:
    battle_id: str
    generation: str
    sender: str
    players: tuple[str, ...]
    leases: tuple[int, ...]
    roster: tuple[CanonicalBattler, ...] = field(repr=False)
    rng: bytes = field(repr=False)
    fingerprint: str
    deadline: float
    mode: int = 2
    state: str = "invited"
    reason: str | None = None
    consent: set[str] = field(default_factory=set)
    incarnations: dict[str, int] = field(default_factory=dict)
    bind_intent: set[str] = field(default_factory=set)
    bound: set[str] = field(default_factory=set)
    prepared: set[str] = field(default_factory=set)
    started: set[str] = field(default_factory=set)
    parts: dict[str, list[tuple[int, int, bytes]]] = field(default_factory=dict, repr=False)
    finished: dict[str, int] = field(default_factory=dict)
    released: set[str] = field(default_factory=set)
    abort_pending: set[str] = field(default_factory=set)
    abort_acked: set[str] = field(default_factory=set)
    receipts: dict[tuple[str, int], tuple[bytes, bytes]] = field(default_factory=dict, repr=False)
    last_sequence: dict[str, int] = field(default_factory=dict)


class BattleDesk:
    """Two singles rooms or one four-trainer room; unresolved holds stay busy.

    START authorization is irreversible here even before its reply: either ROM
    may have entered native startup. Exact receipt retries cannot resample RNG,
    consent, or results. A host restart discards this in-memory service; durable
    battle journals and cold-start recovery are separate required work.
    """

    def __init__(self, store: OwnershipCheckpointStore, lease_for, *,
                 timeout: float = 180, clock=time.monotonic):
        if not isinstance(store, OwnershipCheckpointStore):
            raise ValueError("native battles require the explicit ownership store")
        if (type(timeout) not in (int, float) or not math.isfinite(timeout)
                or not 1 <= timeout <= 3600 or not callable(clock) or not callable(lease_for)):
            raise ValueError("battle timeout/callbacks are invalid")
        self.store, self.lease_for = store, lease_for
        self.timeout, self.clock = float(timeout), clock
        self._last_time = None
        self._active: dict[str, _Battle] = {}
        self._history: OrderedDict[str, _Battle] = OrderedDict()

    def _now(self):
        now = self.clock()
        try:
            valid = (type(now) in (int, float) and math.isfinite(now) and now >= 0
                     and (self._last_time is None or now >= self._last_time))
        except OverflowError:
            valid = False
        if not valid:
            raise BattleError("battle_clock", "battle clock must be finite and monotonic")
        self._last_time = float(now)
        return float(now)

    def _auth(self, actor, lease):
        try:
            _uuid(actor, "actor"); _integer(lease, 1, MAX_COUNTER, "actor lease")
        except BattleMailboxError as error:
            raise BattleError("invalid_field", str(error)) from error
        checkpoint = self.store.read_checkpoint(actor, lease)
        if self.lease_for(actor) != lease:
            raise BattleError("stale_lease", "actor is not the current connected player")
        return checkpoint

    @staticmethod
    def _id(value, name):
        try:
            return _uuid(value, name)
        except BattleMailboxError as error:
            raise BattleError("invalid_field", str(error)) from error

    def _archive(self, battle):
        self._active.pop(battle.battle_id, None)
        self._history[battle.battle_id] = battle
        while len(self._history) > MAX_HISTORY:
            self._history.popitem(last=False)

    def _abort(self, battle, reason):
        battle.consent.clear()
        battle.reason = reason
        battle.abort_pending = battle.bind_intent - battle.abort_acked
        battle.state = "aborting" if battle.abort_pending else "aborted"
        if not battle.abort_pending:
            self._archive(battle)

    def _recover(self, battle, reason):
        battle.state, battle.reason = "recovery_required", reason

    def refresh(self):
        """Trusted lifecycle hook; never frees a possibly held native battle."""
        now = self._now()
        for battle in tuple(self._active.values()):
            if battle.state in ("aborting", "recovery_required"):
                continue
            reason = None
            if any(self.lease_for(p) != lease for p, lease in zip(battle.players, battle.leases)):
                reason = "session_changed"
            elif now >= battle.deadline:
                reason = "deadline"
            else:
                try:
                    for player, lease, frozen in zip(battle.players, battle.leases, battle.roster):
                        # A correlated RELEASE has already proved this actor's
                        # native hold ended; later ordinary saves are legitimate.
                        # Still retain both captured network lease fences above.
                        if player in battle.released:
                            continue
                        head = self.store.read_checkpoint(player, lease)
                        if head is None or (head.revision, head.sha256) != (frozen.revision, frozen.checkpoint_sha256):
                            reason = "canonical_changed"
                            break
                except StorageError:
                    reason = "session_changed"
            if reason:
                if battle.state in _POST_START:
                    self._recover(battle, reason)
                else:
                    self._abort(battle, reason)

    def _get(self, actor, lease, battle_id, generation=None, *, historical=False):
        self._id(battle_id, "battle ID")
        if generation is not None:
            self._id(generation, "generation")
        self._auth(actor, lease)
        self.refresh()
        battle = self._active.get(battle_id) or self._history.get(battle_id)
        if battle is None:
            raise BattleError("battle_missing", "this battle is not retained in the current server session")
        if actor not in battle.players:
            raise BattleError("battle_not_participant", "actor is not a battle participant")
        if generation is not None and generation != battle.generation:
            raise BattleError("battle_generation_mismatch", "battle generation has changed")
        if not historical and lease != battle.leases[battle.players.index(actor)]:
            raise BattleError("stale_lease", "mutations require the original captured battle lease")
        return battle

    def _heads(self, battle):
        try:
            for player, lease, frozen in zip(battle.players, battle.leases, battle.roster):
                current = self._auth(player, lease)
                if current is None or (current.revision, current.sha256) != (frozen.revision, frozen.checkpoint_sha256):
                    raise BattleError("revision_conflict", "canonical party changed after the challenge")
                pending = getattr(self.store, "pending_trade_recovery", None)
                if pending is not None and pending(player, lease):
                    raise BattleError("trade_recovery_required", "apply the pending trade before battling")
        except StorageError:
            if battle.state in _POST_START:
                self._recover(battle, "canonical_or_session_changed")
            else:
                self._abort(battle, "canonical_or_session_changed")
            raise

    @staticmethod
    def _view(battle):
        view = dict(scope="session-local-native-singles-development" if battle.mode == 2 else "session-local-native-full-multi-development", battle_id=battle.battle_id,
            generation=battle.generation, sender=battle.sender, state=battle.state, reason=battle.reason,
            players=list(battle.players), fingerprint=battle.fingerprint,
            consent=sorted(battle.consent), bound=sorted(battle.bound),
            prepared=sorted(battle.prepared), started=sorted(battle.started),
            startup_verified=sorted(p for p in battle.players if len(battle.parts.get(p, ())) == 3),
            finished=sorted(battle.finished), released=sorted(battle.released),
            abort_pending=sorted(battle.abort_pending),
            outcome=next(iter(battle.finished.values())) if len(battle.finished) == len(battle.players) else None,
            checkpoints=[dict(player_id=r.player_id, source_slot=r.source_slot,
                revision=r.revision, sha256=r.checkpoint_sha256, party_count=r.party_count)
                for r in battle.roster])
        if battle.mode == 3:
            view.update(mode=3, teams=[list(battle.players[::2]), list(battle.players[1::2])])
        return view

    def invite(self, actor, lease, peer, battle_id):
        self._id(peer, "peer"); self._id(battle_id, "battle ID")
        if actor == peer:
            raise BattleError("invalid_battle", "singles require two different trainers")
        self._auth(actor, lease)
        return self._invite(actor, lease, tuple(sorted((actor, peer))), battle_id, mode=2)

    def invite_multi(self, actor, lease, teammate, opponents, battle_id):
        """Propose two explicit duos; no teammate's consent is inherited.

        This is a battle roster, not a persistent TeamDesk membership change.
        Every other trainer must accept its exact fingerprint independently.
        """
        self._auth(actor, lease)
        self._id(teammate, "teammate"); self._id(battle_id, "battle ID")
        if type(opponents) is not tuple or len(opponents) != 2:
            raise BattleError("invalid_battle", "Multi requires exactly two opposing trainers")
        for player in opponents:
            self._id(player, "opponent")
        if len({actor, teammate, *opponents}) != 4:
            raise BattleError("invalid_battle", "Multi requires four distinct trainers")
        own, other = sorted((actor, teammate)), sorted(opponents)
        return self._invite(actor, lease, (own[0], other[0], own[1], other[1]), battle_id, mode=3)

    def _invite(self, actor, lease, players, battle_id, *, mode):
        self._auth(actor, lease); self.refresh()
        existing = self._active.get(battle_id) or self._history.get(battle_id)
        if existing is not None:
            if existing.sender != actor or existing.players != players or existing.mode != mode:
                raise BattleError("request_conflict", "battle ID belongs to another challenge")
            return self._view(existing)
        if len(self._active) >= MAX_ACTIVE or any(set(players).intersection(b.players) for b in self._active.values()):
            raise BattleError("battle_busy", "a participant has an unresolved battle lifecycle")
        leases, roster = [], []
        for slot, player in enumerate(players):
            current_lease = self.lease_for(player)
            if current_lease is None:
                raise BattleError("player_offline", "all trainers must be connected")
            checkpoint = self._auth(player, current_lease)
            pending = getattr(self.store, "pending_trade_recovery", None)
            if pending is not None and pending(player, current_lease):
                raise BattleError("trade_recovery_required", "apply the pending trade before battling")
            try:
                descriptor = CanonicalBattler.from_checkpoint(checkpoint,
                    world_id=self.store.metadata.world_id, build_id=self.store.build_id,
                    ruleset_id=self.store.ruleset_id, source_slot=slot, mode=mode)
            except ValueError as error:
                raise BattleError("checkpoint_required", "all trainers need a valid owned canonical party") from error
            leases.append(current_lease); roster.append(descriptor)
        generation, rng = str(uuid4()), secrets.token_bytes(16)
        if not any(rng):
            raise BattleError("rng_unavailable", "could not issue a nonzero native battle RNG state")
        material = [self.store.metadata.world_id, battle_id, generation,
            [[p, l, r.revision, r.checkpoint_sha256] for p, l, r in zip(players, leases, roster)], rng.hex()]
        domain = b"EM-NATIVE-SINGLES-CONSENT-1\0" if mode == 2 else b"EM-NATIVE-FULL-MULTI-CONSENT-1\0"
        fingerprint = hashlib.sha256(domain +
            json.dumps(material, separators=(",", ":")).encode("ascii")).hexdigest()
        battle = _Battle(battle_id, generation, actor, players, tuple(leases),
            tuple(roster), rng, fingerprint, self._now()+self.timeout, mode=mode, consent={actor})
        self._active[battle_id] = battle
        return self._view(battle)

    def accept(self, actor, lease, battle_id, generation, fingerprint):
        battle = self._get(actor, lease, battle_id, generation)
        if actor == battle.sender:
            raise BattleError("battle_not_recipient", "the invited trainer must accept separately")
        if not isinstance(fingerprint, str) or fingerprint != battle.fingerprint:
            raise BattleError("battle_offer_changed", "accept the exact canonical challenge")
        if battle.state not in ("invited", "accepted", "prepared"):
            raise BattleError("battle_state", "this challenge cannot accept consent")
        self._heads(battle)
        if actor in battle.consent:
            return self._view(battle)
        battle.consent.add(actor)
        if battle.state == "invited" and battle.consent == set(battle.players):
            battle.state = "accepted"
        battle.deadline = self._now()+self.timeout
        return self._view(battle)

    def status(self, actor, lease, battle_id):
        return self._view(self._get(actor, lease, battle_id, historical=True))

    def pending(self, actor, lease):
        """Only this authenticated player's active challenges, at most one."""
        self._auth(actor, lease)
        self.refresh()
        return [self._view(battle) for battle in self._active.values() if actor in battle.players]

    def register(self, actor, lease, battle_id, generation, incarnation):
        battle = self._get(actor, lease, battle_id, generation)
        try:
            _integer(incarnation, 1, 0xFFFFFFFF, "incarnation")
        except BattleMailboxError as error:
            raise BattleError("invalid_field", str(error)) from error
        if battle.state not in ("accepted", "prepared"):
            raise BattleError("battle_state", "all trainers must consent before registration")
        self._heads(battle)
        if actor in battle.incarnations and battle.incarnations[actor] != incarnation:
            self._abort(battle, "incarnation_changed")
            raise BattleError("battle_incarnation_changed", "new native incarnation needs a new challenge")
        battle.incarnations[actor] = incarnation
        return self._view(battle)

    @staticmethod
    def _binding(battle, actor):
        if len(battle.incarnations) != len(battle.players):
            raise BattleError("battle_not_registered", "all native incarnations must be registered")
        return NativeBinding(battle.generation, battle.players, battle.leases,
            tuple(battle.incarnations[p] for p in battle.players), battle.players.index(actor), mode=battle.mode)

    def authorize_bind(self, actor, lease, battle_id, generation):
        battle = self._get(actor, lease, battle_id, generation)
        if battle.state not in ("accepted", "prepared") or battle.consent != set(battle.players):
            raise BattleError("battle_state", "all trainers must consent before native binding")
        self._heads(battle)
        binding = self._binding(battle, actor)
        battle.bind_intent.add(actor)  # Before the coordinator sends any BIND.
        return binding

    def descriptor(self, actor, lease, battle_id, generation):
        battle = self._get(actor, lease, battle_id, generation)
        return battle.roster[battle.players.index(actor)]

    def preparation(self, actor, lease, battle_id, generation):
        battle = self._get(actor, lease, battle_id, generation)
        if actor not in battle.bound or battle.state not in ("accepted", "prepared"):
            raise BattleError("battle_state", "native binding must be acknowledged before preparation")
        return battle.roster[battle.players.index(actor)].preparation(battle.rng)

    def _receipt(self, battle, actor, request, response, opcode, *, once=True):
        try:
            if not isinstance(request, NativeControl) or not isinstance(response, NativeControl) or request.opcode != opcode:
                raise BattleMailboxError("receipt needs the exact native operation")
            binding = self._binding(battle, actor)
            request.validate_command(binding=binding, player_id=actor)
            if request.battle_id != battle.battle_id:
                raise BattleMailboxError("receipt names another battle")
            response.validate_response(request)
            if opcode in (Opcode.BIND, Opcode.PREPARE, Opcode.START, Opcode.KEEP, Opcode.QUERY) and not response.status:
                query = NativeQuery.unpack(response.data)
                if query.generation != battle.generation or query.local_slot != battle.players.index(actor):
                    raise BattleMailboxError("native receipt changed the generation or local role")
        except BattleMailboxError as error:
            raise BattleError("invalid_receipt", str(error)) from error
        key, raw = (actor, opcode), (request.pack(), response.pack())
        previous = battle.receipts.get(key)
        if previous == raw:
            return True
        if previous is not None and once:
            raise BattleError("request_conflict", "operation receipt changed after acknowledgment")
        # Observational QUERY does not consume the ROM's mutating sequence.
        # A following RELEASE may use that same next native sequence number.
        if opcode != Opcode.QUERY and request.sequence <= battle.last_sequence.get(actor, 0):
            raise BattleError("battle_order", "receipt sequence decreased or was reused")
        if response.status:
            if battle.state in _POST_START:
                self._recover(battle, "native_refused")
            else:
                self._abort(battle, "native_refused")
            raise BattleError("native_refused", "native operation did not succeed; hold fate remains protected")
        return False

    @staticmethod
    def _record(battle, actor, request, response):
        battle.receipts[(actor, request.opcode)] = (request.pack(), response.pack())
        if request.opcode != Opcode.QUERY:
            battle.last_sequence[actor] = request.sequence

    @staticmethod
    def _allow(battle, actor, request, response, states):
        if battle.state in states:
            return
        if (isinstance(request, NativeControl) and isinstance(response, NativeControl)
                and battle.receipts.get((actor, request.opcode)) == (request.pack(), response.pack())):
            return  # Exact acknowledged retries may observe a later state.
        raise BattleError("battle_state", "operation is not permitted in this battle lifecycle")

    def bound(self, actor, lease, battle_id, generation, request, response):
        battle = self._get(actor, lease, battle_id, generation)
        if actor not in battle.bind_intent:
            raise BattleError("battle_state", "native bind intent must precede its acknowledgment")
        self._allow(battle, actor, request, response, ("accepted",))
        duplicate = self._receipt(battle, actor, request, response, Opcode.BIND)
        if duplicate:
            return self._view(battle)
        if battle.state != "accepted":
            raise BattleError("battle_state", "this challenge cannot acknowledge a new binding")
        query = NativeQuery.unpack(response.data)
        if query.prepared or query.started:
            raise BattleError("invalid_receipt", "initial bind receipt claims advanced native lifecycle")
        battle.bound.add(actor)
        self._record(battle, actor, request, response)
        return self._view(battle)

    def prepared(self, actor, lease, battle_id, generation, request, response, trainer):
        battle = self._get(actor, lease, battle_id, generation)
        if actor not in battle.bound:
            raise BattleError("battle_state", "native binding must precede preparation")
        self._allow(battle, actor, request, response, ("accepted", "prepared"))
        duplicate = self._receipt(battle, actor, request, response, Opcode.PREPARE)
        descriptor = battle.roster[battle.players.index(actor)]
        try:
            descriptor.verify_startup(Kind.TRAINER, trainer)
            if request.data != descriptor.preparation(battle.rng).pack():
                raise BattleMailboxError("native preparation changes the canonical checkpoint or issued RNG")
        except BattleMailboxError as error:
            if not duplicate:
                self._abort(battle, "preparation_mismatch")
            raise BattleError("canonical_mismatch", str(error)) from error
        if duplicate:
            return self._view(battle)
        if battle.state not in ("accepted", "prepared"):
            raise BattleError("battle_state", "this challenge cannot accept preparation")
        self._heads(battle)
        battle.prepared.add(actor)
        if battle.prepared == set(battle.players):
            battle.state = "prepared"
        self._record(battle, actor, request, response)
        return self._view(battle)

    def authorize_start(self, battle_id, generation):
        """Trusted coordinator entry, before dispatching any START command."""
        self._id(battle_id, "battle ID"); self._id(generation, "generation")
        self.refresh()
        battle = self._active.get(battle_id)
        if battle is None or generation != battle.generation:
            raise BattleError("battle_generation_mismatch", "no matching active battle exists")
        if battle.state in ("starting", "running"):
            self._heads(battle)
            return self._view(battle)
        if (battle.state != "prepared" or battle.consent != set(battle.players)
                or battle.prepared != set(battle.players) or battle.bound != set(battle.players)):
            raise BattleError("battle_not_ready", "all trainers must consent, bind and prepare")
        self._heads(battle)
        battle.state, battle.deadline = "starting", self._now()+self.timeout
        return self._view(battle)

    def started(self, actor, lease, battle_id, generation, request, response):
        battle = self._get(actor, lease, battle_id, generation)
        self._allow(battle, actor, request, response, ("starting",))
        duplicate = self._receipt(battle, actor, request, response, Opcode.START)
        if duplicate:
            return self._view(battle)
        if battle.state != "starting":
            raise BattleError("battle_state", "START needs prior coordinator authorization")
        query = NativeQuery.unpack(response.data)
        if query.generation != battle.generation or query.checkpoint_revision != battle.roster[battle.players.index(actor)].revision:
            self._recover(battle, "start_mismatch")
            raise BattleError("canonical_mismatch", "START response changed the native preparation")
        battle.started.add(actor)
        self._record(battle, actor, request, response)
        return self._view(battle)

    def verify_startup(self, actor, lease, battle_id, generation, kind, block_sequence, data):
        battle = self._get(actor, lease, battle_id, generation)
        if battle.state not in ("starting", "running") or actor not in battle.started:
            raise BattleError("battle_state", "native party startup requires acknowledged START")
        try:
            _integer(block_sequence, 1, 0xFFFFFFFF, "block sequence")
            if type(kind) is bool or kind not in (Kind.PARTY_0, Kind.PARTY_1, Kind.PARTY_2):
                raise BattleMailboxError("only the three original party startup blocks are checked here")
            battle.roster[battle.players.index(actor)].verify_startup(kind, data)
            parts = battle.parts.setdefault(actor, [])
            index = int(kind)-int(Kind.PARTY_0)
            value = (kind, block_sequence, data)
            if index < len(parts):
                if parts[index] != value:
                    raise BattleMailboxError("startup retry changed a completed party block")
                return self._view(battle)
            if index != len(parts) or (parts and block_sequence != parts[-1][1]+1):
                raise BattleMailboxError("original party blocks must arrive exactly once in order")
        except BattleMailboxError as error:
            self._recover(battle, "startup_mismatch")
            raise BattleError("canonical_mismatch", str(error)) from error
        parts.append(value)
        return self._view(battle)

    def authorize_running(self, battle_id, generation):
        """Trusted router entry after its separate HEADER/RNG/order validation.

        Exact canonical party validation here is necessary, but it does not
        replace the typed startup/controller validators owned by the router.
        """
        self._id(battle_id, "battle ID"); self._id(generation, "generation")
        self.refresh()
        battle = self._active.get(battle_id)
        if battle is None or generation != battle.generation:
            raise BattleError("battle_generation_mismatch", "no matching active battle exists")
        if (battle.state not in ("starting", "running")
                or battle.started != set(battle.players)
                or any(len(battle.parts.get(p, ())) != 3 for p in battle.players)):
            raise BattleError("battle_not_ready", "all native starts and exact canonical parties must be verified")
        self._heads(battle)
        battle.state = "running"
        return self._view(battle)

    def keepalive(self, actor, lease, battle_id, generation, request, response):
        battle = self._get(actor, lease, battle_id, generation)
        if battle.state in ("aborting", "recovery_required", "aborted", "closed"):
            raise BattleError("battle_state", "keepalive cannot revive a protected terminal/recovery lifecycle")
        if actor not in battle.bound:
            raise BattleError("battle_state", "keepalive requires an acknowledged native binding")
        if self._receipt(battle, actor, request, response, Opcode.KEEP, once=False):
            return self._view(battle)  # An old receipt cannot extend live time.
        query = NativeQuery.unpack(response.data)
        if query.generation != battle.generation:
            self._recover(battle, "keepalive_mismatch")
            raise BattleError("invalid_receipt", "keepalive names another native generation")
        self._record(battle, actor, request, response)
        battle.deadline = self._now()+self.timeout
        return self._view(battle)

    def finish(self, actor, lease, battle_id, generation, request, response, *, outcome, party, party_count):
        battle = self._get(actor, lease, battle_id, generation)
        self._allow(battle, actor, request, response, ("running", "finishing"))
        duplicate = self._receipt(battle, actor, request, response, Opcode.QUERY)
        descriptor = battle.roster[battle.players.index(actor)]
        query = NativeQuery.unpack(response.data)
        if (type(outcome) is not int or outcome not in (1, 2, 3)
                or type(party_count) is not int or party_count != descriptor.party_count
                or type(party) is not bytes or party != descriptor.party
                or query.generation != battle.generation or not query.restored or not query.started
                or not query.held or query.expired or query.recovery_required
                or query.outcome != outcome or query.checkpoint_revision != descriptor.revision):
            if not duplicate:
                self._recover(battle, "result_mismatch")
            raise BattleError("battle_result_mismatch", "result must prove the fixed-side outcome and exact restored original party")
        if duplicate:
            if battle.finished.get(actor) != outcome:
                raise BattleError("request_conflict", "result retry changed its outcome")
            return self._view(battle)
        if battle.state not in ("running", "finishing"):
            raise BattleError("battle_state", "results require all canonical startup parties")
        if battle.finished and next(iter(battle.finished.values())) != outcome:
            self._recover(battle, "outcome_disagreement")
            raise BattleError("battle_result_mismatch", "trainers disagree on the fixed-side outcome")
        self._heads(battle)
        battle.finished[actor] = outcome
        battle.state = "release_authorized" if len(battle.finished) == len(battle.players) else "finishing"
        self._record(battle, actor, request, response)
        return self._view(battle)

    def released(self, actor, lease, battle_id, generation, request, response):
        battle = self._get(actor, lease, battle_id, generation)
        self._allow(battle, actor, request, response, ("release_authorized",))
        duplicate = self._receipt(battle, actor, request, response, Opcode.RELEASE)
        if duplicate:
            return self._view(battle)
        if battle.state != "release_authorized":
            raise BattleError("battle_state", "all restored outcomes must authorize release")
        descriptor = battle.roster[battle.players.index(actor)]
        outcome = next(iter(battle.finished.values()))
        if request.data != struct.pack("<II", descriptor.party_crc32, outcome):
            self._recover(battle, "release_mismatch")
            raise BattleError("invalid_receipt", "release changes the verified original party/outcome")
        battle.released.add(actor)
        self._record(battle, actor, request, response)
        if battle.released == set(battle.players):
            battle.state = "closed"
            self._archive(battle)
        return self._view(battle)

    def cancel(self, actor, lease, battle_id, generation):
        battle = self._get(actor, lease, battle_id, generation)
        if battle.state == "aborted" or battle.state == "aborting":
            return self._view(battle)
        if battle.state in _POST_START or battle.state == "closed":
            raise BattleError("battle_started", "cancel cannot resolve a possibly started native battle")
        self._abort(battle, "participant_canceled")
        return self._view(battle)

    def refused(self, actor, lease, battle_id, generation):
        """A trusted native/coordinator refusal clears consent, not a hold."""
        battle = self._get(actor, lease, battle_id, generation)
        if battle.state in _POST_START:
            self._recover(battle, "native_refused")
        elif battle.state not in ("aborted", "closed"):
            self._abort(battle, "native_refused")
        return self._view(battle)

    def aborted(self, actor, lease, battle_id, generation, request, response):
        battle = self._get(actor, lease, battle_id, generation)
        self._allow(battle, actor, request, response, ("aborting",))
        duplicate = self._receipt(battle, actor, request, response, Opcode.ABORT_PRE_START)
        if duplicate:
            return self._view(battle)
        if battle.state != "aborting" or actor not in battle.abort_pending:
            raise BattleError("battle_state", "no matching pre-start abort remains")
        battle.abort_pending.remove(actor)
        battle.abort_acked.add(actor)
        self._record(battle, actor, request, response)
        if not battle.abort_pending:
            battle.state = "aborted"
            self._archive(battle)
        return self._view(battle)
