# The ScanRuler bench: running models and grading them

How synthetic scans become measured reconstruction attempts (milestone M2 in
PLAN §6). The bench runs in the ScanRuler fork. The grader runs here, because
the hidden answers and the metrics are here.

| Part | Where | What it does |
|---|---|---|
| `synthscan export` | this repo | Writes `scans/`, `gt/` and `tasks.jsonl` (DATASET.md) |
| `bench/run.mjs` | the fork, `D:\ScanRuler` | Runs N isolated ScanRuler instances in parallel, one model attempt each |
| `synthscan grade` | this repo, `grade.py` | Scores each attempt against the hidden GT and summarises the run |

```
uv run synthscan export smoke data/exports/smoke [--split test]
cd D:\ScanRuler && npm ci && npm ci --prefix mcp && npm run build      # once, and after every app change
node bench/run.mjs --tasks D:/synthetic-scan/data/exports/smoke/tasks.jsonl --model claude-haiku-5-5 --concurrency 3 --name NAME
uv run synthscan grade data/exports/smoke/tasks.jsonl %LOCALAPPDATA%/scanruler-bench/runs/NAME
```

## One job

1. The runner reads only `id`, `scan` and `units` from the task. The scan is
   copied to `jobs/<hash>/scan.stl`. The folder name is a hash, because a model
   can see the scan's folder path, and task ids contain part names
   ("plate", "bushing").
2. A **holder** `scanruler-mcp` takes a free port with a fresh token, serves the
   built app (`--serve dist`) and writes a trace.
3. Headless Chrome opens the app with the pairing link, using the same
   localStorage presets as upstream's e2e (`askstlunits=0`, betas on, support
   card off, agent-data warning accepted). The holder opens the scan, so the
   model starts the way a person's agent does: the scan is already open in the
   tab.
4. The model's client starts its own `scanruler-mcp` on the same port and
   token. That copy relays every call into the same tab (upstream `relay.js`).
   The model works until it stops, hits the budget or times out.
5. The holder then collects whatever is there, whether or not the model
   exported anything, into `out/`:
   - the feature list
   - `final.step` (`reverse_export_step`, verified)
   - the scan as a PLY in the frame the session ended in
   - `scan_qa`
   - `session_state`
   - the `.scanruler` project, which can be opened in ScanRuler to see exactly what the model built

   Everything about the run goes in `result.json`: status, tool calls and
   errors, turns, peak context, cost, wall time and the final message.

Measured: a job is ready for the model about 3 s after it starts.

### Isolation (what keeps a run honest)

- **No answers in reach.** The runner never writes `hidden` anywhere a job can
  see. `scanruler_read` and `scanruler_files` only reach the scan's folder
  (upstream `mcp.js`), and that folder holds only `scan.stl` until the model
  has finished.
- **Claude Code client** (`bench/lib/claude-code.mjs`):
  - `--tools ""` turns off every built-in tool (no Bash, Read or Write), so the
    model has ScanRuler's tools and nothing else.
  - `--strict-mcp-config` loads only this job's server.
  - `--setting-sources local` loads none of the user's settings, hooks or plugins.
  - The job folder sits outside any repository, so Claude Code finds no
    CLAUDE.md or AGENTS.md in a parent folder.
- **`MCP_CONNECTION_NONBLOCKING=false` is required.** In print mode Claude Code
  otherwise connects `--mcp-config` servers in the background. The first turn
  then starts with no tools, and the model makes up tool calls as text
  (measured 2026-11-04).

## Clients and limits

- **`claude-code`**: `claude -p` with
  `--output-format stream-json`. It uses the machine's `claude` login. On a
  claude.ai subscription no API key is needed, and the reported dollars are
  **notional** (API prices). What actually limits runs is the subscription's
  usage limit.
- **Limits per job:** `--timeout-min` (default 45), `--budget-usd` (default 10,
  notional, enforced by Claude Code) and an optional `--effort`.
- **Model ids:** pass full ids. `--model haiku` resolved to Haiku 4.5, not
  `claude-haiku-5-5`.
- **`openai`** (`bench/lib/openai.mjs`): GPT-6 Luna, or any OpenAI-compatible
  API (`OPENAI_BASE_URL`). OpenAI's hosted `mcp` tool only reaches remote
  servers, so this client runs its own loop:
  1. Start the job's relaying `scanruler-mcp` and list its tools.
  2. Offer them as function tools to the Responses API, with
     `previous_response_id` keeping the conversation server-side.
  3. Run each call through MCP and send the text back. Any pictures go back
     in a user message after the outputs.

  The key comes from `OPENAI_API_KEY` or `D:\ScanRuler\bench\.env.local`
  (gitignored, one `OPENAI_API_KEY=...` line). It is never written to a
  transcript or passed to the ScanRuler server. Prices for computing cost are
  in `PRICES`, taken from third-party listings, so check them against OpenAI.
  Tested against a mock Responses endpoint, then run on the owner's key.
- **`script`** (`bench/lib/script.mjs`): no model. It runs a fixed list of calls
  (`BENCH_SCRIPT=calls.json`) through the job's server and logs each answer. Use it to
  probe what the tools answer on real scans, at no token cost.
- **`--tools small`** (fork, `mcp/src/small.js`): lists the 8 page tools a scan-to-CAD
  build needs plus `scanruler_tools`, `scanruler_batch` and `scanruler_wait`. That is about
  7.5 k tokens of definitions, against 91 k for full. Pair it with
  `--prompt bench/prompts/small.md`, the short process guide.

### Context cost of the tool surface (measured 2026-11-04, Haiku 5.5)

Tokens in context at the first turn, before any work:

| Client setup | Tokens |
|---|---|
| Claude Code, no MCP | 8.2 k |
| + ScanRuler `--tools full` (147 tools) | 129.5 k |
| + ScanRuler `--tools compact` | 24.9 k |
| compact + a one-line system prompt instead of Claude Code's | 16.9 k |

With full tools, Haiku spends about two thirds of its 200 k window on tool
schemas before it reads the guides (~30 k more). This is the first M3 target
(research/scanruler.md §5.2).

## Grading (`grade.py`)

**Frames, without fitting the model to the answer.** Bodies are built in the
frame the session ends in, which changes when the model aligns the scan. The
grader handles that in two steps:

1. It registers the exported cloud to `scan.stl`. They are the same points, so
   the fit is exact (test: frame RMS < 1 µm).
2. It applies the generator's `scan_to_cad`.

That puts the model in the CAD frame as honestly as the scan itself.
`scan_to_cad` keeps the scan's deliberate scale error, so a perfect copy of the
scan is off by that error, as it would be with a real scanner.

**Two views:**
- `posed`: chamfer, Hausdorff and p95 model→GT, GT→model p95, coverage@0.5 mm.
- `bestfit`: the same after a rigid ICP onto the GT. The shift says how much of
  the error is placement.

**Bores.** Concave cylinders from the model's STEP and the GT STEP, using the
same labeller (`parts._load_step`), grouped by axis and radius and wrapping
≥ 270°. Matched by axis line (≤ 1 mm) and radius (Hungarian). Diameter error
per pair.

**Faces: design intent.** The grader samples the GT surface (60 k points) and
finds the model's nearest face under each point. A point agrees when that face
is the same kind of analytic surface, with the same size, within 0.2 mm:
- plane normal within 2°
- cylinder, sphere or fillet (torus minor) radius within max(0.1 mm, 3 %)
- cone half-angle within 2°

`agreement` is the agreeing share of GT area. The output also breaks it down
by GT face type and lists the worst faces ("4.4 % of GT: cylinder r4.5
(concave), model has cylinder r4.23"). A fillet where the part has a chamfer,
an unsnapped radius or a missing pocket all show up here, even when the
distances look good.

**Scan reference.** `scan_reference` holds the scan's own chamfer, p95,
Hausdorff and coverage against GT: what a perfect copy of the scan would score.

**Success** ("as close to the real object as possible", owner, PLAN §0;
the numbers are proposed defaults in `Thresholds`). All of these must hold:
- a body was built
- posed chamfer ≤ 0.25 mm
- posed p95 ≤ 0.5 mm
- face agreement ≥ 90 %
- every GT bore matched with |Δd| ≤ 0.2 mm, and no extra bores

The thresholds are CLI flags. Changing the defaults changes what "success"
means, so it needs the owner.

**Output:** `grades.jsonl`, one row per job (status, success, why, posed and
bestfit metrics, faces, bores, scan reference, tool calls, peak context, cost,
wall time, profile, artifacts, `scan_qa` rims). `grades-summary.json` holds the same per model,
with success broken down by profile, by open versus closed scan
(`scan_qa` rims: ScanRuler routes these differently) and by artifact.

## Grading the dossier (no model)

The fork's `scan.dossier` is the deterministic part summary a small model starts from
(`D:\ScanRuler\FORK.md`). The bench collects it into `out/dossier.json` for every job,
whatever the client. `--client none` runs no model at all, so this costs no tokens:

```
node bench/run.mjs --client none --app dist-dev --tasks <export>/tasks.jsonl --model none --name dossier-vN
uv run synthscan grade <export>/tasks.jsonl <runs>/dossier-vN
```

`grade_dossier` maps the dossier's part frame (`frame.to_part`) to CAD, the same way as a
model, and scores:
- **Bores:** found (matched by axis line), invented, the measured Ø error, whether the
  first nominal candidate is the true Ø, and every pair.
- **Planes:** GT planes of at least 1 % of the area matched by a dossier face (normal
  within 2°, offset within the scan's own p95 or 0.3 mm, whichever is larger).
- **Archetype:** `extrude` / `revolve` against the procedural part's kind.
- **Size:** about one token per 4 characters of the answer the model would see.

**Only what the scan shows counts.** A GT face is "in the scan" when at least 30 % of it is
within the scan's p95 (at least 0.5 mm) of scan surface; for a bore, 10 % of its wall, since
a deep bore's wall is barely scanned even when its ends are. The rest are reported as
`gt_not_in_scan`. An inside corner the scanner never saw is the scan's gap, not a dossier miss.

## Failure analysis (rule 6)

Every failed job gets a written root cause from its trace before anything
changes. Per job, read:
- `transcript.jsonl`: every model turn and tool result
- `trace/*.jsonl`: ScanRuler's per-call log, with arguments
- `out/final.scanruler`: open it in ScanRuler
- `result.json`

Root causes go in the run folder as `analysis.md` and are summarised in the PR
that changes the tool.
