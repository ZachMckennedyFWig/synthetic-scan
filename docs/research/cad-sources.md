# Ground-truth CAD sources for synthscan

*Research notes, 2026-11-04. Audience: synthscan engineers. Not legal advice. Re-check each licence before any public release, because terms change (several cited here were revised in Sept–Oct 2026).*

## TL;DR

| Rank | Source | What you get | Parametric history? | Licence verdict for a **public** dataset |
|---|---|---|---|---|
| 1 | **Our own procedural generator** (build123d/CadQuery) | Unlimited STEP + exact parameters | Yes, exact (we wrote it) | We own it. Release under CC0/CC BY. |
| 2 | **Fusion 360 Gallery – Reconstruction** (8,625 designs) | STEP/SMT/OBJ + sketch+extrude JSON, per-step intermediates | Yes (sketch + extrude) | Non-commercial research only. You may share *portions or modified* data under the same terms, but not the whole dataset. |
| 3 | **DeepCAD** (~178k) + **Text2CAD** annotations | Onshape sketch+extrude JSON, exportable to STEP | Yes (sketch + extrude) | DeepCAD data has no explicit licence (Onshape-derived). Text2CAD is CC BY-NC-SA 4.0. Treat both as NC research. |
| 4 | **MFCAD++** (59,665) | STEP plus a machining-feature label on every face | No history, but per-face feature labels | **CC BY**: redistributable with attribution |
| 5 | **ABC** (~1M, Onshape) | STEP, Parasolid, meshes, analytic `feat` YAML; FeatureScript for some | Partial (FeatureScript `ofs`) | NYU archive says MIT, but model copyright stays with the creators under Onshape public-doc terms. Usable with attribution; use a curated subset. |
| 6 | **CAD-Recode** (~1M CadQuery programs) | Executable CadQuery Python → STEP | Yes (as code) | CC BY-NC 4.0 |
| 7 | **Printables**, hand-curated CC0/CC BY items that ship STEP | Complex real-world parts | Rarely (STEP only) | Per model. Use only CC0 / CC BY / CC BY-SA, and record the attribution. |
| ✗ | McMaster-Carr | STEP/IGES/SolidWorks/DWG… | No | **Do not include.** The ToS forbids retaining copies and redistribution, and bars AI training "in connection with" its CAD models. |
| ✗ | MakerWorld, GrabCAD, TraceParts | Mostly 3MF/STL; some STEP | No | The default licences are personal use only, or commercial use and distribution need written consent. |
| ✗ | Thingiverse / Thingi10K / MCB | Meshes only | No | They have no B-rep ground truth, and their licences are mixed or unclear. Low value for this project. |

**Recommended STEP loader:** `build123d` (it pulls `cadquery-ocp-novtk`, which has Windows cp312 wheels). Add `cascadio` as the fast mesh-only path. I installed and ran both in a fresh uv Python 3.12 venv on this machine (see §4):

```
uv add --optional step build123d cascadio
```

---

## 1. McMaster-Carr

### Formats
McMaster's CAD page says it offers 3-D and 2-D models "in file formats compatible with most CAD applications", including STEP and SolidWorks. In practice the site's download menu offers STEP, IGES, Parasolid, SAT, SolidWorks part/assembly, Inventor, 3-D PDF, and 2-D DWG/DXF. The API examples show STEP (3-D) and DWG (2-D) links. <https://www.mcmaster.com/cad-models>, <https://www.mcmaster.com/help/api>

### API / bulk download
- An official **Product Information API** exists, with `GET /v1/cad/{cadPath}` for CAD files. Access is only for **approved customers**: contact eCommerce@mcmaster.com, and you receive a client certificate and a password. You must "subscribe" to each part number before you can query it, and there is a total cap and a daily cap on subscriptions. CAD endpoints are rate-limited (no published numbers). The API agreement in the T&Cs limits use of the data to "ingest API Information into your internal systems… solely for use within your company." <https://www.mcmaster.com/help/api>, <https://www.mcmaster.com/termsandconditions>
- There is no bulk or archive download.

### Terms (quoted from <https://www.mcmaster.com/termsandconditions>, retrieved 2026-11-04)
- CAD models "are being made available to help you decide whether to purchase Products from us."
- "you shall not reproduce, display, retain copies of, redistribute or make available the CAD Models … to any third parties"
- "You shall not use the CAD Models to engage in 3D printing or other fabrication of the objects depicted"
- Prohibited: "page or screen scrape, web harvest, or use any robot, indexing agent or other automatic device". The only exception is a self-identified bot that isn't reproducing content.
- Prohibited: using "the McMaster-Carr Properties, any Content, the Products, or the CAD Models, in whole or in part, for or in connection with training or fine-tuning AI Technology".
- `robots.txt` opens with "McMaster-Carr content may not be used to train or fine-tune artificial intelligence or machine-learning technology". It also `Disallow: /`s GPTBot, ClaudeBot, CCBot, Google-Extended and other AI crawlers. <https://www.mcmaster.com/robots.txt>

### Anti-bot behaviour
The site is a heavy JS single-page app with per-session tokens. Third-party "scraper" actors exist (e.g. Apify), but they are unofficial and violate the terms above. We did not test this and will not.

### Recommendation
- **Never ship McMaster geometry or derived scans in a shared dataset.** Derived scans are a "derivative work" of the CAD model, and the terms forbid making the models available to anyone else.
- An LLM *evaluation* is arguably not "training or fine-tuning". Even so, keeping a local corpus collides with "retain copies of", and the stated purpose (deciding whether to buy) doesn't cover benchmarking. If the team still wants McMaster parts for an **internal, private** sanity set, get written permission from McMaster first. The T&Cs explicitly allow uses "agreed to in writing by an authorized representative".
- The tool design should stay source-agnostic regardless. `synthscan` ingests whatever STEP files the user drops into a dataset's input folder (the existing `POST /api/datasets/{ds}/inputs` already does this). Put a `provenance.json` next to each input (`source`, `url`, `licence`, `author`, `redistributable: bool`). Have the dataset exporter refuse to package inputs with `redistributable=false`. A user can then download McMaster parts manually for private experiments without any automation on our side.

---

## 2. Community model sites

### Printables (Prusa)
- **API:** No *official* public API. The site runs on an internal GraphQL endpoint (`api.printables.com/graphql/`). Community tools such as `printables-mcp` use it anonymously: `search_models` with `license_ids`, `list_licenses`, and `get_download_links` (links expire after 24 h; paid and Club models can't be downloaded). The endpoint is undocumented and may change without notice. <https://pypi.org/project/printables-mcp/>, <https://glama.ai/mcp/servers/feodor-ra/printables-mcp/tools/list_licenses>
- **ToS:** The Printables T&Cs (effective 15 Oct 2026) have no explicit scraping or AI clause. They do say the user may "use the PRUSA websites only in the usual manner and for the anticipated purposes" (§4.3), and they incorporate Prusa's General T&Cs. Bulk automated harvesting through an internal API is therefore at least questionable. `robots.txt` allows everything except `/world/`. <https://www.prusa3d.com/page/terms-of-service-of-printablescom_231249/>, <https://www.printables.com/robots.txt>
- **Licences:** Creators choose from "Creative Commons licences, GNU licences, BSD License, Apache License 2.0, CERN Open Hardware Licence, Open Community License and its variants, Standard Digital File License and Commercial Use licences" (§2.3). Downloaders may use files "in accordance with … the selected Licence". The licence can be filtered via GraphQL `license_ids`, or per model in the UI.
- **STEP availability:** STEP *uploads* are accepted (they get no 3-D viewer), but most models ship only STL/3MF. There is **no file-type filter**, only an "authoring software" filter. Expect a small minority of models to have STEP. <https://forum.prusa3d.com/forum/english-forum-general-discussion-announcements-and-releases/printables-search>, <https://forum.prusa3d.com/forum/english-forum-general-discussion-announcements-and-releases/printables-com-not-showing-3d-model-view>
- **Recommendation:** Hand-curate 50–200 "complex geometry" parts that ship STEP and use CC0, CC BY or CC BY-SA. A person downloads them in the browser and records the provenance. Do not bulk-crawl. NC-licensed models are acceptable only for an NC-licensed release. Avoid ND licences, because our scans are derivatives.

### MakerWorld (Bambu Lab)
- **API:** None public. Third-party Apify scrapers exist and are unofficial. <https://apify.com/lexis-solutions/maker-world-com>
- **ToS:** `robots.txt` disallows `/policies` (the ToS path), and WebFetch got 403. I therefore could not quote the current ToS, so treat it as unverified. <https://makerworld.com/robots.txt>
- **Licences:** The **Standard Digital File License** is preselected on upload and, per community readings, forbids sharing the files "under any circumstances". "MakerWorld Exclusive" models also prohibit commercial use of derivatives. Creators can pick CC licences instead. <https://forum.bambulab.com/t/understanding-makerworlds-standard-digital-file-license/257609>, <https://3dprintingindustry.com/news/bambu-lab-makerworld-escalates-copyright-dispute-over-3d-model-reuploads-creality-among-those-named-246363/>
- **Formats:** Mostly 3MF print projects with STL. Users have asked for a "has design file" filter, so STEP is neither filterable nor common. <https://forum.bambulab.com/t/feature-request-add-flag-filter-to-find-models-that-have-design-file/80876>
- **Verdict:** Lowest priority. Use only explicitly CC-licensed models, downloaded by hand.

### Thingiverse (and Thingi10K)
- **API:** A REST API at `api.thingiverse.com` with an app token or OAuth2. It exposes things, files, licences and search. Reports from 2026 say new developer apps are rarely approved, and that there's a limit of roughly 300 requests/hour (unofficial). The site is behind a Cloudflare JS challenge (`robots.txt` itself returns a challenge page). <https://providers.apievangelist.com/providers/makerbot/>, <https://github.com/sebas1922/Thingiverse-API-Script>
- Content is almost entirely STL, with no B-rep, so there are no analytic ground-truth labels. Each thing has a licence field.
- **Thingi10K:** 10,000 Thingiverse meshes, each under its own licence. `pip install thingi10k` provides `thingi10k.dataset(license='creative commons')` for filtering. The code is Apache-2.0. Geometry skews artistic/organic, so it is a poor fit for "reconstruct as CAD". <https://pypi.org/project/thingi10k/>

### GrabCAD / TraceParts (for completeness)
- **GrabCAD:** "All models on GrabCAD are for personal use only… You must come to an agreement with the member who created the content if you'd like to use it commercially." The ToS page returned 403 to automated fetch. **Not redistributable.** <https://blog.grabcad.com/?p=15000>
- **TraceParts:** Download requires an account. Duplication and distribution of site data are restricted, and "commercial use is only authorized with the express written consent of TraceParts". **Not redistributable.** <https://info.traceparts.com/ja/general-terms-of-use>, <https://info.traceparts.com/es/condiciones-generales-utilizacion>

---

## 3. Research datasets

| Dataset | Size | Formats | History / labels | Licence | Download | Relevance to "scan → CAD ops" |
|---|---|---|---|---|---|---|
| **Fusion 360 Gallery – Reconstruction** r1.0.1 | 8,625 designs, 2.0 GB | `.smt`, `.step`, `.obj` (one group per face), `.png`, `.json` sequence, plus all of these per extrude step | Full **sketch + extrude** timeline: sketch curves, constraints, dimensions, profiles, extrude op/extent/taper. Units are **cm**. Official 80:20 split in `train_test.json` | Fusion 360 Gallery Dataset License: **non-commercial research**. You may not redistribute the whole dataset, but may share portions or modified data under the same terms. No re-identification of creators | <https://fusion-360-gallery-dataset.s3.us-west-2.amazonaws.com/reconstruction/r1.0.1/r1.0.1.zip> | **Highest.** Human-designed, exact op sequence, intermediate states. A standard CAD-Recode benchmark |
| Fusion 360 Gallery – Segmentation s2.0.1 | 35,680 parts (3.1 GB) + extended set of 42,912 STEP (483 MB) | `.smt`/`.step`/`.obj` + per-face labels | Per-face **operation** labels (ExtrudeSide/End, CutSide/End, Fillet, Chamfer, RevolveSide/End) | Same as above | <https://github.com/AutodeskAILab/Fusion360GalleryDataset> | Good source of face-op labels; includes fillets and chamfers |
| **DeepCAD** | 178,238 models (~208 MB tarball) | `cad_json` (Onshape-parsed sequences), `cad_vec`. STEP is produced via `utils/export2step.py` (pythonocc) | Sketch + extrude (+ boolean). Fillet, revolve etc. were filtered out | Code is MIT. **Data has no stated licence** (Onshape public docs via ABC). HF mirror is gated | <http://www.cs.columbia.edu/cg/deepcad/data.tar>, <https://github.com/ChrisWu1997/DeepCAD> | **High.** The de-facto benchmark test split, comparable to published numbers |
| **Text2CAD** | ~170k models, ~660k text prompts (beginner → expert) | Text annotations keyed by DeepCAD uid; `cad_seq.zip` (579 MB) | Inherits DeepCAD sequences | **CC BY-NC-SA 4.0**, gated on HF | <https://huggingface.co/datasets/SadilKhan/Text2CAD> | Useful if the LLM prompt includes a text description |
| **CAD-Recode** v1.5 | ~1M train / ~1k val CadQuery `.py` programs | Python source; execute to get STEP | Sketch-extrude **as code** (procedurally generated) | **CC BY-NC 4.0** | <https://huggingface.co/datasets/filapro/cad-recode-v1.5>, <https://github.com/filaPro/cad-recode> | **High, and a direct baseline.** CAD-Recode is a small LLM (Qwen2-1.5B) doing point cloud → CadQuery, evaluated on DeepCAD, Fusion360 and CC3D. Reuse its metrics (Chamfer distance, IoU, invalid-ratio) |
| **ABC** | ~1M models in 10k-model chunks (~1.2 GB per STEP chunk) | `step`, `para` (Parasolid), `stl2`, `meta` for all models. `obj`, `feat` (YAML of analytic curves/surfaces: type, location, axis, radius… indexed into the OBJ), `ofs` (FeatureScript), `stat` for ~750k | FeatureScript for some. Analytic primitive labels (no kernel needed) | Copyright stays with the creators, under Onshape ToS §1.g.ii (public docs). NYU archive records state **MIT**. Cite Koch et al. CVPR 2019 | <https://deep-geometry.github.io/abc-dataset/>, <https://archive.nyu.edu/handle/2451/44368> | Medium-high. Huge and redistributable-ish, but full of trivial, duplicate and junk models, so **filter** by face count, volume, and planar/cylindrical ratio |
| **MFCAD++** | 59,665 STEP (1.5 GB) | STEP. The feature label sits in each `ADVANCED_FACE` name; `feature_labels.txt` (25 classes) | Per-face **machining feature** (hole, slot, pocket, step, chamfer…). Synthetic prismatic stock | **CC BY** (QUB Pure) | <https://pure.qub.ac.uk/en/datasets/mfcad-dataset-dataset-for-paper-hierarchical-cadnet-learning-from/> (DOI 10.17034/d1fec5a0-…); HF mirror `AI4Manufacturing/mfcadpp` | High for feature-label ground truth, and redistributable. Caveat: label order = STEP text order, not OCC traversal order. The original 16-class MFCAD is MIT (<https://github.com/hducg/MFCAD>) |
| CADParser | ~40k models with sequences incl. revolve, fillet, chamfer | Unclear | Richer ops than DeepCAD | **No public release or licence found.** A subset is repackaged in HF `VladPyatov/CADFS` (CC BY 4.0, which covers the repackaging only) | <https://www.ijcai.org/proceedings/2023/200> | Would be ideal, but availability is unclear. Skip unless the authors respond |
| CC3D / CC3D-Ops | 50k+ scan/CAD mesh pairs; 37k B-reps with per-face op labels | Meshes; B-rep (Ops) | Per-face ops (Ops variant) | **Signed agreement required**, not redistributable | <https://cvi2.uni.lu/cc3d-dataset/> | Prior art for exactly our idea (realistic scans from CAD). Use it to *calibrate* artifact models, not as an input source |
| MCB (Mechanical Components Benchmark) | 58,696 parts, 68 classes | Meshes (OBJ) | Class labels only | Code is MIT. **Data was scraped from TraceParts/GrabCAD/3D Warehouse, licence unclear** | <https://github.com/stnoah1/mcb> | Low. No B-rep, and inherits those sites' restrictions |
| Thingi10K | 10k meshes | STL | None | Per model | <https://pypi.org/project/thingi10k/> | Low |

Paper links: Fusion 360 Gallery <https://arxiv.org/abs/2010.02392>, DeepCAD <https://arxiv.org/abs/2105.09492>, Text2CAD <https://arxiv.org/abs/2409.17106>, CAD-Recode <https://arxiv.org/abs/2412.14042>, MCB <https://www.cs.utexas.edu/~huangqx/mcb_benchmark.pdf>. Fusion licence: <https://github.com/AutodeskAILab/Fusion360GalleryDataset/blob/master/LICENSE.md>.

### Release strategy implied by the licences
1. **Tier A (CC BY 4.0, redistributable):** our generator output, MFCAD++, a curated ABC subset, and hand-picked CC0/CC BY Printables parts. Ship the STEP, scans and labels, with an `ATTRIBUTION.csv`.
2. **Tier B (NC research):** scans derived from Fusion 360 Reconstruction, DeepCAD/Text2CAD and CAD-Recode. Either ship them under the strictest upstream terms (CC BY-NC-SA 4.0 covers all three), or ship a "recipe": upstream IDs + scanner profile + RNG seeds + `synthscan` version, so users regenerate the files locally. The recipe route avoids redistributing upstream geometry at all. Fusion's licence also forbids re-identifying creators, so strip any user or project names.
3. **Never:** McMaster, GrabCAD, TraceParts, MakerWorld "Standard Digital File License" models.

---

## 4. Python STEP loading and tessellation on Windows (Python 3.12, uv)

### Package status (PyPI, checked 2026-11-04)

| Package | Version | Win cp312 wheel | Notes |
|---|---|---|---|
| `cadquery-ocp` | 8.0.1.1.0 | ✓ | Full OCCT 8.0 bindings. **Pins `vtk==9.6.2`** (large) |
| `cadquery-ocp-novtk` | 8.0.1.1.0 | ✓ | Same OCP module without VTK |
| `build123d` | 0.13.0 (py ≥3.11,<3.15) | pure-python | Depends on `cadquery-ocp-novtk>=8.0,<8.1` |
| `cadquery` | 2.8.0 | pure-python | Depends on `cadquery-ocp>=7.9.3.1,<8.0`, plus trame, casadi, numba, nlopt. **Conflicts with build123d 0.13** (different OCP major, and both ship the `OCP` module), so pick one per environment |
| `cascadio` | 0.1.1 | ✓ (`cp312-abi3`) | Minimal OCCT STEP/IGES → GLB/OBJ, used by `trimesh.load("x.step")`. Since 0.1 it can export analytic primitives. Old releases get deleted from PyPI for space, so don't pin an exact non-LTS version (LTS: 0.0.13) |
| `pythonocc-core` | 7.9.3 | conda-forge only | Unofficial pip repack: `pythonocc-core-wheels` 7.9.3.post1 (<https://pypi.org/project/pythonocc-core-wheels/>). DeepCAD's export scripts use it. Not recommended alongside OCP |
| `gmsh` | 4.15.2 | ✓ (`py3-none-win_amd64`) | Bundles OCC for STEP import, but is **GPL-2.0+** and FEM-meshing oriented. Avoid |
| `trimesh` | 5.2.0 | pure-python | STEP only through `cascadio`. **Returns metres** (see the gotcha below) |

**Verified on this machine:** `uv venv -p 3.12` then `uv pip install build123d cascadio trimesh` installed cleanly. Pulled in `cadquery-ocp-novtk 8.0.1.1.0`, `numpy 2.5.4`, `trimesh 5.2.0`.

> Note: `pyproject.toml` currently has `step = ["cadquery-ocp>=7.8"]`. That pulls VTK and would block adding `build123d` later. Suggested change: `step = ["build123d>=0.13", "cascadio>=0.1.1"]` (or `cadquery-ocp-novtk>=8.0` if we only want raw OCP).

### Recommendation: build123d / OCP for ground truth, cascadio for quick mesh loads

**Path A: accurate tessellation + per-face analytic labels (tested).** Mesh once with explicit deflection, then walk the faces. This gives a triangle→B-rep-face map, which is exactly what per-point ground-truth labels need.

```python
from build123d import import_step
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools
from OCP.BRep import BRep_Tool
from OCP.TopLoc import TopLoc_Location
from OCP.TopAbs import TopAbs_REVERSED
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Cone, GeomAbs_Sphere, GeomAbs_Torus

shape = import_step("part.step")  # build123d Shape/Compound, units = file units (mm normally)
BRepTools.Clean_s(shape.wrapped)  # drop any triangulation embedded in the STEP
# (shape, linear deflection [mm], is_relative, angular deflection [rad], parallel)
BRepMesh_IncrementalMesh(shape.wrapped, 0.01, False, 0.1, True)

V, F, face_id, labels = [], [], [], []
for i, face in enumerate(shape.faces()):
    loc = TopLoc_Location()
    tri = BRep_Tool.Triangulation_s(face.wrapped, loc)
    if tri is None:
        continue
    T, base = loc.Transformation(), len(V)
    V += [tri.Node(k).Transformed(T).Coord() for k in range(1, tri.NbNodes() + 1)]
    flip = face.wrapped.Orientation() == TopAbs_REVERSED
    for k in range(1, tri.NbTriangles() + 1):
        a, b, c = tri.Triangle(k).Get()
        F.append((base + a - 1, base + (c if flip else b) - 1, base + (b if flip else c) - 1))
        face_id.append(i)

    s = BRepAdaptor_Surface(face.wrapped)
    t = s.GetType()
    lab = {"face": i, "type": face.geom_type.name, "area": face.area}
    if t == GeomAbs_Plane:
        p = s.Plane()
        lab |= dict(origin=p.Location().Coord(), normal=p.Axis().Direction().Coord())
    elif t == GeomAbs_Cylinder:
        c = s.Cylinder()
        lab |= dict(radius=c.Radius(), origin=c.Location().Coord(), axis=c.Axis().Direction().Coord())
    elif t == GeomAbs_Cone:
        c = s.Cone()
        lab |= dict(
            ref_radius=c.RefRadius(),
            half_angle=c.SemiAngle(),
            apex=c.Apex().Coord(),
            axis=c.Axis().Direction().Coord(),
        )
    elif t == GeomAbs_Sphere:
        c = s.Sphere()
        lab |= dict(radius=c.Radius(), center=c.Location().Coord())
    elif t == GeomAbs_Torus:
        c = s.Torus()
        lab |= dict(
            major=c.MajorRadius(),
            minor=c.MinorRadius(),
            center=c.Location().Coord(),
            axis=c.Axis().Direction().Coord(),
        )
    labels.append(lab)  # B-spline/offset faces: type only

# trimesh.Trimesh(V, F, process=False).merge_vertices() -> watertight solid (verified)
```

On a 60×40×8 mm filleted plate with a boss and 4 holes, this produced 3,074 verts / 3,060 tris in 0.04 s, with 9 CYLINDER + 7 PLANE faces. Hole radius, origin and axis came out exactly. After `merge_vertices()` the mesh is watertight, because adjacent faces share edge discretisation.

Notes:
- Linear deflection is an absolute chord error in model units. Pick it relative to the part size (e.g. `1e-3 × bbox diagonal`, floored at 0.005 mm) or use `is_relative=True`. Angular deflection of 0.1–0.2 rad keeps small holes round.
- build123d's convenience `shape.tessellate(tolerance, angular_tolerance=0.1)` returns `(verts, tris)` for the whole shape, but loses the face map.
- **Hole vs boss:** for a cylinder face, evaluate the face normal (orientation-corrected, `face.normal_at(...)`) and check whether it points toward the axis (concave = hole) or away from it (convex = boss/fillet).
- Edges and loops (`face.edges()`, `Edge.geom_type`, `radius`) give circle and line ground truth for sharp-edge labels.
- Full face counts and topology also let us compute "feature" metrics (number of holes, hole diameters, pattern pitch) for grading LLM output.

**Path B: fast mesh-only load (tested).** Use this when you only need triangles, e.g. for the simulated scan itself:

```python
import cascadio, trimesh

cascadio.step_to_glb(
    "part.step", "part.glb", tol_linear=0.01, tol_angular=0.1, include_brep=True
)  # analytic primitives -> metadata
scene = trimesh.load("part.glb")  # or trimesh.load("part.step") directly
scene = scene.convert_units("millimeters")  # GLB is metres! returns a copy; not in-place
g = next(iter(scene.geometry.values()))
g.metadata["cascadio"]["brep_primitives"]  # Plane/Cylinder/Cone/Sphere/Torus with params (metres)
```

**Gotcha:** `trimesh.load("x.step")` reports `units == "meters"` with extents 0.06×0.04×0.028 for a 60×40×28 mm part. Always convert. With `include_brep=True` the GLB carries per-primitive parameters, and a direct `step_to_glb` → `trimesh.load(glb)` exposes a per-triangle `face_attributes["brep_index"]`. Going through `trimesh.load("x.step")` does *not* expose `brep_index`, because it doesn't pass `include_brep`. `convert_units` doesn't rescale the `brep_primitives` metadata, which stays in metres. GLB vertices are float32, so expect ~1e-6 relative error (59.99999866 mm instead of 60). Cascadio has no B-spline parameters, edges or topology, so use Path A for labels.

Docs: build123d <https://build123d.readthedocs.io/>, OCP <https://github.com/CadQuery/OCP>, cascadio <https://pypi.org/project/cascadio/>, cadquery-ocp <https://pypi.org/project/cadquery-ocp/>, gmsh <https://pypi.org/project/gmsh/>.

---

## 5. Procedurally generated parts (complement)

Our own generator is the only source with **perfect, licence-free, parameter-level ground truth**, e.g. "bracket: t=4, L1=40, L2=30, 2× Ø5.5 at pitch 20". That matches what ScanRuler-style LLM reconstruction outputs. Build it in build123d (same OCP stack as the loader) and emit, per part:
`part.step`, `params.json` (family, parameters, units), `ops.json` (an ordered sketch/extrude/hole/fillet list, Fusion-360-like), and `faces.json` (labels from §4).

Families worth starting with: L/Z brackets, flat plates with hole grids and slots, spacers/standoffs, washers, flanges (bolt circle), pillow blocks, shaft collars, enclosures with bosses, gussets, revolved pulleys and knobs. Randomise within engineering-plausible ranges (standard metric clearance holes, chamfer/fillet sizes ≤ wall/2).

Existing open-source building blocks:

| Project | What | Licence |
|---|---|---|
| **bd_warehouse** (build123d) | Parametric bearings, fasteners (ISO/DIN screws, nuts, washers), **flanges (ASME B16.5)**, gears, sprockets, pipes, threads, OpenBuilds parts | Apache-2.0 per source headers. <https://bd-warehouse.readthedocs.io/> |
| **cq_warehouse** (CadQuery) | Older CadQuery equivalent (fasteners, bearings, chains, sprockets) | Apache-2.0. <https://cq-warehouse.readthedocs.io/> |
| **CAD-Recode** generator output | 1M random sketch-extrude CadQuery programs. A good model of how to sample "plausible" sketch-extrude parts; the generator code itself is not clearly released | Data CC BY-NC 4.0. <https://huggingface.co/datasets/filapro/cad-recode-v1.5> |
| **MFCAD / MFCAD++** | Synthetic prismatic stock with machined features (holes, slots, pockets, steps) and per-face labels | MFCAD MIT (<https://github.com/hducg/MFCAD>), MFCAD++ CC BY |
| **Fusion 360 Gallery tools** | Reconstruction "gym" / regraph tools that replay JSON sequences via the Fusion API (needs Fusion 360) | See repo. <https://github.com/AutodeskAILab/Fusion360GalleryDataset/tree/master/tools> |

Replaying DeepCAD or Fusion JSON sequences in build123d (sketch lines/arcs/circles → `extrude` with NewBody/Join/Cut/Intersect) is a few hundred lines. It would let us regenerate those parts locally from IDs, which suits the Tier-B "recipe" release, and it avoids depending on pythonocc or Fusion.

---

## Open items
- MakerWorld ToS text could not be retrieved (robots-disallowed path and a 403). Read it in a browser before using any MakerWorld model.
- Ask CADParser authors (Zhou, Tang, Zhou; IJCAI 2023) about data release.
- If McMaster parts are wanted even internally, email eCommerce@mcmaster.com for written permission; the API agreement alone does not cover benchmarking or retention.
