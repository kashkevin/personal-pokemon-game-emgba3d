"""Four native games through the whole launcher: a battle interrupted by a crash, an exit, a lost connection or a host crash.

The owner's request of 2026-10-19 (KNOWN_ISSUES MS-16): if any player disconnects, crashes, closes the game or loses
the connection during a multiplayer battle, nobody may be stuck. The players who remain can abandon the interrupted
battle (no winner, no loser, no wager, no progression), get their own game back on the field with the party of their
last verified save, and the player who left comes back with the same character. The launcher harness of
native_launcher_battle_proof.py (real LauncherWindow, SessionWorker and LauncherSession per player, production world
creation and enrollment, the real world server and store) runs four native games, one per X display, driven by
ordinary key presses. Scenarios (--scenario):

    pairs-crash      Two 1v1 battles at the same time (host vs Friend 1, Friend 2 vs Friend 3). Friend 3's game is
                     killed (SIGKILL) during the battle. The host and Friend 1 finish their battle (a result). Friend 2
                     abandons from the launcher; Friend 3 starts the launcher again. Then Friend 2 and Friend 3 battle
                     each other again to the end.
    multi-network    A 2v2 (host and Friend 1 against Friends 2 and 3). Friend 1's connection to the world is cut
                     during the battle (its game keeps running). The host abandons from the launcher; Friends 2 and 3
                     are resolved by their launchers without doing anything; Friend 1 abandons (its launcher reconnects
                     for that). Then the same 2v2 is played again to the end.
    ffa-host-crash   A free-for-all. The host's game is killed and every connection of the host is cut during the
                     battle, then the host's launcher winds down. The host starts the launcher again (the world
                     reopens), Friends 1 and 2 abandon from the launcher, Friend 3 closes its game and starts the
                     launcher again. Then the host and Friend 3 battle 1v1 to the end.
    ffa-exit         A free-for-all. Friend 2 closes its game during the battle (SIGTERM, which SDL turns into the
                     same quit as closing the window; the harness's ordinary close on Linux). Friend 2 starts the
                     launcher again, which abandons the battle as it opens the world; the other three launchers follow
                     by themselves. Then the same four play a free-for-all again to the end.

Every scenario then checks: everyone back on the field, linked to the other three ("Connected: 4/4"), every party the
one from before the battle, no pending battle intent anywhere, the abandoned battle has no result (no archive entry, no
free-for-all book entry) and its durable reservation is closed as abandoned; the harness's own end follows (all save,
the saves' money, items, flags and variables unchanged from before the battle, the store's integrity check, a normal
close, a fresh Continue onto the same saves).

On a build without the abandon option (the code before the MS-16 fix) the run records what the players get instead and
ends with "MS-16 reproduced": that is how the failure was reproduced before the fix.

    PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime \\
      python scripts/multiplayer/native_launcher_abandon_proof.py --scenario pairs-crash \\
        --game ../engine/pokeemerald-mp --rom pokedev.gba --manifest manifest.json \\
        --source a.sav --source b.sav --source c.sav --source d.sav \\
        --display :94 --display :95 --display :96 --display :97 \\
        --output /private/multiplayer-proof/abandon-pairs-1
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows-runtime"))
from native_launcher_battle_proof import Player, drive_battle_input, launcher_proof  # noqa: E402
from native_launcher_ffa_proof import close_players, into_littleroot, players_tab, pose_of, save_regions  # noqa: E402
from qualify_admission_cleanup import on_worker, require  # noqa: E402
from qualify_launcher_session import inspect_closed_head  # noqa: E402

PLAYER_NAMES = ("AB Host", "AB Friend 1", "AB Friend 2", "AB Friend 3")
SCENARIOS = ("pairs-crash", "multi-network", "ffa-host-crash", "ffa-exit")
PENDING = ("pending-battle.json", "pending-battle-admission.json")


class Reproduced(AssertionError):
    """The build has no way out of the interrupted battle (MS-16)."""


class AbandonProof:
    def __init__(self, scenario, interrupt_after, watch, match_seconds):
        self.scenario, self.interrupt_after, self.watch = scenario, interrupt_after, watch
        self.match_seconds = match_seconds
        self.harness = None
        self.before_saves = None
        self.thread_slot = {}

    def adopt(self, harness):
        """One machine stands in for four PCs: a game a launcher starts again by itself (after abandoning) opens on
        that player's own display. The harness sets the display only when it starts a launcher; this wrapper picks it
        by the launcher's worker thread. Display plumbing only; nothing else of the spawn changes."""
        self.harness = harness
        real = asyncio.create_subprocess_exec

        async def spawn(program, *arguments, **options):
            slot = self.thread_slot.get(threading.get_ident())
            if slot is not None and "env" not in options:
                options["env"] = dict(os.environ, DISPLAY=harness.args.display[slot])
            return await real(program, *arguments, **options)
        asyncio.create_subprocess_exec = spawn

    def own_display(self, n, worker):
        thread = getattr(worker, "_thread", None)
        if thread is not None and thread.ident is not None:
            self.thread_slot[thread.ident] = n

    # Observations -----------------------------------------------------------------------------------------------
    @staticmethod
    async def session(s):
        c = s._companion
        pose = pose_of(c)
        return dict(code=s.status.code, connected=c.connected, epoch=c.session_epoch, game_link=c._bridge is not None,
                    roster=len(c._players), field=pose is not None and pose[0] == 1, can_save=bool(s.can_save),
                    abandon_offered=bool(getattr(s.status, "battle_abandon_available", False)),
                    recovery_offered=bool(getattr(s.status, "battle_recovery_available", False)),
                    game_pid=None if s._game is None else s._game.process.pid, pose=pose)

    async def state_of(self, worker):
        try:
            return await on_worker(worker, self.session)
        except RuntimeError as error:                       # the worker's session has ended
            return dict(code=getattr(worker, "_status_code", None), ended=str(error))

    @staticmethod
    def host_fate(battle_id):
        async def read(s):
            server = s._server
            desk = server.battle_desk
            battle = desk._active.get(battle_id) or desk._history.get(battle_id)
            room = server.battle_execution.rooms.get(battle_id) if server.battle_execution is not None else None
            row = s._store._connection.execute("SELECT terminal_kind FROM battle_reservations WHERE battle_id=?",
                                               (battle_id,)).fetchone()
            directory = server.battle_execution.directory if server.battle_execution is not None else None
            record = None if directory is None else directory / (battle_id + ".abandoned.json")
            history = server._battle_results.get(battle_id) if server._battle_results is not None else None
            ffa = server.shared_world.ffa.result(battle_id)
            return dict(desk=None if battle is None else battle.state, reason=None if battle is None else battle.reason,
                        room=None if room is None else room.state,
                        reservation=None if row is None else (row["terminal_kind"] or "unresolved"),
                        abandonment_record=record is not None and record.exists(),
                        result=None if history is None else dict(outcome=history["outcome"], players=history["players"]),
                        ffa_result=ffa)
        return read

    def players(self):
        return self.harness.players

    # Menus --------------------------------------------------------------------------------------------------------
    async def challenge_1v1(self, host, probes, sender, recipient):
        await probes[sender].open_players()
        await probes[sender].choose(host.accounts[recipient].display_name, prefix=True)
        await probes[sender].choose("Challenge 1v1")
        await probes[recipient].open_players()
        await probes[recipient].choose("Pending challenge")
        await probes[recipient].choose("Accept challenge")

    async def form_teams(self, host, current, probes, record):
        for sender, recipient in ((0, 1), (2, 3)):
            await probes[sender].open_players()
            await probes[sender].choose(host.accounts[recipient].display_name, prefix=True)
            await probes[sender].choose("Invite to team")
            await probes[recipient].open_players()
            await probes[recipient].choose("Team invitation")
            await probes[recipient].choose("Accept invitation")
            await close_players(probes[sender])
            await close_players(probes[recipient])
        record("teams-formed", teams=[[0, 1], [2, 3]])

    async def challenge_2v2(self, probes):
        await probes[0].open_players()
        await probes[0].choose("Your team")
        await probes[0].choose("Challenge other team 2v2")
        for probe in probes[1:]:
            await probe.open_players()
            await probe.choose("Pending challenge")
            await probe.choose("Accept challenge")

    async def challenge_ffa(self, probes):
        await probes[0].open_players()
        await probes[0].choose("Challenges")
        await probes[0].choose("Free-for-all 1v1v1v1")
        for probe in probes[1:]:
            await probe.open_players()
            await probe.choose("Pending challenge")
            await probe.choose("Accept challenge")

    async def descriptors(self, current, slots):
        async def descriptor(s):
            values = s._companion._bridge.menu_session.menu._battles
            require(len(values) == 1 and values[0]["state"] == "accepted", f"expected one accepted challenge: {values}")
            return json.loads(json.dumps(values[0]))
        return {n: await on_worker(current[n], descriptor) for n in slots}

    async def enter(self, current, probes, slots, record, label):
        async with asyncio.timeout(60):
            while not all(screen.admission_action for _, screen in [await probes[n].ready() for n in slots]):
                await asyncio.sleep(.05)
        found = await self.descriptors(current, slots)
        battles = {}
        for n, value in found.items():
            battles.setdefault(value["battle_id"], value)
            require(battles[value["battle_id"]] == value, "two players of one battle see different challenges")
        await asyncio.gather(*(probes[n].choose("Enter battle", wait=False) for n in slots))
        for battle_id, value in battles.items():
            record("entered-" + label, battle_id=battle_id, mode=value["mode"],
                   players=[self.harness.names[self.index(value, p)] for p in value["players"]])
        return battles

    def index(self, challenge, player_id):
        return [a.player_id for a in self.harness.host.accounts].index(player_id)

    def drive(self, current, probes, symbols, battles, slots):
        """One input driver per game; each reads its own battle's room on the host."""
        stops, drivers = {}, {}
        for n in slots:
            battle = next(b for b in battles.values() if self.harness.host.accounts[n].player_id in b["players"])
            slot = battle["players"].index(self.harness.host.accounts[n].player_id)

            async def view(battle_id=battle["battle_id"], slot=slot):
                async def read(s):
                    room = s._server.battle_execution.rooms.get(battle_id)
                    if room is None:
                        return dict(state="waiting", pending=None)
                    return dict(state=room.state, pending=None if room.route is None else room.route.validator.pending[slot])
                try:
                    return await on_worker(current[0], read)
                except RuntimeError:
                    return dict(state="recovery_required", pending=None)   # the host is gone
            stops[n] = asyncio.Event()
            drivers[n] = asyncio.create_task(drive_battle_input(probes[n], view, symbols, stops[n]))
        return stops, drivers

    async def finish(self, current, probes, battles, slots, stops, drivers, record, label):
        """The battle(s) of these players run to their end; each launcher reports battle_finished."""
        async def finished(s):
            if s._game is None or s._game.process.returncode is not None:
                raise AssertionError(f"launcher lost its game: {s.status.code}")
            return s.status.code == "battle_finished" and s.can_save and s._interaction is None
        started = time.monotonic()
        try:
            async with asyncio.timeout(self.match_seconds):
                report_at = 0
                while True:
                    for n in slots:
                        if drivers[n].done():
                            await drivers[n]
                    if all([await on_worker(current[n], finished) for n in slots]):
                        break
                    if time.monotonic() >= report_at:
                        record(label + "-progress", elapsed=round(time.monotonic() - started))
                        report_at = time.monotonic() + 60
                    await asyncio.sleep(.2)
        finally:
            for n in slots:
                stops[n].set()
            await asyncio.gather(*(drivers[n] for n in slots))
        results = {}
        for battle_id, challenge in battles.items():
            if not any(self.harness.host.accounts[n].player_id in challenge["players"] for n in slots):
                continue
            fate = await on_worker(current[0], self.host_fate(battle_id))
            require(fate["reservation"] == "closed", f"{label}: the battle did not close: {fate}")
            results[battle_id] = fate["result"] or fate["ffa_result"]
            require(results[battle_id] is not None, f"{label}: no durable result: {fate}")
            record(label + "-result", battle_id=battle_id, seconds=round(time.monotonic() - started),
                   outcome=results[battle_id]["outcome"])
        return results

    # Interruptions -------------------------------------------------------------------------------------------------
    async def interrupt(self, kind, slot, current, games, record):
        harness = self.harness
        if kind in ("crash", "exit"):
            os.kill(games[slot].process.pid, signal.SIGKILL if kind == "crash" else signal.SIGTERM)
            await harness.poll_until(lambda: games[slot].process.returncode is not None, 60)
            record("game-" + ("killed" if kind == "crash" else "closed") + "-during-the-battle", slot=slot,
                   exit_code=games[slot].process.returncode)
        elif kind == "network":
            async def cut(s):
                writer = s._companion._remote_writer
                require(writer is not None, "no world connection to cut")
                writer.transport.abort()                  # a cable pulled: no goodbye, the socket just dies
            await on_worker(current[slot], cut)
            record("connection-cut-during-the-battle", slot=slot)
        elif kind == "host-crash":
            async def crash(s):
                server = s._server
                os.kill(s._game.process.pid, signal.SIGKILL)
                for writer in list(server._connections):
                    writer.transport.abort()
                if server._server is not None:
                    server._server.close()
                writer = s._companion._remote_writer
                if writer is not None:
                    writer.transport.abort()
            await on_worker(current[0], crash)
            await harness.poll_until(lambda: games[0].process.returncode is not None, 60)
            record("host-crashed-during-the-battle", exit_code=games[0].process.returncode)
        else:
            raise ValueError(kind)

    async def watch_after(self, current, slots, battle_id, record, seconds):
        started = time.monotonic()
        states = {}
        while True:
            states = {n: await self.state_of(current[n]) for n in slots}
            fate = None
            try:
                fate = await on_worker(current[0], self.host_fate(battle_id))
            except RuntimeError:
                pass
            record("after-the-interruption", seconds=round(time.monotonic() - started), host_battle=fate,
                   players={self.harness.names[n]: v for n, v in states.items()})
            if all(v.get("abandon_offered") for v in states.values()) or time.monotonic() - started >= seconds:
                return states
            await asyncio.sleep(10)

    # Ways back -----------------------------------------------------------------------------------------------------
    def supported(self, worker):
        return callable(getattr(worker, "request_battle_abandon", None))

    async def abandon_from(self, n, current, probes, games, record, *, explicit=True, timeout=240):
        """The player's launcher abandons (explicitly, or by itself) and restarts the game in the same session."""
        harness, worker = self.harness, current[n]
        old_pid = games[n].process.pid
        if explicit:
            async with asyncio.timeout(120):
                while not (await self.state_of(worker)).get("abandon_offered"):
                    await asyncio.sleep(.5)
            require(worker.request_battle_abandon(), f"{harness.names[n]}: the launcher refused to abandon")
            record("abandon-chosen", slot=n)

        async def new_game(s):
            game = s._game
            return None if game is None or game.process.returncode is not None or game.process.pid == old_pid else (
                game, s.profile_directory / "character.sav", s._companion)
        async with asyncio.timeout(timeout):
            while True:
                found = await on_worker(worker, new_game)
                if found is not None:
                    break
                await asyncio.sleep(.25)
        game, mirror, companion = found
        harness.children.append(game.process)
        probe = await harness.boot_until_field(companion, game.process, n)
        player = Player(n, worker, game, probe, mirror, companion)
        revision = await harness.ready(player)
        harness.players[n] = player
        games[n], probes[n] = game, probe
        state = await self.state_of(worker)
        record("back-on-the-field-after-abandoning", slot=n, explicit=explicit, revision=revision,
               old_pid=old_pid, new_pid=game.process.pid, code=state["code"], epoch=state["epoch"])
        return player

    async def rejoin(self, n, current, probes, games, record):
        """The launcher is started again for this player (its earlier game is gone)."""
        harness = self.harness
        if games[n].process.returncode is None:
            os.kill(games[n].process.pid, signal.SIGTERM)
            await harness.poll_until(lambda: games[n].process.returncode is not None, 60)
            record("closed-a-held-game", slot=n, exit_code=games[n].process.returncode)
        await harness.poll_until(lambda: not current[n].busy, 180)
        try:
            again = await harness.start("rejoin", n)
        except AssertionError:
            worker = harness.workers[-1]
            await harness.poll_until(lambda: not worker.busy, 60)
            codes = []                            # every status the refused launcher showed, in order
            while True:
                try:
                    event = worker.events.get_nowait()
                except Exception:                 # noqa: BLE001 - queue.Empty
                    break
                codes.append(f"{event.kind}:{event.code}")
            code = next((c.split(":", 1)[1] for c in reversed(codes) if c.split(":", 1)[1] not in ("closed", "new")),
                        getattr(worker, "_status_code", None))
            shown = harness.windows[-1].message.get() if harness.windows else None   # what the player reads
            record("rejoin-refused", slot=n, status=code, statuses=codes, shown=shown)
            raise Reproduced(f"{harness.names[n]} cannot open the world again after the interrupted battle "
                             f"(launcher status {code})") from None
        self.own_display(n, again.worker)
        revision = await harness.ready(again)
        harness.players[n] = again
        current[n], games[n], probes[n] = again.worker, again.game, again.probe
        record("rejoined", slot=n, pid=again.game.process.pid, revision=revision)
        return again

    async def reproduce(self, current, games, held, record):
        """No abandon option: what the players can still do (close the game, start again) is tried and recorded."""
        for n in held:
            record("no-abandon-option", slot=n, state=await self.state_of(current[n]))

    # Checks --------------------------------------------------------------------------------------------------------
    async def world_is_whole(self, current, probes, before, record, label):
        async with asyncio.timeout(180):
            while True:
                states = [await self.state_of(w) for w in current]
                if all(v.get("connected") and v.get("game_link") and v.get("roster") == 4 and v.get("field")
                       for v in states):
                    break
                await asyncio.sleep(.5)
        for index, probe in enumerate(probes):
            status, rows = await players_tab(probe)
            require(status == "Connected: 4/4", f"player {index}'s PLAYERS: {status} {rows}")
        for index, probe in enumerate(probes):
            now = await probe.battle()
            require(now["count"] == before[index]["count"] and now["party_sha256"] == before[index]["party_sha256"],
                    f"player {index}'s party is not the one from before the battle")

        async def clean(s):
            left = [name for name in PENDING if (s.profile_directory / name).exists()]
            waiting = (await s._companion.battle_challenge_rpc("waiting"))["result"]
            return dict(pending_files=left, waiting=waiting, retained=s._battle_retained is not None)
        leftovers = [await on_worker(w, clean) for w in current]
        require(all(not v["pending_files"] and not v["waiting"] and not v["retained"] for v in leftovers),
                f"a battle still holds somebody: {leftovers}")
        record(label, sessions=[v["epoch"] for v in states], parties="as before the battle",
               players=[self.harness.names[n] for n in range(4)])

    async def abandoned(self, current, battle_id, record):
        fate = await on_worker(current[0], self.host_fate(battle_id))
        require(fate["reservation"] in ("aborted", None) and fate["result"] is None and fate["ffa_result"] is None
                and (fate["reservation"] is None or fate["abandonment_record"]),
                f"the interrupted battle was not abandoned without a result: {fate}")

        async def wager(s):
            return s._server.wagers.view(battle_id)
        record("battle-abandoned-without-a-result", battle_id=battle_id, host_battle=fate,
               wager=await on_worker(current[0], wager))
        return fate

    # Scenarios -----------------------------------------------------------------------------------------------------
    async def match(self, current, probes, games, host, symbols, record):
        async def saves(s):
            return [save_regions(inspect_closed_head(s._store, a.player_id)) for a in host.accounts]
        self.before_saves = await on_worker(current[0], saves)
        for n, worker in enumerate(current):
            self.own_display(n, worker)
        before_sessions = [await self.state_of(w) for w in current]
        require(all(v["connected"] and v["game_link"] and v["roster"] == 4 for v in before_sessions),
                f"not everyone is in the session: {before_sessions}")
        for index, probe in enumerate(probes):
            status, rows = await players_tab(probe)
            require(status == "Connected: 4/4", f"player {index}'s PLAYERS: {status} {rows}")
        record("everyone-linked-before-the-battle", sessions=[v["epoch"] for v in before_sessions])
        before = [await probe.battle() for probe in probes]
        scenario = getattr(self, self.scenario.replace("-", "_"))
        try:
            await scenario(current, probes, games, host, symbols, record, before)
        except Reproduced as error:
            record("MS-16-reproduced", reason=str(error))
            raise
        finally:
            # Later phases start new launchers, whose worker threads can reuse these idents: the harness's own
            # display choice applies to them again.
            self.thread_slot.clear()
        return None

    async def pairs_crash(self, current, probes, games, host, symbols, record, before):
        await self.challenge_1v1(host, probes, 0, 1)
        await self.challenge_1v1(host, probes, 2, 3)
        battles = await self.enter(current, probes, range(4), record, "two-1v1-battles")
        stops, drivers = self.drive(current, probes, symbols, battles, range(4))
        await asyncio.sleep(self.interrupt_after)
        interrupted = next(b for b, v in battles.items() if host.accounts[3].player_id in v["players"])
        stops[3].set()
        await drivers[3]
        await self.interrupt("crash", 3, current, games, record)
        finished = await self.finish(current, probes, battles, (0, 1), stops, drivers, record, "uninterrupted-1v1")
        record("the-other-battle-finished-normally", results=finished)
        await drivers[2]
        states = await self.watch_after(current, (2,), interrupted, record, self.watch)
        if not self.supported(current[2]):
            await self.reproduce(current, games, (2,), record)
            await self.rejoin(3, current, probes, games, record)
            await self.rejoin(2, current, probes, games, record)
            raise Reproduced("the build has no abandon option")
        await self.abandon_from(2, current, probes, games, record)
        await self.rejoin(3, current, probes, games, record)
        await self.abandoned(current, interrupted, record)
        await self.world_is_whole(current, probes, before, record, "everyone-back-after-the-crash")
        # The two who were in the abandoned battle battle each other again, to the end.
        await self.challenge_1v1(host, probes, 2, 3)
        again = await self.enter(current, probes, (2, 3), record, "rematch-1v1")
        stops, drivers = self.drive(current, probes, symbols, again, (2, 3))
        await self.finish(current, probes, again, (2, 3), stops, drivers, record, "rematch-1v1")
        await self.world_is_whole(current, probes, before, record, "everyone-back-after-the-rematch")

    async def multi_network(self, current, probes, games, host, symbols, record, before):
        await self.form_teams(host, current, probes, record)
        await self.challenge_2v2(probes)
        battles = await self.enter(current, probes, range(4), record, "2v2")
        battle_id = next(iter(battles))
        stops, drivers = self.drive(current, probes, symbols, battles, range(4))
        await asyncio.sleep(self.interrupt_after)
        await self.interrupt("network", 1, current, games, record)
        for n in range(4):
            stops[n].set()
        await asyncio.gather(*drivers.values())
        await self.watch_after(current, range(4), battle_id, record, self.watch)
        if not self.supported(current[0]):
            await self.reproduce(current, games, range(4), record)
            for n in (1, 2, 3, 0):
                await self.rejoin(n, current, probes, games, record)
            raise Reproduced("the build has no abandon option")
        await self.abandon_from(0, current, probes, games, record)
        for n in (2, 3):                                        # nobody touches these two launchers
            await self.abandon_from(n, current, probes, games, record, explicit=False)
        await self.abandon_from(1, current, probes, games, record)
        await self.abandoned(current, battle_id, record)
        await self.world_is_whole(current, probes, before, record, "everyone-back-after-the-lost-connection")
        # A team lasts as long as both members' connections (team_desk.py); every restarted game came back on a new
        # world session, so the players team up again before the rematch.
        async def teams(s):
            s._server.team_desk.refresh()
            return len(s._server.team_desk._teams)
        record("teams-after-the-abandoned-battle", teams=await on_worker(current[0], teams))
        await self.form_teams(host, current, probes, record)
        await self.challenge_2v2(probes)
        again = await self.enter(current, probes, range(4), record, "rematch-2v2")
        stops, drivers = self.drive(current, probes, symbols, again, range(4))
        await self.finish(current, probes, again, range(4), stops, drivers, record, "rematch-2v2")
        await self.world_is_whole(current, probes, before, record, "everyone-back-after-the-rematch")

    async def ffa_host_crash(self, current, probes, games, host, symbols, record, before):
        await self.challenge_ffa(probes)
        battles = await self.enter(current, probes, range(4), record, "free-for-all")
        battle_id = next(iter(battles))
        stops, drivers = self.drive(current, probes, symbols, battles, range(4))
        await asyncio.sleep(self.interrupt_after)
        for n in range(4):
            stops[n].set()
        await asyncio.gather(*drivers.values())
        await self.interrupt("host-crash", 0, current, games, record)
        await self.harness.poll_until(lambda: not current[0].busy, 180)
        record("host-launcher-wound-down", status=getattr(current[0], "_status_code", None))
        await self.watch_after(current, (1, 2, 3), battle_id, record, 30)
        await self.rejoin(0, current, probes, games, record)    # the world reopens with the host's own character
        if not self.supported(current[1]):
            raise Reproduced("the build has no abandon option")
        for n in (1, 2):
            await self.abandon_from(n, current, probes, games, record)
        await self.rejoin(3, current, probes, games, record)
        await self.abandoned(current, battle_id, record)
        await self.world_is_whole(current, probes, before, record, "everyone-back-after-the-host-crash")
        await self.challenge_1v1(host, probes, 0, 3)
        again = await self.enter(current, probes, (0, 3), record, "rematch-1v1")
        stops, drivers = self.drive(current, probes, symbols, again, (0, 3))
        await self.finish(current, probes, again, (0, 3), stops, drivers, record, "rematch-1v1")
        await self.world_is_whole(current, probes, before, record, "everyone-back-after-the-rematch")

    async def ffa_exit(self, current, probes, games, host, symbols, record, before):
        await self.challenge_ffa(probes)
        battles = await self.enter(current, probes, range(4), record, "free-for-all")
        battle_id = next(iter(battles))
        stops, drivers = self.drive(current, probes, symbols, battles, range(4))
        await asyncio.sleep(self.interrupt_after)
        for n in range(4):
            stops[n].set()
        await asyncio.gather(*drivers.values())
        await self.interrupt("exit", 2, current, games, record)
        await self.harness.poll_until(lambda: not current[2].busy, 180)
        record("launcher-after-the-exit", slot=2, status=getattr(current[2], "_status_code", None))
        await self.watch_after(current, (0, 1, 3), battle_id, record, 30)
        if not self.supported(current[0]):
            await self.reproduce(current, games, (0, 1, 3), record)
            await self.rejoin(2, current, probes, games, record)
            raise Reproduced("the build has no abandon option")
        # The player who closed the game starts the launcher again; it abandons the battle as it opens the world,
        # and the other three launchers follow by themselves.
        await self.rejoin(2, current, probes, games, record)
        for n in (0, 1, 3):
            await self.abandon_from(n, current, probes, games, record, explicit=False)
        await self.abandoned(current, battle_id, record)
        await self.world_is_whole(current, probes, before, record, "everyone-back-after-the-exit")
        await self.challenge_ffa(probes)
        again = await self.enter(current, probes, range(4), record, "rematch-free-for-all")
        stops, drivers = self.drive(current, probes, symbols, again, range(4))
        await self.finish(current, probes, again, range(4), stops, drivers, record, "rematch-free-for-all")
        await self.world_is_whole(current, probes, before, record, "everyone-back-after-the-rematch")

    async def after_save(self, current, host, record):
        async def saves(s):
            return [save_regions(inspect_closed_head(s._store, a.player_id)) for a in host.accounts]
        after = await on_worker(current[0], saves)
        for slot, (old, new) in enumerate(zip(self.before_saves, after)):
            require(new["revision"] == old["revision"] + 1, f"slot {slot}: revision {old['revision']} -> {new['revision']}")
            for field in ("money", "coins", "registered", "items"):
                require(new[field] == old[field], f"slot {slot}: {field} changed: {old[field]} -> {new[field]}")
            require(new["flags_and_vars"] == old["flags_and_vars"], f"slot {slot}: flags or variables changed")
        record("items-and-progression-unchanged", revisions=[[o["revision"], n["revision"]] for o, n in
                                                            zip(self.before_saves, after)],
               money=[n["money"] for n in after], items=[len(n["items"]) for n in after])


async def run(args):
    require(len(args.source) == 4, "four sources, one per player")
    proof = AbandonProof(args.scenario, args.interrupt_after, args.watch, args.match_seconds)
    await launcher_proof(args, names=PLAYER_NAMES, sources=args.source, party_counts=(1,) * 4, match=proof.match,
                         version="Native interrupted battle proof", settings="windowScale=2\n",
                         scope=__doc__.split("\n\n")[0] + " Scenario: " + args.scenario,
                         after_boot=into_littleroot, after_save=proof.after_save,
                         environment=dict(SDL_FRAMEBUFFER_ACCELERATION="0"),
                         on_harness=proof.adopt)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", choices=SCENARIOS, required=True)
    parser.add_argument("--game", type=Path, required=True, help="native Linux executable, unstripped")
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source", type=Path, action="append", required=True, help="a save per player (four)")
    parser.add_argument("--display", action="append", required=True, help="an X display per player (four)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0)
    parser.add_argument("--interrupt-after", type=float, default=60, help="seconds into the battle")
    parser.add_argument("--watch", type=float, default=90, help="how long to watch the others after the interruption")
    parser.add_argument("--match-seconds", type=float, default=1800)
    parser.add_argument("--wine", type=Path, action="append", help="(not used by this proof)")
    parser.add_argument("--sdl", type=Path)
    parser.add_argument("--elf", type=Path)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
