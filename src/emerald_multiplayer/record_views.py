"""Pure presentation of authenticated records, without new gameplay claims.

These functions neither query a store nor start an interaction. Callers retain
the authenticated snapshot/selection binding and decide when to refresh it.
"""
from __future__ import annotations

from .battle_results import HISTORY_LIMIT, validate_result
from .reset_protocol import SOURCES


def battle_outcome(result, actor):
    validate_result(result, actor)
    if result["outcome"] == 3:
        return "draw"
    return "win" if result["outcome"] == 1 + result["players"].index(actor) % 2 else "loss"


def battle_rows(results, actor, *, mode="all", outcome="all"):
    """Filter the retained latest-eight window; never imply archive coverage."""
    if mode not in {"all", "singles", "doubles"} or outcome not in {"all", "win", "loss", "draw"}:
        raise ValueError("unknown battle history filter")
    if type(results) is not list or len(results) > HISTORY_LIMIT:
        raise ValueError("invalid recent result window")
    rows, identities, sequences = [], set(), set()
    for result in results:
        verdict = battle_outcome(result, actor)
        if result["battle_id"] in identities or result["sequence"] in sequences:
            raise ValueError("repeated recent result")
        identities.add(result["battle_id"])
        sequences.add(result["sequence"])
        result_mode = "singles" if result["mode"] == 2 else "doubles"
        if (mode == "all" or mode == result_mode) and (outcome == "all" or outcome == verdict):
            rows.append(result)
    return tuple(sorted(rows, key=lambda row: row["sequence"], reverse=True))


def hunt_rows(hunts, *, show="all", order="source", query=""):
    """Return copies of admitted counters plus the compiled source names."""
    if show not in {"all", "started", "unstarted"} or order not in {"source", "attempts", "name"}:
        raise ValueError("unknown personal hunt filter")
    if type(query) is not str or len(query) > 100:
        raise ValueError("invalid personal hunt search")
    if type(hunts) is not list or len(hunts) != len(SOURCES):
        raise ValueError("personal hunt catalogue differs")
    rows = []
    for expected, hunt in zip(sorted(SOURCES), hunts):
        if (type(hunt) is not dict or set(hunt) != {"encounter_id", "attempts"}
                or type(hunt["encounter_id"]) is not int or hunt["encounter_id"] != expected
                or type(hunt["attempts"]) is not int or not 0 <= hunt["attempts"] <= 0xFFFFFFFF):
            raise ValueError("invalid personal hunt counter")
        if ((show == "started" and not hunt["attempts"])
                or (show == "unstarted" and hunt["attempts"])
                or query.casefold().strip() not in SOURCES[expected].casefold()):
            continue
        rows.append(dict(hunt, name=SOURCES[expected]))
    key = {"source": lambda row: row["encounter_id"],
           "attempts": lambda row: (-row["attempts"], row["encounter_id"]),
           "name": lambda row: (row["name"].casefold(), row["encounter_id"])}[order]
    return tuple(sorted(rows, key=key))


def hunt_totals(hunts):
    rows = hunt_rows(hunts)
    return dict(attempts=sum(row["attempts"] for row in rows),
                started=sum(bool(row["attempts"]) for row in rows), sources=len(rows))


def hunt_detail(hunts, encounter_id):
    if type(encounter_id) is not int or encounter_id not in SOURCES:
        raise ValueError("unknown personal hunt source")
    row = next(row for row in hunt_rows(hunts) if row["encounter_id"] == encounter_id)
    return dict(row, scope="Personal static encounter", counting="Admitted encounter attempts",
                odds="Attempt counts do not change shiny odds.",
                availability="A catalogue entry does not prove this build enables the encounter.",
                outcome="Capture and shiny outcomes are not recorded in this ledger.")
