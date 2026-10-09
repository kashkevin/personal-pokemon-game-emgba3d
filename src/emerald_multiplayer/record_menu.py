"""Six-row native browsing of private durable records; no gameplay mutation."""
from __future__ import annotations

import base64
from copy import deepcopy
from textwrap import wrap

from .battle_archive import (BattleArchiveUnsupported, default_battle_archive_request,
                            read_battle_archive)
from .record_views import battle_outcome
from .reset_history import (ResetHistoryUnsupported, default_reset_history_request,
                           read_reset_history)
from .reset_protocol import SOURCES
from .species_labels import species_label
from .trade_archive import (TradeArchiveUnsupported, default_trade_archive_request,
                           fetch_trade_archive)
from .trade_inspection import summarize_record


class NativeRecordMenu:
    def __init__(self, companion):
        self.companion = companion
        self.reset()

    def reset(self):
        self.kind = None
        self.page = "home"
        self.request = self.data = self.selected = self.summary = None
        self.stack = []
        self.offset = self.source_offset = self.summary_page = 0
        self.dirty = False
        self.notice = ""
        self.binding = None

    def _session(self):
        c = self.companion
        return (c.world_id, c.server_epoch, c.session_epoch) if c.connected else None

    def open(self, kind=None, encounter_id=None):
        self.reset()
        self.binding = self._session()
        if kind is not None:
            self._start(kind, encounter_id)

    def _start(self, kind, encounter_id=None):
        self.kind, self.page = kind, "list"
        self.request = (default_battle_archive_request() if kind == "battle" else
                        default_trade_archive_request() if kind == "trade" else
                        default_reset_history_request(encounter_id, limit=3))
        self._reload()

    def _reload(self):
        self.data = self.selected = self.summary = None
        self.stack, self.offset, self.notice, self.dirty = [], 0, "", True
        if self.kind == "hunt":
            self.request.update(through_attempt=None, before_attempt=None)
        else:
            self.request.update(through=0, before=0)

    async def refresh(self):
        original = self._session()
        if original is None or original != self.binding:
            raise ConnectionError("record browser lost its authenticated session")
        if not self.dirty:
            return
        from .companion import BattleChallengeError
        try:
            self.data = await {"battle": read_battle_archive, "trade": fetch_trade_archive,
                               "hunt": read_reset_history}[self.kind](self.companion, self.request)
            self.notice = ""
        except (BattleArchiveUnsupported, TradeArchiveUnsupported, ResetHistoryUnsupported):
            self.data, self.notice = None, "Host lacks this record browser"
        except BattleChallengeError as error:
            if error.code != "reset_disabled":
                raise
            self.data, self.notice = None, "Host hunt ledger is not enabled"
        if self._session() != original:
            self.data = None
            raise ConnectionError("record browser changed its authenticated session")
        self.dirty = False

    def _name(self, player):
        return next((p["display_name"] for p in self.companion._players if p["player_id"] == player),
                    "Trainer " + player[:8])

    def _rows(self):
        return [] if self.data is None else self.data["entries" if self.kind == "hunt" else "rows"]

    def render(self):
        actions = []
        def add(label, operation="", *args):
            actions.append((label, "records_" + operation if operation else "", args))
        title, status = "Your record archives", self.notice or "Private recorded activity"
        if self.page == "home":
            add("Full battle archive", "open", "battle")
            add("Committed trade journal", "open", "trade")
            add("Personal hunt receipts", "sources", 0)
        elif self.page == "sources":
            title, status = "Choose a hunt", "Personal admissions only"
            sources = sorted(SOURCES)
            for source in sources[self.source_offset:self.source_offset + 4]:
                add(SOURCES[source], "open", "hunt", source)
            if self.source_offset + 4 < len(sources):
                add("Next sources", "sources", self.source_offset + 4)
            if self.source_offset:
                add("Previous sources", "sources", max(0, self.source_offset - 4))
        elif self.page == "list":
            title = {"battle": "Full battle archive", "trade": "Your trade journal", "hunt": "Personal attempt receipts"}[self.kind]
            if self.data is None:
                add("Retry record read", "refresh")
                return title, status, actions
            total = self.data["through_attempt"] if self.kind == "hunt" else self.data["total"]
            status = f"{total} matching records"
            if self.kind == "hunt":
                status = f"{total} admitted attempts"
                if self.data["current_attempt"] > total:
                    status = "New attempts; refresh for latest"
            for row in self._rows()[self.offset:self.offset + 3]:
                if self.kind == "battle":
                    label = f"#{row['sequence']} {'1v1' if row['mode'] == 2 else '2v2'} {battle_outcome(row, self.companion.config.player_id)}"
                    key = row["battle_id"]
                elif self.kind == "trade":
                    mon = summarize_record(base64.b64decode(row["received"], validate=True))
                    label, key = f"#{row['sequence']} {species_label(mon.species)}", row["transaction_id"]
                else:
                    label, key = f"Attempt #{row['attempt']}", row["request_id"]
                add(label, "detail", key)
            if self.offset + 3 < len(self._rows()) or self.data["next_before"] is not None:
                add("Older records", "older")
            if self.offset or self.stack:
                add("Newer records", "newer")
            add("Options and refresh", "options")
            if not self._rows():
                status = "No matching recorded activity"
        elif self.page == "options":
            if self.kind == "battle":
                title = "Battle archive filters"
                for field, label in (("mode", "Format"), ("outcome", "Result"), ("peer", "Trainer"), ("relation", "Role")):
                    value = self.request[field]
                    label_value = ("Anyone" if value is None else self._name(value)) if field == "peer" else value
                    add(label + ": " + label_value, "filter", field)
                add("Refresh matching archive", "refresh")
                add("Clear all filters", "clear")
            elif self.kind == "trade":
                title = "Trade journal filters"
                peer = self.request["peer"]
                add("Trainer: " + ("Anyone" if peer is None else self._name(peer)), "filter", "peer")
                add("Instance: " + (str(self.request["serial"]) if self.request["serial"] else "Any"))
                add("Refresh matching journal", "refresh")
                add("Clear all filters", "clear")
                add("Back to journal", "list")
            else:
                title, status = "Hunt receipt options", SOURCES[self.request["encounter_id"]]
                add("Latest admitted attempts", "refresh")
                if self.data and self.data["first"] is not None:
                    add("First admitted attempt", "bound", "first")
                    add("Last in this snapshot", "bound", "latest")
                add("Choose another source", "sources", 0)
                add("Back to receipts", "list")
        elif self.page == "detail":
            row = self.selected
            if self.kind == "battle":
                title = f"Battle #{row['sequence']}"
                status = "Your result: " + battle_outcome(row, self.companion.config.player_id)
                for slot, player in enumerate(row["players"]):
                    add(f"Side {1 + slot % 2}: {self._name(player)}")
                add("Parties at battle entry", "battle_parties")
                add("Back to archive", "list")
            elif self.kind == "trade":
                title, status = f"Trade #{row['sequence']}", "With " + self._name(row["peer"])
                for key, label in (("sent", "Sent"), ("received", "Received")):
                    mon = summarize_record(base64.b64decode(row[key], validate=True))
                    add(label + ": " + species_label(mon.species), "mon", key)
                add("Your delivery: " + ("applied" if row["applied"] else "pending"))
                add(f"Your save: #{row['revision']}")
                add("Trace sent Pokemon", "trace", "sent")
                add("Trace received Pokemon", "trace", "received")
            else:
                title, status = f"Attempt #{row['attempt']}", "Durably admitted; outcome unknown"
                add(f"Host checkpoint #{row['checkpoint_revision']}")
                add(f"Previously seen: {row['observed_count']}")
                for line in wrap("Receipt: " + row["request_id"], 25):
                    add(line)
                add("Back to receipts", "list")
        elif self.page == "battle_parties":
            title, status = "Battle entry parties", "Original checkpoint party sizes"
            for index, checkpoint in enumerate(self.selected["checkpoints"]):
                add(f"Trainer {index + 1}: {checkpoint['party_count']} Pokemon")
            add("Back to battle", "detail_back")
        elif self.page == "mon":
            pages = self.summary.pages()
            status, facts = pages[self.summary_page]
            title = f"As traded: {self.summary_page + 1}/{len(pages)}"
            for fact in facts:
                add(fact)
            add("Previous detail", "mon_page", (self.summary_page - 1) % len(pages))
            add("Next detail", "mon_page", (self.summary_page + 1) % len(pages))
        return title, status, actions

    async def choose(self, operation, args):
        if self._session() is None or self._session() != self.binding:
            raise ConnectionError("record choice changed its authenticated session")
        op = operation.removeprefix("records_")
        if op == "open":
            self._start(*args)
        elif op == "sources":
            self.page, self.source_offset = "sources", args[0]
        elif op == "refresh":
            self.page = "list"
            self._reload()
        elif op == "list":
            self.page = "list"
        elif op == "options":
            self.page = "options"
        elif op == "older":
            if self.offset + 3 < len(self._rows()):
                self.offset += 3
            elif self.data["next_before"] is not None:
                request = deepcopy(self.request)
                through, before = ("through_attempt", "before_attempt") if self.kind == "hunt" else ("through", "before")
                request[through] = self.data[through]
                self.stack.append((request, self.data, self.offset))
                self.request = dict(request, **{before: self.data["next_before"]})
                self.data, self.offset, self.dirty = None, 0, True
        elif op == "newer":
            if self.offset:
                self.offset = max(0, self.offset - 3)
            elif self.stack:
                self.request, self.data, self.offset = self.stack.pop()
        elif op == "filter":
            field = args[0]
            choices = ({"mode": ("all", "singles", "doubles"), "outcome": ("all", "win", "loss", "draw"),
                        "relation": ("all", "together", "against")}.get(field))
            if field == "peer":
                peers = [p["player_id"] for p in self.companion._players if p["player_id"] != self.companion.config.player_id]
                choices = (None, *peers)
            if field == "relation" and self.request["peer"] is None:
                self.notice = "Choose a trainer before a role"
                return
            current = self.request[field]
            self.request[field] = choices[(choices.index(current) + 1) % len(choices)] if current in choices else choices[0]
            if field == "peer" and self.request["peer"] is None and self.kind == "battle":
                self.request["relation"] = "all"
            self._reload()
        elif op == "clear":
            self._start(self.kind)
        elif op == "detail":
            key = {"battle": "battle_id", "trade": "transaction_id", "hunt": "request_id"}[self.kind]
            self.selected = next(row for row in self._rows() if row[key] == args[0])
            self.page = "detail"
        elif op == "bound":
            self.selected, self.page = self.data[args[0]], "detail"
        elif op == "battle_parties":
            self.page = "battle_parties"
        elif op == "detail_back":
            self.page = "detail"
        elif op == "mon":
            self.summary = summarize_record(base64.b64decode(self.selected[args[0]], validate=True))
            self.summary_page, self.page = 0, "mon"
        elif op == "mon_page":
            self.summary_page = args[0]
        elif op == "trace":
            mon = summarize_record(base64.b64decode(self.selected[args[0]], validate=True))
            self.request = default_trade_archive_request(serial=mon.serial)
            self.page = "list"
            self._reload()
        elif op == "back":
            if self.page == "home":
                return True
            self.page = ("detail" if self.page in {"mon", "battle_parties"} else "list"
                         if self.page in {"detail", "options"} else "home")
        else:
            raise ValueError("unknown record browser action")
