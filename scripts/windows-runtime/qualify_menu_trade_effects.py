"""Private actual Windows public native-effect trade and fresh Continue proof.

Uses two real LauncherSessions and their original Players/MenuSession tasks,
ordinary bounded joypad presses, explicit consent and private native candidate
review, the pinned real host replay worker and canonical checkpoint ownership.
All enrolled characters/worlds are new disposable copies. Diagnostic geography
policy is explicit and does not select a user's production-world policy.

The supplied genuine parties determine evolution coverage: no invented Pokemon,
RAM writes, forced outcomes or injected receipts. Any native move decisions are
explicitly declined through the complete ordinary review/confirmation screens.
No animation, physical keyboard, GUI-button, LAN/Internet or fault acceptance.
Close only the reported friend then host game windows normally at each phase.
Use a separate process watchdog at least 120 seconds beyond --timeout.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import AsyncExitStack
import hashlib
import json
import math
import os
import re
from pathlib import Path
import shutil
import socket
import time
import traceback

from emerald_multiplayer import launcher_session as session_module
from emerald_multiplayer.checkpoint_mirror import MirrorLease
from emerald_multiplayer.launcher_session import GameInstallation, LauncherSession, SessionState
from emerald_multiplayer.launcher_setup import create_world, export_friend_invitation, host_enrollment
from emerald_multiplayer.player_runtime import RuntimeBundle
from emerald_multiplayer.trade_capability import native_effects_available
from emerald_multiplayer.trade_effect_preparation import POLICIES
from emerald_multiplayer.trade_effect_storage import parse_document
from emerald_multiplayer.trade_effect_witness import MAX_CHOICES
from qualify_admission_cleanup import SYMBOLS, Probe, append_input_probe, require
from qualify_launcher_session import checked_log, inspect_closed_head, output_event, wait_for_child
from qualify_live_runtime import field_ready, lease_is_owned, party, proof_bundle, sha


async def until(predicate, *, timeout=30, tasks=()):
    async with asyncio.timeout(timeout):
        while not predicate():
            for task in tasks:
                if task.done():
                    await task
                    raise AssertionError("original native play task ended early")
            await asyncio.sleep(.05)


async def displayed(probe, predicate, *, timeout=45):
    """Wait for a complete, actually displayed native screen; never issue RPCs."""
    async with asyncio.timeout(timeout):
        while True:
            row, screen = await probe.ready()
            if predicate(screen):
                return row, screen
            await asyncio.sleep(.05)


async def choose_visible(probe, label):
    await displayed(probe, lambda s: any(r.action and r.label == label for r in s.rows))
    await probe.choose(label, wait=False)


async def choose_party_slot(probe, slot):
    row, screen = await displayed(probe, lambda s: s.title == "Trade Pokemon"
                                  and s.status == "Pick; [X] blocked; B: cancel")
    require(0 <= slot < len(screen.rows) <= 6 and screen.rows[slot].action
            and not screen.rows[slot].label.startswith("[X]"), "selected genuine Pokemon is not eligible")
    # Native rows can have identical species/level labels. Use the explicitly
    # pinned party slot, preserving the same ordinary Probe key sequence.
    for _ in range((slot-row["cursor"]) % len(screen.rows)):
        await probe.press(128)
    await probe.press(1)


async def open_players_first_screen(probe):
    """Use ordinary Start/Player/Players keys without dismissing its notice.

    The shared setup helper normalizes a retained detail page with Back; that
    intentional action clears completion notices. Here the first displayed
    page itself is the evidence, regardless of the retained navigation page.
    """
    await probe.press(8, release=60)
    row = await probe.snapshot(lambda r: 0 < r["count"] <= probe.action_size)
    target = row["actions"][:row["count"]].index(15)
    for _ in range((target-row["start_cursor"]) % row["count"]):
        await probe.press(128)
    await probe.press(1, release=60)
    await probe.snapshot(lambda r: r["actions"][:3] == [16, 17, 18])
    await probe.press(128)
    await probe.press(1)
    return await probe.ready()


async def review_candidate(probe, slot, record):
    decisions = 0
    while True:
        _, screen = await displayed(probe, lambda s: s.title == "Trade preparation"
                                    or s.title.startswith("Learn "), timeout=90)
        record("native-effect-review", slot=slot, title=screen.title, status=screen.status,
               rows=[r.label for r in screen.rows])
        labels = [r.label for r in screen.rows if r.action]
        if "Choose evolution move" in labels or screen.title.startswith("Learn "):
            require(decisions < MAX_CHOICES, "native evolution decision count exceeded its bound")
            if "Choose evolution move" in labels:
                await choose_visible(probe, "Choose evolution move")
            await choose_visible(probe, "Decline this move")
            await choose_visible(probe, "Continue to confirmation")
            await choose_visible(probe, "Confirm decline")
            decisions += 1
            record("native-evolution-move-declined", slot=slot, decision=decisions)
            continue
        require("Prepare candidate" in labels, "native candidate never reached READY")
        await choose_visible(probe, "Review Pokemon")
        _, detail = await displayed(probe, lambda s: s.title.startswith("Candidate "))
        record("native-candidate-details", slot=slot, title=detail.title, status=detail.status,
               rows=[r.label for r in detail.rows])
        await probe.press(2)
        await displayed(probe, lambda s: s.title == "Trade preparation")
        await choose_visible(probe, "Prepare candidate")
        await choose_visible(probe, "Prepare private copy")
        return decisions


async def public_trade(sessions, games, probes, tasks, host, slots, record):
    store = sessions[0]._store
    originals = [(s._game, s._runtime, s._companion._bridge, s._companion.save_incarnation)
                 for s in sessions]
    before = [inspect_closed_head(store, a.player_id) for a in host.accounts]
    serials = sorted(v for h in before for v in party(h)["serials"])
    require(store.trade_effects_enabled, "new world lacks its explicit native effect extension")
    require(all(native_effects_available(s._companion) for s in sessions), "original core effect transport missing")
    require(store._connection.execute("SELECT COUNT(*) FROM trade_effect_commits").fetchone()[0] == 0,
            "disposable world already contains an effect trade")
    await probes[0].open_players()
    await choose_visible(probes[0], host.accounts[1].display_name)
    await choose_visible(probes[0], "Trading")
    await choose_party_slot(probes[0], slots[0])
    await probes[1].open_players()
    await choose_visible(probes[1], "Pending trade")
    await choose_visible(probes[1], "Choose your Pokemon")
    await choose_party_slot(probes[1], slots[1])
    for probe in probes:
        await displayed(probe, lambda s: any(r.label == "Confirm this trade" and r.action for r in s.rows))
    await choose_visible(probes[0], "Confirm this trade")
    await displayed(probes[0], lambda s: s.status == "Confirmed; waiting for friend")
    require(store._connection.execute("SELECT COUNT(*) FROM trade_effect_commits").fetchone()[0] == 0,
            "one consent published an effect trade")
    require([inspect_closed_head(store, a.player_id).revision for a in host.accounts] == [2, 2],
            "prepared source checkpoints differ from the original base plus one")
    intents = [json.loads((s.profile_directory / "pending-trade.json").read_text())["intent"] for s in sessions]
    identities = {(i["transaction_id"], i["generation"]) for i in intents}
    require(len(identities) == 1, "originals prepared different trades")
    tx, generation = identities.pop()
    record("one-consent-no-commit", transaction_id=tx, generation=generation)
    await choose_visible(probes[1], "Confirm this trade")
    await asyncio.gather(*(displayed(p, lambda s: s.title == "Trade preparation", timeout=90) for p in probes))
    require(store._connection.execute("SELECT COUNT(*) FROM trade_effect_commits").fetchone()[0] == 0,
            "consent without explicit native candidate review published a trade")
    record("both-consents-await-native-review", transaction_id=tx)
    decisions = await asyncio.gather(*(review_candidate(p, slot, record) for slot, p in enumerate(probes)))
    started = time.monotonic()
    report_at = 0
    async with asyncio.timeout(240):
        while not all(s.status.code == "trade_finished" and s.can_save and s._interaction is None for s in sessions):
            for task in tasks:
                if task.done():
                    await task
                    raise AssertionError("original game closed before trade completion")
            require(not any(s._save_failed and s._interaction is None for s in sessions),
                    "launcher retained a trade failure")
            if time.monotonic() >= report_at:
                record("native-trade-progress", elapsed_seconds=round(time.monotonic()-started, 3),
                       statuses=[s.status.code for s in sessions])
                report_at = time.monotonic()+20
            await asyncio.sleep(.05)
    rows = store._connection.execute("SELECT * FROM trade_effect_commits WHERE transaction_id=?", (tx,)).fetchall()
    require(len(rows) == 1, "native replay did not publish exactly one effect commit")
    document = parse_document(rows[0])
    require(all(d["generation"] == generation and d["format"] == "emerald-trade-recipient-effects-v2"
                for d in document["descriptions"]), "canonical effect proof identity changed")
    after = [inspect_closed_head(store, a.player_id) for a in host.accounts]
    require(sorted(v for h in after for v in party(h)["serials"]) == serials, "ownership serials changed")
    received = []
    for slot, (session, probe, game) in enumerate(zip(sessions, probes, games)):
        original = originals[slot]
        require(all(a is b for a, b in zip(original[:3],
                (session._game, session._runtime, session._companion._bridge)))
                and session._companion.save_incarnation == original[3], "trade replaced an original core/bridge")
        require(game.process.returncode is None and after[slot].revision == 3 and session.status.revision == 3,
                "terminal revision or original process differs")
        require(session._emergency.result.state == "armed", "terminal emergency saver is not armed")
        require(not (session.profile_directory / "pending-trade.json").exists(), "trade intent remains pending")
        prefix = tx + "." + generation
        receipt_path = session.profile_directory / (prefix + ".effect-receipt.json")
        receipt = json.loads(receipt_path.read_text())
        result_path = session.profile_directory / (prefix + ".received-result.json")
        result = json.loads(result_path.read_text())
        require(result["candidate_sha256"] == after[slot].sha256 and result["revision"] == 3,
                "received result is not the applied canonical candidate")
        require(result["serial"] == party(before[1-slot])["serials"][slots[1-slot]]
                and party(after[slot])["serials"][slots[slot]] == result["serial"],
                "recipient did not receive the friend's selected original Pokemon")
        require(len(receipt["receipt"]["choices"]) == decisions[slot], "native decisions differ from durable receipt")
        player_index = next(n for n, d in enumerate(document["descriptions"])
                            if d["recipient_id"] == host.accounts[slot].player_id)
        require(receipt["receipt"] == document["receipts"][player_index], "client and replay receipts differ")
        # Canonical import returns to the field; the success notification is
        # retained in Players. Open it through the ordinary Start submenu.
        if not (await probe.snapshot())["active"]:
            await open_players_first_screen(probe)
        _, screen = await displayed(probe, lambda s: s.status.startswith(("Received: ", "Evolved: ")))
        record("native-received-result", slot=slot, status=screen.status, result=result,
               receipt_sha256=sha(receipt_path), result_sha256=sha(result_path))
        received.append(result)
        async with asyncio.timeout(15):
            while (await probe.snapshot())["active"]:
                await probe.press(2)
    store.integrity_check()
    record("paired-native-effect-commit", transaction_id=tx, generation=generation,
           commit_sha256=rows[0]["sha256"], evolved=[r["evolved"] for r in received], move_decisions=decisions)
    return [party(h) for h in after]


async def run(args, *, trade_flow=public_trade, interrupted=False, interrupted_outcome="aborted", scope=None):
    require(os.name == "nt", "Windows native runtime required")
    require(math.isfinite(args.timeout) and 300 <= args.timeout <= 1800, "bounded timeout required")
    require(interrupted_outcome in ("aborted", "committed"), "explicit interruption fate required")
    committed_cut = interrupted and interrupted_outcome == "committed"
    canonical_revision = (3 if committed_cut else 2) if interrupted else 4
    slots = (args.slot_a, args.slot_b)
    require(all(type(v) is int and 0 <= v < 6 for v in slots), "explicit original party slots required")
    names = ("rom", "manifest", "elf", "symbols", "bridge", "worker", "source_a", "source_b")
    inputs = {n: getattr(args, n).resolve() for n in names}
    hashes = {n: sha(p) for n, p in inputs.items()}
    require(hashes == {n: getattr(args, n + "_sha256") for n in names}, "explicit input pins differ")
    manifest = json.loads(inputs["manifest"].read_text())
    required = dict(menu_abi_version=2, trade_abi_version=1, emergency_save_abi_version=2,
        trade_effect_prepare_abi_version=1, trade_effect_save_abi_version=1,
        trade_effect_choice_abi_version=1, trade_replay_abi_version=1)
    require(manifest["elf_sha256"] == hashes["elf"] and all(manifest.get(k) == v for k, v in required.items()),
            "exact public effect game required")
    symbols = {}
    for line in inputs["symbols"].read_text().splitlines():
        fields = line.split()
        if len(fields) == 4:
            symbols[fields[3]] = (int(fields[0], 16), int(fields[1], 16))
    require(all(symbols.get(k, (0, 0))[1] == v for k, v in SYMBOLS.items()), "menu diagnostic sizes differ")
    action_size = symbols.get("sCurrentStartMenuActions", (0, 0))[1]
    require(3 <= action_size <= 64, "bounded start menu required")
    for name in (*SYMBOLS, "sCurrentStartMenuActions"):
        address, size = symbols[name]
        require(0x02000000 <= address and address + size <= 0x02040000 or
                0x03000000 <= address and address + size <= 0x03008000, "diagnostic outside native RAM")
    parent = RuntimeBundle(args.bundle.resolve(), args.bundle_sha256)
    GameInstallation(inputs["rom"], inputs["manifest"], hashes["rom"], hashes["manifest"], parent).verify()
    output = args.output.resolve()
    require("PokemonPrivate" in output.parts, "fresh private output required")
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
    shutil.copyfile(inputs["worker"], bundle.directory / "emerald-trade-replay.exe")
    metadata = bundle.directory / "runtime.json"
    value = json.loads(metadata.read_text())
    value["files"]["emerald-trade-replay.exe"] = hashes["worker"]
    metadata.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    bundle = RuntimeBundle(bundle.directory, sha(metadata))
    installation = GameInstallation(output / "input-rom.gba", output / "input-manifest.json",
                                    hashes["rom"], hashes["manifest"], bundle)
    evidence = dict(passed=False, scope=scope or __doc__, inputs=hashes, source_hashes=source_hashes,
        parent_runtime_pin=args.bundle_sha256, proof_runtime_pin=bundle.manifest_sha256,
        diagnostic_policy=args.trade_effect_policy, selected_party_slots=slots,
        checks=[], forced_children=[], cleanup_errors=[])
    def persist():
        (output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    def record(name, **fields):
        evidence["checks"].append(dict(name=name, **fields))
        persist()
        output_event(check=name, **fields)
    children, all_tasks, enrollment_pids = [], [], set()
    completed = False
    private = output / "private"
    try:
        async with asyncio.timeout(args.timeout):
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            host = create_world(installation, private, player_names=("Trade Host", "Trade Friend"),
                endpoint="127.0.0.1", port=port, trade_effect_policy=args.trade_effect_policy)
            for slot, name in enumerate(("source_a", "source_b")):
                async with host_enrollment(installation, private, world_directory=host.directory,
                        slot=slot, source_path=inputs[name]) as runtime:
                    children.append(runtime._game.process)
                    record("enrollment-child", slot=slot, pid=runtime._game.process.pid)
                    await field_ready(runtime.companion, runtime._game)
                    enrolled = await runtime.enroll()
                    require(enrolled.metadata["revision"] == 1 and runtime._game.process.returncode is not None,
                            "production enrollment did not complete and close its bootstrap child")
                    enrollment_pids.add(runtime._game.process.pid)
                    record("production-enrollment-closed-bootstrap", slot=slot, pid=runtime._game.process.pid,
                           returncode=runtime._game.process.returncode)
                with MirrorLease(runtime.save_path):
                    pass
            invitation = output / "friend-invitation.json"
            export_friend_invitation(installation, host.directory, 1, invitation)
            saved, expected = [], []
            first_phase = "interrupted-trade" if interrupted else "trade-and-save"
            for phase in (first_phase, "fresh-Continue"):
                sessions = [LauncherSession(installation, private, world_directory=host.directory,
                                bind_address="127.0.0.1", host_route="127.0.0.1"),
                            LauncherSession(installation, private, invitation_path=invitation)]
                async with AsyncExitStack() as stack:
                    for session in sessions:
                        await stack.enter_async_context(session.open())
                        require(session.status.state is SessionState.READY and
                                session.status.revision == (1 if phase == first_phase else canonical_revision), "startup revision differs")
                        await session.set_autosave_enabled(False)
                    tasks = [asyncio.create_task(session.play()) for session in sessions]
                    all_tasks.extend(tasks)
                    games = await asyncio.gather(*(wait_for_child(s, t, children) for s, t in zip(sessions, tasks)))
                    record("actual-launcher-cores", phase=phase, pids=[g.process.pid for g in games])
                    try:
                        await asyncio.gather(*(field_ready(s._companion, g) for s, g in zip(sessions, games)))
                        await until(lambda: all(s._emergency and s._emergency.result.state == "armed" for s in sessions), tasks=tasks)
                        for session in sessions:
                            lease_is_owned(session.profile_directory / "character.sav")
                            require(session._companion._remote_writer.get_extra_info("ssl_object") is not None, "TLS missing")
                        probes = [Probe(output, s._companion.ipc_address[1], action_size, record) for s in sessions]
                        if phase == first_phase:
                            original_parties = [party(inspect_closed_head(sessions[0]._store, a.player_id)) for a in host.accounts]
                            expected = await trade_flow(sessions, games, probes, tasks, host, slots, record)
                            if not interrupted:
                                require(all(await asyncio.gather(*(s.save() for s in sessions))), "posttrade manual save failed")
                        heads = [inspect_closed_head(sessions[0]._store, a.player_id) for a in host.accounts]
                        require(all(h.revision == canonical_revision and party(h) == expected[i] for i, h in enumerate(heads)),
                                "canonical posttrade party or manual-save revision differs")
                        actual = [(h.revision, h.sha256, h.payload) for h in heads]
                        if phase == first_phase:
                            saved = actual
                        else:
                            require(actual == saved and all(g.startup.mirror.sha256 == heads[i].sha256
                                    for i, g in enumerate(games)), "fresh Continue changed canonical characters")
                            if interrupted:
                                require(all(g.startup.trade_result is not None and
                                    g.startup.trade_result["state"] == ("applied" if committed_cut else "aborted")
                                    for g in games), "closed recovery did not report the verified fate")
                                if committed_cut:
                                    for i, game in enumerate(games):
                                        result = game.startup.trade_result
                                        received = result.get("received")
                                        require(received is not None and received["candidate_sha256"] == heads[i].sha256
                                                and received["revision"] == canonical_revision
                                                and received["serial"] in expected[i]["serials"],
                                                "fresh recovery omitted the exact received Pokemon result")
                                        result_path = sessions[i].profile_directory / (
                                            result["transaction_id"] + "." + result["generation"] + ".received-result.json")
                                        require(json.loads(result_path.read_bytes()) == received,
                                                "fresh recovery result differs from retained notification")
                                    receipts = list(sessions[0]._store._connection.execute("SELECT acknowledged FROM trade_recovery"))
                                    require(len(receipts) == 2 and all(r[0] == 1 for r in receipts),
                                            "fresh canonical restore did not acknowledge both committed recipients")
                                require(all(not (s.profile_directory / "pending-trade.json").exists()
                                    and s.can_save for s in sessions), "fresh recovery did not retire original intent")
                                require(all(await asyncio.gather(*(s.save() for s in sessions))), "fresh recovered manual save failed")
                                heads = [inspect_closed_head(sessions[0]._store, a.player_id) for a in host.accounts]
                                require(all(h.revision == canonical_revision + 1 and party(h) == expected[i] for i, h in enumerate(heads)),
                                        "recovered save changed party or revision")
                                saved = [(h.revision, h.sha256, h.payload) for h in heads]
                                record("fresh-cold-recovery-and-save", results=[g.startup.trade_result for g in games])
                        record("ready_for_normal_close", phase=phase, friend_pid=games[1].process.pid,
                               host_pid=games[0].process.pid)
                        exits = await asyncio.wait_for(asyncio.gather(*tasks), 120)
                        require(exits == [0, 0], "native normal close failed")
                        for i, game in enumerate(games):
                            if committed_cut and phase == first_phase:
                                # At a genuine service-loss cut an original can
                                # still hold its source or have imported the
                                # entire canonical candidate before ACK. Never
                                # count a third/native partial party as valid.
                                samples = re.findall(r"WINDOWS_LIVE party_count=(\d+) box_crc=([0-9a-f]{8})",
                                                     game.log_path.read_text(errors="replace"))
                                options = [(str(p["count"]), p["box_crc"]) for p in (original_parties[i], expected[i])]
                                require(samples and samples[-1] in options, "original native party is neither source nor committed candidate")
                                record("original-held-native-party", slot=i,
                                       party_state="source" if samples[-1] == options[0] else "committed-candidate")
                            else:
                                checked_log(game, expected[i])
                        record("normal-close-and-native-party-verified", phase=phase, exit_codes=exits)
                    except BaseException as error:
                        chain, seen, current = [], set(), error
                        while current is not None and id(current) not in seen and len(chain) < 12:
                            seen.add(id(current))
                            chain.append(dict(type=type(current).__name__, code=getattr(current, "code", None),
                                              detail=str(current)))
                            current = current.__cause__ or current.__context__
                        record("phase-failed-before-cleanup", phase=phase, errors=chain,
                               traceback=traceback.format_exc(),
                               statuses=[s.status.code for s in sessions],
                               pids=[g.process.pid for g in games])
                        raise
                    finally:
                        # Mark forced cleanup before production play cancellation
                        # can stop the child. Cancellation cannot earn acceptance.
                        for game in games:
                            if game.process.returncode is None:
                                evidence["forced_children"].append(game.process.pid)
                        for task in tasks:
                            if not task.done():
                                task.cancel()
                        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 30)
                for session in sessions:
                    with MirrorLease(session.profile_directory / "character.sav"):
                        pass
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
        for child in children:
            if child.returncode is None:
                evidence["forced_children"].append(child.pid)
                try:
                    child.terminate()
                    try:
                        await asyncio.wait_for(child.wait(), 5)
                    except TimeoutError:
                        child.kill()
                        await asyncio.wait_for(child.wait(), 5)
                except BaseException as error:
                    evidence["cleanup_errors"].append(repr(error))
        for task in all_tasks:
            if not task.done():
                task.cancel()
        try:
            await asyncio.wait_for(asyncio.gather(*all_tasks, return_exceptions=True), 15)
        except BaseException as error:
            evidence["cleanup_errors"].append(repr(error))
        evidence["child_exits"] = [dict(pid=p.pid, returncode=p.returncode) for p in children]
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
            and all(p.returncode is not None and (p.pid in enrollment_pids or p.returncode == 0) for p in children))
        persist()
        output_event(passed=evidence["passed"], child_exits=evidence["child_exits"])
    require(evidence["passed"], "qualification failed; private evidence preserved")


def arguments(description=__doc__):
    parser = argparse.ArgumentParser(description=description)
    for name in ("rom", "manifest", "elf", "symbols", "bridge", "worker", "bundle", "source-a", "source-b"):
        parser.add_argument("--" + name, type=Path, required=True)
        parser.add_argument("--" + name + "-sha256", required=True)
    parser.add_argument("--trade-effect-policy", choices=POLICIES, required=True)
    parser.add_argument("--slot-a", type=int, choices=range(6), required=True)
    parser.add_argument("--slot-b", type=int, choices=range(6), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=1200)
    return parser.parse_args()


def main():
    asyncio.run(run(arguments()))


if __name__ == "__main__":
    main()
