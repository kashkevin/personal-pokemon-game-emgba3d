"""Three native games through the whole launcher: a battle lobby whose format follows who joined (Update 32, feature 10).

The 1v1v1 proof (native_launcher_ffa3_proof.py), started from a lobby instead of the free-for-all row:

    1. Everyone linked ("Connected: 3/4").
    2. The host opens PLAYERS > Challenges > New battle > Battle lobby, invites both friends and sends the
       invitations: the lobby says it waits for two answers. Each friend opens PLAYERS > Battle lobby and joins. The
       host's lobby page then shows the detected format ("1v1v1: 3 joined") and offers "Start 1v1v1" (no other format);
       the host starts it, and both friends accept the challenge it sent (only them: nobody else is pulled in).
    3-5. As the 1v1v1 proof: one native 1v1v1 to its end, back in the world, saves and a fresh Continue.

    PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime \\
      python scripts/multiplayer/native_launcher_lobby_proof.py \\
        --game ../engine/pokeemerald-mp --rom pokedev.gba --manifest manifest.json \\
        --source a.sav --source b.sav --source c.sav --display :94 --display :95 --display :96 \\
        --output /private/multiplayer-proof/native-launcher-lobby-1
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows-runtime"))
from native_launcher_battle_proof import launcher_proof  # noqa: E402
from native_launcher_ffa_proof import MATCH_SECONDS, close_players, into_littleroot  # noqa: E402
from native_launcher_ffa3_proof import ThreePlayerFreeForAll  # noqa: E402
from qualify_admission_cleanup import require  # noqa: E402

PLAYER_NAMES = ("Lobby Host", "Lobby Friend 1", "Lobby Friend 2")


class LobbyFreeForAll(ThreePlayerFreeForAll):
    async def challenge(self, probes, host, record):
        names = [account.display_name for account in host.accounts]
        await probes[0].open_players()
        await probes[0].choose("Challenges")
        await probes[0].choose("New battle")
        await probes[0].choose("Battle lobby")
        for name in names[1:]:
            await probes[0].choose(f"{name[:19]}: No")
        _, screen = await probes[0].choose("Send invitations")
        record("lobby-sent", title=screen.title, status=screen.status, rows=[r.label for r in screen.rows])
        require(screen.status == "Waiting for 2 to answer", f"the new lobby says {screen.status!r}")
        await close_players(probes[0])
        for probe in probes[1:]:
            await probe.open_players()
            _, screen = await probe.choose("Battle lobby")
            require("Join lobby" in [r.label for r in screen.rows], f"no Join row: {[r.label for r in screen.rows]}")
            await probe.choose("Join lobby")
            await close_players(probe)
        await probes[0].open_players()
        _, screen = await probes[0].choose("Battle lobby")
        rows = [r.label for r in screen.rows]
        record("lobby-detected-format", status=screen.status, rows=rows)
        require(screen.status == "1v1v1: 3 joined" and "Start 1v1v1" in rows
                and not any(r.startswith("Start ") and r != "Start 1v1v1" for r in rows),
                f"the lobby detected {screen.status!r} {rows}")
        await probes[0].choose("Start 1v1v1")
        for probe in probes[1:]:
            await probe.open_players()
            await probe.choose("Pending challenge")
            await probe.choose("Accept challenge")


async def run(args):
    require(len(args.source) == 3 and len(args.display) == 3, "three sources and three displays, one per player")
    ffa = LobbyFreeForAll(args.match_seconds)
    await launcher_proof(args, names=PLAYER_NAMES, sources=args.source, party_counts=(1,) * 3, match=ffa.match,
                         version="Native battle lobby proof", settings="windowScale=2\n",
                         scope=__doc__.split("\n\n")[0], after_boot=into_littleroot, after_save=ffa.after_save,
                         environment=dict(SDL_FRAMEBUFFER_ACCELERATION="0"),
                         on_harness=lambda harness: setattr(ffa, "harness", harness))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True, help="native Linux executable, unstripped")
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source", type=Path, action="append", required=True, help="a save per player (three)")
    parser.add_argument("--display", action="append", required=True, help="an X display per player (three)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0)
    parser.add_argument("--match-seconds", type=float, default=MATCH_SECONDS)
    parser.add_argument("--wine", type=Path, action="append", help="(not used)")
    parser.add_argument("--sdl", type=Path)
    parser.add_argument("--elf", type=Path)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
