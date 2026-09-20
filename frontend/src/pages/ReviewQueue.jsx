import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { metrics, review } from '../api/endpoints'
import Button from '../components/Button'
import DataTable, { Pager } from '../components/DataTable'
import GlowBackground from '../components/GlowBackground'
import { EmptyState } from '../components/States'
import { SeverityPill, StatusPill } from '../components/StatusPill'
import { useAsync } from '../hooks/useAsync'
import { fmtConfidence, fmtRelative } from '../utils/format'

const LIMIT = 50
const SEV_RANK = { critical: 3, error: 2, warning: 1, info: 0 }

export default function ReviewQueue() {
  const navigate = useNavigate()
  const [offset, setOffset] = useState(0)
  const [severity, setSeverity] = useState('')
  const [pack, setPack] = useState('')
  const q = useAsync(() => review.queue({ limit: LIMIT, offset }), [offset], { interval: 10000 })
  const m = useAsync(() => metrics.summary({ days: 7 }), [], { interval: 30000 })

  const rows = useMemo(() => {
    const items = q.data?.items || []
    return items.filter((it) => (!severity || it.max_severity === severity) && (!pack || it.rule_pack_key === pack))
  }, [q.data, severity, pack])
  const packs = useMemo(() => [...new Set((q.data?.items || []).map((i) => i.rule_pack_key).filter(Boolean))], [q.data])

  const columns = [
    {
      key: 'original_filename',
      label: 'Document',
      sortValue: (r) => r.original_filename.toLowerCase(),
      render: (r) => (
        <div>
          <div style={{ fontWeight: 600 }}>{r.original_filename}</div>
          <div className="micro muted">#{r.document_id} · {r.owner_name}</div>
        </div>
      ),
    },
    { key: 'rule_pack_key', label: 'Pack', sortValue: (r) => r.rule_pack_key || '', render: (r) => r.rule_pack_key?.toUpperCase() || '—', width: 80 },
    { key: 'min_confidence', label: 'Lowest confidence', sortValue: (r) => r.min_confidence ?? 1, render: (r) => fmtConfidence(r.min_confidence), width: 150 },
    { key: 'max_severity', label: 'Max severity', sortValue: (r) => SEV_RANK[r.max_severity] ?? -1, render: (r) => (r.max_severity ? <SeverityPill severity={r.max_severity} /> : '—'), width: 130 },
    { key: 'open_flags', label: 'Open flags', sortValue: (r) => r.open_flags, align: 'right', width: 100 },
    { key: 'routing_reason', label: 'Why it is here', render: (r) => <span className="small muted">{r.routing_reason}</span> },
    { key: 'status', label: 'Status', render: (r) => <StatusPill status={r.status} />, width: 130 },
    { key: 'waiting_since', label: 'Waiting', sortValue: (r) => r.waiting_since, render: (r) => <span className="muted nowrap">{fmtRelative(r.waiting_since)}</span>, width: 100 },
  ]

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <p className="eyebrow">Human in the loop</p>
          <h1 className="display display-h1">Review queue</h1>
        </div>
        <div className="row">
          <Button variant="secondary" to="/upload">
            Upload
          </Button>
        </div>
      </div>

      <section style={{ position: 'relative', marginBottom: 32 }}>
        <GlowBackground position="behind" soft />
        <div className="card above" style={{ display: 'flex', gap: 40, alignItems: 'center', flexWrap: 'wrap' }}>
          <Strip value={m.data ? `${m.data.flagged_this_week} of ${m.data.decided_this_week}` : '—'} label="documents needed review this week" />
          <Strip value={m.data ? `${m.data.auto_approved_pct.toFixed(0)}%` : '—'} label="auto-approval rate, all time" />
          <Strip value={q.data ? q.data.total : '—'} label="waiting in the queue now" />
          <Strip value={m.data?.reviewer_agreement_pct == null ? '—' : `${m.data.reviewer_agreement_pct.toFixed(0)}%`} label="flags reviewers confirmed" />
        </div>
      </section>

      <div className="card card-solid">
        <div className="card-head">
          <div className="filters">
            <label className="field">
              <span className="field-label">Severity</span>
              <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
                <option value="">Any</option>
                {['critical', 'error', 'warning', 'info'].map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="field-label">Rule pack</span>
              <select value={pack} onChange={(e) => setPack(e.target.value)}>
                <option value="">Any</option>
                {packs.map((p) => (
                  <option key={p} value={p}>{p.toUpperCase()}</option>
                ))}
              </select>
            </label>
          </div>
          <span className="small muted">Sorted lowest-confidence first — the most ambiguous documents need a human most.</span>
        </div>
        <DataTable
          columns={columns}
          rows={q.data ? rows : null}
          rowKey={(r) => r.document_id}
          loading={q.loading}
          error={q.error}
          onRetry={q.reload}
          defaultSort={{ key: 'min_confidence', dir: 'asc' }}
          onRowClick={(r) => navigate(`/review/${r.document_id}`)}
          empty={
            <EmptyState title={severity || pack ? 'No matches' : 'Queue is clear'}>
              {severity || pack ? 'Try loosening the filters.' : 'Everything uploaded so far was auto-approved or already reviewed.'}
            </EmptyState>
          }
        />
        <Pager total={q.data?.total} limit={LIMIT} offset={offset} onChange={setOffset} />
      </div>
    </div>
  )
}

function Strip({ value, label }) {
  return (
    <div>
      <div className="display display-h2" style={{ marginBottom: 2 }}>{value}</div>
      <div className="small muted">{label}</div>
    </div>
  )
}
