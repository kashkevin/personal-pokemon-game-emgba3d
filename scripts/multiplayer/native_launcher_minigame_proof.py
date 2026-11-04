"""The wireless minigames between two to four of a world's players through the whole launcher (KNOWN_ISSUES MS-141c).

--activity berry_crush (the default):
    1. Both linked; each game Continues at a Pokemon Center 2F below the Direct Corner's attendant (make_tower_saves.py's
       crush-a and crush-b: a POWDER JAR and Berries, the POKEDEX's flag).
    2. Each talks to the attendant, chooses WORLD PLAYERS ("Play BERRY CRUSH with players in this world, or with
       computers?") and saves (the game's own questions); the Players menu opens on BERRY CRUSH's lobby.
    3. The host leads a group; the friend's lobby shows it and the friend joins ("Join <host> 1/4"); the host's page then
       offers "Start with 2 players" and the host starts it: both windows close and both games walk into the link room.
    4. The game over the world, the host's game its parent: each picks a Berry from the Bag, the crush (A pressed as a
       player presses it), the results, the save, "Want to play BERRY CRUSH again?" - the host YES, the friend NO - and
       both games close the link and are back on their 2F with no communication error; the host's group is gone,
       nobody was told it was lost, every link frame went through the host.
    5. As every launcher proof: the launcher's saves, a fresh Continue, the canonical saves and parties unchanged.

--activity pokemon_jump:
    1. Both linked; each game Continues in Mossdeep City's minigame building, across the counter from the old man
       (make_tower_saves.py's jump-a and jump-b: a Pikachu, a Marill).
    2. Each talks to the old man, chooses POKEMON JUMP, enters its Pokemon (the party's first), chooses WORLD PLAYERS
       ("Play with players in this world, or with computer partners?") and saves; the Players menu opens on POKEMON
       JUMP's lobby.
    3. As Berry Crush's: the host leads, the friend joins, the host starts with 2 players; both walk into the room.
    4. The game, the host's game its parent: the names, the countdown, then both players jump the vine (A as the vine
       comes down, as a player times it) for a few swings and then stop, so the vine catches them; each game's score
       (the leader's, sent to the member), "Play again?" - the host YES, the friend NO - "...dropped out", both games
       close the link and walk out of the room with no communication error.
    5. As Berry Crush's.

--activity dodrio (three players: --source-c and a third --display):
    1. Each game Continues where Pokemon Jump's do (make_tower_saves.py's dodrio-a, -b and -c: a Dodrio each).
    2. Each chooses DODRIO BERRY-PICKING, enters its Dodrio, WORLD PLAYERS, saves; the lobby opens.
    3. The host leads, both friends join, the host starts with 3 players (the game's minimum).
    4. The game, the host's game its parent: each player picks (UP, the Dodrio's middle head, again and again) until
       ten Berries have fallen, the results (A through their pages: the scores sent between the games as link blocks),
       "Want to play again?" - the host YES, the friends NO - and all three close the link and walk out of the room.
    5. As Berry Crush's.

--players 3 or 4 (a world's most; --source-c, --source-d and a --display each): the same with more friends, each
joining in turn ("Join <host> 2/4", "3/4"), the host starting with them all, every friend a member answering NO; Pokemon
Jump's checks then read every player's jumps (each game shows every other player's), the score the same in all games
(make_tower_saves.py's crush-c and -d at two more Pokemon Centers' 2F, jump-c, -d and dodrio-d where the others are).

What the games do is read from their memory (the attendant's choice, the save's questions, the Players menu, the
minigame's current step, from the game's debug information where a structure is read: minigame_facts.py); keys are
pressed as a player presses them (xdotool on Linux; on Windows, the keyboard's messages to each game's own window, as
the other Windows proofs press them). Pictures for a person: OUT/pictures.

Windows (the CI runner, the release's Windows game, no X displays): --sdl, --pe-symbols and --sizes as the other
Windows proofs, and --minigame-facts (minigame_facts.py of the game before its strip); no --display.

    PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime \\
      python scripts/multiplayer/native_launcher_minigame_proof.py \\
        --game ../engine/pokeemerald-mp --rom pokeemerald.gba --manifest manifest.json \\
        --source-a crush-a.sav --source-b crush-b.sav --display :94 --display :95 \\
        --output /private/multiplayer-proof/native-launcher-minigame-1 [--activity pokemon_jump | dodrio --source-c ..]
        [--players 4 --source-c crush-c.sav --source-d crush-d.sav --display :96 --display :97]
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows-runtime"))
from minigame_facts import BERRY_CRUSH_STEPS, MULTICHOICE_TASKS, game_facts  # noqa: E402
from native_launcher_battle_proof import KEYS, WINDOWS, game_picture, launcher_proof  # noqa: E402
from qualify_admission_cleanup import on_worker, require  # noqa: E402

A, B, UP, DOWN = 1, 2, 64, 128
# Pokemon Jump's phases (src/pokemon_jump.c, FUNC_*: the index in its leader's and members' tables)
JUMP_PHASES = ("GameIntro", "WaitRound", "GameRound", "GameOver", "AskPlayAgain", "ResetGame", "Exit", "GivePrize",
               "Save")
MONSTATE_JUMP = 1
VINE_DOWNSWING_LOWER, VINE_UPSWING_LOWER = 4, 6
RENDER_STATE_CLEAR, RENDER_STATE_SCROLL_START = 2, 3    # a text printer waiting for a press (include/text.h)
JUMPS = 6                                               # each player's jumps before letting the vine catch it
# Dodrio Berry Picking's phases (src/dodrio_berry_picking.c, FUNC_*)
DODRIO_PHASES = ("Intro", "InitCountdown", "Countdown", "WaitStart", "PlayGame", "InitResults", "Results",
                 "AskPlayAgain", "EndLink", "Exit", "ResetGame", "WaitEndGame")
DODRIO_RESULTS = 6                                      # each player's Berries blue, green, gold, missed, prize, in a row
# least: the game's (minigame_protocol.ACTIVITIES); names: a world's players in order (a world has four at most)
ACTIVITIES = {
    "berry_crush": dict(title="BERRY CRUSH", least=2, names=("Crush Host", "Crush Friend", "Crush Third", "Crush Fourth")),
    "pokemon_jump": dict(title="POKEMON JUMP", least=2, names=("Jump Host", "Jump Friend", "Jump Third", "Jump Fourth")),
    "dodrio": dict(title="DODRIO BERRY-PICKING", least=3, names=("Pick Host", "Pick Friend", "Pick Third", "Pick Fourth")),
}
GAME_SECONDS = 420


class Game:
    """What one game is doing, read from its memory at the build's facts (minigame_facts.py). Three kinds of read: a
    variable at the build's own address (static: the Windows game is moved where Windows loaded it), memory a pointer
    of the game's points at (heap: as it is), and a code pointer compared with the build's functions (code: moved
    back by the same distance on Windows)."""

    def __init__(self, facts, activity):
        self.activity = activity
        functions, data, structs = facts["functions"], facts["data"], facts["structs"]

        def fn(*names):
            return frozenset(a for name in names for a in functions.get(name, ()))
        self.multichoice = fn(*MULTICHOICE_TASKS)
        self.save_questions = {**{a: "save?" for a in fn("SaveConfirmInputCallback")},
                               **{a: "overwrite?" for a in fn("SaveOverwriteInputCallback")}}
        self.save_dialog = data["sSaveDialogCallback"]
        self.link_active = data["sLocalLinkActive"]
        self.link_error = fn("CB2_LinkError")
        self.overworld = fn("CB2_Overworld")
        self.first_printer = data["sFirstTextPrinter"]
        self.main = data["gMain"]
        self.printer_fields = structs["TextPrinter"]
        found = (self.first_printer and self.multichoice and len(self.save_questions) == 2 and self.save_dialog
                 and self.link_active and self.link_error and self.overworld and len(self.main) == 1)
        if activity == "berry_crush":
            self.steps = {address: name for name in BERRY_CRUSH_STEPS for address in functions.get(name, ())}
            self.crush_games = data["sGame"]
            self.bag = fn("CB2_BagMenuRun", "CB2_Bag")
            found = found and len(self.steps) >= len(BERRY_CRUSH_STEPS) and self.crush_games and self.bag
        elif activity == "pokemon_jump":
            self.jump_game = data["sPokemonJump"]
            self.jump_screen = fn("CB2_PokemonJump")
            self.party_menu = fn("CB2_UpdatePartyMenu")
            self.jump_fields = structs["PokemonJump"]
            found = found and len(self.jump_game) == 1 and self.jump_screen and self.party_menu
        else:
            self.dodrio_game = facts["statics"]["dodrio_berry_picking.c::sGame"]
            self.dodrio_screen = fn("CB2_DodrioGame")
            self.party_menu = fn("CB2_UpdatePartyMenu")
            self.dodrio_fields = structs["DodrioGame"]
            found = found and self.dodrio_screen and self.party_menu
        require(found, "the native game lacks the symbols this proof reads: build it unstripped")

    @staticmethod
    def static(probe, address, size):
        """`size` bytes of a variable at the build's own address."""
        if WINDOWS:
            return probe.memory.read(address, size)
        with open(f"/proc/{probe.pid}/mem", "rb", buffering=0) as memory:
            memory.seek(address)
            return memory.read(size)

    @staticmethod
    def heap(probe, address, size):
        """`size` bytes where a pointer the game holds points."""
        if WINDOWS:
            return probe.memory._raw(address, size)
        with open(f"/proc/{probe.pid}/mem", "rb", buffering=0) as memory:
            memory.seek(address)
            return memory.read(size)

    def word(self, probe, address):
        return int.from_bytes(self.static(probe, address, 4), "little")

    def heap_word(self, probe, address):
        return int.from_bytes(self.heap(probe, address, 4), "little")

    @staticmethod
    def code(probe, value):
        """A code pointer the game holds, as the build's own address (the facts' numbering)."""
        return probe.code(value & ~1)

    def callback2(self, probe):
        return self.code(probe, self.word(probe, self.main[0] + 4))

    def multichoice_shown(self, probe):
        tasks = probe.mem("gTasks", 640)
        return any(tasks[o + 4] and self.code(probe, int.from_bytes(tasks[o:o + 4], "little")) in self.multichoice
                   for o in range(0, 640, 40))

    def text_waiting(self, probe):
        """Whether a text box waits for a press: the arrow at a paragraph's or a line's end (the message goes on)."""
        f, printer = self.printer_fields, self.word(probe, self.first_printer[0])
        for _ in range(64):                                # the game's list of text printers
            if not printer:
                return False
            data = self.heap(probe, printer, f["nextPrinter"] + 4)
            if data[f["active"]] and data[f["state"]] in (RENDER_STATE_CLEAR, RENDER_STATE_SCROLL_START):
                return True
            printer = int.from_bytes(data[f["nextPrinter"]:f["nextPrinter"] + 4], "little")
        return False

    def save_question(self, probe):
        return self.save_questions.get(self.code(probe, self.word(probe, self.save_dialog[0])))

    def crush(self, probe):
        """Berry Crush's current step (its command's name, the command's state), or None outside Berry Crush."""
        for address in self.crush_games:
            game = self.word(probe, address)
            if game:
                try:
                    step = self.steps.get(self.code(probe, self.heap_word(probe, game + 4)))
                except OSError:
                    continue                               # another file's sGame, not a pointer
                if step is not None:
                    return step, self.heap(probe, game + 12, 1)[0]
        return None

    def jump(self, probe, count):
        """Pokemon Jump's state while its screen runs (its structure is freed, not cleared, at its end), else None:
        the phase, the phase's helper state, the vine's state, whether this game leads, the score, the swings cleared,
        and each of the `count` players' Pokemon's state (jumping or not)."""
        if self.callback2(probe) not in self.jump_screen:
            return None
        game = self.word(probe, self.jump_game[0])
        if not game:
            return None
        f = self.jump_fields
        data = self.heap(probe, game, f["comm.jumpScore"] + 4)          # the structure's head
        stride = f["players[1].monState"] - f["players[0].monState"]   # one player's entry in its players[]
        mons = [int.from_bytes(self.heap(probe, game + f["players[0].monState"] + i * stride, 2), "little")
                for i in range(count)]
        phase = data[f["comm.funcId"]]
        return dict(phase=JUMP_PHASES[phase] if phase < len(JUMP_PHASES) else phase,
                    helper=int.from_bytes(data[f["helperState"]:f["helperState"] + 2], "little"),
                    vine=int.from_bytes(data[f["vineState"]:f["vineState"] + 4], "little"),
                    leader=data[f["isLeader"]],
                    score=int.from_bytes(data[f["comm.jumpScore"]:f["comm.jumpScore"] + 4], "little"),
                    cleared=int.from_bytes(data[f["comm.jumpsInRow"]:f["comm.jumpsInRow"] + 2], "little"),
                    mons=mons)

    def dodrio(self, probe):
        """Dodrio Berry Picking's state while its screen runs, else None: the phase, its state, whether this game
        leads, the players, the Berries missed (the gray squares) and each player's Berries eaten as this game shows."""
        if self.callback2(probe) not in self.dodrio_screen:
            return None
        game = self.word(probe, self.dodrio_game)
        if not game:
            return None
        f = self.dodrio_fields
        data = self.heap(probe, game, f["berriesEaten"] + 10)
        phase, players = data[f["funcId"]], data[f["numPlayers"]]
        eaten, table = f["berriesEaten"], f["berryResults"]

        def u16(offset):
            return int.from_bytes(data[offset:offset + 2], "little")
        return dict(phase=DODRIO_PHASES[phase] if phase < len(DODRIO_PHASES) else phase, state=data[f["state"]],
                    leader=data[f["isLeader"]], players=players, missed=data[f["numGraySquares"]],
                    eaten=[u16(eaten + 2 * i) for i in range(min(players, 5))],
                    results=[[u16(table + 2 * (DODRIO_RESULTS * i + k)) for k in range(DODRIO_RESULTS)]
                             for i in range(min(players, 5))])

    def linked(self, probe):
        return any(self.static(probe, address, 1)[0] for address in self.link_active)


async def until(predicate, timeout, what):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.05)
    return True


def _mash(probe, key, seconds, period=.11):
    """A held as briefly as a quick thumb holds it, again and again (one focus for the burst; on Windows the keyboard's
    messages to the game's window, found once)."""
    window = probe._window()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if WINDOWS:
            probe._windows.press(window, key, .045)
        else:
            subprocess.run(["xdotool", "keydown", key], env=probe.environment, check=True)
            time.sleep(.045)
            subprocess.run(["xdotool", "keyup", key], env=probe.environment, check=True)
        time.sleep(period - .045)


def _tap(probe, key):
    """One quick press to the focused window (a jump: no time lost focusing it again; on Windows to the game's
    window)."""
    if WINDOWS:
        probe._windows.press(probe._window(), key, .05)
    else:
        subprocess.run(["xdotool", "keydown", key, "sleep", "0.05", "keyup", key], env=probe.environment, check=True)


class MinigameMatch:
    def __init__(self, output, facts, activity):
        self.output, self.facts, self.activity = output, facts, activity
        self.pictures = output / "pictures"
        self.count = ACTIVITIES[activity]["least"]           # the players in the game (match sets it)
        self.reported = {}                                   # each game's last periodic report (stuck_picture)

    def stuck_picture(self, probe, slot, now, name):
        """The periodic report's picture, only when this game has not moved on since its last report (then it may be
        stuck, and a picture helps): taking one holds up every player's reading (one event loop; about a second a
        picture on Windows), which once let three games miss Dodrio Berry Picking's short EndLink (run 280)."""
        last = self.reported.get(slot)
        self.reported[slot] = now
        return self.picture(probe, name) if now == last else None

    def picture(self, probe, name):
        self.pictures.mkdir(exist_ok=True)
        try:
            return game_picture(probe, self.pictures / f"{name}.png")
        except Exception as error:  # noqa: BLE001 - a picture is for a person; the checks read memory
            return f"no picture: {error}"

    async def to_lobby(self, probe, slot, game, record):
        """The attendant (Mossdeep's old man: the game, then the Pokemon), WORLD PLAYERS, the game's own save; the
        Players menu then opens on the lobby."""
        await probe.press(UP)                              # turn to the attendant (the counter: no step is taken)
        await probe.press(A)
        # Mossdeep's old man talks in paragraphs before his question: A at each, never at the question itself
        async with asyncio.timeout(60):
            while not game.multichoice_shown(probe):
                if game.text_waiting(probe):
                    await probe.press(A, release=20)
                else:
                    await asyncio.sleep(.05)
        await asyncio.sleep(.4)
        if self.activity in ("pokemon_jump", "dodrio"):
            record("old-man-games", slot=slot, picture=self.picture(probe, f"{slot}-0-which-game"))
            if self.activity == "dodrio":
                await probe.press(DOWN)                    # DODRIO BERRY-PICKING, the second row
            await probe.press(A)                           # (POKEMON JUMP the first)
            # "Which POKEMON will you enter?" (a message that waits for A), then the party menu
            async with asyncio.timeout(60):
                while game.callback2(probe) not in game.party_menu:
                    await probe.press(A, release=30)
            await asyncio.sleep(1)
            record("enter-pokemon", slot=slot, picture=self.picture(probe, f"{slot}-0-party"))
            if game.callback2(probe) in game.party_menu:
                await probe.press(A)                       # the party's first Pokemon (it can play: the fixture's)
            await until(lambda: game.multichoice_shown(probe), 60, "the old man's world-or-computers choice")
            await asyncio.sleep(.4)
        record("attendant-choice", slot=slot, picture=self.picture(probe, f"{slot}-1-world-or-computers"))
        await probe.press(A)                               # WORLD PLAYERS, the first row
        await until(lambda: game.save_question(probe) == "save?", 60, "the save's question")
        await probe.press(A)                               # YES
        await until(lambda: game.save_question(probe) == "overwrite?" or probe.read()["active"], 60, "the save")
        if game.save_question(probe) == "overwrite?":
            await probe.press(A)                           # YES: the save it Continued from is this world's
        row, screen = await probe.ready(timeout=60)
        rows = [r.label for r in screen.rows]
        record("lobby-open", slot=slot, title=screen.title, status=screen.status, rows=rows,
               picture=self.picture(probe, f"{slot}-2-lobby"))
        title = ACTIVITIES[self.activity]["title"]
        require(screen.title == title, f"the lobby's page is {screen.title!r}, not {title!r}")
        return screen

    async def play_crush(self, probe, slot, game, record, stop):
        """Berry Crush for one player, from its memory: a Berry from the Bag, A while crushing, A through the
        results, then the host YES and the friend NO to playing again, until the game is back on the field."""
        steps, presses, mashing, entered = [], 0, 0.0, False
        last_step, last_report = None, time.monotonic()
        async with asyncio.timeout(GAME_SECONDS):
            while not stop.is_set():
                callback = game.callback2(probe)
                require(callback not in game.link_error, f"player {slot}'s game shows the communication error")
                state = game.crush(probe)
                if time.monotonic() - last_report >= 15:
                    # what the game shows and what this proof reads of it, now and then (a step that never moves)
                    last_report = time.monotonic()
                    record("berry-crush-now", slot=slot, callback2=hex(callback), step=state, presses=presses,
                           picture=self.stuck_picture(probe, slot, (callback, state),
                                                      f"{slot}-w-{len(steps):02d}-{int(last_report) % 100000}"))
                if state is None:
                    if entered and callback in game.overworld and not game.linked(probe):
                        break
                    await asyncio.sleep(.1)
                    continue
                entered = True
                step, phase = state
                if step != last_step:
                    steps.append(step)
                    last_step = step
                    pictured = step in ("Cmd_Countdown", "Cmd_PlayGame_Leader", "Cmd_PlayGame_Member", "Cmd_ShowResults",
                                        "Cmd_AskPlayAgain", "Cmd_StopGame")
                    record("berry-crush-step", slot=slot, step=step, phase=phase,
                           picture=self.picture(probe, f"{slot}-3-{len(steps):02d}-{step}") if pictured else None)
                if callback in game.bag:
                    await probe.press(A, release=36)       # the first Berry, then CONFIRM
                    presses += 1
                elif step in ("Cmd_PlayGame_Leader", "Cmd_PlayGame_Member"):
                    started = time.monotonic()
                    await asyncio.to_thread(_mash, probe, KEYS[A], 1.0)
                    mashing += time.monotonic() - started
                elif step == "Cmd_PrintMessage" and phase == 1:
                    # the text printer itself waits for a press (the arrow) or still prints: the host presses A, the
                    # friend B (both go on with the text; B is also "no", the friend's answer to playing again)
                    await probe.press(A if slot == 0 else B, release=30)
                    presses += 1
                elif step == "Cmd_PrintMessage" and phase == 2 or step == "Cmd_ShowResults" and phase == 2:
                    await probe.press(A)
                    presses += 1
                elif step == "Cmd_AskPlayAgain" and phase == 2:
                    await asyncio.sleep(.5)
                    record("play-again-question", slot=slot, answer="YES" if slot == 0 else "NO",
                           picture=self.picture(probe, f"{slot}-4-play-again"))
                    await probe.press(A if slot == 0 else B)
                    presses += 1
                else:
                    await asyncio.sleep(.05)
        await asyncio.sleep(2)
        record("back-on-the-field", slot=slot, steps=steps, presses=presses, mashing_seconds=round(mashing, 1),
               picture=self.picture(probe, f"{slot}-5-back"))
        return dict(steps=steps)

    async def play_jump(self, probe, slot, game, record, stop):
        """Pokemon Jump for one player, from its memory: A as the vine comes down (each swing until JUMPS jumps, then
        none: the vine catches it), the prize's message if there is one, the host YES and the friends NO to playing
        again, until the game has walked out of the room. Counted on the way: this game's rounds and jumps, and each
        other player's jumps as this game shows them (they come over the link)."""
        phases, rounds, jumps = [], 0, 0
        entered, focused, swing_pressed = False, False, False
        last_phase, last_report, at_question = None, time.monotonic(), None
        others = [i for i in range(self.count) if i != slot]   # the host leads (player 0), the friends follow
        other_jumps, was_jumping = dict.fromkeys(others, 0), dict.fromkeys(others, False)
        # how well this proof follows the vine (it must see VINE_DOWNSWING_LOWER, a few frames, to jump): the states
        # read in a round and the longest time between two reads there
        vines_seen, longest_gap, last_read, focus_seconds = set(), 0.0, None, None
        async with asyncio.timeout(GAME_SECONDS):
            while not stop.is_set():
                callback = game.callback2(probe)
                require(callback not in game.link_error, f"player {slot}'s game shows the communication error")
                state = game.jump(probe, self.count)
                if time.monotonic() - last_report >= 15:
                    last_report = time.monotonic()
                    # no picture while the vine swings: taking one holds up every player's reading (one event loop)
                    swinging = state is not None and state["phase"] == "GameRound"
                    record("pokemon-jump-now", slot=slot, callback2=hex(callback), state=state, jumps=jumps,
                           picture=None if swinging else
                           self.stuck_picture(probe, slot, (callback, state and state["phase"], state and state["helper"]),
                                              f"{slot}-w-{len(phases):02d}-{int(last_report) % 100000}"))
                if state is None:
                    if entered and callback in game.overworld and not game.linked(probe):
                        break
                    await asyncio.sleep(.05)
                    continue
                entered, phase = True, state["phase"]
                if phase not in JUMP_PHASES or state["leader"] not in (0, 1):
                    await asyncio.sleep(.01)               # read as its structure was freed: the screen is ending
                    continue
                for other in others:
                    jumping = state["mons"][other] == MONSTATE_JUMP
                    other_jumps[other] += int(jumping and not was_jumping[other])
                    was_jumping[other] = jumping
                if phase != last_phase:
                    rounds += phase == "GameRound"
                    last_read = None                       # a gap is measured within a round
                    if phase not in phases:                # each round is GameRound, then WaitRound: named once
                        phases.append(phase)
                        pictured = phase in ("GameIntro", "GameOver", "Exit")
                        record("pokemon-jump-phase", slot=slot, phase=phase, leader=state["leader"],
                               score=state["score"], cleared=state["cleared"],
                               picture=self.picture(probe, f"{slot}-3-{len(phases):02d}-{phase}") if pictured else None)
                    last_phase = phase
                if phase in ("GameIntro", "GameRound") and not focused:
                    # its display has one window: focused once, as the names show, before the vine moves (focusing
                    # can take seconds: done in a round it cost the first swing, KNOWN_ISSUES MS-141c four players)
                    started = time.monotonic()
                    await asyncio.to_thread(probe._window)
                    focus_seconds, focused = round(time.monotonic() - started, 3), True
                    continue
                if phase == "GameRound":
                    now = time.monotonic()
                    if last_read is not None:
                        longest_gap = max(longest_gap, now - last_read)
                    last_read = now
                    vines_seen.add(state["vine"])
                    if state["vine"] == VINE_DOWNSWING_LOWER and not swing_pressed:
                        swing_pressed = True
                        if jumps < JUMPS:
                            await asyncio.to_thread(_tap, probe, KEYS[A])
                            jumps += 1
                    elif state["vine"] not in (VINE_DOWNSWING_LOWER, VINE_DOWNSWING_LOWER + 1, VINE_UPSWING_LOWER):
                        swing_pressed = False
                    await asyncio.sleep(.004)
                elif phase == "AskPlayAgain" and state["helper"] == 2 and at_question is None:
                    await asyncio.sleep(.5)
                    at_question = dict(state, answer="YES" if slot == 0 else "NO")
                    record("play-again-question", slot=slot, **at_question,
                           picture=self.picture(probe, f"{slot}-4-play-again"))
                    await probe.press(A if slot == 0 else B)
                elif phase == "GivePrize" and state["helper"] in (2, 5):
                    await probe.press(A)                   # the prize's message waits for a press (or 3 s)
                else:
                    await asyncio.sleep(.01)
        await asyncio.sleep(2)
        played = dict(rounds=rounds, jumps=jumps, other_jumps=other_jumps, at_question=at_question)
        record("back-on-the-field", slot=slot, phases=phases, **played, vines_seen=sorted(vines_seen),
               longest_read_gap=round(longest_gap, 3), focus_seconds=focus_seconds,
               picture=self.picture(probe, f"{slot}-5-back"))
        return dict(steps=phases, **played)

    async def play_dodrio(self, probe, slot, game, record, stop):
        """Dodrio Berry Picking for one player, from its memory: UP (the middle head) again and again while the Berries
        fall, A through the results' pages, then the host YES and the friends NO to playing again, until the game has
        walked out of the room."""
        phases, picks, entered, focused, last_pick = [], 0, False, False, 0.0
        last_phase, last_report, last_page, at_question, at_results = None, time.monotonic(), 0.0, None, None
        async with asyncio.timeout(GAME_SECONDS):
            while not stop.is_set():
                callback = game.callback2(probe)
                require(callback not in game.link_error, f"player {slot}'s game shows the communication error")
                state = game.dodrio(probe)
                if time.monotonic() - last_report >= 15:
                    last_report = time.monotonic()
                    record("dodrio-now", slot=slot, callback2=hex(callback), state=state, picks=picks,
                           picture=self.stuck_picture(probe, slot, (callback, state and state["phase"],
                                                                    state and state["state"]),
                                                      f"{slot}-w-{len(phases):02d}-{int(last_report) % 100000}"))
                if state is None:
                    if entered and callback in game.overworld and not game.linked(probe):
                        break
                    await asyncio.sleep(.05)
                    continue
                entered, phase = True, state["phase"]
                if phase not in DODRIO_PHASES or state["leader"] not in (0, 1) or not 3 <= state["players"] <= 5:
                    await asyncio.sleep(.01)               # read as its structure was freed: the screen is ending
                    continue
                if phase != last_phase:
                    if phase not in phases:
                        phases.append(phase)
                        pictured = phase in ("Intro", "PlayGame", "Results", "EndLink")
                        record("dodrio-phase", slot=slot, phase=phase, leader=state["leader"], missed=state["missed"],
                               eaten=state["eaten"],
                               picture=self.picture(probe, f"{slot}-3-{len(phases):02d}-{phase}") if pictured else None)
                    last_phase = phase
                now = time.monotonic()
                if phase == "PlayGame":
                    if not focused:
                        await asyncio.to_thread(probe._window)    # its display has one window: focused once
                        focused = True
                    if now - last_pick >= .2:
                        await asyncio.to_thread(_tap, probe, KEYS[UP])
                        picks, last_pick = picks + 1, now
                    await asyncio.sleep(.01)
                elif phase == "Results":
                    # the table every game shows: the leader's, sent to the others as a link block at the results
                    at_results = state
                    if now - last_page >= 1.0:
                        await probe.press(A)               # each page waits half a second, then for A
                        last_page = time.monotonic()
                    else:
                        await asyncio.sleep(.05)
                elif phase == "AskPlayAgain" and state["state"] == 3 and at_question is None:
                    await asyncio.sleep(.5)
                    at_question = dict(state, answer="YES" if slot == 0 else "NO")
                    record("play-again-question", slot=slot, **at_question,
                           picture=self.picture(probe, f"{slot}-4-play-again"))
                    await probe.press(A if slot == 0 else B)
                else:
                    await asyncio.sleep(.02)
        await asyncio.sleep(2)
        played = dict(picks=picks, at_results=at_results, at_question=at_question)
        record("back-on-the-field", slot=slot, phases=phases, **played, picture=self.picture(probe, f"{slot}-5-back"))
        return dict(steps=phases, **played)

    async def match(self, current, probes, games, host, symbols, record):
        names = [account.display_name for account in host.accounts]
        game = Game(self.facts, self.activity)
        host_probe, friends, count = probes[0], probes[1:], len(probes)
        self.count = count

        async def host_view(s):
            groups = s._server.minigames
            return dict(groups={gid: dict(activity=g.activity, players=list(g.players), started=g.started,
                                          left=sorted(g.left)) for gid, g in groups._groups.items()},
                        relayed=groups.relayed)

        async def link_view(s):
            link = s._companion.minigames
            return dict(activity=link.activity, group=link.group_id, started=link.started, dropped=link.dropped,
                        notice=link.notice)

        timeline, seen = [], dict(groups={}, started=[None] * count, notices=[set() for _ in probes], dropped=[0] * count)
        stop = asyncio.Event()

        async def watch():
            last = None
            while not stop.is_set():
                view = await on_worker(current[0], host_view)
                links = [await on_worker(worker, link_view) for worker in current]
                for gid, group in view["groups"].items():
                    seen["groups"].setdefault(gid, group)
                    seen["groups"][gid] = dict(group, started=group["started"] or seen["groups"][gid]["started"])
                for slot, link in enumerate(links):
                    if link["started"]:
                        seen["started"][slot] = list(link["started"])
                    if link["notice"]:
                        seen["notices"][slot].add(link["notice"])
                    seen["dropped"][slot] = link["dropped"]
                row = (view, links)
                if row != last:
                    timeline.append(dict(t=round(time.monotonic() - began, 2), host=view, companions=links))
                    last = row
                await asyncio.sleep(.1)

        began = time.monotonic()
        watcher = asyncio.create_task(watch())
        try:
            # 2. both at the attendant, both lobbies
            screen = await self.to_lobby(host_probe, 0, game, record)
            require(screen.rows and screen.rows[0].label == "Lead a group", f"the host's lobby: {screen.rows}")
            _, screen = await host_probe.choose("Lead a group")
            record("host-leads", status=screen.status, rows=[r.label for r in screen.rows])
            minimum = ACTIVITIES[self.activity]["least"]
            require(screen.status == f"Waiting: {minimum} players or more", f"the host's group says {screen.status!r}")
            for slot, friend in enumerate(friends, 1):
                screen = await self.to_lobby(friend, slot, game, record)
                join = f"Join {names[0][:12]} {slot}/4"
                async with asyncio.timeout(15):
                    while join not in [r.label for r in screen.rows]:
                        await asyncio.sleep(.5)            # the page reads the host's groups every 2 s
                        _, screen = await friend.ready()
                _, screen = await friend.choose(join)
                record("friend-joins", slot=slot, status=screen.status, rows=[r.label for r in screen.rows],
                       picture=self.picture(friend, f"{slot}-2-joined"))
                require(screen.status == f"Waiting for {names[0][:12]} to start", f"friend {slot}'s page: {screen.status!r}")
            # 3. the host's page offers the start once the friends are in
            start = f"Start with {count} players"
            async with asyncio.timeout(15):
                while True:
                    _, screen = await host_probe.ready()
                    if start in [r.label for r in screen.rows]:
                        break
                    await asyncio.sleep(.3)
            record("host-can-start", status=screen.status, rows=[r.label for r in screen.rows],
                   picture=self.picture(host_probe, "0-2-start"))
            await host_probe.choose(start, wait=False)
            await until(lambda: not any(p.read()["active"] for p in probes), 30, "every window closed")
            record("started", groups=seen["started"])
            # 4. the game
            play = dict(berry_crush=self.play_crush, pokemon_jump=self.play_jump, dodrio=self.play_dodrio)[self.activity]
            played = await asyncio.gather(*(play(probe, slot, game, record, stop) for slot, probe in enumerate(probes)))
            steps = [p["steps"] for p in played]
            if self.activity == "berry_crush":
                require("Cmd_PlayGame_Leader" in steps[0] and all("Cmd_PlayGame_Member" in s for s in steps[1:]),
                        f"the crush was not played as leader and members: {steps}")
                require(all("Cmd_ShowResults" in s for s in steps), f"a game showed no results: {steps}")
                require(all("Cmd_AskPlayAgain" in s for s in steps), f"a game had no play-again question: {steps}")
            elif self.activity == "dodrio":
                # in every game the phases that last the game or wait for its player; the short ones (Intro, the names
                # for 3 s; EndLink, a few frames on the way out) are recorded when seen: every picture holds up every
                # game's reading (one event loop, about a second a picture on Windows), and run 280's four games on
                # Windows missed EndLink so; the results, the play-again question and every game back on the field
                # with its link closed are checked below
                for phase in ("PlayGame", "Results", "AskPlayAgain"):
                    require(all(phase in s for s in steps), f"Dodrio Berry Picking's {phase} not in every game: {steps}")
                ends = [p["at_question"] for p in played]
                require(all(ends), f"a game was not asked to play again: {ends}")
                require([e["leader"] for e in ends] == [1] + [0] * (count - 1), f"not the host alone leading: {ends}")
                tables = [p["at_results"] and p["at_results"]["results"] for p in played]
                require(all(tables), f"a game showed no results: {tables}")
                require(all(t == tables[0] for t in tables), f"the games show different results: {tables}")
                eaten = [sum(row[:3]) for row in tables[0]]     # blue, green and gold Berries
                require(all(n >= 1 for n in eaten), f"a player's picks never reached the leader's game: {eaten}")
            else:
                # as Dodrio Berry Picking's: the rounds and the play-again question in every game; GameIntro, GameOver
                # (the vine's hit, a second or two) and Exit are recorded when seen (run 280 on Windows: one of four
                # games' GameOver passed while the others' pictures held up its reading); the question comes only
                # after a GameOver (the leader sets FUNC_GAME_OVER when the vine hits, src/pokemon_jump.c), and every
                # game's score there is checked below
                for phase in ("GameRound", "AskPlayAgain"):
                    require(all(phase in s for s in steps), f"Pokemon Jump's {phase} not in every game: {steps}")
                ends = [p["at_question"] for p in played]
                require(all(ends), f"a game was not asked to play again: {ends}")
                require([e["leader"] for e in ends] == [1] + [0] * (count - 1),
                        f"not the host leading and the friends members: {ends}")
                require(all((e["score"], e["cleared"]) == (ends[0]["score"], ends[0]["cleared"]) for e in ends),
                        f"the games show different scores: {ends}")
                require(ends[0]["cleared"] >= 1, f"no swing cleared by every player: {ends}")
                require(all(n >= 1 for p in played for n in p["other_jumps"].values()),
                        f"a game never showed another player's jump: {[p['other_jumps'] for p in played]}")
            await asyncio.sleep(3)                         # the leaves reach the host
        finally:
            stop.set()
            await watcher
            (self.output / "minigame-timeline.json").write_text(json.dumps(timeline, indent=1) + "\n")
        view = await on_worker(current[0], host_view)
        groups = [g for g in seen["groups"].values() if g["activity"] == self.activity and g["started"]]
        ids = [account.player_id for account in host.accounts]
        require(len(groups) == 1 and groups[0]["players"] == ids, f"the host's groups: {seen['groups']}")
        require(sorted(index for _, index in filter(None, seen["started"])) == list(range(count)),
                f"the games were told {seen['started']}")
        require(view["relayed"] >= (600 if self.activity == "berry_crush" else 300),
                f"only {view['relayed']} link frames went through the host")
        require(not any(seen["dropped"]), f"a companion dropped link frames: {seen['dropped']}")
        require(not view["groups"], f"the host still has groups: {view['groups']}")
        require(not any(seen["notices"]), f"a game was told its group was lost: {seen['notices']}")
        require(not any(game.linked(p) for p in probes), "a game's link is still up")
        record(f"{self.activity.replace('_', '-')}-between-world-players", frames_relayed=view["relayed"],
               host_group=groups[0], started=seen["started"], seconds=round(time.monotonic() - began, 1),
               played=[{k: v for k, v in p.items() if k != "steps"} for p in played])


async def run(args):
    activity = ACTIVITIES[args.activity]
    players = args.players or activity["least"]
    require(activity["least"] <= players <= len(activity["names"]),
            f"{args.activity} takes {activity['least']} to {len(activity['names'])} of a world's players, not {players}")
    names = activity["names"][:players]
    if WINDOWS:
        # the release's Windows game is stripped: its facts were written before (minigame_facts.py); one desktop
        require(args.minigame_facts, "on Windows: --minigame-facts (minigame_facts.py of the game before its strip)")
        facts = json.loads(args.minigame_facts.read_text())
        args.display = args.display or [f"desktop-{n}" for n in range(len(names))]   # names for the records
    else:
        facts = game_facts(args.game.resolve())
    minigame = MinigameMatch(args.output.resolve(), facts, args.activity)

    async def match(*values):
        return await minigame.match(*values)
    sources = (args.source_a, args.source_b, args.source_c, args.source_d)[:len(names)]
    require(all(sources) and args.display and len(args.display) >= len(names),
            f"{args.activity} takes {len(names)} players: a --source and a --display each")
    await launcher_proof(args, names=names, sources=sources, party_counts=(1,) * len(names), match=match,
                         version="Native minigame proof", settings="windowScale=2\n", scope=__doc__.split("\n\n")[0])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True,
                        help="the native game: Linux, unstripped; Windows, the release's (with --minigame-facts)")
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--activity", choices=sorted(ACTIVITIES), default="berry_crush")
    parser.add_argument("--source-a", type=Path, required=True, help="make_tower_saves.py's crush-a (jump-a)")
    parser.add_argument("--source-b", type=Path, required=True, help="make_tower_saves.py's crush-b (jump-b)")
    parser.add_argument("--source-c", type=Path, help="make_tower_saves.py's dodrio-c (--activity dodrio), crush-c, jump-c")
    parser.add_argument("--source-d", type=Path, help="make_tower_saves.py's crush-d, jump-d, dodrio-d (--players 4)")
    parser.add_argument("--players", type=int, choices=(2, 3, 4),
                        help="a world's players in the game (default the game's least: 2, Dodrio Berry Picking 3)")
    parser.add_argument("--display", action="append", help="an X display per player (Linux)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0)
    parser.add_argument("--wine", type=Path, action="append", help="not for this proof (Linux clients)")
    parser.add_argument("--sdl", type=Path)
    parser.add_argument("--elf", type=Path)
    parser.add_argument("--pe-symbols", type=Path, help="Windows: nm -n of the game before its strip")
    parser.add_argument("--sizes", type=Path, help="Windows: nm -S of the Linux build of the same engine commit")
    parser.add_argument("--minigame-facts", type=Path, help="Windows: minigame_facts.py of the game before its strip")
    parser.add_argument("--runtime-extra", type=Path, action="append", help="Windows: another file beside the game")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
