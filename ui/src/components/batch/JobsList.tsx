import { useState } from 'react'
import { fmtClock, fmtEta } from '../../lib/format'
import type { Job, JobState } from '../../lib/types'
import { isActiveJob, shortId, useBatch } from '../../store/useBatch'
import { RefreshIcon } from '../icons'

const STATE_TONE: Record<JobState, string> = {
  queued: 'neutral',
  running: 'run',
  done: 'ok',
  failed: 'bad',
  cancelled: 'neutral',
}

export function JobsList() {
  const jobs = useBatch((s) => s.jobs)
  const error = useBatch((s) => s.jobsError)
  const refreshJobs = useBatch((s) => s.refreshJobs)
  const active = jobs.filter(isActiveJob).length

  return (
    <div className="card">
      <div className="panel-head">
        <span>Jobs</span>
        <span className="head-aside subtle">
          {jobs.length > 0 && (
            <span>
              {active} active · {jobs.length} total
            </span>
          )}
          <button className="icon-btn" onClick={() => void refreshJobs()} title="Reload jobs">
            <RefreshIcon />
          </button>
        </span>
      </div>
      {error && (
        <div className="notice" data-kind="error">
          <strong>Jobs unavailable</strong> — {error}
        </div>
      )}
      {!jobs.length ? (
        <div className="list-note">No jobs yet. Upload parts, then Generate.</div>
      ) : (
        jobs.map((j) => <JobRow key={j.id} job={j} />)
      )}
    </div>
  )
}

function JobRow({ job }: { job: Job }) {
  const cancelJob = useBatch((s) => s.cancelJob)
  const [open, setOpen] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const active = isActiveJob(job)
  const okPct = job.total ? (job.done / job.total) * 100 : 0
  const failPct = job.total ? (job.failed / job.total) * 100 : 0
  const elapsed = job.started ? (job.finished ?? Date.now() / 1000) - job.started : null

  return (
    <div className="job">
      <div className="job-head">
        <span className="id" title={job.id}>
          {shortId(job.id)}
        </span>
        <span className="badge" data-tone={STATE_TONE[job.state]}>
          {job.state}
        </span>
        <span className="muted">
          {job.dataset} · {job.profile}
        </span>
        <span className="grow" />
        {active && (
          <button
            className="btn sm"
            data-variant="danger"
            disabled={cancelling}
            onClick={async () => {
              setCancelling(true)
              await cancelJob(job.id)
              setCancelling(false)
            }}
          >
            {cancelling ? 'Cancelling…' : 'Cancel'}
          </button>
        )}
      </div>

      <div className="progress" data-state={job.state === 'done' && !job.failed ? 'done' : undefined}>
        <span style={{ width: `${okPct}%` }} />
        <span data-kind="failed" style={{ width: `${failPct}%` }} />
      </div>

      <div className="job-meta">
        <span>
          <b>{job.done}</b>/{job.total} done
        </span>
        {job.failed > 0 && (
          <span style={{ color: 'var(--color-red)' }}>
            <b style={{ color: 'inherit' }}>{job.failed}</b> failed
          </span>
        )}
        {active && job.eta_s != null && (
          <span>
            eta <b>{fmtEta(job.eta_s)}</b>
          </span>
        )}
        {elapsed != null && (
          <span>
            {active ? 'running' : 'took'} <b>{fmtEta(elapsed)}</b>
          </span>
        )}
        <span>created {fmtClock(job.created)}</span>
        <span style={{ flex: 1 }} />
        {job.errors.length > 0 && (
          <button className="link-btn" onClick={() => setOpen((o) => !o)}>
            {open ? 'hide' : 'show'} {job.errors.length} error{job.errors.length > 1 ? 's' : ''}
          </button>
        )}
      </div>

      {open && job.errors.length > 0 && (
        <ul className="job-errors">
          {job.errors.map((e, i) => (
            <li key={i}>
              <b>{e.input}</b>
              {e.sample && <> · {e.sample}</>} — {e.error}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
