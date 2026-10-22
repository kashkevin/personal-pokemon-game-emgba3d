# Development roadmap

The main checklist, as of 2026-10-09. It merges the unfinished items from
`docs/development-roadmap.md` and `PROJECT_STATUS_AND_HANDOFF.md` with the native PC
migration (Milestones A-G) and the development toolkit, in dependency order.
Requirements: `PROJECT_SPEC.md`. Status of each feature: `FEATURE_STATUS.md`.

How to read it:

- `[x]` means the cited source shows it done, within the scope that source states.
  `[ ]` means not done.
- IDs are for dependency notes. "Needs:" lists what must be done first.
- Emulator-build results come from earlier frozen builds; Milestone G re-checks them
  on the native build.
- Independent work may run in parallel; dependency and acceptance gates still apply.
  [road]
- Source tags are the same as in `PROJECT_SPEC.md`, plus: [mig] = native migration
  status of 2026-10-09 (`FEATURE_STATUS.md`, Native PC migration; matches engine commit
  `822ea59f9`); [vwd] = `docs/visible-world-design.md`; [eng-platform] = engine
  `src/platform/README.md`.

Order: Milestone A (now) -> toolkit (alongside A) -> owner decisions and records ->
B -> C -> D -> E -> F -> G -> gameplay steps 1-7 (AGENTS.md order) -> accepted
additions -> Hoenn content backlog -> future regions.

## Current priority: Native migration Milestone A (in progress)

Milestone A is the native engine: the game runs as a standalone program with no
emulator, ending in a Windows .exe. Work so far is on Linux. [dir] [base] [mig]

- [x] A1 Emulator baseline preserved: tag `emulator-baseline-20261009` in both
  repositories (app `7240c81`, engine `761c9c27f`), private checkpoint folder, ROM
  hashes. [base]
- [x] A2 Feature-status audit of the emulator baseline. [audit]
- [x] A3 Branch `claude/native-pc` created in both repositories at the baseline
  commits; the emulator branches stay untouched. [base]
- [x] A4 Engine compiles and links natively for Linux i386 (`Makefile_pc`). [mig]
- [x] A5 Launches on Linux under Xvfb. Needs: A4. [mig]
- [x] A6 Renders the intro, title screen, main menu, Professor Birch intro and naming
  screen. Needs: A5. [mig]
- [x] A7 Audio produces non-silent samples. Needs: A5. [mig]
- [x] A8 Investigate and fix the intro logo that appeared corrupted: the Linux build's
  "fast draw" renderer has no 256-colour backgrounds; both targets now use "easy
  draw". Decompression of all 7469 assets verified. Needs: A6. [mig]
- [ ] A9 Listen to the audio (so far only the samples were checked). Needs: A7. [mig]
- [x] A10 Overworld runs natively (Linux and Windows under Wine). Needs: A6. [mig]
- [x] A11 Movement (Linux and Windows under Wine). Needs: A10. [mig]
- [x] A12 Saves: save and reload natively in the GBA 128 KiB Flash format; emulator
  saves load (Linux and Windows under Wine). Needs: A10. [mig] [base]
- [x] A13 Battles: wild battles with Fight, Bag, switch, Run (Linux); fight and win
  (Windows under Wine). Trainer battles and Mega Evolution not run yet (B5). Needs:
  A10. [mig]
- [ ] A14 Build the Windows .exe and repeat the A5-A13 checks on Windows. Built, and
  A5-A13 pass under Wine in the cloud workspace; still to do: run it on the owner's
  PC (real GPU, sound, controller) and resolve or rule out KNOWN_ISSUES N20 (one
  unexplained crash). Needs: A4. [dir] [mig]
  2026-10-09: entering any Pokémon Center crashed natively (N24); fixed in engine
  `5b2bcb7ce`, verified on Linux and Windows (Wine).
- [x] A17 In-process soft reset (the game's `DoSoftReset`), Linux and Windows.
- [ ] A15 Licensing of the imported native platform layer (from
  ZallaxDev/pokeemerald-voxel-project): recorded in `docs/dependency-ledger.md`; still
  to do: replace or properly license the GPL/MPL-derived `bios.c` code before the
  native game is given to anyone. [agents] [eng-platform]
- [ ] A16 Keep the emulator build working as the fallback until Milestone G passes.
  [dir] [base]

Milestone A is stable when A8-A14 are done (A9 and the owner's-PC part of A14 remain).

## Development toolkit (being added alongside Milestone A)

- [x] K1 pytest: configured (`pytest.ini`, `conftest.py`, pinned venv); 1373 passed,
  1 skipped. Supports: all Python work. [dir]
- [ ] K2 Sanitizers and static analysis for the native build: UBSan build (found
  N13-N16), AddressSanitizer build (found N22) and the NULL trap are in use; clang
  static analysis not set up yet. Supports: A, B. [dir]
- [x] K3 Native C tests: `check-native` (1063 checks, plus 4186 bridge checks), `check-abi` (Linux and
  Windows), `check-game-sections`, `check-decompress` (7469 assets). Supports: A, B.
  [dir] [hand]
- [ ] K4 Multiplayer harness with application-level network simulation. Supports: C,
  G, step 7. [dir]
- [ ] K5 Graphics benchmark scene. Supports: D, F. [dir]
  Started: `PKMN_PERF_LOG=1` logs game and presented frames per second and the time
  per present every 5 s; the Diorama debug overlay (F3) shows triangles and draw
  calls. The fixed benchmark scene itself is not built.
- [ ] K6 CI workflow files: written (`.github/workflows/`), never run because neither
  repository is hosted on GitHub. Supports: all. [dir]

## Owner decisions and records

- [ ] O1 Personal vs shared wild spawns - Decision pending - owner to confirm. The
  earlier owner decision is personal spawns (as built); the newest directive lists
  shared, server-authoritative spawns. The audit asked for this before the migration.
  Blocks 9.13 and the spawn part of F1. [audit] [dir]
- [x] O2 Save the 2026-10-09 native PC directive verbatim as a `docs/project-*.txt`
  file (and the toolkit directive). [agents] [spec]
- [ ] O3 `docs/balance-defaults.md` is cited by four source files but does not exist:
  create it or point those comments at `PROJECT_SPEC.md` section 7. [audit]
- [ ] O4 Update `docs/master-spec.md`, `docs/visible-world-design.md` and
  `PROJECT_STATUS_AND_HANDOFF.md`, which still describe the 2026-10-09 rules as
  pending or design-only. [audit]

Other open decisions sit next to the work they block: 1.6, 2.6, 2.8, 8.7, 9.8, 9.19,
9.24, 9.25. Owner inputs (not decisions): 4.2, 7.1.

## Milestone B - gameplay integration

All of the project's gameplay code runs in the native build. [dir]

- [x] B1 Save layout parity: byte-identical save blocks (SaveBlock1 15568, SaveBlock2
  3884, SaveBlock3 600 bytes), so the Python readers and the stored 128 KiB Flash
  checkpoints keep working; otherwise migrate every reader and checkpoint. Needs: A12.
  [base] [audit]
  Done 2026-10-10: `check-abi` finds the three save blocks identical on GBA, Linux and
  Windows; the native game continues from emulator saves; the Python readers
  (`inspect_flash`, `inspect_ownership`) read every save the native game wrote, which
  equal their canonical checkpoints byte for byte; canonical checkpoints go back into a
  running native game by live recovery (`native-checkpoint-evidence.json`).
- [ ] B2 Adapt or confirm the GBA-specific parts of the project engine code: EWRAM
  mailboxes, Flash save path, RTC hook (host world clock while connected, local clock
  otherwise), 16-object / 64-sprite / palette budgets. Needs: A10. [audit]
- [ ] B3 Rework process and ROM handling for the native .exe: `player_runtime.py`,
  `draft_runtime.py`, `enrollment_runtime.py`, `trade_native_replay.py`,
  `game_import.py`, `game_patch.py` (today they launch mGBA or patch a GBA ROM).
  Needs: A14. [audit]
  Progress 2026-10-10: a native runtime bundle (`emerald-native-runtime-v1`,
  `scripts/windows-runtime/collect_native_bundle.py`) holds the exe and SDL2.dll and
  names the ROM build it pairs with; `player_runtime.py`, `enrollment_runtime.py` and
  `draft_runtime.py` start it with `--save`, `--bridge` (a private bridge.txt) and
  `--config` (engine `9e1de660f`: settings kept beside the launch folders) and refuse
  another ROM build before recovery. Proved through `PlayerRuntime` under Wine
  (`native-launcher-evidence.json`), and through the whole launcher (`LauncherWindow`,
  `SessionWorker`, `LauncherSession`, host and join, with world creation, host
  enrollment and the friend's invitation) with a 1v1 battle, both with two Linux games
  and with two Windows exes under Wine (`native-launcher-battle-evidence.json`). Still
  to do: the launcher on Windows itself with a native release (application folder and
  release record), the 3D exe through the launcher,
  and whether a native install still needs the user's GBA ROM (`game_import.py`,
  `game_patch.py`: the companion verifies it, KNOWN_ISSUES M1); `trade_native_replay.py`
  keeps its mGBA replay worker (B4).
  Launcher migration, 2026-10-10 (owner's priority): the launcher no longer needs mGBA
  for native gameplay: a native runtime bundle holds only the game exe and SDL2.dll (no
  mGBA, no Lua bridge), and every native proof above ran without them. Host loss and
  rejoin through the launcher pass (2 Linux, 2 Windows under Wine,
  `native-launcher-reconnect-evidence.json`). The launcher's controls help names the
  native game's keys for a native runtime; `build_launcher.py` accepts a native runtime
  for a development preview, and the private package "Native 3D preview 1" (the 3D exe
  as its runtime) was built under Wine: its file check accepts the native runtime,
  manifest and game file. The emulator runtime stays the rollback (branch
  `claude/continuation`, unchanged). Not run yet: that package played through, real
  Windows, a new character (draft) through the launcher.
- [ ] B4 Replace the mGBA-specific Windows runtime: SDL hooks and reset-chord filter
  (`native/windows-runtime/sdl-multiplayer.c/.h`) and the headless-mGBA trade replay
  worker (`trade-replay-worker.c`). Needs: A14. [audit]
- [ ] B5 Run the gameplay rows of `FEATURE_STATUS.md` that need no network natively,
  and record the results in its Native PC status column. Needs: B1, B2, K3. [audit]

## Milestone C - native multiplayer

- [x] C1 A native bridge replaces `bridge/mgba.lua` and preserves the protocol; the
  Python host and companion stay. Needs: B2. [dir] [audit]
  Done 2026-10-09: engine `src/platform/mp_bridge.c` (`e2e3917e2`), a line-for-line C
  port with the Lua bridge's checks; native clients joined an unchanged server through
  unchanged companions (C6). `edb755a26` departs from the Lua budgets on purpose so
  the bridge keeps up below 60 frames a second (KNOWN_ISSUES M4); 4186 unit checks.
- [ ] C2 Native in-process interface for the mailboxes (presence EMP1 128 B; save 512 B
  plus the 4 KiB save window; battle and menu 512 B each; reset 128 B; trade effects;
  world EMW1 256 B), keeping the struct layouts as contracts and replacing the
  ELF-symbol manifest (`scripts/multiplayer/generate_manifest.py`). Needs: C1. [audit]
  In progress: the bridge takes every mailbox and marker from the executable's own
  symbols (layouts checked by `abi_layout.py`); the companion still verifies the GBA
  ROM's manifest, and pairing the executable with it is open (KNOWN_ISSUES M1).
- [ ] C3 Battle transport natively (today the GBA link layer: SendBlock /
  GetBlockReceivedStatus). Needs: C2. [audit]
  Progress 2026-10-10: the battle mailbox path runs natively through the C bridge: a
  1v1 between two native games routed 362 blocks, the same count and forced switch
  as the emulator qualifier wqb1, on Linux and with the Windows exe under Wine
  (`native-launcher-battle-evidence.json`). 2v2 with four clients and full parties
  passes through the launcher (native-launcher-multi-10: 5545 routed blocks, the
  same result for all four, parties back, saves, fresh Continue;
  `native-launcher-multi-evidence.json`), after harness fixes and one product bug
  (M6). Not run yet: Windows clients and the 3D build in multiplayer battles.
- [ ] C4 Input and reset-chord routing through the native bridge (today in the Lua
  bridge and the SDL adapter). Needs: C1, B4. [audit]
  Done in code (the SDL adapter's guard ported, unit-tested with its own cases); the
  native reset handler taking the chord has not run in gameplay yet.
- [ ] C5 Rebuild the proof and qualification harness for the native build (today
  libmGBA `harness.c`, `scripts/multiplayer/*_proof.py`,
  `scripts/windows-runtime/qualify_*.py`); it produced all current evidence. Needs: C1,
  K4. [audit]
  Started: `scripts/multiplayer/native_presence_proof.py` drives 2-4 real native
  clients (Linux, Windows under Wine, or the 3D build) with key presses on their own
  X displays (door map change, companion restart optional);
  `native_checkpoint_proof.py` adds the ownership store and live checkpoints;
  `native_trade_proof.py` a trade through the Players menu; `native_launcher_proof.py`
  the launcher's `PlayerRuntime`; `native_launcher_battle_proof.py` ports the Windows
  1v1 qualifier (`qualify_menu_battle.py`) with the whole launcher; its
  `LauncherHarness` is reused by `native_launcher_reconnect_proof.py` (host loss and
  rejoin) and `native_launcher_multi_proof.py` (four players, 2v2).
- [ ] C6 Two, then four native clients: connect, see each other, move, change maps,
  disconnect and reconnect, then trade and battle. Needs: C2-C5. [audit] [brief]
  In progress: connect, see each other and move pass with 2 Linux, 2 Windows (Wine),
  4 Linux and 2 3D clients; a door map change (2, 4 and 3D clients) and a companion
  restart while the game runs (2D and 3D) pass (`native-presence-evidence.json`); live
  checkpoints into the ownership store pass with 2 Linux, 2 Wine and 2 3D clients:
  enrollment, a save after walking, both games restarted, saves after the restart,
  and live recovery into a running game (2 Linux, 2 Wine)
  (`native-checkpoint-evidence.json`); a trade through the Players menu with its cancel
  path and a restart (2 Linux and 2 Windows under Wine, `native-trade-evidence.json`);
  a 1v1 battle through the Players menu between two games the launcher started (2
  Linux and 2 Windows under Wine, `native-launcher-battle-evidence.json`); the host
  lost and the friend rejoining through the launcher with its unsaved progress kept (2
  Linux and 2 Windows under Wine, `native-launcher-reconnect-evidence.json`); a 2v2
  with full parties between four launchers' games (4 Linux,
  `native-launcher-multi-evidence.json`). Next: trades and battles in the 3D build; a
  network loss while the host keeps running (`native_launcher_reconnect_proof.py
  --drop`, written); a host loss during a battle or a trade.

## Milestone D - enhanced graphics

The highest priority once the native engine (Milestone A) is stable. [dir]

- [x] D1 Research: the voxel project's own Diorama build was run separately, outside
  our engine. [mig]
- [x] D2 Before importing anything: license, attribution, exact revision, dependencies
  and performance of the Diorama renderer (ZallaxDev/pokeemerald-voxel-project) and of
  the ZallaxDev/pokeemerald-3Ds-dualscreen graphics; record them in
  `docs/dependency-ledger.md`. [agents] [vis]
  Done 2026-10-09: voxel `cfb429bd1` (MIT) imported and recorded; 3DS `4a699e3` (MIT)
  recorded as research reference until code is ported (D4). Performance: software-GL
  numbers only (KNOWN_ISSUES V3); real-GPU numbers come from the owner's PC test.
- [ ] D3 Integrate the Diorama renderer as the technical base, kept separate from
  authoritative gameplay state; graphics never override save, trade, battle, ownership
  or recovery guarantees. Needs: A stable, D2. [dir] [spec]
  In progress (engine branch `claude/native-graphics`, `DIORAMA=1`): renders Route 101,
  Oldale, Littleroot and a Pokémon Center interior in 3D on Linux and Windows (Wine);
  the renderer only reads a per-frame snapshot of game state. Battle start from the
  3D view and soft reset in 3D verified. Open: follower during Poké Ball animation
  (V1), real-GPU test, wider map coverage, merge into `claude/native-pc` after parity.
- [ ] D4 Adopt the enhanced dimensional overworld graphics of
  ZallaxDev/pokeemerald-3Ds-dualscreen - graphics only, not its dual-screen interface.
  Needs: D3. [dir]
  In progress (engine `claude/native-graphics` up to `7a200f33d`): modelled buildings
  and furniture (its generator, 475 models from our maps), walkers drawn whole in
  front of furniture and walls (its `ModelPush` plus upright-card depth), sun shadows
  (shadow map; none indoors or in bad weather, half at night) - visually rendering on
  Linux and Windows (Wine), software GL only. Since then (graphics up to `edd1f5105`):
  doors on models, colour grade, cast sprite shadows, the 3DS tree style, weather
  light, dapples, dust, rays, bloom, fog banks and a dark cave's light, all visually
  rendering. Defaults (the owner's choice, 2026-10-10, graphics `2057c4ac7`): the 3DS
  close camera and the 3DS trees; F7 and F8 switch both, and a camera, zoom, tilt or
  tree style the player saved is kept. Remaining, in the order of
  `docs/diorama-3ds-gap-analysis.md`: signposts (compared, not worth it as is),
  relief. Graphics overhaul phase 1, step 1 (graphics `graphics-wip-20261010-6`,
  `docs/graphics-overhaul.md`): Adventure, Diorama and photo cameras, F12 pictures,
  a 49 x 49 scene fading into the sky, Petalburg Woods in 3D. Next in phase 1:
  neighbouring maps with other tilesets, a readable player behind buildings.
  3D battle scenery, 2026-10-10 (owner directive "INTEGRATE EMERALD 3DS BATTLE
  GRAPHICS ONLY"): ported on engine branches `claude/battle-3d` and
  `claude/battle-3d-integration` (the latter on graphics `3e39f2b15`), kept off
  `claude/native-graphics` until the owner merges it (`docs/battle-3d.md`): wild,
  trainer, double, Mega, catch, defeat, terrains and return to the field verified
  on software GL (Linux, Windows under Wine). Open: multiplayer battles in 3D (after
  C3), real-GPU frame rate (V3), the visual problems in `docs/battle-3d.md`. The
  native crash fixes found on the way (KNOWN_ISSUES N26-N32) are on `claude/native-pc`
  (cherry-picked, `8f32fa79e`, `52844189f`, `fb6ee9455`) and in the graphics branch
  (merge `5a4431686`); the battle branches themselves were not changed.
- [ ] D5 Keep previous working assets recoverable and the asset inventory current
  (source, creator, license, coverage, states, changes, missing art). Needs: D4.
  [vis] [spec]
- [ ] D6 Measure with the graphics benchmark scene: four players, followers, mounts,
  visible wild Pokémon, NPCs, weather and effects together. Needs: K5, D4.
  [dir] [vis] [spec]

## Milestone E - single-screen PC UI

- [ ] E1 Single-screen PC interface starting at 1920x1080. Needs: A. [dir]
  Started: `windowScale=6` gives a 1920x1080 window, F11 toggles fullscreen (graphics
  branch); not yet seen on a 1080p display.
- [ ] E2 Keyboard support. Needs: E1. [dir]
- [ ] E3 Controller support. Needs: E1. [dir]
  2026-10-10: the Windows exe no longer imports `xinput1_3.dll` (part of the old
  DirectX redistributable, not shipped with Windows 10/11: without it the game could not
  start); it loads XInput at run time
  (`xinput1_4`, then `1_3`, then `9_1_0`) and works without it (engine `34ddb17a6`,
  KNOWN_ISSUES N34). No physical controller tested.
- [ ] E4 Local Soft Reset classic chord and Select input on keyboard and controller.
  Needs: E2, E3, C4. [lsr] [audit]

Physical keyboard and gamepad input was never qualified on the emulator build either.
[hand]

## Milestone F - visual integration of all gameplay systems

- [ ] F1 Every gameplay system shows correctly in the new renderer and UI: Trainers and
  appearance, remote players, followers, mounts, visible wild Pokémon including
  shinies, World Events and notices, NPCs, weather, day/night, the Players, trade,
  battle and Championship menus, and battles. Needs: B5, C6, D4, E1. [dir] [vis]
- [ ] F2 Crowded four-client scenes stay within the measured budget; stability comes
  before extra effects. Needs: F1, D6. [vis] [spec]

## Milestone G - regression parity with the emulator build

- [ ] G1 Make the emulator reference current: rebuild the Windows emulator runtime
  (6.3) and re-run the audit's Delta rows on the baseline. [base] [audit]
- [ ] G2 The native build passes the same gameplay tests as the emulator build: every
  "Implemented and tested" row and the 15 behaviours in `FEATURE_STATUS.md`. Needs: C6,
  F1, G1, K4. [base] [audit] [dir]
- [ ] G3 Only after G2 does the native build replace the emulator build; until then
  the emulator build is the fallback. [dir] [base]

## Gameplay roadmap

The owner's order from `AGENTS.md`: safe trading; battles and teams; four actual
clients; Local Soft Reset with its encounter/RNG foundation; automatic saving and
disconnect handling; Windows Host/Join packaging; Wi-Fi/Internet acceptance and polish.
Customization, friendship/Lucky Trades and the Shiny Charm/Game Corner are scheduled
around those, and the Gen 1-6, Mega, follower, event and campaign content stays in
scope. [agents] Checks can run on the emulator baseline (they become G's reference)
and must then pass natively in G. [audit] [base]

### 1. Safe trading

- [x] 1.1 Exact-swap trading: offers, consent that any edit cancels, atomic paired
  saves, retries and committed recovery; native offer/confirm, cancel, exchange, saves
  and fresh Continue on actual cores (earlier builds). [hand]
- [x] 1.2 Supported trade-effects flow (wqte4): two actual Windows clients, an eligible
  non-evolving pair, candidate review, native replay, atomic paired save/history
  commit, both Received notices, saves and fresh Continue. [hand]
- [x] 1.3 Windows trade replay worker: actual-ROM Machoke to Machamp evolution,
  paired-save and restart replay on disposable fixtures. [hand]
- [ ] 1.4 Fix the evolution move-choice screen: `trade_effect_choice.py:53` still
  rejects stored move ids above 621, so a trade that evolves a Pokémon already knowing a
  later-generation move fails; the owner decided such moves trade as-is. [audit]
- [ ] 1.5 Genuine evolution and move-learning trades in actual gameplay. Needs: 1.4.
  [hand]
- [ ] 1.6 Decision: original-world geography policy, needed before upgrading any
  original world. [hand]
- [ ] 1.7 Interrupted trade-effect cases (disconnect, host restart) in actual gameplay.
  Needs: 1.5. [hand]
- [ ] 1.8 Eggs, mail and unsupported forms (refused today, `trade_eligibility.py:107-111`)
  need their own adapters. [hand] [audit]
- [ ] 1.9 Re-run trading on the emulator baseline (Delta: Lucky/fence changes). [audit]

### 2. Battles and teams

- [x] 2.1 Players menu: team invite, accept, leave and change; four battle consents;
  cancel before binding (four actual cores). [hand]
- [x] 2.2 1v1 through Windows menus (wqb1, parties 2 vs 1); four-client 2v2 (wqm1,
  parties 2/1/1/1); full-six 2v2 on four actual cores (run 5). [hand] [audit]
- [x] 2.3 Neutral battle-entry cancellation before BIND: three actual-core cases and
  the Windows launcher run wqc8. [hand]
- [x] 2.4 Durable completed-battle history: exactly one immutable result after all
  releases, with retry and host restart. [hand]
- [ ] 2.5 Re-run battles on the emulator baseline (Delta: battle code 923dc64,
  761c9c27f, cd951f7). [audit]
- [ ] 2.6 Decision: wager pot, ties, interruptions and forfeits. [spec]
- [ ] 2.7 Full-six 2v2 through Windows menus. Needs: 2.5. [audit] [hand]
- [ ] 2.8 Decision: should teams persist across disconnect and restart (session-local
  today)? [audit]
- [ ] 2.9 Cleanup for an entry refused after BIND (bound/prepared cancellation). [hand]
- [ ] 2.10 Battle speed: the recorded full-party headless battle took 45.6 minutes;
  measure and improve. [hand]
- [ ] 2.11 Championship: four actual clients play two semifinals and a final; an
  uncertain issued match is recovered, never silently replaced. [audit] [hand]
- [ ] 2.12 Wagers: 1v1 and 2v2 win, draw, cancel and interrupt, with money checked in
  every save. Needs: 2.6. [audit]

### 3. Four actual clients

- [x] 3.1 Four actual cores: presence, ownership, capacity (a fifth player is refused)
  and rejoin (older build). [hand] [audit]
- [ ] 3.2 One combined four-client run on a single candidate: independent maps,
  encounters and saves, two teams at once, trading, 1v1 and 2v2, join/leave/rejoin,
  capacity and host restart. Needs: 1.9, 2.5. [road]
- [ ] 3.3 Shared-world sync over EMW1 (followers, mounts, appearance, clock, World
  Events) with four clients; never run. [audit]

### 4. Local Soft Reset

- [x] 4.1 Development reset encounter: 21 checks with four actual cores (fresh local
  rolls, other players unaffected, capture, checkpoint, fresh Continue). [hand] [audit]
- [ ] 4.2 Owner input: a legitimately progressed private save, needed to reach the
  authored static encounters. [hand]
- [ ] 4.3 Ticket access path for Ho-Oh, Lugia, Mew, Deoxys and Southern Island (today
  only vanilla Mystery Gift / record-mixing scripts give the tickets). [audit]
- [ ] 4.4 Production hunts: each of the 25 source families on progressed saves with
  three peers active; Select and classic chord input; cancellation, capture and
  interruption; durable attempt counts; Charm effect. Needs: 4.2 (and 4.3 for ticket
  sources). [audit] [hand]

### 5. Automatic saving and disconnect handling

- [x] 5.1 Autosave every 5 minutes with a per-character off switch, manual saves and
  fresh Continue on actual Windows (wqt2); visible toggle and Save now
  (launcher-gui-proof-1). [audit]
- [x] 5.2 Host-loss field preservation: safe field and interrupted export, held core,
  authenticated rejoin, fresh Continue (actual cores). [audit] [hand]
- [x] 5.3 Interrupted battle waits for all four: host loss before BIND, mid-battle and
  after RELEASE, parties 2/1/1/1, checkpoints and fresh Continue (four actual cores).
  [audit] [hand]
- [ ] 5.4 Host loss during an authored static hunt, a trade or a multiplayer battle;
  Windows host-loss UI; four simultaneous clients. [audit]
- [ ] 5.5 Full-six interrupted battle to completion (runs 3 and 4 failed); an
  interrupted Windows match; co-op and wager modes. Needs: 2.7. [audit] [hand]
- [ ] 5.6 Recovery after process death or host power loss: unsupported today and needs
  its own design. [hand] [audit]
- [ ] 5.7 Save pause: each save pauses the game about 6.3 seconds. [audit] [hand]
- [ ] 5.8 Autosave through the packaged launcher buttons. [audit] [road]
- [ ] 5.9 Upgrade the original private worlds (backed-up friendship, effect and reset
  feature upgrade; legacy handler-friendship history), tested on copies first. No
  original world has been migrated yet. Needs: 1.6. [hand] [readme] [spec]

### 6. Windows Host Game / Join Game packaging

The delivery target is now the native .exe; the emulator package is the fallback until
Milestone G. [dir] [base]

- [x] 6.1 The owner's dump produced a reconstructing BPS patch. [hand]
- [x] 6.2 Private candidate9: recursive audits, packaged-resource import and retry,
  executable startup and normal closure, isolated GUI import. [hand]
- [ ] 6.3 Rebuild the Windows emulator runtime: the built one predates two baseline
  source changes (Lua bridge presence/world frame alternation; the replay worker
  accepting the Lucky bit), so it cannot exercise the Oct 9 features yet. [base]
- [ ] 6.4 One frozen package: clean-PC install, import, first character, Host/Join,
  controls, autosave, error messages and updates. Needs: 6.3 for the emulator package,
  or A14 and B3 for the native one. [road] [hand]
- [ ] 6.5 Release content review: distribution terms for bundled code and game assets.
  [hand] [spec]

### 7. Wi-Fi/Internet acceptance and polish

- [ ] 7.1 Owner input: separate Windows PCs, another network and participant, and real
  input devices. [hand]
- [ ] 7.2 Separate-PC LAN/Wi-Fi and port-forwarded Internet: firewall and port setup,
  latency, loss and reconnect, matching builds, transport security, performance and
  clear recovery. This is the delivery acceptance gate. Needs: 6.4, 7.1 (K4 for network
  simulation beforehand). [road] [hand] [dir]

### 8. Accepted additions

**Trainer customization**

- [ ] 8.1 Hair style, clothing shapes, hats and accessories, body, and creation at game
  start (today: palette recolour of Brendan/May with a STYLE editor). [audit] [cfc]
- [ ] 8.2 Fix the `appearance.py` describe() labels that disagree with the ROM tables.
  [audit]
- [ ] 8.3 Appearance sync on four clients. Needs: 3.3. [audit]

**Friendship and Lucky trading**

- [ ] 8.4 Friendship points from real trades, battles and events; daily caps;
  persistence across host restart. [audit]
- [ ] 8.5 Lucky trade in an actual trade: forced Lucky, no re-roll on retry or
  restart, host and native candidates match; Lucky Pokémon summary, IV floor and marker
  survive save, trade and evolution. Needs: 1.5. [audit]
- [ ] 8.6 Lucky Friends: the flag survives cancel, retry and reconnect and is used
  exactly once. [audit]
- [ ] 8.7 Decision: secondary Lucky benefits, repeated Lucky conversion, both sides of
  a Lucky trade (the code makes both received Pokémon Lucky), IV changes that alter
  Hidden Power's type. [road] [audit]

**Shiny Charm and Game Corner**

- [ ] 8.8 Game Corner purchase (9,000 coins), persistence and effect: holder vs
  non-holder; World Events unchanged. [audit]

**Queued by the owner (2026-10-21/22; not started unless marked)**

- [~] 8.9 Battle Tower: Legends (QUEUED 1): 100 floors, bosses, solo and Duo, checkpoints, experience cap, rewards,
  Bottle Caps, Hyper Training, Ability Patch, Tower Shop, Mega floors, native UI. Implemented (app `tower*.py`, engine
  `src/tower_legends.c`); verification in progress: all 100 floors won and lost (L, test build), launcher proofs (L,
  W), deliverables 1-15 report (`docs/battle-tower-legends.md`). See TEST_LEDGER and KNOWN_ISSUES MS-47 to MS-52.
- [ ] 8.10 Six-player worlds and eight-competitor Championships (QUEUED 2): worlds of up to six players (today four:
  the host, the menus, PLAYERS, the battle desk and the lobbies assume at most four), Championships of eight
  competitors with AI trainers filling the empty places. Not started: needs a design pass over every four-player
  limit (world server, presence, battle router, menus, launcher) and its own Windows multiplayer proofs.
- [ ] 8.11 Comprehensive game-wide QA update (owner request, kept separate from the Tower): every map, trainer,
  NPC, item, warp and feature of the whole game re-verified on the current build (the QM inventory and accelerated
  gameplay checks as its base), with Windows runner coverage wherever feasible and a per-feature Passed on Windows /
  Linux only / Failed / Blocked / Unverified / Not implemented record. Not started: queued after the Tower's
  integration.

### 9. Hoenn content backlog

**Gen 1-6 profile**

- [x] 9.1 Gen 6 defaults candidate: selected settings, with an actual Windows 1v1 on
  the Gen 6 ROM (wqg2); not the entire ruleset. [audit] [hand]
- [ ] 9.2 Gen 6 open items: B_EXTRAPOLATED_MOVE_FLAGS, B_X_ITEMS_CROSSUSE,
  B_THUNDERSTORM_TERRAIN, B_RUN_TRAINER_BATTLE, B_AFFECTION_MECHANICS, Gen 6 affection
  vs friendship; mechanic matrix in actual battles. [audit]
- [ ] 9.3 The 721 boundary on every acquisition path (TM, tutor and egg data,
  evolutions into Gen 7+ species, gifts), with actual capture, evolve and trade runs.
  [audit]
- [ ] 9.4 Fairy matchups (vs Dragon, Steel, Fighting, Poison) in an actual battle.
  [audit]
- [ ] 9.5 18 starters: New Game, each pick, first battle, save, fresh Continue,
  enrollment. [audit]
- [ ] 9.6 Wild pool: per-map sampling (land, surf, fishing, Rock Smash), rarity
  histogram, base stages early, no Legendaries (confirm the roaming Latios/Latias
  exception). [audit]
- [ ] 9.7 Shinies: in battle, in the overworld, as a follower, after a trade and after
  fresh Continue. [audit]

**Mega Evolution**

- [ ] 9.8 Decision: later-Mega adaptations (Dragonize 20% vs 30%, Mega Sol, Eternal
  Floette and Zygarde Complete prerequisites, Rayquaza via Dragon Ascent) and Mega
  capture, form duration and reversion rules. [audit] [spec]
- [ ] 9.9 Official per-form Mega ledger vs the current official list. [audit]
- [ ] 9.10 Mega Ring from Flannery, Mega Stone purchase and holding, Mega Evolution in
  battle, one per trainer in native 2v2. [audit]

**Visible world** (amendment order: synchronized entities, visible wild Pokémon, spawn
sync, followers, clock, time mechanics, mounts, then visuals and performance) [vis] [road]

- [x] 9.11 Remote running animation: two actual cores, four directions, existing art
  (Brendan, one map). [hand]
- [ ] 9.12 Visible wild Pokémon: spawn, approach, battle, catch and run-return in
  actual cores; object budget (16 objects) with four players. [audit]
- [ ] 9.13 Shared spawn synchronization, only if O1 confirms shared spawns. The owner
  first needs rules for shared-spawn RNG and the Charm, mixed progression, and
  catch/defeat/run/disconnect/crash. Needs: O1. [spec] [vis]
- [ ] 9.14 Traditional encounter adapters verified (Repels, fishing, Surf access,
  scripted encounters, encounter-free areas), since random grass/surf encounters are
  now off. [audit] [vwd]
- [ ] 9.15 Followers: four-client sync, indoors and large Pokémon, shiny, transitions,
  object and palette budget. Needs: 3.3. [audit]
- [ ] 9.16 Day/night: same time and tint on four clients, pause at 0 players, host
  restart. [audit]
- [ ] 9.17 Audit every RTC consumer now on the 12x clock (berries, daily events, tides,
  Shoal Cave, timed events). [audit] [vwd]
- [ ] 9.18 Time mechanics: the 10 Gen 6 time-evolution branches on both sides of each
  boundary under the world clock; the exact XY/ORAS hour boundaries are still unknown.
  [audit]
- [ ] 9.19 Riding: collisions, ledges, water edges, remote rendering, follower to mount
  to follower; decision on the exact mount speed (pending). [audit] [spec]
- [ ] 9.20 Weather maps (rain, ash, sandstorm) with four players, followers and
  day/night tint. [audit]
- [ ] 9.21 Major visual overhaul, environmental effects and performance work: now
  delivered through Milestones D and F on the native build. Needs: D, F. [vis] [dir]

**World Events**

- [ ] 9.22 Spawn, notice, travel, claim and catch with 2-4 actual clients; Mega capture
  result and stone; a two-player race. [audit]
- [ ] 9.23 Lost result report: the claim is released 120 s after the claimant
  disconnects, so a lost catch report could let a second player catch the same
  Pokémon. Resolve and test. [audit]
- [ ] 9.24 Decision: World Event timers during downtime or empty sessions (today they
  keep counting while the host app runs with nobody online) and mixed-progression
  scaling. [spec] [audit]

**Campaign**

- [ ] 9.25 Decision: co-op story eligibility, badge advancement and mixed progression.
  [spec]
- [ ] 9.26 Twin Gym Leaders: all eight Gyms with a team; first-win badge vs helper
  prize. Needs: 9.25. [audit]

**Later systems**

- [ ] 9.27 Custom 1v1v1v1, researched and built as its own project once conventional
  battles are stable. Needs: step 2. [brief] [spec]
- [ ] 9.28 Multiplayer Pokémon League and expanded endgame systems: Planned in the
  audit, with no requirements written yet. [audit]
- [ ] 9.29 Hoenn polish: stable, polished Hoenn multiplayer with all accepted systems,
  UI, performance and lifecycle tests. Needs: everything above. [brief] [spec]

## Future regions (after Hoenn is stable)

- [ ] R1 Design the first additional region only after 9.29, one region at a time
  (Kanto, Johto, Sinnoh, Unova, Kalos), as content in the same game (never by combining
  ROMs), with trainers, wild encounters and Gyms scaled for existing progression;
  measure map, save and rendering budgets first. Needs: 9.29. [brief] [gen6] [spec]

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
[vwd]: docs/visible-world-design.md
[mig]: FEATURE_STATUS.md#native-pc-migration
