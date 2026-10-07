# Headless baseline frontend

This development tool runs the ordinary, unmodified baseline GBA ROM using the
official libmGBA core. It sends emulated joypad input and captures the core's
framebuffer. It does not operate the desktop, write emulated RAM, apply cheats,
or load savestates. Flash saving still happens through the game's Save menu.

Build against mGBA tag `0.10.5`, commit
`26b7884bc25a5933960f3cdcd98bac1ae14d42e2`, in Ubuntu WSL:

```bash
bash scripts/baseline-headless/build.sh \
  /home/kevin/src/pokemon/mgba-baseline-harness \
  /home/kevin/src/pokemon/baseline-proof
```

The source checkout is separate from the Emerald engine. CMake, a C compiler,
and libpng development headers are required. The source directory's `build`
folder contains the shared library; the frontend's runtime path points there.

Use a ROM copy and a separate Flash save under `baseline-proof`:

```bash
/home/kevin/src/pokemon/baseline-proof/harness \
  /home/kevin/src/pokemon/baseline-proof/client-a/baseline.gba \
  /home/kevin/src/pokemon/baseline-proof/client-a/baseline.sav
```

The tool refuses save paths without `/baseline-proof/`. Never pass an existing
player save directly; copy it into the dedicated proof directory first.

Commands are newline-delimited:

| Command | Meaning |
| --- | --- |
| `F mask frames` | Hold hexadecimal button mask for that many emulated frames. |
| `P /absolute/path.png` | Write a screenshot from the emulated framebuffer. |
| `R address bytes` | Read hexadecimal emulated bus address, maximum 4096 bytes. |
| `Q` | Unload the ROM and close the core normally. |

GBA button masks: A `1`, B `2`, Select `4`, Start `8`, Right `10`, Left `20`,
Up `40`, Down `80`, R `100`, L `200`. Send `F 0 frames` to release buttons.
Inputs during cutscenes or battles do not imply movement occurred. Inspect
framebuffer and live object coordinates before choosing the next movement.

The verified Continue sequence for this baseline was:

```text
F 0 1000
F 8 8
F 0 480
F 8 8
F 0 180
F 1 8
F 0 300
```

Saving over an existing save requires both confirmations. Explicitly select
Yes on the overwrite prompt, wait for saving to finish, confirm the Flash hash
changed, close the core, and verify Continue in a fresh process. A visible
confirmation prompt is not proof that saving completed.
