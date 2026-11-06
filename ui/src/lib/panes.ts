/**
 * Which panes a tab shows, and what each one draws. Pure, so the canvas, the
 * status bar and the stage all agree on one answer.
 */
import type { PaneSpec } from '../render/stage'
import { LAYER_BY_ID, LAYERS } from './layers'
import type { LayerId } from './types'

export type Mode = 'scan' | 'gt'

export interface PaneModel extends PaneSpec {
  /** The layer the pane is "about": drives the label pill and the stats chip. */
  primary: LayerId | null
  label: string
  color: string | null
}

interface TabLike {
  split: LayerId[] | null
  layers: Record<LayerId, { status: string }>
}

export function panesFor(
  tab: TabLike,
  layers: readonly { id: LayerId; visible: boolean }[],
  mode: Mode,
): PaneModel[] {
  if (tab.split) {
    return tab.split.map((id) => ({
      key: id,
      layers: [id],
      ghostGt: false,
      primary: id,
      label: LAYER_BY_ID[id].short,
      color: LAYER_BY_ID[id].color,
    }))
  }

  const visible = LAYERS.map((l) => l.id).filter((id) => layers.find((l) => l.id === id)?.visible)
  const scanAvailable = visible.includes('scan') && tab.layers.scan.status !== 'missing'

  if (mode === 'gt') {
    // The flip target: GT on its own (plus any point overlays), solid.
    const shown = visible.filter((id) => id !== 'scan')
    const primary: LayerId | null = shown.includes('gt') ? 'gt' : (shown[0] ?? null)
    return [single(shown, false, primary, '')]
  }

  // Scan mode: the scan solid with GT as a ghost over it -- the ghost is only
  // a ghost when there is a scan to compare against; alone, GT draws solid.
  const ghostGt = scanAvailable && visible.includes('gt')
  const primary: LayerId | null = scanAvailable ? 'scan' : (visible[0] ?? null)
  return [single(visible, ghostGt, primary, ghostGt ? ' · GT ghost' : '')]
}

function single(layers: LayerId[], ghostGt: boolean, primary: LayerId | null, suffix: string): PaneModel {
  return {
    key: 'main',
    layers,
    ghostGt,
    primary,
    label: primary ? LAYER_BY_ID[primary].short + suffix : '',
    color: primary ? LAYER_BY_ID[primary].color : null,
  }
}

/** Grid shape for n panes: prefer wider-than-tall, like FootprintUi. */
export function gridFor(n: number): { cols: number; rows: number } {
  if (n <= 1) return { cols: 1, rows: 1 }
  if (n === 2) return { cols: 2, rows: 1 }
  if (n <= 4) return { cols: 2, rows: 2 }
  if (n <= 6) return { cols: 3, rows: 2 }
  return { cols: 3, rows: 3 }
}
