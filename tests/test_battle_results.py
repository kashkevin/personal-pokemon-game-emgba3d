"""SQLite/Flash and simulated native receipts; not an actual game proof."""
from copy import deepcopy
from contextlib import closing
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
from uuid import uuid4

from emerald_multiplayer.battle_desk import BattleDesk
from emerald_multiplayer.battle_results import BattleResults
from emerald_multiplayer.storage import StorageError
import test_battle_desk as fixture
import test_battle_multi_desk as multi


class BattleResultTests(unittest.TestCase):
    tearDown = fixture.BattleDeskTests.tearDown
    actor = fixture.BattleDeskTests.actor
    call = fixture.BattleDeskTests.call
    descriptor = fixture.BattleDeskTests.descriptor
    control = fixture.BattleDeskTests.control
    query = fixture.BattleDeskTests.query
    accept = fixture.BattleDeskTests.accept
    register = fixture.BattleDeskTests.register
    bind = fixture.BattleDeskTests.bind
    prepare = fixture.BattleDeskTests.prepare
    prepared = fixture.BattleDeskTests.prepared
    start = fixture.BattleDeskTests.start
    parts = fixture.BattleDeskTests.parts
    running = fixture.BattleDeskTests.running
    finish = fixture.BattleDeskTests.finish
    release = fixture.BattleDeskTests.release
    assert_code = fixture.BattleDeskTests.assert_code

    def setUp(self):
        fixture.BattleDeskTests.setUp(self)
        self.archive_path = Path(self.temp.name) / "results.sqlite3"
        self.archive = self.reopen()
        self.desk.results = self.archive

    def reopen(self):
        return BattleResults(self.archive_path, world_id=self.store.metadata.world_id,
            build_id=self.store.build_id, ruleset_id=self.store.ruleset_id)

    def history(self, index=0):
        return self.archive.history(self.players[index].player_id)

    def complete(self):
        self.running(); self.finish(0); self.finish(1); self.release(0)
        return self.release(1)

    def test_publishes_only_after_all_restoration_and_release_receipts(self):
        self.running(); self.finish(0)
        self.assertEqual(self.history(), [])
        self.finish(1); self.release(0)
        self.assertEqual(self.history(), [])
        result, request, response = self.release(1)
        self.assertEqual(result["state"], "closed")
        history = self.history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history, self.history(1))
        self.assertEqual(self.history(2), [])
        self.assertEqual(history[0]["outcome"], 1)
        self.assertEqual(history[0]["sequence"], 1)
        self.assertEqual(self.call("released", 1, request, response), result)
        self.assertEqual(self.reopen().history(self.players[0].player_id), history)
        for i in range(4): self.assertEqual(self.store.read_checkpoint(*self.actor(i)), self.heads[i])

    def test_restarted_desk_refuses_completed_battle_id(self):
        self.complete()
        desk = BattleDesk(self.store, self.leases.get, results=self.reopen())
        self.assert_code("battle_result_conflict", desk.invite, *self.actor(0), self.players[1].player_id, self.battle_id)

    def test_conflicting_native_outcomes_never_publish(self):
        self.running(); self.finish(0)
        self.assert_code("battle_result_mismatch", self.finish, 1, outcome=2)
        self.assertEqual(self.history(), [])
        self.assertEqual(self.call("status", 0)["state"], "recovery_required")

    def test_archive_failure_retains_final_server_barrier_and_exact_retry(self):
        self.running(); self.finish(0); self.finish(1); self.release(0)
        with patch.object(self.archive, "_append_closed", side_effect=StorageError("battle_archive_unavailable", "simulated")):
            self.assert_code("battle_archive_unavailable", self.release, 1)
        view = self.call("status", 0)
        self.assertEqual(view["state"], "release_authorized")
        self.assertEqual(view["released"], [self.players[0].player_id])
        self.assertEqual(self.release(1)[0]["state"], "closed")
        self.assertEqual(len(self.history()), 1)

    def test_uncertain_commit_retry_does_not_duplicate_result(self):
        self.running(); self.finish(0); self.finish(1); self.release(0)
        append = self.archive._append_closed
        def committed_then_failed(*args):
            append(*args)
            raise StorageError("battle_archive_unavailable", "simulated lost acknowledgment")
        with patch.object(self.archive, "_append_closed", side_effect=committed_then_failed):
            self.assert_code("battle_archive_unavailable", self.release, 1)
        self.assertEqual(len(self.history()), 1)
        self.release(1)
        self.assertEqual(len(self.history()), 1)

    def test_repeated_id_cannot_change_outcome_or_receipts(self):
        self.complete()
        with closing(sqlite3.connect(self.archive_path)) as connection:
            import json
            record = json.loads(connection.execute("SELECT record FROM results").fetchone()[0])
        self.assertEqual(self.archive._append_closed(**record), self.history()[0])
        changed = deepcopy(record); changed["summary"]["outcome"] = 2
        self.assert_code("battle_result_conflict", self.archive._append_closed, **changed)
        changed = deepcopy(record); changed["receipts_sha256"] = "0" * 64
        self.assert_code("battle_result_conflict", self.archive._append_closed, **changed)

    def test_corruption_unknown_schema_and_foreign_world_fail_closed(self):
        self.complete()
        with closing(sqlite3.connect(self.archive_path)) as connection:
            connection.execute("UPDATE results SET sha256 = ?", ("0" * 64,))
            connection.commit()
        self.assert_code("battle_archive_invalid", self.history)
        self.assert_code("battle_archive_mismatch", BattleResults, self.archive_path,
            world_id=str(uuid4()), build_id=self.store.build_id, ruleset_id=self.store.ruleset_id)
        with closing(sqlite3.connect(self.archive_path)) as connection:
            connection.execute("CREATE TABLE unexpected (x INTEGER)")
            connection.commit()
        self.assert_code("battle_archive_invalid", self.reopen)

    def test_sql_failure_rolls_back_and_leaves_native_barrier(self):
        self.running(); self.finish(0); self.finish(1); self.release(0)
        with patch.object(self.archive, "_read", side_effect=StorageError("battle_archive_invalid", "simulated readback error")):
            self.assert_code("battle_archive_invalid", self.release, 1)
        self.assertEqual(self.history(), [])
        self.assertEqual(self.call("status", 0)["state"], "release_authorized")
        self.release(1)
        self.assertEqual(len(self.history()), 1)

    def test_existing_empty_or_truncated_archive_is_not_reinitialized(self):
        self.complete()
        self.archive_path.write_bytes(b"")
        self.assert_code("battle_archive_invalid", self.reopen)
        self.assertEqual(self.archive_path.stat().st_size, 0)


class MultiBattleResultTests(unittest.TestCase):
    tearDown = fixture.BattleDeskTests.tearDown
    actor = fixture.BattleDeskTests.actor
    call = fixture.BattleDeskTests.call
    descriptor = fixture.BattleDeskTests.descriptor
    control = fixture.BattleDeskTests.control
    query = fixture.BattleDeskTests.query
    bind = fixture.BattleDeskTests.bind
    prepare = fixture.BattleDeskTests.prepare
    start = fixture.BattleDeskTests.start
    parts = fixture.BattleDeskTests.parts
    finish = fixture.BattleDeskTests.finish
    release = fixture.BattleDeskTests.release
    reopen = BattleResultTests.reopen
    history = BattleResultTests.history

    def setUp(self):
        multi.MultiBattleDeskTests.setUp(self)
        self.archive_path = Path(self.temp.name) / "results.sqlite3"
        self.archive = self.reopen()
        self.desk.results = self.archive

    invite = multi.MultiBattleDeskTests.invite
    accepted = multi.MultiBattleDeskTests.accepted
    registered = multi.MultiBattleDeskTests.registered
    prepared = multi.MultiBattleDeskTests.prepared
    running = multi.MultiBattleDeskTests.running

    # Singles-specific assertions are already covered above; this scenario
    # isolates the four-party final barrier and exact full roster persistence.
    def test_fourth_release_is_required(self):
        self.running()
        for i in range(4): self.finish(i)
        for i in range(3):
            self.release(i)
            self.assertEqual(self.history(), [])
        self.assertEqual(self.release(3)[0]["state"], "closed")
        result = self.history()[0]
        self.assertEqual(result["mode"], 3)
        self.assertEqual(result["players"], self.view["players"])
        self.assertEqual(len(result["checkpoints"]), 4)
        for i in range(4): self.assertEqual(self.history(i), [result])
