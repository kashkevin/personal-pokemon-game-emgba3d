"""Menu state for explicit player choices over authenticated service APIs.

Views are immutable. Actions refer to the displayed generation and captured
world lease; refreshing or reconnecting never implies consent.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from textwrap import wrap
from uuid import uuid4

from .companion import TeamError, BattleChallengeError, TradeError


WAGER_CHOICES = (1_000, 5_000, 10_000, 25_000, 50_000, 100_000)
LABEL_CHARACTERS = 25  # a menu row's label: menu_mailbox packs 26 bytes, NUL-terminated
GYM_LEADERS = {1: "Roxanne", 2: "Brawly", 3: "Wattson", 4: "Flannery", 5: "Norman",
               6: "Winona", 7: "Tate&Liza", 8: "Juan"}
_OPEN_BATTLE_STATES = ("invited", "accepted", "prepared")


def _money(amount):
    return f"${amount:,}"


class PlayerMenuError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class MenuRow:
    action: int
    label: str


@dataclass(frozen=True)
class MenuScreen:
    revision: int
    title: str
    status: str
    rows: tuple[MenuRow, ...]
    back: int = 7
    admission_action: int = 0


def battle_admission_enabled(companion):
    config = getattr(companion, "config", None)
    return (getattr(config, "menu_abi_version", 0) == 2
        and getattr(config, "battle_resume_abi_version", 0) == 1
        and getattr(config, "emergency_save_abi_version", 0) == 2
        and callable(getattr(companion, "_native_menu_capture_battle", None))
        and callable(getattr(companion, "_native_menu_prepare_battle", None))
        and callable(getattr(companion, "_native_menu_abandon_battle_preparation", None))
        and callable(getattr(companion, "_native_menu_handoff", None)))


def _text(value, limit):
    # Native controls cannot interpret player names as text control sequences.
    return "".join(c if 32 <= ord(c) <= 126 else "?" for c in value)[:limit]


class PlayerMenu:
    """Bounded team/challenge menus. Native battle execution has another owner."""

    def __init__(self, companion):
        self.companion = companion
        self._lock = asyncio.Lock()
        self._page = ("home", None)
        self._team = self._battles = None
        self._results = []
        self._results_binding = None
        self._result_mode = "all"
        self._result_outcome = "all"
        self._hunt_show = "all"
        self._hunt_order = "source"
        self._players = {}
        self._friends = {}
        self._wager = None  # {"wager": view | None, "money": int | None} for the pending challenge
        self._wager_amount = WAGER_CHOICES[1]
        self._binding = None
        self._signature = None
        self._actions = {}
        self._screen = MenuScreen(0, "Players", "Connecting", ())
        self._notice = ""
        self.handoff = None
        self._trades = None
        self._nav = None          # the host's PokeNav-style world view (Phase 7)
        self._base = None         # the player's base sharing choice (Phase 6)
        self._card = None
        self._card_binding = None
        self._card_notice = ""
        from .championship_menu import ChampionshipMenu
        self._championship = ChampionshipMenu(companion)
        from .record_menu import NativeRecordMenu
        self._record_menu = NativeRecordMenu(companion)

    def _session(self):
        c = self.companion
        return (c.world_id, c.server_epoch, c.session_epoch) if c.connected else None

    @property
    def screen(self):
        return self._screen

    async def refresh(self):
        async with self._lock:
            return await self._refresh()

    async def _refresh(self):
        binding = self._session()
        if binding is None:
            self._binding = None
            self._page = ("home", None)
            self._players, self._team, self._battles = {}, None, None
            self._card, self._card_binding = None, None
            self._championship.reset()
            self._record_menu.reset()
            return self._show("Players", "Connection lost", [])
        if binding != self._binding:
            self._page = ("home", None)
            self._notice = ""
            self._card, self._card_binding = None, None
            self._championship.reset()
            self._record_menu.reset()
        self._binding = binding
        # Immutable value copies; the companion owns and validates the roster.
        self._players = {p["player_id"]: p["display_name"] for p in self.companion._players}
        # Player friendship (host-owned); older hosts simply show none.
        self._friends = {}
        friendship_rpc = getattr(self.companion, "friendship_rpc", None)
        if callable(friendship_rpc) and getattr(self.companion.config, "world_enabled", False):
            try:
                self._friends = await friendship_rpc()
            except Exception:  # noqa: BLE001 - friendship display is optional
                self._friends = {}
            if self._session() != binding:
                raise PlayerMenuError("session_changed")
        for kind, call in (("team", self.companion.team_rpc), ("battle", self.companion.battle_challenge_rpc)):
            try:
                value = (await call("status" if kind == "team" else "pending"))["result"]
            except (TeamError, BattleChallengeError) as error:
                if error.code not in ("team_disabled", "battle_disabled"):
                    raise
                value = None
            if self._session() != binding:
                self._actions.clear()
                self._signature = None
                raise PlayerMenuError("session_changed")
            if kind == "team": self._team = value
            else: self._battles = value
        # The optional money wager on the pending challenge (host-owned).
        self._wager = None
        wager_rpc = getattr(self.companion, "wager_rpc", None)
        if self._battles and callable(wager_rpc) and getattr(self.companion.config, "world_enabled", False):
            try:
                self._wager = await wager_rpc("wager_get", battle_id=self._battles[0]["battle_id"])
            except Exception:  # noqa: BLE001 - wagers are optional; older hosts have none
                self._wager = None
            if self._session() != binding:
                raise PlayerMenuError("session_changed")
        world_nav = getattr(self.companion, "world_nav", None)
        self._nav = world_nav() if callable(world_nav) else None
        if self._page[0] == "base" and self._base is None:
            base_rpc = getattr(self.companion, "secret_base_rpc", None)
            if callable(base_rpc) and getattr(self.companion.config, "world_enabled", False):
                try:
                    self._base = await base_rpc()
                except Exception:  # noqa: BLE001 - older hosts have no secret bases
                    self._base = None
                if self._session() != binding:
                    raise PlayerMenuError("session_changed")
        self._trades = None
        if (callable(getattr(self.companion, "_native_menu_handoff", None))
                and getattr(self.companion.config, "menu_abi_version", 1) == 2
                and getattr(self.companion.config, "trade_enabled", False)):
            try:
                self._trades = (await self.companion.trade_rpc("proposals"))["proposals"]
            except TradeError as error:
                if error.code not in {"trade_disabled", "trade_preparation_unsupported"}:
                    raise
            if self._session() != binding:
                raise PlayerMenuError("session_changed")
        if self._page[0] in ("results", "result", "result_filters") and self._results_binding != binding:
            self._results = (await self.companion.battle_challenge_rpc("history"))["result"]
            if self._session() != binding:
                self._actions.clear()
                self._signature = None
                raise PlayerMenuError("session_changed")
            self._results_binding = binding
        if self._page[0] in ("card", "card_battles", "card_championships", "card_shared", "card_progress", "hunts", "hunt", "hunt_filters", "hunt_totals"):
            target = (self._page[1] if self._page[0] in {"card", "card_battles", "card_championships", "card_shared"}
                      else self.companion.config.player_id)
            # Native menu presence still refreshes every two seconds. Historical
            # ledgers are fetched only when this card opens or Refresh is chosen.
            card_binding = (binding, target)
            if self._card_binding != card_binding:
                self._card, self._card_notice = None, ""
                try:
                    from .player_card import read_player_card
                    reply = await read_player_card(self.companion, target)
                    self._card = reply["player_card"]
                except BattleChallengeError as error:
                    if error.code in ("invalid_fields", "invalid_field", "player_card_unsupported", "battle_disabled"):
                        self._card_notice = "Host has no Trainer Cards"
                    elif error.code == "player_offline":
                        self._card_notice = "That player disconnected"
                    else:
                        raise
                if self._session() != binding:
                    self._card, self._card_binding = None, None
                    raise PlayerMenuError("session_changed")
                self._card_binding = card_binding
        if self._page[0] == "championship":
            from .championship_menu import ChampionshipMenuError
            try:
                await self._championship.refresh()
            except ChampionshipMenuError as error:
                raise PlayerMenuError(error.code) from error
            if self._session() != binding:
                self._actions.clear()
                self._signature = None
                raise PlayerMenuError("session_changed")
        if self._page[0] == "records":
            await self._record_menu.refresh()
            if self._session() != binding:
                self._actions.clear()
                self._signature = None
                raise PlayerMenuError("session_changed")
        return self._render()

    def _show(self, title, status, actions):
        if len(actions) > 6:
            raise PlayerMenuError("menu_capacity")
        title, status = _text(title, 23), _text(status, 31)
        normalized = tuple((_text(label, 25), op, tuple(args)) for label, op, args in actions)
        admission = next((i + 1 for i, (_, op, _) in enumerate(normalized)
            if op == "battle_enter" and battle_admission_enabled(self.companion)), 0)
        signature = (self._binding, self._page, title, status, normalized, admission)
        if signature != self._signature:
            revision = self._screen.revision + 1
            if revision > 0xFFFFFFFF:
                raise PlayerMenuError("menu_generation_exhausted")
            self._actions = {i + 1: (op, args) for i, (_, op, args) in enumerate(normalized) if op}
            back = 0 if self._page[0] == "home" else 7
            if back:
                self._actions[back] = ("records_back", ()) if self._page[0] == "records" else ("home", ())
            self._screen = MenuScreen(revision, title, status,
                tuple(MenuRow(i + 1 if op else 0, label) for i, (label, op, _) in enumerate(normalized)), back, admission)
            self._signature = signature
        return self._screen

    def claim_battle_admission(self, revision, action):
        """Consume a displayed Enter selection without waiting on network state.

        Only MenuSession's exact native marked-row gate calls this. Consent was
        authenticated when displayed; a lost host cannot turn its native latch
        into a fresh choice or discard the original accepted descriptor.
        """
        if (type(revision) is not int or type(action) is not int
                or revision != self._screen.revision or not action
                or action != self._screen.admission_action or self._binding is None
                or action not in self._actions or self._actions[action][0] != "battle_enter"):
            raise PlayerMenuError("stale_battle_admission")
        _, args = self._actions[action]
        battle = next((b for b in self._battles or () if
            (b["battle_id"], b["generation"], b["fingerprint"]) == args), None)
        if (battle is None or battle["state"] != "accepted"
                or set(battle["consent"]) != set(battle["players"])):
            raise PlayerMenuError("stale_battle")
        self._actions.clear()
        self._signature = None
        self.handoff = None
        return deepcopy(battle)

    def _name(self, player):
        return self._players.get(player, "Disconnected player")

    def _render(self):
        actor = self.companion.config.player_id
        page, target = self._page
        actions = []
        title, status = "Players", self._notice or f"Connected: {len(self._players)}/4"
        if page == "player" and target in self._players and target != actor:
            title = self._name(target)
            friend = self._friends.get(target)
            if friend is not None:
                progress = "" if friend["next"] is None else f" {friend['points']}/{friend['next']}"
                status = friend["name"] + progress
                if friend["lucky_friends"]:
                    actions.append(("LUCKY FRIENDS: next trade", "", ()))
            if self._trades is not None and not self._trades:
                actions.append(("Trade Pokemon", "trade_open", (target,)))
            if self._team is not None and self._team["team"] is None:
                actions.append(("Invite to team", "team_invite", (target,)))
            if self._battles is not None and not self._battles:
                actions.append(("Challenge 1v1", "battle_invite", (target,)))
            actions.append(("View Trainer Card", "card", (target,)))
            if self._notice or friend is None:
                status = self._notice or "Choose an interaction"
        elif page == "trade" and self._trades:
            trade = self._trades[0]
            title, status = "Trade Pokemon", "With " + self._name(next(p for p in trade["players"] if p != actor))
            params = (trade["transaction_id"], trade["generation"])
            actions.extend((("Choose your Pokemon", "trade_enter", params), ("Decline trade", "trade_cancel", params)))
        elif page == "team" and self._team is not None:
            title = "Your team"
            own = self._team["team"]
            if own:
                peer = next(p for p in own["members"] if p != actor)
                actions.append((self._name(peer), "", ()))
                actions.append(("Leave team", "team_leave", (own["team_id"], own["generation"])))
                other = next((t for t in self._team["teams"] if t["team_id"] != own["team_id"]), None)
                if other is not None and self._battles is not None and not self._battles:
                    actions.append(("Challenge other team 2v2", "battle_multi", (peer, *other["members"])))
                status = self._notice or "Separate parties and items"
            elif self._team["invitations"]:
                invitation = self._team["invitations"][0]
                params = (invitation["invitation_id"], invitation["generation"])
                if invitation["recipient"] == actor:
                    status = "From " + self._name(invitation["sender"])
                    actions.extend((("Accept invitation", "team_accept", params), ("Decline invitation", "team_decline", params)))
                else:
                    status = "Waiting for " + self._name(invitation["recipient"])
                    actions.append(("Cancel invitation", "team_cancel", params))
            else:
                status = "Choose a player to invite"
        elif page == "battles":
            title = "Challenges"
            if self._battles:
                battle = self._battles[0]
                title = {2: "1v1 challenge", 3: "2v2 full-party challenge",
                         4: "Team Gym vs " + GYM_LEADERS.get(battle.get("gym"), "Leader")}.get(battle["mode"], "Challenge")
                status = self._notice or f"Accepted: {len(battle['consent'])}/{len(battle['players'])}"
                parties = {cp["player_id"]: cp["party_count"] for cp in battle["checkpoints"]}
                if battle["mode"] in (2, 4):
                    for cp in battle["checkpoints"]:
                        actions.append((f"{self._name(cp['player_id'])[:18]} ({cp['party_count']})", "", ()))
                else:
                    # Two team rows keep room for the consent and wager rows.
                    for team in (battle["players"][::2], battle["players"][1::2]):
                        actions.append((" & ".join(f"{self._name(p)[:8]}({parties.get(p, 0)})" for p in team), "", ()))
                params = (battle["battle_id"], battle["generation"])
                wager = self._wager["wager"] if self._wager is not None else None
                wager_ready = wager is None or set(wager["accepted"]) == set(wager["players"])
                if battle["state"] in _OPEN_BATTLE_STATES and self._wager is not None:
                    if wager is None:
                        label = "Wager: none (set one)"
                    else:
                        label = f"Wager {_money(wager['amount'])} {len(wager['accepted'])}/{len(wager['players'])} OK"
                    actions.append((label, "wager", (battle["battle_id"],)))
                if battle["state"] in _OPEN_BATTLE_STATES:
                    if actor not in battle["consent"] and actor != battle["sender"]:
                        actions.append(("Accept challenge", "battle_accept", (*params, battle["fingerprint"])))
                    actions.append(("Cancel challenge", "battle_cancel", params))
                    if battle["state"] == "accepted" and not wager_ready:
                        status = "Everyone must accept the wager"
                    elif battle["state"] == "accepted":
                        status = "Waiting for battle coordinator"
                        if (callable(getattr(self.companion, "_native_menu_handoff", None))
                                and (getattr(self.companion.config, "battle_resume_abi_version", 0) != 1
                                     or battle_admission_enabled(self.companion))):
                            status = "All players accepted"
                            actions.append(("Enter battle", "battle_enter", (*params, battle["fingerprint"])))
                else:
                    status = {"aborting": "Canceling safely", "recovery_required": "Battle recovery required",
                              "running": "Battle in progress", "starting": "Starting battle"}.get(battle["state"], battle["state"])
                if battle["mode"] == 2 and len(actions) < 6:
                    actions.append(("Championship", "championship", ()))
            else:
                status = self._notice or ("New battles disabled on host" if self._battles is None else "No pending challenges")
                actions.append(("Recent battle results", "results", (0,)))
                actions.append(("Full record archives", "records", ()))
                actions.append(("Your Trainer Card", "card", (actor,)))
                actions.append(("Championship", "championship", ()))
        elif page == "wager":
            title = "Battle wager"
            battle = next((b for b in self._battles or () if b["battle_id"] == target), None)
            view = self._wager
            if battle is None or view is None or battle["state"] not in _OPEN_BATTLE_STATES:
                status = self._notice or "This challenge has no open wager"
            else:
                wager, money = view["wager"], view["money"]
                actions.append(("Your money: " + ("unknown" if money is None else _money(money)), "", ()))
                if wager is None:
                    status = self._notice or "Each trainer stakes the same"
                    actions.append((f"Amount: {_money(self._wager_amount)}", "wager_amount", (target,)))
                    actions.append(("Propose this wager", "wager_propose", (target, self._wager_amount)))
                    actions.append(("Winners take the stakes", "", ()))
                else:
                    status = self._notice or f"{_money(wager['amount'])} each, {len(wager['accepted'])}/{len(wager['players'])} accepted"
                    actions.append(("Proposed by " + self._name(wager["sender"])[:13], "", ()))
                    if actor not in wager["accepted"]:
                        actions.append((f"Accept {_money(wager['amount'])} wager", "wager_accept", (target, wager["amount"])))
                        actions.append(("Decline wager", "wager_decline", (target,)))
                    elif actor == wager["sender"]:
                        actions.append(("Remove wager", "wager_remove", (target,)))
                    else:
                        actions.append(("You accepted this wager", "", ()))
            actions.append(("Back to challenge", "battles", ()))
        elif page in ("world", "world_players", "world_player", "world_outbreak", "world_event", "base"):
            return self._show(*self._render_world(page, target))
        elif page == "championship":
            return self._show(*self._championship.render())
        elif page == "records":
            return self._show(*self._record_menu.render())
        elif page in ("card", "card_battles", "card_championships", "card_shared", "card_progress", "hunts", "hunt", "hunt_filters", "hunt_totals"):
            title, status = "Trainer Card", self._card_notice or "Recorded results snapshot"
            card = self._card
            if card is None:
                actions.append(("Refresh card", "card_refresh", (target if page in
                    {"card", "card_battles", "card_championships", "card_shared"} else actor,)))
            elif page == "card":
                title = card["display_name"]
                counts = card["battles"]["total"]
                actions.append((f"All: W{counts['wins']} L{counts['losses']} D{counts['draws']}", "", ()))
                actions.append((f"Streak {counts['streak']} Best {counts['best_streak']}", "", ()))
                actions.append(("1v1 and 2v2 records", "card_battles", (target,)))
                if "championships" in card:
                    actions.append(("Championship records", "card_championships", (target,)))
                if card["personal"] is not None:
                    actions.append(("Trades and saved party", "card_progress", ()))
                    actions.append(("Personal hunt attempts", "hunts", (0,)))
                else:
                    if card.get("shared") is not None:
                        actions.append(("Your shared records", "card_shared", (target,)))
                    actions.append(("Refresh card", "card_refresh", (target,)))
            elif page == "card_battles":
                title = "Battle records"
                for key, label in (("total", "All"), ("singles", "1v1"), ("doubles", "2v2")):
                    counts = card["battles"][key]
                    actions.append((f"{label}: W{counts['wins']} L{counts['losses']} D{counts['draws']}", "", ()))
                actions.append(("Back to Trainer Card", "card", (target,)))
                actions.append(("Refresh card", "card_refresh", (target,)))
            elif page == "card_championships":
                title = "Championship records"
                records = card.get("championships")
                if records is None:
                    status = "Host has no tournament records"
                else:
                    status = "Entries need all four consents"
                    for key, label in (("entries", "Entered"), ("completed", "Completed"), ("wins", "Won")):
                        actions.append((f"{label}: {records[key]}", "", ()))
                actions.append(("Back to Trainer Card", "card", (target,)))
                actions.append(("Refresh card", "card_refresh", (target,)))
            elif page == "card_shared":
                title, status = "Your shared records", "Your completed shared activity"
                shared = card.get("shared")
                if shared is None:
                    status = "Shared records unavailable"
                else:
                    trades = shared["trades"]
                    actions.append(("Trade records unavailable" if trades is None else f"Trades: {trades}", "", ()))
                    for key, label in (("together", "As teammates"), ("against", "As opponents")):
                        records = shared["battles"][key]
                        actions.append((f"{label}: {records['played']}", "", ()))
                        actions.append((f"You: W{records['wins']} L{records['losses']} D{records['draws']}", "", ()))
                actions.append(("Back to Trainer Card", "card", (target,)))
            elif page == "card_progress":
                title = "Trades and saved party"
                personal = card["personal"]
                trades, saved = personal["trades"], personal["checkpoint"]
                if trades is None:
                    actions.append(("Trade records unavailable", "", ()))
                else:
                    actions.append((f"Trades committed: {trades['committed']}", "", ()))
                    actions.append((f"Awaiting recovery: {trades['pending']}", "", ()))
                if saved is None:
                    actions.append(("No canonical save yet", "", ()))
                else:
                    actions.append((f"Save revision: {saved['revision']}", "", ()))
                    actions.append((f"Saved party {saved['party_count']} PC {saved['stored_count']}", "", ()))
                actions.append(("Full records and trades", "records", ()))
                actions.append(("Refresh your card", "card_refresh", (actor,)))
            else:
                from .record_views import hunt_rows, hunt_detail, hunt_totals
                title = "Personal hunt attempts"
                hunts = card["personal"]["hunts"]
                if hunts is None:
                    status = "Host hunt ledger not enabled"
                    actions.append(("Refresh your hunts", "hunts_refresh", ()))
                elif page == "hunt":
                    detail = hunt_detail(hunts, target)
                    from .reset_catalogue import reset_source_catalogue
                    availability = next(row["availability"] for row in reset_source_catalogue(self.companion.config)
                                        if row["encounter_id"] == target)
                    title, status = "Personal hunt details", "Source " + availability + "; access unknown"
                    actions.extend((line, "", ()) for line in wrap(detail["name"], 25))
                    actions.append((f"Attempts: {detail['attempts']}", "", ()))
                    actions.append(("Capture/shiny: unknown", "", ()))
                    actions.append(("Hunt admission receipts", "records", ("hunt", target)))
                    actions.append(("Back to hunt list", "hunts", (0,)))
                elif page == "hunt_filters":
                    title, status = "Hunt list options", "Filter your recorded attempts"
                    show = {"all": "All sources", "started": "Started", "unstarted": "Not started"}[self._hunt_show]
                    order = {"source": "Catalogue", "attempts": "Most attempts", "name": "Name"}[self._hunt_order]
                    actions.extend((("Show: " + show, "hunt_show", ()),
                                    ("Sort: " + order, "hunt_order", ()),
                                    ("Your hunt totals", "hunt_totals", ()),
                                    ("Refresh your hunts", "hunts_refresh", ()),
                                    ("Back to hunt list", "hunts", (0,))))
                elif page == "hunt_totals":
                    totals = hunt_totals(hunts)
                    title, status = "Personal hunt totals", "Counts never change shiny odds"
                    actions.extend(((f"Attempts: {totals['attempts']}", "", ()),
                                    (f"Sources started: {totals['started']}", "", ()),
                                    (f"Catalogue: {totals['sources']}", "", ()),
                                    ("Capture/shiny: unknown", "", ()),
                                    ("Back to hunt list", "hunts", (0,))))
                else:
                    rows = hunt_rows(hunts, show=self._hunt_show, order=self._hunt_order)
                    offset = target or 0
                    if offset >= len(rows):
                        offset = 0
                    status = "Select a hunt for full details" if rows else "No hunts match this filter"
                    for hunt in rows[offset:offset + 3]:
                        name = hunt["name"]
                        # Counts get their own line width budget; source names
                        # may be abbreviated, but attempts are never truncated.
                        count = str(hunt["attempts"])
                        actions.append((name[:24 - len(count)] + " " + count, "hunt", (hunt["encounter_id"],)))
                    if offset + 3 < len(rows):
                        actions.append(("Next hunts", "hunts", (offset + 3,)))
                    if offset:
                        actions.append(("Previous hunts", "hunts", (max(0, offset - 3),)))
                    actions.append(("Filters, totals, refresh", "hunt_filters", ()))
        elif page == "results":
            from .record_views import battle_rows, battle_outcome
            rows = battle_rows(self._results, actor, mode=self._result_mode, outcome=self._result_outcome)
            title, status = "Battle results", "Filtered from latest 8 results"
            offset = target or 0
            if offset >= len(rows):
                offset = 0
            for result in rows[offset:offset + 3]:
                outcome = battle_outcome(result, actor).title()
                mode = "1v1" if result["mode"] == 2 else "2v2"
                actions.append((f"{mode} {outcome} #{result['sequence']}", "result", (result["battle_id"],)))
            if offset + 3 < len(rows):
                actions.append(("Older results", "results", (offset + 3,)))
            if offset:
                actions.append(("Newer results", "results", (max(0, offset - 3),)))
            actions.append(("Filters and refresh", "result_filters", ()))
            if not rows:
                status = "No matching recent results" if self._results else "No completed battles yet"
        elif page == "result_filters":
            title, status = "Battle history options", "Search the latest 8 results"
            mode = {"all": "All", "singles": "1v1", "doubles": "2v2"}[self._result_mode]
            actions.extend((("Format: " + mode, "result_mode", ()),
                            ("Outcome: " + self._result_outcome.title(), "result_outcome", ()),
                            ("Show matching results", "results", (0,)),
                            ("Refresh latest results", "results_refresh", ()),
                            ("Clear filters", "result_clear", ())))
        elif page == "result":
            result = next((r for r in self._results if r["battle_id"] == target), None)
            title = "Battle result"
            if result is None:
                status = "No longer in recent results"
            else:
                status = "Draw" if result["outcome"] == 3 else f"Team {result['outcome']} won"
                for slot, player in enumerate(result["players"]):
                    actions.append((f"Team {1 + slot % 2}: {self._name(player)}", "", ()))
            actions.append(("Back to matching results", "results", (0,)))
        else:
            self._page = ("home", None)
            for player in self._players:
                if player != actor:
                    friend = self._friends.get(player)
                    label = self._name(player)
                    if friend is not None:
                        # The level's first word after the name, in the row's 25
                        # characters: a name is cut only where both cannot fit, so
                        # names that differ after their 13th character stay apart.
                        level = friend["name"].split()[0]
                        label = f"{label[:LABEL_CHARACTERS - 3 - len(level)]} - {level}"
                    actions.append((label, "player", (player,)))
            if self._team is not None:
                actions.append(("Team invitation" if self._team["invitations"] else "Your team", "team", ()))
            if self._battles is not None:
                actions.append(("Pending challenge" if self._battles else "Challenges", "battles", ()))
            else:
                # Completed history remains authenticated and readable when
                # new native battle admission is disabled (normal launcher).
                actions.append(("Battles and records", "battles", ()))
            last = ("Pending trade", "trade", ()) if self._trades else ("Your Trainer Card", "card", (actor,))
            world = ("World and my base", "world", ())
            room = 6 - len(actions)
            if room >= 2:
                actions.extend((world, last))
            elif room == 1:
                actions.append(last if self._trades else world)  # a full lobby: the Trainer Card is under Challenges
        return self._show(title, status, actions)

    def _render_world(self, page, target):
        """The PokeNav-style World pages (expansion Phase 7) and the player's own
        secret base sharing (Phase 6). Everything shown is the host's live view."""
        nav, actor = self._nav, self.companion.config.player_id
        actions = []
        if nav is None:
            return "World", "The host has no world view", [("Back", "home", ())]
        if page == "world":
            title, status = "PokeNav: World", self._notice or "Live view from the host"
            actions.append(("Players and weather", "world_players", ()))
            outbreak, event = nav["outbreak"], nav["event"]
            actions.append((("Outbreak: " + outbreak["name"]) if outbreak else "Outbreak: none",
                            "world_outbreak" if outbreak else "", ()))
            actions.append((("Event: " + event["name"]) if event else "World Event: none",
                            "world_event" if event else "", ()))
            actions.append(("My Secret Base", "base", ()))
            if nav.get("rule"):
                actions.append(("Rule: " + nav["rule"], "", ()))
        elif page == "world_players":
            title, status = "Players and weather", "Where everyone is"
            for player in nav["players"][:4]:
                actions.append((f"{self._name(player['player_id'])[:9]} - {player['place']}", "world_player",
                                (player["player_id"],)))
        elif page == "world_player":
            player = next((p for p in nav["players"] if p["player_id"] == target), None)
            title = self._name(target)
            status = "Not online" if player is None else "Position and weather"
            if player is not None:
                actions.extend((line, "", ()) for line in wrap(player["place"], 25)[:2])
                actions.append(("Weather: " + (player["weather"] or "unknown"), "", ()))
            actions.append(("Back to players", "world_players", ()))
        elif page in ("world_outbreak", "world_event"):
            entry = nav["outbreak" if page == "world_outbreak" else "event"]
            title = "Mass outbreak" if page == "world_outbreak" else "World Event"
            if entry is None:
                status = "Nothing right now"
            else:
                status = f"{entry['seconds_left'] // 60}m {entry['seconds_left'] % 60:02d}s left"
                actions.extend((line, "", ()) for line in wrap(entry["name"], 25)[:2])
                if entry.get("waiting"):
                    actions.extend((line, "", ()) for line in wrap(entry["waiting"], 25)[:2])
                actions.extend((line, "", ()) for line in wrap("Near " + entry["place"], 25)[:2])
            actions.append(("Back to World", "world", ()))
        else:
            title = "My Secret Base"
            base = self._base
            if base is None:
                status = self._notice or "Host has no secret bases"
            else:
                status = self._notice or ("Shared with the host" if base["published"] else "Make a base in the game")
                label = {"everyone": "Everyone", "team": "Teammate", "nobody": "Nobody"}[base["visibility"]]
                actions.append(("Visible to: " + label, "base_cycle", (base["visibility"],)))
                actions.append(("Others keep a copy in", "", ()))
                actions.append(("their save to visit it", "", ()))
            actions.append(("Back to World", "world", ()))
        return title, status, actions

    async def choose(self, revision, action):
        async with self._lock:
            if (type(revision) is not int or type(action) is not int or revision != self._screen.revision
                    or action not in self._actions):
                raise PlayerMenuError("stale_menu")
            if self._binding is None or self._session() != self._binding:
                self._actions.clear()
                self._signature = None
                raise PlayerMenuError("session_changed")
            op, args = self._actions[action]
            # Consume before awaiting: double clicks and a lost reply cannot
            # silently repeat a consent or create another invitation.
            self._actions.clear()
            self._signature = None
            self._notice = ""
            if op == "championship":
                self._championship.open()
                self._page = ("championship", None)
            elif op == "records":
                self._record_menu.open(*args)
                self._page = ("records", None)
            elif op.startswith("records_"):
                if await self._record_menu.choose(op, args):
                    self._page = ("home", None)
            elif op.startswith("champ_"):
                from .championship_menu import ChampionshipMenuError
                try:
                    to_battle = await self._championship.choose(op, args)
                except ChampionshipMenuError as error:
                    raise PlayerMenuError(error.code) from error
                if to_battle:
                    self._page = ("battles", None)
            elif op in ("result_mode", "result_outcome", "result_clear", "results_refresh"):
                if op == "result_mode":
                    choices = ("all", "singles", "doubles")
                    self._result_mode = choices[(choices.index(self._result_mode) + 1) % len(choices)]
                elif op == "result_outcome":
                    choices = ("all", "win", "loss", "draw")
                    self._result_outcome = choices[(choices.index(self._result_outcome) + 1) % len(choices)]
                elif op == "result_clear":
                    self._result_mode, self._result_outcome = "all", "all"
                else:
                    self._results_binding = None
                self._page = ("results", 0) if op in {"result_clear", "results_refresh"} else ("result_filters", None)
            elif op in ("hunt_show", "hunt_order", "hunts_refresh"):
                if op == "hunt_show":
                    choices = ("all", "started", "unstarted")
                    self._hunt_show = choices[(choices.index(self._hunt_show) + 1) % len(choices)]
                elif op == "hunt_order":
                    choices = ("source", "attempts", "name")
                    self._hunt_order = choices[(choices.index(self._hunt_order) + 1) % len(choices)]
                else:
                    self._card_binding = None
                self._page = ("hunts", 0) if op == "hunts_refresh" else ("hunt_filters", None)
            elif op == "base_cycle":
                choices = ("everyone", "team", "nobody")
                try:
                    self._base = await self.companion.secret_base_rpc(choices[(choices.index(args[0]) + 1) % 3])
                except Exception:  # noqa: BLE001 - the host decides; show that it did not change
                    self._notice = "Could not change it"
                self._page = ("base", None)
            elif op in ("home", "world", "world_players", "world_player", "world_outbreak", "world_event", "base",
                        "team", "battles", "player", "results", "result", "result_filters", "trade", "card", "card_battles", "card_championships", "card_shared", "card_progress", "hunts", "hunt", "hunt_filters", "hunt_totals"):
                if op == "results" and self._page[0] not in {"results", "result", "result_filters"}:
                    self._results_binding = None
                self._page = (op, args[0] if args else None)
                if op == "base":
                    self._base = None  # read afresh from the host
                if op == "card":
                    self._card_binding = None
            elif op == "card_refresh":
                self._card_binding = None
                self._page = ("card", args[0])
            elif op == "trade_open":
                trade = (await self.companion.trade_rpc("open", peer=args[0], transaction_id=str(uuid4())))["trade"]
                if trade["state"] != "offering" or self._session() != self._binding:
                    raise PlayerMenuError("trade_changed")
                self.handoff = ("trade", deepcopy(trade))
                return self._show("Trade Pokemon", "Preparing your party", [])
            elif op == "trade_enter":
                trade = next((t for t in self._trades or () if (t["transaction_id"], t["generation"]) == args), None)
                if trade is None:
                    raise PlayerMenuError("trade_changed")
                self.handoff = ("trade", deepcopy(trade))
                return self._show("Trade Pokemon", "Preparing your party", [])
            elif op == "trade_cancel":
                await self.companion.trade_rpc("cancel", transaction_id=args[0], generation=args[1])
                self._page = ("home", None)
            elif op == "team_invite":
                await self.companion.team_rpc("invite", peer=args[0], invitation_id=str(uuid4()))
                self._page = ("team", None)
            elif op == "team_leave":
                await self.companion.team_rpc("leave", team_id=args[0], generation=args[1])
            elif op in ("team_accept", "team_decline", "team_cancel"):
                await self.companion.team_rpc(op.removeprefix("team_"), invitation_id=args[0], generation=args[1])
            elif op == "battle_invite":
                await self.companion.battle_challenge_rpc("invite", peer=args[0], battle_id=str(uuid4()))
                self._page = ("battles", None)
            elif op == "battle_multi":
                await self.companion.battle_challenge_rpc("invite_multi", teammate=args[0], opponents=list(args[1:]), battle_id=str(uuid4()))
                self._page = ("battles", None)
            elif op in ("battle_accept", "battle_cancel"):
                fields = dict(battle_id=args[0], generation=args[1])
                if op == "battle_accept": fields["fingerprint"] = args[2]
                await self.companion.battle_challenge_rpc(op.removeprefix("battle_"), **fields)
            elif op == "wager":
                self._page = ("wager", args[0])
            elif op == "wager_amount":
                index = WAGER_CHOICES.index(self._wager_amount) if self._wager_amount in WAGER_CHOICES else 0
                self._wager_amount = WAGER_CHOICES[(index + 1) % len(WAGER_CHOICES)]
                self._page = ("wager", args[0])
            elif op in ("wager_propose", "wager_remove", "wager_accept", "wager_decline"):
                from .protocol import ProtocolError
                operation, fields = {
                    "wager_propose": ("wager_set", dict(battle_id=args[0], amount=args[1] if len(args) > 1 else 0)),
                    "wager_remove": ("wager_set", dict(battle_id=args[0], amount=0)),
                    "wager_accept": ("wager_accept", dict(battle_id=args[0], amount=args[1] if len(args) > 1 else 0)),
                    "wager_decline": ("wager_decline", dict(battle_id=args[0])),
                }[op]
                try:
                    await self.companion.wager_rpc(operation, **fields)
                except ProtocolError as error:
                    # Money rules are the host's: show why, never retry silently.
                    self._notice = error.message[:31]
                self._page = ("wager", args[0])
            elif op == "battle_enter":
                battle = next((b for b in self._battles or () if
                    (b["battle_id"], b["generation"], b["fingerprint"]) == args), None)
                if (battle is None or battle["state"] != "accepted"
                        or set(battle["consent"]) != set(battle["players"])):
                    raise PlayerMenuError("stale_battle")
                self.handoff = ("battle", deepcopy(battle))
                return self._show("Battle", "Closing menu for battle", [])
            return await self._refresh()
