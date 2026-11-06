import { create } from 'zustand'
import { api } from '../lib/api'
import { LAYERS } from '../lib/layers'
import type { Mode } from '../lib/panes'
import type { DatasetInfo, Health, LayerId, SampleMeta, SampleRow } from '../lib/types'
import { geometryCache, sampleKey, StaleLoadError, type LayerInfo } from '../render/geometryCache'
import type { DisplayOptions } from '../render/stage'
import { viewportController } from '../render/viewportController'
import { loadPrefs, type SortKey } from './prefs'

export type ViewName = 'viewer' | 'batch'

export interface LayerState {
  status: 'idle' | 'loading' | 'ready' | 'missing' | 'error'
  info?: LayerInfo
  error?: string
}

export interface Tab {
  /** `${dataset}/${sampleId}` -- also the geometry-cache and camera key. */
  id: string
  dataset: string
  sampleId: string
  name: string
  row: SampleRow | null
  meta: SampleMeta | null
  metaError: string | null
  layers: Record<LayerId, LayerState>
  /** Layer per pane while in split screen; null = single pane. */
  split: LayerId[] | null
}

export interface LayerConfig {
  id: LayerId
  visible: boolean
}

interface Toast {
  id: number
  text: string
  kind: 'info' | 'error'
}

interface Store {
  online: boolean
  /** False until the first health check has answered either way. */
  checked: boolean
  health: Health | null

  datasets: DatasetInfo[]
  dataset: string | null
  samples: SampleRow[]
  /** 1-based index of each sample among its part's samples, for tab names. */
  sampleIndex: Record<string, number>
  samplesLoading: boolean
  samplesError: string | null
  filter: string
  sort: SortKey
  sortDesc: boolean

  view: ViewName
  tabs: Tab[]
  activeTabId: string | null

  /** Global on purpose, like FootprintUi: every tab and pane renders comparably. */
  layers: LayerConfig[]
  selection: LayerId[]
  mode: Mode
  display: DisplayOptions

  busy: number
  toasts: Toast[]
  /** Bumped by "+" so the dataset panel can focus its filter. */
  browseNonce: number

  setHealth: (h: Health | null) => void
  toast: (text: string, kind?: 'info' | 'error') => void

  loadDatasets: () => Promise<void>
  selectDataset: (name: string | null) => void
  createDataset: (name: string) => Promise<boolean>
  refreshSamples: () => Promise<void>
  setFilter: (f: string) => void
  setSort: (key: SortKey, desc?: boolean) => void

  setView: (v: ViewName) => void
  requestBrowse: () => void
  openSample: (row: SampleRow, activate?: boolean) => void
  closeTab: (tabId: string) => void
  setActiveTab: (tabId: string) => void

  ensureLayer: (tabId: string, layer: LayerId) => Promise<void>
  ensureVisible: (tabId: string) => void

  setLayerVisible: (id: LayerId, visible: boolean) => void
  toggleLayer: (id: LayerId) => void
  isolateLayer: (id: LayerId) => void
  soloOrRestore: (id: LayerId) => void
  select: (id: LayerId, additive: boolean) => void
  clearSelection: () => void

  enterSplit: (ids: LayerId[]) => void
  exitSplit: () => void
  toggleGtScanSplit: () => void

  toggleMode: () => void
  setDisplay: (patch: Partial<DisplayOptions>) => void
}

const prefs = loadPrefs()

const DEFAULT_DISPLAY: DisplayOptions = {
  heatmap: false,
  range: 0.5,
  wireframe: false,
  flat: true, // CAD tessellations share vertices across sharp edges; smooth normals smear them
  ghostOpacity: 0.22,
}

const DEFAULT_LAYERS: LayerConfig[] = LAYERS.map((l) => ({
  id: l.id,
  visible: l.id === 'gt' || l.id === 'scan',
}))

function restoredLayers(): LayerConfig[] {
  const saved = new Map((prefs.layers ?? []).map((l) => [l.id, l.visible]))
  return DEFAULT_LAYERS.map((l) => ({ ...l, visible: saved.get(l.id) ?? l.visible }))
}

function emptyLayers(): Record<LayerId, LayerState> {
  return { gt: { status: 'idle' }, scan: { status: 'idle' }, points: { status: 'idle' }, coverage: { status: 'idle' } }
}

function indexSamples(rows: SampleRow[]): Record<string, number> {
  const byPart = new Map<string, SampleRow[]>()
  for (const r of rows) {
    const list = byPart.get(r.part_id)
    if (list) list.push(r)
    else byPart.set(r.part_id, [r])
  }
  const out: Record<string, number> = {}
  for (const list of byPart.values()) {
    list.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
    list.forEach((r, i) => (out[r.id] = i + 1))
  }
  return out
}

export function sampleLabel(row: Pick<SampleRow, 'id' | 'part_name'>, index: Record<string, number>): string {
  const i = index[row.id]
  return i ? `${row.part_name} #${i}` : row.part_name || row.id
}

let toastSeq = 0
/** Tabs from the last session, reopened once their dataset's samples arrive. */
let pendingRestore = prefs.tabs ?? []

/** Saved tabs not yet reopened (their dataset has not loaded). Persisted
 *  alongside the open ones so an offline start does not forget them. */
export function pendingRestoreTabs(): { dataset: string; sampleId: string }[] {
  return pendingRestore
}

export const useStore = create<Store>((set, get) => {
  /** Patch one tab by id; a no-op if it has been closed meanwhile. */
  const patchTab = (tabId: string, fn: (t: Tab) => Partial<Tab>) =>
    set((s) => ({ tabs: s.tabs.map((t) => (t.id === tabId ? { ...t, ...fn(t) } : t)) }))

  const patchLayer = (tabId: string, layer: LayerId, st: LayerState) =>
    patchTab(tabId, (t) => ({ layers: { ...t.layers, [layer]: st } }))

  const loadMeta = async (tabId: string) => {
    const tab = get().tabs.find((t) => t.id === tabId)
    if (!tab) return
    try {
      const meta = await api.sampleMeta(tab.dataset, tab.sampleId)
      patchTab(tabId, () => ({ meta, metaError: null }))
    } catch (err) {
      patchTab(tabId, () => ({ metaError: (err as Error).message }))
    }
  }

  return {
    online: false,
    checked: false,
    health: null,

    datasets: [],
    dataset: prefs.dataset ?? null,
    samples: [],
    sampleIndex: {},
    samplesLoading: false,
    samplesError: null,
    filter: '',
    sort: prefs.sort ?? 'name',
    sortDesc: prefs.sortDesc ?? false,

    view: 'viewer',
    tabs: [],
    activeTabId: null,

    layers: restoredLayers(),
    selection: [],
    mode: 'scan',
    display: { ...DEFAULT_DISPLAY, ...prefs.display },

    busy: 0,
    toasts: [],
    browseNonce: 0,

    setHealth(h) {
      // Keep the last good health while offline so the status bar can still say
      // what it was talking to.
      set({ health: h ?? get().health, online: h !== null, checked: true })
    },

    toast(text, kind = 'info') {
      const id = ++toastSeq
      set((s) => ({ toasts: [...s.toasts.slice(-3), { id, text, kind }] }))
      setTimeout(() => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })), kind === 'error' ? 6000 : 4000)
    },

    async loadDatasets() {
      try {
        const datasets = await api.datasets()
        set({ datasets })
        const current = get().dataset
        if (!current || !datasets.some((d) => d.name === current)) {
          get().selectDataset(datasets[0]?.name ?? null)
        } else if (!get().samples.length) {
          void get().refreshSamples()
        }
      } catch (err) {
        get().toast(`Datasets: ${(err as Error).message}`, 'error')
      }
    },

    selectDataset(name) {
      if (name === get().dataset && get().samples.length) return
      set({ dataset: name, samples: [], sampleIndex: {}, samplesError: null })
      if (name) void get().refreshSamples()
    },

    async createDataset(name) {
      const clean = name.trim()
      if (!clean) return false
      try {
        const res = await api.createDataset(clean)
        await get().loadDatasets()
        get().selectDataset(res.name)
        get().toast(`Created dataset ${res.name}`)
        return true
      } catch (err) {
        get().toast(`Create dataset: ${(err as Error).message}`, 'error')
        return false
      }
    },

    async refreshSamples() {
      const ds = get().dataset
      if (!ds) return
      set({ samplesLoading: true })
      try {
        const samples = await api.samples(ds)
        if (get().dataset !== ds) return // switched away while loading
        const sampleIndex = indexSamples(samples)
        const byId = new Map(samples.map((r) => [r.id, r]))
        set((s) => ({
          samples,
          sampleIndex,
          samplesError: null,
          // Re-label open tabs: a regenerated dataset can renumber or update metrics.
          tabs: s.tabs.map((t) => {
            const row = t.dataset === ds ? byId.get(t.sampleId) : undefined
            return row ? { ...t, row, name: sampleLabel(row, sampleIndex) } : t
          }),
        }))

        const restore = pendingRestore.filter((p) => p.dataset === ds)
        if (restore.length) {
          pendingRestore = pendingRestore.filter((p) => p.dataset !== ds)
          // Re-add the tabs without activating each one -- activation fetches
          // geometry, and only the tab you were looking at needs it now.
          for (const p of restore) {
            const row = byId.get(p.sampleId)
            if (row) get().openSample(row, false)
          }
          const tabs = get().tabs
          const active = tabs.find((t) => t.id === prefs.activeTabId) ?? tabs[0]
          if (active && !get().activeTabId) get().setActiveTab(active.id)
        }
      } catch (err) {
        if (get().dataset === ds) set({ samplesError: (err as Error).message })
      } finally {
        set({ samplesLoading: false })
      }
    },

    setFilter(filter) {
      set({ filter })
    },

    setSort(sort, desc) {
      set((s) => ({ sort, sortDesc: desc ?? (s.sort === sort ? !s.sortDesc : sort !== 'name' && sort !== 'coverage') }))
    },

    setView(view) {
      set({ view })
    },

    requestBrowse() {
      set((s) => ({ view: 'viewer', browseNonce: s.browseNonce + 1 }))
    },

    openSample(row, activate = true) {
      const ds = get().dataset
      if (!ds) return
      const id = sampleKey(ds, row.id)
      if (!get().tabs.some((t) => t.id === id)) {
        const tab: Tab = {
          id,
          dataset: ds,
          sampleId: row.id,
          name: sampleLabel(row, get().sampleIndex),
          row,
          meta: null,
          metaError: null,
          layers: emptyLayers(),
          split: null,
        }
        set((s) => ({ tabs: [...s.tabs, tab] }))
        void loadMeta(id)
      }
      if (activate) get().setActiveTab(id)
    },

    closeTab(tabId) {
      // Free the GPU + heap copy now rather than waiting for LRU pressure: a
      // closed tab is the clearest "not needed" signal there is.
      geometryCache.evict(tabId)
      viewportController.forget(tabId)
      const { tabs, activeTabId } = get()
      const i = tabs.findIndex((t) => t.id === tabId)
      const rest = tabs.filter((t) => t.id !== tabId)
      const next = activeTabId === tabId ? (rest[Math.min(i, rest.length - 1)]?.id ?? null) : activeTabId
      set({ tabs: rest, activeTabId: next })
      if (next && next !== activeTabId) get().setActiveTab(next)
    },

    setActiveTab(tabId) {
      set({ activeTabId: tabId, view: 'viewer' })
      geometryCache.touch(tabId)
      get().ensureVisible(tabId)
    },

    async ensureLayer(tabId, layer) {
      const tab = get().tabs.find((t) => t.id === tabId)
      if (!tab || !get().online) return
      const st = tab.layers[layer]
      if (st.status === 'loading' || st.status === 'missing') return
      // "ready" can be stale: the LRU may have evicted this sample while its
      // tab sat in the background.
      if (st.status === 'ready' && geometryCache.has(tabId, layer)) return

      patchLayer(tabId, layer, { status: 'loading' })
      set((s) => ({ busy: s.busy + 1 }))
      try {
        const info = await geometryCache.load(tab.dataset, tab.sampleId, layer)
        patchLayer(tabId, layer, info ? { status: 'ready', info } : { status: 'missing' })
      } catch (err) {
        if (err instanceof StaleLoadError) patchLayer(tabId, layer, { status: 'idle' })
        else {
          patchLayer(tabId, layer, { status: 'error', error: (err as Error).message })
          get().toast(`${tab.name} / ${layer}: ${(err as Error).message}`, 'error')
        }
      } finally {
        set((s) => ({ busy: Math.max(0, s.busy - 1) }))
      }
    },

    ensureVisible(tabId) {
      const tab = get().tabs.find((t) => t.id === tabId)
      if (!tab) return
      const wanted = new Set<LayerId>(tab.split ?? [])
      for (const l of get().layers) if (l.visible) wanted.add(l.id)
      for (const id of wanted) void get().ensureLayer(tabId, id)
    },

    setLayerVisible(id, visible) {
      set((s) => ({ layers: s.layers.map((l) => (l.id === id ? { ...l, visible } : l)) }))
      const tabId = get().activeTabId
      if (visible && tabId) void get().ensureLayer(tabId, id)
    },

    toggleLayer(id) {
      const layer = get().layers.find((l) => l.id === id)
      get().setLayerVisible(id, !layer?.visible)
    },

    isolateLayer(id) {
      set((s) => ({ layers: s.layers.map((l) => ({ ...l, visible: l.id === id })) }))
      const tabId = get().activeTabId
      if (tabId) void get().ensureLayer(tabId, id)
    },

    /** Shift-click: isolate, or restore the defaults if already isolated. */
    soloOrRestore(id) {
      const visible = get().layers.filter((l) => l.visible).map((l) => l.id)
      if (visible.length === 1 && visible[0] === id) {
        set({ layers: DEFAULT_LAYERS.map((l) => ({ ...l, visible: l.visible || l.id === id })) })
        const tabId = get().activeTabId
        if (tabId) get().ensureVisible(tabId)
      } else {
        get().isolateLayer(id)
      }
    },

    select(id, additive) {
      set((s) => {
        if (!additive) return { selection: [id] }
        return {
          selection: s.selection.includes(id) ? s.selection.filter((x) => x !== id) : [...s.selection, id],
        }
      })
    },

    clearSelection() {
      set({ selection: [] })
    },

    enterSplit(ids) {
      const tabId = get().activeTabId
      if (!tabId || ids.length < 1) return
      // A split pane showing a hidden layer would be an empty box; switching
      // them on is what the user evidently wants.
      set((s) => ({
        layers: s.layers.map((l) => (ids.includes(l.id) ? { ...l, visible: true } : l)),
        tabs: s.tabs.map((t) => (t.id === tabId ? { ...t, split: [...ids] } : t)),
      }))
      get().ensureVisible(tabId)
    },

    exitSplit() {
      const tabId = get().activeTabId
      if (tabId) patchTab(tabId, () => ({ split: null }))
    },

    toggleGtScanSplit() {
      const tab = get().tabs.find((t) => t.id === get().activeTabId)
      if (!tab) return
      if (tab.split) get().exitSplit()
      else get().enterSplit(['gt', 'scan'])
    },

    toggleMode() {
      set((s) => ({ mode: s.mode === 'scan' ? 'gt' : 'scan' }))
    },

    setDisplay(patch) {
      set((s) => ({ display: { ...s.display, ...patch } }))
    },
  }
})

export function useActiveTab(): Tab | null {
  return useStore((s) => s.tabs.find((t) => t.id === s.activeTabId) ?? null)
}

// Dev-only handle for poking at state from the console.
if (import.meta.env.DEV) {
  ;(window as unknown as { __store: typeof useStore }).__store = useStore
}
