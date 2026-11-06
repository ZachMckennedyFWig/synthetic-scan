/**
 * Parser for the `SSG1` geometry format (docs/API.md).
 *
 *   offset 0   char[4]  "SSG1"
 *   offset 4   u32      n_vertices
 *   offset 8   u32      n_faces          (0 for point layers)
 *   offset 12  u32      flags            bit 0: scalar present
 *   offset 16  f32[3n]  positions
 *              u32[3f]  triangle indices
 *              f32[n]   scalar, if flag bit 0
 *
 * Every section is 4-byte aligned by construction, so on a little-endian host
 * the arrays are zero-copy views into the response buffer -- a 3M-triangle scan
 * is ~70 MB and copying it would double peak memory for no benefit.
 */

export interface Ssg1 {
  nVertices: number
  nFaces: number
  positions: Float32Array
  /** null for point layers. */
  index: Uint32Array | null
  scalar: Float32Array | null
}

const HEADER_BYTES = 16
const FLAG_SCALAR = 1

const LITTLE_ENDIAN_HOST = new Uint8Array(new Uint16Array([1]).buffer)[0] === 1

export class Ssg1Error extends Error {}

export function parseSsg1(buf: ArrayBuffer): Ssg1 {
  if (buf.byteLength < HEADER_BYTES) throw new Ssg1Error(`SSG1: ${buf.byteLength} bytes is shorter than the header`)

  const dv = new DataView(buf)
  const magic = String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3))
  if (magic !== 'SSG1') throw new Ssg1Error(`SSG1: bad magic "${magic}"`)

  const nVertices = dv.getUint32(4, true)
  const nFaces = dv.getUint32(8, true)
  const flags = dv.getUint32(12, true)
  const hasScalar = (flags & FLAG_SCALAR) !== 0

  const posOff = HEADER_BYTES
  const idxOff = posOff + nVertices * 12
  const scalarOff = idxOff + nFaces * 12
  const end = scalarOff + (hasScalar ? nVertices * 4 : 0)
  if (buf.byteLength < end) {
    throw new Ssg1Error(`SSG1: truncated (${buf.byteLength} bytes, header promises ${end})`)
  }

  return {
    nVertices,
    nFaces,
    positions: f32(buf, dv, posOff, nVertices * 3),
    index: nFaces > 0 ? u32(buf, dv, idxOff, nFaces * 3) : null,
    scalar: hasScalar ? f32(buf, dv, scalarOff, nVertices) : null,
  }
}

// Big-endian hosts are effectively extinct in browsers, but a silent garbage
// mesh is a worse failure than a slow copy, so fall back rather than assume.
function f32(buf: ArrayBuffer, dv: DataView, offset: number, length: number): Float32Array {
  if (LITTLE_ENDIAN_HOST) return new Float32Array(buf, offset, length)
  const out = new Float32Array(length)
  for (let i = 0; i < length; i++) out[i] = dv.getFloat32(offset + i * 4, true)
  return out
}

function u32(buf: ArrayBuffer, dv: DataView, offset: number, length: number): Uint32Array {
  if (LITTLE_ENDIAN_HOST) return new Uint32Array(buf, offset, length)
  const out = new Uint32Array(length)
  for (let i = 0; i < length; i++) out[i] = dv.getUint32(offset + i * 4, true)
  return out
}
