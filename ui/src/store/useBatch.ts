/**
 * Batch-side state: profiles, the dataset's inputs, uploads in flight, jobs.
 *
 * Separate from the viewer store because it churns at a different rate --
 * upload progress and the 1 s job poll would otherwise re-run every viewer
 * selector for nothing.
 */
import { create } from 'zustand'
import { api } from '../lib/api'
import type { InputRow, Job, JobRequest, Profile } from '../lib/types'
import { useStore } from './useStore'

export type UploadStatus = 'queued' | 'uploading' | 'saved' | 'skipped' | 'error'

export interface UploadItem {
  id: number
  dataset: string
  name: string
  size: number
  loaded: number
  status: UploadStatus
  reason?: string
}

interface Batch {
  profiles: Profile[]
  inputs: InputRow[]
  inputsLoading: boolean
  inputsError: string | null
  uploads: UploadItem[]
  jobs: Job[]
  jobsError: string | null
  submitting: boolean

  loadProfiles: () => Promise<void>
  refreshInputs: () => Promise<void>
  enqueue: (files: File[]) => void
  cancelUploads: () => void
  clearFinishedUploads: () => void

  refreshJobs: () => Promise<void>
  submitJob: (req: JobRequest) => Promise<boolean>
  cancelJob: (id: string) => Promise<void>
}

/** Parallel uploads. Enough to hide per-request latency on many small STLs,
 *  few enough that one big STEP still gets most of the bandwidth. */
const CONCURRENCY = 4
const POLL_MS = 1000

export const isActiveJob = (j: Job) => j.state === 'queued' || j.state === 'running'

// File objects and XHR handles stay out of the store: they are not state
// anything renders, and keeping them here avoids holding them in snapshots.
const files = new Map<number, File>()
const aborts = new Map<number, () => void>()
const lastPatch = new Map<number, number>()
const queue: number[] = []
let active = 0
let uploadSeq = 0
let roundSaved = 0
let roundSkipped = 0
let roundFailed = 0
let pollTimer: number | undefined

export const useBatch = create<Batch>((set, get) => {
  const patchUpload = (id: number, patch: Partial<UploadItem>) =>
    set((s) => ({ uploads: s.uploads.map((u) => (u.id === id ? { ...u, ...patch } : u)) }))

  const finishRound = () => {
    const toast = useStore.getState().toast
    const parts = [`${roundSaved} uploaded`]
    if (roundSkipped) parts.push(`${roundSkipped} skipped`)
    if (roundFailed) parts.push(`${roundFailed} failed`)
    toast(parts.join(' · '), roundFailed ? 'error' : 'info')
    roundSaved = roundSkipped = roundFailed = 0
    void get().refreshInputs()
    void useStore.getState().loadDatasets() // n_inputs changed
  }

  const pump = () => {
    while (active < CONCURRENCY && queue.length) {
      const id = queue.shift()!
      const file = files.get(id)
      const item = get().uploads.find((u) => u.id === id)
      if (!file || !item) continue
      active++
      patchUpload(id, { status: 'uploading' })
      const handle = api.uploadInput(item.dataset, file, (loaded) => {
        // XHR fires progress every few ms on a fast link; 10 Hz is plenty for a bar.
        const now = performance.now()
        if (now - (lastPatch.get(id) ?? 0) < 100) return
        lastPatch.set(id, now)
        patchUpload(id, { loaded })
      })
      aborts.set(id, handle.abort)
      handle.promise
        .then((res) => {
          const skipped = res.skipped?.find((s) => s.name === file.name)
          if (skipped) {
            roundSkipped++
            patchUpload(id, { status: 'skipped', reason: skipped.reason, loaded: item.size })
          } else {
            roundSaved++
            patchUpload(id, { status: 'saved', loaded: item.size })
          }
        })
        .catch((err: Error) => {
          roundFailed++
          patchUpload(id, { status: 'error', reason: err.message })
        })
        .finally(() => {
          active--
          files.delete(id)
          aborts.delete(id)
          lastPatch.delete(id)
          if (queue.length) pump()
          else if (active === 0) finishRound()
        })
    }
  }

  return {
    profiles: [],
    inputs: [],
    inputsLoading: false,
    inputsError: null,
    uploads: [],
    jobs: [],
    jobsError: null,
    submitting: false,

    async loadProfiles() {
      try {
        set({ profiles: await api.profiles() })
      } catch (err) {
        useStore.getState().toast(`Profiles: ${(err as Error).message}`, 'error')
      }
    },

    async refreshInputs() {
      const ds = useStore.getState().dataset
      if (!ds) {
        set({ inputs: [], inputsError: null })
        return
      }
      set({ inputsLoading: true })
      try {
        const inputs = await api.inputs(ds)
        if (useStore.getState().dataset === ds) set({ inputs, inputsError: null })
      } catch (err) {
        set({ inputsError: (err as Error).message })
      } finally {
        set({ inputsLoading: false })
      }
    },

    enqueue(list) {
      const ds = useStore.getState().dataset
      if (!ds) {
        useStore.getState().toast('Create or select a dataset before uploading', 'error')
        return
      }
      const items: UploadItem[] = list.map((f) => {
        const id = ++uploadSeq
        files.set(id, f)
        queue.push(id)
        return { id, dataset: ds, name: f.name, size: f.size, loaded: 0, status: 'queued' }
      })
      set((s) => ({ uploads: [...s.uploads, ...items] }))
      pump()
    },

    cancelUploads() {
      // Queued ones never started; in-flight ones abort and land as errors.
      for (const id of queue.splice(0)) {
        files.delete(id)
        patchUpload(id, { status: 'error', reason: 'cancelled' })
      }
      for (const abort of aborts.values()) abort()
    },

    clearFinishedUploads() {
      set((s) => ({ uploads: s.uploads.filter((u) => u.status === 'queued' || u.status === 'uploading') }))
    },

    async refreshJobs() {
      window.clearTimeout(pollTimer)
      const before = get().jobs
      try {
        const jobs = await api.jobs()
        const wasActive = new Set(before.filter(isActiveJob).map((j) => j.id))
        const finished = jobs.filter((j) => wasActive.has(j.id) && !isActiveJob(j))
        set({ jobs, jobsError: null })
        if (finished.length) onJobsFinished(finished)
      } catch (err) {
        set({ jobsError: (err as Error).message })
      }
      // Poll only while something can still change. A failed poll keeps the
      // last known (active) list, so polling resumes by itself on reconnect.
      if (get().jobs.some(isActiveJob)) pollTimer = window.setTimeout(() => void get().refreshJobs(), POLL_MS)
    },

    async submitJob(req) {
      set({ submitting: true })
      try {
        const { id } = await api.submitJob(req)
        useStore.getState().toast(`Job ${shortId(id)} queued`)
        await get().refreshJobs()
        return true
      } catch (err) {
        useStore.getState().toast(`Generate: ${(err as Error).message}`, 'error')
        return false
      } finally {
        set({ submitting: false })
      }
    },

    async cancelJob(id) {
      try {
        const job = await api.cancelJob(id)
        set((s) => ({ jobs: s.jobs.map((j) => (j.id === id ? job : j)) }))
      } catch (err) {
        useStore.getState().toast(`Cancel: ${(err as Error).message}`, 'error')
      }
    },
  }
})

function onJobsFinished(jobs: Job[]) {
  const main = useStore.getState()
  for (const j of jobs) {
    const failed = j.failed ? ` · ${j.failed} failed` : ''
    main.toast(`Job ${shortId(j.id)} ${j.state} · ${j.done}/${j.total}${failed}`, j.state === 'done' && !j.failed ? 'info' : 'error')
  }
  // New samples exist now: refresh the list the user is looking at, the
  // dataset counts, and the inputs' done/failed status.
  if (jobs.some((j) => j.dataset === main.dataset)) void main.refreshSamples()
  void main.loadDatasets()
  void useBatch.getState().refreshInputs()
}

export function shortId(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id
}

/** Aggregate progress over active jobs, for the status bar. */
export function activeProgress(jobs: Job[]): { done: number; total: number; eta: number | null; n: number } | null {
  const act = jobs.filter(isActiveJob)
  if (!act.length) return null
  let done = 0
  let total = 0
  let eta: number | null = null
  for (const j of act) {
    done += j.done + j.failed
    total += j.total
    if (j.eta_s != null) eta = Math.max(eta ?? 0, j.eta_s)
  }
  return { done, total, eta, n: act.length }
}
