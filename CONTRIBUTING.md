# Contributing to synthetic-scan

synthetic-scan makes realistic synthetic 3D-scanner meshes from CAD, with exact ground truth, to measure and improve LLM-driven reconstruction in a fork of CNC Kitchen's ScanRuler.

This page is how people work here. Start with [README.md](README.md) for what the project is and which doc answers what. AI agents follow [AGENTS.md](AGENTS.md), which points back here for the details. The process is adapted from scouting-is-ez.

## Owner

| Who | GitHub | Role |
| --- | --- | --- |
| Zach Mckennedy | @ZachMckennedyFWig | Owner |

The owner makes every call marked "owner" in `docs/PLAN.md` and decides what merges. Questions, ideas and bugs go to the owner. A bug report names the dataset, the sample id, and what you saw. A realism report also needs the real scan it disagrees with (`WHAT-IS-A-BUG.md`, E1).

## Branches

| Branch | What goes there |
| --- | --- |
| `main` | Always green (`scripts/check.py` passes). Every change arrives by PR |
| `feat/…`, `fix/…`, `docs/…` | Work branches from `main`, PR back into it |

`main` only, by owner decision (PLAN §0, 2026-11-04): the tool runs locally, so there is no deploy branch.

## Try it locally

- **Generator:** `uv run synthscan procedural data/inputs/try -n 10`, then `uv run synthscan run data/inputs/try -d try -n 2`.
- **Scan Lab:** double-click `Scan Lab.bat` (it builds the UI if its sources changed, then serves on :8849), or `uv run synthscan serve`. For UI work, `Scan Lab (dev).bat` runs Vite with hot reload on :5173.
- **One sample under a debugger:** `synthscan.pipeline.generate_sample(part, index, profile, seed, out_dir, overrides={...})`. `overrides` pins any parameter, e.g. `{"registration": {"drift_mm": 0}}`.

## Test before you open a PR

There is no CI yet, so a PR is only as tested as its author made it.

**Once, to set up**, from the repo root:

```
uv sync
npm ci --prefix ui
```

**Before every PR:**

```
uv run python scripts/check.py
```

It runs every check once and prints a line each: `lint` (ruff), `format` (ruff format --check), `py` (every test) and `ui` (tsc and vite build). All four MUST pass. A failure prints its failing tests, and the whole output is in `data/check/<step>.log`: read it there instead of running again. `check.py py lint` runs only the steps you name while you fix something, but run all of it once before the PR.

```
ok   lint    All checks passed!  (0 s)
ok   format  34 files already formatted  (0 s)
ok   py      29 passed, 1 warning in 36.92s  (39 s)
ok   ui      built in 2.32s  (7 s)
```

**If you touched the simulator** (`scanner.py`, `meshing.py`, `profiles.py`, `randomness.py`), run the throughput benchmark in `docs/PLAN.md` §4.1 and add a row. Say whether existing seeds now produce different samples. If they do, bump `PROFILES_VERSION` when the change is to a range.

**If you touched what a profile produces** for realism reasons, attach the real-scan comparison: scanner, app version, settings, part, and the numbers (`WHAT-IS-A-BUG.md`, E1).

**If you touched the UI,** run it against the real backend and say what you clicked.

**Say what you ran.** Paste the `check.py` summary lines into the PR, plus anything else you ran, and what you skipped and why.

## Leave nothing for the reviewer to finish

1. **Docs move with code.** The on-disk format changes `docs/DATASET.md`; the HTTP API changes `docs/API.md` and `ui/src/lib/types.ts`; a new artifact or parameter changes the catalogue in `docs/SIMULATOR.md`; a new measured fact goes in `docs/PLAN.md` §4.
2. **No old way left next to the new one.** When you replace a command, a profile or a doc, remove or redirect the old one in the same PR.
3. **Every new parameter is recorded.** It lives in a profile spec (so it lands in `meta.json → params`), and it has a range with a source (research doc section, a real scan, or `[est]` with the reasoning).
4. **No placeholders for someone else to fill.**

## Make a change

1. Branch from `main`.
2. Make the change. Read `WHAT-IS-A-BUG.md` first if it's a fix.
3. Try it locally (above).
4. Run `scripts/check.py` (above), and the benchmark if it applies.
5. Go through "Leave nothing for the reviewer to finish".
6. Open a PR into `main` and fill in the template.

Feature PRs are squash merged. Commit and PR titles are a gitmoji (gitmoji.dev), a space, then an imperative summary, 72 characters or fewer.

| Gitmoji | For | Example |
| --- | --- | --- |
| 🐛 | A bug fix | `🐛 Keep the remnant skirt inside the contact outline` |
| ✨ | A new feature | `✨ Add a photogrammetry profile` |
| 🎯 | Realism (backed by a real scan) | `🎯 Match bore visibility depth to Raptor scans` |
| ⚡️ | Faster | `⚡️ Skip point gathering for TSDF-only samples` |
| ♻️ | Refactor, no behaviour change | `♻️ Share one RaycastingScene per session` |
| 🗃️ | Dataset format | `🗃️ Record per-face coverage in meta.json` |
| 💄 | How Scan Lab looks | `💄 Match the batch table to the design tokens` |
| ✅ | Tests only | `✅ Cover the hole filler on bow-tie rims` |
| 📝 | Docs | `📝 Document the export format` |
| 🔧 | Config | `🔧 Pin ruff rules` |
| ⬆️ | Upgrading a dependency | `⬆️ Upgrade Open3D` |
| 🔥 | Removing code or files | `🔥 Drop the legacy TSDF path` |

## Things that need the owner's OK first

- A new CAD source, or using one whose licence is unclear (`docs/research/cad-sources.md`).
- Changing a profile range, a distribution or the random draw order (it changes existing samples).
- Changing what a metric means, or how ground truth is made.
- The dataset format or the HTTP API (add fields; don't rename or remove them).
- What users see in Scan Lab: a name, a label, a layout or a default. Offer options and let the owner pick.
- A new dependency.
- Publishing a dataset anywhere.

## Licences, secrets and data

- `data/` is gitignored and stays that way. It holds multi-GB datasets and possibly licensed CAD.
- Never commit CAD, meshes, scans, renders or screenshots, and never commit API keys or `.env` files (a harness for M2 will need model API keys).
- McMaster-Carr CAD is private input only (PLAN §0).

## If AI helped

Any AI tool is fine. You're responsible for what you send, same as if you typed it.

- Say which tool you used and what it did, in the PR.
- End each commit it helped write with an `Assisted-by: <tool>` line, like `Assisted-by: Claude Code`. Name the tool, not the model, and never add a line claiming a person reviewed or tested it.
- You should be able to explain every line you send.

If you run an AI agent on this repo, point it at [AGENTS.md](AGENTS.md).
