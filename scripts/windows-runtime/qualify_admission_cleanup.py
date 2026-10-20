"""Private Windows LauncherSession/GUI admission cancellation qualification.

Requires a fresh private output, explicitly pinned cleanup-capable ROM/ELF,
an `arm-none-eabi-nm -S` dump of that ELF, two unassigned saves and a runtime.
The parent runtime is preserved; a separately pinned proof bridge appends only
ordinary joypad input and read-only diagnostics. The existing production bridge
is supplied separately because an older runtime may predate cleanup support.

Real SessionWorker/LauncherWindow instances drive unchanged LauncherSessions.
Only the initiator's existing checkpoint lock is temporarily held: native Enter
publishes its original intent normally, while production preparation waits at
its usual lock. The gate releases only after real host revocation and drainage
of that exact menu task. No production method or native receipt is replaced.
The actual enabled Tk cancellation button is invoked programmatically. This is
not physical keyboard/click, packaged installer, fault/recovery, or LAN proof.

Enrollment closes its bootstrap child through its normal production contract.
Close ONLY printed play-session PIDs normally at ready_for_normal_close, friend
first, then host. An outer watchdog is still required for interpreter or GUI
failure. Forced qualification cleanup is recorded as failure.
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
import traceback

from emerald_multiplayer import launcher_session as session_module
from emerald_multiplayer.battle_admission_intent import FILENAME, read_admission_intent
from emerald_multiplayer.checkpoint_mirror import MirrorLease
from emerald_multiplayer.launcher_gui import LaunchRequest, LauncherWindow, SessionWorker
from emerald_multiplayer.launcher_session import GameInstallation
from emerald_multiplayer.launcher_setup import create_world, export_friend_invitation, host_enrollment
from emerald_multiplayer.menu_mailbox import unpack_screen
from emerald_multiplayer.player_runtime import RuntimeBundle
from qualify_launcher_session import checked_log, inspect_closed_head, output_event
from qualify_live_runtime import field_ready, lease_is_owned, party, proof_bundle, sha


SYMBOLS = dict(gMultiplayerBattleHoldFlags=4, sMultiplayerMenuActive=1,
    sMultiplayerMenuWaiting=1, sMultiplayerMenuCursor=1, sMultiplayerMenuScreen=240,
    sNumStartMenuActions=1, sStartMenuCursorPos=1)
HEADER = struct.Struct("<IIBBBBBI")


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def append_input_probe(bundle, bridge, output, symbols):
    """Local proof files grant keys only; diagnostics never write emulated RAM."""
    path = bundle.directory / "mgba.lua"
    # proof_bundle's suffix is its already qualified ordinary Continue plan.
    old = path.read_bytes().decode("utf-8")
    parent_prefix = old[:old.index("\nlocal plan={{0,1000}")]
    require(parent_prefix == bridge, "proof helper changed its production bridge prefix")
    root = json.dumps(output.as_posix(), ensure_ascii=True)
    addr = {name: value[0] for name, value in symbols.items()}
    appendix = '''
do
local base=ROOT.."/input-"..cfg.port
local seen,ack,key,left,release=0,0,0,0,0
local function hex(s) return (s:gsub(".",function(c)return string.format("%02x",string.byte(c))end)) end
callbacks:add("frame",function()
  if emu:currentFrame()<2400 then return end
  if left>0 then
    emu:setKeys(key);left=left-1
    if left==0 then emu:setKeys(0) end
  elseif release>0 then
    emu:setKeys(0);release=release-1
    if release==0 then ack=seen end
  else
    local f=io.open(base..".keys","rb")
    if f then
      local raw=f:read(96);f:close()
      local id,k,n,r=raw:match("^(%d+) (%d+) (%d+) (%d+)\\n$")
      id,k,n,r=tonumber(id),tonumber(k),tonumber(n),tonumber(r)
      if id and id==seen+1 and k<=1023 and n>=1 and n<=120 and r>=1 and r<=180 then
        seen,key,left,release=id,k,n,r
      end
    end
  end
  if emu:currentFrame()%6==0 then
    local raw=string.pack("<I4I4I1I1I1I1I1I4",emu:currentFrame(),ack,
      emu:read8(ACTIVE),emu:read8(WAITING),emu:read8(CURSOR),
      emu:read8(COUNT),emu:read8(STARTCURSOR),emu:read32(HOLD))
      ..emu:readRange(ACTIONS,ACTIONSIZE)..emu:readRange(SCREEN,240)
    local f=io.open(base..".read","wb")
    if f then f:write(raw);f:close() end
  end
end)
end
'''
    substitutions = dict(ROOT=root, ACTIVE=addr["sMultiplayerMenuActive"],
        WAITING=addr["sMultiplayerMenuWaiting"], CURSOR=addr["sMultiplayerMenuCursor"],
        COUNT=addr["sNumStartMenuActions"], STARTCURSOR=addr["sStartMenuCursorPos"],
        HOLD=addr["gMultiplayerBattleHoldFlags"], ACTIONS=addr["sCurrentStartMenuActions"],
        ACTIONSIZE=symbols["sCurrentStartMenuActions"][1], SCREEN=addr["sMultiplayerMenuScreen"])
    # Long names first, so ACTIONS never replaces part of ACTIONSIZE.
    for name in sorted(substitutions, key=len, reverse=True):
        appendix = appendix.replace(name, str(substitutions[name]))
    path.write_bytes((old + appendix).encode("utf-8"))
    manifest_path = bundle.directory / "runtime.json"
    value = json.loads(manifest_path.read_text())
    value["files"]["mgba.lua"] = sha(path)
    manifest_path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    return RuntimeBundle(bundle.directory, sha(manifest_path))


class Probe:
    def __init__(self, output, port, action_size, record):
        self.base, self.action_size = output / f"input-{port}", action_size
        self.sequence, self.record = 0, record

    def read(self):
        try:
            raw = self.base.with_suffix(".read").read_bytes()
            if len(raw) != HEADER.size + self.action_size + 240:
                return None
            values = HEADER.unpack_from(raw)
            return dict(zip(("frame", "ack", "active", "waiting", "cursor", "count", "start_cursor", "hold"), values),
                actions=list(raw[HEADER.size:HEADER.size+self.action_size]), screen=raw[-240:])
        except OSError:
            return None

    async def snapshot(self, predicate=lambda row: True, timeout=15):
        async with asyncio.timeout(timeout):
            while True:
                row = self.read()
                if row is not None and predicate(row):
                    return row
                await asyncio.sleep(.03)

    async def press(self, key, frames=12, release=24):
        self.sequence += 1
        raw = f"{self.sequence} {key} {frames} {release}\n"
        # Complete local files only. A reader sees either the previous command
        # or this command, and the sequence forbids duplicate button execution.
        pending = self.base.with_suffix(".next")
        # Keep the wire newline LF on Windows too; the Lua parser is exact.
        pending.write_bytes(raw.encode("ascii"))
        async with asyncio.timeout(3):
            while True:
                try:
                    os.replace(pending, self.base.with_suffix(".keys"))
                    break
                except PermissionError:
                    await asyncio.sleep(.01)
        row = await self.snapshot(lambda r: r["ack"] == self.sequence)
        self.record("ordinary-input", port=self.base.name, key=key, frame=row["frame"])
        return row

    async def ready(self):
        async with asyncio.timeout(15):
            while True:
                row = await self.snapshot()
                if row["active"] and not row["waiting"]:
                    try:
                        screen = unpack_screen(row["screen"], allow_battle_admission=True)[1]
                        return row, screen
                    except ValueError:
                        pass
                await asyncio.sleep(.03)

    async def choose(self, label, *, wait=True):
        row, screen = await self.ready()
        indices = [n for n, item in enumerate(screen.rows) if item.action and item.label == label]
        require(len(indices) == 1, f"expected one actual displayed choice: {label}")
        for _ in range((indices[0] - row["cursor"]) % len(screen.rows)):
            await self.press(128)
        await self.press(1)
        if wait:
            return await self.ready()

    async def open_players(self):
        await self.press(8, release=60)
        row = await self.snapshot(lambda r: 0 < r["count"] <= self.action_size)
        target = row["actions"][:row["count"]].index(15)
        for _ in range((target-row["start_cursor"]) % row["count"]):
            await self.press(128)
        await self.press(1, release=60)
        await self.snapshot(lambda r: r["actions"][:3] == [16, 17, 18])
        await self.press(128)
        await self.press(1)
        _, screen = await self.ready()
        if screen.back:
            await self.press(2)
            _, screen = await self.ready()
            require(not screen.back, "Players did not reach its ordinary root")


async def on_worker(worker, operation):
    """Every session/SQLite observation runs on its owning worker event loop."""
    async def invoke():
        session = worker._active_session
        if session is None:
            raise RuntimeError("real worker has no active LauncherSession")
        return await operation(session)
    if worker._loop is None:
        raise RuntimeError("worker event loop is unavailable")
    return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(invoke(), worker._loop))


async def run(args):
    require(os.name == "nt", "this qualifier requires the existing Windows runtime")
    require(math.isfinite(args.timeout) and 180 <= args.timeout <= 600, "timeout must be 180..600 seconds")
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
    bundle = append_input_probe(bundle, bridge, output, symbols)
    installation = GameInstallation(output / "input-rom.gba", output / "input-manifest.json",
                                    hashes["rom"], hashes["manifest"], bundle)
    evidence = dict(passed=False, scope=__doc__, inputs=hashes, source_hashes=source_hashes,
        parent_runtime_pin=args.bundle_sha256, proof_runtime_pin=bundle.manifest_sha256,
        checks=[], statuses=[], forced_children=[], cleanup_errors=[],
        physical_input=False, physical_gui_click=False, timed_autosave=False,
        fault_recovery=False, separate_pc=False, internet=False)
    def persist():
        (output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    def record(name, **fields):
        evidence["checks"].append(dict(name=name, **fields))
        persist()
        output_event(check=name, **fields)
    workers, children, windows, roots = [], [], [], []
    enrollment_pids = set()
    gate_task = None
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
            host = create_world(installation, private, player_names=("Cancel Host", "Cancel Friend"), endpoint="127.0.0.1", port=port)
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
            invitation = output / "friend-invitation.json"
            export_friend_invitation(installation, host.directory, 1, invitation)
            saved = []
            for phase in ("cancel-and-save", "fresh-Continue"):
                current, games, probes, mirrors = [], [], [], []
                for slot, mode in enumerate(("host", "join")):
                    worker = SessionWorker(installation, private)
                    workers.append(worker)
                    current.append(worker)
                    import tkinter as tk
                    root = tk.Tk() if not roots else tk.Toplevel(roots[0])
                    window = LauncherWindow(root, worker, version="Private cancellation qualification")
                    root.title(f"Cleanup proof {phase} {mode}")
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
                    probes.append(Probe(output, ipc, action_size, record))
                    async def ready(s):
                        await field_ready(s._companion, s._game)
                        async with asyncio.timeout(20):
                            while s._emergency is None or s._emergency.result.state != "armed":
                                await asyncio.sleep(.03)
                        lease_is_owned(s.profile_directory / "character.sav")
                        require(s._companion._remote_writer.get_extra_info("ssl_object") is not None, "TLS missing")
                        return s.status.revision
                    require(await on_worker(worker, ready) == (1 if phase == "cancel-and-save" else 2), "startup revision differs")
                record("actual-launcher-workers-ready", phase=phase, pids=[g.process.pid for g in games])
                if phase == "cancel-and-save":
                    await probes[0].open_players()
                    await probes[0].choose("Cancel Friend")
                    await probes[0].choose("Rival Battle - 1v1")
                    await probes[1].open_players()
                    await probes[1].choose("Pending challenge")
                    await probes[1].choose("Accept challenge")
                    while (await probes[1].snapshot())["active"]:
                        await probes[1].press(2)
                    async with asyncio.timeout(15):
                        while not (await probes[0].ready())[1].admission_action:
                            await asyncio.sleep(.05)
                    gate_ready = asyncio.get_running_loop().create_future()
                    main_loop = asyncio.get_running_loop()
                    async def gate(s):
                        c = s._companion
                        async with c.live_checkpoint_lock:
                            require(c._live_save_owner is None and getattr(c, "_live_battle_owner", None) is None,
                                    "gate found a live operation")
                            main_loop.call_soon_threadsafe(gate_ready.set_result, True)
                            async with asyncio.timeout(35):
                                while s._battle_menu_preparation is None or s._battle_menu_preparation[0] is None:
                                    await asyncio.sleep(.01)
                                owner, menu, intent = s._battle_menu_preparation
                                require(owner is menu._task and not owner.done(), "original production menu task missing")
                                path = host.directory / "native-battle-execution" / (intent.battle_id + ".consent.json")
                                while not owner.done():
                                    await asyncio.sleep(.01)
                                require(json.loads(path.read_text())["canceled"] is True, "menu drained before durable host cancellation")
                                require((s.profile_directory / (intent.battle_id + ".admission-cleanup.json")).is_file(), "local revocation evidence missing")
                                return intent.value(), sha(path)
                    gate_task = asyncio.create_task(on_worker(current[0], gate))
                    # A gate failure must reach the qualifier instead of
                    # leaving its readiness future pending until the watchdog.
                    ready_tasks, _ = await asyncio.wait((gate_ready, gate_task),
                        timeout=10, return_when=asyncio.FIRST_COMPLETED)
                    if gate_task in ready_tasks:
                        await gate_task
                        raise AssertionError("entry gate ended before native Enter")
                    require(gate_ready in ready_tasks, "entry gate did not become ready")
                    await gate_ready
                    await probes[0].choose("Enter battle", wait=False)
                    async def selected(s):
                        async with asyncio.timeout(10):
                            while not s.can_cancel_battle_entry:
                                await asyncio.sleep(.02)
                        intent = read_admission_intent(s.profile_directory / FILENAME)
                        require(not (s.profile_directory / (intent.battle_id + ".battle-admission-receipt.json")).exists(), "test crossed ADMIT")
                        require(s._store._connection.execute("SELECT count(*) FROM battle_reservations").fetchone()[0] == 0, "test crossed reservation")
                        return intent.value()
                    intent = await on_worker(current[0], selected)
                    battle_id = intent["challenge"]["battle_id"]
                    require((await probes[0].snapshot())["hold"] == 1, "native Enter did not retain the field")
                    host_window = windows[-2]
                    await poll_until(lambda: str(host_window.cancel_battle_entry_button.cget("state")) == "normal", 5)
                    record("real-gui-cancel-enabled-for-native-Enter", battle_id=battle_id)
                    host_window.cancel_battle_entry_button.invoke()
                    require(current[0]._battle_recovery_pending, "actual widget did not dispatch through SessionWorker")
                    original, tombstone_sha = await gate_task
                    gate_task = None
                    require(original == intent, "gate changed original admission")
                    await poll_until(lambda: not current[0]._battle_recovery_pending, 30)
                    async def canceled(s):
                        require(s.status.code == "admission_canceled" and s.can_save and not s.can_cancel_battle_entry, "launcher did not finish exact cleanup/handoff")
                        require(s._battle_retained is None and s._battle_handoff_successor is None, "launcher still retains cleanup ownership")
                        require(s._emergency.result.state == "armed", "fresh successor is not armed")
                        require(not (s.profile_directory / FILENAME).exists(), "provisional intent remains pending")
                        return dict(status=asdict(s.status), handoff_sha256=sha(s.profile_directory / (battle_id + ".admission-cleanup-handoff.json")))
                    result = await on_worker(current[0], canceled)
                    await probes[0].snapshot(lambda row: row["hold"] == 0)
                    record("actual-gui-to-launcher-cancellation-complete", tombstone_sha256=tombstone_sha, **result)
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
                if phase == "cancel-and-save":
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
        if gate_task is not None:
            gate_task.cancel()
            await asyncio.gather(gate_task, return_exceptions=True)
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
    parser.add_argument("--timeout", type=float, default=600)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
