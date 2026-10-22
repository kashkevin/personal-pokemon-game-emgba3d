"""Battle Tower: Legends' host service end to end (tower_service.py): solo battles from the command to the settled words on
the wallet stream, results repeated, contradicted, refused, expired and forfeited, prizes exactly once across a restart,
milestone Pokemon, the experience caps, the Tower Shop, and Duo battles on the real native battle desk.

The battles themselves are the engine's; their reports arrive here the way the companion forwards world action 7, and a
Duo battle's released outcome the way the desk's on_publish hook records it. Saves are synthetic Flash images (test_flash)
with a party, badge flags, Battle Points and a Tower record; the floor table is the synthetic one of test_tower_rules.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import random
import struct
import tempfile
from types import SimpleNamespace
import unittest

from emerald_multiplayer import coop_code, rewards, tower_data, tower_rewards
from emerald_multiplayer.flash import LAYOUT_ID
from emerald_multiplayer.shared_world import SharedWorld, SharedWorldError
from emerald_multiplayer.tower_service import CONNECTION_SECONDS, ISSUED_SECONDS, STARTED_SECONDS, TowerService
from emerald_multiplayer.wagers import Wagers
import test_flash
from test_flash import _rewrite, make_flash
from test_tower_contract import tower_record
from test_tower_rules import TABLE_HASH, party_mon, synthetic_data, without_generated_module

WORLD = "11111111-1111-4111-8111-111111111111"
A, B = "aaaaaaaa-0000-4000-8000-000000000001", "bbbbbbbb-0000-4000-8000-000000000002"


def tower_save(*, record=None, badges=0, champion=False, party=((258, 30),), hp=50, bp=0, counter=2, wallet_seq=0):
    """A synthetic save: a party (species, level), badges, the Champion flag, Battle Points, the last wallet adjustment it
    applied and a Tower record."""
    data = make_flash(counter=counter)
    bank = counter % 2
    data = _rewrite(data, bank, 1, 0x234, bytes([len(party)]))
    for index, (species, level) in enumerate(party):
        mon = bytearray(party_mon(species, (31, 20, 10, 5, 31, 0), (0, 0, 1, 0, 0, 0), personality=0x1000 + index,
                                  level=level))
        struct.pack_into("<HH", mon, 86, hp, 60)
        data = _rewrite(data, bank, 1, 0x238 + index * 100, bytes(mon))
    flags = bytearray(2)                                         # SaveBlock1 flags bytes 268-269 (0x860-0x86F)
    for flag in [0x867 + n for n in range(badges)] + ([0x864] if champion else []):
        flags[flag // 8 - 268] |= 1 << flag % 8
    data = _rewrite(data, bank, 2, 0x1270 + 268 - 3968, bytes(flags))
    data = _rewrite(data, bank, 0, 0xEB8, struct.pack("<H", bp))
    data = _rewrite(data, bank, 2, 0x1598 - 3968, struct.pack("<H", wallet_seq))   # SaveBlock1 VAR_MP_WALLET_SEQ
    if record is not None:
        data = test_flash.FlashTests._put_block3(data, 1012, record) if bank == 0 else data
    return data


class Store:
    def __init__(self):
        self.saves = {}

    def read_checkpoint(self, player, epoch):
        payload = self.saves.get(player)
        return None if payload is None else SimpleNamespace(payload=payload, save_profile=LAYOUT_ID,
                                                            sha256=hashlib.sha256(payload).hexdigest())


class SoloTests(unittest.TestCase):
    def setUp(self):
        tower_data.install(synthetic_data())
        self.addCleanup(tower_data.reset)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "w.sqlite3"
        self.world = SharedWorld(self.path, WORLD)
        self.addCleanup(lambda: self.world.close())
        self.now, self.mono = 10_000.0, 1_000.0
        self.world.tower._now = lambda: self.now
        self.store = Store()
        self.sessions = {p: SimpleNamespace(player_id=p, display_name=n, closed=False, session_epoch=3, connected=0.0,
                                            presence={"activity": "overworld"}) for p, n in ((A, "Alice"), (B, "Bob"))}
        self.wagers = Wagers(":memory:", WORLD)
        self.addCleanup(self.wagers.close)
        self.broadcasts = 0
        self.server = SimpleNamespace(
            store=self.store, sessions=self.sessions, shared_world=self.world, wagers=self.wagers, battle_desk=None,
            battle_execution=None, _battle_reservations=None, _teammate=lambda p: None,
            _player_name=lambda p: self.sessions[p].display_name, _assert_battle_available=lambda *p: None)
        self.server._broadcast_world = lambda: setattr(self, "broadcasts", self.broadcasts + 1)
        self.service = self.restart()
        self.store.saves[A] = tower_save()
        self.store.saves[B] = tower_save()

    def restart(self):
        return TowerService(self.server, rng=random.Random(9), monotonic=lambda: self.mono)

    # ----------------------------------------------------------------- helpers
    def call(self, op, player=A, **fields):
        return self.service.request(self.sessions[player], dict(type="tower", op=op, **fields))

    def refused(self, op, code, player=A, **fields):
        with self.assertRaises(SharedWorldError) as caught:
            self.call(op, player, **fields)
        self.assertEqual(caught.exception.code, code, caught.exception.message)
        self.assertLessEqual(len(caught.exception.message), 31)                       # a status line
        return caught.exception.message

    def solo(self, floor, player=A):
        command = self.call("solo", player, floor=floor)["command"]
        self.assertEqual((command["floor"], command["table_hash"]), (floor, TABLE_HASH))
        return command["ticket"]

    def report(self, outcome, ticket, floor, player=A, seq=1):
        return self.service.result(self.sessions[player], dict(type="tower_result", ticket=ticket, floor=floor,
                                                               outcome=outcome, seq=seq))

    def words(self, player=A):
        """(kind, payload) of the player's wallet stream in order; money as (0, amount)."""
        return [rewards.decode(w["delta"], tower=True) or (0, w["delta"]) for w in self.wagers.pending_for(player)]

    def apply(self, player=A, *, room=True, revision=None):
        """The player's game applies every wallet word it was sent, in order, and reports each receipt."""
        revision = [self.world.tower.player(player)["revision"] if revision is None else revision]
        for entry in self.wagers.pending_for(player):
            if entry["applied"] is not None:
                continue
            decoded = rewards.decode(entry["delta"], tower=True)
            if decoded is None:
                amount = entry["delta"]
            elif decoded[0] == rewards.KIND_TOWER_STATE:
                revision[0] += 1
                amount = revision[0]
            elif decoded[0] == rewards.KIND_TOWER_MON:
                amount = 1 if room else 0
            elif decoded[0] == rewards.KIND_ITEM:
                amount = decoded[1] & 0xFF if room else 0
            else:
                amount = decoded[1]
            self.wagers.applied(player, entry["seq"], amount)
        self.service.reconcile()

    def progress(self, player=A):
        row = self.world.tower.player(player)
        return row["progress"], row["highest"]

    # -------------------------------------------------------------------- solo
    def test_a_solo_win_from_the_command_to_its_words(self):
        view = self.call("status")
        self.assertEqual((view["player"]["progress"], view["available"], view["table_hash"]), (1, True, TABLE_HASH))
        ticket = self.solo(1)
        self.assertTrue(ticket & 0xFF)
        self.assertEqual(self.call("status")["battle"]["state"], "issued")
        self.assertEqual(self.report("started", ticket, 1)["state"], "started")
        self.assertEqual(self.words(), [])                                            # nothing before the result
        self.assertEqual(self.report("won", ticket, 1)["state"], "won")
        self.assertEqual(self.progress(), (2, 1))
        self.assertEqual(self.words(), [(6, rewards.tower_progress(1, 2, ticket & 0xFF)), (0, 100), (1, 1)])
        for outcome in ("won", "lost", "drew", "started", "refused"):                # a repeat or a contradiction
            self.report(outcome, ticket, 1, seq=2)
        self.assertEqual(len(self.words()), 3)
        self.assertEqual(self.progress(), (2, 1))
        self.assertEqual(self.call("status")["last"]["state"], "won")

    def test_the_designs_losses_fall_back_to_the_last_checkpoint(self):
        for floor, expected in ((18, 11), (48, 41), (73, 71), (79, 76), (7, 1)):
            with self.subTest(floor=floor):
                self.world.tower._db.execute("DELETE FROM tower_players")
                self.store.saves[A] = tower_save(record=tower_record(highest=floor - 1, progress=floor, revision=floor))
                self.call("status")
                ticket = self.solo(floor)
                self.report("lost" if floor % 2 else "drew", ticket, floor)
                self.assertEqual(self.progress(), (expected, floor - 1))
                self.assertEqual(self.words()[-1], (6, rewards.tower_progress(floor - 1, expected, ticket & 0xFF)))
                self.apply()

    def test_replays_and_the_completed_climb(self):
        self.store.saves[A] = tower_save(record=tower_record(highest=100, progress=101, revision=4))
        view = self.call("status")
        self.assertEqual(view["player"]["progress"], 101)
        ticket = self.solo(100)
        self.report("won", ticket, 100)
        self.assertEqual(self.progress(), (101, 100))
        self.assertEqual(self.words()[1:], [(0, 3000), (1, 18)])                     # a later win near the top
        self.assertEqual(self.world.tower.player(A)["completions"], 1)

    def test_every_refusal_says_why(self):
        self.store.saves[A] = tower_save(record=tower_record(highest=11, progress=12, revision=1))
        self.assertIn("12", self.refused("solo", "tower_floor_locked", floor=13))
        self.sessions[A].presence = None
        self.refused("solo", "game_away", floor=12)
        self.sessions[A].presence = {"activity": "overworld"}
        self.store.saves[A] = tower_save(record=tower_record(highest=11, progress=12, revision=1), hp=0)
        self.assertEqual(self.refused("solo", "no_pokemon", floor=12), "Heal a Pokemon first")
        self.store.saves[A] = tower_save(record=tower_record(highest=11, progress=12, revision=1), party=())
        self.refused("solo", "no_pokemon", floor=12)
        del self.store.saves[A]
        self.refused("solo", "no_save", floor=12)
        self.store.saves[A] = tower_save(record=tower_record(highest=11, progress=12, revision=1))
        ticket = self.solo(12)
        self.assertIn("starting", self.refused("solo", "tower_busy", floor=5))       # one Tower battle at a time
        with without_generated_module():
            tower_data.reset()
            self.refused("solo", "tower_unavailable", player=B, floor=1)
            self.assertEqual(self.call("status", B)["unavailable"], "Tower floor data is missing")
            self.assertIsNone(self.call("status", B)["table_hash"])
        tower_data.install(synthetic_data())
        self.report("refused", ticket, 12)
        self.solo(12)                                                                 # a refused command changed nothing

    def test_a_refused_command_is_void_and_changes_nothing(self):
        ticket = self.solo(1)
        self.assertEqual(self.report("refused", ticket, 1)["state"], "void")
        self.assertEqual(self.world.tower.ticket_by_number(ticket)["reason"], "refused")
        self.assertEqual((self.progress(), self.words()), ((1, 0), []))
        self.assertEqual(self.report("won", ticket, 1)["state"], "void")             # it can never pay ...
        self.assertEqual(self.progress(), (1, 0))
        self.assertEqual(self.words(), [(6, rewards.tower_progress(0, 1, ticket & 0xFF))])   # ... but its result is settled

    def test_a_command_never_started_expires(self):
        ticket = self.solo(1)
        self.now += ISSUED_SECONDS - 1
        self.service.reconcile()
        self.assertEqual(self.world.tower.ticket_by_number(ticket)["state"], "issued")
        self.now += 1
        self.service.reconcile()
        self.assertEqual(self.world.tower.ticket_by_number(ticket)["state"], "void")
        self.solo(1)

    def test_a_started_battle_that_never_reports_is_forfeited_when_its_player_asks_again(self):
        self.store.saves[A] = tower_save(record=tower_record(highest=17, progress=18, revision=1))
        ticket = self.solo(18)
        self.report("started", ticket, 18)
        self.sessions[A].connected = self.mono - CONNECTION_SECONDS + 1                # the game has just connected
        self.assertIn("18", self.refused("solo", "tower_result_pending", floor=18))
        self.mono += 1
        self.assertEqual(self.refused("solo", "tower_forfeited", floor=18), "Floor 18: counted as a loss")
        ticket_row = self.world.tower.ticket_by_number(ticket)
        self.assertEqual(ticket_row["state"], "forfeit")
        self.assertEqual(self.progress(), (11, 17))
        self.assertEqual(self.words(), [(6, rewards.tower_progress(17, 11, ticket & 0xFF))])
        self.refused("solo", "tower_saving", floor=11)                                # its word is not applied yet
        self.apply()
        self.solo(11)

    def test_a_duo_invitation_is_an_ask_too(self):
        self.store.saves[A] = tower_save(record=tower_record(highest=17, progress=18, revision=1))
        ticket = self.solo(18)
        self.report("started", ticket, 18)
        self.sessions[A].connected = self.mono - CONNECTION_SECONDS
        self.server._teammate = {A: B, B: A}.get
        self.assertEqual(self.refused("duo_invite", "tower_forfeited", floor=1), "Floor 18: counted as a loss")
        self.assertEqual(self.world.tower.ticket_by_number(ticket)["state"], "forfeit")
        self.assertIsNone(self.world.tower.duo_of(A))                                 # nothing else happened

    def test_a_started_battle_is_forfeited_after_a_day(self):
        ticket = self.solo(1)
        self.report("started", ticket, 1)
        self.now += STARTED_SECONDS
        self.service.reconcile()
        self.assertEqual(self.world.tower.ticket_by_number(ticket)["state"], "forfeit")

    def test_a_result_after_its_settlement_is_answered_once_its_word_has_landed(self):
        ticket = self.solo(1)
        self.report("won", ticket, 1)
        self.report("won", ticket, 1, seq=2)                                          # its own word is on its way
        self.assertEqual(len(self.words()), 3)
        self.apply()
        self.report("won", ticket, 1, seq=3)                                          # the game still holds it
        self.report("won", ticket, 1, seq=4)
        self.assertEqual(self.words()[-1], (6, rewards.tower_progress(1, 2, ticket & 0xFF)))
        self.assertEqual(len(self.words()), 4)                                        # once
        self.assertEqual(self.progress(), (2, 1))

    def test_another_worlds_ticket_is_answered_with_this_ledger_and_changes_nothing(self):
        self.store.saves[A] = tower_save(record=tower_record(highest=49, progress=50, pending=2, ticket=0x0102037F,
                                                             floor=50, revision=8))
        self.assertEqual(self.report("won", 0x0102037F, 50)["state"], "unknown")      # the first action: an import
        self.assertEqual(self.progress(), (50, 49))
        self.assertEqual(self.words(), [(6, rewards.tower_progress(49, 50, 0x7F))])
        self.report("won", 0x0102037F, 50, seq=2)
        self.assertEqual(len(self.words()), 1)
        self.report("lost", 0x0405067F, 20, seq=3)                                    # any other unknown ticket too
        self.assertEqual(self.words()[-1], (6, rewards.tower_progress(49, 50, 0x7F)))
        self.assertEqual(self.world.tower.player(A)["battles"], 0)

    def test_with_no_readable_save_and_no_row_the_report_waits(self):
        del self.store.saves[A]
        self.assertEqual(self.report("won", 0x0102037F, 50)["state"], "unknown")
        self.assertEqual(self.words(), [])
        self.assertIsNone(self.world.tower.player(A))

    def test_another_players_ticket_is_never_theirs_to_settle(self):
        ticket = self.solo(1, player=B)
        self.report("won", ticket, 1, player=A)
        self.assertEqual(self.world.tower.ticket_by_number(ticket)["state"], "issued")
        self.assertEqual(self.words(B), [])
        self.assertEqual(self.words(A), [(6, rewards.tower_progress(0, 1, ticket & 0xFF))])

    def test_a_contradicting_floor_changes_nothing(self):
        ticket = self.solo(1)
        self.report("won", ticket, 2)
        self.assertEqual(self.world.tower.ticket_by_number(ticket)["state"], "issued")
        self.assertEqual(self.progress(), (1, 0))

    # ----------------------------------------------------------------- prizes
    def test_a_prize_floor_pays_once_in_order_even_across_a_restart(self):
        self.store.saves[A] = tower_save(record=tower_record(highest=9, progress=10, revision=2))
        self.call("status")
        ticket = self.solo(10)
        row = self.world.tower.ticket_by_number(ticket)
        self.world.tower.settle(row["ticket_id"], "won")                              # settled; the host died before paying
        first = self.world.tower.planned_words()[0]
        self.wagers.grant_reward(A, first["kind"], first["payload"], first["ref"], tower=True)   # ... after one word
        self.world.close()
        self.world = SharedWorld(self.path, WORLD)
        self.world.tower._now = lambda: self.now
        self.server.shared_world = self.world
        self.service = self.restart()
        for _ in range(3):
            self.service.reconcile()
            self.call("status")
        self.assertEqual(self.words(), [(6, rewards.tower_progress(10, 11, ticket & 0xFF)), (0, 10_000),
                                        (2, rewards.item_payload(tower_rewards.ITEM_RARE_CANDY, 10)), (1, 6),
                                        (6, rewards.tower_claims(1))])
        self.apply()
        replay = self.solo(10)
        self.report("won", replay, 10)
        self.assertEqual(self.words()[5:], [(6, rewards.tower_progress(10, 11, replay & 0xFF)), (0, 300), (1, 2)])

    def test_a_milestone_pokemon_waits_for_room_and_is_sent_again(self):
        self.store.saves[A] = tower_save(record=tower_record(highest=24, progress=25, revision=2), badges=8)
        ticket = self.solo(25)
        self.report("won", ticket, 25)
        milestone = self.world.tower.milestone(A, 0)
        self.assertEqual((milestone["level"], milestone["state"]), (25, "sent"))     # cap 60: the floor's level
        self.assertIn(milestone["species"], {1})                                      # legal at 25: only Bulbasaur here
        self.assertEqual(self.words()[-1], (7, rewards.tower_mon(0, 1, 25)))
        self.apply(room=False)
        self.assertEqual(self.world.tower.milestone(A, 0)["state"], "owed")
        view = self.call("status")
        self.assertEqual(view["milestones"][0]["state"], "owed")
        self.call("milestone_send", milestone=0)
        self.assertEqual(self.words()[-1], (7, rewards.tower_mon(0, 1, 25)))
        self.refused("milestone_send", "nothing_owed", milestone=0)
        self.apply()
        self.assertEqual(self.world.tower.milestone(A, 0)["state"], "delivered")
        claims = self.world.tower.player(A)["claims"]
        self.assertEqual(self.words()[-1], (6, rewards.tower_claims(claims)))
        self.assertTrue(claims & tower_rewards.delivered_bit(0))
        self.assertEqual(len([w for w in self.words() if w[0] == 7]), 2)

    def test_the_experience_caps_and_the_milestone_level_at_the_claim(self):
        for badges, champion, cap in [(n, False, c) for n, c in enumerate((15, 20, 25, 30, 40, 45, 50, 55, 60))] + \
                [(3, True, 100)]:
            with self.subTest(badges=badges, champion=champion):
                self.store.saves[B] = tower_save(badges=badges, champion=champion)
                save = self.call("status", B)["save"]
                self.assertEqual((save["badges"], save["champion"], save["cap"]), (badges, champion, cap))
        self.store.saves[A] = tower_save(record=tower_record(highest=24, progress=25, revision=2), badges=0)
        self.report("won", self.solo(25), 25)
        self.assertEqual(self.world.tower.milestone(A, 0)["level"], 15)               # 0 badges: capped at 15
        self.store.saves[B] = tower_save(record=tower_record(highest=99, progress=100, revision=2), champion=True)
        self.report("won", self.solo(100, player=B), 100, player=B)
        legendary = self.world.tower.milestone(B, 3)
        self.assertEqual(legendary["level"], 70)                                      # a legendary at most 70
        self.assertIn(legendary["species"], {380, 381, 150})

    def test_a_milestone_with_no_legal_species_waits_until_one_is(self):
        self.store.saves[A] = tower_save(record=tower_record(highest=99, progress=100, revision=2), badges=1)  # cap 20
        self.report("won", self.solo(100), 100)
        self.assertEqual(self.world.tower.milestone(A, 3)["state"], "waiting")       # no legendary is legal at 20
        self.store.saves[A] = tower_save(record=tower_record(highest=100, progress=101, revision=2), badges=4)  # cap 40
        self.service.reconcile()
        milestone = self.world.tower.milestone(A, 3)
        self.assertEqual((milestone["state"], milestone["level"]), ("sent", 40))
        self.assertIn(milestone["species"], {380, 381})

    # ------------------------------------------------------------------- shop
    def buy(self, slot, bp=500):
        self.store.saves[A] = tower_save(bp=bp)
        return self.call("shop_buy", slot=slot)

    def test_the_shop_takes_the_points_first_and_refunds_when_nothing_can_be_given(self):
        entry = tower_rewards.SHOP[1]                                                 # a Gold Bottle Cap, 192 BP
        self.buy(1)
        purchase = self.world.tower.open_purchase(A)
        self.assertEqual(self.words(), [(3, 192)])
        self.service.reconcile()
        self.assertEqual(len(self.words()), 1)                                        # no item before the receipt
        self.wagers.applied(A, 1, 192)
        self.service.reconcile()
        self.assertEqual(self.words()[-1], (2, rewards.item_payload(entry.item, 1)))
        self.wagers.applied(A, 2, 0)                                                   # the bag and the PC were full
        self.service.reconcile()
        self.service.reconcile()
        self.assertEqual(self.world.tower.purchase(purchase["purchase_id"])["state"], "refunded")
        self.assertEqual(self.words()[-1], (1, 192))
        self.assertEqual(len(self.words()), 3)
        self.store.saves[A] = tower_save(bp=10)
        self.assertEqual(self.refused("shop_buy", "not_enough_bp", slot=1), "192 BP needed, you have 10")

    def test_a_save_with_fewer_points_gets_them_back_and_one_purchase_at_a_time(self):
        self.buy(0)
        self.refused("shop_buy", "purchase_open", slot=4)
        self.wagers.applied(A, 1, 20)                                                  # only 20 of 48 were there
        self.service.reconcile()
        self.assertEqual(self.words(), [(3, 48), (1, 20)])
        self.buy(4)                                                                   # not stuck
        self.refused("shop_buy", "no_such_item", slot=len(tower_rewards.SHOP))

    def test_an_order_whose_debit_was_never_queued_does_not_hold_the_shop(self):
        # The host stopped between the order (the Tower's database) and its debit (the wallet's): review of 2026-10-21
        # found the order then waited for a receipt that could never come, and the shop refused every later order.
        self.world.tower.start_purchase("lost-order", A, tower_rewards.SHOP[0].item, 1, tower_rewards.SHOP[0].price)
        self.assertIsNotNone(self.world.tower.open_purchase(A))
        self.service.reconcile()
        self.assertEqual(self.world.tower.purchase("lost-order")["state"], "void")
        self.assertEqual(self.words(), [])                                             # nothing taken, nothing given
        self.buy(4)                                                                   # the next order goes through
        self.assertEqual(self.words(), [(3, tower_rewards.SHOP[4].price)])

    def test_a_debit_the_wallet_refuses_leaves_the_shop_open(self):
        self.store.saves[A] = tower_save(bp=500)
        real = self.wagers.grant_reward

        def refuse(*args, **kwargs):
            raise RuntimeError("the wallet refused")
        self.wagers.grant_reward = refuse
        with self.assertRaises(RuntimeError):
            self.service._shop_buy(self.sessions[A], 0)
        self.wagers.grant_reward = real
        self.assertIsNone(self.world.tower.open_purchase(A))
        self.buy(4)                                                                   # not stuck

    def test_battle_points_paid_since_the_last_save_count_in_the_shop(self):
        # windows-package run 121 and Linux tower-solo-7: eleven floors paid 19 BP, the game saved nothing between
        # floors, and the host read the save's 0 BP: the Tower said 0BP and the shop refused an HP Up the game could pay.
        price = tower_rewards.SHOP[0].price
        self.store.saves[A] = tower_save(bp=price - 1)
        self.report("won", self.solo(1), 1)
        self.assertEqual(self.words()[-1], (1, 1))                                    # floor 1 pays 1 BP (seq 3)
        self.apply()
        self.sessions[A].presence["wallet_seq"] = 3                                   # the game applied seq 3 ...
        self.assertEqual(self.call("status")["save"]["bp"], price)                    # ... and holds the saved 47 + 1
        self.sessions[A].presence["wallet_seq"] = 0                                   # back on its save (a reload)
        self.assertEqual(self.refused("shop_buy", "not_enough_bp", slot=0), f"{price} BP needed, you have {price - 1}")
        self.sessions[A].presence["wallet_seq"] = 3
        self.call("shop_buy", slot=0)
        self.assertEqual(self.words()[-1], (3, price))                                # the debit (seq 4)
        self.wagers.applied(A, 4, price)
        self.sessions[A].presence["wallet_seq"] = 4
        self.assertEqual(self.call("status")["save"]["bp"], 0)                        # the debit counts as well
        self.store.saves[A] = tower_save(bp=0, wallet_seq=4)                          # saved: nothing counted twice
        self.assertEqual(self.call("status")["save"]["bp"], 0)
        self.store.saves[A] = tower_save(bp=price, wallet_seq=3)                      # saved before the debit
        self.assertEqual(self.call("status")["save"]["bp"], 0)

    # ----------------------------------------------------------------- the view
    def test_the_view_carries_the_records_and_the_partys_training(self):
        self.store.saves[A] = tower_save(record=tower_record(highest=11, progress=12, revision=1), party=((258, 30), (25, 9)))
        self.report("won", self.solo(12), 12)
        view = self.call("status")
        self.assertEqual(view["player"]["checkpoint"], 10)
        self.assertEqual(view["records"][0], {"name": "Alice", "best_solo": 12, "best_duo": 0, "completions": 0, "wins": 1,
                                              "me": True})
        self.assertEqual([(m["name"], m["level"], m["ivs"], m["trained"]) for m in view["party"]],
                         [("Mudkip", 30, [31, 20, 10, 5, 31, 0], [False, False, True, False, False, False]),
                          ("Pikachu", 9, [31, 20, 10, 5, 31, 0], [False, False, True, False, False, False])])
        self.assertEqual(view["last"]["reward"]["bp"], 2)


class DuoTests(unittest.TestCase):
    """Two players of a host-formed team against the floor's pair, on the real native battle desk and saved parties."""

    def setUp(self):
        import test_battle_desk as fixtures
        tower_data.install(synthetic_data())
        self.addCleanup(tower_data.reset)
        self.fixture = fixtures.BattleDeskTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        f = self.fixture
        self.players = [p.player_id for p in f.players]
        f.desk.cancel(self.players[0], f.leases[self.players[0]], f.battle_id, f.generation)   # the fixture's challenge
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.world = SharedWorld(Path(self.temp.name) / "w.sqlite3", WORLD)
        self.addCleanup(lambda: self.world.close())
        self.sessions = {p: SimpleNamespace(player_id=p, display_name=f"Trainer {i}", closed=False, connected=0.0,
                                            session_epoch=f.leases[p], presence={"activity": "overworld"})
                         for i, p in enumerate(self.players)}
        self.teams = {self.players[0]: self.players[1], self.players[1]: self.players[0]}
        self.wagers = Wagers(":memory:", WORLD)
        self.addCleanup(self.wagers.close)
        self.server = SimpleNamespace(
            store=f.store, sessions=self.sessions, battle_desk=f.desk, _battle_reservations=None, battle_execution=None,
            shared_world=self.world, wagers=self.wagers, _teammate=lambda p: self.teams.get(p),
            _player_name=lambda p: self.sessions[p].display_name, _assert_battle_available=lambda *p: None,
            _broadcast_world=lambda: None)
        self.service = TowerService(self.server, rng=random.Random(2), monotonic=lambda: 1_000.0)
        self.a, self.b = self.players[:2]
        # Alice climbs at floor 12; Bob has climbed to 50 (their saves' records, imported at their first Tower action).
        for player, (progress, highest) in ((self.a, (12, 11)), (self.b, (50, 49))):
            self.world.tower.sync(player, "x", SimpleNamespace(progress=progress, highest=highest, claims=0, revision=5),
                                  outstanding=0)

    def call(self, player, op, **fields):
        return self.service.request(self.sessions[player], dict(type="tower", op=op, **fields))

    def form(self, floor=12):
        self.call(self.a, "duo_invite", floor=floor)
        self.call(self.b, "duo_accept")
        self.call(self.a, "duo_ready")
        return self.call(self.b, "duo_ready")["duo"]

    def finish(self, battle_id, outcome):
        self.world.frontier.record_result(battle_id, outcome, self.players[:2])          # the desk's on_publish hook
        self.fixture.desk._active.pop(battle_id, None)
        self.fixture.desk._history.pop(battle_id, None)

    def test_the_duo_battle_moves_one_player_and_is_a_replay_for_the_other(self):
        view = self.call(self.a, "duo_invite", floor=12)
        self.assertEqual(view["duo"]["state"], "invited")
        self.assertEqual([m["progression"] for m in view["duo"]["members"]], [True, False])
        self.assertEqual(self.call(self.b, "status")["duo"]["proposer"], self.a)
        self.call(self.b, "duo_accept")
        self.assertEqual(self.call(self.a, "duo_ready")["duo"]["state"], "forming")
        duo = self.call(self.b, "duo_ready")["duo"]
        self.assertEqual(duo["state"], "battle")
        native = self.fixture.desk._active[duo["battle_id"]]
        self.assertEqual((native.mode, native.gym, native.sender), (4, coop_code.encode_tower(12), self.b))
        self.assertEqual(coop_code.decode_tower(native.gym), coop_code.TowerFloor(12, True))
        with self.assertRaises(SharedWorldError):
            self.call(self.a, "solo", floor=5)                                            # one Tower battle at a time
        self.finish(duo["battle_id"], 1)
        self.service.reconcile()
        a, b = self.world.tower.player(self.a), self.world.tower.player(self.b)
        self.assertEqual(((a["progress"], a["highest"]), (b["progress"], b["highest"])), ((13, 12), (50, 49)))
        self.assertEqual(rewards.decode(self.wagers.pending_for(self.a)[0]["delta"], tower=True),
                         (6, rewards.tower_progress(12, 13, 0)))                          # a Duo settles no solo result
        self.assertEqual(rewards.decode(self.wagers.pending_for(self.b)[0]["delta"], tower=True),
                         (6, rewards.tower_progress(49, 50, 0)))
        view = self.call(self.a, "status")["duo"]
        self.assertEqual((view["state"], view["floor"]), ("forming", 13))                 # on to the next floor
        self.service.reconcile()
        self.assertEqual(len(self.wagers.pending_for(self.a)), 3)                         # paid once

    def test_a_battle_that_never_started_is_void_for_both(self):
        duo = self.form()
        self.fixture.desk._active.pop(duo["battle_id"])                                  # the host lost the challenge
        self.service.reconcile()
        self.assertEqual([t["state"] for t in self.world.tower.tickets_of_battle(duo["battle_id"])], ["void", "void"])
        view = self.call(self.a, "status")["duo"]
        self.assertEqual((view["state"], view["floor"]), ("forming", 12))
        self.assertEqual(self.wagers.pending_for(self.a) + self.wagers.pending_for(self.b), [])
        self.finish(duo["battle_id"], 1)                                                  # a late result pays nothing
        self.service.reconcile()
        self.assertEqual(self.world.tower.player(self.a)["progress"], 12)

    def test_a_loss_and_the_floor_choice(self):
        self.call(self.a, "duo_invite", floor=12)
        self.call(self.b, "duo_accept")
        with self.assertRaises(SharedWorldError) as caught:
            self.call(self.b, "duo_floor", floor=13)                                       # beyond Alice's floors
        self.assertEqual(caught.exception.code, "tower_floor_locked")
        self.call(self.b, "duo_floor", floor=5)                                            # a replay for both
        self.call(self.a, "duo_ready")
        duo = self.call(self.b, "duo_ready")["duo"]
        self.assertEqual(duo["floor"], 5)
        self.finish(duo["battle_id"], 2)
        self.service.reconcile()
        self.assertEqual(self.world.tower.player(self.a)["progress"], 12)                 # a replay never moves
        self.assertEqual(self.world.tower.player(self.a)["losses"], 1)

    def test_the_team_choice_is_at_most_three_and_resets_readiness(self):
        self.call(self.a, "duo_invite", floor=12)
        self.call(self.b, "duo_accept")
        self.call(self.a, "duo_ready")
        view = self.call(self.a, "bring", mask=0b10)
        self.assertEqual([m["ready"] for m in view["duo"]["members"]], [False, False])
        self.assertEqual(view["team"]["limit"], 3)
        self.call(self.a, "duo_ready")
        duo = self.call(self.b, "duo_ready")["duo"]
        self.assertEqual([r.bring for r in self.fixture.desk._active[duo["battle_id"]].roster], [0, 2])
        with self.assertRaises(SharedWorldError) as caught:
            self.call(self.a, "bring", mask=0b1)
        self.assertEqual(caught.exception.code, "tower_busy")

    def test_declining_leaving_and_a_dissolved_team(self):
        with self.assertRaises(SharedWorldError) as caught:
            self.call(self.players[2], "duo_invite", floor=1)
        self.assertEqual(caught.exception.code, "no_teammate")
        self.call(self.a, "duo_invite", floor=12)
        self.assertEqual(self.call(self.b, "duo_decline")["duo"]["reason"], "declined")
        self.call(self.a, "duo_invite", floor=12)
        self.call(self.b, "duo_accept")
        self.teams.clear()                                                                 # the team was dissolved
        self.assertEqual(self.call(self.a, "status")["duo"]["reason"], "team_changed")
        with self.assertRaises(SharedWorldError):
            self.call(self.a, "duo_ready")


if __name__ == "__main__":
    unittest.main()
