# HTTP API (backend ↔ UI contract)

The backend (`synthscan serve`, FastAPI, default `http://127.0.0.1:8849`) serves the
built UI from `ui/dist` and this JSON/binary API under `/api`. One process, one
port: Node is only needed to *build* the UI.

All lengths are **millimetres**. All geometry returned by `/geometry/` is in the
**CAD frame** (the ground-truth part's own coordinates), so every layer overlays
without client-side transforms. The deliverable `scan.stl` on disk is in the
*scan frame* (a random pose, like a real scanner export); the server applies
`meta.transforms.scan_to_cad` before sending it.

## Health and catalogue

| Method | Path | Returns |
|---|---|---|
| GET | `/api/health` | `{ok, version, cpu_count, workers, open3d, step_support, data_dir}` |
| GET | `/api/profiles` | `[{id, label, description, weight}]` — scanner profiles; `random` mixes them |
| GET | `/api/datasets` | `[{name, n_inputs, n_parts, n_samples, created}]` |
| POST | `/api/datasets` | body `{name}` → `{name}` (creates `data/datasets/<name>/`) |

## Inputs (bulk upload)

| Method | Path | Returns |
|---|---|---|
| GET | `/api/datasets/{ds}/inputs` | `[{name, size, format, n_samples, status}]`, `status` ∈ `new` `done` `failed` |
| POST | `/api/datasets/{ds}/inputs` | multipart, field `files` repeated → `{saved: [name], skipped: [{name, reason}]}` |

Accepted formats: `.step .stp` (when `step_support`), `.stl .obj .ply .3mf .glb .off`.

## Jobs (bulk processing)

| Method | Path | Returns |
|---|---|---|
| POST | `/api/jobs` | body `JobRequest` → `{id}` |
| GET | `/api/jobs` | `[Job]`, newest first |
| GET | `/api/jobs/{id}` | `Job` |
| POST | `/api/jobs/{id}/cancel` | `Job` |

```ts
type JobRequest = {
  dataset: string
  profile: string            // 'random' or a profile id
  samples_per_part: number   // 1..64
  seed: number
  inputs?: string[]          // default: every input with status 'new'
  save_points?: boolean      // also write the fused raw point cloud
}
type Job = {
  id: string; dataset: string; profile: string
  state: 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
  total: number; done: number; failed: number
  created: number; started: number | null; finished: number | null   // unix seconds
  eta_s: number | null
  errors: { input: string; sample: string | null; error: string }[]
}
```

Poll `GET /api/jobs` about once a second while any job is `queued`/`running`.

## Samples

| Method | Path | Returns |
|---|---|---|
| GET | `/api/datasets/{ds}/samples` | `[SampleRow]` |
| GET | `/api/datasets/{ds}/samples/{sid}` | the sample's `meta.json` (see [DATASET.md](DATASET.md)) |
| GET | `/api/datasets/{ds}/samples/{sid}/geometry/{layer}` | binary `SSG1`, below |
| GET | `/api/datasets/{ds}/samples/{sid}/files/{name}` | raw file download (`scan.stl`, `points.ply`, `meta.json`) |

```ts
type SampleRow = {
  id: string; part_id: string; part_name: string
  input: string                       // the input file it came from
  sample_index: number                // 0..samples_per_part-1 within its (part, profile, seed)
  seed: number
  split: 'train' | 'val' | 'test'
  profile: string
  artifacts: string[]                 // names of artifact stages that fired
  has_points: boolean                 // the `points` layer exists
  metrics: {
    chamfer_mm: number; hausdorff_mm: number; rms_mm: number
    p95_mm: number                    // 95th percentile |scan -> GT| distance
    coverage: number                  // fraction of GT surface within 0.5 mm of the scan
    n_tris: number; watertight: boolean; n_components: number; n_boundary_edges: number
  }
}
```

`/api/profiles` always lists `random` first. Dataset `created` is unix seconds.

### Geometry layers

| `layer` | What | Faces | Scalar |
|---|---|---|---|
| `gt` | ground-truth tessellation | yes | none |
| `scan` | the synthetic scan mesh, moved into the CAD frame | yes | signed deviation to GT (mm, + = outside) |
| `points` | fused raw points (only if the job saved them) | no | signed deviation to GT |
| `coverage` | points sampled on the GT surface | no | unsigned distance to the scan (mm): large = missing data |

Binary `SSG1` (little-endian, every section 4-byte aligned):

```
offset 0   char[4]  magic "SSG1"
offset 4   u32      n_vertices
offset 8   u32      n_faces          (0 for point layers)
offset 12  u32      flags            bit 0: scalar present
offset 16  f32[3·n_vertices]         positions (x, y, z)
           u32[3·n_faces]            triangle indices
           f32[n_vertices]           scalar, if flag bit 0
```

The server computes deviation scalars lazily on first request and caches them
next to the sample (`.view-<layer>.npz`, gitignored with the data).
