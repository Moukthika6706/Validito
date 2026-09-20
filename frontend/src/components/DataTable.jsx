import { useMemo, useState } from 'react'
import { SkeletonRows, EmptyState, ErrorState } from './States'

/**
 * Generic table with optional client-side sorting.
 * columns: [{ key, label, render?(row), sortValue?(row), width?, align? }]
 */
export default function DataTable({
  columns,
  rows,
  rowKey = (r) => r.id,
  onRowClick,
  loading,
  error,
  onRetry,
  empty,
  defaultSort,
  dense = false,
  expandable, // (row) => ReactNode
}) {
  const [sort, setSort] = useState(defaultSort || null) // { key, dir }
  const [open, setOpen] = useState(null)

  const sorted = useMemo(() => {
    if (!rows || !sort) return rows || []
    const col = columns.find((c) => c.key === sort.key)
    const get = col?.sortValue || ((r) => r[sort.key])
    return [...rows].sort((a, b) => {
      const va = get(a)
      const vb = get(b)
      if (va == null && vb == null) return 0
      if (va == null) return 1
      if (vb == null) return -1
      const cmp = typeof va === 'number' ? va - vb : String(va).localeCompare(String(vb))
      return sort.dir === 'asc' ? cmp : -cmp
    })
  }, [rows, sort, columns])

  const toggleSort = (key) => setSort((s) => (s?.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' }))

  if (loading && !rows) return <SkeletonRows />
  if (error) return <ErrorState error={error} onRetry={onRetry} />
  if (!rows || rows.length === 0) return empty || <EmptyState title="Nothing here yet" />

  return (
    <div className="table-wrap">
      <table className={dense ? 'table-dense' : ''}>
        <thead>
          <tr>
            {expandable && <th style={{ width: 28 }} />}
            {columns.map((c) => (
              <th key={c.key} style={{ width: c.width, textAlign: c.align }}>
                {c.sortValue || c.sortable ? (
                  <button className={`sort-btn ${sort?.key === c.key ? 'active' : ''}`} onClick={() => toggleSort(c.key)}>
                    {c.label} {sort?.key === c.key ? (sort.dir === 'asc' ? '↑' : '↓') : ''}
                  </button>
                ) : (
                  c.label
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => {
            const k = rowKey(row)
            const isOpen = open === k
            return (
              <FragmentRow key={k}>
                <tr
                  className={onRowClick || expandable ? 'clickable' : ''}
                  onClick={() => (expandable ? setOpen(isOpen ? null : k) : onRowClick && onRowClick(row))}
                >
                  {expandable && <td className="muted">{isOpen ? '▾' : '▸'}</td>}
                  {columns.map((c) => (
                    <td key={c.key} style={{ textAlign: c.align }}>
                      {c.render ? c.render(row) : row[c.key]}
                    </td>
                  ))}
                </tr>
                {expandable && isOpen && (
                  <tr>
                    <td colSpan={columns.length + 1} style={{ background: 'rgba(255,255,255,0.5)' }}>
                      {expandable(row)}
                    </td>
                  </tr>
                )}
              </FragmentRow>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function FragmentRow({ children }) {
  return <>{children}</>
}

export function Pager({ total, limit, offset, onChange }) {
  if (!total || total <= limit) return null
  const page = Math.floor(offset / limit) + 1
  const pages = Math.ceil(total / limit)
  return (
    <div className="pager">
      <button className="btn btn-secondary btn-sm" disabled={page <= 1} onClick={() => onChange(offset - limit)}>
        ‹ Prev
      </button>
      <span className="muted small">
        Page {page} of {pages} · {total} total
      </span>
      <button className="btn btn-secondary btn-sm" disabled={page >= pages} onClick={() => onChange(offset + limit)}>
        Next ›
      </button>
    </div>
  )
}
