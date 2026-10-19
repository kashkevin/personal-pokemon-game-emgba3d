# Create World crashed with "invalid world record" (2026-10-19)

The owner installed the Windows build of 2026-10-19 (`EmeraldTogether-Setup-EmeraldTogether-2026-10-19-visual-repairs.exe`,
windows-package run 39180878911) and Host World > Create World failed with `ValueError: invalid world record`:
shell_app.py lines 256, 393, 932, 801, 732; world_registry.py 226, 144, 96; shell_store.py 85. Those line numbers are the
merged defaults' source exactly (app `d7dbe1c`).

## Root cause

`launcher_worlds.lan_addresses()` returns this PC's local-network and VPN addresses as `LocalAddress` values: a `str`
subclass carrying the address's kind and label (added on 2026-10-18 in `5a6990d`, "labelled addresses"). Three places check
for exact `str` with `type(value) is str`, which a subclass fails:

- the world list's validator (`world_registry._validate`, the `bind_address` check);
- a world's endpoint when it is created (`invitations._endpoint`, called by `HostWorld.create`);
- invite codes (`invite_code.valid_address`).

The Create World form starts on the first local-network address, a `LocalAddress`. So on any PC with a network:

| What the player did | What happened |
| --- | --- |
| Create World, network left as it was | `HostWorld.create` refused the endpoint. The menu said "Character setup could not complete" (the generic message of `launcher_setup`). Nothing was created. |
| Create World with a numeric public address typed in | The world uses the public address as its endpoint (plain text), so it was **created on disk**. Then `register()` saved the `LocalAddress` as `bind_address`, and `_validate` raised `invalid world record`: the reported traceback. |
| Back at the main menu, same session | The main menu lists worlds with `entries(default_bind=<LocalAddress>)`. That found the new, unlisted folder and tried to add it with the same address, so it failed again ("Something went wrong") every time the main menu drew, until the window was closed. |
| Next start | The start-up import lists unknown folders with `127.0.0.1` (plain text), so the left-over world appeared as "<host>'s world", listening on this PC only. |
| Hosting after the PC's address changed, LAN invite codes | Failed the same way (`configure(bind_address=<LocalAddress>)`, `encode_invite`). |

Choosing the network from the picker worked by accident: that answer comes back from the game's menu window as text.

**Why the tests missed it.** Every menu test gave the menu plain strings (`lan=lambda: ["192.168.1.20"]`). With
`LocalAddress` values, as a real PC returns them, 29 existing menu tests fail on the old code.

**Not a save-migration problem.** The world list's format (`emerald-shell-worlds-v1`) did not change, a list written by the
previous release loads byte-identical (test), and nothing in the reported path reads old data. The crash happens on a
completely fresh profile.

## Repair (app `04f5778`)

- `ShellApp.lan()` takes the addresses as plain text and keeps each one's kind for Server Information.
- `WorldRegistry` copies text out of any `str` subclass when it builds or changes a record (`register`, `configure`, the
  listing). Validation stays strict: a number, a host name as listen address, an empty name and so on are still refused,
  now as `WorldRegistryError` naming the setting ("the address to listen on is not a numeric address of this PC").
- Create World checks the record before anything is made (`check_new`), so a world the list cannot take is refused with a
  readable message and no folder is left behind. If the list still cannot be saved afterwards (a full disk), the menu
  says the world was made, keeps it, and the next listing adds it.
- A listing never fails because a found folder could not be saved: the folder stays untouched and is shown as needing
  attention.
- An earlier launcher's remembered address is used as listen address only if it is a numeric address.
- The menu shows any `WorldRegistryError` as "A world setting could not be saved" with the reason, never as a crash. A
  start-up import failure no longer stops the menu from opening.
- World creation failures no longer say "Character setup"; the cause goes to `shell/last-error.txt`.

**Existing data.** Nothing is moved or rewritten. A world left behind by the crash is listed as "<host>'s world" and can be
renamed, opened to the network (Network settings, Listen on) or deleted.

## Tests

- The menu fixtures now return real `LocalAddress` values (`tests/shell_fixture.py`, `lan_of`).
- `tests/test_world_creation.py`, 18 tests (17 fail on the old code): create on the default network and with a public address,
  host name and this-PC-only; save, reopen, host, address change while hosting, rename, Listen on, invite code, delete;
  the world the crash left behind; an earlier launcher's worlds and characters; a VPN address first; the world limit; a
  failed save; readable refusals; strict validation; the previous release's list file.

Whole app suite under Xvfb: 5008 cases (JUnit, subtests included), 4888 passed, 119 skipped, 1 failed: a classic-launcher
Tk test that fails about 3 runs in 5 on the code before this fix too (KNOWN_ISSUES WC-5). The python-tests CI passed on
every pushed commit.

## On Windows

`scripts/windows-runtime/ci_world_check.py` installs a Setup file silently on a fresh GitHub-hosted Windows runner (a
temporary profile), starts the installed `EmeraldTogether.exe` and plays its menu window with keyboard messages posted to
that window. It reads the results from the files the installed launcher writes, the clipboard and the process list.
`.github/workflows/installed-world-check.yml` runs it on the old and new installers; every full `windows-package` build runs
it on its own installer.

**The reported crash, reproduced** (installed-world-check run 39192332500, the installer from run 39180878911,
SHA-256 `800795c1f0aa097e2c1837b639fb472edce8b286e4c02c4321679df6f300ab1e`, runner addresses 10.1.0.112 and 172.17.80.1):

1. Default network: the world was refused and nothing was created.
2. Public address: the world was created on disk and `shell/last-error.txt` recorded the owner's traceback, line for line
   (shell_app.py 256, 393, 932, 801, 732; world_registry.py 226, 144, 96; shell_store.py 85; `ValueError: invalid world record`).
3. Back at the main menu the listing failed again (`registry.entries`).

**The new build** (windows-package run 39191926490 from app `9d11e7a`, which carries the fix `04f5778`; installer
`EmeraldTogether-Setup-EmeraldTogether-2026-10-19-world-fix.exe`, SHA-256
`c84649c15a5d2365a89c55165c1086f37821efb2909dc8c19fadd2709c092fff`), installed-world-check run 39193466499, three steps on
one fresh runner (local-network addresses 10.1.1.36 and 172.21.160.1):

| Step | Profile | Result |
| --- | --- | --- |
| 1. Old installer (run 39180878911) | new | The three failures above, again; then its program folder was deleted by hand, as the owner did, and its data kept |
| 2. New installer | **left by step 1** (the character, the remembered rule, the world the crash left on disk, last-error.txt) | Create World on the default network: listed, listening on 10.1.1.36:7778, certificate endpoint 10.1.1.36; an invite code copied from the menu decodes to 10.1.1.36:7778 and that world; renamed (same world ID); a world with public address 81.2.69.160: listed, listening on 10.1.1.36, endpoint 81.2.69.160; deleted (folder in worlds-deleted); Host this world now: the world was prepared and the game started for the character and loaded its save; started again: the worlds kept, Exit closed it with code 0; no error recorded |
| 3. New installer | completely new | The same, on port 7777 |

Port 7778 in step 2: 7777 belongs to the world the crash left behind, which the new build listed at start.

**The final build from the merged defaults** (app `f136689`, engine `47767264`): windows-package run 39195679171, installer
`EmeraldTogether-Setup-EmeraldTogether-2026-10-19-world-fix.exe`, SHA-256
`fd68a9fef11235bd2ec105a116c6ba9da4578f94ec1ff6dd42f7ffe2565da318`, artifact `EmeraldTogether-Windows-Installer` (ID 12162187817).
Its own installation check ran the world check on a fresh profile and passed. installed-world-check run 39197052414 repeated
the three steps with this installer and passed. The new log lines show the left-over world directly: "listed at start:
Tester's world (listens on 127.0.0.1)" and, after the restart, "kept: Tester's world" and "kept: CI Renamed World".

**What was not checked on Windows.** The runner has no graphics card: the game reports "Graphics unavailable (3D Diorama)",
as in every CI run. Hosting was followed up to the game opening for the character. Choosing CONTINUE in the game, the world
then listening on the local network for friends, and a friend joining are covered by the automated end-to-end tests
(`tests/test_shell_e2e.py`, real servers, now with `LocalAddress` values) but were not driven on the installed build.
Nothing here ran on the owner's PC.

## Checking on your PC

1. Install the new Setup over the old one (or after deleting it). Your characters and worlds in
   `%LOCALAPPDATA%\PokemonPrivate` are kept.
2. Host World > Create a new world, leave Network as it is, Create world. It should open the world's screen, not an error.
3. If you saw the crash before: a world named "<your name>'s world" is in the list. It is the one that was being created.
   Rename it, open it to your network (Network settings, Listen on), or delete it.
4. Invite codes for friends > a friend's row: the code should copy. Host this world now: the game should open on your
   character; choose CONTINUE, and once it has saved the world is hosted.
