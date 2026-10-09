# Eighteen-starter selection

Implemented in source after the owner's instruction to stop testing and continue
development on October 8, 2026. No build or gameplay check was run for this change.

The additive [engine patch](../engine-patches/phase6-eighteen-starters.patch)
extends the existing Birch bag screen to six pages: Hoenn, Kanto, Johto, Sinnoh,
Unova and Kalos. Left/Right selects Grass, Fire or Water; Up/Down or L/R changes
page. A opens the existing animated sprite and Yes/No confirmation. Declining
returns to the same page and choice. Each player independently receives their
selection through the ordinary `ScriptGiveMon` path at level five. There is no
server-wide uniqueness restriction, generated save or inventory injection.

The engine's three balls, hand, label windows, front sprites, cries, confirmation,
first battle and nickname flow are reused. Only one chosen Pokémon sprite is
loaded at a time; no new art, dependency or renderer is imported. Source inspection
covered the pinned RHH `bb1093a7` foundation, the existing integrated engine,
and [maintained upstream's selector](https://github.com/rh-hideout/pokeemerald-expansion/blob/master/src/starter_choose.c).
The [existing reuse audit](customization-and-reuse.md) and
[Gen 6 audit](gen6-foundation-update.md) apply. A separate selector framework
would add integration work without improving this bounded six-page requirement.

`VAR_STARTER_MON` still stores the existing Grass/Fire/Water role, so rival
parties and existing campaign branches retain their behavior. The actual selected
species is recovered through a tagged choice in previously unused script variable
`0x40DB`, now `VAR_MULTIPLAYER_STARTER_CHOICE`. Source searches found that address
only in unused Emerald/FRLG constant declarations before allocation. No saveblock,
species enumeration, ownership record or party layout changes. Zero/invalid or
role-mismatched tags fall back to the original starter rule for existing saves.
`IsStarterInParty` and the credits now read the actual saved choice. FRLG keeps
its original single page and does not write the new variable.

Source files: `src/starter_choose.c`, `include/starter_choose.h`,
`src/battle_setup.c`, `src/field_specials.c`, `src/credits.c`, and
`include/constants/vars.h` in the private engine worktree
`/home/kevin/src/pokemon/engine-admission-cleanup-20261008-1`.
The exact original six files and before/after hashes are retained privately in
`/home/kevin/src/pokemon/multiplayer-proof/starter-selector-source-20261008-1`.
The patch applies after the retained admission-cleanup source; it does not replace
that milestone or any existing binary.

This does not configure the complete Gen 6 battle ruleset, change shiny odds,
select encounter weights, alter rival balancing or add customization. Actual
screen fit, compilation, all 18 selections, native save/reload and multiplayer
enrollment remain unverified because testing was explicitly stopped. Existing
package 7 and compiled game artifacts do not contain this source change.
