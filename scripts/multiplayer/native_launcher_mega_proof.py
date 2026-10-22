"""Four native games through the whole launcher: every player of a battle Mega Evolves (Update 32, Mega Evolution).

Each player's lead holds its Mega Stone and each bag has the Mega Ring. The source saves are test saves made by the
engine's test build (PKMN_TEST_BATTLE=save:1 with PKMN_TEST_PARTY and PKMN_TEST_BAG; never a player build): Charizard
with Charizardite X, Charizard with Charizardite Y, Mewtwo with Mewtwonite X and a shiny Mewtwo with Mewtwonite Y.

    1. A 1v1 of the host and the first friend.
    2. A 1v1v1 of the host and the first two friends (PLAYERS > Challenges > New battle > Free-for-All > "With ...").
    3. The free-for-all of all four.
    4. A 2v2: the host and the first friend against the other two.

In each battle every game presses START once at its first move menu where its battler may Mega Evolve (the trigger;
MEGA EVOLVE on the PC battle screen), checks that the trigger is on, then A, as a player does; every other choice is
the default. After the first turn every game of the battle has marked every Mega (the battlers' active gimmick, which
the healthbox indicator and the PC battle screen show), and the game that runs the battle (its first player's: the
link master, the only game whose battle engine runs) has each battler in its Mega form.
Each battle runs to its end and everyone is back in the world with the party from before it (a native battle never
changes a party, so each Mega is its own form again). The harness's own end: all four save, each save's party is the
canonical one, the store passes its integrity check, a normal close and a fresh Continue.

--scenario three (three games): the 1v1v1 alone, through PLAYERS > Challenges > New battle > Free-for-All - 3 Players.

--scenario two (two games): the 1v1 alone. With --light-3d (the native 3D build, DIORAMA=1) the launchers' game settings
are native_launcher_battle_3d_proof.py's light 3D configuration, so two software-OpenGL games fit a cloud workspace;
the 3D build goes in as --game with its debug information stripped (objcopy --strip-debug: unstripped it is over the
runtime's size limit) and as --elf unstripped, for the battle structures' offsets.

--scenario no-ring (two games): the friend's lead holds Charizardite Y but its bag has no Mega Ring. In their 1v1 the
host Mega Evolves; the friend's game never offers it (the Ring is in the player's own bag, which only their game can
see), so the battle marks one Mega and the friend's Charizard keeps its form.

--scenario no-ring-host (two games): the same with the Ring in the friend's bag and not in the host's (the host's lead
holds Charizardite X). Whichever of the two runs the battle, the one without the Ring is never offered it: the game that
runs the battle reads its own player's bag, and the other game refuses a Mega offered by the game that runs the battle
unless its own bag has the Ring.

The battle structures' offsets come from the game's own debug information (gdb, read only).

    PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime \\
      python scripts/multiplayer/native_launcher_mega_proof.py \\
        --game ../engine/pokeemerald-mp --rom pokedev.gba --manifest manifest.json \\
        --source charizard-x.sav --source charizard-y.sav --source mewtwo-x.sav --source mewtwo-y.sav \\
        --display :94 --display :95 --display :96 --display :97 --output /private/multiplayer-proof/mega-1
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows-runtime"))
from native_launcher_abandon_proof import PENDING, AbandonProof  # noqa: E402
from native_launcher_battle_3d_proof import LIGHT_3D_SETTINGS  # noqa: E402
from native_launcher_battle_proof import WINDOWS, game_picture, launcher_proof  # noqa: E402
from mega_facts import game_facts, load_facts  # noqa: E402
from native_launcher_ffa_proof import MATCH_SECONDS, into_littleroot, players_tab  # noqa: E402
from qualify_admission_cleanup import on_worker, require  # noqa: E402
from qualify_menu_battle import party_action  # noqa: E402

PLAYER_NAMES = ("Mega Host", "Blaze", "Flare", "Psychic")
GIMMICK_MEGA = 1
BATTLE_TYPE_IS_MASTER = 1 << 2
START, A = 8, 1


def raw(probe, address, size):
    """`size` bytes at an address the game holds (a pointer's value: where it is in the running process)."""
    memory = getattr(probe, "memory", None)
    if memory is not None:                     # Windows: ReadProcessMemory (WindowsProbe), the address as it is
        return memory._raw(address, size)
    with open(f"/proc/{probe.pid}/mem", "rb", buffering=0) as memory:
        memory.seek(address)
        return memory.read(size)


def gimmick_data(probe, facts):
    base = int.from_bytes(probe.mem("gBattleStruct", 4), "little")
    if base == 0:
        return None
    start = base + facts["gimmick"]
    usable = raw(probe, start + facts["usable"], 4)
    return dict(usable=list(usable), select=raw(probe, start + facts["select"], 1)[0],
                active=list(raw(probe, start + facts["active"], facts["active_size"])))


def battle_species(probe, facts):
    count = probe.mem("gBattlersCount", 1)[0]
    mons = probe.mem("gBattleMons", facts["mon_size"] * 4)
    return [int.from_bytes(mons[b * facts["mon_size"]:b * facts["mon_size"] + 2], "little") for b in range(min(count, 4))]


def mega_state(probe, facts):
    """What one game shows of the battle's Megas: its gimmick data, its battlers' species (only the master's are kept up
    to date) and whether it runs the battle."""
    data = gimmick_data(probe, facts)
    if data is None:
        return dict(battle=False)
    flags = int.from_bytes(probe.mem("gBattleTypeFlags", 4), "little")
    return dict(battle=True, master=bool(flags & BATTLE_TYPE_IS_MASTER), usable=data["usable"],
                marks=sum(1 for g in data["active"] if g == GIMMICK_MEGA), species=battle_species(probe, facts))


def move_menu_battler(probe, symbols):
    """The battler whose move menu this game shows (its controller waits in HandleInputChooseMove), or None."""
    menu = symbols["HandleInputChooseMove"][0] & ~1
    funcs = probe.mem("gBattlerControllerFuncs", 16)
    for battler in range(4):
        if probe.code(int.from_bytes(funcs[battler * 4:battler * 4 + 4], "little")) & ~1 == menu:
            return battler
    return None


async def drive_mega_input(probe, view, symbols, stop, facts, record, name):
    """The proofs' default input (drive_battle_input), except at this game's first move menu where its battler may Mega
    Evolve: START there, the trigger checked on, then A. The move menu is the game's own (its battler's controller in
    HandleInputChooseMove), not the route's pending command: the game that runs the battle reports its own player's
    choice a moment after its menu is up, so an A pressed in between would choose the move without the trigger."""
    triggered, starts = False, 0
    while not stop.is_set():
        room = await view()
        if room["state"] in ("closed", "aborted", "recovery_required"):
            return
        if not triggered and room["state"] == "executing":
            battler = move_menu_battler(probe, symbols)
            data = gimmick_data(probe, facts) if battler is not None else None
            if data is not None:
                if data["usable"][battler] == GIMMICK_MEGA and not data["select"] and starts < 5:
                    await probe.press(START, frames=12, release=30)
                    starts += 1
                    continue
                if data["usable"][battler] != GIMMICK_MEGA:
                    record("mega-not-offered", player=name, battler=battler, usable=data["usable"])
                elif data["select"]:
                    record("mega-trigger-on", player=name, battler=battler, usable=data["usable"])
                else:
                    # START did not turn the trigger on: what the game shows, then the battle goes on without it
                    funcs = probe.mem("gBattlerControllerFuncs", 16)
                    names = {address & ~1: symbol for symbol, (address, _) in symbols.items()}
                    record("mega-trigger-stuck", player=name, battler=battler, usable=data["usable"], presses=starts,
                           flags=hex(int.from_bytes(probe.mem("gBattleTypeFlags", 4), "little")),
                           controllers=[names.get(probe.code(int.from_bytes(funcs[4 * b:4 * b + 4], "little")) & ~1,
                                                  "?") for b in range(4)])
                triggered = True
        state = await probe.battle()
        action = party_action(room["pending"], state, symbols) if room["state"] == "executing" else "wait"
        if stop.is_set():
            return
        if not triggered and action == "confirm" and move_menu_battler(probe, symbols) is not None:
            continue                                # the move menu came up just now: the trigger first
        if action == "next-party":
            pressed = await probe.press(128, frames=12, release=18)
            moved = await probe.battle(after=pressed["frame"] - 1)
            current = await view()
            if (not stop.is_set() and current["state"] == "executing" and current["pending"] == 21
                    and moved["state"] == 5 and symbols["Task_HandleChooseMonInput"][0] & ~1 in moved["active"]
                    and moved["cursor"] != state["cursor"] and 0 <= moved["cursor"] < moved["count"]):
                await probe.press(A, frames=12, release=18)
        elif action != "wait":
            await probe.press(2 if action == "dismiss" else A, frames=12, release=30 if action == "dismiss" else 18)
        else:
            await asyncio.sleep(.05)


class MegaProof(AbandonProof):
    def __init__(self, scenario, watch, match_seconds, facts):
        super().__init__(scenario, 0, watch, match_seconds)
        self.facts = facts

    async def match(self, current, probes, games, host, symbols, record):
        """AbandonProof.match for this proof's two or four players."""
        for n, worker in enumerate(current):
            self.own_display(n, worker)
            self.watch_loop(n, worker)
        states = [await self.state_of(w) for w in current]
        require(all(v["connected"] and v["game_link"] and v["roster"] == len(current) for v in states),
                f"not everyone is in the session: {states}")
        for index, probe in enumerate(probes):
            status, rows = await players_tab(probe)
            require(status == f"Connected: {len(current)}/4", f"player {index}'s PLAYERS: {status} {rows}")
        record("everyone-linked-before-the-battle", sessions=[v["epoch"] for v in states])
        before = [await probe.battle() for probe in probes]
        try:
            await getattr(self, self.scenario.replace("-", "_"))(current, probes, games, host, symbols, record, before)
        finally:
            self.thread_slot.clear()

    async def world_is_whole(self, current, probes, before, record, label):
        """AbandonProof.world_is_whole for this proof's two or four players."""
        players = len(current)
        async with asyncio.timeout(180):
            while True:
                states = [await self.state_of(w) for w in current]
                if all(v.get("connected") and v.get("game_link") and v.get("roster") == players and v.get("field")
                       for v in states):
                    break
                await asyncio.sleep(.5)
        for index, probe in enumerate(probes):
            status, rows = await players_tab(probe)
            require(status == f"Connected: {players}/4", f"player {index}'s PLAYERS: {status} {rows}")
            now = await probe.battle()
            require(now["count"] == before[index]["count"] and now["party_sha256"] == before[index]["party_sha256"],
                    f"player {index}'s party is not the one from before the battle")

        async def clean(s):
            left = [name for name in PENDING if (s.profile_directory / name).exists()]
            waiting = (await s._companion.battle_challenge_rpc("waiting"))["result"]
            return dict(pending_files=left, waiting=waiting, retained=s._battle_retained is not None)
        leftovers = [await on_worker(w, clean) for w in current]
        require(all(not v["pending_files"] and not v["waiting"] and not v["retained"] for v in leftovers),
                f"a battle still holds somebody: {leftovers}")
        record(label, sessions=[v["epoch"] for v in states], parties="as before the battle")

    def drive(self, current, probes, symbols, battles, slots):
        stops, drivers = {}, {}
        for n in slots:
            battle = next(b for b in battles.values() if self.harness.host.accounts[n].player_id in b["players"])
            slot = battle["players"].index(self.harness.host.accounts[n].player_id)

            async def view(battle_id=battle["battle_id"], slot=slot):
                async def read(s):
                    room = s._server.battle_execution.rooms.get(battle_id)
                    if room is None:
                        return dict(state="waiting", pending=None)
                    return dict(state=room.state, pending=None if room.route is None else room.route.validator.pending[slot])
                try:
                    return await on_worker(current[0], read)
                except RuntimeError:
                    return dict(state="recovery_required", pending=None)
            stops[n] = asyncio.Event()
            drivers[n] = asyncio.create_task(drive_mega_input(probes[n], view, symbols, stops[n], self.facts,
                                                              self.harness.record, self.harness.names[n]))
        return stops, drivers

    def screenshot(self, slot, name):
        return game_picture(self.harness.players[slot].probe, self.harness.output / f"{name}.png", settle=.3)

    async def megas_seen(self, probes, slots, record, label, timeout=240, megas=None):
        """Every game of the battle marks one Mega per player who may Mega Evolve (megas: those slots, default all);
        the game that runs the battle has each of their leads in its Mega form. Returns that game's battlers' species."""
        megas = tuple(slots) if megas is None else megas
        expected = {self.facts["megas"][n] for n in megas}
        started = time.monotonic()
        states = {}
        try:
            async with asyncio.timeout(timeout):
                while True:
                    states = {n: mega_state(probes[n], self.facts) for n in slots}
                    masters = [n for n, v in states.items() if v["battle"] and v["master"]]
                    if (all(v["battle"] and v["marks"] == len(megas) for v in states.values()) and len(masters) == 1
                            and expected <= set(states[masters[0]]["species"])):
                        break
                    await asyncio.sleep(.25)
        except TimeoutError:
            record(label + "-not-seen", expected=sorted(expected),
                   last_seen={self.harness.names[n]: v for n, v in states.items()})
            raise
        shots = [self.screenshot(n, f"{label}-{self.harness.names[n].lower().replace(' ', '-')}") for n in slots]
        record(label, seconds=round(time.monotonic() - started, 1), master=self.harness.names[masters[0]],
               master_species=states[masters[0]]["species"], expected=sorted(expected),
               marks={self.harness.names[n]: v["marks"] for n, v in states.items()}, screenshots=shots)
        return states[masters[0]]["species"]

    async def battle(self, current, probes, slots, record, before, label, mode, megas=None):
        battles = await self.enter(current, probes, slots, record, label)
        require([v["mode"] for v in battles.values()] == [mode], f"{label}: the battle is {battles}")
        stops, drivers = self.drive(current, probes, self.harness.symbols, battles, slots)
        try:
            species = await self.megas_seen(probes, slots, record, label + "-mega-evolved", megas=megas)
            for n in set(slots) - set(megas if megas is not None else slots):
                require(self.facts["megas"][n] not in species, f"{label}: player {n} Mega Evolved: {species}")
        except BaseException:
            for n in slots:
                stops[n].set()
            await asyncio.gather(*(drivers[n] for n in slots), return_exceptions=True)
            raise
        await self.finish(current, probes, battles, slots, stops, drivers, record, label)
        await self.world_is_whole(current, probes, before, record, f"everyone-back-after-the-{label}")

    async def accept(self, probes, slots):
        for n in slots:
            await probes[n].open_players()
            await probes[n].choose("Pending challenge")
            await probes[n].choose("Accept challenge")

    async def three(self, current, probes, games, host, symbols, record, before):
        names = [a.display_name for a in host.accounts]
        await probes[0].open_players()
        await probes[0].choose("Challenges")
        await probes[0].choose("New battle")
        await probes[0].choose("Free-for-All - 3 Players")
        await self.accept(probes, (1, 2))
        await self.battle(current, probes, (0, 1, 2), record, before, "1v1v1", 6)

    async def two(self, current, probes, games, host, symbols, record, before):
        await self.challenge_1v1(host, probes, 0, 1)
        await self.battle(current, probes, (0, 1), record, before, "1v1", 2)

    async def no_ring(self, current, probes, games, host, symbols, record, before):
        await self.challenge_1v1(host, probes, 0, 1)
        await self.battle(current, probes, (0, 1), record, before, "1v1-friend-without-a-mega-ring", 2, megas=(0,))

    async def no_ring_host(self, current, probes, games, host, symbols, record, before):
        await self.challenge_1v1(host, probes, 0, 1)
        await self.battle(current, probes, (0, 1), record, before, "1v1-host-without-a-mega-ring", 2, megas=(1,))

    async def four(self, current, probes, games, host, symbols, record, before):
        names = [a.display_name for a in host.accounts]
        await self.challenge_1v1(host, probes, 0, 1)
        await self.battle(current, probes, (0, 1), record, before, "1v1", 2)

        await probes[0].open_players()
        await probes[0].choose("Challenges")
        await probes[0].choose("New battle")
        await probes[0].choose("Free-for-All")
        # the two names in the roster's order, whichever that is; the challenge's page stays open
        _, screen = await probes[0].ready()
        pair = {f"With {names[1][:8]} & {names[2][:8]}", f"With {names[2][:8]} & {names[1][:8]}"}
        labels = [row.label for row in screen.rows if row.label in pair]
        require(len(labels) == 1, f"no single Free-for-All row for {sorted(pair)}: {[r.label for r in screen.rows]}")
        await probes[0].choose(labels[0])
        await self.accept(probes, (1, 2))
        await self.battle(current, probes, (0, 1, 2), record, before, "1v1v1", 6)

        await self.challenge_ffa(probes)
        await self.battle(current, probes, range(4), record, before, "1v1v1v1", 5)

        await self.form_teams(host, current, probes, record)
        await self.challenge_2v2(probes)
        await self.battle(current, probes, range(4), record, before, "2v2", 3)


async def run(args):
    players = {"four": 4, "three": 3}.get(args.scenario, 2)
    require(len(args.source) == players and len(args.display) == players, f"{players} sources and displays")
    facts = load_facts(args.facts) if args.facts else game_facts(args.elf or args.game)
    proof = MegaProof(args.scenario, args.watch, args.match_seconds, facts)
    await launcher_proof(args, names=PLAYER_NAMES[:players], sources=args.source, party_counts=(1,) * players,
                         match=proof.match, version=f"Native Mega Evolution proof ({args.scenario})",
                         settings=LIGHT_3D_SETTINGS if args.light_3d else "windowScale=2\n",
                         scope=__doc__.split("\n\n")[0], after_boot=into_littleroot,
                         environment=dict(SDL_FRAMEBUFFER_ACCELERATION="0"), on_harness=proof.adopt)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True,
                        help="native Linux executable, with its symbols (and its debug information unless --elf)")
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--scenario", choices=("four", "three", "two", "no-ring", "no-ring-host"), default="four")
    parser.add_argument("--source", type=Path, action="append", required=True, help="a save per player")
    parser.add_argument("--light-3d", action="store_true", help="the native 3D build's light game settings")
    parser.add_argument("--display", action="append", help="an X display per player (Linux)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0)
    parser.add_argument("--watch", type=float, default=120)
    parser.add_argument("--match-seconds", type=float, default=MATCH_SECONDS)
    parser.add_argument("--wine", type=Path, action="append", help="(not used)")
    parser.add_argument("--sdl", type=Path)
    parser.add_argument("--elf", type=Path, help="the unstripped game, for its debug information, when --game "
                        "has none (the native 3D build is over the runtime's size limit with it)")
    parser.add_argument("--facts", type=Path, help="the build's offsets as mega_facts.py wrote them (Windows: the "
                        "packaged game has no debug information)")
    parser.add_argument("--pe-symbols", type=Path, help="Windows: i686-w64-mingw32-nm -n of the game before its strip")
    parser.add_argument("--sizes", type=Path, help="Windows: nm -S of the Linux build of the same engine commit")
    args = parser.parse_args()
    if not args.display:
        require(WINDOWS, "an X display per player")
        players = {"four": 4, "three": 3}.get(args.scenario, 2)
        args.display = [f"desktop-{n}" for n in range(players)]       # Windows: one desktop; names for the records
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
