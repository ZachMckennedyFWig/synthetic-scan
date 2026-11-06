# Dataset format

What `synthscan run` (or a Scan Lab job) writes, and what each field means. The
code that writes it is `src/synthscan/dataset.py` and `pipeline.py`; change
this page in the same PR as any change to the format, and bump `schema` in
`meta.json` when a field changes meaning.

## Layout

```
data/datasets/<name>/
  dataset.json            {name, created (unix s), generator_version}
  inputs/                 source files exactly as uploaded (+ optional <stem>.params.json)
  parts/<part_id>/
    gt.stl                ground-truth tessellation, CAD frame, mm
    gt.npz                vertices (n,3) f64, faces (m,3) i64, face_ids (m,) i32
    part.json             summary + analytic face labels + design params
  samples/<sample_id>/
    scan.stl              THE DELIVERABLE: the synthetic scan, scan frame, mm, binary STL
    meta.json             everything about how it was made and how good it is
    points.ply            fused raw points, scan frame (only with --save-points)
    .view-<layer>.npz     viewer cache (Scan Lab writes it; safe to delete)
  manifest.jsonl          one SampleRow per finished sample (docs/API.md); last row per id wins
  failures.jsonl          {input, sample|null, error, time} per failure
```

- `part_id` = `<slug of file stem>-<first 8 hex of the file's sha1>`. The same
  file uploaded twice is one part, and a changed file is a new part.
- `sample_id` = `<part_id>__<profile>-<seed>-<index:03d>`. A job "ensures N
  samples for (profile, seed)"; re-running it skips the ones that exist.
- **Splits are per part** (`split_for(sha1)`: 80/10/10 train/val/test by
  content hash). Every sample of a part is in the same split, so a test part
  is never seen in training under *any* artifact pattern.

## `part.json`

| Field | Meaning |
|---|---|
| `extents_mm`, `bbox_min`, `bbox_max`, `area_mm2`, `volume_mm3` | of the GT tessellation |
| `watertight` | if false, deviations are unsigned |
| `n_brep_faces` | B-rep faces (STEP) or coplanar facet groups (meshes) |
| `features[]` | STEP only: one per B-rep face. `type` (plane, cylinder, cone, sphere, torus, bspline, ...), `area_mm2`, and per type `origin`/`normal`, `radius`/`axis`/`concave` (hole vs boss), `apex`/`half_angle_rad`, `center`, `major_radius`/`minor_radius` |
| `design_params` | procedural parts: the generator's exact design (hole Ø, pitch, fillet r, ...) |
| `notes[]` | anything the loader repaired |

## `meta.json`

| Field | Meaning |
|---|---|
| `schema` | format version (1) |
| `generator` | `{name, version}` |
| `sample_id`, `sample_index`, `input`, `part_id`, `part_name`, `part_sha1`, `split` | identity |
| `seed` | `{global, sample_index}`: with the part's sha1, this regenerates the sample byte-for-byte (same generator version) |
| `profile`, `requested_profile` | the profile used, and what the job asked for (`random` picks one per sample) |
| `params` | **every sampled parameter**, grouped like the profile spec (`capture`, `noise`, `visibility`, `surface`, `registration`, `base`, `fusion`, `post`, `output`), plus `wild` (drawn with widened ranges), `profiles_version`, `operator` (`voxels_across_min`: the resolution the operator accepts for the part's size) and any `overrides` |
| `derived` | what the simulation computed from the params: `frames` per session, `voxel_mm`, `poisson_depth`, `markers_placed`, `tracking_jumps`, `operator_spacing_mm` (when the operator chose a finer setting), `capture_spacing_mm`, `capture_totals` (pixels, hits, visible, lit, returned, kept, remnant_px, dropped_frames), `post_fired`, `holes_filled`, `scale_xyz`, budget flags |
| `artifacts[]` | names of the artifact stages that actually fired (filter/aggregate by these) |
| `metrics` | see below |
| `transforms.cad_to_scan`, `transforms.scan_to_cad` | 4x4 rigid. `scan.stl` vertices × `scan_to_cad` = CAD frame. The calibration **scale** error is deliberately *not* in these (it is part of the error) |
| `files` | `{scan, points}` |
| `timings_s` | per stage |

### Metrics (all mm, CAD frame, against the exact GT tessellation)

| Field | Meaning |
|---|---|
| `scan_to_gt.{mean,rms,p95,max}` | over scan vertices: noise, rounding, ghosts, spikes, fills, scale |
| `gt_to_scan.{mean,rms,p95,max}` | over 120k area-uniform GT samples: what's **missing** |
| `chamfer_mm` | mean of the two means |
| `hausdorff_mm` | max of the two maxima |
| `rms_mm` | `scan_to_gt.rms` |
| `coverage` | fraction of GT area within `coverage_tol_mm` (0.5) of the scan |
| `signed`, `mean_signed_mm` | signed only for a watertight GT; + = outside the solid |
| `n_vertices`, `n_tris`, `watertight`, `n_components`, `n_boundary_edges`, `n_nonmanifold_edges` | topology of the exported mesh |

## Export for an evaluation harness

`synthscan export <name> <out> [--split test]` writes `scans/<id>.stl` (what a
model may see), `gt/<part_id>.stl`, `gt/<part_id>.step` (the source STEP, when the
input was one), and `tasks.jsonl` with `{id, scan, units, hidden: {gt, gt_step,
scan_to_cad, features, design_params, profile, artifacts, metrics}}`. `gt_step` is
null for mesh inputs. **`hidden` must never reach the model under test.** The
ScanRuler bench reads only `id`, `scan` and `units`, and copies the scan into a
job folder of its own as `scan.stl` (docs/HARNESS.md).

Cylinder labels in `features` carry `span_deg`, the angle the face wraps round
its axis (from the face's UV bounds). A bore is one or more coaxial concave faces
of one radius adding up to 360°; an internal fillet is a quarter turn. Parts
prepared before this field existed lack it, and the grader then assumes 360°.

## Licensing

A dataset inherits the licences of its inputs. Never publish a dataset built
from McMaster-Carr, MakerWorld, GrabCAD or TraceParts files: their terms
forbid redistribution and (McMaster) any AI use. See
[research/cad-sources.md](research/cad-sources.md) and PLAN.md §0.
