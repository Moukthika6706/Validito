import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { documents, rulePacks } from '../api/endpoints'
import Button from '../components/Button'
import GlowBackground from '../components/GlowBackground'
import { Field, Notice } from '../components/States'
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
      navigate(`/review/${doc.id}`)
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
          <p className="eyebrow">New document</p>
          <h1 className="display display-h1">
            Upload a<br />term sheet
          </h1>
          <p className="lede">
            Extraction, rule checks, anomaly scoring and routing run in the background. You'll land on the review screen and watch it
            progress.
          </p>
          <ul className="small muted" style={{ paddingLeft: 18, lineHeight: 1.9 }}>
            <li>PDF, DOCX, or a scanned image (PNG / JPG / TIFF)</li>
            <li>Up to {MAX_MB} MB; scans take a little longer (OCR)</li>
            <li>Link a confirmation to run cross-document checks</li>
          </ul>
        </div>

        <form className="card" onSubmit={submit}>
          {error && <Notice tone="bad">{error}</Notice>}
          <div
            className={`dropzone ${drag ? 'active' : ''}`}
            onClick={() => inputRef.current.click()}
            onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files[0]) }}
          >
            <input ref={inputRef} type="file" accept={ACCEPT} hidden onChange={(e) => pick(e.target.files[0])} />
            {file ? (
              <>
                <div style={{ fontWeight: 600, color: 'var(--ink)' }}>{file.name}</div>
                <div className="small">{fmtBytes(file.size)} · click to change</div>
              </>
            ) : (
              <>
                <div style={{ fontWeight: 600, color: 'var(--ink)' }}>Drop a file here or click to browse</div>
                <div className="small">PDF · DOCX · PNG · JPG · TIFF</div>
              </>
            )}
          </div>

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
          <div className="row" style={{ marginTop: 8 }}>
            <Button size="lg" loading={busy} disabled={!file}>
              Upload and validate
            </Button>
            <Button variant="ghost" to="/">
              Cancel
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
