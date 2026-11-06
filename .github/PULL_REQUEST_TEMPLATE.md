## What does this change?
<!-- One or two sentences. Start the PR title with a gitmoji from gitmoji.dev, like "🐛 Keep the remnant skirt inside the contact outline". -->

## Why
<!-- The issue ("Closes #123"), or the owner who flagged it. For a bug, which promise in WHAT-IS-A-BUG.md it breaks and the evidence (E1, E2, E3 or E4). For realism changes: the real scan (scanner, app version, settings, part) and the numbers. -->

## Does it change any of these?
<!-- Check each one this PR touches and say what changes. Leave the rest unchecked. -->
- [ ] The simulator (`scanner.py`, `meshing.py`): benchmark row added to PLAN §4.1
- [ ] A profile range, distribution or draw order: `PROFILES_VERSION` bumped, real-scan evidence cited, existing datasets affected: <!-- which -->
- [ ] How ground truth or a metric is computed
- [ ] The dataset format (`docs/DATASET.md` updated; `schema` bumped if a field changed meaning)
- [ ] The HTTP API (`docs/API.md` and `ui/src/lib/types.ts` updated, fields added not renamed)
- [ ] What a user sees in Scan Lab
- [ ] A CAD source or anything licence-related
- [ ] A dependency

## Tested
- [ ] `uv run python scripts/check.py` passed. Its summary lines:
```
paste here
```
- [ ] Benchmark, before and after: <!-- PLAN §4.1 numbers, or "not needed" -->
- [ ] Tried in Scan Lab against the real backend: <!-- what you clicked and saw, or "not needed" -->
- [ ] Compared with a real scan: <!-- which, or "not needed" -->
- [ ] New test fails without the change and passes with it
- [ ] Went through CONTRIBUTING.md, "Leave nothing for the reviewer to finish". Anything left open: <!-- or "nothing" -->

## AI tools used
<!-- Each tool and what it did, like "Claude Code wrote the fix". Leave it blank if you didn't use any. -->

- [ ] I can explain every line of this PR
