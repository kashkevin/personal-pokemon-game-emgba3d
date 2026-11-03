"""Eight-place Championships with computer trainers (step 18; docs/championships-eight.md).

The owner's choice of 2026-11-03 (docs/owner-decisions.md #32): Battle Frontier trainers under the same entry rules fill
the places the world's players leave empty; a player against one is a normal battle in that player's own game; two
players still use the existing challenge flow; when two computer trainers meet the higher-ranked one goes through
without a battle; the bracket is 8 -> 4 -> final.

* **Places.** Two to four players (the proposer first, then the order they were proposed in) hold the first places; the
  Battle Tower: Legends floor trainers (tower_floors.py, the solo trainer of each floor, every Pokemon at the floor's
  level) fill the rest. Only trainers whose team passes the bracket's entry rule (frontier_rules.check_party, the rule in
  force when the bracket was proposed, kept with it) may take a place; their floors are spread from the strongest
  player's best level down to the weakest player's, the nearest eligible floor to each, and ranked by floor (higher is
  higher). Quarterfinals 1v8, 4v5, 2v7, 3v6 (seed numbers from 1), then the semifinals, then the final.
* **Two players** meet exactly as in the four players' bracket (championship.py): the host records the issued match
  before inviting, the native challenge's own acceptance, entry, recovery and release, and only the released result
  advances the bracket (the reconcile below is championship.Championships._reconcile_match itself).
* **A player and a computer trainer**: the host records a ticket before answering, and the player's game fights the
  floor's solo trainer with the Battle Tower's solo command in mode 2 (menu_mailbox.TowerCommand; engine
  src/tower_legends.c): healed afterwards, held items back, no money, no whiteout, no experience unless the host asks
  (EXPERIENCE). The game reports the battle as world action 7 for that ticket (tower_service.TowerService.result routes
  it here): started, then won / lost / drew, kept in its save until the host's Tower state word clears it; or refused.
  A command never started for 120 s is void (ask again); a started match that never reports is a loss once its player
  asks for it again at least 15 s after their game connected, or after 24 hours (the Tower's rule); a draw is played
  again.
* **Two computer trainers** never battle: the higher seed goes on as soon as the bracket is active and both are known.

The sidecar (``<world>.championships8.sqlite3``) is its own file: a build that only knows the four players' bracket never
opens it (and so never refuses its world over it), and the four players' sidecar stays exactly as it was - its brackets
are still played to the end and counted here (``legacy``). One bracket at a time per world, over both files.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import secrets
import time
from typing import Callable
from uuid import uuid4

from .championship import MAX_RECORD_BYTES, Championships, _encoded, _json
from .championship8_protocol import (FORMATS, HISTORY_LIMIT, MAX_PLAYERS, MIN_PLAYERS, RULES, VERSION, expected_seeds,
                                     four_player_view, match_kind, match_players, summary_of,
                                     validate_championship_reply, validate_championship_request,
                                     validate_championship_view)
from .championship_protocol import VERSION as FOUR_VERSION
from .protocol import MAX_COUNTER, ProtocolError, validate_identity
from .storage import StorageError
from .team_protocol import _uuid

SCOPE = "durable-eight-place-championships-v1"
SEATS = 8
ISSUED_SECONDS = 120          # a computer match's command the game never started is void after this (the Tower's)
STARTED_SECONDS = 24 * 3600   # a started computer match that never reports is a loss after this
CONNECTION_SECONDS = 15       # ... or once its player asks for it again this long after their game connected
EXPERIENCE = False            # the owner's default to confirm: a match against a computer trainer gives no experience
OPEN, SETTLED = ("issued", "started"), ("won", "lost", "drew", "forfeit")
_SCHEMA = {
    "metadata": "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "brackets": """CREATE TABLE brackets (sequence INTEGER PRIMARY KEY,
        championship_id TEXT NOT NULL UNIQUE, state TEXT NOT NULL, players TEXT NOT NULL,
        record TEXT NOT NULL, sha256 TEXT NOT NULL)""",
    "bracket_states": "CREATE INDEX bracket_states ON brackets (state, sequence)",
    "attempts": """CREATE TABLE attempts (battle_id TEXT PRIMARY KEY,
        championship_id TEXT NOT NULL, round INTEGER NOT NULL, attempt INTEGER NOT NULL, ticket INTEGER UNIQUE,
        record TEXT NOT NULL, sha256 TEXT NOT NULL,
        UNIQUE (championship_id, round, attempt))""",
}
_NATIVE_KEYS = frozenset({"championship_id", "round", "attempt", "battle_id", "players", "sender", "native_generation",
                          "canceled"})
_COMPUTER_KEYS = frozenset({"championship_id", "round", "attempt", "battle_id", "kind", "player", "seed", "opponent",
                            "floor", "ticket", "stage", "flags", "state", "reason", "issued", "started", "settled"})


@dataclass(frozen=True)
class ComputerContext:
    """What the host gives a computer match (server.WorldServer._championship_computers_context): the Tower's floor data
    (tower_data.TowerData: the trainers and the table hash the game checks), why the player's game cannot take a Tower
    battle now (None: it can; one Tower battle at a time - a Tower floor, a Duo, an unsettled result), whether the Tower
    already issued a ticket number, how long the player's game has been connected (None: not connected), and whether
    the battle gives experience."""
    data: object
    busy: Callable[[str], str | None]
    taken: Callable[[int], bool]
    connected_for: Callable[[str], float | None]
    experience: bool = EXPERIENCE


def computer_places(data, rule, strengths, count, check):
    """The ``count`` floors whose solo trainers fill the computer places, highest floor first: only trainers whose team
    passes ``rule`` (``check(rule, members)`` is None: frontier_rules.check_party), the nearest such floor to each level
    of an even spread from the strongest player's best level down to the weakest's (a floor's level is its number), a
    floor once. ``strengths``: each player's best level (0 when unknown: level 1)."""
    from .frontier_rules import PartyMember
    eligible = []
    for entry in data.floors:
        members = [PartyMember(mon["speciesId"], mon["level"], mon.get("itemId") or 0) for mon in entry["solo"]["mons"]]
        if check(rule, members) is None:
            eligible.append(entry["floor"])
    if len(eligible) < count:
        raise ProtocolError("championship_unavailable", "Too few computer trainers fit the rule")
    high, low = max(max(strengths), 1), max(min(strengths), 1)
    chosen = []
    for index in range(count):
        target = high - (high - low) * index / max(1, count - 1)
        floor = min((f for f in eligible if f not in chosen), key=lambda f: (abs(f - target), f > target, -f))
        chosen.append(floor)
    return sorted(chosen, reverse=True)


def _computer_entrant(data, seed, floor):
    from .tower_data import display_class, display_name
    solo = data.floor(floor)["solo"]
    name = (display_name(solo.get("name")) or "Trainer")[:24]
    title = (display_class(solo.get("class")) or "Trainer")[:24]
    return dict(seed=seed, player=None, name=name, title=title, floor=floor)


class EightChampionships(Championships):
    """World-owned sidecar for eight-place brackets, over the four players' sidecar (``legacy``, a
    championship.Championships or None). Every operation runs synchronously on the host loop."""

    SCHEMA = _SCHEMA

    def __init__(self, path, *, world_id, build_id, ruleset_id, legacy=None, clock=time.time):
        from pathlib import Path
        _uuid(world_id, "world_id")
        validate_identity(build_id, "build_id")
        validate_identity(ruleset_id, "ruleset_id")
        self.path = Path(path).resolve()
        self.identity = dict(format=SCOPE, world_id=world_id, build_id=build_id, ruleset_id=ruleset_id)
        self.legacy = legacy
        self._now = clock
        self._statistics = {}
        self._statistics_valid = False
        self._statistics_changes = set()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction(initialize=not self.path.exists()) as connection:
            brackets = {}
            current = 0
            for row in connection.execute("SELECT * FROM brackets"):
                view = self._bracket(row)
                brackets[view["championship_id"]] = view
                current += view["state"] in {"proposed", "active"}
            if current > 1:
                self._invalid()
            latest = {}
            for row in connection.execute("SELECT * FROM attempts ORDER BY attempt"):
                attempt = self._attempt(row)
                view = brackets.get(attempt["championship_id"])
                if view is None or view["state"] == "proposed" or attempt["round"] >= len(view["matches"]):
                    self._invalid()
                match = view["matches"][attempt["round"]]
                self._check_attempt_fits(view, match, attempt)
                key = (attempt["championship_id"], attempt["round"])
                if attempt["attempt"] != latest.get(key, 0) + 1 or attempt["attempt"] > match["attempt"]:
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

    # ------------------------------------------------------------------ records
    def _fingerprint(self, value):
        return hashlib.sha256(_json(dict(identity=self.identity, **{key: value[key] for key in
            ("championship_id", "generation", "sender", "players", "names", "rule", "entrants")})).encode("ascii")).hexdigest()

    def _bracket(self, row):
        value = self._decode(row)
        try:
            validate_championship_view(value, value["sender"])
            if (value["format"] != SEATS or value["championship_id"] != row["championship_id"]
                    or value["state"] != row["state"] or _json(value["players"]) != row["players"]
                    or value["fingerprint"] != self._fingerprint(value)):
                self._invalid()
        except (ProtocolError, KeyError, TypeError) as error:
            raise StorageError("championship_invalid", "Championship bracket is malformed") from error
        return value

    def _attempt(self, row):
        value = self._decode(row)
        try:
            if type(value) is not dict:
                self._invalid()
            if value.get("kind") == "computer":
                self._check_computer_attempt(value)
                if row["ticket"] != value["ticket"]:
                    self._invalid()
            else:
                if set(value) not in (_NATIVE_KEYS, _NATIVE_KEYS | {"issuance"}) or row["ticket"] is not None:
                    self._invalid()
                if "issuance" in value and (value["issuance"] not in {"pending", "dispatching"}
                        or value["issuance"] == "pending" and value["native_generation"] is not None):
                    self._invalid()
                for key in ("championship_id", "battle_id", "sender"):
                    _uuid(value[key], key)
                if value["native_generation"] is not None:
                    _uuid(value["native_generation"], "native_generation")
                if (type(value["round"]) is not int or not 0 <= value["round"] < len(FORMATS[SEATS]["stages"])
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

    def _check_computer_attempt(self, value):
        if set(value) != _COMPUTER_KEYS:
            self._invalid()
        for key in ("championship_id", "battle_id", "player"):
            _uuid(value[key], key)
        if (type(value["round"]) is not int or not 0 <= value["round"] < len(FORMATS[SEATS]["stages"])
                or type(value["attempt"]) is not int or not 1 <= value["attempt"] <= MAX_COUNTER
                or type(value["seed"]) is not int or type(value["opponent"]) is not int
                or not 0 <= value["seed"] < SEATS or not 0 <= value["opponent"] < SEATS
                or type(value["floor"]) is not int or not 1 <= value["floor"] <= 100
                or type(value["ticket"]) is not int or not 0 < value["ticket"] <= 0xFFFFFFFF or not value["ticket"] & 0xFF
                or value["stage"] != FORMATS[SEATS]["stages"][value["round"]] or value["flags"] not in (0, 1)
                or value["state"] not in OPEN + SETTLED + ("void",)
                or value["reason"] not in (None, "refused", "expired")
                or (value["reason"] is not None) != (value["state"] == "void")
                or type(value["issued"]) is not int or not all(value[key] is None or type(value[key]) is int
                                                              for key in ("started", "settled"))
                or (value["settled"] is None) != (value["state"] in OPEN)):
            self._invalid()

    def _check_attempt_fits(self, view, match, attempt):
        entrants = view["entrants"]
        if match["kind"] == "computer" and attempt.get("kind") == "computer":
            human = next(seed for seed in match["seeds"] if entrants[seed]["player"] is not None)
            computer = next(seed for seed in match["seeds"] if entrants[seed]["player"] is None)
            if (attempt["player"] != entrants[human]["player"] or attempt["seed"] != human
                    or attempt["opponent"] != computer or attempt["floor"] != entrants[computer]["floor"]):
                self._invalid()
            if attempt["attempt"] == match["attempt"] and attempt["ticket"] != match["ticket"]:
                self._invalid()
        elif match["kind"] == "players" and attempt.get("kind") is None:
            if set(attempt["players"]) != set(match_players(entrants, match)):
                self._invalid()
        else:
            self._invalid()

    def _save(self, connection, view):
        validate_championship_view(view, view["sender"])
        raw, digest = _encoded(view)
        changed = connection.execute("UPDATE brackets SET state=?, record=?, sha256=? WHERE championship_id=? AND sha256<>?",
                                     (view["state"], raw, digest, view["championship_id"], digest))
        if changed.rowcount:
            self._statistics_changes.add(connection)

    @staticmethod
    def _statistics_from_views(views):
        statistics = {}
        for view in views:
            if set(view["consent"]) != set(view["players"]):
                continue
            champion = None if view["champion"] is None else view["entrants"][view["champion"]]["player"]
            for actor in view["players"]:
                counts = statistics.setdefault(actor, dict(entries=0, completed=0, wins=0))
                counts["entries"] += 1
                if view["state"] == "completed":
                    counts["completed"] += 1
                    counts["wins"] += champion == actor
        return statistics

    def statistics(self, actor):
        """Entries, completed brackets and wins (the Trainer Card), the four players' brackets counted too."""
        own = super().statistics(actor)
        if self.legacy is not None:
            older = self.legacy.statistics(actor)
            own = {key: own[key] + older[key] for key in own}
        return own

    def claims_battle(self, battle_id):
        return super().claims_battle(battle_id) or (self.legacy is not None and self.legacy.claims_battle(battle_id))

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

    def _attempt_of(self, connection, battle_id):
        row = connection.execute("SELECT * FROM attempts WHERE battle_id=?", (battle_id,)).fetchone()
        if row is None:
            self._invalid()
        return self._attempt(row)

    # ---------------------------------------------------------------- reconcile
    def _reconcile(self, connection, view, desk, results, reservations, admission):
        """Every match's state from the durable evidence alone, in bracket order (a later match's places follow its
        feeders' winners); two computer trainers' match is decided at once; the final decides the champion."""
        if view["state"] != "active":
            return
        entrants = view["entrants"]
        for index, match in enumerate(view["matches"]):
            seeds = expected_seeds(view, index)
            if match["seeds"] != seeds:
                if match["seeds"] or match["attempt"]:
                    self._invalid()          # a settled feeder never changes its winner
                match.update(seeds=seeds, kind=match_kind(entrants, seeds), state="ready" if seeds else "blocked")
            if match["kind"] == "auto" and match["state"] == "ready":
                match.update(state="won", winner=min(match["seeds"]))
            elif match["kind"] == "players" and match["attempt"]:
                seat = {entrants[seed]["player"]: seed for seed in match["seeds"]}
                shim = dict(players=match_players(entrants, match), attempt=match["attempt"], battle_id=match["battle_id"],
                            state=match["state"], winner=None if match["winner"] is None else entrants[match["winner"]]["player"])
                self._reconcile_match(connection, shim, desk, results, reservations, admission)
                match.update(state=shim["state"], winner=None if shim["winner"] is None else seat[shim["winner"]])
            elif match["kind"] == "computer" and match["attempt"]:
                self._reconcile_computer(connection, match)
        final = view["matches"][-1]
        if final["state"] == "won":
            view.update(state="completed", champion=final["winner"])
        elif set(view["cancel_consent"]) == set(view["players"]) and all(
                match["state"] in {"blocked", "ready", "draw", "won", "canceled"} for match in view["matches"]):
            view["state"] = "canceled"
        self._save(connection, view)

    def _reconcile_computer(self, connection, match):
        """A computer match's current attempt: what time decided (a command never started for ISSUED_SECONDS is void; a
        started match silent for STARTED_SECONDS is a loss), then the match's state from its attempt."""
        attempt = self._attempt_of(connection, match["battle_id"])
        now = int(self._now())
        if attempt["state"] == "issued" and now - attempt["issued"] >= ISSUED_SECONDS:
            attempt.update(state="void", reason="expired", settled=now)
        elif attempt["state"] == "started" and now - (attempt["started"] or attempt["issued"]) >= STARTED_SECONDS:
            attempt.update(state="forfeit", settled=now)
        self._save_attempt(connection, attempt)
        state = attempt["state"]
        if state in ("won", "lost", "forfeit"):
            match.update(state="won", winner=attempt["seed"] if state == "won" else attempt["opponent"])
        else:
            match.update(state={"issued": "invited", "started": "playing", "drew": "draw", "void": "canceled"}[state],
                         winner=None)

    # -------------------------------------------------------------- operations
    def _recover_issue(self, connection, view, request, actor, desk, results, reservations, admission):
        match = view["matches"][request["round"]]
        if (match["kind"] != "players" or actor not in match_players(view["entrants"], match)
                or request["attempt"] != match["attempt"] or request["battle_id"] != match["battle_id"]):
            raise ProtocolError("championship_changed", "Recovery must name the exact original match")
        if view["state"] != "active" or match["state"] != "waiting":
            return  # An exact retry may already be canceled or have a verified result.
        attempt = self._attempt_of(connection, match["battle_id"])
        if attempt.get("issuance") == "pending":
            if (self._native(desk, match["battle_id"]) is not None
                    or results is not None and results.get(match["battle_id"]) is not None
                    or reservations is not None and reservations.contains(match["battle_id"])
                    or admission is not None and admission.has_consent(match["battle_id"])):
                self._invalid()
            attempt["canceled"] = True
            self._save_attempt(connection, attempt)
        elif admission is not None:
            admission.unentered_terminal(match["battle_id"], revoke=True)
        self._reconcile(connection, view, desk, results, reservations, admission)

    def _fresh_ticket(self, connection, context):
        """A ticket number nobody holds: random (a database restored or replaced never reuses one a save still holds),
        never with a zero low byte (the game's Tower state word names a ticket by its low byte), not the Tower's."""
        while True:
            number = secrets.randbits(32)
            if (number & 0xFF and not context.taken(number)
                    and connection.execute("SELECT 1 FROM attempts WHERE ticket=?", (number,)).fetchone() is None):
                return number

    def _computer_match(self, connection, view, match, request, actor, eligibility, context):
        """A player's ask for their match against a computer trainer: a new ticket and the command for their game, the
        same command again while it has not started, the forfeit of a started match that never reported, or nothing."""
        entrants = view["entrants"]
        retry = request["attempt"] in (match["attempt"] - 1, match["attempt"])
        if match["attempt"] and match["state"] in ("invited", "playing") and retry:
            attempt = self._attempt_of(connection, match["battle_id"])
            if match["state"] == "invited":
                # The answer may have been lost, or the game never took it: the same ticket again, its 120 s renewed.
                attempt["issued"] = int(self._now())
                self._save_attempt(connection, attempt)
                return self._command(attempt, context)
            connected = context.connected_for(actor) if context is not None else None
            if connected is None or connected < CONNECTION_SECONDS:
                raise ProtocolError("championship_result_pending", "Waiting for the match's result")
            attempt.update(state="forfeit", settled=int(self._now()))   # started, never reported: a loss
            self._save_attempt(connection, attempt)
            match.update(state="won", winner=attempt["opponent"])
            return None
        if request["attempt"] != match["attempt"] or match["state"] not in ("ready", "draw", "canceled"):
            if not match["attempt"] and request["attempt"]:
                raise ProtocolError("championship_changed", "Refresh the latest match attempt first")
            return None
        if view["cancel_consent"]:
            raise ProtocolError("championship_cancel_pending", "Resolve the Championship cancellation before another match")
        if context is None or match["attempt"] >= MAX_COUNTER:
            raise ProtocolError("championship_unavailable", "A computer match needs the current game")
        busy = context.busy(actor)
        if busy is not None:
            raise ProtocolError("championship_busy", busy)
        if eligibility is not None:
            eligibility([actor], view["rule"])
        human = next(seed for seed in match["seeds"] if entrants[seed]["player"] is not None)
        computer = next(seed for seed in match["seeds"] if entrants[seed]["player"] is None)
        number = self._fresh_ticket(connection, context)
        attempt = dict(championship_id=view["championship_id"], round=match["round"], attempt=match["attempt"] + 1,
                       battle_id=str(uuid4()), kind="computer", player=actor, seed=human, opponent=computer,
                       floor=entrants[computer]["floor"], ticket=number, stage=match["stage"],
                       flags=int(bool(context.experience)), state="issued", reason=None, issued=int(self._now()),
                       started=None, settled=None)
        raw, digest = _encoded(attempt)
        connection.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,?)", (attempt["battle_id"], attempt["championship_id"],
                           attempt["round"], attempt["attempt"], number, raw, digest))
        match.update(attempt=attempt["attempt"], battle_id=attempt["battle_id"], ticket=number, state="invited",
                     winner=None)
        return self._command(attempt, context)

    @staticmethod
    def _command(attempt, context):
        return dict(ticket=attempt["ticket"], floor=attempt["floor"], table_hash=context.data.table_hash,
                    round=attempt["stage"], flags=attempt["flags"])

    def handle(self, actor, request, *, roster, desk, results, invite, reservations=None, admission=None,
               eligibility=None, rule="open", strengths=None, computers=None, legacy_eligibility=None):
        """The Championship extension of the battle pending RPC; the outer server authenticates the current lease first.

        A version 1 request is the four players' bracket of before (``legacy``, unchanged). Version 2: ``invite`` (the
        native challenge, trusted, synchronous) is called only after an exact intent has committed here; ``eligibility``
        (players, rule) raises ProtocolError when a saved party may not enter under the rule; ``rule`` is the entry rule in
        force now (kept by a new bracket); ``strengths`` (player) is a player's best level; ``computers`` the
        ComputerContext, or None when the host's game cannot fight a computer match (then a Championship is the four
        players' bracket); ``legacy_eligibility`` (players) is the four players' bracket's own check (today's rule, only
        when the host has Frontier rules), exactly as before."""
        if type(request) is dict and request.get("version") == FOUR_VERSION:
            if self.legacy is None:
                raise ProtocolError("championship_disabled", "This host has not enabled Championships")
            if request.get("operation") == "create" and self._has_current():
                raise ProtocolError("championship_busy", "Finish or cancel the world's current Championship first")
            return self.legacy.handle(actor, request, roster=roster, desk=desk, results=results, invite=invite,
                                      reservations=reservations, admission=admission, eligibility=legacy_eligibility)
        validate_championship_request(request)
        operation = request["operation"]
        if reservations is None and desk is not None:
            reservations = desk.reservations
        legacy_view = self._legacy_current(actor, desk, results, reservations, admission)
        if legacy_view is not None and operation not in {"status", "history"} and (
                operation != "create" and request["championship_id"] == legacy_view["championship_id"]):
            return self._legacy_operation(actor, request, legacy_view, roster=roster, desk=desk, results=results,
                                          invite=invite, reservations=reservations, admission=admission,
                                          eligibility=legacy_eligibility)
        if operation == "create" and computers is None:
            if len(request["players"]) != 4 or self.legacy is None:
                raise ProtocolError("championship_unavailable", "Computer trainers need the current game")
            if self._has_current():
                raise ProtocolError("championship_busy", "Finish or cancel the world's current Championship first")
            return self._legacy_operation(actor, request, None, roster=roster, desk=desk, results=results, invite=invite,
                                          reservations=reservations, admission=admission, eligibility=legacy_eligibility)
        if desk is not None:
            desk.refresh()
        issue, command = None, None
        with self._transaction() as connection:
            current = self._current(connection)
            if current is not None:
                self._reconcile(connection, current, desk, results, reservations, admission)
            if operation in {"status", "history"}:
                view = current if current is not None and actor in current["players"] else None
                if view is None and legacy_view is not None:
                    view = four_player_view(legacy_view)
            elif operation == "create":
                view = self._create(connection, actor, request, current, legacy_view, roster, desk, eligibility, rule,
                                    strengths, computers)
            else:
                view = self._target(connection, request, actor)
                self._reconcile(connection, view, desk, results, reservations, admission)
                if operation == "accept" and view["state"] == "proposed":
                    if eligibility is not None and actor not in view["consent"]:
                        eligibility([actor], view["rule"])
                    view["consent"] = sorted(set(view["consent"]) | {actor})
                    if set(view["consent"]) == set(view["players"]):
                        view["state"] = "active"
                        self._reconcile(connection, view, desk, results, reservations, admission)
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
                    if actor not in match_players(view["entrants"], match):
                        raise ProtocolError("championship_not_participant", "Only the assigned players can request this match")
                    if view["state"] != "active":
                        if view["state"] == "proposed":
                            raise ProtocolError("championship_not_ready", "Every player must accept the bracket first")
                    elif match["kind"] == "computer":
                        command = self._computer_match(connection, view, match, request, actor, eligibility, computers)
                        self._reconcile(connection, view, desk, results, reservations, admission)
                    else:
                        issue = self._players_match(connection, view, match, request, actor, desk, eligibility)
                self._save(connection, view)
        if issue is not None:
            self._dispatch(issue, actor, desk, invite)
            with self._transaction() as connection:
                view = self._target(connection, request, actor)
                self._reconcile(connection, view, desk, results, reservations, admission)
        reply = dict(version=VERSION, operation=operation, current=view, history=self._history(actor, operation))
        if command is not None:
            reply["command"] = command
        validate_championship_reply(reply, actor, request)
        return reply

    def _create(self, connection, actor, request, current, legacy_view, roster, desk, eligibility, rule, strengths,
                computers):
        players = list(request["players"])
        if players[0] != actor:
            raise ProtocolError("championship_invalid", "The proposing player must be the first seed")
        previous = connection.execute("SELECT * FROM brackets WHERE championship_id=?",
                                      (request["championship_id"],)).fetchone()
        if previous is not None:
            view = self._bracket(previous)
            if view["players"] != players or view["sender"] != actor:
                raise ProtocolError("championship_conflict", "Championship ID already names another bracket")
            return view
        if current is not None or legacy_view is not None:
            raise ProtocolError("championship_busy", "Finish or cancel the world's current Championship first")
        if desk is None:
            raise ProtocolError("battle_disabled", "This host has disabled new battle challenges")
        if not MIN_PLAYERS <= len(players) <= MAX_PLAYERS or not set(players) <= set(roster):
            raise ProtocolError("championship_roster_changed", "Every proposed player must still be connected")
        if rule not in RULES:
            raise ProtocolError("championship_unavailable", "The entry rule is unknown")
        if eligibility is not None:
            eligibility(players, rule)
        from .frontier_rules import check_party
        levels = [strengths(player) if strengths is not None else 0 for player in players]
        floors = computer_places(computers.data, rule, levels, SEATS - len(players), check_party)
        entrants = [dict(seed=seed, player=player, name=roster[player][:24], title=None, floor=None)
                    for seed, player in enumerate(players)]
        entrants += [_computer_entrant(computers.data, len(players) + index, floor) for index, floor in enumerate(floors)]
        view = dict(format=SEATS, championship_id=request["championship_id"], generation=str(uuid4()), sender=actor,
                    players=players, names=[entrant["name"] for entrant in entrants[:len(players)]], rule=rule,
                    entrants=entrants, state="proposed", consent=[actor], cancel_consent=[], champion=None, matches=[])
        shape = FORMATS[SEATS]
        for index, stage in enumerate(shape["stages"]):
            seeds = list(shape["pairs"][index]) if index < len(shape["pairs"]) else []
            view["matches"].append(dict(round=index, stage=stage, seeds=seeds, kind=match_kind(entrants, seeds),
                                        attempt=0, battle_id=None, ticket=None, state="ready" if seeds else "blocked",
                                        winner=None))
        view["fingerprint"] = self._fingerprint(view)
        validate_championship_view(view, actor)
        raw, digest = _encoded(view)
        connection.execute("INSERT INTO brackets (championship_id,state,players,record,sha256) VALUES (?,?,?,?,?)",
                           (view["championship_id"], view["state"], _json(players), raw, digest))
        self._statistics_changes.add(connection)
        return view

    def _players_match(self, connection, view, match, request, actor, desk, eligibility):
        """Two players' match: exactly the four players' bracket's issue (an intent committed before the invitation)."""
        if request["attempt"] not in {match["attempt"], match["attempt"] - 1}:
            raise ProtocolError("championship_changed", "Refresh the latest match attempt first")
        retry = request["attempt"] == match["attempt"] - 1
        if retry or match["state"] not in {"ready", "draw", "canceled"}:
            return None
        if view["cancel_consent"]:
            raise ProtocolError("championship_cancel_pending", "Resolve the Championship cancellation before another match")
        if desk is None or match["attempt"] >= MAX_COUNTER:
            raise ProtocolError("championship_unavailable", "A new Championship match is unavailable")
        players = match_players(view["entrants"], match)
        if eligibility is not None:
            eligibility(players, view["rule"])
        issue = dict(championship_id=view["championship_id"], round=match["round"], attempt=match["attempt"] + 1,
                     battle_id=str(uuid4()), players=players, sender=actor, native_generation=None, canceled=False,
                     issuance="pending")
        raw, digest = _encoded(issue)
        connection.execute("INSERT INTO attempts VALUES (?,?,?,?,NULL,?,?)", (issue["battle_id"], issue["championship_id"],
                           issue["round"], issue["attempt"], raw, digest))
        match.update(attempt=issue["attempt"], battle_id=issue["battle_id"], state="waiting", winner=None)
        return issue

    def _dispatch(self, issue, actor, desk, invite):
        self._begin_issue(issue)
        try:
            invite(issue["battle_id"], next(player for player in issue["players"] if player != actor))
        except Exception:
            # No awaits occur between persistence and this callback. A synchronous refusal before Desk insertion
            # cannot hold a core.
            if self._native(desk, issue["battle_id"]) is None:
                with self._transaction() as connection:
                    attempt = self._attempt_of(connection, issue["battle_id"])
                    attempt["canceled"] = True
                    self._save_attempt(connection, attempt)
            raise

    def _history(self, actor, operation):
        if operation != "history":
            return []
        history = []
        with self._transaction() as connection:
            for row in connection.execute("SELECT * FROM brackets WHERE state IN ('completed','canceled') "
                                          "ORDER BY sequence DESC"):
                archived = self._bracket(row)
                if actor in archived["players"]:
                    history.append(summary_of(archived))
                if len(history) == HISTORY_LIMIT:
                    break
        if len(history) < HISTORY_LIMIT and self.legacy is not None:
            older = self.legacy.handle(actor, dict(version=FOUR_VERSION, operation="history"), roster={}, desk=None,
                                       results=None, invite=None)
            for summary in older["history"][:HISTORY_LIMIT - len(history)]:
                champion = summary["champion"]
                history.append(dict(championship_id=summary["championship_id"], format=4, players=summary["players"],
                                    names=summary["names"], champion=champion,
                                    champion_name=None if champion is None
                                    else summary["names"][summary["players"].index(champion)],
                                    state=summary["state"]))
        return history

    # ------------------------------------------------------------ the legacy
    def _has_current(self):
        with self._transaction() as connection:
            if self._current(connection) is not None:
                return True
        return self._legacy_current_any() is not None

    def _legacy_current_any(self):
        if self.legacy is None:
            return None
        with self.legacy._transaction() as connection:
            return self.legacy._current(connection)

    def _legacy_current(self, actor, desk, results, reservations, admission):
        """The four players' bracket still proposed or active, when ``actor`` is one of its players (else None)."""
        if self.legacy is None:
            return None
        reply = self.legacy.handle(actor, dict(version=FOUR_VERSION, operation="status"), roster={}, desk=desk,
                                   results=results, invite=None, reservations=reservations, admission=admission)
        current = reply["current"]
        return current if current is not None and current["state"] in {"proposed", "active"} else None

    def _legacy_operation(self, actor, request, legacy_view, *, roster, desk, results, invite, reservations, admission,
                          eligibility):
        """A version 2 request on the four players' bracket: the same operation in version 1, its reply in this shape."""
        older = dict(request, version=FOUR_VERSION)
        if request["operation"] == "match" and legacy_view is not None:
            if request["round"] > 2:
                raise ProtocolError("championship_changed", "Refresh the current Championship before choosing")
        reply = self.legacy.handle(actor, older, roster=roster, desk=desk, results=results, invite=invite,
                                   reservations=reservations, admission=admission, eligibility=eligibility)
        current = None if reply["current"] is None else four_player_view(reply["current"])
        out = dict(version=VERSION, operation=request["operation"], current=current,
                   history=self._history(actor, request["operation"]))
        validate_championship_reply(out, actor, request)
        return out

    # --------------------------------------------------- a computer match's result
    def computer_ticket(self, number):
        """Whether ``number`` is one of this sidecar's computer match tickets (world action 7 belongs here)."""
        with self._transaction() as connection:
            return connection.execute("SELECT 1 FROM attempts WHERE ticket=?", (number,)).fetchone() is not None

    def computer_result(self, actor, number, floor, outcome):
        """World action 7 for one of this sidecar's tickets (TowerService.result): "started", "refused", "won", "lost" or
        "drew". Applied once, by the ticket's own player for its own floor; a repeated or contradicting report changes
        nothing. Returns None when the ticket is not this sidecar's, else {"state": the attempt's state, "settled": whether
        this report settled it, "stage", "won"} (the caller clears the game's kept result for every won / lost / drew
        report: TowerService._answer_result)."""
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM attempts WHERE ticket=?", (number,)).fetchone()
            if row is None:
                return None
            attempt = self._attempt(row)
            mine = attempt["player"] == actor and attempt["floor"] == floor
            now, settled = int(self._now()), False
            if mine and outcome == "started" and attempt["state"] == "issued":
                attempt.update(state="started", started=now)
            elif mine and outcome == "refused" and attempt["state"] == "issued":
                attempt.update(state="void", reason="refused", settled=now)
            elif mine and outcome in ("won", "lost", "drew") and attempt["state"] in OPEN:
                attempt.update(state=outcome, settled=now)
                settled = True
            self._save_attempt(connection, attempt)
            bracket = connection.execute("SELECT * FROM brackets WHERE championship_id=?",
                                         (attempt["championship_id"],)).fetchone()
            view = self._bracket(bracket)
            match = view["matches"][attempt["round"]]
            if match["battle_id"] == attempt["battle_id"]:
                self._reconcile(connection, view, None, None, None, None)
            return dict(state=attempt["state"], settled=settled, stage=attempt["stage"], won=attempt["state"] == "won")

    def computer_busy(self, player):
        """Why ``player``'s game must not take a Tower battle now because of a Championship (their computer match's
        command is out or its battle runs: one Tower battle at a time), else None."""
        with self._transaction() as connection:
            for row in connection.execute("SELECT * FROM attempts WHERE ticket IS NOT NULL"):
                attempt = self._attempt(row)
                if attempt["player"] == player and attempt["state"] in OPEN:
                    return "Finish your Championship match"
        return None


__all__ = ["CONNECTION_SECONDS", "ComputerContext", "EXPERIENCE", "EightChampionships", "ISSUED_SECONDS", "SCOPE", "SEATS",
           "STARTED_SECONDS", "computer_places"]
