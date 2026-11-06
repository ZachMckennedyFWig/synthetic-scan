"""One sample, end to end: ground-truth part + seed -> scan.stl + meta.json.

``generate_sample`` is a pure function of (part, profile, seed): the same inputs
always produce the same files, on any machine and under any worker count.
Everything random is drawn from the sample's own RNG, and every drawn value is
written to ``meta.json`` (``params``), with what the simulation derived from
it (``derived``) and which artifact stages actually fired (``artifacts``).
"""

from __future__ import annotations

import copy
import json
import math
import time
from pathlib import Path

import numpy as np
import open3d as o3d
import trimesh

from . import __version__
from .meshing import MAX_SURFACE_VOXELS, fuse, output_transform, postprocess
from .metrics import compare
from .parts import Part
from .profiles import finest_spacing, sample_params
from .randomness import sample_rng
from .scanner import (
    capture_frame,
    effective_spacing,
    make_surface,
    plan_sessions,
    registration_errors,
    rigid,
    session_offset,
    transform,
)


def split_for(sha1: str) -> str:
    """Part-level split from the content hash: every sample of a part lands in the same split,
    so no test part is ever seen in training, whatever artifacts it was scanned with."""
    h = int(sha1[:8], 16) % 100
    return "train" if h < 80 else "val" if h < 90 else "test"


def operator_spacing(part: Part, params: dict, derived: dict) -> float:
    """The capture spacing the operator ends up using. If the fusion voxel would leave fewer
    than ``operator.voxels_across_min`` voxels across the part's middle extent, they choose a
    finer setting, down to the scanner's finest. (The thinnest extent is left out: thin walls
    merging in the fusion is a real artifact.)"""
    cap, fp = params["capture"], params["fusion"]
    want = params.get("operator", {}).get("voxels_across_min")
    if not want:
        return cap["spacing_mm"]
    middle = float(np.sort(part.mesh.bounding_box_oriented.extents)[1])
    limit = middle / want / fp["voxel_mult"]
    if cap["spacing_mm"] <= limit:
        return cap["spacing_mm"]
    s = max(limit, min(cap["spacing_mm"], finest_spacing(params["profile"])))
    derived["operator_spacing_mm"] = s
    return s


def generate_sample(
    part: Part,
    sample_index: int,
    profile: str,
    global_seed: int,
    out_dir: Path,
    save_points: bool = False,
    nthreads: int = 0,
    input_name: str | None = None,
    overrides: dict | None = None,
) -> dict:
    """Simulate one scan of ``part`` and write it to ``out_dir``. Returns the meta dict.

    ``overrides`` is a nested dict merged over the sampled parameters, e.g.
    ``{"registration": {"drift_mm": 0}}`` — for ablations ("the same scan without drift")
    and for fast deterministic tests. Overrides are recorded in meta."""
    t0 = time.perf_counter()
    timings: dict[str, float] = {}
    rng = sample_rng(global_seed, part.sha1, sample_index)
    params = sample_params(profile, rng)
    if overrides:
        _deep_update(params, overrides)
        params["overrides"] = overrides
    derived: dict = {}
    lo, hi = part.vertices.min(0), part.vertices.max(0)
    center = (lo + hi) / 2
    radius = float(np.linalg.norm(hi - lo) / 2)
    area = float(part.mesh.area)

    # ``params`` is the record of what was drawn; ``run`` is what is simulated. They differ only
    # where the operator picks a finer setting for a small part, or a resource cap applies
    # (scanner.effective_spacing). ``derived`` records both.
    run = copy.deepcopy(params)
    run["capture"]["spacing_mm"] = operator_spacing(part, params, derived)
    eff = effective_spacing(run["capture"], radius, area, MAX_SURFACE_VOXELS)
    run["capture"]["spacing_mm"] = eff
    derived["capture_spacing_mm"] = eff

    surface = make_surface(part, run["surface"], rng)
    derived["markers_placed"] = int(len(surface.markers))
    sessions = plan_sessions(part, run, rng, derived)
    timings["plan"] = time.perf_counter() - t0

    frames = []
    totals: dict[str, int] = {}
    t = time.perf_counter()
    reg_info: dict = {}
    for s_i, sess in enumerate(sessions):
        errs = registration_errors(len(sess.cam_poses), run["registration"], rng, center, reg_info)
        offset = session_offset(run["registration"], rng, center) if s_i > 0 else np.eye(4)
        to_cad = np.linalg.inv(sess.placement)
        for i, cam_to_world in enumerate(sess.cam_poses):
            if rng.random() < run["capture"]["frame_drop_p"]:  # motion blur: frame rejected
                totals["dropped_frames"] = totals.get("dropped_frames", 0) + 1
                continue
            est = offset @ errs[i] @ to_cad @ cam_to_world
            fr = capture_frame(sess, cam_to_world, est, radius, surface, run, rng, nthreads)
            for k, v in fr.stats.items():
                totals[k] = totals.get(k, 0) + v
            frames.append(fr)
    derived["capture_totals"] = totals
    derived.update(reg_info)
    timings["capture"] = time.perf_counter() - t

    t = time.perf_counter()
    mesh, pts = fuse(frames, run, area, rng, derived, want_points=save_points)
    timings["fusion"] = time.perf_counter() - t
    del frames

    t = time.perf_counter()
    mesh = postprocess(mesh, run, rng, derived)
    timings["post"] = time.perf_counter() - t

    V = np.asarray(mesh.vertices, dtype=np.float64)
    F = np.asarray(mesh.triangles, dtype=np.int64)
    if len(F) == 0:
        raise RuntimeError(
            f"scan produced no surface (fusion={params['fusion']['method']}, points={len(pts)}, "
            f"capture={totals}, voxel={derived.get('voxel_mm')})"
        )

    # Calibration scale error, about the part centre, *in the CAD frame* (it is real deviation).
    cad_to_scan, scale = output_transform(params, rng, center, derived)
    V_cad = center + (V - center) * scale
    pts_cad = center + (pts - center) * scale if len(pts) else pts

    t = time.perf_counter()
    gt_watertight = part.mesh.is_watertight
    metrics, _, _, _ = compare(V_cad, F, part.vertices, part.faces, gt_watertight)
    timings["metrics"] = time.perf_counter() - t

    out_dir.mkdir(parents=True, exist_ok=True)
    V_scan = transform(cad_to_scan, V_cad)
    trimesh.Trimesh(V_scan, F, process=False).export(out_dir / "scan.stl")
    if save_points and len(pts_cad):
        pc = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(transform(cad_to_scan, pts_cad)))
        o3d.io.write_point_cloud(str(out_dir / "points.ply"), pc, write_ascii=False)

    timings["total"] = time.perf_counter() - t0
    meta = {
        "schema": 1,
        "generator": {"name": "synthscan", "version": __version__},
        "sample_id": out_dir.name,
        "sample_index": sample_index,
        "input": input_name,
        "part_id": part.part_id,
        "part_name": part.name,
        "part_sha1": part.sha1,
        "split": split_for(part.sha1),
        "seed": {"global": global_seed, "sample_index": sample_index},
        "profile": params["profile"],
        "requested_profile": profile,
        "artifacts": artifacts_fired(params, derived, surface),
        "params": params,
        "derived": derived,
        "metrics": metrics,
        "transforms": {
            "cad_to_scan": cad_to_scan.tolist(),
            "scan_to_cad": np.linalg.inv(cad_to_scan).tolist(),
            "note": "rigid only; the calibration scale error (derived.scale_xyz) is deliberately not undone",
        },
        "files": {"scan": "scan.stl", "points": "points.ply" if save_points else None},
        "timings_s": {k: round(v, 3) for k, v in timings.items()},
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=1, default=_json_default))
    return meta


def artifacts_fired(params: dict, derived: dict, surface) -> list[str]:
    """Names of the artifact stages that actually changed this sample (for filtering and for
    failure analysis: "which artifacts does the LLM fail on?")."""
    n, s, r, c, b, f = (params[k] for k in ("noise", "surface", "registration", "capture", "base", "fusion"))
    a = ["range_noise", "grazing_dropout"]
    if n["corr_share"] > 0:
        a.append("correlated_noise")
    if n["tail_frac"] > 0:
        a.append("heavy_tail")
    if n["banding_mm"] > 0:
        a.append("banding")
    if n["smooth_px"] > 0:
        a.append("edge_smoothing")
    if n["mixed_pixel_p"] > 0:
        a.append("flying_pixels")
    if n["edge_erode_px"] > 0:
        a.append("edge_erosion")
    if n["outlier_frac"] > 0:
        a.append("outliers")
    if params["visibility"]["projector_shadow"] and c["baseline_mm"] > 0:
        a.append("projector_shadow")
    if s["shiny_frac"] > 0.01 or s["shiny_face_p"] > 0.01:
        a.append("shiny_dropout")
    if s["dark_frac"] > 0.01:
        a.append("dark_surface")
    if s["spray_um"] > 0:
        a.append("spray_coat")
    if derived.get("markers_placed"):
        a.append("marker_bumps" if s["marker_mode"] == "bump" else "marker_holes")
    a.append("tracking_drift")
    if derived.get("tracking_jumps"):
        a.append("tracking_jump")
    if c["sessions"] > 1:
        a.append("session_merge")
    a.append("scale_error")
    if b["support"] == "plane":
        a.append("plane_cut")
        if b["remnant"]:
            a.append("plane_remnant")
    a.append(f"fusion_{f['method']}")
    if f["method"] != "tsdf" and f["density_trim_q"] > 0:
        a.append("density_trim")
    a += derived.get("post_fired", [])
    a.append(f"pose_{params['output']['pose']}")
    return a


def _deep_update(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_update(dst[k], v)
        else:
            dst[k] = v


def _json_default(o):
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, float) and not math.isfinite(o):
        return None
    raise TypeError(type(o))


__all__ = ["generate_sample", "split_for", "artifacts_fired", "rigid"]
