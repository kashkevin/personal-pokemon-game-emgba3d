"""Four native games through the whole launcher: a free-for-all 1v1v1v1 from the Players menu.

The owner's request of 2026-10-19 (KNOWN_ISSUES MS-11): the free-for-all must work through the real native game's
bridge without disconnecting anybody. The launcher harness of native_launcher_battle_proof.py (real LauncherWindow,
SessionWorker and LauncherSession; production world creation and enrollment; the real world server with its store)
starts four native games, one per X display, driven by ordinary key presses. Recorded and required:

    1. Everyone linked: each game has the other three as peers, every Players tab lists everyone ("Connected: 4/4").
    2. The host opens PLAYERS > Challenges > "Free-for-all 1v1v1v1"; the three others open PLAYERS, the pending
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
from pathlib import Path
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

    def __init__(self, match_seconds):
        self.match_seconds, self.before_saves = match_seconds, None

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
        require(all(v["connected"] and v["game_link"] and v["roster"] == 4 for v in sessions_before),
                f"not everyone is in the session: {sessions_before}")
        for index, probe in enumerate(probes):
            status, rows = await players_tab(probe)
            require(status == "Connected: 4/4", f"player {index}'s PLAYERS: {status} {rows}")
        record("everyone-linked-before-the-battle", sessions=[v["epoch"] for v in sessions_before])
        before = [await probe.battle() for probe in probes]

        await probes[0].open_players()
        await probes[0].choose("Challenges")
        await probes[0].choose("Free-for-all 1v1v1v1")
        for probe in probes[1:]:
            await probe.open_players()
            await probe.choose("Pending challenge")
            await probe.choose("Accept challenge")
        async with asyncio.timeout(60):
            while not all(screen.admission_action for _, screen in [await p.ready() for p in probes]):
                await asyncio.sleep(.05)

        async def descriptor(s):
            values = s._companion._bridge.menu_session.menu._battles
            require(len(values) == 1 and values[0]["mode"] == 5, f"expected one free-for-all challenge: {values}")
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
        record("all-four-entered-the-free-for-all", battle_id=battle_id, source_slots=slots,
               pids=[g.process.pid for g in games])

        async def view(slot):
            async def read(s):
                room = s._server.battle_execution.rooms.get(battle_id)
                if room is None:
                    return dict(state="waiting", pending=None)
                return dict(state=room.state, pending=None if room.route is None else room.route.validator.pending[slot])
            return await on_worker(current[0], read)

        stop = asyncio.Event()
        drivers = [asyncio.create_task(drive_battle_input(p, lambda slot=slot: view(slot), symbols, stop))
                   for p, slot in zip(probes, slots)]
        started = time.monotonic()

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
        require(all(v["connected"] and v["game_link"] and v["roster"] == 4 for v in states),
                f"somebody left the session: {states}")
        for index, probe in enumerate(probes):
            status, rows = await players_tab(probe)
            require(status == "Connected: 4/4", f"player {index}'s PLAYERS after the battle: {status} {rows}")
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
    ffa = FreeForAll(args.match_seconds)
    await launcher_proof(args, names=PLAYER_NAMES, sources=args.source, party_counts=(1,) * 4, match=ffa.match,
                         version="Native free-for-all proof", settings="windowScale=2\n",
                         scope=__doc__.split("\n\n")[0], after_boot=into_littleroot, after_save=ffa.after_save,
                         environment=dict(SDL_FRAMEBUFFER_ACCELERATION="0"))


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
    parser.add_argument("--wine", type=Path, action="append", help="a Wine prefix per player: Windows clients")
    parser.add_argument("--sdl", type=Path, help="SDL2.dll for the Windows game")
    parser.add_argument("--elf", type=Path, help="the Linux build of the same engine commit (symbol sizes)")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
