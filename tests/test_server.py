"""The HTTP contract in docs/API.md, end to end on a temporary data dir."""

import struct
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from synthscan.server import create_app, encode_ssg1


def decode_ssg1(b: bytes):
    assert b[:4] == b"SSG1"
    nv, nf, flags = struct.unpack("<III", b[4:16])
    off = 16
    v = np.frombuffer(b, "<f4", nv * 3, off).reshape(-1, 3)
    off += nv * 12
    f = np.frombuffer(b, "<u4", nf * 3, off).reshape(-1, 3)
    off += nf * 12
    s = np.frombuffer(b, "<f4", nv, off) if flags & 1 else None
    off += nv * 4 if s is not None else 0
    assert off == len(b)
    return v, f, s


def test_ssg1_roundtrip():
    v = np.random.rand(10, 3)
    f = np.array([[0, 1, 2], [2, 3, 4]])
    s = np.linspace(-1, 1, 10)
    v2, f2, s2 = decode_ssg1(encode_ssg1(v, f, s))
    assert np.allclose(v2, v, atol=1e-6) and np.array_equal(f2, f) and np.allclose(s2, s, atol=1e-6)
    v3, f3, s3 = decode_ssg1(encode_ssg1(v, None, None))
    assert len(f3) == 0 and s3 is None


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHSCAN_DATA", str(tmp_path))
    with TestClient(create_app(workers=2)) as c:
        yield c


def test_full_flow(client, block_with_hole):
    assert client.get("/api/health").json()["ok"]
    ids = {p["id"] for p in client.get("/api/profiles").json()}
    assert "random" in ids and "laser_markers" in ids

    assert client.post("/api/datasets", json={"name": "t1"}).status_code == 200
    assert client.post("/api/datasets", json={"name": "../evil"}).status_code == 400
    files = [("files", ("block.stl", block_with_hole.read_bytes())), ("files", ("notes.txt", b"x"))]
    up = client.post("/api/datasets/t1/inputs", files=files).json()
    assert up["saved"] == ["block.stl"] and up["skipped"][0]["name"] == "notes.txt"
    again = client.post("/api/datasets/t1/inputs", files=files[:1]).json()
    assert again["saved"] == [] and again["skipped"][0]["reason"] == "already in dataset"
    assert client.get("/api/datasets/t1/inputs").json()[0]["status"] == "new"

    jid = client.post(
        "/api/jobs",
        json={
            "dataset": "t1",
            "profile": "laser_markers",
            "samples_per_part": 1,
            "seed": 3,
            "save_points": True,
        },
    ).json()["id"]
    for _ in range(600):
        job = client.get(f"/api/jobs/{jid}").json()
        if job["state"] in ("done", "failed", "cancelled"):
            break
        time.sleep(0.5)
    assert job["state"] == "done", job
    assert job["done"] == 1 and job["failed"] == 0

    rows = client.get("/api/datasets/t1/samples").json()
    assert len(rows) == 1
    row = rows[0]
    for k in ("chamfer_mm", "hausdorff_mm", "rms_mm", "p95_mm", "coverage", "n_tris", "watertight"):
        assert k in row["metrics"]
    assert row["has_points"] and isinstance(row["sample_index"], int)
    assert client.get("/api/datasets/t1/inputs").json()[0]["status"] == "done"

    sid = row["id"]
    meta = client.get(f"/api/datasets/t1/samples/{sid}").json()
    assert meta["sample_id"] == sid and "params" in meta
    for layer in ("gt", "scan", "points", "coverage"):
        r = client.get(f"/api/datasets/t1/samples/{sid}/geometry/{layer}")
        assert r.status_code == 200, layer
        v, f, s = decode_ssg1(r.content)
        assert len(v) > 100
        assert (len(f) > 0) == (layer in ("gt", "scan"))
        assert (s is None) == (layer == "gt")
    # served scan geometry is in the CAD frame: it overlaps the GT box
    v, _, s = decode_ssg1(client.get(f"/api/datasets/t1/samples/{sid}/geometry/scan").content)
    assert np.median(np.abs(s)) < 0.3
    assert client.get(f"/api/datasets/t1/samples/{sid}/files/scan.stl").status_code == 200
    assert client.get(f"/api/datasets/t1/samples/{sid}/files/..%2Fdataset.json").status_code == 404
