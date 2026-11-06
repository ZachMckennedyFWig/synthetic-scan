"""Loading ground-truth parts.

A *part* is the truth every scan is measured against: a triangle mesh in the
part's own CAD frame (millimetres), plus — when the source is a B-rep (STEP) —
a per-triangle B-rep face id and an analytic label for every face (plane,
cylinder radius and axis, ...). Those labels are what a reconstruction is
ultimately graded on ("is the bore 8.00 mm?"), so they are extracted once here
and stored in ``part.json`` next to ``gt.stl``.

Mesh inputs (STL/OBJ/PLY/3MF/GLB/OFF) have no B-rep. For them, ``face_ids``
groups coplanar triangles (trimesh facets), which is good enough to assign
per-face surface finish in the simulator but carries no analytic labels.

Units: STEP is read in file units (mm in practice). Mesh formats carry no
units; we assume mm, like every slicer and like ScanRuler does.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import trimesh

STEP_EXTS = {".step", ".stp"}
MESH_EXTS = {".stl", ".obj", ".ply", ".3mf", ".glb", ".off"}
SUPPORTED_EXTS = STEP_EXTS | MESH_EXTS


@dataclass
class Part:
    """A ground-truth solid, in its CAD frame, in mm."""

    part_id: str
    name: str
    source: str  # file name it came from
    sha1: str  # content hash of the source file; drives splits and seeds
    vertices: np.ndarray  # (n, 3) float64
    faces: np.ndarray  # (m, 3) int64
    face_ids: np.ndarray  # (m,) int32: B-rep face (STEP) or coplanar facet group (mesh)
    features: list[dict] = field(default_factory=list)  # analytic face labels (STEP only)
    notes: list[str] = field(default_factory=list)  # anything the loader had to repair

    @property
    def mesh(self) -> trimesh.Trimesh:
        return trimesh.Trimesh(self.vertices, self.faces, process=False)

    def summary(self) -> dict:
        m = self.mesh
        lo, hi = m.bounds
        return {
            "part_id": self.part_id,
            "name": self.name,
            "source": self.source,
            "sha1": self.sha1,
            "n_vertices": int(len(self.vertices)),
            "n_faces": int(len(self.faces)),
            "n_brep_faces": int(self.face_ids.max() + 1) if len(self.face_ids) else 0,
            "bbox_min": lo.tolist(),
            "bbox_max": hi.tolist(),
            "extents_mm": (hi - lo).tolist(),
            "area_mm2": float(m.area),
            "volume_mm3": float(m.volume) if m.is_watertight else None,
            "watertight": bool(m.is_watertight),
            "features": self.features,
            "notes": self.notes,
        }


def file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def part_id_for(path: Path, sha1: str) -> str:
    """``<slug of the file stem>-<8 hex of content>``: readable, and unique per content."""
    slug = re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")[:40] or "part"
    return f"{slug}-{sha1[:8]}"


def load_part(path: str | Path) -> Part:
    """Load any supported file as a ``Part``. Raises ``ValueError`` for unusable input."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise ValueError(f"unsupported format {ext!r}")
    sha1 = file_sha1(path)
    if ext in STEP_EXTS:
        v, f, fid, feats, notes = _load_step(path)
    else:
        v, f, fid, notes = _load_mesh(path)
        feats = []
    if len(f) == 0:
        raise ValueError("no triangles")
    return Part(part_id_for(path, sha1), path.stem, path.name, sha1, v, f, fid, feats, notes)


# --------------------------------------------------------------------------- STEP


def _load_step(path: Path):
    """Tessellate a STEP file with OCCT, keeping the triangle -> B-rep face map and face labels."""
    from build123d import import_step
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRepTools import BRepTools
    from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane, GeomAbs_Sphere, GeomAbs_Torus
    from OCP.TopAbs import TopAbs_REVERSED
    from OCP.TopLoc import TopLoc_Location

    shape = import_step(str(path))
    bb = shape.bounding_box()
    diag = float(np.linalg.norm([bb.size.X, bb.size.Y, bb.size.Z]))
    # Chord error relative to part size: fine enough that tessellation error is far below any
    # scanner's noise (1e-4 of the diagonal is 10 um on a 100 mm part), floored to keep tiny
    # parts from exploding in triangle count.
    lin = max(2e-3, 1e-4 * diag)
    BRepTools.Clean_s(shape.wrapped)
    BRepMesh_IncrementalMesh(shape.wrapped, lin, False, 0.1, True)

    verts, tris, fids, feats = [], [], [], []
    base = 0
    for i, face in enumerate(shape.faces()):
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face.wrapped, loc)
        if tri is None:
            continue
        T = loc.Transformation()
        n_nodes = tri.NbNodes()
        verts.append(np.array([tri.Node(k).Transformed(T).Coord() for k in range(1, n_nodes + 1)]))
        idx = np.array([tri.Triangle(k).Get() for k in range(1, tri.NbTriangles() + 1)], dtype=np.int64) - 1
        if face.wrapped.Orientation() == TopAbs_REVERSED:
            idx = idx[:, [0, 2, 1]]
        tris.append(idx + base)
        fids.append(np.full(len(idx), i, dtype=np.int32))
        base += n_nodes

        s = BRepAdaptor_Surface(face.wrapped)
        t = s.GetType()
        lab: dict = {"face": i, "type": face.geom_type.name.lower(), "area_mm2": float(face.area)}
        if t == GeomAbs_Plane:
            p = s.Plane()
            lab |= {"origin": p.Location().Coord(), "normal": p.Axis().Direction().Coord()}
        elif t == GeomAbs_Cylinder:
            c = s.Cylinder()
            umin, umax, _, _ = BRepTools.UVBounds_s(face.wrapped)
            lab |= {
                "radius": c.Radius(),
                "origin": c.Location().Coord(),
                "axis": c.Axis().Direction().Coord(),
                # Angle the face wraps round its axis (u is the angle on a cylinder): a bore is
                # 360 deg over one or more faces, an internal fillet a quarter turn.
                "span_deg": float(min(360.0, np.degrees(umax - umin))),
            }
            lab["concave"] = _cylinder_is_concave(face, c)
        elif t == GeomAbs_Cone:
            c = s.Cone()
            lab |= {
                "ref_radius": c.RefRadius(),
                "half_angle_rad": c.SemiAngle(),
                "apex": c.Apex().Coord(),
                "axis": c.Axis().Direction().Coord(),
            }
        elif t == GeomAbs_Sphere:
            c = s.Sphere()
            lab |= {"radius": c.Radius(), "center": c.Location().Coord()}
        elif t == GeomAbs_Torus:
            c = s.Torus()
            lab |= {
                "major_radius": c.MajorRadius(),
                "minor_radius": c.MinorRadius(),
                "center": c.Location().Coord(),
                "axis": c.Axis().Direction().Coord(),
            }
        feats.append(_jsonable(lab))

    if not tris:
        raise ValueError("STEP contains no faces with a triangulation")
    v = np.concatenate(verts)
    f = np.concatenate(tris)
    fid = np.concatenate(fids)
    # Adjacent B-rep faces share their edge discretisation, so welding gives a closed mesh.
    m = trimesh.Trimesh(v, f, process=False)
    m.merge_vertices()
    keep = m.nondegenerate_faces()
    notes = (
        [] if m.is_watertight else ["tessellation is not watertight; signed distances fall back to unsigned"]
    )
    return np.asarray(m.vertices), np.asarray(m.faces)[keep], fid[keep], feats, notes


def _cylinder_is_concave(face, cyl) -> bool:
    """A hole (normal points at the axis) vs a boss or fillet (normal points away)."""
    try:
        c = face.center()
        n = face.normal_at(c)
        o = np.array(cyl.Location().Coord())
        a = np.array(cyl.Axis().Direction().Coord())
        p = np.array([c.X, c.Y, c.Z])
        radial = (p - o) - np.dot(p - o, a) * a
        return bool(np.dot(np.array([n.X, n.Y, n.Z]), radial) < 0)
    except Exception:  # OCCT can refuse normal_at on degenerate faces; the label is optional
        return False


def _jsonable(d: dict) -> dict:
    return {k: (list(map(float, v)) if isinstance(v, tuple) else v) for k, v in d.items()}


# --------------------------------------------------------------------------- meshes


def _load_mesh(path: Path):
    loaded = trimesh.load(str(path), force="mesh", process=True)
    if not isinstance(loaded, trimesh.Trimesh) or len(loaded.faces) == 0:
        raise ValueError("file has no triangle mesh")
    m = loaded
    notes = []
    m.merge_vertices()
    m.update_faces(m.nondegenerate_faces())
    m.update_faces(m.unique_faces())
    m.remove_unreferenced_vertices()
    if not m.is_watertight:
        trimesh.repair.fill_holes(m)
        notes.append("mesh was not watertight" + ("; small holes filled" if m.is_watertight else ""))
    if m.is_watertight and m.volume < 0:
        m.invert()
        notes.append("mesh was inside-out; inverted")
    # Coplanar facets stand in for B-rep faces (used for per-face surface finish).
    fid = np.full(len(m.faces), -1, dtype=np.int32)
    for i, group in enumerate(m.facets):
        fid[group] = i
    lone = fid < 0
    fid[lone] = len(m.facets) + np.arange(lone.sum(), dtype=np.int32)
    return np.asarray(m.vertices, dtype=np.float64), np.asarray(m.faces, dtype=np.int64), fid, notes
