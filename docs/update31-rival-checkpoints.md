# Update 31 — multiplayer rival system, streamlined introduction, shared story checkpoints

Branch `claude/dev-update31-rival` (app), based on the integrated Update 28 default branch
`claude/emeraldtogether-combined-app` = `a912f07`. Development started in parallel with Updates 29
and 30 on the owner's instruction; **nothing is merged** (see "Integration status").

**Engine half (second session, 2026-10-17):** engine branch `claude/dev-update31-rival-engine`, based on the Update 30 engine
branch `claude/dev-update30-gameplay` (`8b8bb92a`, which contains Update 29). Sections 6 and 7 were implemented there; see
section 11 for what was built, how it was checked and what is still open.

Evidence labels follow `AGENTS.md`: *Researched / Implemented / Tested (simulated) / Working / Fully
verified*. Nothing here ran on a real Windows PC, a GPU, a real game core or a real network.

## 1. What was verified before starting

| Item | Result |
| --- | --- |
| App default branch | `claude/emeraldtogether-combined-app` (remote `HEAD`) = `a912f07` "Ledger: Update 28 integrated, CI run and artifact" |
| Update 28 on the app default branch | Yes (`6259914`, `544c889`, ledger `8f4c318`/`a912f07`) |
| Update 29 | Branch `claude/dev-update29-encounters` (`ad254d0`, 2 commits ahead), **not** on the default branch |
| Update 30 | No branch, commit or document found on the app remote |
| Engine repository `kashkevin/personal-pokemon-game-emgba3d-engine` | **Not accessible from this session** ("Repository not found" through git; the session's GitHub credential is scoped to the app repository only; the GitHub API also refused it). The engine default branch and its U28 commit `5aaf2ba2` are known only from the app's ledger. |
| GitHub Actions | Not reachable from this session (API 401); no CI run could be started or read |
| Upstream engine base | `rh-hideout/pokeemerald-expansion` tag `expansion/1.17.1` = `bb1093a7c` (the base `ARCHITECTURE.md` names), cloned read-only for the story audit. Map numbering equals the fork's (`flash._MAP_COUNTS`, 75 groups). |
| Baseline app test suite (untouched U28) | all pass except **4 pre-existing failures** in `tests/test_save_compat.py` (see §9) |

## 2. Dependency map (existing systems reused, nothing rebuilt)

```
                       ┌───────────────────────── engine (not accessible; spec in §6/§7) ──────────────────────────┐
                       │ NewGameInitData · character selection · naming · 18-starter screen (phase6-eighteen-starters)│
                       │ map scripts (Route103/110/119, Rustboro, Route104, Lilycove) · trigger tiles · rival objects │
                       │ native link battle (singles mode 2, full Multi mode 3) · battle_bg / Diorama 3D battle      │
                       │ EMW1 world mailbox (reads RivalRecord at inbound 200..207 when it advertises rival_abi 1)   │
                       │ native Players menu (menu mailbox, custom UI)                                                │
                       └───────────────▲───────────────────────────────▲──────────────────────────────▲──────────────┘
                                       │ EMW1 inbound                  │ menu frames                  │ battle mailbox
┌──────────────────────────────── companion (game side) ────────────────────────────────────────────────────────────┐
│ world_inbound() + RivalRecord (NEW, capability-gated) · _poll_rival (NEW) · PlayerMenu + RivalMenu (NEW page)      │
│ battle_challenge_rpc("pending", rival=…)  — the same authenticated RPC the Championship extension uses             │
└──────────────────────────────────────────────▲─────────────────────────────────────────────────────────────────────┘
                                               │ TLS JSON protocol (battle_pending + "rival" extension, rival_protocol)
┌──────────────────────────────── host (WorldServer) ────────────────────────────────────────────────────────────────┐
│ _rival_challenge (NEW) → RivalCheckpoints (NEW sidecar <world>.rival-checkpoints.sqlite3)                          │
│   reads:  sessions[*].presence (positions) · store.read_checkpoint (party: usable / strength)                     │
│   issues: BattleDesk.invite / invite_multi (existing consent, BIND, START, recovery, release barriers)            │
│   settles from: BattleResults (released results only) · BattleReservations.terminal · admission ledger           │
│ unchanged: friendship (rival battles count as ordinary battles) · wagers (refused for rival matches)              │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Shared files touched (smallest possible change, all additive):

| File | Change | Why |
| --- | --- | --- |
| `server.py` | open the sidecar beside the world; `_rival_challenge`; `_saved_party`/`_party_strength`/`_party_usable`; route `battle_pending` with `rival`; refuse plain invites and wagers on a rival battle ID | host entry point; mirrors the Championship wiring line for line |
| `battle_protocol.py` | accept/validate the `rival` extension on `battle_pending` (request and reply), one extension per request | protocol validation is strict; the extension must be allow-listed |
| `companion.py` | `rival` in the two Championship conditions (cleanup-handoff publication, original-core identity for `match`); `rival_abi_version` capability; `_poll_rival`; `world_inbound(rival=…)` | the same consent-core rules as Championship matches; the engine interface |
| `world_mailbox.py` | `RivalRecord`, packed at inbound 200..207 only when present | engine interface; default bytes stay zero (byte-identical) |
| `player_menu.py` | a "Rival checkpoint" row (home, at a checkpoint) and "Rival checkpoints" (Challenges), the `rival` page | the established custom menu, not a GBA text box |

No U29/U30-owned system (hosting/joining, saved worlds, identity, character loading, PCs, inventory,
breeding, shiny, encounters, Mega economy) was modified.

## 3. Rival checkpoint audit (pokeemerald-expansion 1.17.1)

Every May/Brendan *battle* scene (30 trainer IDs: 5 places × 2 rivals × 3 starters). Re-derived
mechanically by `scripts/multiplayer/check_rival_catalogue.py --engine <checkout>` (map IDs, trigger
tiles, variables, objects, trainer/flag/var/item constants, and the background the original NPC battle
draws); it passes on upstream 1.17.1. **Run it against the private engine before the engine port.**

| # | Checkpoint | Map (group,num) | Original trigger | Prerequisite | Rewards / effects | Gate in the original | Multiplayer behaviour |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Route 103 | `MAP_ROUTE103` (0,18) | talk to rival object at (10,3) | `VAR_BIRCH_LAB_STATE` 3 | `VAR_BIRCH_LAB_STATE`=4, `FLAG_DEFEATED_RIVAL_ROUTE103`, Oldale rival state; then the lab gives the **Pokédex + 5 Poké Balls** | indirect: Oldale's west exit (0,10) stays blocked until the Pokédex | mandatory; no extra barrier (the save's own flags gate it) |
| 2 | Rustboro / Route 104 | `MAP_RUSTBORO_CITY` (0,3) and `MAP_ROUTE104` (0,19) | step on (12..19,53) at `VAR_RUSTBORO_CITY_STATE` 7, or (17,51) at `VAR_ROUTE104_STATE` 1 | after the PokéNav tutorial | Match Call registration; YES/NO battle | none (declinable) | optional battle |
| 3 | Route 110 | `MAP_ROUTE110` (0,25) | step on (33..35,56) at `VAR_ROUTE110_STATE` 0 | — | **Dowsing Machine**; `VAR_ROUTE110_STATE`=1 | the trigger line across the route north to Mauville | mandatory; barrier |
| 4 | Route 119 | `MAP_ROUTE119` (0,34) | step on (25..26,31) at `VAR_ROUTE119_STATE` 0 | — | **HM02 Fly**, `FLAG_RECEIVED_HM_FLY`; `VAR_ROUTE119_STATE`=1 | the trigger line to Fortree | mandatory; barrier |
| 5 | Lilycove | `MAP_LILYCOVE_CITY` (0,5) | talk to rival object at (27,7) | `FLAG_MET_RIVAL_LILYCOVE` unset | YES/NO battle; `FLAG_MET_RIVAL_LILYCOVE`; rival returns home | none (declinable) | optional battle |

Not converted (not rival battles): the lab/house introductions (replaced by the streamlined intro, §6),
post-game rival-house dialogue, ordinary NPC trainers, Gym Leaders, the Battle Frontier.

Original NPC battle backgrounds (computed from tile behaviour and map type exactly as
`BattleSetup_GetEnvironmentId` does): all `BATTLE_ENVIRONMENT_PLAIN`, except Route 103 where talking
from the north or east (tall grass) draws `GRASS`. Canonical multiplayer environment: `PLAIN` for all five.

## 4. Formats (only what the engine already runs)

| Players ready | Format | Engine mode |
| --- | --- | --- |
| 2 | one 1v1 | native singles (mode 2) |
| 3 | round robin A–B, B–C, C–A, one at a time | three native singles |
| 4 | one 2v2; teams = the split with the smallest difference in summed highest party level, ties broken by a hash of (world, checkpoint) | full Multi (mode 3) |

Why not a three-way battle: the engine's free-for-all needs exactly four trainers and its doubles need
four. A three-trainer battle would be a new engine capability; it is not invented. Seat order and tie
breaks never depend on arrival order, so a retry or a restart plans the identical battles. Real parties,
levels, items, moves, abilities, Mega Evolution and animations are the players' own: the battles are
the existing native PvP battles, started from each player's canonical checkpoint party and restored
exactly afterwards (the Desk's existing guarantee). No scripted rival team exists anywhere in this path.

Outcome: a released 1v1/2v2 result (win, loss or draw) **completes** the checkpoint for everyone who
fought. A round robin completes when every match is resolved or void, with at least one resolved; the
winner(s) are the most wins. Losing never blocks: every participant gets the same personal pass.

## 5. Lobby, Start Now / Wait, catch-up, interruptions (host rules)

*Present* = connected, on one of the checkpoint's maps, activity `overworld` or `menu`.

* **Waiting for rival players…** while fewer than two are present.
* **Start Now / Wait for Other Players** (votes, not battle consent). The countdown (5 s) starts when at
  least two chose Start Now and either everyone present did, or the Start Now group has not changed for
  60 s (players who chose Wait, or nothing, are left out and catch up later).
* Any change of who is present or of the Start Now group restarts the 60 s; a change during the
  countdown cancels it. Disconnecting removes a player immediately. Votes are never inherited across a
  reconnect or a host restart.
* At the end of the countdown the plan is committed; any trainer of the ready match presses
  **Battle: A vs B**, which issues an ordinary challenge; every trainer accepts and enters it from
  **Challenges** (the existing flow with all its admission/recovery barriers). A ready match nobody
  starts within 180 s, or whose trainer disconnects before it is issued, is void.
* **Catch-up** (offline or left-out players): after the world completed a checkpoint, **Continue the
  story** records a personal pass (`via=catch_up`) from anywhere; no battle is replayed, no world flag
  changes, rewards come from the player's own save scripts guarded by its own flags (no duplicates).
* **Continue on my own** (`via=solo`): when the player is the only one online, or has stood alone at
  the checkpoint for 120 s, or (bystanders only) the checkpoint's battle has been stuck "waiting" for
  120 s. A solo pass never completes the world checkpoint.
* **Completion is permanent and happens once** (primary key). Repeated interaction shows the result.

Interruption policy (deterministic):

| Situation | Result |
| --- | --- |
| Disconnect / leave before or during the countdown | countdown canceled, lobby open again |
| Challenge declined, expired, or a trainer disconnects before the battle started | match void → 1v1/2v2 session canceled (vote again); round robin skips it |
| Disconnect during a battle, host restart with a battle reserved | stays **waiting** for the existing native battle recovery; never voided or completed by the coordinator |
| Host restart after dispatch, no reservation, no admission ledger | void (nothing can hold a core without a reservation) |
| Host restart with the provisional-admission ledger | waiting; **Recover waiting battle** asks the ledger to classify/revoke the never-entered invitation (same as Championship recovery) |
| Crash between the committed intent and the Desk call | `recover` cancels it (the issuance fence proves the callback never ran) |
| A held battle never resolves (a participant never returns) | bystanders get **Continue on my own** after 120 s; the held battle's own players stay with the native recovery |
| Host leaves | session ends; committed completions/passes are on disk. **No host migration** exists in this architecture (`docs/technical-foundation.md`) and none is claimed. |

## 6. Streamlined new-character introduction (engine work — implemented in the engine session, §11)

The post-intro state is in `docs/update31/intro-post-state.json`: the state the original game reaches
when Birch asks the player to go to Route 103 (`VAR_BIRCH_LAB_STATE` 3), the exact flags/vars to set and
clear (gender-specific house flags included), the respawn point, the spawn tile (south of the player's
own house door: Littleroot (5,9) male / (14,9) female, both walkable), and what must **not** be granted
(Pokédex, Poké Balls, Running Shoes, Route 103 victory). The original introduction gives no items.

Order: `NewGameInitData` → existing character selection → existing naming → existing 18-starter screen
(`special ChooseStarter`, which already writes `VAR_STARTER_MON` and `VAR_MULTIPLAYER_STARTER_CHOICE`) →
the deltas → warp → one save. Applied only to a save without `FLAG_SYS_POKEMON_GET` and with
`VAR_BIRCH_LAB_STATE` < 2. Whether a character is new to a world is decided by Update 30's character
loading, which is why this part waits for U30.

## 7. Engine work as specified by the first session (all items implemented in the engine session, §11)

1. **Run `check_rival_catalogue.py --engine <engine checkout>`**; fix the catalogue if the fork differs.
2. **Manifest `rival_abi_version` = 1** and read `RivalRecord` (EMW1 inbound 200..207: flags
   {1 valid, 2 present, 4 my match}, completed mask, cleared mask, here 1..5, state 1..4). Bit *i* =
   checkpoint *i*+1 in story order. Older engines leave this off and the companion keeps the bytes zero.
3. **Multiplayer mode at the five checkpoints**: hide the NPC rival object (the flags in §3); never start
   `TRAINER_BRENDAN_*`/`TRAINER_MAY_*` battles; on an armed Route 110/119 trigger tile stop the player
   (as Route 101's PreventExit triggers do) when `gate_blocks()` says so and open the Players menu's
   rival page; never stop a player going back, inside buildings, or by Fly/Surf/warps elsewhere.
4. **Personal effects on a pass** (`cleared` bit newly set): run the original scene's completion effects
   from §3 (e.g. Route 110: `giveitem ITEM_DOWSING_MACHINE`, `setvar VAR_ROUTE110_STATE, 1`) guarded by the
   save's own condition (`VAR_ROUTE110_STATE` < 1), so a reload or a repeated record cannot duplicate them.
   A save that already passed the scene solo before Update 31 is simply "already cleared" (no barrier).
5. **Battle background**: a rival PvP battle is a link battle; upstream link battles use the Frontier
   arena and the project's native singles path uses the building arena. The rival battle must instead use
   the checkpoint's canonical environment (`PLAIN`) **on every core**, because the environment changes
   mechanics (Camouflage, Nature Power, Secret Power, environment form changes). Carry it in the battle
   preparation (or derive it from a checkpoint ID carried there) — never from each core's local tile —
   and keep it through intro, moves (a move's own background then the world returns, as today), switches,
   Mega Evolution, faints and the end fade, in Classic 2D and in the Diorama 3D battle (which already
   draws the field where the battle started behind the battle picture). Regression: extend
   `battle_end_check.py`/`first_battle_check.py` with a rival link battle; compare frames before, during
   and after.
6. **Cutscenes**: rival approach/exit using the other players' real appearances (EMW1 peer records
   already carry looks) and names; the custom menu for dialogue; `lockall`/camera released on every exit
   path (timeouts) so a disconnect never leaves a player frozen.
7. **Streamlined intro** (§6), after Update 30's character loading is integrated.

## 8. Tests added (all simulated; see §9 for counts)

| File | What it proves |
| --- | --- |
| `test_rival_catalogue.py` | catalogue structure/order/maps/gates/trainers; gate truth table; intro table (no earned items, gender mirror, spawn); formats (2/3/4 players, fairness, balance, seed tie-break, refusal, winners by native slot, randomized determinism); optional engine re-derivation (`EMERALD_ENGINE_CHECKOUT`) |
| `test_rival_checkpoints.py` | lobby (alone, Start/Wait, simultaneous votes, grace, join/leave/disconnect during countdown, presence filter, unusable party), battles (either side wins, draw, no replay, lost-reply retry, wrong trainer, decline, synchronous refusal, disconnect during battle, recovery-required, ready timeout, one session per player, 2v2 by team), round robin, solo and catch-up, held-battle escape, persistence (restart, reservation evidence, released-while-down, crash before dispatch, recover, corruption, foreign world, unknown schema), and a seeded random walk with invariants after every step and a coverage floor |
| `test_rival_integration.py` | the real `BattleDesk` + `BattleResults` with correlated simulated native receipts: 1v1 and 2v2 complete from the released result; parties restored exactly; decline; expiry; busy refusal; reopen mid-battle |
| `test_rival_server.py` | the real `WorldServer` over authenticated TCP: sidecar location/identity, status, vote → match → ordinary challenge, reserved ID refused for plain invites and wagers, error codes, disconnect/reconnect, save-derived party checks |
| `test_rival_menu.py` | real Companions + real server, the native Players menu clicked by revision/action: row only at a checkpoint, Start Now/Wait, double-click refused, back and reopen, leaving disables buttons, disconnect revokes, Challenges link, host without support |
| `test_rival_world_record.py` | the EMW1 record layout and bounds, default bytes unchanged, capability gating, records from real coordinator replies, the poller (read-only, stops on an unsupported host), every menu page ≤ 6 rows with printable text |

## 9. Results and honest limits

Full app suite (Python 3.12 + tkinter under Xvfb, Linux cloud): **untouched U28 baseline 1827 passed, 4 failed,
50 skipped; with Update 31 1924 passed, 4 failed, 51 skipped** — the 97 new tests all pass, the failures are
the same four, the one extra skip is the optional engine re-derivation (it passes with
`EMERALD_ENGINE_CHECKOUT` pointing at expansion 1.17.1). The skips are Lua 5.3 bridge subtests (the pure
Python paths run) and a private-save-path test. Pre-existing on untouched U28: `test_save_compat.py`
`SharedWorldFromUpdate14` (4 tests) fail because the committed fixture directory
`tests/fixtures/compat/shared_world_u14/` contains only `README.txt` — its SQLite database is excluded by
`.gitignore` (`*.sqlite3`), so a fresh clone cannot run them. Not caused or changed by Update 31.

Not exercised anywhere: a real game core, the engine changes in §7, Windows, a GPU, audio, controllers,
real networks, real UI clicking on Windows. "Tested" above means automated simulation only.

## 10. Integration status

**Final integration (2026-10-17):** integrated with the verified Update 30 game on `claude/integration-u31-final-app` / `claude/integration-u31-final-engine` (not merged into the default branches); results, fixes and the manual Windows CI run are in [update31-final-integration.md](update31-final-integration.md). The paragraph below records the earlier trial.

**Not integrated.** Per the owner's rule, Update 31 merges only after Updates 29 and 30 are on both
default branches. At the end of this session the app default branch had moved to `ad254d0` (U29 now
on it; U30 still absent from the app remote). A trial merge of this branch onto `ad254d0` in a throwaway
worktree conflicted only in `DEVELOPMENT_LEDGER.md` and `FEATURE_STATUS.md` (both updates append rows;
keep both), and the combined app suite gave 1940 passed, the same 4 pre-existing failures, 51 skipped. The
trial was discarded; nothing was merged. At the start of the session U29 was an unmerged branch. The
engine repository and CI are not reachable from this session. The U31 app branch is preserved; the
engine half (§7) has not been started because the engine source cannot be read or modified here.

## 11. Engine session (2026-10-17): the engine half

### 11.1 Verified before starting

| Item | Result |
| --- | --- |
| Both repositories | readable, all branches fetched, histories inspected; push verified by pushing the development branches below |
| GitHub Actions | **not reachable**: no `gh`, no API token in the session, the unauthenticated API is rate-limited and the private repository pages refuse access. No CI run was started or read by this session. |
| App default branch | `claude/emeraldtogether-combined-app` = `ad254d0` (Update 29 integrated) |
| Engine default branch | `claude/emeraldtogether-combined` = `8ea2b8c9` (Update 29 integrated) |
| Update 30 | exists on both remotes, **not integrated**: app `claude/dev-update30` (`f2e6b97`, 2 commits on `ad254d0`), engine `claude/dev-update30-gameplay` (`8b8bb92a`, 3 commits on `8ea2b8c9`). No ledger entry and no recorded CI run were found for it. |
| `check_rival_catalogue.py --engine` | **OK on the real engine** (U29 default `8ea2b8c9` and U30 `8b8bb92a`): the fork's maps, triggers, objects, constants and backgrounds equal upstream 1.17.1's |
| Baseline GBA ROM | U30 engine builds `pokedev.gba` = `f214735b…3387` (the documented hash) |

Audit correction found in the engine: the original Route 119 scene goes on with **Scott** (`addvar VAR_SCOTT_STATE, 1`);
the catalogue now lists it, and the multiplayer reward scene plays Scott's arrival.

### 11.2 What the engine does now (`include/multiplayer_rival.h`, `src/multiplayer_rival.c`, `data/scripts/mp_rival.inc`)

All of it is native PC only (`#ifdef PORTABLE` / `.ifdef PORTABLE`, `#line` kept, `multiplayer_rival.c` filtered out of the
GBA link like the other PC-only modules); **the GBA ROM stays byte-identical** (`f214735b…3387`).

| §7 item | Implementation |
| --- | --- |
| 1. catalogue check | passes; the checker now also verifies the battle environment's enum index and, on a ported engine, the preparation tag, the checkpoint numbering and that every original rival scene asks the multiplayer layer first |
| 2. `rival_abi_version` 1, `RivalRecord` | `gMultiplayerRivalAbiVersion` (PC executable symbol; `generate_manifest.py` reads it from the native symbols like the free-for-all marker and writes `rival_abi_version: 1`); the record is copied with the world mailbox's inbound snapshot (`reserved[8..15]`) and validated byte by byte. Multiplayer mode = connected and a valid record seen on this connection; masks are only ever OR-ed (completion is permanent); with no record for 10 s of field time the host is treated as one without rival checkpoints and the original scenes play. |
| 3. NPC rivals, barriers | the original rival objects of Route 103, Rustboro, Route 104, Route 110 (+ bike), Route 119 (+ bike) and Lilycove stay away in multiplayer (spawn filter; an object already on screen is removed without touching its save flag); every original rival script asks `MultiplayerRival_ScriptMode` first and plays unchanged only in the original mode. The Route 110 and Route 119 trigger lines stop a **northbound** player when `gate_blocks` says so (exclamation, message, one step back, the Players menu opens on its Rival checkpoint row); going back, walking along the line, inside buildings and elsewhere are never stopped; a save that passed the scene itself is never stopped. |
| 4. personal effects | on the player's own pass (`cleared`) and only while the save's own prerequisite holds: Route 103 (`VAR_BIRCH_LAB_STATE` 4 etc.; Birch's lab then gives the Pokedex and Poke Balls itself), Rustboro/Route 104 (Match Call registration, states 8/2), Route 110 (Dowsing Machine, `VAR_ROUTE110_STATE` 1), Route 119 (HM02 Fly, `FLAG_RECEIVED_HM_FLY`, `VAR_ROUTE119_STATE` 1, Scott, `VAR_SCOTT_STATE` + 1), Lilycove (the rival goes home). The trigger lines give theirs on the line; the others when the player is on the checkpoint's map. A world completion without the player's own pass shows a banner ("Continue the story") and gives nothing. |
| 5. battle environment | the host puts `MP_RIVAL_PREP_WORD` ('R' 'V', checkpoint 1..5, environment) into the native preparation's flags word; the engine accepts it for PvP battles only, and `battle_main.c` / `battle_bg.c` then use that environment on every core (PLAIN for all five) instead of the link arena / `BUILDING`. Background, Camouflage, Nature Power and Secret Power therefore agree on every core; the Diorama 3D battle keeps drawing the field. |
| 6. cutscenes | gate scene and reward scenes are local scripts with nothing waiting on the network (no lock can be left behind by a disconnect); when the checkpoint's lobby starts its countdown, every player there (their real avatars, drawn with their own looks by the presence layer) gets the trainer-spotted mark with the original sound and a banner; banners for "your battle is ready" and for completion; Scott's original arrival on Route 119. |
| 7. streamlined intro | `CB2_NewGame` (PC): after Birch's existing gender/name choice and `NewGameInitData`, the existing 18-starter screen, then the post-state of `docs/update31/intro-post-state.json`, the starter at level 5 met on Route 101, the respawn at the player's house, the spawn in front of the player's own door, a nickname offer, and one save. This is the New Game Update 30's character creation (`DraftRuntime`) already expects: a closed save with a starter. `PKMN_ORIGINAL_INTRO=1` keeps the original introduction (development only). |

Found and fixed during the port: a coordinate trigger whose script neither moves the player nor changes its variable fires
again on every frame (the original scenes always do one of the two), which held a player on the line indefinitely. Every
multiplayer path that lets the player pass now ends with one step on (north/south) or a lock/release (east/west).

### 11.3 App changes for the engine port

`rival_catalogue.py` (Scott; `ENVIRONMENT_IDS`, `preparation_word`), `native_battle.Preparation` (accepts a rival word),
`battle_desk.py` (`invite`/`invite_multi(environment=)`, part of the consent fingerprint, the view and both preparations),
`battle_protocol.py` (the `environment` field of a mode 2/3 challenge), `battle_session.py` / `battle_recovery_session.py`
(the companion checks the same preparation), `battle_reservations.py` / `battle_replay.py` (kept for exact recovery),
`server.py` (`enable_rival_battle_environment`, used by `launcher_session.py` when the installed manifest says
`rival_abi_version` 1; every player of a world runs the same build), `generate_manifest.py` (the marker).

### 11.4 Tests

| Test | Result |
| --- | --- |
| engine `make -f Makefile_pc NATIVE_LINUX=1 check-rival` (`--selftest-rival`) | 24 checks, 0 failed: the 160-case mode truth table against `gate_blocks` (2 blocking cases), malformed records, preparation words, object hiding, the intro post-state for both genders |
| engine `tools/pc_port/rival_check.py` (real scripts, headless, simulated host record) | see the ledger for the final count: gates, rewards once, catch-up, going back, walking along a line, Rustboro's open line, NPC objects away / present offline, the original NPC battle offline, PLAIN vs GRASS battle environment, the intro for both genders |
| app `tests/test_rival_environment.py` | 14 new tests: words, codec, real Desk singles and 2v2 with the word in every preparation and the durable record, consent, refusals, the companion validator, the server's enabled/disabled host, the manifest marker |
| GBA ROM | `f214735b…3387`, byte-identical; `check_gba_lines.py` 0 moved lines in the 8 changed GBA-compiled files |

Not exercised: a real game core in a real multiplayer rival battle (the environment word was tested through the Desk with
simulated receipts and through a real local battle with the word injected), two or more real PCs, Windows, a GPU, the
Players menu opening on a real host, the 3D build's look of the new scenes.

