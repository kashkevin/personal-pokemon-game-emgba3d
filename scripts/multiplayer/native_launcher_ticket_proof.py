"""Two native games through the whole launcher: the Legendary Tickets in real games (owner decision 40;
docs/legendary-tickets.md section 6.6, steps 2 and 3).

The launcher harness of native_launcher_battle_proof.py (real launcher workers and windows, production world creation
and enrollment, the real world server and store, Host Game and Join Game), two native games: on Linux one X display per
player; on Windows itself (the CI runner's tickets-proof job: --game pokeemerald-mp.exe --sdl SDL2.dll --pe-symbols
<nm -n of the exe before its strip> --sizes <nm -S of the Linux build>) both games on the runner's one desktop, their
memory read with ReadProcessMemory (native_windows_process.py), keys posted to each game's own window. The world's ticket
setting is the owner's defaults (legendary_tickets.DEFAULT_SOURCES). The sources are fixture saves the engine's test
build made (make_tower_saves.py tickets-a and tickets-b: the game loads a short-introduction save, sets the fixture's
flags and saves through its own save code; test code, not a legitimately progressed save):

  tickets-a  the world's host: a level-30 Treecko and nothing a ticket asks for (the other player)
  tickets-b  the friend: the Sealed Chamber's three legends defeated (FLAG_DEFEATED_REGIROCK, _REGICE, _REGISTEEL: the
             Old Sea Map's default source, regi_trio) and the game clear (FLAG_SYS_GAME_CLEAR: the ferry sails only
             after the Hall of Fame)

The friend is the one who earns: closing the host's game would close the world for both. Checks, in order (the games'
memory, the host's ledger and wallet stream, the canonical saves; a watcher reads both games' world mailboxes and shown
notices from their start and pictures the banner when a game shows it):

  1. the friend's save on the host (its enrollment) meets regi_trio: the host's ledger earns the Old Sea Map and queues
     one word on the friend's wallet stream (kind 8, index 4: 0x48000004, ticket:old_sea_map:1); the host's player's
     stream and ledger stay empty;
  2. in the friend's running game: one Old Sea Map (Bag and PC), its ship flag (FLAG_ENABLE_SHIP_FARAWAY_ISLAND) and
     received flag (FLAG_RECEIVED_OLD_SEA_MAP), its wallet sequence 1; the receipt 1 on the host, the ledger delivered;
     the banner "OLD SEA MAP!" / "Show it at LILYCOVE's port." in the game's world mailbox and shown by the game (its
     shown notice id), pictured;
  3. the friend's game is killed (SIGKILL; Windows has none: TerminateProcess) after the banner and before any save,
     and started again through the launcher (Join Game): it continues from its save on the host, which has no ticket;
     the host offers the same word again (the save's older wallet sequence); the game applies it: exactly one Old Sea
     Map; still one word on the stream;
  4. the friend saves on the host: the save holds one Old Sea Map, the ship and received flags and wallet sequence 1;
     the friend's PLAYERS > World and my base > Frontier and League > Legendary Tickets says "Old Sea Map: GIVEN"
     (pictured);
  5. after saving, the friend's game is closed and started again (a disconnect and a reconnect): two host passes later
     no second word, no new banner, still one Old Sea Map;
  6. the host's player all along: no word, no ledger row, no Old Sea Map, no ticket banner in its game;
then the harness's closing saves and a fresh Continue of both (every process started again, the world's host first):
the restarted host keeps the ledger (delivered) and sends nothing again.

What it cannot say: the conditions were set by test code, not reached in play (no recorded run has reached the Hall of
Fame); one PC plays both players over its own loopback; on the hosted Windows runner the games run in Classic 2D on
Windows' software renderer.

    PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime PROOF_LIGHT_3D=1 \\
      python scripts/multiplayer/native_launcher_ticket_proof.py \\
        --game pokeemerald-mp-diorama-bfxtest --rom pokedev.gba --manifest manifest.json \\
        --source-a tickets-a.sav --source-b tickets-b.sav --display :96 --display :97 \\
        --output /private/multiplayer-proof/native-launcher-tickets-1

On Windows (no --display):

    python scripts/multiplayer/native_launcher_ticket_proof.py --game pokeemerald-mp.exe --sdl SDL2.dll \\
        --rom pokedev.gba --manifest manifest.json --pe-symbols pokeemerald-mp.nm.txt --sizes pokeemerald-mp.sizes.txt \\
        --source-a tickets-a.sav --source-b tickets-b.sav --output <...>/multiplayer-proof/tickets
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT / "src", ROOT / "scripts" / "multiplayer", ROOT / "scripts" / "windows-runtime"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
from native_launcher_abandon_proof import kill_hard  # noqa: E402
from native_launcher_battle_proof import WINDOWS, game_picture, launcher_proof  # noqa: E402
from qualify_admission_cleanup import on_worker, require  # noqa: E402
from qualify_launcher_session import inspect_closed_head  # noqa: E402
from emerald_multiplayer import legendary_tickets as lt  # noqa: E402
from emerald_multiplayer.flash import inspect_flash  # noqa: E402
from emerald_multiplayer.ownership_protocol import OWNERSHIP_PROFILE  # noqa: E402
from emerald_multiplayer.world_mailbox import WORLD_INBOUND_OFFSET  # noqa: E402

NAMES = ("Ticket Host", "Ticket Friend")
TICKET = lt.TICKET_BY_KEY["old_sea_map"]
WORD, REF = 0x48000000 | TICKET.index, lt.ticket_ref(TICKET.key, 1)
BANNER = "|".join(lt.notice(TICKET))                       # "OLD SEA MAP!|Show it at LILYCOVE's port."
B = 2
# Save block 1 (include/global.h; native_launcher_ffa_proof.py's offsets): 50 PC item slots at 0x498, the Bag's 186 slots
# at 0x560 (quantities XOR the low half of SaveBlock2's encryption key, 0xAC); flags at 0x1270; VAR_MP_WALLET_SEQ at
# 0x1598 (test_tower_service.tower_save).
PC_ITEMS, BAG, BAG_SLOTS, ENCRYPTION_KEY, WALLET_SEQ = 0x498, 0x560, 186, 0xAC, 0x1598
NOTICE_ID, NOTICE_TEXT = 112, slice(116, 180)               # in the world mailbox's inbound record (world_mailbox.pack)


def read_at(probe, address, size):
    """`size` bytes at an address the game holds (a pointer's value: where it is in the running process)."""
    memory = getattr(probe, "memory", None)
    if memory is not None:                     # Windows: ReadProcessMemory (WindowsProbe), the address as it is
        return memory._raw(address, size)
    with open(f"/proc/{probe.pid}/mem", "rb", buffering=0) as memory:
        memory.seek(address)
        return memory.read(size)


def tickets_in(block1: bytes, block2: bytes) -> dict:
    """What a save (or a running game's save blocks) holds of the Old Sea Map: its count in the Bag and in the PC, its
    ship and received flags, the game clear, the Sealed Chamber's flags, and the last wallet word applied."""
    key = struct.unpack_from("<I", block2, ENCRYPTION_KEY)[0] & 0xFFFF
    bag = sum(quantity ^ key for item, quantity in (struct.unpack_from("<HH", block1, BAG + 4 * i)
                                                    for i in range(BAG_SLOTS)) if item == TICKET.item)
    pc = sum(quantity for item, quantity in (struct.unpack_from("<HH", block1, PC_ITEMS + 4 * i) for i in range(50))
             if item == TICKET.item)

    def flag(number):
        return bool(block1[lt.FLAGS_OFFSET + number // 8] >> (number % 8) & 1)
    return dict(bag=bag, pc=pc, ship=flag(TICKET.ship_flag), received=flag(TICKET.received_flag),
                game_clear=flag(lt.FLAG_SYS_GAME_CLEAR), regis=sum(flag(f) for f in lt.REGI_FLAGS),
                wallet_seq=struct.unpack_from("<H", block1, WALLET_SEQ)[0])


def live_tickets(probe) -> dict:
    """tickets_in of the running game's own save blocks (gSaveBlock1Ptr, gSaveBlock2Ptr)."""
    block1 = int.from_bytes(probe.mem("gSaveBlock1Ptr", 4), "little")
    block2 = int.from_bytes(probe.mem("gSaveBlock2Ptr", 4), "little")
    return tickets_in(read_at(probe, block1, lt.SAVE_BLOCK_1_SIZE), read_at(probe, block2, lt.SAVE_BLOCK_2_SIZE))


def saved_tickets(payload: bytes) -> dict:
    parsed = inspect_flash(payload, save_profile=OWNERSHIP_PROFILE)
    return tickets_in(parsed.save_block1, parsed.save_block2)


def world_notice(probe) -> dict:
    """The notice in the game's world mailbox (the host's latest for this player) and the id of the last one the game
    showed (multiplayer_world.c sShownNoticeId)."""
    inbound = probe.mem("gMultiplayerWorldMailbox", 256)[WORLD_INBOUND_OFFSET:]
    return dict(id=struct.unpack_from("<I", inbound, NOTICE_ID)[0],
                text=inbound[NOTICE_TEXT].split(b"\0")[0].decode("ascii", "replace"),
                shown=int.from_bytes(probe.mem("sShownNoticeId", 4), "little"))


class TicketProof:
    def __init__(self, args):
        self.args, self.harness = args, None
        self.watchers, self.seen = {}, {0: [], 1: []}       # slot -> what its game's mailbox and shown id said, in order
        self.pictures = {}

    # ------------------------------------------------------------------------------------------------- watching
    async def after_boot(self, phase, slot, probe, companion):
        """From each game's start: its world mailbox's notices and its shown notice id, in order, and a picture when it
        shows the ticket's banner (it is up for a few seconds, maybe before the match begins)."""
        old = self.watchers.get(slot)
        if old is not None:
            old.cancel()
        self.watchers[slot] = asyncio.create_task(self.watch(phase, slot, probe))

    async def watch(self, phase, slot, probe):
        last = None
        try:
            while True:
                try:
                    notice = world_notice(probe)
                    holding = live_tickets(probe)
                except (OSError, ValueError, KeyError):
                    return                                      # the game has ended
                now = (notice["id"], notice["text"], notice["shown"], holding["bag"] + holding["pc"])
                if now != last:
                    last = now
                    self.seen[slot].append(dict(phase=phase, seconds=round(time.monotonic() - self.harness.started, 1),
                                                **notice, tickets=now[3]))
                    if notice["text"] == BANNER and notice["shown"] == notice["id"] and (phase, slot) not in self.pictures:
                        name = f"banner-{phase}-{slot}.png"
                        self.pictures[(phase, slot)] = name
                        await asyncio.sleep(.5)                 # the window slides in over its first frames
                        await asyncio.to_thread(game_picture, probe, self.harness.output / name, .1)
                        self.harness.record("tickets-banner-shown", phase=phase, slot=slot, notice=notice,
                                            picture=name, quiet=False)
                await asyncio.sleep(.1)
        except asyncio.CancelledError:
            return

    # ------------------------------------------------------------------------------------------------- the host
    async def host_view(self, worker, host):
        """The host's ledger rows, wallet words and the notices it is showing or has queued, for each player."""
        ids = [account.player_id for account in host.accounts[:2]]

        async def read(s):
            server = s._server
            world = server.shared_world
            notices = [n for n in [world._notice, *world._notice_queue] if n is not None]
            return [dict(rows=world.tickets.rows(pid),
                         words=[(w["seq"], w["delta"], w["battle_id"], w["applied"]) for w in server.wagers.pending_for(pid)],
                         notices=[n["text"] for n in notices if n["to"] and pid in n["to"]],
                         tickets_enabled=server.tickets is not None,
                         sources={key: [source.text for source in value]
                                  for key, value in (server.tickets.sources.items() if server.tickets else ())})
                    for pid in ids]
        return await on_worker(worker, read)

    async def until_host(self, worker, host, predicate, seconds, what):
        deadline = time.monotonic() + seconds
        while True:
            view = await self.host_view(worker, host)
            if predicate(view):
                return view
            require(time.monotonic() < deadline, f"{what}: {view}")
            await asyncio.sleep(.5)

    @staticmethod
    async def until_game(probe, predicate, seconds, what):
        deadline = time.monotonic() + seconds
        while True:
            holding = live_tickets(probe)
            if predicate(holding):
                return holding
            require(time.monotonic() < deadline, f"{what}: {holding}")
            await asyncio.sleep(.25)

    async def heads(self, worker, host):
        async def read(s):
            return [inspect_closed_head(s._store, account.player_id) for account in host.accounts[:2]]
        return await on_worker(worker, read)

    def nothing_for_the_host(self, view, probes, record, step):
        """The host's player: no word, no ledger row, no ticket banner, no Old Sea Map in its game."""
        holding = live_tickets(probes[0])
        record("tickets-the-other-player-gets-nothing", step=step, rows=view[0]["rows"], words=view[0]["words"],
               notices=view[0]["notices"], live=holding)
        require(view[0]["rows"] == [] and view[0]["words"] == [], f"the host's player was given something: {view[0]}")
        require(BANNER not in view[0]["notices"], "the host's player was told of a ticket")
        require(holding["bag"] + holding["pc"] == 0 and not holding["ship"], f"the host's game has the ticket: {holding}")
        require(all(entry["text"] != BANNER for entry in self.seen[0]), f"the host's game saw the banner: {self.seen[0]}")

    # -------------------------------------------------------------------------------------------------- the match
    async def match(self, current, probes, games, host, symbols, record):
        harness = self.harness
        # 1. the friend's save on the host earns the Old Sea Map: one word queued, nothing for the host's player
        view = await self.until_host(current[0], host, lambda v: v[1]["words"], 60, "no ticket word for the friend")
        record("tickets-the-setting", enabled=view[0]["tickets_enabled"], sources=view[0]["sources"])
        require(view[0]["tickets_enabled"] and view[0]["sources"] == {k: list(v) for k, v in lt.DEFAULT_SOURCES.items()},
                "the host runs the tickets with the owner's defaults")
        require([w[:3] for w in view[1]["words"]] == [(1, WORD, REF)], f"one Old Sea Map word: {view[1]['words']}")
        require([(r["ticket"], r["source"]) for r in view[1]["rows"]] == [("old_sea_map", "regi_trio")],
                f"the ledger earned the Old Sea Map by the Sealed Chamber: {view[1]['rows']}")
        record("tickets-the-friends-save-earns-the-old-sea-map", rows=view[1]["rows"], words=view[1]["words"])
        # 2. the friend's game applies it: one ticket, its flags, receipt 1, the ledger delivered, the banner shown
        holding = await self.until_game(probes[1], lambda t: t["bag"] + t["pc"] >= 1, 90, "no Old Sea Map in the game")
        require(holding == dict(bag=1, pc=0, ship=True, received=True, game_clear=True, regis=3, wallet_seq=1),
                f"one Old Sea Map in the Bag with its flags: {holding}")
        view = await self.until_host(current[0], host, lambda v: v[1]["rows"][0]["state"] == "delivered", 60,
                                     "the ledger did not settle the receipt")
        require(view[1]["words"] == [(1, WORD, REF, lt.RECEIPT_GIVEN)], f"receipt 1: {view[1]['words']}")
        record("tickets-given-in-the-friends-game", live=holding, rows=view[1]["rows"], words=view[1]["words"])
        deadline = time.monotonic() + 60
        while not any(e["text"] == BANNER and e["shown"] == e["id"] for e in self.seen[1]):
            require(time.monotonic() < deadline, f"the friend's game did not show the banner: {self.seen[1][-5:]}")
            await asyncio.sleep(.25)
        shown = next(e for e in self.seen[1] if e["text"] == BANNER and e["shown"] == e["id"])
        record("tickets-the-banner-in-the-friends-game", notice=shown, picture=self.pictures.get(("battle-and-save", 1)))
        self.nothing_for_the_host(view, probes, record, "given")
        # 3. killed after the banner, before any save: the same word again, one ticket
        heads = await self.heads(current[0], host)
        require(heads[1].revision == 1 and saved_tickets(heads[1].payload)["bag"] == 0, "the friend saved meanwhile")
        game = games[1]
        kill_hard(game.process.pid)     # the game this proof's launcher started: SIGKILL (Windows: TerminateProcess)
        await harness.poll_until(lambda: game.process.returncode is not None, 60)
        await harness.poll_until(lambda: not current[1].busy, 180)
        record("tickets-friend-killed-before-saving", exit_code=game.process.returncode, saved=saved_tickets(heads[1].payload))
        again = await harness.start("rejoin", 1)
        harness.players[1] = again
        current[1], probes[1], games[1] = again.worker, again.probe, again.game
        require(await harness.ready(again) == 1, "the friend's game did not continue from its save on the host")
        holding = await self.until_game(probes[1], lambda t: t["wallet_seq"] == 1, 90, "the word did not come again")
        require(holding["bag"] + holding["pc"] == 1 and holding["ship"] and holding["received"],
                f"exactly one Old Sea Map after the word came again: {holding}")
        await asyncio.sleep(6)                                  # the host's next pass
        view = await self.host_view(current[0], host)
        require(view[1]["words"] == [(1, WORD, REF, lt.RECEIPT_GIVEN)], f"still one word: {view[1]['words']}")
        require(live_tickets(probes[1])["bag"] == 1, "a second Old Sea Map")
        record("tickets-the-same-word-again-one-ticket", live=holding, words=view[1]["words"], rows=view[1]["rows"])
        # 4. saved on the host: the save holds it; the PLAYERS page says so
        await harness.save(again, 2)
        heads = await self.heads(current[0], host)
        saved = saved_tickets(heads[1].payload)
        record("tickets-saved-on-the-host", revision=heads[1].revision, saved=saved)
        require(saved == dict(bag=1, pc=0, ship=True, received=True, game_clear=True, regis=3, wallet_seq=1),
                f"the host's save of the friend: {saved}")
        await self.players_page(probes[1], record)
        # 5. a disconnect and a reconnect after saving: nothing again
        before = await self.host_view(current[0], host)
        await harness.close_game(again.game, again.probe)
        await harness.poll_until(lambda: again.game.process.returncode is not None, 60)
        await harness.poll_until(lambda: not current[1].busy, 180)
        back = await harness.start("reconnect", 1)
        harness.players[1] = back
        current[1], probes[1], games[1] = back.worker, back.probe, back.game
        require(await harness.ready(back) == 2, "the friend's game did not continue from its last save")
        await asyncio.sleep(12)                                 # two host passes
        view = await self.host_view(current[0], host)
        holding = live_tickets(probes[1])
        record("tickets-reconnect-after-saving", words=view[1]["words"], rows=view[1]["rows"], live=holding,
               notices=view[1]["notices"])
        require(view[1]["words"] == before[1]["words"] == [(1, WORD, REF, lt.RECEIPT_GIVEN)], "a second word")
        require(holding["bag"] == 1 and holding["wallet_seq"] == 1, f"the reconnected game: {holding}")
        require(BANNER not in view[1]["notices"] and
                not any(e["phase"] == "reconnect" and e["text"] == BANNER for e in self.seen[1]),
                "a new ticket banner after the reconnect")
        self.nothing_for_the_host(view, probes, record, "after the reconnect")
        return dict(expected=[probe.party_now() for probe in probes], revisions=[2, 3])

    async def players_page(self, probe, record):
        """PLAYERS > World and my base > Frontier and League > Legendary Tickets, and the Old Sea Map's page."""
        from native_launcher_ffa_proof import close_players
        await probe.open_players()
        await probe.choose("World and my base")
        await probe.choose("Frontier and League")
        _, screen = await probe.choose("Legendary Tickets")
        for _ in range(20):
            if screen.title == "Legendary Tickets" and screen.status.startswith("Given"):
                break
            await asyncio.sleep(.5)
            _, screen = await probe.ready()
        rows = [row.label for row in screen.rows]
        name = "players-tickets.png"
        await asyncio.to_thread(game_picture, probe, self.harness.output / name)
        record("tickets-players-page", title=screen.title, status=screen.status, rows=rows, picture=name)
        require((screen.title, screen.status) == ("Legendary Tickets", "Given: 1 of 4"), f"the page: {screen}")
        require("Old Sea Map: GIVEN" in rows and "Eon Ticket: 1/2" in rows, f"the page's rows: {rows}")
        _, screen = await probe.choose("Old Sea Map: GIVEN")
        rows = [row.label for row in screen.rows]
        name = "players-old-sea-map.png"
        await asyncio.to_thread(game_picture, probe, self.harness.output / name)
        record("tickets-players-old-sea-map-page", title=screen.title, status=screen.status, rows=rows, picture=name)
        require((screen.title, screen.status) == ("Old Sea Map", "Show it at LILYCOVE's port.") and
                rows == ["Island: Faraway Island", "Earned: Sealed Chamber", "Back"], f"the ticket's page: {rows}")
        await close_players(probe)

    # ---------------------------------------------------------------------------------------------- after the match
    async def after_save(self, current, host, record):
        heads = await self.heads(current[0], host)
        saved = [saved_tickets(head.payload) for head in heads]
        record("tickets-the-closing-saves", revisions=[h.revision for h in heads], saved=saved)
        require(saved[1]["bag"] == 1 and saved[1]["ship"] and saved[0]["bag"] + saved[0]["pc"] == 0 and not saved[0]["ship"],
                f"the closing saves: {saved}")

    async def after_continue(self, current, probes, host, record):
        """The fresh Continue: every process started again, the world's host first. It keeps the ledger and sends
        nothing again."""
        await asyncio.sleep(12)                                 # two passes of the restarted host
        view = await self.host_view(current[0], host)
        holding = [live_tickets(probe) for probe in probes]
        record("tickets-after-the-host-restart", rows=[v["rows"] for v in view], words=[v["words"] for v in view],
               notices=[v["notices"] for v in view], live=holding)
        require(view[1]["words"] == [(1, WORD, REF, lt.RECEIPT_GIVEN)] and
                [r["state"] for r in view[1]["rows"]] == ["delivered"], f"the restarted host: {view[1]}")
        require(holding[1]["bag"] == 1 and holding[1]["wallet_seq"] == 1, f"the friend's game: {holding[1]}")
        require(BANNER not in view[1]["notices"], "the restarted host announced the ticket again")
        self.nothing_for_the_host(view, probes, record, "after the host restart")
        record("tickets-what-each-game-saw", host=self.seen[0], friend=self.seen[1])
        for task in self.watchers.values():
            task.cancel()


async def run(args):
    if not args.display:
        require(WINDOWS, "an X display per player")
        args.display = ["desktop-0", "desktop-1"]                  # Windows: one desktop; names for the records
    require(len(args.display) == 2, "an X display per player (two)")
    proof = TicketProof(args)
    await launcher_proof(args, names=NAMES, sources=(args.source_a, args.source_b), party_counts=(1, 1),
                         match=proof.match, version="Native Legendary Tickets proof",
                         after_boot=proof.after_boot, settings="windowScale=2\n", scope=__doc__.split("\n\n")[0],
                         environment=dict(SDL_FRAMEBUFFER_ACCELERATION="0"),
                         after_save=proof.after_save, on_harness=lambda h: setattr(proof, "harness", h),
                         after_continue=proof.after_continue)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True,
                        help="the native game (Linux: unstripped symbols; on Windows the Windows exe as the build made it)")
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True, help="with ticket_abi_version 1")
    parser.add_argument("--source-a", type=Path, required=True, help="make_tower_saves.py tickets-a (the host)")
    parser.add_argument("--source-b", type=Path, required=True, help="make_tower_saves.py tickets-b (the friend)")
    parser.add_argument("--display", action="append", help="an X display per player (Linux)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0)
    parser.add_argument("--wine", type=Path, action="append")
    parser.add_argument("--sdl", type=Path, help="Windows: SDL2.dll of the game")
    parser.add_argument("--pe-symbols", type=Path, help="Windows: i686-w64-mingw32-nm -n of the game before its strip")
    parser.add_argument("--sizes", type=Path, help="Windows: nm -S of the Linux build of the same engine commit")
    parser.add_argument("--elf", type=Path)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
