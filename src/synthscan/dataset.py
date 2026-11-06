"""On-disk dataset layout (the full spec is docs/DATASET.md).

::

    <data>/datasets/<name>/
      dataset.json              name, created, generator version
      inputs/                   source files as uploaded (STEP/STL/...)
      parts/<part_id>/          one per unique input content
        gt.stl                  ground-truth tessellation, CAD frame (for people and ScanRuler)
        gt.npz                  vertices, faces, face_ids (what the pipeline loads)
        part.json               Part.summary(): extents, B-rep face labels, notes
      samples/<sample_id>/      one per simulated scan
        scan.stl                the deliverable: artifact-laden scan, scan frame
        meta.json               every sampled parameter, metrics, transforms
        points.ply              fused raw points (optional)
      manifest.jsonl            one row per finished sample (append-only; last row per id wins)
      failures.jsonl            one row per failed input/sample

Writes are crash-safe: a sample is generated into ``samples/.tmp-<id>`` and
renamed into place only when complete, so a killed batch leaves no half
samples, and re-running the same job skips everything already done.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

import numpy as np
import trimesh

from . import __version__
from .parts import SUPPORTED_EXTS, Part, file_sha1, load_part, part_id_for

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def data_dir() -> Path:
    """``SYNTHSCAN_DATA`` if set, else ``./data`` (gitignored)."""
    return Path(os.environ.get("SYNTHSCAN_DATA", "data")).resolve()


def sample_id(part_id: str, profile: str, seed: int, index: int) -> str:
    return f"{part_id}__{profile}-{seed}-{index:03d}"


class Dataset:
    def __init__(self, name: str, root: Path | None = None):
        if not NAME_RE.match(name):
            raise ValueError("dataset names are 1-64 chars of letters, digits, '.', '_' or '-'")
        self.name = name
        self.root = (root or data_dir()) / "datasets" / name

    # ------------------------------------------------------------------ lifecycle
    @classmethod
    def create(cls, name: str, root: Path | None = None) -> Dataset:
        ds = cls(name, root)
        for sub in ("inputs", "parts", "samples"):
            (ds.root / sub).mkdir(parents=True, exist_ok=True)
        info = ds.root / "dataset.json"
        if not info.exists():
            info.write_text(
                json.dumps({"name": name, "created": time.time(), "generator_version": __version__})
            )
        return ds

    @classmethod
    def all(cls, root: Path | None = None) -> list[Dataset]:
        base = (root or data_dir()) / "datasets"
        if not base.exists():
            return []
        return [cls(p.name, root) for p in sorted(base.iterdir()) if (p / "dataset.json").exists()]

    def exists(self) -> bool:
        return (self.root / "dataset.json").exists()

    def info(self) -> dict:
        meta = json.loads((self.root / "dataset.json").read_text())
        return {
            "name": self.name,
            "n_inputs": len(self.input_files()),
            "n_parts": sum(1 for p in (self.root / "parts").glob("*/gt.npz")),
            "n_samples": len(self.samples()),
            "created": meta.get("created"),
        }

    # ------------------------------------------------------------------ inputs
    def input_files(self) -> list[Path]:
        d = self.root / "inputs"
        return (
            sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS)
            if d.exists()
            else []
        )

    def add_input(
        self, src: Path, name: str | None = None, link: bool = False
    ) -> tuple[str | None, str | None]:
        """Copy (or hard-link) one file into ``inputs/``. Returns ``(saved_name, skip_reason)``."""
        name = _safe_name(name or src.name)
        if name.lower().endswith(".params.json"):  # design-parameter sidecar of a procedural part
            shutil.copyfile(src, self.root / "inputs" / name)
            return name, None
        if Path(name).suffix.lower() not in SUPPORTED_EXTS:
            return None, f"unsupported format {Path(name).suffix!r}"
        dst = self.root / "inputs" / name
        if dst.exists():
            if dst.stat().st_size == src.stat().st_size and file_sha1(dst) == file_sha1(src):
                return None, "already in dataset"
            stem, ext, k = dst.stem, dst.suffix, 1
            while dst.exists():
                dst = dst.with_name(f"{stem}-{k}{ext}")
                k += 1
        if link:
            try:
                os.link(src, dst)
                return dst.name, None
            except OSError:
                pass  # different volume: fall back to copying
        shutil.copyfile(src, dst)
        return dst.name, None

    def input_rows(self) -> list[dict]:
        rows = self.samples()
        per_input: dict[str, int] = {}
        for r in rows:
            per_input[r.get("input", "")] = per_input.get(r.get("input", ""), 0) + 1
        failed = {f["input"] for f in self.failures() if f.get("sample") is None}
        out = []
        for p in self.input_files():
            n = per_input.get(p.name, 0)
            out.append(
                {
                    "name": p.name,
                    "size": p.stat().st_size,
                    "format": p.suffix.lower().lstrip("."),
                    "n_samples": n,
                    "status": "done" if n else "failed" if p.name in failed else "new",
                }
            )
        return out

    # ------------------------------------------------------------------ parts
    def prepare_part(self, input_name: str) -> dict:
        """Load + tessellate an input once; later calls hit the cache. Returns ``part.json``."""
        src = self.root / "inputs" / input_name
        sha = file_sha1(src)
        pid = part_id_for(src, sha)
        pdir = self.root / "parts" / pid
        if (pdir / "gt.npz").exists() and (pdir / "part.json").exists():
            return json.loads((pdir / "part.json").read_text())
        part = load_part(src)
        tmp = self.root / "parts" / f".tmp-{pid}-{os.getpid()}"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        np.savez(tmp / "gt.npz", vertices=part.vertices, faces=part.faces, face_ids=part.face_ids)
        trimesh.Trimesh(part.vertices, part.faces, process=False).export(tmp / "gt.stl")
        summary = part.summary() | {"input": input_name}
        sidecar = src.with_name(src.stem + ".params.json")  # procedural design parameters, if any
        if sidecar.exists():
            summary["design_params"] = json.loads(sidecar.read_text())
        (tmp / "part.json").write_text(json.dumps(summary, indent=1))
        _replace_dir(tmp, pdir)
        return summary

    def load_part(self, part_id: str) -> Part:
        pdir = self.root / "parts" / part_id
        z = np.load(pdir / "gt.npz")
        info = json.loads((pdir / "part.json").read_text())
        return Part(
            part_id,
            info["name"],
            info["source"],
            info["sha1"],
            z["vertices"],
            z["faces"],
            z["face_ids"],
            info.get("features", []),
            info.get("notes", []),
        )

    # ------------------------------------------------------------------ samples
    def sample_dir(self, sid: str) -> Path:
        if "/" in sid or "\\" in sid or sid.startswith("."):
            raise ValueError("bad sample id")
        return self.root / "samples" / sid

    def has_sample(self, sid: str) -> bool:
        return (self.sample_dir(sid) / "meta.json").exists()

    def samples(self) -> list[dict]:
        path = self.root / "manifest.jsonl"
        if not path.exists():
            return []
        rows: dict[str, dict] = {}
        for line in path.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                rows[r["id"]] = r
        return [r for r in rows.values() if self.has_sample(r["id"])]

    def append_manifest(self, row: dict) -> None:
        with open(self.root / "manifest.jsonl", "a") as f:
            f.write(json.dumps(row) + "\n")

    def append_failure(self, row: dict) -> None:
        with open(self.root / "failures.jsonl", "a") as f:
            f.write(json.dumps(row | {"time": time.time()}) + "\n")

    def failures(self) -> list[dict]:
        path = self.root / "failures.jsonl"
        if not path.exists():
            return []
        return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]

    def reindex(self) -> int:
        """Rebuild ``manifest.jsonl`` from the sample folders (after a crash or a manual edit)."""
        rows = []
        for meta_path in sorted((self.root / "samples").glob("*/meta.json")):
            rows.append(manifest_row(json.loads(meta_path.read_text()), meta_path.parent))
        (self.root / "manifest.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        return len(rows)


def manifest_row(meta: dict, sample_dir: Path) -> dict:
    """The compact per-sample row the UI lists (``SampleRow`` in docs/API.md)."""
    m = meta["metrics"]
    return {
        "id": meta["sample_id"],
        "input": meta.get("input"),
        "part_id": meta["part_id"],
        "part_name": meta["part_name"],
        "sample_index": meta["sample_index"],
        "split": meta["split"],
        "profile": meta["profile"],
        "seed": meta["seed"]["global"],
        "artifacts": meta["artifacts"],
        "has_points": (sample_dir / "points.ply").exists(),
        "metrics": {
            "chamfer_mm": m["chamfer_mm"],
            "hausdorff_mm": m["hausdorff_mm"],
            "rms_mm": m["rms_mm"],
            "p95_mm": m["scan_to_gt"]["p95"],
            "coverage": m["coverage"],
            "n_tris": m["n_tris"],
            "watertight": m["watertight"],
            "n_components": m["n_components"],
            "n_boundary_edges": m["n_boundary_edges"],
        },
    }


def _safe_name(name: str) -> str:
    name = Path(name.replace("\\", "/")).name
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    return name[:120] or "part"


def rename_dir(tmp: Path, final: Path, attempts: int = 20) -> None:
    """``os.replace`` for a folder, retried: on Windows a virus scanner, the search indexer or a
    viewer listing the dataset can hold a handle on freshly written files for a moment, and
    the rename then fails with "Access is denied" (seen in a real 36-sample batch)."""
    for i in range(attempts):
        try:
            os.replace(tmp, final)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(0.05 * (i + 1))


def _replace_dir(tmp: Path, final: Path) -> None:
    """Atomically move a finished folder into place (another worker may have won the race)."""
    try:
        rename_dir(tmp, final)
    except OSError:
        if final.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            raise
