"""KNOWN_ISSUES MS-165's update of 2026-11-06 (Windows run 349): a game stopped for a few seconds while its launcher
held no host command. The battle observer (battle_observer.py) had a PEEK out to the game then; with the companion's own
5 s the PEEK was given up during the stop, the host command handed over meanwhile went to the stopped game, and the game
held two commands when it ran again: its bridge stops the link on a second outstanding battle command (the engine's
mp_bridge.c), and the battle was held for recovery for both players. A PEEK now waits as long as a host command
(battle_session.GAME_ANSWER_SECONDS), so the host command goes to the game after the PEEK's answer.

The game here is a model of its end of the battle mailbox, the times scaled down: one command at a time, a second one
written while the first is unanswered recorded as the link stopping, and every command answered when the game runs.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from emerald_multiplayer import battle_session  # noqa: E402
from emerald_multiplayer.battle_observer import BattleObserver  # noqa: E402
from emerald_multiplayer.native_battle import PHASE, NativeControl, Opcode  # noqa: E402

COMPANION_OWN_SECONDS = .2   # the companion's own wait (5 s), scaled down
GAME_ANSWER_SECONDS = 1.0    # battle_session.GAME_ANSWER_SECONDS (15 s), scaled down
STOP_SECONDS = .6            # a 10 s stop, scaled down: longer than the companion's own wait, shorter than the answer's


class StoppedGame:
    """The game's end of the battle mailbox, stopped until `resumes` (loop time)."""

    def __init__(self, loop, resumes):
        self.loop, self.resumes = loop, resumes
        self.unanswered = None
        self.link_stopped = None
        self.written = []    # (loop time, opcode name)
        self.answered = []   # (loop time, opcode name)

    def write(self, control):
        name = Opcode(control.opcode).name
        self.written.append((self.loop.time(), name))
        if self.unanswered is not None and self.link_stopped is None:
            self.link_stopped = f"{name} written while {Opcode(self.unanswered.opcode).name} was unanswered"
        self.unanswered = control
        future = self.loop.create_future()

        def answer():
            if self.unanswered is control:
                self.unanswered = None
            self.answered.append((self.loop.time(), name))
            if not future.done():
                # a PEEK's answer the observer skips (status not OK: nothing to report to the host here)
                future.set_result(SimpleNamespace(status=1 if control.opcode == Opcode.PEEK else 0,
                                                  validate_response=lambda command: None))
        self.loop.call_at(max(self.resumes, self.loop.time()), answer)
        return future


class Companion:
    """Companion.battle_rpc's waiting: the command goes to the game; given up after `timeout`, its default the
    companion's own. A command given up stays with the game until it runs and answers it."""

    def __init__(self, game):
        self.game = game
        self.config = SimpleNamespace(battle_peek_abi_version=1)
        self.waits = []   # (opcode name, timeout)

    async def battle_rpc(self, control, *, timeout=COMPANION_OWN_SECONDS):
        self.waits.append((Opcode(control.opcode).name, timeout))
        return await asyncio.wait_for(asyncio.shield(self.game.write(control)), timeout)

    async def battle_challenge_rpc(self, operation, **fields):
        raise AssertionError("no report reaches the host in this test")


class ObserverStallTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        saved = battle_session.GAME_ANSWER_SECONDS
        battle_session.GAME_ANSWER_SECONDS = GAME_ANSWER_SECONDS
        self.addCleanup(setattr, battle_session, "GAME_ANSWER_SECONDS", saved)
        self.loop = asyncio.get_running_loop()
        self.battle = str(uuid.uuid4())

    async def observing(self, game):
        """An observer running on the game after the core's last accepted command (sequence 5)."""
        companion = Companion(game)
        observer = BattleObserver(companion, self.battle, 1, 100, 0, PHASE)
        observer.executed(NativeControl(100, 1, self.battle, 5, Opcode.DELIVER), SimpleNamespace(status=0))
        self.addAsyncCleanup(observer.stop)
        return companion, observer

    async def until(self, condition, observer):
        """Wait for condition() (the observer's task must still run)."""
        async def poll():
            while not condition():
                if observer.task is not None and observer.task.done():
                    observer.task.result()   # its exception, if it died
                    self.fail("the observer stopped")
                await asyncio.sleep(.001)
        await asyncio.wait_for(poll(), 5)

    async def host_command(self, companion, observer):
        """The host hands the launcher DELIVER 6 (battle_session: holding, then the command under the lock)."""
        command = NativeControl(100, 1, self.battle, 6, Opcode.DELIVER)
        observer.holding(command)
        response = await battle_session.execute_command(companion, command, observer)
        observer.executed(command, response)
        return response

    async def test_a_host_command_during_a_stop_waits_for_the_peeks_answer(self):
        # the game stops right after answering its last command: the observer's PEEK goes to the stopped game
        game = StoppedGame(self.loop, self.loop.time() + STOP_SECONDS)
        companion, observer = await self.observing(game)
        await self.until(lambda: game.unanswered is not None, observer)
        self.assertEqual(Opcode(game.unanswered.opcode), Opcode.PEEK)
        # the other player's block comes 0.1 s into the stop (as in run 349: 0.1-0.25 s)
        await asyncio.sleep(.1)
        response = await asyncio.wait_for(self.host_command(companion, observer), 5)
        self.assertEqual(response.status, 0)
        self.assertIsNone(game.link_stopped)
        peek_answered = next(t for t, name in game.answered if name == "PEEK")
        deliver_written = next(t for t, name in game.written if name == "DELIVER")
        self.assertGreaterEqual(deliver_written, peek_answered)   # one command at a time on the game
        self.assertIn(("PEEK", GAME_ANSWER_SECONDS), companion.waits)
        self.assertIn(("DELIVER", GAME_ANSWER_SECONDS), companion.waits)

    async def test_the_peek_waits_as_long_as_a_host_command(self):
        # read at each PEEK: the proof's --game-answer-seconds governs both
        battle_session.GAME_ANSWER_SECONDS = 2.5
        game = StoppedGame(self.loop, self.loop.time())
        companion, observer = await self.observing(game)
        await self.until(lambda: companion.waits, observer)
        self.assertEqual(companion.waits[0], ("PEEK", 2.5))

    async def test_a_stop_longer_than_the_answers_wait_is_still_refused_by_the_game(self):
        # past GAME_ANSWER_SECONDS the PEEK is given up and the command reaches the stopped game: the battle is held
        # for recovery, as MS-165 decided for a game stopped that long (the host's route waits 20 s for an answer)
        battle_session.GAME_ANSWER_SECONDS = .3
        game = StoppedGame(self.loop, self.loop.time() + 1.2)
        companion, observer = await self.observing(game)
        await self.until(lambda: game.unanswered is not None, observer)
        await asyncio.sleep(.05)
        with self.assertRaises(asyncio.TimeoutError):
            await self.host_command(companion, observer)
        self.assertEqual(game.link_stopped, "DELIVER written while PEEK was unanswered")


if __name__ == "__main__":
    unittest.main()
