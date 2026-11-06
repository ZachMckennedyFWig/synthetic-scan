/**
 * The small slice of UI state that survives a reload: which dataset, which
 * tabs, layer visibility, display options, list sort. Everything else is
 * re-derived from the backend.
 */
import type { DisplayOptions } from '../render/stage'
import type { LayerId } from '../lib/types'

const KEY = 'scan-lab.prefs.v1'

export type SortKey = 'name' | 'chamfer' | 'hausdorff' | 'coverage'

export interface Prefs {
  dataset?: string | null
  tabs?: { dataset: string; sampleId: string }[]
  activeTabId?: string | null
  layers?: { id: LayerId; visible: boolean }[]
  display?: Partial<DisplayOptions>
  sort?: SortKey
  sortDesc?: boolean
}

export function loadPrefs(): Prefs {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as Prefs) : {}
  } catch {
    return {}
  }
}

export function savePrefs(p: Prefs): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(p))
  } catch {
    /* private window or storage disabled -- the app still works, it just forgets */
  }
}
