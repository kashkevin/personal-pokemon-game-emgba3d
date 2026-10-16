"""Is this saved server reachable, and is it the world the shortcut belongs to?

Used by Join Server before anything is started. It completes the TLS handshake to the address and compares the host's certificate with
the one pinned by the account's invitation - the pinned certificate is tied to the world's stable ID, so a different PC at the same
address, or a different world on the same PC, is refused here rather than being joined. No hello, credential or save data is sent;
this never creates, resets or changes a character because a server is down.
"""
from __future__ import annotations

import asyncio
import errno
import ssl
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .secure_transport import ClientTlsConfig, HostIdentityError

OK = "ok"
UNREACHABLE = "unreachable"
REFUSED = "refused"
TIMEOUT = "timeout"
NOT_THIS_WORLD = "not_this_world"
BLOCKED = "blocked"
NO_NETWORK = "no_network"
STORAGE = "storage"

MESSAGES = {
    OK: "The server answered and it is the right world.",
    UNREACHABLE: "The server could not be reached. Check the address, that the host is running this world, and your network.",
    REFUSED: "Nothing is listening at that address and port. The host may not be running the world, or the port is different.",
    TIMEOUT: "The server did not answer in time. The host may be offline, or a firewall or router is blocking the port.",
    NOT_THIS_WORLD: "Something answered, but it is not this world. Check the address with the host. Nothing was changed.",
    BLOCKED: "This PC's firewall or security software blocked the connection.",
    NO_NETWORK: "This PC has no working route to that address. Check your network connection.",
    STORAGE: "A private working folder could not be used.",
}


@dataclass(frozen=True)
class RouteCheck:
    code: str

    @property
    def ok(self):
        return self.code == OK

    @property
    def message(self):
        return MESSAGES.get(self.code, MESSAGES[UNREACHABLE])


async def probe_route(invitation, host, port, work_directory, *, timeout=5.0):
    """Check ``host:port`` (a numeric address) against ``invitation``'s pinned certificate. Never raises for a network problem."""
    writer = None
    try:
        work = Path(work_directory)
        work.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        return RouteCheck(STORAGE)
    try:
        with tempfile.TemporaryDirectory(prefix="route-check-", dir=work) as directory:
            certificate = Path(directory) / "host-public.pem"
            certificate.write_text(invitation.certificate_pem, encoding="ascii")
            tls = ClientTlsConfig(certificate, invitation.certificate_sha256, handshake_timeout=min(timeout, 5), shutdown_timeout=1)
            context = tls.build_context()
            async with asyncio.timeout(timeout):
                _, writer = await asyncio.open_connection(host, port, ssl=context, server_hostname=host,
                                                          ssl_handshake_timeout=min(timeout, 5), ssl_shutdown_timeout=1)
                tls.verify_peer(writer)
            return RouteCheck(OK)
    except (HostIdentityError, ssl.SSLError):
        return RouteCheck(NOT_THIS_WORLD)
    except TimeoutError:
        return RouteCheck(TIMEOUT)
    except ConnectionRefusedError:
        return RouteCheck(REFUSED)
    except OSError as error:
        number = getattr(error, "winerror", None) or error.errno
        if number in {errno.ENETUNREACH, errno.EHOSTUNREACH, 10051, 10065}:
            return RouteCheck(NO_NETWORK)
        if number in {errno.EACCES, errno.EPERM, 10013}:
            return RouteCheck(BLOCKED)
        return RouteCheck(UNREACHABLE)
    except ValueError:
        return RouteCheck(UNREACHABLE)
    finally:
        if writer is not None:
            writer.close()
            try:
                async with asyncio.timeout(2):
                    await writer.wait_closed()
            except (OSError, TimeoutError):
                pass
