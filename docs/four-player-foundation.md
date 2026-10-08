# Four actual clients: foundation proof

On October 8, 2026, four independent libmGBA processes passed 30 recorded checks on the accepted ownership engine `88c7ef798ab5f91a496099cc687252fa5c4b12a3`. This proves four-player presence and individual persistence on one development computer. Trading, teams, network battles, Windows player delivery, and separate-computer networking retain their own acceptance gates.

## What ran

`scripts/multiplayer/four_player_proof.py` starts four actual game cores, the production Lua bridge, four authenticated companions, and an ownership checkpoint server. Each core has a separate native Trainer, save, controls, and local game state. Ordinary joypad inputs drive gameplay. Diagnostic RAM reads and screenshots observe results; writes are limited to the allocated production mailboxes. No savestates or arbitrary game/save injection are used.

The private original A/B saves were copied without modification. C and D were created through ordinary New Game, intro dialogue, clock setup, movement, and normal saving in `four-player-prepare-1`. Their distinct native Trainer IDs were verified after fresh Continue. A has Torchic and Wurmple; B, C, and D have no party in this proof. Empty-party clients are sufficient for movement/persistence checks and do not establish battle or trade readiness.

The frozen ROM SHA-256 is `a19b6d525599620b86ca48098276fd3e136422fbd2ef6d8bfbf38d203caf284a`; the official mGBA 0.10.5 source is `26b7884bc25a5933960f3cdcd98bac1ae14d42e2`. This uses the already accepted ownership build, separately from the newer trade-hold engine work.

## Verified behavior

- Four simultaneous authenticated clients, each seeing three remote actors together in Littleroot. A fifth authenticated player is refused without changing the admitted players.
- Independent joypad movement, three simultaneous maps, an open menu on C, and an indoor scene on D.
- A enters a normal Route 101 battle against a level-2 wild Wurmple while the other three games continue independently, then exits through the ordinary Run command.
- B disconnects and rejoins under a fresh lease. The other core processes, leases, and canonical save heads remain unchanged.
- Four independent enrollment checkpoints followed by four later saves. All four characters finish at canonical revision 2; the rejected fifth remains at revision 0.
- All four original cores close. Four new cores use normal Continue and restore their individual maps/positions and persistent Pokémon identities. A's Torchic and Wurmple remain serials 1 and 2.
- Closed native Flash bytes and normalized game states exactly match each character's canonical payload. The validated 16-byte emulator RTC footer is handled separately. SQLite integrity and a consistent backup are verified; all original source bytes remain unchanged.

The run contains 21 interactive commands and 24 snapshots. Every original process advanced independently from frame 1,984 to more than 106,000 frames. Fresh Continue uses four new process IDs. The shared proof pump was generalized from two input slots to the actual number of cores.

## Evidence and limits

The final run is `four-player-foundation-3`. The complete evidence hash is `664ebf1139bd7e7c60aa64e4874974d5c85355d5f30d662bd325ba5eecaa3f38`; the additional closed-game acceptance record hash is `f0797963bc32ef2ebbb2b3f70c9ec79724d689f7180c213deabf373690cc1ce8`. The integrity-checked backup hash is `16b71f841df0b1482c59b3f6a00a17302876d36cb24337c1aa346d33fe4db603`.

All 149 files in the final private run were copied to `C:\Users\kashh\AppData\Local\PokemonPrivate\artifacts\multiplayer\four-player-foundation-3` and individually checked against their source SHA-256 values. A [sanitized record](../scripts/multiplayer/four-player-evidence.json) keeps only scope, checks, and hashes in the repository. Private saves, credentials, databases, and ROMs remain outside Git.

Two earlier runs remain preserved. The first exposed a proof-helper expectation mismatch for the fifth-client refusal. The second exposed a helper shutdown race: canceling the pump during an in-flight frame command allowed a later diagnostic to read the wrong response. Final shutdown waits for all command locks to be idle before stopping the pump; snapshots precede shutdown. Neither earlier run is counted as acceptance.

This is a foundation slice of roadmap item 3. Two simultaneous teams, actual paired trades, 1v1/2v2 synchronization, interrupted network battles, host restart across those interactions, GUI/audio performance, real Wi-Fi, and port-forwarded Internet still require separate tests. A local wild battle is not a multiplayer battle.
