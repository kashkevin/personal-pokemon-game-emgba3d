"""Two native game clients (no emulator) trade through the in-game Players menu.

native_trade_menu_proof.py on the native PC build: two copies of the native
Linux executable (engine `src/platform/mp_bridge.c`) with unchanged companions,
the real world server and the launcher's trade-capable ownership store. Only
ordinary key presses drive the games (xdotool, each on its own X display). The
harness reads the games' memory (`/proc/PID/mem`, at the non-PIE executable's
symbols from `nm`) only to see what is on screen and to compare parties; it
never writes it, and no save, party or RNG is edited.

    1. Each player's legacy save is provisioned and enrolled through its
       running game (revision 1).
    2. A opens Start > Players, picks B, Trade Pokemon and its first eligible
       Pokemon; B opens Pending trade and offers its first. Both screens show
       both offers; A's confirmation alone commits nothing; B's completes it:
       both games are on revision 3, ownership is conserved (the two parties'
       serials are swapped, none lost or doubled) and each running game's party
       in memory equals its new canonical save.
    3. A starts another trade and backs out with B: aborted, nothing moves.
    4. Both games are closed and started again from closed-game recovery: each
       has the party of its latest canonical save.
    5. The host store's integrity check passes; the source saves are unchanged.

    PYTHONPATH=src python scripts/multiplayer/native_trade_proof.py \\
        --game ../engine/pokeemerald-mp --rom pokedev.gba --manifest manifest.json \\
        --save a.sav --save b.sav --display :98 --display :97 \\
        --output /private/multiplayer-proof/native-trade-1
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
import hashlib
import json
from pathlib import Path
import secrets
import subprocess

from native_presence_proof import _hold, _screenshot
from emerald_multiplayer.checkpoint_mirror import MirrorLease
from emerald_multiplayer.cold_start import ColdStartRecovery
from emerald_multiplayer.companion import Companion, CompanionConfig
from emerald_multiplayer.flash import inspect_flash
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator
from emerald_multiplayer.menu_mailbox import unpack_screen
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, inspect_ownership
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.trade_menu import NativeTradeMenu
from emerald_multiplayer.trade_storage import TradeCheckpointStore

# GBA key bits as native_trade_menu_proof.py presses them, and the native
# build's keyboard (sdl2.c): Z = A, X = B, Return = Start.
KEYS = {1: "z", 2: "x", 8: "Return", 128: "Down"}
PLAYER_OPTIONS = 15            # start_menu.c MENU_ACTION_PLAYER_OPTIONS (the "Player" entry)
TRAINER_CARD, PLAYERS = 16, 17 # its submenu: Trainer Card, Players, (Style,) Back
PARTY_BYTES = 600              # six struct Pokemon


def symbols_of(game: Path) -> dict[str, tuple[int, int]]:
    rows = subprocess.run(["nm", "-S", str(game)], capture_output=True, text=True, check=True).stdout
    symbols = {}
    for line in rows.splitlines():
        row = line.split()
        if len(row) == 4:
            symbols[row[3]] = (int(row[0], 16), int(row[1], 16))
    return symbols


class NativeGame:
    """One running native game: its process, and read-only views of its memory."""

    def __init__(self, process: subprocess.Popen, symbols: dict):
        self.process, self.symbols = process, symbols

    def read(self, name: str, size: int | None = None) -> bytes:
        address, length = self.symbols[name]
        with open(f"/proc/{self.process.pid}/mem", "rb", buffering=0) as memory:
            memory.seek(address)
            return memory.read(length if size is None else size)


async def run(args: argparse.Namespace) -> None:
    root = args.output.resolve()
    if "/multiplayer-proof/" not in str(root) + "/" or root.exists():
        raise ValueError("choose a new private multiplayer-proof output directory")
    if len(args.save) != 2 or len(args.display) != 2:
        raise ValueError("two saves, one X display each")
    manifest = json.loads(args.manifest.read_text())
    if hashlib.sha256(args.rom.read_bytes()).hexdigest() != manifest["rom_sha256"]:
        raise ValueError("ROM differs from its manifest")
    game_path = args.game.resolve()
    symbols = symbols_of(game_path)
    for name in ("sMultiplayerMenuActive", "sMultiplayerMenuWaiting", "sMultiplayerMenuCursor",
                 "sMultiplayerMenuScreen", "sCurrentStartMenuActions", "sNumStartMenuActions",
                 "sStartMenuCursorPos", "gParties"):
        if name not in symbols:
            raise ValueError(f"the native game has no symbol {name}: build it unstripped")
    originals = [p.read_bytes() for p in args.save]
    meta = [inspect_flash(b).metadata for b in originals]
    if meta[0].trainer_id == meta[1].trainer_id or any(not m.party_count for m in meta):
        raise ValueError("two distinct parties are required")
    root.mkdir(mode=0o700, parents=True)
    evidence = dict(scope=__doc__.split("\n\n")[0], passed=False, build_id=manifest["rom_sha256"],
                    game_sha256=hashlib.sha256(game_path.read_bytes()).hexdigest(), checks=[], inputs=[],
                    sources=[dict(path=str(p), sha256=hashlib.sha256(b).hexdigest())
                             for p, b in zip(args.save, originals)])

    def record(name, **details):
        evidence["checks"].append(dict(verified=name, **details))
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps(dict(verified=name, **details)), flush=True)

    store = TradeCheckpointStore(root / "world.sqlite3", manifest["rom_sha256"], manifest["ruleset_id"],
                                 OWNERSHIP_PROFILE)
    players = [store.create_player("Trader " + x) for x in "AB"]
    for p, data in zip(players, originals):
        store.enroll_player(p.player_id, data)
    server = WorldServer(ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"], heartbeat_interval=.2,
                                      idle_timeout=12), store=store, development_trades=True)
    await server.start(port=0)
    loop = asyncio.get_running_loop()
    companions: list[Companion] = []
    games: list[NativeGame | None] = [None, None]
    leases: list[MirrorLease | None] = [None, None]
    saves = [root / f"character-{i}.sav" for i in range(2)]
    revisions, results, errors = [1, 1], [None, None], []
    generation = 0

    def make_companion(i):
        p = players[i]
        c = Companion(CompanionConfig(args.rom, args.manifest, p.player_id, p.display_name, secrets.token_bytes(32),
                                      server_port=server.address[1], ipc_port=0, server_credential=p.credential))

        async def handoff(kind, proposal, menu, slot=i):
            try:
                if kind != "trade":
                    raise AssertionError("unexpected native handoff")
                result = await NativeTradeMenu(companions[slot], root / f"private-{slot}", menu).run(
                    proposal, revisions[slot])
                revisions[slot] = result["checkpoint"]["revision"]
                results[slot] = result
            except BaseException as error:
                errors.append(error)
                raise
        c._native_menu_handoff = handoff
        return c

    def launch(i):
        nonlocal generation
        generation += 1
        c = companions[i]
        bridge = root / f"bridge-{i}-{generation}.txt"
        bridge.write_text(f"port={c.ipc_address[1]}\ntoken={c.config.token.hex()}\n")
        bridge.chmod(0o600)
        log = (root / f"client-{i}-{generation}.log").open("wb")
        environment = dict(__import__("os").environ, DISPLAY=args.display[i], SDL_AUDIODRIVER="dummy")
        process = subprocess.Popen([str(game_path), "--save", str(saves[i]), "--bridge", str(bridge)],
                                   cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT)
        games[i] = NativeGame(process, symbols)

    def close_games():
        for game in games:
            if game is not None and game.process.poll() is None:
                game.process.terminate()
        for i, game in enumerate(games):
            if game is not None:
                try:
                    game.process.wait(15)
                except subprocess.TimeoutExpired:
                    game.process.kill()
                    game.process.wait(5)
                games[i] = None
            if leases[i] is not None:
                leases[i].__exit__(None, None, None)
                leases[i] = None

    async def until(name, condition, timeout):
        deadline = loop.time() + timeout
        while not condition():
            if errors:
                raise errors[0]
            if any(g is not None and g.process.poll() is not None for g in games):
                raise AssertionError(f"{name}: a game exited")
            if loop.time() >= deadline:
                for i, display in enumerate(args.display):
                    await asyncio.to_thread(_screenshot, display, root / f"timeout-{i}.png")
                raise AssertionError(f"{name}: timed out")
            await asyncio.sleep(.1)

    async def press(i, key, hold=None):
        evidence["inputs"].append(dict(player=i, key=KEYS[key]))
        await asyncio.to_thread(_hold, args.display[i], KEYS[key], args.hold if hold is None else hold)
        await asyncio.sleep(args.gap)

    def in_overworld(i):
        pose = companions[i]._local_pose
        return pose is not None and pose.activity == 1

    async def boot(phase):
        await until(f"{phase}: bridges authenticated", lambda: all(c._bridge is not None for c in companions), 60)
        await asyncio.sleep(10)
        for i in range(2):
            await press(i, 8)
        await asyncio.sleep(4)
        for i in range(2):
            await press(i, 8)
        await asyncio.sleep(6)
        for i in range(2):
            await press(i, 1)
        for _ in range(10):
            waiting = [i for i in range(2) if not in_overworld(i)]
            if not waiting:
                break
            await asyncio.sleep(4)
            for i in waiting:
                if not in_overworld(i):
                    await press(i, 1)
        await until(f"{phase}: both games in the overworld", lambda: all(in_overworld(i) for i in range(2)), 20)
        await until(f"{phase}: menus and save mailboxes announced",
                    lambda: all(c._bridge is not None and c._bridge.menu_session is not None
                                and c._bridge.save_capable for c in companions), 30)
        record(f"{phase}: both games in the overworld with menus and save mailboxes",
               positions=[(companions[i]._local_pose.map_group, companions[i]._local_pose.map_number,
                           companions[i]._local_pose.x, companions[i]._local_pose.y) for i in range(2)])

    def menu_state(i):
        game = games[i]
        active = game.read("sMultiplayerMenuActive")[0]
        waiting = game.read("sMultiplayerMenuWaiting")[0]
        cursor = game.read("sMultiplayerMenuCursor")[0]
        screen = None
        if active and not waiting:
            with suppress(ValueError):  # a screen being copied in
                screen = unpack_screen(game.read("sMultiplayerMenuScreen"), allow_trade_reopen=True,
                                       allow_battle_admission=True)[1]
        return active, waiting, cursor, screen

    async def ready(i, timeout=25):
        deadline = loop.time() + timeout
        while True:
            if errors:
                raise errors[0]
            value = menu_state(i)
            if value[3] is not None:
                return value
            if loop.time() >= deadline:
                await asyncio.to_thread(_screenshot, args.display[i], root / f"menu-timeout-{i}.png")
                raise AssertionError(("menu not ready", i, value[:3]))
            await asyncio.sleep(.05)

    async def choose(i, label=None, *, first=False, wait=True, prefix=False):
        _, _, cursor, screen = await ready(i)
        indices = [n for n, row in enumerate(screen.rows) if row.action and (
            first or row.label == label or (prefix and row.label.startswith(label + " ")))]
        if not indices:
            raise AssertionError(("missing row", i, label, [r.label for r in screen.rows]))
        for _ in range((indices[0] - cursor) % len(screen.rows)):
            await press(i, 128)
        if menu_state(i)[2] != indices[0]:
            raise AssertionError(("cursor did not reach the row", i, label, menu_state(i)[2], indices[0]))
        await press(i, 1)
        if wait:
            await asyncio.sleep(.5)
            return await ready(i)

    async def open_menu(i):
        await press(i, 8)
        await asyncio.sleep(1.0)
        game = games[i]
        count = game.read("sNumStartMenuActions")[0]
        actions = game.read("sCurrentStartMenuActions")[:count]
        cursor = game.read("sStartMenuCursorPos")[0]
        if PLAYER_OPTIONS not in actions:
            await asyncio.to_thread(_screenshot, args.display[i], root / f"start-menu-{i}.png")
            raise AssertionError(("no Player entry in the start menu", i, list(actions)))
        target = actions.index(PLAYER_OPTIONS)
        for _ in range((target - cursor) % count):
            await press(i, 128)
        if game.read("sStartMenuCursorPos")[0] != target:
            raise AssertionError(("start menu cursor did not reach Player", i, game.read("sStartMenuCursorPos")[0], target))
        await press(i, 1)
        deadline = loop.time() + 3
        while game.read("sCurrentStartMenuActions")[0] != TRAINER_CARD:
            if loop.time() >= deadline:
                await asyncio.to_thread(_screenshot, args.display[i], root / f"player-submenu-{i}.png")
                raise AssertionError(("the Player submenu did not open", i, list(actions), cursor, target,
                                      list(game.read("sCurrentStartMenuActions"))))
            await asyncio.sleep(.1)
        count = game.read("sNumStartMenuActions")[0]
        submenu = game.read("sCurrentStartMenuActions")[:count]
        target = submenu.index(PLAYERS)
        for _ in range((target - game.read("sStartMenuCursorPos")[0]) % count):
            await press(i, 128)
        await press(i, 1)
        value = await ready(i)
        if value[3].back:
            await press(i, 2)
            if (await ready(i))[3].back:
                raise AssertionError("the players list did not come back")

    def party(i):
        return games[i].read("gParties", PARTY_BYTES)

    try:
        for i in range(2):
            saves[i].write_bytes(originals[i])
            companions.append(make_companion(i))
            await companions[i].start()
            leases[i] = MirrorLease(saves[i])
            leases[i].__enter__()
            launch(i)
        await boot("first start")
        for i, c in enumerate(companions):
            result = await LiveCheckpointCoordinator(c, root / f"private-{i}").enroll()
            assert result.metadata["revision"] == 1, result.metadata
        before = [store.read_checkpoint(p.player_id, c.session_epoch) for p, c in zip(players, companions)]
        before_ids = [set(r.serial for r in inspect_ownership(inspect_flash(cp.payload, save_profile=OWNERSHIP_PROFILE)).records)
                      for cp in before]
        record("both legacy saves enrolled through their running games", revisions=[1, 1])

        await open_menu(0)
        await choose(0, players[1].display_name, prefix=True)  # "Trader B - New": name and friendship
        await choose(0, "Trade Pokemon")
        await choose(0, first=True)
        await open_menu(1)
        await choose(1, "Pending trade")
        await choose(1, "Choose your Pokemon")
        await choose(1, first=True)
        deadline = loop.time() + 30
        while True:
            rows = [(await ready(i))[3].rows for i in range(2)]
            if all(any(r.label == "Confirm this trade" for r in screen) for screen in rows):
                break
            if loop.time() >= deadline:
                raise AssertionError(("both offers never showed", [[r.label for r in screen] for screen in rows]))
            await asyncio.sleep(.2)
        for i, display in enumerate(args.display):
            await asyncio.to_thread(_screenshot, display, root / f"offer-{i}.png")
        record("both games show both offers")
        started = loop.time()
        await choose(0, "Confirm this trade")
        assert results == [None, None]
        record("A's confirmation alone commits nothing")
        await choose(1, "Confirm this trade", wait=False)
        await until("the trade completed in both games", lambda: all(r is not None for r in results), args.trade_timeout)
        seconds = round(loop.time() - started, 1)
        assert revisions == [3, 3] and all(r["state"] == "applied" for r in results), (revisions, results)
        after = [store.read_checkpoint(p.player_id, c.session_epoch) for p, c in zip(players, companions)]
        after_ids = [set(r.serial for r in inspect_ownership(inspect_flash(cp.payload, save_profile=OWNERSHIP_PROFILE)).records)
                     for cp in after]
        assert set.union(*before_ids) == set.union(*after_ids) and not set.intersection(*after_ids)
        assert all(a != b for a, b in zip(before_ids, after_ids))
        await asyncio.sleep(2)
        matches = [party(i) == inspect_flash(cp.payload, save_profile=OWNERSHIP_PROFILE).save_block1[0x238:0x238 + PARTY_BYTES]
                   for i, cp in enumerate(after)]
        assert all(matches), matches
        for i, display in enumerate(args.display):
            await asyncio.to_thread(_screenshot, display, root / f"traded-{i}.png")
        record("trade applied in both running games; ownership conserved; each party equals its canonical save",
               revisions=revisions, seconds_from_first_confirmation=seconds)

        results[0] = None
        await asyncio.sleep(3)
        await open_menu(0)
        await choose(0, players[1].display_name, prefix=True)  # "Trader B - New": name and friendship
        await choose(0, "Trade Pokemon")
        await press(0, 2)
        await until("the backed-out trade ended", lambda: results[0] is not None, 90)
        assert results[0]["state"] == "aborted" and revisions == [4, 3], (results[0], revisions)
        record("B backs out of an unconfirmed trade: aborted, nothing transferred", revisions=revisions)
        after = [store.read_checkpoint(p.player_id, c.session_epoch) for p, c in zip(players, companions)]

        close_games()
        for c in companions:
            await c.close()
        companions.clear()
        for i in range(2):
            companions.append(make_companion(i))
            await companions[i].start()
        await until("companions joined again", lambda: all(c.connected for c in companions), 30)
        startups = []
        for i in range(2):
            gate = ColdStartRecovery(companions[i], root / f"private-{i}", saves[i])
            context = gate.open()
            startup = await context.__aenter__()
            startups.append(context)
            assert startup.mirror.revision == revisions[i], (startup.mirror.revision, revisions)
            launch(i)
        try:
            await boot("restart")
            matches = [party(i) == inspect_flash(cp.payload, save_profile=OWNERSHIP_PROFILE).save_block1[0x238:0x238 + PARTY_BYTES]
                       for i, cp in enumerate(after)]
            assert all(matches), matches
            record("restarted games hold the parties of their latest canonical saves", revisions=revisions)
            close_games()
        finally:
            for context in startups:
                await context.__aexit__(None, None, None)
        assert all(p.read_bytes() == b for p, b in zip(args.save, originals))
        store.integrity_check()
        evidence["passed"] = True
        record("host store integrity check passed; source saves unchanged")
    except BaseException as error:
        record("failed", error=type(error).__name__, message=str(error)[:500])
        raise
    finally:
        close_games()
        await asyncio.gather(*(c.close() for c in companions), return_exceptions=True)
        await server.close()
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True, help="native Linux executable, unstripped (nm)")
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--save", type=Path, action="append", required=True)
    parser.add_argument("--display", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hold", type=float, default=.12, help="seconds each key is held")
    parser.add_argument("--gap", type=float, default=.25, help="seconds after each key")
    parser.add_argument("--trade-timeout", type=float, default=300)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
