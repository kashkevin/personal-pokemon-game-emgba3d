"""Two actual cores at the earliest native battle Enter/host-loss boundary.

Ordinary native menus invite, accept and choose Enter. One exact marked CHOOSE
is delayed before Python feed while the host closes. Production emergency
BEGIN must refuse with BATTLE_ADMISSION before provisional publication, then
the same IPC event publishes the original admission and production offline
ADMIT atomically closes the menu. This callback harness is not the launcher,
a complete battle/recovery proof, a Windows proof or an Internet proof.
Only proof-owned copies are stopped; original saves and core RAM are not edited.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import secrets
import traceback

from configure_bridge import configure
from live_checkpoint_proof import LockedCore
from native_trade_menu_proof import MenuPump
from emerald_multiplayer import companion as companion_module
from emerald_multiplayer.battle_admission_intent import FILENAME, read_admission_intent
from emerald_multiplayer.battle_admission_session import publish_battle_admission, prepare_battle_admission, read_admission_receipt
from emerald_multiplayer.battle_controller import read_string_lengths
from emerald_multiplayer.battle_reservations import enable_battle_reservations
from emerald_multiplayer.battle_terminal import authenticated_session
from emerald_multiplayer.checkpoint_mirror import MirrorLease
from emerald_multiplayer.companion import Companion, CompanionConfig, verify_rom_manifest
from emerald_multiplayer.emergency_save import EmergencySaveController, load_closed_emergency
from emerald_multiplayer.flash import inspect_flash
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator
from emerald_multiplayer.menu_mailbox import MenuRequest, unpack_screen
from emerald_multiplayer.native_battle import NativeQuery, Opcode as BattleOpcode
from emerald_multiplayer.save_mailbox import Opcode as SaveOpcode, Status
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.trade_storage import TradeCheckpointStore


async def run(args):
    root = args.output.resolve()
    if root.exists() or "/multiplayer-proof/" not in str(root) + "/":
        raise ValueError("choose a fresh private multiplayer-proof directory")
    if not math.isfinite(args.timeout) or not 60 <= args.timeout <= 600:
        raise ValueError("entry proof timeout must be between 60 and 600 seconds")
    _, manifest = verify_rom_manifest(args.rom, args.manifest)
    required = dict(menu_abi_version=2, battle_abi_version=3, battle_resume_abi_version=1,
                    battle_execution_abi_version=1, emergency_save_abi_version=2)
    if (any(manifest.get(key) != value for key, value in required.items())
            or hashlib.sha256(args.elf.read_bytes()).hexdigest() != manifest["elf_sha256"]):
        raise ValueError("exact combined menu2/battle3/resume1/emergency2 ROM and ELF are required")
    sources = [args.save_a, args.save_b]
    originals = [path.read_bytes() for path in sources]
    metadata = [inspect_flash(raw).metadata for raw in originals]
    if len({m.trainer_id for m in metadata}) != 2 or any(not m.party_count for m in metadata):
        raise ValueError("two independent ordinarily progressed party saves are required")
    root.mkdir(parents=True, mode=0o700)
    rom, manifest_path = root / "game.gba", root / "manifest.json"
    rom.write_bytes(args.rom.read_bytes())
    manifest_path.write_bytes(args.manifest.read_bytes())
    bridge_text = args.bridge.read_text()
    (root / "bridge-source.lua").write_text(bridge_text)
    (root / "controller.py").write_bytes(Path(__file__).read_bytes())
    package = Path(companion_module.__file__).parent
    source_hashes = {}
    for path in sorted(package.rglob("*.py")) + sorted(Path(__file__).parent.glob("*.py")):
        relative = (Path("scripts") / path.name if path.parent == Path(__file__).parent
                    else Path("emerald_multiplayer") / path.relative_to(package))
        copy = root / "python-source" / relative
        copy.parent.mkdir(parents=True, exist_ok=True)
        raw = path.read_bytes()
        copy.write_bytes(raw)
        source_hashes[str(path)] = hashlib.sha256(raw).hexdigest()
    evidence = dict(scope=__doc__, passed=False, cores_closed=False, checks=[], inputs=[],
        save_commands=[], battle_commands=[], frozen_python_sources=source_hashes,
        engine_commit=manifest["engine_commit"], rom_sha256=manifest["rom_sha256"], elf_sha256=manifest["elf_sha256"],
        manifest_sha256=hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        bridge_sha256=hashlib.sha256(bridge_text.encode()).hexdigest(),
        controller_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        harness_sha256=hashlib.sha256(args.harness.read_bytes()).hexdigest(),
        sources=[dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest()) for path, raw in zip(sources, originals)])
    def persist():
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    def record(name, **details):
        evidence["checks"].append(dict(name=name, **details))
        persist()
        print(name, flush=True)
    nm = await asyncio.create_subprocess_exec("arm-none-eabi-nm", "-S", str(args.elf), stdout=asyncio.subprocess.PIPE)
    symbols = {}
    for line in (await nm.communicate())[0].decode().splitlines():
        fields = line.split()
        if len(fields) == 4:
            symbols[fields[3]] = int(fields[0], 16), int(fields[1], 16)
    required_symbols = dict(gMultiplayerBattleHoldFlags=4, gRngValue=16, gRng2Value=16,
        gSaveBlock1Ptr=4, gSaveCounter=4, gPartiesCount=4,
        sMultiplayerMenuActive=1, sMultiplayerMenuWaiting=1, sMultiplayerMenuCursor=1,
        sMultiplayerMenuScreen=240, sNumStartMenuActions=1, sStartMenuCursorPos=1)
    if (nm.returncode or any(symbols.get(name, (0, 0))[1] != size for name, size in required_symbols.items())
            or "sCurrentStartMenuActions" not in symbols):
        raise ValueError("the exact ELF must expose the pinned native menu/party/hold diagnostic layout")
    store = TradeCheckpointStore(root / "world.sqlite3", manifest["rom_sha256"], manifest["ruleset_id"])
    enable_battle_reservations(store, root / "before-battle-reservations.sqlite3")
    players = [store.create_player("Entry " + label) for label in "AB"]
    for player, raw in zip(players, originals):
        store.enroll_player(player.player_id, raw)
    server = WorldServer(ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"], heartbeat_interval=.2, idle_timeout=12),
        store=store, development_trades=True, development_battles=True)
    server.enable_battle_execution(read_string_lengths(rom, table_address=manifest["battle_string_table_address"]),
        root / "execution-host", resume_enabled=True)
    await server.start(port=0)
    cores, companions, leases, emergency = [], [], [], []
    saves = [root / f"character-{i}.sav" for i in range(2)]
    original_sessions, captured, armed_sessions = [None, None], [None, None], []
    errors, delayed = [], []
    choice_arrived, transferred, stop_handoff = asyncio.Event(), asyncio.Event(), asyncio.Event()
    pump, snapshot_id = None, 0

    async def menu_state(i):
        names = ("sMultiplayerMenuActive", "sMultiplayerMenuWaiting", "sMultiplayerMenuCursor", "sMultiplayerMenuScreen")
        begin = min(symbols[name][0] for name in names)
        end = max(sum(symbols[name]) for name in names)
        raw = await cores[i].read(begin, end - begin)
        def field(name):
            address, size = symbols[name]
            return raw[address-begin:address-begin+size]
        active, waiting = field(names[0])[0], field(names[1])[0]
        screen = unpack_screen(field(names[3]), allow_battle_admission=True)[1] if active and not waiting else None
        return active, waiting, field(names[2])[0], screen

    async def ready(i):
        async with asyncio.timeout(30):
            while True:
                if errors:
                    raise errors[0]
                state = await menu_state(i)
                if state[3] is not None:
                    return state
                if pump.task.done():
                    await pump.task
                await asyncio.sleep(.03)

    async def press(i, key, frames=12, release=24):
        evidence["inputs"].append(dict(player=i, key=key, frames=frames, frame=pump.frames))
        await pump.press(i, key, frames, release)

    async def choose(i, label, *, wait=True):
        _, _, cursor, screen = await ready(i)
        choices = [n for n, row in enumerate(screen.rows) if row.action and row.label == label]
        if not choices:
            raise AssertionError(("missing ordinary native menu choice", i, label, screen))
        for _ in range((choices[0] - cursor) % len(screen.rows)):
            await press(i, 128)
        await press(i, 1)
        if wait:
            return await ready(i)

    async def open_menu(i):
        await press(i, 8)
        await pump.advance(60)
        actions = await cores[i].read(*symbols["sCurrentStartMenuActions"])
        count = (await cores[i].read(*symbols["sNumStartMenuActions"]))[0]
        cursor = (await cores[i].read(*symbols["sStartMenuCursorPos"]))[0]
        target = actions[:count].index(15)
        for _ in range((target-cursor) % count):
            await press(i, 128)
        await press(i, 1)
        await pump.advance(48)
        if (await cores[i].read(*symbols["sCurrentStartMenuActions"]))[:3] != bytes([16, 17, 18]):
            raise AssertionError("ordinary Players start-menu entry did not open")
        await press(i, 128)
        await press(i, 1)
        if (await ready(i))[3].back:
            await press(i, 2)
            if (await ready(i))[3].back:
                raise AssertionError("ordinary Players root was not reached")

    async def native_snapshot(i):
        nonlocal snapshot_id
        snapshot_id += 1
        core = cores[i]
        sb1 = int.from_bytes(await core.read(*symbols["gSaveBlock1Ptr"]), "little")
        sb2 = int.from_bytes(await core.read(manifest["debug_save_block2_ptr_address"], 4), "little")
        flash = root / f"observed-{i}-{snapshot_id}.flash"
        await core.command(f"D {flash}")
        return dict(pid=core.process.pid, incarnation=companions[i].battle_incarnation,
            party_sha256=hashlib.sha256(await core.read(manifest["debug_parties_address"], 600)).hexdigest(),
            party_count=(await core.read(symbols["gPartiesCount"][0], 1))[0],
            rng=(await core.read(*symbols["gRngValue"])).hex(), rng2=(await core.read(*symbols["gRng2Value"])).hex(),
            position=(await core.read(sb1, 8)).hex(),
            playtime=(await core.read(sb2 + manifest["debug_play_time_offset"], 5)).hex(),
            save_counter=int.from_bytes(await core.read(*symbols["gSaveCounter"]), "little"),
            hold_flags=int.from_bytes(await core.read(*symbols["gMultiplayerBattleHoldFlags"]), "little"),
            battle_state=int.from_bytes(await core.read(manifest["battle_mailbox_address"]+12, 4), "little"),
            flash_sha256=hashlib.sha256(flash.read_bytes()).hexdigest())

    async def stable_input_hold(label, expected_flags):
        first = await native_snapshot(0)
        if first["hold_flags"] != expected_flags:
            raise AssertionError(("native hold marker differs", label, first))
        for key in (0x10, 0x2, 0xF):
            await press(0, key, frames=120, release=24)
            current = await native_snapshot(0)
            if current != first:
                raise AssertionError(("ordinary direction/B/reset escaped native hold", key, first, current))
        record(label, retained=first, frames_per_input=120)
        return first

    async def close_cores():
        nonlocal pump
        if pump is not None:
            await pump.close()
            pump = None
        for core in cores:
            if core.process.returncode is None:
                with suppress(Exception):
                    await asyncio.wait_for(core.command("Q"), 5)
                try:
                    await asyncio.wait_for(core.process.wait(), 5)
                except TimeoutError:
                    with suppress(ProcessLookupError):
                        core.process.terminate()
                    try:
                        await asyncio.wait_for(core.process.wait(), 5)
                    except TimeoutError:
                        with suppress(ProcessLookupError):
                            core.process.kill()
                        await core.process.wait()
        for lease in leases:
            lease.__exit__(None, None, None)
        leases.clear()
        evidence["cores_closed"] = all(core.process.returncode is not None for core in cores)

    try:
        async with asyncio.timeout(args.timeout):
            for i, player in enumerate(players):
                saves[i].write_bytes(originals[i])
                c = Companion(CompanionConfig(rom, manifest_path, player.player_id, player.display_name,
                    secrets.token_bytes(32), server_port=server.address[1], ipc_port=0,
                    server_credential=player.credential, development_battle_channel=True))
                companions.append(c)
                def capture(descriptor, menu, slot=i):
                    if original_sessions[slot] is None or companions[slot]._bridge is not menu.bridge:
                        raise AssertionError("no original authenticated displayed session")
                    captured[slot] = publish_battle_admission(companions[slot], root/f"private-{slot}",
                        descriptor, original_sessions[slot], menu.bridge)
                    return captured[slot]
                async def prepare(descriptor, menu, slot=i):
                    result = await prepare_battle_admission(companions[slot], root/f"private-{slot}", descriptor)
                    if result != captured[slot]:
                        raise AssertionError("production preparation replaced original admission")
                    return result
                async def handoff(kind, descriptor, menu, slot=i):
                    if slot != 0 or kind != "battle" or captured[slot].challenge != descriptor or menu.open:
                        raise AssertionError("unexpected native operation transfer")
                    transferred.set()
                    # This proof ends at admission. It issues no execution
                    # readiness, outcome or cancellation and retains the hold.
                    await stop_handoff.wait()
                def abandon(menu, slot=i):
                    if not stop_handoff.is_set():
                        errors.append(AssertionError(("entry handoff was abandoned", slot)))
                c._native_menu_capture_battle = capture
                c._native_menu_prepare_battle = prepare
                c._native_menu_handoff = handoff
                c._native_menu_abandon_battle_preparation = abandon
                original_emergency_rpc = c.emergency_save_rpc
                async def observe_save(authority, command, slot=i, original=original_emergency_rpc, **kwargs):
                    response = await original(authority, command, **kwargs)
                    value = response[0] if isinstance(response, tuple) else response
                    evidence["save_commands"].append(dict(slot=slot, opcode=int(command.opcode), status=int(value.status),
                        command_sha256=hashlib.sha256(command.pack()).hexdigest(), response_sha256=hashlib.sha256(value.pack()).hexdigest(),
                        provisional_exists=(root/f"private-{slot}"/FILENAME).exists()))
                    return response
                c.emergency_save_rpc = observe_save
                original_battle_rpc = c.battle_rpc
                async def observe_battle(command, slot=i, original=original_battle_rpc, **kwargs):
                    response = await original(command, **kwargs)
                    evidence["battle_commands"].append(dict(slot=slot, opcode=int(command.opcode), status=int(response.status),
                        command_sha256=hashlib.sha256(command.pack()).hexdigest(), response_sha256=hashlib.sha256(response.pack()).hexdigest()))
                    return response
                c.battle_rpc = observe_battle
                await c.start()
                lease = MirrorLease(saves[i]); lease.__enter__(); leases.append(lease)
                script = root/f"bridge-{i}.lua"
                script.write_text(configure(manifest, c.config.token.hex(), c.ipc_address[1], bridge_text))
                process = await asyncio.create_subprocess_exec(str(args.harness), str(rom), str(saves[i]), str(script),
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                cores.append(LockedCore(process, root/f"core-{i}.log"))
                if not (await asyncio.wait_for(process.stdout.readline(), 20)).startswith(b"READY"):
                    raise RuntimeError("native proof core did not start")
            for key, frames in ((0, 1000), (8, 8), (0, 480), (8, 8), (0, 180), (1, 8), (0, 300)):
                for offset in range(0, frames, 24):
                    await asyncio.gather(*(core.command(f"F {key:x} {min(24, frames-offset)}") for core in cores))
                    await asyncio.sleep(.003)
            pump = MenuPump(cores, companions); pump.start()
            for i, c in enumerate(companions):
                async with asyncio.timeout(20):
                    while c._bridge is None or c._bridge.menu_session is None or not c._bridge.save_capable:
                        await asyncio.sleep(.03)
                receipt = await LiveCheckpointCoordinator(c, root/f"private-{i}").enroll()
                if receipt.metadata["revision"] != 1:
                    raise AssertionError("fresh canonical enrollment did not complete")
                saver = EmergencySaveController(c, root/f"private-{i}")
                await saver.arm(1)
                emergency.append(saver)
                armed_sessions.append((c.world_id, c.server_epoch, c.session_epoch, c.save_profile,
                    c.config.player_id, c.config.build_id, c.config.ruleset_id))
                menu = c._bridge.menu_session
                original_send = menu._send
                def observe_display(request, screen, slot=i, original=original_send, **kwargs):
                    if screen.admission_action:
                        original_sessions[slot] = authenticated_session(companions[slot])
                    return original(request, screen, **kwargs)
                menu._send = observe_display
            record("two-ordinary-Continue-enrolled-and-emergency-armed")
            await open_menu(0)
            await choose(0, players[1].display_name)
            await choose(0, "Challenge 1v1")
            await open_menu(1)
            await choose(1, "Pending challenge")
            await choose(1, "Accept challenge")
            while (await menu_state(1))[0]:
                await press(1, 2)
            await pump.advance(90)
            async with asyncio.timeout(15):
                while not (await ready(0))[3].admission_action:
                    await asyncio.sleep(.05)
            menu = companions[0]._bridge.menu_session
            original_feed = menu.feed
            def delay_exact_choice(payload):
                request = MenuRequest.unpack(payload)
                if request.kind == 2 and (request.screen, request.action) == menu._admission_display:
                    if delayed:
                        raise AssertionError("native issued duplicate Enter while latched")
                    delayed.append(payload)
                    choice_arrived.set()
                    return
                original_feed(payload)
            menu.feed = delay_exact_choice
            await choose(0, "Enter battle", wait=False)
            await asyncio.wait_for(choice_arrived.wait(), 10)
            if (root/"private-0"/FILENAME).exists() or captured[0] is not None:
                raise AssertionError("fault must precede Python provisional publication")
            before = await native_snapshot(0)
            if before["hold_flags"] != 1:
                raise AssertionError("native Enter did not latch before IPC processing")
            retained = (cores[0], cores[0].process.pid, companions[0]._bridge, companions[0]._live_battle_runtime_id)
            await server.close()
            async with asyncio.timeout(45):
                for saver in emergency:
                    await saver.lost.wait()
                    await saver.drain()
            refusals = [row for row in evidence["save_commands"] if row["slot"] == 0
                and row["opcode"] == int(SaveOpcode.BEGIN_EMERGENCY_EXPORT) and row["status"] == int(Status.BATTLE_ADMISSION)]
            if len(refusals) != 1 or refusals[0]["provisional_exists"] or emergency[0].result.state != "battle_waiting":
                raise AssertionError(("exact pre-publication BEGIN14 refusal was not observed", refusals, emergency[0].result))
            if emergency[1].result.state != "preserved" or not emergency[1].result.can_close:
                raise AssertionError("the other original core did not finish ordinary host-loss preservation")
            load_closed_emergency(root/"private-1", armed_sessions[1])
            record("native-BEGIN14-refused-before-provisional-and-peer-preserved", refusal=refusals[0], peer=asdict(emergency[1].result))
            held_before = await stable_input_hold("native-Enter-latch-survives-delayed-choice-direction-B-reset", 1)
            if held_before != before:
                raise AssertionError("host loss changed selected Enter-held personal state")
            original_feed(delayed[0])
            await asyncio.wait_for(transferred.wait(), 15)
            intent = read_admission_intent(root/"private-0"/FILENAME)
            if intent != captured[0] or (intent.server_epoch, intent.lease_epoch) != (
                    original_sessions[0].server_epoch, original_sessions[0].lease_epoch):
                raise AssertionError("delayed Enter changed original authenticated admission")
            receipt = read_admission_receipt(root/"private-0", intent)
            query = NativeQuery.unpack(receipt.data)
            if receipt.status or not query.provisional or query.generation != intent.generation:
                raise AssertionError("offline production ADMIT lacks exact native provisional receipt")
            if any(row["opcode"] != int(BattleOpcode.ADMIT) for row in evidence["battle_commands"]):
                raise AssertionError("entry-only proof dispatched a full battle mutation")
            if menu.open or (await menu_state(0))[0] or (root/"private-0"/"pending-battle.json").exists():
                raise AssertionError("provisional atomic CLOSE did not finish at the selected boundary")
            held_after = await stable_input_hold("offline-ADMIT-holds-original-core-after-atomic-menu-CLOSE", 2)
            for key in ("pid", "incarnation", "party_sha256", "party_count", "rng", "rng2", "position", "playtime", "save_counter", "flash_sha256"):
                if held_after[key] != before[key]:
                    raise AssertionError(("native menu-to-provisional transfer changed personal state", key))
            if (cores[0] is not retained[0] or cores[0].process.pid != retained[1]
                    or companions[0]._bridge is not retained[2] or companions[0]._live_battle_runtime_id != retained[3]):
                raise AssertionError("entry handoff replaced the original runtime")
            if any(path.read_bytes() != raw for path, raw in zip(sources, originals)):
                raise AssertionError("original source save changed")
            if any(hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest for path, digest in source_hashes.items()):
                raise AssertionError("controller source changed during proof; use a frozen source tree")
            store.integrity_check()
            evidence["passed"] = True
            record("same-original-core-and-immutable-sources-preserved-at-entry-boundary", admission=intent.value())
    except BaseException as error:
        evidence["error"] = repr(error)
        evidence["traceback"] = traceback.format_exc()
        persist()
        raise
    finally:
        # All children and mirrors are this proof's disposable copies. This
        # bounded admission-only exercise deliberately does not settle a battle.
        stop_handoff.set()
        for c in companions:
            if c._bridge is not None and c._bridge.menu_session is not None:
                task = c._bridge.menu_session._task
                if task is not None and not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        await close_cores()
        await asyncio.gather(*(c.close() for c in companions), return_exceptions=True)
        await server.close()
        store.close()
        evidence["originals_unchanged"] = all(path.read_bytes() == raw for path, raw in zip(sources, originals))
        evidence["python_sources_unchanged"] = all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
            for path, digest in source_hashes.items())
        if not evidence["cores_closed"] or not evidence["originals_unchanged"] or not evidence["python_sources_unchanged"]:
            evidence["passed"] = False
        persist()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rom", "elf", "manifest", "harness", "save-a", "save-b", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--bridge", type=Path, default=Path(__file__).parents[2]/"bridge/mgba.lua")
    parser.add_argument("--timeout", type=float, default=300)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
