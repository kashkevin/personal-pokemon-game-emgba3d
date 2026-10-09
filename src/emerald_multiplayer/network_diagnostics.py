"""Bounded invitation TLS reachability probe, without player authentication.

This does not claim a separate-device path, configure a router/firewall, send a
player credential or join a world. It only verifies the invited host's TLS leaf.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import errno
import ipaddress
import math
from pathlib import Path
import ssl
import tempfile

from .invitations import Invitation
from .secure_transport import ClientTlsConfig, HostIdentityError
from .server import is_local_address


def route_scope(endpoint):
    address = ipaddress.ip_address(endpoint)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return "loopback" if address.is_loopback else "lan" if is_local_address(str(address), allow_lan=True) else "public"


@dataclass(frozen=True)
class ConnectionDetails:
    """Explicit public fields only; never retain an invitation or credential."""
    endpoint: str
    port: int
    route_scope: str
    build_id: str
    certificate_sha256: str

    @classmethod
    def from_identity(cls, identity):
        return cls(identity.endpoint, identity.port, route_scope(identity.endpoint),
                   identity.build_id, identity.certificate_sha256)

    @property
    def destination(self):
        address = f"[{self.endpoint}]" if ":" in self.endpoint else self.endpoint
        return f"{address}:{self.port}"

    @property
    def guidance(self):
        if self.route_scope == "loopback":
            return "This address works only on the host PC. Friends on another PC need an invitation with a LAN or public address."
        address = ipaddress.ip_address(self.endpoint)
        if address.is_link_local or (getattr(address, "ipv4_mapped", None) and address.ipv4_mapped.is_link_local):
            return "This is a link-local address. Check the host's network connection before sharing invitations."
        if self.route_scope == "lan":
            return "Use this invitation on the host's local network. It does not establish Internet access."
        return "Internet hosting needs the host's configured game port and router forwarding. A connection check alone does not prove outside-network gameplay."

    def copy_text(self):
        # Do not serialize the original invitation, account name/ID, world ID,
        # certificate PEM, credential, or private filesystem locations.
        return ("Emerald Together connection details\n"
                f"Host: {self.destination}\nAddress scope: {self.route_scope}\n"
                f"Game build: {self.build_id}\nHost certificate SHA-256: {self.certificate_sha256}\n"
                "These details do not grant access. Each friend needs their own private invitation file.")


def inspect_invitation(invitation_path, *, expected_build=None):
    invitation = Invitation.load(invitation_path)
    if expected_build is not None and invitation.build_id != expected_build:
        from .invitations import InvitationError
        raise InvitationError("build_mismatch", "invitation requires another game build")
    return ConnectionDetails.from_identity(invitation)


@dataclass(frozen=True)
class NetworkProbe:
    code: str
    route_scope: str
    tls_verified: bool
    player_authenticated: bool = False
    separate_device_proven: bool = False
    internet_path_proven: bool = False
    details: ConnectionDetails | None = None
    failure_reason: str | None = None


async def probe_invitation(invitation_path, private_directory, *, timeout=5, expected_build=None):
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 15:
        raise ValueError("timeout must be between zero and fifteen seconds")
    try:
        invitation = Invitation.load(invitation_path)
    except (OSError, ValueError) as error:
        code = "host_identity_invalid" if getattr(error, "code", None) == "certificate_invalid" else "invalid_invitation"
        return NetworkProbe(code, "unknown", False)
    details = ConnectionDetails.from_identity(invitation)
    scope = details.route_scope
    if expected_build is not None and invitation.build_id != expected_build:
        return NetworkProbe("build_mismatch", scope, False, details=details)
    private = Path(private_directory).resolve()
    try:
        private.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        return NetworkProbe("private_storage", scope, False, details=details)
    writer = None
    stage = "storage"
    try:
        # Only the public certificate enters this temporary directory. The
        # capability/credential remains inside the loaded invitation object.
        with tempfile.TemporaryDirectory(prefix="network-probe-", dir=private) as directory:
            certificate = Path(directory) / "host-public.pem"
            certificate.write_text(invitation.certificate_pem, encoding="ascii")
            tls = ClientTlsConfig(certificate, invitation.certificate_sha256,
                                  handshake_timeout=min(timeout, 5), shutdown_timeout=1)
            context = tls.build_context()
            stage = "connection"
            async with asyncio.timeout(timeout):
                _, writer = await asyncio.open_connection(invitation.endpoint, invitation.port,
                    ssl=context, server_hostname=invitation.endpoint,
                    ssl_handshake_timeout=min(timeout, 5), ssl_shutdown_timeout=1)
                tls.verify_peer(writer)
            # No write(), drain(), hello or authentication request is sent.
            stage = "storage"
            return NetworkProbe("tls_reachable", scope, True, details=details)
    except (HostIdentityError, ssl.SSLError):
        return NetworkProbe("host_identity_invalid", scope, False, details=details)
    except TimeoutError:
        return NetworkProbe("unreachable", scope, False, details=details, failure_reason="connection_timed_out")
    except ConnectionRefusedError:
        return NetworkProbe("unreachable", scope, False, details=details, failure_reason="connection_refused")
    except OSError as error:
        if stage == "storage":
            return NetworkProbe("private_storage", scope, False, details=details)
        number = getattr(error, "winerror", None) or error.errno
        reason = ("network_unavailable" if number in {errno.ENETUNREACH, errno.EHOSTUNREACH, 10051, 10065}
                  else "connection_blocked" if number in {errno.EACCES, errno.EPERM, 10013} else None)
        return NetworkProbe("unreachable", scope, False, details=details, failure_reason=reason)
    except ValueError:
        return NetworkProbe("unreachable", scope, False, details=details)
    finally:
        if writer is not None:
            writer.close()
            try:
                async with asyncio.timeout(2):
                    await writer.wait_closed()
            except (OSError, TimeoutError):
                pass
