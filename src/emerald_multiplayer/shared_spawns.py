"""Host-authoritative shared wild spawn slots for one shared map instance.

Phase 3 (docs/shared-spawn-architecture.md in the engine repository): while a
game is connected to a multiplayer world, every visible land wild Pokemon is a
slot on this board. The host chooses its species, level, personality (from
which every game derives the same gender, nature, ability and Unown letter),
shiny status and tile once, when the slot is created; only its tile and facing
change afterwards, when the host moves it. A client may only claim a slot that
is open or that it already holds (a reconnect resumes it). The first valid
claim wins; a caught or defeated Pokemon is removed for everybody and its slot
can be refilled. Nothing here touches the network or the game.

Time: the board's clock is the shared world's *active* clock (seconds during
which somebody is online, Phase 11), so lifetimes and claim grace periods stop
while nobody plays. Saved state holds remaining durations only, never absolute
clock values, so it survives a host restart.

Limits (owner decisions, 2026-10-13): 8 slots per map instance normally, 12
during a mass outbreak. An outbreak raises the limit to 12 in total; it does
not add 12 on top of 8. When an outbreak ends the map returns to 8: the
director retires the open Pokemon above the limit (``trim``, outbreak ones
first, oldest first), never one that somebody is battling, and new spawns wait
until fewer than 8 remain, so nothing is duplicated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

NORMAL_SLOT_LIMIT = 8
OUTBREAK_SLOT_LIMIT = 12
MAX_SLOTS = OUTBREAK_SLOT_LIMIT
# A claimant who disconnects keeps the Pokemon for this much active time, so a
# battle that was running when the link dropped can still report its result
# (see docs: a longer absence can let another player catch it).
CLAIM_GRACE_SECONDS = 600.0
FRESH_SECONDS = 3.0  # a slot younger than this plays its appear animation

OPEN = "open"
CLAIMED = "claimed"
REMOVED = "removed"

KIND_NORMAL = "normal"
KIND_OUTBREAK = "outbreak"

# Results of claim()/result()/release(). Only "consumed" grants anything, once.
GRANTED = "granted"
BUSY = "busy"
GONE = "gone"
NOT_CLAIMANT = "not_claimant"
CONSUMED = "consumed"
RELEASED = "released"

# Battle outcomes the games report (shared_world_protocol.RESULTS) and what
# they do to the slot: caught or defeated removes it for everyone; running,
# losing or a cancelled battle leaves it for the others.
REMOVING_RESULTS = frozenset({"caught", "defeated"})
RESULTS = frozenset({"caught", "defeated", "ran", "fled", "lost", "cancelled"})

DIR_SOUTH, DIR_NORTH, DIR_WEST, DIR_EAST = 1, 2, 3, 4
DIRECTIONS = (DIR_SOUTH, DIR_NORTH, DIR_WEST, DIR_EAST)
STEP = {DIR_SOUTH: (0, 1), DIR_NORTH: (0, -1), DIR_WEST: (-1, 0), DIR_EAST: (1, 0)}

STATE_VERSION = 1


@dataclass
class Slot:
    spawn_id: int
    species: int
    level: int
    personality: int
    shiny: bool
    kind: str
    x: int
    y: int
    facing: int
    expires_at: float   # active seconds
    created_at: float   # active seconds
    form: int = 0
    move_seq: int = 0
    state: str = OPEN
    claimant: str | None = None
    grace_until: float | None = None
    end_reason: str | None = None


@dataclass
class SpawnBoard:
    """Slots of one shared map instance. ``clock`` returns active seconds."""

    map_key: str
    clock: Callable[[], float]
    allocate_id: Callable[[], int] | None = None
    next_id: int = 1  # used only without ``allocate_id`` (stand-alone boards)
    outbreak_active: bool = False
    slots: dict[int, Slot] = field(default_factory=dict)
    last_fill: float = float("-inf")

    # ------------------------------------------------------------ limits
    def limit(self) -> int:
        return OUTBREAK_SLOT_LIMIT if self.outbreak_active else NORMAL_SLOT_LIMIT

    def live(self) -> list[Slot]:
        return [s for s in sorted(self.slots.values(), key=lambda s: s.spawn_id) if s.state != REMOVED]

    def live_count(self) -> int:
        return sum(1 for s in self.slots.values() if s.state != REMOVED)

    def set_outbreak(self, active: bool) -> None:
        """Switch the limit. This alone removes nothing (see ``trim``)."""
        self.outbreak_active = bool(active)

    def trim(self) -> list[int]:
        """Back to the limit after an outbreak: retire open Pokemon above it,
        outbreak ones first and the oldest first. A claimed Pokemon is never
        taken away; while claims keep the map above the limit nothing new
        spawns. Returns the retired ids."""
        excess = self.live_count() - self.limit()
        if excess <= 0:
            return []
        candidates = sorted((s for s in self.slots.values() if s.state == OPEN),
                            key=lambda s: (s.kind != KIND_OUTBREAK, s.created_at, s.spawn_id))
        retired = []
        for slot in candidates[:excess]:
            slot.state = REMOVED
            slot.end_reason = "outbreak_ended"
            retired.append(slot.spawn_id)
        return retired

    def occupied(self) -> set[tuple[int, int]]:
        return {(s.x, s.y) for s in self.slots.values() if s.state != REMOVED}

    # ------------------------------------------------------------ create
    def _new_id(self) -> int:
        if self.allocate_id is not None:
            return self.allocate_id()
        spawn_id = self.next_id
        self.next_id += 1
        return spawn_id

    def create(self, *, species: int, level: int, personality: int, shiny: bool, x: int, y: int,
               lifetime: float, kind: str = KIND_NORMAL, facing: int = DIR_SOUTH, form: int = 0) -> int | None:
        """Add a slot if there is room. The host calls this; clients never do.

        Returns the stable spawn id (never reused), or None when the map is at
        its limit or the tile already holds a Pokemon.
        """
        if kind not in (KIND_NORMAL, KIND_OUTBREAK):
            raise ValueError("unknown spawn kind")
        if kind == KIND_OUTBREAK and not self.outbreak_active:
            raise ValueError("outbreak slots need an active outbreak")
        if facing not in DIRECTIONS:
            raise ValueError("unknown facing")
        if not 0 <= personality <= 0xFFFFFFFF or not 1 <= level <= 100 or species <= 0:
            raise ValueError("invalid spawn attributes")
        if self.live_count() >= self.limit() or (x, y) in self.occupied():
            return None
        now = self.clock()
        spawn_id = self._new_id()
        self.slots[spawn_id] = Slot(
            spawn_id=spawn_id, species=int(species), level=int(level), personality=int(personality),
            shiny=bool(shiny), kind=kind, x=int(x), y=int(y), facing=facing,
            expires_at=now + float(lifetime), created_at=now, form=int(form))
        return spawn_id

    def get(self, spawn_id: int) -> Slot | None:
        slot = self.slots.get(spawn_id)
        return None if slot is None or slot.state == REMOVED else slot

    # ------------------------------------------------------------ movement
    def move(self, spawn_id: int, x: int, y: int, facing: int) -> bool:
        """The host walks an open Pokemon one tile (or turns it in place)."""
        slot = self.get(spawn_id)
        if slot is None or slot.state != OPEN or facing not in DIRECTIONS:
            return False
        if (x, y) != (slot.x, slot.y):
            if abs(x - slot.x) + abs(y - slot.y) != 1 or (x, y) in self.occupied():
                return False
        if (x, y, facing) == (slot.x, slot.y, slot.facing):
            return False
        slot.x, slot.y, slot.facing = int(x), int(y), facing
        slot.move_seq = (slot.move_seq + 1) & 0xFF
        return True

    def retire(self, spawn_id: int, reason: str = "despawned") -> bool:
        """Remove an open Pokemon that wandered off (never a claimed one)."""
        slot = self.get(spawn_id)
        if slot is None or slot.state != OPEN:
            return False
        slot.state = REMOVED
        slot.end_reason = reason
        return True

    # ------------------------------------------------------------ claim
    def claim(self, player: str, spawn_id: int) -> str:
        """First valid claim wins. Returns GRANTED, BUSY or GONE."""
        slot = self.get(spawn_id)
        if slot is None:
            return GONE
        if slot.state == CLAIMED:
            if slot.claimant == player:  # a reconnect resumes the same claim
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
        CONSUMED exactly once; a repeated report returns GONE, so nothing is
        granted twice. Every other outcome releases the slot (RELEASED).
        """
        if outcome not in RESULTS:
            raise ValueError("unknown result")
        slot = self.slots.get(spawn_id)
        if slot is None or slot.state == REMOVED:
            return GONE
        if slot.state != CLAIMED or slot.claimant != player:
            return NOT_CLAIMANT
        if outcome not in REMOVING_RESULTS:
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
        """The player walked away from an engaged spawn (map change, no result)."""
        slot = self.slots.get(spawn_id)
        if slot is None or slot.state == REMOVED:
            return GONE
        if slot.state != CLAIMED or slot.claimant != player:
            return NOT_CLAIMANT
        slot.state = OPEN
        slot.claimant = None
        slot.grace_until = None
        return RELEASED

    def claims_of(self, player: str) -> list[int]:
        return [s.spawn_id for s in self.slots.values() if s.state == CLAIMED and s.claimant == player]

    # ------------------------------------------------------------ connection
    def player_disconnected(self, player: str, grace: float = CLAIM_GRACE_SECONDS) -> None:
        now = self.clock()
        for slot in self.slots.values():
            if slot.state == CLAIMED and slot.claimant == player and slot.grace_until is None:
                slot.grace_until = now + grace

    def player_reconnected(self, player: str) -> None:
        """The claimant is back: its claims stay until it reports or releases them."""
        for slot in self.slots.values():
            if slot.state == CLAIMED and slot.claimant == player:
                slot.grace_until = None

    # ------------------------------------------------------------ time
    def tick(self) -> list[int]:
        """Expire open slots and end lapsed grace periods. Returns the changed ids."""
        now = self.clock()
        changed: list[int] = []
        for slot in self.slots.values():
            if slot.state == OPEN and now >= slot.expires_at:
                slot.state = REMOVED
                slot.end_reason = "expired"
                changed.append(slot.spawn_id)
            elif slot.state == CLAIMED and slot.grace_until is not None and now >= slot.grace_until:
                slot.state = OPEN
                slot.claimant = None
                slot.grace_until = None
                if now >= slot.expires_at:  # its lifetime ran out during the battle
                    slot.state = REMOVED
                    slot.end_reason = "expired"
                changed.append(slot.spawn_id)
        return changed

    # ------------------------------------------------------------ sync
    def snapshot(self, viewer: str | None = None) -> list[dict]:
        """Open and claimed slots, as every client of this map instance sees them.

        Removed slots are never sent. "mine" and "busy" are per viewer.
        """
        now = self.clock()
        out = []
        for slot in self.live():
            out.append({
                "spawn_id": slot.spawn_id, "species": slot.species, "level": slot.level,
                "personality": slot.personality, "shiny": slot.shiny, "form": slot.form,
                "kind": slot.kind, "x": slot.x, "y": slot.y, "facing": slot.facing,
                "move_seq": slot.move_seq,
                "mine": slot.state == CLAIMED and slot.claimant is not None and slot.claimant == viewer,
                "busy": slot.state == CLAIMED and slot.claimant != viewer,
                "fresh": now - slot.created_at < FRESH_SECONDS,
                "seconds_left": max(0, int(slot.expires_at - now)),
            })
        return out

    def prune(self) -> None:
        """Forget removed slots (ids are never reused, so lookups stay GONE)."""
        for spawn_id in [i for i, s in self.slots.items() if s.state == REMOVED]:
            del self.slots[spawn_id]

    # ------------------------------------------------------------ persistence
    def to_state(self) -> dict:
        """Restart-safe state: live slots with remaining durations only."""
        now = self.clock()
        slots = []
        for slot in self.live():
            slots.append({
                "spawn_id": slot.spawn_id, "species": slot.species, "level": slot.level,
                "personality": slot.personality, "shiny": slot.shiny, "form": slot.form, "kind": slot.kind,
                "x": slot.x, "y": slot.y, "facing": slot.facing, "move_seq": slot.move_seq,
                "state": slot.state, "claimant": slot.claimant,
                "remaining": max(0.0, slot.expires_at - now), "age": max(0.0, now - slot.created_at),
                "grace_remaining": None if slot.grace_until is None else max(0.0, slot.grace_until - now),
            })
        return {"version": STATE_VERSION, "map_key": self.map_key, "outbreak_active": self.outbreak_active,
                "next_id": self.next_id, "slots": slots}

    @classmethod
    def from_state(cls, state: dict, clock: Callable[[], float],
                   allocate_id: Callable[[], int] | None = None) -> "SpawnBoard":
        """Rebuild a board after a host restart.

        Every player was disconnected by the restart, so each claim restarts its
        grace period (or keeps what was left of it): the claimant can still
        report its battle and nothing is caught twice.
        """
        if type(state) is not dict or state.get("version") != STATE_VERSION:
            raise ValueError("unsupported spawn board state")
        board = cls(map_key=str(state["map_key"]), clock=clock, allocate_id=allocate_id,
                    next_id=int(state.get("next_id", 1)), outbreak_active=bool(state.get("outbreak_active")))
        now = clock()
        for item in state.get("slots", []):
            claimant = item.get("claimant")
            claimed = item.get("state") == CLAIMED and isinstance(claimant, str)
            grace = item.get("grace_remaining")
            grace = CLAIM_GRACE_SECONDS if grace is None else max(0.0, float(grace))
            slot = Slot(
                spawn_id=int(item["spawn_id"]), species=int(item["species"]), level=int(item["level"]),
                personality=int(item["personality"]), shiny=bool(item["shiny"]), kind=str(item["kind"]),
                x=int(item["x"]), y=int(item["y"]), facing=int(item["facing"]),
                expires_at=now + max(0.0, float(item["remaining"])), created_at=now - max(0.0, float(item["age"])),
                form=int(item.get("form", 0)), move_seq=int(item.get("move_seq", 0)) & 0xFF,
                state=CLAIMED if claimed else OPEN, claimant=claimant if claimed else None,
                grace_until=now + grace if claimed else None)
            if slot.kind not in (KIND_NORMAL, KIND_OUTBREAK) or slot.facing not in DIRECTIONS:
                raise ValueError("invalid spawn slot in saved state")
            board.slots[slot.spawn_id] = slot
        return board


class SpawnBoards:
    """Every shared map instance of one world. Boards never share slots; spawn
    ids are unique across the whole world and never reused."""

    def __init__(self, clock: Callable[[], float], next_id: int = 1) -> None:
        self._clock = clock
        self._boards: dict[str, SpawnBoard] = {}
        self.next_id = max(1, int(next_id))

    def allocate_id(self) -> int:
        spawn_id = self.next_id
        self.next_id = self.next_id % 0x7FFFFFFF + 1
        return spawn_id

    def board(self, map_key: str) -> SpawnBoard:
        if map_key not in self._boards:
            self._boards[map_key] = SpawnBoard(map_key=map_key, clock=self._clock, allocate_id=self.allocate_id)
        return self._boards[map_key]

    def existing(self, map_key: str) -> SpawnBoard | None:
        return self._boards.get(map_key)

    def keys(self) -> list[str]:
        return sorted(self._boards)

    def boards(self) -> list[SpawnBoard]:
        return [self._boards[key] for key in sorted(self._boards)]

    def find(self, spawn_id: int) -> tuple[SpawnBoard, Slot] | None:
        for board in self._boards.values():
            slot = board.slots.get(spawn_id)
            if slot is not None:
                return board, slot
        return None

    def to_state(self) -> dict:
        return {"version": STATE_VERSION, "next_id": self.next_id,
                "boards": [board.to_state() for board in self.boards() if board.live_count() or board.outbreak_active]}

    @classmethod
    def from_state(cls, state: dict, clock: Callable[[], float]) -> "SpawnBoards":
        if type(state) is not dict or state.get("version") != STATE_VERSION:
            raise ValueError("unsupported spawn state")
        boards = cls(clock, int(state.get("next_id", 1)))
        for item in state.get("boards", []):
            board = SpawnBoard.from_state(item, clock, boards.allocate_id)
            boards._boards[board.map_key] = board
        return boards
