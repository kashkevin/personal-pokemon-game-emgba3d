"""Consent and lifecycle barriers for development native battles.

No RPC, controller routing, ROM commands, rewards or character saves run here.
The trusted coordinator supplies correlated native receipts and exact startup
bytes. Actor/lease always come from authentication, never request body claims.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field, replace
import hashlib
import json
import math
import secrets
import struct
import time
from uuid import uuid4

from .battle_mailbox import BattleMailboxError, _integer, _uuid
from .battle_roster import CanonicalBattler, EmptyPartyError
from .coop_code import valid_code
from .rival_catalogue import valid_preparation_word
from .native_battle import Kind, NativeBinding, NativeControl, NativeQuery, Opcode, outcomes_for_phase
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
    gym: int = 0  # co-op Gym index (mode 4 only)
    environment: int = 0  # rival checkpoint battle (modes 2 and 3): its preparation word; 0 for any other battle
    resumable: bool = False
    lease_lineage: tuple = ()
    renewal_digest: str | None = None
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
    consent, or results. Admission reservations and optional completed-result
    history survive a restart. Active coordination and same-battle native
    resumption remain separate required work.
    """

    def __init__(self, store: OwnershipCheckpointStore, lease_for, *,
                 timeout: float = 180, clock=time.monotonic, results=None):
        if not isinstance(store, OwnershipCheckpointStore):
            raise ValueError("native battles require the explicit ownership store")
        if (type(timeout) not in (int, float) or not math.isfinite(timeout)
                or not 1 <= timeout <= 3600 or not callable(clock) or not callable(lease_for)):
            raise ValueError("battle timeout/callbacks are invalid")
        self.store, self.lease_for = store, lease_for
        from .battle_reservations import BattleReservations
        self.reservations = BattleReservations(store)
        if results is not None:
            from .battle_results import BattleResults
            if (not isinstance(results, BattleResults) or results.identity != dict(
                    format="durable-native-battle-results-v1", world_id=store.metadata.world_id,
                    build_id=store.build_id, ruleset_id=store.ruleset_id)):
                raise ValueError("battle history must match this exact world and release")
        self.results = results
        self.on_closed = None  # host friendship bookkeeping after a closed battle
        self.on_publish = None  # co-op (PvE) result, made durable by the host before the battle is closed (Frontier)
        self.on_aborted = None  # host wager bookkeeping after an abort
        self.start_gate = None  # host wager check before the first START
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

    def _auth_lease(self, actor, lease):
        """``_auth`` for callers that discard the checkpoint (``_get``, on every battle RPC): the same
        field checks, the same store lease check (``_require_lease``, so a lease of an earlier server
        boot or a released lease is refused exactly as before) and the same binding check of the latest
        row, then the same connected-lease check, without reading and re-hashing the save payload.
        Readers of the payload still verify it. Subclasses whose ``_auth`` has other semantics (the
        recovery ReplayDesk) override this too."""
        try:
            _uuid(actor, "actor"); _integer(lease, 1, MAX_COUNTER, "actor lease")
        except BattleMailboxError as error:
            raise BattleError("invalid_field", str(error)) from error
        self.store.checkpoint_head(actor, lease)
        if self.lease_for(actor) != lease:
            raise BattleError("stale_lease", "actor is not the current connected player")

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
        if callable(self.on_aborted):
            try:
                self.on_aborted(battle)
            except Exception:  # noqa: BLE001 - a void wager never blocks the abort
                pass

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
                        # Metadata only: this runs on every RPC and only compares the head.
                        head = self.store.checkpoint_head(player, lease)
                        if head is None or head != (frozen.revision, frozen.checkpoint_sha256):
                            reason = "canonical_changed"
                            break
                except StorageError:
                    reason = "session_changed"
            if reason:
                if battle.state in _POST_START or (battle.resumable and battle.consent == set(battle.players)):
                    self._recover(battle, reason)
                else:
                    self._abort(battle, reason)

    def _get(self, actor, lease, battle_id, generation=None, *, historical=False):
        self._id(battle_id, "battle ID")
        if generation is not None:
            self._id(generation, "generation")
        self._auth_lease(actor, lease)
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
        scope = {2: "session-local-native-singles-development", 3: "session-local-native-full-multi-development",
                 4: "session-local-native-coop-gym", 5: "session-local-native-free-for-all",
                 6: "session-local-native-free-for-all-3"}[battle.mode]
        view = dict(scope=scope, battle_id=battle.battle_id,
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
        elif battle.mode == 4:
            # Both trainers share one side against the Gym's two AI trainers.
            view.update(mode=4, gym=battle.gym, teams=[list(battle.players)])
        elif battle.mode in (5, 6):
            # Four (or, in the 1v1v1, three) independent trainers: every trainer is a "team" of one.
            view.update(mode=battle.mode, teams=[[p] for p in battle.players])
        if battle.environment:
            view["environment"] = battle.environment  # Update 31: every core prepares the checkpoint's battle environment
        return view

    def invite(self, actor, lease, peer, battle_id, environment=0):
        """``environment``: a rival checkpoint battle's preparation word (Update 31), else 0."""
        self._id(peer, "peer"); self._id(battle_id, "battle ID")
        if actor == peer:
            raise BattleError("invalid_battle", "singles require two different trainers")
        self._auth(actor, lease)
        return self._invite(actor, lease, tuple(sorted((actor, peer))), battle_id, mode=2, environment=environment)

    def invite_multi(self, actor, lease, teammate, opponents, battle_id, environment=0):
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
        return self._invite(actor, lease, (own[0], other[0], own[1], other[1]), battle_id, mode=3, environment=environment)

    def invite_ffa(self, actor, lease, opponents, battle_id):
        """Four independent trainers in one shared battle (1v1v1v1).

        The challenger is slot 0, the master core that runs the battle's rules; the three others follow in a fixed
        (sorted) order so an exact retry names the same roster. Nobody's consent is inherited and nobody is anybody's
        partner. Every trainer must accept the exact fingerprint independently.
        """
        self._auth(actor, lease)
        self._id(battle_id, "battle ID")
        if type(opponents) is not tuple or len(opponents) != 3:
            raise BattleError("invalid_battle", "a free-for-all requires exactly three other trainers")
        for player in opponents:
            self._id(player, "opponent")
        if len({actor, *opponents}) != 4:
            raise BattleError("invalid_battle", "a free-for-all requires four distinct trainers")
        return self._invite(actor, lease, (actor, *sorted(opponents)), battle_id, mode=5)

    def invite_ffa3(self, actor, lease, opponents, battle_id):
        """Three independent trainers in one shared battle (1v1v1, Update 32).

        The four-player free-for-all with its fourth place empty: the challenger is slot 0 (the master core), the two
        others follow in sorted order. Every trainer is on a side of their own; each must accept the exact fingerprint.
        """
        self._auth(actor, lease)
        self._id(battle_id, "battle ID")
        if type(opponents) is not tuple or len(opponents) != 2:
            raise BattleError("invalid_battle", "a three-player free-for-all requires exactly two other trainers")
        for player in opponents:
            self._id(player, "opponent")
        if len({actor, *opponents}) != 3:
            raise BattleError("invalid_battle", "a three-player free-for-all requires three distinct trainers")
        return self._invite(actor, lease, (actor, *sorted(opponents)), battle_id, mode=6)

    def invite_coop(self, actor, lease, teammate, gym, battle_id, brings=None):
        """Two teammates against a Gym Leader and partner (both AI on slot 0).

        The requesting trainer is slot 0, the master core that runs both AI
        trainers. The teammate's consent is collected exactly like any other
        native challenge; nothing is inherited from the team membership.
        """
        self._id(teammate, "teammate"); self._id(battle_id, "battle ID")
        if actor == teammate:
            raise BattleError("invalid_battle", "a co-op Gym battle needs two different trainers")
        if not valid_code(gym):
            raise BattleError("invalid_battle", "unknown co-op battle")
        self._auth(actor, lease)
        brings = {} if brings is None else dict(brings)
        if set(brings) - {actor, teammate} or any(type(m) is not int or not 1 <= m <= 0x3F for m in brings.values()):
            raise BattleError("invalid_battle", "a team selection names a trainer of the battle and slots 0-5")
        return self._invite(actor, lease, (actor, teammate), battle_id, mode=4, gym=gym, brings=brings)

    def _invite(self, actor, lease, players, battle_id, *, mode, gym=0, brings=None, environment=0):
        if environment and (mode not in (2, 3) or not valid_preparation_word(environment)):
            raise BattleError("invalid_battle", "unknown rival checkpoint battle")
        self._auth(actor, lease); self.refresh()
        existing = self._active.get(battle_id) or self._history.get(battle_id)
        if existing is not None:
            if (existing.sender != actor or existing.players != players or existing.mode != mode or existing.gym != gym
                    or existing.environment != environment
                    or tuple(r.bring for r in existing.roster) != tuple((brings or {}).get(p, 0) for p in players)):
                raise BattleError("request_conflict", "battle ID belongs to another challenge")
            return self._view(existing)
        if self.results is not None and self.results.contains(battle_id):
            raise BattleError("battle_result_conflict", "completed battle ID cannot start another challenge")
        if self.reservations.contains(battle_id):
            raise BattleError("battle_reservation_conflict", "battle ID already belongs to a durable native lifecycle")
        try:
            self.reservations.assert_available(*players)
        except StorageError as error:
            raise BattleError(error.code, error.message) from error
        if len(self._active) >= MAX_ACTIVE or any(set(players).intersection(b.players) for b in self._active.values()):
            raise BattleError("battle_busy", "a participant has an unresolved battle lifecycle")
        leases, roster, empty = [], [], []
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
                    ruleset_id=self.store.ruleset_id, source_slot=slot, mode=mode, bring=(brings or {}).get(player, 0))
            except EmptyPartyError:
                # Update 32: a new character has no Pokemon until its starter claim in Birch's lab.
                empty.append(player)
                continue
            except ValueError as error:
                raise BattleError("checkpoint_required", "all trainers need a valid owned canonical party"
                                  + (" and a team selection that is still valid" if brings else "")) from error
            leases.append(current_lease); roster.append(descriptor)
        if empty:
            # The challenger's own empty party first, whatever the order of the roster.
            raise (BattleError("no_pokemon", "you have no Pokemon yet: claim one in Professor Birch's lab")
                   if actor in empty else BattleError("peer_no_pokemon", "a trainer has no Pokemon yet"))
        generation, rng = str(uuid4()), secrets.token_bytes(16)
        if not any(rng):
            raise BattleError("rng_unavailable", "could not issue a nonzero native battle RNG state")
        material = [self.store.metadata.world_id, battle_id, generation,
            [[p, l, r.revision, r.checkpoint_sha256] for p, l, r in zip(players, leases, roster)], rng.hex()]
        if mode == 4:
            material.append(gym)  # consent names the exact Gym (Leader and partner)
            material.append([r.bring for r in roster])   # ... and the exact team each trainer brings
        if environment:
            material.append(["rival", environment])  # consent names the rival checkpoint battle and its environment
        domain = {2: b"EM-NATIVE-SINGLES-CONSENT-1\0", 3: b"EM-NATIVE-FULL-MULTI-CONSENT-1\0",
                  4: b"EM-NATIVE-COOP-GYM-CONSENT-1\0", 5: b"EM-NATIVE-FFA-CONSENT-1\0",
                  6: b"EM-NATIVE-FFA3-CONSENT-1\0"}[mode]
        fingerprint = hashlib.sha256(domain +
            json.dumps(material, separators=(",", ":")).encode("ascii")).hexdigest()
        battle = _Battle(battle_id, generation, actor, players, tuple(leases),
            tuple(roster), rng, fingerprint, self._now()+self.timeout, mode=mode, gym=gym, environment=environment,
            consent={actor})
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
            tuple(battle.incarnations[p] for p in battle.players), battle.players.index(actor),
            mode=battle.mode, resumable=battle.resumable)

    def authorize_bind(self, actor, lease, battle_id, generation):
        battle = self._get(actor, lease, battle_id, generation)
        if battle.state not in ("accepted", "prepared") or battle.consent != set(battle.players):
            raise BattleError("battle_state", "all trainers must consent before native binding")
        self._heads(battle)
        binding = self._binding(battle, actor)
        self.reservations._reserve(battle, actor)
        battle.bind_intent.add(actor)  # Before the coordinator sends any BIND.
        return binding

    def descriptor(self, actor, lease, battle_id, generation):
        battle = self._get(actor, lease, battle_id, generation)
        return battle.roster[battle.players.index(actor)]

    def preparation(self, actor, lease, battle_id, generation):
        battle = self._get(actor, lease, battle_id, generation)
        if actor not in battle.bound or battle.state not in ("accepted", "prepared"):
            raise BattleError("battle_state", "native binding must be acknowledged before preparation")
        return battle.roster[battle.players.index(actor)].preparation(battle.rng, battle.gym or battle.environment)

    def _receipt(self, battle, actor, request, response, opcode, *, once=True):
        try:
            if not isinstance(request, NativeControl) or not isinstance(response, NativeControl) or request.opcode != opcode:
                raise BattleMailboxError("receipt needs the exact native operation")
            binding = self._binding(battle, actor)
            if request.session_epoch != binding.leases[binding.local_slot]:
                # Only the private recovery coordinator populates this lineage,
                # after every original core proves its exact reauthorization.
                candidates = [leases for leases in battle.lease_lineage
                              if leases[binding.local_slot] == request.session_epoch]
                if opcode == Opcode.BIND:
                    candidates = [leases for leases in candidates if NativeBinding.unpack(request.data).leases == leases]
                if not candidates:
                    raise BattleMailboxError("receipt lease has no verified original-core renewal lineage")
                binding = replace(binding, leases=candidates[-1])
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
            if request.data != descriptor.preparation(battle.rng, battle.gym or battle.environment).pack():
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
        if callable(self.start_gate):
            self.start_gate(battle)  # raises BattleError: an unaccepted/unfunded wager
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
        if (type(outcome) is not int or outcome not in outcomes_for_phase(battle.mode)
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

    def finish_native(self, actor, lease, battle_id, generation, request, response):
        """Accept the pinned native restoration invariant through its mailbox.

        ABI 2/3 sets restored only after checking the original party count and
        PREPARE CRC twice and restoring both personal RNG states. The trusted
        executor must already have verified all three exact startup party blocks;
        this entry grants no public outcome or party-byte submission authority.
        """
        battle = self._get(actor, lease, battle_id, generation)
        descriptor = battle.roster[battle.players.index(actor)]
        return self.finish(actor, lease, battle_id, generation, request, response,
            outcome=NativeQuery.unpack(response.data).outcome,
            party=descriptor.party, party_count=descriptor.party_count)

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
        # Publish before clearing the final server barrier. If COMMIT or its
        # acknowledgment fails, the exact RELEASE receipt can retry without
        # granting a new result or marking this lifecycle closed prematurely.
        if battle.released | {actor} == set(battle.players):
            self._publish_closed(battle, actor, request, response)
        battle.released.add(actor)
        self._record(battle, actor, request, response)
        if battle.released == set(battle.players):
            battle.state = "closed"
            self._archive(battle)
        return self._view(battle)

    def _publish_closed(self, battle, actor, request, response):
        """Shared durable publication after live or exact replay validation."""
        # An abandoned battle (battle_abandonment.py) has no result: a late RELEASE or a replayed quorum cannot publish
        # one. A closed terminal is an exact retry, which _finish below accepts unchanged.
        terminal = self.reservations.terminal(battle.battle_id)
        if terminal is not None and terminal.kind != "closed":
            raise BattleError("battle_abandoned", "this battle was abandoned; it has no result")
        # The archive holds PvP results (player cards, Championships). A co-op
        # Gym battle is PvE: its closure is the reservation's durable record.
        # Both free-for-alls keep their own book (ffa_results.py, via on_publish).
        if self.results is not None and battle.mode not in (4, 5, 6):
            view = self._view(battle)
            summary = {key: view[key] for key in ("battle_id", "generation", "sender", "players",
                "fingerprint", "outcome", "checkpoints")}
            summary["mode"] = battle.mode
            receipts = dict(battle.receipts)
            receipts[(actor, Opcode.RELEASE)] = (request.pack(), response.pack())
            material = bytearray(b"EM-CLOSED-NATIVE-BATTLE-1\0")
            for player in battle.players:
                for opcode in (Opcode.BIND, Opcode.PREPARE, Opcode.START, Opcode.QUERY, Opcode.RELEASE):
                    for raw in receipts[(player, opcode)]:
                        material.extend(raw)
            self.results._append_closed(summary, hashlib.sha256(material).hexdigest())
        if battle.mode in (4, 5, 6) and callable(self.on_publish):
            # A co-op battle's result is not in the PvP archive. The host keeps it (idempotently, by battle ID) *before*
            # the reservation closes, so a crash can never leave a closed battle whose outcome nobody recorded; if this
            # raises the exact RELEASE receipt is retried, as for the archive above.
            self.on_publish(battle)
        self.reservations._finish(battle, "closed", actor, request, response)
        if callable(self.on_closed):
            try:
                self.on_closed(battle)
            except Exception:  # noqa: BLE001 - friendship never affects the battle record
                pass

    def cancel(self, actor, lease, battle_id, generation):
        battle = self._get(actor, lease, battle_id, generation)
        if battle.state == "aborted" or battle.state == "aborting":
            return self._view(battle)
        if battle.state in _POST_START or battle.state == "closed":
            raise BattleError("battle_started", "cancel cannot resolve a possibly started native battle")
        if battle.resumable and battle.consent == set(battle.players):
            raise BattleError("battle_native_abort_required", "accepted original cores require verified native pre-start cleanup")
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
        if battle.abort_pending == {actor}:
            self.reservations._finish(battle, "aborted", actor, request, response)
        battle.abort_pending.remove(actor)
        battle.abort_acked.add(actor)
        self._record(battle, actor, request, response)
        if not battle.abort_pending:
            battle.state = "aborted"
            self._archive(battle)
        return self._view(battle)
