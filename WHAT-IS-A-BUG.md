# What is a bug in synthetic-scan?

This page decides which problems get fixed. `AGENTS.md`, `CONTRIBUTING.md` and `PARKED.md` point here.

**TL;DR.** A problem that breaks a promise in section 1 gets fixed once it has evidence from section 2. The classes in section 3 are parked, except for their "Still in scope" lines.

Read all of it before judging a problem. A sentence found by search can mean something else out of context.

**MUST** and **MUST NOT** are hard rules. **SHOULD** can be broken only with a reason written in the PR description. **MAY** means allowed.

## Words

- **Bug.** synthetic-scan does something it shouldn't, or doesn't do something it should. Parked bugs are still bugs.
- **In scope.** Breaks a promise in section 1. It gets fixed once it has evidence.
- **Waiting for evidence.** Would be in scope, but has no evidence yet. No code is written for it.
- **Parked.** Fits a class in section 3. It's kept out of the code until evidence moves it into scope.
- **Owner.** Zach Mckennedy.
- **Ground truth (GT).** The CAD a sample was made from, its tessellation (`gt.stl`/`gt.npz`), its face labels and design params.
- **Real scan.** A mesh or point cloud a physical scanner produced from a physical part. A synthetic sample isn't one, however realistic.

Nobody writes "not a bug". Write **parked** instead.

Something that breaks no promise and fits no class, like a new profile, a new CAD source or faster code, is a feature. This page doesn't judge features.

## 1. What synthetic-scan promises

1. **Ground truth is exact.** GT geometry and labels match the source CAD within the tessellation tolerance (1e-4 of the diagonal, at least 2 µm), in mm, in the CAD frame. A sample's `scan_to_cad` puts its scan exactly where the simulation put it.
2. **Metrics mean what DATASET.md says.** Every number in `meta.json → metrics` is computed as documented, against the GT, in the CAD frame.
3. **Every sample is reproducible and fully described.** The same input, seed and generator version give a byte-identical `scan.stl`. `meta.json` records every sampled parameter and every artifact stage that fired.
4. **Artifacts come from causes.** Every simulated artifact comes from a modeled physical or software mechanism (SIMULATOR.md), never from editing the output to look scanned.
5. **Real scans are the realism bar.** Where our output for a profile falls outside what real scans of the same part show (by DATASET.md's metrics and research §4.5's distributions), that's a bug in the profile or the simulator.
6. **Bulk runs never lose or corrupt work.** A killed batch leaves no half-written sample, a re-run resumes, and one bad input fails alone without stopping the batch.
7. **Licences and held-out data are respected.** Nothing whose licence forbids it is committed or published, hidden answers never reach a model under test, and test parts are never used for tuning (AGENTS.md §0).
8. **Scan Lab shows the truth.** What the viewer draws (geometry, frames, deviation colours, metrics) matches the files on disk.
9. **Always green.** A clean checkout of `main` passes `uv run python scripts/check.py`.

## 2. Evidence

A problem needs one of these before code is written.

- **E1.** A real scan of a real part (scanner, app version, settings, part) that disagrees with our matching output by numbers. For promises other than 5: a user report with the dataset, sample id and what they saw.
- **E2.** A test on real data, or on a part with an exactly known answer, that fails on the current code. So does `check.py` failing on a clean checkout of `main`.
- **E3.** Wrong code you can quote, with file and line, where the wrong result follows from reading it.
- **E4.** The owner says it's a problem.

Not evidence on its own: a synthetic sample looking "too clean" or "too noisy" to someone, a forum anecdote, or an AI review that says something "could" happen. Those are good reasons to go and take a real scan.

## 3. Parked classes

If a problem fits a class, it's parked even when it seems to break a promise, unless it fits the class's "Still in scope" line.

**3.1 An artifact nobody has shown on a real scan.** "Scanners probably also do X" without a real scan showing X, or how big it is.
*Still in scope, once it has evidence.* E1 showing it, with a magnitude.

**3.2 Impossible or broken input.** CAD with self-intersecting or open solids, zero-thickness sheets, parts below 1 mm or above 2 m, files that OCCT or trimesh can't read.
*Still in scope.* The failure is logged in `failures.jsonl` and doesn't stop the batch (promise 6), and a crash is still a bug.

**3.3 Upstream library limits.** Open3D, OCCT/build123d, trimesh or Embree behaviour we can't change, when a workaround would be large.
*Still in scope.* A small workaround that keeps a promise (we already have three, SIMULATOR.md "pitfalls"), and anything that silently breaks promises 1–3.

**3.4 ScanRuler's own behaviour.** How the upstream app routes, prompts or meshes is the fork's work (M2–M3), not this generator's.
*Still in scope.* An export format or field the harness needs.

**3.5 Model limits.** A small LLM failing a reconstruction because it's a small LLM.
*Still in scope.* Tooling or instructions that make it fail when they shouldn't (M3, with traces).

**3.6 A difference that keeps every promise.** A different-but-valid random draw, a slightly different edge radius at the same settings after a dependency upgrade, a heatmap colour preference.

**Data loss and licence leaks.** If a parked or waiting problem could delete a dataset, publish licensed CAD, or show hidden answers to a model, tell the owner right away. Don't write a fix. The owner decides.

## 4. Worked examples

These happened while the repo was being built (2026-11-04), so they show how the classes apply.

| Problem | Class | Evidence | Result |
|---|---|---|---|
| Plane remnant kept a disc as wide as the part's bounding box (46 mm on a plate standing on edge) | Promise 4 | E2, deviation diagnosis on a smoke sample | **Fixed**: a skirt within `remnant_mm` of the contact outline |
| Back-projection used pixel corners while rays go through centres: a half-pixel bias | Promise 1/2 | E3 + E2, plane points at −9.935 instead of −10 | **Fixed** |
| Same seed, different `scan.stl` bytes | Promise 3 | E2, `test_sample_is_deterministic_and_aligned` | **Fixed**: `meshing.canonical` |
| Legacy TSDF and VTK hole filling silently do nothing in Open3D 0.20 | 3.3, still in scope (silent) | E2 | **Worked around** |
| No inter-reflection bounce rays: ghosts are approximated as spikes | 3.1 | none yet | **Parked** (`SIM-05`) |

## 5. How this page changes

The owner decides. Anyone MAY propose a change in an issue. Agents propose changes to their user and MUST NOT edit this page in a fix PR.
