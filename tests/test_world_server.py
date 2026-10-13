"""Shared-world host features over real loopback TCP: world frames, looks,
friendship, wagers through a closed native battle, wallet receipts and co-op
Gym requests. Native receipts are explicit trusted fixtures (as in
test_battle_arbitration); the ROM side is covered by actual-core proofs."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
import struct
import tempfile
import unittest
from uuid import uuid4

from emerald_multiplayer.battle_desk import BattleError
from emerald_multiplayer.native_battle import Opcode
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE
from emerald_multiplayer.server import ServerConfig, WorldServer
from emerald_multiplayer.trade_storage import TradeCheckpointStore
from emerald_multiplayer.battle_reservations import enable_battle_reservations
from test_battle_arbitration import Actor, BUILD, RULES, wait_until
from test_ownership_storage import owned_flash, source_flash


class WorldServerTests(unittest.IsolatedAsyncioTestCase):
    teams = False

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = TradeCheckpointStore(self.root / "world.sqlite3", BUILD, RULES)
        enable_battle_reservations(self.store, self.root / "before-battles.sqlite3")
        self.store.begin_server_boot()
        self.players = []
        for index in range(4):
            player = self.store.create_player(f"Trainer {index}")
            lease = self.store.acquire_lease(player.player_id, player.credential)
            personalities = (7 + index * 2, 8 + index * 2)
            self.store.enroll_player(player.player_id, source_flash(("party:0", "party:1"), personalities=personalities))
            grant = self.store.reserve_instances(player.player_id, lease, str(uuid4()), 0, 1, 32)
            payload = owned_flash(grant, (("party:0", grant.start), ("party:1", grant.start + 1)),
                                  personalities=personalities)
            self.store.commit_checkpoint(player.player_id, lease, str(uuid4()), 0, payload, BUILD, RULES, OWNERSHIP_PROFILE)
            self.store.release_lease(player.player_id, lease)
            self.players.append(player)
        self.server = WorldServer(ServerConfig(BUILD, RULES, heartbeat_interval=.05, idle_timeout=20),
                                  store=self.store, development_trades=True, development_battles=True,
                                  development_teams=self.teams)
        self.money = {player.player_id: 20_000 for player in self.players}
        self.server._money = lambda player_id: self.money.get(player_id)
        await self.server.start(port=0)
        self.actors = [await Actor.connect(self.server.address, player) for player in self.players]
        self.desk = self.server.battle_desk

    async def asyncTearDown(self):
        for actor in self.actors:
            await actor.close()
        await self.server.close()
        self.store.close()
        self.temp.cleanup()

    def pid(self, index):
        return self.players[index].player_id

    @property
    def pids(self):
        return [player.player_id for player in self.players]

    def actor(self, index):
        return self.pid(index), self.actors[index].lease

    async def presence(self, index, *, x=6, map_number=9, wallet_seq=None):
        message = dict(type="presence", session_epoch=self.actors[index].lease, seq=self.seq(index), map_epoch=0,
                       map_group=0, map_number=map_number, x=x, y=11, direction=1, elevation=0,
                       avatar_gender=0, activity="overworld")
        if wallet_seq is not None:
            message["wallet_seq"] = wallet_seq
        await self.actors[index].send(message)
        await wait_until(lambda: (self.server.sessions[self.pid(index)].presence or {}).get("x") == x)

    def seq(self, index):
        counter = getattr(self, "_seq", {})
        counter[index] = counter.get(index, 0) + 1
        self._seq = counter
        return counter[index]

    async def world(self, index, predicate=lambda world: True):
        actor = self.actors[index]
        async with asyncio.timeout(8):
            while True:
                if actor.worlds and predicate(actor.worlds[-1]):
                    return actor.worlds[-1]
                self.server._broadcast_world()
                await asyncio.sleep(.02)

    def notices_for(self, index):
        """Every notice the host is showing or has queued for this player."""
        world = self.server.shared_world
        pid = self.pid(index)
        return [notice["text"] for notice in [world._notice, *world._notice_queue]
                if notice is not None and (notice["to"] is None or pid in notice["to"])]

    async def world_rpc(self, index, kind, **fields):
        """World replies are bound to the connection; they carry only the request id."""
        from emerald_multiplayer.shared_world_protocol import validate_world_reply
        actor = self.actors[index]
        request_id = str(uuid4())
        future = asyncio.get_running_loop().create_future()
        actor.pending[request_id] = future
        try:
            await actor.send(dict(type=kind, request_id=request_id, session_epoch=actor.lease, **fields))
            reply = validate_world_reply(await asyncio.wait_for(future, 8))
        finally:
            actor.pending.pop(request_id, None)
        return reply if reply["type"] == "world_error" else {**reply, "type": "world_result"}


class WorldFrameTests(WorldServerTests):
    async def test_every_frame_has_clock_event_notice_and_private_wallet_and_teammate(self):
        world = await self.world(0, lambda w: len(w["players"]) == 4)
        self.assertEqual(set(world), {"type", "protocol", "world_seq", "players", "clock", "event",
                                      "notice", "wallet", "teammate", "spawns"})
        self.assertTrue(world["clock"]["running"])
        self.assertIsNone(world["wallet"])
        self.assertIsNone(world["teammate"])
        self.assertTrue(all(set(p) == {"player_id", "display_name", "session_epoch", "presence", "appearance"}
                            for p in world["players"]))

    async def test_appearance_is_validated_stored_and_broadcast(self):
        reply = await self.world_rpc(0, "appearance_set", appearance="0102030405060700")
        self.assertEqual(reply["result"], {"appearance": "0102030405060700"})
        world = await self.world(1, lambda w: any(p["appearance"] == "0102030405060700" for p in w["players"]))
        owner = next(p for p in world["players"] if p["appearance"] == "0102030405060700")
        self.assertEqual(owner["player_id"], self.pid(0))
        self.assertEqual((await self.world_rpc(0, "appearance_get"))["result"], {"appearance": "0102030405060700"})
        # A malformed look is a protocol violation: the host closes that session
        # (the companion validates looks before sending them).
        with self.assertRaises(ConnectionError):
            await self.world_rpc(0, "appearance_set", appearance="0106000000000000")
        self.assertEqual(self.server.shared_world.appearance(self.pid(0)), "0102030405060700")

    async def test_friendship_view_lists_every_other_connected_player(self):
        friends = (await self.world_rpc(0, "friendship_get"))["result"]["friends"]
        self.assertEqual(set(friends), {self.pid(1), self.pid(2), self.pid(3)})
        self.assertTrue(all(view["name"] == "New Friends" for view in friends.values()))

    async def test_world_event_claim_result_and_notice_through_the_host(self):
        world = self.server.shared_world
        world.locations = [{"name": "Route 101", "map_group": 0, "map_number": 16, "x": 9, "y": 9,
                            "min_level": 0, "themes": []}]
        event = world.spawn_event(progression_level=10, category="rare")
        self.server._broadcast_world()
        frame = await self.world(1, lambda w: w["event"] is not None)
        self.assertEqual(frame["event"]["event_id"], event["event_id"])
        claim = await self.world_rpc(0, "world_action", action="claim", event_id=event["event_id"], result=None, seq=1)
        self.assertEqual(claim["result"]["outcome"], "granted")
        busy = await self.world_rpc(1, "world_action", action="claim", event_id=event["event_id"], result=None, seq=1)
        self.assertEqual(busy["result"]["outcome"], "busy")
        frame = await self.world(1, lambda w: w["event"] and w["event"]["claimant"] == self.pid(0))
        caught = await self.world_rpc(0, "world_action", action="result", event_id=event["event_id"],
                                      result="caught", seq=2)
        self.assertEqual(caught["result"]["outcome"], "consumed")
        await self.world(2, lambda w: w["event"] is None)


class WagerNetworkTests(WorldServerTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.battle_id = str(uuid4())
        self.view = self.desk.invite(*self.actor(0), self.pid(1), self.battle_id)
        self.generation = self.view["generation"]

    def call(self, method, index, *args, **fields):
        generation = () if method == "status" else (self.generation,)
        return getattr(self.desk, method)(*self.actor(index), self.battle_id, *generation, *args, **fields)

    def descriptor(self, index):
        return self.call("descriptor", index)

    def control(self, index, opcode, sequence, data=b""):
        from emerald_multiplayer.native_battle import NativeControl
        return NativeControl(100 + index, self.actors[index].lease, self.battle_id, sequence, opcode,
                             source_slot=self.descriptor(index).source_slot, data=data,
                             phase=self.descriptor(index).mode)

    def query(self, index, sequence, flags=1, revision=0, outcome=0):
        from uuid import UUID
        return struct.pack("<I16sBBBB10I", flags, UUID(self.generation).bytes, len(self.view["players"]),
                           self.descriptor(index).source_slot, self.descriptor(index).mode, 0, sequence,
                           0, 0, 0, 0, 0, 0, 600, revision, outcome)

    def accept_and_register(self):
        self.call("accept", 1, self.view["fingerprint"])
        for index in range(2):
            self.call("register", index, 100 + index)

    def bind_and_prepare(self):
        from emerald_multiplayer.native_battle import Kind
        for index in range(2):
            binding = self.call("authorize_bind", index)
            request = self.control(index, Opcode.BIND, 1, binding.pack())
            self.call("bound", index, request, replace(request, data=self.query(index, 1)))
            command = self.control(index, Opcode.PREPARE, 2, self.call("preparation", index).pack())
            self.call("prepared", index, command, replace(command, data=self.query(index, 2, 9, 1)),
                      self.descriptor(index).trainer_descriptor)
        self.kind = Kind

    def start_and_finish(self, outcome):
        self.desk.authorize_start(self.battle_id, self.generation)
        for index in range(2):
            command = self.control(index, Opcode.START, 3)
            self.call("started", index, command, replace(command, data=self.query(index, 3, 25, 1)))
            for part in range(3):
                self.call("verify_startup", index, self.kind.PARTY_0 + part, 3 + part,
                          self.descriptor(index).party[part * 200:part * 200 + 200])
        self.desk.authorize_running(self.battle_id, self.generation)
        for index in range(2):
            command = self.control(index, Opcode.QUERY, 4)
            descriptor = self.descriptor(index)
            self.call("finish", index, command, replace(command, data=self.query(index, 3, 57, 1, outcome)),
                      outcome=outcome, party=descriptor.party, party_count=descriptor.party_count)
        result = None
        for index in range(2):
            command = self.control(index, Opcode.RELEASE, 4, struct.pack("<II", self.descriptor(index).party_crc32, outcome))
            result = self.call("released", index, command, replace(command, data=b""))
        self.assertEqual(result["state"], "closed")

    async def propose_and_accept(self, amount=5000):
        reply = await self.world_rpc(0, "wager_set", battle_id=self.battle_id, amount=amount)
        self.assertEqual(reply["type"], "world_result", reply)
        self.assertEqual(reply["result"]["wager"]["accepted"], [self.pid(0)])
        self.assertEqual(reply["result"]["money"], 20_000)
        await self.world(1, lambda w: w["notice"] and "WAGER $5,000" in w["notice"]["text"])
        reply = await self.world_rpc(1, "wager_accept", battle_id=self.battle_id, amount=amount)
        self.assertEqual(sorted(reply["result"]["wager"]["accepted"]), sorted([self.pid(0), self.pid(1)]))

    async def test_wager_must_be_accepted_before_start(self):
        self.accept_and_register()
        reply = await self.world_rpc(0, "wager_set", battle_id=self.battle_id, amount=5000)
        self.assertEqual(reply["type"], "world_result")
        self.bind_and_prepare()
        with self.assertRaises(BattleError) as caught:
            self.desk.authorize_start(self.battle_id, self.generation)
        self.assertEqual(caught.exception.code, "wager_pending")
        reply = await self.world_rpc(1, "wager_accept", battle_id=self.battle_id, amount=4000)
        self.assertEqual(reply["code"], "wager_changed")

    async def test_unaffordable_and_out_of_range_wagers_are_refused(self):
        self.money[self.pid(1)] = 1000
        reply = await self.world_rpc(0, "wager_set", battle_id=self.battle_id, amount=5000)
        self.assertEqual(reply["code"], "insufficient_funds")
        reply = await self.world_rpc(0, "wager_set", battle_id=self.battle_id, amount=50)
        self.assertEqual(reply["code"], "invalid_wager")
        reply = await self.world_rpc(2, "wager_get", battle_id=self.battle_id)
        self.assertEqual(reply["code"], "no_battle")

    async def test_cancelled_challenge_voids_the_wager(self):
        await self.propose_and_accept()
        self.call("cancel", 0)
        self.assertTrue(any("WAGER CANCELED" in text for text in self.notices_for(1)), self.notices_for(1))
        self.assertEqual(self.server.wagers.view(self.battle_id)["state"], "void")

    async def test_closed_win_moves_the_stake_exactly_once_through_both_games(self):
        await self.propose_and_accept()
        self.accept_and_register()
        self.bind_and_prepare()
        self.start_and_finish(outcome=2)  # the odd battle slot wins
        self.assertEqual(self.server.wagers.view(self.battle_id)["state"], "settled")
        order = [self.pids.index(player) for player in self.view["players"]]  # battle slots are sorted ids
        loser, winner = order[0], order[1]
        # Each game sees only its own adjustment, and only once it reports its save sequence.
        await self.presence(loser, x=7, wallet_seq=0)
        frame = await self.world(loser, lambda w: w["wallet"] is not None)
        self.assertEqual(frame["wallet"], {"seq": 1, "delta": -5000})
        await self.presence(winner, x=8, wallet_seq=0)
        self.assertIsNone((await self.world(winner))["wallet"])  # nothing collected yet
        receipt = await self.world_rpc(loser, "wallet_applied", seq=1, amount=5000)
        self.assertEqual(receipt["result"], {"seq": 1})
        frame = await self.world(winner, lambda w: w["wallet"] is not None)
        self.assertEqual(frame["wallet"], {"seq": 1, "delta": 5000})
        # After applying, the loser's save reports sequence 1: nothing more to apply.
        await self.presence(loser, x=9, wallet_seq=1)
        self.assertIsNone((await self.world(loser, lambda w: w["wallet"] is None))["wallet"])
        # A repeated receipt (reconnect) never credits twice.
        await self.world_rpc(loser, "wallet_applied", seq=1, amount=5000)
        self.assertEqual([row["delta"] for row in self.server.wagers.pending_for(self.pid(winner))], [5000])

    async def test_draw_moves_nothing(self):
        await self.propose_and_accept()
        self.accept_and_register()
        self.bind_and_prepare()
        self.start_and_finish(outcome=3)
        await self.presence(0, x=7, wallet_seq=0)
        self.assertIsNone((await self.world(0))["wallet"])
        self.assertEqual(self.server.wagers.pending_for(self.pid(0)), [])


class CoopGymRequestTests(WorldServerTests):
    teams = True

    async def form_team(self, a=0, b=1):
        invitation = self.server.team_desk.invite(*self.actor(a), self.pid(b), str(uuid4()))
        self.server.team_desk.accept(*self.actor(b), invitation["invitation_id"], invitation["generation"])

    async def test_refusals_post_a_banner_to_the_requester(self):
        reply = await self.world_rpc(0, "gym_coop", gym=1)
        self.assertEqual((reply["type"], reply["code"]), ("world_error", "no_teammate"))
        self.assertTrue(any("Form a team" in text for text in self.notices_for(0)))
        self.assertFalse(any("Form a team" in text for text in self.notices_for(1)))
        await self.form_team()
        frame = await self.world(0, lambda w: w["teammate"] == self.pid(1))
        self.assertEqual(frame["teammate"], self.pid(1))
        await self.presence(0, x=5, map_number=3)
        await self.presence(1, x=6, map_number=4)
        reply = await self.world_rpc(0, "gym_coop", gym=1)
        self.assertEqual(reply["code"], "teammate_away")

    async def test_teammates_in_the_same_gym_receive_a_coop_challenge(self):
        await self.form_team()
        await self.presence(0, x=5, map_number=3)
        await self.presence(1, x=6, map_number=3)
        reply = await self.world_rpc(0, "gym_coop", gym=1)
        self.assertEqual(reply["type"], "world_result", reply)
        battle_id = reply["result"]["battle_id"]
        view = self.desk.status(*self.actor(1), battle_id)
        self.assertEqual((view["mode"], view["gym"], view["players"]), (4, 1, [self.pid(0), self.pid(1)]))
        self.assertTrue(any("TEAM GYM vs ROXANNE!" in text for text in self.notices_for(1)), self.notices_for(1))
        self.assertTrue(any("Open PLAYERS" in text for text in self.notices_for(0)), self.notices_for(0))
        # A co-op Gym battle never carries a wager.
        reply = await self.world_rpc(0, "wager_set", battle_id=battle_id, amount=5000)
        self.assertEqual(reply["code"], "coop_gym")
        # The teammate consents exactly like any native challenge.
        accepted = self.desk.accept(*self.actor(1), battle_id, view["generation"], view["fingerprint"])
        self.assertEqual(sorted(accepted["consent"]), sorted([self.pid(0), self.pid(1)]))
        # A second request while one is pending is refused (one lifecycle per trainer).
        reply = await self.world_rpc(1, "gym_coop", gym=1)
        self.assertEqual(reply["type"], "world_error")


if __name__ == "__main__":
    unittest.main()


class SharedSpawnNetworkTests(WorldServerTests):
    """Phase 3 over real loopback TCP: every game on a map receives the same
    host-chosen wild Pokemon, claims race through the host, and a catch
    removes the Pokemon from every game's world frame."""

    async def on_route101(self, index, x, y):
        message = dict(type="presence", session_epoch=self.actors[index].lease, seq=self.seq(index), map_epoch=0,
                       map_group=0, map_number=16, x=x, y=y, direction=1, elevation=3,
                       avatar_gender=0, activity="overworld", weather=3)
        await self.actors[index].send(message)
        await wait_until(lambda: (self.server.sessions[self.pid(index)].presence or {}).get("x") == x)

    def spot(self):
        tiles = self.server.shared_world.spawn_director.habitat("0.16")
        xs = sorted({x for x, _ in tiles})
        ys = sorted({y for _, y in tiles})
        return xs[len(xs) // 2], ys[len(ys) // 2]

    async def spawns(self, index, predicate):
        return (await self.world(index, lambda w: w["spawns"] is not None and predicate(w["spawns"])))["spawns"]

    async def test_two_players_on_route_101_see_the_same_pokemon_and_race_for_one(self):
        x, y = self.spot()
        await self.on_route101(0, x, y)
        await self.on_route101(1, x + 1, y)
        self.assertEqual(self.server.sessions[self.pid(0)].presence["weather"], 3)
        for _ in range(5):
            self.server.shared_world.spawn_director._last_update = float("-inf")
            self.server.shared_world.tick_spawns({pid: s.presence for pid, s in self.server.sessions.items()})
        first = await self.spawns(0, lambda view: len(view["slots"]) >= 3)
        second = await self.spawns(1, lambda view: [s["spawn_id"] for s in view["slots"]]
                                   == [s["spawn_id"] for s in first["slots"]])
        strip = lambda view: [{k: v for k, v in s.items() if k not in ("fresh", "seconds_left")} for s in view["slots"]]
        self.assertEqual(strip(first), strip(second))
        target = first["slots"][0]["spawn_id"]
        # Both games claim at once: the host answers exactly one "granted".
        replies = await asyncio.gather(
            self.world_rpc(0, "spawn_action", action="claim", spawn_id=target, result=None, seq=1),
            self.world_rpc(1, "spawn_action", action="claim", spawn_id=target, result=None, seq=1))
        outcomes = sorted(reply["result"]["outcome"] for reply in replies)
        self.assertEqual(outcomes, ["busy", "granted"])
        winner = 0 if replies[0]["result"]["outcome"] == "granted" else 1
        loser = 1 - winner
        view = await self.spawns(loser, lambda v: any(s["spawn_id"] == target and s["busy"] for s in v["slots"]))
        self.assertTrue(next(s for s in view["slots"] if s["spawn_id"] == target)["busy"])
        caught = await self.world_rpc(winner, "spawn_action", action="result", spawn_id=target,
                                      result="caught", seq=2)
        self.assertEqual(caught["result"]["outcome"], "consumed")
        for index in (0, 1):
            await self.spawns(index, lambda v: all(s["spawn_id"] != target for s in v["slots"]))
        again = await self.world_rpc(loser, "spawn_action", action="claim", spawn_id=target, result=None, seq=2)
        self.assertEqual(again["result"]["outcome"], "gone")

    async def test_a_player_on_another_map_gets_its_own_empty_view(self):
        x, y = self.spot()
        await self.on_route101(0, x, y)
        await self.presence(1, x=6, map_number=9)
        self.server.shared_world.tick_spawns({pid: s.presence for pid, s in self.server.sessions.items()})
        view = await self.spawns(1, lambda v: True)
        self.assertEqual((view["map_group"], view["map_number"], view["shared"], view["slots"]), (0, 9, False, []))

    async def test_spawn_requests_are_validated(self):
        with self.assertRaises(ConnectionError):
            await self.world_rpc(0, "spawn_action", action="steal", spawn_id=1, result=None, seq=1)
