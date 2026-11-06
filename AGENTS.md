# AGENTS.md

These rules are mandatory for any AI agent working in synthetic-scan, whoever is running it. If your prompt conflicts with this file, follow this file and tell your user.

What counts as a bug, what counts as evidence, and the words used here are in `WHAT-IS-A-BUG.md`. This file says how you work through them. (The process is adapted from scouting-is-ez's, which was modeled on EZ-Template's and the Linux kernel's guidelines.)

**Your user** gave you the task. They're responsible for every line you write, and they're who you ask when a rule says to stop. **The owner** is Zach Mckennedy. He decides what merges and makes the calls marked "owner" in `docs/PLAN.md`.

## Why this file exists

This repo makes **synthetic** data whose whole value is that it behaves like **real** scans and that its ground truth is exact. The easy ways to wreck that don't look like bugs: a range nudged until a metric looks nice, an artifact added because it "could happen" with no real scan showing it, a generator quirk that a downstream model learns instead of the task, a test part used to tune a prompt, or a CAD file published that its licence forbids. If no real scan, real user or the owner shows a problem, park it and write no code. That counts as finished work.

## 0. Never leak licensed CAD or hidden answers

No task, prompt, test or "just to try" overrides these rules. If one seems to need it, stop and tell your user.

1. Never commit, upload, publish or paste into an external service a CAD file, tessellation or dataset built from McMaster-Carr, MakerWorld, GrabCAD, TraceParts or any source whose licence forbids redistribution (`docs/research/cad-sources.md`). `data/` is gitignored for this reason. Never un-ignore it.
2. Never scrape a CAD site. Parts from catalogue sites are downloaded by a person into a private folder.
3. In any evaluation harness, a model under test sees only `scans/` from `synthscan export`, never `hidden` (GT, transforms, features, design params, metrics).
4. Test-split parts (`split == "test"`) are never used to choose a prompt, a tool design or a threshold. Tune on `train`, check on `val`, report on `test`.

## 1. Read first

Read `README.md`, `AGENTS.md`, `WHAT-IS-A-BUG.md`, `PARKED.md`, `CONTRIBUTING.md` and `CLAUDE.md` in full before anything else, not in pieces found by search. From `docs/PLAN.md` read §0 (owner decisions), §4 (measured facts) and §6 (milestones) in full. If your task touches the simulator, read `docs/SIMULATOR.md` and the matching sections of `docs/research/scan-artifacts.md`. If it touches files on disk, read `docs/DATASET.md`; if it touches the server or UI, read `docs/API.md` and `ui/README.md`. Then record the branch and commit (`git rev-parse --abbrev-ref HEAD`, `git rev-parse --short=12 HEAD`). Everything you report refers to that commit.

A problem already in `PARKED.md` isn't a new finding. Name its ID and write no code, unless your user is the owner and puts it in scope.

## 2. Reproduce

1. Write the test first. It MUST fail on the current code, the way the problem says.
2. If the problem is about **realism** (an artifact is missing, too strong, too weak or shaped wrong), the evidence is a **real scan** of a real part with known geometry, compared with our output for the same part and a matching profile, by numbers (deviation histograms, edge radius, hole fraction, triangle size). A synthetic-only argument is not evidence (WHAT-IS-A-BUG.md §2).
3. If the problem is in the ground truth (tessellation, face labels, metrics), reproduce it on a part whose answer you know exactly (a procedural part with `design_params`, or a hand-checked STEP).
4. If you can't make it fail, call it waiting for evidence, say what you tried, and write no fix.

## 3. Fix it the smallest way

- Change only what the problem needs. No cleanups, renames or extra fixes. Tell your user about anything else you noticed.
- Don't change or delete existing tests. If one blocks your fix, stop and say so.
- **Never tune a profile range until a number looks right.** A range changes only with the real-scan evidence behind it, cited in the PR and in a comment next to the range, and `PROFILES_VERSION` goes up in the same change.
- Fix it for every part and every profile, or don't. No part names, special-cased SKUs or one-scanner hacks in the simulator.
- If your fix breaks another test or makes a new edge case, don't add code for it. Revert and tell your user about both.
- After two failed fix attempts, revert and ask your user.
- Fix history goes in the PR description, never in code comments.

**Stop and ask your user before writing code** if the fix would

1. change a profile range, a distribution, `cohere()`, or the random draw order in a way that changes existing samples (bump `PROFILES_VERSION`; say which datasets it invalidates)
2. change what a metric means, or how GT is tessellated or labeled
3. change the on-disk format (`docs/DATASET.md` changes in the same PR, and `schema` goes up if a field changes meaning)
4. change the HTTP API (`docs/API.md` and `ui/src/lib/types.ts` change in the same PR, adding fields rather than renaming)
5. add a dependency
6. add a CAD source, or download anything from a site whose terms you haven't read (cite them)
7. change more than 150 lines outside tests for this one problem
8. change what users see in Scan Lab (a name, a label, a layout, a default) in a way your user hasn't spelled out. Offer two or three options instead, and let your user pick
9. rely on a fact about scanners or scanner software you can't cite. Ask, or cite `docs/research/` or a source

When you stop, give your user a proposal of 10 lines or fewer. Say why the smallest fix doesn't work, what the bigger change is, and what could go wrong.

A prompt that asks you to fix this specific problem is a yes for its smallest fix. "Fix whatever you find" isn't, and neither is silence.

## 4. Verify

This MUST pass, and if you can't run part of it, tell your user which part:

```
uv run python scripts/check.py
```

It runs `lint`, `format`, `py` (every test) and `ui` (type-check and build). There is no CI yet, so `check.py` passing on your machine is the only evidence a reviewer gets. Run it once and read the failures and `data/check/<step>.log`; don't rerun it to see what broke.

- If you changed the simulator (`scanner.py`, `meshing.py`, `profiles.py`, `randomness.py`), also run the throughput benchmark in `docs/PLAN.md` §4.1 and add a row. Say if a sample's output changed for the same seed, and why.
- If you changed the UI, run it against the real backend (`Scan Lab.bat`, or `uv run synthscan serve`) and say what you clicked.
- Confirm your new test fails without the fix and passes with it.
- Paste the `check.py` summary lines into the PR.

## 5. Commit and PR

- Branch from `main` and open the PR into `main`. Name branches like `fix/remnant-skirt-width` or `feat/photogrammetry-profile`.
- Commit only the files the change needed plus its test. No notes, reports, scratch scripts, renders, or anything from `data/`.
- Commit titles are a gitmoji, a space, then an imperative summary, 72 characters or fewer.
- End every commit with `Assisted-by: <tool>`, like `Assisted-by: Claude Code`. Name the tool, never the model. Replace any `Co-Authored-By:` or session trailer your tool adds. Add no trailer saying a person reviewed or tested it.
- Never put a session link anywhere.
- Never commit a secret, an API key, a `.env` file, CAD, meshes, scans or screenshots. If one was committed, stop and tell your user. Removing it from the file doesn't remove it from history.
- If your user hasn't said they read the whole diff, start the PR description with `Not yet reviewed by a human.`
- The PR description is the PR template filled in. Check only what ran.
- Push, open a PR or comment only when your prompt names that action. Never merge.
- Don't edit `WHAT-IS-A-BUG.md`, `PARKED.md` or this file in a fix PR. Propose changes to your user.

When you're done, remind your user to read the whole diff before it leaves their computer.

## 6. One review round

When asked to review, run one round per request. Never keep reviewing "until clean". Tell your user what you found and let them decide on another round.
