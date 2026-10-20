"""Two native games through the whole launcher: a Players-menu 1v1 challenge under the conditions of real play.

The owner's report of 2026-10-20: two players on two Windows PCs challenged each other 1v1 from PLAYERS; both had
accepted, both chose "Enter battle", and both games then showed "Waiting for server..." for good. The committed
launcher proofs challenge, accept and enter at once; real play adds a save between accepting and entering, one player
entering long after the other, a connection that dropped earlier. Each scenario does one of those and then watches
both games for --watch seconds: the menu's Enter latch (sBattleAdmissionLatched), its "Waiting for server..." flag,
the native battle hold flags and each launcher's status. A battle that starts is played to its end and both players
must be back on the field; a pair of menus still latched and waiting when the watch ends is recorded as
"stuck-waiting-for-server" with what each launcher and companion knew.

    enter-both     both choose Enter battle at the same moment (the committed proofs' order)
    friend-save    after both accepted, the friend leaves PLAYERS, its launcher saves (what the five-minute autosave
                   does on the field), the friend opens PLAYERS > Pending challenge again, then both enter
    host-save      the same with the host's save
    save-failed    the friend's launcher has given up on saving (a failed autosave or host-loss arm: the
                   "save_recovery_required" state a real network can leave), then both enter
    late-enter     the host enters; the friend enters --late seconds later
    trade          no challenge: the friend offers the host a trade from PLAYERS, both choose their first
                   Pokemon and confirm; both games and launchers are watched until the trade is applied
    trade-battle   the trade, then the usual challenge, acceptance and entry
    trade-walk     the friend offers the host a trade and keeps walking while PLAYERS closes for it (a player
                   does not wait for the trade window); then the usual challenge, acceptance and entry
    reconnect      before the challenge the friend's world connection is cut (its game keeps running); once the
                   companion is back, the usual challenge, acceptance and entry

    PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime \\
      python scripts/multiplayer/native_launcher_challenge_proof.py --scenario friend-save \\
        --game ../engine/pokeemerald-mp --rom pokedev.gba --manifest manifest.json \\
        --source a.sav --source b.sav --display :94 --display :95 --output /private/multiplayer-proof/challenge-1
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from native_launcher_abandon_proof import AbandonProof, Reproduced
from native_launcher_battle_proof import inspect_closed_head, launcher_proof, party, unpack_screen
from native_launcher_ffa_proof import close_players, into_littleroot, players_tab
from qualify_admission_cleanup import on_worker, require

SCENARIOS = ("enter-both", "friend-save", "host-save", "save-failed", "late-enter", "reconnect", "trade",
             "trade-battle", "trade-walk")
PLAYER_NAMES = ("CH Host", "CH Friend")


def trade_phase(session):
    try:
        return json.loads((Path(session._profile_directory) / "pending-trade.json").read_text()).get("phase")
    except (OSError, TypeError, ValueError):
        return None


async def shown(probe, timeout=60):
    """The screen a game shows once it takes input; the trade window's first screen reopens it (flags 2), which
    NativeProbe.ready does not decode."""
    async with asyncio.timeout(timeout):
        while True:
            row = probe.read()
            if row["active"] and not row["waiting"]:
                try:
                    return row, unpack_screen(row["screen"], allow_trade_reopen=True, allow_battle_admission=True)[1]
                except ValueError:
                    pass
            await asyncio.sleep(.03)


async def pick(probe, label=None):
    """A choice by its label, or the first one on the screen (the trade's first Pokemon), as a player picks it."""
    row, screen = await shown(probe)
    found = [n for n, item in enumerate(screen.rows) if item.action and (label is None or item.label == label)]
    require(found, f"no choice {label!r}: {[r.label for r in screen.rows]}")
    for _ in range((found[0] - row["cursor"]) % len(screen.rows)):
        await probe.press(128)
    await probe.press(1)
    return screen.rows[found[0]].label


class ChallengeProof(AbandonProof):
    def __init__(self, scenario, watch, late, match_seconds):
        super().__init__(scenario, 0, watch, match_seconds)
        self.late = late

    # Observations -----------------------------------------------------------------------------------------------
    @staticmethod
    def native(probe):
        row = probe.read()
        try:
            screen = unpack_screen(row["screen"], allow_trade_reopen=True, allow_battle_admission=True)[1]
            text = [screen.title, screen.status]
        except ValueError:
            text = None
        return dict(menu=bool(row["active"]), waiting=bool(row["waiting"]),
                    latched=bool(probe.mem("sBattleAdmissionLatched")[0]), hold=row["hold"], shown=text)

    async def launcher(self, worker):
        async def read(s):
            c = s._companion
            menu = getattr(getattr(c, "_bridge", None), "menu_session", None)
            return dict(code=s.status.code, revision=s._revision, connected=c.connected, epoch=c.session_epoch,
                        interaction=None if s._interaction is None else type(s._interaction).__name__,
                        save_failed=s._save_failed, recovery_failed=s._battle_recovery_failed,
                        admission_failed=getattr(menu, "_battle_admission_failed", None),
                        latched=getattr(menu, "_battle_latched", None),
                        preparing=getattr(menu, "_battle_preparing", None), trade=trade_phase(s))
        try:
            return await on_worker(worker, read)
        except RuntimeError as error:
            return dict(error=str(error))

    async def observe(self, current, probes, slots, record, label):
        """Both games and launchers every 2 s until a battle runs on every core or --watch seconds pass."""
        started = time.monotonic()
        while True:
            natives = {n: self.native(probes[n]) for n in slots}
            launchers = {n: await self.launcher(current[n]) for n in slots}
            elapsed = round(time.monotonic() - started)
            running = all(v["hold"] and not v["menu"] for v in natives.values())
            if running or elapsed >= self.watch or elapsed % 10 < 2:
                record(label, seconds=elapsed, natives={self.harness.names[n]: v for n, v in natives.items()},
                       launchers={self.harness.names[n]: v for n, v in launchers.items()})
            if running:
                return True
            if elapsed >= self.watch:
                return False
            await asyncio.sleep(2)

    async def saved(self, worker, revision, seconds=60):
        async def read(s):
            return s._revision
        async with asyncio.timeout(seconds):
            while (await on_worker(worker, read)) <= revision:
                await asyncio.sleep(.5)

    # The challenge ------------------------------------------------------------------------------------------------
    async def challenge_and_accept(self, host, probes):
        await self.challenge_1v1(host, probes, 0, 1)
        async with asyncio.timeout(60):
            while not all(screen.admission_action for _, screen in [await probes[n].ready() for n in (0, 1)]):
                await asyncio.sleep(.05)

    async def enter_battle(self, current, probes, record, order):
        found = await self.descriptors(current, (0, 1))
        battle = found[0]
        for group in order:
            if isinstance(group, (int, float)) and not isinstance(group, bool) and group < 0:
                await asyncio.sleep(-group)
                continue
            await asyncio.gather(*(probes[n].choose("Enter battle", wait=False) for n in group))
            record("entered", players=[self.harness.names[n] for n in group])
        return {battle["battle_id"]: battle}

    async def match(self, current, probes, games, host, symbols, record):
        for n, worker in enumerate(current):
            self.own_display(n, worker)
            self.watch_loop(n, worker)
        for index, probe in enumerate(probes):
            status, rows = await players_tab(probe)
            # "Connected: 2/4": the players connected, out of the world's four places.
            require(status.startswith(f"Connected: {len(probes)}/"), f"player {index}'s PLAYERS: {status} {rows}")
        record("linked-before-the-challenge", sessions=[(await self.launcher(w)).get("epoch") for w in current])
        order = [(0, 1)]
        if self.scenario == "reconnect":
            async def cut(s):
                s._companion._remote_writer.transport.abort()
            before = (await self.launcher(current[1]))["epoch"]
            await on_worker(current[1], cut)
            async with asyncio.timeout(90):
                while True:
                    state = await self.launcher(current[1])
                    if state.get("connected") and state.get("epoch") != before:
                        break
                    await asyncio.sleep(.5)
            record("friend-reconnected", epochs=[before, state["epoch"]])
            await asyncio.sleep(3)
        if self.scenario == "trade-walk":
            await probes[1].open_players()
            await probes[1].choose(host.accounts[0].display_name, prefix=True)
            await probes[1].choose("Trading", wait=False)
            for step in range(10):
                await probes[1].press(32 if step % 2 == 0 else 16, frames=18, release=2)
            started = time.monotonic()
            while time.monotonic() - started < 30:
                await asyncio.sleep(5)
                record("after-the-trade-walk", seconds=round(time.monotonic() - started),
                       natives={self.harness.names[n]: self.native(probes[n]) for n in (0, 1)},
                       launchers={self.harness.names[n]: await self.launcher(current[n]) for n in (0, 1)})
            for m in (0, 1):
                if probes[m].read()["active"] and not self.native(probes[m])["latched"]:
                    await close_players(probes[m])
        if self.scenario in ("trade", "trade-battle"):
            await self.trade(host, current, probes, record)
            if self.scenario == "trade":
                return await self.traded(host, current, record)
            await asyncio.sleep(3)
        await self.challenge_and_accept(host, probes)
        record("both-accepted", launchers={self.harness.names[n]: await self.launcher(current[n]) for n in (0, 1)})
        if self.scenario in ("friend-save", "host-save"):
            # A game saves only on the field: PLAYERS holds it (a save asked for then waits as "save_not_ready").
            n = 1 if self.scenario == "friend-save" else 0
            await close_players(probes[n])
            revision = (await self.launcher(current[n]))["revision"]
            require(current[n].request_save(), f"{self.harness.names[n]}: the launcher refused Save now")
            await self.saved(current[n], revision)
            record("saved-after-accepting", slot=n, revision=[revision, (await self.launcher(current[n]))["revision"]])
            await probes[n].open_players()
            _, root = await probes[n].ready()
            if "Pending challenge" not in [r.label for r in root.rows]:
                await asyncio.sleep(3)
                screens = {}
                for m in (0, 1):
                    _, screen = await probes[m].ready()
                    screens[self.harness.names[m]] = dict(title=screen.title, status=screen.status,
                                                          rows=[r.label for r in screen.rows])
                record("challenge-gone-after-the-save", screens=screens,
                       launchers={self.harness.names[m]: await self.launcher(current[m]) for m in (0, 1)})
                raise Reproduced("the save ended the accepted challenge; the menus said: " + json.dumps(screens))
            await probes[n].choose("Pending challenge")
            await asyncio.sleep(3)   # the menus' 2 s refresh
            screens = {}
            for m in (0, 1):
                _, screen = await probes[m].ready()
                screens[self.harness.names[m]] = dict(status=screen.status, rows=[r.label for r in screen.rows])
            record("challenge-after-the-save", screens=screens,
                   launchers={self.harness.names[m]: await self.launcher(current[m]) for m in (0, 1)})
            if not all("Enter battle" in v["rows"] for v in screens.values()):
                await self.observe(current, probes, (0, 1), record, "no-enter-offered")
                raise Reproduced("after the save the challenge offers no Enter battle: " + json.dumps(screens))
        elif self.scenario == "save-failed":
            async def give_up(s):
                s._fail_save()
            await on_worker(current[1], give_up)
            record("friend-save-given-up", launcher=await self.launcher(current[1]))
        elif self.scenario == "late-enter":
            order = [(0,), -self.late, (1,)]
        battles = await self.enter_battle(current, probes, record, order)
        if not await self.observe(current, probes, (0, 1), record, "after-entering"):
            record("stuck-waiting-for-server", natives={self.harness.names[n]: self.native(probes[n]) for n in (0, 1)})
            raise Reproduced("both games are still on the challenge screen, waiting for the server")
        stops, drivers = self.drive(current, probes, symbols, battles, (0, 1))
        await self.finish(current, probes, battles, (0, 1), stops, drivers, record, "1v1")
        async with asyncio.timeout(120):
            while not all([(await self.state_of(w)).get("field") for w in current]):
                await asyncio.sleep(.5)
        record("both-back-on-the-field", players=list(self.harness.names))
        if self.scenario == "trade-battle":
            return await self.traded(host, current, record)

    async def traded(self, host, current, record):
        """What the trade left on the host: each player's canonical party, for the closing saves' checks."""
        async def heads(s):
            return [party(inspect_closed_head(s._store, account.player_id)) for account in host.accounts]
        parties = await on_worker(current[0], heads)
        revisions = [(await self.launcher(w))["revision"] for w in current]
        require(len(set(revisions)) == 1, f"the players' revisions differ after the trade: {revisions}")
        return dict(parties=parties, revision=revisions[0] + 1)

    async def trade(self, host, current, probes, record):
        """The friend offers, the host answers, both pick their first Pokemon and confirm: the native trade window
        through the launcher's own handoff (_native_menu_handoff "trade"), as two players do it."""
        before = {n: (await self.launcher(current[n]))["revision"] for n in (0, 1)}
        await probes[1].open_players()
        await probes[1].choose(host.accounts[0].display_name, prefix=True)
        await probes[1].choose("Trading", wait=False)
        offered = {1: await pick(probes[1])}
        await probes[0].open_players()
        await probes[0].choose("Pending trade")
        await probes[0].choose("Choose your Pokemon", wait=False)
        offered[0] = await pick(probes[0])
        record("trade-offers-chosen", offered={self.harness.names[n]: offered[n] for n in (0, 1)})
        started = time.monotonic()
        confirmed = set()
        while True:
            natives = {n: self.native(probes[n]) for n in (0, 1)}
            launchers = {n: await self.launcher(current[n]) for n in (0, 1)}
            for n in (0, 1):
                row = probes[n].read()
                if n not in confirmed and row["active"] and not row["waiting"]:
                    try:
                        screen = unpack_screen(row["screen"], allow_trade_reopen=True, allow_battle_admission=True)[1]
                    except ValueError:
                        continue
                    if any(r.label == "Confirm this trade" for r in screen.rows):
                        await pick(probes[n], "Confirm this trade")
                        confirmed.add(n)
                        record("trade-confirmed", player=self.harness.names[n],
                               seconds=round(time.monotonic() - started, 1))
            elapsed = round(time.monotonic() - started)
            done = all(v.get("interaction") is None and v.get("trade") is None and v.get("revision") == before[n] + 2
                       for n, v in launchers.items())
            if done or elapsed >= self.watch or elapsed % 10 < 2:
                record("trading", seconds=elapsed, natives={self.harness.names[n]: v for n, v in natives.items()},
                       launchers={self.harness.names[n]: v for n, v in launchers.items()})
            if done:
                record("trade-applied", seconds=elapsed, revisions={self.harness.names[n]: [before[n], launchers[n]["revision"]]
                                                                     for n in (0, 1)})
                return
            if elapsed >= self.watch:
                record("trade-stuck", natives={self.harness.names[n]: v for n, v in natives.items()},
                       launchers={self.harness.names[n]: v for n, v in launchers.items()})
                raise Reproduced("the trade did not finish")
            await asyncio.sleep(1)

    async def after_save(self, current, host, record):
        return None


async def run(args):
    require(len(args.source) == 2 and len(args.display) == 2, "two sources and two displays")
    proof = ChallengeProof(args.scenario, args.watch, args.late, args.match_seconds)
    await launcher_proof(args, names=PLAYER_NAMES, sources=args.source, party_counts=(1, 1), match=proof.match,
                         version="Native challenge proof", settings="windowScale=2\n",
                         scope=__doc__.split("\n\n")[0] + " Scenario: " + args.scenario,
                         after_boot=into_littleroot, after_save=proof.after_save,
                         environment=dict(SDL_FRAMEBUFFER_ACCELERATION="0"), on_harness=proof.adopt)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", choices=SCENARIOS, required=True)
    parser.add_argument("--game", type=__import__("pathlib").Path, required=True)
    parser.add_argument("--rom", type=__import__("pathlib").Path, required=True)
    parser.add_argument("--manifest", type=__import__("pathlib").Path, required=True)
    parser.add_argument("--source", type=__import__("pathlib").Path, action="append", required=True)
    parser.add_argument("--display", action="append", required=True)
    parser.add_argument("--output", type=__import__("pathlib").Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0)
    parser.add_argument("--watch", type=float, default=60, help="seconds to watch both games after entering")
    parser.add_argument("--late", type=float, default=45, help="late-enter: seconds between the two entries")
    parser.add_argument("--match-seconds", type=float, default=900)
    parser.add_argument("--wine", type=__import__("pathlib").Path, action="append", help="(not used)")
    parser.add_argument("--sdl", type=__import__("pathlib").Path)
    parser.add_argument("--elf", type=__import__("pathlib").Path)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
