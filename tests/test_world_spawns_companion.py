"""Companion shared-spawn path (Phase 3): host spawn views -> EMS1 inbound
records ('n'), and the native game's claim/result/release actions ('g') ->
host requests. Real TCP host, binary fake bridge (as test_world_companion)."""
from __future__ import annotations

import asyncio
import struct
import unittest

from emerald_multiplayer.bridge_protocol import read_packet
from emerald_multiplayer.spawn_mailbox import (
    ACTION_CLAIM, ACTION_RELEASE, ACTION_RESULT, FLAG_ENABLED, SLOT_BUSY, SLOT_MINE, SLOT_SHINY,
    SPAWN_INBOUND_SIZE, SPAWN_MAX_SLOTS, SpawnAction, SpawnInbound, SpawnLocal, SpawnMailboxError,
    SpawnSlotView, capability_packet,
)
from emerald_multiplayer.world_mailbox import WorldState
from test_companion import make_pose, wait_until
import test_world_companion as world_companion
from test_world_companion import local_record


def inbound_slots(data):
    flags, ack, group, number, count, _ = struct.unpack_from("<IIBBBB", data, 0)
    slots = []
    for i in range(count):
        spawn_id, personality, species, level, sflags, x, y, facing, move_seq, _ = \
            struct.unpack_from("<IIHBBhhBBH", data, 12 + i * 20)
        slots.append(dict(spawn_id=spawn_id, personality=personality, species=species, level=level,
                          flags=sflags, x=x, y=y, facing=facing, move_seq=move_seq))
    return flags, ack, (group, number), slots


class SpawnMailboxCodecTests(unittest.TestCase):
    def test_capability_and_sizes_match_the_c_header(self):
        self.assertEqual(capability_packet(), b"w" + struct.pack("<HHHH", 1, 12, 384, 20))
        self.assertEqual(len(SpawnLocal().pack()), 116)
        self.assertEqual(len(SpawnInbound().pack()), SPAWN_INBOUND_SIZE)

    def test_local_record_round_trip_and_bounds(self):
        local = SpawnLocal(SpawnAction(7, ACTION_RESULT, 1, 263, 99, 0, 16), 0, 16, 3,
                           ((99, 10, 12), (100, 11, 12)))
        self.assertEqual(SpawnLocal.unpack(local.pack()), local)
        with self.assertRaises(SpawnMailboxError):
            SpawnAction(1, ACTION_CLAIM, 2, 0, 5)  # only results carry an outcome
        with self.assertRaises(SpawnMailboxError):
            SpawnLocal(shown=tuple((i + 1, 0, 0) for i in range(SPAWN_MAX_SLOTS + 1)))
        bad = bytearray(local.pack())
        bad[16 + 3] = 13  # a shown count above twelve
        with self.assertRaises(SpawnMailboxError):
            SpawnLocal.unpack(bytes(bad))

    def test_inbound_packs_flags_per_viewer(self):
        view = {"map_group": 0, "map_number": 16, "shared": True, "slots": [
            {"spawn_id": 5, "species": 263, "level": 3, "personality": 0xABCDEF01, "shiny": True, "form": 0,
             "kind": "normal", "x": 10, "y": 7, "facing": 2, "move_seq": 4, "mine": True, "busy": False,
             "fresh": False, "seconds_left": 100}]}
        data = SpawnInbound.from_view(view, enabled=True, action_ack=9).pack()
        flags, ack, where, slots = inbound_slots(data)
        self.assertEqual((flags, ack, where), (FLAG_ENABLED, 9, (0, 16)))
        self.assertEqual(slots[0]["flags"], SLOT_SHINY | SLOT_MINE)
        self.assertEqual((slots[0]["personality"], slots[0]["x"], slots[0]["y"], slots[0]["facing"]),
                         (0xABCDEF01, 10, 7, 2))
        self.assertEqual(SpawnInbound.from_view(view, enabled=False, action_ack=9).pack()[:4], bytes(4))
        with self.assertRaises(SpawnMailboxError):
            SpawnSlotView(1, 263, 3, 0, SLOT_MINE | SLOT_BUSY, 0, 0, 1, 0)

    def test_a_map_the_host_does_not_share_is_not_enabled(self):
        # The Safari Zone (or a map without land habitat): the game keeps its
        # own encounters there, as offline; the action ack still flows.
        view = {"map_group": 26, "map_number": 0, "shared": False, "slots": []}
        inbound = SpawnInbound.from_view(view, enabled=True, action_ack=4)
        self.assertFalse(inbound.enabled)
        flags, ack, _, slots = inbound_slots(inbound.pack())
        self.assertEqual((flags, ack, slots), (0, 4, []))


class SpawnCompanionTests(unittest.IsolatedAsyncioTestCase):
    # The same real host and two companions as test_world_companion (without
    # re-running its tests here).
    asyncSetUp = world_companion.WorldCompanionTests.asyncSetUp
    asyncTearDown = world_companion.WorldCompanionTests.asyncTearDown

    async def spawn_frame(self, index, predicate=lambda data: True, timeout=4):
        bridge = self.bridges[index]
        async with asyncio.timeout(timeout):
            while True:
                packet = await read_packet(bridge.reader)
                if packet is None:
                    raise ConnectionError("bridge closed")
                if packet[:1] == b"n":
                    self.assertEqual(len(packet), 1 + SPAWN_INBOUND_SIZE)
                    if predicate(packet[1:]):
                        return packet[1:]

    def spot(self):
        tiles = self.server.shared_world.spawn_director.habitat("0.16")
        xs = sorted({x for x, _ in tiles})
        ys = sorted({y for _, y in tiles})
        return xs[len(xs) // 2], ys[len(ys) // 2]

    async def on_route101(self, index, x, y, weather=3):
        await self.bridges[index].send(capability_packet())
        await self.bridges[index].send(local_record(WorldState()))
        await self.bridges[index].send(b"g" + SpawnLocal(map_group=0, map_number=16, weather=weather).pack())
        await self.bridges[index].send(b"P" + make_pose(frame=x + 1000 * y, x=x, y=y, map_number=16,
                                                        elevation=3).pack())
        player = self.companions[index].config.player_id
        await wait_until(lambda: (self.server.sessions[player].presence or {}).get("x") == x, timeout=3)

    def tick_spawns(self):
        world = self.server.shared_world
        world.spawn_director._last_update = float("-inf")
        world.tick_spawns({pid: s.presence for pid, s in self.server.sessions.items()})
        self.server._broadcast_world()

    async def test_both_games_receive_the_same_pokemon_and_one_claim_wins(self):
        x, y = self.spot()
        await self.on_route101(0, x, y)
        await self.on_route101(1, x + 1, y)
        player0 = self.companions[0].config.player_id
        self.assertEqual(self.server.sessions[player0].presence["weather"], 3)
        for _ in range(4):
            self.tick_spawns()
        first = await self.spawn_frame(0, lambda d: len(inbound_slots(d)[3]) >= 3)
        flags, _, where, slots0 = inbound_slots(first)
        self.assertEqual((flags, where), (FLAG_ENABLED, (0, 16)))
        ids = [s["spawn_id"] for s in slots0]
        second = await self.spawn_frame(1, lambda d: [s["spawn_id"] for s in inbound_slots(d)[3]] == ids)
        same = lambda slots: [{k: v for k, v in s.items() if k != "flags"} for s in slots]
        self.assertEqual(same(inbound_slots(second)[3]), same(slots0))
        target = slots0[0]
        # Both games post a claim in the same moment.
        for index in (0, 1):
            await self.bridges[index].send(b"g" + SpawnLocal(SpawnAction(1, ACTION_CLAIM, 0, target["species"],
                                                                         target["spawn_id"], 0, 16), 0, 16, 3).pack())
        mine = lambda d: any(s["spawn_id"] == target["spawn_id"] and s["flags"] & SLOT_MINE for s in inbound_slots(d)[3])
        busy = lambda d: any(s["spawn_id"] == target["spawn_id"] and s["flags"] & SLOT_BUSY for s in inbound_slots(d)[3])
        frames = await asyncio.gather(self.spawn_frame(0, lambda d: inbound_slots(d)[1] == 1 and (mine(d) or busy(d))),
                                      self.spawn_frame(1, lambda d: inbound_slots(d)[1] == 1 and (mine(d) or busy(d))))
        winners = [index for index, frame in enumerate(frames) if mine(frame)]
        self.assertEqual(len(winners), 1)
        winner = winners[0]
        self.assertTrue(busy(frames[1 - winner]))
        # The winner reports the catch; the Pokemon leaves both games.
        await self.bridges[winner].send(b"g" + SpawnLocal(SpawnAction(2, ACTION_RESULT, 1, target["species"],
                                                                      target["spawn_id"], 0, 16), 0, 16, 3).pack())
        gone = lambda d: all(s["spawn_id"] != target["spawn_id"] for s in inbound_slots(d)[3])
        await self.spawn_frame(winner, lambda d: inbound_slots(d)[1] == 2 and gone(d))
        await self.spawn_frame(1 - winner, gone)

    async def test_release_returns_the_pokemon_to_everyone(self):
        x, y = self.spot()
        await self.on_route101(0, x, y)
        for _ in range(2):
            self.tick_spawns()
        frame = await self.spawn_frame(0, lambda d: len(inbound_slots(d)[3]) >= 1)
        target = inbound_slots(frame)[3][0]
        await self.bridges[0].send(b"g" + SpawnLocal(SpawnAction(1, ACTION_CLAIM, 0, target["species"],
                                                                 target["spawn_id"], 0, 16), 0, 16, 3).pack())
        await self.spawn_frame(0, lambda d: any(s["flags"] & SLOT_MINE for s in inbound_slots(d)[3]))
        await self.bridges[0].send(b"g" + SpawnLocal(SpawnAction(2, ACTION_RELEASE, 0, target["species"],
                                                                 target["spawn_id"], 0, 16), 0, 16, 3).pack())
        await self.spawn_frame(0, lambda d: inbound_slots(d)[1] == 2
                               and not any(s["flags"] & (SLOT_MINE | SLOT_BUSY) for s in inbound_slots(d)[3]))

    async def test_an_action_the_host_never_got_is_sent_again_and_acknowledged_once(self):
        # Audit 2026-10-13, KNOWN_ISSUES M16: the companion acknowledged an
        # action even when it never reached the host, so a caught Pokemon's
        # result could be lost. Now only the host's answer acknowledges it.
        x, y = self.spot()
        await self.on_route101(0, x, y)
        for _ in range(2):
            self.tick_spawns()
        frame = await self.spawn_frame(0, lambda d: len(inbound_slots(d)[3]) >= 1)
        target = inbound_slots(frame)[3][0]
        companion = self.companions[0]
        real, calls = companion.world_rpc, []

        async def flaky(operation, **fields):
            calls.append(operation)
            if len(calls) == 1:
                raise ConnectionError("the link dropped")
            return await real(operation, **fields)

        companion.world_rpc = flaky
        record = b"g" + SpawnLocal(SpawnAction(1, ACTION_CLAIM, 0, target["species"], target["spawn_id"], 0, 16),
                                   0, 16, 3).pack()
        await self.bridges[0].send(record)
        await wait_until(lambda: calls, timeout=2)
        await asyncio.sleep(0.2)
        self.assertEqual(companion._spawn_action_ack, 0)  # not acknowledged

        async def keep_posting():  # the game sends its record every 100 ms
            while True:
                await self.bridges[0].send(record)
                await asyncio.sleep(0.1)

        poster = asyncio.create_task(keep_posting())
        try:
            await self.spawn_frame(0, lambda d: inbound_slots(d)[1] == 1 and any(
                s["spawn_id"] == target["spawn_id"] and s["flags"] & SLOT_MINE for s in inbound_slots(d)[3]),
                timeout=6)
            await asyncio.sleep(1.5)  # an answered action is never sent again
            self.assertEqual(calls, ["spawn_action", "spawn_action"])
            companion._spawn_action_sent = 0  # as after a new bridge's capability (M19)
            await asyncio.sleep(0.5)
            self.assertEqual(calls, ["spawn_action", "spawn_action"])
        finally:
            poster.cancel()

    async def test_spawn_record_before_capability_disconnects_the_bridge(self):
        await self.bridges[0].send(b"g" + SpawnLocal().pack())
        with self.assertRaises(ConnectionError):
            for _ in range(50):
                await self.bridges[0].world(timeout=1)

    async def test_disconnected_companion_turns_shared_spawns_off_for_its_game(self):
        x, y = self.spot()
        await self.on_route101(0, x, y)
        await self.spawn_frame(0, lambda d: inbound_slots(d)[0] == FLAG_ENABLED)
        await self.server.close()
        await self.spawn_frame(0, lambda d: inbound_slots(d)[0] == 0 and not inbound_slots(d)[3], timeout=6)


if __name__ == "__main__":
    unittest.main()
