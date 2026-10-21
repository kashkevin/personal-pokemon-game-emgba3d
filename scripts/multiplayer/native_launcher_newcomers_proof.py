"""Two to four new characters in one world, through the whole launcher (the final master update, QM-5 and QM-6).

Every source is a short-introduction save: no Pokemon, a boy or a girl in front of their own house in Littleroot (the
CI makes them with the game's own short introduction). The same proof runs on Linux (one X display per player) and on
Windows itself (the CI runner: every game on one desktop; native_launcher_battle_proof.py). Through real launcher
workers and native games, driven by ordinary key presses:

  1. everyone linked ("Connected: N/4") with no Pokemon in any game or host save; the second player's 1v1 challenge
     and trade offer to the host are refused by name on the page they were made from ("Get a Pokemon in Birch's lab");
  2. the claimers walk from their doors into Professor Birch's lab, each to a ball on the table (other players'
     avatars never block a step, so two can share one), and all claim a starter at the same moment;
  3. everyone saves through the launcher: one owned Pokemon in each claimer's host save, none in the others';
  then, by --scenario:

    lobby   (2-4 players, all claim; first the second player's connection is cut and it joins again) the host invites
            everyone to a battle lobby and all join: the lobby offers the format of the trainers who joined (1v1,
            1v1v1, or 1v1v1v1 and 2v2: --format); everyone accepts and enters, the battle runs to its end and everyone
            is back on the field, linked, with the party of before the battle.
    mixed   (four; the fourth stays without a Pokemon) mixed parties: the fourth's trade offer to the host is refused
            ("Get a Pokemon in Birch's lab") and so is the host's challenge to it ("They have no Pokemon yet"); the
            host invites the other three to a lobby and all join: starting the 1v1v1v1 is refused by name and opens
            nothing; the fourth leaves the lobby, the 1v1v1 of the three runs to its end while the fourth walks into
            the lab and claims its starter; then a second lobby of all four plays --format (2v2 by default).
    busy    (four) at the same time in one world: the host and the second player battle 1v1 while the third offers
            the fourth a trade; with the offer open the fourth's RESET page says "Finish the trade first" and offers
            no reset (the third's too when its game is on the field); they trade, each now holding the other's
            starter; the fourth resets twice from its host save (each time the others' connections carry on and its
            party is the traded one); the third, its starter traded away, faces its ball again: no ball, no starter
            screen, the same Pokemon; the second opens its trainer card and the options and talks to Professor
            Birch while the three others keep drawing it where it stands; the fourth walks out of Littleroot across Route
            101's rescue tiles (VAR_ROUTE101_STATE 1 and 2 scenes): every step lands, no scene starts.
  then the harness's closing saves and a fresh Continue of everyone.

What it cannot say: one PC plays every player over its own loopback; on the hosted Windows runner the games run in
Classic 2D on Windows' software renderer; a new character has no Pokedex yet and Littleroot has no shop, so neither
is opened here.

    PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime \\
      python scripts/multiplayer/native_launcher_newcomers_proof.py --scenario busy \\
        --game ../engine/pokeemerald-mp --rom pokedev.gba --manifest manifest.json \\
        --source boy-1.sav --source girl-1.sav --source boy-2.sav --source girl-2.sav \\
        --display :94 --display :95 --display :96 --display :97 --output /private/multiplayer-proof/newcomers-busy-1
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT / "src", ROOT / "scripts" / "multiplayer", ROOT / "scripts" / "windows-runtime"):
    if str(_path) not in sys.path:              # the Windows runner starts it without PYTHONPATH
        sys.path.insert(0, str(_path))
from native_launcher_battle_proof import WINDOWS, launcher_proof  # noqa: E402
from native_launcher_challenge_proof import pick, shown  # noqa: E402
from native_launcher_ffa_proof import A, DOWN, UP, close_players, players_tab, pose_of, walk_to  # noqa: E402
from native_launcher_lobby4_proof import FourPlayerLobbyProof  # noqa: E402
from native_launcher_newcomer_proof import LAB, LITTLEROOT, NO_POKEMON  # noqa: E402
from native_launcher_soft_reset_proof import SoftResetProof  # noqa: E402
from native_launcher_three_player_proof import ThreePlayerProof, longest_gap  # noqa: E402
from emerald_multiplayer.menu_mailbox import unpack_screen  # noqa: E402
from qualify_admission_cleanup import on_worker, require  # noqa: E402

PLAYER_NAMES = ("New Host", "New Friend 1", "New Friend 2", "New Friend 3")
SCENARIOS = ("lobby", "mixed", "busy")
FORMATS = ("1v1v1v1", "2v2")
MODES = {"1v1": 2, "2v2": 3, "1v1v1v1": 5, "1v1v1": 6}
PEER_NO_POKEMON = "They have no Pokemon yet"
ROUTE_101 = (0, 16)
# A boy starts at (5,9), a girl at (14,9). From there to the lab door (Littleroot (7,16), entered from (7,17)) down the
# free columns 10 and 11 east of the lab (native_launcher_newcomer_proof.py's ways).
STREETS = {"west": ((5, 12), (10, 12), (10, 17), (7, 17)), "east": ((14, 12), (11, 12), (11, 17), (8, 17), (7, 17))}
# In the lab, from its door to below a ball on the table (engine multiplayer_rival.c sLabBalls: Grass (8,4), Fire (9,4),
# Water (10,4)); the right end of the table is reached only along row 5.
TABLES = {"water": ((6, 9), (7, 9), (7, 5), (10, 5)), "fire": ((6, 10), (6, 6), (8, 6), (8, 5), (9, 5)),
          "grass": ((6, 10), (6, 6), (8, 6), (8, 5))}
BALLS = ("water", "fire", "grass", "fire")
# Out of the lab ((6,12) is its door), then from below its door to Littleroot's way north (10,0): Route 101's first rows
# hold the rescue scene's triggers ((10,19)/(11,19), VAR_ROUTE101_STATE 1) and the "don't go" ones ((10,18)/(11,18),
# state 2). A lab character's state is 3 (engine multiplayer_rival.c ApplyIntroState).
FROM_TABLE = ((8, 5), (8, 6), (6, 6), (6, 12))
TO_THE_WAY_NORTH = ((10, 17), (10, 12), (10, 2))
ON_ROUTE_101 = ((10, 18), (10, 16))
START = 8
MENU_ACTION_OPTION, PLAYER_OPTIONS, TRAINER_CARD = 6, 15, 16          # engine src/start_menu.c
BELOW_BIRCH = (6, 5)                     # Birch stands at (6,4) facing down (his aide wanders, so is no target)


class NewcomersProof(SoftResetProof, ThreePlayerProof):
    """The newcomer proof's claims, the soft reset proof's RESET page and the three-player proof's drawing checks, for
    two to four players."""

    send_lobby = FourPlayerLobbyProof.send_lobby
    answer = FourPlayerLobbyProof.answer
    lobby_page = FourPlayerLobbyProof.lobby_page
    accept = FourPlayerLobbyProof.accept

    def __init__(self, scenario, fmt, watch, match_seconds):
        super().__init__(watch, match_seconds)
        self.scenario, self.format = scenario, fmt

    # The claims ---------------------------------------------------------------------------------------------------
    async def walk_to_lab(self, slot, current, probes, record):
        probe, companion = probes[slot], await self.companion_of(current[slot])
        started = time.monotonic()
        here = pose_of(companion)
        require(here is not None and tuple(here[2:4]) == LITTLEROOT, f"{self.harness.names[slot]} is not in Littleroot: {here}")
        for x, y in STREETS["west" if here[4] < 10 else "east"]:
            await walk_to(probe, companion, LITTLEROOT, x, y, record, slot)
        await self.through_door(slot, current, probes, record, UP, LAB)
        for x, y in TABLES[BALLS[slot]]:
            await walk_to(probe, companion, LAB, x, y, record, slot)
        record("at-the-lab-table", player=self.harness.names[slot], ball=BALLS[slot],
               position=list(pose_of(companion)[2:]), seconds=round(time.monotonic() - started, 1))
        return companion

    async def claims(self, slots, current, probes, record):
        """Everyone to their ball (a few seconds apart, as friends arrive), then every claim at the same moment."""
        async def arrive(n, delay):
            await asyncio.sleep(delay)
            return await self.walk_to_lab(n, current, probes, record)
        companions = await asyncio.gather(*(arrive(n, 3 * i) for i, n in enumerate(slots)))
        windows = await asyncio.gather(*(self.claim(n, probes[n], c, record) for n, c in zip(slots, companions)))
        overlap = min(w[1] for w in windows) - max(w[0] for w in windows)
        record("claims-at-once", players=[self.harness.names[n] for n in slots], overlap_seconds=round(overlap, 1),
               windows=[[round(a - self.t0, 1), round(b - self.t0, 1)] for a, b in windows])
        require(overlap > 0, f"the claims did not overlap: {windows}")

    async def save_all(self, current, record, label, slots=None):
        for n in range(len(current)) if slots is None else slots:
            revision = (await self.launcher(current[n]))["revision"]
            require(current[n].request_save(), f"{self.harness.names[n]}: the launcher refused Save now")
            await self.saved(current[n], revision)
        canonical = await self.heads(current, self.harness.host)
        record(label, canonical=canonical, revisions=[(await self.launcher(w))["revision"] for w in current])
        return canonical

    async def refused_with(self, probe, peer, action, record, slot, expected):
        """A choice on a player's page answered by the host's refusal, on that same page."""
        await probe.open_players()
        await probe.choose(peer, prefix=True)
        await probe.choose(action, wait=False)
        async with asyncio.timeout(20):
            while True:
                _, screen = await shown(probe)
                if screen.status != "Choose an interaction":
                    break
                await asyncio.sleep(.2)
        record("refused", player=self.harness.names[slot], peer=peer, action=action, status=screen.status,
               rows=[r.label for r in screen.rows])
        require(screen.status == expected, f"{action}: the menu said {screen.status!r}, expected {expected!r}")
        require(action in [r.label for r in screen.rows], f"{action}: the menu left the player's page")
        await close_players(probe)

    async def nothing_open(self, current, record, label):
        async def open_things(s):
            return dict(battles=len(s._server.battle_desk._active), trades=len(s._server.trade_desk._proposals))
        left = await on_worker(current[0], open_things)
        record(label, **left)
        require(left == dict(battles=0, trades=0), f"{label}: a refused challenge or trade stayed open: {left}")

    # Battles ------------------------------------------------------------------------------------------------------
    async def lobby_battle(self, current, probes, symbols, record, slots, fmt, label):
        """The host's lobby of `slots` (all join), started as `fmt`; accepted, entered, played to its end."""
        names = [a.display_name for a in self.harness.host.accounts]
        invited = [n for n in slots if n != 0]
        await self.send_lobby(probes[0], [names[n] for n in invited], record, label + "-lobby-sent")
        for n in invited:
            await self.answer(probes[n], "Join lobby")
        status, rows = await self.lobby_page(probes[0])
        record(label + "-lobby", status=status, rows=rows)
        offered = {2: ["1v1"], 3: ["1v1v1"], 4: ["1v1v1v1", "2v2"]}[len(slots)]
        require(status == f"{' or '.join(offered)}: {len(slots)} joined" and all(f"Start {f}" in rows for f in offered),
                f"the lobby of {len(slots)} detected {status!r} {rows}")
        _, screen = await probes[0].choose(f"Start {fmt}")
        if fmt == "2v2":
            require(screen.status == "Choose your 2v2 partner", f"the 2v2 start says {screen.status!r}")
            await probes[0].choose(f"With {names[1][:20]}")
        await self.accept(probes, invited)
        return await self.play(current, probes, symbols, record, slots, fmt, label)

    async def play(self, current, probes, symbols, record, slots, fmt, label, meanwhile=None):
        """Enter, drive and finish the accepted battle of `slots`; `meanwhile` (a task of the others') ends before
        everyone's PLAYERS is looked at."""
        before = {n: await probes[n].battle() for n in slots}
        battles = await self.enter(current, probes, slots, record, label)
        modes = [v["mode"] for v in battles.values()]
        require(modes == [MODES[fmt]], f"{label}: started {modes}, expected the {fmt} ({MODES[fmt]})")
        stops, drivers = self.drive(current, probes, symbols, battles, slots)
        results = await self.finish(current, probes, battles, slots, stops, drivers, record, label)
        if meanwhile is not None:
            await meanwhile
        await self.back_on_the_field(current, probes, before, record, label + "-everyone-back")
        return results

    async def back_on_the_field(self, current, probes, before, record, label):
        """Everyone on the field and linked to everyone; each battler's party exactly the one of before the battle;
        no battle left open for anybody."""
        count = len(current)
        async with asyncio.timeout(180):
            while True:
                states = [await self.state_of(w) for w in current]
                if all(v.get("connected") and v.get("game_link") and v.get("roster") == count and v.get("field")
                       for v in states):
                    break
                await asyncio.sleep(.5)
        for n, probe in enumerate(probes):
            status, rows = await players_tab(probe)
            others = [name for m, name in enumerate(self.harness.names) if m != n]
            listed = all(any(row == name or row.startswith(name + " ") for row in rows) for name in others)
            # A notice ("Trade completed and saved") stays on the status line until the player picks a row.
            require(listed and (status == f"Connected: {count}/4" or not status.startswith("Connected")),
                    f"player {n}'s PLAYERS: {status} {rows}")
        for n, old in before.items():
            now = await probes[n].battle()
            require(now["count"] == old["count"] and now["party_sha256"] == old["party_sha256"],
                    f"{self.harness.names[n]}'s party is not the one of before the battle")

        async def clean(s):
            left = [name for name in ("pending-battle.json", "pending-battle-admission.json")
                    if (s.profile_directory / name).exists()]
            waiting = (await s._companion.battle_challenge_rpc("waiting"))["result"]
            return dict(pending_files=left, waiting=waiting, retained=s._battle_retained is not None)
        leftovers = [await on_worker(w, clean) for w in current]
        require(all(not v["pending_files"] and not v["waiting"] and not v["retained"] for v in leftovers),
                f"{label}: a battle still holds somebody: {leftovers}")
        record(label, sessions=[v["epoch"] for v in states], same_parties=[self.harness.names[n] for n in before])

    # Trades and resets --------------------------------------------------------------------------------------------
    async def trade_between(self, current, probes, record, offerer, answerer, while_open=None):
        """The offerer offers the answerer a trade from PLAYERS; `while_open` runs while the offer waits; the answerer
        picks its Pokemon from Pending trade; both confirm; the host applies it (each save two revisions on)."""
        host = self.harness.host
        pair = (offerer, answerer)
        before = {n: (await self.launcher(current[n]))["revision"] for n in pair}
        await probes[offerer].open_players()
        await probes[offerer].choose(host.accounts[answerer].display_name, prefix=True)
        await probes[offerer].choose("Trading", wait=False)
        offered = {offerer: await pick(probes[offerer])}
        if while_open is not None:
            await while_open()
        await probes[answerer].open_players()
        await probes[answerer].choose("Pending trade")
        await probes[answerer].choose("Choose your Pokemon", wait=False)
        offered[answerer] = await pick(probes[answerer])
        record("trade-offers-chosen", offered={self.harness.names[n]: offered[n] for n in pair})
        started, confirmed = time.monotonic(), set()
        while True:
            launchers = {n: await self.launcher(current[n]) for n in pair}
            for n in pair:
                row = probes[n].read()
                if n not in confirmed and row["active"] and not row["waiting"]:
                    try:
                        screen = unpack_screen(row["screen"], allow_trade_reopen=True, allow_battle_admission=True)[1]
                    except ValueError:
                        continue
                    if any(r.label == "Confirm this trade" for r in screen.rows):
                        await pick(probes[n], "Confirm this trade")
                        confirmed.add(n)
                        record("trade-confirmed", player=self.harness.names[n], seconds=round(time.monotonic() - started, 1))
            elapsed = round(time.monotonic() - started)
            if all(v.get("interaction") is None and v.get("trade") is None and v.get("revision") == before[n] + 2
                   for n, v in launchers.items()):
                record("trade-applied", seconds=elapsed,
                       revisions={self.harness.names[n]: [before[n], launchers[n]["revision"]] for n in pair})
                return
            require(elapsed < self.watch, f"the trade did not finish: {launchers}")
            await asyncio.sleep(1)

    async def reset_page_refuses(self, n, current, probes, record, expected):
        screen = await self.open_reset_page(probes[n])
        labels = [r.label for r in screen.rows]
        record("reset-page-refused", player=self.harness.names[n], status=screen.status, rows=labels)
        require(screen.status == expected and "Reset to last host save" not in labels,
                f"{self.harness.names[n]}'s RESET page showed {screen.status!r} {labels}, expected {expected!r}")
        await close_players(probes[n])
        await self.on_field(current[n])

    async def reset_once(self, n, current, probes, games, record, label, battle):
        """RESET > "Reset to last host save" > "Yes, reset now": the launcher starts the game again from the host save
        in the same session; the others' connections carry on; the party is the host save's."""
        others = [m for m in range(len(current)) if m != n]
        epochs = {m: (await self.launcher(current[m]))["epoch"] for m in others}
        canonical = (await self.heads(current, self.harness.host))[n]
        old_pid = games[n].process.pid
        await self.open_reset_page(probes[n])
        await probes[n].choose("Reset to last host save")
        _, screen = await shown(probes[n])
        require([r.label for r in screen.rows] == ["No, go back", "Yes, reset now"], f"the question: {screen}")
        running = battle is not None and not battle.done()
        await self.final_choice(probes[n], "Yes, reset now")
        code, revision = await self.restarted(n, current, probes, games, old_pid, record)
        after = {m: await self.launcher(current[m]) for m in others}
        now = probes[n].party_now()
        record(label, player=self.harness.names[n], code=code, revision=revision, party=now,
               battle_running_at_the_reset=running,
               others={self.harness.names[m]: [epochs[m], after[m]["epoch"], after[m]["connected"]] for m in others})
        require(now == dict(count=canonical["count"], box_crc=canonical["box_crc"]),
                f"after the reset the party is {now}, the host save's {canonical}")
        require(all(after[m]["connected"] and after[m]["epoch"] == epochs[m] for m in others),
                f"a reset changed another player's connection: {epochs} -> {after}")

    async def no_second_claim(self, n, current, probes, record):
        """Facing the table where its ball stood: no ball, A opens no starter screen, the party stays."""
        probe = probes[n]
        before = probe.party_now()
        chooser = probe.symbols["CB2_StarterChoose"][0]
        seen = []
        await probe.press(UP, frames=4, release=20)
        for _ in range(3):
            await probe.press(A, release=40)
            for _ in range(20):
                seen.append(self.screen_of(probe))
                await asyncio.sleep(.1)
        await self.back_to_field(current[n], probe)
        after = probe.party_now()
        record("no-second-claim", player=self.harness.names[n], party=[before, after],
               starter_screen=chooser in seen, position=list(pose_of(await self.companion_of(current[n]))[2:]))
        require(chooser not in seen and after == before, f"{self.harness.names[n]} claimed again: {before} -> {after}")

    # Drawing while in menus ---------------------------------------------------------------------------------------
    async def drawn_while(self, current, probes, record, subject, label, opened, seconds=3):
        """The subject opens something (`opened`); the others keep drawing it where it then stands the whole time. The
        place is taken once it is open (a dialogue walks there first), and only the subject may stand on it: draws()
        matches any player drawn at a place (busy4-2: the dialogue's walk to Birch left a tile another player shared)."""
        observers = [o for o in range(len(probes)) if o != subject]
        await opened()
        places = await self.places(current)
        place = places[subject]
        require(place is not None and all(places[o] != place for o in observers),
                f"{label}: the subject's tile is not its own: {places}")
        samples = await self.sample(probes, observers, place, seconds)
        summary = {self.harness.names[o]: dict(samples=len(v), drawn=sum(v), longest_gap=longest_gap(v))
                   for o, v in samples.items()}
        record("drawn-while", menu=label, player=self.harness.names[subject], place=list(place), observers=summary)
        require(all(all(v) for v in samples.values()), f"{label}: the others stopped drawing the player: {summary}")
        await self.back_to_field(current[subject], probes[subject])

    async def menus_seen(self, current, probes, record, subject):
        probe, worker = probes[subject], current[subject]
        field = probe.symbols["CB2_Overworld"][0]

        async def trainer_card():
            await probe.press(START, release=60)
            await self.to_row(probe, PLAYER_OPTIONS, lambda r: 0 < r["count"] <= len(r["actions"])
                              and PLAYER_OPTIONS in r["actions"][:r["count"]])
            await self.to_row(probe, TRAINER_CARD, lambda r: r["actions"][0] == TRAINER_CARD)
            wanted = probe.symbols["CB2_TrainerCard"][0]
            await self.until(lambda: self.screen(probe) == wanted, 20, "the trainer card")

        async def options():
            await probe.press(START, release=60)
            await self.to_row(probe, MENU_ACTION_OPTION, lambda r: 0 < r["count"] <= len(r["actions"])
                              and MENU_ACTION_OPTION in r["actions"][:r["count"]])
            await self.until(lambda: self.screen(probe) != field, 20, "the options")
            await asyncio.sleep(1)

        async def dialogue():
            companion = await self.companion_of(worker)
            await walk_to(probe, companion, LAB, *BELOW_BIRCH, record, subject)
            await probe.press(UP, frames=4, release=20)          # face Birch
            await probe.press(A, release=60)                     # "Are you curious about your Pokedex rating?"
            await asyncio.sleep(1)

        # first a tile of its own, below Birch (the others stand at the ball table or by the door)
        companion = await self.companion_of(worker)
        await walk_to(probe, companion, LAB, *BELOW_BIRCH, record, subject)
        await self.drawn_while(current, probes, record, subject, "trainer card", trainer_card)
        await self.drawn_while(current, probes, record, subject, "options", options)
        await self.drawn_while(current, probes, record, subject, "a dialogue (Professor Birch)", dialogue)

    # Route 101 ----------------------------------------------------------------------------------------------------
    async def across_route_101(self, n, current, probes, record):
        """Out of the lab and Littleroot, over Route 101's scene tiles and back: every step lands where it was taken."""
        probe, companion = probes[n], await self.companion_of(current[n])
        started = time.monotonic()
        for x, y in FROM_TABLE:
            await walk_to(probe, companion, LAB, x, y, record, n)
        await self.through_door(n, current, probes, record, DOWN, LITTLEROOT)
        for x, y in TO_THE_WAY_NORTH:
            await walk_to(probe, companion, LITTLEROOT, x, y, record, n)
        await self.through_door(n, current, probes, record, UP, ROUTE_101)
        entered = list(pose_of(companion)[2:])
        steps = [entered]
        for x, y in ON_ROUTE_101:
            await walk_to(probe, companion, ROUTE_101, x, y, record, n)
            steps.append(list(pose_of(companion)[2:]))
        record("across-route-101-without-a-scene", player=self.harness.names[n], entered=entered, steps=steps,
               seconds=round(time.monotonic() - started, 1))
        require(tuple(entered[2:]) in ((10, 19), (11, 19)), f"Route 101 entered at {entered}, not its scene row")
        await walk_to(probe, companion, ROUTE_101, 10, 19, record, n)
        await self.through_door(n, current, probes, record, DOWN, LITTLEROOT)
        await walk_to(probe, companion, LITTLEROOT, 10, 3, record, n)

    # The scenarios ------------------------------------------------------------------------------------------------
    async def _match(self, current, probes, games, host, symbols, record):
        self.t0 = time.monotonic()
        count = len(current)
        for n, worker in enumerate(current):
            self.own_display(n, worker)
            self.watch_loop(n, worker)
        for n, probe in enumerate(probes):
            status, rows = await players_tab(probe)
            require(status.startswith(f"Connected: {count}/"), f"player {n}'s PLAYERS: {status} {rows}")
        canonical = await self.heads(current, host)
        record("linked-with-no-pokemon", games=[p.party_now() for p in probes], canonical=canonical)
        require(all(p.party_now()["count"] == 0 for p in probes) and all(c["count"] == 0 for c in canonical),
                "a new character has a Pokemon before its claim")
        host_name = host.accounts[0].display_name
        await self.refused_with(probes[1], host_name, "Rival Battle - 1v1", record, 1, NO_POKEMON)
        await self.refused_with(probes[1], host_name, "Trading", record, 1, NO_POKEMON)
        await self.nothing_open(current, record, "nothing-left-open")

        if self.scenario == "lobby":
            await self.cut_and_rejoin(1, current, probes, games, record)
            await self.claims(range(count), current, probes, record)
            canonical = await self.save_all(current, record, "saved-with-the-starters")
            require(all(c["count"] == 1 and len(c["serials"]) == 1 for c in canonical), f"the host's saves: {canonical}")
            fmt = {2: "1v1", 3: "1v1v1", 4: self.format}[count]
            await self.lobby_battle(current, probes, symbols, record, tuple(range(count)), fmt, fmt)
        elif self.scenario == "mixed":
            await self.mixed(current, probes, games, host, symbols, record)
        else:
            await self.busy(current, probes, games, host, symbols, record)
        parties = await self.heads(current, host)
        revisions = [(await self.launcher(w))["revision"] + 1 for w in current]
        return dict(parties=parties, revisions=revisions)

    async def cut_and_rejoin(self, n, current, probes, games, record):
        """The player's world connection is cut (a cable pulled); its launcher fences the link and keeps the save; it
        joins again with its party as it was."""
        async def cut(s):
            writer = s._companion._remote_writer
            require(writer is not None, "no world connection to cut")
            writer.transport.abort()
        before = (await self.launcher(current[n]))["epoch"]
        await on_worker(current[n], cut)
        async with asyncio.timeout(60):
            while (await self.launcher(current[n])).get("connected"):
                await asyncio.sleep(.5)
        record("connection-cut", player=self.harness.names[n], launcher=await self.launcher(current[n]))
        await asyncio.sleep(5)                        # the launcher's host-loss preservation
        await self.rejoin(n, current, probes, games, record)
        status, _ = await players_tab(probes[n])
        require(status.startswith(f"Connected: {len(current)}/"), f"after joining again PLAYERS says {status}")
        record("joined-again", player=self.harness.names[n], epochs=[before, (await self.launcher(current[n]))["epoch"]],
               party=probes[n].party_now())

    async def mixed(self, current, probes, games, host, symbols, record):
        names = [a.display_name for a in host.accounts]
        await self.claims((0, 1, 2), current, probes, record)
        canonical = await self.save_all(current, record, "saved-with-mixed-parties")
        require([c["count"] for c in canonical] == [1, 1, 1, 0], f"the host's saves: {canonical}")
        await self.refused_with(probes[3], names[0], "Trading", record, 3, NO_POKEMON)
        await self.refused_with(probes[0], names[3], "Rival Battle - 1v1", record, 0, PEER_NO_POKEMON)
        await self.nothing_open(current, record, "nothing-left-open-for-the-one-without-a-pokemon")

        await self.send_lobby(probes[0], names[1:], record, "lobby-sent-to-mixed-parties")
        for n in (1, 2, 3):
            await self.answer(probes[n], "Join lobby")
        status, rows = await self.lobby_page(probes[0])
        record("lobby-with-mixed-parties", status=status, rows=rows)
        require(status == "1v1v1v1 or 2v2: 4 joined" and "Start 1v1v1v1" in rows, f"the lobby says {status!r} {rows}")
        _, screen = await probes[0].choose("Start 1v1v1v1")
        record("start-refused", status=screen.status, rows=[r.label for r in screen.rows])
        require(screen.status == PEER_NO_POKEMON, f"starting with a trainer without a Pokemon said {screen.status!r}")
        await close_players(probes[0])
        await self.nothing_open(current, record, "nothing-open-after-the-refused-start")
        await self.answer(probes[3], "Leave lobby")
        status, rows = await self.lobby_page(probes[0])
        record("lobby-after-the-fourth-left", status=status, rows=rows)
        require(status == "1v1v1: 3 joined" and "Start 1v1v1" in rows, f"the lobby says {status!r} {rows}")
        await probes[0].choose("Start 1v1v1")
        await self.accept(probes, (1, 2))

        async def claim_meanwhile():
            await asyncio.sleep(5)
            companion = await self.walk_to_lab(3, current, probes, record)
            return await self.claim(3, probes[3], companion, record)
        claiming = asyncio.create_task(claim_meanwhile())
        try:
            await self.play(current, probes, symbols, record, (0, 1, 2), "1v1v1", "1v1v1-with-mixed-parties", claiming)
            window = claiming.result()
        finally:
            if not claiming.done():
                claiming.cancel()
                await asyncio.gather(claiming, return_exceptions=True)
        record("claimed-while-the-others-battled", player=names[3], window=[round(w - self.t0, 1) for w in window])
        canonical = await self.save_all(current, record, "saved-after-the-fourth-claim", slots=(3,))
        require(canonical[3]["count"] == 1, f"the fourth's host save: {canonical[3]}")
        await self.lobby_battle(current, probes, symbols, record, (0, 1, 2, 3), self.format, self.format + "-of-four")

    async def busy(self, current, probes, games, host, symbols, record):
        await self.claims((0, 1, 2, 3), current, probes, record)
        canonical = await self.save_all(current, record, "saved-with-the-starters")
        require(all(c["count"] == 1 and len(c["serials"]) == 1 for c in canonical), f"the host's saves: {canonical}")

        await self.challenge_1v1(host, probes, 0, 1)
        before = {n: await probes[n].battle() for n in (0, 1)}
        battles = await self.enter(current, probes, (0, 1), record, "1v1-while-two-others-trade")
        stops, drivers = self.drive(current, probes, symbols, battles, (0, 1))
        battle = asyncio.create_task(self.finish(current, probes, battles, (0, 1), stops, drivers, record, "1v1"))
        try:
            async def while_open():
                await self.reset_page_refuses(3, current, probes, record, "Finish the trade first")
                if not probes[2].read()["active"] and (pose_of(await self.companion_of(current[2])) or (0,))[0] == 1:
                    await self.reset_page_refuses(2, current, probes, record, "Finish the trade first")
                else:
                    record("offerer-waits-in-the-trade-window", player=self.harness.names[2])
            await self.trade_between(current, probes, record, 2, 3, while_open)
            traded = await self.heads(current, host)
            record("traded", canonical=traded)
            require(traded[2]["serials"] == canonical[3]["serials"] and traded[3]["serials"] == canonical[2]["serials"],
                    f"the trade did not swap the starters: {canonical} -> {traded}")
            for k in (1, 2):
                await self.reset_once(3, current, probes, games, record, f"reset-{k}-with-others-playing", battle)
            await battle
        finally:
            if not battle.done():
                battle.cancel()
                await asyncio.gather(battle, return_exceptions=True)
        await self.back_on_the_field(current, probes, before, record, "1v1-everyone-back")
        await self.no_second_claim(2, current, probes, record)
        await self.menus_seen(current, probes, record, 1)
        await self.across_route_101(3, current, probes, record)


async def run(args):
    count = len(args.source)
    require(2 <= count <= 4, "two to four sources (short-introduction saves)")
    require(args.scenario == "lobby" or count == 4, f"--scenario {args.scenario} needs four players")
    if not args.display:
        require(WINDOWS, "an X display per player")
        args.display = [f"desktop-{n}" for n in range(count)]         # Windows: one desktop; names for the records
    proof = NewcomersProof(args.scenario, args.format, args.watch, args.match_seconds)
    await launcher_proof(args, names=PLAYER_NAMES[:count], sources=args.source, party_counts=(0,) * count,
                         match=proof.match, version="Native newcomers proof", settings="windowScale=2\n",
                         scope=__doc__.split("\n\n")[0] + f" Scenario: {args.scenario}, {count} players.",
                         environment=dict(SDL_FRAMEBUFFER_ACCELERATION="0"), after_save=proof.after_save,
                         on_harness=proof.adopt)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", choices=SCENARIOS, required=True)
    parser.add_argument("--format", choices=FORMATS, default=None,
                        help="the battle of four (lobby: 1v1v1v1 by default; mixed: 2v2 by default)")
    parser.add_argument("--game", type=Path, required=True,
                        help="the native game (Linux, unstripped; on Windows the Windows exe as the build made it)")
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source", type=Path, action="append", required=True, help="a short-introduction save per player")
    parser.add_argument("--display", action="append", help="an X display per player (Linux)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0)
    parser.add_argument("--watch", type=float, default=120, help="seconds a trade may take")
    parser.add_argument("--match-seconds", type=float, default=900)
    parser.add_argument("--sdl", type=Path, help="Windows: SDL2.dll of the game")
    parser.add_argument("--pe-symbols", type=Path, help="Windows: i686-w64-mingw32-nm -n of the game before its strip")
    parser.add_argument("--sizes", type=Path, help="Windows: nm -S of the Linux build of the same engine commit")
    parser.add_argument("--wine", type=Path, action="append", help="(not used)")
    parser.add_argument("--elf", type=Path)
    args = parser.parse_args()
    if args.format is None:
        args.format = "2v2" if args.scenario == "mixed" else "1v1v1v1"
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
