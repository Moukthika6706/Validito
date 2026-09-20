import { useCallback, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { audit, documents } from '../api/endpoints'
import { Alert, ConfidenceBar, EmptyState, ErrorState, FlagStatusBadge, JsonView, Loading, SeverityBadge, SourceBadge, StatusBadge } from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { useAsync } from '../hooks/useAsync'
import { fmtBytes, fmtConfidence, fmtDate, fmtNormalized, humanize } from '../utils/format'

const PIPELINE = ['uploaded', 'processing', 'extracted', 'validated', 'decided', 'reviewed']
const IN_FLIGHT = ['uploaded', 'processing', 'extracted', 'validated']

function stepState(status, step) {
  const decided = ['auto_approved', 'needs_review']
  const idx = (s) => (decided.includes(s) ? 4 : PIPELINE.indexOf(s))
  const cur = status === 'failed' ? -1 : idx(status)
  const i = PIPELINE.indexOf(step)
  if (status === 'failed') return i <= 1 ? 'failed' : ''
  if (i < cur) return 'done'
  if (i === cur) return status === 'reviewed' || decided.includes(status) ? 'done' : 'current'
  return ''
}

export default function DocumentDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { isReviewer } = useAuth()
  const [tab, setTab] = useState('flags')
  const [notice, setNotice] = useState(null)
  const shouldPoll = useCallback((d) => !d || IN_FLIGHT.includes(d.status), [])
  const doc = useAsync(() => documents.get(id), [id], { interval: 2500, shouldPoll })
  const flags = useAsync(() => documents.flags(id), [id, doc.data?.status])
  const trail = useAsync(() => (tab === 'audit' ? audit.forDocument(id) : Promise.resolve(null)), [id, tab, doc.data?.status])

  const act = async (fn, msg) => {
    setNotice(null)
    try {
      await fn()
      setNotice({ tone: 'info', text: msg })
      doc.reload(true)
    } catch (e) {
      setNotice({ tone: 'danger', text: e.detail || e.message })
    }
  }

  if (doc.loading && !doc.data) return <Loading label="Loading document…" />
  if (doc.error) return <ErrorState error={doc.error} onRetry={doc.reload} />
  const d = doc.data
  const inFlight = IN_FLIGHT.includes(d.status)
  const openFlags = (flags.data || []).filter((f) => f.status === 'open')
  const currentFlags = (flags.data || []).filter((f) => f.status !== 'superseded')

  return (
    <>
      <div className="page-header">
        <div>
          <div className="muted small">
            <Link to="/documents">Documents</Link> / #{d.id}
          </div>
          <h1>{d.original_filename}</h1>
          <p>
            {humanize(d.doc_type)} · {d.rule_pack_key ? `${d.rule_pack_key.toUpperCase()} rule pack` : 'rule pack auto-detected'} · {fmtBytes(d.size_bytes)} · {d.page_count ?? '?'} page(s)
            {d.ocr_used && ' · OCR'} · uploaded {fmtDate(d.created_at)}
          </p>
        </div>
        <div className="toolbar">
          <StatusBadge status={d.status} outcome={d.review_outcome} />
          {isReviewer && d.status === 'needs_review' && (
            <Link className="btn btn-primary" to={`/review/${d.id}`}>
              Review {openFlags.length} flag{openFlags.length === 1 ? '' : 's'}
            </Link>
          )}
          {!inFlight && (
            <button className="btn" onClick={() => act(() => documents.revalidate(d.id), 'Re-validation queued. Rules, ML and routing will re-run on the extracted terms.')}>
              Re-validate
            </button>
          )}
          {!inFlight && (
            <button className="btn" onClick={() => act(() => documents.reprocess(d.id), 'Re-processing queued. Extraction and validation will run again.')}>
              Re-process
            </button>
          )}
        </div>
      </div>

      {notice && <Alert tone={notice.tone}>{notice.text}</Alert>}

      <div className="timeline">
        {PIPELINE.map((s) => (
          <div key={s} className={`timeline-step ${stepState(d.status, s)}`}>
            {s === 'decided' ? (d.routing_decision ? humanize(d.routing_decision) : 'Decision') : humanize(s)}
          </div>
        ))}
      </div>

      {inFlight && (
        <Alert tone="info">
          <span className="spinner spinner-xs" /> Processing — {humanize(d.status).toLowerCase()}. This page refreshes automatically.
        </Alert>
      )}
      {d.status === 'failed' && (
        <Alert tone="danger">
          Processing failed: {d.error_message || 'unknown error'}. Fix the source file or try re-processing.
        </Alert>
      )}
      {d.status === 'auto_approved' && (
        <Alert tone="success">
          Auto-approved: every rule check passed with high confidence{currentFlags.length ? ` (${currentFlags.length} informational note${currentFlags.length === 1 ? '' : 's'})` : ''}. No human review needed.
        </Alert>
      )}
      {d.status === 'needs_review' && (
        <Alert tone="warning">
          Routed to human review — {openFlags.length} open flag{openFlags.length === 1 ? '' : 's'}. {isReviewer ? 'Use the review screen to accept, reject or override each one.' : 'A reviewer will look at it; you can follow progress here.'}
        </Alert>
      )}
      {d.status === 'reviewed' && (
        <Alert tone={d.review_outcome === 'approved' ? 'success' : 'danger'}>
          Review complete — final outcome: <strong>{d.review_outcome}</strong>. See the audit trail for who decided what.
        </Alert>
      )}

      <div className="tabs">
        <button className={tab === 'flags' ? 'active' : ''} onClick={() => setTab('flags')}>
          Flags ({currentFlags.length})
        </button>
        <button className={tab === 'entities' ? 'active' : ''} onClick={() => setTab('entities')}>
          Extracted terms ({d.entities.length})
        </button>
        <button className={tab === 'audit' ? 'active' : ''} onClick={() => setTab('audit')}>
          Audit trail
        </button>
      </div>

      {tab === 'flags' && (
        <div className="card">
          {flags.loading && !flags.data && <Loading />}
          {flags.error && <ErrorState error={flags.error} onRetry={flags.reload} />}
          {flags.data && currentFlags.length === 0 && (
            <EmptyState title={inFlight ? 'Validation has not run yet' : 'No flags'}>{inFlight ? 'Flags appear once the rule engine has run.' : 'Every check passed.'}</EmptyState>
          )}
          {currentFlags.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>Severity</th>
                  <th>Flag</th>
                  <th>Source</th>
                  <th>Confidence</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {currentFlags.map((f) => (
                  <tr key={f.id} className={isReviewer ? 'clickable' : ''} onClick={() => isReviewer && navigate(`/review/${d.id}?flag=${f.id}`)}>
                    <td>
                      <SeverityBadge severity={f.severity} />
                    </td>
                    <td>
                      <strong>{f.title}</strong>
                      <div className="small" style={{ maxWidth: 560 }}>
                        {f.explanation}
                      </div>
                      <div className="mono muted">{f.rule_id}</div>
                    </td>
                    <td>
                      <SourceBadge source={f.source} />
                    </td>
                    <td>
                      <ConfidenceBar value={f.confidence} band={f.confidence_band} />
                    </td>
                    <td>
                      <FlagStatusBadge status={f.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === 'entities' && (
        <div className="card">
          {d.entities.length === 0 ? (
            <EmptyState title="No terms extracted yet">{inFlight ? 'Extraction is in progress.' : 'The document produced no recognisable clauses. Check the raw text via re-process.'}</EmptyState>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Extracted text</th>
                  <th>Interpreted as</th>
                  <th>Confidence</th>
                  <th>Extractor</th>
                  <th>Page</th>
                </tr>
              </thead>
              <tbody>
                {d.entities.map((e) => (
                  <tr key={e.id} className="entity-row">
                    <td>{humanize(e.entity_type)}</td>
                    <td className="mono">{e.raw_text}</td>
                    <td>{e.normalized_value ? fmtNormalized(e.normalized_value) : <span className="badge badge-warning">could not parse</span>}</td>
                    <td>{fmtConfidence(e.confidence)}</td>
                    <td className="muted">{humanize(e.extractor)}</td>
                    <td className="muted">{e.page ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === 'audit' && (
        <div className="card">
          {trail.loading && !trail.data && <Loading />}
          {trail.error && <ErrorState error={trail.error} onRetry={trail.reload} />}
          {trail.data && (
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Event</th>
                  <th>Actor</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {trail.data.items.map((e) => (
                  <tr key={e.id}>
                    <td className="muted nowrap">{fmtDate(e.created_at)}</td>
                    <td className="mono">{e.event_type}</td>
                    <td>{e.actor_name}</td>
                    <td>
                      <JsonView value={e.payload} collapsed label="payload" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </>
  )
}
