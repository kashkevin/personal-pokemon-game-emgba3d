"""The five May/Brendan rival battle checkpoints of Emerald (Update 31).

Data only. Every value was read from pokeemerald-expansion 1.17.1
(``bb1093a7c``, the engine's documented base) and is re-checked against any
engine or upstream checkout by ``scripts/multiplayer/check_rival_catalogue.py``.
Map numbers are the (group, number) pairs that presence messages carry; the
fork's per-group map counts equal upstream's (``flash._MAP_COUNTS``).

``gate`` describes how the ORIGINAL story stops a player at this checkpoint:

* ``trigger_line``: an unavoidable coordinate trigger across the route; the
  original scene starts when it is stepped on. In multiplayer the same tiles
  stop the player (as Route 101's PreventExit triggers do) until the world has
  completed the checkpoint or the player has personally cleared it.
* ``personal_flags``: the original game's own later gate is driven by the
  personal flags this scene sets (Route 103: no Pokedex, so Oldale's west exit
  stays blocked). No extra barrier is needed.
* ``none``: the original rival asks YES/NO and may be declined; there is no
  barrier and the multiplayer checkpoint is optional.
"""
from __future__ import annotations

from dataclasses import dataclass

STARTER_VARIANTS = ("TREECKO", "TORCHIC", "MUDKIP")
GATES = frozenset({"trigger_line", "personal_flags", "none"})


@dataclass(frozen=True)
class Trigger:
    map: str                 # MAP_* constant
    map_id: tuple[int, int]  # presence (map_group, map_number)
    kind: str                # "coord" (step on a tile) or "talk" (talk to the rival object)
    tiles: tuple[tuple[int, int], ...]
    condition: str           # the original script condition that arms it
    script: str              # the original script label


@dataclass(frozen=True)
class RivalCheckpoint:
    checkpoint_id: str
    order: int
    title: str                          # at most 16 printable ASCII characters (native menu)
    mandatory: bool                     # the original story cannot continue past it without the scene
    declinable: bool                    # the original rival asks YES/NO
    gate: str
    triggers: tuple[Trigger, ...]
    trainers: tuple[str, ...]           # the NPC trainer IDs the human rivals replace
    prerequisites: tuple[str, ...]      # original conditions for the scene
    cleared_when: tuple[str, ...]       # personal save condition(s) meaning "already passed" (any one)
    completion_effects: tuple[str, ...]  # what the original scene writes to the save
    personal_rewards: tuple[str, ...]   # items the original scene gives (every player still receives them)
    unlocks: str
    battle_environments: tuple[str, ...]  # every background the original NPC battle can draw (see the checker)
    canonical_environment: str          # the one environment a multiplayer rival battle uses on every core
    sources: tuple[str, ...]            # upstream file:line references

    @property
    def maps(self) -> frozenset[tuple[int, int]]:
        return frozenset(trigger.map_id for trigger in self.triggers)


def _trainers(place):
    return tuple(f"TRAINER_{rival}_{place}_{starter}" for rival in ("BRENDAN", "MAY") for starter in STARTER_VARIANTS)


CHECKPOINTS = (
    RivalCheckpoint(
        checkpoint_id="route103", order=1, title="Route 103", mandatory=True, declinable=False,
        gate="personal_flags",
        triggers=(Trigger("MAP_ROUTE103", (0, 18), "talk", ((10, 3),),
                          "FLAG_HIDE_ROUTE_103_RIVAL clear (object LOCALID_ROUTE103_RIVAL)",
                          "Route103_EventScript_Rival"),),
        trainers=_trainers("ROUTE_103"),
        prerequisites=("VAR_BIRCH_LAB_STATE == 3", "FLAG_DEFEATED_RIVAL_ROUTE103 unset"),
        cleared_when=("FLAG_DEFEATED_RIVAL_ROUTE103 set",),
        completion_effects=("setvar VAR_BIRCH_LAB_STATE, 4",
                            "clearflag FLAG_HIDE_LITTLEROOT_TOWN_BIRCHS_LAB_RIVAL",
                            "setflag FLAG_DEFEATED_RIVAL_ROUTE103",
                            "setvar VAR_OLDALE_RIVAL_STATE, 1",
                            "clearflag FLAG_HIDE_OLDALE_TOWN_RIVAL",
                            "removeobject LOCALID_ROUTE103_RIVAL"),
        personal_rewards=(),
        unlocks="Birch's lab gives the Pokedex and 5 Poke Balls (VAR_BIRCH_LAB_STATE 5, "
                "FLAG_ADVENTURE_STARTED, VAR_OLDALE_TOWN_STATE 1), which opens Oldale Town's west exit to Route 102",
        # Talking from the south or west (the approach from Oldale) draws PLAIN; from the north or east, GRASS.
        battle_environments=("BATTLE_ENVIRONMENT_GRASS", "BATTLE_ENVIRONMENT_PLAIN"),
        canonical_environment="BATTLE_ENVIRONMENT_PLAIN",
        sources=("data/maps/Route103/scripts.inc:20-150", "data/maps/Route103/map.json (LOCALID_ROUTE103_RIVAL 10,3)",
                 "data/maps/LittlerootTown_ProfessorBirchsLab/scripts.inc:515-525",
                 "data/maps/OldaleTown/map.json (trigger 0,10 VAR_OLDALE_TOWN_STATE 0)")),
    RivalCheckpoint(
        checkpoint_id="rustboro", order=2, title="Rustboro City", mandatory=False, declinable=True,
        gate="none",
        triggers=(Trigger("MAP_RUSTBORO_CITY", (0, 3), "coord", tuple((x, 53) for x in range(12, 20)),
                          "VAR_RUSTBORO_CITY_STATE == 7", "RustboroCity_EventScript_RivalTrigger0..7"),
                  Trigger("MAP_ROUTE104", (0, 19), "coord", ((17, 51),),
                          "VAR_ROUTE104_STATE == 1", "Route104_EventScript_RivalTrigger")),
        trainers=_trainers("RUSTBORO"),
        prerequisites=("VAR_RUSTBORO_CITY_STATE == 7 (Rustboro) or VAR_ROUTE104_STATE == 1 (Route 104)",),
        cleared_when=("FLAG_MET_RIVAL_RUSTBORO set", "FLAG_REGISTER_RIVAL_POKENAV set", "VAR_RUSTBORO_CITY_STATE >= 8"),
        completion_effects=("setflag FLAG_MET_RIVAL_RUSTBORO or FLAG_REGISTER_RIVAL_POKENAV",
                            "setflag FLAG_ENABLE_RIVAL_MATCH_CALL",
                            "setvar VAR_RUSTBORO_CITY_STATE, 8", "setvar VAR_ROUTE104_STATE, 2",
                            "setflag FLAG_DEFEATED_RIVAL_RUSTBORO or FLAG_DEFEATED_RIVAL_ROUTE_104 (only after a battle)"),
        personal_rewards=(),
        unlocks="nothing; the rival registers in the PokeNav and the battle may be declined",
        battle_environments=("BATTLE_ENVIRONMENT_PLAIN",), canonical_environment="BATTLE_ENVIRONMENT_PLAIN",
        sources=("data/maps/RustboroCity/scripts.inc:671-955", "data/maps/Route104/scripts.inc:30-245",
                 "data/maps/RustboroCity/map.json (triggers 12..19,53)", "data/maps/Route104/map.json (trigger 17,51)")),
    RivalCheckpoint(
        checkpoint_id="route110", order=3, title="Route 110", mandatory=True, declinable=False,
        gate="trigger_line",
        triggers=(Trigger("MAP_ROUTE110", (0, 25), "coord", ((33, 56), (34, 56), (35, 56)),
                          "VAR_ROUTE110_STATE == 0", "Route110_EventScript_RivalTrigger1..3"),),
        trainers=_trainers("ROUTE_110"),
        prerequisites=("VAR_ROUTE110_STATE == 0",),
        cleared_when=("VAR_ROUTE110_STATE >= 1",),
        completion_effects=("giveitem ITEM_DOWSING_MACHINE", "setvar VAR_ROUTE110_STATE, 1"),
        personal_rewards=("ITEM_DOWSING_MACHINE",),
        unlocks="the path north to Mauville City",
        battle_environments=("BATTLE_ENVIRONMENT_PLAIN",), canonical_environment="BATTLE_ENVIRONMENT_PLAIN",
        sources=("data/maps/Route110/scripts.inc:356-525", "data/maps/Route110/map.json (triggers 33..35,56)")),
    RivalCheckpoint(
        checkpoint_id="route119", order=4, title="Route 119", mandatory=True, declinable=False,
        gate="trigger_line",
        triggers=(Trigger("MAP_ROUTE119", (0, 34), "coord", ((25, 31), (26, 31)),
                          "VAR_ROUTE119_STATE == 0", "Route119_EventScript_RivalTrigger1..2"),),
        trainers=_trainers("ROUTE_119"),
        prerequisites=("VAR_ROUTE119_STATE == 0",),
        cleared_when=("VAR_ROUTE119_STATE >= 1", "FLAG_RECEIVED_HM_FLY set"),
        completion_effects=("giveitem ITEM_HM_FLY", "setflag FLAG_RECEIVED_HM_FLY", "setvar VAR_ROUTE119_STATE, 1",
                            "addvar VAR_SCOTT_STATE, 1 (Scott arrives after the rival leaves)"),
        personal_rewards=("ITEM_HM_FLY",),
        unlocks="the path on to Fortree City, and HM02 Fly",
        battle_environments=("BATTLE_ENVIRONMENT_PLAIN",), canonical_environment="BATTLE_ENVIRONMENT_PLAIN",
        sources=("data/maps/Route119/scripts.inc:29-210", "data/maps/Route119/map.json (triggers 25..26,31)")),
    RivalCheckpoint(
        checkpoint_id="lilycove", order=5, title="Lilycove City", mandatory=False, declinable=True,
        gate="none",
        triggers=(Trigger("MAP_LILYCOVE_CITY", (0, 5), "talk", ((27, 7),),
                          "FLAG_HIDE_LILYCOVE_CITY_RIVAL clear", "LilycoveCity_EventScript_Rival"),),
        trainers=_trainers("LILYCOVE"),
        prerequisites=("FLAG_MET_RIVAL_LILYCOVE unset",),
        cleared_when=("FLAG_MET_RIVAL_LILYCOVE set",),
        completion_effects=("setflag FLAG_MET_RIVAL_LILYCOVE",
                            "clearflag FLAG_HIDE_LITTLEROOT_TOWN_<RIVAL>S_HOUSE_RIVAL_BEDROOM and the doll flag"),
        personal_rewards=(),
        unlocks="nothing; the rival returns home (the battle may be declined)",
        battle_environments=("BATTLE_ENVIRONMENT_PLAIN",), canonical_environment="BATTLE_ENVIRONMENT_PLAIN",
        sources=("data/maps/LilycoveCity/scripts.inc:227-392", "data/maps/LilycoveCity/map.json (rival object 27,7)")),
)

BY_ID = {checkpoint.checkpoint_id: checkpoint for checkpoint in CHECKPOINTS}
IDS = tuple(BY_ID)

# The engine's enum BattleEnvironments index of each canonical environment (include/constants/battle.h;
# check_rival_catalogue.py re-reads it from the engine).
ENVIRONMENT_IDS = {"BATTLE_ENVIRONMENT_PLAIN": 9}

# A rival battle's native preparation carries 'R' 'V', the checkpoint's story number (1..5) and its canonical
# environment in the u32 the co-op battles use for their code (engine include/constants/multiplayer_rival.h
# MP_RIVAL_PREP_WORD). Every core then draws the same background and resolves the environment-dependent moves alike.
PREPARATION_TAG = 0x52560000


def preparation_word(checkpoint_id):
    checkpoint = BY_ID[checkpoint_id]
    return PREPARATION_TAG | (checkpoint.order << 8) | ENVIRONMENT_IDS[checkpoint.canonical_environment]


def valid_preparation_word(word):
    return (type(word) is int and not isinstance(word, bool)
            and any(word == preparation_word(checkpoint_id) for checkpoint_id in IDS))


def checkpoint_at(map_group, map_number):
    """The checkpoint whose scene happens on this map, or None."""
    for checkpoint in CHECKPOINTS:
        if (map_group, map_number) in checkpoint.maps:
            return checkpoint
    return None


def gate_blocks(checkpoint, *, world_completed, personally_cleared):
    """Reference semantics of the multiplayer barrier (the engine port must match).

    Only an armed ``trigger_line`` stops a player, and only while the world has
    not completed the checkpoint and the player has not passed it personally
    (a pre-Update-31 save, a solo pass or a recorded catch-up). Players are
    never stopped going back, never inside buildings and never elsewhere.
    """
    if not isinstance(checkpoint, RivalCheckpoint):
        raise ValueError("unknown rival checkpoint")
    return checkpoint.gate == "trigger_line" and not world_completed and not personally_cleared
