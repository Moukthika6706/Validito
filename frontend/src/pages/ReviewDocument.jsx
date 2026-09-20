import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { documents, review } from '../api/endpoints'
import { Alert, ConfidenceBar, EmptyState, ErrorState, Field, FlagStatusBadge, JsonView, Loading, SeverityBadge, SourceBadge, StatusBadge } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { fmtConfidence, fmtDate, fmtNormalized, humanize } from '../utils/format'

export default function ReviewDocument() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const doc = useAsync(() => documents.get(id), [id])
  const text = useAsync(() => documents.text(id), [id])
  const flags = useAsync(() => documents.flags(id), [id])
  const [notice, setNotice] = useState(null)
  const [showResolved, setShowResolved] = useState(false)

  const list = useMemo(() => (flags.data || []).filter((f) => f.status !== 'superseded' && (showResolved || f.status === 'open')), [flags.data, showResolved])
  const selectedId = Number(params.get('flag')) || list[0]?.id
  const selected = list.find((f) => f.id === selectedId) || (flags.data || []).find((f) => f.id === selectedId)
  const openCount = (flags.data || []).filter((f) => f.status === 'open').length

  useEffect(() => {
    if (!params.get('flag') && list[0]) setParams({ flag: list[0].id }, { replace: true })
  }, [list, params, setParams])

  const select = (fid) => setParams({ flag: fid })
  const idx = list.findIndex((f) => f.id === selectedId)
  const goto = (delta) => {
    const next = list[idx + delta]
    if (next) select(next.id)
  }

  const afterAction = async (msg) => {
    setNotice({ tone: 'success', text: msg })
    await flags.reload(true)
    const remaining = (await flags.reload(true))?.filter((f) => f.status === 'open') || []
    if (remaining.length && !remaining.find((f) => f.id === selectedId)) select(remaining[0].id)
    doc.reload(true)
  }

  if (doc.loading && !doc.data) return <Loading label="Loading review…" />
  if (doc.error) return <ErrorState error={doc.error} onRetry={doc.reload} />
  const d = doc.data

  return (
    <>
      <div className="page-header">
        <div>
          <div className="muted small">
            <Link to="/review">Review queue</Link> / <Link to={`/documents/${d.id}`}>#{d.id}</Link>
          </div>
          <h1>Review: {d.original_filename}</h1>
          <p>
            {d.rule_pack_key?.toUpperCase()} rule pack · {openCount} open flag{openCount === 1 ? '' : 's'} · uploaded {fmtDate(d.created_at)}
          </p>
        </div>
        <div className="toolbar">
          <StatusBadge status={d.status} outcome={d.review_outcome} />
          <CompleteButton document={d} openCount={openCount} onDone={() => navigate('/review')} />
        </div>
      </div>

      {notice && <Alert tone={notice.tone}>{notice.text}</Alert>}
      {d.status === 'reviewed' && <Alert tone="info">This document has already been completed ({d.review_outcome}). Actions here are still recorded in the audit trail.</Alert>}

      <div className="review-layout">
        <div>
          <div className="card-header">
            <h2 style={{ margin: 0 }}>Flags</h2>
            <label className="small muted" style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
              <input type="checkbox" checked={showResolved} onChange={(e) => setShowResolved(e.target.checked)} /> show resolved
            </label>
          </div>
          {flags.loading && !flags.data && <Loading />}
          {flags.data && list.length === 0 && (
            <EmptyState title={openCount === 0 ? 'All flags resolved' : 'Nothing to show'}>{openCount === 0 ? 'Complete the review to record the final outcome.' : 'Tick "show resolved" to see handled flags.'}</EmptyState>
          )}
          <div className="flag-list">
            {list.map((f) => (
              <div key={f.id} className={`flag-item ${f.id === selectedId ? 'active' : ''}`} onClick={() => select(f.id)}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6 }}>
                  <SeverityBadge severity={f.severity} />
                  <span className="muted small">{fmtConfidence(f.confidence)}</span>
                </div>
                <span className="flag-item-title">{f.title}</span>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6 }}>
                  <SourceBadge source={f.source} />
                  {f.status !== 'open' && <FlagStatusBadge status={f.status} />}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div>
          {!selected && flags.data && <EmptyState title="Select a flag">Pick a flag on the left to see the clause, the rule that fired, and act on it.</EmptyState>}
          {selected && (
            <FlagPanel key={selected.id} flag={selected} rawText={text.data?.raw_text} onPrev={idx > 0 ? () => goto(-1) : null} onNext={idx < list.length - 1 ? () => goto(1) : null} onActed={afterAction} />
          )}
        </div>
      </div>
    </>
  )
}

function FlagPanel({ flag, rawText, onPrev, onNext, onActed }) {
  const [comment, setComment] = useState('')
  const [override, setOverride] = useState('')
  const [mode, setMode] = useState(null) // 'override' shows the value box
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const entity = flag.entity
  const ev = flag.evidence || {}
  const snap = flag.rule_snapshot || {}

  const act = async (action) => {
    setBusy(true)
    setError(null)
    try {
      let override_value = null
      if (action === 'override') {
        if (!override.trim()) throw new Error('Enter the corrected value.')
        try {
          override_value = JSON.parse(override)
        } catch {
          override_value = { value: override.trim() }
        }
      }
      await review.act(flag.id, { action, comment: comment || null, override_value })
      setComment('')
      setOverride('')
      setMode(null)
      onActed(
        {
          accept: 'Flag accepted — the issue is confirmed and recorded.',
          reject: 'Flag rejected as a false positive. This feeds back into future confidence for this rule.',
          override: 'Override recorded with your corrected value.',
        }[action],
      )
    } catch (e) {
      setError(e.detail || e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <SeverityBadge severity={flag.severity} /> <SourceBadge source={flag.source} /> <FlagStatusBadge status={flag.status} />
          <h2 style={{ marginTop: 8 }}>{flag.title}</h2>
        </div>
        <div className="btn-group">
          <button className="btn btn-sm" disabled={!onPrev} onClick={onPrev}>
            ‹ Prev
          </button>
          <button className="btn btn-sm" disabled={!onNext} onClick={onNext}>
            Next ›
          </button>
        </div>
      </div>

      <div className="side-by-side">
        <div className="panel">
          <h3>Extracted clause</h3>
          {entity ? (
            <>
              <div className="clause">{entity.raw_text}</div>
              <dl className="kv" style={{ marginTop: 10 }}>
                <dt>Field</dt>
                <dd>{humanize(entity.entity_type)}</dd>
                <dt>Interpreted as</dt>
                <dd>{entity.normalized_value ? fmtNormalized(entity.normalized_value) : <span className="badge badge-warning">could not parse</span>}</dd>
                <dt>Extraction</dt>
                <dd>
                  {humanize(entity.extractor)} · {fmtConfidence(entity.confidence)} confidence{entity.page ? ` · page ${entity.page}` : ''}
                </dd>
              </dl>
              <Context rawText={rawText} entity={entity} />
            </>
          ) : ev.related_document_id ? (
            <p className="muted">Cross-document finding — compares this document with #{ev.related_document_id}. See evidence for both values.</p>
          ) : (
            <p className="muted">No single clause — this flag is about the document as a whole (e.g. a missing field or an unusual combination of values).</p>
          )}
        </div>

        <div className="panel">
          <h3>Why it was flagged</h3>
          <div className="explanation">{flag.explanation}</div>
          <dl className="kv" style={{ marginTop: 10 }}>
            <dt>Rule</dt>
            <dd className="mono">{flag.rule_id}</dd>
            <dt>Check</dt>
            <dd>
              {snap.check || ev.check}
              {snap.params && Object.keys(snap.params).length > 0 && <span className="mono muted"> {JSON.stringify(snap.params)}</span>}
            </dd>
            <dt>Source</dt>
            <dd>{flag.source_description}</dd>
            <dt>Confidence</dt>
            <dd>
              <ConfidenceBar value={flag.confidence} band={flag.confidence_band} />
              {ev.calibration?.applied && (
                <div className="muted small">
                  Calibrated from reviewer feedback: {ev.calibration.accepted} accepted / {ev.calibration.rejected} rejected → ×{ev.calibration.multiplier}
                </div>
              )}
            </dd>
            {snap.pack && (
              <>
                <dt>Pack</dt>
                <dd>
                  {snap.pack.toUpperCase()} v{snap.pack_version}
                </dd>
              </>
            )}
          </dl>
          {flag.source === 'ml' && ev.contributions && (
            <div style={{ marginTop: 10 }}>
              <h3>Largest deviations from typical</h3>
              {ev.contributions.map((c) => (
                <div className="deviation" key={c.feature}>
                  <span>{c.label}</span>
                  <span>
                    <strong>{c.value_text}</strong> <span className="muted">vs {c.typical_text}</span> <span className="badge badge-outline">{c.z_score > 0 ? '+' : ''}{c.z_score}σ</span>
                  </span>
                </div>
              ))}
              <div className="muted small" style={{ marginTop: 6 }}>
                Isolation forest score {ev.forest_score} · deviation score {ev.deviation_score} · threshold {ev.threshold}
              </div>
            </div>
          )}
          {flag.source === 'cross_doc' && (
            <dl className="kv" style={{ marginTop: 10 }}>
              <dt>This document</dt>
              <dd className="mono">{JSON.stringify(ev.value ?? ev.values)}</dd>
              <dt>Related #{ev.related_document_id}</dt>
              <dd className="mono">{JSON.stringify(ev.related_value ?? ev.related_values)}</dd>
            </dl>
          )}
          <JsonView value={ev} collapsed label="Full evidence" />
          <JsonView value={snap} collapsed label="Rule definition at time of flag" />
        </div>
      </div>

      {flag.review_actions?.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <h3>Review history</h3>
          {flag.review_actions.map((a) => (
            <div key={a.id} className="small" style={{ padding: '4px 0', borderBottom: '1px solid var(--border)' }}>
              <strong>{humanize(a.action)}</strong> by {a.reviewer?.full_name || `user ${a.reviewer_id}`} · {fmtDate(a.created_at)}
              {a.comment && <div className="muted">“{a.comment}”</div>}
              {a.override_value && <div className="mono muted">→ {JSON.stringify(a.override_value)}</div>}
            </div>
          ))}
        </div>
      )}

      <div style={{ marginTop: 16 }}>
        {error && <Alert tone="danger">{error}</Alert>}
        <Field label="Comment (recorded in the audit trail)">
          <textarea value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Why you are accepting, rejecting or overriding this flag" />
        </Field>
        {mode === 'override' && (
          <Field label="Corrected value" hint='JSON (e.g. {"amount": 50000000, "currency": "USD"}) or plain text.'>
            <input value={override} onChange={(e) => setOverride(e.target.value)} placeholder="The value the document should be read as" />
          </Field>
        )}
        <div className="btn-group">
          <button className="btn btn-danger" disabled={busy} onClick={() => act('accept')} title="The issue is real">
            Accept flag (issue confirmed)
          </button>
          <button className="btn btn-success" disabled={busy} onClick={() => act('reject')} title="False positive">
            Reject flag (false positive)
          </button>
          {mode === 'override' ? (
            <button className="btn btn-primary" disabled={busy} onClick={() => act('override')}>
              Save override
            </button>
          ) : (
            <button className="btn" disabled={busy} onClick={() => setMode('override')}>
              Override value…
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

function Context({ rawText, entity }) {
  if (!rawText || entity.char_start == null) return null
  const start = Math.max(0, entity.char_start - 160)
  const end = Math.min(rawText.length, entity.char_end + 160)
  return (
    <details style={{ marginTop: 10 }}>
      <summary className="small">Show in document text</summary>
      <div className="context">
        {rawText.slice(start, entity.char_start)}
        <mark>{rawText.slice(entity.char_start, entity.char_end)}</mark>
        {rawText.slice(entity.char_end, end)}
      </div>
    </details>
  )
}

function CompleteButton({ document: d, openCount, onDone }) {
  const [open, setOpen] = useState(false)
  const [outcome, setOutcome] = useState('approved')
  const [comment, setComment] = useState('')
  const [resolve, setResolve] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      await review.complete(d.id, { outcome, comment: comment || null, resolve_remaining: openCount > 0 ? resolve || null : null })
      onDone()
    } catch (e) {
      setError(e.detail || e.message)
    } finally {
      setBusy(false)
    }
  }

  if (!open)
    return (
      <button className="btn btn-primary" onClick={() => setOpen(true)} disabled={!['needs_review', 'auto_approved', 'reviewed'].includes(d.status)}>
        Complete review
      </button>
    )
  return (
    <div className="card" style={{ margin: 0, minWidth: 320 }}>
      <h3>Final verdict</h3>
      {error && <Alert tone="danger">{error}</Alert>}
      <Field label="Outcome">
        <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
          <option value="approved">Approved — document is acceptable</option>
          <option value="rejected">Rejected — send back to the desk</option>
        </select>
      </Field>
      {openCount > 0 && (
        <Field label={`${openCount} flag(s) still open`} hint="Resolve them individually, or apply one action to all remaining.">
          <select value={resolve} onChange={(e) => setResolve(e.target.value)}>
            <option value="">— choose —</option>
            <option value="accept">Accept all remaining (issues confirmed)</option>
            <option value="reject">Reject all remaining (false positives)</option>
          </select>
        </Field>
      )}
      <Field label="Comment">
        <textarea value={comment} onChange={(e) => setComment(e.target.value)} />
      </Field>
      <div className="btn-group">
        <button className="btn btn-primary" disabled={busy || (openCount > 0 && !resolve)} onClick={submit}>
          {busy ? 'Saving…' : 'Record verdict'}
        </button>
        <button className="btn" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </div>
  )
}
