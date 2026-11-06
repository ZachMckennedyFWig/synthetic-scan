import type {
  DatasetInfo,
  Health,
  InputRow,
  Job,
  JobRequest,
  LayerId,
  Profile,
  SampleMeta,
  SampleRow,
  UploadResult,
} from './types'

const BASE = '/api'
const enc = encodeURIComponent

export class HttpError extends Error {
  readonly status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** FastAPI puts a string in `detail` for HTTPException, an array for validation errors. */
function detailOf(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (d as { msg?: string; loc?: unknown[] }).msg ?? JSON.stringify(d))
      .join('; ')
  }
  return fallback
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`
    try {
      message = detailOf(await res.json(), message)
    } catch {
      /* no JSON body; the status line will do */
    }
    throw new HttpError(res.status, message)
  }
  return res.json() as Promise<T>
}

async function get<T>(path: string): Promise<T> {
  return json<T>(await fetch(`${BASE}${path}`))
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  return json<T>(
    await fetch(`${BASE}${path}`, {
      method: 'POST',
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  )
}

export interface UploadHandle {
  promise: Promise<UploadResult>
  abort: () => void
}

export const api = {
  health: () => get<Health>('/health'),
  profiles: () => get<Profile[]>('/profiles'),
  datasets: () => get<DatasetInfo[]>('/datasets'),
  createDataset: (name: string) => post<{ name: string }>('/datasets', { name }),

  inputs: (ds: string) => get<InputRow[]>(`/datasets/${enc(ds)}/inputs`),

  /**
   * One file per request, through XHR rather than fetch: fetch still has no
   * upload-progress events, and per-file bars are the point of the batch page.
   * The contract allows `files` repeated; sending one keeps a failure local to
   * the file that caused it.
   */
  uploadInput(ds: string, file: File, onProgress: (loaded: number, total: number) => void): UploadHandle {
    const xhr = new XMLHttpRequest()
    const promise = new Promise<UploadResult>((resolve, reject) => {
      xhr.open('POST', `${BASE}/datasets/${enc(ds)}/inputs`)
      xhr.responseType = 'json'
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(e.loaded, e.total)
      }
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response as UploadResult)
        else reject(new HttpError(xhr.status, detailOf(xhr.response, `${xhr.status} ${xhr.statusText}`)))
      }
      xhr.onerror = () => reject(new Error('network error'))
      xhr.onabort = () => reject(new Error('aborted'))
      const fd = new FormData()
      fd.append('files', file, file.name)
      xhr.send(fd)
    })
    return { promise, abort: () => xhr.abort() }
  },

  samples: (ds: string) => get<SampleRow[]>(`/datasets/${enc(ds)}/samples`),
  sampleMeta: (ds: string, sid: string) => get<SampleMeta>(`/datasets/${enc(ds)}/samples/${enc(sid)}`),

  /** Raw SSG1 bytes, or null when the sample simply has no such layer (404). */
  async geometry(ds: string, sid: string, layer: LayerId, signal?: AbortSignal): Promise<ArrayBuffer | null> {
    const res = await fetch(`${BASE}/datasets/${enc(ds)}/samples/${enc(sid)}/geometry/${layer}`, { signal })
    if (res.status === 404) return null
    if (!res.ok) {
      let message = `${res.status} ${res.statusText}`
      try {
        message = detailOf(await res.json(), message)
      } catch {
        /* binary or empty error body */
      }
      throw new HttpError(res.status, message)
    }
    return res.arrayBuffer()
  },

  fileUrl: (ds: string, sid: string, name: string) =>
    `${BASE}/datasets/${enc(ds)}/samples/${enc(sid)}/files/${enc(name)}`,

  jobs: () => get<Job[]>('/jobs'),
  submitJob: (req: JobRequest) => post<{ id: string }>('/jobs', req),
  cancelJob: (id: string) => post<Job>(`/jobs/${enc(id)}/cancel`),
}
