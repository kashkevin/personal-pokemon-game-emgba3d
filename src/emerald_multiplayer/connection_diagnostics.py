"""Honest, specific answers to "why can't my friend connect?".

A failed connection attempt is classified into one stable code, and each code has a plain-English title, an explanation and a short
list of next steps for the people involved: what the host can do on their PC and router, and what the friend can do on theirs. The
menu shows these instead of one catch-all "could not be reached".

``check_server`` is the one check the menu runs for an invite code and for a saved server, directly or through a relay. It never
sends a credential or save data:

1. the address is looked up (a host name each time; ``dns_failed`` when that fails),
2. a TCP connection and the TLS handshake are made (``refused``, ``timeout``, ``unreachable``, ``blocked``, ``tls_failed``),
3. the host's certificate must have the SHA-256 written in the invite and be valid for the world (``wrong_world``,
   ``certificate_invalid``); nothing is sent before this,
4. only then, when the game build is known, a hello *without any credential* asks the server whether it would talk to this game
   version at all. The server checks the protocol and build before it asks for a credential, so "credentials_required" means the
   versions match (``ok``) and "build_mismatch" means they do not (``version_mismatch``). A world that refuses players from outside
   the host's network says so first (``rejected_public_exposure_disabled``). No lease, session or character is created.

Codes (``CODES``): ok, dns_failed, refused, timeout, unreachable, blocked, tls_failed, wrong_world, certificate_invalid,
version_mismatch, invalid_address, rejected_public_exposure_disabled, rejected_player_already_connected,
rejected_invalid_credentials, rejected_enrollment_disabled, rejected_server_full, rejected_busy, rejected, relay_unreachable,
relay_host_offline, relay_busy, relay_failed.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import errno
import hashlib
import socket
import ssl
from uuid import uuid4

DEFAULT_TIMEOUT = 8.0   # one budget for name lookup + TCP + TLS; the companion's connect timeout uses the same value

OK = "ok"
DNS_FAILED = "dns_failed"
REFUSED = "refused"
TIMEOUT = "timeout"
UNREACHABLE = "unreachable"
BLOCKED = "blocked"
TLS_FAILED = "tls_failed"
WRONG_WORLD = "wrong_world"
CERTIFICATE_INVALID = "certificate_invalid"
VERSION_MISMATCH = "version_mismatch"
INVALID_ADDRESS = "invalid_address"
REJECTED = "rejected"
REJECTED_PUBLIC = "rejected_public_exposure_disabled"
REJECTED_ALREADY_CONNECTED = "rejected_player_already_connected"
REJECTED_CREDENTIALS = "rejected_invalid_credentials"
REJECTED_ENROLLMENT = "rejected_enrollment_disabled"
REJECTED_FULL = "rejected_server_full"
REJECTED_BUSY = "rejected_busy"
RELAY_UNREACHABLE = "relay_unreachable"
RELAY_HOST_OFFLINE = "relay_host_offline"
RELAY_BUSY = "relay_busy"
RELAY_FAILED = "relay_failed"

# What the world server's error codes mean for a person (protocol.py, storage.py, server.py).
_SERVER_CODES = {
    "public_exposure_disabled": REJECTED_PUBLIC,
    "player_already_connected": REJECTED_ALREADY_CONNECTED,
    "lease_active": REJECTED_ALREADY_CONNECTED,
    "credentials_invalid": REJECTED_CREDENTIALS,
    "credentials_required": REJECTED_CREDENTIALS,
    "enrollment_disabled": REJECTED_ENROLLMENT,
    "server_full": REJECTED_FULL,
    "connection_limit": REJECTED_BUSY,
    "build_mismatch": VERSION_MISMATCH,
    "ruleset_mismatch": VERSION_MISMATCH,
    "unsupported_protocol": VERSION_MISMATCH,
}

# A connection that fails with one of these will fail the same way every time: retrying cannot help, the player must act.
PERMANENT = frozenset({VERSION_MISMATCH, WRONG_WORLD, CERTIFICATE_INVALID, REJECTED_CREDENTIALS, REJECTED_PUBLIC,
                       REJECTED_ENROLLMENT})
# The server answered and refused, but the reason can clear by itself (a stale session expires within the server's idle timeout,
# a player leaves a full world). Reconnection keeps trying; a session start that runs out of time reports the reason.
HELD = frozenset({REJECTED_ALREADY_CONNECTED, REJECTED_FULL, REJECTED_BUSY, REJECTED})

_REFUSED_NUMBERS = {errno.ECONNREFUSED, 10061, 1225}
_TIMEOUT_NUMBERS = {errno.ETIMEDOUT, 10060, 121}
_UNREACHABLE_NUMBERS = {errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ENETDOWN, errno.EHOSTDOWN, errno.EADDRNOTAVAIL,
                        10050, 10051, 10064, 10065, 10049, 1231, 1232}
_BLOCKED_NUMBERS = {errno.EACCES, errno.EPERM, 10013}


@dataclass(frozen=True)
class Explanation:
    title: str
    message: str
    host_steps: tuple = ()
    friend_steps: tuple = ()

    @property
    def steps(self):
        """Every step, each starting with who does it."""
        return tuple("Host: " + step for step in self.host_steps) + tuple("You: " + step for step in self.friend_steps)


_FIREWALL = "Allow EmeraldTogether through Windows Firewall on the hosting PC (when Windows asks, tick Private and Public networks)."
_ROUTER = ("Let the game set up the router automatically (Network settings, Automatic router setup), or forward TCP port {port} "
           "to the hosting PC in the router's settings.")
_CGNAT = ("If the router's own Internet (WAN) address starts with 100.64 to 100.127, 10., 172.16 to 172.31 or 192.168., the "
          "Internet provider shares one address between many homes (CGNAT) and port forwarding cannot work: use a relay or "
          "Tailscale instead (see the hosting guide, HOSTING.txt).")

EXPLANATIONS = {
    OK: Explanation("Connected", "The host answered and it is the right world."),
    DNS_FAILED: Explanation(
        "The address name could not be found",
        "This PC could not look up the host name in the invite. It may be mistyped, out of date, or your Internet connection may "
        "be down.",
        ("If you use a dynamic DNS name, check that it points to your current Internet address.",),
        ("Check the address with the host, letter by letter.", "Check that this PC can open web pages.")),
    REFUSED: Explanation(
        "Nothing is accepting connections there",
        "Your PC reached the host's computer or router, but nothing is listening on that port. Usually the world is not being "
        "hosted right now, or the port is different.",
        ("Host the world (Host World, then the world) and keep the game open while friends join.",
         "Check that the port in Server Information is the one in the invite.",
         "If the router forwards the port, it must forward it to the PC that is hosting (its current local address)."),
        ("Ask the host to start the world, then try again.",)),
    TIMEOUT: Explanation(
        "The host did not answer",
        "Your PC asked to connect but nothing answered in time. The connection is being blocked or lost before it reaches the "
        "game: the router does not forward the port, a firewall blocks it, the Internet provider shares addresses (CGNAT), or "
        "the address is old or wrong.",
        ("For friends outside your home, turn on Internet access in Network settings and host again.", _FIREWALL, _ROUTER,
         _CGNAT, "Check that the public address in the invite is your current one."),
        ("Check the address and port with the host.", "If you and the host are on the same Wi-Fi, use the host's local address.")),
    UNREACHABLE: Explanation(
        "There is no route to that address",
        "Your PC has no network path to that address. Your own connection may be down, or the address belongs to a network you "
        "are not on: 192.168.x.x, 10.x.x.x and 172.16-31.x.x addresses only work inside the host's home.",
        ("Give friends outside your home your public address (with port forwarding), a relay, or your Tailscale address.",),
        ("Check that this PC is connected to the Internet.",
         "If you use Tailscale or another VPN, check that it is connected on both PCs.")),
    BLOCKED: Explanation(
        "This PC blocked the connection",
        "Firewall or security software on this PC refused to let the game connect.",
        (),
        ("Allow EmeraldTogether in your firewall or antivirus, then try again.",)),
    TLS_FAILED: Explanation(
        "The secure connection could not be set up",
        "Something answered at that address, but the encrypted handshake failed. Another program may be using the same port, "
        "or a network device or antivirus 'HTTPS scanning' is interfering.",
        ("Check that no other program uses the world's port, or choose the world's own port in the router forward.",),
        ("Turn off HTTPS or SSL scanning in your antivirus, or try another network.",)),
    WRONG_WORLD: Explanation(
        "That is not the world from your invite",
        "A server answered, but its identity does not match your invite, so nothing was sent to it and your sign-in stays private.",
        ("Check that you are hosting the right world.",
         "If the router forwards the port, check that it forwards it to the PC that is hosting this world."),
        ("Ask the host for their current address, or a new invite code.",)),
    CERTIFICATE_INVALID: Explanation(
        "The world's security certificate is not valid",
        "The host's world presented its own certificate, but it has expired or is damaged, so the game will not trust it.",
        ("Check the PC's date and time; a world certificate is valid for a year after it was created.",),
        ("Check this PC's date and time.",)),
    VERSION_MISMATCH: Explanation(
        "Different game versions",
        "The host's game and yours are different versions, so they cannot play together.",
        ("Tell your friends which EmeraldTogether version you have.",),
        ("Install exactly the same EmeraldTogether version as the host.",)),
    INVALID_ADDRESS: Explanation(
        "That address cannot be used",
        "The address or port is not valid. Use an IP address such as 203.0.113.7 or a host name, and a port from 1 to 65535.",
        (),
        ("Copy the address again from the host.",)),
    REJECTED_PUBLIC: Explanation(
        "The world is not open to the Internet",
        "Your connection reached the host's game, but the world only accepts players on the host's own network or VPN.",
        ("Open Network settings, turn on Internet access, then host the world again.",
         "Or put both PCs on the same Tailscale network and use the host's Tailscale address."),
        ("Ask the host to turn on Internet access for the world.",)),
    REJECTED_ALREADY_CONNECTED: Explanation(
        "This character is already in the world",
        "The host says this account is already connected: from another PC, another game window, or a game that closed a moment "
        "ago and has not timed out yet.",
        (),
        ("Close any other game that uses this invite.",
         "If the game just closed or crashed, wait half a minute and try again.")),
    REJECTED_CREDENTIALS: Explanation(
        "The host did not accept this invite",
        "The sign-in in this invite is not valid for the world any more. The account may have been replaced, or the code was "
        "copied wrongly.",
        ("Make a new invite code for this friend and send it to them privately.",),
        ("Paste the newest invite code from the host.",)),
    REJECTED_ENROLLMENT: Explanation(
        "The host is not accepting new characters",
        "The world is reachable, but the host has turned off creating new characters over the network.",
        ("Open Network settings and turn on 'New players bring their character', then host again.",),
        ("Ask the host to allow new characters.",)),
    REJECTED_FULL: Explanation(
        "The world is full",
        "All player places in the world are in use right now.",
        (),
        ("Wait until someone leaves, then try again.",)),
    REJECTED_BUSY: Explanation(
        "The host is busy",
        "Too many connections are being set up at the same moment.",
        (),
        ("Wait a few seconds and try again.",)),
    REJECTED: Explanation(
        "The host refused the connection",
        "The host's game answered but refused this connection.",
        ("Check that the world is hosted with the same game version as your friends.",),
        ("Try again in a moment; if it keeps happening, ask the host for a new invite code.",)),
    RELAY_UNREACHABLE: Explanation(
        "The relay could not be reached",
        "The game could not connect to the relay server named in the invite or in Network settings.",
        ("Check that the relay server is running and that its port is reachable from the Internet.",
         "Check the relay address and port in Network settings."),
        ("Check that this PC is connected to the Internet, and the relay address with the host.",)),
    RELAY_HOST_OFFLINE: Explanation(
        "The host is not connected to the relay",
        "The relay is working, but the host's world is not connected to it right now.",
        ("Host the world with the relay turned on and keep the game open.",
         "Check that the relay address in Network settings is the same one in the invite."),
        ("Ask the host to start the world, then try again.",)),
    RELAY_BUSY: Explanation(
        "The relay is full",
        "The relay server has reached its limit of connections or worlds.",
        ("Use another relay, or ask the relay's owner to raise its limits.",),
        ("Try again later.",)),
    RELAY_FAILED: Explanation(
        "The relay did not answer correctly",
        "Something answered at the relay address, but it is not a compatible EmeraldTogether relay.",
        ("Check the relay address and port, and that the relay runs the same EmeraldTogether version.",),
        ("Check the relay address with the host.",)),
}
CODES = tuple(EXPLANATIONS)


def describe(code, *, port=None):
    """The explanation for a code (an unknown code gets the generic refusal text)."""
    explanation = EXPLANATIONS.get(code, EXPLANATIONS[REJECTED])
    text = "?" if port is None else str(port)
    return Explanation(explanation.title, explanation.message, tuple(step.replace("{port}", text) for step in explanation.host_steps),
                       tuple(step.replace("{port}", text) for step in explanation.friend_steps))


def rejection_code(server_code):
    """The code for a world server's error message code."""
    return _SERVER_CODES.get(server_code, REJECTED)


def is_permanent(code):
    return code in PERMANENT


def classify(error):
    """(code, detail) for an exception from a connection attempt. ``detail`` names the exception and number, never secrets."""
    from .secure_transport import HostIdentityError
    code = getattr(error, "reason", None)
    if code in EXPLANATIONS:
        return code, _detail(error)
    from .relay import RelayError
    if isinstance(error, RelayError):
        return error.code if error.code in EXPLANATIONS else RELAY_FAILED, _detail(error)
    if isinstance(error, HostIdentityError):
        return WRONG_WORLD, _detail(error)
    if isinstance(error, ssl.SSLCertVerificationError):
        # Verified against the invitation's own certificate: a different certificate is another server, an expired or
        # not-yet-valid one is this world's certificate out of its dates.
        return (CERTIFICATE_INVALID if getattr(error, "verify_code", None) in (9, 10) else WRONG_WORLD), _detail(error)
    if isinstance(error, socket.gaierror):
        return DNS_FAILED, _detail(error)
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return TIMEOUT, _detail(error)
    if isinstance(error, ConnectionRefusedError):
        return REFUSED, _detail(error)
    if isinstance(error, ssl.SSLError) or isinstance(error, (asyncio.IncompleteReadError, ConnectionResetError,
                                                             ConnectionAbortedError, BrokenPipeError)):
        return TLS_FAILED, _detail(error)
    if isinstance(error, OSError):
        number = getattr(error, "winerror", None) or error.errno
        if number in _REFUSED_NUMBERS:
            return REFUSED, _detail(error)
        if number in _TIMEOUT_NUMBERS:
            return TIMEOUT, _detail(error)
        if number in _UNREACHABLE_NUMBERS:
            return UNREACHABLE, _detail(error)
        if number in _BLOCKED_NUMBERS:
            return BLOCKED, _detail(error)
        return UNREACHABLE, _detail(error)
    server_code = getattr(error, "code", None)
    if type(server_code) is str:
        return rejection_code(server_code), _detail(error)
    return UNREACHABLE, _detail(error)


def _detail(error):
    number = getattr(error, "winerror", None) or getattr(error, "errno", None)
    name = type(error).__name__
    code = getattr(error, "code", None)
    parts = [name]
    if type(code) is str:
        parts.append(code)
    if type(number) is int:
        parts.append(f"error {number}")
    return " ".join(parts)


@dataclass(frozen=True)
class CheckResult:
    code: str
    title: str
    message: str
    steps: tuple
    detail: str = ""
    route: str = "direct"                          # "direct" or "relay"
    address: str = ""                              # what was checked (the relay for a relay route)
    port: int = 0
    host_steps: tuple = ()
    friend_steps: tuple = ()
    certificate_pem: str | None = field(default=None, repr=False)   # the verified host certificate, for redeeming an invite code

    @property
    def ok(self):
        return self.code == OK

    @property
    def permanent(self):
        return is_permanent(self.code)


def result(code, *, detail="", route="direct", address="", port=0, certificate_pem=None, game_port=None):
    explanation = describe(code, port=game_port if game_port is not None else (port or None))
    return CheckResult(code, explanation.title, explanation.message, explanation.steps, detail, route, address, port,
                       explanation.host_steps, explanation.friend_steps, certificate_pem)


def pinning_context():
    """A TLS client context that trusts nothing by itself: the caller compares the certificate with the invite's pin."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


async def open_tls(host, port, context, *, relay=None, room=None, handshake_timeout=5.0, limit=65_536):
    """A TLS stream to ``host:port`` (a numeric address), or through ``relay`` = (address, port) to the world ``room``.

    The TLS handshake is end to end with the world server in both cases; the relay only carries ciphertext."""
    if relay is None:
        return await asyncio.open_connection(host, port, ssl=context, server_hostname=host, limit=limit,
                                             ssl_handshake_timeout=handshake_timeout, ssl_shutdown_timeout=1)
    from .relay import open_relay_connection
    return await open_relay_connection(relay[0], relay[1], room, ssl=context, server_hostname=host or "emerald-world",
                                       ssl_handshake_timeout=handshake_timeout, limit=limit)


def peer_certificate(writer):
    peer = writer.get_extra_info("ssl_object")
    return peer.getpeercert(binary_form=True) if peer is not None else None


async def close_quietly(writer):
    if writer is None:
        return
    writer.close()
    try:
        async with asyncio.timeout(2):
            await writer.wait_closed()
    except (OSError, TimeoutError, ssl.SSLError):
        pass


async def _version_probe(reader, writer, build_id, ruleset_id, budget):
    """Ask the server, without a credential, whether it would talk to this build. Returns (code, detail)."""
    from .protocol import PROTOCOL_VERSION, ProtocolError, encode_message, read_message
    try:
        try:
            # A server that refuses this peer outright says so before it reads anything.
            async with asyncio.timeout(min(.3, budget)):
                first = await read_message(reader)
        except TimeoutError:
            first = None
        else:
            if first is None:
                return OK, "closed before the version check"
            if first.get("type") == "error":
                return rejection_code(first.get("code")), "server error " + str(first.get("code"))[:64]
        writer.write(encode_message({"type": "hello", "protocol": PROTOCOL_VERSION, "build_id": build_id, "ruleset_id": ruleset_id,
                                     "player_id": str(uuid4()), "display_name": "check"}))
        async with asyncio.timeout(max(budget, .5)):
            await writer.drain()
            reply = await read_message(reader)
    except (TimeoutError, ProtocolError, OSError, ssl.SSLError, asyncio.IncompleteReadError):
        return OK, "no answer to the version check"
    if reply is None or reply.get("type") != "error":
        return OK, "version check answered"
    server_code = reply.get("code")
    if server_code in ("credentials_required", "credentials_invalid"):
        return OK, "version check passed"
    return rejection_code(server_code), "server error " + str(server_code)[:64]


async def check_server(address, port, *, certificate_sha256, world_id, build_id=None, ruleset_id=None, timeout=DEFAULT_TIMEOUT,
                       relay=None):
    """Check that ``address:port`` (or the world's room on ``relay`` = (address, port)) is the world with this certificate pin,
    and, when ``build_id`` and ``ruleset_id`` are given, that it accepts this game version. Never raises for a network problem."""
    from .invitations import InvitationError, _certificate
    from .invite_code import InviteCodeError, resolve_address, valid_address, valid_port
    route = "direct" if relay is None else "relay"
    shown = (address, port) if relay is None else tuple(relay)
    common = dict(route=route, address=str(shown[0]), port=shown[1] if type(shown[1]) is int else 0, game_port=port)
    if (not valid_address(address) or not valid_port(port) or type(certificate_sha256) is not str or len(certificate_sha256) != 64
            or (relay is not None and (type(relay) not in (tuple, list) or len(relay) != 2
                                       or not valid_address(relay[0]) or not valid_port(relay[1])))):
        return result(INVALID_ADDRESS, **common)
    if type(timeout) not in (int, float) or not 0 < timeout <= 60:
        raise ValueError("timeout must be between zero and sixty seconds")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    writer = None
    try:
        try:
            async with asyncio.timeout(timeout):
                if relay is None:
                    numeric = await loop.run_in_executor(None, lambda: resolve_address(address, port, timeout=timeout))
                    reader, writer = await open_tls(numeric, port, pinning_context(), handshake_timeout=timeout)
                else:
                    reader, writer = await open_tls(None, port, pinning_context(), relay=tuple(relay), room=world_id,
                                                    handshake_timeout=timeout)
        except InviteCodeError as error:
            code = error.reason if getattr(error, "reason", None) in EXPLANATIONS else INVALID_ADDRESS
            return result(code, detail=error.code, **common)
        except (OSError, TimeoutError, ssl.SSLError, ValueError, ConnectionError, asyncio.IncompleteReadError) as error:
            code, detail = classify(error)
            return result(code, detail=detail, **common)
        der = peer_certificate(writer)
        if not der or hashlib.sha256(der).hexdigest() != certificate_sha256:
            return result(WRONG_WORLD, detail="certificate pin differs", **common)
        pem = ssl.DER_cert_to_PEM_cert(der)
        try:
            _certificate(pem, world_id, certificate_sha256)
        except InvitationError as error:
            return result(CERTIFICATE_INVALID, detail=error.code, **common)
        detail = "certificate verified"
        if build_id is not None and ruleset_id is not None:
            code, detail = await _version_probe(reader, writer, build_id, ruleset_id, max(deadline - loop.time(), .5))
            if code != OK:
                return result(code, detail=detail, **common)
        return result(OK, detail=detail, certificate_pem=pem, **common)
    finally:
        await close_quietly(writer)


async def check_routes(address, port, *, relay=None, **options):
    """Try the direct route first and, when it cannot be reached and a relay is known, the relay. The result names the route that
    answered (or the direct route's failure when both fail for a network reason)."""
    direct = await check_server(address, port, **options)
    if direct.ok or relay is None or direct.code in PERMANENT or direct.code.startswith("rejected"):
        return direct
    relayed = await check_server(address, port, relay=relay, **options)
    if relayed.ok or relayed.code in PERMANENT or relayed.code.startswith("rejected"):
        return relayed
    return direct if relayed.code == RELAY_UNREACHABLE else relayed


__all__ = ["CODES", "CheckResult", "DEFAULT_TIMEOUT", "EXPLANATIONS", "Explanation", "HELD", "PERMANENT", "check_routes",
           "check_server", "classify", "describe", "is_permanent", "rejection_code", "result"]
