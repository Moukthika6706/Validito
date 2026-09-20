import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { documents, review } from '../api/endpoints'
import Button from '../components/Button'
import ClauseCard from '../components/ClauseCard'
import GlowBackground from '../components/GlowBackground'
import { EmptyState, ErrorState, Field, Loading, Notice } from '../components/States'
import { StatusPill } from '../components/StatusPill'
import { useAuth } from '../context/AuthContext'
import { useAsync } from '../hooks/useAsync'
import { fmtNormalized, humanize } from '../utils/format'

const IN_FLIGHT = new Set(['uploaded', 'processing', 'extracted', 'validated'])
const SEV_RANK = { critical: 3, error: 2, warning: 1, info: 0 }
const PIPELINE = ['uploaded', 'processing', 'extracted', 'validated', 'decided']

export default function ReviewDocument() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { isReviewer } = useAuth()
  const [params, setParams] = useSearchParams()
  const [notice, setNotice] = useState(null)
  const [docTab, setDocTab] = useState('original')
  const [focusEntity, setFocusEntity] = useState(null)

  const shouldPoll = useCallback((d) => !d || IN_FLIGHT.has(d.status), [])
  const doc = useAsync(() => documents.get(id), [id], { interval: 2500, shouldPoll })
  const status = doc.data?.status
  const flags = useAsync(() => (status && !IN_FLIGHT.has(status) ? documents.flags(id) : Promise.resolve(null)), [id, status])
  const text = useAsync(() => (status && !IN_FLIGHT.has(status) ? documents.text(id) : Promise.resolve(null)), [id, status])

  const expandedId = Number(params.get('flag')) || null
  const setExpanded = (fid) => setParams(fid ? { flag: fid } : {}, { replace: true })

  const { open, resolved, cleanEntities } = useMemo(() => {
    const all = (flags.data || []).filter((f) => f.status !== 'superseded')
    const open = all.filter((f) => f.status === 'open').sort((a, b) => SEV_RANK[b.severity] - SEV_RANK[a.severity] || a.confidence - b.confidence)
    const resolved = all.filter((f) => f.status !== 'open')
    const flaggedEntityIds = new Set(all.map((f) => f.entity_id).filter(Boolean))
    const cleanEntities = (doc.data?.entities || []).filter((e) => !flaggedEntityIds.has(e.id))
    return { open, resolved, cleanEntities }
  }, [flags.data, doc.data])

  useEffect(() => {
    if (!expandedId && open[0]) setExpanded(open[0].id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open.length])

  const onAct = async (flag, payload) => {
    await review.act(flag.id, payload)
    setNotice({ tone: 'ok', text: { accept: 'Flag confirmed and recorded.', reject: 'Rejected as a false positive — this feeds back into future confidence for the rule.', override: 'Override saved.' }[payload.action] })
    const fresh = await flags.reload(true)
    const nextOpen = (fresh || []).filter((f) => f.status === 'open')
    if (nextOpen.length && !nextOpen.find((f) => f.id === expandedId)) setExpanded(nextOpen[0].id)
    doc.reload(true)
  }

  if (doc.loading && !doc.data) return <Loading label="Loading document" />
  if (doc.error) return <div className="page"><ErrorState error={doc.error} onRetry={doc.reload} /></div>
  const d = doc.data
  const inFlight = IN_FLIGHT.has(d.status)

  return (
    <div className="review-shell">
      <div className="review-bar">
        <div className="title">
          <Link to={isReviewer ? '/queue' : '/'} className="small muted nowrap">
            ← {isReviewer ? 'Back to queue' : 'Home'}
          </Link>
          <strong title={d.original_filename}>{d.original_filename}</strong>
          <StatusPill status={d.status} outcome={d.review_outcome} />
          <span className="micro muted nowrap">
            {d.rule_pack_key ? d.rule_pack_key.toUpperCase() : 'auto'} · {open.length} open flag{open.length === 1 ? '' : 's'}
          </span>
        </div>
        <div className="row" style={{ gap: 8 }}>
          {!inFlight && (
            <Button variant="ghost" size="sm" onClick={() => act(() => documents.revalidate(d.id), 'Re-validation queued.', setNotice, doc)}>
              Re-validate
            </Button>
          )}
          {isReviewer && !inFlight && <CompleteReview document={d} openCount={open.length} onDone={() => navigate('/queue')} />}
        </div>
      </div>

      <div className="review-panes">
        <div className="pane pane-doc">
          <div className="pane-tabs">
            <button className={docTab === 'original' ? 'active' : ''} onClick={() => setDocTab('original')}>Original</button>
            <button className={docTab === 'text' ? 'active' : ''} onClick={() => setDocTab('text')}>Extracted text</button>
          </div>
          {docTab === 'original' ? <OriginalPane document={d} onFallback={() => setDocTab('text')} /> : <TextPane text={text.data?.raw_text} entities={d.entities} focus={focusEntity} />}
        </div>

        <div className="pane pane-flags">
          <GlowBackground position="corner" soft />
          <div className="above">
            {notice && <Notice tone={notice.tone}>{notice.text}</Notice>}
            {inFlight && <ProcessingState status={d.status} />}
            {d.status === 'failed' && <Notice tone="bad">Processing failed: {d.error_message || 'unknown error'}. Fix the file or re-process.</Notice>}
            {d.status === 'auto_approved' && (
              <Notice tone="ok">Auto-approved — every rule passed with high confidence{resolved.length + open.length ? ` (${resolved.length + open.length} informational note${resolved.length + open.length === 1 ? '' : 's'})` : ''}.</Notice>
            )}
            {d.status === 'reviewed' && <Notice tone={d.review_outcome === 'approved' ? 'ok' : 'bad'}>Review complete — final outcome <strong>&nbsp;{d.review_outcome}</strong>.</Notice>}

            {!inFlight && (
              <>
                <div className="section-label">
                  <h2 className="display display-h2">Flagged clauses</h2>
                  <span className="small muted">{open.length}</span>
                </div>
                {flags.loading && !flags.data && <Loading label="Loading flags" />}
                {flags.error && <ErrorState error={flags.error} onRetry={flags.reload} />}
                {flags.data && open.length === 0 && (
                  <div className="card card-quiet">
                    <EmptyState title={resolved.length ? 'All flags resolved' : 'No flags'}>
                      {resolved.length ? (isReviewer ? 'Record the final verdict with Complete review.' : 'A reviewer has handled every flag.') : 'Every rule check passed and the anomaly model found nothing unusual.'}
                    </EmptyState>
                  </div>
                )}
                <div className="clause-list">
                  {open.map((f) => (
                    <ClauseCard key={f.id} flag={f} expanded={expandedId === f.id} onToggle={() => setExpanded(expandedId === f.id ? null : f.id)} canAct={isReviewer} onAct={onAct} onFocusEntity={(e) => { setFocusEntity(e); setDocTab('text') }} />
                  ))}
                </div>

                {resolved.length > 0 && (
                  <>
                    <div className="section-label">
                      <h3 className="display display-h3">Resolved</h3>
                      <span className="small muted">{resolved.length}</span>
                    </div>
                    <div className="clause-list">
                      {resolved.map((f) => (
                        <ClauseCard key={f.id} flag={f} muted expanded={expandedId === f.id} onToggle={() => setExpanded(expandedId === f.id ? null : f.id)} canAct={isReviewer} onAct={onAct} onFocusEntity={(e) => { setFocusEntity(e); setDocTab('text') }} />
                      ))}
                    </div>
                  </>
                )}

                <div className="section-label">
                  <h3 className="display display-h3">Clean clauses</h3>
                  <span className="small muted">{cleanEntities.length}</span>
                </div>
                {cleanEntities.length === 0 ? (
                  <p className="small muted">No other terms were extracted.</p>
                ) : (
                  <div className="clean-list">
                    {cleanEntities.map((e) => (
                      <div className="clean-item" key={e.id} onClick={() => { setFocusEntity(e); setDocTab('text') }} style={{ cursor: 'pointer' }}>
                        <strong>{humanize(e.entity_type)}</strong>
                        <span>{e.normalized_value ? fmtNormalized(e.normalized_value) : e.raw_text}</span>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

async function act(fn, msg, setNotice, doc) {
  try {
    await fn()
    setNotice({ tone: 'info', text: msg })
    doc.reload(true)
  } catch (e) {
    setNotice({ tone: 'bad', text: e.detail || e.message })
  }
}

function ProcessingState({ status }) {
  const idx = PIPELINE.indexOf(status)
  return (
    <div className="card">
      <div className="row">
        <span className="spinner" />
        <strong>{status === 'uploaded' ? 'Queued for processing' : 'Processing'}</strong>
      </div>
      <div className="timeline">
        {PIPELINE.map((s, i) => (
          <span key={s} className={i < idx ? 'done' : i === idx ? 'current' : ''}>{s === 'decided' ? 'decision' : s}</span>
        ))}
      </div>
      <p className="small muted" style={{ margin: 0 }}>Extraction (OCR for scans), rule checks, anomaly scoring and routing run in the background. This page refreshes itself.</p>
    </div>
  )
}

function OriginalPane({ document: d, onFallback }) {
  const [url, setUrl] = useState(null)
  const [error, setError] = useState(null)
  const renderable = d.mime_type === 'application/pdf' || d.mime_type.startsWith('image/')

  useEffect(() => {
    if (!renderable) return undefined
    let objectUrl
    let cancelled = false
    ;(async () => {
      try {
        const token = localStorage.getItem('validito.token')
        const res = await fetch(`${import.meta.env.VITE_API_URL || ''}/api/v1/documents/${d.id}/file`, { headers: { Authorization: `Bearer ${token}` } })
        if (!res.ok) throw new Error(`Could not load the original (${res.status})`)
        const blob = await res.blob()
        objectUrl = URL.createObjectURL(blob)
        if (!cancelled) setUrl(objectUrl)
      } catch (e) {
        if (!cancelled) setError(e.message)
      }
    })()
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [d.id, renderable])

  if (!renderable) {
    return (
      <div className="state">
        <p className="small muted">This is a {d.mime_type.includes('word') ? 'Word document' : 'file'} without an inline preview.</p>
        <Button variant="secondary" size="sm" onClick={onFallback}>View extracted text</Button>
      </div>
    )
  }
  if (error) return <div className="state"><p className="state-error small">{error}</p></div>
  if (!url) return <Loading label="Loading original" />
  return d.mime_type === 'application/pdf' ? <iframe title="original document" src={`${url}#toolbar=0&view=FitH`} /> : <img src={url} alt="original document" />
}

function TextPane({ text, entities, focus }) {
  const ref = useRef(null)
  useEffect(() => {
    if (focus && ref.current) ref.current.querySelector('mark.active')?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [focus, text])
  if (text == null) return <Loading label="Loading text" />
  const spans = (entities || []).filter((e) => e.char_start != null && e.char_end > e.char_start).sort((a, b) => a.char_start - b.char_start)
  const parts = []
  let pos = 0
  for (const e of spans) {
    if (e.char_start < pos) continue
    parts.push(text.slice(pos, e.char_start))
    parts.push(<mark key={e.id} className={focus?.id === e.id ? 'active' : ''} title={humanize(e.entity_type)}>{text.slice(e.char_start, e.char_end)}</mark>)
    pos = e.char_end
  }
  parts.push(text.slice(pos))
  return <div className="doc-text" ref={ref}>{parts}</div>
}

function CompleteReview({ document: d, openCount, onDone }) {
  const [open, setOpen] = useState(false)
  const [outcome, setOutcome] = useState('approved')
  const [comment, setComment] = useState('')
  const [resolve, setResolve] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const eligible = ['needs_review', 'auto_approved', 'reviewed'].includes(d.status)

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

  return (
    <div style={{ position: 'relative' }}>
      <Button size="sm" disabled={!eligible} onClick={() => setOpen((o) => !o)}>
        Complete review
      </Button>
      {open && (
        <div className="card card-solid" style={{ position: 'absolute', right: 0, top: 44, width: 360, zIndex: 30, boxShadow: 'var(--shadow-float)' }}>
          <p className="eyebrow">Final verdict</p>
          {error && <Notice tone="bad">{error}</Notice>}
          <Field label="Outcome">
            <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
              <option value="approved">Approved — document is acceptable</option>
              <option value="rejected">Rejected — send back to the desk</option>
            </select>
          </Field>
          {openCount > 0 && (
            <Field label={`${openCount} flag${openCount === 1 ? '' : 's'} still open`} hint="Resolve them one by one, or apply one action to all.">
              <select value={resolve} onChange={(e) => setResolve(e.target.value)}>
                <option value="">— choose —</option>
                <option value="accept">Accept all remaining</option>
                <option value="reject">Reject all remaining</option>
              </select>
            </Field>
          )}
          <Field label="Comment">
            <textarea value={comment} onChange={(e) => setComment(e.target.value)} style={{ minHeight: 60 }} />
          </Field>
          <div className="row">
            <Button size="sm" loading={busy} disabled={openCount > 0 && !resolve} onClick={submit}>
              Record verdict
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
