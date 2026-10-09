# Host/Join usability additions — source only

The October 8 implementation batch extends the existing launcher and setup
controllers. These additions have **not been built, tested or launched**. The
earlier package 7 and actual-runtime evidence refer to their frozen sources,
not this batch.

## Connection details and invitations

`src/emerald_multiplayer/network_diagnostics.py` defines a public-only
`ConnectionDetails` value. It contains the numeric endpoint, port, address
scope, game build and certificate fingerprint. It never retains the invitation,
credential, account/world identity, certificate PEM or private filesystem path.

Selecting a Join invitation now checks its bounded existing format/certificate
and matching game build on the launcher worker. The window displays the address
and port with loopback, LAN, link-local or public-address guidance. An existing
host session publishes the same details after its normal identity validation;
its advertised invitation address remains distinct from the host's local bind
address. This display does not change either address.

**Copy connection details** copies only those public connection fields and a
reminder that every friend needs their own private invitation file. Clipboard
feedback has its own label and does not replace a save or battle recovery
warning. No invitation JSON or token is copied. Changing selections invalidates
the prior displayed details. Setup's existing invitation export remains
exclusive-create; its completion explains the recipient and offers the same
credential-free copy action. Creating/selecting another world clears that
export summary.

The existing credential-free TLS probe still sends no application data. It now
distinguishes timeout, refused port, missing network route, local network
permission failure and certificate failure through fixed messages. The original
`unreachable` result code remains compatible, with an additional bounded
`failure_reason`. A build mismatch is rejected before opening a connection.
Loopback/LAN/public address classification remains separate from proof of
separate-PC or Internet gameplay. No adapter, firewall, router or trust-store
setting is changed.

## Running game and actions

`launcher_session.py` publishes current authenticated connection state, the last
verified checkpoint revision, controller save availability and public connection
details. `launcher_gui.py` displays the connection/revision separately from the
primary status, and enables Save now from the controller's actual availability.
A displayed checkpoint revision is not evidence that unsaved recent progress
has been committed. Existing safe-point export and recovery ownership remain in
their original controllers.

Rejected save/recovery/restart button dispatches now give a bounded actionable
message. A changed session instructs the player to retain the game until its
save or interaction reaches a verified outcome. The controls/help window
documents the existing keyboard defaults, safe saving, separate invitations,
LAN/Internet setup and Local Soft Reset's eligible-encounter limits. It does not
enable reset encounters or qualify physical input.

## Trainer Card integration

Host/Join tabs have vertical scrolling so connection details remain accessible
when the window has less vertical room. The third launcher tab hosts
`launcher_player_panel.PlayerPanel`. Explicit
Refresh calls the read-only `read_player_snapshot(session)` on the session's
existing event loop, with one pending refresh and a twelve-second bound. Only
the card/roster/team/recent-history summary crosses to Tk. Fixed ready, unsupported, unavailable
or connection-lost results remain separate from the main recovery status.
Session cleanup drains the refresh before releasing its context. There is no
automatic card polling or additional transport/native owner.

## Preservation and remaining evidence

The exact four pre-edit Python files are retained under private
`PokemonPrivate/artifacts/launcher-network-source-before-1`, with SHA-256 values
in `originals.json`. No accepted runtime, ROM, save, private world or package was
modified. No dependency, test, build or GUI process was started for this slice.

Widget layout, clipboard behavior, real error categorization and the composed
Trainer Card lifecycle remain unverified until testing is requested. Network
reachability never substitutes for four real clients, separate computers,
Wi-Fi/Internet play or installation acceptance.

## Extended source batch, October 9

The [extended batch report](large-feature-batch-20261009.md) records the new
Battles, Archives and Local Reset panels. These share the existing worker action
lane, completion draining, recovery exclusions and status events. Battle actions
are reviewed/session-bound; full record browsing is read-only; reset retry sends
only the original waiting admission identity. None of these controls has been
run in a GUI since testing was paused.

`launcher_display.py` stores favorites, display filters and text size separately
in `launcher-display.json` under the launcher's existing private root. These are
local launcher-wide presentation choices, not character stats or per-player game
settings. It preserves malformed/unreadable existing files and applies temporary
in-window choices if persistence fails. Three text sizes, launcher-scoped
shortcuts, scrollable new panels and topic-based help are source additions.
The explicit idle-only installed-file check invokes the existing package verifier;
it does not install anything, open a game, read a character save or provide the
missing import patch. No new dependency or executable is supplied by this work.
