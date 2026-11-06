# synthetic-scan

Turns CAD parts into **realistic, heavily randomized synthetic 3D-scanner
meshes**, with exact ground truth, in bulk. It's the first step toward making
the LLM-driven reconstruction in [CNC Kitchen's ScanRuler](https://github.com/CNCKitchen/ScanRuler)
work with small, cheap models: a dataset where we know the right answer for
every scan.

It doesn't add noise to the CAD mesh. It **scans** the part with a virtual
structured-light or laser scanner:

- **Capture:** Embree ray casting, a projector baseline that shadows deep
  bores, shiny and dark surface patches, range noise, flying pixels, tracking
  drift, marker stickers and table remnants.
- **Fusion:** the frames are fused the way scanner apps do it (TSDF and/or
  screened Poisson).
- **Export cleanup:** apps' hole filling, smoothing and decimation, randomized.

Every parameter is randomized per sample within correlated "scanner profiles"
and recorded in the sample's `meta.json`.

**Scan Lab** is the companion UI. It uploads parts in bulk and runs generation
jobs, then compares the original part and the scan in split-screen 3D with a
deviation heatmap. Its design follows FootprintUi.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Node 22 (Node only to build the UI).

**Double-click `Scan Lab.bat`.** On first run it creates the Python
environment, builds the UI, starts the server on http://127.0.0.1:8849 and
opens your browser.

From a terminal:

```bash
uv sync
uv run synthscan doctor                                   # check the environment
uv run synthscan procedural data/inputs/proc -n 50        # 50 parametric STEP parts we own
uv run synthscan run data/inputs/proc -d demo -n 4        # 4 random scans of each, in parallel
uv run synthscan serve                                    # Scan Lab
uv run python scripts/check.py                            # every check (lint, format, tests, UI build)
```

`synthscan run` takes any mix of files and folders (searched recursively) of
`.step/.stp/.stl/.obj/.ply/.3mf/.glb/.off`. It's resumable: run it again and it
skips samples that already exist.

## What you get per sample

`data/datasets/<name>/samples/<id>/scan.stl` is the synthetic scan, in an
arbitrary pose like a real export, in mm. Beside it, `meta.json` holds:

- every sampled parameter
- the artifacts that fired
- the scan→CAD transform
- exact metrics against the ground truth: chamfer, Hausdorff, p95, coverage,
  and topology

The ground truth is in `parts/<part_id>/`: the tessellation, plus analytic face
labels from STEP (hole radii, axes, planes) and design parameters for
procedural parts. Full spec in [docs/DATASET.md](docs/DATASET.md).

## How we work

The process is adapted from scouting-is-ez (match-cutter). The short version:

- **Real scans judge realism.** Synthetic output proves nothing about
  realism on its own.
- **Ground truth is exact and never edited to flatter a number.**
- **Measure, don't vibe.** Speed, realism and reconstruction quality are
  all numbers.
- **Randomize causes, not symptoms,** and vary the algorithms too, so nothing
  downstream learns this generator instead of the task.
- **Licences first.** McMaster-Carr CAD is private input only.
- **PRs only, evidence before code, the smallest fix, and you own what you
  send.**

## Which doc answers what

| Question | Doc |
| --- | --- |
| I'm an AI agent. What are my rules? | [AGENTS.md](AGENTS.md), then [CLAUDE.md](CLAUDE.md) |
| How do I make a change, test it and get it merged? | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Is this a bug, and does it get fixed? | [WHAT-IS-A-BUG.md](WHAT-IS-A-BUG.md), [PARKED.md](PARKED.md) |
| What are we building, what did the owner decide, how fast is it, what's next? | [docs/PLAN.md](docs/PLAN.md) |
| How does the simulator work, and which artifacts does it model? | [docs/SIMULATOR.md](docs/SIMULATOR.md) |
| What's in a dataset folder, and what does each field mean? | [docs/DATASET.md](docs/DATASET.md) |
| What's the backend↔UI contract? | [docs/API.md](docs/API.md), [ui/README.md](ui/README.md) |
| What do real scanners get wrong, by how much, and how do apps mesh? | [docs/research/scan-artifacts.md](docs/research/scan-artifacts.md) |
| Where can parts come from, and under what licence? | [docs/research/cad-sources.md](docs/research/cad-sources.md) |
| How does ScanRuler work, and where do small models struggle? | [docs/research/scanruler.md](docs/research/scanruler.md) |
| How are models run on ScanRuler and graded? | [docs/HARNESS.md](docs/HARNESS.md) |
| How do others keep CAD agents cheap, and what can be automated? | [docs/research/agent-tooling.md](docs/research/agent-tooling.md) |
