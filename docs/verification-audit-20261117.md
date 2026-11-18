# The verification audit (2026-11-17 to 2026-11-18)

The owner asked (2026-11-17): review everything marked fixed or completed that has not received proper visual or
in-game verification; passing CI is not enough - the gameplay, visuals, performance, multiplayer and the player's
experience are to be verified. This is that review: what was looked at, how, and what each check found.

Verification marks as everywhere in the records: **L** this cloud machine (Linux: real game processes, real
launchers and a real host, Xvfb, Mesa's software OpenGL - not a graphics card); **W** GitHub's Windows runners (CI,
not a player's PC); **PC** the owner's own PCs (nothing here has run there). "Passed in a real game" below means the
real game process ran the case and what a player would see or get was read from it (its pictures, its memory, its
log, its saves); a self-test or a unit test alone is not counted as one.

## How the list was made

* **Every row of KNOWN_ISSUES.md that says fixed, closed or done** (in the row or a later update of it): 126 items.
  78 of them name a gap in their own words - "not run" (23), "not tried" (12), "not looked at" (11), "not seen" (10),
  "simulated" (8), "no game" (6), "not reproduced", "not on Windows", "not pictured" (5 each), "no real" (4) and
  others; 48 name none.
* **Each item triaged by what a player would see and the evidence already recorded for it:**

| Class | Items | Meaning | Done here |
| --- | --- | --- | --- |
| A | 73 | Counted as already verified in a real game or with pictures (L or W) | **Re-read by a second reader**: 56 rows name that evidence (appendix A); 17 did not - 13 shown in real runs their rows never cited (now cited), P4 and MS-4 checked now, G13 and U31-5 moved to D (section "The re-read of class A") |
| B | 33 | Fixed, but never shown in a real game or never pictured: a real check needed | **Run now** (section "B: the checks run"), in three clusters; the checks found 10 more problems (the launcher's behaviour and texts, the Tower Duo's pages, the World page's rows), all fixed, one cosmetic leftover and one status seen once, recorded (section "Found by the audit") |
| C | 2 | Only real PCs or real networks can show it | Steps in the owner's checklist (`docs/windows-test-20261117.md`); appendix C |
| D | 18 + 2 | Nothing a player sees (tools, test harnesses, guards with no visible effect), not reachable in the package, or an owner's decision that changed nothing | Appendix D, with why |

* **B's clusters:** single-player and the battle screens (12 items: me); multiplayer in real games through real
  launchers and a real host (cluster A); the launcher, saves, full disks and the host's clock (cluster B). Clusters A
  and B were run by two helpers in parallel, each on its own displays and folders, with the same game builds; each
  helper's report is a claim until its evidence is read - the rows below say what was read.
* **Builds:** engine `c7b0d80d` (the controller fallback) and `25eb56eb` for the 3D runs that needed the newest
  build; the Linux Classic 2D game, the 3D game, their test builds (`BFX_TEST=1`) and, where a sanitizer was asked
  for, the 3D test build with AddressSanitizer. The app at `abbbd01` and later.

## B: the checks run

### Single-player and the battle screens (L, real game processes)

| Item | What the player gets | Checked in a real game | Result |
| --- | --- | --- | --- |
| MS-38 | Mega Lucario Z's Aura Guard halves contact damage | Classic test build, a trainer battle: Lucario L50 Mega Evolved (Lucarionite Z, the Mega Ring; ability 319 Aura Guard) against a Pinsir L50 using only Tackle: with Hyper Cutter (Aura Guard applies) 32 Tackles, every one 7-9 HP or 11-13 (a critical hit on the halved damage), none in the full range; with Mold Breaker (ignores it) 15-18 every time | **Passed** |
| MS-39 | Rayquaza learns Dragon Ascent and Mega Evolves | Classic test build: START > POKeMON > Rayquaza > MOVES lists Dragon Ascent first; taught over Extreme Speed and saved; from that save, a wild battle: Rayquaza became Mega Rayquaza (Delta Stream), "Rayquaza has Mega Evolved!" pictured | **Passed** |
| MS-35 | A Pokemon revived after fainting as a Mega shows no Mega mark | 3D and Classic test builds, a trainer battle: the foe's Charizard Mega Evolved (X), fainted, Pawmot's Revival Blessing revived it, sent out again: its own form (Fire/Flying), no second Mega in 8 more turns; the healthbox's Mega mark before, none after (3D: the mark after the name; Classic: the Mega symbol in place of "Lv", then "Lv50") | **Passed** |
| MS-109 | A 3D battle's opening keeps the scenery out of the picture | 3D test build: wild battles north of Oldale's Mart and in Route 104's grass, 60 pictures of each opening: the camera moves smoothly (largest step 0.71 and 0.44), no grass, roof or wall across the picture; the one white frame is the intended landing flash | **Passed** |
| P1 | Birch's Zigzagoon gone after the short introduction | Classic test build: the introduction's save and the same save with the flag cleared (an older character), each walked from Littleroot up Route 101 to two cells from where the Zigzagoon jogged: no Zigzagoon, no Birch, in either | **Passed** |
| MS-185 | PokeNav and contest names copied whole | 3D test build with AddressSanitizer: the Match Call list and an entry's page, the PokeNav condition list with a 10-letter nickname and its pages, and a whole Normal Rank contest to the native CONTEST RESULTS screen (the announcer's banners, the eight names, the places): everything whole; the sanitizer's only report in every run the decompressor's known read (upstream code) | **Passed** |
| MS-210 | A full sprite palette table (a busy Pokemon Center) no longer corrupts memory | 3D test build with AddressSanitizer and the test hook that fills every sprite palette (fixed for this audit: `PKMN_TEST_PALETTE_FREE=0` was read as off, engine `c7f89d61`): the nurse heals the party - no sanitizer report, no crash, the same as the control | **Passed**; with every palette taken the healing machine's Poke Balls are drawn in another palette's colours (cosmetic; the guard skips the write as designed) - recorded |
| MS-29 | START right after a turn in place no longer leaves the field "not ready" | The reproduction of 2026-10-21 on the fixed build: Classic test build, Route 101, a 3-frame DOWN tap (a turn in place, facing north to south), START 3, 7, 11 or 15 frames after it; gdb on the running game: as the menu opens the turn is still under way for +3 and +7 (as in the original report) and over for +11 and +15; at the open menu it is over in all four (the fix); the player walks on after the menu | **Passed** (the field check's input; START > PLAYER > RESET itself needs a world: the self-test covers it) |
| MS-126 | The co-op give-up question in the native 3D battle screen | Two 3D test builds through real launchers and a real host (the co-op proof's new `--native-ui`), Rustboro's co-op battle: "Giving up ends this battle / for both players. Give up?" with YES / NO, NO first, in the native battle screen (pictured); No: back to the action menu on GIVE UP; Yes: the team's loss on both games and the host, nothing gained, saves and a fresh Continue | **Passed** |
| MS-125 | "This battle stopped" when a battle core stops itself | The game's own failure function called from inside its battle's frame (gdb) in one game of a running link battle - the abandon proof's new `pairs-corestop`, four Classic games: the notice under the frozen battle (pictured), the host's room needing recovery, the other battle to its result, Recover and Abandon offered to both players, the abandon with no result, everyone back, a rematch, saves, a fresh Continue; and the 3D 1v1 with the same stop: the native notice (pictured) | **Passed** (both builds) |
| G1, MS-10 | Trade effects (a trade evolution's move choice; Lucky Trades) | Not in the package: the Windows package's manifest has no trade-effect rule, so no world turns trade effects on | **Not reachable** (D) |

### Multiplayer (cluster A: L, real launchers, a real host, Classic 2D games unless named)

Each run's own record (`evidence.json`) was read for its result; the scenarios are in the app (this audit's tooling,
below).

| Item | What the player gets | Checked in real games | Result |
| --- | --- | --- | --- |
| MS-23 | Failed trades say why and leave the field usable | Declined ("Decline the trade?" No first; the offerer told "Your friend cancelled the trade."), every host reply to a Confirm lost (both windows closed after the 40 s patience), an unanswered offer ended by the host after 180 s ("The trade timed out."): nothing traded, both players walked and saved after each (pictured) | **Passed** |
| MS-68 | An offer changed as the other confirms: "review again", not a cancel | The answerer changed its offer 0.3 s before the other's Confirm: "Offers changed; review again" with the new pair (pictured); then the trade applied | **Passed** |
| MS-69 | A second A on challenge, team and wager pages does not cancel | Extra A presses after Accept challenge (landed on "Enter battle": entered), Propose, Accept, Invite to team, "Leave the team?" (No first): nothing cancelled. **The Tower Duo pages** (the Tower proof's new `--duo-presses`): after Invite the second press opened "Cancel the invitation?" with No first - kept; **after Accept it opened the team page and a third press took the first Pokemon out; after Ready it undid Ready** | **Passed** (nothing cancelled); the Duo's two traps fixed: **MS-258** |
| MS-120 | Trades survive slow host replies (the game's hold 45 s) | The host's launcher held its next game command 24.9 s during an open trade (the game counted 1,552 frames without a command; the old limit was 600): the window stayed, the trade applied | **Passed** |
| MS-22 | A save after accepting a challenge: "Cancelled: a party was saved" | The friend saved in the game after both accepted: both menus said so; a rematch ran to its result | **Passed** |
| MS-15 | A key pressed as the registration game closes itself does not cancel | Keys 0.27-0.29 s after the game closed itself landed on the menu: the character entered (Solo and Host World), no "Cancelled" | **Passed** |
| MS-92 | A shared wild Pokemon is released when its battler disconnects | The battler's game killed: "busy" for the other player during the grace (by design), released 606.6 s later (the grace is 600 active seconds), then claimed at once | **Passed** |
| M21 | The first World Event action after the launcher restarts the game is not lost | After a restart, the new game's first look was forwarded and stored in 0.71 s | **Passed** |
| MS-122 | Ctrl+P, F5 and F9 refused during a link battle or a held trade | Two **3D** test builds: each key during the battle and the held trade: "No pausing during a link battle or trade.", the game ran on, the battle and the trades to their ends (pictured) | **Passed** |
| MS-123 | A full queue to the companion does not stop a battle or trade | The game's queue stayed at 0 of 4 through four companion freezes: Linux's loopback absorbs the game's writes, so the fixed path never runs | **Not reachable here** (needs smaller socket buffers, as on Windows, or a test hook) |
| MS-124 | Players on lossy links are not dropped when one write stalls | Behind a stalled TCP proxy (3 s during a save, a battle and a download): connected throughout, every operation finished; no write waited over 0.3 s, so the old 1 s limit was never tested against the new 10 s. **And a 5 s stall at a save's start failed the save** while the link survived: **MS-255**, fixed (below) | **Passed** for what it can show; the finding fixed |

### Launcher, saves, full disks and the host's clock (cluster B: L, real menus or the launcher harness, real stores)

| Item | What the player gets | Checked in real games | Result |
| --- | --- | --- | --- |
| MS-212 | A save the disk refuses is written later, and the game says so | The game's own save on a full 512 KB file system (3D and Classic): the title "the save file could not be written: trying again", the 3D save screen's "FILE NOT WRITTEN", written 0.8-8.9 s after room was made, a restart loading it (in full screen a long outage shows only in the title, as the row says) | **Passed** |
| MS-215 | This PC's full disk: "This PC could not store it" | The friend's disk full: its banner, nothing sent or half-written, saving again after room | **Passed**; the launcher's text hidden by **MS-254** (fixed) |
| MS-214 | The host's full disk: the save kept on the friend's PC | The friend's banner "Host PC could not store it. / Kept on this PC: reopen later.", the save kept and committed with the same bytes when the friend joined again | **Passed**; the same masking (MS-254); the run's last step failed on the check's own wait (fixed, below) |
| MS-216 | The newest 40 save copies kept; Continue loads the newest | 44 Save nows; after closing 40 copies; the launcher killed outright and started again: 40; Continue loads the newest | **Passed** |
| NU-1 | A friend can retry after an unfinished registration | Kills of the setup game before the field and at it: retried and registered; **a kill just after the field left every later attempt refused, even for a fresh New Game** | **Failed** - fixed (below) |
| P15 | A crashed setup game is "closed unexpectedly", not "connection lost" | 11 kills at 1.5-9.8 s | **Passed** |
| NU-3 | Connection failures name their reason | A wrong port, a stopped host, a mistyped code, another world's certificate, another version: each its own reason; **a replaced code said "did not answer in time"; a code naming another world said the certificate had expired** | **Partly** - both fixed (below) |
| MS-219 | The host's clock jump does not forfeit a Tower battle | The host process's wall clock moved 25 hours (libfaketime) during a friend's Tower battle: no forfeit, the win paid; with the fix undone in a copy, the same jump forfeited it (the check catches the bug) | **Passed** |
| MS-51 | A milestone Pokemon owed with no room is kept | Owed, "No room for it: make room", a party Pokemon released, "Send Chatot now": delivered; the original sequence (closing before a save) cannot be produced by play: the launcher saves as the Players and Tower pages open | **Passed** for what play can reach |
| MS-48 | Held items after a solo Tower floor | After a won floor at night: Nincada into Ninjask keeps its Choice Specs, the new Shedinja holds nothing (no copy); Gligar into Gliscor uses up its Razor Fang (not given back) | **Passed** |

## Found by the audit, and fixed (app, this change)

| Issue | What the player saw | Fix | Checked |
| --- | --- | --- | --- |
| MS-254 | After Save now the session window kept saying "Saving..." until another row was chosen, hiding "saved" and the disk-full texts | The answer to a chosen row stands until the session's status moves on | Unit tests (fail without it); **real launchers: Save now with the player's disk full - "Saving your character to the host...", then at once "This PC could not store the save (its disk may be full), so it was not sent..."; with room again "Character saved to the host"**, no other row chosen |
| MS-255 | A 5-10 s network stall at a save's start: the link survived, the save failed into recovery ("Saving stopped: restart game") | A save waits 15 s for each answer (more than the 10 s stall the link survives, less than its 20 s dead-host limit) | Unit test; **real launchers: an 8 s stall as the friend's save began: saved, the same connection** |
| MS-256 | Game banners lost their ";" (the game's text has none); a 32-character PLAYERS notice lost its last letter | ":" for ";", a shorter notice | Unit tests; **real games: "Trade cancelled: no change. / Code: TimeoutError" in the friend's game (pictured)** |
| MS-257 | Any program on a world's port: "Close the running host", shown in the menu only as "could not finish" | Its own reason, which reaches the menu | Unit test; **real launcher: another program on 7777 as the host entered - "This world's port is already in use on this PC..." (pictured), then registered and saved once it closed** |
| NU-1 (gap) | A setup game ended just after reaching the field (the host's allocation receipt written): every later setup of that place refused for good | Such an attempt - also another character's at the same place - is set aside when the host holds nothing of it; kept, never deleted | Unit tests (fail without it); **real launchers: setup games killed 0.0, 0.4 and 1.0 s after reaching the field, then a second character's 6.7 s in: each next setup went ahead (the one killed 1.0 s in held the host's allocation receipt: set aside with it), then registered and saved** |
| NU-3 (gaps) | A replaced invite code: "did not answer in time"; another world's code: "certificate expired" | The host's refusal reported at once in Join Friend's words; another world's certificate is "not the world from your invite" | Unit tests (fail without them); **real launchers: both messages right, the other cases unchanged** |
| MS-258 | Tower Duo: a second press after Accept opened the team page and a third took the first Pokemon out (the Duo battle fought with 2 of 3); a second press after Ready undid it | A Duo page whose state or own readiness changed is a new page: the game starts it on its first row (a name, no action) | Unit test (fails without it); **real games: every extra press on the first row, the team three, both ready, the Duo battle** |
| MS-260 | PokeNav > World > Players and weather cut its rows mid-word: "Friend Fl - LITTLEROOT TO", "... - Location hidd" | The place's leading whole words ("LITTLEROOT"), "hidden"; the whole place on the player's own page | Unit test; **real games: "Friend Fl - LITTLEROOT", "Friend Fa - hidden" (pictured)** |
| MS-259 (seen once) | "This save needs recovery" for 0.2 s as the game closed 0.2 s after a save (the MS-214 recheck); the final message right, nothing pending | Not changed: not reproduced with every failed save traced | - |
| The audit's own checks | `ci_play_check.play` counted a recovery commit made as the game opened as its Save now, and closed the game during the real one | The Save now's revision is the one after the newest at the press | **MS-214's run again: every step passed** (the host's refusal shown by itself, the kept save committed as revision 3 when the friend joined again, the Save now 4) |
| MS-210 (cosmetic, recorded) | With all 16 sprite palettes in use, the healing machine's Poke Balls are drawn in another palette's colours | Not changed (the guard skips the write, as designed; only in a Pokemon Center already full of players' sprites) | - |
| The palette test hook | `PKMN_TEST_PALETTE_FREE=0` was read as off | Engine `c7f89d61` (test builds only) | MS-210's run |

## The audit's tooling (app, this change)

Kept so every check above can be run again: the co-op proof's `--native-ui`; the abandon proof's `pairs-corestop`; the
session proof's map-edge crossing sampler (MS-3; `--crossing-only` runs the crossing alone) and its World pages' step (MS-5); the Tower proof's
`--duo-presses` (MS-69's Tower Duo pages); the newcomers proof's `trade-failures`, `proxy-stall` (`--proxy-save-stall`), `spawn-leave` and
`restart-look` scenarios (`audit_trade_checks.py`, `audit_spawn_checks.py`, `audit_restart_checks.py`,
`audit_tcp_proxy.py`); the challenge proof's `menu-presses` (`audit_menu_checks.py`); `ci_play_check.py`'s
`--stray-keys-at-close` and `--world-port`; `save_retry_real_proof.py` (MS-212); `launcher_real_checks.py`
(MS-214, MS-215, MS-216, NU-1, P15, NU-3 on the player's own menu); the Tower proof's `clock-jump`, `milestone-full`
and `held-items` (MS-219, MS-51, MS-48) with their fixtures in `make_tower_saves.py`; `pc_release_probe.py`.
None of it runs in the Windows workflow yet; the evidence (pictures, records) stays out of the repository.

## The re-read of class A (the items counted as already verified)

Counting an item as verified because its row "has evidence" is itself a claim, so all 73 were read again by a second
reader who had not made the first triage, with one question: does the row name a real game process or pictures (a
self-test, a unit test, a test ROM, a simulation or "compiles" does not count)? **56 did. 17 did not**, and each of
those was settled (KNOWN_ISSUES has the citations, appended 2026-11-18):

| Item | What the re-read found | Now |
| --- | --- | --- |
| MS-2 | Row: a unit test only | The host's own enrollment through its real launcher runs in every launcher proof (`docs/multiplayer-session-fix-20261019.md`'s runs; this audit's own runs) |
| MS-3 | Row: the fix only | The session proof's four games after a player crosses from Route 101 into Littleroot (the same document); **the moment of the crossing checked now in real games**: four Classic games, the walker over two map edges, the other three read every 20 ms (2,853 samples): never unlinked, snapshots at most 9 frames old (the limit 180), every player on the field in every game throughout |
| MS-5 | Row: the generated table only | PLAYERS read "Field: LITTLEROOT TOWN" in the session proof; **the World pages (the PokeNav's World > Players and weather) checked now in real games**: the sharing walker in LITTLEROOT, the others "Location hidden", its page "LITTLEROOT TOWN" (pictured) - and the list's rows cut mid-word: **MS-260**, fixed |
| MS-14 | Row: two unit tests | Windows installed check 39303520514: "3D graphics cannot start" answered with Classic 2D (`docs/free-for-all-native-fix-20261019.md`) |
| MS-20 | Row: the rule only | win-late-1 and fixed-ch-failed-2: after a refused Enter, both free, saved, a fresh Continue (`docs/multiplayer-battle-trade-repair-20261020.md`) |
| NU-2 | Row: a design document | Installed check 39303520514: one New Game each, then Solo, Host World, Join Friend with the same characters (one runner) |
| NU-6 | Row: no run named | Every `windows-package` run's installation job (install, start, repair, uninstall, update) |
| P9, P11, P12, P13 | Rows: the fix only | `docs/windows-gameplay-repairs-20261017.md`: the bag measured frame by frame, "LINK HOSTING - Waiting for friends" in a real host session, the resolution matrix's pictures, a new world's pause menu at 12:05 PM |
| VR-4 | Row: the commit only | `docs/visual-repairs-20261018.md`: GBA and 3D frames side by side through the healing, Calvin's "!" |
| WC-2 | Row: tests and a decoded code | Installed check 39303520514: hosting on the runner's network address and a friend joining with the code; hosting after an address change: the owner's checklist, Test E step 10 |
| P4 | Row: the fix only | **Checked now in a real game** (single-player table above) |
| MS-4 | Row: the fix only | **Checked now in real games** (single-player table above) |
| G13, U31-5 | Owner decisions with nothing changed | Moved to D: nothing to verify |

The lesson for the records: a fix's row should name the run that showed it, not only the commit; the 13 rows above
named their runs only in other documents.

## C: what only real PCs and networks can show

| Item | Why only a real PC or network shows it | Where |
| --- | --- | --- |
| MS-89 | A long session's speed and sound on a graphics card and a sound card (growth never reproduced on Linux) | `docs/windows-test-20261117.md`, Test G |
| NU-4 | Hosting across real networks: automatic router setup, Tailscale, a self-run relay | The checklist, Test F |
| WC-2 (part) | Hosting again after the host PC's network address changed | The checklist, Test E step 10 |

## What is still not shown, in one place

* **MS-259's cause** - a 0.2 s status seen once, not reproduced with every failed save traced.
* **MS-123** - the fixed path (a full queue to the companion) cannot be produced on Linux's loopback: each of the
  game's channels waits for an answer before it writes again, so the queue fills only when several answer at once
  into a socket that does not drain; the engine's unit test (`save_response_waits_for_a_full_queue`) fills it by hand.
* **MS-124's 1 s against 10 s** - every operation survived the stalls, but no write waited long enough to tell the
  limits apart here; the save timeout it uncovered is fixed (MS-255).
* **MS-51's exact sequence** - closing before a save cannot be produced by play (the launcher saves first).
* **G1, MS-10** - the trade-effect path is not in the package.
* **Windows**: none of this audit's runs were on Windows. Its fixes (MS-254 to MS-258, NU-1's and NU-3's gaps) went
  into the full `windows-package` run [482](https://github.com/kashkevin/personal-pokemon-game-emgba3d/actions/runs/44230553383)
  (W, 2026-11-18: all 93 jobs passed - each fix's unit tests in the app's tests on Windows, saving and joining in the
  installation check; the rechecks themselves stay L only); MS-260's goes into the next full run; the owner's checklist
  covers the real PCs (PC).

## Where the evidence is

Pictures, logs and each run's own record stayed on this machine (the session's scratch folder), never in the
repository: `auditC/` (single-player, MS-125, MS-126, MS-29, P4, MS-4; the fixes' re-runs in `auditC/fixes/`, MS-3's crossing in `auditC/crossing/`, the Tower Duo's pages in `auditC/duo/`, the trade banners in `auditC/ms256/`), `audit-run/clusterA/` and
`audit-run/clusterB/` (the two clusters), `audit2/` and `audit3/` (the lists, the re-read). TEST_LEDGER.md has a row per
group of runs with its result.

## Appendix A: the 56 items whose rows already named real-game or picture evidence

(The re-read's 17 are in its own table above.)

| Item | What the player sees |
| --- | --- |
| E5 | Battle stage at the Battle Pyramid's top and other flat battle places now right in 3D. |
| E9 | Magma Hideout machines stand as boxes; no 3D battler stands on a machine. |
| MS-13 | Windows players keep their link in battles and menus; characters can enter worlds. |
| MS-17 | Healthy free-for-all battles interrupted mid-battle by a stalled host event loop. |
| MS-19 | PLAYERS window stuck on 'Waiting for server...' after a refused Enter battle. |
| MS-25 | 3D battle water, flowers and sea air keep moving after a hitch. |
| MS-32 | Every player, not only the host, can Mega Evolve in multiplayer battles. |
| MS-33 | Both opposing players in a 2v2 can Mega Evolve. |
| MS-43 | Entering the Battle Dome lobby crashed the PC game. |
| MS-47 | Co-op battles with a team selection (Tower Duo) never started. |
| MS-53 | Battle Points earned since the last save now count in the Tower shop. |
| MS-64 | Trades ending at once ('kicks you out') when a player walked during preparation. |
| MS-70 | In 3D link battles the opponent's moves no longer look like your own. |
| MS-87 | Zoomed-out 3D camera on a wide window showing flat blocks and wrong maps at the edge. |
| MS-90 | HUD showing the previous Pokemon's status on the next one after U-turn. |
| MS-91 | Mr. Briney's cottage could not be entered with a friend connected. |
| MS-95 | Trades kicking players out after both confirmed, leaving saves needing recovery. |
| MS-96 | Battles using Imposter or Transform stopping and asking for recovery. |
| MS-100 | Game Corner screens show all coins, not only the 5,000 stake. |
| MS-103 | Field move cut-in banner (Cut, Surf, Fly) missing in the 3D view. |
| MS-151 | Trade-evolution species can be traded and evolve on the receiving side. |
| MS-153 | Slopes (Jagged Pass, Routes 115/119, Safari Zone, Granite Cave) lying flat in 3D. |
| MS-164 | Room furniture, walls and objects drawn flat on floors in 3D; rooms now modelled. |
| MS-166 | Day Care lady saying 'not enough money' with the money in hand. |
| MS-167 | 3D message boxes going blank or stopping mid-word. |
| MS-172 | Flat 3D places: Mossdeep and Fortree trees, Sootopolis terraces now stand. |
| MS-181 | Other players under water (Dive) not drawn, or drawn without their own carrier. |
| MS-182 | Nothing visible: 3D snapshot read past tileset tables on a warp's last frame. |
| MS-187 | Mossdeep and Battle Frontier stairs standing as slabs with a pop in 3D. |
| MS-188 | East/west ramps drawn backwards, with spikes and sky gaps in 3D. |
| MS-196 | A save could be lost after a power cut right after saving. |
| MS-200 | Battle effects drawn about 40 px off when one side has a lone Pokemon in doubles. |
| MS-203 | Nothing visible: Battle Dome tourney tree read past its state. |
| MS-204 | Nothing visible: two out-of-bounds accesses (script movement, level-100 exp bar) guarded. |
| MS-206 | Windows 3D game crashing at any attendant's 'save the game?' prompt. |
| MS-221 | Game kept running after a launcher crash; a second copy of the character could open. |
| MS-222 | Safari Zone South's white rails and plateau laid flat in 3D. |
| MS-223 | Fortree tree houses and plank bridges laid on the ground in 3D. |
| MS-224 | Cave stairs between floors flat, with a one-tile jump at the top in 3D. |
| MS-226 | People on stands or behind desks hidden inside room models in 3D. |
| MS-232 | Thin walls and corner spikes in battle rooms in 3D. |
| MS-233 | Back walls missing over a switched-on TV or beside stairwells in 3D. |
| MS-235 | Black wedges beside the Battle Palace battle room's pillars and door. |
| MS-236 | Black over lift, cabin and Pike curtain doors in 3D rooms. |
| MS-239 | A line of sky behind the Battle Palace's pools in 3D. |
| MS-240 | Sky showing through gaps of three building models in 3D. |
| MS-241 | F12 screenshots saved where the player can find them (Pictures/EmeraldTogether). |
| MS-245 | Square dark patches under voxel trees (F8) in 3D. |
| MS-248 | Blocky corners on raised edges and square tall-grass outlines in 3D. |
| N20 | Windows game crashing during the intro after loading a save (seen once under Wine). |
| N39 | Double trainer battles (e.g. Tate and Liza) crashing as foes are sent out after continuing a save. |
| S7 | Role Play, Snatch and similar moves draw the HD sprite-pack picture instead of the GBA art. |
| U31-3 (update 2026-11-11) | Rival PvP battles use the checkpoint's plain environment on every player's game. |
| V6 | Lift and cabin doors in rooms with flat back walls now open in 3D instead of staying shut. |
| V44 | Ranking Hall's shading band no longer drawn as recessed windows with sills in 3D. |
| V46 | 3D battles at Mirage Island, Shoal Cave high tide and Sootopolis legends' battle drawn on switched layouts. |

## Appendix D: nothing a player sees, or nothing changed

| Item | Why it is not a player-facing check |
| --- | --- |
| G2 | None: a documentation page of balance values. |
| MS-36 | Not reachable: menus and AI never offer two Megas for one trainer; an engine re-check. |
| MS-59 | None: a gdb breakpoint artefact, closed as not a game defect. |
| MS-98 | None: how the 3D map-sweep test tool enters facility rooms. |
| MS-110 | Less 3D stutter when running; chunk build times measured in real game runs. |
| MS-112 | A regular 3D spike near animated water removed; measured in real game runs. |
| MS-113 | A 3D lag frame after map crossings removed; measured in the real walk runs. |
| MS-115 | Less 3D lag on Route 111 with the Mirage Tower; measured in real runs. |
| MS-116 | Fewer 3D chunk rebuilds when running; measured in the real region sweep. |
| MS-117 | Less 3D lag at sea near Pacifidlog; covered by the real region sweep. |
| MS-159 | None: a Windows 3D build compile error. |
| MS-170 | None: a 3D build tool's test. |
| MS-183 | Nothing visible: door animation read past a palette list for a blank layer. |
| MS-189 | None: a 3D build tool's test. |
| MS-197 | Barely: on Windows, world files stayed locked after a refused store until the launcher closed. |
| P8 | None: a developer capture harness limit. |
| U31-7 | None: developer debug-scene variables on Windows (test harness). |
| U31-9 | Nothing visible: memory guard when a script names an object not on the map. |
| G13 | The owner's decision (#36, 2026-11-05): the 12x world clock's day counters kept as they are; nothing changed, nothing to verify. |
| U31-5 | The owner's decision (#67, 2026-11-14): the original rival's Match Call entry kept; nothing changed, nothing to verify. |
