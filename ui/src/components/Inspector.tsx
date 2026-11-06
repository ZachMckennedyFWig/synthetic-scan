import { Fragment } from 'react'
import { api } from '../lib/api'
import { fmtCount, fmtMm, fmtPct, fmtValue } from '../lib/format'
import type { SampleMetrics } from '../lib/types'
import { useActiveTab } from '../store/useStore'

/** Metrics, sampled parameters and artifacts of the active sample. */
export function Inspector() {
  const tab = useActiveTab()
  const row = tab?.row
  const meta = tab?.meta

  return (
    <div className="panel-section">
      <div className="panel-head">
        <span>Inspector</span>
        {tab && (
          <span className="head-aside">
            <a className="btn sm" href={api.fileUrl(tab.dataset, tab.sampleId, 'scan.stl')} download>
              scan.stl
            </a>
            <a className="btn sm" href={api.fileUrl(tab.dataset, tab.sampleId, 'meta.json')} download>
              meta.json
            </a>
          </span>
        )}
      </div>

      {!tab ? (
        <dl className="kv">
          <dt>—</dt>
          <dd>Open a sample</dd>
        </dl>
      ) : (
        <>
          <dl className="kv">
            <dt>sample</dt>
            <dd>{tab.sampleId}</dd>
            {row && (
              <>
                <dt>part</dt>
                <dd>{row.part_name}</dd>
                <dt>split</dt>
                <dd>{row.split}</dd>
                <dt>profile</dt>
                <dd>{row.profile}</dd>
              </>
            )}
            {row?.metrics && <MetricsKv m={row.metrics} />}
          </dl>

          {row?.artifacts?.length ? (
            <>
              <div className="param-group-head">artifacts</div>
              <div className="badges" style={{ paddingTop: 5 }}>
                {row.artifacts.map((a) => (
                  <span key={a} className="badge" data-tone="neutral">
                    {a}
                  </span>
                ))}
              </div>
            </>
          ) : null}

          {tab.metaError && (
            <div className="notice" data-kind="error">
              <strong>meta.json unavailable</strong> — {tab.metaError}
            </div>
          )}

          {meta?.params && Object.keys(meta.params).length > 0 && (
            <>
              <div className="panel-head" style={{ paddingBottom: 0, borderTop: '1px solid var(--color-border-primary)' }}>
                <span>Sampled parameters</span>
              </div>
              <ParamTree value={meta.params} />
            </>
          )}

          {/* meta.artifacts may carry per-stage parameters (objects) rather than
              bare names; show those generically too. */}
          {Array.isArray(meta?.artifacts) && meta.artifacts.some((a) => a && typeof a === 'object') && (
            <>
              <div className="panel-head" style={{ paddingBottom: 0 }}>
                <span>Artifact stages</span>
              </div>
              <ParamTree value={meta.artifacts as unknown[]} />
            </>
          )}
        </>
      )}
    </div>
  )
}

function MetricsKv({ m }: { m: SampleMetrics }) {
  return (
    <>
      <dt>chamfer</dt>
      <dd>{fmtMm(m.chamfer_mm)}</dd>
      <dt>hausdorff</dt>
      <dd>{fmtMm(m.hausdorff_mm)}</dd>
      <dt>rms</dt>
      <dd>{fmtMm(m.rms_mm)}</dd>
      <dt>coverage</dt>
      <dd>{fmtPct(m.coverage, 2)}</dd>
      <dt>triangles</dt>
      <dd>{fmtCount(m.n_tris)}</dd>
      <dt>watertight</dt>
      <dd data-tone={m.watertight ? undefined : 'bad'}>{m.watertight ? 'yes' : 'no'}</dd>
      <dt>components</dt>
      <dd>{m.n_components}</dd>
      <dt>boundary edges</dt>
      <dd>{fmtCount(m.n_boundary_edges)}</dd>
    </>
  )
}

const isPlainObject = (v: unknown): v is Record<string, unknown> =>
  v !== null && typeof v === 'object' && !Array.isArray(v)

/** Arrays of scalars (vectors, ranges) read best inline. */
const isScalarArray = (v: unknown): v is unknown[] =>
  Array.isArray(v) && v.length <= 16 && v.every((x) => x === null || typeof x !== 'object')

/**
 * Render an arbitrary nested object as grouped kv blocks: scalars of one level
 * form one kv grid, each nested object becomes a sub-group under its key.
 * Generic on purpose -- the parameter schema belongs to the backend.
 */
function ParamTree({ value }: { value: Record<string, unknown> | unknown[] }) {
  const entries: [string, unknown][] = Array.isArray(value)
    ? value.map((v, i) => [isPlainObject(v) && typeof v.name === 'string' ? v.name : `[${i}]`, v])
    : Object.entries(value)

  const leaves = entries.filter(([, v]) => !isPlainObject(v) && !(Array.isArray(v) && !isScalarArray(v)))
  const groups = entries.filter(([, v]) => isPlainObject(v) || (Array.isArray(v) && !isScalarArray(v)))

  return (
    <div>
      {leaves.length > 0 && (
        <dl className="kv">
          {leaves.map(([k, v]) => (
            <Fragment key={k}>
              <dt title={k}>{k}</dt>
              <dd>{isScalarArray(v) ? `[${v.map(fmtValue).join(', ')}]` : fmtValue(v)}</dd>
            </Fragment>
          ))}
        </dl>
      )}
      {groups.map(([k, v]) => (
        <div key={k} className="param-group">
          <div className="param-group-head">{k}</div>
          <ParamTree value={v as Record<string, unknown> | unknown[]} />
        </div>
      ))}
    </div>
  )
}
