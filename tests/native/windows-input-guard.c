/* Compile against the production inline guard, without SDL, mGBA or game data.
 * gcc -std=c11 -Wall -Wextra -Werror tests/native/windows-input-guard.c -o /tmp/guard
 * Use a new private output path for each retained verification run. */
#include "../../native/windows-runtime/sdl-multiplayer.h"
#include <assert.h>
#include <stdio.h>

static unsigned cases;

static void AllMasks(void) {
    for (uint32_t keys = 0; keys < 1024; keys++) {
        struct mSDLMultiplayerInput state = { 0 };
        uint32_t expected = (keys & 15) == 15 ? keys & ~15u : keys;
        assert(mSDLMultiplayerFilterKeys(&state, keys) == expected);
        assert(state.keys == keys);
        assert(mSDLMultiplayerFilterKeys(&state, keys) == expected);
        assert(mSDLMultiplayerClearKeys(&state, 1023) == 0);
        assert(!state.chordHeld);
        cases++;
    }
}

static void OrderedChords(void) {
    const uint32_t bits[] = { 1, 2, 4, 8 };
    /* Every order of four keydown events crossed with every keyup order,
     * including unrelated held buttons and repeated input while latched. */
    for (unsigned a = 0; a < 4; a++)
    for (unsigned b = 0; b < 4; b++)
    for (unsigned c = 0; c < 4; c++)
    for (unsigned d = 0; d < 4; d++) {
        if (a == b || a == c || a == d || b == c || b == d || c == d) continue;
        const unsigned down[] = { a, b, c, d };
        for (unsigned e = 0; e < 4; e++)
        for (unsigned f = 0; f < 4; f++)
        for (unsigned g = 0; g < 4; g++)
        for (unsigned h = 0; h < 4; h++) {
            if (e == f || e == g || e == h || f == g || f == h || g == h) continue;
            const unsigned up[] = { e, f, g, h };
            for (uint32_t other = 0; other < 1024; other += 16) {
                struct mSDLMultiplayerInput state = { 0 };
                assert(mSDLMultiplayerFilterKeys(&state, other) == other);
                uint32_t raw = other;
                for (unsigned i = 0; i < 4; i++) {
                    raw |= bits[down[i]];
                    assert(mSDLMultiplayerAddKeys(&state, bits[down[i]]) == (i == 3 ? other : raw));
                    assert(state.keys == raw);
                }
                assert(state.chordHeld);
                assert(mSDLMultiplayerAddKeys(&state, 15) == other);
                assert(mSDLMultiplayerFilterKeys(&state, raw) == other);
                for (unsigned i = 0; i < 4; i++) {
                    raw &= ~bits[up[i]];
                    assert(mSDLMultiplayerClearKeys(&state, bits[up[i]]) == other);
                    assert(state.keys == raw);
                    assert(state.chordHeld == (i != 3));
                }
                /* A new ordinary A is available only after complete release. */
                assert(mSDLMultiplayerAddKeys(&state, 1) == (other | 1));
                assert(mSDLMultiplayerClearKeys(&state, 1) == other);
                cases++;
            }
        }
    }
}

static void RepressAndReplace(void) {
    struct mSDLMultiplayerInput state = { 0 };
    assert(mSDLMultiplayerFilterKeys(&state, 15) == 0);
    assert(mSDLMultiplayerClearKeys(&state, 1) == 0);
    assert(mSDLMultiplayerAddKeys(&state, 1) == 0);
    assert(state.keys == 15);
    assert(mSDLMultiplayerClearKeys(&state, 7) == 0);
    assert(mSDLMultiplayerAddKeys(&state, 16) == 16);
    assert(mSDLMultiplayerClearKeys(&state, 8) == 16);
    assert(!state.chordHeld);
    assert(mSDLMultiplayerAddKeys(&state, 8) == 24); /* Ordinary Start. */
    assert(mSDLMultiplayerClearKeys(&state, 8) == 16);
    assert(mSDLMultiplayerFilterKeys(&state, 15) == 0);
    assert(mSDLMultiplayerFilterKeys(&state, 4) == 0); /* No synthetic Select. */
    assert(mSDLMultiplayerFilterKeys(&state, 0) == 0);
    assert(mSDLMultiplayerFilterKeys(&state, 4) == 4); /* Fresh Select. */
    cases++;
}

static void NativeCapabilityGesture(void) {
    struct mSDLMultiplayerInput state = { 0 };
    mSDLMultiplayerEnableNativeChord(&state, true);
    assert(mSDLMultiplayerFilterKeys(&state, 31) == 31);
    assert(state.chordHeld && state.chordRouted);
    assert(mSDLMultiplayerClearKeys(&state, 1) == 16);
    assert(mSDLMultiplayerAddKeys(&state, 1) == 16);
    assert(mSDLMultiplayerClearKeys(&state, 15) == 16);
    assert(mSDLMultiplayerAddKeys(&state, 15) == 31);
    mSDLMultiplayerEnableNativeChord(&state, false);
    assert(mSDLMultiplayerFilterKeys(&state, 31) == 16);
    mSDLMultiplayerEnableNativeChord(&state, true);
    assert(mSDLMultiplayerFilterKeys(&state, 31) == 16);
    assert(mSDLMultiplayerClearKeys(&state, 15) == 16);
    assert(mSDLMultiplayerAddKeys(&state, 15) == 31);
    assert(mSDLMultiplayerClearKeys(&state, 15) == 16);
    mSDLMultiplayerEnableNativeChord(&state, false);
    assert(mSDLMultiplayerAddKeys(&state, 15) == 16);
    mSDLMultiplayerEnableNativeChord(&state, true);
    assert(mSDLMultiplayerFilterKeys(&state, 31) == 16);
    cases++;
}

int main(void) {
    AllMasks();
    OrderedChords();
    RepressAndReplace();
    NativeCapabilityGesture();
    printf("PASS: %u input masks/order cases\n", cases);
    return 0;
}
