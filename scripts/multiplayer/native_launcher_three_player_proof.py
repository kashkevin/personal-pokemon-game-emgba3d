"""Three native games through the whole launcher: three players in one world (Update 32, features 6 and 7).

Two of the three characters have a Pokemon (the Route 101 saves) and one is a new character with none (a
short-introduction save), so the world holds mixed parties. Through real launcher workers and native games, one per X
display, driven by ordinary key presses:

    1. Everyone linked: PLAYERS says "Connected: 3/4" in every game.
    2. All three walk to the middle of Littleroot Town: every game draws the other two where their own games say they
       stand (the game's own record of the players it draws: multiplayer.c sRemotes).
    3. Menus (feature 6): the second player opens the START menu, the bag, the party screen and PLAYERS in turn;
       sampled ten times a second, both other games keep drawing it where it stands. While it is in the bag the new
       character takes a step: the host draws it on its new tile (the others keep playing).
    4. The new character asks the host for a trade: refused by name ("Get a Pokemon in Birch's lab"), nothing left open.
    5. While the host and the second player trade (both confirm; the host applies it), the new character walks into
       Professor Birch's lab (another map: the other two stop drawing it and it draws nobody), claims its starter and
       walks out again: drawn by both again, and drawing them. Then it saves through its launcher.
    6. The second player's connection is cut (a cable pulled); it joins again: PLAYERS "Connected: 3/4" everywhere and
       everyone drawn again.
    7. The host and the second player play a 1v1 while the new character walks: they are hidden from it during the
       battle and drawn again once they are back on the field.
    8. The harness's own end: all three save; each canonical save holds the traded or claimed Pokemon; the store passes
       its integrity check; a normal close and a fresh Continue.

The three-player battles (1v1v1) have proofs of their own: native_launcher_ffa3_proof.py and
native_launcher_lobby_proof.py.

    PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime \\
      python scripts/multiplayer/native_launcher_three_player_proof.py \\
        --game ../engine/pokeemerald-mp --rom pokedev.gba --manifest manifest.json \\
        --source route101.sav --source route101-b.sav --source newcomer.sav \\
        --display :94 --display :95 --display :96 --output /private/multiplayer-proof/three-players-1
"""
from __future__ import annotations

import argparse
import asyncio
import subprocess
import struct
import time
from pathlib import Path

from native_launcher_battle_proof import inspect_closed_head, launcher_proof, party
from native_launcher_ffa_proof import (A, B, DOWN, LEFT, RIGHT, UP, close_players, into_littleroot, players_tab,
                                       pose_of, step, walk_to)
from native_launcher_newcomer_proof import LAB, LITTLEROOT, NO_POKEMON, NewcomerProof
from qualify_admission_cleanup import on_worker, require

PLAYER_NAMES = ("3P Host", "3P Friend", "3P Newcomer")
HOST, FRIEND, NEWCOMER = 0, 1, 2
START = 8
# Where the three meet in Littleroot (open ground between the houses and the lab), and each one's way there from
# where it stands after into_littleroot (the Route 101 players at (4,3) and (7,3), the new character at its door).
MEET = {HOST: ((8, 3), (8, 10)), FRIEND: ((10, 3), (10, 11)), NEWCOMER: ((13, 11),)}
# The new character's way to the lab door (7,16) and, inside, to the Fire ball (9,4); and back out.
TO_LAB, TO_TABLE = ((11, 11), (11, 17), (7, 17)), ((6, 10), (6, 6), (8, 6), (8, 5), (9, 5))
FROM_TABLE, BACK = ((8, 5), (8, 6), (6, 6), (6, 12)), ((11, 17), (11, 12), (12, 11))
# START menu actions (start_menu.c) and the screens they open.
MENU_ACTION_POKEMON, MENU_ACTION_BAG = 1, 2
OBJECT_EVENTS_COUNT, MAX_PEERS = 16, 3


def remotes(probe):
    """The other players as this game holds them (multiplayer.c sRemotes: struct MultiplayerPeer, then the object it
    draws for the peer, OBJECT_EVENTS_COUNT when none): each peer's place and whether it is drawn."""
    raw = probe.mem("sRemotes")
    size = len(raw) // MAX_PEERS
    rows = []
    for i in range(MAX_PEERS):
        base = i * size
        player = int.from_bytes(raw[base:base + 4], "little")
        if player:
            x, y = struct.unpack_from("<hh", raw, base + 12)
            rows.append(dict(place=(raw[base + 16], raw[base + 17], x, y), activity=raw[base + 22],
                             drawn=raw[base + 24] < OBJECT_EVENTS_COUNT))
    return rows


def draws(probe, place):
    return any(row["drawn"] and row["place"] == place for row in remotes(probe))


def in_view(observer, subject):
    """multiplayer.c PeerVisible's window around the observer (its own tile, without MAP_OFFSET), on one map."""
    return (observer[:2] == subject[:2] and observer[2] - 9 <= subject[2] <= observer[2] + 10
            and observer[3] - 7 <= subject[3] <= observer[3] + 9)


def longest_gap(samples, period=.1):
    longest = run = 0
    for drawn in samples:
        run = 0 if drawn else run + 1
        longest = max(longest, run)
    return round(longest * period, 1)


class ThreePlayerProof(NewcomerProof):
    async def places(self, current):
        found = []
        for worker in current:
            companion = await self.companion_of(worker)
            pose = pose_of(companion)
            found.append(None if pose is None else tuple(pose[2:]))
        return found

    async def everyone_drawn(self, current, probes, record, label, timeout=30):
        """Every game draws each other player that stands in its view; all of them do here."""
        started = time.monotonic()
        while True:
            places = await self.places(current)
            table = {}
            for o, probe in enumerate(probes):
                for s in range(len(probes)):
                    if s != o:
                        table[f"{self.harness.names[o]} sees {self.harness.names[s]}"] = dict(
                            in_view=places[o] is not None and places[s] is not None and in_view(places[o], places[s]),
                            drawn=places[s] is not None and draws(probe, places[s]))
            if all(v["in_view"] and v["drawn"] for v in table.values()):
                record(label, seconds=round(time.monotonic() - started, 1), places=places)
                return places
            if time.monotonic() - started > timeout:
                record(label + "-failed", places=places, table=table, remotes=[remotes(p) for p in probes])
                raise AssertionError(f"{label}: not everyone draws everyone: {table}")
            await asyncio.sleep(.5)

    def screenshot(self, slot, name):
        """The game's own window, raised above its launcher's (evidence for a person; the checks read memory)."""
        probe = self.harness.players[slot].probe
        path = self.harness.output / f"{name}.png"
        try:
            window = probe._window()
            subprocess.run(["xdotool", "windowraise", window], env=probe.environment, capture_output=True, timeout=10)
            time.sleep(.3)
        except (RuntimeError, subprocess.SubprocessError):
            window = "root"
        subprocess.run(["import", "-window", window, str(path)], capture_output=True, timeout=30, env=probe.environment)
        return path.name

    @staticmethod
    def screen(probe):
        return probe.code(int.from_bytes(probe.mem("gMain", 8)[4:8], "little"))

    async def until(self, predicate, timeout, what):
        async with asyncio.timeout(timeout):
            while not predicate():
                await asyncio.sleep(.05)

    async def on_field(self, worker, timeout=30):
        companion = await self.companion_of(worker)
        async with asyncio.timeout(timeout):
            while (pose_of(companion) or (0,))[0] != 1:
                await asyncio.sleep(.1)

    async def open_start_menu(self, worker, probe):
        companion = await self.companion_of(worker)
        await probe.press(START, release=40)
        async with asyncio.timeout(15):     # the START menu on the field: the game reports a menu (detail 2)
            while (pose_of(companion) or (1, 0))[:2] != (0, 2):
                await asyncio.sleep(.05)
        await asyncio.sleep(.5)
        row = probe.read()
        return row["actions"][:row["count"]], row["start_cursor"]

    async def start_menu_item(self, worker, probe, action, screen_symbol):
        actions, cursor = await self.open_start_menu(worker, probe)
        require(action in actions, f"no START menu action {action}: {actions}")
        target = actions.index(action)
        for _ in range((target - cursor) % len(actions)):
            await probe.press(DOWN)
        require(probe.read()["start_cursor"] == target, "the START menu cursor did not reach its item")
        await probe.press(A)
        wanted = probe.symbols[screen_symbol][0]
        await self.until(lambda: self.screen(probe) == wanted, 20, screen_symbol)

    async def back_to_field(self, worker, probe, timeout=30):
        companion = await self.companion_of(worker)
        async with asyncio.timeout(timeout):
            while (pose_of(companion) or (0,))[0] != 1:
                await probe.press(B, release=40)
                await asyncio.sleep(.4)

    async def sample(self, probes, observers, place, seconds):
        samples = {o: [] for o in observers}
        started = time.monotonic()
        while time.monotonic() - started < seconds:
            for o in observers:
                samples[o].append(draws(probes[o], place))
            await asyncio.sleep(.1)
        return samples

    async def menus(self, current, probes, record):
        """Feature 6: the second player in four menus; both others keep drawing it where it stands."""
        subject, observers = FRIEND, (HOST, NEWCOMER)
        place = (await self.places(current))[subject]
        results = {}

        async def watch(label, seconds, during=None):
            task = asyncio.create_task(self.sample(probes, observers, place, seconds))
            extra = await during() if during is not None else None
            samples = await task
            results[label] = {self.harness.names[o]: dict(samples=len(v), drawn=sum(v), longest_gap=longest_gap(v))
                              for o, v in samples.items()}
            record("menu-drawn", menu=label, place=list(place), observers=results[label], **(extra or {}))
            require(all(all(v) for v in samples.values()), f"{label}: the others stopped drawing the player: {results[label]}")

        await self.open_start_menu(current[subject], probes[subject])
        await watch("START menu", 3)
        await self.back_to_field(current[subject], probes[subject])

        async def newcomer_steps():
            """While the second player is in its bag the new character walks a tile: the host draws it there."""
            await asyncio.sleep(1)
            companion = await self.companion_of(current[NEWCOMER])
            moved = await step(probes[NEWCOMER], companion, LEFT, record, NEWCOMER)
            new_place = tuple(moved[2:])
            started = time.monotonic()
            while not draws(probes[HOST], new_place):
                require(time.monotonic() - started < 5, f"the host does not draw the new character at {new_place}")
                await asyncio.sleep(.1)
            seen_after = round(time.monotonic() - started, 1)
            await asyncio.sleep(1)
            await step(probes[NEWCOMER], companion, RIGHT, record, NEWCOMER)
            return dict(newcomer_stepped_to=list(new_place), host_drew_it_after=seen_after)

        await self.start_menu_item(current[subject], probes[subject], MENU_ACTION_BAG, "CB2_BagMenuRun")
        shots = [self.screenshot(o, f"{self.harness.names[o].split()[-1].lower()}-sees-the-friend-in-its-bag")
                 for o in observers] + [self.screenshot(subject, "the-friend-in-its-bag")]
        await watch("bag", 5, newcomer_steps)
        record("screenshots", files=shots)
        await self.back_to_field(current[subject], probes[subject])

        await self.start_menu_item(current[subject], probes[subject], MENU_ACTION_POKEMON, "CB2_UpdatePartyMenu")
        await watch("party", 4)
        await self.back_to_field(current[subject], probes[subject])

        await probes[subject].open_players()
        await watch("PLAYERS", 3)
        await close_players(probes[subject])
        await self.on_field(current[subject])
        return results

    async def three_connected(self, probe, index, when, record):
        """PLAYERS lists both other players; its status line says "Connected: 3/4" unless it shows the player's last
        notice instead (a trade's "Trade completed and saved" stays until the player picks a row)."""
        status, rows = await players_tab(probe)
        others = [name for n, name in enumerate(self.harness.names) if n != index]
        listed = all(any(row == name or row.startswith(name + " ") for row in rows) for name in others)
        record("players-tab", player=self.harness.names[index], when=when, status=status, rows=rows)
        require(listed and (status == "Connected: 3/4" or not status.startswith("Connected")),
                f"player {index}'s PLAYERS {when}: {status} {rows}")

    async def walk(self, slot, current, probes, record, area, points):
        companion = await self.companion_of(current[slot])
        for x, y in points:
            await walk_to(probes[slot], companion, area, x, y, record, slot)
        return companion

    async def through_door(self, slot, current, probes, record, key, area):
        companion = await self.companion_of(current[slot])
        for _ in range(6):
            after = await step(probes[slot], companion, key, record, slot)
            if after is not None and tuple(after[2:4]) == area:
                break
        require(tuple(pose_of(companion)[2:4]) == area, f"{self.harness.names[slot]} did not reach {area}: {pose_of(companion)}")
        await self.on_field(current[slot])

    async def lab_trip(self, current, probes, record):
        """The new character's way into the lab (another map), its claim, and its way back to the others."""
        await asyncio.sleep(3)                  # the trade's first menus open before the walk starts
        started = time.monotonic()
        await self.walk(NEWCOMER, current, probes, record, LITTLEROOT, TO_LAB)
        await self.through_door(NEWCOMER, current, probes, record, UP, LAB)
        own = (await self.places(current))[NEWCOMER]
        await asyncio.sleep(2)
        seen = {self.harness.names[o]: draws(probes[o], own) for o in (HOST, FRIEND)}
        drawn_there = [row for row in remotes(probes[NEWCOMER]) if row["drawn"]]
        record("newcomer-in-the-lab", place=list(own), drawn_by_others=seen, draws=drawn_there,
               seconds=round(time.monotonic() - started, 1))
        require(not any(seen.values()) and not drawn_there, "players on two maps still draw each other")
        companion = await self.walk(NEWCOMER, current, probes, record, LAB, TO_TABLE)
        claimed = await self.claim(NEWCOMER, probes[NEWCOMER], companion, record)
        await self.walk(NEWCOMER, current, probes, record, LAB, FROM_TABLE)
        await self.through_door(NEWCOMER, current, probes, record, DOWN, LITTLEROOT)
        await self.walk(NEWCOMER, current, probes, record, LITTLEROOT, BACK)
        record("newcomer-back-from-the-lab", seconds=round(time.monotonic() - started, 1))
        return claimed

    async def heads(self, current, host):
        async def read(s):
            return [party(inspect_closed_head(s._store, a.player_id)) for a in host.accounts]
        return await on_worker(current[0], read)

    async def after_save(self, current, host, record):
        """Every player walked after the saves the match returned (friendship rises with steps: win-ch4-enter-3), so
        what each one just saved is what its game must hold: the same Pokemon (count and owned serials) as before."""
        saved = await self.heads(current, host)
        for n, new in enumerate(saved):
            old = self.harness.expected[n]
            require((new["count"], new["serials"]) == (old["count"], old["serials"]),
                    f"{self.harness.names[n]} came back with other Pokemon: {old} -> {new}")
            self.harness.expected[n] = new
        record("closing-saves-hold-the-same-pokemon", parties={self.harness.names[n]: v for n, v in enumerate(saved)})

    async def _match(self, current, probes, games, host, symbols, record):
        self.t0 = time.monotonic()
        for n, worker in enumerate(current):
            self.own_display(n, worker)
            self.watch_loop(n, worker)
        for index, probe in enumerate(probes):
            status, rows = await players_tab(probe)
            require(status == "Connected: 3/4", f"player {index}'s PLAYERS: {status} {rows}")
        before = await self.heads(current, host)
        record("linked-with-mixed-parties", sessions=[(await self.launcher(w)).get("epoch") for w in current],
               games=[p.party_now() for p in probes], canonical=before)
        require([p.party_now()["count"] for p in probes] == [1, 1, 0], "the three parties are not 1, 1 and 0")

        # 2. Everyone to the middle of Littleroot; every game draws the other two.
        await asyncio.gather(*(self.walk(n, current, probes, record, LITTLEROOT, MEET[n]) for n in (HOST, FRIEND, NEWCOMER)))
        await self.everyone_drawn(current, probes, record, "everyone-drawn")

        # 3. Menus.
        await self.menus(current, probes, record)

        # 4. The new character's trade offer is refused by name.
        await self.refused(probes[NEWCOMER], host.accounts[HOST].display_name, "Trading", record, NEWCOMER)
        async def open_things(s):
            return dict(battles=len(s._server.battle_desk._active), trades=len(s._server.trade_desk._proposals))
        left = await on_worker(current[0], open_things)
        record("nothing-left-open", **left)
        require(left == dict(battles=0, trades=0), f"a refused trade stayed open: {left}")

        # 5. Host and friend trade while the new character goes to the lab, claims and comes back.
        trade_started = time.monotonic()
        _, claim = await asyncio.gather(self.trade(host, current, probes, record), self.lab_trip(current, probes, record))
        record("trade-and-lab-trip-overlapped", trade_started=round(trade_started - self.t0, 1),
               claim=[round(t - self.t0, 1) for t in claim])
        for n in (HOST, FRIEND):
            await self.on_field(current[n], 60)
        await self.everyone_drawn(current, probes, record, "everyone-drawn-after-the-trade-and-the-claim")
        revision = (await self.launcher(current[NEWCOMER]))["revision"]
        require(current[NEWCOMER].request_save(), "the new character's launcher refused Save now")
        await self.saved(current[NEWCOMER], revision)
        after = await self.heads(current, host)
        record("saved-after-the-trade-and-the-claim", before=before, after=after,
               revisions=[(await self.launcher(w))["revision"] for w in current])
        require(after[HOST]["serials"] == before[FRIEND]["serials"] and after[FRIEND]["serials"] == before[HOST]["serials"],
                f"the trade did not swap the two Pokemon: {before} -> {after}")
        require(after[NEWCOMER]["count"] == 1 and len(after[NEWCOMER]["serials"]) == 1,
                f"the new character's save does not hold its starter: {after[NEWCOMER]}")

        # 6. The friend's connection is cut; it joins again.
        async def cut(s):
            writer = s._companion._remote_writer
            require(writer is not None, "no world connection to cut")
            writer.transport.abort()
        epoch = (await self.launcher(current[FRIEND]))["epoch"]
        await on_worker(current[FRIEND], cut)
        async with asyncio.timeout(60):
            while (await self.launcher(current[FRIEND])).get("connected"):
                await asyncio.sleep(.5)
        record("friend-connection-cut", launcher=await self.launcher(current[FRIEND]),
               others=[(await self.launcher(current[n])).get("connected") for n in (HOST, NEWCOMER)])
        await asyncio.sleep(5)
        await self.rejoin(FRIEND, current, probes, games, record)
        for index, probe in enumerate(probes):
            await self.three_connected(probe, index, "after the rejoin", record)
        await self.walk(FRIEND, current, probes, record, LITTLEROOT, MEET[FRIEND][-1:])
        await self.everyone_drawn(current, probes, record, "everyone-drawn-after-the-rejoin")
        record("friend-joined-again", epochs=[epoch, (await self.launcher(current[FRIEND]))["epoch"]],
               parties=[p.party_now() for p in probes])

        # 7. A 1v1 of host and friend while the new character walks.
        await self.challenge_and_accept(host, probes)
        battles = await self.enter_battle(current, probes, record, [(HOST, FRIEND)])
        require(await self.observe(current, probes, (HOST, FRIEND), record, "after-entering"), "the battle did not start")
        self.explorers = asyncio.create_task(self.explore(current, probes, (NEWCOMER,)))
        stops, drivers = self.drive(current, probes, symbols, battles, (HOST, FRIEND))
        hidden = dict(samples=0, both_hidden=0)

        async def watch_battlers():
            while True:
                rows = remotes(probes[NEWCOMER])
                hidden["samples"] += 1
                hidden["both_hidden"] += not any(r["drawn"] for r in rows)
                await asyncio.sleep(.5)
        watcher = asyncio.create_task(watch_battlers())
        try:
            await self.finish(current, probes, battles, (HOST, FRIEND), stops, drivers, record, "1v1")
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        record("battlers-hidden-from-the-walker", **hidden)
        require(hidden["both_hidden"] > 0, "the new character's game drew the two players all through their battle")
        async with asyncio.timeout(120):
            while not all([(await self.state_of(w)).get("field") for w in current]):
                await asyncio.sleep(.5)
        back = time.monotonic()
        self.explorers.cancel()
        await asyncio.gather(self.explorers, return_exceptions=True)
        self.explorers = None
        record("newcomer-explored", explored=self.explored[NEWCOMER])
        require(self.explored[NEWCOMER]["steps"] >= 10, f"the new character did not walk: {self.explored}")
        await self.everyone_drawn(current, probes, record, "everyone-drawn-after-the-battle")
        record("battlers-drawn-again", seconds=round(time.monotonic() - back, 1))

        parties = await self.heads(current, host)
        revisions = [(await self.launcher(w))["revision"] + 1 for w in current]
        return dict(parties=parties, revisions=revisions)


async def run(args):
    proof = ThreePlayerProof(args.watch, args.match_seconds)
    require(len(args.source) == 3 and len(args.display) == 3, "three sources and three displays")
    await launcher_proof(args, names=PLAYER_NAMES, sources=args.source, party_counts=(1, 1, 0), match=proof.match,
                         version="Native three-player proof", settings="windowScale=2\n",
                         scope=__doc__.split("\n\n")[0], after_boot=into_littleroot, after_save=proof.after_save,
                         environment=dict(SDL_FRAMEBUFFER_ACCELERATION="0"), on_harness=proof.adopt)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source", type=Path, action="append", required=True,
                        help="two saves with a Pokemon (Route 101), then a short-introduction save")
    parser.add_argument("--display", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0)
    parser.add_argument("--watch", type=float, default=120, help="seconds the trade may take")
    parser.add_argument("--match-seconds", type=float, default=900)
    parser.add_argument("--wine", type=Path, action="append", help="(not used)")
    parser.add_argument("--sdl", type=Path)
    parser.add_argument("--elf", type=Path)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
