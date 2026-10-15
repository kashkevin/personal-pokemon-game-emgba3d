# 1v1v1v1 free-for-all: feasibility (Update 9)

**Result: not implemented. The existing battle engine cannot run four independent trainers in one battle without a
battle-engine redesign, and an approximation would be unsafe.** Nothing was faked: no sequence of 1v1 matches stands in for it.

## What the request needs
One shared battle with four independent sides: each trainer controls only their own Pokémon, may target any of the other
three, no allies, last trainer with a usable Pokémon wins, eliminated trainers spectate, no EXP.

## What the engine is (measured on the engine repository, `claude/dev-update8-14-engine`)
* **A battle has exactly two sides.** `NUM_BATTLE_SIDES = 2`; a battler's side is the parity of its position
  (`B_POSITION_PLAYER_LEFT/OPPONENT_LEFT/PLAYER_RIGHT/OPPONENT_RIGHT`). 237 uses of `GetBattlerSide` in 34 files, 143 uses of
  `B_SIDE_PLAYER/B_SIDE_OPPONENT` in 30 files, 234 uses of the per-side state arrays `gSideStatuses` / `gSideTimers` (Reflect,
  Light Screen, Tailwind, Spikes, Stealth Rock, Toxic Spikes, Sticky Web, Mist, Safeguard, Lucky Chant... all stored per side
  and keyed by side) in 19 files, 82 ally/opponent tests (`IsBattlerAlly/IsBattlerOpponent`) in 23 files.
* **"Opponent", "ally", "partner" and "opposite" are defined by side everywhere:** target selection (`MOVE_TARGET_*` resolve
  to "both foes", "all others", "ally"), spread-move damage reduction, abilities and items that read allies/foes (Intimidate,
  Plus/Minus, Friend Guard, Helping Hand, Follow Me/Rage Powder, Instruct, Ally Switch, Pledge combos...), AI scoring,
  switch-in hazards, weather/terrain ownership, "last Pokémon of the side" win/loss checks, the whiteout and the outcome word
  (`B_OUTCOME_WON/LOST/DREW` is binary per side).
* **Controllers and screens assume two columns:** the player controller, the opponent controller, the link controller and the
  battle UI lay out four battlers as two sides of two; the 3D battle stage does the same.
* **The native multiplayer layer encodes it too:** the native battle protocol, the host's canonical rosters, the journal and
  replay of battle recovery, the checkpoints and the outcome (1, 2 or 3 per team) all describe either 1v1 (two sides of one),
  2v2 (two sides of two) or co-op (two linked trainers vs two AI trainers). `mode` 3 already has four human trainers, but as two
  teams.

## Why an approximation is not acceptable
Treating "four trainers" as two sides (as the 2v2 does) gives teams, which the request forbids. Letting one trainer's moves
hit "a random other trainer" while the engine still thinks there are two sides would make Reflect, hazards, weather, Intimidate,
spread moves, Helping Hand and the win check wrong for some pair of trainers, and the outcome word cannot name a winner among four.
Each of those is a correctness bug in a ranked/prized mode and a desync risk between four cores that must stay in lockstep.

## What a real implementation would take (not started)
1. Make the side an explicit property of a battler (4 sides), turn `NUM_BATTLE_SIDES` into 4 and audit the ~700 side/ally uses
   above (per-side hazards and screens arrays, target resolution, ally/opponent predicates, abilities/items, AI, scripts).
2. Four-battler turn flow in the battle controllers and a four-position stage/UI, in 2D and 3D.
3. A new native battle phase: four independent trainers, four cores (the protocol, canonical rosters, the journal, replay and
   recovery all need the new shape), per-trainer outcomes, elimination and spectating.
4. The GBA test suite (6,000 tests, built for two sides) as the regression net, plus new multi-side tests.
This is an architecture project of the size of the whole native battle layer; it needs a model with deeper architectural
reasoning than this session's, and real two-to-four-PC testing. **Recorded for escalation; no code was written for it.**

## What exists instead (for players who want four people competing)
* Four-player 2v2 (two teams) and the four-player Championship bracket (1v1 elimination, each fights for themselves, durable
  results). Neither is a shared free-for-all and neither is described as one.
* If the owner wants a cheaper stand-in, a *round-robin* of 1v1 battles with a points table is a separate feature (it does not
  satisfy this request); it was not built.
