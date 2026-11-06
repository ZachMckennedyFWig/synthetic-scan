# Parked

This page lists known gaps we have decided not to fix in code for now, each in a class from [WHAT-IS-A-BUG.md](WHAT-IS-A-BUG.md) section 3.

If you have a real scan showing one of these (E1), open an issue and name the ID. That can move the row into scope. The owner saying a row matters (E4) does the same. Agents name the ID to their user and write no code for it.

## IDs

Each row has an ID made of an area and a number, like `SIM-01`. An ID never changes and is never reused. Agents propose rows with `NEW` as the ID, and the owner gives it one.

| Area | Covers |
|---|---|
| `SIM` | The virtual scanner: capture, surface response, noise, registration |
| `MESH` | Fusion, meshing, post-processing |
| `GT` | Loading CAD, tessellation, labels, metrics |
| `DATA` | Dataset layout, batch runs, CAD sources |
| `APP` | Scan Lab UI and server |
| `EVAL` | The ScanRuler harness |

## 3.1 An artifact nobody has shown on a real scan (yet)

Reopen with E1: a real scan that shows it, with a magnitude.

| ID | Gap | Where |
|---|---|---|
| `SIM-01` | No systematic material bias (subsurface scattering in translucent plastics, which shifts the surface inward 0.05–0.3 mm) | research §2.2 |
| `SIM-02` | No laser-line edge stair-step or overshoot on edges perpendicular to the baseline (Abbasinejad 2009) | research §5 |
| `SIM-03` | Photogrammetry is approximated: no texture-driven matching failure, only the `dark` field and heavy correlated noise | research §1.2, P5 |
| `SIM-04` | No sharpening (unsharp mask) post-filter or its overshoot | research §2.22 |
| `SIM-05` | Inter-reflection ghosts are spikes along the ray, not mirror-bounce false surfaces in concave shiny regions | research §2.9 |
| `SIM-06` | Spray-coat pooling in concave corners (fillet-like build-up) isn't modelled; only an even ±40% coat | research §2.17 |
| `SIM-07` | No lateral (in-plane) noise distinct from range noise; lateral error comes only from pixel footprint and blur | research §1.2 (Nguyen 2012) |
| `SIM-08` | No distractor geometry (hands, clamps, putty, fixtures) attached to or near the part | research §2.11 |
| `MESH-01` | No ball-pivoting or alpha-shape mesher (research §4.4 asks for 3 or more meshers; we have 3 fusion paths) | research §3.3 |
| `MESH-02` | No real ICP / pose-graph registration: pose error is sampled, not produced by running the registration | research §3.3 step 2 |

## 3.3 Upstream library limits

| ID | Gap | Where |
|---|---|---|
| `MESH-03` | The GPU (RTX 4070) is unused: Open3D's Windows wheel is CPU-only. A CUDA build or a Linux box could run VoxelBlockGrid on the GPU | PLAN §4 |
