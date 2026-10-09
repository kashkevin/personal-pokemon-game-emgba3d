"""Bounded proof-driver tests; these do not execute a native game or GUI."""
import asyncio
import hashlib
from pathlib import Path
import struct
import sys
import unittest

SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts" / "windows-runtime")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
from qualify_menu_battle import (BATTLE_HEADER, BATTLE_SNAPSHOT_SIZE,
    decode_battle_snapshot, drive_battle_input, party_action)


SYMBOLS = {"Task_HandleChooseMonInput": (0x08001001, 100),
           "Task_HandleSelectionMenuInput": (0x08002000, 100),
           "Task_PrintAndWaitForText": (0x08003001, 100)}


def state(*, cursor=0, task="Task_HandleChooseMonInput", native=5):
    return dict(frame=90, state=native, count=2, cursor=cursor,
                active={SYMBOLS[task][0] & ~1})


class SnapshotTests(unittest.TestCase):
    def test_real_arm_task_stride_active_flag_thumb_pointer_and_party_bytes(self):
        tasks = bytearray(640)
        struct.pack_into("<I", tasks, 80, SYMBOLS["Task_HandleChooseMonInput"][0])
        tasks[84] = 1
        struct.pack_into("<I", tasks, 40, SYMBOLS["Task_PrintAndWaitForText"][0])
        party_menu = bytearray(20)
        party_menu[9] = 1
        party = bytes(range(200)) * 3
        raw = BATTLE_HEADER.pack(1234, 5, 2) + tasks + party_menu + party
        self.assertEqual(len(raw), BATTLE_SNAPSHOT_SIZE)
        value = decode_battle_snapshot(raw)
        self.assertEqual(value["active"], {0x08001000})
        self.assertEqual((value["frame"], value["state"], value["cursor"], value["count"]), (1234, 5, 1, 2))
        self.assertEqual(value["party_sha256"], hashlib.sha256(party).hexdigest())

    def test_partial_or_oversize_snapshot_and_invalid_count_refused(self):
        raw = BATTLE_HEADER.pack(12, 5, 2) + bytes(1260)
        for value in (raw[:-1], raw+b"x", BATTLE_HEADER.pack(12, 5, 7)+raw[BATTLE_HEADER.size:]):
            with self.subTest(length=len(value)), self.assertRaises(AssertionError):
                decode_battle_snapshot(value)

    def test_native_phase_and_pending_request_gate_party_keys(self):
        for phase in (0, 1, 2, 3, 4, 6, 7, 8, 9, 10):
            self.assertEqual(party_action(21, state(native=phase), SYMBOLS), "wait")
        self.assertEqual(party_action(17, state(), SYMBOLS), "confirm")
        self.assertEqual(party_action(21, state(), SYMBOLS), "next-party")
        self.assertEqual(party_action(21, state(task="Task_HandleSelectionMenuInput"), SYMBOLS), "confirm")
        self.assertEqual(party_action(21, state(task="Task_PrintAndWaitForText"), SYMBOLS), "dismiss")


class Probe:
    def __init__(self, states, stop=None):
        self.states, self.stop = iter(states), stop
        self.keys = []
        self.finished_presses = 0
    async def battle(self, **kwargs):
        return next(self.states)
    async def press(self, key, frames, release):
        self.keys.append((key, frames, release))
        if self.stop is not None:
            self.stop.set()
        await asyncio.sleep(0)  # Completion models the input's release ACK.
        self.finished_presses += 1
        return dict(frame=90)


class DriverTests(unittest.IsolatedAsyncioTestCase):
    async def drive(self, probe, views, stop=None):
        values = iter(views)
        async def view():
            return next(values)
        await asyncio.wait_for(drive_battle_input(probe, view, SYMBOLS, stop or asyncio.Event()), 1)

    async def test_forced_switch_moves_then_confirms_only_live_changed_slot(self):
        probe = Probe([state(cursor=0), state(cursor=1)])
        await self.drive(probe, [dict(state="executing", pending=21)]*2+[dict(state="closed", pending=None)])
        self.assertEqual(probe.keys, [(128, 12, 18), (1, 12, 18)])

    async def test_closure_during_cursor_move_does_not_send_confirm(self):
        probe = Probe([state(cursor=0), state(cursor=1)])
        await self.drive(probe, [dict(state="executing", pending=21),
            dict(state="closed", pending=None), dict(state="closed", pending=None)])
        self.assertEqual(probe.keys, [(128, 12, 18)])

    async def test_failed_switch_text_uses_b_then_stops_at_recovery(self):
        probe = Probe([state(task="Task_PrintAndWaitForText")])
        await self.drive(probe, [dict(state="executing", pending=21), dict(state="recovery_required", pending=21)])
        self.assertEqual(probe.keys, [(2, 12, 30)])

    async def test_stop_during_normal_pulse_waits_for_release_without_more_input(self):
        stop = asyncio.Event()
        probe = Probe([state()], stop)
        await self.drive(probe, [dict(state="executing", pending=17)], stop)
        self.assertEqual(probe.keys, [(1, 12, 18)])
        self.assertEqual(probe.finished_presses, 1)

    async def test_closed_room_sends_no_input_and_reads_no_native_state(self):
        probe = Probe([])
        await self.drive(probe, [dict(state="closed", pending=None)])
        self.assertEqual(probe.keys, [])


if __name__ == "__main__":
    unittest.main()
