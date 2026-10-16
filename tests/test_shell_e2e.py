"""End to end through the in-game menu with real worlds, a real server over TLS, and real first-time enrollment.

What is simulated, honestly: the game process (a placeholder child), the game's save mailbox (the existing ``NativeEnrollmentFixture``)
and the New Game itself (a synthetic unassigned save per player). Everything else is the shipping code: world creation, the
registry and links, invite codes, certificate pinning, the authenticated connection, the server's enrollment checks and per-player
checkpoint storage. These are single-machine runs: the "PCs" are separate private folders on one computer.
"""
import asyncio
from functools import partial
import hashlib
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from emerald_multiplayer.character_creation import create_character
from emerald_multiplayer.character_links import character_state, profile_directory
from emerald_multiplayer.companion import Companion
from emerald_multiplayer.host_world import HostWorld
from emerald_multiplayer.invite_code import encode_invite
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, inspect_ownership
from emerald_multiplayer.flash import inspect_flash
from process_fixture import direct_python
from shell_fixture import BACK, Driver, FakeWorker, ServerThread, World, label_id, select
from test_enrollment_runtime import NativeEnrollmentFixture
from test_ownership_storage import owned_flash, source_flash
from test_shell_app import create_world_steps, main_exit

LOOPBACK_LAN = lambda: ["127.0.0.1"]


class Players(unittest.IsolatedAsyncioTestCase):
    pass


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.world = World(self)
        self.native = NativeEnrollmentFixture(self)
        self.companions, self.children = [], []
        self.personality = 1000
        self.personalities = {}
        self.real_spawn = asyncio.create_subprocess_exec
        self.private = None
        patches = [patch("emerald_multiplayer.launcher_setup.Companion", self.companion),
                   patch("emerald_multiplayer.character_creation.Companion", self.companion),
                   patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn),
                   patch("test_enrollment_runtime.owned_flash", self.export)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.addCleanup(self.kill_children)

    def kill_children(self):
        for child in self.children:
            if child.returncode is None:
                try:
                    child.kill()
                except ProcessLookupError:
                    pass

    def companion(self, config):
        result = Companion(config)
        result.save_rpc = self.native.rpc
        self.companions.append(result)
        return result

    async def spawn(self, *args, **kwargs):
        self.private = Path(args[4]).parent
        self.companions[-1]._bridge = SimpleNamespace(save_capable=True, window_capable=False, incarnation=1,
                                                      outbox=SimpleNamespace(put=lambda _: None))
        child = await self.real_spawn(direct_python(), "-c", "import time; time.sleep(60)", **kwargs)
        self.children.append(child)
        return child

    def export(self, grant, **keywords):
        # The fixture's first export keeps the enrolled Pokemon: it carries the source's personality (one per player).
        return owned_flash(grant, personalities=(self.personalities[grant.player_id],), **keywords)

    async def drafter(self, installation, private_root, *, on_status=None):
        """The player's New Game, simulated: a closed, valid, unassigned save with one starter, unique to this character."""
        self.personality += 111
        self.native.grant = None            # each New Game is a fresh game process with no ownership yet
        folder = Path(private_root) / "drafts" / str(uuid4())
        folder.mkdir(parents=True)
        path = folder / "character.sav"
        payload = source_flash(personalities=(self.personality,))
        path.write_bytes(payload)
        self.last_personality = self.personality
        return SimpleNamespace(source_path=path, sha256=hashlib.sha256(payload).hexdigest(), party_count=1)

    def creator_for(self, account_player_id):
        """create_character with the simulated New Game; remembers which player's save this personality belongs to."""
        async def creator(installation, private_root, **options):
            result = await create_character(installation, private_root, drafter=self.drafter_for(account_player_id), **options)
            return result
        return creator

    def drafter_for(self, player_id):
        async def draft(installation, private_root, *, on_status=None):
            result = await self.drafter(installation, private_root, on_status=on_status)
            self.personalities[player_id] = self.last_personality
            return result
        return draft

    @staticmethod
    def head(world, player_id):
        connection = sqlite3.connect(world.database_path)
        try:
            row = connection.execute("SELECT latest_revision FROM players WHERE player_id = ?", (player_id,)).fetchone()
        finally:
            connection.close()
        return row[0] if row else 0

    def worker_for(self, world):
        """The session worker: 'enrollment_required' until the server holds a checkpoint for that account, then 'game_closed'."""
        return FakeWorker(lambda request: "game_closed" if self.head(world, self.account_of(request)) else "enrollment_required")

    def account_of(self, request):
        if request.mode == "host":
            return HostWorld.open(request.selection.parent, self.world.rom, self.world.manifest).accounts[0].player_id
        from emerald_multiplayer.invitations import Invitation
        return Invitation.load(request.selection).player_id

    def build_world(self, name="Kevin's world"):
        driver = Driver(*create_world_steps(name, "Kevin"), ("world", BACK), ("host_list", BACK), main_exit())
        app, _ = self.world.app(driver, lan=LOOPBACK_LAN)
        app.run()
        entry = next(e for e in app.registry.entries() if e.name == name)
        return app, entry, HostWorld.open(entry.folder, self.world.rom, self.world.manifest)

    def host_first_time(self, entry, host_world):
        host_id = host_world.accounts[0].player_id
        worker = self.worker_for(host_world)
        driver = Driver(("main", select("host")), ("host_list", select(entry.world_id)), ("world", select("host")),
                        ("create_character", select("go")), ("host_list", BACK), main_exit())
        app, _ = self.world.app(driver, worker=worker, creator=self.creator_for(host_id), lan=LOOPBACK_LAN)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        return app, worker

    def join_first_time(self, pc, host_world, entry, slot, server_app_check=None):
        player_id = host_world.accounts[slot].player_id
        code = encode_invite(host_world.invitation(slot), "127.0.0.1", entry.port)
        worker = self.worker_for(host_world)
        driver = Driver(("main", select("join")), ("join_list", select("new")),
                        ("join_new", select("join", code=code, name="", address="", port="")),
                        ("create_character", select("go")), ("join_list", BACK), main_exit())
        app, _ = pc.app(driver, worker=worker, creator=self.creator_for(player_id), lan=LOOPBACK_LAN)
        try:
            app.run()
        except AssertionError:
            import traceback
            if app.last_error is not None:
                traceback.print_exception(app.last_error)
            raise
        self.assertTrue(driver.done(), driver.steps)
        return app, worker

    def test_host_then_two_friends_each_create_their_own_character_and_reconnect_to_it(self):
        _, entry, host_world = self.build_world()
        # 1. The host's first time: character created and enrolled automatically, then the game starts as that character.
        app, worker = self.host_first_time(entry, host_world)
        host_id = host_world.accounts[0].player_id
        self.assertEqual(len(worker.requests), 2)
        self.assertEqual(self.head(host_world, host_id), 1)
        self.assertEqual(character_state(self.world.private, entry.world_id, host_id), "ready")
        # 2. The world is served; each friend, on their own PC, joins with their own code and creates their own character.
        ServerThread(self, self.world.installation, host_world)
        pcs = {slot: self.world.peer(f"friend-pc-{slot}") for slot in (1, 2)}
        for slot, pc in pcs.items():
            _, friend_worker = self.join_first_time(pc, host_world, entry, slot)
            self.assertEqual(len(friend_worker.requests), 2)
            self.assertEqual(self.head(host_world, host_world.accounts[slot].player_id), 1)
        # 3. Three accounts, three different approved sources, three checkpoints: nothing shared.
        connection = sqlite3.connect(host_world.database_path)
        enrollments = dict(connection.execute("SELECT player_id, source_sha256 FROM ownership_enrollments").fetchall())
        checkpoints = connection.execute("SELECT player_id, payload FROM checkpoints WHERE revision = 1").fetchall()
        connection.close()
        self.assertEqual(set(enrollments), {account.player_id for account in host_world.accounts[:3]})
        self.assertEqual(len(set(enrollments.values())), 3)
        self.assertEqual(len(checkpoints), 3)
        for player_id, payload in checkpoints:
            owner = inspect_ownership(inspect_flash(payload, save_profile=OWNERSHIP_PROFILE))
            self.assertEqual((owner.world_id, owner.player_id), (entry.world_id, player_id))     # every save names its own account
        self.assertEqual(len({hashlib.sha256(payload).hexdigest() for _, payload in checkpoints}), 3)
        # 4. On each PC the character is in the folder of that world account and nowhere else.
        for slot, pc in pcs.items():
            mine = profile_directory(pc.private, entry.world_id, host_world.accounts[slot].player_id)
            self.assertTrue((mine / "character.sav").is_file())
            other = 3 - slot
            self.assertFalse(profile_directory(pc.private, entry.world_id, host_world.accounts[other].player_id).exists())
            self.assertFalse(profile_directory(pc.private, entry.world_id, host_id).exists())
        # 5. Reconnect: Continue Adventure on a friend's PC joins straight into the same character, with no creation.
        pc = pcs[1]
        saved = (profile_directory(pc.private, entry.world_id, host_world.accounts[1].player_id) / "character.sav").read_bytes()
        worker = self.worker_for(host_world)
        driver = Driver(("main", select("continue")), ("main", select("exit")))
        app, _ = pc.app(driver, worker=worker, creator=self.creator_for(host_world.accounts[1].player_id), lan=LOOPBACK_LAN)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual([r.mode for r in worker.requests], ["join"])
        self.assertEqual((profile_directory(pc.private, entry.world_id, host_world.accounts[1].player_id) / "character.sav").read_bytes(), saved)
        # 6. The host rehosts: its own character again, immediately.
        worker = self.worker_for(host_world)
        driver = Driver(("main", select("continue")), ("main", select("exit")))
        app, _ = self.world.app(driver, worker=worker, creator=self.creator_for(host_id), lan=LOOPBACK_LAN)
        app.run()
        self.assertEqual([r.mode for r in worker.requests], ["host"])

    def test_two_players_on_one_pc_have_separate_saved_servers_and_characters(self):
        _, entry, host_world = self.build_world()
        self.host_first_time(entry, host_world)
        ServerThread(self, self.world.installation, host_world)
        pc = self.world.peer("shared-pc")
        for slot in (1, 2):
            self.join_first_time(pc, host_world, entry, slot)
        # Both players' characters are on the one PC, each in its own account folder; each has its own saved server.
        folders = {slot: profile_directory(pc.private, entry.world_id, host_world.accounts[slot].player_id) for slot in (1, 2)}
        self.assertNotEqual(folders[1], folders[2])
        saves = {slot: (folder / "character.sav").read_bytes() for slot, folder in folders.items()}
        self.assertNotEqual(saves[1], saves[2])
        app, _ = pc.app(Driver(("main", select("join")), ("join_list", BACK), main_exit()), lan=LOOPBACK_LAN)
        app.run()
        self.assertEqual(len(app.servers.all()), 2)
        self.assertEqual(len({s["player_id"] for s in app.servers.all()}), 2)

    def test_no_character_is_created_while_the_server_is_down_and_nothing_is_duplicated_after(self):
        _, entry, host_world = self.build_world()
        self.host_first_time(entry, host_world)
        pc = self.world.peer("late-pc")
        code = encode_invite(host_world.invitation(1), "127.0.0.1", entry.port)
        # The server is down: joining a new server cannot verify it; nothing is saved or created.
        driver = Driver(("main", select("join")), ("join_list", select("new")),
                        ("join_new", select("join", code=code, name="", address="", port="")),
                        ("join_new", BACK), ("join_list", BACK), main_exit())
        app, _ = pc.app(driver, lan=LOOPBACK_LAN)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual(app.servers.all(), [])
        self.assertFalse((pc.private / "players").exists())
        self.assertEqual(self.head(host_world, host_world.accounts[1].player_id), 0)
        # Once the server is up the join works once, and joining again creates no second character.
        ServerThread(self, self.world.installation, host_world)
        self.join_first_time(pc, host_world, entry, 1)
        connection = sqlite3.connect(host_world.database_path)
        count = connection.execute("SELECT COUNT(*) FROM ownership_enrollments WHERE player_id = ?",
                                   (host_world.accounts[1].player_id,)).fetchone()[0]
        connection.close()
        self.assertEqual(count, 1)
        worker = self.worker_for(host_world)
        driver = Driver(("main", select("continue")), ("main", select("exit")))
        app2, _ = pc.app(driver, worker=worker, creator=self.creator_for(host_world.accounts[1].player_id), lan=LOOPBACK_LAN)
        app2.run()
        self.assertEqual([r.mode for r in worker.requests], ["join"])
        self.assertEqual(len(app2.servers.all()), 1)


if __name__ == "__main__":
    unittest.main()
