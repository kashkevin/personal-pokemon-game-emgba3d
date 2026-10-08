/* Project-owned integration for the pinned mGBA 0.10.5 SDL frontend. */
#ifndef EMERALD_SDL_MULTIPLAYER_H
#define EMERALD_SDL_MULTIPLAYER_H

#include <mgba-util/common.h>
#include <mgba/feature/commandline.h>
#include <mgba/core/core.h>
#include <mgba/core/thread.h>
#include <SDL.h>

void mSDLMultiplayerParserInit(struct mSubParser* parser);
bool mSDLMultiplayerEnabled(void);
bool mSDLMultiplayerValidate(const struct mArguments* args);
void mSDLMultiplayerConfigure(struct mCore* core);
bool mSDLMultiplayerLoad(struct mCoreThread* thread, struct mLogger* logger);
void mSDLMultiplayerUnload(void);
bool mSDLMultiplayerBlockHotkey(const SDL_Keysym* key);

#endif
