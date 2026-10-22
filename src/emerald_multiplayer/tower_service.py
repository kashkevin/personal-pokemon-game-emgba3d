"""The host side of Battle Tower: Legends (docs/battle-tower-legends.md; tower.py holds the durable book, tower_rules.py
the rules, tower_rewards.py the prizes).

Everything that touches the rest of the server goes through here: the players' saves (their Tower records, badges, Battle
Points and parties), the team desk, the native battle desk (Duo battles), the released co-op results, the wallet stream
and the in-game notices. The host is enabled only when its installed game has the Tower (WorldServer.enable_tower).

* **Solo:** the player's Players menu asks for a floor; the host checks it (one Tower battle at a time, the player's
  progress floor or a floor already cleared, a readable save with a Pokemon able to battle, no unsettled result) and
  records a ticket *before* answering with the command the game's window takes (menu flags 4). The game reports the
  battle as world action 7: started, then won / lost / drew (kept in its save and posted again until settled), or refused.
* **Results:** a result settles its ticket once, in one transaction with the player's progress and every wallet word it
  pays. Every won / lost / drew report is answered with a Tower state word carrying that ticket's low byte, which is what
  lets the game clear its unsettled result: for a ticket this world never issued, a voided one or one settled long ago, a
  word with the ledger's progress that changes nothing else.
* **Interrupted battles:** a command never started for 120 s is void; a started battle that never reports is a loss
  (forfeit) once its player asks for another Tower battle at least 15 s after their game connected, or after 24 hours.
  A Duo battle follows the native recovery; one abandoned without a result is void for both.
* **Duo:** a host-formed team of two (PLAYERS > Invite to team) forms a Duo session: invite, accept, choose a floor and
  the team (at most three each, the Frontier's selection), both ready; the second Ready issues the native co-op battle
  (BattleDesk.invite_coop with the floor's Tower code), entered from PLAYERS > Challenges as any co-op battle.
* **Paying:** the settlement plans the words (Tower state, money, items, Battle Points, claims, milestone Pokemon) and
  ``pay`` queues each on the player's wallet stream exactly once per (player, reference) (wagers.py). The receipts come
  back: a Tower state word's is the save record's revision, a milestone Pokemon's says whether it was made (no room: it
  stays owed and the player sends it again from the Tower page).
* **The Tower Shop:** debit first, like the Frontier shop (the points come back when nothing can be given).

``reconcile()`` is the single place that turns time, receipts and released co-op results into progress and prizes; it is
safe to call at any time, any number of times, after a restart or a reconnect.
"""
from __future__ import annotations

import random
import time
from uuid import uuid4

from . import coop_code, rewards, tower_data, tower_rewards
from .frontier import FrontierError
from .frontier_service import FrontierService
from .tower import DUO, OPEN, SETTLED, SOLO, TowerError
from .tower_data import TowerDataError
from .tower_rules import (CLIMBED, TowerRuleError, can_fight, checkpoint, choose_milestone, duo_floor_allowed,
                          is_progression, milestone_level, party_training, save_cap)

ISSUED_SECONDS = 120              # a solo command the game never started is void after this
STARTED_SECONDS = 24 * 3600       # a started solo battle that never reports is a loss after this
CONNECTION_SECONDS = 15           # ... or when its player asks for another battle this long after their game connected
DUO_BRING = 3                     # each player of a Duo brings at most three Pokemon (the Frontier's team selection)
OUTCOMES = {1: "won", 2: "lost", 3: "drew"}   # a released co-op battle's outcome (frontier.FrontierBook.coop_result)
# The native battle desk's refusals of a Duo battle, as a status line says them.
DESK_REFUSALS = {"battle_busy": "Finish the other battle first", "player_offline": "Your teammate is offline",
                 "trade_recovery_required": "Finish the earlier trade", "checkpoint_required": "Save your games first",
                 "no_pokemon": "Get a Pokemon in Birch's lab", "peer_no_pokemon": "Your teammate has no Pokemon",
                 "stale_lease": "Connection changed: try again", "battle_reservation_conflict": "Finish the other battle first"}


class _Saves(FrontierService):
    """The co-op Battle Frontier's readings of a save (the Duo's team selection, Battle Points), from the Tower's own
    parsed saves (one parse per checkpoint, however often a page reads it)."""

    def __init__(self, server, tower):
        super().__init__(server, party_limit=DUO_BRING)
        self._tower = tower

    def _party(self, player):
        from .frontier_rules import party_bytes, party_slots
        try:
            block1 = self._tower._snapshot(player).save_block1
        except TowerError as error:
            raise FrontierError(error.code, error.message) from error
        data, count = party_bytes(block1)
        return data, count, party_slots(block1)

    def battle_points(self, player):
        from .frontier_service import held_battle_points
        try:
            snapshot = self._tower._snapshot(player)
        except TowerError:
            return None
        return held_battle_points(self.server, player, snapshot)


class TowerService:
    def __init__(self, server, *, rng=None, monotonic=time.monotonic):
        self.server = server
        self._rng = rng if rng is not None else random.SystemRandom()
        self._mono = monotonic
        self._parsed = {}         # (player, checkpoint sha256) -> its parsed save (a few, newest last)
        # Saves, Battle Points and the Duo's team selection are read exactly as the co-op Battle Frontier reads them.
        self._frontier = _Saves(server, self)

    @property
    def book(self):
        return self.server.shared_world.tower

    # ------------------------------------------------------------------ saves
    def _snapshot(self, player):
        """The player's last saved game (the host's checkpoint), or TowerError saying why it cannot be read."""
        from .flash import FlashError, inspect_flash
        from .storage import StorageError
        server = self.server
        session = server.sessions.get(player)
        if session is None or session.closed:
            raise TowerError("player_away", f"{self._name(player)} is not connected")
        try:
            checkpoint_ = server.store.read_checkpoint(player, session.session_epoch) if server.store is not None else None
        except StorageError as error:
            raise TowerError("player_away", f"{self._name(player)} is reconnecting") from error
        if checkpoint_ is None:
            raise TowerError("no_save", "Save your game first")
        key = (player, checkpoint_.sha256)
        if key not in self._parsed:
            try:
                snapshot = inspect_flash(checkpoint_.payload, save_profile=checkpoint_.save_profile)
            except FlashError as error:
                raise TowerError("bad_save", f"{self._name(player)}: save unreadable") from error
            self._parsed = {k: v for k, v in self._parsed.items() if k[0] != player}
            self._parsed[key] = snapshot
            while len(self._parsed) > 8:
                self._parsed.pop(next(iter(self._parsed)))
        return self._parsed[key]

    def _name(self, player) -> str:
        return self.server._player_name(player)[:12]

    def _outstanding(self, player) -> int:
        """Tower words on the player's wallet stream that the game may have applied without the host having its receipt
        yet (each may have raised the save record's revision by one)."""
        wagers = self.server.wagers
        base = wagers.applied_seq(player)
        count = 0
        for word in self.book.words_in_flight():
            if word["player_id"] == player and word["kind"] in rewards.TOWER_KINDS:
                entry = wagers.entry(player, word["ref"])
                count += entry is None or entry["seq"] > base
        return count

    def _sync(self, player) -> dict:
        """The player's Tower row, created from (or brought up to date with) their save's Tower record: the import rule
        (tower.py). Raises TowerError when the player has no row and no readable save."""
        try:
            snapshot = self._snapshot(player)
        except TowerError:
            current = self.book.player(player)
            if current is None:
                raise
            return current
        row, imported = self.book.sync(player, self.server._player_name(player), snapshot.tower,
                                       outstanding=self._outstanding(player))
        return row

    def _save_info(self, player) -> dict | None:
        try:
            snapshot = self._snapshot(player)
        except TowerError:
            return None
        badges, champion, cap = save_cap(snapshot.save_block1)
        return {"badges": badges, "champion": champion, "cap": cap, "bp": self._frontier.battle_points(player)}

    def _chooser(self, players):
        """The milestone choice for a settlement: (player, milestone, floor) -> (species, name, level), or None while no
        species can be made (no floor data, an unreadable save, none legal at that level: the milestone waits). The caps
        are read before the settlement's transaction; the species is a recorded random choice."""
        try:
            data = tower_data.load()
        except TowerDataError:
            return None
        caps = {player: (info or {}).get("cap") for player in players for info in (self._save_info(player),)}

        def choose(player, milestone, floor):
            cap = caps.get(player)
            if cap is None:
                return None
            level = milestone_level(floor, cap)
            entry = choose_milestone(data.legendary_species if milestone == 3 else data.milestone_species, level,
                                     self._rng)
            return None if entry is None else (entry.species, entry.name, level)
        return choose

    # -------------------------------------------------------------------- view
    def view(self, actor) -> dict:
        self.reconcile()
        book, problem = self.book, None
        try:
            row = self._sync(actor)
        except TowerError as error:
            row, problem = None, {"code": error.code, "message": error.message}
        reason = tower_data.unavailable()
        try:
            table_hash = tower_data.load().table_hash
        except TowerDataError:
            table_hash = None
        out = {"available": reason is None, "unavailable": reason, "table_hash": table_hash, "problem": problem,
               "player": self._player_view(row), "save": self._save_info(actor), "battle": None, "last": None,
               "milestones": [], "duo": None, "teammate": None, "team": self._frontier.team_view(actor),
               "shop": [{"slot": i, "name": e.name, "price": e.price} for i, e in enumerate(tower_rewards.SHOP)],
               "purchase": None, "records": [], "party": self._party_view(actor)}
        ticket = book.open_ticket(actor)
        if ticket is not None:
            out["battle"] = {"ticket": ticket["number"], "mode": ticket["mode"], "floor": ticket["floor"],
                             "state": ticket["state"], "progression": ticket["progression"],
                             "age": max(0, int(book._now() - ticket["created"]))}
        last = book.last_ticket(actor)
        if last is not None and last["state"] not in OPEN:
            result = last["result"] or {}
            out["last"] = {"floor": last["floor"], "mode": last["mode"], "state": last["state"], "reason": last["reason"],
                           "progression": last["progression"], "after": result.get("after"),
                           "reward": result.get("reward")}
        for milestone in book.milestones_of(actor):
            out["milestones"].append({key: milestone[key] for key in ("milestone", "floor", "state", "name", "level")})
        purchase = book.last_purchase(actor)
        if purchase is not None:
            out["purchase"] = {"state": purchase["state"], "price": purchase["price"],
                               "name": tower_rewards.ITEM_NAMES.get(purchase["item"], "item")}
        teammate = self.server._teammate(actor)
        if teammate is not None:
            try:
                mate = self._sync(teammate)
            except TowerError:
                mate = None
            out["teammate"] = {"player_id": teammate, "name": self._name(teammate),
                               "progress": mate["progress"] if mate else 1, "highest": mate["highest"] if mate else 0}
        out["duo"] = self._duo_view(actor, teammate)
        out["records"] = [{"name": entry["name"][:12], "best_solo": entry["best_solo"], "best_duo": entry["best_duo"],
                           "completions": entry["completions"], "wins": entry["wins"], "me": entry["player_id"] == actor}
                          for entry in book.ranking()]
        return out

    @staticmethod
    def _player_view(row) -> dict:
        if row is None:
            return {"known": False, "progress": 1, "highest": 0, "checkpoint": 0, "claims": 0, "best": 0,
                    "best_solo": 0, "best_duo": 0, "wins": 0, "losses": 0, "battles": 0, "completions": 0}
        return {"known": True, "progress": row["progress"], "highest": row["highest"],
                "checkpoint": checkpoint(row["highest"]), "claims": row["claims"], "best": row["best"],
                "best_solo": row["best_solo"],
                "best_duo": row["best_duo"], "wins": row["wins"], "losses": row["losses"], "battles": row["battles"],
                "completions": row["completions"]}

    def _party_view(self, player) -> list:
        """The saved party's natural IVs and Hyper Training (the Tower page's Hyper Training information)."""
        from .species_labels import NAMES
        try:
            party = party_training(self._snapshot(player).save_block1)
        except (TowerError, ValueError):
            return []
        return [{"name": "Egg" if mon["egg"] else NAMES[mon["species"]] if 0 < mon["species"] < len(NAMES) else "Pokemon",
                 "level": mon["level"], "egg": mon["egg"], "ivs": mon["ivs"], "trained": mon["trained"]} for mon in party]

    def _duo_view(self, actor, teammate) -> dict | None:
        duo = self.book.duo_of(actor)
        if duo is None:
            return None
        if duo["state"] in ("invited", "forming") and teammate not in duo["players"]:
            duo = self.book.end_duo(duo["duo_id"], "team_changed")     # the team was dissolved: the Duo ends with it
        members = []
        for player in duo["players"]:
            row = self.book.player(player)
            progress, highest = (row["progress"], row["highest"]) if row else (1, 0)
            team = self._frontier.team_view(player)
            members.append({"player_id": player, "name": self._name(player), "progress": progress, "highest": highest,
                            "progression": is_progression(progress, duo["floor"]),
                            "ready": player in duo["ready"], "consent": player in duo["consent"],
                            "team": None if team is None else [s["name"] for s in team["slots"] if s["selected"]]})
        native = None
        desk = self.server.battle_desk
        if duo["battle_id"] is not None and desk is not None:
            battle = desk._active.get(duo["battle_id"]) or desk._history.get(duo["battle_id"])
            native = None if battle is None else battle.state
        return {"duo_id": duo["duo_id"], "state": duo["state"], "floor": duo["floor"], "proposer": duo["players"][0],
                "reason": duo["reason"], "battle_id": duo["battle_id"], "native": native, "members": members}

    # ---------------------------------------------------------------- requests
    def request(self, session, request) -> dict:
        from .shared_world import SharedWorldError
        op, actor = request["op"], session.player_id
        if op == "status":
            return self.view(actor)
        self.reconcile()
        command = None
        try:
            if op == "solo":
                command = self._solo(session, request["floor"])
            elif op == "duo_invite":
                self._duo_invite(session, request["floor"])
            elif op in ("duo_accept", "duo_decline", "duo_leave"):
                self._duo_answer(session, op)
            elif op == "duo_floor":
                self._duo_floor(session, request["floor"])
            elif op in ("duo_ready", "duo_unready"):
                self._duo_ready(session, request, op == "duo_ready")
            elif op == "bring":
                self._bring(session, request["mask"])
            elif op == "shop_buy":
                self._shop_buy(session, request["slot"])
            elif op == "milestone_send":
                self._milestone_send(session, request["milestone"])
        except (TowerError, TowerRuleError, FrontierError) as error:
            raise SharedWorldError(error.code, error.message) from error
        self.server._broadcast_world()
        view = self.view(actor)
        if command is not None:
            view["command"] = command
        return view

    def _data(self):
        try:
            return tower_data.load()
        except TowerDataError as error:
            raise TowerError("tower_unavailable", error.reason) from error

    def _ready_player(self, player) -> dict:
        """The player's synced row, for an action that changes something (refused when their save cannot be read)."""
        self._snapshot(player)
        return self._sync(player)

    def _unsettled_in_game(self, player) -> bool:
        """A Tower state word that settles a solo result in the save is decided but not yet applied by the game: until it
        is, the game refuses every new solo battle, so the host does not issue one."""
        wagers = self.server.wagers
        base = wagers.applied_seq(player)
        for word in self.book.unapplied_state_words(player):
            state = rewards.decode_tower_state(word["payload"])
            if state[0] != "progress" or not state[3]:
                continue
            entry = wagers.entry(player, word["ref"]) if word["state"] == "queued" else None
            if word["state"] == "planned" or entry is None or entry["seq"] > base:
                return True
        return False

    def _free(self, session) -> None:
        """One Tower battle at a time. A started solo battle that never reported is forfeited (a loss) when its player
        asks for another one at least CONNECTION_SECONDS after their game connected (it posts any result it kept right
        after connecting); that ask is answered with the forfeit (its word reaches the game before any new battle). A
        command not yet started still has its time."""
        player = session.player_id
        ticket = self.book.open_ticket(player)
        if ticket is not None:
            if ticket["mode"] == SOLO and ticket["state"] == "started":
                if self._mono() - getattr(session, "connected", 0.0) < CONNECTION_SECONDS:
                    raise TowerError("tower_result_pending", f"Waiting for floor {ticket['floor']}'s result")
                self._forfeit(ticket)
                raise TowerError("tower_forfeited", f"Floor {ticket['floor']}: counted as a loss")
            if ticket["mode"] == SOLO:
                raise TowerError("tower_busy", f"Floor {ticket['floor']} is starting")
            raise TowerError("tower_busy", "Finish your Duo battle first")
        if self._unsettled_in_game(player):
            raise TowerError("tower_saving", "Your game is saving a result")

    def _solo(self, session, floor) -> dict:
        actor = session.player_id
        data = self._data()
        self._ready_player(actor)
        if session.presence is None:
            raise TowerError("game_away", "Your game is not connected")
        self._free(session)
        row = self.book.player(actor)
        duo = self.book.duo_of(actor)
        if duo is not None and duo["state"] == "battle":
            raise TowerError("tower_busy", "Finish your Duo battle first")
        if not can_fight(row["progress"], row["highest"], floor):
            if row["progress"] == CLIMBED or floor <= row["highest"]:
                raise TowerError("tower_floor_locked", f"Floor {floor} is not open")
            raise TowerError("tower_floor_locked", f"Clear floor {row['progress']} first")
        members = [slot for slot in self._frontier._party(actor)[2] if not slot.egg]
        if not members:
            raise TowerError("no_pokemon", "Get a Pokemon in Birch's lab")
        if not any(slot.hp for slot in members):
            raise TowerError("no_pokemon", "Heal a Pokemon first")
        ticket = self.book.issue_solo(actor, floor)
        return {"ticket": ticket["number"], "floor": floor, "table_hash": data.table_hash}

    # ------------------------------------------------------------- the results
    def result(self, session, request) -> dict:
        """World action 7 as the companion forwards it: a solo battle started, was refused, or ended (won, lost, drew)."""
        actor, number, floor, outcome = session.player_id, request["ticket"], request["floor"], request["outcome"]
        self.reconcile()
        ticket = self.book.ticket_by_number(number)
        mine = ticket is not None and ticket["player_id"] == actor and ticket["mode"] == SOLO
        matching = mine and ticket["floor"] == floor
        if outcome == "started":
            if matching and ticket["state"] == "issued":
                ticket = self.book.start(ticket["ticket_id"])
        elif outcome == "refused":
            if matching and ticket["state"] == "issued":
                ticket = self.book.void(ticket["ticket_id"], "refused")
                self._notice([actor], f"TOWER FLOOR {floor}", "Your game refused the battle")
        elif matching and ticket["state"] in OPEN:
            settled = self.book.settle(ticket["ticket_id"], outcome, choose=self._chooser([actor]))
            if settled is not None:
                ticket = settled
                self._settled_notice(settled)
        else:
            self._answer_result(actor, ticket if mine else None, number)
        self.pay()
        self.server._broadcast_world()
        return {"seq": request["seq"], "ticket": number, "state": ticket["state"] if mine else "unknown"}

    def _answer_result(self, player, ticket, number) -> None:
        """A won / lost / drew report the ledger cannot apply (a ticket this world never issued, another player's, a
        voided one, a repeat after its settlement, a contradiction) still gets a Tower state word with its ticket's low
        byte, or the game would keep the result (and refuse every new solo battle) for ever. The word carries the
        ledger's P and H (the save's own when the player has no row yet: the import) and changes nothing else."""
        if ticket is None:
            ref = f"tower:clear:{number}"
        else:
            ref = f"tower:{ticket['ticket_id']}:clear"
            if ticket["state"] in SETTLED:
                # Its settlement's own state word already carries the low byte; until the game has applied that one it
                # clears the result, so a second word is needed only once that one has landed.
                state = next((w for w in self.book.words_of(player, ticket["ticket_id"]) if w["position"] == 0), None)
                if state is not None and state["applied"] is None:
                    return
        try:
            self._sync(player)
        except TowerError:
            return            # no row and no readable save yet: the game reports again, and is answered then
        self.book.plan_clear(player, ref, number)

    def _forfeit(self, ticket) -> None:
        settled = self.book.settle(ticket["ticket_id"], "lost", choose=None, forfeit=True)
        if settled is not None:
            self._notice([ticket["player_id"]], f"TOWER FLOOR {ticket['floor']}: NO RESULT",
                         "It counted as a loss")
            self.pay()

    def _settled_notice(self, ticket) -> None:
        result = ticket["result"] or {}
        progress, _ = result.get("after") or (None, None)
        reward = result.get("reward")
        floor = ticket["floor"]
        if ticket["state"] == "won":
            tail = f"+{reward['bp']}BP" if reward else ""
            if reward and reward["money"]:
                tail += f" ${reward['money']:,}"
            if reward and reward["items"]:
                tail += " +prize"
            if reward and reward["milestone"] is not None:
                tail += " +Pokemon!"
            self._notice([ticket["player_id"]], f"TOWER FLOOR {floor} CLEARED!", tail.strip())
        elif ticket["progression"] and progress is not None:
            self._notice([ticket["player_id"]], f"TOWER FLOOR {floor} LOST", f"Back to floor {progress}")
        else:
            self._notice([ticket["player_id"]], f"TOWER FLOOR {floor}", "Replay over: no change")

    def _notice(self, players, first, second) -> None:
        from .shared_world import _banner
        self.server.shared_world.post_notice(_banner(first, second), to=list(players))

    # -------------------------------------------------------------------- Duo
    def _teammate(self, session) -> str:
        teammate = self.server._teammate(session.player_id)
        if teammate is None:
            raise TowerError("no_teammate", "Form a team in PLAYERS first")
        return teammate

    def _duo_rows(self, players) -> list[dict]:
        return [self._ready_player(player) for player in players]

    def _duo_invite(self, session, floor) -> None:
        actor = session.player_id
        self._data()
        teammate = self._teammate(session)
        rows = self._duo_rows((actor, teammate))
        if not duo_floor_allowed(floor, *((row["progress"], row["highest"]) for row in rows)):
            raise TowerError("tower_floor_locked", f"Floor {floor} is not open to both")
        if self.book.open_ticket(actor) is not None:
            self._free(session)        # always refused: its reason, or the forfeit of a battle that never reported
        if self.book.open_ticket(teammate) is not None:
            raise TowerError("tower_busy", f"{self._name(teammate)} is in a battle")
        self.book.invite_duo(str(uuid4()), actor, teammate, floor)
        name = self._name(actor).upper()[:10]
        self._notice([teammate], f"TOWER DUO: FLOOR {floor}", f"{name}: PLAYERS > Tower")

    def _open_duo(self, actor) -> dict:
        duo = self.book.duo_of(actor)
        if duo is None or duo["state"] == "ended":
            raise TowerError("no_duo", "There is no Duo: invite first")
        return duo

    def _duo_answer(self, session, op) -> None:
        actor = session.player_id
        duo = self._open_duo(actor)
        if op == "duo_accept":
            if duo["state"] != "invited" or actor == duo["players"][0]:
                raise TowerError("no_duo", "No Duo invitation to accept")
            if self.server._teammate(actor) != duo["players"][0]:
                self.book.end_duo(duo["duo_id"], "team_changed")
                raise TowerError("no_teammate", "Your teammate left the team")
            self._ready_player(actor)
            self.book.accept_duo(duo["duo_id"], actor)
            self._notice(duo["players"], f"TOWER DUO: FLOOR {duo['floor']}", "Choose a team, then Ready")
        else:
            reason = "declined" if op == "duo_decline" and duo["state"] == "invited" and actor != duo["players"][0] \
                else "left"
            self.book.end_duo(duo["duo_id"], reason)
            other = [p for p in duo["players"] if p != actor]
            self._notice(other, "TOWER DUO ENDED", f"{self._name(actor).upper()[:10]} {reason} it")

    def _duo_floor(self, session, floor) -> None:
        duo = self._open_duo(session.player_id)
        rows = self._duo_rows(duo["players"])
        if not duo_floor_allowed(floor, *((row["progress"], row["highest"]) for row in rows)):
            raise TowerError("tower_floor_locked", f"Floor {floor} is not open to both")
        self.book.set_duo_floor(duo["duo_id"], floor)

    def _duo_ready(self, session, request, ready) -> None:
        actor = session.player_id
        duo = self._open_duo(actor)
        if duo["state"] != "forming":
            raise TowerError("no_duo", "Accept the Duo first" if duo["state"] == "invited" else "The Duo battle is open")
        if not ready:
            self.book.set_ready(duo["duo_id"], actor, False)
            return
        self._data()
        teammate = next(p for p in duo["players"] if p != actor)
        if self.server._teammate(actor) != teammate:
            self.book.end_duo(duo["duo_id"], "team_changed")
            raise TowerError("no_teammate", "Your teammate left the team")
        self._ready_player(actor)
        self._free(session)
        self._frontier.check_party(actor)
        duo = self.book.set_ready(duo["duo_id"], actor, True)
        if set(duo["ready"]) == set(duo["players"]):
            self._duo_battle(session, request, duo, teammate)
        else:
            self._notice([teammate], f"TOWER DUO: FLOOR {duo['floor']}", f"{self._name(actor).upper()[:10]} is ready")

    def _duo_battle(self, session, request, duo, teammate) -> None:
        """Both are ready: the second Ready issues the native co-op battle (that player's game runs both trainers)."""
        server, actor = self.server, session.player_id
        try:
            rows = self._duo_rows(duo["players"])
            if not duo_floor_allowed(duo["floor"], *((row["progress"], row["highest"]) for row in rows)):
                raise TowerError("tower_floor_locked", f"Floor {duo['floor']}: not open to both")
            if self.book.open_ticket(teammate) is not None or self._unsettled_in_game(teammate):
                raise TowerError("tower_busy", f"{self._name(teammate)} is in a battle")
            self._frontier.check_party(teammate)
            if server.battle_desk is None:
                raise TowerError("battle_disabled", "Duo battles are off here")
            capture = server.battle_execution is not None and server.battle_execution.resume_enabled
            if capture and "runtime_id" not in request:
                raise TowerError("battle_original_core_required", "Update your game files")
        except (TowerError, FrontierError):
            self.book.set_ready(duo["duo_id"], actor, False)
            raise
        battle_id = str(uuid4())
        self.book.issue_duo(duo["duo_id"], battle_id)      # the intent is durable before anybody is invited
        try:
            server._assert_battle_available(actor, teammate)
            brings = {player: mask for player in (actor, teammate) if (mask := self._frontier.team(player)[0])}
            server.battle_desk.invite_coop(actor, session.session_epoch, teammate, coop_code.encode_tower(duo["floor"]),
                                           battle_id, brings=brings or None)
            if capture:
                fields = {k: v for k, v in request.items() if k in ("incarnation", "runtime_id")}
                server.battle_execution.admission.capture(actor, session.session_epoch, dict(fields, battle_id=battle_id))
        except Exception as error:  # noqa: BLE001 - nothing started: the Duo is offered again
            self.book.void_battle(battle_id, "not_started")
            code = getattr(error, "code", "battle_unavailable")
            raise TowerError(code, DESK_REFUSALS.get(code, (getattr(error, "message", None) or str(error))[:31])) \
                from error
        name = self._name(actor).upper()[:10]
        self._notice([teammate], f"TOWER FLOOR {duo['floor']} (DUO)", f"{name}: PLAYERS > Challenges")
        self._notice([actor], f"TOWER FLOOR {duo['floor']} (DUO)", "PLAYERS > Challenges")

    def _bring(self, session, mask) -> None:
        """The Duo team: the player's Frontier team selection (frontier_bring), at most three; never during a battle."""
        actor = session.player_id
        ticket = self.book.open_ticket(actor)
        if ticket is not None and ticket["mode"] == DUO:
            raise TowerError("tower_busy", "Not during a Duo battle")
        self._frontier._bring(session, {"mask": mask})
        duo = self.book.duo_of(actor)
        if duo is not None and duo["state"] == "forming" and actor in duo["ready"]:
            self.book.set_ready(duo["duo_id"], actor, False)      # a new team needs a new Ready

    # ------------------------------------------------- milestones and the shop
    def _milestone_send(self, session, milestone) -> None:
        actor = session.player_id
        self._snapshot(actor)
        ticket = self.book.open_ticket(actor)
        if ticket is not None:
            raise TowerError("tower_busy", "Finish your Tower battle first")
        self.book.resend_milestone(actor, milestone)
        self.pay()

    def _shop_buy(self, session, slot) -> None:
        actor = session.player_id
        if not 0 <= slot < len(tower_rewards.SHOP):
            raise TowerError("no_such_item", "The shop does not sell that")
        entry = tower_rewards.SHOP[slot]
        if self.book.open_ticket(actor) is not None:
            raise TowerError("tower_busy", "Finish your Tower battle first")
        if self.book.open_purchase(actor) is not None:
            raise TowerError("purchase_open", "Your last order is not done")
        known = self._frontier.battle_points(actor)
        if known is not None and known < entry.price:
            raise TowerError("not_enough_bp", f"{entry.price} BP needed, you have {known}")
        wagers = getattr(self.server, "wagers", None)
        if wagers is None:
            raise TowerError("no_wallet", "This host has no wallet")
        purchase_id = str(uuid4())
        self.book.start_purchase(purchase_id, actor, entry.item, entry.quantity, entry.price)
        try:
            wagers.grant_reward(actor, rewards.KIND_BP_DEBIT, entry.price, f"tower-shop:{purchase_id}:debit")
        except Exception:
            self.book.set_purchase(purchase_id, "void")     # nothing was taken: the order never holds the shop
            raise

    def _advance_purchases(self) -> None:
        """Move every open purchase one step: the game's receipt for the debit decides whether the item is given."""
        wagers = getattr(self.server, "wagers", None)
        if wagers is None:
            return
        book = self.book
        for purchase in book.open_purchases():
            pid, player = purchase["purchase_id"], purchase["player_id"]
            if purchase["state"] == "debit":
                entry = wagers.entry(player, f"tower-shop:{pid}:debit")
                if entry is None:
                    # The debit was never queued (the host stopped between the order and its debit, in two databases):
                    # nothing was taken, and the order must not hold the shop for ever.
                    book.set_purchase(pid, "void")
                    continue
                if entry["applied"] is None:
                    continue
                paid = entry["applied"]
                if paid >= purchase["price"]:
                    wagers.grant_reward(player, rewards.KIND_ITEM,
                                        rewards.item_payload(purchase["item"], purchase["quantity"]), f"tower-shop:{pid}:item")
                    book.set_purchase(pid, "granting")
                else:   # the save had fewer points than the host's view of its last save: what was taken comes back
                    if paid > 0:
                        wagers.grant_reward(player, rewards.KIND_BP, paid, f"tower-shop:{pid}:refund")
                    book.set_purchase(pid, "refused")
            else:
                entry = wagers.entry(player, f"tower-shop:{pid}:item")
                if entry is None or entry["applied"] is None:
                    continue
                if entry["applied"] >= purchase["quantity"]:
                    book.set_purchase(pid, "done")
                else:   # the bag and the PC were full: the points come back
                    wagers.grant_reward(player, rewards.KIND_BP, purchase["price"], f"tower-shop:{pid}:refund")
                    book.set_purchase(pid, "refunded")

    # --------------------------------------------------------------- reconcile
    def reconcile(self) -> None:
        """Expire, forfeit and void what time decided; settle released Duo results; record receipts; choose waiting
        milestone Pokemon; pay what is owed; move the shop along. Idempotent."""
        book = self.book
        self._collect_receipts()
        now = book._now()
        for ticket in book.open_tickets(SOLO):
            if ticket["state"] == "issued" and now - ticket["created"] >= ISSUED_SECONDS:
                book.void(ticket["ticket_id"], "expired")
            elif ticket["state"] == "started" and now - (ticket["started"] or ticket["created"]) >= STARTED_SECONDS:
                self._forfeit(ticket)
        self._reconcile_duo()
        for milestone in book.waiting_milestones():
            choose = self._chooser([milestone["player_id"]])
            if choose is not None:
                choice = choose(milestone["player_id"], milestone["milestone"], milestone["floor"])
                if choice is not None:
                    book.choose_milestone(milestone["player_id"], milestone["milestone"], choice)
        self.pay()
        self._advance_purchases()

    def _reconcile_duo(self) -> None:
        """A Duo battle's fate, exactly as the Frontier reads a co-op battle's: its released outcome settles both
        players; a battle proven never started, or abandoned without a result, is void for both."""
        server, book = self.server, self.book
        desk = server.battle_desk
        if desk is not None:
            try:
                desk.refresh()
            except Exception:  # noqa: BLE001 - a lifecycle hook never blocks progress reading
                pass
        for battle_id in dict.fromkeys(t["battle_id"] for t in book.open_tickets(DUO)):
            outcome = server.shared_world.frontier.coop_result(battle_id)
            if outcome is not None:
                tickets = book.tickets_of_battle(battle_id)
                choose = self._chooser([t["player_id"] for t in tickets])
                settled = book.settle(tickets[0]["ticket_id"], OUTCOMES[outcome], choose=choose)
                if settled is not None:
                    for ticket in book.tickets_of_battle(battle_id):
                        self._settled_notice(ticket)
                continue
            native = None if desk is None else desk._active.get(battle_id) or desk._history.get(battle_id)
            reservations = server._battle_reservations
            terminal = reservations.terminal(battle_id) if reservations is not None else None
            if terminal is not None and terminal.kind == "aborted":
                book.void_battle(battle_id, "abandoned")         # aborted before it started, or abandoned without a result
                continue
            if server.battle_execution is not None and server.battle_execution.admission.terminal(battle_id) is not None:
                book.void_battle(battle_id, "abandoned")
                continue
            reserved = reservations is not None and reservations.contains(battle_id)
            consented = server.battle_execution is not None and server.battle_execution.admission.has_consent(battle_id)
            if native is None:
                if not reserved and not consented and desk is not None:
                    book.void_battle(battle_id, "not_started")    # it never reached a native hold
            elif native.state == "aborted" and not reserved:
                book.void_battle(battle_id, "not_started")

    def _collect_receipts(self) -> None:
        """What each game reported for the Tower words it was sent: revisions, and milestone Pokemon made or not."""
        wagers = getattr(self.server, "wagers", None)
        if wagers is None:
            return
        for word in self.book.words_in_flight():
            entry = wagers.entry(word["player_id"], word["ref"])
            if entry is None or entry["applied"] is None:
                continue
            self.book.word_receipt(word["player_id"], word["ref"], entry["applied"])
            if word["kind"] == rewards.KIND_TOWER_MON:
                # 1 made, 2 already delivered to this save (nothing made), 0 nothing made: 1 and 2 count as delivered.
                milestone = self.book.milestone(word["player_id"], word["payload"] >> 22)
                if entry["applied"] == 1:
                    self._notice([word["player_id"]], "TOWER MILESTONE POKEMON!",
                                 f"{(milestone or {}).get('name') or 'It'} joined you!")
                elif not entry["applied"]:
                    self._notice([word["player_id"]], "NO ROOM FOR YOUR POKEMON", "Make room: PLAYERS > Tower")

    def pay(self) -> None:
        """Queue every planned word on its player's wallet stream, in the order decided, once per (player, reference)."""
        wagers = getattr(self.server, "wagers", None)
        if wagers is None:
            return
        from .wagers import WagerError
        blocked, queued = set(), False
        for word in self.book.planned_words():
            player = word["player_id"]
            if player in blocked:
                continue   # a player's words keep their order: nothing after one that could not be queued
            try:
                if word["kind"] == 0:
                    wagers.grant(player, word["payload"], word["ref"])
                else:
                    wagers.grant_reward(player, word["kind"], word["payload"], word["ref"], tower=True)
            except WagerError:
                blocked.add(player)
                continue
            self.book.word_queued(player, word["ref"])
            queued = True
        if queued:
            self.server._broadcast_world()


__all__ = ["CONNECTION_SECONDS", "DUO_BRING", "ISSUED_SECONDS", "STARTED_SECONDS", "TowerService"]
