"""Real disposable SQLite/consent files; no emulator or player save acceptance."""
import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from emerald_multiplayer.battle_desk import BattleDesk, BattleError
from emerald_multiplayer.battle_execution import BattleExecutionService
from emerald_multiplayer.championship import Championships
from emerald_multiplayer.championship_protocol import validate_championship_reply, validate_championship_request
from emerald_multiplayer.championship_menu import ChampionshipMenu
from emerald_multiplayer.launcher_championship_panel import ChampionshipPanelController, ChampionshipPanelError
from emerald_multiplayer.protocol import ProtocolError
from emerald_multiplayer.storage import StorageError
from emerald_multiplayer.trade_storage import TradeCheckpointStore
import test_battle_desk as fixtures


class ProcessLoss(BaseException):
    pass


class ChampionshipRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BattleDeskTests()
        self.fixture.setUp()
        self.root = Path(self.fixture.temp.name)
        self.store, self.desk, self.leases = self.fixture.store, self.fixture.desk, self.fixture.leases
        self.players = [p.player_id for p in self.fixture.players]
        self.roster = {p: "Trainer " + str(i) for i, p in enumerate(self.players)}
        self.desk.cancel(self.players[0], self.leases[self.players[0]], self.fixture.battle_id, self.fixture.generation)
        self.execution = BattleExecutionService(self.desk, (None,) * 721, self.root / "execution", resume_enabled=True)
        self.identities = {p: dict(incarnation=i+100, runtime_id=str(uuid4())) for i, p in enumerate(self.players)}
        self.champ = self.open_champ()
        self.view = None
        self.invites = []
        self.call("create", championship_id=str(uuid4()), players=list(self.players))
        for i in range(1, 4):
            self.call("accept", actor=i)

    def tearDown(self):
        self.fixture.store = self.store
        self.fixture.tearDown()

    def open_champ(self):
        return Championships(self.root / "championship.sqlite3", world_id=self.store.metadata.world_id,
                             build_id=self.store.build_id, ruleset_id=self.store.ruleset_id)

    def call(self, operation, actor=0, invite=None, **fields):
        request = dict(version=1, operation=operation)
        if operation not in {"status", "history", "create"}:
            request.update({key: self.view[key] for key in ("championship_id", "generation", "fingerprint")})
        if operation in {"match", "recover"}:
            match = self.view["matches"][fields.get("round", 0)]
            request.update(round=match["round"], attempt=match["attempt"])
            if operation == "recover":
                request["battle_id"] = match["battle_id"]
        request.update(fields)
        player = self.players[actor]
        def original_invite(battle_id, peer):
            self.invites.append(battle_id)
            self.desk.invite(player, self.leases[player], peer, battle_id)
            self.execution.admission.capture(player, self.leases[player],
                                            dict(battle_id=battle_id, **self.identities[player]))
        reply = self.champ.handle(player, request, roster=self.roster, desk=self.desk, results=None,
            invite=original_invite if invite is None else invite,
            reservations=self.desk.reservations, admission=self.execution.admission)
        validate_championship_reply(reply, player, request)
        self.view = reply["current"]
        return reply

    def restart(self):
        self.store.close()
        self.store = TradeCheckpointStore(self.fixture.store.path, "test-build", "test-rules")
        self.store.begin_server_boot()
        self.leases = {p.player_id: self.store.acquire_lease(p.player_id, p.credential) for p in self.fixture.players}
        self.desk = BattleDesk(self.store, self.leases.get)
        self.execution = BattleExecutionService(self.desk, (None,) * 721, self.root / "execution", resume_enabled=True)
        self.champ = self.open_champ()
        self.call("status")

    def pending_cut(self):
        with patch.object(self.champ, "_begin_issue", side_effect=ProcessLoss):
            with self.assertRaises(ProcessLoss):
                self.call("match")
        self.call("status")
        return self.view["matches"][0]["battle_id"]

    def test_pre_dispatch_crash_is_recoverable_but_rematch_is_a_separate_explicit_request(self):
        battle_id = self.pending_cut()
        self.assertFalse(self.invites)
        self.restart()
        self.assertEqual(self.view["matches"][0]["state"], "waiting")
        self.call("recover")
        self.assertEqual(self.view["matches"][0]["state"], "canceled")
        self.assertEqual(self.view["matches"][0]["battle_id"], battle_id)
        self.call("recover")
        self.call("match", attempt=0)  # Lost original reply cannot issue attempt 2.
        self.assertFalse(self.invites)
        self.call("match")
        self.assertEqual(self.view["matches"][0]["attempt"], 2)
        self.assertNotEqual(self.view["matches"][0]["battle_id"], battle_id)
        self.assertEqual(len(self.invites), 1)
        self.assertIsNone(self.view["champion"])

    def test_dispatch_fence_without_invitation_evidence_remains_uncertain(self):
        def lost(*args):
            raise ProcessLoss()
        with self.assertRaises(ProcessLoss):
            self.call("match", invite=lost)
        self.restart()
        before = deepcopy(self.view)
        self.call("recover")
        self.assertEqual(self.view, before)
        self.assertFalse(self.invites)

    def test_legacy_attempt_does_not_gain_fabricated_pre_dispatch_evidence(self):
        battle_id = self.pending_cut()
        with self.champ._transaction() as connection:
            attempt = self.champ._attempt(connection.execute("SELECT * FROM attempts WHERE battle_id=?", (battle_id,)).fetchone())
            attempt.pop("issuance")
            self.champ._save_attempt(connection, attempt)
        self.restart()
        self.call("recover")
        self.assertEqual(self.view["matches"][0]["state"], "waiting")

    def test_partial_original_consent_after_restart_can_be_revoked_and_fences_late_bind(self):
        self.call("match")
        battle_id = self.view["matches"][0]["battle_id"]
        before_heads = [(cp.revision, cp.sha256, cp.payload) for cp in self.fixture.heads]
        self.restart()
        self.call("recover", actor=1)
        self.assertEqual(self.view["matches"][0]["state"], "canceled")
        path = self.execution.admission._path(battle_id)
        tombstone = path.read_bytes()
        self.assertTrue(self.execution.admission._read(battle_id)["canceled"])
        with self.assertRaises(BattleError):
            self.execution.admission.assert_not_canceled(battle_id)
        self.call("recover")
        self.assertEqual(path.read_bytes(), tombstone)
        after_heads = [self.store.read_checkpoint(p, self.leases[p]) for p in self.players]
        self.assertEqual([(cp.revision, cp.sha256, cp.payload) for cp in after_heads], before_heads)
        self.assertEqual(self.store._connection.execute("SELECT COUNT(*) FROM battle_reservations").fetchone()[0], 0)

    def test_tombstone_write_before_volatile_archive_is_retryable_without_new_invitation(self):
        self.call("match")
        battle_id = self.view["matches"][0]["battle_id"]
        battle = self.desk._active[battle_id]
        self.desk._recover(battle, "original_consent_not_durable")
        self.call("status")
        with patch.object(self.desk, "_abort", side_effect=OSError("lost after tombstone")):
            with self.assertRaises(StorageError) as error:
                self.call("recover")
            self.assertEqual(error.exception.code, "championship_unavailable")
        tombstone = self.execution.admission._path(battle_id).read_bytes()
        self.assertTrue(self.execution.admission._read(battle_id)["canceled"])
        self.restart()
        self.assertEqual(self.view["matches"][0]["state"], "canceled")
        self.call("recover")
        self.assertEqual(self.execution.admission._path(battle_id).read_bytes(), tombstone)
        self.assertEqual(len(self.invites), 1)

    def test_complete_consent_and_raw_enter_claim_remain_waiting_without_handoff_receipts(self):
        self.call("match")
        battle_id = self.view["matches"][0]["battle_id"]
        battle = self.desk._active[battle_id]
        actor = self.players[1]
        self.desk.accept(actor, self.leases[actor], battle_id, battle.generation, battle.fingerprint)
        self.execution.admission.capture(actor, self.leases[actor], dict(battle_id=battle_id, **self.identities[actor]))
        self.execution.admission.claim(actor, self.leases[actor],
            dict(battle_id=battle_id, generation=battle.generation, **self.identities[actor]))
        original = self.execution.admission._path(battle_id).read_bytes()
        self.restart()
        self.call("recover")
        self.assertEqual(self.view["matches"][0]["state"], "waiting")
        self.assertEqual(self.execution.admission._path(battle_id).read_bytes(), original)

    def test_any_route_evidence_refuses_partial_consent_revocation(self):
        self.call("match")
        battle_id = self.view["matches"][0]["battle_id"]
        original = self.execution.admission._path(battle_id).read_bytes()
        (self.execution.directory / (battle_id + ".events.jsonl")).write_bytes(b"uncertain route")
        self.restart()
        self.call("recover")
        self.assertEqual(self.view["matches"][0]["state"], "waiting")
        self.assertEqual(self.execution.admission._path(battle_id).read_bytes(), original)

    def test_wrong_round_actor_attempt_or_battle_cannot_cancel_retained_invitation(self):
        self.call("match")
        battle_id = self.view["matches"][0]["battle_id"]
        self.restart()
        original = self.execution.admission._path(battle_id).read_bytes()
        for changes in (dict(actor=2), dict(attempt=2), dict(battle_id=str(uuid4()))):
            with self.subTest(changes=changes), self.assertRaises(ProtocolError):
                self.call("recover", **changes)
            self.assertEqual(self.execution.admission._path(battle_id).read_bytes(), original)

    def test_all_cancel_votes_can_settle_after_explicit_safe_recovery_without_a_champion(self):
        self.pending_cut()
        for i in range(4):
            self.call("cancel", actor=i)
        self.assertEqual(self.view["state"], "active")
        self.call("recover")
        self.assertEqual(self.view["state"], "canceled")
        self.assertIsNone(self.view["champion"])
        self.assertFalse(self.invites)

    def test_pending_phase_with_contradictory_native_evidence_is_an_integrity_failure(self):
        self.call("match")
        battle_id = self.view["matches"][0]["battle_id"]
        with self.champ._transaction() as connection:
            attempt = self.champ._attempt(connection.execute("SELECT * FROM attempts WHERE battle_id=?", (battle_id,)).fetchone())
            attempt.update(issuance="pending", native_generation=None)
            self.champ._save_attempt(connection, attempt)
        original = self.execution.admission._path(battle_id).read_bytes()
        with self.assertRaises(StorageError):
            self.call("recover")
        self.assertEqual(self.execution.admission._path(battle_id).read_bytes(), original)

    def test_recovery_reply_cannot_replace_the_requested_attempt(self):
        self.pending_cut()
        match = self.view["matches"][0]
        request = dict(version=1, operation="recover", round=0, attempt=match["attempt"], battle_id=match["battle_id"],
            **{key:self.view[key] for key in ("championship_id", "generation", "fingerprint")})
        validate_championship_request(request)
        reply = dict(version=1, operation="recover", current=deepcopy(self.view), history=[])
        reply["current"]["matches"][0]["battle_id"] = str(uuid4())
        with self.assertRaises(ProtocolError):
            validate_championship_reply(reply, self.players[0], request)

    def test_native_menu_recovery_is_bound_to_original_attempt_and_fits_six_rows(self):
        self.pending_cut()
        async def scenario():
            companion = SimpleNamespace(config=SimpleNamespace(player_id=self.players[0]), connected=True,
                world_id=self.store.metadata.world_id, server_epoch=1, session_epoch=self.leases[self.players[0]],
                _players=[dict(player_id=p,display_name=n) for p,n in self.roster.items()])
            menu = ChampionshipMenu(companion)
            menu._binding = menu._session(); menu._supported = True
            menu._current = deepcopy(self.view); menu._page = ("round",0)
            title, status, actions = menu.render()
            self.assertLessEqual(len(actions),6)
            action = next(a for a in actions if a[1]=="champ_recover")
            request = []
            async def rpc(operation, **fields):
                request.append((operation,fields))
                menu._current = self.call(operation, **fields)["current"]
                return True
            menu._rpc = rpc
            self.assertFalse(await menu.choose(action[1], action[2]))
            self.assertEqual(request[0][0],"recover")
            self.assertEqual(menu._current["matches"][0]["state"],"canceled")
            self.assertFalse(self.invites)
        asyncio.run(scenario())

    def test_launcher_recovery_consumes_exact_action_before_rpc_and_cannot_cancel_rematch(self):
        self.pending_cut()
        async def scenario():
            companion = SimpleNamespace(config=SimpleNamespace(player_id=self.players[0]), connected=True,
                _bridge=SimpleNamespace(incarnation=123),
                _players=[dict(player_id=p,display_name=n) for p,n in self.roster.items()])
            session = SimpleNamespace(companion=companion, _open=True, _closing=False,
                _game=SimpleNamespace(process=SimpleNamespace(returncode=None)),
                _binding=(1,2), _signature=lambda:(1,2), can_manage_championship=True)
            calls = []
            async def rpc(operation, *, championship):
                calls.append(deepcopy(championship))
                request = dict(championship)
                op = request.pop("operation"); request.pop("version")
                extension = self.call(op, **request)
                return dict(championship=extension, result=[])
            companion.battle_challenge_rpc = rpc
            panel = ChampionshipPanelController(session)
            snapshot = await panel.dispatch()
            action = next(a for a in snapshot["actions"] if a["label"]=="Recover waiting match")
            result = await panel.dispatch(snapshot["snapshot_id"],action["action_id"])
            self.assertEqual(result["notice"],"match_canceled")
            self.assertEqual(calls[-1]["battle_id"],snapshot["current"]["matches"][0]["battle_id"])
            self.call("match")
            with self.assertRaises(ChampionshipPanelError) as error:
                await panel.dispatch(snapshot["snapshot_id"],action["action_id"])
            self.assertEqual(error.exception.code,"stale")
            self.assertEqual(len(calls),2)
            self.assertEqual(self.view["matches"][0]["attempt"],2)
            self.assertEqual(self.view["matches"][0]["state"],"invited")
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
