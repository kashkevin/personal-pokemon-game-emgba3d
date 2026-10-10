# Feature status

As of 2026-10-09. Requirements are in `PROJECT_SPEC.md`; the work order is in
`DEVELOPMENT_ROADMAP.md`.

The gameplay classifications and evidence below come from the read-only audit
`docs/native-migration/feature-status.md` of the emulator baseline (app `7240c81`,
engine `761c9c27f`, tag `emulator-baseline-20261009` in both repositories), reused
nearly verbatim. Only the status labels were renamed.

## Status values

Every row uses exactly one of these.

| Status | Meaning | Audit label |
| --- | --- | --- |
| Implemented and tested | Code complete end to end and a recorded run in actual gameplay (actual mGBA core or actual Windows run). **Every such run used an earlier frozen build, not the baseline pair itself** (pins are in each cited doc). | Implemented |
| Implemented but unverified | Code appears complete by source review (may have unit tests or fixtures), but there is no recorded actual-core or gameplay run. | Unverified |
| Partially implemented | Some of the feature exists; the missing pieces are named. | Partial |
| Planned | In the design; no meaningful code. | Planned |
| Blocked | Cannot move until a named dependency or owner decision is resolved. | not used yet |
| Broken | A recorded run or check fails on the current build. | not used yet |

**Native PC status** is "Not yet tested natively" for every gameplay row unless the
row says otherwise. The native build reaches the overworld, saves and battles (see
Native PC migration below). The native multiplayer bridge exists (engine `e2e3917e2`);
re-verified natively so far: players connecting, seeing each other and moving, a door
map change, a companion restart, live checkpoints into the ownership store, a trade
and a 1v1 battle through the Players menu (the battle between two games the real
launcher started). Each row below names its runs.

Conventions (from the audit): bare file names are under app `src/emerald_multiplayer/`;
`app:` is this repository; `eng:` is the engine repository (our pokeemerald-expansion
fork); "Doc x.md" means `docs/x.md`. **Delta** marks a row whose proven path was
changed by the Oct 9 commits after the recorded run; re-run it on the baseline before
using it as reference behaviour. Unit/fixture tests, the engine's headless TEST runner,
source reviews and compilation never count as a run.

Counts. Feature list (53): Implemented and tested 9, Partially implemented 5,
Implemented but unverified 33, Planned 6. Behaviours to re-verify (15): Implemented and
tested 10, Partially implemented 3, Implemented but unverified 2. Delivery (2):
Implemented but unverified 2.

## Core Pokémon

| Feature | Status | Native PC status | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Generations 1-6 Pokémon | Partially implemented | Not yet tested natively | `eng:include/config/general.h` GEN_LATEST=GEN_6; `species_enabled.h` unchanged, so Gen 7-9 stay compiled (save layout). 721 gates only in wild pool (`eng:tools/mp/gen_wild_pool.py` MAX_DEX=721), starters, World Event catalogue, trade gate (`trade_eligibility.py:118`). Doc gen6-defaults-profile.md: headless test "every standard National Dex entry 1-721 has a nonempty, bounded level-up list containing no post-Gen6 move". | Doc: the 721 boundary "needs separate gates" (TM/tutor/egg data, evolutions into Gen 7+ species, gifts). Verify: per-path acquisition audit + actual capture/evolve/trade runs. |
| Generation 6 mechanics | Partially implemented | Not yet tested natively | GEN_LATEST=GEN_6. Doc gen6-defaults-profile.md: headless runner passed 5 selected tests (burn 1/8, paralysis Speed 1/4, data). Doc windows-gen6-battle-proof.md: wqg2 "passed" an actual Windows 1v1 on the Gen6 ROM, "not the entire Gen6 ruleset". | Open items: B_EXTRAPOLATED_MOVE_FLAGS, B_X_ITEMS_CROSSUSE, B_THUNDERSTORM_TERRAIN, B_RUN_TRAINER_BATTLE, B_AFFECTION_MECHANICS, Gen6 affection vs friendship. Delta: battle code (923dc64, 761c9c27f). Verify: mechanic matrix in actual battles. |
| Fairy typing | Implemented but unverified | Not yet tested natively | Upstream type + chart (Doc gen6-foundation-update.md); headless test read Clefairy as Fairy. | No recorded battle using Fairy matchups. Verify: Fairy vs Dragon/Steel/Fighting/Poison in an actual battle. |
| All applicable official Mega Evolutions incl. later-introduced forms | Partially implemented | Not yet tested natively | 84 Mega records on Gen 1-6 bases (48 original + 36 later, Doc gen6-foundation-update.md). Mega Ring from Flannery and Mega Stone shop (`eng:data/scripts/mp_progression.inc`, generated `mp_mega_stone_shop.inc`); all 84 forms in World Event catalogue. | No official per-form ledger, so completeness vs the current official list is unknown; documented adaptations unresolved (Dragonize 20% vs 30%, Mega Sol, Eternal Floette / Zygarde Complete prerequisites, Rayquaza via Dragon Ascent). No actual battle with Mega Evolution recorded; one Mega per trainer in native 2v2 untested. |
| 18 selectable starters | Implemented but unverified | Not yet tested natively | `eng:src/starter_choose.c` six pages, 18 species; choice in VAR 0x40DB. Doc eighteen-starter-selection.md: "No build or gameplay check was run for this change." | Verify: New Game, each of 18 picks, first battle, save, fresh Continue, enrollment. |
| Randomized wild Pokémon | Implemented but unverified | Not yet tested natively | `eng:src/mp_wild_random.c` hooked into `wild_encounter.c` (TryGenerateWildMon, fishing) and so into visible spawns; pool `eng:src/data/mp_wild_pool.h` (312 families) generated from engine data (5618a4aa9). | Verify: actual-core sampling per map, land/surf/fish/rock smash; Battle Frontier tables kept. |
| Rarity-based encounters | Implemented but unverified | Not yet tested natively | 4 tiers (90/134/70/18 families), weights 10/5/2/1 per family; area type x3; nocturnal/diurnal x3 or /3 (`mp_wild_random.c`). | Verify: species histogram per area from actual cores. |
| Low-level/basic-stage early encounters | Implemented but unverified | Not yet tested natively | Map table keeps vanilla level; evolved stages need member minLevel (non-level evolutions 30/45); 35% one-stage-lower roll. Pseudo/fossil families very rare at base stage. | Verify: early routes give base stages only. |
| No normal wild Legendary/Mythical Pokémon | Implemented but unverified | Not yet tested natively | Generator drops Legendary/Sub-legendary/Mythical/UB/Paradox families; pool contains none. | Exception to confirm: vanilla post-game roaming Latios/Latias can still appear as a visible spawn (`eng:src/wild_encounter_ow.c` CreateEnemyPartyOWE -> TryStartRoamerEncounter). |
| Shiny Pokémon | Implemented but unverified | Not yet tested natively | Engine shinies; personal generation rate set to 1/4096 (MP_GEN6_SHINY_ODDS, `eng:src/pokemon.c`, 80fef1a82; stored-mon predicate unchanged). Shiny visible spawns sparkle and do not despawn off-screen; follower shiny flag synced. Rate choice recorded only in code. | No shiny in any recorded run. Verify: shiny in battle, overworld, as follower, after trade and fresh Continue. |
| Shiny Charm | Implemented but unverified | Not yet tested natively | Engine Charm: 2 extra rolls (I_SHINY_CHARM_ADDITIONAL_ROLLS, 3/4096 total) on personal rolls incl. visible spawns and Local Soft Reset (80fef1a82). World Event shininess is the host's own 1/64 roll, unaffected. | Verify: holder vs non-holder in actual cores; events unchanged. |
| Time-based evolution mechanics | Implemented but unverified | Not yet tested natively | Engine evolution conditions use GetTimeOfDay; while connected `eng:src/rtc.c` RtcCalcLocalTime takes the host world clock; GEN_6 hours (night 21-04) in `eng:include/constants/rtc.h`. Doc visible-world-design.md: exact XY/ORAS hour boundaries "UNKNOWN". | Verify: the 10 Gen6 time branches (table in visible-world-design.md) on both sides of each boundary under the world clock. |

## Multiplayer

| Feature | Status | Native PC status | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Up to four players | Implemented and tested | Four native Linux clients joined, each saw the other three, and all three saw one of them walk through a door and back (presence only; the fifth-player refusal not rerun) | Doc four-player-foundation.md: four actual cores, "A fifth authenticated player is refused"; `protocol.py` MAX_PLAYERS=4; Doc windows-menu-multi-proof.md: wqm1 four Windows clients "passed". | Ran on earlier builds only. One PC only; separate PCs, Wi-Fi, Internet never run. Delta: protocol 2 / EMW1 (7056dd2, 5618a4aa9). |
| Independent exploration | Implemented and tested | Not yet tested natively | Doc four-player-foundation.md: "three simultaneous maps, an open menu on C, and an indoor scene on D"; A's wild battle "while the other three games continue independently". | Ran on earlier builds only. Delta: presence v2. |
| Free-form teams | Implemented and tested | Not yet tested natively | Doc native-players-menu.md run-2 (4 actual cores): invitation, acceptance, leaving, "forming both teams"; wqm1 formed two teams. `team_desk.py`. | Ran on earlier builds only. Teams are session-local: dissolve on disconnect/restart (Doc team-foundation.md); persistence rule undecided. |
| Maximum normal team size of two | Implemented and tested | Not yet tested natively | `team_desk.py`: "a team requires two different players", MAX_TEAMS=2, "at most two teams may coexist"; 2+2 teams formed in run-2 and wqm1. | Ran on earlier builds only. |
| Individual rewards | Implemented but unverified | Not yet tested natively | PvP (apart from the new wagers) and Championship give no rewards (Doc championships.md: "no forfeits, wagers, prizes, or balance numbers are introduced"). Per-player rewards exist only in new code: co-op Gym (each game runs its own victory script + prize, `eng:data/scripts/mp_coop_gym.inc`), wager wallets (`wagers.py`), World Event catch (catcher's save). | Verify: co-op Gym and wager runs with per-player checkpoint diffs. Optional Championship buy-ins/prizes not built. |
| Trading from the beginning | Implemented and tested | Tested natively (2 Linux clients, and 2 Windows clients under Wine: early-game Torchic for Treecko through the Players menu, `native-trade-evidence.json`) | Players-menu trade needs only an enrolled character with a party; no progression gate. Doc windows-menu-trade-effects-proof.md: wqte4 "passed" with early-game Torchic/Wurmple; Doc native-trade-menu-delivery.md trade-menu-core-2. | Ran on earlier builds only. Delta: Lucky/fence changes (8bbd40e, 55c9a3dfb, 06be3d5). |
| PvP from the beginning | Implemented and tested | Tested natively (2 Linux clients started by the launcher, the same starter-stage sources as wqg2: Torchic L7 and a second Pokémon vs Treecko L5, Gen 6 defaults build; `native-launcher-battle-evidence.json`); Windows clients not yet | wqb1 (Doc windows-menu-battle-proof.md) and wqg2 used starter-stage parties (Torchic L7, Wurmple L3 vs Treecko L5); enabled by host manifest, not progression (`launcher_session.py:423`). | Ran on earlier builds only. Delta: battle code (923dc64, 761c9c27f, cd951f7). |
| 1v1 battles | Implemented and tested | Tested natively (2 Linux clients started by the real launcher: Challenge 1v1, Accept, Enter battle through the Players menu; 362 routed blocks with the forced switch, as in wqb1; the same durable result for both, full parties restored, Recent battle results, manual saves, normal close, fresh Continue; native-launcher-battle-1, `native-launcher-battle-evidence.json`); Windows clients and the 3D build not yet | wqb1 "passed": native Challenge/Accept/Enter, 362 routed blocks, agreed result, saves, fresh Continue; wqg2 same on the Gen6 ROM. | Ran on earlier builds only. 2-vs-1 parties only. Delta: battle code. |
| 2v2 battles | Implemented and tested | Not yet tested natively | wqm1 (4 Windows clients, parties 2/1/1/1); Doc native-battle-execution.md: "actual four-core execution run 5 passed with all four trainers owning six Pokémon". Full party per trainer = owner decision. | Ran on earlier builds only. Full-six never run on Windows. Delta: IsFullMulti -> IsNativeDouble refactor in shared battle code (761c9c27f). |
| Planned 1v1v1v1 battles | Planned | Not yet tested natively | No code. Doc master-spec.md phase 10. | Design and build separately. |
| Championship tournaments | Implemented but unverified | Not yet tested natively | `championship.py`, `championship_menu.py`, launcher panel. Doc championships.md: "No actual native Championship match or packaged four-person tournament qualification is claimed"; Doc championship-recovery.md: 45 focused tests (TCP + SQLite). | Verify: 4 actual clients play 2 semifinals + final; recovery of an uncertain issued match. |
| Optional in-game currency wagers | Implemented but unverified | Not yet tested natively | `wagers.py` (proposal, every trainer accepts exact amount, START gate, settle only on a closed result, numbered wallet adjustments), `eng:src/multiplayer_world.c` UpdateWallet (VAR_MP_WALLET_SEQ); cd951f7, 9b8648e19. Proof mode in ba59c93 "WIP (untested)". | Verify: 1v1 and 2v2 wager win/draw/cancel/interrupt with money checked in every save. |
| Persistent saves | Implemented and tested | Tested natively (live checkpoints into the host's ownership store; 2 Linux, 2 Windows under Wine, 2 3D clients): each legacy save enrolled through the running game, a checkpoint after walking holds the new position, each game's own save file equals its canonical save, both games restarted (Continue restores the saved position) and saved again against their last revision; live recovery of the canonical save into a running game (2 Linux, 2 Wine, 2 3D clients) (`scripts/multiplayer/native-checkpoint-evidence.json`). Captures and box moves not run natively | Doc phase3-ownership.md: "ownership-run-8, passed all 22 recorded checks" (capture, box moves, release, live recovery, fresh Continue); four-player fresh Continue; fresh Continue in wqb1/wqm1/wqte4/wqt2. | Ran on earlier builds only. Save format is the GBA 128 KiB Flash image; the native build must keep it byte-identical or migrate every reader (Doc native-migration/baseline.md). |
| Player friendship levels | Implemented but unverified | Not yet tested natively | `friendship.py`: host-owned pairs, 5 levels at 0/30/120/300/600 points, daily cap 60, Players-menu page (8bbd40e). | Verify: points from real trades/battles/events, caps, persistence across host restart. |
| Lucky Trades | Implemented but unverified | Not yet tested natively | Decided once at mutual consent in the effect path (`trade_effect_backend.py` lucky_decider; 5-30% by level); exact-swap trades are never Lucky; both received Pokémon become Lucky. | Verify: actual trade forced Lucky; retry/restart does not re-roll; host and native candidates match. |
| Lucky Pokémon | Implemented but unverified | Not yet tested natively | `eng:src/multiplayer_trade_effects.c` MultiplayerLucky_Apply: IV floor 12, never lowers; marker = Gigantamax-factor bit; "LUCKY" on summary (`pokemon_summary_screen.c`). | Verify: summary, IVs, marker survives save, trade, evolution. |
| Lucky Friends | Implemented but unverified | Not yet tested natively | `friendship.py`: Best Friends, 10% per eligible activity, 12 h cooldown; next effect-path trade guaranteed Lucky; consumed only by a Lucky commit. | Verify: flag survives cancel/retry/reconnect; consumed exactly once. |

## World and exploration

| Feature | Status | Native PC status | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Pokémon followers | Implemented but unverified | Not yet tested natively | OW_FOLLOWERS_ENABLED TRUE (`eng:include/config/overworld.h`, 5618a4aa9); remote followers drawn from EMW1 (`eng:src/multiplayer_world.c` UpdateFollower). | Verify: 4-client follower sync, indoors/large Pokémon, shiny, transitions, object/palette budget. |
| Rideable Pokémon (ground riding; must not grant flying) | Implemented but unverified | Not yet tested natively | `eng:src/multiplayer_ride.c`: 67-species roster, lead Pokémon, only on maps that allow bikes and only on foot, dismount for Surf/bike, running pace, grants no Fly/Surf; remote rider via EMW1 (e726268e6). | Verify: collisions, ledges, water edges, remote rendering, follower -> mount -> follower. |
| Visible wild Pokémon | Implemented but unverified | Not yet tested natively | WE_OW_ENCOUNTERS TRUE; WE_VANILLA_RANDOM FALSE, so random grass/surf encounters are off (fishing, Rock Smash stay) - `eng:include/config/wild_encounter.h`; up to 4 per client. | Verify: spawn, approach, battle, catch, run-return in actual cores; 4-player object budget (16 objects). Spawns are personal; a Pokémon you run from returns only in your own game (see the decision section below). |
| Shared wild spawns | Planned | Not yet tested natively | No shared ordinary-spawn code: visible spawns are generated per client and EMW1 carries none. Only World Events are shared. Design only: Doc visible-world-design.md. | Decision pending - owner to confirm: the earlier owner decision is personal spawns (as built); the newest directive lists shared spawns. See below. |
| Customizable player characters | Partially implemented | Not yet tested natively | `eng:src/multiplayer_appearance.c`: palette recolour of Brendan/May (skin, hair colour, outfit, hat/bag; bytes 4 and 6 reserved), STYLE editor in the Player start menu; host stores per player (`shared_world.py`), synced via EMW1. | Missing vs spec: hair style, clothing shapes, hats/accessories, body, creation at game start. `appearance.py` describe() labels disagree with the ROM tables (helper unused). |
| Day/night cycle | Implemented but unverified | Not yet tested natively | OW_ENABLE_DNS TRUE (upstream); host world clock 12x (`balance.py` clock_rate=12), runs only while at least one session is connected, persisted (`shared_world.py`); ROM uses it when connected, local RTC otherwise. | Verify: same time/tint on 4 clients, pause at 0 players, host restart. Every RTC consumer (berries, daily events, tides) now runs 12x; not audited. |
| Weather | Implemented but unverified | Not yet tested natively | Vanilla per-map weather only; no project weather code or sync; sprite reserves protect weather sprites (`eng:src/multiplayer.c`, `multiplayer_world.c`). | Verify: rain/ash/sandstorm maps with 4 players, followers and day/night tint. |
| Time-dependent Pokémon mechanics | Implemented but unverified | Not yet tested natively | Spawn weighting by time (`mp_wild_random.c`), time evolutions via world clock; OW_TIME_OF_DAY_ENCOUNTERS FALSE. | Verify under the world clock in actual cores. |
| Twin Gym Leaders | Implemented but unverified | Not yet tested natively | `eng:src/multiplayer_coop.c`, `data/scripts/mp_coop_gym.inc`, 8 partner trainers (`src/data/trainers.party`, flags 855-862), native phase 4 (2 cores, AI on master); app battle-desk mode 4 (923dc64). Proof mode in ba59c93 "WIP (untested)". | Verify: all 8 Gyms with a team; first-win badge vs helper prize. |
| Multiple regions eventually | Planned | Not yet tested natively | Hoenn only (Doc master-spec.md Regions). | - |
| Enhanced 3D-style Emerald overworld | Planned | Not started: Diorama/3DS-style graphics are not in our engine yet | Migration target. At the baseline: no renderer code in either repo; master-spec keeps 2D. Out-of-repo research under `/home/claude/research` is not part of the baseline. | Milestone D. The voxel project's own Diorama build was run separately earlier, outside our engine. |

## Events and progression

| Feature | Status | Native PC status | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Legendary events | Implemented but unverified | Not yet tested natively | Host: `shared_world.py` (schedule 10-20 min then every 25-45 min, 15 min timer, claims), catalogue `world_event_catalogue.py` (legendary 38; weights rare 50 / legendary 28 / mega 15 / mythical 5 / mega legendary 2; 80 reachable spots from `eng:tools/mp/gen_world_events.py`). ROM: `eng:src/multiplayer_world.c` event object, claim, battle, result (f458e5e, ce021aeb6). | Verify: spawn, notice, travel, claim, catch with 2-4 actual clients. |
| Mythical events | Implemented but unverified | Not yet tested natively | Same path; mythical 16 entries (Mew ... Volcanion). | Same. |
| Mega events | Implemented but unverified | Not yet tested natively | Mega 75 entries spawned in Mega form; capture stores the base form (PrepareEventBattle / RevertCaughtBattleForm). | Verify capture result and stone. |
| Shiny events | Implemented but unverified | Not yet tested natively | Host 1/64 shiny roll on any event; no separate shiny category. | - |
| Rare Shiny Mega Legendary events | Implemented but unverified | Not yet tested natively | Mega legendary 9 entries (weight 2) x shiny 1/64. | - |
| Expensive purchasable Mega Stones | Implemented but unverified | Not yet tested natively | 60,000 each (MP_MEGA_STONE_PRICE), Mauville Mart dealer after the Mega Ring (Flannery, 4th badge) - `eng:data/scripts/mp_progression.inc`, `src/data/items.h`. | Verify purchase, hold, Mega Evolve in battle. |
| Mega Stones obtainable through events | Implemented but unverified | Not yet tested natively | Every Mega event Pokémon holds its own stone (all 75 Mega entries carry held_item); the catcher keeps it. | Verify stone after capture. |
| Personal/static Legendary encounters | Partially implemented | Not yet tested natively | Vanilla statics live in each player's own save; 25 authored reset descriptors (Doc local-reset-production-flow.md). Ticket statics (Ho-Oh, Lugia, Mew, Deoxys, Southern Island) need items that only vanilla Mystery Gift / record-mixing scripts give (`eng:data/scripts/gift_*.inc`, `cable_club.inc`); Doc local-reset-ticket-sources.md: "No unlock, ticket ... is granted." | Missing: a ticket access path. No static legendary reached in any recorded run. Verify with legitimately progressed saves. |
| Multiplayer-safe local soft resets | Implemented but unverified | Not yet tested natively | Mechanism ran on actual cores only with a development encounter (MP_LOCAL_RESET_DEVELOPMENT=1): Doc local-soft-reset-design.md "local-reset-four-run-1 then passed 21 checks", "local-reset-select-four-run-1 passed 21 checks". Production: 25 sources on (`eng:include/config/multiplayer_local_reset.h`); Doc local-reset-production-flow.md: "They do not prove that all 25 encounters are reachable and reset correctly in the actual game." Charm added by 80fef1a82. | Verify each source family on progressed saves with 3 peers active; Select and chord input; interruptions. |
| Individual event rewards | Implemented but unverified | Not yet tested natively | First catch wins: only the catcher's save gets the Pokémon (+ held stone); other challengers get friendship points only. | Verify a 2-player race; also a lost result report (see Known mismatches). |
| Shiny Charm obtainable through the in-game Game Corner | Implemented but unverified | Not yet tested natively | Mauville Game Corner prize clerk: 9,000 coins, guaranteed, Coin Case needed, one per player (`eng:data/scripts/mp_progression.inc`, `MauvilleCity_GameCorner/map.json`). | Verify purchase, persistence, effect. |
| Multiplayer Pokémon League | Planned | Not yet tested natively | No multiplayer League/Elite Four code; the Championship is a 4-player bracket, not a League. | - |
| Expanded endgame systems | Planned | Not yet tested natively | No project code (vanilla Battle Frontier only). | - |

## Multiplayer behaviours to re-verify after migration

These are the reference behaviours for Milestone G.

| Feature | Status | Native PC status | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Players connecting | Implemented and tested | Tested natively: 2 and 4 Linux clients, 2 Windows clients under Wine and 2 3D clients, through the native bridge, unchanged companions and world server, also with the ownership store and credentials (`scripts/multiplayer/native-presence-evidence.json`, `native-checkpoint-evidence.json`) | Doc phase2-presence.md (2 actual cores); four-player-foundation.md (4 cores, 5th refused); handoff: wq1 "simultaneous authenticated TLS Host/Join" on Windows; wqt2/wqb1/wqm1. | Ran on earlier builds only. One PC, loopback only. Delta: protocol 2 (7056dd2). |
| Player synchronization | Implemented and tested | Not yet tested natively | Doc phase2-presence.md: tile and relative-pixel checks on both clients; Doc remote-running-animation.md: two actual cores, observer running frames. | Ran on earlier builds only. EMW1 sync (followers, mounts, appearance, clock, events) never run. Delta: remote avatars now need 8 free sprites (80fef1a82). |
| Movement | Implemented and tested | Tested natively: one client's two steps reach another client (same 2- and 4-client runs) | phase2-presence: "Simultaneous movement passed tile and relative pixel checks on both clients". | Ran on earlier builds only. Delta: avatar drawing reads mount state. |
| Map transitions | Implemented and tested | Tested natively: a client walked through Littleroot's lab door and back out; the other client (2 clients, 2D and 3D) or the other three (4 clients) saw it on the lab map and outside again (`native-presence-5`, `-four-2`, `-3d-3`). Route connections not run natively | phase2-presence: interior and route transitions "without duplication"; four-player: three maps at once. | Ran on earlier builds only. |
| Separate parties/inventories/money | Implemented and tested | Partly tested natively: after a 1v1 each game's party in memory equals its own canonical character and its bytes from before the battle (native-launcher-battle-1); inventories and money not checked natively | One canonical save per character; four-player: closed Flash "exactly match each character's canonical payload"; battles restore every original party (run 5, wqm1). | Ran on earlier builds only. Wagers now move money (unverified). |
| Separate rewards | Implemented but unverified | Not yet tested natively | See Individual rewards. | - |
| Trading | Partially implemented | Tested natively on Linux: offers on both screens, one confirmation commits nothing, both apply it (revision 3 each, ownership conserved, each running game's party equals its new canonical save), backing out aborts, a restart keeps both results (native-trade-5); about 43 s from the first confirmation at 60 frames a second. The same with 2 Windows clients under Wine (native-trade-wine-1, 47 s). The 3D build not yet | wqte4 (Windows, non-evolving pair); trade-menu-core-2; Doc trade-foundation.md paired-trade-run-2, -restart-1 (22 checks), -abort-1, -cold-1. | Eggs and mail refused (`trade_eligibility.py:107-111`); evolution/move choice only in synthetic native replay (Doc native-trade-replay-worker.md); post-Gen6 move edge case (Known mismatches). Delta: Lucky path. |
| PvP | Implemented and tested | 1v1 tested natively (see 1v1 battles); 2v2 not yet | See 1v1 and 2v2. | Ran on earlier builds only. Delta: battle code. |
| Teams | Implemented and tested | Not yet tested natively | See Free-form teams. | Ran on earlier builds only. Session-local. |
| Disconnect/reconnect | Implemented and tested | Tested natively: a companion restarted while its game ran (the game's bridge reconnected by itself, a new host lease, everyone sees everyone again; 2D and 3D), and both games closed and started again (new leases and incarnations, saves intact). Network loss between companion and host and host restart not run natively | phase2-presence: companion disconnect/rejoin and server restart; four-player: "B disconnects and rejoins under a fresh lease"; trade restart/abort/cold proofs. | Ran on earlier builds only. Teams dissolve on disconnect; real network loss between PCs never run. |
| World Events | Implemented but unverified | Not yet tested natively | See Events and progression. | - |
| Persistent saves | Implemented and tested | Not yet tested natively | See Multiplayer table. | Ran on earlier builds only. |
| Autosave (every 5 minutes + manual save + per-character toggle) | Implemented and tested | Partly tested natively: the launcher's manual save (revision 2) and autosave switched off, with native games (native-launcher-battle-1); the 5-minute timer not run natively | Doc windows-controls-audit.md wqt2: "host's actual 300-second autosave deadline produced revision 2 after 307.210 seconds; the friend remained at revision 1 with autosave off. Both manual saves succeeded"; Doc windows-launcher-gui.md launcher-gui-proof-1 (visible toggle + Save now). `launcher_settings.py` AUTOSAVE_INTERVAL=300, default on. | Ran on earlier builds only. Each save pauses the game about 6.3 s (Doc save-performance.md); packaged button path unqualified. |
| Host-loss handling (everyone saves and disconnects) | Partially implemented | Not yet tested natively | Doc emergency-save.md: combined-emergency-core-2/-3 kept exact Flash at host loss (safe field, interrupted export), held the core, rejoin reconciled to revision 2, fresh Continue; in-battle host loss covered by the recovery proof below. | Doc: it "does not exercise disconnect during an authored static hunt, trade or multiplayer battle, nor Windows host-loss UI, four simultaneous clients or separate-PC networking"; handoff: those combinations "retain separate gates". |
| Interrupted battle waits for every player | Partially implemented | Not yet tested natively | Doc native-battle-resume-proof.md: run-small-all "passed" (4 original cores, parties 2/1/1/1, host loss before BIND / mid-battle / after RELEASE, three reconnected players waited for the fourth). | Full-six recovery runs 3 and 4 failed; no Windows interrupted match; needs the original game processes alive (process death / power loss unsupported, handoff section 2); co-op and wager modes untested. |

## Delivery (emulator build)

Not part of the audit's 53 features. Classified here from `PROJECT_STATUS_AND_HANDOFF.md`
with the audit's rules (no packaged gameplay run means not "tested").

| Feature | Status | Native PC status | Evidence | Notes |
| --- | --- | --- | --- | --- |
| Windows package with own-dump import (Host Game / Join Game) | Implemented but unverified | Not built: the Windows .exe is not built yet | Handoff: the owner's dump produced a reconstructing BPS; private candidate9 includes the patch and pinned runtime/worker; "recursive audits, fresh packaged-resource import/idempotent retry and actual executable startup/normal closure passed. Its later actual GUI import also passed in isolated storage." Doc windows-release-candidate-9.md, Doc release-patch-creation.md. | The handoff calls this "Implemented, bounded installation checks passed". Clean-PC setup, the full first-character flow and combined packaged gameplay/network acceptance were never run. The built emulator runtime predates two baseline source changes and must be rebuilt before the Oct 9 features run on Windows (Doc native-migration/baseline.md). |
| Separate-PC LAN, Wi-Fi and Internet play | Implemented but unverified | Not yet tested natively | Handoff section 2: authenticated, pinned TLS transport exists; the passive connection probe reports player authentication, separate-device proof and Internet-path proof as false (`network_diagnostics.py:22`); Doc network-transport.md. | Every recorded multiplayer run used one PC over loopback. Needs separate PCs, another network and real input devices (handoff, missing inputs). |

## Native PC migration

Status of the native build (branch `claude/native-pc` in both repositories) as of
2026-10-09, night. "Linux" runs are under Xvfb in the cloud workspace; "Windows"
runs are the real `pokeemerald-mp.exe` under Wine 9.0 in the same workspace. Nothing
has run on the owner's PC yet, and no run used a real controller, monitor or sound
device.

| Item | Linux | Windows (Wine) | Notes |
| --- | --- | --- | --- |
| Compiles and links (`Makefile_pc`) | Yes | Yes | Windows needs `-mno-ms-bitfields -mno-align-double` for GBA-compatible struct layout. |
| Byte layout of save data, mailboxes, battle packets, asm data | 172 types match | 172 types match | `tools/pc_port/abi_layout.py`. |
| Launches; intro, title, main menu | Yes | Yes | RHH logo fixed (KNOWN_ISSUES N4). |
| New game: Birch intro, naming, into the truck | Yes | Yes | Needed fixes N9 and N10. |
| Overworld, movement, start menu | Yes | Yes | |
| Menus: party, summary (4 pages), Bag, Pokédex list/entry/area/cry/size | Yes (UBSan build) | Not yet | Needed fixes for out-of-range reads (see KNOWN_ISSUES). |
| Save, quit, continue | Yes | Yes | Same 128 KiB flash format; written atomically. |
| Load an emulator `.sav` (mGBA, 131088 bytes) and save over a copy | Yes | Load: yes | Native save then reloads correctly; the mGBA RTC footer is dropped when the native build writes. |
| Wild battle: Fight, Bag, switch, Run, win | Yes | Fight and win: yes | Visible wild Pokémon trigger battles; follower and spawns show. |
| Soft reset (game's `DoSoftReset`) | Yes | Yes | Process stays up; save unchanged. The clear-save screen used for this test crashed after a few seconds before engine `3ebd6b3a0` (KNOWN_ISSUES N25). |
| Audio | Samples produced (earlier) | No device under Wine | Not listened to. |
| Stability | No crash in the final runs | One unexplained crash in about ten launches (not reproduced; crash reporter added since) | |
| Controller input | Not yet | Not yet | Windows has XInput code from the voxel project; untested. |
| Native multiplayer bridge (replaces the mGBA Lua bridge) | Yes: 2 and 4 clients: presence, map change, companion restart, live checkpoints (save mailbox and 4 KiB save window) | Yes: 2 clients, presence, live checkpoints (Winsock) and a trade through the Players menu (native-trade-wine-1) | Engine `e2e3917e2` (`src/platform/mp_bridge.c`, a C port of `bridge/mgba.lua`), `edb755a26` (keeps up below 60 frames a second, KNOWN_ISSUES M4); 4186 unit checks. Exercised natively since: the Players menu, a trade (native-trade-5; under Wine native-trade-wine-1) and a 1v1 battle (native-launcher-battle-1, 2 Linux clients). Local Soft Reset, 2v2, emergency saves and shared-world actions are carried by the same code but not yet exercised natively. |
| Launcher starts the native game (player runtime, B3) | Yes, through the whole launcher: the real `LauncherWindow`, `SessionWorker` and `LauncherSession` (host and join) started two Linux native games from a native runtime bundle (the Linux executable under the bundle's `.exe` name with a placeholder SDL2.dll, so the launcher's bundle and installation checks ran); world creation, host enrollment through bootstrap games, the friend's invitation, Continue, a 1v1 battle, manual saves, normal close (exit 0) and fresh Continue (`native-launcher-battle-evidence.json`). No clicks on the window: the harness calls the worker's start as its buttons do | Yes: the launcher's `PlayerRuntime` with a native runtime bundle started the 2D exe under Wine with its save, bridge file and settings file; closed-game recovery installed the canonical save, the game reached the overworld at it, a live checkpoint went through it; a bundle of another ROM build was refused before starting (`native-launcher-evidence.json`) | Engine `9e1de660f` (`--config`), app `player_runtime.py` (`emerald-native-runtime-v1`), `draft_runtime.py`, `enrollment_runtime.py` (unit-tested only); the launcher window with the Windows exe and the 3D exe through the launcher not run yet. |
| Pokémon Center: enter, heal, save, leave, re-enter | Yes | Yes | Crashed before engine `5b2bcb7ce` (KNOWN_ISSUES N24). |
| 1920x1080 window / fullscreen | Configurable, not seen | Configurable, not seen | `windowScale=6` in `pokeemerald.cfg` gives 1920x1080; F11 toggles fullscreen. The cloud display is 1280x720, so neither was observed. |

### Diorama 3D overworld (Milestone D, engine branch `claude/native-graphics`)

Built with `make -f Makefile_pc DIORAMA=1` (`pokeemerald-mp-diorama[.exe]`). Renderer
from ZallaxDev/pokeemerald-voxel-project `cfb429bd1`, adapted to our engine. F4
switches between the 3D view and the classic 2D view. All runs below used software
OpenGL (Mesa llvmpipe) in the cloud workspace: they show what is drawn, not how fast
a real GPU draws it.

| Item | Linux | Windows (Wine) | Notes |
| --- | --- | --- | --- |
| Compiles; GBA ROM unchanged | Yes | Yes | ROM sha256 `f214735b...3387`. |
| Launches into the 3D overworld | Yes | Yes | |
| Visually renders: Route 101, Oldale Town, Littleroot Town | Yes | Oldale Town | Voxel trees, buildings, ledges, grass, signs, flowers, map-name popup, neighbouring maps. |
| Visually renders: interior (Oldale Pokémon Center 1F) | Yes | Yes | |
| Player, NPCs, follower, visible wild Pokémon in 3D | Yes | Yes (player, NPCs) | Follower hidden during Poké Ball animation (KNOWN_ISSUES V1). |
| Day/night tint in 3D | Seen; compared with the 2D view at night and midday in Oldale Town | Seen (day) | Ground, buildings and sprites match the 2D tint; the 3D tree crowns stay brighter at night (KNOWN_ISSUES V5). |
| Walking, warps (door in/out), map connections in 3D | Yes; since graphics `398d486ef` the door opens on the model and the whole warp (opening, walking in, closing, fade out and in) stays in 3D | Yes (door out; the new door not yet seen under Wine) | The 3DS project's door, swinging doors included; unmodelled buildings' doors stay shut in 3D. |
| Wild battle in the Diorama build | Yes: started from the 3D view (walking into a visible wild Pokémon), fled, game returned to the 3D view by itself; also from the classic view | Not yet | The battle-intro frames themselves were not inspected. |
| Soft reset in the Diorama build | Yes: clear-save screen, NO, Continue into the 3D view | Not yet | |
| Modelled buildings and furniture (3DS project, D4) | Yes: Littleroot, Oldale Town, Oldale Pokémon Center, a house | Yes: Oldale Town, Oldale Pokémon Center | 475 models generated from our maps at build time (`tools/diorama_buildings`), coloured from the live palettes. Doors do not open in 3D (KNOWN_ISSUES V6). |
| Walkers whole in front of furniture and walls | Yes: at the Center counter and PC, beside the Center and a house; a walker behind the Center's roof is hidden by it | Yes: at the counter | Engine `d63407185`. Before it the counter hid two thirds of a walker standing at it. |
| Sun shadows (terrain, trees, buildings, sprites) | Yes: Oldale Town by day, fainter at night; none in the Center | Yes: Oldale Town by day; none in the Center | Off indoors and in rain, fog, ash, sand and overcast weather (not seen in those weathers yet). `PKMN_DIORAMA_SHADOWS=0` turns them off. |
| Frame rate (software GL) | Route 101 3-6 fps; Oldale Town 7.1 fps (7.6 without shadows); Pokémon Center about 44 fps | Oldale Town about 5 fps | Real GPU unmeasured (KNOWN_ISSUES V3). |
| 3DS colour grade (saturation 1.30) | Yes: Littleroot by day, the Pokémon Center | Not yet | Graphics `0d10b9936`; `PKMN_DIORAMA_GRADE=0` turns it off. |
| Walkers' cast shadows (their own silhouette along the sun) | Yes: Littleroot by day (none for a walker in a building's shadow); round shadows kept indoors | Not yet | Graphics `fde3a5741`, the 3DS project's `EmitCastShadow` on flat ground. |
| 3DS weather light (warm sun, cool shade, distance haze per weather) | Yes: Littleroot by day and at night; real rain in Littleroot and real fog on Mt. Pyre's summit and in Rusturf Tunnel (reached with a debug-menu test build); ash only previewed; indoors unchanged (pixel-identical with it off) | Not yet | Graphics `23ad56924`; `PKMN_DIORAMA_LIGHT=0` turns it off. |
| 3DS fog banks (mist lying in the scene) and a cave's gloom | Yes: Mt. Pyre summit by day, Rusturf Tunnel (cave: cold light, bluish banks, dark ring) | Not yet | Graphics `617e005d7`; replaces the flat fog overlay in 3D (`PKMN_DIORAMA_AIR=0` brings it back). |
| 3DS sun dapples, sunlit dust, sun rays, bloom | Yes: Littleroot by day (dapples 0.94-1.07, rays in the top left only over the scene, dust inside the scene); the dapples stay put across the Littleroot to Route 101 crossing (anchor logged at the connection's offset) | Not yet | Graphics `8920f1f67`; `PKMN_DIORAMA_AIR=0` turns dust, rays and bloom off. No measurable frame-rate change on software GL; real GPU unmeasured (V3). |
| 3DS tree style (option: F8 in the game, kept in `pokeemerald.cfg`; `PKMN_DIORAMA_TREES=3ds` for one run) | Yes: Littleroot (day, wide, early morning), Dewford Town (its own small tree), Route 104; about 3-4 times the frame rate of the voxel trees on software GL; F8 swaps voxel and 3DS trees in place while playing (Route 104) | Not yet | Graphics `633be85c6`, switch `8750fd07b`; crowns 1.12x as bright as the 3DS loads them (`c405136a3`). Voxel trees stay the default until the owner picks. |
| 3DS camera framing (option: F7 in the game, kept in `pokeemerald.cfg`; `PKMN_DIORAMA_CAMERA=3ds` for one run) | Yes: Route 104 (about 10 tiles top to bottom at the player, as on the GBA, against about 30 with the default); F7 switches while playing; the pitch and zoom keys' steps are kept between runs too (restart came back at the same zoom) | Not yet | Graphics `0ab8ee710`, switch `8750fd07b`: the 3DS project's 40 degree pitch and distance rule as a focal length; zoom keys still work. Wide view stays the default until the owner picks (KNOWN_ISSUES V8). |
| Dark caves in 3D (the circle of light round the player) | Yes: Granite Cave B1F, wide and 3DS camera (dark but for an ellipse round the player the size of the GBA's circle; the start menu over the dark); Route 104 unchanged. Flash being used (the circle opening, its glow) not seen yet | Not yet | Graphics `3e39f2b15`, the 3DS project's `VoxelFlashLight`. Before it Granite Cave B1F/B2F and Victory Road B1F/B2F were fully lit in 3D. |
| Other 3DS-project features (relief, camera menu entries; signposts compared and not ported) | Not started | Not started | Ordered list in `docs/diorama-3ds-gap-analysis.md`. 3D battle scenery is being done separately (owner, 2026-10-10). |
| Scripted scenes, fades and night tint in 3D | Yes: a door warp, healing at the nurse, the warp's fades; trees follow the night tint and fades (V5 fixed) | Not yet | Before graphics `398d486ef` scripted scenes and fades cut to the 2D view. |
| Follower in and out of its Poke Ball in 3D | Yes: walking off the Oldale Pokémon Center counter (V1 fixed) | Not yet | Graphics `8dda1e1be`: affine sprites drawn with their matrix. |
| Dual screen removed / single screen | Yes (renderer is single-screen) | Yes | |
| Works in multiplayer | Yes for presence, map change, companion restart and live checkpoints: 2 clients in the 3D Pokémon Center saw each other and a move; 2 clients outdoors in Littleroot at about 2.4 frames a second saw a move, a door map change and a companion restart, and enrolled, saved, restarted and saved again (4-6.5 s per save at that frame rate since the M5 fix `2f150c4db`, 32-38 s before it; 1.3-1.5 s at 60), and a live recovery (69 s) | Yes for presence and a door map change: 2 copies of checkpoint native-wip-20261010-2's 3D exe (graphics `8920f1f67`); live checkpoints (4.2-6.5 s per save), restart and a live recovery (73 s): 2 copies of checkpoint native-wip-20261010-3's 3D exe (graphics `3e39f2b15`) | Graphics branch `b02cf0e97`, saves and recovery `2f150c4db` (bridge `edb755a26`); `scripts/multiplayer/native-presence-evidence.json`, `native-checkpoint-evidence.json`. Trades and battles not run in 3D. |

Automated native checks (engine `Makefile_pc`, see `TEST_PLAN.md`): `check-native`
1063 checks and the bridge's 4186 pass; `check-abi` pass (Linux and Windows); `check-game-sections` pass
(Linux and Windows); `check-decompress` 7469 assets pass (Linux). Graphics branch:
`check-diorama` passes (10 renderer unit-test programs, 18,318-metatile C/Python
compositor goldens, rule validation, generated tables up to date); of the rule
compiler's own Python tests 8 pass, `test_rules_parity` fails upstream as well
(KNOWN_ISSUES V2), and `test_compile_rules` runs 23 tests with one failure
(mountain cliff flags, KNOWN_ISSUES V4).

## Decision pending - owner to confirm: personal vs shared wild spawns

- Earlier owner decision (2026-10-09): visible wild spawns are **personal**, and
  running from one leaves it ("it stays for others").
- Newest directive (2026-10-09): "Shared wild spawns", "shared multiplayer spawns",
  "server-authoritative shared wild spawns".
- What the baseline code does (audit):
  1. Each player's ROM generates its own visible spawns (`eng:src/wild_encounter_ow.c`)
     from its own RNG (MPWild_RandomizeSpecies in `eng:src/mp_wild_random.c`); shininess
     uses that player's own trainer ID and Shiny Charm. Up to 4 spawns per player.
  2. Nothing about them is networked: EMW1 carries followers, mounts, appearance, clock,
     one World Event, notices, wallet and teammate only. Two players in the same grass see
     different Pokémon, and neither sees the other's.
  3. Random grass/surf encounters are off (WE_VANILLA_RANDOM FALSE); fishing and Rock
     Smash stay personal traditional rolls.
  4. "It stays for others" works as "it stays for you": after a Run or Teleport the same
     looking Pokémon reappears **in that player's own game** once they are 3+ tiles away on
     the same map and its object slot is free. It is lost on a map change, slot reuse or
     reload (not saved). Re-battling it rolls a new personality, IVs, nature and moves at
     full HP. Caught, defeated or lost means gone. Other players never had it.
  5. The only shared spawn is the World Event (`shared_world.py`): one host-owned Pokémon
     visible to all; one claimant at a time; run, loss, defeat or cancel releases it to
     everyone until its 15-minute timer ends; the first catch consumes it.
  6. `docs/master-spec.md` and `docs/visible-world-design.md` still recommend shared
     visible entities with first-initiator claims and a Run that consumes the spawn.
- Nothing was changed. The owner picks personal (as built) or shared.

## Known mismatches between code and decisions

From the audit.

| Decision | Code today | Mismatch |
| --- | --- | --- |
| Post-Gen6 moves trade as-is | Relaxed in `trade_effect_witness.py` and `trade_friendship.py` (MAX_STORED_MOVE 847, 7056dd2). | `trade_effect_choice.py:53` still rejects any current move id > 621 when describing the evolution move-choice screen, so an effectful trade that evolves a Pokémon already knowing a post-Gen6 move and asks for a move choice fails ("invalid native move facts"). Narrow; never run. |
| Visible spawns personal; running leaves it for others | Personal as decided. | Running returns the Pokémon only to the runner; "for others" exists only for World Events. |
| Day/night 1 world day = 2 h, paused when nobody online | clock_rate 12; clock stops at 0 sessions. | Matches. World Event timers keep counting while the host app runs with nobody online (spawning stops, expiry does not). |
| World Events first catch wins | Matches. | The claim is released 120 s after the claimant disconnects; a catch whose result report is lost could let a second player catch the same event Pokémon. |
| 2v2 full party; host loss saves and disconnects; interrupted battle waits for all; autosave 5 min + manual + toggle | Match the code. | None found. |

Recorded guidance the code no longer follows (not binding decisions):

- `docs/development-roadmap.md`: "Do not enable personal OWE/followers globally and
  describe them as completed shared systems" - both are now on globally.
- `docs/visible-world-design.md`: "Do not blanket-disable traditional engine encounters
  before those adapters are verified" - WE_VANILLA_RANDOM is FALSE.
- `docs/visible-world-design.md` asks to audit berries, daily flags, Shoal Cave and timed
  events before routing them to the new clock; `eng:src/rtc.c` routes every RTC consumer
  through the 12x clock (berries grow and daily events reset every 2 real hours while
  online).
- Balance numbers live only in code; the cited `docs/balance-defaults.md` is missing.
  They are now written down in `PROJECT_SPEC.md` section 7.

## How to update

1. Change a row only with new evidence: a recorded run (a doc in `docs/` or
   `scripts/multiplayer/*evidence.json`) with its build pins. Fixtures, the headless TEST
   runner, source review, compilation and screenshots never move a row to "Implemented
   and tested".
2. Use exactly one of the six status values. Use Blocked when a named dependency or
   owner decision stops the work, and Broken when a recorded run or check fails on the
   current build; link the evidence either way.
3. Native PC status: keep "Not yet tested natively" until a native run is recorded, then
   write the result and its evidence (for example "Tested natively: <doc or log>,
   <commit>" or "Fails natively: <doc>"). A row reaches parity for Milestone G when its
   native result matches its emulator result.
4. Update the Native PC migration table as milestones advance and date each change.
5. When a Delta row is re-run on the emulator baseline, remove "Delta" from its notes.
6. Update the counts and the date at the top. Leave `docs/native-migration/feature-status.md`
   unchanged as the dated audit record.
7. Requirements go in `PROJECT_SPEC.md`; work items go in `DEVELOPMENT_ROADMAP.md`.
