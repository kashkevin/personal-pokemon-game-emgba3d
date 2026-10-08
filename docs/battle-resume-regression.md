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
