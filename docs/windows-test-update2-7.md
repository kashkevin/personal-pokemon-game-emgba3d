# EmeraldTogether: Windows test checklist for the Update 2-7 build

For the owner's PCs. **Nothing below has been run on a real PC.** Every feature was tested only in the cloud by unit tests,
engine self-tests and a real host with scripted game bridges (see `DEVELOPMENT_LEDGER.md`, Updates 2-7, and
`docs/automated-validation-matrix.md`). This list is what a human with a graphics card, a keyboard, speakers and a
second PC must still check. Older checks that still apply: `docs/expansion-windows-test.md`.

How to use: tick a box, or write what you saw. Take a screenshot (Win+Shift+S) and note the time of anything odd.
Rows marked **NEW** are features of this build. Rows marked **REGRESSION** guard earlier work.

Package: the private GitHub Actions artifact named in `DEVELOPMENT_LEDGER.md` (O6). Unzip it, run the launcher. The
package has no game data: import your own game once (**Set up a world or character**).

## 0. First run (one PC)

- [ ] Launcher opens; **Help** opens; no antivirus/SmartScreen block that cannot be passed with "Run anyway".
- [ ] Import your own game file: the launcher accepts the right one and refuses a wrong one with a clear message.
- [ ] **Graphics mode** (**REGRESSION**): 3D starts on a PC with a normal GPU driver; choosing Classic 2D starts the 2D
      game; on a PC/VM with no OpenGL 3.3 you are *asked* and Classic 2D starts (the 3D game never just vanishes).
- [ ] Window: 1920x1080, F11 fullscreen on and off, resize, a 125% / 150% DPI display looks right (not blurry or cut off).
- [ ] Frame rate is steady (F10 shows the limit; try 60 and the display's rate). Note the lowest frame rate you see.

## 1. Controls and sound (**REGRESSION**, never tried on a real PC)

- [ ] Main menu **Settings > Controls** (Update 30; it was Launcher Help > Game keys): choose A, press Q, start a game: Q is A; the default Z no longer is. Restore defaults.
- [ ] In the 3D game F10 > **Controls**: rebind, a conflict asks to swap, Esc and F1-F12 are refused, the on-screen prompts show the new key.
- [ ] There is **no** fast-forward any more (Update 30): Space and the right trigger do nothing special, and no Controls page row offers one.
- [ ] **Controller:** an Xbox-style pad (XInput): D-pad/left stick move, A = A, left face button (X) = B, Start, Back =
      Select, shoulders = L/R, Y = details view in menus (the right trigger no longer speeds the game up). A PlayStation/Switch pad is **not**
      supported (write down what happens; do not expect it to work).
- [ ] **Sound:** music and cries play in the overworld and in battle, no crackling; changing windows or minimising and returning keeps sound.

## 2. One player

- [ ] Continue your save: your party, items, position are as you left them (**existing saves**). Save in game, close, reopen: still there.
- [ ] Walk to a route: shared wild Pokémon appear; a battle, a catch and a run behave as in `docs/expansion-windows-test.md` A.
- [ ] **Exp. Share** (**REGRESSION**): win a wild battle with only your lead: the rest of the team gains half.
- [ ] **Breeding (NEW check of old code):** leave two compatible Pokémon at the Day Care (Route 117), walk; take the egg.
      Walk about 257 steps per egg cycle with the egg in the party: it hatches (a level 1 Pokémon). With a Magcargo
      (Flame Body) in the party it hatches faster. An egg cannot be offered in a trade.
- [ ] **Mega Evolution:** after the 4th badge (Mega Ring) buy a Mega Stone at Mauville Mart (60,000 each); hold it, battle, Mega Evolve once.

## 3. Two PCs: host and friend

(Host address on this PC = its LAN address, not 127.0.0.1; the friend joins with their invitation.)

- [ ] Both see each other walk; both see the same wild Pokémon; a claim race has exactly one winner (`expansion-windows-test.md` B).
- [ ] **Disconnect/reconnect:** the friend closes the game (not the launcher) and reopens; later the friend loses Wi-Fi for 20 seconds and returns: world and save are intact, nothing is duplicated.
- [ ] **Host restart:** the host closes everything and starts again; the friend reconnects; shared Pokémon and events are still there.
- [ ] **Trade (REGRESSION):** trade one Pokémon each way; both saves keep the right Pokémon; try an egg: it is refused.
- [ ] **Co-op battle experience (REGRESSION):** team up (PLAYERS > player > Invite to team), fight a trainer or Gym together: both teams' Pokémon gain Exp once per defeated Pokémon, never in a player-versus-player battle.
- [ ] **1v1 and wager (REGRESSION):** challenge, accept, optional money wager, battle to the end; the Trainer Card records the result.

## 4. Four PCs (or two PCs with two games each if they can run)

- [ ] 2v2 team battle between two teams of two; a Pokémon of each of the four players Mega Evolves once (each trainer has their own Ring).
- [ ] Interrupt a 2v2 battle (close one game, then reopen it): the battle can be recovered or ends cleanly with nobody losing a Pokémon. Write down the time it took.
- [ ] Battle speed over your real network: note any pause longer than 3 seconds between turns (**M25**).

## 5. NEW: Secret Bases (two PCs)

- [ ] Player A makes a Secret Base (a secret-base spot: a cave hole, a tree, a bush; use the PC in the base).
- [ ] Player B opens **START > PLAYERS > World and my base** (or any menu page): after a minute B can find A's base
      (the PC's *registry*, or by walking to the same spot: it opens as a friend's base) and enter it. Decorations are as A placed them. The owner's party is the trainer to battle.
- [ ] A redecorates; after A saves/re-enters, B sees the change within a minute (B may need to leave and re-enter the base).
- [ ] A chooses **My Secret Base > Visible to: Teammate** (or Nobody): B no longer finds the base after the next sync; choose Everyone again: it returns.
- [ ] A removes the base (the PC's "Delete" option): B loses it. B's own base is never changed by A.

## 6. NEW: PokéNav-style World pages

- [ ] **PLAYERS > World and my base > Players and weather** lists each player with the area name; open one: the weather there (rain, sunshine, ...) matches what that player sees. Names fit; nothing runs off the row.
- [ ] During a mass outbreak and a World Event, the matching row names the species/place and the countdown is right; it says "Nothing right now" otherwise.

## 7. NEW: Dormant legendary events

Quick test: close the launcher, create `world.sqlite3.events.json` next to `world.sqlite3` (the same folder as the
outbreak file) containing

```json
{"first_delay": [60, 60], "interval": [300, 300], "duration": 900, "condition_chance": 1.0,
 "category_weights": {"legendary": 100}}
```

The first event then comes after 1 minute online and is always a legendary that starts asleep. Delete the file for
normal timing (a mistake in it stops the host with a message naming the file).

- [ ] A banner pair appears: "Something stirs near <PLACE>" then "It wakes at night / in the rain / in a sandstorm / by day / at dusk / when trainers gather". The World page shows "Event: Something stirs" and, inside it, the condition, without naming the species. Nobody sees the Pokémon on the map yet.
- [ ] Meet the condition (two players stand on the place's map for "when trainers gather"; wait for the hour for night/day/dusk; walk through rain or the desert's sandstorm for those): the legendary appears at the place with the usual "WORLD EVENT!" banner and at least 5 minutes remain. First catch wins as before; the catcher keeps it, it is gone for everybody.
- [ ] If nobody meets the condition in time: "The legend slipped away / before it woke..." and later another event starts.

## 8. NEW: Championship entry rules (optional host file)

- [ ] On the host, create `world.sqlite3.frontier.json` next to `world.sqlite3` containing `{"fixed": "level_50"}`; restart the host. PLAYERS > World shows "Rule: Level 50".
- [ ] Four players propose a Championship with one Pokémon above level 50: the proposal is refused with "<name>: Over level 50"; with the party fixed, it is accepted. Remove the file for normal play (a mistake in the file stops the host with a message naming it).

## 9. Clean exit

- [ ] Closing the game then the launcher leaves no stuck process (Task Manager) and a second launch works.
- [ ] Note anything that crashed: the game writes `crash.log` beside the program; keep it with the screenshot.
