import { fmtMm } from '../lib/format'
import { useStore } from '../store/useStore'

// The colour range spans two decades (0.05 .. 5 mm), so the slider is
// logarithmic: linear steps would spend almost all of its travel above 1 mm.
const RANGE_MIN = 0.05
const RANGE_MAX = 5
const STEPS = 400
const toSlider = (mm: number) =>
  Math.round((Math.log(mm / RANGE_MIN) / Math.log(RANGE_MAX / RANGE_MIN)) * STEPS)
const fromSlider = (v: number) => {
  const mm = RANGE_MIN * (RANGE_MAX / RANGE_MIN) ** (v / STEPS)
  return Number(mm.toPrecision(2))
}

export function DisplayPanel() {
  const display = useStore((s) => s.display)
  const setDisplay = useStore((s) => s.setDisplay)

  return (
    <div className="panel-section">
      <div className="panel-head">
        <span>Display</span>
      </div>

      <div className="control">
        <label className="control-row" style={{ cursor: 'pointer' }}>
          <span className="control-label">
            Deviation heatmap <kbd>D</kbd>
          </span>
          <input type="checkbox" checked={display.heatmap} onChange={(e) => setDisplay({ heatmap: e.target.checked })} />
        </label>
      </div>

      <div className="control" data-disabled={!display.heatmap}>
        <div className="control-row">
          <span className="control-label">Colour range</span>
          <span className="control-value">±{fmtMm(display.range)}</span>
        </div>
        <input
          type="range"
          min={0}
          max={STEPS}
          step={1}
          value={toSlider(display.range)}
          onChange={(e) => setDisplay({ range: fromSlider(Number(e.target.value)) })}
          title="Applied as a shader uniform: no geometry is touched"
        />
      </div>

      <div className="control">
        <label className="control-row" style={{ cursor: 'pointer' }}>
          <span className="control-label">
            Wireframe <kbd>W</kbd>
          </span>
          <input type="checkbox" checked={display.wireframe} onChange={(e) => setDisplay({ wireframe: e.target.checked })} />
        </label>
        <div className="control-row">
          <span className="control-label">Shading</span>
          <span className="seg">
            <button data-on={display.flat} onClick={() => setDisplay({ flat: true })}>
              flat
            </button>
            <button data-on={!display.flat} onClick={() => setDisplay({ flat: false })}>
              smooth
            </button>
          </span>
        </div>
      </div>

      <div className="control">
        <div className="control-row">
          <span className="control-label">GT ghost opacity</span>
          <span className="control-value">{Math.round(display.ghostOpacity * 100)}%</span>
        </div>
        <input
          type="range"
          min={0}
          max={0.8}
          step={0.02}
          value={display.ghostOpacity}
          onChange={(e) => setDisplay({ ghostOpacity: Number(e.target.value) })}
        />
      </div>
    </div>
  )
}
