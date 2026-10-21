"""Battle Tower: Legends' durable book (tower.py): the import rule, tickets settled exactly once with their wallet words
planned in the contract's order, milestone Pokemon, the Duo session and a restart from the same SQLite file."""
from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from emerald_multiplayer import rewards, tower_rewards
from emerald_multiplayer.shared_world import SharedWorld
from emerald_multiplayer.tower import MONEY, TowerError

WORLD = "11111111-1111-4111-8111-111111111111"


def record(progress=1, highest=0, claims=0, revision=0, pending=None, ticket=0, floor=0):
    """A save's Tower record as flash.TowerRecord reads it."""
    return SimpleNamespace(progress=progress, highest=highest, claims=claims, revision=revision, pending=pending,
                           pending_ticket=ticket, pending_floor=floor)


def chooser(species=6, name="Charizard"):
    picks = []

    def choose(player, milestone, floor):
        picks.append((player, milestone, floor))
        return (species, name, min(floor, 70))
    choose.picks = picks
    return choose


class BookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "w.sqlite3"
        self.world = SharedWorld(self.path, WORLD)
        self.addCleanup(lambda: self.world.close())
        self.book = self.world.tower
        self.now = 1000.0
        self.book._now = lambda: self.now

    def climb(self, player, to):
        """Win floors from the player's P up to ``to`` (exclusive), settling each."""
        while self.book.player(player)["progress"] < to:
            ticket = self.book.issue_solo(player, self.book.player(player)["progress"])
            self.book.settle(ticket["ticket_id"], "won", choose=chooser())

    def words(self, player, ticket_id=None):
        return [(w["ref"].split(":")[-1], w["kind"], w["payload"]) for w in self.book.words_of(player, ticket_id)]

    # ------------------------------------------------------------- the import
    def test_the_first_action_imports_the_saves_record(self):
        row, imported = self.book.sync("pa", "Alice", record(18, 17, 0b11, 9), outstanding=0)
        self.assertTrue(imported)
        self.assertEqual((row["progress"], row["highest"], row["claims"], row["revision"], row["best"]), (18, 17, 3, 9, 17))
        row, imported = self.book.sync("pb", "Bob", None, outstanding=0)              # every older save: no record
        self.assertTrue(imported)
        self.assertEqual((row["progress"], row["highest"], row["claims"], row["revision"]), (1, 0, 0, 0))

    def test_a_newer_save_record_is_imported_and_its_claims_ored(self):
        self.book.sync("pa", "Alice", record(18, 17, 0b001, 9), outstanding=0)
        row, imported = self.book.sync("pa", "Alice", record(41, 48, 0b100, 12), outstanding=0)
        self.assertTrue(imported)
        self.assertEqual((row["progress"], row["highest"], row["claims"], row["revision"], row["best"]), (41, 48, 5, 12, 48))
        # a lower H from elsewhere: taken (the host follows the save), but best keeps what was cleared here
        row, _ = self.book.sync("pa", "Alice", record(5, 4, 0, 13), outstanding=0)
        self.assertEqual((row["progress"], row["highest"], row["claims"], row["best"]), (5, 4, 5, 48))

    def test_a_revision_the_hosts_own_words_explain_is_not_imported(self):
        self.book.sync("pa", "Alice", record(18, 17, 0, 9), outstanding=0)
        for revision, outstanding in ((9, 0), (8, 0), (10, 1), (11, 2)):
            row, imported = self.book.sync("pa", "Alice", record(3, 2, 0, revision), outstanding=outstanding)
            self.assertFalse(imported, (revision, outstanding))
            self.assertEqual((row["progress"], row["highest"]), (18, 17))
        self.assertTrue(self.book.sync("pa", "Alice", record(3, 2, 0, 11), outstanding=1)[1])

    def test_never_while_a_battle_is_open(self):
        self.book.sync("pa", "Alice", record(18, 17, 0, 9), outstanding=0)
        self.book.issue_solo("pa", 18)
        row, imported = self.book.sync("pa", "Alice", record(41, 48, 0, 30), outstanding=0)
        self.assertFalse(imported)
        self.assertEqual(row["progress"], 18)

    def test_a_tower_words_receipt_is_the_revision_last_seen(self):
        self.book.sync("pa", "Alice", None, outstanding=0)
        ticket = self.book.issue_solo("pa", 1)
        self.book.settle(ticket["ticket_id"], "won")
        state = self.book.words_of("pa", ticket["ticket_id"])[0]
        self.book.word_queued("pa", state["ref"])
        self.book.word_receipt("pa", state["ref"], 7)
        self.assertEqual(self.book.player("pa")["revision"], 7)
        self.assertIsNone(self.book.word_receipt("pa", state["ref"], 9))              # once
        self.assertEqual(self.book.player("pa")["revision"], 7)

    # -------------------------------------------------------------- tickets
    def test_a_solo_win_settles_once_with_its_words_in_the_contracts_order(self):
        self.book.sync("pa", "Alice", record(10, 9), outstanding=0)
        ticket = self.book.issue_solo("pa", 10)
        self.assertEqual((ticket["state"], ticket["progression"]), ("issued", True))
        self.assertTrue(ticket["number"] & 0xFF and 0 < ticket["number"] < 1 << 32)
        with self.assertRaises(TowerError):
            self.book.issue_solo("pa", 5)                                             # one Tower battle at a time
        self.assertEqual(self.book.start(ticket["ticket_id"])["state"], "started")
        settled = self.book.settle(ticket["ticket_id"], "won", choose=chooser())
        self.assertEqual(settled["state"], "won")
        self.assertEqual(settled["result"]["after"], [11, 10])
        row = self.book.player("pa")
        self.assertEqual((row["progress"], row["highest"], row["claims"], row["wins"], row["battles"], row["best_solo"]),
                         (11, 10, tower_rewards.claim_bit(10), 1, 1, 10))
        self.assertEqual(self.words("pa", ticket["ticket_id"]), [
            ("state", rewards.KIND_TOWER_STATE, rewards.tower_progress(10, 11, ticket["number"] & 0xFF)),
            ("money", MONEY, 10_000),
            ("item", rewards.KIND_ITEM, rewards.item_payload(tower_rewards.ITEM_RARE_CANDY, 10)),
            ("bp", rewards.KIND_BP, 6),
            ("claims", rewards.KIND_TOWER_STATE, rewards.tower_claims(1)),
        ])
        for outcome in ("won", "lost", "drew"):                                       # a repeat or a contradiction
            self.assertIsNone(self.book.settle(ticket["ticket_id"], outcome))
        self.assertEqual(len(self.book.words_of("pa")), 5)
        self.assertEqual(self.book.player("pa")["wins"], 1)

    def test_a_loss_falls_back_and_pays_nothing_but_still_settles_the_saves_result(self):
        self.book.sync("pa", "Alice", record(18, 17), outstanding=0)
        ticket = self.book.issue_solo("pa", 18)
        self.book.settle(ticket["ticket_id"], "lost")
        row = self.book.player("pa")
        self.assertEqual((row["progress"], row["highest"], row["losses"], row["wins"]), (11, 17, 1, 0))
        self.assertEqual(self.words("pa"), [("state", 6, rewards.tower_progress(17, 11, ticket["number"] & 0xFF))])
        replay = self.book.issue_solo("pa", 5)                                        # 5 <= H: a replay
        self.assertFalse(replay["progression"])
        self.book.settle(replay["ticket_id"], "drew")
        self.assertEqual((self.book.player("pa")["progress"], self.book.player("pa")["highest"]), (11, 17))
        with self.assertRaises(TowerError):
            self.book.issue_solo("pa", 18)                                            # 18 > H and is not P: locked

    def test_a_voided_or_forfeited_ticket(self):
        self.book.sync("pa", "Alice", record(18, 17), outstanding=0)
        ticket = self.book.issue_solo("pa", 18)
        self.assertEqual(self.book.void(ticket["ticket_id"], "refused")["state"], "void")
        self.assertIsNone(self.book.settle(ticket["ticket_id"], "won"))               # a voided battle can never pay
        self.assertEqual(self.book.player("pa")["progress"], 18)
        self.assertEqual(self.book.words_of("pa"), [])
        again = self.book.issue_solo("pa", 18)
        self.book.start(again["ticket_id"])
        forfeited = self.book.settle(again["ticket_id"], "lost", forfeit=True)
        self.assertEqual(forfeited["state"], "forfeit")
        self.assertEqual(self.book.player("pa")["progress"], 11)

    def test_replay_rates_and_a_prize_only_once(self):
        self.book.sync("pa", "Alice", None, outstanding=0)
        self.climb("pa", 12)
        replay = self.book.issue_solo("pa", 10)
        settled = self.book.settle(replay["ticket_id"], "won")
        self.assertEqual(settled["result"]["reward"]["first_clear"], False)
        self.assertEqual([w[0] for w in self.words("pa", replay["ticket_id"])], ["state", "money", "bp"])
        self.assertEqual(self.book.player("pa")["claims"], tower_rewards.claim_bit(10))

    def test_ticket_numbers_are_unique_with_a_nonzero_low_byte(self):
        self.book.sync("pa", "Alice", record(101, 100), outstanding=0)
        numbers = set()
        for _ in range(60):
            ticket = self.book.issue_solo("pa", 50)
            numbers.add(ticket["number"])
            self.book.void(ticket["ticket_id"], "expired")
        self.assertEqual(len(numbers), 60)
        self.assertTrue(all(number & 0xFF for number in numbers))

    # ------------------------------------------------------------ milestones
    def test_a_milestone_is_chosen_before_anything_is_sent_and_delivered_once(self):
        self.book.sync("pa", "Alice", record(25, 24, claims=0b11), outstanding=0)
        ticket = self.book.issue_solo("pa", 25)
        choose = chooser(species=149, name="Dragonite")
        self.book.settle(ticket["ticket_id"], "won", choose=choose)
        self.assertEqual(choose.picks, [("pa", 0, 25)])
        milestone = self.book.milestone("pa", 0)
        self.assertEqual((milestone["species"], milestone["level"], milestone["state"]), (149, 25, "sent"))
        refs = self.words("pa", ticket["ticket_id"])
        self.assertEqual([r[0] for r in refs], ["state", "bp", "claims", "mon"])     # floor 25 pays no money
        self.assertEqual(refs[-1][2], rewards.tower_mon(0, 149, 25))
        mon = self.book.words_of("pa", ticket["ticket_id"])[-1]
        self.book.word_queued("pa", mon["ref"])
        self.book.word_receipt("pa", mon["ref"], 0)                                   # no room
        self.assertEqual(self.book.milestone("pa", 0)["state"], "owed")
        resent = self.book.resend_milestone("pa", 0)
        self.assertEqual((resent["state"], resent["attempts"], resent["species"]), ("sent", 2, 149))
        with self.assertRaises(TowerError):
            self.book.resend_milestone("pa", 0)                                       # not owed while it travels
        second = self.book.words_of("pa")[-1]
        self.assertEqual((second["ref"], second["payload"]), ("tower:mon:0:2", rewards.tower_mon(0, 149, 25)))
        self.book.word_queued("pa", second["ref"])
        self.book.word_receipt("pa", second["ref"], 1)
        self.assertEqual(self.book.milestone("pa", 0)["state"], "delivered")
        claims = self.book.player("pa")["claims"]
        self.assertTrue(claims & tower_rewards.delivered_bit(0) and claims & tower_rewards.claim_bit(25))
        self.assertEqual(self.book.words_of("pa")[-1]["payload"], rewards.tower_claims(claims))

    def test_a_save_that_already_had_the_milestone_counts_it_delivered(self):
        self.book.sync("pa", "Alice", record(75, 74, claims=0xFF), outstanding=0)
        ticket = self.book.issue_solo("pa", 75)
        self.book.settle(ticket["ticket_id"], "won", choose=chooser())
        mon = self.book.words_of("pa", ticket["ticket_id"])[-1]
        self.book.word_queued("pa", mon["ref"])
        self.book.word_receipt("pa", mon["ref"], 2)                                   # already delivered to this save
        self.assertEqual(self.book.milestone("pa", 2)["state"], "delivered")
        self.assertTrue(self.book.player("pa")["claims"] & tower_rewards.delivered_bit(2))

    def test_an_imported_record_settles_a_milestone_the_ledger_thought_owed(self):
        self.book.sync("pa", "Alice", record(25, 24, revision=3), outstanding=0)
        ticket = self.book.issue_solo("pa", 25)
        self.book.settle(ticket["ticket_id"], "won", choose=chooser())
        mon = self.book.words_of("pa", ticket["ticket_id"])[-1]
        self.book.word_queued("pa", mon["ref"])
        self.book.word_receipt("pa", mon["ref"], 0)
        self.assertEqual(self.book.milestone("pa", 0)["state"], "owed")
        delivered = tower_rewards.claim_bit(25) | tower_rewards.delivered_bit(0)
        self.book.sync("pa", "Alice", record(26, 25, claims=delivered, revision=9), outstanding=0)
        self.assertEqual(self.book.milestone("pa", 0)["state"], "delivered")
        with self.assertRaises(TowerError):
            self.book.resend_milestone("pa", 0)

    def test_a_milestone_that_cannot_be_made_yet_waits_and_is_chosen_later(self):
        self.book.sync("pa", "Alice", record(50, 49), outstanding=0)
        ticket = self.book.issue_solo("pa", 50)
        self.book.settle(ticket["ticket_id"], "won", choose=lambda *args: None)
        self.assertEqual(self.book.milestone("pa", 1)["state"], "waiting")
        self.assertEqual([m["milestone"] for m in self.book.waiting_milestones()], [1])
        self.assertNotIn("mon", [w[0] for w in self.words("pa")])
        self.book.choose_milestone("pa", 1, (3, "Venusaur", 45))
        self.assertEqual(self.book.milestone("pa", 1)["state"], "sent")
        self.assertEqual(self.book.words_of("pa")[-1]["payload"], rewards.tower_mon(1, 3, 45))
        self.book.choose_milestone("pa", 1, (6, "Charizard", 45))                     # chosen once: never rerolled
        self.assertEqual(self.book.milestone("pa", 1)["species"], 3)

    # --------------------------------------------------------- answering words
    def test_a_clearing_word_carries_the_ledger_and_the_tickets_low_byte_once(self):
        self.book.sync("pa", "Alice", record(18, 17), outstanding=0)
        self.assertTrue(self.book.plan_clear("pa", "tower:clear:300", 0x0102037F))
        self.assertFalse(self.book.plan_clear("pa", "tower:clear:300", 0x0102037F))
        self.assertEqual(self.words("pa"), [("300", 6, rewards.tower_progress(17, 18, 0x7F))])
        self.assertFalse(self.book.plan_clear("nobody", "tower:clear:1", 1))         # no ledger row: nothing to say
        self.assertEqual(self.book.player("pa")["progress"], 18)                      # nothing else changed

    # ------------------------------------------------------------------- Duo
    def test_a_duo_moves_one_player_and_is_a_replay_for_the_other(self):
        self.book.sync("pa", "Alice", record(12, 11), outstanding=0)
        self.book.sync("pb", "Bob", record(50, 49), outstanding=0)
        duo = self.book.invite_duo("d1", "pa", "pb", 12)
        self.assertEqual((duo["state"], duo["consent"]), ("invited", ["pa"]))
        with self.assertRaises(TowerError):
            self.book.invite_duo("d2", "pb", "pa", 12)                                # one Duo at a time
        with self.assertRaises(TowerError):
            self.book.set_ready("d1", "pa", True)                                     # not before it is accepted
        self.assertEqual(self.book.accept_duo("d1", "pb")["state"], "forming")
        self.book.set_ready("d1", "pa", True)
        self.assertEqual(self.book.set_ready("d1", "pb", True)["ready"], ["pa", "pb"])
        tickets = self.book.issue_duo("d1", "battle-1")
        self.assertEqual({t["player_id"]: t["progression"] for t in tickets}, {"pa": True, "pb": False})
        self.assertEqual(self.book.duo("d1")["state"], "battle")
        with self.assertRaises(TowerError):
            self.book.end_duo("d1", "left")                                           # not during the battle
        self.book.settle(tickets[0]["ticket_id"], "won", choose=chooser())
        self.assertEqual([t["state"] for t in self.book.tickets_of_battle("battle-1")], ["won", "won"])
        a, b = self.book.player("pa"), self.book.player("pb")
        self.assertEqual((a["progress"], a["highest"], a["best_duo"]), (13, 12, 12))
        self.assertEqual((b["progress"], b["highest"], b["best_duo"]), (50, 49, 12))
        self.assertEqual((a["wins"], b["wins"]), (1, 1))
        duo = self.book.duo("d1")
        self.assertEqual((duo["state"], duo["floor"], duo["ready"], duo["battle_id"]), ("forming", 13, [], None))
        state = [w for w in self.book.words_of("pb") if w["ref"].endswith(":0:state")][0]
        self.assertEqual(state["payload"], rewards.tower_progress(49, 50, 0))        # a Duo settles no solo result
        self.assertEqual([w[0] for w in self.words("pb")], ["state", "money", "bp"])  # a replay's rates for B
        self.assertEqual([w[0] for w in self.words("pa")], ["state", "money", "bp"])

    def test_an_abandoned_duo_battle_is_void_for_both(self):
        self.book.sync("pa", "Alice", record(12, 11), outstanding=0)
        self.book.sync("pb", "Bob", record(12, 11), outstanding=0)
        self.book.invite_duo("d1", "pa", "pb", 12)
        self.book.accept_duo("d1", "pb")
        self.book.issue_duo("d1", "battle-1")
        self.book.void_battle("battle-1", "abandoned")
        self.assertEqual([t["state"] for t in self.book.tickets_of_battle("battle-1")], ["void", "void"])
        self.assertEqual(self.book.duo("d1")["state"], "forming")
        self.assertEqual(self.book.words_of("pa") + self.book.words_of("pb"), [])
        self.assertEqual(self.book.player("pa")["progress"], 12)
        self.assertEqual(self.book.end_duo("d1", "left")["state"], "ended")

    # ------------------------------------------------------------------ restart
    def test_everything_survives_a_restart_and_nothing_settles_twice(self):
        self.book.sync("pa", "Alice", record(10, 9), outstanding=0)
        ticket = self.book.issue_solo("pa", 10)
        self.book.settle(ticket["ticket_id"], "won", choose=chooser())
        self.book.word_queued("pa", self.book.words_of("pa")[0]["ref"])
        self.world.close()
        again = SharedWorld(self.path, WORLD)
        self.addCleanup(again.close)
        book = again.tower
        self.assertEqual(book.player("pa")["progress"], 11)
        self.assertIsNone(book.settle(ticket["ticket_id"], "won"))
        self.assertEqual([w["state"] for w in book.words_of("pa")], ["queued", "planned", "planned", "planned", "planned"])
        self.assertEqual(book.ranking()[0]["best_solo"], 10)


if __name__ == "__main__":
    unittest.main()
