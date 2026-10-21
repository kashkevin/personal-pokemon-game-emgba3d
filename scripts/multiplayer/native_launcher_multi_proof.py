"""Four native games through the whole launcher: two teams battle 2v2 from the Players menu.

qualify_menu_multi.py (Windows, mGBA) on the native PC build, with the launcher
harness of native_launcher_battle_proof.py: four real launcher workers (host and
three friends) start four native games; ordinary team invitations and
acceptances form two teams; the host challenges the other team to 2v2, the
other three accept, all four press Enter battle; default moves and forced
switches until the battle ends; all four launchers report battle_finished
with their original games, the durable result is the same for all four, each
player's exact personal party is back in memory, and each game's Recent battle
results shows it; all four save (revision 2), close normally (friends first)
and Continue again onto the same canonical saves; the host store passes its
integrity check.

Parties: the owner's rule is a full party per trainer (six each here, twelve a
side), the full-party profile of the Windows qualifier, which never ran on
Windows. A side loses when all twelve of its Pokemon have fainted, so a losing
trainer sends out its sixth Pokemon: some selection of a sixth party slot is
required. The Windows qualifier also required the host's second slot; whether
the host's first Pokemon faints depends on the battle, so here it is recorded,
not required.

The four sources stand in Route 101's tall grass, where visible wild Pokemon
roam and walk up to an idle player (native-launcher-multi-2 lost the host to a
wild battle while the other games started). So, before anything else, each
player walks out of the grass and south into Littleroot Town (a town: wild
Pokemon despawn there and none appear), to a spot of its own, with ordinary
direction keys checked step by step against the game's reported position.
This happens while each source is enrolled (enrollment saves the running
game, so every character is enrolled standing in Littleroot, its party
unchanged) and again if a game ever starts in the grass; the battle, the saves
and the fresh Continue all happen in Littleroot. Sources that stand south of the
grass, as the other launcher proofs' do, take those proofs' way out
(native_launcher_ffa_proof.into_littleroot).

Four games share the cloud workspace's two processor cores, and the host gives
each native battle step 20 seconds (native-launcher-multi-6's battle went to
recovery after 8 routed blocks, with the processors overloaded: load average
7.5 on two cores; the cause was not recorded). So the launchers' shared
settings file sets windowScale=2 (640x360 windows), and the games get
SDL_FRAMEBUFFER_ACCELERATION=0: SDL then shows each window through X shared
memory instead of software OpenGL, which this display (no graphics card) would
otherwise run on the processors (about 39% of a core per game becomes 16%).
Neither changes any game state. Under Wine (--wine, one prefix per player) the games are the
Windows exe, as in native_launcher_battle_proof.py.

    PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime \\
      python scripts/multiplayer/native_launcher_multi_proof.py \\
        --game ../engine/pokeemerald-mp --rom pokedev.gba --manifest manifest.json \\
        --source a.sav --source b.sav --source c.sav --source d.sav \\
        --display :99 --display :98 --display :97 --display :96 \\
        --output /private/multiplayer-proof/native-launcher-multi-1
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows-runtime"))
from native_launcher_battle_proof import drive_battle_input, launcher_proof  # noqa: E402
from native_launcher_ffa_proof import into_littleroot  # noqa: E402
from qualify_admission_cleanup import on_worker, require  # noqa: E402
from qualify_live_runtime import sha  # noqa: E402
from qualify_menu_multi import (FULL_PARTY_COUNTS, TEAM_ACCOUNTS, challenge_slots, outcome_label,  # noqa: E402
                                selected_party_slots)

PLAYER_NAMES = ("Multi Host", "Multi Friend 1", "Multi Friend 2", "Multi Friend 3")
MATCH_SECONDS = 6600  # the Windows qualifier's full-party match bound
UP, LEFT, RIGHT, DOWN = 64, 32, 16, 128
KEY_NAMES = {UP: "up", LEFT: "left", RIGHT: "right", DOWN: "down"}
ROUTE_101, LITTLEROOT = (0, 16), (0, 9)
# Route 101 (layout collision and tall grass checked from the engine's map data):
# west out of the grass along the start's row to x=10, round the rock at
# (8-11,13) by x=7, east to x=10 again and south through the exit at (10,18-19).
STARTS = {(12, 10), (15, 10), (15, 12)}
WAYPOINTS = ((10, None), (10, 12), (7, 12), (7, 16), (10, 16), (10, 19))
# Littleroot from its north entrance (10,0): down to row 3, then a spot per
# player, the farthest first so that nobody walks past another player.
SPOTS = {0: (4, 3), 1: (7, 3), 2: (16, 3), 3: (13, 3)}


def where(companion):
    pose = companion._local_pose
    return None if pose is None else (pose.map_group, pose.map_number, pose.x, pose.y, pose.activity)


def field_state(probe):
    """What a game is doing, for a harness failure: its main callbacks by name (Linux
    builds have every symbol), the field script status and the open menus."""
    names = getattr(probe, "_names", None)
    if names is None:
        names = probe._names = {address: name for name, (address, _) in probe.symbols.items()}
    state = {}
    if "gMain" in probe.symbols:
        main = probe.mem("gMain", 8)
        for field, offset in (("callback1", 0), ("callback2", 4)):
            # probe.code: a Windows game loaded away from its preferred base holds moved code pointers
            address = probe.code(int.from_bytes(main[offset:offset + 4], "little")) & ~1
            state[field] = names.get(address, hex(address))
    if "sGlobalScriptContextStatus" in probe.symbols:
        state["script_status"] = probe.mem("sGlobalScriptContextStatus", 1)[0]
    state["players_menu_active"] = probe.mem("sMultiplayerMenuActive")[0]
    state["choose_action"] = probe.in_choose_action()
    return state


async def settle(probe, companion, slot, seconds=45):
    """Back to a field the player controls: a notice banner or the map's name ends by
    itself; a wild Pokemon that walked up and started a battle is run from."""
    deadline = time.monotonic() + seconds
    while True:
        now = where(companion)
        if now is not None and now[4] == 1:
            return now
        if probe.in_choose_action():
            await probe.run_from_wild_battle(lambda: (where(companion) or (0,) * 5)[4] == 1)
            probe.record("ran-from-a-wild-battle", slot=slot, during="walk", position=list((now or (0,) * 5)[:4]))
            continue
        if time.monotonic() >= deadline:
            # Keep the picture and the game's state before the harness closes the game.
            output = getattr(probe, "output", None)
            if output is not None:
                subprocess.run(["import", "-window", "root", str(output / f"field-stuck-{slot}.png")],
                               env=probe.environment, capture_output=True)
            raise AssertionError(f"the field did not come back: {now} {field_state(probe)}")
        await asyncio.sleep(.1)


async def step(probe, companion, key, slot):
    """An ordinary key press toward the next tile, and the position afterwards. A press that
    only turns the player is repeated; when the field is busy (a notice, a wild battle) the
    player waits or runs, and the caller walks on from wherever the player stands."""
    start = await settle(probe, companion, slot)
    for _ in range(8):
        await probe.press(key, frames=8, release=1)
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            await asyncio.sleep(.05)
            now = where(companion)
            require(now is not None, "no position while walking")
            if now[:4] != start[:4]:
                await asyncio.sleep(.4)  # the step finishes
                return now
            if now[4] != 1:
                return await settle(probe, companion, slot)
    raise AssertionError(f"could not step {KEY_NAMES[key]} from {start}")


async def walk_to(probe, companion, slot, target_map, x, y, budget):
    """Axis by axis to (x, y) on target_map; every step re-reads the position."""
    while True:
        now = where(companion)
        require(now[:2] == target_map, f"left {target_map} while walking: {now}")
        if (now[2], now[3]) == (x, y):
            return budget
        require(budget > 0, f"too many steps on the way to {(x, y)}: at {now}")
        key = (RIGHT if x > now[2] else LEFT) if now[2] != x else (DOWN if y > now[3] else UP)
        await step(probe, companion, key, slot)
        budget -= 1


async def leave_the_grass(phase, slot, probe, companion, record):
    """Walk from Route 101's grass into Littleroot Town, to this player's own spot."""
    here = where(companion)
    if here[:2] == LITTLEROOT:
        record("starts-in-littleroot", phase=phase, slot=slot, position=list(here[:4]))
        return
    require(here[:2] == ROUTE_101 and tuple(here[2:4]) in STARTS, f"unexpected start position {here}")
    started, budget = time.monotonic(), 80
    for x, y in WAYPOINTS:
        budget = await walk_to(probe, companion, slot, ROUTE_101, x, here[3] if y is None else y, budget)
    while where(companion)[:2] == ROUTE_101:  # through the exit into Littleroot
        require(budget > 0, "could not leave Route 101")
        await step(probe, companion, DOWN, slot)
        budget -= 1
    for x, y in ((10, 3), SPOTS[slot]):
        budget = await walk_to(probe, companion, slot, LITTLEROOT, x, y, budget)
    end = where(companion)
    record("walked-out-of-the-grass-into-littleroot", phase=phase, slot=slot, start=list(here[:4]),
           end=list(end[:4]), steps=80 - budget, seconds=round(time.monotonic() - started, 1))


async def into_town(phase, slot, probe, companion):
    """Into Littleroot Town from where the source stands: this proof's tall grass, or south of the grass (Route 101's
    (4-5,14)), where the other launcher proofs' sources stand - their way out."""
    async with asyncio.timeout(60):
        while where(companion) is None:
            await asyncio.sleep(.2)
    here = where(companion)
    if here[:2] == ROUTE_101 and tuple(here[2:4]) not in STARTS:
        await into_littleroot(phase, slot, probe, companion)
    else:
        await leave_the_grass(phase, slot, probe, companion, probe.record)


async def close_players(probe):
    async with asyncio.timeout(15):
        while probe.read()["active"]:
            await probe.press(2)


async def native_multi_match(current, probes, games, host, symbols, record, *, match_seconds=MATCH_SECONDS):
    """qualify_menu_multi.native_menu_match with native games: production menus own every step."""
    async def identity(s):
        c = s._companion
        return (s._game, s._runtime, c._bridge, c._bridge.incarnation, c._live_battle_runtime_id)
    before = [await probe.battle() for probe in probes]
    for sender, recipient in TEAM_ACCOUNTS:
        await probes[sender].open_players()
        # The players list names each player with the friendship level after it.
        await probes[sender].choose(host.accounts[recipient].display_name, prefix=True)
        await probes[sender].choose("Invite to team")
        await probes[recipient].open_players()
        await probes[recipient].choose("Team invitation")
        await probes[recipient].choose("Accept invitation")
        await close_players(probes[sender])
        await close_players(probes[recipient])
        record("ordinary-native-team-formed", accounts=[sender, recipient])
    async def teams(s):
        return (await s._companion.team_rpc("status"))["result"]
    views = [await on_worker(w, teams) for w in current]
    expected_teams = {frozenset(host.accounts[i].player_id for i in team) for team in TEAM_ACCOUNTS}
    for index, view in enumerate(views):
        require(view["team"] is not None and host.accounts[index].player_id in view["team"]["members"]
                and {frozenset(t["members"]) for t in view["teams"]} == expected_teams,
                "ordinary native team invitations did not form two separate exact duos")
    await probes[0].open_players()
    await probes[0].choose("Your team")
    await probes[0].choose("Rival Battle - 2v2")
    for probe in probes[1:]:
        await probe.open_players()
        await probe.choose("Pending challenge")
        await probe.choose("Accept challenge")
    async with asyncio.timeout(30):
        while not all(screen.admission_action for _, screen in [await p.ready() for p in probes]):
            await asyncio.sleep(.05)
    async def descriptor(s):
        values = s._companion._bridge.menu_session.menu._battles
        require(len(values) == 1, "expected one exact native challenge")
        return json.loads(json.dumps(values[0]))
    challenges = [await on_worker(w, descriptor) for w in current]
    challenge = challenges[0]
    require(all(value == challenge for value in challenges), "four displayed native consent descriptors differ")
    slots = challenge_slots(challenge, host.accounts, FULL_PARTY_COUNTS)
    originals = [await on_worker(worker, identity) for worker in current]
    battle_id = challenge["battle_id"]
    blocks = []
    async def observe(s):
        service = s._server.battle_execution
        require(service.observer is None, "a previous proof observer exists")
        service.observer = lambda block: blocks.append(dict(block))
    await on_worker(current[0], observe)
    await asyncio.gather(*(p.choose("Enter battle", wait=False) for p in probes))
    record("all-four-native-Enter-selected", battle_id=battle_id, pids=[g.process.pid for g in games],
           source_slots=slots)
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
            async def room_of(host_session):
                room = host_session._server.battle_execution.rooms.get(battle_id)
                return None if room is None else dict(state=room.state, error=room.error)
            raise AssertionError("launcher retained a battle failure or lost its original game: " + json.dumps(dict(
                status=s.status.code, game_exited=s._game is None or s._game.process.returncode is not None,
                host_room=await room_of(current[0]._active_session) if current[0]._active_session else None)))
        return s.status.code == "battle_finished" and s.can_save and s._interaction is None
    try:
        async with asyncio.timeout(match_seconds):
            report_at = 0
            while True:
                for driver in drivers:
                    if driver.done():
                        await driver
                if all([await on_worker(w, finished) for w in current]):
                    break
                if time.monotonic() >= report_at:
                    record("native-2v2-progress", blocks=len(blocks),
                           elapsed_seconds=round(time.monotonic() - started, 1))
                    report_at = time.monotonic() + 60
                await asyncio.sleep(.1)
    finally:
        stop.set()
        await asyncio.gather(*drivers)
    async def terminal(s):
        c = s._companion
        require(s._battle_retained is None and s._battle_handoff_successor is None, "launcher still retains battle ownership")
        require(s._emergency.result.state == "armed" and c._emergency_controller is s._emergency,
                "fresh terminal saver is not armed")
        require(not any((s.profile_directory / name).exists() for name in
            ("pending-battle.json", "pending-battle-admission.json", "pending-export.json", "pending-emergency.json")),
            "terminal recovery intent remains pending")
        history = (await c.battle_challenge_rpc("history"))["result"]
        values = [v for v in history if v["battle_id"] == battle_id]
        require(len(values) == 1 and values[0]["mode"] == 3 and values[0]["players"] == challenge["players"],
                "durable native Multi result missing")
        return values[0], dict(status=asdict(s.status),
                               handoff_sha256=sha(s.profile_directory / (battle_id + ".battle-handoff.json")))
    results = []
    for index, worker in enumerate(current):
        after = await on_worker(worker, identity)
        require(all(after[n] is originals[index][n] for n in range(3)) and after[3:] == originals[index][3:],
                "battle replaced the original game, bridge or native identity")
        require(games[index].process.returncode is None, "original native process exited")
        result, details = await on_worker(worker, terminal)
        results.append(result)
        await probes[index].snapshot(lambda r: r["hold"] == 0)
        state = await probes[index].battle()
        require(state["count"] == before[index]["count"] and state["party_sha256"] == before[index]["party_sha256"],
                "original full personal party was not restored")
        record("launcher-native-battle-completed", slot=index, pid=games[index].process.pid, **details)
    require(all(result == results[0] for result in results), "four players disagree on durable result")
    selected = selected_party_slots(blocks)
    require(any(choice["slot"] == 5 for choice in selected), "no trainer sent out its sixth Pokemon")
    record("real-native-2v2-result", result=results[0], routed_blocks=len(blocks), selected_party_slots=selected,
           host_second_slot_selected=dict(owner=slots[0], slot=1) in selected,
           elapsed_seconds=round(time.monotonic() - started, 1))
    for index, probe in enumerate(probes):
        result = results[index]
        await probe.open_players()
        await probe.choose("Challenges")
        await probe.choose("Recent battle results")
        _, screen = await probe.choose(outcome_label(result, host.accounts[index].player_id))
        require(screen.title == "Battle result" and screen.status ==
                ("Draw" if result["outcome"] == 3 else f"Team {result['outcome']} won"),
                "native history screen differs from durable outcome")
        record("native-result-screen-matches", slot=index, title=screen.title, status=screen.status)
        await close_players(probe)
    return results[0]


async def run(args):
    require(len(args.source) == 4, "four sources, one per player")

    async def after_boot(phase, slot, probe, companion):
        await into_town(phase, slot, probe, companion)
    await launcher_proof(args, names=PLAYER_NAMES, sources=args.source, party_counts=FULL_PARTY_COUNTS,
                         match=lambda *values: native_multi_match(*values, match_seconds=args.match_seconds),
                         version="Native 2v2 proof", settings="windowScale=2\n",
                         scope=__doc__.split("\n\n")[0], after_boot=after_boot,
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
