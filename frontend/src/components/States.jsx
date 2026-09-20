// Loading / empty / error / notice primitives shared by every screen.
import Button from './Button'

export function Loading({ label = 'Loading' }) {
  return (
    <div className="state">
      <span className="spinner spinner-lg" />
      <span className="muted small">{label}…</span>
    </div>
  )
}

export function SkeletonRows({ n = 4 }) {
  return (
    <div>
      {Array.from({ length: n }).map((_, i) => (
        <div className="skeleton-row" key={i} style={{ opacity: 1 - i * 0.18 }} />
      ))}
    </div>
  )
}

export function ErrorState({ error, onRetry, title = 'Something went wrong' }) {
  return (
    <div className="state" role="alert">
      <h3 className="display display-h3">{title}</h3>
      <p className="state-error small">{error?.detail || error?.message || String(error)}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  )
}

export function EmptyState({ title, children, action }) {
  return (
    <div className="state">
      <h3 className="display display-h3">{title}</h3>
      {children && <p className="lede small" style={{ textAlign: 'center' }}>{children}</p>}
      {action}
    </div>
  )
}

export function Notice({ tone = 'info', children }) {
  return (
    <div className={`notice notice-${tone}`} role={tone === 'bad' ? 'alert' : 'status'}>
      {children}
    </div>
  )
}

export function Field({ label, hint, children }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  )
}

export function JsonDetails({ value, label = 'Details' }) {
  if (value == null) return null
  return (
    <details>
      <summary>{label}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  )
}
