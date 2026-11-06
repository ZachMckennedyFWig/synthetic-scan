/**
 * App lifecycle: watch the backend, (re)load everything when it appears, and
 * persist prefs. Lives outside both stores so neither has to import the other
 * in both directions.
 *
 * The backend is allowed to be down -- you may be building the UI while the
 * Python side is still being written. The health loop keeps knocking, and the
 * moment it answers the app bootstraps itself; no reload needed.
 */
import { api } from '../lib/api'
import { savePrefs } from './prefs'
import { useBatch } from './useBatch'
import { pendingRestoreTabs, useStore } from './useStore'

const ONLINE_POLL_MS = 5000
const OFFLINE_POLL_MS = 2000

export function startApp(): () => void {
  let stopped = false
  let timer: number | undefined
  let wasOnline = false

  async function check() {
    let health = null
    try {
      health = await api.health()
    } catch {
      health = null
    }
    if (stopped) return
    useStore.getState().setHealth(health)
    const online = health !== null
    if (online && !wasOnline) bootstrap()
    wasOnline = online
    timer = window.setTimeout(() => void check(), online ? ONLINE_POLL_MS : OFFLINE_POLL_MS)
  }

  function bootstrap() {
    const s = useStore.getState()
    void s.loadDatasets()
    void useBatch.getState().loadProfiles()
    void useBatch.getState().refreshJobs()
    void useBatch.getState().refreshInputs()
    // Layers that were requested while offline stayed idle; fetch them now.
    if (s.activeTabId) s.ensureVisible(s.activeTabId)
  }

  // Inputs belong to the selected dataset.
  const unsubDataset = useStore.subscribe((s, prev) => {
    if (s.dataset !== prev.dataset) void useBatch.getState().refreshInputs()
  })

  // Persist the small set of prefs, debounced: sliders fire per pixel.
  let saveTimer: number | undefined
  const unsubPrefs = useStore.subscribe((s, prev) => {
    if (
      s.dataset === prev.dataset &&
      s.tabs === prev.tabs &&
      s.activeTabId === prev.activeTabId &&
      s.layers === prev.layers &&
      s.display === prev.display &&
      s.sort === prev.sort &&
      s.sortDesc === prev.sortDesc
    ) {
      return
    }
    window.clearTimeout(saveTimer)
    saveTimer = window.setTimeout(() => {
      const st = useStore.getState()
      savePrefs({
        dataset: st.dataset,
        tabs: [
          ...st.tabs.map((t) => ({ dataset: t.dataset, sampleId: t.sampleId })),
          ...pendingRestoreTabs().filter((p) => !st.tabs.some((t) => t.dataset === p.dataset && t.sampleId === p.sampleId)),
        ],
        activeTabId: st.activeTabId,
        layers: st.layers,
        display: st.display,
        sort: st.sort,
        sortDesc: st.sortDesc,
      })
    }, 300)
  })

  void check()

  return () => {
    stopped = true
    window.clearTimeout(timer)
    window.clearTimeout(saveTimer)
    unsubDataset()
    unsubPrefs()
  }
}
