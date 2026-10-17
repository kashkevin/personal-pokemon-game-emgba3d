"""Deterministic rival battle formats over the existing native battle modes.

Only formats the engine already runs are used (``battle_desk``):

* two trainers: one 1v1 (mode 2, native singles);
* three trainers: a round robin of three 1v1s (A-B, B-C, C-A). The engine's
  free-for-all needs exactly four trainers and its doubles need four, so a
  three-way battle is not available; every trainer plays each other once and
  plays twice, matches run one at a time (a trainer can hold one battle);
* four trainers: one 2v2 (mode 3, full Multi). Teams are the split of the
  four with the smallest difference in summed strength (each trainer's highest
  party level); ties are broken by a hash of the seed so the same tie does not
  always pair the same trainers.

Seat order and tie breaks come from ``seed`` (the world ID and checkpoint ID),
never from arrival order or the host's dictionary order, so a retry or a
restart plans the identical battles.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

SINGLES, ROUND_ROBIN, MULTI = "singles", "round_robin", "multi"
FORMATS = frozenset({SINGLES, ROUND_ROBIN, MULTI})
MODE_SINGLES, MODE_MULTI = 2, 3


@dataclass(frozen=True)
class PlannedMatch:
    index: int
    mode: int
    teams: tuple[tuple[str, ...], tuple[str, ...]]

    @property
    def players(self) -> tuple[str, ...]:
        return tuple(sorted(self.teams[0] + self.teams[1]))


@dataclass(frozen=True)
class Plan:
    format: str
    players: tuple[str, ...]
    matches: tuple[PlannedMatch, ...]

    def describe(self, names) -> str:
        """At most 32 printable characters for the native status line."""
        def short(player):
            return "".join(c if 32 <= ord(c) <= 126 else "?" for c in names.get(player, "?"))[:6]
        if self.format == SINGLES:
            text = "1v1 rival battle"
        elif self.format == ROUND_ROBIN:
            text = "3 players: three 1v1 battles"
        else:
            a, b = self.matches[0].teams
            text = f"2v2 {short(a[0])}+{short(a[1])} vs {short(b[0])}+{short(b[1])}"
        return text[:32]


def _key(seed, *parts):
    return hashlib.sha256("\0".join((seed,) + tuple(parts)).encode("utf-8")).hexdigest()


def plan(players, strengths, seed):
    """Plan the battles for 2, 3 or 4 distinct trainers; anything else is refused."""
    players = tuple(players)
    if len(set(players)) != len(players) or not 2 <= len(players) <= 4:
        raise ValueError("a rival battle needs two, three or four distinct trainers")
    if type(seed) is not str or not seed:
        raise ValueError("a rival battle plan needs a seed")
    strength = {player: int(strengths.get(player, 0)) for player in players}
    seats = tuple(sorted(players, key=lambda player: (_key(seed, "seat", player), player)))
    if len(seats) == 2:
        teams = tuple(sorted(((seats[0],), (seats[1],))))
        return Plan(SINGLES, seats, (PlannedMatch(0, MODE_SINGLES, teams),))
    if len(seats) == 3:
        pairs = ((seats[0], seats[1]), (seats[1], seats[2]), (seats[2], seats[0]))
        return Plan(ROUND_ROBIN, seats, tuple(
            PlannedMatch(index, MODE_SINGLES, tuple(sorted(((a,), (b,))))) for index, (a, b) in enumerate(pairs)))
    first = seats[0]
    splits = []
    for partner in seats[1:]:
        team = tuple(sorted((first, partner)))
        other = tuple(sorted(p for p in seats if p not in team))
        difference = abs(sum(strength[p] for p in team) - sum(strength[p] for p in other))
        splits.append((difference, _key(seed, "split", *team, *other), tuple(sorted((team, other)))))
    teams = min(splits)[2]
    return Plan(MULTI, seats, (PlannedMatch(0, MODE_MULTI, teams),))


def winners(match, result_players, outcome):
    """Winning team of a released native result, or () for a draw.

    BattleResults outcomes: 1 = the side of the even slots won, 2 = the odd
    slots, 3 = draw (``player_card``). The result's own slot order is used,
    and its sides must be exactly the planned teams.
    """
    result_players = tuple(result_players)
    if len(result_players) == 2:
        sides = ((result_players[0],), (result_players[1],))
    elif len(result_players) == 4:
        sides = (tuple(sorted(result_players[0::2])), tuple(sorted(result_players[1::2])))
    else:
        raise ValueError("rival results have two or four trainers")
    if set(map(tuple, map(sorted, sides))) != set(match.teams):
        raise ValueError("the released battle's sides are not the planned rival teams")
    if outcome == 3:
        return ()
    if outcome not in (1, 2):
        raise ValueError("unknown native battle outcome")
    return tuple(sorted(sides[outcome - 1]))
