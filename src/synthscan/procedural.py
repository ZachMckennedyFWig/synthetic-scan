"""Procedural parametric parts (build123d): ground truth we own outright.

Each generator draws a random but *machinable-looking* part (plates with hole
patterns, L-brackets, flanged bushings, standoffs, pocketed blocks), exports a
STEP, and records the design parameters (``<name>.params.json``). Those
parameters are the exact answers a reconstruction should recover ("4 x Ø6.6
holes on a 48 x 28 pattern, 3 mm fillets"), and unlike downloaded CAD they can
be released under any licence (docs/research/cad-sources.md, rank 1).

Fillets and chamfers are applied best-effort: OCCT occasionally refuses one on
an unlucky combination, and the part is kept without it (recorded in params).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

# Clearance-hole diameters for common metric screws (ISO 273 medium fit).
CLEARANCE = {"M3": 3.4, "M4": 4.5, "M5": 5.5, "M6": 6.6, "M8": 9.0}


def _r(rng, lo, hi, step=0.5):
    """Round to a designer-friendly step: real CAD dimensions are rarely 37.2941 mm."""
    return float(round(rng.uniform(lo, hi) / step) * step)


def _try(fn, part, note, params):
    try:
        return fn(part)
    except Exception as e:  # OCCT fillet/chamfer failures are not fatal
        params.setdefault("skipped", []).append(f"{note}: {type(e).__name__}")
        return part


def plate(rng):
    from build123d import Axis, Box, Cylinder, Pos, chamfer, fillet

    L, W, T = _r(rng, 30, 140), _r(rng, 20, 90), _r(rng, 2, 12)
    screw = rng.choice(list(CLEARANCE))
    d = CLEARANCE[screw]
    margin = max(d * 1.5, 5)
    nx, ny = int(rng.integers(2, 5)), int(rng.integers(1, 4))
    # Holes keep a web of material between them: fewer holes rather than overlapping ones
    # (three Ø9 holes at a 6.25 pitch merged into one lobed slot, PLAN §6 pilot). No extra
    # draws, so every other part from the same seed is unchanged.
    min_pitch = d + max(2.0, 0.5 * d)
    while nx > 1 and (L - 2 * margin) / (nx - 1) < min_pitch:
        nx -= 1
    while ny > 1 and (W - 2 * margin) / (ny - 1) < min_pitch:
        ny -= 1
    px = (L - 2 * margin) / max(nx - 1, 1)
    py = (W - 2 * margin) / max(ny - 1, 1) if ny > 1 else 0
    corner_r = _r(rng, 1, min(W, L) / 5)
    p = {
        "kind": "plate",
        "length": L,
        "width": W,
        "thickness": T,
        "hole_d": d,
        "screw": screw,
        "holes": [nx, ny],
        "pitch": [round(px, 3), round(py, 3)],
        "corner_fillet": corner_r,
    }
    part = Box(L, W, T)
    part = _try(lambda s: fillet(s.edges().filter_by(Axis.Z), corner_r), part, "corner fillet", p)
    for i in range(nx):
        for j in range(ny):
            x = -L / 2 + margin + i * px
            y = (-W / 2 + margin + j * py) if ny > 1 else 0
            part -= Pos(x, y, 0) * Cylinder(d / 2, T * 2)
    if rng.random() < 0.5:
        c = _r(rng, 0.3, min(1.5, T / 3), 0.1)
        p["top_chamfer"] = c
        part = _try(lambda s: chamfer(s.edges().group_by(Axis.Z)[-1], c), part, "top chamfer", p)
    return part, p


def l_bracket(rng):
    from build123d import Axis, Box, Cylinder, Pos, Rot, fillet

    W, L1, L2, T = _r(rng, 15, 60), _r(rng, 20, 80), _r(rng, 20, 80), _r(rng, 2, 8)
    d = CLEARANCE[rng.choice(list(CLEARANCE))]
    p = {"kind": "l_bracket", "width": W, "leg1": L1, "leg2": L2, "thickness": T, "hole_d": d}
    base = Pos(L1 / 2, 0, T / 2) * Box(L1, W, T)
    wall = Pos(T / 2, 0, L2 / 2) * Box(T, W, L2)
    part = base + wall
    r_in = _r(rng, 1, max(1.5, T), 0.5)
    p["inner_fillet"] = r_in
    inner = part.edges().filter_by(Axis.Y).group_by(Axis.X)[1].sort_by(Axis.Z)[:1]
    part = _try(lambda s: fillet(inner, r_in), part, "inner fillet", p)
    part -= Pos(L1 * 0.65, 0, 0) * Cylinder(d / 2, T * 4)
    part -= Pos(0, 0, L2 * 0.65) * Rot(0, 90, 0) * Cylinder(d / 2, T * 4)
    if rng.random() < 0.5:  # a gusset, as on stamped brackets
        g = min(L1, L2) * 0.45
        from build123d import Plane, Polyline, extrude, make_face

        tri = make_face(Polyline((T, T), (T + g, T), (T, T + g), close=True))
        gus = extrude(Plane.XZ.offset(-W * 0.1) * tri, amount=T * 0.8, both=False)
        part = _try(lambda s: s + gus, part, "gusset", p)
        p["gusset"] = round(g, 3)
    return part, p


def bushing(rng):
    from build123d import Axis, Cylinder, Pos, chamfer

    D, H = _r(rng, 10, 60), _r(rng, 8, 50)
    bore = _r(rng, D * 0.25, D * 0.65)
    fl_D, fl_H = _r(rng, D * 1.2, D * 1.8), _r(rng, 1.5, max(2.0, H * 0.3))
    p = {"kind": "flanged_bushing", "od": D, "height": H, "bore": bore, "flange_od": fl_D, "flange_h": fl_H}
    part = Pos(0, 0, H / 2) * Cylinder(D / 2, H) + Pos(0, 0, fl_H / 2) * Cylinder(fl_D / 2, fl_H)
    part -= Pos(0, 0, H / 2) * Cylinder(bore / 2, H * 2)
    if rng.random() < 0.6:
        c = _r(rng, 0.3, 1.0, 0.1)
        p["edge_chamfer"] = c
        part = _try(lambda s: chamfer(s.edges().group_by(Axis.Z)[-1], c), part, "chamfer", p)
    if rng.random() < 0.5:
        n = int(rng.integers(3, 7))
        hd = CLEARANCE[rng.choice(["M3", "M4", "M5"])]
        pcd = (fl_D + D) / 2
        if (fl_D - D) / 2 > hd * 1.4:
            for k in range(n):
                a = 2 * math.pi * k / n
                part -= Pos(pcd / 2 * math.cos(a), pcd / 2 * math.sin(a), 0) * Cylinder(hd / 2, fl_H * 3)
            p["flange_holes"] = {"n": n, "d": hd, "pcd": round(pcd, 3)}
    return part, p


def standoff(rng):
    from build123d import Cylinder, Pos, RegularPolygon, extrude

    af = _r(rng, 5, 17)  # across flats
    H = _r(rng, 5, 40)
    hole = _r(rng, af * 0.3, af * 0.55, 0.1)
    p = {"kind": "hex_standoff", "across_flats": af, "height": H, "hole_d": hole}
    hexa = extrude(RegularPolygon(af / math.sqrt(3), 6, major_radius=True), amount=H)
    part = hexa - Pos(0, 0, H / 2) * Cylinder(hole / 2, H * 2)
    return part, p


def pocket_block(rng):
    from build123d import Axis, Box, Cylinder, Pos, fillet

    L, W, H = _r(rng, 25, 100), _r(rng, 20, 80), _r(rng, 10, 50)
    pl, pw, pd = _r(rng, L * 0.3, L * 0.7), _r(rng, W * 0.3, W * 0.7), _r(rng, H * 0.2, H * 0.7)
    p = {"kind": "pocket_block", "length": L, "width": W, "height": H, "pocket": [pl, pw, pd]}
    part = Pos(0, 0, H / 2) * Box(L, W, H)
    pocket = Pos(0, 0, H - pd / 2 + 0.01) * Box(pl, pw, pd + 0.02)
    pr = _r(rng, 0.5, min(pl, pw) / 4)
    pocket = _try(lambda s: fillet(s.edges().filter_by(Axis.Z), pr), pocket, "pocket corner fillet", p)
    p["pocket_corner_r"] = pr
    part -= pocket
    if rng.random() < 0.7:
        cb_d, d = _r(rng, 8, 11), 5.5
        for sx in (-1, 1):
            x = sx * (L / 2 - max(cb_d, 6))
            if abs(x) > pl / 2 + cb_d / 2:
                part -= Pos(x, 0, H / 2) * Cylinder(d / 2, H * 2)
                part -= Pos(x, 0, H - 2.75) * Cylinder(cb_d / 2, 5.5 + 0.02)
        p["counterbores"] = {"d": d, "cb_d": cb_d, "cb_depth": 5.5}
    return part, p


GENERATORS = {
    "plate": plate,
    "l_bracket": l_bracket,
    "bushing": bushing,
    "standoff": standoff,
    "pocket_block": pocket_block,
}


def generate(out_dir: Path, n: int, seed: int = 0, kinds: list[str] | None = None) -> list[Path]:
    """Write ``n`` random parts as STEP + params JSON into ``out_dir``. Returns the STEP paths."""
    from build123d import export_step

    out_dir.mkdir(parents=True, exist_ok=True)
    kinds = kinds or list(GENERATORS)
    paths = []
    for i in range(n):
        rng = np.random.default_rng([seed, i])
        kind = kinds[i % len(kinds)]
        part, params = GENERATORS[kind](rng)
        name = f"proc-{kind}-{seed}-{i:04d}"
        path = out_dir / f"{name}.step"
        export_step(part, str(path))
        params |= {
            "generator": "synthscan.procedural",
            "seed": [seed, i],
            "volume_mm3": round(part.volume, 3),
        }
        (out_dir / f"{name}.params.json").write_text(json.dumps(params, indent=1))
        paths.append(path)
    return paths
