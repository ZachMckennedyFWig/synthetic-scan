import type { MouseEvent } from 'react'
import { fmtCount } from '../lib/format'
import { LAYERS } from '../lib/layers'
import type { LayerId } from '../lib/types'
import { useActiveTab, useStore, type LayerState } from '../store/useStore'
import { EyeIcon } from './icons'

/**
 * The four API layers, FootprintUi-style: eye toggles, Shift-click isolates,
 * Ctrl-click multi-selects, and the selection becomes split-screen panes.
 */
export function LayerPanel() {
  const layers = useStore((s) => s.layers)
  const selection = useStore((s) => s.selection)
  const select = useStore((s) => s.select)
  const toggleLayer = useStore((s) => s.toggleLayer)
  const soloOrRestore = useStore((s) => s.soloOrRestore)
  const enterSplit = useStore((s) => s.enterSplit)
  const exitSplit = useStore((s) => s.exitSplit)
  const tab = useActiveTab()

  const splitReady = selection.length >= 2
  const inSplit = Boolean(tab?.split)

  function onRowClick(e: MouseEvent, id: LayerId) {
    if (e.shiftKey && !e.ctrlKey && !e.metaKey) {
      soloOrRestore(id)
      return
    }
    select(id, e.ctrlKey || e.metaKey)
  }

  return (
    <div className="panel-section">
      <div className="panel-head">
        <span>Layers</span>
        <span className="head-aside subtle">
          {layers.filter((l) => l.visible).length}/{layers.length} on
        </span>
      </div>

      <div onClick={(e) => e.target === e.currentTarget && useStore.getState().clearSelection()}>
        {LAYERS.map((def, i) => {
          const cfg = layers.find((l) => l.id === def.id)
          const st = tab?.layers[def.id]
          return (
            <div
              key={def.id}
              className="layer"
              data-selected={selection.includes(def.id)}
              data-unavailable={st?.status === 'missing'}
              onClick={(e) => onRowClick(e, def.id)}
              title={`${def.label}\n${def.hint}`}
            >
              <span className="layer-key">{i + 1}</span>
              <button
                className="layer-eye"
                data-on={Boolean(cfg?.visible)}
                onClick={(e) => {
                  e.stopPropagation()
                  if (e.shiftKey) soloOrRestore(def.id)
                  else toggleLayer(def.id)
                }}
                title="Toggle · Shift-click to isolate"
              >
                <EyeIcon on={Boolean(cfg?.visible)} />
              </button>
              <span className="layer-swatch" style={{ background: def.color }} />
              <span className="layer-name">{def.label}</span>
              <LayerMeta st={st} />
            </div>
          )
        })}
      </div>

      <div className="btn-row" style={{ borderTop: '1px solid var(--color-border-primary)' }}>
        {inSplit ? (
          <button className="btn" data-variant="primary" onClick={exitSplit}>
            Exit split screen
          </button>
        ) : (
          <button
            className="btn"
            data-variant={splitReady ? 'primary' : undefined}
            disabled={!splitReady || !tab}
            onClick={() => enterSplit(selection)}
            title={splitReady ? 'Open each selected layer in its own synced pane' : 'Ctrl-click two or more layers first (or press S)'}
          >
            Split screen{splitReady ? ` (${selection.length})` : ''}
          </button>
        )}
      </div>
    </div>
  )
}

function LayerMeta({ st }: { st: LayerState | undefined }) {
  if (!st || st.status === 'idle') {
    return (
      <span className="layer-meta subtle" title="Not loaded — switch it on to fetch">
        —
      </span>
    )
  }
  if (st.status === 'loading') return <span className="layer-meta" data-state="loading">···</span>
  if (st.status === 'error') {
    return (
      <span className="layer-meta" data-state="error" title={st.error}>
        error
      </span>
    )
  }
  if (st.status === 'missing' || !st.info) {
    return (
      <span className="layer-meta subtle" title="This sample has no such layer">
        —
      </span>
    )
  }
  const { nVertices, nFaces } = st.info
  return (
    <span className="layer-meta" title={`${nVertices.toLocaleString()} vertices · ${nFaces.toLocaleString()} triangles`}>
      {nFaces > 0 ? `${fmtCount(nFaces)} tris` : `${fmtCount(nVertices)} pts`}
    </span>
  )
}
