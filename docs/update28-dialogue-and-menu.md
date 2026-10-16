# Update 28 — dialogue that did not advance (bug 5) and the unified main menu (feature 6)

Engine branch `claude/dev-update28-engine`, app branch `claude/dev-update28`. Everything below was measured in the cloud
(headless, xvfb, **software OpenGL, no GPU**, no real keyboard, no second PC). Nothing here is a real-PC or real-network result;
the list of things to check on a real PC is at the end.

## Bug 5 — "Hey you…" stays on screen after A; two or three more presses are needed

### What was wrong (measured, not guessed)

The question was where the script, the text printer, the input and the drawn text disagree. A trace was added
(`PKMN_DEBUG_DIALOG=boy|rescue|youngster|sign|bag` runs one of the game's own Route 101 scripts; every game frame in which anything
changed logs the script's position, the window-0 printer state/offset/delay, the keys of the frame, the Native UI's printed offset
and the page the 3D message box would draw). Real multi-page dialogue (`Route101_EventScript_Boy`, "…tall grass.\p If you want…";
Birch's rescue call) was run in the 3D and the Classic 2D builds.

* **Script, printer and drawn text agree.** In every run the printer waits in `RENDER_STATE_CLEAR` at a `\p`, an A press moves it to
  `HANDLE_CHAR` the same frame and the script finishes at its end; the Native UI's page selection matches the printer's offset.
  No page is skipped or repeated, and Classic 2D (the GBA's own text engine) behaves the same.
* **The input path loses quick taps.** The window loop hands the game the keys *held at the frame boundary* (`keyboardKeys`, a
  level). A key that goes down and up between two boundaries leaves nothing. A 3D frame is much longer than the GBA's 16.7 ms
  (Windows also delivers the down and up events of a quick tap in one batch). The tap was measured with a thread that pushes real
  SDL key events (`PKMN_DEBUG_TAPS`) and counts the presses the game sees (60 taps, 250 ms apart):

  | build | tap length | lost before | lost after |
  |---|---|---|---|
  | Classic 2D | 15 ms | 6 | 0 |
  | Classic 2D | 30 ms | 1 | 0 |
  | Classic 2D | 50 ms | 0 | 0 |
  | 3D | 15 ms | **34** | 0 |
  | 3D | 30 ms | **20** | 0 |
  | 3D | 50 ms | 2 | 0 |

  A lost press at a `\p` is exactly the report: the line stays, and the next press (or the one after) is the one that arrives.
  The software display is slower than a real GPU, so a real PC loses fewer taps, but any long frame (the 3D view, a save, a heavy
  scene) loses some, and 3D is worse than Classic, as reported.
* **The old page stayed up too.** After the press the 3D message box kept the previous page until the first letter of the next one
  was printed (a slow text speed made that a visible pause: "nothing happened"). The GBA engine does the same internally, but the
  native box can do better.

### The fix

* `src/platform/key_queue.c` (`include/platform/key_queue.h`): the keyboard's changes are queued in order and the game frame takes
  one step per frame. A tap is a frame with the key down followed by a frame with it up; a key released and pressed again inside one
  batch is delivered up for a frame in between, so the game sees a new press; changes that lose nothing are merged (two keys pressed
  together arrive in one frame), so ordinary play sees exactly what it saw before. The Windows pad is polled between frames the same
  way. Nothing is sped up, no event is skipped, and the dialogue text, text speed and script flow are untouched.
* `UiW_MessagePageFlip` (`ui_widgets.c`): once the printer has left its wait at a `\p`, the 3D box starts the next (blank) page at
  once instead of keeping the old one until the first letter.
* The game's own scripts, text and the GBA ROM are unchanged (GBA ROM sha256 `f214735b…3387` after the change).

### Verification

* `tools/pc_port/tests/test_key_queue.c` (8 tests, 8,694 checks incl. 2,000 random event streams: every press that came and went is
  seen, nothing is invented, the queue ends on the real level, a backlog cannot hang); `--selftest-keybinds` grew 6 cases
  (a tap between frames, a held key, a second tap in the next batch) — 36 of 36.
* `tools/pc_port/input_tap_check.py` (taps seen = taps pushed, both builds, 15 and 30 ms) — before the fix it reports 34 and 20 lost
  in 3D.
* `tools/pc_port/dialogue_check.py` (3D and Classic 2D, scripts `boy` and `rescue`: all 60 taps seen, the script runs to its end,
  and the 3D box never keeps the old page after A at a page break).
* Not changed and re-checked: GBA ROM hash (`pokeemerald.gba` rebuilt: `f214735b…3387`), the 22 PC selftest targets (0 failures;
  `check-native` includes the new `test_key_queue`), `check-diorama`, and Update 26's `battle_end_check` (wild, trainer),
  `first_battle_check` and `party_menu_check` (AddressSanitizer). The i686 MinGW objects of `sdl2.c`, `key_queue.c`,
  `debug_scene.c`, `text.c` and `script.c` compile (the Windows pad branch cannot be run here).
* `first_battle_check` failed once on this update's first run with 0% and 34% lit scenery: its three pictures were taken at
  *presented* frame numbers, and a machine that presents faster than the one the numbers came from reached them while the game
  was still at the starter screen (the same build passed pinned to one core). It is not the key queue (the script's keys do not
  pass through it). The check now takes its pictures at *game* frames (`PKMN_DEBUG_GLSHOTS_GAME=1`) and passes on 4 cores and 1.
* Not verified: real keyboards (key-repeat settings, other keyboard layouts), real frame times, controller buttons (the pad uses the
  same queue on Windows, which cannot be run here), and dialogue in multiplayer interactions beyond what the existing multiplayer
  suites cover (the queue sits below them).

## Feature 6 — one main menu

### Architecture decision

The GBA engine cannot show a menu before gameplay starts: before a game opens the launcher has to verify the installed game,
open the world or invitation, take the character's save lease, start (or reach) the host server and verify recovery state. All of
that lives in the Python launcher, which is already the application's front window. So the menu is a **single-window native
frontend in the launcher** (as the brief allows), not part of the GBA engine; the SDL game window opens when a session starts and
the launcher stays as its control panel (Save now, autosave, recovery), exactly as before. No network protocol, server, world or
save format was touched.

### Flow

Launch `EmeraldTogether.exe` → the main menu (one window):

| Choice | What it does |
|---|---|
| **Continue Adventure** | Starts what you played last — the same world (or invitation), address and choices — through the same start code as choosing it by hand (graphics check, installation check, world/invitation checks, lease). Its subtitle says what it will start and when it was last played. Off, with the reason, on a first launch or when the file was moved; on a PC without the game it becomes **Set Up Your Game** and opens Settings → Game files. |
| **My Worlds** | Lists the worlds on this PC with players and "played 2 days ago" (opened read-only: no listener, no lease, nothing written). Host this world, Set up characters, Create a new world, Prepare a character to join a friend, Choose a world file, Refresh. The setup pages open **inside this window**. |
| **Host Multiplayer** | Pick a world, the address ("Use this PC's network address" fills the likeliest LAN address), Internet option (asks first: it exposes the host; says plainly that **port forwarding is the host's job and there is no relay server**), Host Game, connection details and Copy. |
| **Join Friend** | Choose your invitation file (recent ones are listed), Check connection, Join Game. States plainly that this version joins **by invitation file only — no invite codes, no automatic discovery**. |
| **Settings** | Display & graphics (3D Diorama / Classic 2D, resolution, mode, quality), Audio (game and cry volume), Game keys, Game files (Import my game…, Check installed game files), Launcher text size. |
| **Exit Game** | Closes the launcher; asks first (in the window, no pop-up) if a game or startup is still running. |

Mouse, Up/Down + Enter, the first letter of a choice, Esc to go back. The window is 800×780 (minimum 700×680). The menu does not
read a game controller (Tk cannot); the controller works in the game once it opens.

When a session starts the window shows the running-game page (status, Save now, autosave, recovery buttons, Trainer Card, Challenges,
Archive, Local Reset, Championship). **Back to the main menu** is refused with an explanation while a game or startup runs, and
works after it ends (including after a failed start), so the menu is always reachable without abandoning recovery.

### Windows and checks: kept vs removed

* **Removed:** the "Set up a world or character" pop-up window (it was a second modal window with its own pages); the
  tabbed Host Game / Join Game pages inside the old start window. Both are now pages of the one window; the setup pages are the same
  code, worker and messages (`SetupWindow(container=…)`).
* **Kept on purpose:** the Help window (read-only text, F1), file pickers, and everything underneath: game installation/pin
  verification, game import (ROM ownership), graphics check, world/invitation verification, host/join session code, one session at a
  time (a second start while one runs is refused: no duplicate server), the save lease, autosave, battle/trade/host recovery. None
  of the launcher's checks were removed or relaxed to make the start look simpler.
* New private data: `launcher-recent.json` in the private launcher folder (a path, address, internet flag, times; never a
  credential; a damaged file is ignored and kept). Worlds, invitations, saves and the display/graphics files are not migrated or
  rewritten, so existing worlds and characters work as before.

### Tests (all simulated; Tk under xvfb)

`tests/test_launcher_menu.py` (30), `test_launcher_recent.py` (8), `test_launcher_worlds.py` (12, including real worlds made and
opened by the setup code: listed with their players, a damaged world flagged, a changed installation noticed, nothing written),
`test_launcher_setup_gui.py` (+4, setup embedded), `test_game_display_settings.py` (+4, audio), updated footer-visibility test. They cover: menu order and no
pop-up windows, back/Esc/arrow keys, first launch, missing game, Continue (host with its address, join, moved world, remembered
after a start), one session only, back refused while running and allowed after (also after a failed start), Internet confirmation,
bad address, no-invite-code wording, recent invitations, world list/selection, background scan, embedded setup, exit confirmation,
settings pages and saving audio only while no game runs, connection/invitation failure messages. Full app suite: see the ledger.

### Not verified (needs a real PC)

Continue Adventure and every menu path with the real game and a real world; real LAN and Internet join (never run); a real
controller; high-DPI scaling of the new pages; the frozen `EmeraldTogether.exe` look (screenshots here are the Tk source run on
Linux with a fixed font).

Screenshots (Linux, Tk source, simulated display): `docs/update28-screenshots/`.
