"""Real-game checks of a trade's failure exits and its hold (KNOWN_ISSUES MS-23, MS-68's follow-up, MS-120), for
native_launcher_newcomers_proof.py (--scenario trade-failures, --hold-commands, --watch-window).

trade-failures (two players; the sources make_tower_saves.py's coop-a (a Treecko and a Zigzagoon) and coop-b (a
Torchic), no claims): everyone saves, then, each through PLAYERS and the trade window with ordinary key presses:

  declined      the first player offers its first Pokemon; the second opens Pending trade, Decline trade..., and
                answers the question's Yes: the offerer's window closes with the reason in its game's banner, the
                decliner's menu says "Trade declined"; nothing traded on either side; both walk; both save.
  offers-changed  the second player offers; the first answers, then changes its Pokemon (Change your Pokemon, its
                other one) while the second presses Confirm this trade: the second's window shows "Offers changed;
                review again" (tried up to six times with other gaps between the two presses), the trade goes on and
                is applied with the changed offer.
  lost-replies  the first player offers, the second answers and confirms; every reply of the host to the second's
                Confirm is lost (the host takes the Confirm; its answer never reaches the launcher) until the
                launcher gives up (HOST_PATIENCE_SECONDS) and cancels on its own: the friend's game reads "Trade
                stopped on friend's side.", the launcher's own says why; nothing traded; both walk; both save.
  expired       (--expire-exit) the first player offers and waits in its window; the second never answers: the host
                ends the offer after its time limit, "The trade timed out."; nothing traded; both walk; both save.

--hold-commands PLAYER:SECONDS (trade scenario): in the second trade (traded-back), once both windows show the offers,
that player's launcher sends its game no command for SECONDS (each command waits before it is sent, as a coordinator
waiting on slow host replies holds them; its heartbeat and presence carry on), while the game's trade hold is read
from its memory every 0.25 s: the frames since its last command, its hold's expired flag, its window.

--watch-window (with --freeze worker:...): while a launcher is frozen, when each game's trade window closed.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
import time

from native_launcher_battle_proof import game_picture, unpack_screen
from native_launcher_challenge_proof import pick, shown
from native_launcher_ffa_proof import A, DOWN, LEFT, RIGHT, UP, close_players, pose_of, step
from qualify_admission_cleanup import on_worker, require

EXPIRE_EXIT = [False]
HOLD_COMMANDS = [None]        # (player, seconds)
WATCH_WINDOW = [False]
WATCH_BRIDGE = [False]
PAUSE_KEYS = [None]           # the player whose game gets Ctrl+P, F5 and F9 (KNOWN_ISSUES MS-122)
VBLANK_COUNTER = 32           # struct Main's vblankCounter1 (32-bit build: seven callbacks, intrCheck and its padding)
# struct MpBridge (engine include/platform/mp_bridge.h) in the 32-bit PC game, offsetof() from a probe compiled with -m32
# against that header (sizeof 31400 = the game's sBridge symbol size): the reliable control queue's count (it may hold
# MP_BRIDGE_CONTROL_LIMIT frames; a save or battle response that found it full stopped the bridge before engine 7dbbb1c8,
# KNOWN_ISSUES MS-123), the frame being written to the socket, and whether the bridge is connected.
BRIDGE_SIZE, CONTROL_COUNT, TX_LENGTH, CONNECTED, CONTROL_LIMIT = 31400, 26632, 9244, 295, 4
# The old trade hold: the game's held save expired 600 frames (10 s) after the coordinator's last command; the PC game
# gives an active trade 2,100 more (engine cc897dda, multiplayer_save.c TRADE_HOLD_EXTRA_FRAMES).
OLD_HOLD_FRAMES = 600


def labels(screen):
    return [r.label for r in screen.rows]


def hold_addresses(game):
    """multiplayer_save.c's trade hold statics in the game: sTradeActive, sTradeExpired, and its own sDeadline and sFrame
    (other files have statics of those names; this file's lie just after sTradeActive in .bss)."""
    found = {}
    for line in subprocess.run(["nm", "-n", str(game)], capture_output=True, text=True, check=True).stdout.splitlines():
        parts = line.split()
        if len(parts) == 3:
            found.setdefault(parts[2], []).append(int(parts[0], 16))
    active = found["sTradeActive"][0]
    return dict(active=active, expired=found["sTradeExpired"][0],
                deadline=min(a for a in found["sDeadline"] if a > active),
                frame=min(a for a in found["sFrame"] if a > active))


def bridge_address(game):
    for line in subprocess.run(["nm", "-S", str(game)], capture_output=True, text=True, check=True).stdout.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[3] == "sBridge" and int(parts[1], 16) == BRIDGE_SIZE:
            return int(parts[0], 16)
    raise ValueError("the game has no sBridge of the expected size")


def bridge_state(pid, address):
    with open(f"/proc/{pid}/mem", "rb", buffering=0) as memory:
        def read(offset, size):
            memory.seek(address + offset)
            return int.from_bytes(memory.read(size), "little")
        return dict(queued=read(CONTROL_COUNT, 4), tx=read(TX_LENGTH, 4), connected=read(CONNECTED, 1))


def hold_state(probe, where):
    with open(f"/proc/{probe.pid}/mem", "rb", buffering=0) as memory:
        def read(address, size):
            memory.seek(address)
            return int.from_bytes(memory.read(size), "little")
        frame, deadline = read(where["frame"], 4), read(where["deadline"], 4)
        since = (frame - deadline) & 0xFFFFFFFF
        since = (since - (1 << 32) if since >= 1 << 31 else since) + OLD_HOLD_FRAMES
        return dict(trade_active=read(where["active"], 1), expired=read(where["expired"], 1), frame=frame,
                    frames_since_command=since, window=probe.read()["active"])


class TradeAuditMixin:
    """Mixed into NewcomersProof."""

    # Plumbing -----------------------------------------------------------------------------------------------------
    def screen_now(self, probe):
        row = probe.read()
        if not row["active"]:
            return dict(active=False)
        try:
            screen = unpack_screen(row["screen"], allow_trade_reopen=True, allow_battle_admission=True)[1]
        except ValueError:
            return dict(active=True, unreadable=True)
        return dict(active=True, waiting=bool(row["waiting"]), title=screen.title, status=screen.status,
                    rows=labels(screen), cursor=row["cursor"])

    async def picture(self, n, name):
        try:
            return await asyncio.to_thread(game_picture, self.harness.players[n].probe,
                                           self.harness.output / f"{name}.png", .3)
        except Exception as error:  # noqa: BLE001 - a picture never fails a check
            return f"no picture: {error!r}"

    async def watch_banners(self, current):
        """Every banner a launcher puts in its own game (Companion.show_local_notice: how a trade ended), with when."""
        self.banners = {n: [] for n in range(len(current))}
        self.companions = [await self.companion_of(w) for w in current]
        for n, c in enumerate(self.companions):
            real = c.show_local_notice

            def shown_notice(text, *args, _real=real, _n=n, **options):
                self.banners[_n].append([round(time.monotonic() - self.t0, 1), text])
                return _real(text, *args, **options)
            c.show_local_notice = shown_notice

    def banners_since(self, n, since):
        return [text for at, text in self.banners.get(n, ()) if at >= round(since - self.t0, 1) - .1]

    async def snapshot(self, current, probes):
        return dict(revisions=[(await self.launcher(w))["revision"] for w in current],
                    heads=await self.heads(current, self.harness.host),
                    games=[p.party_now() for p in probes])

    async def trade_page(self, probe, test, what, timeout=60):
        """The trade window's (or the menu's) screen once it passes `test`."""
        try:
            async with asyncio.timeout(timeout):
                while True:
                    row, screen = await shown(probe, timeout=timeout)
                    if test(screen):
                        return row, screen
                    await asyncio.sleep(.1)
        except TimeoutError:
            raise AssertionError(f"{what}: the window shows {self.screen_now(probe)}") from None

    async def cursor_to(self, probe, index):
        row, screen = await shown(probe)
        for _ in range((index - row["cursor"]) % len(screen.rows)):
            await probe.press(DOWN)
        require(probe.read()["cursor"] == index, f"the cursor did not reach row {index}")

    async def open_offer(self, probes, offerer, answerer, label=None):
        """The offerer: PLAYERS, the answerer's name, Trading, its Pokemon (the first, or `label`): its window shows the
        trade's review page."""
        await probes[offerer].open_players()
        await probes[offerer].choose(self.harness.host.accounts[answerer].display_name, prefix=True)
        await probes[offerer].choose("Trading", wait=False)
        await self.trade_page(probes[offerer], lambda s: s.title == "Trade Pokemon" and s.status.startswith("Pick"),
                              "the offerer's party page")
        offered = await pick(probes[offerer], label, again="Trading")
        await self.trade_page(probes[offerer], lambda s: "Change your Pokemon" in labels(s), "the offerer's review page")
        return offered

    async def answer_offer(self, probes, answerer, label=None):
        await probes[answerer].open_players()
        await probes[answerer].choose("Pending trade")
        await probes[answerer].choose("Choose your Pokemon", wait=False)
        await self.trade_page(probes[answerer], lambda s: s.title == "Trade Pokemon" and s.status.startswith("Pick"),
                              "the answerer's party page")
        offered = await pick(probes[answerer], label, again="Choose your Pokemon")
        await self.trade_page(probes[answerer], lambda s: "Change your Pokemon" in labels(s),
                              "the answerer's review page")
        return offered

    async def ended(self, current, probes, record, players, label, timeout=150, codes=("trade_cancelled",)):
        """Each of `players` (their trade window open) back on the field: its window closed, its launcher holding no trade
        and reporting one of `codes`; the seconds it took."""
        started = time.monotonic()
        async with asyncio.timeout(timeout):
            while True:
                launchers = {n: await self.launcher(current[n]) for n in players}
                if all(v.get("interaction") is None and v.get("trade") is None and v.get("code") in codes
                       and not probes[n].read()["active"] for n, v in launchers.items()):
                    break
                await asyncio.sleep(.5)
        record(label, seconds=round(time.monotonic() - started, 1),
               launchers={self.harness.names[n]: dict(code=v.get("code"), revision=v.get("revision"),
                                                      connected=v.get("connected")) for n, v in launchers.items()})
        return launchers

    async def field_moves(self, n, current, probes, record, label):
        """The player walks: a step in some direction changes its game's own pose (the field is not frozen)."""
        companion = self.companions[n]
        if probes[n].read()["active"]:
            await close_players(probes[n])
        await self.on_field(current[n], timeout=60)
        before = pose_of(companion)
        moved = None
        for key in (LEFT, RIGHT, DOWN, UP, RIGHT, LEFT):
            after = await step(probes[n], companion, key, record, n)
            if after is not None and before is not None and after[2:] != before[2:]:
                moved = dict(key=key, before=list(before[2:]), after=list(after[2:]))
                break
        record(label, player=self.harness.names[n], moved=moved)
        require(moved is not None, f"{label}: {self.harness.names[n]} could not walk: at {pose_of(companion)}")

    async def saving_works(self, n, current, record, label):
        state = await self.launcher(current[n])
        await self.save_now(n, current[n])
        await self.saved(current[n], state["revision"])
        after = await self.launcher(current[n])
        record(label, player=self.harness.names[n], revisions=[state["revision"], after["revision"]],
               code=after.get("code"))

    async def after_a_failed_trade(self, current, probes, record, label):
        for n in (0, 1):
            await self.field_moves(n, current, probes, record, f"{label}-walks")
        for n in (0, 1):
            await self.saving_works(n, current, record, f"{label}-saves")

    def nothing_traded(self, before, after, record, label):
        same = [b["serials"] == a["serials"] and b["count"] == a["count"] for b, a in zip(before["heads"], after["heads"])]
        record(label, host_heads_unchanged=same, before=before["heads"], after=after["heads"],
               games_before=before["games"], games_after=after["games"])
        require(all(same), f"{label}: the host's saves changed: {before['heads']} -> {after['heads']}")
        require([g["box_crc"] for g in before["games"]] == [g["box_crc"] for g in after["games"]],
                f"{label}: a game's party changed: {before['games']} -> {after['games']}")

    def drop_replies(self, player_id, operation):
        """From now on the host's answers to this player's trade `operation` are lost on their way (the host still
        takes the request); `restore` ends it. The count of answers lost is in the returned state."""
        from emerald_multiplayer.server import WorldServer
        control = WorldServer._control
        state = dict(dropped=0, first=None, last=None)

        def lossy(server, session, message):
            if (message.get("type") in ("trade_result", "trade_error") and message.get("operation") == operation
                    and getattr(session, "player_id", None) == player_id):
                now = round(time.monotonic() - self.t0, 1)
                state["dropped"] += 1
                state["first"] = state["first"] or now
                state["last"] = now
                return
            control(server, session, message)
        WorldServer._control = lossy

        def restore():
            WorldServer._control = control
        return state, restore

    # The scenario -------------------------------------------------------------------------------------------------
    async def trade_failures(self, current, probes, record):
        host = self.harness.host
        await self.watch_banners(current)
        canonical = await self.save_all(current, record, "saved-before-the-trades")
        require([c["count"] for c in canonical] == [2, 1], f"trade-failures: coop-a then coop-b: {canonical}")
        await self.exit_declined(current, probes, record, 0, 1)
        await self.exit_offers_changed(current, probes, record, offerer=1, answerer=0)
        await self.exit_lost_replies(current, probes, record, offerer=0, answerer=1)
        if EXPIRE_EXIT[0]:
            await self.exit_expired(current, probes, record, offerer=0, answerer=1)
        record("trade-banners", banners={self.harness.names[n]: v for n, v in self.banners.items()})
        parties = await self.heads(current, host)
        revisions = [(await self.launcher(w))["revision"] + 1 for w in current]
        return dict(parties=parties, revisions=revisions)

    async def exit_declined(self, current, probes, record, offerer, answerer):
        names = self.harness.names
        before = await self.snapshot(current, probes)
        offered = await self.open_offer(probes, offerer, answerer)
        record("declined-offer-open", offerer=names[offerer], offered=offered, screen=self.screen_now(probes[offerer]))
        await probes[answerer].open_players()
        await probes[answerer].choose("Pending trade")
        record("declined-trade-page", screen=self.screen_now(probes[answerer]))
        await probes[answerer].choose("Decline trade...", wait=False)
        await self.trade_page(probes[answerer], lambda s: s.title == "Decline the trade?", "the decline question")
        record("declined-asked", screen=self.screen_now(probes[answerer]))
        await asyncio.sleep(1.0)                  # past the question's 0.6 s grace, as a player reads it
        started = time.monotonic()
        await pick(probes[answerer], "Yes, decline the trade")
        await self.trade_page(probes[answerer], lambda s: s.title != "Decline the trade?", "after the decline")
        menu = self.screen_now(probes[answerer])
        record("declined-answerer-menu", player=names[answerer], screen=menu,
               picture=await self.picture(answerer, "declined-answerer-menu"))
        await self.ended(current, probes, record, [offerer], "declined-offerer-window-closed")
        await asyncio.sleep(2)
        banners = {names[n]: self.banners_since(n, started) for n in (0, 1)}
        record("declined-banners", banners=banners, picture=await self.picture(offerer, "declined-offerer-banner"))
        after = await self.snapshot(current, probes)
        self.nothing_traded(before, after, record, "declined-nothing-traded")
        require(menu.get("status") == "Trade declined", f"declined: the decliner's menu says {menu}")
        require(any(b.startswith("Your friend cancelled the trade.") for b in banners[names[offerer]]),
                f"declined: the offerer's game said {banners[names[offerer]]}")
        await self.after_a_failed_trade(current, probes, record, "declined")

    async def exit_offers_changed(self, current, probes, record, offerer, answerer, attempts=8):
        """The answerer (two Pokemon) changes its offer while the offerer presses Confirm this trade."""
        names = self.harness.names
        before = await self.snapshot(current, probes)
        offered = {offerer: await self.open_offer(probes, offerer, answerer)}
        offered[answerer] = await self.answer_offer(probes, answerer)
        record("offers-changed-open", offered={names[n]: v for n, v in offered.items()})
        current_row, seen, hit = 0, [], False
        for attempt, gap in enumerate((0.3, 0.15, 0.45, 0.05, 0.6, 0.25, 0.1, 0.8)[:attempts]):
            await self.trade_page(probes[answerer], lambda s: "Change your Pokemon" in labels(s), "answerer review")
            if "Confirm this trade" not in self.screen_now(probes[offerer]).get("rows", ()):
                # The offerer's last Confirm came after the change had reached its window: it confirmed the pair as it
                # now is. One more change of the answerer's Pokemon (not raced) clears that confirmation.
                record("offers-changed-unconfirm", offerer=self.screen_now(probes[offerer]))
                await pick(probes[answerer], "Change your Pokemon")
                await self.trade_page(probes[answerer], lambda s: s.status.startswith("Pick"), "the answerer's party page")
                await self.cursor_to(probes[answerer], 1 - current_row)
                await probes[answerer].press(A)
                current_row = 1 - current_row
                await self.trade_page(probes[offerer], lambda s: "Confirm this trade" in labels(s), "the offerer's Confirm")
                await self.trade_page(probes[answerer], lambda s: "Change your Pokemon" in labels(s), "answerer review")
            await pick(probes[answerer], "Change your Pokemon")
            _, party = await self.trade_page(probes[answerer], lambda s: s.status.startswith("Pick"),
                                             "the answerer's party page")
            target = 1 - current_row
            await self.cursor_to(probes[answerer], target)
            _, review = await self.trade_page(probes[offerer], lambda s: "Confirm this trade" in labels(s),
                                              "the offerer's Confirm")
            await self.cursor_to(probes[offerer], labels(review).index("Confirm this trade"))
            change = asyncio.create_task(probes[answerer].press(A))
            await asyncio.sleep(gap)
            confirm = asyncio.create_task(probes[offerer].press(A))
            await asyncio.gather(change, confirm)
            current_row = target
            statuses = []
            until = time.monotonic() + 6
            while time.monotonic() < until:
                now = self.screen_now(probes[offerer])
                if now.get("status") and (not statuses or statuses[-1] != now["status"]):
                    statuses.append(now["status"])
                if now.get("status") == "Offers changed; review again":
                    hit = True
                    picture = await self.picture(offerer, "offers-changed-review-again")
                    break
                await asyncio.sleep(.05)
            seen.append(dict(attempt=attempt + 1, gap=gap, offered_row=target, offerer_statuses=statuses,
                             answerer=self.screen_now(probes[answerer])))
            record("offers-changed-attempt", **seen[-1])
            if hit:
                record("offers-changed-review-again", attempt=attempt + 1, screen=self.screen_now(probes[offerer]),
                       picture=picture)
                break
        require(hit, f"offers-changed: the race was never met in {attempts} tries: {seen}")
        # The trade goes on: both confirm the pair as it now is.
        started = time.monotonic()
        confirmed = set()
        while True:
            launchers = {n: await self.launcher(current[n]) for n in (0, 1)}
            if all(v.get("interaction") is None and v.get("trade") is None and v.get("revision") == before["revisions"][n] + 2
                   for n, v in launchers.items()):
                break
            for n in (0, 1):
                if n in confirmed:
                    continue
                now = self.screen_now(probes[n])
                if now.get("active") and not now.get("waiting") and "Confirm this trade" in now.get("rows", ()):
                    await pick(probes[n], "Confirm this trade")
                    confirmed.add(n)
                    record("offers-changed-confirmed", player=names[n], seconds=round(time.monotonic() - started, 1))
            require(time.monotonic() - started < self.watch, f"offers-changed: the trade did not finish: {launchers}")
            await asyncio.sleep(.5)
        await asyncio.sleep(2)
        after = await self.snapshot(current, probes)
        record("offers-changed-applied", seconds=round(time.monotonic() - started, 1), heads=after["heads"],
               banners={names[n]: self.banners_since(n, started) for n in (0, 1)},
               picture=await self.picture(offerer, "offers-changed-applied"))
        a, b = before["heads"][answerer]["serials"], before["heads"][offerer]["serials"]
        require(sorted(after["heads"][answerer]["serials"] + after["heads"][offerer]["serials"]) == sorted(a + b)
                and after["heads"][offerer]["serials"] != b, f"offers-changed: not one exchange: {before} -> {after}")

    async def exit_lost_replies(self, current, probes, record, offerer, answerer):
        names = self.harness.names
        before = await self.snapshot(current, probes)
        offered = {offerer: await self.open_offer(probes, offerer, answerer)}
        offered[answerer] = await self.answer_offer(probes, answerer)
        player = self.harness.host.accounts[answerer].player_id
        state, restore = self.drop_replies(player, "confirm")
        try:
            started = time.monotonic()
            await pick(probes[answerer], "Confirm this trade")
            record("lost-replies-confirmed", player=names[answerer], offered={names[n]: v for n, v in offered.items()})
            await self.ended(current, probes, record, [offerer, answerer], "lost-replies-both-windows-closed",
                                         timeout=180)
        finally:
            restore()
        await asyncio.sleep(2)
        banners = {names[n]: self.banners_since(n, started) for n in (0, 1)}
        record("lost-replies-banners", replies_lost=state, banners=banners,
               pictures=[await self.picture(n, f"lost-replies-banner-{n}") for n in (0, 1)])
        after = await self.snapshot(current, probes)
        self.nothing_traded(before, after, record, "lost-replies-nothing-traded")
        require(state["dropped"] >= 1, "lost-replies: no reply was lost")
        require(any(b.startswith("Trade stopped on friend's side.") for b in banners[names[offerer]]),
                f"lost-replies: the friend's game said {banners[names[offerer]]}")
        require(banners[names[answerer]], "lost-replies: the launcher that gave up said nothing in its game")
        await self.after_a_failed_trade(current, probes, record, "lost-replies")

    async def exit_expired(self, current, probes, record, offerer, answerer):
        names = self.harness.names
        before = await self.snapshot(current, probes)
        offered = await self.open_offer(probes, offerer, answerer)
        started = time.monotonic()
        record("expired-offer-open", offerer=names[offerer], offered=offered)
        statuses = []

        async def watch():
            while True:
                statuses.append([round(time.monotonic() - started), self.screen_now(probes[offerer]).get("status")])
                await asyncio.sleep(15)
        watcher = asyncio.create_task(watch())
        try:
            await self.ended(current, probes, record, [offerer], "expired-offerer-window-closed", timeout=300)
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        seconds = round(time.monotonic() - started, 1)
        await asyncio.sleep(2)
        banners = {names[n]: self.banners_since(n, started) for n in (0, 1)}
        record("expired-banners", seconds_after_the_offer=seconds, statuses=statuses, banners=banners,
               picture=await self.picture(offerer, "expired-offerer-banner"))
        await probes[answerer].open_players()
        _, home = await probes[answerer].ready()
        record("expired-friend-players", rows=labels(home), status=home.status)
        require("Pending trade" not in labels(home), f"expired: the friend still has the trade: {labels(home)}")
        await close_players(probes[answerer])
        after = await self.snapshot(current, probes)
        self.nothing_traded(before, after, record, "expired-nothing-traded")
        require(any(b.startswith("The trade timed out.") for b in banners[names[offerer]]),
                f"expired: the offerer's game said {banners[names[offerer]]}")
        await self.after_a_failed_trade(current, probes, record, "expired")

    # MS-120: the game's hold while its coordinator waits -----------------------------------------------------------
    async def hold_commands(self, n, seconds, record, label):
        """For `seconds` this player's launcher sends its game no command (each waits before it is sent); the game's trade
        hold read every 0.25 s meanwhile and until the next command has reached it."""
        companion = await self.companion_of(self.current[n])
        probe = self.harness.players[n].probe
        where = getattr(self, "_hold_where", None) or hold_addresses(self.harness.game)
        self._hold_where = where
        real = companion.save_rpc
        until = time.monotonic() + seconds
        held = []

        async def save_rpc(control, *args, **options):
            wait = until - time.monotonic()
            if wait > 0:
                held.append(dict(opcode=int(control.opcode), waited=round(wait, 1)))
                await asyncio.sleep(wait)
            return await real(control, *args, **options)
        companion.save_rpc = save_rpc
        started = time.monotonic()
        samples = []
        try:
            while time.monotonic() < until + 3:
                state = hold_state(probe, where)
                samples.append([round(time.monotonic() - started, 2), state["frames_since_command"], state["expired"],
                                state["window"], state["trade_active"]])
                await asyncio.sleep(.25)
        finally:
            companion.save_rpc = real
        peak = max(samples, key=lambda s: s[1])
        record(label, player=self.harness.names[n], seconds=seconds, commands_held=held,
               most_frames_without_a_command=peak[1], at=peak[0], old_limit_frames=OLD_HOLD_FRAMES,
               expired_ever=any(s[2] for s in samples), window_always_open=all(s[3] for s in samples),
               trade_hold_active_always=all(s[4] for s in samples), samples=samples[::4])
        return samples

    async def watch_bridge(self, slot, seconds, record, where):
        """--watch-bridge: during a launcher's freeze (its companion reads nothing from its game), that game's bridge to
        the companion read every 20 ms: its reliable control queue (full at CONTROL_LIMIT), the frame waiting for the
        socket, and whether it stays connected; and the companion's socket to the game (bytes waiting to be read)."""
        probe = self.harness.players[slot].probe
        address = getattr(self, "_bridge_address", None) or bridge_address(self.harness.game)
        self._bridge_address = address
        started = time.monotonic()
        samples = []
        while time.monotonic() - started < seconds + 3:
            try:
                state = bridge_state(probe.pid, address)
            except OSError:
                break
            samples.append([round(time.monotonic() - started, 2), state["queued"], state["tx"], state["connected"]])
            await asyncio.sleep(.02)
        record("bridge-during-the-freeze", frozen=self.harness.names[slot], where=where, seconds=seconds,
               most_queued=max((s[1] for s in samples), default=None), queue_limit=CONTROL_LIMIT,
               most_tx_waiting=max((s[2] for s in samples), default=None),
               connected_throughout=all(s[3] for s in samples), samples=len(samples),
               queued_over_time=[s for s in samples if s[1]][:40])

    def symbol_addresses(self, *names):
        found = {}
        for line in subprocess.run(["nm", "-S", str(self.harness.game)], capture_output=True, text=True,
                                   check=True).stdout.splitlines():
            parts = line.split()
            if len(parts) == 4 and parts[3] in names:
                found.setdefault(parts[3], (int(parts[0], 16), int(parts[1], 16)))
        return found

    async def pause_keys(self, n, record, where):
        """--pause-keys (KNOWN_ISSUES MS-122): Ctrl+P, F5 (the survey view) and F9 (photo mode) pressed in this player's
        game during a link battle or a held trade, each with xdotool to the game's window, as a player presses them; after
        each: the 3D game's notice (sScreenshotNotice and when it was set), its pause and photo-mode flags, its frames
        counting on (gMain.vblankCounter1), the trade hold or battle still there, a picture. The game's own log line
        ("pause refused: ...") is looked for in its runtime.log after the run."""
        probe = self.harness.players[n].probe
        where_ = self.symbol_addresses("sScreenshotNotice", "sScreenshotNoticeMs", "paused", "sPhotoMode", "gMain",
                                       "sTradeActive", "gMultiplayerBattleHoldFlags")

        def read(name, size=None, offset=0):
            address, length = where_[name]
            with open(f"/proc/{probe.pid}/mem", "rb", buffering=0) as memory:
                memory.seek(address + offset)
                return memory.read(length if size is None else size)

        def state():
            notice = read("sScreenshotNotice").split(b"\0")[0].decode("latin-1") if "sScreenshotNotice" in where_ else None
            return dict(frames=int.from_bytes(read("gMain", 4, VBLANK_COUNTER), "little"),
                        paused=read("paused", 1)[0] if "paused" in where_ else None,
                        photo=read("sPhotoMode", 1)[0] if "sPhotoMode" in where_ else None,
                        notice=notice,
                        notice_ms=int.from_bytes(read("sScreenshotNoticeMs", 4), "little") if "sScreenshotNoticeMs" in where_ else None,
                        trade_active=read("sTradeActive", 1)[0], battle_hold=int.from_bytes(read("gMultiplayerBattleHoldFlags", 4), "little"),
                        window=probe.read()["active"])
        results = []
        for key in ("ctrl+p", "F5", "F9"):
            before = state()

            def press(key=key):
                probe._window()
                subprocess.run(["xdotool", "key", key], env=probe.environment, check=True)
            await asyncio.to_thread(press)
            await asyncio.sleep(1.5)
            after = state()
            picture = await self.picture(n, f"pause-key-{where}-{key.replace('+', '-')}")
            await asyncio.sleep(1.0)
            later = state()
            results.append(dict(key=key, before=before, after=after, frames_in_2_5_s=later["frames"] - before["frames"],
                                paused_after=later["paused"], photo_after=later["photo"], picture=picture))
        record("pause-keys-" + where, player=self.harness.names[n], keys=results)
        for r in results:
            require(r["frames_in_2_5_s"] > 5 and not r["paused_after"] and not r["photo_after"],
                    f"pause keys during the {where}: the game stopped: {r}")

    async def watch_windows(self, slot, seconds, record, where):
        """--watch-window: during a launcher's freeze, when each game's trade window closed (seconds into the freeze)."""
        started = time.monotonic()
        closed = {}
        probes = [p.probe for p in self.harness.players]
        while time.monotonic() - started < seconds + 2:
            for n, probe in enumerate(probes):
                if n not in closed and not probe.read()["active"]:
                    closed[n] = round(time.monotonic() - started, 2)
            await asyncio.sleep(.05)
        record("trade-windows-during-the-freeze", frozen=self.harness.names[slot], where=where, seconds=seconds,
               closed_after={self.harness.names[n]: closed.get(n) for n in range(len(probes))})


# MS-124: a friend whose link holds everything for seconds ----------------------------------------------------------------
PROXY_BUFFER = 4096
# 3 s (the triage's 3-5 s): a 5 s stall at a save's first request outlasts the checkpoint request's own 5 s answer
# timeout (ms124-proxy-stall-1: the save failed with TimeoutError and saving stopped, save_recovery_required)
PROXY_STALL_SECONDS = 3.0
PROXY_SAVE_STALL = [3.0]          # --proxy-save-stall: the stall during the save's upload
PROXY_STOP_BEFORE_CHUNKS = [False]     # --proxy-stop-before-chunks


class ProxyStallMixin:
    """--scenario proxy-stall (two players with Pokemon: coop-a, coop-b). The friend's launcher reaches the host through
    audit_tcp_proxy.py (its connections to the host's loopback port are sent to the proxy: asyncio.open_connection in
    the friend's launcher threads), whose sockets have small kernel buffers; both ends of the friend's link get small
    send buffers too (SO_SNDBUF, and the transport's write buffer limit 2 KiB), as a lossy link whose TCP is
    retransmitting leaves room for little, so a write must wait while the link holds. The proxy process is then stopped
    (SIGSTOP) for PROXY_STALL_SECONDS while the friend's save uploads (Save now) and again 20 s into a Rival 1v1, and
    continued. Every StreamWriter.drain() of the proof process that waits over 0.3 s is recorded with its thread
    (the host's or the friend's launcher): a write that waited over 1 s dropped the player before app 89a27d5. The
    friend must stay connected (same session epoch on both ends, the host's session not closed), the save must land and
    the battle must end normally."""

    def install_proxy(self, harness):
        import subprocess as sp
        import sys
        import threading
        self.proxies, self.proxied, self.drains = {}, [], []
        self.stop_armed = False           # --proxy-stop-before-chunks: only the save the stall is meant for
        proof = self
        real_open = asyncio.open_connection

        def proxy_for(port):
            if port not in proof.proxies:
                log = open(harness.output / f"proxy-{port}.log", "w")
                process = sp.Popen([sys.executable, str(Path(__file__).with_name("audit_tcp_proxy.py")), "--target",
                                    str(port), "--buffer", str(PROXY_BUFFER)], stdout=sp.PIPE, stderr=log, text=True)
                line = process.stdout.readline().split()
                require(len(line) == 2 and line[0] == "listening", f"the proxy did not start: {line}")
                proof.proxies[port] = (process, int(line[1]))
            return proof.proxies[port][1]

        # Each launcher worker is tagged with the slot harness.start was starting when it first met this check (the
        # friend's is slot 1, also after a rejoin, whose worker is the harness's third).
        proof.starting_slot = 0
        real_start = harness.start

        async def start(phase, slot):
            proof.starting_slot = slot
            return await real_start(phase, slot)
        harness.start = start

        def friend_thread():
            current = threading.current_thread()
            found = False
            for w in harness.workers:
                if not hasattr(w, "_audit_slot"):
                    w._audit_slot = proof.starting_slot
                found = found or (w._audit_slot == 1 and getattr(w, "_thread", None) is current)
            return found

        async def open_connection(host=None, port=None, *args, **options):
            if friend_thread() and host in ("127.0.0.1", "localhost") and port:
                via = proxy_for(port)
                proof.proxied.append(dict(port=port, via=via, at=time.strftime("%H:%M:%S")))
                return await real_open(host, via, *args, **options)
            return await real_open(host, port, *args, **options)
        asyncio.open_connection = open_connection
        real_drain = asyncio.StreamWriter.drain

        async def drain(writer):
            started = time.monotonic()
            try:
                return await real_drain(writer)
            finally:
                waited = time.monotonic() - started
                if waited > .3:
                    current = threading.current_thread()
                    slot = next((getattr(w, "_audit_slot", None) for w in harness.workers
                                 if getattr(w, "_thread", None) is current), None)
                    proof.drains.append(dict(at=round(time.monotonic() - getattr(proof, "t0", started), 1),
                                             seconds=round(waited, 2),
                                             side={0: "host launcher", 1: "friend launcher"}.get(slot, current.name),
                                             peer=str(writer.get_extra_info("peername"))))
        asyncio.StreamWriter.drain = drain
        from emerald_multiplayer import checkpoint_client
        real_answers = checkpoint_client.CheckpointClient._answers
        try:
            main_loop = asyncio.get_running_loop()
        except RuntimeError:
            main_loop = asyncio.get_event_loop_policy().get_event_loop()
        self.upload_started = asyncio.Event()

        def answers(client, operation, requests):
            # the save's data chunks are about to go (its begin request answered): the stall comes now; with
            # PROXY_STOP_BEFORE_CHUNKS the proxy is stopped here, in the friend's launcher thread, before the first chunk
            # is written, so the chunks meet a link that holds everything (they pile up in the small buffers)
            if friend_thread() and operation == "chunk":
                if PROXY_STOP_BEFORE_CHUNKS[0] and proof.stop_armed and not proof.upload_started.is_set():
                    import signal as _signal
                    for process, _ in proof.proxies.values():
                        os.kill(process.pid, _signal.SIGSTOP)
                    proof.stopped_at = time.monotonic()
                main_loop.call_soon_threadsafe(proof.upload_started.set)
            return real_answers(client, operation, requests)
        checkpoint_client.CheckpointClient._answers = answers
        # --proxy-stop-before-chunks also: the host about to answer the friend's first save read (a startup download) stops
        # the proxy first, in the host's launcher thread, so the host's answers pile up behind a link that holds them
        from emerald_multiplayer.server import WorldServer
        real_control = WorldServer._control
        proof.host_stop_armed, proof.host_stopped = False, asyncio.Event()

        def control(server, session, message):
            if (proof.host_stop_armed and message.get("type") == "checkpoint_result" and message.get("operation") == "read"
                    and getattr(session, "player_id", None) == getattr(proof, "friend_id", None)):
                import signal as _signal
                proof.host_stop_armed = False
                for process, _ in proof.proxies.values():
                    os.kill(process.pid, _signal.SIGSTOP)
                proof.host_stopped_at = time.monotonic()
                main_loop.call_soon_threadsafe(proof.host_stopped.set)
            return real_control(server, session, message)
        WorldServer._control = control

    def stop_proxies(self):
        import signal
        for process, _ in getattr(self, "proxies", {}).values():
            if process.poll() is None:
                try:
                    import os
                    os.kill(process.pid, signal.SIGCONT)
                except ProcessLookupError:
                    pass
                process.terminate()
                try:
                    process.wait(10)
                except Exception:  # noqa: BLE001
                    process.kill()

    async def link_state(self, current):
        friend_id = self.harness.host.accounts[1].player_id

        async def host_side(s):
            session = s._server.sessions.get(friend_id)
            return None if session is None else dict(epoch=session.session_epoch, closed=session.closed,
                                                     reason=session.close_reason, id=id(session),
                                                     peer=str(session.writer.get_extra_info("peername")))

        async def friend_side(s):
            c = s._companion
            writer = c._remote_writer
            return dict(connected=c.connected, epoch=c.session_epoch,
                        peer=None if writer is None else str(writer.get_extra_info("peername")))
        return dict(host=await on_worker(current[0], host_side), friend=await on_worker(current[1], friend_side))

    async def small_buffers(self, current, record):
        import socket
        friend_id = self.harness.host.accounts[1].player_id

        def shrink(writer):
            sock = writer.get_extra_info("socket")
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, PROXY_BUFFER)
            writer.transport.set_write_buffer_limits(high=2048, low=512)
            return dict(sndbuf=sock.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF),
                        limits=list(writer.transport.get_write_buffer_limits()))

        async def host_side(s):
            return shrink(s._server.sessions[friend_id].writer)

        async def friend_side(s):
            return shrink(s._companion._remote_writer)
        record("friend-link-buffers", host=await on_worker(current[0], host_side),
               friend=await on_worker(current[1], friend_side), proxied=self.proxied,
               proxies={port: via for port, (_, via) in self.proxies.items()})

    async def stall_proxy(self, seconds, record, where, already_stopped_at=None):
        import signal
        pids = [process.pid for process, _ in self.proxies.values() if process.poll() is None]
        require(pids, "no proxy is running")
        before = len(self.drains)
        started = time.monotonic() if already_stopped_at is None else already_stopped_at
        if already_stopped_at is None:
            for pid in pids:
                os.kill(pid, signal.SIGSTOP)
        else:
            seconds = max(0.0, seconds - (time.monotonic() - already_stopped_at))
        try:
            await asyncio.sleep(seconds)
        finally:
            for pid in pids:
                os.kill(pid, signal.SIGCONT)
        await asyncio.sleep(2)
        record("proxy-stalled", where=where, seconds=round(time.monotonic() - started - 2, 1),
               drains_meanwhile=self.drains[before:])

    async def proxy_stall(self, current, probes, symbols, record):
        await self.save_all(current, record, "saved-before-the-stalls")
        require(self.proxied, "the friend's launcher did not connect through the proxy")
        state = await self.link_state(current)
        record("friend-linked-through-the-proxy", link=state, proxied=self.proxied)
        await self.small_buffers(current, record)
        # (a) a stall while the friend's save uploads
        revision = (await self.launcher(current[1]))["revision"]
        self.upload_started.clear()
        self.stop_armed = True
        saving = asyncio.create_task(self.save_now(1, current[1]))
        await asyncio.wait_for(self.upload_started.wait(), 60)
        self.stop_armed = False
        await self.stall_proxy(PROXY_SAVE_STALL[0], record, "the friend's save upload",
                               already_stopped_at=getattr(self, "stopped_at", None) if PROXY_STOP_BEFORE_CHUNKS[0] else None)
        await saving
        await self.saved(current[1], revision, seconds=90)
        after = await self.link_state(current)
        record("save-after-the-stall", revisions=[revision, (await self.launcher(current[1]))["revision"]], link=after)
        require(after["friend"]["connected"] and after["friend"]["epoch"] == state["friend"]["epoch"]
                and after["host"] is not None and not after["host"]["closed"] and after["host"]["id"] == state["host"]["id"],
                f"the friend's link did not survive the stall during the save: {state} -> {after}")
        # (b) a stall 20 s into a Rival 1v1
        await self.challenge_1v1(self.harness.host, probes, 0, 1)

        async def stall():
            await self.stall_proxy(PROXY_STALL_SECONDS, record, "the battle")
        await self.play(current, probes, symbols, record, (0, 1), "1v1", "rival-1v1-stalled", freeze=stall)
        final = await self.link_state(current)
        record("link-after-the-battle", link=final, drains=self.drains)
        require(final["friend"]["connected"] and final["friend"]["epoch"] == state["friend"]["epoch"]
                and final["host"] is not None and final["host"]["id"] == state["host"]["id"],
                f"the friend's link did not survive the stall during the battle: {state} -> {final}")
        if PROXY_STOP_BEFORE_CHUNKS[0]:
            # (c) the friend closes its game and joins again: its launcher downloads its save from the host at startup;
            # the proxy is stopped as the host writes the first answers of that download
            self.friend_id = self.harness.host.accounts[1].player_id
            self.host_stopped.clear()
            self.host_stop_armed = True
            joining = asyncio.create_task(self.rejoin(1, current, probes, self.games, record))
            try:
                await asyncio.wait_for(self.host_stopped.wait(), 180)
            finally:
                self.host_stop_armed = False
            await self.stall_proxy(PROXY_STALL_SECONDS, record, "the friend's startup download (the host writing)",
                                   already_stopped_at=self.host_stopped_at)
            await joining
            again = await self.link_state(current)
            record("link-after-the-download-stall", link=again, drains=self.drains,
                   proxies={port: via for port, (_, via) in self.proxies.items()})
            require(again["friend"]["connected"] and again["host"] is not None and not again["host"]["closed"],
                    f"the friend's link did not survive the stall during the download: {again}")
        parties = await self.heads(current, self.harness.host)
        revisions = [(await self.launcher(w))["revision"] + 1 for w in current]
        return dict(parties=parties, revisions=revisions)
