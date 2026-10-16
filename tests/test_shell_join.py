"""Join Server from the in-game menu against a real server: invite codes, saved servers, automatic character loading."""
from pathlib import Path
import unittest

from emerald_multiplayer.character_links import character_state, profile_directory
from emerald_multiplayer.host_world import HostWorld
from emerald_multiplayer.invitations import Invitation
from emerald_multiplayer.invite_code import encode_invite
from emerald_multiplayer.saved_servers import invitation_path
from shell_fixture import BACK, Driver, FakeWorker, ServerThread, World, choose_label, label_id, labels, select
from test_shell_app import create_world_steps, fake_creator, main_exit, make_character

LOOPBACK_LAN = lambda: ["127.0.0.1"]


class JoinFixture(unittest.TestCase):
    """A host PC with a world (created through the menu), a server for it, and invite codes for its friend accounts."""

    def setUp(self):
        self.world = World(self)
        driver = Driver(*create_world_steps("Kevin's world", "Kevin"), ("world", BACK), ("host_list", BACK), main_exit())
        app, _ = self.world.app(driver, lan=LOOPBACK_LAN)
        app.run()
        self.entry = app.registry.entries()[0]
        self.host_world = HostWorld.open(self.entry.folder, self.world.rom, self.world.manifest)
        self.server = ServerThread(self, self.world.installation, self.host_world)
        self.port = self.entry.port

    def code(self, slot):
        return encode_invite(self.host_world.invitation(slot), "127.0.0.1", self.port)

    def friend(self, name="friend-pc"):
        return self.world.peer(name)

    def join_steps(self, code, *, then=()):
        return [("main", select("join")), ("join_list", select("new")),
                ("join_new", select("join", code=code, name="", address="", port=""))] + list(then)


class JoinNewServerTests(JoinFixture):
    def test_pasting_an_invite_code_saves_the_server_and_links_the_account_for_good(self):
        pc = self.friend()
        calls = []
        worker = FakeWorker(lambda request: "game_closed" if character_state(pc.private, *self.ids(pc)) == "ready" else "enrollment_required")
        self.ids = lambda pc: (self.entry.world_id, self.entry.accounts[1][1])
        driver = Driver(*self.join_steps(self.code(1), then=[("create_character", select("go")), ("join_list", BACK), main_exit()]))
        app, _ = pc.app(driver, worker=worker, creator=fake_creator(calls), lan=LOOPBACK_LAN)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        (server,) = app.servers.all()
        self.assertEqual((server["world_id"], server["player_id"], server["slot"]), (self.entry.world_id, self.entry.accounts[1][1], 1))
        self.assertEqual((server["address"], server["port"]), ("127.0.0.1", self.port))
        # The private invitation copy lives in the character's own folder; the credential never enters the shortcut file.
        copy = invitation_path(pc.private, self.entry.world_id, self.entry.accounts[1][1])
        self.assertTrue(copy.is_file())
        self.assertEqual(Invitation.load(copy).credential, self.host_world.invitation(1).credential)
        shell_files = b"".join(p.read_bytes() for p in (pc.private / "shell").glob("*.json"))
        self.assertNotIn(self.host_world.invitation(1).credential.hex().encode(), shell_files)
        link = app.links.get(self.entry.world_id, self.entry.accounts[1][1])
        self.assertEqual((link["role"], link["stage"], link["display_name"]), ("friend", "enrolled", "Player 2"))
        self.assertEqual([c["role"] for c in calls], ["friend"])
        self.assertEqual(len(worker.requests), 2)
        request = worker.requests[0]
        self.assertEqual((request.mode, request.selection, request.route), ("join", copy, ("127.0.0.1", self.port)))

    def test_next_time_continue_and_join_server_load_the_same_character_with_nothing_to_select(self):
        pc = self.friend()
        worker = FakeWorker(lambda request: "game_closed" if character_state(pc.private, self.entry.world_id, self.entry.accounts[1][1]) == "ready"
                            else "enrollment_required")
        driver = Driver(*self.join_steps(self.code(1), then=[("create_character", select("go")), ("join_list", BACK), main_exit()]))
        pc.app(driver, worker=worker, creator=fake_creator([]), lan=LOOPBACK_LAN)[0].run()
        calls = []
        worker2 = FakeWorker(lambda request: "game_closed")
        seen = {}

        def main(screen):
            row = next(i for i in screen.items if i.id == "continue")
            seen["row"] = (row.flags, row.detail)
            return select("continue")
        driver = Driver(("main", main), ("main", select("join")),
                        ("join_list", lambda s: select(label_id(s, "Player 2's server"))), ("server", select("join")),
                        ("join_list", BACK), main_exit())
        app, _ = pc.app(driver, worker=worker2, creator=fake_creator(calls), lan=LOOPBACK_LAN)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertNotIn("d", seen["row"][0])
        self.assertIn("Player 2's server", seen["row"][1])
        self.assertEqual(calls, [])                                                    # no creation, no import, no selecting
        self.assertEqual([r.mode for r in worker2.requests], ["join", "join"])
        self.assertEqual({r.selection for r in worker2.requests},
                         {invitation_path(pc.private, self.entry.world_id, self.entry.accounts[1][1])})

    def test_two_friends_each_get_their_own_account_and_their_own_character(self):
        results = {}
        for slot in (1, 2):
            pc = self.friend(f"pc-{slot}")
            account = self.entry.accounts[slot][1]
            worker = FakeWorker(lambda request, pc=pc, account=account: "game_closed" if character_state(
                pc.private, self.entry.world_id, account) == "ready" else "enrollment_required")
            driver = Driver(*self.join_steps(self.code(slot), then=[("create_character", select("go")), ("join_list", BACK), main_exit()]))
            app, _ = pc.app(driver, worker=worker, creator=fake_creator([]), lan=LOOPBACK_LAN)
            app.run()
            results[slot] = (pc, app)
        a, b = results[1][1].links.all(), results[2][1].links.all()
        self.assertEqual(len(a), 1)
        self.assertEqual(len(b), 1)
        self.assertNotEqual(a[0]["player_id"], b[0]["player_id"])
        self.assertEqual(a[0]["world_id"], b[0]["world_id"])
        for slot in (1, 2):
            pc, _ = results[slot]
            save = profile_directory(pc.private, self.entry.world_id, self.entry.accounts[slot][1]) / "character.sav"
            self.assertIn(self.entry.accounts[slot][1].encode(), save.read_bytes())   # each save was made for its own account
        # The other friend's account has no character on this PC at all.
        self.assertEqual(character_state(results[1][0].private, self.entry.world_id, self.entry.accounts[2][1]), "none")

    def test_one_player_on_one_pc_in_two_worlds_has_two_separate_characters(self):
        # A second world on the same host PC, served too; the friend joins both from one PC.
        driver = Driver(*create_world_steps("Second world", "Kevin"), ("world", BACK), ("host_list", BACK), main_exit())
        app, _ = self.world.app(driver, lan=LOOPBACK_LAN)
        app.run()
        second = next(e for e in app.registry.entries() if e.name == "Second world")
        second_world = HostWorld.open(second.folder, self.world.rom, self.world.manifest)
        ServerThread(self, self.world.installation, second_world)
        pc = self.friend()
        worker = FakeWorker(lambda request: "game_closed")
        steps = []
        for host_world, entry in ((self.host_world, self.entry), (second_world, second)):
            code = encode_invite(host_world.invitation(1), "127.0.0.1", entry.port)
            steps += [("main", select("join")), ("join_list", select("new")),
                      ("join_new", select("join", code=code, name="", address="", port="")),
                      ("join_list", BACK)]
        driver = Driver(*steps, main_exit())
        app2, _ = pc.app(driver, worker=worker, creator=fake_creator([]), lan=LOOPBACK_LAN)
        app2.run()
        self.assertTrue(driver.done(), driver.steps)
        servers = app2.servers.all()
        self.assertEqual(len(servers), 2)
        self.assertEqual(len({(s["world_id"], s["player_id"]) for s in servers}), 2)
        folders = {profile_directory(pc.private, s["world_id"], s["player_id"]) for s in servers}
        self.assertEqual(len(folders), 2)
        self.assertEqual({r.selection for r in worker.requests}, {invitation_path(pc.private, s["world_id"], s["player_id"]) for s in servers})

    def test_bad_codes_say_what_is_wrong_and_change_nothing(self):
        pc = self.friend()
        good = self.code(1)
        messages = []

        def capture(screen):
            messages.append(screen.status[1])
            return BACK
        driver = Driver(("main", select("join")), ("join_list", select("new")),
                        ("join_new", select("join", code="", name="", address="", port="")), ("join_new", select("join", code="ET1-AAAA-BBBB", name="", address="", port="")),
                        ("join_new", select("join", code=good[:-6] + "AAAAAA", name="", address="", port="")),
                        ("join_new", select("join", code=good, name="", address="256.1.1.1", port="")),
                        ("join_new", select("join", code=good, name="", address="", port="70000")),
                        ("join_new", capture), ("join_list", BACK), main_exit())
        app, _ = pc.app(driver, lan=LOOPBACK_LAN)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual(app.servers.all(), [])
        self.assertFalse((pc.private / "players").exists())
        self.assertTrue(all(messages))

    def test_an_invitation_file_path_works_where_a_code_does(self):
        pc = self.friend()
        path = self.world.root / "friend.json"
        self.host_world.export_invitation(1, path)
        worker = FakeWorker(lambda request: "game_closed")
        driver = Driver(*self.join_steps(str(path), then=[("join_list", BACK), main_exit()]))
        app, _ = pc.app(driver, worker=worker, creator=fake_creator([]), lan=LOOPBACK_LAN)
        # The file points at the address chosen at world creation (127.0.0.1 here), so it reaches the test server.
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual(len(app.servers.all()), 1)
        self.assertEqual(len(worker.requests), 1)


class OfflineAndEditTests(JoinFixture):
    def join_once(self, pc, worker):
        driver = Driver(*self.join_steps(self.code(1), then=[("join_list", BACK), main_exit()]))
        app, _ = pc.app(driver, worker=worker, creator=fake_creator([]), lan=LOOPBACK_LAN)
        app.run()
        return app

    def test_a_server_that_is_down_gives_a_clear_message_and_creates_nothing_then_retry_works(self):
        pc = self.friend()
        self.join_once(pc, FakeWorker(lambda request: "game_closed"))
        # Take the server down: the saved server cannot be reached.
        self.server.stop()
        before = {p: p.read_bytes() for p in (pc.private / "players").rglob("*") if p.is_file()}
        worker = FakeWorker(lambda request: "game_closed")
        seen = []

        def offline(screen):
            seen.append(" ".join(screen.notes))
            return select("retry")
        self.assertFalse(worker.requests)
        # Bring it back during the second retry.
        revived = []

        def second_offline(screen):
            seen.append(" ".join(screen.notes))
            revived.append(ServerThread(self, self.world.installation, HostWorld.open(self.entry.folder, self.world.rom, self.world.manifest)))
            return select("retry")
        driver = Driver(("main", select("join")), ("join_list", lambda s: select(label_id(s, "Player 2's server"))),
                        ("server", select("join")), ("offline", offline), ("offline", second_offline),
                        ("join_list", BACK), main_exit())
        app, _ = pc.app(driver, worker=worker, creator=fake_creator([]), lan=LOOPBACK_LAN)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertTrue(all("Nothing was created or reset" in text for text in seen))
        self.assertEqual(len(worker.requests), 1)                                       # started only once the server answered
        after = {p: p.read_bytes() for p in (pc.private / "players").rglob("*") if p.is_file()}
        self.assertEqual(before, after)                                                  # no character created, reset or rewritten

    def test_a_wrong_server_at_the_address_is_refused_by_world_identity_not_by_address(self):
        pc = self.friend()
        self.join_once(pc, FakeWorker(lambda request: "game_closed"))
        self.server.stop()
        # A different world answers at the same address and port.
        driver = Driver(*create_world_steps("Impostor", "Mallory"), ("world", BACK), ("host_list", BACK), main_exit())
        app, _ = self.world.app(driver, lan=LOOPBACK_LAN)
        app.run()
        impostor_entry = next(e for e in app.registry.entries() if e.name == "Impostor")
        impostor = HostWorld.open(impostor_entry.folder, self.world.rom, self.world.manifest)
        # Serve the impostor on the saved server's port by editing the saved server to the impostor's port.
        ServerThread(self, self.world.installation, impostor)
        server = next(iter(SavedServersOf(pc)))
        messages = []

        def refused(screen):
            messages.append(" ".join(screen.notes))
            return select("back")
        app2, _ = pc.app(Driver(), lan=LOOPBACK_LAN)
        app2.servers.edit(server["id"], port=impostor_entry.port)
        worker = FakeWorker(lambda request: "game_closed")
        driver = Driver(("main", select("join")), ("join_list", lambda s: select(label_id(s, "Player 2's server"))),
                        ("server", select("join")), ("offline", refused), ("join_list", BACK), main_exit())
        app3, _ = pc.app(driver, worker=worker, creator=fake_creator([]), lan=LOOPBACK_LAN)
        app3.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertIn("not this world", messages[0])
        self.assertEqual(worker.requests, [])

    def test_a_changed_host_address_is_followed_by_editing_the_shortcut_and_the_character_stays_linked(self):
        pc = self.friend()
        self.join_once(pc, FakeWorker(lambda request: "game_closed"))
        app0, _ = pc.app(Driver(), lan=LOOPBACK_LAN)
        server = app0.servers.all()[0]
        app0.servers.edit(server["id"], port=self.port + 1 if self.port < 65535 else self.port - 1)    # the old address no longer works
        worker = FakeWorker(lambda request: "game_closed")
        port = str(self.port)
        driver = Driver(("main", select("join")), ("join_list", lambda s: select(label_id(s, "Player 2's server"))),
                        ("server", select("join")), ("offline", select("edit")),
                        ("edit_server", select("save", name="Kevin at home", address="127.0.0.1", port=port)),
                        ("join_list", BACK), main_exit())
        # After the edit is saved the join is tried again at once and succeeds.
        app, _ = pc.app(driver, worker=worker, creator=fake_creator([]), lan=LOOPBACK_LAN)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        edited = app.servers.get(server["id"])
        self.assertEqual((edited["id"], edited["world_id"], edited["player_id"]), (server["id"], server["world_id"], server["player_id"]))
        self.assertEqual((edited["name"], edited["address"], edited["port"]), ("Kevin at home", "127.0.0.1", self.port))
        self.assertEqual(len(worker.requests), 1)
        self.assertEqual(worker.requests[0].selection,
                         invitation_path(pc.private, server["world_id"], server["player_id"]))      # the same character

    def test_removing_the_shortcut_keeps_the_character_and_the_same_code_brings_it_back(self):
        pc = self.friend()
        self.join_once(pc, FakeWorker(lambda request: "game_closed"))
        account = self.entry.accounts[1][1]
        make_character(pc.private, self.entry.world_id, account)
        save = profile_directory(pc.private, self.entry.world_id, account) / "character.sav"
        original = save.read_bytes()
        driver = Driver(("main", select("join")), ("join_list", lambda s: select(label_id(s, "Player 2's server"))),
                        ("server", select("remove")), ("confirm", select("yes")), ("join_list", BACK), main_exit())
        app, _ = pc.app(driver, lan=LOOPBACK_LAN)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual(app.servers.all(), [])
        self.assertEqual(save.read_bytes(), original)
        self.assertEqual(character_state(pc.private, self.entry.world_id, account), "ready")
        self.assertIsNotNone(app.links.get(self.entry.world_id, account))
        # The same code again: back in the same character, no creation.
        calls = []
        worker = FakeWorker(lambda request: "game_closed")
        driver = Driver(*self.join_steps(self.code(1), then=[("join_list", BACK), main_exit()]))
        app2, _ = pc.app(driver, worker=worker, creator=fake_creator(calls), lan=LOOPBACK_LAN)
        app2.run()
        self.assertEqual(calls, [])
        self.assertEqual(len(app2.servers.all()), 1)
        self.assertEqual(worker.requests[0].selection, invitation_path(pc.private, self.entry.world_id, account))
        self.assertEqual(save.read_bytes(), original)


def SavedServersOf(pc):
    from emerald_multiplayer.saved_servers import SavedServers
    return SavedServers(pc.private / "shell").all()


if __name__ == "__main__":
    unittest.main()
