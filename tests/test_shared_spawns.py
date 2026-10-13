import unittest

from emerald_multiplayer import shared_spawns as ss
from emerald_multiplayer.shared_spawns import SpawnBoard, SpawnBoards


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_board(clock=None):
    clock = clock or FakeClock()
    return SpawnBoard(map_key="0.16#1", clock=clock), clock


def add(board, **kw):
    args = dict(species=10, level=5, lifetime=600)
    args.update(kw)
    return board.create(**args)


class LimitTests(unittest.TestCase):
    def test_normal_limit_is_eight(self):
        board, _ = make_board()
        ids = [add(board) for _ in range(ss.NORMAL_SLOT_LIMIT)]
        self.assertTrue(all(i is not None for i in ids))
        self.assertIsNone(add(board))

    def test_outbreak_limit_is_twelve_not_twenty(self):
        board, _ = make_board()
        board.set_outbreak(True)
        ids = [add(board, kind=ss.KIND_OUTBREAK) for _ in range(ss.OUTBREAK_SLOT_LIMIT)]
        self.assertTrue(all(i is not None for i in ids))
        self.assertIsNone(add(board, kind=ss.KIND_OUTBREAK))
        self.assertEqual(board.live_count(), 12)

    def test_outbreak_slots_need_an_active_outbreak(self):
        board, _ = make_board()
        with self.assertRaises(ValueError):
            add(board, kind=ss.KIND_OUTBREAK)

    def test_ending_outbreak_keeps_existing_spawns_and_blocks_new_ones_above_eight(self):
        board, _ = make_board()
        board.set_outbreak(True)
        ids = [add(board, kind=ss.KIND_OUTBREAK) for _ in range(12)]
        board.set_outbreak(False)
        self.assertEqual(board.live_count(), 12)  # nothing removed, nothing duplicated
        self.assertTrue(all(board.slots[i].state == ss.OPEN for i in ids))
        self.assertIsNone(add(board))  # no new spawn until below the normal limit

    def test_refill_after_outbreak_ends_once_below_eight(self):
        board, _ = make_board()
        board.set_outbreak(True)
        ids = [add(board, kind=ss.KIND_OUTBREAK) for _ in range(12)]
        board.set_outbreak(False)
        for spawn_id in ids[:5]:
            self.assertEqual(board.claim("a", spawn_id), ss.GRANTED)
            self.assertEqual(board.result("a", spawn_id, "caught"), ss.CONSUMED)
        self.assertEqual(board.live_count(), 7)
        self.assertIsNotNone(add(board))
        self.assertEqual(board.live_count(), 8)
        self.assertIsNone(add(board))


class ClaimTests(unittest.TestCase):
    def test_first_claim_wins_second_gets_busy(self):
        board, _ = make_board()
        sid = add(board)
        self.assertEqual(board.claim("a", sid), ss.GRANTED)
        self.assertEqual(board.claim("b", sid), ss.BUSY)

    def test_simultaneous_claims_resolve_to_exactly_one_winner(self):
        board, _ = make_board()
        sid = add(board)
        answers = [board.claim(p, sid) for p in ["p1", "p2", "p3", "p4"]]
        self.assertEqual(answers.count(ss.GRANTED), 1)
        self.assertEqual(answers[0], ss.GRANTED)

    def test_claim_unknown_or_removed_is_gone(self):
        board, _ = make_board()
        self.assertEqual(board.claim("a", 999), ss.GONE)
        sid = add(board)
        board.claim("a", sid)
        board.result("a", sid, "caught")
        self.assertEqual(board.claim("b", sid), ss.GONE)

    def test_expired_slot_cannot_be_claimed(self):
        board, clock = make_board()
        sid = add(board, lifetime=30)
        clock.now += 31
        board.tick(online_players=1)
        self.assertEqual(board.claim("a", sid), ss.GONE)


class ResultTests(unittest.TestCase):
    def test_caught_removes_for_everyone_and_pays_once(self):
        board, _ = make_board()
        sid = add(board)
        board.claim("a", sid)
        self.assertEqual(board.result("a", sid, "caught"), ss.CONSUMED)
        self.assertEqual(board.result("a", sid, "caught"), ss.GONE)  # no second reward
        self.assertEqual(board.claim("b", sid), ss.GONE)  # defeated/caught not battleable again

    def test_defeated_cannot_be_battled_again(self):
        board, _ = make_board()
        sid = add(board)
        board.claim("a", sid)
        self.assertEqual(board.result("a", sid, "defeated"), ss.CONSUMED)
        self.assertEqual(board.claim("b", sid), ss.GONE)

    def test_only_the_claimant_may_report(self):
        board, _ = make_board()
        sid = add(board)
        board.claim("a", sid)
        self.assertEqual(board.result("b", sid, "caught"), ss.NOT_CLAIMANT)
        self.assertEqual(board.slots[sid].state, ss.CLAIMED)

    def test_fled_releases_slot_to_others(self):
        board, _ = make_board()
        sid = add(board)
        board.claim("a", sid)
        self.assertEqual(board.result("a", sid, "fled"), ss.RELEASED)
        self.assertEqual(board.claim("b", sid), ss.GRANTED)

    def test_removed_slot_frees_capacity_for_replacement(self):
        board, _ = make_board()
        ids = [add(board) for _ in range(ss.NORMAL_SLOT_LIMIT)]
        board.claim("a", ids[0])
        board.result("a", ids[0], "caught")
        self.assertIsNotNone(add(board))


class ReconnectAndDepartureTests(unittest.TestCase):
    def test_reconnect_within_grace_resumes_same_claim(self):
        board, clock = make_board()
        sid = add(board)
        board.claim("a", sid)
        board.player_disconnected("a")
        clock.now += ss.CLAIM_GRACE_SECONDS - 5
        board.tick(online_players=1)
        self.assertEqual(board.claim("a", sid), ss.GRANTED)
        self.assertIsNone(board.slots[sid].grace_until)
        self.assertEqual(board.claim("b", sid), ss.BUSY)

    def test_claim_released_after_grace_so_others_can_engage(self):
        board, clock = make_board()
        sid = add(board)
        board.claim("a", sid)
        board.player_disconnected("a")
        clock.now += ss.CLAIM_GRACE_SECONDS + 1
        self.assertEqual(board.tick(online_players=1), [sid])
        self.assertEqual(board.claim("b", sid), ss.GRANTED)

    def test_disconnect_during_claim_does_not_duplicate_reward(self):
        board, clock = make_board()
        sid = add(board)
        board.claim("a", sid)
        board.player_disconnected("a")
        clock.now += ss.CLAIM_GRACE_SECONDS + 1
        board.tick(online_players=0)  # nobody online: grace paused, no release
        self.assertEqual(board.result("a", sid, "caught"), ss.CONSUMED)  # the claim survived: one reward
        self.assertEqual(board.result("a", sid, "caught"), ss.GONE)  # and never a second one
        self.assertEqual(board.slots[sid].state, ss.REMOVED)

    def test_release_on_map_change_frees_slot(self):
        board, _ = make_board()
        sid = add(board)
        board.claim("a", sid)
        self.assertEqual(board.release("a", sid), ss.RELEASED)
        self.assertEqual(board.claim("b", sid), ss.GRANTED)

    def test_releasing_someone_elses_spawn_is_refused(self):
        board, _ = make_board()
        sid = add(board)
        board.claim("a", sid)
        self.assertEqual(board.release("b", sid), ss.NOT_CLAIMANT)


class TimerTests(unittest.TestCase):
    def test_open_spawn_expires_only_while_someone_is_online(self):
        board, clock = make_board()
        sid = add(board, lifetime=100)
        board.tick(online_players=1)
        clock.now += 3600  # an hour with nobody online
        self.assertEqual(board.tick(online_players=0), [])
        self.assertEqual(board.slots[sid].state, ss.OPEN)
        clock.now += 50
        self.assertEqual(board.tick(online_players=1), [])
        clock.now += 60
        self.assertEqual(board.tick(online_players=1), [sid])

    def test_grace_period_pauses_with_nobody_online(self):
        board, clock = make_board()
        sid = add(board)
        board.claim("a", sid)
        board.player_disconnected("a")
        board.tick(online_players=0)
        clock.now += 10_000
        self.assertEqual(board.tick(online_players=0), [])
        self.assertEqual(board.slots[sid].state, ss.CLAIMED)


class ShinyAndSyncTests(unittest.TestCase):
    def test_shiny_and_species_are_fixed_at_creation(self):
        board, _ = make_board()
        sid = add(board, species=25, level=12, form=1, gender=2, shiny=True)
        before = board.snapshot()
        board.claim("a", sid)
        board.result("a", sid, "fled")
        board.claim("b", sid)
        after = board.snapshot(viewer="b")
        for snap in (before[0], after[0]):
            self.assertEqual((snap["species"], snap["level"], snap["form"], snap["gender"]), (25, 12, 1, 2))
            self.assertTrue(snap["shiny"])
        self.assertTrue(after[0]["claimed_by_you"])

    def test_late_join_snapshot_lists_only_live_slots(self):
        board, _ = make_board()
        a = add(board, species=1)
        b = add(board, species=2)
        board.claim("x", a)
        board.result("x", a, "caught")
        snap = board.snapshot()
        self.assertEqual([s["spawn_id"] for s in snap], [b])

    def test_snapshot_never_exceeds_limit(self):
        board, _ = make_board()
        board.set_outbreak(True)
        for _ in range(12):
            add(board, kind=ss.KIND_OUTBREAK)
        self.assertEqual(len(board.snapshot()), 12)


class IsolationTests(unittest.TestCase):
    def test_map_instances_do_not_share_slots_or_limits(self):
        clock = FakeClock()
        boards = SpawnBoards(clock)
        first = boards.board("0.16#1")
        second = boards.board("0.16#2")
        for _ in range(ss.NORMAL_SLOT_LIMIT):
            add(first)
        self.assertIsNone(add(first))
        self.assertIsNotNone(add(second))
        self.assertEqual(second.live_count(), 1)
        self.assertEqual(boards.keys(), ["0.16#1", "0.16#2"])

    def test_spawn_ids_are_never_reused_across_removal(self):
        board, _ = make_board()
        first = add(board)
        board.claim("a", first)
        board.result("a", first, "caught")
        board.prune()
        second = add(board)
        self.assertGreater(second, first)
        self.assertEqual(board.claim("a", first), ss.GONE)


if __name__ == "__main__":
    unittest.main()
