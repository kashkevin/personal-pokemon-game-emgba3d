# Update 30 addendum — the in-game main menu, saved servers and automatic character loading

Everything below was built and measured in the cloud: Linux, a virtual X display, **software rendering, no GPU**, a single machine
standing in for several PCs (separate private folders) and a placeholder child process standing in for the game. Nothing here is a
real-PC, real-GPU, real-network or real-controller result. The Windows CI run (see the final report) adds the menu window on real
Windows with a software renderer; it still has no GPU, no second PC and no controller.

## What the player sees

`EmeraldTogether.exe` opens the menu **in the game's own window**: the packaged game executable started with `--shell` (the
Classic 2D game when the package has one — it needs nothing from the graphics driver — otherwise the 3D game). The window shows the custom
EmeraldTogether theme (the launcher's green, the game's own latin font, nothing from the GBA's menus or windows) and has exactly
these choices:

| Choice | What it does |
|---|---|
| **Continue Adventure** | starts the adventure played last (a hosted world or a joined server), loading its character; off, with the reason, when there is nothing yet |
| **New Game** | a new private adventure world on this PC (hosted on this PC only), with a new character; asks before it does anything when an adventure already exists, and never touches the existing ones |
| **Host Server** | the saved worlds on this PC (name, host, port, last hosted) and **Create New Server World** |
| **Join Server** | the saved servers (name, address, your character's name and state) and **Join New Server** |
| **Settings** | Native 3D / Classic 2D, display, audio, controls (rebinding in the menu), characters on this PC, multiplayer, game files |
| **Exit** | closes the program |

There is no separate server-setup program, launcher window or second setup step. The earlier Tk launcher window is kept only as a
fallback that opens when the menu window itself cannot (no display, a game that fails its pinned check); it is not part of the normal
path. Mouse, keyboard (Up/Down, Enter, Esc, Tab, PageUp/PageDown, Ctrl+V to paste, F11 fullscreen) and a game controller's D-pad, A and B
work in the menu; the controller input is untested on hardware.

### Host Server

* The list holds every world in the private storage, found by its stable world ID. Choosing one opens its page: **Host This World**,
  **Server Information**, **Invite codes for friends**, **Network settings**, **Rename world**.
* **Host This World** starts it straight away. The same checks as before run (installed game's pins, the world's certificate and database,
  the authenticated connection, closed-game recovery) and the host's own saved character **loads by itself**: no character is selected,
  imported or re-created. A world is only ever opened, never reset, by a restart.
* **Create New Server World** asks for a world name, your name, a port, the network (this PC only, or one of this PC's local addresses),
  Internet access (off; turning it on asks first), an optional public address or host name and — once, because the game build requires an
  explicit choice and has no default — the trade friendship rule. It creates a world with a stable world ID, its own database, certificate
  and keys under `worlds/<folder>/`, and four accounts (the host and three friends). Creating a world never overwrites or deletes another;
  names and ports must differ from the worlds already there.
* The **first time** into a world the host's character does not exist yet. The menu says so once and then runs the game's ordinary New Game
  (name and starter, then SAVE and close the game), registers that character with the world and opens the game on it — see
  *First-time characters* below. It is saved and linked to the host account automatically.

### Join Server

* **Join New Server**: paste the invite code the host sent (or the path of an invitation file). The address and port in the code are filled
  in and can be overridden. The program resolves a host name, completes a TLS handshake with the server and accepts it only if its
  certificate is the one **pinned in the invite**; the pinned certificate belongs to one world, so a different PC at the same address, or a
  different world on the same PC, is refused ("not this world"). Then the server is saved and joined.
* **Saved servers** list name, address:port, the account's name and whether the character exists. Choosing one offers **Join**,
  **Edit name or address** and **Remove this shortcut**.
* **Joining a saved server** checks the world first. If the host is offline, the message says so and offers *Try again*, *Edit the address*
  or *Back*: **nothing is created, reset or rewritten because a server is down**. When the server answers, the session starts and the account's
  character loads.
* **A changed host address** is followed by editing the shortcut (or by pasting a newer code); the world ID and player ID do not change, so the
  character stays linked.
* **Removing a shortcut** removes the shortcut only. The character, its saves and its private invitation copy stay; pasting the same code
  again links back to the same character.

### Server Information

For a host, from the world's page and from the session window while hosting: the world name, the port, the address it listens on, this PC's
local addresses (with the port), the public address or host name **only if the host typed one** (shown as "set by you, not checked"), whether
Internet access is on, whether the world is being hosted now, a **Copy address** row and the invite codes. The guidance is deliberately plain:
friends on the same network use the local address; friends elsewhere need the host's public address and the port opened on the router.
EmeraldTogether **does not open ports, traverse NAT, use UPnP or relay connections**, and the screen says so. It never invents a public IP.

### Settings

Graphics mode (Native 3D / Classic 2D; saved, applied the next time a game starts, unchanged by a failed 3D check), resolution, display mode and
quality, the two volumes, keyboard keys (press-a-key rebinding with swap on conflict; F1–F12 and Esc stay reserved; there is no fast-forward
action — see the 2× speed note below), a list of the characters on this PC with their state, the trade friendship rule for new worlds,
and the game files (verification; import of the player's own game when the package carries the release patch).

### During a session

The game opens in its own window (the same executable and renderer as before). The menu window stays open as a small **session window**
beside it: status, **Save now**, the autosave switch, the recovery actions that exist (interrupted battle, host restart, trade
recovery) when they apply, and **Server Information / Invite codes** for a host. Closing the game ends the session and the menu returns to
the main menu. Closing the session window while the game runs does not stop the game: the program waits until the game is closed.
This is a hand-over, not a single window: the menu process and the game are two windows of the same executable.

## First-time characters

A character is the account's canonical save; it is created with the game's own New Game and enrolled by the existing, unchanged enrollment
path. The menu removes the selecting and importing:

1. The game opens on a new private save; the player chooses a name and starter, saves and closes the game (`DraftRuntime`).
2. The source is approved for **this account**: the host's own PC does it for the host (`host_enrollment`); a friend's PC sends it to the
   host's server over the world connection (new messages `enrollment_status/begin/chunk/commit`, `enrollment_protocol.py`). The **server decides**:
   the sender is the authenticated account of the session, the account must have no character and no different source, the bytes must be a valid
   legacy save with no assigned owner identities and not the source of another account. The host can turn this off per world (Network
   settings, "New players create their character"); the host's own PC can always enroll.
3. The game opens once more on that save; the player chooses CONTINUE and, at the first safe place outside menus and battles, the first checkpoint
   is made (the old "Finish enrollment" button is replaced by retrying every 1.5 s) and the game closes by itself.
4. The session starts as that character. From then on every start loads it with no steps at all.

A game closed too early, a refused source, a source used by another account, an interrupted attempt or a lost connection stop with their own
message and keep the private files; an earlier created character is resumed rather than created again. The sequence involves three short game windows
(create, finish, play); that is the cost of reusing the verified enrollment path unchanged.

## Identity, data locations and old saves

* **World** = its stable world ID (a UUID created with the world, bound into its certificate). **Account** = its stable player ID. Neither
  changes with the world's name, the host's address, the port or a trainer's name.
* Per world and account, on the PC that plays it: `players/<world_id>/<player_id>/` holds the character (`character.sav`, recovery journals,
  launcher settings) and, for a friend, the private invitation copy (`invitation.json`, mode 0600, created once, never replaced; a
  different invitation for the same account is refused). The same account in another world is another folder; another account in
  the same world is another folder.
* The menu's own records are in `shell/` (`worlds.json` names and network settings, `servers.json` saved servers, `characters.json` the links,
  `preferences.json`, `migration.json`). They hold **no credential, certificate or save**. Writes are atomic (temporary file, flush, rename)
  and keep the previous version as `.bak`; a record that cannot be read and has no usable backup is reported and never overwritten.
* Everything lives under the launcher's private folder (`%LOCALAPPDATA%\PokemonPrivate\launcher\` on Windows).
* **Old saves.** The earlier launcher's worlds, characters, invitations and `launcher-recent.json` are read, never moved or rewritten (a copy of
  `launcher-recent.json` goes to `shell/backups/` first). Worlds are listed by ID with a name made from the host ("Kevin's world"); characters
  are found where they already are; invitations the player used become saved servers (the original file is left where it is); the last
  session and the world play times drive Continue Adventure. Only unambiguous matches are imported: a conflicting invitation or a second folder
  claiming a registered world ID is left alone and listed under Settings, Characters. Re-running changes nothing.

## Invite codes

`ET1-…` (about 270 characters) is a friend's private invitation without the host's certificate: world and account IDs, the account's name, its
**sign-in credential**, the game build, the **SHA-256 pin of the host certificate**, and the address and port the host chose, with a CRC-32 that
catches mistyped characters. The game fetches the certificate from the server on the first connection and accepts it only if its hash
equals the pin. **A code is a password for that account**: send each friend only their own and only privately. It carries no certificate or
private key. This is the only mechanism for a first connection (every account has its own credential, so an address and a port alone cannot
sign in); it was implemented and is covered by tests, including a real TLS server.

## Networking: what is and is not supported

Supported: TCP with TLS 1.2+ and a pinned certificate; numeric IPv4 loopback, private-LAN and public addresses (IPv6 literals pass validation
but were not tested); host names in saved servers and invite codes (resolved on the joining PC at each connection; the pinned certificate, not the
name, identifies the host); one world per port; hosting on this PC only, on a local address, or — by the host's choice — with Internet access
on a port the host forwarded.
Not supported, and not claimed: automatic port forwarding, UPnP, NAT traversal, relay servers, server discovery, accounts or identities
beyond the world's four, spectators. Internet play needs the host's router and firewall set up by the host.

## 2× speed

The player-facing speed-up is gone (settings, keyboard binding, controller trigger, the controls page); nothing in multiplayer
synchronisation or battle timing changed. Details in [update30-gameplay.md](update30-gameplay.md).

## Tests

| File | What it covers |
|---|---|
| `tests/test_shell_app.py` | main menu structure, Continue off with its reason, close handling, Create New Server World, first-time host creation then automatic load, restart never resets a world, second world and switching, name/port refusals, Server Information honesty, New Game (confirmation, never overwrites), settings pages (graphics persistence, display, audio, controls with swap, no 2×), damaged-record handling, no launcher toolkit loaded |
| `tests/test_shell_join.py` | real TLS server: invite code and file path, saved server and link, automatic load next time, two friends, one player in two worlds, bad codes, offline then retry with nothing created, wrong world at the address, edited address, removed shortcut and re-add |
| `tests/test_shell_e2e.py` | real worlds and servers with real enrollment (host local, friends remote): three accounts, three sources, three checkpoints, every save names its own account, per-PC folders, reconnect, rehost, two players on one PC, no duplicate characters |
| `tests/test_shell_migration.py` | earlier launcher data found without touching a byte, Continue picks the last session, idempotent, hosting an old world, conflicts left alone and reported |
| `tests/test_character_creation.py` | remote enrollment against the real server: acceptance, the same source for a second account, two friends, owned/invalid sources refused, safe-place retry, game closed early, server down, host turned it off |
| `tests/test_invite_code.py`, `tests/test_shell_records.py` | the code format, tolerance and rejection, certificate fetch and pin check; stores, links and shortcuts |
| `tests/test_shell_window.py` | the real window on a virtual display: drawing, theme pixels, keyboard, typing, paste of a long code, key capture, scrolling, resize, end on EOF, close |
| `tests/test_personal_storage_isolation.py` | two players in one world keep separate heads, eggs, reconnect and restart; profile folders never collide |
| engine `tools/pc_port/tests/test_shell_protocol.c` | the line protocol's split and escapes |

Skipped tests are reported as skipped (the window tests skip when the engine binary or Xvfb is missing); they are never counted as passes.

## Not verified (needs a real PC or people)

A real GPU and real DPI scaling of the menu; a game controller in the menu; two physical PCs on a LAN; Internet play through a router; the real
New Game → enrollment sequence with the real game on Windows (the cloud tests use a placeholder game and the save-mailbox fixture);
clipboard behaviour of the player's chat client; IPv6; the package on a clean PC. The manual checklist is in the final report.
