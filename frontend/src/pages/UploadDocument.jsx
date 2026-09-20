import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { documents, rulePacks } from '../api/endpoints'
import { Alert, Field } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { fmtBytes } from '../utils/format'

const ACCEPT = '.pdf,.docx,.png,.jpg,.jpeg,.tif,.tiff'
const MAX_MB = 25

export default function UploadDocument() {
  const navigate = useNavigate()
  const packs = useAsync(() => rulePacks.list(), [])
  const candidates = useAsync(() => documents.list({ limit: 100 }), [])
  const [file, setFile] = useState(null)
  const [docType, setDocType] = useState('term_sheet')
  const [pack, setPack] = useState('')
  const [related, setRelated] = useState('')
  const [drag, setDrag] = useState(false)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const inputRef = useRef()

  const pick = (f) => {
    setError(null)
    if (!f) return
    const ext = f.name.split('.').pop().toLowerCase()
    if (!ACCEPT.includes(`.${ext}`)) return setError(`Unsupported file type .${ext}. Use PDF, DOCX, PNG, JPG or TIFF.`)
    if (f.size > MAX_MB * 1024 * 1024) return setError(`File is ${fmtBytes(f.size)}; the limit is ${MAX_MB} MB.`)
    setFile(f)
  }

  const submit = async (e) => {
    e.preventDefault()
    if (!file) return setError('Choose a file first.')
    setBusy(true)
    setError(null)
    try {
      const doc = await documents.upload({ file, doc_type: docType, rule_pack_key: pack || null, related_document_id: related || null })
      navigate(`/documents/${doc.id}`, { state: { justUploaded: true } })
    } catch (err) {
      setError(err.detail || err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Upload a term sheet</h1>
          <p>Processing runs in the background: text extraction (OCR for scans), clause extraction, rule checks, anomaly scoring, then routing.</p>
        </div>
      </div>
      <form className="card" onSubmit={submit} style={{ maxWidth: 720 }}>
        {error && <Alert tone="danger">{error}</Alert>}
        <div
          className={`dropzone ${drag ? 'active' : ''}`}
          onClick={() => inputRef.current.click()}
          onDragOver={(e) => {
            e.preventDefault()
            setDrag(true)
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDrag(false)
            pick(e.dataTransfer.files[0])
          }}
        >
          <input ref={inputRef} type="file" accept={ACCEPT} hidden onChange={(e) => pick(e.target.files[0])} />
          {file ? (
            <>
              <strong>{file.name}</strong>
              <div className="muted small">{fmtBytes(file.size)} · click to change</div>
            </>
          ) : (
            <>
              <strong>Drop a file here or click to browse</strong>
              <div className="small">PDF, DOCX, or a scanned image (PNG / JPG / TIFF) up to {MAX_MB} MB</div>
            </>
          )}
        </div>

        <div className="grid grid-2" style={{ marginTop: 16 }}>
          <Field label="Document type">
            <select value={docType} onChange={(e) => setDocType(e.target.value)}>
              <option value="term_sheet">Term sheet</option>
              <option value="confirmation">Confirmation</option>
              <option value="other">Other</option>
            </select>
          </Field>
          <Field label="Rule pack" hint="Leave on auto-detect to pick ISDA / LMA from the document's content.">
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
        <Field label="Compare against (optional)" hint="Link a related document — e.g. the confirmation for this term sheet — to run cross-document consistency checks.">
          <select value={related} onChange={(e) => setRelated(e.target.value)}>
            <option value="">None</option>
            {(candidates.data?.items || []).map((d) => (
              <option key={d.id} value={d.id}>
                #{d.id} · {d.original_filename} ({d.status.replace('_', ' ')})
              </option>
            ))}
          </select>
        </Field>
        <div className="btn-group">
          <button className="btn btn-primary" disabled={busy || !file}>
            {busy ? 'Uploading…' : 'Upload and validate'}
          </button>
          <Link className="btn" to="/documents">
            Cancel
          </Link>
        </div>
      </form>
    </>
  )
}
