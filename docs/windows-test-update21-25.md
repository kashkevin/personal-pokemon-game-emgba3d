# EmeraldTogether: Windows test checklist for the Update 21-25 release candidate

Adds to `windows-test-update15-20.md` (its section A's "The opposing X" and "partner slot" lines are **superseded** by the list below).
**Nothing below has been run on a real PC.** The build is for the owner's private testing: bios.c licensing is unresolved, so it is
**not cleared for distribution**, and nothing here claims the game is fully tested or release-ready. Keep a copy of your `world` and `profile`
folders before updating.

## A. Four-player battle screen (four PCs; Classic 2D and 3D)
- [ ] Four distinct Pokémon: yours (back), three foes facing you, none overlapping; each healthbox shows **its trainer's name** (2D: where the level was) / a **coloured name tag** (3D: `ALICE (YOU)`, `BOB`, `CY`, `DI`).
- [ ] Battle text names the trainer: "BOB's Gardevoir used Swift!" (your own Pokémon unprefixed); no "The opposing".
- [ ] 3D target selection: four plates, all others **FOE**, you greyed; the highlighted plate and the blinking Pokémon agree. 2D: the blinking sprite (no names while choosing).
- [ ] A trainer out of Pokémon: 3D shows a grey `NAME - OUT` tag where the box was; the others fight on. Look at the tags' legibility at your window size and the four colours.
- [ ] 1v1, 2v2 and co-op look as before (no name tags, partner box short, back sprites for you and the partner).
## B. Location privacy (two PCs)
- [ ] PokeNav > World > Players and weather: **Share my location: ON** by default. Turn it OFF on PC 1, stand on a different map from PC 2: PC 2's Town Map has **no marker** for you, the Players list and Trainer Card say **Location hidden**, no weather. Stand on the **same map**: PC 2 sees you (expected). Restart: the choice is kept. Turn it ON: everything is shared again.
## C. Controls and sound
- [ ] Xbox pad: **A**, **B (new: Cancel/Back)** and **X** all work in menus; Y details; triggers/shoulders; stick and d-pad. Rebind a key (F10 > Controls in 3D, or the launcher's Game keys tab) and check every menu still works; Restore defaults.
- [ ] Loudness: music and effects are about 6 dB louder than the previous build at the same volume setting. Is it right? Any crackle on loud passages?
## D. Looks
- [ ] 3D on a real GPU: walk through a few towns and routes (the sweep saw 29 maps in a software renderer); Low and Medium quality presets; note any 2D flash: **in front of the Littleroot house at the start the moving trucks make the view fall back to 2D** (known; also Cable Car, S.S. Tidal, Seagallop).
## E. Updating an existing world
- [ ] Start the new host on a copy of an existing `world` folder: it opens, previous catches/BP/records are intact, nothing is paid twice.
