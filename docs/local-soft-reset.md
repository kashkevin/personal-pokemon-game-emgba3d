# Local Soft Reset development backlog

Local Soft Reset lets a player repeat an eligible personal/static encounter for shiny hunting while the multiplayer session continues. The [original amendment](project-update-local-soft-reset.txt) defines this mechanic; the owner's latest [delivery roadmap](development-roadmap.md) places its implementation after four-player testing. Other accepted game rules and save guarantees remain in force.

## Implementation timing

Complete safe trading, battles/teams, and four-player proof first. The ownership milestone supplies durable identity, revisions, leases, and recovery. Then implement the minimal personal/static encounter boundary, individual RNG and Gen 6 shiny-roll behavior needed for Local Soft Reset, without waiting for every later roster/map/content feature. This dependency work is part of the reset milestone, not permission to bypass save/ownership safety. Phase 9 must additionally verify that the event system never exposes a Local Soft Reset reroll path.

The [Shiny Charm amendment](project-update-customization-friendship-shiny-charm.txt) adds a later personal modifier: eligible fresh rolls use only the requesting player's legitimately owned Charm once implemented. The attempt counter never changes probability. Establish that hook now; the actual Charm feature follows its encounter/shiny dependencies, and its guaranteed Game Corner purchase path can be developed later. World Event properties remain outside both systems.

## Required behavior

- Reset/reload only the requesting player's eligible personal/static encounter, returning immediately before it when practical and generating a fresh legitimate roll.
- Preserve the player's multiplayer connection, the running server, shared state, and every other player's gameplay and persistent state.
- Where practical, intercept the classic button combination while connected; optional Yes/No confirmation prevents accidental resets.
- Count eligible encounter attempts, incrementing when the next encounter starts. The counter must not influence the shiny rate. Recording a shiny's attempt number and displaying it in statistics/Trainer Card are permitted later additions.
- Keep normal wild encounter mechanics unchanged. Exclude World Events from rerolling species, Mega status, shiny status, rarity, rewards, and all other event-generated properties.

Define the eligible encounter boundary, safe return point, and handling of an encounter that has already committed capture/reward changes before implementation. Recovery must respect existing player revisions and ownership transactions. Do not use a whole-server rollback, emulator savestate restoration, or an older player snapshot to manufacture a reset.

## Acceptance checks

1. Start a personal/static hunt and reset repeatedly. Each new encounter receives a legitimate fresh roll and a single new attempt count; the probability remains the established rate.
2. Keep three other players respectively in a battle, a wild encounter, and a trade. Their sessions, encounter rolls, transactions, locations, and progression remain unchanged throughout the requesting player's reset.
3. Reject ineligible wild/event reset requests. A normal Mega event cannot become shiny, and an originally shiny event remains shiny with its original species, form, rarity, and rewards.
4. Test confirmation cancellation, disconnect/rejoin, server restart, and interruption during an eligible reset. Preserve attempt counts and completed ownership changes without duplication.
5. Verify that classic input invokes the local operation where supported and never intentionally restarts the server, another game, or a shared event.

Current status: the [development encounter](local-soft-reset-design.md) passed an actual four-client reset, capture, checkpoint and fresh-Continue proof. The [authored encounter implementation](local-reset-durable-admission.md) now covers nine explicit sources, durable attempt counts, Gen 6 personal shiny rolls and exact pre-generation host-loss cancellation. Its native and transport tests have passed; ordinary-route authored hunts, their composed emergency-save path, Windows controls and simultaneous trade/battle/reset acceptance remain outstanding. The development encounter is default-off, and enabling the authored catalogue requires the explicit native build flag. Neither test coverage nor the development encounter establishes completed production reset delivery.
