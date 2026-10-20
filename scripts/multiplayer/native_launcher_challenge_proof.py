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
    friend-save    after both accepted, the friend's launcher saves ("Save now"), then both enter
    host-save      the same with the host's save
    late-enter     the host enters; the friend enters --late seconds later
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

from native_launcher_abandon_proof import AbandonProof, Reproduced
from native_launcher_battle_proof import launcher_proof
from native_launcher_ffa_proof import into_littleroot, players_tab
from qualify_admission_cleanup import on_worker, require

SCENARIOS = ("enter-both", "friend-save", "host-save", "late-enter", "reconnect")
PLAYER_NAMES = ("CH Host", "CH Friend")


class ChallengeProof(AbandonProof):
    def __init__(self, scenario, watch, late, match_seconds):
        super().__init__(scenario, 0, watch, match_seconds)
        self.late = late

    # Observations -----------------------------------------------------------------------------------------------
    @staticmethod
    def native(probe):
        row = probe.read()
        return dict(menu=bool(row["active"]), waiting=bool(row["waiting"]),
                    latched=bool(probe.mem("sBattleAdmissionLatched")[0]), hold=row["hold"])

    async def launcher(self, worker):
        async def read(s):
            c = s._companion
            menu = getattr(getattr(c, "_bridge", None), "menu_session", None)
            return dict(code=s.status.code, revision=s._revision, connected=c.connected, epoch=c.session_epoch,
                        interaction=None if s._interaction is None else type(s._interaction).__name__,
                        save_failed=s._save_failed, recovery_failed=s._battle_recovery_failed,
                        admission_failed=getattr(menu, "_battle_admission_failed", None),
                        latched=getattr(menu, "_battle_latched", None),
                        preparing=getattr(menu, "_battle_preparing", None))
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
        async with asyncio.timeout(seconds):
            while (await on_worker(worker, lambda s: s._revision)) <= revision:
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
            require(status == f"Connected: {len(probes)}/{len(probes)}", f"player {index}'s PLAYERS: {status} {rows}")
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
        await self.challenge_and_accept(host, probes)
        record("both-accepted", launchers={self.harness.names[n]: await self.launcher(current[n]) for n in (0, 1)})
        if self.scenario in ("friend-save", "host-save"):
            n = 1 if self.scenario == "friend-save" else 0
            revision = (await self.launcher(current[n]))["revision"]
            require(current[n].request_save(), f"{self.harness.names[n]}: the launcher refused Save now")
            await self.saved(current[n], revision)
            record("saved-after-accepting", slot=n, revision=[revision, (await self.launcher(current[n]))["revision"]])
        elif self.scenario == "late-enter":
            order = [(0,), -self.late, (1,)]
        battles = await self.enter_battle(current, probes, record, order)
        if not await self.observe(current, probes, (0, 1), record, "after-entering"):
            record("stuck-waiting-for-server", natives={self.harness.names[n]: self.native(probes[n]) for n in (0, 1)})
            raise Reproduced("both games are still on the challenge screen, waiting for the server")
        stops, drivers = self.drive(current, probes, symbols, battles, (0, 1))
        await self.finish(current, probes, battles, (0, 1), stops, drivers, record, "1v1")
        async with asyncio.timeout(120):
            while not all((await self.state_of(w)).get("field") for w in current):
                await asyncio.sleep(.5)
        record("both-back-on-the-field", players=list(self.harness.names))

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
