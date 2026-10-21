"""Battle Tower: Legends: every byte between the engine and the app (docs/battle-tower-legends.md section 8).

The reward words (8.4), world action 7 (8.3), the Players menu's page, screens and styles (8.2), the Duo battle code (8.5),
the save's Tower record (8.6) and the capability (8.1: manifest marker, bridge.txt opt-in, companion configuration). The
engine side is checked against the same document by its own self-test; these are the app's codecs and their refusals.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import secrets
import struct
from types import SimpleNamespace
import tempfile
import unittest
from uuid import uuid4
import zlib

from emerald_multiplayer import coop_code, rewards
from emerald_multiplayer.bridge_config import configure_native, tower_enabled
from emerald_multiplayer.bridge_protocol import BridgeOutbox
from emerald_multiplayer.flash import (FlashError, SAVE_BLOCK_3_FULL_SIZE, TOWER_RECORD_OFFSET, TOWER_RECORD_SIZE,
                                       TowerRecord, inspect_flash, parse_tower_record)
from emerald_multiplayer.menu_mailbox import (FLAG_HYPER_TRAINING, FLAG_TOWER_SOLO, OPEN_PAGES, TOWER_MAGIC, MenuRequest,
                                              TowerCommand, pack_screen, unpack_screen)
from emerald_multiplayer.menu_session import MenuSession
from emerald_multiplayer.player_menu import MenuRow, MenuScreen
from emerald_multiplayer.protocol import ProtocolError
from emerald_multiplayer.shared_world_protocol import validate_wallet, validate_world_request
from emerald_multiplayer.wagers import WagerError, Wagers
from emerald_multiplayer.world_mailbox import (ACTION_TOWER, ACTION_KINDS, TOWER_RESULTS, WorldAction, WorldInbound,
                                               WorldMailboxError, unpack_local)
import test_flash
from test_flash import make_flash

WORLD = "11111111-1111-4111-8111-111111111111"
TOKEN = "ab" * 32


def tower_record(highest=11, progress=12, pending=0, ticket=0, floor=0, claims=0, revision=3, *, tamper=None) -> bytes:
    """A sealed MPTowerRecord (8.6): 60 bytes, then the CRC-32 of those 60 bytes."""
    body = bytearray(struct.pack("<IBBBBIBBHHH40s", 0x314C5754, 1, highest, progress, pending, ticket, floor, 0, claims,
                                 revision, 0, bytes(40)))
    if tamper is not None:
        tamper(body)
    return bytes(body) + struct.pack("<I", zlib.crc32(bytes(body)))


def with_record(record: bytes, data: bytes | None = None) -> bytes:
    return test_flash.FlashTests._put_block3(make_flash() if data is None else data, TOWER_RECORD_OFFSET, record)


class RewardWordTests(unittest.TestCase):
    def test_progress_and_claims_words_have_the_engines_bit_layout(self):
        payload = rewards.tower_progress(17, 18, 0x2A)
        self.assertEqual(payload, (17 << 15) | (18 << 8) | 0x2A)                       # op 0 in bits 22-23
        word = rewards.encode(rewards.KIND_TOWER_STATE, payload, tower=True)
        self.assertEqual(word, 0x46000000 | payload)
        self.assertEqual(rewards.decode(word, tower=True), (6, payload))
        self.assertEqual(rewards.decode_tower_state(payload), ("progress", 17, 18, 0x2A))
        claims = rewards.tower_claims(0b1001_0000_0000_0101)
        self.assertEqual(claims, (1 << 22) | 0x9005)
        self.assertEqual(rewards.decode_tower_state(claims), ("claims", 0x9005))
        for highest, progress, low in ((0, 1, 0), (100, 101, 0xFF), (100, 41, 1), (10, 11, 0)):
            payload = rewards.tower_progress(highest, progress, low)
            self.assertEqual(rewards.decode_tower_state(payload), ("progress", highest, progress, low))
            self.assertTrue(rewards.valid_wallet_delta(rewards.encode(6, payload, tower=True), tower=True))
        self.assertLess(rewards.encode(6, rewards.tower_progress(100, 101, 0xFF), tower=True), 2 ** 31)

    def test_milestone_pokemon_word(self):
        payload = rewards.tower_mon(3, 2047, 70)
        self.assertEqual(payload, (3 << 22) | (2047 << 11) | (70 << 4))
        self.assertEqual(rewards.decode_tower_mon(payload), (3, 2047, 70))
        word = rewards.encode(rewards.KIND_TOWER_MON, payload, tower=True)
        self.assertEqual(word, 0x47000000 | payload)
        self.assertEqual(rewards.decode(word, tower=True), (7, payload))
        self.assertEqual(rewards.decode_tower_mon(rewards.tower_mon(0, 1, 1)), (0, 1, 1))

    def test_every_malformed_tower_word_is_refused(self):
        for args in ((101, 12, 0), (-1, 1, 0), (5, 0, 0), (5, 102, 0), (5, 6, 256), (5, 6, -1), (True, 6, 0), (5, 6.0, 0)):
            with self.subTest(progress=args), self.assertRaises(rewards.RewardError):
                rewards.tower_progress(*args)
        for claims in (-1, 0x10000, True):
            with self.subTest(claims=claims), self.assertRaises(rewards.RewardError):
                rewards.tower_claims(claims)
        for args in ((4, 1, 1), (-1, 1, 1), (0, 0, 1), (0, 2048, 1), (0, 1, 0), (0, 1, 101), (0, True, 5)):
            with self.subTest(mon=args), self.assertRaises(rewards.RewardError):
                rewards.tower_mon(*args)
        bad_states = (
            (101 << 15) | (12 << 8),                  # H above 100
            (5 << 15) | (0 << 8),                     # P zero
            (5 << 15) | (102 << 8),                   # P above 101
            (1 << 22) | (1 << 16),                    # CLAIMS with a bit 16-21 set
            (1 << 22) | (1 << 21),
            (2 << 22) | 5, (3 << 22) | 5,             # unknown ops
            1 << 24, -1,
        )
        for payload in bad_states:
            with self.subTest(state=hex(payload)), self.assertRaises(rewards.RewardError):
                rewards.encode(rewards.KIND_TOWER_STATE, payload, tower=True)
        for payload in (rewards.tower_mon(0, 25, 10) | 1, rewards.tower_mon(0, 25, 10) | 8,   # bits 0-3 not zero
                        (0 << 22) | (0 << 11) | (10 << 4),                                     # species 0
                        (0 << 22) | (25 << 11) | (0 << 4), (0 << 22) | (25 << 11) | (101 << 4)):  # level 0, 101
            with self.subTest(mon=hex(payload)), self.assertRaises(rewards.RewardError):
                rewards.encode(rewards.KIND_TOWER_MON, payload, tower=True)

    def test_tower_words_exist_only_for_a_game_with_the_tower(self):
        state = rewards.tower_progress(1, 2, 3)
        word = 0x46000000 | state
        for call in (lambda: rewards.encode(6, state), lambda: rewards.encode(7, rewards.tower_mon(0, 1, 1)),
                     lambda: rewards.encode(6, state, tower=1)):
            with self.assertRaises(rewards.RewardError):
                call()
        self.assertIsNone(rewards.decode(word))
        self.assertFalse(rewards.valid_wallet_delta(word))
        self.assertTrue(rewards.valid_wallet_delta(word, tower=True))
        for kind in (8, 9, 15):                                       # still unknown with the Tower
            with self.assertRaises(rewards.RewardError):
                rewards.encode(kind, 1, tower=True)

    def test_kinds_one_to_five_are_unchanged(self):
        for kind, payload, word in ((1, 12, 0x4100000C), (3, 16, 0x43000010), (2, (102 << 8) | 2, 0x42006602),
                                    (4, 7, 0x44000007), (5, 7, 0x45000007)):
            for tower in (False, True):
                self.assertEqual(rewards.encode(kind, payload, tower=tower), word)
                self.assertEqual(rewards.decode(word, tower=tower), (kind, payload))

    def test_the_wire_the_wallet_and_the_mailbox_carry_tower_words_only_with_the_capability(self):
        word = rewards.encode(6, rewards.tower_progress(0, 1, 9), tower=True)
        self.assertEqual(validate_wallet({"seq": 2, "delta": word}, tower=True), {"seq": 2, "delta": word})
        with self.assertRaises(ProtocolError):
            validate_wallet({"seq": 2, "delta": word})
        self.assertIn(struct.pack("<Ii", 2, word), WorldInbound(wallet_seq=2, wallet_delta=word, tower=True).pack())
        with self.assertRaises(WorldMailboxError):
            WorldInbound(wallet_seq=2, wallet_delta=word)
        with self.assertRaises(WorldMailboxError):
            WorldInbound(tower=1)
        self.assertEqual(WorldInbound(tower=True).pack(), WorldInbound().pack())       # the flag itself is never sent
        wagers = Wagers(":memory:", WORLD)
        self.addCleanup(wagers.close)
        player = str(uuid4())
        with self.assertRaises(WagerError):
            wagers.grant_reward(player, 6, rewards.tower_progress(0, 1, 9), "tower:x")
        self.assertEqual(wagers.pending_for(player), [])
        self.assertEqual(wagers.grant_reward(player, 6, rewards.tower_progress(0, 1, 9), "tower:x", tower=True), 1)
        self.assertIsNone(wagers.grant_reward(player, 6, rewards.tower_progress(0, 1, 9), "tower:x", tower=True))


class WorldActionTests(unittest.TestCase):
    def test_kind_seven_is_a_tower_result(self):
        self.assertEqual((ACTION_TOWER, ACTION_KINDS[7]), (7, "tower"))
        self.assertEqual(TOWER_RESULTS, {1: "started", 2: "won", 3: "lost", 4: "refused", 5: "drew"})
        action = WorldAction(9, ACTION_TOWER, 2, 100, 0x1234AB, 0)
        raw = action.pack()
        self.assertEqual(raw, struct.pack("<IBBHII", 9, 7, 2, 100, 0x1234AB, 0))
        state = bytes(16)
        self.assertEqual(unpack_local(state + raw)[1], action)
        for result in TOWER_RESULTS:
            self.assertEqual(WorldAction.unpack(replace(action, result=result).pack()).result, result)

    def test_malformed_tower_results_are_refused(self):
        good = WorldAction(9, ACTION_TOWER, 2, 12, 0x105, 0)
        for changes in (dict(result=0), dict(result=6), dict(species=0), dict(species=101), dict(event_id=0),
                        dict(event_id=0x100), dict(amount=1)):
            with self.subTest(changes=changes), self.assertRaises(WorldMailboxError):
                replace(good, **changes)
        raw = bytearray(good.pack())
        struct.pack_into("<I", raw, 12, 3)                                             # an amount on a Tower result
        with self.assertRaises(WorldMailboxError):
            WorldAction.unpack(bytes(raw))

    def test_the_result_request_names_a_ticket_floor_and_outcome(self):
        base = dict(type="tower_result", session_epoch=3, request_id=str(uuid4()), ticket=0x105, floor=12,
                    outcome="won", seq=9)
        self.assertEqual(validate_world_request(dict(base), 3), base)
        for changes in (dict(ticket=0), dict(ticket=0x100), dict(ticket=1 << 32), dict(floor=0), dict(floor=101),
                        dict(outcome="cancelled"), dict(outcome=["won"]), dict(seq=0), dict(ticket=True)):
            with self.subTest(changes=changes), self.assertRaises(ProtocolError):
                validate_world_request({**base, **changes}, 3)
        for extra in ({"amount": 0}, {}):
            request = {**base, **extra}
            if not extra:
                del request["seq"]
            with self.assertRaises(ProtocolError):
                validate_world_request(request, 3)

    def test_the_menu_requests_name_only_their_own_field(self):
        base = dict(type="tower", session_epoch=3, request_id=str(uuid4()))
        for op, fields in (("status", {}), ("solo", {"floor": 12}), ("duo_invite", {"floor": 1}), ("duo_floor", {"floor": 100}),
                           ("duo_accept", {}), ("duo_decline", {}), ("duo_leave", {}), ("duo_ready", {}),
                           ("duo_ready", {"incarnation": 3, "runtime_id": str(uuid4())}), ("duo_unready", {}),
                           ("bring", {"mask": 63}), ("shop_buy", {"slot": 0}), ("milestone_send", {"milestone": 3})):
            validate_world_request({**base, "op": op, **fields}, 3)
        for op, fields in (("cheat", {}), ("solo", {}), ("solo", {"floor": 0}), ("solo", {"floor": 101}),
                           ("status", {"floor": 1}), ("bring", {"mask": 64}), ("shop_buy", {"slot": 32}),
                           ("milestone_send", {"milestone": 4}), ("solo", {"floor": 5, "slot": 1}),
                           ("duo_accept", {"incarnation": 3, "runtime_id": str(uuid4())}),
                           ("duo_ready", {"incarnation": 0, "runtime_id": str(uuid4())}),
                           ("solo", {"floor": True}), (5, {})):
            with self.subTest(op=op, fields=fields), self.assertRaises(ProtocolError):
                validate_world_request({**base, "op": op, **fields}, 3)


class MenuContractTests(unittest.TestCase):
    def screen(self, **changes):
        return replace(MenuScreen(12, "Battle Tower: Legends", "Floor 12 best 11", (MenuRow(1, "Solo: floor 12"),), 7),
                       **changes)

    def test_open_page_two_is_the_tower_and_needs_the_capability(self):
        self.assertEqual(OPEN_PAGES[2], "tower")
        request = MenuRequest(4, 0, 2, 1)
        with self.assertRaises(ValueError):
            request.pack()
        with self.assertRaises(ValueError):
            MenuRequest.unpack(request.pack(allow_tower=True))
        self.assertEqual(MenuRequest.unpack(request.pack(allow_tower=True), allow_tower=True), request)
        self.assertEqual(MenuRequest.unpack(MenuRequest(4, 0, 1, 1).pack()), MenuRequest(4, 0, 1, 1))  # RESET unchanged
        for bad in (MenuRequest(4, 0, 3, 1), MenuRequest(4, 3, 2, 1)):
            with self.subTest(request=bad), self.assertRaises(ValueError):
                bad.pack(allow_tower=True)

    def test_the_solo_command_screen_has_the_exact_bytes(self):
        command = TowerCommand(0x0102037F, 0xDEADBEEF, 12)
        screen = MenuScreen(13, "Battle Tower", "Floor 12: get ready!", (), 7)
        raw = pack_screen(5, screen, tower_command=command, allow_tower=True)
        self.assertEqual(len(raw), 240)
        self.assertEqual(raw[8], FLAG_TOWER_SOLO)
        self.assertEqual((raw[9], raw[236:240]), (0, bytes(4)))                         # count 0, admission 0, no style
        self.assertEqual(raw[68:100], struct.pack("<IIIBB", TOWER_MAGIC, 0x0102037F, 0xDEADBEEF, 12, 1) + bytes(18))
        self.assertEqual(raw[100:236], bytes(136))
        self.assertEqual(unpack_screen(raw, allow_tower=True), (5, screen, 4, command))
        self.assertEqual(TowerCommand.unpack(command.pack()), command)

    def test_the_hyper_training_screen(self):
        screen = MenuScreen(13, "Hyper Training", "Opening Hyper Training", (), 7)
        raw = pack_screen(6, screen, hyper_training=True, allow_tower=True)
        self.assertEqual((raw[8], raw[9]), (FLAG_HYPER_TRAINING, 0))
        self.assertEqual(raw[68:240], bytes(172))
        self.assertEqual(unpack_screen(raw, allow_tower=True), (6, screen, 5, None))

    def test_style_bytes(self):
        for style, arg in ((1, 0), (2, 1), (2, 91), (3, 100), (4, 0), (5, 0), (6, 0), (7, 0), (8, 0)):
            screen = self.screen(style=style, style_arg=arg)
            raw = pack_screen(3, screen, allow_tower=True)
            self.assertEqual(raw[236:240], bytes((0, 0, style, arg)))
            self.assertEqual(unpack_screen(raw, allow_tower=True), (3, screen, 0, None))
            self.assertEqual(unpack_screen(pack_screen(3, screen, close=True, allow_tower=True), allow_tower=True)[2], 1)
        plain = self.screen()
        self.assertEqual(unpack_screen(pack_screen(3, plain, allow_tower=True), allow_tower=True), (3, plain, 0, None))
        self.assertEqual(unpack_screen(pack_screen(3, plain)), (3, plain, False))      # a page without a style is unchanged

    def test_every_tower_screen_is_refused_without_the_capability_or_out_of_shape(self):
        command = TowerCommand(0x105, 7, 12)
        with self.assertRaises(ValueError):
            pack_screen(5, self.screen(rows=()), tower_command=command)
        with self.assertRaises(ValueError):
            pack_screen(5, self.screen(rows=()), hyper_training=True)
        with self.assertRaises(ValueError):
            pack_screen(5, self.screen(style=1))
        refused = (
            dict(screen=self.screen(), tower_command=command),                         # rows beside a command
            dict(screen=self.screen(rows=(), style=1), tower_command=command),         # a style on a command
            dict(screen=self.screen(), hyper_training=True),
            dict(screen=self.screen(rows=()), tower_command=command, hyper_training=True),
            dict(screen=self.screen(rows=()), tower_command=command, close=True),
            dict(screen=self.screen(rows=()), tower_command=b"x" * 32),
            dict(screen=self.screen(style=9)), dict(screen=self.screen(style=2, style_arg=101)),
            dict(screen=self.screen(style=0, style_arg=4)), dict(screen=self.screen(style=True)),
            dict(screen=self.screen(rows=()), hyper_training=1),
        )
        for case in refused:
            with self.subTest(case=case), self.assertRaises(ValueError):
                pack_screen(5, allow_tower=True, **case)
        for bad in (dict(ticket=0), dict(ticket=0x100), dict(ticket=1 << 32), dict(floor=0), dict(floor=101),
                    dict(mode=2), dict(mode=0), dict(table_hash=-1), dict(table_hash=1 << 32), dict(floor=True)):
            with self.subTest(command=bad), self.assertRaises(ValueError):
                replace(command, **bad).pack()
        raw = pack_screen(5, self.screen(rows=()), tower_command=command, allow_tower=True)
        with self.assertRaises(ValueError):
            unpack_screen(raw)                                                         # a reader without the Tower
        for offset, value in ((68, 0x55), (90, 1), (99, 1), (100, 1), (235, 1), (9, 1), (236, 1), (238, 9),
                              (239, 1)):
            changed = bytearray(raw)
            changed[offset] = value
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                unpack_screen(bytes(changed), allow_tower=True)
        styled = pack_screen(5, self.screen(style=3, style_arg=12), allow_tower=True)
        with self.assertRaises(ValueError):
            unpack_screen(styled)
        for offset, value in ((238, 9), (239, 101)):
            changed = bytearray(styled)
            changed[offset] = value
            with self.subTest(style_offset=offset), self.assertRaises(ValueError):
                unpack_screen(bytes(changed), allow_tower=True)
        hyper = bytearray(pack_screen(5, self.screen(rows=()), hyper_training=True, allow_tower=True))
        hyper[80] = 1
        with self.assertRaises(ValueError):
            unpack_screen(bytes(hyper), allow_tower=True)


class FakeMenu:
    def __init__(self):
        self.screen = MenuScreen(1, "Battle Tower: Legends", "Floor 12", (MenuRow(1, "Solo: floor 12"),), 7, 0, 1, 0)
        self.pages, self.handoff, self.tower_reply = [], None, None

    async def refresh(self):
        return self.screen

    async def open_page(self, page):
        self.pages.append(page)
        return self.screen

    async def choose(self, revision, action):
        self.tower_reply = ("command", TowerCommand(0x2A01, 99, 12))
        return replace(self.screen, revision=2, title="Battle Tower", status="Floor 12: get ready!")


class MenuSessionTowerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bridge = SimpleNamespace(outbox=BridgeOutbox(), writer=SimpleNamespace(close=lambda: None))
        self.config = SimpleNamespace(menu_open_page_abi_version=1, tower_abi_version=1)
        self.companion = SimpleNamespace(_bridge=self.bridge, config=self.config)
        self.session = MenuSession(self.companion, self.bridge)
        self.session.menu = FakeMenu()

    async def asyncTearDown(self):
        await self.session.close()

    async def frame(self):
        frame = await asyncio.wait_for(self.bridge.outbox.get(), 1)
        self.assertEqual(frame[4:5], b"M")
        return frame[5:]

    async def test_start_player_tower_opens_the_tower_page_with_its_style(self):
        self.session.feed(MenuRequest(1, 0, 2, 1).pack(allow_tower=True))
        await self.session._task
        sequence, screen, flags, command = unpack_screen(await self.frame(), allow_tower=True)
        self.assertEqual((sequence, screen.style, flags, command), (1, 1, 0, None))
        self.assertEqual(self.session.menu.pages, ["tower"])

    async def test_a_game_without_the_tower_cannot_open_it_and_never_sees_a_style(self):
        self.config.tower_abi_version = 0
        with self.assertRaises(ValueError):
            self.session.feed(MenuRequest(1, 0, 2, 1).pack(allow_tower=True))
        self.assertEqual(self.session.menu.pages, [])
        self.session.feed(MenuRequest(1, 0, 0, 1).pack())
        await self.session._task
        raw = await self.frame()
        self.assertEqual(raw[236:240], bytes(4))                                       # the classic page only
        self.assertEqual(unpack_screen(raw)[1].title, "Battle Tower: Legends")

    async def test_the_hosts_command_answers_the_choice_once_and_the_window_is_left_alone(self):
        self.session.feed(MenuRequest(1, 0, 2, 1).pack(allow_tower=True))
        await self.session._task
        await self.frame()
        self.session.feed(MenuRequest(2, 1, 1, 2).pack())
        await self.session._task
        sequence, screen, flags, command = unpack_screen(await self.frame(), allow_tower=True)
        self.assertEqual((sequence, flags, command, screen.rows, screen.style), (2, 4, TowerCommand(0x2A01, 99, 12), (), 0))
        self.assertIsNone(self.session.menu.tower_reply)                               # consumed: never sent twice
        self.assertTrue(self.session._window_closing)                                  # no status refresh into it
        self.session.feed(MenuRequest(3, 0, 0, 3).pack())                              # the game's window closed
        self.assertFalse(self.session.open or self.session._window_closing)

    async def test_without_the_capability_the_command_is_never_sent(self):
        self.session.feed(MenuRequest(1, 0, 0, 1).pack())
        await self.session._task
        await self.frame()
        self.config.tower_abi_version = 0
        self.session.feed(MenuRequest(2, 1, 1, 2).pack())
        await self.session._task
        sequence, screen, close = unpack_screen(await self.frame())
        self.assertEqual((sequence, close, screen.status), (2, False, "Floor 12: get ready!"))


class DuoCodeTests(unittest.TestCase):
    def test_the_tower_family_layout(self):
        for floor in (1, 12, 99, 100):
            for exp in (True, False):
                code = coop_code.encode_tower(floor, exp)
                self.assertEqual(code, 0x80000000 | (0x40000000 if exp else 0) | (floor << 20) | 0x80 | floor)
                self.assertEqual(coop_code.decode_tower(code), coop_code.TowerFloor(floor, exp))
                self.assertIsNone(coop_code.decode(code))                              # not a ladder battle
                self.assertTrue(coop_code.valid_code(code))
        self.assertEqual(coop_code.encode_tower(12), 0xC0C0008C)
        self.assertIsNone(coop_code.decode_tower(coop_code.encode(261, 262, 50)))      # ladder codes are not Tower codes
        self.assertTrue(coop_code.valid_code(coop_code.encode(261, 262, 50)) and coop_code.valid_code(3))

    def test_every_malformed_tower_code_is_refused(self):
        good = coop_code.encode_tower(12)
        for bad in (good & ~0x80000000, good | 0x400, good | 0x80000 >> 1, good ^ 0x80 | 0x100, good | 0x200,
                    (good & ~0x7F) | 13, (good & ~(0x3FF << 20)) | (13 << 20), coop_code.encode_tower(1) & ~0x7F & ~(0x3FF << 20),
                    0x80000000 | (101 << 20) | 0x80 | 101, True, 1 << 32, -1, "12"):
            with self.subTest(code=bad):
                self.assertIsNone(coop_code.decode_tower(bad))
        for args in ((0,), (101,), (True,), (5, 1)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                coop_code.encode_tower(*args)

    def test_the_challenges_page_names_the_floor(self):
        from emerald_multiplayer.player_menu import PlayerMenu
        title = PlayerMenu._coop_title(coop_code.encode_tower(100))
        self.assertEqual(title, "Battle Tower floor 100")
        self.assertLessEqual(len(title), 23)


class SaveRecordTests(unittest.TestCase):
    def test_older_saves_have_no_record_and_the_block_grows_by_64(self):
        self.assertEqual((TOWER_RECORD_OFFSET, TOWER_RECORD_SIZE, SAVE_BLOCK_3_FULL_SIZE), (1012, 64, 1076))
        self.assertIsNone(inspect_flash(make_flash()).tower)
        self.assertIsNone(parse_tower_record(bytes(64)))

    def test_a_sealed_record_is_read_for_the_host(self):
        record = tower_record(highest=48, progress=41, pending=3, ticket=0x0A0B0C0D, floor=48, claims=0x1013, revision=77)
        value = inspect_flash(with_record(record)).tower
        self.assertEqual(value, TowerRecord(41, 48, 0x1013, "lost", 0x0A0B0C0D, 48, 77))
        for code, name in ((0, None), (2, "won"), (3, "lost"), (5, "drew")):
            self.assertEqual(parse_tower_record(tower_record(pending=code)).pending, name)
        self.assertEqual(parse_tower_record(tower_record(highest=100, progress=101)).progress, 101)
        self.assertEqual(parse_tower_record(tower_record(highest=0, progress=1, revision=0xFFFF)).revision, 0xFFFF)
        # both profiles carry it, the egg queue beside it, and the older bank may still have none
        eggs = test_flash.FlashTests._put_block3(make_flash(), 600, test_flash.FlashTests._egg_queue(2))
        self.assertEqual(inspect_flash(with_record(record, eggs)).tower.revision, 77)

    def test_anything_else_is_refused_like_the_egg_queue(self):
        cases = {
            "magic": tower_record(tamper=lambda b: b.__setitem__(0, 0x55)),
            "version": tower_record(tamper=lambda b: b.__setitem__(4, 2)),
            "highest 101": tower_record(highest=101, progress=101),
            "progress 0": tower_record(progress=0),
            "progress 102": tower_record(highest=100, progress=102),
            "pending 1": tower_record(pending=1), "pending 4": tower_record(pending=4), "pending 6": tower_record(pending=6),
            "reserved0": tower_record(tamper=lambda b: b.__setitem__(13, 1)),
            "reserved1": tower_record(tamper=lambda b: b.__setitem__(18, 1)),
            "reserved": tower_record(tamper=lambda b: b.__setitem__(59, 1)),
            "reserved first": tower_record(tamper=lambda b: b.__setitem__(20, 1)),
            "crc": tower_record()[:60] + b"\0\0\0\0",
            "a stray byte": bytes(63) + b"\1",
        }
        for name, record in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(FlashError):
                    parse_tower_record(record)
                with self.assertRaises(FlashError):
                    inspect_flash(with_record(record))
        with self.assertRaises(FlashError):
            parse_tower_record(bytes(63))
        with self.assertRaisesRegex(FlashError, "padding"):                            # byte 1076 is past the record
            inspect_flash(test_flash.FlashTests._put_block3(with_record(tower_record()), 1076, b"\1"))


class CapabilityTests(unittest.TestCase):
    def manifest(self, **changes):
        return {"menu_abi_version": 2, "menu_open_page_abi_version": 1, "world_abi_version": 1, "tower_abi_version": 1,
                **changes}

    def test_the_launcher_opts_in_exactly_like_the_open_page(self):
        manifest = self.manifest()
        self.assertTrue(tower_enabled(manifest))
        self.assertEqual(configure_native(manifest, TOKEN, 9).splitlines()[2:], ["menu_open_page=1", "tower=1"])
        for changes in (dict(tower_abi_version=2), dict(tower_abi_version=True), dict(tower_abi_version=None),
                        dict(menu_open_page_abi_version=0), dict(menu_abi_version=1), dict(world_abi_version=None),
                        dict(world_abi_version=True)):
            with self.subTest(changes=changes):
                self.assertFalse(tower_enabled(self.manifest(**changes)))
                self.assertNotIn("tower=1", configure_native(self.manifest(**changes), TOKEN, 9))

    def test_the_companion_reads_its_games_capability(self):
        from emerald_multiplayer.companion import CompanionConfig
        from test_world_companion import make_world_files
        for extra, expected in (({}, 0), ({"tower_abi_version": 1}, 0), (self.manifest(), 1),
                                (self.manifest(tower_abi_version=2), 0)):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as temp:
                rom, manifest = make_tower_world_files(temp) if expected or "menu_abi_version" in extra else \
                    make_world_files(temp)
                data = json.loads(manifest.read_text())
                data.update({key: value for key, value in extra.items() if key.startswith("tower")})
                manifest.write_text(json.dumps(data))
                config = CompanionConfig(rom, manifest, str(uuid4()), "Alice", secrets.token_bytes(32), ipc_port=0)
                self.assertEqual(config.tower_abi_version, expected)


def make_tower_world_files(directory):
    """The shared-world fixture game with the Players menu ABI 2 and its named pages (a Tower game's prerequisites)."""
    from test_world_companion import make_world_files
    rom, manifest = make_world_files(directory)
    data = bytearray(rom.read_bytes())
    struct.pack_into("<I", data, 0x104, 2)                                             # the menu ABI 2 marker
    rom.write_bytes(bytes(data))
    import hashlib
    values = json.loads(manifest.read_text())
    values.update(rom_sha256=hashlib.sha256(bytes(data)).hexdigest(), rom_crc32=f"{zlib.crc32(bytes(data)):08x}",
                  menu_abi_version=2, menu_abi_address=0x08000104, menu_mailbox_address=0x02031000,
                  menu_mailbox_size=512, menu_open_page_abi_version=1, tower_abi_version=1)
    manifest.write_text(json.dumps(values))
    return rom, manifest


class ManifestTests(unittest.TestCase):
    """The marker comes from the native executable, beside the Players menu ABI 2, its named pages and the shared world."""

    def setUp(self):
        from test_battle_manifest import CoopAndWorldManifestTests
        self.fixture = CoopAndWorldManifestTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        with self.fixture.rom.open("r+b") as rom:
            rom.seek(212)
            rom.write(b"\x02\0\0\0")                                                   # the Players menu ABI 2 marker
        self.menu = "080000d4 00000004 R gMultiplayerMenuAbiVersion\n02024000 00000200 B gMultiplayerMenuMailbox\n"
        self.open_page = "00bd2790 00000004 R gMultiplayerMenuOpenPageAbiVersion\n"
        self.tower = "00bd2794 00000004 R gMultiplayerTowerAbiVersion\n"

    def generate(self, elf, native):
        f = self.fixture
        return f.generate_native(f.base + f.battle + elf, native)

    def test_the_marker_needs_the_menu_its_pages_and_the_world(self):
        f = self.fixture
        generated = self.generate(f.world + self.menu, self.open_page + self.tower)
        self.assertEqual((generated["tower_abi_version"], generated["menu_abi_version"]), (1, 2))
        self.assertTrue(tower_enabled(generated))
        self.assertIn("tower=1", configure_native(generated, TOKEN, 9))
        mingw = self.generate(f.world + self.menu, self.open_page + "00bd2794 R _gMultiplayerTowerAbiVersion\n")
        self.assertEqual(mingw["tower_abi_version"], 1)
        self.assertNotIn("tower_abi_version", self.generate(f.world + self.menu, self.open_page))
        for elf, native in ((f.world + self.menu, self.tower),                          # no named pages
                            (self.menu, self.open_page + self.tower),                   # no shared world
                            (f.world + self.menu, self.open_page + self.tower + self.tower),
                            (f.world + self.menu, self.open_page + "00bd2794 00000008 R gMultiplayerTowerAbiVersion\n")):
            with self.subTest(elf=elf, native=native), self.assertRaises(ValueError):
                self.generate(elf, native)


class CompanionForwardingTests(unittest.IsolatedAsyncioTestCase):
    """A Tower result posted by the game reaches the host as tower_result and is acknowledged once the host answered."""

    async def asyncSetUp(self):
        from emerald_multiplayer.companion import BASELINE_RULESET, Companion, CompanionConfig, verify_rom_manifest
        from emerald_multiplayer.server import ServerConfig, WorldServer
        from test_companion import wait_until
        from test_world_companion import Bridge
        self.wait_until = wait_until
        self.temp = tempfile.TemporaryDirectory()
        rom, manifest = make_tower_world_files(self.temp.name)
        build = verify_rom_manifest(rom, manifest)[0]
        self.server = WorldServer(ServerConfig(build, BASELINE_RULESET, heartbeat_interval=0.05, idle_timeout=2,
                                               monitor_interval=0.005))
        await self.server.start(port=0)
        config = CompanionConfig(rom, manifest, str(uuid4()), "Alice", secrets.token_bytes(32),
                                 server_port=self.server.address[1], ipc_port=0, pose_interval=0.005,
                                 snapshot_interval=0.01, reconnect_delay=0.02)
        self.assertEqual(config.tower_abi_version, 1)
        self.companion = Companion(config)
        await self.companion.start()
        await wait_until(lambda: self.companion.connected)
        self.bridge = await Bridge.connect(self.companion)

    async def asyncTearDown(self):
        await self.bridge.close()
        await self.companion.close()
        await self.server.close()
        self.temp.cleanup()

    async def test_the_result_is_forwarded_and_acknowledged_after_the_answer(self):
        from test_world_companion import ack, local_record
        from emerald_multiplayer.world_mailbox import WorldState
        seen = []

        def answer(session, request):
            seen.append(request)
            return {"seq": request["seq"], "state": "won"}
        self.server._tower_enabled = True                                                # a host whose Tower answers
        self.server._tower_service = SimpleNamespace(result=answer, reconcile=lambda: None)
        await self.bridge.send(local_record(WorldState(), WorldAction(4, ACTION_TOWER, 2, 12, 0x2A05, 0)))
        await self.bridge.world(lambda d: ack(d) == 4)
        self.assertEqual([(r["type"], r["ticket"], r["floor"], r["outcome"], r["seq"]) for r in seen],
                         [("tower_result", 0x2A05, 12, "won", 4)])

    async def test_a_host_without_the_tower_still_answers_and_the_game_is_acknowledged(self):
        from test_world_companion import ack, local_record
        from emerald_multiplayer.world_mailbox import WorldState
        await self.bridge.send(local_record(WorldState(), WorldAction(5, ACTION_TOWER, 1, 3, 0x0101, 0)))
        await self.bridge.world(lambda d: ack(d) == 5)


if __name__ == "__main__":
    unittest.main()


class ServerWiringTests(unittest.IsolatedAsyncioTestCase):
    """The host serves the Tower only when its installed game has it (WorldServer.enable_tower, called by the launcher
    from the manifest), and reconciles it on its own tick."""

    async def asyncSetUp(self):
        import test_world_companion as wc
        await wc.WorldCompanionTests.asyncSetUp(self)

    async def asyncTearDown(self):
        import test_world_companion as wc
        await wc.WorldCompanionTests.asyncTearDown(self)

    async def test_a_host_without_the_tower_refuses_every_tower_request(self):
        with self.assertRaises(ProtocolError) as caught:
            await self.companions[0].tower_rpc()
        self.assertEqual(caught.exception.code, "tower_disabled")
        self.assertIsNone(self.server._tower_service)                                 # never even built
        with self.assertRaises(ValueError):
            self.server.enable_tower()                                                # only before the host starts

    async def test_an_enabled_host_serves_the_view_and_reconciles_on_its_tick(self):
        from test_companion import wait_until
        self.server._tower_enabled = True                                             # what enable_tower sets
        view = await self.companions[0].tower_rpc()
        self.assertEqual((view["player"]["progress"], view["problem"]["code"]), (1, "no_save"))
        calls = []
        self.server._tower_service = SimpleNamespace(reconcile=lambda: calls.append(1))
        self.server._last_tower_tick = 0.0
        await wait_until(lambda: calls, timeout=2)

    async def test_a_tower_fault_is_an_answer_not_a_dropped_connection(self):
        self.server._tower_enabled = True

        def broken(session, request):
            raise KeyError("a bug")
        self.server._tower_service = SimpleNamespace(request=broken, result=broken, reconcile=lambda: None)
        with self.assertRaises(ProtocolError) as caught:
            await self.companions[0].tower_rpc()
        self.assertEqual(caught.exception.code, "tower_failed")
        self.assertTrue(self.companions[0].connected)



class LauncherHostingTests(unittest.IsolatedAsyncioTestCase):
    """The launcher's host enables the Tower exactly when its installed game's manifest has it."""

    def setUp(self):
        from test_launcher_session import LauncherSessionTests
        LauncherSessionTests.setUp(self)

    async def asyncTearDown(self):
        from test_launcher_session import LauncherSessionTests
        await LauncherSessionTests.asyncTearDown(self)

    def session(self, **options):
        from test_launcher_session import LauncherSessionTests
        return LauncherSessionTests.session(self, **options)

    async def test_a_game_without_the_tower_hosts_without_it(self):
        session = self.session()
        async with session.open():
            self.assertFalse(session._server._tower_enabled)

    async def test_a_game_with_the_tower_hosts_with_it(self):
        from unittest.mock import patch
        seen = []

        def enabled(manifest):
            seen.append(manifest)
            return True
        with patch("emerald_multiplayer.bridge_config.tower_enabled", enabled):
            session = self.session()
            async with session.open():
                self.assertTrue(session._server._tower_enabled)
        self.assertIs(seen[0], session._manifest)                                     # the installed game's manifest
