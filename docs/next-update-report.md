# EmeraldTogether next update: multiplayer, character persistence, installation, menu

Session of 2026-10-18. Baselines: app `27c43c7` (= `claude/emeraldtogether-combined-app`), engine `cf7cba76`
(= `claude/emeraldtogether-combined`). Work branches: app `claude/admiring-bohr-dpxzuy`, engine `claude/nu-engine`.
Nothing is merged into the default branches (section H).

**In short.** A player now installs with one Setup file, creates one character, and plays it Solo, in their own hosted
worlds and in friends' worlds; its Pokemon and progress go with it, and joining a friend no longer needs a second New Game
or hits "already started with a different character". The menu checks a friend's world (identity and game version) before
anything starts and names the real reason when it cannot connect; hosts get automatic router setup, Tailscale support and
an optional self-run relay. All of this is tested automatically on one machine, and the installer is built and
install/repair/uninstall-checked on a fresh Windows CI runner. **It has not been tried on two real PCs, across two Internet
connections, or by a person playing the real New Game and registration on a real PC** (section G).

---

## A. Root causes

Evidence lines refer to the baseline `27c43c7` unless noted.

### Character conflict: `CreationError: This account already started with a different character; its files were kept.`

* The message is `enrollment_conflict` (`character_creation.py:47`). The host's world store raises it when an account
  already has a *different* registered source that never reached a checkpoint (`ownership_storage.py:167`), or when a
  checkpointed account tries to enroll again (`:170`).
* A first source was registered as soon as the friend's game uploaded it. Any attempt that did not finish (the game closed
  early, a crash, a lost connection, the friend's PC restarted) left that source on the host. The next attempt made a
  **new** New Game, so its source differed and was refused for ever. The menu even offered "Create a different character
  instead" (`shell_app.py:815`), which could only conflict.
* A draft lost on the friend's side (another PC, a reinstall, a damaged link record) had the same effect, and a friend had
  no way to clear the host's record.
* A second bug blocked retries: the friend's own `invitation.json` in the account folder was treated as a leftover of an
  abandoned attempt, so a restart after a failure was refused (`enrollment_runtime.py`, fixed in `497f96a`).

### Solo character unusable for multiplayer

* A character belonged to one (world, account) pair. Solo was a private world on 127.0.0.1 with its own account and
  character. Joining a friend's world needed a new character made in that world with another New Game. The Solo character
  could not be brought along, and the second New Game ran straight into the conflict above.

### "Server cannot be reached" / "No multiplayer link"

* **Every network failure looked the same.** Fetching the host's certificate turned any failure into
  `certificate_unavailable` ("The server could not be reached ...", `invite_code.py:52,171,196`), and the menu replaced
  other exceptions with a generic sentence (`shell_app.py:1184`). In the game session, every server refusal became
  `server_rejected` (`companion.py:1332`) and a reconnect loop that ended in "The host did not respond". Version
  mismatches, a different world at the address, a world closed to the Internet and refused credentials were all
  invisible.
* **The host was hard to reach.** The world listened on one specific LAN address, never all interfaces; "Internet access"
  only relaxed the peer filter. Peers outside private ranges were refused unless Internet access was on, and
  100.64.0.0/10 (Tailscale, CGNAT) was always refused (`server.py:41-56`, `secure_transport.py`). There was no UPnP,
  NAT-PMP, relay or VPN support, so friends outside the host's home could connect only with a manual router port forward,
  and never behind CGNAT.
* **The world exists only while hosted.** Friends who tried while the host was not hosting (or was still creating their
  own character) were refused, with the same generic message.
* **"No multiplayer link"** is not a connection result: the engine's title and main menu showed "NO MULTIPLAYER LINK ·
  HOST AND JOIN ARE IN THE LAUNCHER" / "No multiplayer link. This window was started on its own" whenever the game had no
  multiplayer bridge (engine `ui_title.c:299`, `ui_main_menu.c:43-49`). The character-creation run (`--setup`) has no
  bridge by design, so every player saw it while creating a character and took it for a failed connection.

### Installation too complicated

* The packaged native game has all game data compiled in and never reads a GBA ROM, but the launcher still required
  `%LOCALAPPDATA%\PokemonPrivate\launcher\games\<sha>\game.gba` (`launcher_gui.py:180`): only for the build identity,
  capability markers and battle-message lengths. Installing it needed an import patch the CI never ships, so friends were
  asked for files, hashes and PowerShell steps.
* There was no installer: a ZIP, unsigned, with developer artifacts (`native-inputs`) beside the player's files.

### Confusing menu

* "New Game" created a new world *and* a new character; "Host Server" / "Join Server" each led to their own character
  flows; the same person ended up with several unrelated characters, and errors were developer sentences.

---

## B. Implemented fixes

App branch `claude/admiring-bohr-dpxzuy` (78 files, +10.9k / -1.4k lines since `27c43c7`); engine branch `claude/nu-engine`.

| Area | Behaviour now | Files |
| --- | --- | --- |
| Universal characters | One character library per PC; a character enters any world with its own save (detached from its previous world and verified); coming back registers the newer save as a new source generation; refusals change nothing. Design: `docs/universal-characters.md`. | `character_library.py`, `character_transfer.py`, `character_transfers.py`, `character_play.py`, `character_migration.py` (new); `ownership_storage.py`, `trade_storage.py`, `storage.py`, `server.py`, `enrollment_protocol.py`, `enrollment_runtime.py`, `live_checkpoint.py`, `launcher_setup.py`, `character_creation.py`, `host_world.py`, `wagers.py` |
| No more conflicts | An unfinished first source is replaced, not refused; retries are idempotent (the same character never registers twice); the friend's restart after a failure works. | `ownership_storage.enroll_player(replace_unconsumed)`, `enrollment_runtime.py`, `server.py` |
| Menu | Continue Adventure, Solo, Host World, Join Friend, Characters, Settings, Exit; world management (create, host, play Solo, invite codes, server information, network settings, rename, delete to `worlds-deleted/`); saved servers (join, edit address, remove); character management (create, choose, rename, back up, restore, delete to `characters-deleted/`, recover earlier attempts); plain messages with details in `shell/last-error.txt`. | `shell_app.py`, `world_registry.py` |
| Honest connections | One check before anything starts: pinned world identity, then the game version (hello without credentials), directly and via relay; each failure has a stable code, a plain title and host/friend steps. The session reports "connected" only after the server's welcome; permanent refusals stop the reconnect loop with their own code. | `connection_diagnostics.py` (new), `invite_code.py`, `server_check.py`, `companion.py`, `launcher_session.py`, `launcher_gui.py`, `secure_transport.py` |
| Reachability | Internet and VPN worlds listen on all IPv4 interfaces; Tailscale/overlay addresses accepted and offered; automatic router setup (UPnP IGD, NAT-PMP) while Internet access is on; optional relay (host agent, friend connector, server; `EmeraldTogether.exe --relay-server`); invite code v2 carries the relay; friends' route file. Design: `docs/networking.md`. | `port_mapping.py`, `relay.py`, `network_settings.py` (new); `server.py`, `launcher_worlds.py`, `saved_servers.py`, `invitations.py` |
| Installation | No game.gba needed: pinned game facts stand in for the ROM's identity data; `check_installation` explains missing or changed files in plain words (shown in Settings, Game files); Inno Setup installer (per user, no admin, Start menu, repair/upgrade in place, uninstaller never touches saves); CI builds it, ships the player artifact separately and checks install/start/repair/uninstall on a fresh runner. Details: `docs/windows-installation.md`. | `game_facts.py`, `installation_check.py` (new); `companion.py`, `launcher_gui.py`, `launcher_session.py`, `player_runtime.py`; `scripts/windows-runtime/build_launcher.py`, `ci_installer_check.py`, `installer/EmeraldTogether.iss`; `.github/workflows/windows-package.yml` |
| Engine text | The character-setup run says "CHARACTER SETUP · NEW GAME THEN SAVE AND CLOSE" and "Creating your character ..."; world sessions and games started on their own say so in the current menu's words. PC-only native UI; the GBA ROM is unchanged (`f214735b…3387`). | engine `src/native_ui/screens/ui_title.c`, `ui_main_menu.c` (`6cd8af0f`) |
| Player guides | QUICK-START.txt (rewritten for the new menu), HOSTING.txt (new), RELEASE-LIMITS.txt, README.txt. | `scripts/windows-runtime/resources/` |

Gameplay code was not changed: no engine game logic, no battle, trade or story code. The only engine change is the
PC-only text above.

---

## C. Save migration and recovery

Existing players keep everything; nothing is deleted or overwritten.

* **Characters**: at the first start of this version every world account with a readable save becomes a library character
  bound to that account; the draft an earlier attempt recorded becomes a character too; other drafts wait under
  Characters, "Recover a character". The original files stay byte-identical in their old places (tested).
* **Worlds**: existing worlds stay where they are and keep their identity, port, accounts and invite codes. The first time
  the host hosts an older world it gains the character-transfer capability after a verified backup beside the world
  (`<uuid>.before-character-transfers.sqlite3`). Earlier-launcher records (worlds, invitations, the last session) are
  imported as before; Continue Adventure falls back to them after an upgrade.
* **Coming back to a world**: the account's earlier save moves to `previous-saves/<UTC time>/` in the account folder.
* **History and restore**: each character keeps its earlier saves (40) and explicit backups; Characters, "Restore an
  earlier save" makes one current (the present one goes to history first).
* **Deletion**: characters go to `characters-deleted/`, worlds to `worlds-deleted/`, both under
  `%LOCALAPPDATA%\PokemonPrivate\launcher`.
* **Damage**: a changed or unreadable character save is reported and left alone; problems found during migration are
  listed on the Characters screen ("Left untouched").
* **Installer**: repairing, upgrading and uninstalling only touch the program folder; player data in
  `%LOCALAPPDATA%\PokemonPrivate` is never touched (checked by the CI installation job with a planted sentinel).

---

## D. Windows installation package

Built by the repository's CI (`.github/workflows/windows-package.yml`); the session cannot build Windows executables
locally (PyInstaller and Inno Setup run on Windows).

| Run | Mode | Commit | Result |
| --- | --- | --- | --- |
| [39162293580](https://github.com/kashkevin/personal-pokemon-game-emgba3d/actions/runs/39162293580) | smoke (synthetic game) | app `76a27ca` | success: installer built; fresh-runner silent install, file check, start, repair, uninstall passed |
| [39162322062](https://github.com/kashkevin/personal-pokemon-game-emgba3d/actions/runs/39162322062) | full (real game from engine `6cd8af0f`, expected ROM `f214735b…3387`) | app `76a27ca` | success: game built (ROM `f214735b…3387` verified), package audit, packaged game files verified, frozen menu starts, graphics-mode and in-game menu checks on the real packaged games, installer built; fresh-runner silent install, file check, start, repair, uninstall passed |

Where to get it: [run 39162322062](https://github.com/kashkevin/personal-pokemon-game-emgba3d/actions/runs/39162322062), **Artifacts**, `EmeraldTogether-Windows-Installer` (53.8 MB zip, expires 2026-10-25; artifact digest `sha256:a24d09dd…addf3`): it holds exactly
`EmeraldTogether-Setup-<version>.exe` and `QUICK-START.txt`. Artifacts are private to the repository and kept 7 days; they
are not a public release (no GitHub Release was made). The developer artifact `EmeraldTogether-windows-full` holds the ZIP,
hashes, audit and reports. The package contains no ROM, save or database; the game program has the game's content
compiled in, so it is a private build for friends who own Pokemon Emerald (RELEASE-LIMITS.txt). The installer is not
code-signed (SmartScreen warns; QUICK-START.txt explains). `bios.c` licensing remains an open question
(`docs/bios-licensing-review.md`).

---

## E. Friend installation guide

`scripts/windows-runtime/resources/QUICK-START.txt`, shipped next to the Setup file in the player artifact. In short:

1. Save `EmeraldTogether-Setup-<version>.exe` from your friend.
2. Double-click it. If Windows says "Windows protected your PC", click **More info**, then **Run anyway**. Click Next and
   Install (no administrator password).
3. Start EmeraldTogether from the Start menu. Allow it when Windows asks about the network.
4. Choose **Join Friend**, then **Join with an invite code**, paste the code your friend sent (Ctrl+V). The first time,
   create your character (the game opens on a New Game: pick a name and starter, save with START then SAVE, close the
   window). Then the game opens once on your character: choose CONTINUE.
5. Next time: **Continue Adventure**.

No GitHub, PowerShell, game file or emulator is needed.

---

## F. Multiplayer hosting guide

`scripts/windows-runtime/resources/HOSTING.txt` (installed in the program folder) for players; `docs/networking.md` for
the design. In short:

* **Same home**: Host World, create a world, "Invite codes for friends", send each friend their own code privately, "Host
  this world now", keep the game open.
* **Friends elsewhere**, one of:
  * *Port forwarding*: Network settings, Internet access on; the game asks the router (UPnP / NAT-PMP). If the router
    refuses, forward the world's TCP port by hand. Not possible behind CGNAT.
  * *Tailscale* (free personal plan): install on every PC, choose the 100.x.y.z address in Network settings, Listen on.
  * *Relay*: someone trusted runs `EmeraldTogether.exe --relay-server --port 7780` (a PC with that port forwarded) or
    `python3 relay.py serve --port 7780` on a small server (a few dollars or euros a month); the host sets it under Network
    settings, Relay, and makes new invite codes. No public relay is provided.
* Windows Firewall must allow EmeraldTogether on the host.

What still needs a person: a router that refuses automatic setup, CGNAT (Tailscale or a relay), running a relay.

---

## G. Test report

Environments: **auto** = automated tests in the cloud (Linux, Python 3.12, Xvfb), separate temporary private folders for
each "PC", real servers and TLS on loopback, the game process a placeholder child and the game's save mailbox the existing
fixture; **CI** = GitHub's Windows runner (no GPU); **runtime** = the real native game run here (Linux build, software
OpenGL). No test ran against a real user's save folder.

App suite at the final head `955851d`: **2234 passed, 0 failed**, 119 skipped (the mGBA bridge's Lua subtests: no Lua 5.3 in this container; one private-save-path test), 2605 subtests passed. Focused groups: shell/menu 61 + character 27
(including the end-to-end and relay runs); networking 131 + 142 subtests; installation 44 + 18 subtests; trial merge
226 + 191 subtests.

| # | Scenario | Automated | Runtime / CI | Cross-machine |
| --- | --- | --- | --- | --- |
| 1 | Fresh Windows installation | `test_build_installer`, `test_ci_installer_check` (simulated Inno Setup) | CI install-check job on a fresh windows-2022 runner with the real game: silent install, file hashes, start, uninstall (runs 39162293580 smoke and 39162322062 full: passed) | not performed on a real PC |
| 2 | Existing installation upgrade | `test_shell_migration` (earlier launcher data, byte-identical), `test_character_library` migration | CI: repair/upgrade in place over an installed copy (stray DLL removed, deleted file restored), sentinel data kept | not performed on a real PC |
| 3 | First character creation | `test_shell_app` (first start, one New Game ever), `test_shell_e2e` (simulated New Game, real registration) | runtime: setup-mode title and main menu screenshots show the new instructions | the real New Game sequence by a player: **not performed** |
| 4 | Solo save and reload | `test_shell_app` (Solo, then Continue Adventure on the next start), `test_shell_e2e` Solo round trip | - | not performed |
| 5 | Closing and reopening | restart tests in `test_shell_app`, `test_shell_migration`; `sync_from_worlds` (game ended while the menu was closed) in `test_character_play` | - | not performed |
| 6 | Joining with an existing Solo character | `test_shell_e2e::test_a_solo_character_joins_a_friends_world_without_a_second_new_game_or_a_conflict` (real registration) | - | **not performed** (two PCs) |
| 7 | Joining without a character | `test_shell_join::test_a_new_player_creates_one_character_then_joins_with_it`, `test_shell_e2e` | - | not performed |
| 8 | Repeated failed connection attempts | `test_shell_join` (server down, retry twice, back up; nothing changed), `test_shell_e2e` (down, then up, no duplicate) | - | not performed |
| 9 | Repeated character submissions | `test_character_creation`, `test_character_play` (retry never duplicates), `test_launcher_setup` (unfinished source replaced) | - | not performed |
| 10 | Multiple character records | `test_character_library`, `test_character_play` (two characters, one account), `test_shell_e2e` (two players on one PC) | - | - |
| 11 | Character identity conflicts | `test_character_play` (`pokemon_owned_here` refused, nothing changes), library `wrong_world` / `wrong_trainer`, `other_character_here` | - | - |
| 12 | Host creating and deleting worlds | `test_shell_app` (create with stable ID, delete asks first and moves to worlds-deleted) | - | - |
| 13 | Client joining from another computer | simulated: separate private folders on one machine, real TLS | - | **not performed** |
| 14 | Client from a different Internet connection | simulated: relay route with the direct port closed (`test_shell_e2e` relay test), fake routers (`test_port_mapping`) | - | **not performed** |
| 15 | Client disconnect and reconnect | `test_companion` (remote disconnect/reconnect epochs), `test_companion_live` (runtime reconnect keeps the lease), `test_launcher_session` | - | not performed |
| 16 | Host disconnecting | `test_emergency_save`, `test_admission_cleanup_session` (host loss), `test_autosave` (lost connection during export) | - | not performed |
| 17 | Incorrect IP addresses | `test_shell_join` (invalid address and port), `test_connection_diagnostics` (invalid address, DNS failure), wrong world at the address | - | - |
| 18 | Closed or blocked ports | `test_shell_join` (refused, explained), `test_connection_diagnostics` (refused / timeout / blocked classification) | - | real firewall/router: not performed |
| 19 | Invalid invitations | `test_shell_join` (malformed, tampered), `test_invite_code`, `test_connection_rejections` (refused credentials) | - | - |
| 20 | Incompatible game versions | `test_connection_diagnostics`, `test_connection_rejections` (version mismatch stops reconnects), invite build mismatch refused | - | - |
| 21 | Interrupted saves | `test_autosave`, `test_emergency_save`, enrollment interruption tests (`test_enrollment_runtime`, pending enrollment) | - | not performed |
| 22 | Corrupted save recovery | library damage detection and restore (`test_character_library`, `test_shell_app`), store integrity audits (`test_character_transfers`, `test_storage`) | - | - |
| 23 | Launcher (menu) crashes | menu errors become messages with `shell/last-error.txt` (`test_shell_app`), `sync_from_worlds` after a crash, abandoned enrollment restart | - | not performed |
| 24 | Game crashes | `test_character_creation` (a crashing game ends the setup with its code), session outcomes | - | real crash on a PC: not performed |
| 25 | Connection loss during play | `test_character_creation` (lost connection stays a lost connection), `test_companion*`; session window shows "Not connected" (`test_shell_app`) | - | not performed |
| 26 | Old saves preserved in migration | `test_shell_migration`, `test_character_library` (originals byte-identical), `previous-saves` on return | - | - |

**Reproducible two-PC procedure** (for the owner; not marked passed here):

1. Install the full-run Setup on PC A (host) and PC B (friend). On both, create a character (Characters, or the first Solo).
2. Same Wi-Fi: on A, Host World, create a world, Invite codes, copy Player 2's code, "Host this world now". On B, Join
   Friend, paste. Expect: B's game opens once on its character (CONTINUE), then plays in A's world; A's session window shows
   the friend; both see each other in the game.
3. Close B's game; on B choose Continue Adventure: B returns with nothing to create.
4. Wrong things on purpose: on B edit the saved address to a wrong port (expect "Nothing is accepting connections there"
   and nothing changed); stop hosting on A and retry from B (same); run different versions (expect "Different game
   versions").
5. Different Internet connections (B on a phone hotspot): repeat 2 with Internet access on (watch "Router:" in A's session
   window), then with Tailscale, then with a relay (run `EmeraldTogether.exe --relay-server` on a third reachable PC, set it
   in Network settings, Relay, make a new code).
6. Universal character: on B, play Solo and catch a Pokemon, then join A's world again; expect "played somewhere else" and
   the new Pokemon in A's world.
7. Record the results in `TEST_LEDGER.md` (PC rows).

---

## H. Integration status

| Repo | Branch | Head | Based on | State |
| --- | --- | --- | --- | --- |
| App | `claude/admiring-bohr-dpxzuy` | `955851d` + this record | `27c43c7` (default) | pushed; fast-forward of the default possible; suite 2234/0; CI full run 39162322062 green |
| App (merged into the above) | `claude/nu-network` | `6597062` | `27c43c7` | merged at `af038bd` |
| App (merged into the above) | `claude/nu-install` | `45703cb` | `27c43c7` | merged at `9cef3eb` |
| Engine | `claude/nu-engine` | `6cd8af0f` | `cf7cba76` (default) | pushed; fast-forward of the default possible |

Readiness: the code and its automated tests are complete for what this update asked; the defaults are not changed.
Merging needs the owner's go-ahead (engine first, then app, both fast-forwards; the app's CI builds the engine default
unless `engine_ref` names a commit).

Outstanding before calling it released:

* a person on real PCs: the New Game and registration sequence, two PCs on one network, two Internet connections,
  a real router's UPnP/NAT-PMP, Tailscale, a relay on a real machine, Windows Firewall's prompt (procedure in G);
* invite codes cannot be revoked one at a time (a leaked code means stopping that world);
* the installer is unsigned; `bios.c` licensing is unresolved;
* two background agents (networking, installation) stopped at a usage limit before writing their final reports; their
  committed work was reviewed, its remaining uncommitted pieces were tested and committed, and the menu integration they
  left for this session was done here.
