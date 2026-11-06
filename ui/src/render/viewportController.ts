/**
 * The live camera, deliberately outside React.
 *
 * Orbit/pan/zoom fire at input rate -- a 1000 Hz mouse produces ~1000
 * pointermove events per second, but only ~60 of them can ever become a frame.
 * Routing each one through `setState` would mean ~940 wasted React render +
 * commit cycles per second for a value no component displays. So gestures
 * mutate the view here in place and the stage, the only subscriber, just marks
 * itself dirty; its single rAF loop turns that into at most one frame.
 *
 * One view per tab, shared by every pane of that tab: split-screen panes are
 * locked together because there is literally one camera, not because anything
 * keeps several in sync.
 *
 * (FootprintUi also pushed a throttled copy into the store for a zoom readout.
 * Nothing here shows camera state in React -- the mm scale bar is written to
 * the DOM by the stage -- so that path is intentionally absent.)
 *
 * Model space is Z-up (CAD convention); the camera is a turntable around +Z.
 */

export const FOV_DEG = 35
const HALF_FOV_TAN = Math.tan((FOV_DEG * Math.PI) / 360)

export interface View {
  tx: number
  ty: number
  tz: number
  /** Distance from camera to target, mm. */
  radius: number
  /** Azimuth around +Z, radians. */
  az: number
  /** Elevation above the XY plane, radians, clamped short of the poles. */
  el: number
}

export interface BoundingSphereLike {
  center: { x: number; y: number; z: number }
  radius: number
}

type Listener = () => void

const EL_LIMIT = Math.PI / 2 - 0.001
const DEFAULT_AZ = -Math.PI / 4
const DEFAULT_EL = Math.PI / 7

class ViewportController {
  private views = new Map<string, View>()
  private listeners = new Set<Listener>()

  get(tabId: string): View | undefined {
    return this.views.get(tabId)
  }

  has(tabId: string): boolean {
    return this.views.has(tabId)
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }

  private emit(): void {
    for (const fn of this.listeners) fn()
  }

  forget(tabId: string): void {
    this.views.delete(tabId)
    this.emit()
  }

  /** Turntable orbit: horizontal drag spins about +Z, vertical tilts. */
  orbit(tabId: string, dxPx: number, dyPx: number): void {
    const v = this.views.get(tabId)
    if (!v) return
    v.az -= dxPx * 0.008
    v.el = Math.max(-EL_LIMIT, Math.min(EL_LIMIT, v.el + dyPx * 0.008))
    this.emit()
  }

  /** Screen-space pan, scaled so the point at the target depth tracks the cursor. */
  pan(tabId: string, dxPx: number, dyPx: number, paneHeightPx: number): void {
    const v = this.views.get(tabId)
    if (!v || paneHeightPx <= 0) return
    const wpp = (2 * v.radius * HALF_FOV_TAN) / paneHeightPx
    const b = basis(v)
    v.tx += (-b.rx * dxPx + b.ux * dyPx) * wpp
    v.ty += (-b.ry * dxPx + b.uy * dyPx) * wpp
    v.tz += (-b.rz * dxPx + b.uz * dyPx) * wpp
    this.emit()
  }

  /**
   * Dolly by `factor` (<1 = closer) about the point under the cursor, given in
   * pane NDC. That point sits on the focal plane through the target; scaling
   * the target's offset from it by the same factor keeps it fixed on screen.
   */
  zoom(tabId: string, factor: number, ndcX: number, ndcY: number, aspect: number): void {
    const v = this.views.get(tabId)
    if (!v) return
    const next = Math.max(1e-3, Math.min(1e7, v.radius * factor))
    const f = next / v.radius
    const halfH = v.radius * HALF_FOV_TAN
    const halfW = halfH * aspect
    const b = basis(v)
    const px = v.tx + b.rx * ndcX * halfW + b.ux * ndcY * halfH
    const py = v.ty + b.ry * ndcX * halfW + b.uy * ndcY * halfH
    const pz = v.tz + b.rz * ndcX * halfW + b.uz * ndcY * halfH
    v.tx = px + (v.tx - px) * f
    v.ty = py + (v.ty - py) * f
    v.tz = pz + (v.tz - pz) * f
    v.radius = next
    this.emit()
  }

  /**
   * Frame a bounding sphere. Keeps the current viewing angle when the tab
   * already has a view (so F re-centres without spinning you around), else
   * starts from a conventional iso-ish angle.
   */
  fit(tabId: string, sphere: BoundingSphereLike, aspect: number): void {
    const prev = this.views.get(tabId)
    const halfV = Math.atan(HALF_FOV_TAN)
    // In a tall pane the horizontal FOV is the tighter one.
    const half = aspect < 1 ? Math.atan(HALF_FOV_TAN * aspect) : halfV
    const r = Math.max(sphere.radius, 1e-3)
    const view: View = {
      tx: sphere.center.x,
      ty: sphere.center.y,
      tz: sphere.center.z,
      radius: (r / Math.sin(half)) * 1.08,
      az: prev?.az ?? DEFAULT_AZ,
      el: prev?.el ?? DEFAULT_EL,
    }
    this.views.set(tabId, view)
    this.emit()
  }
}

/** Camera right/up vectors for a view; allocation-free hot path helper. */
const _b = { rx: 0, ry: 0, rz: 0, ux: 0, uy: 0, uz: 0 }
export function basis(v: View): typeof _b {
  const ca = Math.cos(v.az)
  const sa = Math.sin(v.az)
  const ce = Math.cos(v.el)
  const se = Math.sin(v.el)
  // Camera sits at target + radius * d, d = (ce·ca, ce·sa, se), looking along -d.
  // right = normalize(-d × Z) = (-sa, ca, 0); up = right × (-d).
  _b.rx = -sa
  _b.ry = ca
  _b.rz = 0
  _b.ux = -se * ca
  _b.uy = -se * sa
  _b.uz = ce
  return _b
}

export function eyeOf(v: View, out: { x: number; y: number; z: number }): void {
  const ce = Math.cos(v.el)
  out.x = v.tx + v.radius * ce * Math.cos(v.az)
  out.y = v.ty + v.radius * ce * Math.sin(v.az)
  out.z = v.tz + v.radius * Math.sin(v.el)
}

export const viewportController = new ViewportController()
