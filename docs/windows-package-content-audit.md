# Windows package content audit

The launcher builder audits the selected runtime files before creating its output, verifies the copied runtime tree, and audits both the finished package tree and final ZIP. The standalone `scripts/windows-runtime/package_audit.py` reads ZIP, TAR and gzip/bzip2/xz wrappers without extraction. It rejects known console ROM/disc, save/state, credential and database extensions, plus this project's secret-bearing host/invitation JSON formats. It recognizes archive signatures even under a different filename. Ordinary source code mentioning these formats, notices, generic `.bin` assets, and object/static-library relink inputs are retained.

The audit limits nesting to five archive layers, files/members to 50,000, individual files to 128 MiB, decompressed archive streams to 256 MiB, and cumulative inspected bytes to 2 GiB. Cumulative bytes include wrappers and their members. ZIP directory counts are checked before materializing its entries; encrypted, malformed, unsupported or over-limit archives fail closed. TAR links are inspected as metadata, resolved within the archive namespace, and never followed. The builder records tree/ZIP counts in its private `package-audit.json` and build result.

This is a bounded known-format packaging guard, not a classifier for every possible renamed binary payload or a complete distribution/licensing review.

## Independent derivative review

The new `bundle-players-source-clean-2` runtime manifest has SHA256 `dfd3b2d91e874b0823bfd04b5d48e6db64ff243671b4f954a055947e3baf6c21`. The retained original source archive is `24e11bd15b49dcbd74513e8fd6acdcead005616c0e3f52b8e93413fb8f42725e`; its derivative is `d2648866d4cb01d1cdaf882d4a3b0f3764aba9ba5beb73cbd8896b54eac082e3`.

An independent comparison verified every retained member's bytes and metadata: **2,823 identical members**, with exactly the sanitizer's 193 pinned cinema fixtures removed (154 `.gb`, three `.gba`, five empty `.sav`, and 31 `.mvl`). The pinned mGBA video-log implementation can store an initial native state; the MVL fixtures therefore belong to the excluded test-data inventory. Production `BUILD_TEST`, `BUILD_CINEMA`, and `BUILD_PERF` are OFF. The production sources and relink command require none of the excluded fixtures.

All original runtime files retain their hashes. In the derivative, only the existing source tar and explanatory README change, and three reproducibility files are added. Executable, DLL, Lua bridge, relink materials and notices remain identical. Every one of the derivative's 32 manifest entries was independently verified. No ROM rebuild or native acceptance is inferred from this packaging transformation.

The final guard passed the actual derivative (5,264 files/members, 13 archives, 490,759,185 inspected bytes) and an in-memory ZIP wrapper around that exact runtime (5,265 files/members, 14 archives, 490,762,345 inspected bytes). The private independent record `package-audit-independent-runtime2-final.json` has SHA256 `48bfe5048f254bcc67da5af2ca0f0f3b246825704ad28762311b082b0e54a137`.

## Tooling verification

All **12 focused tests passed on Windows and WSL**, with no skips, in 0.155 and 0.050 seconds respectively. Coverage includes nested fixtures, final ZIP wrapping, unchanged source/relink inputs, arbitrary-name project credentials, archive signature detection, malformed/unsupported/encrypted containers, ZIP directory-count forgery, depth/size/expanded-byte limits, legitimate relative source links, and builder refusal before output creation or PyInstaller execution.

Private logs are `package-audit-windows-3.log` (SHA256 `b512f0175316f1a9a3eefcda54f8b1fb4b03d6247f82396fd378f5e28d8f0d38`) and `package-audit-wsl-2.log` (`95d9b834252dffdbdb894493d31a305c955470d7ef47034bafb196651a79233a`). The WSL archive copy matches its original. These standalone packaging tests are separate from the 834-test application regression frozen at `1b7c75013d570de8f33d75f2a29bdbe67003114c`.
