"""The host's shared wild spawn director (EmeraldTogether Phase 3).

Fills each shared map instance that has players on it with visible land wild
Pokemon (up to 8, or 12 during an outbreak), walks them around their habitat,
retires the ones nobody is near and replaces caught or defeated ones. It is
pure logic over the generated catalogue (shared_spawn_catalogue.py, built from
the pinned engine by tools/mp/gen_shared_spawns.py), a random source and the
shared world's active clock; the shared world owns it and persists its state.

Species choice ports src/mp_wild_random.c (MPWild_RandomizeSpecies for land
encounters, as the PC game computes it) exactly: the same families, rarity
weights, time-of-day factors, area type boosts, the Phase 2 weather table and
the lower-stage chance; the level comes from the map's own land encounter slots
as it does offline.

Variety (the owner's report of 2026-10-25, "the same 30 pokemon are spawning"):
a family out of its time of day is a third as likely and one in it is as likely
as any other (it used to be three times as likely, so the same few dozen day or
night families filled every route); the time of day and the area's types
together never make a family more than MAX_BOOST times as likely as its rarity
tier; and a new Pokemon avoids the families already on its map and those of the
map's last few spawns (SpawnBoard.recent): the roll is made again up to
REPEAT_TRIES times in all, and the last one is kept whatever it is. The game's
own visible spawns (offline, and while surfing in a world) follow the same rules.

Map instances: the key "group.number" (one instance per map; every player in a
world shares it). Tiles are map coordinates without MAP_OFFSET, as in presence.
"""
from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Callable

from . import legend_rules
from .shared_spawns import (
    DIRECTIONS, KIND_NORMAL, KIND_OUTBREAK, OPEN, STEP, SpawnBoard, SpawnBoards,
)

TIME_ANY, TIME_NOCTURNAL, TIME_DIURNAL = 0, 1, 2
MAX_BOOST = 3      # MP_WILD_MAX_BOOST: time of day and area types together, at most this times the tier's weight
REPEAT_TRIES = 4   # MP_WILD_REPEAT_TRIES: rolls for a family the map does not already show, the last one kept
SHINY_ODDS = 4096  # MP_GEN6_SHINY_ODDS: the approved Gen 6 odds (docs/master-spec.md)

# Phase 2 weather table (src/mp_wild_random.c GetWeatherWeight): weather ->
# (main type, secondary type, heavy rain).
WEATHER_TYPES = {
    "WEATHER_RAIN": ("TYPE_WATER", None, False),
    "WEATHER_DOWNPOUR": ("TYPE_WATER", None, True),
    "WEATHER_RAIN_THUNDERSTORM": ("TYPE_ELECTRIC", "TYPE_WATER", False),
    "WEATHER_SNOW": ("TYPE_ICE", None, False),
    # Sun is WEATHER_DROUGHT only. WEATHER_SUNNY is Emerald's ordinary clear
    # sky, the map weather of most routes, and changes nothing (KNOWN_ISSUES G12).
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
        # Species -> the families it belongs to (a species can be listed in more than one).
        self._family_of: dict[int, set[int]] = {}
        for index, (_tier, _habitat, _time, _types, members) in enumerate(families):
            for species, _min_level, _depth in members:
                self._family_of.setdefault(species, set()).add(index)
        self._tier_weight = catalogue["tier_weights"]
        # Update 29: families found only inside the Safari Zone (never shared, so never picked for a shared spawn)
        self._safari_only = frozenset(catalogue.get("safari_only", ()))
        self._map_weather: dict[str, str | None] = {}

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
    def family_count(self) -> int:
        return len(self._families)

    def family_tier(self, family_index: int) -> str:
        return self._families[family_index][0]

    def stage_at(self, family_index: int, level: int) -> int:
        """The family's most evolved member a wild Pokemon of this level can be
        (no lower-stage roll): a mass outbreak's one species for a whole map."""
        members = self._families[family_index][4]
        depth = max((depth for _, min_level, depth in members if min_level <= level), default=0)
        return next((species for species, min_level, member_depth in members
                     if member_depth == depth and min_level <= level), members[0][0])

    def species_name(self, species: int) -> str:
        for (member_species, _, _), name in zip(self.catalogue["members"], self.catalogue["member_names"]):
            if member_species == species:
                return name.replace("_", " ")
        return "POKEMON"

    def species_weights(self, map_key: str, level: int, night: bool, weather: str | None,
                        tier_weights: dict[str, int] | None = None) -> list[tuple[int, int]]:
        """(family index, weight) for land families, as MPWild_RandomizeSpecies.
        ``tier_weights`` replaces the rarity tiers' base weights (outbreaks)."""
        entry = self.map_entry(map_key) or {}
        boost = set(entry.get("boost", ()))
        habitat = self.catalogue["habitat_land"]
        main, secondary, heavy = (None, None, False)
        if not entry.get("underground") and weather in WEATHER_TYPES:
            main, secondary, heavy = WEATHER_TYPES[weather]
        out = []
        for index, (tier, family_habitat, time, types, _members) in enumerate(self._families):
            if not family_habitat & habitat or index in self._safari_only:
                continue
            weight = (tier_weights or self._tier_weight).get(tier, 0)
            if tier_weights is not None and weight == 0:
                continue  # a rarity tier the outbreak settings leave out
            most = weight * MAX_BOOST
            # Out of its time of day a family is a third as likely; in it, as likely as any other.
            if (time == TIME_NOCTURNAL and not night) or (time == TIME_DIURNAL and night):
                weight //= 3
            if boost & types:
                weight *= 3
            weight = min(weight, most)
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

    def families_of(self, species: int) -> set[int]:
        return self._family_of.get(int(species), set())

    def avoided_families(self, board: SpawnBoard) -> set[int]:
        """The families a new Pokemon on this board should not repeat: those on
        the map now and those of its last few spawns."""
        avoid: set[int] = set()
        for species in [slot.species for slot in board.live()] + list(board.recent):
            avoid |= self.families_of(species)
        return avoid

    def choose_species(self, map_key: str, level: int, night: bool, weather: str | None,
                       outbreak: dict | None = None, avoid: set[int] | frozenset = frozenset()) -> int:
        """A species for a new Pokemon. A family in ``avoid`` is rolled again,
        REPEAT_TRIES rolls in all; the last roll is kept whatever it is."""
        if outbreak is not None and self.rng.random() < outbreak.get("share", 0.0):
            return int(outbreak["species"])
        weights = self.species_weights(map_key, level, night, weather)
        total = sum(weight for _, weight in weights)
        for _ in range(REPEAT_TRIES):
            index = self._roll_family(weights, total)
            if index not in avoid:
                break
        return self.choose_member(index, level)

    def _roll_family(self, weights: list[tuple[int, int]], total: int) -> int:
        roll = self.rng.randrange(total)
        for index, weight in weights:
            if roll < weight:
                return index
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

    # ------------------------------------------------------------ Legendary / Mythical (Update 29)
    def roll_legend_on_claim(self, board: SpawnBoard, spawn_id: int, *, night: bool) -> bool:
        """The random Legendary/Mythical chance of one shared encounter: exactly 1 in 6000, once per Pokemon, made by the
        host when it is first claimed. On a hit the slot becomes a Legendary/Mythical of the map (habitat rules of
        legend_rules.py) at the level and with the shiny status the slot already has. True when the slot changed."""
        slot = board.get(spawn_id)
        if slot is None or slot.legend_rolled or slot.state != OPEN:
            return False
        slot.legend_rolled = True
        if not legend_rules.roll_hits(self.rng):
            return False
        entry = self.map_entry(board.map_key) or {}
        tags = legend_rules.area_tags(entry.get("mapsec", ""), entry.get("map_type", ""),
                                      self._map_weather.get(board.map_key, entry.get("weather")))
        species = legend_rules.pick(self.rng, tags, night)
        if species is None:
            return False
        slot.species = species
        slot.form = 0
        slot.legend = True
        return True

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
            self._map_weather[map_key] = self.weather_for(map_key, players)
            outbreak = outbreaks.get(map_key)
            board.set_outbreak(outbreak is not None)
            if board.trim():  # an outbreak ended: back to 8, claimed ones kept
                changed = True
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
            # During an outbreak most new Pokemon are its species (its share);
            # only those count as outbreak Pokemon. The others keep the map's
            # usual weights, weather included.
            from_outbreak = outbreak is not None and self.rng.random() < outbreak.get("share", 0.0)
            if from_outbreak:
                species, kind = int(outbreak["species"]), KIND_OUTBREAK
                odds = int(outbreak.get("shiny_odds", SHINY_ODDS))
            else:
                species = self.choose_species(map_key, level, night, weather, avoid=self.avoided_families(board))
                kind = KIND_NORMAL
                odds = SHINY_ODDS
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
