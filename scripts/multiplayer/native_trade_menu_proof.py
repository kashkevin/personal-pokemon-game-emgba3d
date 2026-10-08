"""Two actual cores trade through ordinary native menu input and production RPC.

No source-save, party, RNG or RAM edits. This qualifies the exact-record UI,
not excluded native trade effects, Windows controls or Internet acceptance.
"""
import argparse
import asyncio
from contextlib import AsyncExitStack, suppress
import hashlib
import json
from pathlib import Path
import secrets

from configure_bridge import configure
from live_checkpoint_proof import LockedCore
from battle_channel_proof import DiagnosticPump
from emerald_multiplayer.checkpoint_mirror import MirrorLease
from emerald_multiplayer.cold_start import ColdStartRecovery
from emerald_multiplayer.companion import Companion, CompanionConfig, verify_rom_manifest
from emerald_multiplayer.flash import inspect_flash
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator
from emerald_multiplayer.menu_mailbox import unpack_screen
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, inspect_ownership
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.trade_menu import NativeTradeMenu
from emerald_multiplayer.trade_storage import TradeCheckpointStore


class MenuPump(DiagnosticPump):
    async def _run(self):
        # Measure consent and durable checkpoint timing near ordinary playback.
        while True:
            started = asyncio.get_running_loop().time()
            await asyncio.gather(*(core.command(f"F {key:x} 3")
                for core, key in zip(self.cores, self.keys)))
            self.frames += 3
            await asyncio.sleep(max(0, .05 - (asyncio.get_running_loop().time() - started)))


async def run(args):
    root = args.output.resolve()
    if root.exists() or "/multiplayer-proof/" not in str(root) + "/":
        raise ValueError("choose a fresh private proof directory")
    _, manifest = verify_rom_manifest(args.rom, args.manifest)
    if manifest.get("menu_abi_version") != 2 or hashlib.sha256(args.elf.read_bytes()).hexdigest() != manifest["elf_sha256"]:
        raise ValueError("exact native menu ABI2 ROM/ELF is required")
    sources = (args.save_a, args.save_b)
    originals = [p.read_bytes() for p in sources]
    meta = [inspect_flash(p).metadata for p in originals]
    if meta[0].trainer_id == meta[1].trainer_id or any(not m.party_count for m in meta):
        raise ValueError("two distinct ordinarily obtained parties are required")
    root.mkdir(parents=True, mode=0o700)
    rom, manifest_path = root / "game.gba", root / "manifest.json"
    rom.write_bytes(args.rom.read_bytes()); manifest_path.write_bytes(args.manifest.read_bytes())
    bridge = args.bridge.read_text()
    (root / "bridge-source.lua").write_text(bridge)
    (root / "controller.py").write_bytes(Path(__file__).read_bytes())
    evidence = dict(scope=__doc__, passed=False, rom_sha256=manifest["rom_sha256"],
        engine_commit=manifest["engine_commit"], checks=[], inputs=[],
        manifest_sha256=hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        bridge_sha256=hashlib.sha256(bridge.encode()).hexdigest(),
        harness_sha256=hashlib.sha256(args.harness.read_bytes()).hexdigest(),
        controller_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        sources=[dict(path=str(p), sha256=hashlib.sha256(b).hexdigest()) for p, b in zip(sources, originals)])
    def record(name, **details):
        evidence["checks"].append(dict(name=name, **details))
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(name, flush=True)
    nm = await asyncio.create_subprocess_exec("arm-none-eabi-nm", "-S", str(args.elf), stdout=asyncio.subprocess.PIPE)
    symbols = {}
    for line in (await nm.communicate())[0].decode().splitlines():
        row = line.split()
        if len(row) == 4: symbols[row[3]] = (int(row[0], 16), int(row[1], 16))
    if nm.returncode: raise RuntimeError("ELF read failed")
    store = TradeCheckpointStore(root / "world.sqlite3", manifest["rom_sha256"], manifest["ruleset_id"])
    players = [store.create_player("Trader " + x) for x in "AB"]
    for p, data in zip(players, originals): store.enroll_player(p.player_id, data)
    server = WorldServer(ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"], heartbeat_interval=.2, idle_timeout=12),
                         store=store, development_trades=True)
    await server.start(port=0)
    companions, cores, leases = [], [], []
    saves = [root / f"character-{i}.sav" for i in range(2)]
    revisions, results, errors = [1, 1], [None, None], []
    pump = None
    generation = 0

    async def launch(i):
        nonlocal generation
        generation += 1
        c = companions[i]
        script = root / f"bridge-{i}-{generation}.lua"
        script.write_text(configure(manifest, c.config.token.hex(), c.ipc_address[1], bridge))
        process = await asyncio.create_subprocess_exec(str(args.harness), str(rom), str(saves[i]), str(script),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        core = LockedCore(process, root / f"core-{i}-{generation}.log")
        cores.append(core)
        if not (await asyncio.wait_for(process.stdout.readline(), 20)).startswith(b"READY"):
            raise RuntimeError("core startup failed")

    async def boot():
        for key, frames in ((0, 1000), (8, 8), (0, 480), (8, 8), (0, 180), (1, 8), (0, 300)):
            for offset in range(0, frames, 24):
                await asyncio.gather(*(c.command(f"F {key:x} {min(24, frames-offset)}") for c in cores))
                await asyncio.sleep(.003)

    async def state(i):
        names = ("sMultiplayerMenuActive", "sMultiplayerMenuWaiting", "sMultiplayerMenuCursor", "sMultiplayerMenuScreen")
        begin = min(symbols[n][0] for n in names)
        end = max(sum(symbols[n]) for n in names)
        raw = await cores[i].read(begin, end - begin)
        def field(n):
            address, size = symbols[n]
            return raw[address - begin:address - begin + size]
        active, waiting = field(names[0])[0], field(names[1])[0]
        screen = unpack_screen(field(names[3]))[1] if active and not waiting else None
        return active, waiting, field(names[2])[0], screen

    async def ready(i):
        async with asyncio.timeout(25):
            while True:
                if errors: raise errors[0]
                value = await state(i)
                if value[3] is not None: return value
                if pump.task.done(): await pump.task
                await asyncio.sleep(.03)

    async def press(i, key):
        evidence["inputs"].append(dict(player=i, key=key, frame=pump.frames))
        await pump.press(i, key, 12, 24)

    async def choose(i, label=None, *, first=False, wait=True):
        _, _, cursor, screen = await ready(i)
        indices = [n for n, row in enumerate(screen.rows) if row.action and (first or row.label == label)]
        if not indices: raise AssertionError(("missing native row", i, label, screen))
        for _ in range((indices[0] - cursor) % len(screen.rows)): await press(i, 128)
        await press(i, 1)
        if wait: return await ready(i)

    async def open_menu(i):
        await press(i, 8); await pump.advance(60)
        actions = await cores[i].read(*symbols["sCurrentStartMenuActions"])
        count = (await cores[i].read(*symbols["sNumStartMenuActions"]))[0]
        cursor = (await cores[i].read(*symbols["sStartMenuCursorPos"]))[0]
        target = actions[:count].index(15)
        for _ in range((target - cursor) % count): await press(i, 128)
        await press(i, 1); await pump.advance(48)
        if (await cores[i].read(*symbols["sCurrentStartMenuActions"]))[:3] != bytes([16, 17, 18]):
            raise AssertionError("ordinary player submenu did not open")
        await press(i, 128); await press(i, 1)
        value = await ready(i)
        if value[3].back:
            await press(i, 2)
            assert not (await ready(i))[3].back

    async def close_cores():
        nonlocal pump
        if pump is not None:
            await pump.close(); pump = None
        for c in cores:
            if c.process.returncode is None:
                with suppress(Exception):
                    await asyncio.wait_for(c.command("Q"), 5)
                try:
                    await asyncio.wait_for(c.process.wait(), 5)
                except TimeoutError:
                    # These are this proof's private child processes. Reap each
                    # before releasing the save lease, even after a failed run.
                    with suppress(ProcessLookupError): c.process.terminate()
                    try:
                        await asyncio.wait_for(c.process.wait(), 5)
                    except TimeoutError:
                        with suppress(ProcessLookupError): c.process.kill()
                        await c.process.wait()
        cores.clear()
        for lease in leases: lease.__exit__(None, None, None)
        leases.clear()

    try:
        for i, p in enumerate(players):
            saves[i].write_bytes(originals[i])
            c = Companion(CompanionConfig(rom, manifest_path, p.player_id, p.display_name, secrets.token_bytes(32),
                server_host="127.0.0.1", server_port=server.address[1], server_credential=p.credential, ipc_port=0))
            companions.append(c)
            async def handoff(kind, proposal, menu, slot=i):
                try:
                    if kind != "trade": raise AssertionError("unexpected native handoff")
                    result = await NativeTradeMenu(companions[slot], root / f"private-{slot}", menu).run(proposal, revisions[slot])
                    revisions[slot] = result["checkpoint"]["revision"]
                    results[slot] = result
                except BaseException as error:
                    errors.append(error)
                    raise
            c._native_menu_handoff = handoff
            await c.start()
            lease = MirrorLease(saves[i]); lease.__enter__(); leases.append(lease)
            await launch(i)
        await boot()
        pump = MenuPump(cores, companions); pump.start()
        for i, c in enumerate(companions):
            async with asyncio.timeout(15):
                while c._bridge is None or c._bridge.menu_session is None or not c._bridge.save_capable:
                    await asyncio.sleep(.03)
            result = await LiveCheckpointCoordinator(c, root / f"private-{i}").enroll()
            assert result.metadata["revision"] == 1
        before = [store.read_checkpoint(p.player_id, c.session_epoch) for p, c in zip(players, companions)]
        before_ids = [set(r.serial for r in inspect_ownership(inspect_flash(cp.payload, save_profile=OWNERSHIP_PROFILE)).records) for cp in before]
        record("ordinary-Continue-and-enrollment")
        await open_menu(0)
        await choose(0, players[1].display_name)
        await choose(0, "Trade Pokemon")
        await choose(0, first=True)
        await open_menu(1)
        await choose(1, "Pending trade")
        await choose(1, "Choose your Pokemon")
        await choose(1, first=True)
        # Periodic status refresh must present both offers before either input.
        async with asyncio.timeout(12):
            for i in range(2):
                while not any(r.label == "Confirm this trade" for r in (await ready(i))[3].rows):
                    await asyncio.sleep(.1)
        for i in range(2): await cores[i].command(f"P {root / ('offer-' + str(i) + '.png')}")
        await choose(0, "Confirm this trade")
        assert results == [None, None]
        record("first-explicit-native-consent-does-not-commit")
        await choose(1, "Confirm this trade", wait=False)
        async with asyncio.timeout(90):
            while any(result is None for result in results):
                if errors: raise errors[0]
                await asyncio.sleep(.05)
        assert revisions == [3, 3] and all(r["state"] == "applied" for r in results)
        after = [store.read_checkpoint(p.player_id, c.session_epoch) for p, c in zip(players, companions)]
        after_ids = [set(r.serial for r in inspect_ownership(inspect_flash(cp.payload, save_profile=OWNERSHIP_PROFILE)).records) for cp in after]
        assert set.union(*before_ids) == set.union(*after_ids) and not set.intersection(*after_ids)
        assert all(a != b for a, b in zip(before_ids, after_ids))
        for i, cp in enumerate(after):
            party = await cores[i].read(manifest["debug_parties_address"], 600)
            assert party == inspect_flash(cp.payload, save_profile=OWNERSHIP_PROFILE).save_block1[0x238:0x238 + 600]
            assert not (root / f"private-{i}" / "pending-trade.json").exists()
        record("paired-native-menu-trade-applied-and-ownership-conserved", revisions=revisions)
        results[0] = None
        await pump.advance(90)
        await open_menu(0)
        await choose(0, players[1].display_name)
        await choose(0, "Trade Pokemon")
        await press(0, 2)
        async with asyncio.timeout(45):
            while results[0] is None:
                if errors: raise errors[0]
                await asyncio.sleep(.05)
        assert results[0]["state"] == "aborted" and revisions == [4, 3]
        record("native-B-cancels-uncommitted-trade-without-transferring-ownership", revisions=revisions)
        after = [store.read_checkpoint(p.player_id, c.session_epoch) for p, c in zip(players, companions)]
        await close_cores()
        for c in companions: await c.close()
        companions.clear()
        async with AsyncExitStack() as stack:
            for i, p in enumerate(players):
                c = Companion(CompanionConfig(rom, manifest_path, p.player_id, p.display_name, secrets.token_bytes(32),
                    server_host="127.0.0.1", server_port=server.address[1], server_credential=p.credential, ipc_port=0))
                companions.append(c)
                await c.start()
                async with asyncio.timeout(15):
                    while not c.connected: await asyncio.sleep(.03)
                startup = await stack.enter_async_context(ColdStartRecovery(c, root / f"private-{i}", saves[i]).open())
                assert startup.mirror.revision == revisions[i]
                await launch(i)
            await boot()
            for i, cp in enumerate(after):
                party = await cores[i].read(manifest["debug_parties_address"], 600)
                assert party == inspect_flash(cp.payload, save_profile=OWNERSHIP_PROFILE).save_block1[0x238:0x238 + 600]
            record("two-fresh-Continue-cores-retain-completed-trade-and-cancelled-party")
            await close_cores()
        assert all(p.read_bytes() == b for p, b in zip(sources, originals))
        store.integrity_check()
        evidence["passed"] = True
        record("original-sources-unchanged-and-store-integrity-valid")
    except BaseException as error:
        record("failed-run-retained", error=type(error).__name__, message=str(error))
        raise
    finally:
        await close_cores()
        await asyncio.gather(*(c.close() for c in companions), return_exceptions=True)
        await server.close(); store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rom", "elf", "manifest", "harness", "save-a", "save-b", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--bridge", type=Path, default=Path(__file__).parents[2] / "bridge/mgba.lua")
    asyncio.run(run(parser.parse_args()))
