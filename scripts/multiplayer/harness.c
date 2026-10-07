/* Project-owned test frontend for pinned libmGBA 0.10.5 with real Lua.
 * Input and framebuffer are emulated. Presence writes come only from the
 * supplied project bridge; no generic RAM-write command exists.
 * This is a development harness, not the Windows player runtime.
 */
#include <mgba/core/core.h>
#include <mgba/core/blip_buf.h>
#include <mgba/core/log.h>
#include <mgba/core/scripting.h>
#include <mgba/script/context.h>
#include <mgba-util/vfs.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void quiet_log(struct mLogger* logger, int category, enum mLogLevel level,
                      const char* format, va_list args) {
    (void) logger; (void) category;
    if (level & (mLOG_FATAL | mLOG_ERROR)) {
        vfprintf(stderr, format, args);
        fputc('\n', stderr);
    }
}
static void script_log(struct mLogger* logger, int category, enum mLogLevel level,
                       const char* format, va_list args) {
    (void) logger; (void) category; (void) level;
    fprintf(stderr, "SCRIPT ");
    vfprintf(stderr, format, args);
    fputc('\n', stderr);
}

int main(int argc, char** argv) {
    if (argc != 4 || !strstr(argv[2], "/multiplayer-proof/")) {
        fprintf(stderr, "Usage: harness ROM /.../multiplayer-proof/.../save.sav verified-bridge.lua\n");
        return 2;
    }
    struct mLogger logger = { .log = quiet_log };
    struct mLogger consoleLogger = { .log = script_log };
    mLogSetDefaultLogger(&logger);
    struct mCore* core = mCoreFind(argv[1]);
    if (!core || !core->init(core)) return 3;
    mCoreInitConfig(core, "multiplayer-proof");
    mCoreConfigSetDefaultValue(&core->config, "idleOptimization", "detect");
    mCoreLoadConfig(core);
    unsigned width, height;
    core->desiredVideoDimensions(core, &width, &height);
    color_t* pixels = calloc(width * height, sizeof(color_t));
    core->setVideoBuffer(core, pixels, width);
    if (!mCoreLoadFile(core, argv[1]) || !mCoreLoadSaveFile(core, argv[2], false)) return 4;
    blip_set_rates(core->getAudioChannel(core, 0), core->frequency(core), 32768);
    blip_set_rates(core->getAudioChannel(core, 1), core->frequency(core), 32768);
    core->reset(core);

    struct mScriptContext script;
    mScriptContextInit(&script);
    mScriptContextAttachStdlib(&script);
    mScriptContextAttachSocket(&script);
    mScriptContextRegisterEngines(&script);
    mScriptContextAttachLogger(&script, &consoleLogger);
    mScriptContextAttachCore(&script, core);
    struct mScriptEngineContext* lua = HashTableLookup(&script.engines, "lua");
    if (!lua || !mScriptContextLoadFile(&script, argv[3]) || !lua->run(lua)) {
        fprintf(stderr, "Lua load failed: %s\n", lua ? lua->getError(lua) : "engine missing");
        return 5;
    }
    mScriptContextTriggerCallback(&script, "start");
    setvbuf(stdout, NULL, _IOLBF, 0);
    printf("READY %u %u LUA\n", width, height);
    char line[1024];
    while (fgets(line, sizeof(line), stdin)) {
        unsigned keys, frames, address, length;
        char path[900];
        if (sscanf(line, "F %x %u", &keys, &frames) == 2) {
            if (frames > 200000) { puts("ERROR frame limit"); continue; }
            core->setKeys(core, keys);
            for (unsigned f = 0; f < frames; ++f) {
                core->runFrame(core);
                mScriptContextTriggerCallback(&script, "frame");
                blip_clear(core->getAudioChannel(core, 0));
                blip_clear(core->getAudioChannel(core, 1));
            }
            printf("FRAME %u\n", core->frameCounter(core));
        } else if (sscanf(line, "P %899s", path) == 1) {
            struct VFile* file = VFileOpen(path, O_WRONLY | O_CREAT | O_TRUNC);
            bool ok = file && mCoreTakeScreenshotVF(core, file);
            if (file) file->close(file);
            printf("PNG %s %s\n", ok ? "OK" : "FAILED", path);
        } else if (sscanf(line, "R %x %u", &address, &length) == 2 && length <= 4096) {
            printf("READ %08x ", address);
            for (unsigned i = 0; i < length; ++i) printf("%02x", core->busRead8(core, address + i));
            fputc('\n', stdout);
        } else if (line[0] == 'Q') {
            break;
        } else {
            puts("ERROR commands: F keymask_hex frames; P png_path; R address_hex bytes; Q");
        }
    }
    mScriptContextTriggerCallback(&script, "shutdown");
    mScriptContextDetachCore(&script);
    mScriptContextDeinit(&script);
    core->unloadROM(core);
    mCoreConfigDeinit(&core->config);
    core->deinit(core);
    free(pixels);
    puts("CLOSED");
    return 0;
}
