import { useState } from 'react'
import { Link } from 'react-router-dom'
import { audit } from '../api/endpoints'
import Button from '../components/Button'
import DataTable, { Pager } from '../components/DataTable'
import { EmptyState, JsonDetails, Notice } from '../components/States'
import { useAuth } from '../context/AuthContext'
import { useAsync } from '../hooks/useAsync'
import { fmtDate } from '../utils/format'

const LIMIT = 100
const EMPTY = { document_id: '', event_type: '', actor_id: '', since: '', until: '' }

export default function AuditTrail() {
  const { isAdmin, isReviewer } = useAuth()
  const [filters, setFilters] = useState(EMPTY)
  const [applied, setApplied] = useState(EMPTY)
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

  const columns = [
    { key: 'created_at', label: 'Timestamp', sortValue: (r) => r.created_at, render: (r) => <span className="nowrap muted">{fmtDate(r.created_at)}</span>, width: 170 },
    { key: 'event_type', label: 'Action', sortValue: (r) => r.event_type, render: (r) => <span className="mono">{r.event_type}</span>, width: 190 },
    { key: 'actor_name', label: 'User', sortValue: (r) => r.actor_name || '', width: 130 },
    { key: 'document_id', label: 'Document', sortValue: (r) => r.document_id ?? -1, render: (r) => (r.document_id ? <Link to={`/review/${r.document_id}`} onClick={(e) => e.stopPropagation()}>#{r.document_id}</Link> : '—'), width: 90 },
    { key: 'summary', label: 'Detail', render: (r) => <Summary payload={r.payload} type={r.event_type} /> },
    { key: 'hash', label: 'Hash', render: (r) => <span className="mono muted" title={`prev ${r.prev_hash || 'genesis'}`}>{r.hash.slice(0, 10)}…</span>, width: 110 },
  ]

  return (
    <div className="page page-dense">
      <div className="page-head" style={{ marginBottom: 24 }}>
        <div>
          <p className="eyebrow">Compliance</p>
          <h1 className="display display-h1">Audit trail</h1>
          <p className="lede small" style={{ marginTop: 8 }}>
            Append-only, hash-chained. Every extraction, rule decision, routing outcome, rule-pack edit and reviewer action.
            {!isReviewer && ' You see events on your own documents.'}
          </p>
        </div>
        {isAdmin && (
          <Button variant="secondary" size="sm" onClick={runVerify} loading={verify?.loading}>
            Verify chain integrity
          </Button>
        )}
      </div>

      {verify && !verify.loading && (
        <Notice tone={verify.error || !verify.ok ? 'bad' : 'ok'}>
          {verify.error
            ? verify.error
            : verify.ok
              ? `Chain intact — ${verify.entries} entries re-hashed, every link matches.`
              : `Chain broken at entry #${verify.first_bad_id}: a row was altered or removed outside the logger.`}
        </Notice>
      )}

      <form
        className="card card-quiet card-tight"
        style={{ marginBottom: 16 }}
        onSubmit={(e) => {
          e.preventDefault()
          setOffset(0)
          setApplied(filters)
        }}
      >
        <div className="filters">
          <label className="field" style={{ minWidth: 110 }}>
            <span className="field-label">Document #</span>
            <input value={filters.document_id} onChange={set('document_id')} placeholder="any" />
          </label>
          <label className="field">
            <span className="field-label">Action</span>
            <select value={filters.event_type} onChange={set('event_type')}>
              <option value="">any</option>
              <option value="review.*">review.*</option>
              <option value="flag.*">flag.*</option>
              <option value="routing.*">routing.*</option>
              <option value="rule_pack.*">rule_pack.*</option>
              {(types.data || []).map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </label>
          {isReviewer && (
            <label className="field" style={{ minWidth: 110 }}>
              <span className="field-label">User #</span>
              <input value={filters.actor_id} onChange={set('actor_id')} placeholder="any" />
            </label>
          )}
          <label className="field">
            <span className="field-label">From</span>
            <input type="datetime-local" value={filters.since} onChange={set('since')} />
          </label>
          <label className="field">
            <span className="field-label">To</span>
            <input type="datetime-local" value={filters.until} onChange={set('until')} />
          </label>
          <Button size="sm">Apply</Button>
          <Button type="button" variant="ghost" size="sm" onClick={() => { setFilters(EMPTY); setApplied(EMPTY); setOffset(0) }}>
            Clear
          </Button>
        </div>
      </form>

      <div className="card card-solid card-tight">
        <DataTable
          dense
          columns={columns}
          rows={q.data?.items || null}
          loading={q.loading}
          error={q.error}
          onRetry={q.reload}
          empty={<EmptyState title="No events match">Widen the filters, or upload a document to generate activity.</EmptyState>}
          expandable={(r) => (
            <div className="grid-2 small">
              <dl className="kv">
                <dt>Entry</dt>
                <dd>#{r.id}</dd>
                <dt>Target</dt>
                <dd>{r.target_type}{r.target_id ? ` #${r.target_id}` : ''}</dd>
                <dt>Actor</dt>
                <dd>{r.actor_name}{r.actor_id ? ` (user #${r.actor_id})` : ''}</dd>
                <dt>Hash</dt>
                <dd className="mono" style={{ wordBreak: 'break-all' }}>{r.hash}</dd>
                <dt>Previous</dt>
                <dd className="mono" style={{ wordBreak: 'break-all' }}>{r.prev_hash || 'genesis'}</dd>
              </dl>
              <JsonDetails value={r.payload} label="Payload" />
            </div>
          )}
        />
        <Pager total={q.data?.total} limit={LIMIT} offset={offset} onChange={setOffset} />
      </div>
    </div>
  )
}

function Summary({ payload, type }) {
  if (!payload) return <span className="muted">—</span>
  let text = null
  if (type === 'document.status_changed') text = `${payload.from} → ${payload.to}${payload.outcome ? ` (${payload.outcome})` : ''}${payload.reason ? ` · ${payload.reason}` : ''}`
  else if (type === 'flag.raised') text = `${payload.severity} · ${payload.rule_id} · ${payload.title}`
  else if (type === 'routing.decided') text = `${payload.decision}: ${payload.reason}`
  else if (type === 'review.action') text = `${payload.action} on ${payload.rule_id}${payload.comment ? ` — “${payload.comment}”` : ''}`
  else if (type === 'entity.extracted') text = `${payload.entity_type}: ${payload.raw_text}`
  else if (type === 'extraction.completed') text = `${payload.entity_count} terms from ${payload.page_count} page(s)${payload.ocr_used ? ' via OCR' : ''}`
  else if (type === 'validation.completed') text = `${payload.flag_count} flag(s), score ${payload.score}`
  else if (type === 'validation.started') text = `${payload.rule_pack} v${payload.rule_pack_version}`
  else if (type === 'document.uploaded') text = `${payload.filename} (${payload.mime_type})`
  else if (type === 'user.updated') text = `${JSON.stringify(payload.before)} → ${JSON.stringify(payload.after)}`
  else if (type?.startsWith('rule_pack')) text = `${payload.key} v${payload.version || payload.to_version || payload.activated_version}${payload.rule_id ? ` · ${payload.rule_id}` : ''}`
  else if (type?.startsWith('user.')) text = payload.email || ''
  return text ? <span>{text}</span> : <span className="muted">expand for payload</span>
}
