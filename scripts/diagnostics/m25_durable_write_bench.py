"""M25 diagnostic: what one native-battle RPC's durable writes cost on this machine.

A host-side RPC does a route-journal append with fsync twice (command, response) and rewrites
the intent file atomically twice (`battle_execution._persist`); the client rewrites its own
execution file twice (`battle_session._persist`). The atomic write below is a copy of
`live_checkpoint._atomic` (temp file, fsync, replace, directory fsync off Windows), so this
script needs no project imports or dependencies. Prints the per-write cost and a per-RPC and
per-step estimate. Diagnostic only; changes nothing.
"""
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path


def sync_directory(path):
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def atomic(path, payload):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".stage")
    try:
        with os.fdopen(fd, "wb") as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        try:
            Path(temporary).unlink()
        except FileNotFoundError:
            pass


def timed(count, action):
    samples = []
    for _ in range(count):
        start = time.perf_counter()
        action()
        samples.append((time.perf_counter() - start) * 1000)
    samples.sort()
    return statistics.mean(samples), samples[len(samples) // 2], samples[int(len(samples) * 0.95)]


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.gettempdir())
    folder = Path(tempfile.mkdtemp(dir=root))
    payload = b'{"x":"' + b"A" * 700 + b'"}\n'
    line = b"B" * 400 + b"\n"
    count = 300
    a_mean, a_med, a_p95 = timed(count, lambda: atomic(folder / "intent.json", payload))
    flags = os.O_RDWR | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0)
    fd = os.open(folder / "journal", flags)

    def append():
        os.write(fd, line)
        os.fsync(fd)

    j_mean, j_med, j_p95 = timed(count, append)
    os.close(fd)
    rpc = 2 * j_mean + 4 * a_mean       # 2 journal appends, 2 host + 2 client atomic writes
    print(f"platform {sys.platform}, folder {root}")
    print(f"atomic write   mean {a_mean:.2f} ms  median {a_med:.2f}  p95 {a_p95:.2f}")
    print(f"journal append mean {j_mean:.2f} ms  median {j_med:.2f}  p95 {j_p95:.2f}")
    print(f"durable cost per RPC ~ {rpc:.1f} ms; three RPC phases per step ~ {3 * rpc:.0f} ms "
          f"(observed in the cloud runs: about 66 ms per RPC in total)")


if __name__ == "__main__":
    main()
