import numpy as np
import pytest

from synthscan.profiles import PROFILES, cohere, sample_params
from synthscan.randomness import Bern, Choice, LogU, Maybe, U, sample_rng, sample_tree


def test_sample_rng_is_stable_and_independent_of_order():
    a = sample_rng(1, "abc", 3).random(4)
    sample_rng(1, "zzz", 0).random(100)  # other samples drawn in between change nothing
    b = sample_rng(1, "abc", 3).random(4)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, sample_rng(1, "abc", 4).random(4))
    assert not np.array_equal(a, sample_rng(2, "abc", 3).random(4))


def test_distributions_stay_in_range_and_widen():
    rng = np.random.default_rng(0)
    xs = [U(1, 2).sample(rng) for _ in range(500)]
    assert 1 <= min(xs) and max(xs) <= 2
    wide = [U(1, 2).sample(rng, widen=3) for _ in range(500)]
    assert min(wide) < 1 and max(wide) > 2
    ls = [LogU(0.01, 1).sample(rng) for _ in range(500)]
    assert 0.01 <= min(ls) and max(ls) <= 1
    assert all(U(0, 1).sample(rng, widen=10) >= 0 for _ in range(200))  # floor holds


def test_maybe_and_bern_rates():
    rng = np.random.default_rng(1)
    on = sum(Maybe(0.3, U(1, 2)).sample(rng) > 0 for _ in range(4000)) / 4000
    assert 0.26 < on < 0.34
    assert 0.65 < sum(Bern(0.7).sample(rng) for _ in range(4000)) / 4000 < 0.75
    picks = [Choice.of(a=9, b=1).sample(rng) for _ in range(2000)]
    assert 0.85 < picks.count("a") / 2000 < 0.95


def test_sample_tree_keeps_shape():
    spec = {"a": U(0, 1), "b": {"c": Choice.of(x=1), "d": 5}}
    out = sample_tree(spec, np.random.default_rng(0))
    assert set(out) == {"a", "b"} and out["b"]["c"] == "x" and out["b"]["d"] == 5


@pytest.mark.parametrize("profile", ["random", *PROFILES])
def test_every_profile_samples_a_complete_tree(profile):
    ref = sample_params("budget_ir_handheld", np.random.default_rng(0))
    for seed in range(20):
        p = sample_params(profile, np.random.default_rng(seed))
        for group in (
            "capture",
            "noise",
            "visibility",
            "surface",
            "registration",
            "base",
            "fusion",
            "post",
            "output",
        ):
            assert set(p[group]) == set(ref[group]), f"{profile}.{group} keys differ from the base schema"
        assert p["capture"]["spacing_mm"] > 0 and p["noise"]["sigma_mm"] > 0
        assert p["capture"]["elev_max_deg"] > p["capture"]["elev_min_deg"]
        assert p["fusion"]["method"] in ("tsdf", "tsdf_poisson", "poisson")


def test_cohere_enforces_physical_correlations():
    p = sample_params("budget_ir_handheld", np.random.default_rng(0))
    p["surface"] |= {"spray_um": 12.0, "shiny_frac": 0.5, "markers_per_100cm2": 10.0}
    p["registration"] |= {"jump_p": 0.4, "drift_mm": 0.05}
    p = cohere(p)
    assert p["surface"]["shiny_frac"] == pytest.approx(0.05)  # spray kills shine
    assert p["registration"]["jump_p"] == 0  # markers: no lost-tracking jumps
    assert p["registration"]["drift_mm"] <= 0.005


def test_random_profile_mixes_profiles():
    seen = {sample_params("random", np.random.default_rng(s))["profile"] for s in range(200)}
    assert seen == set(PROFILES)
