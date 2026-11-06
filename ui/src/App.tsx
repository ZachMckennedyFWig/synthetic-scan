import { useEffect } from 'react'
import { BatchPage } from './components/batch/BatchPage'
import { CanvasArea } from './components/CanvasArea'
import { DatasetPanel } from './components/DatasetPanel'
import { DisplayPanel } from './components/DisplayPanel'
import { Inspector } from './components/Inspector'
import { LayerPanel } from './components/LayerPanel'
import { StatusBar, Toasts } from './components/StatusBar'
import { TabBar } from './components/TabBar'
import { LAYERS } from './lib/layers'
import { stage } from './render/stage'
import { startApp } from './store/boot'
import { useStore } from './store/useStore'

export default function App() {
  const view = useStore((s) => s.view)

  useEffect(() => startApp(), [])
  useKeyboard()

  return (
    <div className="app">
      <TabBar />
      <CanvasArea hidden={view === 'batch'} />
      {view === 'batch' && <BatchPage />}
      <aside className="panel">
        <DatasetPanel />
        <LayerPanel />
        <DisplayPanel />
        <Inspector />
      </aside>
      <StatusBar />
      <Toasts />
    </div>
  )
}

function useKeyboard() {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement
      // Never steal keys from a control the user is actually operating.
      if (target.matches('input, textarea, select') || target.isContentEditable) return
      if (e.ctrlKey || e.metaKey) return // leave browser shortcuts alone

      const s = useStore.getState()
      const tab = s.tabs.find((t) => t.id === s.activeTabId)

      if (e.key === 'Tab') {
        if (!s.tabs.length) return
        e.preventDefault()
        const i = s.tabs.findIndex((t) => t.id === s.activeTabId)
        const next = (i + (e.shiftKey ? -1 : 1) + s.tabs.length) % s.tabs.length
        s.setActiveTab(s.tabs[next].id)
        return
      }
      // The rest are viewer gestures; on the Batch page they would act unseen.
      if (s.view !== 'viewer') return

      switch (e.key) {
        case ' ': {
          // The headline gesture: flip the pane between the scan (with its GT
          // ghost) and the ground truth, in place, same camera.
          e.preventDefault()
          s.toggleMode()
          return
        }
        case 'Escape': {
          if (tab?.split) s.exitSplit()
          else s.clearSelection()
          return
        }
        case 's':
        case 'S':
          s.toggleGtScanSplit()
          return
        case 'd':
        case 'D':
          s.setDisplay({ heatmap: !s.display.heatmap })
          return
        case 'w':
        case 'W':
          s.setDisplay({ wireframe: !s.display.wireframe })
          return
        case 'f':
        case 'F':
          stage.fit()
          return
        case 'Enter':
          if (s.selection.length >= 2) s.enterSplit(s.selection)
          return
      }

      // 1-9 toggle the nth layer; with Alt, isolate it instead. `e.code` so
      // Alt+digit still reads as a digit on layouts where Alt changes the key.
      const m = /^Digit([1-9])$/.exec(e.code)
      if (m) {
        const layer = LAYERS[Number(m[1]) - 1]
        if (!layer) return
        e.preventDefault()
        if (e.altKey) s.isolateLayer(layer.id)
        else s.toggleLayer(layer.id)
      }
    }

    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
}
