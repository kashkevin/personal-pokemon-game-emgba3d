"""Four actual cores using the authenticated native battle execution service.

The production host executor routes authenticated participants' typed blocks
and the production client journals own every mailbox mutation. This is not the
player challenge UI or an Internet proof. Gameplay uses ordinary joypad
inputs. Core memory and Flash access below is read-only diagnostic evidence.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import secrets
import time
import traceback
from uuid import uuid4

from configure_bridge import configure
from live_checkpoint_proof import LockedCore
from battle_channel_proof import DiagnosticPump
from emerald_multiplayer.battle_controller import ControllerValidator, read_string_lengths
from emerald_multiplayer.battle_roster import CanonicalBattler
from emerald_multiplayer.battle_session import NativeBattleSession
from emerald_multiplayer.checkpoint_mirror import MirrorLease
from emerald_multiplayer.cold_start import ColdStartRecovery
from emerald_multiplayer.companion import Companion, CompanionConfig, verify_rom_manifest
from emerald_multiplayer.flash import inspect_flash
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator
from emerald_multiplayer.mailbox import inspect_mailbox
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, inspect_ownership
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.trade_storage import TradeCheckpointStore


class ExecutionPump(DiagnosticPump):
    async def _run(self):
        # Approximate the ordinary 60fps desktop runtime. Durable host/client
        # journals may need more wall time than the older in-memory proof.
        while True:
            started = time.monotonic()
            await asyncio.gather(*(core.command(f"F {key:x} 6")
                for core, key in zip(self.cores, self.keys)))
            self.frames += 6
            await asyncio.sleep(max(.001, .1 - (time.monotonic() - started)))


async def run(args):
    root = args.output.resolve()
    if "/multiplayer-proof/" not in str(root)+"/" or root.exists():
        raise ValueError("choose a new private multiplayer-proof output directory")
    _, manifest = verify_rom_manifest(args.rom, args.manifest)
    if manifest.get("battle_abi_version") != 3:
        raise ValueError("native full Multi requires the exact ABI3 development ROM")
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
    evidence = dict(scope="four actual native full-party Multi cores using authenticated consent/execution RPC, host-owned routing and persistent client command journals; no native menu, interrupted-battle recovery, Windows or Internet claim",
        engine_commit=manifest["engine_commit"], rom_sha256=manifest["rom_sha256"],
        elf_sha256=manifest["elf_sha256"], controller_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        bridge_sha256=hashlib.sha256(bridge_source.encode()).hexdigest(),
        harness_sha256=hashlib.sha256(args.harness.read_bytes()).hexdigest(),
        party_counts=[m.party_count for m in source_meta],
        require_full_parties=args.require_full_parties,
        sources=[dict(path=str(p), sha256=h, trainer_id=m.trainer_id)
                 for p, h, m in zip(sources, original_hashes, source_meta)],
        checks=[], snapshots=[], commands=[], blocks=[], passed=False, cores_closed=False)

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
                "gTasks": 16*40, "gPartyMenu": 20}
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
    server = WorldServer(ServerConfig(manifest["rom_sha256"], manifest["ruleset_id"],
        heartbeat_interval=.2, idle_timeout=12), store=store, development_trades=True, development_battles=True)
    server.enable_battle_execution(read_string_lengths(rom, table_address=symbols["gBattleStringsTable"][0]), root/"execution-host")
    execution_started = time.monotonic()
    server.battle_execution.observer = lambda block: evidence["blocks"].append(
        dict(block, frame=pump.frames, elapsed_seconds=round(time.monotonic()-execution_started, 6)))
    original_command = server.battle_execution._command
    async def timed_command(room, actor, command):
        started = time.monotonic()
        try:
            return await original_command(room, actor, command)
        finally:
            evidence["commands"].append(dict(source=room.battle.players.index(actor),
                opcode=int(command.opcode), seconds=round(time.monotonic()-started, 6)))
    server.battle_execution._command = timed_command
    await server.start(port=0)
    saves = [root/f"client-{name}.sav" for name in "abcd"[:len(sources)]]
    companions, live, cores, all_cores, leases, rosters = [], [], [], [], [], []
    pump = None
    battle_id, generation, rng = str(uuid4()), None, None
    desk = None
    cold_contexts, execution_tasks = [], []
    party_input = [None]*4
    revisions = [0]*len(sources)

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
        # A pending six-frame pump batch may already hold the previous keys;
        # twelve frames guarantees at least one batch samples this press.
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

    try:
        for i, identity in enumerate(identities):
            saves[i].write_bytes(originals[i])
            c = Companion(CompanionConfig(rom, manifest_path, identity.player_id, identity.display_name,
                secrets.token_bytes(32), server_port=server.address[1], ipc_port=0,
                server_credential=identity.credential, development_battle_channel=True))
            await c.start()
            companions.append(c)
            live.append(LiveCheckpointCoordinator(c, root/f"private-{i}"))
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
        execution_started = time.monotonic()
        deadline, last_snapshot = execution_started+args.timeout, execution_started
        while time.monotonic() < deadline:
            room = server.battle_execution.rooms.get(battle_id)
            if room is not None and room.route is not None:
                validator = room.route.validator
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
        completions = await asyncio.gather(*execution_tasks)
        pump.keys[:] = [0]*len(sources)
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
        record("authenticated-four-player-execution-exact-party-and-flash-return",
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
        for core in cores: await core.close()
        cores.clear()
        for lease in leases: lease.__exit__(None, None, None)
        leases.clear()
        for _ in range(200):
            if all(c.connected and c._bridge is None for c in companions): break
            await asyncio.sleep(.025)
        else: raise AssertionError("closed cores failed to detach and reauthenticate")
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
        for task in execution_tasks:
            if not task.done(): task.cancel()
        await asyncio.gather(*execution_tasks, return_exceptions=True)
        for task in party_input:
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(t for t in party_input if t is not None), return_exceptions=True)
        if pump is not None: await pump.close()
        await asyncio.gather(*(core.close() for core in all_cores), return_exceptions=True)
        for lease in leases: lease.__exit__(None, None, None)
        for context in reversed(cold_contexts): await context.__aexit__(None, None, None)
        await asyncio.gather(*(c.close() for c in companions), return_exceptions=True)
        await server.close()
        store.close()
        evidence["cores_closed"] = all(c.process.returncode is not None for c in all_cores)
        evidence["original_sources_unchanged"] = [hashlib.sha256(p.read_bytes()).hexdigest() for p in sources] == original_hashes
        if not evidence["cores_closed"] or not evidence["original_sources_unchanged"]:
            evidence["passed"] = False
        persist()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rom", "elf", "manifest", "harness", "save-a", "save-b", "save-c", "save-d", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--bridge", type=Path, default=Path(__file__).parents[2]/"bridge/mgba.lua")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--require-full-parties", action="store_true",
        help="Require six per trainer and an ordinary sixth-slot switch before accepting the run")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
