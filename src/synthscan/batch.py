"""Bulk generation: many inputs x many samples, in parallel, resumable.

Two phases, both in a process pool:

1. **Prepare** each input once (STEP tessellation + face labels, cached in
   ``parts/``). Inputs that fail here (corrupt files, empty meshes) are logged
   to ``failures.jsonl`` and skipped; they never stop the batch.
2. **Sample**: one task per (part, sample index). Tasks whose sample folder
   already exists are skipped, so re-running a job resumes it.

Parallelism: processes, not threads (numpy/Open3D release the GIL only
partly). Each worker caps its own native thread pools (Embree rays, OpenMP)
so ``workers x threads`` matches the machine instead of oversubscribing it.
Results are deterministic regardless of worker count (see randomness.py).
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import traceback
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from dataclasses import dataclass, field

from .dataset import Dataset, manifest_row, rename_dir, sample_id


@dataclass
class JobSpec:
    dataset: str
    profile: str = "random"
    samples_per_part: int = 4
    seed: int = 0
    inputs: list[str] | None = None  # None = every input without samples yet
    save_points: bool = False
    workers: int = 0  # 0 = half the logical CPUs
    data_root: str | None = None


@dataclass
class Progress:
    total: int = 0
    done: int = 0
    failed: int = 0
    skipped: int = 0
    started: float = field(default_factory=time.time)
    errors: list[dict] = field(default_factory=list)

    def eta_s(self) -> float | None:
        finished = self.done + self.failed
        if finished == 0 or self.total == 0:
            return None
        rate = (time.time() - self.started) / finished
        return rate * (self.total - finished)


def default_workers() -> int:
    return max(1, (os.cpu_count() or 2) // 2)


def _init_worker(threads: int) -> None:
    # Must run before Open3D/numpy spin up their pools in this process.
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[var] = str(threads)


def _prepare_task(root: str | None, dataset: str, input_name: str) -> dict:
    from pathlib import Path

    ds = Dataset(dataset, Path(root) if root else None)
    return ds.prepare_part(input_name)


def _sample_task(root, dataset, input_name, part_id, index, profile, seed, save_points, threads) -> dict:
    from pathlib import Path

    from .pipeline import _json_default, generate_sample

    ds = Dataset(dataset, Path(root) if root else None)
    sid = sample_id(part_id, profile, seed, index)
    final = ds.sample_dir(sid)
    tmp = final.with_name(f".tmp-{sid}")
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        meta = generate_sample(
            ds.load_part(part_id), index, profile, seed, tmp, save_points, threads, input_name
        )
        meta["sample_id"] = sid
        (tmp / "meta.json").write_text(json.dumps(meta, indent=1, default=_json_default))
        if final.exists():
            shutil.rmtree(final)
        rename_dir(tmp, final)
        return manifest_row(meta, final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def run_job(
    spec: JobSpec,
    on_progress: Callable[[Progress], None] | None = None,
    cancel: threading.Event | None = None,
) -> Progress:
    """Run a whole job, blocking. ``on_progress`` is called from this thread after every task."""
    from pathlib import Path

    root = Path(spec.data_root) if spec.data_root else None
    ds = Dataset.create(spec.dataset, root)
    cancel = cancel or threading.Event()
    workers = spec.workers or default_workers()
    threads = max(1, (os.cpu_count() or 2) // workers)
    prog = Progress()

    if spec.inputs is None:
        names = [r["name"] for r in ds.input_rows() if r["status"] == "new"]
    else:
        names = list(spec.inputs)
    prog.total = len(names) * spec.samples_per_part
    notify = on_progress or (lambda p: None)
    notify(prog)

    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker, initargs=(threads,)) as pool:
        # ---- phase 1: prepare parts
        prep: dict[Future, str] = {
            pool.submit(_prepare_task, spec.data_root, spec.dataset, n): n for n in names
        }
        parts: dict[str, dict] = {}
        for fut in list(prep):
            name = prep[fut]
            try:
                parts[name] = fut.result()
            except Exception as e:
                err = {"input": name, "sample": None, "error": f"{type(e).__name__}: {e}"}
                ds.append_failure(err)
                prog.errors.append(err)
                prog.failed += spec.samples_per_part
                notify(prog)
            if cancel.is_set():
                break

        # ---- phase 2: samples
        tasks = []
        for name, info in parts.items():
            for i in range(spec.samples_per_part):
                sid = sample_id(info["part_id"], spec.profile, spec.seed, i)
                if ds.has_sample(sid):
                    prog.skipped += 1
                    prog.done += 1
                    continue
                tasks.append((name, info["part_id"], i, sid))
        notify(prog)

        pending: dict[Future, tuple] = {}
        it = iter(tasks)

        # Keep only ~2 tasks per worker queued so cancel takes effect quickly.
        def refill():
            while len(pending) < workers * 2 and not cancel.is_set():
                t = next(it, None)
                if t is None:
                    return
                f = pool.submit(
                    _sample_task,
                    spec.data_root,
                    spec.dataset,
                    t[0],
                    t[1],
                    t[2],
                    spec.profile,
                    spec.seed,
                    spec.save_points,
                    threads,
                )
                pending[f] = t

        refill()
        while pending:
            finished, _ = wait(list(pending), return_when=FIRST_COMPLETED)
            for fut in finished:
                name, pid, i, sid = pending.pop(fut)
                try:
                    ds.append_manifest(fut.result())
                    prog.done += 1
                except Exception as e:
                    err = {
                        "input": name,
                        "sample": sid,
                        "error": f"{type(e).__name__}: {e}",
                        "trace": traceback.format_exception_only(type(e), e)[-1].strip(),
                    }
                    ds.append_failure(err)
                    prog.errors.append(err)
                    prog.failed += 1
                notify(prog)
            refill()
    return prog
