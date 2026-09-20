// Small shared building blocks: badges, states, stat tiles, JSON viewer.
import { useState } from 'react'
import { fmtConfidence, humanize } from '../utils/format'

export const STATUS_TONE = {
  uploaded: 'neutral',
  processing: 'info',
  extracted: 'info',
  validated: 'info',
  auto_approved: 'success',
  needs_review: 'warning',
  reviewed: 'neutral',
  failed: 'danger',
}

export function StatusBadge({ status, outcome }) {
  const label = status === 'reviewed' && outcome ? `Reviewed · ${outcome}` : humanize(status)
  const tone = status === 'reviewed' && outcome ? (outcome === 'approved' ? 'success' : 'danger') : STATUS_TONE[status] || 'neutral'
  return (
    <span className={`badge badge-${tone}`}>
      {status === 'processing' && <span className="spinner spinner-xs" />}
      {label}
    </span>
  )
}

export const SEVERITY_TONE = { info: 'neutral', warning: 'warning', error: 'danger', critical: 'critical' }

export function SeverityBadge({ severity }) {
  return <span className={`badge badge-${SEVERITY_TONE[severity] || 'neutral'}`}>{humanize(severity)}</span>
}

export function FlagStatusBadge({ status }) {
  const tone = { open: 'warning', accepted: 'danger', rejected: 'success', overridden: 'info', superseded: 'neutral' }[status] || 'neutral'
  const label = { accepted: 'Accepted (issue confirmed)', rejected: 'Rejected (false positive)', overridden: 'Overridden' }[status] || humanize(status)
  return <span className={`badge badge-${tone}`}>{label}</span>
}

export function SourceBadge({ source }) {
  const label = { rule: 'Rule', ml: 'ML anomaly', cross_doc: 'Cross-document' }[source] || source
  return <span className="badge badge-outline">{label}</span>
}

export function ConfidenceBar({ value, band, threshold = 0.85 }) {
  const pct = Math.round((value || 0) * 100)
  const tone = band || (value >= threshold ? 'high' : value >= 0.6 ? 'medium' : 'low')
  return (
    <div className="confidence" title={`Confidence ${pct}% (${tone}). Flags below ${Math.round(threshold * 100)}% are routed to a reviewer.`}>
      <div className="confidence-track">
        <div className={`confidence-fill confidence-${tone}`} style={{ width: `${pct}%` }} />
        <div className="confidence-threshold" style={{ left: `${threshold * 100}%` }} />
      </div>
      <span className="confidence-label">
        {fmtConfidence(value)} <span className="muted">{tone}</span>
      </span>
    </div>
  )
}

export function Loading({ label = 'Loading…' }) {
  return (
    <div className="state state-loading">
      <span className="spinner" /> {label}
    </div>
  )
}

export function ErrorState({ error, onRetry, title = 'Something went wrong' }) {
  return (
    <div className="state state-error" role="alert">
      <strong>{title}</strong>
      <p>{error?.detail || error?.message || String(error)}</p>
      {onRetry && (
        <button className="btn" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  )
}

export function EmptyState({ title, children, action }) {
  return (
    <div className="state state-empty">
      <strong>{title}</strong>
      {children && <p>{children}</p>}
      {action}
    </div>
  )
}

export function StatTile({ label, value, hint, tone }) {
  return (
    <div className={`stat ${tone ? `stat-${tone}` : ''}`}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  )
}

export function JsonView({ value, collapsed = false, label = 'Details' }) {
  const [open, setOpen] = useState(!collapsed)
  if (value == null) return null
  return (
    <div className="json">
      <button className="link" onClick={() => setOpen((o) => !o)}>
        {open ? '▾' : '▸'} {label}
      </button>
      {open && <pre>{JSON.stringify(value, null, 2)}</pre>}
    </div>
  )
}

export function Pager({ total, limit, offset, onChange }) {
  if (total <= limit) return null
  const page = Math.floor(offset / limit) + 1
  const pages = Math.ceil(total / limit)
  return (
    <div className="pager">
      <button className="btn btn-sm" disabled={page <= 1} onClick={() => onChange(offset - limit)}>
        ‹ Prev
      </button>
      <span className="muted">
        Page {page} of {pages} · {total} total
      </span>
      <button className="btn btn-sm" disabled={page >= pages} onClick={() => onChange(offset + limit)}>
        Next ›
      </button>
    </div>
  )
}

export function Field({ label, children, hint }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  )
}

export function Alert({ tone = 'info', children }) {
  return (
    <div className={`alert alert-${tone}`} role={tone === 'danger' ? 'alert' : 'status'}>
      {children}
    </div>
  )
}
