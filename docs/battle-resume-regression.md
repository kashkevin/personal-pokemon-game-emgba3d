# Retained-battle candidate regression

The first complete Windows regression used frozen application commit `a13f6e6ab74c72514e7fdf94e4914ad0b6e400ee`, including the delayed native Enter selection and mixed provisional/full-intent restart corrections. It ran from a private Git archive rather than the working checkout. The native recovery candidate and actual-core controllers have separate qualification in [the recovery record](native-battle-recovery.md) and [proof scope](native-battle-resume-proof.md).

On October 8, the Windows suite ran **1,066 tests in 533.618 seconds: 1,065 passed, one failed, zero skipped**. The sole failure was the existing save-mailbox corruption fixture's assumption that status 14 was unknown; the newly added, separately gated `BATTLE_ADMISSION` response legitimately uses that value. The fixture now tests unknown status 15. No production code changed for this correction.

The corrected save-mailbox, emergency-save and real-Lua menu-bridge cohort then passed **37/37 tests in 7.830 seconds**, without skips. This establishes passing coverage of every discovered Windows test across the complete run and the focused correction, but the original complete run remains recorded as failed. The focused run also includes exact emergency refusal evidence and the new Enter marker's Lua validation. Both workers verified Windows BelowNormal priority with the correctly typed process handle. The optional private-save read-only test was enabled during the complete run.

| Private artifact | SHA-256 |
| --- | --- |
| `resume-candidate-source-a13f6e6.zip` | `36d55a5477bfc793347bc2110c08748e479f43b9ff8ef3301942b04264914775` |
| `resume-candidate-full-windows-1.log` | `2ed1ca96e889def8c431c321aa2b53e55520201c39b7178aa3f677f911b727f2` |
| `resume-candidate-status-fixture-windows-2.log` | `5af086b4078924659fc064a224a48e39085c4630ffeba7f3f601b74db2959ff2` |
| Source archive verification record | `c2abae0c0b9be57432cb94d35cd3efb7029f712adc97e56b2770a3734cc7da13` |

All **321 archived files** remained byte-identical in both the tested Windows extraction and the separate WSL extraction. The original archive and failed log are preserved. This Python/Lua suite uses explicit native fixtures; it does not establish resumed native gameplay, packaged recovery, separate-PC networking or power-loss durability.

The previously qualified application `5a7afee7f14dbc86dbaaba909c9f57688df7ac0b` is additionally preserved by annotated tag `WINDOWS_SAVE_DELIVERY_BASE_POC`. Its actual Windows Host/Join, five-minute autosave, independent disabling, manual saving and fresh Continue evidence retain their original combined native `1a7a0cd` pins. That tag does not include optional battle resume.

## Complete WSL run 2

The separate WSL suite ran from frozen application `2dba880` with verified niceness 19 and the private-save read-only case enabled. It ran **1,066 tests in 316.890 seconds: 1,065 passed, one failed, zero skipped**. The failed subcase was `RouteJournalTests.test_live_owner_refuses_same_size_replacement_or_changed_bytes_before_append (replacement=False)`: changed bytes of the same size were not detected before append. This is a production journal guard issue assigned for correction, not a fixture-only acceptance or a passing complete suite. The original failed log and runner remain immutable; the correction and its qualification must be recorded separately.

| Private artifact | SHA-256 |
| --- | --- |
| `resume-candidate-full-wsl-2.log` | `466ed04fe1f05b14e5dd5e04387523fd62b397488b2039445270bc072751d02a` |
| `run-resume-candidate-full-wsl-2.sh` | `ccd9e2ade9d6c2bd9bd31007008e27aab67134468fc458f8b864fde0435c8a04` |
| `resume-candidate-source-2dba880.zip` | `6fcd1629c8accbaa00c76b13e61f03bf2a2294e6fb1f188ebe1059d593cbe779` |
| `resume-candidate-source-2dba880.verified.json` | `da11335857cf1a57fd5b47f350d27916bbb73e3be244111f62ba929c67cd7ae3` |

An independent Windows archive preserves these files together with the completed failed native entry run 1 at `%LOCALAPPDATA%\PokemonPrivate\artifacts\battles\resume-candidate-failed-evidence-1`. Its **134 copied files, 38,732,557 bytes** were each hashed before copying, after copying and again at their unchanged origin. `copy-inventory.json` has SHA-256 `ce0bd425d0db25c668fe05c8c8ed8d9f33e84fdef65074ad184f4fe10a4bcc6d`. Only this run's own private copies and its source/diagnostic evidence were archived; no original player save was moved or changed. These artifacts are outside Git.

## Uncommitted handoff follow-up: complete Windows regression

The October 8 takeover began at `31e5bf93ec8fb24e7cf522908b540b318890d365`. The new handoff changes and their limits are recorded in [PROJECT_STATUS_AND_HANDOFF.md](../PROJECT_STATUS_AND_HANDOFF.md). A first frozen run executed 1,082 tests with three child-process startup failures and no skips. The audit runner had changed only its own `sys.path`; child interpreters lacked the inherited project `PYTHONPATH`. A preserved import diagnostic reproduced `ModuleNotFoundError` without that variable and successful imports with it. The exact three failed methods then passed unchanged in 0.934 seconds. The first failed evidence remains preserved; it is not a passing suite.

The corrected run freezes 333 files, includes the provisional-BIND, reset cancellation, friendship-table and recovery-poll changes, sets inherited `PYTHONPATH`/`PYTHONDONTWRITEBYTECODE`, and verifies Windows BelowNormal priority. **All 1,086 tests passed in 532.412 seconds, with zero failures, errors or skips.** The optional read-only private-save case was enabled. Every indexed source file and both original saves were unchanged after the run. No dependency installation or private world migration was performed.

| Private artifact under `artifacts/handoff-audit` | SHA-256 |
| --- | --- |
| `windows-regression-20261008-182318/tests.log` (failed runner) | `fabaf6f2cbbd023a5842d1cf708c539716f3ebbd7ccdbbbcd69c0e8a7b48177a` |
| `windows-regression-corrected-20261008-183632/source-index.json` | `dcd669fe87907248cc4d7af386699bf5ed9e96f7b319928891f44a724f500834` |
| Corrected `tests.log` | `49b9c7bfe6baf3d67e1f35f56a380e60d43f65885036cfd721833f143b815010` |
| Corrected `evidence.json` | `e82efa286042417f7decb7c8c9795fda23e1943fc4fdf0aab39be162926575dd` |

This source snapshot predates the later one-line menu identity retirement and collector provenance wording correction. The menu/launcher correction has a separate passing 54-test cohort and unchanged source hashes in [native-players-menu.md](native-players-menu.md); collector wording changes no runtime behavior. The Windows suite uses explicit fixtures and does not establish actual-core recovery, native controls, packaged gameplay or remote-network acceptance.

## Uncommitted handoff follow-up: complete current-source WSL regression

After the corrected Windows run completed, a new private ext4 snapshot froze all 333 tracked and non-ignored untracked source files at base `31e5bf93ec8fb24e7cf522908b540b318890d365`, including the later menu identity retirement and collector wording correction. Its base revision, tracked binary diff, Git status and complete file index are retained separately from earlier snapshots. Copying compared every source byte against the working checkout and rechecked the Git metadata; the regression then used only that frozen directory.

**All 1,088 tests passed in 379.320 seconds, with zero failures, errors or skips** (380.102 seconds measured by the private runner). Both the runner and test process were observed at niceness 19. The existing provisioning virtual environment ran `python -m unittest discover -s tests -v`, with explicit absolute `PYTHONPATH` inherited by child processes and `PYTHONDONTWRITEBYTECODE=1`. The optional private-save test passed using the two established original sources read-only. All 333 indexed snapshot files and both original source hashes matched before and after; no dependencies were installed and no private world was migrated.

| Private artifact under `multiplayer-proof/handoff-final-wsl-regression-20261008-1` | SHA-256 |
| --- | --- |
| `source-before.json` | `a56fa813de5e4a012edcaa4e954553d7dd5ed5e522baa131be190cd046ca4191` |
| `tracked-diff.patch` | `52f08c81c060582dc9fc1833f59e140c78f05c4861a8e952d696fd7bec3e6d35` |
| `run-regression.py` | `704dcb02529649c97ef90e3e475c860db0d50762242b9ad26520a73064293c08` |
| `unittest.log` | `75cf4d2f10262af0cd506679909dd35c259ead1d953dfdfb8189f651d752d732` |
| `summary.json` | `a6b2c9371ead117f53c79cd8d96f9a229077c0da99bd42c5d21c723971e40fc2` |
| `hash-index.json` | `44125f22c32f10e7d22ae8954f0256039b0e5dfd9f219fde8c42d41d73b287c2` |

This is a separately passing full WSL suite after the earlier journal failure and later source corrections; the failed historical evidence above remains unchanged. It verifies the Python/Lua test scope, including explicit native fixtures, and does not establish actual-core resumed gameplay, Windows SDL input, friend installation or separate-PC networking.

## Cancellation, saver transfer and asynchronous journal loading

The final Windows application/bridge/native-adapter/test source passed **1,144 tests in 653.061 seconds**, with zero failures, errors or skips. This includes neutral admission cleanup, same-lease terminal saver transfer and the later asynchronous initial journal reconstruction. The existing isolated provisioning interpreter ran the frozen 346-file snapshot at verified BelowNormal priority, with inherited project imports, disabled bytecode and the optional original-save read checks enabled. Every frozen source and both original saves remained unchanged. A subsequent comparison found no difference between the current `src`, `bridge`, `native` or `tests` files and this passing snapshot. Documentation and the separately qualified Windows proof driver have later changes.

| Artifact under `%LOCALAPPDATA%/PokemonPrivate/artifacts/handoff-audit/windows-regression-async-final-20261008-1` | SHA-256 |
| --- | --- |
| `source-index.json` | `9b13d09576c6a9d91dc9d3ce71715ea2974c1f3fc45640b25e1523a687e388af` |
| `tests.log` | `8245c344600e744d88139ddfc61f7cca364298981ebe9aa3070eebaee1f72919` |
| `evidence.json` | `93225209d4e6003a96bfa876578f07cbd80755bda93d17e210f944fde101a1f1` |

Earlier cancellation-era snapshots remain distinct. `windows-regression-cleanup-20261008-1` ran 1,133 tests and found one obsolete public-protocol fixture missing the new operation. The corrected fixture and stricter response cases passed in `windows-regression-cleanup-20261008-2`: 1,135 tests, 548.618 seconds, no failures/errors/skips; index `6c3d282ef5ab419632bec3a9946e898afe08b68228d9616fe21eab6b2c8bd37d`, log `3d9fc6564993e7830fa87487006bf1cf09e432ca1251771f41efe1cf0f40162e`.

`windows-regression-cleanup-final-20261008-1` accidentally used the system interpreter without the already-installed private cryptography dependency: 1,134 tests, 95 errors, no acceptance. The unchanged frozen source then passed under the qualified existing interpreter in `windows-regression-cleanup-final-20261008-2`: 1,138 tests, 635.568 seconds, no failures/errors/skips; index `b0d80734c50691a2a6d709d5dfd3a12ae237244ccf69134a50b9c89a743eaadf`, log `a92a12f4024fd686c8b87e16b865b767ba08fd1fb4dbfa1212017b878fe32725`. That passing snapshot includes both terminal saver fixes but predates the asynchronous journal-load correction. No dependency was installed to repair the runner selection.

These complete fixture suites remain separate from [native cancellation](native-admission-cleanup.md), [actual Windows GUI cancellation](windows-admission-cleanup-proof.md), the [large-journal TCP diagnostic](native-battle-recovery.md#uncommitted-follow-up-responsive-initial-journal-reconstruction), and actual four-core recovery. None establishes a clean friend installation or external-network acceptance.
