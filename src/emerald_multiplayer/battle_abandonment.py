"""Abandoning an interrupted native battle: no result, and every participant free again (KNOWN_ISSUES MS-16).

The owner's decision of 2026-10-19: when a player disconnects, crashes, closes the game or loses the connection
during a multiplayer battle (1v1, 2v2, co-op or the free-for-all), the players who remain must not be stuck. Any
participant of an interrupted battle may abandon it. An abandoned battle has no winner and no loser, gives no reward,
settles no wager and changes no progression: a native battle never writes a character's save (RELEASE only restores
the party the battle started with), so every participant continues from the canonical checkpoint the challenge pinned,
which is still their latest verified save. A battle whose result is already durable is not abandoned: its terminal
reservation is ``closed`` (every restored RELEASE published), or every participant's restored RELEASE is in the route
journal (a host that crashed before publishing); the existing recovery settles those.

Host (``BattleAbandonment``):

* ``abandon`` writes an abandonment record beside the route journal (``<battle>.abandoned.json``) and then closes the
  durable reservation as ``aborted`` with that record's digest (the schema's "no result" terminal, which the
  Championship, Frontier and rival checkpoints already treat as a battle to play again). That releases every
  participant's barrier; the original consent is cancelled (no late Enter or BIND), the live route and any recovery
  quorum stop, a wager is cancelled, and the Desk forgets the battle. A late RELEASE cannot publish a result any more
  (``BattleDesk._publish_closed`` refuses an aborted reservation) and recovery refuses the battle. Every step is
  idempotent and keyed by the battle ID, so a host crash between them is finished by the next request, and other
  battles of the world are not touched.
* ``fate`` answers the same question without changing anything.

The answer (``abandonment_view``) names the battle, its players and its state: ``abandoned``, ``aborted`` (an
earlier abort), ``closed`` (the result stands) or ``unresolved``.

Client (``local_battle_targets`` / ``retire_local_battle``): the launcher keeps the host's answer, with the bytes of
the local battle intents it retires, in ``<battle>.battle-abandoned.json`` and only then removes those intents. Its
game, held in the battle, is closed and started again from the canonical save (launcher_session.py); a player whose
game is already gone (a crash, a closed window, a full restart) resolves the battle the same way when the launcher
starts.
"""
from __future__ import annotations

import base64
from contextlib import suppress
import hashlib
import json
from pathlib import Path
import re
import stat
from types import SimpleNamespace

from .live_checkpoint import _atomic, _json_bytes, _sync_directory
from .protocol import ProtocolError

SCOPE = "native-battle-abandonment-v1"
RECORD_FORMAT = "native-battle-abandonment-record-v1"
CLIENT_FORMAT = "native-battle-client-abandonment-v1"
DOMAIN = b"durable-native-battle-reservations-v1:abandoned\0"
STATES = frozenset(("abandoned", "aborted", "closed", "unresolved"))
PENDING = ("pending-battle.json", "pending-battle-admission.json")
# A battle's last commands are each core's RELEASE: a crash before the result was published leaves them at the end.
JOURNAL_TAIL = 512 * 1024
_HASH = re.compile(r"[0-9a-f]{64}\Z")


# --------------------------------------------------------------------------------------------------------------- view
def abandonment_view(battle_id, generation, state, players, digest):
    return dict(scope=SCOPE, battle_id=battle_id, generation=generation, state=state, players=list(players),
                terminal_sha256=digest)


def validate_abandonment_view(value, actor, request=None):
    from .team_protocol import _uuid
    if (type(value) is not dict or set(value) != {"scope", "battle_id", "generation", "state", "players", "terminal_sha256"}
            or value["scope"] != SCOPE or value["state"] not in STATES):
        raise ProtocolError("invalid_server_message", "invalid battle abandonment answer")
    try:
        _uuid(value["battle_id"], "battle_id")
        _uuid(value["generation"], "generation")
        players = value["players"]
        if type(players) is not list or len(players) not in (2, 4) or len(set(players)) != len(players):
            raise ValueError()
        for player in players:
            _uuid(player, "player")
        digest = value["terminal_sha256"]
        if digest is not None and (type(digest) is not str or _HASH.fullmatch(digest) is None):
            raise ValueError()
        # A terminal fact names its digest; an unresolved battle has none; an earlier abort may have no reservation.
        if (digest is None) == (value["state"] in ("abandoned", "closed")) or value["state"] == "unresolved" and digest:
            raise ValueError()
    except (ValueError, ProtocolError) as error:
        raise ProtocolError("invalid_server_message", "malformed battle abandonment answer") from error
    if actor not in players:
        raise ProtocolError("identity_mismatch", "battle abandonment answer names another player's battle")
    if request is not None and (value["battle_id"], value["generation"]) != (request["battle_id"], request["generation"]):
        raise ProtocolError("identity_mismatch", "battle abandonment answer names another battle")
    return value


def record_digest(record):
    return hashlib.sha256(DOMAIN + _json_bytes(record)).hexdigest()


def _read_json(path, limit=65536):
    if not stat.S_ISREG(Path(path).lstat().st_mode):
        raise ValueError("not a regular file")
    with open(path, "rb") as source:
        raw = source.read(limit + 1)
    value = json.loads(raw)
    if len(raw) > limit or type(value) is not dict or _json_bytes(value) != raw:
        raise ValueError("not a canonical record")
    return value


def releases_journaled(path, players):
    """Every participant's successful RELEASE is in the route journal's tail (the result is final there)."""
    from .battle_execution_protocol import decode_control
    from .native_battle import Opcode
    try:
        with open(path, "rb") as source:
            source.seek(0, 2)
            size = source.tell()
            source.seek(max(0, size - JOURNAL_TAIL))
            raw = source.read()
    except FileNotFoundError:
        return False
    released = set()
    lines = raw.split(b"\n")
    if size > JOURNAL_TAIL:
        lines = lines[1:]                                     # the first line may start mid-record
    for line in lines:
        if not line:
            continue
        try:
            value = json.loads(line)["value"]
            if type(value) is not dict or value.get("kind") != "response":
                continue
            control = decode_control(value["control_b64"], response=True)
        except (ValueError, KeyError, TypeError):
            continue
        if control.opcode == Opcode.RELEASE and control.status == 0 and value.get("actor") in players:
            released.add(value["actor"])
    return released == set(players)


# --------------------------------------------------------------------------------------------------------------- host
class BattleAbandonment:
    """The host's answer to "abandon this interrupted battle" and "what became of it"; see the module text."""

    def __init__(self, server):
        self.server = server

    @property
    def desk(self):
        return self.server.battle_desk

    @property
    def execution(self):
        return self.server.battle_execution

    @property
    def reservations(self):
        return self.server._battle_reservations

    def _directory(self):
        return None if self.execution is None else self.execution.directory

    def _record_path(self, battle_id):
        directory = self._directory()
        return None if directory is None else directory / (battle_id + ".abandoned.json")

    def _record(self, battle_id):
        path = self._record_path(battle_id)
        if path is None or not path.exists():
            return None
        try:
            value = _read_json(path)
            if value.get("format") != RECORD_FORMAT or value.get("battle_id") != battle_id:
                raise ValueError()
            return value
        except (OSError, ValueError, TypeError) as error:
            from .battle_desk import BattleError
            raise BattleError("battle_abandonment_invalid", "the battle's abandonment record cannot be read") from error

    def _row(self, battle_id):
        if self.reservations is None:
            return None
        with self.reservations.store._transaction():
            self.reservations.store._validate_schema()
            row = self.reservations.store._connection.execute(
                "SELECT * FROM battle_reservations WHERE battle_id=?", (battle_id,)).fetchone()
            return None if row is None else (dict(row), self.reservations._read(row))

    def _consent(self, battle_id):
        execution = self.execution
        if execution is None or not execution.admission.has_consent(battle_id):
            return None
        return execution.admission._read(battle_id)

    def _identify(self, actor, lease, request):
        """(identity, row, record, battle, consent) of a battle this authenticated player is part of."""
        from .battle_desk import BattleError
        from .battle_mailbox import _uuid
        desk = self.desk
        if desk is None:
            raise BattleError("battle_disabled", "this host has no native battles")
        battle_id, generation = request["battle_id"], request["generation"]
        _uuid(battle_id, "battle ID"); _uuid(generation, "generation")
        desk._auth_lease(actor, lease)
        found = self._row(battle_id)
        row, reserved = (None, None) if found is None else found
        record = self._record(battle_id)
        battle = desk._active.get(battle_id) or desk._history.get(battle_id)
        consent = self._consent(battle_id)
        if reserved is not None:
            view = reserved["view"]
            identity = dict(players=list(view["players"]), generation=view["generation"], mode=view["mode"],
                            fingerprint=view["fingerprint"], sender=view["sender"])
        elif battle is not None:
            identity = dict(players=list(battle.players), generation=battle.generation, mode=battle.mode,
                            fingerprint=battle.fingerprint, sender=battle.sender)
        elif consent is not None:
            view = consent["view"]
            identity = dict(players=list(view["players"]), generation=view["generation"], mode=view["mode"],
                            fingerprint=view["fingerprint"], sender=view["sender"])
        elif record is not None:
            identity = {key: record[key] for key in ("players", "generation", "mode", "fingerprint", "sender")}
        else:
            raise BattleError("battle_missing", "this host has no record of that battle")
        if actor not in identity["players"]:
            raise BattleError("battle_not_participant", "actor is not a battle participant")
        if generation != identity["generation"]:
            raise BattleError("battle_generation_mismatch", "battle generation has changed")
        if record is not None and any(record[key] != identity[key] for key in identity):
            raise BattleError("battle_abandonment_invalid", "the abandonment record names another battle")
        return identity, row, record, battle, consent

    def _fate(self, battle_id, identity, row, record, battle):
        players = identity["players"]
        if row is not None and row["terminal_kind"] == "closed":
            return abandonment_view(battle_id, identity["generation"], "closed", players, row["terminal_digest"])
        if row is not None and row["terminal_kind"] == "aborted":
            if record is not None and row["terminal_digest"] == record_digest(record):
                return abandonment_view(battle_id, identity["generation"], "abandoned", players, row["terminal_digest"])
            return abandonment_view(battle_id, identity["generation"], "aborted", players, row["terminal_digest"])
        if row is None and record is not None and not record["reserved"]:
            # Abandoned before any reservation: the record and the cancelled consent are the whole terminal fact.
            return abandonment_view(battle_id, identity["generation"], "abandoned", players, record_digest(record))
        if row is None and battle is not None and battle.state == "aborted":
            return abandonment_view(battle_id, identity["generation"], "aborted", players, None)
        return abandonment_view(battle_id, identity["generation"], "unresolved", players, None)

    def fate(self, actor, lease, request):
        identity, row, record, battle, _ = self._identify(actor, lease, request)
        return self._fate(request["battle_id"], identity, row, record, battle)

    def _interrupted(self, battle_id, battle, identity):
        """True when the battle can no longer go on as it is (a participant left, the route failed, the host restarted)."""
        desk = self.desk
        if battle is None or desk._active.get(battle_id) is not battle:
            return True                                   # the host restarted (or the Desk let it go): nothing runs it
        if battle.state in ("recovery_required", "aborting"):
            return True
        if any(desk.lease_for(p) != lease for p, lease in zip(battle.players, battle.leases)):
            return True
        room = None if self.execution is None else self.execution.rooms.get(battle_id)
        return room is not None and room.state == "recovery_required"

    def abandon(self, actor, lease, request):
        from .battle_desk import BattleError
        try:
            return self._abandon(actor, lease, request)
        except OSError as error:
            # A file that could not be written durably: nothing later is done; a repeat finishes it (idempotent).
            raise BattleError("battle_abandon_failed", "the host could not record the abandonment; try again") from error

    def _abandon(self, actor, lease, request):
        from .battle_desk import BattleError
        battle_id = request["battle_id"]
        self.desk.refresh()
        identity, row, record, battle, consent = self._identify(actor, lease, request)
        fate = self._fate(battle_id, identity, row, record, battle)
        if fate["state"] != "unresolved":
            return fate
        if not self._interrupted(battle_id, battle, identity):
            raise BattleError("battle_still_running", "the battle is still running; it can be abandoned once it is interrupted")
        players = identity["players"]
        if battle is not None and battle.released == set(players):
            raise BattleError("battle_result_final", "every participant was released; the result stands")
        directory = self._directory()
        journal = None if directory is None else directory / (battle_id + ".events.jsonl")
        if journal is not None and releases_journaled(journal, players):
            raise BattleError("battle_result_final", "every participant's restored release is recorded; recover to settle it")
        self._stop_live(battle_id)
        if record is None:
            route = None
            if journal is not None and journal.exists():
                route = hashlib.sha256(journal.read_bytes()).hexdigest()
            record = dict(format=RECORD_FORMAT, world_id=self.desk.store.metadata.world_id,
                          build_id=self.desk.store.build_id, ruleset_id=self.desk.store.ruleset_id,
                          battle_id=battle_id, **identity, requested_by=actor, reserved=row is not None,
                          reservation_sha256=None if row is None else row["sha256"], route_sha256=route,
                          reason=None if battle is None else (battle.reason or battle.state),
                          released=sorted(battle.released) if battle is not None else [])
            path = self._record_path(battle_id)
            if path is None:
                raise BattleError("battle_execution_disabled", "this host keeps no native battle evidence")
            _atomic(path, _json_bytes(record))
        digest = record_digest(record)
        if row is not None:
            self.reservations._abandon(battle_id, digest)
        if consent is not None and not consent["canceled"]:
            consent["canceled"] = True
            _atomic(self.execution.admission._path(battle_id), _json_bytes(consent))
        self._forget(battle_id, battle, players)
        return self.fate(actor, lease, request)

    def _stop_live(self, battle_id):
        """The route and any recovery quorum of this battle stop; nothing they do later can publish anything."""
        execution = self.execution
        if execution is None:
            return
        room = execution.rooms.get(battle_id)
        if room is not None:
            room.state, room.error = "aborted", "abandoned"
            for command, future, _ in room.pending.values():
                if not future.done():
                    future.cancel()
            room.pending.clear()
            if room.task is not None and not room.task.done():
                room.task.cancel()
            with suppress(OSError):
                execution._persist(room)
        recovery = execution.recovery
        if recovery is not None:
            quorum = recovery.rooms.pop(battle_id, None)
            if quorum is not None:
                quorum.state = "aborted"
                for task in (quorum.task, quorum.loading):
                    if task is not None and not task.done():
                        task.cancel()

    def _forget(self, battle_id, battle, players):
        desk = self.desk
        if battle is not None and desk._active.get(battle_id) is battle:
            battle.consent.clear()
            battle.abort_pending = set()
            battle.state, battle.reason = "aborted", "abandoned"
            desk._archive(battle)
        elif battle is not None:
            battle.state, battle.reason = "aborted", "abandoned"
        if callable(desk.on_aborted):
            try:
                desk.on_aborted(battle if battle is not None else
                                SimpleNamespace(battle_id=battle_id, players=tuple(players), reason="abandoned"))
            except Exception:  # noqa: BLE001 - a wager never blocks an abandonment
                pass
        try:
            from .shared_world import _banner
            self.server.shared_world.post_notice(_banner("BATTLE ABANDONED", "No result was recorded"), to=list(players))
            self.server._broadcast_world()
        except Exception:  # noqa: BLE001 - a notice never blocks an abandonment
            pass


# ------------------------------------------------------------------------------------------------------------- client
def _intent_target(path):
    from .battle_admission_intent import read_admission_intent
    from .battle_journal import read_battle_intent
    intent = read_admission_intent(path) if path.name == "pending-battle-admission.json" else read_battle_intent(path)
    return intent.battle_id, intent.generation


def local_battle_targets(directory):
    """(battle_id, generation) of every battle a local intent in this character's folder still holds."""
    from .battle_journal import BattleJournalError, path_present
    targets = []
    for name in PENDING:
        path = Path(directory) / name
        if path_present(path):
            try:
                target = _intent_target(path)
            except (BattleJournalError, ValueError, OSError) as error:
                raise BattleJournalError("pending_battle", "a pending battle intent cannot be read") from error
            if target not in targets:
                targets.append(target)
    return targets


def retire_local_battle(directory, view):
    """Keep the host's terminal answer with the retired intents' bytes, then remove those intents (crash-safe)."""
    from .battle_journal import BattleJournalError, path_present
    if view["state"] not in ("abandoned", "aborted", "closed"):
        raise BattleJournalError("pending_battle", "the battle is not resolved on the host")
    directory = Path(directory)
    battle_id = view["battle_id"]
    retired = {}
    for name in (*PENDING, "native-battle-execution.json"):
        path = directory / name
        if not path_present(path):
            continue
        if name == "native-battle-execution.json":
            try:
                owner = _read_json(path, 32768)["intent"]["battle_id"]
            except (OSError, ValueError, KeyError, TypeError):
                owner = None
        else:
            try:
                owner = _intent_target(path)[0]
            except (BattleJournalError, ValueError, OSError):
                owner = None
        if owner == battle_id:
            retired[name] = base64.b64encode(path.read_bytes()).decode("ascii")
    evidence = directory / (battle_id + ".battle-abandoned.json")
    record = dict(format=CLIENT_FORMAT, host=view, retired=retired)
    if path_present(evidence):
        previous = _read_json(evidence)
        # A second resolution (after a crash between the two steps) keeps the first record and its retired bytes.
        if previous.get("format") != CLIENT_FORMAT or previous.get("host", {}).get("battle_id") != battle_id:
            raise BattleJournalError("pending_battle", "another abandonment record has this battle's name")
        retired = {**retired, **previous["retired"]}
        record = dict(format=CLIENT_FORMAT, host=previous["host"], retired=retired)
    _atomic(evidence, _json_bytes(record))
    for name in retired:
        path = directory / name
        if path_present(path) and base64.b64encode(path.read_bytes()).decode("ascii") == retired[name]:
            path.unlink()
    _sync_directory(directory)
    return record


async def host_can_abandon(companion):
    """Whether the connected host abandons battles; asked once per authenticated session (an older host refuses)."""
    from .companion import BattleChallengeError
    cached = getattr(companion, "_battle_abandon_capability", None)
    if cached is not None and cached[0] == (companion.world_id, companion.session_epoch):
        return cached[1]
    try:
        reply = await companion.battle_challenge_rpc("pending", abandon_version=1)
        supported = reply.get("abandon_version") == 1
    except BattleChallengeError:
        supported = False
    companion._battle_abandon_capability = ((companion.world_id, companion.session_epoch), supported)
    return supported


async def resolve_battle(companion, battle_id, generation, *, abandon=True):
    """Ask the host to abandon this battle (or only for its fate); the validated answer."""
    from .battle_journal import BattleJournalError
    if not await host_can_abandon(companion):
        raise BattleJournalError("battle_abandon_unsupported", "the host cannot abandon battles")
    reply = await companion.battle_challenge_rpc("abandon" if abandon else "fate", battle_id=battle_id,
                                                 generation=generation)
    return validate_abandonment_view(reply["result"], companion.config.player_id,
                                     dict(battle_id=battle_id, generation=generation))
