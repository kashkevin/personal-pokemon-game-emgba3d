# EmeraldTogether development ledger

Persistent record of the autonomous work queue that follows `EMERALDTOGETHER_SIX_ISSUE_DIAGNOSIS.md`.
One task at a time; each entry names what was done, the evidence, the commits, what is unverified and the
next step. Never edited to hide a failure: a failed or reverted attempt stays recorded.

Branches (nothing merged into the combined branches; no force-pushes):

| Repo | Branch | Based on |
| --- | --- | --- |
| App | `claude/dev-m25-stability` | `claude/admiring-bohr-dpxzuy` (diagnosis, packaging) |
| App, integration (Opus session) | `claude/dev-integration` = dev-m25-stability + `claude/graphics-mode-selector` | merge commit `a5d8fa4` |
| Engine, integration (Opus session) | `claude/dev-integration-engine` = dev-stability-engine + `claude/graphics-mode-engine` | merge commit `2e3e9d49` |
| Engine | `claude/dev-stability-engine` (created at P3; pushed) | `claude/cloud-setup-engine` |
| Graphics mode (separate work, not duplicated here) | app `claude/graphics-mode-selector`, engine `claude/graphics-mode-engine` | CI run 38655648745 pending when this ledger began |

## Queue

| # | Task | Status |
| --- | --- | --- |
| P1 | M25 multiplayer battle performance | done for what is safe (−12 % to −28 %); two further levers need Opus (see entry) |
| P2 | Four-player 2v2 and recovery (journal growth) | done for what is safe (reload −47 %); journal-format reduction and the full-six proof need Opus / owner data (see entry) |
| P3 | Co-op EXP / Exp. Share verification | verified; parity test added; no confirmed bug; persistence and farming are owner decisions |
| P4 | Stability: clock self-test, UBSan coverage, M27, GEN_6 test review | done (clock, sanitizers, M27, GEN_6 review); battle/animation sanitizer coverage still needs a driver |
| K | Customizable keybinds (inspected: **did not exist**, built from scratch) | done and tested; not tried on a real PC |
| P5 | Incomplete features audit and partial completions | audited; status refreshed; owner decisions listed; no new mechanics built |

## P1 — M25 multiplayer battle performance

**Measured with** `tests/test_battle_throughput.py` (real host, server and client session; synthetic native
core; asyncio debug mode off; only the relay phase timed; `-s` prints the numbers; `BATTLE_BENCH_OLD_POLL=1`
emulates the old fixed 10 ms poll).

| Case (battle start-up: no gameplay turns) | Before | After | Change |
| --- | --- | --- | --- |
| 2 players, instant core | 2.1 s (96 native commands) | 1.5 s (96) | −28 % |
| 2 players, 16 ms game delay per command | 3.4 s | 3.0 s | −12 % |
| 4 players, 16 ms game delay | 8.1 s (264 commands) | 6.2 s (264) | −24 % |

(Five to six runs each; run-to-run noise about ±0.2 s. The command counts are unchanged: this is host and
client overhead per command, not fewer commands.)

**Corrections to the diagnosis (measured, not assumed).** The 10 ms client sleep is *not* the main cost: the
adaptive poll alone was worth about 10 %. Profiling the relay phase showed ~40 % of host time in repeated
canonical-checkpoint reads (SHA-256 of the whole save, SQLite, flash decoding): `battle_desk.refresh()` re-read
and re-hashed every participant's checkpoint on every RPC (about 15 reads per native command) only to compare
revision and hash. KEEP was sent every step although every accepted native command (QUERY included) already
refreshes the game's own deadline.

Changes (app only; no protocol, journal format or ABI change):
1. `battle_session.py`: client poll 1 ms right after activity, doubling to the old 10 ms when idle.
2. `storage.py` `checkpoint_head()` + `battle_desk.refresh()`: compare (revision, sha256) from the metadata row
   instead of reading and hashing the payload. Readers of the payload still verify it.

**Tried and reverted (recorded on purpose; both need Opus-level reading of the recovery flow).**
* A lease-only check in `battle_desk._get` (skipping the checkpoint read) broke seven host-restart recovery
  tests: the recovery flow reaches `_get` with a battle's original lease. `_get` still uses the full `_auth`.
* Throttling the per-step KEEP to once a second (it removed 18 of 20 KEEP round trips and gave another −15 %)
  made `test_battle_recovery.py::test_uncertain_successful_release_reconciles_without_replaying_gameplay` fail
  deterministically (the test client stalls after the first command); with `KEEP_INTERVAL = 0` it passes. The
  game's own deadline is refreshed by every accepted command, so the cause is a host-side dependency on a KEEP
  per step that I could not find in the time I allowed it. KEEP therefore stays one per step.

**Evidence:** the battle test group (arbitration, execution, desk, recovery, recovery session, admission intent,
protocol, native battle, launcher battle recovery/admission, native resume, co-op battle, the new throughput
tests): **182 passed, 1 skipped** (2026-10-15). Real game and real network are **not** measured here (the earlier cloud runs
and a real PC are the ground truth: expect the host-side gain, not the 1-2 game frames per command).

**Not done / next:** the remaining costs are per-command durable writes (about 20 % of the relay phase here),
128-byte READ_OUT/RECEIVE chunks and a QUERY every step. Both need a protocol or ABI change: only if a real run
shows the gain above is not enough. Fast-forwarding the game's frames while a command is outstanding (engine,
PC only) is the next cheap lever for real games; it needs a real-game measurement.

## P2 — Four-player 2v2 and recovery (journal growth, reload cost)

**What the code already had (found, not built):** the 66 MB journal timeout from the diagnosis was already
addressed in this lineage by `BattleRecoveryService._journal_ready` (the load runs in a worker thread, with
exact-byte re-verification), recorded in `docs/native-battle-recovery.md` (copied-world loopback: 303 RPCs,
longest 0.153 s). What remained is the *cost* of the load itself.

**Measured** (synthetic two-player journal built with the recovery fixture's own encoder; 108,007 events,
65.2 MB, about the size of the failed full-six run's 110,048 events / 66.4 MB; this machine):

| | Before | After |
| --- | --- | --- |
| `RouteJournal` reload | 12.3 s (114 µs/event) | 6.5 s (60 µs/event), **−47 %** |
| `verify_current` | 0.2 s | unchanged |

Profile of the old load: about 60 % in `NativeControl` unpack/validation (a UUID parsed 5 times per event, a
tuple of every enum member rebuilt per field) and about 15 % in encoding each record twice.

Changes (no journal format, protocol, ABI or validation change):
1. `battle_mailbox.py`: `_uuid` and the UUID text of unpacked controls are cached (`lru_cache`, same accept/reject
   rules); `_enum` uses a per-enum frozenset with the same membership as `tuple(enum)`.
2. `battle_execution_journal.py` `_record`: the value is encoded once instead of twice; the bytes are identical
   (pinned by a test against the old formula, including non-ASCII and escaping).

**Evidence:** `tests/test_journal_load.py` (bytes unchanged vs the legacy encoder, growth bound ≤ 700 B/event,
reload ≤ 400 µs/event). The 34 battle/recovery/admission/native modules: **381 passed, 19 skipped** (2026-10-15).
Not a real game: a real run is the only proof that a full-six interrupted battle completes.

**Not done, and why:**
* **Fewer journal events per battle** (110k events for one full-six battle; each native command is 2 events plus
  a QUERY and KEEP every step) changes the journaled opcode set that recovery replays. That is the same
  protocol/recovery redesign as M25 F2: **recommend Opus** (invariants across journal, resume and admission). Not
  started. Snapshot-plus-tail loading has the same dependency.
* **The full-six `--scenario all --require-full-parties` proof** needs the owner's four private source parties and
  about two hours per run on the owner's machine; not runnable in this cloud environment, so it remains
  unverified. Likewise client (not host) disconnect mid-battle on a real core, Windows interrupted 2v2, and four
  real PCs.
* Turn order and targeting are covered by the engine's 66 focused tests (`docs/native-full-multi.md`); the engine
  suite is run at the P4 milestone.

## P3 — Co-op EXP and the permanent Exp. Share

**Result: verified by test and code reading; no confirmed bug; one test added; nothing in the game changed.**

Engine commit `8176fc07` on `claude/dev-stability-engine` (test only, `src/platform/native_selftest.c`).

* **Parity with the battle's own EXP path (new).** `MultiplayerCoop_ExpReward` repeats `Cmd_getexp` states 1-2.
  The old self-test compared it with a hand-written Gen 6 calculation that skipped Lucky Egg, traded, Exp. Charm
  and the level cap. The new check runs the multiplier chain through the **real** `ApplyExperienceMultipliers` and
  `GetSoftLevelCapExpValue` for 6 getter variants (plain, traded, Lucky Egg, past evolution level, four hearts,
  all together) x Exp. Charm in the bag x 5 foes (Lv. 1 to 100) x faced/shared: **120 of 120 equal**. Mutation
  check: changing the Lucky Egg multiplier in `MultiplayerCoop_ExpReward` from 150 to 140 makes it fail (100 of
  120), then restored. `--selftest-coop-exp`: **26 checks, 0 failed** (24 before). Limit: it replicates the
  first-stage arithmetic of `Cmd_getexp` (a state machine tied to battle controllers); it is not the whole
  state machine. The project's configuration is Gen 6 (`GEN_LATEST` is `GEN_6`), so the Gen 5/7+ "scaled EXP"
  branch is compiled out and not exercised.
* **Reviewed, no defect:** PvP awards nothing (link battles refuse EXP in `BattleTypeAllowsExp`; the self-test also
  checks that a non-co-op result records and awards nothing); the award is consumed once (`pending` cleared before
  `ApplyCoopExp`), and ending the same battle again finds nothing; the teammate's party is never touched; Eggs,
  fainted and Lv. 100 Pokémon behave per the self-test.
* **Not a bug, by design (documented in the source):** the pending award lives only in memory, so a reset in the
  few seconds between the battle's end and the award script loses it and never doubles it. Persisting it needs a
  save-layout change, which affects every save and the ABI check. **Owner decision** (accept the loss window, or
  approve a save field).
* **Rematch/farming (owner decision, not changed):** a Leader's co-op battle can be offered only by a player who has
  not beaten that Leader (`HasTrainerBeenFought`), and a win flags the Leader for the players' own games. So EXP is
  repeatable (a) by losing again and again after knocking out foes (a loss still awards the knocked-out foes), and
  (b) in a 3-4 player group, while someone who has not beaten that Leader still asks a helper who has (the helper
  keeps EXP and prize money). Like wild battles, this is bounded farming, not a duplicate award.
* **Cosmetic report from the diagnosis not changed:** the Exp. Share key item says "turned off" while the share is
  permanent (`item_use.c`). The item exists only in the FRLG maps that Emerald never loads, so a player cannot reach
  it; no change.
* **Not covered anywhere:** co-op NPC and Frontier rewards do not exist (rules are P5 owner decisions); a kill
  between result and award on a real game was not run; all eight Gyms' scripted awards on a real game were not run.

## P4 — Stability and polish

Engine commits on `claude/dev-stability-engine`: `2f8b35ef` (clock), `e1594d51` (M27).

* **D2, the midnight-dependent clock self-test: fixed.** Reproduced first (`TZ` giving 23:51 local: 3 of 58 failed,
  exactly as the diagnosis said). The test now pins its start to noon of the player's day. 58/58 in six time zones;
  `make check-clock` runs four zones six hours apart, so one is always near midnight.
* **Sanitizers.** UBSan build (`SANITIZE=1`) of the current source: the 11 self-tests that finish (battle-names, clock,
  coop-controller, coop-exp incl. the new parity check, cry-stop, line-break, mp-objects, party-order, shake-anim,
  spawn-claims, wild-weather) **0 reports**. `--selftest-decompress` under UBSan again hit the time limit (1500 s this
  time, exit 124): slowness, not a finding, as before. **First AddressSanitizer run** (`SANITIZE=address`): the same 11
  self-tests, **0 errors**. Limit unchanged: no existing headless driver plays trainer battles or move animations, so
  those paths (where N37-N40 were found) are still covered only by playing. Extending that needs a scripted battle
  driver in the engine (new tooling), not a flag; not started.
* **M27: done as PC-only wording** ("START menu: PLAYER, then STYLE"). The GBA text is unchanged; `#line` markers keep
  line numbers; the GBA ROM `pokedev.gba` was rebuilt after this and the keybinds work and is still sha256
  `f214735b...3387`.
* **GEN_6 test failures (review done):** `make check` re-run (6000 tests, 5498 passed, **39 failed**, 15 assumption skips; the same
  39 as before). **No genuine bug found**: each follows from the Gen 6 profile (details and the "known" vs "title only"
  basis per group in `docs/gba-test-failures.md`); whether each Gen 6 result equals the real Gen 6 games is not verified for
  the "title only" groups. New: a checked-in expected list (`docs/gba-test-expected-failures.txt`) and
  `scripts/diagnostics/check_gba_test_failures.py` that fails on any failure outside it (test: `tests/test_gba_test_failures.py`).

## K — Customizable keybinds (built from scratch)

Inspection first: the keys were fixed `#define`s in the engine's `sdl2.c`; no settings page, no file lines, no
rebinding. Gamepad code exists (Windows XInput, Android) and was left alone. Everything is in `docs/keybinds.md`.

* Engine commit `962b9fa3` (+ cleanup): pure module `keybinds.[ch]`, `key.*` lines in the settings file (only changed
  bindings written), conflicts with swap, F1-F12/Esc reserved, damaged files stay playable, Ctrl+R/Ctrl+P chords kept,
  F10 **Controls** page in the 3D game, prompts show the bound keys.
* App commit `02726d1`: launcher Help > **Game keys** tab, `game_controls.py`.
* **Evidence:** engine `test_keybinds` 24,154 checks (incl. 2,000 randomly damaged files), Controls-page model tests
  (308 checks in that binary), `--selftest-keybinds` 21 checks through the real event loop, `check-native` and
  `check-abi` pass, `check-diorama` passes, the GBA ROM is byte-identical; app `test_game_controls.py` (18 tests) and
  a launcher GUI test; **full app suite 1506 passed, 118 skipped** (2026-10-15).
* **Not verified:** a real keyboard on a real PC, any Windows run (the Windows executables are built by CI; this branch
  has not been through it yet), the on-screen look of the Controls page (drawn by the renderer; no screenshot taken).

## P5 — Incomplete features

No new mechanic was built (the brief says finish partials, do not invent). Done: `FEATURE_STATUS.md` brought up to
date (customization row was stale; rebinding row added), and every open design question gathered into
`docs/owner-decisions.md` with a recommendation. The audit itself is unchanged from the diagnosis (section 5):
Secret Bases, expanded PokéNav, co-op Frontier and breeding are missing and each needs rules from the owner first;
legendary events are partial (G3 and the dynamics); character customization is partial; followers and shared spawns
are implemented. Small partial, left open on purpose: G1 (post-Gen-6 move in an evolution trade) is rare in a Gen 6
game and is listed as an owner decision rather than changed.

---

# Opus session (2026-10-15): Windows build, M25 finish, journals, validation

## O1 — The Windows build

* Run 38669384604 (`claude/dev-m25-stability` + `claude/dev-stability-engine`) could not answer the owner's
  questions by construction: those branches do **not** contain the graphics-mode work (no Classic 2D build, no
  fallback check). So the two lines of work were merged on new integration branches (above); conflicts were
  small (a `.PHONY` list, two independent helpers in `sdl2.c`, two independent methods in `launcher_gui.py`).
  Engine `check-native`, `check-keybinds`, `check-clock`, `check-graphics-mode`; app launcher/graphics/controls
  tests: pass.
* The first full integration run, **38670082036, failed**: `keybinds.c` included `<SDL_keycode.h>`, which exists
  only on the Linux include path. The keybinds work from the Sonnet session had never been built for Windows. Fixed
  as `<SDL2/SDL_keycode.h>` (engine `cab2fd41` on integration, cherry-picked to dev-stability as `bf2887f7`);
  both Windows executables (2D and 3D) were then built locally with the pinned SDL2 MinGW before re-running CI.
  Run 38669384604 has the same defect and is superseded.

## O2 — M25: the two reverted levers, root causes, safe versions (app `e843ae4`)

**Why the KEEP throttle broke recovery (root cause).** Recovery does not restore a snapshot: `RouteReplay` re-runs
the same `_NativeRoute` code against the journal and requires every command to equal the recorded one
(`battle_replay_mismatch`). A KEEP throttled by wall-clock time is not a function of the journal, so the fast
replay issued a different command stream from the live run. **Safe version:** a slot gets KEEP when its last
QUERY reported fewer than 480 of the 600 watchdog frames (QUERY never refreshes the watchdog; every accepted
mutating command does, per the engine's `multiplayer_battle.c`), or after 32 steps without one (keeps the desk's
180 s host deadline fresh during long transfers). Both inputs are journaled responses and step counts. Because an
interrupted battle from the old router must still replay with the old policy, the route journal format is now
`...-v2`; a v1 journal replays with a KEEP on every step. Proven necessary: replaying a v1 journal with the new
policy makes recovery fail (mutation run).

**Why the lease-only `_get` broke recovery (root cause).** The recovery `ReplayDesk` overrides `_auth` to check the
battle's *logical original* actor; a shortcut that bypassed `_auth` made replay consult the store's current lease
for retired leases. **Safe version:** `_auth_lease` keeps the field checks, the store lease check
(`_require_lease`: boot epoch and released leases), the binding check and the connected-lease check, but does not
read and hash the save payload; `ReplayDesk` overrides it with its own semantics. A test asserts it refuses exactly
what `_auth` refuses (stale, released, other boot, other player, malformed) and that `_get` no longer reads payloads.

**Measured** (synthetic relay, same machine, medians of 3; start-of-session baseline in brackets):

| Case | Before (both reverted) | After |
| --- | --- | --- |
| 2p start-up, instant core | 1.97 s, 96 commands | 1.10 s, 76 (−44 %) |
| 2p start-up, 16 ms/command | 3.33 s | 2.37 s (−29 %) |
| 4p start-up, 16 ms/command | 6.81 s, 264 commands | 4.89 s, 224 (−28 %) |
| 2p, players choosing for 60 steps | 7.0 s, 336 commands, 140 KEEP | 4.75 s, 220, 24 KEEP (−32 %; journal −35 %) |

The synthetic core now models the watchdog (it expires when not refreshed), so these runs also prove the KEEP rule
keeps the cores alive. Battle/recovery group: 192 passed, 1 skipped; new tests: interrupt at a deadline KEEP and
recover; a v1 journal recovers with the old policy; lease-check equivalence.

## O3 — Oversized battle journals (app `7dd528a`)

**Measured first, with production polling (50 ms):** for a 6,206-event, 3.7 MB four-player journal, load 0.6 s (in
a worker thread since an earlier session), **router replay 2.45 s**, event-loop stall ~150-190 ms, not growing with
size. Replay, not load, was the larger cost. Cause: the router's 1 ms sleep per step (for live cores) also ran for
every *historical* step. Now a replay only yields to the event loop: **2.45 → 1.15-1.25 s (−50 %)**, commands
unchanged; regression test asserts no replayed step waits.

**Event counts:** the deadline-based KEEP (O2) removes most KEEP command/response pairs from idle steps (−35 % events
in the 60-step waiting case). For the failed full-six run's journal (110k events, about 5.5k blocks), blocks
dominate, so the expected reduction there is smaller (estimate about −20 %, not measured on a real game).

**Snapshots/compaction: not implemented, on evidence.** Recovery's correctness argument is that the same router code
re-derives every command from authenticated history; a snapshot would have to serialize the router, the desk's
receipts and the controller validator exactly and be proven equivalent, a new protocol surface. The measurements
show it is not needed to avoid timeouts: load runs off the event loop, replay yields every step with flat stalls
far below the 5 s RPC deadline, and projected recovery of a 110k-event journal is about 5-7 s load (worker) plus
about 20 s replay (waiting clients keep getting answers). Open risk, documented: the journal's hard bound
(500k events / 256 MB) would end a battle about four times longer than the full-six run.

## O4 — Multiplayer validation (simulated, not network)

Everything below is **simulated**: real host, server and client code over real loopback TCP with synthetic native
cores (app), or the engine's own battle code in its test ROM / self-tests. **No real game on a real network was run.**

| Area | Evidence (this session) |
| --- | --- |
| 2-player co-op and PvP battles, four-player 2v2 (start-up, relay, release) | app battle/recovery group and full app suite **1550 passed, 118 skipped** |
| 2v2 turn sync, targeting, controller ownership, switch order, completion barriers | engine GBA test ROM `make check TESTS="Multiplayer"`: **133 of 133** |
| Disconnect / host restart / reconnect recovery, incl. four cores interrupted at a deadline KEEP during idle steps, an uncertain RELEASE, a v1 journal from the old router | `test_battle_recovery.py` (new and existing) pass |
| Co-op EXP once per defeated Pokémon, never in PvP, parity with the battle's EXP path | `--selftest-coop-exp` 26/26, `--selftest-coop-controller` 14/14 |
| Save integrity after recovery | recovery tests check canonical revision, freed reservations and SQLite integrity |

Not covered: a real network, real Windows PCs, a full-six interrupted battle on real cores (needs the owner's parties).

## O5 — Integration and delivery: Windows package built and checked

GitHub Actions run **38672941750** (workflow `windows-package`, full mode), app `claude/dev-integration` at `7dd528a`
(everything after it is ledger text), engine `claude/dev-integration-engine` at `cab2fd41`. Both jobs succeeded.

* Built: GBA ROM (sha256 `f214735b…3387`, unchanged), Windows **3D game** `pokeemerald-mp-diorama.exe`
  (`505ec4d6…206f`) and **Classic 2D game** `pokeemerald-mp.exe` (`b56bb71f…020f`); both verified in the package as the
  engine job's own builds.
* Launcher package built, contents and game files verified, frozen launcher stayed up 20 s.
* Graphics fallback on the real packaged games: **16 of 16** (the VM's GDI OpenGL 1.1 cannot run 3D: definite answer,
  the player is asked, Classic 2D starts and runs 20 s, a failed 3D start exits 78 with an explanation and writes
  no save, the preference is not forced to 2D, 2D keeps the 3D settings lines).
* Private artifact **EmeraldTogether-windows-full** (ID 11945612108, 63 MB, 7 days):
  https://github.com/kashkevin/personal-pokemon-game-emgba3d/actions/runs/38672941750/artifacts/11945612108
* Contains: graphics-mode switching, keybinds, M25 relay and recovery changes, EXP/clock/M27 work.
* Not in it: the sprite pack, the import of the owner's own game (no base dump in CI). Not shown: a real GPU, real
  input on a real PC, real network play.

# Update 2-7 queue (autonomous, started 2026-10-15)

Branches: app `claude/dev-update2-7` (from `claude/dev-integration` 7714054), engine `claude/dev-update2-7-engine`
(from `claude/dev-integration-engine` cab2fd41). Real-PC testing is postponed by the owner; every "tested" below is
**simulated** (engine self-tests, unit tests, real host + companion + scripted bridges over loopback) unless it says
otherwise. The GBA ROM must stay `f214735b…3387`.

## Update 2 — Secret Bases and PokéNav

**Audit.** Upstream single-player secret bases work in the native game (24 locations; `secretBases[0]` own, `[1..19]`
visitors; record mixing needs a link cable). Nothing multiplayer existed (expansion-checklist rows 6-7 "NOT STARTED").
Specs: those two one-line rows only; owner decision 7 asks for rules, so the defaults below are mine, flagged.

**Design (reuses the game's own base code; no new GBA UI, no save-layout change).**
* Engine (native PC only): `MultiplayerSecretBase_GetOwn/Receive` in `secret_base.c` (the only places a record crosses
  the save boundary; Receive applies the original's `TrySaveFriendsSecretBase` rules, keeps the player's registry
  decision, never replaces the player's own base, handles a withdrawal record and refuses malformed ones).
  `multiplayer_extras.[ch]` = EMX1 mailbox (384 bytes), bridge frames `e` (capability), `x` (own base), `y` (inbound).
  `multiplayer_extras.c` is excluded from the GBA build like `multiplayer_spawns.c`.
* App: `extras_mailbox.py` (codec/validation/tombstone), `secret_bases.py` (host book in the world SQLite file:
  durable, per-owner visibility everyone/team/nobody, withdrawal records), world message gains optional `extras`
  (`bases` for this player + `nav` PokéNav view), requests `base_publish/base_visibility/base_get`, companion publishes the
  game's base (retries until the host answers; re-sends in a new host session) and offers the host's list to the
  game a few times (the game applies idempotently), Players menu "World and my base" (PokéNav-style pages: players'
  places + weather, running outbreak, World Event, My Secret Base visibility).
* Phase 7 scope delivered: positions, weather by route (per player), outbreaks, event locations as host-driven pages.
  Not delivered (needs new GBA/PC UI art, escalation-level work): graphical full map and habitat lists.

**Evidence.** Engine `--selftest-secret-base` **24/24**; `check-native` (bridge test **4293 checks, 0 failures**),
`check-abi` (172 types), `check-spawn-claims` 23/23, `check-mp-objects` 21/21, `check-keybinds` 21/21,
`check-coop-exp` 26/26; GBA ROM rebuilt = `f214735b…3387` (first attempt differed because the empty
`multiplayer_extras.c` object was linked; excluded, then identical). App: `tests/test_secret_bases.py` **26 passed**
(codec, host book incl. persistence/old-file upgrade, protocol, PokéNav view, menu pages, real host + two companions with
scripted bridges: base reaches the other game, follows redecorating, withdrawal on nobody/removal, ack, invalid base
refused, publication retried, mailbox off when the host goes away).

**Known limits (documented, not hidden).** Never observed in a running game on two PCs. A visitor's base whose
location equals the player's own is not shown (original rule: own base wins). A base hidden or removed while a
visitor's companion was offline stays in that visitor's save until the owner changes it again. Owner-base
decoration edits reach others when the record next changes (the game republishes on any change). No NPC base
teams (checklist said "NPC teams"): not built, the owner's party is the base's trainer as in the original.

## Update 3 — Battle Frontier modes and breeding

**Audit (what exists).** No Battle Frontier multiplayer code exists besides the host's four-player **Championship**
(`championship.py`, durable single-elimination bracket over native 1v1 battles; strongly tested in
`test_championship_recovery*.py`, never played by humans), 1v1 / 2v2 team battles with wagers, co-op Gym battles, win/loss
records and streaks on the Trainer Card. The vanilla Frontier facilities are unchanged (FEATURE_STATUS: "vanilla Battle
Frontier only"). Frontier EXP stays excluded by the base game (owner decision 6 open).

**Built.** `frontier_rules.py` — Frontier-style *entry rules* for Championships, **off unless the host creates
`<world>.frontier.json`**: rotating (one rule per world day) or fixed Open / Species Clause / Item Clause / Level 50 /
Level 30 / No Legendaries, checked against each player's last saved party (eggs ignored) at proposal and at consent;
a refusal names the player and the reason in the Championship page ("Bob: Over level 50"); the PokéNav World page shows
today's rule. No battle mechanic changes (Gen 6 rules untouched). Tests `tests/test_frontier_rules.py` (11).

**Not built, with the reason (needs a decision or deeper work).**
* *Co-op survival* (a team facing a streak of trainers): would reuse the co-op Gym battle (mode 4), but that battle is
  started by a Gym script in the game; a host-started trainer streak needs a native "start trainer battle" hook that
  can only be validated in a running two-PC game. Recorded for escalation, not attempted blind.
* *Level scaling* (Frontier Level 50 = scale up/down): the rules only admit or refuse; scaling needs engine battle code.
* *Rewards / Battle Points / streak records for Championships*: new currency and record fields = owner decisions.

**Breeding and eggs (audit + evidence, no code change needed).** The Day Care is the expansion's, under
`GEN_LATEST = GEN_6`: egg cycle 257 steps, level-1 hatchlings, Destiny Knot / power items, Ball and ability inheritance as
Gen 6. Upstream's daycare tests run on the GBA test ROM here: `(Daycare)` 12/12, `GetChildNature` 11/11, `InheritIVs`
5/5, `InheritPokeball` 7/7, `InheritAbility` 3/3. New engine test `test/egg_hatch.c` (4 tests, all pass): 257 steps per
cycle, which egg is due, no hatching without eggs, Flame Body/Magma Armor take two cycles. Multiplayer: eggs are
refused in trades (`trade_eligibility.py`), ignored by Frontier rules, and a saved party with eggs is a valid
checkpoint. Not built: a host-side Day Care/hatch-progress page (reading the last checkpoint would show stale numbers)
and a native Day Care UI (new screens); save compatibility is untouched.

## Update 4 — Legendary events and remaining gameplay

**Audit.** World Events already provide: legendary / mythical / mega-legendary / mega / rare categories (catalogue of 38 + 16 +
9 + 75 + 88), shiny rolls (1/64), host-scheduled spawns on 80 locations, announcements and reminders, first-catch-wins claims with
grace, durable restarts, catch ownership (consumed for everyone after the first reported catch), friendship credit for
shared events, Mega events (Mega form shown, base form stored, own stone held) and a 60,000 shop for 82 Mega Stones after the Mega
Ring. Not built before: weather / night / cooperative conditions. Static personal legendaries: 25 reset descriptors, no ticket
source (owner decision 11).

**Built: dormant legendary events (host only, no engine change).** `event_conditions.py` + `shared_world.py`: a legendary-class
event may start dormant (default 60%): two banners announce that something stirs near a place and when it wakes; the games are
shown nothing and a claim answers "gone"; the connected players' presence (time of day, reported weather, players on the
event's map) wakes it once, latched, with a 5-minute minimum; reminders are suppressed and expiry says only that the legend slipped
away; the PokéNav World page shows "Something stirs / Wakes in the rain" without naming the species; state survives host restarts.
Tests: `tests/test_event_conditions.py` (11) plus the existing `test_shared_world.py` (chance pinned to 0 there), mutation-checked.

**Engine evidence for Mega / multi battles.** `make check TESTS="Mega"`: 19 of 20 pass; the one failure
(`mega_sol.c:149`, Snow Defense boost, a Gen 9 rule) is in the checked-in expected-failure list. New
`test/battle/form_change/mega_evolution_multi.c` (2 tests, pass): in a link multi battle both trainers of one side can Mega
Evolve in the same turn and an opposing trainer can too (the 2v2 "one Mega per trainer" case that FEATURE_STATUS said was untested).

**Audited, unchanged (see FEATURE_STATUS for each):** followers (tested natively in the cloud in Phase 5), trading (G1 owner
decision 10 open), customization (roster + palette editor; scope is owner decision 12), shared world / spawns / outbreaks (tested),
battle modes (1v1, 2v2, co-op Gym; **1v1v1v1 not built**: needs a battle-engine mode that does not exist), animation/UI
integration (native UI pages for Players and Controls). Multiplayer Pokémon League and "expanded endgame systems" have no
specification beyond their names; not started.

## Update 5 — Integration and regression pass

Everything from Updates 2-4 sits on `claude/dev-update2-7` (app) and `claude/dev-update2-7-engine` (engine), both made from the
Update 1 integration heads, nothing rebased or rewritten.

**Compatibility, by evidence:**
* *Update 1 fixes (M25 relay, deadline KEEP, journal v2, recovery):* app suite 1598 passed / 0 failed includes the battle recovery,
  throughput and journal tests; no file of those systems was changed (only `shared_world`, `server` world broadcast,
  `companion` bridge handling, `player_menu`, `championship` (an optional hook), `bridge_protocol` (one more replaceable snapshot)).
* *3D / Classic 2D switching:* `check-graphics-mode` all PASS; both Windows executables and both Linux binaries build.
* *Keybinds:* `check-keybinds` 21, `test_keybinds` 176, launcher Game keys tests pass.
* *EXP Share / co-op rewards:* `check-coop-exp` 26, `check-coop-controller` 14.
* *Existing saves:* no save structure changed (`check-abi` 172 types identical on GBA and PC; Secret Bases use the original `secretBases[20]`
  array and its original rules; no new save fields). The GBA ROM is byte-identical `f214735b…3387`.
* *Multiplayer recovery:* battle recovery tests above; a new reconnect test (a reconnected companion gives a new host session its secret base again).
* *Windows launcher:* built by the CI job in Update 7 (below); locally the frozen-launcher tests pass.

**Regressions found and fixed during the pass (all caused by this queue's own changes, none in earlier work):**
1. Adding `multiplayer_extras.c` linked an empty object into the GBA ROM and changed its hash; excluded from the GBA build like
   `multiplayer_spawns.c` (hash identical again).
2. The world-message tests pinned the exact key set; the optional `extras` field is added to them (`test_world_server`,
   `test_checkpoint_server`).
3. A menu row was longer than 25 characters ("Visible to: My teammate only"); shortened (found by the new menu test).
4. Applying a visitor's base while the player was inside a base or a menu could move a slot the game had cached: the game now
   applies only in the calm overworld outside secret bases, and the companion re-offers the host's list every 15 s.
5. A test race in the new reconnect test (the ack arrives after the host stored the base): the test now waits for it.

Environment note: 7 Tk GUI tests error with "no $DISPLAY" without a display; with `xvfb-run` the whole suite passes.
Correction: the six-issue diagnosis said "no gamepad on PC"; Windows reads an XInput pad (see its D3 correction).

## Update 6 — Automated validation and the manual checklist

See `docs/automated-validation-matrix.md` (what each area is covered by, and what none of it proves) and
`docs/windows-test-update2-7.md` (the manual Windows checklist). New automated coverage in this update: `test_gamepad`
(28,216 checks on the controller mapping, which had none), the secret-base mailbox deferral self-test (29 checks), the reconnect and
pacing tests, `(EggHatch)` and Mega multi-battle GBA tests. Full runs: app 1598 passed, 0 failed; GBA ROM suite 5504 passed,
39 expected failures, 0 new. **No hardware claim is made anywhere.**

## Update 7 — Optimization, bios.c review, private Windows build (O6)

**Optimization:** none was justified. The remaining performance items are GPU-bound and unmeasurable without a graphics card
(V3, V25, V30, V39) or were done in Update 1 (M25). Cost of this queue's new host code measured: `extras_inbound()+pack()` 8.5 µs
per publish with six bases; the engine's per-frame work is one 160-byte copy and compare. No code was changed for speed.

**bios.c:** reviewed, not resolved, not changed: `docs/bios-licensing-review.md`. Every artifact is private; nothing was published.

**Final runs (before the build):** app suite under xvfb **1605 passed, 118 skipped, 0 failed**; engine native checks all pass on the
Linux 2D and 3D binaries; both Windows executables cross-compile; GBA test ROM 5504 passed, 39 expected failures, 0 new; GBA ROM
sha256 `f214735b…3387` unchanged.

**Windows build:** GitHub Actions run **38684352610** (workflow `windows-package`, full mode, `expected_rom_sha256` = `f214735b…3387`,
so the job would have failed on any change), app `claude/dev-update2-7` at `90f21544d2`, engine `claude/dev-update2-7-engine` at
`a18e2e96b1`. Both jobs succeeded: GBA ROM, Windows 3D game and Classic 2D game built; launcher built, package audited, game files
verified, frozen launcher stayed up, graphics-mode check on the packaged games passed.
* Private artifact **EmeraldTogether-windows-full** (ID 11949872388, 63 MB, expires 2026-10-22):
  https://github.com/kashkevin/personal-pokemon-game-emgba3d/actions/runs/38684352610/artifacts/11949872388
* Not in it: the sprite pack, the owner's own game (imported on the player's PC), any save.
* Not shown: any real PC, GPU, audio, controller or network. Test list: `docs/windows-test-update2-7.md`.


# Update 8-14 queue (autonomous, started 2026-10-15)

Branches: app `claude/dev-update8-14` (from `claude/dev-update2-7` 053be90), engine `claude/dev-update8-14-engine`
(from `claude/dev-update2-7-engine` a18e2e96). Same rules as before: every "tested" is simulated unless it says otherwise; the
GBA ROM must stay `f214735b…3387`.

## Update 8 — Cooperative Battle Frontier

Design and rules: `docs/battle-frontier.md`. Built on the existing native co-op battle instead of a new battle mode.
* **Engine (PC only, GBA ROM identical):** `multiplayer_ladder.[ch]`. The 32-bit code of a co-op battle names two opposing
  trainers, a level and whether experience is awarded (a Gym is still 1..8). The opposing parties are cut to three each and
  scaled exactly; the result script shows the outcome. `--selftest-ladder` **18/18**: all 862 trainers build a party and
  scale to the level with full HP; codes round-trip; bad codes are refused; Gym codes keep their meaning. Hooks in shared
  files are PORTABLE-wrapped with `#line` markers (`multiplayer_coop.c`, `multiplayer_battle.c`).
* **App:** `coop_code.py` (code, validators widened in `native_battle`, `battle_desk`, `battle_protocol`), `frontier.py` (ladder,
  levels, prizes, durable book), `frontier_service.py` (team/party rules, issue, reconcile, payment), `Wagers.grant`,
  `BattleDesk.on_publish` (durable co-op outcome before closure), world request `frontier`, companion `frontier_rpc`, Players
  menu pages, optional `party_limit` in `<world>.frontier.json`.
* **Evidence:** `test_frontier.py` 31 (rules, book incl. restart, service against the real desk and real saved parties, menu,
  protocol path; mutation-checked: removing settle idempotence or grant idempotence fails 4 tests), `test_coop_battle.py` +2
  (ladder code reaches the game; a failed publication keeps the battle open for the exact retry).
* **Not built:** choosing a subset of a larger party inside the battle (native protocol change; Opus-level), items/BP prizes
  (no delivery channel). See `docs/battle-frontier.md`.

## Update 9 — Four-player free-for-all (1v1v1v1): not implemented, documented

Audit of the engine (`docs/free-for-all-feasibility.md`): `NUM_BATTLE_SIDES = 2`, a battler's side is its position's parity;
237 `GetBattlerSide`, 143 `B_SIDE_*`, 234 per-side state (`gSideStatuses/gSideTimers`), 82 ally/opponent predicates; binary
`B_OUTCOME_*`; two-column controllers/UI/3D stage; the native protocol, canonical rosters, journal and replay describe 1v1, 2v2 or
co-op only. Four independent trainers in one battle need four sides throughout: an architecture project (needs Opus-level design
and real multi-PC testing). Per the brief, no unstable approximation and no fake of four 1v1 matches was built; work continued.

## Update 10 — Cooperative Pokémon League

`docs/pokemon-league.md`. Built on the Frontier ladder machinery with `mode='league'`: three co-op rounds (Sidney & Phoebe, Glacia &
Drake, Wallace & Steven) at the trainers' own levels (battle code level 0; engine `--selftest-ladder` now **20/20**, adds level 0
and the host's reading of the save layout: flags 0x1270, badges 0x867-0x86E), 8 badges for both players, per-player durable
records (`league_records`), prizes with a first-clear bonus once per player, experience only while someone is a first-timer, Hall
of Fame (`hall_of_fame`, entered once, recovered after a crash), world-file upgrade for runs from before the League, menu pages
(Frontier and League hub, League, Hall of Fame). Evidence: `test_frontier.py` **43** (League book 6, badges 1, service 3 incl. three real
desk battles to a clear, menu 2). Not touched: the story, the Elite Four rooms, anyone's save flags. Endgame audit: no further
specification exists; nothing invented.

## Update 11 — Legendary catch ownership

`docs/legendary-catch-resolution.md`. Rule: the first valid reported catch wins, in host arrival order; valid = the sender claimed
that event (claimants persisted with the event). Durable ledger `event_resolutions` (winner, sequence, species, level, shiny, mega,
held item, claimants) written before the event closes, `event_reports` audit trail, replay-safe (winner's replays "consumed", others
"gone"), restart-safe (a decided event is closed on restart), loser notified, dormant events untouchable, existing probabilities and
dormant behaviour unchanged. Evidence: `test_event_catch.py` 11; `test_shared_world.py` late-catch test rewritten to the new rule
(the old rule's refusal is the behaviour that was replaced); app suites for shared world/events/server pass.

## Update 12 — Secret Bases and PokéNav completion

`docs/secret-bases-and-pokenav.md`. Engine: the own base's party is refreshed (`SetPlayerSecretBaseParty`) in the calm overworld so
published bases carry the owner's real team as NPC defenders; `--selftest-secret-base` **36/36** (7 new). Host/app: PokéNav "This
area's wild Pokemon" page backed by `SharedWorld.habitat_view` (real `spawn_director` tables; unknown areas say so), nav now carries host
time/time-of-day and the Frontier entry rule, new world request `habitat_get`. Evidence: `test_secret_bases.py` (+3 incl. real-table
habitat view, protocol, menu). Graphical Town Map markers: **not built** (see doc). Visibility default Everyone with Teammate/Nobody was
already in place and is unchanged. GBA ROM untouched (PC-only files).
