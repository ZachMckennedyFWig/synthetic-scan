# synthetic-scan: plan

The source of truth for what we're building, why, what the owner decided, how
good it is, and what comes next. AGENTS.md §1 says which sections to read in
full.

## §0 Owner decisions

Dated. A decision changes only by a new dated entry, never by editing an old
one. Entries marked **proposed** were made by an agent in the founding
session (2026-11-04) to keep work moving. They stand until the owner confirms
or replaces them.

| Date | Decision |
|---|---|
| 2026-11-04 | **Goal**: a ground-truth synthetic-scan dataset to tune, examine and extend LLM-driven reconstruction in a fork of CNC Kitchen's ScanRuler, so that small, cheap models (Haiku-class, small GPT, cheap open models) reconstruct accurately. This repo is the first step. (owner) |
| 2026-11-04 | Artifacts must be **highly random**, so that improvements don't learn this generator's pattern. (owner) |
| 2026-11-04 | Python. Rust only for a measured large win (owner allowed it). **Proposed**: no Rust. The hot paths are already C++ (Embree ray casting, TSDF, Poisson) inside Open3D; numpy per frame is the remainder (§4). |
| 2026-11-04 | UI design and architecture follow FootprintUi: Linear dark tokens, tab bar, split panes on one shared camera, right panel, mono status bar, one process and one port. (owner) |
| 2026-11-04 | Bulk upload and bulk processing are first-class. (owner) |
| 2026-11-04 | ~~**Proposed**: McMaster-Carr CAD is **private input only**. Its terms forbid keeping copies, redistribution, scraping, and use "for or in connection with training or fine-tuning AI" (research/cad-sources.md §1). Files are downloaded by hand into a private folder and never committed or published. Training or tuning on them needs McMaster's written permission. **The owner should read this.**~~ *(Superseded below.)* |
| 2026-11-04 | **McMaster-Carr is used** as private evaluation input. No model is trained or fine-tuned here: the parts test an existing agent (Opus, Haiku, later DeepSeek) driving ScanRuler, so the *process and tooling* improve. Files are still downloaded by hand, kept in the gitignored `data/`, and never committed, published or shared. Their terms' "in connection with" wording is broad, so this stays a local evaluation set. (owner) |
| 2026-11-04 | **Calibration scanner: Creality Raptor Pro**, usually at its highest settings (blue laser, ~0.07 mm min point distance). Its laser mode calibrates profile `laser_markers` (P3), and its NIR mode can calibrate `budget_ir_handheld` (P1). (owner) |
| 2026-11-04 | **Models:** baseline Opus 5.5 (works today), target Claude Haiku first, a DeepSeek model later. The harness must be client-agnostic: MCP for Claude, and an MCP-to-function-calling bridge for OpenAI-compatible APIs like DeepSeek's. (owner) |
| 2026-11-04 | **Target:** ScanRuler's full reverse-engineering flow (feature tree → STEP). Plan: finish this generator, fork ScanRuler, build a concurrent test suite on a tiny model, find weaknesses, patch the tool, repeat until tiny models reconstruct accurately. (owner) |
| 2026-11-04 | **Branching:** `main` only, with PRs. The tool runs locally only, so there is no deploy branch. (owner) |
| 2026-11-04 | **M2 runs in parallel with M1.** The owner is printing the `proc-a` set (12 procedural parts) to scan on the Raptor Pro. Meanwhile the ScanRuler fork and bench go ahead. This is an exception to "a milestone starts only when the previous one is met" (§6). M3 conclusions about realism still wait for M1. McMaster is reconfirmed as local only: never published or distributed. (owner) |
| 2026-11-04 | **Proposed**: the fork is a local clone at `D:\ScanRuler`, upstream `5c1f2f9` (v0.9.4), with no GitHub fork or push until the owner asks. The bench lives in the fork (`bench/`, Node, reusing upstream's e2e plumbing). Grading lives here (`synthscan grade`), next to the hidden answers. |
| 2026-11-04 | **Proposed**: the Claude client is Claude Code in print mode (`claude -p`) with ScanRuler as its only tools, on the owner's existing login (docs/HARNESS.md). The prompt is `bench/prompts/baseline.md`: "reverse-engineer and export STEP; unattended, so take the guides' defaults instead of asking". |
| 2026-11-04 | ~~**Proposed**: success means a body was built, posed chamfer ≤ 0.5 mm, posed p95 ≤ 1.0 mm, and every GT bore is matched with \|Δd\| ≤ 0.2 mm and no extra bores (docs/HARNESS.md "Grading").~~ *(Superseded below.)* |
| 2026-11-04 | **Grade against the real object, as close as possible**; show the scan's own error for reference. Success now also needs ≥ 90 % of the GT surface area to be the right kind and size of surface (face agreement, docs/HARNESS.md), and the distance thresholds tighten to posed chamfer ≤ 0.25 mm and p95 ≤ 0.5 mm. The exact numbers are **proposed**. (owner) |
| 2026-11-04 | **No Opus reference run.** (owner) |
| 2026-11-04 | **Procedural plates never overlap holes** (≥ 2 mm or ½ d web). Already generated parts (`data/inputs/proc-a`, being printed and scanned) are not regenerated. (owner) |
| 2026-11-04 | **Cheap model: GPT-6 Luna, through the OpenAI API.** The API only reaches remote MCP servers, so the bench has its own function-calling loop around the local server (`bench/lib/openai.mjs`). The key goes in `D:\ScanRuler\bench\.env.local` (gitignored) or `OPENAI_API_KEY`. (owner) |
| 2026-11-04 | **The fork will be published eventually.** Write it as publishable: AGPL headers on every new file, no secrets or licensed CAD in it, and no ScanRuler trademark presented as ours. (owner) |
| 2026-11-04 | **Direction for M3 (owner):** stop showing every tool up front. Rebuild the approach around deterministic, pre-computed diagnostics of the scanned part, and a very low-token way to learn the tools and the process, so cheap models generalise to reverse-engineering workflows. Design: `D:\ScanRuler\FORK.md`. |
| 2026-11-04 | **Proposed**: source priority is (1) our own procedural build123d parts (we own them), (2) Fusion 360 Gallery and DeepCAD (research, non-commercial), (3) MFCAD++ and ABC (attribution), (4) hand-picked CC0 / CC BY Printables models that ship a STEP. MakerWorld, GrabCAD and TraceParts are excluded from anything shared. |
| 2026-11-04 | **Proposed**: splits are per part, by content hash, 80/10/10. Test-split parts are never used to tune ScanRuler prompts or tools. |
| 2026-11-04 | **Proposed**: STEP is the preferred input (analytic face labels give graded answers). Mesh inputs are accepted but carry no feature ground truth. |
| 2026-11-04 | **Proposed**: units are millimetres everywhere. Exports carry a random pose like real scanner files, and the calibration scale error is deliberately not undone by `scan_to_cad`. |
| 2026-11-05 | **The operator picks a finer resolution for a small part** (profiles v2): at least `voxels_across_min` ~ U(6, 12) fusion voxels across the part's middle extent, never finer than the profile's finest spacing. A phone scan of a 10 mm standoff gave no surface at all before. The range is proposed, for M1 calibration. Of the existing samples it changes 1/65; datasets on disk are not regenerated. (owner approved the clamp) |
| 2026-11-05 | **No OpenAI rate-limit upgrade** (it needs the $100 tier): Luna runs go slowly, at ≤ 4 in parallel. **Haiku benchmarking stops for now**; the bench runs Luna only. (owner) |

## §1 What success looks like

1. **Realism**: a person who scans parts can't pick our scans out of a lineup
   of real ones, and a small point-cloud classifier can't do much better than
   chance (§6 M1).
2. **Coverage**: every artifact a real consumer or prosumer pipeline produces
   is either simulated (docs/SIMULATOR.md) or parked with a reason (PARKED.md).
3. **Usefulness**: the ScanRuler fork's small-model reconstruction measurably
   improves on held-out parts **and** on real scans, not only on ours (§6 M3).

## §2 Architecture

- `src/synthscan/`: the generator, as a library plus a CLI (`synthscan`).
  How it works and the artifact catalogue are in **docs/SIMULATOR.md**.
- `src/synthscan/server.py` + `ui/`: **Scan Lab**, the FootprintUi-style viewer
  and batch front-end. HTTP contract: **docs/API.md**. UI notes: `ui/README.md`.
- Data on disk: **docs/DATASET.md**.
- Research: `docs/research/` holds scan-artifacts.md (the artifact physics and
  numbers), cad-sources.md (where parts come from, licences, the STEP loader)
  and scanruler.md (the target app's internals and weaknesses).

## §3 Data model

docs/DATASET.md is normative. Change it in the same PR as the code.

## §4 Measured facts

Dev box: Ryzen 7 3700X (8C/16T), 96 GB, RTX 4070 (unused so far), Windows 10,
Python 3.12, Open3D 0.20.

| What | Number | How measured |
|---|---|---|
| Embree ray casting | ~42 M rays/s, 16 threads | `RaycastingScene.cast_rays`, 800×600 × 20, box scene |
| Exact distance queries | 100k points in 8 ms | `compute_signed_distance` |
| Fusion bias at zero noise (0.42 mm voxel) | median signed −0.007 to +0.002 mm, p95 \|d\| ≈ 0.08 mm, for TSDF, Poisson and TSDF→Poisson | scratch check on a 40×30×20 block with a bore, 2026-11-04 |
| Throughput | see §4.1 | `synthscan run` |
| ScanRuler bench job ready (holder + headless Chrome + scan open) | ~3 s | `bench/run.mjs`, 2 jobs in parallel |
| Haiku 5.5 context at turn 1 with ScanRuler full tools | 129.5 k tokens (Claude Code alone: 8.2 k; `--tools compact`: 24.9 k) | docs/HARNESS.md |

### §4.1 Throughput

12 procedural parts × 3 samples, `random` profile, 8 workers:

CPU time is per sample inside one worker. Wall time is the whole batch.

| Date | Commit | Wall time | Per sample (wall) | CPU s/sample (mean / median / max) | Failures | Notes |
|---|---|---|---|---|---|---|
| 2026-11-04 | (uncommitted) | 405 s | 11.3 s | 62 / – / 322 | 0 | first run |
| 2026-11-04 | (uncommitted) | 191 s | 5.3 s | 34 / 28 / 129 | 1 | `--save-points`; capture spacing coarsened to fit caps in 16/36 samples; one Windows rename "Access is denied" (now retried, and the re-run resumed it in 49 s) |

Where the time goes (one heavy sample, profiled): screened Poisson ≈ 60%. It
runs single-threaded on purpose, because multi-threaded Poisson isn't
deterministic (a different hash on every run) and samples must be
byte-reproducible. In a full worker pool, more threads per sample would buy
latency, not throughput. Next are the random-field cosines, point gathering
for Poisson, and the canonical sort.

Quality spread of that batch (36 samples): coverage median 0.88 (0.31–1.00),
chamfer median 0.25 mm (0.05–1.8), triangles median 180k (1.3k–1.2M),
components median 1 (max 91).

## §5 The evaluation harness (design, M2)

From research/scanruler.md:

- ScanRuler has no model of its own. An MCP client (Claude Code, Codex, LM
  Studio, ...) drives a browser tab through a local MCP server and builds a
  feature tree with `reverse_feature_add` in an OCCT (wasm) kernel. It is
  AGPL-3.0, so a fork is fine for internal evaluation, and publishing or
  hosting it means publishing its source.
- **Headless:** the repo's own e2e harness (one MCP server + one headless
  Chrome page per instance) runs today. The `--engine` Node build can run
  without Chrome once a command whitelist is widened.
- **Our harness:** for each task in `synthscan export … --split test`, start
  an instance, open `scans/<id>.stl` (`units: mm`), and let a model drive it
  under a tool-call budget. Collect the exported STEP and the full tool trace.
  Grade against `hidden` with this repo's `metrics.compare` (chamfer /
  Hausdorff vs GT) plus feature checks (hole count, diameters, pitch from
  `features` and `design_params`).
- **Watch:** ScanRuler's `scan_qa` sends near-noiseless scans to a separate CAD
  pipeline and treats watertight meshes with no open rims as assembly
  wraps. Our generator varies both on purpose. Report results per `scan_qa`
  route.
- **Weaknesses for small models:** ~30k tokens of guides to read first;
  ~150 tools and ~50k tokens of schema; deeply nested feature JSON; verbose
  answers (19–41 KB); a check-and-fix loop that depends on vision; prompts that
  assume a human in the chat. These are what M3 attacks.

## §6 Milestones

A milestone starts only when the previous one's exit criteria are met and
verified.

**M0: Generator and Scan Lab (this session).**
Exit: every artifact in SIMULATOR.md is ✅/🟡 or parked; `scripts/check.py`
is green; a 36-sample bulk run has 0 failures; Scan Lab shows GT and scan
split and overlaid with the deviation heatmap; bulk upload and jobs work from
the UI. *Status: met 2026-11-04. The UI was driven by Playwright against the
real backend (dataset list, scan + GT ghost, heatmap, GT | Scan split, Space
flip, batch page; no console errors). A real drag-and-drop of files into the
batch page couldn't be automated and is left for the owner (`Scan Lab.bat`).*

**M1: Calibrate against real scans.** The owner scans 5–10 known parts on
the Creality Raptor Pro (a procedural set, 3D-printed or machined, plus McMaster
hardware with its STEP), with metadata: mode (laser / NIR), CrealityScan
version, resolution and quality settings (usually the highest), spray, markers,
turntable or handheld, and the export options (watertight, smoothing). Each
real scan's sibling synthetic samples come from `laser_markers` (laser) or
`budget_ir_handheld` (NIR), with the capture settings pinned through
`overrides` to match.
Exit:
- For each real scan, the distribution of signed deviation, edge radius,
  bore visibility depth, hole-area fraction, triangle size and island count
  falls inside the range our matching profile produces (research §4.5).
- Every `[est]` number in profiles.py that this contradicts is replaced, with
  the evidence noted.
- A real-vs-synthetic classifier on point patches is below 65% accuracy.

**M2: ScanRuler fork and concurrent test suite.** Fork it, add a headless
batch runner (N instances in parallel, each with its own MCP server, port,
config and output folder), ingest `synthscan export`, and run baselines:
Opus 5.5 (reference; works today) and Haiku (target) on the test split. Keep the
model client pluggable so a DeepSeek model can be added via an MCP→function-calling
bridge.
Exit: per-model success rate, chamfer, feature accuracy, tool calls and
tokens per task, and a failure taxonomy by `artifacts` and `profile`, all
reproducible from one command.
*Status (2026-11-04): runner, Claude Code client and grader built and tested
(docs/HARNESS.md). The GPT-6 Luna client is built and tested against a mock
API and now runs on the owner's key. No Opus baseline (owner).*

*Baselines (2026-11-05, `smoke`, unmodified ScanRuler, full tools; details in
`D:\ScanRuler\FORK.md`):*

| Model | Success | Faces agree (median) | Cost |
|---|---|---|---|
| Haiku 5.5 | 3/12 | 68 % | $72.75 notional |
| GPT-6 Luna | 4/36 | 66 % | $4.11 real |

*Luna on the same 12 scans as Haiku: 1/12. Both build a body almost every time and get
the size roughly right; both miss design intent: nominal sizes, edge treatment and secondary
features.*

*Pilot (2026-11-04), one job: Haiku 5.5 on `proc-plate-3-0000` /
`budget_ir_handheld` (closed scan, 0 rims), full tools, baseline prompt.*

| What | Result |
|---|---|
| Outcome | finished and exported a valid closed STEP |
| Time and cost | 204 s, notional $6.16 |
| Tool calls | 51 (4 errors) |
| Peak context | 241 k tokens per turn |
| Posed chamfer | 0.119 mm (the scan itself: 0.091 mm) |
| Volume ratio | 0.9996 |

*Under the first proposed thresholds the grade was a PASS. The model has the right overall size and opening, but
the wrong edge treatment: R1.5/R1.25 rounds where the part has a 0.5 mm
chamfer, and R3.75 corners where it has 3.5. The posed thresholds don't
catch this. Bores were not graded, because the GT plate's three Ø9 holes at a
6.25 mm pitch overlap into one lobed slot, so no cylinder wraps ≥ 270°. The
procedural plate generator allowed pitch < diameter (fixed for new parts).
Regraded with face agreement: **fail, 67 %**. The lobes are r4.23/4.31
against a nominal 4.5 (Ø9 M8 clearance, never snapped), and there are
fillets where the part has chamfers.*

**M3 runs as a loop:** run the suite on the tiny model → read the failing traces
and write root causes → patch the tool, guides or tool surface → rerun. Tune on
`train`/`val`, report on `test`, and also check the patches don't regress Opus.

*M3 early test (2026-11-05, owner-approved, Luna only): the dossier, `--tools small` and a
short guide, on the same 12 scans as the baselines. Details and root causes:
`D:\ScanRuler\FORK.md`.*

| Setup | Success | Faces agree (median) | Calls (median) | Peak context | Cost |
|---|---|---|---|---|---|
| Luna, full tools (B) | 1/12 | 63 % | 62 | ~190 k | $1.38 |
| Luna, small + dossier + guide | 1/12 | 64 % | 14.5 | 21.7 k | $0.088 |

*Accuracy held at 1/16 of the cost. The failures now come from deterministic inputs, not from
the model:*
- *open cuts on scans with unseen sides*
- *dossier bores (12/23 found, 10/23 at the right nominal)*
- *one misaligned plate*
- *blends, which nothing models yet*

*The pilot also found two page bugs, both fixed in the fork. Accept solved the whole sketch for
each trial: 772 s, then a failure. A fit at a face's height (844 chains) hung the page.*

**M3: Tooling for small models.** Using M2's failure analysis (look at the
traces, write root causes before changing anything): a compact tool surface;
deterministic primitive proposals (plane / cylinder / hole-pattern fits with
residuals) the model chooses from instead of authoring; short task-focused
guides; non-vision verification (numeric deviation summaries per feature).
Exit: improvement on held-out synthetic **and** real scans, with no loss on
the strong model.

**M4: Release tiers.** CC BY tier (procedural + MFCAD++ + vetted CC0/CC BY);
research tier shipped as upstream IDs + seeds + generator version for local
regeneration.

## §7 Open questions for the owner

Resolved 2026-11-04 (§0): the calibration scanner, McMaster use, models
(GPT-6 Luna replaces DeepSeek), target flow, branching, grading, and no Opus run.

1. Is there a per-task token or cost budget for Haiku / GPT-6 Luna runs?
