# Battle transitions and the battle's opening in 3D (2026-10-27)

The queued work "battle transition + battle-opening camera fixes in 3D": MS-106, MS-107 and MS-109 from
`docs/ui-overhaul-and-fixes-20261026.md`. Nothing here is packaged.

Where a result comes from: **L** this Linux machine (real game processes of the 3D build and the 3D test build; the 3D
view through Mesa's software OpenGL). Nothing here was tried on Windows, on a real graphics card or on a player's PC.

## MS-106: the Frontier's squares (fixed, engine `739817fe`, PC only)

**What was wrong.** Over the 3D field, a transition's own picture (the GBA's 240 x 160) is laid where the field's
tiles are, and the rest of the window gets each picture line's edge colour stretched out. The Battle Frontier's three
squares transitions (the grid, its scroll and its spiral) fill the GBA screen's 8-pixel side margins solid: stretched,
they made a black frame round the 3D field. In the scroll, the squares passing the picture's edge became stripes, and
bands of solid colour above and beside the picture.

**What changed.** For those three the grid is carried out as squares. The part of the picture that holds whole
squares (seven across and five down, or fewer when the scroll has moved the grid; the renderer now records BG0's scroll
for each frame) is shown as it is, and copies of it at its own size cover the rest of the window, the picture's own
margins included. The squares now cover the window as they cover the GBA's screen; the field shows through where no
square is yet, and the squares are erased to black as on the GBA. The picture's text box is not drawn a second time
over them (it brought the margins back as two black bars).

## MS-107: the flash's peak (fixed, engine `739817fe`, PC only)

**What was wrong.** At the peak of the two white flashes that open a transition, the game turns every colour into one
grey. The Classic 2D picture is then plain grey; the 3D view drew the 3D field lit in that grey, which looked like the
field without its textures.

**What changed.** While a transition is drawn over the 3D field and the game has faded every colour into one, the field
under the transition's picture is that colour whole (people included), as the GBA shows it. It also covers the fade to
black at a transition's end (it was already black).

## Tests (L)

| Test | Result |
|---|---|
| The three squares transitions (`PKMN_DEBUG_TRANSITION` 27, 28, 29 on Mauville's field, 3D build), pictured every 3 or 6 frames, before and after | Before (28, pictured today): stripes and bands of solid colour; the black frame of 27 and 29 is in MS-106's pictures of 2026-10-26. After: the squares across the whole window in all three, whole squares only (the scroll's grid aligned), erased to black; no frame, stripe, band or bar |
| The flash, pictured every frame (transition 28, frames 138-169), against the Classic 2D view | Before: one frame of the 3D field lit grey. After: the two peaks (145, 161) plain grey, as the 2D view's |
| Other transitions after the change: 0 (blur), 3 (big Poke Ball), 12 (mugshot), 22 (black hole), 31 (Frontier circles) | as before |
| A real wild battle's start (3D test build): Route 104's tall grass; Oldale Town beside the Poke Mart and the Pokemon Center | the flash, the transition and the opening as expected; the battle starts |
| `check-diorama` (compositor goldens, rules), GBA ROM, Classic 2D build | passes; ROM **unchanged** (`f214735b...`); builds |

Evidence: scratchpad `trans/` (before: `t28-pre`, `t28-2d`; after: `t27-fix3`, `t28-fix3`, `t29-fix2`, `flash-fix`,
`t0/3/12/22/31-fix2`), `ms109/`.

## MS-109: the battle's opening camera (open: cause found, not changed today)

Reproduced in Oldale Town north of the Poke Mart (the 3D test build, a wild battle): for about half a second of the
opening swoop, the roof of the house far south of the player fills the bottom of the picture. At rest the stage's view
is clear (it is chosen so). The cause: the swoop's dolly zoom narrows the view and pulls the camera back along its own
line of sight, up to about 1.7 times as far, so it passes behind buildings and grass the field's and the stage's views
never cross (`StepCamera` in `gl_battle.c`). On Route 104's grass (24, 57) it was not seen.

Not changed today: a fix means either a near clipping plane that moves with the swoop (each 3D renderer's shader has
its own fixed one) or a swoop that stops pulling back at the first tall cell behind it (a change to the opening's look).
Both need testing in many places; kept for the next session.

## Not done

* MS-108 (the transitions' own pictures are the GBA's art) is art, not a broken screen; unchanged.
* Not tried on Windows, on a real graphics card or on a player's PC; the squares transitions not in a real Frontier
  battle (the debug transition plays them as a battle's start does).
