"""Host-authoritative shared wild spawn slots for one shared map instance.

Phase 3 (and the slot rules Phase 4 uses): the host owns every visible wild
Pokemon. Species, level, form, gender and shiny status are chosen once, when a
slot is created, and never change. A client may only claim a slot that is open
or that it already holds (reconnect). The first valid claim wins; a caught or
defeated Pokemon is removed for everybody and its slot can be refilled. Nothing
here touches the network or the game; the transport calls these methods.

Limits (owner decisions, 2026-10-13): 8 slots per map instance normally, 12
during a mass outbreak. An outbreak raises the limit, it does not add slots on
top of 8. Ending an outbreak only stops new spawns above 8; existing valid
spawns are kept, so nothing is duplicated.
"""

from __future__ import annotations

from dataclasses import dataclass, field

NORMAL_SLOT_LIMIT = 8
OUTBREAK_SLOT_LIMIT = 12
CLAIM_GRACE_SECONDS = 60.0

OPEN = "open"
CLAIMED = "claimed"
REMOVED = "removed"

KIND_NORMAL = "normal"
KIND_OUTBREAK = "outbreak"

# Results of claim()/result(). Only "consumed" grants a reward, once.
GRANTED = "granted"
BUSY = "busy"
GONE = "gone"
NOT_CLAIMANT = "not_claimant"
CONSUMED = "consumed"
RELEASED = "released"

RESULTS = ("caught", "defeated", "fled")


@dataclass
class Slot:
    spawn_id: int
    species: int
    level: int
    form: int
    gender: int
    shiny: bool
    kind: str
    expires_at: float
    state: str = OPEN
    claimant: str | None = None
    grace_until: float | None = None
    end_reason: str | None = None


@dataclass
class SpawnBoard:
    """Slots of one shared map instance. Pass a clock for deterministic tests."""

    map_key: str
    clock: object  # zero-argument callable returning seconds (float)
    next_id: int = 1
    outbreak_active: bool = False
    slots: dict[int, Slot] = field(default_factory=dict)

    # ------------------------------------------------------------ limits
    def limit(self) -> int:
        return OUTBREAK_SLOT_LIMIT if self.outbreak_active else NORMAL_SLOT_LIMIT

    def live_count(self) -> int:
        return sum(1 for s in self.slots.values() if s.state != REMOVED)

    def set_outbreak(self, active: bool) -> None:
        """Switch the limit. Ending an outbreak keeps existing spawns (no duplicates)."""
        self.outbreak_active = bool(active)

    # ------------------------------------------------------------ create
    def create(self, *, species: int, level: int, form: int = 0, gender: int = 0,
               shiny: bool = False, lifetime: float, kind: str = KIND_NORMAL) -> int | None:
        """Add a slot if there is room. The host calls this; clients never do.

        Returns the stable spawn id, or None when the map is at its limit.
        """
        if kind not in (KIND_NORMAL, KIND_OUTBREAK):
            raise ValueError("unknown spawn kind")
        if kind == KIND_OUTBREAK and not self.outbreak_active:
            raise ValueError("outbreak slots need an active outbreak")
        if self.live_count() >= self.limit():
            return None
        spawn_id = self.next_id
        self.next_id += 1
        self.slots[spawn_id] = Slot(
            spawn_id=spawn_id, species=int(species), level=int(level), form=int(form),
            gender=int(gender), shiny=bool(shiny), kind=kind,
            expires_at=self.clock() + float(lifetime),
        )
        return spawn_id

    # ------------------------------------------------------------ claim
    def claim(self, player: str, spawn_id: int) -> str:
        """First valid claim wins. Returns GRANTED, BUSY or GONE."""
        slot = self.slots.get(spawn_id)
        if slot is None or slot.state == REMOVED:
            return GONE
        if slot.state == CLAIMED:
            if slot.claimant == player:  # reconnect resumes the same claim
                slot.grace_until = None
                return GRANTED
            return BUSY
        slot.state = CLAIMED
        slot.claimant = player
        slot.grace_until = None
        return GRANTED

    # ------------------------------------------------------------ result
    def result(self, player: str, spawn_id: int, outcome: str) -> str:
        """Apply a battle result. Only the claimant may report it.

        "caught" and "defeated" remove the Pokemon for everybody and return
        CONSUMED exactly once; a repeated report returns GONE, so no reward is
        paid twice. "fled" releases the slot back to open (RELEASED).
        """
        if outcome not in RESULTS:
            raise ValueError("unknown result")
        slot = self.slots.get(spawn_id)
        if slot is None or slot.state == REMOVED:
            return GONE
        if slot.state != CLAIMED or slot.claimant != player:
            return NOT_CLAIMANT
        if outcome == "fled":
            slot.state = OPEN
            slot.claimant = None
            slot.grace_until = None
            return RELEASED
        slot.state = REMOVED
        slot.claimant = None
        slot.grace_until = None
        slot.end_reason = outcome
        return CONSUMED

    def release(self, player: str, spawn_id: int) -> str:
        """Player walked away from an engaged spawn (map change, no result)."""
        slot = self.slots.get(spawn_id)
        if slot is None or slot.state == REMOVED:
            return GONE
        if slot.state != CLAIMED or slot.claimant != player:
            return NOT_CLAIMANT
        slot.state = OPEN
        slot.claimant = None
        slot.grace_until = None
        return RELEASED

    # ------------------------------------------------------------ connection
    def player_disconnected(self, player: str) -> None:
        now = self.clock()
        for slot in self.slots.values():
            if slot.state == CLAIMED and slot.claimant == player and slot.grace_until is None:
                slot.grace_until = now + CLAIM_GRACE_SECONDS

    # ------------------------------------------------------------ time
    def tick(self, online_players: int) -> list[int]:
        """Advance timers. Returns the ids removed or released during this tick.

        With nobody online nothing ages: every deadline is pushed forward by the
        time that passed (consistent with the world-clock rule in Phase 11).
        """
        now = self.clock()
        last = getattr(self, "_last_tick", None)
        self._last_tick = now
        changed: list[int] = []
        if online_players == 0:
            paused = (now - last) if last is not None else 0.0
            for slot in self.slots.values():
                slot.expires_at += paused
                if slot.grace_until is not None:
                    slot.grace_until += paused
            return changed
        for slot in list(self.slots.values()):
            if slot.state == REMOVED:
                continue
            if slot.state == OPEN and now >= slot.expires_at:
                slot.state = REMOVED
                slot.end_reason = "expired"
                changed.append(slot.spawn_id)
            elif slot.state == CLAIMED and slot.grace_until is not None and now >= slot.grace_until:
                slot.state = OPEN
                slot.claimant = None
                slot.grace_until = None
                changed.append(slot.spawn_id)
        return changed

    # ------------------------------------------------------------ sync
    def snapshot(self, viewer: str | None = None) -> list[dict]:
        """Current open and claimed slots, for sending to a joining or reconnecting client.

        Removed slots are not sent. Shiny and species come from the host record.
        """
        now = self.clock()
        out = []
        for slot in sorted(self.slots.values(), key=lambda s: s.spawn_id):
            if slot.state == REMOVED:
                continue
            out.append({
                "spawn_id": slot.spawn_id,
                "species": slot.species,
                "level": slot.level,
                "form": slot.form,
                "gender": slot.gender,
                "shiny": slot.shiny,
                "kind": slot.kind,
                "state": slot.state,
                "seconds_left": max(0, int(slot.expires_at - now)),
                "claimed_by_you": slot.claimant is not None and slot.claimant == viewer,
            })
        return out

    def prune(self) -> None:
        """Drop removed slots older than needed for id lookups (ids are never reused)."""
        for spawn_id in [i for i, s in self.slots.items() if s.state == REMOVED]:
            del self.slots[spawn_id]


class SpawnBoards:
    """Every shared map instance of one world. Boards never share slots."""

    def __init__(self, clock) -> None:
        self._clock = clock
        self._boards: dict[str, SpawnBoard] = {}

    def board(self, map_key: str) -> SpawnBoard:
        if map_key not in self._boards:
            self._boards[map_key] = SpawnBoard(map_key=map_key, clock=self._clock)
        return self._boards[map_key]

    def keys(self) -> list[str]:
        return sorted(self._boards)
