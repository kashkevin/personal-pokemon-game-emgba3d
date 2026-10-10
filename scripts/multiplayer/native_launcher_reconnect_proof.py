"""The launcher's disconnect and reconnect with native games: host lost, progress kept, rejoin.

The owner's rule: if the host is lost, everyone saves and disconnects. Two
players through the whole launcher (the harness of native_launcher_battle_proof.py:
real LauncherWindow, SessionWorker and LauncherSession, a native runtime
bundle, production world creation, host enrollment and invitation):

  1. Host and friend start their games, Continue into Littleroot Town and see
     each other; both walk two steps and save through the launcher
     (revision 2). The friend walks two more steps and does not save.
  2. Disconnect: the host's game closes normally, which ends the host's
     session and its world server. The friend's launcher keeps the running
     game's unsaved progress locally (host_loss_preserved, "close the game and
     rejoin when the host returns"); the friend's game then closes normally.
  3. Reconnect: the host starts again (revision 2); the friend joins again. The
     launcher hands the kept progress to the host as the friend's next
     canonical save (revision 3) and the game continues exactly where the
     friend stood. Both see each other again and save once more (host 3,
     friend 4), close normally, and the host store passes its integrity check;
     the source saves are unchanged.

With --drop the disconnect is a network drop instead: the friend's connection
to the host breaks (the harness aborts the companion's TCP connection, as a
dropped network would) while the host keeps running; the friend's launcher
keeps its progress the same way, the friend's game closes, and the friend
joins the still-running host again (revision 3); the host saves at 3.

Ordinary key presses only (direction keys checked step by step against the
game's reported position); the harness reads the games' memory only to see
what is on screen and compare parties.

    PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime \\
      python scripts/multiplayer/native_launcher_reconnect_proof.py \\
        --game ../engine/pokeemerald-mp --rom pokedev.gba --manifest manifest.json \\
        --source-a a.sav --source-b b.sav --display :98 --display :97 \\
        --output /private/multiplayer-proof/native-launcher-reconnect-1

Windows clients: --wine P1 --wine P2 --sdl SDL2.dll --elf <Linux build>, as in
native_launcher_battle_proof.py.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows-runtime"))
from native_launcher_battle_proof import LauncherHarness  # noqa: E402
from native_launcher_multi_proof import RIGHT, settle, walk_to, where  # noqa: E402
from qualify_admission_cleanup import on_worker, require  # noqa: E402
from qualify_launcher_session import inspect_closed_head  # noqa: E402
from qualify_live_runtime import party  # noqa: E402

LITTLEROOT = (0, 9)
NAMES = ("Reconnect Host", "Reconnect Friend")


async def roster(player):
    async def read(s):
        return sorted(p["player_id"] for p in s._companion._players)
    return await on_worker(player.worker, read)


async def see_each_other(harness, players, timeout=60):
    """Every player's companion lists every player of the world session."""
    ids = sorted(account.player_id for account in harness.host.accounts)
    async with asyncio.timeout(timeout):
        while True:
            views = [await roster(p) for p in players]
            if all(view == ids for view in views):
                return views
            await asyncio.sleep(.25)


async def status(player):
    async def read(s):
        return s.status.code, s.status.revision
    return await on_worker(player.worker, read)


async def walk_right(harness, player, steps):
    # A notice banner (the style hint after 12 s in the field) pauses the field briefly.
    here = await settle(player.probe, player.companion, player.slot)
    require(here[:2] == LITTLEROOT, f"not in Littleroot: {here}")
    await walk_to(player.probe, player.companion, player.slot, LITTLEROOT, here[2] + steps, here[3], steps + 4)
    return where(player.companion)[:4]


async def run(args):
    harness = LauncherHarness(args, names=NAMES, sources=(args.source_a, args.source_b), party_counts=(2, 1),
                              version="Native reconnect proof", scope=__doc__.split("\n\n")[0])
    async with harness:
        record = harness.record
        await harness.setup_world()
        host, friend = [await _start(harness, "play", slot, 1) for slot in (0, 1)]
        record("both-in-the-field", revisions=[1, 1], rosters=await see_each_other(harness, [host, friend]))
        positions = [await walk_right(harness, p, 2) for p in (host, friend)]
        for player in (host, friend):
            await harness.save(player, 2)
        record("both-walked-and-saved", positions=positions, revision=2)
        unsaved = await walk_right(harness, friend, 2)
        record("friend-walked-on-without-saving", position=list(unsaved))

        started = time.monotonic()
        if args.drop:
            # Disconnect: the friend's network drops; the host keeps running.
            async def drop(s):
                writer = s._companion._remote_writer
                require(writer is not None and s._companion.connected, "the friend has no host connection to drop")
                writer.transport.abort()
            await on_worker(friend.worker, drop)
            record("friend-connection-dropped-host-still-running")
        else:
            # Disconnect: the host goes away.
            codes = await harness.close([host])
            record("host-closed-normally", exit_codes=codes)
        async with asyncio.timeout(180):
            while (await status(friend))[0] != "host_loss_preserved":
                require(friend.game.process.returncode is None, "the friend's game exited during host loss")
                await asyncio.sleep(.25)
        async def kept(s):
            names = sorted(p.name for p in s.profile_directory.iterdir() if p.name.startswith("pending-"))
            return dict(status=s.status.code, revision=s.status.revision, pending=names,
                        can_close=s._emergency.result.can_close)
        preserved = await on_worker(friend.worker, kept)
        require(preserved["can_close"], "the launcher did not allow closing after preservation")
        record("friend-progress-kept-locally-after-host-loss", seconds=round(time.monotonic() - started, 1),
               **preserved)
        codes = await harness.close([friend])
        record("friend-closed-normally-to-rejoin-later", exit_codes=codes)

        if args.drop:
            # Reconnect: the friend joins the host that kept running.
            require(host.game.process.returncode is None, "the host's game exited during the friend's drop")
            async def host_view(s):
                return s.status.code, s.status.revision, s._companion.connected
            record("host-still-running", status=list(await on_worker(host.worker, host_view)))
            friend = await _start(harness, "rejoin", 1, 3)
        else:
            # Reconnect: the host returns, the friend joins again.
            host = await _start(harness, "rejoin", 0, 2)
            friend = await _start(harness, "rejoin", 1, 3)
        here = where(friend.companion)
        require(here is not None and list(here[:4]) == list(unsaved),
                f"the friend did not continue where it stood: {here} instead of {unsaved}")
        record("friend-rejoined-where-it-stood", position=list(here[:4]), revision=3,
               rosters=await see_each_other(harness, [host, friend]))
        await harness.save(host, 3)
        await harness.save(friend, 4)
        async def heads(s):
            rows = []
            for slot, account in enumerate(harness.host.accounts):
                head = inspect_closed_head(s._store, account.player_id)
                require(party(head) == harness.expected[slot], "a canonical party changed")
                rows.append(head.revision)
            s._store.integrity_check()
            return rows
        revisions = await on_worker(host.worker, heads)
        require(revisions == [3, 4], f"canonical revisions differ: {revisions}")
        parties = [p.probe.party_now() for p in (host, friend)]
        require(parties == [dict(count=e["count"], box_crc=e["box_crc"]) for e in harness.expected],
                "a running game's party differs from its canonical character")
        record("both-saved-after-rejoining", revisions=revisions, parties=parties)
        codes = await harness.close([friend, host])
        record("normal-close", exit_codes=codes)
        harness.finish()


async def _start(harness, phase, slot, revision):
    player = await harness.start(phase, slot)
    got = await harness.ready(player)
    require(got == revision, f"{harness.names[slot]} started at revision {got}, expected {revision}")
    harness.record("launcher-game-ready", phase=phase, slot=slot, pid=player.game.process.pid, revision=got,
                   position=list(where(player.companion)[:4]))
    return player


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True,
                        help="native Linux executable, unstripped (or the Windows exe with --wine)")
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-a", type=Path, required=True)
    parser.add_argument("--source-b", type=Path, required=True)
    parser.add_argument("--display", action="append", required=True, help="an X display per player (twice)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0)
    parser.add_argument("--wine", type=Path, action="append", help="a Wine prefix per player: Windows clients")
    parser.add_argument("--sdl", type=Path, help="SDL2.dll for the Windows game")
    parser.add_argument("--elf", type=Path, help="the Linux build of the same engine commit (symbol sizes)")
    parser.add_argument("--drop", action="store_true",
                        help="the friend's network drops while the host keeps running (instead of the host closing)")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
