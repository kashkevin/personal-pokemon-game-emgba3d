"""Host World > Create World on a real PC, and the world list it writes (the 'invalid world record' crash of 2026-10-19).

``launcher_worlds.lan_addresses`` returns LocalAddress values: a ``str`` subclass carrying the address's kind and label. The world
list (``world_registry``), a world's certificate and invite codes accept exact ``str`` only, so a world created on the default
local-network address failed: without a public address with "Character setup could not complete", and with a numeric public
address the world was made, then ``ValueError: invalid world record`` left it on disk unlisted, and from then on every main menu
listing tried to add it with the same LocalAddress and failed again. These tests use LocalAddress values the way a PC returns them,
on a fresh private folder and on folders an earlier version left behind.
"""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from emerald_multiplayer.character_links import profile_directory
from emerald_multiplayer.host_world import HostWorld
from emerald_multiplayer.invite_code import decode_invite
from emerald_multiplayer.launcher_recent import RecentStore
from emerald_multiplayer.launcher_setup import create_world
from emerald_multiplayer.launcher_worlds import LocalAddress, classify_address
from emerald_multiplayer.world_registry import FORMAT, MAX_WORLDS, WorldRegistry, WorldRegistryError
from shell_fixture import BACK, Driver, FakeWorker, World, fake_register, free_port, label_id, lan_of, select
from test_shell_app import host_steps, library_character, main_exit, world_character

LAN_ADDRESS = classify_address("192.168.1.20", "Ethernet")


def stored(private):
    return json.loads((Path(private) / "shell" / "worlds.json").read_text())["worlds"]


def new_world(private):
    return SimpleNamespace(world_id=str(uuid4()), directory=Path(private) / "worlds" / str(uuid4()))


def create_steps(name="Kevin's world", host="Kevin", *, address=None):
    """Host World > Create a new world, optionally typing a public address first, then Create world."""
    steps = [("main", select("host")), ("host_list", select("create"))]
    if address is not None:
        steps += [("create_world", select("address", name=name, host=host)), ("ask_text", select("ok", value=address))]
    return steps + [("create_world", select("create", name=name, host=host, port=str(free_port())))]


def orphan(world, endpoint="81.2.69.160", names=("Kevin", "Player 2", "Player 3", "Player 4")):
    """What the crash left on disk: a world folder that was created and never added to the world list."""
    return create_world(world.installation, world.private, player_names=names, endpoint=endpoint, port=free_port())


class RegistryTextTests(unittest.TestCase):
    """The world list stores exact text, copies it out of a str subclass, and still refuses what is not usable."""

    def setUp(self):
        import tempfile
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.private = Path(self.temp.name)

    def test_a_local_address_is_stored_as_plain_text(self):
        registry = WorldRegistry(self.private)
        world = new_world(self.private)
        registry.register(world, "Kevin's world", bind_address=LAN_ADDRESS, address=classify_address("10.0.0.5"))
        (record,) = stored(self.private)
        self.assertEqual((record["bind_address"], record["address"]), ("192.168.1.20", "10.0.0.5"))
        (memory,) = registry._store.record["worlds"]
        self.assertIs(type(memory["bind_address"]), str)
        self.assertIs(type(memory["address"]), str)
        self.assertEqual(WorldRegistry(self.private)._store.record["worlds"], [record])     # read back unchanged

    def test_changing_a_setting_to_a_local_address_is_stored_as_plain_text(self):
        registry = WorldRegistry(self.private)
        world = new_world(self.private)
        registry.register(world, "Kevin's world")
        registry.configure(world.world_id, bind_address=classify_address("192.168.1.21", "Wi-Fi"))
        self.assertEqual(stored(self.private)[0]["bind_address"], "192.168.1.21")
        self.assertIs(type(registry._store.record["worlds"][0]["bind_address"]), str)

    def test_validation_is_still_strict_and_says_which_setting(self):
        registry = WorldRegistry(self.private)
        cases = {"bind_address": dict(bind_address="my-pc.local"), "name": dict(name=""), "address": dict(address="x" * 254)}
        for field, change in cases.items():
            options = dict(name="Kevin's world", bind_address="127.0.0.1", address="")
            options.update(change)
            name = options.pop("name")
            with self.subTest(field=field), self.assertRaises(WorldRegistryError) as caught:
                registry.register(new_world(self.private), name, **options)
            self.assertEqual(caught.exception.code, "world_record_invalid")
            self.assertIn({"bind_address": "address to listen on", "name": "world name", "address": "public address"}[field],
                          str(caught.exception))
        with self.assertRaises(WorldRegistryError):
            registry.register(new_world(self.private), "Kevin's world", bind_address=1921681120)       # not text at all
        with self.assertRaises(WorldRegistryError):
            registry.register(new_world(self.private), "Kevin's world", internet="yes")
        self.assertFalse((self.private / "shell" / "worlds.json").exists())                       # nothing was written

    def test_check_new_refuses_a_world_past_the_limit_before_anything_is_made(self):
        records = [dict(world_id=str(uuid4()), folder=f"w{i}", name=f"World {i}", kind="server", created=1.0, last_hosted=None,
                        bind_address="127.0.0.1", internet=False, address="", enrollment=True) for i in range(MAX_WORLDS)]
        (self.private / "shell").mkdir()
        (self.private / "shell" / "worlds.json").write_text(json.dumps({"format": FORMAT, "worlds": records}))
        registry = WorldRegistry(self.private)
        with self.assertRaises(WorldRegistryError) as caught:
            registry.check_new("One more", bind_address=LAN_ADDRESS)
        self.assertEqual(caught.exception.code, "world_limit")
        WorldRegistry(self.private, self.private / "other").check_new("Fine", bind_address=LAN_ADDRESS)   # an empty list accepts it

    def test_a_list_written_by_the_previous_release_loads_as_it_is(self):
        """The format did not change: the file an earlier version wrote is read, listed and left byte-identical."""
        (self.private / "shell").mkdir()
        record = dict(world_id=str(uuid4()), folder="gone", name="Old world", kind="server", created=1_700_000_000.5,
                      last_hosted=1_700_000_100.0, bind_address="192.168.1.20", internet=True, address="friends.example.org",
                      enrollment=False)
        raw = json.dumps({"format": "emerald-shell-worlds-v1", "worlds": [record]}, indent=2).encode()
        (self.private / "shell" / "worlds.json").write_bytes(raw)
        registry = WorldRegistry(self.private)
        self.assertTrue(registry.available)
        self.assertEqual(registry._store.record["worlds"], [record])
        registry.entries(default_bind=LAN_ADDRESS)
        self.assertEqual((self.private / "shell" / "worlds.json").read_bytes(), raw)


class ListingTests(unittest.TestCase):
    """A world folder the list has not met is added with plain text, and a listing never fails the main menu."""

    def test_an_unlisted_folder_is_added_with_the_local_address_as_plain_text(self):
        world = World(self)
        left = orphan(world)
        registry = WorldRegistry(world.private)
        (entry,) = registry.entries(default_bind=LAN_ADDRESS)
        self.assertEqual((entry.world_id, entry.name, entry.bind_address, entry.endpoint),
                         (left.world_id, "Kevin's world", "192.168.1.20", "81.2.69.160"))
        self.assertIs(type(stored(world.private)[0]["bind_address"]), str)

    def test_an_earlier_launchers_unusable_address_is_not_used_as_the_listen_address(self):
        world = World(self)
        left = orphan(world)
        registry = WorldRegistry(world.private)
        (entry,) = registry.entries(default_bind=LAN_ADDRESS, hints={Path(left.directory).name: "my-pc.local"})
        self.assertEqual(entry.bind_address, "192.168.1.20")
        (entry,) = WorldRegistry(world.private, world.private / "again").entries(
            hints={Path(left.directory).name: classify_address("10.1.2.3", "Ethernet")})
        self.assertEqual(entry.bind_address, "10.1.2.3")

    def test_a_listing_whose_save_fails_still_lists_and_marks_the_new_folder(self):
        world = World(self)
        left = orphan(world)
        registry = WorldRegistry(world.private)
        with patch.object(registry._store, "save", side_effect=OSError("disk full")):
            self.assertEqual(registry.entries(default_bind=LAN_ADDRESS), [])
        self.assertIn(Path(left.directory).name, registry.damaged)
        self.assertTrue((Path(left.directory) / "host.json").is_file())                    # untouched
        (entry,) = registry.entries(default_bind=LAN_ADDRESS)                               # the next listing adds it
        self.assertEqual(entry.world_id, left.world_id)


class CreateWorldTests(unittest.TestCase):
    """Host World > Create World through the menu, with the addresses a real PC reports."""

    def setUp(self):
        self.world = World(self)
        self.assertFalse(self.world.private.exists())                                       # a fresh installation
        library_character(self.world)

    def run_app(self, *steps, **options):
        driver = Driver(*steps)
        app, ui = self.world.app(driver, **options)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        return app, ui

    def test_the_default_local_network_creates_and_lists_the_world(self):
        app, ui = self.run_app(*create_steps(), ("world", BACK), ("host_list", BACK), main_exit())
        (entry,) = app.registry.entries()
        self.assertEqual((entry.name, entry.bind_address, entry.endpoint, entry.address), ("Kevin's world", "192.168.1.20",
                                                                                          "192.168.1.20", ""))
        self.assertEqual(stored(self.world.private)[0]["bind_address"], "192.168.1.20")
        self.assertNotIn("message", [screen.id for screen in ui.shown])
        self.assertFalse((self.world.private / "shell" / "last-error.txt").exists())

    def test_a_numeric_public_address_creates_and_lists_the_world(self):
        """The reported traceback: the world was made (its invitations point at the public address) and the list refused it."""
        app, ui = self.run_app(*create_steps(address="81.2.69.160"), ("world", BACK), ("host_list", BACK), main_exit())
        (entry,) = app.registry.entries()
        self.assertEqual((entry.bind_address, entry.endpoint, entry.address), ("192.168.1.20", "81.2.69.160", "81.2.69.160"))
        self.assertEqual(len(list((self.world.private / "worlds").iterdir())), 1)
        self.assertFalse((self.world.private / "shell" / "last-error.txt").exists())

    def test_a_host_name_as_public_address_and_this_pc_only_both_create(self):
        app, _ = self.run_app(*create_steps("Named", address="friends.example.org"), ("world", BACK), ("host_list", BACK), main_exit())
        app, _ = self.run_app(("main", select("host")), ("host_list", select("create")),
                              ("create_world", select("network", name="Local", host="Kevin")), ("choose", select("127.0.0.1")),
                              ("create_world", select("create", name="Local", host="Kevin", port=str(free_port()))),
                              ("world", BACK), ("host_list", BACK), main_exit())
        worlds = {entry.name: entry for entry in app.registry.entries()}
        self.assertEqual((worlds["Named"].address, worlds["Named"].endpoint), ("friends.example.org", "192.168.1.20"))
        self.assertEqual((worlds["Local"].bind_address, worlds["Local"].endpoint), ("127.0.0.1", "127.0.0.1"))

    def test_create_save_reopen_host_rename_change_network_invite_and_delete(self):
        self.run_app(*create_steps(), ("world", BACK), ("host_list", BACK), main_exit())
        # Reopen: a new start lists the same world, by the same ID, with the same settings.
        app, _ = self.run_app(main_exit())
        (entry,) = app.registry.entries()
        self.assertEqual((entry.name, entry.bind_address), ("Kevin's world", "192.168.1.20"))
        # Host it: the character comes in once and the game is started listening on the local-network address.
        worker, registrations = FakeWorker(lambda request: "game_closed"), []
        self.run_app(*host_steps(entry), worker=worker, register=fake_register(registrations))
        self.assertEqual([r["role"] for r in registrations], ["host"])
        self.assertEqual((worker.requests[0].mode, worker.requests[0].address), ("host", "192.168.1.20"))
        # The PC's address changed: hosting moves to the new one, saves it, and says so (this crashed too).
        worker, seen = FakeWorker(lambda request: "game_closed"), []
        app, ui = self.run_app(*host_steps(entry, register=False), worker=worker, lan=lan_of("192.168.1.21"))
        self.assertEqual(worker.requests[0].address, "192.168.1.21")
        self.assertEqual(app.registry.get(entry.world_id).bind_address, "192.168.1.21")
        # Rename it; the new name is kept after a restart.
        self.run_app(("main", select("host")), ("host_list", select(entry.world_id)), ("world", select("rename")),
                     ("ask_text", select("ok", value="Hoenn Friends")), ("world", BACK), ("host_list", BACK), main_exit(),
                     lan=lan_of("192.168.1.21"))
        app, _ = self.run_app(main_exit(), lan=lan_of("192.168.1.21"))
        self.assertEqual(app.registry.get(entry.world_id).name, "Hoenn Friends")
        # Network settings > Listen on: the row offered for the local network is saved as that address.
        self.run_app(("main", select("host")), ("host_list", select(entry.world_id)), ("world", select("network")),
                     ("network", select("bind")), ("choose", select("127.0.0.1")),
                     ("network", select("bind")), ("choose", lambda s: select(label_id(s, "Local network"))),
                     ("network", BACK), ("world", BACK), ("host_list", BACK), main_exit(), lan=lan_of("192.168.1.21"))
        self.assertEqual(stored(self.world.private)[0]["bind_address"], "192.168.1.21")
        # An invite code for the local network points at that address (it was refused for a LocalAddress).
        _, ui = self.run_app(("main", select("host")), ("host_list", select(entry.world_id)), ("world", select("codes")),
                             ("codes", select("slot1")), ("codes", lambda s: self.assertIn("copied", s.status[1]) or BACK),
                             ("world", BACK), ("host_list", BACK), main_exit(), lan=lan_of("192.168.1.21"))
        code = decode_invite(ui.copied[-1])
        self.assertEqual((code.address, code.port, code.world_id), ("192.168.1.21", entry.port, entry.world_id))
        # Delete it: asked first, the folder moves to worlds-deleted, and a restart no longer lists it.
        self.run_app(("main", select("host")), ("host_list", select(entry.world_id)), ("world", select("delete")),
                     ("confirm", select("yes")), ("host_list", BACK), main_exit(), lan=lan_of("192.168.1.21"))
        app, _ = self.run_app(main_exit())
        self.assertEqual(app.registry.entries(), [])
        (moved,) = (self.world.private / "worlds-deleted").iterdir()
        self.assertTrue((moved / "host.json").is_file())

    def test_a_world_the_list_cannot_take_is_refused_before_anything_is_made(self):
        records = [dict(world_id=str(uuid4()), folder=f"w{i}", name=f"World {i}", kind="server", created=1.0, last_hosted=None,
                        bind_address="127.0.0.1", internet=False, address="", enrollment=True) for i in range(MAX_WORLDS)]
        (self.world.private / "shell").mkdir(parents=True, exist_ok=True)
        (self.world.private / "shell" / "worlds.json").write_text(json.dumps({"format": FORMAT, "worlds": records}))
        seen = {}
        self.run_app(*create_steps(), ("message", lambda s: seen.update(title=s.title, notes=" ".join(s.notes)) or BACK),
                     ("create_world", BACK), ("host_list", BACK), main_exit())
        self.assertEqual(seen["title"], "The world could not be created")
        self.assertIn("64 worlds", seen["notes"])
        self.assertIn("Nothing was changed", seen["notes"])
        self.assertFalse((self.world.private / "worlds").exists() and any((self.world.private / "worlds").iterdir()))

    def test_a_world_made_but_not_listed_is_explained_and_listed_next_time(self):
        seen = {}
        with patch.object(WorldRegistry, "register", side_effect=OSError("disk full")):
            self.run_app(*create_steps(), ("message", lambda s: seen.update(title=s.title, notes=" ".join(s.notes)) or BACK),
                         ("create_world", BACK), ("host_list", BACK), main_exit())
        self.assertEqual(seen["title"], "The world was made but not added to your list")
        self.assertIn("Kevin's world", seen["notes"])
        app, _ = self.run_app(main_exit())
        (entry,) = app.registry.entries()
        self.assertEqual((entry.name, entry.bind_address), ("Kevin's world", "192.168.1.20"))

    def test_a_setting_the_list_refuses_is_a_readable_message_not_a_crash(self):
        self.run_app(*create_steps(), ("world", BACK), ("host_list", BACK), main_exit())
        app, _ = self.run_app(main_exit())
        (entry,) = app.registry.entries()
        seen = {}
        refusal = WorldRegistryError("world_record_invalid", "the world name is not usable (1 to 32 printable characters)")
        with patch.object(WorldRegistry, "configure", side_effect=refusal):
            self.run_app(("main", select("host")), ("host_list", select(entry.world_id)), ("world", select("rename")),
                         ("ask_text", select("ok", value="Other")),
                         ("message", lambda s: seen.update(title=s.title, notes=" ".join(s.notes)) or BACK), main_exit())
        self.assertEqual(seen["title"], "A world setting could not be saved")
        self.assertIn("The world name is not usable", seen["notes"])
        self.assertIn("Nothing was changed", seen["notes"])


class LeftoverDataTests(unittest.TestCase):
    """An installation over a private folder an earlier version (or the crash) left behind."""

    def test_the_world_the_crash_left_behind_is_listed_and_the_menu_opens(self):
        world = World(self)
        library_character(world)
        left = orphan(world)                                       # Create World made it, then the list refused it
        driver = Driver(("main", select("host")),
                        ("host_list", lambda s: self.assertIn("Kevin's world", [i.label for i in s.items]) or select(left.world_id)),
                        ("world", BACK), ("host_list", BACK), main_exit())
        app, ui = world.app(driver)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertNotIn("message", [screen.id for screen in ui.shown])                  # no "Something went wrong" loop
        (entry,) = app.registry.entries()
        # The start-up import lists a folder it has not met as listening on this PC only, as for an earlier launcher's world;
        # Network settings opens it to the local network.
        self.assertEqual((entry.world_id, entry.bind_address, entry.endpoint), (left.world_id, "127.0.0.1", "81.2.69.160"))
        # A new world can be created next to it, and both stay.
        driver = Driver(*create_steps("Second"), ("world", BACK), ("host_list", BACK), main_exit())
        app, _ = world.app(driver)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual(sorted(entry.name for entry in app.registry.entries()), ["Kevin's world", "Second"])

    def test_an_earlier_launchers_worlds_and_characters_are_kept_and_create_world_works(self):
        world = World(self)
        private = world.private
        host_world = create_world(world.installation, private, player_names=("Kevin", "Pat"), endpoint="127.0.0.1", port=free_port())
        saved = world_character(private, host_world.world_id, host_world.accounts[0].player_id)
        RecentStore(private).record_session("host", host_world.directory / "host.json", "127.0.0.1", False)
        database = (Path(host_world.directory) / "world.sqlite3").read_bytes()
        driver = Driver(*create_steps("New one"), ("world", BACK), ("host_list", BACK), main_exit())
        app, ui = world.app(driver)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        worlds = {entry.name: entry for entry in app.registry.entries()}
        self.assertEqual(set(worlds), {"Kevin's world", "New one"})
        self.assertEqual(worlds["Kevin's world"].bind_address, "127.0.0.1")              # the earlier launcher's address
        self.assertEqual(worlds["New one"].bind_address, "192.168.1.20")
        self.assertEqual((Path(host_world.directory) / "world.sqlite3").read_bytes(), database)
        (character,) = app.library.all()
        self.assertEqual((character.world_id, character.player_id), (host_world.world_id, host_world.accounts[0].player_id))
        self.assertEqual((profile_directory(private, host_world.world_id, host_world.accounts[0].player_id)
                          / "character.sav").read_bytes(), saved)
        self.assertNotIn("message", [screen.id for screen in ui.shown])

    def test_a_vpn_address_reported_first_is_also_plain_text(self):
        world = World(self)
        library_character(world)
        vpn = lambda: [classify_address("100.101.102.103", "Tailscale"), LAN_ADDRESS]
        self.assertIsInstance(vpn()[0], LocalAddress)
        driver = Driver(*create_steps(), ("world", BACK), ("host_list", BACK), main_exit())
        app, _ = world.app(driver, lan=vpn)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        (entry,) = app.registry.entries()
        self.assertEqual(entry.bind_address, "100.101.102.103")
        HostWorld.open(entry.folder, world.installation.rom_path, world.installation.manifest_path)      # its certificate verifies


if __name__ == "__main__":
    unittest.main()
