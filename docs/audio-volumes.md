# Volume controls (owner decision #45, 2026-11-05)

The owner's decision (`docs/owner-decisions.md` #45, which supersedes #23 "Loudness"): "Set default music volume to 70%.
Keep sound effects at 100%. Provide independent master, music, and sound-effect controls."

## What the player has

Four volumes, each 0-100% in 10% steps:

| Control | Covers | Default | Settings file key |
| --- | --- | --- | --- |
| Master volume | everything the game plays, after the mix | 100% | `volume=` (the old game volume, unchanged) |
| Music | every music song, the fanfares and jingles included (a level-up, a Pokemon Center's heal, a new item, an evolution), the bard's song | 70% | `musicVolume=` (new) |
| Sound effects | every sound effect | 100% | `sfxVolume=` (new) |
| Pokemon cries | the cries | 100% | `cryVolume=` (existed, was never applied: now it is) |

Where they are changed:

* **In the 3D game:** F10 > Audio (a page like Controls: Up/Down choose, Left/Right change, heard at once and saved;
  Esc or Back returns). The Classic 2D game has no F10 menu: the launcher or the in-game menu below.
* **The launcher:** Settings > Audio (four sliders with their percentage; saved for the next start; refused while a
  game runs, as the other game pages).
* **The in-game menu** (the shell before a game starts): Settings > Audio volumes (pick 0%-100% for each).

All three read and write the same four lines of the player's `game-settings.cfg` (the game's `pokeemerald.cfg`).

## The settings file and older files

* A file written by this engine or this launcher has all four lines.
* **A file without `musicVolume=` and `sfxVolume=`** (written before they existed): music gets 70% and sound effects
  100% (so existing players also get the owner's new music default), `volume=` stays the master as it was, and
  **`cryVolume=5` reads as 100%**: every earlier game wrote 5 as its default and never applied it, so the cries stay
  exactly as loud as they always were. Any other `cryVolume=` in such a file was the player's own choice and is kept
  (it now works). The engine (`AudioVolumes_Finish`) and the launcher (`read_audio_settings`) apply the same rule;
  the next save of the file writes the four lines, and a file with the new lines is read as written (a chosen 5 stays 5).
* Alternative not built: keep existing players' music at 100% (only new installations at 70%), by reading an older
  file's missing `musicVolume=` as 10. One line in each reader if the owner prefers it.
* **The app and the engine must ship together:** an older engine rewrites the file without the two new lines (it keeps
  only the keys it knows), and the next new reader then takes the defaults again.

## How the game applies them (engine `5e12fe8b51`)

* `include/platform/audio_volume.h`, `src/platform/audio_volume.c`: the four settings, the older-file rule, which
  control each song and mixer channel answers to, the master stage.
* A song's control is decided by its **number**, not by the music player it plays on: below `START_MUS` (350) a sound
  effect, from it on music. The fanfares and jingles play on sound effect player 2 but are music (22 of them, plus the
  bard's 51 phonemes). Cries are the two cry players' (`SetPokemonCryTone`).
* Each mixer channel takes the category of the note it plays when the note starts, so music, effects and cries are
  scaled per channel in the mixers (`sound_mixer.c` for the 12 sample channels, `cgb_audio.c` for the 4 GB channels).
  The master, the x4 make-up gain of decision #23 and the clamp to [-1, 1] stay where they were (`Platform_QueueAudio`).
* Every gain is at most 1: no sound is louder than before (the audit's worst case, the loudest music plus the loudest
  effect at 0.86 of full scale, still holds for any mix of the controls).
* **At 100% a channel is mixed by the code that mixed it before**, so with every control at 100% the sound is bit for
  bit the old build's: the whole song library (all 609 song numbers, 30 frames each, 18,880 frames) gave the same
  FNV-1a hash of every queued sample from the build before the change and from this one, on Linux.
* The audio audit (`PKMN_DEBUG_SCENE=audio`) measures with music, effects and cries at 100% whatever the settings file
  says, so its numbers compare with `docs/visual-audio-audit.md`.

## Tests

* Engine `make -f Makefile_pc NATIVE_LINUX=1 DIORAMA=1 BFX_TEST=1 check-audio-volumes` (`--selftest-audio-volumes`,
  `src/platform/native_selftest_audio.c`): the categories of all 610 song numbers, the fanfares on sound effect player 2,
  a player keeping the category of the song it really plays; a music song, a sound effect, a fanfare and a cry through
  the game's mixer at levels of their control and the master (every sample level/10 of the 100% mix, 0% silent, 100%
  through the unchanged path, the other controls changing nothing); the settings file as the game reads and writes it
  (the app tests' cases); the F10 Audio page through its keys (heard at once, saved).
* Engine `check-native`: the menu model's Audio page (`tools/pc_port/tests/test_display_settings.c`).
* App: `tests/test_game_display_settings.py` (reading, writing, the older-file rule, junk), `tests/test_shell_app.py`
  (the in-game menu's audio screen), `tests/test_launcher_menu.py` (the launcher's audio page; under `xvfb-run`).
* Results 2026-11-05 (Linux): `--selftest-audio-volumes` 98 checks, 0 failed (3D test build); `check-native` all pass
  (`test_display_settings` 375 checks, 307 before); `check-game-sections` passes; the library comparison above; the
  3D game on Xvfb read an older file (music 70%, cries 100%) and F10 > Audio changed and saved the volumes; the GBA ROM
  is unchanged (f214735b...3387); MinGW compiles.

## Not verified

* By ear: whether 70% music sits well against the effects and cries on real speakers (decision #23's +6 dB make-up
  gain is unchanged).
* Windows: compiled (MinGW) only; nothing run there. The 100% path's bit-for-bit claim was checked on Linux only.
