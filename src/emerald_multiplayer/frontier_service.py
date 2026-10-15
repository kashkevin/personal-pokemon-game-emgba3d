"""The host side of the cooperative Battle Frontier (frontier.py holds the rules and the durable book).

Everything that touches the rest of the server goes through here: the team, the saved parties, the native battle desk,
the released battle results, the wallet and the in-game notices. `reconcile()` is the single place that turns a released
battle result (or the proof that a battle never started) into progress and prizes; it is safe to call at any time, any
number of times, after a restart or a reconnect, because every step it takes happens at most once.
"""
from __future__ import annotations

from uuid import uuid4

from . import coop_code, frontier_rewards, rewards
from .frontier import (FrontierBook, FrontierError, LEAGUE, LEAGUE_FIRST_CLEAR_BONUS, Plan, TRAINER_NAMES,
                       league_plan, league_prize, plan, prize_for, set_of)
from .protocol import ProtocolError

PARTY_LIMIT_DEFAULT = 3
MIN_PARTY = 1
# The Pokemon League opens with all eight badges, as in the game (flags in the saved game, checked against the engine by
# --selftest-ladder: flags at 0x1270 of the first save block, badge 1 = flag 0x867).
# The player's Battle Points: SaveBlock2.frontier.battlePoints (a u16, offset 0xEB8 of the second save block).
BATTLE_POINTS_OFFSET = 0xEB8
FLAGS_OFFSET = 0x1270
BADGE_FLAGS = tuple(range(0x867, 0x86F))


def count_badges(save_block1: bytes) -> int:
    """The Gym badges (of eight) in a saved game's first block."""
    return sum(bool(save_block1[FLAGS_OFFSET + flag // 8] >> (flag % 8) & 1) for flag in BADGE_FLAGS)


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

    def badges(self, player) -> int:
        """How many of the eight Gym badges the player's last saved game has."""
        from .flash import FlashError, inspect_flash
        server = self.server
        session = server.sessions.get(player)
        if session is None or session.closed or server.store is None:
            raise FrontierError("player_away", "your teammate is not connected")
        checkpoint = server.store.read_checkpoint(player, session.session_epoch)
        if checkpoint is None:
            raise FrontierError("no_save", f"{session.display_name[:10]} has no saved game yet")
        try:
            block1 = inspect_flash(checkpoint.payload, save_profile=checkpoint.save_profile).save_block1
        except FlashError as error:
            raise FrontierError("bad_save", f"{session.display_name[:10]}'s save cannot be read") from error
        return count_badges(block1)

    def check_league(self, player) -> None:
        if self.badges(player) < len(BADGE_FLAGS):
            raise FrontierError("badges", f"{self.server._player_name(player)[:10]} needs all 8 badges")

    def _party(self, player):
        """(raw saved party, its count, every slot) of the player's last saved game."""
        from .flash import FlashError, inspect_flash
        from .frontier_rules import party_bytes, party_slots
        server = self.server
        session = server.sessions.get(player)
        if session is None or session.closed:
            raise FrontierError("player_away", "your teammate is not connected")
        checkpoint = server.store.read_checkpoint(player, session.session_epoch) if server.store is not None else None
        if checkpoint is None:
            raise FrontierError("no_save", f"{session.display_name[:10]} has no saved party yet")
        try:
            block1 = inspect_flash(checkpoint.payload, save_profile=checkpoint.save_profile).save_block1
        except FlashError as error:
            raise FrontierError("bad_save", f"{session.display_name[:10]}'s save cannot be read") from error
        data, count = party_bytes(block1)
        return data, count, party_slots(block1)

    def team(self, player):
        """The Pokemon this player brings: (mask, members, automatic).

        ``mask`` is the team selection the native battle takes (bit n = saved slot n), or 0 for the whole saved party (a
        party of at most ``party_limit`` Pokemon needs no selection). A selection the player made is used while it is still
        valid for their latest save; otherwise the first ``party_limit`` Pokemon in party order (one able to fight) go."""
        from .battle_roster import valid_bring
        data, count, slots = self._party(player)
        usable = [slot for slot in slots if not slot.egg]
        if len(usable) < MIN_PARTY:
            raise FrontierError("no_pokemon", f"{self.server._player_name(player)[:10]} has no Pokemon to bring")
        chosen = self.book.bring(player)
        if chosen and valid_bring(chosen, data, count) and bin(chosen).count("1") <= self.party_limit:
            mask, auto = chosen, False
        elif len(usable) <= self.party_limit:
            mask, auto = 0, True
        else:
            picks = usable[:self.party_limit]
            if not any(slot.hp for slot in picks):
                able = next((slot for slot in usable[self.party_limit:] if slot.hp), None)
                if able is not None:
                    picks = picks[:-1] + [able]
            mask, auto = sum(1 << slot.slot for slot in picks), True
        members = [slot for slot in usable if not mask or mask >> slot.slot & 1]
        return mask, members, auto

    def check_party(self, player) -> list:
        """The Pokemon the player brings (raises when there is none to bring)."""
        return self.team(player)[1]

    def team_view(self, player) -> dict | None:
        from .species_labels import NAMES
        try:
            data, count, slots = self._party(player)
            mask, members, auto = self.team(player)
        except FrontierError:
            return None
        chosen = {slot.slot for slot in members}
        return {"limit": self.party_limit, "auto": auto,
                "slots": [{"slot": slot.slot, "name": NAMES[slot.species] if 0 < slot.species < len(NAMES) else "Pokemon",
                           "level": slot.level, "egg": slot.egg, "able": slot.hp > 0,
                           "selected": slot.slot in chosen} for slot in slots]}

    def _bring(self, session, request) -> None:
        from .battle_roster import valid_bring
        actor, mask = session.player_id, request.get("mask")
        if type(mask) is not int or isinstance(mask, bool) or not 0 <= mask <= 0x3F:
            raise FrontierError("invalid_team", "a team is slots 1 to 6")
        data, count, slots = self._party(actor)
        if mask:
            if not valid_bring(mask, data, count):
                raise FrontierError("invalid_team", "bring Pokemon that exist, are not Eggs and one that can fight")
            if bin(mask).count("1") > self.party_limit:
                raise FrontierError("too_many", f"bring at most {self.party_limit} Pokemon")
        run = self.book.run_of(actor)
        if run is not None and self.book.open_attempt(run["run_id"]) is not None:
            raise FrontierError("battle_open", "change your team between rounds")
        self.book.set_bring(actor, mask)

    def base_level(self, players) -> int:
        return min(levels_of_party(self.check_party(player)) for player in players)

    # ---------------------------------------------------------------- view
    def view(self, player) -> dict:
        book = self.book
        self.reconcile()
        run = book.run_of(player)
        record = book.record(player)
        out = {"team": self.team_view(player), "bp": self.bp_view(player), "record": record, "party_limit": self.party_limit, "run": None,
               "league": {**book.league_record(player), "rounds": len(LEAGUE),
                          "hall": [{"names": e["names"], "entry": e["entry"]} for e in book.hall_of_fame(3)]}}
        if run is None:
            return out
        names = [self.server._player_name(p)[:12] for p in run["players"]]
        attempt = book.open_attempt(run["run_id"])
        info = {"run_id": run["run_id"], "mode": run["mode"], "state": run["state"], "players": run["players"],
                "names": names, "consent": run["consent"], "round": run["round"], "streak": run["streak"],
                "ended_reason": run["ended_reason"], "battle_id": attempt["battle_id"] if attempt else None,
                "next": None}
        if run["state"] == "active":
            info["next"] = self._next(run)
        out["run"] = info
        return out

    def _next(self, run) -> dict | None:
        book = self.book
        if run["mode"] == "league":
            p = league_plan(run["round"])
            firsts = [run["round"] > book.league_record(x)["best_round"] for x in run["players"]]
            prize = league_prize(run["round"], first_time=any(firsts))
            if run["round"] == len(LEAGUE) and any(book.league_record(x)["clears"] == 0 for x in run["players"]):
                prize += LEAGUE_FIRST_CLEAR_BONUS
            return {"round": p.round, "level": 0, "label": LEAGUE[p.round - 1][2], "brain": p.brain, "set": 1,
                    "prize": prize}
        try:
            base = self.base_level(run["players"])
        except FrontierError:
            return None
        p = plan(run["seed"], run["round"], base)
        first = run["round"] > min(book.record(x)["best_streak"] for x in run["players"])
        return {"round": p.round, "level": p.level, "label": p.label, "brain": p.brain, "set": set_of(p.round) + 1,
                "prize": prize_for(p.level, p.round, first_time=first),
                "bp": frontier_rewards.bp_for(p.round, first_time=first),
                "item": (lambda it: None if it is None else {"name": frontier_rewards.ITEM_NAMES.get(it[0], "item"),
                                                             "quantity": it[1]})(frontier_rewards.item_for(p.round, first_time=first))}

    # ------------------------------------------------- Battle Points and the shop
    def battle_points(self, player) -> int | None:
        """The Battle Points in the player's last saved game (None when there is no readable save)."""
        from .flash import FlashError, inspect_flash
        server = self.server
        session = server.sessions.get(player)
        if session is None or session.closed or server.store is None:
            return None
        checkpoint = server.store.read_checkpoint(player, session.session_epoch)
        if checkpoint is None:
            return None
        try:
            block2 = inspect_flash(checkpoint.payload, save_profile=checkpoint.save_profile).save_block2
        except FlashError:
            return None
        return min(int.from_bytes(block2[BATTLE_POINTS_OFFSET:BATTLE_POINTS_OFFSET + 2], "little"), rewards.MAX_BP)

    def bp_view(self, player) -> dict:
        ledger = self.book.bp_ledger(player)
        purchase = self.book.last_purchase(player)
        item = None
        if purchase is not None:
            item = {"state": purchase["state"], "name": frontier_rewards.ITEM_NAMES.get(purchase["item"], "item"),
                    "price": purchase["price"], "quantity": purchase["quantity"]}
        return {"balance": self.battle_points(player), "earned": ledger["earned"], "spent": ledger["spent"],
                "shop": [{"slot": i, "name": entry.name, "price": entry.price, "quantity": entry.quantity}
                         for i, entry in enumerate(frontier_rewards.SHOP)],
                "purchase": item}

    def _shop_buy(self, session, request) -> None:
        actor = session.player_id
        slot = request.get("slot")
        if type(slot) is not int or not 0 <= slot < len(frontier_rewards.SHOP):
            raise FrontierError("no_such_item", "the shop does not sell that")
        entry = frontier_rewards.SHOP[slot]
        if self.book.open_purchase(actor) is not None:
            raise FrontierError("purchase_open", "your last purchase is not finished")
        known = self.battle_points(actor)
        if known is not None and known < entry.price:
            raise FrontierError("not_enough_bp", f"{entry.name} costs {entry.price} BP; you have {known}")
        wagers = getattr(self.server, "wagers", None)
        if wagers is None:
            raise FrontierError("no_wallet", "this host has no wallet")
        purchase_id = str(uuid4())
        self.book.start_purchase(purchase_id, actor, entry.item, entry.quantity, entry.price)
        wagers.grant_reward(actor, rewards.KIND_BP_DEBIT, entry.price, f"shop:{purchase_id}:debit")

    def _advance_purchases(self) -> None:
        """Move every open purchase one step along: the game's receipt for the debit decides whether the item is granted."""
        wagers = getattr(self.server, "wagers", None)
        if wagers is None:
            return
        book = self.book
        for purchase in book.open_purchases():
            pid, player = purchase["purchase_id"], purchase["player_id"]
            if purchase["state"] == "debit":
                entry = wagers.entry(player, f"shop:{pid}:debit")
                if entry is None or entry["applied"] is None:
                    continue
                paid = entry["applied"]
                if paid >= purchase["price"]:
                    wagers.grant_reward(player, rewards.KIND_ITEM,
                                        rewards.item_payload(purchase["item"], purchase["quantity"]), f"shop:{pid}:item")
                    book.set_purchase(pid, "granting", spent=purchase["price"])
                elif paid > 0:      # the save had fewer points than the host believed: give back what was taken
                    wagers.grant_reward(player, rewards.KIND_BP, paid, f"shop:{pid}:refund")
                    book.set_purchase(pid, "refused")
                else:
                    book.set_purchase(pid, "refused")
            elif purchase["state"] == "granting":
                entry = wagers.entry(player, f"shop:{pid}:item")
                if entry is None or entry["applied"] is None:
                    continue
                if entry["applied"] >= purchase["quantity"]:
                    book.set_purchase(pid, "done")
                else:               # the bag and the PC were full: the points come back
                    wagers.grant_reward(player, rewards.KIND_BP, purchase["price"], f"shop:{pid}:refund")
                    book.set_purchase(pid, "refunded", spent=-purchase["price"])

    def _collect_rewards(self) -> None:
        """Record what each game reported for the Battle Points and items it was sent."""
        wagers = getattr(self.server, "wagers", None)
        if wagers is None:
            return
        for reward in self.book.rewards_in_flight():
            entry = wagers.entry(reward["player_id"], f"{reward['battle_id']}:{reward['kind']}")
            if entry is not None and entry["applied"] is not None:
                self.book.reward_result(reward["battle_id"], reward["player_id"], reward["kind"], entry["applied"])

    # ------------------------------------------------------------ requests
    def request(self, session, request) -> dict:
        op, actor, server = request["op"], session.player_id, self.server
        if op == "status":
            return self.view(actor)
        self.reconcile()
        try:
            if op == "propose":
                self._propose(session, request.get("mode", "frontier"))
            elif op == "accept":
                self._accept(session)
            elif op in ("cancel", "retire"):
                self._cancel(session, op)
            elif op == "battle":
                self._battle(session, request)
            elif op == "shop_buy":
                self._shop_buy(session, request)
            elif op == "bring":
                self._bring(session, request)
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

    def _propose(self, session, mode="frontier"):
        actor, teammate = session.player_id, self._teammate(session)
        self.check_party(actor)
        self.check_party(teammate)
        if mode == "league":
            self.check_league(actor)
            self.check_league(teammate)
        import random
        run = self.book.propose(str(uuid4()), actor, teammate, random.SystemRandom().randrange(1, 2 ** 31), mode)
        name = self.server._player_name(actor).upper()[:10]
        self._notice("POKEMON LEAGUE!" if mode == "league" else "FRONTIER RUN!",
                     f"{name}: open PLAYERS > {'League' if mode == 'league' else 'Frontier'}", [teammate])
        return run

    def _accept(self, session):
        actor = session.player_id
        run = self.book.run_of(actor)
        if run is None or run["state"] != "forming":
            raise FrontierError("no_run", "there is no Frontier run to join")
        self.check_party(actor)
        if run["mode"] == "league":
            self.check_league(actor)
        run = self.book.accept(run["run_id"], actor)
        if run["state"] == "active":
            self._notice("THE LEAGUE AWAITS!" if run["mode"] == "league" else "FRONTIER BEGINS!",
                         "Open PLAYERS > World", run["players"])

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
        if run["mode"] == "league":
            # Experience is awarded in the League while a trainer of the team is clearing it for the first time.
            first = any(self.book.league_record(x)["clears"] == 0 for x in run["players"])
            p = league_plan(run["round"], exp=first)
        else:
            p = plan(run["seed"], run["round"], self.base_level(run["players"]))
        battle_id = str(uuid4())
        self.book.issue(run["run_id"], battle_id, p)      # the intent is durable before anybody is invited
        try:
            server._assert_battle_available(actor, teammate)
            brings = {player: mask for player in (actor, teammate) if (mask := self.team(player)[0])}
            view = server.battle_desk.invite_coop(actor, session.session_epoch, teammate, p.code, battle_id,
                                                  brings=brings or None)
            if capture:
                fields = {k: v for k, v in request.items() if k in ("incarnation", "runtime_id")}
                server.battle_execution.admission.capture(actor, session.session_epoch, dict(fields, battle_id=battle_id))
        except Exception as error:  # noqa: BLE001 - nothing started: the round is offered again
            self.book.void(battle_id)
            code = getattr(error, "code", "battle_unavailable")
            raise FrontierError(code, getattr(error, "message", None) or str(error)) from error
        name = server._player_name(actor).upper()[:10]
        self._notice(f"ROUND {p.round}: {p.label.upper()}"[:32], f"{name}: PLAYERS > Challenges", [teammate])
        self._notice(f"ROUND {p.round}" + (f" LEVEL {p.level}" if p.level else ""), "PLAYERS > Challenges", [actor])
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
        for run in book.cleared_without_hall():     # a crash between clearing the League and entering the Hall
            self._enter_hall(run)
        self.pay()
        self._collect_rewards()
        self._advance_purchases()

    def _settled_notice(self, attempt):
        run = self.book.run(attempt["run_id"])
        if attempt["state"] == "won" and run["mode"] == "league" and run["ended_reason"] == "cleared":
            self._enter_hall(run)
            self._notice("HALL OF FAME!", "You cleared the POKEMON LEAGUE!", run["players"])
        elif attempt["state"] == "won":
            top = max(attempt["prizes"].values()) if attempt["prizes"] else 0
            extras = self.book.rewards_of(attempt["battle_id"])
            bp = max((r["payload"] for r in extras if r["kind"] == "bp"), default=0)
            item = next((r for r in extras if r["kind"] == "item"), None)
            tail = (f" +{bp}BP" if bp else "") + (f" +{frontier_rewards.describe('item', item['payload'])}" if item else "")
            self._notice(f"ROUND {attempt['round']} CLEARED!", (f"Prize up to ${top:,}" + tail)[:32], run["players"])
        elif attempt["state"] == "lost":
            self._notice("FRONTIER RUN OVER", f"Streak {run['streak']} - well fought!", run["players"])

    def _enter_hall(self, run) -> None:
        """Enter a cleared League run in the Hall of Fame, once, with the team as it last saved."""
        party = []
        for player in run["players"]:
            try:
                members = self._members(player)
            except FrontierError:
                members = []
            party.append({"name": self.server._player_name(player)[:12],
                          "mons": [[m.species, m.level] for m in members]})
        self.book.add_hall_of_fame(run["run_id"], [p["name"] for p in party], party)

    def pay(self) -> None:
        wagers = getattr(self.server, "wagers", None)
        if wagers is None:
            return
        paid = False
        for attempt in self.book.unpaid():
            for player, amount in attempt["prizes"].items():
                wagers.grant(player, amount, attempt["battle_id"])
            for reward in self.book.rewards_of(attempt["battle_id"]):
                if reward["state"] != "queued":
                    continue
                # Battle Points and items go through the same numbered wallet stream, once per (player, battle, kind).
                kind = rewards.KIND_BP if reward["kind"] == "bp" else rewards.KIND_ITEM
                wagers.grant_reward(reward["player_id"], kind, reward["payload"], f"{reward['battle_id']}:{reward['kind']}")
                self.book.reward_sent(reward["battle_id"], reward["player_id"], reward["kind"])
            self.book.mark_paid(attempt["battle_id"])
            paid = True
        if paid:
            self.server._broadcast_world()
