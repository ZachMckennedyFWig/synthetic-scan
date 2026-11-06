"""Scan Lab backend: the HTTP API in docs/API.md, plus the built UI from ``ui/dist``.

One process, one port (default 8849), like FootprintUi: Node is needed only to
build the UI. Jobs run one at a time on a background thread, each fanning out
to a process pool (``batch.run_job``), so the API stays responsive while a
batch saturates the CPU.

Geometry for the viewer is served in the CAD frame as ``SSG1`` binary
(docs/API.md). Deviation scalars are computed on first request and cached next
to the sample as ``.view-<layer>.npz``.
"""

from __future__ import annotations

import os
import queue
import struct
import tempfile
import threading
import time
import uuid
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .batch import JobSpec, Progress, default_workers, run_job
from .dataset import Dataset, data_dir

UI_DIST = Path(__file__).resolve().parents[2] / "ui" / "dist"
LAYERS = ("gt", "scan", "points", "coverage")


# --------------------------------------------------------------------------- jobs


class JobRequest(BaseModel):
    dataset: str
    profile: str = "random"
    samples_per_part: int = Field(4, ge=1, le=64)
    seed: int = 0
    inputs: list[str] | None = None
    save_points: bool = False


class NewDataset(BaseModel):  # module level: FastAPI cannot resolve postponed local annotations
    name: str


class Job:
    def __init__(self, req: JobRequest):
        self.id = uuid.uuid4().hex[:10]
        self.req = req
        self.state = "queued"
        self.created = time.time()
        self.started: float | None = None
        self.finished: float | None = None
        self.progress = Progress()
        self.cancel = threading.Event()

    def view(self) -> dict:
        p = self.progress
        return {
            "id": self.id,
            "dataset": self.req.dataset,
            "profile": self.req.profile,
            "state": self.state,
            "total": p.total,
            "done": p.done,
            "failed": p.failed,
            "created": self.created,
            "started": self.started,
            "finished": self.finished,
            "eta_s": p.eta_s() if self.state == "running" else None,
            "errors": [{k: e.get(k) for k in ("input", "sample", "error")} for e in p.errors[-200:]],
        }


class JobManager:
    """FIFO of jobs, executed one at a time on a daemon thread."""

    def __init__(self, workers: int):
        self.workers = workers
        self.jobs: dict[str, Job] = {}
        self.q: queue.Queue[Job] = queue.Queue()
        threading.Thread(target=self._loop, daemon=True, name="synthscan-jobs").start()

    def submit(self, req: JobRequest) -> Job:
        job = Job(req)
        self.jobs[job.id] = job
        self.q.put(job)
        return job

    def _loop(self) -> None:
        while True:
            job = self.q.get()
            if job.cancel.is_set():
                job.state = "cancelled"
                continue
            job.state, job.started = "running", time.time()
            spec = JobSpec(
                dataset=job.req.dataset,
                profile=job.req.profile,
                samples_per_part=job.req.samples_per_part,
                seed=job.req.seed,
                inputs=job.req.inputs,
                save_points=job.req.save_points,
                workers=self.workers,
                data_root=str(data_dir()),
            )
            try:

                def on_progress(p: Progress, job=job):
                    job.progress = p

                run_job(spec, on_progress, job.cancel)
                if job.cancel.is_set():
                    job.state = "cancelled"
                elif job.progress.total and job.progress.failed == job.progress.total:
                    job.state = "failed"
                else:
                    job.state = "done"
            except Exception as e:  # the pool itself broke; keep the server alive
                job.progress.errors.append({"input": "", "sample": None, "error": f"{type(e).__name__}: {e}"})
                job.state = "failed"
            job.finished = time.time()


# --------------------------------------------------------------------------- geometry


def encode_ssg1(vertices: np.ndarray, faces: np.ndarray | None, scalar: np.ndarray | None) -> bytes:
    """docs/API.md "Binary SSG1": 16-byte header, then f32 positions, u32 indices, f32 scalar."""
    v = np.ascontiguousarray(vertices, dtype="<f4")
    f = np.ascontiguousarray(faces if faces is not None else np.zeros((0, 3)), dtype="<u4")
    s = (
        None
        if scalar is None
        else np.ascontiguousarray(np.nan_to_num(scalar, posinf=1e3, neginf=-1e3), dtype="<f4")
    )
    head = b"SSG1" + struct.pack("<III", len(v), len(f), 1 if s is not None else 0)
    return head + v.tobytes() + f.tobytes() + (s.tobytes() if s is not None else b"")


def build_layer(ds: Dataset, sid: str, layer: str) -> tuple[np.ndarray, np.ndarray | None, np.ndarray | None]:
    """Compute (or load the cached) arrays for one viewer layer, in the CAD frame."""
    import json

    import open3d as o3d
    import trimesh

    from .metrics import distances_to, gt_samples
    from .scanner import transform

    sdir = ds.sample_dir(sid)
    cache = sdir / f".view-{layer}.npz"
    if cache.exists():
        z = np.load(cache)
        return z["v"], (z["f"] if z["f"].size else None), (z["s"] if z["s"].size else None)
    meta = json.loads((sdir / "meta.json").read_text())
    part = ds.load_part(meta["part_id"])
    watertight = part.mesh.is_watertight
    s2c = np.array(meta["transforms"]["scan_to_cad"])
    f = s = None
    if layer == "gt":
        v, f = part.vertices, part.faces
    elif layer == "scan":
        m = trimesh.load(sdir / "scan.stl", process=True)
        v, f = transform(s2c, np.asarray(m.vertices)), np.asarray(m.faces)
        s = distances_to(part.vertices, part.faces, v, signed=watertight)
    elif layer == "points":
        if not (sdir / "points.ply").exists():
            raise FileNotFoundError("this sample has no points layer (generate with save_points)")
        v = transform(s2c, np.asarray(o3d.io.read_point_cloud(str(sdir / "points.ply")).points))
        s = distances_to(part.vertices, part.faces, v, signed=watertight)
    elif layer == "coverage":
        m = trimesh.load(sdir / "scan.stl", process=True)
        sv, sf = transform(s2c, np.asarray(m.vertices)), np.asarray(m.faces)
        v = gt_samples(part.vertices, part.faces, n=80_000, seed=1)
        s = distances_to(sv, sf, v, signed=False)
    else:
        raise KeyError(layer)
    _atomic_savez(cache, v=v, f=np.zeros(0) if f is None else f, s=np.zeros(0) if s is None else s)
    return v, f, s


def _atomic_savez(path: Path, **arrays) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".npz")
    os.close(fd)
    np.savez(tmp, **arrays)
    os.replace(tmp, path)


# --------------------------------------------------------------------------- app


def create_app(workers: int | None = None) -> FastAPI:
    app = FastAPI(title="Scan Lab", version=__version__)
    jobs = JobManager(workers or default_workers())

    def get_ds(name: str) -> Dataset:
        try:
            ds = Dataset(name)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        if not ds.exists():
            raise HTTPException(404, f"no dataset {name!r}")
        return ds

    @app.get("/api/health")
    def health():
        return {
            "ok": True,
            "version": __version__,
            "cpu_count": os.cpu_count(),
            "workers": jobs.workers,
            "open3d": True,
            "step_support": True,
            "data_dir": str(data_dir()),
        }

    @app.get("/api/profiles")
    def profiles():
        from .profiles import list_profiles

        return list_profiles()

    @app.get("/api/datasets")
    def datasets():
        return [d.info() for d in Dataset.all()]

    @app.post("/api/datasets")
    def create_dataset(body: NewDataset):
        try:
            return {"name": Dataset.create(body.name).name}
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.get("/api/datasets/{ds}/inputs")
    def inputs(ds: str):
        return get_ds(ds).input_rows()

    @app.post("/api/datasets/{ds}/inputs")
    async def upload(ds: str, files: list[UploadFile] = File(...)):
        d = get_ds(ds)
        saved, skipped = [], []
        for uf in files:
            fd, tmp = tempfile.mkstemp(dir=d.root, suffix=".upload")
            try:
                with os.fdopen(fd, "wb") as out:
                    while chunk := await uf.read(1 << 20):
                        out.write(chunk)
                name, reason = d.add_input(Path(tmp), uf.filename or "part")
            finally:
                Path(tmp).unlink(missing_ok=True)
            if name:
                saved.append(name)
            else:
                skipped.append({"name": uf.filename, "reason": reason})
        return {"saved": saved, "skipped": skipped}

    @app.post("/api/jobs")
    def submit(req: JobRequest):
        get_ds(req.dataset)
        from .profiles import PROFILES

        if req.profile != "random" and req.profile not in PROFILES:
            raise HTTPException(400, f"unknown profile {req.profile!r}")
        return {"id": jobs.submit(req).id}

    @app.get("/api/jobs")
    def list_jobs():
        return [j.view() for j in sorted(jobs.jobs.values(), key=lambda j: -j.created)]

    @app.get("/api/jobs/{jid}")
    def get_job(jid: str):
        if jid not in jobs.jobs:
            raise HTTPException(404, "no such job")
        return jobs.jobs[jid].view()

    @app.post("/api/jobs/{jid}/cancel")
    def cancel_job(jid: str):
        if jid not in jobs.jobs:
            raise HTTPException(404, "no such job")
        jobs.jobs[jid].cancel.set()
        return jobs.jobs[jid].view()

    @app.get("/api/datasets/{ds}/samples")
    def samples(ds: str):
        return get_ds(ds).samples()

    @app.get("/api/datasets/{ds}/samples/{sid}")
    def sample_meta(ds: str, sid: str):
        d = get_ds(ds)
        path = d.sample_dir(sid) / "meta.json"
        if not path.exists():
            raise HTTPException(404, "no such sample")
        return Response(path.read_bytes(), media_type="application/json")

    @app.get("/api/datasets/{ds}/samples/{sid}/geometry/{layer}")
    def geometry(ds: str, sid: str, layer: str):
        d = get_ds(ds)
        if layer not in LAYERS:
            raise HTTPException(404, f"unknown layer {layer!r}")
        if not d.has_sample(sid):
            raise HTTPException(404, "no such sample")
        try:
            v, f, s = build_layer(d, sid, layer)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e
        return Response(
            encode_ssg1(v, f, s),
            media_type="application/octet-stream",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    @app.get("/api/datasets/{ds}/samples/{sid}/files/{name}")
    def sample_file(ds: str, sid: str, name: str):
        d = get_ds(ds)
        if name not in ("scan.stl", "points.ply", "meta.json"):
            raise HTTPException(404, "not a downloadable file")
        path = d.sample_dir(sid) / name
        if not path.exists():
            raise HTTPException(404, "file not present")
        return FileResponse(path, filename=f"{sid}-{name}")

    @app.exception_handler(ValueError)
    def bad_value(_, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    if UI_DIST.exists():
        app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="ui")
    else:

        @app.get("/")
        def no_ui():
            return JSONResponse(
                {"detail": "UI not built: run `npm ci && npm run build` in ui/"}, status_code=503
            )

    return app


__all__ = ["create_app", "encode_ssg1", "build_layer"]
