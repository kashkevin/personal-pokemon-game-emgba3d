"""Battle Tower: Legends pages composed into the native Players menu (docs/battle-tower-legends.md sections 8.2 and 10).

The parent (player_menu.PlayerMenu) owns native screen revisions, choice consumption and the session lock; this controller
only reads the host's Tower view (companion.tower_rpc, tower_service.py) and issues its authenticated requests. Every page
fits the Players menu (a title of 23 characters, a status of 31, at most six rows of 25 printable ASCII characters, B for
back) and names a style (menu_mailbox.TOWER_STYLES) the native PC UI draws it with; the classic window shows the rows.

Reached from PLAYERS > World and my base > Frontier and League > Battle Tower: Legends, and from START > PLAYER > TOWER
(the Players menu OPEN of page 2). A solo battle's command and Hyper Training are answers to the player's choice, which
the menu session sends as the game's flags-4 and flags-5 screens (``choose`` returns them). Every refusal says why: the
host's own reason, or the one shown here.
"""
from __future__ import annotations

import asyncio

from . import tower_data, tower_rewards
from .tower_rules import CLIMBED, FLOORS, checkpoint, default_duo_floor, max_unlocked, win_reward

TITLE = "Battle Tower: Legends"
STYLE_HOME, STYLE_MAP, STYLE_PREVIEW, STYLE_SHOP, STYLE_DUO, STYLE_RECORDS, STYLE_TRAINING, STYLE_PRIZES = range(1, 9)
KIND_NAMES = {"regular": "Trainer", "boss": "Boss", "special": "Special", "final": "Final floor"}
# A prize floor's prize in a row's room (the money and Battle Points are on its own page).
PRIZE_LABELS = {10: "10 Rare Candy", 20: "5 Bottle Caps", 25: "Shiny Pokemon", 30: "15 Rare Candy", 40: "Gold Bottle Cap",
                50: "Pokemon, IVs 31", 60: "20 Rare Candy", 70: "2 Gold Bottle Caps", 75: "Shiny, IVs 31",
                80: "Ability Patch", 90: "Patch, 3 Gold Caps", 100: "Shiny legendary"}
STAT_NAMES = ("HP", "Attack", "Defense", "Speed", "Sp. Atk", "Sp. Def")
NATIVE_STATES = {"invited": "Open Challenges to battle", "accepted": "Open Challenges to battle",
                 "prepared": "Open Challenges to battle", "starting": "The Duo battle is starting",
                 "running": "The Duo battle is on", "finishing": "The Duo battle is ending",
                 "recovery_required": "Battle needs recovery", "aborting": "Cancelling the Duo battle"}
DUO_ENDINGS = {"declined": "The invitation was declined", "left": "The Duo was left",
               "team_changed": "Your team was dissolved"}
LAST_STATES = {"void": "Floor {floor}: not started", "forfeit": "Floor {floor}: counted as a loss"}
VOID_REASONS = {"refused": "Floor {floor}: your game refused", "expired": "Floor {floor}: never started"}
PER_PAGE = 4


# The game pays for an order and receives it (and a milestone Pokemon) on the field, never while the Players menu is
# open (engine multiplayer.c FieldReady): the player closes it (windows-package run 121, L tower-solo-8).
CLOSE_TO_FINISH = "Close the menu to finish"

class TowerMenuError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _text(value, limit=25):
    return "".join(char if 32 <= ord(char) <= 126 else "?" for char in str(value))[:limit]


def _money(amount):
    return f"${amount:,}"


class TowerMenu:
    def __init__(self, companion):
        self.companion = companion
        self.reset()

    def reset(self):
        self._binding = None
        self._view = None
        self._supported = None
        self._notice = ""
        self._page = ("home", None)
        self._stack = []
        self._origin = "coop"

    def open(self, origin="coop"):
        """The Tower's home page; B from it goes back to ``origin`` (the Frontier and League page, or the Players home
        when START > PLAYER > TOWER opened it)."""
        self._page, self._stack, self._notice, self._origin = ("home", None), [], "", origin

    @property
    def origin(self):
        return self._origin

    def _session(self):
        companion = self.companion
        return (companion.world_id, companion.server_epoch, companion.session_epoch) if companion.connected else None

    @property
    def _actor(self):
        return self.companion.config.player_id

    # ------------------------------------------------------------------ host
    async def refresh(self):
        binding = self._session()
        if binding is None:
            self._view, self._notice = None, "Connection lost"
            return
        if binding != self._binding:
            self._binding, self._view, self._stack, self._page = binding, None, [], ("home", None)
        rpc = getattr(self.companion, "tower_rpc", None)
        if not callable(rpc) or not getattr(self.companion.config, "world_enabled", False):
            self._supported = False
            return
        await self._rpc("status")
        if self._session() != binding:
            raise TowerMenuError("session_changed")

    async def _rpc(self, op, **fields):
        """The host's answer (its view), or False with the reason shown. A lost reply is never retried: the next
        refresh shows what the host decided."""
        from .protocol import ProtocolError
        try:
            view = await self.companion.tower_rpc(op, **fields)
        except ProtocolError as error:
            if error.code in ("tower_disabled", "invalid_type", "invalid_fields", "invalid_field") and op == "status":
                self._supported = False
            else:
                self._notice = _text(error.message, 31)
            return False
        except (ConnectionError, OSError, asyncio.TimeoutError):
            self._notice = "Host did not answer: refresh"
            return False
        self._supported, self._view = True, view
        return view

    # --------------------------------------------------------------- helpers
    def _data(self):
        try:
            return tower_data.load()
        except tower_data.TowerDataError:
            return None

    def _trainer(self, floor, which="solo"):
        data = self._data()
        return data.trainer(floor, which) if data is not None else f"Floor {floor} trainer"

    def _kind(self, floor):
        data = self._data()
        return data.floor(floor)["kind"] if data is not None else "regular"

    def _region(self, floor):
        data = self._data()
        return data.region(floor) if data is not None else ""

    def _player(self):
        return (self._view or {}).get("player") or {"progress": 1, "highest": 0, "claims": 0, "best": 0}

    def _go(self, page, arg=None):
        """Open a page; B comes back here (paging within one list replaces it: B leaves the list)."""
        if page != self._page[0]:
            self._stack.append(self._page)
            del self._stack[:-8]
        self._page = (page, arg)

    def _reward_rows(self, floor):
        """What winning ``floor`` would pay this player (section 4), in two rows."""
        player = self._player()
        reward = win_reward(floor, player["highest"], max(player["highest"], player.get("best", 0)), player["claims"])
        if not reward.first_clear:
            return [("Win: Exp. only (cleared)", "", ())]      # a floor cleared before pays nothing again
        rows = []
        if reward.claim:
            rows.append(("Prize: " + PRIZE_LABELS[floor], "", ()))
        rows.append((f"Win: {reward.bp} BP" + (f", {_money(reward.money)}" if reward.money else ""), "", ()))
        return rows

    # ---------------------------------------------------------------- choose
    async def choose(self, op, args):
        """None to stay on the Tower's pages; "leave" (B from the home page), "battles" (PLAYERS > Challenges) or
        "players" (the Players home: invite a teammate) for the parent; or ("command", TowerCommand) / ("hyper_training",
        None): the answer the game's window takes."""
        if self._binding is None or self._session() != self._binding:
            raise TowerMenuError("session_changed")
        self._notice = ""
        if op == "tower_back":
            if not self._stack:
                return "leave"
            self._page = self._stack.pop()
            return None
        if op == "tower_page":
            self._go(*args)
            return None
        if op in ("tower_challenges", "tower_players"):
            return "battles" if op == "tower_challenges" else "players"
        if op == "tower_hyper":
            return ("hyper_training", None)
        if op == "tower_solo":
            from .menu_mailbox import TowerCommand
            view = await self._rpc("solo", floor=args[0])
            if view and view.get("command"):
                command = view["command"]
                self._page, self._stack = ("home", None), []     # back on the home page: the battle's state is there
                return ("command", TowerCommand(command["ticket"], command["table_hash"], command["floor"]))
            return None
        if op == "tower_buy":
            if await self._rpc("shop_buy", slot=args[0]):
                self._notice = CLOSE_TO_FINISH
            return None
        if op == "tower_send":
            if await self._rpc("milestone_send", milestone=args[0]):
                self._notice = "Sent: close the menu"
            return None
        if op == "tower_bring":
            return await self._toggle(*args)
        if op == "tower_duo":
            operation, fields = args[0], dict(zip(("floor",), args[1:]))
            if await self._rpc(operation, **fields) and operation in ("duo_invite", "duo_floor"):
                self._page, self._stack = ("duo", None), [entry for entry in self._stack if entry[0] != "duo"][-7:]
            return None
        if op == "tower_refresh":
            return None
        raise TowerMenuError("stale_menu")

    async def _toggle(self, slot, page_no):
        """The Duo team (the Frontier's selection, at most three): tap a Pokemon to bring it or leave it."""
        team = (self._view or {}).get("team") or {"slots": [], "limit": 0}
        chosen = [entry["slot"] for entry in team["slots"] if entry["selected"]]
        if slot in chosen:
            if len(chosen) == 1:
                self._notice = "Bring at least one Pokemon"
                return None
            chosen.remove(slot)
        else:
            if len(chosen) >= team["limit"] > 0:
                chosen.pop(0)            # a full team gives up its first member
            chosen.append(slot)
        await self._rpc("bring", mask=sum(1 << s for s in chosen))
        self._page = ("team", page_no)
        return None

    # ---------------------------------------------------------------- render
    def render(self):
        """(title, status, actions, (style, argument)) for the parent's six-row screen."""
        if self._binding is None or self._session() != self._binding:
            return TITLE, "Connection lost; reopen Players", [], (STYLE_HOME, 0)
        if self._supported is False:
            return TITLE, "The host has no Battle Tower", [("Refresh", "tower_refresh", ())], (STYLE_HOME, 0)
        if self._view is None:
            return TITLE, self._notice or "Asking the host...", [("Refresh", "tower_refresh", ())], (STYLE_HOME, 0)
        page, arg = self._page
        title, status, actions, style = getattr(self, "_render_" + page)(arg)
        if len(actions) > 6:
            raise TowerMenuError("menu_capacity")
        return _text(title, 23), _text(self._notice or status, 31), [(_text(l), op, a) for l, op, a in actions], style

    def _status_line(self):
        view, player = self._view, self._player()
        battle, last = view.get("battle"), view.get("last")
        if view.get("unavailable"):
            return view["unavailable"]
        if view.get("problem"):
            return view["problem"]["message"]
        if battle is not None:
            if battle["mode"] == "duo":
                return f"Duo floor {battle['floor']}: PLAYERS > Challenges"
            # Started: this menu is open, so the game is out of that battle and its result has not reached the host.
            return (f"Floor {battle['floor']}: starting" if battle["state"] == "issued"
                    else f"Floor {battle['floor']}: no result yet")
        if last is not None and last["state"] in ("void", "forfeit") and last["mode"] == "solo":
            text = VOID_REASONS.get(last["reason"]) if last["state"] == "void" else None
            return (text or LAST_STATES[last["state"]]).format(floor=last["floor"])
        bp = (view.get("save") or {}).get("bp")
        bp = "?" if bp is None else bp
        head = "Climbed!" if player["progress"] >= CLIMBED else f"Floor {player['progress']}"
        return f"{head} Best {player['highest']} CP{checkpoint(player['highest'])} {bp}BP"

    def _render_home(self, _):
        view, player = self._view, self._player()
        progress, highest = player["progress"], player["highest"]
        actions = []
        battle = view.get("battle")
        # A command on its way shows as such. A started battle with no result stays askable: asking again is how the host
        # learns the game is out of it (it waits for a late result, or counts the battle as a loss: design section 2).
        if battle is not None and battle["mode"] == "solo" and battle["state"] == "issued":
            actions.append((f"Floor {battle['floor']}: starting", "", ()))
        elif progress <= FLOORS:
            actions.append((f"Solo: floor {progress}", "tower_page", ("solo", progress)))
        else:
            actions.append(("Solo: replay a floor", "tower_page", ("replay", 0)))
        duo = view.get("duo")
        if duo is not None and duo["state"] != "ended":
            actions.append((f"Duo: floor {duo['floor']} ({duo['state']})", "tower_page", ("duo", None)))
        else:
            mate = view.get("teammate")
            actions.append(("Duo with " + mate["name"][:16] if mate else "Duo (needs a teammate)", "tower_page",
                            ("duo", None)))
        if highest and progress <= FLOORS:
            actions.append(("Replay a floor", "tower_page", ("replay", 0)))
        actions.append(("Floors and bosses", "tower_page", ("bosses", 0)))
        actions.append(("Prizes and shop", "tower_page", ("prizes", None)))
        actions.append(("Records", "tower_page", ("records", None)))
        return TITLE, self._status_line(), actions, (STYLE_HOME, 0)

    def _render_solo(self, floor):
        """The confirmation of a solo battle: who, where, what it pays, the player's experience cap (never the team)."""
        view, player = self._view, self._player()
        replay = floor != player["progress"]
        title = f"Floor {floor}" + (" (replay)" if replay else "")
        kind = KIND_NAMES[self._kind(floor)]
        status = f"Lv{floor} {kind}" + (f", {self._region(floor)}" if self._region(floor) else "")
        actions = [("vs " + self._trainer(floor), "", ())]
        actions.extend(self._reward_rows(floor))
        save = view.get("save")
        if save is not None:
            actions.append((f"Exp cap: Lv{save['cap']}" + (" (Champion)" if save["champion"]
                                                           else f" ({save['badges']} badges)"), "", ()))
        battle = view.get("battle")
        if battle is not None and (battle["mode"] != "solo" or battle["state"] == "issued"):
            status = self._status_line()
        else:
            actions.append(("Start the battle", "tower_solo", (floor,)))
        return title, status, actions, (STYLE_PREVIEW, floor)

    def _floor_mark(self, floor):
        player = self._player()
        if floor == player["progress"]:
            return ">"
        return "+" if floor <= player["highest"] else "-"

    def _floor_row(self, floor, op_page):
        return (f"{floor:>3}{self._floor_mark(floor)} {self._trainer(floor)}", "tower_page", (op_page, floor))

    def _render_replay(self, page_no):
        """A floor already cleared, newest first, four to a page."""
        player = self._player()
        floors = list(range(min(player["highest"], FLOORS), 0, -1))
        pages = max(1, (len(floors) + PER_PAGE - 1) // PER_PAGE)
        page_no = page_no if type(page_no) is int and 0 <= page_no < pages else 0
        shown = floors[page_no * PER_PAGE:(page_no + 1) * PER_PAGE]
        actions = [(f"{f:>3} {self._trainer(f)}", "tower_page", ("solo", f)) for f in shown]
        if pages > 1:
            actions.append((f"More floors ({page_no + 1}/{pages})", "tower_page", ("replay", (page_no + 1) % pages)))
        status = "Replays: Exp. only, no BP" if floors else "Clear a floor to replay it"
        return "Replay a floor", status, actions, (STYLE_MAP, shown[-1] if shown else 1)

    def _render_bosses(self, page_no):
        """The bosses and special floors, four to a page, and the floor map."""
        data = self._data()
        bosses = list(data.bosses()) if data is not None else [10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 100]
        pages = (len(bosses) + PER_PAGE - 1) // PER_PAGE
        page_no = page_no if type(page_no) is int and 0 <= page_no < pages else 0
        shown = bosses[page_no * PER_PAGE:(page_no + 1) * PER_PAGE]
        player = self._player()
        actions = [("Floor map", "tower_page", ("map", (min(player["progress"], FLOORS) - 1) // PER_PAGE * PER_PAGE + 1))]
        actions.extend(self._floor_row(floor, "preview") for floor in shown)
        actions.append((f"More bosses ({page_no + 1}/{pages})", "tower_page", ("bosses", (page_no + 1) % pages)))
        status = "Tower data missing in this app" if data is None else "+ cleared  > your floor"
        return "Floors and bosses", status, actions, (STYLE_MAP, shown[0])

    def _render_map(self, first):
        """The floor map, four floors to a page."""
        first = first if type(first) is int and 1 <= first <= FLOORS else 1
        shown = range(first, min(FLOORS, first + PER_PAGE - 1) + 1)
        actions = [self._floor_row(floor, "preview") for floor in shown]
        actions.append(("Next floors", "tower_page", ("map", first + PER_PAGE if first + PER_PAGE <= FLOORS else 1)))
        actions.append(("Previous floors", "tower_page", ("map", first - PER_PAGE if first > PER_PAGE
                                                          else (FLOORS - 1) // PER_PAGE * PER_PAGE + 1)))
        return f"Floors {shown[0]}-{shown[-1]}", "+ cleared  > your floor", actions, (STYLE_MAP, first)

    def _render_preview(self, floor):
        """A floor or a boss: name, region, floor, difficulty and the prize; never the team."""
        player = self._player()
        data = self._data()
        entry = data.floor(floor) if data is not None else {}
        kind = KIND_NAMES[entry.get("kind", "regular")]
        title = f"Floor {floor}: {kind}"
        actions = [(self._trainer(floor), "", ())]
        if self._region(floor):
            actions.append((f"Region: {self._region(floor)}", "", ()))
        if entry.get("difficulty") is not None:
            actions.append((f"Difficulty: {entry['difficulty']}", "", ()))
        actions.extend(self._reward_rows(floor))
        if floor == player["progress"] or floor <= player["highest"]:
            status = "Your next floor" if floor == player["progress"] else "Cleared: replay for Exp."
            actions.append(("Fight this floor", "tower_page", ("solo", floor)))
        else:
            status = f"Clear floor {min(player['progress'], FLOORS)} first"
        return title, status, actions[:6], (STYLE_PREVIEW, floor)

    def _milestone_owed(self):
        return next((m for m in (self._view or {}).get("milestones") or () if m["state"] == "owed"), None)

    def _render_prizes(self, _):
        view, player = self._view, self._player()
        claimed = sum(bool(player["claims"] >> n & 1) for n in range(len(tower_rewards.PRIZE_FLOORS)))
        actions = [(f"Prizes: {claimed}/{len(tower_rewards.PRIZE_FLOORS)} claimed", "tower_page", ("prize_list", 0))]
        owed = self._milestone_owed()
        status = "Prizes, BP and Hyper Training"
        if owed is not None:
            actions.append((f"Send {owed['name'] or 'Pokemon'} now"[:25], "tower_send", (owed["milestone"],)))
            status = "No room for it: make room"
        waiting = next((m for m in view.get("milestones") or () if m["state"] in ("waiting", "sent")), None)
        if waiting is not None and owed is None:
            status = ("Your Pokemon is on its way" if waiting["state"] == "sent"
                      else "Your Pokemon waits for your level")
        bp = (view.get("save") or {}).get("bp")
        actions.append((f"Tower Shop ({'?' if bp is None else bp} BP)", "tower_page", ("shop", 0)))
        actions.append(("Hyper Training", "tower_page", ("training", None)))
        return "Prizes and shop", status, actions, (STYLE_PRIZES, 0)

    def _render_prize_list(self, page_no):
        player = self._player()
        floors = tower_rewards.PRIZE_FLOORS
        pages = (len(floors) + PER_PAGE - 1) // PER_PAGE
        page_no = page_no if type(page_no) is int and 0 <= page_no < pages else 0
        actions = []
        for floor in floors[page_no * PER_PAGE:(page_no + 1) * PER_PAGE]:
            mark = "+" if player["claims"] & tower_rewards.claim_bit(floor) else "-"
            actions.append((f"{mark}{floor:>3} {PRIZE_LABELS[floor]}", "tower_page", ("prize", floor)))
        actions.append((f"More prizes ({page_no + 1}/{pages})", "tower_page", ("prize_list", (page_no + 1) % pages)))
        return "Floor prizes", "+ claimed: first clears only", actions, (STYLE_PRIZES, 0)

    def _render_prize(self, floor):
        player = self._player()
        prize = tower_rewards.PRIZES[floor]
        actions = []
        actions.extend((tower_rewards.describe_items((item,)), "", ()) for item in prize.items)
        if prize.milestone is not None:
            actions.append((tower_rewards.MILESTONE_KINDS[prize.milestone][:25], "", ()))
        if prize.money:
            actions.append((f"Money: {_money(prize.money)}", "", ()))
        actions.append((f"Battle Points: {tower_rewards.first_clear_bp(floor)}", "", ()))
        claimed = player["claims"] & tower_rewards.claim_bit(floor)
        milestone = next((m for m in (self._view or {}).get("milestones") or () if m["floor"] == floor), None)
        if milestone is not None and milestone["name"]:
            actions.append((f"{milestone['name']} Lv{milestone['level']}: {milestone['state']}", "", ()))
        status = "Claimed" if claimed else f"First clear of floor {floor}"
        return f"Floor {floor} prize", status, actions, (STYLE_PRIZES, floor)

    def _render_shop(self, page_no):
        """The Tower Shop: points are taken from your save first, then the item is given (refunded without room)."""
        view = self._view
        shop = view.get("shop") or []
        bp = (view.get("save") or {}).get("bp")
        status = "Your BP: " + ("?" if bp is None else str(bp))
        purchase = view.get("purchase")
        if purchase is not None:
            status = {"debit": CLOSE_TO_FINISH, "granting": CLOSE_TO_FINISH,
                      "done": "Bought " + purchase["name"][:18], "refused": "Not enough BP in the game",
                      "refunded": "No room: BP returned", "void": "Order not taken: try again"}.get(purchase["state"], status)
        pages = max(1, (len(shop) + PER_PAGE - 1) // PER_PAGE)
        page_no = page_no if type(page_no) is int and 0 <= page_no < pages else 0
        actions = [(f"{entry['name'][:15]} {entry['price']}BP", "tower_buy", (entry["slot"],))
                   for entry in shop[page_no * PER_PAGE:(page_no + 1) * PER_PAGE]]
        if pages > 1:
            actions.append((f"More items ({page_no + 1}/{pages})", "tower_page", ("shop", (page_no + 1) % pages)))
        return "Tower Shop", status, actions, (STYLE_SHOP, 0)

    def _render_training(self, _):
        actions = [("Open Hyper Training", "tower_hyper", ())]
        if (self._view or {}).get("party"):
            actions.append(("Party IVs (last save)", "tower_page", ("party", None)))
        actions.append(("Bottle Cap: one stat", "", ()))
        actions.append(("Gold Bottle Cap: all six", "", ()))
        return "Hyper Training", "Trained stats count as 31", actions, (STYLE_TRAINING, 0)

    def _render_party(self, _):
        actions = []
        for index, mon in enumerate((self._view or {}).get("party") or ()):
            if mon["egg"]:
                actions.append(("Egg", "", ()))
                continue
            left = sum(1 for iv, trained in zip(mon["ivs"], mon["trained"]) if iv < 31 and not trained)
            actions.append((f"{mon['name'][:10]} L{mon['level']}: {left} to train", "tower_page", ("mon", index)))
        return "Party IVs", "Natural IVs from your last save", actions[:6], (STYLE_TRAINING, 0)

    def _render_mon(self, index):
        party = (self._view or {}).get("party") or []
        if type(index) is not int or not 0 <= index < len(party):
            return "Party IVs", "Save to see your party", [], (STYLE_TRAINING, 0)
        mon = party[index]
        actions = [(f"{name}: {iv}" + (" (trained)" if trained else " (max)" if iv == 31 else ""), "", ())
                   for name, iv, trained in zip(STAT_NAMES, mon["ivs"], mon["trained"])]
        return _text(f"{mon['name']} Lv{mon['level']}", 23), "Natural IVs; trained count 31", actions, (STYLE_TRAINING, 0)

    def _render_records(self, _):
        player, records = self._player(), (self._view or {}).get("records") or []
        actions = [(f"You: best {player.get('best_solo', 0)}, Duo {player.get('best_duo', 0)}", "", ()),
                   (f"Won {player.get('wins', 0)} Lost {player.get('losses', 0)} Clears {player.get('completions', 0)}",
                    "", ())]
        for rank, entry in enumerate(records[:4], 1):
            actions.append((f"{rank}. {entry['name'][:10]} {entry['best_solo']} ({entry['wins']}W)", "", ()))
        return "Tower records", "Highest floors in this world", actions, (STYLE_RECORDS, 0)

    # ------------------------------------------------------------------- Duo
    def _duo_member(self, member, floor):
        """One player of the Duo: whether this floor pays them its first-clear rewards ("prizes") or, cleared before,
        only experience (each player reckoned on their own)."""
        role = "prizes" if member.get("first_clear", member["progression"]) else "Exp only"
        state = ", ready" if member["ready"] else ""
        return (f"{member['name'][:8]}: {role}{state}", "", ())

    def _render_duo(self, _):
        view, actor = self._view, self._actor
        duo, mate = view.get("duo"), view.get("teammate")
        if duo is None or duo["state"] == "ended":
            status = DUO_ENDINGS.get((duo or {}).get("reason"), "Two players, three Pokemon each")
            if mate is None:
                return "Tower Duo", "Form a team in PLAYERS first", [("Choose a teammate", "tower_players", ())], \
                    (STYLE_DUO, 0)
            player = self._player()
            floor = default_duo_floor(player["progress"], mate["progress"])
            actions = [(f"{mate['name'][:12]}: floor {min(mate['progress'], FLOORS)}", "", ()),
                       (f"You: floor {min(player['progress'], FLOORS)}", "", ()),
                       (f"Invite: floor {floor}", "tower_duo", ("duo_invite", floor)),
                       ("Invite: replay a floor", "tower_page", ("duo_floor", 0))]
            return "Tower Duo", status, actions, (STYLE_DUO, floor)
        members = duo["members"]
        floor = duo["floor"]
        actions = [self._duo_member(member, floor) for member in members]
        mine = next(member for member in members if member["player_id"] == actor)
        if duo["state"] == "invited":
            if duo["proposer"] == actor:
                status = f"Waiting for {members[1]['name'][:12]}"
                actions.append(("Cancel the invitation", "tower_duo", ("duo_leave",)))
            else:
                status = f"{members[0]['name'][:12]} invites you"
                actions.append((f"Accept: floor {floor}", "tower_duo", ("duo_accept",)))
                actions.append(("Decline", "tower_duo", ("duo_decline",)))
            return f"Duo: floor {floor}", status, actions, (STYLE_DUO, floor)
        if duo["state"] == "battle":
            status = NATIVE_STATES.get(duo.get("native"), "Open Challenges to battle")
            actions.append(("Open Challenges", "tower_challenges", ()))
            return f"Duo: floor {floor}", status, actions, (STYLE_DUO, floor)
        ready = sum(member["ready"] for member in members)
        status = f"Floor {floor}: {ready}/2 ready"
        if mine.get("save_needed"):
            status = "Save first: START > SAVE"          # the last Duo battle's experience is not in the save yet
        elif any(member.get("save_needed") for member in members):
            other = next(member for member in members if member.get("save_needed"))
            status = f"{other['name'][:10]} must save first"
        team = mine.get("team")
        actions.append(("Team: " + (", ".join(team) if team else "choose")[:19], "tower_page", ("team", 0)))
        actions.append(("Not ready" if mine["ready"] else "Ready", "tower_duo", ("duo_unready" if mine["ready"]
                                                                                 else "duo_ready",)))
        if duo["proposer"] == actor:      # the Duo's host chooses its floor
            actions.append(("Change floor", "tower_page", ("duo_floor", 0)))
        actions.append(("Leave the Duo", "tower_duo", ("duo_leave",)))
        return f"Duo: floor {floor}", status, actions, (STYLE_DUO, floor)

    def _render_duo_floor(self, page_no):
        """The Duo's floor: the default (the lower progress floor) or a replay both players have unlocked."""
        view = self._view
        duo = view.get("duo")
        player = self._player()
        if duo is not None and duo["state"] != "ended":
            members = duo["members"]
            top = min(max_unlocked(m["progress"], m["highest"]) for m in members)
            default = default_duo_floor(*(m["progress"] for m in members))
            operation = "duo_floor"
        else:
            mate = view.get("teammate") or {"progress": 1, "highest": 0}
            top = min(max_unlocked(player["progress"], player["highest"]), max_unlocked(mate["progress"], mate["highest"]))
            default, operation = default_duo_floor(player["progress"], mate["progress"]), "duo_invite"
        floors = [default] + [f for f in range(top, 0, -1) if f != default]
        pages = max(1, (len(floors) + PER_PAGE - 1) // PER_PAGE)
        page_no = page_no if type(page_no) is int and 0 <= page_no < pages else 0
        shown = floors[page_no * PER_PAGE:(page_no + 1) * PER_PAGE]
        actions = [(f"{f:>3} {self._trainer(f, 'a')}", "tower_duo", (operation, f)) for f in shown]
        if pages > 1:
            actions.append((f"More floors ({page_no + 1}/{pages})", "tower_page", ("duo_floor", (page_no + 1) % pages)))
        return "Duo floor", f"Up to floor {top} for both", actions, (STYLE_MAP, min(shown))

    def _render_team(self, page_no):
        """The Duo team: tap a Pokemon to bring it (at most three; a full team gives up its first member)."""
        team = (self._view or {}).get("team")
        if team is None:
            return "Your Duo team", "No saved party yet", [], (STYLE_DUO, 0)
        slots, limit = team["slots"], team["limit"]
        pages = max(1, (len(slots) + PER_PAGE - 1) // PER_PAGE)
        page_no = page_no if type(page_no) is int and 0 <= page_no < pages else 0
        actions = []
        for slot in slots[page_no * PER_PAGE:(page_no + 1) * PER_PAGE]:
            if slot["egg"]:
                actions.append(("Egg (cannot fight)", "", ()))
                continue
            mark = "*" if slot["selected"] else "-"
            actions.append((f"{mark} {slot['name'][:11]} L{slot['level']}" + ("" if slot["able"] else " (fnt)"),
                            "tower_bring", (slot["slot"], page_no)))
        if pages > 1:
            actions.append((f"More ({page_no + 1}/{pages})", "tower_page", ("team", (page_no + 1) % pages)))
        count = sum(1 for slot in slots if slot["selected"])
        return "Your Duo team", f"Bring up to {limit}: {count} chosen" + (" (auto)" if team["auto"] else ""), actions, \
            (STYLE_DUO, 0)
