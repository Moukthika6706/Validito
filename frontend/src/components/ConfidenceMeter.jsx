import { fmtConfidence } from '../utils/format'

/** Horizontal confidence bar with the auto-approve threshold marked. */
export default function ConfidenceMeter({ value, band, threshold = 0.85, compact = false }) {
  const pct = Math.round((value || 0) * 100)
  const tone = band || (value >= threshold ? 'high' : value >= 0.6 ? 'medium' : 'low')
  return (
    <div className="meter" style={compact ? { minWidth: 120 } : undefined} title={`Confidence ${pct}% (${tone}). Below ${Math.round(threshold * 100)}% routes to a reviewer.`}>
      <div className="meter-track">
        <div className={`meter-fill ${tone}`} style={{ width: `${pct}%` }} />
        <div className="meter-threshold" style={{ left: `${threshold * 100}%` }} />
      </div>
      <span className="meter-label">
        {fmtConfidence(value)}
        {!compact && <span className="band">{tone}</span>}
      </span>
    </div>
  )
}
