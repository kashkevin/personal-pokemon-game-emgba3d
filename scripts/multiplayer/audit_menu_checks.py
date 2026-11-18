"""Real-game checks of PLAYERS' pages under repeated presses and of an accepted challenge a save ends (KNOWN_ISSUES
MS-69, MS-22), for native_launcher_challenge_proof.py --scenario menu-presses (two players, one Pokemon each).

Every press is an ordinary key press to the game's window; what each page showed and where each press landed is read
from the game's memory (the menu's screen and cursor) and recorded, with pictures:

  team      the host chooses Invite to team and presses A again at once and once more when the next page shows; the
            friend opens Team invitation, presses A at once (where the cursor stays), chooses Accept invitation and
            presses A again twice; then the host chooses Leave team... (the question: No first, B is No, a Yes in its
            first 0.6 s counts for nothing) and leaves.
  wager     the host challenges the friend to Rival Battle - 1v1, pressing A again twice; sets a wager (Propose this
            wager, A again twice); the friend opens the wager (Accept, A again twice), then Accept challenge with A again
            twice: the challenge never ends, each press lands on Enter battle (entering) or a row that does nothing;
            both enter, the battle is played to its end (the stake moves to the winner).
  save      (MS-22) the host challenges again, the friend accepts; the friend closes PLAYERS and saves in its game
            (START > SAVE, YES): both PLAYERS menus say "Cancelled: a party was saved"; then they challenge again,
            accept, enter and battle to the end.
"""
from __future__ import annotations

import asyncio
import json
import time

from native_launcher_battle_proof import game_picture, unpack_screen
from native_launcher_ffa_proof import A, B, DOWN, close_players, pose_of
from qualify_admission_cleanup import on_worker, require

MENU_ACTION_SAVE = 5            # engine src/start_menu.c
CANCELLED_SAVED = "Cancelled: a party was saved"


def labels(screen):
    return [r.label for r in screen.rows]


async def pick(*args, **options):
    from native_launcher_challenge_proof import pick as real      # imported late: that proof imports this module
    return await real(*args, **options)


async def shown(*args, **options):
    from native_launcher_challenge_proof import shown as real
    return await real(*args, **options)


class MenuAuditMixin:
    def screen_now(self, probe):
        row = probe.read()
        if not row["active"]:
            return dict(active=False)
        try:
            screen = unpack_screen(row["screen"], allow_trade_reopen=True, allow_battle_admission=True)[1]
        except ValueError:
            return dict(active=True, unreadable=True)
        return dict(active=True, waiting=bool(row["waiting"]), title=screen.title, status=screen.status,
                    rows=labels(screen), cursor=row["cursor"],
                    under_cursor=screen.rows[row["cursor"]].label if row["cursor"] < len(screen.rows) else None,
                    acts=bool(row["cursor"] < len(screen.rows) and screen.rows[row["cursor"]].action))

    async def picture(self, n, name):
        try:
            return await asyncio.to_thread(game_picture, self.harness.players[n].probe,
                                           self.harness.output / f"{name}.png", .3)
        except Exception as error:  # noqa: BLE001
            return f"no picture: {error!r}"

    async def settled_screen(self, probe, seconds=2.5):
        """The screen once the game takes input again (or `seconds` on: a window latched for a battle entry)."""
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            now = self.screen_now(probe)
            if now.get("active") and not now.get("waiting") and not now.get("unreadable"):
                return now
            await asyncio.sleep(.05)
        return self.screen_now(probe)

    async def choose_and_press_again(self, n, probes, record, label, page_label, again=2):
        """Choose `label` as a player does (cursor, A), then A again at once (a double press) and once more when the next
        page shows (the cursor where the game keeps it): each press's row and what came of it."""
        probe = probes[n]
        _, screen = await probe.ready(timeout=30)
        before = self.screen_now(probe)
        await probe.choose(label, wait=False)
        presses = []
        for k in range(again):
            if k == 0:
                landed = self.screen_now(probe)          # at once: the window may still wait for its answer
            else:
                await asyncio.sleep(1.0)
                landed = await self.settled_screen(probe)
            await probe.press(A)
            after = await self.settled_screen(probe)
            presses.append(dict(press=k + 2, on=landed.get("under_cursor"), row_acts=landed.get("acts"),
                                waiting=landed.get("waiting"), then=dict(title=after.get("title"),
                                                                         status=after.get("status"),
                                                                         rows=after.get("rows"))))
        await asyncio.sleep(1.0)
        final = await self.settled_screen(probe)
        record(page_label, player=self.harness.names[n], chose=label, page_before=before.get("title"),
               presses=presses, final=final, picture=await self.picture(n, page_label))
        return final

    async def host_view(self, current):
        async def read(s):
            server = s._server
            battles = [dict(battle_id=b.battle_id, state=b.state, reason=b.reason)
                       for b in list(server.battle_desk._active.values())]
            return dict(battles=battles)
        return await on_worker(current[0], read)

    async def menu_view(self, current, n):
        async def read(s):
            menu = s._companion._bridge.menu_session.menu
            return dict(battles=json.loads(json.dumps(menu._battles)) if menu._battles is not None else None,
                        team=json.loads(json.dumps(menu._team)) if menu._team is not None else None,
                        wager=json.loads(json.dumps(menu._wager)) if menu._wager is not None else None)
        return await on_worker(current[n], read)

    async def enter_both(self, current, probes, record, label):
        """Each player whose page offers Enter battle chooses it (one may have entered already with a repeated A)."""
        battles = await self.descriptors(current, (0, 1))
        async with asyncio.timeout(60):
            while True:
                pending = []
                for n in (0, 1):
                    now = self.screen_now(probes[n])
                    if now.get("active") and not now.get("waiting") and "Enter battle" in now.get("rows", ()):
                        pending.append(n)
                if pending or all(probes[n].read()["hold"] or not probes[n].read()["active"] for n in (0, 1)):
                    break
                await asyncio.sleep(.2)
        for n in pending:
            await probes[n].choose("Enter battle", wait=False)
        record(label, entered=[self.harness.names[n] for n in pending])
        return {b["battle_id"]: b for b in battles.values()}

    async def battle_to_the_end(self, current, probes, symbols, record, label):
        battles = await self.enter_both(current, probes, record, label + "-entered")
        if not await self.observe(current, probes, (0, 1), record, label + "-starting"):
            raise AssertionError(f"{label}: the battle did not start")
        stops, drivers = self.drive(current, probes, symbols, battles, (0, 1))
        await self.finish(current, probes, battles, (0, 1), stops, drivers, record, label)
        async with asyncio.timeout(120):
            while not all([(await self.state_of(w)).get("field") for w in current]):
                await asyncio.sleep(.5)
        record(label + "-both-back-on-the-field")

    async def in_game_save(self, n, current, probes, record, label):
        """START > SAVE, YES (and YES to overwrite), the text closed: the game's own save, which in a world is the host's
        save as well (MS-61); the launcher's revision moves on."""
        probe = probes[n]

        async def own(s):
            return s._companion
        companion = await on_worker(current[n], own)
        revision = (await self.launcher(current[n]))["revision"]
        await probe.press(8, release=60)
        async with asyncio.timeout(30):
            while True:
                row = probe.read()
                if 0 < row["count"] <= len(row["actions"]) and MENU_ACTION_SAVE in row["actions"][:row["count"]]:
                    break
                await asyncio.sleep(.1)
        actions = row["actions"][:row["count"]]
        for _ in range((actions.index(MENU_ACTION_SAVE) - row["start_cursor"]) % len(actions)):
            await probe.press(DOWN)
        require(probe.read()["start_cursor"] == actions.index(MENU_ACTION_SAVE), "the cursor did not reach SAVE")
        presses = 0
        started = time.monotonic()
        await probe.press(A, release=60)
        picture = None
        # YES is the dialog's default: A through "Would you like to save the game?", the overwrite question and the
        # closing text, until the field is back.
        while time.monotonic() - started < 40:
            await asyncio.sleep(1.2)
            pose = pose_of(companion)
            if presses == 1 and picture is None:
                picture = await self.picture(n, label + "-dialog")
            if pose is not None and pose[0] == 1 and presses >= 1:
                break
            await probe.press(A)
            presses += 1
        for _ in range(4):                        # anything an A opened on the field afterwards is closed again
            if (pose_of(companion) or (1,))[0] == 1:
                break
            await probe.press(B)
            await asyncio.sleep(1)
        async with asyncio.timeout(60):
            while (await self.launcher(current[n]))["revision"] <= revision:
                await asyncio.sleep(.5)
        record(label, player=self.harness.names[n], a_presses=presses + 1, picture=picture,
               revisions=[revision, (await self.launcher(current[n]))["revision"]],
               seconds=round(time.monotonic() - started, 1))

    # The scenario -------------------------------------------------------------------------------------------------
    async def menu_presses(self, current, probes, host, symbols, record):
        friend_name = host.accounts[1].display_name
        # Team pages
        await probes[0].open_players()
        await probes[0].choose(friend_name, prefix=True)
        final = await self.choose_and_press_again(0, probes, record, "Invite to team", "team-invite-presses")
        require(final.get("title") == "Your team" and any(r.startswith("Invited") for r in final.get("rows", ())),
                f"team: the invitation did not stay: {final}")
        await probes[1].open_players()
        _, home = await probes[1].ready()
        require("Team invitation" in labels(home), f"team: the friend has no invitation: {labels(home)}")
        final = await self.choose_and_press_again(1, probes, record, "Team invitation", "team-invitation-open-presses",
                                                  again=1)
        if final.get("title") == "Decline the invitation?":
            # the press that opened the page rested on Decline invitation...: it only asked; No (first) keeps it
            record("team-decline-asked-by-a-repeated-press", screen=final)
            await asyncio.sleep(1.0)
            await pick(probes[1], "No, keep it")
            final = await self.settled_screen(probes[1])
            record("team-decline-kept", screen=final)
        if "Accept invitation" in final.get("rows", ()):
            final = await self.choose_and_press_again(1, probes, record, "Accept invitation", "team-accept-presses")
        teams = await self.menu_view(current, 1)
        record("team-formed", team=teams["team"], friend_screen=final)
        require(teams["team"] and teams["team"]["team"] and host.accounts[0].player_id in teams["team"]["team"]["members"],
                f"team: no team was formed: {teams['team']}")
        for n in (0, 1):
            await close_players(probes[n])
        # Leave the team: the question first, No first; a Yes at once counts for nothing.
        await probes[0].open_players()
        await probes[0].choose("Your team")
        await probes[0].choose("Leave team...", wait=False)
        _, question = await self.question(probes[0], "Leave the team?")
        asked = self.screen_now(probes[0])
        await probes[0].press(A)               # where the cursor stayed: never Yes
        after_stray = await self.settled_screen(probes[0])
        record("team-leave-asked", question=asked, stray_press_then=after_stray,
               picture=await self.picture(0, "team-leave-question"))
        teams = await self.menu_view(current, 0)
        require(teams["team"] and teams["team"]["team"], f"team: a stray press on the question left the team: {teams}")
        if after_stray.get("title") != "Leave the team?":
            await pick(probes[0], "Leave team...")
            await self.question(probes[0], "Leave the team?")
        await asyncio.sleep(1.0)
        await pick(probes[0], "Yes, leave the team")
        await asyncio.sleep(2)
        teams = await self.menu_view(current, 0)
        record("team-left", team=teams["team"], screen=self.screen_now(probes[0]))
        require(not (teams["team"] and teams["team"]["team"]), f"team: could not leave: {teams['team']}")
        for n in (0, 1):
            await close_players(probes[n])
        # Challenge, wager, accept, with repeated presses
        await probes[0].open_players()
        await probes[0].choose(friend_name, prefix=True)
        final = await self.choose_and_press_again(0, probes, record, "Rival Battle - 1v1", "challenge-send-presses")
        require(any(r.startswith("Wager") for r in final.get("rows", ())) or "Enter battle: not yet" in final.get("rows", ()),
                f"challenge: the sender's page {final}")
        wager_row = next((r for r in final.get("rows", ()) if r.startswith("Wager")), None)
        if wager_row is not None:
            await probes[0].choose(wager_row)
            page = await self.settled_screen(probes[0])
            record("wager-page", screen=page)
            if "Propose this wager" not in page.get("rows", ()):
                # the press that opened the page rested on Propose (the challenge page's wager row's place)
                record("wager-proposed-by-the-opening-press", screen=page)
            else:
                def amount(rows, prefix):
                    row = next((r for r in rows if r.startswith(prefix)), "")
                    digits = "".join(ch for ch in row if ch.isdigit())
                    return int(digits) if digits else None
                for _ in range(6):        # an amount both can stake (the default is 5,000)
                    rows = self.screen_now(probes[0]).get("rows", ())
                    money, stake = amount(rows, "Your money"), amount(rows, "Amount")
                    if money is None or stake is None or stake <= money:
                        break
                    await probes[0].choose(next(r for r in rows if r.startswith("Amount")))
                final = await self.choose_and_press_again(0, probes, record, "Propose this wager", "wager-propose-presses")
            await probes[0].choose("Back to challenge")
        await probes[1].open_players()
        await probes[1].choose("Pending challenge")
        page = self.screen_now(probes[1])
        wager_row = next((r for r in page.get("rows", ()) if r.startswith("Wager")), None)
        if wager_row is not None:
            await probes[1].choose(wager_row)
            accept = next(r for r in self.screen_now(probes[1])["rows"] if r.startswith("Accept "))
            await self.choose_and_press_again(1, probes, record, accept, "wager-accept-presses")
            await probes[1].choose("Back to challenge")
        final = await self.choose_and_press_again(1, probes, record, "Accept challenge", "challenge-accept-presses")
        await asyncio.sleep(2)
        view = await self.host_view(current)
        record("challenge-after-the-presses", host=view, friend=self.screen_now(probes[1]),
               host_screen=self.screen_now(probes[0]), menus=await self.menu_view(current, 1))
        require(view["battles"] and all(b["state"] in ("accepted", "starting", "running") for b in view["battles"]),
                f"challenge: the presses ended the challenge: {view}")
        await self.battle_to_the_end(current, probes, symbols, record, "wager-1v1")
        # MS-22: a save after accepting
        await asyncio.sleep(3)
        await self.challenge_and_accept(host, probes)
        record("save-challenge-accepted", host=await self.host_view(current), host_screen=self.screen_now(probes[0]))
        await close_players(probes[1])
        await self.in_game_save(1, current, probes, record, "save-after-accepting")
        started = time.monotonic()
        host_statuses = []
        # The host's PLAYERS stayed open on the challenge page (an Enter page is never refreshed underneath,
        # MenuSession._poll): watched for 6 s, then the host presses Enter battle as a waiting player would.
        while time.monotonic() - started < 6:
            now = self.screen_now(probes[0])
            if not host_statuses or host_statuses[-1] != now.get("status"):
                host_statuses.append(now.get("status"))
            await asyncio.sleep(.25)
        host_entered = False
        if CANCELLED_SAVED not in host_statuses and "Enter battle" in self.screen_now(probes[0]).get("rows", ()):
            await probes[0].choose("Enter battle", wait=False)
            host_entered = True
            until = time.monotonic() + 20
            while time.monotonic() < until:
                now = self.screen_now(probes[0])
                if not host_statuses or host_statuses[-1] != now.get("status"):
                    host_statuses.append(now.get("status"))
                if now.get("status") == CANCELLED_SAVED and not now.get("waiting"):
                    break
                await asyncio.sleep(.25)
        host_status = self.screen_now(probes[0]).get("status")
        host_seconds = round(time.monotonic() - started, 1)
        host_picture = await self.picture(0, "save-cancelled-host-menu")
        await probes[1].open_players()
        _, home = await probes[1].ready()
        friend_status = home.status
        friend_picture = await self.picture(1, "save-cancelled-friend-menu")
        record("save-cancelled-the-challenge", host_status=host_status, host_statuses=host_statuses,
               host_pressed_enter=host_entered, host_seconds_after_the_save=host_seconds,
               friend_status=friend_status, friend_rows=labels(home), host_screen=self.screen_now(probes[0]),
               host=await self.host_view(current), pictures=[host_picture, friend_picture])
        require(host_status == CANCELLED_SAVED and friend_status == CANCELLED_SAVED,
                f"MS-22: the menus said {host_status!r} and {friend_status!r}")
        for n in (0, 1):
            await close_players(probes[n])
        await asyncio.sleep(2)
        await self.challenge_and_accept(host, probes)
        record("challenged-again-after-the-save")
        await self.battle_to_the_end(current, probes, symbols, record, "rematch-1v1")
        parties = await self.host_parties(host, current)
        revisions = [(await self.launcher(w))["revision"] for w in current]
        record("menu-presses-done", revisions=revisions)
        return dict(parties=parties, revisions=[revision + 1 for revision in revisions])

    async def question(self, probe, title, timeout=30):
        async with asyncio.timeout(timeout):
            while True:
                row, screen = await shown(probe)
                if screen.title == title:
                    return row, screen
                await asyncio.sleep(.1)
