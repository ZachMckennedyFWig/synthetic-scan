# How the simulator works

The short version: we **scan the CAD part with a virtual scanner**, the way a
real one does, rather than adding noise to the CAD mesh. Every artifact then
appears where it physically would. The research behind each number is in
[research/scan-artifacts.md](research/scan-artifacts.md) (§ references below
point there).

```
part (CAD frame) ──► placement on the table (1 or 2 sessions, flipped)
                 ──► camera path (turntable rings | handheld random walk)
                 ──► per frame: Embree ray cast ──► visibility ──► surface response ──► range noise
                                                ──► depth firmware ──► markers  =  depth image
                 ──► pose estimate per frame (drift walk + jumps + loop closure; session offset)
                 ──► fusion (TSDF | TSDF→Poisson | Poisson)
                 ──► post (islands, hole fill, smoothing, decimation, defects)
                 ──► calibration scale + export pose ──► scan.stl
```

| Stage | Code |
|---|---|
| parameters | `profiles.py` (priors), `randomness.py` (distributions, seeding) |
| placement, path, capture, registration | `scanner.py` |
| fusion, post, export pose | `meshing.py` |
| orchestration, `meta.json` | `pipeline.py` |
| metrics | `metrics.py` |

## Artifact catalogue

**Status**: ✅ simulated from the physical cause · 🟡 simplified · ⏸ parked
(see PARKED.md). Parameter names are `group.key` in `meta.json → params`.

| Artifact (research §) | How | Parameters | Status |
|---|---|---|---|
| Range noise (2.1) | Per pixel, along the ray. σ = `sigma_mm` · (z/z₀)^`distance_exp` · cos θ^−`incidence_gamma` · (1 + 2·dark + 0.5·shiny) · per-frame exposure | `noise.sigma_mm`, `distance_exp`, `incidence_gamma`, `exposure_jitter` | ✅ |
| Spatially correlated noise (4.4) | Mix of white noise and a Gaussian-filtered noise field (no i.i.d. "fake scan" look) | `noise.corr_px`, `corr_share` | ✅ |
| Heavy-tailed decoding errors (2.1) | A fraction of pixels get noise × `tail_mult` | `noise.tail_frac`, `tail_mult` | ✅ |
| Banding / striation (2.19) | Sine ripple along image rows (the stripe direction), random phase per frame. A hand rolls the scanner, so its direction varies | `noise.banding_mm`, `banding_period_px` | ✅ |
| Edge rounding (2.3) | Emerges from pixel footprint + edge-preserving depth blur (blurs across creases, never across depth jumps) + TSDF voxel / Poisson octree size | `noise.smooth_px`, `smooth_jump_mm`, `fusion.voxel_mult` | ✅ |
| Small-feature and chamfer loss (2.4) | Emergent: features smaller than ~2 voxels or pixels vanish | `capture.spacing_mm`, `fusion.voxel_mult` | ✅ |
| Thin walls merging or perforating (2.5) | Emergent from the TSDF truncation band and Poisson | `fusion.trunc_vox` | ✅ |
| Occlusion holes: pockets, bores, undercuts (2.6) | Camera line of sight (ray cast) **and projector line of sight** (shadow rays from each hit toward a projector `baseline_mm` along the camera x-axis) | `capture.baseline_mm`, `visibility.projector_shadow` | ✅ |
| Grazing-angle dropout (2.6) | Soft cut-off at `grazing_cos` × U(0.6, 1.4) | `visibility.grazing_cos` | ✅ |
| Working-range clipping | Points outside the depth of field are dropped | `capture.distance_mm`, `dof_frac` | ✅ |
| Underside never seen (2.7) | The part rests on a real plane in the scene (on a convex-hull facet, area-weighted) | `base.support` | ✅ |
| Plane-cut error, bottom band lost (2.7) | Part points below `cut_mm` are removed with the table | `base.cut_mm` | ✅ |
| Turntable remnant skirt (2.7) | Plane points within `remnant_mm` of the part's contact outline are kept | `base.remnant`, `remnant_mm` | ✅ |
| Flip-and-merge second pass (2.13) | A second placement on the most opposite facet, with a rigid merge residual | `capture.sessions`, `registration.session_deg`, `session_mm` | ✅ |
| Shiny surfaces: dropout and saturation (2.8) | A smooth random 3D "shiny" field plus whole shiny B-rep faces (machined flats). Low diffuse return → dropout; specular half-vector term over `saturation` → hole or spike | `surface.shiny_frac`, `shiny_scale_mm`, `shiny_face_p`, `specular_exp`, `saturation`, `dropout_gain` | ✅ |
| Dark surfaces (2.8) | A random "dark" field: less return (more dropout), more noise | `surface.dark_frac`, `dark_scale_mm` | ✅ |
| Specular spikes (2.9) | Saturated pixels sometimes survive, displaced along the ray | `surface.spike_p`, `spike_mm` | 🟡 no true inter-reflection ray bounce |
| Flying or mixed pixels (2.10) | At depth discontinuities, near pixels are blended toward the far neighbour | `noise.mixed_pixel_p`, `smooth_jump_mm` | ✅ |
| Silhouette erosion | The valid mask is eroded by k pixels | `noise.edge_erode_px` | ✅ |
| Outliers (2.11) | Sparse uniform range errors | `noise.outlier_frac`, `outlier_mm` | ✅ |
| Floating fragments (2.11, 2.25) | Lumpy blobs near the surface, at low rate | `post.floaters` | 🟡 no hands, clamps or putty geometry |
| Tracking drift (2.12) | se(3) random walk per frame about the part centre | `registration.drift_deg`, `drift_mm` | ✅ |
| Loop-closure residual (2.14) | A fraction of the end drift is removed linearly | `registration.loop_closure` | ✅ |
| Lost-tracking jump (2.12) | One step offset for the rest of the pass | `registration.jump_p`, `jump_deg`, `jump_mm` | ✅ |
| Per-frame pose jitter | Independent small pose noise | `registration.jitter_deg`, `jitter_mm` | ✅ |
| Global scale error (2.15) | Per-axis scale about the part centre; **not** undone by `scan_to_cad` | `registration.scale_sigma`, `scale_aniso` | ✅ |
| Marker stickers (2.16) | Poisson-disc sticker centres on the surface: a masked hole, or a 0.15 mm bump | `surface.markers_per_100cm2`, `marker_radius_mm`, `marker_mode` | ✅ |
| Spray coat (2.17) | Outward offset with smooth ±40% thickness variation; spray removes shine and darkness (`cohere`) | `surface.spray_um` | 🟡 no pooling in concave corners |
| Non-uniform sampling density (2.18) | Emergent from path, distance and incidence | (path) | ✅ |
| Motion-blurred frames | Frames dropped at random | `capture.frame_drop_p` | ✅ |
| Hole fill, flat or tented caps (2.20) | Our own boundary-loop fan filler, all holes or under a radius | `post.hole_fill`, `hole_fill_mm` | ✅ |
| Hole fill, bulging watertight caps (2.20) | Screened Poisson extrapolates unseen regions | `fusion.method` = `poisson` / `tsdf_poisson`, `density_trim_q` = 0 | ✅ |
| Ragged open borders | Poisson density trimming | `fusion.density_trim_q` | ✅ |
| Over-smoothing (2.21) | Taubin, Laplacian (shrinks) or simple averaging | `post.smoothing`, `smooth_iters` | ✅ |
| Sharpening overshoot (2.22) | — | — | ⏸ `SIM-04` |
| Decimation faceting (2.23) | Quadric (bimodal triangle sizes) or vertex clustering (grid-aligned) | `post.decimate`, `decimator` | ✅ |
| Flipped normals, duplicate faces (2.24) | Low-rate defect injector | `post.flip_patches`, `dup_faces` | ✅ |
| Small floating islands removed or kept (2.25) | "Remove floating parts" with a random size fraction; fragments under 30 triangles always go | `post.keep_islands`, `island_frac` | ✅ |
| Export frame (4.4) | Upright with random yaw (turntable apps) or arbitrary rotation, plus an offset | `output.pose`, `offset_mm` | ✅ |
| Systematic material bias, translucency (2.2) | — | — | ⏸ `SIM-01` |
| Laser edge stair-step / overshoot (Abbasinejad) | — | — | ⏸ `SIM-02` |
| Texture-driven photogrammetry holes | Approximated by the dark field in the `phone` profile | — | 🟡 `SIM-03` |
| Ball-pivoting / alpha-shape meshers (4.4 item 1) | — | — | ⏸ `MESH-01` |

## Randomization: against generator fingerprints (research §4.4)

- **Profiles are priors, not presets.** `random` picks one of five correlated
  bundles (P1–P5) by weight. 15% of `random` samples are drawn **wild**:
  every range is widened ×1.6 and the categorical weights are flattened.
- **Algorithms vary, not just numbers:** 3 fusers, 4 smoothing choices,
  2 decimators, 3 hole-fill modes, 3 export poses.
- **Surface properties are smooth random 3D fields**, so dropout patches have
  organic shapes unrelated to the triangulation. Only the "machined face"
  shininess follows B-rep faces, as it physically does.
- **The operator picks a finer setting for a small part** (`profiles.OPERATOR`, profiles v2):
  when the fusion voxel would leave fewer than `voxels_across_min` (U(6, 12), proposed) voxels
  across the part's middle extent, the capture spacing is made finer, but never finer than the
  profile's finest. The thinnest extent is ignored, so thin walls still merge in the fusion.
  Recorded as `derived.operator_spacing_mm`.
- **`cohere()`** restores physical correlations after sampling: spray means
  matte; markers mean low drift and no jumps; a turntable means a plane.
- **Splits are per part**, so held-out parts stay held out.

## Performance

Measured on the dev box (Ryzen 7 3700X 8C/16T), PLAN.md §4. Caps that
keep a sample bounded (each is recorded in `derived` when it fires):

| Cap | Value | Why |
|---|---|---|
| `MAX_RAYS_PER_SAMPLE` | 30 M | over budget, the capture spacing is coarsened (never frames dropped: that left straight field-of-view-edge gaps, a fingerprint). Recorded as `derived.capture_spacing_mm` |
| `MAX_SURFACE_VOXELS` | 6e5 | floors the TSDF voxel and the Poisson octree depth (~1–1.5 M triangles before decimation); capture spacing is floored at 0.6× that voxel, since finer detail is fused away anyway |
| `MAX_POISSON_POINTS` | 1 M | Poisson time is roughly linear in points |
| frames per sample | 400 | |

Determinism: every random draw comes from the sample's own RNG, and the fused
mesh is put into a canonical order (`meshing.canonical`) before any
order-sensitive step. The same part, seed and version give a byte-identical
`scan.stl` on any machine and worker count (`tests/test_pipeline.py`).

## Known Open3D 0.20 (Windows wheel) pitfalls

- Legacy `ScalableTSDFVolume.integrate` produces nothing, whatever the depth
  type, so we use the tensor `VoxelBlockGrid`.
- `t.geometry.TriangleMesh.fill_holes` (VTK) silently fills nothing on simple
  holes, so we use our own `meshing.fill_holes`.
- `create_rays_pinhole` shoots through pixel **centres** (u + 0.5).
  Back-projection must match, or every point is biased half a pixel.
