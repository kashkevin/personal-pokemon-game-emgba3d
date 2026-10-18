"""A universal character entering worlds (character_play.py): a friend's world with no New Game, then coming back to it
with progress made elsewhere; the host's own world the same way. Real TLS, real WorldServer and stores, real child
processes; the native game's save mailbox is the existing fixture (NativeEnrollmentFixture)."""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
import socket
from unittest.mock import patch
import uuid

from emerald_multiplayer.character_creation import CreationError
from emerald_multiplayer.character_library import CharacterLibrary
from emerald_multiplayer.character_play import needs_registration, record_after_session, register_character, sync_from_worlds
from emerald_multiplayer.flash import OWNERSHIP_LAYOUT_ID, inspect_flash
from emerald_multiplayer.ownership import inspect_ownership
from emerald_multiplayer.ownership_storage import AllocationGrant
from test_character_creation import RemoteEnrollmentFixture
from test_ownership_storage import owned_flash, source_flash

FIRST = ((("party:0", 111111),))
LATER = (("party:0", 111111), ("box:0:3", 333333))


def elsewhere_save(records, world=None, player=None):
    """The character's save from another world it played in (other world's identities)."""
    grant = AllocationGrant(world or str(uuid.uuid4()), player or str(uuid.uuid4()), str(uuid.uuid4()), 500, 532, 1, 1, 0)
    return owned_flash(grant, tuple((location, 500 + i) for i, (location, _) in enumerate(records)),
                       personalities=tuple(pid for _, pid in records)), grant


class CharacterPlayTests(RemoteEnrollmentFixture):
    PERSONALITIES = (111111, 222222)
    inventory = FIRST

    def patches(self):
        test = self

        def export(grant, **keywords):
            keywords.pop("personalities", None)
            keywords["next_serial"] = grant.start + len(test.inventory)
            return owned_flash(grant, tuple((location, grant.start + i) for i, (location, _) in enumerate(test.inventory)),
                               personalities=tuple(pid for _, pid in test.inventory), **keywords)
        if not getattr(self, "_export_patch", None):
            self._export_patch = patch("test_enrollment_runtime.owned_flash", export)
            self._export_patch.start()
            self.addCleanup(self._export_patch.stop)
        return (patch("emerald_multiplayer.character_creation.Companion", self.companion),
                patch("emerald_multiplayer.player_runtime.asyncio.create_subprocess_exec", self.spawn))

    async def register(self, library, character, slot=1):
        account = self.host.accounts[slot]
        companion_patch, spawn_patch = self.patches()
        with companion_patch, spawn_patch:
            return await register_character(self.installation, self.private_root, library, character, role="friend",
                                            world_id=self.host.world_id, player_id=account.player_id,
                                            invitation_path=self.invitations[slot - 1], route_host="127.0.0.1",
                                            route_port=self.port, interval=0.01)

    def head(self, slot=1):
        row = self.store._connection.execute("SELECT latest_revision FROM players WHERE player_id = ?",
                                             (self.host.accounts[slot].player_id,)).fetchone()
        return row[0]

    async def test_a_new_character_joins_a_friends_world_without_a_new_game_then_comes_back_with_its_progress(self):
        library = CharacterLibrary(self.private_root)
        character = library.create(source_flash(personalities=(111111,)))
        account = self.host.accounts[1]
        self.assertEqual(needs_registration(self.private_root, library, character, self.host.world_id, account.player_id).reason,
                         "new_here")
        character = await self.register(library, character)
        self.assertEqual((character.world_id, character.player_id), (self.host.world_id, account.player_id))
        self.assertEqual(self.head(), 1)
        self.assertFalse(needs_registration(self.private_root, library, character, self.host.world_id, account.player_id).register)
        # Retrying never creates another character or conflicts: the account simply has it.
        self.assertEqual(len(library.all()), 1)

        # The character plays somewhere else and catches a second Pokémon there.
        payload, other = elsewhere_save(LATER)
        character = library.record_world_save(character.character_id, other.world_id, other.player_id, payload)
        plan = needs_registration(self.private_root, library, character, self.host.world_id, account.player_id)
        self.assertEqual(plan.reason, "coming_back")
        self.inventory = LATER
        self.native.grant = None
        character = await self.register(library, character)
        self.assertEqual(self.head(), 2)
        owned = inspect_ownership(inspect_flash(library.save_bytes(character), save_profile=OWNERSHIP_LAYOUT_ID))
        self.assertEqual((owned.world_id, owned.player_id), (self.host.world_id, account.player_id))
        self.assertEqual(sorted(r.personality for r in owned.records), [111111, 333333])
        # The first Pokémon's identity from the first visit left the world with the old save; nothing is active twice.
        statuses = self.store._connection.execute(
            "SELECT status, retirement_reason FROM ownership_instances WHERE player_id = ? ORDER BY serial",
            (account.player_id,)).fetchall()
        self.assertEqual([tuple(row) for row in statuses][0], ("retired", 1))
        self.assertEqual(sum(1 for row in statuses if row[0] == "active"), 2)
        self.store.integrity_check()
        # The account's earlier save is kept beside it, never deleted.
        previous = list((self.profile(1) / "previous-saves").iterdir())
        self.assertEqual(len(previous), 1)
        self.assertTrue((previous[0] / "character.sav").is_file())
        self.assertEqual(len(library.history(character)), 3)

    async def test_two_characters_in_one_account_and_session_end_bookkeeping(self):
        library = CharacterLibrary(self.private_root)
        first = await self.register(library, library.create(source_flash(personalities=(111111,))))
        account = self.host.accounts[1]
        second = library.create(source_flash(personalities=(222222,)))
        self.assertEqual(needs_registration(self.private_root, library, second, self.host.world_id, account.player_id).reason,
                         "other_character_here")
        # The game ended while the menu was not running: start-up takes the newer world save for its character.
        save = self.profile(1) / "character.sav"
        newer = owned_flash(AllocationGrant(self.host.world_id, account.player_id, str(uuid.uuid4()), 1, 33, 1, 1, 0),
                            personalities=(111111,), counter=7)
        save.write_bytes(newer)
        self.assertEqual(sync_from_worlds(self.private_root, library), [first.name])
        self.assertEqual(library.get(first.character_id).sha256, hashlib.sha256(newer).hexdigest())
        self.assertEqual(record_after_session(self.private_root, library, first.character_id, self.host.world_id,
                                              account.player_id).sha256, hashlib.sha256(newer).hexdigest())

    async def test_a_copy_of_a_pokemon_another_trainer_owns_here_is_refused_and_nothing_changes(self):
        library = CharacterLibrary(self.private_root)
        friend = await self.register(library, library.create(source_flash(personalities=(111111,))))
        # Another trainer in the same world owns pid 333333.
        self.current_source = 1
        self.native.grant = None
        self.inventory = ((("party:0", 222222)),)
        other = library.create(source_flash(personalities=(222222,)))
        await self.register(library, other, slot=2)
        # The first character comes back with a copy of a Pokémon now owned by the other trainer.
        payload, elsewhere = elsewhere_save((("party:0", 111111), ("box:0:3", 222222)))
        friend = library.record_world_save(friend.character_id, elsewhere.world_id, elsewhere.player_id, payload)
        before = self.head()
        with self.assertRaises(CreationError) as caught:
            await self.register(library, friend)
        self.assertEqual(caught.exception.code, "pokemon_owned_here")
        self.assertEqual(self.head(), before)
        self.assertEqual(library.get(friend.character_id).sha256, friend.sha256)
        self.assertFalse((self.profile(1) / "previous-saves").exists())


class HostOwnWorldTests(RemoteEnrollmentFixture):
    """The player's own world (Solo or hosted): the host's PC approves its own character, first and coming back."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        # The host PC registers with its own short-lived server on the world's port: free it.
        await self.server.close()
        self.store.close()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            free = listener.getsockname()[1]
        import json
        descriptor = json.loads((self.host.directory / "host.json").read_text())
        descriptor["port"] = free
        (self.host.directory / "host.json").write_text(json.dumps(descriptor))
        from emerald_multiplayer.host_world import HostWorld
        self.host = HostWorld.open(self.host.directory, self.rom, self.manifest)
        self.store = self.host.open_store()
        self.server = type("Closed", (), {"close": staticmethod(lambda: asyncio.sleep(0))})()

    async def asyncTearDown(self):
        self.store.close()
        await super().asyncTearDown()

    def patches(self):
        return CharacterPlayTests.patches(self)

    inventory = FIRST

    async def test_the_hosts_character_enters_and_comes_back_to_the_own_world(self):
        self.store.close()
        library = CharacterLibrary(self.private_root)
        character = library.create(source_flash(personalities=(111111,)))
        account = self.host.accounts[0]
        companion_patch, spawn_patch = self.patches()
        launcher_patch = patch("emerald_multiplayer.launcher_setup.Companion", self.companion)
        with companion_patch, spawn_patch, launcher_patch:
            character = await register_character(self.installation, self.private_root, library, character, role="host",
                                                 world_directory=self.host.directory, world_id=self.host.world_id,
                                                 player_id=account.player_id, interval=0.01)
            payload, other = elsewhere_save(LATER)
            character = library.record_world_save(character.character_id, other.world_id, other.player_id, payload)
            self.inventory = LATER
            self.native.grant = None
            character = await register_character(self.installation, self.private_root, library, character, role="host",
                                                 world_directory=self.host.directory, world_id=self.host.world_id,
                                                 player_id=account.player_id, interval=0.01)
        self.store = self.host.open_store()
        row = self.store._connection.execute("SELECT latest_revision FROM players WHERE player_id = ?", (account.player_id,)).fetchone()
        self.assertEqual(row[0], 2)
        self.store.integrity_check()
        self.assertEqual((character.world_id, character.player_id), (self.host.world_id, account.player_id))

