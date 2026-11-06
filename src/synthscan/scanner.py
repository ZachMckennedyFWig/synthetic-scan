"""The virtual scanner: ground-truth part in, a sequence of noisy depth frames out.

How a real structured-light / laser scanner works, and how we copy it
---------------------------------------------------------------------
A real scanner is a camera plus a projector (or laser) a *baseline* apart. A
surface point is measured only if the camera sees it **and** the projector lights
it, with enough returned light and without saturating the sensor. Each frame
is a depth image. The software estimates every frame's pose (tracking/ICP/
markers), fuses the frames (TSDF or Poisson) and post-processes the mesh.

We reproduce each step physically rather than perturbing the final mesh,
because that is what makes artifacts land where real ones do: holes in deep
bores and in the projector's shadow, rounding on convex edges, flying pixels on
silhouettes, misregistration ghosts along overlaps.

Per frame (``capture_frame``), in order:

1. Ray-cast the scene (part + optional support plane) with Embree via
   Open3D's ``RaycastingScene`` — ~40 M rays/s on 16 threads.
2. Visibility: working range, grazing-angle dropout, **projector shadow**
   (shadow rays toward the projector), plane removal / cut height.
3. Surface response: a smooth random *shiny* field plus shiny B-rep faces
   (machined flats), and a random *dark* field. These give low-return dropout,
   saturation holes and specular spikes, and raise noise.
4. Range noise along the ray: distance- and incidence-dependent sigma, white +
   spatially correlated parts, optional banding (stripe pattern ripple),
   spray-coat thickness, sparse outliers.
5. Depth-image firmware: edge-preserving blur (rounds convex edges), mixed /
   flying pixels at depth discontinuities, silhouette erosion.
6. Tracking-marker stickers punch small circular holes.

Pose estimation error (``registration_errors``) is a random walk with partial
loop closure plus per-frame jitter, and a rigid offset between scan sessions
(the "flip the part and scan the other side" merge).

Coordinate frames
-----------------
``cad``   the part's own frame (ground truth lives here).
``world`` a session's physical setup: part resting on the plane z = 0, centred on
          the z axis. ``placement`` maps cad -> world, one per session.
``cam``   OpenCV camera: +x right, +y down, +z forward.
Depth frames carry an *estimated* cam -> cad pose, so fusion directly produces a
mesh in the CAD frame (plus all the registration error).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import open3d as o3d
import trimesh
from scipy import ndimage
from scipy.spatial import cKDTree
from scipy.special import ndtri

from .parts import Part

PART_GID = 0  # geometry id of the part in every RaycastingScene (added first)
MAX_RAYS_PER_SAMPLE = 30e6  # caps capture time (~1 s of Embree, plus numpy) per sample


# --------------------------------------------------------------------------- small SE(3) helpers


def rot_from_vec(w: np.ndarray) -> np.ndarray:
    """Rodrigues: axis-angle vector (radians) -> 3x3 rotation."""
    th = float(np.linalg.norm(w))
    if th < 1e-12:
        return np.eye(3)
    k = w / th
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(th) * K + (1 - math.cos(th)) * (K @ K)


def rigid(R: np.ndarray, t: np.ndarray) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    return T


def transform(T: np.ndarray, p: np.ndarray) -> np.ndarray:
    return p @ T[:3, :3].T + T[:3, 3]


def look_at(eye: np.ndarray, target: np.ndarray, up: np.ndarray) -> np.ndarray:
    """cam -> world pose for an OpenCV camera at ``eye`` looking at ``target``."""
    z = target - eye
    z /= np.linalg.norm(z)
    x = np.cross(z, up)
    if np.linalg.norm(x) < 1e-6:  # looking straight along ``up``
        x = np.cross(z, np.array([1.0, 0, 0]))
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    return rigid(np.stack([x, y, z], axis=1), eye)


def random_rotation(rng: np.random.Generator) -> np.ndarray:
    q = rng.normal(size=4)
    q /= np.linalg.norm(q)
    w, x, y, z = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


# --------------------------------------------------------------------------- placement


def resting_poses(part: Part, rng: np.random.Generator, n: int) -> list[np.ndarray]:
    """``n`` distinct cad -> world placements, each resting the part on a convex-hull facet.

    Facets are drawn with probability proportional to area — the big flat sides a
    person would actually put a part down on. The second pose prefers the facet
    most opposite to the first, as when flipping a part to scan its underside.
    """
    hull = part.mesh.convex_hull
    normals, areas = hull.facets_normal, hull.facets_area
    if len(areas) == 0:  # a hull with no coplanar groups (very round part): use its faces
        normals, areas = hull.face_normals, hull.area_faces
    p = areas / areas.sum()
    first = int(rng.choice(len(areas), p=p))
    chosen = [first]
    if n > 1:
        opp = np.clip(1 - normals @ normals[first], 0, 2) ** 2 * areas
        opp[first] = 0
        chosen.append(int(rng.choice(len(areas), p=opp / opp.sum())) if opp.sum() > 0 else first)
    poses = []
    for idx in chosen[:n]:
        down = normals[idx]
        R = trimesh.geometry.align_vectors(down, [0, 0, -1])[:3, :3]
        R = rot_from_vec(np.array([0, 0, rng.uniform(0, 2 * math.pi)])) @ R  # random yaw on the table
        v = part.vertices @ R.T
        lo, hi = v.min(0), v.max(0)
        t = -np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]])
        poses.append(rigid(R, t))
    return poses


# --------------------------------------------------------------------------- surface response fields


class RandomField:
    """A smooth random scalar field over 3D space (random Fourier features).

    Real parts are shiny or dark in patches: a machined flat, a polished rim, an
    anodised pocket, a fingerprint. Patches here are level sets of a smooth
    Gaussian-like field, so they have random, organic shapes that do not follow
    our triangulation or any feature we could accidentally learn.
    ``coverage`` is the expected fraction of the surface inside a patch.
    """

    def __init__(self, rng: np.random.Generator, scale_mm: float, coverage: float, n: int = 16):
        d = rng.normal(size=(n, 3))
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        k = 2 * math.pi / (scale_mm * rng.uniform(0.5, 2.0, n))
        # float32 halves the cost of the cosines (millions of points x n waves per sample).
        self.W = (d * k[:, None]).astype(np.float32)
        self.phi = rng.uniform(0, 2 * math.pi, n).astype(np.float32)
        self.coverage = float(np.clip(coverage, 0.0, 1.0))
        self.threshold = float(ndtri(1 - self.coverage)) if 0 < self.coverage < 1 else 0.0

    def __call__(self, x: np.ndarray) -> np.ndarray:
        if self.coverage <= 0:
            return np.zeros(len(x), dtype=np.float32)
        if self.coverage >= 1:
            return np.ones(len(x), dtype=np.float32)
        g = np.cos(x.astype(np.float32) @ self.W.T + self.phi).sum(1) * np.float32(
            math.sqrt(2.0 / len(self.phi))
        )
        return (1 / (1 + np.exp(-(g - self.threshold) / 0.12))).astype(np.float32)  # ~N(0,1) -> soft mask


@dataclass
class Surface:
    """Per-sample surface properties of the part, all in the CAD frame."""

    shiny_field: RandomField
    dark_field: RandomField
    face_shiny: np.ndarray  # (n_triangles,) float32 in [0, 1]
    markers: np.ndarray  # (k, 3) marker sticker centres on the surface
    marker_radius: float
    marker_bump: bool  # True: sticker left on (a 0.1-0.2 mm bump); False: software masks it (a hole)
    spray_field: RandomField  # spray coats unevenly: thickness = spray * (0.6 + 0.8 * field)

    def at(self, prim: np.ndarray, p_cad: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        shiny = np.maximum(self.shiny_field(p_cad), self.face_shiny[prim])
        return shiny, self.dark_field(p_cad)


def make_surface(part: Part, sp: dict, rng: np.random.Generator) -> Surface:
    """Build the surface finish and marker layout for one sample from ``params['surface']``."""
    diag = float(np.linalg.norm(part.vertices.max(0) - part.vertices.min(0)))
    shiny = RandomField(rng, sp["shiny_scale_mm"] * max(diag, 1) / 100, sp["shiny_frac"])
    dark = RandomField(rng, sp["dark_scale_mm"] * max(diag, 1) / 100, sp["dark_frac"])
    n_faces = int(part.face_ids.max()) + 1
    shiny_faces = (rng.random(n_faces) < sp["shiny_face_p"]).astype(np.float32)
    shiny_faces *= rng.uniform(0.6, 1.0, n_faces).astype(np.float32)
    face_shiny = shiny_faces[part.face_ids]

    markers = np.zeros((0, 3))
    r = sp["marker_radius_mm"]
    if sp["markers_per_100cm2"] > 0:
        m = part.mesh
        want = int(sp["markers_per_100cm2"] * m.area / 1e4)
        if want > 0:
            cand, _ = trimesh.sample.sample_surface(m, want * 4, seed=int(rng.integers(1 << 31)))
            keep: list[np.ndarray] = []
            for c in cand:  # greedy min-spacing thinning: real stickers never overlap
                if all(np.linalg.norm(c - k) > 4 * r for k in keep):
                    keep.append(c)
                    if len(keep) >= want:
                        break
            markers = np.array(keep) if keep else markers
    spray = RandomField(rng, 0.25 * max(diag, 1), 0.5)
    return Surface(shiny, dark, face_shiny, markers, r, sp["marker_mode"] == "bump", spray)


# --------------------------------------------------------------------------- trajectories


@dataclass
class Session:
    """One physical scanning pass: a placement of the part and the camera path around it."""

    placement: np.ndarray  # cad -> world
    cam_poses: list[np.ndarray]  # true cam -> world, one per frame
    scene: o3d.t.geometry.RaycastingScene
    plane_gid: int | None
    footprint: cKDTree | None  # 2D tree of the part's near-plane outline, for the remnant skirt


def frames_for(cap: dict, radius: float, n_sessions: int, total_cap: int = 400) -> int:
    """Frames per session: enough for the field of view to sweep the whole part."""
    fov_half = min(cap["sensor_w_px"], cap["sensor_h_px"]) / 2 * cap["spacing_mm"]
    size_factor = float(np.clip((radius / max(fov_half, 1e-6)) ** 2, 1.0, 6.0))
    return max(6, int(min(total_cap // n_sessions, round(cap["frames_per_session"] * size_factor))))


def effective_spacing(cap: dict, radius: float, area_mm2: float, max_surface_voxels: float) -> float:
    """The capture point spacing actually simulated (recorded as ``derived.capture_spacing_mm``).

    Two caps, both traded against *resolution*, never coverage. (Dropping frames instead
    left gaps with straight field-of-view edges no real scan has: a generator fingerprint.)
    1. Finer than ~half the fusion voxel floor is detail the fusion throws away anyway.
    2. If all frames at that spacing exceed the ray budget, coarsen until they fit. Coarser
       spacing also widens the field of view, so fewer frames are needed: both shrink."""
    s = max(cap["spacing_mm"], 0.6 * math.sqrt(max(area_mm2, 1.0) / max_surface_voxels))
    n_sessions = int(cap["sessions"])
    for _ in range(80):
        c = dict(cap, spacing_mm=s)
        _, W, H = intrinsics_for(c, c["distance_mm"], radius)
        if frames_for(c, radius, n_sessions) * n_sessions * W * H <= MAX_RAYS_PER_SAMPLE:
            break
        s *= 1.08
    return s


def plan_sessions(part: Part, params: dict, rng: np.random.Generator, derived: dict) -> list[Session]:
    cap = params["capture"]
    base = params["base"]
    n_sessions = int(cap["sessions"])
    placements = resting_poses(part, rng, n_sessions)
    sessions = []
    total_cap = 400  # frames across all sessions; bounds runtime on huge parts
    surf_pts, _ = trimesh.sample.sample_surface(part.mesh, 20000, seed=int(rng.integers(1 << 31)))
    for P in placements:
        v = transform(P, part.vertices)
        lo, hi = v.min(0), v.max(0)
        center = (lo + hi) / 2
        radius = float(np.linalg.norm(hi - lo) / 2)
        # The remnant skirt hugs the contact outline: plane points near the part's bottom band.
        sp_w = transform(P, surf_pts)
        band = sp_w[sp_w[:, 2] < max(base["remnant_mm"], 1.0)]
        footprint = cKDTree(band[:, :2]) if len(band) else None

        scene = o3d.t.geometry.RaycastingScene()
        gid = scene.add_triangles(
            o3d.core.Tensor(v.astype(np.float32)), o3d.core.Tensor(part.faces.astype(np.uint32))
        )
        assert gid == PART_GID
        plane_gid = None
        if base["support"] == "plane":
            L = max(radius * 4, 50.0)
            pv = np.array([[-L, -L, 0], [L, -L, 0], [L, L, 0], [-L, L, 0]], dtype=np.float32)
            pf = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.uint32)
            plane_gid = scene.add_triangles(o3d.core.Tensor(pv), o3d.core.Tensor(pf))

        n = frames_for(cap, radius, n_sessions, total_cap)
        poses = _trajectory(cap, base, center, radius, n, rng)
        sessions.append(Session(P, poses, scene, plane_gid, footprint))
        derived.setdefault("frames", []).append(n)
    return sessions


def _trajectory(cap, base, center, radius, n, rng) -> list[np.ndarray]:
    """Camera path for one session. Turntable = rings at fixed elevations; handheld = a smooth
    random walk over the viewing hemisphere with wandering distance and aim."""
    d0 = cap["distance_mm"]
    up = np.array([0.0, 0, 1])
    el_lo, el_hi = math.radians(cap["elev_min_deg"]), math.radians(cap["elev_max_deg"])
    if base["support"] == "plane":
        el_lo = max(el_lo, math.radians(4))  # you cannot look up through the table
    el_hi = max(el_hi, el_lo + 1e-3)
    poses = []
    if cap["mode"] == "turntable":
        rings = max(1, int(cap["rings"]))
        per = max(3, n // rings)
        els = np.linspace(el_lo, el_hi, rings) if rings > 1 else [rng.uniform(el_lo, el_hi)]
        phase = rng.uniform(0, 2 * math.pi)
        for el in els:
            el = el + rng.normal(0, math.radians(1.5))
            for i in range(per):
                az = phase + 2 * math.pi * i / per + rng.normal(0, 0.01)
                d = d0 * (1 + rng.normal(0, 0.01))
                eye = center + d * np.array(
                    [math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)]
                )
                target = center + rng.normal(0, 0.02 * radius, 3)
                poses.append(look_at(eye, target, up))
    else:
        laps = rng.uniform(1.0, 2.5)
        az = rng.uniform(0, 2 * math.pi)
        el = rng.uniform(el_lo, el_hi)
        el_v = 0.0
        aim = np.zeros(3)
        fov_half = min(cap["sensor_w_px"], cap["sensor_h_px"]) / 2 * cap["spacing_mm"]
        aim_range = max(0.0, radius - 0.6 * fov_half) + cap["target_jitter"] * radius
        for _ in range(n):
            az += 2 * math.pi * laps / n * rng.uniform(0.3, 1.7)
            el_v = 0.8 * el_v + rng.normal(0, (el_hi - el_lo) * 0.08)
            el += el_v
            if el < el_lo or el > el_hi:  # reflect off the elevation limits
                el = float(np.clip(el, el_lo, el_hi))
                el_v = -el_v
            aim = 0.85 * aim + rng.normal(0, 0.35 * aim_range + 1e-6, 3)
            aim = np.clip(aim, -aim_range, aim_range)
            d = d0 * float(np.clip(1 + rng.normal(0, cap["distance_jitter"]), 0.6, 1.5))
            target = center + aim
            eye = target + d * np.array(
                [math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)]
            )
            # A hand rolls the scanner a little; that rotates the stripe/banding direction.
            roll_up = rot_from_vec((eye - target) / d * rng.normal(0, 0.3)) @ up
            poses.append(look_at(eye, target, roll_up))
    return poses


# --------------------------------------------------------------------------- registration error


def registration_errors(
    n: int, rp: dict, rng: np.random.Generator, pivot: np.ndarray, info: dict | None = None
) -> list[np.ndarray]:
    """Per-frame pose error (applied as ``E @ true_cam_to_cad``) for one session.

    Tracking drift is a random walk in se(3) (small-angle vectors). Global optimisation /
    loop closure removes a fraction ``loop_closure`` of the end-point drift, linearly over the
    sequence, which leaves the bowed residual that shows up as seams and doubled walls.
    Rotations pivot about the part centre so a rotational drift does not fling the part away.
    """
    step = np.concatenate([np.full(3, math.radians(rp["drift_deg"])), np.full(3, rp["drift_mm"])])
    inc = rng.normal(size=(n, 6)) * step
    if n > 2 and rng.random() < rp["jump_p"]:
        # Tracking lost and re-acquired slightly wrong: one step offset for the rest of the pass.
        k = int(rng.integers(1, n - 1))
        w = rng.normal(size=6)
        w[:3] *= math.radians(rp["jump_deg"]) / max(np.linalg.norm(w[:3]), 1e-9)
        w[3:] *= rp["jump_mm"] / max(np.linalg.norm(w[3:]), 1e-9)
        inc[k] += w
        if info is not None:
            info.setdefault("tracking_jumps", []).append(
                {"frame": k, "deg": rp["jump_deg"], "mm": rp["jump_mm"]}
            )
    walk = np.cumsum(inc, axis=0)
    if n > 1:
        walk -= rp["loop_closure"] * np.linspace(0, 1, n)[:, None] * walk[-1]
    jit = np.concatenate([np.full(3, math.radians(rp["jitter_deg"])), np.full(3, rp["jitter_mm"])])
    walk += rng.normal(size=(n, 6)) * jit
    out = []
    for w in walk:
        R = rot_from_vec(w[:3])
        out.append(rigid(R, pivot - R @ pivot + w[3:]))
    return out


def session_offset(rp: dict, rng: np.random.Generator, pivot: np.ndarray) -> np.ndarray:
    """The rigid misalignment left after merging a second session onto the first."""
    w = rng.normal(size=3)
    w *= math.radians(rp["session_deg"]) / max(np.linalg.norm(w), 1e-9)
    t = rng.normal(size=3)
    t *= rp["session_mm"] / max(np.linalg.norm(t), 1e-9)
    R = rot_from_vec(w)
    return rigid(R, pivot - R @ pivot + t)


# --------------------------------------------------------------------------- capture


@dataclass
class Frame:
    depth: np.ndarray  # (H, W) float32 mm along the optical axis, 0 = no measurement
    K: np.ndarray  # 3x3 intrinsics
    cam_to_cad: np.ndarray  # *estimated* pose (includes registration error)
    stats: dict = field(default_factory=dict)


def intrinsics_for(cap: dict, eye_dist: float, radius: float) -> tuple[np.ndarray, int, int]:
    """Pinhole intrinsics whose pixel footprint at the nominal distance is ``spacing_mm``.

    The image is cropped to the part's projected bounding sphere: a real sensor is bigger,
    but rays that cannot hit the part are wasted work (and the far background is never
    scanned in a real session either)."""
    f = cap["distance_mm"] / cap["spacing_mm"]
    half_angle = math.asin(min(radius / max(eye_dist, 1e-6), 0.98))
    half_px = f * math.tan(half_angle) * 1.15 + 4
    W = int(min(cap["sensor_w_px"], 2 * math.ceil(half_px)))
    H = int(min(cap["sensor_h_px"], 2 * math.ceil(half_px)))
    K = np.array([[f, 0, W / 2], [0, f, H / 2], [0, 0, 1]])
    return K, W, H


def capture_frame(
    session: Session,
    cam_to_world: np.ndarray,
    est_cam_to_cad: np.ndarray,
    part_radius: float,
    surface: Surface,
    params: dict,
    rng: np.random.Generator,
    nthreads: int,
) -> Frame:
    cap, nz, vis, sp, base = (params[k] for k in ("capture", "noise", "visibility", "surface", "base"))
    eye = cam_to_world[:3, 3]
    target_dist = float(np.linalg.norm(eye - session.placement[:3, 3]))
    K, W, H = intrinsics_for(cap, target_dist, part_radius)
    world_to_cam = np.linalg.inv(cam_to_world)
    rays = o3d.t.geometry.RaycastingScene.create_rays_pinhole(
        o3d.core.Tensor(K), o3d.core.Tensor(world_to_cam), W, H
    )
    hit = session.scene.cast_rays(rays, nthreads=nthreads)
    t = hit["t_hit"].numpy()
    ok = np.isfinite(t)
    stats = {"pixels": W * H, "hits": int(ok.sum())}
    depth = np.zeros((H, W), dtype=np.float32)
    if not ok.any():
        return Frame(depth, K, est_cam_to_cad, stats)

    r = rays.numpy()
    gid_img = hit["geometry_ids"].numpy()
    # Early cut: most rays hit the table. The software removes it, so only part hits and the
    # remnant skirt (if this scan keeps one) are worth simulating further.
    cand = ok & (gid_img == PART_GID)
    if session.plane_gid is not None and base["remnant"] and session.footprint is not None:
        py, px = np.nonzero(ok & (gid_img == session.plane_gid))
        pp = r[py, px, :2] + r[py, px, 3:5] * t[py, px, None]
        lo2, hi2 = session.footprint.mins - base["remnant_mm"], session.footprint.maxes + base["remnant_mm"]
        near = np.all((pp > lo2) & (pp < hi2), axis=1)
        if near.any():
            d2, _ = session.footprint.query(pp[near], distance_upper_bound=base["remnant_mm"])
            sel = np.nonzero(near)[0][np.isfinite(d2)]
            cand[py[sel], px[sel]] = True
            stats["remnant_px"] = int(len(sel))
    iy, ix = np.nonzero(cand)
    if len(iy) == 0:
        return Frame(depth, K, est_cam_to_cad, stats)
    o, dvec = r[iy, ix, :3].astype(np.float64), r[iy, ix, 3:].astype(np.float64)
    tt = t[iy, ix].astype(np.float64)
    p = o + dvec * tt[:, None]
    dnorm = np.linalg.norm(dvec, axis=1)
    v = dvec / dnorm[:, None]  # unit ray direction (camera -> surface)
    tr = tt * dnorm  # metric range along the ray
    n = hit["primitive_normals"].numpy()[iy, ix].astype(np.float64)
    n *= -np.sign(np.einsum("ij,ij->i", n, v))[:, None]  # face the camera
    gid = gid_img[iy, ix]
    prim = hit["primitive_ids"].numpy()[iy, ix]
    is_part = gid == PART_GID
    keep = np.ones(len(p), dtype=bool)

    # -- 2. visibility -------------------------------------------------------------------
    z = (p - eye) @ cam_to_world[:3, 2]
    dof = cap["dof_frac"]
    keep &= (z > cap["distance_mm"] * (1 - dof)) & (z < cap["distance_mm"] * (1 + dof))

    cos_i = np.abs(np.einsum("ij,ij->i", n, v))
    # Soft grazing cut-off: real sensors fade out rather than clip at one angle.
    keep &= cos_i > vis["grazing_cos"] * rng.uniform(0.6, 1.4, len(p))

    if session.plane_gid is not None:
        # Plane removal cuts slightly above the table: the part's bottom band goes with it.
        keep &= ~(is_part & (p[:, 2] < base["cut_mm"]))
    stats["visible"] = int(keep.sum())

    proj = eye + cam_to_world[:3, 0] * cap["baseline_mm"]  # projector sits along the camera's x axis
    to_proj = proj - p
    proj_dist = np.linalg.norm(to_proj, axis=1)
    l = to_proj / proj_dist[:, None]
    cos_l = np.einsum("ij,ij->i", n, l) if cap["baseline_mm"] > 0 else cos_i
    if vis["projector_shadow"] and cap["baseline_mm"] > 0:
        keep &= cos_l > 0.02
        idx = np.nonzero(keep)[0]
        if len(idx):
            eps = 1e-3 * max(part_radius, 1.0)
            srays = np.concatenate([p[idx] + n[idx] * eps, l[idx]], axis=1).astype(np.float32)
            occ = session.scene.test_occlusions(
                o3d.core.Tensor(srays), tnear=0.0, tfar=float(proj_dist.max()), nthreads=nthreads
            ).numpy()
            # test_occlusions has one tfar for all rays; reject only blockers nearer than the projector.
            if occ.any():
                sub = idx[occ]
                tb = session.scene.cast_rays(o3d.core.Tensor(srays[occ]), nthreads=nthreads)["t_hit"].numpy()
                keep[sub[tb < proj_dist[sub] - 2 * eps]] = False
    stats["lit"] = int(keep.sum())

    # -- 3. surface response -------------------------------------------------------------
    p_cad = transform(np.linalg.inv(session.placement), p)
    shiny = np.zeros(len(p), dtype=np.float32)
    dark = np.zeros(len(p), dtype=np.float32)
    if is_part.any():
        shiny[is_part], dark[is_part] = surface.at(prim[is_part], p_cad[is_part])
    h = l - v  # half vector between "to projector" and "to camera"
    h /= np.linalg.norm(h, axis=1, keepdims=True)
    spec = shiny * np.clip(np.einsum("ij,ij->i", n, h), 0, 1) ** sp["specular_exp"]
    diffuse = np.clip(cos_l, 0, 1) * (1 - 0.75 * shiny) * (1 - 0.85 * dark)
    low = rng.random(len(p)) * sp["dropout_gain"] > diffuse
    keep &= ~low
    saturated = spec > sp["saturation"]
    spike = saturated & (rng.random(len(p)) < sp["spike_p"])
    keep &= ~(saturated & ~spike)
    stats["returned"] = int(keep.sum())

    # -- 4. range noise along the ray -----------------------------------------------------
    rel = z / cap["distance_mm"]
    exposure = 1 + rng.uniform(-1, 1) * nz["exposure_jitter"]  # auto-exposure varies frame to frame
    sigma = (
        nz["sigma_mm"]
        * exposure
        * np.clip(rel, 0.3, 3) ** nz["distance_exp"]
        * np.clip(cos_i, 0.2, 1) ** (-nz["incidence_gamma"])
        * (1 + 2.0 * dark + 0.5 * shiny)
    )
    white = rng.normal(size=len(p))
    cs = nz["corr_share"]
    if cs > 0 and nz["corr_px"] > 0:
        field_img = ndimage.gaussian_filter(rng.normal(size=(H, W)).astype(np.float32), nz["corr_px"])
        field_img /= max(float(field_img.std()), 1e-9)
        noise = math.sqrt(1 - cs) * white + math.sqrt(cs) * field_img[iy, ix]
    else:
        noise = white
    if nz["tail_frac"] > 0:  # heavy tail: decoding errors are not Gaussian
        tail = rng.random(len(p)) < nz["tail_frac"]
        noise[tail] *= nz["tail_mult"]
    dr = sigma * noise
    if nz["banding_mm"] > 0:
        dr += nz["banding_mm"] * np.sin(
            2 * math.pi * iy / nz["banding_period_px"] + rng.uniform(0, 2 * math.pi)
        )
    if sp["spray_um"] > 0 and is_part.any():
        coat = np.zeros(len(p))
        coat[is_part] = sp["spray_um"] * 1e-3 * (0.6 + 0.8 * surface.spray_field(p_cad[is_part]))
        dr -= coat / np.clip(cos_i, 0.2, 1)  # the surface moves outward = toward the camera
    if spike.any():
        dr[spike] += rng.normal(0, sp["spike_mm"], int(spike.sum()))
    if nz["outlier_frac"] > 0:
        out = rng.random(len(p)) < nz["outlier_frac"]
        dr[out] += rng.uniform(-nz["outlier_mm"], nz["outlier_mm"], int(out.sum()))
    zn = z * (tr + dr) / tr

    # -- 6. markers (before rasterising, they are a surface property) ----------------------
    if len(surface.markers):
        dist, _ = cKDTree(surface.markers).query(p_cad, distance_upper_bound=surface.marker_radius)
        on_marker = is_part & np.isfinite(dist)
        if surface.marker_bump:
            dr_m = 0.15 / np.clip(cos_i[on_marker], 0.2, 1)  # ~0.1-0.2 mm sticker thickness
            zn[on_marker] = z[on_marker] * (tr[on_marker] + dr[on_marker] - dr_m) / tr[on_marker]
        else:
            keep &= ~on_marker

    depth[iy[keep], ix[keep]] = zn[keep]

    # -- 5. depth-image firmware -----------------------------------------------------------
    valid = depth > 0
    if nz["smooth_px"] > 0 and valid.any():
        num = ndimage.gaussian_filter(depth, nz["smooth_px"])
        den = ndimage.gaussian_filter(valid.astype(np.float32), nz["smooth_px"])
        blurred = np.where(den > 1e-3, num / np.maximum(den, 1e-3), 0)
        # Edge-preserving: blur across creases (rounds them), never across a depth jump.
        smooth_ok = valid & (np.abs(blurred - depth) < nz["smooth_jump_mm"])
        depth[smooth_ok] = blurred[smooth_ok]
    if nz["mixed_pixel_p"] > 0 and valid.any():
        _mixed_pixels(depth, valid, nz["smooth_jump_mm"], nz["mixed_pixel_p"], rng)
    if nz["edge_erode_px"] > 0:
        eroded = ndimage.binary_erosion(depth > 0, iterations=int(nz["edge_erode_px"]))
        depth[~eroded] = 0
    stats["kept"] = int((depth > 0).sum())
    return Frame(depth, K, est_cam_to_cad, stats)


def _mixed_pixels(depth: np.ndarray, valid: np.ndarray, jump: float, prob: float, rng) -> None:
    """Flying pixels: a pixel straddling a depth step averages foreground and background, so it
    lands in empty space between them. Only near-side pixels next to a far neighbour move."""
    far = np.zeros_like(depth)
    for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        nb = np.roll(depth, (dy, dx), axis=(0, 1))
        nbv = np.roll(valid, (dy, dx), axis=(0, 1))
        far = np.where(nbv & (nb > far), nb, far)
    edge = valid & (far - depth > jump)
    sel = edge & (rng.random(depth.shape) < prob)
    if sel.any():
        u = rng.random(int(sel.sum())).astype(np.float32)
        depth[sel] = depth[sel] + u * (far[sel] - depth[sel])


def backproject(frame: Frame, stride: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """Depth frame -> (points, unit vectors toward the camera), both in the CAD frame (estimated)."""
    d = frame.depth[::stride, ::stride]
    iy, ix = np.nonzero(d > 0)
    z = d[iy, ix].astype(np.float64)
    fx, fy, cx, cy = frame.K[0, 0], frame.K[1, 1], frame.K[0, 2], frame.K[1, 2]
    # Open3D's create_rays_pinhole shoots through pixel *centres* (u + 0.5); so must we, or every
    # point slides half a pixel sideways (a 0.07 mm bias on inclined surfaces at 0.15 mm spacing).
    u, v = ix * stride + 0.5, iy * stride + 0.5
    pc = np.stack([(u - cx) * z / fx, (v - cy) * z / fy, z], axis=1)
    pts = transform(frame.cam_to_cad, pc)
    to_cam = frame.cam_to_cad[:3, 3] - pts
    to_cam /= np.linalg.norm(to_cam, axis=1, keepdims=True)
    return pts, to_cam
