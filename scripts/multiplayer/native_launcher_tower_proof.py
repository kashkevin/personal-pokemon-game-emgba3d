"""Two native games through the whole launcher: Battle Tower: Legends, solo and Duo, in real games.

The Tower (docs/battle-tower-legends.md) with the launcher harness of native_launcher_battle_proof.py (real launcher
workers, the production world, enrollment, the Players menu): two games, Linux or (Windows mode) the Windows exe on
Windows. Their sources are fixture saves the engine's test build made (make_tower_saves.py: PKMN_TEST_BATTLE=save:1
with PKMN_TEST_PARTY, and PKMN_TEST_TOWER_RECORD for a record): six level-100 Mewtwo with Dazzling Gleam first (above
every Tower experience cap of a trainer without badges, so a Tower win never gives them experience; no type is immune
to the move), or a level-1 Magikarp that loses. Every step is a player's presses in the game's own menus; the checks
read the games' memory (the save's Tower record mirror, the party), the host's Tower view and, after the harness's
saves, the canonical checkpoints (money, the Bag, Battle Points, the PC, the record).

  --scenario solo     player 1: START > PLAYER > TOWER opens the Tower's home page (the Players menu's page 2); "Solo:
                      floor N" > "Start the battle" for floors P (its save's record; 1 without one) to --floors (default
                      11) in turn: the game closes the menu, shows the floor's intro, battles the floor's trainer (A: the
                      lead's first move; NO to the Shift style's "Will you change Pokemon?"), shows the result; the host
                      settles it and the game's record reaches P = N + 1, H = N; the lead's experience never moves (at
                      the cap); the party is healed. Floor 10 is Brock, the first checkpoint: its first-clear prize (10
                      Rare Candy, $10,000) and every floor's BP and money are in the next save as the host's rules
                      (tower_rewards.py) say. A milestone floor (25, 50, 75, 100) climbed makes its milestone Pokemon in
                      the game (the full party: into the PC; the record marks it delivered). Then the last prize floor
                      is replayed (Replay a floor: P and H kept, replay rates, no second prize or Pokemon) and, with 16
                      BP, an HP Up is bought in the Tower Shop (the game pays the BP, then gets the item). Player 2 (--weak-b: a level-1 Magikarp's save) loses its
                      progress floor in its game and goes back as the checkpoint rule says, nothing paid: floor 1 from
                      a save without a Tower record (P stays 1), or the special boss, Giovanni on floor 25, from one
                      whose record says floor 24 cleared (P 21: checkpoint 20 is kept, H stays 24).
  --scenario duo      a team (Players > invite, accept); Tower > Duo > "Invite: floor F" (F the lower progress floor),
                      accepted, both Ready: the host issues the native co-op battle against the floor's two trainers;
                      both enter it (A presses) and win; each game's co-op award gives nothing above its cap; the host
                      settles each player's result (a replay changes nothing; a climb advances).
  --scenario mega     as duo, from saves whose Tower records say floor 40 cleared (the host imports a save's record on
                      the player's first Tower action): a Duo replay of floor 40, Norman and his partner; the master
                      game's battle shows Norman's Kangaskhan Mega Evolved.
  --scenario climb    both players climb floors 1 to --floors (default 100) at the same time, in the engine's test build
                      (--game pokeemerald-mp-bfxtest with --test-env: PKMN_TEST_TOWER_WIN=1, the floor check's in-memory
                      advantage, and PKMN_TEST_SPEED=4, the game's clock four times as fast; an accelerated set-up, as
                      the request allows): every floor through the menus and settled by the host, the record mirror
                      after each; at the end each save holds every first-clear prize (the 12 prize floors' items and
                      money, every floor's money and BP as tower_rewards.py says), the four milestone Pokemon (in the
                      PC: the party is full) and the record P 101, H 100, claims 0xFFFF.
  --scenario ui       the 3D game with the native PC UI (--native-ui): player 1 opens each Tower page (home, a floor's
                      preview, floors and bosses, the floor map, prizes, the shop, Hyper Training, records, the Duo) and
                      each is pictured (ui-*.png: the Players screen's link device shows the page's Tower screen).
  --scenario forfeit  player 2 (who joined: the world stays up) from a save whose record says floor 12 cleared (P =
                      13): floor 13 started, the game closed in the battle (an ordinary close), started again through
                      the launcher: the Tower counts floor 13 as a loss ("Floor 13: counted as a loss") and P = 11
                      (checkpoint 10 + 1); H stays 12. (Player 1 hosts the world: closing that game closes it for
                      both, and player 2's next save found no host, windows-package run 116.)

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

ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT / "src", ROOT / "scripts" / "multiplayer", ROOT / "scripts" / "windows-runtime"):
    if str(_path) not in sys.path:              # the Windows runner starts it without PYTHONPATH
        sys.path.insert(0, str(_path))
from native_launcher_battle_proof import WINDOWS, NativeProbe, game_picture, launcher_proof  # noqa: E402
from native_launcher_coop_proof import finish_award, logged_driver, own_party  # noqa: E402
from native_launcher_multi_proof import close_players, field_state, into_town  # noqa: E402
from qualify_admission_cleanup import on_worker, require  # noqa: E402
from qualify_launcher_session import inspect_closed_head  # noqa: E402
from emerald_multiplayer import tower_rewards  # noqa: E402
from emerald_multiplayer.flash import TOWER_RECORD_OFFSET, TOWER_RECORD_SIZE, inspect_flash, parse_tower_record  # noqa: E402
from emerald_multiplayer.menu_mailbox import unpack_screen  # noqa: E402
from emerald_multiplayer.ownership_protocol import OWNERSHIP_PROFILE  # noqa: E402

A, B, START, DOWN = 1, 2, 8, 128
PLAYER_OPTIONS, TRAINER_CARD, TOWER = 15, 16, 23          # src/start_menu.c MENU_ACTION_*
TITLE = "Battle Tower: Legends"
NAMES = ("Tower Host", "Tower Friend")
CAP_NO_BADGES = 15
# Save block 1 (include/global.h): money at 0x490, the bag's slots at 0x560 (items pocket first); save block 2's
# encryption key at 0xAC and the Battle Frontier's points at 0xEB8 (offsetof in the PC build; native_launcher_ffa_proof.py's
# offsets).
MONEY, BAG, BAG_SLOTS, ENCRYPTION_KEY = 0x490, 0x560, 186, 0xAC
BATTLE_POINTS = 0xEB8
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


# ---------------------------------------------------------------------------------------------------------- reading
def read_at(probe, address: int, size: int) -> bytes:
    """`size` bytes at an address the game holds (a pointer's value: where it is in the running process)."""
    memory = getattr(probe, "memory", None)
    if memory is not None:                     # Windows: ReadProcessMemory (WindowsProbe), the address as it is
        return memory._raw(address, size)
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
    """Money, Rare Candy, HP Up and Battle Points of a checkpoint, decrypted, the Pokemon in its PC and its Tower
    record."""
    parsed = inspect_flash(checkpoint_payload, save_profile=OWNERSHIP_PROFILE)
    block1, block2 = parsed.save_block1, parsed.save_block2
    key = struct.unpack_from("<I", block2, ENCRYPTION_KEY)[0]
    money = struct.unpack_from("<I", block1, MONEY)[0] ^ key
    slots = [struct.unpack_from("<HH", block1, BAG + 4 * i) for i in range(BAG_SLOTS)]

    def count(wanted):
        return sum(quantity ^ (key & 0xFFFF) for item, quantity in slots if item == wanted)
    bp = struct.unpack_from("<H", block2, BATTLE_POINTS)[0]
    return dict(money=money, rare_candy=count(ITEM_RARE_CANDY), hp_up=count(tower_rewards.ITEM_HP_UP), bp=bp,
                stored=parsed.metadata.stored_pokemon_count,
                tower=None if parsed.tower is None else dataclasses.asdict(parsed.tower))


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


def battle_question_up(probe) -> bool:
    """The battle's YES/NO box takes input (the player's battler: PlayerHandleYesNoInput): with the Shift battle style
    (a new game's default) "<trainer> is about to use ... Will <player> change Pokemon?" when a foe faints."""
    address = probe.symbols.get("PlayerHandleYesNoInput", (None,))[0]
    funcs = probe.code(int.from_bytes(probe.mem("gBattlerControllerFuncs", 4), "little")) & ~1
    return address is not None and funcs == address


async def play_local_battle(probe, record, slot, label, seconds=600):
    """The floor's intro, its battle and its result as a player plays them: B through the field's messages, A in the
    battle (FIGHT, the first move, its messages), until the field has been calm for three seconds after a battle. The
    Shift style's question after a foe faints is answered NO (B) as a player keeping the lead in; a party screen opened
    from the battle by anything else is left with B."""
    deadline, battled, calm_since, screens, questions = time.monotonic() + seconds, False, None, [], 0
    while time.monotonic() < deadline:
        state = field_state(probe)
        screen = state.get("callback2")
        if not screens or screens[-1] != screen:
            screens.append(screen)
        if in_battle(probe):
            battled, calm_since = True, None
            if battle_question_up(probe):
                questions += 1
                record("tower-switch-question-declined", slot=slot, label=label, count=questions, quiet=questions > 1)
                await probe.press(B, frames=8, release=30)
            elif screen == "CB2_UpdatePartyMenu":
                record("tower-party-screen-left", slot=slot, label=label)
                await probe.press(B, frames=8, release=30)
            else:
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


async def choose_paged(probe, prefix, more):
    """The row starting with `prefix` on a page of four, turning the pages (rows starting with `more`)."""
    for _ in range(30):
        _, screen = await probe.ready()
        label = next((r.label for r in screen.rows if r.label.startswith(prefix)), None)
        if label is not None:
            await probe.choose(label)
            return label
        await probe.choose(next(r.label for r in screen.rows if r.label.startswith(more)))
    raise AssertionError(f"no row {prefix!r} on any page")


async def solo_floor(probe, worker, record, slot, floor, *, won=True, replay=False):
    """One solo floor through the menus (a replay: Replay a floor > its row), played, settled."""
    before = tower_record(probe)
    party_before = own_party(probe)
    screen = await open_tower(probe)
    record("tower-home", slot=slot, status=screen.status, rows=[r.label for r in screen.rows],
           style=[screen.style, screen.style_arg])
    require(screen.style == 1, "the home page names the native UI's home screen (style 1)")
    if replay:
        await probe.choose("Replay a floor")
        await choose_paged(probe, f"{floor:>3} ", "More floors")
    else:
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
    if replay:                                   # a replay never changes P or H (design section 2)
        progress, highest = before.progress, before.highest
    view, mirror = await wait_settled(probe, worker, record, slot, progress=progress, highest=highest)
    require(all(m["hp"] == m["max_hp"] for m in party_after), "the party is healed after a Tower battle")
    if party_before[0]["level"] >= CAP_NO_BADGES:
        require(party_after[0]["experience"] == party_before[0]["experience"],
                "the lead (at or above the Tower experience cap) gained no experience")
    record("tower-floor-done", slot=slot, floor=floor, won=won, replay=replay,
           lead_experience=[party_before[0]["experience"], party_after[0]["experience"]],
           record=dataclasses.asdict(mirror))
    return view


async def milestone_delivered(probe, worker, record, slot, milestone, floor, seconds=180):
    """The milestone Pokemon of `floor` made in the player's game: the host's milestone delivered, the game's record
    marking it (claims bit 12 + milestone) as well as the floor's prize."""
    deadline = time.monotonic() + seconds
    while True:
        view = await tower_view(worker)
        entry = next((m for m in view.get("milestones") or () if m["floor"] == floor), None)
        mirror = tower_record(probe)
        if entry is not None and entry["state"] == "delivered" and mirror is not None \
                and mirror.claims >> (12 + milestone) & 1 and mirror.claims & tower_rewards.claim_bit(floor):
            # (not name=: the record's own first argument; windows-package run 121 stopped on it right after the
            # Pokemon was made)
            record("tower-milestone-delivered", slot=slot, floor=floor, milestone=milestone, pokemon=entry["name"],
                   level=entry["level"], claims=mirror.claims)
            return entry
        require(time.monotonic() < deadline, f"the milestone of floor {floor} was not delivered: {entry} {mirror}")
        await asyncio.sleep(1)


async def shop_buy(probe, worker, record, slot, name, price):
    """Tower > Prizes and shop > Tower Shop > the item (its page): the game pays the BP, then gets the item."""
    await open_tower(probe)
    await probe.choose("Prizes and shop")
    _, screen = await probe.ready()
    await probe.choose(next(r.label for r in screen.rows if r.label.startswith("Tower Shop")))
    label = await choose_paged(probe, f"{name} {price}BP", "More items")
    _, screen = await probe.ready()
    record("tower-shop-ordered", slot=slot, row=label, status=screen.status)
    # The game pays and receives the item on the field, never while the Players menu is open (engine multiplayer.c
    # FieldReady): the page says so, and the player closes it (L tower-solo-8 waited with it open for nothing).
    require(screen.status == "Close the menu to finish", f"the shop's status after the order: {screen.status!r}")
    await close_players(probe)
    deadline = time.monotonic() + 120
    while True:
        purchase = (await tower_view(worker)).get("purchase")
        if purchase is not None and purchase["state"] in ("done", "refused", "refunded"):
            break
        require(time.monotonic() < deadline, f"the purchase did not finish: {purchase}")
        await asyncio.sleep(1)
    record("tower-shop-purchase", slot=slot, purchase=purchase)
    require(purchase["state"] == "done" and purchase["price"] == price, f"the purchase: {purchase}")


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


SEEN_BATTLES = set()       # the co-op battles already fought (the menu keeps their challenges listed)


async def duo_ready_again(probes, record):
    """After a Duo battle the Duo goes on to its next floor (forming): both players Tower > Duo: floor F > Ready."""
    floor = None
    for slot, probe in enumerate(probes):
        await open_tower(probe)
        await probe.choose(next(r.label for r in (await probe.ready())[1].rows if r.label.startswith("Duo: floor")))
        _, screen = await probe.ready()
        floor = int(screen.title.split()[-1])
        record("tower-duo-again", slot=slot, title=screen.title, status=screen.status)
        await probe.choose("Ready")
        await close_players(probe)
    return floor


async def duo_battle(current, probes, host, symbols, record, *, floor=None, megas=None, again=False):
    """A team, the Duo through the Tower's pages, the native co-op battle, each game's award. Returns the battle id.
    again: the Duo already played a battle (its next floor: both Ready)."""
    if again:
        floor = await duo_ready_again(probes, record)
        return await duo_fight(current, probes, host, symbols, record, floor, megas)
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
    return await duo_fight(current, probes, host, symbols, record, floor, megas)


async def duo_fight(current, probes, host, symbols, record, floor, megas):
    """Both Ready: the host issues the native co-op battle (the challenge as the co-op Gym's); both enter and play it."""
    async def descriptor(s):
        values = s._companion._bridge.menu_session.menu._battles
        return [json.loads(json.dumps(v)) for v in values]
    async with asyncio.timeout(60):
        while True:
            values = [v for v in await on_worker(current[0], descriptor) if v["battle_id"] not in SEEN_BATTLES]
            if values:
                break
            await asyncio.sleep(.5)
    battle_id = values[0]["battle_id"]
    SEEN_BATTLES.add(battle_id)
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
        self.args, self.harness, self.before, self.loser = args, None, None, None

    async def solo(self, current, probes, games, host, symbols, record):
        async def head(s):
            return inspect_closed_head(s._store, host.accounts[0].player_id)
        self.before = wallet_of((await on_worker(current[0], head)).payload)
        record("tower-wallet-before", wallet=self.before)
        start = tower_record(probes[0])               # the save's record, imported on the first Tower action
        floors = range(start.progress if start else 1, self.args.floors + 1)
        for floor in floors:
            await solo_floor(probes[0], current[0], record, 0, floor)
        self.paid = dict(expected_solo_pay(floors), hp_up=0)
        self.milestones = 0
        for milestone, floor in enumerate(tower_rewards.MILESTONE_FLOORS):
            if floor in floors:
                await milestone_delivered(probes[0], current[0], record, 0, milestone, floor)
                self.milestones += 1
        prize_floors = [floor for floor in floors if floor in tower_rewards.PRIZES]
        if prize_floors:
            # The last prize floor again: replay rates only - no second prize, no second milestone, P and H kept.
            again, highest = prize_floors[-1], floors[-1]
            await solo_floor(probes[0], current[0], record, 0, again, replay=True)
            self.paid["money"] += tower_rewards.later_win_money(again, highest)
            self.paid["bp"] += tower_rewards.later_win_bp(again, highest)
        if self.paid["bp"] >= 16:
            # The Tower Shop: an HP Up for 16 BP, paid from the game's points.
            await shop_buy(probes[0], current[0], record, 0, "HP Up", 16)
            self.paid["bp"] -= 16
            self.paid["hp_up"] += 1
        if self.args.weak_b:
            start = tower_record(probes[1])               # the save's record, imported on the first Tower action
            await solo_floor(probes[1], current[1], record, 1, start.progress if start else 1, won=False)
            end = tower_record(probes[1])
            self.loser = (end.progress, end.highest)
        return dict(expected=[p.party_now() for p in probes])

    async def climb(self, current, probes, games, host, symbols, record):
        async def head(s, slot):
            return inspect_closed_head(s._store, host.accounts[slot].player_id)
        self.before = [wallet_of((await on_worker(current[0], lambda s, n=n: head(s, n))).payload) for n in range(2)]
        record("tower-climb-wallets-before", wallets=self.before)
        floors = range(1, self.args.floors + 1)
        started = time.monotonic()

        async def climb_one(slot):
            for floor in floors:
                await solo_floor(probes[slot], current[slot], record, slot, floor)
                if floor % 10 == 0:
                    record("tower-climb-progress", slot=slot, floor=floor,
                           minutes=round((time.monotonic() - started) / 60, 1))
        await asyncio.gather(climb_one(0), climb_one(1))
        for slot in range(2):
            view = await tower_view(current[slot])
            mirror = tower_record(probes[slot])
            record("tower-climb-done", slot=slot, player=view["player"], record=dataclasses.asdict(mirror))
            if self.args.floors == 100:
                require(view["player"]["claims"] == 0xFFFF and mirror.claims == 0xFFFF,
                        f"slot {slot}: every prize and milestone claimed: host {view['player']['claims']:#x}, "
                        f"game {mirror.claims:#x}")
        self.paid = expected_solo_pay(floors)
        return dict(expected=[p.party_now() for p in probes])

    async def duo_climb(self, current, probes, games, host, symbols, record):
        """Both players climb together in Duo battles to --floors; a loss sends both back to their checkpoint and the
        climb goes on. Each settled result's prize is summed (the saves must hold exactly that)."""
        async def head(s, slot):
            return inspect_closed_head(s._store, host.accounts[slot].player_id)
        self.before = [wallet_of((await on_worker(current[0], lambda s, n=n: head(s, n))).payload) for n in range(2)]
        record("tower-duo-climb-wallets-before", wallets=self.before)
        self.paid = [dict(money=0, rare_candy=0, bp=0) for _ in range(2)]
        started, battles, losses, again = time.monotonic(), 0, 0, False
        while True:
            views = [await tower_view(w) for w in current]
            players = [v["player"] for v in views]
            if min(p["progress"] for p in players) > self.args.floors:
                break
            require(battles < 3 * self.args.floors, f"the Duo climb took {battles} battles")
            battle_id, floor = await duo_battle(current, probes, host, symbols, record, again=again)
            again, battles = True, battles + 1
            outcomes = []
            for slot, (worker, probe) in enumerate(zip(current, probes)):
                async with asyncio.timeout(180):
                    while True:
                        view = await tower_view(worker)
                        last = view.get("last")
                        if view["battle"] is None and last and last["floor"] == floor and last["mode"] == "duo":
                            break
                        await asyncio.sleep(1)
                player, outcome = players[slot], last["state"]
                progress, highest = last["after"] if last["after"] else (player["progress"], player["highest"])
                await wait_settled(probe, worker, record, slot, progress=progress, highest=highest)
                reward = last.get("reward") or {}
                self.paid[slot]["money"] += reward.get("money", 0)
                self.paid[slot]["bp"] += reward.get("bp", 0)
                self.paid[slot]["rare_candy"] += sum(q for item, q in reward.get("items", ()) if item == ITEM_RARE_CANDY)
                outcomes.append(outcome)
            require(len(set(outcomes)) == 1, f"floor {floor}: the two players' results differ: {outcomes}")
            losses += outcomes[0] != "won"
            if floor % 10 == 0 or outcomes[0] != "won":
                record("tower-duo-climb-progress", floor=floor, outcome=outcomes[0], battles=battles, losses=losses,
                       minutes=round((time.monotonic() - started) / 60, 1))
        for slot in range(2):
            view = await tower_view(current[slot])
            mirror = tower_record(probes[slot])
            record("tower-duo-climb-done", slot=slot, player=view["player"], record=dataclasses.asdict(mirror),
                   battles=battles, losses=losses, paid=self.paid[slot])
            if self.args.floors == 100:
                require(view["player"]["claims"] == 0xFFFF and mirror.claims == 0xFFFF,
                        f"slot {slot}: every prize and milestone claimed: host {view['player']['claims']:#x}, "
                        f"game {mirror.claims:#x}")
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

    def picture(self, slot, name):
        """The game's window as the player sees it (game_picture: the window on Linux, the desktop on Windows)."""
        return game_picture(self.harness.players[slot].probe, self.harness.output / f"{name}.png", settle=.5)

    async def ui(self, current, probes, games, host, symbols, record):
        probe, pictures = probes[0], []

        async def shot(name):
            await asyncio.sleep(1.5)                     # the screen drawn and settled
            _, screen = await probe.ready()
            pictures.append(dict(name=self.picture(0, f"ui-{name}"), title=screen.title, status=screen.status,
                                 style=[screen.style, screen.style_arg], rows=[r.label for r in screen.rows]))
            record("tower-ui-page", **pictures[-1])

        async def back():
            await probe.press(B)
            await probe.ready()

        await open_tower(probe)
        await shot("home")
        await probe.choose("Solo: floor 1")
        await shot("solo-preview")
        await back()
        await probe.choose("Floors and bosses")
        await shot("bosses")
        await probe.choose("Floor map")
        await shot("map")
        await back()
        await back()
        await probe.choose("Prizes and shop")
        await shot("prizes")
        label = next(r.label for r in (await probe.ready())[1].rows if r.label.startswith("Prizes:"))
        await probe.choose(label)
        await shot("prize-list")
        await back()
        label = next(r.label for r in (await probe.ready())[1].rows if r.label.startswith("Tower Shop"))
        await probe.choose(label)
        await shot("shop")
        await back()
        await probe.choose("Hyper Training")
        await shot("training")
        await back()
        await back()
        await probe.choose("Records")
        await shot("records")
        await back()
        label = next(r.label for r in (await probe.ready())[1].rows if r.label.startswith("Duo"))
        await probe.choose(label)
        await shot("duo")
        await close_players(probe)
        record("tower-ui-pictures", count=len(pictures))
        return dict(expected=[p.party_now() for p in probes])

    async def forfeit(self, current, probes, games, host, symbols, record):
        harness, probe = self.harness, probes[1]
        view = await tower_view(current[1])
        require(view["player"]["progress"] == 13, f"the imported record: floor 13 next, not {view['player']}")
        await open_tower(probe)
        await probe.choose("Solo: floor 13")
        await probe.choose("Start the battle", wait=False)
        await probe.snapshot(lambda r: not r["active"], timeout=30)
        async with asyncio.timeout(120):
            while not in_battle(probe):
                await probe.press(B, frames=8, release=20)
        async with asyncio.timeout(60):
            while (await tower_view(current[1])).get("battle", {}) is None or \
                    (await tower_view(current[1]))["battle"]["state"] == "issued":
                await asyncio.sleep(.5)
        record("tower-forfeit-battle-started", floor=13)
        game = games[1]
        os.kill(game.process.pid, signal.SIGTERM)                 # an ordinary close in the battle
        await harness.poll_until(lambda: game.process.returncode is not None, 60)
        await harness.poll_until(lambda: not current[1].busy, 180)
        record("tower-forfeit-game-closed", exit_code=game.process.returncode)
        again = await harness.start("rejoin", 1)
        harness.players[1] = again
        current[1], probes[1], games[1] = again.worker, again.probe, again.game
        await harness.ready(again)
        # The loss is counted when the player next asks (design section 2), at least 15 s into the game's new session
        # (a status read cannot tell a closed game's battle from one still running).
        await asyncio.sleep(16)
        screen = await open_tower(again.probe)
        record("tower-forfeit-home", status=screen.status, rows=[r.label for r in screen.rows])
        await again.probe.choose("Solo: floor 13")
        await again.probe.choose("Start the battle")
        _, screen = await again.probe.ready()
        record("tower-forfeit-asked", title=screen.title, status=screen.status, rows=[r.label for r in screen.rows])
        require("counted as a loss" in screen.status, f"the ask answers the forfeit: {screen.status!r}")
        view = await tower_view(current[1])
        require((view["player"]["progress"], view["player"]["highest"]) == (11, 12),
                f"floor 13 counted as a loss: P 11, H 12, not {view['player']}")
        await close_players(again.probe)
        record("tower-forfeit-counted-as-a-loss", player=view["player"], last=view.get("last"))
        return dict(expected=[p.party_now() for p in probes])

    async def after_save(self, current, host, record):
        """The canonical checkpoints after the match's saves: the prizes and the record (solo, climb, duo-climb)."""
        if self.args.scenario not in ("solo", "climb", "duo-climb"):
            return

        async def heads(s):
            return [inspect_closed_head(s._store, account.player_id) for account in host.accounts]
        saved = await on_worker(current[0], heads)
        if self.args.scenario in ("climb", "duo-climb"):
            for slot in range(2):
                after, before = wallet_of(saved[slot].payload), self.before[slot]
                paid = dict(money=after["money"] - before["money"], rare_candy=after["rare_candy"] - before["rare_candy"],
                            bp=after["bp"] - before["bp"])
                expected = self.paid[slot] if self.args.scenario == "duo-climb" else self.paid
                stored = inspect_flash(saved[slot].payload, save_profile=OWNERSHIP_PROFILE).metadata.stored_pokemon_count
                record("tower-climb-saved", slot=slot, revision=saved[slot].revision, paid=paid, expected=expected,
                       stored_pokemon=stored, record=after["tower"])
                require(paid == expected, f"slot {slot}: the saved prizes {paid} differ from the host's {expected}")
                require(after["tower"] is not None and (after["tower"]["progress"], after["tower"]["highest"])
                        == (self.args.floors + 1, self.args.floors), f"slot {slot}: the saved Tower record")
            return
        after = wallet_of(saved[0].payload)
        paid = {key: after[key] - self.before[key] for key in ("money", "rare_candy", "bp", "hp_up")}
        record("tower-saved-wallet", revision=saved[0].revision, before=self.before, after=after, paid=paid,
               expected=self.paid, milestones=self.milestones)
        require(paid == self.paid, f"the saved prizes {paid} differ from the host's rules {self.paid}")
        require(after["stored"] - self.before["stored"] == self.milestones,
                f"the PC holds {after['stored'] - self.before['stored']} new Pokemon, not the {self.milestones} "
                f"milestone Pokemon (the party is full)")
        require(after["tower"] is not None and (after["tower"]["progress"], after["tower"]["highest"])
                == (self.args.floors + 1, self.args.floors), "the saved Tower record")
        if self.args.weak_b:
            lost = wallet_of(saved[1].payload)
            record("tower-saved-loser", after=lost)
            require(lost["tower"] is not None and (lost["tower"]["progress"], lost["tower"]["highest"]) == self.loser,
                    f"the loser's saved Tower record: P {self.loser[0]}, H {self.loser[1]}")


async def run(args):
    sources = (args.source_a, args.source_b)
    if not args.display:
        require(WINDOWS, "an X display per player")
        args.display = ["desktop-0", "desktop-1"]                  # Windows: one desktop; names for the records
    if args.floors is None:
        args.floors = 100 if args.scenario in ("climb", "duo-climb") else 11
    scenario = TowerScenario(args)
    await launcher_proof(args, names=NAMES, sources=tuple(sources), party_counts=tuple(args.party_counts),
                         match=getattr(scenario, args.scenario.replace("-", "_")),
                         version=f"Native Tower proof ({args.scenario})",
                         after_boot=lambda phase, slot, probe, companion: into_town(phase, slot, probe, companion),
                         settings="windowScale=2\n", scope=__doc__.split("\n\n")[0],
                         environment=dict(SDL_FRAMEBUFFER_ACCELERATION="0", PKMN_NATIVE_UI="1" if args.native_ui else "0",
                                          **dict(item.split("=", 1) for item in args.test_env)),
                         after_save=scenario.after_save, on_harness=lambda h: setattr(scenario, "harness", h))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", choices=("solo", "duo", "mega", "forfeit", "ui", "climb", "duo-climb"),
                        required=True)
    parser.add_argument("--test-env", action="append", default=[],
                        help="NAME=VALUE for the games (the test build's switches: the climb's accelerated set-up)")
    parser.add_argument("--native-ui", action="store_true", help="the 3D game's native PC UI on (the ui scenario)")
    parser.add_argument("--floors", type=int, default=None, help="the last floor (solo: 11, climb: 100)")
    parser.add_argument("--weak-b", action="store_true", help="source B is a losing fixture (player 2 loses its progress floor)")
    parser.add_argument("--party-counts", type=int, nargs=2, default=(2, 1))
    parser.add_argument("--floors-json", type=Path, help="the engine's tools/tower_legends/tower_legends.json (mega)")
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-a", type=Path, required=True)
    parser.add_argument("--source-b", type=Path, required=True)
    parser.add_argument("--display", action="append", help="an X display per player (Linux)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0)
    parser.add_argument("--wine", type=Path, action="append")
    parser.add_argument("--sdl", type=Path, help="Windows: SDL2.dll of the game")
    parser.add_argument("--pe-symbols", type=Path, help="Windows: i686-w64-mingw32-nm -n of the game before its strip")
    parser.add_argument("--sizes", type=Path, help="Windows: nm -S of the Linux build of the same engine commit")
    parser.add_argument("--elf", type=Path)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
