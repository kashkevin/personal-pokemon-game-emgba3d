"""Verify an interrupted original's exact canonical fate before player closure.

This never reconnects its native bridge, releases a hold, restores a live save,
or starts a replacement game. Fresh launch still passes ColdStartRecovery.
"""
import asyncio
from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
import secrets
from types import SimpleNamespace

from .checkpoint_client import CheckpointClient
from .cold_start import _ClosedTradeReader
from .companion import Companion
from .live_checkpoint import _atomic, _json_bytes
from .live_trade import LiveTradeError


@dataclass(frozen=True)
class TradeCloseReview:
    transaction_id: str
    generation: str
    state: str
    checkpoint: dict
    journal_sha256: str
    evidence_path: Path


def read_original_trade(companion, directory, binding, identity):
    """Read only; a new lease cannot replace the original intent identity."""
    config = companion.config
    if (config.expected_world_id, config.player_id, config.build_id, config.ruleset_id) != (
            binding[0], binding[4], binding[5], binding[6]):
        raise LiveTradeError("trade_recovery_held", "retained identity differs from the provisioned world")
    # Disconnect deliberately clears the Companion's current authentication.
    # This reader has no transport/native methods: it verifies local source
    # ownership against the exact captured identity, never restores a lease.
    reader = _ClosedTradeReader(SimpleNamespace(world_id=binding[0], config=config), Path(directory))
    raw = reader.trade_path.read_bytes()
    intent = reader._load((binding[0], binding[2], identity[3]))
    expected = (intent["transaction_id"], intent["generation"], intent["expected_revision"],
                intent["incarnation"], intent["runtime_id"])
    if (expected != identity or intent["prepared"] is None or not intent["export_ended"]
            or (intent["world_id"], intent["player_id"], intent["build_id"], intent["ruleset_id"], intent["save_profile"])
                != (binding[0], binding[4], binding[5], binding[6], binding[3])):
        raise LiveTradeError("trade_recovery_held", "the original complete prepared source is not verified")
    return reader, intent, raw


async def review_with_observer(observer, directory, binding, identity, *, check_original):
    """Explicit cancellation of unfinished trades; committed fates only verify.

    The caller has already explained that this action cancels an unfinished
    trade. The observer owns a newer authenticated lease and has no game.
    """
    check_original()
    reader, intent, raw = read_original_trade(observer, directory, binding, identity)
    client = CheckpointClient(observer)
    session = (observer.world_id, observer.server_epoch, observer.session_epoch, observer.save_profile)
    if (session[0] != binding[0] or session[3] != binding[3]
            or type(session[1]) is not int or session[1] < binding[1]
            or type(session[2]) is not int or session[2] <= binding[2]):
        raise LiveTradeError("trade_recovery_held", "observer did not authenticate the original world and a new lease")

    def unchanged():
        check_original()
        if (not observer.connected or observer._bridge is not None
                or (observer.world_id, observer.server_epoch, observer.session_epoch, observer.save_profile) != session
                or reader.trade_path.read_bytes() != raw):
            raise LiveTradeError("trade_recovery_held", "original or observer changed during fate verification")

    unchanged()
    fate = (await observer.trade_rpc("status", transaction_id=intent["transaction_id"]))["trade"]
    unchanged()
    if fate["state"] in {"offering", "preparing"}:
        if fate["generation"] != intent["generation"]:
            raise LiveTradeError("trade_changed", "another generation cannot settle this original")
        fate = (await observer.trade_rpc("cancel", transaction_id=intent["transaction_id"],
                                        generation=intent["generation"]))["trade"]
        unchanged()
    if fate["state"] not in {"aborted", "committed"} or fate["transaction_id"] != intent["transaction_id"]:
        raise LiveTradeError("trade_recovery_held", "the host has not settled this exact trade")
    if intent["fate"] is not None and fate != intent["fate"]:
        raise LiveTradeError("trade_conflict", "the retained committed fate changed")
    head = await client.info()
    unchanged()
    if fate["state"] == "committed":
        if (head is None or (head["request_id"], head["revision"], head["sha256"]) !=
                (intent["transaction_id"], intent["expected_revision"] + 2, fate["sha256"])
                or fate["revision"] != head["revision"]):
            raise LiveTradeError("revision_conflict", "committed fate is not this original's current canonical head")
        expected = reader._prepared_candidate(intent, (binding[0], session[2], None))
        if expected is None:
            raise LiveTradeError("trade_recovery_held", "exact retained recipient candidate is unavailable")
    else:
        if head != intent["prepared"]:
            raise LiveTradeError("revision_conflict", "canceled trade no longer owns the canonical prepared source")
        expected = reader._bytes(intent["prepare_id"] + ".flash", intent["frozen_sha256"], 131072)
    downloaded = await client.download()
    unchanged()
    if (downloaded is None or downloaded.metadata != head or downloaded.payload != expected
            or (downloaded.world_id, downloaded.player_id) != (binding[0], binding[4])):
        raise LiveTradeError("trade_conflict", "canonical bytes do not match this original's retained result")
    if await client.info() != head:
        raise LiveTradeError("revision_conflict", "canonical head changed before closure verification")
    unchanged()
    # No ACK: the cold gate must first install and verify these bytes while its
    # MirrorLease is exclusively held, then acknowledge the committed result.
    record = dict(format="emerald-trade-close-review-v1", original_binding=list(binding),
        original_identity=list(identity), journal_sha256=hashlib.sha256(raw).hexdigest(),
        observer_session=list(session), fate=fate, checkpoint=head)
    path = Path(directory) / (intent["transaction_id"] + "." + intent["generation"]
                              + f".close-review.{session[1]}.{session[2]}.json")
    encoded = _json_bytes(record)
    if path.exists() and path.read_bytes() != encoded:
        raise LiveTradeError("journal_changed", "an existing closure review differs")
    if not path.exists():
        _atomic(path, encoded)
    if path.read_bytes() != encoded:
        raise LiveTradeError("journal_changed", "closure review readback differs")
    unchanged()
    return TradeCloseReview(intent["transaction_id"], intent["generation"], fate["state"],
                            head, record["journal_sha256"], path)


async def review_interrupted_trade(original, directory, binding, identity, *, check_original, timeout):
    """Observe/cancel with new authentication; the original stays disconnected."""
    check_original()
    observer = Companion(replace(original.config, token=secrets.token_bytes(32), ipc_port=0))
    try:
        await observer.start()
        async with asyncio.timeout(timeout):
            while not observer.connected:
                check_original()
                await asyncio.sleep(.025)
            observer._reconnect_blocked = True
            return await review_with_observer(observer, directory, binding, identity,
                                               check_original=check_original)
    finally:
        # Drain only this observer; it never owns the original bridge or file.
        from .player_runtime import _finish_even_if_cancelled
        _, canceled = await _finish_even_if_cancelled(asyncio.create_task(observer.close()))
        if canceled:
            raise asyncio.CancelledError()
