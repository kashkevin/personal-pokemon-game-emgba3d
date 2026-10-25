# Feature status of the emulator baseline (before the native PC migration)

Date: 2026-10-09. Read-only audit. Nothing in either repository was changed
except this file.

## Baseline

| Repo | Branch / tag | Commit |
| --- | --- | --- |
| App `/home/claude/pokemon` (`app:` below) | `claude/continuation`, tag `emulator-baseline-20261009` | `7240c81` |
| Engine `/home/claude/engine` (`eng:` below) | `claude/engine-continuation`, tag `emulator-baseline-20261009` | `761c9c27f` |

Engine = pokeemerald-expansion 1.17.1 (`bb1093a7c`) + Codex work to `aef47e4b2`
+ Codex WIP checkpoint `62f0bae0f` + Claude commits `5618a4aa9..761c9c27f`.
App = Codex work to `31e5bf9` + Codex WIP checkpoint `3189faf` + Claude commits
`7056dd2..7240c81`. "Doc" means a file under `app:docs/`.

## Labels

- **Implemented** - code complete end to end in the baseline AND recorded
  evidence that it ran in actual gameplay (actual mGBA core or actual Windows run).
- **Partial** - some of the feature exists; named pieces are missing.
- **Unverified** - code appears complete by source review (may have unit tests or
  fixtures) but no recorded actual-core or gameplay run.
- **Planned** - in the design; no meaningful code.

Counts. Feature list (53): Implemented 9, Partial 5, Unverified 33, Planned 6.
Behaviours to re-verify (15): Implemented 10, Partial 3, Unverified 2.

## Evidence rules used

1. Only runs recorded in docs or `app:scripts/multiplayer/*evidence.json` count
   toward Implemented. Unit/fixture tests, the engine's headless TEST runner,
   source reviews and compilation do not.
2. **No actual-core or Windows run exists for the baseline pair itself.** Every
   recorded run used an earlier frozen build (pins are in each cited doc).
   Implemented here means "ran in actual gameplay on a recorded earlier build and
   the code is still in the baseline". **Delta** marks rows whose proven path was
   changed afterwards by the Oct 9 Claude commits; re-run those on the baseline
   before using them as the migration's reference behaviour.
3. The Oct 9 Claude commits (shared world, visible wild Pokémon, wild pool,
   followers, riding, appearance, Charm/Mega shop, Lucky, wagers, co-op Gyms,
   friendship, World Events) have no doc and no actual-core run. `ba59c93` says
   "WIP (untested) ... run before relying on it"; inputs staged in
   `/home/claude/proof/multiplayer-proof` have no run output. `eng:pokedev.gba`
   shows the engine HEAD compiles; that is not a run.
4. Fixture check made for this audit on a scratch `git archive` of `7240c81`
   (Linux, Python 3.12, bytecode off): `tests/` discover ran 1,374 tests,
   0 failures, 20 errors (all `ModuleNotFoundError: tkinter`, GUI tests), 1 skip.
   The 95 tests added by `06be3d5` (shared world, world server/companion/mailbox/
   bridge, wagers, friendship, co-op, world menu) pass. Fixture level only.
5. The Oct 9 owner decisions exist only as code comments
   (`app:src/emerald_multiplayer/balance.py`, `shared_world.py`,
   `eng:src/wild_encounter_ow.c`, `eng:src/rtc.c`). `docs/balance-defaults.md`,
   cited by four source files, does not exist. `PROJECT_STATUS_AND_HANDOFF.md`,
   `master-spec.md` and `visible-world-design.md` still describe visible wild,
   followers, mounts and time as design-only and their rules as pending.

Unless stated, app paths are under `app:src/emerald_multiplayer/`.

## Core Pokémon

| Feature | Status | Evidence (paths/docs) | Missing / how to verify |
| --- | --- | --- | --- |
| Generations 1-6 Pokémon | Partial | `eng:include/config/general.h` GEN_LATEST=GEN_6; `species_enabled.h` unchanged, so Gen 7-9 stay compiled (save layout). 721 gates only in wild pool (`eng:tools/mp/gen_wild_pool.py` MAX_DEX=721), starters, World Event catalogue, trade gate (`trade_eligibility.py:118`). Doc gen6-defaults-profile.md: headless test "every standard National Dex entry 1-721 has a nonempty, bounded level-up list containing no post-Gen6 move". | Doc: the 721 boundary "needs separate gates" (TM/tutor/egg data, evolutions into Gen 7+ species, gifts). Verify: per-path acquisition audit + actual capture/evolve/trade runs. |
| Generation 6 mechanics | Partial | GEN_LATEST=GEN_6. Doc gen6-defaults-profile.md: headless runner passed 5 selected tests (burn 1/8, paralysis Speed 1/4, data). Doc windows-gen6-battle-proof.md: wqg2 "passed" an actual Windows 1v1 on the Gen6 ROM, "not the entire Gen6 ruleset". | Doc lists open items: B_EXTRAPOLATED_MOVE_FLAGS, B_X_ITEMS_CROSSUSE, B_THUNDERSTORM_TERRAIN, B_RUN_TRAINER_BATTLE, B_AFFECTION_MECHANICS, Gen6 affection vs friendship. Delta: battle code (923dc64, 761c9c27f). Verify: mechanic matrix in actual battles. |
| Fairy typing | Unverified | Upstream type + chart (Doc gen6-foundation-update.md); headless test read Clefairy as Fairy. | No recorded battle using Fairy matchups. Verify: Fairy vs Dragon/Steel/Fighting/Poison in an actual battle. |
| All applicable official Mega Evolutions incl. later-introduced forms | Partial | 84 Mega records on Gen 1-6 bases (48 original + 36 later, Doc gen6-foundation-update.md). Mega Ring from Flannery and Mega Stone shop (`eng:data/scripts/mp_progression.inc`, generated `mp_mega_stone_shop.inc`); all 84 forms in World Event catalogue. | No official per-form ledger, so completeness vs the current official list is unknown; doc'd adaptations unresolved (Dragonize 20% vs 30%, Mega Sol, Eternal Floette / Zygarde Complete prerequisites, Rayquaza via Dragon Ascent). No actual battle with Mega Evolution recorded; one Mega per trainer in native 2v2 untested. |
| 18 selectable starters | Unverified | `eng:src/starter_choose.c` six pages, 18 species; choice in VAR 0x40DB. Doc eighteen-starter-selection.md: "No build or gameplay check was run for this change." | Verify: New Game, each of 18 picks, first battle, save, fresh Continue, enrollment. |
| Randomized wild Pokémon | Unverified | `eng:src/mp_wild_random.c` hooked into `wild_encounter.c` (TryGenerateWildMon, fishing) and so into visible spawns; pool `eng:src/data/mp_wild_pool.h` (312 families) generated from engine data (5618a4aa9). | Verify: actual-core sampling per map, land/surf/fish/rock smash; Battle Frontier tables kept. |
| Rarity-based encounters | Unverified | 4 tiers (90/134/70/18 families), weights 10/5/2/1 per family; area type x3; nocturnal/diurnal /3 out of their time of day and x1 in it, time and area together at most x3 (PC builds since 2026-10-25, the owner's "same 30 pokemon" report; the GBA ROM keeps x3 or /3) (`mp_wild_random.c`, host `spawn_director.py`). No repeats on a map: a visible spawn whose family is already on the map or among its last 6 spawns is rolled again, 4 rolls at most (`wild_encounter_ow.c` for the game's own spawns, `spawn_director.py` for the shared ones). | Verify: species histogram per area from actual cores. |
| Low-level/basic-stage early encounters | Unverified | Map table keeps vanilla level; evolved stages need member minLevel (non-level evolutions 30/45); 35% one-stage-lower roll. Pseudo/fossil families very rare at base stage. | Verify: early routes give base stages only. |
| No normal wild Legendary/Mythical Pokémon | Unverified | Generator drops Legendary/Sub-legendary/Mythical/UB/Paradox families; pool contains none. | Exception to confirm: vanilla post-game roaming Latios/Latias can still appear as a visible spawn (`eng:src/wild_encounter_ow.c` CreateEnemyPartyOWE -> TryStartRoamerEncounter). |
| Shiny Pokémon | Unverified | Engine shinies; personal generation rate set to 1/4096 (MP_GEN6_SHINY_ODDS, `eng:src/pokemon.c`, 80fef1a82; stored-mon predicate unchanged). Shiny visible spawns sparkle and do not despawn off-screen; follower shiny flag synced. Rate choice recorded only in code. | No shiny in any recorded run. Verify: shiny in battle, overworld, as follower, after trade and fresh Continue. |
| Shiny Charm | Unverified | Engine Charm: 2 extra rolls (I_SHINY_CHARM_ADDITIONAL_ROLLS, 3/4096 total) on personal rolls incl. visible spawns and Local Soft Reset (80fef1a82). World Event shininess is the host's own 1/64 roll, unaffected. | Verify: holder vs non-holder in actual cores; events unchanged. |
| Time-based evolution mechanics | Unverified | Engine evolution conditions use GetTimeOfDay; while connected `eng:src/rtc.c` RtcCalcLocalTime takes the host world clock; GEN_6 hours (night 21-04) in `eng:include/constants/rtc.h`. Doc visible-world-design.md: exact XY/ORAS hour boundaries "UNKNOWN". | Verify: the 10 Gen6 time branches (table in visible-world-design.md) on both sides of each boundary under the world clock. |

## Multiplayer

| Feature | Status | Evidence (paths/docs) | Missing / how to verify |
| --- | --- | --- | --- |
| Up to four players | Implemented | Doc four-player-foundation.md: four actual cores, "A fifth authenticated player is refused"; `protocol.py` MAX_PLAYERS=4; Doc windows-menu-multi-proof.md: wqm1 four Windows clients "passed". | One PC only; separate PCs, Wi-Fi, Internet never run. Delta: protocol 2 / EMW1 (7056dd2, 5618a4aa9). |
| Independent exploration | Implemented | Doc four-player-foundation.md: "three simultaneous maps, an open menu on C, and an indoor scene on D"; A's wild battle "while the other three games continue independently". | Delta: presence v2. |
| Free-form teams | Implemented | Doc native-players-menu.md run-2 (4 actual cores): invitation, acceptance, leaving, "forming both teams"; wqm1 formed two teams. `team_desk.py`. | Teams are session-local: dissolve on disconnect/restart (Doc team-foundation.md); persistence rule undecided. |
| Maximum normal team size of two | Implemented | `team_desk.py`: "a team requires two different players", MAX_TEAMS=2, "at most two teams may coexist"; 2+2 teams formed in run-2 and wqm1. | - |
| Individual rewards | Unverified | PvP (apart from the new wagers) and Championship give no rewards (Doc championships.md: "no forfeits, wagers, prizes, or balance numbers are introduced"). Per-player rewards exist only in new code: co-op Gym (each game runs its own victory script + prize, `eng:data/scripts/mp_coop_gym.inc`), wager wallets (`wagers.py`), World Event catch (catcher's save). | Verify: co-op Gym and wager runs with per-player checkpoint diffs. Optional Championship buy-ins/prizes not built. |
| Trading from the beginning | Implemented | Players-menu trade needs only an enrolled character with a party; no progression gate. Doc windows-menu-trade-effects-proof.md: wqte4 "passed" with early-game Torchic/Wurmple; Doc native-trade-menu-delivery.md trade-menu-core-2. | Delta: Lucky/fence changes (8bbd40e, 55c9a3dfb, 06be3d5). |
| PvP from the beginning | Implemented | wqb1 (Doc windows-menu-battle-proof.md) and wqg2 used starter-stage parties (Torchic L7, Wurmple L3 vs Treecko L5); enabled by host manifest, not progression (`launcher_session.py:423`). | Delta: battle code (923dc64, 761c9c27f, cd951f7). |
| 1v1 battles | Implemented | wqb1 "passed": native Challenge/Accept/Enter, 362 routed blocks, agreed result, saves, fresh Continue; wqg2 same on the Gen6 ROM. | 2-vs-1 parties only. Delta: battle code. |
| 2v2 battles | Implemented | wqm1 (4 Windows clients, parties 2/1/1/1); Doc native-battle-execution.md: "actual four-core execution run 5 passed with all four trainers owning six Pokémon". Full party per trainer = owner decision. | Full-six never run on Windows. Delta: IsFullMulti -> IsNativeDouble refactor in shared battle code (761c9c27f). |
| Planned 1v1v1v1 battles | Planned | No code. Doc master-spec.md phase 10. | Design and build separately. |
| Championship tournaments | Unverified | `championship.py`, `championship_menu.py`, launcher panel. Doc championships.md: "No actual native Championship match or packaged four-person tournament qualification is claimed"; Doc championship-recovery.md: 45 focused tests (TCP + SQLite). | Verify: 4 actual clients play 2 semifinals + final; recovery of an uncertain issued match. |
| Optional in-game currency wagers | Unverified | `wagers.py` (proposal, every trainer accepts exact amount, START gate, settle only on a closed result, numbered wallet adjustments), `eng:src/multiplayer_world.c` UpdateWallet (VAR_MP_WALLET_SEQ); cd951f7, 9b8648e19. Proof mode in ba59c93 "WIP (untested)". | Verify: 1v1 and 2v2 wager win/draw/cancel/interrupt with money checked in every save. |
| Persistent saves | Implemented | Doc phase3-ownership.md: "ownership-run-8, passed all 22 recorded checks" (capture, box moves, release, live recovery, fresh Continue); four-player fresh Continue; fresh Continue in wqb1/wqm1/wqte4/wqt2. | Save format is the GBA 128 KiB Flash image (see migration impact). |
| Player friendship levels | Unverified | `friendship.py`: host-owned pairs, 5 levels at 0/30/120/300/600 points, daily cap 60, Players-menu page (8bbd40e). | Verify: points from real trades/battles/events, caps, persistence across host restart. |
| Lucky Trades | Unverified | Decided once at mutual consent in the effect path (`trade_effect_backend.py` lucky_decider; 5-30% by level); exact-swap trades are never Lucky; both received Pokémon become Lucky. | Verify: actual trade forced Lucky; retry/restart does not re-roll; host and native candidates match. |
| Lucky Pokémon | Unverified | `eng:src/multiplayer_trade_effects.c` MultiplayerLucky_Apply: IV floor 12, never lowers; marker = Gigantamax-factor bit; "LUCKY" on summary (`pokemon_summary_screen.c`). | Verify: summary, IVs, marker survives save, trade, evolution. |
| Lucky Friends | Unverified | `friendship.py`: Best Friends, 10% per eligible activity, 12 h cooldown; next effect-path trade guaranteed Lucky; consumed only by a Lucky commit. | Verify: flag survives cancel/retry/reconnect; consumed exactly once. |

## World and exploration

| Feature | Status | Evidence (paths/docs) | Missing / how to verify |
| --- | --- | --- | --- |
| Pokémon followers | Unverified | OW_FOLLOWERS_ENABLED TRUE (`eng:include/config/overworld.h`, 5618a4aa9); remote followers drawn from EMW1 (`eng:src/multiplayer_world.c` UpdateFollower). | Verify: 4-client follower sync, indoors/large Pokémon, shiny, transitions, object/palette budget. |
| Rideable Pokémon (ground riding; must not grant flying) | Unverified | `eng:src/multiplayer_ride.c`: 67-species roster, lead Pokémon, only on maps that allow bikes and only on foot, dismount for Surf/bike, running pace, grants no Fly/Surf; remote rider via EMW1 (e726268e6). | Verify: collisions, ledges, water edges, remote rendering, follower -> mount -> follower. |
| Visible wild Pokémon | Unverified | WE_OW_ENCOUNTERS TRUE; WE_VANILLA_RANDOM FALSE, so random grass/surf encounters are off (fishing, Rock Smash stay) - `eng:include/config/wild_encounter.h`; up to 4 per client. | Verify: spawn, approach, battle, catch, run-return in actual cores; 4-player object budget (16 objects). |
| Shared wild spawns (see conflict note) | Planned | No shared ordinary-spawn code: visible spawns are generated per client and EMW1 carries none. Only World Events are shared. Design only: Doc visible-world-design.md. | Owner decision needed; see Decision conflicts. |
| Customizable player characters | Partial | `eng:src/multiplayer_appearance.c`: palette recolour of Brendan/May (skin, hair colour, outfit, hat/bag; bytes 4 and 6 reserved), STYLE editor in the Player start menu; host stores per player (`shared_world.py`), synced via EMW1. | Missing vs spec: hair style, clothing shapes, hats/accessories, body, creation at game start. `appearance.py` describe() labels disagree with the ROM tables (helper unused). |
| Day/night cycle | Unverified | OW_ENABLE_DNS TRUE (upstream); host world clock 12x (`balance.py` clock_rate=12), runs only while at least one session is connected, persisted (`shared_world.py`); ROM uses it when connected, local RTC otherwise. | Verify: same time/tint on 4 clients, pause at 0 players, host restart. Every RTC consumer (berries, daily events, tides) now runs 12x; not audited. |
| Weather | Unverified | Vanilla per-map weather only; no project weather code or sync; sprite reserves protect weather sprites (`eng:src/multiplayer.c`, `multiplayer_world.c`). | Verify: rain/ash/sandstorm maps with 4 players, followers and day/night tint. |
| Time-dependent Pokémon mechanics | Unverified | Spawn weighting by time (`mp_wild_random.c`), time evolutions via world clock; OW_TIME_OF_DAY_ENCOUNTERS FALSE. | Verify under the world clock in actual cores. |
| Twin Gym Leaders | Unverified | `eng:src/multiplayer_coop.c`, `data/scripts/mp_coop_gym.inc`, 8 partner trainers (`src/data/trainers.party`, flags 855-862), native phase 4 (2 cores, AI on master); app battle-desk mode 4 (923dc64). Proof mode in ba59c93 "WIP (untested)". | Verify: all 8 Gyms with a team; first-win badge vs helper prize. |
| Multiple regions eventually | Planned | Hoenn only (Doc master-spec.md Regions). | - |
| Enhanced 3D-style Emerald overworld | Planned | Migration target. No renderer code in either repo; master-spec keeps 2D. Out-of-repo research under `/home/claude/research` is not part of the baseline. | - |

## Events and progression

| Feature | Status | Evidence (paths/docs) | Missing / how to verify |
| --- | --- | --- | --- |
| Legendary events | Unverified | Host: `shared_world.py` (schedule 10-20 min then every 25-45 min, 15 min timer, claims), catalogue `world_event_catalogue.py` (legendary 38; weights rare 50 / legendary 28 / mega 15 / mythical 5 / mega legendary 2; 80 reachable spots from `eng:tools/mp/gen_world_events.py`). ROM: `eng:src/multiplayer_world.c` event object, claim, battle, result (f458e5e, ce021aeb6). | Verify: spawn, notice, travel, claim, catch with 2-4 actual clients. |
| Mythical events | Unverified | Same path; mythical 16 entries (Mew ... Volcanion). | Same. |
| Mega events | Unverified | Mega 75 entries spawned in Mega form; capture stores the base form (PrepareEventBattle / RevertCaughtBattleForm). | Verify capture result and stone. |
| Shiny events | Unverified | Host 1/64 shiny roll on any event; no separate shiny category. | - |
| Rare Shiny Mega Legendary events | Unverified | Mega legendary 9 entries (weight 2) x shiny 1/64. | - |
| Expensive purchasable Mega Stones | Unverified | 60,000 each (MP_MEGA_STONE_PRICE), Mauville Mart dealer after the Mega Ring (Flannery, 4th badge) - `eng:data/scripts/mp_progression.inc`, `src/data/items.h`. | Verify purchase, hold, Mega Evolve in battle. |
| Mega Stones obtainable through events | Unverified | Every Mega event Pokémon holds its own stone (all 75 Mega entries carry held_item); the catcher keeps it. | Verify stone after capture. |
| Personal/static Legendary encounters | Partial | Vanilla statics live in each player's own save; 25 authored reset descriptors (Doc local-reset-production-flow.md). Ticket statics (Ho-Oh, Lugia, Mew, Deoxys, Southern Island) need items that only vanilla Mystery Gift / record-mixing scripts give (`eng:data/scripts/gift_*.inc`, `cable_club.inc`); Doc local-reset-ticket-sources.md: "No unlock, ticket ... is granted." | Missing: a ticket access path. No static legendary reached in any recorded run. Verify with legitimately progressed saves. |
| Multiplayer-safe local soft resets | Unverified | Mechanism ran on actual cores only with a development encounter (MP_LOCAL_RESET_DEVELOPMENT=1): Doc local-soft-reset-design.md "local-reset-four-run-1 then passed 21 checks", "local-reset-select-four-run-1 passed 21 checks". Production: 25 sources on (`eng:include/config/multiplayer_local_reset.h`); Doc local-reset-production-flow.md: "They do not prove that all 25 encounters are reachable and reset correctly in the actual game." Charm added by 80fef1a82. | Verify each source family on progressed saves with 3 peers active; Select and chord input; interruptions. |
| Individual event rewards | Unverified | First catch wins: only the catcher's save gets the Pokémon (+ held stone); other challengers get friendship points only. | Verify a 2-player race; also a lost result report (see conflicts). |
| Shiny Charm obtainable through the in-game Game Corner | Unverified | Mauville Game Corner prize clerk: 9,000 coins, guaranteed, Coin Case needed, one per player (`eng:data/scripts/mp_progression.inc`, `MauvilleCity_GameCorner/map.json`). | Verify purchase, persistence, effect. |
| Multiplayer Pokémon League | Planned | No multiplayer League/Elite Four code; the Championship is a 4-player bracket, not a League. | - |
| Expanded endgame systems | Planned | No project code (vanilla Battle Frontier only). | - |

## Multiplayer behaviours to re-verify after migration

| Behaviour | Status | Evidence (paths/docs) | Missing / how to verify |
| --- | --- | --- | --- |
| Players connecting | Implemented | Doc phase2-presence.md (2 actual cores); four-player-foundation.md (4 cores, 5th refused); handoff: wq1 "simultaneous authenticated TLS Host/Join" on Windows; wqt2/wqb1/wqm1. | One PC, loopback only. Delta: protocol 2 (7056dd2). |
| Player synchronization | Implemented | Doc phase2-presence.md: tile and relative-pixel checks on both clients; Doc remote-running-animation.md: two actual cores, observer running frames. | EMW1 sync (followers, mounts, appearance, clock, events) never run. Delta: remote avatars now need 8 free sprites (80fef1a82). |
| Movement | Implemented | phase2-presence: "Simultaneous movement passed tile and relative pixel checks on both clients". | Delta: avatar drawing reads mount state. |
| Map transitions | Implemented | phase2-presence: interior and route transitions "without duplication"; four-player: three maps at once. | - |
| Separate parties/inventories/money | Implemented | One canonical save per character; four-player: closed Flash "exactly match each character's canonical payload"; battles restore every original party (run 5, wqm1). | Wagers now move money (unverified). |
| Separate rewards | Unverified | See Individual rewards. | - |
| Trading | Partial | wqte4 (Windows, non-evolving pair); trade-menu-core-2; Doc trade-foundation.md paired-trade-run-2, -restart-1 (22 checks), -abort-1, -cold-1. | Eggs and mail refused (`trade_eligibility.py:107-111`); evolution/move choice only in synthetic native replay (Doc native-trade-replay-worker.md); post-Gen6 move edge case (conflicts). Delta: Lucky path. |
| PvP | Implemented | See 1v1 and 2v2. | Delta: battle code. |
| Teams | Implemented | See Free-form teams. | Session-local. |
| Disconnect/reconnect | Implemented | phase2-presence: companion disconnect/rejoin and server restart; four-player: "B disconnects and rejoins under a fresh lease"; trade restart/abort/cold proofs. | Teams dissolve on disconnect; real network loss between PCs never run. |
| World Events | Unverified | See Events table. | - |
| Persistent saves | Implemented | See Multiplayer table. | - |
| Autosave (every 5 minutes + manual save + per-character toggle) | Implemented | Doc windows-controls-audit.md wqt2: "host's actual 300-second autosave deadline produced revision 2 after 307.210 seconds; the friend remained at revision 1 with autosave off. Both manual saves succeeded"; Doc windows-launcher-gui.md launcher-gui-proof-1 (visible toggle + Save now). `launcher_settings.py` AUTOSAVE_INTERVAL=300, default on. | Each save pauses the game about 6.3 s (Doc save-performance.md); packaged button path unqualified. |
| Host-loss handling (everyone saves and disconnects) | Partial | Doc emergency-save.md: combined-emergency-core-2/-3 kept exact Flash at host loss (safe field, interrupted export), held the core, rejoin reconciled to revision 2, fresh Continue; in-battle host loss covered by the recovery proof below. | Doc: it "does not exercise disconnect during an authored static hunt, trade or multiplayer battle, nor Windows host-loss UI, four simultaneous clients or separate-PC networking"; handoff: those combinations "retain separate gates". |
| Interrupted battle waits for every player | Partial | Doc native-battle-resume-proof.md: run-small-all "passed" (4 original cores, parties 2/1/1/1, host loss before BIND / mid-battle / after RELEASE, three reconnected players waited for the fourth). | Full-six recovery runs 3 and 4 failed; no Windows interrupted match; needs the original game processes alive (process death / power loss unsupported, handoff section 2); co-op and wager modes untested. |

## Decision conflicts

### Shared vs personal wild spawns (decide before migration)

The migration directive says "Shared wild spawns". The owner earlier chose
**Personal**. What the baseline code does today:

1. **Ordinary visible wild Pokémon are personal.** Each player's ROM runs the
   engine's visible-spawn generator locally (`eng:src/wild_encounter_ow.c`).
   Species come from that game's own RNG via MPWild_RandomizeSpecies
   (`eng:src/mp_wild_random.c`); shininess uses that player's own trainer ID and
   own Shiny Charm (ComputePlayerShinyOdds). Up to 4 spawns per player.
2. **Nothing about them is networked.** The EMW1 mailbox
   (`eng:include/multiplayer_world.h`) carries followers, mounts, appearance,
   clock, one World Event, notices, wallet and teammate only. Two players in the
   same grass see different Pokémon, and neither sees the other's.
3. Random grass/surf encounters are off (WE_VANILLA_RANDOM FALSE); fishing and
   Rock Smash stay personal traditional rolls.
4. **"It stays for others" means "it stays for you".** Comment in
   `eng:src/wild_encounter_ow.c`: "owner decision Oct 9, 2026: a wild Pokemon
   you run away from stays in the world". At battle start the game remembers one
   generated spawn (wild, outbreak or Feebas; not roamers) in RAM: graphics
   (species, form, shiny, gender), map, tile, elevation, movement type, level.
   If the battle ends Ran or Teleported, the same-looking Pokémon reappears **in
   that player's own game** once they are 3+ tiles away on the same map and its
   object slot is free. It is lost on a map change, slot reuse or reload (not
   saved). Re-battling it rolls a new personality, IVs, nature and moves at full
   HP. Caught, defeated or lost -> gone. Other players never had it.
5. **The only shared spawn is the World Event** (`app:.../shared_world.py`):
   one host-owned Pokémon at a fixed spot, visible to all; one claimant at a time
   (others see it as busy); run, loss, defeat or cancel releases it to everyone
   until its 15-minute timer ends; the first catch consumes it. This is the only
   code where running literally leaves a Pokémon for others.
6. The docs disagree with the code: master-spec.md and visible-world-design.md
   still recommend shared visible entities with first-initiator claims and
   recommend that a Run consumes the spawn.

No change is recommended here; the owner must pick personal (as built) or shared.

### Other mismatches with the binding decisions

| Decision | Code | Mismatch |
| --- | --- | --- |
| Post-Gen6 moves trade as-is | Relaxed in `trade_effect_witness.py` and `trade_friendship.py` (MAX_STORED_MOVE 847, 7056dd2). | `trade_effect_choice.py:53` still rejects any current move id > 621 when describing the evolution move-choice screen, so an effectful trade that evolves a Pokémon already knowing a post-Gen6 move and asks for a move choice fails ("invalid native move facts"). Narrow; never run. |
| Visible spawns personal; running leaves it for others | Personal as decided. | Running returns the Pokémon only to the runner (above); "for others" exists only for World Events. |
| Day/night 1 world day = 2 h, paused when nobody online | clock_rate 12; clock stops at 0 sessions. | Matches. Note: World Event timers keep counting while the host app runs with nobody online (spawning stops, expiry does not). |
| World Events first catch wins | Matches. | Note: the claim is released 120 s after the claimant disconnects; a catch whose result report is lost could let a second player catch the same event Pokémon. |
| 2v2 full party; host loss saves and disconnects; interrupted battle waits for all; autosave 5 min + manual + toggle | Match the code. | None found. |

### Recorded guidance the code no longer follows (not binding decisions)

- development-roadmap.md: "Do not enable personal OWE/followers globally and
  describe them as completed shared systems" - both are now on globally.
- visible-world-design.md: "Do not blanket-disable traditional engine
  encounters before those adapters are verified" - WE_VANILLA_RANDOM is FALSE.
- visible-world-design.md asks to audit berries, daily flags, Shoal Cave and
  timed events before routing them to the new clock; `eng:src/rtc.c` routes every
  RTC consumer through the 12x clock (berries grow and daily events reset every
  2 real hours while online).
- Balance numbers (Charm 9,000 coins, Mega Stone 60,000, Lucky IV floor 12 and
  chances, shiny 1/4096, event weights) live only in code; the cited
  `docs/balance-defaults.md` is missing.

## Native-migration impact

| Subsystem | Main files | Class | Features carried |
| --- | --- | --- | --- |
| Host, companion and game services | `server.py`, `companion.py`, `storage.py`, `ownership_storage.py`, `team_desk.py`, `trade_desk.py`, `battle_desk.py`, `battle_recovery*.py`, `championship*.py`, `friendship.py`, `wagers.py` (ledger), `shared_world.py`, `world_event_catalogue.py`, `autosave.py`, `secure_transport.py`, `invitations.py`, `launcher_*.py` | Pure Python - unaffected | Connecting, teams, trade/battle coordination, Championship, friendship, Lucky decision, wager ledger, World Event scheduling, world clock, autosave timing, launcher UI. |
| Save and Pokémon format readers | `flash.py`, `ownership.py`, `trade_eligibility.py`, `trade_flash.py`, `trade_effect_flash.py`, `trade_friendship_flash.py`, `trade_inspection.py`, `player_card.py`, `cold_start.py`, `emergency_save.py`, `wagers.money_from_snapshot` (SaveBlock1+0x490), `server._progression_level` | Pure Python, but bound to the GBA 128 KiB Flash image and BoxPokemon encryption | Persistent saves, ownership, trading, wagers, event levels. A native save must keep this byte format or every reader and stored checkpoint must migrate. |
| Mailbox and bridge codecs | `mailbox.py` (EMP1 128 B), `save_mailbox.py` (512 B) + save window (4 KiB), `battle_mailbox.py`, `menu_mailbox.py` (512 B each), `reset_mailbox.py` (128 B), `trade_effect_mailbox.py`, `world_mailbox.py` (EMW1 256 B), `bridge_protocol.py`, `bridge_config.py`, `app:scripts/multiplayer/generate_manifest.py` (ELF symbol addresses) | Depends on GBA EWRAM mailboxes / addresses | Every multiplayer feature. Replace with a native in-process interface; the struct layouts can stay as contracts. |
| Lua bridge | `app:bridge/mgba.lua` | Lua/mGBA-specific - replace | All ROM <-> companion traffic, reset-chord routing. |
| Windows runtime | `app:native/windows-runtime/sdl-multiplayer.c/.h` (mGBA SDL hooks, reset-chord filter), `trade-replay-worker.c` (headless mGBA core replaying native trade code) | mGBA-specific - replace | Input, trade-effect replay on the host. |
| Process and ROM handling | `player_runtime.py`, `draft_runtime.py`, `enrollment_runtime.py`, `trade_native_replay.py`, `game_import.py`, `game_patch.py` (BPS from the owner's ROM) | Python that launches mGBA / patches a GBA ROM - rework | Enrollment, Host/Join launch, import. |
| Engine C and scripts | `eng:src/multiplayer*.c` (presence, save/ownership, battle + virtual link adapter, menu, resets, trade effects, world, ride, appearance, co-op), `mp_wild_random.c`, hooks in `wild_encounter_ow.c`, `rtc.c`, `starter_choose.c`, battle files, `data/scripts/*.inc`, map scripts, `trainers.party`, `include/config/*` | Engine C - recompile natively. GBA-specific parts: EWRAM mailboxes, Flash save path, GBA link-layer battle transport (SendBlock / GetBlockReceivedStatus), RTC hook, 16-object / 64-sprite / palette budgets | All gameplay content and native halves of every multiplayer feature. |
| Data generators | `eng:tools/mp/gen_wild_pool.py`, `gen_world_events.py` | Python; call `arm-none-eabi-gcc -E`; output keyed to map group/number/coordinates | Wild pool, event catalogue, Mega Stone shop. |
| Proof and qualification harness | `app:scripts/multiplayer/*_proof.py` + `harness.c` (libmGBA), `app:scripts/windows-runtime/qualify_*.py`, `app:scripts/baseline-headless/` | mGBA-specific | Produced all Implemented evidence; must be rebuilt to re-qualify after migration. |

GBA save-layout facts a native save must keep or migrate: ownership serial in
unused substruct bits (`eng:src/pokemon.c` MON_DATA_MULTIPLAYER_ID, 20 bits);
Lucky marker = Gigantamax-factor bit; starter choice VAR 0x40DB; wallet
VAR_MP_WALLET_SEQ 0x40FE / AMOUNT_LO 0x40FF / AMOUNT_HI 0x40E5; static-reset
counters in vars (for example VAR_MP_VOLTORB_1_*); co-op partner trainer flags
855-862 (1 flag slot left); host checkpoints are whole 128 KiB Flash images in
SQLite.
