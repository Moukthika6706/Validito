import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { documents, rulePacks } from '../api/endpoints'
import Button from '../components/Button'
import GlowBackground from '../components/GlowBackground'
import { Field, Notice } from '../components/States'
import { StatusPill } from '../components/StatusPill'
import { useAsync } from '../hooks/useAsync'
import { fmtBytes } from '../utils/format'

const ACCEPT = '.pdf,.docx,.png,.jpg,.jpeg,.tif,.tiff'
const MAX_MB = 25
const MAX_FILES = 20
const POLL_MS = 2000
const AMENDABLE = ['notional_amount', 'effective_date', 'maturity_date', 'interest_rate', 'margin', 'commitment_fee', 'counterparty', 'governing_law', 'settlement_terms', 'payment_frequency', 'forward_rate', 'value_date', 'currency_pair', 'credit_support', 'repayment_terms']

export default function UploadDocument() {
  const packs = useAsync(() => rulePacks.list(), [])
  const candidates = useAsync(() => documents.list({ limit: 100 }), [])
  const [files, setFiles] = useState([]) // File[]
  const [docType, setDocType] = useState('term_sheet')
  const [pack, setPack] = useState('')
  const [related, setRelated] = useState('')
  const [amendmentOf, setAmendmentOf] = useState('')
  const [amended, setAmended] = useState([])
  const [drag, setDrag] = useState(false)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [batch, setBatch] = useState(null) // results from the server
  const inputRef = useRef()

  const addFiles = (list) => {
    setError(null)
    const next = [...files]
    const problems = []
    for (const f of Array.from(list || [])) {
      const ext = f.name.split('.').pop().toLowerCase()
      if (!ACCEPT.includes(`.${ext}`)) problems.push(`${f.name}: unsupported type .${ext}`)
      else if (f.size > MAX_MB * 1024 * 1024) problems.push(`${f.name}: ${fmtBytes(f.size)} exceeds ${MAX_MB} MB`)
      else if (next.some((x) => x.name === f.name && x.size === f.size)) problems.push(`${f.name}: already added`)
      else if (next.length >= MAX_FILES) problems.push(`${f.name}: batch limit is ${MAX_FILES} files`)
      else next.push(f)
    }
    setFiles(next)
    if (problems.length) setError(problems.join(' · '))
  }
  const removeFile = (i) => setFiles((fs) => fs.filter((_, idx) => idx !== i))

  const submit = async (e) => {
    e.preventDefault()
    if (!files.length) return setError('Add at least one file.')
    setBusy(true)
    setError(null)
    try {
      if (files.length === 1) {
        const doc = await documents.upload({ file: files[0], doc_type: docType, rule_pack_key: pack || null, related_document_id: related || null, amendment_of_id: amendmentOf || null, amended_fields: amended })
        setBatch({ accepted: 1, rejected: 0, results: [{ filename: files[0].name, accepted: true, document_id: doc.id, status: doc.status, reason: null }] })
      } else {
        setBatch(await documents.bulkUpload({ files, doc_type: docType, rule_pack_key: pack || null }))
      }
      setFiles([])
    } catch (err) {
      setError(err.detail || err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page" style={{ maxWidth: 1080 }}>
      <GlowBackground position="corner" soft />
      <div className="above" style={{ display: 'grid', gridTemplateColumns: '1fr 1.2fr', gap: 56, alignItems: 'start' }}>
        <div>
          <p className="eyebrow">New documents</p>
          <h1 className="display display-h1">
            Upload
            <br />
            term sheets
          </h1>
          <p className="lede">
            Drop one file or a whole batch. Each document is queued on its own: extraction, rule checks, anomaly scoring and routing
            run in the background and the list below updates live.
          </p>
          <ul className="small muted" style={{ paddingLeft: 18, lineHeight: 1.9 }}>
            <li>PDF, DOCX, or a scanned image (PNG / JPG / TIFF)</li>
            <li>Up to {MAX_MB} MB each, {MAX_FILES} files per batch; scans take longer (OCR)</li>
            <li>Linking a related document is available for single uploads</li>
          </ul>
        </div>

        <div className="stack">
          <form className="card" onSubmit={submit}>
            {error && <Notice tone="bad">{error}</Notice>}
            <div
              className={`dropzone ${drag ? 'active' : ''}`}
              onClick={() => inputRef.current.click()}
              onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files) }}
            >
              <input ref={inputRef} type="file" accept={ACCEPT} multiple hidden onChange={(e) => { addFiles(e.target.files); e.target.value = '' }} />
              <div style={{ fontWeight: 600, color: 'var(--ink)' }}>{files.length ? `${files.length} file${files.length === 1 ? '' : 's'} ready — drop more or click to add` : 'Drop files here or click to browse'}</div>
              <div className="small">PDF · DOCX · PNG · JPG · TIFF</div>
            </div>

            {files.length > 0 && (
              <div className="stack" style={{ marginTop: 12, gap: 6 }}>
                {files.map((f, i) => (
                  <div key={`${f.name}-${f.size}`} className="spread small" style={{ padding: '6px 10px', background: 'var(--surface-muted)', borderRadius: 10 }}>
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.name} <span className="muted">· {fmtBytes(f.size)}</span></span>
                    <button type="button" className="link micro" onClick={() => removeFile(i)}>remove</button>
                  </div>
                ))}
              </div>
            )}

            <div className="field-row" style={{ marginTop: 20 }}>
              <Field label="Document type">
                <select value={docType} onChange={(e) => setDocType(e.target.value)}>
                  <option value="term_sheet">Term sheet</option>
                  <option value="confirmation">Confirmation</option>
                  <option value="other">Other</option>
                </select>
              </Field>
              <Field label="Rule pack" hint="Auto-detect picks ISDA / LMA from the content.">
                <select value={pack} onChange={(e) => setPack(e.target.value)}>
                  <option value="">Auto-detect</option>
                  {(packs.data || []).map((p) => (
                    <option key={p.key} value={p.key}>
                      {p.name} (v{p.version})
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            {files.length <= 1 && (
              <Field label="Amendment of (optional)" hint="Link the original this document amends, then tick the terms the amendment changes. Changes to anything else are flagged.">
                <select value={amendmentOf} onChange={(e) => { setAmendmentOf(e.target.value); if (!e.target.value) setAmended([]) }}>
                  <option value="">None</option>
                  {(candidates.data?.items || []).map((d) => (
                    <option key={d.id} value={d.id}>#{d.id} · {d.original_filename}</option>
                  ))}
                </select>
                {amendmentOf && (
                  <div className="row" style={{ gap: 6, marginTop: 8 }}>
                    {AMENDABLE.map((f) => (
                      <label key={f} className={`pill ${amended.includes(f) ? 'pill-info' : 'pill-plain'}`} style={{ cursor: 'pointer' }}>
                        <input type="checkbox" hidden checked={amended.includes(f)} onChange={(e) => setAmended((a) => (e.target.checked ? [...a, f] : a.filter((x) => x !== f)))} />
                        {f.replace(/_/g, ' ')}
                      </label>
                    ))}
                  </div>
                )}
              </Field>
            )}
            {files.length <= 1 && (
              <Field label="Compare against (optional)" hint="e.g. the confirmation for this term sheet.">
                <select value={related} onChange={(e) => setRelated(e.target.value)}>
                  <option value="">None</option>
                  {(candidates.data?.items || []).map((d) => (
                    <option key={d.id} value={d.id}>
                      #{d.id} · {d.original_filename}
                    </option>
                  ))}
                </select>
              </Field>
            )}
            <div className="row" style={{ marginTop: 8 }}>
              <Button size="lg" loading={busy} disabled={!files.length}>
                {files.length > 1 ? `Upload ${files.length} files` : 'Upload and validate'}
              </Button>
              <Button variant="ghost" to="/">
                Done
              </Button>
            </div>
          </form>

          {batch && <ProgressList batch={batch} />}
        </div>
      </div>
    </div>
  )
}

/** Live status for an uploaded batch: polls /documents/status until every row is terminal. */
function ProgressList({ batch }) {
  const ids = batch.results.filter((r) => r.accepted).map((r) => r.document_id)
  const [rows, setRows] = useState({}) // id -> status snapshot
  const [retrying, setRetrying] = useState(null)
  const allTerminal = ids.length > 0 && ids.every((id) => rows[id]?.terminal)

  useEffect(() => {
    if (!ids.length) return undefined
    let cancelled = false
    const tick = async () => {
      try {
        const snap = await documents.status(ids)
        if (!cancelled) setRows(Object.fromEntries(snap.map((s) => [s.id, s])))
      } catch {
        /* transient; next tick retries */
      }
    }
    tick()
    const timer = setInterval(() => {
      if (!allTerminal) tick()
    }, POLL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batch, allTerminal])

  const retry = async (id) => {
    setRetrying(id)
    try {
      await documents.reprocess(id)
      setRows((r) => ({ ...r, [id]: { ...r[id], status: 'queued', terminal: false, error_message: null } }))
    } finally {
      setRetrying(null)
    }
  }

  const done = ids.filter((id) => rows[id]?.terminal).length
  return (
    <div className="card card-solid">
      <div className="card-head">
        <p className="card-title">
          Batch progress · {done}/{ids.length} finished{batch.rejected ? ` · ${batch.rejected} rejected` : ''}
        </p>
        {!allTerminal && ids.length > 0 && <span className="spinner" />}
      </div>
      <div className="stack" style={{ gap: 6 }}>
        {batch.results.map((r) => {
          const s = r.accepted ? rows[r.document_id] : null
          return (
            <div key={r.filename + (r.document_id || '')} className="activity-row" style={{ gridTemplateColumns: 'minmax(0,1fr) 150px auto', cursor: 'default' }}>
              <div style={{ minWidth: 0 }}>
                <div className="activity-name">{r.filename}</div>
                <div className="activity-meta">
                  {!r.accepted && <span style={{ color: 'var(--bad)' }}>{r.reason}</span>}
                  {s?.status === 'failed' && <span style={{ color: 'var(--bad)' }}>Failed during {s.failed_stage}: {s.error_message}</span>}
                  {s && s.status !== 'failed' && !s.terminal && 'Processing in the background…'}
                  {s?.terminal && s.status !== 'failed' && `Decision: ${s.routing_decision?.replace('_', ' ') || s.status.replace('_', ' ')}`}
                </div>
              </div>
              <div>{r.accepted ? <StatusPill status={s?.status || r.status} /> : <span className="pill pill-bad">Rejected</span>}</div>
              <div className="row" style={{ gap: 6 }}>
                {s?.status === 'failed' && (
                  <Button variant="secondary" size="sm" loading={retrying === r.document_id} onClick={() => retry(r.document_id)}>
                    Retry
                  </Button>
                )}
                {r.accepted && (
                  <Link className="btn btn-ghost btn-sm" to={`/review/${r.document_id}`}>
                    Open ›
                  </Link>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
