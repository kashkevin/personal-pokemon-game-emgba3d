"""The in-game main menu's flows, driven by a scripted player (no window): characters, Solo, Host World, settings, the session."""
import json
from pathlib import Path
import unittest

from emerald_multiplayer.character_creation import CreationError
from emerald_multiplayer.character_library import CharacterLibrary
from emerald_multiplayer.character_links import character_state, profile_directory
from emerald_multiplayer.invite_code import decode_invite
from shell_fixture import BACK, Driver, FakeWorker, World, fake_drafter, fake_register, free_port, label_id, labels, select
from test_ownership_storage import source_flash


def main_exit():
    return ("main", select("exit"))


def library_character(world, personality=7):
    return CharacterLibrary(world.private).create(source_flash(personalities=(personality,)))


def world_character(private, world_id, player_id, personality=7):
    """A character an earlier version left in a world account: the world's own save for it (an ownership save)."""
    import uuid
    from emerald_multiplayer.ownership_storage import AllocationGrant
    from test_ownership_storage import owned_flash
    folder = profile_directory(private, world_id, player_id)
    folder.mkdir(parents=True, exist_ok=True)
    payload = owned_flash(AllocationGrant(world_id, player_id, str(uuid.uuid4()), 1, 33, 1, 1, 0), personalities=(personality,))
    (folder / "character.sav").write_bytes(payload)
    (folder / "enrollment-completed.json").write_text("{}")
    return payload


def create_world_steps(name="Kevin's world", host="Kevin"):
    """Host World > Create a new world > create (the friendship rule asked once)."""
    return [("main", select("host")), ("host_list", select("create")),
            ("create_world", select("create", name=name, host=host, port=str(free_port())))]


def make_world(test, world, name="Kevin's world", host="Kevin"):
    """Create a world through the menu and back out; returns the app used."""
    library_character(world) if not CharacterLibrary(world.private).all() else None
    driver = Driver(*create_world_steps(name, host), ("world", BACK), ("host_list", BACK), main_exit())
    app, _ = world.app(driver)
    app.run()
    test.assertTrue(driver.done(), driver.steps)
    return app


def host_steps(entry, *, register=True):
    steps = [("main", select("host")), ("host_list", select(entry.world_id)), ("world", select("host"))]
    if register:
        steps.append(("bring_character", select("go")))
    return steps + [("host_list", BACK), main_exit()]


class MainMenuTests(unittest.TestCase):
    def test_the_game_opens_on_the_in_game_menu_with_exactly_the_requested_choices(self):
        world = World(self)
        driver = Driver(("main", lambda screen: self.assertEqual(labels(screen), [
            "Continue Adventure", "Solo", "Host World", "Join Friend", "Characters", "Settings", "Exit"]) or select("exit")))
        app, ui = world.app(driver)
        self.assertEqual(app.run(), 0)
        self.assertTrue(driver.done())
        self.assertEqual(ui.windows[0][:2], app.menu_window)
        self.assertEqual(ui.shown[0].id, "main")

    def test_a_first_start_says_to_create_a_character_and_continue_is_off(self):
        world = World(self)
        seen = {}

        def look(screen):
            row = next(item for item in screen.items if item.id == "continue")
            seen.update(flags=row.flags, detail=row.detail, sub=screen.sub, status=screen.status)
            return select("exit")
        app, _ = world.app(Driver(("main", look)))
        app.run()
        self.assertIn("d", seen["flags"])
        self.assertIn("nothing played yet", seen["detail"])
        self.assertIn("creating your character", seen["sub"])
        self.assertIn("Create your character", seen["status"][1])

    def test_closing_the_window_ends_the_menu_cleanly(self):
        from emerald_multiplayer.shell_protocol import ShellClosed

        def closer(screen):
            raise ShellClosed("closed")
        app, _ = World(self).app(closer)
        self.assertEqual(app.run(), 0)


class CharacterTests(unittest.TestCase):
    def test_a_first_time_player_creates_one_character_and_plays_solo_with_no_second_new_game(self):
        world = World(self)
        drafts, registrations = [], []
        worker = FakeWorker(lambda request: "game_closed")
        driver = Driver(("main", select("solo")),
                        ("confirm", lambda s: self.assertIn("one character everywhere", " ".join(s.notes)) or select("yes")),
                        ("create_character", select("go")),
                        ("solo", select("new")),
                        ("ask_text", select("ok", value="My world")),
                        ("bring_character", lambda s: self.assertIn("first visit", " ".join(s.notes)) or select("go")),
                        main_exit())
        app, _ = world.app(driver, worker=worker, drafter=fake_drafter(drafts), register=fake_register(registrations))
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual(drafts, ["draft"])                                        # one New Game, ever
        (character,) = app.library.all()
        (entry,) = app.registry.entries()
        self.assertEqual((entry.name, entry.kind), ("My world", "adventure"))
        self.assertEqual([(r["role"], r["world_id"]) for r in registrations], [("host", entry.world_id)])
        (request,) = worker.requests
        self.assertEqual((request.mode, request.address, request.internet, request.allow_enrollment),
                         ("host", "127.0.0.1", False, False))                       # Solo: this PC only
        self.assertEqual((character.world_id, character.player_id), (entry.world_id, entry.accounts[0][1]))
        # Next start: Continue Adventure plays the same world with the same character - nothing to create or register.
        worker2, drafts2, registrations2 = FakeWorker(lambda request: "game_closed"), [], []
        driver = Driver(("main", lambda s: self.assertIn("My world", s.items[0].detail) or select("continue")), main_exit())
        app2, _ = world.app(driver, worker=worker2, drafter=fake_drafter(drafts2), register=fake_register(registrations2))
        app2.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual((drafts2, registrations2, len(worker2.requests)), ([], [], 1))

    def test_the_same_character_enters_a_second_world_without_a_new_game(self):
        world = World(self)
        character = library_character(world)
        drafts, registrations = [], []
        steps = []
        for name in ("First", "Second"):
            steps += [("main", select("solo")), ("solo", select("new"))]
            steps += [("ask_text", select("ok", value=name)), ("bring_character", select("go"))]
        driver = Driver(*steps, main_exit())
        app, _ = world.app(driver, drafter=fake_drafter(drafts), register=fake_register(registrations))
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual(drafts, [])
        self.assertEqual({r["character_id"] for r in registrations}, {character.character_id})
        self.assertEqual(len({r["world_id"] for r in registrations}), 2)
        self.assertEqual(len(app.library.all()), 1)

    def test_characters_menu_create_choose_rename_back_up_restore_and_delete(self):
        world = World(self)
        first = library_character(world)
        steps = [("main", select("characters")), ("characters", select("create")), ("create_character", select("go")),
                 ("characters", lambda s: select("c:" + first.character_id)),
                 ("character", select("play")),
                 ("character", select("rename")), ("ask_text", select("ok", value="Kev")),
                 ("character", select("backup")),
                 ("character", select("restore")), ("choose", select("0")), ("confirm", select("yes")),
                 ("character", select("delete")),
                 ("confirm", lambda s: self.assertIn("not destroyed", " ".join(s.notes)) or select("no")),
                 ("character", BACK), ("characters", BACK), main_exit()]
        driver = Driver(*steps)
        app, _ = world.app(driver, drafter=fake_drafter([]))
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        characters = app.library.all()
        self.assertEqual(len(characters), 2)
        self.assertEqual(app.library.active().character_id, first.character_id)
        self.assertEqual(app.library.get(first.character_id).name, "Kev")
        # The backup is kept; restoring a copy identical to the current save changes nothing and adds nothing.
        self.assertEqual(len(app.library.history(app.library.get(first.character_id))), 1)
        self.assertEqual(app.library.get(first.character_id).sha256, first.sha256)
        # Deleting for real moves the folder aside.
        other = next(c for c in characters if c.character_id != first.character_id)
        driver = Driver(("main", select("characters")), ("characters", select("c:" + other.character_id)),
                        ("character", select("delete")), ("confirm", select("yes")), ("characters", BACK), main_exit())
        app2, _ = world.app(driver)
        app2.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertIsNone(app2.library.get(other.character_id))
        self.assertTrue(any((world.private / "characters-deleted").iterdir()))

    def test_characters_from_an_earlier_version_are_kept_and_unfinished_attempts_can_be_recovered(self):
        world = World(self)
        from emerald_multiplayer.ownership_storage import AllocationGrant
        from test_ownership_storage import owned_flash
        import uuid
        world_id, player_id = str(uuid.uuid4()), str(uuid.uuid4())
        folder = profile_directory(world.private, world_id, player_id)
        folder.mkdir(parents=True)
        (folder / "character.sav").write_bytes(owned_flash(AllocationGrant(world_id, player_id, str(uuid.uuid4()), 1, 33, 1, 1, 0),
                                                           personalities=(7,)))
        for personality in (21, 22):
            draft = world.private / "drafts" / str(uuid.uuid4())
            draft.mkdir(parents=True)
            (draft / "character.sav").write_bytes(source_flash(personalities=(personality,)))
        seen = {}
        driver = Driver(("main", lambda s: seen.update(status=s.status) or select("characters")),
                        ("characters", lambda s: seen.update(labels=labels(s)) or select("recover")),
                        ("choose", select("0")),
                        ("characters", lambda s: seen.update(after=s.status) or BACK), main_exit())
        app, _ = world.app(driver)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertIn("ready", seen["status"][1])
        self.assertIn("Recover a character", seen["labels"])
        self.assertIn("recovered", seen["after"][1])
        self.assertEqual(len(app.library.all()), 2)
        self.assertTrue((folder / "character.sav").is_file())                    # the original stays

    def test_a_refused_entry_explains_plainly_and_changes_nothing(self):
        world = World(self)
        library_character(world)
        worker = FakeWorker(lambda request: "game_closed")
        seen = {}
        driver = Driver(("main", select("solo")), ("solo", select("new")),
                        ("ask_text", select("ok", value="W")), ("bring_character", select("go")),
                        ("message", lambda s: seen.update(text=" ".join(s.notes)) or BACK),
                        ("solo", BACK), main_exit())
        app, _ = world.app(driver, worker=worker, register=fake_register([], error=CreationError("pokemon_owned_here")))
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertIn("belongs to another trainer", seen["text"])
        self.assertIn("latest save is safe", seen["text"])
        self.assertNotIn("Traceback", seen["text"])
        self.assertEqual(worker.requests, [])
        self.assertIn("CreationError", (world.private / "shell" / "last-error.txt").read_text())


class HostWorldTests(unittest.TestCase):
    def test_create_a_world_with_a_stable_id_and_its_own_storage(self):
        world = World(self)
        app = make_world(self, world)
        (entry,) = app.registry.entries()
        self.assertEqual((entry.name, entry.host_name, len(entry.accounts)), ("Kevin's world", "Kevin", 4))
        self.assertTrue((entry.folder / "host.json").is_file())
        self.assertEqual(entry.folder.parent, world.private / "worlds")
        self.assertEqual(character_state(world.private, entry.world_id, entry.accounts[0][1]), "none")

    def test_hosting_brings_the_character_in_once_then_the_world_simply_starts(self):
        world = World(self)
        app = make_world(self, world)
        (entry,) = app.registry.entries()
        registrations, worker = [], FakeWorker(lambda request: "game_closed")
        driver = Driver(*host_steps(entry))
        app2, _ = world.app(driver, worker=worker, register=fake_register(registrations))
        app2.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual([r["role"] for r in registrations], ["host"])
        (request,) = worker.requests
        self.assertEqual((request.mode, request.selection, request.address), ("host", entry.folder / "host.json", "192.168.1.20"))
        registrations2, worker2 = [], FakeWorker(lambda request: "game_closed")
        driver = Driver(*host_steps(entry, register=False))
        app3, _ = world.app(driver, worker=worker2, register=fake_register(registrations2))
        app3.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual((registrations2, len(worker2.requests)), ([], 1))

    def test_deleting_a_world_asks_first_moves_its_folder_aside_and_keeps_the_character(self):
        world = World(self)
        app = make_world(self, world)
        (entry,) = app.registry.entries()
        character = app.library.all()[0]
        seen = {}
        driver = Driver(("main", select("host")), ("host_list", select(entry.world_id)), ("world", select("delete")),
                        ("confirm", lambda s: seen.update(no=" ".join(s.notes)) or select("no")),
                        ("world", select("delete")), ("confirm", select("yes")),
                        ("host_list", lambda s: seen.update(status=s.status, rows=[i.id for i in s.items]) or BACK), main_exit())
        app2, _ = world.app(driver)
        app2.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertIn("not destroyed", seen["no"])
        self.assertIn("worlds-deleted", seen["status"][1])
        self.assertNotIn(entry.world_id, seen["rows"])
        self.assertEqual(app2.registry.entries(), [])
        (moved,) = (world.private / "worlds-deleted").iterdir()
        self.assertTrue((moved / "host.json").is_file())                         # the world itself is kept
        self.assertEqual(app2.library.get(character.character_id).sha256, character.sha256)

    def test_a_restart_never_resets_a_world(self):
        world = World(self)
        app = make_world(self, world)
        (entry,) = app.registry.entries()
        descriptor = (entry.folder / "host.json").read_bytes()
        before = (entry.folder / "world.sqlite3").read_bytes()
        for _ in range(2):
            fresh, _ = world.app(Driver(main_exit()))
            fresh.run()
        self.assertEqual([e.world_id for e in fresh.registry.entries()], [entry.world_id])
        self.assertEqual((entry.folder / "host.json").read_bytes(), descriptor)
        self.assertEqual((entry.folder / "world.sqlite3").read_bytes(), before)

    def test_deleting_a_world_asks_first_and_moves_it_aside(self):
        world = World(self)
        app = make_world(self, world)
        (entry,) = app.registry.entries()
        driver = Driver(("main", select("host")), ("host_list", select(entry.world_id)), ("world", select("delete")),
                        ("confirm", select("no")), ("world", select("delete")),
                        ("confirm", lambda s: self.assertIn("not destroyed", " ".join(s.notes)) or select("yes")),
                        ("host_list", BACK), main_exit())
        app2, _ = world.app(driver)
        app2.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual(app2.registry.entries(), [])
        moved = list((world.private / "worlds-deleted").iterdir())
        self.assertEqual(len(moved), 1)
        self.assertTrue((moved[0] / "host.json").is_file())

    def test_world_names_must_differ_and_a_taken_port_is_refused(self):
        world = World(self)
        make_world(self, world)
        driver = Driver(("main", select("host")), ("host_list", select("create")),
                        ("create_world", select("create", name="kevin's WORLD", host="K", port="7777")),
                        ("create_world", lambda s: self.assertIn("already have a world", s.status[1]) or BACK),
                        ("host_list", BACK), main_exit())
        app, _ = world.app(driver)
        app.run()
        self.assertTrue(driver.done(), driver.steps)

    def test_server_information_is_honest_about_what_is_known(self):
        world = World(self)
        app = make_world(self, world)
        (entry,) = app.registry.entries()
        seen = {}

        def info(screen):
            seen.update(notes=" ".join(screen.notes), status=screen.status)
            return BACK
        driver = Driver(("main", select("host")), ("host_list", select(entry.world_id)), ("world", select("info")),
                        ("server_info", info), ("world", BACK), ("host_list", BACK), main_exit())
        app2, _ = world.app(driver)
        app2.run()
        self.assertIn(f"Port: {entry.port}", seen["notes"])
        self.assertIn("Public address: not set", seen["notes"])
        self.assertIn("192.168.1.20", seen["notes"])
        self.assertEqual(seen["status"][0], "info")

    def test_network_settings_are_carried_to_the_next_hosting(self):
        world = World(self)
        app = make_world(self, world)
        (entry,) = app.registry.entries()
        steps = [("main", select("host")), ("host_list", select(entry.world_id)), ("world", select("network")),
                 ("network", select("bind")), ("choose", select("127.0.0.1")),
                 ("network", select("internet")), ("confirm", select("yes")),
                 ("network", select("address")), ("ask_text", select("ok", value="not a valid host!")),
                 ("network", lambda s: self.assertIn("not a usable address", s.status[1]) or select("address")),
                 ("ask_text", select("ok", value="friends.example.org")),
                 ("network", select("enrollment")), ("network", BACK), ("world", BACK), ("host_list", BACK), main_exit()]
        driver = Driver(*steps)
        app2, _ = world.app(driver)
        app2.run()
        self.assertTrue(driver.done(), driver.steps)
        entry = app2.registry.get(entry.world_id)
        self.assertEqual((entry.bind_address, entry.internet, entry.address, entry.enrollment),
                         ("127.0.0.1", True, "friends.example.org", False))
        worker = FakeWorker(lambda request: "game_closed")
        driver = Driver(*host_steps(entry))
        app3, _ = world.app(driver, worker=worker)
        app3.run()
        (request,) = worker.requests
        self.assertEqual((request.address, request.internet, request.allow_enrollment), ("127.0.0.1", True, False))

    def test_invite_codes_are_copied_for_the_right_account(self):
        world = World(self)
        app = make_world(self, world)
        (entry,) = app.registry.entries()
        notes = []
        driver = Driver(("main", select("host")), ("host_list", select(entry.world_id)), ("world", select("codes")),
                        ("codes", lambda s: notes.append(" ".join(s.notes)) or select("slot2")),
                        ("codes", lambda s: notes.append(s.status[1]) or BACK), ("world", BACK), ("host_list", BACK), main_exit())
        app2, ui = world.app(driver)
        app2.run()
        self.assertTrue(driver.done(), driver.steps)
        code = decode_invite(ui.copied[-1])
        self.assertEqual((code.player_id, code.slot, code.world_id), (entry.accounts[2][1], 2, entry.world_id))
        self.assertIn("copied", notes[1])
        self.assertIn("password", notes[0])

    def test_the_session_window_saves_toggles_autosave_and_shows_server_information_while_hosting(self):
        from emerald_multiplayer.launcher_gui import UiEvent
        from emerald_multiplayer.shell_app import ShellApp
        from emerald_multiplayer.shell_protocol import ScriptedShell
        world = World(self)
        app = make_world(self, world)
        (entry,) = app.registry.entries()

        from types import SimpleNamespace
        from emerald_multiplayer.relay import RelayAgentStatus

        class Manual(FakeWorker):
            def start(self, request):
                self.requests.append(request)
                self.events.put(UiEvent("status", "running", "running", True, save_available=True, is_host=True, connected=True,
                                        router=SimpleNamespace(code="mapped", message="The router forwards port 7777 (UPnP)."),
                                        relay=RelayAgentStatus("relay_ready", "127.0.0.1:7780", 1)))
                return True

        worker = Manual()
        script = iter([select("save"), select("autosave"), select("info"), BACK, None])
        seen = {}

        def responder(screen, waiting=False):
            if screen.id == "session":
                seen.setdefault("rows", [i.id for i in screen.items])
                seen["notes"] = " ".join(screen.notes)
                answer = next(script)
                if answer is None:
                    worker.events.put(UiEvent("complete", "game_closed"))
                return answer
            if screen.id == "server_info":
                seen.update(info=" ".join(screen.notes), status=screen.status)
                return BACK
            if screen.id == "world":
                seen["hosted"] = True
                return select("host")
            if screen.id == "busy" and waiting:
                return None
            return {"main": select("host") if not seen.get("hosted") else select("exit"),
                    "host_list": select(entry.world_id) if not seen.get("hosted") else BACK,
                    "bring_character": select("go")}.get(screen.id) or self.fail(f"unexpected {screen.id}")
        ui = ScriptedShell(responder)
        app3 = ShellApp(world.installation, world.private, ui, worker=worker, lan=lambda: ["192.168.1.20"], graphics_gate=lambda: "3d",
                        version="t", register=fake_register([]), drafter=fake_drafter([]))
        app3.run()
        self.assertEqual((worker.saves, worker.autosave), (1, [False]))
        self.assertIn("save", seen["rows"])
        self.assertIn("info", seen["rows"])
        self.assertIn("Hosting now on 192.168.1.20", seen["status"][1])
        # What the session itself reports: the world connection, the router setup and the relay (never a guess).
        self.assertIn("Your world is running and your game is connected to it.", seen["notes"])
        self.assertIn("Router: The router forwards port 7777 (UPnP).", seen["notes"])
        self.assertIn("(1 friend through it)", seen["notes"])
        self.assertEqual(ui.windows[-1][:2], app3.menu_window)

    def test_a_relay_set_in_network_settings_goes_into_new_invite_codes_and_router_setup_toggles(self):
        from emerald_multiplayer.network_settings import NetworkSettings
        world = World(self)
        app = make_world(self, world)
        (entry,) = app.registry.entries()
        seen = {}
        driver = Driver(("main", select("host")), ("host_list", select(entry.world_id)), ("world", select("network")),
                        ("network", select("relay")),
                        ("choose", lambda s: seen.update(relay_notes=" ".join(s.notes)) or select("set")),
                        ("ask_text", select("ok", value="relay.example.net:7780")),
                        ("network", lambda s: seen.update(status=s.status) or select("router")),
                        ("network", lambda s: seen.update(router=s.status) or BACK),
                        ("world", select("codes")), ("codes", lambda s: seen.update(code_notes=" ".join(s.notes)) or select("slot1")),
                        ("codes", BACK), ("world", BACK), ("host_list", BACK), main_exit())
        app2, ui = world.app(driver)
        app2.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertIn("does not run a public relay", seen["relay_notes"])
        self.assertIn("Relay saved", seen["status"][1])
        self.assertIn("off", seen["router"][1])
        network = NetworkSettings(world.private).get(entry.world_id)
        self.assertEqual((network.relay, network.router_setup), (("relay.example.net", 7780), False))
        self.assertIn("relay.example.net:7780", seen["code_notes"])
        self.assertEqual(decode_invite(ui.copied[-1]).relay, ("relay.example.net", 7780))


class SettingsTests(unittest.TestCase):
    def test_controls_rebind_a_key_with_a_swap_and_never_offer_the_removed_double_speed(self):
        world = World(self)
        seen = {}

        def controls(screen):
            seen["labels"] = [i.label.lower() for i in screen.items]
            return select("a_start", key="Space")
        driver = Driver(("main", select("settings")), ("settings", select("controls")), ("controls", controls),
                        ("controls", select("a_a", key="X")), ("confirm", select("yes")),
                        ("controls", select("a_up", key="F5")),
                        ("controls", lambda s: self.assertIn("cannot be used", s.status[1]) or BACK),
                        ("settings", BACK), main_exit())
        app, _ = world.app(driver)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertFalse(any("fast" in label or "speed" in label for label in seen["labels"]))
        text = (world.private / "game-settings.cfg").read_text()
        self.assertIn("key.start=Space", text)
        self.assertIn("key.a=X", text)
        self.assertIn("key.b=Z", text)
        self.assertNotIn("F5", text)

    def test_graphics_mode_persists_and_the_other_pages_open(self):
        world = World(self)
        driver = Driver(("main", select("settings")), ("settings", select("graphics")), ("choose", select("2d")),
                        ("settings", select("characters")), ("characters", BACK),
                        ("settings", select("multiplayer")), ("multiplayer", BACK),
                        ("settings", select("files")), ("message", BACK), ("settings", BACK), main_exit())
        app, _ = world.app(driver)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual(json.loads((world.private / "graphics-mode.json").read_text())["mode"], "2d")

    def test_display_and_audio_settings_are_written_to_the_games_settings_file(self):
        world = World(self)
        driver = Driver(("main", select("settings")), ("settings", select("display")), ("display", select("resolution")),
                        ("choose", select("1280x720")), ("display", select("mode")), ("choose", select("borderless")), ("display", BACK),
                        ("settings", select("audio")), ("audio", select("volume")), ("choose", select("4")), ("audio", BACK),
                        ("settings", BACK), main_exit())
        app, _ = world.app(driver)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        text = (world.private / "game-settings.cfg").read_text()
        for expected in ("resolution=1280x720", "displayMode=borderless", "volume=4"):
            self.assertIn(expected, text)

    def test_a_damaged_record_is_reported_and_never_overwritten(self):
        world = World(self)
        shell = world.private / "shell"
        shell.mkdir(parents=True)
        (shell / "servers.json").write_text("{ this is not json")
        driver = Driver(("message", lambda s: self.assertIn("could not be read", " ".join(s.notes)) or BACK), main_exit())
        app, _ = world.app(driver)
        app.run()
        self.assertEqual((shell / "servers.json").read_text(), "{ this is not json")

    def test_an_unexpected_failure_shows_a_plain_message_keeps_the_menu_alive_and_records_it(self):
        world = World(self)
        app, _ = world.app(Driver())

        def broken():
            raise RuntimeError("boom")
        app.settings_menu = broken
        seen = {}
        driver = Driver(("main", select("settings")), ("message", lambda s: seen.update(text=" ".join(s.notes)) or BACK), main_exit())
        app.ui.responder = driver
        self.assertEqual(app.run(), 0)
        self.assertTrue(driver.done(), driver.steps)
        self.assertIn("Nothing was deleted", seen["text"])
        self.assertNotIn("boom", seen["text"])
        self.assertIn("boom", (world.private / "shell" / "last-error.txt").read_text())

    def test_the_menu_never_opens_a_launcher_window(self):
        import subprocess
        import sys
        code = ("import sys; sys.path.insert(0, 'src'); import emerald_multiplayer.shell_app, emerald_multiplayer.shell_protocol;"
                "sys.exit(1 if 'tkinter' in sys.modules else 0)")
        done = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(done.returncode, 0, "the in-game menu must not load the launcher's window toolkit")


class ShellProcessStartTests(unittest.TestCase):
    """A game executable that ends without announcing a menu (a smoke-test stub, a broken build) must not count as a started menu,
    so the packaged entry falls back to the earlier launcher instead of exiting with nothing on screen."""

    def test_program_that_just_ends_is_not_a_menu(self):
        import sys
        from emerald_multiplayer.shell_protocol import ShellClosed, ShellProcess
        with self.assertRaises(ShellClosed):
            ShellProcess([sys.executable, "-c", "pass"])

    def test_program_that_announces_ready_is_accepted(self):
        import sys
        from emerald_multiplayer.shell_protocol import ShellProcess
        shell = ShellProcess([sys.executable, "-c",
                              "import sys,time; sys.stdout.write('ready\\tx\\n'); sys.stdout.flush(); time.sleep(5)"])
        try:
            self.assertTrue(shell.announced)
        finally:
            shell.close()


if __name__ == "__main__":
    unittest.main()
