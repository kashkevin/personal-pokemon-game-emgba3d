"""Four native games through the whole launcher: a free-for-all 1v1v1v1 from the Players menu.

The owner's request of 2026-10-19 (KNOWN_ISSUES MS-11): the free-for-all must work through the real native game's
bridge without disconnecting anybody. The launcher harness of native_launcher_battle_proof.py (real LauncherWindow,
SessionWorker and LauncherSession; production world creation and enrollment; the real world server with its store)
starts four native games, one per X display, driven by ordinary key presses. Recorded and required:

    1. Everyone linked: each game has the other three as peers, every Players tab lists everyone ("Connected: 4/4").
    2. The host opens PLAYERS > Challenges > New battle > the free-for-all of all four; the three others open PLAYERS, the pending
       challenge, and accept; all four see the same challenge and press Enter battle at the same time.
    3. One native free-for-all (phase 5, four cores) runs with default moves to its end: every launcher reports
       battle_finished with its original game, bridge and native identity; each trainer's exact party is back in
       memory; the host's free-for-all book has the result (a winner's slot, or a draw) and one winner, three losers.
    4. Back in the world: every game on the field, linked to the other three, every roster with four players, the
       same server sessions as before the battle; PLAYERS still "Connected: 4/4".
    5. The harness's own end (native_launcher_battle_proof.launcher_proof): all four save (revision 2), each save's
       party is the canonical one, the store passes its integrity check, a normal close (friends first) and a fresh
       Continue onto the same canonical saves. Before that the proof compares each character's canonical save before
       and after the battle: money, coins, PC items and the bag, and every flag and variable are unchanged.

The sources stand in Route 101's grass; each character is first walked south into Littleroot Town (no wild Pokemon
there), to a spot of its own, while it is enrolled, so the battle and the saves happen in Littleroot.

--leave-after SECONDS (a player leaves during the battle; exploratory, what happens is recorded): the battle runs that
long, then the last friend closes their game the ordinary way. For the next --watch seconds (beyond the host's 180 s
battle deadline) the proof records, every 30 s, what each launcher reports for the three who stayed (status, link to the
world, roster, on the field or not, whether "Recover interrupted battle" is offered) and the host's battle state. Then
whoever is still held in the battle closes their game too, and everyone who closed starts again from the launcher
(rejoin). If the launchers let them in: all four linked, PLAYERS "Connected: 4/4", every party the canonical one, then
step 5 as above. If a launcher refuses (an interrupted native battle is held for recovery by the original games, which
are closed now: "pending_battle"), that is recorded and the run ends there. ffa-leave-1 (2026-10-19): nobody else was
disconnected; the three who stayed were held in the battle ("battle_recovery_held") for the whole watch; after closing,
the host's launcher refused to open the world again (pending_battle).

    PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime \\
      python scripts/multiplayer/native_launcher_ffa_proof.py \\
        --game ../engine/pokeemerald-mp --rom pokedev.gba --manifest manifest.json \\
        --source a.sav --source b.sav --source c.sav --source d.sav \\
        --display :94 --display :95 --display :96 --display :97 \\
        --output /private/multiplayer-proof/native-launcher-ffa-1
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import signal
import struct
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows-runtime"))
from native_launcher_battle_proof import drive_battle_input, launcher_proof  # noqa: E402
from qualify_admission_cleanup import on_worker, require  # noqa: E402
from qualify_launcher_session import inspect_closed_head  # noqa: E402
from emerald_multiplayer.flash import inspect_flash  # noqa: E402
from emerald_multiplayer.ownership_protocol import OWNERSHIP_PROFILE  # noqa: E402

PLAYER_NAMES = ("FFA Host", "FFA Friend 1", "FFA Friend 2", "FFA Friend 3")
MATCH_SECONDS = 1800
A, B, RIGHT, LEFT, UP, DOWN = 1, 2, 16, 32, 64, 128
ROUTE_101, LITTLEROOT = (0, 16), (0, 9)
# From the sources' place in Route 101's grass to its south exit (native_session_persistence_proof.py's way), then
# from Littleroot's north entrance down to row 3 and a spot per player (native_launcher_multi_proof.py's spots).
WAYPOINTS = ((7, None), (7, 16), (10, 16), (10, 19))
SPOTS = {0: (4, 3), 1: (7, 3), 2: (16, 3), 3: (13, 3)}
# Save block 1 (include/global.h): money (u32) and coins (u16) at 0x490, the registered item, 50 PC item slots at 0x498,
# then the bag's 186 slots (items, key items, balls, TMs, berries) at 0x560; flags and variables at 0x1270-0x159C.
# Money, coins and bag quantities are kept XOR the save block 2 encryption key, which the game renews when it saves.
MONEY, PC_ITEMS, BAG, BAG_SLOTS = 0x490, 0x498, 0x560, 186
FLAGS_AND_VARS = (0x1270, 0x159C)
ENCRYPTION_KEY = 0xAC


def pose_of(companion):
    """(activity, detail, map group, map number, x, y) of the game's own pose; activity 1 is the field."""
    p = companion._local_pose
    return None if p is None else (p.activity, p.detail, p.map_group, p.map_number, p.x, p.y)


async def out_of_a_wild_battle(probe, companion, record, slot):
    """A wild Pokemon that walked up: RUN (B through texts, Down, Right, A), fought out after 90 s."""
    started = time.monotonic()
    while (pose_of(companion) or (0,))[0] != 1:
        here = pose_of(companion)
        if here is not None and here[1] == 1:
            keys = (B, B, DOWN, RIGHT, A) if time.monotonic() - started < 90 else (A,)
            for key in keys:
                await probe.press(key)
                await asyncio.sleep(.4)
            await asyncio.sleep(1.5)
        else:
            await asyncio.sleep(.3)
        require(time.monotonic() - started < 300, f"a wild battle did not end: {pose_of(companion)}")
    record("left-a-wild-battle-on-the-way", slot=slot, seconds=round(time.monotonic() - started, 1))


async def step(probe, companion, key, record, slot):
    before = pose_of(companion)
    await probe.press(key, frames=8, release=1)
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        await asyncio.sleep(.05)
        now = pose_of(companion)
        if now is not None and now[0] != 1:
            await asyncio.sleep(1)
            if (pose_of(companion) or (0, 0))[1] == 1:
                await out_of_a_wild_battle(probe, companion, record, slot)
            else:
                while (pose_of(companion) or (0,))[0] != 1:  # a notice, the map's name, a door's fade
                    await asyncio.sleep(.2)
            return pose_of(companion)
        if now is not None and before is not None and now[2:] != before[2:]:
            await asyncio.sleep(.3)
            return now
    return pose_of(companion)


async def walk_to(probe, companion, target_map, x, y, record, slot, budget=60):
    stuck = 0
    for _ in range(budget):
        now = pose_of(companion)
        require(tuple(now[2:4]) == target_map, f"left {target_map} while walking: {now}")
        ty = now[5] if y is None else y
        if (now[4], now[5]) == (x, ty):
            return
        key = (RIGHT if x > now[4] else LEFT) if now[4] != x else (DOWN if ty > now[5] else UP)
        after = await step(probe, companion, key, record, slot)
        if after is None or after[2:] != now[2:]:
            stuck = 0
            continue
        stuck += 1
        if stuck % 3 == 0:  # a wild Pokemon or a person in the way: one step aside
            aside = (DOWN, UP) if key in (LEFT, RIGHT) else (RIGHT, LEFT)
            await step(probe, companion, aside[(stuck // 3) % 2], record, slot)
    raise AssertionError(f"could not reach {(x, y)} on {target_map}: at {pose_of(companion)}")


async def into_littleroot(phase, slot, probe, companion):
    """Out of Route 101's grass, south into Littleroot Town, to this player's own spot."""
    record = probe.record
    async with asyncio.timeout(60):
        while pose_of(companion) is None or pose_of(companion)[0] != 1:
            await asyncio.sleep(.2)
    here = pose_of(companion)
    if tuple(here[2:4]) == LITTLEROOT:
        record("starts-in-littleroot", phase=phase, slot=slot, position=list(here[2:]))
        return
    require(tuple(here[2:4]) == ROUTE_101, f"unexpected start {here}")
    started = time.monotonic()
    for x, y in WAYPOINTS:
        await walk_to(probe, companion, ROUTE_101, x, y, record, slot)
    for _ in range(10):
        if tuple(pose_of(companion)[2:4]) == LITTLEROOT:
            break
        await step(probe, companion, DOWN, record, slot)
    for x, y in ((10, 3), SPOTS[slot]):
        await walk_to(probe, companion, LITTLEROOT, x, y, record, slot)
    record("walked-into-littleroot", phase=phase, slot=slot, start=list(here[2:]), end=list(pose_of(companion)[2:]),
           seconds=round(time.monotonic() - started, 1))


async def close_players(probe):
    async with asyncio.timeout(15):
        while probe.read()["active"]:
            await probe.press(B)


async def challenge_free_for_all(probe, players):
    """PLAYERS > Challenges > New battle > the free-for-all of everyone connected (Update 32). A game with the 1v1v1
    offers four connected players a Free-for-All page (everyone, or three of the four): "Everyone: 4 Players"."""
    await probe.open_players()
    await probe.choose("Challenges")
    _, screen = await probe.choose("New battle")
    if players == 4 and "Free-for-All" in [row.label for row in screen.rows]:
        await probe.choose("Free-for-All")
        await probe.choose("Everyone: 4 Players")
    else:
        await probe.choose(f"Free-for-All - {players} Players")


async def players_tab(probe):
    await probe.open_players()
    _, screen = await probe.ready()
    rows = [row.label for row in screen.rows]
    await close_players(probe)
    return screen.status, rows


def save_regions(checkpoint):
    """What a battle must not change, decrypted: money, coins, the registered item, PC items, the bag; flags and vars."""
    parsed = inspect_flash(checkpoint.payload, save_profile=OWNERSHIP_PROFILE)
    block1 = parsed.save_block1
    key = struct.unpack_from("<I", parsed.save_block2, ENCRYPTION_KEY)[0]
    money, coins, registered = struct.unpack_from("<IHH", block1, MONEY)
    pc = [struct.unpack_from("<HH", block1, PC_ITEMS + 4 * i) for i in range(50)]
    bag = [(item, quantity ^ (key & 0xFFFF)) for item, quantity in
           (struct.unpack_from("<HH", block1, BAG + 4 * i) for i in range(BAG_SLOTS))]
    return dict(revision=checkpoint.revision, money=money ^ key, coins=coins ^ (key & 0xFFFF), registered=registered,
                items=[list(slot) for slot in pc + bag if slot[0]],
                flags_and_vars=block1[slice(*FLAGS_AND_VARS)].hex())


class FreeForAll:
    """The match (step 2-4) and the comparison of the saves (step 5) for launcher_proof."""
    PLAYERS, MODE = 4, 5   # native_launcher_ffa3_proof.py: the 1v1v1

    def __init__(self, match_seconds, leave_after=None, watch=240):
        self.match_seconds, self.before_saves = match_seconds, None
        self.leave_after, self.watch = leave_after, watch
        self.harness = None

    async def leave_and_rejoin(self, current, probes, games, host, record, battle_id, blocks, drivers, stops, started,
                               session, before, sessions_before):
        """--leave-after: the last friend closes their game during the battle; what the others see is recorded."""
        harness, leaver = self.harness, 3
        async with asyncio.timeout(self.leave_after + 300):
            while time.monotonic() - started < self.leave_after or len(blocks) < 20:
                for driver in drivers:
                    if driver.done():
                        await driver
                await asyncio.sleep(.2)
        stops[leaver].set()
        await drivers[leaver]
        record("leaving-during-the-free-for-all", slot=leaver, seconds=round(time.monotonic() - started),
               routed_blocks=len(blocks))
        game = games[leaver]
        os.kill(game.process.pid, signal.SIGTERM)                 # an ordinary close (SDL turns it into a quit)
        await harness.poll_until(lambda: game.process.returncode is not None, 60)
        await harness.poll_until(lambda: not current[leaver].busy, 180)
        record("left-during-the-free-for-all", slot=leaver, exit_code=game.process.returncode)

        async def state(s):
            c = s._companion
            pose = pose_of(c)
            return dict(code=s.status.code, connected=c.connected, game_link=c._bridge is not None, roster=len(c._players),
                        field=pose is not None and pose[0] == 1, can_save=bool(s.can_save),
                        recovery_offered=bool(getattr(s.status, "battle_recovery_available", False)),
                        game_running=s._game is not None and s._game.process.returncode is None)

        async def host_battle(s):
            desk = s._server.battle_desk
            battle = desk._active.get(battle_id) or desk._history.get(battle_id)
            room = s._server.battle_execution.rooms.get(battle_id)
            return dict(desk=None if battle is None else battle.state, reason=None if battle is None else battle.reason,
                        room=None if room is None else room.state)
        stayed = [n for n in range(4) if n != leaver]
        watch_started = time.monotonic()
        while True:
            states = {n: await on_worker(current[n], state) for n in stayed}
            record("after-the-leave", seconds=round(time.monotonic() - watch_started), host_battle=await on_worker(current[0], host_battle),
                   players={PLAYER_NAMES[n]: v for n, v in states.items()})
            if all(v["field"] and v["can_save"] for v in states.values()) or time.monotonic() - watch_started >= self.watch:
                break
            await asyncio.sleep(30)
        for n in stayed:
            stops[n].set()
        await asyncio.gather(*(drivers[n] for n in stayed), return_exceptions=True)
        held = [n for n, v in states.items() if not (v["field"] and v["can_save"])]
        record("still-held-in-the-battle" if held else "everyone-who-stayed-is-back-on-the-field",
               players=[PLAYER_NAMES[n] for n in (held or stayed)])
        for n in held:                                           # their way out: close the game, as the leaver did
            os.kill(games[n].process.pid, signal.SIGTERM)
            await harness.poll_until(lambda g=games[n]: g.process.returncode is not None, 60)
            await harness.poll_until(lambda w=current[n]: not w.busy, 180)
            record("closed-a-held-game", slot=n, exit_code=games[n].process.returncode)
        pending = [n for n in range(4) if (harness.players[n].worker.private_root / "players").exists() and any(
            (path / "pending-battle.json").exists() for path in (harness.players[n].worker.private_root / "players").glob("*/*"))]
        record("battle-recovery-intents-left", players=[PLAYER_NAMES[n] for n in pending])
        for n in sorted(held + [leaver]):                        # everyone who closed starts again from the launcher
            try:
                again = await harness.start("rejoin", n)
            except AssertionError:
                # The launcher refuses to open a character an interrupted native battle still holds (pending_battle):
                # recovery needs the original games, and they are closed. Recorded as the result of this run.
                worker = harness.workers[-1]
                code = getattr(worker, "_status_code", None)
                record("rejoin-refused", slot=n, status=code)
                raise AssertionError(f"{PLAYER_NAMES[n]} cannot open the world again after the interrupted free-for-all "
                                     f"(launcher status {code})") from None
            await harness.ready(again)
            harness.players[n] = again
            current[n], games[n], probes[n] = again.worker, again.game, again.probe
            record("rejoined", slot=n, pid=again.game.process.pid)
        async with asyncio.timeout(120):
            while True:
                states = [await on_worker(w, session) for w in current]
                if all(v["connected"] and v["game_link"] and v["roster"] == 4 and v["pose"] is not None and v["pose"][0] == 1
                       for v in states):
                    break
                await asyncio.sleep(.5)
        for index, probe in enumerate(probes):
            status, rows = await players_tab(probe)
            require(status == "Connected: 4/4", f"player {index}'s PLAYERS after rejoining: {status} {rows}")
        for index, probe in enumerate(probes):
            state_now = await probe.battle()
            require(state_now["count"] == before[index]["count"] and state_now["party_sha256"] == before[index]["party_sha256"],
                    f"player {index}'s party is not the one from before the battle")
        record("everyone-back-linked-with-their-parties", sessions=[v["epoch"] for v in states],
               replaced=[v["epoch"] != o["epoch"] for v, o in zip(states, sessions_before)],
               host_battle=await on_worker(current[0], host_battle))
        return None

    async def challenge(self, probes, host, record):
        """Step 2: the host's free-for-all of everyone; each other player accepts it."""
        await challenge_free_for_all(probes[0], self.PLAYERS)
        for probe in probes[1:]:
            await probe.open_players()
            await probe.choose("Pending challenge")
            await probe.choose("Accept challenge")

    async def match(self, current, probes, games, host, symbols, record):
        async def identity(s):
            c = s._companion
            return (s._game, s._runtime, c._bridge, c._bridge.incarnation, c._live_battle_runtime_id)

        async def session(s):
            c = s._companion
            return dict(connected=c.connected, epoch=c.session_epoch, game_link=c._bridge is not None,
                        roster=len(c._players), pose=pose_of(c))

        async def saves(s):
            return [save_regions(inspect_closed_head(s._store, a.player_id)) for a in host.accounts]

        self.before_saves = await on_worker(current[0], saves)
        sessions_before = [await on_worker(w, session) for w in current]
        connected = f"Connected: {self.PLAYERS}/4"
        require(all(v["connected"] and v["game_link"] and v["roster"] == self.PLAYERS for v in sessions_before),
                f"not everyone is in the session: {sessions_before}")
        for index, probe in enumerate(probes):
            status, rows = await players_tab(probe)
            require(status == connected, f"player {index}'s PLAYERS: {status} {rows}")
        record("everyone-linked-before-the-battle", sessions=[v["epoch"] for v in sessions_before])
        before = [await probe.battle() for probe in probes]

        await self.challenge(probes, host, record)
        async with asyncio.timeout(60):
            while not all(screen.admission_action for _, screen in [await p.ready() for p in probes]):
                await asyncio.sleep(.05)

        async def descriptor(s):
            values = s._companion._bridge.menu_session.menu._battles
            require(len(values) == 1 and values[0]["mode"] == self.MODE, f"expected one free-for-all challenge: {values}")
            return json.loads(json.dumps(values[0]))
        challenges = [await on_worker(w, descriptor) for w in current]
        challenge = challenges[0]
        require(all(value == challenge for value in challenges), "the four displayed challenges differ")
        battle_id = challenge["battle_id"]
        slots = [challenge["players"].index(account.player_id) for account in host.accounts]
        originals = [await on_worker(worker, identity) for worker in current]
        blocks = []

        async def observe(s):
            service = s._server.battle_execution
            require(service.observer is None, "a previous proof observer exists")
            service.observer = lambda block: blocks.append(dict(block))
        await on_worker(current[0], observe)
        await asyncio.gather(*(p.choose("Enter battle", wait=False) for p in probes))
        record("everyone-entered-the-free-for-all", battle_id=battle_id, source_slots=slots,
               pids=[g.process.pid for g in games])

        async def view(slot):
            async def read(s):
                room = s._server.battle_execution.rooms.get(battle_id)
                if room is None:
                    return dict(state="waiting", pending=None)
                return dict(state=room.state, pending=None if room.route is None else room.route.validator.pending[slot])
            return await on_worker(current[0], read)

        stops = [asyncio.Event() for _ in probes]
        drivers = [asyncio.create_task(drive_battle_input(p, lambda slot=slot: view(slot), symbols, stop))
                   for p, slot, stop in zip(probes, slots, stops)]
        started = time.monotonic()
        if self.leave_after is not None:
            return await self.leave_and_rejoin(current, probes, games, host, record, battle_id, blocks, drivers, stops,
                                               started, session, before, sessions_before)

        async def finished(s):
            if (s._save_failed and s._interaction is None
                    or s._game is None or s._game.process.returncode is not None):
                raise AssertionError(f"launcher lost its game or kept a battle failure: {s.status.code}")
            return s.status.code == "battle_finished" and s.can_save and s._interaction is None
        try:
            async with asyncio.timeout(self.match_seconds):
                report_at = 0
                while True:
                    for driver in drivers:
                        if driver.done():
                            await driver
                    if all([await on_worker(w, finished) for w in current]):
                        break
                    if time.monotonic() >= report_at:
                        states = [await on_worker(w, session) for w in current]
                        record("free-for-all-progress", blocks=len(blocks), elapsed=round(time.monotonic() - started),
                               linked=[v["game_link"] and v["connected"] for v in states])
                        report_at = time.monotonic() + 30
                    await asyncio.sleep(.1)
        finally:
            for stop in stops:
                stop.set()
            await asyncio.gather(*drivers)
        seconds = round(time.monotonic() - started, 1)

        async def terminal(s):
            require(s._battle_retained is None and s._battle_handoff_successor is None,
                    "launcher still retains battle ownership")
            require(not any((s.profile_directory / name).exists() for name in
                            ("pending-battle.json", "pending-battle-admission.json", "pending-export.json",
                             "pending-emergency.json")), "a recovery intent remains pending")
            return s.status.code
        for index, worker in enumerate(current):
            after = await on_worker(worker, identity)
            require(all(after[n] is originals[index][n] for n in range(3)) and after[3:] == originals[index][3:],
                    "the battle replaced the original game, bridge or native identity")
            require(games[index].process.returncode is None, "an original game exited")
            await on_worker(worker, terminal)
            await probes[index].snapshot(lambda r: r["hold"] == 0)
            state = await probes[index].battle()
            require(state["count"] == before[index]["count"] and state["party_sha256"] == before[index]["party_sha256"],
                    "a trainer's original party was not restored")
            record("free-for-all-finished-for", slot=index, pid=games[index].process.pid)

        async def book(s):
            return s._server.shared_world.ffa.result(battle_id)
        result = await on_worker(current[0], book)
        require(result is not None and result["players"] == challenge["players"], f"no free-for-all result: {result}")
        winner = result["winner"]
        names = {a.player_id: a.display_name for a in host.accounts}
        record("free-for-all-result", outcome=result["outcome"], draw=winner is None,
               winner=names.get(winner), losers=[names[p] for p in result["players"] if p != winner],
               routed_blocks=len(blocks), seconds=seconds)

        async with asyncio.timeout(60):
            while True:
                states = [await on_worker(w, session) for w in current]
                if all(v["pose"] is not None and v["pose"][0] == 1 for v in states):
                    break
                await asyncio.sleep(.5)
        require([v["epoch"] for v in states] == [v["epoch"] for v in sessions_before],
                f"a session was replaced by the battle: {states}")
        require(all(v["connected"] and v["game_link"] and v["roster"] == self.PLAYERS for v in states),
                f"somebody left the session: {states}")
        for index, probe in enumerate(probes):
            status, rows = await players_tab(probe)
            require(status == connected, f"player {index}'s PLAYERS after the battle: {status} {rows}")
        record("back-in-the-world-same-sessions", sessions=[v["epoch"] for v in states],
               poses=[list(v["pose"]) for v in states])
        return result

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
    ffa = FreeForAll(args.match_seconds, args.leave_after, args.watch)
    await launcher_proof(args, names=PLAYER_NAMES, sources=args.source, party_counts=(1,) * 4, match=ffa.match,
                         version="Native free-for-all proof", settings="windowScale=2\n",
                         scope=__doc__.split("\n\n")[0], after_boot=into_littleroot, after_save=ffa.after_save,
                         environment=dict(SDL_FRAMEBUFFER_ACCELERATION="0"),
                         on_harness=lambda harness: setattr(ffa, "harness", harness))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True,
                        help="native Linux executable, unstripped (or the Windows exe with --wine)")
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source", type=Path, action="append", required=True, help="a save per player (four)")
    parser.add_argument("--display", action="append", required=True, help="an X display per player (four)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0)
    parser.add_argument("--match-seconds", type=float, default=MATCH_SECONDS)
    parser.add_argument("--leave-after", type=float, help="the last friend closes their game this long into the battle")
    parser.add_argument("--watch", type=float, default=240, help="with --leave-after: how long to watch the others")
    parser.add_argument("--wine", type=Path, action="append", help="a Wine prefix per player: Windows clients")
    parser.add_argument("--sdl", type=Path, help="SDL2.dll for the Windows game")
    parser.add_argument("--elf", type=Path, help="the Linux build of the same engine commit (symbol sizes)")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
