"""The unified main menu (Update 28): one window, six choices, and the same session worker, checks and recovery behind them."""
from pathlib import Path
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from emerald_multiplayer.launcher_gui import LauncherWindow, SessionWorker, status_text
from emerald_multiplayer.launcher_recent import RecentStore
from emerald_multiplayer.launcher_worlds import STATUS_INVALID, STATUS_READY, WorldEntry
from test_launcher_gui import ControlledSession


def wait_for(root, condition, seconds=5):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        if condition():
            return True
        time.sleep(0.01)
    return False


class MenuTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest("Tk display unavailable: " + str(error))
        self.root.withdraw()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.private = self.directory / "private"
        self.private.mkdir()
        (self.directory / "game.gba").write_bytes(b"rom")
        self.instances = []
        self.windows = []

        def factory(*args, **kwargs):
            session = ControlledSession(*args, **kwargs)
            self.instances.append(session)
            return session

        def bundle_verify(*_):
            raise ValueError("not a real runtime")     # the graphics check then starts the game as it is

        installation = SimpleNamespace(rom_path=self.directory / "game.gba", manifest_path=self.directory / "manifest.json",
                                       bundle=SimpleNamespace(verify=bundle_verify, is_native=lambda: False))
        self.worker = SessionWorker(installation, self.private, factory=factory)

        def cleanup():
            for session in self.instances:
                session.release_connect.set()
                session.release_game.set()
                session.release_cleanup.set()
            self.worker.cancel_startup()
            if self.worker._thread:
                self.worker._thread.join(5)
            try:
                for window in self.windows:
                    self.root.after_cancel(window._poll_id)
                self.root.destroy()
            except tk.TclError:
                pass
        self.addCleanup(cleanup)

    def world(self, name="w-1"):
        directory = self.private / "worlds" / name
        directory.mkdir(parents=True)
        (directory / "host.json").write_text("{}")
        return directory / "host.json"

    def window(self, worker="default"):
        window = LauncherWindow(self.root, self.worker if worker == "default" else worker, version="test")
        self.windows.append(window)
        return window

    # ---- the menu itself

    def test_the_menu_is_the_first_page_with_the_six_choices_in_order(self):
        window = self.window()
        self.assertEqual(window.current_view, "home")
        self.assertEqual(list(window.menu.cards), ["continue", "worlds", "host", "join", "settings", "exit"])
        titles = [card.title.cget("text") for card in window.menu.cards.values()]
        self.assertEqual(titles, ["Continue Adventure", "My Worlds", "Host Multiplayer", "Join Friend", "Settings", "Exit Game"])

    def test_every_choice_opens_its_page_in_this_window_and_back_returns(self):
        window = self.window()
        before = set(self.root.winfo_children())
        for key, view in (("worlds", "worlds"), ("host", "host"), ("join", "join"), ("settings", "settings")):
            window.menu.cards[key].invoke()
            self.assertEqual(window.current_view, view)
            window.go_home()
            self.assertEqual(window.current_view, "home")
        self.assertEqual(set(self.root.winfo_children()), before, "no pop-up window opens for any page")

    def test_escape_goes_back_and_arrow_keys_move_between_choices(self):
        window = self.window()
        window.show_view("settings")
        window._escape()
        self.assertEqual(window.current_view, "home")
        self.root.deiconify()
        self.root.update()
        window.menu.cards["worlds"].frame.focus_force()
        self.root.update()
        window.menu.cards["worlds"].frame.event_generate("<Down>")
        self.root.update()
        self.assertIs(self.root.focus_get(), window.menu.cards["host"].frame)
        window.menu.cards["host"].frame.event_generate("<Up>")
        window.menu.cards["host"].frame.event_generate("<Up>")
        self.root.update()
        self.assertIs(self.root.focus_get(), window.menu.cards["continue"].frame)

    def test_a_missing_game_package_is_explained_and_nothing_starts(self):
        window = self.window(None)
        self.assertIn("verified game package", window.message.get())
        window.continue_adventure()
        window.show_view("host")
        window.begin_host()
        self.assertFalse(self.instances)

    # ---- Continue Adventure

    def test_continue_is_off_on_a_first_launch_and_says_what_to_do(self):
        window = self.window()
        card = window.menu.cards["continue"]
        self.assertFalse(card.enabled)
        self.assertIn("Nothing to continue", card.subtitle.cget("text"))
        window.continue_adventure()
        self.assertEqual(window.message.get(), status_text("continue_none"))
        self.assertFalse(self.instances)

    def test_a_missing_game_is_reported_before_anything_else(self):
        (self.directory / "game.gba").unlink()
        window = self.window()
        self.assertIn("not installed", window.menu.banner.cget("text"))
        card = window.menu.cards["continue"]
        self.assertEqual(card.title.cget("text"), "Set Up Your Game")
        card.invoke()
        self.assertEqual(window.message.get(), status_text("game_not_installed"))
        self.assertEqual(window.current_view, "settings")
        self.assertEqual(window.settings_tabs.select(), str(window.settings_pages["files"]))
        self.assertFalse(self.instances)

    def test_continue_hosts_the_last_world_with_the_last_address(self):
        record = self.world()
        RecentStore(self.private).record_session("host", record, "192.168.1.20", False)
        window = self.window()
        self.assertTrue(window.menu.cards["continue"].enabled)
        self.assertIn("Host", window.menu.cards["continue"].subtitle.cget("text"))
        window.continue_adventure()
        self.assertTrue(wait_for(self.root, lambda: self.instances))
        options = self.instances[0].options
        self.assertEqual(options["world_directory"], record.parent)
        self.assertEqual(options["bind_address"], "192.168.1.20")
        self.assertFalse(options["public"])
        self.assertEqual(window.current_view, "session")

    def test_continue_rejoins_the_last_invitation(self):
        invitation = self.directory / "friend.json"
        invitation.write_text("{}")
        RecentStore(self.private).record_session("join", invitation, "127.0.0.1", False)
        window = self.window()
        self.assertIn("Rejoin friend", window.menu.cards["continue"].subtitle.cget("text"))
        window.continue_adventure()
        self.assertTrue(wait_for(self.root, lambda: self.instances))
        self.assertEqual(self.instances[0].options["invitation_path"], invitation)

    def test_a_world_that_moved_cannot_be_continued_and_nothing_is_started(self):
        record = self.world()
        RecentStore(self.private).record_session("host", record, "127.0.0.1", False)
        record.unlink()
        window = self.window()
        self.assertFalse(window.menu.cards["continue"].enabled)
        self.assertIn("moved or been deleted", window.menu.cards["continue"].subtitle.cget("text"))
        window.continue_adventure()
        self.assertEqual(window.message.get(), status_text("continue_missing"))
        self.assertFalse(self.instances)

    def test_starting_a_game_remembers_it_for_next_time(self):
        record = self.world()
        window = self.window()
        window.selection["host"] = record
        window.address.set("127.0.0.1")
        window.start("host")
        self.assertTrue(wait_for(self.root, lambda: self.instances))
        last = RecentStore(self.private).last
        self.assertEqual((last.mode, last.selection), ("host", record))

    # ---- one session, one server

    def test_a_second_start_while_a_game_runs_is_refused_and_starts_no_second_server(self):
        record = self.world()
        window = self.window()
        window.selection["host"] = record
        window.start("host")
        self.assertTrue(wait_for(self.root, lambda: self.instances))
        self.assertTrue(self.worker.busy)
        window.start("host")
        window.continue_adventure()
        window.begin_host()
        self.root.update()
        time.sleep(0.1)
        self.assertEqual(len(self.instances), 1)

    def test_back_to_the_menu_waits_for_the_game_then_works(self):
        record = self.world()
        window = self.window()
        window.selection["host"] = record
        window.start("host")
        self.assertTrue(wait_for(self.root, lambda: self.instances))
        window.go_home()
        self.assertEqual(window.current_view, "session")
        self.assertEqual(window.message.get(), status_text("back_busy"))
        self.assertEqual(str(window.page_headers["session"].back.cget("state")), "disabled")
        session = self.instances[0]
        session.release_connect.set()
        self.assertTrue(session.played.wait(3))
        session.release_game.set()
        self.assertTrue(wait_for(self.root, lambda: not self.worker.busy and str(window.page_headers["session"].back.cget("state")) == "normal"))
        window.go_home()
        self.assertEqual(window.current_view, "home")
        self.assertTrue(window.menu.cards["continue"].enabled)

    # ---- Host Multiplayer

    def test_turning_on_internet_connections_asks_before_hosting(self):
        record = self.world()
        window = self.window()
        window.show_view("host")
        window.selection["host"] = record
        window.internet.set(True)
        window.begin_host()
        self.root.update()
        self.assertTrue(window.host_confirm.visible)
        self.assertFalse(self.instances)
        self.assertIn("port", window.host_confirm.text.cget("text"))
        window.host_confirm.cancel()
        self.assertFalse(window.host_confirm.visible)
        self.assertFalse(self.instances)
        window.begin_host()
        window.host_confirm.accept()
        self.assertTrue(wait_for(self.root, lambda: self.instances))
        self.assertTrue(self.instances[0].options["public"])

    def test_a_bad_address_is_refused_with_a_clear_message(self):
        window = self.window()
        window.selection["host"] = self.world()
        window.address.set("not an address")
        window.start("host")
        self.assertEqual(window.message.get(), status_text("address_invalid"))
        self.assertFalse(self.instances)

    def test_the_lan_address_button_fills_the_address_or_says_none_was_found(self):
        window = self.window()
        with patch("emerald_multiplayer.launcher_worlds.lan_addresses", return_value=["192.168.1.7"]):
            window.use_lan_address()
        self.assertEqual(window.address.get(), "192.168.1.7")
        with patch("emerald_multiplayer.launcher_worlds.lan_addresses", return_value=[]):
            window.use_lan_address()
        self.assertEqual(window.message.get(), status_text("lan_none"))
        self.assertEqual(window.address.get(), "192.168.1.7")

    def test_the_host_page_is_honest_about_the_internet(self):
        window = self.window()
        text = " ".join(widget.cget("text") for widget in _labels(window.views["host"]))
        self.assertIn("port forwarding", text)
        self.assertIn("no relay server", text)

    # ---- My Worlds

    def test_worlds_are_listed_with_their_players_and_a_world_can_be_picked_for_hosting(self):
        a, b = self.world("a"), self.world("b")
        entries = [WorldEntry(a.parent, a, ("Ash", "Misty"), STATUS_READY, 2.0), WorldEntry(b.parent, b, (), STATUS_INVALID, 1.0)]
        window = self.window()
        window._apply_worlds(entries)
        tree = window.world_tree
        self.assertEqual(len(tree.get_children()), 2)
        self.assertEqual(tree.item("0", "text"), "Ash's world with Misty")
        self.assertIn("needs attention", tree.item("1", "values")[1])
        tree.selection_set("1")
        self.root.update()
        self.assertEqual(str(window.world_host_button.cget("state")), "disabled", "a world that cannot be opened is not offered")
        tree.selection_set("0")
        self.root.update()
        self.assertEqual(str(window.world_host_button.cget("state")), "normal")
        window.host_selected_world()
        self.assertEqual(window.current_view, "host")
        self.assertEqual(window.selection["host"], a)
        self.assertEqual(window.host_choice.get(), "Ash's world with Misty")

    def test_a_single_world_is_preselected_on_the_host_page(self):
        a = self.world("a")
        window = self.window()
        window._apply_worlds([WorldEntry(a.parent, a, ("Red",), STATUS_READY, 1.0)])
        self.assertEqual(window.selection["host"], a)

    def test_the_world_scan_runs_in_the_background_and_fills_the_list(self):
        a = self.world("a")
        entries = [WorldEntry(a.parent, a, ("Gold",), STATUS_READY, 1.0)]
        with patch("emerald_multiplayer.launcher_worlds.scan_worlds", return_value=entries):
            window = self.window()
            window.show_view("worlds")
            self.assertTrue(wait_for(self.root, lambda: window.worlds))
        self.assertEqual(window.worlds[0].names, ("Gold",))

    def test_setup_opens_inside_this_window_not_as_a_popup(self):
        window = self.window()
        created = {}

        class FakeSetup:
            def __init__(self, parent, installation, private_root, **options):
                created.update(options)
                self.options = options

        with patch("emerald_multiplayer.launcher_setup_gui.SetupWindow", FakeSetup):
            window.open_setup(role="host")
        self.assertTrue(wait_for(self.root, lambda: created))
        self.assertIs(created["container"], window.setup_host)
        self.assertEqual(created["start_role"], "host")
        self.assertEqual(window.current_view, "setup")
        self.assertEqual(len([w for w in self.root.winfo_children() if w.winfo_class() == "Toplevel"]), 0)

    # ---- Join Friend

    def test_join_page_says_there_are_no_invite_codes_or_discovery(self):
        window = self.window()
        text = " ".join(widget.cget("text") for widget in _labels(window.views["join"]))
        self.assertIn("no invite codes", text)
        self.assertIn("automatic discovery", text)

    def test_joining_without_an_invitation_asks_for_one(self):
        window = self.window()
        window.start("join")
        self.assertEqual(window.message.get(), status_text("selection_required"))
        self.assertFalse(self.instances)

    def test_recent_invitations_are_offered_and_chosen_by_name(self):
        invitation = self.directory / "friend-ada.json"
        invitation.write_text("{}")
        RecentStore(self.private).record_session("join", invitation, "127.0.0.1", False)
        window = self.window()
        window.show_view("join")
        self.assertEqual(list(window.recent_chooser.cget("values")), ["friend-ada"])
        with patch.object(self.worker, "start_probe", return_value=True) as probe:
            window.recent_chooser.current(0)
            window._recent_invitation_changed()
        self.assertEqual(window.selection["join"], invitation)
        probe.assert_called_once()

    def test_unreachable_servers_and_bad_invitations_give_clear_messages_and_the_menu_stays_usable(self):
        from emerald_multiplayer.launcher_gui import UiEvent
        window = self.window()
        window.show_view("join")
        for code in ("unreachable", "connection_timed_out", "connection_refused", "network_unavailable", "connection_blocked",
                     "invalid_invitation", "certificate_invalid", "host_identity_invalid", "build_mismatch", "connection_timeout"):
            self.worker.events.put(UiEvent("complete", code))
            self.assertTrue(wait_for(self.root, lambda: window.message.get() == status_text(code)), code)
            self.assertNotIn("Traceback", window.message.get())
            self.assertNotEqual(window.message.get(), status_text("session_failed"), code + " must have its own message")
            self.assertEqual(str(window.join_button.cget("state")), "normal")
            self.assertEqual(window.current_view, "join")

    def test_a_session_that_fails_to_open_returns_the_player_to_a_usable_menu(self):
        record = self.world()
        window = self.window()
        window.selection["host"] = record
        window.start("host")
        self.assertTrue(wait_for(self.root, lambda: self.instances))
        self.instances[0].error = RuntimeError("the host could not start")
        self.instances[0].release_connect.set()
        self.assertTrue(wait_for(self.root, lambda: not self.worker.busy))
        self.assertTrue(wait_for(self.root, lambda: str(window.page_headers["session"].back.cget("state")) == "normal"))
        window.go_home()
        self.assertEqual(window.current_view, "home")
        self.assertEqual(str(window.host_button.cget("state")), "normal")

    # ---- Exit

    def test_exit_with_nothing_running_closes_the_window(self):
        window = self.window()
        with patch.object(window, "close") as close:
            window.exit_game()
        close.assert_called_once()

    def test_exit_while_a_game_runs_asks_first(self):
        record = self.world()
        window = self.window()
        window.selection["host"] = record
        window.start("host")
        self.assertTrue(wait_for(self.root, lambda: self.instances))
        window.show_view("home")        # (the menu cannot be reached by Back while running; Exit is reachable by keyboard)
        with patch.object(window, "close") as close:
            window.exit_game()
            self.root.update()
            self.assertTrue(window.menu.confirm.visible)
            close.assert_not_called()
            window.menu.confirm.cancel()
            close.assert_not_called()
            window.exit_game()
            window.menu.confirm.accept()
            close.assert_called_once()

    # ---- Settings

    def test_settings_shows_the_files_and_launcher_pages_and_hides_game_pages_for_a_non_native_package(self):
        window = self.window()
        window.show_view("settings")
        states = {key: window.settings_tabs.tab(str(page), "state") for key, page in window.settings_pages.items()}
        self.assertEqual(states["display"], "hidden")
        self.assertEqual(states["keys"], "hidden")
        self.assertEqual(states["files"], "normal")
        self.assertIn("installed", window.game_state.get() + "installed")

    def test_audio_settings_are_saved_to_the_games_file_and_other_lines_are_kept(self):
        self.worker.installation.bundle.is_native = lambda: True
        self.worker.installation.bundle.has_classic = lambda: True
        (self.private / "game-settings.cfg").write_text("key.a=Q\nvolume=7\n")
        window = self.window()
        window.show_view("settings")
        self.root.update()
        states = {key: window.settings_tabs.tab(str(page), "state") for key, page in window.settings_pages.items()}
        self.assertEqual((states["display"], states["audio"], states["keys"]), ("normal", "normal", "normal"))
        page = next(w for w in _walk(window.settings_pages["audio"]) if hasattr(w, "audio_save"))
        self.assertEqual(page.audio_scales["volume"].get(), 7)
        page.audio_scales["volume"].set(3)
        page.audio_scales["cry_volume"].set(0)
        page.audio_save()
        lines = (self.private / "game-settings.cfg").read_text().splitlines()
        self.assertIn("key.a=Q", lines)
        self.assertIn("volume=3", lines)
        self.assertIn("cryVolume=0", lines)

    def test_settings_cannot_be_saved_while_a_game_runs(self):
        self.worker.installation.bundle.is_native = lambda: True
        self.worker.installation.bundle.has_classic = lambda: True
        (self.private / "game-settings.cfg").write_text("volume=7\n")
        window = self.window()
        record = self.world()
        window.selection["host"] = record
        window.start("host")
        self.assertTrue(wait_for(self.root, lambda: self.instances))
        window._refresh_settings()
        page = next(w for w in _walk(window.settings_pages["audio"]) if hasattr(w, "audio_save"))
        page.audio_scales["volume"].set(1)
        page.audio_save()
        self.assertEqual((self.private / "game-settings.cfg").read_text(), "volume=7\n")


def _walk(widget):
    stack = [widget]
    while stack:
        item = stack.pop()
        yield item
        stack.extend(item.winfo_children())


def _labels(widget):
    found = []
    stack = [widget]
    while stack:
        item = stack.pop()
        if item.winfo_class() in {"TLabel", "Label"} and item.cget("text"):
            found.append(item)
        stack.extend(item.winfo_children())
    return found


if __name__ == "__main__":
    unittest.main()
