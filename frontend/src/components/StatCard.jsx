/** Glassy stat tile: big condensed number, small label. `loading` renders a shimmer. */
export default function StatCard({ value, unit, label, hint, loading = false }) {
  return (
    <div className="card stat-card above">
      <div>
        {loading ? (
          <div className="stat-skeleton" />
        ) : (
          <div className="stat-value">
            {value}
            {unit && <small>{unit}</small>}
          </div>
        )}
        <div className="stat-label">{label}</div>
      </div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  )
}
