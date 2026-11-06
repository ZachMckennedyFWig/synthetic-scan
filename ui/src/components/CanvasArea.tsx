import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { gridFor, panesFor } from '../lib/panes'
import { bindGestures } from '../render/gestures'
import { stage } from '../render/stage'
import { useActiveTab, useStore } from '../store/useStore'
import { Pane } from './Pane'

/**
 * The 3D view: one canvas (owned by the stage) under a grid of DOM panes.
 *
 * Stays mounted while the Batch page is shown, just hidden: tearing the
 * WebGL context down would mean re-uploading every cached mesh on return.
 */
export function CanvasArea({ hidden }: { hidden: boolean }) {
  const hostRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const gridRef = useRef<HTMLDivElement>(null)
  const [glError, setGlError] = useState<string | null>(null)
  const [focusedPane, setFocusedPane] = useState<string | null>(null)

  const tab = useActiveTab()
  const layers = useStore((s) => s.layers)
  const mode = useStore((s) => s.mode)
  const display = useStore((s) => s.display)

  const panes = useMemo(() => (tab ? panesFor(tab, layers, mode) : []), [tab, layers, mode])
  const grid = gridFor(panes.length)

  useLayoutEffect(() => {
    const err = stage.attach(canvasRef.current!, hostRef.current!)
    setGlError(err)
    return () => stage.detach()
  }, [])

  useEffect(
    () =>
      bindGestures(gridRef.current!, {
        getTabId: () => useStore.getState().activeTabId,
        onPaneFocus: setFocusedPane,
      }),
    [],
  )

  // Push the scene description to the stage. Layer status is part of `tab`, so
  // a layer finishing its download re-runs this and the stage picks it up.
  useEffect(() => {
    stage.setScene({
      tabId: tab?.id ?? null,
      sampleKey: tab?.id ?? null,
      panes: panes.map((p) => ({ key: p.key, layers: p.layers, ghostGt: p.ghostGt })),
      display,
    })
  }, [tab, panes, display])

  return (
    <div ref={hostRef} className="canvas-area" hidden={hidden}>
      <canvas ref={canvasRef} className="gl-canvas" />
      <div
        ref={gridRef}
        className="split-grid"
        style={{
          gridTemplateColumns: `repeat(${grid.cols}, minmax(0, 1fr))`,
          gridTemplateRows: `repeat(${grid.rows}, minmax(0, 1fr))`,
        }}
      >
        {tab &&
          panes.map((pane) => (
            <Pane
              key={pane.key}
              pane={pane}
              tab={tab}
              focused={panes.length > 1 && focusedPane === pane.key}
              heatmap={display.heatmap}
              range={display.range}
            />
          ))}
      </div>

      {glError ? (
        <div className="empty">
          <h2>WebGL unavailable</h2>
          <p style={{ color: 'var(--color-red)' }}>{glError}</p>
        </div>
      ) : (
        !tab && <EmptyState />
      )}
    </div>
  )
}

function EmptyState() {
  const online = useStore((s) => s.online)
  const checked = useStore((s) => s.checked)
  const dataset = useStore((s) => s.dataset)
  const nSamples = useStore((s) => s.samples.length)
  const setView = useStore((s) => s.setView)

  if (!checked) return <div className="empty"><p>Connecting…</p></div>

  if (!online) {
    return (
      <div className="empty">
        <h2>Backend offline</h2>
        <p>
          Nothing is answering on <code>/api</code>. Start it with <code>synthscan serve</code> (port 8849); this page
          reconnects by itself.
        </p>
      </div>
    )
  }
  if (!dataset) {
    return (
      <div className="empty">
        <h2>No dataset yet</h2>
        <p>Create one in the Dataset panel, then upload CAD parts on the Batch page and generate scans.</p>
        <button className="btn" data-variant="primary" onClick={() => setView('batch')}>
          Open Batch
        </button>
      </div>
    )
  }
  return (
    <div className="empty">
      <h2>No sample open</h2>
      <p>
        {nSamples
          ? 'Pick a sample from the Dataset panel. Each opens in its own tab; Space flips scan ↔ GT, S splits them side by side.'
          : `${dataset} has no samples yet. Upload parts and run a generation job on the Batch page.`}
      </p>
      {!nSamples && (
        <button className="btn" data-variant="primary" onClick={() => setView('batch')}>
          Open Batch
        </button>
      )}
    </div>
  )
}
