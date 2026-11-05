"""Location privacy (docs/pokenav-privacy.md). Since the owner's decision of 2026-11-05 a player's precise place reaches the other
players only with their explicit permission: private by default, a launcher checkbox and the game's PokeNav toggle editing one
stored choice, and the host showing nobody else (its own operator's game included) the place of a player who has not opted in."""
from __future__ import annotations

import json
import secrets
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from emerald_multiplayer import privacy
from emerald_multiplayer.companion import Companion, CompanionConfig
from emerald_multiplayer.launcher_session import LauncherSessionError
from emerald_multiplayer.protocol import PROTOCOL_VERSION, ProtocolError, validate_presence
from test_companion import WORLD_FIELDS, make_files, make_pose
from test_world_server import WorldServerTests
import test_companion as companion_fixture
import test_launcher_session as session_fixture

# What the earlier builds (Update 24 to 2026-11-05) wrote, byte for byte, and only when the player pressed the PokeNav toggle.
EARLIER_SHARE = b'{"format":"emerald-privacy-settings-v1","share_location":true}\n'
EARLIER_HIDE = b'{"format":"emerald-privacy-settings-v1","share_location":false}\n'


def presence(group=0, number=9, **extra):
    return {"session_epoch": 1, "seq": 1, "map_epoch": 0, "map_group": group, "map_number": number, "x": 6, "y": 11,
            "direction": 1, "elevation": 0, "avatar_gender": 0, "activity": "overworld", "movement_mode": "walk",
            "weather": 3, **extra}


def place(value):
    return value["map_group"], value["map_number"], value["x"], value["y"]


def labels(menu):
    return [row.label for row in menu.screen.rows]


async def click(test, menu, label):
    """Press a row of the game's Players menu as the game does (PlayerMenu.choose with the screen's revision)."""
    row = next((r for r in menu.screen.rows if r.label == label and r.action), None)
    test.assertIsNotNone(row, labels(menu))
    return await menu.choose(menu.screen.revision, row.action)


class RedactionTests(unittest.TestCase):
    def test_a_player_who_never_chose_is_nowhere_for_viewers_on_other_maps(self):
        never = presence()                                       # no share_location at all: no permission
        self.assertTrue(privacy.is_hidden(never))
        shown = privacy.redact(never, presence(0, 11))
        self.assertEqual(place(shown), (255, 255, 0, 0))
        self.assertNotIn("weather", shown)                       # the weather at their position says where they are
        self.assertTrue(privacy.is_redacted(shown))
        self.assertEqual(never["map_number"], 9)                 # the original is not touched
        self.assertEqual(privacy.redact(never, None)["map_number"], 255)    # a viewer with no place yet learns nothing
        self.assertFalse(privacy.is_hidden(None))                # no presence yet: no place to hide

    def test_an_explicit_no_is_hidden_the_same_way(self):
        self.assertEqual(place(privacy.redact(presence(share_location=False), presence(0, 11))), (255, 255, 0, 0))

    def test_only_an_explicit_permission_shows_the_place_unchanged(self):
        shared = presence(share_location=True)
        self.assertTrue(privacy.shares(shared))
        self.assertFalse(privacy.is_hidden(shared))
        self.assertIs(privacy.redact(shared, presence(0, 11)), shared)
        self.assertIs(privacy.for_readout(shared), shared)
        for value in (False, None, 1, "true"):
            self.assertFalse(privacy.shares(presence(share_location=value)), value)

    def test_a_viewer_on_the_same_map_receives_the_avatar_but_never_a_readout(self):
        never = presence()
        self.assertIs(privacy.redact(never, presence(0, 9)), never)          # the shared world: their avatar on screen
        self.assertTrue(privacy.is_redacted(privacy.for_readout(never)))     # the PokeNav text: "Location hidden"

    def test_you_always_see_yourself(self):
        never = presence()
        self.assertIs(privacy.redact(never, presence(0, 11), own=True), never)
        self.assertIs(privacy.for_readout(never, own=True), never)


class WireTests(unittest.TestCase):
    def test_the_choice_is_a_boolean_and_its_absence_is_no_permission(self):
        self.assertNotIn("share_location", validate_presence({"type": "presence", **presence()}, 1))
        for value in (True, False):
            self.assertIs(validate_presence({"type": "presence", **presence(share_location=value)}, 1)["share_location"], value)
        for bad in (0, 1, "true", "false", None):
            with self.subTest(bad=bad), self.assertRaises(ProtocolError):
                validate_presence({"type": "presence", **presence(share_location=bad)}, 1)


class SettingFileTests(unittest.TestCase):
    def test_a_new_profile_is_private_and_loading_writes_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertFalse(privacy.load(folder))
            self.assertFalse(privacy.load(Path(folder) / "never-created"))
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_an_explicit_choice_round_trips(self):
        with tempfile.TemporaryDirectory() as folder:
            privacy.save(folder, True)
            self.assertTrue(privacy.load(folder))
            privacy.save(folder, False)
            self.assertFalse(privacy.load(folder))

    def test_migration_from_the_earlier_sharing_default(self):
        """The earlier builds shared a player who never chose (no file) and wrote the file only from the toggle."""
        with tempfile.TemporaryDirectory() as folder:
            never, shared, hidden = (Path(folder) / name for name in ("never", "turned-back-on", "turned-off"))
            for directory in (never, shared, hidden):
                directory.mkdir()
            (shared / privacy.FILENAME).write_bytes(EARLIER_SHARE)
            (hidden / privacy.FILENAME).write_bytes(EARLIER_HIDE)
            self.assertFalse(privacy.load(never))        # shared before only by the old default: private now
            self.assertTrue(privacy.load(shared))        # the player turned it off and on again: their permission stands
            self.assertFalse(privacy.load(hidden))
            self.assertEqual((shared / privacy.FILENAME).read_bytes(), EARLIER_SHARE)    # nothing rewritten
            privacy.save(shared, True)
            self.assertEqual((shared / privacy.FILENAME).read_bytes(), EARLIER_SHARE)    # an earlier build reads ours

    def test_an_unreadable_choice_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / privacy.FILENAME
            for raw in (b"{not json", json.dumps({"format": "other", "share_location": True}).encode(),
                        json.dumps({"format": "emerald-privacy-settings-v1", "share_location": 1}).encode(), b"\xff\xfe"):
                with self.subTest(raw=raw):
                    path.write_bytes(raw)
                    self.assertFalse(privacy.load(folder))      # never shared by accident


class CompanionStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        rom, manifest = make_files(self.temp.name)
        self.config = CompanionConfig(rom, manifest, str(uuid.UUID(int=1)), "Player", secrets.token_bytes(32))

    def test_a_companion_is_private_until_its_profile_says_otherwise(self):
        companion = Companion(self.config)
        self.assertIs(companion.share_location, False)

    def test_sharing_starts_only_once_kept_and_going_private_at_once(self):
        companion = Companion(self.config)
        companion._privacy_directory = Path(self.temp.name) / "profile"
        companion.set_share_location(True)
        self.assertTrue(companion.share_location)
        self.assertTrue(privacy.load(companion._privacy_directory))
        with patch("emerald_multiplayer.live_checkpoint.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                companion.set_share_location(False)
            self.assertFalse(companion.share_location)             # private at once although it could not be kept
            with self.assertRaises(OSError):
                companion.set_share_location(True)
            self.assertFalse(companion.share_location)             # never shared without the kept permission

    def test_a_peer_turning_real_or_hidden_without_new_counters_is_not_a_stale_pose(self):
        companion = Companion(self.config)
        companion.connected, companion.session_epoch = True, 1
        own = {"player_id": self.config.player_id, "display_name": "Me", "session_epoch": 1, "appearance": None,
               "presence": {"session_epoch": 1, "seq": 1, "map_epoch": 0, **make_pose(map_number=7).network_fields(True)}}
        real = {"session_epoch": 1, "seq": 4, "map_epoch": 2, **make_pose(map_number=1, x=9).network_fields(True),
                "share_location": False}
        hidden = privacy.redact(real, own["presence"])

        def world(seq, peer):
            return {"type": "world", "protocol": PROTOCOL_VERSION, "world_seq": seq, **WORLD_FIELDS, "players": [
                own, {"player_id": str(uuid.UUID(int=2)), "display_name": "Peer", "session_epoch": 1, "appearance": None,
                      "presence": peer}]}

        companion._apply_world(world(1, hidden))
        companion._apply_world(world(2, real))        # this player walked onto the peer's map: the avatar appears
        companion._apply_world(world(3, hidden))      # and left it again
        peer = companion.snapshot.peers[0].pose
        self.assertEqual((peer.map_group, peer.map_number, peer.x), (255, 255, 0))
        # A real stale pose is still refused: the same view moved to another map without a new map epoch.
        companion._apply_world(world(4, real))
        with self.assertRaises(ProtocolError):
            companion._apply_world(world(5, {**real, "map_number": 3}))


class CompanionPrivacyTests(unittest.IsolatedAsyncioTestCase):
    """Two real companions on a real host, each with a scripted game bridge (as tests/test_companion.py), whose players have
    made no choice (share_location=None: the companion's own default)."""
    asyncSetUp = companion_fixture.CompanionIntegrationTests.asyncSetUp
    asyncTearDown = companion_fixture.CompanionIntegrationTests.asyncTearDown
    add_companion = companion_fixture.CompanionIntegrationTests.add_companion
    add_bridge = companion_fixture.CompanionIntegrationTests.add_bridge

    async def two_on_different_maps(self):
        first, second = await self.add_companion(1, share_location=None), await self.add_companion(2, share_location=None)
        a, b = await self.add_bridge(first), await self.add_bridge(second)
        await a.pose(make_pose(x=11, map_number=1))
        await b.pose(make_pose(x=7, map_number=2))
        return first, second, a, b

    async def test_games_whose_players_never_chose_receive_no_place_of_each_other(self):
        first, second, a, b = await self.two_on_different_maps()
        seen_by_a = await a.snapshot(lambda s: len(s.peers) == 1 and s.peers[0].pose.map_number == 255)
        seen_by_b = await b.snapshot(lambda s: len(s.peers) == 1 and s.peers[0].pose.map_number == 255)
        for seen in (seen_by_a, seen_by_b):
            pose = seen.peers[0].pose
            self.assertEqual((pose.map_group, pose.x, pose.y), (255, 0, 0))
        # The host keeps the real place for what it runs (presence, claims, spawns) and shows it to nobody else.
        held = self.server.sessions[first.config.player_id].presence
        self.assertEqual((held["map_number"], held["x"], held["share_location"]), (1, 11, False))

    async def test_walking_onto_a_private_players_map_shows_their_avatar_on_the_same_connection(self):
        first, second, a, b = await self.two_on_different_maps()
        await b.snapshot(lambda s: s.peers and s.peers[0].pose.map_number == 255)
        epoch = second.session_epoch
        await b.pose(make_pose(frame=2, epoch=1, map_number=1, x=3))       # B walks onto A's map
        seen = await b.snapshot(lambda s: s.peers and s.peers[0].pose.map_number == 1)
        self.assertEqual((seen.peers[0].pose.x, seen.peers[0].pose.activity), (11, 1))     # A, drawn where A stands
        await b.pose(make_pose(frame=3, epoch=2, map_number=2, x=4))       # and leaves it
        await b.snapshot(lambda s: s.peers and s.peers[0].pose.map_number == 255)
        # Before the change a viewer's companion refused that frame ("stale_server_presence") and reconnected.
        self.assertTrue(second.connected)
        self.assertEqual(second.session_epoch, epoch)

    async def test_opting_in_shows_the_place_to_everybody_at_once_and_opting_out_hides_it(self):
        first, second, a, b = await self.two_on_different_maps()
        await b.snapshot(lambda s: s.peers and s.peers[0].pose.map_number == 255)
        epoch = second.session_epoch
        first.set_share_location(True)
        seen = await b.snapshot(lambda s: s.peers and s.peers[0].pose.map_number == 1)
        self.assertEqual(seen.peers[0].pose.x, 11)
        self.assertIs(self.server.sessions[first.config.player_id].presence["share_location"], True)
        first.set_share_location(False)
        await b.snapshot(lambda s: s.peers and s.peers[0].pose.map_number == 255)
        self.assertEqual((second.connected, second.session_epoch), (True, epoch))


class PrivacyOverTheWireTests(WorldServerTests):
    """Four real connections to the host. The host's own game joins its world exactly like these (there is no operator
    view): what one of them is sent is what the host's operator sees of the others."""

    async def place(self, index, share=None, **kwargs):
        message = dict(type="presence", session_epoch=self.actors[index].lease, seq=self.seq(index), map_epoch=0, map_group=0,
                       map_number=kwargs.get("map_number", 9), x=kwargs.get("x", 6), y=11, direction=1, elevation=0,
                       avatar_gender=0, activity="overworld", weather=5)
        if share is not None:
            message["share_location"] = share
        await self.actors[index].send(message)
        from test_battle_arbitration import wait_until
        await wait_until(lambda: (self.server.sessions[self.pid(index)].presence or {}).get("x") == message["x"]
                         and (self.server.sessions[self.pid(index)].presence or {}).get("share_location") == share)

    def entry(self, world, index):
        return next(p for p in world["players"] if p["player_id"] == self.pid(index))

    def nav(self, world):
        return {p["player_id"]: p for p in world["extras"]["nav"]["players"]}

    def placed(self, *indices):
        """A world view built once these players' places reached the host: one built between two presences (the
        viewer's own still on its way) is no answer to what the viewer sees, so it is waited past, not judged."""
        return lambda world: all(self.entry(world, index)["presence"] is not None for index in indices)

    async def test_a_player_who_never_chose_reaches_the_others_only_as_an_avatar_on_their_own_map(self):
        await self.place(0, None, map_number=9)
        await self.place(1, None, map_number=11)
        await self.place(2, None, map_number=9)        # standing on 0's map
        b = await self.world(1, self.placed(0, 1))
        self.assertEqual(place(self.entry(b, 0)["presence"]), (255, 255, 0, 0))
        self.assertNotIn("weather", self.entry(b, 0)["presence"])
        text = json.dumps(b)
        self.assertNotIn('"map_number": 9,', text.split(self.pid(0))[1].split("appearance")[0])
        self.assertEqual(self.nav(b)[self.pid(0)], {"player_id": self.pid(0), "place": privacy.HIDDEN_PLACE, "weather": None})
        self.assertNotEqual(self.nav(b)[self.pid(1)]["place"], privacy.HIDDEN_PLACE)      # your own place, always
        c = await self.world(2, self.placed(0, 2))
        self.assertEqual(place(self.entry(c, 0)["presence"]), (0, 9, 6, 11))             # the avatar on the same screen
        self.assertEqual(self.nav(c)[self.pid(0)]["place"], privacy.HIDDEN_PLACE)          # but never a readout
        a = await self.world(0, self.placed(0))
        self.assertEqual(self.entry(a, 0)["presence"]["map_number"], 9)                   # you see yourself
        self.assertNotEqual(self.nav(a)[self.pid(0)]["place"], privacy.HIDDEN_PLACE)
        self.assertEqual(self.nav(a)[self.pid(2)]["place"], privacy.HIDDEN_PLACE)          # 2 never chose either

    async def test_an_explicit_no_is_hidden_the_same_way(self):
        await self.place(0, False, map_number=9)
        await self.place(1, None, map_number=11)
        b = await self.world(1, self.placed(0, 1))
        self.assertEqual(place(self.entry(b, 0)["presence"]), (255, 255, 0, 0))
        self.assertEqual(self.nav(b)[self.pid(0)]["place"], privacy.HIDDEN_PLACE)

    async def test_an_opted_in_player_appears_to_everybody_as_before(self):
        await self.place(0, True, map_number=9)
        await self.place(1, None, map_number=11)
        b = await self.world(1, self.placed(0, 1))
        self.assertEqual(place(self.entry(b, 0)["presence"]), (0, 9, 6, 11))
        self.assertEqual(self.entry(b, 0)["presence"]["weather"], 5)
        self.assertNotEqual(self.nav(b)[self.pid(0)]["place"], privacy.HIDDEN_PLACE)
        a = await self.world(0, self.placed(0, 1))
        self.assertEqual(place(self.entry(a, 1)["presence"]), (255, 255, 0, 0))           # 1 has not opted in
        await self.place(2, True, map_number=12)
        await self.place(3, True, map_number=13)
        a = await self.world(0, self.placed(0, 1, 2, 3))
        self.assertEqual([self.entry(a, i)["presence"]["map_number"] for i in range(4)], [9, 255, 12, 13])

    async def test_turning_it_on_and_off_again(self):
        await self.place(0, None, map_number=9)
        await self.place(1, None, map_number=11)
        await self.world(1, lambda w: (self.entry(w, 0)["presence"] or {}).get("map_number") == 255)
        await self.place(0, True, map_number=9, x=7)
        b = await self.world(1, lambda w: (self.entry(w, 0)["presence"] or {}).get("map_number") == 9)
        self.assertIs(self.entry(b, 0)["presence"]["share_location"], True)
        await self.place(0, False, map_number=9, x=8)
        await self.world(1, lambda w: (self.entry(w, 0)["presence"] or {}).get("map_number") == 255)

    async def test_a_private_world_event_claimant_is_somebody_to_everybody_else(self):
        world = self.server.shared_world
        world.locations = [{"name": "Route 101", "map_group": 0, "map_number": 16, "x": 9, "y": 9,
                            "min_level": 0, "themes": []}]
        event = world.spawn_event(progression_level=10, category="rare")
        await self.place(0, None, map_number=16)
        self.assertEqual((await self.world_rpc(0, "world_action", action="claim", event_id=event["event_id"], result=None,
                                               seq=1))["result"]["outcome"], "granted")
        b = await self.world(1, lambda w: w["event"] is not None and w["event"]["claimant"] is not None)
        self.assertEqual(b["event"]["claimant"], privacy.SOMEBODY)           # taken, by nobody it names
        self.assertNotIn(self.pid(0), json.dumps(b["event"]))
        a = await self.world(0, lambda w: w["event"] is not None and w["event"]["claimant"] is not None)
        self.assertEqual(a["event"]["claimant"], self.pid(0))               # the claimant's own game knows it is theirs
        await self.place(0, True, map_number=16, x=7)
        b = await self.world(1, lambda w: w["event"] is not None and w["event"]["claimant"] == self.pid(0))
        self.assertEqual((b["event"]["map_group"], b["event"]["map_number"]), (0, 16))


class MenuToggleTests(unittest.IsolatedAsyncioTestCase):
    """PokeNav > World > Players and weather > Share my location."""

    async def test_the_toggle_is_off_by_default_flips_and_is_kept(self):
        from test_secret_bases import FakeMenuCompanion
        from emerald_multiplayer.player_menu import PlayerMenu

        class Companion(FakeMenuCompanion):
            def set_share_location(self, share):
                self.share_location = share
                self.saved = share

        for companion in (FakeMenuCompanion(), Companion()):         # a companion that knows no choice is private too
            menu = PlayerMenu(companion)
            await menu.refresh()
            await click(self, menu, "World and my base")
            await click(self, menu, "Players and weather")
            self.assertIn("Share my location: OFF", labels(menu))
            self.assertIn("Location hidden", menu.screen.status)
        await click(self, menu, "Share my location: OFF")
        self.assertIs(companion.saved, True)
        self.assertIn("Share my location: ON", labels(menu))
        await click(self, menu, "Share my location: ON")
        self.assertIs(companion.saved, False)
        self.assertTrue(all(len(label) <= 25 for label in labels(menu)))


class LauncherCheckboxSessionTests(unittest.IsolatedAsyncioTestCase):
    """The launcher session behind the checkbox (the Tk launcher's and the in-game menu's), on a real host world."""
    setUp = session_fixture.LauncherSessionTests.setUp
    asyncTearDown = session_fixture.LauncherSessionTests.asyncTearDown
    session = session_fixture.LauncherSessionTests.session

    def profile(self, slot=0):
        return self.private / "players" / self.host.world_id / self.host.accounts[slot].player_id

    async def test_the_checkbox_and_the_pokenav_toggle_read_and_write_one_choice(self):
        from test_secret_bases import FakeMenuCompanion
        from emerald_multiplayer.player_menu import PlayerMenu
        session = self.session()
        async with session.open():
            real = session._companion
            directory = session.profile_directory
            self.assertEqual(directory, self.profile())
            self.assertIs(session.status.share_location, False)               # a character that never chose: private
            self.assertFalse((directory / privacy.FILENAME).exists())

            class Game(FakeMenuCompanion):                                     # the game's PokeNav over the real companion
                share_location = property(lambda self: real.share_location)

                def set_share_location(self, share):
                    real.set_share_location(share)

            menu = PlayerMenu(Game())
            await menu.refresh()
            await click(self, menu, "World and my base")
            await click(self, menu, "Players and weather")
            self.assertIn("Share my location: OFF", labels(menu))

            session.set_share_location(True)                                  # the launcher's checkbox
            self.assertTrue(privacy.load(directory))
            self.assertTrue(real.share_location)                              # what the next presence says
            self.assertIs(session.status.share_location, True)
            await menu.refresh()
            self.assertIn("Share my location: ON", labels(menu))             # shows in the game

            await click(self, menu, "Share my location: ON")                  # the game's toggle
            self.assertFalse(privacy.load(directory))
            self.assertIs(session.status.share_location, False)               # shows in the launcher

            for bad in (1, "yes", None):
                with self.assertRaises(LauncherSessionError) as caught:
                    session.set_share_location(bad)
                self.assertEqual(caught.exception.code, "invalid_configuration")
            with patch("emerald_multiplayer.live_checkpoint.os.replace", side_effect=OSError("private path")):
                with self.assertRaises(LauncherSessionError) as caught:
                    session.set_share_location(True)
            self.assertEqual(caught.exception.code, "privacy_unavailable")
            self.assertNotIn("private path", str(caught.exception))
            self.assertIs(session.status.share_location, False)               # not shared without the kept choice
        with self.assertRaises(LauncherSessionError) as caught:
            session.set_share_location(True)
        self.assertEqual(caught.exception.code, "session_closed")

    async def test_a_character_that_chose_to_share_before_keeps_sharing(self):
        directory = self.profile()
        directory.mkdir(parents=True)
        (directory / privacy.FILENAME).write_bytes(EARLIER_SHARE)
        session = self.session()
        async with session.open():
            self.assertIs(session.status.share_location, True)
            self.assertTrue(session._companion.share_location)
        self.assertEqual((directory / privacy.FILENAME).read_bytes(), EARLIER_SHARE)


if __name__ == "__main__":
    unittest.main()
