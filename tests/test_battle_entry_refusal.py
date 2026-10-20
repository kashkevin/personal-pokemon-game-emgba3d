"""Enter battle refusals and challenges that end unstarted (the owner's report of 2026-10-20: after Enter battle both
games stayed on "Waiting for server..." for good)."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from emerald_multiplayer.battle_admission_session import BattleAdmissionRefused
from emerald_multiplayer.battle_desk import BattleError
from emerald_multiplayer.launcher_session import LauncherSession
from emerald_multiplayer.server import WorldServer


class CancelEnteredChallengeTests(unittest.TestCase):
    """A trainer who never entered may cancel a challenge another trainer already entered: the entered game holds its
    entry, so the battle becomes recovery_required (that game cancels its entry itself) instead of the cancel being
    refused while the entered game stays frozen."""

    def server(self, claimed=("host",), state="accepted", bind_intent=()):
        battle = SimpleNamespace(state=state, bind_intent=set(bind_intent), bound=set())
        recovered = []
        def recover(b, reason):
            recovered.append(reason)
            b.state = "recovery_required"
        desk = SimpleNamespace(_get=lambda *args: battle, _recover=recover, _view=lambda b: {"state": b.state})
        execution = SimpleNamespace(resume_enabled=True, admission=SimpleNamespace(claimed=lambda battle_id: claimed))
        return SimpleNamespace(battle_execution=execution, battle_desk=desk), recovered

    def cancel(self, server, actor, code="battle_native_abort_required"):
        return WorldServer._cancel_entered_challenge(server, actor, "b1", "g1", BattleError(code, "refused"))

    def test_an_unentered_trainer_turns_an_entered_challenge_into_recovery(self):
        server, recovered = self.server()
        self.assertEqual(self.cancel(server, ("friend", 7)), {"state": "recovery_required"})
        self.assertEqual(recovered, ["participant_canceled"])

    def test_entered_trainers_bound_battles_and_other_refusals_still_refuse(self):
        for kwargs, actor, code in (({}, ("host", 6), "battle_native_abort_required"),        # entered itself
                                    (dict(bind_intent={"host"}), ("friend", 7), "battle_native_abort_required"),
                                    (dict(state="prepared"), ("friend", 7), "battle_native_abort_required"),
                                    ({}, ("friend", 7), "battle_started")):
            server, recovered = self.server(**kwargs)
            with self.subTest(kwargs=kwargs, actor=actor, code=code), self.assertRaises(BattleError):
                self.cancel(server, actor, code)
            self.assertEqual(recovered, [])


class EnterBlockerTests(unittest.TestCase):
    """What PLAYERS asks before it offers Enter battle, and what the Enter itself checks before anything is written."""

    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        session = object.__new__(LauncherSession)
        binding = ("world", 1, 6, "profile", "player", "build", "rules")
        session._companion = SimpleNamespace(connected=True, config=SimpleNamespace(player_id="player"),
                                             _live_export_pending_path=None, _live_trade_pending_path=None)
        session._open, session._closing = True, False
        session._game = SimpleNamespace(process=SimpleNamespace(returncode=None))
        session._save_failed = session._idle_save_disconnect = False
        session._interaction = session._save_task = None
        session._binding = binding
        session._signature = lambda: binding
        session._revision = 3
        session._profile_directory = self.directory
        self.session = session
        self.challenge = {"checkpoints": [{"player_id": "player", "revision": 3}, {"player_id": "friend", "revision": 9}]}

    def tearDown(self):
        for path in self.directory.iterdir():
            path.unlink()
        self.directory.rmdir()

    def test_each_reason_that_would_refuse_an_enter(self):
        blocker = self.session._native_menu_battle_blocker
        self.assertIsNone(blocker(self.challenge))
        self.session._save_failed = True
        self.assertEqual(blocker(self.challenge), "save_recovery_required")
        self.session._idle_save_disconnect = True       # an idle disconnect never blocked an Enter
        self.assertIsNone(blocker(self.challenge))
        self.session._save_failed = self.session._idle_save_disconnect = False
        self.session._revision = 4                      # a save after the challenge pinned revision 3
        self.assertEqual(blocker(self.challenge), "save_not_ready")
        self.session._revision = 3
        (self.directory / "pending-trade.json").write_text("{}")   # an interrupted trade's record
        self.assertEqual(blocker(self.challenge), "character_recovery_pending")
        (self.directory / "pending-trade.json").unlink()
        self.session._companion.connected = False
        self.assertEqual(blocker(self.challenge), "session_changed")
        self.assertIsNone(blocker(self.challenge, entering=True))  # the Enter's own checks handle a host loss

    def test_a_refused_enter_is_not_a_save_failure(self):
        failed = []
        self.session._fail_save = lambda **_: failed.append(True)
        self.session._save_failed, self.session._idle_save_disconnect = True, False
        with self.assertRaises(BattleAdmissionRefused) as raised:
            self.session._native_menu_capture_battle(self.challenge, SimpleNamespace(_battle_preparing=True))
        self.assertEqual(raised.exception.code, "save_recovery_required")
        self.assertEqual(failed, [])
        self.assertEqual(list(self.directory.iterdir()), [])       # nothing durable names the Enter


if __name__ == "__main__":
    unittest.main()
