"""Seeded, declarative parameter distributions.

Every number that shapes a synthetic scan is drawn from one of these, never
hard-coded in the simulation. Profiles (``profiles.py``) are just nested dicts
of distributions; ``sample_tree`` turns one into a nested dict of plain values
that is stored verbatim in the sample's ``meta.json``. That record is what lets
us later ask "which artifacts made the LLM fail?" — and replay any sample.

Reproducibility: a sample's RNG is derived from ``(global_seed, part_hash,
sample_index)`` with ``numpy.random.SeedSequence``, so results do not depend on
worker scheduling or on how many other parts are in the batch.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any

import numpy as np


def sample_rng(global_seed: int, part_hash: str, sample_index: int) -> np.random.Generator:
    """The RNG for one sample. Stable across runs, machines and worker counts."""
    part_key = int(hashlib.sha1(part_hash.encode()).hexdigest()[:8], 16)
    return np.random.default_rng(np.random.SeedSequence([global_seed & 0xFFFFFFFF, part_key, sample_index]))


class Dist:
    """A distribution over one parameter. ``widen`` stretches its range (see ``Wild``)."""

    def sample(self, rng: np.random.Generator, widen: float = 1.0) -> Any:  # pragma: no cover - interface
        raise NotImplementedError

    def describe(self) -> str:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass(frozen=True)
class Const(Dist):
    value: Any

    def sample(self, rng, widen=1.0):
        return self.value

    def describe(self):
        return repr(self.value)


@dataclass(frozen=True)
class U(Dist):
    """Uniform on [lo, hi]. Widening grows the interval about its centre, clamped at ``floor``."""

    lo: float
    hi: float
    floor: float | None = 0.0

    def sample(self, rng, widen=1.0):
        mid, half = (self.lo + self.hi) / 2, (self.hi - self.lo) / 2 * widen
        lo, hi = mid - half, mid + half
        if self.floor is not None:
            lo = max(lo, self.floor)
        return float(rng.uniform(lo, max(lo, hi)))

    def describe(self):
        return f"U({self.lo:g}, {self.hi:g})"


@dataclass(frozen=True)
class LogU(Dist):
    """Log-uniform on [lo, hi] (both > 0): for scales that span orders of magnitude."""

    lo: float
    hi: float

    def sample(self, rng, widen=1.0):
        a, b = math.log(self.lo), math.log(self.hi)
        mid, half = (a + b) / 2, (b - a) / 2 * widen
        return float(math.exp(rng.uniform(mid - half, mid + half)))

    def describe(self):
        return f"LogU({self.lo:g}, {self.hi:g})"


@dataclass(frozen=True)
class IntU(Dist):
    """Uniform integer on [lo, hi] inclusive."""

    lo: int
    hi: int

    def sample(self, rng, widen=1.0):
        mid, half = (self.lo + self.hi) / 2, (self.hi - self.lo) / 2 * widen
        lo, hi = max(0, int(round(mid - half))), int(round(mid + half))
        return int(rng.integers(lo, max(lo, hi) + 1))

    def describe(self):
        return f"IntU({self.lo}, {self.hi})"


@dataclass(frozen=True)
class Choice(Dist):
    """Weighted categorical. ``options`` maps value -> weight."""

    options: tuple[tuple[Any, float], ...]

    @staticmethod
    def of(**weights: float) -> Choice:
        return Choice(tuple(weights.items()))

    def sample(self, rng, widen=1.0):
        values = [v for v, _ in self.options]
        w = np.array([w for _, w in self.options], dtype=float)
        # Widening flattens the weights toward uniform, so rare options get tried more.
        w = w ** (1.0 / max(widen, 1e-6))
        return values[int(rng.choice(len(values), p=w / w.sum()))]

    def describe(self):
        return "Choice(" + ", ".join(f"{v}:{w:g}" for v, w in self.options) + ")"


@dataclass(frozen=True)
class Bern(Dist):
    """True with probability ``p``. Widening pulls ``p`` toward 0.5."""

    p: float

    def sample(self, rng, widen=1.0):
        p = 0.5 + (self.p - 0.5) / max(widen, 1.0)
        return bool(rng.random() < p)

    def describe(self):
        return f"Bern({self.p:g})"


@dataclass(frozen=True)
class Maybe(Dist):
    """With probability ``p`` draw from ``inner``, otherwise ``off`` (usually 0 = artifact disabled)."""

    p: float
    inner: Dist
    off: Any = 0.0

    def sample(self, rng, widen=1.0):
        p = 0.5 + (self.p - 0.5) / max(widen, 1.0)
        return self.inner.sample(rng, widen) if rng.random() < p else self.off

    def describe(self):
        return f"Maybe({self.p:g}, {self.inner.describe()}, off={self.off!r})"


def sample_tree(spec: Any, rng: np.random.Generator, widen: float = 1.0) -> Any:
    """Sample every ``Dist`` in a nested dict/list, keeping the shape. Keys are visited in sorted
    order so adding a parameter to a profile never reshuffles the draws of unrelated keys more
    than necessary (it still shifts later ones; profiles are versioned for that reason)."""
    if isinstance(spec, Dist):
        return spec.sample(rng, widen)
    if isinstance(spec, dict):
        return {k: sample_tree(spec[k], rng, widen) for k in sorted(spec)}
    if isinstance(spec, (list, tuple)):
        return [sample_tree(v, rng, widen) for v in spec]
    return spec


def describe_tree(spec: Any) -> Any:
    """Human-readable form of a spec, for ``synthscan profiles --show`` and the docs."""
    if isinstance(spec, Dist):
        return spec.describe()
    if isinstance(spec, dict):
        return {k: describe_tree(v) for k, v in spec.items()}
    return spec
