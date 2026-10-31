import { useEffect, useMemo, useRef, useState } from 'react'
import { tokenStore } from '../api/client'
import { documents } from '../api/endpoints'
import { Loading } from './States'

const SEV_COLOR = {
  critical: 'var(--crit)',
  error: 'var(--bad)',
  warning: 'var(--warn)',
  info: 'var(--info)',
}

/**
 * Renders a document's pages as images with overlay rectangles for flagged spans.
 * `highlights`: [{ id, flagId, severity, boxes: [{page,x0,y0,x1,y1}], label }]
 * `activeId` pulses that highlight and scrolls it into view; `onSelect(flagId)` fires on click.
 */
export default function PageViewer({ documentId, highlights, activeId, onSelect, onUnrenderable }) {
  const [info, setInfo] = useState(null)
  const [urls, setUrls] = useState({}) // page number -> object URL
  const [error, setError] = useState(null)
  const container = useRef(null)

  useEffect(() => {
    let cancelled = false
    const created = []
    ;(async () => {
      try {
        const meta = await documents.pages(documentId)
        if (cancelled) return
        setInfo(meta)
        if (!meta.renderable) {
          onUnrenderable?.(meta.note)
          return
        }
        const token = tokenStore.get()
        for (const p of meta.pages) {
          const res = await fetch(`${import.meta.env.VITE_API_URL || ''}/api/v1/documents/${documentId}/pages/${p.number}.png?dpi=110`, { headers: { Authorization: `Bearer ${token}` } })
          if (!res.ok) throw new Error(`Page ${p.number} failed to render (${res.status})`)
          const url = URL.createObjectURL(await res.blob())
          created.push(url)
          if (cancelled) break
          setUrls((u) => ({ ...u, [p.number]: url }))
        }
      } catch (e) {
        if (!cancelled) setError(e.message)
      }
    })()
    return () => {
      cancelled = true
      created.forEach((u) => URL.revokeObjectURL(u))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId])

  const byPage = useMemo(() => {
    const map = {}
    for (const h of highlights || []) {
      for (const b of h.boxes || []) {
        ;(map[b.page] ||= []).push({ ...h, box: b })
      }
    }
    return map
  }, [highlights])

  useEffect(() => {
    if (!activeId || !container.current) return
    const el = container.current.querySelector(`[data-hl="${activeId}"]`)
    if (el) el.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [activeId, urls])

  if (error) return <div className="state"><p className="state-error small">{error}</p></div>
  if (!info) return <Loading label="Loading pages" />
  if (!info.renderable) return null

  return (
    <div className="pages" ref={container}>
      {info.pages.map((p) => (
        <div key={p.number} className="page-frame" style={{ aspectRatio: `${p.width} / ${p.height}` }}>
          {urls[p.number] ? <img src={urls[p.number]} alt={`page ${p.number}`} draggable={false} /> : <div className="page-skeleton" />}
          {(byPage[p.number] || []).map((h) => (
            <button
              key={`${h.id}-${h.box.y0}`}
              type="button"
              data-hl={h.id}
              className={`hl ${h.id === activeId ? 'hl-active' : ''}`}
              title={h.label}
              style={{
                left: `${h.box.x0 * 100}%`,
                top: `${h.box.y0 * 100}%`,
                width: `${(h.box.x1 - h.box.x0) * 100}%`,
                height: `${(h.box.y1 - h.box.y0) * 100}%`,
                '--hl': SEV_COLOR[h.severity] || 'var(--glow-1)',
              }}
              onClick={() => onSelect?.(h.flagId)}
            />
          ))}
          <span className="page-num">{p.number} / {info.page_count}</span>
        </div>
      ))}
    </div>
  )
}
