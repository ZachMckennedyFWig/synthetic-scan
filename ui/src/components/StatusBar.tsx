import { fmtEta } from '../lib/format'
import { activeProgress, useBatch } from '../store/useBatch'
import { useActiveTab, useStore } from '../store/useStore'

export function StatusBar() {
  const online = useStore((s) => s.online)
  const health = useStore((s) => s.health)
  const busy = useStore((s) => s.busy)
  const mode = useStore((s) => s.mode)
  const view = useStore((s) => s.view)
  const toggleMode = useStore((s) => s.toggleMode)
  const dataset = useStore((s) => s.dataset)
  const dsInfo = useStore((s) => s.datasets.find((d) => d.name === s.dataset))
  const heatmap = useStore((s) => s.display.heatmap)
  const tab = useActiveTab()
  const jobs = useBatch((s) => s.jobs)
  const uploading = useBatch((s) => s.uploads.some((u) => u.status === 'uploading' || u.status === 'queued'))

  const progress = activeProgress(jobs)
  const working = busy > 0 || uploading || Boolean(progress)
  const split = view === 'viewer' ? tab?.split : null

  return (
    <div className="statusbar">
      <span className="dot" data-state={!online ? 'off' : working ? 'busy' : 'on'} />
      <span>
        {online && health ? (
          <>
            cpu <b>{health.cpu_count}</b> · <b>{health.workers}</b> workers
            {!health.step_support && <> · no STEP</>}
          </>
        ) : (
          'backend offline'
        )}
      </span>

      {dataset && (
        <>
          <span className="sep">│</span>
          <span>
            <b>{dataset}</b>
            {dsInfo && (
              <>
                {' '}
                · <b>{dsInfo.n_parts}</b> parts · <b>{dsInfo.n_samples}</b> samples
              </>
            )}
          </span>
        </>
      )}

      {view === 'viewer' && tab && (
        <>
          <span className="sep">│</span>
          {split ? (
            <span className="mode-pill" data-mode="split">
              SPLIT
            </span>
          ) : (
            <button className="mode-pill" data-mode={mode} onClick={toggleMode} title="Space">
              {mode === 'scan' ? 'SCAN + GHOST' : 'GT'}
            </button>
          )}
          {heatmap && <span>heatmap</span>}
          {split && (
            <>
              <span className="sep">│</span>
              <span>
                split <b>{split.length}</b> · synced
              </span>
            </>
          )}
        </>
      )}

      {progress && (
        <>
          <span className="sep">│</span>
          <span className="job-progress">
            {progress.n > 1 ? `${progress.n} jobs` : 'job'} {progress.done}/{progress.total} · eta {fmtEta(progress.eta)}
          </span>
        </>
      )}

      <span className="spacer" />
      <span className="subtle">
        <kbd>Space</kbd> scan/GT · <kbd>S</kbd> split · <kbd>D</kbd> heatmap · <kbd>W</kbd> wire · <kbd>F</kbd> fit ·{' '}
        <kbd>1</kbd>–<kbd>4</kbd> layers · <kbd>Shift</kbd>+click isolate · <kbd>Ctrl</kbd>+click multi
      </span>
    </div>
  )
}

export function Toasts() {
  const toasts = useStore((s) => s.toasts)
  if (!toasts.length) return null
  return (
    <div className="toasts">
      {toasts.map((t) => (
        <div className="toast" key={t.id} data-kind={t.kind} title={t.text}>
          {t.text}
        </div>
      ))}
    </div>
  )
}
