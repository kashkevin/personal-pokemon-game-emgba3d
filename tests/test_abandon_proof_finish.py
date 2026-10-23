"""The interrupted-battle proof's wait for a battle's end (scripts/multiplayer/native_launcher_abandon_proof.py finish),
against stand-ins for the launchers and the host's battle rooms. Regression for windows-package run 138's ffa-exit: the
rematch free-for-all gave no result for 30 minutes and the record said only how long it had waited. A room the route
left without a result now ends the wait at once with the host's view of it (its state, error and diagnosis, each slot's
pending request and last command hop) and each player's launcher status and driver; the minute records and a timeout
carry the same view. The shared battle driver keeps what it last read and did (drive_battle_input's `seen`). The
knockout scenarios' check of the host's route journal (host_was_out, KNOWN_ISSUES MS-57) counts only the master's action
menus that carried battler 0's B_ACTION_NOTHING_FAINTED."""
from __future__ import annotations

import asyncio
import base64
from collections import deque
import json
from pathlib import Path
import struct
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from uuid import UUID
import zlib

ROOT = Path(__file__).resolve().parents[1]
for _path in (ROOT / "src", ROOT / "scripts" / "multiplayer", ROOT / "scripts" / "windows-runtime"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
import native_launcher_abandon_proof as proof  # noqa: E402
import native_launcher_battle_proof as harness_module  # noqa: E402
from emerald_multiplayer.native_battle import FFA_PHASE, Kind, NativeControl, NativeQuery, Opcode  # noqa: E402

BATTLE = "7a6b5c4d-0000-4000-8000-000000000001"
PLAYERS = ("p0", "p1", "p2", "p3")


def room(state, error=None):
    now = time.monotonic()
    hop = dict(dispatch=9, opcode=3, published=now - 12, delivered=now - 11.5, answered=None, status="published")
    return SimpleNamespace(state=state, error=error, battle=SimpleNamespace(players=list(PLAYERS)),
                           hops={"p2": deque([hop])},
                           route=SimpleNamespace(validator=SimpleNamespace(pending=[None, 17, 21, None])))


class Launcher:
    """One player's launcher session as the proof reads it (on_worker hands it to the operation)."""

    def __init__(self, server=None, code="battle_running"):
        self._server = server
        self.status = SimpleNamespace(code=code)
        self._game = SimpleNamespace(process=SimpleNamespace(returncode=None))
        self.can_save = code == "battle_finished"
        self._interaction = None


class Worker:
    def __init__(self, session):
        self._active_session = session
        self._loop = asyncio.get_running_loop()


class FinishTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.rooms = {BATTLE: room("executing")}
        server = SimpleNamespace(battle_execution=SimpleNamespace(rooms=self.rooms, directory=self.directory))
        self.launchers = [Launcher(server)] + [Launcher() for _ in range(3)]
        self.current = [Worker(launcher) for launcher in self.launchers]
        self.proof = proof.AbandonProof("ffa-exit", 0, 0, match_seconds=30)
        self.proof.harness = SimpleNamespace(host=SimpleNamespace(accounts=[SimpleNamespace(player_id=p)
                                                                            for p in PLAYERS]),
                                             names=["Host", "Friend 1", "Friend 2", "Friend 3"])
        self.records = []
        self.stops = {n: asyncio.Event() for n in range(4)}
        self.drivers = {n: asyncio.create_task(self.stops[n].wait()) for n in range(4)}
        for n in range(4):
            self.proof.seen[n] = dict(room="executing", pending=None, phase=5, action="confirm", presses=n,
                                      pressed=time.monotonic() - 3)

    def record(self, check, **fields):
        self.records.append(dict(check=check, **fields))

    async def finish(self):
        battles = {BATTLE: dict(battle_id=BATTLE, players=list(PLAYERS))}
        return await self.proof.finish(self.current, None, battles, range(4), self.stops, self.drivers, self.record,
                                       "rematch-free-for-all")

    async def test_a_room_left_without_a_result_ends_the_wait_at_once_with_its_diagnosis(self):
        self.rooms[BATTLE] = room("recovery_required", "execution_interrupted")
        (self.directory / (BATTLE + ".diagnosis.json")).write_text(json.dumps(dict(
            reason="execution_interrupted", error="TimeoutError: the host core's deadline", code="7",
            traceback=[f"line {n}\n" for n in range(12)], players=[])))
        started = time.monotonic()
        with self.assertRaisesRegex(AssertionError, "stopped without a result"):
            await self.finish()
        self.assertLess(time.monotonic() - started, 5)
        stopped = [r for r in self.records if r["check"] == "rematch-free-for-all-stopped"]
        self.assertEqual(len(stopped), 1)
        view = stopped[0]["rooms"][BATTLE[:8]]
        self.assertEqual((view["state"], view["error"]), ("recovery_required", "execution_interrupted"))
        self.assertEqual(view["diagnosis"]["error"], "TimeoutError: the host core's deadline")
        self.assertEqual(view["diagnosis"]["traceback"], [f"line {n}\n" for n in range(6, 12)])
        self.assertEqual([slot["pending"] for slot in view["slots"]], [None, 17, 21, None])
        self.assertEqual(view["slots"][2]["hop"]["opcode"], 3)
        self.assertEqual(view["slots"][2]["hop"]["answered"], None)
        self.assertGreaterEqual(view["slots"][2]["hop"]["published"], 12)
        self.assertIsNone(view["slots"][0]["hop"])
        player = stopped[0]["players"]["Friend 2"]
        self.assertEqual((player["code"], player["action"], player["presses"]), ("battle_running", "confirm", 2))
        self.assertGreaterEqual(player["idle"], 3)
        self.assertTrue(all(stop.is_set() for stop in self.stops.values()))
        self.assertTrue(all(driver.done() for driver in self.drivers.values()))

    async def test_the_minute_record_and_a_timeout_carry_the_rooms_and_the_players(self):
        self.proof.match_seconds = .6
        with self.assertRaises(TimeoutError):
            await self.finish()
        progress = [r for r in self.records if r["check"] == "rematch-free-for-all-progress"]
        timed_out = [r for r in self.records if r["check"] == "rematch-free-for-all-timed-out"]
        self.assertEqual(len(progress), 1)
        self.assertEqual(len(timed_out), 1)
        for value in (progress[0], timed_out[0]):
            self.assertEqual(value["rooms"][BATTLE[:8]]["state"], "executing")
            self.assertNotIn("diagnosis", value["rooms"][BATTLE[:8]])
            self.assertEqual(sorted(value["players"]), ["Friend 1", "Friend 2", "Friend 3", "Host"])
        self.assertTrue(all(stop.is_set() for stop in self.stops.values()))

    async def test_a_closed_battle_whose_launcher_never_finishes_it_ends_the_wait(self):
        self.rooms[BATTLE] = room("closed")
        for launcher in self.launchers[:3]:
            launcher.status.code, launcher.can_save = "battle_finished", True
        old, proof.CLOSED_WAIT = proof.CLOSED_WAIT, .4
        try:
            with self.assertRaisesRegex(AssertionError, "closed but not every launcher finished"):
                await self.finish()
        finally:
            proof.CLOSED_WAIT = old
        unfinished = [r for r in self.records if r["check"] == "rematch-free-for-all-closed-unfinished"]
        self.assertEqual(len(unfinished), 1)
        self.assertEqual(unfinished[0]["players"]["Friend 3"]["code"], "battle_running")
        self.assertEqual(unfinished[0]["players"]["Host"]["code"], "battle_finished")
        self.assertEqual(unfinished[0]["rooms"][BATTLE[:8]]["state"], "closed")

    async def test_a_battle_that_ends_gives_its_result(self):
        for launcher in self.launchers:
            launcher.status.code, launcher.can_save = "battle_finished", True
        self.rooms[BATTLE] = room("closed")
        fate = dict(reservation="closed", result=dict(outcome=1, players=list(PLAYERS)), ffa_result=None)

        def host_fate(battle_id):
            async def read(s):
                return fate
            return read
        self.proof.host_fate = host_fate
        results = await self.finish()
        self.assertEqual(results, {BATTLE: fate["result"]})
        self.assertEqual([r["check"] for r in self.records], ["rematch-free-for-all-result"])


class Probe:
    def __init__(self, states):
        self.states, self.keys = iter(states), []

    async def battle(self):
        return next(self.states)

    async def press(self, key, frames=None, release=None):
        self.keys.append(key)


class DriverSeenTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_driver_keeps_what_it_last_read_and_did(self):
        symbols = {"Task_HandleChooseMonInput": (0x08001001, 4), "Task_HandleSelectionMenuInput": (0x08002000, 4),
                   "Task_PrintAndWaitForText": (0x08003001, 4)}
        views = iter([dict(state="executing", pending=17), dict(state="executing", pending=17),
                      dict(state="recovery_required", pending=17)])

        async def view():
            return next(views)
        probe = Probe([dict(state=5, active=frozenset(), cursor=0, count=1)] * 2)
        seen = {}
        await asyncio.wait_for(harness_module.drive_battle_input(probe, view, symbols, asyncio.Event(), seen), 1)
        self.assertEqual(probe.keys, [1, 1])
        self.assertEqual((seen["room"], seen["pending"], seen["phase"], seen["action"], seen["presses"]),
                         ("recovery_required", 17, 5, "confirm", 2))
        self.assertLessEqual(seen["pressed"], time.monotonic())


def journal_row(kind, opcode, data=b"", sequence=1, block=1):
    control = NativeControl(1, 1, BATTLE, sequence, opcode, block_sequence=block, total_size=16, phase=FFA_PHASE,
                            kind=Kind.CONTROLLER, data=data)
    return json.dumps(dict(value=dict(kind=kind, actor=PLAYERS[0], dispatch_id=sequence,
                                      control_b64=base64.b64encode(control.pack()).decode())))


def peek_row(block, outbound, sequence):
    # KNOWN_ISSUES MS-62: the observed router's journal row for a launcher's look at its core (PEEK): the query,
    # held with an outbound block of one chunk, then that block's bytes.
    query = struct.pack("<I16sBBBB10I", 5, UUID(BATTLE).bytes, 4, 0, FFA_PHASE, 0, 1, outbound, Kind.CONTROLLER,
                        len(block), zlib.crc32(block), 0, 0, 600, 0, 0)
    control = NativeControl(1, 1, BATTLE, sequence, Opcode.PEEK, phase=FFA_PHASE, data=query + block)
    return json.dumps(dict(value=dict(kind="observation", actor=PLAYERS[0], dispatch_id=sequence,
                                      control_b64=base64.b64encode(control.pack()).decode())))


class HostOutTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = Path(tempfile.mkdtemp())
        server = SimpleNamespace(battle_execution=SimpleNamespace(rooms={}, directory=self.directory))
        self.current = [Worker(Launcher(server))]
        self.proof = proof.AbandonProof("ffa-knockout", 0, 0, match_seconds=30)
        self.records = []

    def record(self, check, **fields):
        self.records.append(dict(check=check, **fields))

    def journal(self, *rows):
        header = json.dumps(dict(value=dict(kind="header", value=dict(battle_id=BATTLE, players=list(PLAYERS)))))
        (self.directory / (BATTLE + ".events.jsonl")).write_text("\n".join((header,) + rows) + "\n")

    async def test_only_the_masters_action_menus_with_nothing_fainted_count(self):
        out = bytes.fromhex("0001020308000502" "110d0000" "00000000")      # L knockout-fixed-1's block
        self.journal(
            journal_row("command", Opcode.READ_OUT, sequence=1),            # a command carries no block
            journal_row("response", Opcode.READ_OUT, out, sequence=1, block=1),
            journal_row("response", Opcode.READ_OUT, out[:9] + b"\x00" + out[10:], sequence=2, block=2),  # USE_MOVE
            journal_row("response", Opcode.READ_OUT, b"\x01" + out[1:8] + bytes((32, 13)) + out[10:], sequence=3,
                        block=3),
            journal_row("response", Opcode.READ_OUT, out, sequence=4, block=4))
        await self.proof.host_was_out(self.current, BATTLE, self.record, "knockout-2v2")
        self.assertEqual(self.records, [dict(check="knockout-2v2-host-out", menus=2)])

    async def test_each_block_counts_once_read_out_or_observed(self):
        # The observed router (journal v4/v5) takes small blocks from its launchers' looks at their cores (PEEK),
        # perhaps the same block more than once, and reads out the rest: a block counts once by its sequence
        # (L multiko-2 found none when only read-out blocks counted).
        out = bytes.fromhex("0001020308000502" "110d0000" "00000000")
        self.journal(
            peek_row(out, outbound=7, sequence=1),
            peek_row(out, outbound=7, sequence=2),                          # block 7 observed again
            peek_row(out[:9] + b"\x00" + out[10:], outbound=8, sequence=3),  # B_ACTION_USE_MOVE
            peek_row(out, outbound=9, sequence=4),
            journal_row("response", Opcode.READ_OUT, out, sequence=5, block=9),   # block 9 read out as well
            journal_row("response", Opcode.READ_OUT, out, sequence=6, block=10))
        await self.proof.host_was_out(self.current, BATTLE, self.record, "knockout-2v2")
        self.assertEqual(self.records, [dict(check="knockout-2v2-host-out", menus=3)])

    def test_the_knockout_sources_have_their_own_party_profile(self):
        self.assertEqual(proof.party_counts("ffa-knockout"), (1, 2, 2, 4))
        self.assertEqual(proof.party_counts("multi-knockout"), (1, 2, 2, 4))
        for scenario in ("pairs-crash", "multi-network", "ffa-host-crash", "ffa-exit"):
            self.assertEqual(proof.party_counts(scenario), (1, 1, 1, 1))

    def test_the_knockout_2v2_puts_the_host_at_battler_0_when_any_id_sorts_after_it(self):
        self.assertEqual(proof.knockout_teams(["b", "a", "c", "d"]), (((0, 2), (1, 3)), True))
        self.assertEqual(proof.knockout_teams(["a", "b", "c", "d"]), (((0, 1), (2, 3)), True))
        self.assertEqual(proof.knockout_teams(["c", "d", "a", "b"]), (((0, 1), (2, 3)), True))
        self.assertEqual(proof.knockout_teams(["d", "a", "b", "c"]), (((0, 1), (2, 3)), False))
        for ids in (["b", "a", "c", "d"], ["c", "a", "b", "d"], ["c", "d", "a", "b"]):
            (team, _), first = proof.knockout_teams(ids)
            self.assertTrue(first)
            self.assertEqual(min(team, key=lambda slot: ids[slot]), 0)    # battle_desk.invite_multi sorts each team

    async def test_a_battle_whose_host_was_never_out_fails_the_check(self):
        out = bytes.fromhex("0001020308000502" "11000000" "00000000")
        self.journal(journal_row("response", Opcode.READ_OUT, out))
        with self.assertRaisesRegex(AssertionError, "never out"):
            await self.proof.host_was_out(self.current, BATTLE, self.record, "knockout-free-for-all")
        self.assertEqual(self.records, [])


if __name__ == "__main__":
    unittest.main()
