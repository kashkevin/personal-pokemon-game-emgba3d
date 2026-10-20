"""Two new characters with no Pokemon through the whole launcher: host, join, menus, reconnect, starters, a battle.

Update 32: a new character starts with no Pokemon (the short introduction: boy or girl, a name, the save in
Littleroot) and claims its starter from the Poke Balls on the table in Professor Birch's lab. Both sources are
short-introduction saves with an empty party. The proof, through real launcher workers and native games:

  1. production world creation and host enrollment of both characters, no Pokemon at all;
  2. both linked (PLAYERS "Connected: 2/4"); both games and the host's canonical saves hold no Pokemon;
  3. the friend's 1v1 challenge and trade offer are refused by name on the page they were made from
     ("Get a Pokemon in Birch's lab"), and no challenge or trade is left open on the host;
  4. the friend's world connection is cut (a cable pulled): its launcher fences the link and preserves the save, as
     it does for every lost host; the friend joins again and is linked with its empty party (a reconnect);
  5. both walk from their house door to the lab and claim a starter in overlapping moments (the host the Water
     ball, the friend the Fire ball): one Pokemon each, the table empty in both games;
  6. both save through the launcher: the host's canonical parties hold that one Pokemon each, with owned serials;
  7. the host challenges the friend, both enter and the battle is played to its end;
  then the harness's closing saves and a fresh Continue of both (the claimed starters stay theirs).

    PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime \\
      python scripts/multiplayer/native_launcher_newcomer_proof.py \\
        --game ../engine/pokeemerald-mp --rom pokedev.gba --manifest manifest.json \\
        --source host-intro.sav --source friend-intro.sav --display :94 --display :95 \\
        --output /private/multiplayer-proof/newcomer-1
"""
from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

from native_launcher_battle_proof import inspect_closed_head, launcher_proof, party
from native_launcher_challenge_proof import ChallengeProof, shown
from native_launcher_ffa_proof import A, B, UP, close_players, players_tab, pose_of, step, walk_to
from qualify_admission_cleanup import on_worker, require

PLAYER_NAMES = ("NC Host", "NC Friend")
LITTLEROOT, LAB = (0, 9), (1, 4)
NO_POKEMON = "Get a Pokemon in Birch's lab"
# From each house door to the lab door (Littleroot (7,16)) down the two free columns east of the lab; then inside
# the lab from its door (6,12) up to the table. The right end of the table is reached only along row 5, so the host
# (first) goes on to the Water ball (10,4) and the friend stops below the Fire ball (9,4).
STREET = {0: ((5, 12), (10, 12), (10, 17), (7, 17)), 1: ((14, 12), (11, 12), (11, 17), (8, 17), (7, 17))}
TABLE = {0: ((6, 9), (7, 9), (7, 5), (10, 5)), 1: ((6, 10), (6, 6), (8, 6), (8, 5), (9, 5))}


class NewcomerProof(ChallengeProof):
    def __init__(self, watch, match_seconds):
        super().__init__("enter-both", watch, 0, match_seconds, True, False)

    async def refused(self, probe, peer, action, record, slot):
        """The friend's choice on the host's page is answered by the host's refusal, on that same page."""
        await probe.open_players()
        await probe.choose(peer, prefix=True)
        await probe.choose(action, wait=False)
        async with asyncio.timeout(20):
            while True:
                _, screen = await shown(probe)
                if screen.status != "Choose an interaction":
                    break
                await asyncio.sleep(.2)
        record("refused-with-no-pokemon", player=self.harness.names[slot], action=action, status=screen.status,
               rows=[r.label for r in screen.rows])
        require(screen.status == NO_POKEMON, f"{action}: the menu said {screen.status!r}, expected {NO_POKEMON!r}")
        require(action in [r.label for r in screen.rows], f"{action}: the menu left the player's page")
        await close_players(probe)

    async def to_lab_and_claim(self, slot, current, probes, record):
        probe, companion = probes[slot], current[slot]._companion
        started = time.monotonic()
        here = pose_of(companion)
        require(here is not None and tuple(here[2:4]) == LITTLEROOT, f"{self.harness.names[slot]} is not in Littleroot: {here}")
        for x, y in STREET[slot]:
            await walk_to(probe, companion, LITTLEROOT, x, y, record, slot)
        for _ in range(6):                                   # the lab door is the tile above (7,17)
            after = await step(probe, companion, UP, record, slot)
            if after is not None and tuple(after[2:4]) == LAB:
                break
        require(tuple(pose_of(companion)[2:4]) == LAB, f"{self.harness.names[slot]} did not enter the lab: {pose_of(companion)}")
        for x, y in TABLE[slot]:
            await walk_to(probe, companion, LAB, x, y, record, slot)
        record("at-the-lab-table", player=self.harness.names[slot], position=list(pose_of(companion)[2:]),
               seconds=round(time.monotonic() - started, 1))
        before = probe.party_now()
        require(before["count"] == 0, f"{self.harness.names[slot]} has a Pokemon before the claim: {before}")
        claim_started = time.monotonic()
        await probe.press(UP, frames=4, release=20)          # face the ball (a tap turns, the ball does not let a step)
        await probe.press(A, release=120)                     # the 18-starter screen
        await asyncio.sleep(1.5)
        await probe.press(A, release=60)                      # the ball's own starter
        await asyncio.sleep(2.5)
        await probe.press(A, release=60)                      # YES
        async with asyncio.timeout(30):
            while probe.party_now()["count"] == 0:
                await asyncio.sleep(.2)
        await asyncio.sleep(4)                                # the fanfare
        for _ in range(8):                                    # B: NO to the nickname, then the last message
            await probe.press(B, release=40)
        async with asyncio.timeout(30):
            while (pose_of(companion) or (0,))[0] != 1:
                await asyncio.sleep(.2)
        claimed = probe.party_now()
        record("claimed-a-starter", player=self.harness.names[slot], party=claimed,
               started=round(claim_started - self.t0, 1), finished=round(time.monotonic() - self.t0, 1))
        require(claimed["count"] == 1, f"{self.harness.names[slot]}: party {claimed} after the claim")
        return claim_started, time.monotonic()

    async def _match(self, current, probes, games, host, symbols, record):
        self.t0 = time.monotonic()
        for n, worker in enumerate(current):
            self.own_display(n, worker)
            self.watch_loop(n, worker)
        for index, probe in enumerate(probes):
            status, rows = await players_tab(probe)
            require(status.startswith(f"Connected: {len(probes)}/"), f"player {index}'s PLAYERS: {status} {rows}")
        async def heads(s):
            return [party(inspect_closed_head(s._store, a.player_id)) for a in host.accounts]
        canonical = await on_worker(current[0], heads)
        record("linked-with-no-pokemon", games=[p.party_now() for p in probes], canonical=canonical)
        require(all(p.party_now()["count"] == 0 for p in probes) and all(c["count"] == 0 for c in canonical),
                "a new character has a Pokemon before its claim")

        await self.refused(probes[1], host.accounts[0].display_name, "Rival Battle - 1v1", record, 1)
        await self.refused(probes[1], host.accounts[0].display_name, "Trading", record, 1)
        async def open_things(s):
            return dict(battles=len(s._server.battle_desk._active), trades=len(s._server.trade_desk._proposals))
        left = await on_worker(current[0], open_things)
        record("nothing-left-open", **left)
        require(left == dict(battles=0, trades=0), f"a refused challenge or trade stayed open: {left}")

        async def cut(s):
            writer = s._companion._remote_writer
            require(writer is not None, "no world connection to cut")
            writer.transport.abort()                  # a cable pulled: no goodbye, the socket just dies
        before = (await self.launcher(current[1]))["epoch"]
        await on_worker(current[1], cut)
        async with asyncio.timeout(60):
            while (await self.launcher(current[1])).get("connected"):
                await asyncio.sleep(.5)
        record("friend-connection-cut", launcher=await self.launcher(current[1]))
        await asyncio.sleep(5)                        # the launcher's host-loss preservation
        await self.rejoin(1, current, probes, games, record)
        status, _ = await players_tab(probes[1])
        require(status.startswith("Connected: 2/"), f"after joining again PLAYERS says {status}")
        canonical = await on_worker(current[0], heads)
        record("friend-joined-again-with-no-pokemon", epochs=[before, (await self.launcher(current[1]))["epoch"]],
               games=[p.party_now() for p in probes], canonical=canonical)
        require(all(p.party_now()["count"] == 0 for p in probes) and all(c["count"] == 0 for c in canonical),
                "a Pokemon appeared across the reconnect")

        # Both claim; the friend starts a few seconds later so the two do not meet in the lab's door.
        async def friend():
            await asyncio.sleep(4)
            return await self.to_lab_and_claim(1, current, probes, record)
        windows = await asyncio.gather(self.to_lab_and_claim(0, current, probes, record), friend())
        overlap = min(w[1] for w in windows) - max(w[0] for w in windows)
        record("claims-overlapped", seconds=round(overlap, 1))

        for n in (0, 1):
            revision = (await self.launcher(current[n]))["revision"]
            require(current[n].request_save(), f"{self.harness.names[n]}: the launcher refused Save now")
            await self.saved(current[n], revision)
        canonical = await on_worker(current[0], heads)
        record("saved-with-the-starters", canonical=canonical,
               revisions=[(await self.launcher(w))["revision"] for w in current])
        require(all(c["count"] == 1 and len(c["serials"]) == 1 for c in canonical),
                f"the host's saves do not hold one owned Pokemon each: {canonical}")

        await self.challenge_and_accept(host, probes)
        battles = await self.enter_battle(current, probes, record, [(0, 1)])
        require(await self.observe(current, probes, (0, 1), record, "after-entering"), "the battle did not start")
        stops, drivers = self.drive(current, probes, symbols, battles, (0, 1))
        await self.finish(current, probes, battles, (0, 1), stops, drivers, record, "1v1")
        async with asyncio.timeout(120):
            while not all([(await self.state_of(w)).get("field") for w in current]):
                await asyncio.sleep(.5)
        record("both-back-on-the-field", players=list(self.harness.names))
        # What the closing saves must hold: each character's canonical party now, one revision on.
        parties = await on_worker(current[0], heads)
        revisions = [(await self.launcher(w))["revision"] + 1 for w in current]
        return dict(parties=parties, revisions=revisions)


async def run(args):
    proof = NewcomerProof(args.watch, args.match_seconds)
    require(len(args.source) == 2 and len(args.display) == 2, "two sources and two displays")
    await launcher_proof(args, names=PLAYER_NAMES, sources=args.source, party_counts=(0, 0), match=proof.match,
                         version="Native newcomer proof", settings="windowScale=2\n", scope=__doc__.split("\n\n")[0],
                         environment=dict(SDL_FRAMEBUFFER_ACCELERATION="0"), on_harness=proof.adopt)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source", type=Path, action="append", required=True, help="two short-introduction saves")
    parser.add_argument("--display", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0)
    parser.add_argument("--watch", type=float, default=60, help="seconds to watch both games after entering")
    parser.add_argument("--match-seconds", type=float, default=900)
    parser.add_argument("--wine", type=Path, action="append", help="(not used)")
    parser.add_argument("--sdl", type=Path)
    parser.add_argument("--elf", type=Path)
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
