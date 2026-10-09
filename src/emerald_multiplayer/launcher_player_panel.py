"""Explicit player records and team choices on the existing session loop."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from .companion import BattleChallengeError, TeamError
from .player_card import read_player_card, validate_player_card
from .record_views import battle_outcome, battle_rows, hunt_rows, hunt_totals, hunt_detail


class PlayerSnapshotError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


async def read_player_snapshot(session, target=None, *, allow_unsupported=False):
    """Use the live authenticated connection; never open a character/database."""
    companion = session.companion

    def binding():
        if companion is None or not companion.connected:
            return None
        return (companion.world_id, companion.server_epoch, companion.session_epoch)

    original = binding()
    if original is None:
        raise PlayerSnapshotError("connection_lost")
    actor = companion.config.player_id
    target = actor if target is None else target
    try:
        card, history, card_notice, history_available = None, [], "", False
        try:
            reply = await read_player_card(companion, target)
            card = validate_player_card(reply["player_card"], actor, target)
            # The history extension always belongs to the authenticated viewer,
            # even when the requested card belongs to a connected peer.
            history = reply["result"]
            history_available = True
        except BattleChallengeError as error:
            if not allow_unsupported or error.code not in {
                    "invalid_fields", "invalid_field", "player_card_unsupported", "battle_disabled", "player_offline"}:
                raise
            card_notice = "peer_offline" if error.code == "player_offline" else "unsupported"
        try:
            team = (await companion.team_rpc("status"))["result"]
        except TeamError as error:
            if error.code != "team_disabled":
                raise
            team = None
        if binding() != original or session.companion is not companion:
            raise PlayerSnapshotError("connection_lost")
        players = [dict(player_id=p["player_id"], display_name=p["display_name"],
                        in_world=p["presence"] is not None, you=p["player_id"] == actor)
                   for p in companion._players]
        if target != actor and not any(p["player_id"] == target for p in players):
            card, card_notice = None, "peer_offline"
        return deepcopy(dict(card=card, players=players, team=team, history=history,
                             actor_id=actor, target_id=target, card_notice=card_notice,
                             history_available=history_available))
    except BattleChallengeError as error:
        code = ("unsupported" if error.code in {
            "invalid_fields", "invalid_field", "player_card_unsupported", "battle_disabled"}
            else "peer_offline" if error.code == "player_offline" else "unavailable")
        raise PlayerSnapshotError(code) from error
    except (ConnectionError, OSError) as error:
        raise PlayerSnapshotError("connection_lost") from error


@dataclass(frozen=True)
class _PlayerAction:
    operation: str
    parameters: tuple


class PlayerPanelController:
    """Retain displayed choices off Tk, on one original LauncherSession."""

    def __init__(self, session):
        self.session = session
        self._binding = self._snapshot_id = self._target = self._snapshot = None
        self._actions = {}
        self._busy = False

    def _identity(self):
        s, c = self.session, self.session.companion
        if (c is None or not c.connected or not s._open or s._closing
                or s._game is None or s._game.process.returncode is not None
                or s._signature() != s._binding):
            raise PlayerSnapshotError("connection_lost")
        return (c, s._signature(), s._game, c._bridge, getattr(c._bridge, "incarnation", None))

    def _invalidate(self):
        self._snapshot_id = None
        self._actions.clear()

    @staticmethod
    def _team_key(status):
        if status is None:
            return None
        # Expiry seconds are informational and decrease between reads.
        return (deepcopy(status["team"]), deepcopy(status["teams"]),
                [{key: value for key, value in invitation.items() if key != "expires_in"}
                 for invitation in status["invitations"]])

    async def _read(self, notice="ready"):
        snapshot = await read_player_snapshot(self.session, self._target, allow_unsupported=True)
        if self._identity() != self._binding:
            raise PlayerSnapshotError("connection_lost")
        self._snapshot = snapshot
        self._invalidate()
        self._snapshot_id = str(uuid4())
        actions, peers = [], []
        actor = snapshot["actor_id"]
        mutable = self.session.can_manage_players

        def add(operation, parameters):
            token = str(uuid4())
            self._actions[token] = _PlayerAction(operation, tuple(parameters))
            return token

        team = snapshot["team"]
        members = {p for entry in team["teams"] for p in entry["members"]} if team else set()
        for player in snapshot["players"]:
            target = player["player_id"]
            invite = None
            if (mutable and team is not None and not team["invitations"]
                    and actor not in members and target not in members and target != actor):
                invite = add("invite", (target, player["display_name"], str(uuid4())))
            peers.append(dict(player_id=target,
                card_action=add("card", (target, player["display_name"])), invite_action=invite))
        if mutable and team is not None:
            if team["team"] is not None:
                own = team["team"]
                actions.append(dict(label="Leave your current team", action_id=add("leave", (own["team_id"], own["generation"]))))
            elif team["invitations"]:
                invitation = team["invitations"][0]
                params = invitation["invitation_id"], invitation["generation"]
                operations = (("Accept invitation", "accept"), ("Decline invitation", "decline")) if invitation["recipient"] == actor else (("Cancel your invitation", "cancel"),)
                actions.extend(dict(label=label, action_id=add(operation, params)) for label, operation in operations)
        return deepcopy(dict(snapshot, snapshot_id=self._snapshot_id, peer_actions=peers,
            own_card_action=add("card", (actor, None)), team_actions=actions,
            mutable=mutable, notice=notice))

    async def dispatch(self, snapshot_id=None, action_id=None):
        if self._busy:
            raise PlayerSnapshotError("busy")
        self._busy = True
        try:
            original = self._identity()
            if snapshot_id is None and action_id is None:
                self._invalidate()
                if original != self._binding:
                    self._target = self.session.companion.config.player_id
                self._binding = original
                return await self._read()
            action = self._actions.get(action_id) if type(action_id) is str else None
            if (type(snapshot_id) is not str or snapshot_id != self._snapshot_id
                    or original != self._binding or action is None):
                raise PlayerSnapshotError("stale")
            self._invalidate()  # Consume every action before the first await.
            operation, parameters = action.operation, action.parameters
            if operation in {"card", "invite"}:
                roster = {p["player_id"]: p["display_name"] for p in self.session.companion._players}
                if parameters[0] not in roster or (parameters[1] is not None and roster[parameters[0]] != parameters[1]):
                    raise PlayerSnapshotError("peer_offline")
            if operation == "card":
                self._target = parameters[0]
                return await self._read()
            if not self.session.can_manage_players:
                raise PlayerSnapshotError("not_ready")
            c = self.session.companion
            current = (await c.team_rpc("status"))["result"]
            if self._identity() != original:
                raise PlayerSnapshotError("connection_lost")
            if self._team_key(current) != self._team_key(self._snapshot["team"]):
                raise PlayerSnapshotError("stale")
            if not self.session.can_manage_players:
                raise PlayerSnapshotError("not_ready")
            if operation == "invite":
                fields = dict(peer=parameters[0], invitation_id=parameters[2])
            elif operation == "leave":
                fields = dict(team_id=parameters[0], generation=parameters[1])
            else:
                fields = dict(invitation_id=parameters[0], generation=parameters[1])
            try:
                result = (await c.team_rpc(operation, **fields))["result"]
                try:
                    same = self._identity() == original
                except PlayerSnapshotError:
                    same = False
                if not same:
                    raise PlayerSnapshotError("uncertain")
            except TeamError:
                raise
            except (ConnectionError, OSError, asyncio.TimeoutError) as error:
                raise PlayerSnapshotError("uncertain") from error
            notice = {"invited": "invited", "formed": "formed", "left": "left",
                      "declined": "declined", "canceled": "invite_canceled"}[result["state"]]
            try:
                return await self._read(notice)
            except Exception as error:
                # The reply was verified, but no fresh combined snapshot exists.
                # Do not leave the previous invitation/team buttons reusable.
                raise PlayerSnapshotError("applied_refresh_required") from error
        except TeamError as error:
            self._invalidate()
            code = {"team_disabled": "teams_unsupported", "player_offline": "peer_offline",
                "team_invite_busy": "busy", "team_already_member": "stale",
                "team_generation_mismatch": "stale", "team_invitation_missing": "stale",
                "team_not_member": "stale", "stale_lease": "connection_lost"}.get(error.code, "refused")
            raise PlayerSnapshotError(code) from error
        except BaseException:
            self._invalidate()
            raise
        finally:
            self._busy = False


_MESSAGES = {
    "ready": "Host records refreshed. Refresh again for later player or team changes.",
    "unsupported": "This host version does not provide Trainer Cards. Available team controls still use the host's current status.",
    "teams_unsupported": "This host has disabled team invitations.",
    "peer_offline": "That Trainer disconnected or changed identity. Refresh the player list before choosing again.",
    "connection_lost": "Host connection unavailable. Any displayed records are an earlier snapshot.",
    "stale": "The displayed player, invitation or team changed. Refresh and review before choosing again.",
    "busy": "A player or launcher operation is busy. Finish it, then refresh.",
    "not_ready": "Team changes are unavailable while this character is saving, trading, battling or recovering.",
    "uncertain": "The choice's outcome is unknown. Refresh host status; do not assume it failed or send it again.",
    "applied_refresh_required": "The host acknowledged your team choice, but the new snapshot was unavailable. Refresh before another choice.",
    "refused": "The host refused this team choice. Refresh its current status before choosing again.",
    "unavailable": "Records are unavailable. Refresh when the host connection is ready.",
    "invited": "Your invitation was sent. The other Trainer must explicitly accept it.",
    "formed": "The host confirmed your two-Trainer team. Parties, money, items and progress remain separate.",
    "left": "The host confirmed that you left the team.",
    "declined": "The host confirmed that you declined the invitation.",
    "invite_canceled": "The host confirmed that you canceled your invitation.",
}


class PlayerPanel:
    """All Tk work stays on its owning thread; refresh is explicit and bounded."""

    def __init__(self, parent, worker, *, preferences=None):
        import tkinter as tk
        from tkinter import ttk
        self.worker = worker
        from .launcher_display import DisplayPreferences
        self.preferences = preferences if preferences is not None else DisplayPreferences()
        self._connected = self._pending = self._closed = self._eligible = self._suspended = False
        self._has_snapshot = False
        self._snapshot = None
        self._team_buttons = []
        self._history_records, self._shown_history = [], ()
        self._history_actor = None
        self._history_roster = {}
        self._history_available = False
        self._hunt_records = None
        self._shown_hunts = ()
        self.frame = ttk.Frame(parent, padding=16)
        self.frame.pack(fill="both", expand=True)
        header = ttk.Frame(self.frame)
        header.pack(fill="x")
        self.title = tk.StringVar(value="Your multiplayer Trainer Card")
        ttk.Label(header, textvariable=self.title, font=("Segoe UI", 13, "bold")).pack(side="left")
        self.refresh_button = ttk.Button(header, text="Refresh", command=self.refresh, state="disabled")
        self.refresh_button.pack(side="right")
        self.own_button = ttk.Button(header, text="My card", command=self.show_own, state="disabled")
        self.own_button.pack(side="right", padx=6)
        self.message = tk.StringVar(value="Open your character, then refresh to read its host records.")
        ttk.Label(self.frame, textvariable=self.message, wraplength=545).pack(anchor="w", pady=(6, 10))
        tabs = ttk.Notebook(self.frame)
        self.tabs = tabs
        tabs.pack(fill="both", expand=True)
        pages = {}
        self.pages = {}
        for key, title in (("records", "Card"), ("shared", "Shared"), ("hunts", "My hunts"), ("players", "Players & team"), ("history", "My battles")):
            container = ttk.Frame(tabs)
            tabs.add(container, text=title)
            self.pages[key] = container
            canvas = tk.Canvas(container, highlightthickness=0, height=240)
            bar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
            bar.pack(side="right", fill="y")
            canvas.pack(side="left", fill="both", expand=True)
            canvas.configure(yscrollcommand=bar.set)
            page = ttk.Frame(canvas, padding=8)
            item = canvas.create_window((0, 0), window=page, anchor="nw")
            page.bind("<Configure>", lambda _, c=canvas: c.configure(scrollregion=c.bbox("all")))
            canvas.bind("<Configure>", lambda event, c=canvas, i=item: c.itemconfigure(i, width=event.width))
            pages[key] = page
        self.records = self._table(pages["records"], (
            ("format", "Format", 76), ("played", "Played", 58), ("wins", "Wins", 55),
            ("losses", "Losses", 55), ("draws", "Draws", 55)), height=3)
        self.streak = tk.StringVar(value="")
        self.details = tk.StringVar(value="")
        self.championships = tk.StringVar(value="")
        ttk.Label(pages["records"], textvariable=self.streak, wraplength=515).pack(anchor="w", pady=(8, 4))
        ttk.Label(pages["records"], textvariable=self.details, wraplength=515).pack(anchor="w")
        ttk.Label(pages["records"], textvariable=self.championships, wraplength=515).pack(anchor="w", pady=(6, 0))
        ttk.Label(pages["records"], text="Counts cover this world's recorded multiplayer activity.\n"
            "An interrupted battle has no result until every participant finishes recovery.",
            wraplength=515).pack(anchor="w", pady=(10, 0))
        hunt_filters = ttk.Frame(pages["hunts"])
        hunt_filters.pack(fill="x", pady=(0, 6))
        self.hunt_show = tk.StringVar(value=self.preferences.value["hunt_show"])
        self.hunt_order = tk.StringVar(value=self.preferences.value["hunt_order"])
        for variable, values in ((self.hunt_show, ("All sources", "Started", "No attempts yet")),
                                 (self.hunt_order, ("Source order", "Most attempts", "Name"))):
            choice = ttk.Combobox(hunt_filters, textvariable=variable, values=values, state="readonly", width=17)
            choice.pack(side="left", padx=(0, 8))
            choice.bind("<<ComboboxSelected>>", self._render_hunts)
        search = ttk.Frame(pages["hunts"])
        search.pack(fill="x", pady=(0, 6))
        ttk.Label(search, text="Source name").pack(side="left", padx=(0, 6))
        self.hunt_query = tk.StringVar()
        entry = ttk.Entry(search, textvariable=self.hunt_query, width=26, validate="key",
                          validatecommand=(self.frame.register(lambda value: len(value) <= 100), "%P"))
        entry.pack(side="left")
        entry.bind("<Return>", self._render_hunts)
        ttk.Button(search, text="Search", command=self._render_hunts).pack(side="left", padx=6)
        favorites = ttk.Frame(pages["hunts"])
        favorites.pack(fill="x", pady=(0, 6))
        self.favorites_only = tk.BooleanVar(value=self.preferences.value["favorites_only"])
        ttk.Checkbutton(favorites, text="Favorites only", variable=self.favorites_only,
                        command=self._render_hunts).pack(side="left")
        self.favorite_button = ttk.Button(favorites, text="Favorite selected source", command=self.toggle_favorite, state="disabled")
        self.favorite_button.pack(side="left", padx=8)
        self.display_notice = tk.StringVar(value="Favorites and filters are local display preferences; they do not change the game.")
        ttk.Label(pages["hunts"], textvariable=self.display_notice, wraplength=515).pack(anchor="w", pady=(0, 6))
        self.hunt_summary = tk.StringVar(value="No personal hunt snapshot")
        ttk.Label(pages["hunts"], textvariable=self.hunt_summary, wraplength=515).pack(anchor="w", pady=(0, 6))
        self.hunts = self._table(pages["hunts"], (
            ("source", "Personal encounter", 340), ("attempts", "Attempts", 90)), height=7, scroll=True)
        self.hunts.bind("<<TreeviewSelect>>", self._select_hunt)
        self.hunt_detail = tk.StringVar(value="Select a source for its counting scope and limitations.")
        ttk.Label(pages["hunts"], textvariable=self.hunt_detail, wraplength=515).pack(anchor="w", pady=(8, 0))
        self.hunt_note = tk.StringVar(value="Host hunt records have not been read.")
        ttk.Label(pages["hunts"], textvariable=self.hunt_note, wraplength=515).pack(anchor="w", pady=(8, 0))
        self.players = self._table(pages["players"], (
            ("trainer", "Trainer", 180), ("state", "Connection", 125), ("team", "Team", 190)), height=4)
        self.players.bind("<<TreeviewSelect>>", self._select_player)
        self.selected_player = tk.StringVar(value="Select a connected Trainer.")
        ttk.Label(pages["players"], textvariable=self.selected_player, wraplength=515).pack(anchor="w", pady=(6, 4))
        peer_actions = ttk.Frame(pages["players"])
        peer_actions.pack(fill="x")
        self.card_button = ttk.Button(peer_actions, text="View selected Trainer Card", state="disabled", command=self.show_selected)
        self.card_button.pack(side="left")
        self.invite_button = ttk.Button(peer_actions, text="Invite selected Trainer", state="disabled", command=self.invite_selected)
        self.invite_button.pack(side="left", padx=8)
        self.team_note = tk.StringVar(value="Refresh to read your team and invitations.")
        ttk.Label(pages["players"], textvariable=self.team_note, wraplength=515).pack(anchor="w", pady=(10, 4))
        self.team_actions = ttk.Frame(pages["players"])
        self.team_actions.pack(fill="x")
        ttk.Label(pages["players"], text="Teams are session-local: disconnecting either Trainer or restarting the host dissolves them. Leave before changing partners. Team membership does not share parties, items, money or progression. Use Players in the game for trades and battle consent/Enter.",
            wraplength=515).pack(anchor="w", pady=(10, 0))
        self.shared_title = tk.StringVar(value="Choose a peer's Trainer Card to read your shared records.")
        ttk.Label(pages["shared"], textvariable=self.shared_title, wraplength=515).pack(anchor="w", pady=(0, 8))
        self.shared = self._table(pages["shared"], (("role", "Together as", 150), ("played", "Played", 65),
            ("wins", "Your wins", 75), ("losses", "Your losses", 80), ("draws", "Draws", 65)), height=2)
        self.shared_trades = tk.StringVar(value="")
        ttk.Label(pages["shared"], textvariable=self.shared_trades, wraplength=515).pack(anchor="w", pady=(8, 0))
        ttk.Label(pages["shared"], text="Shared records cover only you and this connected Trainer. These are recorded battle/trade counts, not friendship progress, Lucky eligibility or rewards.",
            wraplength=515).pack(anchor="w", pady=(10, 0))
        history_filters = ttk.Frame(pages["history"])
        history_filters.pack(fill="x", pady=(0, 6))
        self.history_mode = tk.StringVar(value=self.preferences.value["history_mode"])
        self.history_outcome = tk.StringVar(value=self.preferences.value["history_outcome"])
        for title, variable, values in (("Format", self.history_mode, ("All formats", "1v1", "2v2")),
                                       ("Your result", self.history_outcome, ("All outcomes", "Win", "Loss", "Draw"))):
            ttk.Label(history_filters, text=title).pack(side="left", padx=(0, 4))
            choice = ttk.Combobox(history_filters, textvariable=variable, values=values, state="readonly", width=13)
            choice.pack(side="left", padx=(0, 8))
            choice.bind("<<ComboboxSelected>>", self._render_history)
        self.history = self._table(pages["history"], (
            ("record", "Record", 65), ("format", "Format", 65), ("result", "Result", 75),
            ("opponents", "Opponents", 240)), height=7, scroll=True)
        self.history.bind("<<TreeviewSelect>>", self._select_history)
        self.history_note = tk.StringVar(value="Refresh to read your latest completed battles.")
        ttk.Label(pages["history"], textvariable=self.history_note, wraplength=515).pack(anchor="w", pady=(8, 0))
        self.history_detail = tk.StringVar(value="Select a result for both sides and the original party counts.")
        ttk.Label(pages["history"], textvariable=self.history_detail, wraplength=515).pack(anchor="w", pady=(8, 0))
        ttk.Label(pages["history"], text="Filters apply to your latest eight released results, even while viewing a peer's card. Lifetime counters include older records; an empty filter does not mean you have never played that format.",
            wraplength=515).pack(anchor="w", pady=(8, 0))

    @staticmethod
    def _table(parent, columns, *, height, scroll=False):
        from tkinter import ttk
        wrapper = ttk.Frame(parent)
        wrapper.pack(fill="both", expand=scroll)
        table = ttk.Treeview(wrapper, columns=tuple(c[0] for c in columns), show="headings", height=height, selectmode="browse")
        for key, heading, width in columns:
            table.heading(key, text=heading)
            table.column(key, width=width, minwidth=40, stretch=True)
        table.pack(side="left", fill="both", expand=True)
        if scroll:
            bar = ttk.Scrollbar(wrapper, orient="vertical", command=table.yview)
            bar.pack(side="right", fill="y")
            table.configure(yscrollcommand=bar.set)
        return table

    @staticmethod
    def _replace(table, rows):
        for child in table.get_children():
            table.delete(child)
        for index, row in enumerate(rows):
            table.insert("", "end", iid=str(index), values=row)

    def refresh(self):
        self._request()

    def _request(self, action_id=None):
        if self._closed or self._suspended or self._pending or not self._connected or self.worker is None:
            return
        snapshot_id = None if action_id is None or self._snapshot is None else self._snapshot["snapshot_id"]
        if self.worker.request_player_snapshot(snapshot_id, action_id):
            self._pending = True
            self._enable()
            self.message.set("Reading host records and team status…" if action_id is None else "Sending your explicit choice…")
        else:
            self.message.set("Finish the current launcher action, then refresh your records.")

    def _selected_action(self):
        selection = self.players.selection()
        if self._snapshot is None or not selection:
            return None
        index = int(selection[0])
        return self._snapshot["peer_actions"][index]

    def _select_player(self, _event=None):
        selected = self._selected_action()
        if selected is not None:
            player = next(p for p in self._snapshot["players"] if p["player_id"] == selected["player_id"])
            self.selected_player.set(player["display_name"] + (" (you)" if player["you"] else ""))
        self._enable()

    def show_selected(self):
        selected = self._selected_action()
        if selected is not None:
            self._request(selected["card_action"])
            self.tabs.select(self.pages["records"])

    def invite_selected(self):
        selected = self._selected_action()
        if selected is not None and selected["invite_action"] is not None and self._eligible:
            self._request(selected["invite_action"])

    def show_own(self):
        if self._snapshot is not None:
            self._request(self._snapshot["own_card_action"])
            self.tabs.select(self.pages["records"])

    def _clear_actions(self):
        for button in self._team_buttons:
            button.destroy()
        self._team_buttons.clear()
        # Keep the displayed records, but retire every token on failure/loss.
        self._snapshot = None

    def _enable(self):
        available = self._connected and not self._pending and not self._closed and not self._suspended
        self.refresh_button.configure(state="normal" if available else "disabled")
        self.own_button.configure(state="normal" if available and self._snapshot is not None else "disabled")
        selected = self._selected_action()
        self.card_button.configure(state="normal" if available and selected is not None else "disabled")
        self.invite_button.configure(state="normal" if available and self._eligible and selected is not None
            and selected["invite_action"] is not None else "disabled")
        for button in self._team_buttons:
            button.configure(state="normal" if available and self._eligible else "disabled")

    def _render_history(self, _event=None):
        if _event is not None:
            self._save_display(history_mode=self.history_mode.get(), history_outcome=self.history_outcome.get())
        self._shown_history = (() if self._history_actor is None else battle_rows(
            self._history_records, self._history_actor,
            mode={"All formats": "all", "1v1": "singles", "2v2": "doubles"}[self.history_mode.get()],
            outcome={"All outcomes": "all", "Win": "win", "Loss": "loss", "Draw": "draw"}[self.history_outcome.get()]))
        recent = []
        for result in self._shown_history:
            slot = result["players"].index(self._history_actor)
            opponents = [self._history_roster.get(p, f"Offline Trainer {i + 1}")
                         for i, p in enumerate(result["players"]) if i % 2 != slot % 2]
            recent.append((result["sequence"], "1v1" if result["mode"] == 2 else "2v2",
                           battle_outcome(result, self._history_actor).capitalize(), ", ".join(opponents)))
        self._replace(self.history, recent)
        self.history_note.set(f"Showing {len(recent)} of {len(self._history_records)} recent recorded results. Displayed snapshot only."
            if self._history_available else "Your recent results were unavailable in this response. Choose My card and refresh.")
        self.history_detail.set("Select a result for both sides and the original party counts." if recent else
                                "No result in the current snapshot matches these filters.")

    def _select_history(self, _event=None):
        selection = self.history.selection()
        if not selection:
            return
        result = self._shown_history[int(selection[0])]
        actor_slot = result["players"].index(self._history_actor)
        parties = {checkpoint["player_id"]: checkpoint["party_count"] for checkpoint in result["checkpoints"]}
        own, opposing = [], []
        for index, player in enumerate(result["players"]):
            name = self._history_roster.get(player, f"Offline Trainer {index + 1}")
            label = name + (" (you)" if player == self._history_actor else "") + f" — {parties[player]} Pokémon"
            (own if index % 2 == actor_slot % 2 else opposing).append(label)
        self.history_detail.set(f"Record #{result['sequence']} · {'1v1' if result['mode'] == 2 else '2v2'} · Your result: {battle_outcome(result, self._history_actor).capitalize()}\n"
            + "Your side: " + "; ".join(own) + "\nOpposing side: " + "; ".join(opposing)
            + "\nParty counts are from the accepted battle checkpoints. Names use the current roster; offline names were not archived. This result does not grant replay, rewards or recovery authority.")

    def _render_hunts(self, _event=None):
        self._save_display(hunt_show=self.hunt_show.get(), hunt_order=self.hunt_order.get(),
                           favorites_only=self.favorites_only.get())
        if self._hunt_records is None:
            self._shown_hunts = ()
            self.hunt_summary.set("No personal hunt snapshot. Choose My card and refresh.")
        else:
            self._shown_hunts = hunt_rows(self._hunt_records,
                show={"All sources": "all", "Started": "started", "No attempts yet": "unstarted"}[self.hunt_show.get()],
                order={"Source order": "source", "Most attempts": "attempts", "Name": "name"}[self.hunt_order.get()],
                query=self.hunt_query.get())
            if self.favorites_only.get():
                self._shown_hunts = tuple(row for row in self._shown_hunts
                    if row["encounter_id"] in self.preferences.value["favorite_hunts"])
            totals = hunt_totals(self._hunt_records)
            self.hunt_summary.set(f"{totals['attempts']} admitted attempts across {totals['started']} sources with attempts. "
                + f"Showing {len(self._shown_hunts)} of {totals['sources']} catalogue entries.")
        self._replace(self.hunts, [(row["name"] + (" [favorite]" if row["encounter_id"]
            in self.preferences.value["favorite_hunts"] else ""), row["attempts"]) for row in self._shown_hunts])
        self.favorite_button.configure(state="disabled")
        self.hunt_detail.set("Select a source for its counting scope and limitations." if self._shown_hunts else
                            "No source in this snapshot matches the selected filters.")

    def _select_hunt(self, _event=None):
        selection = self.hunts.selection()
        if not selection or self._hunt_records is None:
            return
        row = self._shown_hunts[int(selection[0])]
        self.favorite_button.configure(state="normal" if not self._closed else "disabled",
            text="Remove favorite" if row["encounter_id"] in self.preferences.value["favorite_hunts"] else "Favorite selected source")
        detail = hunt_detail(self._hunt_records, row["encounter_id"])
        self.hunt_detail.set(f"{detail['name']}\n{detail['counting']}: {detail['attempts']}\n{detail['scope']}\n"
            + "\n".join(detail[key] for key in ("odds", "availability", "outcome")))

    def _save_display(self, **changes):
        if all(self.preferences.value[key] == value for key, value in changes.items()):
            return
        saved = self.preferences.update(**changes)
        self.display_notice.set("Local display preferences saved." if saved else
            "Display choices apply to this window; the existing preference file was retained because it could not be saved or read.")

    def toggle_favorite(self):
        selection = self.hunts.selection()
        if not selection or self._closed:
            return
        source = self._shown_hunts[int(selection[0])]["encounter_id"]
        favorites = set(self.preferences.value["favorite_hunts"])
        favorites.symmetric_difference_update({source})
        self._save_display(favorite_hunts=sorted(favorites))
        self._render_hunts()

    def _render(self, snapshot):
        from tkinter import ttk
        self._clear_actions()
        self._snapshot = snapshot
        card = snapshot["card"]
        actor, target = snapshot["actor_id"], snapshot["target_id"]
        if card is not None:
            validate_player_card(card, actor, target)
        self.title.set("Trainer Card unavailable" if card is None else card["display_name"] + " — Trainer Card")
        self._replace(self.records, [
            (label, *(card["battles"][key][k] for k in ("played", "wins", "losses", "draws")))
            for key, label in (() if card is None else (("total", "All PvP"), ("singles", "1v1"), ("doubles", "2v2")))])
        total = card["battles"]["total"] if card is not None else None
        self.streak.set("" if total is None else f"Current win streak: {total['streak']}    Best: {total['best_streak']}")
        personal = card["personal"] if card is not None else None
        if personal is None:
            self.details.set("Saved party, inventory, trade recovery and hunt progress are private to each Trainer. Choose My card for your own saved progress.")
        else:
            trades, saved = personal["trades"], personal["checkpoint"]
            trade_text = ("Trade records unavailable" if trades is None else
                f"Committed trades: {trades['committed']}    Awaiting your recovery: {trades['pending']}")
            saved_text = ("No canonical save yet" if saved is None else
                f"Host save #{saved['revision']}: party {saved['party_count']}/6, PC {saved['stored_count']}/420")
            self.details.set(trade_text + "\n" + saved_text + "\nSaved counts exclude unsaved live changes.")
        championship = card.get("championships") if card is not None else None
        self.championships.set("Championship records unavailable on this host." if championship is None else
            f"Championships entered: {championship['entries']}    Completed: {championship['completed']}    Won: {championship['wins']}\n"
            "An entry requires all four players' bracket consent; canceled brackets never award a win.")
        shared = card.get("shared") if card is not None else None
        self.shared_title.set("Choose a peer's card for records shared with you." if target == actor else
            "This host cannot provide shared records for that Trainer." if shared is None else
            "Your recorded activity with " + card["display_name"])
        self._replace(self.shared, [] if shared is None else [
            (label, *(shared["battles"][key][k] for k in ("played", "wins", "losses", "draws")))
            for key, label in (("together", "Teammates"), ("against", "Opponents"))])
        self.shared_trades.set("" if shared is None else "Shared trade records unavailable." if shared["trades"] is None else
                               f"Committed trades between you: {shared['trades']}")
        hunts = personal["hunts"] if personal is not None else None
        self._hunt_records = hunts
        self._render_hunts()
        self.hunt_note.set("Choose My card to read your own personal hunt counters." if personal is None else
            "Durable personal hunts are not enabled for this world." if hunts is None else
            "Admitted attempts only. Counters do not change shiny odds. Catalogue entries do not prove a source is enabled in this game build.")
        roster = {p["player_id"]: p["display_name"] for p in snapshot["players"]}
        teammates = {}
        if snapshot["team"] is not None:
            for team in snapshot["team"]["teams"]:
                first, second = team["members"]
                teammates[first] = roster.get(second, "Disconnected trainer")
                teammates[second] = roster.get(first, "Disconnected trainer")
        self._replace(self.players, [
            (p["display_name"] + (" (you)" if p["you"] else ""),
             "In world" if p["in_world"] else "Connected", teammates.get(p["player_id"], "No teammate"))
            for p in snapshot["players"]])
        self.selected_player.set("Select a connected Trainer.")
        team = snapshot["team"]
        if team is None:
            self.team_note.set("Team controls are disabled on this host.")
        elif team["team"] is not None:
            peer = next(p for p in team["team"]["members"] if p != actor)
            self.team_note.set("Your teammate: " + roster.get(peer, "Disconnected Trainer"))
        elif team["invitations"]:
            invitation = team["invitations"][0]
            received = invitation["recipient"] == actor
            peer = invitation["sender"] if received else invitation["recipient"]
            self.team_note.set(("Invitation from " if received else "Invitation sent to ") + roster.get(peer, "Disconnected Trainer")
                + f". About {int(invitation['expires_in'])} seconds remained at this snapshot; refresh for current status.")
        else:
            self.team_note.set("You have no team or pending invitation. Select a free Trainer to invite.")
        for index, action in enumerate(snapshot["team_actions"]):
            button = ttk.Button(self.team_actions, text=action["label"], command=lambda token=action["action_id"]: self._request(token))
            button.grid(row=index, column=0, sticky="w", pady=2)
            self._team_buttons.append(button)
        self._history_records = list(snapshot.get("history", ()))
        self._history_actor, self._history_roster = actor, roster
        self._history_available = snapshot["history_available"]
        self._render_history()
        self._has_snapshot = True
        notice = _MESSAGES.get(snapshot["notice"], _MESSAGES["ready"])
        if snapshot["card_notice"]:
            notice += " " + _MESSAGES[snapshot["card_notice"]]
        self.message.set(notice + " (" + datetime.now().strftime("%H:%M:%S") + ")")

    def handle_event(self, event):
        if self._closed:
            return event.kind == "player_snapshot"
        if event.kind == "player_snapshot":
            self._pending = False
            if event.code == "ready" and self._connected and event.player_snapshot is not None:
                self._render(event.player_snapshot)
            else:
                self._clear_actions()
                self.message.set(_MESSAGES.get(event.code, _MESSAGES["unavailable"]) + " Any displayed records are an earlier snapshot.")
            self._enable()
            return True
        if event.kind in ("status", "complete"):
            connected = event.kind == "status" and event.state == "running" and getattr(event, "connected", False)
            if self._connected and not connected:
                self._clear_actions()
                self.message.set("Connection closed. Displayed records are an earlier snapshot." if self._has_snapshot
                                 else "Open your character, then refresh to read its host records.")
            self._connected = connected
            self._eligible = connected and getattr(event, "player_actions_available", False)
            self._enable()
        return False

    def close(self):
        self._closed = True
        self._clear_actions()
        self._enable()

    def set_closing(self, closing):
        self._suspended = bool(closing)
        self._enable()
