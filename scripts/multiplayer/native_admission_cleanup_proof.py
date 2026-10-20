"""Actual native Enter/ADMIT cancellation through the production cleanup APIs.

Ordinary Players menus create genuine consent and latch Enter. A documented
callback gate stops only the already selected operation before ADMIT or BIND.
Its task is drained only AFTER a real durable host cancellation tombstone.
Optional loss withholds a genuine reply, closes/reopens the original host and
SQLite store, and retries cleanup on the identical retained original core.
Read-only diagnostics prove held personal state, fresh-saver-before-HANDOFF,
ordinary movement/checkpoint and fresh Continue. No RAM/save edits, debug warp,
forced battle outcome, fake native receipts or replacement core recovery.
This headless callback proof does not qualify LauncherSession/Windows GUI,
full bound-battle cancellation, separate PCs or Internet connectivity.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import secrets
import traceback
from uuid import uuid4

from configure_bridge import configure
from live_checkpoint_proof import LockedCore
from native_trade_menu_proof import MenuPump
from emerald_multiplayer import companion as companion_module
from emerald_multiplayer.battle_admission_cleanup import (AdmissionCleanupSession, cleanup_path,
    verify_cleanup_completion, complete_cleanup_handoff)
from emerald_multiplayer.cold_start import ColdStartRecovery
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, inspect_ownership
from emerald_multiplayer.battle_admission_intent import FILENAME, read_admission_intent
from emerald_multiplayer.battle_admission_session import publish_battle_admission, prepare_battle_admission, read_admission_receipt
from emerald_multiplayer.battle_execution_protocol import encode_control
from emerald_multiplayer.battle_controller import read_string_lengths
from emerald_multiplayer.battle_reservations import enable_battle_reservations
from emerald_multiplayer.battle_terminal import authenticated_session
from emerald_multiplayer.checkpoint_mirror import MirrorLease
from emerald_multiplayer.companion import Companion, CompanionConfig, BattleChallengeError, verify_rom_manifest
from emerald_multiplayer.emergency_save import EmergencySaveController
from emerald_multiplayer.flash import inspect_flash
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator
from emerald_multiplayer.menu_mailbox import MenuRequest, unpack_screen
from emerald_multiplayer.native_battle import Opcode as BattleOpcode
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.trade_storage import TradeCheckpointStore


async def run(args):
    root = args.output.resolve()
    if root.exists() or "/multiplayer-proof/" not in str(root) + "/":
        raise ValueError("choose a fresh private multiplayer-proof directory")
    if not math.isfinite(args.timeout) or not 60 <= args.timeout <= 600:
        raise ValueError("admission cleanup proof timeout must be between 60 and 600 seconds")
    _, manifest = verify_rom_manifest(args.rom, args.manifest)
    required = dict(menu_abi_version=2, battle_abi_version=3, battle_resume_abi_version=1,
                    battle_execution_abi_version=1, emergency_save_abi_version=2, battle_admission_cleanup_abi_version=1)
    if (any(manifest.get(key) != value for key, value in required.items())
            or hashlib.sha256(args.elf.read_bytes()).hexdigest() != manifest["elf_sha256"]):
        raise ValueError("exact combined menu2/battle3/resume1/emergency2/cleanup1 ROM and ELF are required")
    sources = [args.save_a, args.save_b]
    originals = [path.read_bytes() for path in sources]
    input_hashes = {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in (args.rom, args.elf, args.manifest, args.bridge, args.harness)}
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
        immutable_inputs=input_hashes, cleanup_errors=[], core_closures=[],
        phase=args.phase, fault=args.fault,
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
    cores, companions, leases, emergency, cold_contexts = [], [], [], [], []
    all_cores, closures = [], {}
    completed = False
    saves = [root / f"character-{i}.sav" for i in range(2)]
    original_sessions, captured = [None, None], [None, None]
    errors = []
    phase_ready, stop_handoff = asyncio.Event(), asyncio.Event()
    fault_ready, fault_release = asyncio.Event(), asyncio.Event()
    expected_gate_cancel, tombstone_seen, fault_used = False, False, False
    cleanup_task = None
    handoff_saver = None
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
            try:
                await asyncio.wait_for(pump.close(), 10)
            except BaseException as error:
                evidence["cleanup_errors"].append(dict(resource="frame-pump", error=repr(error)))
            pump = None
        for core in cores:
            forced = False
            failures = []
            alive_before_q = core.process.returncode is None
            q_reply_error = None
            if core.process.returncode is None:
                try:
                    await asyncio.wait_for(core.command("Q"), 5)
                except BaseException as error:
                    # EOF while sending Q does not itself prove an abnormal
                    # exit. Retain the transport observation; still require
                    # an ordinary zero exit without terminate/kill below.
                    q_reply_error = repr(error)
                try:
                    await asyncio.wait_for(core.process.wait(), 5)
                except BaseException as error:
                    failures.append(dict(stage="ordinary-exit", error=repr(error)))
                    forced = True
                    try:
                        core.process.terminate()
                    except BaseException as error:
                        failures.append(dict(stage="terminate", error=repr(error)))
                    try:
                        await asyncio.wait_for(core.process.wait(), 5)
                    except BaseException as error:
                        failures.append(dict(stage="terminate-exit", error=repr(error)))
                        try:
                            core.process.kill()
                        except BaseException as error:
                            failures.append(dict(stage="kill", error=repr(error)))
                        try:
                            await asyncio.wait_for(core.process.wait(), 5)
                        except BaseException as error:
                            failures.append(dict(stage="kill-wait", error=repr(error)))
            try:
                await asyncio.wait_for(core.logs, 5)
            except BaseException as error:
                failures.append(dict(stage="stderr-drain", error=repr(error)))
            closures[core.process.pid] = dict(pid=core.process.pid, returncode=core.process.returncode,
                                              alive_before_q=alive_before_q, q_reply_error=q_reply_error,
                                              forced=forced, failures=failures)
        for lease in leases:
            try:
                lease.__exit__(None, None, None)
            except BaseException as error:
                evidence["cleanup_errors"].append(dict(resource="mirror-lease", error=repr(error)))
        leases.clear()
        evidence["core_closures"] = list(closures.values())
        evidence["cores_closed"] = all(core.process.returncode is not None for core in all_cores)

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
                    if args.phase == "enter":
                        phase_ready.set()
                        await stop_handoff.wait()
                        raise AssertionError("raw Enter proof gate was released instead of drained")
                    result = await prepare_battle_admission(companions[slot], root/f"private-{slot}", descriptor)
                    if result != captured[slot]:
                        raise AssertionError("production preparation replaced original admission")
                    return result
                async def handoff(kind, descriptor, menu, slot=i):
                    if slot != 0 or kind != "battle" or captured[slot].challenge != descriptor or menu.open:
                        raise AssertionError("unexpected native operation transfer")
                    phase_ready.set()
                    await stop_handoff.wait()
                    raise AssertionError("admitted proof gate was released instead of drained")
                def abandon(menu, slot=i):
                    if not expected_gate_cancel:
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
                original_challenge_rpc = c.battle_challenge_rpc
                async def observe_challenge(operation, slot=i, original=original_challenge_rpc, **fields):
                    nonlocal tombstone_seen
                    reply = await original(operation, **fields)
                    if slot == 0 and operation == "cancel_admission" and fields.get("cleanup_receipt_b64") is None:
                        result = reply["result"]
                        if not tombstone_seen:
                            tombstone_seen = True
                            record("durable-host-tombstone-reply-observed", result=result)
                    return reply
                c.battle_challenge_rpc = observe_challenge
                original_battle_rpc = c.battle_rpc
                async def observe_battle(command, slot=i, original=original_battle_rpc, **kwargs):
                    nonlocal fault_used
                    if slot == 0 and command.opcode == BattleOpcode.ADMISSION_CANCEL_HANDOFF:
                        saver = getattr(companions[0], "_emergency_controller", None)
                        if saver is not handoff_saver or saver.result.state != "armed" or saver.needs_arm:
                            raise AssertionError("native release preceded the exact fresh emergency saver")
                        record("fresh-exact-emergency-saver-armed-before-native-HANDOFF")
                    response = await original(command, **kwargs)
                    evidence["battle_commands"].append(dict(slot=slot, opcode=int(command.opcode), status=int(response.status),
                        command_sha256=hashlib.sha256(command.pack()).hexdigest(), response_sha256=hashlib.sha256(response.pack()).hexdigest()))
                    if slot == 0 and command.opcode == BattleOpcode.ADMISSION_CANCEL_HOLD and args.fault == "lost-hold" and not fault_used:
                        if response.status:
                            raise AssertionError("cannot withhold an unsuccessful native HOLD receipt")
                        fault_used = True
                        fault_ready.set()
                        await fault_release.wait()
                        raise ConnectionError("proof withheld the real successful HOLD receipt during host loss")
                    return response
                c.battle_rpc = observe_battle
                await c.start()
                lease = MirrorLease(saves[i]); lease.__enter__(); leases.append(lease)
                script = root/f"bridge-{i}.lua"
                script.write_text(configure(manifest, c.config.token.hex(), c.ipc_address[1], bridge_text))
                process = await asyncio.create_subprocess_exec(str(args.harness), str(rom), str(saves[i]), str(script),
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                cores.append(LockedCore(process, root/f"core-{i}.log"))
                all_cores.append(cores[-1])
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
            await choose(0, "Rival Battle - 1v1")
            await open_menu(1)
            await choose(1, "Pending challenge")
            await choose(1, "Accept challenge")
            while (await menu_state(1))[0]:
                await press(1, 2)
            await pump.advance(90)
            async with asyncio.timeout(15):
                while not (await ready(0))[3].admission_action:
                    await asyncio.sleep(.05)
            await choose(0, "Enter battle", wait=False)
            await asyncio.wait_for(phase_ready.wait(), 15)
            intent = read_admission_intent(root/"private-0"/FILENAME)
            if intent != captured[0] or intent.challenge != captured[0].challenge:
                raise AssertionError("selected native Enter lost its original durable identity")
            expected_flag = 1 if args.phase == "enter" else 2
            initial = await stable_input_hold("actual-" + args.phase + "-holds-personal-state-before-cleanup", expected_flag)
            retained = (cores[0], cores[0].process.pid, companions[0]._bridge,
                        companions[0].battle_incarnation, companions[0]._live_battle_runtime_id)
            if args.phase == "enter":
                if any(row["opcode"] == int(BattleOpcode.ADMIT) for row in evidence["battle_commands"]):
                    raise AssertionError("raw Enter case unexpectedly executed ADMIT")
            else:
                read_admission_receipt(root/"private-0", intent)
            if any(row["opcode"] in (int(BattleOpcode.BIND), int(BattleOpcode.START)) for row in evidence["battle_commands"]):
                raise AssertionError("cleanup case crossed into full battle authority")
            c = companions[0]
            fields = dict(battle_id=intent.battle_id, generation=intent.generation,
                          incarnation=intent.incarnation, runtime_id=intent.runtime_id)
            cleanup = AdmissionCleanupSession(c, root/"private-0", intent)
            readiness = await cleanup.ready()
            # These negative calls go through authenticated production validation.
            # A refusal here is host/client evidence, not a native dispatch claim.
            for key in ("battle_id", "generation", "runtime_id"):
                wrong = dict(fields, **{key: str(uuid4())})
                try:
                    await c.battle_challenge_rpc("cancel_admission", **wrong,
                        cleanup_ready_b64=encode_control(readiness), cleanup_receipt_b64=None)
                except BattleChallengeError as error:
                    expected = "battle_admission_invalid" if key == "battle_id" else "battle_incarnation_changed"
                    if error.code != expected:
                        raise AssertionError(("identity case failed at another gate", key, error.code)) from error
                    record("wrong-identity-refused-before-native-dispatch", field=key, error_code=error.code)
                else:
                    raise AssertionError(("wrong cleanup identity accepted", key))
            await cleanup.revoke_before_menu_drain()
            if not tombstone_seen or not cleanup_path(root/"private-0", intent).is_file():
                raise AssertionError("production revocation did not persist before the menu drain")
            record("production-revocation-persisted-before-gated-menu-task-drain")
            expected_gate_cancel = True
            task = c._bridge.menu_session._task
            if task is None or task.done():
                raise AssertionError("selected native operation was not retained at its proof gate")
            task.cancel()
            await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 10)
            if not task.done() or c._bridge.menu_session._battle_preparing:
                raise AssertionError("gated menu operation did not relinquish Python ownership")
            record("gated-menu-operation-drained-after-durable-host-and-local-fence")
            cleanup_task = asyncio.create_task(cleanup.run())
            if args.fault == "lost-hold":
                await asyncio.wait_for(fault_ready.wait(), 30)
                before_loss = await stable_input_hold("real-reply-withheld-core-still-held", 32)
                port = server.address[1]
                await server.close()
                fault_release.set()
                try:
                    await asyncio.wait_for(cleanup_task, 15)
                except ConnectionError:
                    pass
                else:
                    raise AssertionError("withheld real reply did not interrupt cleanup")
                for saver in emergency:
                    await asyncio.wait_for(saver.lost.wait(), 30)
                    await asyncio.wait_for(saver.drain(), 30)
                if emergency[0].result.state != "battle_waiting":
                    raise AssertionError(("cleanup host loss escaped retained battle wait", emergency[0].result))
                if emergency[1].result.state != "preserved" or not emergency[1].result.can_close:
                    raise AssertionError("unrelated original peer was not ordinarily preserved")
                if await native_snapshot(0) != before_loss:
                    raise AssertionError("host loss changed the retained cleanup core")
                store.close()
                store = TradeCheckpointStore(root/"world.sqlite3", manifest["rom_sha256"], manifest["ruleset_id"])
                server = WorldServer(ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"], heartbeat_interval=.2, idle_timeout=12),
                    store=store, development_trades=True, development_battles=True)
                server.enable_battle_execution(read_string_lengths(rom, table_address=manifest["battle_string_table_address"]),
                    root/"execution-host", resume_enabled=True)
                await server.start(port=port)
                record("real-host-and-SQLite-reopened-with-original-core-retained", fault=args.fault)
                cleanup_task = asyncio.create_task(AdmissionCleanupSession(c, root/"private-0", intent).run())
            completion = await asyncio.wait_for(cleanup_task, 45)
            verify_cleanup_completion(c, root/"private-0", completion, intent, retained[2])
            terminal = await stable_input_hold("durable-cleanup-terminal-hold-awaits-fresh-save-handoff", 32)
            for key in ("party_sha256", "party_count", "rng", "rng2", "position", "playtime", "save_counter", "flash_sha256"):
                if initial[key] != terminal[key]:
                    raise AssertionError(("neutral cleanup changed personal state", key, initial, terminal))
            if (cores[0], cores[0].process.pid, c._bridge, c.battle_incarnation, c._live_battle_runtime_id) != retained:
                raise AssertionError("cleanup replaced its original core")
            tombstone_path = root/"execution-host"/(intent.battle_id + ".consent.json")
            tombstone = tombstone_path.read_bytes()
            cleanup_record = json.loads(cleanup_path(root/"private-0", intent).read_text())
            if (not json.loads(tombstone)["canceled"]
                    or hashlib.sha256(tombstone).hexdigest() != cleanup_record["cancellation"]["tombstone_sha256"]
                    or list((root/"execution-host").glob("*.events.jsonl"))):
                raise AssertionError("cleanup lost its durable never-routed cancellation fence")
            try:
                await c.battle_challenge_rpc("claim", **fields)
            except BattleChallengeError as error:
                if error.code not in {"battle_not_ready", "battle_missing", "stale_lease", "battle_admission_canceled"}:
                    raise AssertionError(("late claim failed at another gate", error.code)) from error
                record("late-original-claim-refused-with-durable-host-tombstone", error_code=error.code)
            else:
                raise AssertionError("canceled original consent could be reclaimed")
            if await native_snapshot(0) != terminal or tombstone_path.read_bytes() != tombstone:
                raise AssertionError("late rejected request changed native terminal hold")
            await emergency[0].retire_after_admission_cleanup(completion, intent, retained[2])
            if args.fault == "lost-retirement":
                retired_completion = completion
                retirement_path = root/"private-0"/(intent.battle_id + ".admission-emergency-retirement.json")
                retirement_bytes = retirement_path.read_bytes()
                retired_state = await stable_input_hold("old-emergency-retired-before-fresh-ARM-core-still-held", 32)
                port = server.address[1]
                await server.close()
                async with asyncio.timeout(30):
                    while c.connected or not c._reconnect_blocked:
                        await asyncio.sleep(.03)
                await asyncio.wait_for(emergency[1].lost.wait(), 30)
                await asyncio.wait_for(emergency[1].drain(), 30)
                if emergency[1].result.state != "preserved" or not emergency[1].result.can_close:
                    raise AssertionError("peer did not preserve during the retired-saver interruption")
                if await native_snapshot(0) != retired_state:
                    raise AssertionError("retired-saver host loss changed its retained terminal hold")
                store.close()
                store = TradeCheckpointStore(root/"world.sqlite3", manifest["rom_sha256"], manifest["ruleset_id"])
                server = WorldServer(ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"], heartbeat_interval=.2, idle_timeout=12),
                    store=store, development_trades=True, development_battles=True)
                server.enable_battle_execution(read_string_lengths(rom, table_address=manifest["battle_string_table_address"]),
                    root/"execution-host", resume_enabled=True)
                await server.start(port=port)
                cleanup_task = asyncio.create_task(AdmissionCleanupSession(c, root/"private-0", intent).run())
                completion = await asyncio.wait_for(cleanup_task, 45)
                verify_cleanup_completion(c, root/"private-0", completion, intent, retained[2])
                if completion.renewed_session.lease_epoch <= retired_completion.renewed_session.lease_epoch:
                    raise AssertionError("retired-saver retry did not renew its real host authentication")
                await emergency[0].retire_after_admission_cleanup(completion, intent, retained[2])
                if await native_snapshot(0) != retired_state or retirement_path.read_bytes() != retirement_bytes:
                    raise AssertionError("renewed retirement proof changed native personal state")
                record("host-loss-after-old-retirement-retried-same-core-before-fresh-ARM",
                       previous=asdict(retired_completion), renewed=asdict(completion),
                       immutable_retirement_sha256=hashlib.sha256(retirement_bytes).hexdigest())
            if (cores[0], cores[0].process.pid, c._bridge, c.battle_incarnation, c._live_battle_runtime_id) != retained:
                raise AssertionError("terminal retry replaced its original native core")
            handoff_saver = EmergencySaveController(c, root/"private-0")
            await handoff_saver.arm(intent.canonical_revision)
            emergency[0] = handoff_saver
            await complete_cleanup_handoff(c, root/"private-0", completion, intent, retained[2], handoff_saver)
            c._bridge.menu_session.finish_battle_admission(intent.battle_id, intent.generation)
            await pump.advance(120)
            if (await native_snapshot(0))["hold_flags"]:
                raise AssertionError("native handoff did not release field ownership")
            position = (c._local_pose.x, c._local_pose.y)
            for key in (0x10, 0x20, 0x40, 0x80):
                await press(0, key, frames=18, release=48)
                if c._local_pose.activity == 1 and (c._local_pose.x, c._local_pose.y) != position:
                    break
            else:
                raise AssertionError("ordinary field movement did not resume after cleanup")
            record("ordinary-field-movement-resumed-after-fresh-saver-HANDOFF")
            prior = store.read_checkpoint(players[0].player_id, c.session_epoch)
            prior_inventory = inspect_ownership(inspect_flash(prior.payload, save_profile=OWNERSHIP_PROFILE)).records
            receipt = await LiveCheckpointCoordinator(c, root/"private-0").checkpoint(expected_revision=intent.canonical_revision)
            if receipt.metadata["revision"] != intent.canonical_revision + 1:
                raise AssertionError("ordinary checkpoint did not advance once")
            current = store.read_checkpoint(players[0].player_id, c.session_epoch)
            if inspect_ownership(inspect_flash(current.payload, save_profile=OWNERSHIP_PROFILE)).records != prior_inventory:
                raise AssertionError("ordinary checkpoint changed owned inventory")
            record("ordinary-native-checkpoint-preserves-owned-inventory", revision=current.revision)
            configs = [value.config for value in companions]
            await pump.close()
            pump = None
            await asyncio.gather(*(value.close() for value in companions))
            await close_cores()
            cores.clear()
            companions.clear()
            for config in configs:
                value = Companion(replace(config, token=secrets.token_bytes(32), ipc_port=0, server_port=server.address[1]))
                companions.append(value)
                await value.start()
            async with asyncio.timeout(20):
                while not all(value.connected and value._bridge is None for value in companions):
                    await asyncio.sleep(.03)
            for i, value in enumerate(companions):
                context = ColdStartRecovery(value, root/f"private-{i}", saves[i]).open()
                verified = await context.__aenter__()
                cold_contexts.append(context)
                script = root/f"fresh-bridge-{i}.lua"
                script.write_text(configure(manifest, value.config.token.hex(), value.ipc_address[1], bridge_text))
                process = await asyncio.create_subprocess_exec(str(args.harness), str(rom), str(saves[i]), str(script),
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                cores.append(LockedCore(process, root/f"fresh-core-{i}.log"))
                all_cores.append(cores[-1])
                if not (await asyncio.wait_for(process.stdout.readline(), 20)).startswith(b"READY"):
                    raise RuntimeError("fresh proof core did not start")
            for key, frames in ((0, 1000), (8, 8), (0, 480), (8, 8), (0, 180), (1, 8), (0, 300)):
                for offset in range(0, frames, 24):
                    await asyncio.gather(*(core.command(f"F {key:x} {min(24, frames-offset)}") for core in cores))
                    await asyncio.sleep(.003)
            pump = MenuPump(cores, companions)
            pump.start()
            await pump.advance(120)
            for i, value in enumerate(companions):
                checkpoint = store.read_checkpoint(players[i].player_id, value.session_epoch)
                parsed = inspect_flash(checkpoint.payload, save_profile=OWNERSHIP_PROFILE)
                pose = value._local_pose
                if pose is None or pose.activity != 1:
                    raise AssertionError("fresh native Continue did not reach the field")
                for key in ("map_group", "map_number", "x", "y"):
                    if getattr(pose, key) != getattr(parsed.metadata, key):
                        raise AssertionError(("fresh Continue position differs", i, key))
                state = await native_snapshot(i)
                if state["hold_flags"] or state["party_sha256"] != hashlib.sha256(parsed.save_block1[0x238:0x238+600]).hexdigest():
                    raise AssertionError("fresh Continue changed party or retained a stale hold")
            store.integrity_check()
            record("fresh-native-Continue-and-canonical-party-map-preserved")
            completed = True
            record("same-original-core-cleanup-and-fresh-Continue-complete", admission=intent.value())
    except BaseException as error:
        evidence["error"] = repr(error)
        evidence["traceback"] = traceback.format_exc()
        persist()
        raise
    finally:
        # All children and mirrors are this proof's disposable copies. This
        # Cleanup never settles a bound or possibly dispatched battle.
        expected_gate_cancel = True
        fault_release.set()
        async def finish_resource(label, awaitable, seconds=10):
            try:
                await asyncio.wait_for(awaitable, seconds)
            except BaseException as error:
                evidence["cleanup_errors"].append(dict(resource=label, error=repr(error)))
        if cleanup_task is not None and not cleanup_task.done():
            cleanup_task.cancel()
            await finish_resource("cleanup-operation", asyncio.gather(cleanup_task, return_exceptions=True))
        for c in companions:
            if c._bridge is not None and c._bridge.menu_session is not None:
                task = c._bridge.menu_session._task
                if task is not None and not task.done():
                    task.cancel()
                    await finish_resource("menu-operation", asyncio.gather(task, return_exceptions=True))
        await close_cores()
        for c in companions:
            await finish_resource("companion", c.close())
        for context in reversed(cold_contexts):
            await finish_resource("cold-start-context", context.__aexit__(None, None, None))
        await finish_resource("world-server", server.close())
        try:
            store.close()
        except BaseException as error:
            evidence["cleanup_errors"].append(dict(resource="checkpoint-store", error=repr(error)))
        for name, verify in (
            ("originals_unchanged", lambda: all(path.read_bytes() == raw for path, raw in zip(sources, originals))),
            ("python_sources_unchanged", lambda: all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
                for path, digest in source_hashes.items())),
            ("inputs_unchanged", lambda: all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
                for path, digest in input_hashes.items())),
        ):
            try:
                evidence[name] = verify()
            except BaseException as error:
                evidence[name] = False
                evidence["cleanup_errors"].append(dict(resource=name, error=repr(error)))
        evidence["passed"] = (completed and evidence["cores_closed"] and evidence["originals_unchanged"]
            and evidence["python_sources_unchanged"] and evidence["inputs_unchanged"]
            and not evidence["cleanup_errors"] and len(closures) == len(all_cores)
            and all(row["alive_before_q"] and row["returncode"] == 0 and not row["forced"]
                    and not row["failures"] for row in closures.values()))
        persist()
        if completed and not evidence["passed"]:
            raise AssertionError("cleanup or immutable-input verification failed; inspect final evidence")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rom", "elf", "manifest", "harness", "save-a", "save-b", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--bridge", type=Path, default=Path(__file__).parents[2]/"bridge/mgba.lua")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--phase", choices=("enter", "admit"), required=True)
    parser.add_argument("--fault", choices=("none", "lost-hold", "lost-retirement"), default="none")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
