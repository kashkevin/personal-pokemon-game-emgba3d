"""Read-only multiplayer statistics derived from canonical host records.

No client can submit a win, hunt count, reward or friendship level here. Private
checkpoint/trade/hunt details belong only to the authenticated actor; peers may
see a connected trainer's completed-battle record.
"""
from __future__ import annotations

from .protocol import MAX_COUNTER, ProtocolError, _fields, _integer
from .team_protocol import _uuid

VERSION = 1
LATEST_VERSION = 2
SUPPORTED_VERSIONS = frozenset({VERSION, LATEST_VERSION})
SCOPE = "recorded-multiplayer-trainer-card-v1"
SCOPE_V2 = "recorded-multiplayer-trainer-card-v2"
BUCKETS = ("total", "singles", "doubles")
COUNTERS = ("played", "wins", "losses", "draws", "streak", "best_streak")
SHARED_COUNTERS = ("played", "wins", "losses", "draws")


def empty_shared_battle_statistics():
    return dict(recorded_through=0, **{key: dict.fromkeys(SHARED_COUNTERS, 0)
                                     for key in ("together", "against")})


def add_shared_battle_result(statistics, result):
    """Project released results by ordered actor/peer; never friendship XP."""
    from .battle_results import validate_result
    validate_result(result, result["sender"])
    for slot, actor in enumerate(result["players"]):
        outcome = "draws" if result["outcome"] == 3 else (
            "wins" if result["outcome"] == 1 + slot % 2 else "losses")
        for peer_slot, peer in enumerate(result["players"]):
            if peer == actor:
                continue
            record = statistics.setdefault((actor, peer), empty_shared_battle_statistics())
            if result["sequence"] <= record["recorded_through"]:
                raise ProtocolError("invalid_server_message", "shared battle archive order repeated")
            record["recorded_through"] = result["sequence"]
            bucket = record["together" if slot % 2 == peer_slot % 2 else "against"]
            bucket["played"] += 1
            bucket[outcome] += 1


def _validate_extended(card, actor, target):
    championship = card["championships"]
    if championship is not None:
        _fields(championship, {"entries", "completed", "wins"})
        for key in championship:
            _integer(championship[key], key, 0, MAX_COUNTER)
        if not championship["wins"] <= championship["completed"] <= championship["entries"]:
            raise ProtocolError("invalid_server_message", "inconsistent Championship counters")
    shared = card["shared"]
    if actor == target:
        if shared is not None:
            raise ProtocolError("invalid_server_message", "a Trainer Card cannot claim shared activity with itself")
        return
    _fields(shared, {"trades", "battles"})
    if shared["trades"] is not None:
        _integer(shared["trades"], "shared trades", 0, MAX_COUNTER)
    battles = shared["battles"]
    _fields(battles, {"recorded_through", "together", "against"})
    _integer(battles["recorded_through"], "recorded_through", 0, MAX_COUNTER)
    played = 0
    for key in ("together", "against"):
        bucket = battles[key]
        _fields(bucket, set(SHARED_COUNTERS))
        for counter in bucket:
            _integer(bucket[counter], counter, 0, MAX_COUNTER)
        if bucket["played"] != bucket["wins"] + bucket["losses"] + bucket["draws"]:
            raise ProtocolError("invalid_server_message", "inconsistent shared battle counters")
        played += bucket["played"]
    if played > battles["recorded_through"] or bool(played) != bool(battles["recorded_through"]):
        raise ProtocolError("invalid_server_message", "shared battle coverage is inconsistent")


async def read_player_card(companion, target):
    """Prefer extended cards; only an explicit older-host refusal allows v1."""
    from .companion import BattleChallengeError
    binding = (companion.world_id, companion.server_epoch, companion.session_epoch)
    try:
        reply = await companion.battle_challenge_rpc("history", player_card_version=LATEST_VERSION, card_player=target)
    except BattleChallengeError as error:
        if error.code not in {"invalid_field", "invalid_fields", "player_card_unsupported"}:
            raise
        if (not companion.connected or binding !=
                (companion.world_id, companion.server_epoch, companion.session_epoch)):
            raise ConnectionError("Trainer Card lost its authenticated session") from error
        reply = await companion.battle_challenge_rpc("history", player_card_version=VERSION, card_player=target)
    if (not companion.connected or binding !=
            (companion.world_id, companion.server_epoch, companion.session_epoch)):
        raise ConnectionError("Trainer Card lost its authenticated session")
    validate_player_card(reply["player_card"], companion.config.player_id, target)
    return reply


def empty_battle_statistics():
    return dict(recorded_through=0, **{key: dict.fromkeys(COUNTERS, 0) for key in BUCKETS})


def add_battle_result(statistics, result, player):
    from .battle_results import validate_result
    validate_result(result, player)
    if result["sequence"] <= statistics["recorded_through"]:
        raise ProtocolError("invalid_server_message", "battle archive order repeated")
    statistics["recorded_through"] = result["sequence"]
    side = 1 + result["players"].index(player) % 2
    outcome = "draws" if result["outcome"] == 3 else ("wins" if result["outcome"] == side else "losses")
    for key in ("total", "singles" if result["mode"] == 2 else "doubles"):
        bucket = statistics[key]
        bucket["played"] += 1
        bucket[outcome] += 1
        bucket["streak"] = bucket["streak"] + 1 if outcome == "wins" else 0
        bucket["best_streak"] = max(bucket["best_streak"], bucket["streak"])


def validate_player_card(card, actor, target):
    version = card.get("version") if type(card) is dict else None
    extended = type(version) is int and version == LATEST_VERSION
    _fields(card, {"version", "scope", "player_id", "display_name", "battles", "personal"}
            | ({"championships", "shared"} if extended else set()))
    _uuid(card["player_id"], "card_player")
    if (type(version) is not int or version not in SUPPORTED_VERSIONS
            or card["scope"] != (SCOPE_V2 if extended else SCOPE) or card["player_id"] != target):
        raise ProtocolError("identity_mismatch", "Trainer Card belongs to another player or version")
    name = card["display_name"]
    if type(name) is not str or not 1 <= len(name) <= 24 or not name.strip() or not name.isprintable():
        raise ProtocolError("invalid_server_message", "invalid Trainer Card name")
    battles = card["battles"]
    _fields(battles, {"recorded_through", *BUCKETS})
    _integer(battles["recorded_through"], "recorded_through", 0, MAX_COUNTER)
    for key in BUCKETS:
        bucket = battles[key]
        _fields(bucket, set(COUNTERS))
        for counter in COUNTERS:
            _integer(bucket[counter], counter, 0, MAX_COUNTER)
        if (bucket["played"] != bucket["wins"] + bucket["losses"] + bucket["draws"]
                or not bucket["streak"] <= bucket["best_streak"] <= bucket["wins"]):
            raise ProtocolError("invalid_server_message", "inconsistent battle counters")
    for counter in ("played", "wins", "losses", "draws"):
        if battles["total"][counter] != battles["singles"][counter] + battles["doubles"][counter]:
            raise ProtocolError("invalid_server_message", "battle formats differ from total record")
    if (battles["total"]["played"] > battles["recorded_through"]
            or bool(battles["total"]["played"]) != bool(battles["recorded_through"])):
        raise ProtocolError("invalid_server_message", "battle archive coverage is inconsistent")
    if extended:
        _validate_extended(card, actor, target)
    personal = card["personal"]
    if actor != target:
        if personal is not None:
            raise ProtocolError("identity_mismatch", "another player's private card data was exposed")
        return card
    _fields(personal, {"checkpoint", "trades", "hunts"})
    checkpoint = personal["checkpoint"]
    if checkpoint is not None:
        _fields(checkpoint, {"revision", "party_count", "stored_count"})
        _integer(checkpoint["revision"], "revision", 1, MAX_COUNTER)
        _integer(checkpoint["party_count"], "party_count", 0, 6)
        _integer(checkpoint["stored_count"], "stored_count", 0, 420)
    trades = personal["trades"]
    if trades is not None:
        _fields(trades, {"committed", "pending"})
        _integer(trades["committed"], "committed", 0, MAX_COUNTER)
        _integer(trades["pending"], "pending", 0, trades["committed"])
    hunts = personal["hunts"]
    if hunts is not None:
        from .reset_protocol import SOURCES
        if type(hunts) is not list or len(hunts) != len(SOURCES):
            raise ProtocolError("invalid_server_message", "personal hunt catalogue differs")
        for expected, hunt in zip(sorted(SOURCES), hunts):
            _fields(hunt, {"encounter_id", "attempts"})
            _integer(hunt["encounter_id"], "encounter_id", 1, 0xFFFFFFFF)
            _integer(hunt["attempts"], "attempts", 0, 0xFFFFFFFF)
            if hunt["encounter_id"] != expected:
                raise ProtocolError("invalid_server_message", "personal hunt sources repeat or differ")
    return card


def build_player_card(server, session, target, *, version=VERSION):
    """Called synchronously by the authenticated host request handler."""
    from .flash import FlashError, inspect_flash
    from .storage import StorageError
    from .trade_storage import TradeCheckpointStore
    if type(version) is not int or version not in SUPPORTED_VERSIONS:
        raise ProtocolError("player_card_unsupported", "unsupported Trainer Card version")
    actor, lease, store = session.player_id, session.session_epoch, server.store
    checkpoint = store.read_checkpoint(actor, lease)
    if server._connected_lease(actor) != lease:
        raise ProtocolError("stale_lease", "Trainer Card requires the current authenticated player")
    peer = server.sessions.get(target)
    if peer is None or peer.closed or server._connected_lease(target) != peer.session_epoch:
        raise ProtocolError("player_offline", "that trainer is no longer connected")
    personal = None
    if actor == target:
        saved = None
        if checkpoint is not None:
            try:
                snapshot = inspect_flash(checkpoint.payload, save_profile=checkpoint.save_profile)
            except FlashError as error:
                raise StorageError("storage_corrupt", "saved progress could not be read safely") from error
            saved = dict(revision=checkpoint.revision, party_count=snapshot.metadata.party_count,
                         stored_count=snapshot.metadata.stored_pokemon_count)
        personal = dict(checkpoint=saved,
            trades=store.trade_statistics(actor, lease) if isinstance(store, TradeCheckpointStore) else None,
            hunts=server._reset_attempts.summary(actor, lease) if server._reset_attempts is not None else None)
    card = dict(version=version, scope=SCOPE_V2 if version == LATEST_VERSION else SCOPE,
        player_id=target, display_name=peer.display_name,
        battles=(empty_battle_statistics() if server._battle_results is None
                 else server._battle_results.statistics(target)), personal=personal)
    if version == LATEST_VERSION:
        shared = None
        if actor != target:
            shared = dict(trades=(store.trade_statistics(actor, lease, peer_id=target)["committed"]
                                 if isinstance(store, TradeCheckpointStore) else None),
                battles=(empty_shared_battle_statistics() if server._battle_results is None
                         else server._battle_results.shared_statistics(actor, target)))
        card.update(championships=(None if server._championships is None else server._championships.statistics(target)),
                    shared=shared)
    return validate_player_card(card, actor, target)
