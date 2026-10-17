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

## Update 13 — Remaining feature audit

Audit of `FEATURE_STATUS.md`, code (`TODO/FIXME/placeholder/NotImplemented` scan of app and engine PC code: none outside
legitimate text-placeholder machinery) and the Gen 6 profile. Completed: (1) **Gen 6 fidelity**: PC build sets `B_RUN_TRAINER_BATTLE`
(running from trainer battles, a Gen 9 rule — would also have offered "Run" in co-op ladder/Gym battles) and `B_THUNDERSTORM_TERRAIN`
(Gen 8) to FALSE under `PORTABLE`; the GBA build is untouched, so its ROM hash is unchanged. (2) `appearance.py` colour names corrected to
the ROM editor's tables, with a test. Everything else partial is a documented owner decision or needs real play: static-legendary
ticket path, subset-party selection and item/BP prizes (new engine channels), per-form Mega ledger and unofficial Mega adaptations,
free-form character creation, graphical PokéNav markers, eggs/mail in trades (kept refused), 1v1v1v1. No feature was relabelled
"complete" without a run; native/hardware verification items stay in `FEATURE_STATUS.md`.

## Update 14 — Integration and release candidate (O7)

* **Private Windows build:** GitHub Actions run **38692719289** (`windows-package`, mode full, ref `claude/dev-update8-14` at app
  `7f3ca84035`, engine `claude/dev-update8-14-engine` at `c56e76a668`, ROM sha256 pinned to `f214735b…3387`): success. Engine job built the
  GBA ROM, the Windows 3D game and the Classic 2D game (the ROM hash check passed); the Windows job built the launcher, audited the
  package, started the frozen launcher and ran the graphics-mode check on the packaged games. Artifact `EmeraldTogether-windows-full`
  (ID 11953413779, sha256 `c0844963…700a0d`, 63 MB, expires 2026-10-22). Private to the repository; **bios.c licensing is unresolved: not
  cleared for distribution.**
* **Cloud evidence:** app suite 1662 passed, 0 failed (121 skipped; the 24 launcher-GUI tests need Python 3.12 with tkinter, run
  separately: 85 passed); engine `check-native` all suites 0 failures; `--selftest-secret-base` 36, `--selftest-ladder` 20; GBA ROM rebuilt
  after the Gen 6 switch change: sha256 unchanged. The GBA test-ROM suite was **not rerun**: the only shared-source change is a
  `#ifdef PORTABLE` in `include/config/battle.h`, so the GBA/test-ROM code is identical (previous result: 5504 pass, 39 = expected list).
* **Not verified on hardware:** everything in `docs/windows-test-update8-14.md` and `docs/windows-test-update2-7.md`.

## Update 15 — True four-player free-for-all (1v1v1v1)

Branches `claude/dev-update15-20` (app) and `claude/dev-update15-20-engine` (engine). **Design (`docs/free-for-all.md`):** not four 1v1s, not
a renamed 2v2, not a simulator: the engine's own battle code with a fourth *side model*. `GetBattlerSide()` answers the rules side (the
battler itself in a free-for-all), `GetBattlerPositionSide()` the screen column; `NUM_BATTLE_LOGIC_SIDES` = 4 for the side arrays;
`IsPartnerAlive`/`GetPartnerBattler` know nobody has an ally; targets, spread counts, Intimidate/Download/Trace, screens, hazards, Court
Change, Helping Hand/Ally Switch/Follow Me, Symbiosis/Friend Guard, the win check (`battle_ffa.c`: eliminated = party fainted, last
trainer wins, simultaneous = draw) and the winner byte in the end-of-battle controller block are free-for-all aware; everything is
behind `MP_FFA_ENABLED` (PC build and test ROM only). Native phase 5 (`MP_BATTLE_PHASE_FFA`) reuses the four-core full-Multi
infrastructure; the result is the winner's slot + 1 or 5 (draw), identical on every core, each core checking its own local result against it.
Host: `BattleDesk.invite_ffa` (mode 5, own consent domain), protocol op, controller validator, binding/query outcome words, manifest
marker read from the **native exe** (the GBA ROM stays byte-identical), `ffa_results` durable book (idempotent), no wager, friendships,
in-game menu and launcher entries (offered only when the ROM advertises it).
**Evidence:** GBA test ROM 25 new FFA tests + native four-core startup test; full suite 6031 tests, 5529 pass, 39 failed = the 39 expected, 0
new; PC selftests (coop-controller 22, ladder 20, secret-base 36, check-native); app tests listed in the validation matrix. **Release GBA ROM
sha256 f214735b…3387 unchanged** — this needed work: inline helpers as macros in the GBA form, `battle_ffa.c` kept out of the release link
(an empty object reordered the linker's veneers), `#line` markers; verified by relinking the baseline objects and by per-function
disassembly comparison. **A regression found and fixed on the way:** `BattleSideHasTwoTrainers` returned FALSE for a free-for-all
which broke the party-index setup in the 25 tests (they had passed before the native-phase commit).
**Not verified:** four real PCs, the screen layout (doubles layout reused, third foe in the partner slot), a real disconnect mid-battle.
The 3 `2v1`/two-opponent test failures also fail on the Update 14 head (they are among the 39 listed Gen 6 failures).

## Update 16 — Complete Battle Frontier

`docs/battle-frontier.md`. **Team selection from a larger party:** the host stores each player's selection (`frontier_bring`), validates it against the
latest save and puts it in the battle: `invite_coop(brings=)`, the consent fingerprint, `CanonicalBattler.bring/battle_party/adopting`, the durable
reservation (`brings`) and the replay desk, so a restart or a recovery replays the identical team. Native protocol change (documented, contained): the
co-op preparation carries `0x80 | slot mask` in the **last byte of its seed**; the game clears it before seeding (every core still seeds
identically), validates it (`BringSelectionValid`), saves the original party as before, reduces the live party to the chosen Pokemon in saved order
(`ApplyBringSelection`), compares the reduced party's CRC at start and restores the original six exactly at the end; co-op experience maps battle slots
back to saved slots. `MP_BRING_ENABLED` (PC build and test ROM only): release GBA ROM **f214735b…3387 unchanged** (checked after each engine change).
**Battle Points and items:** the wager wallet stream (numbered, exactly-once per save, receipts say what landed) carries reward words (`rewards.py`;
engine `MultiplayerWorld_ApplyRewardWord`): BP into the save's own `frontier.battlePoints` (cap 9999), items into the bag else the PC. BP per cleared
round, a first-clear item per Brain round, ledger and delivery states in `frontier_rewards`/`frontier_bp`, settled in the same transaction as the round
(exactly once), re-sent after a crash. **BP shop** (`frontier_purchases`): debit first, item only after the game reports the points taken, refunds for
partial points or a full bag, one open purchase per player. **Evidence:** engine GBA test ROM (co-op team-selection tests; targeted re-run 197 pass + 3
listed), `--selftest-rewards` 18, `--selftest-coop-exp` 32, `--selftest-ladder` 20, `check-native` 4305 bridge checks; app `test_frontier`, `test_rewards`,
`test_coop_battle`, menu tests. Changed behaviour: a party over the limit is no longer refused (it brings its first `party_limit`).
**Not verified:** a real round with a reduced party on a PC, BP/items landing in a real save, the new pages on screen. Pre-existing 3 two-opponent
test failures (Gen 6 list) are unchanged.

## Update 17 — Legendary catch consistency

`docs/legendary-catch-resolution.md`. **Engine:** a World Event catch is recorded in the save (five unused `VAR_MP_CATCH_*` variables: event, slot,
species, personality, trainer id) and re-reported to the host until a verdict arrives; the verdict (keep = kind 4, release = kind 5, payload = catch
number) comes through the existing numbered wallet stream, so it is delivered once and survives disconnects. Release finds the exact Pokémon by
species + personality + trainer id, never the last party member, never anything else; keep clears the record. **Host:** one `catch_verdict` per event in
`event_verdicts` (restart-safe), a retroactive winner when the second report arrives after the event expired, verdicts queued once per player and
receipted by `wallet_applied`. **Evidence (simulated):** engine `--selftest-catch-reconcile`, `--selftest-rewards`, `check-native` bridge checks; app
`test_event_catch`, `test_rewards`, `test_world_server` (contested catch over the wire: B keeps, A is told to release, repeated reports queue nothing
new, receipt recorded). **Not verified:** a real two-PC race, a real save losing the copy; a traded/evolved copy and saves without a record are left
alone by design. Save bytes are not rewritten directly; the engine uses its normal party/box functions while running.

## Update 18 — Graphical PokéNav map

`docs/graphical-pokenav-map.md`. The original Town Map (PokéNav, fly map, Pokémon Center wall map) now draws the other players (the game's own
Brendan/May icon with its accent colours swapped for a per-slot ramp, derived from the game's palette at run time), the visible World Event (the
original red Battle Frontier outline) and the mass outbreak (the original pink fly dot); SELECT jumps the cursor marker to marker; markers follow the
zoomed map and refresh every ~1.5 s. **No protocol change for players:** poses already reach the game; the outbreak's map is new (host `nav.outbreak.map`
→ companion `WorldInbound.outbreak` → the world mailbox's reserved bytes, ABI size unchanged, older engines ignore it). Engine code is PC-only
(`src/region_map.c`); release GBA ROM **f214735b…3387 unchanged**. Remote map ids are bounds-checked against a committed per-group map count table that
`tools/pc_port/map_group_counts.py --check` compares with the header. **How it was checked:** a new development aid (`PKMN_DEBUG_SCENE`, `PKMN_DEBUG_KEYS`,
`PKMN_DEBUG_SHOTS`, `include/platform/debug_scene.h`) opens a screen headlessly, presses scripted keys and writes PNGs, so the rendered screens could be
looked at (this is how the earlier "needs a visual-verification session" blocker was removed). While building it a harness bug was found and fixed (an
uncleared scanline-effect task killed the PokéNav's own task), not a game bug. **Not verified:** real Windows, 3D window, real players. **Missing art** is
listed exactly in the doc (event glyph, outbreak glyph, number badges, SELECT help-bar string, cave marker style).

## Update 19 — Final PC feature audit

`docs/final-pc-audit.md`. Re-ran everything that exists: app suite **1756 passed, 50 skipped, 0 failed**; engine `check-native` and 20 selftest targets all
0 failures; `abi_layout.py` 172 types OK; GBA test ROM full `make check` **5532 passed, 39 failed = the expected list, 0 new** (1389 s); release GBA ROM hash
unchanged. Both native builds (2D and 3D) booted headless from cold with scripted keys to Birch's introduction (new debug scene). **Defects confirmed and
fixed:** (1) `FEATURE_STATUS.md` still said the Windows .exe was not built; (2) a Town Map marker could be drawn in the wrong colours if every sprite palette bank
was taken (now skipped). No other defect was confirmed; owner-decision and cosmetic items stay in `KNOWN_ISSUES.md`. Every area still needs its real-PC pass.

## Update 20 — Final Windows integration

* **Run 38723716523** (`windows-package`, full, app `03a7326`, engine `998164d0`): **failed** in the engine job: the new `src/platform/debug_scene.c` included `<SDL.h>`
  (found on Linux, not on the Windows cross-compile, which has `SDL2/SDL.h`). Real defect, fixed in engine `676afe0c` (`#include <SDL2/SDL.h>`). Both Windows executables
  (2D and 3D) were then cross-compiled locally with the pinned SDL2 MinGW release to catch any second error before spending another CI run.
* **Run 38726808703** (`windows-package`, full, app `62bab63`, engine `676afe0c` on `claude/dev-update15-20-engine`, `expected_rom_sha256` = `f214735b…3387`): **success**. Engine job
  built the GBA ROM (hash check against the pinned value passed), the Windows 3D game and the Classic 2D game (about 17 min); the Windows job built the launcher with the
  pinned wheels, audited the package, verified the packaged game files, started the frozen launcher and ran the graphics-mode check on the real packaged games.
  Private artifact **EmeraldTogether-windows-full** (ID 11969537177, 63 MB, sha256 `fff7bbbf…e93610`, expires 2026-10-22):
  https://github.com/kashkevin/personal-pokemon-game-emgba3d/actions/runs/38726808703 . Private to the repository; **bios.c licensing unresolved: not cleared for distribution.**
  Existing-save compatibility: the GBA ROM is byte-identical and the save layout is untouched (the catch record uses five previously unused script variables; the
  host's new books are new tables; older saves without a record simply ignore catch verdicts). Not run on a real PC.

## Update 21 — Four-player battle visual polish

`docs/four-player-battle-ui.md`. Engine branch `claude/dev-update21-25-engine`. The free-for-all screen now draws the second player's Pokémon facing
you, names every Pokémon's trainer (2D: in the healthbox; 3D: a coloured name tag on each box and `NAME - OUT` for an eliminated trainer),
prefixes battle text ("BOB's Gardevoir used Swift!"), and the 3D target page shows FOE plates (nobody is an ally). Looked at through a new
headless four-player preview (`PKMN_DEBUG_SCENE=ffa`: real battle engine, computer trainers) in 2D and 3D: intro, menus, target selection,
moves, status, faints, elimination; the same four Pokémon as a 2v2 for a regression look (unchanged). Findings on the way (scene artefacts, not
game bugs): computer trainers Dynamaxed/Terastallized, disobedience at level 50; one real engine fix for the preview path (the opponent
controller waited on its own flags in a free-for-all). `tools/pc_port/ffa_visual_check.py` + `tests/visual/ffa_signatures.json` (numbers only) is the visual
regression check. Two FFA test expectations changed to the new text; **FFA test ROM subset 25 of 25**. Release ROM **f214735b…3387 unchanged**.
Not seen on a real monitor or over a real network.

## Update 22 — Visual and audio audit

`docs/visual-audio-audit.md`. New tools: field scene, `visual_audit.py` sweep, audio scene. **3D sweep: 29 of 29 maps drawn in 3D, none blank or crashed**; Low and
Medium quality presets looked at (closes V22); **confirmed limitation:** objects drawn from several sprite pieces (Littleroot's moving trucks, Cable Car, S.S. Tidal,
Seagallop, Rayquaza) make the 3D view fall back to 2D while on screen (owner decision). **Audio:** all 558 song numbers through the mixer: no crash, no clipping, no stuck
song (80 numbers are unused slots); **music peaked near -18 dBFS: make-up gain raised 2 → 4** (needs real ears). Simulation only.

## Update 23 — Reliability and save compatibility

`docs/save-compatibility.md`. Databases written by the Update 14 code (fixtures made by `tools/compat`, data only) open with the current code: the three checkpoint
store modules are byte-identical since Update 14; the shared world only gains tables; catches, resolutions and open claims survive; verdicts are exactly-once; 30 reopen cycles change
nothing; the committed fixtures are never modified (tests copy them first). `tests/test_save_compat.py` 6 tests. No duplicate-reward, wrong-owner, lost-progress or growth defect was
found; the existing suites for rewards, restarts, journals and recovery all pass. Not covered: old journals/saves from real runs.

## Update 24 — Balance, privacy, controls

`docs/pokenav-privacy.md`, `docs/balance-and-controls-review.md`. **PokeNav location privacy**: Players page toggle, default ON, per character; the host redacts a hidden player from every
other viewer (presence as map 255.255 without weather, PokeNav text "Location hidden", no Town Map marker, Players screens/Trainer Card say so); same-map viewers still see them;
failing closed on an unreadable setting file; 9 tests incl. four real connections. **Controls:** Xbox B did nothing → now Cancel (the engine's pad test oracle updated: 28,217
checks, 0 failures); rebinding self-test 30/30. **Balance:** documentation error about shop prices corrected; recommendations (not changes) listed separately.

## Update 25 — Final integration

Branches `claude/dev-update21-25` (app) and `claude/dev-update21-25-engine` (engine). Local: release ROM hash unchanged (f214735b…3387, rebuilt after every Update 21-24 engine change);
GBA test ROM full run **5532 passed, 39 failed = the expected list, 0 new** (6034 total, 9 expected-failing); PC selftests (22 targets) 0 failures; ABI parity 172 types; app suite
all passing (one timing test, `test_two_player_start_up_without_game_delay`, failed once at 4.97 s against 4.0 s while the GBA suite loaded all four cores, and passed on its own).

* **Run 38757166230** (`windows-package`, full, app `1446354`, engine `677821af` on `claude/dev-update21-25-engine`, `expected_rom_sha256` = `f214735b…3387`): **success** (engine job 24 min; Windows job: launcher package, content audit, packaged-game file check, frozen launcher start, graphics-mode check on the real packaged 3D and 2D games all green). Private artifact **EmeraldTogether-windows-full** (ID 11984854602, 63 MB, sha256 `dbe291b2…6fd1`, expires 2026-10-22): https://github.com/kashkevin/personal-pokemon-game-emgba3d/actions/runs/38757166230 . **bios.c licensing unresolved: not cleared for distribution.** Not run on a real PC.

## Update 26 — three bugs from the first real Windows test

`docs/update26-bug-fixes.md`. Engine `claude/dev-update26-fixes-engine`, app `claude/dev-update26-fixes`. **Bug 1** (old GBA UI over the 3D view at the end of a battle): the native battle
screen let go when the battle's data was freed while the engine was still in the battle callback during the end fade; it now stays up (`ui_battle.c`). **Bug 2** (crash leaving the
Pokemon menu, found with AddressSanitizer, not reproduced as a crash): the party-menu state read an action list one frame before it was built (uninitialised field-move index);
also a far-scenery colour read past a tileset and a stack-use-after-return in the weather-sprite test; `crash.log` now names the native screen. **Bug 3** (black first battle,
reproduced in 3D through Birch's bag): a completed fade-to-black counted as a steady field. **Bug 4** (battle UI over entrance animations): not reproduced, no code change; findings
in the doc. Regression tools: `battle_end_check.py` (wild, trainer; fails without the fix), `party_menu_check.py` (AddressSanitizer, 3D and 2D), `first_battle_check.py`
(`make -f Makefile_pc NATIVE_LINUX=1 DIORAMA=1 check-update26`). Local: GBA ROM hash unchanged, 22 PC selftest targets and `check-diorama` pass, save-compat and privacy tests pass.
Simulation only; not run on a real PC.

**Update 26 integrated.** Fast-forwarded into the default branches (no conflicts, no force-push): engine `claude/emeraldtogether-combined` = `903e63b8`, app `claude/emeraldtogether-combined-app` = `8849155`
(code identical to the verified fix branches). Run **38852544799** (`windows-package`, full, app `8849155`, engine pinned to `903e63b8`, `expected_rom_sha256` `f214735b…3387`): **success**; engine job 14 min,
Windows job: package content audit (190 archive members, 130 hashed files), packaged game files = the engine job's build (3D `pokeemerald-mp-diorama.exe` sha256 `50fdede8…653a`, Classic 2D `pokeemerald-mp.exe` sha256
`05441f21…e50f7`), frozen `EmeraldTogether.exe` stayed up 20 s, graphics-mode check 16/16 (the runner has no GPU, so 3D correctly reported unsupported and exited 78 with an explanation; Classic 2D ran). Private artifact
**EmeraldTogether-windows-full** (ID 12026995145, 63,187,822 bytes, zip sha256 `7c62de6e…79df`, expires 2026-10-23). No sprite pack, no game ROM in it (`HAVE_SPRITES false`, `HAVE_BASE false`: the player imports their own game).
An earlier attempt (run 38850387860) failed in 0 s because its version label contained parentheses (the launcher accepts letters, digits, space . _ - only); nothing else changed. **bios.c licensing unresolved: not cleared for distribution. Not run on a real PC.**

## Update 27 — Battle FX audit

`docs/battle-fx-audit-update27.md`, `docs/battle-fx-audit/matrix.md` (959 rows), `docs/windows-test-update27.md`. Engine `claude/dev-update27-battlefx-engine`, app `claude/dev-update27-battlefx`.
**Audit** (cloud simulation, software OpenGL, no GPU): 847 moves (621 HD by Battle FX, 226 the game's own animation in the 3D view; Z/Max moves not reachable), 81 battle animations: 959 of 959 animations
triggered and ended, 652 of 652 HD move rows and 76 of 76 HD battle animations exact against the core's replay, none failed/stuck/crashed, no effect left after its animation, memory flat over 170 animations; Classic 2D
45 of 46 sampled moves drew (Recover fails at full HP); fought battles (shiny, Mega Evolution, doubles) 50 of 50 exact. **Defect fixed:** a black block over the player's Pokemon behind about 36 move backgrounds
(`gba_easy_draw.c`: rows 112-160 of a move's background mirrored): 36 flagged before, 2 (dark by design) after; regression `tools/battlefx/bg_check.sh`. Not exercised: real GPU, FFA in the overworld, Z/Dynamax.
**Integrated** (fast-forward, no conflicts, no force-push): engine `claude/emeraldtogether-combined` = `1da670975e9ee3aa55790c7269f0295515e7a3ae`, app `claude/emeraldtogether-combined-app` = `afc382e` (+ this note).
Checks: GBA ROM hash unchanged (`f214735b…3387`); 22 PC selftest targets 0 failures; `check-diorama` pass; Update 26's `first_battle_check` and `battle_end_check` pass on the new build; app suite passes (the 24 GUI tests need
tkinter: pass under a Python that has it). **Run 38915559897** (`windows-package`, full, app `afc382e`, engine pinned `1da67097`, label "Update 27 app afc382e engine 1da67097"): success; packaged 3D `pokeemerald-mp-diorama.exe` sha256
`6172e11a…5725` and Classic 2D `pokeemerald-mp.exe` `7486101a…9df3` equal the engine job's build; launcher stayed up 20 s; graphics-mode check 16/16 (the runner has no GPU: 3D unsupported, as designed). Artifact
**EmeraldTogether-windows-full** ID 12052684712, 63,192,983 bytes, zip sha256 `5f25173b…f469`, expires 2026-10-23; no ROM, no sprite pack. The Update 26 artifact (12026995145) is untouched. bios.c licensing unresolved. Not run on a real PC.

## Update 28 — dialogue bug 5 and the unified main menu

`docs/update28-dialogue-and-menu.md`, screenshots in `docs/update28-screenshots/`. Engine `claude/dev-update28-engine`, app `claude/dev-update28`.
**Bug 5** (dialogue stays after A; two or three more presses): script, text printer and drawn text agree in every traced run (3D and Classic 2D); the cause measured is the input path:
the window loop gave the game the keys *held at the frame boundary*, so a tap that began and ended between two frames was lost. With real SDL key events pushed by a thread
(`PKMN_DEBUG_TAPS`, 60 taps) the 3D build lost 34 of 60 taps of 15 ms and 20 of 60 of 30 ms (Classic 6 and 1) on the software display; after the fix none in either. Fix:
`src/platform/key_queue.c` (every change queued in order, one step per game frame; Windows pad polled between frames); the 3D message box also starts the next page when the printer leaves
its wait at a `\p`. Dialogue text, speed and scripts unchanged; GBA ROM hash unchanged. Checks: `test_key_queue.c`, `--selftest-keybinds` (+6), `input_tap_check.py`, `dialogue_check.py`
(boy, rescue; 3D and 2D). **Feature 6:** one launcher window: Continue Adventure, My Worlds, Host Multiplayer, Join Friend, Settings, Exit Game; setup pages embedded
(`SetupWindow(container=)`), no pop-up; Back to the menu refused while a game runs; Continue uses `launcher-recent.json` (no credentials); worlds listed read-only; audio settings added;
Internet host asks first and says port forwarding is the host's job, no relay; join is by invitation file only (no invite codes, no discovery). No protocol/server/world/save change.
Local checks: GBA ROM `f214735b…3387`; 22 PC selftest targets, `check-diorama`, Update 26's `battle_end_check`, `first_battle_check` (now takes its pictures at game frames: it failed on a
fast 4-core run and passed on one core before that change), `party_menu_check`; MinGW objects of the changed files compile; app suite exit 0 (49 skipped: 48 need Lua 5.3+, 1 needs private
save paths; skips are not passes); Tk GUI tests under xvfb. Simulation only; nothing run on a real PC or network.

**Update 28 integrated.** Fast-forwarded into the default branches (no conflicts, no force-push): engine `claude/emeraldtogether-combined` = `5aaf2ba2e082995022bf0db3d3b43e1c2ec5ef1b`, app `claude/emeraldtogether-combined-app` = `544c889` (+ this note).
Run **38945766332** (`windows-package`, full, app `544c889`, engine pinned `5aaf2ba2`, `expected_rom_sha256` `f214735b…3387`): success; engine job 22 min; Windows job: package audit (190 archive members, 130 hashed files, no .gba/.sav/.sqlite3/.pem/.key),
packaged 3D `pokeemerald-mp-diorama.exe` sha256 `c8b2bc5c…28ac` and Classic 2D `pokeemerald-mp.exe` `334df799…dadf8` equal the engine job's build, frozen `EmeraldTogether.exe` stayed up 20 s (its screenshot is in the artifact), graphics-mode check 16/16 (the runner has no GPU: 3D reported unsupported, as designed).
Artifact **EmeraldTogether-windows-full** ID 12067368786, 63,225,464 bytes, zip sha256 `efd90f79…1a79`, expires 2026-10-23; no ROM, no sprite pack. Earlier artifacts (12026995145, 12052684712) untouched. The frozen menu's pages were not clicked through on Windows. bios.c licensing unresolved.

## Update 31 — multiplayer rival checkpoints (in development, not integrated)

`docs/update31-rival-checkpoints.md`, `docs/update31/intro-post-state.json`, `docs/windows-test-update31.md`. App branch `claude/dev-update31-rival`
from the integrated U28 default branch `a912f07`; developed in parallel with Updates 29/30 on the owner's instruction. **Verified before starting:** the app
default branch holds U28; U29 is an unmerged branch (`ad254d0`); no U30 exists on the app remote; the engine repository and GitHub Actions are **not reachable**
from this session (credential scoped to the app repository), so no engine change, engine pin or CI run was made. **Audit** (upstream expansion 1.17.1, the engine's
base): five May/Brendan battle checkpoints (Route 103, Rustboro/Route 104, Route 110, Route 119, Lilycove) with maps, triggers, flags, rewards and gates, and the
original introduction's post-state; both re-derivable by `scripts/multiplayer/check_rival_catalogue.py --engine <checkout>`. **App implementation:** world sidecar
`<world>.rival-checkpoints.sqlite3` (completion once per world, personal passes, committed battle intents before the Desk call), Start Now / Wait lobby with a
grace and countdown, formats over the existing native battles (1v1; three players: round robin of 1v1s; four: balanced 2v2), completion only from released
results, catch-up and solo passes, interruption policy (no completion from a timeout or disconnect; held battles wait for native recovery; bystanders are never
stranded), the `rival` extension of `battle_pending`, the Players-menu rival page, and a capability-gated EMW1 `RivalRecord` for the engine. Shared files changed
minimally: `server.py`, `battle_protocol.py`, `companion.py`, `world_mailbox.py`, `player_menu.py`. **Not done (engine):** intro replacement, NPC rival removal,
barriers, per-player rewards on a pass, canonical rival battle background, cutscenes. Simulation only; nothing ran on a real PC, core, GPU or network.

## Update 31 — engine half (engine session, 2026-10-17; not integrated)

Engine `claude/dev-update31-rival-engine` (`429c5211`, on the U30 engine branch `8b8bb92a`, which contains U29), app `claude/dev-update31-rival`
(`312518a` + docs). **Verified first:** both repositories readable and pushable (development branches); GitHub Actions not reachable (no `gh`, no token,
private pages refused); app default `ad254d0` and engine default `8ea2b8c9` hold Update 29; Update 30 exists only on `claude/dev-update30` (app `f2e6b97`)
and `claude/dev-update30-gameplay` (engine `8b8bb92a`), with no ledger entry or recorded CI run; `check_rival_catalogue.py --engine` OK on the real engine.
**Engine:** `src/multiplayer_rival.c` + `data/scripts/mp_rival.inc` (PC only): `RivalRecord` from the world mailbox snapshot, `gMultiplayerRivalAbiVersion`;
original May/Brendan objects away and their five battle scenes replaced only in multiplayer (offline and with older hosts the original scenes play);
Route 110 / Route 119 trigger lines stop a northbound player per `gate_blocks` (exclamation, message, step back, Players menu); personal effects of a pass
once, guarded by the save's own state (Route 103 lab state; Rustboro Match Call; Dowsing Machine; HM02 Fly, `FLAG_RECEIVED_HM_FLY` and Scott's scene, which
the first audit had missed; Lilycove); battle cue and banners; the rival battle's environment from `MP_RIVAL_PREP_WORD` in the native preparation on every
core (PLAIN; background and Camouflage / Nature Power / Secret Power alike); the streamlined introduction in `CB2_NewGame` (Birch's gender/name, the
18-starter screen, the audited post-state, Littleroot at the own door, one save: what Update 30's first-time character creation expects). Fixed during the
port: a pass-through coordinate trigger re-fired every frame and held the player (U31-4). GBA ROM byte-identical (`f214735b…3387`; `multiplayer_rival.c`
kept out of the GBA link like the other PC-only modules, which was needed: an empty object reordered the linker's interworking veneers).
**App:** the environment word through `BattleDesk` (consent fingerprint, view, both preparations, durable record, replay), the companion's checks, the
host enabling it from its manifest's `rival_abi_version`, the manifest marker, Scott in the catalogue, a stricter catalogue checker.
**Checks:** `--selftest-rival` 24/0; `rival_check.py` 21/21; app `test_rival_environment.py` 14 new; focused battle + rival suites pass; trial integration
U29 + U30 + U31 2072 passed, 4 failed (U31-1, a missing fixture: regenerated locally from the Update 14 code all 6 `test_save_compat.py` tests pass), 9 skipped;
MinGW objects of every changed file compile (2D and 3D flags); the 27 other PC selftest targets 0 failures (`species_data_check.py` lists the six
PORTABLE map-script hooks as reviewed exceptions; species fingerprints unchanged); 3D `first_battle_check` and `battle_end_check` (wild) ok. Final engine
head `7140c6bc`. **Not performed:** Windows CI (not reachable), a real multiplayer rival battle between game
cores, real PCs, GPU, network. bios.c licensing unresolved; no ROM or sprite pack is distributed.

