"""Four retained actual cores recovering after a bounded host failure.

The production host executor routes authenticated participants' typed blocks
and the production client journals own every mailbox mutation. This is not the
player challenge UI or an Internet proof. Gameplay uses ordinary joypad
inputs. Core memory and Flash access below is read-only diagnostic evidence.
Faults interrupt only production command delivery/receipt and host transport.
This controller is separate from the preserved no-interruption baseline.
The pre-bind fault withholds the first full BIND after full intent publication;
it does not qualify the earlier native Players Enter/provisional-only boundary.
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
import time
import traceback
from uuid import uuid4

from configure_bridge import configure
from live_checkpoint_proof import LockedCore
from native_execution_proof import ExecutionPump
from emerald_multiplayer.battle_controller import ControllerValidator, read_string_lengths
from emerald_multiplayer.battle_roster import CanonicalBattler
from emerald_multiplayer.battle_session import NativeBattleSession
from emerald_multiplayer.battle_recovery_session import NativeBattleRecoverySession, verify_recovery_completion
from emerald_multiplayer.battle_terminal import complete_battle_handoff
from emerald_multiplayer.battle_journal import read_battle_intent
from emerald_multiplayer.native_battle import Opcode
from emerald_multiplayer.checkpoint_mirror import MirrorLease, MirrorError
from emerald_multiplayer.cold_start import ColdStartRecovery
from emerald_multiplayer.companion import Companion, CompanionConfig, verify_rom_manifest
from emerald_multiplayer import companion as companion_module
from emerald_multiplayer.emergency_save import EmergencySaveController
from emerald_multiplayer.flash import inspect_flash
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator
from emerald_multiplayer.mailbox import inspect_mailbox
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, inspect_ownership
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.trade_storage import TradeCheckpointStore


async def drain_interrupted_operations(tasks, *, timeout=30):
    """End prior explicit recovery calls before selecting the next reconnect set.

    Recovery deliberately keeps trying after transport loss. Cancel only those
    Python operations, never the original cores or their durable intent. A
    drain timeout refuses the next stage instead of overlapping lifecycle owners.
    """
    operations = tuple(dict.fromkeys(tasks))
    for task in operations:
        if not task.done():
            task.cancel()
    if not operations:
        return
    finished, pending = await asyncio.wait(operations, timeout=timeout)
    await asyncio.gather(*finished, return_exceptions=True)
    if pending:
        raise TimeoutError("previous explicit battle operations did not drain before the next recovery stage")


async def run(args):
    root = args.output.resolve()
    if "/multiplayer-proof/" not in str(root)+"/" or root.exists():
        raise ValueError("choose a new private multiplayer-proof output directory")
    _, manifest = verify_rom_manifest(args.rom, args.manifest)
    if (manifest.get("battle_abi_version") != 3 or manifest.get("battle_resume_abi_version") != 1
            or manifest.get("battle_execution_abi_version") != 1 or manifest.get("emergency_save_abi_version") != 2):
        raise ValueError("recovery requires the exact ABI3/full-Multi execution1/resume1/emergency2 ROM")
    if (not math.isfinite(args.timeout) or not 60 <= args.timeout <= 7200
            or not 120 <= args.hold_frames <= 600 or not 0 <= args.fault_slot < 4):
        raise ValueError("recovery needs a bounded timeout, sustained hold and original participant slot")
    if hashlib.sha256(args.elf.read_bytes()).hexdigest() != manifest["elf_sha256"]:
        raise ValueError("ELF does not match the native build manifest")
    sources = [args.save_a, args.save_b, args.save_c, args.save_d]
    originals = [path.read_bytes() for path in sources]
    source_meta = [inspect_flash(payload).metadata for payload in originals]
    if len({m.trainer_id for m in source_meta}) != len(sources) or not all(m.party_count for m in source_meta):
        raise ValueError("four independent trainers with ordinarily obtained Pokémon are required")
    if args.require_full_parties and any(m.party_count != 6 for m in source_meta):
        raise ValueError("the full-six acceptance run requires six ordinary Pokémon per trainer")
    original_hashes = [hashlib.sha256(data).hexdigest() for data in originals]
    root.mkdir(parents=True, mode=0o700)
    rom, manifest_path = root/"proof.gba", root/"manifest.json"
    rom.write_bytes(args.rom.read_bytes())
    manifest_path.write_bytes(args.manifest.read_bytes())
    (root/"controller.py").write_bytes(Path(__file__).read_bytes())
    bridge_source = args.bridge.read_text()
    (root/"bridge-source.lua").write_text(bridge_source)
    # Retain the exact controller dependencies used by this run and reject
    # source mutation during execution. The operator must run from a frozen
    # tree: a filesystem copy cannot establish which earlier code was loaded.
    package_root = Path(companion_module.__file__).parent
    source_files = sorted(package_root.rglob("*.py"))
    source_files += sorted(Path(__file__).parent.glob("*.py"))
    source_hashes = {}
    for source in source_files:
        relative = (Path("scripts") / source.name if source.parent == Path(__file__).parent
                    else Path("emerald_multiplayer") / source.relative_to(package_root))
        destination = root/"python-source"/relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = source.read_bytes()
        destination.write_bytes(payload)
        source_hashes[str(source)] = hashlib.sha256(payload).hexdigest()
    evidence = dict(scope="four actual native full-party Multi cores; authenticated consent/execution, lost host and reopened SQLite, original-core wait-all recovery; no native menu, packaged launcher, Windows or Internet claim",
        engine_commit=manifest["engine_commit"], rom_sha256=manifest["rom_sha256"],
        elf_sha256=manifest["elf_sha256"], controller_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        bridge_sha256=hashlib.sha256(bridge_source.encode()).hexdigest(),
        harness_sha256=hashlib.sha256(args.harness.read_bytes()).hexdigest(),
        frozen_python_sources=source_hashes,
        party_counts=[m.party_count for m in source_meta],
        require_full_parties=args.require_full_parties, scenario=args.scenario,
        sources=[dict(path=str(p), sha256=h, trainer_id=m.trainer_id)
                 for p, h, m in zip(sources, original_hashes, source_meta)],
        checks=[], snapshots=[], commands=[], blocks=[], native_dispatches=[],
        passed=False, cores_closed=False)

    def persist():
        (root/"evidence.json").write_text(json.dumps(evidence, indent=2)+"\n")

    def record(name, **fields):
        row = dict(verified=name, **fields)
        evidence["checks"].append(row)
        persist()
        print(json.dumps(row), flush=True)

    process = await asyncio.create_subprocess_exec("arm-none-eabi-nm", "-S", str(args.elf), stdout=asyncio.subprocess.PIPE)
    symbols = {}
    for line in (await process.communicate())[0].decode().splitlines():
        parts = line.split()
        if len(parts) == 4:
            symbols[parts[3]] = (int(parts[0], 16), int(parts[1], 16))
    required = {"gBattleStringsTable": 721*4, "gRngValue": 16, "gRng2Value": 16,
                "gSaveCounter": 4, "gPartiesCount": 4, "gBattleTypeFlags": 4,
                "gTasks": 16*40, "gPartyMenu": 20, "gMultiplayerBattleHoldFlags": 4}
    if process.returncode or any(name not in symbols or symbols[name][1] != size for name, size in required.items()):
        raise ValueError("native proof symbols do not match the pinned ARM layout")
    party_tasks = ("Task_HandleChooseMonInput", "Task_HandleSelectionMenuInput", "Task_PrintAndWaitForText")
    if any(name not in symbols or not 0x08000000 <= symbols[name][0] < 0x0A000000 for name in party_tasks):
        raise ValueError("party input diagnostics require the matching native menu symbols")
    evidence["party_joypad"] = []
    validator = ControllerValidator(read_string_lengths(rom, table_address=symbols["gBattleStringsTable"][0]), mode=3)
    store = TradeCheckpointStore(root/"world.sqlite3", manifest["rom_sha256"], manifest["ruleset_id"])
    from emerald_multiplayer.battle_reservations import enable_battle_reservations
    enable_battle_reservations(store, root/"before-battle-reservations.sqlite3")
    identities = sorted([store.create_player("Native Multi "+name) for name in "ABCD"], key=lambda p: p.player_id)
    for identity, payload in zip(identities, originals):
        store.enroll_player(identity.player_id, payload)
    (root/"profiles.json").write_text(json.dumps([dict(player_id=i.player_id,
        display_name=i.display_name, credential=i.credential.hex()) for i in identities], indent=2)+"\n")
    execution_started = time.monotonic()
    def create_server():
        host = WorldServer(ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"],
            heartbeat_interval=.2, idle_timeout=12), store=store, development_trades=True, development_battles=True)
        host.enable_battle_execution(read_string_lengths(rom, table_address=symbols["gBattleStringsTable"][0]),
            root/"execution-host", resume_enabled=True)
        host.battle_execution.observer = lambda block: evidence["blocks"].append(
            dict(block, frame=pump.frames, elapsed_seconds=round(time.monotonic()-execution_started, 6)))
        original_command = host.battle_execution._command
        async def timed_command(room, actor, command):
            started = time.monotonic()
            try:
                return await original_command(room, actor, command)
            finally:
                evidence["commands"].append(dict(source=room.battle.players.index(actor),
                    opcode=int(command.opcode), seconds=round(time.monotonic()-started, 6)))
        host.battle_execution._command = timed_command
        return host
    server = create_server()
    await server.start(port=0)
    saves = [root/f"client-{name}.sav" for name in "abcd"[:len(sources)]]
    companions, live, cores, all_cores, leases, rosters = [], [], [], [], [], []
    pump = None
    battle_id, generation, rng = str(uuid4()), None, None
    desk = None
    cold_contexts, execution_tasks, recovery_tasks, emergency = [], [], [], []
    party_input = [None]*4
    revisions = [0]*len(sources)
    fault_ready, fault_disconnected = asyncio.Event(), asyncio.Event()
    fault_active = False
    fault_stages = ["pre-bind", "mid-battle", "post-release"] if args.scenario == "all" else [args.scenario]
    completed_faults = []
    preparation_states = [None]*4

    def next_fault():
        return fault_stages[len(completed_faults)] if len(completed_faults) < len(fault_stages) else None

    def observe_dispatch(i, companion):
        """Withhold one real transport delivery/receipt, never synthesize one."""
        original_rpc = companion.battle_rpc
        async def observed(command, *rpc_args, **rpc_kwargs):
            row = dict(slot=i, opcode=int(command.opcode), sequence=command.sequence,
                lease=command.session_epoch, incarnation=command.incarnation,
                command_sha256=hashlib.sha256(command.pack()).hexdigest(), started=time.monotonic())
            evidence["native_dispatches"].append(row)
            selected = i == args.fault_slot and not fault_active
            if selected and next_fault() == "pre-bind" and command.opcode == Opcode.BIND:
                row["fault"] = "delivery withheld before first native BIND"
                fault_ready.set()
                await fault_disconnected.wait()
                raise ConnectionError("qualification withheld the native command delivery")
            before_prepare = await native_state(i) if command.opcode == Opcode.PREPARE else None
            response = await original_rpc(command, *rpc_args, **rpc_kwargs)
            row["response_sha256"] = hashlib.sha256(response.pack()).hexdigest()
            row["status"] = int(response.status)
            if not response.status and before_prepare is not None:
                preparation_states[i] = before_prepare
            if not response.status and command.opcode == Opcode.RELEASE:
                restored = await native_state(i)
                prepared = preparation_states[i]
                if prepared is None:
                    raise AssertionError("native RELEASE had no observed original preparation")
                for key in ("party_sha256", "party_count", "rng", "rng2", "counter"):
                    if restored[key] != prepared[key]:
                        raise AssertionError(("native RELEASE did not restore personal state", i, key))
                row["restored_personal_state"] = restored
            if selected and next_fault() == "post-release" and command.opcode == Opcode.RELEASE and not response.status:
                row["fault"] = "successful native RELEASE receipt withheld from client journal"
                fault_ready.set()
                await fault_disconnected.wait()
                raise ConnectionError("qualification withheld the native RELEASE receipt")
            return response
        companion.battle_rpc = observed

    async def boot():
        for key, frames in ((0, 1000), (8, 8), (0, 480), (8, 8), (0, 180), (1, 8), (0, 300)):
            for offset in range(0, frames, 24):
                await asyncio.gather(*(c.command(f"F {key:x} {min(24, frames-offset)}") for c in cores))
                await asyncio.sleep(.003)
        for _ in range(400):
            if all(c.connected and c._bridge and c._bridge.save_capable and c._bridge.battle_capable for c in companions):
                return
            await asyncio.sleep(.025)
        raise AssertionError("native bridge capability did not become available")

    async def launch(i, held_lease=None):
        if held_lease is None:
            lease = MirrorLease(saves[i])
            lease.__enter__()
            leases.append(lease)
        elif not held_lease._held or held_lease.save_path != saves[i].resolve():
            raise ValueError("cold startup must retain the correct closed-save lease")
        script = root/f"bridge-{i}-{len(all_cores)}.lua"
        script.write_text(configure(manifest, companions[i].config.token.hex(), companions[i].ipc_address[1], bridge_source))
        proc = await asyncio.create_subprocess_exec(str(args.harness), str(rom), str(saves[i]), str(script),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        core = LockedCore(proc, root/f"core-{i}-{len(all_cores)}.log")
        cores.append(core)
        all_cores.append(core)
        if not (await asyncio.wait_for(proc.stdout.readline(), 30)).startswith(b"READY"):
            raise RuntimeError("actual native core failed to start")

    async def snapshot(label):
        rows = []
        for i, core in enumerate(cores):
            pose, _ = inspect_mailbox(await core.read(manifest["mailbox_address"], 128))
            state = int.from_bytes(await core.read(manifest["battle_mailbox_address"]+12, 4), "little")
            await core.command(f"P {root/(label+'-'+str(i)+'.png')}")
            rows.append(dict(player=i, pid=core.process.pid, pose=asdict(pose), state=state))
        evidence["snapshots"].append(dict(label=label, rows=rows))
        persist()
        return rows

    async def drive_party_menu(i):
        # Read-only task/cursor diagnostics let normal joypad presses wait for
        # the actual menu. Blind Down/A bursts can land in a text printer or
        # SEND OUT submenu and repeatedly reselect the same fainted Pokemon.
        # The pinned ARM PartyMenu has slotId at byte 9; Task is 40 bytes with
        # its active flag at byte 4. Neither structure is ever written here.
        # Twelve ordinary frames provide a bounded real menu key press under
        # the imported pinned frame pump; no cursor memory is written.
        async def press(key, frames=12, release=18):
            evidence["party_joypad"].append(dict(owner=i, key=key, frames=frames,
                release=release, frame=pump.frames))
            pump.keys[i] = key
            await pump.advance(frames)
            pump.keys[i] = 0
            await pump.advance(release)

        async def menu_state():
            tasks = await cores[i].read(*symbols["gTasks"])
            active = {int.from_bytes(tasks[o:o+4], "little") & ~1
                for o in range(0, len(tasks), 40) if tasks[o+4]}
            cursor = (await cores[i].read(symbols["gPartyMenu"][0]+9, 1))[0]
            return active, cursor

        pump.keys[i] = 0
        deadline = time.monotonic()+120
        while validator.pending[i] == 21:
            if time.monotonic() >= deadline:
                raise AssertionError(("ordinary party menu did not accept a usable Pokemon", i))
            active, cursor = await menu_state()
            if symbols["Task_PrintAndWaitForText"][0] & ~1 in active:
                await press(2, release=30)
            elif symbols["Task_HandleSelectionMenuInput"][0] & ~1 in active:
                await press(1)  # Native menu's initial SEND OUT action.
            elif symbols["Task_HandleChooseMonInput"][0] & ~1 in active:
                await press(0x80)
                current, moved = await menu_state()
                if (symbols["Task_HandleChooseMonInput"][0] & ~1 in current
                        and moved != cursor and 0 <= moved < 6):
                    await press(1)
            else:
                await pump.advance(12)
        pump.keys[i] = 0

    async def native_state(i):
        core = cores[i]
        party = await core.read(manifest["debug_parties_address"], 600)
        ptr = int.from_bytes(await core.read(manifest["debug_save_block2_ptr_address"], 4), "little")
        return dict(party_sha256=hashlib.sha256(party).hexdigest(),
            party_count=(await core.read(symbols["gPartiesCount"][0], 1))[0],
            rng=(await core.read(symbols["gRngValue"][0], 16)).hex(),
            rng2=(await core.read(symbols["gRng2Value"][0], 16)).hex(),
            playtime=(await core.read(ptr+manifest["debug_play_time_offset"], 5)).hex(),
            counter=int.from_bytes(await core.read(symbols["gSaveCounter"][0], 4), "little"))

    async def retained_state():
        rows = []
        for i, core in enumerate(cores):
            row = await native_state(i)
            row["pid"] = core.process.pid
            row["incarnation"] = companions[i].battle_incarnation
            row["native_state"] = int.from_bytes(await core.read(manifest["battle_mailbox_address"]+12, 4), "little")
            if symbols.get("gMultiplayerBattleHoldFlags", (0, 0))[1] != 4:
                raise AssertionError("pinned read-only native hold diagnostic is unavailable")
            row["held_flags"] = int.from_bytes(await core.read(*symbols["gMultiplayerBattleHoldFlags"]), "little")
            row["gameplay"] = {}
            for name in ("gBattleMainFunc", "gBattleControllerExecFlags", "gBattleMons",
                         "gBattlerPartyIndexes", "gBattleCommunication"):
                if name not in symbols or symbols[name][1] > 4096:
                    raise AssertionError("pinned native gameplay diagnostic is unavailable: " + name)
                row["gameplay"][name] = hashlib.sha256(await core.read(*symbols[name])).hexdigest()
            rows.append(row)
        return rows

    async def stable_hold(label, scenario):
        first = await retained_state()
        allowed = {9, 10} if scenario == "pre-bind" else {1, 9} if scenario == "post-release" else {9}
        if not all(row["native_state"] in allowed for row in first):
            raise AssertionError(("every original core must be natively suspended", label, first))
        if scenario == "pre-bind" and first[args.fault_slot]["native_state"] != 10:
            raise AssertionError("withheld BIND lost its exact provisional native hold")
        for row in first:
            if row["native_state"] == 10 and row["held_flags"] != 0x2:
                raise AssertionError("provisional native marker is missing")
            if row["native_state"] == 9 and row["held_flags"] != 0x4:
                raise AssertionError("suspended native marker is missing")
            if row["native_state"] == 1 and row["held_flags"] not in (0x8, 0x10):
                raise AssertionError("terminal native marker is missing")
        # Sustained ordinary directional input must not escape either hold.
        pump.keys[:] = [0x10]*4
        try:
            await pump.advance(args.hold_frames)
        finally:
            pump.keys[:] = [0]*4
        second = await retained_state()
        if first != second:
            raise AssertionError(("held core gameplay progressed while waiting", label, first, second))
        record(label, scenario=scenario, retained=second, frames=args.hold_frames)

    async def interrupt_and_recover(scenario):
        nonlocal server, store, desk, fault_active, recovery_tasks
        fault_active = True
        original_port = server.address[1]
        originals_retained = [(core, core.process.pid, c._bridge, c.battle_incarnation,
                              c._live_battle_runtime_id) for core, c in zip(cores, companions)]
        original_intents = [read_battle_intent(root/f"private-{i}"/"pending-battle.json") for i in range(4)]
        original_intent_bytes = [(root/f"private-{i}"/"pending-battle.json").read_bytes() for i in range(4)]
        record("fault-at-production-dispatch-boundary", scenario=scenario,
            frame=pump.frames, retained_pids=[value[1] for value in originals_retained],
            original_intent_hashes=[hashlib.sha256(raw).hexdigest() for raw in original_intent_bytes])
        for i, companion in enumerate(companions):
            try:
                async with ColdStartRecovery(companion, root/f"private-{i}", saves[i]).open():
                    raise AssertionError("cold replacement acquired a retained game's save")
            except MirrorError as error:
                if error.code != "mirror_active":
                    raise
        record("cold-replacement-refused-by-all-four-retained-mirror-leases")
        pump.keys[:] = [0]*4
        for selection in party_input:
            if selection is not None and not selection.done():
                selection.cancel()
        await asyncio.gather(*(t for t in party_input if t is not None), return_exceptions=True)
        party_input[:] = [None]*4
        await server.close()
        fault_disconnected.set()
        await drain_interrupted_operations(execution_tasks)
        async with asyncio.timeout(30):
            while any(c.connected for c in companions):
                await asyncio.sleep(.02)
            for controller in emergency:
                await controller.lost.wait()
                if controller.task is not None:
                    await controller.task
                if controller.result.state != "battle_waiting":
                    raise AssertionError(("host loss changed the battle into another lifecycle", controller.result))
            allowed = {9, 10} if scenario == "pre-bind" else {1, 9} if scenario == "post-release" else {9}
            while not all(row["native_state"] in allowed for row in await retained_state()):
                await asyncio.sleep(.05)
        await stable_hold("all-four-original-cores-frozen-after-host-loss", scenario)
        for i in range(4):
            if (root/f"private-{i}"/"pending-battle.json").read_bytes() != original_intent_bytes[i]:
                raise AssertionError("host loss changed an original battle intent")
        store.integrity_check()
        store.close()
        store = TradeCheckpointStore(root/"world.sqlite3", manifest["rom_sha256"], manifest["ruleset_id"])
        store.integrity_check()
        server = create_server()
        await server.start(port=original_port)
        desk = server.battle_desk
        recoveries = [NativeBattleRecoverySession(c, root/f"private-{i}", original_intent=original_intents[i])
                      for i, c in enumerate(companions)]
        recovery_tasks = [asyncio.create_task(recoveries[i].run(), name=f"proof-recovery-{i}") for i in range(3)]
        async with asyncio.timeout(30):
            while not all(c.connected for c in companions[:3]):
                for task in recovery_tasks:
                    if task.done():
                        await task
                        raise AssertionError("a partial quorum completed battle recovery")
                await asyncio.sleep(.02)
        if companions[3].connected:
            raise AssertionError("the fourth original reconnected without its explicit recovery action")
        trace_start = len(evidence["native_dispatches"])
        await stable_hold("three-reconnected-originals-still-wait-for-fourth", scenario)
        forbidden = {int(op) for op in (Opcode.PREPARE, Opcode.START, Opcode.READ_OUT,
            Opcode.ACK_OUT, Opcode.RECEIVE, Opcode.KEEP, Opcode.RELEASE, Opcode.RESUME)}
        if any(row["opcode"] in forbidden for row in evidence["native_dispatches"][trace_start:]):
            raise AssertionError("partial quorum dispatched ordinary progression or released a core")
        if any(task.done() for task in recovery_tasks):
            raise AssertionError("a partial quorum completed recovery")
        for i, original in enumerate(originals_retained):
            c, core = companions[i], cores[i]
            if (core is not original[0] or core.process.pid != original[1] or core.process.returncode is not None
                    or c._bridge is not original[2] or c.battle_incarnation != original[3]
                    or c._live_battle_runtime_id != original[4]):
                raise AssertionError("recovery replaced an original runtime or bridge")
            if (root/f"private-{i}"/"pending-battle.json").read_bytes() != original_intent_bytes[i]:
                raise AssertionError("partial renewal replaced the original intent")
        record("reopened-host-and-sqlite-retain-exact-original-cores-and-intents")
        completed_faults.append(scenario)
        evidence["completed_fault_stages"] = list(completed_faults)
        fault_ready.clear()
        fault_disconnected.clear()
        fault_active = False
        recovery_tasks.append(asyncio.create_task(recoveries[3].run(), name="proof-recovery-3"))
        return recovery_tasks, original_intents, originals_retained

    try:
        for i, identity in enumerate(identities):
            saves[i].write_bytes(originals[i])
            c = Companion(CompanionConfig(rom, manifest_path, identity.player_id, identity.display_name,
                secrets.token_bytes(32), server_port=server.address[1], ipc_port=0,
                server_credential=identity.credential, development_battle_channel=True))
            await c.start()
            companions.append(c)
            live.append(LiveCheckpointCoordinator(c, root/f"private-{i}"))
            observe_dispatch(i, c)
        for i in range(len(sources)): await launch(i)
        await boot()
        initial = await snapshot("01-native-Continue")
        assert all(row["pose"]["activity"] == 1 for row in initial)
        pump = ExecutionPump(cores, companions)
        pump.start()
        inventories, original_flash = [], []
        for i in range(len(sources)):
            receipt = await live[i].enroll()
            assert receipt.metadata["revision"] == 1
            revisions[i] = 1
            cp = store.read_checkpoint(identities[i].player_id, companions[i].session_epoch)
            rosters.append(CanonicalBattler.from_checkpoint(cp, world_id=store.metadata.world_id,
                    build_id=store.build_id, ruleset_id=store.ruleset_id, source_slot=i, mode=3))
            inventories.append(inspect_ownership(inspect_flash(cp.payload, save_profile=OWNERSHIP_PROFILE)))
            flash_path = root/f"before-battle-{i}.flash"
            await cores[i].command(f"D {flash_path}")
            original_flash.append(flash_path.read_bytes())
            controller = EmergencySaveController(companions[i], root/f"private-{i}")
            await controller.arm(1)
            emergency.append(controller)
        record("four-ordinary-Continue-and-canonical-owned-parties", counts=[r.party_count for r in rosters])
        desk = server.battle_desk
        offer = (await companions[0].battle_challenge_rpc("invite_multi",
            teammate=identities[2].player_id,
            opponents=[identities[1].player_id, identities[3].player_id], battle_id=battle_id))["result"]
        assert offer["players"] == [identity.player_id for identity in identities]
        generation = offer["generation"]
        for i in range(1, 4):
            await companions[i].battle_challenge_rpc("accept", battle_id=battle_id,
                generation=generation, fingerprint=offer["fingerprint"])
        offer = (await companions[0].battle_challenge_rpc("status", battle_id=battle_id))["result"]
        held = [await native_state(i) for i in range(4)]
        sessions = [NativeBattleSession(c, root/f"private-{i}") for i, c in enumerate(companions)]
        execution_tasks = [asyncio.create_task(session.run(offer)) for session in sessions]
        original_intents = retained_objects = None
        execution_started = time.monotonic()
        deadline, last_snapshot = execution_started+args.timeout, execution_started
        while time.monotonic() < deadline:
            room = server.battle_execution.rooms.get(battle_id)
            if room is not None and room.route is not None:
                validator = room.route.validator
            if (not fault_active and next_fault() == "mid-battle"
                    and any(block["kind"] == 8 for block in evidence["blocks"])
                    and all(any(row["slot"] == i and row["opcode"] == int(Opcode.START)
                                and row.get("status") == 0 for row in evidence["native_dispatches"]) for i in range(4))):
                if all(row["native_state"] == 5 for row in await retained_state()):
                    fault_ready.set()
            if fault_ready.is_set() and not fault_active:
                execution_tasks, original_intents, retained_objects = await interrupt_and_recover(next_fault())
                # The reconstructed route owns a fresh validator and pending
                # input state. No command or choice is injected to advance it.
                continue
            for i, selection in enumerate(party_input):
                if selection is not None and selection.done():
                    await selection
                    party_input[i] = None
                if party_input[i] is None and validator.pending[i] == 21 and rosters[i].party_count > 1:
                    party_input[i] = asyncio.create_task(drive_party_menu(i))
                if party_input[i] is None:
                    pump.keys[i] = 1 if pump.frames//12 % 2 else 0
            if any(task.done() and (task.cancelled() or task.exception() is not None) for task in execution_tasks):
                await asyncio.gather(*execution_tasks)
            if all(task.done() for task in execution_tasks):
                break
            if time.monotonic()-last_snapshot > 10:
                await snapshot(f"battle-{len(evidence['snapshots']):03}")
                print(json.dumps(dict(progress="authenticated native execution",
                    blocks=len(evidence["blocks"]), frames=pump.frames)), flush=True)
                last_snapshot = time.monotonic()
            await asyncio.sleep(.01)
        else:
            raise AssertionError("authenticated full Multi execution did not close before timeout")
        if completed_faults != fault_stages:
            raise AssertionError(("not every selected production fault boundary completed", fault_stages, completed_faults))
        completions = await asyncio.gather(*execution_tasks)
        pump.keys[:] = [0]*len(sources)
        for i, (completion, original) in enumerate(zip(completions, retained_objects)):
            c = companions[i]
            if (cores[i] is not original[0] or cores[i].process.pid != original[1]
                    or c._bridge is not original[2] or c.battle_incarnation != original[3]
                    or c._live_battle_runtime_id != original[4]):
                raise AssertionError("terminal recovery replaced a retained original")
            verify_recovery_completion(c, root/f"private-{i}", completion, original_intents[i], original[2])
            await emergency[i].retire_after_battle_recovery(completion, original_intents[i], original[2])
            replacement = EmergencySaveController(c, root/f"private-{i}")
            await replacement.arm(1)
            emergency[i] = replacement
            await complete_battle_handoff(c, root/f"private-{i}", completion, original_intents[i], original[2], replacement)
        record("exact-terminal-receipts-retire-old-emergency-and-arm-fresh-save-binding")
        after = [await native_state(i) for i in range(4)]
        for before_state, after_state in zip(held, after):
            for key in ("party_sha256", "party_count", "counter"):
                assert before_state[key] == after_state[key], (key, before_state, after_state)
        for i in range(4):
            flash_path = root/f"after-battle-release-{i}.flash"
            await cores[i].command(f"D {flash_path}")
            assert flash_path.read_bytes() == original_flash[i]
            assert completions[i].canonical_revision == 1
            assert not sessions[i].journal.path.exists()
        selected_slots = []
        for block in evidence["blocks"]:
            data = bytes.fromhex(block["data"])
            if block["kind"] == 8 and data[0] == 1 and data[8] == 33:
                selected_slots.append(dict(owner=block["source"], slot=data[9]))
        if args.require_full_parties:
            assert any(choice["slot"] == 5 for choice in selected_slots), "no actual sixth-slot switch observed"
        state = desk.status(identities[0].player_id, companions[0].session_epoch, battle_id)
        assert state["state"] == "closed"
        record("authenticated-four-player-recovery-exact-party-and-flash-return",
            outcome=state["outcome"], completions=[asdict(value) for value in completions],
            routed_blocks=len(evidence["blocks"]), selected_party_slots=selected_slots,
            execution_seconds=round(time.monotonic()-execution_started, 6))
        await pump.advance(120)
        returned = await snapshot("04-independent-current-map-return")
        for before, after_row in zip(initial, returned):
            assert after_row["pose"]["activity"] == 1
            for key in ("map_group", "map_number", "x", "y"):
                assert before["pose"][key] == after_row["pose"][key]
        for i in range(len(sources)):
            receipt = await live[i].checkpoint(expected_revision=revisions[i])
            assert receipt.metadata["revision"] == revisions[i]+1
            revisions[i] += 1
            cp = store.read_checkpoint(identities[i].player_id, companions[i].session_epoch)
            assert inspect_ownership(inspect_flash(cp.payload, save_profile=OWNERSHIP_PROFILE)).records == inventories[i].records
        record("all-four-current-maps-and-ordinary-native-checkpoints-preserve-owned-inventories")
        await pump.close()
        pump = None
        previous_configs = [c.config for c in companions]
        # Retained recovery connections intentionally fence automatic reconnect.
        # Close them through their public lifecycle before creating entirely
        # fresh authentication for the ordinary cold-start path.
        await asyncio.gather(*(c.close() for c in companions))
        for core in cores: await core.close()
        cores.clear()
        for lease in leases: lease.__exit__(None, None, None)
        leases.clear()
        companions.clear()
        for config in previous_configs:
            companion = Companion(replace(config, token=secrets.token_bytes(32), ipc_port=0, server_port=server.address[1]))
            companions.append(companion)
            await companion.start()
        async with asyncio.timeout(20):
            while not all(c.connected and c._bridge is None for c in companions):
                await asyncio.sleep(.025)
        for i in range(len(sources)):
            recovery = ColdStartRecovery(companions[i], root/f"private-{i}", saves[i])
            context = recovery.open()
            verified = await context.__aenter__()
            cold_contexts.append(context)
            await launch(i, verified.lease)
        await boot()
        fresh = await snapshot("05-fresh-native-Continue")
        assert all(row["pose"]["activity"] == 1 and row["state"] == 0 for row in fresh)
        for i in range(len(sources)):
            cp = store.read_checkpoint(identities[i].player_id, companions[i].session_epoch)
            parsed = inspect_flash(cp.payload, save_profile=OWNERSHIP_PROFILE)
            assert cp.revision == revisions[i]
            assert (await native_state(i))["party_sha256"] == hashlib.sha256(parsed.save_block1[0x238:0x238+600]).hexdigest()
            for key in ("map_group", "map_number", "x", "y"):
                assert fresh[i]["pose"][key] == getattr(parsed.metadata, key)
        store.integrity_check()
        assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in sources] == original_hashes
        record("fresh-Continue-and-original-source-hashes-preserved")
        evidence["passed"] = True
    except BaseException:
        evidence["error"] = traceback.format_exc()
        diagnostics = []
        for core in cores:
            state = {}
            try:
                state["cpu_registers"] = await core.command("G")
                stack = int(state["cpu_registers"].split()[14], 16)
                if 0x03000000 <= stack < 0x03008000:
                    state["cpu_stack_address"] = stack
                    state["cpu_stack"] = (await core.read(stack, 0x03008000-stack)).hex()
            except BaseException:
                pass
            for name in ("gBattleControllerExecFlags", "gBattleMainFunc", "gBattlerControllerFuncs",
                         "gBattlerControllerEndFuncs", "gBattlerAttacker", "gBattlerTarget", "gEffectBattler",
                         "gAbsentBattlerFlags", "gActiveBattler", "gTasks", "gBattleOutcome",
                         "gLinkBattleSendBuffer", "gLinkBattleRecvBuffer", "gMultiplayerBattleFailure",
                         "gSprites", "gHealthboxSpriteIds", "gBattlerSpriteIds", "gBattleSpritesDataPtr"):
                if name not in symbols:
                    continue
                address, size = symbols[name]
                if not (0x02000000 <= address < 0x02040000 or 0x03000000 <= address < 0x03008000) or size > 8192:
                    continue
                try:
                    data = await core.read(address, size)
                    state[name] = data.hex()
                    if name in ("gLinkBattleSendBuffer", "gLinkBattleRecvBuffer") and size == 4:
                        pointer = int.from_bytes(data, "little")
                        if 0x02000000 <= pointer <= 0x0203F000:
                            state[name+"_bytes"] = (await core.read(pointer, 4096)).hex()
                except BaseException:
                    pass
            diagnostics.append(state)
        evidence["failure_diagnostics"] = diagnostics
        try: await snapshot("failure")
        except BaseException: pass
        raise
    finally:
        for task in execution_tasks + recovery_tasks:
            if not task.done(): task.cancel()
        await asyncio.gather(*(execution_tasks + recovery_tasks), return_exceptions=True)
        for task in party_input:
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(t for t in party_input if t is not None), return_exceptions=True)
        if pump is not None: await pump.close()
        await asyncio.gather(*(core.close() for core in all_cores), return_exceptions=True)
        for lease in leases: lease.__exit__(None, None, None)
        for context in reversed(cold_contexts): await context.__aexit__(None, None, None)
        await asyncio.gather(*(c.close() for c in companions), return_exceptions=True)
        await asyncio.gather(*(controller.task for controller in emergency if controller.task is not None),
                             return_exceptions=True)
        await server.close()
        store.close()
        evidence["cores_closed"] = all(c.process.returncode is not None for c in all_cores)
        evidence["original_sources_unchanged"] = [hashlib.sha256(p.read_bytes()).hexdigest() for p in sources] == original_hashes
        evidence["python_sources_unchanged"] = all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
            for path, digest in source_hashes.items())
        if not evidence["cores_closed"] or not evidence["original_sources_unchanged"] or not evidence["python_sources_unchanged"]:
            evidence["passed"] = False
        persist()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rom", "elf", "manifest", "harness", "save-a", "save-b", "save-c", "save-d", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--bridge", type=Path, default=Path(__file__).parents[2]/"bridge/mgba.lua")
    parser.add_argument("--timeout", type=float, default=3600)
    parser.add_argument("--scenario", choices=("pre-bind", "mid-battle", "post-release", "all"), default="mid-battle",
        help="pre-bind withholds the first full BIND after all full intents; it excludes the earlier Players Enter boundary")
    parser.add_argument("--fault-slot", type=int, default=3)
    parser.add_argument("--hold-frames", type=int, default=180,
        help="Frames during each all-four/three-player suspension comparison (minimum 120)")
    parser.add_argument("--require-full-parties", action="store_true",
        help="Require six per trainer and an ordinary sixth-slot switch before accepting the run")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
