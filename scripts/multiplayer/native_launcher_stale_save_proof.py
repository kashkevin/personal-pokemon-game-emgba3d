"""KNOWN_ISSUES MS-60 in real games: a game with progress its host has not saved is turned away at Enter battle.

The host prepares every native battle from each trainer's canonical save (the host's), and the game's PREPARE refuses
a preparation that is not its own state. Before the fix a battle entered with progress the host had not saved left both
trainers held with saving stopped, and its abandonment started the games again from their host saves, the progress lost
(L ms60-pvp-2, 2026-10-22). Now the game answers QUERY_PARTY (what PREPARE compares), the launcher names the answer in
its Enter claim, and the host turns a game whose state is not that save away before anything is held; the launcher then
saves the game once its Players menu is closed.

Two native games through the whole launcher (native_launcher_battle_proof.py's harness: the real LauncherWindow,
SessionWorker and LauncherSession per player, production world creation and enrollment, the real world server and
store), driven by ordinary key presses. The friend's unsaved progress is the game's own START > SAVE, as a player makes
it: a save to the game's own flash only (the launcher's Save now and its autosave are the host saves), after which the
game's save counter is ahead of its host save. Steps:

  round 1  The friend saves in the game. The host challenges the friend (1v1), the friend accepts and enters first: the
           friend's Enter is refused ("Not saved: close menu to save") and the challenge ends (aborted, save_needed)
           with no result; the host, whose screen still offers Enter, presses it: refused too, its menu says
           "Cancelled: a trainer must save". Neither game holds anything, no launcher
           offers "Abandon battle", both can save, and the friend's game still has its progress (same process, same save
           counter). With both menus closed the friend's launcher saves by itself (host revision 2), after which the
           game's QUERY_PARTY answer is its host save's.
  round 2  The friend saves in the game again. A new challenge; this time the host enters first and its Enter is
           recorded, then the friend enters: refused as before, and the host's launcher cancels its entry neutrally;
           nobody held, both can save; the friend's launcher saves again (revision 3).
  battle   The same two battle 1v1 to the end (native_launcher_battle_proof.native_menu_match): the refused challenges
           left nothing behind.

Then the harness's end: both save (host revision 2, friend 4), the canonical parties unchanged, the store's integrity
check, a normal close, a fresh Continue onto the same saves. On a game or host without the check the run ends with
"MS-60 reproduced" as soon as a refused Enter leaves a game held or a launcher offering recovery.

The sources are make_tower_saves.py abandon-a and abandon-b (one level-5 starter each).

    PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime \\
      python scripts/multiplayer/native_launcher_stale_save_proof.py \\
        --game ../engine/pokeemerald-mp --rom pokedev.gba --manifest manifest.json \\
        --source-a abandon-a.sav --source-b abandon-b.sav --display :98 --display :97 \\
        --output /private/multiplayer-proof/stale-save-1
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "windows-runtime"))
from native_launcher_battle_proof import WINDOWS, launcher_proof, native_menu_match  # noqa: E402
from qualify_admission_cleanup import on_worker, require  # noqa: E402
from qualify_launcher_session import inspect_closed_head  # noqa: E402
from emerald_multiplayer.battle_roster import CanonicalBattler  # noqa: E402
from emerald_multiplayer.menu_mailbox import unpack_screen  # noqa: E402
from emerald_multiplayer.player_menu import CANCEL_REASONS, REFUSALS  # noqa: E402

SAVE = 5                 # MENU_ACTION_SAVE (start_menu.c)
HOST, FRIEND = 0, 1
PENDING = ("pending-battle.json", "pending-battle-admission.json")
REFUSED = REFUSALS["save_needed"]
CANCELLED = CANCEL_REASONS["save_needed"]


class Reproduced(AssertionError):
    """A refused Enter left a game held or a launcher offering recovery (MS-60)."""


def save_counter(probe):
    return int.from_bytes(probe.mem("gSaveCounter", 4), "little")


def field_locked(probe):
    return probe.mem("sLockFieldControls", 1)[0] != 0


async def save_in_game(probe):
    """START > SAVE > YES (> YES to overwrite): the game's own save, to its own flash only. Returns the save counter
    before and after."""
    before = save_counter(probe)
    await probe.press(8, release=60)
    row = await probe.snapshot(lambda r: 0 < r["count"] <= len(r["actions"]) and SAVE in r["actions"][:r["count"]])
    target = row["actions"][:row["count"]].index(SAVE)
    for _ in range((target - row["start_cursor"]) % row["count"]):
        await probe.press(128)
    async with asyncio.timeout(90):
        while save_counter(probe) == before:
            # The start menu and its save dialog keep the field locked; unlocked without a new counter, it failed.
            require(field_locked(probe), "the game's own save ended without saving")
            await probe.press(1)
            await asyncio.sleep(.3)
        while field_locked(probe):               # "... saved the game." closes by itself, then the start menu
            await asyncio.sleep(.1)
    return before, save_counter(probe)


async def status_becomes(probe, text, timeout=60):
    """The game's Players screen once its status line is `text`."""
    last = None
    try:
        async with asyncio.timeout(timeout):
            while True:
                row = probe.read()
                if row["active"] and not row["waiting"]:
                    try:
                        screen = unpack_screen(row["screen"], allow_battle_admission=True)[1]
                    except ValueError:
                        screen = None                # a screen being copied in
                    if screen is not None:
                        last = screen.status
                        if screen.status == text:
                            return screen
                await asyncio.sleep(.1)
    except TimeoutError:
        raise AssertionError(f"the Players screen never said {text!r} (last {last!r})") from None


async def close_menu(probe):
    async with asyncio.timeout(20):
        while probe.read()["active"]:
            await probe.press(2)


async def challenge(current, probes):
    """The host challenges the friend to a 1v1; the friend accepts; both screens offer Enter battle."""
    await probes[HOST].open_players()
    await probes[HOST].choose("Battle Friend", prefix=True)
    await probes[HOST].choose("Rival Battle - 1v1")
    await probes[FRIEND].open_players()
    await probes[FRIEND].choose("Pending challenge")
    await probes[FRIEND].choose("Accept challenge")
    async with asyncio.timeout(20):
        while not all(screen.admission_action for _, screen in [await p.ready() for p in probes]):
            await asyncio.sleep(.05)

    async def descriptor(s):
        values = s._companion._bridge.menu_session.menu._battles
        require(len(values) == 1 and values[0]["state"] == "accepted", "expected exact accepted native challenge")
        return json.loads(json.dumps(values[0]))
    return await on_worker(current[HOST], descriptor)


def canonical_of(host, slot):
    """The canonical save's revision and what a battle prepared from it names (battle_roster.CanonicalBattler)."""
    async def read(s):
        c = s._companion
        head = inspect_closed_head(s._store, host.accounts[slot].player_id)
        battler = CanonicalBattler.from_checkpoint(head, world_id=c.world_id, build_id=c.config.build_id,
                                                   ruleset_id=c.config.ruleset_id, source_slot=0)
        return dict(revision=head.revision, counter=battler.native_counter, trainer_id=battler.trainer_id,
                    party_crc32=battler.party_crc32), battler
    return read


async def live_identity(worker):
    """The game's QUERY_PARTY answer (None from a game without it)."""
    async def query(s):
        return await s._companion.live_party_identity()
    return await on_worker(worker, query)


async def launcher_state(s):
    c = s._companion
    pose = c._local_pose
    return dict(code=s.status.code, revision=s.status.revision, can_save=bool(s.can_save),
                field=pose is not None and pose.activity == 1,
                abandon=bool(getattr(s.status, "battle_abandon_available", False)),
                recovery=bool(getattr(s.status, "battle_recovery_available", False)),
                save_failed=bool(s._save_failed), game_pid=None if s._game is None else s._game.process.pid,
                pending=[name for name in PENDING if (s.profile_directory / name).exists()])


def fate_of(battle_id):
    async def read(s):
        server = s._server
        desk = server.battle_desk
        battle = desk._active.get(battle_id) or desk._history.get(battle_id)
        room = server.battle_execution.rooms.get(battle_id)
        return dict(desk=None if battle is None else battle.state, reason=None if battle is None else battle.reason,
                    active=battle_id in desk._active, room=None if room is None else room.state,
                    room_error=None if room is None else room.error,
                    claimed=list(server.battle_execution.admission.claimed(battle_id)))
    return read


async def no_result(current, battle_id):
    async def history(s):
        values = (await s._companion.battle_challenge_rpc("history"))["result"]
        return [v for v in values if v["battle_id"] == battle_id]
    for worker in current:
        if await on_worker(worker, history):
            return False
    return True


async def settled(current, probes, games, battle_id, record, label, *, timeout=180):
    """Wait until the refused challenge has ended for everybody: archived, no hold, both launchers able to save with
    nothing pending or offered, the same game processes. Returns the battle's fate, the launchers' states and every
    (slot, what) a launcher showed on the way: a held entry being cancelled ("recovery", "save_failed"). A battle that
    started its route (BIND, then the refused PREPARE) or a launcher offering abandonment is MS-60 itself."""
    started, last, seen = time.monotonic(), None, set()
    pids = [g.process.pid for g in games]
    while True:
        fate = await on_worker(current[HOST], fate_of(battle_id))
        states = [await on_worker(w, launcher_state) for w in current]
        holds = [int.from_bytes(p.mem("gMultiplayerBattleHoldFlags"), "little") for p in probes]
        now = dict(fate=fate, launchers=states, holds=holds)
        if now != last:
            record(label + "-state", seconds=round(time.monotonic() - started, 1), **now)
            last = now
        seen.update((slot, what) for slot, v in enumerate(states) for what in ("abandon", "recovery", "save_failed")
                    if v[what])
        if fate["room"] not in (None, "waiting", "aborted") or any(v["abandon"] for v in states):
            raise Reproduced(f"MS-60 reproduced: the refused Enter started a battle that cannot end ({now})")
        if (not fate["active"] and fate["desk"] == "aborted" and holds == [0, 0]
                and all(v["can_save"] and not v["save_failed"] and not v["pending"] for v in states)
                and [v["game_pid"] for v in states] == pids):
            return fate, states, sorted(seen)
        if time.monotonic() - started > timeout:
            if any(holds):
                raise Reproduced(f"MS-60 reproduced: a refused Enter left a game held ({now})")
            raise AssertionError(f"the refused challenge did not end for everybody: {now}")
        await asyncio.sleep(.5)


async def saved_by_its_launcher(current, revision, timeout=180):
    """The friend's launcher saves by itself once its Players menu is closed (launcher_session._start_battle_save)."""
    async def state(s):
        return s.status.code, s.status.revision
    started = time.monotonic()
    async with asyncio.timeout(timeout):
        while True:
            code, now = await on_worker(current[FRIEND], state)
            require(now in (revision - 1, revision), f"the friend's revision jumped to {now}")
            if now == revision:
                return round(time.monotonic() - started, 1)
            await asyncio.sleep(.5)


async def stale_save_match(current, probes, games, host, symbols, record):
    friend = probes[FRIEND]
    revision = 1
    for round_, first in ((1, FRIEND), (2, HOST)):
        # The friend saves in the game only: its save counter moves on, its host save does not.
        launcher_before = await on_worker(current[FRIEND], launcher_state)
        before, after = await save_in_game(friend)
        require(after > before, "the game's own save did not move its save counter on")
        canonical, battler = await on_worker(current[HOST], canonical_of(host, FRIEND))
        launcher_after = await on_worker(current[FRIEND], launcher_state)
        require(canonical["revision"] == revision and launcher_after["revision"] == revision
                and launcher_before["revision"] == revision, "the game's own save changed the host save")
        identity = await live_identity(current[FRIEND])
        record("saved-in-the-game-only", round=round_, save_counter_before=before, save_counter_after=after,
               canonical=canonical, live=None if identity is None else identity.as_request(),
               live_matches_canonical=None if identity is None else identity.matches(battler))
        if identity is not None:
            require(identity.save_counter == after and not identity.matches(battler),
                    "QUERY_PARTY does not tell the game's own save from its host save")

        descriptor = await challenge(current, probes)
        battle_id = descriptor["battle_id"]
        record("challenge-accepted", round=round_, battle_id=battle_id, checkpoints=descriptor.get("checkpoints"))
        if first == FRIEND:
            await friend.choose("Enter battle", wait=False)
            record("friend-chose-enter-battle", round=round_)
        else:
            await probes[HOST].choose("Enter battle", wait=False)
            entered = host.accounts[HOST].player_id
            async with asyncio.timeout(60):
                while entered not in (await on_worker(current[HOST], fate_of(battle_id)))["claimed"]:
                    await asyncio.sleep(.1)
            record("host-entered-first", round=round_, fate=await on_worker(current[HOST], fate_of(battle_id)))
            await friend.choose("Enter battle", wait=False)
            record("friend-chose-enter-battle", round=round_)

        refused = await status_becomes(friend, REFUSED)
        record("friend-refused-at-enter", round=round_, status=refused.status, title=refused.title,
               rows=[r.label for r in refused.rows], save_counter=save_counter(friend))
        if first == FRIEND:
            # The host's screen still offers Enter (a displayed Enter screen is never refreshed underneath it,
            # MenuSession._poll), so the host presses it, as a player would: refused, and the menu says why.
            await probes[HOST].choose("Enter battle", wait=False)
            cancelled = await status_becomes(probes[HOST], CANCELLED)
            record("host-entered-after-and-told-why", round=round_, status=cancelled.status, title=cancelled.title)
        fate, states, seen = await settled(current, probes, games, battle_id, record, f"round-{round_}")
        require(fate["reason"] == ("save_needed" if first == FRIEND else "admission_canceled"),
                f"the challenge ended for another reason: {fate}")
        # Only the host's entry, recorded before the refusal (round 2), was ever held - and cancelled neutrally.
        require(all(slot == HOST and first == HOST for slot, _ in seen), f"a refused Enter held a launcher: {seen}")
        require(await no_result(current, battle_id), "a refused challenge has a battle result")
        require(save_counter(friend) == after, "the friend's game lost its progress")
        record("nobody-held-and-progress-kept", round=round_, fate=fate, launchers=states, shown_on_the_way=seen,
               save_counter=save_counter(friend))

        for probe in probes:
            await close_menu(probe)
        revision += 1
        seconds = await saved_by_its_launcher(current, revision)
        canonical, battler = await on_worker(current[HOST], canonical_of(host, FRIEND))
        identity = await live_identity(current[FRIEND])
        require(canonical["revision"] == revision, "the friend's host save did not move on")
        if identity is not None:
            require(identity.matches(battler), "after its launcher's save the game is still not its host save")
        record("saved-by-its-launcher", round=round_, seconds_after_the_menus_closed=seconds, canonical=canonical,
               live=None if identity is None else identity.as_request())

    # The battle: the refused challenges left nothing behind.
    result = await native_menu_match(current, probes, games, host, symbols, record)
    record("battle-after-the-refusals", result=result)
    return dict(expected=[p.party_now() for p in probes], revisions=[2, revision + 1])


async def run(args):
    await launcher_proof(args, names=("Battle Host", "Battle Friend"), sources=(args.source_a, args.source_b),
                         party_counts=(1, 1), match=stale_save_match, version="Stale save proof",
                         scope=__doc__.split("\n\n")[0])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True, help="native Linux executable, unstripped")
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-a", type=Path, required=True)
    parser.add_argument("--source-b", type=Path, required=True)
    parser.add_argument("--display", action="append", help="an X display per player (twice; Linux)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0)
    parser.add_argument("--wine", type=Path, action="append", help="(not used by this proof)")
    parser.add_argument("--sdl", type=Path)
    parser.add_argument("--elf", type=Path)
    parser.add_argument("--pe-symbols", type=Path, help="Windows: i686-w64-mingw32-nm -n of the game before its strip")
    parser.add_argument("--sizes", type=Path, help="Windows: nm -S of the Linux build of the same engine commit")
    args = parser.parse_args()
    if not args.display:
        require(WINDOWS, "an X display per player")
        args.display = [f"desktop-{n}" for n in range(2)]          # Windows: one desktop; names for the records
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
