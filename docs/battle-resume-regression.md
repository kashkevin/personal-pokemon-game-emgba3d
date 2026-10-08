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
