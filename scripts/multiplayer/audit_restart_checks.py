"""Real-game check of a World Event action made first by a game the launcher started again in its session (KNOWN_ISSUES
M21), for native_launcher_newcomers_proof.py --scenario restart-look (two players with a Pokemon each).

The host's player saves a look in its game (START > PLAYER > STYLE: SKIN one step on, SAVE): the game posts its World
Event action, the companion forwards it and the host stores the look. A Rival 1v1 starts; the friend's game is killed
during it; the host's player abandons the interrupted battle from the launcher, which starts the host's game again in
the same launcher session (the same companion). The first World Event action of that new game is another look (SKIN one
more step): it must reach the host (its stored look becomes the new one) at once, not be taken for the earlier game's
acknowledged action and skipped. Each World Event action the companion meets is recorded (its number, kind, and the
companion's last sent and acknowledged numbers then); the friend joins again; the harness's closing saves follow.
"""
from __future__ import annotations

import asyncio
import subprocess
import time

from native_launcher_ffa_proof import A, DOWN, RIGHT
from qualify_admission_cleanup import on_worker, require

PLAYER_OPTIONS, STYLE = 15, 21          # engine src/start_menu.c: MENU_ACTION_PLAYER_OPTIONS, MENU_ACTION_STYLE
ROW_SKIN, ROW_SAVE = 1, 5               # include/character_customization.h: CC_EDITOR_ROW_SKIN, CC_EDITOR_ROW_SAVE


class RestartLookMixin:
    def appearance_symbols(self):
        found = {}
        for line in subprocess.run(["nm", "-S", str(self.harness.game)], capture_output=True, text=True,
                                   check=True).stdout.splitlines():
            parts = line.split()
            if len(parts) == 4 and parts[3] in ("sEditorCursor", "sEditorActive", "sPendingSave", "sLocal"):
                found.setdefault(parts[3], int(parts[0], 16))
        return found

    def editor(self, probe):
        where = self._appearance
        with open(f"/proc/{probe.pid}/mem", "rb", buffering=0) as memory:
            def read(name, size):
                memory.seek(where[name])
                return memory.read(size)
            return dict(active=read("sEditorActive", 1)[0], cursor=read("sEditorCursor", 1)[0],
                        pending=read("sPendingSave", 1)[0], local=read("sLocal", 8).hex())

    def watch_world_actions(self, companion, n):
        """Every World Event action the companion meets (its number and kind, the last sent and acknowledged numbers)."""
        if getattr(companion, "_audit_watched", False):
            return
        real = companion._spawn_world_action

        def spawn(action, _real=real, _c=companion):
            self.world_actions.append(dict(at=round(time.monotonic() - self.t0, 1), player=self.harness.names[n],
                                           companion=id(_c), seq=action.seq, kind=action.kind,
                                           last_sent=_c._world_action_sent, last_ack=_c._world_action_ack))
            return _real(action)
        companion._spawn_world_action = spawn
        companion._audit_watched = True

    async def host_look(self, current, n):
        player = self.harness.host.accounts[n].player_id

        async def read(s):
            return s._server.shared_world.appearance(player)
        return await on_worker(current[0], read)

    async def save_a_look(self, n, current, probes, record, label):
        probe = probes[n]
        companion = await self.companion_of(current[n])
        self.watch_world_actions(companion, n)

        def top(r):
            return 0 < r["count"] <= len(r["actions"]) and PLAYER_OPTIONS in r["actions"][:r["count"]]

        def submenu(r):
            return r["actions"][0] == 16 and STYLE in r["actions"][:r["count"]]
        await self.on_field(current[n], timeout=60)
        before = dict(host=await self.host_look(current, n), game=self.editor(probe),
                      sent=companion._world_action_sent, ack=companion._world_action_ack)
        await probe.press(8, release=60)
        await probe.snapshot(top, timeout=30)
        await probe.start_menu_row(top, PLAYER_OPTIONS, submenu)
        await probe.start_menu_row(submenu, STYLE, lambda r: self.editor(probe)["active"] == 1)
        await asyncio.sleep(1)
        for _ in range(8):
            if self.editor(probe)["cursor"] == ROW_SKIN:
                break
            await probe.press(DOWN)
        require(self.editor(probe)["cursor"] == ROW_SKIN, f"the STYLE editor's cursor did not reach SKIN: {self.editor(probe)}")
        await probe.press(RIGHT)
        for _ in range(8):
            if self.editor(probe)["cursor"] == ROW_SAVE:
                break
            await probe.press(DOWN)
        require(self.editor(probe)["cursor"] == ROW_SAVE, f"the STYLE editor's cursor did not reach SAVE: {self.editor(probe)}")
        picture = await self.picture(n, label + "-editor")
        pressed = time.monotonic()
        actions_before = len(self.world_actions)
        await probe.press(A)
        saved = self.editor(probe)
        look = saved["local"]
        async with asyncio.timeout(60):
            while (stored_look := await self.host_look(current, n)) in (before["host"], None) and stored_look != look:
                await asyncio.sleep(.1)
        stored = round(time.monotonic() - pressed, 2)
        async with asyncio.timeout(30):
            while self.editor(probe)["pending"]:
                await asyncio.sleep(.1)
        confirmed = round(time.monotonic() - pressed, 2)
        record(label, player=self.harness.names[n], game_pid=probe.pid, before=before, saved_look=look,
               host_look_now=await self.host_look(current, n),
               host_stored_after_seconds=stored, game_confirmed_after_seconds=confirmed,
               actions=self.world_actions[actions_before:], companion=id(companion),
               after=dict(sent=companion._world_action_sent, ack=companion._world_action_ack), picture=picture)
        return look

    async def restart_look(self, current, probes, games, symbols, record):
        host = self.harness.host
        self.world_actions = []
        self._appearance = self.appearance_symbols()
        await self.save_all(current, record, "saved-before-the-looks")
        first = await self.save_a_look(0, current, probes, record, "look-saved-in-the-first-game")
        companion_before = await self.companion_of(current[0])
        # An interrupted Rival 1v1: the friend's game is killed during it; the host abandons it.
        await self.challenge_1v1(host, probes, 0, 1)
        battles = await self.enter(current, probes, (0, 1), record, "1v1-to-interrupt")
        battle_id = next(iter(battles))
        stops, drivers = self.drive(current, probes, symbols, battles, (0, 1))
        async with asyncio.timeout(120):
            while self.seen[1].get("presses", 0) < 3:
                await asyncio.sleep(.1)
        stops[1].set()
        await drivers[1]
        await asyncio.sleep(5)
        await self.interrupt("crash", 1, current, games, record)
        stops[0].set()
        await drivers[0]
        await self.watch_after(current, (0,), battle_id, record, self.watch)
        old_pid = games[0].process.pid
        await self.abandon_from(0, current, probes, games, record)
        companion_after = await self.companion_of(current[0])
        record("host-game-started-again", old_pid=old_pid, new_pid=games[0].process.pid,
               same_launcher_session=True, same_companion=companion_after is companion_before,
               companion_last_sent=companion_after._world_action_sent,
               companion_last_ack=companion_after._world_action_ack)
        second = await self.save_a_look(0, current, probes, record, "look-saved-first-in-the-restarted-game")
        record("world-actions", actions=self.world_actions, looks=[first, second])
        require(second != first, "the second look is the first one")
        await self.rejoin(1, current, probes, games, record)
        parties = await self.heads(current, host)
        revisions = [(await self.launcher(w))["revision"] + 1 for w in current]
        return dict(parties=parties, revisions=revisions)
