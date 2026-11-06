import { useState } from 'react'
import { useBatch } from '../../store/useBatch'
import { useStore } from '../../store/useStore'

const randomSeed = () => Math.floor(Math.random() * 2 ** 31)

interface Props {
  /** Inputs checked in the table; empty = the backend default (every `new` input). */
  selected: string[]
  onSubmitted: () => void
}

export function GenerateForm({ selected, onSubmitted }: Props) {
  const online = useStore((s) => s.online)
  const dataset = useStore((s) => s.dataset)
  const profiles = useBatch((s) => s.profiles)
  const inputs = useBatch((s) => s.inputs)
  const submitting = useBatch((s) => s.submitting)
  const submitJob = useBatch((s) => s.submitJob)

  const [profile, setProfile] = useState('random')
  const [samples, setSamples] = useState(8)
  const [seed, setSeed] = useState(() => randomSeed())
  const [savePoints, setSavePoints] = useState(false)

  // The contract says `random` mixes the profiles; offer it even if the
  // backend does not list it explicitly.
  const options = profiles.some((p) => p.id === 'random')
    ? profiles
    : [{ id: 'random', label: 'Random mix', description: 'Weighted mix of every profile', weight: 0 }, ...profiles]
  const chosen = options.find((p) => p.id === profile)

  const nTargets = selected.length || inputs.filter((i) => i.status === 'new').length
  const valid = Number.isInteger(samples) && samples >= 1 && samples <= 64 && Number.isInteger(seed) && seed >= 0
  const canSubmit = online && Boolean(dataset) && valid && nTargets > 0 && !submitting

  return (
    <div className="card">
      <div className="panel-head">
        <span>Generate</span>
      </div>
      <form
        className="form"
        onSubmit={async (e) => {
          e.preventDefault()
          if (!canSubmit || !dataset) return
          const ok = await submitJob({
            dataset,
            profile,
            samples_per_part: samples,
            seed,
            save_points: savePoints,
            ...(selected.length ? { inputs: selected } : {}),
          })
          if (ok) {
            setSeed(randomSeed()) // the next job should not silently repeat this one
            onSubmitted()
          }
        }}
      >
        <div className="control">
          <label className="control-row">
            <span className="control-label">Scanner profile</span>
            <select value={profile} onChange={(e) => setProfile(e.target.value)}>
              {options.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label || p.id}
                </option>
              ))}
            </select>
          </label>
          {chosen?.description && <div className="subtle" style={{ fontSize: 'var(--text-tiny-size)' }}>{chosen.description}</div>}
        </div>

        <div className="control">
          <label className="control-row">
            <span className="control-label">Samples per part</span>
            <input
              type="number"
              min={1}
              max={64}
              step={1}
              value={samples}
              onChange={(e) => setSamples(Math.round(Number(e.target.value)))}
            />
          </label>
        </div>

        <div className="control">
          <div className="control-row">
            <span className="control-label">Seed</span>
            <span style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <button type="button" className="btn sm" onClick={() => setSeed(randomSeed())} title="New random seed">
                ⟳
              </button>
              <input
                type="number"
                min={0}
                step={1}
                value={seed}
                onChange={(e) => setSeed(Math.round(Number(e.target.value)))}
                style={{ width: 118 }}
              />
            </span>
          </div>
        </div>

        <div className="control">
          <label className="control-row" style={{ cursor: 'pointer' }}>
            <span className="control-label">Save raw points</span>
            <input type="checkbox" checked={savePoints} onChange={(e) => setSavePoints(e.target.checked)} />
          </label>
        </div>

        <div className="hint">
          {selected.length
            ? `${selected.length} selected input${selected.length > 1 ? 's' : ''}`
            : `${nTargets} new input${nTargets === 1 ? '' : 's'} (select rows to choose others)`}{' '}
          × {valid ? samples : '?'} = <b>{valid ? nTargets * samples : '—'}</b> samples
          {savePoints && ' · points add a large points.ply per sample'}
        </div>

        <div className="btn-row" style={{ paddingTop: 0 }}>
          <button className="btn" data-variant="primary" type="submit" disabled={!canSubmit}>
            {submitting ? 'Submitting…' : 'Generate'}
          </button>
        </div>
      </form>
    </div>
  )
}
