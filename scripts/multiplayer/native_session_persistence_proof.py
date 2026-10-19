"""The owner's report of 2026-10-19 with real games: a player in a battle stays in everyone's session and Players list.

Two or four players through the whole launcher (native_launcher_battle_proof.LauncherHarness: the real LauncherWindow,
SessionWorker and LauncherSession, production world creation and enrollment, the real world server with its store) and
one native game per player on its own X display, driven by ordinary key presses. Recorded and required:

    1. Every game is linked to the session and has every other player (the game's own multiplayer.c state, read from
       its memory: sConnected, its peers and their activity); every Players tab lists everyone ("Connected: N/4").
       The world's first mass outbreak starts four active minutes in (its settings file; the default is 8-15): every
       game holds its Town Map marker (the shared-world record's bytes 192-199) and stays linked.
    2. A player walks to a shared wild Pokemon and talks to it: an ordinary wild battle. For 25 s (longer than the
       server's presence and idle timeouts) every other game keeps that player as a peer (hidden, activity 0), every
       roster says "battle", no session is replaced, and another player's Players tab lists "<name> - In battle".
       With four players two of them battle at the same time.
    3. The player runs from the battle (the host fights its battle out: won, or lost and whited out): back on the
       field in the same session; the others draw that player again.
    4. The last player walks out of Route 101 into Littleroot Town (another map): still listed everywhere, its
       Players page says where it is.
    5. The last player closes the game (an ordinary close): the others' rosters and Players tabs drop it; it starts
       again (Join) and is back in everyone's session.
    6. The host store passes its integrity check; the source saves are unchanged.

What the games show is saved as pictures (2D build on Xvfb, 50%). The battles are ordinary wild battles; nothing in
them is changed or asserted beyond the session's view of the player.

    PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime \\
      python scripts/multiplayer/native_session_persistence_proof.py \\
        --game ../engine/pokeemerald-mp --rom pokedev.gba --manifest manifest.json \\
        --source a.sav --source b.sav [--source c.sav --source d.sav] \\
        --display :92 --display :93 [--display :94 --display :95] \\
        --output /private/multiplayer-proof/session-persistence-1
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows-runtime"))
import native_launcher_battle_proof  # noqa: E402
from native_launcher_battle_proof import LauncherHarness  # noqa: E402
from qualify_admission_cleanup import on_worker, require  # noqa: E402

UP, LEFT, RIGHT, DOWN, A, B, START = 64, 32, 16, 128, 1, 2, 8
ROUTE_101, LITTLEROOT = (0, 16), (0, 9)
# Route 101 to Littleroot (native_launcher_multi_proof.py: the rock at (8-11,13), the exit at (10,18-19)).
WAYPOINTS = ((7, None), (7, 16), (10, 16), (10, 19))
NAMES = ("Host Hana", "Friend Finn", "Friend Fay", "Friend Flo")
BATTLE_SECONDS = 25
OUTBREAK_AFTER = 240    # active seconds before this world's first mass outbreak (the default is 8-15 minutes)
OUTBREAK_WAIT = 480


def engine_addresses(game):
    """multiplayer.c's statics follow gMultiplayerMailbox (other files reuse the names sConnected and sFrame). The
    Windows exe (under Wine, mapped at its preferred base) has the same symbols with MinGW's leading underscore."""
    pe = Path(game).read_bytes()[:2] == b"MZ"
    rows = subprocess.run(["nm", str(game)], capture_output=True, text=True, check=True).stdout
    table = {}
    for line in rows.splitlines():
        row = line.split()
        if len(row) == 3:
            name = row[2][1:] if pe and row[2].startswith("_") else row[2]
            table.setdefault(name, []).append(int(row[0], 16))
    base = table["gMultiplayerMailbox"][0]

    def after(name):
        return min((a for a in table[name] if a > base), key=lambda a: a - base)
    return dict(connected=after("sConnected"), last=after("sLastHeartbeatFrame"), frame=after("sFrame"),
                remotes=after("sRemotes"), world=table["gMultiplayerWorldMailbox"][0])


class Session:
    def __init__(self, harness, players, addresses):
        self.h, self.players, self.addresses = harness, players, addresses
        self.timeline = (harness.output / "timeline.jsonl").open("w")
        self.started = time.monotonic()
        self.shots = 0

    # What each side knows -------------------------------------------------
    def game_view(self, player):
        """The game's own multiplayer state, read (never written) from its memory."""
        a = self.addresses
        with open(f"/proc/{player.game.process.pid}/mem", "rb", buffering=0) as memory:
            def read(address, size):
                memory.seek(address)
                return memory.read(size)
            connected = read(a["connected"], 1)[0]
            frame, last = struct.unpack("<I", read(a["frame"], 4))[0], struct.unpack("<I", read(a["last"], 4))[0]
            raw = read(a["remotes"], 84)
            world = read(a["world"], 256)
        peers = []
        for i in range(3):
            record = raw[i * 28:i * 28 + 28]
            token = struct.unpack("<I", record[:4])[0]
            if token:
                peers.append(dict(token=token, map=[record[16], record[17]], activity=record[22]))
        # The shared-world record sits at 48 of the EMW1 mailbox; its bytes 192-199 are the outbreak marker.
        outbreak = list(world[240:248]) if world[:4] == b"EMW1" else None
        return dict(linked=bool(connected), heartbeat_age=frame - last, peers=peers, outbreak=outbreak)

    async def companion_view(self, player):
        async def read(s):
            c = s._companion
            pose = c._local_pose
            return dict(status=s.status.code, connected=c.connected, game_link=c._bridge is not None,
                        session=c.session_epoch,
                        roster={p["display_name"]: (p["presence"] or {}).get("activity") for p in c._players},
                        maps={p["display_name"]: [(p["presence"] or {}).get("map_group"),
                                                  (p["presence"] or {}).get("map_number")] for p in c._players},
                        pose=None if pose is None else [pose.activity, pose.detail, pose.map_group, pose.map_number,
                                                        pose.x, pose.y],
                        spawns=c._world_spawns, outbreak=c.world_inbound().outbreak)
        return await on_worker(player.worker, read)

    async def sessions(self):
        async def read(s):
            return {session.display_name: session.session_epoch for session in s._server.sessions.values()}
        return await on_worker(self.players[0].worker, read)

    async def state(self):
        rows = []
        for player in self.players:
            view = await self.companion_view(player)
            view.pop("spawns")
            rows.append(dict(name=player.name, game=self.game_view(player), **view))
        return rows

    def note(self, kind, **fields):
        row = dict(t=round(time.monotonic() - self.started, 1), kind=kind, **fields)
        self.timeline.write(json.dumps(row) + "\n")
        self.timeline.flush()

    def picture(self, label):
        """Each player's display, the game's window raised above the launcher's."""
        self.shots += 1
        for player in self.players:
            display = {"DISPLAY": self.h.args.display[player.slot]}
            windows = subprocess.run(["xdotool", "search", "--onlyvisible", "--pid", str(player.game.process.pid)],
                                     env=display, capture_output=True, text=True).stdout.split()
            for window in windows:
                subprocess.run(["xdotool", "windowraise", window], env=display, capture_output=True)
            path = self.h.output / f"{self.shots:02d}-{label}-{player.slot}.png"
            subprocess.run(["import", "-window", "root", str(path)], env=display, capture_output=True)
            subprocess.run(["convert", str(path), "-resize", "50%", str(path)], capture_output=True)

    # Play ----------------------------------------------------------------
    async def players_tab(self, player):
        """START > PLAYER > PLAYERS as a player opens it: (title, status, row labels); then closed with B."""
        probe = player.probe
        await self.ensure_field(player)
        await probe.open_players()
        _, screen = await probe.ready()
        result = (screen.title, screen.status, [row.label for row in screen.rows])
        self.picture(f"players-tab-of-{player.slot}")
        async with asyncio.timeout(20):
            while probe.read()["active"]:
                await probe.press(B)
        await asyncio.sleep(1)
        return result

    async def pose(self, player):
        return (await self.companion_view(player))["pose"]

    async def in_battle(self, player):
        pose = await self.pose(player)
        return pose is not None and pose[0] == 0 and pose[1] == 1

    async def on_field(self, player):
        pose = await self.pose(player)
        return pose is not None and pose[0] == 1

    async def run_away(self, player, timeout=180):
        """Run, as a player does: B through the battle's text (B also leaves the move list), then RUN, the bottom
        right of the four actions (Down, Right), and A. Repeated until the field is back: a slow intro or a failed
        escape only costs another round."""
        async with asyncio.timeout(timeout):
            while not await self.on_field(player):
                if await self.in_battle(player):
                    for key in (B, B, DOWN, RIGHT, A):
                        await player.probe.press(key)
                        await asyncio.sleep(.5)
                    await asyncio.sleep(2)
                else:
                    await asyncio.sleep(.5)

    async def win(self, player, timeout=240):
        """Fight, as a player does: A through the battle (FIGHT, the first move, the texts, the level-up box) until
        the field is back. Returns where the player is then (a lost battle whites out to the last place healed)."""
        async with asyncio.timeout(timeout):
            while not await self.on_field(player):
                await player.probe.press(A)
                await asyncio.sleep(.6)
        return await self.pose(player)

    async def ensure_field(self, player, timeout=150):
        """Back on the field: a wild Pokemon that walked up to this idle player is run from (it happens in the
        grass); anything else off the field (a notice, a text) is waited for."""
        async with asyncio.timeout(timeout):
            while not await self.on_field(player):
                if await self.in_battle(player):
                    self.h.record("ran-from-a-wild-pokemon-that-walked-up", slot=player.slot)
                    await self.run_away(player)
                else:
                    await asyncio.sleep(.5)

    async def step(self, player, key, flee=True):
        """One ordinary step; a wild Pokemon that walks up and starts a battle is run from (unless flee is False)."""
        before = await self.pose(player)
        await player.probe.press(key, frames=8, release=1)
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            await asyncio.sleep(.05)
            now = await self.pose(player)
            if now is not None and now[0] == 0:
                await asyncio.sleep(1.5)
                if flee and await self.in_battle(player):
                    self.h.record("ran-from-a-wild-pokemon-on-the-way", slot=player.slot)
                    await self.run_away(player)
                return await self.pose(player)
            if now is not None and before is not None and now[2:] != before[2:]:
                await asyncio.sleep(.3)
                return now
        return await self.pose(player)

    async def start_wild_battle(self, player, seconds=240):
        """An ordinary wild battle, as a player gets one in the grass: stay in the grass where the game started, talk
        to a shared wild Pokemon (A) when one is next to the player or a few clear steps away in a straight line,
        line up with one a few steps away (the shorter way first, the other way when that one is blocked), and
        otherwise wait: wild Pokemon roam and walk up to a player standing in the grass."""
        home = None
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if await self.in_battle(player):
                return True
            view = await self.companion_view(player)
            pose, spawns = view["pose"], view["spawns"] or {}
            if pose is None or pose[0] != 1:
                if pose is not None and pose[1] == 0:
                    # A text over the field (two players talked to the same Pokemon): B closes it.
                    self.note("walk", slot=player.slot, pose=pose, text=True)
                    await player.probe.press(B)
                await asyncio.sleep(1)
                continue
            home = home or (pose[4], pose[5])
            on_map = [spawns.get("map_group"), spawns.get("map_number")] == pose[2:4]
            slots = [s for s in (spawns.get("slots") or []) if on_map and not s.get("busy")]
            near = sorted(slots, key=lambda s: abs(s["x"] - pose[4]) + abs(s["y"] - pose[5]))
            self.note("walk", slot=player.slot, pose=pose, near=[[s["x"], s["y"]] for s in near[:3]])
            target = near[0] if near else None
            dx = dy = 99
            if target is not None:
                dx, dy = target["x"] - pose[4], target["y"] - pose[5]
            if abs(dx) + abs(dy) == 1:
                await player.probe.press((RIGHT if dx > 0 else LEFT) if dx else (DOWN if dy > 0 else UP))  # face it
                await player.probe.press(A)
                await asyncio.sleep(2)
            elif target is not None and (dx == 0 or dy == 0) and abs(dx) + abs(dy) <= 4 \
                    and abs(target["x"] - home[0]) + abs(target["y"] - home[1]) <= 5:
                await self.step(player, (RIGHT if dx > 0 else LEFT) if dx else (DOWN if dy > 0 else UP), flee=False)
            elif target is not None and abs(dx) + abs(dy) <= 6 \
                    and abs(target["x"] - home[0]) + abs(target["y"] - home[1]) <= 6:
                keys = [RIGHT if dx > 0 else LEFT, DOWN if dy > 0 else UP]
                if abs(dy) < abs(dx):
                    keys.reverse()
                for key in keys:
                    moved = await self.step(player, key, flee=False)
                    if moved is None or moved[4:] != pose[4:]:
                        break
            elif abs(pose[4] - home[0]) + abs(pose[5] - home[1]) > 2:
                hx, hy = home[0] - pose[4], home[1] - pose[5]
                await self.step(player, (RIGHT if hx > 0 else LEFT) if hx else (DOWN if hy > 0 else UP))
            else:
                await asyncio.sleep(.5)
        return False

    async def walk_to_littleroot(self, player):
        here = await self.pose(player)
        require(here is not None and tuple(here[2:4]) == ROUTE_101, f"expected Route 101: {here}")
        for x, y in WAYPOINTS:
            for _ in range(40):
                now = await self.pose(player)
                ty = now[5] if y is None else y
                if (now[4], now[5]) == (x, ty):
                    break
                key = (RIGHT if x > now[4] else LEFT) if now[4] != x else (DOWN if ty > now[5] else UP)
                await self.step(player, key)
            else:
                raise AssertionError(f"could not reach {(x, y)} from {await self.pose(player)}")
        for _ in range(10):
            if tuple((await self.pose(player))[2:4]) == LITTLEROOT:
                break
            await self.step(player, DOWN)
        for _ in range(4):
            await self.step(player, DOWN)  # off the town's entrance
        require(tuple((await self.pose(player))[2:4]) == LITTLEROOT, "did not reach Littleroot Town")

    # Checks --------------------------------------------------------------
    async def everyone_linked(self, label):
        state = await self.state()
        self.note("state", label=label, players=state)
        for row in state:
            require(row["game"]["linked"] and len(row["game"]["peers"]) == len(self.players) - 1,
                    f"{row['name']}'s game is not linked to everyone ({label}): {row['game']}")
            require(len(row["roster"]) == len(self.players), f"{row['name']}'s roster is short ({label})")
        return state

    async def hold_battle(self, battlers, label):
        """BATTLE_SECONDS of battle: every other game keeps each battler (hidden), every roster says battle."""
        names = {p.name for p in battlers}
        sessions = await self.sessions()
        end = time.monotonic() + BATTLE_SECONDS
        checked = 0
        while time.monotonic() < end:
            state = await self.state()
            self.note("state", label=label, players=state)
            for row in state:
                require(row["connected"], f"{row['name']}'s companion left the session during {label}")
                for name in names - {row["name"]}:
                    require(row["roster"].get(name) == "battle", f"{row['name']} does not list {name} in battle: {row['roster']}")
                if row["name"] not in names:
                    require(row["game"]["linked"] and len(row["game"]["peers"]) == len(self.players) - 1,
                            f"{row['name']}'s game lost a player during {label}: {row['game']}")
                    battling = [p for p in row["game"]["peers"] if p["activity"] == 0]
                    require(len(battling) >= len(names), f"{row['name']}'s game draws a battling player: {row['game']}")
            require(await self.sessions() == sessions, f"a session was replaced during {label}")
            checked += 1
            await asyncio.sleep(2)
        self.h.record("battle-kept-everyone", label=label, battlers=sorted(names), seconds=BATTLE_SECONDS,
                      observations=checked, sessions=sessions)
        return sessions


async def scenario(harness, players, session):
    record = harness.record
    count = len(players)
    host = players[0]
    for player in players:
        await session.ensure_field(player)
    state = await session.everyone_linked("baseline")
    record("everyone-linked", players=[dict(name=r["name"], peers=len(r["game"]["peers"])) for r in state])
    session.picture("baseline")
    title, status, rows = await session.players_tab(players[1])
    require(status == f"Connected: {count}/4" and any(r.startswith(host.name) for r in rows),
            f"the Players tab does not list everyone: {status} {rows}")
    record("players-tab-baseline", slot=1, status=status, rows=rows)

    # A mass outbreak (this world's settings start the first one four active minutes in, not after 8-15): its place
    # rides in the shared-world record's bytes 192-199 for the Town Map, which the game's bridge refused until
    # 2026-10-19 and then stopped for good, on every game at once.
    async with asyncio.timeout(OUTBREAK_WAIT):
        while not all([(await session.companion_view(p))["outbreak"] for p in players]):
            await asyncio.sleep(1)
    place = (await session.companion_view(host))["outbreak"]
    end = time.monotonic() + 10
    while time.monotonic() < end:
        state = await session.everyone_linked("outbreak")
        for row in state:
            require(row["game"]["outbreak"] == [1, place[0], place[1], 0, 0, 0, 0, 0],
                    f"{row['name']}'s game does not hold the outbreak marker: {row['game']['outbreak']}")
        await asyncio.sleep(2)
    record("outbreak-kept-everyone", map=list(place), markers=[r["game"]["outbreak"] for r in state])

    battles = [[players[0]], [players[1]]] + ([[players[2], players[3]]] if count == 4 else [])
    for battlers in battles:
        label = "battle-" + "-and-".join(str(p.slot) for p in battlers)
        for player in players:
            await session.ensure_field(player)
        # One after the other (two players next to each other would talk to the same Pokemon); each stays in its
        # battle while the next one starts, so the battles run at the same time.
        started = [await session.start_wild_battle(p) for p in battlers]
        require(all(started), f"{label}: no wild battle started")
        require(all([await session.in_battle(p) for p in battlers]), f"{label}: not all in battle at once")
        record("wild-battle-started", label=label, slots=[p.slot for p in battlers])
        session.picture(label + "-started")
        watcher = next(p for p in players if p not in battlers)
        hold = asyncio.create_task(session.hold_battle(battlers, label))
        await asyncio.sleep(6)
        title, status, rows = await session.players_tab(watcher)
        for battler in battlers:
            require(any(r.startswith(battler.name[:12]) and r.endswith("In battle") for r in rows),
                    f"{watcher.name}'s Players tab does not show {battler.name} in battle: {rows}")
        record("players-tab-during-battle", label=label, watcher=watcher.slot, status=status, rows=rows)
        sessions = await hold
        session.picture(label + "-long")
        if os.environ.get("PROOF_PAUSE_IN_BATTLE"):   # diagnostics: leave the games running for a look by hand
            (harness.output / "paused").write_text(json.dumps({p.slot: p.game.process.pid for p in players}))
            await asyncio.sleep(float(os.environ["PROOF_PAUSE_IN_BATTLE"]))
        if battlers == [host]:
            # The host fights this one out: the end of a won (or lost) battle, not only an escape.
            before = await session.pose(host)
            after = await session.win(host)
            record("fought-the-battle-out", label=label, map_before=before[2:4], map_after=after[2:4],
                   outcome="won" if after[2:4] == before[2:4] else "whited out")
        else:
            await asyncio.gather(*(session.run_away(p) for p in battlers))
            record("ran-from-the-battle", label=label)
        for player in players:
            await session.ensure_field(player)
        async with asyncio.timeout(20):
            while True:
                state = await session.state()
                if all(len([q for q in r["game"]["peers"] if q["activity"] == 1]) == count - 1 for r in state):
                    break
                await asyncio.sleep(.5)
        require(await session.sessions() == sessions, f"{label}: a session was replaced when the battle ended")
        session.note("state", label=label + "-after", players=state)
        session.picture(label + "-after")
        record("back-on-the-field-same-session", label=label, sessions=sessions)

    walker = players[-1]
    await session.walk_to_littleroot(walker)
    async with asyncio.timeout(20):
        while True:
            state = await session.state()
            if all(r["maps"][walker.name] == list(LITTLEROOT) for r in state):
                break
            await asyncio.sleep(.5)
    for row in state:
        require(row["game"]["linked"] and len(row["game"]["peers"]) == count - 1, f"{row['name']} lost a player on a map change")
    session.picture("other-map")
    title, status, rows = await session.players_tab(host)
    page = next(r for r in rows if r.startswith(walker.name[:12]))
    record("other-map-still-listed", walker=walker.slot, host_rows=rows)
    await host.probe.open_players()
    await host.probe.choose(page)
    _, screen = await host.probe.ready()
    where = screen.rows[0].label
    session.picture("player-page")
    require(where.split(":")[0] in ("On the field", "Field") and "LITTLEROOT" in where.upper(),
            f"the player page does not say where: {where}")
    record("player-page-says-where", label=where)
    async with asyncio.timeout(20):
        while host.probe.read()["active"]:
            await host.probe.press(B)
    return walker


def create_world_with_an_early_outbreak(*args, **kwargs):
    """The production world, with its outbreak settings file written before anything opens the world: the first
    server (enrollment's) saves the outbreak timer, and every later start resumes that timer."""
    host = create_world(*args, **kwargs)
    path = host.database_path.with_name(host.database_path.name + ".outbreaks.json")
    path.write_text(json.dumps({"first_delay": [OUTBREAK_AFTER, OUTBREAK_AFTER]}))
    return host


create_world = native_launcher_battle_proof.create_world
native_launcher_battle_proof.create_world = create_world_with_an_early_outbreak


async def run(args):
    count = len(args.source)
    require(count in (2, 4) and len(args.display) == count, "two or four sources, one display each")
    harness = LauncherHarness(args, names=NAMES[:count], sources=tuple(args.source), party_counts=(1,) * count,
                              version="Session persistence proof", scope=__doc__.split("\n\n")[0])
    async with harness:
        await harness.setup_world()
        players = []
        for slot in range(count):
            player = await harness.start("session", slot)
            player.name = NAMES[slot]
            players.append(player)
            await harness.ready(player)
        session = Session(harness, players, engine_addresses(args.game.resolve()))
        walker = await scenario(harness, players, session)
        # An ordinary close of the last player's game: gone from every roster and Players tab; then it joins again.
        await harness.close([walker])
        players.remove(walker)
        session.players = players
        async with asyncio.timeout(30):
            while True:
                rosters = [(await session.companion_view(p))["roster"] for p in players]
                if not any(walker.name in roster for roster in rosters):
                    break
                await asyncio.sleep(.5)
        title, status, rows = await session.players_tab(players[0])
        require(status == f"Connected: {count - 1}/4" and not any(r.startswith(walker.name[:12]) for r in rows),
                f"the closed player is still listed: {status} {rows}")
        harness.record("left-and-removed", slot=walker.slot, status=status, rows=rows)
        again = await harness.start("rejoin", walker.slot)
        again.name = walker.name
        players.append(again)
        await harness.ready(again)
        await session.everyone_linked("rejoined")
        title, status, rows = await session.players_tab(players[0])
        require(status == f"Connected: {count}/4", f"the rejoined player is missing: {status} {rows}")
        harness.record("rejoined-and-listed", slot=walker.slot, status=status, rows=rows)
        session.picture("rejoined")
        await harness.close(list(reversed(players)))
        harness.finish()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True, help="native Linux executable, unstripped")
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source", type=Path, action="append", required=True, help="a legacy save per player")
    parser.add_argument("--display", action="append", required=True, help="an X display per player")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0)
    parser.add_argument("--wine", type=Path, action="append")
    parser.add_argument("--sdl", type=Path)
    parser.add_argument("--elf", type=Path)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
