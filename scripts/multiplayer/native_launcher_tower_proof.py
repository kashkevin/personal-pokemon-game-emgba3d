"""Two native games through the whole launcher: Battle Tower: Legends, solo and Duo, in real games.

The Tower (docs/battle-tower-legends.md) with the launcher harness of native_launcher_battle_proof.py (real launcher
workers, the production world, enrollment, the Players menu): two Linux games whose sources' leads are raised to Lv. 60
with Crunch first (native_launcher_coop_proof.py's boost_lead; a test fixture), above the Tower experience cap of a
trainer without badges (Lv. 15), so a Tower win never gives them experience. Every step is a player's presses in the
game's own menus; the checks read the games' memory (the save's Tower record mirror, the party), the host's Tower view
and, after the harness's saves, the canonical checkpoints (money, the Bag, Battle Points, the record).

  --scenario solo     player 1: START > PLAYER > TOWER opens the Tower's home page (the Players menu's page 2); "Solo:
                      floor N" > "Start the battle" for floors 1 to --floors (default 11) in turn: the game closes the
                      menu, shows the floor's intro, battles the floor's trainer (A: the lead's first move), shows the
                      result; the host settles it and the game's record reaches P = N + 1, H = N; the lead's experience
                      never moves (at the cap); the party is healed. Floor 10 is Brock, the first checkpoint: its
                      first-clear prize (10 Rare Candy, $10,000) and every floor's BP and money are in the next save as
                      the host's rules (tower_rewards.py) say. Player 2 (--weak-b: its lead Lv. 1 with Splash only, a
                      second fixture) loses floor 1 in its game: its P stays 1, nothing is paid.
  --scenario duo      a team (Players > invite, accept); Tower > Duo > "Invite: floor F" (F the lower progress floor),
                      accepted, both Ready: the host issues the native co-op battle against the floor's two trainers;
                      both enter it (A presses) and win; each game's co-op award gives nothing above its cap; the host
                      settles each player's result (a replay changes nothing; a climb advances).
  --scenario mega     as duo, from saves whose Tower records say floor 40 cleared (a third fixture: the record mirror,
                      which the host imports on the first Tower action): a Duo replay of floor 40, Norman and his
                      partner; the master game's battle shows Norman's Kangaskhan Mega Evolved.
  --scenario forfeit  player 1 from a save whose record says floor 12 cleared (P = 13): floor 13 started, the game
                      closed in the battle (an ordinary close), started again through the launcher: the Tower counts
                      floor 13 as a loss ("Floor 13: counted as a loss") and P = 11 (checkpoint 10 + 1); H stays 12.

    PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime \\
      python scripts/multiplayer/native_launcher_tower_proof.py --scenario solo \\
        --game ../engine/pokeemerald-mp --rom pokeemerald.gba --manifest manifest.json \\
        --source-a menu-a.sav --source-b menu-b.sav --display :98 --display :97 \\
        --output /private/multiplayer-proof/native-launcher-tower-solo-1
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
from pathlib import Path
import signal
import struct
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows-runtime"))
from native_launcher_battle_proof import NativeProbe, launcher_proof  # noqa: E402
from native_launcher_coop_proof import boost_lead, finish_award, logged_driver, own_party  # noqa: E402
from native_launcher_multi_proof import close_players, field_state, into_town  # noqa: E402
from native_spawn_proof import SAVEBLOCK1_DATA, _save_slots, _sector_checksum  # noqa: E402
from qualify_admission_cleanup import on_worker, require  # noqa: E402
from qualify_launcher_session import inspect_closed_head  # noqa: E402
from emerald_multiplayer import tower_rewards  # noqa: E402
from emerald_multiplayer.flash import (POKEMON_SIZE, SAVED_PARTY_OFFSET, TOWER_RECORD_OFFSET, TOWER_RECORD_SIZE,  # noqa: E402
                                       inspect_flash, parse_tower_record)
from emerald_multiplayer.menu_mailbox import unpack_screen  # noqa: E402
from emerald_multiplayer.ownership import _SUBSTRUCT_OFFSETS  # noqa: E402
from emerald_multiplayer.ownership_protocol import OWNERSHIP_PROFILE  # noqa: E402

A, B, START, DOWN = 1, 2, 8, 128
PLAYER_OPTIONS, TRAINER_CARD, TOWER = 15, 16, 23          # src/start_menu.c MENU_ACTION_*
TITLE = "Battle Tower: Legends"
NAMES = ("Tower Host", "Tower Friend")
CAP_NO_BADGES = 15
MOVE_SPLASH = 150
# Save block 1 (include/global.h): money at 0x490, the bag's slots at 0x560 (items pocket first); save block 2's
# encryption key at 0xAC and the Battle Frontier's points at frontier + 0xEB8 (native_launcher_ffa_proof.py's offsets).
MONEY, BAG, BAG_SLOTS, ENCRYPTION_KEY = 0x490, 0x560, 186, 0xAC
FRONTIER, BATTLE_POINTS = 0x64C, 0xEB8
ITEM_RARE_CANDY = 102


# The Players menu's Tower screens carry style bytes: read them as the Tower-capable reader does.
async def _ready(self, timeout=15):
    async with asyncio.timeout(timeout):
        while True:
            row = self.read()
            if row["active"] and not row["waiting"]:
                try:
                    return row, unpack_screen(row["screen"], allow_battle_admission=True, allow_tower=True)[1]
                except ValueError:
                    pass  # a screen being copied in
            await asyncio.sleep(.03)


NativeProbe.ready = _ready


# ---------------------------------------------------------------------------------------------------------- fixtures
def _block3_positions(data: bytes, base_sectors):
    """Where SaveBlock3's bytes [offset, offset + 64) of the Tower record live in a bank: (file offset, length) pieces
    (SaveBlock3 is kept 116 bytes a sector, after each sector's 3968 data bytes)."""
    pieces = []
    for section_id in range(14):
        lo, hi = section_id * 116, section_id * 116 + 116
        a, b = max(lo, TOWER_RECORD_OFFSET), min(hi, TOWER_RECORD_OFFSET + TOWER_RECORD_SIZE)
        if a < b:
            pieces.append((base_sectors[section_id] + 3968 + (a - lo), b - a, a - TOWER_RECORD_OFFSET))
    return pieces


def with_tower_record(source: Path, target: Path, highest: int, progress: int) -> None:
    """A private test fixture: the copy's Tower record mirror says floor `highest` cleared and `progress` next (claims
    and pending result none, revision 1, its CRC-32), in the save's newest bank; nothing else changes. The host imports
    it on the player's first Tower action (design section 9)."""
    import zlib
    data = bytearray(source.read_bytes() if source != target else target.read_bytes())
    _, sectors = _save_slots(data)
    body = struct.pack("<IBBBBIBBHHH40s", 0x314C5754, 1, highest, progress, 0, 0, 0, 0, 0, 1, 0, bytes(40))
    record = body + struct.pack("<I", zlib.crc32(body))
    for offset, length, start in _block3_positions(data, sectors):
        data[offset:offset + length] = record[start:start + length]
    target.write_bytes(bytes(data))
    target.chmod(0o600)


def weaken_lead(source: Path, target: Path) -> None:
    """A private test fixture: the copy's lead at Lv. 1 with Splash alone and 1 HP: it loses any Tower floor."""
    data = bytearray(source.read_bytes())
    _, sectors = _save_slots(data)
    base = sectors[1]
    start = base + SAVED_PARTY_OFFSET
    mon = bytearray(data[start:start + POKEMON_SIZE])
    personality, ot_id = struct.unpack_from("<II", mon)
    key = personality ^ ot_id
    words = [value ^ key for value in struct.unpack_from("<12I", mon, 32)]
    growth = [row[personality % 24] for row in _SUBSTRUCT_OFFSETS][0] * 3
    words[growth + 1] &= ~0x1FFFFF                       # experience 0: level 1
    attacks = [row[personality % 24] for row in _SUBSTRUCT_OFFSETS][1] * 3
    words[attacks] = MOVE_SPLASH                         # Splash, no second move
    words[attacks + 1] = 0
    words[attacks + 2] = (words[attacks + 2] & ~0xFFFFFFFF) | 40   # its PP; the others none
    struct.pack_into("<H", mon, 28, sum((v & 0xFFFF) + (v >> 16) for v in words) & 0xFFFF)
    struct.pack_into("<12I", mon, 32, *(value ^ key for value in words))
    mon[84] = 1
    struct.pack_into("<7H", mon, 86, 1, 11, 5, 5, 5, 5, 5)
    data[start:start + POKEMON_SIZE] = mon
    struct.pack_into("<H", data, base + 0xFF6, _sector_checksum(data, base, SAVEBLOCK1_DATA))
    target.write_bytes(bytes(data))
    target.chmod(0o600)


# ---------------------------------------------------------------------------------------------------------- reading
def read_at(probe, address: int, size: int) -> bytes:
    with open(f"/proc/{probe.pid}/mem", "rb", buffering=0) as memory:
        memory.seek(address)
        return memory.read(size)


def tower_record(probe):
    """The running game's Tower record mirror (gSaveBlock3Ptr->tower), parsed as the app parses a save's."""
    pointer = int.from_bytes(probe.mem("gSaveBlock3Ptr", 4), "little")
    return parse_tower_record(read_at(probe, pointer + TOWER_RECORD_OFFSET, TOWER_RECORD_SIZE))


async def tower_view(worker):
    async def view(s):
        return await s._companion.tower_rpc("status")
    return await on_worker(worker, view)


def wallet_of(checkpoint_payload: bytes) -> dict:
    """Money, Rare Candy and Battle Points of a checkpoint, decrypted, and its Tower record."""
    parsed = inspect_flash(checkpoint_payload, save_profile=OWNERSHIP_PROFILE)
    block1, block2 = parsed.save_block1, parsed.save_block2
    key = struct.unpack_from("<I", block2, ENCRYPTION_KEY)[0]
    money = struct.unpack_from("<I", block1, MONEY)[0] ^ key
    candy = sum(quantity ^ (key & 0xFFFF) for item, quantity in
                (struct.unpack_from("<HH", block1, BAG + 4 * i) for i in range(BAG_SLOTS)) if item == ITEM_RARE_CANDY)
    bp = struct.unpack_from("<H", block2, FRONTIER + BATTLE_POINTS)[0] if len(block2) >= FRONTIER + BATTLE_POINTS + 2 else None
    return dict(money=money, rare_candy=candy, bp=bp, tower=None if parsed.tower is None else dataclasses.asdict(parsed.tower))


def expected_solo_pay(floors) -> dict:
    """What first clears of `floors` pay (tower_rewards.py): money, Rare Candy, BP."""
    money = candy = bp = 0
    for floor in floors:
        prize = tower_rewards.PRIZES.get(floor)
        bp += tower_rewards.first_clear_bp(floor)
        if prize is None:
            money += tower_rewards.first_clear_money(floor)
        else:
            money += prize.money
            candy += sum(quantity for item, quantity in prize.items if item == ITEM_RARE_CANDY)
    return dict(money=money, rare_candy=candy, bp=bp)


# ---------------------------------------------------------------------------------------------------------- playing
async def open_tower(probe):
    """START > PLAYER > TOWER: the Players menu opens on the Tower's home page (the Players menu's page 2)."""
    await probe.press(START, release=60)
    row = await probe.snapshot(lambda r: 0 < r["count"] <= len(r["actions"]) and PLAYER_OPTIONS in r["actions"][:r["count"]])
    target = row["actions"][:row["count"]].index(PLAYER_OPTIONS)
    for _ in range((target - row["start_cursor"]) % row["count"]):
        await probe.press(DOWN)
    await probe.press(A, release=60)
    row = await probe.snapshot(lambda r: r["actions"][0] == TRAINER_CARD and TOWER in r["actions"][:r["count"]])
    target = row["actions"][:row["count"]].index(TOWER)
    for _ in range((target - row["start_cursor"]) % row["count"]):
        await probe.press(DOWN)
    await probe.press(A)
    for _ in range(100):
        _, screen = await probe.ready(timeout=30)
        if screen.title == TITLE and not screen.status.startswith("Asking"):
            return screen
        await asyncio.sleep(.2)
    raise AssertionError(f"the Tower's home page did not come: {screen.title!r} {screen.status!r}")


def in_battle(probe) -> bool:
    return field_state(probe).get("callback2") not in ("CB2_Overworld", None)


def calm(probe) -> bool:
    state = field_state(probe)
    return (state.get("callback2") == "CB2_Overworld" and state.get("script_status") != 0
            and not state.get("players_menu_active"))


async def play_local_battle(probe, record, slot, label, seconds=600):
    """The floor's intro, its battle and its result as a player plays them: B through the field's messages, A in the
    battle (FIGHT, the first move, its messages), until the field has been calm for three seconds after a battle."""
    deadline, battled, calm_since, screens = time.monotonic() + seconds, False, None, []
    while time.monotonic() < deadline:
        state = field_state(probe)
        screen = state.get("callback2")
        if not screens or screens[-1] != screen:
            screens.append(screen)
        if in_battle(probe):
            battled, calm_since = True, None
            await probe.press(A, frames=8, release=16)
            continue
        if battled and calm(probe):
            calm_since = calm_since or time.monotonic()
            if time.monotonic() - calm_since >= 3:
                record("tower-local-battle-over", slot=slot, label=label, screens=screens)
                return screens
            await asyncio.sleep(.2)
            continue
        calm_since = None
        await probe.press(B, frames=8, release=20)
    raise AssertionError(f"slot {slot} {label}: the Tower battle did not end: {field_state(probe)} {screens}")


async def wait_settled(probe, worker, record, slot, *, progress, highest, seconds=120):
    """The host settled the result: its view and the game's record mirror both say (progress, highest), no result
    waiting in the save's record."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        view = await tower_view(worker)
        mirror = tower_record(probe)
        player = view["player"]
        if (player["progress"], player["highest"]) == (progress, highest) and mirror is not None \
                and (mirror.progress, mirror.highest, mirror.pending) == (progress, highest, None):
            record("tower-settled", slot=slot, progress=progress, highest=highest, claims=player["claims"],
                   record_revision=mirror.revision)
            return view, mirror
        await asyncio.sleep(1)
    raise AssertionError(f"slot {slot}: not settled at P {progress} H {highest}: host {view['player']} game {mirror}")


async def solo_floor(probe, worker, record, slot, floor, *, won=True):
    """One solo floor through the menus, played, settled."""
    before = tower_record(probe)
    party_before = own_party(probe)
    screen = await open_tower(probe)
    record("tower-home", slot=slot, status=screen.status, rows=[r.label for r in screen.rows],
           style=[screen.style, screen.style_arg])
    require(screen.style == 1, "the home page names the native UI's home screen (style 1)")
    await probe.choose(f"Solo: floor {floor}")
    _, screen = await probe.ready()
    record("tower-solo-page", slot=slot, title=screen.title, status=screen.status, rows=[r.label for r in screen.rows],
           style=[screen.style, screen.style_arg])
    require(screen.title.startswith(f"Floor {floor}") and screen.style == 3 and screen.style_arg == floor,
            "the solo page previews its floor (style 3)")
    await probe.choose("Start the battle", wait=False)
    await probe.snapshot(lambda r: not r["active"], timeout=30)
    record("tower-command-taken", slot=slot, floor=floor)
    await play_local_battle(probe, record, slot, f"floor {floor}")
    party_after = own_party(probe)
    highest = max(before.highest if before else 0, floor) if won else (before.highest if before else 0)
    checkpoint = max((c for c in tower_rewards.PRIZE_FLOORS if c <= highest), default=0)
    progress = floor + 1 if won else checkpoint + 1
    view, mirror = await wait_settled(probe, worker, record, slot, progress=progress, highest=highest)
    require(all(m["hp"] == m["max_hp"] for m in party_after), "the party is healed after a Tower battle")
    if party_before[0]["level"] >= CAP_NO_BADGES:
        require(party_after[0]["experience"] == party_before[0]["experience"],
                "the lead (at or above the Tower experience cap) gained no experience")
    record("tower-floor-done", slot=slot, floor=floor, won=won, lead_experience=[party_before[0]["experience"],
           party_after[0]["experience"]], record=dataclasses.asdict(mirror))
    return view


async def form_team(probes, host, record):
    await probes[0].open_players()
    await probes[0].choose(host.accounts[1].display_name, prefix=True)
    await probes[0].choose("Invite to team")
    await probes[1].open_players()
    await probes[1].choose("Team invitation")
    await probes[1].choose("Accept invitation")
    await close_players(probes[0])
    await close_players(probes[1])
    record("ordinary-native-team-formed")


async def duo_battle(current, probes, host, symbols, record, *, floor=None, megas=None):
    """A team, the Duo through the Tower's pages, the native co-op battle, each game's award. Returns the battle id."""
    await form_team(probes, host, record)
    # player 1: Tower > Duo with ... > Invite: floor F (or the replay page's floor)
    await open_tower(probes[0])
    await probes[0].choose(f"Duo with {host.accounts[1].display_name}"[:25], prefix=False)
    _, screen = await probes[0].ready()
    record("tower-duo-page", slot=0, rows=[r.label for r in screen.rows], style=[screen.style, screen.style_arg])
    if floor is None:
        invite = next(r.label for r in screen.rows if r.label.startswith("Invite: floor"))
        floor = int(invite.split()[-1])
        await probes[0].choose(invite)
    else:
        await probes[0].choose("Invite: replay a floor")
        _, screen = await probes[0].ready()
        label = next(r.label for r in screen.rows if r.label.lstrip().startswith(f"{floor} "))
        await probes[0].choose(label)
    await close_players(probes[0])
    # player 2: Tower > Duo: floor F (invited) > Accept
    await open_tower(probes[1])
    await probes[1].choose(next(r.label for r in (await probes[1].ready())[1].rows if r.label.startswith("Duo: floor")))
    await probes[1].choose(f"Accept: floor {floor}")
    record("tower-duo-accepted", floor=floor)
    # both: Ready (their teams: the host's automatic choice)
    await probes[1].choose("Ready")
    await close_players(probes[1])
    await open_tower(probes[0])
    await probes[0].choose(next(r.label for r in (await probes[0].ready())[1].rows if r.label.startswith("Duo: floor")))
    await probes[0].choose("Ready")
    await close_players(probes[0])
    # the host issues the co-op battle: the challenge as the co-op Gym's
    async def descriptor(s):
        values = s._companion._bridge.menu_session.menu._battles
        return [json.loads(json.dumps(v)) for v in values]
    async with asyncio.timeout(60):
        while True:
            values = await on_worker(current[0], descriptor)
            if values:
                break
            await asyncio.sleep(.5)
    battle_id = values[0]["battle_id"]
    record("tower-duo-challenge-issued", battle_id=battle_id, challenge=values[0])
    await probes[1].open_players()
    await probes[1].choose("Pending challenge")
    _, screen = await probes[1].ready()
    if any(r.label == "Accept challenge" for r in screen.rows):
        await probes[1].choose("Accept challenge")
    await probes[0].open_players()
    await probes[0].choose("Pending challenge")
    async with asyncio.timeout(60):
        while not all(screen.admission_action for _, screen in [await p.ready() for p in probes]):
            await asyncio.sleep(.05)
    await asyncio.gather(*(p.choose("Enter battle", wait=False) for p in probes))
    record("tower-duo-entered", battle_id=battle_id, floor=floor)

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
    mega_seen = None

    async def finished(s):
        return s.status.code == "battle_finished" and s._interaction is None
    started = time.monotonic()
    try:
        async with asyncio.timeout(1800):
            while not all([await on_worker(w, finished) for w in current]):
                for driver in drivers:
                    if driver.done():
                        await driver
                if megas and mega_seen is None:
                    mega_seen = opposing_mega(probes[0], megas)
                    if mega_seen:
                        record("tower-duo-opposing-mega", species=mega_seen)
                await asyncio.sleep(.2)
    finally:
        stop.set()
        await asyncio.gather(*drivers)
    record("tower-duo-battle-finished", seconds=round(time.monotonic() - started, 1))
    await asyncio.gather(*(finish_award(p, n, record) for n, p in enumerate(probes)))
    if megas:
        require(mega_seen, "an opposing Pokemon Mega Evolved in the Duo (Norman's Kangaskhan)")
    return battle_id, floor


def opposing_mega(probe, base_species):
    """An opposing battler of the game running the battle (gBattleMons, species first) whose species is none of the
    floor's trainers' own: a form changed in battle (the Mega Evolution of a stone holder), else None."""
    address, length = probe.symbols["gBattleMons"]
    raw = probe.mem("gBattleMons")
    size = length // 4
    for battler in (1, 3):
        species = struct.unpack_from("<H", raw, battler * size)[0]
        if species and species not in base_species:
            return species
    return None





# ---------------------------------------------------------------------------------------------------------- scenarios
class TowerScenario:
    def __init__(self, args):
        self.args, self.harness, self.before = args, None, None

    async def solo(self, current, probes, games, host, symbols, record):
        async def head(s):
            return inspect_closed_head(s._store, host.accounts[0].player_id)
        self.before = wallet_of((await on_worker(current[0], head)).payload)
        record("tower-wallet-before", wallet=self.before)
        floors = range(1, self.args.floors + 1)
        for floor in floors:
            await solo_floor(probes[0], current[0], record, 0, floor)
        if self.args.weak_b:
            await solo_floor(probes[1], current[1], record, 1, 1, won=False)
        self.paid = expected_solo_pay(floors)
        return dict(expected=[p.party_now() for p in probes])

    async def duo(self, current, probes, games, host, symbols, record):
        views = [await tower_view(w) for w in current]
        _, floor = await duo_battle(current, probes, host, symbols, record)
        for slot, (worker, probe) in enumerate(zip(current, probes)):
            player = views[slot]["player"]
            climb = floor == player["progress"]
            highest = max(player["highest"], floor) if climb else player["highest"]
            await wait_settled(probe, worker, record, slot, progress=floor + 1 if climb else player["progress"],
                               highest=highest)
        return dict(expected=[p.party_now() for p in probes])

    async def mega(self, current, probes, games, host, symbols, record):
        data = json.loads(Path(self.args.floors_json).read_text())["floors"][39]
        base = {mon["speciesId"] for trainer in data["duo"] for mon in trainer["mons"]}
        _, floor = await duo_battle(current, probes, host, symbols, record, floor=40, megas=base)
        return dict(expected=[p.party_now() for p in probes])

    async def forfeit(self, current, probes, games, host, symbols, record):
        harness, probe = self.harness, probes[0]
        view = await tower_view(current[0])
        require(view["player"]["progress"] == 13, f"the imported record: floor 13 next, not {view['player']}")
        await open_tower(probe)
        await probe.choose("Solo: floor 13")
        await probe.choose("Start the battle", wait=False)
        await probe.snapshot(lambda r: not r["active"], timeout=30)
        async with asyncio.timeout(120):
            while not in_battle(probe):
                await probe.press(B, frames=8, release=20)
        async with asyncio.timeout(60):
            while (await tower_view(current[0])).get("battle", {}) is None or \
                    (await tower_view(current[0]))["battle"]["state"] == "issued":
                await asyncio.sleep(.5)
        record("tower-forfeit-battle-started", floor=13)
        game = games[0]
        os.kill(game.process.pid, signal.SIGTERM)                 # an ordinary close in the battle
        await harness.poll_until(lambda: game.process.returncode is not None, 60)
        await harness.poll_until(lambda: not current[0].busy, 180)
        record("tower-forfeit-game-closed", exit_code=game.process.returncode)
        again = await harness.start("rejoin", 0)
        harness.players[0] = again
        current[0], probes[0], games[0] = again.worker, again.probe, again.game
        await harness.ready(again)
        await open_tower(again.probe)
        _, screen = await again.probe.ready()
        record("tower-forfeit-home", status=screen.status, rows=[r.label for r in screen.rows])
        view = await tower_view(current[0])
        require((view["player"]["progress"], view["player"]["highest"]) == (11, 12),
                f"floor 13 counted as a loss: P 11, H 12, not {view['player']}")
        await close_players(again.probe)
        record("tower-forfeit-counted-as-a-loss", player=view["player"], last=view.get("last"))
        return dict(expected=[p.party_now() for p in probes])

    async def after_save(self, current, host, record):
        """The canonical checkpoints after the match's saves: the prizes and the record (solo)."""
        if self.args.scenario != "solo":
            return

        async def heads(s):
            return [inspect_closed_head(s._store, account.player_id) for account in host.accounts]
        saved = await on_worker(current[0], heads)
        after = wallet_of(saved[0].payload)
        paid = dict(money=after["money"] - self.before["money"], rare_candy=after["rare_candy"] - self.before["rare_candy"],
                    bp=None if after["bp"] is None else after["bp"] - self.before["bp"])
        record("tower-saved-wallet", revision=saved[0].revision, before=self.before, after=after, paid=paid,
               expected=self.paid)
        require(paid == self.paid, f"the saved prizes {paid} differ from the host's rules {self.paid}")
        require(after["tower"] is not None and (after["tower"]["progress"], after["tower"]["highest"])
                == (self.args.floors + 1, self.args.floors), "the saved Tower record")
        if self.args.weak_b:
            lost = wallet_of(saved[1].payload)
            record("tower-saved-loser", after=lost)
            require(lost["tower"] is not None and (lost["tower"]["progress"], lost["tower"]["highest"]) == (1, 0),
                    "the loser's saved Tower record: P 1, H 0")


async def run(args):
    root = args.output.resolve()
    fixtures = root.parent / (root.name + "-fixtures")
    fixtures.mkdir(parents=True, exist_ok=False)
    sources = []
    for name, source in (("a", args.source_a), ("b", args.source_b)):
        target = fixtures / f"tower-{name}.sav"
        boost_lead(source, target)
        if name == "b" and args.weak_b:
            weaken_lead(target, target)
        if args.scenario == "mega":
            with_tower_record(target, target, 40, 41)
        if args.scenario == "forfeit" and name == "a":
            with_tower_record(target, target, 12, 13)
        sources.append(target)
    scenario = TowerScenario(args)
    await launcher_proof(args, names=NAMES, sources=tuple(sources), party_counts=tuple(args.party_counts),
                         match=getattr(scenario, args.scenario), version=f"Native Tower proof ({args.scenario})",
                         after_boot=lambda phase, slot, probe, companion: into_town(phase, slot, probe, companion),
                         settings="windowScale=2\n", scope=__doc__.split("\n\n")[0],
                         environment=dict(SDL_FRAMEBUFFER_ACCELERATION="0", PKMN_NATIVE_UI="0"),
                         after_save=scenario.after_save, on_harness=lambda h: setattr(scenario, "harness", h))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", choices=("solo", "duo", "mega", "forfeit"), required=True)
    parser.add_argument("--floors", type=int, default=11)
    parser.add_argument("--weak-b", action="store_true")
    parser.add_argument("--party-counts", type=int, nargs=2, default=(2, 1))
    parser.add_argument("--floors-json", type=Path, help="the engine's tools/tower_legends/tower_legends.json (mega)")
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
