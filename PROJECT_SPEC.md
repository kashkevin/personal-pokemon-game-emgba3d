# Project specification

Pokémon Emerald private multiplayer: every established requirement in one place, as of 2026-10-09.

This file lists requirements only. It does not say what is built or tested; see
`FEATURE_STATUS.md` for that and `DEVELOPMENT_ROADMAP.md` for the work order. The
original brief and amendments stay preserved verbatim in `docs/project-*.txt`. If this
summary disagrees with a source, the source wins and this file should be corrected.

## How to read this

- Every requirement ends with source tags (key below).
- Precedence: a later amendment overrides an earlier one, and a later direct owner
  instruction overrides both [agents]. Where a newer rule replaced an older one, the
  newer rule is stated and the replacement is noted.
- "Pending" means the owner has not decided yet. Section 7 holds the binding decisions
  and the open wild-spawn conflict; section 8 lists the other open decisions.

| Tag | Source |
| --- | --- |
| [brief] | `docs/project-brief.txt` (original brief) |
| [gen6] | `docs/project-update-gen6.txt` |
| [lsr] | `docs/project-update-local-soft-reset.txt` |
| [cfc] | `docs/project-update-customization-friendship-shiny-charm.txt` |
| [vis] | `docs/project-update-maximum-visuals-visible-wild-riding-time.txt` |
| [spec] | `docs/master-spec.md` |
| [road] | `docs/development-roadmap.md` |
| [hand] | `PROJECT_STATUS_AND_HANDOFF.md` |
| [readme] | `README.md` |
| [agents] | `AGENTS.md` |
| [audit] | `docs/native-migration/feature-status.md` |
| [base] | `docs/native-migration/baseline.md` |
| [bal] | `src/emerald_multiplayer/balance.py` (values and comments) |
| [sw] | `src/emerald_multiplayer/shared_world.py` (module docstring) |
| [tf] | `src/emerald_multiplayer/trade_friendship.py` (comment at `MAX_STORED_MOVE`) |
| [eng-bal] | engine `include/constants/multiplayer_balance.h` |
| [eng-owe] | engine `src/wild_encounter_ow.c` (comment above `OWE_RUN_RETURN_DISTANCE`) |
| [eng-rtc] | engine `src/rtc.c` (comment in `RtcCalcLocalTime`) |
| [dir] | Owner directive of 2026-10-09 on the native PC migration. Not yet saved as a file in `docs/`; referred to by [base] and [audit]. |

"Engine" means our pokeemerald-expansion fork; exact revisions are in [base].

## 1. Game identity and scope

- A private game for 1-4 players in total, including the host, for the owner and
  friends. Not a commercial release and no public ROM distribution. [brief] [spec] [readme]
- Emerald provides the visual, world and technical foundation. Vanilla Emerald
  mechanics are kept only where this spec does not override them. Pinned engine base:
  RHH pokeemerald-expansion `expansion/1.17.1` (`bb1093a7c`). [brief] [spec] [readme]
- Hoenn is the first region and the only one to build and polish for now. [gen6] [spec]
- Multiplayer is the core of the game. It is available as soon as a player has chosen
  a starter and entered the world, with no Elite Four or endgame gate. [brief] [spec]
- No global mode is forced (co-op, FFA, 2v2). Every player exists independently in the
  shared world and decides how to interact. [brief]
- Keep the full, ambitious vision. Do not quietly simplify it into ordinary Emerald
  multiplayer or drop a feature; if something is not feasible, explain the limit, why it
  exists, the alternatives and a recommendation. [brief]
- Do not fake features: a system counts as complete only after its real gameplay
  lifecycle has been tested (a second sprite is not multiplayer; a Trade button is not
  trading). [brief] [agents]
- Do not download or distribute commercial ROMs. The planned download contains our
  application, runtime and modification patch, and each player imports their own game
  dump once. Review code and asset terms before distribution; a patch alone does not
  grant permission for its contents. [brief] [spec]

## 2. Core Pokémon

### Roster and mechanics

- Roster: standard species from Generations 1-6, National Pokédex 1-721. Alternate
  forms and Mega forms need their own explicit catalogue. (Replaces the original
  Gen 1-5 / 649 target.) [gen6] [spec]
- Mechanics: Generation 6 for stats, typings, abilities, moves and move behaviour,
  damage and battle rules, held items, evolution methods, type chart and status. Use the
  completed Gen 6 rules and document XY vs ORAS differences where they change play.
  Never mix in Gen 7+ rules silently. (Replaces the original Gen 5 baseline.) [gen6] [spec]
- Fairy type is included, with the Gen 6 type chart and the Gen 6 retypings (for
  example Clefairy, Jigglypuff, Gardevoir, Mawile, Marill, Azumarill). (Replaces "no
  Fairy".) [gen6] [spec]
- Gen 6 species take part in every system: wild encounters, rarity, shinies, trading,
  PvP, followers, abilities, moves, evolution and Mega Evolution. [gen6]

### Starters

- Each player independently picks one of 18 traditional starters on a custom selection
  screen. Duplicates are allowed, including all four players picking the same one.
  [brief] [gen6] [spec]

| Gen | Choices |
| --- | --- |
| 1 | Bulbasaur, Charmander, Squirtle |
| 2 | Chikorita, Cyndaquil, Totodile |
| 3 | Treecko, Torchic, Mudkip |
| 4 | Turtwig, Chimchar, Piplup |
| 5 | Snivy, Tepig, Oshawott |
| 6 | Chespin, Fennekin, Froakie |

### Wild encounters

- Species are randomized from eligible Gen 1-6 evolutionary families with rarity
  weighting (common, uncommon, rare and very rare are possible tiers). Starters can
  appear. Legendary and Mythical Pokémon never appear in ordinary wild encounters; they
  belong to events and special content. [brief] [gen6] [spec]
- Early encounters are mostly low-level basic forms. Rare strong families (for example
  Bagon, Larvitar, Gible, Axew, Deino, Riolu, Honedge, Goomy) can appear early, but at a
  low level and base stage. Evolution stages and levels open up with progression.
  [brief] [gen6] [spec]
- Visible overworld Pokémon are the primary presentation: the spawn system picks the
  species first and shows it in a fitting environment (land, sky, water where
  practical; rare spawns visibly rare). The battle starts when the player approaches,
  touches or interacts with it. Traditional hidden encounters stay possible for chosen
  areas, modes or settings. (Replaces invisible random encounters as the primary
  presentation.) [vis] [spec]
- Each player gets independent encounter rolls: two players in the same grass can meet
  different Pokémon. [brief] [gen6] [spec]
- Whether a visible spawn is personal or shared is an open conflict: see section 7,
  "Decision pending - owner to confirm". [audit] [dir]

### Shinies and the Shiny Charm

- Shinies remain possible and must look correct in battle, as followers and, where
  reliable palettes exist, in the overworld before the battle starts. Never silently
  choose a new shiny rate. Visibility, the world clock and attempt counters never change
  shiny odds or a World Event's identity. [brief] [vis] [spec]
- Research and document the exact Gen 6 base odds and Charm behaviour before
  implementing them; the approved values are in section 7. [cfc] [spec] [eng-bal]
- The Shiny Charm is a permanent, player-specific, non-tradable, non-consumable key
  item. It is kept through defeat, disconnect and reload and is never shared with
  teammates. [cfc] [spec]
- It improves that player's personal wild rolls and eligible personal/static rolls,
  including Local Soft Reset hunts. It never changes World Event generation or an
  event's shiny status. [cfc] [spec]
- It is a major Game Corner prize: players earn a separate fictional coin currency and
  then buy it. The purchase is guaranteed, never a random prize roll. It is expensive but
  does not require a complete Pokédex or the postgame. No real money, cryptocurrency,
  Robux, external purchases or real-world wagering. Reuse Emerald's casino systems where
  compatible; multiplayer casino games are optional later work. [cfc] [spec]

### Mega Evolution

- Include every officially released Mega Evolution for eligible Gen 1-6 species,
  including Megas added after Gen 6; check the current official list when implementing.
  A later Mega whose base species is post-Gen 6 does not add that species to the roster;
  ask the owner first. [gen6] [spec]
- Later Megas use their official appearance, typing, base stats, ability and stone,
  adapted to the Gen 6 engine. Document any conflict and propose the closest faithful
  behaviour before changing it. Z-Moves, Dynamax, Terastallization and Primal Reversion
  are not included by this rule. [gen6] [spec]
- One Mega Evolution per trainer per battle: each human in a 2v2 and each AI trainer
  (for example a Gym Leader and their Twin) gets one; never one per side. [brief] [gen6] [spec]
- Players do not start with Mega access. A Key Stone/Bracelet unlocks through
  progression, possibly before the postgame. [brief] [spec]
- Mega Stones can be bought and are deliberately expensive, so early and mid-game
  choices matter; wealth later makes collecting easier. Events and rewards can also give
  stones, and a successful Mega event may give that Pokémon's stone. [brief] [gen6] [spec]
- Design capture, form duration and reversion rules before an event Mega is stored as
  an ordinary Pokémon. [spec]

### Time-based mechanics

- Follow Gen 6 time-of-day rules for evolutions and other mechanics, auditing the
  complete Gen 1-6 list (for example Eevee to Espeon/Umbreon, Riolu to Lucario, Amaura
  to Aurorus). Never remove a legitimate day/night requirement for convenience. [vis] [spec]
- Time of day can weight or filter spawns, but must not make large parts of the
  Pokédex practically unobtainable or change shiny odds. [vis] [spec]

## 3. Multiplayer

### Players, teams and rewards

- Players explore separately or together, with independent encounters and solo
  battles. Joining a server does not create a team. [brief] [spec]
- Each player owns their party, PC storage, inventory, money, progression/badges,
  rewards and statistics. There is no shared wallet or inventory. When teammates finish
  something together, each receives their own appropriate reward; a reward is never
  split. [brief] [spec]
- Teams have at most two players. Players invite, accept, leave and change teammates
  without restarting the world. Two teams can exist at the same time. [brief] [spec]
- Player interaction menu: invite to team, leave team, trade, challenge, double-battle
  challenge, view Trainer Card. [brief] [spec]

### Trading

- Trading is available from the start and does not need the Link Room. Both players
  pick an offer and explicitly confirm; any change cancels the confirmation. Ownership
  changes are atomic and survive crashes and rejoins. [brief] [spec]
- Ordinary trades keep IVs, nature, ability, moves, shiny status, level, EVs, original
  trainer and history. Trade evolution and traded eggs need deliberate, audited
  handling. [cfc] [spec]
- Pokémon that already know a post-Gen 6 move trade unchanged (binding decision 6,
  section 7). [tf] [audit]

### Battles

- PvP is available from the start. Build and stabilize 1v1 and 2v2 first. A 2v2 is two
  humans against two humans, each with their own party and ownership; each trainer
  brings a full party of up to six, so up to twelve Pokémon per side (binding decision
  7). [brief] [spec]
- A custom 1v1v1v1 (four independently hostile trainers) comes later, researched and
  built as its own project without destabilizing conventional battles. [brief] [spec]
- Optional wagers use only fictional in-game money. Both sides confirm the amount
  before the battle; team wagers respect each player's own wallet; nobody loses money by
  accident and there is no silent automatic forfeit. Pot, ties, interruptions and
  forfeits need deliberate rules (pending). [brief] [spec]
- Championship: four players, two semifinals, then a final between the winners.
  Available early, without finishing the campaign. Possible statistics: entries, wins,
  PvP wins/losses, win streak, 1v1 and 2v2 records. Optional buy-ins and rewards follow
  the individual-wallet rules. [brief] [spec]

### Player friendship and Lucky trading

- Every pair of players has its own lasting relationship: New, Good, Great, Ultra,
  then Best Friends. It grows mainly through meaningful play together, with limits
  against AFK farming. It is separate from team membership, never gates trading or
  teams, and is never reduced by PvP, wagers, Championships or opposing teams.
  [cfc] [spec]
- Higher friendship raises the chance that an eligible trade becomes Lucky; Best
  Friends have the highest normal chance. A Lucky Pokémon keeps a permanent, visible
  Lucky status and a better minimum IV floor. No IV is ever lowered or raised above the
  legal maximum, and Lucky does not mean perfect. Species, shiny status, Mega
  eligibility, event identity, original trainer/history, level and moves are kept where
  appropriate. [cfc] [spec]
- Best Friends can rarely become Lucky Friends: their next eligible successful trade
  together is guaranteed Lucky, and only that trade uses the flag. Cancels, failed
  commits, retries and reconnects never lose it or repeat it. Both players are notified,
  and the state shows in the Friends/Players screen with progress, team status and
  online status. [cfc] [spec]
- Pair records are server-authoritative and restored after reconnect; no local save
  can rewrite a relationship. Keep original trainer, received-from, trade date and Lucky
  history where practical. [cfc] [spec]
- Build order: reliable trading, then pair persistence and progression, Lucky
  conversion and presentation, Best Friends and Lucky Friends, then the Friends UI.
  [cfc] [spec]

### Saves and recovery

- A player can disconnect and later rejoin with Pokémon, party/storage, inventory,
  money and progression intact. Shared world state persists. Saves are protected from
  partial writes, stale snapshots, duplicate ownership and duplicated payouts.
  [brief] [spec]
- Versioned character and world schemas with build/ruleset compatibility checks;
  backups; migrations tested on copies. Never discard a character because the roster or
  configuration changed, and never merge conflicting offline/online characters
  automatically. [spec]
- Autosave every five minutes, on by default, with a persistent per-character off
  switch and manual saving (binding decision 10). An overdue autosave waits until a
  safe checkpoint is allowed, missed ticks coalesce, and the next interval starts after a
  successful save. The launcher's Save now is a verified host checkpoint; an ordinary
  in-game Save alone is not a host commit. [spec]
- If the host is lost, everyone saves and disconnects (binding decision 8). Each client
  detects the loss, stops ordinary play and keeps its local recovery save for exact
  verification on rejoin; it never claims an upload it cannot prove. [spec]
- An interrupted multiplayer battle waits until every participant reconnects (binding
  decision 9): no automatic winner, penalty or cancellation. Normal saving never
  overwrites a character with a temporary battle party or bypasses an unsettled trade.
  [spec]
- Lifecycle tests cover menus/pause, separate local battles, map entry/exit, slow or
  partial network delivery, disconnect/reconnect, host/server restart, save/import
  interruption and interruptions around irreversible commits. [spec]

### Local Soft Reset (shiny hunting)

- A player can reset their own eligible personal/static encounter: reload just before
  it when practical and roll a new legitimate encounter. The server, that player's
  connection, shared world state and every other player's position, battle, trade,
  progression, Pokémon, inventory and money are untouched. It is an encounter-state
  operation, not a server or game reboot. [lsr] [spec]
- While connected, the classic soft-reset buttons trigger this instead of rebooting
  where practical, with an optional "Reset this encounter?" Yes/No prompt. [lsr] [spec]
- Attempts are counted per eligible hunt. The counter is informational and never
  changes odds; the attempt that produced a shiny may be recorded for statistics and the
  Trainer Card. [lsr] [spec]
- World Events are excluded: no reroll of species, Mega status, shiny status, rarity,
  rewards or any other event property. Normal wild encounters keep their normal
  mechanics. Resets work at any world time as long as the encounter's own conditions are
  met. [lsr] [vis] [spec]

### Hosting and network

- The owner's Windows PC hosts over home Wi-Fi. Friends on the Internet connect
  directly through a configured game port and matching firewall rule. Keep the host awake
  during sessions. No paid hosting or public matchmaking. [spec] [readme]
- Prefer a simple host/client design that reliably serves four friends over MMO-scale
  infrastructure. No MMO-grade anti-cheat is needed, but obvious desync and duplication
  must be prevented. [brief]

## 4. World and exploration

### Trainer appearance

- Every player creates a distinct Trainer near the start, before or around entering the
  multiplayer world, not limited to Brendan/May. Targets: base/body, skin tone, hair
  style and colour, hats, tops/jackets, bottoms, outfit colours, shoes, backpack and
  accessories. Options can be staged. [cfc] [spec]
- The appearance is saved as a versioned part of the player's profile and synced as
  compact IDs, so every client shows the same Trainer in every needed state: idle and
  walking in four directions, running, biking, surfing, fishing and the other Emerald
  avatar states. A standing-only creator is not enough. [cfc] [spec]
- Later changes (wardrobe, mirror, shop or menu) update the profile and all connected
  players. Cosmetic rewards (Gyms, Championships, PvP, events, exploration, regional
  stores, quests, challenges) give no combat stats. The Trainer Card shows the Trainer
  and multiplayer statistics; it comes after the multiplayer foundations. [cfc] [spec]

### Followers

- Eventually the full Gen 1-6 roster and approved forms, including shiny and
  legitimately represented Mega overworld forms. Players choose a party follower, see
  other players' followers and interact with their own. Paths, running, transitions and
  indoors are synchronized for every observer. Possible later: friendship messages,
  location reactions, occasional item finds. [brief] [gen6] [vis] [spec]
- Do not produce hundreds of follower assets before networking is proven. [gen6] [spec]

### Riding

- Riding is ground movement and cosmetics. A supported ride roster grows over time
  (examples: Arcanine, Rapidash, Tauros, Rhyhorn, Rhydon, Charizard, Tyranitar,
  Salamence, Garchomp, Zebstrika, Sawsbuck). [vis]
- Speed is common or tightly balanced, a modest gain over walking/running; the exact
  value is pending. Riding never grants Fly, Surf or any other traversal ability.
  [vis] [spec]
- Follower to mount to follower where supported. Rider alignment, collisions and
  mount/dismount show on every client; mount state is part of the synced appearance.
  [vis] [spec]

### Day/night and time

- One persistent world clock is shared by every connected player, with morning, day,
  evening and night and gradual palette transitions that work with weather, interiors,
  fades and accessibility. Rate: binding decision 1. Exact visual period boundaries are
  pending. [vis] [spec]
- World Events may use time of day, but major events must stay reachable for players
  with different real-world schedules. [vis] [spec]

### Visual direction and animation

- Goal: the most impressive dimensional presentation we can achieve while keeping the
  pixel-art identity: better tilesets and terrain, larger buildings, layered roofs and
  foreground, overlapping trees, elevation, shadows, animated water, grass and flowers,
  reflections, waterfalls, particles, fog, rain, storms, cave, window and street
  lighting, light shafts, better battle backgrounds and transitions, larger landmarks.
  The engine target for the new graphics is in section 6. [vis] [spec] [dir]
- Player animations: walking, dedicated running, a full fishing sequence (prepare,
  cast, splash, wait, bite, reel, encounter), idle, turning, interacting, ledges,
  cycling, surfing, doors, mounting/dismounting, using items, throwing Poké Balls,
  entering battle, victory. [vis]
- Pokémon move in species-appropriate ways (idle, walk, run, turn, hop, swim, fly or
  hover, sleep, react, follow). Battle sprites and effects cover front/back, shiny, Mega
  and forms, with idle, entrance, attack, damage, faint, status, Mega transformation,
  shiny sparkle and capture effects, without changing battle balance. [vis]
- Reuse the best legally reusable community assets first, check licenses and
  permissions, and improve them where it helps. Never delete previous working assets;
  keep originals recoverable. Keep an asset inventory: source and creator, license,
  coverage, animation states, status, improvements, missing frames, limits. [vis] [spec]
- Performance: budget for four players, followers, mounts, visible wild Pokémon, NPCs,
  weather and effects together, using culling, slower distant updates and effect caps;
  measure on real four-client scenes. Stable gameplay beats one more effect. Graphics
  never override save, trade, battle, ownership or recovery guarantees. [vis] [spec]

### Campaign and Gym Twins

- A solo challenger faces the normal Gym Leader. Two teammates face the Leader plus a
  custom Twin/Partner in a purpose-built double battle with coordinated strategies
  (weather, speed, screens/support, status, offence). Later AI trainers may Mega Evolve.
  [brief] [spec]
- Rewards and progression stay individual. Co-op story eligibility, badge advancement
  and mixed-progression rules must be decided before shared campaign scripts (pending).
  [spec]

### Regions

- Hoenn first. Later regions (Kanto, Johto, Sinnoh, Unova, Kalos) come one at a time,
  as content inside one game (never by combining ROMs), and only after Hoenn and the
  core multiplayer are stable. Supporting Gen 6 species does not mean building Kalos.
  Trainers, wild encounters and Gyms scale for existing progression. [brief] [gen6] [spec]

## 5. Events and progression

- World Events: the shared world schedules random timed events, notifies every
  connected player and requires travel to the location (no teleport). Categories: rare,
  Mega, Legendary, Mythical, shiny, shiny Mega, shiny Legendary/Mythical, and extremely
  rare shiny Mega Legendary where the species allows. [brief] [gen6] [spec]
- Events use the Gen 1-6 roster and any supported official Mega that meets the roster
  rule. Valuable events are extremely rare. Levels scale with player/world progression
  unless an event is deliberately a high-risk challenge. [brief] [gen6] [spec]
- Event IDs, timers, participation, claims and despawn/recovery stay consistent on all
  clients. Rewards stay per player. [spec]
- Capture: the first player to catch the event Pokémon wins it (binding decision 4).
  [sw] [bal]
- Pending: event timers during server downtime, and mixed-progression scaling. [spec]
- Legendary and Mythical Pokémon come mainly from events and special content. [brief] [spec]
- Rewards are per player for money, items, Gym rewards, event participation, quests and
  Championships; a single reward is never divided. [brief]
- Mega unlocks, Mega Stones and the Shiny Charm: see section 2.
- Listed as planned in the native-migration feature list, with no requirement text yet:
  a multiplayer Pokémon League and expanded endgame systems. [audit]

## 6. Platform, graphics and UI targets

### Delivery (still in force)

- A Windows download with one entry point and Host Game / Join Game. The runtime is
  bundled, so friends need no compiler, Python, WSL, VPN or manual emulator scripts.
  [spec] [readme]

### Native PC migration (newest directive, 2026-10-09)

- Migrate the game to a native standalone Windows .exe with no emulator, on branch
  `claude/native-pc`. The emulator build stays the fallback until the native build
  passes equivalent gameplay tests. [dir] [base]
- Keep the Python host and companion. Replace the mGBA Lua bridge with a native bridge
  that preserves the protocol. [dir]
- Native saves keep the GBA save byte layout (byte-identical save blocks), or every
  reader and stored checkpoint must be migrated. [base] [audit]
- The no-ROM-distribution rule and the own-dump import still apply. Today's import
  patches a GBA ROM and launches mGBA, so it must be reworked for the native build.
  [spec] [audit]
- Graphics: adopt the enhanced dimensional overworld graphics of
  ZallaxDev/pokeemerald-3Ds-dualscreen (graphics only, not its dual-screen interface),
  using ZallaxDev/pokeemerald-voxel-project's native PC Diorama renderer as the
  technical base. [dir]
- The renderer stays separate from authoritative gameplay state. [dir]
- UI: a single-screen PC interface starting at 1920x1080, with keyboard and controller
  support. [dir]
- Milestones, in order: A native engine; B gameplay integration; C native
  multiplayer; D enhanced graphics (the highest priority once the native engine is
  stable); E single-screen UI; F visual integration of all gameplay systems; G regression
  parity with the emulator build. [dir] [base]
- Development toolkit: pytest, sanitizers and static analysis, native C tests, a
  multiplayer harness with application-level network simulation, a graphics benchmark
  scene, CI workflow files. [dir]
- Precedence note: earlier texts assume a GBA ROM run by an emulator and keep the 2D
  engine ("do not attempt to convert the engine into true polygonal 2.5D/3D" [vis];
  "retain the 2D Emerald/expansion engine" [spec]). For the native build this newer
  directive decides the runtime and the renderer. The visual goals, performance rule,
  asset-preservation rule and all gameplay rules in sections 2-5 still apply. [vis] [spec] [dir]

## 7. Binding owner decisions

| # | Decision | Decided | Recorded in |
| --- | --- | --- | --- |
| 1 | Day/night: one world day per two real hours (world clock at 12x real time), paused while nobody is online. | 2026-10-09 | [bal] [sw] [eng-rtc] |
| 2 | Visible wild spawns are personal: each player has their own. **Conflicts with the newest directive; see below.** | 2026-10-09 | [audit] |
| 3 | Running from a visible wild Pokémon leaves it in the world ("it stays for others"). [audit] records what the code actually does: the Pokémon reappears only in the runner's own game; only World Events are shared. | 2026-10-09 | [eng-owe] [audit] |
| 4 | World Events: the first player to catch it wins; running, losing or defeating it leaves it for everyone until the timer ends. | 2026-10-09 | [sw] [bal] |
| 5 | Balance values: the recommended defaults in `balance.py`, with the ROM-side values mirrored in the engine header (table below). | 2026-10-09 | [bal] [eng-bal] |
| 6 | Pokémon that already know a later-generation move (for example Leafage, 633) trade unchanged; moves newly learned on evolution still use the Gen 6 bound. | 2026-10-09 | [tf] [audit] |
| 7 | 2v2 uses each trainer's full party (up to six). | 2026-10-08, listed again 2026-10-09 | [spec] [audit] |
| 8 | If the host is lost, everyone saves and disconnects. | 2026-10-08, listed again 2026-10-09 | [spec] [audit] |
| 9 | An interrupted battle waits for every player to reconnect. | 2026-10-08, listed again 2026-10-09 | [spec] [audit] |
| 10 | Autosave every 5 minutes, plus manual save, plus a persistent per-character on/off toggle (on by default). | 2026-10-08, listed again 2026-10-09 | [spec] [audit] |
| 11 | Missing legacy trade-handler friendship values use the Gen 6 species base; known values are kept. | 2026-10-09 | [hand] |

### Approved default values (decision 5)

| Area | Values | Source |
| --- | --- | --- |
| World clock | 12x real time; runs only while at least one player is connected; world day 0 starts at 08:00 | [bal] [sw] |
| Overworld notices | stay available 8 seconds | [bal] |
| World Events | first event after 10-20 min, then one every 25-45 min; 15 min duration; category weights rare 50, legendary 28, mega 15, mythical 5, mega legendary 2; shiny chance 1/64 (host roll); level = progression level + 3 (rare) or + 8 (legendary), kept within 5-70; a claim is released 120 s after the claimant disconnects | [bal] |
| Friendship | New/Good/Great/Ultra/Best Friends at 0/30/120/300/600 points; points: trade 15, battle together 12, battle against 6, Championship 10, event together 10, Gym together 20, session together 2 (per 30 min together); cap 60 points per pair per real day | [bal] |
| Lucky | Lucky trade chance 5/8/12/20/30% by friendship level; Lucky IV floor 12 (never lowered, max 31); Lucky Friends chance 10% per eligible Best Friends interaction, 12 h cooldown | [bal] [eng-bal] |
| Wagers | 100 to 100,000 in-game money | [bal] |
| Shiny odds and Charm | personal roll 1/4096 (Gen 6); the Charm gives 1/2500 (Update 30), the Safari Zone 1 extra roll (1/2048.3, with the Charm 1/1024.4); eggs 1/4096, 1/1365.7 with a shiny parent or the Charm, 1/683 with both; the Charm costs 100,000 Game Corner coins (Update 29; the Coin Case holds up to 999,999) and is guaranteed | [eng-bal] |
| Mega Stones | 4,500-15,000 Game Corner coins each by Mega form (Update 29; every Game Corner coin price cut to 15% on 2026-10-25), sold by the Mauville City Poké Mart dealer once the player has the Mega Ring (3,750 coins at the Game Corner prize counter; the Shiny Charm 15,000) | [eng-bal] |

The code cites `docs/balance-defaults.md` as the written copy of these values; that file
does not exist [audit]. This section is the written record until it does.

### Wild spawn ownership - Decision pending - owner to confirm

- Earlier owner decision (2026-10-09): visible wild spawns are **personal**, each
  player's own, and running from one leaves it in the world. [audit] [eng-owe]
- Newest directive (2026-10-09, native PC migration): lists "Shared wild spawns",
  "shared multiplayer spawns" and "server-authoritative shared wild spawns". [dir] [audit]
- On the emulator baseline, spawns are personal and nothing about them is networked;
  the only shared spawn is the World Event. Details in `FEATURE_STATUS.md`. [audit]
- Not resolved here. If shared spawns are chosen, the owner must also settle
  shared-spawn RNG and the personal Charm, mixed-progression eligibility, and the
  catch/defeat/run/disconnect/crash rules before implementation. [spec]

## 8. Other open decisions

- Wager pot, ties, interruptions and forfeits. [spec]
- World Event timer behaviour during server downtime or empty sessions; mixed-progression
  event scaling. [spec]
- Co-op campaign: story eligibility, badge advancement, mixed progression. [spec]
- Whether teams persist across disconnect or restart (they are session-local today).
  [audit]
- Later-Mega adaptations (for example Dragonize 20% vs 30%, Mega Sol, Eternal Floette
  and Zygarde Complete prerequisites, Rayquaza via Dragon Ascent), and Mega capture,
  form duration and reversion rules. [audit] [hand] [spec]
- Exact mount speed; exact visual day/night period boundaries; the exact Gen 6
  evolution hour boundaries (still unknown from the inspected evidence). [spec] [audit]
- Lucky questions the default values do not settle: secondary Lucky benefits, repeated
  Lucky conversion, treatment of both sides of a Lucky trade, IV changes that alter
  Hidden Power's type. [road]
- Original-world geography policy before upgrading any original world. [hand]
- Final distribution permissions for bundled code and game assets. [spec] [hand]

## 9. Working rules

- Before building any major system, inspect the pinned engine, its maintained upstream,
  official documentation and compatible community projects. Check exact revision,
  license and attribution, dependencies, maintenance, known issues, save compatibility,
  multiplayer conflicts and measured performance. Prefer a maintained compatible
  implementation; record incorporated sources in `docs/dependency-ledger.md`.
  [agents] [cfc] [spec]
- Keep foundational multiplayer first (order in `DEVELOPMENT_ROADMAP.md`). [agents] [road]
- Never remove or rebalance an established gameplay rule while adding features. For a
  genuine compatibility conflict, explain it and get the owner's decision; routine
  implementation choices within accepted rules need no approval. [agents] [brief]
- Values not covered by decision 5 (for example mount speed) stay explicitly pending.
  [agents] [bal]
- Small commits, meaningful tests, known-good tags and private backups. Diagnose a bug
  before stacking fixes; never destroy a working system without preserving it.
  [agents] [brief] [spec]
- No commercial ROMs, player credentials, saves, databases or private build artifacts
  in Git. [agents]
- Do not infer playable acceptance from compilation, fixtures or screenshots. Record
  actual-core tests and their limits separately; test multiplayer with real clients.
  [agents] [brief] [spec]

## 10. Amendment history

Later rows override earlier rows. Dates are when each file was first committed;
[spec] gives the same dates for the Gen 6 update (October 7) and the visual/world
amendment (October 9).

| Date | File | Topic | Effect on earlier rules |
| --- | --- | --- | --- |
| 2026-10-07 | `docs/project-brief.txt` | Original brief: private 1-4 player Emerald multiplayer; Gen 1-5 roster (649), Gen 5 mechanics, no Fairy; Megas; free-form teams; trading and PvP from the start; 1v1, 2v2, later 1v1v1v1; wagers; Championship; Twin Gyms; World Events; followers; saves; regions; phases 0-12; testing rules. | Base text. Its roster, mechanics and Fairy rules were replaced by the Gen 6 update. |
| 2026-10-07 | `docs/project-update-gen6.txt` | Gen 1-6 roster; Gen 6 mechanics; Fairy; all official Megas including later ones; 18 starters; Kalos added to the region list. | Overrides Gen 1-5, Gen 5 and no-Fairy. |
| 2026-10-07 | `docs/project-update-local-soft-reset.txt` | Multiplayer-safe Local Soft Reset for personal/static shiny hunts; World Events excluded. | Addition only. |
| 2026-10-07 | `docs/project-update-customization-friendship-shiny-charm.txt` | Three amendments: customizable Trainers plus the project-wide research-and-reuse rule; player friendship and Lucky trading; personal Shiny Charm bought at the Game Corner. | Additions only. |
| 2026-10-09 | `docs/project-update-maximum-visuals-visible-wild-riding-time.txt` | Maximum fake-2.5D visuals; visible wild Pokémon; shared-spawn investigation; ground riding; day/night; Gen 6 time mechanics; complete graphics and animation upgrade mission. Testing resumed. | Visible wild Pokémon replace invisible random encounters as the primary presentation. |

Owner decisions and directives that are not `docs/project-*.txt` files:

| Date | Where recorded | Topic |
| --- | --- | --- |
| 2026-10-08 | [spec] | 2v2 full parties; autosave every 5 minutes with toggle and manual save; host loss means save and disconnect; an interrupted battle waits for all. |
| 2026-10-09 | [hand] | Missing legacy trade-handler friendship uses the Gen 6 species base. |
| 2026-10-09 | Code comments [bal] [sw] [tf] [eng-bal] [eng-owe] [eng-rtc]; summarized in [audit] | Clock rate and pause; personal spawns; running leaves the Pokémon; first catch wins; balance defaults; later-generation moves trade as-is. First written up in this file (section 7). |
| 2026-10-09 (newest) | Not yet a file [dir]; referred to by [base] and [audit] | Native PC migration (section 6). It lists shared wild spawns, which conflicts with decision 2. |

[brief]: docs/project-brief.txt
[gen6]: docs/project-update-gen6.txt
[lsr]: docs/project-update-local-soft-reset.txt
[cfc]: docs/project-update-customization-friendship-shiny-charm.txt
[vis]: docs/project-update-maximum-visuals-visible-wild-riding-time.txt
[spec]: docs/master-spec.md
[road]: docs/development-roadmap.md
[hand]: PROJECT_STATUS_AND_HANDOFF.md
[readme]: README.md
[agents]: AGENTS.md
[audit]: docs/native-migration/feature-status.md
[base]: docs/native-migration/baseline.md
[bal]: src/emerald_multiplayer/balance.py
[sw]: src/emerald_multiplayer/shared_world.py
[tf]: src/emerald_multiplayer/trade_friendship.py
