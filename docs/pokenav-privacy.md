# Location privacy (PokeNav and launcher)

**Status: private by default since the owner's decision of 2026-11-05 (`docs/owner-decisions.md` #47: "Enable the launcher location
privacy checkbox. Default to privacy enabled. Do not expose precise player locations without explicit permission"). Built in
Update 24 as a PokeNav toggle that shared by default. Host, companions and launcher tested on Linux over real loopback connections
(a real host, real companions with scripted game bridges, the real launcher session), the Tk checkbox under a virtual display and
the in-game menu's row by its script. Not played on two real PCs, not checked on Windows.**

## What the player gets
* **Private unless you choose otherwise.** A character that never chose shows the other players no place at all.
* **Two switches, one choice.** Both edit the same file in the character's profile folder (`privacy-settings.json`, one per
  character in each world), so a change in one shows in the other:
  * in the game: **PokeNav > World > Players and weather > "Share my location: OFF / ON"** (the page draws the current choice
    each time it is shown);
  * in the launcher, while the game runs: **"Share my location with other players"**, unchecked by default: a checkbox on the
    Tk launcher's "Your game" page (under Save now and Autosave) and a row of the in-game EmeraldTogether menu's session window
    (under Autosave, "off - turn on" / "on - turn off"). It follows the game's toggle within a second.
* While you do not share, every *other* player sees you as online but nowhere: **no marker on their PokeNav map**, their Players
  list and a player's page say **Location hidden**, and no weather. A player standing on **the same map** sees your avatar in front
  of them (that is the shared world, not a location readout), but their PokeNav text still says **Location hidden**.
* While you battle a World Event, the other games know the Pokemon is taken, not by whom.
* You always see your own place and marker.

## Default and migration (exact rule)
* **No file: private** (the new default; loading never writes the file).
* The earlier builds (Update 24, commit `69680bb`, to 2026-11-05) shared by default and wrote this file **only when the player pressed
  the PokeNav toggle** (`Companion.set_share_location`, whose only caller was that toggle; nothing wrote a default). So every stored
  choice is the player's own:
  * no file (never chose; shared before only by the old default) -> **private** now;
  * `"share_location": true` (the player turned sharing off and on again) -> an explicit permission -> **keeps sharing**;
  * `"share_location": false` -> private.
* Unreadable or malformed file: **private** (a privacy setting that fails open would share what the player asked to keep).
* The file format is unchanged (`emerald-privacy-settings-v1`): an earlier build reads what this one writes, and the reverse.
* Going private applies at once even if the choice cannot be saved; sharing starts only once the choice is saved (the launcher then
  says "Your location sharing choice could not be saved. Your location is private for now").

## The rule the host enforces (the only place that can keep the promise)
`src/emerald_multiplayer/privacy.py`, applied per viewer in `WorldServer._broadcast_world`:
* Every presence the companion sends carries `share_location: true` or `false`. The host shows a player's place only for an explicit
  **`true`**; `false`, or no field at all, is private. Only a JSON boolean is accepted (anything else is a protocol error).
* A private player's presence reaches another player as map `255.255`, position `0,0`, **without the weather at their position**
  (which would give the region away). **Exception: a viewer standing on the same map** gets the real presence: their game draws
  that player's avatar (hiding it would break the shared overworld).
* **Readouts have no exception:** the PokeNav text (Players and weather, a player's page) is built from presences redacted with no
  same-map exception (`privacy.for_readout`), so it says "Location hidden" to every other viewer.
* **World Event claimant:** while a private player battles the World Event (whose place is announced), every other game is sent
  `00000000-0000-0000-0000-000000000000` ("somebody") as the claimant: the game only needs to know it is taken.
* The host keeps the real presence for what it runs (rival checkpoints, co-op Gym checks, World Event claims and wake conditions,
  shared wild Pokemon) and sends it to nobody else. There is no operator view: the host's own game joins its world as one of these
  viewers, and the launcher's host pages show no places (players online / in the world only).
* Before this change a viewer's companion refused a world frame (`stale_server_presence`) and reconnected whenever a hidden player's
  copy changed between hidden and real without that player's counters moving (the viewer walking onto their map, or the player
  turning sharing on). With privacy the default that would have happened constantly; `Companion._apply_world` now accepts that
  change (the order of `seq` and `map_epoch` is still checked).

## What it does not hide (stated, not hidden)
* **The same map.** A player on your map sees your avatar. From the avatar's own data their game also draws your PokeNav map marker
  at the map you both stand on and names that map in its own Players screen and Trainer Card (engine `native_ui` screens). The game
  draws all three from the one pose it receives, so the launcher cannot hide one without the others; doing it needs an engine change
  (a "private" bit per peer). They show nothing the viewer is not standing on.
* **Gameplay that tells where someone was**, kept as it is because hiding it would change the game:
  * World Event notices: "NAME caught the X!" / "NAME knocked out the X!" to everyone, "NAME caught it first!" to the other battler
    (the event's place was announced);
  * the rival checkpoint lobby: players at the same checkpoint see each other's names and choices (Rustboro's spans Rustboro City and
    Route 104); that is how they gather for the rival battle;
  * a co-op Gym challenge: "Your teammate must be here" says the teammate is not in this Gym;
  * a dormant World Event that wakes "when trainers gather" says two trainers were on its map (no names);
  * the "busy" mark on a shared wild Pokemon of the viewer's own map.
* **The host's server process** holds every presence (it is the authority); nothing of it is displayed or logged.
* Names and what a player is doing (online, In battle, In a menu) are not places and stay visible.
* Logs and diagnostics hold no other player's place: the host and companion write no positions to any log, the menu's
  troubleshooting file holds the last error; only the developer proof scripts (`scripts/multiplayer/native_*_proof.py`) write map
  numbers into their evidence files.

## Wire compatibility
* A world admits only players running the host's launcher version (KNOWN_ISSUES MS-28), so an earlier game never meets this rule.
  Between two development builds of different source (both "development"), an older host refuses the new game's
  `share_location: true` as a protocol error.
* The GBA release ROM is unchanged: to the ROM a hidden player is a peer on an unknown map, which it already ignores. The PC's own
  screens look maps up through a bounds-checked table (`RegionMap_PortableMapKnown`).

## Tests
* `tests/test_privacy.py`: redaction (no permission, explicit no, explicit yes, same map: avatar without readout, yourself); the wire
  field; the settings file (new profile private, round trip, the migration with the earlier build's exact bytes, failing closed); the
  companion (private until its profile says otherwise; sharing only once kept; a peer turning hidden or real is no stale pose); two
  real companions on a real host (no place for players who never chose; walking onto a private player's map shows the avatar on the
  same connection; opting in and out reaches the other game at once); four real connections (never chose, explicit no, opted in as
  before, on and off again, the World Event claimant); the PokeNav toggle (off by default); the real launcher session (the checkbox
  and the PokeNav toggle read and write one choice; an earlier explicit share keeps sharing).
* `tests/test_launcher_gui.py`: the worker applies the checkbox on the session's loop and reports the session's choice from either
  side; a choice that cannot be kept is reported; the Tk checkbox (label, unchecked and disabled by default, follows the game's
  toggle, a refused change puts it back, visible at 700x680).
* `tests/test_shell_app.py`: the in-game menu's session window row (off by default, turns on, follows the game).
* Tests that carry positions between players for other purposes now use players who chose to share: `tests/test_companion.py`
  (`add_companion(share_location=True)`), `tests/test_server.py` (its test client's presence), `tests/test_checkpoint_server.py`,
  `tests/test_session_persistence.py` (its players, and Trainer 1 on the Players page). `tests/test_secret_bases.py` expects the
  switch OFF by default; `tests/test_world_server.py` expects a World Event claimant who never chose to share to be "somebody".
* The developer proofs that follow a player onto another map (`scripts/multiplayer/native_presence_proof.py --enter`,
  `native_dive_check.py`, `native_session_persistence_proof.py`) now have those players choose to share; not re-run here (they need
  the native game).
* Engine (Update 24): Town Map with a hidden peer draws no marker and does not crash.

## Manual check (two PCs, not yet done)
- [ ] A new character: the launcher's "Share my location with other players" is unchecked and the game's PokeNav says
      **Share my location: OFF**. On PC 2, on another map: no marker for PC 1 on the PokeNav map, the Players list says
      **Location hidden**, no weather.
- [ ] Stand on the same map: PC 2 sees PC 1's avatar; PC 2's PokeNav text still says Location hidden.
- [ ] Tick the box in the launcher: the game's PokeNav page says ON; PC 2 sees the place and the marker. Turn it OFF in the game:
      the launcher's box clears. Restart: the choice is kept.
- [ ] Battle a World Event while private: PC 2's game shows it as taken; no name until the catch notice.
