import { fmtBytes } from '../../lib/format'
import type { InputStatus } from '../../lib/types'
import { useBatch } from '../../store/useBatch'
import { useStore } from '../../store/useStore'
import { RefreshIcon } from '../icons'

const STATUS_TONE: Record<InputStatus, string> = { new: 'run', done: 'ok', failed: 'bad' }

interface Props {
  selected: Set<string>
  onToggle: (name: string) => void
  onToggleAll: (names: string[] | null) => void
}

/** The dataset's uploaded parts. Checking rows narrows the next job to them. */
export function InputsTable({ selected, onToggle, onToggleAll }: Props) {
  const inputs = useBatch((s) => s.inputs)
  const loading = useBatch((s) => s.inputsLoading)
  const error = useBatch((s) => s.inputsError)
  const refresh = useBatch((s) => s.refreshInputs)
  const dataset = useStore((s) => s.dataset)

  const nNew = inputs.filter((i) => i.status === 'new').length
  const nFailed = inputs.filter((i) => i.status === 'failed').length
  const allChecked = inputs.length > 0 && inputs.every((i) => selected.has(i.name))

  return (
    <div className="card">
      <div className="panel-head">
        <span>Inputs</span>
        <span className="head-aside subtle">
          {inputs.length > 0 && (
            <span>
              {inputs.length} parts · {nNew} new{nFailed ? ` · ${nFailed} failed` : ''}
              {selected.size > 0 && ` · ${selected.size} selected`}
            </span>
          )}
          <button className="icon-btn" disabled={!dataset || loading} onClick={() => void refresh()} title="Reload inputs">
            <RefreshIcon spinning={loading} />
          </button>
        </span>
      </div>

      {error ? (
        <div className="notice" data-kind="error">
          <strong>Inputs unavailable</strong> — {error}
        </div>
      ) : !inputs.length ? (
        <div className="list-note">
          {dataset ? 'No parts uploaded to this dataset yet. Drop some above.' : 'No dataset selected.'}
        </div>
      ) : (
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th style={{ width: 28 }}>
                  <input
                    type="checkbox"
                    checked={allChecked}
                    onChange={() => onToggleAll(allChecked ? null : inputs.map((i) => i.name))}
                    title="Select all"
                  />
                </th>
                <th>Name</th>
                <th>Format</th>
                <th className="right">Size</th>
                <th className="right">Samples</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {inputs.map((i) => (
                <tr key={i.name} onClick={() => onToggle(i.name)} style={{ cursor: 'default' }}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selected.has(i.name)}
                      onChange={() => onToggle(i.name)}
                      onClick={(e) => e.stopPropagation()}
                    />
                  </td>
                  <td className="name" title={i.name}>
                    {i.name}
                  </td>
                  <td className="mono">{i.format}</td>
                  <td className="mono right">{fmtBytes(i.size)}</td>
                  <td className="mono right">{i.n_samples}</td>
                  <td>
                    <span className="badge" data-tone={STATUS_TONE[i.status] ?? 'neutral'}>
                      {i.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
