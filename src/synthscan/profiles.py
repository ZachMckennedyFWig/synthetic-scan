"""Scanner profiles: correlated priors over every simulation parameter.

A profile is a nested dict of distributions (``randomness.Dist``) with the same
shape as the sampled ``params`` tree in ``meta.json``. Ranges come from
``docs/research/scan-artifacts.md`` §4.3 (P1–P5) and its artifact catalogue;
where that doc tags a number ``[est]``, so is ours — those are the first
numbers to replace with measurements of real scans (``docs/PLAN.md``, M2).

Anti-fingerprinting (research §4.4), built in:

* ``random`` picks a profile per sample, then with probability ``WILD_P``
  samples it *widened* (ranges ×``WILD_WIDEN``, categorical weights flattened),
  so profile boundaries are not hard edges a model can learn.
* Algorithms are randomized, not just parameters: 3 fusers, 3 smoothers,
  2 decimators, 2 hole-fill modes, 3 output poses.
* ``cohere`` enforces the physical correlations after sampling (spray kills
  shine, markers mean low drift, ...), so widened draws stay plausible.

Bump ``PROFILES_VERSION`` whenever a range changes: it is recorded per sample,
and datasets made with different versions are not comparable.
"""

from __future__ import annotations

import copy

import numpy as np

from .randomness import Bern, Choice, Const, IntU, LogU, Maybe, U, sample_tree

PROFILES_VERSION = 2  # 2: OPERATOR (resolution chosen for the part's size)
WILD_P = 0.15
WILD_WIDEN = 1.6


def _base() -> dict:
    """Shared defaults; each profile overrides what differs."""
    return {
        "capture": {
            "mode": Choice.of(handheld=1.0),
            "sessions": Choice(((1, 0.6), (2, 0.4))),
            "frames_per_session": IntU(40, 90),
            "rings": IntU(1, 3),
            "elev_min_deg": U(5, 20),
            "elev_max_deg": U(45, 80),
            "distance_mm": U(250, 400),
            "distance_jitter": U(0.03, 0.12),
            "dof_frac": U(0.35, 0.6),
            "spacing_mm": LogU(0.15, 0.5),
            "sensor_w_px": Const(1280),
            "sensor_h_px": Const(1024),
            "baseline_mm": U(40, 120),
            "target_jitter": U(0.05, 0.3),
            "frame_drop_p": U(0.0, 0.05),
        },
        "noise": {
            "sigma_mm": LogU(0.05, 0.15),
            "distance_exp": U(1.5, 2.0),
            "incidence_gamma": U(0.3, 1.0),
            "exposure_jitter": U(0.05, 0.25),
            "corr_px": U(1.0, 4.0),
            "corr_share": U(0.2, 0.7),
            "tail_frac": U(0.01, 0.03),
            "tail_mult": U(3, 6),
            "banding_mm": Maybe(0.3, LogU(0.005, 0.03)),
            "banding_period_px": U(6, 40),
            "smooth_px": U(0.0, 1.5),
            "smooth_jump_mm": U(0.8, 3.0),
            "mixed_pixel_p": U(0.1, 0.6),
            "edge_erode_px": IntU(0, 2),
            "outlier_frac": Maybe(0.5, LogU(1e-4, 3e-3)),
            "outlier_mm": U(1, 15),
        },
        "visibility": {
            "grazing_cos": U(0.26, 0.42),  # cos(65..75 deg)
            "projector_shadow": Const(True),
        },
        "surface": {
            "shiny_frac": Maybe(0.5, U(0.05, 0.35)),
            "shiny_scale_mm": U(8, 40),  # per 100 mm of part diagonal
            "shiny_face_p": Maybe(0.5, U(0.05, 0.3)),
            "dark_frac": Maybe(0.4, U(0.05, 0.5)),
            "dark_scale_mm": U(10, 60),
            "specular_exp": U(20, 200),
            "saturation": U(0.5, 0.9),
            "spike_p": U(0.05, 0.3),
            "spike_mm": LogU(0.1, 1.5),
            "dropout_gain": U(0.05, 0.25),
            "spray_um": Maybe(0.1, U(8, 50)),
            "markers_per_100cm2": Maybe(0.15, U(4, 20)),
            "marker_radius_mm": Choice(((1.5, 0.3), (2.5, 0.2), (3.0, 0.4), (5.0, 0.1))),
            "marker_mode": Choice.of(hole=0.7, bump=0.3),
        },
        "registration": {
            "drift_deg": LogU(0.003, 0.03),
            "drift_mm": LogU(0.003, 0.03),
            "jitter_deg": LogU(0.002, 0.02),
            "jitter_mm": LogU(0.002, 0.03),
            "loop_closure": U(0.5, 0.9),
            "jump_p": U(0.1, 0.4),
            "jump_deg": U(0.1, 1.5),
            "jump_mm": U(0.2, 2.0),
            "session_deg": U(0.02, 0.4),
            "session_mm": U(0.05, 0.4),
            "scale_sigma": LogU(5e-4, 3e-3),
            "scale_aniso": LogU(5e-5, 5e-4),
        },
        "base": {
            "support": Choice.of(plane=0.9, none=0.1),
            "cut_mm": U(0.0, 1.0),
            "remnant": Bern(0.3),
            "remnant_mm": U(1, 5),
        },
        "fusion": {
            "method": Choice.of(tsdf=0.3, tsdf_poisson=0.5, poisson=0.2),
            "voxel_mult": U(0.9, 2.0),
            "trunc_vox": U(3, 5),
            "poisson_depth_offset": IntU(-1, 1),
            "density_trim_q": Maybe(0.3, U(0.005, 0.05)),
            "normal_knn": IntU(15, 40),
        },
        "post": {
            "keep_islands": Bern(0.15),
            "island_frac": LogU(0.002, 0.05),
            "hole_fill": Choice.of(none=0.4, small=0.4, all=0.2),
            "hole_fill_mm": U(1, 8),
            "smoothing": Choice.of(none=0.2, taubin=0.5, laplacian=0.15, simple=0.15),
            "smooth_iters": IntU(1, 10),
            "decimate": Maybe(0.6, U(0.1, 0.8), off=1.0),
            "decimator": Choice.of(quadric=0.8, cluster=0.2),
            "flip_patches": Maybe(0.05, IntU(1, 3)),
            "dup_faces": Maybe(0.03, IntU(1, 20)),
            "floaters": Maybe(0.08, IntU(1, 3)),
        },
        "output": {
            "pose": Choice.of(upright=0.4, arbitrary=0.6),
            "offset_mm": U(0, 100),
        },
    }


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


PROFILES: dict[str, dict] = {
    # P1: Ferret Pro / POP 3 / Einstar class, novice, no prep. Rounded edges, ghosting, W meshes.
    "budget_ir_handheld": {
        "label": "Budget IR handheld",
        "description": "Ferret/POP/Einstar class, no prep, feature tracking, one-click watertight export",
        "weight": 0.3,
        "spec": _merge(
            _base(),
            {
                "capture": {"sessions": Choice(((1, 0.6), (2, 0.4)))},
                "registration": {
                    "drift_deg": LogU(0.01, 0.06),
                    "drift_mm": LogU(0.01, 0.06),
                    "jump_p": U(0.1, 0.4),
                },
                "fusion": {"method": Choice.of(tsdf=0.3, tsdf_poisson=0.7), "voxel_mult": U(1.0, 2.5)},
                "post": {
                    "smoothing": Choice.of(taubin=0.6, laplacian=0.2, simple=0.2),
                    "smooth_iters": IntU(2, 15),
                    "hole_fill": Choice.of(none=0.2, small=0.3, all=0.5),
                },
            },
        ),
    },
    # P2: MINI 2 / EinScan SP class on a turntable. Flip seams, plane remnants, banding.
    "bluelight_turntable": {
        "label": "Blue-light turntable",
        "description": "MINI/EinScan SP class on a turntable, sometimes sprayed, flip-and-merge",
        "weight": 0.25,
        "spec": _merge(
            _base(),
            {
                "capture": {
                    "mode": Choice.of(turntable=1.0),
                    "sessions": Choice(((1, 0.4), (2, 0.6))),
                    "frames_per_session": IntU(16, 60),
                    "distance_mm": U(150, 300),
                    "spacing_mm": LogU(0.05, 0.2),
                    "baseline_mm": U(40, 90),
                },
                "noise": {"sigma_mm": LogU(0.02, 0.06), "banding_mm": Maybe(0.5, LogU(0.005, 0.03))},
                "surface": {"spray_um": Maybe(0.4, U(10, 50)), "markers_per_100cm2": Maybe(0.05, U(4, 12))},
                "registration": {
                    "drift_deg": LogU(0.002, 0.01),
                    "drift_mm": LogU(0.002, 0.01),
                    "jump_p": U(0, 0.1),
                    "session_mm": U(0.05, 0.3),
                },
                "base": {"support": Const("plane"), "remnant": Bern(0.4)},
                "fusion": {"method": Choice.of(tsdf=0.5, tsdf_poisson=0.4, poisson=0.1)},
                "post": {"hole_fill": Choice.of(none=0.3, small=0.5, all=0.2), "smooth_iters": IntU(0, 6)},
                "output": {"pose": Choice.of(upright=0.7, arbitrary=0.3)},
            },
        ),
    },
    # P3: Raptor laser / MetroX / FreeScan class. Crisp, sprayed, marker holes, open meshes.
    "laser_markers": {
        "label": "Blue laser + markers",
        "description": "Raptor/MetroX/FreeScan class laser lines, marker tracking, sprayed, experienced user",
        "weight": 0.2,
        "spec": _merge(
            _base(),
            {
                "capture": {
                    "distance_mm": U(200, 300),
                    "spacing_mm": LogU(0.03, 0.1),
                    "frames_per_session": IntU(60, 140),
                    "baseline_mm": U(60, 150),
                },
                "noise": {
                    "sigma_mm": LogU(0.005, 0.02),
                    "smooth_px": U(0, 0.6),
                    "mixed_pixel_p": U(0.02, 0.2),
                    "banding_mm": Maybe(0.5, LogU(0.003, 0.015)),
                    "banding_period_px": U(3, 12),
                    "corr_share": U(0.1, 0.4),
                },
                "surface": {
                    "spray_um": Maybe(0.8, U(8, 15)),
                    "markers_per_100cm2": Maybe(0.75, U(6, 25)),
                    "marker_radius_mm": Choice(((1.5, 0.4), (2.5, 0.2), (3.0, 0.4))),
                },
                "registration": {
                    "drift_deg": LogU(0.001, 0.005),
                    "drift_mm": LogU(0.001, 0.005),
                    "jump_p": Const(0.0),
                    "loop_closure": U(0.8, 0.98),
                    "scale_sigma": LogU(1e-4, 5e-4),
                },
                "fusion": {
                    "method": Choice.of(tsdf=0.6, poisson=0.3, tsdf_poisson=0.1),
                    "voxel_mult": U(0.8, 1.4),
                    "density_trim_q": Maybe(0.7, U(0.005, 0.05)),
                },
                "post": {
                    "hole_fill": Choice.of(none=0.6, small=0.4),
                    "smoothing": Choice.of(none=0.5, taubin=0.5),
                    "smooth_iters": IntU(0, 3),
                    "decimate": Maybe(0.4, U(0.3, 0.9), off=1.0),
                    "keep_islands": Bern(0.05),
                },
            },
        ),
    },
    # P4: mid-range SL on unprepared shiny metal. The stress case: dropout, spikes, bulging caps.
    "shiny_unprepared": {
        "label": "Shiny part, no spray",
        "description": "Mid-range structured light on unprepared shiny metal: dropout, spikes, ghosts",
        "weight": 0.15,
        "spec": _merge(
            _base(),
            {
                "capture": {"spacing_mm": LogU(0.1, 0.3)},
                "noise": {"sigma_mm": LogU(0.03, 0.1)},
                "surface": {
                    "shiny_frac": U(0.2, 0.6),
                    "shiny_face_p": U(0.3, 0.7),
                    "spike_p": U(0.2, 0.6),
                    "spike_mm": LogU(0.3, 3.0),
                    "saturation": U(0.3, 0.7),
                    "spray_um": Const(0.0),
                },
                "registration": {"jump_p": U(0.2, 0.5)},
                "fusion": {"method": Choice.of(tsdf_poisson=0.7, poisson=0.3), "density_trim_q": Const(0.0)},
                "post": {"hole_fill": Choice.of(all=0.7, small=0.3), "smooth_iters": IntU(4, 15)},
            },
        ),
    },
    # P5: phone depth / photogrammetry. The low end: coarse, smooth, scaled wrong.
    "phone": {
        "label": "Phone depth / photogrammetry",
        "description": "TrueDepth / LiDAR / photogrammetry: coarse, heavily smoothed, scale error",
        "weight": 0.1,
        "spec": _merge(
            _base(),
            {
                "capture": {
                    "distance_mm": U(200, 450),
                    "spacing_mm": LogU(0.4, 2.0),
                    "sensor_w_px": Const(640),
                    "sensor_h_px": Const(480),
                    "baseline_mm": Choice(((0.0, 0.5), (20.0, 0.5))),
                    "frames_per_session": IntU(40, 120),
                },
                "noise": {
                    "sigma_mm": LogU(0.2, 1.0),
                    "corr_px": U(3, 8),
                    "corr_share": U(0.6, 0.9),
                    "smooth_px": U(1, 2.5),
                },
                "visibility": {"projector_shadow": Bern(0.4)},
                "surface": {"dark_frac": U(0.2, 0.6), "markers_per_100cm2": Const(0.0)},
                "registration": {
                    "drift_deg": LogU(0.02, 0.1),
                    "drift_mm": LogU(0.02, 0.1),
                    "scale_sigma": LogU(1e-3, 2e-2),
                },
                "fusion": {
                    "method": Choice.of(tsdf_poisson=0.6, poisson=0.4),
                    "poisson_depth_offset": IntU(-2, 0),
                },
                "post": {
                    "smoothing": Choice.of(taubin=0.5, laplacian=0.5),
                    "smooth_iters": IntU(5, 25),
                    "hole_fill": Choice.of(all=0.6, small=0.4),
                },
            },
        ),
    },
}


# The operator, independent of the scanner: how many fusion voxels across the part's middle
# extent they accept before switching to a finer resolution setting (scanner apps offer
# point-distance or "small object" settings). It never goes finer than the profile's finest
# spacing: a part too small for the scanner still scans badly. The range is proposed, for
# calibration against real scans (M1). Drawn from a child RNG so the rest of a sample's draws
# are the same as before it existed.
OPERATOR: dict = {"voxels_across_min": U(6, 12)}


def list_profiles() -> list[dict]:
    rows = [
        {
            "id": "random",
            "label": "Random mix",
            "weight": 1.0,
            "description": "Each sample picks a profile by weight; 15% are drawn with widened ranges",
        }
    ]
    rows += [
        {"id": k, "label": p["label"], "description": p["description"], "weight": p["weight"]}
        for k, p in PROFILES.items()
    ]
    return rows


def sample_params(profile: str, rng: np.random.Generator) -> dict:
    """Draw one sample's full parameter tree. ``profile`` is a profile id or ``random``."""
    if profile == "random":
        ids = list(PROFILES)
        w = np.array([PROFILES[i]["weight"] for i in ids])
        chosen = ids[int(rng.choice(len(ids), p=w / w.sum()))]
    elif profile in PROFILES:
        chosen = profile
    else:
        raise KeyError(f"unknown profile {profile!r}; known: random, {', '.join(PROFILES)}")
    wild = bool(rng.random() < WILD_P) if profile == "random" else False
    params = sample_tree(PROFILES[chosen]["spec"], rng, WILD_WIDEN if wild else 1.0)
    params["profile"] = chosen
    params["wild"] = wild
    params["profiles_version"] = PROFILES_VERSION
    params["operator"] = sample_tree(OPERATOR, rng.spawn(1)[0])
    return cohere(params)


def finest_spacing(profile: str) -> float:
    """The finest capture spacing a profile's scanner offers (its range's low end)."""
    return float(PROFILES[profile]["spec"]["capture"]["spacing_mm"].lo)


def cohere(p: dict) -> dict:
    """Physical correlations a widened or independent draw can break (research §4.3)."""
    s, r, c, n = p["surface"], p["registration"], p["capture"], p["noise"]
    if s["spray_um"] > 0:  # spray makes everything matte and light grey
        s["shiny_frac"] *= 0.1
        s["shiny_face_p"] *= 0.1
        s["dark_frac"] *= 0.2
    if s["markers_per_100cm2"] > 0:  # marker tracking: no lost-tracking jumps, little drift
        r["jump_p"] = 0.0
        r["drift_deg"] = min(r["drift_deg"], 0.005)
        r["drift_mm"] = min(r["drift_mm"], 0.005)
    if c["mode"] == "turntable":
        p["base"]["support"] = "plane"
    if c["elev_max_deg"] <= c["elev_min_deg"]:
        c["elev_max_deg"] = c["elev_min_deg"] + 10
    if c["spacing_mm"] > 0.6:  # coarse captures: novices keep the default heavy smoothing
        n["smooth_px"] = max(n["smooth_px"], 1.0)
    return p
