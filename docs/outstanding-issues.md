# Outstanding issues and their verification status

The owner's instruction of 2026-11-04: work through the remaining engineering issues (save integrity first, then
multiplayer performance, then 3D stability), document the options where a change would be a gameplay design
decision, keep this list complete, and treat nothing as verified on Windows from Linux results.

Verification marks: **L** Linux (this cloud machine: unit tests, self-tests in the real game code, real native games
through real launchers); **W** Windows on GitHub's hosted runners (CI, not a player's PC); **PC** the owner's own PCs
(nothing has run there). A fix is "done" here when it is committed and pushed with its tests; "Windows" says whether
a Windows CI run has covered it since.

Updated with every fix; the newest first within each section.

## 1. Engineering work in progress (owner's approval of 2026-11-04)

| Issue | What | Status | L | W | PC |
| --- | --- | --- | --- | --- | --- |
| MS-51 | Battle Tower milestone Pokemon lost when the game closed before saving and the older save had no room | **Fixed** (engine `36fb4589`, app: this change) | self-test 2,103/2,103 (the real game code: a full party and PC answer 0, the host's replayed claims change nothing, the resend makes it); app tests 173 | not yet | - |
| Co-op EXP | Gym EXP farming by losing again; the pending award lost on a reset before the award script | open (next) | - | - | - |
| MS-145 | Kept shinies and Legendaries forgotten when the game closes | open | - | - | - |
| MS-161 | Opening a world slows as its saves pile up | open (partly fixed before: about 5x) | - | - | - |
| MS-118 | 3D frame hitches when many chunks come into view at once | open | - | - | - |
| MS-189 | The 3D rules parity test compares out of step | open | - | - | - |
| MS-39 | Mega Rayquaza unreachable (no way to learn Dragon Ascent) | open | - | - | - |
| MS-38 | Mega Lucario Z's Aura Guard does nothing | open | - | - | - |

## 2. Other engineering issues (to be worked through; options documented where a design call is needed)

| Issue | What | Status |
| --- | --- | --- |
| G3 | A World Event's 120 s claim release after a disconnect could let two players catch the same event Pokemon | open (improved before: active seconds only) |
| NU-7 | An invite code cannot be revoked for one friend | open (design: per-friend credential rotation) |
| MS-29 | START > PLAYER > RESET sometimes does not open PLAYERS (the player is told to try again) | open |
| MS-55 | A new Players menu page opens with the previous page's cursor row | open (cosmetic) |
| MS-52 | The native Tower screens show the game's copy of the record until the next word | open (cosmetic) |
| MS-154 | 6 ledges the player cannot jump land a level higher in 3D | partly fixed |
| MS-108 | Transitions' pictures still the GBA's art | open (art) |
| VR-5 | 226 of 959 battle animations have no HD version | open (art) |
| MS-9 | The emulator fallback's Lua bridge has the same all-zero check as the old native one | open (fallback only) |
| MS-26 | Save checks on the launcher's and host's event loops | measured, no player-visible cost found |
| Trades | Eggs, mail and unsupported forms are refused in trades | open (adapter work) |
| G1 | An evolution trade that must choose a move for a Pokemon knowing a post-Gen-6 move is refused | open (owner decision recorded: such moves trade unchanged; the move-choice path still refuses) |
| MS-141c limits | Wireless minigames: four players not run | open |
| MS-98 | The 3D map sweep's debug scene stops in three rooms (debug warp only) | open (not reachable in play) |
| MS-170 | A 3D rules test's notion of height (records vs resolved cells) | open (test) |

## 3. Decisions only the owner can make (options in `docs/owner-decisions.md`)

N8 licensing of `src/platform/bios.c` (blocks giving the build to anyone; "Leave for now"); the base game dump for CI
(U31-13); the Node 24 actions patch (U31-16); day counters on the world clock (G13); a ticket source for personal
static legendaries; the character customization scope; the 39 upstream GBA test failures under Gen 6 rules; egg
hatching speed (MS-42); and the "built, your call" items: Xbox B as Cancel, 3D vehicles falling back to 2D, music
loudness, Battle Point shop prices, a launcher checkbox for location privacy.

## 4. Verification only the owner's PCs can give

A real graphics card at 60 fps, a controller, two PCs on a home network and over the Internet (router, UPnP/NAT-PMP),
a fresh install and first play on the owner's PC, and the owner's crash logs if the Safari crash recurs (MS-169).
NU-8, VR-6, WC-4, MS-7 hold the checklists.

## 5. Windows CI coverage of the newest work

Run 271 (2026-11-04 morning) covered engine `2054cf05`. Since then, not yet run on Windows: the wireless minigames
with the world's players (MS-141c), the Safari Zone's plateau, and every fix in section 1. The next full run comes
after section 1's fixes, with a Windows minigame job added; its installer is prepared only when every required job
passes, and is not distributed (N8).
