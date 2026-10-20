"""Update 32 (feature 10): battle lobbies, where the format follows the trainers who joined.

A trainer opens a lobby and invites one to three connected trainers. Each invitee joins or declines; nobody else is
pulled in, and an invitee who has not answered is not counted. The lobby shows who joined, who is still invited and
who declined, and the format the joined trainers make: two trainers 1v1, three 1v1v1, four 1v1v1v1 or 2v2 (the creator
chooses between the two, and a 2v2 partner).

Only the creator starts the lobby, once at least one invitee has joined. Starting is the ordinary challenge of that
format (battle_desk.py) for exactly the joined trainers, sent by the creator's own game, so consent, the original game
core and recovery are the challenge's own: every joined trainer then accepts the exact challenge in "Pending challenge"
and enters. start() links the lobby to that challenge (its battle ID, players and format must be the lobby's).

A lobby ends when it is started, when its creator cancels or leaves it, when nobody but its creator remains (everyone
declined or left), or at its deadline (DEFAULT_TIMEOUT seconds without a start). A trainer whose connection is replaced
leaves the lobby. An ended lobby stays visible to its members for LINGER seconds, with the reason, then is dropped.

Session-local and in memory, like the team desk (team_desk.py): a host restart starts with no lobbies. Callers pass
actor and lease from the authenticated connection, never from a request body.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import math
import time
from uuid import UUID, uuid4

from .protocol import MAX_COUNTER, MAX_PLAYERS, ProtocolError

DEFAULT_TIMEOUT = 300
LINGER = 60
SCOPE = "session-local-battle-lobbies-v1"
# The format of a lobby's joined trainers, and the challenge mode (battle_desk.py) each format starts.
FORMATS = {2: ("1v1",), 3: ("1v1v1",), 4: ("1v1v1v1", "2v2")}
MODES = {"1v1": 2, "2v2": 3, "1v1v1v1": 5, "1v1v1": 6}
OPEN, STARTED, ENDED = "open", "started", "ended"


class LobbyError(ProtocolError):
    """A lobby operation was refused; nothing changed."""


def _uuid(value, name):
    try:
        valid = isinstance(value, str) and len(value) == 36 and str(UUID(value)) == value and UUID(value).int != 0
    except (ValueError, AttributeError):
        valid = False
    if not valid:
        raise LobbyError("invalid_field", f"{name} must be a nonzero canonical UUID")
    return value


def detected_formats(count):
    """The formats a lobby with `count` joined trainers (its creator included) can start."""
    return FORMATS.get(count, ())


@dataclass
class _Lobby:
    lobby_id: str
    generation: str
    creator: str
    invited: tuple[str, ...]
    leases: dict[str, int]
    deadline: float
    joined: list[str] = field(default_factory=list)
    declined: list[str] = field(default_factory=list)
    left: list[str] = field(default_factory=list)
    state: str = OPEN
    reason: str | None = None
    battle_id: str | None = None
    format: str | None = None
    ended: float | None = None

    def members(self):
        return (self.creator, *self.invited)

    def waiting(self):
        return [p for p in self.invited if p not in self.joined and p not in self.declined and p not in self.left]


class LobbyDesk:
    """At most two open lobbies; a trainer is in at most one open lobby (as creator, invitee or member)."""

    def __init__(self, connected_sessions: Callable[[], Mapping[str, int]], *, battle_desk=None,
                 timeout: float = DEFAULT_TIMEOUT, linger: float = LINGER, clock: Callable[[], float] = time.monotonic):
        if not callable(connected_sessions) or not callable(clock):
            raise ValueError("roster and clock must be callable")
        for value in (timeout, linger):
            if type(value) not in (int, float) or not 1 <= value <= 3600 or not math.isfinite(value):
                raise ValueError("lobby timeouts must be between 1 and 3600 seconds")
        self._connected_sessions, self._clock = connected_sessions, clock
        self.battle_desk, self.timeout, self.linger = battle_desk, float(timeout), float(linger)
        self._lobbies: dict[str, _Lobby] = {}

    # -- roster and lifecycle ---------------------------------------------------------------------------------------
    def _roster(self):
        raw = self._connected_sessions()
        if not isinstance(raw, Mapping) or len(raw) > MAX_PLAYERS:
            raise LobbyError("lobby_capacity", "the authenticated roster must contain at most four players")
        now = self._clock()
        if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
            raise LobbyError("lobby_clock", "the lobby clock must be finite")
        return {player: lease for player, lease in raw.items()}, float(now)

    def _end(self, lobby, reason, now):
        lobby.state, lobby.reason, lobby.ended = ENDED, reason, now

    def _prune(self, roster, now):
        for key, lobby in tuple(self._lobbies.items()):
            if lobby.state != OPEN:
                if lobby.ended is not None and now - lobby.ended >= self.linger:
                    del self._lobbies[key]
                continue
            if roster.get(lobby.creator) != lobby.leases[lobby.creator]:
                self._end(lobby, "creator_left", now)
                continue
            for player in lobby.invited:
                if player not in lobby.left and player not in lobby.declined and roster.get(player) != lobby.leases[player]:
                    lobby.left.append(player)                     # disconnected: out of the lobby
                    if player in lobby.joined:
                        lobby.joined.remove(player)
            if now >= lobby.deadline:
                self._end(lobby, "timed_out", now)
            elif not lobby.waiting() and len(lobby.joined) < 2:
                self._end(lobby, "nobody_joined", now)

    def refresh(self):
        """Trusted server lifecycle hook (roster changes, before publishing lobbies)."""
        roster, now = self._roster()
        self._prune(roster, now)

    def _auth(self, actor, lease):
        _uuid(actor, "actor")
        if type(lease) is not int or not 1 <= lease <= MAX_COUNTER:
            raise LobbyError("invalid_field", "lease is outside its integer bounds")
        roster, now = self._roster()
        self._prune(roster, now)
        if roster.get(actor) != lease:
            raise LobbyError("stale_lease", "actor is not the current authenticated connected player")
        return roster, now

    def _open_for(self, player):
        return next((lobby for lobby in self._lobbies.values() if lobby.state == OPEN
                     and player in lobby.members() and player not in lobby.declined and player not in lobby.left), None)

    def _get(self, lobby_id, generation):
        _uuid(lobby_id, "lobby_id"); _uuid(generation, "generation")
        lobby = self._lobbies.get(lobby_id)
        if lobby is None:
            raise LobbyError("lobby_missing", "the lobby no longer exists")
        if generation != lobby.generation:
            raise LobbyError("lobby_generation_mismatch", "the lobby has been replaced")
        return lobby

    def _view(self, lobby, now):
        formats = detected_formats(len(lobby.joined)) if lobby.state == OPEN else ()
        return dict(scope=SCOPE, lobby_id=lobby.lobby_id, generation=lobby.generation, creator=lobby.creator,
                    invited=list(lobby.invited), joined=list(lobby.joined), declined=list(lobby.declined),
                    left=list(lobby.left), state=lobby.state, reason=lobby.reason, formats=list(formats),
                    format=lobby.format, battle_id=lobby.battle_id,
                    expires_in=max(0.0, lobby.deadline - now) if lobby.state == OPEN else 0.0)

    # -- operations ---------------------------------------------------------------------------------------------------
    def create(self, actor, lease, invitees, lobby_id):
        """Open a lobby inviting one to three connected trainers; the creator has joined it."""
        _uuid(lobby_id, "lobby_id")
        if type(invitees) is not tuple or not 1 <= len(invitees) <= MAX_PLAYERS - 1:
            raise LobbyError("invalid_lobby", "a lobby invites one to three other trainers")
        for player in invitees:
            _uuid(player, "invitee")
        if len(set(invitees)) != len(invitees) or actor in invitees:
            raise LobbyError("invalid_lobby", "a lobby invites distinct other trainers")
        roster, now = self._auth(actor, lease)
        existing = self._lobbies.get(lobby_id)
        if existing is not None:
            if existing.creator != actor or existing.invited != invitees:
                raise LobbyError("request_conflict", "lobby ID belongs to another lobby")
            return self._view(existing, now)
        offline = [p for p in invitees if p not in roster]
        if offline:
            raise LobbyError("player_offline", "every invited trainer must be connected")
        busy = [p for p in (actor, *invitees) if self._open_for(p) is not None]
        if busy:
            raise LobbyError("lobby_busy", "a trainer is already in an open lobby")
        if self.battle_desk is not None:
            self.battle_desk.refresh()
            if any(set((actor, *invitees)).intersection(b.players) for b in self.battle_desk._active.values()):
                raise LobbyError("battle_busy", "a trainer has an open challenge or battle")
        if sum(1 for lobby in self._lobbies.values() if lobby.state == OPEN) >= MAX_PLAYERS // 2:
            raise LobbyError("lobby_capacity", "at most two lobbies may be open")
        lobby = _Lobby(lobby_id, str(uuid4()), actor, invitees,
                       {p: roster[p] for p in (actor, *invitees)}, now + self.timeout, joined=[actor])
        self._lobbies[lobby_id] = lobby
        return self._view(lobby, now)

    def _answer(self, actor, lease, lobby_id, generation):
        _, now = self._auth(actor, lease)
        lobby = self._get(lobby_id, generation)
        if actor not in lobby.invited:
            raise LobbyError("lobby_not_invited", "only an invited trainer can answer")
        if lobby.state != OPEN:
            raise LobbyError("lobby_closed", "the lobby is no longer open")
        return lobby, now

    def join(self, actor, lease, lobby_id, generation):
        lobby, now = self._answer(actor, lease, lobby_id, generation)
        if actor in lobby.declined or actor in lobby.left:
            raise LobbyError("lobby_answered", "you already left this lobby")
        if actor not in lobby.joined:
            lobby.joined.append(actor)
        return self._view(lobby, now)

    def decline(self, actor, lease, lobby_id, generation):
        lobby, now = self._answer(actor, lease, lobby_id, generation)
        if actor in lobby.joined:
            raise LobbyError("lobby_answered", "you joined: leave the lobby instead")
        if actor not in lobby.declined:
            lobby.declined.append(actor)
        self._prune(self._roster()[0], now)
        return self._view(lobby, now)

    def leave(self, actor, lease, lobby_id, generation):
        """A member leaves; the creator leaving ends the lobby for everyone."""
        _, now = self._auth(actor, lease)
        lobby = self._get(lobby_id, generation)
        if actor not in lobby.members():
            raise LobbyError("lobby_not_member", "actor is not in this lobby")
        if lobby.state == OPEN:
            if actor == lobby.creator:
                self._end(lobby, "cancelled", now)
            else:
                if actor in lobby.joined:
                    lobby.joined.remove(actor)
                if actor not in lobby.left:
                    lobby.left.append(actor)
                self._prune(self._roster()[0], now)
        return self._view(lobby, now)

    def start(self, actor, lease, lobby_id, generation, battle_id):
        """Link the open lobby to the challenge its creator just sent for exactly the joined trainers.

        The challenge must exist, be this creator's, name the joined trainers (no one else) and have a format the
        joined count allows. Then the lobby is started and every member sees the challenge to accept.
        """
        _uuid(battle_id, "battle_id")
        _, now = self._auth(actor, lease)
        lobby = self._get(lobby_id, generation)
        if actor != lobby.creator:
            raise LobbyError("lobby_not_creator", "only the lobby's creator starts it")
        if lobby.state == STARTED and lobby.battle_id == battle_id:
            return self._view(lobby, now)                       # an exact retry
        if lobby.state != OPEN:
            raise LobbyError("lobby_closed", "the lobby is no longer open")
        if len(lobby.joined) < 2:
            raise LobbyError("lobby_too_small", "at least one invited trainer must join first")
        if self.battle_desk is None:
            raise LobbyError("battle_disabled", "this world has not enabled battle challenges")
        battle = self.battle_desk._active.get(battle_id)
        modes = {MODES[f]: f for f in detected_formats(len(lobby.joined))}
        if (battle is None or battle.sender != actor or set(battle.players) != set(lobby.joined)
                or battle.mode not in modes):
            raise LobbyError("lobby_changed", "the challenge does not match the lobby's joined trainers")
        lobby.state, lobby.battle_id, lobby.format, lobby.ended = STARTED, battle_id, modes[battle.mode], now
        return self._view(lobby, now)

    def status(self, actor, lease):
        """The lobbies the actor is part of (open ones, and ended or started ones for LINGER seconds)."""
        _, now = self._auth(actor, lease)
        return dict(scope=SCOPE, lobbies=[self._view(lobby, now) for lobby in self._lobbies.values()
                                          if actor in lobby.members()])
