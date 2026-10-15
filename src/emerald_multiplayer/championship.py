"""Durable four-human brackets over the existing native battle service.

No client supplies outcomes. Only released BattleResults advance a bracket.
Persisting an invitation intent precedes the volatile Desk call, so a host
restart can never replace an uncertain match with a second native battle.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .championship_protocol import (HISTORY_LIMIT, VERSION,
    validate_championship_request, validate_championship_reply, validate_championship_view)
from .battle_reservations import BattleReservationTerminal
from .battle_admission_cleanup_protocol import AdmissionCleanupTerminal, UnenteredInvitationTerminal
from .protocol import MAX_COUNTER, ProtocolError, validate_identity
from .storage import StorageError
from .team_protocol import _uuid

SCOPE = "durable-four-player-championships-v1"
MAX_RECORD_BYTES = 8192
_SCHEMA = {
    "metadata": "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "brackets": """CREATE TABLE brackets (sequence INTEGER PRIMARY KEY,
        championship_id TEXT NOT NULL UNIQUE, state TEXT NOT NULL,
        player0 TEXT NOT NULL, player1 TEXT NOT NULL, player2 TEXT NOT NULL, player3 TEXT NOT NULL,
        record TEXT NOT NULL, sha256 TEXT NOT NULL)""",
    "bracket_states": "CREATE INDEX bracket_states ON brackets (state, sequence)",
    "attempts": """CREATE TABLE attempts (battle_id TEXT PRIMARY KEY,
        championship_id TEXT NOT NULL, round INTEGER NOT NULL, attempt INTEGER NOT NULL,
        record TEXT NOT NULL, sha256 TEXT NOT NULL,
        UNIQUE (championship_id, round, attempt))""",
}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _encoded(value):
    raw = _json(value)
    if len(raw.encode("ascii")) > MAX_RECORD_BYTES:
        raise StorageError("championship_invalid", "Championship record exceeds its bound")
    return raw, hashlib.sha256(raw.encode("ascii")).hexdigest()


class Championships:
    """World-owned sidecar; all operations run synchronously on the host loop."""

    def __init__(self, path, *, world_id, build_id, ruleset_id):
        _uuid(world_id, "world_id")
        validate_identity(build_id, "build_id")
        validate_identity(ruleset_id, "ruleset_id")
        self.path = Path(path).resolve()
        self.identity = dict(format=SCOPE, world_id=world_id, build_id=build_id, ruleset_id=ruleset_id)
        self._statistics = {}
        self._statistics_valid = False
        self._statistics_changes = set()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction(initialize=not self.path.exists()) as connection:
            brackets = {}
            active = 0
            for row in connection.execute("SELECT * FROM brackets"):
                view = self._bracket(row)
                brackets[view["championship_id"]] = view
                active += view["state"] in {"proposed", "active"}
            if active > 1:
                self._invalid()
            latest = {}
            for row in connection.execute("SELECT * FROM attempts ORDER BY attempt"):
                attempt = self._attempt(row)
                view = brackets.get(attempt["championship_id"])
                if view is None or view["state"] == "proposed":
                    self._invalid()
                match = view["matches"][attempt["round"]]
                if attempt["players"] != match["players"] or attempt["attempt"] > match["attempt"]:
                    self._invalid()
                key = (attempt["championship_id"], attempt["round"])
                if attempt["attempt"] != latest.get(key, 0) + 1:
                    self._invalid()
                latest[key] = attempt["attempt"]
                if attempt["attempt"] == match["attempt"] and attempt["battle_id"] != match["battle_id"]:
                    self._invalid()
            for view in brackets.values():
                for match in view["matches"]:
                    if latest.get((view["championship_id"], match["round"]), 0) != match["attempt"]:
                        self._invalid()
        self._statistics = self._statistics_from_views(brackets.values())
        self._statistics_valid = True

    @staticmethod
    def _invalid():
        raise StorageError("championship_invalid", "Championship records could not be verified")

    @contextmanager
    def _transaction(self, *, initialize=False):
        connection = None
        commit_started = False
        try:
            connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("BEGIN IMMEDIATE")
            schema = {row["name"]: row["sql"] for row in connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_autoindex_%'")}
            if not schema and initialize:
                for sql in _SCHEMA.values():
                    connection.execute(sql)
                connection.executemany("INSERT INTO metadata VALUES (?, ?)", self.identity.items())
                schema = dict(_SCHEMA)
            if schema != _SCHEMA or dict(connection.execute("SELECT key, value FROM metadata")) != self.identity:
                self._invalid()
            yield connection
            commit_started = True
            connection.execute("COMMIT")
        except BaseException as error:
            if connection is not None and connection.in_transaction:
                connection.execute("ROLLBACK")
            if isinstance(error, (sqlite3.DatabaseError, OSError)):
                raise StorageError("championship_unavailable", "Championship records are unavailable") from error
            raise
        finally:
            if connection is not None:
                # Successful writes and uncertain COMMITs require a fresh
                # projection; rolled-back work before COMMIT does not count.
                if commit_started and connection in self._statistics_changes:
                    self._statistics_valid = False
                self._statistics_changes.discard(connection)
                connection.close()

    @staticmethod
    def _statistics_from_views(views):
        statistics = {}
        for view in views:
            if set(view["consent"]) != set(view["players"]):
                continue
            for actor in view["players"]:
                counts = statistics.setdefault(actor, dict(entries=0, completed=0, wins=0))
                counts["entries"] += 1
                if view["state"] == "completed":
                    counts["completed"] += 1
                    counts["wins"] += view["champion"] == actor
        return statistics

    def statistics(self, actor):
        """Validated host projection; no names, native holds or mutable rows.

        Entries require all four bracket consents, including a later canceled
        bracket. Completed/wins require a released-result final/champion.
        Startup verifies the entire archive before the listener opens; reads
        reuse that projection until an actual committed bracket change.
        """
        _uuid(actor, "actor")
        if not self._statistics_valid:
            with self._transaction() as connection:
                views = [self._bracket(row) for row in connection.execute("SELECT * FROM brackets")]
            self._statistics = self._statistics_from_views(views)
            self._statistics_valid = True
        return dict(self._statistics.get(actor, dict(entries=0, completed=0, wins=0)))

    def _decode(self, row):
        try:
            raw = row["record"]
            if type(raw) is not str or len(raw) > MAX_RECORD_BYTES:
                self._invalid()
            value = json.loads(raw)
            if _encoded(value) != (raw, row["sha256"]):
                self._invalid()
            return value
        except (ValueError, TypeError, KeyError, RecursionError) as error:
            raise StorageError("championship_invalid", "Championship record is malformed") from error

    def _fingerprint(self, value):
        return hashlib.sha256(_json(dict(identity=self.identity, **{key: value[key] for key in
            ("championship_id", "generation", "sender", "players", "names")})).encode("ascii")).hexdigest()

    def _bracket(self, row):
        value = self._decode(row)
        try:
            validate_championship_view(value, value["sender"])
            if (value["championship_id"] != row["championship_id"] or value["state"] != row["state"]
                    or value["players"] != [row[f"player{index}"] for index in range(4)]
                    or value["fingerprint"] != self._fingerprint(value)):
                self._invalid()
        except (ProtocolError, KeyError, TypeError) as error:
            raise StorageError("championship_invalid", "Championship bracket is malformed") from error
        return value

    def _attempt(self, row):
        value = self._decode(row)
        try:
            legacy = {"championship_id", "round", "attempt", "battle_id",
                      "players", "sender", "native_generation", "canceled"}
            if type(value) is not dict or set(value) not in (legacy, legacy | {"issuance"}):
                self._invalid()
            if "issuance" in value and (value["issuance"] not in {"pending", "dispatching"}
                    or value["issuance"] == "pending" and value["native_generation"] is not None):
                self._invalid()
            for key in ("championship_id", "battle_id", "sender"):
                _uuid(value[key], key)
            if value["native_generation"] is not None:
                _uuid(value["native_generation"], "native_generation")
            if (type(value["round"]) is not int or value["round"] not in (0, 1, 2)
                    or type(value["attempt"]) is not int or not 1 <= value["attempt"] <= MAX_COUNTER
                    or type(value["canceled"]) is not bool or type(value["players"]) is not list
                    or len(value["players"]) != 2 or len(set(value["players"])) != 2
                    or value["sender"] not in value["players"]):
                self._invalid()
            for player in value["players"]:
                _uuid(player, "player")
            if any(value[key] != row[key] for key in ("championship_id", "battle_id", "round", "attempt")):
                self._invalid()
        except (ProtocolError, KeyError, TypeError) as error:
            raise StorageError("championship_invalid", "Championship match identity is malformed") from error
        return value

    def _save(self, connection, view):
        validate_championship_view(view, view["sender"])
        raw, digest = _encoded(view)
        changed = connection.execute("UPDATE brackets SET state=?, record=?, sha256=? WHERE championship_id=? AND sha256<>?",
                                     (view["state"], raw, digest, view["championship_id"], digest))
        if changed.rowcount:
            self._statistics_changes.add(connection)

    def _save_attempt(self, connection, attempt):
        raw, digest = _encoded(attempt)
        connection.execute("UPDATE attempts SET record=?, sha256=? WHERE battle_id=? AND sha256<>?",
                           (raw, digest, attempt["battle_id"], digest))

    def _current(self, connection):
        row = connection.execute("SELECT * FROM brackets WHERE state IN ('proposed', 'active')").fetchone()
        return None if row is None else self._bracket(row)

    def _target(self, connection, request, actor):
        row = connection.execute("SELECT * FROM brackets WHERE championship_id=?", (request["championship_id"],)).fetchone()
        if row is None:
            raise ProtocolError("championship_missing", "This Championship is not retained")
        view = self._bracket(row)
        if actor not in view["players"]:
            raise ProtocolError("championship_not_participant", "This Championship belongs to other players")
        if any(request[key] != view[key] for key in ("generation", "fingerprint") if key in request):
            raise ProtocolError("championship_changed", "Refresh the current Championship before choosing")
        return view

    def claims_battle(self, battle_id):
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM attempts WHERE battle_id=?", (battle_id,)).fetchone()
            if row is not None:
                self._attempt(row)
            return row is not None

    @staticmethod
    def _native(desk, battle_id):
        return None if desk is None else desk._active.get(battle_id) or desk._history.get(battle_id)

    def _reconcile(self, connection, view, desk, results, reservations, admission):
        if view["state"] != "active":
            return
        for match in view["matches"]:
            if not match["attempt"]:
                continue
            row = connection.execute("SELECT * FROM attempts WHERE battle_id=?", (match["battle_id"],)).fetchone()
            if row is None:
                self._invalid()
            attempt = self._attempt(row)
            result = None if results is None else results.get(match["battle_id"])
            native = self._native(desk, match["battle_id"])
            if attempt.get("issuance") == "pending" and (native is not None or result is not None
                    or reservations is not None and reservations.contains(match["battle_id"])
                    or admission is not None and admission.has_consent(match["battle_id"])):
                self._invalid()
            terminal = None if reservations is None else reservations.terminal(match["battle_id"])
            unreserved = None if admission is None else admission.terminal(match["battle_id"])
            unentered = None if admission is None else admission.unentered_terminal(match["battle_id"])
            if unentered is not None:
                if terminal is not None or unreserved is not None or type(unentered) is not UnenteredInvitationTerminal:
                    self._invalid()
                terminal = unentered
            if unreserved is not None:
                if terminal is not None or type(unreserved) is not AdmissionCleanupTerminal:
                    self._invalid()
                terminal = unreserved
            if terminal is not None:
                if (type(terminal) not in (BattleReservationTerminal, AdmissionCleanupTerminal, UnenteredInvitationTerminal)
                        or any(getattr(terminal, key) != self.identity[key] for key in
                               ("world_id", "build_id", "ruleset_id"))
                        or terminal.battle_id != match["battle_id"] or terminal.mode != 2
                        or terminal.kind not in {"aborted", "closed"}
                        or set(terminal.players) != set(match["players"])
                        or terminal.sender != attempt["sender"] or (attempt["native_generation"] is not None
                        and terminal.generation != attempt["native_generation"])):
                    self._invalid()
                attempt["native_generation"] = terminal.generation
                if terminal.kind == "closed" and attempt["canceled"]:
                    self._invalid()
            if native is not None:
                if (native.mode != 2 or set(native.players) != set(match["players"])
                        or native.sender != attempt["sender"] or (attempt["native_generation"] is not None
                        and attempt["native_generation"] != native.generation)
                        or terminal is not None and native.fingerprint != terminal.fingerprint
                        or terminal is not None and terminal.kind == "closed"
                        and native.state not in {"closed", "release_authorized", "recovery_required"}):
                    self._invalid()
                attempt["native_generation"] = native.generation
            if terminal is not None and terminal.kind == "aborted":
                # Either every authorized BIND abort succeeded, or every
                # original never-reserved core has its durable HANDOFF receipt.
                # This read does not issue controls or clear any native hold.
                if (result is not None or match["state"] in {"won", "draw"}
                        or native is not None and (native.started
                        or native.state not in {"aborted", "aborting", "recovery_required"})):
                    self._invalid()
                attempt["canceled"] = True
                match.update(state="canceled", winner=None)
            elif result is not None:
                if (attempt["canceled"] or result["mode"] != 2 or set(result["players"]) != set(match["players"])
                        or result["battle_id"] != match["battle_id"] or result["sender"] != attempt["sender"]
                        or (attempt["native_generation"] is not None
                        and result["generation"] != attempt["native_generation"])
                        or terminal is not None and result["fingerprint"] != terminal.fingerprint):
                    self._invalid()
                attempt["native_generation"] = result["generation"]
                match["winner"] = result["players"][result["outcome"] - 1] if result["outcome"] in (1, 2) else None
                match["state"] = "won" if match["winner"] else "draw"
            elif native is not None:
                if attempt["canceled"] and native.state != "aborted":
                    self._invalid()
                # A Desk abort without BIND may still have an original Enter
                # latch or provisional cleanup/saver handoff. Its volatile
                # state alone must not authorize a replacement match.
                match["state"] = ("canceled" if attempt["canceled"] else "waiting"
                    if native.state in {"recovery_required", "aborting", "aborted", "closed"} else "invited"
                    if native.state in {"invited", "accepted"} else "playing")
                match["winner"] = None
            elif attempt["canceled"]:
                match.update(state="canceled", winner=None)
            else:
                # Neither an in-memory challenge nor a released result proves
                # this persisted issue intent never reached a native hold.
                match.update(state="waiting", winner=None)
            self._save_attempt(connection, attempt)
        if all(match["state"] == "won" for match in view["matches"][:2]):
            final = view["matches"][2]
            final["players"] = [match["winner"] for match in view["matches"][:2]]
            if not final["attempt"]:
                final["state"] = "ready"
        if view["matches"][2]["state"] == "won":
            view.update(state="completed", champion=view["matches"][2]["winner"])
        elif set(view["cancel_consent"]) == set(view["players"]) and all(
                match["state"] in {"blocked", "ready", "draw", "won", "canceled"} for match in view["matches"]):
            view["state"] = "canceled"
        self._save(connection, view)

    def _begin_issue(self, issue):
        """Commit the dispatch fence before the synchronous invitation callback.

        A crash with a new pending record is affirmative evidence that this
        callback was never entered. Old records lack that evidence forever.
        """
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM attempts WHERE battle_id=?", (issue["battle_id"],)).fetchone()
            attempt = self._attempt(row)
            if attempt != issue or attempt.get("issuance") != "pending" or attempt["canceled"]:
                self._invalid()
            attempt["issuance"] = "dispatching"
            self._save_attempt(connection, attempt)

    def _recover_issue(self, connection, view, request, actor, desk, results, reservations, admission):
        match = view["matches"][request["round"]]
        if (actor not in match["players"] or request["attempt"] != match["attempt"]
                or request["battle_id"] != match["battle_id"]):
            raise ProtocolError("championship_changed", "Recovery must name the exact original match")
        if view["state"] != "active" or match["state"] != "waiting":
            return  # An exact retry may already be canceled or have a verified result.
        row = connection.execute("SELECT * FROM attempts WHERE battle_id=?", (match["battle_id"],)).fetchone()
        attempt = self._attempt(row)
        if attempt.get("issuance") == "pending":
            if (self._native(desk, match["battle_id"]) is not None
                    or results is not None and results.get(match["battle_id"]) is not None
                    or reservations is not None and reservations.contains(match["battle_id"])
                    or admission is not None and admission.has_consent(match["battle_id"])):
                self._invalid()
            attempt["canceled"] = True
            self._save_attempt(connection, attempt)
        elif admission is not None:
            # The helper fences late consent/claim/BIND durably before returning.
            # Missing or fully accepted evidence stays waiting, never discarded.
            admission.unentered_terminal(match["battle_id"], revoke=True)
        self._reconcile(connection, view, desk, results, reservations, admission)

    def handle(self, actor, request, *, roster, desk, results, invite, reservations=None, admission=None,
               eligibility=None):
        """Outer server authenticates the current lease before this call.

        invite is a synchronous trusted callback using the original actor/core.
        It is called only after an exact intent has committed to this sidecar.
        ``eligibility`` (optional, the host's Frontier rules) takes the players who
        are entering and raises ProtocolError when a party may not.
        """
        validate_championship_request(request)
        operation = request["operation"]
        if reservations is None and desk is not None:
            reservations = desk.reservations
        if desk is not None:
            desk.refresh()
        issue = None
        with self._transaction() as connection:
            current = self._current(connection)
            if current is not None:
                self._reconcile(connection, current, desk, results, reservations, admission)
            if operation in {"status", "history"}:
                view = current if current is not None and actor in current["players"] else None
            elif operation == "create":
                if request["players"][0] != actor:
                    raise ProtocolError("championship_invalid", "The proposing player must be the first seed")
                previous = connection.execute("SELECT * FROM brackets WHERE championship_id=?",
                                              (request["championship_id"],)).fetchone()
                if previous is not None:
                    view = self._bracket(previous)
                    if view["players"] != request["players"] or view["sender"] != actor:
                        raise ProtocolError("championship_conflict", "Championship ID already names another bracket")
                else:
                    if current is not None and current["state"] in {"proposed", "active"}:
                        raise ProtocolError("championship_busy", "Finish or cancel the world's current Championship first")
                    if desk is None:
                        raise ProtocolError("battle_disabled", "This host has disabled new battle challenges")
                    if set(request["players"]) != set(roster):
                        raise ProtocolError("championship_roster_changed", "All four proposed players must still be connected")
                    players = list(request["players"])
                    if eligibility is not None:
                        eligibility(players)
                    view = dict(championship_id=request["championship_id"], generation=str(uuid4()), sender=actor,
                        players=players, names=[roster[player] for player in players], state="proposed",
                        consent=[actor], cancel_consent=[], champion=None,
                        matches=[dict(round=index, players=players[index*2:index*2+2] if index < 2 else [],
                            attempt=0, battle_id=None, state="ready" if index < 2 else "blocked", winner=None)
                            for index in range(3)])
                    view["fingerprint"] = self._fingerprint(view)
                    validate_championship_view(view, actor)
                    raw, digest = _encoded(view)
                    connection.execute("INSERT INTO brackets (championship_id,state,player0,player1,player2,player3,record,sha256) VALUES (?,?,?,?,?,?,?,?)",
                                       (view["championship_id"], view["state"], *players, raw, digest))
                    self._statistics_changes.add(connection)
            else:
                view = self._target(connection, request, actor)
                self._reconcile(connection, view, desk, results, reservations, admission)
                if operation == "accept" and view["state"] == "proposed":
                    if eligibility is not None and actor not in view["consent"]:
                        eligibility([actor])
                    view["consent"] = sorted(set(view["consent"]) | {actor})
                    if set(view["consent"]) == set(view["players"]):
                        view["state"] = "active"
                elif operation == "accept" and view["state"] == "active":
                    view["cancel_consent"] = [player for player in view["cancel_consent"] if player != actor]
                elif operation == "cancel":
                    if view["state"] == "proposed":
                        view["state"] = "canceled"
                    elif view["state"] == "active":
                        view["cancel_consent"] = sorted(set(view["cancel_consent"]) | {actor})
                        self._reconcile(connection, view, desk, results, reservations, admission)
                elif operation == "recover":
                    self._recover_issue(connection, view, request, actor, desk, results, reservations, admission)
                elif operation == "match":
                    match = view["matches"][request["round"]]
                    if actor not in match["players"]:
                        raise ProtocolError("championship_not_participant", "Only the assigned players can request this match")
                    if request["attempt"] not in {match["attempt"], match["attempt"] - 1}:
                        raise ProtocolError("championship_changed", "Refresh the latest match attempt first")
                    # A retry of the request that issued this attempt returns
                    # it even if its reply was lost and the match has finished.
                    retry = request["attempt"] == match["attempt"] - 1
                    if not retry and view["state"] == "active" and match["state"] in {"ready", "draw", "canceled"}:
                        if view["cancel_consent"]:
                            raise ProtocolError("championship_cancel_pending", "Resolve the Championship cancellation before another match")
                        if desk is None or match["attempt"] >= MAX_COUNTER:
                            raise ProtocolError("championship_unavailable", "A new Championship match is unavailable")
                        issue = dict(championship_id=view["championship_id"], round=match["round"],
                            attempt=match["attempt"] + 1, battle_id=str(uuid4()), players=list(match["players"]),
                            sender=actor, native_generation=None, canceled=False, issuance="pending")
                        raw, digest = _encoded(issue)
                        connection.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?)", (issue["battle_id"],
                            issue["championship_id"], issue["round"], issue["attempt"], raw, digest))
                        match.update(attempt=issue["attempt"], battle_id=issue["battle_id"], state="waiting", winner=None)
                    elif not match["attempt"]:
                        raise ProtocolError("championship_not_ready", "All four players must accept the bracket first")
                self._save(connection, view)
        if issue is not None:
            self._begin_issue(issue)
            try:
                invite(issue["battle_id"], next(player for player in issue["players"] if player != actor))
            except Exception:
                # No awaits occur between persistence and this callback. A
                # synchronous refusal before Desk insertion cannot hold a core.
                if self._native(desk, issue["battle_id"]) is None:
                    with self._transaction() as connection:
                        row = connection.execute("SELECT * FROM attempts WHERE battle_id=?", (issue["battle_id"],)).fetchone()
                        attempt = self._attempt(row)
                        attempt["canceled"] = True
                        self._save_attempt(connection, attempt)
                raise
            with self._transaction() as connection:
                view = self._target(connection, request, actor)
                self._reconcile(connection, view, desk, results, reservations, admission)
        with self._transaction() as connection:
            history = []
            if operation == "history":
                # No names, checkpoints or results from foreign rosters escape.
                for row in connection.execute("SELECT * FROM brackets WHERE state IN ('completed','canceled') "
                        "AND ? IN (player0,player1,player2,player3) ORDER BY sequence DESC LIMIT ?", (actor, HISTORY_LIMIT)):
                    archived = self._bracket(row)
                    if actor not in archived["players"]:
                        self._invalid()
                    history.append({key: archived[key] for key in ("championship_id", "players", "names", "champion", "state")})
        reply = dict(version=VERSION, operation=operation, current=view, history=history)
        validate_championship_reply(reply, actor, request)
        return reply
