"""Automatic router setup against a fake UPnP gateway (HTTP + SSDP on loopback) and a fake NAT-PMP gateway (UDP on loopback).
Nothing here reaches a real router or the Internet: the SSDP search goes to a loopback responder and the gateway is given."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
import socket
import struct
import threading
import time
import unittest
from xml.sax.saxutils import escape

from emerald_multiplayer.port_mapping import (
    CGNAT, CONFLICT, DOUBLE_NAT, MAPPED, NO_GATEWAY, NO_ROUTER_SUPPORT, PortMapper, address_problem, parse_proc_net_route,
    parse_route_print, ssdp_discover,
)

SERVICE = "urn:schemas-upnp-org:service:WANIPConnection:1"


class FakeGateway:
    """A UPnP IGD: device description, a WANIPConnection control point and an SSDP responder, all on 127.0.0.1."""

    def __init__(self, external="81.2.69.160", add_errors=(), location_host=None, conflict_client=None):
        self.external, self.add_errors, self.conflict_client = external, list(add_errors), conflict_client
        self.calls = []
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                body = ('<?xml version="1.0"?><root xmlns="urn:schemas-upnp-org:device-1-0"><device><deviceList><device>'
                        '<deviceList><device><serviceList><service>'
                        f'<serviceType>{SERVICE}</serviceType><controlURL>/ctl/IPConn</controlURL>'
                        '</service></serviceList></device></deviceList></device></deviceList></device></root>').encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                data = self.rfile.read(int(self.headers["Content-Length"])).decode()
                action = self.headers["SOAPAction"].strip('"').split("#")[1]
                arguments = dict(re.findall(r"<(New\w+)>([^<]*)</New\w+>", data))
                gateway.calls.append((action, arguments))
                if action == "AddPortMapping" and gateway.add_errors:
                    code = gateway.add_errors.pop(0)
                    return self.reply(500, f"<s:Fault><detail><UPnPError><errorCode>{code}</errorCode>"
                                           f"<errorDescription>fake</errorDescription></UPnPError></detail></s:Fault>")
                if action == "GetSpecificPortMappingEntry":
                    return self.reply(200, f'<u:{action}Response xmlns:u="{SERVICE}"><NewInternalPort>{arguments["NewExternalPort"]}'
                                           f'</NewInternalPort><NewInternalClient>{escape(gateway.conflict_client or "")}'
                                           f'</NewInternalClient><NewLeaseDuration>0</NewLeaseDuration></u:{action}Response>')
                fields = f"<NewExternalIPAddress>{gateway.external}</NewExternalIPAddress>" if action == "GetExternalIPAddress" else ""
                self.reply(200, f'<u:{action}Response xmlns:u="{SERVICE}">{fields}</u:{action}Response>')

            def reply(self, status, inner):
                body = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
                        f"{inner}</s:Body></s:Envelope>").encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http_thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.http_thread.start()
        self.ssdp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ssdp.bind(("127.0.0.1", 0))
        self.ssdp.settimeout(.1)
        self.location = f"http://{location_host or '127.0.0.1'}:{self.http.server_address[1]}/rootDesc.xml"
        self.searches = []
        self.running = True
        self.ssdp_thread = threading.Thread(target=self._answer, daemon=True)
        self.ssdp_thread.start()

    @property
    def ssdp_target(self):
        return self.ssdp.getsockname()

    def _answer(self):
        while self.running:
            try:
                data, address = self.ssdp.recvfrom(2048)
            except (TimeoutError, socket.timeout, OSError):
                continue
            self.searches.append(data)
            if b"InternetGatewayDevice:1" in data:
                self.ssdp.sendto(("HTTP/1.1 200 OK\r\nCACHE-CONTROL: max-age=120\r\nST: urn:schemas-upnp-org:device:"
                                  f"InternetGatewayDevice:1\r\nLOCATION: {self.location}\r\n\r\n").encode(), address)

    def actions(self, name):
        return [arguments for action, arguments in self.calls if action == name]

    def close(self):
        self.running = False
        self.ssdp_thread.join(1)
        self.ssdp.close()
        self.http.shutdown()
        self.http.server_close()


class FakeNatPmp:
    def __init__(self, external="81.2.69.161", result=0):
        self.external, self.result = external, result
        self.requests = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(.1)
        self.running = True
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    @property
    def port(self):
        return self.sock.getsockname()[1]

    def _serve(self):
        while self.running:
            try:
                data, address = self.sock.recvfrom(64)
            except (TimeoutError, socket.timeout, OSError):
                continue
            self.requests.append(data)
            if data[:2] == b"\0\0":
                self.sock.sendto(struct.pack(">BBHI", 0, 128, self.result, 1) + socket.inet_aton(self.external), address)
            elif data[1] == 2:
                _, _, _, internal, external, lifetime = struct.unpack(">BBHHHI", data)
                self.sock.sendto(struct.pack(">BBHIHHI", 0, 130, self.result, 1, internal, external, lifetime), address)

    def close(self):
        self.running = False
        self.thread.join(1)
        self.sock.close()


def silent_udp_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ParsingTests(unittest.TestCase):
    def test_default_gateway_from_linux_and_windows_route_tables(self):
        linux = ("Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
                 "eth0\t00000000\t0101A8C0\t0003\t0\t0\t100\t00000000\t0\t0\t0\n"
                 "wlan0\t00000000\t0100000A\t0003\t0\t0\t600\t00000000\t0\t0\t0\n"
                 "eth0\t0001A8C0\t00000000\t0001\t0\t0\t100\t00FFFFFF\t0\t0\t0\n")
        self.assertEqual(parse_proc_net_route(linux), "192.168.1.1")
        windows = ("===========================================================================\r\n"
                   "IPv4 Route Table\r\n=========================================================================\r\n"
                   "Active Routes:\r\nNetwork Destination        Netmask          Gateway       Interface  Metric\r\n"
                   "          0.0.0.0          0.0.0.0      192.168.1.1     192.168.1.20     35\r\n"
                   "          0.0.0.0          0.0.0.0       10.0.0.1       10.0.0.7         25\r\n"
                   "        127.0.0.0        255.0.0.0         On-link         127.0.0.1    331\r\n")
        self.assertEqual(parse_route_print(windows), "10.0.0.1")
        self.assertIsNone(parse_route_print("Aktive Routen:\nKeine\n"))
        self.assertIsNone(parse_proc_net_route("Iface\tDestination\n"))

    def test_the_routers_own_address_reveals_cgnat_and_double_nat(self):
        self.assertEqual(address_problem("100.72.1.2"), CGNAT)
        self.assertEqual(address_problem("192.168.0.5"), DOUBLE_NAT)
        self.assertEqual(address_problem("10.1.1.1"), DOUBLE_NAT)
        self.assertIsNone(address_problem("81.2.69.160"))
        self.assertIsNone(address_problem(None))


class UpnpTests(unittest.IsolatedAsyncioTestCase):
    def gateway(self, **options):
        gateway = FakeGateway(**options)
        self.addCleanup(gateway.close)
        return gateway

    def mapper(self, gateway, port=7777, **options):
        values = dict(ssdp_target=gateway.ssdp_target, gateway="127.0.0.1", natpmp_port=silent_udp_port(), budget=2.0)
        values.update(options)
        return PortMapper(port, **values)

    async def test_a_upnp_router_maps_the_port_reports_its_address_and_removes_it_on_close(self):
        gateway = self.gateway()
        changes = []
        mapper = self.mapper(gateway, on_change=changes.append)
        result = await mapper.start()
        self.assertEqual((result.code, result.method, result.external_address, result.external_port), (MAPPED, "upnp", "81.2.69.160", 7777))
        self.assertTrue(result.ok)
        self.assertIn("81.2.69.160:7777", result.message)
        add = gateway.actions("AddPortMapping")[0]
        self.assertEqual((add["NewExternalPort"], add["NewInternalPort"], add["NewProtocol"], add["NewInternalClient"]),
                         ("7777", "7777", "TCP", "127.0.0.1"))
        self.assertEqual(add["NewLeaseDuration"], "3600")
        self.assertEqual(changes[-1], result)
        await mapper.close()
        self.assertEqual(gateway.actions("DeletePortMapping"), [{"NewRemoteHost": "", "NewExternalPort": "7777", "NewProtocol": "TCP"}])

    async def test_the_lease_is_renewed_while_hosting(self):
        gateway = self.gateway()
        mapper = self.mapper(gateway, lease=2)
        result = await mapper.start()
        self.assertEqual(result.lease_seconds, 2)
        async with asyncio.timeout(5):
            while len(gateway.actions("AddPortMapping")) < 2:
                await asyncio.sleep(.05)
        await mapper.close()

    async def test_a_router_that_only_allows_permanent_mappings_gets_one(self):
        gateway = self.gateway(add_errors=[725])
        mapper = self.mapper(gateway)
        result = await mapper.start()
        self.assertEqual((result.code, result.lease_seconds), (MAPPED, 0))
        self.assertEqual([call["NewLeaseDuration"] for call in gateway.actions("AddPortMapping")], ["3600", "0"])
        self.assertIsNone(mapper._renewal)
        await mapper.close()
        self.assertEqual(len(gateway.actions("DeletePortMapping")), 1)

    async def test_a_port_already_forwarded_to_another_device_is_a_conflict(self):
        gateway = self.gateway(add_errors=[718], conflict_client="192.168.1.77")
        result = await self.mapper(gateway).start()
        self.assertEqual(result.code, CONFLICT)
        self.assertIn("another device", result.message)

    async def test_our_own_earlier_mapping_is_accepted(self):
        gateway = self.gateway(add_errors=[718], conflict_client="127.0.0.1")
        result = await self.mapper(gateway).start()
        self.assertEqual(result.code, MAPPED)

    async def test_a_cgnat_or_double_nat_router_is_reported_as_such(self):
        for external, code, words in (("100.72.1.2", CGNAT, "carrier-grade NAT"), ("192.168.0.5", DOUBLE_NAT, "another router")):
            with self.subTest(code=code):
                gateway = self.gateway(external=external)
                mapper = self.mapper(gateway)
                result = await mapper.start()
                self.assertEqual((result.code, result.external_address), (code, external))
                self.assertFalse(result.ok)
                self.assertIn(words, result.message)
                self.assertIn("relay", result.message)
                await mapper.close()

    async def test_a_device_pointing_at_another_machine_is_ignored(self):
        gateway = self.gateway(location_host="127.0.0.2")
        self.assertEqual(await asyncio.to_thread(ssdp_discover, .5, target=gateway.ssdp_target), [])

    async def test_the_search_asks_for_internet_gateways(self):
        gateway = self.gateway()
        self.assertEqual(await asyncio.to_thread(ssdp_discover, .5, target=gateway.ssdp_target), [gateway.location])
        self.assertTrue(any(b'MAN: "ssdp:discover"' in search for search in gateway.searches))


class NatPmpTests(unittest.IsolatedAsyncioTestCase):
    def silent_ssdp(self):
        return ("127.0.0.1", silent_udp_port())

    async def test_without_upnp_nat_pmp_maps_the_port_and_removes_it(self):
        fake = FakeNatPmp()
        self.addCleanup(fake.close)
        mapper = PortMapper(7777, ssdp_target=self.silent_ssdp(), gateway="127.0.0.1", natpmp_port=fake.port, budget=2.0)
        result = await mapper.start()
        self.assertEqual((result.code, result.method, result.external_address, result.external_port, result.lease_seconds),
                         (MAPPED, "natpmp", "81.2.69.161", 7777, 3600))
        mapping = [request for request in fake.requests if request[1] == 2][0]
        self.assertEqual(struct.unpack(">BBHHHI", mapping), (0, 2, 0, 7777, 7777, 3600))
        await mapper.close()
        removal = [request for request in fake.requests if request[1] == 2][-1]
        self.assertEqual(struct.unpack(">BBHHHI", removal), (0, 2, 0, 7777, 0, 0))

    async def test_nat_pmp_reports_cgnat(self):
        fake = FakeNatPmp(external="100.80.0.9")
        self.addCleanup(fake.close)
        result = await PortMapper(7777, ssdp_target=self.silent_ssdp(), gateway="127.0.0.1", natpmp_port=fake.port,
                                  budget=2.0).start()
        self.assertEqual(result.code, CGNAT)

    async def test_a_router_without_automatic_setup_is_reported_quickly_and_never_raises(self):
        started = time.monotonic()
        result = await PortMapper(7777, ssdp_target=self.silent_ssdp(), gateway="127.0.0.1", natpmp_port=silent_udp_port(),
                                  budget=1.5).start()
        self.assertEqual(result.code, NO_ROUTER_SUPPORT)
        self.assertLess(time.monotonic() - started, 5)
        self.assertIn("7777", result.message)

    async def test_no_gateway_is_its_own_answer(self):
        result = await PortMapper(7777, ssdp_target=self.silent_ssdp(), find_gateway=lambda: None, budget=1.0).start()
        self.assertEqual(result.code, NO_GATEWAY)


if __name__ == "__main__":
    unittest.main()
