"""Explicit launcher Championship choices on the existing session-owned loop.

Only opaque, single-use actions cross from Tk. Their retained parameters bind
the displayed bracket and original session/core; the network request is built
here from those parameters. No action accepts or enters a native battle.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from .championship_protocol import VERSION, validate_championship_reply
from .companion import BattleChallengeError


class ChampionshipPanelError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class _Action:
    operation: str
    parameters: tuple


class ChampionshipPanelController:
    """One controller per LauncherSession; call only from its owning loop."""

    def __init__(self, session):
        self.session = session
        self._binding = None
        self._snapshot_id = None
        self._actions = {}
        self._current = None
        self._history = []
        self._preview = None
        self._busy = False

    def _identity(self):
        session = self.session
        companion = session.companion
        if (companion is None or not companion.connected or not session._open or session._closing
                or session._game is None or session._game.process.returncode is not None
                or session._signature() != session._binding):
            raise ChampionshipPanelError("connection_lost")
        bridge = companion._bridge
        return (companion, session._signature(), session._game, bridge,
                getattr(bridge, "incarnation", None))

    def _invalidate(self):
        self._snapshot_id = None
        self._actions.clear()

    def _roster(self):
        companion = self.session.companion
        return [dict(player_id=player["player_id"], display_name=player["display_name"])
                for player in companion._players]

    async def _rpc(self, operation, **fields):
        original = self._identity()
        request = dict(version=VERSION, operation=operation, **fields)
        mutating = operation not in {"status", "history"}
        try:
            reply = await self.session.companion.battle_challenge_rpc("pending", championship=request)
        except BattleChallengeError as error:
            code = {
                "invalid_field": "unsupported", "invalid_fields": "unsupported",
                "championship_unsupported": "unsupported", "championship_disabled": "unsupported",
                "battle_disabled": "unsupported", "championship_roster_changed": "roster_changed",
                "championship_changed": "stale", "championship_busy": "busy",
                "championship_cancel_pending": "cancel_pending", "championship_not_ready": "not_ready",
                "battle_original_core_required": "not_ready", "player_offline": "roster_changed",
                "battle_busy": "busy", "player_busy": "busy",
            }.get(error.code, "refused")
            raise ChampionshipPanelError(code) from error
        except (ConnectionError, OSError, asyncio.TimeoutError) as error:
            raise ChampionshipPanelError("uncertain" if mutating else "connection_lost") from error
        try:
            same = self._identity() == original
        except ChampionshipPanelError:
            same = False
        if not same:
            raise ChampionshipPanelError("uncertain" if mutating else "connection_lost")
        extension = reply.get("championship")
        validate_championship_reply(extension, self.session.companion.config.player_id, request)
        self._current = deepcopy(extension["current"])
        if operation == "history":
            self._history = deepcopy(extension["history"])
        return reply

    async def dispatch(self, snapshot_id=None, action_id=None):
        if self._busy:
            raise ChampionshipPanelError("busy")
        self._busy = True
        try:
            original = self._identity()
            if snapshot_id is None and action_id is None:
                self._invalidate()
                self._preview = None
                self._binding = original
                await self._rpc("history")
                return self._project("ready")
            action = self._actions.get(action_id) if type(action_id) is str else None
            if (type(snapshot_id) is not str or snapshot_id != self._snapshot_id
                    or original != self._binding or action is None):
                self._invalidate()
                raise ChampionshipPanelError("stale")
            # Consume all displayed actions before awaiting or checking mutable
            # state. A double click, lost reply or reconnect cannot replay one.
            self._invalidate()
            if not self.session.can_manage_championship:
                raise ChampionshipPanelError("not_ready")
            operation, parameters = action.operation, action.parameters
            if operation == "preview":
                roster = {p["player_id"]: p["display_name"] for p in self._roster()}
                actor = self.session.companion.config.player_id
                if len(roster) != 4 or actor not in roster:
                    raise ChampionshipPanelError("roster_changed")
                players = [actor, *sorted(player for player in roster if player != actor)]
                self._preview = dict(championship_id=str(uuid4()), players=players,
                                     names=[roster[player] for player in players])
                return self._project("preview")
            if operation == "discard":
                self._preview = None
                return self._project("ready")
            if operation == "create":
                preview = self._preview
                if preview is None or parameters != (preview["championship_id"], *preview["players"]):
                    raise ChampionshipPanelError("stale")
                roster = {p["player_id"]: p["display_name"] for p in self._roster()}
                if (set(roster) != set(preview["players"])
                        or [roster.get(player) for player in preview["players"]] != preview["names"]):
                    self._preview = None
                    raise ChampionshipPanelError("roster_changed")
                self._preview = None
                await self._rpc("create", championship_id=parameters[0], players=list(parameters[1:]))
                return self._project("proposal_created")
            current = self._current
            if current is None or parameters[:3] != self._params(current):
                raise ChampionshipPanelError("stale")
            fields = dict(zip(("championship_id", "generation", "fingerprint"), parameters[:3]))
            actor = self.session.companion.config.player_id
            if operation == "accept":
                if current["state"] != "proposed" or actor in current["consent"]:
                    raise ChampionshipPanelError("stale")
                await self._rpc("accept", **fields)
                notice = "accepted" if actor in self._current["consent"] else "ready"
            elif operation == "withdraw":
                if current["state"] != "active" or actor not in current["cancel_consent"]:
                    raise ChampionshipPanelError("stale")
                await self._rpc("accept", **fields)
                notice = ("withdrawn" if self._current["state"] == "active"
                          and actor not in self._current["cancel_consent"] else "ready")
            elif operation == "cancel":
                if current["state"] not in {"proposed", "active"} or actor in current["cancel_consent"]:
                    raise ChampionshipPanelError("stale")
                await self._rpc("cancel", **fields)
                notice = ("canceled" if self._current["state"] == "canceled" else "cancel_voted"
                          if actor in self._current["cancel_consent"] else "ready")
            elif operation == "match":
                match = current["matches"][parameters[3]]
                if (current["state"] != "active" or current["cancel_consent"]
                        or actor not in match["players"] or match["attempt"] != parameters[4]
                        or match["state"] not in {"ready", "draw", "canceled"}):
                    raise ChampionshipPanelError("stale")
                reply = await self._rpc("match", **fields, round=match["round"], attempt=match["attempt"])
                latest = self._current["matches"][match["round"]]
                pending = any(battle["battle_id"] == latest["battle_id"] for battle in reply["result"])
                notice = "challenge_ready" if latest["state"] == "invited" and pending else "match_waiting"
            elif operation == "recover":
                match = current["matches"][parameters[3]]
                if (current["state"] != "active" or actor not in match["players"]
                        or match["state"] != "waiting" or match["attempt"] != parameters[4]
                        or match["battle_id"] != parameters[5]):
                    raise ChampionshipPanelError("stale")
                await self._rpc("recover", **fields, round=match["round"],
                                attempt=match["attempt"], battle_id=match["battle_id"])
                latest = self._current["matches"][match["round"]]
                notice = ("match_canceled" if latest["state"] == "canceled" else "match_unresolved"
                          if latest["state"] == "waiting" else "ready")
            else:
                raise ChampionshipPanelError("stale")
            return self._project(notice)
        except BaseException:
            self._invalidate()
            raise
        finally:
            self._busy = False

    @staticmethod
    def _params(view):
        return (view["championship_id"], view["generation"], view["fingerprint"])

    def _project(self, notice):
        if self._identity() != self._binding:
            raise ChampionshipPanelError("connection_lost")
        self._invalidate()
        self._snapshot_id = str(uuid4())
        actor = self.session.companion.config.player_id
        mutable = self.session.can_manage_championship
        actions = []

        def add(label, operation, parameters=()):
            token = str(uuid4())
            self._actions[token] = _Action(operation, tuple(parameters))
            actions.append(dict(action_id=token, label=label))

        current = self._current
        if mutable:
            if self._preview is not None:
                add("Create and accept these pairings", "create", (self._preview["championship_id"], *self._preview["players"]))
                add("Discard preview", "discard")
            elif current is None or current["state"] in {"completed", "canceled"}:
                if len(self._roster()) == 4:
                    add("Review new four-Trainer bracket", "preview")
            else:
                parameters = self._params(current)
                if current["state"] == "proposed":
                    if actor not in current["consent"]:
                        add("Accept the displayed pairings", "accept", parameters)
                    add("Cancel this proposal", "cancel", parameters)
                elif current["state"] == "active":
                    if actor in current["cancel_consent"]:
                        add("Withdraw your cancel vote", "withdraw", parameters)
                    else:
                        add("Vote to cancel this bracket", "cancel", parameters)
                    for match in current["matches"]:
                        if actor in match["players"]:
                            if match["state"] == "waiting":
                                add("Recover waiting match", "recover", (*parameters, match["round"],
                                    match["attempt"], match["battle_id"]))
                            elif not current["cancel_consent"] and match["state"] in {"ready", "draw", "canceled"}:
                                label = ("Semifinal 1", "Semifinal 2", "Final")[match["round"]]
                                add(("Propose rematch: " if match["attempt"] else "Propose 1v1: ") + label,
                                    "match", (*parameters, match["round"], match["attempt"]))
        return deepcopy(dict(snapshot_id=self._snapshot_id, player_id=actor,
            current=current, history=self._history, players=self._roster(), preview=self._preview,
            mutable=mutable, actions=actions, notice=notice))


_MESSAGES = {
    "ready": "Host bracket refreshed. Refresh again for later changes.",
    "preview": "Review both semifinal pairings below. Create records your acceptance; each other Trainer must accept separately.",
    "proposal_created": "Proposal recorded with your acceptance. Waiting for the other Trainers to review and accept.",
    "accepted": "Your bracket acceptance is recorded. Each match still needs normal battle consent and Enter in the game.",
    "cancel_voted": "Your cancel vote is recorded. All four must agree, and outstanding matches must settle safely. No forfeit is assigned.",
    "withdrawn": "Your cancel vote was withdrawn. Refresh to see the other Trainers' choices.",
    "canceled": "The host confirmed this bracket is canceled. No winner or reward was assigned.",
    "challenge_ready": "Match proposed. In the game, open Players → Challenges for normal acceptance and Enter battle.",
    "match_waiting": "The host retained the original match or result. Refresh to check its state; keep any game waiting for recovery open.",
    "match_canceled": "Durable host evidence proves this unstarted match is safely canceled. No winner was assigned. Propose a rematch separately if desired.",
    "match_unresolved": "Safe cancellation is not proven. The original invitation may have been dispatched, or original admission/result receipts are still needed. The match remains waiting; keep retained games open for recovery.",
    "unsupported": "This host version does not provide Championships or has disabled new battle challenges.",
    "uncertain": "The request's outcome is unknown. Refresh host status before choosing again; do not assume it was canceled or retry it.",
    "stale": "The displayed action or session changed. Refresh and review the bracket before choosing again.",
    "roster_changed": "The four connected Trainers changed. Refresh and review the pairings again.",
    "connection_lost": "Host connection unavailable. Displayed records are an earlier snapshot; retain any game waiting for recovery.",
    "busy": "A player or launcher operation is busy. Finish it, then refresh the bracket.",
    "cancel_pending": "Resolve the pending bracket cancellation votes before proposing another match.",
    "not_ready": "This character is busy saving, trading, battling or recovering. Return to ordinary play, then refresh.",
    "refused": "The host refused this choice. Refresh to read its current bracket before trying another action.",
    "unavailable": "Championship records are unavailable. Refresh when the host connection is ready.",
}


class ChampionshipPanel:
    """Tk-only public presentation; no network or session object on this thread."""

    def __init__(self, parent, worker):
        import tkinter as tk
        from tkinter import ttk
        self.worker = worker
        self._connected = self._eligible = self._pending = self._closed = self._suspended = False
        self._snapshot = None
        self._buttons = []
        self.frame = ttk.Frame(parent, padding=12)
        self.frame.pack(fill="both", expand=True)
        header = ttk.Frame(self.frame)
        header.pack(fill="x")
        ttk.Label(header, text="Four-Trainer Championship", font=("Segoe UI", 13, "bold")).pack(side="left")
        self.refresh_button = ttk.Button(header, text="Refresh", state="disabled", command=self.refresh)
        self.refresh_button.pack(side="right")
        self.message = tk.StringVar(value="Open your character, then refresh the host bracket.")
        ttk.Label(self.frame, textvariable=self.message, wraplength=555).pack(anchor="w", pady=(6, 8))
        wrapper = ttk.Frame(self.frame)
        wrapper.pack(fill="both", expand=True)
        canvas = tk.Canvas(wrapper, highlightthickness=0, height=260)
        bar = ttk.Scrollbar(wrapper, orient="vertical", command=canvas.yview)
        bar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=bar.set)
        content = ttk.Frame(canvas, padding=(0, 0, 6, 0))
        item = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(item, width=event.width))
        self.heading = tk.StringVar(value="No bracket snapshot")
        ttk.Label(content, textvariable=self.heading, font=("Segoe UI", 11, "bold"), wraplength=530).pack(anchor="w")
        self.participants = self._table(content, (("seed", "Pairing", 65), ("name", "Trainer", 220),
            ("accepted", "Accepted", 75), ("cancel", "Cancel vote", 90)), height=4)
        self.pairings = self._table(content, (("round", "Match", 85), ("first", "Trainer 1", 130),
            ("second", "Trainer 2", 130), ("state", "State", 95), ("winner", "Winner", 115)), height=3)
        self.match_detail = tk.StringVar(value="Select a match to read its participants and result.")
        ttk.Label(content, textvariable=self.match_detail, wraplength=530).pack(anchor="w", pady=(5, 6))
        self.pairings.bind("<<TreeviewSelect>>", self._select_match)
        self.actions = ttk.Frame(content)
        self.actions.pack(fill="x", pady=(4, 8))
        ttk.Label(content, text="Bracket choices do not enter a battle. Use Players → Challenges in the game for each match's normal Accept and Enter. Draws need a fresh mutual rematch; no fees, prizes or automatic forfeits.",
                  wraplength=530).pack(anchor="w", pady=(0, 10))
        ttk.Label(content, text="Your latest four completed or canceled brackets", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.history = self._table(content, (("number", "Record", 65), ("state", "Status", 100),
            ("winner", "Champion", 310)), height=4)
        self.history_detail = tk.StringVar(value="History is read only. Select a record to review its original pairings.")
        ttk.Label(content, textvariable=self.history_detail, wraplength=530).pack(anchor="w", pady=(5, 0))
        self.history.bind("<<TreeviewSelect>>", self._select_history)

    @staticmethod
    def _table(parent, columns, *, height):
        from tkinter import ttk
        table = ttk.Treeview(parent, columns=tuple(column[0] for column in columns), show="headings", height=height, selectmode="browse")
        for key, title, width in columns:
            table.heading(key, text=title)
            table.column(key, width=width, minwidth=40, stretch=True)
        table.pack(fill="x", pady=(5, 0))
        return table

    @staticmethod
    def _replace(table, rows):
        for child in table.get_children():
            table.delete(child)
        for index, row in enumerate(rows):
            table.insert("", "end", iid=str(index), values=row)

    @staticmethod
    def _name(view, player):
        return view["names"][view["players"].index(player)] if player is not None else "—"

    def _enable(self):
        available = self._connected and not self._pending and not self._closed and not self._suspended
        self.refresh_button.configure(state="normal" if available else "disabled")
        for button in self._buttons:
            button.configure(state="normal" if available and self._eligible else "disabled")

    def refresh(self):
        self._request()

    def _request(self, action_id=None):
        if self._closed or self._suspended or self._pending or not self._connected or self.worker is None:
            return
        snapshot_id = None if action_id is None or self._snapshot is None else self._snapshot["snapshot_id"]
        if self.worker.request_championship(snapshot_id, action_id):
            self._pending = True
            self._enable()
            self.message.set("Reading host bracket…" if action_id is None else "Sending your explicit choice… Keep the game and launcher open.")
        else:
            self.message.set("Finish the current launcher action, then refresh the Championship.")

    def _clear_actions(self):
        for button in self._buttons:
            button.destroy()
        self._buttons.clear()

    def _render(self, snapshot):
        from tkinter import ttk
        self._snapshot = snapshot
        current = snapshot["preview"] or snapshot["current"]
        preview = snapshot["preview"] is not None
        if current is None:
            self.heading.set(f"No current bracket — {len(snapshot['players'])}/4 Trainers connected")
            self._replace(self.participants, [])
            self._replace(self.pairings, [])
        else:
            state = "Preview — not submitted" if preview else current["state"].capitalize()
            champion = "" if preview or current["champion"] is None else " · Champion: " + self._name(current, current["champion"])
            self.heading.set(state + champion)
            self._replace(self.participants, [
                (f"SF{1 + index // 2}", name + (" (you)" if player == snapshot["player_id"] else ""),
                 "—" if preview else "Yes" if player in current["consent"] else "No",
                 "—" if preview else "Yes" if player in current["cancel_consent"] else "No")
                for index, (player, name) in enumerate(zip(current["players"], current["names"]))])
            self._replace(self.pairings, [] if preview else [
                (("Semifinal 1", "Semifinal 2", "Final")[match["round"]],
                 self._name(current, match["players"][0]) if match["players"] else "SF1 winner",
                 self._name(current, match["players"][1]) if match["players"] else "SF2 winner",
                 match["state"], self._name(current, match["winner"])) for match in current["matches"]])
        self.match_detail.set("Select a match for full Trainer names and its recorded attempt." if not preview else
                              "SF1 is the first two Trainers; SF2 is the last two. Their winners meet in the final.")
        self._replace(self.history, [(index + 1, record["state"].capitalize(), self._name(record, record["champion"]))
                                    for index, record in enumerate(snapshot["history"])])
        self.history_detail.set("Stored history snapshot. Refresh to include later completed brackets.")
        self._clear_actions()
        for index, action in enumerate(snapshot["actions"]):
            button = ttk.Button(self.actions, text=action["label"],
                                command=lambda token=action["action_id"]: self._request(token))
            button.grid(row=index, column=0, sticky="w", pady=2)
            self._buttons.append(button)
        message = _MESSAGES.get(snapshot["notice"], _MESSAGES["ready"])
        if not snapshot["mutable"]:
            message += " Bracket actions are unavailable during this character's current operation."
        self.message.set(message + " (" + datetime.now().strftime("%H:%M:%S") + ")")

    def _select_match(self, _event=None):
        selection = self.pairings.selection()
        current = None if self._snapshot is None else self._snapshot["current"]
        if not selection or current is None or self._snapshot["preview"] is not None:
            return
        match = current["matches"][int(selection[0])]
        names = " vs ".join(self._name(current, player) for player in match["players"]) or "Waiting for both semifinal winners"
        winner = "" if match["winner"] is None else " · Winner: " + self._name(current, match["winner"])
        self.match_detail.set(f"{names} · {match['state']} · Attempt {match['attempt']}{winner}")

    def _select_history(self, _event=None):
        selection = self.history.selection()
        if not selection or self._snapshot is None:
            return
        record = self._snapshot["history"][int(selection[0])]
        names = record["names"]
        self.history_detail.set(f"SF1: {names[0]} vs {names[1]}\nSF2: {names[2]} vs {names[3]}\n"
            + ("Champion: " + self._name(record, record["champion"]) if record["champion"] else "Canceled; no champion assigned."))

    def handle_event(self, event):
        if self._closed:
            return event.kind == "championship"
        if event.kind == "championship":
            self._pending = False
            snapshot = getattr(event, "championship_snapshot", None)
            if event.code == "ready" and self._connected and snapshot is not None:
                self._render(snapshot)
            else:
                self._clear_actions()
                self.message.set(_MESSAGES.get(event.code, _MESSAGES["unavailable"]) + " Any displayed bracket is an earlier snapshot.")
            self._enable()
            return True
        if event.kind in {"status", "complete"}:
            connected = event.kind == "status" and event.state == "running" and getattr(event, "connected", False)
            if self._connected and not connected:
                self._clear_actions()
                self.message.set(_MESSAGES["connection_lost"])
            self._connected = connected
            self._eligible = connected and getattr(event, "championship_available", False)
            self._enable()
        return False

    def close(self):
        self._closed = True
        self._clear_actions()
        self._enable()

    def set_closing(self, closing):
        self._suspended = bool(closing)
        self._enable()
