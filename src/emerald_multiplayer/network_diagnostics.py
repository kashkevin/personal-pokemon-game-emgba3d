"""Bounded invitation TLS reachability probe, without player authentication.

This does not claim a separate-device path, configure a router/firewall, send a
player credential or join a world. It only verifies the invited host's TLS leaf.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import ipaddress
import math
from pathlib import Path
import ssl
import tempfile

from .invitations import Invitation
from .secure_transport import ClientTlsConfig, HostIdentityError
from .server import is_local_address


@dataclass(frozen=True)
class NetworkProbe:
    code: str
    route_scope: str
    tls_verified: bool
    player_authenticated: bool = False
    separate_device_proven: bool = False
    internet_path_proven: bool = False


async def probe_invitation(invitation_path, private_directory, *, timeout=5):
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 15:
        raise ValueError("timeout must be between zero and fifteen seconds")
    try:
        invitation = Invitation.load(invitation_path)
    except (OSError, ValueError):
        return NetworkProbe("invalid_invitation", "unknown", False)
    address = ipaddress.ip_address(invitation.endpoint)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    scope = "loopback" if address.is_loopback else "lan" if is_local_address(invitation.endpoint, allow_lan=True) else "public"
    private = Path(private_directory).resolve()
    private.mkdir(parents=True, exist_ok=True, mode=0o700)
    writer = None
    try:
        # Only the public certificate enters this temporary directory. The
        # capability/credential remains inside the loaded invitation object.
        with tempfile.TemporaryDirectory(prefix="network-probe-", dir=private) as directory:
            certificate = Path(directory) / "host-public.pem"
            certificate.write_text(invitation.certificate_pem, encoding="ascii")
            tls = ClientTlsConfig(certificate, invitation.certificate_sha256,
                                  handshake_timeout=min(timeout, 5), shutdown_timeout=1)
            async with asyncio.timeout(timeout):
                _, writer = await asyncio.open_connection(invitation.endpoint, invitation.port,
                    ssl=tls.build_context(), server_hostname=invitation.endpoint,
                    ssl_handshake_timeout=min(timeout, 5), ssl_shutdown_timeout=1)
                tls.verify_peer(writer)
            # No write(), drain(), hello or authentication request is sent.
            return NetworkProbe("tls_reachable", scope, True)
    except (HostIdentityError, ssl.SSLError):
        return NetworkProbe("host_identity_invalid", scope, False)
    except (OSError, TimeoutError, ValueError):
        return NetworkProbe("unreachable", scope, False)
    finally:
        if writer is not None:
            writer.close()
            try:
                async with asyncio.timeout(2):
                    await writer.wait_closed()
            except (OSError, TimeoutError):
                pass
