"""Six-row Championship pages composed into the existing native Players menu.

The parent owns native screen revisions, choice consumption and the session
lock. This controller issues only authenticated bracket requests. A successful
match proposal returns to ordinary Challenges, whose separate Accept/Enter
flow retains all native admission and recovery ownership.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from uuid import uuid4

from .championship_protocol import VERSION, validate_championship_reply
from .companion import BattleChallengeError


class ChampionshipMenuError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _text(value, limit=25):
    return "".join(char if 32 <= ord(char) <= 126 else "?" for char in value)[:limit]


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

    async def _rpc(self, operation, **fields):
        self._check_binding()
        binding = self._binding
        request = dict(version=VERSION, operation=operation, **fields)
        try:
            reply = await self.companion.battle_challenge_rpc("pending", championship=request)
        except BattleChallengeError as error:
            self._check_binding()
            if error.code in {"invalid_field", "invalid_fields", "championship_unsupported", "championship_disabled", "battle_disabled"}:
                self._supported = False
                self._notice = "Host has no Championship support"
            elif error.code == "championship_ineligible":
                self._notice = str(error)[:31]  # "Name: Over level 50" (frontier_rules.py)
            else:
                self._notice = {
                    "player_offline": "A participant disconnected",
                    "player_busy": "A participant is busy",
                    "battle_busy": "Finish the current battle first",
                    "no_pokemon": "Get a Pokemon in Birch's lab",
                    "peer_no_pokemon": "A trainer has no Pokemon yet",
                    "championship_busy": "A participant has another bracket",
                    "championship_changed": "Bracket changed; refresh first",
                    "championship_stale": "Bracket changed; refresh first",
                    "championship_waiting": "Original match is still waiting",
                    "championship_cancel_pending": "Cancel needs all four and safety",
                }.get(error.code, "Host refused; refresh bracket")
            return False
        except (ConnectionError, OSError, asyncio.TimeoutError):
            # A lost reply can follow a committed proposal, consent or issued
            # battle. Never retry a mutation automatically or manufacture a
            # fresh match from a transport failure.
            self._uncertain = True
            self._notice = "Outcome unknown; refresh status"
            return False
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
        return True

    async def refresh(self):
        binding = self._session()
        if binding is None:
            self.reset()
            self._notice = "Connection lost"
            return
        if binding != self._binding:
            self.reset()
            self._binding = binding
        operation = ("history" if self._page[0] in {"history", "record"}
                     and self._history_dirty else "status")
        if await self._rpc(operation):
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

    @staticmethod
    def _name(view, player):
        return view["names"][view["players"].index(player)]

    @staticmethod
    def _seeds(view, consent=False):
        result = []
        for index, (player, name) in enumerate(zip(view["players"], view["names"])):
            prefix = f"SF{1 + index // 2} "
            if consent:
                prefix += "+ " if player in view["consent"] else "- "
            result.append((_text(prefix + name), "", ()))
        return result

    async def choose(self, operation, args):
        """Return True only when the parent should open ordinary Challenges."""
        self._check_binding()
        if not isinstance(operation, str) or not operation.startswith("champ_"):
            raise ChampionshipMenuError("stale_menu")
        self._notice = ""
        if operation == "champ_refresh":
            if self._page[0] in {"history", "record"}:
                self._history_dirty = True
            return False
        if operation == "champ_overview":
            self._page = ("overview", None)
            return False
        if operation == "champ_history":
            self._page = ("history", None)
            self._history_dirty = True
            return False
        if operation == "champ_record":
            if not any(record["championship_id"] == args[0] for record in self._history):
                raise ChampionshipMenuError("championship_changed")
            self._page = ("record", args[0])
            return False
        if operation == "champ_participants":
            self._require_current(args)
            self._page = ("participants", None)
            return False
        if operation == "champ_round":
            self._require_current(args)
            if type(args[3]) is not int or args[3] not in range(3):
                raise ChampionshipMenuError("stale_menu")
            self._page = ("round", args[3])
            return False
        if self._supported is not True or self._uncertain:
            raise ChampionshipMenuError("championship_unavailable")
        if operation == "champ_new":
            if self._current is not None and self._current["state"] not in {"completed", "canceled"}:
                raise ChampionshipMenuError("championship_busy")
            roster = self._roster()
            if len(roster) != 4 or self._actor not in roster:
                self._notice = "Connect all four Trainers first"
                return False
            players = [self._actor, *sorted(player for player in roster if player != self._actor)]
            self._draft = dict(championship_id=str(uuid4()), players=players,
                               names=[roster[player] for player in players])
            self._page = ("create", None)
            return False
        if operation == "champ_create":
            draft = self._draft
            if draft is None or tuple(args) != (draft["championship_id"], *draft["players"]):
                raise ChampionshipMenuError("stale_menu")
            roster = self._roster()
            if (set(roster) != set(draft["players"])
                    or [roster.get(player) for player in draft["players"]] != draft["names"]):
                self._draft = None
                self._page = ("overview", None)
                self._notice = "Players changed; review again"
                return False
            # The preview expressly identifies Create as the proposer's consent.
            # No other participant's bracket or battle consent is supplied.
            await self._rpc("create", championship_id=draft["championship_id"], players=list(draft["players"]))
            self._draft = None
            self._page = ("overview", None)
            return False
        current = self._require_current(args)
        fields = dict(zip(("championship_id", "generation", "fingerprint"), self._params(current)))
        if operation == "champ_accept":
            accepting = current["state"] == "proposed" and self._actor not in current["consent"]
            withdrawing = current["state"] == "active" and self._actor in current["cancel_consent"]
            if not accepting and not withdrawing:
                raise ChampionshipMenuError("championship_changed")
            if await self._rpc("accept", **fields) and withdrawing:
                self._notice = "Your cancel vote was withdrawn"
            self._page = ("overview", None)
        elif operation == "champ_cancel":
            if (current["state"] not in {"proposed", "active"}
                    or self._actor in current["cancel_consent"]):
                raise ChampionshipMenuError("championship_changed")
            if await self._rpc("cancel", **fields):
                self._notice = ("Bracket canceled" if self._current["state"] == "canceled"
                                else "Cancel vote saved; no forfeit")
            self._page = ("overview", None)
        elif operation == "champ_battle":
            match = current["matches"][args[3]]
            if (match["battle_id"] != args[4] or self._actor not in match["players"]
                    or match["state"] != "invited"):
                raise ChampionshipMenuError("championship_changed")
            return True
        elif operation == "champ_match":
            match = current["matches"][args[3]]
            if (current["state"] != "active" or self._actor not in match["players"]
                    or match["attempt"] != args[4] or current["cancel_consent"]
                    or match["state"] not in {"ready", "draw", "canceled"}):
                raise ChampionshipMenuError("championship_changed")
            if await self._rpc("match", **fields, round=match["round"], attempt=match["attempt"]):
                return True
        elif operation == "champ_recover":
            match = current["matches"][args[3]]
            if (current["state"] != "active" or self._actor not in match["players"]
                    or match["state"] != "waiting" or match["attempt"] != args[4]
                    or match["battle_id"] != args[5]):
                raise ChampionshipMenuError("championship_changed")
            if await self._rpc("recover", **fields, round=match["round"],
                               attempt=match["attempt"], battle_id=match["battle_id"]):
                recovered = self._current["matches"][args[3]]
                self._notice = ("Unstarted match safely canceled" if recovered["state"] == "canceled"
                                else "Safety evidence incomplete; kept waiting" if recovered["state"] == "waiting"
                                else "Original match status refreshed")
        else:
            raise ChampionshipMenuError("stale_menu")
        return False

    def render(self):
        title, status = "Championship", self._notice
        actions = []
        if self._binding is None or self._session() != self._binding:
            return title, "Connection lost; reopen Players", []
        if self._supported is not True:
            return title, status or "Championship unavailable", [("Refresh availability", "champ_refresh", ())]
        if self._uncertain:
            return title, status or "Outcome unknown; refresh status", [("Refresh host status", "champ_refresh", ())]
        page, target = self._page
        current = self._current
        if page == "create" and self._draft is not None:
            title, status = "New Championship", "Create = accept these pairings"
            actions = self._seeds(self._draft)
            actions.extend((("Create and accept bracket", "champ_create", (self._draft["championship_id"], *self._draft["players"])),
                            ("Back to Championship", "champ_overview", ())))
        elif page == "history":
            title = "Recent Championships"
            status = status or "Your completed/canceled brackets"
            for summary in self._history:
                label = ("Winner: " + self._name(summary, summary["champion"])
                         if summary["state"] == "completed" else "Canceled bracket")
                actions.append((_text(label), "champ_record", (summary["championship_id"],)))
            actions.extend((("Refresh history", "champ_refresh", ()), ("Current bracket", "champ_overview", ())))
            if not self._history:
                status = self._notice or "No completed brackets recorded"
        elif page == "record":
            summary = next((record for record in self._history if record["championship_id"] == target), None)
            title = "Championship record"
            if summary is None:
                status = "No longer in recent history"
            else:
                actions = self._seeds(summary)
                if summary["state"] == "completed":
                    status = "Completed; no fees or rewards"
                    actions.append((_text("Winner: " + self._name(summary, summary["champion"])), "", ()))
                else:
                    status = "Canceled; no winner assigned"
                    actions.append(("Bracket canceled", "", ()))
            actions.append(("Recent Championships", "champ_history", ()))
        elif current is None:
            status = status or "Four Trainers; no fees or rewards"
            if len(self._roster()) == 4:
                actions.append(("Review a new bracket", "champ_new", ()))
            else:
                actions.append(("Connect all four Trainers", "", ()))
            actions.extend((("Recent Championships", "champ_history", ()), ("Refresh", "champ_refresh", ())))
        elif page == "participants":
            title = "Review Championship"
            status = status or (f"Accepted {len(current['consent'])}/4; SF1 and SF2"
                                if current["state"] == "proposed" else f"Cancel votes: {len(current['cancel_consent'])}/4")
            actions = self._seeds(current, consent=True)
            params = self._params(current)
            if current["state"] == "proposed":
                if self._actor not in current["consent"]:
                    actions.append(("Accept these pairings", "champ_accept", params))
                else:
                    actions.append(("Your acceptance is recorded", "", ()))
                actions.append(("Cancel proposal", "champ_cancel", params))
            elif current["state"] == "active":
                actions.append((("Withdraw cancel vote", "champ_accept", params) if self._actor in current["cancel_consent"]
                                else ("Vote to cancel bracket", "champ_cancel", params)))
                actions.append(("View bracket", "champ_overview", ()))
            else:
                actions.append(("View bracket", "champ_overview", ()))
        elif page == "round":
            match = current["matches"][target]
            title = ("Semifinal 1", "Semifinal 2", "Championship final")[target]
            status = status or {
                "blocked": "Waiting for bracket/winners", "ready": "Both must accept a 1v1 challenge",
                "invited": "Open Challenges to accept/enter", "playing": "Original match in progress",
                "waiting": "Waiting for original players", "draw": "Draw; mutual rematch required",
                "won": "Verified battle result recorded", "canceled": "Previous challenge canceled",
            }[match["state"]]
            if (not self._notice and current["state"] == "active" and current["cancel_consent"]
                    and match["state"] in {"ready", "draw", "canceled"}):
                status = "Resolve bracket cancel votes"
            for player in match["players"]:
                actions.append((_text(self._name(current, player)), "", ()))
            if match["winner"] is not None:
                actions.append((_text("Winner: " + self._name(current, match["winner"])), "", ()))
            elif match["attempt"]:
                actions.append((f"Match attempt: {match['attempt']}", "", ()))
            params = (*self._params(current), target)
            if current["state"] == "active" and self._actor in match["players"]:
                if match["state"] in {"ready", "draw", "canceled"} and not current["cancel_consent"]:
                    label = "Propose rematch" if match["attempt"] else "Propose 1v1 match"
                    actions.append((label, "champ_match", (*params, match["attempt"])))
                elif match["state"] == "invited":
                    actions.append(("Open normal Challenges", "champ_battle", (*params, match["battle_id"])))
                elif match["state"] == "waiting":
                    actions.append(("Recover waiting match", "champ_recover",
                                    (*params, match["attempt"], match["battle_id"])))
            actions.extend((("View bracket", "champ_overview", ()), ("Refresh match", "champ_refresh", ())))
        else:
            params = self._params(current)
            status = status or {
                "proposed": f"Bracket consent: {len(current['consent'])}/4",
                "active": (f"Cancel votes: {len(current['cancel_consent'])}/4; no forfeit"
                           if current["cancel_consent"] else "Two semifinals, then the final"),
                "completed": "Championship completed", "canceled": "Bracket canceled; no forfeit",
            }[current["state"]]
            for match in current["matches"]:
                label = ("SF1", "SF2", "Final")[match["round"]]
                if match["winner"] is not None:
                    label += ": " + self._name(current, match["winner"])
                else:
                    label += ": " + match["state"]
                actions.append((_text(label), "champ_round", (*params, match["round"])))
            if current["state"] in {"completed", "canceled"}:
                actions.append(("Review a new bracket", "champ_new", ()))
            else:
                actions.append(("Review pairings / consent", "champ_participants", params))
            actions.extend((("Refresh bracket", "champ_refresh", ()), ("Recent Championships", "champ_history", ())))
        if len(actions) > 6:
            raise ChampionshipMenuError("menu_capacity")
        return _text(title, 23), _text(status, 31), actions
