import { useLayoutEffect, useRef } from 'react'
import { fmtCount, fmtMm, fmtPct } from '../lib/format'
import { LAYER_BY_ID } from '../lib/layers'
import type { PaneModel } from '../lib/panes'
import type { LayerId } from '../lib/types'
import { legendGradient, type HeatKind } from '../render/colormap'
import { stage } from '../render/stage'
import type { Tab } from '../store/useStore'

interface Props {
  pane: PaneModel
  tab: Tab
  focused: boolean
  heatmap: boolean
  range: number
}

/**
 * One pane is only DOM: the label/stat overlays and a box the stage measures.
 * The pixels underneath come from the shared canvas (render/stage.ts).
 */
export function Pane({ pane, tab, focused, heatmap, range }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const barRef = useRef<HTMLDivElement>(null)
  const textRef = useRef<HTMLSpanElement>(null)

  useLayoutEffect(() => {
    stage.registerPane(pane.key, ref.current!, barRef.current, textRef.current)
    return () => stage.unregisterPane(pane.key)
  }, [pane.key])

  const loading = pane.layers.filter((id) => tab.layers[id].status === 'loading')
  const legends = heatmap ? legendKinds(pane.layers, tab) : []

  return (
    <div ref={ref} className="pane" data-key={pane.key} data-focused={focused ? 'true' : 'false'}>
      {pane.label && (
        <div className="pane-label">
          {pane.color && <span className="pane-swatch" style={{ background: pane.color }} />}
          {pane.label}
        </div>
      )}

      {loading.length > 0 && <div className="pane-loading">loading {loading.join(', ')}…</div>}

      <PaneStats primary={pane.primary} tab={tab} />

      <div className="pane-corner">
        <div className="scalebar">
          <span ref={textRef} />
          <div ref={barRef} className="scalebar-bar" />
        </div>
        {legends.map((kind) => (
          <Legend key={kind} kind={kind} range={range} />
        ))}
      </div>
    </div>
  )
}

function legendKinds(layers: LayerId[], tab: Tab): HeatKind[] {
  const ready = (id: LayerId) => layers.includes(id) && tab.layers[id].status === 'ready'
  const out: HeatKind[] = []
  if (ready('scan') || ready('points')) out.push('diverging')
  if (ready('coverage')) out.push('sequential')
  return out
}

function Legend({ kind, range }: { kind: HeatKind; range: number }) {
  const gradient = legendGradient(kind)
  const r = fmtMm(range, false)
  return (
    <div className="legend">
      <div className="legend-title">
        <span>{kind === 'diverging' ? 'deviation' : 'distance to scan'}</span>
        <span>mm</span>
      </div>
      <div className="legend-bar" style={{ background: gradient }} />
      <div className="legend-ticks">
        {kind === 'diverging' ? (
          <>
            <span>−{r}</span>
            <span>in · 0 · out</span>
            <span>+{r}</span>
          </>
        ) : (
          <>
            <span>0</span>
            <span>missing →</span>
            <span>{r}</span>
          </>
        )}
      </div>
    </div>
  )
}

function PaneStats({ primary, tab }: { primary: LayerId | null; tab: Tab }) {
  if (!primary) return null
  const st = tab.layers[primary]
  if (st.status === 'missing') {
    return (
      <div className="pane-stats">
        <span>no {LAYER_BY_ID[primary].label.toLowerCase()} layer in this sample</span>
      </div>
    )
  }
  if (st.status === 'error') {
    return (
      <div className="pane-stats">
        <span style={{ color: 'var(--color-red)' }}>{st.error}</span>
      </div>
    )
  }
  if (st.status !== 'ready' || !st.info) return null

  const info = st.info
  const m = tab.row?.metrics
  const p95 = typeof tab.meta?.metrics?.p95_mm === 'number' ? (tab.meta.metrics.p95_mm as number) : null
  return (
    <div className="pane-stats">
      {info.nFaces > 0 ? (
        <span>
          <b>{fmtCount(info.nFaces)}</b> tris
        </span>
      ) : (
        <span>
          <b>{fmtCount(info.nVertices)}</b> pts
        </span>
      )}
      {primary === 'scan' && m && (
        <>
          <span>
            chamfer <b>{fmtMm(m.chamfer_mm, false)}</b>
          </span>
          {p95 !== null && (
            <span>
              p95 <b>{fmtMm(p95, false)}</b>
            </span>
          )}
          <span>
            haus <b>{fmtMm(m.hausdorff_mm, false)}</b>
          </span>
          <span>
            cov <b>{fmtPct(m.coverage)}</b>
          </span>
        </>
      )}
    </div>
  )
}
