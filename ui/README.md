# Scan Lab UI

Viewer and batch front end for synthscan. It uploads CAD parts, runs generation
jobs, and compares each ground-truth part with its synthetic scan in 3D.
Implements `docs/API.md` exactly.

React 19 + Vite 7 + TypeScript (strict) + zustand 5 + three. No other runtime deps.

## Dev / build

```sh
npm install
npm run dev      # http://localhost:5173, proxies /api -> http://127.0.0.1:8849
npm run build    # tsc -b && vite build -> dist/, which `synthscan serve` serves at /
```

The app works with the backend down: the status dot goes red, the canvas shows
how to start it, and a health loop (every 2 s offline, 5 s online)
bootstraps everything as soon as `/api/health` answers. You don't need to reload.

## Layout

- **Tab bar**: `Batch` is pinned left. Each opened sample gets a tab,
  named `part #n` and dimmed by tri count. `+` focuses the dataset filter.
- **Canvas**: a split grid of 3D panes that all share one camera.
- **Panel**: DATASET (picker, create, filter, sort, windowed sample list),
  LAYERS (gt / scan / points / coverage), DISPLAY, INSPECTOR (metrics, the
  `meta.params` tree rendered generically, artifact badges).
- **Status bar**: backend dot, cpu/workers, dataset counts, mode pill,
  split count, job progress, and the keyboard hints.

Keys: `Space` flips scan+ghost / GT · `S` GT|Scan split · `D` heatmap ·
`W` wireframe · `F` fit · `1`-`4` toggle layer (`Alt` isolates) · `Tab` next tab ·
`Esc` leaves split or clears the selection · `Enter` splits the selection. Mouse:
left-drag orbits, right/middle or Shift-drag pans, the wheel zooms at the cursor,
and double-click fits. Keys typed into inputs are never captured.

## Architecture notes

**Single renderer, scissor split** (`src/render/stage.ts`). One `WebGLRenderer`
draws on one canvas that covers the whole canvas area. The panes are transparent
DOM boxes on top of it, and each frame renders the shared scene once per pane
with `setViewport`/`setScissor` set to that pane's rectangle. The rectangles are
measured by ResizeObserver, never per frame. All panes use one camera, so they
are locked together without any syncing code. Meshes are uploaded to the GPU once
no matter how many panes show them. Panes differ only in which objects are
visible while they draw. The stage first clears to the border colour and each
pane then clears its own box, which leaves the 1px grid gaps showing as
FootprintUi's split borders.

**Viewport controller** (`src/render/viewportController.ts`,
`src/render/gestures.ts`). Camera state is a per-tab turntable (target, radius,
azimuth, elevation; Z-up) kept outside React. Native pointer and wheel
listeners change it in place and notify the stage, which sets a dirty flag.
A single rAF loop draws at most one frame per vsync, and only when that flag is
set. Gestures never call `setState`. The mm scale bar is written straight to
the DOM by the stage.

**SSG1 parsing** (`src/lib/ssg1.ts`). Every section is 4-byte aligned, so on
little-endian hosts the positions, indices and scalars are zero-copy typed-array
views into the response `ArrayBuffer`. A big-endian fallback copies through
`DataView`. A 404 on a layer means the sample has no such layer (for example
`points` when the job didn't save them); it is not an error.

**Colour by deviation in the shader** (`src/render/colormap.ts`). The scalar is
a vertex attribute. Stock `MeshStandardMaterial`/`PointsMaterial` are patched
via `onBeforeCompile` to colour by it through shared uniforms: diverging
blue/grey/red for deviation, sequential for coverage. Moving the range slider
therefore writes one uniform. It never rewrites a colour buffer.

**Geometry cache** (`src/render/geometryCache.ts`). BufferGeometry lives here,
not in zustand; the store keeps only per-layer status and counts. Entries are
keyed per sample in an LRU of 6 samples. Closing a tab evicts its sample at once:
the stage drops its meshes first, then the geometry is disposed. Loads that are
still in flight for an evicted sample are aborted.

**Stores**. `useStore` holds viewer state: tabs, layers, mode, display options
and the dataset browser. `useBatch` holds uploads (XHR per file, 4 concurrent,
progress throttled to about 10 Hz), inputs and jobs. Jobs are polled every 1 s,
but only while one is queued or running; when a job finishes, samples, inputs
and dataset counts are refreshed. `boot.ts` wires up the health loop and saves
preferences (dataset, open tabs, layers, display, sort) to localStorage.
