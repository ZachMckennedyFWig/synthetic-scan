"""``synthscan`` command line.

synthscan doctor                         check the environment
synthscan profiles [--show ID]           list scanner profiles / show one's distributions
synthscan procedural OUT -n 50           write random parametric parts (STEP + params)
synthscan run INPUTS... -d NAME          bulk-generate a dataset from files/folders
synthscan reindex NAME                   rebuild a dataset's manifest from its sample folders
synthscan export NAME OUT [--split test] flat folder of scans + tasks.jsonl for an eval harness
synthscan serve                          Scan Lab UI + API on http://127.0.0.1:8849
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path


def _iter_inputs(paths: list[str]):
    from .parts import SUPPORTED_EXTS

    for p in map(Path, paths):
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS:
                    yield f
        elif p.is_file():
            yield p
        else:
            print(f"warning: {p} does not exist", file=sys.stderr)


def cmd_doctor(_a) -> int:
    import numpy
    import open3d
    import trimesh

    from . import __version__
    from .batch import default_workers
    from .dataset import data_dir

    print(f"synthscan {__version__}   python {sys.version.split()[0]}")
    print(f"numpy {numpy.__version__}   open3d {open3d.__version__}   trimesh {trimesh.__version__}")
    try:
        import build123d

        print(f"build123d {build123d.__version__} (STEP support)")
    except Exception as e:  # pragma: no cover
        print(f"STEP support missing: {e}")
    print(f"cpus {os.cpu_count()}   default workers {default_workers()}   data dir {data_dir()}")
    ui = Path(__file__).resolve().parents[2] / "ui" / "dist" / "index.html"
    print(f"ui build {'present' if ui.exists() else 'MISSING (cd ui && npm ci && npm run build)'}")
    return 0


def cmd_profiles(a) -> int:
    from .profiles import PROFILES, list_profiles
    from .randomness import describe_tree

    if a.show:
        if a.show not in PROFILES:
            print(f"unknown profile {a.show!r}", file=sys.stderr)
            return 2
        print(json.dumps(describe_tree(PROFILES[a.show]["spec"]), indent=1))
        return 0
    for p in list_profiles():
        print(f"{p['id']:22s} w={p['weight']:<5g} {p['description']}")
    return 0


def cmd_procedural(a) -> int:
    from .procedural import generate

    paths = generate(Path(a.out), a.n, a.seed, a.kinds.split(",") if a.kinds else None)
    print(f"wrote {len(paths)} parts to {a.out}")
    return 0


def cmd_run(a) -> int:
    from .batch import JobSpec, run_job
    from .dataset import Dataset

    ds = Dataset.create(a.dataset)
    added, skipped = 0, 0
    names = []
    for f in _iter_inputs(a.inputs):
        sidecar = f.with_name(f.stem + ".params.json")
        if sidecar.exists():
            ds.add_input(sidecar)
        name, reason = ds.add_input(f, link=True)
        if name:
            added += 1
            names.append(name)
        else:
            skipped += 1
            if reason == "already in dataset":
                names.append(f.name)
    print(f"dataset {ds.name}: {added} inputs added, {skipped} skipped (already present or unsupported)")
    spec = JobSpec(
        dataset=ds.name,
        profile=a.profile,
        samples_per_part=a.samples,
        seed=a.seed,
        inputs=names or None,
        save_points=a.save_points,
        workers=a.workers,
    )
    last = [0.0]

    def progress(p):
        now = time.time()
        if now - last[0] < 1 and p.done + p.failed < p.total:
            return
        last[0] = now
        eta = p.eta_s()
        print(
            f"\r  {p.done + p.failed}/{p.total}  ok {p.done}  failed {p.failed}  eta {eta / 60:.1f} min"
            if eta
            else f"\r  {p.done + p.failed}/{p.total}",
            end="",
            flush=True,
        )

    t = time.time()
    prog = run_job(spec, progress)
    print(
        f"\ndone in {time.time() - t:.0f} s: {prog.done} samples ({prog.skipped} already existed), "
        f"{prog.failed} failed"
    )
    for e in prog.errors[:20]:
        print(f"  ! {e['input']} {e['sample'] or ''}: {e['error']}")
    return 0 if prog.failed == 0 else 1


def cmd_reindex(a) -> int:
    from .dataset import Dataset

    print(f"{Dataset(a.dataset).reindex()} samples indexed")
    return 0


def cmd_export(a) -> int:
    """A flat folder an evaluation harness (e.g. driving ScanRuler) can consume.

    ``scans/<id>.stl`` are what the model sees. ``tasks.jsonl`` carries, per task, the scan
    path and the *hidden* answers (GT path, transforms, design params) — the harness must not
    show those to the model."""
    from .dataset import Dataset

    ds = Dataset(a.dataset)
    out = Path(a.out)
    (out / "scans").mkdir(parents=True, exist_ok=True)
    (out / "gt").mkdir(parents=True, exist_ok=True)
    n = 0
    with open(out / "tasks.jsonl", "w") as f:
        for row in ds.samples():
            if a.split and row["split"] != a.split:
                continue
            sdir = ds.sample_dir(row["id"])
            meta = json.loads((sdir / "meta.json").read_text())
            shutil.copyfile(sdir / "scan.stl", out / "scans" / f"{row['id']}.stl")
            gt = out / "gt" / f"{row['part_id']}.stl"
            if not gt.exists():
                shutil.copyfile(ds.root / "parts" / row["part_id"] / "gt.stl", gt)
            part = json.loads((ds.root / "parts" / row["part_id"] / "part.json").read_text())
            # The source STEP too, so a grader labels GT and a model's STEP with the same code.
            gt_step = None
            src = ds.root / "inputs" / part.get("input", "")
            if part.get("input") and src.suffix.lower() in (".step", ".stp"):
                gt_step = f"gt/{row['part_id']}{src.suffix.lower()}"
                if not (out / gt_step).exists():
                    shutil.copyfile(src, out / gt_step)
            f.write(
                json.dumps(
                    {
                        "id": row["id"],
                        "scan": f"scans/{row['id']}.stl",
                        "units": "mm",
                        "hidden": {
                            "gt": f"gt/{row['part_id']}.stl",
                            "gt_step": gt_step,
                            "scan_to_cad": meta["transforms"]["scan_to_cad"],
                            "features": part.get("features", []),
                            "design_params": part.get("design_params"),
                            "profile": row["profile"],
                            "artifacts": row["artifacts"],
                            "metrics": row["metrics"],
                        },
                    }
                )
                + "\n"
            )
            n += 1
    print(f"exported {n} tasks to {out}")
    return 0


def cmd_grade(a) -> int:
    """Grade every job of a bench run; writes grades.jsonl and grades-summary.json into it."""
    from .grade import Thresholds, grade_run

    th = Thresholds(
        chamfer_mm=a.chamfer_mm,
        p95_mm=a.p95_mm,
        bore_diameter_mm=a.bore_diameter_mm,
        face_agreement=a.face_agreement,
    )
    rows, summary = grade_run(Path(a.tasks), Path(a.run_dir), th)
    for r in rows:
        ch = (r.get("posed") or {}).get("chamfer_mm")
        fa = (r.get("faces") or {}).get("agreement")
        sc = (r.get("scan_reference") or {}).get("chamfer_mm")
        print(
            f"{'PASS' if r['success'] else 'fail'}  {r['model'] or '-':18} {r['task'][:48]:48} "
            f"{r['status'] or '-':9} chamfer {'-' if ch is None else f'{ch:.3f}'} "
            f"(scan {'-' if sc is None else f'{sc:.3f}'})  faces {'-' if fa is None else f'{fa:.0%}'}  "
            f"{r.get('why', '')}"
        )
        for f in (r.get("faces") or {}).get("worst", [])[:4]:
            print(
                f"        {f['area_share']:5.1%} of GT: {f['gt']:24} "
                f"model has {f['model_there']:24} agree {f['agree']:.0%}"
            )
    print(json.dumps(summary["models"], indent=1))
    return 0


def cmd_serve(a) -> int:
    import uvicorn

    from .server import create_app

    url = f"http://{a.host}:{a.port}"
    print(f"Scan Lab on {url}")
    if not a.no_browser:
        import threading
        import webbrowser

        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(a.workers or None), host=a.host, port=a.port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="synthscan", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)

    p = sub.add_parser("profiles")
    p.add_argument("--show", metavar="ID")
    p.set_defaults(fn=cmd_profiles)

    p = sub.add_parser("procedural")
    p.add_argument("out")
    p.add_argument("-n", type=int, default=20)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--kinds", help="comma list: plate,l_bracket,bushing,standoff,pocket_block")
    p.set_defaults(fn=cmd_procedural)

    p = sub.add_parser("run")
    p.add_argument("inputs", nargs="+", help="files and/or folders (searched recursively)")
    p.add_argument("-d", "--dataset", required=True)
    p.add_argument("-n", "--samples", type=int, default=4, help="samples per part")
    p.add_argument("-p", "--profile", default="random")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("-w", "--workers", type=int, default=0)
    p.add_argument("--save-points", action="store_true")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("reindex")
    p.add_argument("dataset")
    p.set_defaults(fn=cmd_reindex)

    p = sub.add_parser("export")
    p.add_argument("dataset")
    p.add_argument("out")
    p.add_argument("--split", choices=["train", "val", "test"])
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("grade", help="grade a ScanRuler bench run against the hidden answers")
    p.add_argument("tasks", help="tasks.jsonl from `synthscan export`")
    p.add_argument("run_dir", help="a run folder written by the fork's bench/run.mjs")
    p.add_argument("--chamfer-mm", type=float, default=0.25)
    p.add_argument("--p95-mm", type=float, default=0.5)
    p.add_argument("--bore-diameter-mm", type=float, default=0.2)
    p.add_argument("--face-agreement", type=float, default=0.9)
    p.set_defaults(fn=cmd_grade)

    p = sub.add_parser("serve")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8849)
    p.add_argument("-w", "--workers", type=int, default=0)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(fn=cmd_serve)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
