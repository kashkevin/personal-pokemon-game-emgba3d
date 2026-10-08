"""Profile the frozen actual-core proof without changing its inputs or checks.

Wrappers time production operations; only the ordinary proof's Lua commands
write ROM-owned mailboxes. Baseline and new builds use separate fresh worlds.
"""
from __future__ import annotations

import argparse
import asyncio
from contextvars import ContextVar
import hashlib
import json
from pathlib import Path
import time
from unittest.mock import patch
from uuid import uuid4

import save_window_proof as proof
from emerald_multiplayer.live_checkpoint import LiveCheckpointCoordinator
from emerald_multiplayer.save_mailbox import Opcode

PROOF_SHA256 = "dc6df9d0debbbb5faa2d259302b7b8ae638f8b517f7f7f7f932f3c6095d28cdd"
BASELINE_ROM = "26a86fd1d616b1a1f86f860b4423f91d886c5703fc84027c6d7e57e1b219fabb"


async def run(args):
    source = Path(proof.__file__)
    if hashlib.sha256(source.read_bytes()).hexdigest() != PROOF_SHA256:
        raise ValueError("profiling requires the preserved proof source")
    baseline_bytes = args.baseline_evidence.read_bytes()
    baseline = json.loads(baseline_bytes)
    if (baseline.get("passed") is not True or baseline.get("cores_closed") is not True
            or baseline.get("rom_sha256") != BASELINE_ROM or baseline.get("frame_rate") != 60
            or baseline.get("timing_label") != "quiet"):
        raise ValueError("comparison requires the completed quiet d0db 60fps proof")
    rows, attempts, writes = [], [], {}
    context = ContextVar("profile-attempt", default=None)

    class TrackPump(proof.Pump):
        def __init__(self, cores, companions):
            super().__init__(cores, companions)
            for companion in companions:
                companion._proof_profile_pump = self

    class TrackPacedPump(proof.PacedPump):
        def __init__(self, cores, companions):
            super().__init__(cores, companions)
            for companion in companions:
                companion._proof_profile_pump = self

    def frames(c):
        pump = getattr(c, "_proof_profile_pump", None)
        return pump.frames if pump is not None else 0

    def timer(c, stage, operation, *, write_key=None):
        async def measured(*values, **fields):
            start, first = time.monotonic(), frames(c)
            outcome = "ok"
            try:
                return await operation(*values, **fields)
            except BaseException as error:
                outcome = getattr(error, "code", type(error).__name__)
                raise
            finally:
                row = dict(attempt_id=context.get(), player_id=c.config.player_id, stage=stage,
                    seconds=time.monotonic()-start, emulated_frames=frames(c)-first, outcome=outcome)
                if write_key is None:
                    rows.append(row)
                else:
                    key = (context.get(), c.config.player_id)
                    aggregate = writes.setdefault(key, dict(row, seconds=0.0, emulated_frames=0, count=0))
                    aggregate["seconds"] += row["seconds"]
                    aggregate["emulated_frames"] += row["emulated_frames"]
                    aggregate["count"] += 1
                    if outcome != "ok":
                        aggregate["outcome"] = outcome
        return measured

    original_init = LiveCheckpointCoordinator.__init__
    def initialize(coord, companion, directory):
        original_init(coord, companion, directory)
        for name in ("_bind", "_prepare_ownership", "_read_flash"):
            setattr(coord, name, timer(companion, name[1:], getattr(coord, name)))
        coord.client.upload = timer(companion, "upload", coord.client.upload)
        command = coord._command
        timed_commands = {
            Opcode.BEGIN_EXPORT: timer(companion, "begin_export", command),
            Opcode.END: timer(companion, "end", command),
            Opcode.BEGIN_IMPORT: timer(companion, "begin_import", command),
            Opcode.COMMIT: timer(companion, "commit_import", command),
            Opcode.WRITE: timer(companion, "write_import", command, write_key=True),
        }
        async def dispatch(session, operation_id, revision, opcode, **kwargs):
            return await timed_commands.get(opcode, command)(session, operation_id, revision, opcode, **kwargs)
        coord._command = dispatch
        checkpoint, recover = coord._checkpoint, coord.recover
        async def attempt(method, function, **kwargs):
            identifier = str(uuid4())
            token = context.set(identifier)
            start, first = time.monotonic(), frames(companion)
            outcome = "ok"
            try:
                return await function(**kwargs)
            except BaseException as error:
                outcome = getattr(error, "code", type(error).__name__)
                raise
            finally:
                attempts.append(dict(attempt_id=identifier, player_id=companion.config.player_id,
                    method=method, expected_revision=kwargs.get("expected_revision"),
                    enroll=kwargs.get("enroll", False), seconds=time.monotonic()-start,
                    emulated_frames=frames(companion)-first, outcome=outcome))
                context.reset(token)
        async def checkpoint_attempt(**kwargs):
            return await attempt("checkpoint", checkpoint, **kwargs)
        async def recover_attempt():
            return await attempt("recover", recover)
        coord._checkpoint, coord.recover = checkpoint_attempt, recover_attempt

    try:
        with patch.object(LiveCheckpointCoordinator, "__init__", initialize), \
                patch.object(proof, "Pump", TrackPump), patch.object(proof, "PacedPump", TrackPacedPump):
            await proof.run(args)
    finally:
        rows.extend(writes.values())
        output = args.output.resolve()
        if output.exists():
            profile = dict(scope="production stage timings inside preserved official-core proof; purpose-paced60fps, not Windows frontend acceptance",
                wrapper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), proof_sha256=PROOF_SHA256,
                baseline_evidence_sha256=hashlib.sha256(baseline_bytes).hexdigest(), attempts=attempts, stages=rows)
            evidence_path = output / "evidence.json"
            if evidence_path.exists():
                evidence = json.loads(evidence_path.read_text())
                profile.update(passed=evidence["passed"], evidence_sha256=hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
                    baseline_rom_sha256=BASELINE_ROM, new_rom_sha256=evidence["rom_sha256"],
                    baseline_read_timings=[{k:r[k] for k in ("action", "seconds", "emulated_frames", "count")}
                        for r in baseline["reads"]], new_read_timings=[{k:r[k] for k in ("action", "seconds", "emulated_frames", "count")}
                        for r in evidence["reads"]])
            (output / "profile.json").write_text(json.dumps(profile, indent=2)+"\n")
            print(json.dumps(dict(profile=str(output / "profile.json"), passed=profile.get("passed"))), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rom", "elf", "manifest", "harness", "save-a", "save-b", "output", "baseline-evidence"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--bridge", type=Path, default=Path(__file__).parents[2] / "bridge/mgba.lua")
    parser.add_argument("--timing-label", choices=("development", "quiet"), default="quiet")
    parser.add_argument("--frame-rate", type=int, choices=(60,), default=60)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
