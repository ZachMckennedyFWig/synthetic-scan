/**
 * Wire types, transcribed from docs/API.md. Keep this file a literal mirror of
 * the contract: anything the UI derives (labels, indices, colours) lives
 * elsewhere so a contract change is a one-file diff here.
 */

export interface Health {
  ok: boolean
  version: string
  cpu_count: number
  workers: number
  open3d: boolean
  step_support: boolean
  data_dir: string
}

export interface Profile {
  id: string
  label: string
  description: string
  weight: number
}

export interface DatasetInfo {
  name: string
  n_inputs: number
  n_parts: number
  n_samples: number
  /** The contract does not pin the encoding; unix seconds or an ISO string both render. */
  created: number | string
}

export type InputStatus = 'new' | 'done' | 'failed'

export interface InputRow {
  name: string
  size: number
  format: string
  n_samples: number
  status: InputStatus
}

export interface UploadResult {
  saved: string[]
  skipped: { name: string; reason: string }[]
}

export interface JobRequest {
  dataset: string
  profile: string
  samples_per_part: number
  seed: number
  inputs?: string[]
  save_points?: boolean
}

export type JobState = 'queued' | 'running' | 'done' | 'failed' | 'cancelled'

export interface JobError {
  input: string
  sample: string | null
  error: string
}

export interface Job {
  id: string
  dataset: string
  profile: string
  state: JobState
  total: number
  done: number
  failed: number
  created: number
  started: number | null
  finished: number | null
  eta_s: number | null
  errors: JobError[]
}

export type Split = 'train' | 'val' | 'test'

export interface SampleMetrics {
  chamfer_mm: number
  hausdorff_mm: number
  rms_mm: number
  coverage: number
  n_tris: number
  watertight: boolean
  n_components: number
  n_boundary_edges: number
}

export interface SampleRow {
  id: string
  part_id: string
  part_name: string
  split: Split
  profile: string
  artifacts: string[]
  metrics: SampleMetrics
}

/**
 * A sample's meta.json. DATASET.md owns the full schema; the UI only relies on
 * `params` (a nested object of sampled parameters) and `artifacts`, and renders
 * everything else generically so new backend fields show up without UI work.
 */
export interface SampleMeta {
  params?: Record<string, unknown>
  artifacts?: unknown
  metrics?: Record<string, unknown>
  [key: string]: unknown
}

export type LayerId = 'gt' | 'scan' | 'points' | 'coverage'
