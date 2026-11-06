/**
 * Deviation / coverage colouring, done in the shader.
 *
 * The scalar rides along as a vertex attribute and the colormap is a few
 * uniforms, so dragging the range slider is one uniform write per frame rather
 * than rewriting a 3M-entry colour buffer. Materials stay stock three
 * (MeshStandardMaterial / PointsMaterial) and are patched via onBeforeCompile,
 * so lighting, flat shading and transparency all keep working unchanged.
 *
 * The hex stops below are the single source of truth: the GLSL uniforms and the
 * CSS legend gradients are both derived from them.
 */
import { Color, type Material } from 'three'

/** Diverging: blue = inside the GT (negative), neutral grey ~0, red = outside. */
export const DIVERGING = { neg: '#3d7bf0', mid: '#8f939b', pos: '#eb5757' } as const

/** Sequential for coverage: grey = covered, amber -> magenta = increasingly missing. */
export const SEQUENTIAL = { lo: '#8f939b', mid: '#f0bf00', hi: '#e04bd0' } as const

/** Shared uniform objects. Every patched program points at these same objects,
 *  so one assignment re-colours every pane and every layer. */
export const heatUniforms = {
  uHeat: { value: 0 },
  uRange: { value: 0.5 },
  uNeg: { value: new Color(DIVERGING.neg) },
  uMid: { value: new Color(DIVERGING.mid) },
  uPos: { value: new Color(DIVERGING.pos) },
  uSeqLo: { value: new Color(SEQUENTIAL.lo) },
  uSeqMid: { value: new Color(SEQUENTIAL.mid) },
  uSeqHi: { value: new Color(SEQUENTIAL.hi) },
}

// Colours are interpolated in linear space (three converts the hex stops on
// construction), which is also what the legend gradients ask for.
const HEAT_GLSL = /* glsl */ `
uniform float uHeat;
uniform float uRange;
uniform vec3 uNeg;
uniform vec3 uMid;
uniform vec3 uPos;
uniform vec3 uSeqLo;
uniform vec3 uSeqMid;
uniform vec3 uSeqHi;
varying float vScalar;

vec3 ssHeat(float s) {
#ifdef SS_SEQUENTIAL
  float t = clamp(s / uRange, 0.0, 1.0);
  return t < 0.5 ? mix(uSeqLo, uSeqMid, t * 2.0) : mix(uSeqMid, uSeqHi, t * 2.0 - 1.0);
#else
  float t = clamp(s / uRange, -1.0, 1.0);
  return t < 0.0 ? mix(uMid, uNeg, -t) : mix(uMid, uPos, t);
#endif
}
`

export type HeatKind = 'diverging' | 'sequential'

/**
 * Patch a stock material to colour by the `scalar` attribute while
 * `heatUniforms.uHeat` is 1. Geometry without the attribute reads 0 from the
 * default vertex attribute, i.e. neutral -- correct for "no deviation data".
 */
export function withHeat<M extends Material>(material: M, kind: HeatKind): M {
  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, heatUniforms)
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nattribute float scalar;\nvarying float vScalar;')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\n\tvScalar = scalar;')
    shader.fragmentShader =
      (kind === 'sequential' ? '#define SS_SEQUENTIAL\n' : '') +
      shader.fragmentShader
        .replace('#include <common>', `#include <common>\n${HEAT_GLSL}`)
        .replace(
          '#include <color_fragment>',
          '#include <color_fragment>\n\tif ( uHeat > 0.5 ) diffuseColor.rgb = ssHeat( vScalar );',
        )
  }
  // Distinct cache keys, or three would hand the sequential material the
  // diverging program it compiled first.
  material.customProgramCacheKey = () => `ss-heat-${kind}`
  return material
}

/**
 * CSS gradient for the legend. The shader mixes in linear space but CSS
 * gradients interpolate in sRGB, so rather than rely on `in srgb-linear`
 * support the ramp is sampled here in linear space (three's Color stores
 * linear components) and handed to CSS as many short sRGB segments.
 */
export function legendGradient(kind: HeatKind): string {
  const [a, b, c] = (kind === 'diverging'
    ? [DIVERGING.neg, DIVERGING.mid, DIVERGING.pos]
    : [SEQUENTIAL.lo, SEQUENTIAL.mid, SEQUENTIAL.hi]
  ).map((h) => new Color(h))
  const tmp = new Color()
  const stops: string[] = []
  const N = 16
  for (let i = 0; i <= N; i++) {
    const t = i / N
    if (t < 0.5) tmp.lerpColors(a, b, t * 2)
    else tmp.lerpColors(b, c, t * 2 - 1)
    stops.push(`#${tmp.getHexString()} ${(t * 100).toFixed(1)}%`)
  }
  return `linear-gradient(to right, ${stops.join(', ')})`
}
