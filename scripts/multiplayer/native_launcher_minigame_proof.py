"""Berry Crush between two of a world's players through the whole launcher (KNOWN_ISSUES MS-141c).

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

What the games do is read from their memory (the attendant's choice, the save's questions, the Players menu, Berry
Crush's current step); keys are pressed as a player presses them (xdotool). Pictures for a person: OUT/pictures.

    PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime \\
      python scripts/multiplayer/native_launcher_minigame_proof.py \\
        --game ../engine/pokeemerald-mp --rom pokeemerald.gba --manifest manifest.json \\
        --source-a crush-a.sav --source-b crush-b.sav --display :94 --display :95 \\
        --output /private/multiplayer-proof/native-launcher-minigame-1
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
from native_launcher_battle_proof import KEYS, function_addresses, game_picture, launcher_proof  # noqa: E402
from qualify_admission_cleanup import on_worker, require  # noqa: E402

A, B, UP = 1, 2, 64
PLAYER_NAMES = ("Crush Host", "Crush Friend")
MULTICHOICE_TASKS = ("Task_HandleScrollingMultichoiceInput", "Task_HandleMultichoiceInput")
BERRY_CRUSH_STEPS = (
    "Cmd_BeginNormalPaletteFade", "Cmd_WaitPaletteFade", "Cmd_PrintMessage", "Cmd_ShowGameDisplay",
    "Cmd_HideGameDisplay", "Cmd_SignalReadyToBegin", "Cmd_AskPickBerry", "Cmd_GoToBerryPouch",
    "Cmd_WaitForOthersToPickBerries", "Cmd_DropBerriesIntoCrusher", "Cmd_DropLid", "Cmd_Countdown",
    "Cmd_PlayGame_Leader", "Cmd_PlayGame_Member", "Cmd_FinishGame", "Cmd_HandleTimeUp", "Cmd_TabulateResults",
    "Cmd_ShowResults", "Cmd_SaveGame", "Cmd_AskPlayAgain", "Cmd_CommunicatePlayAgainResponses", "Cmd_PlayAgain",
    "Cmd_StopGame", "Cmd_CloseLink", "Cmd_Quit")
GAME_SECONDS = 420


def data_addresses(game, name):
    """Every address of a data symbol (static ones repeat: several files have an `sGame`)."""
    rows = subprocess.run(["nm", str(game)], capture_output=True, text=True, check=True).stdout
    return sorted({int(row[0], 16) for row in (line.split() for line in rows.splitlines())
                   if len(row) == 3 and row[1] in "bBdD" and row[2] == name})


class Game:
    """What one game is doing, read from its memory (the Linux game runs where it was linked)."""

    def __init__(self, game, symbols):
        self.symbols = symbols
        self.multichoice = frozenset().union(*(function_addresses(game, name) for name in MULTICHOICE_TASKS))
        self.save_questions = {**{a: "save?" for a in function_addresses(game, "SaveConfirmInputCallback")},
                               **{a: "overwrite?" for a in function_addresses(game, "SaveOverwriteInputCallback")}}
        self.steps = {address: name for name in BERRY_CRUSH_STEPS for address in function_addresses(game, name)}
        self.crush_games = data_addresses(game, "sGame")
        self.save_dialog = data_addresses(game, "sSaveDialogCallback")
        self.link_active = data_addresses(game, "sLocalLinkActive")
        self.bag = function_addresses(game, "CB2_BagMenuRun") | function_addresses(game, "CB2_Bag")
        self.link_error = function_addresses(game, "CB2_LinkError")
        self.overworld = function_addresses(game, "CB2_Overworld")
        require(self.multichoice and len(self.save_questions) == 2 and len(self.steps) >= len(BERRY_CRUSH_STEPS)
                and self.crush_games and self.save_dialog and self.link_active and self.bag and self.link_error
                and self.overworld, "the native game lacks the symbols this proof reads: build it unstripped")

    @staticmethod
    def raw(probe, address, size):
        with open(f"/proc/{probe.pid}/mem", "rb", buffering=0) as memory:
            memory.seek(address)
            return memory.read(size)

    def word(self, probe, address):
        return int.from_bytes(self.raw(probe, address, 4), "little")

    def callback2(self, probe):
        return self.word(probe, self.symbols["gMain"][0] + 4) & ~1

    def multichoice_shown(self, probe):
        tasks = probe.mem("gTasks", 640)
        return any(tasks[o + 4] and int.from_bytes(tasks[o:o + 4], "little") & ~1 in self.multichoice
                   for o in range(0, 640, 40))

    def save_question(self, probe):
        return self.save_questions.get(self.word(probe, self.save_dialog[0]) & ~1)

    def crush(self, probe):
        """Berry Crush's current step (its command's name, the command's state), or None outside Berry Crush."""
        for address in self.crush_games:
            game = self.word(probe, address)
            if game:
                step = self.steps.get(self.word(probe, game + 4) & ~1)
                if step is not None:
                    return step, self.raw(probe, game + 12, 1)[0]
        return None

    def linked(self, probe):
        return any(self.raw(probe, address, 1)[0] for address in self.link_active)


async def until(predicate, timeout, what):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.05)
    return True


def _mash(probe, key, seconds, period=.11):
    """A held as briefly as a quick thumb holds it, again and again (one focus for the burst)."""
    probe._window()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        subprocess.run(["xdotool", "keydown", key], env=probe.environment, check=True)
        time.sleep(.045)
        subprocess.run(["xdotool", "keyup", key], env=probe.environment, check=True)
        time.sleep(period - .045)


class MinigameMatch:
    def __init__(self, output, game_path):
        self.output, self.game_path = output, game_path
        self.pictures = output / "pictures"

    def picture(self, probe, name):
        self.pictures.mkdir(exist_ok=True)
        try:
            return game_picture(probe, self.pictures / f"{name}.png")
        except Exception as error:  # noqa: BLE001 - a picture is for a person; the checks read memory
            return f"no picture: {error}"

    async def to_lobby(self, probe, slot, game, record):
        """The attendant, WORLD PLAYERS, the game's own save; the Players menu then opens on the lobby."""
        await probe.press(UP)                              # turn to the attendant (the counter: no step is taken)
        await probe.press(A)
        await until(lambda: game.multichoice_shown(probe), 60, "the attendant's choice")
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
        require(screen.title == "BERRY CRUSH", f"the lobby's page is {screen.title!r}")
        return screen

    async def play(self, probe, slot, game, record, stop):
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
                           picture=self.picture(probe, f"{slot}-w-{len(steps):02d}-{int(last_report) % 100000}"))
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
        return steps

    async def match(self, current, probes, games, host, symbols, record):
        names = [account.display_name for account in host.accounts]
        game = Game(self.game_path, symbols)
        host_probe, friend_probe = probes

        async def host_view(s):
            groups = s._server.minigames
            return dict(groups={gid: dict(activity=g.activity, players=list(g.players), started=g.started,
                                          left=sorted(g.left)) for gid, g in groups._groups.items()},
                        relayed=groups.relayed)

        async def link_view(s):
            link = s._companion.minigames
            return dict(activity=link.activity, group=link.group_id, started=link.started, dropped=link.dropped,
                        notice=link.notice)

        timeline, seen = [], dict(groups={}, started=[None, None], notices=[set(), set()], dropped=[0, 0])
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
            require(screen.status == "Waiting: 2 players or more", f"the host's group says {screen.status!r}")
            screen = await self.to_lobby(friend_probe, 1, game, record)
            join = f"Join {names[0][:12]} 1/4"
            if join not in [r.label for r in screen.rows]:
                await asyncio.sleep(2.5)                   # the page reads the host's groups every 2 s
                _, screen = await friend_probe.ready()
            _, screen = await friend_probe.choose(join)
            record("friend-joins", status=screen.status, rows=[r.label for r in screen.rows],
                   picture=self.picture(friend_probe, "1-2-joined"))
            require(screen.status == f"Waiting for {names[0][:12]} to start", f"the friend's page: {screen.status!r}")
            # 3. the host's page offers the start once the friend is in
            async with asyncio.timeout(15):
                while True:
                    _, screen = await host_probe.ready()
                    if "Start with 2 players" in [r.label for r in screen.rows]:
                        break
                    await asyncio.sleep(.3)
            record("host-can-start", status=screen.status, rows=[r.label for r in screen.rows],
                   picture=self.picture(host_probe, "0-2-start"))
            await host_probe.choose("Start with 2 players", wait=False)
            await until(lambda: not host_probe.read()["active"] and not friend_probe.read()["active"], 30,
                        "both windows closed")
            record("started", host_group=seen["started"][0], friend_group=seen["started"][1])
            # 4. the game
            steps = await asyncio.gather(self.play(host_probe, 0, game, record, stop),
                                         self.play(friend_probe, 1, game, record, stop))
            require("Cmd_PlayGame_Leader" in steps[0] and "Cmd_PlayGame_Member" in steps[1],
                    f"the crush was not played as leader and member: {steps}")
            require("Cmd_ShowResults" in steps[0] and "Cmd_ShowResults" in steps[1], "no results")
            require("Cmd_AskPlayAgain" in steps[0] and "Cmd_AskPlayAgain" in steps[1], "no play-again question")
            await asyncio.sleep(3)                         # the leaves reach the host
        finally:
            stop.set()
            await watcher
            (self.output / "minigame-timeline.json").write_text(json.dumps(timeline, indent=1) + "\n")
        view = await on_worker(current[0], host_view)
        crush = [g for g in seen["groups"].values() if g["activity"] == "berry_crush" and g["started"]]
        ids = [account.player_id for account in host.accounts]
        require(len(crush) == 1 and crush[0]["players"] == ids, f"the host's groups: {seen['groups']}")
        require(sorted(index for _, index in filter(None, seen["started"])) == [0, 1],
                f"the games were told {seen['started']}")
        require(view["relayed"] >= 600, f"only {view['relayed']} link frames went through the host")
        require(not any(seen["dropped"]), f"a companion dropped link frames: {seen['dropped']}")
        require(not view["groups"], f"the host still has groups: {view['groups']}")
        require(not any(seen["notices"]), f"a game was told its group was lost: {seen['notices']}")
        require(not any(game.linked(p) for p in probes), "a game's link is still up")
        record("berry-crush-between-world-players", frames_relayed=view["relayed"], host_group=crush[0],
               started=seen["started"], seconds=round(time.monotonic() - began, 1))


async def run(args):
    minigame = MinigameMatch(args.output.resolve(), args.game.resolve())

    async def match(*values):
        return await minigame.match(*values)
    await launcher_proof(args, names=PLAYER_NAMES, sources=(args.source_a, args.source_b), party_counts=(1, 1),
                         match=match, version="Native minigame proof", settings="windowScale=2\n",
                         scope=__doc__.split("\n\n")[0])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True, help="native Linux executable, unstripped")
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-a", type=Path, required=True, help="make_tower_saves.py's crush-a")
    parser.add_argument("--source-b", type=Path, required=True, help="make_tower_saves.py's crush-b")
    parser.add_argument("--display", action="append", required=True, help="an X display per player (twice)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0)
    parser.add_argument("--wine", type=Path, action="append", help="not for this proof (Linux clients)")
    parser.add_argument("--sdl", type=Path)
    parser.add_argument("--elf", type=Path)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
