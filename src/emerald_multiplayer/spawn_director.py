"""The host's shared wild spawn director (EmeraldTogether Phase 3).

Fills each shared map instance that has players on it with visible land wild
Pokemon (up to 8, or 12 during an outbreak), walks them around their habitat,
retires the ones nobody is near and replaces caught or defeated ones. It is
pure logic over the generated catalogue (shared_spawn_catalogue.py, built from
the pinned engine by tools/mp/gen_shared_spawns.py), a random source and the
shared world's active clock; the shared world owns it and persists its state.

Species choice ports src/mp_wild_random.c (MPWild_RandomizeSpecies for land
encounters) exactly: the same families, rarity weights, time-of-day factors,
area type boosts, the Phase 2 weather table and the lower-stage chance; the
level comes from the map's own land encounter slots as it does offline.

Map instances: the key "group.number" (one instance per map; every player in a
world shares it). Tiles are map coordinates without MAP_OFFSET, as in presence.
"""
from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Callable

from .shared_spawns import (
    DIRECTIONS, KIND_NORMAL, KIND_OUTBREAK, OPEN, STEP, SpawnBoard, SpawnBoards,
)

TIME_ANY, TIME_NOCTURNAL, TIME_DIURNAL = 0, 1, 2
SHINY_ODDS = 4096  # MP_GEN6_SHINY_ODDS: the approved Gen 6 odds (docs/master-spec.md)

# Phase 2 weather table (src/mp_wild_random.c GetWeatherWeight): weather ->
# (main type, secondary type, heavy rain).
WEATHER_TYPES = {
    "WEATHER_RAIN": ("TYPE_WATER", None, False),
    "WEATHER_DOWNPOUR": ("TYPE_WATER", None, True),
    "WEATHER_RAIN_THUNDERSTORM": ("TYPE_ELECTRIC", "TYPE_WATER", False),
    "WEATHER_SNOW": ("TYPE_ICE", None, False),
    "WEATHER_SUNNY": ("TYPE_FIRE", "TYPE_GRASS", False),
    "WEATHER_DROUGHT": ("TYPE_FIRE", "TYPE_GRASS", False),
    "WEATHER_SANDSTORM": ("TYPE_GROUND", "TYPE_ROCK", False),
    "WEATHER_FOG": ("TYPE_GHOST", "TYPE_PSYCHIC", False),
    "WEATHER_FOG_HORIZONTAL": ("TYPE_GHOST", "TYPE_PSYCHIC", False),
    "WEATHER_FOG_DIAGONAL": ("TYPE_GHOST", "TYPE_PSYCHIC", False),
}
WEATHER_PRIMARY_BOOST = 3
WEATHER_SECONDARY_BOOST = 2
WEATHER_HEAVY_RARE_BOOST = 2
RARE_TIERS = frozenset({"RARE", "VERY_RARE"})

# Activities during which a player stands on the map (presence "activity").
PRESENT_ACTIVITIES = frozenset({"overworld", "menu", "battle", "transition"})


@dataclass(frozen=True)
class SpawnTuning:
    """Implementation defaults (not balance rules): how fast slots fill, how
    long they live, how they wander and where they appear."""
    fill_interval: float = 2.5        # active seconds between new spawns on one map
    first_burst: int = 3              # spawns created at once for a newly visited empty map
    lifetime: tuple[float, float] = (180.0, 360.0)
    move_chance: float = 0.35         # per Pokemon per update (about once a second)
    turn_chance: float = 0.15         # idle: turn in place instead
    near_x: int = 7                   # spawn within this many tiles of a player (about one screen)
    near_y: int = 5
    keep_clear: int = 2               # never spawn within this many tiles of a player
    retire_distance: int = 18         # open Pokemon this far from every player ...
    retire_age: float = 45.0          # ... and at least this old are retired
    update_interval: float = 1.0      # active seconds between director updates
    stale_claim_seconds: float = 20.0 # a claimant back on the overworld this long without a result releases


DEFAULT_TUNING = SpawnTuning()


def _decode_tiles(runs: list[list[int]]) -> dict[tuple[int, int], int]:
    tiles = {}
    for y, x0, length, elevation in runs:
        for x in range(x0, x0 + length):
            tiles[(x, y)] = elevation
    return tiles


class SpawnDirector:
    def __init__(self, catalogue: dict, boards: SpawnBoards, *, rng: random.Random | None = None,
                 clock: Callable[[], float], tuning: SpawnTuning = DEFAULT_TUNING):
        if catalogue.get("format") != 1:
            raise ValueError("unsupported shared spawn catalogue")
        self.catalogue = catalogue
        self.boards = boards
        self.rng = rng or random.Random()
        self.clock = clock
        self.tuning = tuning
        self._tiles: dict[str, dict[tuple[int, int], int]] = {}
        self._tile_lists: dict[str, list[tuple[int, int]]] = {}
        self._weather_names = {value: name for name, value in catalogue["weather"].items()}
        self._last_update = float("-inf")
        self._overworld_since: dict[tuple[int, str], float] = {}
        families = []
        for first, count, tier, habitat, time, type1, type2 in catalogue["families"]:
            members = [tuple(m) for m in catalogue["members"][first:first + count]]
            families.append((tier, habitat, time, {type1, type2}, members))
        self._families = families
        self._tier_weight = catalogue["tier_weights"]

    # ------------------------------------------------------------ catalogue
    def map_entry(self, map_key: str) -> dict | None:
        return self.catalogue["maps"].get(map_key)

    def habitat(self, map_key: str) -> dict[tuple[int, int], int]:
        if map_key not in self._tiles:
            entry = self.map_entry(map_key)
            self._tiles[map_key] = _decode_tiles(entry["tiles"]) if entry else {}
            self._tile_lists[map_key] = sorted(self._tiles[map_key])
        return self._tiles[map_key]

    # ------------------------------------------------------------ species
    def species_weights(self, map_key: str, level: int, night: bool, weather: str | None) -> list[tuple[int, int]]:
        """(family index, weight) for land families, as MPWild_RandomizeSpecies."""
        entry = self.map_entry(map_key) or {}
        boost = set(entry.get("boost", ()))
        habitat = self.catalogue["habitat_land"]
        main, secondary, heavy = (None, None, False)
        if not entry.get("underground") and weather in WEATHER_TYPES:
            main, secondary, heavy = WEATHER_TYPES[weather]
        out = []
        for index, (tier, family_habitat, time, types, _members) in enumerate(self._families):
            if not family_habitat & habitat:
                continue
            weight = self._tier_weight[tier]
            if time == TIME_NOCTURNAL:
                weight = weight * 3 if night else weight // 3
            elif time == TIME_DIURNAL:
                weight = weight // 3 if night else weight * 3
            if boost & types:
                weight *= 3
            if weight == 0:
                weight = 1
            if main in types:
                weight *= WEATHER_PRIMARY_BOOST
            if secondary is not None and secondary in types:
                weight *= WEATHER_SECONDARY_BOOST
            if heavy and tier in RARE_TIERS:
                weight *= WEATHER_HEAVY_RARE_BOOST
            out.append((index, weight))
        return out

    def choose_member(self, family_index: int, level: int) -> int:
        members = self._families[family_index][4]
        max_depth = max((depth for _, min_level, depth in members if min_level <= level), default=0)
        target = max_depth
        if max_depth > 0 and self.rng.randrange(100) < self.catalogue["lower_stage_chance"]:
            target = max_depth - 1
        eligible = [species for species, min_level, depth in members if depth == target and min_level <= level]
        if not eligible:
            return members[0][0]
        return self.rng.choice(eligible)

    def choose_species(self, map_key: str, level: int, night: bool, weather: str | None,
                       outbreak: dict | None = None) -> int:
        if outbreak is not None and self.rng.random() < outbreak.get("share", 0.0):
            return int(outbreak["species"])
        weights = self.species_weights(map_key, level, night, weather)
        total = sum(weight for _, weight in weights)
        roll = self.rng.randrange(total)
        for index, weight in weights:
            if roll < weight:
                return self.choose_member(index, level)
            roll -= weight
        raise AssertionError("weighted roll fell outside the table")

    def choose_level(self, map_key: str) -> int:
        entry = self.map_entry(map_key)
        slots = entry["levels"]
        rates = entry["rates"][:len(slots)]
        low, high = self.rng.choices(slots, weights=rates)[0]
        return self.rng.randint(min(low, high), max(low, high))

    # ------------------------------------------------------------ placement
    def choose_tile(self, map_key: str, board: SpawnBoard, players: list[dict]) -> tuple[int, int] | None:
        self.habitat(map_key)
        tiles = self._tile_lists[map_key]
        if not tiles or not players:
            return None
        occupied = board.occupied() | {(p["x"], p["y"]) for p in players}
        t = self.tuning
        anchor = self.rng.choice(players)
        near = [(x, y) for x, y in tiles
                if abs(x - anchor["x"]) <= t.near_x and abs(y - anchor["y"]) <= t.near_y
                and (x, y) not in occupied
                and all(abs(x - p["x"]) + abs(y - p["y"]) > t.keep_clear for p in players)]
        if not near:
            return None
        return self.rng.choice(near)

    # ------------------------------------------------------------ update
    @staticmethod
    def present_players(presences: dict[str, dict]) -> dict[str, list[dict]]:
        """map key -> presences of the players standing on that map."""
        out: dict[str, list[dict]] = {}
        for player_id, presence in sorted(presences.items()):
            if presence is None or presence.get("activity") not in PRESENT_ACTIVITIES:
                continue
            key = f"{presence['map_group']}.{presence['map_number']}"
            out.setdefault(key, []).append({**presence, "player_id": player_id})
        return out

    def weather_for(self, map_key: str, players: list[dict]) -> str | None:
        """The weather the map's first player reports (or the map's default)."""
        for player in players:
            value = player.get("weather")
            if type(value) is int and value in self._weather_names:
                return self._weather_names[value]
        entry = self.map_entry(map_key)
        return entry.get("weather") if entry else None

    def update(self, presences: dict[str, dict], *, night: bool,
               outbreaks: dict[str, dict] | None = None, force: bool = False) -> bool:
        """One director step (about once a second of active time). True when
        anything a client sees changed."""
        now = self.clock()
        if not force and now - self._last_update < self.tuning.update_interval:
            return False
        self._last_update = now
        outbreaks = outbreaks or {}
        changed = False
        for board in self.boards.boards():
            if board.tick():
                changed = True
        if self._release_stale_claims(presences):
            changed = True
        for map_key, players in self.present_players(presences).items():
            if self.map_entry(map_key) is None:
                continue
            board = self.boards.board(map_key)
            outbreak = outbreaks.get(map_key)
            board.set_outbreak(outbreak is not None)
            if self._retire_far(board, players):
                changed = True
            if self._wander(map_key, board, players):
                changed = True
            if self._fill(map_key, board, players, night, outbreak):
                changed = True
        for board in self.boards.boards():
            board.prune()
        return changed

    def _release_stale_claims(self, presences: dict[str, dict]) -> bool:
        """A connected claimant who is plainly not battling the Pokemon any more
        (on another map, or back on the overworld for a while without a result)
        lets it go; a disconnected claimant keeps its grace period instead."""
        now = self.clock()
        changed = False
        seen = set()
        for board in self.boards.boards():
            for slot in board.live():
                if slot.state != "claimed" or slot.claimant not in presences:
                    continue
                presence = presences[slot.claimant]
                key = (slot.spawn_id, slot.claimant)
                seen.add(key)
                if presence is None:
                    continue
                elsewhere = f"{presence['map_group']}.{presence['map_number']}" != board.map_key
                idle = presence.get("activity") == "overworld"
                if elsewhere and presence.get("activity") in ("overworld", "menu"):
                    changed |= board.release(slot.claimant, slot.spawn_id) == "released"
                    self._overworld_since.pop(key, None)
                elif idle:
                    since = self._overworld_since.setdefault(key, now)
                    if now - since >= self.tuning.stale_claim_seconds:
                        changed |= board.release(slot.claimant, slot.spawn_id) == "released"
                        self._overworld_since.pop(key, None)
                else:
                    self._overworld_since.pop(key, None)
        for key in list(self._overworld_since):
            if key not in seen:
                del self._overworld_since[key]
        return changed

    def _fill(self, map_key: str, board: SpawnBoard, players: list[dict], night: bool, outbreak: dict | None) -> bool:
        now = self.clock()
        if board.live_count() >= board.limit():
            return False
        burst = self.tuning.first_burst if board.live_count() == 0 and now - board.last_fill >= 30.0 else 1
        if burst == 1 and now - board.last_fill < self.tuning.fill_interval:
            return False
        created = False
        weather = self.weather_for(map_key, players)
        for _ in range(burst):
            if board.live_count() >= board.limit():
                break
            tile = self.choose_tile(map_key, board, players)
            if tile is None:
                break
            level = self.choose_level(map_key)
            kind = KIND_OUTBREAK if outbreak is not None else KIND_NORMAL
            species = self.choose_species(map_key, level, night, weather, outbreak)
            odds = int(outbreak.get("shiny_odds", SHINY_ODDS)) if outbreak is not None else SHINY_ODDS
            shiny = self.rng.randrange(max(1, odds)) == 0
            spawn_id = board.create(
                species=species, level=level, personality=self.rng.getrandbits(32), shiny=shiny,
                x=tile[0], y=tile[1], lifetime=self.rng.uniform(*self.tuning.lifetime), kind=kind,
                facing=self.rng.choice(DIRECTIONS))
            if spawn_id is None:
                break
            created = True
        if created:
            board.last_fill = now
        return created

    def _retire_far(self, board: SpawnBoard, players: list[dict]) -> bool:
        now = self.clock()
        changed = False
        for slot in board.live():
            if slot.state != OPEN or now - slot.created_at < self.tuning.retire_age:
                continue
            if all(abs(slot.x - p["x"]) + abs(slot.y - p["y"]) > self.tuning.retire_distance for p in players):
                changed |= board.retire(slot.spawn_id, "wandered_off")
        return changed

    def _wander(self, map_key: str, board: SpawnBoard, players: list[dict]) -> bool:
        tiles = self.habitat(map_key)
        player_tiles = {(p["x"], p["y"]) for p in players}
        changed = False
        for slot in board.live():
            if slot.state != OPEN:
                continue
            # A Pokemon next to a player holds still, so the player can talk to it.
            if any(abs(slot.x - x) + abs(slot.y - y) <= 1 for x, y in player_tiles):
                continue
            roll = self.rng.random()
            if roll < self.tuning.move_chance:
                facing = self.rng.choice(DIRECTIONS)
                dx, dy = STEP[facing]
                target = (slot.x + dx, slot.y + dy)
                if (target in tiles and tiles[target] == tiles.get((slot.x, slot.y))
                        and target not in player_tiles and target not in board.occupied()):
                    changed |= board.move(slot.spawn_id, target[0], target[1], facing)
                else:
                    changed |= board.move(slot.spawn_id, slot.x, slot.y, facing)
            elif roll < self.tuning.move_chance + self.tuning.turn_chance:
                changed |= board.move(slot.spawn_id, slot.x, slot.y, self.rng.choice(DIRECTIONS))
        return changed

    # ------------------------------------------------------------ views
    def view(self, player_id: str, presence: dict | None) -> dict | None:
        """The slots of the map this player stands on (None without a pose).

        "shared" is False on a map the catalogue does not cover (no land
        habitat, or a map whose battles follow their own rules, such as the
        Safari Zone): the game then keeps its own encounters there."""
        if presence is None:
            return None
        key = f"{presence['map_group']}.{presence['map_number']}"
        shared = self.map_entry(key) is not None
        board = self.boards.existing(key) if shared else None
        slots = board.snapshot(player_id) if board is not None else []
        return {"map_group": presence["map_group"], "map_number": presence["map_number"], "shared": shared,
                "slots": slots}
