"""Private actual Windows enrollment, TLS Host/Join, Save now and fresh Continue.

Uses original unassigned saves and public setup/session controllers. The only
test adapter replays ordinary joypad input and reads party diagnostics. Close
both owned game windows normally when the phase prints ready_for_normal_close.
This is not physical keyboard, GUI-button, clean-machine or Internet acceptance.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import AsyncExitStack
import json
from pathlib import Path
import re
import shutil
import socket

from emerald_multiplayer.checkpoint_mirror import MirrorLease
from emerald_multiplayer.launcher_session import GameInstallation, LauncherSession, SessionState
from emerald_multiplayer.launcher_setup import create_world, export_friend_invitation, host_enrollment
from emerald_multiplayer.player_runtime import RuntimeBundle
from qualify_live_runtime import field_ready, lease_is_owned, party, proof_bundle, sha


def output_event(**fields):
    print(json.dumps(fields), flush=True)


async def wait_for_child(session, task, children):
    async with asyncio.timeout(30):
        while session._game is None:
            if task.done():
                await task
                raise RuntimeError("session finished before its native child")
            await asyncio.sleep(.05)
    children.append(session._game.process)
    return session._game


def checked_log(game, expected):
    samples = re.findall(r"WINDOWS_LIVE party_count=(\d+) box_crc=([0-9a-f]{8})",
                         game.log_path.read_text(errors="replace"))
    if not samples or samples[-1] != (str(expected["count"]), expected["box_crc"]):
        raise RuntimeError("native party differs from canonical character")


def inspect_closed_head(store, player_id):
    # Read-only proof inspection while the server is closed. Do not boot a
    # server or acquire a new lease just to inspect its canonical checkpoint.
    row = store._connection.execute(
        "SELECT c.* FROM checkpoints c JOIN players p ON p.player_id=c.player_id "
        "AND p.latest_revision=c.revision WHERE p.player_id=?", (player_id,)).fetchone()
    if row is None:
        raise RuntimeError("expected canonical character is missing")
    return store._checkpoint(row)


async def run(args):
    output = args.output.resolve()
    inputs = {"rom": args.rom.resolve(), "manifest": args.manifest.resolve(),
              "source_a": args.source_a.resolve(), "source_b": args.source_b.resolve()}
    before = {name: sha(path) for name, path in inputs.items()}
    pins = dict(rom=args.rom_sha256, manifest=args.manifest_sha256,
                source_a=args.source_a_sha256, source_b=args.source_b_sha256)
    if before != pins:
        raise ValueError("qualification inputs differ from their explicit pins")
    parent = RuntimeBundle(args.bundle.resolve(), args.bundle_sha256)
    GameInstallation(inputs["rom"], inputs["manifest"], pins["rom"], pins["manifest"], parent).verify()
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, output / "controller.py")
    shutil.copyfile(Path(__file__).with_name("qualify_live_runtime.py"), output / "qualify_live_runtime.py")
    for name in ("rom", "manifest"):
        shutil.copyfile(inputs[name], output / ("game.gba" if name == "rom" else "manifest.json"))
    bundle = proof_bundle(parent, output, json.loads(inputs["manifest"].read_text()))
    installation = GameInstallation(output / "game.gba", output / "manifest.json",
                                    pins["rom"], pins["manifest"], bundle)
    private = output / "private"
    evidence = dict(passed=False, inputs=before, parent_runtime_pin=args.bundle_sha256,
                    proof_runtime_pin=bundle.manifest_sha256, enrollment=[], sessions=[],
                    scripted_ordinary_joypad=True, physical_input_qualified=False,
                    gui_buttons_qualified=False, separate_pc_qualified=False,
                    internet_qualified=False, transport="pinned TLS authenticated loopback")
    children = []
    try:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        host = create_world(installation, private, player_names=("Host proof", "Friend proof"),
                            endpoint="127.0.0.1", port=port)
        expected_parties = []
        for slot, name in enumerate(("source_a", "source_b")):
            async with host_enrollment(installation, private, world_directory=host.directory,
                                       slot=slot, source_path=inputs[name]) as runtime:
                game = runtime._game
                children.append(game.process)
                output_event(phase="enrollment", slot=slot, pid=game.process.pid)
                capabilities = await field_ready(runtime.companion, game)
                lease_is_owned(runtime.save_path)
                tls = runtime.companion._remote_writer.get_extra_info("ssl_object")
                assert tls is not None
                result = await runtime.enroll()
                assert result.metadata["revision"] == 1 and game.process.returncode is not None
                assert runtime.receipt_path.exists() and not runtime.pending_path.exists()
                evidence["enrollment"].append(dict(slot=slot, revision=1, sha256=result.flash_sha256,
                    capabilities=capabilities, tls=True, child_closed=True))
            # Setup fully relinquishes child, lease, listener and store first.
            with MirrorLease(runtime.save_path):
                pass
            with host.open_store() as store:
                # Inspection only; no new authentication epoch or lease here.
                head = inspect_closed_head(store, host.accounts[slot].player_id)
                expected_parties.append(party(head))
        invitation = output / "friend-invitation.json"
        export_friend_invitation(installation, host.directory, 1, invitation)

        saved_heads = {}
        for phase in ("save-now", "fresh-Continue"):
            sessions = [LauncherSession(installation, private, world_directory=host.directory,
                        bind_address="127.0.0.1", host_route="127.0.0.1"),
                        LauncherSession(installation, private, invitation_path=invitation)]
            tasks, games = [], []
            details = dict(phase=phase, players=[])
            evidence["sessions"].append(details)
            async with AsyncExitStack() as stack:
                for session in sessions:
                    await stack.enter_async_context(session.open())
                    assert session.status.state is SessionState.READY
                    assert session.status.revision == (1 if phase == "save-now" else 2)
                assert sessions[0]._server.battle_desk is None
                assert sessions[0]._server.trade_desk is None
                try:
                    tasks = [asyncio.create_task(session.play()) for session in sessions]
                    games = await asyncio.gather(*(wait_for_child(s, t, children) for s, t in zip(sessions, tasks)))
                    output_event(phase=phase, pids=[game.process.pid for game in games])
                    capabilities = await asyncio.gather(*(field_ready(s._companion, g)
                                                          for s, g in zip(sessions, games)))
                    for session in sessions:
                        lease_is_owned(session.profile_directory / "character.sav")
                        assert session._companion._remote_writer.get_extra_info("ssl_object") is not None
                    if phase == "save-now":
                        assert all(await asyncio.gather(*(session.save() for session in sessions)))
                    for slot, (session, game, caps) in enumerate(zip(sessions, games, capabilities)):
                        assert session.status.revision == 2
                        head = sessions[0]._store.read_checkpoint(host.accounts[slot].player_id,
                                                                  session._companion.session_epoch)
                        assert head.revision == 2 and party(head) == expected_parties[slot]
                        checked_log(game, expected_parties[slot])
                        if phase == "fresh-Continue":
                            assert game.startup.mirror.sha256 == head.sha256
                            assert saved_heads[slot] == (head.revision, head.sha256, head.payload)
                        else:
                            saved_heads[slot] = (head.revision, head.sha256, head.payload)
                        details["players"].append(dict(slot=slot, revision=2, sha256=head.sha256,
                            capabilities=caps, party_matches=True, tls=True,
                            startup_evidence=str(game.startup.evidence_path)))
                    output_event(phase=phase, ready_for_normal_close=True)
                    exits = await asyncio.wait_for(asyncio.gather(*tasks), 180)
                    assert exits == [0, 0]
                    details["normal_exit_codes"] = exits
                finally:
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
            for session in sessions:
                with MirrorLease(session.profile_directory / "character.sav"):
                    pass
            details["all_leases_released"] = True
        with host.open_store() as store:
            store.integrity_check()
            for account in host.accounts:
                head = inspect_closed_head(store, account.player_id)
                assert saved_heads[account.slot] == (head.revision, head.sha256, head.payload)
        evidence["passed"] = True
    except BaseException as error:
        evidence["error_type"] = type(error).__name__
        evidence["error_code"] = getattr(error, "code", None)
        # Private diagnostic evidence preserves chained errors hidden by the
        # intentionally bounded player-facing setup status. Never print it.
        evidence["error_context"] = []
        current = error
        while current is not None and len(evidence["error_context"]) < 8:
            evidence["error_context"].append(dict(type=type(current).__name__,
                code=getattr(current, "code", None), message=str(current)))
            current = current.__context__
        raise
    finally:
        evidence["all_children_closed"] = all(child.returncode is not None for child in children)
        evidence["source_hashes_after"] = {name: sha(path) for name, path in inputs.items()}
        evidence["sources_unchanged"] = evidence["source_hashes_after"] == before
        evidence["passed"] = evidence["passed"] and evidence["sources_unchanged"] and evidence["all_children_closed"]
        (output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        output_event(passed=evidence["passed"], all_children_closed=evidence["all_children_closed"])
    if not evidence["passed"]:
        raise RuntimeError("qualification source preservation or child cleanup failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rom", "manifest", "bundle", "source-a", "source-b", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("rom", "manifest", "bundle", "source-a", "source-b"):
        parser.add_argument("--" + name + "-sha256", required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
