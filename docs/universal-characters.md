# Universal characters

Owner decision (2026-10-18): *"the character should be universal they can use it in solo and multiplayer and data, level
pokemon transfers."* A player creates one character once and plays it Solo, in their own hosted worlds and in friends'
worlds; its Pokemon, levels, items, money and story progress go with it.

Before this change a character belonged to one (world, account) pair: Solo was a private world with its own character,
and joining a friend needed another New Game in that world, which then collided with any earlier unfinished attempt
(`enrollment_conflict`, "This account already started with a different character"). See the root-cause report in
`docs/next-update-report.md`, section A.

## The pieces

| Piece | Module | What it does |
| --- | --- | --- |
| Character library | `character_library.py` | `<private>/characters/<character id>/`: `character.json` (name, trainer id, origin, the world accounts it played in), `current.sav` (its latest save), `history/` (earlier saves, 40 kept, plus explicit backups). `shell/character-library.json` holds the active character and the bindings world/account -> character + the save SHA it last took from there. |
| Detach | `character_transfer.py` | `detach_from_world(payload, wallet_seq=...)` turns an ownership save of any world back into an unassigned source: clears the Pokemon identity fields in party, boxes, Day Care and fusions (box checksums recomputed, re-encrypted), zeroes the world-scoped SaveBlock3 record (the egg queue is kept), keeps the newest bank, resets the world's catch-record vars and wallet amount and sets the wallet sequence to the destination world's. `_verify` then proves the result is the same character: trainer, every Pokemon's content and location, SaveBlock2, Hall of Fame and special sectors, egg queue, and everything outside the cleared fields byte-identical. |
| World store: transfers | `character_transfers.py` (+ `ownership_storage.py`, `trade_storage.py`) | Capability 3200 on the world store: table `ownership_transfers(player_id, base_revision, source_*, inventory_*)`. A transfer row makes the detached save the account's next *source generation*: the checkpoint at `base_revision + 1` must match that inventory with new serials only; the previous generation's serials are retired with reason 1 (left the world). The full-history audit understands generations. Refused while a trade recovery is pending or a battle is reserved, for another account's source, and when a Pokemon (personality, original trainer) is active for **another** player in the world (`pokemon_owned_here`). |
| Protocol | `enrollment_protocol.py`, `server.py` | The enrollment upload has an optional `mode` (`enroll` / `transfer`); chunks inherit the upload's mode; status returns state, revision, pending, wallet sequence and transfers. An unfinished first source is replaced instead of conflicting (`replace_unconsumed`). |
| Runtime | `enrollment_runtime.py`, `live_checkpoint.py` | `enroll(base_revision=N)` runs a transfer: the game loads the character once, the player chooses CONTINUE, and the world's first checkpoint of the new generation is committed. Before a transfer, the account's previous files are moved to `previous-saves/<UTC time>/` (refused while a pending trade, battle or emergency file exists). |
| Orchestration | `character_play.py` | `needs_registration` (ready / new_here / coming_back / other_character_here), `register_character` (host's own world through `launcher_setup.host_enrollment`; friend's world through `character_creation.remote_enrollment` with the character's save), `record_after_session` and `sync_from_worlds` (the world's save becomes the character's latest; at start-up for a game that ended while the menu was closed). |
| Menu | `shell_app.py` | Characters screen; `_registered` before every world entry; `_after_session` after every game. |

## Entering a world

1. The menu asks `needs_registration(character, world, account)`.
   * `ready`: the account already holds this character's latest save: play.
   * `new_here`: first visit. The character's save is detached and enrolled (the account's first source).
   * `coming_back`: the character played elsewhere since. The detached save is registered as a transfer at the account's
     current revision; the earlier save stays in `previous-saves/`.
   * `other_character_here`: another character used this account on this PC; the chosen character takes it over (the
     other keeps all its progress in the library).
2. The game opens once on the character (CONTINUE); it closes itself after the world saved the character.
3. After every game, `record_after_session` stores the world's save as the character's latest (the previous one goes to
   history). The library refuses a save of another world or trainer (`wrong_world`, `wrong_trainer`).

Worlds created by this version have the transfer capability from the start (a verified backup is made first). An older
world gains it the first time its host hosts it (`prepare_world_for_returning_characters`, closed world, verified backup
`<uuid>.before-character-transfers.sqlite3`; Host World does this before every hosting, Solo before a returning
character's registration). A friend coming back to a world whose host runs an older EmeraldTogether is refused with
`transfer_unsupported` ("Ask the host to install the same version"); the friend's character is not changed.

## What can be refused, and what then happens

Every refusal changes nothing on either side: the world's head revision, the character's save and the account's files
stay as they were (tested).

| Code | Meaning shown to the player |
| --- | --- |
| `pokemon_owned_here` | A Pokemon this character carries belongs to another trainer in this world (for example a traded copy). |
| `transfer_pending`, `trade_recovery_required`, `battle_reserved` | Finish the trade or battle in this world first. |
| `transfer_unsupported` | The host's EmeraldTogether is older and cannot take characters coming back. |
| `unreadable_character` | The character's save could not be read; restore an earlier save in Characters. |
| `source_already_enrolled` / `already_enrolled` | Handled automatically: retrying never makes a second character. |

## Migration from earlier versions (nothing is deleted)

At start-up (`character_migration.migrate_characters`, once):

* every world account on this PC with a readable world save becomes a library character bound to that account (the
  original `players/<world>/<account>/character.sav` stays where it is, byte-identical);
* the draft an earlier attempt recorded for an account (`drafts/<id>/character.sav`, named in the character links)
  becomes a character too;
* other drafts are listed under Characters, "Recover a character"; recovering copies them, the originals stay;
* unreadable saves are reported on the Characters screen ("Left untouched") and not imported.

`shell_migration.migrate` (from the previous update) still turns the earlier launcher's worlds, invitations and recent
sessions into worlds and saved servers; Continue Adventure falls back to those records until the new last-session record
exists.

## Recovery

* **History**: every world save the character takes keeps the previous one in `history/` (40 kept). Characters,
  "Restore an earlier save" makes one current again (the present one goes to history first; same trainer only).
* **Back up now**: an explicit copy in history.
* **Damaged character folder**: a `current.sav` whose SHA no longer matches is reported ("save changed") and left alone.
* **Delete**: moves the character folder to `characters-deleted/<UTC time>-<id>/`; its world saves stay in the worlds.
* **Worlds**: deleting a world moves its folder to `worlds-deleted/`; every store migration makes a verified backup first.
* **Interrupted registration**: an abandoned pre-grant attempt is moved to `abandoned-enrollments/` and restarted; the
  friend's own `invitation.json` and `previous-saves/` are no longer mistaken for leftovers (this blocked friends' retries).

## Tests

`tests/test_character_transfer.py` (detach verification), `tests/test_character_transfers.py` (store generations, audit,
refusals), `tests/test_character_library.py` (library and migration), `tests/test_character_play.py` (real TLS server:
friend first visit and return with a Pokemon caught elsewhere, duplicate refusal, two characters, host's own world),
`tests/test_shell_app.py`, `tests/test_shell_join.py`, `tests/test_shell_migration.py`, and `tests/test_shell_e2e.py`
(through the menu with the real registration: host plus two friends, Solo first then a friend's world, friend's world ->
own Solo world -> back with what it caught, a relay route).

Not tested: the real game's CONTINUE-and-save sequence on a real PC (the game process is a placeholder and its save mailbox
the existing fixture), and gameplay effects of a save moving between worlds beyond what the save verification checks.
