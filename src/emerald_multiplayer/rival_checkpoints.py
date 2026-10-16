"""World-level rival checkpoints: lobby, battle issuance and durable completion.

Shared per world: whether each rival checkpoint has been completed, by whom,
with what result, and which players have passed it personally. Personal
Pokemon, items, Eggs, PCs and story flags stay in each character's own save;
this sidecar never edits a save and grants nothing. The engine reads the
summary to decide its barriers and gives each player the original scene's
rewards from that player's own script (guarded by the player's own flags).

Durable rules (the same discipline as ``championship.py``):

* a battle intent is committed before the volatile Desk invitation, so a
  restart never replaces an uncertain battle with a second one;
* only a released ``BattleResults`` record resolves a match; no client claim,
  disconnect or timeout ever completes a checkpoint;
* a checkpoint completes at most once (primary key), and a player's personal
  pass is recorded at most once per checkpoint.

Volatile rules: votes, the start grace and the countdown live in memory and
are recomputed from live presence on every request, so a host restart, a
disconnect or a player walking away simply returns the lobby to waiting.

Lobby (deterministic):

* present = connected players whose presence is on one of the checkpoint's
  maps with activity ``overworld`` or ``menu``;
* the countdown starts when at least two present players chose Start Now and
  either every present player chose Start Now, or the Start Now group has not
  changed for ``grace`` seconds (players who chose Wait or did not choose are
  then left out of this battle and catch up later);
* any change of the present players or of the Start Now group restarts the
  grace; a change during the countdown cancels it;
* when the countdown ends the battle plan is committed (``rival_formats``) and
  the first match becomes ready; any of its trainers asks the host to issue it,
  and every trainer accepts and enters it through ordinary Challenges.

Interruptions: a match whose native lifecycle aborts before a result (declined,
expired, a trainer disconnected before the battle started) is void. A 1v1 or
2v2 session with a void match is canceled and the lobby opens again; a round
robin skips the void match and completes if at least one match was played,
otherwise it is canceled. A match the native layer still holds (started, or
uncertain after a host restart) stays waiting for the existing battle recovery;
``recover`` asks the admission ledger to classify a never-entered invitation.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

from .protocol import ProtocolError, validate_identity
from .rival_catalogue import BY_ID, CHECKPOINTS, IDS, checkpoint_at
from .rival_formats import MODE_MULTI, MULTI, ROUND_ROBIN, SINGLES, PlannedMatch, plan, winners
from .rival_protocol import VERSION, validate_rival_reply, validate_rival_request
from .storage import StorageError
from .team_protocol import _uuid

SCOPE = "durable-rival-checkpoints-v1"
MAX_RECORD_BYTES = 8192
PRESENT_ACTIVITIES = frozenset({"overworld", "menu"})
_SCHEMA = {
    "metadata": "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "sessions": """CREATE TABLE sessions (sequence INTEGER PRIMARY KEY,
        session_id TEXT NOT NULL UNIQUE, checkpoint_id TEXT NOT NULL, state TEXT NOT NULL,
        record TEXT NOT NULL, sha256 TEXT NOT NULL)""",
    "session_states": "CREATE INDEX session_states ON sessions (checkpoint_id, state)",
    "attempts": """CREATE TABLE attempts (battle_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL, match INTEGER NOT NULL, attempt INTEGER NOT NULL,
        record TEXT NOT NULL, sha256 TEXT NOT NULL, UNIQUE (session_id, match, attempt))""",
    "completions": """CREATE TABLE completions (checkpoint_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL UNIQUE, record TEXT NOT NULL, sha256 TEXT NOT NULL)""",
    "clears": """CREATE TABLE clears (checkpoint_id TEXT NOT NULL, player_id TEXT NOT NULL,
        via TEXT NOT NULL, record TEXT NOT NULL, sha256 TEXT NOT NULL,
        PRIMARY KEY (checkpoint_id, player_id))""",
}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _encoded(value):
    raw = _json(value)
    if len(raw.encode("ascii")) > MAX_RECORD_BYTES:
        raise StorageError("rival_invalid", "rival checkpoint record exceeds its bound")
    return raw, hashlib.sha256(raw.encode("ascii")).hexdigest()


def _printable(value, limit=24):
    text = "".join(c if 32 <= ord(c) <= 126 else "?" for c in str(value)).strip()[:limit]
    return text or "Trainer"


@dataclass
class _Lobby:
    votes: dict = field(default_factory=dict)
    since: dict = field(default_factory=dict)
    present: frozenset = frozenset()
    starters: tuple = ()
    changed: float = 0.0
    countdown: tuple | None = None  # (deadline, roster)


class RivalCheckpoints:
    """World-owned sidecar; every operation runs synchronously on the host loop."""

    def __init__(self, path, *, world_id, build_id, ruleset_id, clock=time.monotonic,
                 countdown=5.0, grace=60.0, solo_wait=120.0, ready_timeout=180.0):
        _uuid(world_id, "world_id")
        validate_identity(build_id, "build_id")
        validate_identity(ruleset_id, "ruleset_id")
        for value in (countdown, grace, solo_wait, ready_timeout):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 3600:
                raise ValueError("rival lobby timings must be finite seconds")
        if not callable(clock):
            raise ValueError("rival clock must be callable")
        self.path = Path(path).resolve()
        self.identity = dict(format=SCOPE, world_id=world_id, build_id=build_id, ruleset_id=ruleset_id)
        self.clock, self.countdown, self.grace, self.solo_wait = clock, float(countdown), float(grace), float(solo_wait)
        self.ready_timeout = float(ready_timeout)
        self._last_time = None
        self._ready_since = {}  # (session_id, match) -> when it became ready; volatile like the lobby
        self._stuck_since = {}  # session_id -> since when every unresolved match is only "waiting"
        self._lobbies = {checkpoint_id: _Lobby() for checkpoint_id in IDS}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction(initialize=not self.path.exists()) as connection:
            self._verify(connection)

    # -- storage ---------------------------------------------------------------------------------------------

    @staticmethod
    def _invalid(message="rival checkpoint records could not be verified"):
        raise StorageError("rival_invalid", message)

    @contextmanager
    def _transaction(self, *, initialize=False):
        connection = None
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
                self._invalid("rival checkpoint records belong to another world or format")
            yield connection
            connection.execute("COMMIT")
        except BaseException as error:
            if connection is not None and connection.in_transaction:
                connection.execute("ROLLBACK")
            if isinstance(error, (sqlite3.DatabaseError, OSError)):
                raise StorageError("rival_unavailable", "rival checkpoint records are unavailable") from error
            raise
        finally:
            if connection is not None:
                connection.close()

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
            raise StorageError("rival_invalid", "rival checkpoint record is malformed") from error

    def _verify(self, connection):
        """Startup check of the entire sidecar before the host opens its listener."""
        sessions = {}
        active = {}
        for row in connection.execute("SELECT * FROM sessions ORDER BY sequence"):
            session = self._decode(row)
            if (session.get("session_id") != row["session_id"] or session.get("checkpoint_id") != row["checkpoint_id"]
                    or session.get("state") != row["state"] or row["checkpoint_id"] not in BY_ID
                    or row["state"] not in {"active", "completed", "canceled"}):
                self._invalid()
            if row["state"] == "active":
                if row["checkpoint_id"] in active:
                    self._invalid("two rival sessions are active at one checkpoint")
                active[row["checkpoint_id"]] = session
            sessions[row["session_id"]] = session
        for row in connection.execute("SELECT * FROM attempts"):
            attempt = self._decode(row)
            session = sessions.get(row["session_id"])
            if (session is None or attempt.get("battle_id") != row["battle_id"]
                    or not 0 <= row["match"] < len(session["matches"])
                    or session["matches"][row["match"]]["battle_id"] != row["battle_id"]):
                self._invalid()
        for row in connection.execute("SELECT * FROM completions"):
            completion = self._decode(row)
            session = sessions.get(row["session_id"])
            if (session is None or session["state"] != "completed" or session["checkpoint_id"] != row["checkpoint_id"]
                    or completion.get("session_id") != row["session_id"]):
                self._invalid()
        for row in connection.execute("SELECT * FROM clears"):
            clear = self._decode(row)
            if (row["checkpoint_id"] not in BY_ID or row["via"] not in {"battle", "catch_up", "solo"}
                    or clear != dict(checkpoint_id=row["checkpoint_id"], player_id=row["player_id"], via=row["via"])):
                self._invalid()

    def _session_row(self, connection, session_id):
        row = connection.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        return None if row is None else self._decode(row)

    def _active(self, connection, checkpoint_id):
        row = connection.execute("SELECT * FROM sessions WHERE checkpoint_id=? AND state='active'",
                                 (checkpoint_id,)).fetchone()
        return None if row is None else self._decode(row)

    def _save_session(self, connection, session):
        raw, digest = _encoded(session)
        connection.execute("UPDATE sessions SET state=?, record=?, sha256=? WHERE session_id=?",
                           (session["state"], raw, digest, session["session_id"]))

    def _attempt(self, connection, battle_id):
        row = connection.execute("SELECT * FROM attempts WHERE battle_id=?", (battle_id,)).fetchone()
        if row is None:
            self._invalid("an issued rival match has no committed intent")
        return self._decode(row)

    def _save_attempt(self, connection, attempt):
        raw, digest = _encoded(attempt)
        connection.execute("UPDATE attempts SET record=?, sha256=? WHERE battle_id=?", (raw, digest, attempt["battle_id"]))

    def _completion(self, connection, checkpoint_id):
        row = connection.execute("SELECT * FROM completions WHERE checkpoint_id=?", (checkpoint_id,)).fetchone()
        return None if row is None else self._decode(row)

    def _clears(self, connection, player_id):
        return {row["checkpoint_id"]: row["via"] for row in connection.execute(
            "SELECT checkpoint_id, via FROM clears WHERE player_id=?", (player_id,))}

    def _clear(self, connection, checkpoint_id, player_id, via):
        raw, digest = _encoded(dict(checkpoint_id=checkpoint_id, player_id=player_id, via=via))
        connection.execute("INSERT OR IGNORE INTO clears VALUES (?, ?, ?, ?, ?)", (checkpoint_id, player_id, via, raw, digest))

    # -- trusted host reads ----------------------------------------------------------------------------------

    def claims_battle(self, battle_id):
        _uuid(battle_id, "battle_id")
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM attempts WHERE battle_id=?", (battle_id,)).fetchone()
            if row is not None:
                self._decode(row)
            return row is not None

    def summary(self, player_id):
        """Every checkpoint's world completion and this player's personal pass, in story order."""
        _uuid(player_id, "player_id")
        with self._transaction() as connection:
            clears = self._clears(connection, player_id)
            completed = {row["checkpoint_id"] for row in connection.execute("SELECT checkpoint_id FROM completions")}
        return [dict(checkpoint_id=checkpoint_id, completed=checkpoint_id in completed,
                     cleared=checkpoint_id in clears, via=clears.get(checkpoint_id)) for checkpoint_id in IDS]

    # -- clock and lobby -------------------------------------------------------------------------------------

    def _now(self):
        now = self.clock()
        if (type(now) not in (int, float) or not math.isfinite(now)
                or (self._last_time is not None and now < self._last_time)):
            raise StorageError("rival_clock", "rival clock must be finite and monotonic")
        self._last_time = float(now)
        return float(now)

    @staticmethod
    def _present(checkpoint, roster, presences):
        present = set()
        for player in roster:
            presence = presences.get(player)
            if (type(presence) is dict and presence.get("activity") in PRESENT_ACTIVITIES
                    and (presence.get("map_group"), presence.get("map_number")) in checkpoint.maps):
                present.add(player)
        return frozenset(present)

    def _lobby(self, checkpoint_id, now, present, *, blocked):
        """Recompute the volatile lobby; return the committed roster when the countdown has ended."""
        lobby = self._lobbies[checkpoint_id]
        for player in tuple(lobby.since):
            if player not in present:
                lobby.since.pop(player)
                lobby.votes.pop(player, None)
        for player in present:
            lobby.since.setdefault(player, now)
        if blocked:
            lobby.votes.clear()
            lobby.countdown = None
            lobby.present, lobby.starters = present, ()
            return None
        starters = tuple(sorted(p for p in present if lobby.votes.get(p) == "start"))
        if present != lobby.present or starters != lobby.starters:
            lobby.present, lobby.starters, lobby.changed = present, starters, now
        roster = None
        if len(starters) >= 2 and (set(starters) == present or now - lobby.changed >= self.grace):
            roster = starters
        if roster is None:
            lobby.countdown = None
        elif lobby.countdown is None or lobby.countdown[1] != roster:
            lobby.countdown = (now + self.countdown, roster)
        if lobby.countdown is not None and now >= lobby.countdown[0]:
            roster = lobby.countdown[1]
            lobby.countdown = None
            lobby.votes.clear()
            lobby.starters = ()
            return roster
        return None

    # -- native evidence --------------------------------------------------------------------------------------

    @staticmethod
    def _native(desk, battle_id):
        return None if desk is None else desk._active.get(battle_id) or desk._history.get(battle_id)

    def _evidence(self, match, attempt, desk, results, reservations, admission):
        """(state, winners) of one issued match from durable and volatile native facts."""
        battle_id = attempt["battle_id"]
        result = None if results is None else results.get(battle_id)
        if result is not None:
            if (result["battle_id"] != battle_id or result["mode"] != match.mode
                    or set(result["players"]) != set(match.players) or attempt["canceled"]):
                self._invalid("a released rival battle does not match its committed intent")
            try:
                return "resolved", winners(match, result["players"], result["outcome"])
            except ValueError as error:
                raise StorageError("rival_invalid", str(error)) from error
        if attempt["canceled"]:
            return "void", ()
        terminal = None if reservations is None else reservations.terminal(battle_id)
        if terminal is None and admission is not None:
            terminal = admission.unentered_terminal(battle_id) or admission.terminal(battle_id)
        if terminal is not None and getattr(terminal, "kind", None) == "aborted":
            return "void", ()
        native = self._native(desk, battle_id)
        if (native is None and admission is None and reservations is not None
                and not reservations.contains(battle_id)):
            # Reservations are written before any BIND (BattleDesk.authorize_bind) and, without
            # the provisional-admission ledger, nothing else can hold a core: never held, so void.
            return "void", ()
        if native is not None:
            if native.mode != match.mode or set(native.players) != set(match.players):
                self._invalid("a native battle does not match its committed rival intent")
            if native.state in {"invited", "accepted"}:
                return "invited", ()
            if native.state == "aborted" and admission is None and not native.bind_intent:
                # No BIND was ever authorized, so no ROM can hold this battle.
                return "void", ()
            if native.state in {"prepared", "starting", "running", "finishing", "release_authorized"}:
                return "playing", ()
            return "waiting", ()
        # A committed intent without native or durable evidence (for example after a
        # host restart) is never treated as void automatically.
        return "waiting", ()

    def _reconcile(self, connection, session, roster, desk, results, reservations, admission, now):
        if session["state"] != "active":
            return session
        session = self._settle(connection, session, roster, desk, results, reservations, admission, now)
        unresolved = [m["state"] for m in session["matches"] if m["state"] not in {"resolved", "void", "pending"}]
        if session["state"] == "active" and unresolved and set(unresolved) == {"waiting"}:
            self._stuck_since.setdefault(session["session_id"], now)
        else:
            self._stuck_since.pop(session["session_id"], None)
        return session

    def _settle(self, connection, session, roster, desk, results, reservations, admission, now):
        matches = [self._planned(session, index) for index in range(len(session["matches"]))]
        for index, public in enumerate(session["matches"]):
            if public["attempt"] and public["state"] not in {"resolved", "void"}:
                attempt = self._attempt(connection, public["battle_id"])
                state, won = self._evidence(matches[index], attempt, desk, results, reservations, admission)
                public.update(state=state, winners=list(won))
                if state == "void" and not attempt["canceled"]:
                    attempt["canceled"] = True
                    self._save_attempt(connection, attempt)
            elif public["state"] == "ready":
                # An unissued match is void when a trainer left or nobody asked for it in time.
                since = self._ready_since.setdefault((session["session_id"], index), now)
                if (any(player not in roster for player in matches[index].players)
                        or now - since >= self.ready_timeout):
                    public["state"] = "void"
        if session["format"] in (SINGLES, MULTI):
            state = session["matches"][0]["state"]
            if state == "resolved":
                self._complete(connection, session)
            elif state == "void":
                session["state"] = "canceled"
        else:
            for index, public in enumerate(session["matches"]):
                if public["state"] in {"resolved", "void"}:
                    continue
                if public["state"] == "pending":
                    if all(player in roster for player in matches[index].players):
                        public["state"] = "ready"
                        self._ready_since[(session["session_id"], index)] = now
                    else:
                        public["state"] = "void"  # a trainer is offline: this match is skipped
                        continue
                break
            if all(public["state"] in {"resolved", "void"} for public in session["matches"]):
                if any(public["state"] == "resolved" for public in session["matches"]):
                    self._complete(connection, session)
                else:
                    session["state"] = "canceled"
        self._save_session(connection, session)
        return session

    @staticmethod
    def _planned(session, index):
        public = session["matches"][index]
        return PlannedMatch(index, public["mode"], tuple(tuple(team) for team in public["teams"]))

    def _complete(self, connection, session):
        if self._completion(connection, session["checkpoint_id"]) is not None:
            self._invalid("a rival checkpoint completed twice")
        names = dict(zip(session["players"], session["names"]))
        tally = {player: dict(wins=0, losses=0, draws=0) for player in session["players"]}
        participants = set()
        for public in session["matches"]:
            if public["state"] != "resolved":
                continue
            sides = [tuple(team) for team in public["teams"]]
            participants.update(sides[0] + sides[1])
            for side in sides:
                for player in side:
                    if not public["winners"]:
                        tally[player]["draws"] += 1
                    elif player in public["winners"]:
                        tally[player]["wins"] += 1
                    else:
                        tally[player]["losses"] += 1
        if session["format"] == ROUND_ROBIN:
            best = max(tally[player]["wins"] for player in participants)
            top = sorted(player for player in participants if best and tally[player]["wins"] == best)
        else:
            top = sorted(session["matches"][0]["winners"])
        players = [player for player in session["players"] if player in participants]
        completion = dict(session_id=session["session_id"], format=session["format"], players=players,
                          winners=top, standings=[dict(player_id=player, name=names[player], **tally[player])
                                                  for player in players])
        raw, digest = _encoded(completion)
        connection.execute("INSERT INTO completions VALUES (?, ?, ?, ?)", (session["checkpoint_id"],
                           session["session_id"], raw, digest))
        for player in players:
            self._clear(connection, session["checkpoint_id"], player, "battle")
        session["state"] = "completed"

    # -- the public operation ---------------------------------------------------------------------------------

    def handle(self, actor, request, *, roster, presences, strengths, usable, desk, results, invite,
               reservations=None, admission=None):
        """Outer server authenticates the current lease before this call.

        roster: {player_id: display name} of connected authenticated players.
        presences: {player_id: latest presence or None}. strengths(player) and
        usable(player) read the player's last saved party. invite(match,
        battle_id) is the synchronous trusted Desk invitation sent as ``actor``;
        it is called only after the exact intent has committed here.
        """
        validate_rival_request(request)
        _uuid(actor, "actor")
        operation = request["operation"]
        now = self._now()
        if reservations is None and desk is not None:
            reservations = desk.reservations
        if desk is not None:
            desk.refresh()
        if operation == "status":
            presence = presences.get(actor)
            here = None if type(presence) is not dict else checkpoint_at(presence.get("map_group"), presence.get("map_number"))
            checkpoint_id = None if here is None else here.checkpoint_id
        else:
            checkpoint_id = request["checkpoint_id"]
        issue = None
        with self._transaction() as connection:
            # Every active session is reconciled on each call, so results and
            # disconnects settle even when nobody is standing at that checkpoint.
            for checkpoint in CHECKPOINTS:
                session = self._active(connection, checkpoint.checkpoint_id)
                if session is not None:
                    self._reconcile(connection, session, roster, desk, results, reservations, admission, now)
            for checkpoint in CHECKPOINTS:
                self._advance_lobby(connection, checkpoint, now, roster, presences, strengths, usable)
            if operation == "vote":
                self._vote(connection, actor, checkpoint_id, request["choice"], roster, presences, usable)
                self._advance_lobby(connection, BY_ID[checkpoint_id], now, roster, presences, strengths, usable)
            elif operation == "continue":
                self._continue(connection, actor, checkpoint_id, request["via"], now, roster, presences)
            elif operation == "match":
                issue = self._begin_match(connection, actor, request, roster)
            elif operation == "recover":
                self._recover(connection, actor, request, roster, desk, results, reservations, admission, now)
        if issue is not None:
            self._dispatch(issue, desk, invite, roster, results, reservations, admission, now)
        with self._transaction() as connection:
            if issue is not None:
                session = self._active(connection, checkpoint_id)
                if session is not None:  # the reply shows the invitation the Desk now holds
                    self._reconcile(connection, session, roster, desk, results, reservations, admission, now)
            here = None if checkpoint_id is None else self._view(connection, actor, BY_ID[checkpoint_id], now,
                                                                  roster, presences, usable)
            clears = self._clears(connection, actor)
            completed = {row["checkpoint_id"] for row in connection.execute("SELECT checkpoint_id FROM completions")}
        reply = dict(version=VERSION, operation=operation, here=here, checkpoints=[
            dict(checkpoint_id=cid, completed=cid in completed, cleared=cid in clears, via=clears.get(cid)) for cid in IDS])
        validate_rival_reply(reply, actor, request)
        return reply

    def _advance_lobby(self, connection, checkpoint, now, roster, presences, strengths, usable):
        checkpoint_id = checkpoint.checkpoint_id
        blocked = (self._active(connection, checkpoint_id) is not None
                   or self._completion(connection, checkpoint_id) is not None)
        present = self._present(checkpoint, roster, presences)
        committed = self._lobby(checkpoint_id, now, present, blocked=blocked)
        if committed is None:
            return
        players = [player for player in committed if player in roster and usable(player)]
        if len(players) < 2 or any(self._player_busy(connection, player) for player in players):
            return
        battle_plan = plan(players, {player: int(strengths(player) or 0) for player in players},
                           f"{self.identity['world_id']}:{checkpoint_id}")
        session = dict(session_id=str(uuid4()), checkpoint_id=checkpoint_id, format=battle_plan.format,
                       players=list(battle_plan.players), names=[_printable(roster[p]) for p in battle_plan.players],
                       state="active", matches=[dict(index=m.index, mode=m.mode, teams=[list(t) for t in m.teams],
                       attempt=0, battle_id=None, state="ready" if m.index == 0 else "pending", winners=[])
                       for m in battle_plan.matches])
        raw, digest = _encoded(session)
        connection.execute("INSERT INTO sessions (session_id, checkpoint_id, state, record, sha256) VALUES (?, ?, ?, ?, ?)",
                           (session["session_id"], checkpoint_id, "active", raw, digest))
        self._ready_since[(session["session_id"], 0)] = now

    def _player_busy(self, connection, player):
        for row in connection.execute("SELECT record, sha256 FROM sessions WHERE state='active'"):
            if player in self._decode(row)["players"]:
                return True
        return False

    def _vote(self, connection, actor, checkpoint_id, choice, roster, presences, usable):
        checkpoint = BY_ID[checkpoint_id]
        if self._completion(connection, checkpoint_id) is not None:
            raise ProtocolError("rival_completed", "This rival checkpoint is already complete")
        if self._active(connection, checkpoint_id) is not None:
            raise ProtocolError("rival_battling", "A rival battle is already in progress here")
        if actor not in self._present(checkpoint, roster, presences):
            raise ProtocolError("rival_not_present", "Stand at the rival checkpoint to choose")
        if choice == "start" and not usable(actor):
            raise ProtocolError("rival_no_usable_pokemon", "Heal a Pokemon before a rival battle")
        self._lobbies[checkpoint_id].votes[actor] = choice

    def _continue(self, connection, actor, checkpoint_id, via, now, roster, presences):
        if checkpoint_id in self._clears(connection, actor):
            return  # a repeated pass changes nothing
        completed = self._completion(connection, checkpoint_id) is not None
        if via == "catch_up":
            if not completed:
                raise ProtocolError("rival_not_completed", "The world has not completed this checkpoint yet")
        elif not self._solo_allowed(connection, actor, checkpoint_id, now, roster, presences, completed):
            raise ProtocolError("rival_solo_unavailable", "Another rival player can still join you here")
        self._clear(connection, checkpoint_id, actor, via)

    def _solo_allowed(self, connection, actor, checkpoint_id, now, roster, presences, completed):
        if completed:
            return False
        present = self._present(BY_ID[checkpoint_id], roster, presences)
        active = self._active(connection, checkpoint_id)
        if active is not None:
            # A battle the native layer still holds (uncertain after a restart, or waiting for a player
            # who never returns) must not strand the others at a gate: after solo_wait they may pass
            # personally. The held battle itself is never voided or completed by this.
            stuck = self._stuck_since.get(active["session_id"])
            return (actor in present and actor not in active["players"]
                    and stuck is not None and now - stuck >= self.solo_wait)
        if present != {actor}:
            return False
        alone_online = set(roster) <= {actor}
        waited = now - self._lobbies[checkpoint_id].since.get(actor, now) >= self.solo_wait
        return alone_online or waited

    def _current_match(self, connection, actor, request):
        session = self._active(connection, request["checkpoint_id"])
        if session is None or session["session_id"] != request["session_id"]:
            raise ProtocolError("rival_changed", "Refresh the rival checkpoint first")
        public = session["matches"][request["match"]] if request["match"] < len(session["matches"]) else None
        if public is None or actor not in sum(public["teams"], []):
            raise ProtocolError("rival_not_participant", "Only this match's trainers can start it")
        return session, public

    def _begin_match(self, connection, actor, request, roster):
        session, public = self._current_match(connection, actor, request)
        if request["attempt"] == public["attempt"] - 1:
            return None  # a lost reply's retry returns the already issued match
        if request["attempt"] != public["attempt"] or public["state"] != "ready":
            raise ProtocolError("rival_not_ready", "This rival match is not ready")
        match = self._planned(session, public["index"])
        if any(player not in roster for player in match.players):
            raise ProtocolError("player_offline", "All of this match's trainers must be connected")
        issue = dict(checkpoint_id=session["checkpoint_id"], session_id=session["session_id"], match=match.index,
                     attempt=public["attempt"] + 1, battle_id=str(uuid4()), sender=actor,
                     mode=match.mode, teams=[list(t) for t in match.teams], canceled=False, issuance="pending")
        raw, digest = _encoded(issue)
        connection.execute("INSERT INTO attempts VALUES (?, ?, ?, ?, ?, ?)", (issue["battle_id"], issue["session_id"],
                           issue["match"], issue["attempt"], raw, digest))
        public.update(attempt=issue["attempt"], battle_id=issue["battle_id"], state="waiting", winners=[])
        self._save_session(connection, session)
        return issue

    def _dispatch(self, issue, desk, invite, roster, results, reservations, admission, now):
        with self._transaction() as connection:
            attempt = self._attempt(connection, issue["battle_id"])
            if attempt != issue:
                self._invalid()
            attempt["issuance"] = "dispatching"
            self._save_attempt(connection, attempt)
        match = PlannedMatch(issue["match"], issue["mode"], tuple(tuple(team) for team in issue["teams"]))
        try:
            invite(match, issue["battle_id"])
        except Exception:
            # No await runs between the commit and this callback; a synchronous
            # refusal before Desk insertion cannot hold any core.
            if self._native(desk, issue["battle_id"]) is None:
                with self._transaction() as connection:
                    attempt = self._attempt(connection, issue["battle_id"])
                    attempt["canceled"] = True
                    self._save_attempt(connection, attempt)
                    session = self._session_row(connection, issue["session_id"])
                    self._reconcile(connection, session, roster, desk, results, reservations, admission, now)
            raise

    def _recover(self, connection, actor, request, roster, desk, results, reservations, admission, now):
        session, public = self._current_match(connection, actor, request)
        if public["battle_id"] != request["battle_id"] or public["attempt"] != request["attempt"]:
            raise ProtocolError("rival_changed", "Recovery must name the exact original match")
        if public["state"] != "waiting":
            return
        attempt = self._attempt(connection, public["battle_id"])
        if attempt.get("issuance") == "pending":
            if (self._native(desk, public["battle_id"]) is not None
                    or results is not None and results.get(public["battle_id"]) is not None
                    or reservations is not None and reservations.contains(public["battle_id"])):
                self._invalid("a pending rival intent already reached the native layer")
            attempt["canceled"] = True  # committed before dispatch: affirmative proof it never ran
            self._save_attempt(connection, attempt)
        elif admission is not None:
            admission.unentered_terminal(public["battle_id"], revoke=True)
        self._reconcile(connection, session, roster, desk, results, reservations, admission, now)

    # -- the actor's view -------------------------------------------------------------------------------------

    def _view(self, connection, actor, checkpoint, now, roster, presences, usable):
        checkpoint_id = checkpoint.checkpoint_id
        lobby = self._lobbies[checkpoint_id]
        completion = self._completion(connection, checkpoint_id)
        session = self._active(connection, checkpoint_id)
        if session is None and completion is not None:
            session = self._session_row(connection, completion["session_id"])
        clears = self._clears(connection, actor)
        present = sorted(self._present(checkpoint, roster, presences))
        others_online = len([player for player in roster if player != actor])
        if completion is not None:
            state = "completed"
        elif session is not None and session["state"] == "active":
            state = "battling"
        elif lobby.countdown is not None:
            state = "countdown"
        else:
            state = "open"
        is_present = actor in present
        lobby_open = state in {"open", "countdown"}
        can_start = lobby_open and is_present and usable(actor)
        solo = state in {"open", "battling"} and checkpoint_id not in clears and self._solo_allowed(
            connection, actor, checkpoint_id, now, roster, presences, False)
        catch_up = completion is not None and checkpoint_id not in clears
        countdown_ms = None if state != "countdown" else max(0, int((lobby.countdown[0] - now) * 1000))
        grace_ms = None
        starters = [p for p in present if lobby.votes.get(p) == "start"]
        if lobby_open and len(starters) >= 2 and len(starters) < len(present):
            grace_ms = max(0, int((lobby.changed + self.grace - now) * 1000))
        message = self._message(state, actor, session, completion, clears, checkpoint_id, present, starters,
                                countdown_ms, grace_ms, catch_up)
        return dict(checkpoint_id=checkpoint_id, title=checkpoint.title, mandatory=checkpoint.mandatory,
                    declinable=checkpoint.declinable, state=state, message=message,
                    present=[dict(player_id=p, name=_printable(roster.get(p, "Trainer")), vote=lobby.votes.get(p))
                             for p in present],
                    others_online=others_online, countdown_ms=countdown_ms, grace_ms=grace_ms,
                    can_start=can_start, can_wait=lobby_open and is_present, can_solo=solo, can_catch_up=catch_up,
                    session=None if session is None else {key: session[key] for key in
                        ("session_id", "format", "players", "names", "state", "matches")},
                    completion=completion, cleared=checkpoint_id in clears, via=clears.get(checkpoint_id))

    @staticmethod
    def _message(state, actor, session, completion, clears, checkpoint_id, present, starters, countdown_ms,
                 grace_ms, catch_up):
        if state == "completed":
            if catch_up:
                return "Completed - you may continue"
            if actor in completion["winners"]:
                return "You won the rival battle!"
            if actor in completion["players"] and not completion["winners"]:
                return "The rival battle was a draw"
            if actor in completion["players"]:
                return "Good battle! The story goes on"
            return "Rival checkpoint complete"
        if state == "battling":
            for public in session["matches"]:
                if actor in sum(public["teams"], []) and public["state"] == "ready":
                    return "Your rival battle is ready"
                if actor in sum(public["teams"], []) and public["state"] == "invited":
                    return "Accept it in Challenges"
                if actor in sum(public["teams"], []) and public["state"] == "waiting":
                    return "Battle waiting; try Recover"
            return "Rival battle in progress"
        if state == "countdown":
            return f"Battle starts in {(countdown_ms + 999) // 1000}s"
        if checkpoint_id in clears:
            return "You passed; others may battle"
        if grace_ms is not None and actor in starters:
            return f"Starting without waiters {(grace_ms + 999) // 1000}s"
        if len(present) < 2:
            return "Waiting for rival players..."
        return "Start now or wait for others?"
