"""Join Friend from the in-game menu against a real server (real TLS, real world identity): invite codes, saved servers,
and the player's one universal character entering friends' worlds without a New Game."""
import unittest

from emerald_multiplayer.character_library import CharacterLibrary
from emerald_multiplayer.character_links import character_state, profile_directory
from emerald_multiplayer.host_world import HostWorld
from emerald_multiplayer.invitations import Invitation
from emerald_multiplayer.invite_code import encode_invite
from emerald_multiplayer.saved_servers import invitation_path
from shell_fixture import BACK, Driver, FakeWorker, ServerThread, World, fake_drafter, fake_register, label_id, select
from test_shell_app import create_world_steps, library_character, main_exit

LOOPBACK_LAN = lambda: ["127.0.0.1"]


class JoinFixture(unittest.TestCase):
    """A host PC with a world (created through the menu), a server for it, and invite codes for its friend accounts."""

    def setUp(self):
        self.world = World(self)
        self.entry = self.host_world_named("Kevin's world")
        self.host_world = HostWorld.open(self.entry.folder, self.world.rom, self.world.manifest)
        self.server = ServerThread(self, self.world.installation, self.host_world)
        self.port = self.entry.port

    def host_world_named(self, name, host="Kevin"):
        if not CharacterLibrary(self.world.private).all():
            library_character(self.world)
        driver = Driver(*create_world_steps(name, host), ("world", BACK), ("host_list", BACK), main_exit())
        app, _ = self.world.app(driver, lan=LOOPBACK_LAN)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        return next(entry for entry in app.registry.entries() if entry.name == name)

    def code(self, slot, host_world=None, port=None):
        return encode_invite((host_world or self.host_world).invitation(slot), "127.0.0.1", port or self.port)

    def friend(self, name="friend-pc", *, character=True):
        pc = self.world.peer(name)
        if character:
            library_character(pc, personality=31)
        return pc

    def join_steps(self, code, *, then=()):
        return [("main", select("join")), ("join_list", select("new")),
                ("join_new", select("join", code=code, name="", address="", port=""))] + list(then)

    def account(self, slot=1):
        return self.entry.accounts[slot][1]


class JoinNewServerTests(JoinFixture):
    def test_pasting_an_invite_code_saves_the_server_and_brings_the_character_in_once(self):
        pc = self.friend()
        registrations, worker = [], FakeWorker(lambda request: "game_closed")
        driver = Driver(*self.join_steps(self.code(1), then=[
            ("bring_character", lambda s: self.assertIn("first visit", " ".join(s.notes)) or select("go")),
            ("join_list", BACK), main_exit()]))
        app, _ = pc.app(driver, worker=worker, register=fake_register(registrations), lan=LOOPBACK_LAN)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        (server,) = app.servers.all()
        self.assertEqual((server["world_id"], server["player_id"], server["slot"]), (self.entry.world_id, self.account(), 1))
        self.assertEqual((server["address"], server["port"]), ("127.0.0.1", self.port))
        # The private invitation copy lives in the account's own folder; the credential never enters the shortcut file.
        copy = invitation_path(pc.private, self.entry.world_id, self.account())
        self.assertEqual(Invitation.load(copy).credential, self.host_world.invitation(1).credential)
        shell_files = b"".join(p.read_bytes() for p in (pc.private / "shell").glob("*.json"))
        self.assertNotIn(self.host_world.invitation(1).credential.hex().encode(), shell_files)
        (registration,) = registrations
        self.assertEqual((registration["role"], registration["world_id"], registration["player_id"]),
                         ("friend", self.entry.world_id, self.account()))
        self.assertEqual((registration["options"]["invitation_path"], registration["options"]["route_port"]), (copy, self.port))
        (request,) = worker.requests
        self.assertEqual((request.mode, request.selection, request.route), ("join", copy, ("127.0.0.1", self.port)))
        link = app.links.get(self.entry.world_id, self.account())
        self.assertEqual((link["role"], link["stage"], link["display_name"]), ("friend", "enrolled", "Player 2"))
        (character,) = app.library.all()
        self.assertEqual((character.world_id, character.player_id), (self.entry.world_id, self.account()))

    def test_a_new_player_creates_one_character_then_joins_with_it(self):
        pc = self.friend(character=False)
        drafts, registrations = [], []
        driver = Driver(*self.join_steps(self.code(1), then=[
            ("confirm", lambda s: self.assertIn("one character everywhere", " ".join(s.notes)) or select("yes")),
            ("create_character", select("go")), ("bring_character", select("go")), ("join_list", BACK), main_exit()]))
        app, _ = pc.app(driver, drafter=fake_drafter(drafts), register=fake_register(registrations), lan=LOOPBACK_LAN)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual(drafts, ["draft"])
        (character,) = app.library.all()
        self.assertEqual([r["character_id"] for r in registrations], [character.character_id])

    def test_next_time_continue_and_join_friend_play_the_same_character_with_nothing_to_create_or_register(self):
        pc = self.friend()
        driver = Driver(*self.join_steps(self.code(1), then=[("bring_character", select("go")), ("join_list", BACK), main_exit()]))
        pc.app(driver, lan=LOOPBACK_LAN)[0].run()
        self.assertTrue(driver.done(), driver.steps)
        drafts, registrations, worker = [], [], FakeWorker(lambda request: "game_closed")
        seen = {}

        def main(screen):
            row = next(i for i in screen.items if i.id == "continue")
            seen["row"] = (row.flags, row.detail)
            return select("continue")
        driver = Driver(("main", main), ("main", select("join")),
                        ("join_list", lambda s: select(label_id(s, "Player 2's server"))), ("server", select("join")),
                        ("join_list", BACK), main_exit())
        app, _ = pc.app(driver, worker=worker, drafter=fake_drafter(drafts), register=fake_register(registrations), lan=LOOPBACK_LAN)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertNotIn("d", seen["row"][0])
        self.assertIn("Player 2's server", seen["row"][1])
        self.assertEqual((drafts, registrations), ([], []))                     # no creation, no registration, no selecting
        self.assertEqual([r.mode for r in worker.requests], ["join", "join"])
        self.assertEqual({r.selection for r in worker.requests}, {invitation_path(pc.private, self.entry.world_id, self.account())})

    def test_two_friends_each_get_their_own_account_with_their_own_character(self):
        results = {}
        for slot in (1, 2):
            pc = self.friend(f"pc-{slot}")
            driver = Driver(*self.join_steps(self.code(slot), then=[("bring_character", select("go")), ("join_list", BACK), main_exit()]))
            app, _ = pc.app(driver, lan=LOOPBACK_LAN)
            app.run()
            self.assertTrue(driver.done(), driver.steps)
            results[slot] = (pc, app)
        for slot in (1, 2):
            pc, app = results[slot]
            (character,) = app.library.all()
            self.assertEqual((character.world_id, character.player_id), (self.entry.world_id, self.account(slot)))
            self.assertEqual(character_state(pc.private, self.entry.world_id, self.account(slot)), "ready")
        # The other friend's account has nothing on this PC at all.
        self.assertEqual(character_state(results[1][0].private, self.entry.world_id, self.account(2)), "none")

    def test_one_character_enters_two_friends_worlds_and_stays_one_character(self):
        second = self.host_world_named("Second world")
        second_world = HostWorld.open(second.folder, self.world.rom, self.world.manifest)
        ServerThread(self, self.world.installation, second_world)
        pc = self.friend()
        registrations, worker = [], FakeWorker(lambda request: "game_closed")
        steps = []
        for host_world, entry in ((self.host_world, self.entry), (second_world, second)):
            steps += self.join_steps(self.code(1, host_world, entry.port), then=[("bring_character", select("go")), ("join_list", BACK)])
        driver = Driver(*steps, main_exit())
        app, _ = pc.app(driver, worker=worker, register=fake_register(registrations), lan=LOOPBACK_LAN)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        servers = app.servers.all()
        self.assertEqual(len({(s["world_id"], s["player_id"]) for s in servers}), 2)
        self.assertEqual(len(app.library.all()), 1)
        self.assertEqual(len({r["character_id"] for r in registrations}), 1)
        self.assertEqual({r["world_id"] for r in registrations}, {self.entry.world_id, second.world_id})
        self.assertEqual({r.selection for r in worker.requests}, {invitation_path(pc.private, s["world_id"], s["player_id"]) for s in servers})

    def test_bad_codes_say_what_is_wrong_and_change_nothing(self):
        pc = self.friend()
        good = self.code(1)
        messages = []

        def capture(screen):
            messages.append(screen.status[1])
            return BACK
        driver = Driver(("main", select("join")), ("join_list", select("new")),
                        ("join_new", select("join", code="", name="", address="", port="")),
                        ("join_new", select("join", code="ET1-AAAA-BBBB", name="", address="", port="")),
                        ("join_new", select("join", code=good[:-6] + "AAAAAA", name="", address="", port="")),
                        ("join_new", select("join", code=good, name="", address="256.1.1.1", port="")),
                        ("join_new", select("join", code=good, name="", address="", port="70000")),
                        ("join_new", capture), ("join_list", BACK), main_exit())
        registrations = []
        app, _ = pc.app(driver, register=fake_register(registrations), lan=LOOPBACK_LAN)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual((app.servers.all(), registrations), ([], []))
        self.assertFalse((pc.private / "players").exists())
        self.assertTrue(all(messages))

    def test_an_invitation_file_path_works_where_a_code_does(self):
        pc = self.friend()
        path = self.world.root / "friend.json"
        self.host_world.export_invitation(1, path)
        worker = FakeWorker(lambda request: "game_closed")
        driver = Driver(*self.join_steps(str(path), then=[("bring_character", select("go")), ("join_list", BACK), main_exit()]))
        app, _ = pc.app(driver, worker=worker, lan=LOOPBACK_LAN)
        # The file points at the address chosen at world creation (127.0.0.1 here), so it reaches the test server.
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual(len(app.servers.all()), 1)
        self.assertEqual(len(worker.requests), 1)


class OfflineAndEditTests(JoinFixture):
    def join_once(self, pc):
        driver = Driver(*self.join_steps(self.code(1), then=[("bring_character", select("go")), ("join_list", BACK), main_exit()]))
        app, _ = pc.app(driver, lan=LOOPBACK_LAN)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        return app

    def saved(self, pc):
        return pc.app(Driver(), lan=LOOPBACK_LAN)[0].servers.all()[0]

    def test_a_server_that_is_down_says_so_starts_nothing_and_retry_works_once_it_is_back(self):
        pc = self.friend()
        self.join_once(pc)
        self.server.stop()
        saves = lambda: {p: p.read_bytes() for p in pc.private.rglob("*") if p.is_file() and (p.suffix == ".sav" or "players" in p.parts)}
        before = saves()
        seen, revived = [], []

        def offline(screen):
            seen.append(" ".join(screen.notes))
            return select("retry")

        def second_offline(screen):
            seen.append(" ".join(screen.notes))
            revived.append(ServerThread(self, self.world.installation, HostWorld.open(self.entry.folder, self.world.rom, self.world.manifest)))
            return select("retry")
        registrations, worker = [], FakeWorker(lambda request: "game_closed")
        driver = Driver(("main", select("join")), ("join_list", lambda s: select(label_id(s, "Player 2's server"))),
                        ("server", select("join")), ("offline", offline), ("offline", second_offline),
                        ("join_list", BACK), main_exit())
        app, _ = pc.app(driver, worker=worker, register=fake_register(registrations), lan=LOOPBACK_LAN)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertTrue(all("Nothing was created or reset" in text for text in seen))
        self.assertEqual(len(worker.requests), 1)                                   # started only once the server answered
        self.assertEqual(registrations, [])                                         # the character was already there
        self.assertTrue(before == saves())                                          # no character created, reset or rewritten

    def test_a_down_server_never_falls_back_to_solo_or_creates_a_character(self):
        pc = self.friend()
        self.server.stop()
        registrations, worker = [], FakeWorker(lambda request: "game_closed")
        seen = []
        driver = Driver(*self.join_steps(self.code(1), then=[("join_new", lambda s: seen.append(s.status) or BACK),
                                                             ("join_list", BACK), main_exit()]))
        app, _ = pc.app(driver, worker=worker, register=fake_register(registrations), lan=LOOPBACK_LAN)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual(seen[0][0], "error")
        self.assertIn("could not be reached", seen[0][1])
        self.assertEqual((worker.requests, registrations, app.servers.all(), app.registry.entries()), ([], [], [], []))

    def test_a_wrong_server_at_the_address_is_refused_by_world_identity_not_by_address(self):
        pc = self.friend()
        self.join_once(pc)
        self.server.stop()
        impostor_entry = self.host_world_named("Impostor", "Mallory")
        ServerThread(self, self.world.installation, HostWorld.open(impostor_entry.folder, self.world.rom, self.world.manifest))
        server = self.saved(pc)
        pc.app(Driver(), lan=LOOPBACK_LAN)[0].servers.edit(server["id"], port=impostor_entry.port)
        messages = []

        def refused(screen):
            messages.append(" ".join(screen.notes))
            return select("back")
        registrations, worker = [], FakeWorker(lambda request: "game_closed")
        driver = Driver(("main", select("join")), ("join_list", lambda s: select(label_id(s, "Player 2's server"))),
                        ("server", select("join")), ("offline", refused), ("join_list", BACK), main_exit())
        app, _ = pc.app(driver, worker=worker, register=fake_register(registrations), lan=LOOPBACK_LAN)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertIn("not this world", messages[0])
        self.assertEqual((worker.requests, registrations), ([], []))

    def test_a_changed_host_address_is_followed_by_editing_the_shortcut_and_the_character_stays(self):
        pc = self.friend()
        self.join_once(pc)
        server = self.saved(pc)
        pc.app(Driver(), lan=LOOPBACK_LAN)[0].servers.edit(server["id"], port=self.port + 1 if self.port < 65535 else self.port - 1)
        registrations, worker = [], FakeWorker(lambda request: "game_closed")
        driver = Driver(("main", select("join")), ("join_list", lambda s: select(label_id(s, "Player 2's server"))),
                        ("server", select("join")), ("offline", select("edit")),
                        ("edit_server", select("save", name="Kevin at home", address="127.0.0.1", port=str(self.port))),
                        ("join_list", BACK), main_exit())
        # After the edit is saved the join is tried again at once and succeeds.
        app, _ = pc.app(driver, worker=worker, register=fake_register(registrations), lan=LOOPBACK_LAN)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        edited = app.servers.get(server["id"])
        self.assertEqual((edited["id"], edited["world_id"], edited["player_id"]), (server["id"], server["world_id"], server["player_id"]))
        self.assertEqual((edited["name"], edited["address"], edited["port"]), ("Kevin at home", "127.0.0.1", self.port))
        self.assertEqual((len(worker.requests), registrations), (1, []))
        self.assertEqual(worker.requests[0].selection, invitation_path(pc.private, server["world_id"], server["player_id"]))

    def test_removing_the_shortcut_keeps_the_character_and_the_same_code_brings_it_back(self):
        pc = self.friend()
        self.join_once(pc)
        save = profile_directory(pc.private, self.entry.world_id, self.account()) / "character.sav"
        original = save.read_bytes()
        driver = Driver(("main", select("join")), ("join_list", lambda s: select(label_id(s, "Player 2's server"))),
                        ("server", select("remove")), ("confirm", select("yes")), ("join_list", BACK), main_exit())
        app, _ = pc.app(driver, lan=LOOPBACK_LAN)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual(app.servers.all(), [])
        self.assertEqual(save.read_bytes(), original)
        self.assertEqual(len(app.library.all()), 1)
        # The same code again: back in with the same character, nothing created or registered.
        drafts, registrations, worker = [], [], FakeWorker(lambda request: "game_closed")
        driver = Driver(*self.join_steps(self.code(1), then=[("join_list", BACK), main_exit()]))
        app2, _ = pc.app(driver, worker=worker, drafter=fake_drafter(drafts), register=fake_register(registrations), lan=LOOPBACK_LAN)
        app2.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual((drafts, registrations), ([], []))
        self.assertEqual(len(app2.servers.all()), 1)
        self.assertEqual(worker.requests[0].selection, invitation_path(pc.private, self.entry.world_id, self.account()))
        self.assertEqual(save.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
