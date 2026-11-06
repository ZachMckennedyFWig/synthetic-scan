/** Display formatting. Everything here is mono-font friendly: fixed-ish widths. */

export function fmtCount(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—'
  if (n >= 1e6) return `${(n / 1e6).toFixed(n >= 1e7 ? 1 : 2)}M`
  if (n >= 1e4) return `${(n / 1e3).toFixed(n >= 1e5 ? 0 : 1)}k`
  return n.toLocaleString()
}

/** Millimetres with enough precision for sub-0.01 mm deviations. */
export function fmtMm(n: number | null | undefined, unit = true): string {
  if (n == null || !Number.isFinite(n)) return '—'
  const a = Math.abs(n)
  const s = a === 0 ? '0' : a < 0.01 ? n.toPrecision(2) : a < 10 ? n.toFixed(3) : n.toFixed(1)
  return unit ? `${s} mm` : s
}

export function fmtPct(f: number | null | undefined, digits = 1): string {
  if (f == null || !Number.isFinite(f)) return '—'
  return `${(f * 100).toFixed(digits)}%`
}

export function fmtBytes(b: number | null | undefined): string {
  if (b == null || !Number.isFinite(b)) return '—'
  if (b < 1024) return `${b} B`
  if (b < 1024 ** 2) return `${(b / 1024).toFixed(1)} KB`
  if (b < 1024 ** 3) return `${(b / 1024 ** 2).toFixed(1)} MB`
  return `${(b / 1024 ** 3).toFixed(2)} GB`
}

export function fmtEta(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s)) return '—'
  if (s < 60) return `${Math.max(0, Math.round(s))}s`
  if (s < 3600) return `${Math.round(s / 60)}m`
  const h = Math.floor(s / 3600)
  const m = Math.round((s % 3600) / 60)
  return `${h}h ${String(m).padStart(2, '0')}m`
}

export function fmtClock(unix: number | null | undefined): string {
  if (unix == null) return '—'
  return new Date(unix * 1000).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

export function fmtDate(v: number | string | null | undefined): string {
  if (v == null) return '—'
  const d = typeof v === 'number' ? new Date(v * 1000) : new Date(v)
  return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleDateString()
}

/** Generic scalar for the parameter inspector: ints stay ints, floats get 4 s.f. */
export function fmtValue(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) return String(v)
    if (Number.isInteger(v)) return String(v)
    const a = Math.abs(v)
    return a !== 0 && (a < 1e-3 || a >= 1e6) ? v.toExponential(3) : String(Number(v.toPrecision(4)))
  }
  if (typeof v === 'string') return v
  return JSON.stringify(v)
}
