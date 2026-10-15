# PokeNav location privacy (Update 24)

**Status: built; host side tested over real loopback connections, engine side compiled and its "no marker / no crash" path
looked at in the headless Town Map. Not played on two real PCs.**

## What the player gets
* **PokeNav > World > Players and weather > "Share my location: ON / OFF".** Default **ON** (nothing changes for anybody who
  never touches it). OFF is kept in the character's profile folder (`privacy-settings.json`) and survives restarts.
* While OFF, every *other* player sees you as online but nowhere: **no marker on the graphical PokeNav map**, the Players
  screens and the Trainer Card say **"Location hidden"**, and the World page's Players list says **Location hidden** with no weather.
* You always see your own place and marker.

## Rule the host enforces (the only place that can keep the promise)
`src/emerald_multiplayer/privacy.py`, applied per viewer in `WorldServer._broadcast_world`:
a hidden player's presence reaches another player as map `255.255`, position `0,0`, **without the weather at their position**
(which would give the region away); the PokeNav text is built from the same redacted data. Spawn and claim views are the viewer's
own map's, so they carry nobody else's place. **Exception: a viewer standing on the same map** gets the real presence (that
player is on the screen in front of them; hiding it would break the shared overworld).

## What it cannot hide (stated, not hidden)
* The **host's own computer** sees every presence (it is the authority). The setting protects players from each other.
* A player **on the same map** sees you.
* An old build that never sends the flag is, of course, sharing.

## Failure behaviour
* Missing settings file: sharing (default). **Unreadable or malformed file: hidden** (a privacy setting that fails open would
  share what the player asked to keep).
* The wire field exists only as `share_location: false`; `true` or anything else is a protocol error. Older games and hosts
  without the field behave as before (it is optional).
* The GBA release ROM is unchanged: to the ROM a hidden player is a peer on an unknown map, which it already ignores.
  The PC's own screens look maps up through a bounds-checked table (`RegionMap_PortableMapKnown`).

## Where else a location could leak (audited)
Player list presences, PokeNav text (Players and weather), Players screens, Trainer Card, Town Map markers (all covered);
notices (carry no place), secret bases (the base's place, not the player's), shared wild Pokémon and the habitat page (the viewer's
own map), battle/trade/team rosters (names only), the launcher's player list (online/offline only). The **host launcher** shows
presence to its own operator.

## Tests
`tests/test_privacy.py`: redaction rules, the wire field, the settings file (default, round trip, failing closed), four real
connections (a hidden player is unlocated for others, located for same-map viewers and for themselves; turning it off shares again;
default shares everything), the menu toggle. Engine: Town Map with a hidden peer draws no marker and does not crash.
