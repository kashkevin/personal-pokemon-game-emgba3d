"""Shared wild spawn slots (Phase 3): limits, claims, results, time, persistence."""
import unittest

from emerald_multiplayer import shared_spawns as ss
from emerald_multiplayer.shared_spawns import SpawnBoard, SpawnBoards


class ActiveClock:
    """The shared world's active clock: it only runs while somebody is online."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_board(clock=None):
    clock = clock or ActiveClock()
    return SpawnBoard(map_key="0.16", clock=clock), clock


_NEXT_TILE = [0]


def add(board, **kw):
    _NEXT_TILE[0] += 1
    args = dict(species=10, level=5, personality=0x12345678, shiny=False,
                x=_NEXT_TILE[0] % 40, y=_NEXT_TILE[0] // 40, lifetime=600)
    args.update(kw)
    return board.create(**args)


class LegendStaysTests(unittest.TestCase):
    """Legendary and Mythical Pokemon never despawn (the owner's request of 2026-10-27): only a catch or a win removes one."""

    def legend(self, board, **kw):
        spawn_id = add(board, **kw)
        board.get(spawn_id).legend_rolled = True
        board.get(spawn_id).legend = True
        board.get(spawn_id).species = 380   # as roll_legend_on_claim leaves a slot that became one (here Latias)
        return spawn_id

    def test_a_legend_outlives_its_lifetime_and_a_plain_one_does_not(self):
        board, clock = make_board()
        legend, plain = self.legend(board, lifetime=60), add(board, lifetime=60)
        clock.now += 100_000
        board.tick()
        self.assertEqual([s.spawn_id for s in board.live()], [legend])

    def test_a_legend_is_never_retired_for_distance_or_trimmed(self):
        board, clock = make_board()
        legend = self.legend(board)
        self.assertFalse(board.retire(legend, "wandered_off"))
        board.set_outbreak(True)
        for _ in range(ss.OUTBREAK_SLOT_LIMIT - 1):
            add(board, kind=ss.KIND_OUTBREAK)
        board.set_outbreak(False)
        retired = board.trim()
        self.assertNotIn(legend, retired)
        self.assertIn(legend, [s.spawn_id for s in board.live()])

    def test_running_or_losing_leaves_it_catching_or_defeating_removes_it(self):
        board, clock = make_board()
        legend = self.legend(board, lifetime=60)
        for result in ("ran", "fled", "lost", "cancelled"):
            self.assertEqual(board.claim("a", legend), ss.GRANTED)
            clock.now += 1_000
            self.assertEqual(board.result("a", legend, result), ss.RELEASED)
            board.tick()
            self.assertIn(legend, [s.spawn_id for s in board.live()], result)
        self.assertEqual(board.claim("b", legend), ss.GRANTED)
        self.assertEqual(board.claim("a", legend), ss.BUSY)   # one claimant at a time
        self.assertEqual(board.result("b", legend, "defeated"), ss.CONSUMED)
        self.assertNotIn(legend, [s.spawn_id for s in board.live()])

    def test_a_claimant_who_disconnects_keeps_it_for_the_grace_then_it_reopens(self):
        board, clock = make_board()
        legend = self.legend(board, lifetime=60)
        board.claim("a", legend)
        board.player_disconnected("a", grace=30)
        clock.now += 100_000
        board.tick()
        (slot,) = board.live()
        self.assertEqual((slot.spawn_id, slot.state, slot.species, slot.legend), (legend, ss.OPEN, 380, True))

    def test_a_legend_survives_a_save_and_restore_once(self):
        board, clock = make_board()
        legend = self.legend(board, lifetime=60, shiny=True, personality=0xCAFEBABE, level=37)
        clock.now += 100_000
        state = board.to_state()
        clock2 = ActiveClock()
        restored = SpawnBoard.from_state(state, clock2)   # a host restart: the active clock starts again
        clock2.now += 100_000
        restored.tick()
        live = restored.live()
        self.assertEqual(len(live), 1)   # restored once, not duplicated
        (slot,) = live
        self.assertEqual((slot.spawn_id, slot.species, slot.level, slot.shiny, slot.personality, slot.legend, slot.legend_rolled),
                         (legend, 380, 37, True, 0xCAFEBABE, True, True))


class ShinyStaysTests(unittest.TestCase):
    """Shiny Pokemon never despawn (the owner's request of 2026-10-24): only a catch or a win removes one."""

    def test_a_shiny_outlives_its_lifetime_and_a_plain_one_does_not(self):
        board, clock = make_board()
        shiny, plain = add(board, shiny=True, lifetime=60), add(board, lifetime=60)
        clock.now += 10_000
        board.tick()
        self.assertEqual([s.spawn_id for s in board.live()], [shiny])
        self.assertNotIn(plain, [s.spawn_id for s in board.live()])

    def test_a_shiny_is_never_retired_or_trimmed(self):
        board, clock = make_board()
        shiny = add(board, shiny=True)
        self.assertFalse(board.retire(shiny, "wandered_off"))
        board.set_outbreak(True)
        for _ in range(ss.OUTBREAK_SLOT_LIMIT - 1):
            add(board, kind=ss.KIND_OUTBREAK)
        board.set_outbreak(False)
        retired = board.trim()
        self.assertNotIn(shiny, retired)
        self.assertIn(shiny, [s.spawn_id for s in board.live()])
        self.assertEqual(len(retired), ss.OUTBREAK_SLOT_LIMIT - ss.NORMAL_SLOT_LIMIT)

    def test_running_from_a_shiny_leaves_it_and_catching_it_removes_it(self):
        board, clock = make_board()
        shiny = add(board, shiny=True, lifetime=60)
        self.assertEqual(board.claim("a", shiny), ss.GRANTED)
        clock.now += 1_000
        self.assertEqual(board.result("a", shiny, "ran"), ss.RELEASED)
        board.tick()
        self.assertIn(shiny, [s.spawn_id for s in board.live()])
        self.assertEqual(board.claim("b", shiny), ss.GRANTED)
        self.assertEqual(board.result("b", shiny, "caught"), ss.CONSUMED)
        self.assertNotIn(shiny, [s.spawn_id for s in board.live()])

    def test_a_shiny_whose_claimant_never_came_back_stays(self):
        board, clock = make_board()
        shiny = add(board, shiny=True, lifetime=60)
        board.claim("a", shiny)
        board.player_disconnected("a", grace=30)
        clock.now += 10_000
        board.tick()
        (slot,) = board.live()
        self.assertEqual((slot.spawn_id, slot.state), (shiny, ss.OPEN))

    def test_a_pokemon_shiny_only_for_shiny_charm_owners_is_kept_too(self):
        """The 2026-10-27 wild item audit: the host keeps a Pokemon the Shiny Charm makes shiny (it cannot see bags)."""
        board, clock = make_board()
        charm, plain = None, None
        for personality in range(200_000):   # find a personality the Charm makes shiny for the next spawn id
            if ss.charm_shiny(board.next_id, personality):
                charm = add(board, personality=personality, lifetime=60)
                break
        self.assertIsNotNone(charm)
        plain = add(board, personality=0, lifetime=60)
        self.assertFalse(ss.charm_shiny(plain, 0))
        self.assertFalse(board.retire(charm, "wandered_off"))
        clock.now += 10_000
        board.tick()
        self.assertEqual([s.spawn_id for s in board.live()], [charm])
        (slot,) = board.live()
        self.assertFalse(slot.shiny)   # the host's own roll is unchanged: it is shiny only for a Charm owner
        self.assertTrue(slot.kept)

    def test_the_charm_hash_is_the_engines_bit_for_bit(self):
        # multiplayer_spawns.c MultiplayerSpawns_CharmHash, compiled and run (2026-10-27)
        for spawn_id, personality, expected in ((1, 0, 3291240986), (65, 0x12345678, 4188010237), (129, 0xDEADBEEF, 1050170200),
                                                (65535, 0xFFFFFFFF, 3317913772), (4000000000, 0x00ABCDEF, 3674487299)):
            self.assertEqual(ss.charm_hash(spawn_id, personality), expected)
        self.assertEqual(ss.CHARM_THRESHOLD, 669574)

    def test_a_shiny_survives_a_save_and_restore(self):
        board, clock = make_board()
        shiny = add(board, shiny=True, lifetime=60)
        clock.now += 10_000
        state = board.to_state()
        again = SpawnBoard.from_state(state, clock)
        clock.now += 10_000
        again.tick()
        self.assertEqual([s.spawn_id for s in again.live()], [shiny])


class LimitTests(unittest.TestCase):
    def test_normal_limit_is_eight(self):
        board, _ = make_board()
        ids = [add(board) for _ in range(ss.NORMAL_SLOT_LIMIT)]
        self.assertTrue(all(i is not None for i in ids))
        self.assertIsNone(add(board))

    def test_outbreak_limit_is_twelve_in_total_not_twenty(self):
        board, _ = make_board()
        normal = [add(board) for _ in range(5)]
        board.set_outbreak(True)
        more = [add(board, kind=ss.KIND_OUTBREAK) for _ in range(ss.OUTBREAK_SLOT_LIMIT)]
        self.assertTrue(all(i is not None for i in normal))
        self.assertEqual(sum(i is not None for i in more), ss.OUTBREAK_SLOT_LIMIT - 5)
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

    def test_two_pokemon_never_share_a_tile(self):
        board, _ = make_board()
        self.assertIsNotNone(add(board, x=3, y=3))
        self.assertIsNone(add(board, x=3, y=3))


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
        board.tick()
        self.assertEqual(board.claim("a", sid), ss.GONE)

    def test_claimed_pokemon_does_not_move_or_retire(self):
        board, _ = make_board()
        sid = add(board, x=5, y=5)
        board.claim("a", sid)
        self.assertFalse(board.move(sid, 6, 5, ss.DIR_EAST))
        self.assertFalse(board.retire(sid))


class ResultTests(unittest.TestCase):
    def test_caught_removes_for_everyone_and_counts_once(self):
        board, _ = make_board()
        sid = add(board)
        board.claim("a", sid)
        self.assertEqual(board.result("a", sid, "caught"), ss.CONSUMED)
        self.assertEqual(board.result("a", sid, "caught"), ss.GONE)  # never a second time
        self.assertEqual(board.claim("b", sid), ss.GONE)

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

    def test_running_losing_or_cancelling_releases_to_others(self):
        for outcome in ("ran", "fled", "lost", "cancelled"):
            board, _ = make_board()
            sid = add(board)
            board.claim("a", sid)
            self.assertEqual(board.result("a", sid, outcome), ss.RELEASED)
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
        board.tick()
        self.assertEqual(board.claim("a", sid), ss.GRANTED)
        self.assertIsNone(board.slots[sid].grace_until)
        self.assertEqual(board.claim("b", sid), ss.BUSY)

    def test_claim_released_after_grace_so_others_can_engage(self):
        board, clock = make_board()
        sid = add(board, lifetime=10_000)
        board.claim("a", sid)
        board.player_disconnected("a")
        clock.now += ss.CLAIM_GRACE_SECONDS + 1
        self.assertEqual(board.tick(), [sid])
        self.assertEqual(board.claim("b", sid), ss.GRANTED)

    def test_disconnected_claimant_reports_once_after_reconnecting(self):
        board, clock = make_board()
        sid = add(board)
        board.claim("a", sid)
        board.player_disconnected("a")
        clock.now += 30
        board.player_reconnected("a")
        self.assertEqual(board.result("a", sid, "caught"), ss.CONSUMED)
        self.assertEqual(board.result("a", sid, "caught"), ss.GONE)

    # Audit 2026-10-13, KNOWN_ISSUES M16: a result that arrives after the claim lapsed.
    def test_a_late_catch_from_the_last_claimant_removes_it_once(self):
        board, clock = make_board()
        sid = add(board, lifetime=10_000)
        board.claim("a", sid)
        board.player_disconnected("a")
        clock.now += ss.CLAIM_GRACE_SECONDS + 1
        board.tick()  # the grace ran out while the result was on its way
        self.assertEqual(board.result("b", sid, "caught"), ss.NOT_CLAIMANT)
        self.assertEqual(board.result("a", sid, "caught"), ss.CONSUMED)
        self.assertEqual(board.result("a", sid, "caught"), ss.GONE)
        self.assertEqual(board.claim("b", sid), ss.GONE)

    def test_a_late_run_from_the_last_claimant_changes_nothing(self):
        board, clock = make_board()
        sid = add(board, lifetime=10_000)
        board.claim("a", sid)
        board.player_disconnected("a")
        clock.now += ss.CLAIM_GRACE_SECONDS + 1
        board.tick()
        self.assertEqual(board.result("a", sid, "ran"), ss.NOT_CLAIMANT)
        self.assertEqual(board.claim("b", sid), ss.GRANTED)

    def test_a_late_catch_while_another_player_battles_it_is_refused(self):
        board, clock = make_board()
        sid = add(board, lifetime=10_000)
        board.claim("a", sid)
        board.player_disconnected("a")
        clock.now += ss.CLAIM_GRACE_SECONDS + 1
        board.tick()
        self.assertEqual(board.claim("b", sid), ss.GRANTED)
        self.assertEqual(board.result("a", sid, "caught"), ss.NOT_CLAIMANT)
        self.assertEqual(board.result("b", sid, "caught"), ss.CONSUMED)

    def test_the_last_claimant_survives_a_restart(self):
        clock = ActiveClock()
        boards = SpawnBoards(clock)
        sid = add(boards.board("0.16"), lifetime=10_000)
        boards.board("0.16").claim("alice", sid)
        boards.board("0.16").result("alice", sid, "ran")
        again = SpawnBoards.from_state(boards.to_state(), clock)
        self.assertEqual(again.board("0.16").result("alice", sid, "caught"), ss.CONSUMED)

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


class MovementTests(unittest.TestCase):
    def test_moves_one_tile_and_counts_moves(self):
        board, _ = make_board()
        sid = add(board, x=5, y=5)
        self.assertTrue(board.move(sid, 6, 5, ss.DIR_EAST))
        self.assertEqual((board.slots[sid].x, board.slots[sid].y, board.slots[sid].move_seq), (6, 5, 1))
        self.assertFalse(board.move(sid, 8, 5, ss.DIR_EAST))  # never jumps
        self.assertTrue(board.move(sid, 6, 5, ss.DIR_NORTH))  # turn in place
        self.assertEqual(board.slots[sid].move_seq, 2)

    def test_never_steps_onto_another_pokemon(self):
        board, _ = make_board()
        a = add(board, x=5, y=5)
        add(board, x=6, y=5)
        self.assertFalse(board.move(a, 6, 5, ss.DIR_EAST))


class ShinyAndSyncTests(unittest.TestCase):
    def test_attributes_are_fixed_at_creation_and_the_same_for_every_viewer(self):
        board, _ = make_board()
        sid = add(board, species=25, level=12, personality=0xDEADBEEF, shiny=True, form=1, x=4, y=9)
        before = board.snapshot("x")
        board.claim("a", sid)
        board.result("a", sid, "ran")
        board.claim("b", sid)
        for viewer in ("a", "b", "c"):
            snap = board.snapshot(viewer)[0]
            self.assertEqual((snap["species"], snap["level"], snap["personality"], snap["form"], snap["shiny"]),
                             (25, 12, 0xDEADBEEF, 1, True))
            self.assertEqual((snap["x"], snap["y"]), (4, 9))
        self.assertEqual(before[0]["personality"], 0xDEADBEEF)
        self.assertTrue(board.snapshot("b")[0]["mine"])
        self.assertTrue(board.snapshot("a")[0]["busy"])
        self.assertFalse(board.snapshot("a")[0]["mine"])

    def test_late_join_snapshot_lists_only_live_slots(self):
        board, _ = make_board()
        a = add(board, species=1)
        b = add(board, species=2)
        board.claim("x", a)
        board.result("x", a, "caught")
        self.assertEqual([s["spawn_id"] for s in board.snapshot()], [b])

    def test_fresh_flag_lasts_a_moment(self):
        board, clock = make_board()
        add(board)
        self.assertTrue(board.snapshot()[0]["fresh"])
        clock.now += ss.FRESH_SECONDS
        self.assertFalse(board.snapshot()[0]["fresh"])


class TimeTests(unittest.TestCase):
    def test_open_spawn_expires_on_active_time_only(self):
        # The board's clock is the shared world's active clock: when nobody is
        # online it does not advance, so nothing expires (see the shared world tests).
        board, clock = make_board()
        sid = add(board, lifetime=100)
        clock.now += 99
        self.assertEqual(board.tick(), [])
        clock.now += 1
        self.assertEqual(board.tick(), [sid])

    def test_battle_outlasting_the_lifetime_ends_with_the_battle(self):
        board, clock = make_board()
        sid = add(board, lifetime=10)
        board.claim("a", sid)
        clock.now += 60
        self.assertEqual(board.tick(), [])  # still being battled
        self.assertEqual(board.result("a", sid, "ran"), ss.RELEASED)
        self.assertEqual(board.tick(), [sid])  # then its time is up


class PersistenceTests(unittest.TestCase):
    def test_restart_restores_slots_with_remaining_time_and_claims_with_grace(self):
        clock = ActiveClock()
        boards = SpawnBoards(clock)
        board = boards.board("0.16")
        a = add(board, lifetime=100, x=1, y=1, shiny=True)
        b = add(board, lifetime=100, x=2, y=1)
        board.claim("alice", b)
        clock.now += 40
        state = boards.to_state()
        restarted = ActiveClock()
        restarted.now = 5.0  # a new process: an unrelated clock value
        again = SpawnBoards.from_state(state, restarted)
        board2 = again.board("0.16")
        self.assertEqual(board2.slots[a].expires_at - restarted.now, 60)
        self.assertTrue(board2.slots[a].shiny)
        self.assertEqual(board2.claim("bob", b), ss.BUSY)          # alice keeps it
        self.assertEqual(board2.result("alice", b, "caught"), ss.CONSUMED)
        self.assertGreater(again.allocate_id(), b)                 # ids are never reused

    def test_restored_claim_lapses_after_grace(self):
        clock = ActiveClock()
        boards = SpawnBoards(clock)
        sid = add(boards.board("0.16"), lifetime=10_000)
        boards.board("0.16").claim("alice", sid)
        again = SpawnBoards.from_state(boards.to_state(), clock)
        clock.now += ss.CLAIM_GRACE_SECONDS + 1
        again.board("0.16").tick()
        self.assertEqual(again.board("0.16").claim("bob", sid), ss.GRANTED)

    def test_unknown_state_versions_are_refused(self):
        with self.assertRaises(ValueError):
            SpawnBoards.from_state({"version": 99}, ActiveClock())


class RecentSpawnTests(unittest.TestCase):
    """A board remembers its last few species, so the director can avoid repeating them (2026-10-25)."""

    def test_a_board_keeps_the_species_of_its_last_six_spawns(self):
        board, clock = make_board()
        for species in range(1, 9):
            add(board, species=species, lifetime=1)
            clock.now += 5
            board.tick()   # each one expires before the next: the history is about spawns, not live slots
        self.assertEqual(board.recent, [3, 4, 5, 6, 7, 8])
        self.assertEqual(len(board.recent), ss.RECENT_SPAWNS)

    def test_a_refused_spawn_is_not_remembered(self):
        board, _clock = make_board()
        add(board, species=1, x=3, y=3)
        self.assertIsNone(add(board, species=2, x=3, y=3))   # the tile is taken
        self.assertEqual(board.recent, [1])

    def test_the_history_survives_a_restart(self):
        clock = ActiveClock()
        boards = SpawnBoards(clock)
        for species in (10, 13, 16):
            add(boards.board("0.16"), species=species)
        again = SpawnBoards.from_state(boards.to_state(), ActiveClock())
        self.assertEqual(again.board("0.16").recent, [10, 13, 16])

    def test_a_state_saved_before_the_history_loads_without_one(self):
        clock = ActiveClock()
        boards = SpawnBoards(clock)
        add(boards.board("0.16"), species=10)
        state = boards.to_state()
        for item in state["boards"]:
            del item["recent"]
        self.assertEqual(SpawnBoards.from_state(state, clock).board("0.16").recent, [])


class IsolationTests(unittest.TestCase):
    def test_map_instances_do_not_share_slots_or_limits(self):
        clock = ActiveClock()
        boards = SpawnBoards(clock)
        first = boards.board("0.16")
        second = boards.board("0.17")
        for _ in range(ss.NORMAL_SLOT_LIMIT):
            add(first)
        self.assertIsNone(add(first))
        self.assertIsNotNone(add(second))
        self.assertEqual(second.live_count(), 1)
        self.assertEqual(boards.keys(), ["0.16", "0.17"])

    def test_spawn_ids_are_unique_across_the_world_and_never_reused(self):
        clock = ActiveClock()
        boards = SpawnBoards(clock)
        a = add(boards.board("0.16"))
        b = add(boards.board("0.17"))
        self.assertNotEqual(a, b)
        boards.board("0.16").claim("p", a)
        boards.board("0.16").result("p", a, "caught")
        boards.board("0.16").prune()
        c = add(boards.board("0.16"))
        self.assertGreater(c, b)
        self.assertEqual(boards.board("0.16").claim("p", a), ss.GONE)
        self.assertEqual(boards.find(b)[0].map_key, "0.17")


if __name__ == "__main__":
    unittest.main()
