"""START > PLAYER > RESET in a world, through the whole launcher: the shiny starter reroll with a friend connected.

Update 32: in a world the reset goes back to the character's save on the host. The game's own RESET opens the
Players menu on its soft reset page; there the player saves on the host, or resets: the launcher closes the game
and starts it again from the host's save in the same session (the world, the host's server and the friend carry
on). Both sources are short-introduction saves (no Pokemon). The proof, through real launcher workers and native
games:

  1. production world creation and host enrollment of both characters; both linked;
  2. both walk to the lab table; the friend claims the Fire ball's starter; the host chooses RESET > "Save on host
     now" (the host's save moves on one revision) and claims the Water ball's starter (its personality from the
     game's log);
  3. RESET > "Reset to last host save" > "Yes, reset now": the launcher starts a new game in the same session; the
     friend's connection never drops; CONTINUE shows the host's save: the lab, no Pokemon, the claim open, the
     host's save unchanged by the reset;
  4. the host claims again: a new roll (another personality), one Pokemon; both save through the launcher;
  5. the friend challenges the host (a challenge needs a Pokemon in both host saves): the host's RESET page says
     "Cancel your challenge first" and offers no reset; the friend cancels;
  then the harness's closing saves and a fresh Continue of both.

    PYTHONPATH=src:scripts/multiplayer:scripts/windows-runtime \\
      python scripts/multiplayer/native_launcher_soft_reset_proof.py \\
        --game ../engine/pokeemerald-mp --rom pokedev.gba --manifest manifest.json \\
        --source host-intro.sav --source friend-intro.sav --display :94 --display :95 \\
        --output /private/multiplayer-proof/soft-reset-1
"""
from __future__ import annotations

import argparse
import asyncio
import re
import time
from pathlib import Path

from native_launcher_battle_proof import (KEYS, PLAYER_OPTIONS, TRAINER_CARD, Player, inspect_closed_head,
                                          launcher_proof, party)
from native_launcher_challenge_proof import shown
from native_launcher_ffa_proof import A, B, DOWN, close_players, players_tab, pose_of
from native_launcher_newcomer_proof import LAB, NewcomerProof
from qualify_admission_cleanup import on_worker, require

PLAYER_NAMES = ("SR Host", "SR Friend")
SOFT_RESET = 22                     # MENU_ACTION_SOFT_RESET (engine src/start_menu.c)
START = 8
CLAIM = re.compile(r"intro: lab starter (\d+) \(species (\d+), shiny (\d), personality ([0-9a-f]{8}), ivs ([\d/]+)\)")


class SoftResetProof(NewcomerProof):
    @staticmethod
    async def to_row(probe, wanted, menu):
        """Down to the START menu row `wanted`, checking the game's own cursor before A (a press while a menu is
        still opening is lost, and A would choose the row above)."""
        row = await probe.snapshot(menu)
        for _ in range(12):
            row = probe.read()
            target = row["actions"][:row["count"]].index(wanted)
            if row["start_cursor"] == target:
                await probe.press(A, release=60)
                return
            await probe.press(DOWN)
        raise AssertionError(f"the START menu cursor did not reach {wanted}: {row['actions'][:row['count']]}")

    async def open_reset_page(self, probe, refused=False):
        """MS-61: the soft reset key, as a player presses it: the Players menu opens on its question ("Reset the game?",
        No first) or, when the reset would cut something open short (refused), on the Soft reset page saying why."""
        await probe.press_reset_key()
        _, screen = await shown(probe)
        title = "Soft reset" if refused else "Reset the game?"
        require(screen.title == title, f"the reset key opened {screen.title!r}: {[r.label for r in screen.rows]}")
        return screen

    @staticmethod
    async def final_choice(probe, label):
        """A choice after which this game closes: the cursor is checked first, and nothing is read after the key."""
        _, screen = await probe.ready()
        target = [r.label for r in screen.rows].index(label)
        for _ in range(len(screen.rows)):
            if probe.read()["cursor"] == target:
                break
            await probe.press(DOWN)
        require(probe.read()["cursor"] == target, f"the cursor did not reach {label!r}")
        await asyncio.to_thread(probe._press, KEYS[A], max(probe.hold, 12 / 60))

    async def log_of(self, worker):
        async def path(s):
            return s._game.log_path
        return Path(await on_worker(worker, path))

    async def rolls(self, worker):
        text = (await self.log_of(worker)).read_text(errors="replace")
        return [dict(choice=int(m.group(1)), species=int(m.group(2)), shiny=int(m.group(3)), personality=m.group(4),
                     ivs=m.group(5)) for m in CLAIM.finditer(text)]

    async def restarted(self, n, current, probes, games, old_pid, record, timeout=240):
        """The launcher's new game of the same session, booted to the field (CONTINUE), as abandon_from does."""
        harness, worker = self.harness, current[n]

        async def new_game(s):
            game = s._game
            return None if game is None or game.process.returncode is not None or game.process.pid == old_pid else (
                game, s.profile_directory / "character.sav", s._companion, s.status.code)
        async with asyncio.timeout(timeout):
            while (found := await on_worker(worker, new_game)) is None:
                await asyncio.sleep(.25)
        game, mirror, companion, code = found
        harness.children.append(game.process)
        probe = await harness.boot_until_field(companion, game.process, n)
        player = Player(n, worker, game, probe, mirror, companion)
        revision = await harness.ready(player)
        harness.players[n] = player
        games[n], probes[n] = game, probe
        record("restarted-in-the-same-session", slot=n, old_pid=old_pid, new_pid=game.process.pid,
               first_code=code, revision=revision)
        return code, revision

    async def _match(self, current, probes, games, host, symbols, record):
        self.t0 = time.monotonic()
        for n, worker in enumerate(current):
            self.own_display(n, worker)
            self.watch_loop(n, worker)
        for index, probe in enumerate(probes):
            status, rows = await players_tab(probe)
            require(status.startswith(f"Connected: {len(probes)}/"), f"player {index}'s PLAYERS: {status} {rows}")

        async def heads(s):
            return [party(inspect_closed_head(s._store, a.player_id)) for a in host.accounts]

        companion = await self.walk_to_lab(0, current, probes, record)
        await self.to_lab_and_claim(1, current, probes, record)     # the friend's starter: a challenge needs two
        friend_before = await self.launcher(current[1])
        # Turn away from the table first (a tap turns): a save facing the ball would let a stray A claim at once.
        await probes[0].press(DOWN, frames=4, release=20)
        revision = (await self.launcher(current[0]))["revision"]
        screen = await self.open_reset_page(probes[0])
        record("reset-page", status=screen.status, rows=[r.label for r in screen.rows])
        require("Reset to last host save" in [r.label for r in screen.rows], f"no reset offered: {screen.status!r}")
        await probes[0].choose("Save on host now", wait=False)
        await self.saved(current[0], revision)
        saved = await self.launcher(current[0])
        canonical = await on_worker(current[0], heads)
        record("saved-on-the-host-from-the-page", revision=saved["revision"], code=saved["code"], canonical=canonical)
        require(canonical[0]["count"] == 0, f"the host's save already holds a Pokemon: {canonical[0]}")

        await self.claim(0, probes[0], companion, record)
        first = await self.rolls(current[0])
        require(len(first) == 1, f"one claim expected in the game's log: {first}")

        old_pid = games[0].process.pid
        screen = await self.open_reset_page(probes[0])
        await probes[0].choose("Reset to last host save")
        _, screen = await shown(probes[0])
        record("reset-question", title=screen.title, status=screen.status, rows=[r.label for r in screen.rows])
        require([r.label for r in screen.rows] == ["No, go back", "Yes, reset now"], f"the question: {screen}")
        await self.final_choice(probes[0], "Yes, reset now")
        code, revision = await self.restarted(0, current, probes, games, old_pid, record)
        friend_after = await self.launcher(current[1])
        canonical = await on_worker(current[0], heads)
        here = pose_of(await self.companion_of(current[0]))
        now = probes[0].party_now()
        record("back-from-the-host-save", code=code, revision=revision, position=list(here[2:]) if here else None,
               party=now, canonical=canonical, friend=[friend_before, friend_after])
        require(revision == saved["revision"], f"the reset changed the host's save: {saved['revision']} -> {revision}")
        require(now["count"] == 0 and here is not None and tuple(here[2:4]) == LAB,
                f"after the reset: party {now}, at {here}; expected the lab with no Pokemon")
        require(friend_after["connected"] and friend_after["epoch"] == friend_before["epoch"],
                f"the friend's connection changed: {friend_before} -> {friend_after}")
        status, _ = await players_tab(probes[1])
        require(status.startswith("Connected: 2/"), f"after the host's reset the friend's PLAYERS says {status}")

        await self.claim(0, probes[0], await self.companion_of(current[0]), record)
        second = await self.rolls(current[0])
        record("rolls", before=first, after=second)
        require(len(second) == 1 and second[0]["personality"] != first[0]["personality"],
                f"the second claim is not a new roll: {first} then {second}")

        for n in (0, 1):
            revision = (await self.launcher(current[n]))["revision"]
            require(current[n].request_save(), f"{self.harness.names[n]}: the launcher refused Save now")
            await self.saved(current[n], revision)
        canonical = await on_worker(current[0], heads)
        record("saved-after-the-reroll", canonical=canonical)
        require(all(c["count"] == 1 and len(c["serials"]) == 1 for c in canonical), f"the host's saves: {canonical}")
        # An open challenge (both host saves hold a Pokemon now): the reset would cut it short, so the
        # page offers none until it is cancelled.
        await probes[1].open_players()
        await probes[1].choose(host.accounts[0].display_name, prefix=True)
        await probes[1].choose("Rival Battle - 1v1")
        await close_players(probes[1])
        screen = await self.open_reset_page(probes[0])
        labels = [r.label for r in screen.rows]
        record("reset-page-with-a-challenge", status=screen.status, rows=labels)
        require(screen.status == "Cancel your challenge first" and "Reset to last host save" not in labels,
                f"with an open challenge the RESET page showed {screen.status!r} {labels}")
        await close_players(probes[0])
        await probes[1].open_players()
        await probes[1].choose("Pending challenge")
        await probes[1].choose("Cancel challenge...")      # it asks first (No first; a quick Yes counts for nothing)
        await asyncio.sleep(0.8)
        await probes[1].choose("Yes, cancel challenge")
        await close_players(probes[1])

        parties = await on_worker(current[0], heads)
        revisions = [(await self.launcher(w))["revision"] + 1 for w in current]
        return dict(parties=parties, revisions=revisions)


async def run(args):
    proof = SoftResetProof(args.watch, args.match_seconds)
    require(len(args.source) == 2 and len(args.display) == 2, "two sources and two displays")
    await launcher_proof(args, names=PLAYER_NAMES, sources=args.source, party_counts=(0, 0), match=proof.match,
                         version="Native soft reset proof", settings="windowScale=2\n", scope=__doc__.split("\n\n")[0],
                         environment=dict(SDL_FRAMEBUFFER_ACCELERATION="0"), on_harness=proof.adopt)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source", type=Path, action="append", required=True, help="two short-introduction saves")
    parser.add_argument("--display", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slow", type=float, default=1.0)
    parser.add_argument("--watch", type=float, default=60)
    parser.add_argument("--match-seconds", type=float, default=900)
    parser.add_argument("--wine", type=Path, action="append", help="(not used)")
    parser.add_argument("--sdl", type=Path)
    parser.add_argument("--elf", type=Path)
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
