import { useEffect, useRef, useState } from 'react'
import { fmtBytes } from '../../lib/format'
import { acceptedExtensions, collectDrop, collectFileList, type Collected } from '../../lib/files'
import { useBatch, type UploadItem } from '../../store/useBatch'
import { useStore } from '../../store/useStore'

/** Rendered rows are capped: a dropped folder can hold thousands of parts. */
const MAX_ROWS = 300

export function DropZone() {
  const online = useStore((s) => s.online)
  const dataset = useStore((s) => s.dataset)
  const stepSupport = useStore((s) => s.health?.step_support ?? true)
  const toast = useStore((s) => s.toast)
  const enqueue = useBatch((s) => s.enqueue)
  const uploads = useBatch((s) => s.uploads)
  const cancelUploads = useBatch((s) => s.cancelUploads)
  const clearFinished = useBatch((s) => s.clearFinishedUploads)

  const [dragging, setDragging] = useState(false)
  const [scanning, setScanning] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const dirRef = useRef<HTMLInputElement>(null)
  const exts = acceptedExtensions(stepSupport)
  const enabled = online && Boolean(dataset)

  // `webkitdirectory` is not in React's input props; set it on the element.
  useEffect(() => {
    dirRef.current?.setAttribute('webkitdirectory', '')
  }, [])

  function accept(c: Collected) {
    if (c.rejected.length) {
      const sample = c.rejected.slice(0, 3).join(', ')
      toast(`Ignored ${c.rejected.length} unsupported file${c.rejected.length > 1 ? 's' : ''}: ${sample}${c.rejected.length > 3 ? '…' : ''}`)
    }
    if (c.files.length) enqueue(c.files)
    else if (!c.rejected.length) toast('Nothing to upload')
  }

  const counts = countUploads(uploads)
  const inFlight = counts.queued + counts.uploading > 0
  const totalBytes = uploads.reduce((a, u) => a + u.size, 0)
  const loadedBytes = uploads.reduce((a, u) => a + Math.min(u.loaded, u.size), 0)
  // Active first, then the newest finished ones.
  const shown = [...uploads]
    .sort((a, b) => rank(a) - rank(b) || b.id - a.id)
    .slice(0, MAX_ROWS)

  return (
    <div className="card">
      <div className="panel-head">
        <span>Upload parts</span>
        <span className="head-aside subtle">
          {uploads.length > 0 && (
            <span>
              {counts.saved} saved · {counts.skipped} skipped · {counts.error} failed
              {inFlight && ` · ${counts.queued + counts.uploading} to go`}
            </span>
          )}
        </span>
      </div>

      <div
        className="dropzone"
        data-dragging={dragging}
        data-disabled={!enabled}
        onDragOver={(e) => {
          e.preventDefault()
          e.dataTransfer.dropEffect = enabled ? 'copy' : 'none'
          setDragging(true)
        }}
        onDragLeave={(e) => {
          if (e.currentTarget === e.target) setDragging(false)
        }}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          if (!enabled) {
            toast(online ? 'Select a dataset first' : 'Backend offline', 'error')
            return
          }
          setScanning(true)
          // collectDrop reads the entries synchronously before awaiting.
          collectDrop(e.dataTransfer, exts)
            .then(accept)
            .catch((err: Error) => toast(`Reading drop: ${err.message}`, 'error'))
            .finally(() => setScanning(false))
        }}
      >
        <strong>{scanning ? 'Reading folders…' : 'Drop CAD files or whole folders'}</strong>
        <span>
          {enabled ? (
            <>
              into <b className="mono">{dataset}</b> — folders are searched recursively
            </>
          ) : online ? (
            'Create or select a dataset first'
          ) : (
            'Backend offline'
          )}
        </span>
        <span className="exts">{exts.join(' ')}</span>
        <span style={{ display: 'flex', gap: 6 }}>
          <button className="btn" disabled={!enabled} onClick={() => fileRef.current?.click()}>
            Choose files…
          </button>
          <button className="btn" disabled={!enabled} onClick={() => dirRef.current?.click()}>
            Choose folder…
          </button>
        </span>
        <input
          ref={fileRef}
          type="file"
          multiple
          hidden
          accept={exts.join(',')}
          onChange={(e) => {
            accept(collectFileList(e.target.files, exts))
            e.target.value = ''
          }}
        />
        <input
          ref={dirRef}
          type="file"
          multiple
          hidden
          onChange={(e) => {
            accept(collectFileList(e.target.files, exts))
            e.target.value = ''
          }}
        />
      </div>

      {uploads.length > 0 && (
        <>
          <div className="control" style={{ paddingTop: 0 }}>
            <div className="control-row">
              <span className="control-label">
                {fmtBytes(loadedBytes)} / {fmtBytes(totalBytes)}
              </span>
              <span style={{ display: 'flex', gap: 6 }}>
                {inFlight ? (
                  <button className="btn sm" data-variant="danger" onClick={cancelUploads}>
                    Cancel
                  </button>
                ) : (
                  <button className="btn sm" onClick={clearFinished}>
                    Clear
                  </button>
                )}
              </span>
            </div>
            <div className="progress" data-state={inFlight ? undefined : 'done'}>
              <span style={{ width: `${totalBytes ? (loadedBytes / totalBytes) * 100 : 0}%` }} />
            </div>
          </div>
          <div className="upload-list">
            {shown.map((u) => (
              <UploadRow key={u.id} u={u} />
            ))}
            {uploads.length > MAX_ROWS && (
              <div className="list-note">+{uploads.length - MAX_ROWS} more not shown</div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

function UploadRow({ u }: { u: UploadItem }) {
  const pct = u.size ? Math.min(100, (u.loaded / u.size) * 100) : 0
  return (
    <div className="upload" title={u.reason ? `${u.name}\n${u.reason}` : u.name}>
      <span className="name">{u.name}</span>
      <span className="size">{fmtBytes(u.size)}</span>
      {u.status === 'uploading' ? (
        <div className="progress">
          <span style={{ width: `${pct}%` }} />
        </div>
      ) : (
        <span className="state" data-status={u.status}>
          {u.status === 'queued' ? 'queued' : u.status === 'saved' ? 'saved' : u.status === 'skipped' ? `skipped · ${u.reason ?? ''}` : `error · ${u.reason ?? ''}`}
        </span>
      )}
    </div>
  )
}

function rank(u: UploadItem): number {
  return u.status === 'uploading' ? 0 : u.status === 'queued' ? 1 : u.status === 'error' ? 2 : 3
}

function countUploads(list: UploadItem[]) {
  const c = { queued: 0, uploading: 0, saved: 0, skipped: 0, error: 0 }
  for (const u of list) c[u.status]++
  return c
}
