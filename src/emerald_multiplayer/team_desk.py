"""Session-local team invitations for the development server.

The master specification permits two-person teams and individual parties,
wallets and friendship. It does not settle membership across disconnect or
server restart. This bounded development coordinator therefore dissolves a
team when either authenticated lease disappears/changes; restart starts empty.
A player changes partners by explicitly leaving, then inviting/accepting again.
No battle execution, rewards, permanent relationship or save mutation occurs.

Reuse audit (October 8, 2026): pinned RHH ownership 88c7ef7 derives from
expansion/1.17.1 bb1093. battle_setup.c:352 provides AI-partner multi battles;
union_room.c:1683 enters cable multi battles; battle_controller_link_partner.c
uses link player IDs/controller transfers. Maintained upstream
6057b187f946094d614e9c34bc12731ea6a5b7bb retains that link-oriented controller:
https://github.com/rh-hideout/pokeemerald-expansion/blob/6057b187f946094d614e9c34bc12731ea6a5b7bb/src/battle_controller_link_partner.c
Wired-Ariel v1.7.2 remains a vanilla Cable Club reference, not a compatible
canonical team coordinator. No external implementation was incorporated.

Callers MUST pass actor/lease from the authenticated connection, never from
actor claims in a request body. connected_sessions must expose the server's
current authenticated roster with a fresh monotonic lease on every reconnect.
Call refresh on roster changes, and before publishing membership to clients.
Methods are synchronous: no await separates consent validation from formation.
The invitation timeout is a configurable development transport bound, not a
gameplay cooldown or a friendship requirement.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import math
import time
from uuid import UUID, uuid4

from .protocol import MAX_COUNTER, MAX_PLAYERS, ProtocolError

MAX_TEAMS = MAX_PLAYERS // 2
MAX_PENDING_INVITATIONS = MAX_PLAYERS // 2


class TeamError(ProtocolError):
    """A bounded team operation failed without accepting stale consent."""


def _uuid(value: str, field: str) -> str:
    try:
        valid = (isinstance(value, str) and len(value) == 36
                 and str(UUID(value)) == value and UUID(value).int != 0)
    except (ValueError, AttributeError):
        valid = False
    if not valid:
        raise TeamError("invalid_field", f"{field} must be a nonzero canonical UUID")
    return value


def _lease(value: int) -> int:
    if type(value) is not int or not 1 <= value <= MAX_COUNTER:
        raise TeamError("invalid_field", "lease is outside its integer bounds")
    return value


@dataclass(frozen=True)
class _Invitation:
    invitation_id: str
    generation: str
    sender: str
    recipient: str
    leases: tuple[int, int]
    expires: float


@dataclass(frozen=True)
class _Team:
    team_id: str
    generation: str
    members: tuple[str, str]
    leases: tuple[int, int]
    invitation: _Invitation


class TeamDesk:
    """At most two disjoint invitations and two two-person connected teams.

    Invitation creation expresses the sender's consent only. The designated
    recipient must accept the exact generation under its captured live lease.
    Already teamed players must leave explicitly before a new invitation.
    Formation/leave cancels obsolete invitations. Exact accepted retries are
    harmless while that same team and both original leases remain current.
    """

    def __init__(self, connected_sessions: Callable[[], Mapping[str, int]], *,
                 timeout: float = 60, clock: Callable[[], float] = time.monotonic):
        if not callable(connected_sessions) or not callable(clock):
            raise ValueError("roster and clock must be callable")
        if (type(timeout) not in (int, float) or not 1 <= timeout <= 3600
                or not math.isfinite(timeout)):
            raise ValueError("invitation timeout must be between 1 and 3600 seconds")
        self._connected_sessions = connected_sessions
        self._clock, self.timeout = clock, float(timeout)
        self._last_time: float | None = None
        self._invitations: dict[str, _Invitation] = {}
        self._teams: dict[str, _Team] = {}

    def _roster(self) -> tuple[dict[str, int], float]:
        raw = self._connected_sessions()
        if not isinstance(raw, Mapping) or len(raw) > MAX_PLAYERS:
            raise TeamError("team_capacity", "the authenticated roster must contain at most four players")
        roster = {_uuid(player, "player_id"): _lease(lease) for player, lease in raw.items()}
        now = self._clock()
        try:
            valid_clock = (type(now) in (int, float) and now >= 0 and math.isfinite(now)
                           and (self._last_time is None or now >= self._last_time))
        except OverflowError:
            valid_clock = False
        if not valid_clock:
            raise TeamError("team_clock", "the invitation clock must be finite and monotonic")
        self._last_time = float(now)
        return roster, float(now)

    def _team_for(self, player: str) -> _Team | None:
        return next((team for team in self._teams.values() if player in team.members), None)

    def _formed_from(self, invitation_id: str) -> _Team | None:
        return next((team for team in self._teams.values()
                     if team.invitation.invitation_id == invitation_id), None)

    def _drop_invitations(self, players: tuple[str, ...]) -> None:
        participants = set(players)
        for key, invitation in tuple(self._invitations.items()):
            if participants.intersection((invitation.sender, invitation.recipient)):
                del self._invitations[key]

    def _prune(self, roster: Mapping[str, int], now: float) -> None:
        for key, team in tuple(self._teams.items()):
            if any(roster.get(player) != lease for player, lease in zip(team.members, team.leases)):
                del self._teams[key]
                self._drop_invitations(team.members)
        for key, invitation in tuple(self._invitations.items()):
            if (invitation.expires <= now
                    or roster.get(invitation.sender) != invitation.leases[0]
                    or roster.get(invitation.recipient) != invitation.leases[1]
                    or self._team_for(invitation.sender) is not None
                    or self._team_for(invitation.recipient) is not None):
                del self._invitations[key]

    def refresh(self) -> None:
        """Trusted server lifecycle hook; expire disconnected/stale membership."""
        roster, now = self._roster()
        self._prune(roster, now)

    def _auth(self, actor: str, lease: int) -> tuple[dict[str, int], float]:
        _uuid(actor, "actor"); _lease(lease)
        roster, now = self._roster()
        self._prune(roster, now)
        if roster.get(actor) != lease:
            raise TeamError("stale_lease", "actor is not the current authenticated connected player")
        return roster, now

    @staticmethod
    def _team_view(team: _Team) -> dict:
        return dict(state="formed", team_id=team.team_id, generation=team.generation,
                    members=list(team.members), invitation_id=team.invitation.invitation_id,
                    invitation_generation=team.invitation.generation)

    @staticmethod
    def _invitation_view(invitation: _Invitation, now: float) -> dict:
        return dict(state="invited", invitation_id=invitation.invitation_id,
                    generation=invitation.generation, sender=invitation.sender,
                    recipient=invitation.recipient,
                    expires_in=max(0.0, invitation.expires - now))

    def invite(self, actor: str, lease: int, peer: str, invitation_id: str) -> dict:
        """Create a sender's invitation; neither participant joins implicitly."""
        _uuid(peer, "peer"); _uuid(invitation_id, "invitation_id")
        roster, now = self._auth(actor, lease)
        if actor == peer:
            raise TeamError("invalid_team", "a team requires two different players")
        if peer not in roster:
            raise TeamError("player_offline", "the invited player must be connected")
        formed = self._formed_from(invitation_id)
        if formed is not None:
            if (actor, peer) != (formed.invitation.sender, formed.invitation.recipient):
                raise TeamError("request_conflict", "invitation ID belongs to different participants")
            return self._team_view(formed)
        existing = self._invitations.get(invitation_id)
        if existing is not None:
            if (actor, peer) != (existing.sender, existing.recipient):
                raise TeamError("request_conflict", "invitation ID belongs to different participants")
            return self._invitation_view(existing, now)
        if self._team_for(actor) is not None or self._team_for(peer) is not None:
            raise TeamError("team_already_member", "leave the current team before changing teammates")
        if (len(self._invitations) >= MAX_PENDING_INVITATIONS
                or any({actor, peer}.intersection((invite.sender, invite.recipient))
                       for invite in self._invitations.values())):
            raise TeamError("team_invite_busy", "a participant already has a pending invitation")
        invitation = _Invitation(invitation_id, str(uuid4()), actor, peer,
                                 (lease, roster[peer]), now + self.timeout)
        self._invitations[invitation_id] = invitation
        return self._invitation_view(invitation, now)

    def _pending(self, actor: str, invitation_id: str, generation: str) -> _Invitation:
        _uuid(invitation_id, "invitation_id"); _uuid(generation, "generation")
        invitation = self._invitations.get(invitation_id)
        if invitation is None:
            raise TeamError("team_invitation_missing", "the pending invitation no longer exists")
        if actor not in (invitation.sender, invitation.recipient):
            raise TeamError("team_not_participant", "actor is not an invitation participant")
        if generation != invitation.generation:
            raise TeamError("team_generation_mismatch", "the invitation has been replaced")
        return invitation

    def accept(self, actor: str, lease: int, invitation_id: str, generation: str) -> dict:
        """Accept only as the designated recipient, then form one pair."""
        _uuid(invitation_id, "invitation_id"); _uuid(generation, "generation")
        self._auth(actor, lease)
        formed = self._formed_from(invitation_id)
        if formed is not None:
            invitation = formed.invitation
            if actor != invitation.recipient:
                raise TeamError("team_not_recipient", "only the invited player can accept")
            if generation != invitation.generation:
                raise TeamError("team_generation_mismatch", "the invitation has been replaced")
            return self._team_view(formed)
        invitation = self._pending(actor, invitation_id, generation)
        if actor != invitation.recipient:
            raise TeamError("team_not_recipient", "only the invited player can accept")
        if self._team_for(invitation.sender) is not None or self._team_for(invitation.recipient) is not None:
            raise TeamError("team_already_member", "leave the current team before changing teammates")
        if len(self._teams) >= MAX_TEAMS:
            raise TeamError("team_capacity", "at most two teams may coexist")
        members = (invitation.sender, invitation.recipient)
        team = _Team(str(uuid4()), str(uuid4()), members, invitation.leases, invitation)
        self._drop_invitations(members)
        self._teams[team.team_id] = team
        return self._team_view(team)

    def cancel(self, actor: str, lease: int, invitation_id: str, generation: str) -> dict:
        """Withdraw a pending invitation only as its original sender."""
        self._auth(actor, lease)
        invitation = self._pending(actor, invitation_id, generation)
        if actor != invitation.sender:
            raise TeamError("team_not_sender", "only the sender can cancel the invitation")
        del self._invitations[invitation_id]
        return dict(state="canceled", invitation_id=invitation_id)

    def decline(self, actor: str, lease: int, invitation_id: str, generation: str) -> dict:
        """Reject a pending invitation only as its designated recipient."""
        self._auth(actor, lease)
        invitation = self._pending(actor, invitation_id, generation)
        if actor != invitation.recipient:
            raise TeamError("team_not_recipient", "only the invited player can decline")
        del self._invitations[invitation_id]
        return dict(state="declined", invitation_id=invitation_id)

    def leave(self, actor: str, lease: int, team_id: str, generation: str) -> dict:
        """A current member explicitly leaves the exact current pair."""
        _uuid(team_id, "team_id"); _uuid(generation, "generation")
        self._auth(actor, lease)
        team = self._teams.get(team_id)
        if team is None or actor not in team.members:
            raise TeamError("team_not_member", "actor is not a member of this current team")
        if generation != team.generation:
            raise TeamError("team_generation_mismatch", "the team has been replaced")
        del self._teams[team_id]
        self._drop_invitations(team.members)
        return dict(state="left", team_id=team_id)

    def status(self, actor: str, lease: int) -> dict:
        """Bounded roster/team view, with invitations visible to participants."""
        _, now = self._auth(actor, lease)
        team = self._team_for(actor)
        return dict(scope="session-local-development",
                    team=None if team is None else self._team_view(team),
                    teams=[self._team_view(value) for value in self._teams.values()],
                    invitations=[self._invitation_view(value, now)
                                 for value in self._invitations.values()
                                 if actor in (value.sender, value.recipient)])
