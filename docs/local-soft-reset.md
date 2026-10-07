# Local Soft Reset development backlog

Local Soft Reset lets a player repeat an eligible personal/static encounter for shiny hunting while the multiplayer session continues. The [user's amendment](project-update-local-soft-reset.txt) adds this mechanic only. It leaves every other accepted game rule, save architecture, and development priority unchanged.

## Implementation timing

Continue the existing foundation work first. Phase 3 supplies durable player identity, revisions, session leases, and recovery; the encounter and individual RNG systems must also be established before this feature is enabled. Implement eligible personal/static hunt support during the encounter work at the appropriate later phase. Phase 9 must verify that the event system never exposes a Local Soft Reset reroll path. Do not reorder the existing phases or delay the foundational multiplayer work for shiny hunting.

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

Current status: specified and queued. The movement prototype has no eligible static-hunt reset implementation yet.
