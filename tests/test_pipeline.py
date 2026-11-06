import json
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh
from conftest import FAST

from synthscan.metrics import distances_to
from synthscan.parts import load_part
from synthscan.pipeline import generate_sample, split_for
from synthscan.scanner import transform


def test_step_loader_extracts_exact_hole_labels(step_plate):
    part = load_part(step_plate)
    params = json.loads(step_plate.with_name(step_plate.stem + ".params.json").read_text())
    assert part.mesh.is_watertight
    holes = [f for f in part.features if f["type"] == "cylinder" and f.get("concave")]
    assert holes, "a procedural plate always has through holes"
    for h in holes:
        assert h["radius"] * 2 == pytest.approx(params["hole_d"], abs=1e-6)


def test_sample_is_deterministic_and_aligned(block_with_hole, tmp_path):
    part = load_part(block_with_hole)
    a = generate_sample(part, 0, "budget_ir_handheld", 5, tmp_path / "a", overrides=FAST)
    b = generate_sample(part, 0, "budget_ir_handheld", 5, tmp_path / "b", overrides=FAST)
    assert a["params"] == b["params"]
    assert a["metrics"]["chamfer_mm"] == pytest.approx(b["metrics"]["chamfer_mm"], rel=1e-6)
    assert (tmp_path / "a" / "scan.stl").read_bytes() == (tmp_path / "b" / "scan.stl").read_bytes()

    # The exported scan is in a random pose; scan_to_cad must bring it back onto the part.
    m = trimesh.load(tmp_path / "a" / "scan.stl")
    v = transform(np.array(a["transforms"]["scan_to_cad"]), np.asarray(m.vertices))
    d = np.abs(distances_to(part.vertices, part.faces, v, signed=False))
    assert np.median(d) < 0.3
    raw = np.abs(distances_to(part.vertices, part.faces, np.asarray(m.vertices), signed=False))
    if a["params"]["output"]["pose"] != "cad":
        assert np.median(raw) > np.median(d)


def test_different_samples_differ(block_with_hole, tmp_path):
    part = load_part(block_with_hole)
    a = generate_sample(part, 0, "random", 5, tmp_path / "a", overrides=FAST)
    b = generate_sample(part, 1, "random", 5, tmp_path / "b", overrides=FAST)
    assert a["params"] != b["params"]


@pytest.mark.parametrize("method", ["tsdf", "tsdf_poisson", "poisson"])
def test_every_fusion_method_produces_a_close_surface(block_with_hole, tmp_path, method):
    part = load_part(block_with_hole)
    ov = json.loads(json.dumps(FAST))
    ov["fusion"]["method"] = method
    ov["post"] |= {"hole_fill": "none", "smoothing": "none"}
    meta = generate_sample(part, 2, "laser_markers", 9, tmp_path / method, overrides=ov)
    m = meta["metrics"]
    assert m["n_tris"] > 500
    assert m["scan_to_gt"]["p95"] < 1.0, m
    # Only 14 frames, and the face it rests on is never seen: a third of the area is plenty.
    assert m["coverage"] > 0.25
    assert f"fusion_{method}" in meta["artifacts"]


def test_hole_fill_all_closes_the_mesh(block_with_hole, tmp_path):
    part = load_part(block_with_hole)
    ov = json.loads(json.dumps(FAST))
    ov["post"] |= {"hole_fill": "all", "smoothing": "none", "keep_islands": False, "island_frac": 0.5}
    meta = generate_sample(part, 3, "laser_markers", 9, tmp_path / "w", overrides=ov)
    assert meta["metrics"]["n_boundary_edges"] == 0, meta["metrics"]


def test_split_is_a_stable_function_of_content():
    assert split_for("00000000aaaa") == split_for("00000000bbbb")
    counts = {"train": 0, "val": 0, "test": 0}
    for i in range(2000):
        counts[split_for(f"{i * 2654435761 % (1 << 32):08x}")] += 1
    assert 0.75 < counts["train"] / 2000 < 0.85 and counts["test"] > 120


def test_procedural_plate_holes_never_overlap():
    """A web of >= 2 mm (or half a diameter) between neighbouring holes, for every draw."""
    from synthscan.procedural import plate

    for s in range(40):
        _, p = plate(np.random.default_rng(s))
        web = max(2.0, 0.5 * p["hole_d"])
        for n, pitch in zip(p["holes"], p["pitch"], strict=True):
            assert n == 1 or pitch >= p["hole_d"] + web - 1e-6, (s, p)


def test_operator_picks_a_finer_setting_for_a_small_part():
    from synthscan.pipeline import operator_spacing
    from synthscan.profiles import finest_spacing

    part = SimpleNamespace(mesh=trimesh.creation.box((9.4, 9.8, 19.0)))
    params = {
        "profile": "phone",
        "capture": {"spacing_mm": 1.28},
        "fusion": {"voxel_mult": 1.45},
        "operator": {"voxels_across_min": 8.0},
    }
    derived: dict = {}
    s = operator_spacing(part, params, derived)
    assert s == pytest.approx(9.8 / 8.0 / 1.45, rel=1e-6)
    assert derived["operator_spacing_mm"] == s
    # Never finer than the scanner offers, and a large part is left alone.
    tiny = SimpleNamespace(mesh=trimesh.creation.box((1.0, 1.0, 2.0)))
    assert operator_spacing(tiny, params, {}) == finest_spacing("phone")
    big = SimpleNamespace(mesh=trimesh.creation.box((80.0, 90.0, 100.0)))
    assert operator_spacing(big, params, {}) == 1.28
