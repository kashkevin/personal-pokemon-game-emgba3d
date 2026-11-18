"""Real-game check of a shared wild Pokemon whose battler leaves (KNOWN_ISSUES MS-92), for native_launcher_newcomers_proof.py
--scenario spawn-leave (two players with Pokemon: coop-a, coop-b, in Littleroot).

Both walk north onto Route 101 and stand on the same tile facing north (the path at (10,17)); the host puts a shiny
Zigzagoon on the tile in front of them (the proof's one direct host action, as native_spawn_proof.py does: the spawn
director fills the map by itself, but not in front of the players). The friend presses A: the host grants the friend's
claim and the friend's game starts the wild battle. The friend's game is then killed (SIGKILL) during the battle; its
launcher ends its link to the host. At once the host's player faces the Pokemon and presses A: "busy" (the claimant's
grace, CLAIM_GRACE_SECONDS of the world's active time, by design). The board is read every 15 s until the claim is let
go; then the host's player presses A again: the host grants its claim and its game starts the battle (not "busy"); the
host's player runs from it (the party unchanged). The friend starts its launcher again and Continues; then the
harness's closing saves, fresh Continue and integrity check.
"""
from __future__ import annotations

import asyncio
import os
import signal
import time

from native_launcher_ffa_proof import A, B, UP, out_of_a_wild_battle, pose_of, step, walk_to
from qualify_admission_cleanup import on_worker, require

LITTLEROOT, ROUTE_101 = (0, 9), (0, 16)
ROUTE_101_KEY = "0.16"
STAND, SPOT = (10, 17), (10, 16)        # both players on the path, facing north; the Pokemon one tile north
SHINY_ZIGZAGOON, LEVEL = 263, 3


class SpawnLeaveMixin:
    async def onto_route_101(self, n, current, probes, record):
        probe, companion = probes[n], await self.companion_of(current[n])
        for x, y in ((pose_of(companion)[4], 3), (10, 3), (10, 2)):
            await walk_to(probe, companion, LITTLEROOT, x, y, record, n)
        await self.through_door(n, current, probes, record, UP, ROUTE_101)
        await walk_to(probe, companion, ROUTE_101, 10, 18, record, n)
        after = await step(probe, companion, UP, record, n)
        record("on-route-101", player=self.harness.names[n], pose=list(pose_of(companion)))
        require(tuple(pose_of(companion)[2:6]) == (*ROUTE_101, *STAND), f"{self.harness.names[n]} is not at {STAND}: {after}")

    async def board_slot(self, current, spawn_id):
        async def read(s):
            board = s._server.shared_world.spawn_boards.existing(ROUTE_101_KEY)
            slot = None if board is None else board.get(spawn_id)
            if slot is None:
                return None
            return dict(state=slot.state, claimant=slot.claimant, grace_until=slot.grace_until,
                        now=board.clock(), x=slot.x, y=slot.y)
        return await on_worker(current[0], read)

    async def place_shiny(self, current, record):
        async def place(s):
            server = s._server
            board = server.shared_world.spawn_boards.board(ROUTE_101_KEY)
            for slot in list(board.live()):
                if (slot.x, slot.y) == SPOT:
                    board.retire(slot.spawn_id, "proof")
            for slot in list(board.live()):
                if board.live_count() < board.limit():
                    break
                board.retire(slot.spawn_id, "proof")
            spawn_id = board.create(species=SHINY_ZIGZAGOON, level=LEVEL, personality=0x12345678, shiny=True,
                                    x=SPOT[0], y=SPOT[1], lifetime=3600, facing=1)
            server._broadcast_world()
            return spawn_id
        spawn_id = await on_worker(current[0], place)
        record("shiny-placed", spawn_id=spawn_id, tile=list(SPOT))
        return spawn_id

    def drawn(self, companion, spawn_id):
        local = companion._local_spawn
        if local is None or (local.map_group, local.map_number) != ROUTE_101:
            return None
        return next(((x, y) for sid, x, y in local.shown if sid == spawn_id), None)

    def busy_for(self, companion, spawn_id):
        return any(slot.spawn_id == spawn_id and slot.flags & 4 for slot in companion.spawn_inbound().slots)

    async def until(self, predicate, timeout, what):
        started = time.monotonic()
        while not predicate():
            require(time.monotonic() - started < timeout, f"{what}: not within {timeout} s")
            await asyncio.sleep(.25)
        return round(time.monotonic() - started, 1)

    async def in_battle(self, companion, timeout=30):
        started = time.monotonic()
        while time.monotonic() - started < timeout:
            pose = pose_of(companion)
            if pose is not None and pose[0] != 1 and pose[1] == 1:
                return round(time.monotonic() - started, 1)
            await asyncio.sleep(.2)
        return None

    async def spawn_leave(self, current, probes, games, record):
        host_id, friend_id = (self.harness.host.accounts[n].player_id for n in (0, 1))
        companions = [await self.companion_of(w) for w in current]
        await self.save_all(current, record, "saved-before-route-101")
        for n in (0, 1):
            await self.onto_route_101(n, current, probes, record)
        spawn_id = await self.place_shiny(current, record)
        seconds = await self.until(lambda: all(self.drawn(c, spawn_id) == SPOT for c in companions), 60,
                                   "both games draw the shiny in front of them")
        record("both-draw-the-shiny", seconds=seconds, pictures=[await self.picture(n, f"spawn-{n}-placed") for n in (0, 1)])
        # The friend claims it: its battle starts.
        await probes[1].press(A, frames=20)
        await self.until(lambda: True, 1, "")
        started = await self.in_battle(companions[1], 45)
        slot = await self.board_slot(current, spawn_id)
        record("friend-claimed-and-battles", seconds=started, slot=slot)
        require(started is not None and slot is not None and slot["claimant"] == friend_id,
                f"the friend's claim did not start its battle: {slot}")
        await asyncio.sleep(4)
        record("friend-in-battle", picture=await self.picture(1, "spawn-friend-battle"),
               host_sees_busy=self.busy_for(companions[0], spawn_id))
        # The friend's game is killed during the battle.
        pid = games[1].process.pid
        os.kill(pid, signal.SIGKILL)
        killed = time.monotonic()
        friend_session = None

        async def session(s):
            found = s._server.sessions.get(friend_id)
            return None if found is None else dict(epoch=found.session_epoch, closed=found.closed)
        for _ in range(120):
            friend_session = await on_worker(current[0], session)
            if friend_session is None:
                break
            await asyncio.sleep(.5)
        slot = await self.board_slot(current, spawn_id)
        record("friend-game-killed", pid=pid, host_session_for_the_friend=friend_session,
               seconds_until_the_host_dropped_it=round(time.monotonic() - killed, 1), slot=slot,
               friend_launcher=await self.state_of(current[1]))
        require(friend_session is None, "the host still holds the friend's session after its game was killed")
        require(slot["claimant"] == friend_id and slot["grace_until"] is not None,
                f"the claim did not start its grace after the friend left: {slot}")
        # Within the grace the host's player is told it is busy (by design).
        await probes[0].press(A, frames=20)
        await asyncio.sleep(3)
        record("host-tries-within-the-grace", busy=self.busy_for(companions[0], spawn_id),
               in_battle=pose_of(companions[0])[0] != 1 and pose_of(companions[0])[1] == 1,
               picture=await self.picture(0, "spawn-host-busy"), slot=await self.board_slot(current, spawn_id))
        for _ in range(6):                        # the game's "busy" message closed
            if (pose_of(companions[0]) or (0,))[0] == 1:
                break
            await probes[0].press(B)
            await asyncio.sleep(1)
        # The grace runs out: the board lets go of the friend's claim.
        samples = []
        while True:
            slot = await self.board_slot(current, spawn_id)
            samples.append(dict(after=round(time.monotonic() - killed), slot=slot))
            if slot is not None and slot["claimant"] is None:
                break
            require(time.monotonic() - killed < 900, f"the claim was never let go: {samples[-3:]}")
            await asyncio.sleep(15)
        released = round(time.monotonic() - killed, 1)
        await asyncio.sleep(2)
        record("claim-let-go", seconds_after_the_kill=released, slot=slot, samples=samples[::4],
               host_still_sees_busy=self.busy_for(companions[0], spawn_id),
               drawn_for_the_host=self.drawn(companions[0], spawn_id))
        # The host's player faces it and presses A: the battle starts.
        if (pose_of(companions[0]) or (0, 0, 0, 0, 0, 0, 4))[0] == 1:
            pass
        await probes[0].press(A, frames=20)
        started = await self.in_battle(companions[0], 45)
        slot = await self.board_slot(current, spawn_id)
        record("host-claims-after-the-grace", seconds=started, slot=slot,
               busy=self.busy_for(companions[0], spawn_id),
               picture=await self.picture(0, "spawn-host-battle"))
        require(started is not None and slot is not None and slot["claimant"] == host_id,
                f"after the grace the host's claim did not start a battle: {slot}")
        await out_of_a_wild_battle(probes[0], companions[0], record, 0)
        record("host-ran-from-it", slot=await self.board_slot(current, spawn_id))
        # The friend comes back.
        await self.rejoin(1, current, probes, games, record)
        parties = await self.heads(current, self.harness.host)
        revisions = [(await self.launcher(w))["revision"] + 1 for w in current]
        return dict(parties=parties, revisions=revisions)
