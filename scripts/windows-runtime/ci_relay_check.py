"""The relay server of an INSTALLED EmeraldTogether: ``EmeraldTogether.exe --relay-server`` (KNOWN_ISSUES NU-10; Windows
runner, CI only, or its Linux rehearsal).

    python ci_relay_check.py --setup EmeraldTogether-Setup-X.exe --work <new folder> [--label relay]
    python ci_relay_check.py --linux --work <new folder>          (the same entry, relay.frozen_main, from src/)

A player who cannot be reached from the Internet hosts through a relay someone they trust runs with the packaged program
(HOSTING.txt). Its entry had been checked only by unit tests (frozen_main with run_cli stubbed): this runs it as installed.

  1. installs the Setup file silently (as ci_world_check.install) and starts the installed EmeraldTogether.exe
     --relay-server --host 127.0.0.1 --port <free port>: a windowed program, so it opens its own console (relay._console);
  2. waits for the port to accept connections (the process must still be running);
  3. a world's host side (relay.RelayHostAgent, the launcher's own) registers a room with its key and reaches "relay_ready";
     its target is an echo server here, standing in for the world server's relayed-connection listener;
  4. three friends join through it at once (relay.open_relay_connection, the companion's own) and each sends 64 KiB of
     random bytes and reads them back unchanged; the host side counts the friends it pipes;
  5. one friend sends and reads back 4 MiB (the time is reported);
  6. a second host with a different key for the same room is refused (relay_room_taken), and a friend for a room nobody
     holds is refused (relay_host_offline);
  7. the relay process is ended and must end; the program is uninstalled.

Writes <work>/<label>-relay-check.json and prints each step.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "src"), str(HERE)]

from emerald_multiplayer.relay import RelayError, RelayHostAgent, open_relay_connection  # noqa: E402


class CheckFailed(AssertionError):
    pass


def require(condition, message):
    if not condition:
        raise CheckFailed(message)


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def listening(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


async def wait_for(condition, seconds, step=0.1):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        await asyncio.sleep(step)
    return bool(condition())


async def echo_server():
    """The world server's stand-in: every connection gets its bytes back."""
    async def handle(reader, writer):
        try:
            while data := await reader.read(65536):
                writer.write(data)
                await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            writer.close()
    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def round_trip(port, room, size):
    """A friend through the relay: ``size`` random bytes out and the same bytes back. Returns the seconds it took."""
    reader, writer = await open_relay_connection("127.0.0.1", port, room)
    try:
        payload = secrets.token_bytes(size)
        began = time.monotonic()

        async def send():
            for start in range(0, size, 65536):
                writer.write(payload[start:start + 65536])
                await writer.drain()
        sender = asyncio.create_task(send())
        received = bytearray()
        async with asyncio.timeout(60):
            while len(received) < size:
                chunk = await reader.read(65536)
                require(chunk, f"the relay closed a friend's connection after {len(received)} of {size} bytes")
                received += chunk
        await sender
        require(bytes(received) == payload, "the bytes a friend got back through the relay are not the bytes it sent")
        return round(time.monotonic() - began, 3)
    finally:
        writer.close()


async def exercise(port, report, log):
    room, secret = str(uuid.uuid4()), secrets.token_bytes(32)
    echo, echo_port = await echo_server()
    statuses = []
    agent = RelayHostAgent("127.0.0.1", port, room, secret, lambda: ("127.0.0.1", echo_port),
                           on_status=lambda status: statuses.append((status.code, status.friends)))
    await agent.start()
    try:
        ready = await wait_for(lambda: agent.status.ready, 20)
        require(ready, f"the host side did not reach relay_ready: {agent.status.code} ({agent.status.message})")
        log(f"host side: {agent.status.code} on {agent.status.relay} ({agent.status.message})")

        # three friends at once
        times = await asyncio.gather(*(round_trip(port, room, 65536) for _ in range(3)))
        most = max((friends for _, friends in statuses), default=0)
        log(f"three friends at once: 64 KiB each there and back in {times} s; the host side piped up to {most} at a time")
        require(most >= 1, f"the host side never counted a friend: {statuses}")
        report["friends"] = dict(seconds=times, most_at_once=most)

        big = await round_trip(port, room, 4 * 1024 * 1024)
        log(f"one friend: 4 MiB there and back in {big} s")
        report["four_mib_seconds"] = big

        # a different key for the same room is refused; a room nobody holds is told so
        thief = RelayHostAgent("127.0.0.1", port, room, secrets.token_bytes(32), lambda: ("127.0.0.1", echo_port))
        await thief.start()
        try:
            refused = await wait_for(lambda: thief.status.code == "relay_room_taken", 20)
            require(refused, f"a second host with another key was not refused: {thief.status.code}")
            log(f"another key for the same room: {thief.status.code} ({thief.status.message})")
        finally:
            await thief.close()
        try:
            await open_relay_connection("127.0.0.1", port, str(uuid.uuid4()))
            raise CheckFailed("a friend for a room nobody holds was connected")
        except RelayError as error:
            log(f"a room nobody holds: refused ({error.code})")
            report["unknown_room"] = error.code
        require(agent.status.ready, f"the room's own host lost its place: {agent.status.code}")
        report["host_status"] = agent.status.code
    finally:
        await agent.close()
        echo.close()
        await echo.wait_closed()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--setup", type=Path)
    parser.add_argument("--linux", action="store_true", help="the entry from src/ (relay.frozen_main), no install")
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--label", default="relay")
    args = parser.parse_args()
    work = args.work.resolve()
    require(not work.exists() or not any(work.iterdir()), "choose a new, empty --work folder")
    work.mkdir(parents=True, exist_ok=True)
    report = dict(format="emerald-relay-check-v1", label=args.label, platform="linux rehearsal" if args.linux else "windows",
                  setup=args.setup.name if args.setup else None)
    lines = []

    def log(text):
        print(text, flush=True)
        lines.append(text)

    target = work / f"{args.label}-EmeraldTogether"
    process = output = None
    try:
        port = free_port()
        if args.linux:
            command = [sys.executable, "-c", "import sys; from emerald_multiplayer.relay import frozen_main; "
                       "sys.exit(frozen_main(sys.argv[1:]))"]
            env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
        else:
            require(os.name == "nt" and args.setup is not None, "this check runs on Windows with --setup (or use --linux)")
            import ci_world_check as w
            env = dict(os.environ, LOCALAPPDATA=str(work / "profile"))
            w.install(args.setup.resolve(), target, env, work, args.label)
            command = [str(target / "EmeraldTogether.exe")]
            log(f"windows: installed {args.setup.name} into {target}")
        command += ["--relay-server", "--host", "127.0.0.1", "--port", str(port)]
        output = open(work / f"{args.label}-relay-output.txt", "w")
        began = time.monotonic()
        process = subprocess.Popen(command, env=env, cwd=work, stdout=output, stderr=subprocess.STDOUT)
        up = False
        while time.monotonic() - began < 30 and process.poll() is None:
            if listening(port):
                up = True
                break
            time.sleep(0.2)
        require(process.poll() is None, f"the relay ended at once (exit code {process.poll()})")
        require(up, f"the relay did not listen on 127.0.0.1:{port} within 30 s")
        report["listening_after_seconds"] = round(time.monotonic() - began, 2)
        log(f"{' '.join(Path(command[0]).name if i == 0 else part for i, part in enumerate(command))}: listening on "
            f"127.0.0.1:{port} after {report['listening_after_seconds']} s (pid {process.pid})")
        asyncio.run(exercise(port, report, log))
        require(process.poll() is None, f"the relay ended during the check (exit code {process.poll()})")
        process.terminate()
        try:
            code = process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            raise CheckFailed("the relay did not end within 15 s of being ended")
        log(f"the relay ended when ended (exit code {code})")
        report["result"] = "passed"
    except CheckFailed as error:
        report["result"] = "failed: " + str(error)
        print("check failed: " + str(error), flush=True)
        lines.append("check failed: " + str(error))
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=15)
        if output is not None:
            output.close()
        report["log"] = lines
        (work / f"{args.label}-relay-check.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if not args.linux and target.exists():
            import ci_world_check as w
            w.uninstall(target, work, args.label)
    if report["result"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
