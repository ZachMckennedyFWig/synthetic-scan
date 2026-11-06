/**
 * The single WebGL renderer behind every pane.
 *
 * One canvas covers the whole canvas area; each pane is a transparent DOM box
 * on top of it, and the stage renders the shared scene once per pane with
 * setViewport/setScissor set to that box. Consequences, all intended:
 *
 *  - One camera. Panes are locked together by construction -- there is
 *    nothing to keep in sync, so nothing can drift.
 *  - One GL context. A 3M-triangle scan is uploaded once no matter how many
 *    panes show it (separate canvases would each need their own copy).
 *  - Panes differ only in which objects are visible while they draw.
 *
 * Drawing is on demand: anything that changes the picture sets `dirty`, and a
 * single rAF loop draws at most one frame per vsync when it is set. The hot
 * path (draw) allocates nothing; meshes are built once per layer geometry and
 * reused across frames and tab switches.
 *
 * Pane rectangles are measured on resize (ResizeObserver), never per frame, so
 * the loop does not force layout either.
 */
import {
  AmbientLight,
  Color,
  DirectionalLight,
  DoubleSide,
  FrontSide,
  Group,
  HemisphereLight,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  Object3D,
  PerspectiveCamera,
  Points,
  PointsMaterial,
  Scene,
  Sphere,
  Vector3,
  WebGLRenderer,
} from 'three'
import { LAYER_BY_ID } from '../lib/layers'
import type { LayerId } from '../lib/types'
import { heatUniforms, withHeat } from './colormap'
import { geometryCache, type LayerGeometry } from './geometryCache'
import { eyeOf, FOV_DEG, viewportController } from './viewportController'

const BG = new Color('#010102') // --color-bg-marketing, as FootprintUi's panes
const GAP = new Color('#23252a') // --color-border-primary: the 1px split borders
const SCAN_COLOR = '#b3aba1'
const LAYER_IDS: LayerId[] = ['gt', 'scan', 'points', 'coverage']

export interface DisplayOptions {
  heatmap: boolean
  /** Symmetric colour range, mm: ±range for deviation, 0..range for coverage. */
  range: number
  wireframe: boolean
  flat: boolean
  ghostOpacity: number
}

export interface PaneSpec {
  key: string
  layers: LayerId[]
  /** Draw GT as the transparent ghost (when a scan shares the pane). */
  ghostGt: boolean
}

export interface StageScene {
  tabId: string | null
  sampleKey: string | null
  panes: PaneSpec[]
  display: DisplayOptions
}

interface PaneEntry {
  el: HTMLElement
  scaleBar: HTMLElement | null
  scaleText: HTMLElement | null
  x: number
  y: number
  w: number
  h: number
  lastScaleMm: number
  lastScalePx: number
}

/** The drawable objects for one layer of one sample; all share its geometry. */
interface Bundle {
  layer: LayerGeometry
  solid: Object3D
  ghost: Mesh | null
  wire: Mesh | null
}

function makeMaterials() {
  const standard = (color: string) =>
    new MeshStandardMaterial({
      color,
      roughness: 0.62,
      metalness: 0.04,
      flatShading: true,
      side: DoubleSide, // scans have holes; back faces seen through them should still shade
      // Pushes filled faces back a hair so the wireframe overlay wins the depth test.
      polygonOffset: true,
      polygonOffsetFactor: 1,
      polygonOffsetUnits: 1,
    })
  return {
    gt: standard(LAYER_BY_ID.gt.color),
    scan: withHeat(standard(SCAN_COLOR), 'diverging'),
    ghost: new MeshStandardMaterial({
      color: LAYER_BY_ID.gt.color,
      roughness: 0.7,
      metalness: 0,
      flatShading: true,
      transparent: true,
      opacity: 0.25,
      depthWrite: false, // a ghost must never hide the scan behind it
      side: FrontSide,
      // Same offset as the solids: GT and scan are near-coplanar, and an
      // un-offset ghost would win every depth tie and wash over the scan
      // instead of showing only where the GT really is in front (or uncovered).
      polygonOffset: true,
      polygonOffsetFactor: 1,
      polygonOffsetUnits: 1,
    }),
    wire: new MeshBasicMaterial({
      color: '#d0d6e0',
      wireframe: true,
      transparent: true,
      opacity: 0.16,
      depthWrite: false,
    }),
    points: withHeat(new PointsMaterial({ color: LAYER_BY_ID.points.color, size: 1.75, sizeAttenuation: false }), 'diverging'),
    coverage: withHeat(new PointsMaterial({ color: LAYER_BY_ID.coverage.color, size: 1.75, sizeAttenuation: false }), 'sequential'),
  }
}

type Materials = ReturnType<typeof makeMaterials>

class Stage {
  private renderer: WebGLRenderer | null = null
  private canvas: HTMLCanvasElement | null = null
  private host: HTMLElement | null = null
  private ro: ResizeObserver | null = null
  private raf = 0
  private dirty = true
  private width = 0
  private height = 0

  private readonly scene = new Scene()
  private readonly camera = new PerspectiveCamera(FOV_DEG, 1, 0.1, 1000)
  private readonly materials: Materials = makeMaterials()
  private readonly panes = new Map<string, PaneEntry>()
  private readonly bundles = new Map<string, Map<LayerId, Bundle>>()
  private readonly groups = new Map<string, Group>()
  private activeGroup: Group | null = null
  private flatApplied = true

  private desc: StageScene = {
    tabId: null,
    sampleKey: null,
    panes: [],
    display: { heatmap: false, range: 0.5, wireframe: false, flat: true, ghostOpacity: 0.25 },
  }

  // Scratch objects for the draw path.
  private readonly tmpSphere = new Sphere()
  private readonly tmpEye = { x: 0, y: 0, z: 0 }
  private readonly tmpTarget = new Vector3()

  constructor() {
    // Headlight: a directional light parented to the camera so the side you
    // look at is always lit -- CAD faces read by their shading, not by where
    // some fixed sun happens to be. Hemisphere + a little ambient fill keeps
    // faces turned away from being pure black.
    const head = new DirectionalLight('#ffffff', 2.4)
    head.position.set(0.25, 0.35, 0)
    head.target.position.set(0, 0, -1)
    this.camera.add(head, head.target)
    this.camera.up.set(0, 0, 1)
    this.scene.add(this.camera)
    this.scene.add(new HemisphereLight('#d0d6e0', '#202122', 0.9))
    this.scene.add(new AmbientLight('#ffffff', 0.12))

    viewportController.subscribe(() => this.markDirty())
    geometryCache.onEvict((key) => this.dropSample(key))
  }

  /** Returns an error message if WebGL is unavailable. */
  attach(canvas: HTMLCanvasElement, host: HTMLElement): string | null {
    this.detach()
    try {
      this.renderer = new WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' })
    } catch (err) {
      return (err as Error).message || 'WebGL could not be initialised'
    }
    this.renderer.autoClear = false
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    this.canvas = canvas
    this.host = host
    canvas.addEventListener('webglcontextlost', this.onContextLost)
    canvas.addEventListener('webglcontextrestored', this.onContextRestored)

    this.ro = new ResizeObserver(() => this.measure())
    this.ro.observe(host)
    for (const p of this.panes.values()) this.ro.observe(p.el)
    this.measure()

    this.raf = requestAnimationFrame(this.loop)
    return null
  }

  detach(): void {
    cancelAnimationFrame(this.raf)
    this.ro?.disconnect()
    this.ro = null
    if (this.canvas) {
      this.canvas.removeEventListener('webglcontextlost', this.onContextLost)
      this.canvas.removeEventListener('webglcontextrestored', this.onContextRestored)
    }
    // Releases the context; the CPU-side geometry stays in the cache and is
    // simply re-uploaded by the next renderer.
    this.renderer?.dispose()
    this.renderer = null
    this.canvas = null
    this.host = null
  }

  markDirty = (): void => {
    this.dirty = true
  }

  setScene(desc: StageScene): void {
    const d = desc.display
    heatUniforms.uHeat.value = d.heatmap ? 1 : 0
    heatUniforms.uRange.value = Math.max(1e-6, d.range)
    this.materials.ghost.opacity = d.ghostOpacity
    if (d.flat !== this.flatApplied) this.applyShading(d.flat)
    this.desc = desc
    this.markDirty()
  }

  registerPane(key: string, el: HTMLElement, scaleBar: HTMLElement | null, scaleText: HTMLElement | null): void {
    this.panes.set(key, { el, scaleBar, scaleText, x: 0, y: 0, w: 0, h: 0, lastScaleMm: -1, lastScalePx: -1 })
    this.ro?.observe(el)
    this.measure()
  }

  unregisterPane(key: string): void {
    const p = this.panes.get(key)
    if (p) this.ro?.unobserve(p.el)
    this.panes.delete(key)
    this.markDirty()
  }

  /** Frame what the first pane shows (or anything loaded) -- the F key. */
  fit(): void {
    const { tabId, sampleKey } = this.desc
    if (!tabId || !sampleKey) return
    const sphere = this.sphereOf(sampleKey, this.desc.panes[0]?.layers ?? LAYER_IDS)
    if (sphere) viewportController.fit(tabId, sphere, this.minAspect())
  }

  // ---- internals ---------------------------------------------------------

  private onContextLost = (e: Event): void => {
    e.preventDefault() // lets the browser restore it
  }

  private onContextRestored = (): void => {
    this.markDirty()
  }

  private measure(): void {
    const host = this.host
    const r = this.renderer
    if (!host || !r) return
    const hr = host.getBoundingClientRect()
    const w = Math.round(hr.width)
    const h = Math.round(hr.height)
    if (w !== this.width || h !== this.height) {
      this.width = w
      this.height = h
      if (w > 0 && h > 0) r.setSize(w, h, false)
    }
    for (const p of this.panes.values()) {
      const pr = p.el.getBoundingClientRect()
      p.x = Math.round(pr.left - hr.left)
      p.y = Math.round(pr.top - hr.top)
      p.w = Math.round(pr.width)
      p.h = Math.round(pr.height)
    }
    this.markDirty()
  }

  private minAspect(): number {
    let a = Infinity
    for (const spec of this.desc.panes) {
      const p = this.panes.get(spec.key)
      if (p && p.w > 0 && p.h > 0) a = Math.min(a, p.w / p.h)
    }
    return Number.isFinite(a) ? a : 1
  }

  private applyShading(flat: boolean): void {
    for (const m of [this.materials.gt, this.materials.scan, this.materials.ghost]) {
      m.flatShading = flat
      m.needsUpdate = true // one recompile per toggle, not per frame
    }
    this.flatApplied = flat
  }

  private dropSample(key: string): void {
    const g = this.groups.get(key)
    if (g) {
      this.scene.remove(g)
      if (this.activeGroup === g) this.activeGroup = null
    }
    this.groups.delete(key)
    this.bundles.delete(key)
    this.markDirty()
  }

  /** Union of the bounding spheres of the given layers that are loaded. */
  private sphereOf(key: string, layers: readonly LayerId[]): Sphere | null {
    let found = false
    for (const id of layers) {
      const g = geometryCache.peek(key, id)
      if (!g) continue
      if (!found) this.tmpSphere.copy(g.sphere)
      else this.tmpSphere.union(g.sphere)
      found = true
    }
    return found ? this.tmpSphere : null
  }

  /** Make the active sample's group current and build any newly loaded layers. */
  private syncObjects(key: string): Map<LayerId, Bundle> {
    let group = this.groups.get(key)
    if (!group) {
      group = new Group()
      this.groups.set(key, group)
    }
    if (this.activeGroup !== group) {
      if (this.activeGroup) this.scene.remove(this.activeGroup)
      this.scene.add(group)
      this.activeGroup = group
    }
    let bundles = this.bundles.get(key)
    if (!bundles) {
      bundles = new Map()
      this.bundles.set(key, bundles)
    }
    for (const id of LAYER_IDS) {
      const layer = geometryCache.peek(key, id)
      const existing = bundles.get(id)
      if (existing && existing.layer === layer) continue
      if (existing) {
        group.remove(existing.solid)
        if (existing.ghost) group.remove(existing.ghost)
        if (existing.wire) group.remove(existing.wire)
        bundles.delete(id)
      }
      if (!layer) continue
      const b = this.buildBundle(id, layer)
      group.add(b.solid)
      if (b.ghost) group.add(b.ghost)
      if (b.wire) group.add(b.wire)
      bundles.set(id, b)
    }
    return bundles
  }

  private buildBundle(id: LayerId, layer: LayerGeometry): Bundle {
    const m = this.materials
    const g = layer.geometry
    if (LAYER_BY_ID[id].primitive === 'points' || layer.nFaces === 0) {
      return { layer, solid: new Points(g, id === 'coverage' ? m.coverage : m.points), ghost: null, wire: null }
    }
    const solid = new Mesh(g, id === 'gt' ? m.gt : m.scan)
    const ghost = id === 'gt' ? new Mesh(g, m.ghost) : null
    if (ghost) ghost.renderOrder = 1 // after opaque geometry, whatever three's sort says
    const wire = new Mesh(g, m.wire)
    wire.renderOrder = 2
    return { layer, solid, ghost, wire }
  }

  private loop = (): void => {
    this.raf = requestAnimationFrame(this.loop)
    if (!this.dirty) return
    this.dirty = false
    this.draw()
  }

  private draw(): void {
    const r = this.renderer
    if (!r || this.width <= 0 || this.height <= 0) return
    const { tabId, sampleKey, panes, display } = this.desc

    r.setScissorTest(false)
    r.setViewport(0, 0, this.width, this.height)
    // The gap colour fills everything; panes then clear their own boxes, so the
    // 1px grid gaps show through as borders exactly like FootprintUi's split-grid.
    r.setClearColor(panes.length > 1 ? GAP : BG, 1)
    r.clear()
    if (!tabId || !sampleKey) return

    const bundles = this.syncObjects(sampleKey)

    // Smooth shading needs normals SSG1 does not carry; compute them once, on
    // first use, rather than for every mesh up front.
    if (!display.flat) {
      for (const b of bundles.values()) {
        const g = b.layer.geometry
        if (b.wire && !g.getAttribute('normal')) g.computeVertexNormals()
      }
    }

    let view = viewportController.get(tabId)
    if (!view) {
      // First geometry for this tab just arrived: frame it.
      const sphere = this.sphereOf(sampleKey, LAYER_IDS)
      if (!sphere) return
      viewportController.fit(tabId, sphere, this.minAspect())
      view = viewportController.get(tabId)
      if (!view) return
    }

    eyeOf(view, this.tmpEye)
    this.camera.position.set(this.tmpEye.x, this.tmpEye.y, this.tmpEye.z)
    this.tmpTarget.set(view.tx, view.ty, view.tz)
    this.camera.lookAt(this.tmpTarget)
    // Depth range from the scene's extent around the target. Generous far, and
    // near as large as safely possible: depth precision is spent near `near`.
    const sphere = this.sphereOf(sampleKey, LAYER_IDS)
    const extent = sphere ? sphere.radius + sphere.center.distanceTo(this.tmpTarget) : view.radius
    this.camera.near = Math.max(view.radius * 0.002, view.radius - extent * 1.5, 1e-4)
    this.camera.far = view.radius + extent * 2 + 1
    this.camera.updateMatrixWorld()

    r.setScissorTest(true)
    for (const spec of panes) {
      const p = this.panes.get(spec.key)
      if (!p || p.w <= 0 || p.h <= 0) continue
      const y = this.height - p.y - p.h // GL's origin is bottom-left
      r.setViewport(p.x, y, p.w, p.h)
      r.setScissor(p.x, y, p.w, p.h)
      r.setClearColor(BG, 1)
      r.clear()

      this.camera.aspect = p.w / p.h
      this.camera.updateProjectionMatrix()
      this.applyVisibility(bundles, spec, display)
      r.render(this.scene, this.camera)
      this.updateScaleBar(p, view.radius)
    }
  }

  private applyVisibility(bundles: Map<LayerId, Bundle>, spec: PaneSpec, display: DisplayOptions): void {
    for (const [id, b] of bundles) {
      const shown = spec.layers.includes(id)
      const ghosted = shown && id === 'gt' && spec.ghostGt
      b.solid.visible = shown && !ghosted
      if (b.ghost) b.ghost.visible = ghosted && display.ghostOpacity > 0.001
      if (b.wire) b.wire.visible = shown && !ghosted && display.wireframe
    }
  }

  /** Written straight to the DOM: camera changes never touch React. */
  private updateScaleBar(p: PaneEntry, radius: number): void {
    if (!p.scaleBar || !p.scaleText) return
    const mmPerPx = (2 * radius * Math.tan((FOV_DEG * Math.PI) / 360)) / p.h
    const target = mmPerPx * 90
    const pow = 10 ** Math.floor(Math.log10(target))
    const n = target / pow
    const mm = (n >= 5 ? 5 : n >= 2 ? 2 : 1) * pow
    const px = Math.round(mm / mmPerPx)
    if (mm === p.lastScaleMm && px === p.lastScalePx) return
    p.lastScaleMm = mm
    p.lastScalePx = px
    p.scaleBar.style.width = `${px}px`
    p.scaleText.textContent = mm >= 1 ? `${mm} mm` : `${Number(mm.toPrecision(1))} mm`
  }
}

export const stage = new Stage()

if (import.meta.env.DEV) {
  ;(window as unknown as { __stage: Stage }).__stage = stage
}
