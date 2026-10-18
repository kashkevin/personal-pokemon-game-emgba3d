# Networking: how friends reach a world, and how failures are explained

Player-facing version: `scripts/windows-runtime/resources/HOSTING.txt` (packaged beside the game). Root causes of the
reported failures ("Server cannot be reached", "No multiplayer link"): `docs/next-update-report.md`, section A.

## Options evaluated

| Option | Works behind | Needs | Decision |
| --- | --- | --- | --- |
| Direct connection, same network | any home | nothing | kept (default) |
| Direct connection over the Internet with a port forward | a router the host controls, no CGNAT | the router to forward one TCP port | kept; the game now asks the router itself (UPnP IGD / NAT-PMP) |
| VPN overlay (Tailscale, ZeroTier, ...) | CGNAT, any router | the overlay installed on every PC (free personal plans exist) | supported: overlay addresses (100.64.0.0/10) can be chosen as the world's address and are accepted by the host |
| Relay (the host and friends dial out to a third machine) | CGNAT, any router, locked-down networks | someone to run a small program on a reachable machine | **implemented** (`relay.py`); no public relay is provided |
| NAT hole punching / STUN + rendezvous | many NATs, not symmetric NAT or some CGNAT | a public rendezvous service, UDP or simultaneous TCP open | **not implemented**: it needs a hosted rendezvous service (which does not exist and would be invented infrastructure), it fails on exactly the networks where help is most needed (symmetric NAT, CGNAT), and the game's transport is TCP + TLS |

The simplest reliable combination is: direct for home networks, automatic router setup where the router allows it,
and, for everything else, a relay the players run themselves or a VPN overlay. None of this is presented as automatic:
the menu and HOSTING.txt say when a router or CGNAT still needs a person to act.

## What runs where

* **Host**: the world server runs inside the host's EmeraldTogether while the world is hosted
  (`LauncherSession`, `WorldServer`). A Solo or LAN world listens on its chosen address only; a world with Internet access,
  or on an overlay address, listens on all IPv4 interfaces (`0.0.0.0`, an explicit opt-in that requires TLS and a durable
  world store) and the host's own game connects over loopback (`LaunchRequest.options`).
* **Peer filter** (`WorldServer.peer_allowed`): loopback and private-network peers, and 100.64.0.0/10 (overlay VPNs; the
  documented decision is that an overlay admits only its owner's devices, and TLS plus the account credential still
  decide); any other public peer only when the world allows Internet connections. A refusal is sent as
  `rejected_public_exposure_disabled`, which the friend sees as "The world is not open to the Internet".
* **Automatic router setup** (`port_mapping.py`, standard library only): while a world allows Internet connections and
  the host has not turned it off (Network settings), the session asks the router for the world's TCP port: UPnP IGD
  (SSDP discovery, WANIPConnection/WANPPPConnection, AddPortMapping, GetExternalIPAddress) or NAT-PMP (RFC 6886) on the
  default gateway. It runs in the background (never blocks hosting), renews the lease and deletes the mapping when the
  session closes. The router's external address reveals CGNAT (100.64.0.0/10) and double NAT, which are reported.
  Result codes reach the session window as "Router: ...".
* **Relay** (`relay.py`, protocol ETR1, standard library only): the host's session runs a `RelayHostAgent` when a relay
  is set for the world. It holds the world's room on the relay (room = world UUID; token = HMAC-SHA256(world relay key,
  room)) and opens one outgoing data connection per announced friend, piped to a loopback-only listener of the world
  server (`start(relay=True)`). The friend's game runs the normal TLS handshake through the pipe and checks the pinned
  certificate exactly as on a direct connection, so the relay only ever carries ciphertext. Limits (defaults): 64 rooms,
  256 connections, 32 per address, 8 waiting and 8 active friends per room, 10 s preamble, 5 min idle, rooms kept 7 days
  after their host leaves. A refusal is one short line sent only after a completed TCP handshake (no amplification). The
  relay keeps nothing on disk.
  Run it: `EmeraldTogether.exe --relay-server [--port 7780]` (packaged game) or `python3 relay.py serve --port 7780`
  (any machine with Python 3.11+; the file has no dependencies).
* **Invite codes** (`invite_code.py`): version 2 codes carry an optional relay endpoint; codes without a relay stay
  version 1, so older games still read them. The version message is now correct in both directions.
* **Friend's route** (`network_settings.save_join_route`, `players/<world>/<account>/route.json`): direct or a relay.
  `Invitation.companion_config` reads it, so the game, the character's registration and every reconnect use the route
  that answered the menu's check.

## The connection check (never a launch as proof)

`connection_diagnostics.check_server` is the only check the menu runs for an invite code or a saved server, before
anything is started or saved:

1. the address is looked up (`dns_failed`);
2. TCP and TLS (`refused`, `timeout`, `unreachable`, `blocked`, `tls_failed`), directly or through the relay's room
   (`relay_unreachable`, `relay_host_offline`, `relay_busy`, `relay_failed`);
3. the host certificate must have the SHA-256 in the invite and be valid for the world (`wrong_world`,
   `certificate_invalid`); nothing is sent before this;
4. a hello **without any credential** asks whether the server talks to this game build (`version_mismatch`), or refuses
   players from outside the host's network (`rejected_public_exposure_disabled`). No lease, session or character is created.

`check_routes` tries the direct route first and the relay second. Every code has a title, an explanation and next steps
split into "Host:" and "You:" (`describe`). The menu shows them on the "Can't join" screen with Try again, Edit the
address and Back; nothing is created or reset.

During a session, "connected" comes only from the companion's own handshake (the server's welcome), never from the game
having started. The companion keeps the server's refusal code: a permanent refusal (version, identity, credential,
exposure, enrollment disabled) stops the reconnect loop and fails the session with its own code; transient failures keep
retrying; "already connected" and "full" are retried calmly. The session window shows "Connected to the host's world" or
"Not connected to the host's world right now"; a failed session names its diagnosed cause.

## Infrastructure, cost and security

* Nothing is hosted by the project. Direct and port-forwarded play cost nothing. Tailscale's personal plan is free
  (subject to its own terms and limits). A relay needs a machine with one reachable TCP port: a friend's PC with a
  port forward (free) or a small rented server (typically a few dollars or euros a month).
* Credentials: each invite code is one account's password (32 random bytes) plus the world's certificate pin. It never
  goes into the saved-server list; it is kept only in the account's private folder.
* The relay sees which rooms exist, the addresses that connect and how much they send, and can refuse or drop
  connections. It cannot read or change game traffic, sign in as anyone, or impersonate a world. The room token travels
  in the clear between the host and the relay: someone who can watch that traffic could take the room after a relay
  restart (a denial of service only); "New relay key" makes a new token.
* Automatic router setup asks only for the hosted world's port, only while Internet access is on, and removes it at the
  end of the session (if the router honours removal). It can be turned off per world.
* A leaked invite code cannot be revoked individually yet (KNOWN_ISSUES).

## Verification

Automated (one machine; separate private folders play the host and friends; real servers, real TLS): diagnostics for
every code (`tests/test_connection_diagnostics.py`, `test_connection_rejections.py`), host reachability
(`test_host_reachability.py`), router setup against a fake IGD and a fake NAT-PMP gateway (`test_port_mapping.py`), the
relay protocol, limits and abuse cases (`test_relay.py`), sessions meeting through a relay (`test_launcher_session.py`),
the menu's checks against a real server and a relay with the real character registration (`test_shell_join.py`,
`test_shell_e2e.py`).

**Not performed**: two real PCs on one home network, two PCs on different Internet connections, a real router's UPnP or
NAT-PMP, a real CGNAT line, Tailscale, a relay on a real VPS, Windows Firewall's first-run prompt. Reproducible
procedure for those: `docs/next-update-report.md`, section G.
