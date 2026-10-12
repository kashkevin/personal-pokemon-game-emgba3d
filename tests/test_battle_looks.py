"""Battle looks: the native PC game's 'A' announcement and the companion's 'B' frame."""
import asyncio
from dataclasses import replace
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from emerald_multiplayer.battle_looks import LOOK_BYTES, SLOTS, capability_packet, looks_packet
from emerald_multiplayer.battle_mailbox import _QUERY, BattleMailboxError, response_packet as battle_response
from emerald_multiplayer.bridge_protocol import encode_packet, read_packet
from emerald_multiplayer.native_battle import NativeBinding, NativeControl, Opcode as NativeOpcode
from test_companion import wait_until
import test_companion_battle as ipc_fixture

KIT_A = bytes((1, 0, 0, 0, 2, 0, 1, 0))      # a character look: id (2 << 4) | 1 = 33
COLOURS = bytes((1, 2, 3, 4, 0, 5, 0, 0))    # the default trainer, recoloured


def binding(count=2, local=0):
    players = tuple(sorted(str(uuid4()) for _ in range(count)))
    return NativeBinding(str(uuid4()), players, tuple(range(1, count + 1)), tuple(range(1, count + 1)),
                         local, mode=3 if count == 4 else 2)


class BattleLooksPacketTests(unittest.TestCase):
    def test_capability(self):
        self.assertEqual(capability_packet(), b"A\x01\x00\x04\x00")

    def test_one_look_per_binding_slot(self):
        bound = binding()
        stranger = str(uuid4())
        roster = ({"player_id": bound.players[1], "appearance": KIT_A.hex()},
                  {"player_id": bound.players[0], "appearance": None},
                  {"player_id": stranger, "appearance": COLOURS.hex()})
        packet = looks_packet(bound.pack(), roster)
        self.assertEqual(len(packet), 1 + 16 + SLOTS * LOOK_BYTES)
        self.assertEqual(packet[:1], b"B")
        self.assertEqual(packet[1:17], UUID(bound.generation).bytes)
        slots = [packet[17 + i * 8:25 + i * 8] for i in range(SLOTS)]
        self.assertEqual(slots, [bytes(8), KIT_A, bytes(8), bytes(8)])

    def test_four_players(self):
        bound = binding(4, local=2)
        roster = [{"player_id": p, "appearance": (KIT_A if n % 2 else COLOURS).hex()}
                  for n, p in enumerate(bound.players)]
        packet = looks_packet(bound.pack(), roster)
        self.assertEqual([packet[17 + i * 8:25 + i * 8] for i in range(4)], [COLOURS, KIT_A, COLOURS, KIT_A])

    def test_unusable_roster_entries_give_default_trainers(self):
        bound = binding()
        roster = ({"player_id": bound.players[0], "appearance": "zz"},
                  {"player_id": "not a uuid", "appearance": KIT_A.hex()},
                  {"appearance": KIT_A.hex()},
                  {"player_id": bound.players[1], "appearance": KIT_A.hex()[:-2]})
        self.assertEqual(looks_packet(bound.pack(), roster)[17:], bytes(SLOTS * LOOK_BYTES))

    def test_only_a_native_binding(self):
        with self.assertRaises(BattleMailboxError):
            looks_packet(bytes(115), ())


class CompanionBattleLooksTests(unittest.IsolatedAsyncioTestCase):
    """The real companion over loopback: 'B' follows a successful native BIND only
    when the game announced 'A'; the battle commands themselves are unchanged."""
    abi_version = 2
    asyncTearDown = ipc_fixture.CompanionBattleTests.asyncTearDown

    async def asyncSetUp(self):
        await ipc_fixture.CompanionBattleTests.asyncSetUp(self)
        actor = self.c.config.player_id
        other = str(uuid4())
        players = tuple(sorted((actor, other)))
        local = players.index(actor)
        leases = tuple(self.c.session_epoch if p == actor else self.c.session_epoch + 1 for p in players)
        incarnations = tuple(self.c.battle_incarnation if p == actor else self.c.battle_incarnation + 1 for p in players)
        self.binding = NativeBinding(str(uuid4()), players, leases, incarnations, local, mode=2)
        self.other = other
        self.bind = NativeControl(self.c.battle_incarnation, self.c.session_epoch, str(uuid4()), 1,
                                  NativeOpcode.BIND, source_slot=local, data=self.binding.pack(), phase=2)
        self.roster = ({"player_id": actor, "appearance": COLOURS.hex()},
                       {"player_id": other, "appearance": KIT_A.hex()})

    async def announce(self):
        self.bridge.writer.write(encode_packet(capability_packet()))
        await self.bridge.writer.drain()
        await wait_until(lambda: self.c._bridge.battle_looks_capable)

    async def bind_and_collect(self, *, status=0):
        """BIND through battle_rpc, answered by the game; then the frames that follow
        up to the next battle command (a QUERY)."""
        async def game():
            seen = []
            async with asyncio.timeout(3):
                while True:
                    packet = await read_packet(self.bridge.reader)
                    if packet[:1] == b"D":
                        command = NativeControl.unpack(packet[1:])
                        if command.opcode == NativeOpcode.QUERY:
                            return seen
                        held = _QUERY.pack(1, UUID(self.binding.generation).bytes, 2, self.binding.local_slot, 2, 0,
                                           command.sequence, 0, 0, 0, 0, 0, 0, 300, 0, 0)
                        response = replace(command, status=status, data=b"" if status else held)
                        self.bridge.writer.write(encode_packet(battle_response(response)))
                        await self.bridge.writer.drain()
                    elif packet[:1] != b"S":
                        seen.append(packet)
        task = asyncio.create_task(game())
        self.tasks.append(task)
        with patch.object(type(self.c), "_battle_looks_roster", lambda _: self.roster):
            reply = await self.c.battle_rpc(self.bind)
        self.assertEqual(reply.status, status)
        query = replace(self.bind, opcode=NativeOpcode.QUERY, data=b"", sequence=2)
        self.tasks.append(asyncio.create_task(self.c.battle_rpc(query, timeout=.5)))
        return await task

    async def test_looks_follow_a_bind(self):
        await self.announce()
        frames = await self.bind_and_collect()
        self.assertEqual(len(frames), 1)
        expected = looks_packet(self.binding.pack(), self.roster)
        self.assertEqual(frames[0], expected)
        slot = self.binding.players.index(self.other)
        self.assertEqual(frames[0][17 + slot * 8:25 + slot * 8], KIT_A)
        self.assertTrue(self.c.connected)

    async def test_no_looks_without_the_announcement(self):
        self.assertEqual(await self.bind_and_collect(), [])

    async def test_no_looks_after_a_refused_bind(self):
        await self.announce()
        self.assertEqual(await self.bind_and_collect(status=5), [])

    async def test_announcement_needs_the_battle_capability_once(self):
        await self.announce()
        self.bridge.writer.write(encode_packet(capability_packet()))
        await self.bridge.writer.drain()
        await wait_until(lambda: self.c._bridge is None, 3)


if __name__ == "__main__":
    unittest.main()
