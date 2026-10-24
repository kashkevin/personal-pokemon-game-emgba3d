"""Four native games through the whole launcher: battle lobbies of four (Update 32, features 9 and 10).

The lobby's format follows the trainers who joined, and nobody who did not join is pulled in:

    1. Everyone linked ("Connected: 4/4").
    2. The host invites the three others to a lobby ("Waiting for 3 to answer"); two join, the third declines. The
       host's lobby page shows "1v1v1: 3 joined", the third as declined and only "Start 1v1v1". The host starts it; the
       two who joined accept. The one who declined has no challenge (PLAYERS shows none, its launcher holds no
       battle) and stays on the field while the three battle. The 1v1v1 runs with default moves to its end; everyone
       is back in the world with the same parties.
    3. The host invites the three again and all three join: "1v1v1v1 or 2v2: 4 joined" with both "Start 1v1v1v1" and
       "Start 2v2". The host starts the 2v2 with the first friend as partner ("Choose your 2v2 partner", "With <name>");
       everyone accepts; the 2v2 (two teams of two) runs to its end; everyone is back in the world.
    4. The harness's own end: all four save; each save's party is the canonical one; the store passes its integrity
       check; a normal close and a fresh Continue.

    PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime \\
      python scripts/multiplayer/native_launcher_lobby4_proof.py \\
        --game ../engine/pokeemerald-mp --rom pokedev.gba --manifest manifest.json \\
        --source a.sav --source b.sav --source c.sav --source d.sav \\
        --display :94 --display :95 --display :96 --display :97 --output /private/multiplayer-proof/lobby4-1
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows-runtime"))
from native_launcher_abandon_proof import AbandonProof  # noqa: E402
from native_launcher_battle_proof import launcher_proof  # noqa: E402
from native_launcher_ffa_proof import MATCH_SECONDS, close_players, into_littleroot, players_tab  # noqa: E402
from qualify_admission_cleanup import on_worker, require  # noqa: E402

PLAYER_NAMES = ("Lobby4 Host", "Lobby4 Friend 1", "Lobby4 Friend 2", "Lobby4 Friend 3")


class FourPlayerLobbyProof(AbandonProof):
    def __init__(self, watch, match_seconds):
        super().__init__("lobby", 0, watch, match_seconds)

    async def send_lobby(self, probe, names, record, label):
        await probe.open_players()
        await probe.choose("Challenges")
        await probe.choose("New battle")
        await probe.choose("Battle lobby")
        for name in names:
            await probe.choose(f"{name[:19]}: No")
        _, screen = await probe.choose("Send invitations")
        record(label, title=screen.title, status=screen.status, rows=[r.label for r in screen.rows])
        require(screen.status == f"Waiting for {len(names)} to answer", f"the new lobby says {screen.status!r}")
        await close_players(probe)

    async def answer(self, probe, choice, yes=None):
        """``yes``: the choice asks first (Decline..., Leave lobby...): its question's Yes, pressed after the grace in
        which a Yes counts as the asking press repeated (player_menu.ASK_GRACE_SECONDS)."""
        await probe.open_players()
        _, screen = await probe.choose("Battle lobby")
        require(choice in [r.label for r in screen.rows], f"no {choice!r} row: {[r.label for r in screen.rows]}")
        _, screen = await probe.choose(choice)
        if yes is not None:
            require(screen.rows and screen.rows[0].label == "No, keep it", f"{choice!r} did not ask: {screen.title!r}")
            await asyncio.sleep(0.8)
            await probe.choose(yes)
        await close_players(probe)

    async def lobby_page(self, probe):
        await probe.open_players()
        _, screen = await probe.choose("Battle lobby")
        return screen.status, [r.label for r in screen.rows]

    async def accept(self, probes, slots):
        for n in slots:
            await probes[n].open_players()
            await probes[n].choose("Pending challenge")
            await probes[n].choose("Accept challenge")

    async def no_battle(self, worker):
        async def read(s):
            return list(s._companion._bridge.menu_session.menu._battles or ())
        return await on_worker(worker, read)

    async def lobby(self, current, probes, games, host, symbols, record, before):
        names = [a.display_name for a in host.accounts]

        # 2. Two join, one declines: the 1v1v1 of the three who joined.
        await self.send_lobby(probes[0], names[1:], record, "lobby-of-four-sent")
        await self.answer(probes[1], "Join lobby")
        await self.answer(probes[2], "Join lobby")
        await self.answer(probes[3], "Decline...", "Yes, decline it")     # declining asks first (No first)
        status, rows = await self.lobby_page(probes[0])
        record("lobby-after-a-decline", status=status, rows=rows)
        require(status == "1v1v1: 3 joined" and "Start 1v1v1" in rows and f"{names[3][:15]}: declined" in rows
                and not any(r.startswith("Start ") and r != "Start 1v1v1" for r in rows),
                f"the lobby detected {status!r} {rows}")
        await probes[0].choose("Start 1v1v1")          # PLAYERS stays on the challenge (Enter battle comes there)
        await self.accept(probes, (1, 2))
        status, rows = await players_tab(probes[3])
        left_out = await self.no_battle(current[3])
        record("the-one-who-declined-is-left-out", status=status, rows=rows, battles=left_out)
        require("Pending challenge" not in rows and not left_out, f"the player who declined was pulled in: {rows} {left_out}")
        battles = await self.enter(current, probes, (0, 1, 2), record, "1v1v1-from-the-lobby")
        require([v["mode"] for v in battles.values()] == [6], f"the lobby started {battles}")
        stops, drivers = self.drive(current, probes, symbols, battles, (0, 1, 2))
        field = []

        async def stays_on_the_field():
            while True:
                field.append(bool((await self.state_of(current[3])).get("field")))
                await asyncio.sleep(5)
        watcher = asyncio.create_task(stays_on_the_field())
        try:
            await self.finish(current, probes, battles, (0, 1, 2), stops, drivers, record, "1v1v1")
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        record("the-fourth-stayed-on-the-field", samples=len(field), on_field=sum(field))
        require(field and all(field), f"the fourth player left the field during the 1v1v1: {field}")
        await self.world_is_whole(current, probes, before, record, "everyone-back-after-the-1v1v1")

        # 3. All three join: 1v1v1v1 or 2v2; the host starts the 2v2 with the first friend.
        await self.send_lobby(probes[0], names[1:], record, "second-lobby-sent")
        for n in (1, 2, 3):
            await self.answer(probes[n], "Join lobby")
        status, rows = await self.lobby_page(probes[0])
        record("lobby-of-four-joined", status=status, rows=rows)
        require(status == "1v1v1v1 or 2v2: 4 joined" and "Start 1v1v1v1" in rows and "Start 2v2" in rows,
                f"four who joined see {status!r} {rows}")
        _, screen = await probes[0].choose("Start 2v2")
        require(screen.status == "Choose your 2v2 partner", f"the 2v2 start says {screen.status!r}")
        await probes[0].choose(f"With {names[1][:20]}")
        await self.accept(probes, (1, 2, 3))
        battles = await self.enter(current, probes, range(4), record, "2v2-from-the-lobby")
        challenge = next(iter(battles.values()))
        teams = [{self.index(challenge, p) for p in challenge["players"][::2]},
                 {self.index(challenge, p) for p in challenge["players"][1::2]}]
        record("2v2-teams", mode=challenge["mode"], teams=[sorted(t) for t in teams])
        require(challenge["mode"] == 3 and {0, 1} in teams and {2, 3} in teams, f"the 2v2 teams are {teams}")
        stops, drivers = self.drive(current, probes, symbols, battles, range(4))
        await self.finish(current, probes, battles, range(4), stops, drivers, record, "2v2")
        await self.world_is_whole(current, probes, before, record, "everyone-back-after-the-2v2")


async def run(args):
    require(len(args.source) == 4 and len(args.display) == 4, "four sources and four displays, one per player")
    proof = FourPlayerLobbyProof(args.watch, args.match_seconds)
    await launcher_proof(args, names=PLAYER_NAMES, sources=args.source, party_counts=(1,) * 4, match=proof.match,
                         version="Native battle lobby proof (four)", settings="windowScale=2\n",
                         scope=__doc__.split("\n\n")[0], after_boot=into_littleroot,
                         environment=dict(SDL_FRAMEBUFFER_ACCELERATION="0"), on_harness=proof.adopt)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True, help="native Linux executable, unstripped")
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source", type=Path, action="append", required=True, help="a save per player (four)")
    parser.add_argument("--display", action="append", required=True, help="an X display per player (four)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0)
    parser.add_argument("--watch", type=float, default=120)
    parser.add_argument("--match-seconds", type=float, default=MATCH_SECONDS)
    parser.add_argument("--wine", type=Path, action="append", help="(not used)")
    parser.add_argument("--sdl", type=Path)
    parser.add_argument("--elf", type=Path)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
