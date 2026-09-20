import { useState } from 'react'
import { Link } from 'react-router-dom'
import { audit } from '../api/endpoints'
import { Alert, EmptyState, ErrorState, Field, JsonView, Loading, Pager } from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { useAsync } from '../hooks/useAsync'
import { fmtDate } from '../utils/format'

const LIMIT = 50

export default function AuditTrail() {
  const { isAdmin, isReviewer } = useAuth()
  const [filters, setFilters] = useState({ document_id: '', event_type: '', actor_id: '', since: '', until: '' })
  const [applied, setApplied] = useState(filters)
  const [offset, setOffset] = useState(0)
  const [verify, setVerify] = useState(null)
  const types = useAsync(() => audit.eventTypes(), [])
  const q = useAsync(
    () =>
      audit.query({
        ...applied,
        since: applied.since ? new Date(applied.since).toISOString() : undefined,
        until: applied.until ? new Date(applied.until).toISOString() : undefined,
        limit: LIMIT,
        offset,
      }),
    [applied, offset],
  )
  const set = (k) => (e) => setFilters((f) => ({ ...f, [k]: e.target.value }))

  const runVerify = async () => {
    setVerify({ loading: true })
    try {
      setVerify(await audit.verify())
    } catch (e) {
      setVerify({ error: e.detail || e.message })
    }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Audit trail</h1>
          <p>
            Immutable, hash-chained log of every extraction, rule decision, routing outcome and reviewer action.
            {!isReviewer && ' Analysts see events on their own documents.'}
          </p>
        </div>
        {isAdmin && (
          <div className="toolbar">
            <button className="btn" onClick={runVerify} disabled={verify?.loading}>
              {verify?.loading ? 'Verifying…' : 'Verify chain integrity'}
            </button>
          </div>
        )}
      </div>

      {verify && !verify.loading && (
        <Alert tone={verify.error ? 'danger' : verify.ok ? 'success' : 'danger'}>
          {verify.error
            ? verify.error
            : verify.ok
              ? `Chain intact — ${verify.entries} entries re-hashed and every link matches.`
              : `Chain BROKEN at entry #${verify.first_bad_id}: a row was altered or removed outside the logger.`}
        </Alert>
      )}

      <form
        className="card inline-form"
        onSubmit={(e) => {
          e.preventDefault()
          setOffset(0)
          setApplied(filters)
        }}
      >
        <Field label="Document #">
          <input value={filters.document_id} onChange={set('document_id')} style={{ width: 100 }} placeholder="any" />
        </Field>
        <Field label="Event type">
          <select value={filters.event_type} onChange={set('event_type')}>
            <option value="">any</option>
            <option value="review.*">review.*</option>
            <option value="flag.*">flag.*</option>
            <option value="routing.*">routing.*</option>
            <option value="rule_pack.*">rule_pack.*</option>
            {(types.data || []).map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </Field>
        {isReviewer && (
          <Field label="Actor user #">
            <input value={filters.actor_id} onChange={set('actor_id')} style={{ width: 100 }} placeholder="any" />
          </Field>
        )}
        <Field label="From">
          <input type="datetime-local" value={filters.since} onChange={set('since')} />
        </Field>
        <Field label="To">
          <input type="datetime-local" value={filters.until} onChange={set('until')} />
        </Field>
        <button className="btn btn-primary">Apply</button>
        <button
          type="button"
          className="btn"
          onClick={() => {
            const empty = { document_id: '', event_type: '', actor_id: '', since: '', until: '' }
            setFilters(empty)
            setApplied(empty)
            setOffset(0)
          }}
        >
          Clear
        </button>
      </form>

      <div className="card">
        {q.loading && !q.data && <Loading />}
        {q.error && <ErrorState error={q.error} onRetry={q.reload} />}
        {q.data && q.data.items.length === 0 && <EmptyState title="No events match">Widen the filters, or upload a document to generate activity.</EmptyState>}
        {q.data && q.data.items.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>When</th>
                  <th>Event</th>
                  <th>Actor</th>
                  <th>Document</th>
                  <th>Target</th>
                  <th>Payload</th>
                  <th>Hash</th>
                </tr>
              </thead>
              <tbody>
                {q.data.items.map((e) => (
                  <tr key={e.id}>
                    <td className="muted">{e.id}</td>
                    <td className="muted nowrap">{fmtDate(e.created_at)}</td>
                    <td className="mono">{e.event_type}</td>
                    <td>{e.actor_name}</td>
                    <td>{e.document_id ? <Link to={`/documents/${e.document_id}`}>#{e.document_id}</Link> : '—'}</td>
                    <td className="muted">
                      {e.target_type}
                      {e.target_id ? ` #${e.target_id}` : ''}
                    </td>
                    <td>
                      <Summary payload={e.payload} type={e.event_type} />
                      <JsonView value={e.payload} collapsed label="raw" />
                    </td>
                    <td className="mono muted" title={`prev: ${e.prev_hash || 'genesis'}`}>
                      {e.hash.slice(0, 10)}…
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pager total={q.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
          </div>
        )}
      </div>
    </>
  )
}

function Summary({ payload, type }) {
  if (!payload) return null
  let text = null
  if (type === 'document.status_changed') text = `${payload.from} → ${payload.to}${payload.outcome ? ` (${payload.outcome})` : ''}`
  else if (type === 'flag.raised') text = `${payload.severity} · ${payload.rule_id} · ${payload.title}`
  else if (type === 'routing.decided') text = `${payload.decision}: ${payload.reason}`
  else if (type === 'review.action') text = `${payload.action} on ${payload.rule_id}${payload.comment ? ` — “${payload.comment}”` : ''}`
  else if (type === 'entity.extracted') text = `${payload.entity_type}: ${payload.raw_text}`
  else if (type === 'extraction.completed') text = `${payload.entity_count} terms from ${payload.page_count} page(s)${payload.ocr_used ? ' via OCR' : ''}`
  else if (type === 'validation.completed') text = `${payload.flag_count} flag(s), score ${payload.score}`
  else if (type === 'document.uploaded') text = `${payload.filename} (${payload.mime_type})`
  else if (type?.startsWith('rule_pack')) text = `${payload.key} v${payload.version || payload.to_version || payload.activated_version}${payload.rule_id ? ` · ${payload.rule_id}` : ''}`
  return text ? <div className="small">{text}</div> : null
}
