"""The companion's side of the wireless minigames with the world's players (KNOWN_ISSUES MS-141c).

The game announces the channel ('u'), says who it is when it opens a minigame's lobby (an 'm' HELLO: the game, its link
player), and leaves when it gives up or its game has closed the link (LEAVE, with its reason). The lobby itself is a page of the Players
menu (MinigameMenu below, drawn by player_menu.py): lead a group, join one, start it. When the host starts a group,
every player's companion sends its game STARTED (every player's link player and its own number) and closes the menu;
from then on the link's frames go through here both ways - the game's to the host (minigame_link), the host's to the
game - each on its own bounded lane, so the link never waits behind saves or menus. If the group closes under a started
game (a player lost), the game is told (CLOSED) and shows its own communication error.

A leave goes to the host after the link frames the game sent before it (the leader's closing frame, which the members'
games wait for, ahead of the leader's leaving). A game gone from a started group - its link lost, its bridge closed,
or its lobby left as the start came - leaves as lost: the others' games, which would wait for it, are told the group
has ended. Only a game that closed the link at its end, as every player's game does, leaves quietly.
"""
from __future__ import annotations

import asyncio
import struct

from .minigame_protocol import (CMD_BYTES, FRAME_BYTES, LEAVE_ENDED, MAX_GROUP, TITLES, closed_frame, link_frame,
                                parse_game_frame, started_frame)

OUTBOUND_LIMIT = 512   # link frames waiting for the host connection (some seconds of a game)


def capability_packet() -> bytes:
    """The game's 'u': version 1, 5 players, a command of 14 bytes, a frame of 70."""
    return b"u" + struct.pack("<HHHH", 1, 5, CMD_BYTES, FRAME_BYTES)


class MinigameLink:
    """The companion's minigame channel, bound to the current bridge (rebound on reconnect)."""

    def __init__(self, companion):
        self.companion = companion
        self.bridge = None
        self.activity: str | None = None     # the lobby the game opened (its HELLO)
        self.link_player: bytes | None = None
        self.group_id: int | None = None      # the group this player is in, as the last reply or push said
        self.started: tuple[int, int] | None = None   # (group id, own index) once its game started
        self.notice = ""
        self._outbound: asyncio.Queue | None = None
        self._sender: asyncio.Task | None = None
        self.dropped = 0

    # ---- the bridge ------------------------------------------------------------------------------------------------
    def bind(self, bridge) -> None:
        """A bridge announced 'u'. A new incarnation of the game starts with no lobby and no group."""
        if self.started is not None or self.group_id is not None:
            self._schedule_leave(self.group_id or 0, lost=True)
        self.bridge = bridge
        self.activity = self.link_player = None
        self.group_id = self.started = None
        self.notice = ""
        if self._sender is None or self._sender.done():
            self._outbound = asyncio.Queue(maxsize=OUTBOUND_LIMIT)
            self._sender = asyncio.create_task(self._send_loop(), name="minigame-link-sender")

    async def close(self) -> None:
        """The companion closes: its sender of link frames stops (nothing is left to send to)."""
        sender, self._sender = self._sender, None
        if sender is not None and not sender.done():
            sender.cancel()
            try:
                await sender
            except asyncio.CancelledError:
                pass

    def unbind(self, bridge) -> None:
        if self.bridge is bridge:
            if self.group_id is not None:
                self._schedule_leave(self.group_id, lost=True)   # the game is gone: a started group ends for the others
            self.bridge = None
            self.activity = self.link_player = None
            self.group_id = self.started = None

    def from_game(self, payload: bytes) -> None:
        """An 'm' frame from the game."""
        kind, value = parse_game_frame(payload)
        if kind == "hello":
            self.activity, self.link_player = value
            self.notice = ""
        elif kind == "leave":
            group = self.group_id or 0
            self.started = None
            self.group_id = None
            self._schedule_leave(group, lost=value != LEAVE_ENDED)
        elif self.started is not None:
            message = {"type": "minigame_link", "session_epoch": self.companion.session_epoch,
                       "group_id": self.started[0], "data": value.hex()}
            try:
                self._outbound.put_nowait(message)
            except (asyncio.QueueFull, AttributeError):
                self.dropped += 1

    def _to_game(self, payload: bytes, *, link: bool = False) -> bool:
        bridge = self.bridge
        if bridge is None or self.companion._bridge is not bridge:
            return False
        try:
            if link:
                bridge.outbox.put_minigame(b"m" + payload)
            else:
                bridge.outbox.put_control(b"m" + payload)
            return True
        except Exception:  # noqa: BLE001 - a full or closed outbox: the game reconnects or the group ends
            return False

    # ---- the host ---------------------------------------------------------------------------------------------------
    async def _send_loop(self) -> None:
        while True:
            message = await self._outbound.get()
            if isinstance(message, tuple):
                # a leave, after every link frame queued before it has gone; its answer is not waited for here
                self._leave_now(*message)
                continue
            writer = self.companion._remote_writer
            if writer is None or not self.companion.connected or message.get("session_epoch") != self.companion.session_epoch:
                continue
            try:
                await self.companion._send_remote(writer, message)
            except (ConnectionError, OSError, asyncio.TimeoutError):
                continue

    def _schedule_leave(self, group_id: int, *, lost: bool) -> None:
        """Leave the group after the link frames already queued (lost: see the module's notes)."""
        try:
            self._outbound.put_nowait((group_id, lost))
        except (asyncio.QueueFull, AttributeError):
            self._leave_now(group_id, lost)

    def _leave_now(self, group_id: int, lost: bool) -> None:
        rpc = getattr(self.companion, "minigame_rpc", None)
        if not callable(rpc) or not self.companion.connected:
            return      # without the world connection the host ends the player's groups itself

        async def leave():
            try:
                await rpc("leave", group_id=group_id, lost=lost)
            except Exception:  # noqa: BLE001 - the host forgets a group whose players are gone anyway
                pass
        asyncio.get_running_loop().create_task(leave())

    def on_push(self, message: dict) -> None:
        """A host's push for this player: a group's start or end, or one of its link frames."""
        kind = message["type"]
        if kind == "minigame_link":
            if self.started is not None and message["group_id"] == self.started[0]:
                if not self._to_game(link_frame(message["source"], bytes.fromhex(message["data"])), link=True):
                    self.dropped += 1
            return
        if kind == "minigame_started":
            if self.activity != message["activity"]:
                # a start for a lobby this game no longer shows: the others would wait for it
                self._schedule_leave(message["group_id"], lost=True)
                return
            players = [bytes.fromhex(player) for player in message["link_players"]]
            self.group_id = message["group_id"]
            self.started = (message["group_id"], message["index"])
            if not self._to_game(started_frame(message["activity"], message["index"], players)):
                self.group_id = self.started = None
                self._schedule_leave(message["group_id"], lost=True)
                return
            session = getattr(self.bridge, "menu_session", None)
            close = getattr(session, "close_window", None)
            if callable(close):
                close("Off to the game!")
            return
        # minigame_closed
        if self.group_id is not None and message["group_id"] != self.group_id:
            return
        reason = message["reason"]
        if self.started is not None:
            self._to_game(closed_frame(reason))
        self.started = None
        self.group_id = None
        self.notice = {"leader_ended": "The leader ended the group", "player_lost": "A player left the group",
                       "host_stopped": "The host stopped"}.get(reason, "The group ended")

    def note_group(self, view: dict | None) -> None:
        """A reply's view of this player's group (None: not in one)."""
        self.group_id = view["group_id"] if view else None


class MinigameMenuError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class MinigameMenu:
    """The Players menu's lobby page of one game (player_menu.py draws it): lead a group, join one, the players in it,
    start, leave. B leaves the lobby (and the group, before its start) and closes the window."""

    def __init__(self, companion):
        self.companion = companion
        self.activity: str | None = None
        self.status: dict | None = None
        self.notice = ""

    @property
    def link(self) -> MinigameLink | None:
        return getattr(self.companion, "minigames", None)

    def open(self, activity: str) -> None:
        self.activity = activity
        self.status = None
        self.notice = ""

    async def refresh(self) -> None:
        rpc = getattr(self.companion, "minigame_rpc", None)
        if not callable(rpc) or self.activity is None:
            self.status = None
            return
        self.status = (await rpc("status", activity=self.activity))["result"]
        if self.link is not None:
            self.link.note_group(self.status["mine"])
            if self.link.notice and not self.notice:
                self.notice, self.link.notice = self.link.notice, ""

    def render(self, show):
        """The page through PlayerMenu._show(title, status, [(label, op, args)])."""
        activity = self.activity or "berry_crush"
        title = TITLES[activity]
        if self.status is None:
            return show(title, self.notice or "Asking the host", [])
        mine = self.status["mine"]
        if mine is None:
            groups = self.status["groups"]
            rows = [("Lead a group", "mg_lead", ())]
            rows += [(f"Join {g['leader_name'][:12]} {g['players']}/{MAX_GROUP}", "mg_join", (g["group_id"],))
                     for g in groups[:4]]
            status = self.notice or ("Lead a group or join one" if groups else "No groups yet: lead one")
            return show(title, status, rows)
        players = mine["players"]
        names = [(p["display_name"][:20] or "?", "", ()) for p in players]
        if mine["index"] == 0:
            rows = []
            if len(players) >= mine["minimum"]:
                rows.append((f"Start with {len(players)} players", "mg_start", (mine["group_id"],)))
            rows += names + [("End the group", "mg_leave", (mine["group_id"],))]
            if len(players) < mine["minimum"]:
                status = f"Waiting: {mine['minimum']} players or more"
            else:
                status = self.notice or f"{len(players)} of {MAX_GROUP} players: start?"
            return show(title, status, rows[:6])
        leader = players[0]["display_name"][:12] or "the leader"
        return show(title, self.notice or f"Waiting for {leader} to start", names + [("Leave the group", "mg_leave",
                                                                                      (mine["group_id"],))])

    async def choose(self, op: str, args: tuple) -> str | None:
        """A lobby row: "close" when the window should close (the player left), else None (the page again)."""
        rpc = getattr(self.companion, "minigame_rpc", None)
        link = self.link
        if not callable(rpc) or link is None:
            raise MinigameMenuError("minigame_unavailable")
        self.notice = ""
        if op in ("mg_lead", "mg_join"):
            if link.link_player is None or link.activity != self.activity:
                self.notice = "One moment, then again"
                return None
            try:
                if op == "mg_lead":
                    view = (await rpc("open", activity=self.activity, link_player=link.link_player.hex()))["result"]
                else:
                    view = (await rpc("join", group_id=args[0], link_player=link.link_player.hex()))["result"]
            except MinigameRemoteError as error:
                self.notice = {"minigame_full": "That group is full", "minigame_gone": "That group has gone",
                               "minigame_busy": "Your game is still linked"}.get(error.code, "The host said no")
                return None
            link.note_group(view)
            return None
        if op == "mg_start":
            try:
                await rpc("start", group_id=args[0])
            except MinigameRemoteError as error:
                self.notice = {"minigame_too_few": "Not enough players yet"}.get(error.code, "Could not start")
            return None
        # mg_leave, mg_back: leave the group (before its start) and close the window
        group = args[0] if args else (link.group_id or 0)
        if link.started is None:
            try:
                await rpc("leave", group_id=group, lost=False)
            except Exception:  # noqa: BLE001 - the window closes either way
                pass
            link.group_id = None
        return "close"


class MinigameRemoteError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
