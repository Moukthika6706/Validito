import { Link, useNavigate } from 'react-router-dom'
import { documents, metrics } from '../api/endpoints'
import { EmptyState, ErrorState, Loading, StatTile, StatusBadge } from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { useAsync } from '../hooks/useAsync'
import { fmtPct, fmtRelative, humanize } from '../utils/format'

export default function Dashboard() {
  const { user, isReviewer } = useAuth()
  const navigate = useNavigate()
  const m = useAsync(() => metrics.summary({ days: 14 }), [], { interval: 20000 })
  const recent = useAsync(() => documents.list({ limit: 8 }), [], { interval: 10000 })

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Dashboard</h1>
          <p>{isReviewer ? 'Portfolio-wide validation activity.' : `Your validation activity, ${user.full_name.split(' ')[0]}.`}</p>
        </div>
        <div className="toolbar">
          <Link className="btn btn-primary" to="/documents/new">
            Upload term sheet
          </Link>
          {isReviewer && (
            <Link className="btn" to="/review">
              Open review queue
            </Link>
          )}
        </div>
      </div>

      {m.loading && !m.data && <Loading />}
      {m.error && <ErrorState error={m.error} onRetry={m.reload} />}
      {m.data && (
        <>
          <div className="grid grid-4">
            <StatTile label="Documents processed" value={m.data.documents_total} hint={`${m.data.decided_total} reached a decision`} />
            <StatTile
              label="Auto-approved"
              value={fmtPct(m.data.auto_approved_pct, 1)}
              tone="success"
              hint={`${m.data.auto_approved_total} of ${m.data.decided_total} needed no human review`}
            />
            <StatTile
              label="Manual review reduction"
              value={fmtPct(m.data.manual_review_reduction_pct, 1)}
              tone="success"
              hint="Share of documents a reviewer never had to open"
            />
            <StatTile
              label="Avg time to decision"
              value={m.data.avg_processing_seconds == null ? '—' : `${m.data.avg_processing_seconds.toFixed(1)}s`}
              hint="Upload → routing decision"
            />
          </div>

          <div className="grid grid-3" style={{ marginTop: 16 }}>
            <div className="card">
              <h2>Flags by severity</h2>
              <Bars data={m.data.flags_by_severity} order={['critical', 'error', 'warning', 'info']} />
              <p className="muted small" style={{ marginTop: 8 }}>
                Avg {m.data.avg_flags_per_document} flags per decided document.
              </p>
            </div>
            <div className="card">
              <h2>Flags by source</h2>
              <Bars data={m.data.flags_by_source} order={['rule', 'cross_doc', 'ml']} labels={{ rule: 'Rule pack', cross_doc: 'Cross-doc', ml: 'ML anomaly' }} />
              <p className="muted small" style={{ marginTop: 8 }}>
                Reviewer agreement: {m.data.reviewer_agreement_pct == null ? 'no reviews yet' : fmtPct(m.data.reviewer_agreement_pct, 0)}
              </p>
            </div>
            <div className="card">
              <h2>Most triggered rules</h2>
              {m.data.top_rules.length === 0 ? (
                <p className="muted">No flags yet.</p>
              ) : (
                <table>
                  <tbody>
                    {m.data.top_rules.slice(0, 6).map((r) => (
                      <tr key={r.rule_id}>
                        <td>
                          <div>{r.title}</div>
                          <div className="mono muted">{r.rule_id}</div>
                        </td>
                        <td className="right nowrap">
                          {r.count}
                          {r.accepted + r.rejected > 0 && (
                            <div className="muted small">
                              {r.accepted}✓ {r.rejected}✗
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </>
      )}

      <div className="card">
        <div className="card-header">
          <h2>Recent documents</h2>
          <Link to="/documents">View all</Link>
        </div>
        {recent.loading && !recent.data && <Loading />}
        {recent.error && <ErrorState error={recent.error} onRetry={recent.reload} />}
        {recent.data && recent.data.items.length === 0 && (
          <EmptyState title="No documents yet" action={<Link className="btn btn-primary" to="/documents/new">Upload your first term sheet</Link>}>
            Upload a PDF, DOCX or scanned image and Validito will extract the key terms and validate them.
          </EmptyState>
        )}
        {recent.data && recent.data.items.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>File</th>
                <th>Pack</th>
                <th>Status</th>
                <th>Uploaded</th>
              </tr>
            </thead>
            <tbody>
              {recent.data.items.map((d) => (
                <tr key={d.id} className="clickable" onClick={() => navigate(`/documents/${d.id}`)}>
                  <td>{d.original_filename}</td>
                  <td>{d.rule_pack_key ? d.rule_pack_key.toUpperCase() : <span className="muted">auto</span>}</td>
                  <td>
                    <StatusBadge status={d.status} outcome={d.review_outcome} />
                  </td>
                  <td className="muted">{fmtRelative(d.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}

function Bars({ data, order, labels = {} }) {
  const entries = order.filter((k) => data[k]).map((k) => [k, data[k]])
  if (entries.length === 0) return <p className="muted">Nothing flagged.</p>
  const max = Math.max(...entries.map(([, v]) => v))
  return (
    <div className="progress-bars">
      {entries.map(([k, v]) => (
        <div className="bar" key={k}>
          <span>{labels[k] || humanize(k)}</span>
          <div className="bar-track">
            <div className="bar-fill" style={{ width: `${(v / max) * 100}%` }} />
          </div>
          <span className="right">{v}</span>
        </div>
      ))}
    </div>
  )
}
