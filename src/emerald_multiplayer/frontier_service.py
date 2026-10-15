"""The host side of the cooperative Battle Frontier (frontier.py holds the rules and the durable book).

Everything that touches the rest of the server goes through here: the team, the saved parties, the native battle desk,
the released battle results, the wallet and the in-game notices. `reconcile()` is the single place that turns a released
battle result (or the proof that a battle never started) into progress and prizes; it is safe to call at any time, any
number of times, after a restart or a reconnect, because every step it takes happens at most once.
"""
from __future__ import annotations

from uuid import uuid4

from . import coop_code
from .frontier import FrontierBook, FrontierError, Plan, TRAINER_NAMES, plan, prize_for, set_of
from .protocol import ProtocolError

PARTY_LIMIT_DEFAULT = 3
MIN_PARTY = 1


def levels_of_party(members) -> int:
    """The Frontier's measure of a trainer: the average level of the Pokemon they bring."""
    return round(sum(m.level for m in members) / len(members)) if members else 0


class FrontierService:
    def __init__(self, server, *, party_limit: int = PARTY_LIMIT_DEFAULT):
        self.server = server
        self.party_limit = party_limit

    @property
    def book(self) -> FrontierBook:
        return self.server.shared_world.frontier

    # ------------------------------------------------------------- parties
    def _members(self, player):
        """The non-egg Pokemon of the player's last saved party (the one a native battle will check)."""
        from .flash import FlashError, inspect_flash
        from .frontier_rules import party_members
        server = self.server
        session = server.sessions.get(player)
        if session is None or session.closed:
            raise FrontierError("player_away", "your teammate is not connected")
        checkpoint = server.store.read_checkpoint(player, session.session_epoch) if server.store is not None else None
        if checkpoint is None:
            raise FrontierError("no_save", f"{session.display_name[:10]} has no saved party yet")
        try:
            return party_members(inspect_flash(checkpoint.payload, save_profile=checkpoint.save_profile).save_block1)
        except FlashError as error:
            raise FrontierError("bad_save", f"{session.display_name[:10]}'s save cannot be read") from error

    def check_party(self, player) -> list:
        members = self._members(player)
        name = self.server._player_name(player)[:10]
        if len(members) < MIN_PARTY:
            raise FrontierError("no_pokemon", f"{name} has no Pokemon to bring")
        if len(members) > self.party_limit:
            raise FrontierError("too_many", f"{name}: bring at most {self.party_limit} Pokemon")
        return members

    def base_level(self, players) -> int:
        return min(levels_of_party(self.check_party(player)) for player in players)

    # ---------------------------------------------------------------- view
    def view(self, player) -> dict:
        book = self.book
        self.reconcile()
        run = book.run_of(player)
        record = book.record(player)
        out = {"record": record, "party_limit": self.party_limit, "run": None}
        if run is None:
            return out
        names = [self.server._player_name(p)[:12] for p in run["players"]]
        attempt = book.open_attempt(run["run_id"])
        info = {"run_id": run["run_id"], "state": run["state"], "players": run["players"], "names": names,
                "consent": run["consent"], "round": run["round"], "streak": run["streak"],
                "ended_reason": run["ended_reason"], "battle_id": attempt["battle_id"] if attempt else None,
                "next": None}
        if run["state"] == "active":
            try:
                base = self.base_level(run["players"])
            except FrontierError:
                base = None
            if base is not None:
                p = plan(run["seed"], run["round"], base)
                first = run["round"] > min(book.record(x)["best_streak"] for x in run["players"])
                info["next"] = {"round": p.round, "level": p.level, "label": p.label, "brain": p.brain,
                                "set": set_of(p.round) + 1, "prize": prize_for(p.level, p.round, first_time=first)}
        out["run"] = info
        return out

    # ------------------------------------------------------------ requests
    def request(self, session, request) -> dict:
        op, actor, server = request["op"], session.player_id, self.server
        if op == "status":
            return self.view(actor)
        self.reconcile()
        try:
            if op == "propose":
                self._propose(session)
            elif op == "accept":
                self._accept(session)
            elif op in ("cancel", "retire"):
                self._cancel(session, op)
            elif op == "battle":
                self._battle(session, request)
        except FrontierError as error:
            from .shared_world import SharedWorldError
            raise SharedWorldError(error.code, error.message) from error
        server._broadcast_world()
        return self.view(actor)

    def _teammate(self, session) -> str:
        teammate = self.server._teammate(session.player_id)
        if teammate is None:
            raise FrontierError("no_teammate", "form a team in the Players menu first")
        return teammate

    def _notice(self, first, second, to):
        from .shared_world import _banner
        self.server.shared_world.post_notice(_banner(first, second), to=list(to))

    def _propose(self, session):
        actor, teammate = session.player_id, self._teammate(session)
        self.check_party(actor)
        self.check_party(teammate)
        import random
        run = self.book.propose(str(uuid4()), actor, teammate, random.SystemRandom().randrange(1, 2 ** 31))
        name = self.server._player_name(actor).upper()[:10]
        self._notice("FRONTIER RUN!", f"{name}: open PLAYERS > Frontier", [teammate])
        return run

    def _accept(self, session):
        actor = session.player_id
        run = self.book.run_of(actor)
        if run is None or run["state"] != "forming":
            raise FrontierError("no_run", "there is no Frontier run to join")
        self.check_party(actor)
        run = self.book.accept(run["run_id"], actor)
        if run["state"] == "active":
            self._notice("FRONTIER BEGINS!", "Open PLAYERS > Frontier", run["players"])

    def _cancel(self, session, op):
        actor = session.player_id
        run = self.book.run_of(actor)
        if run is None or run["state"] == "ended":
            raise FrontierError("no_run", "there is no Frontier run")
        if op == "retire" and run["state"] != "active":
            raise FrontierError("not_active", "the run has not begun")
        ended = self.book.end(run["run_id"], "retired" if run["state"] == "active" else "declined")
        if run["state"] == "active":
            self._notice("FRONTIER RETIRED", f"Streak {ended['streak']} kept", ended["players"])

    def _battle(self, session, request):
        server, actor = self.server, session.player_id
        run = self.book.run_of(actor)
        if run is None or run["state"] != "active":
            raise FrontierError("not_active", "there is no active Frontier run")
        teammate = next(p for p in run["players"] if p != actor)
        if server._teammate(actor) != teammate:
            raise FrontierError("no_teammate", "your Frontier teammate must be connected and on your team")
        if server.battle_desk is None:
            raise FrontierError("battle_disabled", "battles are not enabled on this host")
        capture = server.battle_execution is not None and server.battle_execution.resume_enabled
        if capture and "runtime_id" not in request:
            raise FrontierError("battle_original_core_required", "update your game files")
        base = self.base_level(run["players"])
        p = plan(run["seed"], run["round"], base)
        battle_id = str(uuid4())
        self.book.issue(run["run_id"], battle_id, p)      # the intent is durable before anybody is invited
        try:
            server._assert_battle_available(actor, teammate)
            view = server.battle_desk.invite_coop(actor, session.session_epoch, teammate, p.code, battle_id)
            if capture:
                fields = {k: v for k, v in request.items() if k in ("incarnation", "runtime_id")}
                server.battle_execution.admission.capture(actor, session.session_epoch, dict(fields, battle_id=battle_id))
        except Exception as error:  # noqa: BLE001 - nothing started: the round is offered again
            self.book.void(battle_id)
            code = getattr(error, "code", "battle_unavailable")
            raise FrontierError(code, getattr(error, "message", None) or str(error)) from error
        name = server._player_name(actor).upper()[:10]
        self._notice(f"ROUND {p.round}: {p.label.upper()}"[:32], f"{name}: PLAYERS > Challenges", [teammate])
        self._notice(f"ROUND {p.round} LEVEL {p.level}", "PLAYERS > Challenges", [actor])
        return view

    # ----------------------------------------------------------- reconcile
    def reconcile(self) -> None:
        """Settle every issued battle whose fate is known, then pay what is owed. Idempotent."""
        server, book = self.server, self.book
        desk = server.battle_desk
        if desk is not None:
            try:
                desk.refresh()
            except Exception:  # noqa: BLE001 - a lifecycle hook never blocks progress reading
                pass
        for attempt in book.issued():
            battle_id = attempt["battle_id"]
            outcome = book.coop_result(battle_id)
            if outcome is not None:
                settled = book.settle(battle_id, outcome)
                if settled is not None:
                    self._settled_notice(settled)
                continue
            native = None if desk is None else desk._active.get(battle_id) or desk._history.get(battle_id)
            reservations = server._battle_reservations
            terminal = reservations.terminal(battle_id) if reservations is not None else None
            if terminal is not None and terminal.kind == "aborted":
                book.void(battle_id)            # the battle was aborted before it started
                continue
            reserved = reservations is not None and reservations.contains(battle_id)
            consented = (server.battle_execution is not None
                         and server.battle_execution.admission.has_consent(battle_id))
            if native is None:
                if not reserved and not consented and desk is not None:
                    book.void(battle_id)        # it never reached a native hold
            elif native.state == "aborted" and not reserved:
                book.void(battle_id)
        self.pay()

    def _settled_notice(self, attempt):
        run = self.book.run(attempt["run_id"])
        if attempt["state"] == "won":
            top = max(attempt["prizes"].values()) if attempt["prizes"] else 0
            self._notice(f"ROUND {attempt['round']} CLEARED!", f"Prize up to ${top:,}", run["players"])
        elif attempt["state"] == "lost":
            self._notice("FRONTIER RUN OVER", f"Streak {run['streak']} - well fought!", run["players"])

    def pay(self) -> None:
        wagers = getattr(self.server, "wagers", None)
        if wagers is None:
            return
        paid = False
        for attempt in self.book.unpaid():
            for player, amount in attempt["prizes"].items():
                wagers.grant(player, amount, attempt["battle_id"])
            self.book.mark_paid(attempt["battle_id"])
            paid = True
        if paid:
            self.server._broadcast_world()
