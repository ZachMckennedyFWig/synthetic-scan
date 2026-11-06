"""Fusion and post-processing: depth frames -> the mesh a scanner app would export.

Two fusion back-ends, because consumer apps use both and they fail differently:

* **TSDF** (KinectFusion-style volumetric fusion, what most handheld
  structured-light apps do live). Open surfaces stay open, thin walls under
  ~2 voxels erode or merge, misregistered frames average into thickened or
  stepped walls, and the voxel size sets the edge rounding radius.
* **Screened Poisson** (the "watertight" export option in most apps, and the
  default for laser/point-cloud pipelines). Always closes the surface:
  unseen regions become smooth bulging caps unless low-density areas are
  trimmed away (which reopens them, ragged).

Post-processing then copies the export dialog: remove small floating parts
(or not), fill holes (flat VTK caps), smoothing, decimation, plus a low-probability
"defects" stage (flipped patches, duplicated faces, leftover floaters), and
finally the global calibration scale error and an arbitrary output pose.
"""

from __future__ import annotations

import math

import numpy as np
import open3d as o3d

from .scanner import Frame, backproject, random_rotation, rigid

# Memory/time caps. TSDF memory ~ surface area / voxel^2; Poisson time ~ point count.
MAX_SURFACE_VOXELS = 6e5  # -> roughly 1-1.5 M triangles at most before decimation
SPECK_TRIS = 30  # fragments smaller than this are always dropped (apps never export them)
MAX_POISSON_POINTS = 1.0e6


def fuse(
    frames: list[Frame], params: dict, area_mm2: float, rng, derived: dict, want_points: bool = False
) -> tuple[o3d.geometry.TriangleMesh, np.ndarray]:
    """Fuse frames into a mesh in the CAD frame. Also returns the fused raw points when they
    were needed anyway (Poisson) or asked for (``want_points``, for ``points.ply``)."""
    fp, cap = params["fusion"], params["capture"]
    floor = math.sqrt(max(area_mm2, 1.0) / MAX_SURFACE_VOXELS)
    voxel = max(cap["spacing_mm"] * fp["voxel_mult"], floor)
    derived["voxel_mm"] = voxel

    # Gathering every frame's points costs as much as TSDF itself: only do it when used.
    if fp["method"] == "poisson" or want_points:
        pts, to_cam = _gather_points(frames, voxel)
    else:
        pts, to_cam = np.zeros((0, 3)), np.zeros((0, 3))
    if fp["method"] == "tsdf":
        mesh = _tsdf(frames, voxel, fp, cap, area_mm2)
    elif fp["method"] == "tsdf_poisson":
        # Live voxel fusion, then a watertight "fitting" mesher on the fused surface — the
        # one-click pipeline of most handheld apps (research §3.1). The TSDF surface's own
        # vertex normals are consistently oriented, so they seed Poisson directly.
        tm = _tsdf(frames, voxel, fp, cap, area_mm2)
        if len(tm.vertices) >= 100:
            tm.compute_vertex_normals()
            fused = np.asarray(tm.vertices)
            mesh = _poisson(fused, np.asarray(tm.vertex_normals), voxel, fp, area_mm2, derived)
        else:
            mesh = o3d.geometry.TriangleMesh()
    else:
        mesh = _poisson(pts, to_cam, voxel, fp, area_mm2, derived)
    mesh.remove_degenerate_triangles()
    mesh.remove_unreferenced_vertices()
    return canonical(mesh), pts


def canonical(mesh: o3d.geometry.TriangleMesh) -> o3d.geometry.TriangleMesh:
    """Sort vertices and triangles into a canonical order.

    The voxel-block hash map hands marching cubes its blocks in a run-dependent order, so the
    same surface comes out with a different vertex order each run — which then changes what
    order-sensitive steps (quadric decimation) do. Sorting here makes every sample
    byte-for-byte reproducible from its seed."""
    V = np.asarray(mesh.vertices)
    F = np.asarray(mesh.triangles)
    if len(F) == 0:
        return mesh
    order = np.lexsort(V.T[::-1])
    remap = np.empty(len(V), dtype=np.int64)
    remap[order] = np.arange(len(V))
    F = remap[F]
    F = _rotate_min_first(F)
    F = F[np.lexsort(F.T[::-1])]
    return o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(V[order]), o3d.utility.Vector3iVector(F))


def _rotate_min_first(F: np.ndarray) -> np.ndarray:
    """Rotate each triangle (keeping its winding) so its smallest index comes first."""
    k = np.argmin(F, axis=1)
    idx = (k[:, None] + np.arange(3)[None, :]) % 3
    return np.take_along_axis(F, idx, axis=1)


def _gather_points(frames: list[Frame], voxel: float) -> tuple[np.ndarray, np.ndarray]:
    all_p, all_c = [], []
    for fr in frames:
        p, c = backproject(fr)
        if len(p):
            all_p.append(p)
            all_c.append(c)
    if not all_p:
        return np.zeros((0, 3)), np.zeros((0, 3))
    pcd = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(np.concatenate(all_p)))
    # Carry the to-camera direction through the voxel average in the normals slot: that is
    # exactly the per-point orientation a real scanner knows, and Poisson needs it.
    pcd.normals = o3d.utility.Vector3dVector(np.concatenate(all_c))
    down = pcd.voxel_down_sample(voxel * 0.7)
    return np.asarray(down.points), np.asarray(down.normals)


def _tsdf(
    frames: list[Frame], voxel: float, fp: dict, cap: dict, area_mm2: float
) -> o3d.geometry.TriangleMesh:
    """Sparse voxel-block TSDF (Open3D tensor ``VoxelBlockGrid``; the legacy
    ``ScalableTSDFVolume`` integrates nothing in the 0.20 Windows wheel). Units are mm
    throughout (``depth_scale = 1``)."""
    oc = o3d.core
    res = 8
    # Initial hash capacity: blocks touched by the truncation band; the map grows if needed.
    blocks = int(np.clip(4 * area_mm2 / (res * voxel) ** 2, 2_000, 400_000))
    vbg = o3d.t.geometry.VoxelBlockGrid(
        attr_names=("tsdf", "weight"),
        attr_dtypes=(oc.float32, oc.float32),
        attr_channels=((1), (1)),
        voxel_size=float(voxel),
        block_resolution=res,
        block_count=blocks,
        device=oc.Device("CPU:0"),
    )
    far = float(cap["distance_mm"] * (1 + cap["dof_frac"]) * 1.5)
    trunc = float(fp["trunc_vox"])
    for fr in frames:
        # A frame that saw nothing inside the fusion range touches no block, and Open3D
        # aborts the whole sample on it (seen on a standoff, eval-b 2026-11-05): skip it.
        if not ((fr.depth > 0) & (fr.depth < far)).any():
            continue
        depth = o3d.t.geometry.Image(oc.Tensor(np.ascontiguousarray(fr.depth)))
        K = oc.Tensor(fr.K.astype(np.float64))
        E = oc.Tensor(np.linalg.inv(fr.cam_to_cad).astype(np.float64))
        try:
            coords = vbg.compute_unique_block_coordinates(depth, K, E, 1.0, far, trunc)
            vbg.integrate(coords, depth, K, E, 1.0, far, trunc)
        except RuntimeError as e:
            if "No block is touched" not in str(e):
                raise
            continue
    try:
        return vbg.extract_triangle_mesh(weight_threshold=1.0).to_legacy()
    except RuntimeError:  # nothing integrated
        return o3d.geometry.TriangleMesh()


def _poisson(pts, to_cam, voxel, fp, area_mm2, derived) -> o3d.geometry.TriangleMesh:
    if len(pts) < 100:
        return o3d.geometry.TriangleMesh()
    if len(pts) > MAX_POISSON_POINTS:
        idx = np.random.default_rng(len(pts)).choice(len(pts), int(MAX_POISSON_POINTS), replace=False)
        pts, to_cam = pts[idx], to_cam[idx]
        derived["poisson_subsampled"] = True
    ref = pts
    pcd = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(pts))
    pcd.estimate_normals(o3d.geometry.KDTreeSearchParamKNN(int(fp["normal_knn"])))
    # Orient each estimated normal toward the camera(s) that saw the point.
    nrm = np.asarray(pcd.normals).copy()
    flip = np.einsum("ij,ij->i", nrm, to_cam) < 0
    nrm[flip] *= -1
    pcd.normals = o3d.utility.Vector3dVector(nrm)

    extent = float(np.linalg.norm(ref.max(0) - ref.min(0)))
    # Same surface budget as TSDF: the finest octree cell may not be smaller than the floor.
    max_depth = int(math.floor(math.log2(extent / math.sqrt(max(area_mm2, 1.0) / MAX_SURFACE_VOXELS))))
    depth = int(np.clip(round(math.log2(extent / voxel)) + fp["poisson_depth_offset"], 6, min(10, max_depth)))
    derived["poisson_depth"] = depth
    mesh, dens = o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(pcd, depth=depth, n_threads=1)
    dens = np.asarray(dens)
    if fp["density_trim_q"] > 0 and len(dens):
        mesh.remove_vertices_by_mask(dens < np.quantile(dens, fp["density_trim_q"]))
    # Poisson's octree extends past the data; real apps crop to the scanned region.
    bb = o3d.geometry.AxisAlignedBoundingBox(ref.min(0) - 2 * voxel, ref.max(0) + 2 * voxel)
    return mesh.crop(bb)


# --------------------------------------------------------------------------- post-processing


def postprocess(
    mesh: o3d.geometry.TriangleMesh, params: dict, rng, derived: dict
) -> o3d.geometry.TriangleMesh:
    pp = params["post"]
    fired = derived.setdefault("post_fired", [])
    if len(mesh.triangles) == 0:
        return mesh

    # "Remove floating parts": islands under a fraction of the main body. With it off, the
    # larger floating fragments survive into the export (but never single-voxel specks).
    if _drop_small_components(mesh, 0 if pp["keep_islands"] else pp["island_frac"]):
        fired.append("islands_removed" if not pp["keep_islands"] else "specks_removed")

    if pp["hole_fill"] != "none":
        size = math.inf if pp["hole_fill"] == "all" else pp["hole_fill_mm"]
        mesh, n = fill_holes(mesh, size)
        if n:
            fired.append(f"hole_fill_{pp['hole_fill']}")
            derived["holes_filled"] = n

    if pp["smoothing"] == "taubin" and pp["smooth_iters"] > 0:
        mesh = mesh.filter_smooth_taubin(number_of_iterations=int(pp["smooth_iters"]))
        fired.append("smooth_taubin")
    elif pp["smoothing"] == "laplacian" and pp["smooth_iters"] > 0:
        mesh = mesh.filter_smooth_laplacian(number_of_iterations=int(pp["smooth_iters"]), lambda_filter=0.5)
        fired.append("smooth_laplacian")
    elif pp["smoothing"] == "simple" and pp["smooth_iters"] > 0:
        mesh = mesh.filter_smooth_simple(number_of_iterations=max(1, int(pp["smooth_iters"]) // 3))
        fired.append("smooth_simple")

    if pp["decimate"] < 0.999:
        n0 = len(mesh.triangles)
        if pp["decimator"] == "cluster":
            # Grid-aligned vertex clustering: the blocky, uniform triangle look of some exporters.
            V = np.asarray(mesh.vertices)
            ext = float(np.linalg.norm(V.max(0) - V.min(0))) if len(V) else 1.0
            avg_edge = math.sqrt(4 * max(mesh.get_surface_area(), 1e-9) / max(n0, 1) / math.sqrt(3))
            cell = avg_edge / math.sqrt(max(pp["decimate"], 0.05))
            mesh = mesh.simplify_vertex_clustering(voxel_size=min(cell, ext / 20))
        else:
            mesh = mesh.simplify_quadric_decimation(
                target_number_of_triangles=max(500, int(n0 * pp["decimate"]))
            )
        fired.append(f"decimated_{pp['decimator']}")
        _drop_small_components(mesh, 0)  # clustering can shatter thin regions into specks

    mesh = _defects(mesh, pp, rng, fired)
    mesh.remove_unreferenced_vertices()
    return mesh


def boundary_loops(F: np.ndarray) -> list[list[int]]:
    """Closed loops of boundary vertices, each ordered along the boundary's directed edges.

    A directed edge (a, b) of some triangle whose reverse (b, a) belongs to no triangle is on
    the boundary. Walking ``a -> b`` around each one gives the loop. Non-manifold vertices
    (two boundary edges leaving one vertex) are handled by consuming edges as they are walked."""
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    key = e[:, 0].astype(np.int64) << 32 | e[:, 1]
    rev = e[:, 1].astype(np.int64) << 32 | e[:, 0]
    bnd = e[~np.isin(key, rev)]
    nxt: dict[int, list[int]] = {}
    for a, b in bnd.tolist():
        nxt.setdefault(a, []).append(b)
    loops = []
    while nxt:
        start = next(iter(nxt))
        loop, cur = [start], start
        while True:
            outs = nxt.get(cur)
            if not outs:
                break
            nb = outs.pop()
            if not outs:
                del nxt[cur]
            if nb == start:
                break
            loop.append(nb)
            cur = nb
            if len(loop) > len(bnd):  # malformed boundary; give up on this loop
                break
        if len(loop) >= 3:
            loops.append(loop)
    return loops


def fill_holes(mesh: o3d.geometry.TriangleMesh, max_radius: float) -> tuple[o3d.geometry.TriangleMesh, int]:
    """Cap every boundary loop whose radius (centroid to farthest rim vertex) is <= ``max_radius``
    with a fan from its centroid: a flat cap on a planar rim, a tent on a warped one — like the
    "fill holes" of scanner apps (research §2.20). Caps keep the mesh's orientation."""
    V = np.asarray(mesh.vertices)
    F = np.asarray(mesh.triangles)
    if len(F) == 0:
        return mesh, 0
    newV, newF = [V], [F]
    nv, filled = len(V), 0
    for loop in boundary_loops(F):
        ring = V[loop]
        c = ring.mean(0)
        if np.linalg.norm(ring - c, axis=1).max() > max_radius:
            continue
        idx = np.array(loop)
        # Rim edge (a, b) belongs to an existing triangle as a -> b; the cap uses b -> a.
        tri = np.stack([np.roll(idx, -1), idx, np.full(len(idx), nv)], axis=1)
        newV.append(c[None])
        newF.append(tri)
        nv += 1
        filled += 1
    if not filled:
        return mesh, 0
    out = o3d.geometry.TriangleMesh(
        o3d.utility.Vector3dVector(np.concatenate(newV)), o3d.utility.Vector3iVector(np.concatenate(newF))
    )
    return out, filled


def _drop_small_components(mesh: o3d.geometry.TriangleMesh, frac: float) -> bool:
    """Remove connected components below ``max(SPECK_TRIS, frac * largest)`` triangles."""
    if len(mesh.triangles) == 0:
        return False
    labels, counts, _ = mesh.cluster_connected_triangles()
    labels, counts = np.asarray(labels), np.asarray(counts)
    if len(counts) < 2:
        return False
    small = counts[labels] < max(SPECK_TRIS, frac * counts.max())
    if not small.any() or small.all():
        return False
    mesh.remove_triangles_by_mask(small)
    mesh.remove_unreferenced_vertices()
    return True


def _defects(mesh, pp, rng, fired) -> o3d.geometry.TriangleMesh:
    """Low-probability export defects real scan files contain and tools must tolerate."""
    V = np.asarray(mesh.vertices)
    F = np.asarray(mesh.triangles).copy()
    if len(F) == 0:
        return mesh
    if pp["flip_patches"] > 0:
        cent = V[F].mean(1)
        for _ in range(int(pp["flip_patches"])):
            seed = cent[rng.integers(len(F))]
            r = np.linalg.norm(V.max(0) - V.min(0)) * rng.uniform(0.005, 0.03)
            sel = np.linalg.norm(cent - seed, axis=1) < r
            F[sel] = F[sel][:, ::-1]
        fired.append("flipped_patches")
    if pp["dup_faces"] > 0:
        F = np.concatenate([F, F[rng.integers(len(F), size=int(pp["dup_faces"]))]])
        fired.append("duplicate_faces")
    if pp["floaters"] > 0:
        extent = np.linalg.norm(V.max(0) - V.min(0))
        nV = [V]
        nF = [F]
        base = len(V)
        for _ in range(int(pp["floaters"])):
            s = o3d.geometry.TriangleMesh.create_sphere(
                radius=extent * rng.uniform(0.003, 0.02), resolution=4
            )
            sv = np.asarray(s.vertices)
            sv = sv * rng.uniform(0.5, 1.5, (len(sv), 1))  # lumpy, not a clean sphere
            anchor = V[rng.integers(len(V))]
            offset = rng.normal(size=3)
            offset *= extent * rng.uniform(0.01, 0.08) / np.linalg.norm(offset)
            nV.append(sv + anchor + offset)
            nF.append(np.asarray(s.triangles) + base)
            base += len(sv)
        V = np.concatenate(nV)
        F = np.concatenate(nF)
        fired.append("floaters")
    out = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(V), o3d.utility.Vector3iVector(F))
    return out


def output_transform(params: dict, rng, center: np.ndarray, derived: dict) -> tuple[np.ndarray, np.ndarray]:
    """The rigid cad -> scan pose of the export, and the per-axis calibration scale.

    Real exports are in the scanner's own frame. Turntable apps export roughly upright
    (z up, arbitrary yaw); handheld apps export in an arbitrary orientation. The scale error
    is a calibration error (slightly anisotropic): it is *not* undone by ``scan_to_cad``, so
    it counts as deviation — exactly as a real miscalibrated scanner's would.
    """
    op, rp = params["output"], params["registration"]
    scale = (1 + rng.normal(0, rp["scale_sigma"])) * (1 + rng.normal(0, rp["scale_aniso"], 3))
    if op["pose"] == "upright":
        a = rng.uniform(0, 2 * math.pi)
        R = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
    elif op["pose"] == "arbitrary":
        R = random_rotation(rng)
    else:  # "cad": keep the CAD frame (useful for debugging)
        R = np.eye(3)
    t = rng.normal(0, op["offset_mm"], 3) if op["pose"] != "cad" else np.zeros(3)
    T = rigid(R, -R @ center + center + t)
    derived["scale_xyz"] = scale.tolist()
    return T, scale
