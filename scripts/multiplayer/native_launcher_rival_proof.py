"""Native games through the whole launcher: Update 31's rival checkpoint battle between real players (Route 110).

The rival checkpoints (docs/update31-rival-checkpoints.md) with the launcher harness of native_launcher_battle_proof.py
(real launcher workers, the production world, enrollment, the Players menu): two games (--players 2: one 1v1) or three
(--players 3: the round robin of three 1v1s, one at a time, that three present players get), Linux or (Windows mode) the
Windows exe on Windows. Their sources are fixture saves the engine's test build made (make_tower_saves.py rival-a,
rival-b, rival-c: a level-5 starter each, on Route 110 just south of its rival line, VAR_ROUTE110_STATE 0). Every step
is a player's presses; the checks read the games' memory, the host's rival coordinator and battle results and, after the
harness's saves, the canonical checkpoints.

  1. The host's rival record reaches both games (each companion's world rival record: without it a game falls back to
     the original NPC rival scene after ten seconds).
  2. Player 1 walks north onto the line: the armed gate stops the player ("Your rivals meet here!", a step back south)
     and opens the Players menu by itself.
  3. Everyone opens "Rival checkpoint" ("Rival: Route 110") and chooses "Start Now"; everyone present chose it, so the
     5 s countdown runs and the host commits the session: the ready match's two trainers see "Battle: <1> vs <2>".
  4. The first of them chooses it (an ordinary challenge carrying the checkpoint's battle environment); the other "Open
     Challenges to accept" > "Accept challenge"; both "Enter battle": the native 1v1 runs to its end, with a durable
     result. Three players: the next match's two trainers do the same, until all three are played.
  5. The host completes the checkpoint for everyone ("via battle") and each game's record says so.
  6. Each steps onto the line again: the original reward scene, once - the Dowsing Machine, VAR_ROUTE110_STATE 1.
  7. The harness's saves: each holds the Dowsing Machine, VAR_ROUTE110_STATE 1 and FLAG_HIDE_ROUTE_110_RIVAL; its own
     end follows (the parties unchanged, the store's integrity check, a normal close, a fresh Continue).

    PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime \\
      python scripts/multiplayer/native_launcher_rival_proof.py \\
        --game ../engine/pokeemerald-mp --rom pokedev.gba --manifest manifest.json \\
        --source-a rival-a.sav --source-b rival-b.sav --display :96 --display :97 \\
        --output /private/multiplayer-proof/native-launcher-rival-1
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
from pathlib import Path
import struct
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows-runtime"))
from native_launcher_abandon_proof import AbandonProof  # noqa: E402
from native_launcher_battle_proof import WINDOWS, launcher_proof  # noqa: E402
from native_launcher_ffa_proof import close_players, pose_of  # noqa: E402
from native_launcher_multi_proof import field_state  # noqa: E402
from native_launcher_tower_proof import read_at  # noqa: E402
from qualify_admission_cleanup import on_worker, require  # noqa: E402
from qualify_launcher_session import inspect_closed_head  # noqa: E402
from emerald_multiplayer.flash import inspect_flash  # noqa: E402
from emerald_multiplayer.ownership_protocol import OWNERSHIP_PROFILE  # noqa: E402

NAMES = ("Rival Host", "Rival Friend", "Rival Third")
A, B, UP = 1, 2, 64
ROUTE110, LINE_Y, CHECKPOINT, BIT = (0, 25), 56, "route110", 1 << 2     # the third checkpoint in story order
# SaveBlock1 (engine include/global.h): flags at 0x1270, vars at 0x139C (from VARS_START 0x4000); the bag's 186 slots
# at 0x560, quantities XOR the low half of SaveBlock2's encryption key (0xAC).
VAR_ROUTE110_STATE = 0x139C + 2 * (0x4069 - 0x4000)
FLAG_HIDE_ROUTE_110_RIVAL = 0x397
FLAGS, BAG, BAG_SLOTS, ENCRYPTION_KEY = 0x1270, 0x560, 186, 0xAC
ITEM_DOWSING_MACHINE = 712


def route110_state(probe) -> int:
    """VAR_ROUTE110_STATE in the running game (gSaveBlock1Ptr's vars)."""
    pointer = int.from_bytes(probe.mem("gSaveBlock1Ptr", 4), "little")
    return int.from_bytes(read_at(probe, pointer + VAR_ROUTE110_STATE, 2), "little")


def saved_rival(payload: bytes) -> dict:
    """What the reward leaves in a checkpoint: VAR_ROUTE110_STATE, FLAG_HIDE_ROUTE_110_RIVAL, the Dowsing Machines."""
    parsed = inspect_flash(payload, save_profile=OWNERSHIP_PROFILE)
    block1, block2 = parsed.save_block1, parsed.save_block2
    key = struct.unpack_from("<I", block2, ENCRYPTION_KEY)[0] & 0xFFFF
    slots = [struct.unpack_from("<HH", block1, BAG + 4 * i) for i in range(BAG_SLOTS)]
    flag = block1[FLAGS + FLAG_HIDE_ROUTE_110_RIVAL // 8] >> (FLAG_HIDE_ROUTE_110_RIVAL % 8) & 1
    return dict(route110_state=struct.unpack_from("<H", block1, VAR_ROUTE110_STATE)[0], hide_rival_flag=flag,
                dowsing_machines=sum(quantity ^ key for item, quantity in slots if item == ITEM_DOWSING_MACHINE))


async def rows_until(probe, wanted, timeout, label):
    """The open page's rows until one passes `wanted` (the Players pages refresh every two seconds)."""
    deadline = time.monotonic() + timeout
    while True:
        _, screen = await probe.ready()
        rows = [row.label for row in screen.rows]
        if any(wanted(row) for row in rows):
            return screen
        require(time.monotonic() < deadline, f"{label}: not on the page {screen.title!r} {screen.status!r} {rows}")
        await asyncio.sleep(.5)


class RivalProof(AbandonProof):
    """The match and the saves' check for launcher_proof (the battle helpers are the interrupted battle proof's)."""

    def __init__(self, match_seconds):
        super().__init__("rival", 0, 0, match_seconds)
        self.before = None

    async def record_of(self, worker):
        async def read(s):
            rival = s._companion._world_rival
            return None if rival is None else dataclasses.asdict(rival)
        return await on_worker(worker, read)

    async def summary(self, current, slot):
        player = self.harness.host.accounts[slot].player_id

        async def read(s):
            return next(row for row in s._server._rivals.summary(player) if row["checkpoint_id"] == CHECKPOINT)
        return await on_worker(current[0], read)

    async def records_arrive(self, current, record):
        """Step 1: each game's companion holds the host's rival record."""
        deadline = time.monotonic() + 60
        for slot, worker in enumerate(current):
            while (got := await self.record_of(worker)) is None:
                require(time.monotonic() < deadline, f"slot {slot}: the host's rival record never reached the game")
                await asyncio.sleep(.5)
            require(not got["completed"] & BIT and not got["cleared"] & BIT, f"slot {slot}: Route 110 already passed: {got}")
            record("rival-record", slot=slot, record=got)

    async def gate_stops(self, probe, companion, record):
        """Step 2: north onto the armed line - the gate's scene, a step back south, then the Players menu by itself."""
        start = pose_of(companion)
        require(start is not None and tuple(start[2:4]) == ROUTE110 and start[5] == LINE_Y + 1,
                f"player 1 is not south of the Route 110 line: {start}")
        await probe.press(UP, frames=24, release=30)
        deadline, presses = time.monotonic() + 60, 0
        while not probe.read()["active"]:
            require(time.monotonic() < deadline, f"the gate never opened the Players menu: {field_state(probe)} "
                                                 f"{pose_of(companion)}")
            if field_state(probe).get("callback2") == "CB2_Overworld" and probe.read()["active"] == 0:
                await probe.press(A, frames=8, release=40)       # "Your rivals meet here!" and its second page
                presses += 1
            await asyncio.sleep(.3)
        here = pose_of(companion)
        require(here is not None and tuple(here[2:4]) == ROUTE110 and here[5] == LINE_Y + 1,
                f"the gate did not step the player back south of the line: {here}")
        record("rival-gate-stopped", slot=0, start=list(start[2:]), after=list(here[2:]), presses=presses)

    @staticmethod
    async def rival_page(probe, slot):
        """The player's Players menu on "Rival: Route 110" (opened, or back to its root first)."""
        if not probe.read()["active"]:
            await probe.open_players()
        _, screen = await probe.ready()
        if screen.title != "Rival: Route 110":
            while screen.back:                          # a page under the root (an A that met the menu's opening)
                await probe.press(B)
                _, screen = await probe.ready()
            await probe.choose("Rival checkpoint")
            _, screen = await probe.ready()
        require(screen.title == "Rival: Route 110", f"slot {slot}: the rival page is {screen.title!r}")
        return screen

    async def vote(self, probe, slot, record):
        await self.rival_page(probe, slot)
        await probe.choose("Start Now")
        _, screen = await probe.ready()
        record("rival-voted", slot=slot, title=screen.title, status=screen.status, rows=[r.label for r in screen.rows])

    async def reward(self, probe, companion, slot, record):
        """Step 6: north onto the line once more - the original reward scene (A through its lines) gives the Dowsing
        Machine once and sets VAR_ROUTE110_STATE to 1; the field is back."""
        require(route110_state(probe) == 0, f"slot {slot}: VAR_ROUTE110_STATE before the reward")
        await probe.press(UP, frames=24, release=30)
        deadline = time.monotonic() + 90
        while route110_state(probe) != 1:
            require(time.monotonic() < deadline, f"slot {slot}: no reward: {field_state(probe)} {pose_of(companion)}")
            await probe.press(A, frames=8, release=40)
            await asyncio.sleep(.4)
        calm_since = None
        while True:                                   # the scene's last lines, then three calm seconds on the field
            require(time.monotonic() < deadline, f"slot {slot}: the reward scene did not end: {field_state(probe)}")
            pose = pose_of(companion)
            if pose is not None and pose[0] == 1 and not probe.read()["active"]:
                calm_since = calm_since or time.monotonic()
                if time.monotonic() - calm_since >= 3:
                    break
            else:
                calm_since = None
                await probe.press(B, frames=8, release=40)
            await asyncio.sleep(.3)
        record("rival-reward", slot=slot, route110_state=route110_state(probe), pose=list(pose_of(companion)[2:]))

    async def ready_pair(self, probes, timeout=120):
        """The two slots whose rival page offers "Battle: ...", the ready match's trainers (every player's page open)."""
        deadline = time.monotonic() + timeout
        while True:
            seen = {}
            for slot, probe in enumerate(probes):
                screen = await self.rival_page(probe, slot)
                seen[slot] = [row.label for row in screen.rows]
            pair = [slot for slot, rows in seen.items() if any(row.startswith("Battle: ") for row in rows)]
            if len(pair) == 2:
                return pair, seen
            require(time.monotonic() < deadline, f"no ready match: {seen}")
            await asyncio.sleep(1)

    async def match(self, current, probes, games, host, symbols, record):
        companions = [p.companion for p in self.harness.players]
        count = len(probes)
        await self.records_arrive(current, record)
        await self.gate_stops(probes[0], companions[0], record)
        for slot in range(count):
            await self.vote(probes[slot], slot, record)
        results = {}
        for number in range(1 if count == 2 else 3):
            # Step 3's end (and each next match): the committed session's ready match
            (sender, recipient), seen = await self.ready_pair(probes)
            record("rival-session", match=number, sender=sender, recipient=recipient, pages=seen)
            # Step 4: the challenge, accepted, entered and played to its end
            await probes[sender].choose("Battle:", prefix=True)
            await rows_until(probes[recipient], lambda row: row == "Open Challenges to accept", 60, "the invitation")
            await probes[recipient].choose("Open Challenges to accept")
            await probes[recipient].choose("Accept challenge")
            pair = sorted((sender, recipient))
            battles = await self.enter(current, probes, pair, record, f"rival-{number}")
            stops, drivers = self.drive(current, probes, symbols, battles, pair)
            results.update(await self.finish(current, probes, battles, pair, stops, drivers, record, f"rival-{number}"))
        # Step 5: the world's completion and each player's pass
        for slot in range(count):
            row = await self.summary(current, slot)
            require(row["completed"] and row["cleared"] and row["via"] == "battle", f"slot {slot}: {row}")
            deadline = time.monotonic() + 60
            while not ((got := await self.record_of(current[slot])) or {}).get("completed", 0) & BIT:
                require(time.monotonic() < deadline, f"slot {slot}: the game's record never said complete: {got}")
                await asyncio.sleep(.5)
            record("rival-complete", slot=slot, host=row, record=got)
        for probe in probes:
            await close_players(probe)
        # Step 6
        for slot in range(count):
            await self.reward(probes[slot], companions[slot], slot, record)
        record("rival-results", results=results)
        return dict(expected=[p.party_now() for p in probes])

    async def after_save(self, current, host, record):
        """Step 7: the canonical checkpoints hold the reward."""
        async def heads(s):
            return [inspect_closed_head(s._store, account.player_id) for account in host.accounts]
        saved = await on_worker(current[0], heads)
        for slot, head in enumerate(saved):
            got = saved_rival(head.payload)
            record("rival-saved", slot=slot, revision=head.revision, **got)
            require(got == dict(route110_state=1, hide_rival_flag=1, dowsing_machines=1),
                    f"slot {slot}: the saved reward {got}")


async def run(args):
    sources = (args.source_a, args.source_b, args.source_c)[:args.players]
    require(all(sources), f"--players {args.players}: a source per player (--source-a, -b, -c)")
    if not args.display:
        require(WINDOWS, "an X display per player")
        args.display = [f"desktop-{n}" for n in range(args.players)]   # Windows: one desktop; names for the records
    proof = RivalProof(args.match_seconds)
    await launcher_proof(args, names=NAMES[:args.players], sources=sources, party_counts=(1,) * args.players,
                         match=proof.match, version="Native rival checkpoint proof", settings="windowScale=2\n",
                         scope=__doc__.split("\n\n")[0], after_save=proof.after_save,
                         environment=dict(SDL_FRAMEBUFFER_ACCELERATION="0"), on_harness=proof.adopt)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True, help="native Linux executable (or the Windows exe)")
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-a", type=Path, required=True, help="make_tower_saves.py rival-a")
    parser.add_argument("--source-b", type=Path, required=True, help="make_tower_saves.py rival-b")
    parser.add_argument("--source-c", type=Path, help="make_tower_saves.py rival-c (--players 3)")
    parser.add_argument("--players", type=int, choices=(2, 3), default=2)
    parser.add_argument("--display", action="append", help="an X display per player (Linux)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0)
    parser.add_argument("--match-seconds", type=float, default=900)
    parser.add_argument("--wine", type=Path, action="append", help="(not used by this proof)")
    parser.add_argument("--sdl", type=Path, help="Windows: SDL2.dll of the game")
    parser.add_argument("--elf", type=Path)
    parser.add_argument("--pe-symbols", type=Path, help="Windows: i686-w64-mingw32-nm -n of the game before its strip")
    parser.add_argument("--sizes", type=Path, help="Windows: nm -S of the Linux build of the same engine commit")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
