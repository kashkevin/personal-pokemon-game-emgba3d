"""Explicit challenge consent in the launcher; Enter stays in the native menu."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import itertools
from dataclasses import dataclass
from uuid import uuid4

from .companion import BattleChallengeError, TeamError


class BattlePanelError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class _Action:
    operation: str
    parameters: tuple


class BattlePanelController:
    def __init__(self, session):
        self.session = session
        self._binding = self._snapshot_id = self._preview = None
        self._actions = {}
        self._pending = []
        self._team = None
        self._busy = False

    def _identity(self):
        s, c = self.session, self.session.companion
        if (c is None or not c.connected or not s._open or s._closing or s._game is None
                or s._game.process.returncode is not None or s._signature() != s._binding):
            raise BattlePanelError("connection_lost")
        return (c, s._signature(), s._game, c._bridge, getattr(c._bridge, "incarnation", None))

    def _invalidate(self):
        self._snapshot_id = None
        self._actions.clear()

    def _roster(self):
        return {p["player_id"]: p["display_name"] for p in self.session.companion._players}

    async def _read(self):
        c = self.session.companion
        self._pending = (await c.battle_challenge_rpc("pending"))["result"]
        try:
            self._team = (await c.team_rpc("status"))["result"]
        except TeamError as error:
            if error.code != "team_disabled":
                raise
            self._team = None
        if self._identity() != self._binding:
            raise BattlePanelError("connection_lost")

    @staticmethod
    def _key(view):
        return (view["battle_id"], view["generation"], view["fingerprint"])

    def _duos(self):
        team = self._team
        actor = self.session.companion.config.player_id
        if team is None or team["team"] is None or len(team["teams"]) != 2:
            return None
        own = team["team"]
        other = next((t for t in team["teams"] if t["team_id"] != own["team_id"]), None)
        if other is None:
            return None
        players = (actor, next(p for p in own["members"] if p != actor), *other["members"])
        if len(set(players)) != 4 or not set(players).issubset(self._roster()):
            return None
        return (own["team_id"], own["generation"], other["team_id"], other["generation"], *players)

    async def dispatch(self, snapshot_id=None, action_id=None):
        if self._busy:
            raise BattlePanelError("busy")
        self._busy = True
        try:
            original = self._identity()
            if snapshot_id is None and action_id is None:
                self._invalidate()
                self._binding, self._preview = original, None
                await self._read()
                return self._project("ready")
            action = self._actions.get(action_id) if type(action_id) is str else None
            if (snapshot_id != self._snapshot_id or original != self._binding or action is None):
                raise BattlePanelError("stale")
            self._invalidate()
            if not self.session.can_manage_players:
                raise BattlePanelError("not_ready")
            operation, args = action.operation, action.parameters
            if operation == "discard":
                self._preview = None
                return self._project("ready")
            previous = deepcopy(self._pending)
            await self._read()
            if not self.session.can_manage_players:
                raise BattlePanelError("not_ready")
            roster, actor = self._roster(), self.session.companion.config.player_id
            if operation in {"preview_single", "preview_multi", "preview_ffa"}:
                if self._pending:
                    raise BattlePanelError("stale")
                if operation == "preview_single":
                    if roster.get(args[0]) != args[1]:
                        raise BattlePanelError("roster_changed")
                    self._preview = dict(mode=2, players=[actor, args[0]], names=[roster[actor], roster[args[0]]],
                                         battle_id=str(uuid4()), teams=None)
                elif operation == "preview_ffa":
                    rivals = args[::2]
                    if len(set(rivals)) != 3 or actor in rivals or any(roster.get(p) != n for p, n in zip(args[::2], args[1::2])):
                        raise BattlePanelError("roster_changed")
                    self._preview = dict(mode=5, players=[actor, *rivals], names=[roster[actor], *args[1::2]],
                                         battle_id=str(uuid4()), teams=None)
                else:
                    if self._duos() != args:
                        raise BattlePanelError("roster_changed")
                    players = list(args[4:])
                    self._preview = dict(mode=3, players=players, names=[roster[p] for p in players],
                                         battle_id=str(uuid4()), teams=args)
                return self._project("preview")
            if operation == "invite":
                p = self._preview
                if (p is None or args != (p["battle_id"],) or self._pending
                        or any(roster.get(player) != name for player, name in zip(p["players"], p["names"]))
                        or p["mode"] == 3 and self._duos() != p["teams"]):
                    raise BattlePanelError("roster_changed")
                if p["mode"] == 2:
                    rpc, fields = "invite", dict(peer=p["players"][1], battle_id=p["battle_id"])
                elif p["mode"] == 5:
                    rpc, fields = "invite_ffa", dict(opponents=p["players"][1:], battle_id=p["battle_id"])
                else:
                    rpc, fields = "invite_multi", dict(teammate=p["players"][1], opponents=p["players"][2:], battle_id=p["battle_id"])
                self._preview = None
            else:
                if (len(previous) != 1 or len(self._pending) != 1
                        or self._key(previous[0]) != args or self._key(self._pending[0]) != args):
                    raise BattlePanelError("stale")
                view = self._pending[0]
                if view["state"] != "invited" or view["bound"] or view["started"]:
                    raise BattlePanelError("native_required")
                fields = dict(battle_id=args[0], generation=args[1])
                if operation == "accept":
                    if actor in view["consent"] or actor == view["sender"]:
                        raise BattlePanelError("stale")
                    fields["fingerprint"] = args[2]
                elif operation != "cancel":
                    raise BattlePanelError("stale")
                rpc = operation
            try:
                result = (await self.session.companion.battle_challenge_rpc(rpc, **fields))["result"]
                try:
                    same = self._identity() == original
                except BattlePanelError:
                    same = False
                if not same:
                    raise BattlePanelError("uncertain")
            except (ConnectionError, OSError, asyncio.TimeoutError) as error:
                raise BattlePanelError("uncertain") from error
            notice = "canceled" if result["state"] == "aborted" else "canceling" if rpc == "cancel" else "accepted" if rpc == "accept" else "invited"
            try:
                await self._read()
                return self._project(notice)
            except Exception as error:
                raise BattlePanelError("applied_refresh_required") from error
        except BattleChallengeError as error:
            code = {"battle_disabled": "unsupported", "battle_original_core_required": "not_ready",
                "battle_native_abort_required": "native_required", "battle_started": "native_required",
                "battle_busy": "busy", "player_busy": "busy", "player_offline": "roster_changed",
                "battle_offer_changed": "stale", "battle_generation_mismatch": "stale"}.get(error.code, "refused")
            self._invalidate()
            raise BattlePanelError(code) from error
        except BaseException:
            self._invalidate()
            raise
        finally:
            self._busy = False

    def _project(self, notice):
        if self._identity() != self._binding:
            raise BattlePanelError("connection_lost")
        self._invalidate()
        self._snapshot_id = str(uuid4())
        roster, actions = self._roster(), []
        actor = self.session.companion.config.player_id
        def add(label, op, args=()):
            token = str(uuid4())
            self._actions[token] = _Action(op, tuple(args))
            actions.append(dict(label=label, action_id=token))
        if self.session.can_manage_players:
            if self._preview:
                add("Send proposal and consent", "invite", (self._preview["battle_id"],))
                add("Back without sending", "discard")
            elif not self._pending:
                for peer, name in roster.items():
                    if peer != actor:
                        add("Review 1v1 with " + name, "preview_single", (peer, name))
                duos = self._duos()
                if duos:
                    add("Review 2v2 between current teams", "preview_multi", duos)
                others = [(p, n) for p, n in roster.items() if p != actor]
                ffa_capable = getattr(self.session.companion.config, "battle_ffa_enabled", True)
                for trio in (list(itertools.combinations(others, 3))[:6] if ffa_capable else ()):
                    add("Review 1v1v1v1 free-for-all with " + ", ".join(n for _, n in trio), "preview_ffa",
                        tuple(x for pair in trio for x in pair))
            else:
                view = self._pending[0]
                if view["state"] == "invited" and not view["bound"] and not view["started"]:
                    if actor not in view["consent"] and actor != view["sender"]:
                        add("Accept this exact challenge", "accept", self._key(view))
                    add("Decline / cancel this proposal", "cancel", self._key(view))
        return deepcopy(dict(snapshot_id=self._snapshot_id, actor=actor, roster=roster, pending=self._pending,
            preview=self._preview, actions=actions, notice=notice, has_duos=self._duos() is not None))


MESSAGES = {
    "ready": "Host challenge snapshot updated. Enter battle remains an explicit in-game choice.",
    "preview": "Review both sides. Sending this proposal records your consent; every other Trainer must accept separately.",
    "invited": "Proposal acknowledged. Each other Trainer must accept the exact saved-party challenge.",
    "accepted": "Your consent was acknowledged. Once everyone accepts, use Players → Challenges → Enter battle in each original game.",
    "canceled": "The host canceled this unstarted proposal.",
    "canceling": "The host is canceling safely; this is not permission to close a held game.",
    "native_required": "This challenge needs its native lifecycle. Use the in-game Players menu or the existing Cancel battle entry / Recover battle controls; keep the original game open.",
    "unsupported": "This host does not enable battle challenges.",
    "stale": "The displayed proposal changed. Refresh and review its current participants and party counts.",
    "roster_changed": "A Trainer or team changed. Refresh and review a new proposal.",
    "not_ready": "Finish the current save, menu interaction, trade, battle or recovery before changing consent.",
    "connection_lost": "The original authenticated game connection is no longer available.",
    "uncertain": "The request may have reached the host. Refresh status before making another decision; keep the original game open.",
    "applied_refresh_required": "The host acknowledged the action, but its next status could not be read. Refresh; do not assume the request failed.",
    "busy": "Finish the current launcher action, then refresh.",
    "refused": "The host refused this choice. Refresh the current challenge; existing recovery evidence was retained.",
    "unavailable": "Challenge status could not be read. Earlier details are a snapshot only.",
}


class BattlePanel:
    def __init__(self, parent, worker):
        import tkinter as tk
        from tkinter import ttk
        self.worker = worker
        self._connected = self._eligible = self._pending = self._closed = self._suspended = False
        self._snapshot = None
        self._buttons = []
        from .launcher_display import scrollable_frame
        self.frame = scrollable_frame(parent, padding=16)
        self.refresh_button = ttk.Button(self.frame, text="Refresh challenges", command=self.refresh, state="disabled")
        self.refresh_button.pack(anchor="w")
        self.message = tk.StringVar(value="Open your character, then refresh challenges.")
        ttk.Label(self.frame, textvariable=self.message, wraplength=560).pack(anchor="w", pady=8)
        self.details = tk.StringVar(value="No challenge snapshot.")
        ttk.Label(self.frame, textvariable=self.details, wraplength=560, justify="left").pack(anchor="w", pady=8)
        self.actions = ttk.Frame(self.frame)
        self.actions.pack(fill="x")
        ttk.Label(self.frame, text="Proposals use the current host-saved parties. Save now first if you want recent field progress included. 2v2 uses both current teams with independent full parties, up to six Pokémon per Trainer. Accepting never presses Enter or controls battle moves. No wagers, rewards, experience or automatic forfeits are added; a free-for-all (1v1v1v1) has every Trainer against every other.", wraplength=560).pack(anchor="w", pady=12)

    def refresh(self):
        self._request()

    def _request(self, token=None):
        if self._closed or self._suspended or self._pending or not self._connected:
            return
        snapshot_id = self._snapshot["snapshot_id"] if token and self._snapshot else None
        if self.worker is not None and self.worker.request_battle_panel(snapshot_id, token):
            self._pending = True
            self._enable()

    def _enable(self):
        available = self._connected and not (self._pending or self._closed or self._suspended)
        self.refresh_button.configure(state="normal" if available else "disabled")
        for button in self._buttons:
            button.configure(state="normal" if available and self._eligible and self._snapshot else "disabled")

    def _clear_actions(self):
        for button in self._buttons:
            button.destroy()
        self._buttons.clear()
        self._snapshot = None

    def _render(self, snapshot):
        from tkinter import ttk
        self._clear_actions()
        self._snapshot = snapshot
        self.message.set(MESSAGES.get(snapshot["notice"], MESSAGES["ready"]))
        preview, pending = snapshot["preview"], snapshot["pending"]
        if preview:
            names = preview["names"]
            sides = names if preview["mode"] in (2, 5) else (" + ".join(names[:2]), " + ".join(names[2:]))
            self.details.set({2: "1v1", 5: "1v1v1v1 free-for-all (everyone against everyone)"}.get(preview["mode"], "2v2 full parties") + " proposal\n" + " vs ".join(sides)
                + "\nParty counts are confirmed by the host when the proposal is created.")
        elif pending:
            view = pending[0]
            names, actor = snapshot["roster"], snapshot["actor"]
            parties = {p["player_id"]: p["party_count"] for p in view["checkpoints"]}
            lines = []
            coop = view["mode"] == 4  # both trainers together against a Gym Leader and partner
            ffa = view["mode"] == 5   # four independent trainers: no sides at all
            for index, player in enumerate(view["players"]):
                lines.append((f"Team: " if coop else f"Trainer {index + 1}: " if ffa else f"Side {index % 2 + 1}: ") + names.get(player, 'Offline Trainer')
                    + (" (you)" if player == actor else "") + f" · {parties[player]} Pokémon · "
                    + ("accepted" if player in view["consent"] else "awaiting consent"))
            label = "Team Gym battle" if coop else "1v1v1v1 free-for-all" if ffa else ("1v1" if view["mode"] == 2 else "2v2 full parties")
            self.details.set(label + " · " + view["state"]
                + "\n" + "\n".join(lines) + "\n" + ("Everyone accepted: use the original game’s Players menu to Enter." if view["state"] == "accepted" else "Refresh to see new consent; no automatic polling."))
        else:
            self.details.set("No pending challenge. Review a connected opponent below."
                + ("\nTwo current teams can review a 2v2 proposal." if snapshot["has_duos"] else "\nForm two teams in Trainer Card & Players to propose 2v2 here."))
        for action in snapshot["actions"]:
            button = ttk.Button(self.actions, text=action["label"], command=lambda token=action["action_id"]: self._request(token))
            button.pack(anchor="w", pady=3)
            self._buttons.append(button)

    def handle_event(self, event):
        if self._closed:
            return event.kind == "battle_panel"
        if event.kind == "battle_panel":
            self._pending = False
            if event.code == "ready" and self._connected and event.battle_snapshot is not None:
                self._render(event.battle_snapshot)
            else:
                self._clear_actions()
                self.message.set(MESSAGES.get(event.code, MESSAGES["unavailable"]))
            self._enable()
            return True
        if event.kind in {"status", "complete"}:
            connected = event.kind == "status" and event.state == "running" and event.connected
            if self._connected and not connected:
                self._clear_actions()
                self.message.set(MESSAGES["connection_lost"])
            self._connected = connected
            self._eligible = connected and event.player_actions_available
            self._enable()
        return False

    def set_closing(self, value):
        self._suspended = bool(value)
        self._enable()

    def close(self):
        self._closed = True
        self._clear_actions()
        self._enable()
