/**
 * Orbit / pan / zoom on the canvas area, wired natively and outside React.
 *
 *   left drag            orbit (turntable about +Z)
 *   right/middle drag,
 *   Shift + left drag    pan
 *   wheel                zoom about the cursor
 *   double-click         fit
 *
 * Every pane drives the same camera, so it only matters which pane the
 * gesture *started* in for screen-to-world scaling (its height and aspect).
 */
import { stage } from './stage'
import { viewportController } from './viewportController'

export interface GestureOptions {
  getTabId: () => string | null
  /** Called with the pane key under a pointerdown, for the focus outline. */
  onPaneFocus?: (key: string) => void
}

function paneAt(target: EventTarget | null): HTMLElement | null {
  return target instanceof Element ? (target.closest('.pane') as HTMLElement | null) : null
}

export function bindGestures(el: HTMLElement, opts: GestureOptions): () => void {
  function onPointerDown(e: PointerEvent) {
    const tabId = opts.getTabId()
    const pane = paneAt(e.target)
    if (!tabId || !pane || !viewportController.has(tabId)) return
    if (pane.dataset.key) opts.onPaneFocus?.(pane.dataset.key)
    if (e.button !== 0 && e.button !== 1 && e.button !== 2) return
    e.preventDefault()

    const panMode = e.button !== 0 || e.shiftKey
    const paneH = pane.clientHeight
    let lastX = e.clientX
    let lastY = e.clientY
    el.setPointerCapture(e.pointerId)
    el.style.cursor = panMode ? 'move' : 'grabbing'

    const move = (ev: PointerEvent) => {
      const dx = ev.clientX - lastX
      const dy = ev.clientY - lastY
      lastX = ev.clientX
      lastY = ev.clientY
      if (!dx && !dy) return
      if (panMode) viewportController.pan(tabId, dx, dy, paneH)
      else viewportController.orbit(tabId, dx, dy)
    }
    const up = (ev: PointerEvent) => {
      if (el.hasPointerCapture(ev.pointerId)) el.releasePointerCapture(ev.pointerId)
      el.removeEventListener('pointermove', move)
      el.removeEventListener('pointerup', up)
      el.removeEventListener('pointercancel', up)
      el.style.cursor = ''
    }
    el.addEventListener('pointermove', move)
    el.addEventListener('pointerup', up)
    el.addEventListener('pointercancel', up)
  }

  // Registered natively: React attaches wheel handlers as passive, so
  // preventDefault() there is a no-op and the page would scroll instead.
  function onWheel(e: WheelEvent) {
    const tabId = opts.getTabId()
    const pane = paneAt(e.target)
    if (!tabId || !pane || !viewportController.has(tabId)) return
    e.preventDefault()
    const rect = pane.getBoundingClientRect()
    const ndcX = ((e.clientX - rect.left) / rect.width) * 2 - 1
    const ndcY = -(((e.clientY - rect.top) / rect.height) * 2 - 1)
    // deltaMode 1 is lines, not pixels -- mice and trackpads report differently.
    const delta = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY
    viewportController.zoom(tabId, Math.exp(delta * 0.0015), ndcX, ndcY, rect.width / rect.height)
  }

  function onDoubleClick(e: MouseEvent) {
    if (paneAt(e.target)) stage.fit()
  }

  // Right-drag pans; the context menu would swallow the gesture.
  function onContextMenu(e: MouseEvent) {
    if (paneAt(e.target)) e.preventDefault()
  }

  el.addEventListener('pointerdown', onPointerDown)
  el.addEventListener('wheel', onWheel, { passive: false })
  el.addEventListener('dblclick', onDoubleClick)
  el.addEventListener('contextmenu', onContextMenu)
  return () => {
    el.removeEventListener('pointerdown', onPointerDown)
    el.removeEventListener('wheel', onWheel)
    el.removeEventListener('dblclick', onDoubleClick)
    el.removeEventListener('contextmenu', onContextMenu)
  }
}
