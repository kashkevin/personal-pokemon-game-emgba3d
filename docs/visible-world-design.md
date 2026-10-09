# Visible world, shared encounters and time: design recommendation

Research date: October 9, 2026. **Design only. No gameplay rule is selected or
enabled by this document.** It implements the requested planning step in the
[visual/world amendment](project-update-maximum-visuals-visible-wild-riding-time.txt),
read alongside the [master specification](master-spec.md),
[development order](development-roadmap.md) and
[reuse audit](customization-and-reuse.md). Build success, inherited source and
the proposed acceptance checks below are not playable acceptance.

## Accepted requirements and decisions still needed

Accepted: Emerald remains the 2D engine; improve depth through art, layers,
lighting, shadows, animation and composition. Visible Pokémon become the
primary ordinary encounter presentation while traditional encounters remain
available to appropriate content. Retain the Gen 1–6 family pool, rarity,
progression, ordinary Legendary/Mythical exclusion, personal ownership and
existing shiny rules. Synchronize visible entities, followers and ground
mounts. A mount never grants Fly, Surf or another traversal permission. Use
one persistent world time with morning/day/evening/night presentation and
Gen6 time-dependent mechanics. Multiplayer reliability takes priority over
additional decoration.

The amendment recommends investigating shared wild entities and temporary
first-initiator claims; it does not settle all their ownership rules. Earlier
independent personal encounter rolls and personal Charm effects therefore
cannot silently become global rolls. The following remain owner decisions:

1. Shared shiny identity versus personal Charm eligibility and independent rolls.
2. Mixed-progression spawn visibility, encounter eligibility and level selection.
3. Whether a confirmed escape consumes a shared spawn or returns that same
   Pokémon, and what HP/status it retains if returned.
4. Recovery of an unresolved wild encounter when its original process cannot
   return; no automatic timeout, reroll or reward is assumed.
5. World-clock speed, progress during empty sessions/downtime, visual boundaries,
   event access windows and any daily/calendar systems using that clock.
6. Spawn density, rarity weights, lifetimes, mount speed and final effect budgets.

The recommendations below are a concrete proposal for these decisions, not
permission to change them. Public shared-spawn activation depends on settling
the conflicting rules and proving the ownership path.

## What the current engine actually supplies

Inspected local engine: `/home/kevin/src/pokemon/engine-admission-cleanup-20261008-1`,
base `aef47e4b28fd6d0e84376961e0cc6632996bb0be` plus the preserved project
deltas. Inherited RHH baseline is
[`bb1093a7c72d3961d9a37d8e02ad2abc2c866682`](https://github.com/rh-hideout/pokeemerald-expansion/tree/bb1093a7c72d3961d9a37d8e02ad2abc2c866682)
(`expansion/1.17.1`). This is source evidence, not a claim that an arbitrary
binary has these capabilities enabled.

| Evidence in that engine | Reuse/adaptation consequence |
| --- | --- |
| `include/config/wild_encounter.h:5,20–39`: traditional encounters on; generated overworld encounters off; existing spawn, movement, sparkle and despawn switches | Reuse existing native presentation/generation primitives; replace local ownership decisions with a host-authorized adapter. Do not simply enable local generators on four clients. |
| `include/wild_encounter_ow.h:4`: `OWE_SPAWNS_MAX=4`; `src/wild_encounter_ow.c` | Existing local pool is a bounded starting point, not a global four-player spawn protocol or proven density. |
| `include/config/overworld.h:50,61`: species object graphics on; followers off | Existing graphics/follower code is reusable; remote follower state, asset coverage and resource arbitration remain work. |
| `include/config/overworld.h:92–97`: latest-generation time profile, time encounter tables off | A shared clock needs an adapter; enabling this switch alone would still use each client's local time source. |
| `src/rtc.c:331`, `src/pokemon.c:4193–4200`: time queries and evolution conditions | Reuse predicates behind one authenticated world-time interface. Audit other RTC consumers before changing a global function. |
| `src/multiplayer.c:285–314`: map/viewport filtering and guarded object/sprite/palette allocation | Extend existing interest filtering and allocation refusal. It does not currently replicate arbitrary wild entities, mounts or followers. |
| `src/multiplayer.c:20–37`, `include/multiplayer.h:7–9`: fixed 128-byte mailbox, three peers, checked local-ID partition | Add a separately versioned bounded entity capability; do not reinterpret reserved fields or collide with generated-wild IDs. |

Current maintained upstream still documents per-time encounter tables and
fallback behavior. Reuse its table tooling after auditing the randomized
family selector; it does not provide this project's shared spawn ownership.
[Maintainer tutorial](https://raw.githubusercontent.com/rh-hideout/pokeemerald-expansion/expansion/1.17.1/docs/tutorials/how_to_time_of_day_encounters.md),
[release history](https://github.com/rh-hideout/pokeemerald-expansion/releases).
No external code, library or artwork was incorporated for this document.
Asset selection, licenses and frame inventories belong in the separate
visual resource audit; this design does not authorize replacing that work.

## Recommended shared-spawn lifecycle

Give each entity a host-created, durable `spawn_id`, world/area instance,
generation, content/rules version, authoritative position, immutable encounter
identity, shiny presentation, spawn-time tick and progression policy. Distinguish
the world entity from the permanent owned-Pokémon serial: capture allocates or
consumes an exact reserved serial once, through the ownership transaction.
Neither proximity, a screenshot nor a client-side collision is capture proof.

Recommended lifecycle:

`available → claimed → encounter_active → terminal`, with a separate
`recovery_pending` state for uncertain outcomes. Only exact verified
pre-battle cancellation may return `claimed → available` automatically.

| Situation | Recommended result and durable boundary |
| --- | --- |
| Two players touch/interact simultaneously | Atomically accept one eligible request; host serialization determines the winner. Return the current claim to the other player without starting a second native encounter. No client timestamp wins arbitration. |
| Claim accepted | Persist claimant, lease, exact spawn generation, request ID and immutable encounter digest before native admission. Freeze that entity for other observers and show that it is engaged. |
| Admission refused before battle can start | Release only with exact native no-start/neutral-return evidence, then restore the same entity and properties. An uncertain command is not a refusal. |
| Capture | In one authoritative transaction, validate the native result, update claimant checkpoint/inventory/party or PC, publish the Pokémon's ownership and consume the spawn. Duplicate result requests return the same receipt. Never consume first and save later. |
| Defeat | Commit appropriate player rewards, resource use and the consumed spawn together. Other observers receive removal; they do not receive an extra copy of that battle's reward. |
| Successful Run / native forced escape after admission | **Recommend consuming the spawn without capture/reward**, with the claimant's legitimate battle costs saved. This avoids replaying the encounter to reroll its result. Returning the exact entity is an alternative requiring explicit HP/status/re-entry rules; it is not currently selected. |
| Blackout / defeat of the claimant | Recommend a terminal consumed encounter with the ordinary personal defeat consequences. Confirm this alongside the escape rule; do not infer extra shared penalties. |
| Player disconnects or process crashes | Move to recovery pending; keep others unable to claim. Preserve exact available emergency/result evidence. Reconnect and reconcile the same encounter before making it available or terminal. A lost socket is never proof that capture did not happen. |
| Host crashes or loses power | Restore spawn/claim/result rows from the same durable world database. A committed capture remains consumed; an unresolved claim stays reserved. Repeated packets and old leases cannot create another result. |
| Original process cannot return and no terminal proof exists | Keep the spawn quarantined and expose a clear recovery status. A safe verified rollback to the exact pre-admission state or an explicit abandonment policy needs separate design and testing. Do not quietly expire the lock. |
| Viewport culling, map unload or all observers leave | Remove only rendering subscriptions. Entity identity/claim state remains authoritative. World despawn is a separate host transition with a recorded reason. |
| Time period changes while entity is claimed | Never reroll or despawn the claimed entity. Time weighting applies when generating a new entity; its original identity survives retries and clock transitions. |

Use exact source/result revisions and typed native authority, as established by
`src/emerald_multiplayer/trade_storage.py`, `trade_effect_backend.py`,
`battle_reservations.py`, `reset_attempts.py` and `emergency_save.py`; these are
patterns to adapt, **not existing shared-wild implementation**. Capture needs
a genuine native result barrier and durable spawn linkage. Polling party bytes
or accepting a client-supplied species is insufficient.

Claim retries must bind world, actor, current lease, spawn/generation and request
ID. Persist every terminal receipt before replying. Reject stale claims after
restart. A snapshot plus ordered entity revisions lets reconnecting observers
recover without replaying historical animations. Keep spawn-generation RNG,
battle RNG and decorative animation RNG separate. Resending a snapshot, losing
an observer, changing an animation rate or lowering visual quality must never
advance encounter RNG.

## Shared shiny identity and personal Charm conflict

These requirements cannot all be assumed equivalent: one fixed shiny Pokémon
visible to everyone; independent personal rolls; a Charm that benefits only
its owner; and unrestricted first-player capture of that same entity.

| Candidate rule | What it would change |
| --- | --- |
| One shared base roll, no personal modifier | Clear shared appearance; would remove the accepted personal Charm benefit from these encounters unless another approved personal path supplies it. |
| Creator/nearest/highest-Charm player's roll becomes shared | Gives other players a personal bonus they did not own and makes proximity/joins affect odds. Not recommended. |
| Apply the claimant's Charm on interaction | Preserves a personal roll but can change apparent shininess after the Pokémon was already visible. Conflicts with reliable shiny overworld identity unless an explicit presentation rule changes. |
| Personal shiny projections / separate personal lanes | Preserves personal modifiers, but observers may see different shiny states or different claimable Pokémon. Needs explicit approval of what “same Pokémon” means. |

**Recommendation:** keep shared rare/event identity immutable, and offer a
clearly distinguished personal encounter lane for personal rolls if the owner
accepts that split. Do not silently recategorize all ordinary wild encounters
as events or disable Charm there. Until the owner selects a rule, a shared
technical prototype uses controlled fixtures rather than claiming a new shiny
economy. No numerical odds or Charm reroll count is chosen here.

Native generation must also prove that the observed shiny identity survives
claimant-specific original-trainer data, capture, storage, trading and fresh
Continue. Sharing a personality value alone is not proof of equivalent shiny
behavior. A missing shiny overworld palette needs an explicit consistent visual
fallback; never show a knowingly incorrect normal palette as verified shiny
rendering. World Event shiny properties and Local Soft Reset exclusions stay
unchanged.

## Mixed progression recommendation

Prefer stable area/progression bands with an explicit eligibility policy,
rather than using the maximum or minimum badge count of whoever happens to
be nearby. Pin species, evolutionary stage and level when the entity is
created; do not level it up when a stronger player approaches or weaken it
when another player leaves. Validate claimant eligibility before a claim.

The owner still must choose between shared visibility with some encounters
marked unavailable to earlier players, and progression-specific encounter
instances. The latter provides personal scaling but means the area is not one
universal spawn pool. Neither permits advanced players to inject unrestricted
endgame spawns into a beginner's ordinary pool. Party strength must not replace
the accepted progression rules. Teams do not merge badges, inventory or rewards.

Static personal encounters and special events retain their own ledgers and
policies; a visible sprite does not convert them into ordinary shared wild
entities. Repels, fishing, Surf access, scripted encounters and encounter-free
areas each need an explicit adapter. Do not blanket-disable traditional engine
encounters before those adapters are verified.

## Persistent shared clock recommendation

| Model | Benefit | Cost / unresolved behavior |
| --- | --- | --- |
| Host local wall clock | Familiar real-life day/night | Host timezone, daylight-saving changes and manual clock edits affect everybody; fixed schedules exclude players with limited availability. |
| Server UTC with a fixed world offset | One stable civil-time basis; independent of each client | Still ties access to real hours; downtime catch-up and wall-clock corrections need policy. It does not require a paid server—the host is this project's server. |
| Persistent accelerated world time | All players can reach different periods in ordinary play; visual transitions remain shared | Rate and offline/empty-session progression must be selected; game time must not accelerate network deadlines or unrelated reward calendars. |

**Recommend the third model:** one persisted logical world clock, advanced by
the host's monotonic elapsed time while the world is actively played. Recommend
pausing advancement while the service is stopped or no player is active so
unattended periods do not consume event access. These are recommendations for
approval, not selected settings; no multiplier, cycle duration or grace period
is prescribed.

Persist world ID, clock generation/version, logical tick and chosen mode/rate.
Use monotonic elapsed time within a boot; do not derive play time by subtracting
arbitrary client wall clocks. On restart resume no earlier than the last
authoritatively committed tick. Durably pin a time-dependent gameplay decision
to its action/result ID so a lost reply cannot retry under another time period.
Bound and version any permitted clock adjustment rather than silently rewriting
past spawn/evolution decisions.

Clients receive authenticated tick/period snapshots and may interpolate only
the display. Stale time data cannot authorize a new time-restricted action.
Restore clock authority before showing time-dependent availability on rejoin.
Palette interpolation must not determine eligibility. Keep four visual periods
separate from the binary day/night evolution predicate. Darkness in a cave is
not night, and an interior's fixed palette does not override world time.

Use normal monotonic real-time deadlines for network leases, autosaves, battle
recovery and shutdown. Do not accelerate those when accelerating world time.
Audit berries, daily flags, Pokérus, Shoal Cave, weather and timed events before
routing them to the new clock; changing their calendar behavior is outside
this recommendation. Event expiry during downtime needs explicit approval.

## Gen 1–6 time-dependent evolution audit

The complete standard-species enumeration below was independently checked
against the maintained PKHeX project's generation-specific source data at
`66ef5983a5d349efa2dd615f2926a1b1ee97306e`. Its Gen6 tree selects `evos_g6.pkl`
with the ORAS personal table. Read-only decoding inspected species 1–721,
using its documented 16-bit container and eight-byte branch layout; methods
2, 3, 19, 20, 32 and 33 yield **ten branches across nine starting species**.
[Gen6 tree selection](https://github.com/kwsch/PKHeX/blob/66ef5983a5d349efa2dd615f2926a1b1ee97306e/PKHeX.Core/Legality/Evolutions/EvolutionTree.cs),
[branch decoder](https://github.com/kwsch/PKHeX/blob/66ef5983a5d349efa2dd615f2926a1b1ee97306e/PKHeX.Core/Legality/Evolutions/EvolutionSet.cs),
[method definitions](https://github.com/kwsch/PKHeX/blob/66ef5983a5d349efa2dd615f2926a1b1ee97306e/PKHeX.Core/Legality/Evolutions/Methods/EvolutionType.cs).

| Starting Pokémon | Evolution | Gen6 trigger and time requirement |
| --- | --- | --- |
| Eevee | Espeon | Level up with sufficient friendship, daytime |
| Eevee | Umbreon | Level up with sufficient friendship, nighttime |
| Gligar | Gliscor | Level up holding Razor Fang, nighttime |
| Sneasel | Weavile | Level up holding Razor Claw, nighttime |
| Budew | Roselia | Level up with sufficient friendship, daytime |
| Chingling | Chimecho | Level up with sufficient friendship, nighttime |
| Happiny | Chansey | Level up holding Oval Stone, daytime |
| Riolu | Lucario | Level up with sufficient friendship, daytime |
| Tyrunt | Tyrantrum | Level up at level 39 or above, daytime |
| Amaura | Aurorus | Level up at level 39 or above, nighttime |

The [inspected data](https://github.com/kwsch/PKHeX/blob/66ef5983a5d349efa2dd615f2926a1b1ee97306e/PKHeX.Core/Resources/byte/evolve/evos_g6.pkl)
is 4,570 bytes, SHA-256
`270a7348b07f96c95c37821d17c4b6fe9e2b2526719af7229807587f729ef48a`.
This is primary implementation/data research, not a cartridge execution proof.
No PKHeX source or binary dataset was incorporated into the game; its
[GPL-3.0 license](https://github.com/kwsch/PKHeX/blob/66ef5983a5d349efa2dd615f2926a1b1ee97306e/LICENSE)
was inspected as research provenance only.

The local engine contains corresponding branches in
`src/data/pokemon/species_info/gen_1_families.h:14912,18217`,
`gen_2_families.h:4894,5664`, `gen_3_families.h:6034,10232`,
`gen_4_families.h:4662` and `gen_6_families.h:4581,4725`.
However, it also includes alternative direct-item branches for some held-item
evolutions and later-generation regional evolutions. Those must not become
accepted Gen6 behavior merely because the engine supplies them. Sylveon's
Gen6 affection/Fairy-move requirement and Eevee evolution precedence require
a separate complete-mechanics audit; Sylveon is not an additional time branch.
Later-generation Lycanroc, regional variants and Ursaluna are not additions
to this ten-branch Gen6 list.

Two concrete configuration gaps remain:

- `include/config/pokemon.h:23` selects `GEN_LATEST` for friendship evolution;
  `src/pokemon.c:83` consequently selects 160 rather than the engine's pre-Gen8
  threshold of 220. Gen6 profile qualification must correct this deliberately
  and verify the real level-up/handler friendship path. This is Pokémon
  friendship, not the separately unbalanced player-friendship feature.
- `include/constants/rtc.h:53–63` labels a Gen6 visual profile with night
  starting at 21:00; the current latest-generation branch uses 20:00–06:00.
  The pinned evolution conditions call the same time enumeration. **Exact
  original XY/ORAS evolution-hour boundary equivalence remains UNKNOWN from
  the primary evidence inspected here.** Do not infer it from labels or adopt
  either current branch as proved cartridge behavior. Verify it before
  selecting the gameplay predicate; independently chosen visual twilight
  boundaries must never shorten or remove legitimate evolution eligibility.
  [Pinned time constants](https://github.com/rh-hideout/pokeemerald-expansion/blob/bb1093a7c72d3961d9a37d8e02ad2abc2c866682/include/constants/rtc.h).

Acceptance should exercise every branch immediately inside/outside the
confirmed boundary, below/at friendship or level thresholds, with/without the
required held item, with evolution cancellation, conflicting Eevee conditions,
reconnect and lost result replies. Clock changes alone do not trigger a
level-up evolution. Item consumption must occur only with its legitimate
successful evolution. None of these game tests ran for this design document.

## Resource budget and staging

Use measured resource admission, not an arbitrary promise of a fixed crowded
scene. Hard source ceilings are **16 object events**
(`include/constants/global.h:95`) and **64 engine sprites**
(`include/sprite.h:5`). `include/gba/defines.h:47–73` defines 512 bytes of OBJ
palette memory (16 four-bit palette banks) and 32 KiB OBJ VRAM in the normal
tile mode. These ceilings are shared with the entire engine; they are not
available solely to new Pokémon. Sprite dimensions, reflections and composite
riders may consume more than one allocation. Larger object limits also affect
saved object arrays (`include/global.h:1151`) and are not a harmless constant bump.

For every test map calculate:

`required objects = player avatars + active followers/mount actors + required NPC/script actors + visible wild actors + reserved transition actors`.

Four avatars plus four followers already leave only eight object slots before
NPCs/wild actors. A mount should replace that trainer's follower representation,
not duplicate the same Pokémon, but rider composition still needs measured
sprite/tile/palette costs. Reserve gameplay actors and transition headroom
before allocating optional scenery. Do not claim all four followers and a
full wild pool work on every existing map until the map audit proves it.

| Resource | Admission rule / recommended fallback |
| --- | --- |
| Objects and sprites | Reserve player, claimed encounter and necessary script actors first. Refuse additional spawn admission when the required representation cannot fit; do not evict an active claim or hide a nearby collidable actor. |
| Tiles and palettes | Record catalogue cost per species/form/shiny/rider combination; share compatible palettes/tiles only where visually correct. Never steal a live player's palette to render another wild Pokémon. |
| Animation CPU and transfer work | Full fidelity near the player; reduced decorative updates offscreen, with deterministic interpolation. Do not reduce authoritative movement/collision correctness or battle input updates. |
| Effects | Drop distant particles, extra reflections and optional light overlays first. Keep readable actors, interaction indicators and scene transitions. Local quality settings cannot change spawn availability or shiny results. |
| Network | Subscribe by map/area and bounded viewport interest; send reliable identity/claim/terminal events and bounded position updates. Derive decorative frames locally from versioned state. Measure bytes/second and tail latency with four clients. |
| World persistence | Persist live/claimed entities and required terminal receipts; choose bounded compaction with replay-safe retention. Do not accumulate every animation tick as an unbounded journal. |

Exact active-wild/effect caps, distance bands and update rates remain measured
engineering outputs; no new gameplay probability or clock multiplier is
selected. Profile worst-case frame work, object/sprite high-water marks,
palette failures, VRAM usage, input latency, audio continuity and network/save
deadlines on the supported Windows runtime. Compare against the same scene
with the feature off. A faster development PC does not establish friend-PC
acceptance.

Recommended delivery slices, each with rollbackable source/assets and its own
four-client acceptance before expanding content:

1. Finish trade/battle/save/reconnect delivery gates; add read-only scene budget
   instrumentation and an asset/licensing catalogue without replacing the world.
2. One bounded land-entity prototype on one sparse map: stable identity,
   snapshot/rejoin, movement and claim arbitration. No live shiny/progression
   policy or capture release until the decisions above are approved.
3. Complete native capture/result ownership, every terminal/recovery path and
   simultaneous claims; preserve ordinary hidden encounters outside the pilot.
4. Local then remote follower selection, paths, running and map/interior
   transitions; prove resource admission with four observers.
5. Shared persistent clock, gradual palette presentation and all ten evolution
   branches; add reviewed time weights to the existing randomized family filter.
6. One ground-mount roster entry with complete directions and rider alignment,
   follower handoff, collision, mount/dismount interruption and remote appearance.
   Expand the roster only with equivalent assets and tests.
7. Polish one representative route, town, cave and water scene using reused
   permitted assets; add layered roofs/trees, water, weather and lighting one
   measured effect at a time. Expand only after the combined crowded scene passes.

No whole-engine replacement, engine-limit increase, save migration, new asset
import, gameplay implementation or game execution was performed for this plan.
