# Agent tooling for cheap-model scan-to-CAD: research notes

Web research done 2026-11-04 for the ScanRuler fork (see [scanruler.md](scanruler.md)). Nothing
was installed or run. Every claim has a URL next to it.

**Markers.** **[P]** means I read it in the primary source (paper, official docs, vendor's own
page). **[S]** means I only found it in secondary coverage, or the primary source didn't confirm
the number. Treat [S] as a lead to check, not a fact. Numbers are the authors' own unless noted.
None has been reproduced independently.

---

## 0. The most actionable findings

1. **Coarse tools plus a 7B model can match GPT-4o.** ToolCAD gives the model just **6** FreeCAD
   MCP tools (set coordinate system, complex sketch, simple sketch, boolean, multi-fuse, extrude
   face). An RL-trained Qwen2.5-7B reaches 63.9 % average success, against 62.7 % for GPT-4o
   with ReAct. It also uses 5,178 tokens per tool call, where CAD-Assistant (GPT-4o) uses 30,802
   [P] <https://arxiv.org/html/2604.07960v2>. This is a text-to-CAD result, not scan-to-CAD, and
   the 7B model was RL-trained. Untrained Qwen2.5-72B reaches only 36–43 % on the same 6 tools.
2. **Anthropic says selection accuracy drops once a model sees more than 30–50 tools.** On-demand
   loading (tool search, `defer_loading`) cuts definition tokens by more than 85 %. Tool search
   is supported on **Haiku 4.5 and Haiku 5.5** [P]
   <https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool>. OpenAI's
   `tool_search` needs gpt-5.4 or later [P]
   <https://developers.openai.com/api/docs/guides/tools-tool-search>. Its availability on cheap
   OpenAI models (mini/nano) is unverified.
3. **Code mode shrinks huge APIs to a couple of tools.** Cloudflare exposes more than 2,500
   endpoints through `search()` + `execute()` in about 1,000 tokens, against 1.17 M for one tool
   per endpoint [P] <https://blog.cloudflare.com/code-mode-mcp/>. Anthropic reports 150k → 2k
   tokens on one demo task [P] <https://www.anthropic.com/engineering/code-execution-with-mcp>.
   Neither source reports **accuracy**, and neither tested small models.
4. **Numeric verification beat visual verification.** In CADCodeVerify, VLM image feedback improved
   GPT-4 point-cloud distance from 0.155 to 0.127. A geometric solver did better (0.103), but it
   needs the ground-truth shape [P] <https://arxiv.org/html/2410.05340v2>. In reverse engineering
   the **scan is the reference**, so we get the "geometric solver" style of feedback for free:
   deviation maps and per-face residuals.
5. **The first refinement loop does most of the work.** In Query2CAD, GPT-4 Turbo went
   53.6 → 73.2 → 76.7 → 76.7 % and GPT-3.5 Turbo went 32.7 → 44.8 → 51.7 → 53.4 % over three
   refinement rounds [P] <https://arxiv.org/html/2406.00144v1>.
6. **A "summary as JSON" pattern already exists.** CAD-Assistant's Sketch and Solid Recognizers
   return JSON summaries of geometry and constraints, and a Cross-section Extract tool handles
   scans. Swapping the GPT-4o planner for GPT-4o-mini drops SGP-Bench QA from 0.791/0.857 to
   0.614/0.783 (2D/3D) [P] <https://arxiv.org/html/2412.13810v3>.
7. **Split the decisions.** Img2CAD lets a VLM pick the **discrete structure** and a separate
   regressor fill in the **continuous values** [S]
   <https://arxiv.org/html/2408.01437v2>. The same split fits a "dossier the model confirms":
   the model picks between candidates and code fits the numbers.
8. **Deterministic primitive extraction is mature for planes, cylinders, cones and spheres.**
   Fillets, chamfers, freeform surfaces and feature *ordering* are where every pipeline gets
   weak. Point2CAD's residuals grow 1.6–1.8× when it uses a learned segmentation instead of the
   ground-truth one [P] <https://arxiv.org/html/2312.04962>. Commercial auto-surfacing gives a
   "dumb solid" with no feature tree [S]
   <https://hawkridgesys.com/blog/hybrid-modeling-with-geomagic-design-x>.

---

## 1. How LLM agents drive CAD tools

| System | Kernel | Tool surface | Model(s) | Token control | Small-model evidence |
|---|---|---|---|---|---|
| blender-mcp (ahujasid, ~33k★) | Blender | **9** tools, including `execute_blender_code`, `get_scene_info`, `look` | any MCP client | `get_scene_info` returns a compact summary with fields you choose, plus drill-down via `root`/`query` | none [P] <https://github.com/ahujasid/blender-mcp> |
| freecad-mcp (neka-nat, ~3.2k★) | FreeCAD | **17** tools: CRUD on objects, `execute_code` (sync/async/headless), `get_view`, parts library, FEM | any | `include_screenshot=false` per call, `--only-text-feedback` flag | none [P] <https://github.com/neka-nat/freecad-mcp/blob/main/docs/tools.md> |
| build123d-mcp | build123d | `execute`, `validate`, `find_candidates` (recognised features such as holes), `interface_features`, `edit_feature`, `compare`, `install_skill`, and more; full count not stated | any | workflow guidance loaded on demand as a "skill", not a long prompt | README: on CADGenBench, the same model scores 0.360 → 0.457 with the server and validity rises from 88 → 100 % [P, self-reported] <https://github.com/pzfreo/build123d-mcp> |
| Fusion 360 MCPs (community) | Fusion | 51 / 81 / "84+" tools across three projects | any | `execute_python` as an escape hatch | none [S] <https://glama.ai/mcp/servers/prim-design/fusion-mcp>, <https://glama.ai/mcp/servers/@faust-machines/fusion360-mcp-server> |
| Onshape FeatureScript MCP (official, Labs) | Onshape | the agent writes FeatureScript, checks errors and inspects geometry; has persistent "memory" of past errors | any | the model writes code instead of calling many tools | none [S] <https://www.onshape.com/en/blog/get-started-featurescript-mcp-server> |
| onshape-mcp (community) | Onshape UI via Playwright | 43 tools | vision LLM | screenshots | none [S] <https://pypi.org/project/onshape-mcp/> |
| OpenSCAD MCPs | OpenSCAD | compile + render PNG/STL | any | one code tool | none [S] <https://pypi.org/project/openscad-mcp-server/> |
| Zoo Zookeeper / Text-to-CAD | Zoo (KCL) | agent writes KCL; ML API | proprietary | n/a | none published; vendor claims only [S] <https://zoo.dev/press/zoo-introduces-zookeeper> |
| **CAD-Assistant** (ICCV'25) | FreeCAD in a Python interpreter | 7 tool groups: Python, FreeCAD API, Sketch Parameterizer, Sketch Recognizer (JSON), Solid Recognizer (JSON + 4 renders), Constraint Checker, Cross-section Extract | GPT-4o, GPT-4 Turbo, GPT-4o-mini | average **11k–31k input tokens** per request ($0.03–0.09) | 4o-mini: 0.614 / 0.783 vs 4o 0.791 / 0.857 on SGP-Bench [P] <https://arxiv.org/html/2412.13810v3> |
| **ToolCAD** (2026) | FreeCAD MCP | **6** coarse tools | Qwen2.5-7B, Qwen3-8B (RL), compared with GPT-4o, Qwen-72B/235B | 16k context, 5.2k tokens per call | 7B RL 63.9 % vs GPT-4o ReAct 62.7 %; IR 1.51 vs 9.12 [P] <https://arxiv.org/html/2604.07960v2> |
| Query2CAD | FreeCAD macros | the model writes a macro; error and caption feedback | GPT-3.5 / GPT-4 Turbo | 3 refinement rounds | GPT-3.5 Turbo 53.4 % vs GPT-4 Turbo 76.7 % after refinement; only **57 queries** [P] <https://arxiv.org/html/2406.00144v1> |
| CADCodeVerify (ICLR'25) | CadQuery | code, then VLM self-questions about 4 renders | GPT-4, Gemini 1.5 Flash, CodeLlama-70B | n/a | CodeLlama compile rate 67 → 73.5 % [P] <https://arxiv.org/html/2410.05340v2> |
| CADialogue (CAD journal 2026) | code-generating | text/speech/image/selection inputs; caches validated designs | general LLM (swappable) | design cache gives more than 85.71 % speed-up on repeats | 95.71 % success over 70+10 tasks; 91.43 % text-only [S, abstract via catalogue] <https://portalcientific.uji.es/documentos/693d97c32dbbec5f17a8b71c> |

**Fine-tuned small models that write CAD code (no agent loop):**

- **CAD-Recode:** Qwen2-1.5B plus a point projector, point cloud → CadQuery. It samples 10
  candidates and keeps the lowest Chamfer distance. On **CC3D real scans** it gets IoU 74.2 %,
  median CD 0.31, invalid ratio 0.3 %. CAD-SIGNet gets 42.6 % IoU there. Shrinking to
  Qwen2-0.5B costs about 2 IoU points (CC3D 72.6 vs 74.2) [P]
  <https://arxiv.org/html/2412.14042>. The model only sees **256 points**, and its operations are
  sketch-extrude only.
- **cadrille:** Qwen2-VL-2B, SFT then online RL. CC3D IoU goes 61.8 % (SFT) → 67.9 % (RL), and
  the invalid ratio 5.9 → 0.2 % [P] <https://arxiv.org/html/2505.22914v3>. Note the CC3D numbers
  are in a different table/protocol from CAD-Recode's 74.2.
- **Text-to-CadQuery:** fine-tunes six models from 124M to 7B. Best top-1 exact match is 69.3 %
  [S] <https://arxiv.org/abs/2505.06507>.
- **CAD-Coder** (Qwen2.5-7B, SFT+GRPO with a Chamfer reward) [S]
  <https://huggingface.co/gudo7208/CAD-Coder/blob/main/README.md>. **BlenderLLM** (Qwen2.5-Coder-7B)
  [S] <https://arxiv.org/html/2412.14203>.

**Takeaways for us.** Two tool-surface shapes dominate. Either (a) one "run code" tool plus a few
inspectors (blender-mcp, freecad-mcp, Onshape, OpenSCAD), or (b) a handful of coarse, high-level
modelling tools (ToolCAD with 6, build123d-mcp). Nobody in this survey ships ~150 fine-grained tools
together with small models. The only published small-model *agent* wins (ToolCAD) came with RL
training on the tool surface itself. Prompted, untrained small models consistently trail
(CAD-Assistant with 4o-mini, Query2CAD with GPT-3.5, CADCodeVerify with CodeLlama). This survey
found no published result for Haiku or DeepSeek on any CAD agent task.

---

## 2. Techniques for large tool surfaces

| Technique | What it is | Reported effect | Caveat |
|---|---|---|---|
| **Tool search / `defer_loading`** (Anthropic) | Every definition is still sent, but deferred ones stay out of context until a regex or BM25 search returns `tool_reference`s (5 per search by default). Keep the 3–5 most-used tools non-deferred. The cache prefix is preserved. | 55k tokens of definitions (58 tools) → about 8.7k; "over 85 %" reduction. Internal MCP eval: Opus 4 49 → 74 %, Opus 4.5 79.5 → 88.1 % [P] <https://www.anthropic.com/engineering/advanced-tool-use> | Accuracy numbers are frontier models on Anthropic's internal eval. The docs say it's not worth it for fewer than 10 tools [P] <https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool> |
| **Tool search** (OpenAI) | `defer_loading` on functions, namespaces or a whole MCP server | no numbers [P] <https://developers.openai.com/api/docs/guides/tools-tool-search> | gpt-5.4 or later only |
| **Code execution with MCP** (Anthropic) | Tools become files in a code tree (`servers/x/tool.ts`), or `search_tools(detail=name\|desc\|full)`. The model writes code; intermediate data stays in the sandbox. | 150k → 2k tokens on one Drive → Salesforce demo (98.7 %) [P] <https://www.anthropic.com/engineering/code-execution-with-mcp> | One anecdotal task. Needs a sandbox. No accuracy number. |
| **Programmatic tool calling** (Anthropic) | Claude writes code that calls tools in a container | 43,588 → 27,297 tokens (−37 %). GIA 46.5 → 51.2 % [P] <https://www.anthropic.com/engineering/advanced-tool-use> | Frontier models |
| **Code Mode** (Cloudflare) | MCP schema → TypeScript API; one `execute` tool in a V8 isolate | 2,500+ endpoints in about 1k tokens vs 1.17M [P] <https://blog.cloudflare.com/code-mode-mcp/>. Argues models write code better than tool calls because of training data [P] <https://blog.cloudflare.com/code-mode/> | No accuracy data at all |
| **Tool use examples** | 1–5 `input_examples` per tool | Complex-parameter accuracy 72 → 90 % [P] <https://www.anthropic.com/engineering/advanced-tool-use> | Costs tokens per tool |
| **Skills (progressive disclosure)** | Only name + description sit in context; the SKILL.md body loads on demand, extra files later; scripts run without being loaded | No numbers in Anthropic's post [P] <https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills>. "~100 tokens per skill" and "<5k body" come from secondary sources [S] | |
| **Consolidated tools + `response_format`** | One `schedule_event` instead of list+list+create. Return names, not UUIDs. Offer a concise/detailed enum. | Concise response 72 vs detailed 206 tokens. Claude Code caps tool responses at 25k tokens by default [P] <https://www.anthropic.com/engineering/writing-tools-for-agents> | |
| **RAG-MCP** (retrieve, then inject one server) | vector retrieval over tool descriptions | Selection accuracy 13.62 → 43.13 %; prompt tokens 2,134 → 1,084 [S] <https://arxiv.org/html/2505.03275v1> | Not reproduced. Precision falls at thousands of tools. |
| **Less-is-More** (edge devices) | offline tool hierarchy, then pass only a subset | Up to 70 % less execution time and 40 % less power on small local models (BFCL) [S] <https://arxiv.org/html/2411.15399v1> | |
| **MCP protocol hooks** | `listChanged` + `notifications/tools/list_changed` let a server swap its tool list per phase. `outputSchema`/`structuredContent` support typed compact results. | spec only [P] <https://modelcontextprotocol.io/specification/2025-06-18/server/tools> | Client support for live list changes varies (not checked) |

**Tool count vs. small models (anecdotal).** Speakeasy says Llama 3.1 8B succeeds at 19 tools and
fails at 46 [S] <https://www.speakeasy.com/mcp/tool-design/less-is-more>. HumanMCP reports roughly
a 10-point drop going from 10 to 100 tools [S] <https://arxiv.org/pdf/2602.23367>; the abstract
page doesn't show it. Treat both as the right direction with unverified magnitudes.

**ScanRuler already has part of this.** `--tools compact` comes with a `scanruler_tools` meta-tool
that returns up to 20 full definitions ([scanruler.md](scanruler.md) §2). What it doesn't have is
consolidated, high-level tools or a precomputed summary of the part.

---

## 3. Deterministic scan-to-CAD pipelines (candidate "part dossier" sources)

### 3.1 Classical, non-learned

- **Efficient RANSAC** (Schnabel, Wahl, Klein 2007) finds planes, spheres, cylinders, cones and
  tori. **CGAL Shape Detection** implements it plus **Region Growing** (Lafarge & Mallet), with
  parameters `epsilon`, `normal_threshold` and `probability` [P]
  <https://doc.cgal.org/latest/Shape_detection/>. **CGAL's SWIG Python bindings don't wrap
  Shape_detection** [P] <https://github.com/CGAL/cgal-swig-bindings/wiki/Package_wrappers_available>,
  so from Python it needs a small C++ shim or a subprocess.
- **Open3D** (already a dependency here) has `segment_plane` (RANSAC, one plane per call) and
  `detect_planar_patches` (robust statistics, returns oriented bounding boxes) [P]
  <https://www.open3d.org/docs/latest/tutorial/geometry/python_interface.html>. It has no
  cylinder fitting. One user reports `detect_planar_patches` finding nothing on an STL cube until
  tuned [P] <https://www.Github.com/isl-org/Open3D/discussions/6233>.
- **pyransac3d** is NumPy-only and does Plane, Cylinder (centre, axis, radius, inliers), Sphere,
  Cuboid, Circle and Line. Last activity was around 2023 [S] <https://github.com/leomariga/pyRANSAC-3D/>.
  **PrimitivesFittingLib** (C++/pybind, Linux build) does plane, sphere and cylinder [S].
- **Mesh region growing** (normal/curvature criteria) is the textbook approach for planar and
  cylindrical features on meshes [S] <https://pubs.kist.re.kr/handle/201004/139573>. We have
  triangle meshes with normals, so region growing on the mesh is a cheap first pass before RANSAC
  per region. *(Inference, not tested.)*
- FreeCAD's Reverse Engineering workbench (plane, cylinder and sphere fit, segmentation) exists,
  but its wiki blocked fetching. **Unverified.**

### 3.2 Learned segmentation + fitting (trained on ABC CAD, mostly synthetic)

- **ParSeNet:** ABCParts segmentation mIoU 81.2 % vs SPFN 69.0 % [S]
  <https://arxiv.org/pdf/2003.12181>.
- **HPNet:** 91.3 % Seg-IoU vs ParSeNet 80.9 % on ANSI [S]. Very sensitive to point count [S]
  <https://arxiv.org/html/2307.04013v1>.
- **SED-Net:** no noise-robustness numbers found. **Unverified.**
- **Point2CAD** (CVPR'24, code at github.com/YujiaLiu76/point2cad): segment, then fit
  plane/sphere/cylinder/cone/INR-freeform per cluster, then intersect surfaces to get edges and
  corners. Residual error is 0.011 with GT segmentation, 0.018 with ParSeNet, 0.020 with HPNet. The
  authors say it is "sensitive to the quality of the point cloud segmentation". Noise is tested
  only synthetically, and P-coverage "drops notably" [P] <https://arxiv.org/html/2312.04962>.
  **Lesson:** the fitting stage is reliable; segmentation is the weak link.

### 3.3 Sketch-and-extrude recovery

- **Point2Cyl** (supervised), **ExtrudeNet** and **SECAD-Net** (self-supervised) all use SDF
  sketches. They're described as "less editable" and their profiles come out curved instead of
  sharp [S] <https://arxiv.org/html/2505.02043v3>. SECAD-Net reports 4.30 primitives vs
  ExtrudeNet's 14.46 on ABC, self-reported [S] <https://ar5iv.labs.arxiv.org/html/2303.10613>. On
  DeepCAD, Point2Cyl's IoU is 73.8 % vs CAD-Recode's 92.0 % [P] <https://arxiv.org/html/2412.14042>.
- **Point2Primitive** predicts explicit sketch primitives directly. It isn't LLM-based [S]
  <https://arxiv.org/html/2505.02043v3>.
- **CADFit** (2026) fits extrude, revolve, fillet and chamfer incrementally from a mesh using IoU
  feedback, with no LLM. The abstract claims SOTA but gives no numbers [P]
  <https://arxiv.org/abs/2605.01171>. This is the closest published analogue to a deterministic
  dossier builder and worth reading in full.

### 3.4 Commercial tools (no independent accuracy data found)

- **Geomagic Design X.** *Auto Segment* groups adjacent triangles by curvature into regions that are
  labelled plane, cylinder, cone and so on [S] <https://cimquest-inc.com/?p=15076>. A cylinder is
  extracted from a region with "Solid Primitive" [S]. *Auto Surface* wraps the part in 4-sided
  NURBS patches and gives a **dumb solid** with no tree [S]
  <https://hawkridgesys.com/blog/hybrid-modeling-with-geomagic-design-x>. It "may not replicate
  the mesh curvature precisely enough and sharp corners could be smoothed" [S]
  <https://rangevision.com/en/application/examples/helpful-articles/geomagic-design-x-reverse-engineering-of-organic-forms-3d-scan-processing/>.
  *Auto Sketch* fits lines, arcs and circles to section polylines [S]
  <https://www.goengineer.com/en-us/blog/geomagic-design-x-features-and-tutorials>. Automatic
  regions are a Pro-tier feature [S]. The verification step is the Accuracy Analyzer (deviation
  to the scan).
- **QuickSurface / Revopoint Revo Design** (which runs on QuickSurface) extracts planes,
  cylinders, cones, spheres and symmetry planes, constrains them (perpendicular, parallel,
  coincident), fits freeform surfaces and shows a live deviation map [S]
  <https://www.revopoint3d.com/pages/revodesign>, <https://novedge.com/products/quicksurface>.
- **Creality:** found nothing on its recommended scan-to-CAD workflow. **Unverified.**

**What seems reliable vs. what fails (synthesis; the sources above are qualitative):**

| Reliable | Weak |
|---|---|
| Large planes; cylinders and holes with enough coverage; coaxial and parallel relations; extrusion direction from dominant plane normals; a symmetry plane (QuickSurface/Design X expose it as a tool) | fillets and chamfers (smoothed edges on scans; CC3D results drop: CAD-Recode IoU 92 → 74 %); small holes and blind features (occlusion); freeform surfaces (all methods fall back to NURBS or INR); **segmentation boundaries**; **feature order / design intent** (every commercial tool leaves it to the human) |

---

## 4. LLMs in the loop for scan → CAD specifically

- **CAD-Assistant** is the only agent found that takes a **3D scan** as input. It runs **Cross-section
  Extract** (mesh → 2D section images), parameterizes the sketch, then builds in FreeCAD. The paper
  shows this only qualitatively, with **no scan-reconstruction metrics** [P]
  <https://arxiv.org/html/2412.13810v3>.
- **CAD-Recode → GPT-4o:** feeding the recovered *code* to GPT-4o lifts CAD-QA to 76.5 %, against
  63.2 % via CAD-SIGNet and 42.3 % for PointLLM [P] <https://arxiv.org/html/2412.14042>. A compact,
  symbolic intermediate form helps a general LLM reason about a scan much more than raw points do.
- **Img2CAD** splits VLM-chosen discrete structure from regressed continuous values. v1 used GPT-4V,
  v2 a fine-tuned Llama 3.2 [S] <https://arxiv.org/html/2408.01437v2>.
- **PrimitiveCAD** (Oct 2026) uses primitive-aware point tokenization, then an LLM with SFT+RL. It
  reports DeepCAD/Fusion360 only and no real scans in the abstract [P]
  <https://arxiv.org/abs/2610.08698>.
- **No published work** found where a *prompted* small model (Haiku-class, GPT-mini-class,
  DeepSeek) does scan → parametric CAD with a structured dossier. Every small-model success here
  is a fine-tuned or RL-trained model (CAD-Recode 1.5B, cadrille 2B, ToolCAD 7B). That gap is our
  opportunity, and also the risk.

---

## 5. Implications for the fork (my inferences, for the owner to decide; not findings)

1. **Dossier first, model confirms.** Precompute per-region primitives (Open3D normals → mesh
   region growing → per-region LSQ fit of plane/cylinder/cone; CGAL Efficient RANSAC as a later
   option), axis clusters, coaxial/parallel/perpendicular groups, hole lists with nominal-size
   snapping, symmetry-plane candidates, and extrude/revolve candidates with section polylines.
   Return them as a compact, ID-indexed JSON (short IDs, not UUIDs, per Anthropic's guidance). The
   model picks among candidates (the discrete choice) and code fits the numbers (Img2CAD split).
2. **Six to ten coarse tools, with no fine-grained tools in context.** ToolCAD is the evidence
   that a small model can drive about 6 tools. Fine-grained ScanRuler tools can stay behind
   `defer_loading` or `listChanged` phases for the rare cases.
3. **Verification by numbers, not pictures.** Each build step returns the deviation against the
   scan per dossier region (RMS, % of points within tolerance, worst region). CADCodeVerify's
   strongest feedback was geometric, and we have the reference for free.
4. **Budget for one or two refinement rounds.** Query2CAD's gain flattens after round 1–2.
5. **Code mode is unproven for small models.** All published savings are frontier-model token
   counts with no accuracy. Test it as an arm in the harness; don't adopt it on faith.
6. **Measure every claim on the harness** (CLAUDE.md rule 4): tokens/run, success, deviation,
   calls, per model, tuned on `train` only (AGENTS.md §0.4).

## 6. Not verified / open

- DeepSeek function-calling limits and strict mode (the docs page fetched didn't cover it).
- Whether gpt-5.x-mini/nano support `tool_search`.
- SED-Net noise robustness. FreeCAD RE workbench capabilities. Creality's workflow.
- The CAD-Assistant scan pipeline's accuracy (none published). CADFit's numbers (abstract only).
- Text2CAD numbers (NeurIPS'24, <https://arxiv.org/abs/2409.17106>) weren't extracted. It's
  text-only, so it matters little here.
