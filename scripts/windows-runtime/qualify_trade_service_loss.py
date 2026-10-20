"""Actual Windows trade interruption: one candidate, real host-service loss.

Two genuine copied characters use ordinary native offer/consent/review menus.
Only the first recipient approves its private candidate. The real host service
then closes; both original games must remain held. Production host restart and
explicit trade-close recovery verify canceled fate through independent observer
leases, with no reconnect/release/replacement of the originals. The operator
closes the reported windows normally. Fresh Host/Join verifies canonical source,
Continue, fresh saving and normal closure. No evolution/fault-after-commit,
GUI-button/physical-keyboard, LAN/Internet or whole-app-crash claim is made.
"""
import asyncio
import hashlib
import json

from qualify_menu_trade_effects import (
    arguments, choose_party_slot, choose_visible, displayed, inspect_closed_head,
    party, require, review_candidate, run, until,
)
from emerald_multiplayer.trade_effect_storage import parse_document


async def interrupted_trade(sessions, games, probes, tasks, host, slots, record, *, committed=False):
    before = [inspect_closed_head(sessions[0]._store, a.player_id) for a in host.accounts]
    originals = [(s._game, s._runtime, s._companion, s._companion._bridge,
                  s._companion.save_incarnation, s._companion.session_epoch) for s in sessions]
    await probes[0].open_players()
    await choose_visible(probes[0], host.accounts[1].display_name)
    await choose_visible(probes[0], "Trading")
    await choose_party_slot(probes[0], slots[0])
    await probes[1].open_players()
    await choose_visible(probes[1], "Pending trade")
    await choose_visible(probes[1], "Choose your Pokemon")
    await choose_party_slot(probes[1], slots[1])
    for probe in probes:
        await displayed(probe, lambda s: any(r.action and r.label == "Confirm this trade" for r in s.rows))
    await choose_visible(probes[0], "Confirm this trade")
    await displayed(probes[0], lambda s: s.status == "Confirmed; waiting for friend")
    await choose_visible(probes[1], "Confirm this trade")
    await asyncio.gather(*(displayed(p, lambda s: s.title == "Trade preparation", timeout=90) for p in probes))
    await review_candidate(probes[0], 0, record)
    paths = [s.profile_directory / "pending-trade.json" for s in sessions]
    intents = [json.loads(p.read_bytes())["intent"] for p in paths]
    identities = {(i["transaction_id"], i["generation"]) for i in intents}
    require(len(identities) == 1, "original trade identities differ")
    tx, generation = identities.pop()
    prefix = tx + "." + generation
    await until(lambda: (sessions[0].profile_directory / (prefix + ".effect-receipt.json")).exists(), tasks=tasks)
    await displayed(probes[0], lambda s: s.status == "Ready; waiting for friend", timeout=90)
    require(not (sessions[1].profile_directory / (prefix + ".effect-receipt.json")).exists(),
            "withheld recipient unexpectedly prepared")
    require(sessions[0]._store._connection.execute("SELECT COUNT(*) FROM trade_effect_commits").fetchone()[0] == 0,
            "one recipient prepared a committed pair")
    record("one-native-candidate-no-commit", transaction_id=tx, generation=generation)
    commit_pin = None
    if committed:
        # Observe real atomic publication. No method is replaced, response is
        # withheld, or receipt is injected. Missing the cut disqualifies it.
        async def close_after_commit():
            store = sessions[0]._store
            async with asyncio.timeout(240):
                while True:
                    rows = store._connection.execute(
                        "SELECT * FROM trade_effect_commits WHERE transaction_id=?", (tx,)).fetchall()
                    if rows:
                        require(len(rows) == 1, "paired commit is not unique")
                        document = parse_document(rows[0])
                        require(all(d["transaction_id"] == tx and d["generation"] == generation
                                    and d["format"] == "emerald-trade-recipient-effects-v2"
                                    for d in document["descriptions"]), "committed identity differs")
                        recovery = [dict(r) for r in store._connection.execute(
                            "SELECT * FROM trade_recovery WHERE transaction_id=? ORDER BY player_id", (tx,))]
                        require(len(recovery) == 2 and all(r["acknowledged"] == 0 for r in recovery),
                                "unsuitable cut: recipient acknowledged before service loss")
                        heads = [inspect_closed_head(store, a.player_id) for a in host.accounts]
                        require(all(h.revision == 3 for h in heads), "commit did not publish both candidates")
                        pin = dict(sha256=rows[0]["sha256"], document=document,
                                   heads=[(h.revision, h.sha256, h.payload) for h in heads])
                        record("real-paired-commit-before-service-loss", transaction_id=tx,
                               generation=generation, commit_sha256=pin["sha256"], recovery=recovery)
                        await sessions[0]._close_host_service()
                        return pin
                    for task in tasks:
                        if task.done():
                            await task
                            raise AssertionError("original exited before committed cut")
                    await asyncio.sleep(.005)
        watcher = asyncio.create_task(close_after_commit())
        try:
            await review_candidate(probes[1], 1, record)
            commit_pin = await watcher
        finally:
            if not watcher.done():
                watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
    else:
        await sessions[0]._close_host_service()
    record("real-host-service-closed", original_pids=[g.process.pid for g in games])
    await until(lambda: all(s.can_prepare_trade_recovery for s in sessions), timeout=90, tasks=tasks)
    # Freeze the settled journals, not an in-flight native request that is still
    # legitimately completing under the old connection's final disconnect.
    raw = [p.read_bytes() for p in paths]
    require(all(not s._companion.connected and s._emergency.result.state == "trade_waiting"
                and not s.can_save for s in sessions), "originals did not retain trade holds")
    record("both-originals-held", journal_sha256=[hashlib.sha256(v).hexdigest() for v in raw])
    # A failed strict read must be visible before the generic availability
    # property converts it into a disabled action. This invokes no new control.
    sessions[0]._retained_trade()
    require(sessions[0].can_restart_host_service, "host restart is unreachable from retained trade")
    await sessions[0].restart_host_service()
    record("production-host-service-restarted", server_epoch=sessions[0]._store.metadata.server_epoch)
    require(sessions[0]._server.is_serving, "replacement host service did not start")
    reviews = []
    for index, s in enumerate(sessions):
        record("production-trade-close-review-started", slot=index)
        review = await s.prepare_trade_recovery()
        require(review.state == ("committed" if committed else "aborted")
                and review.transaction_id == tx and review.generation == generation,
                "interrupted pair did not resolve its exact expected fate")
        require(s.status.code == "trade_recovery_close" and not s.can_save,
                "close instruction did not preserve old-core save block")
        require(paths[index].read_bytes() == raw[index], "observer changed original native intent")
        current = (s._game, s._runtime, s._companion, s._companion._bridge,
                   s._companion.save_incarnation, s._companion.session_epoch)
        require(all(a is b for a, b in zip(current[:4], originals[index][:4]))
                and current[4] == originals[index][4] and current[5] is None
                and all(getattr(s._companion, name) is None for name in ("world_id", "server_epoch", "save_profile"))
                and s._binding == s._trade_retained[3] and s._binding[2] == originals[index][5]
                and not s._companion.connected,
                "observer replaced or renewed an original core")
        reviews.append(dict(slot=index, state=review.state, checkpoint=review.checkpoint,
                            evidence_sha256=hashlib.sha256(review.evidence_path.read_bytes()).hexdigest()))
    heads = [inspect_closed_head(sessions[0]._store, a.player_id) for a in host.accounts]
    store = sessions[0]._store
    if committed:
        require([(h.revision, h.sha256, h.payload) for h in heads] == commit_pin["heads"],
                "observer changed the atomically committed candidates")
        rows = store._connection.execute("SELECT * FROM trade_effect_commits WHERE transaction_id=?", (tx,)).fetchall()
        require(len(rows) == 1 and rows[0]["sha256"] == commit_pin["sha256"]
                and parse_document(rows[0]) == commit_pin["document"], "paired native proof changed")
        recovery = [dict(r) for r in store._connection.execute(
            "SELECT * FROM trade_recovery WHERE transaction_id=? ORDER BY player_id", (tx,))]
        require(len(recovery) == 2 and all(r["acknowledged"] == 0 for r in recovery),
                "unsuitable cut: an original acknowledged the committed trade")
        require(sorted(v for h in heads for v in party(h)["serials"])
                == sorted(v for h in before for v in party(h)["serials"]), "ownership serials changed")
        for i, session in enumerate(sessions):
            receipt = json.loads((session.profile_directory / (prefix + ".effect-receipt.json")).read_bytes())
            recipient = next(n for n, d in enumerate(commit_pin["document"]["descriptions"])
                             if d["recipient_id"] == host.accounts[i].player_id)
            require(receipt["receipt"] == commit_pin["document"]["receipts"][recipient],
                    "retained native approval differs from the host commit")
            require(party(heads[i])["serials"][slots[i]] == party(before[1-i])["serials"][slots[1-i]],
                    "committed recipient did not receive the selected original Pokemon")
        record("committed-originals-unacknowledged", recovery=recovery, commit_sha256=commit_pin["sha256"])
    else:
        require(all(h.revision == 2 and party(h) == party(before[i]) for i, h in enumerate(heads)),
                "canceled trade changed either original party")
        require(store._connection.execute("SELECT COUNT(*) FROM trade_effect_commits").fetchone()[0] == 0,
                "canceled pair acquired a committed result")
    record("verified-close-permission-no-native-release", reviews=reviews)
    return [party(h) for h in heads]


if __name__ == "__main__":
    asyncio.run(run(arguments(__doc__), trade_flow=interrupted_trade, interrupted=True, scope=__doc__))
