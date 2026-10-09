# Windows first-run character handoff

The launcher now gives hosts and friends separate setup routes. This extends the
existing ordinary New Game and host enrollment controllers; it adds no remote
registration, save synthesis, ownership grant, dependency or gameplay rule.

1. Each player imports their own supported game dump in the main launcher.
2. The host chooses **Set up a world or character → I’m hosting**, creates the
   accounts and explicitly selects the world’s trade friendship rule. Successful
   creation or world selection opens the account setup page.
3. A friend chooses **I’m joining a friend**, creates a character through normal
   New Game, starter choice and in-game Save, then closes that game. Alternatively
   they select a closed, unassigned character save.
4. **Export character for host approval** writes a new `.sav` copy to the friend’s
   selected location. The friend gives this copy to the host themselves. The
   launcher does not send files or ask for the host’s private world directory.
5. The host selects that copy for the correct provisioned account, explicitly
   approves it, uses ordinary Continue, and chooses **Finish enrollment** at a
   safe field point. The existing enrollment runtime assigns ownership and
   commits the canonical save before completing.
6. The host exports that friend’s personal invitation. The friend uses it in
   **Join Game** while the host is running. The original unassigned save remains
   a backup, not a second branch to keep playing or merge into the world.

Already enrolled players continue to use normal Host/Join and canonical
recovery. An invitation alone does not enroll a character. Private `host.json`,
world databases, credentials and canonical saves are never included in this
character export.

## Source and publication guarantees

[`character_handoff.py`](../src/emerald_multiplayer/character_handoff.py) reuses
the pinned Flash parser, unassigned inventory validator and cooperative
`MirrorLease` used by the existing draft/enrollment controllers. A source must
have a valid complete container, wholly unassigned inventory and a nonempty
party. Selection binds its exact bytes, party count, ROM and manifest hashes.
The New Game worker retains the exact receipt produced after normal child exit;
it does not select a later unverified file merely by pathname.

The host’s explicit approval also passes that selected hash into
`host_enrollment` / `approve_enrollment_source`. A changed source is refused
before its enrollment record is written or a bootstrap child is launched.
Existing non-GUI callers remain compatible with the optional pin parameter.

Validation runs before opening Save As, then runs again under the save lease
after the dialog. Size, inode, modification time and digest checks reject a
changing or replaced selection. The file is re-read before publication. A live
launcher draft is refused by the same cooperative lock; another emulator must
also be closed by the user. These checks do not claim control over arbitrary
external writers.

Publication flushes a temporary file and links the complete bytes to an
exclusive new `.sav` destination. Existing files, the original source, linked
destinations and paths within the application’s managed private tree are
refused. The source contents are never rewritten. The lock sidecar is not an
enrollment or identity receipt. The export contains no synthetic Pokémon,
canonical checkpoint or credentials.

[`launcher_setup_gui.py`](../src/emerald_multiplayer/launcher_setup_gui.py) keeps
the existing worker/Tk event boundary. Save As opens only after validation has
completed and its worker thread has exited; a closing window cannot dispatch
the pending export. Host approval is still a separate explicit action. Setup
forms now scroll and reserve footer space for status and Close.

## Verification and limits — October 9, 2026

The Windows `test_character_handoff`, `test_launcher_setup_gui` and
`test_draft_runtime` cohort passed **32 tests in 8.523 seconds**. It covers real
disposable Flash containers, exclusive file publication and OS save locks;
changed sources before and during Save As; installed-build changes; destination
races; owned/invalid/starterless rejection; and actual Tk widgets composed with
the worker and filesystem. The file picker is controlled in those automated
tests. Draft lifecycle tests use disposable child/save fixtures, not native
New Game gameplay. Independent source review found no concrete blocker.

The unchanged [private candidate 9](windows-release-candidate-9.md) was also
opened with a fresh isolated `LOCALAPPDATA`. Its real **Import my game** button
and native file picker imported the owner-supplied ZIP. The visible completion
status was observed, the installed 33,554,432-byte game matched SHA-256
`f99bfa4e19ccb5ba998b54d2151986665c15bed3b2d28dab10340d59be3a1d65`, and the
original ZIP and packaged executable retained their prior hashes. The owned
launcher closed normally; no game, world, enrollment or network session was
opened in that check. Evidence is private under
`artifacts/launcher-first-run-20261009-1/gui-import-receipt.json`.

This inspection also found candidate 9’s default window clips its bottom
status/actions; maximizing reveals them. The separate current launcher layout
fix is not part of candidate 9. A source-only setup visual-preview helper had a
hidden owner window and was closed without qualification; its failed receipt
is retained separately. The new friend handoff has automated source evidence,
not a rebuilt packaged GUI or separate-PC enrollment acceptance. Candidate 9,
all original worlds and saves, and the owner’s source ZIP remain unchanged.

Reuse basis: [setup composition](launcher-setup.md),
[draft and enrollment lifecycle](launcher-session.md), and the current
[master specification](master-spec.md) / [roadmap](development-roadmap.md).
No community code or artwork was incorporated for this interface change.

The final affected Windows cohort, including `test_launcher_setup` and
`test_enrollment_runtime`, passed **51 tests in 35.832 seconds** after the
host-approval pin fix. It confirms the changed selection creates no enrollment
record or child and retains the prior TLS/store/child cleanup behavior.
`artifacts/launcher-first-run-20261009-1/final-setup-tests.log` retains the log.
The earlier 32-test result separately covers ordinary draft regressions.
