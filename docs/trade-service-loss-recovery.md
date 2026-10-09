# Interrupted trade: verified close and fresh Continue

The launcher now offers **Resolve interrupted trade** after a public trade loses
its host connection and the original menu and emergency controller have naturally
settled into a retained trade hold. This is a close-and-reopen recovery path. It
does not resume the disconnected trade core, change battle recovery, or reconstruct
a game after whole-PC failure.

## Player flow

1. Keep both original game windows open. If the surviving host's service stopped,
   the host uses **Restart host service**. That action restarts the same verified
   world, endpoint and server certificate without replacing either running game.
2. Each player chooses **Resolve interrupted trade**. Its confirmation explains
   that an unfinished trade will be canceled. An already committed trade is kept.
3. Wait for the explicit verified-close status. Unknown fate, changed source,
   missing evidence, failed authentication or a competing canonical revision
   leaves the original held; a timeout is not cancellation evidence.
4. Close that original game window normally, then open the same Host/Join
   character. The existing closed-game recovery gate downloads and verifies the
   canonical result before it launches a fresh game. Continue resumes that result.
   The launcher distinguishes a recovered committed trade from a verified canceled
   trade. A committed native-effect result also retains its received/evolved summary.

## Authority and persistence

`launcher_session.py` captures the exact original game, runtime, bridge,
incarnation, runtime identifier, authentication binding, transaction, generation
and base revision at public native trade handoff. The action is unavailable while
the original menu task, a save, another interaction, or battle ownership is active.
The completed emergency task must affirm `trade_waiting` for that exact original.

The local reader crosschecks the captured world/player/build/rules binding with
the provisioned configuration. Its transport-free identity view allows strict
Flash ownership checks even though disconnect has correctly cleared the original
Companion's current authentication. Those original fields remain cleared.

`trade_close_recovery.py` uses a short-lived separate Companion with no native
bridge and a strictly newer authenticated player lease. The original Companion
stays disconnected. This observer can query the exact transaction and explicitly
cancel its exact unfinished generation. It issues no native command, checkpoint
upload, live import, native release or committed ACK.

An aborted result must still name the original prepared canonical head and match
every byte of its retained frozen source. A committed result must be the original
base plus two and match the complete retained recipient candidate, including the
existing native-effect consent, review, receipt and transcript validation. The
observer rechecks the current head and original intent, then durably records a
`*.close-review.<server epoch>.<lease>.json` receipt. This receipt is explanatory
evidence; it cannot bypass any later startup check.

`cold_start.py` repeats authoritative fate, metadata, ownership and candidate
checks with the original game closed and an exclusive `MirrorLease`. It restores
the exact canonical bytes, verifies them, and ACKs a committed trade only after
installation. It retains a `trade-result.json` record alongside the normal closed
recovery evidence before retiring pending intent. Effect results use the same
immutable `received-result.json` format as normal live completion.

Earlier interruptions without a complete verified prepared export remain held.
This change does not infer a safe close from an absent journal, expired proposal,
missing peer, or disconnected socket. It does not add a new native trade-handoff
ABI or weaken the original lease/emergency-save fences.

## Verification

- Disposable Python/SQLite/Flash and launcher/UI cohort: **69 passed**, 21.389 s.
  Sources: `test_trade_close_recovery.py`, `test_launcher_trade_recovery.py`,
  `test_cold_start.py`, `test_public_trade_effect_client.py`,
  `test_launcher_trade_terminal.py`, and `test_launcher_gui.py`.
- Final completed-emergency-task fence: retained launcher checks **3 passed**,
  0.064 s. These are fixtures, not emulator acceptance.
- After the real interruption exposed the cleared-authentication reader defect:
  focused recovery/cold-start/recipient/terminal checks **51 passed**, 16.409 s;
  an additional captured-world/player/build/rules and observer-world mismatch
  check **passed**, 0.224 s. A task-composed restart fixture also passed.
- Actual Tk layout checks verify that status, recovery, host restart and close
  controls fit at both 740×810 and 660×730. The footer reserves space before the
  already scrollable notebook; no larger screen is required.
- Copies of both actual `wqte4` native candidate/receipt profiles also reconstruct
  the exact original received summaries through the new cold canonical-metadata
  override on a newer lease. Changed canonical hash and native receipt are refused;
  both originals remain unchanged. This is real retained-artifact validation,
  **not** an actual-core committed-interruption proof. Evidence is private at
  `PokemonPrivate/artifacts/trade-real-retained-summary-20261009-1/evidence.json`.
- Actual-core canceled-interruption qualification **passed** as recorded below.
  The controller is `scripts/windows-runtime/qualify_trade_service_loss.py`;
  it shares ordinary menu/input and lifecycle helpers with the preserved successful
  happy-path trade qualifier.

The local test log is private at
`PokemonPrivate/artifacts/trade-close-recovery-focused-20261009-1/focused.log`.
Its Tk teardown printed pending callback warnings; all 69 tests completed with no
failures or skips. These checks do not establish LAN/Internet acceptance,
whole-app crash recovery, committed-ACK fault acceptance, or trade cinematics.

## Preserved initial interruption failure

Private `PokemonPrivate/wqtr1` reached real offers and mutual consent, one genuine
native Wurmple candidate review/receipt, zero commits, actual service closure, and
both original trade holds. The strict original-source reader then incorrectly
used `Companion.world_id`, which `Companion._disconnect_remote` deliberately clears.
That disabled restart before a new host listener or observer receipt existed.

This run is **failed**, with all original inputs and frozen source preserved.
The inherited proof cleanup delayed and masked the initial error with a canceled
play-task timeout. The two disposable original game windows were normally closed
to finish diagnostics; both exited 0, while enrollment children had their expected
exit 1. No watchdog kill was used. The evidence still marks interruption cleanup
as disqualifying. All six recorded controller/native processes were independently
absent afterward. A separate copied-world diagnostic passed strict source reads,
HostWorld validation and real service startup, isolating the cleared original
identity as the problem. Fresh proofs record exception context before cleanup and
check that disconnected original authentication remains cleared.

## Actual Windows canceled-interruption acceptance

Private `PokemonPrivate/wqtr2` passed on 2026-10-09 using two real original
LauncherSessions, genuine copied Torchic/Wurmple parties, ordinary native
offers/confirmation/candidate-review inputs, and the real native replay worker.
The deliberate service loss occurred after the first recipient's native receipt,
with the second approval withheld and zero commits. Both originals naturally
reached `trade_waiting`, retained their exact journals, and remained unable to save.

The production host restart succeeded. Each production recovery action used an
independent observer lease and verified the exact canceled fate and unchanged
source bytes. Both original Companions stayed disconnected, their current
authentication stayed cleared, their captured bindings stayed unchanged, and no
native release or lease renewal occurred. Both originals then closed normally
with exit 0 and their original native parties intact.

Fresh Host/Join repeated the normal cold recovery gate, retired both pending
intents, reported the exact canceled transaction/generation, loaded the canonical
revision-2 parties through Continue, and saved revision 3. Both fresh games closed
normally with exit 0. The two enrollment children had their expected exit 1. All
eight recorded native/controller processes were independently absent and no test
window remained afterward. No process was forced; original inputs, copied inputs,
frozen source, runtime and launcher files were unchanged.

The runner elapsed time was 361.964 s; the outer watchdog measured 363.303 s.
The fixed scenario/runner/watchdog limits were 1200/1320/1440 seconds.

| Evidence | SHA-256 |
| --- | --- |
| Frozen 479-file source index | `f394986bd8a0f4d73466af0d11202f43ff2e6b3b94791875817b7ab222bf18ad` |
| Frozen interruption controller | `24c93effb161ea70372e2db154848ee439ffc9569f4daf9ac5b12677ae076e89` |
| `wqtr2/run/evidence.json` | `8ab80375c787256277eab26337e31b25b48c45462fb1b2e942020ffab7daae80` |
| `wqtr2/outer-evidence.json` | `ecdd40c739868f64d57f520255198a4896b6656a32a6701778250fc8918cfe76` |
| `wqtr2/watchdog-evidence.json` | `d60329497f608baf602d876fee062218f925c1653def6ae76259897df448914c` |
| Original game ROM | `f99bfa4e19ccb5ba998b54d2151986665c15bed3b2d28dab10340d59be3a1d65` |
| Game manifest | `f97dffa70c4edf93de4f90202f8fe08a5a3a499cb2113574c73881321b4bb7e1` |
| Host replay worker | `1874676fdb1cbb4a4dd2afca64a7e3197d8f18f1afd9bb9216ae68a5a9dcb4e6` |

This qualifies a same-machine service interruption before commit, with genuine
non-evolving parties and programmatic calls to the same production launcher
actions. It does not qualify physical keyboard/GUI-button operation, whole-app
death, committed-ACK faults, evolution/move choices or LAN/Internet. The old f99
game is retained for this evidence; later Gen6/release candidates need their own
applicable acceptance and are not silently substituted here.
