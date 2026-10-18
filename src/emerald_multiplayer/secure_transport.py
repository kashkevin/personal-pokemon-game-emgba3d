"""Opt-in TLS with dedicated certificate trust and an exact pinned host identity.

Player credentials and durable world identities remain application-level checks.
This module does not discover certificates, change trust stores, or open listeners.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
import ipaddress
import math
from pathlib import Path
import re
import ssl
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncio

_MAX_PEM_BYTES = 65_536
# 100.64.0.0/10 is the shared address space of carrier-grade NAT (RFC 6598). Overlay VPNs such as Tailscale give each PC an
# address there, so a friend's game must be allowed to *connect* to one; the TLS pin and the credential still decide who the host is.
OVERLAY_NETWORK = ipaddress.ip_network("100.64.0.0/10")
_PRIVATE_NETWORKS = tuple(ipaddress.ip_network(value) for value in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7",
)) + (OVERLAY_NETWORK,)


class HostIdentityError(ConnectionError):
    """The encrypted connection did not present the invited host certificate."""


def is_numeric_unicast_address(value: str) -> bool:
    """Accept a specific numeric Internet/LAN/overlay/loopback endpoint, never a wildcard."""
    if not isinstance(value, str) or "%" in value:
        return False
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    if address.is_loopback:
        return True
    if address.is_unspecified or address.is_multicast or address.is_reserved:
        return False
    return address.is_global or any(
        address.version == network.version and address in network
        for network in _PRIVATE_NETWORKS
    )


def is_overlay_address(value: str) -> bool:
    """An address in 100.64.0.0/10: an overlay VPN (Tailscale and similar) or an Internet provider's CGNAT network."""
    try:
        address = ipaddress.ip_address(value)
    except (ValueError, TypeError):
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.version == 4 and address in OVERLAY_NETWORK


def _duration(value: float, name: str, maximum: float) -> None:
    if (type(value) not in (int, float) or not math.isfinite(value)
            or not 0 < value <= maximum):
        raise ValueError(f"{name} must be finite and between 0 and {maximum} seconds")


def _bounded_file(path: Path, name: str) -> None:
    if not path.is_file() or not 1 <= path.stat().st_size <= _MAX_PEM_BYTES:
        raise ValueError(f"{name} must be a bounded PEM file")


@dataclass(frozen=True)
class ServerTlsConfig:
    certificate_path: Path
    private_key_path: Path = field(repr=False)
    handshake_timeout: float = 5.0
    shutdown_timeout: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "certificate_path", Path(self.certificate_path).resolve())
        object.__setattr__(self, "private_key_path", Path(self.private_key_path).resolve())
        _duration(self.handshake_timeout, "TLS handshake timeout", 30)
        _duration(self.shutdown_timeout, "TLS shutdown timeout", 10)

    def build_context(self) -> ssl.SSLContext:
        _bounded_file(self.certificate_path, "host certificate")
        _bounded_file(self.private_key_path, "host private key")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        # No interactive password prompt, default trust loading, or key logging.
        # Hosts provide a private, unencrypted key; password handling is future UI.
        context.load_cert_chain(self.certificate_path, self.private_key_path,
                                password=lambda: b"")
        return context


@dataclass(frozen=True)
class ClientTlsConfig:
    trusted_certificate_path: Path
    certificate_sha256: str
    handshake_timeout: float = 8.0      # the same budget as connection_diagnostics.DEFAULT_TIMEOUT
    shutdown_timeout: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "trusted_certificate_path", Path(self.trusted_certificate_path).resolve())
        if (not isinstance(self.certificate_sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", self.certificate_sha256) is None):
            raise ValueError("host certificate pin must be a lowercase DER SHA256")
        _duration(self.handshake_timeout, "TLS handshake timeout", 30)
        _duration(self.shutdown_timeout, "TLS shutdown timeout", 10)

    def build_context(self) -> ssl.SSLContext:
        _bounded_file(self.trusted_certificate_path, "trusted host certificate")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        # The exact leaf pin is the host identity, independent of the IP address.
        # Chain/date validation is still mandatory against this dedicated file.
        context.check_hostname = False
        context.verify_mode = ssl.CERT_REQUIRED
        context.verify_flags |= ssl.VERIFY_X509_STRICT
        context.load_verify_locations(cafile=str(self.trusted_certificate_path))
        return context

    def verify_peer(self, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("ssl_object")
        certificate = peer.getpeercert(binary_form=True) if peer is not None else None
        if not certificate or not hmac.compare_digest(
                hashlib.sha256(certificate).hexdigest(), self.certificate_sha256):
            raise HostIdentityError("host TLS certificate does not match its pin")
