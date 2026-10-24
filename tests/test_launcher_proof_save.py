"""The launcher proofs' closing save clicks again while the game is busy, as a player would.

windows-package run 211's trade-lag proof finished both trades and then failed on its own Save: the launcher refused it
with "busy: checkpoint lock, live save" while the second trade's settlement still held the game's checkpoint (the
launcher never waits behind another transaction; a later click may retry). Only that refusal is retried."""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "src", ROOT / "scripts" / "multiplayer", ROOT / "scripts" / "windows-runtime"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
import native_launcher_battle_proof as harness  # noqa: E402


class FakeSession:
    def __init__(self, refusals, error="busy: checkpoint lock, live save", revision=7):
        self.refusals, self.error, self.calls = refusals, error, 0
        self.status = SimpleNamespace(code="running", revision=revision - 1)
        self.last_save_error = None
        self.revision = revision

    async def save(self):
        self.calls += 1
        if self.calls <= self.refusals:
            self.status.code, self.last_save_error = "save_not_ready", self.error
            return False
        self.status.code, self.status.revision, self.last_save_error = "saved", self.revision, None
        return True


class WorkerLoop:
    """The launcher worker's own event loop, on its own thread (on_worker runs the save there)."""

    def __init__(self, session):
        self._loop = asyncio.new_event_loop()
        self._active_session = session
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def close(self):
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(5)
        self._loop.close()


class ClosingSaveTests(unittest.TestCase):
    def save(self, session, revision=7):
        worker = WorkerLoop(session)
        self.addCleanup(worker.close)
        proof = object.__new__(harness.LauncherHarness)
        asyncio.run(proof.save(SimpleNamespace(worker=worker), revision))

    def test_a_busy_game_is_asked_again_until_it_saves(self):
        session = FakeSession(refusals=2)
        self.save(session)
        self.assertEqual(session.calls, 3)
        self.assertEqual(session.status.revision, 7)

    def test_any_other_refusal_fails_at_once(self):
        session = FakeSession(refusals=5, error="LiveSaveError save_failed: the game refused")
        with self.assertRaises(AssertionError) as caught:
            self.save(session)
        self.assertEqual(session.calls, 1)
        self.assertIn("manual save did not finish", str(caught.exception))
        self.assertIn("save_failed", str(caught.exception))

    def test_a_save_with_another_revision_still_fails(self):
        with self.assertRaises(AssertionError) as caught:
            self.save(FakeSession(refusals=0, revision=8), revision=7)
        self.assertIn("manual save revision differs", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
