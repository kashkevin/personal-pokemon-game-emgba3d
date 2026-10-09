/* Project-owned player frontend adapter for pinned libmGBA 0.10.5.
 * Uses public core/script/thread/input APIs. It exposes no RAM-write, state,
 * or live-save replacement interface. The launcher owns the save-file lease.
 * This is a development runtime; network lifecycle qualification is separate.
 */
#include "sdl-multiplayer.h"
#include <mgba/feature/commandline.h>
#include <mgba/core/core.h>
#include <mgba/core/thread.h>
#include <mgba/core/scripting.h>
#include <mgba/script/context.h>
#include <mgba/script/macros.h>
#include <mgba-util/socket.h>
#include <SDL.h>
#include <stdio.h>
#include <string.h>

static const char* sScriptPath;
static const char* sSavePath;
static struct mScriptContext sScript;
static bool sScriptInitialized;
static bool sSocketInitialized;
static struct mCore* sCore;
static void (*sSetKeys)(struct mCore*, uint32_t);
static void (*sAddKeys)(struct mCore*, uint32_t);
static void (*sClearKeys)(struct mCore*, uint32_t);
static struct mSDLMultiplayerInput sInput;

static const struct mOption sOptions[] = {
    { "multiplayer-script", true, '\0' },
    { "multiplayer-save", true, '\0' },
    { 0, 0, 0 }
};

static bool ParseLong(struct mSubParser* parser, const char* name, const char* value) {
    (void) parser;
    if (!strcmp(name, "multiplayer-script")) {
        if (sScriptPath || !value || !*value) return false;
        sScriptPath = value;
        return true;
    }
    if (!strcmp(name, "multiplayer-save")) {
        if (sSavePath || !value || !*value) return false;
        sSavePath = value;
        return true;
    }
    return false;
}

void mSDLMultiplayerParserInit(struct mSubParser* parser) {
    memset(parser, 0, sizeof(*parser));
    parser->usage = "Private multiplayer runtime:\n"
        "  --multiplayer-script PATH  Verified launcher bridge (required with save)\n"
        "  --multiplayer-save PATH    Isolated launcher-owned native save";
    parser->extraOptions = "";
    parser->longOptions = sOptions;
    parser->parseLong = ParseLong;
}

bool mSDLMultiplayerEnabled(void) {
    return sScriptPath || sSavePath;
}

bool mSDLMultiplayerValidate(const struct mArguments* args) {
    if (!mSDLMultiplayerEnabled()) return true;
    if (!sScriptPath || !sSavePath || args->cheatsFile || args->savestate || args->patch
            || args->debuggerType != DEBUGGER_NONE) {
        fprintf(stderr, "Multiplayer requires both explicit paths and disables cheats, states, patches and debuggers.\n");
        return false;
    }
    return true;
}

void mSDLMultiplayerConfigure(struct mCore* core) {
    if (!mSDLMultiplayerEnabled()) return;
    core->opts.rewindEnable = false;
    core->opts.rewindBufferCapacity = 0;
}

static void SetKeys(struct mCore* core, uint32_t keys) {
    sSetKeys(core, mSDLMultiplayerFilterKeys(&sInput, keys));
}

static void AddKeys(struct mCore* core, uint32_t keys) {
    sSetKeys(core, mSDLMultiplayerAddKeys(&sInput, keys));
}

static void ClearKeys(struct mCore* core, uint32_t keys) {
    sSetKeys(core, mSDLMultiplayerClearKeys(&sInput, keys));
}

static uint32_t EnableNativeChord(uint32_t abi) {
    /* Only the verified bridge opts in after checking the separate ROM marker.
     * Native ABI1 consumes the gesture even without an eligible encounter or
     * live binding; it never falls through to BIOS soft reset. */
    mSDLMultiplayerEnableNativeChord(&sInput, abi == 1);
    if (sCore) SetKeys(sCore, sInput.keys);
    return 1;
}

mSCRIPT_BIND_FUNCTION(EnableNativeChordBinding, U32, EnableNativeChord, 1, U32, abi);

static void AttachThreadScript(struct mCoreThread* thread) {
    /* mCoreThread explicitly supports adding an already initialized context in
     * startCallback; it registers frame/reset/shutdown callbacks at this point. */
    thread->scriptContext = &sScript;
}

bool mSDLMultiplayerLoad(struct mCoreThread* thread, struct mLogger* logger) {
    if (!mSDLMultiplayerEnabled()) return true;
    struct mCore* core = thread->core;
    if (!mCoreLoadSaveFile(core, sSavePath, false)) {
        fprintf(stderr, "Unable to open the launcher-owned multiplayer save.\n");
        return false;
    }
    mSDLMultiplayerConfigure(core);
    core->reset(core);
    sCore = core;
    sSetKeys = core->setKeys;
    sAddKeys = core->addKeys;
    sClearKeys = core->clearKeys;
    sInput = (struct mSDLMultiplayerInput) { .keys = core->getKeys(core) };
    core->setKeys = SetKeys;
    core->addKeys = AddKeys;
    core->clearKeys = ClearKeys;
    SetKeys(core, sInput.keys);
    /* SDL does not initialize the platform socket subsystem upstream. Qt and
     * the upstream network examples do this before attaching script sockets. */
    SocketSubsystemInit();
    sSocketInitialized = true;
    mScriptContextInit(&sScript);
    sScriptInitialized = true;
    mScriptContextAttachStdlib(&sScript);
    mScriptContextAttachSocket(&sScript);
    mScriptContextRegisterEngines(&sScript);
    mScriptContextAttachLogger(&sScript, logger);
    mScriptContextAttachCore(&sScript, core);
    mScriptContextSetGlobal(&sScript, "emeraldResetInput",
                           mScriptValueAlloc(EnableNativeChordBinding.type));
    struct mScriptEngineContext* lua = HashTableLookup(&sScript.engines, "lua");
    if (!lua || !mScriptContextLoadFile(&sScript, sScriptPath) || !lua->run(lua)) {
        fprintf(stderr, "Multiplayer bridge initialization failed: %s\n",
                lua && lua->getError(lua) ? lua->getError(lua) : "Lua engine or script unavailable");
        mSDLMultiplayerUnload();
        return false;
    }
    thread->startCallback = AttachThreadScript;
    return true;
}

void mSDLMultiplayerUnload(void) {
    if (sScriptInitialized) {
        mScriptContextDetachCore(&sScript);
        mScriptContextDeinit(&sScript);
        sScriptInitialized = false;
    }
    if (sSocketInitialized) {
        SocketSubsystemDeinit();
        sSocketInitialized = false;
    }
    if (sCore) {
        sCore->setKeys = sSetKeys;
        sCore->addKeys = sAddKeys;
        sCore->clearKeys = sClearKeys;
        sInput = (struct mSDLMultiplayerInput) { 0 };
        sCore = NULL;
    }
}

bool mSDLMultiplayerBlockHotkey(const SDL_Keysym* key) {
    if (!mSDLMultiplayerEnabled()) return false;
    /* Frontend shortcuts cannot undo server-owned state. Ordinary pause and
     * fullscreen remain available; reset will be mediated by the launcher. */
    return key->sym == SDLK_BACKQUOTE || (key->sym >= SDLK_F1 && key->sym <= SDLK_F11)
        || (key->sym == SDLK_r && (key->mod & KMOD_CTRL));
}
