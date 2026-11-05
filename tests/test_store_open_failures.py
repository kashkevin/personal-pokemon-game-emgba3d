"""A world's side stores refused while opening leave no connection open (Windows: an open file cannot be replaced or
deleted while the process lives; the whole suite's first Windows run, run 304, met it as WinError 32 at the tests'
cleanups).

The shared world, friendship and wager stores each keep one SQLite connection; one refused (another world's data beside
this world's) closed it only when garbage collection came round. And the world server opens the three in turn: one
refused left the ones before it open."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from emerald_multiplayer import friendship, shared_world, wagers
from emerald_multiplayer.friendship import FriendshipError, FriendshipStore
from emerald_multiplayer.shared_world import SharedWorld, SharedWorldError
from emerald_multiplayer.wagers import WagerError, Wagers

_CONNECT = sqlite3.connect      # the real one: the stores' modules share the sqlite3 module the tests patch
WORLD = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


def closed(connection) -> bool:
    try:
        connection.execute("SELECT 1")
    except sqlite3.ProgrammingError:
        return True
    return False


class RecordingConnect:
    """sqlite3.connect for one module, keeping every connection it made."""

    def __init__(self):
        self.made = []

    def __call__(self, *args, **kwargs):
        connection = _CONNECT(*args, **kwargs)
        self.made.append(connection)
        return connection


class StoreOpenFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def refused_closes(self, module, opener, error):
        path = self.root / f"{module.__name__.rsplit('.', 1)[1]}.sqlite3"
        opener(path, WORLD).close()                      # this world's file
        recording = RecordingConnect()
        with mock.patch.object(module.sqlite3, "connect", recording):
            with self.assertRaises(error):
                opener(path, OTHER)                      # another world's: refused
        self.assertEqual(len(recording.made), 1)
        self.assertTrue(closed(recording.made[0]), "the refused store's connection is still open")
        opener(path, WORLD).close()                      # the file itself unchanged and usable

    def test_a_refused_shared_world_closes_its_connection(self):
        self.refused_closes(shared_world, SharedWorld, SharedWorldError)

    def test_a_refused_friendship_store_closes_its_connection(self):
        self.refused_closes(friendship, FriendshipStore, FriendshipError)

    def test_a_refused_wager_store_closes_its_connection(self):
        self.refused_closes(wagers, Wagers, WagerError)


class ServerOpenFailureTests(unittest.TestCase):
    def test_the_server_closes_the_stores_it_opened_when_a_later_one_is_refused(self):
        from emerald_multiplayer import server as server_module
        opened = []

        class Recording:
            def __init__(self, real):
                self.real = real

            def __call__(self, *args, **kwargs):
                store = self.real(*args, **kwargs)
                opened.append(store)
                return store

        def refused(*args, **kwargs):
            raise WagerError("world_mismatch", "wager data belongs to another world")

        store = mock.MagicMock()
        store.path = Path(tempfile.mkdtemp()) / "world.sqlite3"
        self.addCleanup(lambda: __import__("shutil").rmtree(store.path.parent, ignore_errors=True))
        store.metadata.world_id = WORLD
        store.reset_attempts_enabled = False
        store.battle_reservations_enabled = False
        config = mock.MagicMock()
        store.build_id, store.ruleset_id = config.build_id, config.ruleset_id
        from emerald_multiplayer.flash import LAYOUT_ID
        store.save_profile = LAYOUT_ID
        with mock.patch("emerald_multiplayer.shared_world.SharedWorld", Recording(SharedWorld)), \
                mock.patch("emerald_multiplayer.friendship.FriendshipStore", Recording(FriendshipStore)), \
                mock.patch("emerald_multiplayer.wagers.Wagers", refused):
            with self.assertRaises(WagerError):
                server_module.WorldServer(config, store=store)
        self.assertEqual([type(s).__name__ for s in opened], ["SharedWorld", "FriendshipStore"])
        for store_opened in opened:
            self.assertIsNone(store_opened._db, f"{type(store_opened).__name__} left open")


if __name__ == "__main__":
    unittest.main()
