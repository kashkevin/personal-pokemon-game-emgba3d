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
