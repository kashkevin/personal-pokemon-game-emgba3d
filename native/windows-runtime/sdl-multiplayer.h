/* Project-owned integration for the pinned mGBA 0.10.5 SDL frontend. */
#ifndef EMERALD_SDL_MULTIPLAYER_H
#define EMERALD_SDL_MULTIPLAYER_H

#include <stdbool.h>
#include <stdint.h>

struct mSubParser;
struct mArguments;
struct mCore;
struct mCoreThread;
struct mLogger;
typedef struct SDL_Keysym SDL_Keysym;

/* Keep physical/script input separate from the filtered core state. Once a
 * reboot chord is detected, releasing one button must not expose held A/B or
 * Start as a new ordinary action. Require release of all four before rearming.
 * A verified native input capability may handle the complete gesture itself;
 * unsupported builds never see it. Never translate it into Select. */
struct mSDLMultiplayerInput {
    uint32_t keys;
    bool chordHeld;
    bool nativeChordEnabled;
    bool chordRouted;
};

static inline uint32_t mSDLMultiplayerFilterKeys(struct mSDLMultiplayerInput* input, uint32_t keys) {
    const uint32_t chord = 15u; /* GBA A | B | Select | Start */
    input->keys = keys;
    if ((keys & chord) == chord && !input->chordHeld) {
        input->chordHeld = true;
        input->chordRouted = input->nativeChordEnabled;
    }
    /* The native frame may never have observed a very brief complete chord.
     * Do not expose its partial release as ordinary A/B/Select/Start, or let
     * re-pressing one still-held gesture become a second native request. */
    if (input->chordHeld && (keys & chord) != chord) input->chordRouted = false;
    if (!(keys & chord)) input->chordHeld = input->chordRouted = false;
    return input->chordHeld && !input->chordRouted ? keys & ~chord : keys;
}

static inline void mSDLMultiplayerEnableNativeChord(struct mSDLMultiplayerInput* input, bool enabled) {
    input->nativeChordEnabled = enabled;
    /* Revocation consumes the remainder. Enabling never revives a gesture
     * that began without capability/connection or was revoked midway. */
    if (!enabled) input->chordRouted = false;
}

static inline uint32_t mSDLMultiplayerAddKeys(struct mSDLMultiplayerInput* input, uint32_t keys) {
    return mSDLMultiplayerFilterKeys(input, input->keys | keys);
}

static inline uint32_t mSDLMultiplayerClearKeys(struct mSDLMultiplayerInput* input, uint32_t keys) {
    return mSDLMultiplayerFilterKeys(input, input->keys & ~keys);
}

void mSDLMultiplayerParserInit(struct mSubParser* parser);
bool mSDLMultiplayerEnabled(void);
bool mSDLMultiplayerValidate(const struct mArguments* args);
void mSDLMultiplayerConfigure(struct mCore* core);
bool mSDLMultiplayerLoad(struct mCoreThread* thread, struct mLogger* logger);
void mSDLMultiplayerUnload(void);
bool mSDLMultiplayerBlockHotkey(const SDL_Keysym* key);

#endif
