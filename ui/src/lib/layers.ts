import type { LayerId } from './types'

export type ScalarKind = 'deviation' | 'coverage'

export interface LayerDef {
  id: LayerId
  label: string
  /** Pane-label text; uppercase is applied by CSS. */
  short: string
  /** Swatch colour, and the base colour when the heatmap is off. */
  color: string
  primitive: 'mesh' | 'points'
  scalar: ScalarKind | null
  hint: string
}

/** Fixed by the API (see the geometry-layer table in docs/API.md), so this is
 *  a constant rather than state: order here is the 1-4 hotkey order. */
export const LAYERS: readonly LayerDef[] = [
  {
    id: 'gt',
    label: 'Ground truth',
    short: 'GT',
    color: '#5e6ad2',
    primitive: 'mesh',
    scalar: null,
    hint: 'CAD tessellation the scan was simulated from',
  },
  {
    id: 'scan',
    label: 'Scan',
    short: 'Scan',
    color: '#b3aba1',
    primitive: 'mesh',
    scalar: 'deviation',
    hint: 'Synthetic scan mesh, moved into the CAD frame · scalar = signed deviation (mm)',
  },
  {
    id: 'points',
    label: 'Raw points',
    short: 'Points',
    color: '#fc7840',
    primitive: 'points',
    scalar: 'deviation',
    hint: 'Fused raw point cloud (only when the job saved points) · scalar = signed deviation',
  },
  {
    id: 'coverage',
    label: 'Coverage',
    short: 'Coverage',
    color: '#00b8cc',
    primitive: 'points',
    scalar: 'coverage',
    hint: 'Points on the GT surface · scalar = distance to the scan (large = missing data)',
  },
]

export const LAYER_BY_ID: Record<LayerId, LayerDef> = Object.fromEntries(
  LAYERS.map((l) => [l.id, l]),
) as Record<LayerId, LayerDef>
