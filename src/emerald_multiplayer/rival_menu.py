"""Six-row rival checkpoint pages composed into the existing native Players menu (Update 31).

The parent owns native screen revisions, choice consumption and the session
lock (``player_menu``). This controller only issues authenticated rival RPCs.
Start Now and Wait are votes, never battle consent: a ready match is proposed
here and then accepted and entered through the ordinary Challenges page,
which keeps every native admission and recovery barrier.

This is the EmeraldTogether menu (the native Players menu drawn by the
custom UI), not a GBA dialogue box.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy

from .companion import BattleChallengeError
from .rival_catalogue import BY_ID, checkpoint_at
from .rival_protocol import VERSION, validate_rival_reply


class RivalMenuError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _text(value, limit=25):
    return "".join(char if 32 <= ord(char) <= 126 else "?" for char in value)[:limit]


NOTICES = {
    "rival_not_present": "Stand at the checkpoint first",
    "rival_completed": "Already completed",
    "rival_battling": "A rival battle is in progress",
    "rival_no_usable_pokemon": "Heal a Pokemon first",
    "rival_not_completed": "Not completed by the world yet",
    "rival_solo_unavailable": "Others can still join you",
    "rival_changed": "Checkpoint changed; refreshed",
    "rival_not_ready": "That match is not ready",
    "rival_not_participant": "Not your match",
    "player_offline": "A rival disconnected",
    "battle_busy": "A rival is busy in a battle",
    "player_busy": "A rival is busy",
    "checkpoint_required": "A rival has no saved party",
    "trade_recovery_required": "Finish the pending trade",
}


class RivalMenu:
    def __init__(self, companion):
        self.companion = companion
        self.reset()

    def reset(self):
        self._binding = None
        self._reply = None
        self._supported = None
        self._uncertain = False
        self._notice = ""

    def open(self):
        self._notice = ""

    def _session(self):
        companion = self.companion
        return ((companion.world_id, companion.server_epoch, companion.session_epoch)
                if companion.connected else None)

    @property
    def _actor(self):
        return self.companion.config.player_id

    def local_checkpoint(self):
        """The checkpoint the host last saw this player standing on (host-echoed presence), or None."""
        for player in getattr(self.companion, "_players", ()):
            if player.get("player_id") == self._actor and type(player.get("presence")) is dict:
                presence = player["presence"]
                return checkpoint_at(presence.get("map_group"), presence.get("map_number"))
        return None

    def _check_binding(self):
        if self._binding is None or self._session() != self._binding:
            raise RivalMenuError("session_changed")

    async def _rpc(self, operation, **fields):
        self._check_binding()
        binding = self._binding
        request = dict(version=VERSION, operation=operation, **fields)
        try:
            reply = await self.companion.battle_challenge_rpc("pending", rival=request)
        except BattleChallengeError as error:
            self._check_binding()
            if error.code in {"invalid_field", "invalid_fields", "rival_unsupported", "rival_disabled", "battle_disabled"}:
                self._supported = False
                self._notice = "Host has no rival checkpoints"
            else:
                self._notice = NOTICES.get(error.code, "Host refused; refresh")
            return False
        except (ConnectionError, OSError, asyncio.TimeoutError):
            # A lost reply can follow a committed vote or an issued battle: never
            # retry a mutation automatically; the next refresh shows the truth.
            self._uncertain = True
            self._notice = "Outcome unknown; refresh"
            return False
        if self._session() != binding:
            raise RivalMenuError("session_changed")
        extension = reply.get("rival")
        validate_rival_reply(extension, self._actor, request)
        self._supported = True
        self._reply = deepcopy(extension)
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
        notice = self._notice
        if await self._rpc("status"):
            self._notice = notice

    @property
    def here(self):
        return None if self._reply is None else self._reply["here"]

    def _require(self, checkpoint_id):
        here = self.here
        if here is None or here["checkpoint_id"] != checkpoint_id:
            raise RivalMenuError("rival_changed")
        return here

    async def choose(self, operation, args):
        """Return True only when the parent should open ordinary Challenges."""
        self._check_binding()
        if not isinstance(operation, str) or not operation.startswith("rival_"):
            raise RivalMenuError("stale_menu")
        self._notice = ""
        if operation == "rival_refresh":
            return False
        if self._supported is not True or self._uncertain:
            raise RivalMenuError("rival_unavailable")
        here = self._require(args[0])
        if operation in ("rival_start", "rival_wait"):
            choice = operation.removeprefix("rival_")
            if not here["can_start" if choice == "start" else "can_wait"]:
                raise RivalMenuError("rival_changed")
            if await self._rpc("vote", checkpoint_id=args[0], choice=choice):
                self._notice = "You chose Start Now" if choice == "start" else "You chose to wait"
        elif operation in ("rival_solo", "rival_catch_up"):
            via = operation.removeprefix("rival_")
            if not here["can_solo" if via == "solo" else "can_catch_up"]:
                raise RivalMenuError("rival_changed")
            if await self._rpc("continue", checkpoint_id=args[0], via=via):
                self._notice = "You may continue your journey"
        elif operation == "rival_match":
            session = here["session"]
            if session is None or session["session_id"] != args[1]:
                raise RivalMenuError("rival_changed")
            match = session["matches"][args[2]]
            if match["state"] != "ready" or match["attempt"] != args[3] or self._actor not in sum(match["teams"], []):
                raise RivalMenuError("rival_changed")
            if await self._rpc("match", checkpoint_id=args[0], session_id=args[1], match=args[2], attempt=args[3]):
                return True
        elif operation == "rival_battle":
            return True
        elif operation == "rival_recover":
            session = here["session"]
            if session is None or session["session_id"] != args[1]:
                raise RivalMenuError("rival_changed")
            match = session["matches"][args[2]]
            if match["state"] != "waiting" or match["attempt"] != args[3] or match["battle_id"] != args[4]:
                raise RivalMenuError("rival_changed")
            if await self._rpc("recover", checkpoint_id=args[0], session_id=args[1], match=args[2],
                               attempt=args[3], battle_id=args[4]):
                self._notice = "Recovery checked"
        else:
            raise RivalMenuError("stale_menu")
        return False

    def _name(self, session, player):
        if session is not None and player in session["players"]:
            return session["names"][session["players"].index(player)]
        here = self.here
        for row in (here or {}).get("present", ()):
            if row["player_id"] == player:
                return row["name"]
        return "Trainer"

    def render(self):
        """(title, status, actions) for the parent's six-row screen."""
        title = "Rival checkpoint"
        if self._binding is None or self._session() != self._binding:
            return title, "Connection lost; reopen Players", []
        if self._supported is not True:
            return title, self._notice or "Rival checkpoints unavailable", [("Refresh", "rival_refresh", ())]
        if self._uncertain:
            return title, self._notice or "Outcome unknown; refresh", [("Refresh", "rival_refresh", ())]
        here = self.here
        if here is None:
            done = sum(row["completed"] for row in self._reply["checkpoints"])
            actions = [(_text(f"{BY_ID[row['checkpoint_id']].title}: " + ("done" if row["completed"] else
                       "passed" if row["cleared"] else "open")), "", ()) for row in self._reply["checkpoints"]]
            return title, self._notice or f"World rival progress {done}/5", actions[:5] + [("Refresh", "rival_refresh", ())]
        cid = here["checkpoint_id"]
        title = _text("Rival: " + here["title"], 23)
        status = self._notice or here["message"]
        actions = []
        session = here["session"]
        if here["state"] in ("open", "countdown"):
            for row in here["present"][:3]:
                vote = {"start": "Start", "wait": "Wait", None: "-"}[row["vote"]]
                actions.append((_text(f"{row['name'][:16]}: {vote}"), "", ()))
            if here["can_start"]:
                actions.append(("Start Now", "rival_start", (cid,)))
            if here["can_wait"]:
                actions.append(("Wait for Other Players", "rival_wait", (cid,)))
            if here["can_solo"] and len(actions) < 5:
                actions.append(("Continue on my own", "rival_solo", (cid,)))
        elif here["state"] == "battling" and session is not None:
            for match in session["matches"]:
                if len(actions) >= 4:
                    break
                sides = [" & ".join(self._name(session, p)[:7] for p in team) for team in match["teams"]]
                mine = self._actor in sum(match["teams"], [])
                label = _text(f"{sides[0]} vs {sides[1]}")
                if mine and match["state"] == "ready":
                    actions.append((_text("Battle: " + label), "rival_match",
                                    (cid, session["session_id"], match["index"], match["attempt"])))
                elif mine and match["state"] == "invited":
                    actions.append(("Open Challenges to accept", "rival_battle", (cid,)))
                elif mine and match["state"] == "waiting":
                    actions.append(("Recover waiting battle", "rival_recover",
                                    (cid, session["session_id"], match["index"], match["attempt"], match["battle_id"])))
                else:
                    actions.append((_text(f"{label} {match['state']}"), "", ()))
            if here["can_solo"]:
                actions.append(("Continue on my own", "rival_solo", (cid,)))
        else:
            completion = here["completion"]
            if completion is not None:
                for row in completion["standings"][:4]:
                    actions.append((_text(f"{row['name'][:12]} W{row['wins']} L{row['losses']} D{row['draws']}"), "", ()))
            if here["can_catch_up"]:
                actions.append(("Continue the story", "rival_catch_up", (cid,)))
        actions.append(("Refresh", "rival_refresh", ()))
        if len(actions) > 6:
            raise RivalMenuError("menu_capacity")
        return title, _text(status, 31), actions
