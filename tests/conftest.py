from pathlib import Path

import numpy as np
import pytest
import trimesh

# Small, fast settings: tests check behaviour, not realism. Every test that runs the
# pipeline merges these over the sampled params via ``generate_sample(overrides=...)``.
FAST = {
    "capture": {
        "sessions": 1,
        "frames_per_session": 14,
        "spacing_mm": 0.35,
        "sensor_w_px": 320,
        "sensor_h_px": 320,
        "frame_drop_p": 0.0,
    },
    "fusion": {"method": "tsdf", "voxel_mult": 1.2},
    "post": {"decimate": 1.0, "flip_patches": 0, "dup_faces": 0, "floaters": 0, "keep_islands": False},
}


@pytest.fixture(scope="session")
def block_with_hole(tmp_path_factory) -> Path:
    """40 x 30 x 20 mm block with a 6 mm blind hole 18 mm deep from the top (an occlusion trap)."""
    d = tmp_path_factory.mktemp("parts")
    block = trimesh.creation.box((40, 30, 20))
    hole = trimesh.creation.cylinder(radius=3, height=18, sections=48)
    hole.apply_translation([0, 0, 10 - 9 + 0.001])
    part = block.difference(hole)
    assert part.is_watertight
    path = d / "block_with_hole.stl"
    part.export(path)
    return path


@pytest.fixture(scope="session")
def step_plate(tmp_path_factory) -> Path:
    from synthscan.procedural import generate

    d = tmp_path_factory.mktemp("step")
    return generate(d, 1, seed=11, kinds=["plate"])[0]


def rng(seed=0):
    return np.random.default_rng(seed)
