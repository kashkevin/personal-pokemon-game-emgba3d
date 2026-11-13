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
    a Gym Leader's script sends (world action "gym_coop"; --gym, Rustboro's
    Roxanne by default: since 2026-11-04 a co-op Gym battle awards its
    experience only with the win that earns the badge (KNOWN_ISSUES MS-190), so
    both trainers must still be able to earn it; Norman (--gym 5) with these
    sources is the helpers' case: no experience); the host requires a team on
    one map, as in a Gym;
  - player 2 accepts in Players > Pending challenge, both choose Enter battle;
    default moves (A) until the battle ends;
  - each game asks for the host save first (its result waits in the save's
    co-op record), then runs its own victory script with the experience award: A
    presses answer its messages (and YES to "forget a move?", the summary's
    first move), evolutions play out; then it saves on the host again;
  - with --close-during-award N, player N's game is closed (SIGTERM, as its
    window's close button) once the award is in its memory and before anything
    after it is saved, its launcher is started again (Join Game) from the host
    save made with the result waiting, and that game runs the award again: the
    same experience, once;
  - with --give-up N (KNOWN_ISSUES MS-126: a player may give up a battle with
    other players whenever they wish), player N chooses its first move and gives
    up from the waiting screen (B, Yes) while its teammate has walked away at the
    action menu: one forfeit notice, from N's game, for its own battler; the
    whole team loses (the master plays the notice as N's Run: LOST with the
    link-battle Run's mark) - both games' own result and the host's co-op result
    lost; each game runs the co-op defeat script (no whiteout) with no
    experience, no badge, the Leader not marked beaten, no money gained or lost;
    both host saves around the script as after a win; the parties unchanged;
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
import os
from pathlib import Path
import struct
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows-runtime"))
from native_launcher_battle_proof import (CHOOSE_ACTION_REQUEST, FORFEIT_ROLE, WINDOWS, drive_battle_input,  # noqa: E402
                                          idle_battle_input, launcher_proof)
from native_launcher_multi_proof import close_players, field_state, into_town  # noqa: E402
from native_coop_exp_award_proof import decode  # noqa: E402
from native_spawn_proof import SAVEBLOCK1_DATA, _save_slots, _sector_checksum  # noqa: E402
from qualify_admission_cleanup import on_worker, require  # noqa: E402
from emerald_multiplayer.flash import POKEMON_SIZE, SAVED_PARTY_OFFSET  # noqa: E402
from emerald_multiplayer.ownership import _SUBSTRUCT_OFFSETS  # noqa: E402

GYM = 1  # Rustboro (Roxanne): see the docstring; --gym
CLOSE_SLOT = -1  # --close-during-award
GIVE_UP = -1     # --give-up: the player who gives up (MS-126)
# A Gym's badge and its Leader's trainer flag (engine include/constants/flags.h FLAG_BADGE01_GET .. 08, in the co-op
# Gyms' order MP_COOP_GYM_RUSTBORO 1 .. SOOTOPOLIS 8; TRAINER_FLAGS_START + TRAINER_ROXANNE_1 265 .. TRAINER_JUAN_1 272),
# read from the running game's save block 1 (SaveBlock1.flags at 0x1270, tower_rules.FLAGS_OFFSET)
FLAG_BADGE01_GET, TRAINER_FLAGS_START, FIRST_LEADER = 0x867, 0x500, 265
OUTCOME_LOST = 2   # B_OUTCOME_LOST: the team's own result (gBattleOutcome) and the host's co-op result
HARNESS = None   # the launcher harness (on_harness), for a game closed and started again
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
    count, raw = probe.party_bytes()      # as the game keeps it at rest (party_read.py)
    return [decode(raw[i * POKEMON_SIZE:(i + 1) * POKEMON_SIZE], i) for i in range(count)]


COOP_EXP_STAGE_GAINED, COOP_EXP_STAGE_DONE = 0, 5  # src/multiplayer_coop.c


def award_done(probe) -> bool:
    """The game's co-op award reached its last stage (sCoopAward.stage, PC build), or there was nothing to award: the
    battle's experience consumed (sCoopExp.pending clear) and no Pokemon gaining any (sCoopAward's participants, sharers
    and leveled masks empty: level-100 parties, a Tower floor above the experience cap). The award then stays at its
    first stage (multiplayer_coop.c MultiplayerCoop_ExpBegin), as tower-duo-2 (2026-10-22) waited out."""
    award = probe.mem("sCoopAward", 8)
    if award[0] == COOP_EXP_STAGE_DONE:
        return True
    pending = probe.mem("sCoopExp", 2)[1]
    return award[0] == COOP_EXP_STAGE_GAINED and not pending and not (award[4] | award[5] | award[6])


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

    async def revision(s):
        return s.status.revision
    start_revisions = [await on_worker(w, revision) for w in current]
    record("parties-before", parties=before)
    for p in before:
        require(p[0]["level"] == LEAD_LEVEL, "fixture parties: the lead at Lv. 60")
    if GIVE_UP >= 0:
        from native_launcher_tower_proof import live_wallet
        START_MONEY.update({slot: live_wallet(p)["money"] for slot, p in enumerate(probes)})
        flags = [FLAG_BADGE01_GET + GYM - 1, TRAINER_FLAGS_START + FIRST_LEADER + GYM - 1]
        found = [flags_of(p, *flags) for p in probes]
        record("before-the-give-up", money=START_MONEY, badge_and_leader_beaten=found)
        require(not any(any(f) for f in found), f"the fixtures already have the badge or beat the Leader: {found}")

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
    blocks, given = [], {}
    if GIVE_UP >= 0:
        # MS-126: the giver chooses its move, then gives up from the waiting screen; its teammate has walked away at
        # its action menu. Every routed block is kept (the notice and the replies are checked after the battle).
        async def observe(s):
            service = s._server.battle_execution
            require(service.observer is None, "a previous proof observer exists")
            service.observer = lambda block: blocks.append(dict(block, at=round(time.monotonic(), 2)))
        await on_worker(current[0], observe)
        giver, other = GIVE_UP, 1 - GIVE_UP
        battlers = (0, 2)
        given.update(wait_for=CHOOSE_ACTION_REQUEST)
        drivers = [None, None]
        drivers[giver] = asyncio.create_task(drive_battle_input(
            probes[giver], lambda: view(battlers[giver]), symbols, stop, {}, give_up=given,
            other_view=lambda: view(battlers[other])))
        drivers[other] = asyncio.create_task(idle_battle_input(probes[other], lambda: view(battlers[other]), stop))
    else:
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
        # battle_finished, then (KNOWN_ISSUES MS-190) the launcher's save of the co-op result: saving, saved
        return s.status.code in ("battle_finished", "saving", "saved") and s._interaction is None
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
    if GIVE_UP >= 0:
        async def unobserve(s):
            s._server.battle_execution.observer = None
        await on_worker(current[0], unobserve)
        return await coop_given_up(current, probes, games, before, start_revisions, battle_id, blocks, given, record)

    # Each game's own victory script and experience award: the host save first (the result waits in the save), then
    # the script, then the host save again (KNOWN_ISSUES MS-190). With --close-during-award, that player's game closes
    # with the award in its memory only and its launcher starts again from the host save that has the result waiting.
    logs = [game_log_path(g) for g in games]

    async def award(slot):
        if slot == CLOSE_SLOT:
            await close_during_award(slot, current, probes, games, before, start_revisions, logs, record)
        return await finish_award(probes[slot], slot, record)
    screens = await asyncio.gather(*(award(n) for n in range(2)))
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
        if slot == CLOSE_SLOT:
            remembered = CLOSED_AWARD[slot]
            require([a["experience"] for a in after[slot]] == remembered,
                    f"slot {slot}: the award after the restart differs from the one the closed game had in memory")
            record("award-after-the-restart-equals-the-closed-games", slot=slot, experience=remembered)
    record("both-games-awarded-their-own-parties")
    # Each game saved on the host twice by itself: with the result waiting (before its script) and after the script.
    deadline = time.monotonic() + 90
    while True:
        now = [await on_worker(w, revision) for w in current]
        if all(r == b + 2 for r, b in zip(now, start_revisions)):
            break
        require(time.monotonic() < deadline and all(r <= b + 2 for r, b in zip(now, start_revisions)),
                f"the games' host saves around the award: revisions {now} from {start_revisions}")
        await asyncio.sleep(.5)
    lines = [result_lines(path) for path in logs]
    record("saved-before-and-after-the-script", revisions=now, game_logs=lines)
    for slot in range(2):
        require(any("saved with the result waiting; its script runs" in line for line in lines[slot]),
                f"slot {slot}: the game's log has no host save made with the result waiting")
        if slot == CLOSE_SLOT:
            require(any("the loaded save has a result waiting; its script runs" in line for line in lines[slot]),
                    f"slot {slot}: the restarted game did not find the waiting result in its save")
    return dict(expected=[p.party_now() for p in probes], revisions=[r + 1 for r in now])


def flags_of(probe, *flags):
    """Whether each of `flags` is set in the running game's save block 1 (SaveBlock1.flags)."""
    from emerald_multiplayer.tower_rules import FLAGS_OFFSET
    from native_launcher_tower_proof import read_at
    block1 = int.from_bytes(probe.mem("gSaveBlock1Ptr", 4), "little")
    return [bool(read_at(probe, block1 + FLAGS_OFFSET + flag // 8, 1)[0] >> (flag % 8) & 1) for flag in flags]


async def coop_given_up(current, probes, games, before, start_revisions, battle_id, blocks, given, record):
    """--give-up (MS-126): what a co-op Gym battle given up by one of the team leaves. The whole team lost: one notice
    from the giver's game for its own battler, both games' own result and the host's co-op result LOST; each game runs
    its defeat script (no whiteout) after the host save that carries the result, then saves again; no experience, no
    badge, the Leader not marked beaten, no money gained or lost; the parties as before."""
    from native_launcher_tower_proof import live_wallet
    giver = GIVE_UP
    battler = (0, 2)[giver]
    require("chosen" in given, "the giver never chose Yes on the question: " + json.dumps(given, default=str))

    def data(b):
        return bytes.fromhex(b["data"])
    notices = [b for b in blocks if b["kind"] == 8 and data(b)[0] == FORFEIT_ROLE]
    require(len(notices) == 1 and notices[0]["source"] == giver and data(notices[0])[1] == battler,
            f"expected one forfeit notice from the giver's game for battler {battler}: "
            f"{[(n['source'], data(n)[1]) for n in notices]}")

    def replies(core):
        # (command, first byte) of a core's replies for the players' battlers (TWORETURNVALUES 32, CHOSENMONRETURNVALUE
        # 33); the master's AI trainers' (battlers 1 and 3) are left out
        return [tuple(data(b)[8:10]) for b in blocks if b["kind"] == 8 and b["source"] == core and data(b)[0] == 1
                and data(b)[1] in (0, 2) and data(b)[8] in (32, 33)]
    require(replies(giver) == [(32, 0), (32, 10)], f"the giver's replies differ: {replies(giver)}")
    require(replies(1 - giver) == [(32, 13)], f"the teammate's game did not pass its turn by itself: "
            f"{replies(1 - giver)}")
    own = [p.mem("gBattleOutcome", 1)[0] for p in probes]

    async def host_records(s):
        server = s._server
        rows = server.friendships._db.execute("SELECT kind FROM activity WHERE reference=?", (battle_id,)).fetchall()
        return dict(coop_result=server.shared_world.frontier.coop_result(battle_id),
                    friendship=[row[0] for row in rows])
    host = await on_worker(current[0], host_records)
    record("coop-given-up", giver=giver, battler=battler, own_results=own, host=host, notice_at=notices[0]["at"],
           seconds_from_enter_to_yes=round(given["chosen"] - min(b["at"] for b in blocks), 1),
           presses_of_b_before_the_question=given.get("b_without_question", 0))
    require(own == [OUTCOME_LOST, OUTCOME_LOST], f"a game's own result is not a loss: {own}")
    require(host["coop_result"] == OUTCOME_LOST, f"the host's co-op result is not a loss: {host}")
    # each game's defeat script after the host save that carries the result (A presses its message)
    logs = [game_log_path(g) for g in games]
    wallets = [live_wallet(p) for p in probes]
    screens = await asyncio.gather(*(finish_award(probes[n], n, record) for n in range(2)))
    after = [own_party(p) for p in probes]
    flags = [FLAG_BADGE01_GET + GYM - 1, TRAINER_FLAGS_START + FIRST_LEADER + GYM - 1]
    for slot in range(2):
        gains = [a["experience"] - b["experience"] for a, b in zip(after[slot], before[slot])]
        badge, beaten = flags_of(probes[slot], *flags)
        money = live_wallet(probes[slot])["money"]
        record("coop-given-up-player", slot=slot, gains=gains, badge=badge, leader_beaten=beaten,
               money=[START_MONEY[slot], wallets[slot]["money"], money], screens=screens[slot],
               levels=[(b["level"], a["level"]) for a, b in zip(after[slot], before[slot])])
        require(not any(gains), f"slot {slot}: experience after a lost co-op battle: {gains}")
        require(not badge and not beaten, f"slot {slot}: the badge ({badge}) or the Leader beaten ({beaten}) after a "
                "lost co-op battle")
        require(money == wallets[slot]["money"] == START_MONEY[slot],
                f"slot {slot}: money changed: {START_MONEY[slot]} -> {wallets[slot]['money']} -> {money}")
        require(probes[slot].mem("gPartiesCount", 4)[2] == 0, f"slot {slot}: the teammate's party is still held")
    # each game saved on the host twice by itself, as after a win: with the result waiting, then after its script
    async def revision(s):
        return s.status.revision
    deadline = time.monotonic() + 90
    while True:
        now = [await on_worker(w, revision) for w in current]
        if all(r == b + 2 for r, b in zip(now, start_revisions)):
            break
        require(time.monotonic() < deadline and all(r <= b + 2 for r, b in zip(now, start_revisions)),
                f"the games' host saves around the defeat script: revisions {now} from {start_revisions}")
        await asyncio.sleep(.5)
    lines = [result_lines(path) for path in logs]
    record("saved-before-and-after-the-defeat-script", revisions=now, game_logs=lines)
    for slot in range(2):
        require(any("saved with the result waiting; its script runs" in line for line in lines[slot]),
                f"slot {slot}: the game's log has no host save made with the result waiting")
    return dict(expected=[p.party_now() for p in probes], revisions=[r + 1 for r in now])


START_MONEY = {}   # --give-up: each game's money when the match began
CLOSED_AWARD = {}
WATCHERS = []


async def watch_status(slot, worker):
    """Diagnostics: the restarted launcher's status as it changes (why a host save was or was not made)."""
    async def peek(s):
        st = s.status
        return [getattr(st.state, "value", str(st.state)), st.code, st.revision, st.save_available,
                getattr(s, "last_save_error", None), s._interaction is not None, s.can_save]
    last = None
    while True:
        try:
            now = await on_worker(worker, peek)
        except Exception as error:   # the worker stopped
            print(json.dumps({"diagnostic": "status-watch-ended", "slot": slot, "error": repr(error)}), flush=True)
            return
        if now != last:
            print(json.dumps({"diagnostic": "launcher-status", "slot": slot, "status": now,
                              "t": round(time.monotonic(), 1)}), flush=True)
            last = now
        await asyncio.sleep(.1)


def game_log_path(game):
    """The game's own log (stdout and stderr: runtime.log in its launch folder, which the launcher's running game
    names; else the process's working directory, Linux)."""
    path = getattr(game, "log_path", None)
    if path is not None:
        return Path(path)
    return Path(os.readlink(f"/proc/{game.process.pid}/cwd")) / "runtime.log"


def result_lines(paths):
    """The game log's co-op result lines (multiplayer_coop.c ResultLog), from every launch of that player."""
    if isinstance(paths, Path):
        paths = [paths]
    lines = []
    for path in paths:
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        lines += [line.strip() for line in text.splitlines() if line.startswith("co-op result:")]
    return lines


async def close_during_award(slot, current, probes, games, before, start_revisions, logs, record):
    """The game closed with the award in its memory only, then its launcher started again (Join Game)."""
    harness = HARNESS
    probe = probes[slot]

    async def revision(s):
        return s.status.revision
    # 1. The host save made with the result waiting.
    async with asyncio.timeout(120):
        while await on_worker(current[slot], revision) < start_revisions[slot] + 1:
            await asyncio.sleep(.2)
    # 2. The award in the game's memory (the script has applied it and shows its first message), nothing saved since.
    async with asyncio.timeout(120):
        while True:
            party = own_party(probe)
            if party[0]["experience"] > before[slot][0]["experience"]:
                await asyncio.sleep(1)
                again = own_party(probe)
                if [m["experience"] for m in again] == [m["experience"] for m in party]:
                    break
            await asyncio.sleep(.1)
    memory = [m["experience"] for m in own_party(probe)]
    saved = await on_worker(current[slot], revision)
    require(saved == start_revisions[slot] + 1, f"slot {slot}: saved again before the close ({saved})")
    CLOSED_AWARD[slot] = memory
    record("award-in-memory-only", slot=slot, experience=memory, revision=saved, log=result_lines(logs[slot]))
    game = games[slot]
    await harness.close_game(game, probe)   # SIGTERM: the window's close button
    await harness.poll_until(lambda: game.process.returncode is not None, 60)
    record("game-closed-during-the-award", slot=slot, exit_code=game.process.returncode)
    await harness.poll_until(lambda: not current[slot].busy, 180)
    again = await harness.start("rejoin", slot)
    WATCHERS.append(asyncio.create_task(watch_status(slot, again.worker)))
    logs[slot] = [logs[slot], game_log_path(again.game)]
    started = await harness.ready(again)
    harness.players[slot] = again
    current[slot], games[slot], probes[slot] = again.worker, again.game, again.probe
    require(started in (start_revisions[slot] + 1, start_revisions[slot] + 2),
            f"slot {slot}: the restarted game is not from the host save with the result waiting ({started})")
    record("restarted-from-the-host-save", slot=slot, revision=started, pid=again.game.process.pid)


async def after_boot(phase, slot, probe, companion):
    await into_town(phase, slot, probe, companion)


def adopt(harness):
    global HARNESS
    HARNESS = harness


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
    if not args.display:
        require(WINDOWS, "an X display per player")
        args.display = ["desktop-0", "desktop-1"]           # Windows: one desktop; names for the records
    root = args.output.resolve()
    sources = []
    fixtures = root.parent / (root.name + "-fixtures")
    fixtures.mkdir(parents=True, exist_ok=False)
    for name, source in (("a", args.source_a), ("b", args.source_b)):
        target = fixtures / f"coop-{name}.sav"
        boost_lead(source, target)
        sources.append(target)
    global GYM, CLOSE_SLOT, GIVE_UP
    GYM, CLOSE_SLOT, GIVE_UP = args.gym, args.close_during_award, args.give_up
    require(GIVE_UP < 0 or CLOSE_SLOT < 0, "--give-up and --close-during-award: one at a time")
    await launcher_proof(args, names=NAMES, sources=tuple(sources), party_counts=(2, 1), match=coop_match,
                         version="Native co-op proof", after_boot=after_boot, on_harness=adopt,
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
    parser.add_argument("--display", action="append", help="an X display per player (Linux)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0)
    parser.add_argument("--wine", type=Path, action="append")
    parser.add_argument("--sdl", type=Path)
    parser.add_argument("--elf", type=Path)
    parser.add_argument("--pe-symbols", type=Path, help="Windows: i686-w64-mingw32-nm -n of the game before its strip")
    parser.add_argument("--sizes", type=Path, help="Windows: nm -S of the Linux build of the same engine commit")
    parser.add_argument("--runtime-extra", type=Path, action="append", help="Windows: another file beside the game")
    parser.add_argument("--gym", type=int, default=GYM, help="MP_COOP_GYM_*: 1 Rustboro (default) .. 8 Sootopolis")
    parser.add_argument("--close-during-award", type=int, default=-1, choices=(-1, 0, 1),
                        help="close this player's game during its award, then start its launcher again (1: the friend)")
    parser.add_argument("--give-up", type=int, default=-1, choices=(-1, 0, 1),
                        help="this player chooses its move and gives up from the waiting screen while its teammate has "
                             "walked away (MS-126; 1: the friend): the team must lose, with nothing gained")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
