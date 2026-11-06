"""Two to four new characters in one world, through the whole launcher (the final master update, QM-5 and QM-6).

Every source is a short-introduction save: no Pokemon, a boy or a girl in front of their own house in Littleroot (the
CI makes them with the game's own short introduction). The same proof runs on Linux (one X display per player) and on
Windows itself (the CI runner: every game on one desktop; native_launcher_battle_proof.py). Through real launcher
workers and native games, driven by ordinary key presses:

  1. everyone linked ("Connected: N/4") with no Pokemon in any game or host save; the second player's 1v1 challenge
     and trade offer to the host are refused by name on the page they were made from ("Get a Pokemon in Birch's lab");
  2. the claimers walk from their doors into Professor Birch's lab, each to a ball on the table (other players'
     avatars never block a step, so two can share one), and all claim a starter at the same moment;
  3. everyone saves through the launcher: one owned Pokemon in each claimer's host save, none in the others';
  then, by --scenario:

    lobby   (2-4 players, all claim; first the second player's connection is cut and it joins again) the host invites
            everyone to a battle lobby and all join: the lobby offers the format of the trainers who joined (1v1,
            1v1v1, or 1v1v1v1 and 2v2: --format); everyone accepts and enters, the battle runs to its end and everyone
            is back on the field, linked, with the party of before the battle.
    mixed   (four; the fourth stays without a Pokemon) mixed parties: the fourth's trade offer to the host is refused
            ("Get a Pokemon in Birch's lab") and so is the host's challenge to it ("They have no Pokemon yet"); the
            host invites the other three to a lobby and all join: starting the 1v1v1v1 is refused by name and opens
            nothing; the fourth leaves the lobby, the 1v1v1 of the three runs to its end while the fourth walks into
            the lab and claims its starter; then a second lobby of all four plays --format (2v2 by default).
    busy    (four) at the same time in one world: the host and the second player battle 1v1 while the third offers
            the fourth a trade; with the offer open the fourth's RESET page says "Finish the trade first" and offers
            no reset (the third's too when its game is on the field); they trade, each now holding the other's
            starter; the fourth resets twice from its host save (each time the others' connections carry on and its
            party is the traded one); the third, its starter traded away, faces its ball again: no ball, no starter
            screen, the same Pokemon; the second opens its trainer card and the options and talks to Professor
            Birch while the three others keep drawing it where it stands; the fourth walks out of Littleroot across Route
            101's rescue tiles (VAR_ROUTE101_STATE 1 and 2 scenes): every step lands, no scene starts.
    trade-evolve  (two; their --source saves already hold a Pokemon each, no claims: KNOWN_ISSUES MS-151) everyone
            saves; the first player offers its first Pokemon to the second, who offers its own; both confirm and the
            host applies the exact exchange; each game then evolves the Pokemon it received by itself (the trade
            evolution scene, its text advanced with B, which stops nothing in a trade evolution), the field comes
            back; everyone saves: the host's saves hold the species in --expect-species (one per player), and a held
            item a trade evolution uses up (a Metal Coat) is gone.
    trade-forms  (two; as trade-evolve, for Pokemon that do not evolve: the Rotom Catalog's forms, trade_forms.py)
            everyone saves; the first player offers its first Pokemon to the second, who offers its own; both confirm
            and the host applies the exact exchange; the field comes back; everyone saves: the host's saves hold the
            species in --expect-species (one per player), each Pokemon under its own serial.
    trade-mail  (two; owner decision 39; the sources make_tower_saves.py's trade-mail-a and -b: a Wingull holding Wave
            Mail; a Treecko holding Wood Mail and a Zigzagoon) everyone saves; the Wingull is traded for the Treecko,
            each Mail along with its Pokemon; then the Treecko for the Zigzagoon (its Mail goes one way). After each
            trade the host's saves, read with the app's own code (trade_eggs_mail_evidence.py): each received Pokemon
            points at a party Mail slot holding its sender's 36 bytes exactly, the sender's slot cleared as ClearMail
            clears it (or taken by the Mail received), no Mail duplicated or lost, every other slot as it was; each game
            that received a Mail reads it (START > POKEMON > the Pokemon > MAIL > READ: the game's own Mail screen,
            pictured, the Mail it shows the one its save block holds at the slot the Pokemon names, the host's bytes);
            the world's integrity check. With --freeze the first trade is cut (KIND:PLAYER:trade:SECONDS once the first
            player confirmed, :trade-confirmed: once both did, :trade-committed: once the host committed it, before
            either game has it): the trade ends applied on both sides or on neither, each Mail on exactly one side
            (an interrupted one resolved as the launcher tells its player), then, unmade, it is made again.
    trade-egg  (two; the sources trade-egg-a and -b: a Zigzagoon and a shiny Togepi Egg one egg cycle from hatching; a
            Mudkip and a Zigzagoon; the world's game hatches a traded Egg right: manifest trade_egg_abi_version 1) the
            Egg is traded for the Mudkip; its receiver walks to and fro until it hatches (--hatch-in party: the game's own
            hatch, "Huh?", the hatch scene, NO to a nickname; --hatch-in box: first the receiver's game is started again
            from its host save with the test build's PKMN_TEST_EGG_TO_PC, which moves the party's Eggs to the PC as a
            deposit does, and saves; the PC's Egg hatches at the same egg cycle's end) and saves: the host takes the one
            change of original trainer it allows. The host's saves: no Bad Egg, the hatcher's trainer ID, name and
            gender, species, personality, IVs, moves and shininess kept; the integrity check; with --hatch-in party the
            hatched Pokemon is traded on to the other player for the Mudkip; with --hatch-in box the Egg's first
            trainer's old save (the copy of the Egg still unhatched) is refused as a character coming back. The games
            are the engine's test build (Makefile_pc BFX_TEST=1; on Windows pokeemerald-mp-bfxtest.exe with its own
            symbol table): its breed log is read from the file each game appends it to (PKMN_TEST_LOG, TEST_LOG in the
            game's launch folder: on Windows the game's own output may reach no file).
    give-up  (two; KNOWN_ISSUES MS-126: no turn timer, a player may give up whenever they wish) both claim their
            starters and save (or, with --no-save, the games save by themselves); the host challenges the second
            player to Rival Battle - 1v1 and both enter. The game that does not run the battle (core 1; core 0, the
            master, does) chooses a move and, on the waiting screen ("Link standby..."), gives up: B, then Yes. The
            master's player has walked away at the action menu, so the master's game answers that choice by itself (a
            pass). One forfeit notice, from the giver's game; the giver loses; everyone is back on the field, linked,
            with the party of before the battle.
    give-up-mid-turn  (two) as give-up, but the master's player chooses too, and the giver gives up after the master
            has begun the turn and before its game has heard of it: once the giver's move is with the host, the host's
            battle messages to the giver arrive GIVE_UP_DELAY_MS late (proof_network.delay_battle_messages_to, until
            the notice is there), so the giver's game still shows the waiting screen when the host routes the master's
            first command of the turn, and gives up then. The notice reaches the master during the turn, which plays
            it as the turn's next action; the giver still loses.
    give-up-knockout  (two; the sources make_tower_saves.py's giveup-ko-a and -b, no claims: each player's only
            Pokemon a level-100 Mewtwo with Dazzling Gleam first, whose move knocks the other's out: the turn ends the
            battle whichever moves first) as give-up-mid-turn: a give-up in a turn that would end the battle another
            way. The giver loses; the record says whether a Pokemon fell after the notice (the notice comes before the
            giver's game has answered any command of the turn, so the master plays it first).
    give-up-switch  (two; the sources giveup-switch-a and -b in either order, no claims: one player a level-50 Golem
            with Explosion first and a Shedinja, the other - the giver, whichever core its game is - a level-30 Ninjask
            with Spikes first and a Zigzagoon) the battle ending another way between a switch and the next action: in
            the first turn the faster Ninjask lays Spikes on the Golem's side and the Golem's Explosion knocks out both;
            both players must send their next Pokemon, the giver picks its Zigzagoon and gives up from the waiting
            screen while the other player has walked away in its party menu. That game answers the choice by itself
            (the Shedinja, its last Pokemon), both are sent out and the Spikes knock the Shedinja out on its way in: the
            battle ends with the giver's side the one left standing, after the notice, and the giver still loses
            (battle_main.c HandleEndTurn_BattleWon / _BattleLost: a forfeit decides the result however the battle
            ended).
    give-up-2v2  (four, all claim) the host's lobby of four starts the 2v2 with the second player as its partner; in
            the battle the master's player has walked away at the action menu, the master's partner (core 2) chooses
            a move and gives up from its waiting screen, the other two choose theirs: one notice, from the giver's
            game; the giver's side (the master and its partner) loses, the other side wins, in every game's own result
            and on the host; everyone back on the field, linked, with the party of before.
  then the harness's closing saves and a fresh Continue of everyone.

What it cannot say: one PC plays every player over its own loopback; on the hosted Windows runner the games run in
Classic 2D on Windows' software renderer; a new character has no Pokedex yet and Littleroot has no shop, so neither
is opened here.

    PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime \\
      python scripts/multiplayer/native_launcher_newcomers_proof.py --scenario busy \\
        --game ../engine/pokeemerald-mp --rom pokedev.gba --manifest manifest.json \\
        --source boy-1.sav --source girl-1.sav --source boy-2.sav --source girl-2.sav \\
        --display :94 --display :95 --display :96 --display :97 --output /private/multiplayer-proof/newcomers-busy-1
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import signal
import sys
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[2]
for _path in (ROOT / "src", ROOT / "scripts" / "multiplayer", ROOT / "scripts" / "windows-runtime"):
    if str(_path) not in sys.path:              # the Windows runner starts it without PYTHONPATH
        sys.path.insert(0, str(_path))
from native_launcher_battle_3d_proof import LIGHT_3D_SETTINGS  # noqa: E402
from native_launcher_battle_proof import (CHOOSE_ACTION_REQUEST, CHOOSE_POKEMON_REQUEST, FORFEIT_ROLE,  # noqa: E402
                                          KEYS, WINDOWS, drive_battle_input, game_picture, idle_battle_input,
                                          launcher_proof, walk_away_at)
from native_launcher_challenge_proof import pick, shown  # noqa: E402
from native_launcher_ffa_proof import A, B, DOWN, LEFT, RIGHT, UP, close_players, players_tab, pose_of, walk_to  # noqa: E402
from native_launcher_lobby4_proof import FourPlayerLobbyProof  # noqa: E402
from native_launcher_newcomer_proof import LAB, LITTLEROOT, NO_POKEMON  # noqa: E402
from native_launcher_soft_reset_proof import SoftResetProof  # noqa: E402
from native_launcher_three_player_proof import ThreePlayerProof, longest_gap  # noqa: E402
from proof_network import delay_battle_messages_to, simulate_disk, simulate_internet  # noqa: E402
from emerald_multiplayer.flash import STORAGE_SIZE, inspect_flash  # noqa: E402
from emerald_multiplayer.menu_mailbox import unpack_screen  # noqa: E402
from emerald_multiplayer.ownership import OWNERSHIP_PROFILE, box_at, box_is_egg, inspect_ownership  # noqa: E402
from emerald_multiplayer.trade_eligibility import validate_party_offer  # noqa: E402
from emerald_multiplayer.trade_mail import MAIL_OFFSET, MAIL_SIZE  # noqa: E402
from qualify_admission_cleanup import on_worker, require  # noqa: E402
from qualify_launcher_session import inspect_closed_head  # noqa: E402
import trade_eggs_mail_evidence as evidence  # noqa: E402

PLAYER_NAMES = ("New Host", "New Friend 1", "New Friend 2", "New Friend 3")
SCENARIOS = ("lobby", "mixed", "busy", "trade", "battle-trade", "trade-evolve", "trade-forms", "trade-mail", "trade-egg",
             "give-up", "give-up-mid-turn", "give-up-knockout", "give-up-switch", "give-up-2v2")
# The give-ups whose --source saves hold the parties their battle needs (make_tower_saves.py giveup-ko-*, giveup-switch-*)
GIVE_UP_HOLDING = ("give-up-knockout", "give-up-switch")
# Scenarios whose --source saves already hold Pokemon (no claims): their parties are the sources' own.
HOLDING = ("trade-evolve", "trade-forms", "trade-mail", "trade-egg", *GIVE_UP_HOLDING)
# Owner decision 39 (KNOWN_ISSUES "Trades: eggs and Mail"). The party menu (engine src/party_menu.c): a party Pokemon's
# menu lists struct PartyMenuInternal's actions (two pointers, a u32 of bit fields and windowId[3], then actions[9] and
# numActions in the PC build); MENU_MAIL opens READ, TAKE, CANCEL. The Mail screen (src/mail.c struct MailRead): the lines
# it prints (8 x 64 bytes), its author's name (12), its callback and the Mail it reads. CONTEXT_SHUTDOWN (src/script.c):
# no field script runs.
MENU_ACTION_POKEMON = 1
PARTY_ACTIONS, PARTY_ACTION_COUNT = 15, 24
MENU_MAIL, MENU_TAKE_MAIL, MENU_READ, MENU_CANCEL2 = 7, 8, 9, 10
MAIL_LINES, MAIL_AUTHOR, MAIL_CALLBACK, MAIL_POINTER = 0, 0x200, 0x210, 0x214
SCRIPT_SHUTDOWN = 2
# Where a hatching receiver walks to and fro (row 12 east and west of the lab's street: the newcomers' own ways).
PACE = {"east": (12, 11, 14), "west": (12, 5, 10)}
# trade-egg: the file each game of the test build appends its driver's log to (PKMN_TEST_LOG, battle_env_test.c
# TestLog), in the game's own launch folder beside its runtime.log
TEST_LOG = "test.log"
# The soft reset key as a keyboard player presses it (Ctrl+R), and the four keys it stands for (A, B, START, SELECT:
# NativeProbe.press_reset_key's), in the probes' key names
CTRL_R, RESET_KEYS = ("ctrl", "r"), ("z", "x", "Return", "backslash")
# trade-mail's --freeze points: once the first player confirmed, once both did, once the host committed the trade
TRADE_CUTS = ("trade", "trade-confirmed", "trade-committed")
GIVE_UPS = ("give-up", "give-up-mid-turn", "give-up-knockout", "give-up-switch", "give-up-2v2")
# The give-ups made after the battle's master has begun the turn (the host's messages to the giver held, below)
MID_TURN = ("give-up-mid-turn", "give-up-knockout")
# The master's command of a Pokemon fainting on every game's screen (engine include/battle_controllers.h
# CONTROLLER_FAINTANIMATION); B_OUTCOME_WON and B_OUTCOME_LOST, as a game keeps its own result in gBattleOutcome after
# the battle (from its own side; the next battle clears it)
FAINT_ANIMATION = 10
OUTCOME_WON, OUTCOME_LOST = 1, 2
NINJASK = 291        # give-up-switch: the giver's lead (make_tower_saves.py giveup-switch-b)
# give-up-mid-turn: how late the host's battle messages reach the giver's game once its move is with the host, until the
# notice is there (then at once again, in order). The giver gives up (B, the question, UP, A: about 2 s) between the host
# routing the master's first command of the turn and the giver's game receiving it, at least this much later; below the
# 5 s the giver's launcher waits for each answer of the host (companion.battle_challenge_rpc), so none is given up on.
GIVE_UP_DELAY_MS = 4500
FORMATS = ("1v1v1v1", "2v2")
MODES = {"1v1": 2, "2v2": 3, "1v1v1v1": 5, "1v1v1": 6}
PEER_NO_POKEMON = "They have no Pokemon yet"
ROUTE_101 = (0, 16)
# A boy starts at (5,9), a girl at (14,9). From there to the lab door (Littleroot (7,16), entered from (7,17)) down the
# free columns 10 and 11 east of the lab (native_launcher_newcomer_proof.py's ways).
STREETS = {"west": ((5, 12), (10, 12), (10, 17), (7, 17)), "east": ((14, 12), (11, 12), (11, 17), (8, 17), (7, 17))}
# In the lab, from its door to below a ball on the table (engine multiplayer_rival.c sLabBalls: Grass (8,4), Fire (9,4),
# Water (10,4)); the right end of the table is reached only along row 5.
TABLES = {"water": ((6, 9), (7, 9), (7, 5), (10, 5)), "fire": ((6, 10), (6, 6), (8, 6), (8, 5), (9, 5)),
          "grass": ((6, 10), (6, 6), (8, 6), (8, 5))}
BALLS = ("water", "fire", "grass", "fire")
# Out of the lab ((6,12) is its door), then from below its door to Littleroot's way north (10,0): Route 101's first rows
# hold the rescue scene's triggers ((10,19)/(11,19), VAR_ROUTE101_STATE 1) and the "don't go" ones ((10,18)/(11,18),
# state 2). A lab character's state is 3 (engine multiplayer_rival.c ApplyIntroState).
FROM_TABLE = ((8, 5), (8, 6), (6, 6), (6, 12))
TO_THE_WAY_NORTH = ((10, 17), (10, 12), (10, 2))
ON_ROUTE_101 = ((10, 18), (10, 16))
START = 8
MENU_ACTION_OPTION, PLAYER_OPTIONS, TRAINER_CARD = 6, 15, 16          # engine src/start_menu.c
BELOW_BIRCH = (6, 5)                     # Birch stands at (6,4) facing down (his aide wanders, so is no target)


def read_at(probe, address, size):
    """`size` bytes at an address the game holds (a pointer's value: where it is in the running process)."""
    memory = getattr(probe, "memory", None)
    if memory is not None:                     # Windows: ReadProcessMemory (WindowsProbe), the address as it is
        return memory._raw(address, size)
    with open(f"/proc/{probe.pid}/mem", "rb", buffering=0) as memory:
        memory.seek(address)
        return memory.read(size)


class NewcomersProof(SoftResetProof, ThreePlayerProof):
    """The newcomer proof's claims, the soft reset proof's RESET page and the three-player proof's drawing checks, for
    two to four players."""

    send_lobby = FourPlayerLobbyProof.send_lobby
    answer = FourPlayerLobbyProof.answer
    lobby_page = FourPlayerLobbyProof.lobby_page
    accept = FourPlayerLobbyProof.accept

    def __init__(self, scenario, fmt, watch, match_seconds, no_save=False, expect_species=(), hatch_in="party"):
        super().__init__(watch, match_seconds)
        self.scenario, self.format, self.no_save = scenario, fmt, no_save
        self.expect_species = tuple(expect_species)
        self.hatch_in = hatch_in

    def adopt(self, harness):
        """AbandonProof.adopt; and with trade-egg every game the proof's launchers start (an enrollment's, Host Game's
        and Join Game's, and a game a reset starts again) appends the test build's log to a file of its own: TEST_LOG
        in its launch folder (PKMN_TEST_LOG; the spawn's working directory, beside its runtime.log). On Windows the
        game's own output may reach no file (battle_env_test.c), so the breed log is read from there on every platform.
        This spawn runs under AbandonProof's (which picks the player's display), so it adds to the environment that one
        chose. The environment only; nothing else of the spawn changes."""
        if self.scenario == "trade-egg":
            real = asyncio.create_subprocess_exec

            async def spawn(program, *arguments, **options):
                if options.get("cwd") is not None:
                    options["env"] = dict(options.get("env") or os.environ,
                                          PKMN_TEST_LOG=str(Path(options["cwd"]) / TEST_LOG))
                return await real(program, *arguments, **options)
            asyncio.create_subprocess_exec = spawn
        super().adopt(harness)

    # The claims ---------------------------------------------------------------------------------------------------
    async def walk_to_lab(self, slot, current, probes, record):
        probe, companion = probes[slot], await self.companion_of(current[slot])
        started = time.monotonic()
        here = pose_of(companion)
        require(here is not None and tuple(here[2:4]) == LITTLEROOT, f"{self.harness.names[slot]} is not in Littleroot: {here}")
        for x, y in STREETS["west" if here[4] < 10 else "east"]:
            await walk_to(probe, companion, LITTLEROOT, x, y, record, slot)
        await self.through_door(slot, current, probes, record, UP, LAB)
        for x, y in TABLES[BALLS[slot]]:
            await walk_to(probe, companion, LAB, x, y, record, slot)
        record("at-the-lab-table", player=self.harness.names[slot], ball=BALLS[slot],
               position=list(pose_of(companion)[2:]), seconds=round(time.monotonic() - started, 1))
        return companion

    async def claims(self, slots, current, probes, record):
        """Everyone to their ball (a few seconds apart, as friends arrive), then every claim at the same moment."""
        async def arrive(n, delay):
            await asyncio.sleep(delay)
            return await self.walk_to_lab(n, current, probes, record)
        companions = await asyncio.gather(*(arrive(n, 3 * i) for i, n in enumerate(slots)))
        windows = await asyncio.gather(*(self.claim(n, probes[n], c, record) for n, c in zip(slots, companions)))
        overlap = min(w[1] for w in windows) - max(w[0] for w in windows)
        record("claims-at-once", players=[self.harness.names[n] for n in slots], overlap_seconds=round(overlap, 1),
               windows=[[round(a - self.t0, 1), round(b - self.t0, 1)] for a, b in windows])
        require(overlap > 0, f"the claims did not overlap: {windows}")

    async def save_all(self, current, record, label, slots=None):
        for n in range(len(current)) if slots is None else slots:
            revision = (await self.launcher(current[n]))["revision"]
            require(current[n].request_save(), f"{self.harness.names[n]}: the launcher refused Save now")
            await self.saved(current[n], revision)
        canonical = await self.heads(current, self.harness.host)
        record(label, canonical=canonical, revisions=[(await self.launcher(w))["revision"] for w in current])
        return canonical

    async def auto_saved(self, current, record, label, before, seconds=90):
        """--no-save (the owner's request of 2026-10-22): nobody presses Save now; a game whose party's Pokemon changed
        saves on the host by itself (multiplayer_soft_reset.c), so each launcher's revision moves past `before` and
        the host save holds the starter."""
        async with asyncio.timeout(seconds):
            while True:
                revisions = [(await self.launcher(w))["revision"] for w in current]
                canonical = await self.heads(current, self.harness.host)
                if all(r > b for r, b in zip(revisions, before)) and all(c["count"] == 1 for c in canonical):
                    break
                await asyncio.sleep(.5)
        record(label, canonical=canonical, revisions=revisions, before=before)
        return canonical

    async def refused_with(self, probe, peer, action, record, slot, expected):
        """A choice on a player's page answered by the host's refusal, on that same page."""
        await probe.open_players()
        await probe.choose(peer, prefix=True)
        await probe.choose(action, wait=False)
        async with asyncio.timeout(20):
            while True:
                _, screen = await shown(probe)
                if screen.status != "Choose an interaction":
                    break
                await asyncio.sleep(.2)
        record("refused", player=self.harness.names[slot], peer=peer, action=action, status=screen.status,
               rows=[r.label for r in screen.rows])
        require(screen.status == expected, f"{action}: the menu said {screen.status!r}, expected {expected!r}")
        require(action in [r.label for r in screen.rows], f"{action}: the menu left the player's page")
        await close_players(probe)

    async def nothing_open(self, current, record, label):
        async def open_things(s):
            return dict(battles=len(s._server.battle_desk._active), trades=len(s._server.trade_desk._proposals))
        left = await on_worker(current[0], open_things)
        record(label, **left)
        require(left == dict(battles=0, trades=0), f"{label}: a refused challenge or trade stayed open: {left}")

    # Battles ------------------------------------------------------------------------------------------------------
    async def stray_presses(self, probe, presses, record, label):
        """--stray-presses: A pressed `presses` times where the game's cursor already is, as a player clicking again
        (the owner's "when clicked again it kicks us out back to start"): each press, the row it landed on and the
        screen it led to. A press on a row that does nothing changes nothing."""
        seen = []
        for _ in range(presses):
            row, screen = await probe.ready()
            cursor = row["cursor"]
            landed = screen.rows[cursor].label if cursor < len(screen.rows) else None
            await probe.press(1)
            _, after = await probe.ready()
            seen.append(dict(on=landed, active=bool(cursor < len(screen.rows) and screen.rows[cursor].action),
                             then=after.title, rows=[r.label for r in after.rows]))
        record(label, presses=seen)
        return seen

    async def stray_lobby(self, probes, names, record, label):
        """--stray-presses, two players: the leader's A on Send invitations, and the friend's A on Battle lobby, each
        followed by more presses without moving. No row they land on may end the lobby (MS-69 on the lobby path)."""
        leader, friend = probes
        await leader.open_players()
        for step in ("Challenges", "New battle", "Battle lobby", f"{names[1][:19]}: No"):
            await leader.choose(step)
        await leader.choose("Send invitations")
        led = await self.stray_presses(leader, 1, record, label + "-leader-stray")
        await close_players(leader)
        await friend.open_players()
        await friend.choose("Battle lobby")
        seen = await self.stray_presses(friend, 2, record, label + "-friend-stray")
        require(all(s["on"] not in ("Decline", "Yes, decline it") for s in seen),
                f"a stray press landed on a decline: {seen}")
        require(seen[-1]["then"] == "Battle lobby" and "Join lobby" in seen[-1]["rows"],
                f"after two stray presses the friend's lobby is gone: {seen}")
        require(led[0]["on"] == "Waiting for trainers" and not led[0]["active"] and led[0]["then"] == "Battle lobby",
                f"the leader's next A after Send invitations: {led}")
        await friend.choose("Join lobby")
        await close_players(friend)

    async def lobby_battle(self, current, probes, symbols, record, slots, fmt, label):
        """The host's lobby of `slots` (all join), started as `fmt`; accepted, entered, played to its end."""
        names = [a.display_name for a in self.harness.host.accounts]
        invited = [n for n in slots if n != 0]
        if STRAY[0] and len(slots) == 2:
            await self.stray_lobby([probes[n] for n in slots], [names[n] for n in slots], record, label)
        else:
            await self.send_lobby(probes[0], [names[n] for n in invited], record, label + "-lobby-sent")
            for n in invited:
                await self.answer(probes[n], "Join lobby")
        status, rows = await self.lobby_page(probes[0])
        record(label + "-lobby", status=status, rows=rows)
        offered = {2: ["1v1"], 3: ["1v1v1"], 4: ["1v1v1v1", "2v2"]}[len(slots)]
        require(status == f"{' or '.join(offered)}: {len(slots)} joined" and all(f"Start {f}" in rows for f in offered),
                f"the lobby of {len(slots)} detected {status!r} {rows}")
        _, screen = await probes[0].choose(f"Start {fmt}")
        if fmt == "2v2":
            require(screen.status == "Choose your 2v2 partner", f"the 2v2 start says {screen.status!r}")
            await probes[0].choose(f"With {names[1][:20]}")
        await self.accept(probes, invited)
        return await self.play(current, probes, symbols, record, slots, fmt, label)

    async def lobby_2v2(self, probes, record, label):
        """The host's lobby of all four (everyone joins), started as the 2v2 with the second player as its partner and
        accepted by the three others; entered by give_up_battle."""
        names = [a.display_name for a in self.harness.host.accounts]
        await self.send_lobby(probes[0], names[1:], record, label + "-lobby-sent")
        for n in (1, 2, 3):
            await self.answer(probes[n], "Join lobby")
        status, rows = await self.lobby_page(probes[0])
        record(label + "-lobby", status=status, rows=rows)
        require(status == "1v1v1v1 or 2v2: 4 joined" and "Start 2v2" in rows, f"the lobby of four says {status!r} {rows}")
        _, screen = await probes[0].choose("Start 2v2")
        require(screen.status == "Choose your 2v2 partner", f"the 2v2 start says {screen.status!r}")
        await probes[0].choose(f"With {names[1][:20]}")
        await self.accept(probes, (1, 2, 3))

    async def play(self, current, probes, symbols, record, slots, fmt, label, meanwhile=None, freeze=None):
        """Enter, drive and finish the accepted battle of `slots`; `meanwhile` (a task of the others') ends before
        everyone's PLAYERS is looked at; `freeze` (--freeze ...:battle) runs FREEZE_INTO_BATTLE seconds into it."""
        before = {n: await probes[n].battle() for n in slots}
        battles = await self.enter(current, probes, slots, record, label)
        modes = [v["mode"] for v in battles.values()]
        require(modes == [MODES[fmt]], f"{label}: started {modes}, expected the {fmt} ({MODES[fmt]})")
        stops, drivers = self.drive(current, probes, symbols, battles, slots)
        freezing = None
        if freeze is not None:
            async def later():
                await asyncio.sleep(FREEZE_INTO_BATTLE)
                await freeze()
            freezing = asyncio.create_task(later())
        try:
            results = await self.finish(current, probes, battles, slots, stops, drivers, record, label)
        finally:
            if freezing is not None:
                if not freezing.done():
                    record("battle-ended-before-the-freeze", label=label)
                    freezing.cancel()
                await asyncio.gather(freezing, return_exceptions=True)

        async def route(s):
            # KNOWN_ISSUES MS-62: the native commands each battle's route issued, the trainers' polls that carried them,
            # and the seconds from each trainer's first poll to its last (the host's own counters).
            out = {}
            for battle_id in battles:
                room = s._server.battle_execution.rooms.get(battle_id)
                if room is None:
                    continue
                commands = sum(room.dispatch_ids.values())
                polls = sum(p["count"] for p in room.polls.values())
                seconds = max(p["last"] for p in room.polls.values()) - min(p["first"] for p in room.polls.values())
                # The last commands' hops (battle_execution.HOPS_KEPT a trainer): waiting for the trainer's poll to
                # take the command (published to delivered), and from there to its answer (the trainer's launcher and
                # game, both ways over the network), in median milliseconds.
                hops = [h for kept in room.hops.values() for h in kept
                        if h["delivered"] is not None and h["answered"] is not None]

                def median(values):
                    values = sorted(values)
                    return round(1000 * values[len(values) // 2], 1) if values else None
                out[battle_id[:8]] = dict(commands=commands, polls=polls, seconds=round(seconds, 1),
                                          polls_per_command=round(polls / max(commands, 1), 2),
                                          ms_per_command=round(1000 * seconds / max(commands, 1), 1),
                                          hops=len(hops), take_ms=median([h["delivered"] - h["published"] for h in hops]),
                                          answer_ms=median([h["answered"] - h["delivered"] for h in hops]))
            return out
        record(label + "-route", latency_ms=LATENCY_MS[0], hold=HOLD[0], disk_ms=DISK_MS[0], remote_only=REMOTE_ONLY[0], rough=ROUGH[0], rooms=await on_worker(current[0], route))
        if meanwhile is not None:
            await meanwhile
        await self.back_on_the_field(current, probes, before, record, label + "-everyone-back")
        return results

    async def give_up_battle(self, current, probes, symbols, record, mid_turn=False, label=None, slots=(0, 1),
                             giver_slot=None):
        """KNOWN_ISSUES MS-126: the accepted battle entered (a 1v1, or with four `slots` the 2v2); the giver - core 1 of a
        1v1 (core 0, the master, runs the battle; the 1v1's cores are its players in the order of their ids), the
        master's partner (core 2) in a 2v2, or the player `giver_slot` whichever core it is - chooses a move and gives up
        from the waiting screen. The other player of a 1v1 (the master in a 2v2) has walked away at its action menu, or
        (`mid_turn`, the master) chooses too, and the giver gives up once the master has begun the turn, before its own
        game has heard of it; or (give-up-switch) plays the first turn and walks away in its party menu, and the giver
        gives up once it has sent its own next Pokemon. The other two players of a 2v2 choose as usual. The giver's side
        loses either way, in every game's own result and on the host."""
        label = label or ("give-up-mid-turn" if mid_turn else "give-up")
        switch, four = label == "give-up-switch", len(slots) == 4
        blocks = []
        slowed, turn = [], []   # mid_turn: (resume, end) of the giver's slowed link; when the master began the turn

        def seen_block(block):
            blocks.append(dict(block, at=round(time.monotonic() - self.t0, 2)))
            data = bytes.fromhex(block["data"])
            if block["kind"] != 8:
                return
            if data[0] == FORFEIT_ROLE and slowed:
                slowed[0][0]()  # the notice is there: the giver's game hears from the host at once again
            elif mid_turn and not turn and block["source"] == 0 and data[0] == 0 and any(
                    b["kind"] == 8 and b["source"] == 0 and bytes.fromhex(b["data"])[0] == 1
                    and bytes.fromhex(b["data"])[8:10] == bytes((32, 10)) for b in blocks):
                turn.append(time.monotonic())   # the master's first command after its own move: the turn has begun

        async def observe(s):
            service = s._server.battle_execution
            require(service.observer is None, "a previous proof observer exists")
            service.observer = seen_block
        await on_worker(current[0], observe)
        before = {n: await probes[n].battle() for n in slots}
        battles = await self.enter(current, probes, slots, record, label)
        (battle_id, battle), = battles.items()
        fmt = "2v2" if four else "1v1"
        require(battle["mode"] == MODES[fmt], f"{label}: started mode {battle['mode']}, not the {fmt}")
        # the host's route takes the battle's commands from core 0 only (battle_controller.py): the master
        cores = [self.index(battle, player) for player in battle["players"]]     # each core's player slot
        giver_core = cores.index(giver_slot) if giver_slot is not None else 2 if four else 1
        idle_core = 1 if giver_core == 0 else 0       # the player who walked away (a 2v2's: the master)
        require(not mid_turn or giver_core == 1, f"{label}: a give-up during the turn is the other game's, not the "
                "master's")
        master_n, giver_n, idle_n = cores[0], cores[giver_core], cores[idle_core]

        def view(core):
            async def read(s):
                room = s._server.battle_execution.rooms.get(battle_id)
                if room is None:
                    return dict(state="waiting", pending=None)
                return dict(state=room.state, pending=None if room.route is None else room.route.validator.pending[core])
            return lambda: on_worker(current[0], read)
        stops = {n: asyncio.Event() for n in slots}
        for n in slots:
            self.seen[n] = {}
        # the giver gives up while the other is asked its action (give-up-switch: its next Pokemon)
        give_up = dict(wait_for=CHOOSE_POKEMON_REQUEST if switch else CHOOSE_ACTION_REQUEST)
        if mid_turn:
            async def begun():
                return bool(turn)
            give_up["when"] = begun     # the giver gives up once the host has routed the master's turn

            async def master_input():
                # once the giver's move is with the host, its game hears from the host late; then the master's player
                # chooses (so the turn begins while the giver's game still shows the waiting screen)
                while not stops[master_n].is_set() and not (give_up.get("asked_move")
                                                            and (await view(giver_core)())["pending"] is None):
                    await asyncio.sleep(.05)
                slowed.append(delay_battle_messages_to(self.harness.host.accounts[giver_n].player_id, GIVE_UP_DELAY_MS))
                give_up["slowed"] = time.monotonic()
                await drive_battle_input(probes[master_n], view(0), symbols, stops[master_n], self.seen[master_n])
            master = asyncio.create_task(master_input())
        elif switch:
            # the first turn as a player plays it, then nothing once the party menu asks for the next Pokemon
            master = asyncio.create_task(walk_away_at(probes[idle_n], view(idle_core), symbols, stops[idle_n],
                                                      CHOOSE_POKEMON_REQUEST, self.seen[idle_n]))
        else:
            master = asyncio.create_task(idle_battle_input(probes[idle_n], view(idle_core), stops[idle_n]))
        drivers = {idle_n: master, giver_n: asyncio.create_task(drive_battle_input(
            probes[giver_n], view(giver_core), symbols, stops[giver_n], self.seen[giver_n], give_up=give_up,
            other_view=view(idle_core)))}
        for core, n in enumerate(cores):
            if n not in drivers:        # a 2v2's other two players choose as usual
                drivers[n] = asyncio.create_task(drive_battle_input(probes[n], view(core), symbols, stops[n],
                                                                    self.seen[n]))
        try:
            results = await self.finish(current, probes, battles, slots, stops, drivers, record, label)
        finally:
            for _resume, end in slowed:
                end()

            async def unobserve(s):
                s._server.battle_execution.observer = None
            await on_worker(current[0], unobserve)
        # each game's own result, from its own side (gBattleOutcome, kept until its next battle)
        own = {core: probes[n].mem("gBattleOutcome", 1)[0] for core, n in enumerate(cores)}

        async def history(s):
            values = [v for v in (await s._companion.battle_challenge_rpc("history"))["result"]
                      if v["battle_id"] == battle_id]
            return values[0]["outcome"] if values else None
        seen_by = {core: await on_worker(current[n], history) for core, n in enumerate(cores)}

        def data(b):
            return bytes.fromhex(b["data"])

        def replies(core):
            # (command, first byte) of a core's choice replies (role 1: TWORETURNVALUES 32, CHOSENMONRETURNVALUE 33)
            return [tuple(data(b)[8:10]) for b in blocks if b["kind"] == 8 and b["source"] == core
                    and data(b)[0] == 1 and data(b)[8] in (32, 33)]
        notices = [i for i, b in enumerate(blocks) if b["kind"] == 8 and data(b)[0] == FORFEIT_ROLE]
        require("chosen" in give_up, f"{label}: the giver never chose Yes on the question: "
                + json.dumps({k: v for k, v in give_up.items() if k != "prepare"}, default=str))
        require(len(notices) == 1 and blocks[notices[0]]["source"] == giver_core
                and data(blocks[notices[0]])[1] == giver_core,
                f"{label}: expected one forfeit notice from the giver's game: {[blocks[i]['source'] for i in notices]}")
        outcome = results[battle_id]["outcome"]
        winner = 2 - giver_core % 2             # the team without the giver (team 1: cores 0 and 2)
        require(outcome == winner, f"{label}: the giver's side did not lose: outcome {outcome}, not team {winner}")
        expected_own = {core: OUTCOME_WON if 1 + core % 2 == winner else OUTCOME_LOST for core in range(len(cores))}
        require(own == expected_own, f"{label}: a game's own result differs: {own}, expected {expected_own}")
        require(all(value == outcome for value in seen_by.values()),
                f"{label}: a player's launcher shows another result: {seen_by}")
        # the giver: Fight (action 0) and a move (10) (give-up-switch: then its next Pokemon, party slot 1); the other:
        # its own pass (13) at the action menu it was left at, or its player's Fight and move (mid_turn; give-up-switch:
        # then its game's own pick of its next Pokemon, the Shedinja in party slot 1)
        giver_expected = [(32, 0), (32, 10)] + ([(33, 1)] if switch else [])
        require(replies(giver_core) == giver_expected,
                f"{label}: the giver's replies differ: {replies(giver_core)}, expected {giver_expected}")
        expected = [(32, 0), (32, 10), (33, 1)] if switch else [(32, 0), (32, 10)] if mid_turn else [(32, 13)]
        require(replies(idle_core) == expected,
                f"{label}: the other game's replies differ: {replies(idle_core)}, expected {expected}")
        # the master's commands after the notice reached the host: (command, battler; a 1v1's or 2v2's battler is its
        # core's)
        after_notice = [tuple(data(b)[8:9] + data(b)[1:2]) for b in blocks[notices[0] + 1:]
                        if b["kind"] == 8 and b["source"] == 0 and data(b)[0] == 0]
        fainted_after = sorted({battler for command, battler in after_notice if command == FAINT_ANIMATION})
        if switch:
            # the battle ended another way after the notice: the other side's last Pokemon (the Shedinja) knocked out on
            # its way in, so the giver's side was left standing - and still lost
            require(idle_core in fainted_after and giver_core not in fainted_after,
                    f"{label}: not the other side's last Pokemon alone fell after the notice: {after_notice}")
        before_notice = None
        if mid_turn:
            # the master's commands after its own move and before the notice reached the host: the turn had begun
            chosen = max(i for i, b in enumerate(blocks) if b["kind"] == 8 and b["source"] == 0 and data(b)[0] == 1
                         and tuple(data(b)[8:10]) == (32, 10))
            before_notice = [data(b)[8] for b in blocks[chosen + 1:notices[0]]
                             if b["kind"] == 8 and b["source"] == 0 and data(b)[0] == 0]
            require(before_notice, f"{label}: the notice reached the host before the master began the turn")
        record(label + "-forfeit", battle_id=battle_id, giver=self.harness.names[giver_n], giver_core=giver_core,
               master=self.harness.names[master_n], walked_away=None if mid_turn else self.harness.names[idle_n],
               winner_team=outcome,
               own_results=own, launchers_show=seen_by, giver_replies=replies(giver_core),
               walked_away_replies=replies(idle_core),
               other_replies={core: replies(core) for core in range(len(cores)) if core not in (idle_core, giver_core)},
               notice_at=blocks[notices[0]]["at"], master_commands_after_the_notice=after_notice,
               fainted_after_the_notice=fainted_after, master_commands_before_the_notice=before_notice,
               delay_ms=GIVE_UP_DELAY_MS if mid_turn else 0,
               seconds_from_the_turn_to_yes=None if not mid_turn else round(give_up["chosen"] - turn[0], 1),
               presses_of_b_before_the_question=give_up.get("b_without_question", 0),
               walked_away_at=self.seen[idle_n].get("at_request"))
        await self.back_on_the_field(current, probes, before, record, label + "-everyone-back")

    async def back_on_the_field(self, current, probes, before, record, label):
        """Everyone on the field and linked to everyone; each battler's party exactly the one of before the battle;
        no battle left open for anybody."""
        count = len(current)
        async with asyncio.timeout(180):
            while True:
                states = [await self.state_of(w) for w in current]
                if all(v.get("connected") and v.get("game_link") and v.get("roster") == count and v.get("field")
                       for v in states):
                    break
                await asyncio.sleep(.5)
        for n, probe in enumerate(probes):
            status, rows = await players_tab(probe)
            others = [name for m, name in enumerate(self.harness.names) if m != n]
            listed = all(any(row == name or row.startswith(name + " ") for row in rows) for name in others)
            # A notice ("Trade completed and saved") stays on the status line until the player picks a row.
            require(listed and (status == f"Connected: {count}/4" or not status.startswith("Connected")),
                    f"player {n}'s PLAYERS: {status} {rows}")
        for n, old in before.items():
            now = await probes[n].battle()
            require(now["count"] == old["count"] and now["party_sha256"] == old["party_sha256"],
                    f"{self.harness.names[n]}'s party is not the one of before the battle")

        async def clean(s):
            left = [name for name in ("pending-battle.json", "pending-battle-admission.json")
                    if (s.profile_directory / name).exists()]
            waiting = (await s._companion.battle_challenge_rpc("waiting"))["result"]
            return dict(pending_files=left, waiting=waiting, retained=s._battle_retained is not None)
        leftovers = [await on_worker(w, clean) for w in current]
        require(all(not v["pending_files"] and not v["waiting"] and not v["retained"] for v in leftovers),
                f"{label}: a battle still holds somebody: {leftovers}")
        record(label, sessions=[v["epoch"] for v in states], same_parties=[self.harness.names[n] for n in before])

    # Trades and resets --------------------------------------------------------------------------------------------
    async def trade_between(self, current, probes, record, offerer, answerer, while_open=None, freeze=None,
                            labels=(None, None), freeze_when="first"):
        """The offerer offers the answerer a trade from PLAYERS; `while_open` runs while the offer waits; the answerer
        picks its Pokemon from Pending trade (each the first one, or the rows `labels` names: the offerer's, the
        answerer's); both confirm; the host applies it (each save two revisions on): "applied". `freeze` (--freeze
        ...:trade) runs once the first player confirmed (`freeze_when` "both": once both did); a trade it ends,
        aborted on both sides with nothing left open, is "cancelled"; one that leaves a player's launcher without the
        host, holding the trade (`self.interrupted`), is "interrupted"."""
        host = self.harness.host
        pair = (offerer, answerer)
        before = {n: (await self.launcher(current[n]))["revision"] for n in pair}
        await probes[offerer].open_players()
        await probes[offerer].choose(host.accounts[answerer].display_name, prefix=True)
        # The seconds from each player's choice to its trade window open again (its party prepared on the host),
        # the time a player looks at the field meanwhile.
        prepared = {}
        if WALK[0]:
            await self.count_exports(current[offerer])
        chosen = time.monotonic()
        await probes[offerer].choose("Trading", wait=False)
        try:
            if WALK[0]:
                await self.walk_meanwhile(probes[offerer], record)
            offered = {offerer: await pick(probes[offerer], labels[0], again="Trading")}
        finally:
            if WALK[0]:
                record("trade-exports", player=self.harness.names[offerer], statuses=await self.exports(current[offerer]))
        prepared[offerer] = round(time.monotonic() - chosen, 1)
        if while_open is not None:
            await while_open()
        await probes[answerer].open_players()
        await probes[answerer].choose("Pending trade")
        chosen = time.monotonic()
        await probes[answerer].choose("Choose your Pokemon", wait=False)
        offered[answerer] = await pick(probes[answerer], labels[1], again="Choose your Pokemon")
        prepared[answerer] = round(time.monotonic() - chosen, 1)
        record("trade-offers-chosen", offered={self.harness.names[n]: offered[n] for n in pair},
               window_seconds={self.harness.names[n]: prepared[n] for n in pair})
        started, confirmed = time.monotonic(), set()
        mashers = {}
        freezing, calm = None, 0
        try:
            while True:
                launchers = {n: await self.launcher(current[n]) for n in pair}
                for n in pair:
                    row = probes[n].read()
                    if n not in confirmed and row["active"] and not row["waiting"]:
                        try:
                            screen = unpack_screen(row["screen"], allow_trade_reopen=True, allow_battle_admission=True)[1]
                        except ValueError:
                            continue
                        if any(r.label == "Confirm this trade" for r in screen.rows):
                            await pick(probes[n], "Confirm this trade")
                            confirmed.add(n)
                            record("trade-confirmed", player=self.harness.names[n],
                                   seconds=round(time.monotonic() - started, 1))
                            if MASH[0]:
                                mashers[n] = asyncio.create_task(self.mash(probes[n]))
                            if (freeze is not None and freezing is None
                                    and (freeze_when == "first" or len(confirmed) == len(pair))):
                                freezing = asyncio.create_task(freeze())
                elapsed = round(time.monotonic() - started)
                if all(v.get("interaction") is None and v.get("trade") is None and v.get("revision") == before[n] + 2
                       for n, v in launchers.items()):
                    record("trade-applied", seconds=elapsed,
                           revisions={self.harness.names[n]: [before[n], launchers[n]["revision"]] for n in pair})
                    return "applied"
                # After a freeze: a launcher the host dropped meanwhile holds the trade until the player resolves it
                # (launcher_gui.py host_loss_trade_waiting), once nothing is open for the others.
                lost = [n for n, v in launchers.items() if v.get("code") == "host_loss_trade_waiting"]
                if (freezing is not None and freezing.done() and lost
                        and all(v.get("trade") is None for n, v in launchers.items() if n not in lost)):
                    record("trade-interrupted", players=[self.harness.names[n] for n in lost],
                           launchers={self.harness.names[n]: dict(code=v.get("code"), revision=v.get("revision"),
                                                                  connected=v.get("connected"))
                                      for n, v in launchers.items()})
                    self.interrupted = lost
                    return "interrupted"
                # After a freeze: the trade aborted on both sides (each save one revision on, its abort recorded:
                # launcher_session.py), nothing left open, for 3 s on end.
                ended = (freezing is not None and freezing.done()
                         and all(v.get("interaction") is None and v.get("trade") is None
                                 and v.get("code") == "trade_cancelled" and v.get("revision") == before[n] + 1
                                 for n, v in launchers.items()))
                calm = calm + 1 if ended else 0
                if calm >= 3:
                    record("trade-cancelled", seconds=elapsed, launchers={self.harness.names[n]: dict(
                        revision=launchers[n].get("revision"), notice=launchers[n].get("notice")) for n in pair})
                    return "cancelled"
                require(elapsed < self.watch, f"the trade did not finish: {launchers}")
                await asyncio.sleep(1)
        finally:
            if freezing is not None:
                await asyncio.gather(freezing, return_exceptions=True)
            for n, task in mashers.items():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                record("mashed-after-confirm", player=self.harness.names[n], presses=self.mashed.pop(id(probes[n]), 0))

    async def mash(self, probe):
        """--mash-after-confirm: after its Confirm, a player presses A and B by turns while the trade window is open
        (the owner's report of 2026-10-24: "when trade was being done it kicked us out and said trade cancelled"; once
        both had confirmed, the one row left under the cursor and B were Cancel trade)."""
        self.mashed = getattr(self, "mashed", {})
        key = 1
        while True:
            if probe.read()["active"]:
                await probe.press(key)
                self.mashed[id(probe)] = self.mashed.get(id(probe), 0) + 1
                key = 3 - key                      # A, then B
            else:
                await asyncio.sleep(.2)

    async def walk_meanwhile(self, probe, record):
        """--walk-while-preparing: the offerer walks left and right on the field while its party is prepared (the
        Players menu has closed; the owner's report of 2026-10-23, "it just kicks you out of the screen"), as a player
        who moves on may: the game refuses to freeze a moving party, and the launcher must wait for a calm field."""
        started = time.monotonic()
        held = 0
        while time.monotonic() - started < WALK[0]:
            row = probe.read()
            if row["active"] and not row["waiting"]:
                try:
                    screen = unpack_screen(row["screen"], allow_trade_reopen=True, allow_battle_admission=True)[1]
                except ValueError:
                    screen = None
                if screen is not None and any(r.action for r in screen.rows):
                    break                  # the trade window is open again ("Preparing your party" has no rows)
            key = (KEYS[LEFT], KEYS[RIGHT])[held % 2]
            await asyncio.to_thread(probe._chord, (key,), .4)
            held += 1
        record("walked-while-preparing", seconds=round(time.monotonic() - started, 1), holds=held)

    async def count_exports(self, worker):
        """--walk-while-preparing: the game's answers to this launcher's commands that need a calm field from now on
        (live_trade.CALM_OPCODES: the ownership query and grant, BEGIN_TRADE_EXPORT), as (opcode, status): 0 OK, 1 busy,
        2 unsafe (its field not calm yet)."""
        async def install(s):
            c = s._companion
            if getattr(c, "_proof_exports", None) is None:
                c._proof_exports, real = [], c.save_rpc

                async def save_rpc(control, **options):
                    response = await real(control, **options)
                    if control.opcode in CALM_OPCODES:
                        c._proof_exports.append((int(control.opcode), int(response.status)))
                    return response
                c.save_rpc = save_rpc
            c._proof_exports.clear()
        await on_worker(worker, install)

    async def exports(self, worker):
        async def read(s):
            return list(getattr(s._companion, "_proof_exports", None) or ())
        return await on_worker(worker, read)

    async def reset_page_refuses(self, n, current, probes, record, expected):
        screen = await self.open_reset_page(probes[n], refused=True)
        labels = [r.label for r in screen.rows]
        record("reset-page-refused", player=self.harness.names[n], status=screen.status, rows=labels)
        require(screen.status == expected and "Yes, reset now" not in labels,
                f"{self.harness.names[n]}'s RESET page showed {screen.status!r} {labels}, expected {expected!r}")
        await close_players(probes[n])
        await self.on_field(current[n])

    async def reset_once(self, n, current, probes, games, record, label, battle):
        """The reset key > "Yes, reset now" (MS-61): the launcher starts the game again from the host save
        in the same session; the others' connections carry on; the party is the host save's."""
        others = [m for m in range(len(current)) if m != n]
        epochs = {m: (await self.launcher(current[m]))["epoch"] for m in others}
        canonical = (await self.heads(current, self.harness.host))[n]
        old_pid = games[n].process.pid
        screen = await self.open_reset_page(probes[n])
        require([r.label for r in screen.rows][:2] == ["No, keep playing", "Yes, reset now"], f"the question: {screen}")
        running = battle is not None and not battle.done()
        await self.final_choice(probes[n], "Yes, reset now")
        code, revision = await self.restarted(n, current, probes, games, old_pid, record)
        after = {m: await self.launcher(current[m]) for m in others}
        now = probes[n].party_now()
        record(label, player=self.harness.names[n], code=code, revision=revision, party=now,
               battle_running_at_the_reset=running,
               others={self.harness.names[m]: [epochs[m], after[m]["epoch"], after[m]["connected"]] for m in others})
        require(now == dict(count=canonical["count"], box_crc=canonical["box_crc"]),
                f"after the reset the party is {now}, the host save's {canonical}")
        require(all(after[m]["connected"] and after[m]["epoch"] == epochs[m] for m in others),
                f"a reset changed another player's connection: {epochs} -> {after}")

    async def no_second_claim(self, n, current, probes, record):
        """Facing the table where its ball stood: no ball, A opens no starter screen, the party stays."""
        probe = probes[n]
        before = probe.party_now()
        chooser = probe.symbols["CB2_StarterChoose"][0]
        seen = []
        await probe.press(UP, frames=4, release=20)
        for _ in range(3):
            await probe.press(A, release=40)
            for _ in range(20):
                seen.append(self.screen_of(probe))
                await asyncio.sleep(.1)
        await self.back_to_field(current[n], probe)
        after = probe.party_now()
        record("no-second-claim", player=self.harness.names[n], party=[before, after],
               starter_screen=chooser in seen, position=list(pose_of(await self.companion_of(current[n]))[2:]))
        require(chooser not in seen and after == before, f"{self.harness.names[n]} claimed again: {before} -> {after}")

    # Drawing while in menus ---------------------------------------------------------------------------------------
    async def drawn_while(self, current, probes, record, subject, label, opened, seconds=3):
        """The subject opens something (`opened`); the others keep drawing it where it then stands the whole time. The
        place is taken once it is open (a dialogue walks there first), and only the subject may stand on it: draws()
        matches any player drawn at a place (busy4-2: the dialogue's walk to Birch left a tile another player shared)."""
        observers = [o for o in range(len(probes)) if o != subject]
        await opened()
        places = await self.places(current)
        place = places[subject]
        require(place is not None and all(places[o] != place for o in observers),
                f"{label}: the subject's tile is not its own: {places}")
        samples = await self.sample(probes, observers, place, seconds)
        summary = {self.harness.names[o]: dict(samples=len(v), drawn=sum(v), longest_gap=longest_gap(v))
                   for o, v in samples.items()}
        record("drawn-while", menu=label, player=self.harness.names[subject], place=list(place), observers=summary)
        require(all(all(v) for v in samples.values()), f"{label}: the others stopped drawing the player: {summary}")
        await self.back_to_field(current[subject], probes[subject])

    async def menus_seen(self, current, probes, record, subject):
        probe, worker = probes[subject], current[subject]
        field = probe.symbols["CB2_Overworld"][0]

        async def trainer_card():
            await probe.press(START, release=60)
            await self.to_row(probe, PLAYER_OPTIONS, lambda r: 0 < r["count"] <= len(r["actions"])
                              and PLAYER_OPTIONS in r["actions"][:r["count"]])
            await self.to_row(probe, TRAINER_CARD, lambda r: r["actions"][0] == TRAINER_CARD)
            wanted = probe.symbols["CB2_TrainerCard"][0]
            await self.until(lambda: self.screen(probe) == wanted, 20, "the trainer card")

        async def options():
            await probe.press(START, release=60)
            await self.to_row(probe, MENU_ACTION_OPTION, lambda r: 0 < r["count"] <= len(r["actions"])
                              and MENU_ACTION_OPTION in r["actions"][:r["count"]])
            await self.until(lambda: self.screen(probe) != field, 20, "the options")
            await asyncio.sleep(1)

        async def dialogue():
            companion = await self.companion_of(worker)
            await walk_to(probe, companion, LAB, *BELOW_BIRCH, record, subject)
            await probe.press(UP, frames=4, release=20)          # face Birch
            await probe.press(A, release=60)                     # "Are you curious about your Pokedex rating?"
            await asyncio.sleep(1)

        # first a tile of its own, below Birch (the others stand at the ball table or by the door)
        companion = await self.companion_of(worker)
        await walk_to(probe, companion, LAB, *BELOW_BIRCH, record, subject)
        await self.drawn_while(current, probes, record, subject, "trainer card", trainer_card)
        await self.drawn_while(current, probes, record, subject, "options", options)
        await self.drawn_while(current, probes, record, subject, "a dialogue (Professor Birch)", dialogue)

    # Route 101 ----------------------------------------------------------------------------------------------------
    async def across_route_101(self, n, current, probes, record):
        """Out of the lab and Littleroot, over Route 101's scene tiles and back: every step lands where it was taken."""
        probe, companion = probes[n], await self.companion_of(current[n])
        started = time.monotonic()
        for x, y in FROM_TABLE:
            await walk_to(probe, companion, LAB, x, y, record, n)
        await self.through_door(n, current, probes, record, DOWN, LITTLEROOT)
        for x, y in TO_THE_WAY_NORTH:
            await walk_to(probe, companion, LITTLEROOT, x, y, record, n)
        await self.through_door(n, current, probes, record, UP, ROUTE_101)
        entered = list(pose_of(companion)[2:])
        steps = [entered]
        for x, y in ON_ROUTE_101:
            await walk_to(probe, companion, ROUTE_101, x, y, record, n)
            steps.append(list(pose_of(companion)[2:]))
        record("across-route-101-without-a-scene", player=self.harness.names[n], entered=entered, steps=steps,
               seconds=round(time.monotonic() - started, 1))
        require(tuple(entered[2:]) in ((10, 19), (11, 19)), f"Route 101 entered at {entered}, not its scene row")
        await walk_to(probe, companion, ROUTE_101, 10, 19, record, n)
        await self.through_door(n, current, probes, record, DOWN, LITTLEROOT)
        await walk_to(probe, companion, LITTLEROOT, 10, 3, record, n)

    # The scenarios ------------------------------------------------------------------------------------------------
    async def _match(self, current, probes, games, host, symbols, record):
        self.t0 = time.monotonic()
        self.current, self.games = current, games
        sampler = asyncio.create_task(self.sample_memory(games, SAMPLE[0])) if SAMPLE[0] else None
        try:
            return await self._scenario(current, probes, games, host, symbols, record)
        finally:
            if sampler is not None:
                sampler.cancel()
                await asyncio.gather(sampler, return_exceptions=True)
                self.memory_sampled(record)

    async def _scenario(self, current, probes, games, host, symbols, record):
        host_player = None
        if REMOTE_ONLY[0]:
            async def player(s):
                return s._companion.config.player_id
            host_player = await on_worker(current[0], player)
        jitter_ms, stall_every, stall_ms = ROUGH[0]
        simulate_internet(LATENCY_MS[0], HOLD[0], host_player, everything=LATENCY_ALL[0], jitter_ms=jitter_ms,
                          stall_every=stall_every, stall_ms=stall_ms)
        simulate_disk(DISK_MS[0])
        count = len(current)
        for n, worker in enumerate(current):
            self.own_display(n, worker)
            self.watch_loop(n, worker)
        for n, probe in enumerate(probes):
            status, rows = await players_tab(probe)
            require(status.startswith(f"Connected: {count}/"), f"player {n}'s PLAYERS: {status} {rows}")
        if self.scenario in GIVE_UP_HOLDING:
            # the sources' own parties (the fixtures' Pokemon, saved on the host at enrollment): the battle at once
            canonical = await self.heads(current, host)
            record("parties-of-the-sources", canonical=canonical, games=[p.party_now() for p in probes])
            require(all(c["count"] == p.party_now()["count"] > 0 for c, p in zip(canonical, probes)),
                    f"the sources' parties are not the host's saves: {canonical}")
            giver_slot = None
            if self.scenario == "give-up-switch":
                # the giver is the player whose lead is the Ninjask (giveup-switch-b), whichever --source and whichever
                # core its game is (a 1v1's cores follow the players' ids)
                species = await self.party_species(current)
                leads = [party[0][0] if party else None for party in species]
                require(leads.count(NINJASK) == 1, f"give-up-switch: one player leads with the Ninjask: {species}")
                giver_slot = leads.index(NINJASK)
                record("give-up-switch-giver", player=self.harness.names[giver_slot], parties=species)
            await self.challenge_1v1(self.harness.host, probes, 0, 1)
            await self.give_up_battle(current, probes, symbols, record, mid_turn=self.scenario in MID_TURN,
                                      label=self.scenario, giver_slot=giver_slot)
            parties = await self.heads(current, host)
            revisions = [(await self.launcher(w))["revision"] + 1 for w in current]
            return dict(parties=parties, revisions=revisions)
        if self.scenario in HOLDING:
            if self.scenario in ("trade-mail", "trade-egg"):
                async def capability(s):
                    return dict(manifest_trade_egg_abi_version=s._manifest.get("trade_egg_abi_version"),
                                host_trades_eggs=bool(getattr(s._server.trade_desk, "trade_eggs", False)),
                                host_trades_mail=bool(getattr(s._server.trade_desk, "trade_mail", False)),
                                launcher_trade_egg_abi_version=s._companion.config.trade_egg_abi_version)
                found = await on_worker(current[0], capability)
                record("eggs-and-mail-capability", **found)
                require(found["host_trades_mail"], f"the host does not trade Mail: {found}")
                require(self.scenario != "trade-egg" or (found["host_trades_eggs"]
                                                         and found["manifest_trade_egg_abi_version"] == 1),
                        f"this world's game does not declare that it hatches a traded Egg right: {found}")
            if self.scenario == "trade-mail":
                await self.trade_mail(current, probes, record)
            elif self.scenario == "trade-egg":
                await self.trade_egg(current, probes, games, record)
            else:
                await self.trade_evolve(current, probes, record, evolves=self.scenario == "trade-evolve")
            parties = await self.heads(current, host)
            revisions = [(await self.launcher(w))["revision"] + 1 for w in current]
            return dict(parties=parties, revisions=revisions)
        canonical = await self.heads(current, host)
        record("linked-with-no-pokemon", games=[p.party_now() for p in probes], canonical=canonical)
        require(all(p.party_now()["count"] == 0 for p in probes) and all(c["count"] == 0 for c in canonical),
                "a new character has a Pokemon before its claim")
        host_name = host.accounts[0].display_name
        await self.refused_with(probes[1], host_name, "Rival Battle - 1v1", record, 1, NO_POKEMON)
        await self.refused_with(probes[1], host_name, "Trading", record, 1, NO_POKEMON)
        await self.nothing_open(current, record, "nothing-left-open")

        if self.scenario == "lobby":
            await self.cut_and_rejoin(1, current, probes, games, record)
            before = [(await self.launcher(w))["revision"] for w in current]
            await self.claims(range(count), current, probes, record)
            if self.no_save:
                # A new Pokemon is saved on the host at once (the owner's reports of 2026-10-22 and -23: no save before
                # a battle, but no save on every small party change either).
                canonical = await self.auto_saved(current, record, "auto-saved-with-the-starters", before)
            else:
                canonical = await self.save_all(current, record, "saved-with-the-starters")
            require(all(c["count"] == 1 and len(c["serials"]) == 1 for c in canonical), f"the host's saves: {canonical}")
            fmt = {2: "1v1", 3: "1v1v1", 4: self.format}[count]
            started = time.monotonic()
            if self.no_save and count == 2:
                # The owner's report: right after the starters, the Players menu's "Rival Battle - 1v1" never began.
                await self.challenge_1v1(self.harness.host, probes, 0, 1)
                await self.play(current, probes, symbols, record, (0, 1), fmt, "rival-1v1")
            else:
                await self.lobby_battle(current, probes, symbols, record, tuple(range(count)), fmt, fmt)
            record("battle-seconds", seconds=round(time.monotonic() - started, 1), latency_ms=LATENCY_MS[0],
                   hold=HOLD[0])
        elif self.scenario in ("trade", "battle-trade"):
            await self.trade_back_and_forth(current, probes, record, symbols if self.scenario == "battle-trade" else None)
        elif self.scenario in GIVE_UPS:
            before = [(await self.launcher(w))["revision"] for w in current]
            await self.claims(range(count), current, probes, record)
            if self.no_save:
                canonical = await self.auto_saved(current, record, "auto-saved-with-the-starters", before)
            else:
                canonical = await self.save_all(current, record, "saved-with-the-starters")
            require(all(c["count"] == 1 and len(c["serials"]) == 1 for c in canonical), f"the host's saves: {canonical}")
            if self.scenario == "give-up-2v2":
                await self.lobby_2v2(probes, record, self.scenario)
                await self.give_up_battle(current, probes, symbols, record, label=self.scenario, slots=tuple(range(count)))
            else:
                await self.challenge_1v1(self.harness.host, probes, 0, 1)
                await self.give_up_battle(current, probes, symbols, record, mid_turn=self.scenario in MID_TURN,
                                          label=self.scenario)
        elif self.scenario == "mixed":
            await self.mixed(current, probes, games, host, symbols, record)
        else:
            await self.busy(current, probes, games, host, symbols, record)
        parties = await self.heads(current, host)
        revisions = [(await self.launcher(w))["revision"] + 1 for w in current]
        return dict(parties=parties, revisions=revisions)

    def party_species(self, current):
        """Each player's host save: the species and held item of every party Pokemon, in slot order."""
        async def species(s):
            rows = []
            for account in self.harness.host.accounts:
                head = inspect_closed_head(s._store, account.player_id)
                owned = inspect_ownership(inspect_flash(head.payload, save_profile=OWNERSHIP_PROFILE))
                party = sorted((r for r in owned.records if r.location.startswith("party:")), key=lambda r: r.location)
                rows.append([[r.species, validate_party_offer(head.payload, r.serial).held_item
                              if r.species <= 721 else None] for r in party])
            return rows
        return on_worker(current[0], species)

    async def through_evolution(self, n, current, probes, record, received_crc, timeout=90):
        """After a trade: B once a second until the game's party is no longer the one the trade brought (its received
        Pokemon evolved: the scene's text goes by with B, which stops nothing in a trade evolution) and the field
        is back for two seconds."""
        started, calm = time.monotonic(), 0
        companion = await self.companion_of(current[n])
        async with asyncio.timeout(timeout):
            while True:
                on_field = (pose_of(companion) or (0,))[0] == 1
                changed = probes[n].party_now()["box_crc"] != received_crc
                calm = calm + 1 if on_field and changed else 0
                if calm >= 4:
                    break
                if not on_field:
                    await probes[n].press(B)
                await asyncio.sleep(.5)
        record("through-the-evolution", player=self.harness.names[n], seconds=round(time.monotonic() - started, 1),
               game=probes[n].party_now())

    async def trade_evolve(self, current, probes, record, evolves=True):
        """KNOWN_ISSUES MS-151: the scenario's docstring (trade-evolve); with evolves False, trade-forms."""
        canonical = await self.save_all(current, record, "saved-with-their-pokemon")
        require(all(c["count"] >= 1 for c in canonical), f"a player without a Pokemon: {canonical}")
        before = await self.party_species(current)
        record("species-before", species=before)
        outcome = await self.trade_between(current, probes, record, 0, 1)
        require(outcome == "applied", f"the trade was not applied: {outcome}")
        traded = await self.heads(current, self.harness.host)
        record("traded", canonical=traded, species=await self.party_species(current),
               games=[p.party_now() for p in probes])
        if evolves:
            await asyncio.gather(*(self.through_evolution(n, current, probes, record, traded[n]["box_crc"])
                                   for n in (0, 1)))
        else:
            await asyncio.sleep(3)                    # the trade's banner, the field back
        canonical = await self.save_all(current, record, "saved-after-the-evolutions" if evolves else "saved-after-the-trade")
        after = await self.party_species(current)
        record("species-after", species=after, expected=list(self.expect_species))
        require(tuple(p[0][0] for p in after) == self.expect_species,
                f"after the trade the parties hold {after}, expected {self.expect_species} first")
        require(all(c["serials"] == t["serials"] for c, t in zip(canonical, traded)),
                f"the evolutions changed the parties' Pokemon: {traded} then {canonical}")
        for n, party in enumerate(after):
            require(party[0][1] in (0, None), f"{self.harness.names[n]}'s evolved Pokemon still holds item {party[0][1]}")

    # Mail and Eggs (owner decision 39) ------------------------------------------------------------------------------
    async def host_saves(self, current):
        """Each player's canonical save on the host (its payload), as the store holds it now."""
        async def read(s):
            return [inspect_closed_head(s._store, a.player_id).payload for a in self.harness.host.accounts]
        return await on_worker(current[0], read)

    async def integrity(self, current, record, label):
        """The world's integrity check (the store's own: every checkpoint, ownership and trade history replayed)."""
        async def check(s):
            started = time.monotonic()
            s._store.integrity_check()
            return round(time.monotonic() - started, 1)
        record(label, passed=True, seconds=await on_worker(current[0], check))

    @staticmethod
    def active_tasks(probe):
        tasks = probe.mem("gTasks", 640)
        return {probe.code(int.from_bytes(tasks[o:o + 4], "little")) & ~1 for o in range(0, 640, 40) if tasks[o + 4]}

    @staticmethod
    def task_cursor(probe, function):
        """data[0] of the active task running `function` (struct Task: func, isActive, prev, next, priority, data[16]):
        the party menu's selection window keeps its cursor there each frame (Task_HandleSelectionMenuInput)."""
        tasks = probe.mem("gTasks", 640)
        for o in range(0, 640, 40):
            if tasks[o + 4] and probe.code(int.from_bytes(tasks[o:o + 4], "little")) & ~1 == function:
                return int.from_bytes(tasks[o + 8:o + 10], "little", signed=True)
        return None

    @staticmethod
    def fading(probe):
        """A palette fade runs (gPaletteFade.active, bit 31 of its fourth word: the menus take no input meanwhile)."""
        return bool(int.from_bytes(probe.mem("gPaletteFade", 4, 12), "little") >> 31)

    async def settled(self, probe, predicate, timeout, what):
        """`predicate()` holds with no palette fade running, for a second on end (a press during a fade is lost)."""
        calm = 0
        try:
            async with asyncio.timeout(timeout):
                while calm < 5:
                    calm = calm + 1 if predicate() and not self.fading(probe) else 0
                    await asyncio.sleep(.2)
        except TimeoutError:
            raise AssertionError(f"{what}: not there after {timeout} s") from None

    async def press_until(self, probe, key, done, what, tries=3, wait=10):
        """`key` until `done()`: a press the game did not take (a loaded PC's slow frame) is pressed again."""
        for _ in range(tries):
            await probe.press(key)
            try:
                async with asyncio.timeout(wait):
                    while not done():
                        await asyncio.sleep(.1)
                return
            except TimeoutError:
                continue
        raise AssertionError(f"{what}: {tries} presses, no answer")

    @staticmethod
    def party_actions(probe):
        """The actions of the menu a party Pokemon opened (sPartyMenuInternal), in its order."""
        base = int.from_bytes(probe.mem("sPartyMenuInternal", 4), "little")
        if not base:
            return []
        raw = read_at(probe, base + PARTY_ACTIONS, PARTY_ACTION_COUNT - PARTY_ACTIONS + 1)
        return list(raw[:min(raw[-1], PARTY_ACTION_COUNT - PARTY_ACTIONS)])

    @staticmethod
    def mail_screen(probe):
        """The game's Mail screen as it stands (sMailRead): its callback, the Mail it reads, its lines and author."""
        base = int.from_bytes(probe.mem("sMailRead", 4), "little")
        if not base:
            return None
        raw = read_at(probe, base, MAIL_POINTER + 4)
        pointer = int.from_bytes(raw[MAIL_POINTER:MAIL_POINTER + 4], "little")
        return dict(callback=probe.code(int.from_bytes(raw[MAIL_CALLBACK:MAIL_CALLBACK + 4], "little")),
                    pointer=pointer, mail=read_at(probe, pointer, MAIL_SIZE) if pointer else None,
                    lines=[line for line in (evidence.text(raw[MAIL_LINES + 64 * i:MAIL_LINES + 64 * (i + 1)])
                                             for i in range(8)) if line.strip()],
                    author=evidence.text(raw[MAIL_AUTHOR:MAIL_AUTHOR + 12]))

    async def read_mail_in_game(self, n, current, probes, record, index, label):
        """START > POKEMON > party Pokemon `index` > MAIL > READ, as a player reads a Mail: the game's own Mail screen,
        pictured once its letter shows; B, and back to the field. Returns what the screen read: the 36 bytes of the
        Mail it shows, where the game holds them (its save block's Mail slot the Pokemon names), its lines."""
        probe, worker, name = probes[n], current[n], self.harness.names[n]
        await self.start_menu_item(worker, probe, MENU_ACTION_POKEMON, "CB2_UpdatePartyMenu")
        choose, select = probe.symbols["Task_HandleChooseMonInput"][0], probe.symbols["Task_HandleSelectionMenuInput"][0]
        await self.settled(probe, lambda: choose in self.active_tasks(probe), 60, f"{name}: the party menu")

        def slot():
            return probe.mem("gPartyMenu", 20)[9]                # gPartyMenu.slotId
        # The Classic screen's party is a column (DOWN: the next Pokemon; RIGHT from the first: the second); the 3D
        # build's native screen a grid of two columns (RIGHT, LEFT within a row; DOWN: the row below or CANCEL). Both
        # take RIGHT from the first Pokemon to the second; otherwise a step toward it, the cursor read after each.
        for _ in range(12):
            here = slot()
            if here == index:
                break
            key = (RIGHT if index % 2 == 1 and here == index - 1 else LEFT if index % 2 == 0 and here == index + 1
                   else DOWN)
            await self.press_until(probe, key, lambda: slot() != here, f"{name}: the party menu's cursor")
        require(slot() == index, f"{name}: the party menu's cursor did not reach Pokemon {index}")
        await self.press_until(probe, A, lambda: select in self.active_tasks(probe), f"{name}: Pokemon {index}'s menu")
        await self.settled(probe, lambda: self.task_cursor(probe, select) is not None, 30, f"{name}: Pokemon {index}'s menu")
        actions = self.party_actions(probe)
        require(MENU_MAIL in actions, f"{name}: Pokemon {index}'s menu offers no MAIL: {actions}")
        for _ in range(len(actions)):
            cursor = self.task_cursor(probe, select)
            if cursor == actions.index(MENU_MAIL):
                break
            await self.press_until(probe, DOWN, lambda: self.task_cursor(probe, select) != cursor, f"{name}: to MAIL")
        require(self.task_cursor(probe, select) == actions.index(MENU_MAIL), f"{name}: the cursor did not reach MAIL")
        submenu = [MENU_READ, MENU_TAKE_MAIL, MENU_CANCEL2]
        await self.press_until(probe, A, lambda: self.party_actions(probe) == submenu, f"{name}: MAIL's READ, TAKE, CANCEL")
        await self.settled(probe, lambda: self.task_cursor(probe, select) == 0, 30, f"{name}: READ under the cursor")
        reading, ready = probe.symbols["CB2_MailRead"][0], probe.symbols["CB2_ExitOnKeyPress"][0]
        party_menu = probe.symbols["CB2_UpdatePartyMenu"][0]
        # READ: the selection window goes (the party menu closes for the Mail); a press it did not take is pressed again
        await self.press_until(probe, A, lambda: select not in self.active_tasks(probe)
                               or self.screen(probe) != party_menu, f"{name}: READ")
        await self.until(lambda: self.screen(probe) == reading and (self.mail_screen(probe) or {}).get("callback") == ready,
                         90, "the Mail on the screen")
        await asyncio.sleep(1)                                   # drawn (the 3D build's native UI reads it each frame)
        shown = self.mail_screen(probe)
        block1 = int.from_bytes(probe.mem("gSaveBlock1Ptr", 4), "little")
        slot = probe.mem("gParties", 100, 100 * index)[85]
        picture = game_picture(probe, self.harness.output / f"{label}.png", settle=.5)
        # B: the letter closes and the party menu comes back
        await self.press_until(probe, B, lambda: self.screen(probe) != reading or (self.mail_screen(probe) or {}).get(
            "callback") != ready, f"{name}: closing the Mail")
        await self.until(lambda: self.screen(probe) == party_menu, 60, "the party menu after the Mail")
        await self.settled(probe, lambda: self.screen(probe) == party_menu, 60, f"{name}: the party menu again")
        await self.back_to_field(worker, probe, timeout=90)
        await self.on_field(worker)
        result = dict(player=name, party_index=index, slot=slot, picture=picture, lines=shown["lines"],
                      author=shown["author"], mail=shown["mail"].hex(),
                      reads_its_own_slot=shown["pointer"] == block1 + MAIL_OFFSET + slot * MAIL_SIZE)
        record("read-the-mail-in-game", **result)
        require(result["reads_its_own_slot"], f"{name}'s Mail screen reads another place than Mail slot {slot}")
        return result

    async def mail_trade_checked(self, current, record, before, serials, label):
        """The host's saves after a trade, read against `before` (trade_eggs_mail_evidence.mail_trade); the world's
        integrity check."""
        after = await self.host_saves(current)
        summary, problems = evidence.mail_trade(tuple(before), tuple(after), serials)
        record(label, problems=problems, **summary)
        require(not problems, f"{label}: {problems}")
        await self.integrity(current, record, label + "-integrity")
        return after

    async def trade_mail(self, current, probes, record):
        """The trade-mail scenario (the docstring): two trades, the first with Mail both ways, the second one way."""
        canonical = await self.save_all(current, record, "saved-with-their-pokemon")
        names = self.harness.names
        before = await self.host_saves(current)
        views = [evidence.save_mail(payload) for payload in before]
        record("mail-before", sides=[{str(serial): row for serial, row in view["party"].items()} for view in views])
        (wingull,), (treecko, zigzagoon) = canonical[0]["serials"], canonical[1]["serials"]
        require(views[0]["party"][wingull]["mail"] is not None and views[1]["party"][treecko]["mail"] is not None
                and views[1]["party"][zigzagoon]["mail"] is None,
                f"the sources do not hold the Mail this scenario trades: {views[0]['party']} {views[1]['party']}")
        freeze = next(((kind, slot, when, seconds) for kind, slot, when, seconds, at in FREEZES
                       if when in TRADE_CUTS and at == 1), None)

        async def committed(s):
            return s._store._connection.execute("SELECT COUNT(*) FROM trade_transactions").fetchone()[0]
        while True:
            hold = None
            if freeze is not None:
                base = await on_worker(current[0], committed)

                async def hold(f=freeze, base=base):
                    if f[2] == "trade-committed":
                        # the host has committed both post-images (one SQLite transaction); neither game has them yet
                        async with asyncio.timeout(120):
                            while await on_worker(current[0], committed) <= base:
                                await asyncio.sleep(.05)
                    await self.freeze(f[0], f[1], f[3], record, f"trade, {f[2]}")
            outcome = await self.trade_between(current, probes, record, 0, 1, freeze=hold,
                                               freeze_when="first" if freeze and freeze[2] == "trade" else "both",
                                               labels=("Wingull Lv20", "Treecko Lv20"))
            if outcome == "interrupted":
                for n in self.interrupted:
                    await self.resolve_interrupted_trade(n, current, probes, record)
            for n in (0, 1):
                await self.on_field(current[n])
            after = await self.host_saves(current)
            heads = await self.heads(current, self.harness.host)
            made = [h["serials"] for h in heads] == [[treecko], [wingull, zigzagoon]]
            unmade = [h["serials"] for h in heads] == [[wingull], [treecko, zigzagoon]]
            # Atomic: applied on both sides or on neither; each Mail on exactly one side.
            census = evidence.census(after)
            record("trade-outcome", outcome=outcome, made=made, canonical=heads, host_committed_trades=await on_worker(
                       current[0], committed), mails_held=census, freeze=None if freeze is None else list(freeze))
            require(made or unmade, f"the trade left the parties half made: {heads}")
            require(census == [1, 1], f"the two Mails are not each held once: {census}")
            if made:
                break
            # Ended unmade: every Mail slot and every party Pokemon's Mail as before the trade, on both sides.
            for side, payload in enumerate(after):
                now = evidence.save_mail(payload)
                require(now == views[side], f"a trade ended unmade changed {names[side]}'s Mail: {now['party']}")
            record("trade-not-made-mail-unmoved", outcome=outcome)
            freeze = None
        after = await self.mail_trade_checked(current, record, before, (wingull, treecko), "mail-traded")
        received = [await self.read_mail_in_game(n, current, probes, record, 0, label)
                    for n, label in enumerate(("host-reads-the-treeckos-mail", "friend-reads-the-wingulls-mail"))]
        for n, seen in enumerate(received):
            held = evidence.save_mail(after[n])["party"][treecko if n == 0 else wingull]
            require(seen["mail"] == held["mail"] and seen["slot"] == held["mail_slot"],
                    f"{names[n]}'s game shows another Mail than its host save holds: {seen} {held}")
        # The second trade: the Treecko's Mail back to its first trainer's side, nothing the other way.
        outcome = await self.trade_between(current, probes, record, 0, 1, labels=("Treecko Lv20", "Zigzagoon Lv20"))
        require(outcome == "applied", f"the second trade was not applied: {outcome}")
        await self.mail_trade_checked(current, record, after, (treecko, zigzagoon), "mail-traded-one-way")
        seen = await self.read_mail_in_game(1, current, probes, record, 1, "friend-reads-the-treeckos-mail")
        final = evidence.save_mail((await self.host_saves(current))[1])["party"][treecko]
        require(seen["mail"] == final["mail"], f"the friend's game shows another Mail than its host save: {seen}")
        canonical = await self.save_all(current, record, "saved-after-the-trades")
        return canonical

    async def until_hatched(self, n, current, probes, record, hatched, label, timeout=900):
        """The receiver walks to and fro on row 12 of Littleroot (east or west of the lab's street, as it stands) until
        `hatched()` holds and its field is calm: every step a player's own; anything else on its screen (the "Huh?"
        of a party Egg's hatch, the hatch scene and its nickname question, a banner) gets B, as a player gets through
        it (NO to the nickname). Returns the steps taken."""
        probe, companion = probes[n], await self.companion_of(current[n])
        field = probe.symbols["CB2_Overworld"][0]
        here = pose_of(companion)
        require(here is not None and tuple(here[2:4]) == LITTLEROOT, f"{self.harness.names[n]} is not in Littleroot: {here}")
        row, low, high = PACE["east" if here[4] >= 10 else "west"]
        target, steps, presses, calm, stuck = high, 0, 0, 0, 0
        started, pictures, pictured = time.monotonic(), [], 0.0

        def calm_field():
            pose = pose_of(companion)
            return (self.screen(probe) == field and probe.mem("sGlobalScriptContextStatus", 1)[0] == SCRIPT_SHUTDOWN
                    and pose is not None and pose[0] == 1)
        while True:
            require(time.monotonic() - started < timeout, f"{label}: nothing hatched after {steps} steps")
            if hatched():
                if len(pictures) < 3 and not calm_field() and time.monotonic() - pictured > 4:
                    # the hatch scene (the Egg, the Pokemon out of it, its message), a few seconds apart
                    pictures.append(game_picture(probe, self.harness.output / f"{label}-{len(pictures) + 1}.png",
                                                 settle=.3))
                    pictured = time.monotonic()
                calm = calm + 1 if calm_field() else 0
                if calm >= 4:
                    break
                if not calm_field():
                    await probe.press(B, release=30)
                    presses += 1
                await asyncio.sleep(.5)
                continue
            if not calm_field():
                await probe.press(B, release=30)
                presses += 1
                await asyncio.sleep(.4)
                continue
            pose = pose_of(companion)
            x, y = pose[4], pose[5]
            if y != row:
                key = DOWN if y < row else UP
            else:
                if x == target or stuck >= 6:       # an end of the walk, or somebody standing in the way
                    target, stuck = (low if target == high else high), 0
                key = RIGHT if target > x else LEFT
            await probe.press(key, frames=8, release=1)
            deadline, moved = time.monotonic() + 1.5, False
            while time.monotonic() < deadline:
                await asyncio.sleep(.05)
                now = pose_of(companion)
                if now is not None and now[2:] != pose[2:]:
                    steps, moved = steps + 1, True
                    break
                if not calm_field():
                    break
            stuck = 0 if moved else stuck + 1
        record(label, player=self.harness.names[n], steps=steps, presses_of_b=presses, pictures=pictures,
               seconds=round(time.monotonic() - started, 1), position=list(pose_of(companion)[2:]))
        return steps

    def game_party_record(self, probe, index):
        return probe.mem("gParties", 100, 100 * index)

    def game_box_record(self, probe, personality):
        """The PC slot (box:B:N) holding the record of this personality in the running game, and its 80 bytes."""
        storage = read_at(probe, int.from_bytes(probe.mem("gPokemonStoragePtr", 4), "little"), STORAGE_SIZE)
        for box in range(14):
            for slot in range(30):
                location = f"box:{box}:{slot}"
                record = box_at(b"", storage, location)
                if record[19] & 2 and int.from_bytes(record[:4], "little") == personality:
                    return location, record
        return None, None

    async def log_lines(self, worker, prefix):
        """The breed log's lines of this player's running game (PKMN_TEST_BREED_LOG: the test build's own record of
        its party, its PC's Eggs and its banners), from the file the game appends them to (TEST_LOG beside its
        runtime.log: adopt); none while it has written none."""
        path = (await self.log_of(worker)).with_name(TEST_LOG)
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        return [line.split("Battle env test: ", 1)[1] for line in text.splitlines()
                if "Battle env test: " + prefix in line]

    async def reset_question(self, n, current, probes, record):
        """MS-61's soft reset key as a keyboard player presses it: Ctrl+R, which the game itself turns into A, B, START
        and SELECT held for one frame (sdl2.c), so a loaded PC's slow frames never see the four keys apart (the four
        keys pressed one by one did: START alone opened the START menu). On Windows the keyboard's messages for Ctrl
        and R are posted to the game's window, Ctrl's first (native_windows_process.chord; SDL keeps Ctrl held for the
        R that follows); should none of the three be taken there, a fourth try posts the four keys themselves at once
        (no frame comes between messages posted together: the busy proof's resets on the runner), and the record says
        so. The Players menu opens on its question ("Reset the game?", No first)."""
        probe = probes[n]
        tries = [CTRL_R] * 3 + ([RESET_KEYS] if WINDOWS else [])
        for attempt, keys in enumerate(tries):
            await self.on_field(current[n], timeout=60)
            await asyncio.to_thread(probe._chord, keys, max(probe.hold, .2))
            try:
                _, screen = await shown(probe, timeout=30)
            except TimeoutError:
                record("reset-key-not-taken", player=self.harness.names[n], attempt=attempt + 1)
                await self.back_to_field(current[n], probe, timeout=60)
                continue
            require(screen.title == "Reset the game?", f"the reset key opened {screen.title!r}: {screen.status!r}")
            if keys != CTRL_R:
                record("reset-question-by-the-four-keys", player=self.harness.names[n], attempt=attempt + 1)
            return screen
        raise AssertionError(f"{self.harness.names[n]}: the reset key opened nothing in {len(tries)} tries")

    async def egg_to_the_pc(self, n, current, probes, games, record):
        """--hatch-in box: the receiver's game started again from its host save (the reset key's "Yes, reset now",
        MS-61) with the test build's PKMN_TEST_EGG_TO_PC, which at its first field frame moves the party's Eggs to the
        PC as a deposit does (CopyMonToPC); then it saves on the host."""
        old_pid = games[n].process.pid
        os.environ["PKMN_TEST_EGG_TO_PC"] = "1"     # the next game a launcher starts (adopt's spawn copies os.environ)
        try:
            await self.reset_question(n, current, probes, record)
            await self.final_choice(probes[n], "Yes, reset now")
            code, revision = await self.restarted(n, current, probes, games, old_pid, record)
        finally:
            os.environ.pop("PKMN_TEST_EGG_TO_PC", None)
        moved = await self.log_lines(current[n], "breed moved")
        record("egg-moved-to-the-pc", player=self.harness.names[n], log=moved, code=code, revision=revision,
               party=probes[n].party_now())
        require(moved == ["breed moved 1 party Eggs to the PC"], f"the restarted game moved {moved}")
        return await self.save_all(current, record, "saved-with-the-egg-in-the-pc", slots=(n,))

    async def trade_egg(self, current, probes, games, record):
        """The trade-egg scenario (the docstring)."""
        names, host = self.harness.names, self.harness.host
        canonical = await self.save_all(current, record, "saved-with-their-pokemon")
        (zigzagoon_a, egg), (mudkip, zigzagoon_b) = canonical[0]["serials"], canonical[1]["serials"]
        before = await self.host_saves(current)
        location, laid = evidence.where_is(before[0], egg)
        record("egg-before-the-trade", serial=egg, location=location, record=laid, trainer=evidence.trainer(before[0]))
        require(laid["egg"] and laid["species"] == 175 and not laid["bad_egg"], f"the source holds no Togepi Egg: {laid}")
        outcome = await self.trade_between(current, probes, record, 0, 1, labels=("Egg", "Mudkip Lv5"))
        require(outcome == "applied", f"the Egg's trade was not applied: {outcome}")
        traded = await self.host_saves(current)
        heads = await self.heads(current, host)
        require([h["serials"] for h in heads] == [[zigzagoon_a, mudkip], [egg, zigzagoon_b]],
                f"the Egg's trade left {heads}")
        moved = evidence.where_is(traded[1], egg)
        record("egg-traded", location=moved[0], record=moved[1], canonical=heads)
        for key in ("egg", "personality", "ot_id", "species", "ivs", "moves", "friendship", "shiny", "nickname_hex"):
            require(moved[1][key] == laid[key], f"the traded Egg's {key} changed: {laid[key]} -> {moved[1][key]}")
        await self.integrity(current, record, "egg-traded-integrity")
        receiver = 1
        if self.hatch_in == "box":
            await self.egg_to_the_pc(receiver, current, probes, games, record)
            boxed = await self.host_saves(current)
            where, kept = evidence.where_is(boxed[receiver], egg)
            record("egg-in-the-pc-on-the-host", location=where, record=kept)
            require(where.startswith("box:") and kept["egg"], f"the host's save holds the Egg at {where}: {kept}")
            game_where, _ = self.game_box_record(probes[receiver], laid["personality"])
            require(game_where == where, f"the game holds the Egg at {game_where}, its host save at {where}")
            base = boxed

            def hatched():
                _, mon = self.game_box_record(probes[receiver], laid["personality"])
                require(mon is None or not mon[19] & 1, "the PC's Egg became a Bad Egg in the game")
                return mon is not None and not box_is_egg(mon)
        else:
            base = traded

            def hatched():
                mon = self.game_party_record(probes[receiver], 0)
                require(not mon[19] & 1, "the party's Egg became a Bad Egg in the game")
                return int.from_bytes(mon[:4], "little") == laid["personality"] and not box_is_egg(mon[:80])
        await self.until_hatched(receiver, current, probes, record, hatched, f"walked-until-the-egg-hatched-in-the-{self.hatch_in}")
        if self.hatch_in == "box":
            async with asyncio.timeout(60):
                while not await self.log_lines(current[receiver], "breed pc notice: PC EGG HATCHED!"):
                    await asyncio.sleep(.5)
            record("pc-hatch-banner", picture=game_picture(probes[receiver], self.harness.output / "pc-egg-hatched.png",
                                                            settle=.3))
        record("breed-log", player=names[receiver], party=await self.log_lines(current[receiver], "breed party"),
               box=await self.log_lines(current[receiver], "breed box"),
               notices=await self.log_lines(current[receiver], "breed pc notice"))
        await self.save_all(current, record, "saved-after-the-hatch", slots=(receiver,))
        hatched_saves = await self.host_saves(current)
        summary, problems = evidence.hatch(base[receiver], hatched_saves[receiver], egg)
        record("hatched-on-the-host", problems=problems, **summary)
        require(not problems, f"the hatch: {problems}")

        async def instance(s):
            row = s._store._connection.execute("SELECT player_id, ot_id, personality, status FROM ownership_instances "
                                               "WHERE serial = ?", (egg,)).fetchone()
            return dict(row)
        held = await on_worker(current[0], instance)
        record("hatched-instance", serial=egg, **held, hatcher=summary["hatcher"])
        require(held["ot_id"] == summary["hatcher"]["trainer_id"] and held["status"] == "active"
                and held["player_id"] == host.accounts[receiver].player_id,
                f"the host's record of the hatched Pokemon: {held}")
        await self.integrity(current, record, "hatched-integrity")
        if self.hatch_in == "box":
            # The Egg's first trainer brings its old character back (its source save, the Egg in it unhatched): the
            # host's own approval of a character coming back (enrollment_runtime.approve_transfer_source, as My Worlds
            # calls it) refuses it while the hatched Pokemon is the other player's, its earlier trainer ID in its
            # history (character_transfers.transfer_player); refused before anything is written.
            source = self.harness.sources[0]

            async def bring_back(s):
                from emerald_multiplayer.enrollment_runtime import approve_transfer_source
                from emerald_multiplayer.storage import StorageError
                try:
                    approve_transfer_source(s._store, host.accounts[0].player_id, source)
                except StorageError as error:
                    return dict(refused=True, code=error.code, message=str(error))
                return dict(refused=False)
            outcome = await on_worker(current[0], bring_back)
            record("old-save-with-the-unhatched-egg-brought-back", player=names[0], source=str(source), **outcome)
            require(outcome.get("code") == "pokemon_owned_here",
                    f"the copy of the unhatched Egg came back with its old character: {outcome}")
            await self.integrity(current, record, "refused-copy-integrity")
        if self.hatch_in == "party":
            # The hatched Pokemon traded on: the receiver offers it, the Egg's first trainer offers the Mudkip back.
            outcome = await self.trade_between(current, probes, record, receiver, 0, labels=("Togepi Lv1", "Mudkip Lv5"))
            require(outcome == "applied", f"the hatched Pokemon's trade was not applied: {outcome}")
            heads = await self.heads(current, host)
            require([h["serials"] for h in heads] == [[zigzagoon_a, egg], [mudkip, zigzagoon_b]],
                    f"the hatched Pokemon's trade left {heads}")
            onward = await self.host_saves(current)
            where, mon = evidence.where_is(onward[0], egg)
            record("hatched-pokemon-traded-on", location=where, record=mon, canonical=heads)
            hatched_record = summary["after"]
            for key in ("personality", "ot_id", "ot_name_bytes", "ot_gender", "species", "ivs", "moves", "shiny"):
                require(mon[key] == hatched_record[key], f"the traded-on Pokemon's {key} changed")
            require(not mon["egg"] and not mon["bad_egg"] and mon["checksum_ok"], f"the traded-on Pokemon: {mon}")
            await self.integrity(current, record, "traded-on-integrity")
        return await self.save_all(current, record, "saved-after-the-egg")

    async def trade_back_and_forth(self, current, probes, record, symbols=None):
        """The owner's report (2026-10-23, "trading is also broken"): two new characters claim their starters (with
        --no-save nobody saves: each new Pokemon is saved on the host by itself), trade them, and trade back.
        With `symbols` (--scenario battle-trade) they first fight the Players menu's rival 1v1, as the owner did.
        With --rounds all of it that many times over in one session (the stability audit's long session through the
        host); --freeze freezes a player's launcher session or game in one round's first trade or battle (`freeze`):
        a trade the freeze ends is applied on both sides or on neither, then made again."""
        before = [(await self.launcher(w))["revision"] for w in current]
        await self.claims((0, 1), current, probes, record)
        if self.no_save:
            canonical = await self.auto_saved(current, record, "auto-saved-with-the-starters", before)
        else:
            canonical = await self.save_all(current, record, "saved-with-the-starters")
        for round_ in range(1, ROUNDS[0] + 1):
            suffix = "" if ROUNDS[0] == 1 else f"-{round_}"
            if symbols is not None:
                await self.challenge_1v1(self.harness.host, probes, 0, 1)
                await self.play(current, probes, symbols, record, (0, 1), "1v1", "rival-1v1" + suffix,
                                freeze=self.freeze_for("battle", round_, record))
                if round_ == 1:
                    canonical = await self.heads(current, self.harness.host)
            if round_ == 1:
                serials = [c["serials"] for c in canonical]
            for offerer, answerer, label in ((0, 1, "traded"), (1, 0, "traded-back")):
                freeze = self.freeze_for("trade", round_, record) if label == "traded" else None
                expected = [serials[1], serials[0]] if label == "traded" else serials
                while True:
                    outcome = await self.trade_between(current, probes, record, offerer, answerer, freeze=freeze)
                    if outcome == "interrupted":
                        for n in self.interrupted:
                            await self.resolve_interrupted_trade(n, current, probes, record)
                    for n in (0, 1):
                        await self.on_field(current[n])
                    heads = await self.heads(current, self.harness.host)
                    if outcome == "applied":
                        break
                    # Ended by the freeze (cancelled, or resolved after the host dropped a player): nothing traded on
                    # either side; made again.
                    record("trade-not-made" + suffix, canonical=heads, games=[p.party_now() for p in probes])
                    unchanged = [expected[1], expected[0]]
                    require([h["serials"] for h in heads] == unchanged,
                            f"a trade ended by the freeze changed the host's saves: {heads}, not {unchanged}")
                    freeze = None
                record(label + suffix, canonical=heads, games=[p.party_now() for p in probes])
                require([h["serials"] for h in heads] == expected, f"{label}: the host's saves hold {heads}, not {expected}")

    async def resolve_interrupted_trade(self, n, current, probes, record):
        """What the launcher tells a player whose trade lost the host (launcher_gui.py host_loss_trade_waiting):
        Resolve interrupted trade (the launcher verifies the trade's fate and the saved bytes: trade_recovery_close),
        then close the game normally and open the same character again (its recovery runs before Continue)."""
        name = self.harness.names[n]
        worker = current[n]
        async with asyncio.timeout(120):
            while not worker.request_trade_recovery():
                await asyncio.sleep(1)
        record("resolve-interrupted-trade", player=name)
        async with asyncio.timeout(240):
            while (code := (await self.launcher(worker)).get("code")) not in ("trade_recovery_close",
                                                                               "trade_recovery_held"):
                await asyncio.sleep(1)
        record("trade-recovery", player=name, code=code)
        require(code == "trade_recovery_close", f"{name}: the interrupted trade was not verified ({code})")
        await self.rejoin(n, current, probes, self.games, record)

    def freeze_for(self, step, round_, record):
        """The --freeze of this round's `step` (trade, battle) as a coroutine function, or None."""
        for kind, slot, when, seconds, at in FREEZES:
            if when == step and at == round_:
                async def freeze():
                    await self.freeze(kind, slot, seconds, record, f"{step}, round {round_}")
                return freeze
        return None

    async def freeze(self, kind, slot, seconds, record, where):
        """A player's launcher session frozen (worker: its event loop runs nothing for `seconds`, so its companion
        neither reads nor writes, to the host or to its game, as when the launcher stalls) or its game stopped
        (game: the game process stalls, then runs on: stop_process, continue_process)."""
        name = self.harness.names[slot]
        started = time.monotonic()
        record("frozen", kind=kind, player=name, seconds=seconds, where=where, at=round(started - self.t0, 1))
        if kind == "worker":
            loop = self.current[slot]._loop
            require(loop is not None, f"{name}'s worker has no event loop to freeze")
            loop.call_soon_threadsafe(time.sleep, seconds)
            await asyncio.sleep(seconds)
        else:
            pid = self.games[slot].process.pid
            stop_process(pid)
            try:
                await asyncio.sleep(seconds)
            finally:
                continue_process(pid)
        record("thawed", kind=kind, player=name, seconds=round(time.monotonic() - started, 1), where=where)

    async def sample_memory(self, games, every):
        """--sample-every: each game's memory (resident, anonymous: its own), threads and open files, and this
        process's (the host and every launcher session), to samples.jsonl."""
        def status(pid):
            out = dict(pid=pid)
            try:
                for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                    name, _, value = line.partition(":")
                    if name in ("VmRSS", "RssAnon", "RssFile", "Threads"):
                        out[name] = int(value.split()[0])
                out["files"] = len(os.listdir(f"/proc/{pid}/fd"))
            except OSError:
                out["gone"] = True
            return out
        self.memory_samples = []
        path = self.harness.output / "samples.jsonl"
        if TRACE[0]:
            tracemalloc.start(1)
        while True:
            row = dict(t=round(time.monotonic() - self.t0, 1), games=[status(g.process.pid) for g in games],
                       proof=dict(status(os.getpid()), tasks=len(asyncio.all_tasks())))
            if TRACE[0]:
                # --trace-memory: where this process's Python memory is, by allocating line (the largest 40)
                top = tracemalloc.take_snapshot().statistics("lineno")[:40]
                row["traced"] = [[str(stat.traceback[0]), stat.size // 1024, stat.count] for stat in top]
            self.memory_samples.append(row)
            with path.open("a") as out:
                out.write(json.dumps(row) + "\n")
            await asyncio.sleep(every)

    def memory_sampled(self, record):
        """The samples' first, last, lowest and highest of each process, in the evidence."""
        rows = getattr(self, "memory_samples", [])
        if not rows:
            return
        def span(values):
            values = [v for v in values if v is not None]
            return dict(first=values[0], last=values[-1], low=min(values), high=max(values)) if values else None
        summary = {}
        for key in ("VmRSS", "RssAnon", "Threads", "files"):
            summary[key] = dict(games=[span([r["games"][n].get(key) for r in rows]) for n in range(len(rows[0]["games"]))],
                                proof=span([r["proof"].get(key) for r in rows]))
        summary["tasks"] = span([r["proof"]["tasks"] for r in rows])
        record("memory-over-the-session", samples=len(rows), seconds=rows[-1]["t"] - rows[0]["t"], **summary)

    async def cut_and_rejoin(self, n, current, probes, games, record):
        """The player's world connection is cut (a cable pulled); its launcher fences the link and keeps the save; it
        joins again with its party as it was."""
        async def cut(s):
            writer = s._companion._remote_writer
            require(writer is not None, "no world connection to cut")
            writer.transport.abort()
        before = (await self.launcher(current[n]))["epoch"]
        await on_worker(current[n], cut)
        async with asyncio.timeout(60):
            while (await self.launcher(current[n])).get("connected"):
                await asyncio.sleep(.5)
        record("connection-cut", player=self.harness.names[n], launcher=await self.launcher(current[n]))
        await asyncio.sleep(5)                        # the launcher's host-loss preservation
        await self.rejoin(n, current, probes, games, record)
        status, _ = await players_tab(probes[n])
        require(status.startswith(f"Connected: {len(current)}/"), f"after joining again PLAYERS says {status}")
        record("joined-again", player=self.harness.names[n], epochs=[before, (await self.launcher(current[n]))["epoch"]],
               party=probes[n].party_now())

    async def mixed(self, current, probes, games, host, symbols, record):
        names = [a.display_name for a in host.accounts]
        await self.claims((0, 1, 2), current, probes, record)
        canonical = await self.save_all(current, record, "saved-with-mixed-parties")
        require([c["count"] for c in canonical] == [1, 1, 1, 0], f"the host's saves: {canonical}")
        await self.refused_with(probes[3], names[0], "Trading", record, 3, NO_POKEMON)
        await self.refused_with(probes[0], names[3], "Rival Battle - 1v1", record, 0, PEER_NO_POKEMON)
        await self.nothing_open(current, record, "nothing-left-open-for-the-one-without-a-pokemon")

        await self.send_lobby(probes[0], names[1:], record, "lobby-sent-to-mixed-parties")
        for n in (1, 2, 3):
            await self.answer(probes[n], "Join lobby")
        status, rows = await self.lobby_page(probes[0])
        record("lobby-with-mixed-parties", status=status, rows=rows)
        require(status == "1v1v1v1 or 2v2: 4 joined" and "Start 1v1v1v1" in rows, f"the lobby says {status!r} {rows}")
        _, screen = await probes[0].choose("Start 1v1v1v1")
        record("start-refused", status=screen.status, rows=[r.label for r in screen.rows])
        require(screen.status == PEER_NO_POKEMON, f"starting with a trainer without a Pokemon said {screen.status!r}")
        await close_players(probes[0])
        await self.nothing_open(current, record, "nothing-open-after-the-refused-start")
        await self.answer(probes[3], "Leave lobby...", "Yes, leave the lobby")   # leaving asks first (No first)
        status, rows = await self.lobby_page(probes[0])
        record("lobby-after-the-fourth-left", status=status, rows=rows)
        require(status == "1v1v1: 3 joined" and "Start 1v1v1" in rows, f"the lobby says {status!r} {rows}")
        await probes[0].choose("Start 1v1v1")
        await self.accept(probes, (1, 2))

        async def claim_meanwhile():
            await asyncio.sleep(5)
            companion = await self.walk_to_lab(3, current, probes, record)
            return await self.claim(3, probes[3], companion, record)
        claiming = asyncio.create_task(claim_meanwhile())
        try:
            await self.play(current, probes, symbols, record, (0, 1, 2), "1v1v1", "1v1v1-with-mixed-parties", claiming)
            window = claiming.result()
        finally:
            if not claiming.done():
                claiming.cancel()
                await asyncio.gather(claiming, return_exceptions=True)
        record("claimed-while-the-others-battled", player=names[3], window=[round(w - self.t0, 1) for w in window])
        canonical = await self.save_all(current, record, "saved-after-the-fourth-claim", slots=(3,))
        require(canonical[3]["count"] == 1, f"the fourth's host save: {canonical[3]}")
        await self.lobby_battle(current, probes, symbols, record, (0, 1, 2, 3), self.format, self.format + "-of-four")

    async def busy(self, current, probes, games, host, symbols, record):
        await self.claims((0, 1, 2, 3), current, probes, record)
        canonical = await self.save_all(current, record, "saved-with-the-starters")
        require(all(c["count"] == 1 and len(c["serials"]) == 1 for c in canonical), f"the host's saves: {canonical}")

        await self.challenge_1v1(host, probes, 0, 1)
        before = {n: await probes[n].battle() for n in (0, 1)}
        battles = await self.enter(current, probes, (0, 1), record, "1v1-while-two-others-trade")
        stops, drivers = self.drive(current, probes, symbols, battles, (0, 1))
        battle = asyncio.create_task(self.finish(current, probes, battles, (0, 1), stops, drivers, record, "1v1"))
        try:
            async def while_open():
                await self.reset_page_refuses(3, current, probes, record, "Finish the trade first")
                if not probes[2].read()["active"] and (pose_of(await self.companion_of(current[2])) or (0,))[0] == 1:
                    await self.reset_page_refuses(2, current, probes, record, "Finish the trade first")
                else:
                    record("offerer-waits-in-the-trade-window", player=self.harness.names[2])
            await self.trade_between(current, probes, record, 2, 3, while_open)
            traded = await self.heads(current, host)
            record("traded", canonical=traded)
            require(traded[2]["serials"] == canonical[3]["serials"] and traded[3]["serials"] == canonical[2]["serials"],
                    f"the trade did not swap the starters: {canonical} -> {traded}")
            for k in (1, 2):
                await self.reset_once(3, current, probes, games, record, f"reset-{k}-with-others-playing", battle)
            await battle
        finally:
            if not battle.done():
                battle.cancel()
                await asyncio.gather(battle, return_exceptions=True)
        await self.back_on_the_field(current, probes, before, record, "1v1-everyone-back")
        await self.no_second_claim(2, current, probes, record)
        await self.menus_seen(current, probes, record, 1)
        await self.across_route_101(3, current, probes, record)


LATENCY_MS, HOLD, DISK_MS, REMOTE_ONLY, LATENCY_ALL, WALK, MASH = [0], [True], [0], [False], [False], [0.0], [False]
ROUGH = [(0.0, 0.0, 0.0)]   # --jitter-ms, --stall-every, --stall-ms (proof_network.RoughLink)
STRAY = [False]
ROUNDS, SAMPLE, FREEZES, TRACE = [1], [0.0], [], [False]
FREEZE_INTO_BATTLE = 20          # seconds into a battle that --freeze ...:battle starts
# live_trade.CALM_OPCODES (QUERY_OWNERSHIP, GRANT_OWNERSHIP, BEGIN_TRADE_EXPORT), spelled out to run on older apps too.
CALM_OPCODES = frozenset({10, 11, 12})


def _nt_process(pid, call):
    """Windows: the whole process stopped or let run on (ntdll's NtSuspendProcess and NtResumeProcess, as Process
    Explorer's Suspend and Resume do), as a PC that does not run the game for a moment (KNOWN_ISSUES MS-165)."""
    import ctypes
    from ctypes import wintypes
    PROCESS_SUSPEND_RESUME = 0x0800
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
    require(bool(handle), f"OpenProcess({pid}) for {call}: Windows error {ctypes.get_last_error()}")
    try:
        function = getattr(ntdll, call)
        function.restype = ctypes.c_long              # NTSTATUS
        function.argtypes = (wintypes.HANDLE,)
        status = function(handle)
        require(status == 0, f"{call}({pid}): NTSTATUS {status & 0xFFFFFFFF:#010x}")
    finally:
        kernel32.CloseHandle(handle)


def stop_process(pid):
    """--freeze game: the game's process stops running (SIGSTOP; on Windows NtSuspendProcess)."""
    if WINDOWS:
        _nt_process(pid, "NtSuspendProcess")
    else:
        os.kill(pid, signal.SIGSTOP)


def continue_process(pid):
    """The game's process runs on (SIGCONT; on Windows NtResumeProcess)."""
    if WINDOWS:
        _nt_process(pid, "NtResumeProcess")
    else:
        os.kill(pid, signal.SIGCONT)


async def run(args):
    LATENCY_MS[0], HOLD[0], DISK_MS[0], REMOTE_ONLY[0] = args.latency_ms, not args.no_hold, args.disk_ms, args.remote_only
    LATENCY_ALL[0], WALK[0], MASH[0] = args.latency_all, args.walk_while_preparing, args.mash_after_confirm
    STRAY[0] = args.stray_presses
    ROUGH[0] = (args.jitter_ms, args.stall_every, args.stall_ms)
    ROUNDS[0], SAMPLE[0], TRACE[0] = args.rounds, args.sample_every, args.trace_memory
    for spec in args.freeze:
        parts = spec.split(":")
        require(len(parts) in (4, 5) and parts[0] in ("worker", "game") and parts[2] in (*TRADE_CUTS, "battle"),
                f"--freeze {spec}: KIND:PLAYER:STEP:SECONDS[:ROUND], KIND worker or game, STEP trade, trade-confirmed "
                "or trade-committed (trade-mail), or battle")
        FREEZES.append((parts[0], int(parts[1]), parts[2], float(parts[3]), int(parts[4]) if len(parts) == 5 else 1))
    require(args.rounds >= 1 and (args.rounds == 1 or args.scenario in ("trade", "battle-trade")),
            "--rounds: the trade and battle-trade scenarios")
    require(not args.freeze or args.scenario in ("trade", "battle-trade", "trade-mail"),
            "--freeze: the trade, battle-trade and trade-mail scenarios")
    require(all(f[2] in ("trade", "battle") for f in FREEZES) or args.scenario == "trade-mail",
            "--freeze ...:trade-confirmed and trade-committed: the trade-mail scenario")
    require(not args.sample_every or not WINDOWS, "--sample-every: Linux games only (it reads /proc)")
    require(not args.trace_memory or args.sample_every, "--trace-memory: with --sample-every")
    if args.game_answer_seconds is not None:
        # The launchers run in this process: their battle sessions read it at each command (KNOWN_ISSUES MS-165).
        from emerald_multiplayer import battle_session
        battle_session.GAME_ANSWER_SECONDS = args.game_answer_seconds
    count = len(args.source)
    require(2 <= count <= 4, "two to four sources (short-introduction saves)")
    two = ("trade", "battle-trade", *HOLDING, *(name for name in GIVE_UPS if name != "give-up-2v2"))
    require(args.scenario == "lobby" or count == 4 or (args.scenario in two and count == 2),
            f"--scenario {args.scenario} needs four players (trade: two)")
    require(args.scenario != "give-up-2v2" or count == 4, "--scenario give-up-2v2 needs four players")
    expect = tuple(int(x) for x in args.expect_species.split(",")) if args.expect_species else ()
    require(args.scenario not in ("trade-evolve", "trade-forms") or len(expect) == count,
            f"{args.scenario}: --expect-species, one per player")
    require(args.hatch_in == "party" or args.scenario == "trade-egg", "--hatch-in: the trade-egg scenario")
    if not args.display:
        require(WINDOWS, "an X display per player")
        args.display = [f"desktop-{n}" for n in range(count)]         # Windows: one desktop; names for the records
    environment = dict(SDL_FRAMEBUFFER_ACCELERATION="0")
    if args.scenario == "trade-egg":
        # the test build's breed log (its party's and PC's Eggs and their cycles, its banners) in each game's own
        # TEST_LOG (NewcomersProof.adopt)
        environment["PKMN_TEST_BREED_LOG"] = "1"
    if args.scenario in ("trade-mail", "trade-egg", *GIVE_UP_HOLDING):
        # the sources' own parties (make_tower_saves.py's trade-mail-a/-b, trade-egg-a/-b, giveup-ko-a/-b,
        # giveup-switch-a/-b)
        counts = tuple(inspect_flash(Path(p).read_bytes()).metadata.party_count for p in args.source)
    else:
        counts = (1,) * count if args.scenario in HOLDING else (0,) * count
    proof = NewcomersProof(args.scenario, args.format, args.watch, args.match_seconds, args.no_save, expect,
                           hatch_in=args.hatch_in)

    def adopt(harness):
        proof.adopt(harness)
        if args.key_hold is not None:
            # --key-hold: each key held this long (a loaded PC's game runs few frames a second, and a press shorter
            # than its frame can come and go between two of them unseen)
            harness.hold = harness.evidence["key_hold_seconds"] = args.key_hold
    await launcher_proof(args, names=PLAYER_NAMES[:count], sources=args.source, party_counts=counts,
                         match=proof.match, version="Native newcomers proof",
                         settings=LIGHT_3D_SETTINGS if args.light_3d else "windowScale=2\n",
                         scope=__doc__.split("\n\n")[0] + f" Scenario: {args.scenario}, {count} players.",
                         environment=environment, after_save=proof.after_save,
                         on_harness=adopt)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", choices=SCENARIOS, required=True)
    parser.add_argument("--expect-species", default="",
                        help="trade-evolve, trade-forms: the species each player's first Pokemon is after the trade, "
                             "e.g. 589,617")
    parser.add_argument("--key-hold", type=float, default=None, metavar="SECONDS",
                        help="how long each key is held (the harness's own 0.15 s by default; longer on a loaded PC)")
    parser.add_argument("--hatch-in", choices=("party", "box"), default="party",
                        help="trade-egg: where the received Egg hatches (box: first moved to the PC by the test build's "
                             "PKMN_TEST_EGG_TO_PC in the receiver's game started again from its host save)")
    parser.add_argument("--format", choices=FORMATS, default=None,
                        help="the battle of four (lobby: 1v1v1v1 by default; mixed: 2v2 by default; give-up-2v2: "
                             "always the 2v2)")
    parser.add_argument("--game", type=Path, required=True,
                        help="the native game (Linux, unstripped; on Windows the Windows exe as the build made it)")
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source", type=Path, action="append", required=True, help="a short-introduction save per player")
    parser.add_argument("--display", action="append", help="an X display per player (Linux)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0)
    parser.add_argument("--watch", type=float, default=120, help="seconds a trade may take")
    parser.add_argument("--match-seconds", type=float, default=900)
    parser.add_argument("--sdl", type=Path, help="Windows: SDL2.dll of the game")
    parser.add_argument("--pe-symbols", type=Path, help="Windows: i686-w64-mingw32-nm -n of the game before its strip")
    parser.add_argument("--sizes", type=Path, help="Windows: nm -S of the Linux build of the same engine commit")
    parser.add_argument("--wine", type=Path, action="append", help="(not used)")
    parser.add_argument("--elf", type=Path)
    parser.add_argument("--no-save", action="store_true",
                        help="lobby, two players: nobody saves after the claims (the games save by themselves), then "
                             "the Players menu's Rival Battle - 1v1")
    parser.add_argument("--latency-ms", type=float, default=0, help="each way, between the host and every player")
    parser.add_argument("--remote-only", action="store_true",
                        help="--latency-ms for the other players only (the host's own game is on its PC)")
    parser.add_argument("--disk-ms", type=float, default=0, help="extra milliseconds on every fsync (a player's PC)")
    parser.add_argument("--latency-all", action="store_true",
                        help="--latency-ms on every message from the match on, not only the battle's")
    parser.add_argument("--no-hold", action="store_true", help="the host answers battle polls at once (before MS-62)")
    parser.add_argument("--jitter-ms", type=float, default=0,
                        help="each message up to this much later again, at random (in order; a rough connection)")
    parser.add_argument("--stall-every", type=float, default=0, metavar="SECONDS",
                        help="the connection stalls this often (with --stall-ms; a Wi-Fi hiccup)")
    parser.add_argument("--stall-ms", type=float, default=0, help="how long each stall holds every message")
    parser.add_argument("--mash-after-confirm", action="store_true",
                        help="trade: after its Confirm each player presses A and B by turns while its trade window is "
                             "open (the owner's report of 2026-10-24)")
    parser.add_argument("--stray-presses", action="store_true",
                        help="lobby, two players: the leader's and the friend's A presses land again where the game's "
                             "cursor stays (the owner's report of 2026-10-24, MS-69 on the lobby path)")
    parser.add_argument("--walk-while-preparing", type=float, default=0, metavar="SECONDS",
                        help="trade: the offerer walks that long once its Players menu closed for the trade")
    parser.add_argument("--light-3d", action="store_true",
                        help="--game is the 3D build (native UI): the light 3D settings of the 3D battle proof")
    parser.add_argument("--runtime-extra", type=Path, action="append",
                        help="Windows: another file beside the game (Mesa's opengl32.dll and its DLLs for the 3D build)")
    parser.add_argument("--rounds", type=int, default=1,
                        help="trade, battle-trade: the battle (battle-trade) and both trades this many times over in one "
                             "session")
    parser.add_argument("--sample-every", type=float, default=0, metavar="SECONDS",
                        help="Linux: each game's and this process's memory, threads and open files to samples.jsonl "
                             "this often")
    parser.add_argument("--game-answer-seconds", type=float, default=None,
                        help="how long a launcher waits for its game's answer to a battle command "
                             "(battle_session.GAME_ANSWER_SECONDS; 5 was the companion's own before KNOWN_ISSUES MS-165)")
    parser.add_argument("--trace-memory", action="store_true",
                        help="with --sample-every: this process's Python memory by allocating line in each sample "
                             "(tracemalloc; slows the process)")
    parser.add_argument("--freeze", action="append", default=[], metavar="KIND:PLAYER:STEP:SECONDS[:ROUND]",
                        help="trade, battle-trade, trade-mail (Linux): freeze a player's launcher session (worker) or "
                             "its game (game: SIGSTOP) for SECONDS, in ROUND's (1 by default) first trade once a player "
                             "confirmed (trade; trade-mail also trade-confirmed: once both did, trade-committed: once "
                             "the host committed it) or 20 s into its battle (battle)")
    args = parser.parse_args()
    if args.format is None:
        args.format = "2v2" if args.scenario in ("mixed", "give-up-2v2") else "1v1v1v1"
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
