# Six-slot native Multi opening preview

Engine commit `bcb8ff837fcb333e72d5d84894bce7421e781ef2`, based on accepted combined source `afd92ce3a12204873e2f06a77a7bf1717d04f53b`, corrects the opening VS screen to show six independent party-status icons for each of the four trainers. This display change does not change the battle packet ABI, save layout, trainer mapping, party capacity or battle rules.

The [source-only patch](../engine-patches/phase5-native-multi-six-slot-preview.patch) has SHA-256 `2da28ef0fe470046e861f7ddf71747924ba4a61309713362930585c144a99316`. Its reverse-apply check passed. Native startup already sends six two-bit statuses in each validated header. The VS task now snapshots the four complete words into its unused data slots 6–9 before party packets reuse the receive buffers. The renderer reads the corresponding trainer's word and draws six existing tiles at the existing card coordinates. Legacy Multi retains three icons and its existing end-screen ordering; singles retains six self/opponent icons.

## Reuse audit

The pinned RHH 1.17.1 engine is `bb1093a7c72d3961d9a37d8e02ad2abc2c866682`. An October 8, 2026 read-only remote check found current maintained master `6057b187f946094d614e9c34bc12731ea6a5b7bb`. Its [official battle background implementation](https://github.com/rh-hideout/pokeemerald-expansion/blob/6057b187f946094d614e9c34bc12731ea6a5b7bb/src/battle_bg.c) still uses three icons per legacy Multi participant. The adaptation reuses the pinned task, two-bit status encoding, tiles, palette and windows. No third-party code, assets, library or new dependency is imported; existing provenance remains in the [dependency ledger](dependency-ledger.md). Four summary words replace two truncated words, with no added persistent storage or new dynamic allocation. No new performance claim is made.

## Qualification and its limits

All **73 focused multiplayer C tests passed** on this source. The three new cases exercise all four local trainer views with distinct six-slot status patterns through the production startup channel, overwrite the old receive buffers, check the bounded tile output, and retain exact singles/legacy Multi behavior. Both normal and development builds completed; initial copied-asset timestamp warnings were followed by warning-free incremental build and test rechecks. The prior complete combined-source regression remains the full-suite evidence; no new full-suite result is claimed for this small display change.

`native-multi-preview-run-1` passed in four actual headless cores with ordinary parties of **6/1/1/1**. A bounded startup pause after all four authenticated headers let the native VS animation finish before the next party packets were routed. Ordinary gameplay then finished the battle: **1,123 routed blocks**, outcome 1, exact personal party/RNG/Flash restoration, four native checkpoints and fresh Continue. All eight original/fresh core processes closed, and original source saves retained their hashes. The proof uses normal input and allocated production IPC, with read-only diagnostics; no savestate or arbitrary RAM writes.

The captured four VS images are byte-identical. Visual inspection shows six filled icons for Aaa and one filled plus five empty icons for each of Aaaa, cc and dd, fitting all four original cards. Their header words are `0x555`, `0x001`, `0x001`, `0x001`. This is an opening-preview proof with mixed party sizes; the separate retained [4×6 actual gameplay proof](native-full-multi.md) remains the evidence for twelve-per-side battle behavior. These checks do not qualify separate Windows PCs, Internet transport or performance.

| Artifact | SHA-256 |
| --- | --- |
| Default-off ROM | `7cfc68dfa6651fc6de1a48122f41405266b284115a2c9d625c296617fa8e1f14` |
| Default-off ELF | `baf2d6802a0dedfd6936c070348544097b1aec912e4bc0cda23b40503e627157` |
| Development ROM used by proof | `c3cb9ff3f5f5e0fbf2ec95452a7e159a0d7ce22e3a27aa4e8e4ca35485c800ed` |
| Development ELF | `25d7a8751a657a376e848889effc479db79fee58fe07f564916a3856121d4691` |
| Development manifest | `eef03fa8c871a0be3a83e1a59ac450fd0668c0e878eefeaa9ac1ff431c94df68` |
| Focused C recheck log | `8380c7f6561bd09d58dc5dde0187c663d6252e694590644f20592e862d7afd03` |
| Complete private proof evidence | `d54e5891a7749fb87e1678f045df594402117d3dec1e15cf99313829eabed948` |
| Frozen proof controller | `50ba417018530f0b89bbe65f3f8b6a6730e18c5c14cefbfaa6651ca894021a98` |
| Each of four VS screenshots | `c1fe40cf0856823cf0c17a89328ecda27cfb8538fb34152352cc1e823df3e4c9` |

The frozen WSL builds are under `/home/kevin/src/pokemon/multiplayer-proof/native-multi-preview-dev{0,1}-build-bcb8ff8`. Physical Windows private archives under `PokemonPrivate/artifacts/battles` contain six default-off build files, five development build files and 164 run files, all copied and individually hash-verified. Credentials, source saves, private databases and build artifacts remain outside Git.
