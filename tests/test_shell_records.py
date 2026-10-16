"""The in-game menu's private records: atomic, backed up, never silently replaced when damaged, and keyed by stable identifiers."""
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from emerald_multiplayer.character_links import CharacterLinks, character_state, profile_directory
from emerald_multiplayer.saved_servers import InvitationConflict, SavedServers
from emerald_multiplayer.shell_store import JsonStore, StoreUnavailable, is_uuid


class Clock:
    def __init__(self):
        self.now = 1_700_000_000.0

    def __call__(self):
        self.now += 60
        return self.now


def ids():
    return str(uuid4()), str(uuid4())


class JsonStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "records.json"

    def store(self):
        def validate(record):
            if set(record) != {"format", "items"} or type(record["items"]) is not list:
                raise ValueError("bad")
            return record
        return JsonStore(self.path, "test-v1", lambda: {"format": "test-v1", "items": []}, validate)

    def test_a_write_keeps_the_previous_version_and_a_damaged_file_falls_back_to_it(self):
        store = self.store()
        store.save({"format": "test-v1", "items": [1]})
        store.save({"format": "test-v1", "items": [1, 2]})
        self.assertEqual(json.loads(self.path.read_text())["items"], [1, 2])
        self.assertEqual(json.loads(self.path.with_name("records.json.bak").read_text())["items"], [1])
        self.path.write_text("{ not json")
        recovered = self.store()
        self.assertTrue(recovered.available and recovered.recovered)
        self.assertEqual(recovered.record["items"], [1])

    def test_a_record_with_no_usable_backup_is_never_overwritten(self):
        self.path.write_text('{"format": "other"}')
        store = self.store()
        self.assertFalse(store.available)
        with self.assertRaises(StoreUnavailable):
            store.save({"format": "test-v1", "items": []})
        self.assertEqual(self.path.read_text(), '{"format": "other"}')

    def test_an_invalid_candidate_is_refused_before_anything_is_written(self):
        store = self.store()
        with self.assertRaises(ValueError):
            store.save({"format": "test-v1", "items": "nope"})
        self.assertFalse(self.path.exists())

    def test_a_missing_file_is_simply_empty_and_no_partial_files_are_left(self):
        store = self.store()
        self.assertEqual(store.record["items"], [])
        store.save({"format": "test-v1", "items": [3]})
        self.assertEqual([p.name for p in self.path.parent.iterdir() if p.name.endswith(".stage")], [])


class CharacterLinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clock = Clock()

    def links(self):
        return CharacterLinks(self.root / "shell", clock=self.clock)

    def test_a_character_is_identified_by_world_and_player_never_by_name(self):
        w1, p1 = ids()
        w2, p2 = ids()
        links = self.links()
        a = links.ensure(w1, p1, "host", 0, "Alpha", "Kevin")
        b = links.ensure(w2, p1, "friend", 1, "Beta", "Kevin")      # the same player id in another world: another character
        c = links.ensure(w1, p2, "friend", 2, "Alpha", "Kevin")     # another account in the same world: another character
        self.assertEqual(len({(l["world_id"], l["player_id"]) for l in (a, b, c)}), 3)
        self.assertEqual(len(links.all()), 3)
        # Renaming the world or the account changes labels only: the link, stage and times stay.
        links.set_stage(w1, p1, "enrolled")
        again = links.ensure(w1, p1, "host", 0, "Alpha Renamed", "Kevin K")
        self.assertEqual((again["world_name"], again["display_name"], again["stage"], again["created"]),
                         ("Alpha Renamed", "Kevin K", "enrolled", a["created"]))
        self.assertEqual(len(links.all()), 3)
        folders = {profile_directory(self.root, l["world_id"], l["player_id"]) for l in links.all()}
        self.assertEqual(len(folders), 3)

    def test_state_comes_from_the_files_and_links_survive_a_restart(self):
        w, p = ids()
        links = self.links()
        links.ensure(w, p, "host", 0, "World", "Kevin")
        self.assertEqual(character_state(self.root, w, p), "none")
        folder = profile_directory(self.root, w, p)
        folder.mkdir(parents=True)
        (folder / "pending-enrollment.json").write_text("{}")
        self.assertEqual(character_state(self.root, w, p), "interrupted")
        (folder / "pending-enrollment.json").unlink()
        (folder / "character.sav").write_bytes(b"x" * 10)
        self.assertEqual(character_state(self.root, w, p), "ready")
        links.set_stage(w, p, "draft", {"source": "/x/y.sav", "sha256": "a" * 64})
        reloaded = self.links()
        self.assertEqual(reloaded.get(w, p)["stage"], "draft")
        self.assertEqual(reloaded.get(w, p)["draft"]["sha256"], "a" * 64)

    def test_only_canonical_identifiers_are_accepted(self):
        for bad in ("", "not-a-uuid", "00000000-0000-0000-0000-000000000000", "../../x"):
            self.assertFalse(is_uuid(bad))
            with self.assertRaises(ValueError):
                profile_directory(self.root, bad, str(uuid4()))
        w, p = ids()
        with self.assertRaises(ValueError):
            self.links().ensure(w, p, "boss", 0, "W", "N")


class SavedServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name) / "shell"
        self.clock = Clock()

    def servers(self):
        return SavedServers(self.dir, clock=self.clock)

    def test_an_account_has_one_shortcut_and_adding_it_again_follows_the_new_address(self):
        w, p = ids()
        servers = self.servers()
        first, created = servers.add("Kevin's server", "192.168.1.5", 7777, w, p, 1, "Pal")
        self.assertTrue(created)
        again, created = servers.add("Another name", "10.0.0.8", 7778, w, p, 1, "Pal")
        self.assertFalse(created)
        self.assertEqual((again["id"], again["name"], again["address"], again["port"]), (first["id"], "Kevin's server", "10.0.0.8", 7778))
        self.assertEqual(len(servers.all()), 1)

    def test_editing_the_address_keeps_the_world_and_player_identity(self):
        w, p = ids()
        servers = self.servers()
        server, _ = servers.add("S", "192.168.1.5", 7777, w, p, 2, "Pal")
        edited = servers.edit(server["id"], name="Renamed", address="host.example.org", port=9000)
        self.assertEqual((edited["world_id"], edited["player_id"], edited["slot"]), (w, p, 2))
        self.assertEqual((edited["name"], edited["address"], edited["port"]), ("Renamed", "host.example.org", 9000))
        self.assertEqual(self.servers().get(server["id"])["address"], "host.example.org")

    def test_removing_a_shortcut_removes_only_the_shortcut(self):
        w, p = ids()
        servers = self.servers()
        links = CharacterLinks(self.dir, clock=self.clock)
        server, _ = servers.add("S", "192.168.1.5", 7777, w, p, 1, "Pal")
        links.ensure(w, p, "friend", 1, "S", "Pal")
        (self.dir.parent / "players" / w / p).mkdir(parents=True)
        (self.dir.parent / "players" / w / p / "character.sav").write_bytes(b"save")
        self.assertTrue(servers.remove(server["id"]))
        self.assertFalse(servers.remove(server["id"]))
        self.assertEqual(servers.all(), [])
        self.assertIsNotNone(links.get(w, p))
        self.assertEqual((self.dir.parent / "players" / w / p / "character.sav").read_bytes(), b"save")

    def test_names_are_made_unique_and_invalid_values_are_refused(self):
        w1, p1 = ids()
        w2, p2 = ids()
        servers = self.servers()
        a, _ = servers.add("Same", "192.168.1.5", 7777, w1, p1, 1, "A")
        b, _ = servers.add("Same", "192.168.1.6", 7777, w2, p2, 1, "B")
        self.assertNotEqual(a["name"].casefold(), b["name"].casefold())
        with self.assertRaises(ValueError):
            servers.edit(a["id"], port=0)
        with self.assertRaises(ValueError):
            servers.edit(a["id"], address="bad host name!")
        self.assertEqual(servers.get(a["id"])["port"], 7777)

    def test_most_recently_joined_comes_first(self):
        servers = self.servers()
        rows = []
        for index in range(3):
            w, p = ids()
            rows.append(servers.add(f"S{index}", "192.168.1.5", 7777 + index, w, p, 1, "N")[0])
        servers.touch(rows[1]["id"])
        self.assertEqual([s["name"] for s in servers.all()][0], "S1")


if __name__ == "__main__":
    unittest.main()
