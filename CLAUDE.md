# synthetic-scan: synthetic 3D-scan dataset generator

Read AGENTS.md in full before doing anything in this repo, and follow it.
README.md maps the docs; CONTRIBUTING.md is the full process.

## Mission

Turn ground-truth CAD solids into realistic, heavily randomized synthetic
3D-scanner meshes, with exact ground truth, so that the LLM-driven
reconstruction in a fork of CNC Kitchen's ScanRuler can be measured and
improved until *small, cheap* models reconstruct parts accurately. The plan,
owner decisions and milestones are in **[docs/PLAN.md](docs/PLAN.md)**.

## Non-negotiable development rules

1. **Milestones with hard exit criteria** (docs/PLAN.md §6). Don't start one
   before the previous one's criteria are met and verified. The one exception
   is the owner's: M2 runs in parallel with M1 (PLAN §0).
2. **Real scans judge realism.** Synthetic output is evidence of nothing
   about realism by itself. Profile ranges change only against real scans
   of known parts (research/scan-artifacts.md §4.5, §6).
3. **Ground truth is exact and never touched to flatter a number.** GT
   tessellation, face labels and design params come from the CAD. Metrics
   are computed against them, in the CAD frame.
4. **Measure, don't vibe.** Every "it's faster / more realistic / better"
   claim comes with a number: throughput (§4.1), deviation statistics, or
   harness scores.
5. **Randomize causes, not symptoms.** Simulate the physical mechanism
   (rays, projector shadow, fusion), never "add holes to the mesh". Vary
   algorithms as well as parameters. Anything constant becomes a fingerprint
   a downstream model can learn.
6. **Failure analysis over score chasing.** Every reconstruction failure (M2+)
   gets a written root cause from its trace before anything changes.
7. **Ask before assuming scanner facts and before choosing what users see.**
   Cite docs/research/ or a source; offer options and the owner picks.
8. **Licences first.** McMaster-Carr and similar CAD is private input only
   (AGENTS.md §0).

## Layout

```
src/synthscan/
  randomness.py   seeded distributions (U, LogU, Choice, Maybe, ...), sample_tree, per-sample RNG
  profiles.py     scanner profiles P1-P5 = correlated priors; random mix + "wild" widening; cohere()
  parts.py        load STEP (build123d/OCP: tessellation + per-face analytic labels) or meshes
  scanner.py      virtual scanner: placement, camera paths, per-frame capture + artifacts, registration error
  meshing.py      fusion (VoxelBlockGrid TSDF | TSDF->Poisson | Poisson), post-processing, hole filler, export pose
  metrics.py      exact scan<->GT distances, coverage, topology stats
  pipeline.py     generate_sample(): one part + seed -> scan.stl + meta.json
  dataset.py      on-disk layout, inputs, part cache, manifest, atomic writes
  batch.py        process-pool bulk runs, resumable
  procedural.py   random parametric parts (build123d) with exact design params
  grade.py        score a ScanRuler bench run vs hidden GT (docs/HARNESS.md)
  server.py       Scan Lab API (docs/API.md) + serves ui/dist
  cli.py          `synthscan` command
ui/               Scan Lab (React 19 + Vite + three.js + zustand), FootprintUi design language
docs/             PLAN, SIMULATOR, DATASET, API, research/
tests/            pytest: randomness/profiles, scanner physics, pipeline, server
scripts/          check.py (every check), launch.ps1 (Scan Lab.bat)
data/             gitignored: datasets/, inputs/, check logs (SYNTHSCAN_DATA overrides)
```

## Commands

```
uv sync                                        # Python 3.12 env (open3d, build123d, trimesh, fastapi)
uv run python scripts/check.py [lint format py ui]   # every check once; run before every PR
uv run pytest                                  # tests (~40 s)
uv run synthscan doctor                        # environment check
uv run synthscan procedural data/inputs/proc -n 50 --seed 0     # parametric STEP parts + params
uv run synthscan run <files/folders...> -d NAME -n 4 [-p PROFILE] [--seed S] [-w WORKERS] [--save-points]
uv run synthscan profiles [--show ID]          # list profiles / dump one's distributions
uv run synthscan export NAME OUT --split test  # flat scans/ + tasks.jsonl (hidden answers) for a harness
uv run synthscan grade TASKS.jsonl RUN_DIR     # grade a bench run (fork: node bench/run.mjs, docs/HARNESS.md)
uv run synthscan reindex NAME                  # rebuild manifest.jsonl from sample folders
uv run synthscan serve                         # Scan Lab on http://127.0.0.1:8849 (or double-click Scan Lab.bat)
cd ui && npm ci && npm run build               # UI build (Scan Lab.bat does this when sources change)
cd ui && npm run dev                           # UI hot reload on :5173, proxies /api to :8849
```

## Engine facts (measured; see docs/PLAN.md §4, docs/SIMULATOR.md)

- Ray casting is Embree via Open3D `RaycastingScene` (~42 M rays/s). The
  numpy per-frame artifact pipeline costs more than the rays do.
- Open3D 0.20 Windows wheel: the legacy `ScalableTSDFVolume` integrates
  nothing (use the tensor `VoxelBlockGrid`), and VTK `fill_holes` silently
  fills nothing (use `meshing.fill_holes`).
- `create_rays_pinhole` rays pass through pixel **centres**; back-projection
  uses `u + 0.5`. Getting this wrong biases every point by half a pixel.
- The VoxelBlockGrid hash order varies run to run. `meshing.canonical`
  sorts the fused mesh so samples are byte-reproducible.
- STEP export embeds a timestamp, so a regenerated procedural STEP is a new
  part (new sha1, new seed stream). Keep the generated files.
- `trimesh.load("x.step")` returns **metres**. We load STEP with build123d
  (mm) instead.
- Dev box: Ryzen 7 3700X 8C/16T, 96 GB, RTX 4070 12 GB, Windows 10.

## Gotchas

- `uv run` re-syncs and fails while a `synthscan.exe` is running (file
  lock). Use `uv run --no-sync` during long batches.
- Never commit anything from `data/`: multi-GB, and possibly licensed CAD.
- In bash, never leave `cat > file` without a heredoc. It waits on stdin forever.
- ScanRuler fork: `D:\ScanRuler` (local clone). `claude -p` there needs
  `MCP_CONNECTION_NONBLOCKING=false`, and full model ids (`--model haiku` is
  Haiku 4.5). PowerShell drops empty-string arguments like `--tools ""`, so use
  bash or Node.
