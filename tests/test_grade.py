"""The bench grader: a perfect model must grade as perfect whatever frame the session ended in."""

import json
import shutil

import numpy as np
import open3d as o3d
import trimesh
from conftest import FAST, rng

from synthscan.grade import grade_run
from synthscan.parts import load_part
from synthscan.pipeline import generate_sample
from synthscan.scanner import random_rotation


def _step_in_frame(src, dst, T):
    """Write the STEP at ``src`` moved by the rigid 4x4 ``T`` to ``dst``."""
    from build123d import Shape, export_step, import_step
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf

    shape = import_step(str(src))
    u, _, vt = np.linalg.svd(T[:3, :3])  # OCCT refuses a rotation off orthogonal by float error
    R = u @ vt
    t = gp_Trsf()
    t.SetValues(*R[0], T[0, 3], *R[1], T[1, 3], *R[2], T[2, 3])
    export_step(Shape.cast(BRepBuilderAPI_Transform(shape.wrapped, t, True).Shape()), str(dst))


def _job(run, key, task_id, scan_stl, T_session=None, model_step=None, cad_to_scan=None):
    d = run / "jobs" / key
    (d / "out").mkdir(parents=True)
    shutil.copyfile(scan_stl, d / "scan.stl")
    T = np.eye(4) if T_session is None else T_session
    v = np.asarray(trimesh.load(scan_stl, process=True).vertices)
    pc = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(v @ T[:3, :3].T + T[:3, 3]))
    o3d.io.write_point_cloud(str(d / "out" / "scan-final-frame.ply"), pc)
    if model_step is not None:
        _step_in_frame(model_step, d / "out" / "final.step", T @ cad_to_scan)
    (d / "result.json").write_text(
        json.dumps({"task": task_id, "model": "fake", "status": "finished", "run": {}})
    )


def test_perfect_model_grades_perfect_in_any_session_frame(step_plate, tmp_path):
    part = load_part(step_plate)
    meta = generate_sample(part, 0, "laser_markers", 3, tmp_path / "sample", overrides=FAST)
    scan_to_cad = np.asarray(meta["transforms"]["scan_to_cad"])
    cad_to_scan = np.linalg.inv(scan_to_cad)

    export = tmp_path / "export"
    (export / "gt").mkdir(parents=True)
    trimesh.Trimesh(part.vertices, part.faces).export(export / "gt" / "p.stl")
    shutil.copyfile(step_plate, export / "gt" / "p.step")
    task = {
        "id": "t0",
        "scan": "scans/t0.stl",
        "units": "mm",
        "hidden": {
            "gt": "gt/p.stl",
            "gt_step": "gt/p.step",
            "scan_to_cad": meta["transforms"]["scan_to_cad"],
            "profile": "laser_markers",
            "artifacts": meta["artifacts"],
            "metrics": meta["metrics"],
        },
    }
    (export / "tasks.jsonl").write_text(json.dumps(task) + "\n")

    run = tmp_path / "run"
    scan = tmp_path / "sample" / "scan.stl"
    A = np.eye(4)
    A[:3, :3] = random_rotation(rng(4))
    A[:3, 3] = [12.0, -40.0, 7.5]  # as if the model had aligned the scan in ScanRuler
    _job(run, "same", "t0", scan, None, step_plate, cad_to_scan)
    _job(run, "aligned", "t0", scan, A, step_plate, cad_to_scan)
    _job(run, "empty", "t0", scan)
    # A block with the plate's outline and no holes, fillets or chamfers: close in distance,
    # wrong in design. Must fail on faces and bores.
    from build123d import Box, Pos, export_step

    lo, hi = part.vertices.min(0), part.vertices.max(0)
    block = tmp_path / "block.step"
    export_step(Pos(*((lo + hi) / 2)) * Box(*(hi - lo)), str(block))
    _job(run, "block", "t0", scan, None, block, cad_to_scan)

    rows, summary = grade_run(export / "tasks.jsonl", run)
    by = {r["key"]: r for r in rows}
    for key in ("same", "aligned"):
        r = by[key]
        assert r["graded"] and r["success"], r
        assert r["frame_rms_mm"] < 1e-3
        assert r["posed"]["chamfer_mm"] < 0.01
        assert r["bores"]["gt"] > 0
        assert r["bores"]["within_tol"] == r["bores"]["gt"] == r["bores"]["model"]
        assert r["faces"]["agreement"] > 0.97, r["faces"]
    assert abs(by["same"]["posed"]["chamfer_mm"] - by["aligned"]["posed"]["chamfer_mm"]) < 1e-3
    assert not by["empty"]["graded"] and by["empty"]["why"] == "no body to export"
    blk = by["block"]
    assert blk["graded"] and not blk["success"]
    assert blk["faces"]["agreement"] < 0.9 and blk["bores"]["model"] == 0
    assert summary["models"]["fake"]["success"] == "2/4"
    assert (run / "grades.jsonl").exists() and (run / "grades-summary.json").exists()
