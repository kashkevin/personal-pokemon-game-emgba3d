# Named Pokémon in the trade menu

October 9, 2026 source-only presentation addition. Trade party choices now show
the Pokémon's species name and level; offer review shows both species names.
Ineligible choices retain their disabled action and get a leading `[X]`, which
remains visible within the native menu width. No eligibility, species, evolution,
shiny, held-item or other gameplay rule changed.

`src/emerald_multiplayer/species_labels.py` contains 721 standard-species display
names extracted from the already incorporated pinned engine. This does not
enable those encounters or grant those Pokémon. Uncatalogued IDs retain an
explicit `No.<ID>` fallback; forms are not guessed from a nearby base ID.
The bounded ASCII native menu folds accents and renders the two Nidoran gender
symbols as `F`/`M`. Game names and native tables remain unchanged.

`scripts/multiplayer/generate_species_labels.py` reads source text only: the
explicit numeric constants and unique literal `.speciesName` fields, including
shared species-info macros. It rejects missing, duplicate or ambiguous standard
entries. It does not compile, import or execute the game, evaluate C conditionals,
or assume conditional gameplay availability. Generation needed support for both
direct initializers and whole-entry macros; its final output covers IDs 1–721.

[Provenance](species-labels-provenance.json) records every input file SHA-256,
native base `aef47e4b28fd6d0e84376961e0cc6632996bb0be`, original incorporated RHH
base `bb1093a7c72d3961d9a37d8e02ad2abc2c866682`, and output SHA-256
`037b7a5d7cd7443393737749fba7645a0a74b0ced3184339d95e89da4307ad86`.
These are factual display labels from the existing dependency, not a new engine,
library or asset import. Existing attribution and release review remain in force.

Only this source-data generator ran. No application import, automated test,
game/core/UI run or build was performed. Actual menu rendering, selection,
confirmation and source/binary alignment still need future verification.
