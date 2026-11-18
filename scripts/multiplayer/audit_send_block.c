/* KNOWN_ISSUES MS-123 in a real game (the newcomers proof's queue-full scenario): while the file
 * "$AUDIT_SEND_BLOCK.<this pid>" exists, send() reports that the socket would block (EAGAIN), as a full socket to a
 * companion that has stopped reading does on Windows; reads are untouched, so the companion's commands still arrive.
 * Preloaded into every process of the run; without its flag file it only passes each send() on.
 *
 * Built for both word sizes, so ld.so's $LIB picks the one that fits each process (the PC game is 32-bit):
 *   gcc -shared -fPIC -O2 -o DIR/lib/x86_64-linux-gnu/send_block.so audit_send_block.c -ldl
 *   gcc -m32 -shared -fPIC -O2 -o DIR/lib/i386-linux-gnu/send_block.so audit_send_block.c -ldl
 * then: native_launcher_newcomers_proof.py --scenario queue-full --send-block DIR ... */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

static ssize_t (*real_send)(int, const void *, size_t, int);

ssize_t send(int fd, const void *buf, size_t len, int flags)
{
    const char *base = getenv("AUDIT_SEND_BLOCK");
    if (!real_send)
        real_send = (ssize_t (*)(int, const void *, size_t, int))dlsym(RTLD_NEXT, "send");
    if (base != NULL && *base != '\0') {
        char path[600];
        struct stat st;
        snprintf(path, sizeof path, "%s.%d", base, (int)getpid());
        if (stat(path, &st) == 0) {
            errno = EAGAIN;
            return -1;
        }
    }
    return real_send(fd, buf, len, flags);
}
