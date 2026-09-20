export const fmtDate = (iso) => {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export const fmtRelative = (iso) => {
  if (!iso) return '—'
  const secs = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (secs < 60) return `${Math.round(secs)}s ago`
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`
  return `${Math.round(secs / 86400)}d ago`
}

export const fmtBytes = (n) => {
  if (n == null) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export const fmtPct = (n, digits = 0) => (n == null ? '—' : `${Number(n).toFixed(digits)}%`)

export const fmtConfidence = (c) => (c == null ? '—' : `${Math.round(c * 100)}%`)

export const humanize = (s) => (s ? String(s).replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase()) : '')

export const fmtAmount = (nv) => {
  if (!nv || nv.amount == null) return null
  const amt = Number(nv.amount)
  const str = amt >= 1e6 ? `${(amt / 1e6).toLocaleString(undefined, { maximumFractionDigits: 2 })}m` : amt.toLocaleString()
  return `${nv.currency || ''} ${str}`.trim()
}

/** Compact one-line rendering of a normalized_value for tables. */
export const fmtNormalized = (nv) => {
  if (!nv) return null
  if (nv.amount != null) return fmtAmount(nv)
  if (nv.date) return nv.date
  if (nv.tenor) return `${nv.tenor.value} ${nv.tenor.unit}${nv.tenor.value === 1 ? '' : 's'}`
  if (nv.type === 'fixed') return `${nv.rate_pct}% fixed`
  if (nv.type === 'floating') return `${nv.benchmark_tenor ? nv.benchmark_tenor + ' ' : ''}${nv.benchmark}${nv.spread_bps != null ? ` + ${nv.spread_bps} bps` : ''}`
  if (nv.type === 'spread') return `${nv.spread_bps} bps`
  if (nv.jurisdiction) return nv.jurisdiction
  if (nv.name) return `${nv.name}${nv.role ? ` (${humanize(nv.role)})` : ''}`
  if (nv.currency && Object.keys(nv).length === 1) return nv.currency
  if (nv.frequency) return `${humanize(nv.frequency)} (${nv.per_year}/yr)`
  if (nv.convention) return nv.convention
  if (nv.type) return humanize(nv.type)
  if (nv.text) return nv.text
  return JSON.stringify(nv)
}
