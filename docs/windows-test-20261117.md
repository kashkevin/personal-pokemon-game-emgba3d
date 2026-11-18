# Release tests on your own PCs, step by step (2026-11-17, revised 2026-11-18)

The tests that only a real PC can do: an upgrade over your saves, a fresh install, controllers, the graphics card's
benchmark, two PCs on one network, two PCs over the Internet and a long session; then the sprite pack and the slopes. Everything a
machine without a graphics card, a controller or a second PC could do was done first (end of this page). Nothing here
has been tried on a real PC yet: each box is open until you tick it.

The installer to test: **CI-482** (`EmeraldTogether-Setup-Native-3D-CI-482.exe`, engine `25eb56eb`; run 482 of
2026-11-18: **all 93 jobs passed**, the update from CI-479 with players' saves among them; its SHA-256 in step 0.4):
run 479's build with the launcher fixes of the verification audit (`docs/verification-audit-20261117.md`) and the
prompts in each controller's own buttons (`docs/package-20261118b.md`). It is for your
own PCs only; please do not pass it on. About 2-3 hours in all; tests 1-4 need one PC, tests 5-6 two.

When something goes wrong: note the time and what you did, press **F12** in the game for a picture (saved in
`Pictures\EmeraldTogether`), and keep `%LOCALAPPDATA%\PokemonPrivate\shell\last-error.txt` and the newest folder in
`%LOCALAPPDATA%\PokemonPrivate\launcher\launches\` (its `runtime.log`, and `crash.log` after a crash).

## 0. Get the installer (5 minutes, once)

1. Signed in to GitHub, open <https://github.com/kashkevin/personal-pokemon-game-emgba3d/actions/runs/44230553383>.
2. Scroll to **Artifacts** and click **EmeraldTogether-Windows-Installer** (a zip of about 59 MB). GitHub keeps it 7
   days after the run (until about 2026-11-25).
3. Right-click the zip > **Extract All** > **Extract**.
4. Check the file: press Win+R, type `cmd`, Enter, and paste (the folder is where the zip was extracted):

   ```
   certutil -hashfile "%USERPROFILE%\Downloads\EmeraldTogether-Windows-Installer\EmeraldTogether-Setup-Native-3D-CI-482.exe" SHA256
   ```

   The second line it prints must be `7fc796f9efbee3af5ff6ca7e89d2ee5d2dd84d381bcf95a246a8c53ab715a87b` (the file is
   59,065,499 bytes). If not, stop and tell me.
5. Copy the exe to each PC you test on (USB stick or a shared folder).
6. The installer is not signed: Windows may say "Windows protected your PC". Click **More info** > **Run anyway**.

## 1. Back up first (each PC, 2 minutes)

1. Close EmeraldTogether completely (Task Manager shows no `EmeraldTogether.exe` and no `pokeemerald-mp*.exe`).
2. Press Win+R, type `%LOCALAPPDATA%`, Enter.
3. Copy the folder **PokemonPrivate** and paste it on your Desktop; rename the copy `PokemonPrivate-backup`.
   Setup and the uninstaller never touch this folder; the copy is only for a disaster.

## 2. Test A: the upgrade over your saves (main PC, 20 minutes)

Before installing:

1. Count the spare copies of world saves. Right-click Start > **Terminal** (or **Windows PowerShell**) and paste:

   ```
   Get-ChildItem "$env:LOCALAPPDATA\PokemonPrivate\launcher\players" -Directory | Get-ChildItem -Directory | ForEach-Object { "{0,5}  {1}" -f (Get-ChildItem $_.FullName -Filter *.export.json).Count, $_.FullName }
   ```

   Each line is one world and player: the number of copies and the folder. Keep the window open.

Install and check:

2. Double-click the Setup file and click through it. It replaces the installed version; it keeps your files.
3. Start EmeraldTogether. Expected: the main menu with all your characters; possibly a green line "Your latest progress
   was picked up".
4. Paste the counting command again. Expected: every folder that had more than 40 now has exactly **40**; the others
   are unchanged. (At most 200 are removed each time EmeraldTogether starts: a folder that had more than 240 needs
   another start - close and reopen, count again.)
5. For each character: **Solo** (and each world you host): it comes back exactly where it last saved, with its party.
   A world you host asks once to get ready for the new version (it makes a backup first) - say yes.
6. Play five minutes, save in the game (START > SAVE), close the game, open it again, **Continue**: the same place.
7. If you play a world with a friend: once both PCs are upgraded, both can join; a PC still on the old version is
   refused with "Different game versions".

## 3. Test B: a fresh install (a second PC, or a new Windows account on this one; 20 minutes)

A PC that never had EmeraldTogether is best. Otherwise make a test account: Settings > Accounts > **Other users**
(or Family & other users) > **Add account** > "I don't have this person's sign-in information" > "Add a user without a
Microsoft account" > name it `ETtest` > Next. Sign out, sign in as `ETtest`.

1. Run Setup there and start EmeraldTogether. Expected: it checks the graphics card and uses the 3D view (or, on a card
   too old for OpenGL 3.3, offers Classic 2D).
2. Make a new character: the short introduction, choose a starter, then START > SAVE in the game. The hint at the
   top reads "Press START, then PLAYER, then STYLE".
3. Close the game and EmeraldTogether, start again, **Solo** > the character: the same place and party.
4. Settings > Apps > Installed apps > EmeraldTogether > **Uninstall**. The folder `%LOCALAPPDATA%\PokemonPrivate` is
   still there. Run Setup again: the character is still there and plays.
5. Afterwards you can delete the `ETtest` account (Settings > Accounts > Other users > ETtest > Remove).

## 4. Test C: controllers (10-15 minutes)

An Xbox controller (or any pad Windows calls an Xbox controller):

1. Plug it in, then start EmeraldTogether. The menu moves with the d-pad; **A** chooses, **B** goes back.
2. In the game: the d-pad and the left stick walk; **A** talks and confirms; **B** and **X** cancel; **Start** opens
   the menu; **Back** is Select; **LB/RB** are L/R; **Y** opens the details view in menus.
3. A multiplayer question (a trade or a challenge): B answers No and never confirms; in a trade window B asks
   "Cancel the trade?".
4. Unplug it while walking, plug it back in: it works again without restarting.

A PlayStation (DualShock 4, DualSense) or Switch Pro controller - **new in this build** (KNOWN_ISSUES MS-252; before
it, such a pad worked only in the menu):

5. Unplug the Xbox controller (while one is connected, the game reads only it). Connect the other pad by USB or
   Bluetooth and start EmeraldTogether.
6. Repeat 1-4. PlayStation: **Cross** = A, **Circle** and **Square** = B, **Triangle** = details, **Options** = Start,
   **Share/Create** = Select, **L1/R1** = L/R. Switch Pro: **A** (right) = A, **B** and **X** = B, **Y** = details,
   **+** = Start, **-** = Select.
7. The on-screen button hints in the 3D view show your controller's own buttons: a PlayStation pad's cross, square and
   triangle, OPTIONS and SHARE (CREATE on a DualSense), L1/R1; a Switch Pro's A, B, +, -; an Xbox pad's letters.
8. Only if that pad misbehaves: close EmeraldTogether, open `cmd` and type
   `set PKMN_SDL_CONTROLLERS=0`, Enter, then `"%LOCALAPPDATA%\Programs\EmeraldTogether\EmeraldTogether.exe"`, Enter. The
   game then ignores everything but an Xbox controller. Tell me what happened.

## 5. Test D: the graphics card's benchmark (10 minutes, then 10 minutes of play)

1. Close EmeraldTogether.
2. Copy the save of a character who stands outdoors: `%LOCALAPPDATA%\PokemonPrivate\characters\<character>\current.sav`
   (one folder per character) to your Desktop and rename the copy `bench.sav`. The benchmark never saves; the copy
   only keeps the real save out of reach.
3. Open `cmd` and paste (one line):

   ```
   "%LOCALAPPDATA%\Programs\EmeraldTogether\_internal\runtime\pokeemerald-mp-diorama.exe" --save "%USERPROFILE%\Desktop\bench.sav" --benchmark 15 --bench-log "%USERPROFILE%\Desktop\benchmark.log"
   ```

4. The game opens, continues the save by itself, measures the 3D view at 1280x720, 1920x1080, 2560x1440 and 3840x2160
   (offscreen when the screen is smaller) with VSync off, and closes by itself after a few minutes. Don't touch it.
5. Send me `benchmark.log` from the Desktop (average frame rate, the 1 % and 0.1 % lows, frame times, the graphics card
   and processor). The targets: 200+ fps at 1080p and 1440p, 180-200+ at 4K, 60+ on a low-end PC.
6. Then play ten minutes normally with **F10** > **Show frame rate** on: run from Mauville west into Route 117 and east
   into Route 118 (nothing popping in at the map edges, no hitch where maps meet); fight a battle; walk around
   Lilycove. In F10 set **Graphics quality** to Low and to Medium once each and look around.

## 6. Test E: two PCs on the same network (30-45 minutes)

1. PC 1: **Host World** > choose a world > open it to friends. It shows an invite code: send it to PC 2 (a message,
   a USB stick).
2. PC 2: **Join Friend** > join a new one with an invite code > paste it > choose a character > join.
3. Both: you see each other walk; **PLAYERS** lists the other. PC 2: in the launcher tick "Share my location with other
   players", then walk into a town. PC 1: **START > POKENAV > World > Players and weather** names that town (for
   example "LITTLEROOT", the whole "LITTLEROOT TOWN" on PC 2's own page there), never "Area" and two numbers
   (KNOWN_ISSUES MS-5; checked on Linux 2026-11-18).
4. A trade (PLAYERS > the other > trade): the Pokemon arrive on both sides; both save; reopen: still traded.
5. A battle (PLAYERS > the other > challenge): it runs to the end; both back on the field.
6. A co-op battle (a Gym battle together, or the Tower Duo): in it choose **GIVE UP**: it first asks "Giving up ends
   this battle for both players."; **No** goes back to the battle; then Yes: the team's loss on both PCs.
7. Closing a game during a co-op battle: about 20 seconds in, close PC 2's game window. For 3 minutes PC 1's launcher
   refuses Abandon and says why. Start PC 2 again and open the world: the battle ends as the team's loss naming PC 2
   ("BATTLE TOGETHER LOST" on both); parties, items and money as before the battle.
8. Both stand in the same Pokemon Center with their partner Pokemon following; heal at the counter: no crash,
   nothing garbled.
9. If you have them: a third and a fourth PC join the same way.
10. A new network address for PC 1 (KNOWN_ISSUES WC-2: never tried on real PCs): close both games and launchers;
    give PC 1 a new address - switch it between Wi-Fi and a cable, or restart the router (in `cmd`, `ipconfig`
    shows the IPv4 Address before and after; it must differ). PC 1: **Host World** again with the same world: it
    opens on the new address. Send PC 2 a new invite code; PC 2 joins with it: you see each other again.

## 7. Test F: two PCs over the Internet (30 minutes)

1. PC 1 (at home): **Host World** > the world > **Network settings**: **Internet access** > turn on (it explains and
   asks first); **Automatic router setup** stays on. Host the world; allow EmeraldTogether when Windows Firewall asks.
   The hosting window shows a line "Router: ..." - write it down: it says whether your router opened the port by
   itself.
2. Send PC 2 a new invite code (made after Internet access was turned on).
3. PC 2 on another network - a phone's hotspot is easiest - **Join Friend** with that code.
4. A trade and a battle. Watch the battle: the turns should not stall between actions. Note how long a turn takes.
5. If joining fails: write down the exact message (it names the reason and what to do on each side). If the router
   refused, forward the port shown in Network settings to PC 1 in the router's page; behind CGNAT (the "Router:" line
   says so) a forward cannot work - then the relay or Tailscale (`HOSTING.txt` in
   `%LOCALAPPDATA%\Programs\EmeraldTogether` explains both).

6. Optional, for a friend behind CGNAT (KNOWN_ISSUES NU-4): the same join over Tailscale (both PCs in your Tailscale
   network; choose the PC's Tailscale address as the world's address) and through a relay you run yourself
   (`HOSTING.txt` explains both). Each should connect and play a battle or a trade.

## 7b. Test G: a long session's speed and sound (1-2 hours of ordinary play; KNOWN_ISSUES MS-89)

1. Close EmeraldTogether. Open `cmd` and type:

   ```
   set PKMN_PERF_LOG=1
   set PKMN_DIORAMA_PROFILE=1
   "%LOCALAPPDATA%\Programs\EmeraldTogether\EmeraldTogether.exe"
   ```

2. Play normally for one to two hours in the 3D view (walking, battles, menus). Note if the game gets laggier or the
   sound falls behind the picture.
3. Close the game, then send me the newest folder's `runtime.log` from `%LOCALAPPDATA%\PokemonPrivate\launcher\launches\`
   (every 5 seconds it records the frame rate, the drawing time and the sound queue).

## 8. The sprite pack (only if you have `battle-sprites.ebsp`; 10 minutes)

The CI installers carry no sprite pack, so their battles draw the game's own GBA sprites. To test yours:

1. Close EmeraldTogether. Open `cmd` and type (your pack's real path):

   ```
   set PKMN_BATTLE_SPRITES_PACK=C:\path\to\battle-sprites.ebsp
   set PKMN_BATTLE_SPRITES_LOG=1
   "%LOCALAPPDATA%\Programs\EmeraldTogether\EmeraldTogether.exe"
   ```

2. In the 3D view, start a wild battle: both Pokemon are the pack's animated sprites.
3. Press **F4** (the classic view) during a battle, or play a Classic 2D game: the battles draw the GBA sprites (your
   #77).
4. A Spinda: its own GBA picture with its own spots (your #76).
5. Send the newest `launcher\launches\...\runtime.log`: its "battle sprites" lines say which picture each battler used
   and why.

## 9. The slopes (5 minutes)

Jagged Pass with the Acro Bike: its bumpy slopes are now smooth ramps (your #71) - ride up and down; the rider stands
on the slope, nothing sinks or floats, and you can stop and turn as before. The Mach Bike's muddy slopes (Route 111,
115, 119) keep their steps. To compare: `set PKMN_DIORAMA_SMOOTH_SLOPES=0` before starting (all steps) or `=1` (the mud
smooth too), as in test C, step 8.

## What to send back

- `benchmark.log` (test D) and the long session's `runtime.log` (test G).
- The save-copy counts before and after (test A).
- For each test: done / failed, with the notes and files named at the top of this page for anything that failed.

## Done here first (not a substitute for the above)

- **Controllers** (MS-252): a virtual SDL controller through the game's real event loop, 63 of 63 checks (every
  button, the stick, a quick tap, unplugging while held), in the Linux 3D and Classic builds; a real game walked and
  used its START menu with only that controller (its d-pad, then its stick), the same as with the keyboard. On
  Windows the same self-test passed in runs 479 and 482 (63 of 63), and in the 3D game in run 482 (68 of 68: the
  prompts' buttons for a DualShock 4, a DualSense and a Switch Pro among them).
- **Benchmark**: the exact command of test D run end to end (Linux, software OpenGL): it continued the save, measured
  every resolution and wrote the log.
- **Upgrade and fresh install**: every full run installs, starts, repairs and uninstalls the installer on a Windows
  runner, updates from the previous run's installer with two players' worlds and plays on from those saves, and does
  it again under a user folder named "José 测试" (run 482: all passed, the update from CI-479 among them).
- **Multiplayer**: 2-4 real games through real launchers on one machine (Linux and Windows runners): trades,
  battles, co-op, the Battle Tower, interrupted battles. Never between separate PCs or across a real router.
- **Sprite pack**: a stand-in pack of plain shapes, in the 3D and Classic test builds: the pack in 3D battles, the
  GBA sprites in 2D, Spinda's own spots, Role Play's and Snatch's pictures.

The earlier, longer checklist (`docs/windows-test-20261106.md`) still holds for what it lists.
