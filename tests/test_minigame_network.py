"""KNOWN_ISSUES MS-141c over real TCP: a world server, companions and bridges that speak as the native game does (the
minigame channel 'u', its 'm' frames). Development transport proofs - no game runs here (the games' side is the engine's
--selftest-netlink and the two-game proof)."""
from __future__ import annotations

import asyncio
from contextlib import suppress
import secrets
import tempfile
import unittest
import uuid

from emerald_multiplayer.bridge_protocol import encode_packet, read_packet
from emerald_multiplayer.companion import BASELINE_RULESET, Companion, CompanionConfig, verify_rom_manifest
from emerald_multiplayer.minigame_link import capability_packet
from emerald_multiplayer.minigame_protocol import closed_frame
from emerald_multiplayer.server import ServerConfig, WorldServer
from test_companion import make_files


def link_player(name: bytes, gender: int = 0, trainer_id: int = 12345) -> bytes:
    """A game's link player: its name in the game's characters (ended by 0xFF), gender, English, Emerald, trainer id."""
    return (name[:7] + bytes([0xFF]) * (8 - len(name[:7])) + bytes([gender, 2, 0x03, 0x40])
            + trainer_id.to_bytes(4, "little"))


LOST = closed_frame("player_lost")      # the game's CLOSED: during its game, its communication error
ASH, MAY, BEN = link_player(bytes([0xBB, 0xCD, 0xC2])), link_player(bytes([0xC7, 0xBB, 0xD3]), 1), \
    link_player(bytes([0xBC, 0xBF, 0xC8]), trainer_id=777)


async def wait_until(predicate, timeout=5.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


class GameBridge:
    """A bridge as the native game speaks it: the handshake, the minigame channel, its 'm' frames (others ignored)."""

    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer
        self.frames: asyncio.Queue[bytes] = asyncio.Queue()
        self._reader_task = asyncio.create_task(self._read())

    @classmethod
    async def connect(cls, companion):
        reader, writer = await asyncio.open_connection(*companion.ipc_address)
        writer.write(encode_packet(b"H" + companion.config.token) + encode_packet(capability_packet()))
        await writer.drain()
        return cls(reader, writer)

    async def _read(self):
        with suppress(ConnectionError, OSError, asyncio.IncompleteReadError):
            while (packet := await read_packet(self.reader)) is not None:
                if packet[:1] == b"m":
                    self.frames.put_nowait(packet[1:])

    async def send(self, payload: bytes):
        self.writer.write(encode_packet(b"m" + payload))
        await self.writer.drain()

    async def next(self, timeout=5.0) -> bytes:
        async with asyncio.timeout(timeout):
            return await self.frames.get()

    async def hello(self, activity_number: int, player: bytes):
        await self.send(bytes([2, 1, activity_number]) + player)

    async def close(self):
        self._reader_task.cancel()
        self.writer.close()
        with suppress(ConnectionError, OSError):
            await self.writer.wait_closed()


class MinigameNetworkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.rom, self.manifest = make_files(self.temp.name)
        build = verify_rom_manifest(self.rom, self.manifest)[0]
        self.server = WorldServer(ServerConfig(build, BASELINE_RULESET, heartbeat_interval=0.05, idle_timeout=10,
                                               monitor_interval=0.01), store=None)
        await self.server.start(port=0)
        self.companions, self.bridges = [], []

    async def asyncTearDown(self):
        for bridge in self.bridges:
            await bridge.close()
        for companion in self.companions:
            await companion.close()
        await self.server.close()
        self.temp.cleanup()

    async def player(self, index: int, name: str, activity: int, link: bytes):
        companion = Companion(CompanionConfig(self.rom, self.manifest, str(uuid.UUID(int=index)), name,
                                              secrets.token_bytes(32), server_port=self.server.address[1], ipc_port=0))
        await companion.start()
        self.companions.append(companion)
        await wait_until(lambda: companion.connected)
        bridge = await GameBridge.connect(companion)
        self.bridges.append(bridge)
        await wait_until(lambda: companion.minigames.bridge is not None)
        await bridge.hello(activity, link)
        await wait_until(lambda: companion.minigames.link_player == link)
        return companion, bridge

    async def started_group(self, activity_name="berry_crush", activity=10, links=(ASH, MAY)):
        """Players lead and join a group in their menus' order, the leader starts it; their games get STARTED."""
        names = ("Ash", "May", "Ben")
        players = [await self.player(i + 1, names[i], activity, link) for i, link in enumerate(links)]
        (leader, _), members = players[0], players[1:]
        view = (await leader.minigame_rpc("open", activity=activity_name, link_player=links[0].hex()))["result"]
        group = view["group_id"]
        for i, (member, _) in enumerate(members, 1):
            status = (await member.minigame_rpc("status", activity=activity_name))["result"]
            self.assertEqual([(g["group_id"], g["leader_name"], g["players"]) for g in status["groups"]],
                             [(group, "Ash", i)])
            joined = (await member.minigame_rpc("join", group_id=group, link_player=links[i].hex()))["result"]
            self.assertEqual(joined["index"], i)
        await leader.minigame_rpc("start", group_id=group)
        for index, (companion, bridge) in enumerate(players):
            self.assertEqual(await bridge.next(), bytes([2, 1, activity, len(links), index]) + b"".join(links))
            self.assertEqual(companion.minigames.started, (group, index))
        return group, players

    async def test_a_group_starts_and_its_link_runs_through_the_host_in_order(self):
        group, ((leader, a), (member, b)) = await self.started_group()
        # the leader's frames (every player's commands, or nothing) reach the member in order, from player 0
        frames = [bytes((i + j) % 256 for j in range(70)) if i % 3 else b"" for i in range(40)]
        for frame in frames:
            await a.send(bytes([1]) + frame)
        for frame in frames:
            self.assertEqual(await b.next(), bytes([1, 0]) + frame)
        # the member's commands reach the leader, from player 1
        commands = [bytes([0x22, 0x2F]) + bytes([i]) * 12 for i in range(20)]
        for command in commands:
            await b.send(bytes([1]) + command)
        for command in commands:
            self.assertEqual(await a.next(), bytes([1, 1]) + command)
        self.assertEqual(self.server.minigames.relayed, 60)
        # the end: the leader's closing frame goes ahead of its leaving, and reaches the member; both leave quietly
        await a.send(bytes([1]) + bytes([0x77]) * 70)
        await a.send(bytes([2, 2, 0]))
        self.assertEqual(await b.next(), bytes([1, 0]) + bytes([0x77]) * 70)
        await wait_until(lambda: leader.minigames.started is None and self.server.minigames.group_of(
            leader.config.player_id) is None)
        await b.send(bytes([2, 2, 0]))
        await wait_until(lambda: group not in self.server.minigames._groups)
        with self.assertRaises(TimeoutError):
            await a.next(timeout=0.3)             # nobody was told the group ended: their games closed it themselves

    async def test_a_player_whose_game_is_gone_ends_the_started_group_for_the_others(self):
        group, ((leader, a), (member, b), (third, c)) = await self.started_group(
            "dodrio", 11, (ASH, MAY, BEN))
        await a.send(bytes([1]) + bytes(70))
        self.assertEqual(await b.next(), bytes([1, 0]) + bytes(70))
        self.assertEqual(await c.next(), bytes([1, 0]) + bytes(70))
        # the member's game window closes: the others' games are told the group has ended (their link error)
        await b.close()
        self.bridges.remove(b)
        self.assertEqual(await a.next(), LOST)
        self.assertEqual(await c.next(), LOST)
        await wait_until(lambda: group not in self.server.minigames._groups)
        self.assertIsNone(leader.minigames.started)
        self.assertEqual(leader.minigames.notice, "A player left the group")

    async def test_a_lost_link_ends_the_group_and_a_lobby_left_as_the_start_came_too(self):
        group, ((leader, a), (member, b)) = await self.started_group()
        await b.send(bytes([2, 2, 1]))                              # the member's link was lost
        self.assertEqual(await a.next(), LOST)
        await wait_until(lambda: group not in self.server.minigames._groups)
        # again: the member's game left its lobby as the leader started (LEAVE "lobby" after the start)
        await a.hello(10, ASH)
        await b.hello(10, MAY)
        await wait_until(lambda: leader.minigames.activity == member.minigames.activity == "berry_crush")
        group = (await leader.minigame_rpc("open", activity="berry_crush", link_player=ASH.hex()))["result"]["group_id"]
        await member.minigame_rpc("join", group_id=group, link_player=MAY.hex())
        await leader.minigame_rpc("start", group_id=group)
        self.assertEqual((await a.next())[:2], bytes([2, 1]))
        self.assertEqual((await b.next())[:2], bytes([2, 1]))
        await b.send(bytes([2, 2, 2]))
        self.assertEqual(await a.next(), LOST)

    async def test_a_disconnected_player_ends_the_started_group_and_an_unstarted_one_goes_on(self):
        group, ((leader, a), (member, b)) = await self.started_group()
        await self.companions[1].close()                             # the member's whole launcher goes
        self.assertEqual(await a.next(), LOST)
        await wait_until(lambda: group not in self.server.minigames._groups)
        # before the start: the leader ends the group, its member is told in the menu, not in the game
        third, c = await self.player(3, "Ben", 10, BEN)
        await a.hello(10, ASH)
        await wait_until(lambda: leader.minigames.link_player == ASH)
        group = (await leader.minigame_rpc("open", activity="berry_crush", link_player=ASH.hex()))["result"]["group_id"]
        await third.minigame_rpc("join", group_id=group, link_player=BEN.hex())
        await leader.minigame_rpc("leave", group_id=group, lost=False)
        await wait_until(lambda: third.minigames.notice == "The leader ended the group")
        with self.assertRaises(TimeoutError):
            await c.next(timeout=0.3)

    async def test_refusals(self):
        _, ((leader, a), (member, b)) = await self.started_group()
        from emerald_multiplayer.minigame_link import MinigameRemoteError
        with self.assertRaises(MinigameRemoteError) as error:
            await member.minigame_rpc("start", group_id=1)
        self.assertEqual(error.exception.code, "minigame_not_leader")
        with self.assertRaises(MinigameRemoteError) as error:
            await leader.minigame_rpc("open", activity="pokemon_jump", link_player=ASH.hex())
        self.assertEqual(error.exception.code, "minigame_busy")
        # a member's frame of the leader's size is refused by the host (the member's session ends: a broken game)
        await b.send(bytes([1]) + bytes(70))
        self.assertEqual(await a.next(), LOST)
