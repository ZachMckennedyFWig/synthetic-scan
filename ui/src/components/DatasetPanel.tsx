import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { fmtMm, fmtPct } from '../lib/format'
import type { SampleRow } from '../lib/types'
import { sampleKey } from '../render/geometryCache'
import type { SortKey } from '../store/prefs'
import { sampleLabel, useStore } from '../store/useStore'
import { RefreshIcon, SortIcon } from './icons'

const ROW_H = 26

const SORTS: { id: SortKey; label: string }[] = [
  { id: 'name', label: 'name' },
  { id: 'chamfer', label: 'chamfer' },
  { id: 'hausdorff', label: 'hausdorff' },
  { id: 'coverage', label: 'coverage' },
]

function metricOf(row: SampleRow, key: SortKey): number {
  const m = row.metrics
  if (key === 'hausdorff') return m?.hausdorff_mm ?? NaN
  if (key === 'coverage') return m?.coverage ?? NaN
  return m?.chamfer_mm ?? NaN
}

/** Dataset picker + the sample browser. */
export function DatasetPanel() {
  const datasets = useStore((s) => s.datasets)
  const dataset = useStore((s) => s.dataset)
  const online = useStore((s) => s.online)
  const selectDataset = useStore((s) => s.selectDataset)
  const createDataset = useStore((s) => s.createDataset)
  const refreshSamples = useStore((s) => s.refreshSamples)
  const samplesLoading = useStore((s) => s.samplesLoading)
  const samplesError = useStore((s) => s.samplesError)
  const samples = useStore((s) => s.samples)
  const sampleIndex = useStore((s) => s.sampleIndex)
  const filter = useStore((s) => s.filter)
  const setFilter = useStore((s) => s.setFilter)
  const sort = useStore((s) => s.sort)
  const sortDesc = useStore((s) => s.sortDesc)
  const setSort = useStore((s) => s.setSort)
  const browseNonce = useStore((s) => s.browseNonce)

  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const filterRef = useRef<HTMLInputElement>(null)

  // "+" in the tab bar lands here.
  useEffect(() => {
    if (browseNonce) {
      filterRef.current?.focus()
      filterRef.current?.select()
    }
  }, [browseNonce])

  const rows = useMemo(() => {
    const q = filter.trim().toLowerCase()
    const list = q
      ? samples.filter((r) =>
          [r.part_name, r.id, r.profile, r.split, ...(r.artifacts ?? [])].some((v) => v?.toLowerCase().includes(q)),
        )
      : samples.slice()
    const dir = sortDesc ? -1 : 1
    if (sort === 'name') {
      list.sort((a, b) => dir * (a.part_name.localeCompare(b.part_name) || (sampleIndex[a.id] ?? 0) - (sampleIndex[b.id] ?? 0)))
    } else {
      // NaN (missing metric) always sinks to the bottom, whatever the direction.
      list.sort((a, b) => {
        const va = metricOf(a, sort)
        const vb = metricOf(b, sort)
        if (Number.isNaN(va)) return Number.isNaN(vb) ? 0 : 1
        if (Number.isNaN(vb)) return -1
        return dir * (va - vb)
      })
    }
    return list
  }, [samples, filter, sort, sortDesc, sampleIndex])

  const dsInfo = datasets.find((d) => d.name === dataset)

  return (
    <div className="panel-section grow">
      <div className="panel-head">
        <span>Dataset</span>
        <span className="head-aside subtle">
          {dsInfo && (
            <span>
              {dsInfo.n_parts} parts · {dsInfo.n_samples} samples
            </span>
          )}
          <button
            className="icon-btn"
            disabled={!dataset || samplesLoading}
            title="Reload samples"
            onClick={() => void refreshSamples()}
          >
            <RefreshIcon spinning={samplesLoading} />
          </button>
        </span>
      </div>

      {creating ? (
        <form
          className="ds-row"
          onSubmit={async (e) => {
            e.preventDefault()
            if (await createDataset(newName)) {
              setCreating(false)
              setNewName('')
            }
          }}
        >
          <input
            autoFocus
            className="text-input grow"
            placeholder="new dataset name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === 'Escape' && setCreating(false)}
          />
          <button className="btn sm" data-variant="primary" type="submit" disabled={!newName.trim()}>
            Create
          </button>
          <button className="btn sm" type="button" onClick={() => setCreating(false)}>
            Cancel
          </button>
        </form>
      ) : (
        <div className="ds-row">
          <select
            value={dataset ?? ''}
            disabled={!online || !datasets.length}
            onChange={(e) => selectDataset(e.target.value || null)}
          >
            {!datasets.length && <option value="">{online ? 'no datasets' : 'offline'}</option>}
            {datasets.map((d) => (
              <option key={d.name} value={d.name}>
                {d.name}
              </option>
            ))}
          </select>
          <button className="btn sm" disabled={!online} onClick={() => setCreating(true)} title="Create a dataset">
            New
          </button>
        </div>
      )}

      <div className="ds-row">
        <input
          ref={filterRef}
          className="text-input grow"
          placeholder="Filter part, profile, artifact…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              setFilter('')
              e.currentTarget.blur()
            } else if (e.key === 'Enter' && rows[0]) {
              useStore.getState().openSample(rows[0])
              e.currentTarget.blur()
            }
          }}
        />
        <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)} title="Sort by">
          {SORTS.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
        <button className="icon-btn" onClick={() => setSort(sort, !sortDesc)} title="Reverse order">
          <SortIcon desc={sortDesc} />
        </button>
      </div>

      {samplesError ? (
        <div className="notice" data-kind="error">
          <strong>Samples unavailable</strong> — {samplesError}
        </div>
      ) : !dataset ? (
        <div className="list-note">{online ? 'Create a dataset to get started.' : 'Waiting for the backend…'}</div>
      ) : !samples.length ? (
        <div className="list-note">
          {samplesLoading ? 'Loading…' : 'No samples yet — run a generation job from the Batch page.'}
        </div>
      ) : (
        <SampleList rows={rows} sortKey={sort} sampleIndex={sampleIndex} total={samples.length} />
      )}
    </div>
  )
}

/**
 * Fixed-height windowed list: a dataset can hold tens of thousands of samples,
 * and mounting a row for each makes every filter keystroke a layout storm.
 */
function SampleList({
  rows,
  sortKey: key,
  sampleIndex,
  total,
}: {
  rows: SampleRow[]
  sortKey: SortKey
  sampleIndex: Record<string, number>
  total: number
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [scrollTop, setScrollTop] = useState(0)
  const [height, setHeight] = useState(300)
  const dataset = useStore((s) => s.dataset)
  const activeTabId = useStore((s) => s.activeTabId)
  const view = useStore((s) => s.view)
  const openIds = useStore((s) => s.tabs.map((t) => t.id).join('\n'))
  const openSample = useStore((s) => s.openSample)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setHeight(e.contentRect.height))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const open = useMemo(() => new Set(openIds.split('\n')), [openIds])
  const first = Math.max(0, Math.floor(scrollTop / ROW_H) - 4)
  const last = Math.min(rows.length, Math.ceil((scrollTop + height) / ROW_H) + 4)
  const metricKey: SortKey = key === 'name' ? 'chamfer' : key

  return (
    <>
      <div ref={ref} className="sample-list" onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}>
        <div style={{ height: rows.length * ROW_H, position: 'relative' }}>
          {rows.slice(first, last).map((row, i) => {
            const id = dataset ? sampleKey(dataset, row.id) : row.id
            const v = metricOf(row, metricKey)
            return (
              <div
                key={row.id}
                className="sample"
                style={{ top: (first + i) * ROW_H }}
                data-open={open.has(id)}
                data-active={view === 'viewer' && activeTabId === id}
                onClick={() => openSample(row)}
                title={`${row.id}\n${row.profile}${row.artifacts?.length ? `\n${row.artifacts.join(', ')}` : ''}`}
              >
                <span className="sample-name">{sampleLabel(row, sampleIndex)}</span>
                <span className="badge" data-tone={row.split}>
                  {row.split}
                </span>
                <span className="sample-metric">
                  {metricKey === 'coverage' ? fmtPct(v) : fmtMm(v, false)}
                </span>
              </div>
            )
          })}
        </div>
      </div>
      {rows.length !== total && (
        <div className="list-note" style={{ paddingBlock: 5 }}>
          {rows.length} of {total} match
        </div>
      )}
    </>
  )
}
