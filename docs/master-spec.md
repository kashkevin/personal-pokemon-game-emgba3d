# Pokémon Emerald private multiplayer specification

This is the current specification for a private Windows game for one to four players total, using Emerald as its visual and technical foundation. The October 7, 2026 Generation 6 update replaces the original Gen 1–5 roster, Gen 5 mechanics, and exclusion of Fairy. Other accepted requirements remain in force. The [original brief](project-brief.txt) and [Generation 6 update](project-update-gen6.txt) are preserved verbatim.

## Game identity and delivery

- Start with Hoenn and Emerald's GBA-style 2D presentation.
- Support standard Pokémon introduced in Generations 1–6: National Pokédex entries 1–721. Alternate forms and Mega forms require a separate explicit catalogue; internal species IDs are not the standard species count.
- Use Generation 6 Pokémon and battle mechanics, including Fairy typing and its type chart. Use the completed Gen 6 main-series rules as the practical data baseline; document differences between XY and ORAS where a choice affects gameplay. Do not silently apply Gen 7+ rules or enable unrelated later mechanics.
- Include all officially released Mega Evolutions applicable to eligible Gen 1–6 Pokémon, including later releases. Verify the current official catalogue when implementing it. A later Mega belonging to a post-Gen-6 base species does not authorize adding that base species.
- Deliver a Windows download with one game entry point and Host Game / Join Game. Bundle the runtime so friends need no compiler, Python, WSL, VPN, or manual emulator scripts.
- The owner's Windows PC hosts over home Wi-Fi, with direct Internet connections through an explicitly configured game port and matching firewall rule. Keep the host awake during shared sessions. No paid hosting or public matchmaking is required.
- Preserve the instruction against downloading or distributing commercial ROMs. The proposed download contains our application/runtime and modification patch, with a one-time import of each player's own game dump. Review included code and asset terms before distribution; a patch alone does not establish permission for its contents.

## Independent players and teams

Players can explore different maps, have independent encounters and solo battles, and choose when to interact. Joining a server does not automatically create a team. Multiplayer interactions should be available after starter selection and entering the world, without an Elite Four/endgame gate.

Each player owns a separate party, PC storage, inventory, money, progression/badges where appropriate, rewards, and statistics. Teaming never creates a shared wallet or inventory. Each eligible participant receives their own appropriate reward; do not divide a single reward between teammates.

Normal teams have at most two players. Players can invite, accept, leave, and change teammates without restarting the world. Two separate teams may coexist. The eventual player interaction menu includes team invitation/leaving, trading, challenges, double-battle challenges, and trainer cards.

## Starters

Each player independently chooses one of these 18 traditional starters through an eventual custom selection interface. Duplicate choices are allowed, including all four players selecting the same starter.

| Generation | Choices |
| --- | --- |
| 1 | Bulbasaur, Charmander, Squirtle |
| 2 | Chikorita, Cyndaquil, Totodile |
| 3 | Treecko, Torchic, Mudkip |
| 4 | Turtwig, Chimchar, Piplup |
| 5 | Snivy, Tepig, Oshawott |
| 6 | Chespin, Fennekin, Froakie |

## Wild encounters and shinies

Randomized encounters select from eligible Gen 1–6 evolutionary families, with rarity weighting rather than equal probabilities. Legendary and Mythical Pokémon are excluded from ordinary randomized encounters and primarily belong to special content/world events. Starters can appear in the normal wild pool.

Early encounters primarily use low-level basic forms. Rare families such as Bagon, Larvitar, Gible, Axew, Deino, Riolu, Honedge, or Goomy can appear early at balanced rarity and low levels; their final evolutions should not normally appear at starter-level difficulty. Evolution stages and encounter levels expand with progression. Common, uncommon, rare, and very rare are possible rarity categories; exact weights are a later balancing decision.

Every player receives independent encounter rolls, even in the same patch of grass. Shinies remain possible and must display correctly in battle and as followers. Do not silently choose a new shiny rate.

## Trading and battles

Trading and PvP should be available essentially from the beginning. Ordinary direct trades should not require Emerald's traditional Link Room. Both players select an offer and explicitly confirm; changes invalidate confirmation. Safe atomic ownership changes and crash/rejoin recovery are required before trading is considered complete.

Implement and stabilize conventional 1v1 and 2v2 first. In 2v2, two human trainers fight two human trainers with independent parties and ownership. Later, design custom 1v1v1v1 with four independently hostile trainers. Four existing battler slots do not make that format a simple doubles flag; protect conventional battles while developing it separately.

Optional wagers use only fictional currency earned inside the game. Both sides explicitly confirm the amount before the battle. Team wagers respect each participant's individual wallet. The exact pot, ties, interruptions, and forfeits require deliberate rules; no accidental currency loss or silent automatic forfeit.

A four-player Championship has two semifinals followed by a final between their winners. It should be available relatively early without completing the campaign. Potential statistics include tournament entries/wins, PvP wins/losses, win streak, and 1v1/2v2 records. Optional buy-ins and rewards must follow the independent-wallet rules.

## Campaign and Gym twins

A solo challenger faces the ordinary Gym Leader. Two teammates face the Leader and a custom Twin/Partner in a purpose-built double battle. Twins are coordinated partners, not merely duplicate trainers. Strategies can combine weather, speed, screens/support, status, and offense. Later eligible AI trainers can Mega Evolve.

Rewards and progression remain individual. Define cooperative story eligibility, badge advancement, and mixed-progression interactions before implementing shared campaign scripts.

## Mega Evolution

- One Mega Evolution per trainer per battle, including each human in 2v2 and eligible AI trainers. Do not mistakenly grant one allowance per team/side.
- Unlock Mega access through appropriate Key Stone/Bracelet progression. Players do not start with Mega access; the exact unlock point can occur before postgame and remains a balance decision.
- Mega Stones are purchasable and deliberately expensive enough to make early/mid-game choices meaningful. Wealth later makes collecting more stones easier.
- Appropriate events and rewards can also supply stones. Successful eligible Mega events may reward the corresponding stone.
- Use official appearance, typing, base stats, ability, and stone/form requirements where practical, including later official Megas for eligible base species.
- Adapt later Megas to the Gen 6 engine. Document any later ability/action/system conflict and propose the closest faithful behavior before changing it. Do not import an entire later-generation ruleset to support one Mega.
- Ordinary later mechanics such as Z-Moves, Dynamax, Terastallization, or Primal Reversion are not automatically included by this Mega requirement.

Mega Pokémon can appear in special world events and may be shiny. Their legitimate overworld representation needs the correct Mega graphics. Capture/form duration and reversion rules must be designed before treating a Mega appearance as a permanently stored ordinary Pokémon.

## Followers

Eventually support the complete Gen 1–6 roster and approved forms, including shiny appearance. Players can choose a party follower, see other players' followers, and interact with their own follower. Friendship messages, location reactions, and occasional item discovery are potential later additions. Legitimately represented Mega overworld forms should display correctly.

Reuse compatible integrated follower work, then test actor, sprite, tile, and palette budgets. Do not spend weeks producing hundreds of follower assets before multiplayer networking is proven.

## World events

The shared world eventually schedules random timed events, notifies connected players, and requires them to travel to the event location. Do not automatically teleport players. Categories include rare, Mega, Legendary, Mythical, shiny, shiny Mega, shiny Legendary/Mythical, and exceptionally rare shiny Mega Legendary Pokémon where applicable.

Events use the Gen 1–6 standard roster and any supported official Mega that meets the eligibility rule. Highly valuable events should be extremely rare; exact probabilities and durations remain balancing decisions. Event difficulty/levels should scale with player/world progression unless intentionally designed as a clearly inaccessible/high-risk challenge.

Keep event IDs, timers, participation, claims, and despawn/recovery behavior consistent across clients. Eligible rewards remain player-specific. A unique spawn's capture allocation—one player, each participant, or another rule—requires an explicit decision. Timer behavior during server downtime and mixed-progression scaling also need decisions before implementation.

## Saves and recovery

Each player can disconnect and later rejoin with Pokémon, party/storage, inventory, money, and progression intact. Persist the shared world state needed by the eventual systems. Protect saves from partial writes, stale snapshots, duplicate ownership, and duplicated payouts.

Use versioned character/world schemas and build/ruleset compatibility checks. Preserve backups and test migrations on copies. Never discard an earlier character merely because the roster/configuration changes. Do not merge conflicting offline/online characters automatically. Autosave intervals, server-loss local-play behavior, and interrupted battle policies must be finalized before those systems ship.

## Regions

Hoenn is the only region to build and polish initially. Potential later regions are Kanto, Johto, Sinnoh, Unova, and Kalos. Add one at a time as content inside one expanded game, not by combining ROM binaries. Supporting Gen 6 Pokémon does not require building Kalos now.

Later regions must account for existing player progression through trainer teams, wild encounters, and Gym difficulty. Exact curves remain a later decision. Measure ROM, map, save, and rendering budgets before committing to every region fitting the GBA runtime.

## Development order and acceptance

Maintain small commits, repeatable builds, focused tests, private artifact/save backups, and known-good checkpoints. Diagnose failures before stacking fixes. Preserve working systems before speculative changes. The tested foundation is pinned RHH `expansion/1.17.1`; re-evaluate a replacement only when its benefit warrants migration cost.

| Phase | Required result |
| --- | --- |
| 0 | Specific foundation, toolchain, emulator, architecture, risks, licensing/provenance, and concrete baseline plan. |
| 1 | Unmodified engine builds reproducibly; gameplay, ordinary saving/reload, and isolated client saves are verified. Preserve the baseline before game changes. |
| 2 | Two actual clients see each other, move independently, handle maps/menus/battles, disconnect cleanly, and reconnect. A server-only synthetic demonstration is insufficient. |
| 3 | Durable individual state, safe rejoin, appearance, map transitions, and interaction infrastructure without corruption/desync. |
| 4 | Direct trade, 1v1, freely formed teams, co-op interactions, 2v2, independent rewards, early interactions, currency wagers, and Championship. |
| 5 | Gen 1–6 roster, Gen 6/Fairy mechanics, 18 starters, rarity-weighted encounters, evolution-stage progression, Legendary/Mythical exclusions, and shinies. Integrate established compatible functionality. |
| 6 | Gym twins, co-op campaign rules, difficulty, double-battle AI, and player-specific rewards. |
| 7 | Followers, remote visibility, shinies, and interactions. |
| 8 | Complete eligible official Mega catalogue, approved later adaptations, per-trainer allowances, unlocks, shops/stones, AI, and multiplayer synchronization. |
| 9 | Scheduled events, notifications, locations/timers, event species/forms/shinies, appropriate stones/rewards, persistence/despawn. |
| 10 | Separately researched and tested custom 1v1v1v1. |
| 11 | Stable, polished Hoenn multiplayer with the accepted systems, UI, performance, and lifecycle tests. |
| 12 | One additional region at a time after Hoenn is stable. |

The first major technical milestone remains reliable multiplayer. Start with two clients, then prove independent persistence before claiming the first playable shared-world milestone. The second playable milestone adds the 18 starters, encounters/capture, trade, 1v1, team changes, and retained state. The third proves four actual clients, two simultaneous teams, trade, 1v1/2v2, individual rewards, and stable rejoin before aggressive content expansion.

Lifecycle tests must cover menus/pause, separate local battles, map entry/exit, slow/partial network delivery, disconnect/reconnect, host/server restart, save/import interruption, and interruptions around irreversible transaction commits. Screenshots, fake client coordinates, or successful compilation alone do not establish a playable milestone.
