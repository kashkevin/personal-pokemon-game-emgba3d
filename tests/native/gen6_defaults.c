// Copied into the pinned engine's test/ directory for the focused ROM runner.
// These checks exercise selected defaults, not complete Gen6 content coverage.
#include "global.h"
#include "pokemon.h"
#include "move.h"
#include "test/battle.h"

TEST("Gen6 defaults: new level 7 Treecko uses ORAS moves")
{
    struct Pokemon mon;
    CreateRandomMon(&mon, SPECIES_TREECKO, 7);
    EXPECT_EQ(GetMonData(&mon, MON_DATA_MOVE1), MOVE_POUND);
    EXPECT_EQ(GetMonData(&mon, MON_DATA_MOVE2), MOVE_LEER);
    EXPECT_EQ(GetMonData(&mon, MON_DATA_MOVE3), MOVE_ABSORB);
    EXPECT_EQ(GetMonData(&mon, MON_DATA_MOVE4), MOVE_NONE);
}

TEST("Gen6 defaults: standard 721 species level-up moves stay within Gen6")
{
    u32 dex, i;
    for (dex = 1; dex <= NATIONAL_DEX_VOLCANION; dex++)
    {
        enum Species species = NationalPokedexNumToSpecies(dex);
        const struct LevelUpMove *moves = GetSpeciesLevelUpLearnset(species);
        EXPECT(species != SPECIES_NONE);
        for (i = 0; i < 128 && moves[i].move != LEVEL_UP_MOVE_END; i++)
            EXPECT(moves[i].move <= MOVE_HYPERSPACE_FURY);
        EXPECT(i > 0 && i < 128);
    }
}

TEST("Gen6 defaults: friendship species ability and move data")
{
    struct Pokemon mon;
    CreateMon(&mon, SPECIES_PIKACHU, 7, 0, OTID_STRUCT_PLAYER_ID);
    EXPECT_EQ(GetMonData(&mon, MON_DATA_FRIENDSHIP), 70);
    CreateMon(&mon, SPECIES_BUNEARY, 7, 0, OTID_STRUCT_PLAYER_ID);
    EXPECT_EQ(GetMonData(&mon, MON_DATA_FRIENDSHIP), 0);
    EXPECT_EQ(GetSpeciesAbility(SPECIES_GENGAR, 0), ABILITY_LEVITATE);
    EXPECT_EQ(GetMoveAccuracy(MOVE_THUNDER_WAVE), 100);
    EXPECT_EQ(GetSpeciesType(SPECIES_CLEFAIRY, 0), TYPE_FAIRY);
}

SINGLE_BATTLE_TEST("Gen6 defaults: burn takes one eighth each turn")
{
    u32 j;
    GIVEN {
        PLAYER(SPECIES_WOBBUFFET) { Status1(STATUS1_BURN); }
        OPPONENT(SPECIES_WOBBUFFET);
    } WHEN {
        for (j = 0; j < 4; j++)
            TURN {}
    } SCENE {
        s32 maxHP = GetMonData(&PLAYER_PARTY[0], MON_DATA_MAX_HP);
        for (j = 0; j < 4; j++)
            HP_BAR(player, damage: maxHP / 8);
    }
}

SINGLE_BATTLE_TEST("Gen6 defaults: paralysis quarters speed")
{
    u32 playerSpeed;
    bool32 playerFirst;
    PARAMETRIZE { playerSpeed = 196; playerFirst = FALSE; }
    PARAMETRIZE { playerSpeed = 204; playerFirst = TRUE; }
    GIVEN {
        PLAYER(SPECIES_WOBBUFFET) { Status1(STATUS1_PARALYSIS); Speed(playerSpeed); }
        OPPONENT(SPECIES_WOBBUFFET) { Speed(50); }
    } WHEN {
        TURN { MOVE(player, MOVE_CELEBRATE); MOVE(opponent, MOVE_CELEBRATE); }
    } SCENE {
        if (playerFirst) {
            ONE_OF {
                MESSAGE("Wobbuffet used Celebrate!");
                MESSAGE("Wobbuffet couldn't move because it's paralyzed!");
            }
            MESSAGE("The opposing Wobbuffet used Celebrate!");
        } else {
            MESSAGE("The opposing Wobbuffet used Celebrate!");
            ONE_OF {
                MESSAGE("Wobbuffet used Celebrate!");
                MESSAGE("Wobbuffet couldn't move because it's paralyzed!");
            }
        }
    }
}
