# Keyboard controls: rebinding

**Status: built from scratch on 2026-10-15** (inspection first: before this, the keys were fixed `#define`s
in the engine's `src/platform/sdl2.c`; there was no settings page, no file lines and no rebinding). Tested by
unit tests, a real-event-loop self-test and the launcher's GUI tests. **Not yet tested on a real PC with a real
keyboard, and not run on a Windows machine.**

## What the player gets

* **Launcher:** Help, tab **Game keys** (native game only). One row per action showing the current key (and the
  default beside it when changed). Click a key, press the new one; Esc cancels. **Restore default keys**,
  **Save controls**. Saving is refused while a game is running (the game keeps the same file); the keys apply the
  next time the game starts.
* **In the 3D game:** F10 opens the settings menu; **Controls** opens the same bindings with the same behaviour
  (press-a-key capture, a conflict prompt, Restore defaults, Back). Changes apply and are stored at once. The
  Classic 2D game has no in-game settings menu (F10 is a 3D-build feature), so its keys are changed in the
  launcher or by editing the file.
* **Prompts:** the 3D game's on-screen key prompts show the bound keys (a gamepad's prompts are unchanged).

## Actions (the engine's order)

*Update 30 removed the player-facing 2x speed (the "Fast forward (hold)" key, default Space, and the controller's right trigger); an old `key.fastforward` line in a settings file is ignored, and the launcher drops it the next time it writes the file.*

| Action | Default | Action | Default |
| --- | --- | --- | --- |
| A button | Z | Up | Up arrow |
| B button | X | Down | Down arrow |
| Start | Enter | Left | Left arrow |
| Select | \ | Right | Right arrow |
| L button | A | | |
| R button | S | | |

## The file

`game-settings.cfg` (the launcher's file; `pokeemerald.cfg` beside a hand-started game) gets one line per
**changed** action: `key.a=Q`, `key.b=Left Shift`. The value is SDL's key name (the game reads it with
`SDL_GetKeyFromName`; case does not matter). No line means the default, so **restoring the defaults removes the
lines**. Other lines are kept by the launcher. A hand-edited file that binds one key twice stays playable: the
later action goes back to its default, and if that is taken too, every action does. Unknown names and reserved
keys are ignored.

## Conflicts, reserved keys and a menu you cannot lose

* A key another action has is a **conflict**: nothing changes until the player chooses *swap* (the two actions
  exchange keys, so none is left without one) or cancels.
* **F1-F12 and Esc can never be game buttons.** F10 always opens the in-game settings, Esc leaves a menu or cancels
  a key capture. The settings menus' own navigation (arrows, Enter/Z, Esc/X/Backspace) and typing screens do not
  follow the bindings, and the launcher's controls are mouse and keyboard independent of the game's keys.
  Whatever is bound, the player can always open F10 (3D game) or the launcher's Game keys tab (also the Classic
  2D game) and press *Restore defaults*.
* A key the game already uses for something else is **allowed with a warning**: the screen-reader hotkeys (L, H,
  U, T, Y), the 3D camera keys (`,` `.` `-` `=` keypad +/-) and Tab (menu details). Ctrl+R (the soft-reset chord) and
  Ctrl+P (pause) keep their meaning whatever is bound to R or P.

## Controllers

Unchanged. The Windows XInput code and the Android controller code were not touched, and a pad is combined with
the keyboard exactly as before, so changing the keyboard never disables a pad. Gamepad rebinding was not part of
this task.

## Where it lives

| What | Where |
| --- | --- |
| Table, file lines, conflicts (pure C) | engine `include/platform/keybinds.h`, `src/platform/keybinds.c` |
| Applying keys, file read/write | engine `src/platform/sdl2.c` (`sKeybinds`) |
| F10 Controls page model / overlay | engine `src/platform/pc_menu.c`, `src/diorama/gl/gl_pc_overlay.c` |
| Launcher file module and page editor | `src/emerald_multiplayer/game_controls.py`, `launcher_gui.py` (`_game_controls_page`) |

## Tests

* Engine `make -f Makefile_pc NATIVE_LINUX=1 check-native` runs `test_keybinds` (24,154 checks, including 2,000
  randomly damaged files that must always yield conflict-free usable keys) and the Controls-page model tests in
  `test_display_settings` (308 checks).
* `check-keybinds` (`--selftest-keybinds`): 21 checks through the real event loop with synthetic key events: the
  defaults, a settings file's bindings, the old key doing nothing, Esc never a button, an old `key.fastforward` line binding nothing,
  the Ctrl+R chord, and write-back of only the changed lines.
* App `tests/test_game_controls.py` (file lines, conflicts, reserved keys, the Tk-to-SDL key mapping, the editor)
  and `tests/test_launcher_gui.py::test_game_keys_tab_rebinds_and_saves_the_native_games_keys`.
* The Python and C key-name tables were checked against SDL's own `SDL_GetKeyName` / `SDL_GetKeyFromName`
  (every listed name round-trips).

## Known limits

* One key per action (no secondary key). Mouse buttons and gamepad buttons are not rebindable.
* The Python table has the keys a launcher can capture (letters, digits, arrows, Enter, Space, Tab, Backspace,
  Delete/Insert/Home/End/Page keys, shift/ctrl/alt, punctuation, keypad); other keys can still be put in the file
  by hand if SDL knows the name.
* The Python and C default tables are separate copies (checked by hand, and the launcher test pins the defaults);
  a later change to the engine's defaults must change both.
