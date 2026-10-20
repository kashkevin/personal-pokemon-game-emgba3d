"""Real save/container/file-lock checks; no game or original character files."""
import hashlib
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from emerald_multiplayer.character_handoff import (
    CharacterHandoffError, export_character_source, inspect_character_source,
)
from emerald_multiplayer.checkpoint_mirror import MirrorLease
from emerald_multiplayer.launcher_session import GameInstallation
from emerald_multiplayer.launcher_setup_gui import SetupWorker, SetupWindow
from test_host_world import make_trade_files
from test_ownership import make_ownership_flash
from test_ownership_storage import source_flash
from test_player_runtime import write_bundle


class CharacterHandoffTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.private = self.root / "private"
        self.private.mkdir()
        rom, manifest = make_trade_files(self.root)
        bundle = self.root / "bundle"
        bundle.mkdir()
        digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        self.installation = GameInstallation(rom, manifest, digest(rom), digest(manifest), write_bundle(bundle))
        self.source = self.root / "original.sav"
        self.payload = source_flash()
        self.source.write_bytes(self.payload)
        self.destination = self.root / "character-for-host.sav"

    def inspect(self):
        return inspect_character_source(self.installation, self.source)

    def export(self, selection, destination=None):
        return export_character_source(self.installation, self.private, selection,
                                       destination or self.destination)

    def denied(self, code, function, *args, **kwargs):
        with self.assertRaises(CharacterHandoffError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_closed_unassigned_source_copies_exactly_without_enrollment_or_overwrite(self):
        selection = self.inspect()
        self.assertEqual(selection.party_count, 1)
        self.assertEqual(self.export(selection), self.destination)
        self.assertEqual(self.destination.read_bytes(), self.payload)
        self.assertEqual(self.source.read_bytes(), self.payload)
        self.assertFalse(list(self.private.iterdir()))
        self.denied("character_exists", self.export, selection)
        self.assertEqual(self.destination.read_bytes(), self.payload)
        self.assertFalse(list(self.root.glob(".character-*")))

    def test_changed_selected_source_fails_before_dialog_and_before_publication(self):
        selection = self.inspect()
        self.source.write_bytes(source_flash(personalities=(12345,)))
        self.denied("source_changed", inspect_character_source, self.installation,
                    self.source, expected=selection)
        self.denied("source_changed", self.export, selection)
        self.assertFalse(self.destination.exists())

    def test_owned_and_invalid_sources_cannot_be_selected(self):
        for payload, code in ((b"not a save", "invalid_source"),
                (make_ownership_flash(), "invalid_source")):
            with self.subTest(code=code, size=len(payload)):
                self.source.write_bytes(payload)
                self.denied(code, self.inspect)
        self.assertFalse(self.destination.exists())

    def test_starterless_new_character_is_selected_and_copied_exactly(self):
        # Update 32: the short introduction saves before the starter is claimed in Birch's lab.
        self.payload = source_flash(locations=())
        self.source.write_bytes(self.payload)
        selection = self.inspect()
        self.assertEqual(selection.party_count, 0)
        self.assertEqual(self.export(selection), self.destination)
        self.assertEqual(self.destination.read_bytes(), self.payload)

    def test_live_draft_lease_blocks_inspection_and_export(self):
        selection = self.inspect()
        with MirrorLease(self.source):
            self.denied("mirror_active", self.inspect)
            self.denied("mirror_active", self.export, selection)
        self.assertFalse(self.destination.exists())

    def test_managed_world_paths_original_and_non_save_destinations_refused(self):
        selection = self.inspect()
        for path in (self.source, self.private / "character.sav", self.root / "host.json"):
            with self.subTest(path=path.name):
                self.denied("character_destination", self.export, selection, path)
        self.assertEqual(self.source.read_bytes(), self.payload)
        self.assertFalse(list(self.private.iterdir()))

    def test_late_destination_creation_cannot_overwrite_other_data(self):
        selection = self.inspect()
        import os
        link = os.link
        def race(source, destination):
            destination.write_bytes(b"already there")
            return link(source, destination)
        with patch("emerald_multiplayer.character_handoff.os.link", race):
            self.denied("character_exists", self.export, selection)
        self.assertEqual(self.destination.read_bytes(), b"already there")
        self.assertEqual(self.source.read_bytes(), self.payload)

    def test_installation_replacement_invalidates_copy_before_any_destination(self):
        selection = self.inspect()
        self.installation.rom_path.write_bytes(b"changed game")
        self.denied("installation_changed", self.export, selection)
        self.assertFalse(self.destination.exists())

    def test_worker_returns_only_validated_selection_and_completed_export(self):
        worker = SetupWorker(self.installation, self.private)
        self.assertTrue(worker.start("source", source_path=self.source))
        worker.thread.join(5)
        self.assertFalse(worker.busy)
        event = worker.events.get_nowait()
        self.assertEqual(event.code, "source_selected")
        self.assertEqual(event.source_path, self.source)
        self.assertTrue(worker.start("export_character", selection=event.character_source,
                                     destination=self.destination))
        worker.thread.join(5)
        self.assertFalse(worker.busy)
        self.assertEqual(worker.events.get_nowait().code, "character_exported")
        self.assertEqual(self.destination.read_bytes(), self.payload)

    def widget(self):
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        worker = SetupWorker(self.installation, self.private)
        window = SetupWindow(root, self.installation, self.private, worker=worker)
        window.root.withdraw()
        def close():
            worker.cancel()
            if worker.thread:
                worker.thread.join(5)
            self.assertFalse(worker.busy)
            window.destroy()
            root.destroy()
        self.addCleanup(close)
        return root, window

    def settle_widget(self, root, window, predicate):
        until = time.monotonic() + 5
        while time.monotonic() < until:
            root.update()
            if predicate() and not window.worker.busy and window.worker.events.empty():
                return
            time.sleep(.01)
        self.fail("setup operation did not settle")

    def test_friend_ui_selects_valid_source_then_exports_without_world_or_approval(self):
        root, window = self.widget()
        window.begin_role("friend")
        self.assertEqual(window.tabs.select(), str(window.character_page))
        self.assertFalse(window.host_frame.winfo_manager())
        self.assertEqual(window.friend_frame.winfo_manager(), "pack")
        with patch("tkinter.filedialog.askopenfilename", return_value=str(self.source)):
            window.choose_source()
        self.settle_widget(root, window, lambda: window.character_source is not None)
        with patch("tkinter.filedialog.asksaveasfilename", return_value=str(self.destination)) as dialog:
            window.export_character()
            self.settle_widget(root, window, lambda: "Character copy saved" in window.status.get())
        dialog.assert_called_once()
        self.assertIsNone(window.world_directory)
        self.assertFalse(window.approval.get())
        self.assertEqual(self.destination.read_bytes(), self.payload)
        self.assertEqual(self.source.read_bytes(), self.payload)

    def test_stale_selected_source_is_refused_before_save_as_is_opened(self):
        root, window = self.widget()
        window.source_path, window.character_source = self.source, self.inspect()
        self.source.write_bytes(source_flash(personalities=(991,)))
        with patch("tkinter.filedialog.asksaveasfilename") as dialog:
            window.export_character()
            self.settle_widget(root, window, lambda: "source changed" in window.status.get())
        dialog.assert_not_called()
        self.assertIsNone(window.pending_character_export)
        self.assertFalse(self.destination.exists())

    def test_source_changed_during_save_as_cannot_publish(self):
        root, window = self.widget()
        window.source_path, window.character_source = self.source, self.inspect()
        def changed_dialog(**_):
            self.source.write_bytes(source_flash(personalities=(994,)))
            return str(self.destination)
        with patch("tkinter.filedialog.asksaveasfilename", side_effect=changed_dialog):
            window.export_character()
            self.settle_widget(root, window, lambda: "source changed" in window.status.get())
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
