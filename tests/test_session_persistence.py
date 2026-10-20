"""The session keeps every connected player through battles, menus and map changes (the owner's report of 2026-10-19).

Real `WorldServer`s and `Companion`s over TCP; each game is the companion's binary bridge protocol (BinaryBridge), so
what the games receive is checked byte for byte while no emulator runs. Membership comes from the server's sessions,
never from what a game draws: a player in a battle stays in every roster and in every snapshot (hidden there, with
the game's own activity flag) and comes back on the field without reconnecting. docs/multiplayer-session-fix-20261019.md
"""
import asyncio
import json
import secrets
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from emerald_multiplayer.companion import BASELINE_RULESET, Companion, CompanionConfig, verify_rom_manifest
from emerald_multiplayer.mailbox import DETAIL_ACTIVITIES, MailboxError, Pose
from emerald_multiplayer.ownership_protocol import OWNERSHIP_PROFILE
from emerald_multiplayer.player_menu import PlayerMenu
from emerald_multiplayer.server import MAX_PLAYERS, ServerConfig, WorldServer
from emerald_multiplayer.trade_storage import TradeCheckpointStore
from emerald_multiplayer.battle_reservations import enable_battle_reservations
from test_companion import BinaryBridge, make_files, make_pose
from test_ownership_storage import owned_flash, source_flash
import test_battle_manifest as manifest_fixture

BATTLE, MENU, TRANSITION = 1, 2, 3


async def wait_until(predicate, timeout=3.0):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


class RunningGame:
    """A game's bridge that keeps publishing, as a running game does every frame (battles and menus included): only
    the frame counter moves unless the test changes what the game shows (`show`)."""

    def __init__(self, bridge, pose_of_frame):
        self.bridge, self.pose_of_frame, self.frame = bridge, pose_of_frame, 0
        self.task = asyncio.create_task(self._run())

    def show(self, pose_of_frame):
        self.pose_of_frame = pose_of_frame

    async def _run(self):
        while True:
            self.frame += 1
            await self.bridge.pose(self.pose_of_frame(self.frame))
            await asyncio.sleep(0.02)

    async def stop(self):
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)


def detail_files(directory, detail=True):
    rom, manifest = make_files(directory)
    if detail:
        data = json.loads(manifest.read_text())
        data["presence_detail_abi_version"] = 1
        manifest.write_text(json.dumps(data))
    return rom, manifest


def off_field(frame, detail, **changes):
    """The pose a PC game publishes off the field: the last field position, activity 0, why in the last byte."""
    return make_pose(frame=frame, activity=0, **changes) if detail == 0 else Pose(
        **{**make_pose(frame=frame, **changes).__dict__, "activity": 0, "detail": detail})


class PoseDetailTests(unittest.TestCase):
    def test_detail_round_trips_only_with_the_capability(self):
        pose = off_field(3, BATTLE)
        self.assertEqual(pose.pack()[19], BATTLE)
        self.assertEqual(Pose.unpack(pose.pack(), detail_version=1), pose)
        with self.assertRaises(MailboxError):
            Pose.unpack(pose.pack())                     # a game without the capability never sends it
        with self.assertRaises(MailboxError):
            Pose.unpack(pose.pack()[:19] + bytes([4]), detail_version=1)
        with self.assertRaises(MailboxError):
            Pose(**{**make_pose().__dict__, "detail": MENU})  # nothing to explain on the field

    def test_session_activity_names(self):
        self.assertEqual({detail: off_field(1, detail).network_fields(True)["activity"] for detail in range(4)},
                         {0: "unavailable", 1: "battle", 2: "menu", 3: "transition"})
        self.assertEqual(make_pose().network_fields(True)["activity"], "overworld")
        # A stale or lost game is unavailable whatever it said last.
        self.assertEqual(off_field(1, BATTLE).network_fields(False)["activity"], "unavailable")
        self.assertEqual(set(DETAIL_ACTIVITIES.values()), {"battle", "menu", "transition"})


class PlaceNameTests(unittest.TestCase):
    def test_every_map_has_the_games_place_name(self):
        from emerald_multiplayer.map_names import MAP_NAMES
        from emerald_multiplayer.shared_world import SharedWorld
        place = SharedWorld._place_name
        holder = type("Holder", (), {"spawn_director": None})()
        # Towns and buildings have no wild Pokemon entry; they showed as "Area 0-9".
        self.assertEqual(place(holder, 0, 9), "LITTLEROOT TOWN")
        self.assertEqual(place(holder, 1, 0), "LITTLEROOT TOWN")     # a house in Littleroot
        self.assertEqual(place(holder, 0, 16), "ROUTE 101")
        self.assertEqual(place(holder, 250, 250), "Area 250-250")    # nothing known
        self.assertGreater(len(MAP_NAMES), 500)


class PresenceDetailManifestTests(manifest_fixture.CoopAndWorldManifestTests):
    def test_the_detail_marker_comes_from_the_native_executable(self):
        native = "00bd2790 00000004 R gMultiplayerPresenceDetailAbiVersion\n"
        plain = self.generate(self.base + self.battle + self.world)
        self.assertNotIn("presence_detail_abi_version", plain)  # the GBA ELF alone never advertises it
        self.assertEqual(self.generate_native(self.base + self.battle + self.world, native)
                         ["presence_detail_abi_version"], 1)
        mingw = "00bd2790 R _gMultiplayerPresenceDetailAbiVersion\n"   # MinGW nm: no size column for a PE executable
        self.assertEqual(self.generate_native(self.base, mingw)["presence_detail_abi_version"], 1)
        for bad in ("00bd2790 00000008 R gMultiplayerPresenceDetailAbiVersion\n", native + native):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.generate_native(self.base, bad)

    def test_only_version_one_enables_it_in_the_companion(self):
        for value, expected in ((None, 0), (1, 1), (2, 0), (True, 0)):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                rom, manifest = make_files(directory)
                if value is not None:
                    data = json.loads(manifest.read_text())
                    data["presence_detail_abi_version"] = value
                    manifest.write_text(json.dumps(data))
                config = CompanionConfig(rom, manifest, str(uuid.uuid4()), "Alice", secrets.token_bytes(32), ipc_port=0)
                self.assertEqual(config.presence_detail_abi_version, expected)


class PresenceSessionTests(unittest.IsolatedAsyncioTestCase):
    """Up to five players on a presence-only world server with fast timeouts."""

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.rom, self.manifest = detail_files(self.temp.name)
        build = verify_rom_manifest(self.rom, self.manifest)[0]
        self.server = WorldServer(ServerConfig(build, BASELINE_RULESET, heartbeat_interval=0.05, idle_timeout=0.5,
                                               presence_timeout=0.25, monitor_interval=0.005))
        await self.server.start(port=0)
        self.companions, self.bridges, self.games = [], [], []

    async def asyncTearDown(self):
        for game in self.games:
            await game.stop()
        for bridge in self.bridges:
            await bridge.close()
        for companion in self.companions:
            await companion.close()
        await self.server.close()
        self.temp.cleanup()

    def play(self, bridge, pose_of_frame):
        game = RunningGame(bridge, pose_of_frame)
        self.games.append(game)
        return game

    async def join(self, index, *, wait=True):
        companion = Companion(CompanionConfig(
            self.rom, self.manifest, str(uuid.UUID(int=index)), f"Player {index}", secrets.token_bytes(32),
            server_port=self.server.address[1], ipc_port=0, pause_timeout=0.3, pose_interval=0.005,
            snapshot_interval=0.01, reconnect_delay=0.025, handshake_timeout=0.2, remote_timeout=0.4,
            send_timeout=0.2))
        await companion.start()
        self.companions.append(companion)
        if wait:
            await wait_until(lambda: companion.connected and bool(companion._players))
        bridge = await BinaryBridge.connect(companion)
        self.bridges.append(bridge)
        return companion, bridge

    def roster(self, companion):
        return {p["display_name"]: (p["presence"] or {}).get("activity") for p in companion._players}

    async def test_a_battle_keeps_the_player_listed_and_the_field_comes_back(self):
        (a, bridge_a), (b, bridge_b) = await self.join(1), await self.join(2)
        game_a = self.play(bridge_a, lambda f: make_pose(frame=f, x=9))
        self.play(bridge_b, lambda f: make_pose(frame=f, x=10))
        seen = await bridge_b.snapshot(lambda s: s.peers and s.peers[0].pose.activity == 1 and s.peers[0].pose.x == 9)
        epoch, token = seen.roster_epoch, seen.peers[0].token
        # A battle longer than the server's idle (0.5 s) and presence (0.25 s) timeouts: no movement, no disconnect.
        game_a.show(lambda f: off_field(f, BATTLE, x=9))
        await asyncio.sleep(1.2)
        self.assertEqual(self.server.sessions[a.config.player_id].presence["activity"], "battle")
        self.assertEqual(self.roster(b), {"Player 1": "battle", "Player 2": "overworld"})
        during = await bridge_b.snapshot(lambda s: s.peers and s.peers[0].pose.activity == 0)
        self.assertEqual((len(during.peers), during.peers[0].token, during.roster_epoch), (1, token, epoch))
        self.assertEqual(during.peers[0].pose.x, 9, "the last field position, kept while hidden")
        self.assertTrue(a.connected and b.connected)
        # Back on the field: visible again in the same session, no reconnect.
        game_a.show(lambda f: make_pose(frame=f, x=9))
        after = await bridge_b.snapshot(lambda s: s.peers and s.peers[0].pose.activity == 1)
        self.assertEqual((after.peers[0].token, after.roster_epoch, after.peers[0].pose.x), (token, epoch, 9))
        await wait_until(lambda: self.roster(b)["Player 1"] == "overworld")

    async def test_menus_and_map_changes_keep_the_player_listed(self):
        (a, bridge_a), (b, bridge_b) = await self.join(1), await self.join(2)
        game_a = self.play(bridge_a, lambda f: make_pose(frame=f))
        self.play(bridge_b, lambda f: make_pose(frame=f))
        first = await bridge_b.snapshot(lambda s: s.peers and s.peers[0].pose.activity == 1)
        game_a.show(lambda f: off_field(f, MENU))
        await wait_until(lambda: self.roster(b)["Player 1"] == "menu")
        # A door: the screen fades (transition), the new map loads with a new epoch, the field comes back there.
        game_a.show(lambda f: off_field(f, TRANSITION))
        await wait_until(lambda: self.roster(b)["Player 1"] == "transition")
        game_a.show(lambda f: make_pose(frame=f, epoch=1, map_number=7, x=3, y=4))
        moved = await bridge_b.snapshot(lambda s: s.peers and s.peers[0].pose.map_number == 7)
        self.assertEqual((moved.peers[0].pose.activity, moved.peers[0].pose.x, moved.peers[0].pose.map_epoch), (1, 3, 1))
        self.assertEqual(moved.roster_epoch, first.roster_epoch)
        await wait_until(lambda: self.roster(b)["Player 1"] == "overworld")
        self.assertEqual(len(self.server.sessions), 2)

    async def test_a_game_without_the_capability_cannot_send_a_detail(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.rom, self.manifest = detail_files(temp.name, detail=False)  # the same ROM bytes: the same build
        a, bridge_a = await self.join(1)
        self.assertEqual(a.config.presence_detail_abi_version, 0)
        await bridge_a.pose(make_pose(frame=1))
        await wait_until(lambda: a._local_pose is not None)
        await bridge_a.pose(off_field(2, BATTLE))
        await wait_until(lambda: a._bridge is None)  # the malformed pose ends the game's link, not the world session
        self.assertTrue(a.connected)
        # Why is kept: a Windows manifest without the marker (2026-10-19) showed only as a game reconnecting again and again.
        self.assertEqual(a.last_bridge_refusal, "MailboxError: local pose reserved byte must be zero")

    async def test_one_to_four_players_a_battle_keeps_everyone_at_every_count(self):
        players, games = [], []
        for count in range(1, MAX_PLAYERS + 1):
            with self.subTest(players=count):
                players.append(await self.join(count))
                games.append(self.play(players[-1][1], lambda f, x=count + 1: make_pose(frame=f, x=x)))
                for companion, bridge in players:
                    await wait_until(lambda: len(companion._players) == count)
                    await bridge.snapshot(lambda s: len(s.peers) == count - 1 and all(p.pose.activity == 1 for p in s.peers))
                sessions = dict(self.server.sessions)
                # The newest player battles longer than the idle and presence timeouts; everyone else keeps them.
                battler = players[-1][0].config.display_name
                games[-1].show(lambda f, x=count + 1: off_field(f, BATTLE, x=x))
                await asyncio.sleep(0.8)
                await wait_until(lambda: self.server.sessions[players[-1][0].config.player_id].presence["activity"]
                                 == "battle")
                for companion, bridge in players:
                    self.assertTrue(companion.connected)
                    await wait_until(lambda: len(companion._players) == count)
                    if companion.config.display_name != battler:
                        await wait_until(lambda: self.roster(companion)[battler] == "battle")
                        snapshot = await bridge.snapshot(lambda s: len(s.peers) == count - 1
                                                         and sorted(p.pose.activity for p in s.peers)[0] == 0)
                        self.assertEqual(sorted(p.pose.activity for p in snapshot.peers), [0] + [1] * (count - 2))
                games[-1].show(lambda f, x=count + 1: make_pose(frame=f, x=x))
                for companion, bridge in players:
                    await bridge.snapshot(lambda s: len(s.peers) == count - 1 and all(p.pose.activity == 1 for p in s.peers))
                self.assertEqual(self.server.sessions.keys(), sessions.keys())
                self.assertTrue(all(self.server.sessions[k] is v for k, v in sessions.items()), "a session was replaced")

    async def test_four_players_one_battles_one_leaves_and_a_fifth_waits_for_a_free_place(self):
        players = [await self.join(i) for i in range(1, 5)]
        games = [self.play(bridge, lambda f, x=index + 2: make_pose(frame=f, x=x))
                 for index, (_, bridge) in enumerate(players)]
        for companion, bridge in players:
            snapshot = await bridge.snapshot(lambda s: len(s.peers) == 3 and all(p.pose.activity == 1 for p in s.peers))
            self.assertEqual(len({p.token for p in snapshot.peers}), 3)
            self.assertEqual(len(companion._players), MAX_PLAYERS)
        # The fifth player is refused as a full world and keeps its place in the queue (it retries calmly).
        fifth, fifth_bridge = await self.join(5, wait=False)
        await wait_until(lambda: fifth.failure == "rejected_server_full")
        self.assertFalse(fifth.connected)
        self.assertEqual(len(self.server.sessions), MAX_PLAYERS)
        # Independent simultaneous states: 2 battles, 3 is in a menu, 1 and 4 walk.
        games[1].show(lambda f: off_field(f, BATTLE, x=3))
        games[2].show(lambda f: off_field(f, MENU, x=4))
        games[0].show(lambda f: make_pose(frame=f, x=2 + (f // 10) % 2))
        expected = {"Player 1": "overworld", "Player 2": "battle", "Player 3": "menu", "Player 4": "overworld"}
        for companion, bridge in players:
            await wait_until(lambda: self.roster(companion) == expected)
            # Every game keeps all three others: those on the field drawn, and (Update 32) the player standing in a
            # menu too; the battling one hidden.
            drawn = sorted(1 if name in ("Player 1", "Player 3", "Player 4") else 0
                           for name in expected if name != companion.config.display_name)
            snapshot = await bridge.snapshot(lambda s: sorted(p.pose.activity for p in s.peers) == drawn)
            self.assertEqual(len(snapshot.peers), 3)
        # Player 4 leaves for good: removed everywhere; the fifth takes the place automatically.
        await games[3].stop()
        await players[3][1].close()
        self.bridges.remove(players[3][1])
        await players[3][0].close()
        await wait_until(lambda: fifth.connected, timeout=6)
        self.play(fifth_bridge, lambda f: make_pose(frame=f, x=12))
        for companion, _ in players[:3]:
            await wait_until(lambda: {p["display_name"] for p in companion._players}
                             == {"Player 1", "Player 2", "Player 3", "Player 5"})
        snapshot = await players[0][1].snapshot(lambda s: len(s.peers) == 3 and any(p.pose.x == 12 for p in s.peers))
        self.assertEqual(len(snapshot.peers), 3)


class AuthenticatedSessionTests(unittest.IsolatedAsyncioTestCase):
    """Four enrolled players on an ownership world: the production session (ownership RPCs, the Players menu)."""

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.rom, self.manifest = detail_files(self.temp.name)
        build = verify_rom_manifest(self.rom, self.manifest)[0]
        self.store = TradeCheckpointStore(Path(self.temp.name) / "world.sqlite3", build, BASELINE_RULESET)
        enable_battle_reservations(self.store, Path(self.temp.name) / "before-battles.sqlite3")
        self.store.begin_server_boot()
        self.players = []
        for i in range(4):
            p = self.store.create_player(f"Trainer {i}")
            lease = self.store.acquire_lease(p.player_id, p.credential)
            personalities = (7 + i * 2, 8 + i * 2)
            self.store.enroll_player(p.player_id, source_flash(("party:0", "party:1"), personalities=personalities))
            grant = self.store.reserve_instances(p.player_id, lease, str(uuid.uuid4()), 0, 1, 32)
            payload = owned_flash(grant, (("party:0", grant.start), ("party:1", grant.start + 1)),
                                  personalities=personalities)
            self.store.commit_checkpoint(p.player_id, lease, str(uuid.uuid4()), 0, payload, build, BASELINE_RULESET,
                                         OWNERSHIP_PROFILE)
            self.store.release_lease(p.player_id, lease)
            self.players.append(p)
        self.server = WorldServer(ServerConfig(build, BASELINE_RULESET, heartbeat_interval=0.05, idle_timeout=10),
                                  store=self.store, development_teams=True, development_battles=True)
        self.companions, self.bridges = [], []

    async def asyncTearDown(self):
        for bridge in self.bridges:
            await bridge.close()
        for companion in self.companions:
            await companion.close()
        await self.server.close()
        self.store.close()
        self.temp.cleanup()

    async def start(self, *, rival=False):
        await self.server.start(port=0)
        for p in self.players:
            config = CompanionConfig(self.rom, self.manifest, p.player_id, p.display_name, secrets.token_bytes(32),
                                     server_port=self.server.address[1], ipc_port=0, server_credential=p.credential,
                                     reconnect_delay=0.02, remote_timeout=15, pose_interval=0.005,
                                     snapshot_interval=0.01, pause_timeout=0.5)
            if rival:
                # The installed game reads rival records (manifest rival_abi_version 1 with its world mailbox).
                object.__setattr__(config, "rival_abi_version", 1)
            companion = Companion(config)
            self.companions.append(companion)
            await companion.start()
        await wait_until(lambda: all(c.connected for c in self.companions))

    def epochs(self):
        return {pid: s.session_epoch for pid, s in self.server.sessions.items()}

    async def test_a_host_that_refuses_rival_status_keeps_every_session(self):
        # A host without rival checkpoints (the enrollment host, an older world) refuses the status once. The
        # refusal ended the companion's world session, which then reconnected in a loop (and never again once the
        # launcher's terminal saver was armed).
        self.server._rivals = None
        await self.start(rival=True)
        first = self.epochs()
        polls = []
        original = self.companions[0].battle_challenge_rpc

        async def counted(operation, **fields):
            if "rival" in fields:
                polls.append(fields["rival"]["operation"])
            return await original(operation, **fields)
        self.companions[0].battle_challenge_rpc = counted
        await asyncio.sleep(1.0)
        self.assertEqual(self.epochs(), first, "no session was replaced")
        self.assertTrue(all(c.connected and c.last_error is None for c in self.companions))
        self.assertTrue(all(c._world_rival is None for c in self.companions))
        self.assertEqual(polls, [], "the refused poll stopped; nothing polls again")

    async def test_rival_records_flow_without_touching_the_session(self):
        await self.start(rival=True)
        first = self.epochs()
        await wait_until(lambda: all(c._world_rival is not None for c in self.companions))
        await asyncio.sleep(0.5)
        self.assertEqual(self.epochs(), first)
        packed = self.companions[0].world_inbound().pack()
        self.assertEqual(packed[192:200], bytes(8))
        self.assertEqual(packed[200], 1, "the valid flag the game's bridge used to refuse")

    async def test_players_menu_lists_all_four_with_what_they_are_doing(self):
        await self.start()
        poses = [make_pose(frame=1, x=2), off_field(5, BATTLE), off_field(5, MENU), off_field(5, TRANSITION)]
        for companion, pose in zip(self.companions, poses):
            bridge = await BinaryBridge.connect(companion)
            self.bridges.append(bridge)
            await bridge.pose(pose)
        await wait_until(lambda: [(p["presence"] or {}).get("activity") for p in self.companions[0]._players]
                         .count(None) == 0)
        menu = PlayerMenu(self.companions[0])
        screen = await menu.refresh()
        labels = [row.label for row in screen.rows]
        self.assertEqual(screen.status, "Connected: 4/4")
        self.assertIn("Trainer 1 - In battle", labels)
        self.assertIn("Trainer 2 - In a menu", labels)
        self.assertIn("Trainer 3 - Changing area", labels)
        row = next(r for r in screen.rows if r.label == "Trainer 1 - In battle")
        page = await menu.choose(screen.revision, row.action)
        self.assertEqual(page.title, "Trainer 1")
        # What the player is doing and where (the host's world view names the map: 0.1 is Slateport City), not
        # selectable.
        self.assertEqual((page.rows[0].label, page.rows[0].action), ("In battle: SLATEPORT CITY", 0))
        # The battle ends: the same player, on the field, in the same session.
        epoch = self.epochs()[self.players[1].player_id]
        await self.bridges[1].pose(make_pose(frame=9, x=4))
        await wait_until(lambda: next(p for p in self.companions[0]._players
                                      if p["display_name"] == "Trainer 1")["presence"]["activity"] == "overworld")
        page = await menu.refresh()
        self.assertEqual(page.rows[0].label, "Field: SLATEPORT CITY")  # "On the field: ..." is over 25 characters
        self.assertEqual(self.epochs()[self.players[1].player_id], epoch)
        # Only leaving the session removes a player from the list.
        await self.bridges[2].close()
        self.bridges.pop(2)
        await self.companions[2].close()
        await wait_until(lambda: len(self.companions[0]._players) == 3)
        home = await menu.choose(page.revision, page.back)
        self.assertEqual(home.status, "Connected: 3/4")
        self.assertNotIn("Trainer 2 - In a menu", [row.label for row in home.rows])


if __name__ == "__main__":
    unittest.main()
