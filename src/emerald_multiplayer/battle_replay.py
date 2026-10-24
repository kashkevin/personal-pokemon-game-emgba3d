"""Reconstruct the existing router by replaying authenticated durable evidence.

Replay never writes a native mailbox or reserves/releases a character. Every
historical response retains its actual lease. Only an explicit verified quorum
can switch a paused replay continuation back to live dispatch.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

from .battle_desk import BattleDesk, BattleError, _Battle
from .battle_execution import _NativeRoute, _Room
from .battle_roster import CanonicalBattler
from .native_battle import NativeBinding, Opcode


class _ReadOnlyReservations:
    def __init__(self, record):
        self.record = record

    def _reserve(self, battle, actor):
        if actor not in self.record["view"]["players"]:
            raise BattleError("battle_replay_mismatch", "replay changed its original reservation")

    def _finish(self, battle, kind, actor, request, response):
        # Existing Desk validations already ran; publication happens separately
        # against the real same-DB reservation after the whole replay settles.
        pass


class ReplayDesk(BattleDesk):
    def __init__(self, original, record, journal, current_leases):
        view = record["view"]
        players, leases = tuple(view["players"]), tuple(record["leases"])
        super().__init__(original.store, lambda actor: leases[players.index(actor)])
        self.reservations = _ReadOnlyReservations(record)
        self.checkpoints = {}
        roster = []
        brings = record.get("brings") or [0] * len(players)
        for slot, (actor, current, pinned) in enumerate(zip(players, current_leases, view["checkpoints"])):
            cp = original._auth(actor, current)
            if cp is None or (cp.revision, cp.sha256) != (pinned["revision"], pinned["sha256"]):
                raise BattleError("canonical_head_mismatch", "retained battle checkpoint changed")
            self.checkpoints[actor] = cp
            battler = CanonicalBattler.from_checkpoint(cp, world_id=record["world_id"],
                build_id=record["build_id"], ruleset_id=record["ruleset_id"], source_slot=slot, mode=view["mode"],
                bring=brings[slot])
            if battler.party_count != pinned["party_count"]:
                raise BattleError("canonical_head_mismatch", "retained party count changed")
            roster.append(battler)
        self.battle = _Battle(view["battle_id"], view["generation"], view["sender"], players, leases,
            tuple(roster), bytes.fromhex(record["rng"]), view["fingerprint"], self._now()+self.timeout,
            mode=view["mode"], gym=view.get("gym", 0), environment=view.get("environment", 0), resumable=True,
            state="accepted", consent=set(players),
            incarnations=dict(zip(players, record["incarnations"])),
            lease_lineage=tuple(journal.lineage) if journal.renewal_epoch else (),
            renewal_digest=journal.renewal_digest)
        self._active[self.battle.battle_id] = self.battle

    def _auth(self, actor, lease):
        b = self.battle
        if actor not in b.players or lease != b.leases[b.players.index(actor)]:
            raise BattleError("battle_replay_mismatch", "replay changed its logical original actor")
        return self.checkpoints[actor]

    def _auth_lease(self, actor, lease):
        self._auth(actor, lease)  # the logical original actor, never the store's current lease

    def refresh(self):
        pass  # Historical elapsed wall time cannot alter a verified replay.

    def _heads(self, battle):
        # Current authenticated heads were pinned before construction and are
        # checked again at activation; replay must not consult retired leases.
        if battle is not self.battle:
            raise BattleError("battle_replay_mismatch", "replay changed its frozen canonical battle")


class RouteReplay:
    def __init__(self, owner, record, journal, current_leases):
        self.owner, self.journal = owner, journal
        self.desk = ReplayDesk(owner.desk, record, journal, current_leases)
        self.string_lengths, self.observer = owner.string_lengths, None
        self.room = _Room(self.desk.battle, owner.directory / (self.desk.battle.battle_id+".json"),
                          ready=dict(self.desk.battle.incarnations), journal=journal, admitted=dict(journal.admitted))
        self.native_sequences = {actor: (lease, self.room.ready[actor], sequence)
            for actor, lease, sequence in zip(self.room.battle.players, self.room.battle.leases,
                                              journal.header["initial_sequences"])}
        self.streams = {actor: [] for actor in self.room.battle.players}
        for actor, ident, command, response in journal.completed:
            self.streams[actor].append((ident, command, response))
        self.positions = dict.fromkeys(self.streams, 0)
        self.remaining = len(journal.completed)
        self.blocked = {}
        self.peek = getattr(owner, "peek", False)
        self.receive_many = getattr(owner, "receive_many", False)
        self.deliver = getattr(owner, "deliver", False)
        self.boundary, self.live = asyncio.Event(), asyncio.Event()
        self.error = None
        self.route = self.room.route = _NativeRoute(self, self.room)
        self.task = None

    @property
    def replaying(self):
        """True while the route consumes durable history (before activation goes live)."""
        return not self.live.is_set()

    def history_consumed(self):
        """The observed router (journal v4) has answered every recorded response and observation and waits for live
        ones: the boundary, as when the lock-step router blocks on its first command beyond history."""
        self.boundary.set()

    def logical(self, actor, command):
        return self.journal._renew_control(actor, command, self.journal.header["leases"])

    async def _dispatch(self, room, actor, command):
        if self.live.is_set():
            return await self.owner._dispatch(room, actor, command)
        position = self.positions[actor]
        stream = self.streams[actor]
        if position < len(stream):
            ident, recorded, response = stream[position]
            if self.logical(actor, recorded) != command:
                raise BattleError("battle_replay_mismatch", "router command differs from durable history")
            self.positions[actor] += 1
            self.remaining -= 1
            if not self.remaining and self.blocked:
                self.boundary.set()
            return recorded, response
        pending = self.journal.pending.get(actor)
        if pending is not None and self.logical(actor, pending[1]) != command:
            raise BattleError("battle_replay_mismatch", "uncertain dispatch differs from reconstructed router")
        if actor in self.blocked:
            raise BattleError("battle_replay_mismatch", "replay issued two commands for one original core")
        self.blocked[actor] = command
        if not self.remaining:
            self.boundary.set()
        await self.live.wait()
        if self.error is not None:
            raise self.error
        del self.blocked[actor]
        rebound = self.journal._renew_control(actor, command, self.room.battle.leases)
        return rebound, await self.owner._resumed_command(self.room, actor, rebound)

    async def _run(self):
        try:
            await self.route.run()
            if self.remaining:
                raise BattleError("battle_replay_mismatch", "router closed before consuming all durable receipts")
            self.room.state = "closed"
        except BaseException as error:
            self.error = error
            raise
        finally:
            self.boundary.set()

    async def prepare(self):
        self.task = asyncio.create_task(self._run(), name="native-battle-router-replay")
        await self.boundary.wait()
        if self.error is not None:
            await self.task
        if self.remaining:
            raise BattleError("battle_replay_mismatch", "replay stopped before the last persisted response")
        return self.room

    def activate(self):
        b = self.room.battle
        b.leases = self.journal.leases
        b.lease_lineage, b.renewal_digest = tuple(self.journal.lineage), self.journal.renewal_digest
        b.deadline = self.owner.desk._now()+self.owner.desk.timeout
        self.desk = self.route.desk = self.owner.desk
        self.owner.desk._active[b.battle_id] = b
        self.room.dispatch_ids = dict(self.journal.ids)
        self.room.state = "executing"
        self.room.task = self.task
        self.observer = self.owner.observer
        self.owner.rooms[b.battle_id] = self.room
        self.live.set()

    async def close(self):
        if self.task is not None and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
