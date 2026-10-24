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

from .companion import TeamError, BattleChallengeError, LobbyError, TradeError


WAGER_CHOICES = (1_000, 5_000, 10_000, 25_000, 50_000, 100_000)
LABEL_CHARACTERS = 25  # a menu row's label: menu_mailbox packs 26 bytes, NUL-terminated
GYM_LEADERS = {1: "Roxanne", 2: "Brawly", 3: "Wattson", 4: "Flannery", 5: "Norman",
               6: "Winona", 7: "Tate&Liza", 8: "Juan"}
# What a connected player is doing, from the session roster's presence (protocol ACTIVITIES). Every player in the
# roster stays listed whatever they do; only leaving the session removes them.
ACTIVITY_LABELS = {"overworld": "On the field", "battle": "In battle", "menu": "In a menu",
                   "transition": "Changing area", "unavailable": "Busy", "joining": "Joining"}
# The same, beside a place name in a row's 25 characters ("Battle: EVER GRANDE CITY").
ACTIVITY_SHORT = {"overworld": "Field", "battle": "Battle", "menu": "Menu", "transition": "Moving",
                  "unavailable": "Busy", "joining": "Joining"}
_OPEN_BATTLE_STATES = ("invited", "accepted", "prepared")
# "Cancel the challenge?", "Leave the lobby?" and every other question below: a Yes pressed this soon after the question
# appeared is the press before it repeated (a double click, a key held), never an answer (the owner's report of
# 2026-10-24). Measured from when the question was sent to the game to when the press was made.
ASK_GRACE_SECONDS = 0.6
# Choices that end something for another player too (a challenge, a lobby, a team, a trade, a wager, a Frontier or
# League run, a Tower Duo) ask first (the owner's reports of 2026-10-24, "it kicks us out back to start" and "Trade
# cancelled"). Only the question's Yes sends them. The question puts No first (B is No too), and its Yes never sits where
# the press that asked left the game's cursor: the game keeps its cursor row when the next screen comes (back to the top
# when that screen is shorter), so the Yes moves one row down when the asking row was the second one.
#   question: (title, what happens, Yes row, the choice Yes sends, its arguments or None for the asking row's own)
QUESTIONS = {
    "battle_cancel": ("Cancel the challenge?", "Nobody will battle", "Yes, cancel challenge", "battle_cancel", None),
    "lobby_cancel": ("Cancel the lobby?", "It ends for everyone in it", "Yes, cancel the lobby", "lobby_leave", None),
    "lobby_leave": ("Leave the lobby?", "You can be invited again", "Yes, leave the lobby", "lobby_leave", None),
    "lobby_decline": ("Decline the lobby?", "You can be invited again", "Yes, decline it", "lobby_decline", None),
    "team_leave": ("Leave the team?", "You can form a team again", "Yes, leave the team", "team_leave", None),
    "team_decline": ("Decline the invitation?", "You can be invited again", "Yes, decline it", "team_decline", None),
    "team_cancel": ("Cancel the invitation?", "You can invite again", "Yes, cancel it", "team_cancel", None),
    "trade_cancel": ("Decline the trade?", "Nothing will be traded", "Yes, decline the trade", "trade_cancel", None),
    "wager_remove": ("Remove the wager?", "The battle has no stake then", "Yes, remove it", "wager_remove", None),
    "wager_decline": ("Decline the wager?", "The wager is removed for all", "Yes, decline it", "wager_decline", None),
    "ladder_cancel": ("Cancel the invitation?", "You can invite again", "Yes, cancel it", "ladder_cancel", ()),
    "ladder_decline": ("Decline the run?", "You can be invited again", "Yes, decline it", "ladder_cancel", ()),
    "ladder_retire": ("Retire from the run?", "Your run ends here", "Yes, retire", "ladder_retire", ()),
    "duo_cancel": ("Cancel the invitation?", "You can invite again", "Yes, cancel it", "tower_duo", ("duo_leave",)),
    "duo_decline": ("Decline the Duo?", "You can be invited again", "Yes, decline it", "tower_duo", ("duo_decline",)),
    "duo_leave": ("Leave the Duo?", "Your teammate is told", "Yes, leave the Duo", "tower_duo", ("duo_leave",)),
}
# The choices only a question's Yes may send (an older screen offering one directly is never acted on).
_ASKED_OPS = frozenset({"battle_cancel", "lobby_leave", "lobby_decline", "team_leave", "team_decline", "team_cancel",
                        "trade_cancel", "wager_remove", "wager_decline", "ladder_cancel", "ladder_retire"})
_ASKED_TOWER = frozenset({("duo_leave",), ("duo_decline",)})
# The battle modes as PLAYERS names them (a row's 25 characters, a title's 23).
MODE_TITLES = {2: "Rival Battle - 1v1", 3: "Rival Battle - 2v2", 5: "Free-for-All: 4 Players", 6: "Free-for-All: 3 Players"}
MODE_ROWS = {2: "Rival Battle - 1v1", 3: "Rival Battle - 2v2", 5: "Free-for-All - 4 Players", 6: "Free-for-All - 3 Players"}
TRADE_ROW = "Trading"
# Why an Enter battle could not be admitted (BattleAdmissionRefused, the launcher's blocker), in a status line's 31
# characters. The owner's report of 2026-10-20: these used to leave the window on "Waiting for server..." for good.
REFUSALS = {
    "save_recovery_required": "Saving stopped: restart game",
    "character_recovery_pending": "Resolve the trade first",
    "character_busy": "Busy saving: try again shortly",
    "save_not_ready": "Save changed: challenge again",
    "session_changed": "Connection interrupted: wait",
    "battle_admission_required": "Connection changed: try again",
    "battle_recovery_required": "Connection changed: try again",
    "battle_not_ready": "Challenge expired: try again",
    "battle_missing": "Challenge ended: try again",
    "battle_generation_mismatch": "Challenge changed: try again",
    "stale_lease": "Connection changed: try again",
    "game_active": "Your game is busy: try again",
    "save_needed": "Not saved: close menu to save",   # KNOWN_ISSUES MS-60 (the launcher saves when the menu closes)
    "party_unknown": "Your game is busy: try again",   # MS-60: the game could not say what its party is
}
# Why an open challenge ended before its battle (BattleDesk reasons), for the menu that showed it.
CANCEL_REASONS = {
    "canonical_changed": "Cancelled: a party was saved",
    "session_changed": "Cancelled: a player reconnected",
    "deadline": "Challenge expired: not entered",
    "participant_canceled": "Challenge cancelled",
    "admission_canceled": "Challenge cancelled",
    "unentered_invitation_canceled": "Challenge cancelled",
    "native_refused": "Cancelled: a game refused it",
    "save_needed": "Cancelled: a trainer must save",  # KNOWN_ISSUES MS-60
}


# Refusals of an Enter that say only that the challenge is gone. A displayed Enter screen is never refreshed underneath
# (MenuSession._poll), so an Enter can come after the challenge ended; why it ended (CANCEL_REASONS, from the host) says
# more, such as the other trainer's unsaved game (KNOWN_ISSUES MS-60, L stale-save-1).
_CHALLENGE_GONE = frozenset({REFUSALS["battle_not_ready"], REFUSALS["battle_missing"]})


def refusal_text(code):
    return REFUSALS.get(code, "Could not enter: try again")[:31]


def _money(amount):
    return f"${amount:,}"


# Update 32: a new character has no Pokemon until it claims its starter in Birch's lab.
NO_POKEMON_NOTICES = {"no_pokemon": "Get a Pokemon in Birch's lab", "peer_no_pokemon": "They have no Pokemon yet"}
# Host refusals of a new challenge shown in the menu (others keep the menu's own error handling).
INVITE_NOTICES = {"battle_busy": "Finish the battle first", "player_offline": "That player is offline",
                  "trade_recovery_required": "Finish the earlier trade", **NO_POKEMON_NOTICES}
# Update 32: battle lobbies (battle_lobby.py): the host's refusals, and why a lobby ended (a status line's 31 characters).
LOBBY_NOTICES = {"lobby_busy": "Someone is in another lobby", "battle_busy": "Someone has an open challenge",
                 "player_offline": "That player is offline", "lobby_capacity": "Too many lobbies are open",
                 "lobby_closed": "The lobby is closed", "lobby_missing": "The lobby has ended",
                 "lobby_changed": "The lobby changed: try again", "lobby_too_small": "Wait for someone to join",
                 "lobby_answered": "You already answered"}
LOBBY_ENDINGS = {"cancelled": "The lobby was cancelled", "creator_left": "The lobby's leader left",
                 "timed_out": "The lobby timed out", "nobody_joined": "Nobody joined the lobby"}
# A lobby format's challenge (battle_desk.py operations) and the game capability it needs.
LOBBY_INVITES = {"1v1": "invite", "1v1v1": "invite_ffa3", "1v1v1v1": "invite_ffa", "2v2": "invite_multi"}


# Update 32: the soft reset in a world (since MS-61 the game's reset key, Ctrl+R or A+B+START+SELECT, no menu row). The
# launcher starts the game again from the character's last save on the host; it is refused while something the reset
# would cut short is open (a status line's 31 characters).
SOFT_RESET_REFUSALS = {
    "trade_pending": "Finish the trade first",
    "challenge_pending": "Cancel your challenge first",
    "battle_pending": "Finish the battle first",
    "character_busy": "Busy saving: try again shortly",
    "save_recovery_required": "Saving stopped: restart game",
    "character_recovery_pending": "Resolve the trade first",
    "session_changed": "Connection interrupted: wait",
    "game_active": "Your game is busy: try again",
}


def soft_reset_refusal(code):
    return SOFT_RESET_REFUSALS.get(code, "Cannot reset now: try again")[:31]


def save_age(seconds):
    """How long ago this character was last saved (on the host: since MS-61 an in-game SAVE in a world is that save too),
    in a row's 25 characters."""
    if type(seconds) not in (int, float) or seconds < 0:
        return "Last save: at game start"
    minutes = int(seconds // 60)
    if minutes < 1:
        return "Last save: just now"
    if minutes < 60:
        return f"Last save: {minutes} min ago"
    return f"Last save: {min(minutes // 60, 99)} h ago"


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
    # Battle Tower: Legends pages (menu_mailbox.TOWER_STYLES): how the native PC UI draws this page, sent only to a game
    # with the Tower; the classic window ignores it.
    style: int = 0
    style_arg: int = 0


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
        self._activities = {}
        self._friends = {}
        self._wager = None  # {"wager": view | None, "money": int | None} for the pending challenge
        self._lobbies = []        # Update 32: the battle lobbies this player is part of (battle_lobby.py)
        self._lobby_pick = []     # the trainers chosen on the lobby's invitation page
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
        self._habitat = None      # the host's wild-Pokemon view of the player's current map (Phase 7)
        self._frontier = None     # the cooperative Battle Frontier's view (Phase 8)
        self._card = None
        self._card_binding = None
        self._card_notice = ""
        from .championship_menu import ChampionshipMenu
        self._championship = ChampionshipMenu(companion)
        from .rival_menu import RivalMenu
        self._rival = RivalMenu(companion)
        from .record_menu import NativeRecordMenu
        self._record_menu = NativeRecordMenu(companion)
        from .tower_menu import TowerMenu
        self._tower = TowerMenu(companion)      # Battle Tower: Legends (games with tower_abi_version 1)
        self.tower_reply = None                 # a Tower answer the menu session sends as the game's flags 4/5 screen

    def _session(self):
        c = self.companion
        return (c.world_id, c.server_epoch, c.session_epoch) if c.connected else None

    def notice(self, text):
        """A status the next screen shows until the player's next choice (a refused Enter, an ended challenge)."""
        self._notice = _text(text, 31)

    @property
    def screen(self):
        return self._screen

    async def _ended_challenge(self, pending, binding):
        """A challenge this menu showed is no longer pending: say why when it ended without its battle (a save, a
        reconnect, the time limit), instead of the challenge silently disappearing (seen 2026-10-20)."""
        shown = getattr(self, "_shown_battle", None)
        self._shown_battle = pending[0]["battle_id"] if pending else None
        if not shown or (pending and pending[0]["battle_id"] == shown):
            return
        try:
            view = (await self.companion.battle_challenge_rpc("status", battle_id=shown))["result"]
        except (BattleChallengeError, ConnectionError, OSError, asyncio.TimeoutError):
            return
        if self._session() == binding and view.get("state") in ("aborted", "aborting") and (
                not self._notice or self._notice in _CHALLENGE_GONE):
            self._notice = CANCEL_REASONS.get(view.get("reason"), "Challenge cancelled")

    async def refresh(self):
        async with self._lock:
            return await self._refresh()

    async def open(self):
        """A plain OPEN (START > PLAYER > PLAYERS). The soft reset page is RESET's own (open_page): PLAYERS opens on
        the Players home, never on that page, wherever an earlier RESET left the menu (it has no way back to home)."""
        async with self._lock:
            if self._page[0] == "confirm":
                self._page = self._page[1][3]       # a question left open is not asked again: the page it came from
            if self._page[0] in ("soft_reset", "soft_reset_confirm") or (self._page[0] == "tower"
                                                                        and self._tower.origin == "home"):
                self._page, self._notice = ("home", None), ""   # a page the reset key or TOWER opened
            return await self._refresh()

    async def reshow(self):
        """The current page again under a new revision: the answer to a press on a screen that a status refresh replaced
        meanwhile (nothing is chosen; the game always takes a newer screen, and the player presses again on what is
        really shown). Such a press used to close the window with "Reopen to check server status"."""
        async with self._lock:
            self._signature = None
            return await self._refresh()

    async def open_page(self, page, alive=None):
        """An OPEN that names its page (Update 32: the soft reset key opens the soft reset question; Battle Tower:
        Legends: START > PLAYER > TOWER opens the Tower, whose B goes back to the Players home; MS-61: an in-game SAVE in
        a world opens the host save, which closes the window at once and saves on the host). ``alive``: whether the
        game's window that asked still waits for this answer (the Tower's next floor is never issued after it closed)."""
        if page not in ("soft_reset", "tower", "host_save", "tower_next"):
            raise PlayerMenuError("unknown_page")
        async with self._lock:
            screen = await self._refresh()      # the binding, the player's open challenges and trades
            if self._binding is None:
                if page == "host_save":
                    return self._show("Save", "Saved on this PC only", [("Not in the world now", "", ())])
                return screen
            self._notice = ""
            if page == "tower":
                self._tower.open("home")
                self._page = ("tower", None)
                return await self._refresh()
            if page == "tower_next":
                # The Tower's "go on to floor N?" answered YES: the next floor starts at once (the game's window takes
                # its command); a refusal shows the Tower's home page with the reason.
                from .tower_menu import TowerMenuError
                self._page = ("tower", None)
                try:
                    outcome = await self._tower.next_floor(alive=alive)
                except TowerMenuError as error:
                    raise PlayerMenuError(error.code) from error
                if outcome is not None:
                    self.tower_reply = outcome
                    return self._show("Battle Tower", f"Floor {outcome[1].floor}: good luck!", [])
                return self._render()
            if page == "host_save":
                # MS-61: the launcher's own, as its Save now: the window closes first, then it saves on the host and
                # the game's banner says how that went (launcher_session._native_menu_reset_handoff).
                self._page = ("home", None)
                self.handoff = ("host_save", {})
                return self._show("Save", "Saving on the host", [])
            # MS-61: the key asks at once ("Reset the game?", NO first); a refusal shows why instead (_render).
            self._page = ("soft_reset_confirm", None)
            return self._render()

    async def _refresh(self):
        binding = self._session()
        if binding is None:
            self._binding = None
            self._page = ("home", None)
            self._players, self._team, self._battles = {}, None, None
            self._card, self._card_binding = None, None
            self._championship.reset()
            self._rival.reset()
            self._record_menu.reset()
            self._tower.reset()
            return self._show("Players", "Connection interrupted", [])
        if binding != self._binding:
            self._page = ("home", None)
            self._notice = ""
            self._card, self._card_binding = None, None
            self._championship.reset()
            self._rival.reset()
            self._record_menu.reset()
            self._tower.reset()
        self._binding = binding
        # Immutable value copies; the companion owns and validates the roster.
        self._players = {p["player_id"]: p["display_name"] for p in self.companion._players}
        # A player whose game has not reported a position yet is joining (still loading).
        self._activities = {p["player_id"]: "joining" if "presence" in p and p["presence"] is None
                            else (p.get("presence") or {}).get("activity") for p in self.companion._players}
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
            if kind == "team":
                self._team = value
            else:
                await self._ended_challenge(value, binding)
                self._battles = value
        # Update 32: battle lobbies, where the format follows the trainers who joined (battle_lobby.py).
        self._lobbies = []
        lobby_rpc = getattr(self.companion, "lobby_rpc", None)
        if self._battles is not None and callable(lobby_rpc):
            try:
                self._lobbies = (await lobby_rpc("status"))["result"]["lobbies"]
            except LobbyError as error:
                if error.code != "battle_disabled":
                    raise
            if self._session() != binding:
                raise PlayerMenuError("session_changed")
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
        if self._page[0] in ("frontier", "league", "hall", "shop", "team_pick", "extras"):
            frontier_rpc = getattr(self.companion, "frontier_rpc", None)
            self._frontier = None
            if callable(frontier_rpc) and getattr(self.companion.config, "world_enabled", False):
                try:
                    self._frontier = await frontier_rpc()
                except Exception:  # noqa: BLE001 - older hosts have no Frontier
                    self._frontier = None
                if self._session() != binding:
                    raise PlayerMenuError("session_changed")
        if self._page[0] == "habitat":
            habitat_rpc = getattr(self.companion, "habitat_rpc", None)
            self._habitat = None
            if callable(habitat_rpc) and getattr(self.companion.config, "world_enabled", False):
                try:
                    self._habitat = await habitat_rpc()
                except Exception:  # noqa: BLE001 - older hosts have no habitat view
                    self._habitat = None
                if self._session() != binding:
                    raise PlayerMenuError("session_changed")
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
        if self._page[0] == "rival":
            from .rival_menu import RivalMenuError
            try:
                await self._rival.refresh()
            except RivalMenuError as error:
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
        if self._page[0] == "tower":
            from .tower_menu import TowerMenuError
            try:
                await self._tower.refresh()
            except TowerMenuError as error:
                raise PlayerMenuError(error.code) from error
            if self._session() != binding:
                self._actions.clear()
                self._signature = None
                raise PlayerMenuError("session_changed")
        return self._render()

    def _show(self, title, status, actions, style=(0, 0)):
        """``style``: a Battle Tower page's (style, argument) for the native PC UI (menu_mailbox.TOWER_STYLES)."""
        if len(actions) > 6:
            raise PlayerMenuError("menu_capacity")
        title, status = _text(title, 23), _text(status, 31)
        normalized = tuple((_text(label, 25), op, tuple(args)) for label, op, args in actions)
        admission = next((i + 1 for i, (_, op, _) in enumerate(normalized)
            if op == "battle_enter" and battle_admission_enabled(self.companion)), 0)
        signature = (self._binding, self._page, title, status, normalized, admission, style)
        if signature != self._signature:
            revision = self._screen.revision + 1
            if revision > 0xFFFFFFFF:
                raise PlayerMenuError("menu_generation_exhausted")
            self._actions = {i + 1: (op, args) for i, (_, op, args) in enumerate(normalized) if op}
            # B closes the menu from the player list, and from the soft reset pages (the reset key opens them).
            back = 0 if self._page[0] in ("home", "soft_reset", "soft_reset_confirm") else 7
            if back:
                self._actions[back] = {"records": ("records_back", ()), "ffa": ("new_battle", ()),
                                       "new_battle": ("battles", ()), "lobby_pick": ("new_battle", ()),
                                       "lobby_2v2": ("lobby", ()), "tower": ("tower_back", ()),
                                       "confirm": ("ask_no", ())}.get(self._page[0], ("home", ()))   # a question's B is No
            self._screen = MenuScreen(revision, title, status,
                tuple(MenuRow(i + 1 if op else 0, label) for i, (label, op, _) in enumerate(normalized)), back, admission,
                *style)
            self._signature = signature
        return self._screen

    async def _start_lobby(self, lobby_id, generation, fmt, teammate=None):
        """The leader starts the lobby: their game sends the format's ordinary challenge to exactly the joined
        trainers (consent and the original game core as for any challenge), then the host links it to the lobby. If
        the lobby changed meanwhile, the challenge is withdrawn again."""
        actor = self.companion.config.player_id
        view = next((v for v in self._lobbies if v["lobby_id"] == lobby_id), None)
        if view is None or view["state"] != "open" or fmt not in self._lobby_formats(view):
            self._notice, self._page = "The lobby changed: try again", ("lobby", None)
            return
        others = [p for p in view["joined"] if p != actor]
        fields = {"1v1": lambda: dict(peer=others[0]), "1v1v1": lambda: dict(opponents=others),
                  "1v1v1v1": lambda: dict(opponents=others),
                  "2v2": lambda: dict(teammate=teammate, opponents=[p for p in others if p != teammate])}[fmt]()
        battle_id = str(uuid4())
        try:
            sent = (await self.companion.battle_challenge_rpc(LOBBY_INVITES[fmt], battle_id=battle_id, **fields))["result"]
        except BattleChallengeError as error:
            self._notice = INVITE_NOTICES.get(error.code, "The host refused: try again")
            self._page = ("lobby", None)
            return
        try:
            await self.companion.lobby_rpc("start", lobby_id=lobby_id, generation=generation, battle_id=battle_id)
        except LobbyError:
            try:
                await self.companion.battle_challenge_rpc("cancel", battle_id=battle_id, generation=sent["generation"])
            except BattleChallengeError:
                pass
            self._notice, self._page = "The lobby changed: try again", ("lobby", None)
            return
        self._page = ("battles", None)

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

    def _lobby_of(self, actor):
        """The battle lobby to show this player: an open one they are in or invited to (not declined or left),
        else one that just started or ended with them in it."""
        def open_for(view):
            return view["state"] == "open" and actor not in view["declined"] and actor not in view["left"]
        return (next((v for v in self._lobbies if open_for(v)), None)
                or next((v for v in self._lobbies if actor in v["joined"] or actor == v["creator"]), None))

    def _lobby_formats(self, view):
        """The formats this player's game can start (a 1v1v1 needs the game's 1v1v1, a 1v1v1v1 its free-for-all)."""
        config = self.companion.config
        ffa = getattr(config, "battle_ffa_enabled", True)
        able = {"1v1": True, "2v2": True, "1v1v1v1": ffa, "1v1v1": ffa and getattr(config, "battle_ffa3_enabled", True)}
        return [f for f in view["formats"] if able[f]]

    def _activity(self, player):
        """What a listed player is doing: "In battle", "In a menu"... ("Joining" before their first position)."""
        return ACTIVITY_LABELS.get(self._activities.get(player), "Connected")

    def _place(self, player):
        """Where a player is, from the host's world view (or "Location hidden" when they keep it private)."""
        nav = self._nav or {}
        return next((row["place"] for row in nav.get("players") or () if row.get("player_id") == player), None)

    # The colours the game gives other players' icons on the PokeNav map, by their place in the roster
    # (engine src/region_map.c sSlotLight). Your own icon is the game's own, in its usual colours.
    MARKER_COLOURS = ("Blue", "Yellow", "Purple", "Orange")

    def _marker(self, player):
        order = list(self._players)
        return self.MARKER_COLOURS[order.index(player)] if player in order and order.index(player) < 4 else None

    def _render(self):
        actor = self.companion.config.player_id
        page, target = self._page
        actions = []
        title, status = "Players", self._notice or f"Connected: {len(self._players)}/4"
        if page == "player" and target in self._players and target != actor:
            title = self._name(target)
            place = self._place(target)
            where = f"{self._activity(target)}: {place}" if place else self._activity(target)
            if len(where) > LABEL_CHARACTERS:
                where = f"{ACTIVITY_SHORT.get(self._activities.get(target), 'Online')}: {place}"
            actions.append((where, "", ()))
            friend = self._friends.get(target)
            if friend is not None:
                progress = "" if friend["next"] is None else f" {friend['points']}/{friend['next']}"
                status = friend["name"] + progress
                if friend["lucky_friends"]:
                    actions.append(("LUCKY FRIENDS: next trade", "", ()))
            trade_blocker = getattr(self.companion, "_native_menu_trade_blocker", None)
            trade_reason = trade_blocker() if callable(trade_blocker) else None
            if self._trades is not None and not self._trades:
                if trade_reason is None:
                    actions.append((TRADE_ROW, "trade_open", (target,)))
                else:
                    actions.append(("Trading: unavailable", "", ()))
            if self._team is not None and self._team["team"] is None:
                actions.append(("Invite to team", "team_invite", (target,)))
            if self._battles is not None and not self._battles:
                actions.append((MODE_ROWS[2], "battle_invite", (target,)))
            actions.append(("View Trainer Card", "card", (target,)))
            if self._notice or friend is None:
                status = self._notice or "Choose an interaction"
            if trade_reason is not None and self._trades is not None and not self._trades and not self._notice:
                status = refusal_text(trade_reason)
        elif page == "trade" and self._trades:
            trade = self._trades[0]
            title, status = "Trading", self._notice or "With " + self._name(next(p for p in trade["players"] if p != actor))
            params = (trade["transaction_id"], trade["generation"])
            trade_blocker = getattr(self.companion, "_native_menu_trade_blocker", None)
            trade_reason = trade_blocker() if callable(trade_blocker) else None
            if trade_reason is None:
                actions.append(("Choose your Pokemon", "trade_enter", params))
            else:
                status = refusal_text(trade_reason)
            actions.append(("Decline trade...", "ask", ("trade_cancel", *params)))
        elif page == "team" and self._team is not None:
            title = "Your team"
            own = self._team["team"]
            if own:
                peer = next(p for p in own["members"] if p != actor)
                actions.append((self._name(peer), "", ()))
                actions.append(("Leave team...", "ask", ("team_leave", own["team_id"], own["generation"])))
                other = next((t for t in self._team["teams"] if t["team_id"] != own["team_id"]), None)
                if other is not None and self._battles is not None and not self._battles:
                    actions.append((MODE_ROWS[3], "battle_multi", (peer, *other["members"])))
                status = self._notice or "Separate parties and items"
            elif self._team["invitations"]:
                invitation = self._team["invitations"][0]
                params = (invitation["invitation_id"], invitation["generation"])
                if invitation["recipient"] == actor:
                    status = "From " + self._name(invitation["sender"])
                    actions.extend((("Accept invitation", "team_accept", params),
                                    ("Decline invitation...", "ask", ("team_decline", *params))))
                else:
                    # A row that does nothing first: the A that sent the invitation rests on it (it used to rest on
                    # Cancel invitation, the page's only row).
                    status = "Waiting for " + self._name(invitation["recipient"])
                    actions.append((f"Invited {self._name(invitation['recipient'])[:17]}", "", ()))
                    actions.append(("Cancel invitation...", "ask", ("team_cancel", *params)))
            else:
                status = "Choose a player to invite"
        elif page == "battles":
            title = "Challenges"
            if self._battles:
                battle = self._battles[0]
                title = MODE_TITLES.get(battle["mode"]) or (self._coop_title(battle.get("gym")) if battle["mode"] == 4
                                                            else "Challenge")
                waiting = [p for p in battle["players"] if p not in battle["consent"]]
                if not waiting:
                    pending_status = "Opponent accepted" if battle["mode"] == 2 else "All players ready"
                elif actor in waiting:
                    pending_status = f"{self._name(battle['sender'])[:12]} challenges you"
                elif len(battle["players"]) == 2:
                    pending_status = "Waiting for opponent"
                else:
                    pending_status = "Waiting for remaining players"
                status = self._notice or pending_status
                parties = {cp["player_id"]: cp["party_count"] for cp in battle["checkpoints"]}
                if battle["mode"] in (2, 4):
                    for cp in battle["checkpoints"]:
                        actions.append((f"{self._name(cp['player_id'])[:18]} ({cp['party_count']})", "", ()))
                elif battle["mode"] in (5, 6):
                    # Independent trainers: rows of two keep room for the consent rows (no wager, no teams).
                    for pair in (battle["players"][:2], battle["players"][2:]):
                        actions.append((" / ".join(f"{self._name(p)[:8]}({parties.get(p, 0)})" for p in pair), "", ()))
                else:
                    # Two team rows keep room for the consent and wager rows.
                    for team in (battle["players"][::2], battle["players"][1::2]):
                        actions.append((" & ".join(f"{self._name(p)[:8]}({parties.get(p, 0)})" for p in team), "", ()))
                params = (battle["battle_id"], battle["generation"])
                wager = self._wager["wager"] if self._wager is not None else None
                wager_ready = wager is None or set(wager["accepted"]) == set(wager["players"])
                if battle["state"] in _OPEN_BATTLE_STATES and self._wager is not None and battle["mode"] not in (5, 6):
                    if wager is None:
                        label = "Wager: none (set one)"
                    else:
                        label = f"Wager {_money(wager['amount'])} {len(wager['accepted'])}/{len(wager['players'])} OK"
                    actions.append((label, "wager", (battle["battle_id"],)))
                if battle["state"] in _OPEN_BATTLE_STATES:
                    # One row is Accept, then Enter battle, and a row that does nothing until then; Cancel is below it
                    # and asks first. The game keeps its cursor row when the next screen comes, so the A that accepted
                    # rests on Enter battle (the owner's report of 2026-10-24: "when clicked again it kicks us out back
                    # to start" - Cancel challenge had moved up under the cursor).
                    primary = ("Enter battle: not yet", "", ())
                    if actor not in battle["consent"] and actor != battle["sender"]:
                        primary = ("Accept challenge", "battle_accept", (*params, battle["fingerprint"]))
                    elif battle["state"] == "accepted" and not wager_ready:
                        status = "Everyone must accept the wager"
                    elif battle["state"] == "accepted":
                        status = "Waiting for battle coordinator"
                        if (callable(getattr(self.companion, "_native_menu_handoff", None))
                                and (getattr(self.companion.config, "battle_resume_abi_version", 0) != 1
                                     or battle_admission_enabled(self.companion))):
                            # Offer Enter only when this game can be admitted: an Enter the launcher must refuse
                            # would latch the game's window for nothing (the owner's report of 2026-10-20).
                            blocker = getattr(self.companion, "_native_menu_battle_blocker", None)
                            reason = blocker(battle) if callable(blocker) else None
                            if reason is None:
                                status = self._notice or pending_status
                                primary = ("Enter battle", "battle_enter", (*params, battle["fingerprint"]))
                            else:
                                status = refusal_text(reason)
                    actions.append(primary)
                    actions.append(("Cancel challenge...", "ask", ("battle_cancel", *params)))
                else:
                    status = {"aborting": "Cancelling safely", "recovery_required": "Battle needs recovery",
                              "running": "Battle in progress", "starting": "Starting battle"}.get(battle["state"], battle["state"])
                    if battle["state"] in ("aborting", "recovery_required") and self._notice:
                        # This player's own refused Enter or cancel says more than the state of a challenge another
                        # trainer's game is still leaving (KNOWN_ISSUES MS-60, L stale-save-4: the refused trainer
                        # read "Battle needs recovery" while the entered one cancelled its entry).
                        status = self._notice
                if battle["mode"] == 2 and len(actions) < 6:
                    actions.append(("Championship", "championship", ()))
            else:
                status = self._notice or ("New battles disabled on host" if self._battles is None else "No pending challenges")
                if self._battles is not None and actor in self._players and len(self._players) >= 2:
                    # Update 32: a battle lobby (the format follows who joins) or a free-for-all of everyone.
                    actions.append(("New battle", "new_battle", ()))
                actions.append(("Recent battle results", "results", (0,)))
                actions.append(("Full record archives", "records", ()))
                actions.append(("Your Trainer Card", "card", (actor,)))
                actions.append(("Championship", "championship", ()))
                actions.append(("Rival checkpoints", "rival", ()))
        elif page == "new_battle":
            title, status = "New battle", self._notice or "Invite: the format follows who joins"
            others = [p for p in self._players if p != actor]
            ffa = getattr(self.companion.config, "battle_ffa_enabled", True)
            ffa3 = ffa and getattr(self.companion.config, "battle_ffa3_enabled", True)
            if self._battles is None:
                status = self._notice or "New battles disabled on host"
            elif self._battles:
                status = self._notice or "Finish the open challenge"
            elif self._lobby_of(actor) is not None and self._lobby_of(actor)["state"] == "open":
                status = self._notice or "You are in a battle lobby"
                actions.append(("Battle lobby", "lobby", ()))
            elif not others or actor not in self._players:
                status = self._notice or "Nobody else is connected"
            else:
                actions.append(("Battle lobby", "lobby_pick", ()))
                if len(self._players) == 4 and ffa3:
                    actions.append(("Free-for-All", "ffa", ()))      # everyone, or three of the four (Update 32)
                elif len(self._players) == 4 and ffa:
                    actions.append((MODE_ROWS[5], "battle_ffa", tuple(others)))
                elif len(self._players) == 3 and ffa3:
                    actions.append((MODE_ROWS[6], "battle_ffa3", tuple(others)))
        elif page == "lobby_pick":
            title = "Battle lobby"
            others = [p for p in self._players if p != actor]
            self._lobby_pick = [p for p in self._lobby_pick if p in others]
            chosen = len(self._lobby_pick)
            status = self._notice or (f"Invite {chosen}: A changes" if chosen else "Who do you invite? A changes")
            for player in others:
                actions.append((f"{self._name(player)[:19]}: {'Yes' if player in self._lobby_pick else 'No'}",
                                "lobby_toggle", (player,)))
            if self._lobby_pick:
                actions.append(("Send invitations", "lobby_create", tuple(self._lobby_pick)))
        elif page in ("lobby", "lobby_2v2"):
            title, view = "Battle lobby", self._lobby_of(actor)
            if view is None:
                status = self._notice or "No battle lobby"
            elif view["state"] == "started":
                status = self._notice or f"{view['format']} challenge sent"
                actions.append(("Pending challenge" if self._battles else "Challenges", "battles", ()))
            elif view["state"] == "ended":
                status = self._notice or LOBBY_ENDINGS.get(view["reason"], "The lobby has ended")
            elif page == "lobby_2v2":
                # The leader's 2v2 partner: the other two make the opposing team.
                status = self._notice or "Choose your 2v2 partner"
                for player in view["joined"]:
                    if player != actor:
                        actions.append((f"With {self._name(player)[:20]}", "lobby_start",
                                        (view["lobby_id"], view["generation"], "2v2", player)))
            else:
                ids = (view["lobby_id"], view["generation"])
                joined = view["joined"]
                formats, playable = view["formats"], self._lobby_formats(view)
                waiting = [p for p in view["invited"] if p not in joined and p not in view["declined"]
                           and p not in view["left"]]
                if formats:
                    status = self._notice or f"{' or '.join(formats)}: {len(joined)} joined"
                else:
                    status = self._notice or f"Waiting for {len(waiting)} to answer"
                for player in (view["creator"], *view["invited"]):
                    if player == actor:
                        continue
                    state = ("leader" if player == view["creator"] else "joined" if player in joined
                             else "declined" if player in view["declined"] else "left" if player in view["left"]
                             else "invited")
                    actions.append((f"{self._name(player)[:15]}: {state}", "", ()))
                if actor == view["creator"]:
                    for fmt in playable:
                        actions.append((f"Start {fmt}", "lobby_2v2" if fmt == "2v2" else "lobby_start",
                                        () if fmt == "2v2" else (*ids, fmt)))
                    if formats and not playable:
                        status = self._notice or f"Your game cannot play {formats[0]}"
                    if not playable:
                        # Where Send invitations was when everyone was invited: the A that sent them rests on a row
                        # that does nothing (it used to rest on Cancel lobby).
                        actions.append(("Waiting for trainers", "", ()))
                    actions.append(("Cancel lobby...", "ask", ("lobby_cancel", *ids)))
                elif actor in joined:
                    # Where Join was: the A that joined rests on a row that does nothing (the cursor keeps its row).
                    actions.append(("Joined: wait for the leader", "", ()))
                    actions.append(("Leave lobby...", "ask", ("lobby_leave", *ids)))
                else:
                    actions.append(("Join lobby", "lobby_join", ids))
                    actions.append(("Decline...", "ask", ("lobby_decline", *ids)))
        elif page == "ffa":
            title, status = "Free-for-All", self._notice or "Who battles?"
            others = [p for p in self._players if p != actor]
            if self._battles is None:
                status = self._notice or "New battles disabled on host"
            elif self._battles:
                status = self._notice or "Finish the open challenge"
            elif len(others) != 3 or actor not in self._players:
                status = self._notice or "Needs four players connected"
            else:
                actions.append(("Everyone: 4 Players", "battle_ffa", tuple(others)))
                for i, a in enumerate(others):
                    for b in others[i + 1:]:
                        actions.append((f"With {self._name(a)[:8]} & {self._name(b)[:8]}", "battle_ffa3", (a, b)))
        elif page == "confirm":
            # A choice that ends something for others asks first (QUESTIONS): No first, B is No, and Yes never where the
            # asking press left the cursor (a second row's press finds a row that does nothing there instead).
            question, cursor, params, _ = target
            title, consequence, yes, yes_op, fixed = QUESTIONS[question]
            status = self._notice or consequence
            actions.append(("No, keep it", "ask_no", ()))
            if cursor == 1:
                actions.append(("B or No keeps it", "", ()))
            actions.append((yes, yes_op, params if fixed is None else fixed))
        elif page in ("soft_reset", "soft_reset_confirm"):
            # The soft reset key (Update 32, MS-61): the game starts again from its last save on the host, in this
            # session; the world and the other players carry on. Nothing open may be cut short by it.
            blocker = getattr(self.companion, "_native_menu_reset_blocker", None)
            reason = blocker() if callable(blocker) else "game_active"
            if reason is None and self._trades:
                reason = "trade_pending"
            if reason is None and self._battles:
                reason = "challenge_pending"
            last_save = getattr(self.companion, "_native_menu_last_save", None)
            age = save_age(last_save() if callable(last_save) else None)
            if page == "soft_reset_confirm" and reason is None:
                # NO first; B is NO too. The last save's age says how far back the reset goes.
                title, status = "Reset the game?", self._notice or "Unsaved progress will be lost"
                actions.append(("No, keep playing", "soft_reset_no", ()))
                actions.append(("Yes, reset now", "soft_reset_now", ()))
                actions.append((age, "", ()))
            else:
                self._page = ("soft_reset", None)
                title = "Soft reset"
                status = self._notice or (soft_reset_refusal(reason) if reason else "Back to your last save")
                actions.append(("Unsaved progress is lost", "", ()))
                actions.append((age, "", ()))
                if reason is None:
                    actions.append(("Reset the game", "soft_reset_confirm", ()))
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
                        actions.append(("Decline wager...", "ask", ("wager_decline", target)))
                    elif actor == wager["sender"]:
                        # Where Propose this wager was: the A that proposed it rests on a row that does nothing.
                        actions.append(("Waiting for the others", "", ()))
                        actions.append(("Remove wager...", "ask", ("wager_remove", target)))
                    else:
                        actions.append(("You accepted this wager", "", ()))
            actions.append(("Back to challenge", "battles", ()))
        elif page in ("world", "world_players", "world_player", "world_outbreak", "world_event", "base", "frontier", "league", "hall", "shop", "team_pick", "extras", "coop", "habitat"):
            return self._show(*self._render_world(page, target))
        elif page == "championship":
            return self._show(*self._championship.render())
        elif page == "rival":
            from .rival_menu import RivalMenuError
            try:
                return self._show(*self._rival.render())
            except RivalMenuError as error:
                raise PlayerMenuError(error.code) from error
        elif page == "records":
            return self._show(*self._record_menu.render())
        elif page == "tower":
            from .tower_menu import TowerMenuError
            try:
                title, status, actions, style = self._tower.render()
            except TowerMenuError as error:
                raise PlayerMenuError(error.code) from error
            return self._show(title, status, actions, style)
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
                    # Off the field, what the player is doing ("In battle"); on it, the friendship level. Either
                    # follows the name in the row's 25 characters: a name is cut only where both cannot fit, so
                    # names that differ after their 13th character stay apart.
                    activity = self._activities.get(player)
                    note = (self._activity(player) if activity not in (None, "overworld", "joining")
                            else friend["name"].split()[0] if friend is not None else None)
                    if note is not None:
                        label = f"{label[:LABEL_CHARACTERS - 3 - len(note)]} - {note}"
                    actions.append((label, "player", (player,)))
            if self._team is not None:
                actions.append(("Team invitation" if self._team["invitations"] else "Your team", "team", ()))
            if self._battles is not None:
                if self._battles:
                    actions.append(("Pending challenge", "battles", ()))
                elif self._lobby_of(actor) is not None:
                    actions.append(("Battle lobby", "lobby", ()))
                else:
                    actions.append(("Challenges", "battles", ()))
            else:
                # Completed history remains authenticated and readable when
                # new native battle admission is disabled (normal launcher).
                actions.append(("Battles and records", "battles", ()))
            last = ("Pending trade", "trade", ()) if self._trades else ("Your Trainer Card", "card", (actor,))
            world = ("World and my base", "world", ())
            if self._rival.local_checkpoint() is not None and len(actions) < 6:
                # Standing at a rival checkpoint: its page is the most relevant one (Update 31).
                actions.append(("Rival checkpoint", "rival", ()))
            room = 6 - len(actions)
            if room >= 2:
                actions.extend((world, last))
            elif room == 1:
                actions.append(last if self._trades else world)  # a full lobby: the Trainer Card is under Challenges
        return self._show(title, status, actions)

    @staticmethod
    def _coop_title(code):
        """A co-op battle's title: a Gym, a ladder battle (Battle Frontier) against two named trainers, or a Battle Tower
        floor's Duo battle."""
        from .coop_code import decode, decode_tower
        from .frontier import TRAINER_NAMES
        tower = decode_tower(code)
        if tower is not None:
            return f"Battle Tower floor {tower.floor}"
        ladder = decode(code)
        if ladder is None:
            return "Team Gym vs " + GYM_LEADERS.get(code, "Leader")
        names = [TRAINER_NAMES.get(t, "Trainer") for t in (ladder.trainer_a, ladder.trainer_b)]
        return f"Co-op: {names[0]} & {names[1]}"

    def _render_shop(self, view, page_no):
        """The Battle Points shop (frontier_rewards.SHOP): points are taken from the save first, then the item is given."""
        from .tower_menu import CLOSE_TO_FINISH
        bp = view.get("bp") or {}
        actions, shop = [], bp.get("shop") or []
        purchase = bp.get("purchase")
        balance = bp.get("balance")
        status = self._notice or ("Your BP: " + ("?" if balance is None else str(balance)))
        if purchase is not None and purchase["state"] in ("debit", "granting", "refunding"):
            status = self._notice or CLOSE_TO_FINISH
        per_page = 4
        pages = max(1, (len(shop) + per_page - 1) // per_page)
        page_no = page_no if type(page_no) is int and 0 <= page_no < pages else 0
        for entry in shop[page_no * per_page:(page_no + 1) * per_page]:
            actions.append((f"{entry['name'][:15]} {entry['price']}BP", "shop_buy", (entry["slot"],)))
        if pages > 1:
            actions.append((f"More items ({page_no + 1}/{pages})", "shop", ((page_no + 1) % pages,)))
        if purchase is not None and not self._notice and purchase["state"] in ("done", "refused", "refunded"):
            status = {"done": "Bought " + purchase["name"][:18], "refused": "Not enough BP in the game",
                      "refunded": "Bag full: BP returned"}[purchase["state"]]
        actions.append(("Back", "extras", ()))
        return "BP Shop", status, actions

    def _render_extras(self, view):
        """The Frontier's team selection and Battle Points shop (one page keeps the main page within six rows)."""
        team, bp, record = view.get("team"), view.get("bp") or {}, view["record"]
        actions = []
        if team is not None:
            names = ", ".join(slot["name"] for slot in team["slots"] if slot["selected"])
            actions.append(("Team: " + (names or "none")[:19], "team_pick", (0,)))
        if bp.get("shop"):
            balance = bp.get("balance")
            actions.append((f"BP shop ({'?' if balance is None else balance} BP)", "shop", (0,)))
        actions.append((f"Best {record['best_streak']}  runs {record['runs']}  BP +{bp.get('earned', 0)}", "", ()))
        actions.append(("Back to the Frontier", "frontier", ()))
        return "Team and BP shop", self._notice or "Choose who fights, spend BP", actions

    def _render_team(self, view, page_no):
        """Choose which saved Pokemon fight: tap one to bring it (a full team gives up its first member)."""
        team = view.get("team")
        if team is None:
            return "Your team", self._notice or "No saved party yet", [("Back", "extras", ())]
        slots, limit = team["slots"], team["limit"]
        per_page = 4
        pages = max(1, (len(slots) + per_page - 1) // per_page)
        page_no = page_no if type(page_no) is int and 0 <= page_no < pages else 0
        actions = []
        for slot in slots[page_no * per_page:(page_no + 1) * per_page]:
            if slot["egg"]:
                actions.append(("Egg (cannot fight)", "", ()))
                continue
            mark = "*" if slot["selected"] else "-"
            actions.append((f"{mark} {slot['name'][:11]} L{slot['level']}" + ("" if slot["able"] else " (fnt)"),
                            "team_toggle", (slot["slot"], page_no)))
        if pages > 1:
            actions.append((f"More ({page_no + 1}/{pages})", "team_pick", ((page_no + 1) % pages,)))
        actions.append(("Back", "extras", ()))
        count = sum(1 for slot in slots if slot["selected"])
        status = self._notice or (f"Bring up to {limit}: {count} chosen" + (" (auto)" if team["auto"] else ""))
        return "Your team", status, actions

    def _render_ladder(self, page, target=None):
        """The cooperative Battle Frontier (frontier.py) and the Pokemon League: team rounds against pairs of trainers."""
        view, actor, actions = self._frontier, self.companion.config.player_id, []
        if page == "shop" and view is not None:
            return self._render_shop(view, target)
        if page == "team_pick" and view is not None:
            return self._render_team(view, target)
        if page == "extras" and view is not None:
            return self._render_extras(view)
        league = page in ("league", "hall")
        title = "Pokemon League" if league else "Battle Frontier"
        if view is None:
            return title, self._notice or "The host has no " + ("League" if league else "Frontier"), [("Back", "coop", ())]
        mode = "league" if league else "frontier"
        run, record, hall = view["run"], view["record"], view.get("league", {})
        if page == "hall":
            title = "Hall of Fame"
            entries = hall.get("hall") or []
            for entry in entries:
                actions.append((f"#{entry['entry']} " + " & ".join(entry["names"]), "", ()))
            if not entries:
                actions.append(("Nobody has cleared it yet", "", ()))
            actions.append(("Back to the League", "league", ()))
            return title, self._notice or "Teams that cleared it", actions
        if run is not None and run["state"] != "ended" and run["mode"] != mode:
            other = "League" if run["mode"] == "league" else "Frontier"
            return title, self._notice or f"A {other} run is active", [(f"Open the {other}", run["mode"], ()),
                                                                          ("Back", "coop", ())]
        if run is not None and run["mode"] != mode:
            run = None
        if run is None or run["state"] == "ended":
            if league:
                status = self._notice or "All 8 badges, 1-%d Pokemon" % view["party_limit"]
            else:
                status = self._notice or f"Bring up to {view['party_limit']} Pokemon and save"
            if run is not None:
                reason = {"defeated": "Beaten", "draw": "Draw", "retired": "Retired", "declined": "Declined",
                          "cleared": "CLEARED"}.get(run["ended_reason"], "Over")
                actions.append((f"Last: {reason}, round {run['streak']}" if league else
                                f"Last: {reason}, streak {run['streak']}", "", ()))
            actions.append(("Challenge the League" if league else "Start a Frontier run", "ladder_propose", (mode,)))
        else:
            others = [n for p, n in zip(run["players"], run["names"]) if p != actor]
            partner = others[0] if others else "teammate"
            if run["state"] == "forming":
                if actor in run["consent"]:
                    # A row that does nothing first: the A that started the run rests on it (it used to rest on Cancel).
                    status = self._notice or "Waiting for " + partner
                    actions.append((f"Invited {partner[:17]}", "", ()))
                    actions.append(("Cancel the invitation...", "ask", ("ladder_cancel",)))
                else:
                    status = self._notice or partner + " invites you"
                    actions.extend((("Join the " + ("League run" if league else "Frontier run"), "ladder_accept", ()),
                                    ("Decline...", "ask", ("ladder_decline",))))
            else:
                status = self._notice or (f"Round {run['round']} of {hall.get('rounds', 3)}" if league
                                          else f"Round {run['round']}  streak {run['streak']}")
                nxt = run["next"]
                if nxt is not None:
                    actions.append((nxt["label"] if league else ("Brain: " if nxt["brain"] else "vs ") + nxt["label"], "", ()))
                    actions.append((f"Prize ${nxt['prize']:,}, own levels" if league
                                    else (f"Lv{nxt['level']} ${nxt['prize']:,} +{nxt['bp']}BP" if "bp" in nxt
                                          else f"Lv{nxt['level']}  prize ${nxt['prize']:,}"), "", ()))
                if run["battle_id"] is not None:
                    actions.append(("Battle: open Challenges", "battles", ()))
                else:
                    actions.append((f"Start round {run['round']}", "ladder_battle", ()))
                    actions.append(("Retire" + ("..." if league else " (keep streak)..."), "ask", ("ladder_retire",)))
        if league:
            actions.append((f"Cleared {hall.get('clears', 0)}x", "hall", ()))
        else:
            bp_view = view.get("bp")
            if view.get("team") is not None or (bp_view is not None and bp_view.get("shop")):
                actions.append((f"Team, BP shop  best {record['best_streak']}"[:25], "extras", ()))
            else:
                actions.append((f"Best {record['best_streak']}  runs {record['runs']}", "", ()))
        actions.append(("Back", "coop", ()))
        return title, status, actions

    def _render_world(self, page, target):
        """The PokeNav-style World pages (expansion Phase 7) and the player's own
        secret base sharing (Phase 6). Everything shown is the host's live view."""
        nav, actor = self._nav, self.companion.config.player_id
        actions = []
        if nav is None:
            return "World", "The host has no world view", [("Back", "home", ())]
        if page == "world":
            title = "PokeNav: World"
            status = self._notice or (f"{nav['time']} {nav['tod']}  online {len(self._players)}/4" if nav.get("time")
                                      else "Live view from the host")
            actions.append(("Players and weather", "world_players", ()))
            outbreak, event = nav["outbreak"], nav["event"]
            actions.append((("Outbreak: " + outbreak["name"]) if outbreak else "Outbreak: none",
                            "world_outbreak" if outbreak else "", ()))
            actions.append((("Event: " + event["name"]) if event else "World Event: none",
                            "world_event" if event else "", ()))
            actions.append(("This area's wild Pokemon", "habitat", ()))
            actions.append(("My Secret Base", "base", ()))
            actions.append(("Frontier and League", "coop", ()))
        elif page == "world_players":
            title, status = "Players and weather", "Also on the PokeNav map"
            for player in nav["players"][:4]:
                actions.append((f"{self._name(player['player_id'])[:9]} - {player['place']}", "world_player",
                                (player["player_id"],)))
            # PokeNav privacy (Update 24): the player's own choice, kept in their profile; on by default.
            sharing = getattr(self.companion, "share_location", True)
            actions.append(("Share my location: " + ("ON" if sharing else "OFF"), "privacy_toggle", ()))
            if not sharing:
                status = self._notice or "Others see Location hidden"
        elif page == "world_player":
            player = next((p for p in nav["players"] if p["player_id"] == target), None)
            title = self._name(target)
            status = "Not online" if player is None else "Position and weather"
            if player is not None:
                actions.extend((line, "", ()) for line in wrap(player["place"], 25)[:2])
                actions.append(("Weather: " + (player["weather"] or "unknown"), "", ()))
                colour = self._marker(target)
                if target == actor:
                    actions.append(("Map icon: your own", "", ()))
                elif colour is not None:
                    actions.append((f"Map icon: {colour}", "", ()))
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
                if page == "world_outbreak" or not entry.get("waiting"):   # a dormant event is not on the map
                    actions.append(("Marked on the PokeNav map", "", ()))
            actions.append(("Back to World", "world", ()))
        elif page == "habitat":
            title = "This area"
            view = self._habitat
            if view is None:
                status = self._notice or "Host has no area data"
            elif not view["known"]:
                status = self._notice or "No wild Pokemon data"
                actions.extend((line, "", ()) for line in wrap(view["place"], 25)[:2])
            else:
                low, high = view["levels"]
                status = self._notice or f"{view['place'][:20]} " + (f"Lv{low}" if low == high else f"Lv{low}-{high}")
                for index, name in enumerate(view["common"][:3]):
                    actions.append((("Common: " if index == 0 else "Then: ") + name[:15], "", ()))
                if not view["common"]:
                    actions.append(("No common species", "", ()))
                if view["favors"] and len(actions) < 4:
                    actions.append(("Favors: " + ", ".join(view["favors"][:2]), "", ()))
                actions.append(("Now: " + view["time"] + (", " + view["weather"] if view["weather"] else ""), "", ()))
            actions.append(("Back to World", "world", ()))
        elif page == "coop":
            title, status = "Frontier and League", self._notice or "Fight together as a team"
            actions = [("Battle Frontier", "frontier", ()), ("Pokemon League", "league", ())]
            if getattr(self.companion.config, "tower_abi_version", 0) == 1:
                actions.append(("Battle Tower: Legends", "tower", ()))
            if nav.get("rule"):
                actions.append(("Entry rule: " + nav["rule"], "", ()))
            actions.append(("Back to World", "world", ()))
        elif page in ("frontier", "league", "hall", "shop", "team_pick", "extras"):
            title, status, actions = self._render_ladder(page, target)
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

    def _answered(self, op, args):
        """The page the open question came from when this choice is that question's Yes, else None."""
        if self._page[0] != "confirm":
            return None
        question, _, params, previous = self._page[1]
        _, _, _, yes_op, fixed = QUESTIONS[question]
        return previous if (op, tuple(args)) == (yes_op, tuple(params if fixed is None else fixed)) else None

    async def choose(self, revision, action, *, pressed=None):
        """``pressed``: when the game's press reached the launcher (loop time; now when not given). A question's grace
        counts from when the question was sent to the game to that moment, not to when the choice is handled here (a
        status refresh or the host's answers can come between)."""
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
            loop = asyncio.get_running_loop()
            if op == "ask":
                # A choice that ends something for others: its question first (QUESTIONS). The asking row's index is
                # where the game's cursor stays, so the question keeps its Yes off that row.
                if not args or args[0] not in QUESTIONS:
                    raise PlayerMenuError("unknown_question")
                self._page = ("confirm", (args[0], action - 1, tuple(args[1:]), self._page))
                screen = await self._refresh()
                self._ask_shown = loop.time()          # the question goes to the game now
                return screen
            if op == "ask_no":
                # No, or B: back to the page that asked, nothing changed.
                self._page = self._page[1][3] if self._page[0] == "confirm" else ("home", None)
                return await self._refresh()
            if op in _ASKED_OPS or (op == "tower_duo" and tuple(args) in _ASKED_TOWER):
                previous = self._answered(op, args)
                if previous is None:
                    return await self._refresh()      # never sent without its question
                if (pressed if pressed is not None else loop.time()) - getattr(self, "_ask_shown", 0.0) < ASK_GRACE_SECONDS:
                    # The question stays: this Yes came with the press that asked (a double click, a key held). It is
                    # shown again, and its grace starts again from then.
                    screen = await self._refresh()
                    self._ask_shown = loop.time()
                    return screen
                self._page = previous           # where the answer leads, unless the choice below says otherwise
            if op == "championship":
                self._championship.open()
                self._page = ("championship", None)
            elif op == "rival":
                self._rival.open()
                self._page = ("rival", None)
            elif op.startswith("rival_"):
                from .rival_menu import RivalMenuError
                try:
                    to_battle = await self._rival.choose(op, args)
                except RivalMenuError as error:
                    raise PlayerMenuError(error.code) from error
                if to_battle:
                    self._page = ("battles", None)
            elif op == "records":
                self._record_menu.open(*args)
                self._page = ("records", None)
            elif op == "tower":
                self._tower.open("coop")
                self._page = ("tower", None)
            elif op.startswith("tower_"):
                from .tower_menu import TowerMenuError
                try:
                    outcome = await self._tower.choose(op, args)
                except TowerMenuError as error:
                    raise PlayerMenuError(error.code) from error
                if isinstance(outcome, tuple):
                    # The game's window takes this answer (menu flags 4: start the solo battle; 5: Hyper Training).
                    self.tower_reply = outcome
                    if outcome[0] == "command":
                        return self._show("Battle Tower", f"Floor {outcome[1].floor}: good luck!", [])
                    return self._show("Hyper Training", "Opening Hyper Training", [])
                if outcome == "leave":
                    self._page = (self._tower.origin, None)
                elif outcome in ("battles", "players"):
                    self._page = ("battles" if outcome == "battles" else "home", None)
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
            elif op == "team_toggle":
                from .protocol import ProtocolError
                try:
                    team = (self._frontier or {}).get("team") or {"slots": [], "limit": 0}
                    chosen = [slot["slot"] for slot in team["slots"] if slot["selected"]]
                    wanted = args[0]
                    if wanted in chosen:
                        if len(chosen) == 1:
                            raise ProtocolError("invalid_team", "Bring at least one Pokemon")
                        chosen.remove(wanted)
                    else:
                        if len(chosen) >= team["limit"] > 0:
                            chosen.pop(0)
                        chosen.append(wanted)
                    self._frontier = await self.companion.frontier_rpc("bring", mask=sum(1 << slot for slot in chosen))
                    self._notice = None
                except ProtocolError as error:
                    self._notice = error.message[:31]
                self._page = ("team_pick", args[1])
            elif op == "shop_buy":
                from .protocol import ProtocolError
                from .tower_menu import CLOSE_TO_FINISH
                try:
                    self._frontier = await self.companion.frontier_rpc("shop_buy", slot=args[0])
                    self._notice = CLOSE_TO_FINISH
                except ProtocolError as error:
                    self._notice = error.message[:31]
                self._page = ("shop", 0)
            elif op in ("ladder_propose", "ladder_accept", "ladder_cancel", "ladder_retire", "ladder_battle"):
                from .protocol import ProtocolError
                try:
                    if op == "ladder_propose":
                        self._frontier = await self.companion.frontier_rpc("propose", args[0])
                    else:
                        self._frontier = await self.companion.frontier_rpc(op.removeprefix("ladder_"))
                    self._page = ("battles", None) if op == "ladder_battle" else self._page
                except ProtocolError as error:
                    self._notice = error.message[:31]
            elif op == "base_cycle":
                choices = ("everyone", "team", "nobody")
                try:
                    self._base = await self.companion.secret_base_rpc(choices[(choices.index(args[0]) + 1) % 3])
                except Exception:  # noqa: BLE001 - the host decides; show that it did not change
                    self._notice = "Could not change it"
                self._page = ("base", None)
            elif op in ("home", "world", "world_players", "world_player", "world_outbreak", "world_event", "base", "frontier",
                        "league", "hall", "shop", "team_pick", "extras", "coop", "habitat", "team", "battles", "ffa", "new_battle", "lobby", "lobby_2v2", "lobby_pick", "player", "results", "result", "result_filters", "trade", "card", "card_battles", "card_championships", "card_shared", "card_progress", "hunts", "hunt", "hunt_filters", "hunt_totals"):
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
            elif op in ("soft_reset", "soft_reset_confirm"):
                self._page = (op, None)
            elif op == "soft_reset_no":
                # MS-61: NO closes the window; the game goes on as it was
                self._page = ("home", None)
                self.handoff = ("close", {})
                return self._show("Soft reset", "Kept playing", [])
            elif op in ("soft_reset_now", "host_save"):
                # The launcher's own (Update 32): the menu closes, then the launcher restarts the game from the host
                # save, or saves on the host; it refuses (and says why) if that is no longer possible.
                self._page = ("soft_reset", None)
                self.handoff = ("soft_reset" if op == "soft_reset_now" else "host_save", {})
                return self._show("Soft reset", "Resetting the game" if op == "soft_reset_now"
                                  else "Saving on the host", [])
            elif op == "trade_open":
                try:
                    trade = (await self.companion.trade_rpc("open", peer=args[0], transaction_id=str(uuid4())))["trade"]
                except TradeError as error:
                    # The host's answer, shown where the choice was made (the menu used to vanish on it).
                    self._notice = {"trade_busy": "A trade is already open",
                                    "player_offline": "That player is offline",
                                    "battle_busy": "Finish the battle first",
                                    "trade_recovery_required": "Finish the earlier trade",
                                    **NO_POKEMON_NOTICES}.get(error.code, "The host refused: try again")
                    return await self._refresh()
                if trade["state"] != "offering" or self._session() != self._binding:
                    raise PlayerMenuError("trade_changed")
                self.handoff = ("trade", deepcopy(trade))
                return self._show("Trade Pokemon", "Preparing your party", [])
            elif op == "trade_enter":
                trade = next((t for t in self._trades or () if (t["transaction_id"], t["generation"]) == args), None)
                if trade is None:
                    # The friend ended it (or the host did) as this was chosen: said where the choice was made, the
                    # window stays open (it used to close with "Reopen to check server status").
                    self._notice, self._page = "That trade has ended", ("home", None)
                    return await self._refresh()
                self.handoff = ("trade", deepcopy(trade))
                return self._show("Trade Pokemon", "Preparing your party", [])
            elif op == "trade_cancel":
                try:
                    await self.companion.trade_rpc("cancel", transaction_id=args[0], generation=args[1])
                    self._notice = "Trade declined"
                except TradeError:
                    self._notice = "The host refused: try again"
                self._page = ("home", None)
            elif op == "team_invite":
                await self.companion.team_rpc("invite", peer=args[0], invitation_id=str(uuid4()))
                self._page = ("team", None)
            elif op == "team_leave":
                await self.companion.team_rpc("leave", team_id=args[0], generation=args[1])
            elif op in ("team_accept", "team_decline", "team_cancel"):
                await self.companion.team_rpc(op.removeprefix("team_"), invitation_id=args[0], generation=args[1])
            elif op == "lobby_toggle":
                chosen = args[0]
                self._lobby_pick = ([p for p in self._lobby_pick if p != chosen] if chosen in self._lobby_pick
                                    else self._lobby_pick + [chosen])[:3]
                self._page = ("lobby_pick", None)
            elif op == "lobby_create":
                try:
                    await self.companion.lobby_rpc("create", lobby_id=str(uuid4()), invitees=list(args))
                    self._lobby_pick = []
                    self._page = ("lobby", None)
                except LobbyError as error:
                    self._notice = LOBBY_NOTICES.get(error.code, "The host refused: try again")
                    self._page = ("lobby_pick", None)
            elif op in ("lobby_join", "lobby_decline", "lobby_leave"):
                try:
                    await self.companion.lobby_rpc(op.removeprefix("lobby_"), lobby_id=args[0], generation=args[1])
                    self._page = ("lobby", None) if op == "lobby_join" else ("home", None)
                except LobbyError as error:
                    self._notice = LOBBY_NOTICES.get(error.code, "The host refused: try again")
                    self._page = ("lobby", None)
            elif op == "lobby_start":
                await self._start_lobby(*args)
            elif op in ("battle_invite", "battle_multi", "battle_ffa", "battle_ffa3"):
                operation, fields = {
                    "battle_invite": ("invite", dict(peer=args[0])),
                    "battle_multi": ("invite_multi", dict(teammate=args[0], opponents=list(args[1:]))),
                    "battle_ffa": ("invite_ffa", dict(opponents=list(args))),
                    "battle_ffa3": ("invite_ffa3", dict(opponents=list(args))),
                }[op]
                try:
                    await self.companion.battle_challenge_rpc(operation, battle_id=str(uuid4()), **fields)
                    self._page = ("battles", None)
                except BattleChallengeError as error:
                    if error.code not in INVITE_NOTICES:
                        raise
                    # The host's answer, shown on the page the challenge was made from (Update 32: a trainer with
                    # no Pokemon yet).
                    self._notice = INVITE_NOTICES[error.code]
            elif op in ("battle_accept", "battle_cancel"):
                if op == "battle_cancel":
                    self._page = ("battles", None)
                fields = dict(battle_id=args[0], generation=args[1])
                if op == "battle_accept": fields["fingerprint"] = args[2]
                try:
                    await self.companion.battle_challenge_rpc(op.removeprefix("battle_"), **fields)
                except BattleChallengeError as error:
                    # The host's answer, shown where the choice was made (the menu used to close on it).
                    self._notice = {"battle_native_abort_required": "Entered games must cancel it",
                                    "battle_offer_changed": "The challenge changed",
                                    "revision_conflict": "A save changed a party",
                                    "battle_started": "The battle already started"}.get(error.code, "The host refused: try again")
            elif op == "wager":
                self._page = ("wager", args[0])
            elif op == "privacy_toggle":
                try:
                    self.companion.set_share_location(not getattr(self.companion, "share_location", True))
                except OSError:
                    self._notice = "Could not save the choice"
                self._page = ("world_players", None)
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
