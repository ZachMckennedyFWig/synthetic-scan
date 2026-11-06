# Real-world 3D scan artifacts and scanner meshing pipelines

Research notes for the `synthscan` generator. It takes ground-truth CAD (STEP/STL) and emits realistic, randomized synthetic scans: raw point clouds, fused clouds, and meshed STLs. The scans train and evaluate LLM-based CAD reconstruction for ScanRuler (CNC Kitchen).

**Audience:** engineers implementing the simulator. Each artifact starts with its physical mechanism and a parameter range you can implement, then the simulation method.

**Status:** research pass, 2026-11. All lengths are in mm unless stated otherwise.

**How to read the numbers:**

- **[spec]** Vendor-stated figure. These are usually best-case values measured on a sphere bar in the lab.
- **[meas]** Independently measured, either a published study or a reviewer's test.
- **[est]** Engineering estimate. We derived it from mechanisms, vendor defaults, or forum reports, and could not find a direct measurement. Tune it against real scans (see §6).

---

## 0. Key definitions (vendor spec sheets mix these up)

| Term | Meaning | Use in simulator |
|---|---|---|
| **Point distance / resolution** | Spacing of the fused point grid, usually the voxel size of the fusion step. Revo Scan's "Standard" fusion is literally *voxel fusion*, and "Advanced" is *fitting fusion* ([Revo Scan manual](https://www.machines-3d.com/images/Image/File/Manuel/Scanner%203D/Miraco/1218-PC-Revo-Scan-User-Manual.pdf)). | Fusion voxel size `h`. It drives edge rounding and small-feature loss. |
| **Single-frame precision** | Repeatability (RMS) of one depth frame on a flat target. | Per-point random noise σ before fusion. |
| **Single-frame accuracy** | Bias plus noise for one frame. | σ plus systematic error terms. |
| **Volumetric accuracy** `a + b·L` | Error over an object of length L (m). It is dominated by registration drift and scale error. Examples: Raptor Pro 0.02 + 0.08 mm/m, Metro Y Pro 0.02 + 0.04 mm/m ([CNC Kitchen](https://cnckitchen.com/blog/creality-raptor-pro-vs-revopoint-metro-y-pro)), MetroX 0.03 + 0.1·L ([Revopoint](https://store.revopoint3d.com/pages/3d-laser-scanner-metrox)), EinScan HX 0.04 + 0.06 mm/m laser and 0.05 + 0.1 mm/m LED ([HX spec sheet](https://cdn.shopify.com/s/files/1/2104/4351/files/EinScan_HX_Spec_Sheet.pdf)), Artec Space Spider 0.05 + 0.3 mm/m ([Hawk Ridge](https://hawkridgesys.com/artec-space-spider-3d-scanner)). | Drift and scale budget: `b` calibrates the drift random walk and the scale error. |

The HP Academy Einstar review explains why: point distance (resolution) is not accuracy, and Shining3D stopped quoting an accuracy figure for the Einstar ([HP Academy](https://www.hpacademy.com/previous-webinars/383-affordable-3d-scanning-shining-3d-einstar/)). The simulator needs separate knobs for `h` (resolution), `σ` (precision), drift (volumetric) and bias (systematic).

---

## 1. Scanner technologies and error models

### 1.1 Spec summary of current consumer/prosumer devices

| Device | Tech | Accuracy / precision | Point distance | Working distance | Source |
|---|---|---|---|---|---|
| Creality CR-Scan Raptor | Blue 7-line laser + NIR SL | 0.02 mm laser, 0.1 mm NIR [spec] | 0.02–2 mm | 150–400 mm (laser) | [Stemfinity listing](https://stemfinity.com/products/cr-scan-raptor-3d-scanner) |
| Creality Raptor Pro | Blue parallel/cross laser + NIR | 0.02 + 0.08 mm/m [spec]; ball-bar ±0.02 mm [meas] | 0.07 mm min (parallel) | ~200 mm (parallel), ~300 mm (cross) | [CNC Kitchen](https://cnckitchen.com/blog/creality-raptor-pro-vs-revopoint-metro-y-pro) |
| Creality CR-Scan Otter | 4-lens stereo, white/IR SL | 0.02 mm @ 60 mm [spec] | 0.05–2 mm | 110–1000 mm | [B&H](https://www.bhphotovideo.com/c/product/1833196-REG/creality_cr_scan_otter_portable_3d.html) |
| Creality CR-Scan Ferret Pro | NIR structured light | 0.1 mm [spec] | 0.16 mm | 150–700 mm | [3DWithUs](https://3dwithus.com/creality-cr-scan-ferret-pro-review-3d-scanner-testing) |
| Revopoint POP 3 / 3 Plus | IR dual-camera SL | 0.08 mm accuracy, 0.04 mm precision [spec] | 0.05 mm | 150–400 mm | [Revopoint](https://www.revopoint3d.com/products/pop3-3d-scanner) |
| Revopoint MINI 2 | Blue-light SL | 0.02–0.05 mm single-frame [spec] | 0.02 mm | 120–250 mm (FOV 52×64 @120) | [Revopoint support](https://global.revopoint3d.com/pages/support-mini2) |
| Revopoint MIRACO / Pro | Quad-camera IR SL | 0.05 mm accuracy, 0.02 mm precision [spec] | 0.05 mm | 100–1000 mm | [Revopoint](https://www.revopoint3d.com/products/revopoint-miraco-pro-3d-scanner) |
| Revopoint RANGE 2 | IR SL (large objects) | 0.3 mm accuracy, 0.1 mm precision [spec] | 0.1 mm | 400–1300 mm | [3DPI](https://3dprintingindustry.com/news/revopoint-unveils-its-new-revopoint-range-2-3d-scanner-technical-specifications-and-pricing-227571/) |
| Revopoint MetroX / Pro | Blue cross/parallel laser + full-field SL | 0.03 (Pro 0.02) mm accuracy, 0.01 mm precision [spec] | 0.05 mm | ~250 mm | [Hackster](https://www.hackster.io/news/revopoint-promises-metrology-grade-accuracy-from-its-new-metrox-3d-scanner-474ad85372a6), [3DJake](https://www.3djake.com/revopoint/metrox-pro) |
| Shining3D Einstar | IR VCSEL SL | "0.1 mm" (no longer quoted) [spec] | 0.1–3 mm | 160–1400 mm, optimum 400 | [Aniwaa review](https://www.aniwaa.com/review/3d-scanners/shining-3d-einstar-review-a-solid-and-all-around-impressive-handheld-3d-scanner-under-1k/), [Top3DShop](https://top3dshop.com/product/shining3d-einstar-3d-scanner) |
| Shining3D EinScan SP V2 | White-light SL, turntable | ≤0.05 mm [spec] | 0.17–0.2 mm | fixed | [Einstar spec page](https://www.einstar.com/pages/einscan-sp-v2-specs) |
| Shining3D EinScan HX | Blue LED SL + blue laser | 0.05 (LED) / 0.04 (laser) mm [spec] | ≥0.05 mm | — | [HX spec sheet](https://cdn.shopify.com/s/files/1/2104/4351/files/EinScan_HX_Spec_Sheet.pdf) |
| Shining3D FreeScan Combo | Blue laser (multi/parallel/single line) + IR | 0.02 mm [spec] | 0.05–2 mm | — | [3DGBIRE](https://3dgbire.com/products/freescan-combo) |
| Artec Space Spider | Blue LED SL | 0.05 + 0.3 mm/m [spec] | 0.1 mm | 200–300 mm | [Hawk Ridge](https://hawkridgesys.com/artec-space-spider-3d-scanner) |
| Artec Eva | White LED SL | 0.1 mm [spec] | 0.5 mm | 400–1000 mm | [Develop3D](https://develop3d.com/3d-scanning/review-artec-eva-spacespider-3d-scanning/) |
| iPhone/iPad LiDAR (dToF) | VCSEL dToF + RGB | cm-level object bias (0.9–9.3 cm on vehicles) [meas]; ~10 cm on outcrops [meas] | effective mesh ~ cm | 0.25–5 m | [SAE 2021-01-0891](https://saemobilus.sae.org/content/2021-01-0891/), [Luetzenburg via CNR](https://chloe.cnr.it/s/DHeLO/item/16176) |
| iPhone TrueDepth | NIR dot-projector SL | 0.35–0.86 mm RMS on faces [meas] | ~0.5 mm | 0.2–0.5 m | [PMC11592646](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11592646/), [Angle Orthod.](https://angle-orthodontist.kglmeridian.com/view/journals/angl/91/5/article-p641.xml) |
| Photogrammetry (phone/DSLR) | SfM + MVS | ~0.6–0.7 mm vs Artec on small sculpture [meas]; scale arbitrary unless rescaled | image-GSD bound | any | [Moyano et al. 2023, Sensors](https://doaj.org/article/f1acadab8afb4678a5f66dc6958b0b3e), [Polycam](https://learn.poly.cam/hc/en-us/articles/50434745985556-How-Accurate-Are-Polycam-Scans) |

### 1.2 Error model by technology

**Structured light (LED blue/white, IR/NIR, VCSEL dot or fringe), active stereo/triangulation**

- **Depth noise grows quadratically with range.** It follows `σ_z = z²·σ_d/(f·b)`, with disparity/phase noise `σ_d`, focal length in pixels `f`, and baseline `b`. Chatterjee & Govindu show the quadratic law is inherent to SL stereo ([arXiv 1505.01936](https://arxiv.org/pdf/1505.01936)). Intel publishes the same formula for D4xx with subpixel RMS ≈ 0.08 px ([Keselman et al., arXiv 1705.05548](https://arxiv.org/pdf/1705.05548)).
  - Over a consumer scanner's working window (e.g. 150–400 mm), noise therefore varies 2–7×. Simulators must not use constant σ.
  - Implement as `σ_z(z) = σ_ref·(z/z_ref)²`, with `z_ref` the scanner's optimal distance.
- **Noise is anisotropic.** It is mostly axial, along the camera ray. Lateral noise is ~1 pixel footprint (`z/f`) and grows only linearly with z. Nguyen et al. measured this for Kinect v1 ([3DIMPVT 2012](https://computer.org/csdl/proceedings-article/3dimpvt/2012/4873a524/12OmNAlvHUP)):
  - `σ_z(z,θ) = 0.0012 + 0.0019·(z−0.4)² [m]` for 10°<θ<60°.
  - Plus a term `0.0001/√z · θ²/(π/2−θ)²` that blows up as θ→90°.
  - `σ_L[px] = 0.8 + 0.035·θ/(π/2−θ)`, so `σ_L[m] = σ_L[px]·z/f`.
  - The shape of this model, flat until ~60° and then hyperbolic, is what we want to transfer. Rescale the magnitudes to the scanner.
- **Incidence-angle dependence.** Signal falls roughly with `cos θ` (Lambertian). Above ~60–75° data is rejected, which gives grazing-angle holes. Berger et al.'s laser simulator reproduces NextEngine's missing-data pattern purely from a low-radiance rejection threshold ([Berger et al. 2013, TOG](https://matthewberger.github.io/papers/bench.pdf)).
- **Triangulation shadow.** A point must be visible to both the projector and the camera; for multi-camera heads, to the projector and at least one camera. Baselines in handhelds are ~40–150 mm. Berger found 10–150 mm baselines span the useful range of accuracy versus occlusion ([Berger et al. 2013](https://matthewberger.github.io/papers/bench.pdf)).
- **Systematic error at edges.** Edges perpendicular to the baseline show a stair-step on the rising edge and an overshoot bump before the falling edge. Edges parallel to the baseline do not ([Abbasinejad, Kil, Sharf, Amenta 2009, "Rotating scans for systematic error removal"](https://www.cs.ucdavis.edu/~amenta/pubs/RotatingScans.pdf)). The overshoot grows with step height (tested on 1–4.7 mm steps).
- **Global-illumination errors.** Projector defocus, inter-reflections and subsurface scattering are the main SL error sources in the PBR benchmark of [Medeiros, Doraiswamy, Berger, Silva 2014 (Pacific Graphics)](https://matthewberger.github.io/papers/sl.pdf). No single pattern scheme (Gray code, micro phase shift, ensemble codes) handles all three.
- **NIR versus blue light.**
  - NIR (Ferret, POP, MIRACO, Einstar, Raptor NIR mode) handles sunlight and dark or skin-like targets better but resolves less micro-geometry. CGMag reports that the Raptor Pro NIR mode can't match laser micro-geometry ([CGMag](https://www.cgmagonline.com/review/hardware/creality-raptor-pro-3d-scanner)).
  - Blue LED (MINI, Spider, Otter) gives finer detail but struggles with dark and shiny surfaces.

**Blue laser line (Raptor laser, MetroX, FreeScan, EinScan HX laser)**

- **Mechanism.** Each frame sees 7–45 thin lines (e.g. MetroX Pro has 30 cross plus 15 parallel lines ([3DJake](https://www.3djake.com/revopoint/metrox-pro))). Depth comes from sub-pixel peak detection on each line.
- **Noise.** Very low: 0.01–0.02 mm precision [spec]. Laser speckle is a key source. Berger models speckle as additive radiance noise whose variance grows with distance from the stripe center, then does Gaussian peak fitting ([Berger et al. 2013](https://matthewberger.github.io/papers/bench.pdf)).
  - Real laser noise appears as **bumps aligned with the laser sweep direction**. This is anisotropic noise, which Berger validated against a NextEngine.
  - In handheld multi-line scanners it shows up as faint striation parallel to the line direction at the line-pitch spatial frequency.
- **Marker tracking almost always.** Laser mode needs retro-reflective markers on or around the part, so marker holes and remnants are typical of laser profiles. CNC Kitchen saw leftover marker geometry in Metro Y output ([CNC Kitchen](https://cnckitchen.com/blog/creality-raptor-pro-vs-revopoint-metro-y-pro)).
- **Better on dark and shiny surfaces than LED.** CNC Kitchen's Raptor Pro scanned an unsprayed brass needle valve including a stamped marking. The Metro Y initially captured almost nothing and needed much higher laser brightness ([CNC Kitchen](https://cnckitchen.com/blog/creality-raptor-pro-vs-revopoint-metro-y-pro)).
- **Inter-reflection.** On metal concavities a line can hit two surfaces, so a secondary reflection is triangulated as a false point. Polarization helps ([BMVC 1995, polarization for triangulation laser scanners](https://bmva-archive.org.uk/bmvc/1995/bmvc-95-051.pdf)). A 2025 study reports metal-workpiece errors falling from 0.8 mm to 0.1 mm after reflection suppression ([Opt. Precision Eng. 2025](https://m.researching.cn/articles/OJ1255d1062587be92)). That gives a magnitude for spurious points: up to ~1 mm off the surface.
- **Step-edge outliers.** When a line straddles a step edge, part of it lands on the adjacent surface and produces outliers ([CVUT STC 2015](https://stc.fs.cvut.cz/history/2015/sbornik/papers/pdf/5518.pdf)).

**IR VCSEL / dToF (iPhone LiDAR) and iToF (Kinect v2-class)**

- **iPhone LiDAR.** The depth map is very low resolution (on the order of 256×192), so the object mesh resolves features at the cm level. ARKit fuses depth into a smoothed mesh.
  - Errors are cm-scale on object dimensions: 0.9–9.3 cm bias on vehicles ([SAE 2021-01-0891](https://saemobilus.sae.org/content/2021-01-0891/)).
  - Developers report under-estimated depth beyond ~1.5 m ([Apple dev forums](https://developer.apple.com/forums/thread/773571)).
  - Missing data in phone AR depth averages ~12.5% per frame, ranging 0–40% ([arXiv 2310.14437](https://arxiv.org/pdf/2310.14437)).
  - Useless for small mechanical parts except as a "worst case" profile.
- **ToF.** Its signature artifact is flying (mixed) pixels at depth discontinuities: one pixel integrates foreground and background returns and reports an in-between depth ([Mask-ToF, CVPR 2021](https://openaccess.thecvf.com/content/CVPR2021/html/Chugunov_Mask-ToF_Learning_Microlens_Masks_for_Flying_Pixel_Correction_in_Time-of-Flight_CVPR_2021_paper.html); [Reynolds et al. CVPR 2011](https://liner.com/review/capturing-timeofflight-data-with-confidence)).
  - Kinect v2 noise was modeled as a function of distance and angle, with a separate sunlight model ([Fankhauser et al. ICAR 2015](https://www.research-collection.ethz.ch/bitstream/handle/20.500.11850/104272/1/eth-48073-01.pdf)).
  - Fitted polynomial axial and lateral models for Kinect v1/v2 and MotionCam-3D are in [arXiv 2402.16514](https://ar5iv.labs.arxiv.org/html/2402.16514). They found the best sim-to-real transfer when synthetic noise was **1.25×** the estimated real noise. That is a useful hint: slightly over-noise.
- **TrueDepth (front dot projector).** This is short-range SL. Accuracy is 0.35–0.86 mm RMS on faces, with regional errors >3 mm ([Angle Orthodontist 2021](https://angle-orthodontist.kglmeridian.com/view/journals/angl/91/5/article-p641.xml), [PMC11592646](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11592646/)).
- **Lego test.** Vogt, Rips & Emmelmann compared iPad Pro LiDAR and TrueDepth against an industrial SL scanner on Lego bricks. The industrial scanner was consistently better, but the phone may suffice for coarse uses ([Technologies 9(2):25, 2021](https://tore.tuhh.de/bitstream/11420/9247/1/technologies-09-00025.pdf)).

**Photogrammetry (RealityScan/RealityCapture, Meshroom, Apple Object Capture, Polycam Photo mode)**

- **Mechanism.** SfM poses, then MVS depth maps, then fusion and meshing. The error model is completely different from active scanners:
  - **Texture dependence.** Uniform CAD-like surfaces (grey PLA, anodized aluminium) produce noisy "orange peel", bumps, or holes on large flat faces, because there are no correspondences to match.
  - **Scale is arbitrary** unless you rescale to a known dimension. Polycam says Object Mode models "are not dimensionally accurate unless you use the Rescale tool" ([Polycam](https://learn.poly.cam/hc/en-us/articles/50434745985556-How-Accurate-Are-Polycam-Scans)).
  - **Accuracy** on a small textured artifact is ~0.6–0.7 mm versus Artec Spider and Revopoint POP ([Moyano et al. 2023](https://doaj.org/article/f1acadab8afb4678a5f66dc6958b0b3e)).
  - **Edges are often better** than on SL scanners when the surface is textured, because image resolution is high. Concavities are filled by the visual hull and graph-cut meshing.
  - **Specular surfaces** produce view-dependent false depth, i.e. "melted" or dented regions.

---

## 2. Artifact catalogue

Format for each artifact: **Mechanism**, then **Signature**, **Magnitude / parameter range**, and **Simulation**.

Scope (randomization level) is noted as **[scan]** (one value per scan), **[region]** (per CAD face or patch), **[frame]** (per depth frame) or **[point]** (per point).

Notation:

- `h`: fusion voxel / point distance.
- `σ0`: single-frame precision at the optimal distance.
- `z`: range.
- `θ`: incidence angle between surface normal and view ray.

### 2.1 Range noise (view-direction, depth- and angle-dependent)

- **Mechanism.** Phase, peak or disparity estimation noise (photon shot noise, speckle, camera read noise) is converted to depth by triangulation. It lies along the camera ray, scales with z², and inflates at grazing angles and on low-albedo surfaces (lower SNR).
- **Signature.** Fine graininess. After fusion it averages to a lower-amplitude, spatially correlated orange-peel texture. Raw single frames look striped along scan lines.
- **Magnitude.**
  - Per frame σ0: 0.005–0.02 mm for laser, 0.02–0.05 mm for blue SL, 0.04–0.15 mm for IR/NIR SL, 1–5 mm for phone LiDAR [spec/est].
  - The fused-surface residual RMS is typically 0.3–0.7× σ0, because K overlapping frames average down roughly as 1/√K but the noise is not independent [est].
- **Simulation.** Do it per frame, in sensor coordinates:
  ```
  σ_ax = σ0 · (z/z_ref)^2 · g(θ) · (albedo_ref/albedo)^0.5 · k_region
  g(θ) = 1 + c_θ · (θ/(π/2−θ))^2          # Nguyen-like; c_θ ∈ [0.02, 0.2]
  depth += N(0, σ_ax)                      # along ray
  xy    += N(0, σ_lat), σ_lat ≈ 0.3–1.0 px · z/f
  ```
  - Add a **correlated** component: band-limited noise (Perlin/simplex, or Gaussian-filtered white noise on the image grid) with σ_c = 0.2–0.6·σ_ax and correlation length 3–15 px. Real noise is not i.i.d. The render_kinect re-implementation of BlenSor's Kinect model offers Gaussian, Perlin and Simplex options for exactly this reason ([render_kinect](https://github.com/jbohg/render_kinect)).
  - Also add **heavy tails**: a 1–3% mixture with 3–6σ. Pure Gaussian is a giveaway.
  - Randomize σ0 **[scan]** from the profile range and `k_region` **[region]** ∈ [0.7, 1.5] for material.

### 2.2 Systematic depth bias (material, translucency, subsurface)

- **Mechanism.** Light enters translucent plastics (natural PETG, nylon, white or light PLA to a lesser degree, resin) and scatters back, so the decoded surface sits below the real one and is blurred. The error can be compensated by shifting points along the normal ([Opt. Eng. 50(6) 2011](https://proceedings.spiedigitallibrary.org/journals/optical-engineering/volume-50/issue-06/063601/Measuring-error-compensation-on-three-dimensional-scans-of-translucent-objects/10.1117/1.3582858.full)). Subsurface blur is a named error class in Medeiros et al. 2014.
- **Signature.**
  - A uniform inward offset with extra edge rounding.
  - Thin translucent walls may show the back face.
- **Magnitude.** 0.02–0.3 mm inward [est]; up to ~1 mm on very translucent material [est].
- **Simulation.** **[region]**
  - Per-face translucency τ∈[0,1]. Offset points by `−τ·d_max·n`.
  - Smooth the result with a Gaussian of σ ≈ τ·0.5 mm in surface space, e.g. by neighbor averaging on the GT mesh.

### 2.3 Edge rounding / filleting of sharp edges

- **Mechanism.** Several mechanisms add up:
  1. **Finite lateral resolution.** The pixel footprint at range z is `z/f`, ~0.05–0.3 mm. The projector pattern is blurred by defocus (Medeiros 2014).
  2. **Peak/phase bias at discontinuities.** Stair-step and overshoot ([Abbasinejad 2009](https://www.cs.ucdavis.edu/~amenta/pubs/RotatingScans.pdf)).
  3. **Grazing-angle rejection** right at the edge.
  4. **Volumetric fusion.** TSDF averaging over a voxel size `h` and truncation band rounds convex edges and fills concave corners.
  5. **Implicit meshing.** Screened Poisson at depth d smooths below `bbox/2^d`.
  6. **Mesh smoothing** (Laplacian/Taubin) in post.
  
  CNC Kitchen's comparison shows the resolution effect directly. The Raptor Pro at 0.07 mm point distance resolved the Nintendo logo crisply; the Metro Y (min 0.15 mm) was "softer and smoother" and showed "frayed or burr-like structures around many sharp features" ([CNC Kitchen](https://cnckitchen.com/blog/creality-raptor-pro-vs-revopoint-metro-y-pro)).
- **Signature.**
  - Convex edges become fillets.
  - Concave (internal) corners get filled with a fillet of similar or larger radius, because fusion also averages there and occlusion makes it worse.
  - Small chamfers become indistinguishable from fillets.
  - Cylinder–plane edges round asymmetrically.
- **Magnitude.** Effective radius `r_eff ≈ 1–3·h + r_smooth`, where `r_smooth` ≈ 0–0.5 mm from post-smoothing [est]. Concrete ranges:
  - Laser at h=0.05–0.1: r_eff ≈ 0.05–0.3 mm.
  - Blue SL at h=0.1–0.2: 0.2–0.6 mm.
  - IR SL at h=0.3–0.5: 0.5–1.5 mm.
  - Phone LiDAR: 3–10 mm.
- **Simulation.** Three options, from most to least faithful:
  - **(a) Physically, by construction.** Raycast frames and fuse them with TSDF at voxel `h` and `sdf_trunc = 3–5·h`. Rounding then emerges naturally. Recommended.
  - **(b) SDF blur.** Voxelize the GT signed distance at h/2, apply a Gaussian filter (σ = r_eff/2) to the SDF, and run marching cubes. This gives convex rounding *and* concave fill. Use it as a fast path when frames are not simulated.
  - **(c) Point displacement.** For each point, compute the distance to the nearest sharp GT edge (dihedral > 30°). Within band r_eff, project the point onto a virtual fillet of radius r_eff. This is cheap but too clean, so add noise.
  - Randomize **[scan]**. Optionally modulate **[region]** by ±30%, since edges perpendicular to the scan baseline round more (anisotropy from Abbasinejad).
  - Optionally add an **overshoot lip**: a small ridge of 0.02–0.1 mm, 1–2·h wide, before falling edges. It comes from both laser triangulation and over-aggressive sharpening (see 2.24).

### 2.4 Chamfer/bevel loss and small-feature dropout (threads, text, knurls, thin ribs)

- **Mechanism.** Features smaller than ~2–3·h fall below the fusion grid's Nyquist limit and below the smoothing/simplification scales. Holes with diameter below ~2–4·h close up, either by the TSDF or by "fill small holes" defaults.
  - The Creality wiki notes that too large a point distance "may cause some parts of the model to be missing" ([Creality wiki, CN](https://wiki.creality.com/zh/3d-scanner/crealityscan/pointcloud-fusion)).
  - EXStar's Filter "High … will lose some small details" ([EXStar docs](https://docs.shining3d.com/exstar/1.2.2/en-us/mesh/)).
- **Signature.**
  - Threads become a shallow sinusoid or a smooth cylinder at major/pitch diameter.
  - Embossed or engraved text < 0.2–0.3 mm deep vanishes on IR scanners.
  - Small chamfers (< 0.5 mm) disappear.
  - Small through-holes (< 1–2 mm) close or become dimples.
  - Knurling becomes a uniform bumpy texture.
- **Magnitude.** Feature survival probability is roughly a smooth step in `size/h`:
  - p≈0 for `size < 1·h`.
  - p≈0.5 at ~2·h.
  - p≈1 for `size > 4·h` [est].
  - Depth of a surviving feature is attenuated by a factor `1 − exp(−(size/(2h))²)` [est].
- **Simulation.**
  - This emerges from TSDF/Poisson at the right `h`, so ensure GT tessellation is fine enough (chord tolerance ≤ h/4).
  - Small holes: explicitly close CAD holes with dia < `U(1.5, 4)·h`. With hole filling on, also close holes up to the profile's `fill_small_hole` threshold.
  - Threads: if the STEP carries cosmetic threads only, decide whether GT has modeled threads at all, because scan GT must match what's physically there.

### 2.5 Thin-wall merging / thickening / perforation

- **Mechanism.** Several mechanisms:
  - **TSDF.** Integration with truncation `μ` lets opposite faces of a wall thinner than ~2μ write conflicting signed distances into the same voxels. The wall gets eroded (holes, "perforated" thin regions) or the zero crossing shifts.
  - **Poisson.** A sheet thinner than one octree cell has opposing normals that cancel, giving holes or a single blobby thick sheet.
  - **Unwatertight (connectivity) meshing.** The two sides can be stitched together.
- **Signature.**
  - Thin fins and walls (< ~0.5–1.5 mm on consumer settings) show holes or ragged edges, or become thicker than GT.
  - Two close parallel walls (e.g. a slot < 2·h wide) merge into one solid.
- **Magnitude.**
  - Critical thickness `t_c ≈ 2–4·h` for TSDF (with μ = 3–5·h).
  - For Poisson, `t_c ≈ 1–2 octree cells` [est].
  - Thickening ≈ +0.5–1.5·h [est].
- **Simulation.** Emerges from TSDF with realistic `μ`. In the SDF-blur path, it emerges if the blur σ is ≥ t/2. Also add an explicit "slot-closing" step: morphological closing of the occupancy grid with radius `U(0.5, 1.5)·h`.

### 2.6 Occlusion holes (deep pockets, bores, undercuts, line-of-sight limits)

- **Mechanism.** Each point needs line of sight from the camera **and** the projector/laser, at incidence < θ_max, within the working-distance window. A bore of depth D and diameter d is only illuminated and seen down to roughly `D_vis ≈ d / tan(α)`, where α is the camera–projector angle. Triangulation angles are typically 15–30°, so `D_vis ≈ 2–4·d` [est]. Narrow slots and blind holes are therefore missing at the bottom.
- **Signature.**
  - Bores open with ragged boundaries at partial depth.
  - Internal corners of pockets are missing.
  - The bottoms of deep holes are missing, or capped by hole filling (see 2.21).
- **Magnitude.** Depends on geometry. Fraction of GT area missing on typical mechanical parts: 1–15% [est].
- **Simulation.**
  - Raycast with Open3D `RaycastingScene` from each camera pose. Keep points that are also visible from the projector origin(s), offset by baseline `b` ∈ [40, 150] mm, and have θ < θ_max.
  - Randomize θ_max **[scan]** ∈ [65°, 85°] with a soft rolloff: rejection probability is logistic in θ.
  - This is Berger's approach: reject points not visible from the laser ([Berger 2013](https://matthewberger.github.io/papers/bench.pdf)).

### 2.7 Support-surface / underside holes and turntable remnants

- **Mechanism.** The part sits on a turntable or table. The contact face is never seen. Users either:
  - (a) accept the hole;
  - (b) flip the part and merge two scans, which introduces registration seams (2.13); or
  - (c) let watertight meshing cap the bottom.
  
  The table plane is captured and removed by plane fit: CrealityScan has auto plane removal and manual 3-point plane removal ([Creality Scan 4](https://store.creality.com/blogs/tutorial/creality-scan-4-3d-scanning-software)). The cut is either slightly too high, which chops the part's bottom, or too low, which leaves a skirt. Marker turntables leave marker-dot islands.
- **Signature.**
  - An open bottom with a jagged boundary at the plane height.
  - Or a thin flange or skirt 0.2–2 mm tall around the base (plane remnant fused to the part).
  - Or a flat or slightly domed Poisson cap.
  - Floating flat islands (turntable patches) if not cleaned.
- **Magnitude.**
  - Plane-cut height error ~ `U(−0.5, +1.5) mm` relative to the true base [est].
  - The unseen band above the base is 0.2–2 mm, because grazing angles and table shadow hide the bottom of vertical walls [est].
  - Remnant flange width is 1–5 mm [est].
- **Simulation.** **[scan]**
  - Choose a support face: pick the largest planar face, or simulate a stable resting pose by convex-hull face plus center of mass.
  - Add a finite disk plane (turntable, radius 50–150 mm) to the raycast scene.
  - After fusion, plane-cut at `z_cut = z_base + δ`. With probability p_skirt, keep a ring of plane points within r_skirt of the part.
  - With probability `p_flip` ∈ [0.3, 0.7], add a second pass in a flipped pose and merge it with a registration error.

### 2.8 Missing data on reflective, dark, and transparent surfaces

- **Mechanism.**
  - **Specular surfaces** reflect the pattern away from the camera, giving no signal. Near the mirror direction they saturate the sensor (blooming), giving a decode failure.
  - **Dark surfaces** (black anodizing, black PLA, rubber) absorb light, giving low SNR, more noise, then rejection. Revo Scan has a dedicated "Dark Object" mode and warns black leather can fail ([Revo Scan manual](https://www.machines-3d.com/images/Image/File/Manuel/Scanner%203D/Miraco/1218-PC-Revo-Scan-User-Manual.pdf)).
  - **Transparent surfaces** return no data, or data from surfaces behind them.
  - Mixed shiny and black parts break auto-exposure. CNC Kitchen's carburetor confused Metro Y exposure between shiny metal and black rubber ([CNC Kitchen](https://cnckitchen.com/blog/creality-raptor-pro-vs-revopoint-metro-y-pro)).
- **Signature.**
  - Holes and sparse speckled patches on polished faces.
  - The hole pattern is view-dependent: blotches where the surface normal bisects the camera and projector directions.
  - Whole faces missing on chrome or glass.
  - Noisier patches on dark faces.
- **Magnitude.** Per-point drop probability:
  - Matte light: 0–2%.
  - Dark matte: 5–40%.
  - Machined aluminum: 20–70%.
  - Polished/chrome: 60–100% (blue LED SL); laser is ~half that.
  - Transparent: ~100% [est].
- **Simulation.**
  - Assign **[region]** materials per CAD face: `albedo` ∈ [0.03, 0.9], `specular` ∈ [0, 1], `roughness`, `transparent` flag.
  - For each frame point compute the half-vector angle `β` between the surface normal and the bisector of the camera and projector directions.
  - Drop probability:
    ```
    p_drop = 1 − (1 − p_dark(albedo)) · (1 − p_sat(β, specular, roughness)) · (1 − p_lowsig(θ, specular))
    p_sat   ≈ specular · exp(−β² / (2·w²)),  w ≈ 3°–15° (roughness)
    p_lowsig: specular surfaces return little diffuse light at all angles away from the lobe
    ```
  - Apply drops as **spatially coherent blobs**, not i.i.d.: threshold a smooth noise field plus p_drop.
  - Because handheld users wave the scanner around, each view gives different blobs. Fusion therefore fills many of them, leaving holes where *all* views failed.
  - Spray (2.16) sets `specular→0, albedo→0.8` and adds thickness.

### 2.9 Specular spikes, inter-reflection ghosts, false surfaces

- **Mechanism.**
  - Inter-reflection in concave shiny regions (inside corners, bores, fillets) makes a secondary bounce of the pattern or laser line look like the primary, so the wrong correspondence is triangulated ([BMVC 1995](https://bmva-archive.org.uk/bmvc/1995/bmvc-95-051.pdf); [patent US9482514 "multipath interference in 3D scanners"](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/9482514)).
  - Saturated glints decode to wrong phase, giving isolated spikes.
- **Signature.**
  - Spikes or "hair" sticking out along view rays.
  - Phantom surfaces floating inside bores or behind concave corners (often a mirrored copy of the adjacent wall).
  - Bumps on polished fillets.
- **Magnitude.**
  - Displacement 0.1–1 mm (0.8 mm metal example in [Opt. Precision Eng. 2025](https://m.researching.cn/articles/OJ1255d1062587be92)), occasionally several mm.
  - Affected fraction 0.1–5% of points on shiny concave regions [est].
- **Simulation.** **[point]**, in shiny concave regions.
  - Trace a mirror bounce: reflect the camera ray at the hit point and intersect the scene again.
  - If the second hit is within the projector's view, emit a point at the *wrong* triangulated depth. A cheap approximation is a point along the original camera ray, displaced by `±U(0.1, 2) mm`.
  - Spike outliers: with probability p_spike ∝ p_sat, displace depth by Laplace(0, 0.3–2 mm).
  - Many get removed by fusion and outlier filters, so simulate before fusion and let the pipeline prune.

### 2.10 Flying / mixed pixels and edge fringes at depth discontinuities

- **Mechanism.**
  - In ToF, one pixel straddles foreground and background and reports an interpolated depth.
  - In SL/stereo, the correlation or decoding window straddles an edge, which causes edge fattening and smearing toward the background.
  - Per-frame boundaries are frayed. EXStar's mesh option "Remove spike: removes spike-like data at image edges" exists because of this ([EXStar docs](https://docs.shining3d.com/exstar/1.2.2/en-us/mesh/)).
  - Frayed scan edges used to cause seams in multi-orientation merges ([CNC Kitchen](https://cnckitchen.com/blog/creality-raptor-pro-vs-revopoint-metro-y-pro)).
- **Signature.**
  - Raw clouds: a veil or "skirt" of points between a silhouette edge and the background, along view rays.
  - Fused meshes: residual burrs, fins and frayed edges along silhouette-prone sharp edges.
- **Magnitude.**
  - Raw clouds: 1–3 px band around each depth discontinuity, with 10–50% of band pixels affected [est].
  - After fusion: fin height 0.05–0.5 mm on SL scanners [est].
- **Simulation.** **[frame]**, in image space.
  - Detect depth discontinuities (|Δz| > τ between neighboring pixels).
  - In the k-px band, replace the depth with `z = α·z_fg + (1−α)·z_bg` (α ~ U(0,1)) for ToF. For SL, dilate the foreground by 1–2 px with extrapolated depth (edge fattening).
  - Also mark 0–2 px at frame borders as low-confidence and drop them, unless the profile has `remove_spike = False`.

### 2.11 Outlier clusters (background, turntable, hands, clamps, putty)

- **Mechanism.** Anything in the measuring volume gets scanned: tabletop, turntable, the user's fingers holding the part, Blu-Tack or clay supports, a stand, marker boards. Cleanup is manual (lasso, clipping plane, connected components) or automatic. Examples:
  - Revo Scan point-cloud and mesh "Isolation" with radius/angle/rate ([manual](https://www.machines-3d.com/images/Image/File/Manuel/Scanner%203D/Miraco/1218-PC-Revo-Scan-User-Manual.pdf)).
  - EXStar "Remove small floating parts", isolated-data ratio default 1 on a 0–100 scale ([EXStar docs](https://docs.shining3d.com/exstar/1.2.2/en-us/mesh/)).
  - CrealityScan connected components and isolated-point removal ([Creality scan-to-print](https://wiki.creality.com/en/3d-scanner/tutorials/general/scan-to-print)).
- **Signature.**
  - Floating islands of points or mesh shells near the part.
  - Blobs *attached* to the part where supports touched it. Attached blobs survive "remove floating parts".
- **Magnitude.**
  - 0–5 islands per scan surviving cleanup, size 1–30 mm [est].
  - Attached support blob with probability ~0.05–0.2 per scan [est].
- **Simulation.**
  - Insert distractor geometry into the raycast scene **[scan]**: turntable disk, a box corner, a capsule "finger", a putty blob at a contact point.
  - Then run a cleanup step with randomized aggressiveness. This yields realistic survivors, e.g. small islands under the size threshold and attached blobs that are never removed.

### 2.12 Multi-frame registration drift (handheld tracking)

- **Mechanism.**
  - Frame-to-frame tracking uses geometry (ICP), texture features, or markers. Each step has a small pose error, which accumulates as a random walk. Small pose errors build up scan after scan ([FARO KB](https://knowledge.faro.com/Hardware/3D_Scanners/Freestyle_2/Correcting_Freestyle2_Scan_Misalignments)).
  - **Tracking loss and relocalization** on symmetric or featureless geometry places frames at a wrong pose, so the scanner "thinks it's somewhere else" and produces a double or ghost ([Revopoint forum](https://forum.revopoint3d.com/t/ignoring-images-by-meshing-generated-while-tracking-loss-in-continous-mode/31013)).
  - Users must delete misaligned frames; some software can't re-run alignment ([Revopoint forum](https://forum.revopoint3d.com/t/feature-request-separate-mistracked-frames/11432)).
  - Marker tracking reduces both effects.
- **Signature.**
  - (a) Smooth low-frequency warp: bent long parts, slightly elliptical cylinders.
  - (b) Ghost/double surfaces offset by a fraction of a mm to mm.
  - (c) Onion-skin layering: several near-parallel sheets where passes overlap.
  - (d) "Bumpy" texture where merged scans overlap ([Revopoint forum](https://forum.revopoint3d.com/t/surface-is-bumpy-where-merged-scans-overlap/23285)).
- **Magnitude.**
  - Continuous drift: budget from the volumetric spec `b` (0.04–0.3 mm/m) for marker or laser tracking. For feature/geometry tracking on featureless CAD parts it is 3–10× worse [est].
  - Per-frame step noise: σ_t ≈ 0.002–0.02 mm, σ_r ≈ 0.001°–0.01° per frame at 10–60 fps [est, back-solved from spec].
  - Discrete jumps: probability 0–0.3 per scan for feature tracking, ~0 with markers. Size 0.1–3 mm translation and 0.1–3° rotation [est].
- **Simulation.** **[frame]**
  - Generate the trajectory. Perturb poses with a correlated random walk (integrated Ornstein–Uhlenbeck) plus Poisson-distributed jump events. A jump is applied to a contiguous run of frames, until "re-tracking", then the walk continues from the wrong pose.
  - Integrate frames into TSDF with the **perturbed** poses:
    - Offset < ~μ: the result is thickened, bumpy surfaces.
    - Offset > μ: the result is double sheets (onion skin), exactly the real signature.
  - Optional realism: run real Open3D ICP / multiway pose-graph optimization from perturbed initializations. The residuals then have the true structure (local minima on symmetric parts). Berger did this, with LW-ICP from random rotations, noting that "less overlap means a poorer initialization … causing misalignment" ([Berger 2013](https://matthewberger.github.io/papers/bench.pdf)).

### 2.13 Seam steps between passes / merge misalignment

- **Mechanism.** Separate scans (top and bottom, or several orientations) are merged by feature or marker alignment. Revo Scan merges need ≥10% overlap, or ≥3 manually picked points for marker merges ([manual](https://www.machines-3d.com/images/Image/File/Manuel/Scanner%203D/Miraco/1218-PC-Revo-Scan-User-Manual.pdf)). CNC Kitchen needed a third "bridge" scan to merge controller halves. Residual rigid misalignment remains.
- **Signature.**
  - A step or ridge along the overlap boundary.
  - A double layer in the overlap.
  - A slight tilt of one half.
- **Magnitude.** Residual 0.02–0.1 mm (laser with markers), 0.05–0.3 mm (SL with features), 0.3–2 mm (failed or poor merges) [est]. CNC Kitchen's comparison scans of the same part on two scanners deviated ~±0.05 mm, which bounds good-case merges [meas].
- **Simulation.** **[scan]**
  - Apply a rigid transform to pass B: rotation ~ N(0, σ_r) about the overlap centroid, translation ~ N(0, σ_t).
  - Fuse both passes. Optionally keep the overlap as a **non-fused** union, where the vendor merges meshes without re-fusion, to get an explicit double sheet.

### 2.14 Loop-closure error

- **Mechanism.** On a 360° handheld orbit, the last frames meet the first. Accumulated drift appears as a discontinuity at the closure. Global optimization (bundle adjustment / pose graph) spreads the error around the loop, turning a step into warp.
- **Signature.**
  - Without global optimization: a single seam step on one side of the part.
  - With it: mild ovality or twist.
- **Magnitude.** The loop residual before optimization is about the drift accumulated over the path length; for a 200 mm part orbit (path ~0.6–1.0 m) that is 0.03–0.3 mm with markers and 0.1–2 mm with feature tracking [est]. After global optimization, the residual is 20–50% of that, distributed around the loop [est].
- **Simulation.** **[scan]**
  - Generate drift as in 2.12, then optionally apply loop closure: linearly distribute the end-pose error back over the trajectory (a simple pose-graph surrogate), leaving a residual fraction `U(0.1, 0.5)`.

### 2.15 Global scale error

- **Mechanism.**
  - Calibration error in baseline or focal length.
  - Thermal expansion of the scanner body: CNC Kitchen recommends ≥10 min warm-up and letting the calibration plate acclimatize ([CNC Kitchen](https://cnckitchen.com/blog/creality-raptor-pro-vs-revopoint-metro-y-pro)).
  - Photogrammetry has no metric scale until it is rescaled.
- **Signature.** The whole part is uniformly too big or small, possibly anisotropic (slightly different in x, y, z).
- **Magnitude.**
  - Good SL/laser: 0.01–0.05% (0.02–0.1 mm on 200 mm).
  - Consumer SL, uncalibrated or cold: 0.05–0.3%.
  - Phone LiDAR: 0.5–3%.
  - Photogrammetry after manual rescale: 0.1–1% [est, consistent with spec `b` terms and the SAE LiDAR bias].
- **Simulation.** **[scan]**
  - `S = diag(1+ε_x, 1+ε_y, 1+ε_z)`, with ε ~ N(0, σ_s) plus a small shared component.
  - Apply S after fusion, about the centroid. Keep S in metadata: for the ScanRuler use case, scale error directly corrupts measured dimensions.

### 2.16 Tracking-marker artifacts (stickers on the part)

- **Mechanism.** Retro-reflective dot stickers are applied to the part for marker tracking. Software masks the marker area out of the surface, leaving a hole. It may then fill "marker holes", as in EXStar's "Marker hole fill: fills unscanned surface areas up to the marker stickers", on by default for unwatertight/semi-watertight in Markers mode ([EXStar docs](https://docs.shining3d.com/exstar/1.2.2/en-us/mesh/)). Unmasked markers leave raised discs because the sticker has thickness.
- **Sizes.**
  - Common "3 mm" markers have a 3 mm dot inside a 6 mm ring, ~0.15 mm thick (PET).
  - Revopoint's "6 mm" markers are 6 mm inner and 10 mm outer.
  - Einstar wants 8–15 markers per frame (min 4) on flat areas ([Einstar](https://www.einstar.com/products/3d-scanner-3mm-markers); [Filaform](https://www.3dprintergear.com.au/filaform-3d-scanning-reflective-marker-stickers-3m)).
  - Revo Scan marker mode needs ≥5 markers in view ([manual](https://www.machines-3d.com/images/Image/File/Manuel/Scanner%203D/Miraco/1218-PC-Revo-Scan-User-Manual.pdf)).
- **Signature.**
  - Circular holes 3–10 mm across, mostly on flat faces, spaced 20–60 mm apart in a loose irregular pattern.
  - Or flat or slightly domed circular plugs (filled holes, slightly off-plane).
  - Or 0.1–0.2 mm raised discs, which CNC Kitchen saw as leftover marker geometry on several Metro Y parts.
- **Magnitude.**
  - Hole diameter ∈ {3, 5, 6, 10} mm ± 0.3.
  - Bump height 0.1–0.2 mm.
  - Spacing such that 5–15 markers fall in a ~100–250 mm FOV [spec].
- **Simulation.** **[region]**, on flat or low-curvature faces.
  - Poisson-disk sample marker centers with spacing `U(20, 60) mm`. Avoid edges by ≥ marker radius plus 1 mm.
  - Per marker, choose a mode:
    - `hole` (p≈0.5–0.8).
    - `filled_flat` with a small offset of ±0.02 mm and a visible boundary ring of slightly different triangle density.
    - `bump` (+0.1–0.2 mm disc).
  - Apply only when profile tracking is `marker` and markers are on the part. Markers on the turntable or a backdrop produce no artifact on the part.

### 2.17 Scanning spray (AESUB and chalk/developer) thickness effects

- **Mechanism.** The coating adds material and makes the surface matte, which removes reflection dropout.
  - AESUB Blue layers are **8–15 µm**, with older datasheets saying 5–15 µm ([AESUB TDS](https://test.3dmart.com.tw/en/upload/2020AESUBBlue/Technical_Datasheet_AESUB_blue.pdf)). It sublimes in ~4 h.
  - Chalk-type spray measured **~44 µm**, about 10× a titanium-powder coating ([MM Science 2025](https://www.mmscience.eu/journal/issues/september-2025/articles/influence-of-the-measurement-of-anti-reflective-coating-layer-for-optical-measuremnt/download)).
  - Eight sublimating sprays all produced layers "in the order of tens of micrometers" detectable by an ATOS III ([Franke et al. 2023, Materials 16:6165](https://www.mdpi.com/1996-1944/16/18/6165)).
  - CNC Kitchen warns the coating adds a measurable layer and should be thin.
- **Signature.**
  - Uniform outward offset, i.e. a thicker part and smaller holes.
  - Slight extra rounding of sharp edges and filling of fine texture.
  - Uneven coats give orange-peel and pooled runs in concave corners.
- **Magnitude.**
  - Thickness t ∈ [5, 60] µm, mean ~15 µm for sublimating sprays and ~40 µm for chalk/developer [meas].
  - Spatial variation ±30–50% with correlation length 5–30 mm [est].
  - Up to 2× in concave corners [est].
- **Simulation.** **[region/point]**
  - Offset GT surface samples by `t(x)·n`, where t is a smooth random field.
  - Add a small curvature-dependent term: more in concave regions, less on convex edges.
  - Set material to diffuse.
  - Correlate with the profile: spray probability is high for laser/metrology users and shiny parts, low for budget users.

### 2.18 Non-uniform sampling density

- **Mechanism.**
  - **Raw clouds.** Density ∝ (frames seeing the patch) × cos θ / z². Overlap regions are dense, grazing regions sparse.
  - **Fused clouds.** Resampled to the voxel grid at spacing ≈h, so near-uniform but grid-aligned. A watertight scan exported as a mesh has ~uniform triangle size, except where decimation coarsens flats.
- **Signature.**
  - Raw: density banding following the scan path.
  - Fused: regular spacing with axis-aligned aliasing (a "voxel staircase") on gently sloped faces.
- **Magnitude.** Raw density varies 3–20× across the part [est].
- **Simulation.** Emerges from frame simulation. For a frame-free fast path, sample GT with density `ρ ∝ Σ_views cos θ/z²` and then voxel-downsample.

### 2.19 Banding / striping / waviness

- **Mechanism.**
  - **Phase-shift SL.** Projector gamma nonlinearity and phase error give periodic ripple at harmonics of the fringe period ([SPIE 9526 phase error analysis](https://nanophotonics.spiedigitallibrary.org/conference-proceedings-of-spie/9526/952608/Phase-error-analysis-and-compensation-in-fringe-projection-profilometry/10.1117/12.2184638.full)).
  - **Laser lines.** Per-line peak bias gives stripes parallel to the lines (Berger's "bumps aligned with the laser projection").
  - **Handheld fusion.** Exposure or temperature changes between passes give bands along the sweep.
- **Signature.** Faint periodic ripples visible under raking light on flat faces. They are often the most obvious "real scan" tell on flat CAD faces.
- **Magnitude.** Amplitude 0.005–0.05 mm, period 0.5–5 mm (SL fringe) or the line pitch (laser) [est].
- **Simulation.** **[frame]** add `A·sin(2π·u/λ + φ)` along the projector's coding axis `u`, which is fixed in sensor coordinates. Per frame, randomize the phase φ slightly. Fusion then partially averages it out, which is realistic.

### 2.20 Hole-fill artifacts (flat caps, bulging caps, wrinkles)

- **Mechanism.**
  - **Watertight Poisson** extrapolates an implicit surface over gaps, producing smooth bulging "balloon" caps that follow surrounding curvature. EinScan notes watertight meshing can produce unwanted shapes: a box with a missing bottom got a wrongly closed bottom ([EinScan](https://www.einscan.com/news/watertight-or-unwatertight-its-a-question/)).
  - **Explicit hole filling** has two kinds:
    - Revo Scan's "Plane or Curve fill"; Auto fill "with a curved surface" under a ratio ([manual](https://www.machines-3d.com/images/Image/File/Manuel/Scanner%203D/Miraco/1218-PC-Revo-Scan-User-Manual.pdf)).
    - MeshLab-style ear clipping (flat triangle fans).
  - **Size thresholds:**
    - EXStar semi-watertight fills holes with diameter ≤ 5× resolution ([EXStar 1.0.5](https://docs.shining3d.com/exstar/1.0.5/en-us/mesh/)).
    - EXStar "Fill small hole" defaults to 10, range 0–100.
    - Artec fills by radius, by perimeter (e.g. 100 mm in the post-processing tool), or fully watertight ([Javelin](https://www.javelin-tech.com/blog/2022/04/3d-scanning-tech-tip-hole-filling-options-in-artec-studio/)).
- **Signature.**
  - **Flat caps:** polygonal flat facets with fan triangulation and a visible crease at the boundary.
  - **Curved caps:** domes or saddles overshooting the true surface.
  - **Watertight bottoms:** pillow-shaped.
  - **Bores:** capped at partial depth with a dome.
  - **Large missing regions:** "wired"/wrinkled patches.
- **Magnitude.**
  - Bulge height ≈ 0.05–0.3 × hole diameter for Poisson caps [est].
  - Flat caps deviate by the local curvature sagitta.
- **Simulation.** **[scan]** choose a fill mode from {none, flat (`trimesh.repair.fill_holes` / PyMeshLab `meshing_close_holes`), smooth (close plus refine plus Laplacian fair, or a local Poisson patch), watertight (screened Poisson on everything)}. Randomize the size threshold.

### 2.21 Over-smoothing

- **Mechanism.** Smoothing happens at several points:
  - EXStar has Filter {None, Standard, Med, High} and Smooth {Standard, Med, High}.
  - Artec offers Smooth Fusion or the Smart-fusion "Smooth" sharpness.
  - Revo Scan Smooth can be repeated ([manual](https://www.machines-3d.com/images/Image/File/Manuel/Scanner%203D/Miraco/1218-PC-Revo-Scan-User-Manual.pdf)).
  - CrealityScan has mesh smoothing ([Creality Scan 4](https://store.creality.com/blogs/tutorial/creality-scan-4-3d-scanning-software)).
  
  Laplacian smoothing shrinks volume. Taubin does not shrink but still rounds features.
- **Signature.**
  - Soft edges and lost small features.
  - Shrinkage: undersized outer dimensions and oversized holes, if Laplacian.
  - "Melted" text.
- **Magnitude.**
  - 0–30 Taubin iterations (λ=0.5, μ=−0.53) or 0–10 Laplacian iterations.
  - Shrinkage of convex regions ~0.01–0.1 mm per Laplacian iteration at h≈0.2 mm [est].
- **Simulation.** **[scan]**
  - Smoothing level ∈ {0, 1, 2, 3}, mapped to iterations and algorithm (Taubin p=0.6, Laplacian p=0.25, HC p=0.15).
  - Optionally restrict it to low-confidence areas, which is what EXStar "Standard" seems to do.

### 2.22 Sharpening artifacts

- **Mechanism.**
  - Artec Sharp fusion "sharpening of fine geometry" ([UMD guide](https://dozuki.umd.edu/Guide/Post-Processing+in+Artec+Studio/86)).
  - EXStar Filter High "reduces noise and sharpens strongly".
  - Unsharp masking on geometry creates overshoot.
- **Signature.**
  - Raised lips or ridges along edges.
  - Grooves just inside them (halo).
  - Exaggerated noise on flats if applied blindly.
- **Magnitude.** 0.02–0.15 mm overshoot [est].
- **Simulation.** **[scan]**, with probability ~0.2: PyMeshLab `apply_coord_unsharp_mask`, or `x + k·(x − Laplacian_smooth(x))` with k ∈ [0.2, 1].

### 2.23 Decimation faceting

- **Mechanism.** Several sources:
  - QEM edge-collapse decimation to a triangle budget. EXStar "Simplification" defaults to 40 when point distance ≤ 0.5 mm, and "Max triangles" is enabled by default ([EXStar docs](https://docs.shining3d.com/exstar/1.2.2/en-us/mesh/)).
  - Revo Scan Simplify.
  - CrealityScan mesh decimation.
  - The user's own export decimation.
- **Signature.**
  - Large slivers on planes.
  - Polygonal (faceted) cylinders and fillets.
  - Chordal error concentrated on curved regions.
  - Triangle-size distribution becomes strongly bimodal.
- **Magnitude.**
  - Target 10–60% of faces, or a hard budget of 100k–2M triangles.
  - Chordal deviation 0.005–0.1 mm [est].
- **Simulation.** **[scan]**
  - Open3D `simplify_quadric_decimation`, PyMeshLab `meshing_decimation_quadric_edge_collapse` (quality threshold 0.3, optional boundary preservation), or `fast-simplification`.
  - Probability ~0.6. Ratio ∈ [0.1, 0.8].

### 2.24 Mesh-topology defects: non-manifold, flipped normals, self-intersections, islands

- **Mechanism.**
  - Ball pivoting and connectivity ("unwatertight") meshing create non-manifold edges and vertices, small holes and overlapping fans.
  - Normal orientation by MST propagation flips large regions near sharp features. Berger notes Hoppe orientation "may result in large regions of inverted normals due to sharp features and nonuniform sampling" ([Berger 2013](https://matthewberger.github.io/papers/bench.pdf)). Flipped normals make Poisson produce sheets or inside-out bubbles.
  - Hole filling and decimation create fold-overs and self-intersections.
  - Merging meshes without re-fusion gives intersecting shells.
  - Leftover islands come from cleanup thresholds.
- **Signature.** In STL:
  - Inconsistent winding.
  - Zero-area faces.
  - Duplicate vertices (STL is a triangle soup).
  - Inner shells.
  - Bubbles.
  - Small detached shells.
- **Magnitude.** Typical vendor exports are mostly manifold, but [est]:
  - 0–0.1% non-manifold edges.
  - 0–3 islands.
  - Occasional 1–5% flipped-normal patches in BPA pipelines.
- **Simulation.** Mostly emergent from choosing BPA or naive orientation. Add a final **[scan]** defect injector with small probabilities:
  - Flip the winding of a connected patch.
  - Duplicate a strip of faces.
  - Add a tiny inner shell.
  - Leave 1–3 islands.
  - Leave a T-junction seam.
  
  Validate with `trimesh` (`is_watertight`, `is_winding_consistent`) and PyMeshLab selection filters `compute_selection_by_non_manifold_edges_per_face` / `compute_selection_by_self_intersections_per_face`.

### 2.25 Disconnected shells / islands of the part itself

- **Mechanism.** Thin bridges that were poorly captured, or a misregistered pass, split the part into several shells. Small separate CAD bodies (pins, inserts) may be merged or lost.
- **Simulation.** Emergent. Ensure cleanup's "remove small components" does not always keep exactly one shell.

---

## 3. Vendor meshing pipelines

### 3.1 Common skeleton

All consumer/prosumer packages follow roughly the same order. Inference: Revo Scan's own terms, "voxel fusion" for Standard and "fitting fusion" for Advanced, together with the point-distance semantics in every package, strongly suggest TSDF-style voxel fusion followed by an implicit or Poisson-type watertight mesher. Vendors do not publish algorithm internals.

| # | Step | What vendors do | User-facing options (examples) |
|---|---|---|---|
| 1 | Capture and live tracking | Per-frame depth. Pose by geometry ICP, texture features, or markers. Frames lost or re-tracked. | Tracking mode: Geometry / Texture / Marker (CrealityScan, [Scan 4](https://store.creality.com/blogs/tutorial/creality-scan-4-3d-scanning-software)); Feature / Marker, "≥5 markers in view" (Revo Scan); accuracy mode Standard / High / High-speed 18 fps (Revo Scan); object type General / Dark (Revo Scan); exposure / laser brightness |
| 2 | Frame cleanup | Delete mis-tracked frames, crop. | Revo Scan frame removal ("double noses or ghosting", [forum](https://forum.revopoint3d.com/t/windows-mac-revo-scan-v5-3-0/22085)) |
| 3 | Global optimization | Pose-graph / bundle adjustment over keyframes and markers; loop closure. | Usually implicit; "optimize" toggles |
| 4 | Fusion (to a point cloud at spacing h) | Voxel/TSDF fusion (fast) or fitting/MLS fusion (detail). | **Point distance** (CrealityScan: 0.1 mm good default, 0.02 mm costly, larger for big parts ([wiki](https://wiki.creality.com/en/3d-scanner/crealityscan/pointcloud-fusion))); fusion Standard vs Fast for blue laser (Fast = sharper edges, Standard = more complete); Revo Standard (voxel) vs Advanced (fitting); Revo merge needs point-distance ratio ≤ ~5:1 |
| 5 | Point-cloud edit | Outlier / isolation removal, overlap detection, plane removal, smoothing, simplify. | Revo: Isolation (radius / angle / rate), Overlap Detection (distance), Smooth, Simplify; CrealityScan: plane removal (auto / 3-point), isolated points, connected components |
| 6 | Multi-scan merge | Feature or marker or manual N-point alignment, then re-fusion. | Revo Merge: feature (≥10% overlap, ≤9 scans) or 3-point marker |
| 7 | Meshing | Watertight (implicit / Poisson-like, fills everything) vs non-watertight (connect points within a distance, no fill), sometimes semi-watertight. | EXStar: Unwatertight / Semi-watertight / Watertight, with quality High / Med / Low only for watertight ([docs](https://docs.shining3d.com/exstar/1.2.2/en-us/mesh/)); Revo: Mesh Quality level, Hole Filling (Auto) by ratio; Artec: Fast / Sharp / Smooth fusion, or Smart fusion with Sharpness toggle (AS18+); resolution ≥ worst Max Error, Spider 0.15–0.3 mm ([Artec guide via search](https://support.artec3d.com/hc/en-us/article_attachments/202201012)); hole fill by radius or watertight |
| 8 | Mesh optimization | Filter (denoise / sharpen), smooth, remove floating parts, remove spikes, fill small holes, marker-hole fill. | EXStar: Filter None / Standard / Med / High; Smooth Standard / Med / High; Remove small floating parts (ratio default 1, range 0–100); Fill small hole (default 10, range 0–100, not for watertight); Remove spike; Marker hole fill; Recommended parameters toggle |
| 9 | Simplification | QEM-type decimation. | EXStar Simplification (default 40 if h ≤ 0.5 mm, else off at 20) plus Max triangles; Revo Simplify; CrealityScan decimation |
| 10 | Manual repair | Fill holes individually (flat or curved), bridge, cut planes. | Revo "File Holes" Plane / Curve fill; Artec Fix Holes by perimeter; Creality manual hole filling (v3.3+) |
| 11 | Texture (ignored for STL) | — | — |
| 12 | Export | STL / OBJ / PLY / 3MF, sometimes "one-click". | CrealityScan and Revo one-click processing pick parameters automatically ([Creality scan-to-print](https://wiki.creality.com/en/3d-scanner/tutorials/general/scan-to-print)) |

### 3.2 Per-package notes

- **CrealityScan (Raptor, Otter, Ferret).**
  - Steps: tracking (geometry / texture / marker), then point-cloud fusion (point distance; Standard or Fast in laser mode), then point editing (plane removal, isolated points, connected components), then meshing, then hole filling (auto and manual), smoothing, decimation, then STL export.
  - It shows live coverage feedback (yellow to blue once an area has enough data, [CNC Kitchen](https://cnckitchen.com/blog/creality-raptor-pro-vs-revopoint-metro-y-pro)), so typical user scans have **uneven but complete-ish coverage** on visible faces.
  - The UNBC Raptor Pro guide's quality bar: "No visible drift or doubled walls … holes and grooves preserved" ([UNBC](https://sparklab.unbc.ca/?p=955)). These are exactly the failure modes users fight.
- **Revo Scan / Revo Studio (POP, MINI, MIRACO, RANGE, MetroX).**
  - Steps: Standard (voxel) or Advanced (fitting) fusion at a suggested point distance, then Isolation, Overlap Detection, Smooth, Simplify on the cloud, then Mesh (quality level; auto hole fill by ratio with curved surface), then mesh Isolation, File Holes (plane/curve), Smooth, Simplify, then texture.
  - Forum tip: mesh at a grid matching the fusion point distance; meshing finer than fusion adds artificial points ([forum](https://forum.revopoint3d.com/t/how-to-proper-meshing-your-pointcloud/23472)).
  - Revo Design is the separate tool for watertight and CAD prep ([Revo Design](https://store.revopoint3d.com/de/pages/revo-design)).
- **EXStar / EXScan (Einstar, EinScan).**
  - The best-documented option set (above). The EinScan rationale: watertight meshing uses a detail level and "is able to predict and fill up large holes"; unwatertight "only connects points within a certain distance" ([EinScan](https://www.einscan.com/news/watertight-or-unwatertight-its-a-question/)).
- **Artec Studio.**
  - Steps: per-scan editing, then global registration, then outlier removal, then fusion, then small-object filter, then hole filling and fix holes, then smoothing, then mesh simplification.
  - Fusion types:
    - Fast fusion: preview, no hole fill.
    - Sharp fusion: default, smart hole filling and sharpening.
    - Smooth fusion: noisy subjects such as hair.
    - Smart fusion (AS18+): replaces these, with a Smooth/Sharp toggle.
  - Resolution guidance is tied to the scans' "Max Error" ([UMD guide](https://dozuki.umd.edu/Guide/Post-Processing+in+Artec+Studio/86), [Artec AS18 notes](https://support.artec3d.com/hc/en-us/articles/11108285755282-Artec-Studio-18-Release-notes)).
- **Polycam / RealityScan / Apple Object Capture.**
  - Photo mode: SfM, MVS, mesh, decimate, texture.
  - LiDAR mode: ARKit depth fused into a coarse TSDF-like mesh.
  - RealityScan offers watertight and non-watertight mesh outputs ([Epic tutorial](https://dev.epicgames.com/community/learning/tutorials/7dly/realityscan-non-watertight-meshes)).
  - Scale needs manual rescale in Polycam Object mode.
- **Meshroom (AliceVision).**
  - Pipeline: CameraInit, FeatureExtraction (DSP-SIFT), ImageMatching, FeatureMatching, StructureFromMotion, PrepareDenseScene, DepthMap, DepthMapFilter, **Meshing** (3D Delaunay tetrahedralization of fused depth points plus an s-t graph cut on visibility, giving a closed, often blobby surface), **MeshFiltering** (Laplacian smoothing, large-triangle removal), Texturing ([Meshroom manual](https://meshroom-manual.readthedocs.io/en/latest/feature-documentation/core/pipelines/photogrammetry.html)).
  - The graph-cut mesher gives a characteristic "shrink-wrapped" fill of concavities and occasional bubbles.

### 3.3 Python equivalents (for emulating each step)

| Step | Library calls |
|---|---|
| STEP to GT mesh | `cadquery-ocp` (already an optional dep): BRepMesh with linear deflection ≤ h/4 and angular ≤ 5°. Keep the face IDs so per-face materials, markers and sharp edges can be assigned. |
| Virtual sensor / raycast | `open3d.t.geometry.RaycastingScene`: `cast_rays` and `create_rays_pinhole` give depth, normals, primitive (face) IDs ([Open3D ray casting](https://www.open3d.org/docs/release/tutorial/geometry/ray_casting.html)). Projector visibility is a second `cast_rays` or `test_occlusions` from the projector origin. Alternative: `trimesh.ray` (embree when available). |
| Range noise, dropout, flying pixels | numpy/scipy on depth images (`scipy.ndimage.gaussian_filter` for correlated noise, `scipy.ndimage` morphology for edge bands) |
| Frame registration (realistic residuals) | `o3d.pipelines.registration.registration_icp` (point-to-plane / generalized ICP), `registration_ransac_based_on_feature_matching` with FPFH, `PoseGraph` + `global_optimization` (multiway registration) |
| TSDF fusion ("voxel fusion") | `o3d.pipelines.integration.ScalableTSDFVolume(voxel_length=h, sdf_trunc=3–5h, color_type=NoColor)` → `extract_point_cloud()` / `extract_triangle_mesh()`; or the GPU `o3d.t.geometry.VoxelBlockGrid` ([Open3D RGBD integration](https://www.open3d.org/docs/release/tutorial/pipelines/rgbd_integration.html)) |
| MLS / "fitting fusion" | PyMeshLab `generate_marching_cubes_apss` / `generate_marching_cubes_rimls`; or Open3D voxel downsample + normal-weighted averaging |
| Outlier / isolation removal | `pcd.remove_statistical_outlier(nb_neighbors, std_ratio)`, `pcd.remove_radius_outlier(nb_points, radius)`, `pcd.cluster_dbscan(eps, min_points)` (connected components); PyMeshLab `compute_selection_point_cloud_outliers` (LoOP, `propthreshold` 0.8, `knearest` 32) ([Open3D outliers](https://www.open3d.org/docs/release/tutorial/geometry/pointcloud_outlier_removal.html)) |
| Plane removal | `pcd.segment_plane(distance_threshold, ransac_n=3, num_iterations)`, then cut at an offset |
| Overlap detection / simplify | `pcd.voxel_down_sample(h)`; PyMeshLab `generate_simplified_point_cloud`, `generate_sampling_poisson_disk` |
| Normals | `pcd.estimate_normals` + `orient_normals_towards_camera_location` (correct) or `orient_normals_consistent_tangent_plane(k)` (Hoppe MST, which produces realistic flips); PyMeshLab `compute_normal_for_point_clouds` |
| Watertight meshing | `o3d.geometry.TriangleMesh.create_from_point_cloud_poisson(pcd, depth=8–11, scale=1.1, linear_fit)`, which returns densities; PyMeshLab `generate_surface_reconstruction_screened_poisson(depth, fulldepth, …)` (Kazhdan & Hoppe 2013) |
| Non-watertight meshing | (a) TSDF marching cubes (holes stay open); (b) Poisson + density trim (`remove_vertices_by_mask(densities < quantile(q))`, q ∈ [0.005, 0.1]); (c) `create_from_point_cloud_ball_pivoting(pcd, radii)` / PyMeshLab `generate_surface_reconstruction_ball_pivoting` (non-manifold-prone, like "connect points within distance"); (d) PyMeshLab `generate_surface_reconstruction_vcg` |
| Delaunay / graph-cut (photogrammetry-like) | No direct equivalent. Approximate with alpha shapes (`create_from_point_cloud_alpha_shape`) or Poisson at low depth plus Laplacian smoothing. |
| Remove floating parts | PyMeshLab `meshing_remove_connected_component_by_diameter` (`mincomponentdiag` %) / `_by_face_number` (`mincomponentsize` 25); `trimesh.Trimesh.split()`; Open3D `cluster_connected_triangles()` |
| Smoothing | Open3D `filter_smooth_taubin`, `filter_smooth_laplacian`, `filter_smooth_simple`; PyMeshLab `apply_coord_taubin_smoothing` (λ 0.5, μ −0.53), `apply_coord_laplacian_smoothing`, `apply_coord_hc_laplacian_smoothing`, `apply_coord_two_steps_smoothing` (feature-preserving); `trimesh.smoothing.filter_taubin` / `filter_humphrey`; pyvista `smooth_taubin` |
| Sharpening | PyMeshLab `apply_coord_unsharp_mask` |
| Hole filling | PyMeshLab `meshing_close_holes(maxholesize=edges, refinehole, selfintersection)` (flat/fan, optional refine); `trimesh.repair.fill_holes` (tiny holes only); pyvista `fill_holes(hole_size)`; `pymeshfix.MeshFix` (aggressive watertight repair); Poisson for "curved" fills |
| Decimation | Open3D `simplify_quadric_decimation(target_number_of_triangles)`, `simplify_vertex_clustering(voxel_size)` (gives grid-aligned faceting); PyMeshLab `meshing_decimation_quadric_edge_collapse(targetperc, qualitythr, preserveboundary)`, `meshing_decimation_clustering`; `fast-simplification` |
| Repair / defect checks | PyMeshLab `meshing_repair_non_manifold_edges`, `meshing_remove_duplicate_faces`, `meshing_re_orient_faces_coherently`, `compute_selection_by_self_intersections_per_face`; trimesh `is_watertight`, `is_winding_consistent`, `fix_normals` |
| Export | `trimesh.Trimesh.export('x.stl')` (binary STL) |

PyMeshLab filter names were checked against the current [filter list](https://pymeshlab.readthedocs.io/en/latest/filter_list.html). PyMeshLab is not yet a project dependency (only trimesh and open3d are). Recommendation: add it as an optional `[meshlab]` extra. It is the only practical source of APSS/RIMLS, LoOP, unsharp mask, two-step smoothing and robust hole closing.

---

## 4. Randomized simulation design

### 4.1 Architecture (recommended)

```
GT (STEP→mesh with face IDs)
  └─ ScanScenario  [scan]   profile, user skill, prep (spray/markers), placement, distractors
      └─ Trajectory [scan]  turntable stops or handheld spline(s), passes (flip?), working distance
          └─ Frames  [frame] raycast → depth image + face IDs + normals
               ├─ sensor model [point]  noise(z,θ,albedo), dropout(material), spikes, flying px, banding
               └─ pose error   [frame]  drift walk + jumps (+ optional real ICP)
      └─ Fusion     [scan]  TSDF(h, μ) | MLS | raw union
      └─ CloudEdit  [scan]  outliers, isolation, plane cut, overlap, smooth
      └─ Mesher     [scan]  watertight Poisson | TSDF-MC | Poisson+trim | BPA | alpha
      └─ MeshPost   [scan]  islands, smooth, sharpen, fill holes(mode, thr), decimate, defects
      └─ Global     [scan]  scale (anisotropic), final rigid pose (random), units
  → outputs: raw_frames.ply (opt), fused.ply, scan.stl, metadata.json (all sampled params + seeds)
```

Also offer a **fast path** with no frames: sample GT surface points with per-point visibility from N virtual viewpoints, then SDF-blur, Poisson, and post. Use it for volume. Use the frame path for fidelity and validation. Keep both, so that downstream models don't key on one generator's signature.

### 4.2 Which randomness lives where

| Level | Parameters |
|---|---|
| **Per scan** | Scanner profile; h (point distance); σ0; z_ref and working-distance window; θ_max; baseline; tracking mode; drift σ and jump rate; number of passes and flip; loop closure on/off and residual; fusion type and μ; cleanup aggressiveness; mesher; smoothing level; sharpening; fill mode and threshold; decimation ratio; scale ε; spray on/off and mean thickness; markers on part y/n; distractor objects; final pose (random rotation; real scanner exports are in arbitrary or table-aligned frames) |
| **Per region (CAD face / patch)** | Material (albedo, specular, roughness, translucency); spray thickness field; marker placements; local noise multiplier k_region ∈ [0.7, 1.5]; dropout blob field seed |
| **Per frame** | Pose error increment; exposure multiplier (changes the dark/shiny dropout threshold, σ0 × U(0.8, 1.25)); banding phase; frame drop (motion blur) probability 0–5% |
| **Per point** | Axial and lateral noise; heavy-tail outliers; dropout draw; spike draw; flying-pixel blend |

### 4.3 Recommended profiles (correlated parameter bundles)

Ranges are sampling bounds. Draw uniformly or log-uniformly within each range, then jitter 10–20% outside the bounds with small probability for robustness. "W" = watertight.

**P1 — Budget IR handheld, no prep, novice.** Like Ferret Pro, POP 3, Einstar, Raptor NIR mode, MIRACO in large mode.

- **Sensor.** h 0.15–0.5 mm; σ0 0.05–0.15 mm; z_ref 300–400 mm (window 150–700 mm); θ_max 65–75°.
- **Tracking.** Geometry/texture tracking with no markers. Drift 3–10× spec. Jump probability 0.1–0.4, size 0.2–2 mm.
- **Materials.** As designed: shiny faces drop heavily; dark faces noisy.
- **Passes.** 1–2 (flip with probability 0.4). Turntable remnant or skirt probability 0.3.
- **Pipeline.** One-click style: TSDF, then Poisson W (probability 0.7) or TSDF-MC with auto fill (0.3). Smoothing level 1–3. Decimation probability 0.6. Remove floating parts on.
- **Expected look.** Rounded edges (0.4–1.5 mm), text gone, bulging bottom cap, ghosting on symmetric parts, scale error 0.05–0.3%.

**P2 — Blue-light SL on a turntable, hobbyist, sometimes sprayed.** Like MINI 2, EinScan SP/SE, Otter close range, POP on a turntable.

- **Sensor.** h 0.05–0.2 mm; σ0 0.02–0.06 mm; window 120–300 mm.
- **Trajectory.** Turntable 8–24 stops × 1–3 tilt levels. Markers on the turntable only (no marker holes), or geometry tracking.
- **Prep.** Spray probability 0.4, thickness 10–50 µm.
- **Passes.** Flip probability 0.6, merge residual 0.05–0.3 mm.
- **Pipeline.** Standard voxel fusion. W probability 0.5; otherwise non-W with fill-small-holes 2–10 mm. Smoothing 0–2. Plane-cut error −0.3 to +1 mm.
- **Expected look.** Good flats with banding ripples, bores capped at partial depth, seam step on the flip line, open or capped bottom.

**P3 — Blue laser metrology, sprayed, markers on part, experienced user.** Like Raptor / Raptor Pro laser, MetroX, FreeScan Combo, EinScan HX laser.

- **Sensor.** h 0.03–0.1 mm; σ0 0.005–0.02 mm; z_ref 200–300 mm.
- **Tracking.** Marker tracking. Drift at spec (0.04–0.1 mm/m). Jump probability ≈0.
- **Prep.** Spray probability 0.8 on shiny/dark parts (AESUB 8–15 µm, sometimes chalk 30–50 µm). Markers on the part: holes 3–6 mm, or filled (marker hole fill probability 0.5).
- **Pipeline.** Laser "Fast" fusion (sharper edges) or Standard. Non-watertight probability 0.7. Minimal smoothing (0–1). Light decimation. Islands removed.
- **Expected look.** Crisp edges (r_eff 0.05–0.3 mm), laser striation, marker-hole pattern on flats, open occluded pockets, thin-wall survival down to ~0.3 mm, scale error 0.01–0.05%.

**P4 — Mid-range SL on unprepared shiny metal / mixed materials.** Stress profile, like MIRACO, Otter or Metro Y full-field on a carburetor-type part.

- **Sensor.** h 0.1–0.3 mm; σ0 0.03–0.1 mm.
- **Materials.** ≥30% of faces specular 0.6–1.0. Exposure conflicts: σ0 × 1.5 on dark faces.
- **Artifacts.** Inter-reflection ghosts in bores and inner corners. Spike outliers 0.5–3%.
- **Tracking.** Feature tracking, with frequent tracking loss caused by dropout.
- **Pipeline.** Poisson W with high fill. Smoothing 2–3.
- **Expected look.** Large bulging caps where shiny faces were missing, phantom surfaces, burrs. This profile teaches downstream tools to distrust geometry inferred from caps.

**P5 — Phone (LiDAR / TrueDepth / photogrammetry).** Like Polycam, RealityScan, Object Capture.

- **LiDAR branch.** h 2–10 mm; σ0 1–5 mm; scale 0.5–3%; heavy smoothing; all features < 5 mm gone.
- **TrueDepth branch.** h 0.3–1 mm; σ0 0.2–0.8 mm.
- **Photogrammetry branch.** Noise driven by texture: plain CAD faces get correlated σ 0.1–0.5% of bbox plus holes. Scale ε 0.1–1% after "rescale". Delaunay/graph-cut-like closed surface (Poisson depth 7–8 plus smoothing as a surrogate). Concavities shrink-wrapped.
- **Purpose.** Defines the low end. Down-weight it in training if ScanRuler targets dedicated scanners.

**Correlations to enforce** (don't sample independently):

- Laser ⇒ markers (on the part with probability 0.6–0.9).
- Markers ⇒ low drift and no jumps.
- Spray ⇒ no reflective dropout, thickness offset, slightly more rounding.
- Large h ⇒ more smoothing and W meshing (novices use defaults).
- Turntable ⇒ unseen bottom band plus plane remnants. Flip ⇔ seam.
- W meshing ⇒ bulging caps and closed bores. Non-W ⇒ open holes with ragged borders plus maybe small-hole fill.
- Shiny material without spray ⇒ more tracking loss with feature tracking.
- Object size ↑ ⇒ volumetric drift ↑ (b·L) and h ↑ (users raise point distance on big parts, per the Creality wiki).

### 4.4 Avoiding "generator fingerprints"

Downstream models will happily learn any constant in the generator. Mitigations:

1. Randomize **algorithms**, not just parameters: ≥2 fusers, ≥3 meshers, ≥3 smoothers, ≥2 hole fillers, ≥2 decimators.
2. Use **non-Gaussian, spatially correlated noise** with heavy tails. Avoid i.i.d. isotropic jitter on vertices, which is the classic "fake scan" look.
3. Randomize the **output frame**: arbitrary rotation and translation, or table-aligned with a random yaw. Real STLs come out in the scanner's or table's frame.
4. Randomize **triangle statistics**: uniform-ish marching-cubes grids, grid-aligned clustering decimation, QEM-decimated bimodal sizes.
5. Randomize **units/scale noise** (ε), and never leave exact CAD dimensions intact in the scan.
6. Include **failure cases** at a low rate (2–5%): heavy ghosting, a missing face cluster, an attached support blob.
7. Overshoot slightly. [arXiv 2402.16514](https://ar5iv.labs.arxiv.org/html/2402.16514) found that noise at 1.25× the measured value transferred best.

### 4.5 Validation loop

- Print or mill a set of GT parts, as Berger did with a 3D-printed Gargoyle ([Berger 2013](https://matthewberger.github.io/papers/bench.pdf)) and Koch et al. did with a physical SL rig ([NeurIPS 2021](https://geometryprocessing.github.io/scanner-sim)).
- Scan them with 2–3 real scanners in CNC Kitchen's lab. Fit profile ranges by matching distributions, not single values:
  - Signed-distance histograms (bias + σ).
  - Edge-radius distributions (fit fillets to GT sharp edges).
  - Hole area fraction by surface type.
  - Triangle-size and dihedral histograms.
  - Island counts.
  - Scale ε from sphere bars.
- Use a classifier two-sample test (real vs synthetic). If a small PointNet/DGCNN can tell them apart above ~60%, find out which features it uses.

---

## 5. Academic and synthetic scanner simulators (noise models used)

| Work | What it models | Noise / artifact model |
|---|---|---|
| **Nguyen, Izadi, Lovell 2012**, *Modeling Kinect Sensor Noise…* (3DIMPVT) [link](https://computer.org/csdl/proceedings-article/3dimpvt/2012/4873a524/12OmNAlvHUP) | Kinect v1 SL | Axial σ quadratic in z, plus a hyperbolic angle term above ~60°; lateral σ linear in z (pixel-based). Formulas in §1.2. |
| **Fankhauser et al. 2015**, Kinect v2 (ICAR) [link](https://www.research-collection.ethz.ch/bitstream/handle/20.500.11850/104272/1/eth-48073-01.pdf) | ToF | Empirical axial and lateral σ(z, θ); separate sunlight model with an incidence-angle term |
| **Chatterjee & Govindu 2015** [arXiv 1505.01936](https://arxiv.org/pdf/1505.01936) | SL stereo | Derives σ_z ∝ z² from first principles; applied to denoising and TSDF merging |
| **Keselman et al. 2017**, Intel RealSense [arXiv 1705.05548](https://arxiv.org/pdf/1705.05548) | Active stereo | ε_z = z²/(f·B)·ε_d, subpixel ε_d ≈ 0.08 px |
| **BlenSor** (Gschwandtner et al., ISVC 2011) [pdf](https://softwareresearch.net/fileadmin/user_upload/Documents/publications/conference_proceedings/ISVC2011.pdf) | LiDAR, ToF, Kinect in Blender | Gaussian range noise, Kinect projector/camera occlusion shadow, 8-bit disparity quantization, correlation-window smoothing (reimplemented in [render_kinect](https://github.com/jbohg/render_kinect), which adds Gaussian/Perlin/Simplex noise). Used for Points2Surf's ABC training scans ([P2S dataset](https://cs.paperswithcode.com/dataset/p2s)). |
| **Handa et al. 2014**, ICL-NUIM / SimKinect [repo](https://www.github.com/ankurhanda/simkinect) | Kinect v1 | Combination of Barron & Malik 2013 and Bohg et al. 2014 models: disparity-domain Gaussian noise, quantization, bilinear interpolation of a shifted dot pattern |
| **Landau, Choo, Beling 2016**, *Simulating Kinect IR and Depth Images* (IEEE T-Cyb) [PubMed](https://www.pubmed.gov/26584505/) | Kinect IR dot pattern | Simulates the IR speckle image, then disparity matching. Gives depth shadowing, dot splitting and spreading, occlusion. MATLAB code. |
| **Berger et al. 2013**, *A Benchmark for Surface Reconstruction* (TOG) [pdf](https://matthewberger.github.io/papers/bench.pdf) | Laser triangulation | Ray-traced stripes with Curless–Levoy radiance; speckle noise η (0–0.6) growing off-stripe-center; Gaussian peak fitting; peak (0.1–0.8) and variance (2× laser width) thresholds cause missing data and edge rejection; baseline 10–150 mm; LW-ICP misregistration from random initial rotations; normals by PCA with Hoppe-MST flips. Validated against a NextEngine. |
| **Abbasinejad et al. 2009**, *Rotating scans for systematic error removal* (CGF) [pdf](https://www.cs.ucdavis.edu/~amenta/pubs/RotatingScans.pdf) | Laser triangulation edge error | Stair-step on rising edges, overshoot on falling edges, only for edges ⟂ baseline |
| **Medeiros, Doraiswamy, Berger, Silva 2014**, *PBR to benchmark SL scanners* (PG) [pdf](https://matthewberger.github.io/papers/sl.pdf) | Projector-camera SL, physically rendered | Projector defocus (aperture), inter-reflections, subsurface scattering; compares Gray code, micro phase shift, ensemble codes, unstructured light |
| **Koch et al. 2021**, *Hardware Design and Accurate Simulation of SL Scanning* (NeurIPS D&B) [site](https://geometryprocessing.github.io/scanner-sim) | Physical SL rig + light-transport sim | Calibrated per-pixel-accurate rendering; synthetic data "indistinguishable" for diffuse objects; ABC-based datasets for denoising, completion, merging |
| **Planche et al. 2017**, *DepthSynth* (3DV) [arXiv 1702.08558](https://arxiv.org/abs/1702.08558) | Multi-shot SL / generic depth sensors | Pattern projection, material reflectance, motion between exposures, rolling shutter, block-matching reconstruction; follow-up differentiable version [arXiv 2103.16563](https://arxiv.org/abs/2103.16563) |
| **arXiv 2402.16514 (2024)**, *Enhancement of 3D Camera Synthetic Training Data with Noise Models* [link](https://ar5iv.labs.arxiv.org/html/2402.16514) | Kinect v1/v2, MotionCam-3D | Fitted quadratic polynomials σ_L(z,θ), σ_z(z,θ); best transfer at 1.25× noise |
| **HELIOS++** (Winiwarter et al., RSE 2022) [arXiv 2101.09154](https://arxiv.org/pdf/2101.09154) | Terrestrial / airborne LiDAR | Beam divergence via ray subsampling, full waveform. Mostly relevant only for long-range. |
| **ShapeNet / PCN / MVP virtual scans** (e.g. PCN, [arXiv 1808.00671](https://arxiv.org/pdf/1808.00671)) | Partial-view completion | Depth renders from 8–26 viewpoints back-projected; occlusion only, usually no sensor noise. A cautionary baseline: too clean. |

---

## 6. Open questions / things to measure

These figures are estimates. The best way to pin them down is real scans of parts with known geometry, in house:

1. Edge-radius versus point-distance curves per scanner (§2.3). Fit fillets on a test block with 90° edges, 0.5/1/2 mm chamfers, and engraved text at 0.1–0.5 mm depth.
2. Bore visibility depth `D_vis/d` per scanner (§2.6). Use a block with 2–10 mm holes, 30 mm deep.
3. Thin-wall survival thresholds (§2.5). Use a comb of 0.2–2 mm fins.
4. Reflective dropout fractions for anodized, bead-blasted and polished aluminium, black PLA and translucent PETG (§2.8).
5. Seam-step and ghost-offset distributions for flip-merged scans with feature versus marker tracking (§2.12–2.14).
6. Vendor default parameter sets for one-click modes in CrealityScan and Revo Scan. These change between versions, so record the version in metadata. The Creality wiki pages are JS-rendered and could not be fetched here, so we couldn't confirm CrealityScan's watertight toggle or the names of its quality levels.
