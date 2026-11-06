/** Inline icons, drawn on a 16-unit grid to match FootprintUi's set. */

export function EyeIcon({ on }: { on: boolean }) {
  return on ? (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path d="M1.5 8S3.9 3.5 8 3.5 14.5 8 14.5 8 12.1 12.5 8 12.5 1.5 8 1.5 8Z" stroke="currentColor" strokeWidth="1.3" />
      <circle cx="8" cy="8" r="2.1" stroke="currentColor" strokeWidth="1.3" />
    </svg>
  ) : (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden>
      <path
        d="M2.6 3.2 13.4 12.8M4.6 4.9C2.8 6.1 1.5 8 1.5 8S3.9 12.5 8 12.5c1.2 0 2.2-.3 3.1-.8M6.6 4c.45-.1.92-.15 1.4-.15C12.1 3.85 14.5 8 14.5 8s-.7 1.3-1.9 2.4"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
      />
    </svg>
  )
}

export function SplitIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 12 12" aria-label="split screen">
      <rect x="0.5" y="0.5" width="4.5" height="11" fill="none" stroke="currentColor" />
      <rect x="7" y="0.5" width="4.5" height="11" fill="none" stroke="currentColor" />
    </svg>
  )
}

export function CloseIcon() {
  return (
    <svg width="9" height="9" viewBox="0 0 10 10" aria-hidden>
      <path d="M1 1l8 8M9 1l-8 8" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  )
}

export function BatchIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden>
      <rect x="1.5" y="1.5" width="5.5" height="5.5" rx="1" stroke="currentColor" strokeWidth="1.3" />
      <rect x="9" y="1.5" width="5.5" height="5.5" rx="1" stroke="currentColor" strokeWidth="1.3" />
      <rect x="1.5" y="9" width="5.5" height="5.5" rx="1" stroke="currentColor" strokeWidth="1.3" />
      <path d="M11.75 9.5v4.5M9.5 11.75H14" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  )
}

export function RefreshIcon({ spinning }: { spinning?: boolean }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 16 16"
      fill="none"
      aria-label="Refresh"
      style={spinning ? { animation: 'spin 0.9s linear infinite' } : undefined}
    >
      <path
        d="M14 8a6 6 0 1 1-1.8-4.3M14 1.5V5h-3.5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function SortIcon({ desc }: { desc: boolean }) {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" aria-label={desc ? 'descending' : 'ascending'}>
      <path
        d={desc ? 'M5 1.5v7M2 5.5l3 3 3-3' : 'M5 8.5v-7M2 4.5l3-3 3 3'}
        stroke="currentColor"
        strokeWidth="1.3"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
