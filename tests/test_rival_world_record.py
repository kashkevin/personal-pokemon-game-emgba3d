"""Update 31: the capability-gated rival record in the EMW1 world mailbox (inbound bytes 200..207)."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from emerald_multiplayer.companion import BattleChallengeError, Companion, CompanionConfig
from emerald_multiplayer.world_mailbox import (RIVAL_OFFSET, RIVAL_STATES, RivalRecord, WorldInbound,
                                               WorldMailboxError)
from test_rival_checkpoints import Harness
from test_world_companion import make_world_files
import secrets
from uuid import uuid4


class RivalRecordTests(unittest.TestCase):
    def test_default_inbound_is_unchanged_without_the_capability(self):
        data = WorldInbound().pack()
        self.assertEqual(len(data), 208)
        self.assertEqual(data[RIVAL_OFFSET:], bytes(8))
        with_outbreak = WorldInbound(outbreak=(0, 25)).pack()
        self.assertEqual(with_outbreak[192:200], bytes([1, 0, 25, 0, 0, 0, 0, 0]))
        self.assertEqual(with_outbreak[200:], bytes(8))

    def test_layout(self):
        record = RivalRecord(completed=0b00101, cleared=0b00001, here=3, state=RIVAL_STATES["battling"],
                             present=True, my_match=True)
        data = WorldInbound(rival=record).pack()
        self.assertEqual(data[RIVAL_OFFSET:RIVAL_OFFSET + 8], bytes([7, 5, 1, 3, 3, 0, 0, 0]))
        self.assertEqual(WorldInbound(rival=RivalRecord()).pack()[RIVAL_OFFSET:], bytes([1, 0, 0, 0, 0, 0, 0, 0]))

    def test_bounds(self):
        for bad in (dict(completed=32), dict(cleared=-1), dict(here=6, state=1), dict(here=1), dict(state=1),
                    dict(present=True), dict(here=1, state=5), dict(here=1, state=1, present=1)):
            with self.assertRaises(WorldMailboxError):
                RivalRecord(**bad)
        with self.assertRaises(WorldMailboxError):
            WorldInbound(rival=b"\x01" * 8)

    def test_from_real_coordinator_replies(self):
        h = Harness(self, 4, countdown=0)
        self.addCleanup(h.close)
        actor = h.players[0]
        record = RivalRecord.from_reply(h.call(0, "status"), actor)
        self.assertEqual(record, RivalRecord())
        h.go(0, "route110"); h.go(1, "route110")
        record = RivalRecord.from_reply(h.call(0, "status"), actor)
        self.assertEqual((record.here, record.state, record.present, record.my_match), (3, 1, True, False))
        h.vote(0, "route110"); h.vote(1, "route110")
        record = RivalRecord.from_reply(h.call(0, "status"), actor)
        self.assertEqual((record.state, record.my_match), (RIVAL_STATES["battling"], True))
        h.match(0, "route110")
        h.play(h.invites[-1][0], 1)
        record = RivalRecord.from_reply(h.call(0, "status"), actor)
        self.assertEqual((record.completed, record.cleared, record.state), (0b00100, 0b00100, RIVAL_STATES["completed"]))
        late = RivalRecord.from_reply(h.call(3, "status"), h.players[3])
        self.assertEqual((late.completed, late.cleared, late.here), (0b00100, 0, 0), "the latecomer is elsewhere")


class CompanionCapabilityTests(unittest.TestCase):
    def config(self, **extra):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        rom, manifest = make_world_files(temp.name)
        data = json.loads(manifest.read_text())
        data.update(extra)
        manifest.write_text(json.dumps(data))
        return CompanionConfig(rom, manifest, str(uuid4()), "Alice", secrets.token_bytes(32), ipc_port=0)

    def test_only_rival_abi_version_one_enables_the_record(self):
        self.assertEqual(self.config().rival_abi_version, 0)
        self.assertEqual(self.config(rival_abi_version=1).rival_abi_version, 1)
        self.assertEqual(self.config(rival_abi_version=2).rival_abi_version, 0)

    def test_world_inbound_carries_the_record_only_with_the_capability(self):
        for version, expected in ((0, bytes(8)), (1, bytes([3, 1, 0, 3, 1, 0, 0, 0]))):
            companion = Companion(self.config(**({"rival_abi_version": 1} if version else {})))
            companion.connected = True
            companion._roster_signature = ()
            companion._players = []
            companion._world_rival = RivalRecord(completed=1, here=3, state=1, present=True)
            self.assertEqual(companion.world_inbound().pack()[RIVAL_OFFSET:], expected)


class PollerTests(unittest.IsolatedAsyncioTestCase):
    async def test_poller_stores_records_and_stops_on_a_host_without_support(self):
        h = Harness(self, 2)
        self.addCleanup(h.close)
        calls = []
        companion = SimpleNamespace(config=SimpleNamespace(player_id=h.players[0]), _world_rival=None,
                                    RIVAL_POLL_SECONDS=0)
        async def rpc(operation, *, rival):
            calls.append(rival)
            if len(calls) == 3:
                raise ConnectionError("lost")
            if len(calls) == 5:
                raise BattleChallengeError("rival_disabled", "no")
            return dict(rival=h.call(0, "status"))
        companion.battle_challenge_rpc = rpc
        await asyncio.wait_for(Companion._poll_rival(companion), 2)
        self.assertEqual(len(calls), 5, "stops after the host says it has no rival checkpoints")
        self.assertTrue(all(call == dict(version=1, operation="status") for call in calls), "read-only polling")
        self.assertIsNone(companion._world_rival)


if __name__ == "__main__":
    unittest.main()


class RivalMenuRenderTests(unittest.TestCase):
    """Every rival page state rendered from real coordinator replies: at most six rows, printable text."""

    def render(self, h, index):
        from emerald_multiplayer.rival_menu import RivalMenu
        companion = SimpleNamespace(config=SimpleNamespace(player_id=h.players[index]), connected=True,
                                    world_id="w", server_epoch=1, session_epoch=1, _players=[])
        menu = RivalMenu(companion)
        menu._binding, menu._supported = menu._session(), True
        menu._reply = h.call(index, "status")
        title, status, actions = menu.render()
        self.assertLessEqual(len(actions), 6)
        self.assertTrue(len(title) <= 23 and len(status) <= 31)
        for label, op, args in actions:
            self.assertTrue(len(label) <= 25 and all(32 <= ord(c) <= 126 for c in label))
        return status, [label for label, op, _ in actions if op], [label for label, *_ in actions]

    def test_states(self):
        h = Harness(self, 4, countdown=5)
        self.addCleanup(h.close)
        for p in range(4):
            h.names[h.players[p]] = "Ünïcode name that is far too long"
        status, clickable, _ = self.render(h, 0)
        self.assertEqual(status, "World rival progress 0/5")
        for p in range(4):
            h.go(p, "route110")
        status, clickable, labels = self.render(h, 0)
        self.assertEqual(clickable, ["Start Now", "Wait for Other Players", "Refresh"])
        for p in range(4):
            h.vote(p, "route110")
        status, clickable, _ = self.render(h, 0)
        self.assertEqual(status, "Battle starts in 5s")
        h.tick(5)
        status, clickable, labels = self.render(h, 0)
        self.assertEqual(status, "Your rival battle is ready")
        self.assertTrue(any(label.startswith("Battle: ") for label in clickable), clickable)
        session = h.status(0, "route110")["session"]
        sender = h.players.index(session["matches"][0]["teams"][0][0])
        h.match(sender, "route110")
        battle_id = h.invites[-1][0]
        status, clickable, _ = self.render(h, sender)
        self.assertIn("Open Challenges to accept", clickable)
        h.desk._active[battle_id].state = "recovery_required"
        status, clickable, _ = self.render(h, sender)
        self.assertIn("Recover waiting battle", clickable)
        h.play(battle_id, 1)
        status, clickable, labels = self.render(h, 1)
        self.assertEqual(sum(" W" in label for label in labels), 4, "four standings rows")

    def test_escape_row_for_a_bystander_of_a_held_battle(self):
        h = Harness(self, 4, countdown=0)
        self.addCleanup(h.close)
        h.go(0, "route110"); h.go(1, "route110")
        h.vote(0, "route110"); h.vote(1, "route110")
        h.match(0, "route110")
        h.desk._active[h.invites[-1][0]].state = "recovery_required"
        h.go(2, "route110")
        h.status(2, "route110")
        h.tick(120)
        status, clickable, _ = self.render(h, 2)
        self.assertIn("Continue on my own", clickable)
