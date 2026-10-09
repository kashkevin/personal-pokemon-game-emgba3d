# Creating the own-dump installation patch

The private Windows package builder now supports `--create-patch` alongside
`--base` and `--base-sha256`. This makes patch creation part of the existing
package pipeline once the owner supplies a matching original dump and its
explicit expected hash. The existing alternative of an externally created,
explicitly pinned `--patch` remains supported. Mixing both modes is refused.

[`game_patch.py`](../src/emerald_multiplayer/game_patch.py) creates deterministic
BPS instructions from the supplied base and verified target only. It copies
unchanged runs from the base and includes changed bytes in the patch; it performs
no downloads and includes no metadata containing local paths. Inputs are bounded
to 32 MiB, with the existing patch/action limits retained. This linear encoder
prioritizes bounded work and no additional dependency over minimum patch size;
encoding time and actual game patch size have not been measured.

[`build_launcher.py`](../scripts/windows-runtime/build_launcher.py) verifies the
explicit base/game hashes before encoding, reconstructs through the existing BPS
reader, checks the exact output hash, and freezes those verified patch bytes into
the new package. Package provenance now includes source/patch/output hashes,
input/output sizes and the encoder identity. The original dump and target ROM
remain outside the distributable tree. No existing package is overwritten.

Append these options to the existing explicit game/manifest/runtime/version
arguments when building a **new private output directory**:

```text
--base <owner-dump-path> --base-sha256 <expected-source-sha256> --create-patch
```

The implementation follows [byuu's public-domain BPS format](https://github.com/Sir-Walrus/Flips/blob/master/bps_spec.md).
The [prior reuse review](windows-launcher-gui.md) considered Flips
and RomPatcher.js; no external implementation, binary or dependency was imported.
The existing strict runtime importer and its compiled release pins are reused.

The owner has now supplied a ZIP in their Desktop ROM directory. A read-only
inspection identified one 16,777,216-byte Emerald USA/Europe revision-0 GBA with
game code `BPEE`, a valid header checksum and the previously documented source
SHA-1 `f3ae088181bf583e55daf962a92bb46f4f1d07b7`. Its uncompressed SHA-256 is
`a9dec84dfe7f62ab2220bafaef7479da0929d066ece16a6885f6226db19085af`.
The original archive was rehashed unchanged; its private path is retained in
the handoff conversation rather than included in a package or source metadata.

`game_import.read_game_source` now accepts raw GBA or a ZIP with exactly one
GBA member. It bounds the archive at 64 MiB, central directory at 1 MiB/64
entries and expanded game at 32 MiB; refuses encryption, multipart/ZIP64 and
unsupported compression; and checks expanded size, CRC and GBA header. No file
is extracted. These checks detect malformed input; the independently compiled
uncompressed source SHA-256 remains the identity gate. Both patch creation and
the launcher's Import my game use this same reader.

Normal builds also require the complete production Local Soft Reset descriptor,
the ROM-declared isolated native trade replay capability, and its fixed pinned
worker in the runtime bundle. An absent patch is refused unless the builder
explicitly selects `--development-preview`. `--preflight-only` performs input
verification and in-memory BPS reconstruction without creating output or running
a build. Host creation/enrollment and existing-world feature upgrade remain
separate explicit user actions after installation; a patch does not convert an
older world's pinned game identity.

This source integration does not itself create a real release patch or download.
Package 7 retains its original import-disabled provenance. Build, fixture,
owner-input reconstruction and actual new-machine acceptance evidence must be
recorded separately for the exact later candidate; no earlier result qualifies
these new paths.

After testing was explicitly resumed, 27 Windows fixture tests passed in
`test_game_import`, `test_game_source_archive` and `test_package_audit` (0.853s).
They cover exact expanded-source pinning, unchanged ZIP/no extraction, malformed
and ambiguous archives, CRC/header damage, directory/expansion limits, encryption
and unsupported compression, BPS commands/CRC/size bounds and recursive package
refusal. The existing runtime audit remains before later manifest reads, so
unsafe runtime contents are rejected before output creation or PyInstaller.
These synthetic checks do not qualify a real release BPS or clean installation.

## Actual owner-input reconstruction, October 9

The private `release-bps-visual-20261009-1` proof subsequently passed with the
original owner-supplied ZIP read in place and a copied latest visual ROM.
Production reset and isolated replay manifest gates passed. The 33,189,240-byte
`game.bps` has SHA-256
`2bac367a4701087ec8c021dd8d5de1c747b6cdde08e228eb010b36717217fe22`;
applying it to the pinned uncompressed source reproduced all 33,554,432 target
bytes, SHA-256
`f99bfa4e19ccb5ba998b54d2151986665c15bed3b2d28dab10340d59be3a1d65`.
The target manifest is
`f97dffa70c4edf93de4f90202f8fe08a5a3a499cb2113574c73881321b4bb7e1`.
The original archive and copied target were unchanged. Encoding took 1.794s
and reconstruction 0.045s on this machine; no general speed guarantee follows.

Evidence `evidence.json` SHA-256:
`01d7e23a59b3d92ce6b4a4b7c6ad0f98c8c2728cf6acea23ece4dc333cb30e80`.
This creates a real private patch candidate. It does not package a launcher,
exercise Import my game through the GUI, qualify a clean PC or promote a release.
Original package 7 remains unchanged and import-disabled.
