"""KNOWN_ISSUES MS-60: a battle entered with a party that is not the canonical save the challenge names is turned away at
Enter (the claim), before anything is held; L ms60-pvp-2 (2026-10-22) showed the old behaviour: both trainers held with
saving stopped, and an abandonment that started the games again from their host saves, the unsaved progress lost."""
import asyncio
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest

from emerald_multiplayer.battle_admission_host import BattleAdmissionHost
from emerald_multiplayer.battle_admission_session import DEFINITE_CLAIM_REFUSALS, live_claim_fields
from emerald_multiplayer.battle_desk import BattleError
from emerald_multiplayer.battle_protocol import ProtocolError, validate_battle_reply, validate_battle_request
from emerald_multiplayer.launcher_session import LauncherSession
from emerald_multiplayer.party_identity import PartyIdentity
from emerald_multiplayer.player_menu import CANCEL_REASONS, REFUSALS, refusal_text
from emerald_multiplayer.save_mailbox import FLASH_SIZE, Opcode, SaveControl, SaveMailboxError, Status
from emerald_multiplayer.server import WorldServer

ROSTER = SimpleNamespace(native_counter=40, trainer_id=0x12345678, party_crc32=0xCAFEF00D)
LIVE = dict(save_counter=40, battle_counter=40, trainer_id=0x12345678, party_count=3, party_crc32=0xCAFEF00D)
UUID = "6c0f3e1e-6b0a-4f68-9f5c-8b3f2e1d0c9a"


class PartyIdentityTests(unittest.TestCase):
    def test_the_game_answers_five_words(self):
        identity = PartyIdentity.unpack(struct.pack("<5I", 41, 40, 0x12345678, 3, 0xCAFEF00D))
        self.assertEqual(identity.as_request(), dict(LIVE, save_counter=41))
        for bad in (b"", bytes(19), bytes(21), struct.pack("<5I", 1, 1, 1, 0, 1), struct.pack("<5I", 1, 1, 1, 7, 1)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                PartyIdentity.unpack(bad)

    def test_it_matches_what_prepare_takes(self):
        self.assertTrue(PartyIdentity(**LIVE).matches(ROSTER))
        # right after a trade's import the game is one save counter higher than the image it imported names
        self.assertTrue(PartyIdentity(**dict(LIVE, save_counter=41)).matches(ROSTER))
        for changed in (dict(save_counter=41, battle_counter=41),       # saved in the game only
                        dict(party_crc32=0xCAFEF00E),                  # a party changed (a wild battle, an item)
                        dict(trainer_id=1)):
            with self.subTest(changed=changed):
                self.assertFalse(PartyIdentity(**dict(LIVE, **changed)).matches(ROSTER))

    def test_a_request_names_exactly_its_fields(self):
        self.assertEqual(PartyIdentity.from_request(LIVE), PartyIdentity(**LIVE))
        for bad in ({}, dict(LIVE, extra=1), {k: v for k, v in LIVE.items() if k != "trainer_id"},
                    dict(LIVE, save_counter=-1), dict(LIVE, party_count=0), dict(LIVE, party_crc32="1"), [LIVE]):
            with self.subTest(bad=bad), self.assertRaises((TypeError, ValueError)):
                PartyIdentity.from_request(bad)


class ProtocolTests(unittest.TestCase):
    def request(self, operation, **fields):
        return dict(type="battle_" + operation, session_epoch=3, request_id=UUID, **fields)

    def claim(self, **fields):
        return self.request("claim", battle_id=UUID, generation=UUID, incarnation=7, runtime_id=UUID, **fields)

    def test_the_capability_query_and_the_claims_live_field(self):
        validate_battle_request(self.request("pending", live_check_version=1), 3)
        validate_battle_request(self.claim(live=LIVE), 3)
        validate_battle_request(self.claim(), 3)                       # an older client, or an older game
        for bad in (self.request("pending", live_check_version=2),
                    self.request("pending", live_check_version=1, abandon_version=1),
                    self.claim(live=dict(LIVE, party_count=9)), self.claim(live="x"),
                    self.request("cancel", battle_id=UUID, generation=UUID, live=LIVE)):
            with self.subTest(bad=bad), self.assertRaises(ProtocolError):
                validate_battle_request(bad, 3)

    def test_only_a_pending_reply_names_the_capability(self):
        reply = dict(type="battle_result", protocol=None, session_epoch=3, request_id=UUID, operation="pending",
                     world_id=UUID, player_id=UUID, result=[], live_check_version=1)
        from emerald_multiplayer.battle_protocol import PROTOCOL_VERSION
        reply["protocol"] = PROTOCOL_VERSION
        validate_battle_reply(reply, UUID, UUID, 3)
        for bad in (dict(reply, live_check_version=2), dict(reply, operation="claim")):
            with self.subTest(bad=bad), self.assertRaises(ProtocolError):
                validate_battle_reply(bad, UUID, UUID, 3)


class HostClaimTests(unittest.TestCase):
    """The host compares a claim's party with the roster entry of the claiming trainer, before recording the claim."""

    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.battle = SimpleNamespace(battle_id="b1", state="accepted", consent={"host", "friend"},
                                      players=("host", "friend"), roster=(ROSTER, ROSTER), resumable=False)
        self.value = dict(canceled=False, view=dict(state="accepted"), claimed=[],
                          identities={"host": dict(incarnation=7, runtime_id=UUID),
                                      "friend": dict(incarnation=8, runtime_id=UUID)})
        host = object.__new__(BattleAdmissionHost)
        host.desk = SimpleNamespace(_get=lambda *args: self.battle, _view=lambda b: dict(state=b.state))
        host._read = lambda battle_id: self.value
        host._path = lambda battle_id: self.directory / "consent.json"
        self.host = host

    def tearDown(self):
        for path in self.directory.iterdir():
            path.unlink()
        self.directory.rmdir()

    def claim(self, actor="friend", **fields):
        identity = self.value["identities"][actor]
        return self.host.claim(actor, 7, dict(battle_id="b1", generation="g1", **identity, **fields))

    def test_a_game_at_its_canonical_save_enters(self):
        self.assertEqual(self.claim(live=LIVE), {"state": "accepted"})
        self.assertEqual(self.value["claimed"], ["friend"])
        self.assertTrue(self.battle.resumable)

    def test_a_changed_game_is_turned_away_before_the_claim_is_recorded(self):
        with self.assertRaises(BattleError) as caught:
            self.claim(live=dict(LIVE, party_crc32=1))
        self.assertEqual(caught.exception.code, "save_needed")
        self.assertEqual(self.value["claimed"], [])
        self.assertFalse(self.battle.resumable)

    def test_a_claim_without_its_party_goes_as_before(self):
        self.claim()
        self.assertEqual(self.value["claimed"], ["friend"])


class HostCancelTests(unittest.TestCase):
    """The battle a stale claim was turned away from ends for everybody, as a cancel does."""

    def server(self, claimed=()):
        battle = SimpleNamespace(state="accepted", bind_intent=set(), bound=set())
        ended = []
        desk = SimpleNamespace(_get=lambda *args: battle,
                               _recover=lambda b, reason: ended.append(("recovery_required", reason)),
                               _abort=lambda b, reason: ended.append(("aborted", reason)))
        admission = SimpleNamespace(claimed=lambda battle_id: claimed,
                                    canceled=lambda battle_id: ended.append(("canceled", battle_id)))
        return SimpleNamespace(battle_desk=desk, battle_execution=SimpleNamespace(admission=admission)), ended

    def test_nobody_entered_yet_the_battle_is_aborted_and_fenced(self):
        server, ended = self.server()
        WorldServer._cancel_stale_claim(server, ("friend", 7), "b1", "g1")
        self.assertEqual(ended, [("aborted", "save_needed"), ("canceled", "b1")])

    def test_a_trainer_who_entered_cancels_its_entry_neutrally(self):
        server, ended = self.server(claimed=("host",))
        WorldServer._cancel_stale_claim(server, ("friend", 7), "b1", "g1")
        self.assertEqual(ended, [("recovery_required", "save_needed")])


class ClientTests(unittest.TestCase):
    def companion(self, *, query=1, reply=None, error=None, identity=PartyIdentity(**LIVE)):
        async def rpc(operation, **fields):
            self.assertEqual((operation, fields), ("pending", dict(live_check_version=1)))
            if error is not None:
                raise error
            return reply if reply is not None else dict(live_check_version=1, result=[])

        async def live():
            return identity
        return SimpleNamespace(config=SimpleNamespace(save_party_query_abi_version=query),
                               battle_challenge_rpc=rpc, live_party_identity=live)

    def fields(self, companion):
        return asyncio.run(live_claim_fields(companion))

    def test_the_claim_names_the_party_when_host_and_game_can(self):
        self.assertEqual(self.fields(self.companion()), {"live": LIVE})

    def test_otherwise_the_claim_goes_as_before(self):
        from emerald_multiplayer.companion import BattleChallengeError
        for companion in (self.companion(query=0), self.companion(reply=dict(result=[])),
                          self.companion(error=BattleChallengeError("invalid_fields", "older host"))):
            with self.subTest(companion=companion):
                self.assertEqual(self.fields(companion), {})

    def test_a_game_that_cannot_say_is_never_claimed_unchecked(self):
        # The host checks, the game has QUERY_PARTY, but its answer did not come (the save mailbox busy): None, and
        # prepare_battle_admission refuses the Enter before any claim (party_unknown).
        self.assertIsNone(self.fields(self.companion(identity=None)))
        self.assertIn("party_unknown", DEFINITE_CLAIM_REFUSALS)
        self.assertEqual(refusal_text("party_unknown"), "Your game is busy: try again")

    def test_a_save_needed_refusal_is_definite_and_explained(self):
        self.assertIn("save_needed", DEFINITE_CLAIM_REFUSALS)
        self.assertEqual(refusal_text("save_needed"), REFUSALS["save_needed"])
        for text in (REFUSALS["save_needed"], CANCEL_REASONS["save_needed"]):
            self.assertLessEqual(len(text), 31)

    def test_the_launcher_saves_after_a_save_needed_refusal(self):
        session = object.__new__(LauncherSession)
        session._battle_menu_preparation = session._interaction = session._battle_retained = None
        session._battle_recovery_intent, session._game = None, None
        session._autosave_wake = asyncio.Event()
        session._companion = SimpleNamespace(_bridge=None, _battle_save_needed=True)
        started = []
        session._start_battle_save = lambda: started.append(True)
        session._native_menu_refused_battle(object())
        self.assertEqual(started, [True])
        self.assertFalse(session._companion._battle_save_needed)
        session._native_menu_refused_battle(object())        # an ordinary refusal saves nothing
        self.assertEqual(started, [True])

    def test_that_save_waits_for_the_players_menu_to_close(self):
        from unittest.mock import patch
        import emerald_multiplayer.launcher_session as module

        class Session(LauncherSession):
            can_save = True

        session = object.__new__(Session)
        session._closing, session._game, session._battle_save_task = False, object(), None
        menu = SimpleNamespace(open=True)
        session._companion = SimpleNamespace(_bridge=SimpleNamespace(menu_session=menu))
        saves = []

        async def save():
            saves.append(menu.open)
            return len(saves) > 1            # the first is refused (the game still busy), the second saves
        session.save = save
        real_sleep = asyncio.sleep

        async def quick(_):
            await real_sleep(0)

        async def run():
            with patch.object(module.asyncio, "sleep", quick):
                session._start_battle_save()
                for _ in range(50):
                    await real_sleep(0)
                self.assertEqual(saves, [])       # never under the open menu
                menu.open = False
                await session._battle_save_task
        asyncio.run(run())
        self.assertEqual(saves, [False, False])


class ManifestTests(unittest.TestCase):
    """The capability comes from the native executable's marker, beside the save mailbox; the companion takes it then."""

    def setUp(self):
        import test_save_manifest as manifests
        self.manifests = manifests
        manifests.SaveManifestTests.setUp(self)
        self.save_symbols = "02021000 00000200 B gMultiplayerSaveMailbox\n"

    def tearDown(self):
        self.temp.cleanup()

    def generate(self, symbols, native=""):
        from unittest.mock import patch
        generator = self.manifests.generator
        with patch.object(generator.subprocess, "check_output", return_value=self.symbols + symbols):
            return generator.generate(self.rom, self.elf, "fixture-nm", "b" * 40, native_symbols=native)

    def test_the_marker_comes_from_the_native_executable_beside_the_save_mailbox(self):
        native = "00bd27a4 00000004 R gMultiplayerSavePartyQueryAbiVersion\n"
        self.assertNotIn("save_party_query_abi_version", self.generate(self.save_symbols))
        self.assertEqual(self.generate(self.save_symbols, native)["save_party_query_abi_version"], 1)
        mingw = "00bd27a4 R _gMultiplayerSavePartyQueryAbiVersion\n"   # the Windows game's nm prints no size
        self.assertEqual(self.generate(self.save_symbols, mingw)["save_party_query_abi_version"], 1)
        for symbols, marker in (("", native), (self.save_symbols, native + native),
                                (self.save_symbols, "00bd27a4 00000008 R gMultiplayerSavePartyQueryAbiVersion\n")):
            with self.subTest(marker=marker), self.assertRaises(ValueError):
                self.generate(symbols, marker)

    def test_the_companion_takes_it_only_with_the_save_mailbox(self):
        import hashlib
        import json
        import uuid
        import zlib
        import test_companion_battle as companion_fixture
        for save, value, expected in ((True, None, 0), (True, 1, 1), (True, 2, 0), (True, True, 0), (False, 1, 0)):
            with self.subTest(save=save, value=value), tempfile.TemporaryDirectory() as directory:
                rom, manifest = companion_fixture.make_files(directory)
                data = json.loads(manifest.read_text())
                raw = bytearray(rom.read_bytes()); raw[192:196] = b"\x01\0\0\0"; rom.write_bytes(raw)
                data.update(rom_sha256=hashlib.sha256(raw).hexdigest(), rom_crc32=f"{zlib.crc32(raw):08x}")
                if save:
                    data.update(save_abi_version=1, save_mailbox_size=512, save_mailbox_address=0x02021000)
                if value is not None:
                    data["save_party_query_abi_version"] = value
                manifest.write_text(json.dumps(data))
                config = companion_fixture.CompanionConfig(rom, manifest, str(uuid.uuid4()), "Alice",
                                                           bytes(32), ipc_port=0)
                self.assertEqual(config.save_party_query_abi_version, expected)


class MailboxTests(unittest.TestCase):
    def control(self, **fields):
        values = dict(incarnation=7, session_epoch=3, request_id=UUID, sequence=1, offset=0, total_size=FLASH_SIZE,
                      revision=0, opcode=Opcode.QUERY_PARTY)
        values.update(fields)
        return SaveControl(**values)

    def test_a_party_query_names_canonical_flash_and_nothing_else(self):
        self.control().validate_command()
        for bad in (dict(offset=128), dict(revision=1), dict(total_size=0), dict(data=b"x")):
            with self.subTest(bad=bad), self.assertRaises(SaveMailboxError):
                self.control(**bad).validate_command()

    def test_its_answer_is_twenty_bytes(self):
        self.control(data=bytes(20)).validate_response()
        self.control(status=Status.BUSY).validate_response()
        with self.assertRaises(SaveMailboxError):
            self.control(data=bytes(48)).validate_response()


if __name__ == "__main__":
    unittest.main()
