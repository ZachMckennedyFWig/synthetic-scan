"""Grade a ScanRuler bench run against the hidden ground truth (docs/HARNESS.md).

The bench (``bench/run.mjs`` in the ScanRuler fork) leaves one folder per job with
``result.json`` (outcome, tool calls, tokens) and ``out/`` (what the model built:
``final.step``, and the scan as a point cloud in the frame the session ended in).
Here each model is put in the CAD frame *without fitting it to the GT*:

    model (session frame F) --T_F->S--> scan.stl frame S --scan_to_cad--> CAD frame

``T_F->S`` registers the exported cloud to ``scan.stl`` (the same points, so the fit is
exact up to float rounding) and undoes any alignment the model applied in ScanRuler.
``scan_to_cad`` is the generator's own transform; it keeps the scan's deliberate scale
error (DATASET.md), so posed numbers include it, as they would for a real scanner.

Two views per job:
- ``posed``: the honest one, in the CAD frame as above.
- ``bestfit``: after a rigid ICP of the model onto the GT. It forgives placement only,
  so ``posed - bestfit`` says how much of the error is where the part sits.

Features: bores (concave cylinders, grouped by axis and radius, wrapping >= 270 deg)
from the model's STEP and the GT STEP, with the same labeller (``parts._load_step``),
matched by axis line and radius.

Faces: the share of GT surface area where the model's nearest face is the same kind of
analytic surface with the same size (``face_agreement``). This is the design-intent check:
a fillet where the part has a chamfer, an R3.75 corner on an R3.5 part, a missing pocket.

The scan's own error vs GT rides along as ``scan_reference``, so a model can be read
against what a perfect copy of the scan would score.

``success`` follows the thresholds in ``Thresholds`` (proposed defaults, PLAN §0).
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import open3d as o3d
import trimesh
from scipy.optimize import linear_sum_assignment

from .metrics import compare, gt_samples
from .parts import _load_step


@dataclass(frozen=True)
class Thresholds:
    """What counts as a success: as close to the real object as possible (owner, PLAN §0).
    Proposed defaults; see docs/HARNESS.md."""

    chamfer_mm: float = 0.25  # posed symmetric mean distance, model <-> GT
    p95_mm: float = 0.5  # posed 95th percentile, model -> GT
    bore_diameter_mm: float = 0.2  # |d_model - d_gt| for every GT bore
    bore_axis_mm: float = 1.0  # a model bore matches a GT bore within this axis distance
    face_agreement: float = 0.9  # share of GT area with the right kind and size of surface
    face_dist_mm: float = 0.2  # ...within this distance of the model
    face_radius_mm: float = 0.1  # radius tolerance, absolute...
    face_radius_rel: float = 0.03  # ...or relative, whichever is larger
    face_angle_deg: float = 2.0  # plane normals and cone half-angles


BORE_MIN_SPAN_DEG = 270.0


# --------------------------------------------------------------------------- frames


def _cloud_points(path: Path) -> np.ndarray:
    pc = o3d.io.read_point_cloud(str(path))
    return np.asarray(pc.points)


def _pca_frames(p: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    c = p.mean(0)
    _, _, vt = np.linalg.svd(p - c, full_matrices=False)
    if np.linalg.det(vt) < 0:
        vt[2] *= -1
    return c, vt


def register_same_points(src: np.ndarray, dst: np.ndarray) -> tuple[np.ndarray, float]:
    """Rigid ``T`` with ``T @ src ~= dst`` for two copies of the same point set in different
    frames. Tries identity and the four proper PCA alignments, refines each with ICP, keeps
    the best. Returns ``(T, rms_mm)``."""
    diag = float(np.linalg.norm(dst.max(0) - dst.min(0)))
    s = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(src))
    d = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(dst))
    cs, vs = _pca_frames(src)
    cd, vd = _pca_frames(dst)
    inits = [np.eye(4)]
    for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        flip = np.diag([sx, sy, sx * sy])
        R = vd.T @ flip @ vs
        T = np.eye(4)
        T[:3, :3] = R
        T[:3, 3] = cd - R @ cs
        inits.append(T)
    best, best_rms = np.eye(4), math.inf
    p2p = o3d.pipelines.registration.TransformationEstimationPointToPoint()
    crit = o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=100)
    for T0 in inits:
        r = o3d.pipelines.registration.registration_icp(s, d, 0.05 * diag, T0, p2p, crit)
        r = o3d.pipelines.registration.registration_icp(s, d, 0.002 * diag, r.transformation, p2p, crit)
        if r.fitness > 0.98 and r.inlier_rmse < best_rms:
            best, best_rms = np.asarray(r.transformation), float(r.inlier_rmse)
    return best, best_rms


def _apply(T: np.ndarray, v: np.ndarray) -> np.ndarray:
    return v @ T[:3, :3].T + T[:3, 3]


def _icp_to(model_v: np.ndarray, gt_pts: np.ndarray) -> np.ndarray:
    """Rigid point-to-plane ICP of the model onto GT samples, from where it already is."""
    diag = float(np.linalg.norm(gt_pts.max(0) - gt_pts.min(0)))
    s = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(model_v))
    d = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(gt_pts))
    d.estimate_normals(o3d.geometry.KDTreeSearchParamKNN(16))
    T = np.eye(4)
    for frac in (0.05, 0.01):
        r = o3d.pipelines.registration.registration_icp(
            s, d, frac * diag, T, o3d.pipelines.registration.TransformationEstimationPointToPlane()
        )
        T = np.asarray(r.transformation)
    return T


# --------------------------------------------------------------------------- features


def bores(features: list[dict], T: np.ndarray | None = None) -> list[dict]:
    """Group concave cylinder faces into bores: same radius, same axis line, >= 270 deg."""
    cyl = [f for f in features if f.get("type") == "cylinder" and f.get("concave")]
    groups: list[dict] = []
    for f in cyl:
        o = np.asarray(f["origin"], float)
        a = np.asarray(f["axis"], float)
        a = a / np.linalg.norm(a)
        if T is not None:
            o, a = _apply(T, o[None])[0], T[:3, :3] @ a
        r = float(f["radius"])
        for g in groups:
            off = o - g["origin"]
            if (
                abs(r - g["radius"]) < 1e-3 * max(1.0, r)
                and abs(abs(a @ g["axis"]) - 1) < 1e-4
                and np.linalg.norm(off - (off @ g["axis"]) * g["axis"]) < 1e-3 * max(1.0, r)
            ):
                g["span_deg"] += f.get("span_deg", 360.0)
                g["faces"].append(f["face"])
                break
        else:
            groups.append(
                {
                    "radius": r,
                    "origin": o,
                    "axis": a,
                    "span_deg": f.get("span_deg", 360.0),
                    "faces": [f["face"]],
                }
            )
    return [g for g in groups if g["span_deg"] >= BORE_MIN_SPAN_DEG]


def _axis_distance(a: dict, b: dict) -> float:
    """Distance between two (near-parallel) axis lines; inf if not parallel within 5 deg."""
    if abs(a["axis"] @ b["axis"]) < math.cos(math.radians(5)):
        return math.inf
    off = b["origin"] - a["origin"]
    return float(np.linalg.norm(off - (off @ a["axis"]) * a["axis"]))


def match_bores(gt: list[dict], model: list[dict], th: Thresholds) -> dict:
    out = {"gt": len(gt), "model": len(model), "matched": 0, "within_tol": 0, "pairs": []}
    if not gt or not model:
        return out
    cost = np.full((len(gt), len(model)), 1e6)
    for i, g in enumerate(gt):
        for j, m in enumerate(model):
            dist = _axis_distance(g, m)
            if dist <= th.bore_axis_mm:
                cost[i, j] = abs(2 * (m["radius"] - g["radius"])) + 0.1 * dist
    rows, cols = linear_sum_assignment(cost)
    for i, j in zip(rows, cols, strict=True):
        if cost[i, j] >= 1e6:
            continue
        dd = 2 * (model[j]["radius"] - gt[i]["radius"])
        out["pairs"].append(
            {
                "d_gt": 2 * gt[i]["radius"],
                "d_model": 2 * model[j]["radius"],
                "d_err": dd,
                "axis_mm": _axis_distance(gt[i], model[j]),
            }
        )
        out["matched"] += 1
        out["within_tol"] += abs(dd) <= th.bore_diameter_mm
    return out


# --------------------------------------------------------------------------- one job


def _summary(m: dict) -> dict:
    return {
        "chamfer_mm": m["chamfer_mm"],
        "hausdorff_mm": m["hausdorff_mm"],
        "p95_mm": m["scan_to_gt"]["p95"],
        "gt_to_model_p95_mm": m["gt_to_scan"]["p95"],
        "coverage": m["coverage"],
        "mean_signed_mm": m["mean_signed_mm"],
    }


def grade_job(job_dir: Path, task: dict, export_dir: Path, th: Thresholds) -> dict:
    res = json.loads((job_dir / "result.json").read_text())
    hid = task["hidden"]
    run = res.get("run") or {}
    row: dict = {
        "key": job_dir.name,
        "task": task["id"],
        "model": res.get("model"),
        "status": res.get("status"),
        "profile": hid.get("profile"),
        "artifacts": hid.get("artifacts", []),
        # The scan's own error vs GT, for reference: what a perfect copy of the scan would score.
        "scan_reference": {
            k: (hid.get("metrics") or {}).get(k) for k in ("chamfer_mm", "p95_mm", "hausdorff_mm", "coverage")
        },
        "tool_calls": run.get("tool_calls"),
        "tool_errors": run.get("tool_errors"),
        "turns": run.get("turns"),
        "peak_context_tokens": run.get("peak_context_tokens"),
        "cost_usd": run.get("cost_usd"),
        "wall_s": res.get("wall_s"),
        "model_exported": bool(res.get("model_step")),
        "n_features": None,
        "scan_qa_rims": None,
        "graded": False,
        "success": False,
    }
    feats_path = job_dir / "out" / "features.json"
    if feats_path.exists():
        fl = json.loads(feats_path.read_text())
        row["n_features"] = len(fl.get("features", fl if isinstance(fl, list) else []))
    qa_path = job_dir / "out" / "scan-qa.json"
    if qa_path.exists():
        row["scan_qa_rims"] = (json.loads(qa_path.read_text()).get("rims") or {}).get("count")

    # The deterministic dossier (fork command scan_dossier), graded on its own: no model needed.
    dossier_path = job_dir / "out" / "dossier.json"
    if dossier_path.exists() and hid.get("gt_step"):
        try:
            dossier = json.loads(dossier_path.read_text())
            scan = trimesh.load(job_dir / "scan.stl", process=True)
            T_fs, _ = register_same_points(
                _cloud_points(job_dir / "out" / "scan-final-frame.ply"), np.asarray(scan.vertices)
            )
            gv, gf, gfid, gfeats, _ = _load_step(export_dir / hid["gt_step"])
            T_sc = np.asarray(hid["scan_to_cad"], float) @ T_fs
            seen = face_visibility(
                gv,
                gf,
                gfid,
                _apply(np.asarray(hid["scan_to_cad"], float), np.asarray(scan.vertices)),
                np.asarray(scan.faces),
                hid,
            )
            row["dossier"] = grade_dossier(dossier, T_sc, gfeats, hid, th, seen)
        except Exception as e:  # report, don't hide the rest of the grade
            row["dossier"] = {"error": repr(e)}

    step = job_dir / "out" / "final.step"
    if not step.exists() or step.stat().st_size == 0:
        row["why"] = "no body to export"
        return row
    try:
        mv, mf, mfid, mfeats, _ = _load_step(step)
    except Exception as e:  # a STEP OCCT cannot read is the model's failure, not ours
        row["why"] = f"STEP unreadable: {e}"
        return row

    # session frame -> scan.stl frame -> CAD frame
    scan = trimesh.load(job_dir / "scan.stl", process=True)
    T_fs, frame_rms = register_same_points(
        _cloud_points(job_dir / "out" / "scan-final-frame.ply"), np.asarray(scan.vertices)
    )
    row["frame_rms_mm"] = frame_rms
    T = np.asarray(hid["scan_to_cad"], float) @ T_fs
    mv_cad = _apply(T, mv)

    gt = trimesh.load(export_dir / hid["gt"], process=True)
    gt_v, gt_f = np.asarray(gt.vertices), np.asarray(gt.faces)
    pts = gt_samples(gt_v, gt_f)
    posed, *_ = compare(mv_cad, mf, gt_v, gt_f, gt.is_watertight, pts)
    T_fit = _icp_to(mv_cad, pts)
    bestfit, *_ = compare(_apply(T_fit, mv_cad), mf, gt_v, gt_f, gt.is_watertight, pts)
    row["posed"] = _summary(posed)
    row["bestfit"] = _summary(bestfit)
    row["bestfit_shift_mm"] = float(np.linalg.norm(T_fit[:3, 3]))
    model_mesh = trimesh.Trimesh(mv_cad, mf, process=False)
    row["model_watertight"] = bool(model_mesh.is_watertight)
    row["volume_ratio"] = (
        float(model_mesh.volume / gt.volume) if model_mesh.is_watertight and gt.is_watertight else None
    )

    row["faces"] = None
    if hid.get("gt_step"):
        gv, gf, gfid, gfeats, _ = _load_step(export_dir / hid["gt_step"])
        row["bores"] = match_bores(bores(gfeats), bores(mfeats, T), th)
        row["faces"] = face_agreement(gv, gf, gfid, gfeats, mv_cad, mf, mfid, mfeats, T[:3, :3], th)
    else:
        row["bores"] = None

    b, fa = row["bores"], row["faces"]
    bores_ok = b is None or (b["within_tol"] == b["gt"] and b["model"] == b["gt"])
    faces_ok = fa is None or fa["agreement"] >= th.face_agreement
    row["graded"] = True
    row["success"] = bool(
        row["posed"]["chamfer_mm"] is not None
        and row["posed"]["chamfer_mm"] <= th.chamfer_mm
        and row["posed"]["p95_mm"] <= th.p95_mm
        and bores_ok
        and faces_ok
    )
    if not row["success"]:
        why = []
        if row["posed"]["chamfer_mm"] > th.chamfer_mm:
            why.append(f"chamfer {row['posed']['chamfer_mm']:.2f} > {th.chamfer_mm}")
        if row["posed"]["p95_mm"] > th.p95_mm:
            why.append(f"p95 {row['posed']['p95_mm']:.2f} > {th.p95_mm}")
        if not bores_ok:
            why.append(f"bores {b['within_tol']}/{b['gt']} in tol, model has {b['model']}")
        if not faces_ok:
            why.append(f"faces {fa['agreement']:.0%} agree < {th.face_agreement:.0%}")
        row["why"] = "; ".join(why)
    return row


# --------------------------------------------------------------------------- dossier

# What each procedural kind is, as a designer would build it (FORK.md "Part dossier").
ARCHETYPE = {
    "plate": "extrude",
    "l_bracket": "extrude",
    "pocket_block": "extrude",
    "hex_standoff": "extrude",
    "flanged_bushing": "revolve",
}
DOSSIER_PLANE_MIN_SHARE = 0.01  # GT planes smaller than this share of the area are not required
DOSSIER_PLANE_OFFSET_MM = 0.3


def _dossier_dir(a) -> np.ndarray:
    """A dossier axis: "+z"-style for a part axis, else a vector."""
    if isinstance(a, str):
        v = np.zeros(3)
        v["xyz".index(a[1])] = -1.0 if a[0] == "-" else 1.0
        return v
    return np.asarray(a, float)


def _dossier_face(f: dict) -> tuple[np.ndarray, np.ndarray]:
    """(normal, point) of a dossier face: ``{facing, at: offset}`` or ``{n, at: point}``."""
    if "facing" in f:
        n = _dossier_dir(f["facing"])
        return n, np.abs(n) * f["at"]
    return np.asarray(f["n"], float), np.asarray(f["at"], float)


VISIBLE_SHARE = 0.3  # a GT face counts as in the scan when this share of it is covered


def face_visibility(gv, gf, gfid, scan_v, scan_f, hid: dict, n: int = 40_000) -> dict[int, float]:
    """Share of each GT face that the scan covers (scan surface within the scan's own p95, at
    least 0.5 mm), in the CAD frame. A dossier is judged only on what the scan shows: an
    inside corner the scanner never saw is the scan's gap, not the dossier's miss."""
    from .metrics import distances_to

    pts, tri = trimesh.sample.sample_surface(trimesh.Trimesh(gv, gf, process=False), n, seed=1)
    tol = max(0.5, (hid.get("metrics") or {}).get("p95_mm") or 0.0)
    near = distances_to(scan_v, scan_f, pts, signed=False) <= tol
    fid = gfid[tri]
    return {int(f): float(near[fid == f].mean()) for f in np.unique(fid)}


def grade_dossier(
    dossier: dict,
    T_session_to_cad: np.ndarray,
    gfeats: list[dict],
    hid: dict,
    th: Thresholds,
    seen: dict[int, float] | None = None,
) -> dict:
    """Score a ``scan_dossier`` answer against the GT B-rep labels, with no model involved.

    Dossier positions are in its part frame; ``frame.to_part`` maps the session frame to it.
    """
    to_part = np.asarray(dossier["frame"]["to_part"], float).reshape(4, 4)
    T = T_session_to_cad @ np.linalg.inv(to_part)  # part frame -> CAD frame
    out: dict = {}

    # Bores: found, diameter as measured, and the first nominal candidate.
    def visible(faces, share=VISIBLE_SHARE):
        return seen is None or max(seen.get(f, 0.0) for f in faces) >= share

    gt_all = bores(gfeats)
    # A deep bore's wall is barely scanned even when its ends are: a tenth will do.
    gt_b = [g for g in gt_all if visible(g["faces"], 0.1)]
    d_b = []
    for b in dossier.get("bores", []):
        a = T[:3, :3] @ _dossier_dir(b["axis"])
        d_b.append(
            {
                "radius": b["d"] / 2,
                "origin": _apply(T, np.asarray(b["at"], float)[None])[0],
                "axis": a / np.linalg.norm(a),
                "nominal": (b.get("nominal") or [{}])[0].get("d"),
            }
        )
    m = match_bores(gt_b, d_b, th)
    nominal_ok = 0
    for g in gt_b:
        near = [db for db in d_b if _axis_distance(g, db) <= th.bore_axis_mm and db["nominal"] is not None]
        if near:
            nominal_ok += abs(near[0]["nominal"] - 2 * g["radius"]) <= 0.01
    out["bores"] = {
        "gt": m["gt"],
        "gt_not_in_scan": len(gt_all) - len(gt_b),
        "found": m["matched"],
        "extra": m["model"] - m["matched"],
        "measured_within_tol": m["within_tol"],
        "nominal_right": nominal_ok,
        "max_measured_err_mm": max((abs(p["d_err"]) for p in m["pairs"]), default=None),
        "pairs": [{"d_gt": round(p["d_gt"], 3), "d": round(p["d_model"], 3)} for p in m["pairs"]],
    }

    # Planes: every sizeable GT plane should be among the dossier's faces.
    total = sum(f["area_mm2"] for f in gfeats)
    min_area = DOSSIER_PLANE_MIN_SHARE * total
    sized = [f for f in gfeats if f["type"] == "plane" and f["area_mm2"] >= min_area]
    gt_planes = [f for f in sized if visible([f["face"]])]
    d_planes = []
    for f in dossier.get("faces", []):
        n0, p0 = _dossier_face(f)
        n = T[:3, :3] @ n0
        d_planes.append((n / np.linalg.norm(n), _apply(T, p0[None])[0]))
    # A dossier reads the scan, so a plane may sit off GT by as much as the scan itself does
    # (its deliberate scale and registration error): the scan's own p95, or 0.3 mm.
    scan_p95 = (hid.get("metrics") or {}).get("p95_mm") or 0.0
    plane_tol = max(DOSSIER_PLANE_OFFSET_MM, scan_p95)
    hit_area, hit = 0.0, 0
    missed = []
    for g in gt_planes:
        gn, go = np.asarray(g["normal"], float), np.asarray(g["origin"], float)
        cos = math.cos(math.radians(th.face_angle_deg))
        if any(abs(n @ gn) >= cos and abs((p - go) @ gn) <= plane_tol for n, p in d_planes):
            hit += 1
            hit_area += g["area_mm2"]
        else:
            # Where it is in the dossier's part frame, so a reader can find it there.
            Ti = np.linalg.inv(T)
            missed.append(
                {
                    "area_mm2": round(g["area_mm2"], 1),
                    "n_part": [round(x, 3) for x in Ti[:3, :3] @ gn],
                    "at_part": [round(x, 2) for x in _apply(Ti, go[None])[0]],
                }
            )
    plane_area = sum(g["area_mm2"] for g in gt_planes)
    out["planes"] = {
        "gt": len(gt_planes),
        "found": hit,
        "found_area_share": hit_area / plane_area if plane_area else None,
        "dossier_faces": len(d_planes),
        "gt_not_in_scan": len(sized) - len(gt_planes),
        "offset_tol_mm": round(plane_tol, 3),
        "missed": sorted(missed, key=lambda m: -m["area_mm2"])[:6],
    }

    kind = (hid.get("design_params") or {}).get("kind")
    want = ARCHETYPE.get(kind)
    got = (dossier.get("archetype") or [{}])[0].get("kind")
    out["archetype"] = {"want": want, "got": got, "right": want is not None and got == want}
    shown = {k: v for k, v in dossier.items() if k != "considered"}  # debug output is not shown to a model
    out["tokens_est"] = len(json.dumps(shown, separators=(",", ":"))) // 4
    return out


# --------------------------------------------------------------------------- faces


def _face_params_agree(g: dict, m: dict, R: np.ndarray, th: Thresholds) -> bool:
    """Same analytic surface, same size. Positions are judged by distance elsewhere."""
    if g.get("type") != m.get("type"):
        return False
    t = g["type"]
    if t == "plane":
        n = R @ np.asarray(m["normal"], float)
        return abs(float(n @ np.asarray(g["normal"], float))) >= math.cos(math.radians(th.face_angle_deg))
    if t in ("cylinder", "sphere"):
        r = g["radius"]
        return abs(m["radius"] - r) <= max(th.face_radius_mm, th.face_radius_rel * r)
    if t == "torus":
        r = g["minor_radius"]  # the blend radius of a fillet on a round edge
        return abs(m["minor_radius"] - r) <= max(th.face_radius_mm, th.face_radius_rel * r)
    if t == "cone":
        return abs(abs(m["half_angle_rad"]) - abs(g["half_angle_rad"])) <= math.radians(th.face_angle_deg)
    return True  # free-form: the type is all we compare


def _describe(lab: dict) -> str:
    t = lab.get("type", "?")
    if t in ("cylinder", "sphere"):
        return f"{t} r{lab['radius']:.3g}" + (" (concave)" if lab.get("concave") else "")
    if t == "torus":
        return f"torus r{lab['minor_radius']:.3g}"
    if t == "cone":
        return f"cone {math.degrees(abs(lab['half_angle_rad'])):.3g}deg"
    return t


def face_agreement(gv, gf, gfid, gfeats, mv, mf, mfid, mfeats, R, th: Thresholds, n: int = 60_000) -> dict:
    """Share of the GT surface (by area) where the model's nearest face is the same kind of
    surface with the same size (plane normal, cylinder/sphere radius, fillet radius, cone
    angle) and lies within ``face_dist_mm``. A fillet where the part has a chamfer, a wrong
    radius or a missing feature all count against it."""
    gmesh = trimesh.Trimesh(gv, gf, process=False)
    pts, tri = trimesh.sample.sample_surface(gmesh, n, seed=0)
    g_face = gfid[tri]
    scene = o3d.t.geometry.RaycastingScene()
    scene.add_triangles(o3d.core.Tensor(mv.astype(np.float32)), o3d.core.Tensor(mf.astype(np.uint32)))
    cp = scene.compute_closest_points(o3d.core.Tensor(pts.astype(np.float32)))
    dist = np.linalg.norm(cp["points"].numpy() - pts, axis=1)
    m_face = mfid[cp["primitive_ids"].numpy().astype(np.int64)]
    glab = {f["face"]: f for f in gfeats}
    mlab = {f["face"]: f for f in mfeats}

    pairs: dict[tuple[int, int], bool] = {}
    ok = np.zeros(len(pts), bool)
    for k, (gi, mi) in enumerate(zip(g_face.tolist(), m_face.tolist(), strict=True)):
        if (gi, mi) not in pairs:
            pairs[(gi, mi)] = gi in glab and mi in mlab and _face_params_agree(glab[gi], mlab[mi], R, th)
        ok[k] = pairs[(gi, mi)] and dist[k] <= th.face_dist_mm

    by_type: dict[str, list[bool]] = {}
    per_face = []
    for gi in np.unique(g_face):
        sel = g_face == gi
        lab = glab.get(int(gi), {"type": "?"})
        by_type.setdefault(lab.get("type", "?"), []).extend(ok[sel].tolist())
        there = np.bincount(m_face[sel]).argmax()
        per_face.append(
            {
                "gt": _describe(lab),
                "area_share": float(sel.mean()),
                "agree": float(ok[sel].mean()),
                "model_there": _describe(mlab.get(int(there), {"type": "?"})),
                "median_dist_mm": float(np.median(dist[sel])),
            }
        )
    worst = sorted(per_face, key=lambda f: -f["area_share"] * (1 - f["agree"]))
    return {
        "agreement": float(ok.mean()),
        "by_type": {t: float(np.mean(v)) for t, v in sorted(by_type.items())},
        "worst": [f for f in worst if f["agree"] < 0.9][:8],
        "n_gt_faces": len(glab),
        "n_model_faces": len(mlab),
    }


# --------------------------------------------------------------------------- a run


def _rate(rows: list[dict]) -> str:
    return f"{sum(r['success'] for r in rows)}/{len(rows)}"


def _median(xs: list) -> float | None:
    xs = [x for x in xs if x is not None]
    return float(np.median(xs)) if xs else None


def _dossier_totals(ds: list[dict]) -> dict | None:
    if not ds:
        return None
    s = lambda k, f: sum(d[k][f] or 0 for d in ds)  # noqa: E731
    return {
        "jobs": len(ds),
        "bores_found": f"{s('bores', 'found')}/{s('bores', 'gt')}",
        "bores_extra": s("bores", "extra"),
        "bores_nominal_right": f"{s('bores', 'nominal_right')}/{s('bores', 'gt')}",
        "planes_found": f"{s('planes', 'found')}/{s('planes', 'gt')}",
        # Only parts whose archetype is known (procedural kinds) count; a real part has none.
        "archetype_right": f"{sum(d['archetype']['right'] for d in ds)}/{sum(d['archetype']['want'] is not None for d in ds)}",
        "median_tokens_est": _median([d["tokens_est"] for d in ds]),
    }


def summarize(rows: list[dict]) -> dict:
    by_model: dict[str, dict] = {}
    for model in sorted({r["model"] for r in rows}):
        rs = [r for r in rows if r["model"] == model]
        graded = [r for r in rs if r["graded"]]
        art: dict[str, list] = {}
        for r in rs:
            for a in r["artifacts"]:
                art.setdefault(a, []).append(r)
        by_model[model] = {
            "jobs": len(rs),
            "success": _rate(rs),
            "built_a_body": f"{len(graded)}/{len(rs)}",
            "status": {s: sum(r["status"] == s for r in rs) for s in sorted({r["status"] for r in rs})},
            "median_posed_chamfer_mm": _median([r["posed"]["chamfer_mm"] for r in graded]),
            "median_face_agreement": _median([(r.get("faces") or {}).get("agreement") for r in graded]),
            "median_scan_chamfer_mm": _median(
                [(r.get("scan_reference") or {}).get("chamfer_mm") for r in rs]
            ),
            "median_bestfit_chamfer_mm": _median([r["bestfit"]["chamfer_mm"] for r in graded]),
            "median_tool_calls": _median([r["tool_calls"] for r in rs]),
            "median_peak_context_tokens": _median([r["peak_context_tokens"] for r in rs]),
            "total_cost_usd": float(sum(r["cost_usd"] or 0 for r in rs)),
            "median_wall_s": _median([r["wall_s"] for r in rs]),
            "by_profile": {
                p: _rate([r for r in rs if r["profile"] == p]) for p in sorted({r["profile"] for r in rs})
            },
            "by_scan_qa_rims": {
                "closed (0 rims)": _rate([r for r in rs if r["scan_qa_rims"] == 0]),
                "open": _rate([r for r in rs if (r["scan_qa_rims"] or 0) > 0]),
            },
            "by_artifact": {a: _rate(v) for a, v in sorted(art.items())},
            "dossier": _dossier_totals([r["dossier"] for r in rs if "bores" in (r.get("dossier") or {})]),
        }
    return by_model


def grade_run(tasks_path: Path, run_dir: Path, th: Thresholds | None = None) -> tuple[list[dict], dict]:
    th = th or Thresholds()
    tasks = {}
    for line in tasks_path.read_text().splitlines():
        if line.strip():
            t = json.loads(line)
            tasks[t["id"]] = t
    rows = []
    for res_path in sorted((run_dir / "jobs").glob("*/result.json")):
        res = json.loads(res_path.read_text())
        task = tasks.get(res.get("task"))
        if task is None:
            continue
        try:
            rows.append(grade_job(res_path.parent, task, tasks_path.parent, th))
        except Exception as e:  # grade the rest; a grader bug must not hide the run
            rows.append(
                {
                    "key": res_path.parent.name,
                    "task": res.get("task"),
                    "model": res.get("model"),
                    "status": res.get("status"),
                    "graded": False,
                    "success": False,
                    "why": f"grader error: {e!r}",
                    "artifacts": [],
                    "profile": None,
                    "scan_qa_rims": None,
                    "tool_calls": None,
                    "peak_context_tokens": None,
                    "cost_usd": None,
                    "wall_s": None,
                }
            )
    summary = {"thresholds": asdict(th), "models": summarize(rows)}
    (run_dir / "grades.jsonl").write_text("".join(json.dumps(r, default=float) + "\n" for r in rows))
    (run_dir / "grades-summary.json").write_text(json.dumps(summary, indent=1, default=float))
    return rows, summary
