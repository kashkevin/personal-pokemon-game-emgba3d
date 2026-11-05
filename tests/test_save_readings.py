"""KNOWN_ISSUES MS-161, the owner's option (b) of 2026-11-05: each save's checked reading is remembered beside the world's
database (save_readings.py, docs/world-open-cache.md) so a save is read once in its life, and the integrity check stays
exactly as strict.

These compare the remembered readings with the reader itself (the same reading or the same refusal, on generated saves
of every kind and on damaged ones), and open worlds grown through the store's own API with and without them: the same
replay inputs and outcomes; a changed save read again; a new reader version, a damaged, edited, foreign or unwritable
file ignored and rebuilt; a world copied or restored from a backup; saves added; processes opening at once; and a
damaged save, membership, manifest or trainer still refused with every reading remembered."""
from __future__ import annotations

from contextlib import redirect_stderr
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import random
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
import uuid

from emerald_multiplayer import save_readings
from emerald_multiplayer import trade_friendship_migration, trade_friendship_observations
from emerald_multiplayer.flash import FlashError, inspect_flash
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, inspect_ownership
from emerald_multiplayer.ownership_storage import OwnershipCheckpointStore
from emerald_multiplayer.save_readings import (
    MAGIC, READER_FINGERPRINT, SUFFIX, SaveReadings, reader_fingerprint,
)
from emerald_multiplayer.storage import Checkpoint, StorageError
from emerald_multiplayer.trade_flash import build_party_swap
from emerald_multiplayer.trade_storage import TradeCheckpointStore, TradeSide
from test_flash import _blocks, _rewrite, _write_bank
from test_flash_box_reader import boxed
from test_ownership import _put_mon, _write_record, make_owned_mon, make_ownership_record
from test_ownership_storage import owned_flash, source_flash

BUILD, RULESET = "ownership-test-ROM-sha256", "baseline-test-rules-v1"
POLICY = "gen6-stable-world-region-v1"
TRAINER = 0x12345678                                  # test_flash._blocks' trainer, in every generated save
WORLD = "91f9294e-d509-4023-b055-f940a269aabc"       # test_ownership.make_ownership_record's world
# Where a generated save puts a caught or moved Pokemon (the party stays one Pokemon long: party:0 never moves).
PLACES = ([f"box:{box}:{slot}" for box in range(14) for slot in range(30)]
          + ["daycare:0", "daycare:1"] + [f"fusion:{index}" for index in range(4)])


def readings_path(database: Path) -> Path:
    return database.with_name(database.name + SUFFIX)


def answer(function):
    """A reading, or the reader's refusal by type and message."""
    try:
        return ("reading", function())
    except FlashError as error:
        return ("refused", type(error).__name__, str(error))


def observation_answer(function):
    try:
        return ("values", tuple(function()))
    except StorageError as error:
        return ("refused", error.code, str(error))


def random_save(rng: random.Random, *, count: int, counter: int = 2, damage: bool = False) -> bytes:
    """An ownership save with `count` random sealed Pokemon in random PC slots (test_flash_box_reader.boxed: any species,
    Eggs, every substructure order and language, random identities, so random serials) and one in the party. With
    `damage` one of them has a bit flipped before the save's own checksums are made (the reader refuses or reads it
    differently)."""
    block1, block2, storage = _blocks(TRAINER)
    block1, pc = bytearray(block1), bytearray(storage)
    _put_mon(block1, pc, "party:0", make_owned_mon(rng.randint(1, 0xFFFFF), personality=rng.getrandbits(32)))
    slots = rng.sample(range(420), count)
    for slot in slots:
        pc[4 + slot * 80:4 + (slot + 1) * 80] = boxed(rng, egg=rng.random() < .2)
    if damage and slots:
        spot = 4 + rng.choice(slots) * 80 + rng.randrange(80)
        pc[spot] ^= 1 << rng.randrange(8)
    record = make_ownership_record()
    flash = bytearray(b"\xff" * 131072)
    _write_bank(flash, counter - 1, (counter - 1) % 14, (bytes(block1), block2, bytes(pc)))
    _write_record(flash, (counter - 1) % 2, record)
    _write_bank(flash, counter, counter % 14, (bytes(block1), block2, bytes(pc)))
    _write_record(flash, counter % 2, record)
    return bytes(flash)


class ReaderCalls:
    """Counts the reader's runs on the cache's behalf (save_readings' inspect_flash and handler-history observation)."""

    def __enter__(self):
        self.flash = self.observations = 0
        real_flash, real_observations = save_readings.inspect_flash, trade_friendship_observations.checkpoint_observations

        def flash(*args, **kwargs):
            self.flash += 1
            return real_flash(*args, **kwargs)

        def observations(*args, **kwargs):
            self.observations += 1
            return real_observations(*args, **kwargs)

        self._patches = (mock.patch.object(save_readings, "inspect_flash", flash),
                         mock.patch.object(trade_friendship_observations, "checkpoint_observations", observations))
        for patch in self._patches:
            patch.start()
        return self

    def __exit__(self, *exc):
        for patch in reversed(self._patches):
            patch.stop()


def open_world(path: Path, *, cache: bool = True, store_type=TradeCheckpointStore) -> None:
    """A world opened and checked as a host's start does (the constructor's integrity check), then closed."""
    store_type(path, BUILD, RULESET, OWNERSHIP_PROFILE, save_readings=cache).close()


def open_code(path: Path, **options) -> str | None:
    try:
        open_world(path, **options)
    except StorageError as error:
        return error.code
    return None


class GrownWorld:
    """A valid world grown through the store's own API: players enrolled with two Pokemon each, then ordinary saves that
    catch, move and release Pokemon at random, and trades; every save distinct (its save counter)."""

    def __init__(self, path: Path, *, players: int = 2, seed: int = 161, store_type=TradeCheckpointStore,
                 handler_history: bool = False):
        self.path, self.rng = path, random.Random(seed)
        self.store = store_type(path, BUILD, RULESET, OWNERSHIP_PROFILE)
        if handler_history:
            from emerald_multiplayer.character_transfers import enable_character_transfers
            from emerald_multiplayer.trade_effect_storage import enable_trade_effects
            from emerald_multiplayer.trade_friendship_migration import enable_friendship_history
            enable_character_transfers(self.store, path.with_name("before-transfers.sqlite3"))
            enable_friendship_history(self.store, path.with_name("before-history.sqlite3"))
            enable_trade_effects(self.store, path.with_name("before-effects.sqlite3"), policy_id=POLICY)
        self.store.begin_server_boot()
        self.players = []
        for index in range(players):
            identity = self.store.create_player(f"Player {index}")
            lease = self.store.acquire_lease(identity.player_id, identity.credential)
            pids = (7 + 100 * index, 8 + 100 * index)
            self.store.enroll_player(identity.player_id, source_flash(("party:0", "box:0:0"), personalities=pids))
            grant = self.store.reserve_instances(identity.player_id, lease, str(uuid.uuid4()), 0, 1, 64)
            self.players.append(dict(identity=identity, lease=lease, grant=grant, revision=0, counter=2,
                                     next=grant.start + 2, retired=[],
                                     held={"party:0": (grant.start, pids[0]), "box:0:0": (grant.start + 1, pids[1])}))
            self.save(index)

    def close(self):
        self.store.close()

    def save(self, index: int) -> Checkpoint:
        player = self.players[index]
        player["counter"] += 1
        places = sorted(player["held"])
        payload = owned_flash(player["grant"], tuple((place, player["held"][place][0]) for place in places),
                              personalities=tuple(player["held"][place][1] for place in places),
                              retirements=tuple(player["retired"]), counter=player["counter"])
        checkpoint = self.store.commit_checkpoint(player["identity"].player_id, player["lease"], str(uuid.uuid4()),
                                                  player["revision"], payload, BUILD, RULESET, OWNERSHIP_PROFILE)
        player["revision"] = checkpoint.revision
        return checkpoint

    def play(self, index: int) -> Checkpoint:
        """One ordinary save: a Pokemon caught, moved or released, or nothing new."""
        player = self.players[index]
        held = player["held"]
        free = [place for place in PLACES if place not in held]
        movable = [place for place in held if place != "party:0"]
        choice = self.rng.choice(("catch", "catch", "move", "release", "same"))
        if choice == "catch" and player["next"] < player["grant"].end_exclusive:
            held[self.rng.choice(free)] = (player["next"], self.rng.getrandbits(32))
            player["next"] += 1
        elif choice == "move" and movable:
            held[self.rng.choice(free)] = held.pop(self.rng.choice(movable))
        elif choice == "release" and movable:
            player["retired"].append((held.pop(self.rng.choice(movable))[0], self.rng.choice((1, 2))))
        return self.save(index)

    def trade(self, a: int = 0, b: int = 1):
        """The two players' party Pokemon exchanged (the exact party swap), and both results applied."""
        pa, pb = self.players[a], self.players[b]
        heads = [self.store.read_checkpoint(p["identity"].player_id, p["lease"]) for p in (pa, pb)]
        serials = (pa["held"]["party:0"][0], pb["held"]["party:0"][0])
        post = build_party_swap(heads[0].payload, serials[0], heads[1].payload, serials[1])
        sides = [TradeSide(p["identity"].player_id, p["lease"], cp.revision, serial, data)
                 for p, cp, serial, data in zip((pa, pb), heads, serials, post)]
        result = self.store.commit_trade(str(uuid.uuid4()), *sides, BUILD, RULESET, OWNERSHIP_PROFILE)
        for checkpoint in (result.checkpoint_a, result.checkpoint_b):
            player = pa if checkpoint.player_id == pa["identity"].player_id else pb
            self.store.acknowledge_trade(checkpoint.player_id, player["lease"], result.transaction_id,
                                         checkpoint.revision, checkpoint.sha256)
            player["revision"] = checkpoint.revision
        pa["held"]["party:0"], pb["held"]["party:0"] = pb["held"]["party:0"], pa["held"]["party:0"]
        return result

    def grow(self, saves: int, *, trade_every: int = 0) -> None:
        for step in range(saves):
            for index in range(len(self.players)):
                self.play(index)
            if trade_every and len(self.players) > 1 and step % trade_every == trade_every - 1:
                self.trade()

    def checkpoints(self) -> int:
        return self.store._connection.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]


def grown(path: Path, *, saves: int = 8, trade_every: int = 0, **options) -> int:
    """A closed grown world at `path`; its checkpoint count."""
    world = GrownWorld(path, **options)
    try:
        world.grow(saves, trade_every=trade_every)
        return world.checkpoints()
    finally:
        world.close()


def replay_inputs(path: Path, *, cache: bool, store_type=TradeCheckpointStore) -> tuple[list, list]:
    """What the integrity check's replays consumed, in order: each save's ownership reading (with its bytes' hash and the
    trainer it was checked against), and each save's handler-history observations."""
    owned, observed = [], []
    real_owned = OwnershipCheckpointStore._read_owned
    real_values = SaveReadings.observations
    real_rows = trade_friendship_migration.checkpoint_observations

    def read_owned(store, payload, trainer_id):
        result = real_owned(store, payload, trainer_id)
        owned.append((hashlib.sha256(payload).hexdigest(), trainer_id, result))
        return result

    def values(readings, checkpoint):
        result = real_values(readings, checkpoint)
        observed.append((checkpoint.player_id, checkpoint.revision, tuple(result)))
        return result

    def rows(checkpoint):
        result = real_rows(checkpoint)
        observed.append((checkpoint.player_id, checkpoint.revision, tuple((s, r) for _, _, s, r, _ in result)))
        return result

    with mock.patch.object(OwnershipCheckpointStore, "_read_owned", read_owned), \
            mock.patch.object(SaveReadings, "observations", values), \
            mock.patch.object(trade_friendship_migration, "checkpoint_observations", rows):
        open_world(path, cache=cache, store_type=store_type)
    return owned, observed


class TempCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "world.sqlite3"

    def stderr_of(self, function, *args, **kwargs) -> str:
        stream = io.StringIO()
        with redirect_stderr(stream):
            function(*args, **kwargs)
        return stream.getvalue()


class ReaderPinTests(unittest.TestCase):
    def test_the_pinned_fingerprint_is_the_reader_source(self):
        actual = reader_fingerprint()
        self.assertEqual(actual, READER_FINGERPRINT, (
            "The save reader's code changed (one of save_readings.READER_MODULES). A remembered reading made by the old "
            "code must never answer for the new code, so its pin must change with it: set READER_FINGERPRINT in "
            f'src/emerald_multiplayer/save_readings.py to "{actual}" (every world then reads its saves once again).'))

    def test_a_change_to_any_reader_module_changes_the_fingerprint(self):
        real = Path.read_bytes
        for name in save_readings.READER_MODULES:
            def edited(path, name=name):
                data = real(path)
                return data + b"\n# changed\n" if path.name == name + ".py" else data
            with self.subTest(module=name), mock.patch.object(Path, "read_bytes", autospec=True, side_effect=edited):
                self.assertNotEqual(reader_fingerprint(), READER_FINGERPRINT)

        def unpinned(path):
            data = real(path)
            return data.replace(b'READER_FINGERPRINT = "', b"READER_FINGERPRINT = '") if path.name == "save_readings.py" else data
        with mock.patch.object(Path, "read_bytes", autospec=True, side_effect=unpinned):
            self.assertNotEqual(reader_fingerprint(), READER_FINGERPRINT)

    def test_without_the_source_the_pin_is_trusted(self):
        # The packaged app runs compiled modules only: the fingerprint cannot be made, READER_FINGERPRINT stands.
        with mock.patch.object(Path, "read_bytes", autospec=True, side_effect=OSError("no source")):
            self.assertIsNone(reader_fingerprint())


class SameAnswerTests(TempCase):
    """The remembered reading answers exactly as the reader: the same reading or the same refusal, cold and warm."""

    def test_the_same_reading_or_refusal_on_generated_saves(self):
        rng = random.Random(161)
        cases = []
        for index in range(160):
            payload = random_save(rng, count=rng.choice((0, 1, 5, 30, 120)), counter=2 + index, damage=index % 4 == 3)
            cases += [(payload, TRAINER), (payload, TRAINER ^ 1)]
            if index % 16 == 0:
                cases += [(payload, None), (payload, -1), (payload, 1 << 32), (payload[:-1], TRAINER),
                          (_rewrite(payload, (2 + index) % 2, 5, 9, b"\x01", recompute=False), TRAINER)]
        cases += [(owned_flash_for_world(), TRAINER), (b"", TRAINER), (bytes(131072), TRAINER)]
        reader = [answer(lambda p=payload, t=trainer: inspect_ownership(
            inspect_flash(p, expected_trainer_id=t, save_profile=OWNERSHIP_PROFILE))) for payload, trainer in cases]
        self.assertGreater(sum(result[0] == "reading" for result in reader), 100)
        self.assertGreater(sum(result[0] == "refused" for result in reader), 150)
        self.assertGreater(len({result[2] for result in reader if result[0] == "refused"}), 4)   # refused for many reasons

        def valid(trainer):                         # a trainer the reader can compare (else it refuses the request itself)
            return type(trainer) is int and 0 <= trainer <= 0xFFFFFFFF

        accepted = {payload for (payload, _), result in zip(cases, reader) if result[0] == "reading"}
        expected_cold, known = 0, set()
        for (payload, trainer), result in zip(cases, reader):
            if not (payload in known and valid(trainer)):
                expected_cold += 1                  # not remembered yet (or nothing to compare): the reader runs
                if result[0] == "reading":
                    known.add(payload)
        cold = SaveReadings(self.path, WORLD, OWNERSHIP_PROFILE)
        with ReaderCalls() as calls:
            self.assertEqual([answer(lambda p=payload, t=trainer: cold.ownership(p, t, OWNERSHIP_PROFILE))
                              for payload, trainer in cases], reader)
        self.assertEqual(calls.flash, expected_cold)
        cold.keep()
        self.assertTrue(readings_path(self.path).read_bytes().startswith(MAGIC))

        warm = SaveReadings(self.path, WORLD, OWNERSHIP_PROFILE)
        with ReaderCalls() as calls:
            self.assertEqual([answer(lambda p=payload, t=trainer: warm.ownership(p, t, OWNERSHIP_PROFILE))
                              for payload, trainer in cases], reader)
        # From the file: every save the reader accepted. Read again: refusals (never remembered) and requests without
        # a trainer to compare.
        self.assertEqual(calls.flash, sum(1 for payload, trainer in cases if not (payload in accepted and valid(trainer))))

    def test_another_profile_or_non_bytes_go_to_the_reader(self):
        readings = SaveReadings(self.path, WORLD, OWNERSHIP_PROFILE)
        payload = owned_flash_for_world()
        readings.ownership(payload, TRAINER, OWNERSHIP_PROFILE)
        for value, profile in ((bytearray(payload), OWNERSHIP_PROFILE), (payload, "rhh-1.17.1-bb1093-presence-v1")):
            with self.subTest(profile=profile), ReaderCalls() as calls:
                expected = answer(lambda: inspect_ownership(inspect_flash(value, expected_trainer_id=TRAINER,
                                                                          save_profile=profile)))
                self.assertEqual(answer(lambda: readings.ownership(value, TRAINER, profile)), expected)
                self.assertEqual(calls.flash, 1)


def owned_flash_for_world() -> bytes:
    """A save of make_ownership_record's world with a few Pokemon at every kind of place."""
    from test_ownership import make_ownership_flash
    return make_ownership_flash(records=(("party:0", 1), ("box:3:7", 2), ("daycare:1", 3), ("fusion:2", 4)), counter=9)


class WorldOpenTests(TempCase):
    def test_cached_and_uncached_checks_consume_the_same_readings(self):
        for handler_history in (False, True):
            with self.subTest(handler_history=handler_history):
                path = self.root / f"world-{handler_history}.sqlite3"
                count = grown(path, saves=14, trade_every=5, players=3, handler_history=handler_history)
                self.assertGreater(count, 45)
                uncached = replay_inputs(path, cache=False)
                self.assertFalse(readings_path(path).exists())
                with ReaderCalls() as calls:
                    cold = replay_inputs(path, cache=True)
                self.assertEqual(calls.flash, count)
                self.assertEqual(calls.observations, count if handler_history else 0)
                written = os.stat(readings_path(path))
                with ReaderCalls() as calls:
                    warm = replay_inputs(path, cache=True)
                self.assertEqual((calls.flash, calls.observations), (0, 0))       # read once in its life
                again = os.stat(readings_path(path))
                self.assertEqual((again.st_ino, again.st_mtime_ns), (written.st_ino, written.st_mtime_ns))  # not rewritten
                self.assertEqual(len(uncached[0]), count)
                self.assertEqual(len(uncached[1]), count if handler_history else 0)
                self.assertEqual(cold, uncached)
                self.assertEqual(warm, uncached)

    def test_schema_two_store_is_the_same(self):
        count = grown(self.path, saves=10, store_type=OwnershipCheckpointStore)
        uncached = replay_inputs(self.path, cache=False, store_type=OwnershipCheckpointStore)
        with ReaderCalls() as calls:
            self.assertEqual(replay_inputs(self.path, cache=True, store_type=OwnershipCheckpointStore), uncached)
        self.assertEqual(calls.flash, count)
        with ReaderCalls() as calls:
            self.assertEqual(replay_inputs(self.path, cache=True, store_type=OwnershipCheckpointStore), uncached)
        self.assertEqual(calls.flash, 0)

    def test_only_an_integrity_check_uses_the_readings(self):
        world = GrownWorld(self.path, store_type=TradeCheckpointStore)
        try:
            world.grow(3)
            world.store.close()
            open_world(self.path)
            world.store = TradeCheckpointStore(self.path, BUILD, RULESET, OWNERSHIP_PROFILE, save_readings=True)
            self.assertIsNone(world.store._readings)
            world.store.begin_server_boot()
            for player in world.players:
                player["lease"] = world.store.acquire_lease(player["identity"].player_id, player["identity"].credential)
            from emerald_multiplayer import ownership_storage
            real = ownership_storage.inspect_flash
            reads = []
            with mock.patch.object(ownership_storage, "inspect_flash", lambda *a, **k: reads.append(1) or real(*a, **k)):
                world.play(0)                          # a new save is read by the reader, as before
            self.assertEqual(len(reads), 1)
            self.assertIsNone(world.store._readings)
        finally:
            world.close()

    def test_a_changed_save_is_read_again(self):
        count = grown(self.path, saves=6)
        open_world(self.path)
        with sqlite3.connect(self.path) as db:
            player, revision, payload = db.execute(
                "SELECT player_id, revision, payload FROM checkpoints ORDER BY revision DESC LIMIT 1").fetchone()
            # Other bytes, the same reading: a special record (sector 30) the reader keeps as opaque bytes after its
            # sentinel. The world stays valid; only this save is read again.
            changed = bytearray(payload)
            changed[30 * 4096:30 * 4096 + 8] = struct.pack("<II", 0xB39D, 77)
            changed = bytes(changed)
            db.execute("UPDATE checkpoints SET payload = ?, sha256 = ? WHERE player_id = ? AND revision = ?",
                       (changed, hashlib.sha256(changed).hexdigest(), player, revision))
        db.close()
        with ReaderCalls() as calls:
            open_world(self.path)
        self.assertEqual(calls.flash, 1)
        saves = json.loads(readings_path(self.path).read_bytes()[len(MAGIC) + 65:])["saves"]
        self.assertIn(hashlib.sha256(changed).hexdigest(), saves)
        self.assertNotIn(hashlib.sha256(payload).hexdigest(), saves)      # the old bytes' reading is dropped
        self.assertEqual(len(saves), count)
        with ReaderCalls() as calls:
            open_world(self.path)
        self.assertEqual(calls.flash, 0)

    def test_a_new_reader_version_discards_every_remembered_reading(self):
        count = grown(self.path, saves=5)
        open_world(self.path)
        with mock.patch.object(save_readings, "READER_FINGERPRINT", "f" * 64), \
                mock.patch.object(save_readings, "_reader_state", [True]):
            with ReaderCalls() as calls:
                open_world(self.path)
            self.assertEqual(calls.flash, count)
            self.assertEqual(json.loads(readings_path(self.path).read_bytes()[len(MAGIC) + 65:])["reader"], "f" * 64)
            with ReaderCalls() as calls:
                open_world(self.path)
            self.assertEqual(calls.flash, 0)
        with ReaderCalls() as calls:                     # and back: the other version's file is discarded again
            open_world(self.path)
        self.assertEqual(calls.flash, count)

    def test_a_stale_pin_turns_the_cache_off(self):
        count = grown(self.path, saves=4)
        with mock.patch.object(save_readings, "_reader_state", [False]):
            with ReaderCalls() as calls:
                text = self.stderr_of(open_world, self.path)
            self.assertEqual(calls.flash, 0)                # no remembered readings at all: the store's reader runs
            self.assertFalse(readings_path(self.path).exists())
            self.assertIn("is off", text)
            self.assertEqual(self.stderr_of(open_world, self.path), "")   # reported once
        self.assertIsNone(open_code(self.path))
        with ReaderCalls() as calls:
            open_world(self.path)
        self.assertEqual(calls.flash, 0)
        self.assertGreater(count, 0)

    def test_a_damaged_edited_or_foreign_file_is_ignored_and_rebuilt(self):
        count = grown(self.path, saves=5)
        other = self.root / "other" / "world.sqlite3"
        other.parent.mkdir()
        grown(other, saves=5, seed=7)
        open_world(self.path)
        open_world(other)
        good = readings_path(self.path).read_bytes()
        body = good[len(MAGIC) + 65:]
        value = json.loads(body)

        def sealed(changed: dict) -> bytes:
            text = json.dumps(changed, sort_keys=True, separators=(",", ":")).encode()
            return MAGIC + save_readings._seal(text) + b"\n" + text

        a_save = sorted(value["saves"])[0]
        bad_record = json.loads(body)
        bad_record["records"][0][4] = 0                                      # species out of bounds
        wrong_content = json.loads(body)
        wrong_content["records"][0][5] = "0" * 64                           # sealed again, but not the reader's manifest
        missing_part = json.loads(body)
        missing_part["saves"][a_save]["o"][11] = [len(missing_part["records"])]   # a record that is not in the table
        other_trainer = json.loads(body)
        other_trainer["saves"][a_save]["o"][0] ^= 1        # still a valid reading's shape: only the seal can tell
        cases = {
            "a reading edited, seal not redone": (good[:len(MAGIC) + 65] + json.dumps(
                other_trainer, sort_keys=True, separators=(",", ":")).encode(), count),
            "truncated": (good[:len(good) // 2], count),
            "empty": (b"", count),
            "one byte changed": (good[:-5] + bytes([good[-5] ^ 1]) + good[-4:], count),
            "edited, seal not redone": (good.replace(b'"world":"', b'"world":"0'), count),
            "another magic": (b"EMERALD-SAVE-READINGS 2\n" + good[len(MAGIC):], count),
            "another world's file": (readings_path(other).read_bytes(), count),
            "these readings under another world's id": (sealed({**value, "world": str(uuid.uuid4())}), count),
            "another reader": (sealed({**value, "reader": "e" * 64}), count),
            "another format": (sealed({**value, "format": 2}), count),
            "another python": (sealed({**value, "python": "2.7"}), count),
            "another profile": (sealed({**value, "profile": "rhh-1.17.1-bb1093-presence-v1"}), count),
            "unknown field": (sealed({**value, "extra": 1}), count),
            "NaN": (good[:len(MAGIC)] + save_readings._seal(body.replace(b'"format":1', b'"format":NaN')) + b"\n"
                    + body.replace(b'"format":1', b'"format":NaN'), count),
            "a record out of bounds": (sealed(bad_record), sum(1 for s in value["saves"].values()
                                                               if 0 in s["o"][11])),
            "a record not the reader's": (sealed(wrong_content), sum(1 for s in value["saves"].values()
                                                                     if 0 in s["o"][11])),
            "an entry naming no record": (sealed(missing_part), 1),
        }
        for name, (data, reads) in cases.items():
            with self.subTest(case=name):
                readings_path(self.path).write_bytes(data)
                with ReaderCalls() as calls:
                    self.assertIsNone(open_code(self.path))
                self.assertEqual(calls.flash, reads)
                self.assertGreater(reads, 0)
                with ReaderCalls() as calls:
                    open_world(self.path)
                self.assertEqual(calls.flash, 0)          # rebuilt: every save answered from memory again
                self.assertEqual(readings_path(self.path).read_bytes(), good)

    def test_a_directory_or_link_in_its_place(self):
        grown(self.path, saves=3)
        place = readings_path(self.path)
        place.mkdir()
        text = self.stderr_of(open_world, self.path)
        self.assertIn("not a regular file", text)
        self.assertIn("could not be written", text)
        self.assertTrue(place.is_dir())
        self.assertEqual(self.stderr_of(open_world, self.path), "")              # each reported once
        place.rmdir()
        if os.name != "nt":
            target = self.root / "elsewhere"
            target.write_bytes(b"not mine")
            place.symlink_to(target)
            open_world(self.path)
            self.assertFalse(place.is_symlink())
            self.assertEqual(target.read_bytes(), b"not mine")                  # the link replaced, never followed
            with ReaderCalls() as calls:
                open_world(self.path)
            self.assertEqual(calls.flash, 0)

    def test_an_unwritable_file_is_reported_once_and_the_open_still_succeeds(self):
        count = grown(self.path, saves=4)
        for error in (OSError(errno.ENOSPC, "No space left on device"), PermissionError(errno.EROFS, "Read-only")):
            with self.subTest(error=type(error).__name__), mock.patch.object(save_readings, "_write", side_effect=error):
                save_readings._reported.clear()
                with ReaderCalls() as calls:
                    text = self.stderr_of(open_world, self.path)
                self.assertEqual(calls.flash, count)
                self.assertEqual(text.count("could not be written"), 1)
                with ReaderCalls() as calls:
                    self.assertEqual(self.stderr_of(open_world, self.path), "")
                self.assertEqual(calls.flash, count)                          # the full check, every open
                self.assertFalse(readings_path(self.path).exists())
        self.assertEqual(sorted(p.name for p in self.root.iterdir() if p.name.endswith(".tmp")), [])
        open_world(self.path)
        with ReaderCalls() as calls:
            open_world(self.path)
        self.assertEqual(calls.flash, 0)

    def test_a_world_copied_or_restored_from_a_backup(self):
        world = GrownWorld(self.path)
        try:
            world.grow(4)
            backup = world.store.backup(self.root / "backup.sqlite3")
            world.grow(4)
            count = world.checkpoints()
        finally:
            world.close()
        open_world(self.path)
        # The whole folder copied: the copy is the same world, its saves the same bytes.
        copy = self.root / "copy"
        copy.mkdir()
        for name in (self.path.name, readings_path(self.path).name):
            shutil.copy2(self.root / name, copy / name)
        with ReaderCalls() as calls:
            open_world(copy / self.path.name)
        self.assertEqual(calls.flash, 0)
        # The older backup restored over the database: every save it has was read already; the newer ones are dropped.
        os.replace(backup, self.path)
        with ReaderCalls() as calls:
            open_world(self.path)
        self.assertEqual(calls.flash, 0)
        saves = json.loads(readings_path(self.path).read_bytes()[len(MAGIC) + 65:])["saves"]
        with sqlite3.connect(self.path) as db:
            kept = {row[0] for row in db.execute("SELECT sha256 FROM checkpoints")}
        db.close()
        self.assertEqual(set(saves), kept)
        self.assertLess(len(kept), count)
        # Another world's database restored in its place: the file is for another world, ignored and rebuilt.
        other = self.root / "other" / self.path.name
        other.parent.mkdir()
        others = grown(other, saves=3, seed=9)
        shutil.copy2(other, self.path)
        with ReaderCalls() as calls:
            open_world(self.path)
        self.assertEqual(calls.flash, others)

    def test_saves_added_are_read_once(self):
        world = GrownWorld(self.path)
        try:
            world.grow(3)
            before = world.checkpoints()
            world.store.close()
            open_world(self.path)
            world.store = TradeCheckpointStore(self.path, BUILD, RULESET, OWNERSHIP_PROFILE)
            world.store.begin_server_boot()
            for player in world.players:
                player["lease"] = world.store.acquire_lease(player["identity"].player_id, player["identity"].credential)
            world.grow(2, trade_every=1)
            added = world.checkpoints() - before
        finally:
            world.close()
        with ReaderCalls() as calls:
            open_world(self.path)
        self.assertEqual(calls.flash, added)
        with ReaderCalls() as calls:
            open_world(self.path)
        self.assertEqual(calls.flash, 0)


class StillRefusedTests(TempCase):
    """With every save's reading remembered, damage is still found exactly as without them (a world with trades; its
    subclass below has handler history too)."""

    handler_history = False

    def setUp(self):
        super().setUp()
        self.count = grown(self.path, saves=6, trade_every=3, handler_history=self.handler_history)
        open_world(self.path)
        with ReaderCalls() as calls:
            open_world(self.path)
        self.assertEqual(calls.flash, 0)                                   # every reading remembered
        self.pristine = self.path.read_bytes()

    def damaged(self, sql, *args):
        self.path.write_bytes(self.pristine)
        with sqlite3.connect(self.path) as db:
            db.execute(sql, args)
        db.close()

    def assert_refused_both_ways(self):
        with ReaderCalls():
            self.assertEqual(open_code(self.path), "storage_corrupt")
        self.assertEqual(open_code(self.path, cache=False), "storage_corrupt")

    def last_payload(self):
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT player_id, revision, payload FROM checkpoints WHERE request_id NOT IN "
                             "(SELECT transaction_id FROM trade_transactions) ORDER BY revision DESC LIMIT 1").fetchone()
        db.close()
        return row

    def test_a_damaged_save(self):
        # Without handler history nothing but the reader can tell, once the stored hash is made to match the damage.
        player, revision, payload = self.last_payload()
        for spot in (5 * 4096 + 100, 20 * 4096 + 3000):                 # inside a save sector of each bank
            broken = bytearray(payload)
            broken[spot] ^= 1
            broken = bytes(broken)
            for sha in (hashlib.sha256(payload).hexdigest(), hashlib.sha256(broken).hexdigest()):
                with self.subTest(spot=spot, hash_updated=sha != hashlib.sha256(payload).hexdigest()):
                    self.damaged("UPDATE checkpoints SET payload = ?, sha256 = ? WHERE player_id = ? AND revision = ?",
                                 broken, sha, player, revision)
                    with ReaderCalls() as calls:
                        self.assertEqual(open_code(self.path), "storage_corrupt")
                    self.assertLessEqual(calls.flash, 1)                 # the damaged bytes, read by the reader
                    self.assertEqual(open_code(self.path, cache=False), "storage_corrupt")

    def test_an_edited_membership_manifest_or_event(self):
        player, revision, _ = self.last_payload()
        for sql in ("UPDATE ownership_memberships SET species = species + 1 WHERE player_id = ? AND revision = ?",
                    "UPDATE ownership_memberships SET location = 'box:13:29' WHERE player_id = ? AND revision = ? "
                    "AND location = 'party:0'",
                    "UPDATE ownership_commits SET manifest_sha256 = '" + "0" * 64 + "' WHERE player_id = ? AND revision = ?",
                    "UPDATE ownership_events SET kind = 'acquire' WHERE player_id = ? AND revision = ? AND kind = 'retain'"):
            with self.subTest(sql=sql.split(" SET ")[1][:30]):
                self.damaged(sql, player, revision)
                self.assert_refused_both_ways()

    def test_a_save_under_another_trainer(self):
        # The save's bytes are unchanged (its reading is remembered); the trainer it must belong to is not.
        with sqlite3.connect(self.path) as db:
            player = db.execute("SELECT player_id FROM players LIMIT 1").fetchone()[0]
            world_id = db.execute("SELECT world_id FROM world_metadata").fetchone()[0]
        db.close()
        self.damaged("UPDATE ownership_enrollments SET trainer_id = trainer_id + 1 WHERE player_id = ?", player)
        self.assert_refused_both_ways()
        player, _, payload = self.last_payload()
        expected = answer(lambda: inspect_ownership(inspect_flash(payload, expected_trainer_id=TRAINER + 1,
                                                                  save_profile=OWNERSHIP_PROFILE)))
        self.assertEqual(expected[0], "refused")
        for readings in (SaveReadings(self.path, world_id, OWNERSHIP_PROFILE),                 # from the file
                         SaveReadings(self.path, str(uuid.uuid4()), OWNERSHIP_PROFILE)):      # read in this check
            with ReaderCalls() as calls:
                self.assertEqual(readings.ownership(payload, TRAINER, OWNERSHIP_PROFILE).player_id, player)
                self.assertEqual(answer(lambda: readings.ownership(payload, TRAINER + 1, OWNERSHIP_PROFILE)), expected)
            self.assertLessEqual(calls.flash, 1)


class StillRefusedWithHandlerHistoryTests(StillRefusedTests):
    handler_history = True

    def test_an_edited_handler_history(self):
        self.damaged("UPDATE pokemon_friendship_history SET history = replace(history, '\"current_handler\":1', "
                     "'\"current_handler\":0') WHERE rowid = (SELECT MAX(rowid) FROM pokemon_friendship_history)")
        self.assert_refused_both_ways()

    def test_observations_answer_as_the_observation_itself(self):
        open_world(self.path)
        store = TradeCheckpointStore(self.path, BUILD, RULESET, OWNERSHIP_PROFILE)
        try:
            row = store._connection.execute("SELECT * FROM checkpoints ORDER BY revision DESC LIMIT 1").fetchone()
            checkpoint = store._checkpoint(row)
            world_id = store.metadata.world_id
        finally:
            store.close()
        other = str(uuid.uuid4())
        variants = [checkpoint,
                    Checkpoint(other, *[getattr(checkpoint, f) for f in ("revision", "request_id", "payload", "sha256",
                                                                         "build_id", "ruleset_id", "save_profile")]),
                    Checkpoint(*[getattr(checkpoint, f) for f in ("player_id", "revision", "request_id")],
                               checkpoint.payload, "0" * 64, BUILD, RULESET, OWNERSHIP_PROFILE),
                    Checkpoint(*[getattr(checkpoint, f) for f in ("player_id", "revision", "request_id", "payload",
                                                                  "sha256", "build_id", "ruleset_id")],
                               "rhh-1.17.1-bb1093-presence-v1"),
                    Checkpoint("not-a-uuid", *[getattr(checkpoint, f) for f in ("revision", "request_id", "payload",
                                                                                "sha256", "build_id", "ruleset_id",
                                                                                "save_profile")]),
                    Checkpoint(checkpoint.player_id, 0, *[getattr(checkpoint, f) for f in (
                        "request_id", "payload", "sha256", "build_id", "ruleset_id", "save_profile")]),
                    "not a checkpoint"]
        expected = [observation_answer(lambda c=c: [(s, r) for _, _, s, r, _ in
                                                    trade_friendship_observations.checkpoint_observations(c)])
                    for c in variants]
        self.assertEqual(expected[0][0], "values")
        self.assertTrue(all(result[0] == "refused" for result in expected[1:]))
        readings = SaveReadings(self.path, world_id, OWNERSHIP_PROFILE)
        with ReaderCalls() as calls:
            self.assertEqual([observation_answer(lambda c=c: readings.observations(c)) for c in variants], expected)
        self.assertEqual(calls.observations, len(variants) - 1)            # the first from memory, the others refused


class ConcurrentOpenTests(TempCase):
    CHILD = """
import sys
from contextlib import suppress
from pathlib import Path
import time
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE
from emerald_multiplayer.trade_storage import TradeCheckpointStore
path, rounds, start = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
while not start.exists():
    time.sleep(.001)
for index in range(rounds):
    if index % 2 == 0:
        with suppress(OSError):
            path.with_name(path.name + ".save-readings").unlink()
    TradeCheckpointStore(path, sys.argv[4], sys.argv[5], OWNERSHIP_PROFILE, save_readings=True).close()
print("ok")
"""

    def test_processes_opening_at_once_never_spoil_the_file(self):
        # Three processes open one world eight times each, deleting the file before every other open, so their reads,
        # rewrites and replacements interleave. Every open must pass and the file left must be whole and complete.
        count = grown(self.path, saves=10, trade_every=4, handler_history=True)
        start = self.root / "start"
        children = [subprocess.Popen([sys.executable, "-c", self.CHILD, str(self.path), "8", str(start), BUILD, RULESET],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=os.environ.copy())
                    for _ in range(3)]
        time.sleep(.3)
        start.touch()
        for child in children:
            out, err = child.communicate(timeout=240)
            self.assertEqual((child.returncode, out.strip()), (0, "ok"), err)
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.endswith(".tmp")], [])
        with ReaderCalls() as calls:
            open_world(self.path)
        self.assertEqual((calls.flash, calls.observations), (0, 0))
        self.assertEqual(len(json.loads(readings_path(self.path).read_bytes()[len(MAGIC) + 65:])["saves"]), count)


if __name__ == "__main__":
    unittest.main()
