"""Private Windows Players-menu 1v1, result, checkpoint and fresh Continue proof.

Uses real LauncherWindow/SessionWorker/LauncherSession with ordinary native
invite, consent and Enter on both original cores. No lifecycle gate, production
method replacement, native authority substitution or emulated-memory writes.
Default move selection and forced party selection reuse the existing native
execution proof's ordinary input policy. A separately pinned Lua appendix reads
the exact ELF's task/party layout and issues bounded joypad presses only.

Requires the same explicitly pinned private inputs as the Windows cancellation
qualifier. Enrollment closes its own bootstrap children. Close ONLY reported
play-session PIDs normally, friend then host, when ready_for_normal_close prints.
Use a 1020-second coroutine envelope and independent 1140-second process watchdog.
Forced cleanup is failure. This is not physical input, 2v2, interrupted recovery,
installed-package, separate-PC, Internet, six-versus-six or game-speed acceptance.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import socket
import struct
import time
import traceback

from emerald_multiplayer import launcher_session as session_module
from emerald_multiplayer.checkpoint_mirror import MirrorLease
from emerald_multiplayer.launcher_gui import LaunchRequest, LauncherWindow, SessionWorker
from emerald_multiplayer.launcher_session import GameInstallation
from emerald_multiplayer.launcher_setup import create_world, export_friend_invitation, host_enrollment
from emerald_multiplayer.player_runtime import RuntimeBundle
from qualify_admission_cleanup import SYMBOLS as MENU_SYMBOLS, Probe, on_worker, require
from qualify_admission_cleanup import append_input_probe as append_menu_probe
from qualify_launcher_session import checked_log, inspect_closed_head, output_event
from qualify_live_runtime import field_ready, lease_is_owned, party, proof_bundle, sha


SYMBOLS = dict(MENU_SYMBOLS, gTasks=640, gPartyMenu=20)
PARTY_TASKS = ("Task_HandleChooseMonInput", "Task_HandleSelectionMenuInput", "Task_PrintAndWaitForText")
BATTLE_HEADER = struct.Struct("<IIB")
BATTLE_SNAPSHOT_SIZE = BATTLE_HEADER.size + 640 + 20 + 600


def decode_battle_snapshot(raw):
    require(len(raw) == BATTLE_SNAPSHOT_SIZE, "battle diagnostic length changed")
    frame, state, count = BATTLE_HEADER.unpack_from(raw)
    require(count <= 6 and state <= 10, "battle diagnostic enum/count changed")
    tasks = raw[BATTLE_HEADER.size:BATTLE_HEADER.size+640]
    active = frozenset(int.from_bytes(tasks[o:o+4], "little") & ~1
        for o in range(0, 640, 40) if tasks[o+4])
    cursor = raw[BATTLE_HEADER.size+640+9]
    return dict(frame=frame, state=state, count=count, active=active,
                cursor=cursor, party_sha256=hashlib.sha256(raw[-600:]).hexdigest())


def party_action(pending, state, symbols):
    """Read-only native phase chooses keys, never a controller reply or winner."""
    if state["state"] != 5:
        return "wait"
    if pending != 21:
        return "confirm"
    active = state["active"]
    if symbols["Task_PrintAndWaitForText"][0] & ~1 in active:
        return "dismiss"
    if symbols["Task_HandleSelectionMenuInput"][0] & ~1 in active:
        return "confirm"
    if symbols["Task_HandleChooseMonInput"][0] & ~1 in active:
        return "next-party"
    return "wait"


def append_input_probe(bundle, bridge, output, symbols, manifest):
    bundle = append_menu_probe(bundle, bridge, output, symbols)
    path = bundle.directory / "mgba.lua"
    # Separate bounded file keeps the proven menu/input framing unchanged.
    appendix = f'''
do
local path={json.dumps(output.as_posix(), ensure_ascii=True)}.."/input-"..cfg.port..".battle"
callbacks:add("frame",function()
  if emu:currentFrame()<2400 or emu:currentFrame()%6~=0 then return end
  local raw=string.pack("<I4I4I1",emu:currentFrame(),emu:read32({manifest['battle_mailbox_address']+12}),
    emu:read8({manifest['debug_party_counts_address']}))
    ..emu:readRange({symbols['gTasks'][0]},640)..emu:readRange({symbols['gPartyMenu'][0]},20)
    ..emu:readRange({manifest['debug_parties_address']},600)
  local f=io.open(path,"wb");if f then f:write(raw);f:close() end
end)
end
'''
    path.write_bytes(path.read_bytes() + appendix.encode("utf-8"))
    metadata = bundle.directory / "runtime.json"
    value = json.loads(metadata.read_text())
    value["files"]["mgba.lua"] = sha(path)
    metadata.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    return RuntimeBundle(bundle.directory, sha(metadata))


class BattleProbe(Probe):
    async def battle(self, *, after=-1, timeout=15):
        async with asyncio.timeout(timeout):
            while True:
                try:
                    state = decode_battle_snapshot(self.base.with_suffix(".battle").read_bytes())
                    if state["frame"] > after:
                        return state
                except (OSError, AssertionError):
                    pass  # Concurrent writer may temporarily expose a partial file.
                await asyncio.sleep(.03)


async def drive_battle_input(probe, view, symbols, stop):
    """One serial key owner per original core; every press includes release."""
    while not stop.is_set():
        room = await view()
        if room["state"] in ("closed", "aborted", "recovery_required"):
            return
        state = await probe.battle()
        action = party_action(room["pending"], state, symbols) if room["state"] == "executing" else "wait"
        if stop.is_set():
            return
        if action == "next-party":
            pressed = await probe.press(128, frames=12, release=18)
            moved = await probe.battle(after=pressed["frame"]-1)
            current = await view()
            if (not stop.is_set() and current["state"] == "executing" and current["pending"] == 21
                    and moved["state"] == 5 and symbols["Task_HandleChooseMonInput"][0] & ~1 in moved["active"]
                    and moved["cursor"] != state["cursor"] and 0 <= moved["cursor"] < moved["count"]):
                await probe.press(1, frames=12, release=18)
        elif action != "wait":
            await probe.press(2 if action == "dismiss" else 1, frames=12, release=30 if action == "dismiss" else 18)
        else:
            await asyncio.sleep(.05)


async def native_menu_match(current, probes, games, host, symbols, record):
    """Both Enter operations remain entirely owned by production MenuSession."""
    originals = []
    async def identity(s):
        c = s._companion
        return (s._game, s._runtime, c._bridge, c._bridge.incarnation, c._live_battle_runtime_id)
    before = [await probe.battle() for probe in probes]
    await probes[0].open_players()
    await probes[0].choose("Battle Friend")
    await probes[0].choose("Challenge 1v1")
    await probes[1].open_players()
    await probes[1].choose("Pending challenge")
    await probes[1].choose("Accept challenge")
    async with asyncio.timeout(20):
        while not all(screen.admission_action for _, screen in await asyncio.gather(*(p.ready() for p in probes))):
            await asyncio.sleep(.05)
    async def descriptor(s):
        values = s._companion._bridge.menu_session.menu._battles
        require(len(values) == 1 and values[0]["state"] == "accepted", "expected exact accepted native challenge")
        return json.loads(json.dumps(values[0]))
    challenge = await on_worker(current[0], descriptor)
    require(challenge == await on_worker(current[1], descriptor), "native consent descriptors differ")
    # The production invitation/acceptance paths allocate each runtime ID.
    # Capture these actual identities only after both original consents exist.
    for worker in current:
        originals.append(await on_worker(worker, identity))
    battle_id = challenge["battle_id"]
    slots = [challenge["players"].index(account.player_id) for account in host.accounts]
    blocks = []
    async def observe(s):
        service = s._server.battle_execution
        require(service.observer is None, "a previous proof observer exists")
        # This existing optional observation hook receives already validated
        # immutable values; it changes no production command or return value.
        service.observer = lambda block: blocks.append(dict(block))
    await on_worker(current[0], observe)
    await asyncio.gather(*(p.choose("Enter battle", wait=False) for p in probes))
    record("both-native-Enter-selected", battle_id=battle_id, original_pids=[g.process.pid for g in games])
    async def view(slot):
        async def read(s):
            room = s._server.battle_execution.rooms.get(battle_id)
            if room is None:
                return dict(state="waiting", pending=None)
            return dict(state=room.state, pending=None if room.route is None else room.route.validator.pending[slot])
        return await on_worker(current[0], read)
    stop = asyncio.Event()
    drivers = [asyncio.create_task(drive_battle_input(p, lambda slot=slot: view(slot), symbols, stop))
               for p, slot in zip(probes, slots)]
    started = time.monotonic()
    async def finished(s):
        # Normal terminal adoption temporarily fences saving while its original
        # menu task retires the old saver and arms the successor. That flag is
        # a failure only after the operation owner has relinquished the task.
        if (s._save_failed and s._interaction is None
                or s._game is None or s._game.process.returncode is not None):
            raise AssertionError("launcher retained a battle failure or lost its original game")
        return s.status.code == "battle_finished" and s.can_save and s._interaction is None
    try:
        async with asyncio.timeout(480):
            report_at = 0
            while True:
                for driver in drivers:
                    if driver.done():
                        await driver
                if all(await asyncio.gather(*(on_worker(w, finished) for w in current))):
                    break
                if time.monotonic() >= report_at:
                    record("native-1v1-progress", blocks=len(blocks), elapsed_seconds=round(time.monotonic()-started, 3))
                    report_at = time.monotonic()+20
                await asyncio.sleep(.05)
    finally:
        stop.set()
        # Never overlap or abandon a key command. A hung diagnostic is bounded
        # by its own timeout and then the qualifier's outer failure cleanup.
        await asyncio.gather(*drivers)
    async def terminal(s):
        c = s._companion
        require(s._battle_retained is None and s._battle_handoff_successor is None, "launcher still retains battle ownership")
        require(s._emergency.result.state == "armed" and c._emergency_controller is s._emergency, "fresh terminal saver is not armed")
        require(not any((s.profile_directory / name).exists() for name in
            ("pending-battle.json", "pending-battle-admission.json", "pending-export.json", "pending-emergency.json")), "terminal recovery intent remains pending")
        history = (await c.battle_challenge_rpc("history"))["result"]
        values = [v for v in history if v["battle_id"] == battle_id]
        require(len(values) == 1 and values[0]["mode"] == 2 and values[0]["players"] == challenge["players"], "durable native singles result missing")
        return values[0], dict(status=asdict(s.status), handoff_sha256=sha(s.profile_directory / (battle_id + ".battle-handoff.json")))
    results = []
    for slot, worker in enumerate(current):
        after = await on_worker(worker, identity)
        require(all(after[n] is originals[slot][n] for n in range(3)) and after[3:] == originals[slot][3:], "battle replaced the original core, bridge or native identity")
        require(games[slot].process.returncode is None, "original native process exited")
        result, details = await on_worker(worker, terminal)
        results.append(result)
        row = await probes[slot].snapshot(lambda r: r["hold"] == 0)
        state = await probes[slot].battle(after=row["frame"]-1)
        require(state["count"] == before[slot]["count"] and state["party_sha256"] == before[slot]["party_sha256"], "original full personal party was not restored")
        record("launcher-native-battle-completed", slot=slot, pid=games[slot].process.pid, **details)
    require(results[0] == results[1], "players disagree on durable result")
    selected = [dict(owner=b["source"], slot=bytes.fromhex(b["data"])[9]) for b in blocks
        if b["kind"] == 8 and len(bytes.fromhex(b["data"])) > 9 and bytes.fromhex(b["data"])[0] == 1
        and bytes.fromhex(b["data"])[8] == 33]
    record("real-native-1v1-result", result=results[0], routed_blocks=len(blocks), selected_party_slots=selected,
           elapsed_seconds=round(time.monotonic()-started, 3))
    for index, probe in enumerate(probes):
        result = results[index]
        await probe.open_players()
        await probe.choose("Challenges")
        await probe.choose("Recent battle results")
        outcome = "Draw" if result["outcome"] == 3 else "Win" if result["outcome"] == 1+slots[index]%2 else "Loss"
        _, screen = await probe.choose(f"1v1 {outcome} #{result['sequence']}")
        require(screen.title == "Battle result" and screen.status ==
            ("Draw" if result["outcome"] == 3 else f"Team {result['outcome']} won"), "native history screen differs from durable outcome")
        record("native-result-screen-matches", slot=index, title=screen.title, status=screen.status)
        async with asyncio.timeout(10):
            while (await probe.snapshot())["active"]:
                await probe.press(2)
    return results[0]

async def run(args):
    require(os.name == "nt", "this qualifier requires the existing Windows runtime")
    require(math.isfinite(args.timeout) and 180 <= args.timeout <= 900, "timeout must be 180..900 seconds")
    inputs = {name: getattr(args, name).resolve() for name in ("rom", "manifest", "elf", "symbols", "bridge", "source_a", "source_b")}
    hashes = {name: sha(path) for name, path in inputs.items()}
    require(hashes == {name: getattr(args, name + "_sha256") for name in inputs}, "explicit input pins differ")
    manifest = json.loads(inputs["manifest"].read_text())
    require(manifest["elf_sha256"] == hashes["elf"], "ELF does not match the manifest")
    required = dict(menu_abi_version=2, battle_abi_version=3, battle_resume_abi_version=1,
        emergency_save_abi_version=2, battle_execution_abi_version=1, battle_admission_cleanup_abi_version=1)
    require(all(manifest.get(k) == v for k, v in required.items()), "combined cleanup-capable game required")
    symbols = {}
    for line in inputs["symbols"].read_text().splitlines():
        fields = line.split()
        if len(fields) == 4:
            symbols[fields[3]] = (int(fields[0], 16), int(fields[1], 16))
    require(all(symbols.get(k, (0, 0))[1] == v for k, v in SYMBOLS.items()), "diagnostic symbol sizes differ")
    for name in PARTY_TASKS:
        address, size = symbols.get(name, (0, 0))
        require(size > 0 and 0x08000000 <= (address & ~1)
                and (address & ~1) + size <= 0x08000000 + manifest["rom_size"],
                "party input task is outside the pinned ROM")
    action_size = symbols.get("sCurrentStartMenuActions", (0, 0))[1]
    require(3 <= action_size <= 64, "bounded start menu actions required")
    for name in (*SYMBOLS, "sCurrentStartMenuActions"):
        address, size = symbols[name]
        require(0x02000000 <= address and address + size <= 0x02040000 or
                0x03000000 <= address and address + size <= 0x03008000, "diagnostic is outside native RAM")
    parent = RuntimeBundle(args.bundle.resolve(), args.bundle_sha256)
    GameInstallation(inputs["rom"], inputs["manifest"], hashes["rom"], hashes["manifest"], parent).verify()
    output = args.output.resolve()
    require("PokemonPrivate" in output.parts, "use a new private PokemonPrivate output directory")
    output.mkdir(parents=True, exist_ok=False)
    for name, path in inputs.items():
        shutil.copyfile(path, output / ("input-" + name + path.suffix))
    source_hashes = {}
    for path in sorted(Path(session_module.__file__).parent.glob("*.py")) + sorted(Path(__file__).parent.glob("*.py")):
        raw = path.read_bytes()
        source_hashes[str(path)] = hashlib.sha256(raw).hexdigest()
        target = output / "source" / path.parent.name / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    # Supply current production Lua as the helper's parent bridge through a
    # new minimal runtime copy; executable/DLL originals remain pinned.
    staging = output / "base-runtime"
    staging.mkdir()
    executable, _ = parent.verify()
    for name in (executable.name, "SDL2.dll", "libwinpthread-1.dll"):
        shutil.copyfile(parent.directory / name, staging / name)
    bridge = inputs["bridge"].read_bytes().decode("utf-8")
    (staging / "mgba.lua").write_bytes(bridge.encode("utf-8"))
    value = dict(format="emerald-windows-runtime-v1", executable=executable.name, bridge="mgba.lua",
                 files={p.name: sha(p) for p in staging.iterdir()})
    (staging / "runtime.json").write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    bundle = proof_bundle(RuntimeBundle(staging, sha(staging / "runtime.json")), output, manifest)
    bundle = append_input_probe(bundle, bridge, output, symbols, manifest)
    if manifest.get("trade_replay_abi_version") == 1:
        # Current ordinary worlds retain the existing trade-history startup
        # barrier even when this proof only battles. Copy the exact already
        # pinned worker; do not disable a production feature to admit the run.
        worker_name = "emerald-trade-replay.exe"
        parent_metadata = json.loads((parent.directory / "runtime.json").read_text())
        require(worker_name in parent_metadata["files"], "parent runtime needs its pinned replay worker")
        shutil.copyfile(parent.directory / worker_name, bundle.directory / worker_name)
        require(sha(bundle.directory / worker_name) == parent_metadata["files"][worker_name],
                "copied replay worker changed")
        metadata = bundle.directory / "runtime.json"
        value = json.loads(metadata.read_text())
        value["files"][worker_name] = parent_metadata["files"][worker_name]
        metadata.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
        bundle = RuntimeBundle(bundle.directory, sha(metadata))
    installation = GameInstallation(output / "input-rom.gba", output / "input-manifest.json",
                                    hashes["rom"], hashes["manifest"], bundle)
    evidence = dict(passed=False, scope=__doc__, inputs=hashes, source_hashes=source_hashes,
        parent_runtime_pin=args.bundle_sha256, proof_runtime_pin=bundle.manifest_sha256,
        checks=[], statuses=[], forced_children=[], cleanup_errors=[],
        physical_input=False, physical_gui_click=False, timed_autosave=False,
        trade_effect_policy=getattr(args, "trade_effect_policy", None),
        fault_recovery=False, separate_pc=False, internet=False)
    def persist():
        (output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    def record(name, **fields):
        evidence["checks"].append(dict(name=name, **fields))
        persist()
        output_event(check=name, **fields)
    workers, children, windows, roots = [], [], [], []
    enrollment_pids = set()
    completed = False
    private = output / "private"

    async def poll_until(predicate, timeout=30):
        async with asyncio.timeout(timeout):
            while not predicate():
                await asyncio.sleep(.05)

    async def gui_pump():
        while True:
            for root in roots:
                root.update()
            await asyncio.sleep(.02)

    pump = asyncio.create_task(gui_pump())
    try:
        async with asyncio.timeout(args.timeout):
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            host = create_world(installation, private, player_names=("Battle Host", "Battle Friend"),
                endpoint="127.0.0.1", port=port, trade_effect_policy=getattr(args, "trade_effect_policy", None))
            expected = []
            for slot, name in enumerate(("source_a", "source_b")):
                async with host_enrollment(installation, private, world_directory=host.directory, slot=slot, source_path=inputs[name]) as runtime:
                    children.append((runtime._game.process, asyncio.get_running_loop()))
                    record("enrollment-child", slot=slot, pid=runtime._game.process.pid)
                    await field_ready(runtime.companion, runtime._game)
                    enrolled = await runtime.enroll()
                    require(enrolled.metadata["revision"] == 1, "enrollment revision differs")
                    require(runtime._game.process.returncode is not None,
                            "production enrollment did not close its bootstrap child")
                    enrollment_pids.add(runtime._game.process.pid)
                    record("production-enrollment-closed-bootstrap", slot=slot,
                           pid=runtime._game.process.pid,
                           returncode=runtime._game.process.returncode)
                with MirrorLease(runtime.save_path):
                    pass
                with host.open_store() as store:
                    expected.append(party(inspect_closed_head(store, host.accounts[slot].player_id)))
            require([value["count"] for value in expected] == [2, 1],
                    "this bounded qualifier requires the pinned ordinary two/one-member parties")
            invitation = output / "friend-invitation.json"
            export_friend_invitation(installation, host.directory, 1, invitation)
            saved = []
            for phase in ("battle-and-save", "fresh-Continue"):
                current, games, probes, mirrors = [], [], [], []
                for slot, mode in enumerate(("host", "join")):
                    worker = SessionWorker(installation, private)
                    workers.append(worker)
                    current.append(worker)
                    import tkinter as tk
                    root = tk.Tk() if not roots else tk.Toplevel(roots[0])
                    window = LauncherWindow(root, worker, version="Private 1v1 qualification")
                    root.title(f"Battle proof {phase} {mode}")
                    roots.append(root)
                    windows.append(window)
                    selection = host.directory / "world.json" if slot == 0 else invitation
                    require(worker.start(LaunchRequest(mode, selection)), "real GUI worker did not start")
                    await poll_until(lambda: worker._active_session is not None or not worker.busy)
                    require(worker._active_session is not None, "launcher worker failed before play")
                    async def prepare(s):
                        async with asyncio.timeout(30):
                            while s._game is None:
                                await asyncio.sleep(.03)
                        # Register the child before any subsequent inspection
                        # can fail, so the qualifier always owns its cleanup.
                        children.append((s._game.process, worker._loop))
                        await s.set_autosave_enabled(False)
                        return s._game, s._companion.ipc_address[1], s.profile_directory / "character.sav"
                    game, ipc, mirror = await on_worker(worker, prepare)
                    games.append(game)
                    mirrors.append(mirror)
                    probes.append(BattleProbe(output, ipc, action_size, record))
                    async def ready(s):
                        await field_ready(s._companion, s._game)
                        async with asyncio.timeout(20):
                            while s._emergency is None or s._emergency.result.state != "armed":
                                await asyncio.sleep(.03)
                        lease_is_owned(s.profile_directory / "character.sav")
                        require(s._companion._remote_writer.get_extra_info("ssl_object") is not None, "TLS missing")
                        return s.status.revision
                    require(await on_worker(worker, ready) == (1 if phase == "battle-and-save" else 2), "startup revision differs")
                record("actual-launcher-workers-ready", phase=phase, pids=[g.process.pid for g in games])
                if phase == "battle-and-save":
                    await native_menu_match(current, probes, games, host, symbols, record)
                    for slot, worker in enumerate(current):
                        async def save(s):
                            require(await s.save(), "manual save did not finish")
                            require(s.status.revision == 2, "manual save revision differs")
                        await on_worker(worker, save)
                async def heads(s):
                    rows = []
                    for slot, account in enumerate(host.accounts):
                        head = inspect_closed_head(s._store, account.player_id)
                        require(head.revision == 2 and party(head) == expected[slot], "canonical party or revision changed")
                        rows.append((head.revision, head.sha256, head.payload))
                    s._store.integrity_check()
                    return rows
                actual = await on_worker(current[0], heads)
                if phase == "battle-and-save":
                    saved = actual
                else:
                    require(actual == saved, "fresh Continue changed canonical checkpoints")
                    require(all(g.startup.mirror.sha256 == actual[n][1] for n, g in enumerate(games)), "fresh native mirror differs")
                record("ready_for_normal_close", phase=phase, friend_pid=games[1].process.pid, host_pid=games[0].process.pid)
                await poll_until(lambda: not any(w.busy for w in current), 120)
                require([g.process.returncode for g in games] == [0, 0], "ordinary SDL exit failed")
                for slot, game in enumerate(games):
                    checked_log(game, expected[slot])
                    with MirrorLease(mirrors[slot]):
                        pass
                record("normal-close-and-native-party-verified", phase=phase, exit_codes=[0, 0])
            with host.open_store() as store:
                store.integrity_check()
                require([(h.revision, h.sha256, h.payload) for h in
                    (inspect_closed_head(store, a.player_id) for a in host.accounts)] == saved, "closed final heads differ")
            completed = True
    except BaseException as error:
        evidence["error"] = repr(error)
        evidence["traceback"] = traceback.format_exc()
        raise
    finally:
        # The normal path has no running children. Failure cleanup stops only
        # explicitly tracked test-owned processes and cannot earn acceptance.
        for child, owner_loop in children:
            if child.returncode is None:
                evidence["forced_children"].append(child.pid)
                async def stop(process=child):
                    if process.returncode is None:
                        process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), 5)
                    except TimeoutError:
                        process.kill()
                        await asyncio.wait_for(process.wait(), 5)
                try:
                    if owner_loop is asyncio.get_running_loop():
                        await stop()
                    elif owner_loop.is_running():
                        await asyncio.wait_for(asyncio.wrap_future(asyncio.run_coroutine_threadsafe(stop(), owner_loop)), 12)
                    else:
                        raise RuntimeError("test child owner loop stopped before child exit")
                except BaseException as error:
                    evidence["cleanup_errors"].append(repr(error))
        try:
            await poll_until(lambda: not any(w.busy for w in workers), 15)
        except BaseException as error:
            evidence["cleanup_errors"].append(repr(error))
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)
        for window in reversed(windows):
            try:
                window._destroy()
            except Exception as error:
                evidence["cleanup_errors"].append(repr(error))
        evidence["child_exits"] = [dict(pid=p.pid, returncode=p.returncode) for p, _ in children]
        evidence["automatically_closed_enrollment_pids"] = sorted(enrollment_pids)
        try:
            evidence["inputs_unchanged"] = all(sha(p) == hashes[n] for n, p in inputs.items())
            evidence["sources_unchanged"] = all(sha(Path(p)) == digest for p, digest in source_hashes.items())
            parent.verify()
            bundle.verify()
        except BaseException as error:
            evidence["cleanup_errors"].append(repr(error))
        evidence["passed"] = (completed and evidence.get("inputs_unchanged") and evidence.get("sources_unchanged")
            and not evidence["forced_children"] and not evidence["cleanup_errors"]
            and all(p.returncode is not None and (p.pid in enrollment_pids or p.returncode == 0)
                    for p, _ in children) and not any(w.busy for w in workers))
        persist()
        output_event(passed=evidence["passed"], child_exits=evidence["child_exits"])
    require(evidence["passed"], "qualification failed; preserved private evidence records its scope")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rom", "manifest", "elf", "symbols", "bridge", "bundle", "source-a", "source-b"):
        parser.add_argument("--" + name, type=Path, required=True)
        parser.add_argument("--" + name + "-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--trade-effect-policy", choices=("gen6-absent-geography-refresh-v1", "gen6-stable-world-region-v1"))
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
