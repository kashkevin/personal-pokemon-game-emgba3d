"""A TCP proxy between a friend's launcher and the host (KNOWN_ISSUES MS-124's real-run check): every connection to
--listen is forwarded to 127.0.0.1:--target, both ways, through sockets with small kernel buffers (--buffer bytes, set
before listen and before connect), so that when this process is stopped (SIGSTOP, as a link whose TCP is retransmitting
holds everything) the writers on both sides soon find nothing more fits. Prints "listening PORT" once it accepts; logs
each connection and its byte counts to stderr.

    python audit_tcp_proxy.py --target 40123 --buffer 4096
"""
from __future__ import annotations

import argparse
import asyncio
import socket
import sys
import time


def small(sock, size):
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, size)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, size)


async def pipe(reader, writer, counts, key):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            counts[key] += len(data)
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        try:
            writer.close()
        except Exception:  # noqa: BLE001
            pass


async def main(args):
    loop = asyncio.get_running_loop()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    small(listener, args.buffer)
    listener.bind(("127.0.0.1", args.listen))
    listener.listen(16)
    listener.setblocking(False)
    number = [0]

    async def handle(client_reader, client_writer):
        number[0] += 1
        n = number[0]
        upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        small(upstream, args.buffer)
        upstream.setblocking(False)
        await loop.sock_connect(upstream, ("127.0.0.1", args.target))
        up_reader, up_writer = await asyncio.open_connection(sock=upstream)
        counts = {"to_host": 0, "to_friend": 0}
        print(f"{time.strftime('%H:%M:%S')} connection {n} from {client_writer.get_extra_info('peername')} "
              f"buffers {client_writer.get_extra_info('socket').getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)}",
              file=sys.stderr, flush=True)
        await asyncio.gather(pipe(client_reader, up_writer, counts, "to_host"),
                             pipe(up_reader, client_writer, counts, "to_friend"))
        print(f"{time.strftime('%H:%M:%S')} connection {n} closed {counts}", file=sys.stderr, flush=True)

    server = await asyncio.start_server(handle, sock=listener)
    print(f"listening {listener.getsockname()[1]}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", type=int, required=True)
    parser.add_argument("--listen", type=int, default=0)
    parser.add_argument("--buffer", type=int, default=4096)
    asyncio.run(main(parser.parse_args()))
