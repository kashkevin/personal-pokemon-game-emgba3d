"""The host side of the Legendary Tickets (docs/legendary-tickets.md section 6.3; legendary_tickets.py holds the catalogue,
the conditions, the owner's setting and the ledger).

Owner decision 40 (2026-11-05): the tickets of the personal static legendaries come from postgame achievements,
challenging quests and Battle Frontier milestones, never from the Game Corner alone. Which source opens which ticket is
the world's setting (legendary_tickets.DEFAULT_SOURCES, or ``<world>.tickets.json``, read by the launcher before the host
opens): nothing here names a condition.

``reconcile()``, every 5 seconds, after a checkpoint commit and before the PLAYERS page is shown, for each connected
player:

* the player's last save on the host is read and parsed once per checkpoint (its head: revision and SHA-256, as
  tower_service._snapshot reads a save once), into the facts the conditions read (legendary_tickets.save_facts), joined
  with this world's own records (legendary_tickets.with_host_records: the Battle Tower's best floor, the co-op Battle
  Frontier's best streak, the co-op League's clears, the Championships won);
* the ledger is brought up to date (legendary_tickets.reconcile): a met source records the ticket once; its reward word
  (kind 8, reference ``ticket:<name>:<attempt>``) is queued on the player's wallet stream once per reference
  (wagers.Wagers.grant_reward); the game's receipt settles it (1 given, 2 already owned: delivered; 0 no room: owed,
  offered again once the player has saved on the host since); a save that already opens the island settles it without
  a word;
* a ticket just given (receipt 1) is announced in that player's game: ``EON TICKET!`` / ``Show it at LILYCOVE's port.``
  (a refusal for want of room says so too).

The service exists only when the host's installed game applies kind 8 (server.WorldServer.enable_tickets, from the
manifest's ticket_abi_version 1): every player of a world runs that build, so no game without it is ever sent one.
"""
from __future__ import annotations

from . import legendary_tickets as lt
from . import rewards

RECONCILE_SECONDS = 5           # the host's tick (server.WorldServer._monitor)
# The PLAYERS page's short name of each condition: a progress row "<short>: <have>/<need>" fits the menu's 25 characters.
SHORT_NAMES = {
    "hall_of_fame": "Hall of Fame",
    "pokedex": "Kinds caught",
    "coop_league": "Co-op League",
    "regi_trio": "Sealed Chamber",
    "weather_trio": "Weather trio",
    "rayquaza": "Rayquaza",
    "trick_house": "Trick House",
    "championship_wins": "Championships",
    "silver_symbols": "Silver Symbols",
    "gold_symbols": "Gold Symbols",
    "frontier_bp": "Frontier BP",
    "tower_floor": "Tower floor",
    "coop_frontier_streak": "Co-op streak",
}
# Why the player's save cannot be read now (a status line's 31 characters); the page still shows every ticket.
PROBLEMS = {"player_away": "Reconnecting: try again", "no_save": "Save your game first",
            "bad_save": "Your save could not be read"}
# The page's states of a ticket: given (the ledger delivered it, or the save opens its island), on its way (earned, its
# word queued: the game applies it in a calm field), owed (no room: offered again after the next save), locked.
VIEW_STATES = ("given", "sending", "owed", "locked")


class TicketService:
    """Event-loop owned (the world server's); every ledger change commits before returning."""

    def __init__(self, server, sources):
        self.server = server
        self.sources = sources            # legendary_tickets.load_sources / validate_sources: {ticket: (Source, ...)}
        self._saves = {}                  # player -> (revision, sha256, TicketFacts or None, problem or None)
        self.faults = 0                   # passes of a player that raised (reconciled again at the next one)
        self.last_fault = None

    @property
    def book(self):
        return self.server.shared_world.tickets

    # ------------------------------------------------------------------ saves
    def _session(self, player):
        session = self.server.sessions.get(player)
        return None if session is None or session.closed else session

    def _save(self, player):
        """(the facts of the player's last save on the host or None, that checkpoint's revision or None, the problem or
        None). The save is read and parsed once per checkpoint: its head (revision, SHA-256) is compared first."""
        from .flash import FlashError, inspect_flash
        from .storage import StorageError
        session, store = self._session(player), self.server.store
        if session is None:
            return None, None, "player_away"
        if store is None:
            return None, None, "no_save"
        cached = self._saves.get(player)
        try:
            if hasattr(store, "checkpoint_head"):
                head = store.checkpoint_head(player, session.session_epoch)
                if head is not None and cached is not None and cached[:2] == tuple(head):
                    return cached[2], (cached[0] if cached[2] is not None else None), cached[3]
            checkpoint = store.read_checkpoint(player, session.session_epoch)
        except StorageError:
            return None, None, "player_away"           # its lease changed: the player is reconnecting
        if checkpoint is None:
            self._saves.pop(player, None)
            return None, None, "no_save"
        if cached is not None and cached[:2] == (checkpoint.revision, checkpoint.sha256):
            return cached[2], (cached[0] if cached[2] is not None else None), cached[3]
        try:
            snapshot = inspect_flash(checkpoint.payload, save_profile=checkpoint.save_profile)
            facts, problem = lt.save_facts(snapshot.save_block1, snapshot.save_block2, snapshot.tower), None
        except (FlashError, lt.TicketError):
            facts, problem = None, "bad_save"
        self._saves[player] = (checkpoint.revision, checkpoint.sha256, facts, problem)
        return facts, (checkpoint.revision if facts is not None else None), problem

    def _records(self, player) -> dict:
        """This world's own records of the player that conditions read (legendary_tickets.with_host_records)."""
        world = self.server.shared_world
        row = world.tower.player(player)
        wins = 0
        championships = getattr(self.server, "_championships", None)
        if championships is not None:
            try:
                wins = championships.statistics(player)["wins"]
            except Exception:  # noqa: BLE001 - an archive that cannot be read now counts no win (none is taken back)
                wins = 0
        return dict(tower_best=0 if row is None else row["best"],
                    coop_frontier_streak=world.frontier.record(player)["best_streak"],
                    coop_league=world.frontier.league_record(player)["clears"], championship_wins=wins)

    def facts(self, player):
        """(the player's facts: last host save and this world's records, or None while no save can be read; the save's
        revision or None; the problem or None)."""
        facts, revision, problem = self._save(player)
        if facts is not None:
            facts = lt.with_host_records(facts, **self._records(player))
        return facts, revision, problem

    # -------------------------------------------------------------- reconcile
    def reconcile(self, players=None) -> bool:
        """Every connected player's tickets (only ``players`` when given). Safe at any time and any number of times: after
        a restart, a reconnect, a save. Returns whether a word was queued or a banner posted (the world view then goes out
        at once). One player's fault never stops another's; the server's callers keep it from the host loop."""
        if players is None:
            players = [player for player, session in self.server.sessions.items() if not session.closed]
        changed = False
        for player in players:
            if self._session(player) is None:
                continue
            try:
                changed |= self._reconcile_player(player)
            except Exception as error:  # noqa: BLE001 - every ledger step commits alone: the next pass goes on from it
                self.faults += 1
                self.last_fault = f"{type(error).__name__}: {error}"[:200]
        return changed

    def _reconcile_player(self, player) -> bool:
        wagers = self.server.wagers
        facts, revision, _ = self.facts(player)
        before = {row["ticket"]: row["state"] for row in self.book.rows(player)}
        queued = []

        def grant(who, ticket, ref):
            # Kind 8 exists only here, and only because the host's game applies it (enable_tickets).
            seq = wagers.grant_reward(who, rewards.KIND_TICKET, ticket.index, ref, tickets=True)
            if seq is not None:
                queued.append(ref)
            return seq

        def receipt(who, ref):
            entry = wagers.entry(who, ref)
            return None if entry is None else entry["applied"]

        given = lt.reconcile(self.book, player, sources=self.sources, facts=facts, revision=revision, grant=grant,
                             receipt=receipt)
        for ticket in given:
            self._notice(player, *lt.notice(ticket))
        refused = [row["ticket"] for row in self.book.rows(player)
                   if row["state"] == "owed" and before.get(row["ticket"]) == "sent"]
        for key in refused:
            self._notice(player, f"NO ROOM FOR THE {lt.TICKET_BY_KEY[key].name.upper()}", "Make room, then save")
        return bool(given or queued or refused)

    def _notice(self, player, first, second) -> None:
        from .shared_world import _banner
        self.server.shared_world.post_notice(_banner(first, second), to=[player])

    # ------------------------------------------------------------------- view
    def view(self, player) -> dict:
        """The player's Legendary Tickets page (PLAYERS > World and my base > Frontier and League > Legendary Tickets):
        each ticket, its island, given or how to earn it (each source of the world's setting with the player's
        progress)."""
        facts, _, problem = self.facts(player)
        rows = {row["ticket"]: row for row in self.book.rows(player)}
        tickets = []
        for ticket in lt.TICKETS:
            row = rows.get(ticket.key)
            if (row is not None and row["state"] == "delivered") or (facts is not None and ticket.key in facts.islands):
                state = "given"
            elif row is None:
                state = "locked"
            else:
                state = "owed" if row["state"] == "owed" else "sending"
            sources = []
            for source in self.sources[ticket.key]:
                have, need = source.progress(facts if facts is not None else lt.TicketFacts())
                sources.append({"text": source.text, "label": source.label, "short": SHORT_NAMES[source.kind],
                                "have": have if facts is not None else None, "need": need,
                                "solo": source.condition.solo})
            tickets.append({"key": ticket.key, "name": ticket.name, "island": ticket.island, "state": state,
                            "earned_by": None if row is None else row["source"], "sources": sources})
        return {"tickets": tickets, "problem": PROBLEMS.get(problem)}


def _printable(value, limit) -> bool:
    return type(value) is str and 0 < len(value) <= limit and all(32 <= ord(c) <= 126 for c in value)


def validate_view(value) -> dict:
    """The host's tickets view as the companion accepts it (TicketService.view); ProtocolError for anything else."""
    from .protocol import ProtocolError

    def refuse():
        raise ProtocolError("invalid_server_message", "invalid Legendary Tickets view")
    if type(value) is not dict or set(value) != {"tickets", "problem"}:
        refuse()
    if value["problem"] is not None and not _printable(value["problem"], 31):
        refuse()
    tickets = value["tickets"]
    if type(tickets) is not list or not 1 <= len(tickets) <= len(lt.TICKETS):
        refuse()
    for ticket in tickets:
        if (type(ticket) is not dict or set(ticket) != {"key", "name", "island", "state", "earned_by", "sources"}
                or not _printable(ticket["key"], 16) or not _printable(ticket["name"], 16)
                or not _printable(ticket["island"], 17) or ticket["state"] not in VIEW_STATES
                or (ticket["earned_by"] is not None and not _printable(ticket["earned_by"], 64))
                or type(ticket["sources"]) is not list or not 1 <= len(ticket["sources"]) <= lt.MAX_SOURCES):
            refuse()
        for source in ticket["sources"]:
            if (type(source) is not dict or set(source) != {"text", "label", "short", "have", "need", "solo"}
                    or not _printable(source["text"], 64) or not _printable(source["label"], 96)
                    or not _printable(source["short"], 14) or type(source["solo"]) is not bool
                    or type(source["need"]) is not int or not 1 <= source["need"] <= 0xFFFF
                    or (source["have"] is not None and (type(source["have"]) is not int
                                                        or not 0 <= source["have"] <= source["need"]))):
                refuse()
    return value


__all__ = ["PROBLEMS", "RECONCILE_SECONDS", "SHORT_NAMES", "TicketService", "VIEW_STATES", "validate_view"]
