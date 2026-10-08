"""Menu state for explicit player choices over authenticated service APIs.

Views are immutable. Actions refer to the displayed generation and captured
world lease; refreshing or reconnecting never implies consent.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import uuid4

from .companion import TeamError, BattleChallengeError


class PlayerMenuError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class MenuRow:
    action: int
    label: str


@dataclass(frozen=True)
class MenuScreen:
    revision: int
    title: str
    status: str
    rows: tuple[MenuRow, ...]
    back: int = 7


def _text(value, limit):
    # Native controls cannot interpret player names as text control sequences.
    return "".join(c if 32 <= ord(c) <= 126 else "?" for c in value)[:limit]


class PlayerMenu:
    """Bounded team/challenge menus. Native battle execution has another owner."""

    def __init__(self, companion):
        self.companion = companion
        self._lock = asyncio.Lock()
        self._page = ("home", None)
        self._team = self._battles = None
        self._players = {}
        self._binding = None
        self._signature = None
        self._actions = {}
        self._screen = MenuScreen(0, "Players", "Connecting", ())
        self._notice = ""

    def _session(self):
        c = self.companion
        return (c.world_id, c.server_epoch, c.session_epoch) if c.connected else None

    @property
    def screen(self):
        return self._screen

    async def refresh(self):
        async with self._lock:
            return await self._refresh()

    async def _refresh(self):
        binding = self._session()
        if binding is None:
            self._binding = None
            self._page = ("home", None)
            self._players, self._team, self._battles = {}, None, None
            return self._show("Players", "Connection lost", [])
        if binding != self._binding:
            self._page = ("home", None)
            self._notice = ""
        self._binding = binding
        # Immutable value copies; the companion owns and validates the roster.
        self._players = {p["player_id"]: p["display_name"] for p in self.companion._players}
        for kind, call in (("team", self.companion.team_rpc), ("battle", self.companion.battle_challenge_rpc)):
            try:
                value = (await call("status" if kind == "team" else "pending"))["result"]
            except (TeamError, BattleChallengeError) as error:
                if error.code not in ("team_disabled", "battle_disabled"):
                    raise
                value = None
            if self._session() != binding:
                self._actions.clear()
                self._signature = None
                raise PlayerMenuError("session_changed")
            if kind == "team": self._team = value
            else: self._battles = value
        return self._render()

    def _show(self, title, status, actions):
        if len(actions) > 6:
            raise PlayerMenuError("menu_capacity")
        title, status = _text(title, 23), _text(status, 31)
        normalized = tuple((_text(label, 25), op, tuple(args)) for label, op, args in actions)
        signature = (self._binding, self._page, title, status, normalized)
        if signature != self._signature:
            revision = self._screen.revision + 1
            if revision > 0xFFFFFFFF:
                raise PlayerMenuError("menu_generation_exhausted")
            self._actions = {i + 1: (op, args) for i, (_, op, args) in enumerate(normalized) if op}
            back = 0 if self._page[0] == "home" else 7
            if back:
                self._actions[back] = ("home", ())
            self._screen = MenuScreen(revision, title, status,
                tuple(MenuRow(i + 1 if op else 0, label) for i, (label, op, _) in enumerate(normalized)), back)
            self._signature = signature
        return self._screen

    def _name(self, player):
        return self._players.get(player, "Disconnected player")

    def _render(self):
        actor = self.companion.config.player_id
        page, target = self._page
        actions = []
        title, status = "Players", self._notice or f"Connected: {len(self._players)}/4"
        if page == "player" and target in self._players and target != actor:
            title = self._name(target)
            if self._team is not None and self._team["team"] is None:
                actions.append(("Invite to team", "team_invite", (target,)))
            if self._battles is not None and not self._battles:
                actions.append(("Challenge 1v1", "battle_invite", (target,)))
            status = self._notice or "Choose an interaction"
        elif page == "team" and self._team is not None:
            title = "Your team"
            own = self._team["team"]
            if own:
                peer = next(p for p in own["members"] if p != actor)
                actions.append((self._name(peer), "", ()))
                actions.append(("Leave team", "team_leave", (own["team_id"], own["generation"])))
                other = next((t for t in self._team["teams"] if t["team_id"] != own["team_id"]), None)
                if other is not None and self._battles is not None and not self._battles:
                    actions.append(("Challenge other team 2v2", "battle_multi", (peer, *other["members"])))
                status = self._notice or "Separate parties and items"
            elif self._team["invitations"]:
                invitation = self._team["invitations"][0]
                params = (invitation["invitation_id"], invitation["generation"])
                if invitation["recipient"] == actor:
                    status = "From " + self._name(invitation["sender"])
                    actions.extend((("Accept invitation", "team_accept", params), ("Decline invitation", "team_decline", params)))
                else:
                    status = "Waiting for " + self._name(invitation["recipient"])
                    actions.append(("Cancel invitation", "team_cancel", params))
            else:
                status = "Choose a player to invite"
        elif page == "battles" and self._battles is not None:
            title = "Challenges"
            if self._battles:
                battle = self._battles[0]
                title = "1v1 challenge" if battle["mode"] == 2 else "2v2 full-party challenge"
                status = self._notice or f"Accepted: {len(battle['consent'])}/{len(battle['players'])}"
                for cp in battle["checkpoints"]:
                    actions.append((f"{self._name(cp['player_id'])[:18]} ({cp['party_count']})", "", ()))
                params = (battle["battle_id"], battle["generation"])
                if battle["state"] in ("invited", "accepted", "prepared"):
                    if actor not in battle["consent"] and actor != battle["sender"]:
                        actions.append(("Accept challenge", "battle_accept", (*params, battle["fingerprint"])))
                    actions.append(("Cancel challenge", "battle_cancel", params))
                    if battle["state"] == "accepted": status = "Waiting for battle coordinator"
                else:
                    status = {"aborting": "Canceling safely", "recovery_required": "Battle recovery required",
                              "running": "Battle in progress", "starting": "Starting battle"}.get(battle["state"], battle["state"])
            else:
                status = self._notice or "No pending challenges"
        else:
            self._page = ("home", None)
            for player in self._players:
                if player != actor:
                    actions.append((self._name(player), "player", (player,)))
            if self._team is not None:
                actions.append(("Team invitation" if self._team["invitations"] else "Your team", "team", ()))
            if self._battles is not None:
                actions.append(("Pending challenge" if self._battles else "Challenges", "battles", ()))
            actions.append(("Refresh", "refresh", ()))
        return self._show(title, status, actions)

    async def choose(self, revision, action):
        async with self._lock:
            if (type(revision) is not int or type(action) is not int or revision != self._screen.revision
                    or action not in self._actions):
                raise PlayerMenuError("stale_menu")
            if self._binding is None or self._session() != self._binding:
                self._actions.clear()
                self._signature = None
                raise PlayerMenuError("session_changed")
            op, args = self._actions[action]
            # Consume before awaiting: double clicks and a lost reply cannot
            # silently repeat a consent or create another invitation.
            self._actions.clear()
            self._signature = None
            self._notice = ""
            if op in ("home", "team", "battles", "player"):
                self._page = (op, args[0] if args else None)
            elif op == "team_invite":
                await self.companion.team_rpc("invite", peer=args[0], invitation_id=str(uuid4()))
                self._page = ("team", None)
            elif op == "team_leave":
                await self.companion.team_rpc("leave", team_id=args[0], generation=args[1])
            elif op in ("team_accept", "team_decline", "team_cancel"):
                await self.companion.team_rpc(op.removeprefix("team_"), invitation_id=args[0], generation=args[1])
            elif op == "battle_invite":
                await self.companion.battle_challenge_rpc("invite", peer=args[0], battle_id=str(uuid4()))
                self._page = ("battles", None)
            elif op == "battle_multi":
                await self.companion.battle_challenge_rpc("invite_multi", teammate=args[0], opponents=list(args[1:]), battle_id=str(uuid4()))
                self._page = ("battles", None)
            elif op in ("battle_accept", "battle_cancel"):
                fields = dict(battle_id=args[0], generation=args[1])
                if op == "battle_accept": fields["fingerprint"] = args[2]
                await self.companion.battle_challenge_rpc(op.removeprefix("battle_"), **fields)
            return await self._refresh()
