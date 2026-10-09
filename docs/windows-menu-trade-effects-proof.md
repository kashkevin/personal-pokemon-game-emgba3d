# Windows public native trade proof

The October 9, 2026 `wqte4` run **passed** the supported two-client trade,
manual-save and fresh-Continue flow. Both clients used real Windows native
cores, their production `LauncherSession`/Players menu tasks, the current
bridge and the actual Windows native replay worker. This is a local TLS
qualification using newly enrolled copies of genuine characters; it is not
separate-PC or Internet acceptance.

## What passed

- Production enrollment of two copied characters at canonical revision 1,
  authenticated Host/Join, TLS and original mirror leases.
- Ordinary Start → Player → Players navigation, original party selection,
  each player's explicit consent and native private-candidate review. One
  consent did not commit; both consents alone still did not commit before
  final candidate approval.
- Complete native recipient saves and durable client receipts, actual host
  replay, one paired v2 commit, canonical import/readback/ACK/release and
  revision 3 on both original cores. Ownership serials were conserved, each
  selected original Pokémon reached the intended recipient, pending intents
  were removed and each emergency saver was armed.
- Both retained native Players notices: `Received: Wurmple` and
  `Received: Torchic`. Their durable result hashes matched the applied
  canonical candidates and the client receipts matched the host's paired
  document.
- Manual saves to revision 4, ordinary friend-then-host window closure,
  and native party-log verification. Both gameplay processes exited 0.
- New Host/Join sessions and native processes, including actual host startup
  history replay, fresh Continue with exact revision/hash/payload and party
  preservation, followed by two more ordinary exit-0 closes.
- Final closed-store integrity, mirror lease release, no forced children or
  cleanup errors, unchanged original/frozen/copied/native/runtime inputs, no
  surviving owned process or window. The final independent comparison also
  found all 119 current production Python files plus the bridge equal to the
  qualified frozen source.

The scenario's runner took **450.873 seconds**; the enclosing watchdog took
**454.067 seconds**, including process setup/finalization. Inner, outer and
watchdog evidence all report success. The unchanged bounds were 1200 seconds
for the scenario, 1320 for its runner, 1440 for the independent watchdog and
120 for each ordinary-close phase. Timed autosave was explicitly disabled;
the saves above were manual.

## Inputs and isolation

The reusable controller is
[`scripts/windows-runtime/qualify_menu_trade_effects.py`](../scripts/windows-runtime/qualify_menu_trade_effects.py).
It freezes exact inputs and source, rejects reused outputs, observes displayed
native menu rows and uses bounded ordinary joypad presses through the existing
proof helper. It does not write native RAM, invent Pokémon, inject receipts,
replace a production method or force a trade result. Normal window closes
used the Computer Use skill's observed title-bar Close controls, after checking
each process's executable, creation time and current window identity.

The explicit diagnostic world policy was
`gen6-absent-geography-refresh-v1`. It applies only to this newly created
disposable world and does not choose a policy for an existing/private world.

| Input | SHA-256 |
| --- | --- |
| Combined normal ROM | `f99bfa4e19ccb5ba998b54d2151986665c15bed3b2d28dab10340d59be3a1d65` |
| Matching ELF | `ec0b0bfe1db792115a12a54bb42152afc5775269ccb9315d99b964545b886863` |
| Game manifest | `f97dffa70c4edf93de4f90202f8fe08a5a3a499cb2113574c73881321b4bb7e1` |
| Production bridge | `7661b9dee572ec7409ec001efda4255471258a27ceebc1daa45c85c6ce92e863` |
| Windows replay worker | `1874676fdb1cbb4a4dd2afca64a7e3197d8f18f1afd9bb9216ae68a5a9dcb4e6` |
| Parent SDL bundle manifest | `d07b4dcdc12d3cb3cdb68e58178ad4f1981a1d527d44d3653beb39d04f2c5b1a` |
| Proof bundle with current bridge, worker and bounded input appendix | `f47c5318eedfd937e335189089942be8786eefb3294666081006ad885627c47c` |
| Host genuine source; selected party slot 0, Torchic level 7 | `8d611857e848f68ff3624d8540704d7e70ed4115326f82e304408587df9f3bf6` |
| Friend genuine source; selected party slot 1, Wurmple level 2 | `c929ab0c161ee230914da38d717b12782d8c71afb9d6e8b99cf8c05dde71a2ed` |

The originals were read-only. All enrollment, checkpoints, native candidates,
history and saves live under the new private proof output. No private content
belongs in Git.

## Evidence and prior failures

All four attempts remain separately preserved under
`%LOCALAPPDATA%/PokemonPrivate/wqte1` through `wqte4`. The successful run's
462-file frozen source index has SHA-256
`8ec64a5e6096d0eea5d5abd499b0e4250630c7f165610c253e0df0c4f65f93c4`;
its controller is
`a0078c63f7deacbafc24468a282dbe57f319e97ceb2a4832372c4beddb32988e`.

| Successful private artifact in `wqte4` | SHA-256 |
| --- | --- |
| `run/evidence.json` | `705a418f3b23afda9bc7ae8e981fd7a443aa875f7404a6cd34102b7d33893c4f` |
| `outer-evidence.json` | `bfd37c98cdc550f65b799369b8aeccd6fdf282f04be77de0d1300be1c4ccdc01` |
| `watchdog-evidence.json` | `b99f5921f5ba89e72071cbafa2c41dbbd32110d7aeb62bc99114af62e102de72` |
| `controller.log` | `dbb5f113a0a899c8e56a2a2e8f5e9f644d2e552fba24183de31f87822967c430` |
| `final-independent-verification.json` | `378271463049a6582dbf72f555b9a60b34dc7d0f473b6f885d547c5b2cf871b7` |

Enrollment children 48512/62988 closed themselves with the existing expected
return code 1. Original games 63924/66392 and fresh games 13500/46776 all
closed normally with code 0. Controller 28472 exited 0. All seven PIDs were
independently absent afterward; exact executable-path enumeration and the
returned window inventory found no surviving owned core/window.

The failed attempts remain failures; their partial progress is not acceptance:

| Run | Confirmed boundary and reason | Inner evidence SHA-256 |
| --- | --- | --- |
| `wqte1` | Host offer succeeded; genuine friend Treecko was blocked because it has move 633, Leafage, outside the selected Gen 6 move contract. No rule or original move was changed. | `957c113174f697b7b81c5af10cd5e6e7559e3f961386a486eb03dc71e833bff8` |
| `wqte2` | Both native records reached READY; opcode 29 parsing rejected real status-move category 3 before the review menu. The narrowly corrected parser/labels are documented in [the client report](public-native-trade-client.md#actual-native-move-category-correction). | `d42b7294b40600fc407f2be3e59f87d5fc5b9b67ce38d22e27b223fb05c92a80` |
| `wqte3` | Both native reviews, paired commit and canonical applications succeeded. The controller then waited for a Received screen without reopening Players after import. Forced failure cleanup prevents full acceptance. Only the proof navigation changed for `wqte4`. | `c8d846f56e52a2a73b1574fb1e3e2c07ff4060f2dbd1fa8ca5933130a3afcdde` |

## Limits

Neither selected Pokémon evolves through trading, so this run had **zero
evolution move decisions**. It does not qualify actual player-driven trade
evolution, replacement/decline decisions, evolution cinematics, trade fault
recovery, physical keyboard mappings, launcher GUI buttons, timed autosaving,
Wi-Fi/Internet or four simultaneous trading clients. Separate native worker
fixtures exercise evolution, but do not extend this run's gameplay scope.
The existing post-Gen-6 move compatibility question remains unresolved; choosing
a supported genuine Wurmple did not change or normalize any other Pokémon.
