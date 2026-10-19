"""End to end through the in-game menu with real worlds, a real server over TLS, and the real registration of the player's
universal character in world accounts.

What is simulated, honestly: the game process (a placeholder child), the game's save mailbox (the existing
``NativeEnrollmentFixture``), the New Game itself (a synthetic unassigned save per character) and, where a test says so, the game
saving progress (a new world save written where the game writes it). Everything else is the shipping code: world creation, the
registry, the character library, invite codes, certificate pinning, the authenticated connection, the server's enrollment and
transfer checks and per-player checkpoint storage. These are single-machine runs: the "PCs" are separate private folders on one
computer, so they say nothing about two real PCs or networks.
"""
import asyncio
import hashlib
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from emerald_multiplayer.character_links import character_state, profile_directory
from emerald_multiplayer.character_play import register_character
from emerald_multiplayer.companion import Companion
from emerald_multiplayer.flash import LAYOUT_ID, OWNERSHIP_LAYOUT_ID, inspect_flash
from emerald_multiplayer.host_world import HostWorld
from emerald_multiplayer.invite_code import encode_invite
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, extract_source_inventory, inspect_ownership
from emerald_multiplayer.ownership_storage import AllocationGrant
from process_fixture import direct_python
from shell_fixture import BACK, Driver, FakeWorker, ServerThread, World, lan_of, select
from test_enrollment_runtime import NativeEnrollmentFixture
from test_ownership_storage import owned_flash, source_flash
from test_shell_app import create_world_steps, main_exit

LOOPBACK_LAN = lan_of("127.0.0.1")


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.world = World(self)
        self.native = NativeEnrollmentFixture(self)
        self.companions, self.children = [], []
        self.personality = 1000
        self.real_spawn = asyncio.create_subprocess_exec
        self.private = None
        self.registrations = []
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
        """The game's first save in the world: the character that was loaded (its outgoing save beside the account folder),
        with the identities the world just granted."""
        source = self.private.parent / f".{self.private.name}.outgoing-character.sav"
        records = extract_source_inventory(inspect_flash(source.read_bytes(), save_profile=LAYOUT_ID))
        keywords.pop("personalities", None)
        keywords["next_serial"] = grant.start + len(records)
        return owned_flash(grant, tuple((record.location, grant.start + i) for i, record in enumerate(records)),
                           personalities=tuple(record.personality for record in records), **keywords)

    async def drafter(self, installation, private_root, *, on_status=None):
        """The player's New Game, simulated: a closed, valid, unassigned save with one starter, unique to this character."""
        self.personality += 111
        folder = Path(private_root) / "drafts" / str(uuid4())
        folder.mkdir(parents=True)
        path = folder / "character.sav"
        payload = source_flash(personalities=(self.personality,))
        path.write_bytes(payload)
        return SimpleNamespace(source_path=path, sha256=hashlib.sha256(payload).hexdigest(), party_count=1)

    async def register(self, *args, **options):
        """The shipping registration; each one is a fresh game process with no ownership yet."""
        self.native.grant = None
        self.registrations.append((options["role"], options["world_id"], options["player_id"]))
        return await register_character(*args, interval=0.01, **options)

    def app(self, pc, driver, worker=None):
        return pc.app(driver, worker=worker, drafter=self.drafter, register=self.register, lan=LOOPBACK_LAN)

    @staticmethod
    def head(world, player_id):
        connection = sqlite3.connect(world.database_path)
        try:
            row = connection.execute("SELECT latest_revision FROM players WHERE player_id = ?", (player_id,)).fetchone()
        finally:
            connection.close()
        return row[0] if row else 0

    def worker_for(self, world, *, plays=None):
        """The session worker: 'enrollment_required' unless the world holds a checkpoint for that account, then 'game_closed'
        (``plays(request)`` first stands for the game saving progress)."""
        def behaviour(request):
            if not self.head(world, self.account_of(request)):
                return "enrollment_required"
            if plays is not None:
                plays(request)
            return "game_closed"
        return FakeWorker(behaviour)

    def account_of(self, request):
        if request.mode == "host":
            return HostWorld.open(request.selection.parent, self.world.rom, self.world.manifest).accounts[0].player_id
        from emerald_multiplayer.invitations import Invitation
        return Invitation.load(request.selection).player_id

    def build_world(self, name="Kevin's world"):
        driver = Driver(("main", select("host")), ("confirm", select("yes")), ("create_character", select("go")),
                        ("host_list", select("create")), *create_world_steps(name, "Kevin")[2:],
                        ("world", BACK), ("host_list", BACK), main_exit())
        app, _ = self.app(self.world, driver)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        entry = next(e for e in app.registry.entries() if e.name == name)
        return entry, HostWorld.open(entry.folder, self.world.rom, self.world.manifest)

    def host_first_time(self, entry, host_world):
        worker = self.worker_for(host_world)
        driver = Driver(("main", select("host")), ("host_list", select(entry.world_id)), ("world", select("host")),
                        ("bring_character", select("go")), ("host_list", BACK), main_exit())
        app, _ = self.app(self.world, driver, worker)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        return app, worker

    def join_steps(self, host_world, entry, slot, *, create=True):
        code = encode_invite(host_world.invitation(slot), "127.0.0.1", entry.port)
        steps = [("main", select("join")), ("join_list", select("new")),
                 ("join_new", select("join", code=code, name="", address="", port=""))]
        if create:
            steps += [("confirm", select("yes")), ("create_character", select("go"))]
        return steps + [("bring_character", select("go")), ("join_list", BACK), main_exit()]

    def join_first_time(self, pc, host_world, entry, slot, *, create=True):
        worker = self.worker_for(host_world)
        driver = Driver(*self.join_steps(host_world, entry, slot, create=create))
        app, _ = self.app(pc, driver, worker)
        try:
            app.run()
        except AssertionError:
            import traceback
            if app.last_error is not None:
                traceback.print_exception(app.last_error)
            raise
        self.assertTrue(driver.done(), driver.steps)
        return app, worker

    def test_host_then_two_friends_each_bring_their_own_character_and_reconnect_to_it(self):
        entry, host_world = self.build_world()
        # 1. The host's character enters the host's world once (the game opens on it), then the world starts as that character.
        app, worker = self.host_first_time(entry, host_world)
        host_id = host_world.accounts[0].player_id
        self.assertEqual(len(worker.requests), 1)
        self.assertEqual(self.head(host_world, host_id), 1)
        self.assertEqual(character_state(self.world.private, entry.world_id, host_id), "ready")
        (host_character,) = app.library.all()
        self.assertEqual((host_character.world_id, host_character.player_id), (entry.world_id, host_id))
        # 2. The world is served; each friend, on their own PC, creates their one character and joins with their own code.
        server = ServerThread(self, self.world.installation, host_world)
        pcs = {slot: self.world.peer(f"friend-pc-{slot}") for slot in (1, 2)}
        for slot, pc in pcs.items():
            _, friend_worker = self.join_first_time(pc, host_world, entry, slot)
            self.assertEqual(len(friend_worker.requests), 1)
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
        # 4. On each PC the character's world save is in the folder of that world account and nowhere else.
        for slot, pc in pcs.items():
            mine = profile_directory(pc.private, entry.world_id, host_world.accounts[slot].player_id)
            self.assertTrue((mine / "character.sav").is_file())
            self.assertFalse(profile_directory(pc.private, entry.world_id, host_world.accounts[3 - slot].player_id).exists())
            self.assertFalse(profile_directory(pc.private, entry.world_id, host_id).exists())
        # 5. Reconnect: Continue Adventure on a friend's PC joins straight in with the same character: nothing to create or register.
        pc = pcs[1]
        saved = (profile_directory(pc.private, entry.world_id, host_world.accounts[1].player_id) / "character.sav").read_bytes()
        before = len(self.registrations)
        worker = self.worker_for(host_world)
        driver = Driver(("main", select("continue")), main_exit())
        app, _ = self.app(pc, driver, worker)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual([r.mode for r in worker.requests], ["join"])
        self.assertEqual(len(self.registrations), before)
        self.assertEqual((profile_directory(pc.private, entry.world_id, host_world.accounts[1].player_id) / "character.sav").read_bytes(), saved)
        # 6. The host hosts again (their world is closed in between): their own character, immediately.
        server.stop()
        worker = self.worker_for(host_world)
        driver = Driver(("main", select("continue")), main_exit())
        app, _ = self.app(self.world, driver, worker)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual([r.mode for r in worker.requests], ["host"])
        self.assertEqual(len(self.registrations), before)

    def test_two_players_on_one_pc_each_have_their_own_character_and_saved_server(self):
        entry, host_world = self.build_world()
        self.host_first_time(entry, host_world)
        ServerThread(self, self.world.installation, host_world)
        pc = self.world.peer("shared-pc")
        self.join_first_time(pc, host_world, entry, 1)
        # The second player creates their own character (Characters), which becomes the one playing, then joins with their code.
        driver = Driver(("main", select("characters")), ("characters", select("create")), ("create_character", select("go")),
                        ("characters", BACK), main_exit())
        self.app(pc, driver)[0].run()
        self.assertTrue(driver.done(), driver.steps)
        app, _ = self.join_first_time(pc, host_world, entry, 2, create=False)
        characters = {(c.world_id, c.player_id): c for c in app.library.all()}
        self.assertEqual(set(characters), {(entry.world_id, host_world.accounts[slot].player_id) for slot in (1, 2)})
        folders = {slot: profile_directory(pc.private, entry.world_id, host_world.accounts[slot].player_id) for slot in (1, 2)}
        saves = {slot: (folder / "character.sav").read_bytes() for slot, folder in folders.items()}
        self.assertNotEqual(saves[1], saves[2])
        self.assertEqual(len({s["player_id"] for s in app.servers.all()}), 2)

    def test_no_character_is_created_while_the_server_is_down_and_nothing_is_duplicated_after(self):
        entry, host_world = self.build_world()
        self.host_first_time(entry, host_world)
        pc = self.world.peer("late-pc")
        code = encode_invite(host_world.invitation(1), "127.0.0.1", entry.port)
        # The server is down: joining cannot verify it; nothing is saved or created, and nothing falls back to Solo.
        seen = []
        driver = Driver(("main", select("join")), ("join_list", select("new")),
                        ("join_new", select("join", code=code, name="", address="", port="")),
                        ("offline", select("back")), ("join_new", lambda s: seen.append(s.status) or BACK), ("join_list", BACK),
                        main_exit())
        app, _ = self.app(pc, driver)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual(seen[0][0], "error")
        self.assertEqual((app.servers.all(), app.library.all(), app.registry.entries()), ([], [], []))
        self.assertFalse((pc.private / "players").exists())
        self.assertEqual(self.head(host_world, host_world.accounts[1].player_id), 0)
        # Once the server is up the join works once, and playing again registers nothing a second time.
        ServerThread(self, self.world.installation, host_world)
        self.join_first_time(pc, host_world, entry, 1)
        connection = sqlite3.connect(host_world.database_path)
        count = connection.execute("SELECT COUNT(*) FROM ownership_enrollments WHERE player_id = ?",
                                   (host_world.accounts[1].player_id,)).fetchone()[0]
        connection.close()
        self.assertEqual(count, 1)
        before = len(self.registrations)
        worker = self.worker_for(host_world)
        driver = Driver(("main", select("continue")), main_exit())
        app2, _ = self.app(pc, driver, worker)
        app2.run()
        self.assertEqual([r.mode for r in worker.requests], ["join"])
        self.assertEqual((len(app2.servers.all()), len(app2.library.all()), len(self.registrations)), (1, 1, before))

    def test_one_character_plays_a_friends_world_then_solo_then_returns_with_what_it_caught(self):
        entry, host_world = self.build_world()
        self.host_first_time(entry, host_world)
        server = ServerThread(self, self.world.installation, host_world)
        pc = self.world.peer("friend-pc")
        friend_id = host_world.accounts[1].player_id
        self.join_first_time(pc, host_world, entry, 1)
        first = self.personality

        # Solo: a new world of the friend's own, the same character, no New Game. In it the game saves a second Pokemon.
        caught = 4242

        def catch(request):
            solo = HostWorld.open(request.selection.parent, self.world.rom, self.world.manifest)
            account = solo.accounts[0].player_id
            grant = AllocationGrant(solo.world_id, account, str(uuid4()), 500, 532, 1, 1, 0)
            folder = profile_directory(pc.private, solo.world_id, account)
            (folder / "character.sav").write_bytes(owned_flash(grant, (("party:0", 500), ("box:0:3", 501)), personalities=(first, caught)))
        driver = Driver(("main", select("solo")), ("solo", select("new")), ("ask_text", select("ok", value="My own world")),
                        ("bring_character", select("go")), main_exit())
        app, _ = self.app(pc, driver)
        app.worker = FakeWorker(lambda request: catch(request) or "game_closed")
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        (solo_entry,) = [e for e in app.registry.entries() if e.name == "My own world"]
        solo_world = HostWorld.open(solo_entry.folder, self.world.rom, self.world.manifest)
        self.assertEqual(self.head(solo_world, solo_world.accounts[0].player_id), 1)
        (character,) = app.library.all()
        self.assertEqual(character.world_id, solo_entry.world_id)

        # Back to the friend's world: the character comes back with both Pokemon; the first visit's save is kept beside it.
        worker = self.worker_for(host_world)
        driver = Driver(("main", select("join")), ("join_list", lambda s: select(s.items[1].id)), ("server", select("join")),
                        ("bring_character", lambda s: self.assertIn("played somewhere else", " ".join(s.notes)) or select("go")),
                        ("join_list", BACK), main_exit())
        app, _ = self.app(pc, driver, worker)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual(self.head(host_world, friend_id), 2)
        # The character's latest save is the one the friend's world saved for it (the world's acknowledged export).
        (character,) = app.library.all()
        self.assertEqual((character.world_id, character.player_id), (entry.world_id, friend_id))
        owned = inspect_ownership(inspect_flash(app.library.save_bytes(character), save_profile=OWNERSHIP_LAYOUT_ID))
        self.assertEqual((owned.world_id, owned.player_id), (entry.world_id, friend_id))
        self.assertEqual(sorted(r.personality for r in owned.records), sorted([first, caught]))
        self.assertTrue(any((profile_directory(pc.private, entry.world_id, friend_id) / "previous-saves").iterdir()))
        statuses = server.query("SELECT status FROM ownership_instances WHERE player_id = ? ORDER BY serial", friend_id)
        self.assertEqual([row[0] for row in statuses].count("active"), 2)

    def test_a_solo_character_joins_a_friends_world_without_a_second_new_game_or_a_conflict(self):
        """Problem C: a character made and played Solo joins a friend's world as itself (no New Game, no duplicate error)."""
        entry, host_world = self.build_world()
        self.host_first_time(entry, host_world)
        ServerThread(self, self.world.installation, host_world)
        pc = self.world.peer("solo-player")
        driver = Driver(("main", select("solo")), ("confirm", select("yes")), ("create_character", select("go")),
                        ("solo", select("new")), ("ask_text", select("ok", value="My adventure")), ("bring_character", select("go")),
                        main_exit())
        app, _ = self.app(pc, driver, FakeWorker(lambda request: "game_closed"))
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        (character,) = app.library.all()
        (solo,) = app.registry.entries()
        solo_world = HostWorld.open(solo.folder, self.world.rom, self.world.manifest)
        self.assertEqual(self.head(solo_world, solo_world.accounts[0].player_id), 1)
        solo_save = (profile_directory(pc.private, solo.world_id, solo_world.accounts[0].player_id) / "character.sav").read_bytes()
        drafts = self.personality
        # Join Friend with the friend's code: the same character, its first visit there.
        app, worker = self.join_first_time(pc, host_world, entry, 1, create=False)
        self.assertEqual(self.personality, drafts)                         # no second New Game
        friend_id = host_world.accounts[1].player_id
        self.assertEqual(self.head(host_world, friend_id), 1)
        (same,) = app.library.all()
        self.assertEqual((same.character_id, same.world_id, same.player_id), (character.character_id, entry.world_id, friend_id))
        owned = inspect_ownership(inspect_flash(app.library.save_bytes(same), save_profile=OWNERSHIP_LAYOUT_ID))
        self.assertEqual(sorted(r.personality for r in owned.records), [drafts])     # its starter came with it
        self.assertEqual([r.mode for r in worker.requests], ["join"])
        # The Solo world still holds its own save of the character, untouched.
        self.assertEqual((profile_directory(pc.private, solo.world_id, solo_world.accounts[0].player_id) / "character.sav").read_bytes(),
                         solo_save)

    def test_a_friend_who_cannot_reach_the_host_joins_through_the_relay_with_the_real_registration(self):
        """The host's PC cannot be reached at the address in the code (as behind CGNAT): the code also names the world's relay,
        the check finds the relay route, and the character's registration and the game both use it. TLS stays end to end."""
        from emerald_multiplayer.network_settings import NetworkSettings, load_join_route
        from shell_fixture import free_port
        entry, host_world = self.build_world()
        self.host_first_time(entry, host_world)
        relay_port = free_port()
        settings = NetworkSettings(self.world.private)
        settings.set_relay(entry.world_id, "127.0.0.1", relay_port)
        server = ServerThread(self, self.world.installation, host_world, relay=(relay_port, settings.get(entry.world_id).relay_secret))
        unreachable = free_port()                                     # nothing listens there: the direct route is refused
        code = encode_invite(host_world.invitation(1), "127.0.0.1", unreachable, relay=("127.0.0.1", relay_port))
        pc = self.world.peer("friend-behind-cgnat")
        worker = self.worker_for(host_world)
        driver = Driver(("main", select("join")), ("join_list", select("new")),
                        ("join_new", select("join", code=code, name="", address="", port="")),
                        ("confirm", select("yes")), ("create_character", select("go")), ("bring_character", select("go")),
                        ("join_list", BACK), main_exit())
        app, _ = self.app(pc, driver, worker)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        friend_id = host_world.accounts[1].player_id
        self.assertEqual(self.head(host_world, friend_id), 1)               # registered through the relay
        (saved,) = app.servers.all()
        self.assertEqual((saved["port"], saved["relay"]), (unreachable, {"address": "127.0.0.1", "port": relay_port}))
        self.assertEqual(load_join_route(profile_directory(pc.private, entry.world_id, friend_id)), ("127.0.0.1", relay_port))
        (request,) = worker.requests
        self.assertEqual((request.mode, request.route), ("join", None))     # the game reads the relay route itself
        # Nothing ever listened at the code's own address: everything above went through the relay's room for this world.
        import socket
        with self.assertRaises(ConnectionRefusedError), socket.create_connection(("127.0.0.1", unreachable), timeout=2):
            pass
        self.assertIn(entry.world_id, server.relay_server.rooms)


if __name__ == "__main__":
    unittest.main()
