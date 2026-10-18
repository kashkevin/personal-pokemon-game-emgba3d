"""Automatic router setup for a world that allows Internet connections: UPnP IGD and NAT-PMP, with honest results.

Most home routers can open a port for a program on request: UPnP Internet Gateway Device (IGD: SSDP discovery on the local network,
then SOAP over HTTP to the router's WANIPConnection or WANPPPConnection service) or NAT-PMP (RFC 6886: UDP port 5351 of the default
gateway; Apple and some other routers). This module asks for one TCP port mapping to this PC, renews its lease while the world is
hosted and removes it when hosting stops. It needs nothing outside the Python standard library and never blocks hosting: every
step has a timeout and the whole attempt is bounded to a few seconds.

The result also says what the router told us about the Internet side. When the router's own external address is private
(another router in front: double NAT) or in 100.64.0.0/10 (the Internet provider shares one public address between many homes:
carrier-grade NAT), a port mapping on this router cannot make the PC reachable from the Internet, and the result says so: the
answer then is a relay or an overlay VPN such as Tailscale (see docs/networking.md).

What this cannot know: whether the Internet provider blocks incoming connections anyway, and whether Windows Firewall on this PC
lets the game's port in (Windows asks the first time the game listens; both Private and Public networks must be allowed for
friends on the Internet).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
import http.client
import ipaddress
import os
import re
import socket
import struct
import time
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree
from xml.sax.saxutils import escape

UPNP = "upnp"
NATPMP = "natpmp"
SSDP_ADDRESS = ("239.255.255.250", 1900)
NATPMP_PORT = 5351
SEARCH_TARGETS = (
    "urn:schemas-upnp-org:device:InternetGatewayDevice:1",
    "urn:schemas-upnp-org:device:InternetGatewayDevice:2",
    "urn:schemas-upnp-org:service:WANIPConnection:1",
    "urn:schemas-upnp-org:service:WANIPConnection:2",
    "urn:schemas-upnp-org:service:WANPPPConnection:1",
)
_SERVICES = ("WANIPConnection", "WANPPPConnection")
_MAX_DESCRIPTION = 65_536
_OVERLAY = ipaddress.ip_network("100.64.0.0/10")

MAPPED = "mapped"
CHECKING = "checking"
DISABLED = "disabled"
NO_GATEWAY = "no_gateway"
NO_ROUTER_SUPPORT = "no_router_support"
CONFLICT = "conflict"
REFUSED = "refused"
CGNAT = "cgnat"
DOUBLE_NAT = "double_nat"
FAILED = "failed"

MESSAGES = {
    MAPPED: "The router was set up automatically ({method}): friends on the Internet can use {external}:{port}.",
    CHECKING: "Setting up the router automatically...",
    DISABLED: "Automatic router setup is off. Friends on the Internet need TCP port {port} forwarded to this PC.",
    NO_GATEWAY: ("This PC's router could not be found, so it could not be set up automatically. Forward TCP port {port} to "
                 "this PC in the router's settings."),
    NO_ROUTER_SUPPORT: ("The router did not answer automatic setup (UPnP and NAT-PMP are turned off or not supported). Turn on "
                        "UPnP in the router, or forward TCP port {port} to this PC ({internal}) yourself."),
    CONFLICT: ("The router already forwards port {port} to another device. Change that forward in the router, or host this "
               "world from that device."),
    REFUSED: "The router refused automatic setup. Forward TCP port {port} to this PC ({internal}) in the router's settings.",
    CGNAT: ("Your Internet provider shares one Internet address between many homes (carrier-grade NAT: the router's Internet "
            "address is {external}). Friends on the Internet cannot reach this PC through the router. Use a relay or Tailscale."),
    DOUBLE_NAT: ("This router is behind another router (its Internet address {external} is private). Forward TCP port {port} "
                 "on the other router too, or use a relay or Tailscale."),
    FAILED: "Automatic router setup did not work. Forward TCP port {port} to this PC ({internal}) in the router's settings.",
}


@dataclass(frozen=True)
class MappingResult:
    code: str
    method: str | None = None             # "upnp" or "natpmp"
    external_address: str | None = None   # the router's Internet address, when it told us
    external_port: int | None = None
    internal_address: str | None = None   # this PC's address on the router's network
    internal_port: int = 0
    lease_seconds: int = 0                # 0: permanent (removed when hosting stops)
    detail: str = ""

    @property
    def ok(self):
        return self.code == MAPPED

    @property
    def message(self):
        return MESSAGES.get(self.code, MESSAGES[FAILED]).format(
            method={"upnp": "UPnP", "natpmp": "NAT-PMP"}.get(self.method, "automatic"),
            external=self.external_address or "unknown", port=self.external_port or self.internal_port,
            internal=self.internal_address or "this PC")


class UpnpError(Exception):
    def __init__(self, code, description=""):
        super().__init__(f"UPnP error {code} {description}".strip())
        self.code = code
        self.description = description


def address_problem(external):
    """CGNAT for 100.64.0.0/10, DOUBLE_NAT for another private address, None for a public one (or unknown)."""
    try:
        address = ipaddress.ip_address(external)
    except (ValueError, TypeError):
        return None
    if address.version == 4 and address in _OVERLAY:
        return CGNAT
    if address.is_private or address.is_link_local:
        return DOUBLE_NAT
    return None


# ------------------------------------------------------------------------------------------------------------ default gateway


def parse_proc_net_route(text):
    """The default gateway from Linux /proc/net/route, or None."""
    best = None
    for line in text.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 8:
            continue
        try:
            destination, gateway, flags, metric = int(fields[1], 16), int(fields[2], 16), int(fields[3], 16), int(fields[6])
        except ValueError:
            continue
        if destination == 0 and flags & 0x2 and gateway:
            candidate = (metric, socket.inet_ntoa(struct.pack("<I", gateway)))
            best = candidate if best is None or candidate < best else best
    return best[1] if best else None


def parse_route_print(text):
    """The default gateway from Windows ``route print -4`` (any display language: the route lines are numeric), or None."""
    best = None
    pattern = re.compile(r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+(\d{1,3}(?:\.\d{1,3}){3})\s+(\d{1,3}(?:\.\d{1,3}){3})\s+(\d+)\s*$")
    for line in text.splitlines():
        match = pattern.match(line)
        if match:
            candidate = (int(match.group(3)), match.group(1))
            best = candidate if best is None or candidate < best else best
    return best[1] if best else None


def default_gateway(run=None):
    """This PC's default IPv4 gateway (normally the home router), or None. Windows: ``route print -4``; Linux: /proc/net/route."""
    try:
        if os.name == "nt":
            import subprocess
            run = run or subprocess.run
            output = run(["route", "print", "-4"], capture_output=True, timeout=3,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return parse_route_print(output.stdout.decode(errors="replace"))
        with open("/proc/net/route", encoding="ascii", errors="replace") as source:
            return parse_proc_net_route(source.read(65_536))
    except Exception:                                                  # noqa: BLE001 - no gateway is a normal answer
        return None


def local_address_towards(host):
    """This PC's address on the network that reaches ``host`` (a UDP connect sends nothing)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((host, 9))
        return probe.getsockname()[0]
    finally:
        probe.close()


# ---------------------------------------------------------------------------------------------------------------------- UPnP


def ssdp_discover(timeout=2.0, *, target=SSDP_ADDRESS):
    """LOCATION URLs of Internet gateway devices that answered an SSDP search within ``timeout`` seconds. A location is kept
    only when it is plain HTTP on the very address that answered (a device cannot point us at another machine)."""
    found = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        for search_target in SEARCH_TARGETS:
            message = ("M-SEARCH * HTTP/1.1\r\n"
                       f"HOST: {SSDP_ADDRESS[0]}:{SSDP_ADDRESS[1]}\r\n"
                       'MAN: "ssdp:discover"\r\n'
                       "MX: 2\r\n"
                       f"ST: {search_target}\r\n\r\n")
            sock.sendto(message.encode("ascii"), target)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if found:
                remaining = min(remaining, .3)       # other gateways answer together with the first; do not wait the full time
            if remaining <= 0:
                break
            sock.settimeout(remaining)
            try:
                data, (responder, _) = sock.recvfrom(4096)
            except (TimeoutError, socket.timeout):
                break
            location = _ssdp_location(data)
            if location is None:
                continue
            parts = urlsplit(location)
            if parts.scheme == "http" and parts.hostname == responder and location not in found:
                found.append(location)
                deadline = min(deadline, time.monotonic() + .3)
    except OSError:
        pass
    finally:
        sock.close()
    return found


def _ssdp_location(data):
    try:
        text = data.decode("ascii", errors="replace")
    except Exception:                                                  # noqa: BLE001
        return None
    lines = text.split("\r\n")
    if not lines or not lines[0].upper().startswith("HTTP/1.1 200"):
        return None
    for line in lines[1:]:
        name, _, value = line.partition(":")
        if name.strip().lower() == "location":
            return value.strip()[:512] or None
    return None


def _http(method, url, *, body=None, headers=None, timeout=2.0):
    parts = urlsplit(url)
    if parts.scheme != "http" or not parts.hostname:
        raise UpnpError("bad_url")
    connection = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=timeout)
    try:
        path = (parts.path or "/") + (("?" + parts.query) if parts.query else "")
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        data = response.read(_MAX_DESCRIPTION + 1)
        if len(data) > _MAX_DESCRIPTION:
            raise UpnpError("too_large")
        return response.status, data
    finally:
        connection.close()


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def find_service(location, *, timeout=2.0):
    """(control URL, service type) of the device's WANIPConnection or WANPPPConnection service, or None."""
    status, data = _http("GET", location, timeout=timeout)
    if status != 200:
        return None
    root = ElementTree.fromstring(data)
    base = next((element.text.strip() for element in root.iter() if _local(element.tag) == "URLBase" and element.text), None)
    host = urlsplit(location).hostname
    for element in root.iter():
        if _local(element.tag) != "service":
            continue
        fields = {_local(child.tag): (child.text or "").strip() for child in element}
        service_type, control = fields.get("serviceType", ""), fields.get("controlURL", "")
        if not control or not any(name in service_type for name in _SERVICES):
            continue
        url = urljoin(base or location, control)
        if urlsplit(url).scheme == "http" and urlsplit(url).hostname == host:
            return url, service_type
    return None


def soap(control_url, service_type, action, arguments=(), *, timeout=2.0):
    """Call one UPnP action. Returns the response arguments; raises UpnpError with the device's error code."""
    body = ('<?xml version="1.0"?>\r\n<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            f'<u:{action} xmlns:u="{escape(service_type)}">'
            + "".join(f"<{name}>{escape(str(value))}</{name}>" for name, value in arguments)
            + f"</u:{action}></s:Body></s:Envelope>\r\n").encode("utf-8")
    headers = {"Content-Type": 'text/xml; charset="utf-8"', "SOAPAction": f'"{service_type}#{action}"', "Connection": "close"}
    status, data = _http("POST", control_url, body=body, headers=headers, timeout=timeout)
    try:
        root = ElementTree.fromstring(data) if data else None
    except ElementTree.ParseError:
        root = None
    if status != 200:
        code = description = ""
        if root is not None:
            for element in root.iter():
                if _local(element.tag) == "errorCode":
                    code = (element.text or "").strip()
                elif _local(element.tag) == "errorDescription":
                    description = (element.text or "").strip()[:80]
        raise UpnpError(int(code) if code.isdigit() else f"http_{status}", description)
    if root is None:
        raise UpnpError("bad_response")
    for element in root.iter():
        if _local(element.tag) == action + "Response":
            return {_local(child.tag): (child.text or "").strip() for child in element}
    return {}


class _Upnp:
    method = UPNP

    def __init__(self, control_url, service_type, internal_address, timeout):
        self.control_url, self.service_type, self.internal_address, self.timeout = control_url, service_type, internal_address, timeout

    def add(self, external_port, internal_port, lease, description):
        arguments = (("NewRemoteHost", ""), ("NewExternalPort", external_port), ("NewProtocol", "TCP"),
                     ("NewInternalPort", internal_port), ("NewInternalClient", self.internal_address), ("NewEnabled", 1),
                     ("NewPortMappingDescription", description), ("NewLeaseDuration", lease))
        try:
            soap(self.control_url, self.service_type, "AddPortMapping", arguments, timeout=self.timeout)
            return lease
        except UpnpError as error:
            if error.code == 725 and lease:          # OnlyPermanentLeasesSupported
                soap(self.control_url, self.service_type, "AddPortMapping", arguments[:-1] + (("NewLeaseDuration", 0),),
                     timeout=self.timeout)
                return 0
            if error.code == 718:                    # ConflictInMappingEntry: ours from an earlier run, or another device's
                entry = soap(self.control_url, self.service_type, "GetSpecificPortMappingEntry",
                             (("NewRemoteHost", ""), ("NewExternalPort", external_port), ("NewProtocol", "TCP")),
                             timeout=self.timeout)
                if entry.get("NewInternalClient") == self.internal_address and entry.get("NewInternalPort") == str(internal_port):
                    return int(entry.get("NewLeaseDuration") or 0) if str(entry.get("NewLeaseDuration", "0")).isdigit() else 0
            raise

    def external_address(self):
        return soap(self.control_url, self.service_type, "GetExternalIPAddress", timeout=self.timeout).get("NewExternalIPAddress")

    def delete(self, external_port, internal_port):
        soap(self.control_url, self.service_type, "DeletePortMapping",
             (("NewRemoteHost", ""), ("NewExternalPort", external_port), ("NewProtocol", "TCP")), timeout=self.timeout)


# ------------------------------------------------------------------------------------------------------------------- NAT-PMP


class NatPmpError(Exception):
    def __init__(self, code):
        super().__init__(f"NAT-PMP result {code}")
        self.code = code


def natpmp_request(gateway, payload, opcode, *, port=NATPMP_PORT, budget=2.0):
    """Send a NAT-PMP request (retransmitting at 250 ms, 500 ms, 1 s, ... within ``budget``) and return the matching answer."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((gateway, port))
        deadline = time.monotonic() + budget
        wait = .25
        while time.monotonic() < deadline:
            sock.send(payload)
            until = min(deadline, time.monotonic() + wait)
            while True:
                remaining = until - time.monotonic()
                if remaining <= 0:
                    break
                sock.settimeout(remaining)
                try:
                    data = sock.recv(64)
                except (TimeoutError, socket.timeout):
                    break
                except ConnectionRefusedError:       # ICMP port unreachable: nothing answers NAT-PMP there
                    raise NatPmpError("unreachable") from None
                if len(data) >= 4 and data[0] == 0 and data[1] == 128 + opcode:
                    result = struct.unpack(">H", data[2:4])[0]
                    if result != 0:
                        raise NatPmpError(result)
                    return data
            wait *= 2
        raise NatPmpError("timeout")
    finally:
        sock.close()


class _NatPmp:
    method = NATPMP

    def __init__(self, gateway, port, budget):
        self.gateway, self.port, self.budget = gateway, port, budget
        self.internal_address = None

    def add(self, external_port, internal_port, lease, description):
        data = natpmp_request(self.gateway, struct.pack(">BBHHHI", 0, 2, 0, internal_port, external_port, lease), 2,
                              port=self.port, budget=self.budget)
        if len(data) < 16:
            raise NatPmpError("short")
        _, _, _, _, mapped_internal, mapped_external, lifetime = struct.unpack(">BBHIHHI", data[:16])
        self.mapped_external = mapped_external
        return lifetime

    def external_address(self):
        data = natpmp_request(self.gateway, struct.pack(">BB", 0, 0), 0, port=self.port, budget=self.budget)
        if len(data) < 12:
            raise NatPmpError("short")
        return socket.inet_ntoa(data[8:12])

    def delete(self, external_port, internal_port):
        natpmp_request(self.gateway, struct.pack(">BBHHHI", 0, 2, 0, internal_port, 0, 0), 2, port=self.port,
                       budget=min(self.budget, 1.0))


# --------------------------------------------------------------------------------------------------------------------- mapper


class PortMapper:
    """Map TCP ``internal_port`` on the router to this PC while hosting; renew it; remove it on ``close``.

    ``start`` never raises and returns a MappingResult (also kept as ``result``); ``on_change`` is called with every new result
    (renewal failures included). Endpoints are injectable for tests: ``ssdp_target`` (where the SSDP search is sent), ``gateway``
    (skip gateway discovery) and ``natpmp_port``."""

    def __init__(self, internal_port, *, external_port=None, description="EmeraldTogether", lease=3600, budget=5.0,
                 ssdp_target=SSDP_ADDRESS, gateway=None, natpmp_port=NATPMP_PORT, on_change=None, find_gateway=default_gateway):
        if type(internal_port) is not int or not 1 <= internal_port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        self.internal_port = internal_port
        self.external_port = external_port or internal_port
        self.description = description[:64]
        self.lease = lease
        self.budget = budget
        self.ssdp_target = ssdp_target
        self.gateway = gateway
        self.natpmp_port = natpmp_port
        self.on_change = on_change
        self.find_gateway = find_gateway
        self.result = MappingResult(CHECKING, internal_port=internal_port, external_port=self.external_port)
        self._backend = None
        self._renewal = None

    def _set(self, result):
        self.result = result
        if self.on_change is not None:
            try:
                self.on_change(result)
            except Exception:                                          # noqa: BLE001 - an observer never stops hosting
                pass

    def _base(self, **fields):
        return MappingResult(internal_port=self.internal_port, external_port=self.external_port, **fields)

    def _map(self):
        """Blocking: discover, map, read the external address. Returns a MappingResult."""
        started = time.monotonic()
        share = self.budget / 2
        detail = []
        gateway = self.gateway or self.find_gateway()
        # UPnP IGD
        try:
            for location in ssdp_discover(min(2.0, share), target=self.ssdp_target):
                service = find_service(location, timeout=2.0)
                if service is None:
                    continue
                internal = local_address_towards(urlsplit(location).hostname)
                backend = _Upnp(service[0], service[1], internal, 2.0)
                result = self._try(backend, internal)
                if result is not None:
                    return result
        except (OSError, UpnpError, ElementTree.ParseError, http.client.HTTPException) as error:
            detail.append("upnp: " + type(error).__name__)
        # NAT-PMP to the default gateway
        if gateway is None:
            return self._base(code=NO_GATEWAY, detail="; ".join(detail))
        internal = None
        try:
            internal = local_address_towards(gateway)
        except OSError:
            pass
        backend = _NatPmp(gateway, self.natpmp_port, max(.5, min(share, self.budget - (time.monotonic() - started))))
        backend.internal_address = internal
        try:
            result = self._try(backend, internal)
            if result is not None:
                return result
        except NatPmpError as error:
            if error.code in ("timeout", "unreachable", 1, 5):
                return self._base(code=NO_ROUTER_SUPPORT, internal_address=internal, detail="; ".join(detail + [str(error)]))
            return self._base(code=REFUSED, internal_address=internal, detail="; ".join(detail + [str(error)]))
        except OSError as error:
            detail.append("natpmp: " + type(error).__name__)
        return self._base(code=NO_ROUTER_SUPPORT, internal_address=internal, detail="; ".join(detail))

    def _try(self, backend, internal):
        """Map with one backend. Returns a result, or None to try the next device. Raises for NAT-PMP failures."""
        try:
            lease = backend.add(self.external_port, self.internal_port, self.lease, self.description)
        except UpnpError as error:
            code = CONFLICT if error.code == 718 else REFUSED
            return self._base(code=code, method=backend.method, internal_address=internal, detail=str(error))
        external_port = getattr(backend, "mapped_external", None) or self.external_port
        self._backend = backend
        try:
            external = backend.external_address()
        except (UpnpError, NatPmpError, OSError, http.client.HTTPException, ElementTree.ParseError):
            external = None
        problem = address_problem(external)
        return MappingResult(problem or MAPPED, backend.method, external, external_port, internal, self.internal_port, lease)

    async def start(self):
        try:
            async with asyncio.timeout(self.budget + 6):
                result = await asyncio.to_thread(self._map)
        except (TimeoutError, Exception) as error:                     # noqa: BLE001 - never stop hosting
            result = self._base(code=FAILED, detail=type(error).__name__)
        self._set(result)
        if self._backend is not None and result.lease_seconds > 0 and result.code in (MAPPED, CGNAT, DOUBLE_NAT):
            self._renewal = asyncio.create_task(self._renew(result.lease_seconds), name="router-mapping-renewal")
        return result

    async def _renew(self, lease):
        while True:
            await asyncio.sleep(max(lease / 2, 1))
            try:
                lease = await asyncio.wait_for(asyncio.to_thread(
                    self._backend.add, self.external_port, self.internal_port, self.lease, self.description), 6) or self.lease
                if self.result.detail:
                    self._set(replace(self.result, detail=""))
            except asyncio.CancelledError:
                raise
            except Exception as error:                                 # noqa: BLE001 - keep trying; say so
                self._set(replace(self.result, detail="renewal failed: " + type(error).__name__))
                lease = 60

    async def close(self):
        """Stop renewing and remove the mapping (bounded to about two seconds)."""
        renewal, self._renewal = self._renewal, None
        if renewal is not None:
            renewal.cancel()
            await asyncio.gather(renewal, return_exceptions=True)
        backend, self._backend = self._backend, None
        if backend is None:
            return
        try:
            await asyncio.wait_for(asyncio.to_thread(backend.delete, self.external_port, self.internal_port), 3)
        except (Exception, asyncio.TimeoutError):                      # noqa: BLE001 - the lease expires by itself
            pass


__all__ = ["MESSAGES", "MappingResult", "PortMapper", "address_problem", "default_gateway", "find_service", "natpmp_request",
           "parse_proc_net_route", "parse_route_print", "soap", "ssdp_discover"]
