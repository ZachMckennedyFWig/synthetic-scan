import { useEffect, useState } from 'react'
import { useBatch } from '../../store/useBatch'
import { useStore } from '../../store/useStore'
import { DropZone } from './DropZone'
import { GenerateForm } from './GenerateForm'
import { InputsTable } from './InputsTable'
import { JobsList } from './JobsList'

/** Upload → inputs → generate → jobs, top to bottom in the order you use them. */
export function BatchPage() {
  const online = useStore((s) => s.online)
  const dataset = useStore((s) => s.dataset)
  const health = useStore((s) => s.health)
  const inputs = useBatch((s) => s.inputs)
  const [selected, setSelected] = useState<Set<string>>(new Set())

  // A selection only means something within one dataset's inputs.
  useEffect(() => setSelected(new Set()), [dataset])
  // Drop names that vanished from the list (e.g. after a refresh).
  const valid = [...selected].filter((n) => inputs.some((i) => i.name === n))

  return (
    <div className="batch">
      <div className="batch-inner">
        <div className="batch-head">
          <h1>Batch</h1>
          <span className="muted mono" style={{ fontSize: 'var(--text-mini-size)' }}>
            {dataset ?? 'no dataset'}
            {health && ` · synthscan ${health.version}`}
            {health && !health.open3d && ' · open3d missing'}
          </span>
        </div>

        {!online && (
          <div className="notice" data-kind="error" style={{ margin: 0 }}>
            <strong>Backend offline</strong> — start <code>synthscan serve</code>; uploads and jobs unlock when it
            answers.
          </div>
        )}
        {online && health && !health.step_support && (
          <div className="notice" style={{ margin: 0 }}>
            <strong>No STEP support</strong> — the backend was started without OpenCASCADE, so <code>.step</code>/
            <code>.stp</code> are not accepted. Mesh formats still work.
          </div>
        )}

        <div className="batch-cols">
          <DropZone />
          <GenerateForm selected={valid} onSubmitted={() => setSelected(new Set())} />
        </div>

        <InputsTable
          selected={new Set(valid)}
          onToggle={(name) =>
            setSelected((s) => {
              const next = new Set(s)
              if (next.has(name)) next.delete(name)
              else next.add(name)
              return next
            })
          }
          onToggleAll={(names) => setSelected(new Set(names ?? []))}
        />

        <JobsList />
      </div>
    </div>
  )
}
