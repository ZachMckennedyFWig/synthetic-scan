"""Physical behaviour of the virtual scanner, on a block with a deep blind hole, in a fixed scene:
block resting on its 40 x 30 face (hole opening up), camera 250 mm straight above."""

import copy

import numpy as np
import open3d as o3d
import pytest
import trimesh
from scipy.spatial import cKDTree

from synthscan.metrics import distances_to
from synthscan.parts import load_part
from synthscan.profiles import sample_params
from synthscan.scanner import (
    PART_GID,
    Session,
    backproject,
    capture_frame,
    look_at,
    make_surface,
    registration_errors,
    rigid,
    transform,
)


def clean_params():
    """A noiseless, artifact-free scanner: each test switches on exactly one effect."""
    p = sample_params("laser_markers", np.random.default_rng(0))
    p["capture"] |= {
        "sessions": 1,
        "spacing_mm": 0.15,
        "sensor_w_px": 640,
        "sensor_h_px": 640,
        "distance_mm": 250,
        "baseline_mm": 0.0,
        "dof_frac": 0.9,
    }
    p["noise"] |= {
        k: 0.0
        for k in (
            "sigma_mm",
            "banding_mm",
            "smooth_px",
            "mixed_pixel_p",
            "outlier_frac",
            "tail_frac",
            "exposure_jitter",
        )
    }
    p["noise"]["edge_erode_px"] = 0
    p["visibility"] |= {"grazing_cos": 0.0, "projector_shadow": False}
    p["surface"] |= {
        "shiny_frac": 0.0,
        "shiny_face_p": 0.0,
        "dark_frac": 0.0,
        "spray_um": 0.0,
        "markers_per_100cm2": 0.0,
        "dropout_gain": 0.0,
    }
    p["base"] |= {"support": "plane", "cut_mm": 0.0, "remnant": False}
    return p


@pytest.fixture(scope="module")
def setup(block_with_hole):
    part = load_part(block_with_hole)
    P = rigid(np.eye(3), np.array([0, 0, 10.0]))  # trimesh box is centred: lift it onto z = 0
    v = transform(P, part.vertices)
    scene = o3d.t.geometry.RaycastingScene()
    assert (
        scene.add_triangles(
            o3d.core.Tensor(v.astype(np.float32)), o3d.core.Tensor(part.faces.astype(np.uint32))
        )
        == PART_GID
    )
    pv = np.array([[-200, -200, 0], [200, -200, 0], [200, 200, 0], [-200, 200, 0]], dtype=np.float32)
    plane = scene.add_triangles(
        o3d.core.Tensor(pv), o3d.core.Tensor(np.array([[0, 1, 2], [0, 2, 3]], dtype=np.uint32))
    )
    sp = transform(P, trimesh.sample.sample_surface(part.mesh, 20000, seed=0)[0])
    footprint = cKDTree(sp[sp[:, 2] < 1][:, :2])  # as plan_sessions builds it
    sess = Session(P, [], scene, plane, footprint)
    cam = look_at(np.array([0.0, 0.0, 270.0]), np.array([0.0, 0.0, 20.0]), np.array([0, 1.0, 0]))
    est = np.linalg.inv(P) @ cam  # perfect registration
    return part, sess, cam, est


def capture(setup, params, seed=0, surface=None):
    part, sess, cam, est = setup
    rng = np.random.default_rng(seed)
    surface = surface or make_surface(part, params["surface"], rng)
    radius = float(np.linalg.norm(np.ptp(part.vertices, axis=0)) / 2)
    return capture_frame(sess, cam, est, radius, surface, params, rng, 0)


def in_bore_bottom(pts):
    r = np.linalg.norm(pts[:, :2], axis=1)
    return int(((r < 2.0) & (pts[:, 2] < -5)).sum())  # CAD frame: top face at z = +10


def test_clean_capture_lies_exactly_on_the_surface(setup):
    part = setup[0]
    pts, _ = backproject(capture(setup, clean_params()))
    assert len(pts) > 20000
    d = np.abs(distances_to(part.vertices, part.faces, pts, signed=False))
    assert np.quantile(d, 0.99) < 0.01
    assert in_bore_bottom(pts) > 50  # straight down the bore, with no projector offset, it is seen


def test_range_noise_matches_sigma(setup):
    part = setup[0]
    p = clean_params()
    p["noise"] |= {"sigma_mm": 0.05, "distance_exp": 0.0, "incidence_gamma": 0.0}
    pts, _ = backproject(capture(setup, p))
    d = distances_to(part.vertices, part.faces, pts, signed=False)
    assert 0.035 < float(np.sqrt(np.mean(d**2))) < 0.07


def test_projector_shadow_hides_the_bottom_of_a_deep_bore(setup):
    """6 mm bore, 18 mm deep, 100 mm baseline at 250 mm: the camera sees the bottom, the projector
    cannot light it. The classic triangulation occlusion."""
    p = clean_params()
    p["capture"]["baseline_mm"] = 100.0
    p["visibility"]["projector_shadow"] = True
    pts, _ = backproject(capture(setup, p))
    assert in_bore_bottom(pts) == 0
    assert len(pts) > 15000  # the rest of the top face is still lit


def test_markers_punch_holes_or_bumps(setup):
    part = setup[0]
    base = int((capture(setup, clean_params()).depth > 0).sum())
    p = clean_params()
    p["surface"] |= {"markers_per_100cm2": 80.0, "marker_radius_mm": 3.0, "marker_mode": "hole"}
    surf = make_surface(part, p["surface"], np.random.default_rng(1))
    assert len(surf.markers) >= 3
    assert int((capture(setup, p, surface=surf).depth > 0).sum()) < base
    p2 = copy.deepcopy(p)
    p2["surface"]["marker_mode"] = "bump"
    surf.marker_bump = True
    pts, _ = backproject(capture(setup, p2, surface=surf))
    d = distances_to(part.vertices, part.faces, pts, signed=True)
    assert d.max() == pytest.approx(0.15, abs=0.02)  # sticker thickness, outward


def test_plane_cut_removes_the_bottom_band_and_remnant_keeps_a_skirt(setup):
    p = clean_params()
    side = look_at(np.array([0.0, -230.0, 90.0]), np.array([0.0, 0.0, 8.0]), np.array([0, 0, 1.0]))
    part, sess, _, _ = setup
    s2 = (part, sess, side, np.linalg.inv(sess.placement) @ side)
    p["base"]["cut_mm"] = 2.0
    pts, _ = backproject(capture(s2, p))
    assert pts[:, 2].min() > -10 + 1.9  # nothing in the bottom 2 mm of the part
    p["base"] |= {"cut_mm": 0.0, "remnant": True, "remnant_mm": 3.0}
    pts, _ = backproject(capture(s2, p))
    skirt = pts[np.abs(pts[:, 2] + 10) < 0.01]  # on the table plane
    assert len(skirt) > 100
    assert np.abs(skirt[:, 1]).max() < 15 + 3.2  # within 3 mm of the 30 mm wide footprint


def test_registration_error_is_zero_when_disabled_and_full_loop_closure_returns_home():
    rp = {
        "drift_deg": 0.0,
        "drift_mm": 0.0,
        "jitter_deg": 0.0,
        "jitter_mm": 0.0,
        "loop_closure": 1.0,
        "jump_p": 0.0,
        "jump_deg": 0.0,
        "jump_mm": 0.0,
    }
    assert all(
        np.allclose(e, np.eye(4)) for e in registration_errors(30, rp, np.random.default_rng(0), np.zeros(3))
    )
    rp |= {"drift_deg": 0.05, "drift_mm": 0.05}
    errs = registration_errors(200, rp, np.random.default_rng(0), np.zeros(3))
    assert np.linalg.norm(errs[-1][:3, 3]) < 1e-9 < max(np.linalg.norm(e[:3, 3]) for e in errs)


def test_ray_budget_coarsens_resolution_instead_of_dropping_coverage():
    """A 0.03 mm laser on an 80 mm part is far over the ray budget. The fix must be a coarser
    spacing with full frame coverage, never fewer frames (which leaves straight FOV-edge gaps)."""
    from synthscan.meshing import MAX_SURFACE_VOXELS
    from synthscan.scanner import MAX_RAYS_PER_SAMPLE, effective_spacing, frames_for, intrinsics_for

    cap = clean_params()["capture"] | {
        "spacing_mm": 0.03,
        "sensor_w_px": 1280,
        "sensor_h_px": 1024,
        "sessions": 2,
    }
    radius, area = 40.0, 15000.0
    s = effective_spacing(cap, radius, area, MAX_SURFACE_VOXELS)
    assert s > 0.03
    c = dict(cap, spacing_mm=s)
    _, W, H = intrinsics_for(c, c["distance_mm"], radius)
    n = frames_for(c, radius, 2)
    assert n * 2 * W * H <= MAX_RAYS_PER_SAMPLE
    assert n >= min(cap["frames_per_session"], 400 // 2)  # the full sweep, not a budget-cut one
    # A coarse capture already inside every cap is left alone.
    assert effective_spacing(dict(cap, spacing_mm=0.5), 10.0, 1500.0, MAX_SURFACE_VOXELS) == 0.5
