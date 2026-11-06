import { fmtCount } from '../lib/format'
import { isActiveJob, useBatch } from '../store/useBatch'
import { useStore } from '../store/useStore'
import { BatchIcon, CloseIcon, SplitIcon } from './icons'

export function TabBar() {
  const tabs = useStore((s) => s.tabs)
  const activeTabId = useStore((s) => s.activeTabId)
  const view = useStore((s) => s.view)
  const setActiveTab = useStore((s) => s.setActiveTab)
  const setView = useStore((s) => s.setView)
  const closeTab = useStore((s) => s.closeTab)
  const requestBrowse = useStore((s) => s.requestBrowse)
  const runningJobs = useBatch((s) => s.jobs.filter(isActiveJob).length)

  return (
    <div className="tabbar" role="tablist">
      {/* Pinned left: the batch page swaps out the canvas, not the workspace. */}
      <div
        className="tab tab-pinned"
        role="tab"
        aria-selected={view === 'batch'}
        data-active={view === 'batch'}
        onClick={() => setView(view === 'batch' && activeTabId ? 'viewer' : 'batch')}
        title="Upload parts and run generation jobs"
      >
        <BatchIcon />
        <span className="tab-name">Batch</span>
        {runningJobs > 0 && <span className="tab-count">{runningJobs}</span>}
      </div>
      <span className="tab-divider" />

      {tabs.map((tab) => {
        const active = view === 'viewer' && tab.id === activeTabId
        return (
          <div
            key={tab.id}
            className="tab"
            role="tab"
            aria-selected={active}
            data-active={active}
            onClick={() => setActiveTab(tab.id)}
            onAuxClick={(e) => e.button === 1 && closeTab(tab.id)}
            title={`${tab.name}\n${tab.dataset} / ${tab.sampleId}`}
          >
            {tab.split && <SplitIcon />}
            <span className="tab-name">{tab.name}</span>
            <span className="tab-dims mono">
              {tab.row ? `${fmtCount(tab.row.metrics.n_tris)} tris` : ''}
            </span>
            <button
              className="tab-close"
              onClick={(e) => {
                e.stopPropagation()
                closeTab(tab.id)
              }}
              aria-label={`Close ${tab.name}`}
            >
              <CloseIcon />
            </button>
          </div>
        )
      })}

      <button className="tab-add" onClick={requestBrowse} title="Open a sample from the dataset browser">
        +
      </button>
    </div>
  )
}
