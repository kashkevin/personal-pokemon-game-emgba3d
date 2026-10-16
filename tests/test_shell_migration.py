"""Saves and worlds made by the earlier launcher stay usable in the in-game menu, unchanged and without guessing."""
import hashlib
import json
from pathlib import Path
import unittest

from emerald_multiplayer.character_links import character_state, profile_directory
from emerald_multiplayer.launcher_recent import RecentStore
from emerald_multiplayer.launcher_setup import create_world, export_friend_invitation
from emerald_multiplayer.saved_servers import invitation_path
from shell_fixture import BACK, Driver, FakeWorker, ServerThread, World, free_port, label_id, select
from test_shell_app import make_character

LAN = lambda: ["127.0.0.1"]


def tree_hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(root).rglob("*")) if p.is_file()}


class MigrationTests(unittest.TestCase):
    def legacy(self):
        """What an earlier launcher left: a host world with its host character, a recent session, a friend invitation in use."""
        world = World(self)
        private = world.private
        host_world = create_world(world.installation, private, player_names=("Kevin", "Pat"), endpoint="127.0.0.1", port=free_port())
        make_character(private, host_world.world_id, host_world.accounts[0].player_id)
        invitation_file = world.root / "downloads" / "pat.json"
        invitation_file.parent.mkdir()
        host_world.export_invitation(1, invitation_file)
        make_character(private, host_world.world_id, host_world.accounts[1].player_id)       # Pat played from this PC too
        ticks = iter(range(1_700_000_000, 1_700_000_100, 10))
        recent = RecentStore(private, clock=lambda: float(next(ticks)))
        recent.record_session("host", host_world.directory / "host.json", "127.0.0.1", False)
        recent.record_session("join", invitation_file, "127.0.0.1", False)
        return world, host_world, invitation_file

    def test_old_worlds_characters_and_invitations_are_found_without_touching_a_file(self):
        world, host_world, invitation_file = self.legacy()
        before = tree_hashes(world.private)
        before_invitation = invitation_file.read_bytes()
        app, _ = world.app(Driver(("main", select("exit"))), lan=LAN, clock=lambda: 1_700_100_000.0)
        app.run()
        # The world is listed by its stable ID with a name made from its host.
        (entry,) = app.registry.entries()
        self.assertEqual((entry.world_id, entry.name, entry.host_name), (host_world.world_id, "Kevin's world", "Kevin"))
        # Its host character is linked to the host account, exactly where it already was.
        link = app.links.get(host_world.world_id, host_world.accounts[0].player_id)
        self.assertEqual((link["role"], link["stage"]), ("host", "enrolled"))
        self.assertEqual(character_state(world.private, host_world.world_id, host_world.accounts[0].player_id), "ready")
        # The invitation the player used is now a saved server for that account; the original file is untouched.
        (server,) = app.servers.all()
        self.assertEqual((server["world_id"], server["player_id"], server["address"], server["port"]),
                         (host_world.world_id, host_world.accounts[1].player_id, "127.0.0.1", host_world.port))
        self.assertTrue(invitation_path(world.private, host_world.world_id, host_world.accounts[1].player_id).is_file())
        self.assertEqual(invitation_file.read_bytes(), before_invitation)
        # Nothing that existed was changed: every old file is byte-identical (the menu only added its own files).
        after = tree_hashes(world.private)
        for path, digest in before.items():
            if path.endswith("launcher-recent.json"):
                self.assertEqual(digest, after[path])
            elif not path.startswith("shell"):
                self.assertEqual(digest, after[path], path)
        self.assertTrue(any(p.startswith("shell/backups/launcher-recent-") for p in after))

    def test_continue_adventure_resumes_the_session_played_last(self):
        world, host_world, _ = self.legacy()
        ServerThread(self, world.installation, host_world)
        worker = FakeWorker(lambda request: "game_closed")
        driver = Driver(("main", lambda s: select("continue")), ("main", select("exit")))
        app, _ = world.app(driver, worker=worker, lan=LAN, clock=lambda: 1_700_100_000.0)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual([r.mode for r in worker.requests], ["join"])       # the join was the most recent session
        self.assertEqual(worker.requests[0].selection, invitation_path(world.private, host_world.world_id, host_world.accounts[1].player_id))

    def test_the_migration_is_idempotent_and_adds_nothing_the_second_time(self):
        world, host_world, _ = self.legacy()
        for _ in range(3):
            app, _ = world.app(Driver(("main", select("exit"))), lan=LAN)
            app.run()
        self.assertEqual(len(app.registry.entries()), 1)
        self.assertEqual(len(app.servers.all()), 1)
        self.assertEqual(len([l for l in app.links.all() if l["world_id"] == host_world.world_id]), 2)

    def test_hosting_an_old_world_uses_its_old_character_and_asks_for_nothing(self):
        world, host_world, _ = self.legacy()
        worker = FakeWorker(lambda request: "game_closed")
        calls = []
        driver = Driver(("main", select("host")), ("host_list", lambda s: select(label_id(s, "Kevin's world"))),
                        ("world", select("host")), ("host_list", BACK), ("main", select("exit")))
        app, _ = world.app(driver, worker=worker, lan=LAN)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual(worker.requests[0].selection, host_world.directory / "host.json")
        self.assertEqual((profile_directory(world.private, host_world.world_id, host_world.accounts[0].player_id) / "character.sav").read_bytes(),
                         b"character save for " + host_world.accounts[0].player_id.encode())

    def test_conflicting_invitations_are_left_alone_and_reported(self):
        world, host_world, invitation_file = self.legacy()
        # A different invitation for the same account is already stored: it is never replaced.
        folder = profile_directory(world.private, host_world.world_id, host_world.accounts[1].player_id)
        stored = folder / "invitation.json"
        other = world.root / "other.json"
        # Make a *different* valid invitation for the same account by rotating nothing: reuse another world's friend.
        other_world = create_world(world.installation, world.private, player_names=("Sam", "Lee"), endpoint="127.0.0.1", port=7800)
        other_world.export_invitation(1, other)
        stored.write_bytes(other.read_bytes())            # a different credential sits where this account's copy goes
        notes = []
        driver = Driver(("main", lambda s: notes.append(s.status) or select("settings")), ("settings", select("characters")),
                        ("characters", lambda s: notes.append(" ".join(s.notes)) or BACK), ("settings", BACK), ("main", select("exit")))
        app, _ = world.app(driver, lan=LAN)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual(notes[0][0], "warn")
        self.assertIn("could not be matched", notes[0][1])
        self.assertIn("Left untouched", notes[1])
        self.assertEqual(stored.read_bytes(), other.read_bytes())
        self.assertEqual(app.servers.all(), [])
        self.assertTrue(any("different one is already stored" in problem for problem in app.migration.problems))


if __name__ == "__main__":
    unittest.main()
