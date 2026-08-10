# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
xdg-open index.html                  # Run the GUI — no build step, no dependencies

pip install -r cli/requirements.txt  # CLI counterpart (batch mode)
python cli/vis_split.py <dir> --report --dry-run

python3 -m http.server 8080          # Only needed when a file:// restriction gets in the way
                                     # (or to test with browser automation, which refuses file://)
```

There is no build system, no package.json, no test suite, no linter. Changes are verified by opening
the page and loading a real STL. The `main` branch auto-deploys to GitHub Pages
(https://tony1213.github.io/stl-part-editor/) via `.github/workflows/deploy.yml`, which uploads the
repo root as-is — so `index.html` must stay self-contained and buildless. **Do not introduce a
bundler, npm dependencies, or split the app into modules**: "double-click the file and it works,
offline" is the product, not an implementation detail.

## Architecture

`index.html` is the entire browser application (~700 lines: `<style>`, markup, one `<script>`). Everything
runs client-side; no STL ever leaves the machine. Sections in the script are demarcated by
`/* ---------- ... ---------- */` banner comments.

Pipeline, in load order (`load()` at the bottom of the script drives it):

1. **`parseSTL(buf)`** — binary and ASCII STL. Binary is detected by checking `84 + count*50 ===
   byteLength`, because plenty of binary STLs also start with the ASCII magic word `solid`. Returns
   flat `pos` / `nor` Float32Arrays (9 floats per triangle, normals replicated per vertex).
2. **`components(pos,count)`** — welds vertices on a `1e-8 m` quantization grid (matches trimesh's
   `merge_vertices` tolerance), then union-finds triangles across shared edges. **Only edges shared
   by exactly two faces union their triangles.** CAD assemblies routinely have parts touching along
   a shared edge (3+ faces on one edge); unioning those merges a motor into its housing and the
   whole tool stops working. This mirrors trimesh's `face_adjacency`, which also requires
   `require_count=2` — that equivalence is what makes the GUI and the CLI agree face-for-face.
3. **`visibility(g)`** — the core metric. Renders the mesh into an offscreen FBO from `NDIR=64`
   Fibonacci-distributed directions with an orthographic camera. The grid is sized from the model,
   not fixed: `min(600, max(64, ceil(2*radius*1.05 / 0.3mm)))`, mirroring the CLI. A fixed 320²
   grid under-samples large parts (base_link, ~180 mm) and depresses every visibility number, which
   silently deletes borderline components — that bug cost two real parts before it was found.
   Continuing the original description, in "id mode" where each fragment
   writes `gl_VertexID/3 + 1` encoded as RGB. Reading back the pixels gives the set of faces visible
   from outside. A component's visibility = (its visible faces) / (its faces). Components smaller
   than `SLIVER=100` faces skip the test and are always kept (they are zero-area CAD export
   garbage). Face ids are `+1` so 0 stays the background sentinel.
   `visibility()` also stashes the per-face `seen` array on `G` and uploads it as the `aSeen`
   vertex attribute — that is what paints "this face is visible from outside" orange, both on the
   selected part and (in 外露高亮 mode) across every part marked for deletion. `G.hit[c]` keeps the
   per-component visible-face count shown in the footer.
   The two remaining view options interact deliberately: 透视待删零件 off normally culls
   delete-marked parts entirely (preview of the export), **except** faces with `aSeen` while 标出外露面
   is on — those stay, painted orange, so the clean preview still shows exactly where the outer
   surface would lose material. Don't "simplify" that exception away; without it the highlight has
   nothing to draw in preview mode, which is the mode where it matters most.
4. **`autoApply()` / `sync()`** — effective state = manual override if present, else
   `visibility < threshold`. `sync()` rewrites the per-vertex `aState` buffer and refreshes the
   table. It must skip table rows without `dataset.c` — the last row is the "N 个碎片" note, not a
   component.
5. **`exportSTL()`** — writes a binary STL of the kept triangles, reusing the original coordinates
   and normals verbatim. Output is always an exact subset of the input.

### Rendering

One WebGL2 program does everything, switched by the `uMode` uniform: `0` = shaded view, `1` = id
buffer (used by both `visibility()` and `pick()`). Hidden geometry is culled in the vertex shader by
emitting `gl_Position = vec4(0,0,2,1)` (outside the clip volume) rather than by re-uploading buffers,
so toggling "show deleted" / "isolate" costs nothing.

The shaded view draws in up to two passes, selected by `uPass`. Pass 0 is the normal scene. Pass 1
is the **through-wall highlight**: depth test off, backface culling on, blending on, and the vertex
shader keeps only the selected component (alpha .66) plus, when 透视待删零件 is on, every
delete-marked component (alpha .24) — so internal parts show through the housing instead of being
invisible behind it. This pass is always available; there is no user-facing toggle for it, and
`frame()` is likewise always applied on selection (both were checkboxes once — the user removed
them as noise). An earlier attempt ghosted *the rest of the model*
with alpha instead; don't go back to that. Layered unsorted transparency (shell front faces + back
faces + other internals) accumulates into a white wash and the part gets harder to see, not easier.

`frame(c)` flies the camera to a component using the per-component bounding boxes (`G.cmin/cmax`,
built in `load()`). Its distance is `max(partRadius*4, modelRadius*1.5)` — the floor matters: zoom
in closer than that on a small internal part and the camera ends up *inside* the housing.

Per-vertex attributes: `aPos`, `aNrm`, `aComp` (component id, used for hover/selection compare in
the shader), `aState` (0 keep / 1 delete — the only buffer that gets rewritten on edits).

`pick(x,y)` renders the id buffer at canvas resolution into the FBO and reads back a single pixel.
The FBO is shared with `visibility()` and resized on demand by `fboSize(n)`.

### State

`G` holds the whole loaded model (`pos`, `nor`, `lab`, `size`, `vis`, `del`, `manual`, `sel`,
`hover`, …). `G.manual` is a `Map<compId, boolean>` of user overrides; clearing it returns to pure
threshold behavior. `G.del` is the resolved per-component decision that the shader and exporter read.

## Conventions

- UI text is Chinese; code comments are Chinese; this file is English (same split as the author's
  other repos).
- `<meta charset="utf-8">` must stay on line 1 — without it, opening the file over `file://` renders
  the Chinese UI as mojibake.
- **`index.html` and `cli/vis_split.py` implement the same criterion twice** (WebGL vs
  trimesh+Embree) and must stay interchangeable: same welding tolerance, same manifold-edge rule,
  same 100-face sliver floor, same visibility definition, same default threshold. Change one, change
  the other. The reference check: `chest_pitch_link.STL` (106,586 faces) must yield 46 components
  and 41,968 kept faces at threshold 0.05 in both.
- Never modify geometry. Deleting whole connected components is the only permitted edit; the export
  must stay a strict subset of the input triangles. No decimation, no remeshing, no transforms.
