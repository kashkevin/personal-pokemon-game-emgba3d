"""Explicit, bounded host-record browsing; records grant no gameplay authority."""
from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from .battle_archive import default_battle_archive_request, read_battle_archive
from .record_views import battle_outcome
from .reset_protocol import SOURCES
from .trade_archive import default_trade_archive_request, fetch_trade_archive


class RecordArchiveError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class RecordArchiveController:
    def __init__(self, session):
        self.session = session
        self._views = {}
        self._busy = False

    def _identity(self):
        s, c = self.session, self.session.companion
        if (c is None or not c.connected or not s._open or s._closing
                or s._game is None or s._game.process.returncode is not None or s._signature() != s._binding):
            raise RecordArchiveError("connection_lost")
        return (c, s._signature(), s._game)

    async def dispatch(self, kind, filters=None, snapshot_id=None, action_id=None):
        if kind not in {"battle", "hunt", "trade"} or self._busy:
            raise RecordArchiveError("unavailable")
        self._busy = True
        try:
            original = self._identity()
            view = self._views.get(kind)
            if snapshot_id is None and action_id is None:
                if kind in {"battle", "trade"}:
                    expected = {"mode", "outcome", "peer", "relation", "record"} if kind == "battle" else {"peer", "serial", "record"}
                    if type(filters) is not dict or set(filters) != expected:
                        raise RecordArchiveError("invalid_filter")
                    request = (default_battle_archive_request if kind == "battle" else default_trade_archive_request)(**filters)
                    actor = self.session.companion.config.player_id
                    allowed = {p["player_id"] for p in self.session.companion._players if p["player_id"] != actor}
                    if view is not None and view["binding"] == original:
                        if kind == "battle":
                            allowed.update(p for row in view["reply"]["rows"] for p in row["players"] if p != actor)
                        else:
                            allowed.update(row["peer"] for row in view["reply"]["rows"])
                        if view["request"]["peer"] is not None:
                            allowed.add(view["request"]["peer"])
                    if request["peer"] is not None and request["peer"] not in allowed:
                        raise RecordArchiveError("invalid_filter")
                else:
                    from .reset_history import default_reset_history_request
                    if (type(filters) is not dict or set(filters) != {"encounter_id"}
                            or type(filters["encounter_id"]) is not int or filters["encounter_id"] not in SOURCES):
                        raise RecordArchiveError("invalid_filter")
                    request = default_reset_history_request(filters["encounter_id"], limit=10)
                stack = []
            else:
                if (filters is not None or view is None or view["binding"] != original
                        or snapshot_id != view["snapshot_id"] or action_id not in view["actions"]):
                    raise RecordArchiveError("stale")
                direction = view["actions"][action_id]
                view["actions"] = {}  # A queued double click cannot reuse a cursor.
                request, stack = deepcopy(view["request"]), deepcopy(view["stack"])
                if direction == "older":
                    stack.append(deepcopy(request))
                    request["before_attempt" if kind == "hunt" else "before"] = view["reply"]["next_before"]
                elif direction == "newer":
                    request = stack.pop()
                else:
                    raise RecordArchiveError("stale")
            # Invalidate prior navigation before an await, including a new search.
            if view is not None:
                view["actions"] = {}
            c = self.session.companion
            if kind == "battle":
                reply = await read_battle_archive(c, request)
                request["through"] = reply["through"]
            elif kind == "trade":
                reply = await fetch_trade_archive(c, request)
                request["through"] = reply["through"]
            else:
                from .reset_history import read_reset_history
                reply = await read_reset_history(c, request)
                request["through_attempt"] = reply["through_attempt"]
            if self._identity() != original:
                raise RecordArchiveError("connection_lost")
            token = str(uuid4())
            actions, public = {}, {}
            for direction, enabled in (("older", reply["next_before"] is not None), ("newer", bool(stack))):
                if enabled:
                    action = str(uuid4())
                    actions[action] = direction
                    public[direction] = action
                else:
                    public[direction] = None
            self._views[kind] = dict(binding=original, snapshot_id=token, actions=actions,
                                    request=deepcopy(request), reply=deepcopy(reply), stack=stack)
            return deepcopy(dict(kind=kind, snapshot_id=token, actions=public, request=request, reply=reply,
                page=len(stack) + 1, actor=c.config.player_id,
                roster={p["player_id"]: p["display_name"] for p in c._players}))
        finally:
            self._busy = False


MESSAGES = {
    "battle_archive_unsupported": "This host does not provide paged battle records. Its recent Trainer Card records remain separate.",
    "reset_history_unsupported": "This host does not provide personal attempt receipts. No empty history is inferred.",
    "trade_archive_unsupported": "This host does not provide your personal trade journal. No empty history is inferred.",
    "connection_lost": "The original authenticated connection ended. Displayed records are an earlier snapshot.",
    "stale": "That page belongs to an earlier view. Load the newest snapshot again.",
    "invalid_filter": "Review the source, peer and record-number filters, then load again.",
    "unavailable": "These records could not be read. Displayed records, if any, are an earlier snapshot.",
}


class RecordArchivePanel:
    def __init__(self, parent, worker):
        import tkinter as tk
        from tkinter import ttk
        self.worker = worker
        self._connected = self._pending = self._closed = self._suspended = False
        self._snapshots = {}
        self._peer_ids = {"battle": [None], "trade": [None]}
        self._rows = {"battle": [], "hunt": [], "trade": []}
        self._last_kind = "battle"
        self.frame = ttk.Frame(parent, padding=12)
        self.frame.pack(fill="both", expand=True)
        self.message = tk.StringVar(value="Open your character, then load its own host records.")
        ttk.Label(self.frame, textvariable=self.message, wraplength=560).pack(anchor="w", pady=(0, 8))
        tabs = ttk.Notebook(self.frame)
        tabs.pack(fill="both", expand=True)
        self._load_buttons, self._nav_buttons, self._tables, self._notes, self._details = {}, {}, {}, {}, {}
        for kind, title in (("battle", "Battle archive"), ("hunt", "Attempt receipts"), ("trade", "Trade journal")):
            from .launcher_display import scrollable_frame
            container = ttk.Frame(tabs)
            tabs.add(container, text=title)
            page = scrollable_frame(container, padding=8)
            if kind == "battle":
                self.mode, self.outcome = tk.StringVar(value="All formats"), tk.StringVar(value="All outcomes")
                row = ttk.Frame(page)
                row.pack(fill="x")
                for variable, choices in ((self.mode, ("All formats", "1v1", "2v2")),
                                           (self.outcome, ("All outcomes", "Win", "Loss", "Draw"))):
                    ttk.Combobox(row, textvariable=variable, values=choices, state="readonly", width=17).pack(side="left", padx=(0, 6))
                row = ttk.Frame(page)
                row.pack(fill="x", pady=6)
                self.peer = ttk.Combobox(row, values=("All Trainers",), state="readonly", width=27)
                self.peer.current(0)
                self.peer.pack(side="left", padx=(0, 6))
                self.relation = tk.StringVar(value="Any relationship")
                ttk.Combobox(row, textvariable=self.relation, values=("Any relationship", "Same side", "Opposing side"), state="readonly", width=18).pack(side="left")
                row = ttk.Frame(page)
                row.pack(fill="x")
                ttk.Label(row, text="Record # (blank = all)").pack(side="left")
                self.record = tk.StringVar()
                entry = ttk.Entry(row, textvariable=self.record, width=13, validate="key",
                    validatecommand=(self.frame.register(lambda value: not value or value.isascii() and value.isdigit() and len(value) <= 20), "%P"))
                entry.pack(side="left", padx=6)
                entry.bind("<Return>", lambda _: self.load("battle"))
                columns = (("number", "Record", 68), ("mode", "Format", 60), ("outcome", "Your result", 80), ("peer", "Other Trainers", 280))
            elif kind == "hunt":
                self.source_ids = sorted(SOURCES)
                self.source = ttk.Combobox(page, values=[SOURCES[i] for i in self.source_ids], state="readonly", width=42)
                self.source.current(0)
                self.source.pack(anchor="w")
                columns = (("number", "Attempt", 75), ("revision", "Saved revision", 130), ("count", "Observed prior count", 160))
            else:
                self.trade_peer = ttk.Combobox(page, values=("All Trainers",), state="readonly", width=35)
                self.trade_peer.current(0)
                self.trade_peer.pack(anchor="w", pady=(0, 6))
                row = ttk.Frame(page)
                row.pack(fill="x")
                self.trade_record, self.trade_serial = tk.StringVar(), tk.StringVar()
                for title, variable in (("Record #", self.trade_record), ("Pokémon instance #", self.trade_serial)):
                    ttk.Label(row, text=title).pack(side="left", padx=(0, 4))
                    entry = ttk.Entry(row, textvariable=variable, width=12, validate="key",
                        validatecommand=(self.frame.register(lambda value: not value or value.isascii() and value.isdigit() and len(value) <= 20), "%P"))
                    entry.pack(side="left", padx=(0, 8))
                    entry.bind("<Return>", lambda _: self.load("trade"))
                ttk.Label(page, text="Blank number filters include all your committed trades.").pack(anchor="w", pady=4)
                columns = (("number", "Record", 70), ("state", "Your delivery", 135), ("sent", "Sent", 145), ("received", "Received", 145))
            navigation = ttk.Frame(page)
            navigation.pack(fill="x", pady=8)
            button = ttk.Button(navigation, text="Load newest snapshot", command=lambda k=kind: self.load(k), state="disabled")
            button.pack(side="left")
            self._load_buttons[kind] = button
            for direction in ("newer", "older"):
                button = ttk.Button(navigation, text=direction.capitalize(), command=lambda k=kind, d=direction: self.navigate(k, d), state="disabled")
                button.pack(side="left", padx=(6, 0))
                self._nav_buttons[kind, direction] = button
            table_frame = ttk.Frame(page)
            table_frame.pack(fill="both", expand=True)
            table = ttk.Treeview(table_frame, columns=[c[0] for c in columns], show="headings", height=8, selectmode="browse")
            bar = ttk.Scrollbar(table_frame, orient="vertical", command=table.yview)
            bar.pack(side="right", fill="y")
            table.configure(yscrollcommand=bar.set)
            for key, label, width in columns:
                table.heading(key, text=label)
                table.column(key, width=width, minwidth=40)
            table.pack(fill="both", expand=True)
            table.bind("<<TreeviewSelect>>", lambda _, k=kind: self.select(k))
            self._tables[kind] = table
            self._notes[kind], self._details[kind] = tk.StringVar(), tk.StringVar(value="Select a record for its details.")
            ttk.Label(page, textvariable=self._notes[kind], wraplength=550).pack(anchor="w", pady=6)
            if kind == "trade":
                self.trade_direction = tk.StringVar(value="Received snapshot")
                choice = ttk.Combobox(page, textvariable=self.trade_direction,
                    values=("Received snapshot", "Sent snapshot"), state="readonly", width=23)
                choice.pack(anchor="w")
                choice.bind("<<ComboboxSelected>>", lambda _: self.select("trade"))
            ttk.Label(page, textvariable=self._details[kind], wraplength=550).pack(anchor="w", pady=6)
            explanation = {"battle": "Only your released results are visible. Filters apply across this archive snapshot. Names use the connected roster; archived records do not contain historical names or dates. A new result appears only when you load newest.",
                "hunt": "Receipts count admitted personal encounters, not captured or shiny Pokémon. They do not change odds, enable an encounter or authorize a reset. Other Trainers' attempts are private.",
                "trade": "Only your committed paired trades are visible. Pokémon details are original as-traded snapshots, not current ownership. Delivery status is your acknowledgment as of this read; browsing never applies or acknowledges a trade. Native recovery remains separate."}[kind]
            ttk.Label(page, text=explanation, wraplength=550).pack(anchor="w", pady=6)

    def _filters(self, kind):
        if kind == "hunt":
            index = self.source.current()
            if index < 0:
                raise ValueError()
            return dict(encounter_id=self.source_ids[index])
        peer = self.peer if kind == "battle" else self.trade_peer
        index = peer.current()
        if not 0 <= index < len(self._peer_ids[kind]):
            raise ValueError()
        if kind == "trade":
            return dict(peer=self._peer_ids[kind][index], serial=int(self.trade_serial.get() or "0"),
                        record=int(self.trade_record.get() or "0"))
        record = int(self.record.get()) if self.record.get() else 0
        if not 0 <= record <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError()
        return dict(mode={"All formats": "all", "1v1": "singles", "2v2": "doubles"}[self.mode.get()],
            outcome={"All outcomes": "all", "Win": "win", "Loss": "loss", "Draw": "draw"}[self.outcome.get()],
            peer=self._peer_ids[kind][index], relation={"Any relationship": "all", "Same side": "together", "Opposing side": "against"}[self.relation.get()], record=record)

    def load(self, kind):
        try:
            filters = self._filters(kind)
            if kind == "battle":
                default_battle_archive_request(**filters)
            elif kind == "trade":
                default_trade_archive_request(**filters)
        except (ValueError, KeyError, IndexError):
            self.message.set(MESSAGES["invalid_filter"])
            return
        self._request(kind, filters=filters)

    def navigate(self, kind, direction):
        view = self._snapshots.get(kind)
        token = view["actions"].get(direction) if view else None
        if token:
            self._request(kind, snapshot_id=view["snapshot_id"], action_id=token)

    def _request(self, kind, **fields):
        if self._pending or not self._connected or self._closed or self._suspended or self.worker is None:
            return
        if self.worker.request_record_archive(kind, **fields):
            self._pending, self._last_kind = True, kind
            self._enable()

    def _enable(self):
        available = self._connected and not (self._pending or self._closed or self._suspended)
        for button in self._load_buttons.values():
            button.configure(state="normal" if available else "disabled")
        for (kind, direction), button in self._nav_buttons.items():
            view = self._snapshots.get(kind)
            button.configure(state="normal" if available and view and view["actions"].get(direction) else "disabled")

    def _render(self, snapshot):
        kind, reply = snapshot["kind"], snapshot["reply"]
        self._snapshots[kind] = snapshot
        rows = reply["entries"] if kind == "hunt" else reply["rows"]
        self._rows[kind] = rows
        table = self._tables[kind]
        for item in table.get_children():
            table.delete(item)
        actor, roster = snapshot["actor"], snapshot["roster"]
        for index, row in enumerate(rows):
            if kind == "battle":
                values = (row["sequence"], "1v1" if row["mode"] == 2 else "2v2", battle_outcome(row, actor).capitalize(),
                    ", ".join(roster.get(p, "Offline Trainer") for p in row["players"] if p != actor))
            elif kind == "hunt":
                values = (row["attempt"], row["checkpoint_revision"], row["observed_count"])
            else:
                import base64
                from .trade_inspection import summarize_record
                from .trade_forms import species_label
                names = [species_label(summarize_record(base64.b64decode(row[key], validate=True)).species) for key in ("sent", "received")]
                values = (row["sequence"], "Acknowledged" if row["applied"] else "Recovery pending", *names)
            table.insert("", "end", iid=str(index), values=values)
        if kind in {"battle", "trade"}:
            current = snapshot["request"]["peer"]
            ids = set(roster) | ({p for row in rows for p in row["players"]} if kind == "battle" else {row["peer"] for row in rows})
            if current is not None:
                ids.add(current)
            self._peer_ids[kind] = [None, *sorted(ids - {actor})]
            peer = self.peer if kind == "battle" else self.trade_peer
            peer.configure(values=["All Trainers", *[roster.get(p, "Recorded Trainer " + p[:8]) for p in self._peer_ids[kind][1:]]])
            peer.current(self._peer_ids[kind].index(current))
            self._notes[kind].set(f"Page {snapshot['page']} · {reply['total']} matching recorded {'battles' if kind == 'battle' else 'trades'} · snapshot through #{reply['through']}.")
        else:
            self._notes[kind].set(f"{SOURCES[reply['encounter_id']]} · page {snapshot['page']} · snapshot through attempt {reply['through_attempt']} · latest count observed {reply['current_attempt']}.")
        self._details[kind].set("Select a record for its details." if rows else "No matching record in this verified page.")
        self.message.set("Host records loaded. Navigation stays within this snapshot; Load newest starts a fresh snapshot.")

    def select(self, kind):
        selected = self._tables[kind].selection()
        if not selected:
            return
        row, snapshot = self._rows[kind][int(selected[0])], self._snapshots[kind]
        if kind == "hunt":
            text = (f"Attempt {row['attempt']} · canonical checkpoint revision {row['checkpoint_revision']}\n"
                    f"Native observed prior count: {row['observed_count']}\nReceipt ID: {row['request_id']}\n"
                    "This records admission only. Shiny, capture and reset outcome are UNKNOWN.")
        elif kind == "battle":
            actor, roster = snapshot["actor"], snapshot["roster"]
            slot = row["players"].index(actor)
            parties = {p["player_id"]: p["party_count"] for p in row["checkpoints"]}
            sides = [[], []]
            for index, player in enumerate(row["players"]):
                sides[0 if index % 2 == slot % 2 else 1].append(roster.get(player, "Recorded Trainer " + player[:8])
                    + (" (you)" if player == actor else "") + f" · {parties[player]} Pokémon")
            text = f"Record #{row['sequence']} · {battle_outcome(row, actor).capitalize()}\nYour side: " + "; ".join(sides[0]) + "\nOpposing side: " + "; ".join(sides[1])
        else:
            import base64
            from .trade_inspection import summarize_record
            direction = "received" if self.trade_direction.get() == "Received snapshot" else "sent"
            summary = summarize_record(base64.b64decode(row[direction], validate=True))
            text = (f"Trade #{row['sequence']} with {snapshot['roster'].get(row['peer'], 'Recorded Trainer ' + row['peer'][:8])}\n"
                f"Your canonical revision: {row['revision']} · Delivery: {'acknowledged' if row['applied'] else 'recovery pending'}\n"
                + direction.capitalize() + " at this trade — not a current ownership claim\n\n"
                + "\n\n".join(title + "\n" + "\n".join(lines) for title, lines in summary.pages()))
        self._details[kind].set(text)

    def handle_event(self, event):
        if self._closed:
            return event.kind == "record_archive"
        if event.kind == "record_archive":
            self._pending = False
            if event.code == "ready" and self._connected and event.archive_snapshot is not None:
                self._render(event.archive_snapshot)
            else:
                view = self._snapshots.get(self._last_kind)
                if view:
                    view["actions"] = {}
                self.message.set(MESSAGES.get(event.code, MESSAGES["unavailable"]))
            self._enable()
            return True
        if event.kind in {"status", "complete"}:
            connected = event.kind == "status" and event.state == "running" and event.connected
            if self._connected and not connected:
                for view in self._snapshots.values():
                    view["actions"] = {}
                self.message.set(MESSAGES["connection_lost"])
            self._connected = connected
            self._enable()
        return False

    def set_closing(self, value):
        self._suspended = bool(value)
        self._enable()

    def close(self):
        self._closed = True
        self._enable()
