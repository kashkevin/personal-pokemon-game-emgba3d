"""The in-game main menu's flows, driven by a scripted player (no window): hosting, worlds, settings, New Game."""
import asyncio
import json
from pathlib import Path
import unittest

from emerald_multiplayer.character_links import character_state, profile_directory
from emerald_multiplayer.invite_code import decode_invite
from emerald_multiplayer.shell_app import TRADE_RULES
from shell_fixture import BACK, Driver, FakeWorker, World, choose_label, free_port, label_id, labels, select


def main_exit():
    return ("main", select("exit"))


def make_character(private, world_id, player_id):
    folder = profile_directory(private, world_id, player_id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "character.sav").write_bytes(b"character save for " + player_id.encode())
    (folder / "enrollment-completed.json").write_text("{}")


def fake_creator(calls):
    async def creator(installation, private_root, *, role, world_directory=None, invitation_path=None, route_host=None,
                      route_port=None, draft=None, on_status=None, on_draft=None, **options):
        calls.append(dict(role=role, world_directory=world_directory, invitation_path=invitation_path, route=(route_host, route_port),
                          draft=draft))
        if on_status:
            on_status("draft_running")
        if role == "host":
            from emerald_multiplayer.host_world import HostWorld
            world = HostWorld.open(world_directory, installation.rom_path, installation.manifest_path)
            make_character(Path(private_root), world.world_id, world.accounts[0].player_id)
        else:
            from emerald_multiplayer.invitations import Invitation
            invitation = Invitation.load(invitation_path)
            make_character(Path(private_root), invitation.world_id, invitation.player_id)
        return draft
    return creator


def create_world_steps(name="Kevin's world", host="Kevin", rule_first=False):
    """The screens of Host Server > Create New Server World > create (the friendship rule asked once)."""
    steps = [("main", select("host")), ("host_list", select("create")),
             ("create_world", select("create", name=name, host=host, port=str(free_port())))]
    return steps


class MainMenuTests(unittest.TestCase):
    def test_the_game_opens_on_the_in_game_menu_with_exactly_the_requested_choices(self):
        world = World(self)
        driver = Driver(("main", lambda screen: self.assertEqual(labels(screen), [
            "Continue Adventure", "New Game", "Host Server", "Join Server", "Settings", "Exit"]) or select("exit")))
        app, ui = world.app(driver)
        self.assertEqual(app.run(), 0)
        self.assertTrue(driver.done())
        # The menu is the only window the player sees before a game: it sized itself for the menu and drew nothing else first.
        self.assertEqual(ui.windows[0][:2], app.menu_window)
        self.assertEqual(ui.shown[0].id, "main")

    def test_continue_is_off_with_its_reason_when_there_is_nothing_to_continue(self):
        world = World(self)
        seen = {}

        def look(screen):
            row = next(item for item in screen.items if item.id == "continue")
            seen.update(flags=row.flags, detail=row.detail)
            return select("exit")
        app, _ = world.app(Driver(("main", look)))
        app.run()
        self.assertIn("d", seen["flags"])
        self.assertIn("no adventure yet", seen["detail"])

    def test_closing_the_window_ends_the_menu_cleanly(self):
        from emerald_multiplayer.shell_protocol import ShellClosed

        def closer(screen):
            raise ShellClosed("closed")
        app, _ = World(self).app(closer)
        self.assertEqual(app.run(), 0)


class HostServerTests(unittest.TestCase):
    def make_world(self, world, name="Kevin's world", host="Kevin"):
        """Create a world through the menu and leave it by backing out; returns the app used."""
        driver = Driver(*create_world_steps(name, host), ("world", BACK), ("host_list", BACK), main_exit())
        app, ui = world.app(driver)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        return app

    def test_create_new_server_world_makes_a_named_world_with_a_stable_id_and_its_own_storage(self):
        world = World(self)
        app = self.make_world(world)
        entries = app.registry.entries()
        self.assertEqual([e.name for e in entries], ["Kevin's world"])
        entry = entries[0]
        self.assertEqual(entry.host_name, "Kevin")
        self.assertEqual(len(entry.accounts), 4)                                  # a host and three friend accounts
        self.assertTrue((entry.folder / "host.json").is_file())
        self.assertEqual(entry.folder.parent, world.private / "worlds")           # its own folder under the private storage
        # The first entry is not created yet: no character files exist, but the host's account is linked.
        link = app.links.get(entry.world_id, entry.accounts[0][1])
        self.assertEqual((link["role"], link["stage"], link["world_name"]), ("host", "none", "Kevin's world"))
        self.assertEqual(character_state(world.private, entry.world_id, entry.accounts[0][1]), "none")

    def test_first_time_host_creates_a_character_once_then_the_saved_character_loads_by_itself(self):
        world = World(self)
        app = self.make_world(world)
        entry = app.registry.entries()[0]
        host_id = entry.accounts[0][1]
        calls = []

        def behaviour(request):
            return "game_closed" if character_state(world.private, entry.world_id, host_id) == "ready" else "enrollment_required"
        worker = FakeWorker(behaviour)
        steps = [("main", select("host")), ("host_list", lambda s: select(label_id(s, "Kevin's world"))),
                 ("world", select("host")),
                 ("create_character", select("go")),                                  # the one explanation, then the game opens
                 ("host_list", BACK), ("main", select("exit"))]
        driver = Driver(*steps)
        app2, ui = world.app(driver, worker=worker, creator=fake_creator(calls))
        app2.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual([c["role"] for c in calls], ["host"])
        self.assertEqual(len(worker.requests), 2)                                    # the start, then the start again as that character
        self.assertEqual({r.mode for r in worker.requests}, {"host"})
        self.assertEqual({r.selection for r in worker.requests}, {entry.folder / "host.json"})
        self.assertEqual(character_state(world.private, entry.world_id, host_id), "ready")
        # Next time: Host Server > the saved world > Host This World starts straight away. No creation, no import, no selection.
        calls.clear()
        worker2 = FakeWorker(behaviour)
        driver = Driver(("main", select("host")), ("host_list", lambda s: select(label_id(s, "Kevin's world"))),
                        ("world", select("host")), ("host_list", BACK), ("main", select("exit")))
        app3, _ = world.app(driver, worker=worker2, creator=fake_creator(calls))
        app3.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual(calls, [])
        self.assertEqual(len(worker2.requests), 1)
        self.assertEqual(worker2.requests[0].selection, entry.folder / "host.json")

    def test_a_restart_never_resets_a_world(self):
        world = World(self)
        app = self.make_world(world)
        entry = app.registry.entries()[0]
        before = (entry.folder / "world.sqlite3").read_bytes()
        descriptor = (entry.folder / "host.json").read_bytes()
        for _ in range(2):
            fresh, _ = world.app(Driver(main_exit()))
            fresh.run()
        again = fresh.registry.entries()
        self.assertEqual([e.world_id for e in again], [entry.world_id])
        self.assertEqual(again[0].name, entry.name)
        self.assertEqual((entry.folder / "host.json").read_bytes(), descriptor)
        self.assertEqual((entry.folder / "world.sqlite3").read_bytes(), before)

    def test_a_second_world_is_independent_and_switching_worlds_loads_each_hosts_own_character(self):
        world = World(self)
        app = self.make_world(world, "First", "Kevin")
        app = self.make_world(world, "Second", "Kevin")
        first, second = sorted(app.registry.entries(), key=lambda e: e.name)
        self.assertEqual((first.name, second.name), ("First", "Second"))
        self.assertNotEqual(first.world_id, second.world_id)
        self.assertNotEqual(first.folder, second.folder)
        self.assertNotEqual({a[1] for a in first.accounts}, {a[1] for a in second.accounts})   # separate accounts
        # Each world's host character is its own: one exists, the other does not.
        make_character(world.private, first.world_id, first.accounts[0][1])
        self.assertEqual(character_state(world.private, first.world_id, first.accounts[0][1]), "ready")
        self.assertEqual(character_state(world.private, second.world_id, second.accounts[0][1]), "none")
        worker = FakeWorker(lambda request: "game_closed")
        driver = Driver(("main", select("host")),
                        ("host_list", select(first.world_id)), ("world", select("host")), ("host_list", BACK),
                        ("main", select("host")),
                        ("host_list", select(second.world_id)), ("world", select("host")), ("host_list", BACK), ("main", select("exit")))
        app2, _ = world.app(driver, worker=worker, creator=fake_creator([]))
        # Second has no character: the fake worker would ask for creation; here both end normally, so only the world matters.
        app2.run()
        self.assertEqual([r.selection.parent for r in worker.requests], [first.folder, second.folder])

    def test_world_names_must_differ_and_a_taken_port_is_refused(self):
        world = World(self)
        self.make_world(world)
        driver = Driver(("host_list", select("create")), ("create_world", select("create", name="kevin's WORLD", host="K", port="7777")),
                        ("create_world", lambda s: self.assertIn("already have a world", s.status[1]) or BACK), ("host_list", BACK))
        app, _ = world.app(Driver(("main", select("host")), *driver.steps, main_exit()))
        app.run()

    def test_server_information_is_honest_about_what_is_known(self):
        world = World(self)
        app = self.make_world(world)
        entry = app.registry.entries()[0]
        seen = {}

        def info(screen):
            seen["notes"] = " ".join(screen.notes)
            seen["status"] = screen.status
            seen["labels"] = labels(screen)
            return BACK
        driver = Driver(("main", select("host")), ("host_list", select(entry.world_id)), ("world", select("info")),
                        ("server_info", info), ("world", BACK), ("host_list", BACK), main_exit())
        app2, _ = world.app(driver)
        app2.run()
        text = seen["notes"]
        self.assertIn(f"Port: {entry.port}", text)
        self.assertIn("Public address: not set", text)                          # never an invented public address
        self.assertIn("does not open ports", text)                              # no claim that port forwarding or NAT traversal is done
        self.assertIn("192.168.1.20", text)
        self.assertEqual(seen["status"][0], "info")                              # not hosting: said so


class NewGameAndSettingsTests(unittest.TestCase):
    def test_new_game_creates_its_own_adventure_world_and_never_overwrites_an_existing_one(self):
        world = World(self)
        worker = FakeWorker(lambda request: "game_closed")
        # First time: no confirmation needed, a new adventure world, hosted on this PC only.
        driver = Driver(("main", select("new")), ("host_list", BACK) if False else ("main", select("exit")))
        app, _ = world.app(driver, worker=worker, creator=fake_creator([]))
        app.run()
        entries = app.registry.entries()
        self.assertEqual([(e.name, e.kind, e.bind_address) for e in entries], [("Adventure 1", "adventure", "127.0.0.1")])
        self.assertEqual(len(worker.requests), 1)
        first = entries[0]
        make_character(world.private, first.world_id, first.accounts[0][1])
        app.links.set_stage(first.world_id, first.accounts[0][1], "enrolled")
        before = (first.folder / "world.sqlite3").read_bytes()
        # With an adventure already there, New Game asks first; declining changes nothing.
        driver = Driver(("main", select("new")), ("confirm", lambda s: self.assertIn("nothing is overwritten", " ".join(s.notes)) or select("no")),
                        ("main", select("exit")))
        app2, _ = world.app(driver, worker=FakeWorker(lambda request: "game_closed"), creator=fake_creator([]))
        app2.run()
        self.assertEqual([e.name for e in app2.registry.entries()], ["Adventure 1"])
        # Accepting makes Adventure 2 and leaves Adventure 1 exactly as it was.
        driver = Driver(("main", select("new")), ("confirm", select("yes")), ("main", select("exit")))
        app3, _ = world.app(driver, worker=FakeWorker(lambda request: "game_closed"), creator=fake_creator([]))
        app3.run()
        self.assertEqual(sorted(e.name for e in app3.registry.entries()), ["Adventure 1", "Adventure 2"])
        self.assertEqual((first.folder / "world.sqlite3").read_bytes(), before)
        self.assertEqual(character_state(world.private, first.world_id, first.accounts[0][1]), "ready")

    def test_controls_rebind_a_key_with_a_swap_and_never_offer_the_removed_double_speed(self):
        world = World(self)
        seen = {}

        def controls(screen):
            seen["labels"] = [i.label.lower() for i in screen.items]
            return select("a_start", key="Space")
        steps = [("main", select("settings")), ("settings", select("controls")), ("controls", controls),
                 ("controls", select("a_a", key="X")), ("confirm", select("yes")),          # X is B's key: swap
                 ("controls", select("a_up", key="F5")),                                    # reserved: refused, nothing written
                 ("controls", lambda s: self.assertIn("cannot be used", s.status[1]) or BACK),
                 ("settings", BACK), ("main", select("exit"))]
        driver = Driver(*steps)
        app, _ = world.app(driver)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertFalse(any("fast" in label or "speed" in label for label in seen["labels"]))
        text = (world.private / "game-settings.cfg").read_text()
        self.assertIn("key.start=Space", text)
        self.assertIn("key.a=X", text)
        self.assertIn("key.b=Z", text)          # swapped: B took A's old key
        self.assertNotIn("F5", text)

    def test_settings_graphics_mode_persists_and_the_other_pages_open(self):
        world = World(self)
        steps = [("main", select("settings")), ("settings", select("graphics")), ("choose", select("2d")),
                 ("settings", select("controls")), ("controls", lambda s: self.assertNotIn("fast", " ".join(i.label.lower() for i in s.items)) or BACK),
                 ("settings", select("characters")), ("characters", BACK),
                 ("settings", select("multiplayer")), ("multiplayer", BACK),
                 ("settings", select("files")), ("message", BACK),
                 ("settings", BACK), ("main", select("exit"))]
        driver = Driver(*steps)
        app, _ = world.app(driver)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        self.assertEqual(json.loads((world.private / "graphics-mode.json").read_text())["mode"], "2d")

    def test_display_and_audio_settings_are_written_to_the_games_settings_file(self):
        world = World(self)
        steps = [("main", select("settings")), ("settings", select("display")), ("display", select("resolution")),
                 ("choose", select("1280x720")), ("display", select("mode")), ("choose", select("borderless")), ("display", BACK),
                 ("settings", select("audio")), ("audio", select("volume")), ("choose", select("4")), ("audio", BACK),
                 ("settings", BACK), ("main", select("exit"))]
        driver = Driver(*steps)
        app, _ = world.app(driver)
        app.run()
        self.assertTrue(driver.done(), driver.steps)
        text = (world.private / "game-settings.cfg").read_text()
        self.assertIn("resolution=1280x720", text)
        self.assertIn("displayMode=borderless", text)
        self.assertIn("volume=4", text)

    def test_a_damaged_record_is_reported_and_never_overwritten(self):
        world = World(self)
        shell = world.private / "shell"
        shell.mkdir(parents=True)
        (shell / "servers.json").write_text("{ this is not json")
        driver = Driver(("message", lambda s: self.assertIn("could not be read", " ".join(s.notes)) or BACK), ("main", select("exit")))
        app, _ = world.app(driver)
        app.run()
        self.assertEqual((shell / "servers.json").read_text(), "{ this is not json")

    def test_an_unexpected_failure_shows_a_message_keeps_the_menu_alive_and_records_it(self):
        world = World(self)
        app, _ = world.app(Driver(("main", select("settings")), ("message", BACK), ("main", select("exit"))))
        original = app.settings_menu

        def broken():
            raise RuntimeError("boom")
        app.settings_menu = broken
        driver = Driver(("main", select("settings")), ("message", lambda s: self.assertIn("Nothing was deleted", " ".join(s.notes)) or BACK),
                        ("main", select("exit")))
        app.ui.responder = driver
        self.assertEqual(app.run(), 0)
        self.assertTrue(driver.done(), driver.steps)
        self.assertIn("boom", (world.private / "shell" / "last-error.txt").read_text())
        app.settings_menu = original

    def test_the_menu_never_opens_a_launcher_window(self):
        import subprocess
        import sys
        code = ("import sys; sys.path.insert(0, 'src'); import emerald_multiplayer.shell_app, emerald_multiplayer.shell_protocol;"
                "sys.exit(1 if 'tkinter' in sys.modules else 0)")
        done = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1])
        self.assertEqual(done.returncode, 0, "the in-game menu must not load the launcher's window toolkit")


class HostSettingsAndSessionTests(unittest.TestCase):
    def world_with(self, world, **changes):
        driver = Driver(*create_world_steps("Kevin's world", "Kevin"), ("world", BACK), ("host_list", BACK), main_exit())
        app, _ = world.app(driver, lan=lambda: ["192.168.1.20"])
        app.run()
        entry = app.registry.entries()[0]
        if changes:
            app.registry.configure(entry.world_id, **changes)
        return app, app.registry.get(entry.world_id)

    def test_network_settings_change_where_the_world_listens_and_never_invent_an_address(self):
        world = World(self)
        app, entry = self.world_with(world)
        self.assertEqual((entry.bind_address, entry.internet, entry.address, entry.enrollment), ("192.168.1.20", False, "", True))
        steps = [("main", select("host")), ("host_list", select(entry.world_id)), ("world", select("network")),
                 ("network", select("bind")), ("choose", select("127.0.0.1")),
                 ("network", select("internet")), ("confirm", select("yes")),
                 ("network", select("address")), ("ask_text", select("ok", value="not a valid host!")),
                 ("network", lambda s: self.assertIn("not a usable address", s.status[1]) or select("address")),
                 ("ask_text", select("ok", value="friends.example.org")),
                 ("network", select("enrollment")),
                 ("network", lambda s: self.assertIn("next time", s.status[1]) or BACK),
                 ("world", BACK), ("host_list", BACK), main_exit()]
        driver = Driver(*steps)
        app2, _ = world.app(driver, lan=lambda: ["192.168.1.20"])
        app2.run()
        self.assertTrue(driver.done(), driver.steps)
        entry = app2.registry.get(entry.world_id)
        self.assertEqual((entry.bind_address, entry.internet, entry.address, entry.enrollment), ("127.0.0.1", True, "friends.example.org", False))
        # The next start carries exactly those choices to the session (and lets the host turn network enrollment off).
        worker = FakeWorker(lambda request: "game_closed")
        make_character(world.private, entry.world_id, entry.accounts[0][1])
        driver = Driver(("main", select("host")), ("host_list", select(entry.world_id)), ("world", select("host")), ("host_list", BACK), main_exit())
        app3, _ = world.app(driver, worker=worker, lan=lambda: ["192.168.1.20"])
        app3.run()
        (request,) = worker.requests
        self.assertEqual((request.address, request.internet, request.allow_enrollment), ("127.0.0.1", True, False))

    def test_a_changed_local_address_is_noticed_and_the_host_told(self):
        world = World(self)
        app, entry = self.world_with(world, bind_address="192.168.1.99")
        worker = FakeWorker(lambda request: "game_closed")
        driver = Driver(("main", select("host")), ("host_list", select(entry.world_id)), ("world", select("host")),
                        ("host_list", BACK), main_exit())
        app2, _ = world.app(driver, worker=worker, lan=lambda: ["10.0.0.7"])
        app2.run()
        self.assertEqual(worker.requests[0].address, "10.0.0.7")                      # the address this PC has now
        self.assertEqual(app2.registry.get(entry.world_id).bind_address, "10.0.0.7")

    def test_invite_codes_are_copied_for_the_right_account_and_say_when_they_cannot_be_reached(self):
        world = World(self)
        app, entry = self.world_with(world)
        notes = []
        steps = [("main", select("host")), ("host_list", select(entry.world_id)), ("world", select("codes")),
                 ("codes", lambda s: notes.append(" ".join(s.notes)) or select("slot2")),
                 ("codes", lambda s: notes.append(s.status[1]) or BACK), ("world", BACK), ("host_list", BACK), main_exit()]
        driver = Driver(*steps)
        app2, ui = world.app(driver, lan=lambda: ["192.168.1.20"])
        app2.run()
        self.assertTrue(driver.done(), driver.steps)
        code = decode_invite(ui.copied[-1])
        self.assertEqual((code.player_id, code.slot, code.world_id, code.display_name),
                         (entry.accounts[2][1], 2, entry.world_id, "Player 3"))
        self.assertEqual((code.address, code.port), ("192.168.1.20", entry.port))
        self.assertIn("copied", notes[1])
        self.assertIn("password", notes[0])

    def test_a_world_that_only_listens_on_this_pc_warns_before_a_code_is_sent(self):
        world = World(self)
        app, entry = self.world_with(world, bind_address="127.0.0.1")
        seen = []
        steps = [("main", select("host")), ("host_list", select(entry.world_id)), ("world", select("codes")),
                 ("codes", lambda s: seen.append(" ".join(s.notes)) or BACK), ("world", BACK), ("host_list", BACK), main_exit()]
        app2, _ = world.app(Driver(*steps), lan=lambda: ["192.168.1.20"])
        app2.run()
        self.assertIn("listens on this PC only", seen[0])

    def test_the_session_window_saves_toggles_autosave_and_shows_server_information_while_hosting(self):
        import queue
        from emerald_multiplayer.launcher_gui import UiEvent

        world = World(self)
        app, entry = self.world_with(world)
        make_character(world.private, entry.world_id, entry.accounts[0][1])

        class Manual(FakeWorker):
            def start(self, request):
                self.requests.append(request)
                self.events.put(UiEvent("status", "running", "running", True, save_available=True, is_host=True, connected=True))
                return True

        worker = Manual()
        script = iter([select("save"), select("autosave"), select("info"), BACK, None])
        seen = {}

        def responder(screen, waiting=False):
            if screen.id == "session":
                seen.setdefault("rows", [i.id for i in screen.items])
                answer = next(script)
                if answer is None:
                    worker.events.put(UiEvent("complete", "game_closed"))
                return answer
            if screen.id == "server_info":
                seen["info"] = " ".join(screen.notes)
                seen["status"] = screen.status
                return BACK
            return {"main": select("host") if not seen.get("hosted") else select("exit"),
                    "host_list": select(entry.world_id) if not seen.get("hosted") else BACK,
                    "world": select("host")}.get(screen.id) or self.fail(f"unexpected {screen.id}")

        def wrapped(screen, waiting=False):
            if screen.id == "world":
                seen["hosted"] = True
            return responder(screen, waiting)
        from emerald_multiplayer.shell_protocol import ScriptedShell
        from emerald_multiplayer.shell_app import ShellApp
        ui = ScriptedShell(wrapped)
        app3 = ShellApp(world.installation, world.private, ui, worker=worker, lan=lambda: ["192.168.1.20"], graphics_gate=lambda: "3d", version="t")
        app3.run()
        self.assertEqual(worker.saves, 1)
        self.assertEqual(worker.autosave, [False])
        self.assertIn("save", seen["rows"])
        self.assertIn("info", seen["rows"])
        self.assertIn("Hosting now on 192.168.1.20", seen["status"][1])
        self.assertIn("does not open ports", seen["info"])
        self.assertEqual(ui.windows[-1][:2], app3.menu_window)                      # the menu window is restored when the session ends


if __name__ == "__main__":
    unittest.main()


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
