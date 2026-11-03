"""Six-row Championship pages composed into the existing native Players menu (protocol version 2, step 18).

The parent owns native screen revisions, choice consumption and the session lock. This controller issues only
authenticated bracket requests. Two players' match proposal returns to ordinary Challenges, whose separate Accept/Enter
flow retains all native admission and recovery ownership. A match against a computer trainer is answered with the
host's command for this player's own game (the Battle Tower's solo command, mode 2): ``choose`` returns it as
("command", TowerCommand) and the parent sends it as the window's answer (menu flags 4), as for a Tower floor.

Pages: the bracket (the player's own next match first, then the quarterfinals, semifinals and final, the places and
consent), a stage's matches, a match, the places (players with their consent, then the computer trainers), a new
bracket (which connected players take part), recent brackets and one of them. B goes back a page.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from uuid import uuid4

from .championship8_protocol import (MAX_PLAYERS, MIN_PLAYERS, STAGE_NAMES, VERSION, match_players,
                                     validate_championship_reply)
from .companion import BattleChallengeError


class ChampionshipMenuError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _text(value, limit=25):
    return "".join(char if 32 <= ord(char) <= 126 else "?" for char in value)[:limit]


STAGE_SHORT = {1: "QF", 2: "SF", 3: "Final"}
RULE_NAMES = {"open": "Open", "species_clause": "Species Clause", "item_clause": "Item Clause",
              "level_50": "Level 50", "level_30": "Level 30", "no_legendaries": "No Legendaries"}


class ChampionshipMenu:
    def __init__(self, companion):
        self.companion = companion
        self.reset()

    def reset(self):
        self._binding = None
        self._page = ("overview", None)
        self._current = None
        self._history = []
        self._history_dirty = True
        self._draft = None
        self._supported = None
        self._uncertain = False
        self._notice = ""

    def open(self):
        self._page = ("overview", None)

    def _session(self):
        companion = self.companion
        return ((companion.world_id, companion.server_epoch, companion.session_epoch)
                if companion.connected else None)

    @property
    def _actor(self):
        return self.companion.config.player_id

    def _roster(self):
        return {player["player_id"]: player["display_name"] for player in self.companion._players}

    def _check_binding(self):
        if self._binding is None or self._session() != self._binding:
            raise ChampionshipMenuError("session_changed")

    def _computers_capable(self):
        """This game fights a computer match (the solo command's mode 2: championship_abi_version 1)."""
        return getattr(getattr(self.companion, "config", None), "championship_abi_version", 0) == 1

    async def _rpc(self, operation, **fields):
        """The host's answer (the reply's extension), or None when it refused or the outcome is unknown."""
        self._check_binding()
        binding = self._binding
        request = dict(version=VERSION, operation=operation, **fields)
        try:
            reply = await self.companion.battle_challenge_rpc("pending", championship=request)
        except BattleChallengeError as error:
            self._check_binding()
            if error.code in {"invalid_field", "invalid_fields", "championship_unsupported", "championship_disabled",
                              "battle_disabled"}:
                self._supported = False
                self._notice = "Host has no Championship support"
            elif error.code in {"championship_ineligible", "championship_busy", "championship_unavailable"}:
                self._notice = str(error)[:31]  # "Name: Over level 50", "Finish your Tower battle first"
            else:
                self._notice = {
                    "player_offline": "A participant disconnected",
                    "player_busy": "A participant is busy",
                    "battle_busy": "Finish the current battle first",
                    "no_pokemon": "Get a Pokemon in Birch's lab",
                    "peer_no_pokemon": "A trainer has no Pokemon yet",
                    "championship_changed": "Bracket changed; refresh first",
                    "championship_stale": "Bracket changed; refresh first",
                    "championship_waiting": "Original match is still waiting",
                    "championship_cancel_pending": "Resolve the cancel votes first",
                    "championship_result_pending": "Waiting for the match result",
                    "championship_roster_changed": "A player disconnected",
                }.get(error.code, "Host refused; refresh bracket")
            return None
        except (ConnectionError, OSError, asyncio.TimeoutError):
            # A lost reply can follow a committed proposal, consent or issued battle. Never retry a mutation
            # automatically or manufacture a fresh match from a transport failure.
            self._uncertain = True
            self._notice = "Outcome unknown; refresh status"
            return None
        if self._session() != binding:
            raise ChampionshipMenuError("session_changed")
        extension = reply.get("championship")
        validate_championship_reply(extension, self._actor, request)
        self._supported = True
        self._current = deepcopy(extension["current"])
        if operation == "history":
            self._history = deepcopy(extension["history"])
            self._history_dirty = False
        if self._uncertain:
            self._notice = "Current host bracket reloaded"
        self._uncertain = False
        return extension

    async def refresh(self):
        binding = self._session()
        if binding is None:
            self.reset()
            self._notice = "Connection lost"
            return
        if binding != self._binding:
            self.reset()
            self._binding = binding
        operation = "history" if self._page[0] in {"history", "record"} and self._history_dirty else "status"
        if await self._rpc(operation) is not None:
            if (self._page[0] == "create" and self._current is not None
                    and self._current["state"] in {"proposed", "active"}):
                self._draft = None
                self._page = ("overview", None)
                self._notice = "An existing bracket needs review"

    @staticmethod
    def _params(current):
        return (current["championship_id"], current["generation"], current["fingerprint"])

    def _require_current(self, args):
        current = self._current
        if current is None or tuple(args[:3]) != self._params(current):
            raise ChampionshipMenuError("championship_changed")
        return current

    # --------------------------------------------------------------- names
    @staticmethod
    def _entrant_name(view, seed, long=False):
        entrant = view["entrants"][seed]
        if entrant["player"] is not None or not long:
            return entrant["name"]
        return f"{entrant['title']} {entrant['name']}"

    def _side(self, view, match, index):
        """A match's place as a row names it: the entrant, or the earlier match whose winner takes it."""
        if match["seeds"]:
            return self._entrant_name(view, match["seeds"][index])
        return "?"

    def _match_label(self, view, match):
        number = self._stage_number(view, match)
        head = STAGE_SHORT[match["stage"]] + (str(number) if match["stage"] != 3 else "")
        if not match["seeds"]:
            return f"{head}: waiting"
        if match["state"] == "won":
            return f"{head}: {self._entrant_name(view, match['winner'])} won"
        return f"{head} {self._side(view, match, 0)} v {self._side(view, match, 1)}"

    @staticmethod
    def _stage_number(view, match):
        return 1 + [m["round"] for m in view["matches"] if m["stage"] == match["stage"]].index(match["round"])

    def _my_match(self, view):
        """The player's own match that is not decided yet (the earliest), or None."""
        for match in view["matches"]:
            if self._actor in match_players(view["entrants"], match) and match["state"] != "won":
                return match
        return None

    # --------------------------------------------------------------- choices
    async def choose(self, operation, args):
        """None, or "battles" when the parent should open ordinary Challenges, "leave" for the Players home, or
        ("command", TowerCommand) when the window's answer starts a computer match in this game."""
        self._check_binding()
        if not isinstance(operation, str) or not operation.startswith("champ_"):
            raise ChampionshipMenuError("stale_menu")
        self._notice = ""
        if operation == "champ_back":
            page = self._page[0]
            if page == "match" and self._current is not None:
                match = self._current["matches"][self._page[1]] if self._page[1] < len(self._current["matches"]) else None
                self._page = ("stage", match["stage"]) if match is not None and match["stage"] != 3 else ("overview", None)
            elif page == "record":
                self._page = ("history", None)
            elif page in {"stage", "places", "computers", "create", "history"}:
                self._page = ("overview", None)
                self._draft = None
            else:
                return "leave"
            return None
        if operation == "champ_refresh":
            if self._page[0] in {"history", "record"}:
                self._history_dirty = True
            return None
        if operation == "champ_overview":
            self._page = ("overview", None)
            return None
        if operation == "champ_history":
            self._page = ("history", None)
            self._history_dirty = True
            return None
        if operation == "champ_record":
            if not any(record["championship_id"] == args[0] for record in self._history):
                raise ChampionshipMenuError("championship_changed")
            self._page = ("record", args[0])
            return None
        if operation in {"champ_places", "champ_computers"}:
            self._require_current(args)
            self._page = ("places" if operation == "champ_places" else "computers", None)
            return None
        if operation == "champ_stage":
            current = self._require_current(args)
            if type(args[3]) is not int or args[3] not in {match["stage"] for match in current["matches"]}:
                raise ChampionshipMenuError("stale_menu")
            stage = args[3]
            matches = [match for match in current["matches"] if match["stage"] == stage]
            self._page = ("match", matches[0]["round"]) if len(matches) == 1 else ("stage", stage)
            return None
        if operation == "champ_round":
            current = self._require_current(args)
            if type(args[3]) is not int or not 0 <= args[3] < len(current["matches"]):
                raise ChampionshipMenuError("stale_menu")
            self._page = ("match", args[3])
            return None
        if self._supported is not True or self._uncertain:
            raise ChampionshipMenuError("championship_unavailable")
        if operation == "champ_new":
            if self._current is not None and self._current["state"] not in {"completed", "canceled"}:
                raise ChampionshipMenuError("championship_busy")
            roster = self._roster()
            if self._actor not in roster or len(roster) < MIN_PLAYERS:
                self._notice = "Another player must be online"
                return None
            others = sorted(player for player in roster if player != self._actor)[:MAX_PLAYERS - 1]
            self._draft = dict(championship_id=str(uuid4()), players=[self._actor, *others], candidates=others,
                               names={player: roster[player] for player in [self._actor, *others]})
            self._page = ("create", None)
            return None
        if operation == "champ_toggle":
            draft = self._draft
            if draft is None or len(args) != 2 or args[0] != draft["championship_id"] or args[1] not in draft["candidates"]:
                raise ChampionshipMenuError("stale_menu")
            players = draft["players"]
            if args[1] in players:
                players.remove(args[1])
            else:
                players.append(args[1])
                players[1:] = [player for player in draft["candidates"] if player in players]
            self._page = ("create", None)
            return None
        if operation == "champ_create":
            draft = self._draft
            if draft is None or tuple(args) != (draft["championship_id"], *draft["players"]):
                raise ChampionshipMenuError("stale_menu")
            roster = self._roster()
            if any(roster.get(player) != draft["names"][player] for player in draft["players"]):
                self._draft = None
                self._page = ("overview", None)
                self._notice = "Players changed; review again"
                return None
            if len(draft["players"]) < MIN_PLAYERS:
                self._notice = "Choose at least one more player"
                return None
            # Propose expressly records the proposer's consent; no other participant's bracket or battle consent.
            await self._rpc("create", championship_id=draft["championship_id"], players=list(draft["players"]))
            self._draft = None
            self._page = ("overview", None)
            return None
        current = self._require_current(args)
        fields = dict(zip(("championship_id", "generation", "fingerprint"), self._params(current)))
        if operation == "champ_accept":
            accepting = current["state"] == "proposed" and self._actor not in current["consent"]
            withdrawing = current["state"] == "active" and self._actor in current["cancel_consent"]
            if not accepting and not withdrawing:
                raise ChampionshipMenuError("championship_changed")
            if await self._rpc("accept", **fields) is not None and withdrawing:
                self._notice = "Your cancel vote was withdrawn"
            self._page = ("overview", None)
        elif operation == "champ_cancel":
            if current["state"] not in {"proposed", "active"} or self._actor in current["cancel_consent"]:
                raise ChampionshipMenuError("championship_changed")
            if await self._rpc("cancel", **fields) is not None:
                self._notice = ("Bracket canceled" if self._current is None or self._current["state"] == "canceled"
                                else "Cancel vote saved")
            self._page = ("overview", None)
        elif operation == "champ_battle":
            match = current["matches"][args[3]]
            if (match["battle_id"] != args[4] or self._actor not in match_players(current["entrants"], match)
                    or match["state"] != "invited" or match["kind"] != "players"):
                raise ChampionshipMenuError("championship_changed")
            return "battles"
        elif operation == "champ_match":
            match = current["matches"][args[3]]
            if (current["state"] != "active" or self._actor not in match_players(current["entrants"], match)
                    or match["attempt"] != args[4] or match["state"] == "won"):
                raise ChampionshipMenuError("championship_changed")
            computer = match["kind"] == "computer"
            if computer and not self._computers_capable():
                self._notice = "Update the game for this match"
                return None
            if not computer and (current["cancel_consent"] or match["state"] not in {"ready", "draw", "canceled"}):
                raise ChampionshipMenuError("championship_changed")
            reply = await self._rpc("match", **fields, round=match["round"], attempt=match["attempt"])
            if reply is None:
                return None
            if computer:
                command = reply.get("command")
                if command is None:
                    after = self._current["matches"][args[3]] if self._current is not None else None
                    self._notice = ("No result came: counted as a loss" if after is not None and after["state"] == "won"
                                    else "Match status refreshed")
                    return None
                from .menu_mailbox import CHAMPIONSHIP_MODE, TowerCommand
                return ("command", TowerCommand(command["ticket"], command["table_hash"], command["floor"],
                                                CHAMPIONSHIP_MODE, command["round"], command["flags"]))
            return "battles"
        elif operation == "champ_recover":
            match = current["matches"][args[3]]
            if (current["state"] != "active" or self._actor not in match_players(current["entrants"], match)
                    or match["state"] != "waiting" or match["attempt"] != args[4] or match["battle_id"] != args[5]):
                raise ChampionshipMenuError("championship_changed")
            if await self._rpc("recover", **fields, round=match["round"], attempt=match["attempt"],
                               battle_id=match["battle_id"]) is not None:
                recovered = self._current["matches"][args[3]]
                self._notice = ("Unstarted match safely canceled" if recovered["state"] == "canceled"
                                else "Safety evidence incomplete; kept waiting" if recovered["state"] == "waiting"
                                else "Original match status refreshed")
        else:
            raise ChampionshipMenuError("stale_menu")
        return None

    # --------------------------------------------------------------- pages
    def render(self):
        title, status = "Championship", self._notice
        if self._binding is None or self._session() != self._binding:
            return title, "Connection lost; reopen Players", []
        if self._supported is not True:
            return title, status or "Championship unavailable", [("Refresh availability", "champ_refresh", ())]
        if self._uncertain:
            return title, status or "Outcome unknown; refresh status", [("Refresh host status", "champ_refresh", ())]
        page, target = self._page
        current = self._current
        if page == "create" and self._draft is not None:
            title, status, actions = self._render_create()
        elif page == "history":
            title, status, actions = self._render_history(status)
        elif page == "record":
            title, status, actions = self._render_record(target)
        elif current is None:
            roster = self._roster()
            status = status or "Players + computer trainers"
            actions = [("Propose a Championship", "champ_new", ()) if len(roster) >= MIN_PLAYERS
                       else ("Needs another player", "", ())]
            actions.extend((("Recent Championships", "champ_history", ()), ("Refresh", "champ_refresh", ())))
        elif page == "places":
            title, status, actions = self._render_places(current, status)
        elif page == "computers":
            title = "Computer trainers"
            status = status or f"Rule: {RULE_NAMES.get(current['rule'], current['rule'])}"
            actions = [(_text(f"{entrant['seed'] + 1} {entrant['title']} {entrant['name']}", 21)
                        + f" {entrant['floor']}", "", ())
                       for entrant in current["entrants"] if entrant["player"] is None][:6]
        elif page == "stage":
            matches = [match for match in current["matches"] if match["stage"] == target]
            title = STAGE_NAMES[target] + "s"
            status = status or f"{sum(match['state'] == 'won' for match in matches)}/{len(matches)} decided"
            params = self._params(current)
            actions = [(_text(self._match_label(current, match)), "champ_round", (*params, match["round"]))
                       for match in matches]
            actions.append(("Refresh", "champ_refresh", ()))
        elif page == "match" and target < len(current["matches"]):
            title, status, actions = self._render_match(current, current["matches"][target], status)
        else:
            title, status, actions = self._render_overview(current, status)
        if len(actions) > 6:
            raise ChampionshipMenuError("menu_capacity")
        return _text(title, 23), _text(status, 31), actions

    def _render_create(self):
        draft = self._draft
        computers = 8 - len(draft["players"])
        actions = [(_text("1 " + draft["names"][self._actor] + " (you)"), "", ())]
        for player in draft["candidates"]:
            mark = "+" if player in draft["players"] else "-"
            actions.append((_text(f"{mark} {draft['names'][player]}"), "champ_toggle", (draft["championship_id"], player)))
        actions.append((_text(f"Propose: {len(draft['players'])} + {computers} computers"), "champ_create",
                        (draft["championship_id"], *draft["players"])))
        return "New Championship", "Propose = accept; +/- a player", actions

    def _render_history(self, status):
        actions = []
        for summary in self._history:
            label = ("Winner: " + summary["champion_name"] if summary["state"] == "completed" else "Canceled bracket")
            actions.append((_text(label), "champ_record", (summary["championship_id"],)))
        actions.extend((("Refresh history", "champ_refresh", ()), ("Current bracket", "champ_overview", ())))
        if not self._history:
            status = status or "No completed brackets recorded"
        return "Recent Championships", status or "Your completed/canceled brackets", actions

    def _render_record(self, target):
        summary = next((record for record in self._history if record["championship_id"] == target), None)
        if summary is None:
            return "Championship record", "No longer in recent history", [("Recent Championships", "champ_history", ())]
        actions = [(_text(name), "", ()) for name in summary["names"]]
        if summary["format"] == 8:
            actions.append((f"+ {8 - len(summary['names'])} computer trainers", "", ()))
        if summary["state"] == "completed":
            actions.append((_text("Winner: " + summary["champion_name"]), "", ()))
            status = "Completed; no fees or rewards"
        else:
            actions.append(("Bracket canceled", "", ()))
            status = "Canceled; no winner assigned"
        return "Championship record", status, actions[:6]

    def _render_places(self, current, status):
        params = self._params(current)
        players = len(current["players"])
        actions = []
        for seed, entrant in enumerate(current["entrants"][:players]):
            mark = ("+ " if entrant["player"] in current["consent"] else "- ") if current["state"] == "proposed" else ""
            actions.append((_text(f"{seed + 1} {mark}{entrant['name']}"), "", ()))
        computers = len(current["entrants"]) - players
        if current["state"] == "proposed":
            status = status or f"Accepted {len(current['consent'])}/{players}"
            if self._actor not in current["consent"]:
                actions.append(("Accept this bracket", "champ_accept", params))
            actions.append(("Cancel proposal", "champ_cancel", params))
        elif current["state"] == "active":
            status = status or f"Cancel votes {len(current['cancel_consent'])}/{players}"
            actions.append((("Withdraw cancel vote", "champ_accept", params) if self._actor in current["cancel_consent"]
                            else ("Vote to cancel bracket", "champ_cancel", params)))
        if computers and len(actions) < 6:
            actions.append((f"{computers} computer trainers", "champ_computers", params))
        return "Places", status or "", actions[:6]

    def _render_overview(self, current, status):
        params = self._params(current)
        players = len(current["players"])
        if current["state"] == "proposed":
            status = status or f"Accepted {len(current['consent'])}/{players}"
        elif current["state"] == "active":
            status = status or (f"Cancel votes {len(current['cancel_consent'])}/{players}" if current["cancel_consent"]
                                else f"Rule: {RULE_NAMES.get(current['rule'], current['rule'])}")
        else:
            status = status or ("Championship completed" if current["state"] == "completed" else "Bracket canceled")
        actions = []
        mine = self._my_match(current) if current["state"] == "active" else None
        if mine is not None:
            actions.append((_text("You: " + self._match_label(current, mine)), "champ_round", (*params, mine["round"])))
        for stage in sorted({match["stage"] for match in current["matches"]}):
            matches = [match for match in current["matches"] if match["stage"] == stage]
            if len(matches) == 1:
                label = self._match_label(current, matches[0])
            else:
                label = f"{STAGE_NAMES[stage]}s {sum(m['state'] == 'won' for m in matches)}/{len(matches)}"
            actions.append((_text(label), "champ_stage", (*params, stage)))
        actions.append(("Places and consent" if current["state"] == "proposed" else "Places", "champ_places", params))
        if len(actions) < 6:
            actions.append(("Refresh", "champ_refresh", ()))
        return "Championship", status, actions

    def _render_match(self, current, match, status):
        number = self._stage_number(current, match)
        title = STAGE_NAMES[match["stage"]] + (f" {number}" if match["stage"] != 3 else "")
        entrants = current["entrants"]
        computer = match["kind"] == "computer"
        status = status or {
            "blocked": "Waiting for earlier matches",
            "ready": ("Battle in your own game" if computer else "Two computer trainers"
                      if match["kind"] == "auto" else "Both must accept a 1v1 challenge"),
            "invited": "Your game starts it" if computer else "Open Challenges to accept/enter",
            "playing": "Match in progress" if computer else "Original match in progress",
            "waiting": "Waiting for original players",
            "draw": "Draw: play it again", "won": "Result recorded",
            "canceled": "Not started: ask again" if computer else "Previous challenge canceled",
        }[match["state"]]
        if (not self._notice and current["state"] == "active" and current["cancel_consent"]
                and match["state"] in {"ready", "draw", "canceled"}):
            status = "Resolve bracket cancel votes"
        actions = []
        for seed in match["seeds"]:
            entrant = entrants[seed]
            label = (f"{seed + 1} {entrant['name']}" if entrant["player"] is not None
                     else f"{seed + 1} {entrant['title']} {entrant['name']}")
            actions.append((_text(label), "", ()))
        if match["winner"] is not None:
            actions.append((_text("Winner: " + self._entrant_name(current, match["winner"])), "", ()))
        elif match["attempt"]:
            actions.append((f"Match attempt: {match['attempt']}", "", ()))
        params = (*self._params(current), match["round"])
        if current["state"] == "active" and self._actor in match_players(entrants, match) and match["state"] != "won":
            if computer:
                other = next(seed for seed in match["seeds"] if entrants[seed]["player"] is None)
                if match["state"] in {"ready", "draw", "canceled"} and not current["cancel_consent"]:
                    actions.append((_text(f"Battle {entrants[other]['name']} now"), "champ_match",
                                    (*params, match["attempt"])))
                elif match["state"] == "invited":
                    actions.append(("Send the battle again", "champ_match", (*params, match["attempt"])))
                elif match["state"] == "playing":
                    # Started, and no result came (the game reports it right after the battle and after it reconnects):
                    # the player may give it up - a loss, as a Tower floor's (the host waits 15 s after a reconnect).
                    actions.append(("Give up: count a loss", "champ_match", (*params, match["attempt"])))
            elif match["state"] in {"ready", "draw", "canceled"} and not current["cancel_consent"]:
                label = "Propose rematch" if match["attempt"] else "Propose 1v1 match"
                actions.append((label, "champ_match", (*params, match["attempt"])))
            elif match["state"] == "invited":
                actions.append(("Open normal Challenges", "champ_battle", (*params, match["battle_id"])))
            elif match["state"] == "waiting":
                actions.append(("Recover waiting match", "champ_recover",
                                (*params, match["attempt"], match["battle_id"])))
        actions.append(("Refresh match", "champ_refresh", ()))
        return title, status, actions[:6]
