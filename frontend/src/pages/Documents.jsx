import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { documents } from '../api/endpoints'
import { EmptyState, ErrorState, Loading, Pager, StatusBadge } from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { useAsync } from '../hooks/useAsync'
import { fmtBytes, fmtDate, humanize } from '../utils/format'

const STATUSES = ['uploaded', 'processing', 'extracted', 'validated', 'auto_approved', 'needs_review', 'reviewed', 'failed']
const LIMIT = 25

export default function Documents() {
  const navigate = useNavigate()
  const { isReviewer } = useAuth()
  const [status, setStatus] = useState('')
  const [offset, setOffset] = useState(0)
  const list = useAsync(() => documents.list({ status: status || undefined, limit: LIMIT, offset }), [status, offset], {
    interval: 5000,
    shouldPoll: (d) => d?.items?.some((x) => ['uploaded', 'processing', 'extracted', 'validated'].includes(x.status)),
  })

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Documents</h1>
          <p>{isReviewer ? 'All uploads across the team.' : 'Your uploads and their validation status.'}</p>
        </div>
        <div className="toolbar">
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value)
              setOffset(0)
            }}
          >
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </select>
          <Link className="btn btn-primary" to="/documents/new">
            Upload
          </Link>
        </div>
      </div>

      <div className="card">
        {list.loading && !list.data && <Loading />}
        {list.error && <ErrorState error={list.error} onRetry={list.reload} />}
        {list.data && list.data.items.length === 0 && (
          <EmptyState title={status ? `No ${humanize(status).toLowerCase()} documents` : 'No documents yet'} action={!status && <Link className="btn btn-primary" to="/documents/new">Upload a term sheet</Link>}>
            {status ? 'Try a different status filter.' : 'Uploads appear here with live processing status.'}
          </EmptyState>
        )}
        {list.data && list.data.items.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>File</th>
                  <th>Type</th>
                  <th>Rule pack</th>
                  <th>Status</th>
                  <th>Pages</th>
                  <th>Size</th>
                  <th>Uploaded</th>
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((d) => (
                  <tr key={d.id} className="clickable" onClick={() => navigate(`/documents/${d.id}`)}>
                    <td>
                      {d.original_filename}
                      {d.ocr_used && <span className="badge badge-outline" style={{ marginLeft: 6 }}>OCR</span>}
                    </td>
                    <td>{humanize(d.doc_type)}</td>
                    <td>{d.rule_pack_key ? d.rule_pack_key.toUpperCase() : <span className="muted">auto-detect</span>}</td>
                    <td>
                      <StatusBadge status={d.status} outcome={d.review_outcome} />
                    </td>
                    <td>{d.page_count ?? '—'}</td>
                    <td>{fmtBytes(d.size_bytes)}</td>
                    <td className="muted nowrap">{fmtDate(d.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pager total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
          </div>
        )}
      </div>
    </>
  )
}
