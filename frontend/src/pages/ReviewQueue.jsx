import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { review } from '../api/endpoints'
import { EmptyState, ErrorState, Loading, Pager, SeverityBadge } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { fmtConfidence, fmtRelative } from '../utils/format'

const LIMIT = 25

export default function ReviewQueue() {
  const navigate = useNavigate()
  const [offset, setOffset] = useState(0)
  const q = useAsync(() => review.queue({ limit: LIMIT, offset }), [offset], { interval: 10000 })

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Review queue</h1>
          <p>Documents the engine could not clear on its own — blocking errors or flags below the confidence threshold. Oldest first.</p>
        </div>
      </div>
      <div className="card">
        {q.loading && !q.data && <Loading />}
        {q.error && <ErrorState error={q.error} onRetry={q.reload} />}
        {q.data && q.data.items.length === 0 && <EmptyState title="Queue is empty">Everything uploaded so far was auto-approved or already reviewed.</EmptyState>}
        {q.data && q.data.items.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Document</th>
                  <th>Analyst</th>
                  <th>Pack</th>
                  <th>Open flags</th>
                  <th>Max severity</th>
                  <th>Lowest confidence</th>
                  <th>Why routed here</th>
                  <th>Waiting</th>
                </tr>
              </thead>
              <tbody>
                {q.data.items.map((it) => (
                  <tr key={it.document_id} className="clickable" onClick={() => navigate(`/review/${it.document_id}`)}>
                    <td>
                      <strong>{it.original_filename}</strong>
                      <div className="muted small">#{it.document_id}</div>
                    </td>
                    <td>{it.owner_name}</td>
                    <td>{it.rule_pack_key?.toUpperCase() || '—'}</td>
                    <td>{it.open_flags}</td>
                    <td>{it.max_severity ? <SeverityBadge severity={it.max_severity} /> : '—'}</td>
                    <td>{fmtConfidence(it.min_confidence)}</td>
                    <td className="small" style={{ maxWidth: 320 }}>
                      {it.routing_reason}
                    </td>
                    <td className="muted nowrap">{fmtRelative(it.waiting_since)}</td>
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
