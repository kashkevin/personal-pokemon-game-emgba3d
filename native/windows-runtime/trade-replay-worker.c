/* Project-owned bounded, headless trusted trade replay for pinned libmGBA.
 * One process, one fresh VM, one ROM-declared function. No player save, Lua,
 * network, generic memory command, rendering window or persistent output file.
 * The owning host validates the ROM/runtime pins and exact canonical input.
 */
#include <mgba/flags.h>
#include <mgba/core/core.h>
#include <mgba/core/blip_buf.h>
#include <mgba/core/log.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#include <windows.h>
#endif

#define INPUT_MAX 35116u
#define OUTPUT_MAX 19452u
#define STEP_MAX 64000000u
#define HEAP_SIZE 0x1C500u
#define DESCRIPTOR_MAGIC 0x57525445u
#define ROM_START 0x08000000u
#define EWRAM_START 0x02000000u
#define IWRAM_START 0x03000000u

static uint32_t read32(const uint8_t* p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static void write32(uint8_t* p, uint32_t v) {
    p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24;
}
static int respond(uint32_t status, const uint8_t* output, uint32_t length) {
    uint8_t header[12] = {'E', 'T', 'R', 'S'};
    write32(header + 4, status);
    write32(header + 8, length);
    if (fwrite(header, 1, sizeof(header), stdout) != sizeof(header)
            || (length && fwrite(output, 1, length, stdout) != length) || fflush(stdout)) return 8;
    return status ? 4 : 0;
}
static bool coreFault;
static void quiet_log(struct mLogger* logger, int category, enum mLogLevel level,
                      const char* format, va_list args) {
    (void)logger; (void)category; (void)format; (void)args;
    /* Never leak Pokemon/save contents or host paths from library diagnostics. */
    if (level & mLOG_FATAL) {
        if (!coreFault) fputs("Trade replay core fault.\n", stderr);
        coreFault = true;
    }
}
static bool setreg(struct mCore* core, const char* name, uint32_t value) {
    return core->writeRegister(core, name, &value);
}
static bool shape(const uint8_t* input, uint32_t length, uint32_t* expected) {
    if (length < 32 || read32(input) != 1 || read32(input + 8) > 255
            || read32(input + 12) > 16 || read32(input + 16) > 5 || read32(input + 20) > 5
            || read32(input + 24) || read32(input + 28)) return false;
    uint32_t operation = read32(input + 4), count = read32(input + 12);
    uint32_t base;
    if (operation == 1) {
        if (read32(input + 16) || read32(input + 20)) return false;
        base = 232;
        *expected = 100;
    } else if (operation == 2) {
        base = 35052;
        *expected = OUTPUT_MAX;
    } else return false;
    if (length != base + count * 4) return false;
    for (uint32_t i = 0; i < count; ++i) {
        const uint8_t* choice = input + base + i * 4;
        if (!(choice[0] | choice[1]) || choice[2] > 4 || choice[3]) return false;
    }
    return true;
}

static int run(int argc, char** argv) {
    if (argc == 2 && !strcmp(argv[1], "--version")) {
        puts("emerald-trade-replay-v1 mgba-26b7884");
        return 0;
    }
    if (argc != 3) {
        fputs("Usage: emerald-trade-replay.exe pinned-ROM descriptor-hex < request > response\n", stderr);
        return 2;
    }
#ifdef _WIN32
    if (_setmode(_fileno(stdin), _O_BINARY) == -1 || _setmode(_fileno(stdout), _O_BINARY) == -1) return 2;
#endif
    char* end = NULL;
    errno = 0;
    unsigned long parsed = strtoul(argv[2], &end, 16);
    if (errno || !*argv[2] || *end || parsed < ROM_START || parsed > 0x09FFFFE0u || parsed % 4) return 2;
    uint32_t descriptor = (uint32_t)parsed;
    uint8_t envelope[8], input[INPUT_MAX], output[OUTPUT_MAX];
    if (fread(envelope, 1, sizeof(envelope), stdin) != sizeof(envelope)
            || memcmp(envelope, "ETRQ", 4)) return 2;
    uint32_t length = read32(envelope + 4), expected;
    if (length > INPUT_MAX || fread(input, 1, length, stdin) != length
            || fgetc(stdin) != EOF || ferror(stdin) || !shape(input, length, &expected)) return 2;

    struct mLogger logger = {.log = quiet_log};
    mLogSetDefaultLogger(&logger);
    struct mCore* core = mCoreCreate(mPLATFORM_GBA);
    if (!core) return 3;
    if (!core->init(core)) { free(core); return 3; }
    mCoreInitConfig(core, "emerald-trade-replay");
    /* No mCoreLoadConfig: user settings, cheats, patches and saves are never read. */
    int status = 3;
    unsigned stage = 1;
    color_t* pixels = NULL;
    if (!mCoreLoadFile(core, argv[1])) goto done;
    stage = 2;
    size_t romSize = core->romSize(core);
    if (romSize < 192 || romSize > 32u * 1024u * 1024u
            || descriptor - ROM_START > romSize - 32) goto done;
    uint32_t words[8];
    for (uint32_t i = 0; i < 8; ++i) words[i] = core->busRead32(core, descriptor + i * 4);
    uint32_t entry = words[2], heap = words[3], size = words[4];
    if (words[0] != DESCRIPTOR_MAGIC || words[1] != 1 || !(entry & 1)
            || (entry & ~1u) < ROM_START || (entry & ~1u) - ROM_START > romSize - 2
            || size != HEAP_SIZE || heap % 4 || heap < EWRAM_START
            || heap - EWRAM_START > 0x40000u - size || words[5] != INPUT_MAX
            || words[6] != OUTPUT_MAX || words[7]) goto done;
    stage = 3;
    /* Supply the fixed GBA software buffer before reset. In this pinned
     * GL-capable core, desiredVideoDimensions uses an unset scale until reset
     * chooses the software renderer; querying it beforehand returns 0x0. */
    pixels = calloc(240 * 160, sizeof(color_t));
    if (!pixels) goto done;
    core->setVideoBuffer(core, pixels, 240);
    blip_set_rates(core->getAudioChannel(core, 0), core->frequency(core), 32768);
    blip_set_rates(core->getAudioChannel(core, 1), core->frequency(core), 32768);
    core->reset(core);
    unsigned width, height;
    core->desiredVideoDimensions(core, &width, &height);
    if (width != 240 || height != 160) goto done;
    stage = 4;
    /* Fresh, unbooted memory: no live save pointers, heap headers or party state. */
    for (uint32_t p = 0; p < 0x40000u; p += 4) core->busWrite32(core, EWRAM_START + p, 0);
    for (uint32_t p = 0; p < 0x8000u; p += 4) core->busWrite32(core, IWRAM_START + p, 0);
    core->busWrite16(core, 0x04000200u, 0); /* IE */
    core->busWrite16(core, 0x04000208u, 0); /* IME */
    uint32_t outAddress = heap + ((length + 15u) & ~15u);
    uint32_t sentinel = heap + size - 4;
    if (outAddress + OUTPUT_MAX + 16 > sentinel) goto done;
    for (uint32_t i = 0; i < length; ++i) core->busWrite8(core, heap + i, input[i]);
    core->busWrite16(core, sentinel, 0xE7FEu); /* Thumb b .; never executed on success. */
    core->busWrite16(core, sentinel + 2, 0xE7FEu);
    if (!setreg(core, "cpsr", 0xFFu) || !setreg(core, "sp", 0x03007F00u)
            || !setreg(core, "lr", sentinel | 1u) || !setreg(core, "r0", heap)
            || !setreg(core, "r1", length) || !setreg(core, "r2", outAddress)
            || !setreg(core, "r3", OUTPUT_MAX) || !setreg(core, "pc", entry & ~1u)) goto done;
    stage = 5;
    uint32_t pc = 0, result = 0;
    bool returned = false;
    for (uint32_t steps = 0; steps < STEP_MAX; ++steps) {
        if (coreFault) goto done;
        if (!core->readRegister(core, "pc", &pc)) goto done;
        /* mGBA's Thumb prefetch stores the next instruction at PC = target+2. */
        if (pc == sentinel + 2) { returned = true; break; }
        core->step(core);
        if (!(steps & 4095u)) {
            blip_clear(core->getAudioChannel(core, 0));
            blip_clear(core->getAudioChannel(core, 1));
        }
    }
    if (!returned || !core->readRegister(core, "r0", &result)) goto done;
    if (!result) { status = respond(1, NULL, 0); goto done; }
    if (result != expected) goto done;
    stage = 6;
    /* The input is immutable across replay. Never return a partial buffer. */
    for (uint32_t i = 0; i < length; ++i) if (core->busRead8(core, heap + i) != input[i]) goto done;
    for (uint32_t i = 0; i < result; ++i) output[i] = core->busRead8(core, outAddress + i);
    status = respond(0, output, result);
done:
    if (status == 3) fprintf(stderr, "Trade replay refused at stage %u.\n", stage);
    core->unloadROM(core);
    mCoreConfigDeinit(&core->config);
    core->deinit(core);
    free(pixels);
    return status;
}

#ifdef _WIN32
/* Python starts this process with Unicode argv. The pinned mGBA Windows VFS
 * expects UTF-8, not the active ANSI code page used by a narrow CRT main(). */
int wmain(int argc, wchar_t** argv) {
    if (argc != 2 && argc != 3) return 2;
    char* utf8[3] = {0};
    int status = 2;
    for (int i = 0; i < argc; ++i) {
        int length = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, argv[i], -1,
                                        NULL, 0, NULL, NULL);
        if (length <= 0 || length > 4096) goto done;
        utf8[i] = malloc((size_t)length);
        if (!utf8[i] || !WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, argv[i], -1,
                                           utf8[i], length, NULL, NULL)) goto done;
    }
    status = run(argc, utf8);
done:
    for (int i = 0; i < argc; ++i) free(utf8[i]);
    return status;
}
#else
int main(int argc, char** argv) {
    return run(argc, argv);
}
#endif
