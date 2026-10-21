"""Two native games through the whole launcher: a co-op Gym battle and its experience.

Co-op battles award experience (owner decision 2026-10-13; engine
src/multiplayer_coop.c): each player's own game notes, during the co-op battle,
which of its own Pokemon faced each opposing Pokemon and which could still
battle when it fell, and after the battle has released the party awards its own
party once (EventScript_MultiplayerCoopExp, run by the co-op victory script).
This proof plays a real co-op Gym battle with two native games and checks both
parties afterwards, with the launcher harness of native_launcher_battle_proof.py
(real launcher workers, production world, enrollment and Players menus):

  - the two sources (menu-a: two Pokemon, menu-b: one) are private copies of test saves whose
    lead is raised to Lv. 60 with Crunch as its first move and a high Attack
    (a test fixture, see `boost_lead`), so the pair wins Norman's seven-Pokemon
    co-op battle by pressing A in reasonable time (with Lv. 60 stats and their
    own first moves, Scratch and Pound, run native-launcher-coop-5 was still
    battling after 900 s: the native battle relay moves about 2.8 controller
    blocks a second in the cloud);
  - both stand in Littleroot (a game that starts on Route 101 walks into the town, as the 2v2 proof's
    into_town);
  - player 1 invites player 2 to a team in the Players menu, player 2 accepts;
  - player 1's companion asks the host for the co-op Gym challenge, the request
    a Gym Leader's script sends (world action "gym_coop"; Petalburg, Norman:
    a trainer who cannot yet challenge Norman alone keeps only the prize money,
    so no Gym story script runs outside the Gym); the host requires a team on
    one map, as in a Gym;
  - player 2 accepts in Players > Pending challenge, both choose Enter battle;
    default moves (A) until the battle ends;
  - each game then runs its own victory script with the experience award: A
    presses answer its messages (and YES to "forget a move?", the summary's
    first move), evolutions play out;
  - checks, from each game's memory: every Pokemon of its own that could battle
    gained experience, its lead (sent out) the most; Pokemon that grew; the
    teammate's party is no longer held (each game changes only its own party);
    each game's experience is in its next save (revision 2) and survives a
    fresh Continue (the harness's canonical checks, with the new parties).

    PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime \\
      python scripts/multiplayer/native_launcher_coop_proof.py \\
        --game ../engine-stability/pokeemerald-mp-diorama --rom pokeemerald.gba --manifest manifest.json \\
        --source-a menu-a.sav --source-b menu-b.sav --display :98 --display :97 \\
        --output /private/multiplayer-proof/native-launcher-coop-1
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import struct
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows-runtime"))
from native_launcher_battle_proof import drive_battle_input, launcher_proof  # noqa: E402
from native_launcher_multi_proof import close_players, field_state, into_town  # noqa: E402
from native_coop_exp_award_proof import decode  # noqa: E402
from native_spawn_proof import SAVEBLOCK1_DATA, _save_slots, _sector_checksum  # noqa: E402
from qualify_admission_cleanup import on_worker, require  # noqa: E402
from emerald_multiplayer.flash import POKEMON_SIZE, SAVED_PARTY_OFFSET  # noqa: E402
from emerald_multiplayer.ownership import _SUBSTRUCT_OFFSETS  # noqa: E402

GYM = 5  # Petalburg (Norman): see the docstring
LEAD_LEVEL = 60
LEAD_MOVE = 242  # MOVE_CRUNCH: physical Dark, 80 power; nothing among Norman's and Caroline's
                 # Pokemon is immune (Kecleon's Protean can make it a Ghost, immune to Scratch/Pound)
LEAD_MOVE_PP = 15
LEAD_ATTACK = 320
NAMES = ("Coop Host", "Coop Friend")


def medium_slow(level: int) -> int:
    return 6 * level ** 3 // 5 - 15 * level ** 2 + 100 * level - 140


def boost_lead(source: Path, target: Path, level: int = LEAD_LEVEL) -> None:
    """A private test fixture: the copy's lead (a Torchic or Treecko, both
    medium-slow) at `level`: its experience, level and party stats (full HP).
    The record's checksum and the sector checksum are recomputed; nothing else
    changes (the HP lost stays as it was). The game recomputes real stats on the
    next level-up."""
    data = bytearray(source.read_bytes())
    _, sectors = _save_slots(data)
    base = sectors[1]
    start = base + SAVED_PARTY_OFFSET
    if SAVED_PARTY_OFFSET + POKEMON_SIZE > SAVEBLOCK1_DATA:
        raise ValueError("the lead is outside the first SaveBlock1 sector")
    mon = bytearray(data[start:start + POKEMON_SIZE])
    personality, ot_id = struct.unpack_from("<II", mon)
    key = personality ^ ot_id
    words = [value ^ key for value in struct.unpack_from("<12I", mon, 32)]
    growth = [row[personality % 24] for row in _SUBSTRUCT_OFFSETS][0] * 3
    species = words[growth] & 0x7FF
    if species not in (252, 255):  # Treecko, Torchic: medium slow
        raise ValueError(f"unexpected lead species {species}")
    words[growth + 1] = (words[growth + 1] & ~0x1FFFFF) | medium_slow(level)
    # First move (PokemonSubstruct1: move1 is the low 11 bits of its first
    # half-word, pp1 the low 7 bits of byte 8).
    attacks = [row[personality % 24] for row in _SUBSTRUCT_OFFSETS][1] * 3
    words[attacks] = (words[attacks] & ~0x7FF) | LEAD_MOVE
    words[attacks + 2] = (words[attacks + 2] & ~0x7F) | LEAD_MOVE_PP
    struct.pack_into("<H", mon, 28, sum((v & 0xFFFF) + (v >> 16) for v in words) & 0xFFFF)
    struct.pack_into("<12I", mon, 32, *(value ^ key for value in words))
    mon[84] = level
    # The box keeps the HP lost (max HP - HP) in its header: keep it, so the box
    # (and the host's enrolled inventory) is unchanged by the new max HP.
    hp, max_hp = struct.unpack_from("<HH", mon, 86)
    struct.pack_into("<7H", mon, 86, 210 - (max_hp - hp), 210, LEAD_ATTACK, 120, 140, 160, 120)  # HP, max HP, Atk, Def, Spe, SpA, SpD
    data[start:start + POKEMON_SIZE] = mon
    struct.pack_into("<H", data, base + 0xFF6, _sector_checksum(data, base, SAVEBLOCK1_DATA))
    target.write_bytes(bytes(data))
    target.chmod(0o600)


def own_party(probe) -> list[dict]:
    count = probe.mem("gPartiesCount", 1)[0]
    raw = probe.mem("gParties", 600)
    return [decode(raw[i * POKEMON_SIZE:(i + 1) * POKEMON_SIZE], i) for i in range(count)]


COOP_EXP_STAGE_DONE = 5  # src/multiplayer_coop.c


def award_done(probe) -> bool:
    """The game's co-op award reached its last stage (sCoopAward.stage, PC build)."""
    return probe.mem("sCoopAward", 1)[0] == COOP_EXP_STAGE_DONE


def calm(probe) -> bool:
    state = field_state(probe)
    return (state.get("callback2") == "CB2_Overworld" and state.get("script_status") != 0
            and not state.get("players_menu_active"))


async def finish_award(probe, slot, record, seconds=600):
    """A presses until the game's victory script (with the experience award) is over
    and the field has been calm for five seconds. Records the screens passed."""
    screens, calm_since, deadline = [], None, time.monotonic() + seconds
    while time.monotonic() < deadline:
        state = field_state(probe)
        screen = state.get("callback2")
        if not screens or screens[-1] != screen:
            screens.append(screen)
        if calm(probe) and award_done(probe):
            calm_since = calm_since or time.monotonic()
            if time.monotonic() - calm_since >= 5:
                record("coop-award-finished", slot=slot, screens=screens)
                return screens
            await asyncio.sleep(.2)
            continue
        calm_since = None
        await probe.press(1, frames=10, release=24)  # A: messages, YES, the summary's first move
        await asyncio.sleep(.3)
    raise AssertionError(f"slot {slot}: the award did not finish: {field_state(probe)} {screens}")


async def logged_driver(probe, battler, view, symbols, stop):
    """drive_battle_input (native_launcher_battle_proof.py) with a log line on every change."""
    from qualify_menu_battle import party_action
    last, last_at = None, 0.0
    while not stop.is_set():
        room = await view()
        state = await probe.battle()
        action = party_action(room["pending"], state, symbols) if room["state"] == "executing" else "wait"
        signature = (room["state"], room["pending"], state["state"], action)
        if signature != last or time.monotonic() - last_at > 5:
            print(json.dumps(dict(diagnostic="driver", battler=battler, room=room["state"], pending=room["pending"],
                                  mailbox=state["state"], action=action, t=round(time.monotonic(), 1))), flush=True)
            last, last_at = signature, time.monotonic()
        if room["state"] in ("closed", "aborted", "recovery_required"):
            return
        if stop.is_set():
            return
        if action == "next-party":
            await probe.press(128, frames=12, release=18)
            moved = await probe.battle()
            current = await view()
            if (not stop.is_set() and current["state"] == "executing" and current["pending"] == 21
                    and moved["state"] == 5 and symbols["Task_HandleChooseMonInput"][0] & ~1 in moved["active"]
                    and moved["cursor"] != state["cursor"] and 0 <= moved["cursor"] < moved["count"]):
                await probe.press(1, frames=12, release=18)
        elif action != "wait":
            await probe.press(2 if action == "dismiss" else 1, frames=12, release=30 if action == "dismiss" else 18)
        else:
            await asyncio.sleep(.05)


async def coop_match(current, probes, games, host, symbols, record):
    before = [own_party(p) for p in probes]
    record("parties-before", parties=before)
    for p in before:
        require(p[0]["level"] == LEAD_LEVEL, "fixture parties: the lead at Lv. 60")

    # A team, through the ordinary Players menus.
    await probes[0].open_players()
    await probes[0].choose(host.accounts[1].display_name, prefix=True)
    await probes[0].choose("Invite to team")
    await probes[1].open_players()
    await probes[1].choose("Team invitation")
    await probes[1].choose("Accept invitation")
    await close_players(probes[0])
    await close_players(probes[1])

    async def teammate(s):
        return s._companion._world_teammate
    async with asyncio.timeout(20):
        while not all([await on_worker(w, teammate) for w in current]):
            await asyncio.sleep(.1)
    record("ordinary-native-team-formed")

    # What a Gym Leader's script asks the host for (world action "gym_coop").
    async def ask(s):
        return await s._companion.world_rpc("gym_coop", gym=GYM)
    request = await on_worker(current[0], ask)
    battle_id = request["battle_id"]
    record("host-issued-coop-gym-challenge", gym=GYM, battle_id=battle_id)

    await probes[1].open_players()
    await probes[1].choose("Pending challenge")
    await probes[1].choose("Accept challenge")
    await probes[0].open_players()
    await probes[0].choose("Pending challenge")
    async with asyncio.timeout(30):
        while not all(screen.admission_action for _, screen in [await p.ready() for p in probes]):
            await asyncio.sleep(.05)
    async def descriptor(s):
        values = s._companion._bridge.menu_session.menu._battles
        require(len(values) == 1 and values[0]["mode"] == 4, "expected one co-op challenge")
        return json.loads(json.dumps(values[0]))
    challenge = await on_worker(current[0], descriptor)
    require(challenge["battle_id"] == battle_id and challenge.get("gym") == GYM, "the co-op challenge differs")
    record("coop-challenge-accepted", players=challenge["players"])
    await asyncio.gather(*(p.choose("Enter battle", wait=False) for p in probes))
    record("both-native-Enter-selected", battle_id=battle_id)

    # The master (slot 0) owns battler 0 and both AI trainers; slot 1 owns battler 2.
    async def view(battler):
        async def read(s):
            room = s._server.battle_execution.rooms.get(battle_id)
            if room is None:
                return dict(state="waiting", pending=None)
            return dict(state=room.state, pending=None if room.route is None else room.route.validator.pending[battler])
        return await on_worker(current[0], read)
    stop = asyncio.Event()
    drivers = [asyncio.create_task(logged_driver(p, b, lambda b=b: view(b), symbols, stop))
               for p, b in zip(probes, (0, 2))]
    started = time.monotonic()
    async def room_of(host_session):
        room = host_session._server.battle_execution.rooms.get(battle_id)
        if room is None:
            return None
        return dict(state=room.state, error=getattr(room, "error", None),
                    pending=None if room.route is None else list(room.route.validator.pending))

    async def finished(s):
        if s._save_failed and s._interaction is None or s._game is None or s._game.process.returncode is not None:
            raise AssertionError("launcher retained a battle failure or lost its original game: "
                                 + json.dumps(dict(status=s.status.code), default=str))
        return s.status.code == "battle_finished" and s._interaction is None
    try:
        async with asyncio.timeout(1800):
            report_at = 0
            while True:
                for driver in drivers:
                    if driver.done():
                        await driver
                if all([await on_worker(w, finished) for w in current]):
                    break
                if time.monotonic() >= report_at:
                    record("coop-battle-progress", elapsed_seconds=round(time.monotonic() - started, 1),
                           room=await on_worker(current[0], room_of))
                    report_at = time.monotonic() + 15
                await asyncio.sleep(.1)
    finally:
        stop.set()
        await asyncio.gather(*drivers)
    async def outcome(s):
        history = (await s._companion.battle_challenge_rpc("history"))["result"]
        values = [v for v in history if v["battle_id"] == battle_id]
        return values[0] if values else None
    result = await on_worker(current[0], outcome)
    record("coop-battle-finished", seconds=round(time.monotonic() - started, 1), result=result)

    # Each game's own victory script and experience award.
    screens = await asyncio.gather(*(finish_award(p, n, record) for n, p in enumerate(probes)))
    after = [own_party(p) for p in probes]
    record("parties-after", parties=after)
    for slot in range(2):
        gains = [a["experience"] - b["experience"] for a, b in zip(after[slot], before[slot])]
        able = [b["hp"] > 0 for b in before[slot]]
        record("coop-experience", slot=slot, gains=gains,
               levels=[(b["level"], a["level"]) for a, b in zip(after[slot], before[slot])],
               species=[(b["species"], a["species"]) for a, b in zip(after[slot], before[slot])],
               screens=screens[slot])
        require(gains[0] > 0, f"slot {slot}: the lead gained no experience")
        require(all(g > 0 for g, ok in zip(gains, able) if ok), f"slot {slot}: a Pokemon that could battle gained nothing")
        require(all(gains[0] >= g for g in gains[1:]), f"slot {slot}: a Pokemon not sent out gained more than the lead")
        require(probes[slot].mem("gPartiesCount", 4)[2] == 0, f"slot {slot}: the teammate's party is still held")
    record("both-games-awarded-their-own-parties")
    return dict(expected=[p.party_now() for p in probes])


async def after_boot(phase, slot, probe, companion):
    await into_town(phase, slot, probe, companion)


async def run(args):
    # A setup failure's cause is kept from the user's screen; print it for the log.
    import traceback
    import emerald_multiplayer.launcher_setup as launcher_setup
    original_error = launcher_setup._error

    def logged(error):
        traceback.print_exception(error)
        return original_error(error)
    launcher_setup._error = logged
    # Diagnostics: why the host's native execution failed, with where.
    import emerald_multiplayer.battle_execution as battle_execution
    original_fail = battle_execution.BattleExecutionService._fail

    def fail(self, room, reason, _original=original_fail):
        print(json.dumps(dict(diagnostic="native-execution-failed", reason=str(reason),
                              exception=traceback.format_exc(limit=12))), flush=True)
        return _original(self, room, reason)
    battle_execution.BattleExecutionService._fail = fail
    original_dispatch = battle_execution.BattleExecutionService._dispatch

    async def dispatch(self, room, actor, command, _original=original_dispatch):
        result = await _original(self, room, actor, command)
        response = result[1]
        if int(response.status) not in (0,) and getattr(response.status, "name", "") != "BUSY":
            print(json.dumps(dict(diagnostic="native-command-refused", actor=actor, opcode=str(command.opcode),
                status=str(response.status), source=command.source_slot, kind=getattr(command, "kind", None),
                block=getattr(command, "block_sequence", None), offset=getattr(command, "offset", None),
                total=getattr(command, "total_size", None), data=bytes(command.data[:96]).hex(),
                reply=bytes(response.data[:64]).hex()), default=str), flush=True)
        return result
    battle_execution.BattleExecutionService._dispatch = dispatch
    # Diagnostics for a refused co-op admission: what the host held.
    import emerald_multiplayer.battle_admission_host as admission_host
    for name in dir(admission_host):
        cls = getattr(admission_host, name)
        if isinstance(cls, type) and hasattr(cls, "prove") and hasattr(cls, "_read"):
            original_prove = cls.prove

            def prove(self, actor, lease, request, _original=original_prove):
                try:
                    return _original(self, actor, lease, request)
                except Exception as error:
                    try:
                        value = self._read(request["battle_id"])
                        view = value["view"]
                        print(json.dumps(dict(diagnostic="admission-prove-refused", error=repr(error), actor=actor,
                            canceled=value["canceled"], state=view["state"], consent=sorted(view["consent"]),
                            players=view["players"], identities=sorted(value["identities"]),
                            generation=[view["generation"], request.get("generation")],
                            identity_match=value["identities"].get(actor) == self.require_identity(request),
                            held=value["identities"].get(actor), offered=self.require_identity(request)),
                            default=str), flush=True)
                    except Exception as inner:  # noqa: BLE001
                        print("diagnostic failed", repr(inner), flush=True)
                    raise
            cls.prove = prove
    root = args.output.resolve()
    sources = []
    fixtures = root.parent / (root.name + "-fixtures")
    fixtures.mkdir(parents=True, exist_ok=False)
    for name, source in (("a", args.source_a), ("b", args.source_b)):
        target = fixtures / f"coop-{name}.sav"
        boost_lead(source, target)
        sources.append(target)
    await launcher_proof(args, names=NAMES, sources=tuple(sources), party_counts=(2, 1), match=coop_match,
                         version="Native co-op proof", after_boot=after_boot,
                         settings="windowScale=2\n", scope=__doc__.split("\n\n")[0],
                         # The harness drives the GBA start menu and Players menu by their
                         # memory (written before the native PC UI); the co-op battle and its
                         # award do not depend on the UI layer (the award's screens with the
                         # native UI: native_coop_exp_award_proof.py).
                         environment=dict(SDL_FRAMEBUFFER_ACCELERATION="0", PKMN_NATIVE_UI="0"))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-a", type=Path, required=True)
    parser.add_argument("--source-b", type=Path, required=True)
    parser.add_argument("--display", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0)
    parser.add_argument("--wine", type=Path, action="append")
    parser.add_argument("--sdl", type=Path)
    parser.add_argument("--elf", type=Path)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
