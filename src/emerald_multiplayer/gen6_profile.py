"""ROM-bound identity for the existing engine's Generation 6 default settings.

This declares selected generation settings, not complete Gen6 content, a new
species/save layout, compatibility migration, or approval of later mechanics.
"""
import struct


GEN6_DEFAULTS_RULESET = "gen6-defaults-rhh1.17.1-mailbox-v1"
FIELDS = frozenset({"generation_profile_version", "generation_profile_address"})
MAGIC = 0x36474445
# These words are emitted from the compiled macros, in this exact order.
SETTINGS = (
    "GEN_LATEST", "P_LVL_UP_LEARNSETS", "P_UPDATED_TYPES", "P_UPDATED_STATS",
    "P_UPDATED_ABILITIES", "P_UPDATED_FRIENDSHIP", "P_EVOLUTION_LEVEL_1_LEARN",
    "P_FRIENDSHIP_EVO_THRESHOLD", "B_UPDATED_MOVE_DATA", "B_UPDATED_ABILITY_DATA",
    "B_UPDATED_TYPE_MATCHUPS", "B_PHYSICAL_SPECIAL_SPLIT", "B_CRIT_MULTIPLIER",
    "B_PARALYSIS_SPEED", "B_CONFUSION_SELF_DMG_CHANCE", "B_BURN_DAMAGE",
    "B_MEGA_EVO_TURN_ORDER", "B_ATE_MULTIPLIER",
)
DESCRIPTOR = struct.pack("<" + "I" * (2 + len(SETTINGS)), MAGIC, 1, *([5] * len(SETTINGS)))


def validate_generation_profile(manifest, rom_path=None):
    declared = bool(FIELDS.intersection(manifest))
    selected = manifest.get("ruleset_id") == GEN6_DEFAULTS_RULESET
    if not declared and not selected:
        return False
    address = manifest.get("generation_profile_address")
    if (not selected or not FIELDS.issubset(manifest)
            or type(manifest.get("generation_profile_version")) is not int
            or manifest["generation_profile_version"] != 1
            or type(address) is not int or address % 4
            or not 0x08000000 <= address <= 0x0A000000 - len(DESCRIPTOR)):
        raise ValueError("generation profile and ruleset are incompatible")
    if rom_path is not None:
        if address - 0x08000000 > rom_path.stat().st_size - len(DESCRIPTOR):
            raise ValueError("generation profile is outside the ROM")
        with rom_path.open("rb") as source:
            source.seek(address - 0x08000000)
            if source.read(len(DESCRIPTOR)) != DESCRIPTOR:
                raise ValueError("compiled generation settings differ from the selected profile")
    return True
