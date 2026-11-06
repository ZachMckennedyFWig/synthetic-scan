"""How far a scan is from its ground truth.

Every number here is computed in the CAD frame, against the exact GT
tessellation, with Embree closest-point queries (Open3D ``RaycastingScene``):
no point-sampling of the GT for scan->GT distances, so they are exact to the
tessellation (itself ~1e-4 of the part diagonal).

* **scan -> GT** (per scan vertex, signed when the GT is watertight: + = outside
  the solid). Captures noise, rounding, ghosts, spikes, bulging fills.
* **GT -> scan** (on area-uniform samples of the GT). Captures what is
  *missing*: holes, occlusions, eroded thin walls. ``coverage`` is the fraction
  of GT area within ``COVERAGE_TOL_MM`` of the scan.

These numbers describe the *scan*. Grading a *reconstruction* against GT uses
the same functions on the reconstructed mesh.
"""

from __future__ import annotations

import numpy as np
import open3d as o3d
import trimesh

COVERAGE_TOL_MM = 0.5
GT_SAMPLES = 120_000


def _scene(vertices: np.ndarray, faces: np.ndarray) -> o3d.t.geometry.RaycastingScene:
    s = o3d.t.geometry.RaycastingScene()
    s.add_triangles(o3d.core.Tensor(vertices.astype(np.float32)), o3d.core.Tensor(faces.astype(np.uint32)))
    return s


def distances_to(vertices: np.ndarray, faces: np.ndarray, query: np.ndarray, signed: bool) -> np.ndarray:
    """Distance from each ``query`` point to the mesh (signed only for a watertight mesh)."""
    if len(query) == 0 or len(faces) == 0:
        return np.full(len(query), np.inf, dtype=np.float32)
    s = _scene(vertices, faces)
    q = o3d.core.Tensor(query.astype(np.float32))
    d = s.compute_signed_distance(q) if signed else s.compute_distance(q)
    return d.numpy().astype(np.float32)


def gt_samples(gt_v: np.ndarray, gt_f: np.ndarray, n: int = GT_SAMPLES, seed: int = 0) -> np.ndarray:
    pts, _ = trimesh.sample.sample_surface(trimesh.Trimesh(gt_v, gt_f, process=False), n, seed=seed)
    return np.asarray(pts)


def _stats(d: np.ndarray) -> dict:
    a = np.abs(d[np.isfinite(d)])
    if len(a) == 0:
        return {"mean": None, "rms": None, "p95": None, "max": None}
    return {
        "mean": float(a.mean()),
        "rms": float(np.sqrt((a**2).mean())),
        "p95": float(np.quantile(a, 0.95)),
        "max": float(a.max()),
    }


def n_shells(faces: np.ndarray, n_vertices: int) -> int:
    """Pieces connected through shared vertices. (Edge adjacency would split a single shell at
    every non-manifold edge, and decimated scans have thousands of those.)"""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    f = np.asarray(faces, dtype=np.int64)
    # Link each triangle's vertices: 0-1 and 0-2 suffice to connect all three.
    a = np.concatenate([f[:, 0], f[:, 0]])
    b = np.concatenate([f[:, 1], f[:, 2]])
    g = coo_matrix((np.ones(len(a), dtype=np.int8), (a, b)), shape=(n_vertices, n_vertices))
    _, labels = connected_components(g, directed=False)
    return int(len(np.unique(labels[np.unique(f)])))


def mesh_stats(vertices: np.ndarray, faces: np.ndarray) -> dict:
    """Topology a reconstruction tool cares about: is it closed, in how many pieces, how holey."""
    if len(faces) == 0:
        return {"n_vertices": 0, "n_tris": 0, "watertight": False, "n_components": 0, "n_boundary_edges": 0}
    m = trimesh.Trimesh(vertices, faces, process=False)
    edges = np.sort(m.edges, axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return {
        "n_vertices": int(len(vertices)),
        "n_tris": int(len(faces)),
        "watertight": bool(m.is_watertight),
        "n_components": n_shells(faces, len(vertices)),
        "n_boundary_edges": int((counts == 1).sum()),
        "n_nonmanifold_edges": int((counts > 2).sum()),
    }


def compare(
    scan_v: np.ndarray,
    scan_f: np.ndarray,
    gt_v: np.ndarray,
    gt_f: np.ndarray,
    gt_watertight: bool,
    gt_pts: np.ndarray | None = None,
) -> tuple[dict, np.ndarray, np.ndarray, np.ndarray]:
    """Metrics plus the per-point arrays the viewer colours by.

    Returns ``(metrics, scan_vertex_signed_dev, gt_sample_points, gt_sample_dist_to_scan)``.
    """
    dev = distances_to(gt_v, gt_f, scan_v, signed=gt_watertight)
    if gt_pts is None:
        gt_pts = gt_samples(gt_v, gt_f)
    back = distances_to(scan_v, scan_f, gt_pts, signed=False)
    a, b = _stats(dev), _stats(back)
    finite = back[np.isfinite(back)]
    m = {
        "scan_to_gt": a,
        "gt_to_scan": b,
        "chamfer_mm": None if a["mean"] is None or b["mean"] is None else (a["mean"] + b["mean"]) / 2,
        "hausdorff_mm": None if a["max"] is None or b["max"] is None else max(a["max"], b["max"]),
        "rms_mm": a["rms"],
        "coverage": float((finite < COVERAGE_TOL_MM).mean()) if len(finite) else 0.0,
        "coverage_tol_mm": COVERAGE_TOL_MM,
        "signed": bool(gt_watertight),
        "mean_signed_mm": float(np.nanmean(dev)) if gt_watertight and len(dev) else None,
    }
    m.update(mesh_stats(scan_v, scan_f))
    return m, dev, gt_pts, back
