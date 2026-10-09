"""Private Windows four-player native Players/team-menu 2v2 qualification.

Uses four real LauncherWindows/SessionWorkers and ordinary team invitation,
acceptance, 2v2 challenge, every consent and every Enter. The existing 1v1
qualifier supplies the exact read-only diagnostics and ordinary joypad driver;
no production method, response, emulated RAM, RNG or outcome is replaced.

The copied legitimate parties must contain 2/1/1/1 Pokemon, or six each with
--full-parties. A real forced switch must select the host's second party slot;
the full-party profile additionally requires a real sixth-slot selection. Both teams' result
screens, original identities, saver handoff, canonical save and fresh Continue
are verified for all four. Close ONLY reported play PIDs normally, friends then
host, at ready_for_normal_close. Forced cleanup cannot earn acceptance.

Use a 2100-second scenario envelope, an outer runner at 2220 seconds and an
independent watchdog with 120 seconds of cleanup grace. Existing RPC/native
request deadlines remain unchanged. No core is launched by importing this file.
This is source-launched Windows ordinary input on one PC; it does not establish
physical controls, packaged delivery or remote/fault recovery. The separate
full-party profile permits a 6600-second match and 7200-second scenario;
use a 7320-second outer runner and 7440-second watchdog for that profile.
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
import time
import traceback

from emerald_multiplayer import launcher_session as session_module
from emerald_multiplayer.checkpoint_mirror import MirrorLease
from emerald_multiplayer.launcher_gui import LaunchRequest, LauncherWindow, SessionWorker
from emerald_multiplayer.launcher_session import GameInstallation
from emerald_multiplayer.launcher_setup import create_world, export_friend_invitation, host_enrollment
from emerald_multiplayer.player_runtime import RuntimeBundle
from qualify_admission_cleanup import on_worker, require
from qualify_launcher_session import checked_log, inspect_closed_head, output_event
from qualify_live_runtime import field_ready, lease_is_owned, party, proof_bundle, sha
from qualify_menu_battle import (SYMBOLS, PARTY_TASKS, BattleProbe,
    append_input_probe, drive_battle_input)

PLAYER_NAMES = ("Multi Host", "Multi Friend 1", "Multi Friend 2", "Multi Friend 3")
SOURCE_NAMES = ("source_a", "source_b", "source_c", "source_d")
PARTY_COUNTS = (2, 1, 1, 1)
FULL_PARTY_COUNTS = (6, 6, 6, 6)
TEAM_ACCOUNTS = ((0, 1), (2, 3))


def qualification_profile(full_parties, timeout):
    require(type(full_parties) is bool, "full-party selection must be explicit")
    maximum = 7200 if full_parties else 2100
    timeout = maximum if timeout is None else timeout
    require(type(timeout) in (int, float) and math.isfinite(timeout)
            and 600 <= timeout <= maximum, "scenario timeout is outside this profile")
    return (FULL_PARTY_COUNTS if full_parties else PARTY_COUNTS,
            6600 if full_parties else 1200, timeout)


def challenge_slots(challenge, accounts, party_counts=PARTY_COUNTS):
    """Check the actual interleaved native roster without assuming UUID order."""
    require(party_counts in (PARTY_COUNTS, FULL_PARTY_COUNTS), "unsupported proof party profile")
    players = challenge["players"]
    expected = [account.player_id for account in accounts]
    require(len(expected) == len(set(expected)) == 4, "four independent accounts required")
    require(challenge["mode"] == 3 and challenge["state"] == "accepted"
            and len(players) == len(set(players)) == 4 and set(players) == set(expected)
            and len(challenge["consent"]) == 4 and set(challenge["consent"]) == set(players),
            "four-player native consent is incomplete or names another roster")
    require({frozenset(players[::2]), frozenset(players[1::2])} ==
            {frozenset(expected[i] for i in team) for team in TEAM_ACCOUNTS},
            "native side ordering does not preserve the two explicitly formed teams")
    slots = [players.index(player) for player in expected]
    checkpoints = challenge["checkpoints"]
    require(len(checkpoints) == 4 and all(cp["player_id"] == players[i]
            and cp["source_slot"] == i and cp["party_count"] == party_counts[expected.index(players[i])]
            for i, cp in enumerate(checkpoints)), "native roster differs from exact personal parties")
    return slots


def outcome_label(result, player_id):
    require(result["mode"] == 3 and result["outcome"] in (1, 2, 3), "invalid completed Multi result")
    slot = result["players"].index(player_id)
    outcome = "Draw" if result["outcome"] == 3 else "Win" if result["outcome"] == 1 + slot % 2 else "Loss"
    return f"2v2 {outcome} #{result['sequence']}"


def selected_party_slots(blocks):
    selected = []
    for block in blocks:
        data = bytes.fromhex(block["data"])
        if block["kind"] == 8 and len(data) > 9 and data[0] == 1 and data[8] == 33:
            selected.append(dict(owner=block["source"], slot=data[9]))
    return selected


async def close_players(probe):
    async with asyncio.timeout(10):
        while (await probe.snapshot())["active"]:
            await probe.press(2)


async def native_menu_match(current, probes, games, host, symbols, record, *,
                            party_counts=PARTY_COUNTS, match_timeout=1200):
    async def identity(s):
        c = s._companion
        return (s._game, s._runtime, c._bridge, c._bridge.incarnation, c._live_battle_runtime_id)
    before = [await probe.battle() for probe in probes]
    for sender, recipient in TEAM_ACCOUNTS:
        await probes[sender].open_players()
        await probes[sender].choose(host.accounts[recipient].display_name)
        await probes[sender].choose("Invite to team")
        await probes[recipient].open_players()
        await probes[recipient].choose("Team invitation")
        await probes[recipient].choose("Accept invitation")
        await close_players(probes[sender])
        await close_players(probes[recipient])
        record("ordinary-native-team-formed", accounts=[sender, recipient])
    async def teams(s):
        return (await s._companion.team_rpc("status"))["result"]
    team_views = await asyncio.gather(*(on_worker(w, teams) for w in current))
    expected_teams = {frozenset(host.accounts[i].player_id for i in team) for team in TEAM_ACCOUNTS}
    for account_index, view in enumerate(team_views):
        require(view["team"] is not None and host.accounts[account_index].player_id in view["team"]["members"]
                and {frozenset(t["members"]) for t in view["teams"]} == expected_teams,
                "ordinary native team invitations did not form two separate exact duos")
    await probes[0].open_players()
    await probes[0].choose("Your team")
    await probes[0].choose("Challenge other team 2v2")
    for probe in probes[1:]:
        await probe.open_players()
        await probe.choose("Pending challenge")
        await probe.choose("Accept challenge")
    async with asyncio.timeout(20):
        while not all(screen.admission_action for _, screen in await asyncio.gather(*(p.ready() for p in probes))):
            await asyncio.sleep(.05)
    async def descriptor(s):
        values = s._companion._bridge.menu_session.menu._battles
        require(len(values) == 1, "expected one exact native challenge")
        return json.loads(json.dumps(values[0]))
    challenges = await asyncio.gather(*(on_worker(w, descriptor) for w in current))
    challenge = challenges[0]
    require(all(value == challenge for value in challenges), "four displayed native consent descriptors differ")
    slots = challenge_slots(challenge, host.accounts, party_counts)
    originals = [await on_worker(worker, identity) for worker in current]
    battle_id = challenge["battle_id"]
    blocks = []
    async def observe(s):
        service = s._server.battle_execution
        require(service.observer is None, "a previous proof observer exists")
        service.observer = lambda block: blocks.append(dict(block))
    await on_worker(current[0], observe)
    await asyncio.gather(*(p.choose("Enter battle", wait=False) for p in probes))
    record("all-four-native-Enter-selected", battle_id=battle_id, original_pids=[g.process.pid for g in games], source_slots=slots)
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
        if (s._save_failed and s._interaction is None or s._game is None or s._game.process.returncode is not None):
            raise AssertionError("launcher retained a battle failure or lost its original game")
        return s.status.code == "battle_finished" and s.can_save and s._interaction is None
    try:
        async with asyncio.timeout(match_timeout):
            report_at = 0
            while True:
                for driver in drivers:
                    if driver.done():
                        await driver
                if all(await asyncio.gather(*(on_worker(w, finished) for w in current))):
                    break
                if time.monotonic() >= report_at:
                    record("native-2v2-progress", blocks=len(blocks), elapsed_seconds=round(time.monotonic()-started, 3))
                    report_at = time.monotonic()+20
                await asyncio.sleep(.05)
    finally:
        stop.set()
        await asyncio.gather(*drivers)
    async def terminal(s):
        c = s._companion
        require(s._battle_retained is None and s._battle_handoff_successor is None, "launcher still retains battle ownership")
        require(s._emergency.result.state == "armed" and c._emergency_controller is s._emergency, "fresh terminal saver is not armed")
        require(not any((s.profile_directory / name).exists() for name in
            ("pending-battle.json", "pending-battle-admission.json", "pending-export.json", "pending-emergency.json")), "terminal recovery intent remains pending")
        history = (await c.battle_challenge_rpc("history"))["result"]
        values = [v for v in history if v["battle_id"] == battle_id]
        require(len(values) == 1 and values[0]["mode"] == 3 and values[0]["players"] == challenge["players"], "durable native Multi result missing")
        return values[0], dict(status=asdict(s.status), handoff_sha256=sha(s.profile_directory / (battle_id + ".battle-handoff.json")))
    results = []
    for account_index, worker in enumerate(current):
        after = await on_worker(worker, identity)
        require(all(after[n] is originals[account_index][n] for n in range(3)) and after[3:] == originals[account_index][3:], "battle replaced the original core, bridge or native identity")
        require(games[account_index].process.returncode is None, "original native process exited")
        result, details = await on_worker(worker, terminal)
        results.append(result)
        row = await probes[account_index].snapshot(lambda r: r["hold"] == 0)
        state = await probes[account_index].battle(after=row["frame"]-1)
        require(state["count"] == before[account_index]["count"] and state["party_sha256"] == before[account_index]["party_sha256"], "original full personal party was not restored")
        record("launcher-native-battle-completed", slot=account_index, pid=games[account_index].process.pid, **details)
    require(all(result == results[0] for result in results), "four players disagree on durable result")
    selected = selected_party_slots(blocks)
    require(dict(owner=slots[0], slot=1) in selected, "ordinary match did not exercise the two-member trainer's second party slot")
    if party_counts == FULL_PARTY_COUNTS:
        require(any(choice["slot"] == 5 for choice in selected),
                "ordinary full-party match did not exercise a real sixth party slot")
    record("real-native-2v2-result", result=results[0], routed_blocks=len(blocks), selected_party_slots=selected,
           elapsed_seconds=round(time.monotonic()-started, 3))
    for index, probe in enumerate(probes):
        result = results[index]
        await probe.open_players()
        await probe.choose("Challenges")
        await probe.choose("Recent battle results")
        _, screen = await probe.choose(outcome_label(result, host.accounts[index].player_id))
        require(screen.title == "Battle result" and screen.status ==
            ("Draw" if result["outcome"] == 3 else f"Team {result['outcome']} won"), "native history screen differs from durable outcome")
        record("native-result-screen-matches", slot=index, title=screen.title, status=screen.status)
        await close_players(probe)
    return results[0]


async def run(args):
    require(os.name == "nt", "this qualifier requires the existing Windows runtime")
    party_counts, match_timeout, scenario_timeout = qualification_profile(
        getattr(args, "full_parties", False), args.timeout)
    inputs = {name: getattr(args, name).resolve() for name in ("rom", "manifest", "elf", "symbols", "bridge", "source_a", "source_b", "source_c", "source_d")}
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
    installation = GameInstallation(output / "input-rom.gba", output / "input-manifest.json",
                                    hashes["rom"], hashes["manifest"], bundle)
    evidence = dict(passed=False, scope=__doc__, inputs=hashes, source_hashes=source_hashes,
        parent_runtime_pin=args.bundle_sha256, proof_runtime_pin=bundle.manifest_sha256,
        checks=[], statuses=[], forced_children=[], cleanup_errors=[],
        physical_input=False, physical_gui_click=False, timed_autosave=False,
        fault_recovery=False, separate_pc=False, internet=False,
        expected_party_counts=list(party_counts), team_accounts=[list(t) for t in TEAM_ACCOUNTS],
        full_party_profile=party_counts == FULL_PARTY_COUNTS,
        scenario_timeout_seconds=scenario_timeout, match_timeout_seconds=match_timeout)
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
        async with asyncio.timeout(scenario_timeout):
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            host = create_world(installation, private, player_names=PLAYER_NAMES, endpoint="127.0.0.1", port=port)
            expected = []
            for slot, name in enumerate(SOURCE_NAMES):
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
            require([value["count"] for value in expected] == list(party_counts),
                    "copied ordinary parties differ from the selected proof profile")
            invitations = [None]
            for slot in range(1, 4):
                invitation = output / f"friend-{slot}-invitation.json"
                export_friend_invitation(installation, host.directory, slot, invitation)
                invitations.append(invitation)
            saved = []
            for phase in ("battle-and-save", "fresh-Continue"):
                current, games, probes, mirrors = [], [], [], []
                for slot, mode in enumerate(("host", "join", "join", "join")):
                    worker = SessionWorker(installation, private)
                    workers.append(worker)
                    current.append(worker)
                    import tkinter as tk
                    root = tk.Tk() if not roots else tk.Toplevel(roots[0])
                    window = LauncherWindow(root, worker, version="Private 2v2 qualification")
                    root.title(f"2v2 proof {phase} {PLAYER_NAMES[slot]}")
                    roots.append(root)
                    windows.append(window)
                    selection = host.directory / "host.json" if slot == 0 else invitations[slot]
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
                    await native_menu_match(current, probes, games, host, symbols, record,
                                            party_counts=party_counts, match_timeout=match_timeout)
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
                record("ready_for_normal_close", phase=phase, friend_pids=[g.process.pid for g in games[1:]], host_pid=games[0].process.pid, close_order=[g.process.pid for g in reversed(games)])
                await poll_until(lambda: not any(w.busy for w in current), 120)
                require([g.process.returncode for g in games] == [0, 0, 0, 0], "ordinary SDL exit failed")
                for slot, game in enumerate(games):
                    checked_log(game, expected[slot])
                    with MirrorLease(mirrors[slot]):
                        pass
                record("normal-close-and-native-party-verified", phase=phase, exit_codes=[0, 0, 0, 0])
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
    for name in ("rom", "manifest", "elf", "symbols", "bridge", "bundle", "source-a", "source-b", "source-c", "source-d"):
        parser.add_argument("--" + name, type=Path, required=True)
        parser.add_argument("--" + name + "-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--full-parties", action="store_true")
    parser.add_argument("--timeout", type=float, default=None,
                        help="Scenario seconds; defaults to 2100, or 7200 for --full-parties")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
