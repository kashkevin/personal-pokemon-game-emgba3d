# EmeraldTogether: Windows test checklist for Update 27 (Battle FX)

Nothing below has been run on a real PC; the Update 27 checks ran in a cloud simulation without a GPU (docs/battle-fx-audit-update27.md). The package is for the
owner's private testing and is not cleared for distribution (bios.c licensing is unresolved). Keep a copy of your `world` and `profile` folders and
`%LOCALAPPDATA%\PokemonPrivate` before updating.

Which build is running: the launcher's version label reads **Update 27 app <hash> engine <hash>**.

## A. Background moves: no black block (the Update 27 fix) - 3D
- [ ] Aura Sphere, Hurricane, Focus Blast, Assurance, Armor Cannon (a Generation 8 move: your Pokemon needs it, or use the debug menu), Trick Room, Magic Room: the background fills the whole window; **no black rectangle** at the bottom centre or the corners, your Pokemon whole.
- [ ] The same in Classic 2D (the GBA picture: the text box covers the bottom, as always).

## B. Move effects (3D, then the same few in Classic 2D)
- [ ] Flamethrower, Fire Blast, Overheat: fire from your Pokemon to the foe, not from the wrong one.
- [ ] Thunderbolt, Thunder, Volt Tackle; Ice Beam, Blizzard, Ice Shard; Surf, Hydro Pump, Water Pulse.
- [ ] Solar Beam, Hyper Beam, Dragon Pulse; Shadow Ball, Dark Pulse, Aura Sphere; Earthquake, Rock Slide, Stone Edge.
- [ ] Psychic, Psybeam, Confusion; Leaf Storm, Energy Ball, Razor Leaf; Explosion, Self-Destruct (the user faints after).
- [ ] Protect, Substitute (the doll appears and goes), Recover, Swords Dance.
- [ ] A move from Generation 7-9 (for example Zippy Zap, Aqua Step, Triple Axel): the original effect, not blank and not covering your Pokemon.
- [ ] Multi-hit moves (Double Slap, Fury Swipes): an effect for each hit. Two-turn moves (Fly, Dig, Solar Beam): both halves.
- [ ] Nothing left on the screen after the animation; no stutter that stays after the battle.

## C. Special effects
- [ ] A shiny Pokemon appearing (sparkles); Mega Evolution (the stone, the ring and light); a Poke Ball catch (the original ball animation: throw, shakes, stars).
- [ ] Burn, poison, paralysis, sleep, freeze, confusion: the status animation on the right Pokemon. Stat up and down arrows.
- [ ] Rain, sandstorm, hail or sun set by a move or ability: the weather effect; Stealth Rock and Spikes.
- [ ] Fainting, switching a Pokemon in and out, winning and losing: the screen returns to the overworld with no old GBA panel flashing (Update 26's fix).

## D. Battles
- [ ] A wild battle, a trainer battle, the first battle with Birch (Route 101 bag): the route's ground behind it, not black.
- [ ] A double battle: each effect from the right Pokemon to the right foe.
- [ ] Two players: a 1v1 and a 2v2; four players: the free-for-all (this is the only one never run even in a simulation with a map: look for effects on the wrong player's Pokemon).

## E. Performance
- [ ] Quality: Settings > Graphics (or `battlefx\settings.cfg` `quality=`): Low, Medium, High, Auto: effects visible at every level; the game keeps 60 frames a second or drops to the original effects, not to a slide show.
- [ ] A long battle (ten turns): the frame rate does not fall; the Task Manager's memory for the game stays flat.
