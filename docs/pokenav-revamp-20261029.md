# The PokéNav in the current UI (2026-10-29)

Step 13 of the queue: the PokéNav and every page in it redrawn in the game's current UI design instead of the GBA's
240x160 screens. What changed, how it works, what was found on the way, what was tested and what is left.

Where each result comes from: **L** this Linux machine, the Linux 3D test build (`make -f Makefile_pc NATIVE_LINUX=1
DIORAMA=1 BFX_TEST=1`), software OpenGL, pictures taken by the test harness or grabbed from its window. Nothing here
ran on Windows, on a GPU, on the owner's PCs or with a gamepad. The engine commits are on
`claude/feature-update-engine` and are **not in the 2026-10-27 package**.

| Part | Engine | What |
| --- | --- | --- |
| 1 | `08b58055` | the main menu, CONDITION's and its search's menus; MATCH CALL (the list, a trainer's menu, the check page, calls) |
| 2 | `6f6a59e9` | CONDITION (the party's or a search's Pokemon, the graph, sheen, the markings menu); a search's ranked results |
| 3 | `676ef1ef` | RIBBONS (the Pokemon with ribbons; a Pokemon's ribbon case); the screen kept up between pages; clicks |
| 4 | `d560a355` | the HOENN MAP (zoom, a visited town's own map and key, a route's landmarks, off the map) |
| 5 | `87799768` | the Rustboro tutorial's menu (only what it opens is lit) |
| 6 | `95dea6b6` | the tutorial's own START menu as the field menu |

## 1. What the player sees

Every page is drawn on the design's device: the PokéNav's blue, a cyan screen for what the cursor is on, cream panels
for lists, the design's title tab, cursor, selection frame and hint bar, the game's fonts.

* **Main menu** (HOENN MAP, CONDITION, MATCH CALL, RIBBONS, SWITCH OFF) and CONDITION's PARTY / SEARCH / CANCEL and its
  search's COOL ... TOUGH / CANCEL: a column of buttons with the game's items, the screen showing the cursor's item and
  the game's own words for it; "There are no RIBBON winners." when RIBBONS has none.
* **MATCH CALL**: the registered trainers (name, class, the Poke Ball of a trainer who wants a rematch), the cursor's
  trainer on the screen with their picture and place, their menu (CALL, CHECK, CANCEL), the check page (strategy, the
  Pokemon, the words about them) and a call in the design's message box (NEXT on the calling dots' page break, HANG UP
  at the end).
* **CONDITION**: the party's Pokemon and CANCEL, or a search's results around the cursor; the cursor's Pokemon with its
  picture, level, gender, shiny star, where it is (party or box), markings and sheen sparkles (the game's count), and
  its five conditions as a pentagon graph. In a search, A opens the markings menu over the graph (the four marks as
  edited so far, OK, CANCEL).
* **A search's results**: the ranked list (the game's ranks, its eight rows, scroll and scrollbar) and the cursor's
  Pokemon pictured with "RANK n OF m".
* **RIBBONS**: the Pokemon with ribbons, the most first, each with its count; a Pokemon's ribbon case laid out as the
  game's (nine to a row, the gift ribbons on a row of their own) in the game's own ribbon art, the chosen ribbon enlarged
  on the screen with the game's words, the Pokemon's card with arrows to the ones before and after.
* **HOENN MAP**: the region map in the design's bezel (as the Fly map), the place under the cursor lit, you and the
  other trainers where the game puts them. Zoomed in (A) the map at four times the game's size scrolls under a still
  cursor as the game's does. The side card: a visited town's own map (the game's town map tiles) with a key to only what
  it holds (Pokemon Center, Mart, Gym, Battle Tent, Contest Hall), a route's landmarks, "Not visited yet."; off the map
  (the event islands) the map dims as the game's does. R flies with the Poke Rider where the game allows it.
* **Rustboro's tutorial** (Mr. Stone's first call): the scientist's START menu is the field menu; in the PokéNav the
  items the tutorial will not open are dimmed, and before the call the hints offer only A (B does nothing there, as in
  the game).
* Between pages the device stays up: the game's own frames no longer show through as a page slides or fades.

## 2. How it works

The game's PokéNav (`src/pokenav*.c`) keeps running under the new pages and keeps every rule: its pages and what each
button does, cursors, lists, calls, markings, the map and flying from it. Each frame the UI reads the page as the game
has it (`Pokenav_NativeUiState` and one read-out per part, in `ENABLE_NATIVE_UI` blocks at the ends of the GBA files)
and draws it (`src/native_ui/screens/ui_pokenav.c`; the HOENN MAP is `ui_region_map.c`'s, the tutorial's START menu
`ui_pause.c`'s). The ROM is byte-identical (`f214735b...3387`) and no GBA line moved (`check_gba_lines.py`).

A click becomes the game's own presses. The game reads no buttons while a page animates, so a click that needs several
presses (a row further down, a ribbon two rows away) sets a goal and the UI sends one press each time the game reads
buttons again; the ribbon case follows the game's own cursor rules.

## 3. Found and fixed on the way

* **MS-168** (Low): the shared mark glyphs were drawn circle, triangle, square, heart where the game's bits are circle,
  square, triangle, heart, so the native summary and storage screens showed a Pokemon marked with the square as a
  triangle (and the other way round). Fixed in part 2 (`ui_mon.c`'s table); the summary screen pictured after.
* Part 1's PokéNav cursors slid further right the longer a page was up (their nudge was the frame count); fixed in
  part 2. Not in any package.
* MATCH CALL's list ran under the hint bar with eight rows; its rows are shorter now, name and class on one line.

## 4. Tests and results

All **L**, the Linux 3D test build; pictures in the session's scratchpad. Test builds gained `c<conditions>` and
`r<ribbons>` for a test Pokemon and the field events `NAVTUTOR` and `NAVMENU` (the tutorial's PokéNav and its START
menu).

| Test | Result |
| --- | --- |
| Main menu, MATCH CALL: the list, a trainer's menu, Roxanne's check page, a call to its end | passed (part 1) |
| CONDITION by party: three Pokemon with conditions, CANCEL, the graph, sheen 120 / 30 / 255 as 4 / 1 / 10 sparkles | passed |
| A COOL search over 12 Pokemon (3 party, 9 in a box): ranks, scroll and scrollbar, a result's graph, the markings menu toggling two marks and OK (the marks kept) | passed |
| RIBBONS: four Pokemon with 32, 9, 3 and 1 ribbons (one in a box); the case full (25 ribbons and 7 gift ribbons); choosing ribbons and moving over the case; switching Pokemon; back to the list and the menu | passed |
| Between pages (dense pictures of a page change) | passed: the device stays up |
| HOENN MAP: opening it, Dewford Town's town map and key, Route 106's and Route 115's landmarks, Petalburg City not visited, zooming in, moving zoomed in, zooming out, closing | passed |
| The Fly map after the shared map changes | passed: as before |
| The Rustboro tutorial: its START menu, the PokéNav's menu (B doing nothing), MATCH CALL, Mr. Stone's whole call, the menu after it, SWITCH OFF back to the field | passed |
| Real mouse clicks (`xdotool` on the test display): the main menu's RIBBONS (the menu wrapped: UP twice, A), a ribbon list row (the cursor, then A), a ribbon two rows away (A, DOWN, DOWN, RIGHT, RIGHT, one at a time), a right click (B), the card's arrow (the next Pokemon) | passed |
| ROM byte-identical, GBA lines, the 2D build | passed after every part |

## 5. Not verified, and left

* Nothing on Windows, a GPU, the owner's PCs or with a gamepad (its prompts).
* Clicks on the condition pages, the markings menu, MATCH CALL's menu and the zoomed map were not exercised with a
  real mouse (the same goal code as the clicks above).
* The gift ribbons' words come from the save's gift slots, as in the game; a test save has none, so only their icons
  were seen.
* The help bar's exact words (the game's bottom bar) are the design's hints instead.
