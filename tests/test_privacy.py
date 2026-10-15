"""Update 24: the PokeNav location privacy setting. Default: sharing. Hidden: no other player's world view carries the place."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from emerald_multiplayer import privacy
from emerald_multiplayer.protocol import ProtocolError, validate_presence
from test_world_server import WorldServerTests


def presence(group=0, number=9, **extra):
    return {"session_epoch": 1, "seq": 1, "map_epoch": 0, "map_group": group, "map_number": number, "x": 6, "y": 11,
            "direction": 1, "elevation": 0, "avatar_gender": 0, "activity": "overworld", "movement_mode": "walk",
            "weather": 3, **extra}


class RedactionTests(unittest.TestCase):
    def test_sharing_is_the_default_and_changes_nothing(self):
        shared = presence()
        self.assertIs(privacy.redact(shared, presence(0, 11)), shared)
        self.assertIs(privacy.redact(None, presence()), None)
        self.assertFalse(privacy.is_hidden(shared))

    def test_a_hidden_player_is_nowhere_for_viewers_on_other_maps(self):
        hidden = presence(share_location=False)
        shown = privacy.redact(hidden, presence(0, 11))
        self.assertEqual((shown["map_group"], shown["map_number"], shown["x"], shown["y"]), (255, 255, 0, 0))
        self.assertNotIn("weather", shown)                       # the weather at their position says where they are
        self.assertTrue(privacy.is_redacted(shown))
        self.assertEqual(hidden["map_number"], 9)                # the original is not touched
        self.assertEqual(privacy.redact(hidden, None)["map_number"], 255)   # a viewer with no place yet learns nothing

    def test_a_viewer_on_the_same_map_sees_them_because_they_are_on_the_screen(self):
        hidden = presence(share_location=False)
        self.assertIs(privacy.redact(hidden, presence(0, 9)), hidden)

    def test_you_always_see_yourself(self):
        hidden = presence(share_location=False)
        self.assertIs(privacy.redact(hidden, presence(0, 11), own=True), hidden)

    def test_the_wire_field_is_only_ever_false(self):
        self.assertNotIn("share_location", validate_presence({"type": "presence", **presence()}, 1))
        self.assertIs(validate_presence({"type": "presence", **presence(share_location=False)}, 1)["share_location"], False)
        for bad in (True, 0, 1, "false", None):
            with self.assertRaises(ProtocolError):
                validate_presence({"type": "presence", **presence(share_location=bad)}, 1)


class SettingFileTests(unittest.TestCase):
    def test_default_on_round_trip_and_failing_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertTrue(privacy.load(folder))                                    # no file: sharing
            privacy.save(folder, False)
            self.assertFalse(privacy.load(folder))
            privacy.save(folder, True)
            self.assertTrue(privacy.load(folder))
            (Path(folder) / privacy.FILENAME).write_text("{not json")
            self.assertFalse(privacy.load(folder))                                    # unreadable: hidden, never shared by accident
            (Path(folder) / privacy.FILENAME).write_text(json.dumps({"format": "other", "share_location": True}))
            self.assertFalse(privacy.load(folder))


class PrivacyOverTheWireTests(WorldServerTests):
    """Four real connections: A hides; B is elsewhere, C is on A's map, D has not said where it is."""

    async def hide(self, index, hidden=True, **kwargs):
        message = dict(type="presence", session_epoch=self.actors[index].lease, seq=self.seq(index), map_epoch=0, map_group=0,
                       map_number=kwargs.get("map_number", 9), x=kwargs.get("x", 6), y=11, direction=1, elevation=0,
                       avatar_gender=0, activity="overworld", weather=5)
        if hidden:
            message["share_location"] = False
        await self.actors[index].send(message)
        from test_battle_arbitration import wait_until
        await wait_until(lambda: (self.server.sessions[self.pid(index)].presence or {}).get("x") == message["x"])

    def entry(self, world, index):
        return next(p for p in world["players"] if p["player_id"] == self.pid(index))

    async def test_nobody_else_receives_a_hidden_players_place_but_those_on_the_same_map(self):
        await self.hide(0, True, map_number=9)
        await self.hide(1, False, map_number=11)
        await self.hide(2, False, map_number=9)
        b = await self.world(1, lambda w: self.entry(w, 0)["presence"] is not None)
        self.assertEqual((self.entry(b, 0)["presence"]["map_group"], self.entry(b, 0)["presence"]["map_number"]), (255, 255))
        text = json.dumps(b)
        self.assertNotIn('"map_number": 9,', text.split(self.pid(0))[1].split("appearance")[0])
        nav = {p["player_id"]: p for p in b["extras"]["nav"]["players"]}
        self.assertEqual(nav[self.pid(0)], {"player_id": self.pid(0), "place": privacy.HIDDEN_PLACE, "weather": None})
        self.assertNotEqual(nav[self.pid(1)]["place"], privacy.HIDDEN_PLACE)
        c = await self.world(2, lambda w: self.entry(w, 0)["presence"] is not None)
        self.assertEqual(self.entry(c, 0)["presence"]["map_number"], 9)             # on the same screen anyway
        a = await self.world(0, lambda w: self.entry(w, 0)["presence"] is not None)
        self.assertEqual(self.entry(a, 0)["presence"]["map_number"], 9)             # you see yourself
        self.assertFalse(any(p["place"] == privacy.HIDDEN_PLACE for p in a["extras"]["nav"]["players"] if p["player_id"] == self.pid(0)))

    async def test_turning_it_off_again_shares_the_place_with_everybody(self):
        await self.hide(0, True, map_number=9)
        await self.hide(1, False, map_number=11)
        await self.world(1, lambda w: self.entry(w, 0)["presence"]["map_number"] == 255)
        await self.hide(0, False, map_number=9, x=7)
        b = await self.world(1, lambda w: self.entry(w, 0)["presence"]["map_number"] == 9)
        self.assertNotIn("share_location", self.entry(b, 0)["presence"])

    async def test_the_default_sends_everyone_everything(self):
        await self.hide(0, False, map_number=9)
        await self.hide(1, False, map_number=11)
        b = await self.world(1, lambda w: self.entry(w, 0)["presence"] is not None)
        self.assertEqual(self.entry(b, 0)["presence"]["map_number"], 9)
        self.assertEqual(self.entry(b, 0)["presence"]["weather"], 5)
        self.assertEqual(len(b["extras"]["nav"]["players"]), 2)


if __name__ == "__main__":
    unittest.main()


class MenuToggleTests(unittest.IsolatedAsyncioTestCase):
    """PokeNav > World > Players and weather > Share my location (Update 24)."""

    async def test_the_toggle_is_on_by_default_flips_and_is_kept(self):
        from test_secret_bases import FakeMenuCompanion
        from emerald_multiplayer.player_menu import PlayerMenu

        class Companion(FakeMenuCompanion):
            share_location = True

            def set_share_location(self, share):
                self.share_location = share
                self.saved = share

        companion = Companion()
        menu = PlayerMenu(companion)
        await menu.refresh()

        async def click(label):
            row = next(r for r in menu.screen.rows if r.label == label)
            await menu.choose(menu.screen.revision, row.action)

        await click("World and my base")
        await click("Players and weather")
        self.assertIn("Share my location: ON", [r.label for r in menu.screen.rows])
        await click("Share my location: ON")
        self.assertIs(companion.saved, False)
        self.assertIn("Share my location: OFF", [r.label for r in menu.screen.rows])
        self.assertIn("Location hidden", menu.screen.status)
        await click("Share my location: OFF")
        self.assertIs(companion.saved, True)
        self.assertTrue(all(len(r.label) <= 25 for r in menu.screen.rows))
