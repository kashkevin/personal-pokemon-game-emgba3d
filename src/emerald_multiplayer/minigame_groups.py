"""The host's wireless minigame groups (KNOWN_ISSUES MS-141c; minigame_protocol.py).

Session-local, nothing saved. A player is in at most one group. Before its start a group takes members up to four and
its leader may end it (its members are told: "leader_ended"); a member may leave. Once started, its players' games are
linked through the host: the leader's frames go to every member still in it, a member's commands to the leader. A
started group's player leaves when their game has closed the link (the game's own end, the same for everyone): the
others are not told, their links close the same way; the group is gone when its last player has left. A started
group's player who disconnects, or whose game is gone from the group (its link lost, its game closed, or the start
crossed its leaving the lobby), ends it for everyone else ("player_lost"): their games show a communication error.

Each operation returns its result and the pushes it causes: [(player_id, message)].
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .minigame_protocol import ACTIVITIES, CMD_BYTES, FRAME_BYTES, GROUP_MAX, MAX_GROUP
from .protocol import PROTOCOL_VERSION
from .protocol import ProtocolError


@dataclass
class _Group:
    group_id: int
    activity: str
    players: list[str]                       # leader first, then members in the order they joined
    link_players: dict[str, bytes]
    started: bool = False
    left: set[str] = field(default_factory=set)


class MinigameGroups:
    def __init__(self, max_players: int = MAX_GROUP):
        self.max_players = max(2, min(MAX_GROUP, max_players))
        self._groups: dict[int, _Group] = {}
        self._of: dict[str, int] = {}
        self._next = 1
        self.relayed = 0

    # ---- views ----------------------------------------------------------------------------------------------------
    def _view(self, group: _Group, actor: str, names: dict[str, str]) -> dict:
        return {"group_id": group.group_id, "activity": group.activity, "leader": group.players[0],
                "players": [{"player_id": p, "display_name": names.get(p, "?")[:64] or "?"} for p in group.players],
                "index": group.players.index(actor), "started": group.started,
                "minimum": ACTIVITIES[group.activity][1]}

    def group_of(self, player_id: str):
        group_id = self._of.get(player_id)
        return self._groups.get(group_id) if group_id is not None else None

    def status(self, actor: str, activity: str, names: dict[str, str]) -> dict:
        """The open groups of a game (not started, not full, not the actor's own) and the actor's own group."""
        groups = [{"group_id": g.group_id, "leader_name": names.get(g.players[0], "?")[:64] or "?",
                   "players": len(g.players), "minimum": ACTIVITIES[g.activity][1]}
                  for g in self._groups.values()
                  if g.activity == activity and not g.started and len(g.players) < self.max_players
                  and actor not in g.players][:MAX_GROUP]
        mine = self.group_of(actor)
        return {"activity": activity, "groups": groups,
                "mine": self._view(mine, actor, names) if mine is not None else None}

    # ---- the lobby ------------------------------------------------------------------------------------------------
    def _leave_unstarted(self, actor: str) -> list:
        """The actor's unstarted group left first (a player opening or joining another)."""
        group = self.group_of(actor)
        if group is None:
            return []
        if group.started:
            raise ProtocolError("minigame_busy", "your game is still linked with its group")
        return self.leave(actor, group.group_id)[1]

    def open(self, actor: str, activity: str, link_player: bytes, names: dict[str, str]):
        if activity not in ACTIVITIES:
            raise ProtocolError("invalid_field", "unknown minigame")
        pushes = self._leave_unstarted(actor)
        group_id = self._next
        self._next = self._next % GROUP_MAX + 1
        group = self._groups[group_id] = _Group(group_id, activity, [actor], {actor: link_player})
        self._of[actor] = group_id
        return self._view(group, actor, names), pushes

    def join(self, actor: str, group_id: int, link_player: bytes, names: dict[str, str]):
        group = self._groups.get(group_id)
        if group is None or group.started:
            raise ProtocolError("minigame_gone", "that group has started or ended")
        if actor in group.players:
            return self._view(group, actor, names), []
        if len(group.players) >= self.max_players:
            raise ProtocolError("minigame_full", "that group is full")
        pushes = self._leave_unstarted(actor)
        if group_id not in self._groups:      # (leaving one's own group cannot end this one, but be sure)
            raise ProtocolError("minigame_gone", "that group has started or ended")
        group.players.append(actor)
        group.link_players[actor] = link_player
        self._of[actor] = group_id
        return self._view(group, actor, names), pushes

    def start(self, actor: str, group_id: int, epochs: dict[str, int], names: dict[str, str]):
        group = self._groups.get(group_id)
        if group is None or group.players[0] != actor:
            raise ProtocolError("minigame_not_leader", "only the group's leader starts it")
        if group.started:
            return self._view(group, actor, names), []
        if len(group.players) < ACTIVITIES[group.activity][1]:
            raise ProtocolError("minigame_too_few", "not enough players have joined yet")
        group.started = True
        link_players = [group.link_players[p].hex() for p in group.players]
        pushes = [(player, {"type": "minigame_started", "protocol": PROTOCOL_VERSION,
                            "session_epoch": epochs.get(player, 1), "group_id": group.group_id,
                            "activity": group.activity, "index": index, "link_players": link_players})
                  for index, player in enumerate(group.players)]
        return self._view(group, actor, names), pushes

    def _close(self, group: _Group, reason: str, epochs: dict[str, int], skip: str | None = None) -> list:
        self._groups.pop(group.group_id, None)
        for player in group.players:
            if self._of.get(player) == group.group_id:
                del self._of[player]
        return [(player, {"type": "minigame_closed", "protocol": PROTOCOL_VERSION,
                          "session_epoch": epochs.get(player, 1), "group_id": group.group_id, "reason": reason})
                for player in group.players if player != skip and player not in group.left]

    def leave(self, actor: str, group_id: int, epochs: dict[str, int] | None = None, lost: bool = False):
        """The actor leaves (group_id 0: whatever group they are in). Returns ({"left": bool}, pushes).

        ``lost``: the actor's game is gone from the group (its link lost, its game closed, or it never started the link
        because it left the lobby as the group started) - a started group ends for the others, whose games would wait
        for it ("player_lost"). Otherwise a started group's player leaves when its game closed the link at its end."""
        epochs = epochs or {}
        group = self.group_of(actor)
        if group is None or (group_id and group.group_id != group_id):
            return {"left": False}, []
        if group.started:
            if lost and actor not in group.left:
                return {"left": True}, self._close(group, "player_lost", epochs, skip=actor)
            # its game closed the link: the same end as everyone's; nobody is told
            group.left.add(actor)
            self._of.pop(actor, None)
            if group.left >= set(group.players):
                self._groups.pop(group.group_id, None)
            return {"left": True}, []
        if group.players[0] == actor:
            return {"left": True}, self._close(group, "leader_ended", epochs, skip=actor)
        group.players.remove(actor)
        group.link_players.pop(actor, None)
        self._of.pop(actor, None)
        return {"left": True}, []

    def disconnected(self, actor: str, epochs: dict[str, int]) -> list:
        """The actor's session ended: an unstarted group is left as by leave; a started one ends for the others."""
        group = self.group_of(actor)
        if group is None:
            return []
        if group.started and actor not in group.left:
            return self._close(group, "player_lost", epochs, skip=actor)
        return self.leave(actor, group.group_id, epochs)[1]

    def stop(self, epochs: dict[str, int]) -> list:
        """The host stops: every group ends."""
        pushes = []
        for group in list(self._groups.values()):
            pushes += self._close(group, "host_stopped", epochs)
        return pushes

    # ---- the link -------------------------------------------------------------------------------------------------
    def link(self, actor: str, group_id: int, data: bytes, epochs: dict[str, int]) -> list:
        """A link frame from the actor's game: the leader's to every member still in, a member's to the leader."""
        group = self._groups.get(group_id)
        if group is None or not group.started or actor not in group.players or actor in group.left:
            return []   # a frame that crossed the group's end: nothing to do
        index = group.players.index(actor)
        if index == 0:
            if len(data) not in (0, FRAME_BYTES):
                raise ProtocolError("invalid_field", "the leader's frame is 0 or 70 bytes")
            targets = [p for p in group.players[1:] if p not in group.left]
        else:
            if len(data) != CMD_BYTES:
                raise ProtocolError("invalid_field", "a member's command is 14 bytes")
            targets = [] if group.players[0] in group.left else [group.players[0]]
        self.relayed += len(targets)
        payload = data.hex()
        return [(player, {"type": "minigame_link", "session_epoch": epochs.get(player, 1), "group_id": group_id,
                          "source": index, "data": payload}) for player in targets]
