"""Invite codes: a friend's world account as one short piece of text.

An invite code is the private invitation (``invitations.py``) without the host's certificate, which the friend's game fetches from
the server on the first connection and accepts only if its SHA-256 equals the pin written in the code. So the code carries what the
host's private channel has to carry: the world and account identities, the account's sign-in credential, the host certificate pin,
the game build, and where to connect (an address the host chose, a numeric address or a host name, and the port). It is about 270
characters, so it can be pasted from a chat message, and it ends in a checksum that catches a mistyped character.

Version 1 codes carry only that. A version 2 code also names a relay (``relay.py``: an address and port a friend can use when the
host cannot be reached directly); it is written only when the host set up a relay, so codes without one stay version 1 and older
games keep reading them. The relay changes only where the friend's game knocks: the TLS pin and the credential are checked end to
end exactly as on a direct connection.

**A code is a credential.** Whoever holds it can sign in as that account, exactly as with an invitation file; give each friend their
own and send it only to them. A code does not contain the host's certificate or private key and cannot be used to open or hack the
world without the credential. Nothing here opens a connection to the network except ``fetch_certificate``, which sends no data: it
only completes the TLS handshake to read the certificate and drops the connection.
"""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
import hashlib
import ipaddress
import re
import socket
import ssl
import struct
import zlib

from .companion import BASELINE_RULESET
from .gen6_profile import GEN6_DEFAULTS_RULESET
from .invitations import INVITATION_FORMAT, Invitation, InvitationError, _certificate
from .ownership import OWNERSHIP_PROFILE
from .secure_transport import is_numeric_unicast_address

PREFIX = "ET1-"
VERSION = 2                 # the newest version this game reads and writes (1: direct only; 2: optional relay endpoint)
_FLAG_RELAY = 0x01
RULESETS = (BASELINE_RULESET, GEN6_DEFAULTS_RULESET)
MAX_CODE_TEXT = 1024
_HOST_NAME = re.compile(r"(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*")


class InviteCodeError(ValueError):
    """``code`` is the stable invite code error; ``reason`` (a connection_diagnostics code) says why a server could not be
    checked, when that is known."""

    def __init__(self, code, message, reason=None):
        self.code = code
        self.reason = reason
        super().__init__(message)


MESSAGES = {
    "invite_malformed": "That invite code is not complete or has a mistyped character. Copy it again from the host.",
    "invite_version": "That invite code was made by a newer version of EmeraldTogether. Update the game to use it.",
    "invite_version_old": "That invite code was made by an older version of EmeraldTogether that this one cannot read. Ask the host "
                          "for a new code.",
    "invite_build": "That invite is for a different game version than the one installed here.",
    "invite_address": "The server address in the invite is not usable.",
    "certificate_mismatch": "The server at that address is not the world this invite belongs to.",
    "certificate_unavailable": "The server could not be reached to check it. Check the address and that the host is running.",
}


def valid_address(value):
    """A numeric address a friend can reach, or a host name. Never a wildcard or a name with odd characters."""
    if type(value) is not str or not value or len(value) > 253 or value != value.strip():
        return False
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return _HOST_NAME.fullmatch(value) is not None and not value.replace(".", "").isdigit()
    return "%" not in value and is_numeric_unicast_address(str(address)) and str(address) == value


def valid_port(value):
    return type(value) is int and 1 <= value <= 65535


@dataclass(frozen=True)
class InviteCode:
    slot: int
    world_id: str
    player_id: str
    display_name: str
    credential: bytes = field(repr=False)
    build_id: str
    ruleset_id: str
    certificate_sha256: str
    address: str
    port: int
    relay: tuple | None = None      # (address, port) of a relay, or None for a direct-only code

    def __post_init__(self):
        from .shell_store import is_uuid
        if (type(self.slot) is not int or not 1 <= self.slot <= 3 or not is_uuid(self.world_id) or not is_uuid(self.player_id)
                or type(self.credential) is not bytes or len(self.credential) != 32
                or not re.fullmatch("[0-9a-f]{64}", self.build_id or "") or not re.fullmatch("[0-9a-f]{64}", self.certificate_sha256 or "")
                or self.ruleset_id not in RULESETS or type(self.display_name) is not str
                or not 1 <= len(self.display_name) <= 24 or not self.display_name.isprintable()):
            raise InviteCodeError("invite_malformed", MESSAGES["invite_malformed"])
        if not valid_address(self.address) or not valid_port(self.port):
            raise InviteCodeError("invite_address", MESSAGES["invite_address"])
        if self.relay is not None and (type(self.relay) is not tuple or len(self.relay) != 2 or not valid_address(self.relay[0])
                                       or not valid_port(self.relay[1])):
            raise InviteCodeError("invite_address", MESSAGES["invite_address"])


def encode_invite(invitation, address=None, port=None, *, relay=None):
    """The code for a friend invitation. ``address``/``port`` override where the invitation points (the host's chosen address);
    ``relay`` = (address, port) adds the world's relay (a version 2 code)."""
    if not isinstance(invitation, Invitation) or invitation.role != "friend":
        raise InviteCodeError("invite_malformed", MESSAGES["invite_malformed"])
    address = invitation.endpoint if address is None else address
    port = invitation.port if port is None else port
    if relay is not None:
        relay = tuple(relay) if type(relay) in (tuple, list) else relay
    code = InviteCode(invitation.slot, invitation.world_id, invitation.player_id, invitation.display_name, invitation.credential,
                      invitation.build_id, invitation.ruleset_id, invitation.certificate_sha256, address, port, relay)
    from uuid import UUID
    host = address.encode("ascii")
    name = code.display_name.encode("utf-8")
    version, flags, tail = 1, 0, b""
    if code.relay is not None:
        relay_host = code.relay[0].encode("ascii")
        version, flags, tail = 2, _FLAG_RELAY, bytes([len(relay_host)]) + relay_host + struct.pack(">H", code.relay[1])
    body = (struct.pack(">BBBBH", version, flags, code.slot, RULESETS.index(code.ruleset_id), code.port)
            + UUID(code.world_id).bytes + UUID(code.player_id).bytes + code.credential
            + bytes.fromhex(code.build_id) + bytes.fromhex(code.certificate_sha256)
            + bytes([len(host)]) + host + bytes([len(name)]) + name + tail)
    raw = body + struct.pack(">I", zlib.crc32(body))
    text = base64.b32encode(raw).decode("ascii").rstrip("=")
    return PREFIX + "-".join(text[i:i + 5] for i in range(0, len(text), 5))


def decode_invite(text):
    """Parse what a person pasted (spaces, line breaks and lower case are fine). Raises InviteCodeError."""
    if type(text) is not str or not text.strip() or len(text) > MAX_CODE_TEXT:
        raise InviteCodeError("invite_malformed", MESSAGES["invite_malformed"])
    compact = re.sub(r"[\s-]+", "", text).upper()
    if not compact.startswith(PREFIX.replace("-", "")):
        raise InviteCodeError("invite_malformed", MESSAGES["invite_malformed"])
    compact = compact[len(PREFIX.replace("-", "")):]
    try:
        raw = base64.b32decode(compact + "=" * (-len(compact) % 8))
    except (ValueError, TypeError):
        raise InviteCodeError("invite_malformed", MESSAGES["invite_malformed"]) from None
    if len(raw) < 6 + 16 + 16 + 32 + 32 + 32 + 2 + 4 or zlib.crc32(raw[:-4]) != struct.unpack(">I", raw[-4:])[0]:
        raise InviteCodeError("invite_malformed", MESSAGES["invite_malformed"])
    version, flags, slot, ruleset, port = struct.unpack(">BBBBH", raw[:6])
    if version > VERSION or (version == 2 and flags & ~_FLAG_RELAY):
        raise InviteCodeError("invite_version", MESSAGES["invite_version"])
    if version < 1:
        raise InviteCodeError("invite_version_old", MESSAGES["invite_version_old"])
    if version == 1 and flags:
        raise InviteCodeError("invite_malformed", MESSAGES["invite_malformed"])
    if ruleset >= len(RULESETS):
        raise InviteCodeError("invite_malformed", MESSAGES["invite_malformed"])
    from uuid import UUID
    try:
        at = 6
        world, player = str(UUID(bytes=raw[at:at + 16])), str(UUID(bytes=raw[at + 16:at + 32]))
        at += 32
        credential = raw[at:at + 32]
        build = raw[at + 32:at + 64].hex()
        pin = raw[at + 64:at + 96].hex()
        at += 96
        host_length = raw[at]
        host = raw[at + 1:at + 1 + host_length].decode("ascii")
        at += 1 + host_length
        name_length = raw[at]
        name = raw[at + 1:at + 1 + name_length].decode("utf-8")
        at += 1 + name_length
        relay = None
        if flags & _FLAG_RELAY:
            relay_length = raw[at]
            relay_host = raw[at + 1:at + 1 + relay_length].decode("ascii")
            at += 1 + relay_length
            if len(raw) - 4 - at < 2:
                raise ValueError("truncated relay")
            relay = (relay_host, struct.unpack(">H", raw[at:at + 2])[0])
            at += 2
        if at != len(raw) - 4:
            raise ValueError("trailing bytes")
    except (ValueError, IndexError, UnicodeError, struct.error):
        raise InviteCodeError("invite_malformed", MESSAGES["invite_malformed"]) from None
    return InviteCode(slot, world, player, name, credential, build, RULESETS[ruleset], pin, host, port, relay)


def _unavailable(reason, port=None):
    """certificate_unavailable with the real reason: its own plain-English sentence and the diagnostics code."""
    from .connection_diagnostics import describe
    explanation = describe(reason, port=port)
    return InviteCodeError("certificate_unavailable", f"{explanation.title}. {explanation.message}", reason)


def resolve_address(address, port, *, timeout=5.0):
    """The numeric address to connect to for a saved address (a host name is looked up each time; the pinned certificate, not the
    name, is what identifies the host). Raises InviteCodeError when nothing usable comes back."""
    if not valid_address(address) or not valid_port(port):
        raise InviteCodeError("invite_address", MESSAGES["invite_address"])
    try:
        return str(ipaddress.ip_address(address))
    except ValueError:
        pass
    previous = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(timeout)
        infos = socket.getaddrinfo(address, port, type=socket.SOCK_STREAM)
    except OSError:
        raise _unavailable("dns_failed", port) from None
    finally:
        socket.setdefaulttimeout(previous)
    for info in sorted(infos, key=lambda item: item[0] != socket.AF_INET):   # IPv4 first
        candidate = info[4][0]
        if is_numeric_unicast_address(candidate):
            return candidate
    raise InviteCodeError("invite_address", MESSAGES["invite_address"])


async def fetch_certificate(address, port, pin, world_id, *, timeout=5.0, relay=None):
    """The host certificate (PEM) of the server at address:port (or of the world's room on ``relay`` = (address, port)), accepted
    only if its SHA-256 is ``pin`` and it is valid for ``world_id``. Sends no data; the connection is dropped after the handshake.
    A failure to reach the server raises certificate_unavailable whose ``reason`` and message say why (connection_diagnostics)."""
    from .connection_diagnostics import classify, close_quietly, open_tls, peer_certificate, pinning_context
    writer = None
    try:
        async with asyncio.timeout(timeout):
            if relay is None:
                numeric = await asyncio.get_running_loop().run_in_executor(None, lambda: resolve_address(address, port))
                _, writer = await open_tls(numeric, port, pinning_context(), handshake_timeout=min(timeout, 5))
            else:
                _, writer = await open_tls(None, port, pinning_context(), relay=tuple(relay), room=world_id,
                                           handshake_timeout=min(timeout, 5))
        der = peer_certificate(writer)
    except InviteCodeError:
        raise
    except (OSError, TimeoutError, ssl.SSLError, ValueError, asyncio.IncompleteReadError) as error:
        raise _unavailable(classify(error)[0], port) from None
    finally:
        await close_quietly(writer)
    if not der or hashlib.sha256(der).hexdigest() != pin:
        raise InviteCodeError("certificate_mismatch", MESSAGES["certificate_mismatch"])
    pem = ssl.DER_cert_to_PEM_cert(der)
    try:
        _certificate(pem, world_id, pin)
    except InvitationError:
        raise InviteCodeError("certificate_mismatch", MESSAGES["certificate_mismatch"]) from None
    return pem


def redeem(code, certificate_pem, *, endpoint=None):
    """The full private invitation for a code and the certificate fetched for it."""
    endpoint = endpoint or code.address
    try:
        ipaddress.ip_address(endpoint)
    except ValueError:
        endpoint = "127.0.0.1"   # a host name: the numeric address is resolved at every connection; this is only a label
    try:
        return Invitation("friend", code.slot, code.world_id, code.player_id, code.display_name, code.credential, endpoint,
                          code.port, code.build_id, code.ruleset_id, OWNERSHIP_PROFILE, certificate_pem, code.certificate_sha256)
    except InvitationError:
        raise InviteCodeError("invite_malformed", MESSAGES["invite_malformed"]) from None


__all__ = ["InviteCode", "InviteCodeError", "MESSAGES", "VERSION", "decode_invite", "encode_invite", "fetch_certificate", "redeem",
           "resolve_address", "valid_address", "valid_port", "INVITATION_FORMAT"]
