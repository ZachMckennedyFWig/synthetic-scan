/**
 * Fetched layer geometry, keyed per sample, with an LRU over samples.
 *
 * Geometry deliberately lives here and not in zustand: a 3M-triangle scan is
 * ~70 MB of typed arrays and React state is the wrong home for that (devtools
 * serialisation, accidental structural copies). The store holds only the small
 * per-layer status/counts; the stage reads BufferGeometry from here directly.
 *
 * The LRU is per *sample*, not per layer, because the layers of a sample are
 * only ever viewed together. Closing a tab evicts its sample immediately;
 * otherwise the least recently activated sample goes once more than
 * MAX_SAMPLES are held, which bounds GPU + heap memory to a few big scans.
 */
import { BufferAttribute, BufferGeometry, Sphere } from 'three'
import { api } from '../lib/api'
import { parseSsg1 } from '../lib/ssg1'
import type { LayerId } from '../lib/types'

export const MAX_SAMPLES = 6

export interface LayerGeometry {
  geometry: BufferGeometry
  nVertices: number
  nFaces: number
  hasScalar: boolean
  sphere: Sphere
}

/** What the store keeps about a loaded layer. */
export interface LayerInfo {
  nVertices: number
  nFaces: number
  hasScalar: boolean
}

export class StaleLoadError extends Error {
  constructor() {
    super('sample evicted while loading')
  }
}

type EvictListener = (sampleKey: string) => void

interface SampleEntry {
  layers: Map<LayerId, LayerGeometry>
  inflight: Map<LayerId, Promise<LayerInfo | null>>
  abort: AbortController
}

export function sampleKey(dataset: string, sampleId: string): string {
  return `${dataset}/${sampleId}`
}

function toGeometry(buf: ArrayBuffer): LayerGeometry {
  const s = parseSsg1(buf)
  const geometry = new BufferGeometry()
  geometry.setAttribute('position', new BufferAttribute(s.positions, 3))
  if (s.index) geometry.setIndex(new BufferAttribute(s.index, 1))
  if (s.scalar) geometry.setAttribute('scalar', new BufferAttribute(s.scalar, 1))
  // Bounds once, up front: three would otherwise compute them lazily inside the
  // first frustum-cull, i.e. as a hitch in the middle of a frame.
  geometry.computeBoundingBox()
  geometry.computeBoundingSphere()
  return {
    geometry,
    nVertices: s.nVertices,
    nFaces: s.nFaces,
    hasScalar: Boolean(s.scalar),
    sphere: geometry.boundingSphere!.clone(),
  }
}

class GeometryCache {
  /** Map iteration order doubles as LRU order: oldest first. */
  private samples = new Map<string, SampleEntry>()
  private listeners = new Set<EvictListener>()

  private entry(key: string): SampleEntry {
    let e = this.samples.get(key)
    if (!e) {
      e = { layers: new Map(), inflight: new Map(), abort: new AbortController() }
      this.samples.set(key, e)
    }
    return e
  }

  peek(key: string, layer: LayerId): LayerGeometry | undefined {
    return this.samples.get(key)?.layers.get(layer)
  }

  has(key: string, layer: LayerId): boolean {
    return Boolean(this.samples.get(key)?.layers.has(layer))
  }

  /** Mark a sample most-recently-used and trim the tail. */
  touch(key: string): void {
    const e = this.samples.get(key)
    if (e) {
      this.samples.delete(key)
      this.samples.set(key, e)
    }
    this.trim(key)
  }

  /**
   * Fetch + parse one layer. Resolves to null if the sample has no such layer
   * (a 404 is an answer, not an error: `points` only exists when the job saved
   * them). Concurrent calls share one request.
   */
  load(dataset: string, sampleId: string, layer: LayerId): Promise<LayerInfo | null> {
    const key = sampleKey(dataset, sampleId)
    const e = this.entry(key)
    const ready = e.layers.get(layer)
    if (ready) return Promise.resolve(infoOf(ready))
    const pending = e.inflight.get(layer)
    if (pending) return pending

    const p = (async () => {
      try {
        const buf = await api.geometry(dataset, sampleId, layer, e.abort.signal)
        // Evicted (tab closed / LRU) while the bytes were in flight: drop them
        // rather than resurrect an entry nobody is looking at.
        if (this.samples.get(key) !== e) throw new StaleLoadError()
        if (!buf) return null
        const g = toGeometry(buf)
        e.layers.set(layer, g)
        return infoOf(g)
      } catch (err) {
        if ((err as Error).name === 'AbortError') throw new StaleLoadError()
        throw err
      } finally {
        e.inflight.delete(layer)
      }
    })()
    e.inflight.set(layer, p)
    this.touch(key)
    return p
  }

  evict(key: string): void {
    const e = this.samples.get(key)
    if (!e) return
    this.samples.delete(key)
    e.abort.abort()
    // Listeners first: the stage must drop its meshes before the buffers go,
    // or a frame in between would re-upload a disposed geometry.
    for (const fn of this.listeners) fn(key)
    for (const g of e.layers.values()) g.geometry.dispose()
  }

  onEvict(fn: EvictListener): () => void {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }

  private trim(keep: string): void {
    for (const key of this.samples.keys()) {
      if (this.samples.size <= MAX_SAMPLES) return
      if (key !== keep) this.evict(key)
    }
  }
}

function infoOf(g: LayerGeometry): LayerInfo {
  return { nVertices: g.nVertices, nFaces: g.nFaces, hasScalar: g.hasScalar }
}

export const geometryCache = new GeometryCache()
