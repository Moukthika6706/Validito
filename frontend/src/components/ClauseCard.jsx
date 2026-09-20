import { useState } from 'react'
import { fmtDate, fmtNormalized, humanize } from '../utils/format'
import Button from './Button'
import ConfidenceMeter from './ConfidenceMeter'
import { FlagStatusPill, SeverityPill, SourcePill } from './StatusPill'
import { Field, JsonDetails, Notice } from './States'

/**
 * One flagged clause: collapsed header (severity, title, excerpt, confidence) that expands
 * into the full explanation, evidence, history and reviewer actions.
 */
export default function ClauseCard({ flag, expanded, onToggle, canAct, onAct, onFocusEntity, muted = false }) {
  const [comment, setComment] = useState('')
  const [override, setOverride] = useState('')
  const [overriding, setOverriding] = useState(false)
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  const entity = flag.entity
  const ev = flag.evidence || {}
  const snap = flag.rule_snapshot || {}

  const act = async (action) => {
    setError(null)
    let override_value = null
    if (action === 'override') {
      if (!override.trim()) return setError('Enter the corrected value first.')
      try {
        override_value = JSON.parse(override)
      } catch {
        override_value = { value: override.trim() }
      }
    }
    setBusy(action)
    try {
      await onAct(flag, { action, comment: comment || null, override_value })
      setComment('')
      setOverride('')
      setOverriding(false)
    } catch (e) {
      setError(e.detail || e.message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className={`card clause ${muted ? 'muted-clause' : ''}`}>
      <div className="clause-head" onClick={onToggle} role="button" aria-expanded={expanded}>
        <div style={{ minWidth: 0 }}>
          <div className="row" style={{ gap: 6 }}>
            <SeverityPill severity={flag.severity} />
            <SourcePill source={flag.source} />
            {flag.status !== 'open' && <FlagStatusPill status={flag.status} />}
          </div>
          <div className="clause-title">{flag.title}</div>
          {entity ? (
            <span className="clause-excerpt" title={entity.raw_text}>
              {humanize(entity.entity_type)}: {entity.raw_text}
            </span>
          ) : (
            <span className="clause-excerpt muted">{ev.related_document_id ? `vs related document #${ev.related_document_id}` : 'whole document'}</span>
          )}
        </div>
        <div style={{ textAlign: 'right' }}>
          <ConfidenceMeter value={flag.confidence} band={flag.confidence_band} compact />
          <div className="micro muted" style={{ marginTop: 6 }}>{expanded ? 'collapse ▴' : 'details ▾'}</div>
        </div>
      </div>

      {expanded && (
        <div className="clause-body">
          <div className="explain" style={{ marginTop: 16 }}>{flag.explanation}</div>

          <dl className="kv">
            <dt>Triggered by</dt>
            <dd>
              <span className="mono">{flag.rule_id}</span>
              <span className="muted"> · {snap.check || ev.check}</span>
              {snap.params && Object.keys(snap.params).length > 0 && <div className="mono muted micro">{JSON.stringify(snap.params)}</div>}
            </dd>
            <dt>Source</dt>
            <dd>{flag.source_description}</dd>
            <dt>Confidence</dt>
            <dd>
              <ConfidenceMeter value={flag.confidence} band={flag.confidence_band} />
              {ev.calibration?.applied && (
                <div className="micro muted">
                  calibrated from reviewer feedback: {ev.calibration.accepted} confirmed / {ev.calibration.rejected} rejected → ×{ev.calibration.multiplier}
                </div>
              )}
            </dd>
            {entity && (
              <>
                <dt>Extracted as</dt>
                <dd>
                  {entity.normalized_value ? fmtNormalized(entity.normalized_value) : <span className="pill pill-warn">could not parse</span>}
                  <div className="micro muted">
                    {humanize(entity.extractor)} · {Math.round(entity.confidence * 100)}% extraction confidence{entity.page ? ` · page ${entity.page}` : ''}
                    {onFocusEntity && entity.char_start != null && (
                      <>
                        {' · '}
                        <button className="link" onClick={() => onFocusEntity(entity)}>
                          show in text
                        </button>
                      </>
                    )}
                  </div>
                </dd>
              </>
            )}
            {snap.pack && (
              <>
                <dt>Rule pack</dt>
                <dd>
                  {snap.pack.toUpperCase()} v{snap.pack_version}
                </dd>
              </>
            )}
          </dl>

          {flag.source === 'ml' && ev.contributions && (
            <div>
              <p className="eyebrow">Largest deviations from typical</p>
              {ev.contributions.map((c) => (
                <div className="deviation" key={c.feature}>
                  <span>{c.label}</span>
                  <span>
                    <strong>{c.value_text}</strong> <span className="muted">vs {c.typical_text}</span>{' '}
                    <span className="pill pill-plain">{c.z_score > 0 ? '+' : ''}{c.z_score}σ</span>
                  </span>
                </div>
              ))}
              <div className="micro muted" style={{ marginTop: 6 }}>
                forest {ev.forest_score} · deviation {ev.deviation_score} · threshold {ev.threshold}
              </div>
            </div>
          )}
          {flag.source === 'cross_doc' && (
            <dl className="kv">
              <dt>This document</dt>
              <dd className="mono">{JSON.stringify(ev.value ?? ev.values)}</dd>
              <dt>Related #{ev.related_document_id}</dt>
              <dd className="mono">{JSON.stringify(ev.related_value ?? ev.related_values)}</dd>
            </dl>
          )}

          <div className="row json-toggle">
            <JsonDetails value={ev} label="Full evidence" />
            <JsonDetails value={snap} label="Rule at time of flag" />
          </div>

          {flag.review_actions?.length > 0 && (
            <div>
              {flag.review_actions.map((a) => (
                <div key={a.id} className="history">
                  <strong>{humanize(a.action)}</strong> · {a.reviewer?.full_name || `user ${a.reviewer_id}`} · {fmtDate(a.created_at)}
                  {a.comment && <div>“{a.comment}”</div>}
                  {a.override_value && <div className="mono">→ {JSON.stringify(a.override_value)}</div>}
                </div>
              ))}
            </div>
          )}

          {canAct && (
            <div>
              {error && <Notice tone="bad">{error}</Notice>}
              <Field label="Comment">
                <textarea value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Why you are confirming, rejecting or overriding (recorded in the audit trail)" style={{ minHeight: 64 }} />
              </Field>
              {overriding && (
                <Field label="Corrected value" hint='JSON like {"amount": 50000000, "currency": "USD"} or plain text.'>
                  <input value={override} onChange={(e) => setOverride(e.target.value)} autoFocus />
                </Field>
              )}
              <div className="clause-actions">
                <Button variant="danger" size="sm" loading={busy === 'accept'} disabled={!!busy} onClick={() => act('accept')} title="The issue is real">
                  Accept flag
                </Button>
                <Button variant="ok" size="sm" loading={busy === 'reject'} disabled={!!busy} onClick={() => act('reject')} title="False positive">
                  Reject flag
                </Button>
                {overriding ? (
                  <>
                    <Button size="sm" loading={busy === 'override'} disabled={!!busy} onClick={() => act('override')}>
                      Save override
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => setOverriding(false)}>
                      Cancel
                    </Button>
                  </>
                ) : (
                  <Button variant="secondary" size="sm" disabled={!!busy} onClick={() => setOverriding(true)}>
                    Override…
                  </Button>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
