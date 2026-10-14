# EmeraldTogether Preview 14: six-issue diagnosis

Diagnosis only. No gameplay code was changed. Written 2026-10-14 on the app branch
`claude/admiring-bohr-dpxzuy` (engine reference: `claude/cloud-setup-engine` = `claude/emeraldtogether-combined`
`e1105565eb` plus two `.gitkeep` files; game code `f8dbffa88a`).

**How to read the labels.** *Confirmed* = reproduced or read directly in code/CI logs this session.
*Reported* = taken from the project's own records (`KNOWN_ISSUES.md`, `TEST_LEDGER.md`, `docs/`); not re-run.
*Suspected* = a hypothesis consistent with the evidence but not verified. Nothing here is "fixed" because a
test passes.

---

## 0. Summary and ranking

| Rank | Issue | Current status | Severity | Impact | Effort | Model |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | **4. Windows: the 3D game exits silently without a modern OpenGL driver; no gamepad on PC** | Confirmed bug (new) | High (blocks some friends' PCs) | Anyone with no GPU driver / a VM / RDP | Medium | Sonnet High |
| 2 | **1. M25 slow battle relay** | Root cause identified; storage ruled out | Medium | Every online battle; gets worse over the Internet | Medium to Hard | Sonnet High (F1, F3), Opus (F2) |
| 3 | **3. 2v2 / full-six recovery** | Works for normal play; recovery for full parties never passed | High for interrupted 2v2 | Host loss mid-battle | Hard | Opus |
| 4 | **6. Compliance and polish** (N8 licensing, M27, time-dependent test, GEN_6 test pins, sanitizer sweep) | Mixed | N8: needs owner decision | Distribution to others | Easy to Hard | Sonnet Medium (most) |
| 5 | **2. Co-op EXP / Exp. Share** | Works; gaps are persistence and parity tests | Low to Medium | Edge cases | Easy to Medium | Sonnet Medium |
| 6 | **5. Unbuilt systems** (Secret Bases, PokéNav, Frontier modes, Breeding, dynamic legendaries) | Not started; roadmap items | n/a (scope) | Large | Hard to Very Hard each | Opus (design), Sonnet High (build) |

Two new defects found this session (both reproduced): **D1** the 3D exe quits with exit code 1 on a machine
with only basic OpenGL, with no message or 2D fallback; **D2** `--selftest-clock` fails when started in the
last two hours of the local day (a test defect, not a game bug).

Cross-issue dependency in one line: **M25's chattiness creates the huge battle journals that make full-six
recovery fail (issue 3)**, so reduce M25 first.

---

## 1. Multiplayer battle performance (M25)

### Status
Confirmed, Medium. The native battle relay is latency-bound, not bandwidth- or storage-bound.

### Evidence
Reported rates (cloud, 2 CPU cores, everything on loopback):
* Co-op Gym: 2535 blocks in ~900 s = **2.8 blocks/s** (`native-launcher-coop-5`).
* 1v1: 362 blocks in 491 s = **0.74 blocks/s** (`native-launcher-battle-1`, includes key holds).
* 2v2 with four games on two cores: 5545 blocks in 8391.6 s = **0.66 blocks/s** (`native-launcher-multi-10`).

Code read (app `src/emerald_multiplayer/battle_execution.py`, `battle_session.py`; engine `src/main.c`,
`src/multiplayer_battle.c`, `src/platform/sdl2.c`, `mp_bridge.c`):
1. The host drives each battle with `_NativeRoute.step()`. **Every step** issues QUERY to all cores, then
   READ_OUT (**128 bytes per RPC, awaited one after another**), RECEIVE (128 bytes per target per step),
   ACK_OUT, and **KEEP to all cores** (`battle_execution.py:325-408`). A block therefore costs about five
   sequential RPC phases, matching the project's own note.
2. Each RPC is strictly one outstanding command per core (`_command`, line 208). The command is journaled
   with fsync, the intent file is rewritten atomically, the client rewrites its own file, then the response is
   journaled and persisted again.
3. **Built-in idle wait:** the client polls the host with `execute`. When the poll returns no command it
   sleeps `asyncio.sleep(.01)` and polls again (`battle_session.py:215-217`). The `execute` call that delivers
   a response is answered immediately after the future resolves, before the host driver has created the next
   command, so the next command is never in that reply. **Every RPC pays at least one 10 ms sleep.** Over a
   real network each poll also costs a full round trip to the host.
4. Game side: the bridge is stepped once per frame at vblank (`sdl2.c:753`, `MpBridge_Frame`), and the ROM
   consumes one command per main-loop iteration (`main.c:182`, `MultiplayerBattle_Tick`). That is one to two
   frames (16.7 to 33 ms at 60 fps) per RPC, and more when frames slip.

Arithmetic (Confirmed from the recorded counts): 7770 QUERY RPCs over two cores = 3885 steps in ~900 s
= 232 ms per step; at about 3.5 sequential phases per step that is **~66 ms per RPC**. The predicted floor is
10 ms (poll sleep) + 17 to 33 ms (game frames) + 2 to 5 ms (durable writes) = about 29 to 48 ms; the
remainder is attributed to CPU contention (**Suspected**: two to four game processes, companions and the
server share two cores; not profiled).

**New measurement (Confirmed, this session).** `scripts/diagnostics/m25_durable_write_bench.py`
(workflow `m25-bench`, run 38651295428) reproduces one RPC's durable writes (two journal appends with fsync
plus four atomic file rewrites):

| Machine | atomic write | journal append | per RPC | per step |
| --- | --- | --- | --- | --- |
| This cloud sandbox (ext4) | 1.0 ms | 0.21 ms | 4.4 ms | 13 ms |
| GitHub Linux runner | 0.89 ms | 0.26 ms | 4.1 ms | 12 ms |
| **GitHub Windows runner (NTFS, Defender on)** | **0.47 ms** | **0.13 ms** | **2.1 ms** | **6 ms** |

So durable I/O is roughly 3 to 7 percent of the ~66 ms per RPC. The M25 note's emphasis on fsync is not the
main cause. Limit: hosted runners use fast disks; a slow HDD or heavy antivirus PC was not measured.

Other consequences (Reported): the route journal reached 28 MB (46,359 events) for one co-op battle, and a
66 MB journal reproduced a five-second RPC timeout on reload (see issue 3).

### Confirmed root cause
A serialized request/response protocol with one outstanding command per core, about 3.5 sequential RPC phases
per step, and a fixed per-RPC latency floor (10 ms client sleep + one to two game frames + journaling). It is
not network throughput (all proofs were on loopback), not serialization cost, and not storage.

### Suspected, still to verify
* CPU starvation accounts for the gap between the ~30 to 48 ms floor and the observed ~66 ms (profile with
  `py-spy` / per-RPC timestamps).
* Over a real Internet link each `execute` poll adds a round trip, so a block would cost roughly
  5 x (66 ms + RTT) (estimate, not measured): about 1.7 blocks/s at 50 ms RTT, 1 block/s at 150 ms. This is the
  biggest unmeasured risk for the planned Internet acceptance.

### Recommended fix (ordered by gain and risk)
* **F1 (Easy to Medium):** answer `execute` only after the host driver has issued the next command (long poll
  of a few ms, or issue it before replying). Removes the 10 ms sleep per RPC and, over a network, one round
  trip per RPC.
* **F3 (Medium, engine PC only):** while a native battle command is outstanding, run the game's frames
  unthrottled. The PC port already has a 5x fast-forward, and nothing authoritative depends on game speed
  (KNOWN_ISSUES M7). Cuts the one-to-two-frame floor several times. Needs a check that battle animation timing
  and text do not misbehave.
* **F2 (Medium to Hard):** stop sending KEEP every step (the deadline is 180 s; refresh every few seconds) and
  fold QUERY into the previous reply. These are journaled opcodes validated by recovery, so this touches the
  journal format and every recovery proof.
* **F4 (Hard):** larger or multiple chunks per RPC. The 128-byte chunk is part of the mailbox ABI that the
  GBA ROM must keep byte-identical; avoid unless F1 to F3 are not enough.
* **F5 (Low value):** merge the per-RPC intent rewrite into the journal. Saves a few percent and shrinks I/O.
* **F6 (Very Hard):** pipeline several outstanding commands per core. Not recommended.

Expected effect of F1 + F2 + F3 together: per RPC from ~66 ms to roughly 15 to 25 ms, and RPCs per block from
about 5 to about 3, i.e. **roughly 5 to 8 times faster** (estimate; verify with the harness below).

### Difficulty and model
Medium (F1, F3) to Hard (F2). **Sonnet High** for F1 and F3. **Opus** for F2 because the journal, resume and
admission invariants are intricate (about 11k lines across the battle and companion modules, with durable-recovery proofs).

### Tests needed
* A new in-process benchmark: real host driver + a fake native core with configurable latency; assert RPCs per
  block and blocks/s before and after (no game needed, runs in CI).
* Existing focused app tests for `battle_execution`, `battle_session`, `native_battle`; `check-coop-controller`.
* Acceptance: `native_launcher_coop_proof.py` (blocks/s, journal events per battle) and one resume proof after
  any journal-format change. A Windows two-PC run for the Internet case.

### Dependencies
Reducing journal events (F2) is a prerequisite for issue 3. F3 needs an engine build; F1 and F2 are app-only.

---

## 2. Co-op EXP and the permanent EXP Share

### Status
Implemented and tested in the cloud. No confirmed gameplay bug found. Gaps are persistence, parity tests and
reach.

### Evidence
Confirmed in code:
* **Permanent party-wide Exp. Share:** under `PORTABLE`, `IsGen6ExpShareEnabled()` returns TRUE
  (`battle_util.c:9641`), so every battle-capable party member gains EXP, including those not sent out (half).
* **PvP never awards EXP:** native battles set `BATTLE_TYPE_LINK` (`multiplayer_battle.c:647`) and
  `BattleTypeAllowsExp()` refuses link, Frontier, Safari, Battle Tower, Trainer Hill and e-Reader battles
  (`battle_script_commands.c:2108`). Link battles also restore each personal party afterwards, so EXP in PvP
  would be discarded even if awarded.
* **Co-op award** is computed after the battle by each game on its own party from locally tracked knock-outs
  (`multiplayer_coop.c`: `TrackCoopFrame`, `CaptureCoopExpNow`, `ApplyCoopExp`, `MultiplayerCoop_ExpBegin`),
  using `MultiplayerCoop_ExpReward` (`battle_script_commands.c:12508`): full for a Pokémon that faced the
  fainted one, half for the rest, with level cap, Lucky Egg, traded and affection multipliers.
* The award only exists for the **eight co-op Gym battles** (`sCoopGyms`).

Test evidence: `--selftest-coop-exp` passes (re-run this session under the UBSan build: exit 0, 0 reports);
the project records `native-exp-share-5` / `-before-1`, `check-coop-exp`, `test/battle/exp_two_opponents.c`
(G14, PORTABLE/TESTING only) and a lost-battle case. The self-test also asserts that without a co-op battle
nothing is recorded.

### Confirmed bugs
None new. Known: upstream G14 (two-trainer EXP slot) is fixed only for the native game and test ROM; the GBA
ROM and the emulator fallback keep upstream behavior by design.

### Suspected / unverified
1. **Lost award on interruption:** the pending award (`sCoopExp.pending`) lives only in EWRAM and is consumed
   when the victory/defeat script runs. A crash or disconnect between the host's result and that script loses
   the EXP, and nothing persists it. Plausible, not reproduced.
2. **Formula drift:** `MultiplayerCoop_ExpReward` duplicates the battle EXP formula (including a hard-coded
   trainer 1.5x). The self-test compares against a test-side calculation, not the real `getexp` path for the
   same inputs.
3. **Exploits:** the award trusts the local game's own knock-out tracking (acceptable for a private friends
   game; no host check). Co-op rematch farming of EXP and prize money depends on whether Leaders can be fought
   repeatedly: needs an owner answer.
4. **Cosmetic:** the Exp. Share key item toggle always reports "off" while the share stays on
   (`item_use.c:250`, reading only).
5. **Reach:** no co-op NPC or Frontier reward path exists. Frontier battles are excluded from EXP by the
   vanilla flag; whether co-op Frontier should award EXP is a design decision (Phase 8 is not started).

### Recommended fix
Persist a pending award in the save or companion until consumed; add a parity test that runs the real `getexp`
and `MultiplayerCoop_ExpReward` on the same inputs; owner decisions on farming and Frontier EXP.

### Difficulty and model
Easy to Medium. **Sonnet Medium.**

### Tests needed
Parity test across species/levels/multipliers; interrupt test (kill game after result, expect award on
restart); PvP in-game check that party EXP is unchanged; run-through of all eight Gyms' awards.

### Dependencies
None. Frontier EXP rule depends on Phase 8.

---

## 3. Four-player multiplayer and 2v2

### Status
Works for uninterrupted play on Linux (four native clients). Recovery for interrupted full-party battles has
never completed. Several scenarios untested.

### Evidence (Reported unless stated)
* `native-launcher-multi-10`: four Linux clients, 2v2 with full parties, 5545 routed blocks, 17 party
  selections, team 1 won for all four, saves and fresh Continue, no forced cleanup (152 minutes).
* `docs/native-full-multi.md`: twelve Pokémon per side; 58 then 66 focused engine tests (controller ownership,
  switch order, targeting, completion barriers).
* A Windows 2v2 small-party menu proof on the owner's PC (`docs/windows-menu-multi-proof.md`).
* Interrupted battle (`docs/native-battle-resume-proof.md`): small parties pass (`run-small-all`). **Full-six
  runs 3 and 4 failed** (run 4 after 5037 blocks at the post-RELEASE step; the original exception is unknown
  because the controller discarded it). A diagnostic reproduced a **five-second RPC timeout loading a 66 MB
  journal** from that run's world. The final full-six retry was stopped at 4042 s, not accepted.

### Confirmed
The journal-load timeout reproduction is documented; this session confirmed from the code that the journal
grows with every RPC (two events each), so M25's chattiness is what inflates it.

### Reproduced bugs vs untested
Reproduced and fixed earlier: M22 to M24 (co-op phases, consent binding, AI partner target). **Not tested:**
full-six interruption completion; Windows interrupted 2v2; disconnect of a *client* (as opposed to the host)
mid-battle; co-op and wager recovery; one Mega per trainer in 2v2; 1v1v1v1 (planned, not built); four real PCs.
The companion does not reconnect by itself after a network loss (documented). I did not find new race
conditions by code reading in the time available; none is claimed.

### Suspected causes
Journal size and journal-load timeout are the leading suspect for the full-six recovery failures
(**Suspected**: the original task exception is unknown).

### Recommended fix
1. Reduce journal events (issue 1, F1/F2).
2. Load the journal in a bounded way (snapshot or checkpoint plus tail, streamed loading) so recovery never
   depends on reading tens of megabytes within a short RPC timeout.
3. Re-run the full-six recovery proof (the controller now keeps task exceptions).
4. Add a client-drop scenario and a Windows 4-client run (owner hardware).

### Difficulty and model
Hard. **Opus** (journal snapshotting and recovery invariants).

### Tests needed
Full-six `--scenario all` recovery proof; unit tests for snapshot + tail load and corruption cases; a client
disconnect/reconnect scenario; a 4-client run on real PCs.

### Dependencies
Issue 1 first. Windows hardware for the last step.

---

## 4. Windows gameplay and hardware compatibility

### Status
The **package builds and verifies on a real Windows runner**. The 3D game exe **does not start on a machine
with only basic OpenGL**, and **gamepads are not supported on PC**. Everything needing real hardware is
untested.

### Evidence (Confirmed, GitHub Actions, this session)
Full run 38648584801 (engine commit `68318eb5`; success): engine build on Ubuntu (ROM sha256 `f214735b…3387`,
identical to the project's recorded build); Windows job on `windows-2022`, Python 3.14.8, all wheels installed
with `--require-hashes`; `EmeraldTogether.exe` built with PyInstaller 6.22.3; 129 files, audit 284/345 members
clean; **the packaged game exe equals the engine job's build** (sha256 `faba420f…f873`, 90,522,126 bytes) and
`SDL2.dll` (2,043,392 bytes) match `runtime.json`; guides present; **the launcher stayed running for 20 s**.
Artifact: `EmeraldTogether-windows-full` (artifact id 11934352759, about 44 MB).
All five `python-tests` runs (full app suite, clean Linux, Python 3.12) passed on GitHub.

### Confirmed bugs
* **D1: silent exit without OpenGL 3.x-class functions.** The informational step that starts the packaged game
  failed: after `INFO: OpenGL function glActiveTexture is unavailable` the process exited with code 1. The
  hosted runner offers only the Windows GDI OpenGL 1.1 renderer. Cause (code): `DioramaGL_Init` fails in
  `DioramaGL_LoadFunctions` (`gl_loader.c:61`) and `main` does `return 1` (`sdl2.c:527-533`) with only a console
  line: no message box, no 2D fallback, and the package ships only the Diorama exe. Likely victims: PCs without
  a GPU driver, VMs, remote-desktop sessions, very old integrated graphics.
* **D3: no gamepad on the PC build.** `SDL_INIT_GAMECONTROLLER` and the controller events are compiled only
  under `__ANDROID__` (`sdl2.c:400, 409-415, 2322+`). FEATURE_STATUS says "Not yet"; it is not implemented.

### Not verified (needs physical hardware; nothing claimed)
Real GPU frame rates (targets of 60 to 200+ fps are unmeasured), DPI scaling and exclusive fullscreen (V21),
audible audio on a real device, keyboard feel, two PCs over Wi-Fi/Internet, clean-PC install and SmartScreen
behavior, the rare Wine crash N20 (1 in ~10 launches, unexplained), and the M7 fast-forward key in multiplayer.
The ledger records "Real GPU, Windows itself, two PCs, controller, audio: Never run."

### Suspected
* The minimum viable OpenGL level is about 3.3 (instanced attributes, multisample renderbuffers); not measured
  per driver.
* Unsigned executables will trigger SmartScreen prompts (not observed).

### Recommended fix
* **D1:** on GL init failure show a message box explaining the requirement, and fall back to the 2D renderer
  build (ship `pokeemerald-mp.exe` too, or compile the fallback in). Keep the launcher's "Check installed game
  files" pin working with two executables.
* **D3:** enable `SDL_INIT_GAMECONTROLLER` and controller events for desktop, with a default mapping and a
  mention in the quick start.
* Run the owner checklist in `docs/expansion-windows-test.md` on at least one PC with a GPU.

### Difficulty and model
Medium (D1) and Easy to Medium (D3). **Sonnet High** (D1), **Sonnet Medium** (D3).

### Tests needed
The CI Windows runner is a ready regression test for D1 (the game must stay up in the 2D fallback or show a
message, not exit 1); a unit test for the controller mapping; then the owner's hardware checklist.

### Dependencies
None for code fixes. Real hardware for acceptance.

---

## 5. Unverified or incomplete game features

Verified by grep and file reads this session; "implemented" means code exists, which is independent of tests.

| Feature | Verdict | Evidence | Notes |
| --- | --- | --- | --- |
| Multiplayer Secret Bases | **Missing** | No multiplayer code in `secret_base.c` (upstream single-player base only) or `multiplayer*.c`; checklist Phase 6 NOT STARTED | Hard to Very Hard (decor sync, visits, permissions, saves). Opus. |
| Expanded PokéNav | **Missing** | No multiplayer/weather/outbreak/event hooks in `pokenav*.c`; Phase 7 NOT STARTED. Outbreaks are announced by host banner notices instead | Medium to Hard; Sonnet High. |
| Co-op Battle Frontier | **Missing** (Championship exists, unverified) | `championship.py` + menu + launcher panel (45 recovery tests, never played); co-op battles exist only for the 8 Gyms; Phase 8 NOT STARTED | Hard; Opus for rules and recovery design. |
| Breeding improvements | **Missing** | `daycare.c` carries no project changes; Phase 9 NOT STARTED | Medium to Hard; Sonnet High. |
| Expanded legendary events | **Partial** | Host World Events implemented (legendary 38 species, schedule, 15 min timer, claims, ROM event object), status "implemented but unverified"; weather/night/cooperative-objective dynamics absent (Phase 10 NOT STARTED); G3 two-claimant race still open | Medium; Sonnet High. |
| Following Pokémon | **Implemented** | Upstream followers enabled (`OW_FOLLOWERS_ENABLED TRUE`); multiplayer follower sync tested natively (native-followers-5, Wine run) | Local extras (reactions, items) not started; Windows hardware not tested. |
| Shared wild Pokémon / outbreaks | **Implemented** | Host-authoritative shared spawns (tested, Linux and Wine, 28/28), host-scheduled outbreaks with banner notices (native-outbreak-5) | PokéNav outbreak list missing; Windows PC test pending. |
| Character customization | **Partial, FEATURE_STATUS is stale** | Engine now has a 37-character selectable roster (`character_customization.c`, PC build only, saved in the look bytes, relayed by the host) plus the palette STYLE editor | Missing vs spec: free-form hair/clothing mix and creation at game start; the status table (2026-10-09) predates this. Needs a re-audit. |
| Permanent Exp. Share, co-op EXP | Implemented | Issue 2 | |
| Shiny Charm / Game Corner reward | Implemented, unverified | `mp_progression.inc` clerk, 9,000 coins | Needs a play-through. |
| Personal static legendaries / ticket access | Partial | 25 authored reset descriptors; ticket sources "not granted" | A ticket path is missing. |
| Trading | Partial | Eggs/mail refused; evolution/move choices proved only in synthetic replay; G1 still refuses a post-Gen6-move evolution trade against the owner's decision | Small fix (G1). |
| 1v1v1v1, multiple regions, Pokémon League, expanded endgame | Planned | Documented as planned | Out of scope until foundations land. |

Recommendation: do not start Phases 6 to 10 before issues 1, 3 and 4. Each is large; Secret Bases and Frontier
modes need design decisions from the owner first (rules, permissions, rewards).

---

## 6. Remaining bugs, regressions and polish

### Test failures
* GBA suite (`make check`, reported 2026-10-14): 6000 tests, 5498 pass, 39 fail. Classified: all 39 pass under
  upstream's `GEN_LATEST GEN_9`, so they follow from the project's GEN_6 profile that those tests do not pin
  (G10). The six project tests that failed on 2026-10-13 are fixed (G9). Not re-run (about 30 minutes).
* `check-diorama-tools`: 23/24, the known upstream V31 failure.
* **D2 (new, Confirmed):** `--selftest-clock` reports 3 of 58 failed when started late in the day. It passes
  with `TZ=America/Los_Angeles` and `Pacific/Auckland` (58/58) and fails with `TZ=UTC` at 22:58: the test
  advances real time by 1 day + 2 h + 1 day and expects exactly two reset boundaries, so the 2-hour step crosses
  midnight when started after 22:00 local. A test defect, not a game bug. Fix: pin the test's start time to
  midday.
* App suite: green on GitHub (five runs) and in the project ledger (1522 passed).

### Sanitizer and memory safety
First UBSan run on the combined game (`SANITIZE=1`, this session): **10 of the 12 built-in self-tests pass with
zero UBSan reports** (battle-names, coop-controller, coop-exp, cry-stop, line-break, mp-objects, party-order,
shake-anim, spawn-claims, wild-weather). `clock` is D2. `decompress` was killed at the 300 s limit under the
sanitizer (slowness, not a finding; it runs normally in the plain build). **Limit:** these tests do not drive
the paths where the earlier crashes were found (N37 to N40: two-trainer battles, cries, shake animations,
placeholder expansion), which were found by playing. The ASan variant (`SANITIZE=address`) has not been run.
Known benign: N23 (over-reads in quickstart HUD and the smol decoder), N7/N30 division by zero mitigated by
`fault_compat.c`, N8 below.

### Open items (Reported)
* **N8 (compliance, not a bug):** `src/platform/bios.c` contains code derived from VBA-M (GPL-2.0+) and mGBA
  (MPL-2.0). KNOWN_ISSUES says to replace it "before giving the build to anyone." The package is now built
  for others, so this needs an owner decision and a clean-room replacement (from GBATEK). This is a licensing
  judgment for the owner; I am not giving legal advice.
* **M27:** the hint banner shows "START  PLAYER  STYLE" because '>' has no glyph in the banner table. Cosmetic;
  both files are GBA code that must stay byte-identical, so the fix is PC-only text (owner's call).
* **N20** rare Wine crash (unknown cause), **M1** native exe/ROM pairing when started by hand, **M9**
  World Event Pokémon disappears during dialogue, **G3** World Event double-catch window, **G13** other
  day counters still run on world time, **V2/V4/V31** upstream rule-test failures, **V22** low/medium
  quality presets not looked at, S2/S3/S5/S7 sprite polish.

### Severity split
Gameplay-breaking: none known in the code paths tested; **D1** breaks startup on some PCs; the full-six
recovery gap breaks resilience in a rare scenario. Cosmetic: M27, M9, V-series visuals, S-series sprites.

### Recommended fix, difficulty, model
Fix D2 (one line of test setup); pin GEN_6 in the 39 upstream tests or mark them expected; replace
`bios.c`; extend the sanitizer sweep by driving every trainer battle and move animation under UBSan/ASan
(debug menu or a scripted sweep). Easy (D2, test pins, M27) to Hard (bios.c, sweep harness).
**Sonnet Medium** for D2, pins, M27; **Sonnet High** for the sweep; **Opus** only if the owner wants the
bios.c replacement verified against hardware behavior.

### Tests needed
Run the clock test under three time zones in CI; a sanitizer sweep job; the existing `check-*` suite after each fix.

### Dependencies
M27 and N8 need owner decisions.

---

## 7. Prioritized roadmap and cost-conscious strategy

### Order of work
1. **Windows start-up (D1) and gamepad (D3)** (issue 4): small, high impact, testable in CI today.
2. **M25 F1 + F3, then F2** (issue 1): F1 first (app-only, quick win, measurable), then F3, then F2.
3. **Quick tests and polish** (D2, GEN_6 pins, M27): bundle in one cheap session.
4. **Recovery journal snapshotting and the full-six proof** (issue 3), after step 2.
5. **EXP persistence and parity tests** (issue 2).
6. **Owner decisions** (see below) and **hardware acceptance** on real PCs.
7. **New systems** (issue 5), in this order: Breeding, PokéNav, dynamic legendaries, then Frontier modes and
   Secret Bases.

### Recommended model per task

| Task | Model | Why |
| --- | --- | --- |
| D1 GL fallback + message | Sonnet High | Contained engine change; CI test exists |
| D3 gamepad | Sonnet Medium | Small, well-known SDL pattern |
| M25 F1, F3 | Sonnet High | Local changes, measurable |
| M25 F2 (journal format) | **Opus** | Invariants across journal, resume and admission |
| Journal snapshot + recovery | **Opus** | Hard recovery semantics |
| D2, test pins, M27, EXP parity/persistence | Sonnet Medium | Small and well-bounded |
| Sanitizer sweep harness | Sonnet High | Scripting plus triage |
| bios.c replacement | Sonnet High, Opus review optional | Needs hardware-faithful behavior |
| Secret Bases, Frontier modes | **Opus** to design, Sonnet High to build | Large, cross-system |
| Breeding, PokéNav, dynamic legendaries | Sonnet High | Mostly bounded features |

### Cost-conscious execution strategy
Your budget is about $230. I cannot price sessions accurately, so sizes below are relative (S/M/L/XL), not dollars.
1. **Work in small, gated steps.** One fix per session, each ending with the focused tests and a commit; stop and
   report at each gate.
2. **Use GitHub Actions for tests and builds.** The Windows package, the app suite and the new benchmark already
   run free of model tokens. Do not run the 30-minute GBA suite or the 150-minute 2v2 proofs unless the
   touched code requires it; rely on the ledger rule for reuse.
3. **Reuse the cloud environment.** The SessionStart hook reinstalls nothing when tools exist; keep engine
   builds incremental (do not wipe `build/`).
4. **Use Opus only for the three rows marked Opus.** Everything else fits Sonnet Medium or High.
5. **Avoid repeating investigations.** This report plus `KNOWN_ISSUES.md` and `TEST_LEDGER.md` are the memory;
   give each session the specific section, not the whole project.
6. **Measure before and after.** M25 gets the in-process benchmark first; D1 uses the CI Windows runner.

Suggested sizes: D1/D3 = S to M each; M25 F1/F3 = M, F2 = L; polish bundle = S; EXP = S; journal snapshot +
full-six proof = L (and long wall-clock proof runs); each new system = L to XL.

### Owner decisions needed
* N8: how to handle `bios.c` before distribution.
* Co-op rematch/farming and EXP in co-op Frontier modes.
* M27 wording or PC-only arrow.
* GEN_6 test policy (pin versus mark expected).
* Whether to ship a 2D fallback executable.
* Rules for Secret Bases, Frontier modes and dynamic legendary objectives.

---

## 8. What this session ran and what it did not

**Ran:** code and document review across the six areas; GitHub Actions full Windows packaging run
(38648584801) and smoke runs; five `python-tests` runs; the `m25-bench` run on Windows and Linux runners;
a UBSan build of the combined game and 12 self-tests; the clock test under three time zones.

**Did not run:** the GBA test suite, the Diorama check suites, ASan, any gameplay proof (co-op, 2v2, recovery),
any real-hardware or two-PC test, and any run on the owner's PC. Reported figures are marked as such.

## Appendix: sources
`KNOWN_ISSUES.md` (M25, M27, M22 to M24, G3 to G14, N8, N20, N23, N37 to N41, V21), `TEST_LEDGER.md`,
`TEST_PLAN.md` (sections 5, 7j), `docs/native-battle-resume-proof.md`, `docs/native-full-multi.md`,
`docs/expansion-windows-test.md`, engine `docs/expansion-checklist.md`, engine sources named inline,
`.github/workflows/windows-package.yml` and `m25-bench.yml`, scratch logs for the UBSan runs.
