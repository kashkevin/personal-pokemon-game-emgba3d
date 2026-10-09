# Player build guard

October 9, 2026. Normal Windows packaging now requires a ROM-bound declaration
that four player-accessible development controls were compiled off. This is a
release preflight gate, not proof of multiplayer or overall gameplay acceptance.
The preserved [candidate 10](windows-release-candidate-10.md) lacks this marker
and is refused by the new normal preflight without altering that package.

## Compiled contract

The native `gMultiplayerPlayerBuildGuard` is exactly 24 read-only ROM bytes:
six little-endian `u32` words, `0x31474250`, ABI `1`, followed by the compiled
values of `DEBUG_OVERWORLD_MENU`, `DEBUG_BATTLE_MENU`,
`DEBUG_POKEMON_SPRITE_VISUALIZER`, and `I_SHOW_NO_ID_TRAINER`. All four must be
zero. Assertions, LTO, other compiler flags, the separate 80-byte Generation 6
descriptor, and gameplay rules are outside this marker's contract.

`scripts/multiplayer/generate_manifest.py` obtains the aligned address from the
exact ELF symbol and emits `player_build_guard_abi_version=1` and
`player_build_guard_address`. A named symbol with a different allocation type,
size, multiplicity, alignment, address, or ROM content is rejected. It is not
silently treated as an older build without the capability.

`src/emerald_multiplayer/player_build.py` validates complete strict-typed
metadata, actual file bounds and the exact descriptor bytes. The companion's
existing full ROM hash verification runs before this optional descriptor check.
Recomputing a debug-enabled ROM's hash does not make its enabled flag acceptable.

`scripts/windows-runtime/build_launcher.py` requires the verified descriptor in
normal packaging, before patch construction, output creation or PyInstaller.
Older manifests with neither field remain readable by the companion. An explicit
`--development-preview` preserves the missing-marker packaging exception; it
does not bypass a declared malformed or enabled marker. Removing the fields
cannot satisfy normal packaging.

## Verification and preserved evidence

The focused command was:

```powershell
$env:PYTHONPATH = 'src;tests'
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m unittest test_player_build test_gen6_profile test_save_manifest test_package_audit -v
```

The existing qualified Windows Python environment passed **34 tests in 1.683
seconds**, including 11 new checks. These use synthetic file fixtures to verify
every compiled flag, malformed headers, partial/typed metadata, ROM bounds,
truncation, symbol generation, legacy compatibility, normal refusal, explicit
development preflight, and unchanged inputs/no subprocess build. Existing Gen6,
save-manifest and recursive package-audit checks also passed. The initial run
had one fixture error: its mocked `nm` output omitted the generator's already
required party symbols. That failed log is retained; production behavior was not
changed to accommodate it.

A separate invocation used candidate 10's actual immutable ROM, manifest and
complete runtime bundle with the current `build_launcher.py --preflight-only`.
The existing Python 3.14.4/PyInstaller 6.22.3 build environment refused it with
`normal player packaging requires the compiled player build guard` in 1.969
seconds. Every supplied input hash was unchanged, no output directory appeared,
and no build, game, save/world operation, or owner-base read occurred. An earlier
attempt in the host-provisioning environment stopped at its missing PyInstaller
metadata; that distinct environment failure is also retained.

| Candidate 10 input | SHA-256 |
| --- | --- |
| ROM | `0b13865da4947b855cfe8062fd624b284725fd1ccb1ff6172d5680b853fac8d2` |
| Game manifest | `999de8a5f20e4194befa59666508ec37b498dcb191ee54a60b9d8fe428611a70` |
| Runtime manifest | `698dff484ded620615d4002c0758bf14379cdb01cf25750d69499dc1cc6a5a84` |

Private before/after source copies and evidence are under
`%LOCALAPPDATA%/PokemonPrivate/artifacts/player-build-guard-before-20261009-1`.
They contain no newly edited original character or world.

| Evidence | SHA-256 |
| --- | --- |
| Five-file `after-index.json` | `c7e23457119d534427357bbabddea931a3bfaa9d16063a7f8db310a2ee784f21` |
| Passing `focused-tests-2.log` | `915a76d28e3a446e02e436efc7c101475569384a63149b1b9bbb18b205f91e29` |
| `candidate10-second/candidate10-refusal.json` | `80f0394dc33d0029c71a9d69cc09bb391392ad01cab029a3aae5af1af57e223e` |

New native output, its macro changes/source delta, marker verification and any
subsequent package or gameplay acceptance have separate evidence. These Python
checks do not retroactively qualify candidate 10 or a newly built game.
