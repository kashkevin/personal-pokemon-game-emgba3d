"""A world server's process killed outright (a crashed launcher, End task in Task Manager) while a player's save is
uploaded or committed: after the restart every save the server acknowledged is there byte for byte, nothing newer
than what was sent, and the store's integrity check passes. Six rounds against a real server process: three killed
during an upload, three right after a commit was sent (before or after it lands). A process kill, not a power cut:
what the process had handed the operating system is still written. The longer randomized soak of the same invariants is
in TEST_LEDGER (2026-11-05)."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import random
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

from emerald_multiplayer.companion import BASELINE_RULESET, verify_rom_manifest
from emerald_multiplayer.flash import LAYOUT_ID
from emerald_multiplayer.protocol import CHECKPOINT_CHUNK_BYTES
from emerald_multiplayer.storage import CheckpointStore

from test_checkpoint_server import Client, fingerprint
from test_companion import make_files
from test_flash import make_flash


SOURCE = Path(__file__).resolve().parents[1] / "src"
# The interpreter itself. A virtual environment's python.exe on Windows is a launcher that runs the interpreter as a
# process of its own: killing the launcher left the server holding the database while the test opened it (Windows run
# 294: "disk I/O error"). The server is given this process's import path instead of the environment's.
INTERPRETER = getattr(sys, "_base_executable", None) or sys.executable

# The world server on the store at argv[1] until its process is killed. A script of its own (python -c), not a
# multiprocessing child: that one re-runs the parent's main script, which fails when the tests were started from a
# script on standard input. It names its own process, which must be the one the test kills.
SERVER = """
import asyncio, json, os, sys
sys.path[:0] = json.loads(sys.argv[3])
from emerald_multiplayer.companion import BASELINE_RULESET
from emerald_multiplayer.flash import LAYOUT_ID
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.storage import CheckpointStore

async def main(path, build):
    store = CheckpointStore(path, build, BASELINE_RULESET, LAYOUT_ID)
    server = WorldServer(ServerConfig(build, BASELINE_RULESET, heartbeat_interval=0.5, idle_timeout=5.0), store=store)
    await server.start(port=0)
    print("ready", server.address[1], os.getpid(), flush=True)
    await asyncio.Event().wait()

asyncio.run(main(sys.argv[1], sys.argv[2]))
"""


class ServerKilledMidSaveTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        rom, manifest = make_files(self.temp.name)
        self.build = verify_rom_manifest(rom, manifest)[0]
        self.path = Path(self.temp.name) / "world.sqlite3"
        store = CheckpointStore(self.path, self.build, BASELINE_RULESET, LAYOUT_ID)
        self.owner = store.create_player("Player A")
        store.close()
        self.processes = []

    async def asyncTearDown(self):
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            process.wait(10)
            process.stdout.close()
        self.temp.cleanup()

    async def start_server(self):
        log = Path(self.temp.name) / f"server-{len(self.processes)}.log"
        with open(log, "wb") as errors:
            process = subprocess.Popen([INTERPRETER, "-c", SERVER, str(self.path), self.build,
                                        json.dumps([str(SOURCE), *sys.path])],
                                       stdout=subprocess.PIPE, stderr=errors, text=True)
        self.processes.append(process)
        try:
            line = await asyncio.wait_for(asyncio.to_thread(process.stdout.readline), 30)
        except asyncio.TimeoutError:
            line = ""
        words = line.split()
        self.assertTrue(len(words) == 3 and words[0] == "ready",
                        f"the server process did not start: {line!r} {log.read_text(errors='replace')[-2000:]}")
        self.assertEqual(int(words[2]), process.pid, "the process the test would kill is not the server's")
        client, welcome = await Client.connect(("127.0.0.1", int(words[1])), self.owner, self.build)
        self.assertEqual(welcome["type"], "welcome")
        return process, client

    async def stage(self, client, payload, revision):
        upload_id = str(uuid.uuid4())
        values = fingerprint(payload, revision)
        result = await client.rpc("begin", request_id=upload_id, **values)
        self.assertEqual(result["type"], "checkpoint_result", result)
        for offset in range(result["next_offset"], len(payload), CHECKPOINT_CHUNK_BYTES):
            result = await client.rpc("chunk", upload_id=upload_id, offset=offset, data_b64=base64.b64encode(
                payload[offset:offset + CHECKPOINT_CHUNK_BYTES]).decode("ascii"))
            self.assertEqual(result["type"], "checkpoint_result", result)
        return upload_id, values

    async def upload(self, client, payload, revision):
        upload_id, values = await self.stage(client, payload, revision)
        result = await client.rpc("commit", upload_id=upload_id, **values)
        self.assertEqual(result["type"], "checkpoint_result", result)
        return result["checkpoint"]["revision"]

    def latest_after_restart(self, acknowledged, sent):
        """The store as the next start opens it: whole, every acknowledged save in it, nothing newer than sent."""
        store = CheckpointStore(self.path, self.build, BASELINE_RULESET, LAYOUT_ID)
        try:
            store.integrity_check()
            store.begin_server_boot()
            lease = store.acquire_lease(self.owner.player_id, self.owner.credential)
            latest = store.read_checkpoint(self.owner.player_id, lease)
            revision = latest.revision if latest is not None else 0
            self.assertGreaterEqual(revision, max(acknowledged, default=0))
            self.assertLessEqual(revision, max(sent, default=0))
            for kept, digest in acknowledged.items():
                checkpoint = store.read_checkpoint(self.owner.player_id, lease, revision=kept)
                self.assertIsNotNone(checkpoint, kept)
                self.assertEqual(hashlib.sha256(checkpoint.payload).hexdigest(), digest)
            if revision:
                self.assertEqual(hashlib.sha256(latest.payload).hexdigest(), sent[revision])
            return revision
        finally:
            store.close()

    async def test_every_acknowledged_save_survives_the_server_killed_mid_upload_or_commit(self):
        rng = random.Random(5)
        acknowledged, sent = {}, {}
        revision = 0
        for round_ in range(6):
            process, client = await self.start_server()
            try:
                for _ in range(rng.randint(0, 2)):
                    payload = make_flash(counter=revision + 1)
                    sent[revision + 1] = hashlib.sha256(payload).hexdigest()
                    revision = await self.upload(client, payload, revision)
                    acknowledged[revision] = sent[revision]
                payload = make_flash(counter=revision + 1)
                sent[revision + 1] = hashlib.sha256(payload).hexdigest()
                if round_ % 2 == 0:
                    # killed somewhere in an upload: its begin, a chunk or its commit
                    task = asyncio.ensure_future(self.upload(client, payload, revision))
                    await asyncio.sleep(rng.uniform(0.0, 0.06))
                    process.kill()
                    try:
                        await task
                    except Exception:  # noqa: BLE001 - the server is gone; the store says what was kept
                        pass
                else:
                    # killed right after the commit was sent: before it lands or after, its answer lost
                    upload_id, values = await self.stage(client, payload, revision)
                    await client.send(dict(type="checkpoint_commit", session_epoch=client.epoch,
                                           request_id=str(uuid.uuid4()), upload_id=upload_id, **values))
                    await asyncio.sleep(rng.uniform(0.0, 0.01))
                    process.kill()
                process.wait(10)
            finally:
                try:
                    await client.close()
                except OSError:
                    pass
            latest = self.latest_after_restart(acknowledged, sent)
            if latest > revision:      # a commit that landed though the kill cut off its answer
                acknowledged[latest] = sent[latest]
            revision = latest
        self.assertGreater(len(acknowledged), 0)
        self.latest_after_restart(acknowledged, sent)


if __name__ == "__main__":
    unittest.main()
