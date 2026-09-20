import { useState } from 'react'
import { rulePacks } from '../api/endpoints'
import { Alert, ErrorState, JsonView, Loading, SeverityBadge } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { fmtConfidence, fmtDate } from '../utils/format'

const SEVERITIES = ['info', 'warning', 'error', 'critical']

export default function AdminRulePacks() {
  const packs = useAsync(() => rulePacks.list({ include_inactive: true }), [])
  const [key, setKey] = useState(null)
  const active = (packs.data || []).filter((p) => p.is_active)
  const selectedKey = key || active[0]?.key
  const pack = useAsync(() => (selectedKey ? rulePacks.get(selectedKey) : Promise.resolve(null)), [selectedKey, packs.data])
  const [notice, setNotice] = useState(null)

  const versions = (packs.data || []).filter((p) => p.key === selectedKey)

  const activate = async (id) => {
    try {
      await rulePacks.activate(id)
      setNotice({ tone: 'success', text: 'Version activated. New validations use it immediately; existing flags keep their rule snapshot.' })
      packs.reload(true)
    } catch (e) {
      setNotice({ tone: 'danger', text: e.detail || e.message })
    }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Rule packs</h1>
          <p>Each pack is versioned. Editing a rule cuts a new patch version and activates it; older versions stay for audit and can be re-activated.</p>
        </div>
        <div className="toolbar">
          {active.map((p) => (
            <button key={p.key} className={`btn ${p.key === selectedKey ? 'btn-primary' : ''}`} onClick={() => setKey(p.key)}>
              {p.name}
            </button>
          ))}
        </div>
      </div>
      {notice && <Alert tone={notice.tone}>{notice.text}</Alert>}
      {packs.error && <ErrorState error={packs.error} onRetry={packs.reload} />}
      {pack.loading && !pack.data && <Loading />}
      {pack.data && (
        <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 1fr) 300px' }}>
          <div>
            <div className="card">
              <div className="card-header">
                <div>
                  <h2 style={{ margin: 0 }}>
                    {pack.data.name} <span className="badge badge-info">v{pack.data.version}</span>
                  </h2>
                  <p className="muted small">{pack.data.description}</p>
                </div>
              </div>
              <dl className="kv">
                <dt>Auto-approve threshold</dt>
                <dd>{fmtConfidence(pack.data.config.routing.auto_approve_confidence)} — flags below this confidence route to review</dd>
                <dt>Blocking severities</dt>
                <dd>{pack.data.config.routing.block_severities.join(', ')}</dd>
                <dt>Score floor</dt>
                <dd>{pack.data.config.routing.min_auto_approve_score}</dd>
                <dt>ML anomaly</dt>
                <dd>
                  {pack.data.config.ml.enabled ? `enabled · threshold ${pack.data.config.ml.anomaly_threshold} · severity ${pack.data.config.ml.severity}` : 'disabled'}
                </dd>
              </dl>
            </div>
            <RuleTable title={`Rules (${pack.data.config.rules.length})`} packKey={pack.data.key} rules={pack.data.config.rules} onChanged={(msg) => { setNotice(msg); packs.reload(true) }} />
            <RuleTable title={`Cross-document rules (${pack.data.config.cross_document_rules.length})`} packKey={pack.data.key} rules={pack.data.config.cross_document_rules} onChanged={(msg) => { setNotice(msg); packs.reload(true) }} />
          </div>
          <div>
            <div className="card">
              <h2>Versions</h2>
              {versions.map((v) => (
                <div key={v.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
                  <div>
                    <strong>v{v.version}</strong> {v.is_active && <span className="badge badge-success">active</span>}
                    <div className="muted small">{fmtDate(v.created_at)} · {v.rule_count} rules</div>
                  </div>
                  {!v.is_active && (
                    <button className="btn btn-sm" onClick={() => activate(v.id)}>
                      Activate
                    </button>
                  )}
                </div>
              ))}
            </div>
            <div className="card">
              <h2>Full config</h2>
              <JsonView value={pack.data.config} collapsed label="YAML-equivalent JSON" />
            </div>
          </div>
        </div>
      )}
    </>
  )
}

function RuleTable({ title, packKey, rules, onChanged }) {
  const [editing, setEditing] = useState(null)
  if (rules.length === 0) return null
  return (
    <div className="card">
      <h2>{title}</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Rule</th>
              <th>Check</th>
              <th>Severity</th>
              <th>Confidence</th>
              <th>Enabled</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rules.map((r) => (
              <RuleRow key={r.id} rule={r} packKey={packKey} editing={editing === r.id} onEdit={() => setEditing(editing === r.id ? null : r.id)} onChanged={(m) => { setEditing(null); onChanged(m) }} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function RuleRow({ rule, packKey, editing, onEdit, onChanged }) {
  const [form, setForm] = useState({ severity: rule.severity, confidence: rule.confidence, enabled: rule.enabled, title: rule.title, explanation: rule.explanation })
  const [busy, setBusy] = useState(false)

  const save = async (patch) => {
    setBusy(true)
    try {
      const res = await rulePacks.patchRule(packKey, rule.id, patch)
      onChanged({ tone: 'success', text: `Saved ${rule.id} — pack is now v${res.version}.` })
    } catch (e) {
      onChanged({ tone: 'danger', text: e.detail || e.message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <tr style={{ opacity: rule.enabled ? 1 : 0.55 }}>
        <td>
          <strong>{rule.title}</strong>
          <div className="mono muted">{rule.id}</div>
          <div className="small muted" style={{ maxWidth: 480 }}>
            {rule.explanation}
          </div>
        </td>
        <td>
          <span className="mono">{rule.check}</span>
          {rule.field && <div className="muted small">field: {rule.field}</div>}
          {rule.params && Object.keys(rule.params).length > 0 && <div className="mono muted small">{JSON.stringify(rule.params)}</div>}
        </td>
        <td>
          <SeverityBadge severity={rule.severity} />
        </td>
        <td>{fmtConfidence(rule.confidence)}</td>
        <td>
          <input type="checkbox" checked={rule.enabled} disabled={busy} onChange={(e) => save({ enabled: e.target.checked })} />
        </td>
        <td>
          <button className="btn btn-sm" onClick={onEdit}>
            {editing ? 'Close' : 'Edit'}
          </button>
        </td>
      </tr>
      {editing && (
        <tr>
          <td colSpan={6} style={{ background: '#f8fafc' }}>
            <div className="grid grid-2">
              <label className="field">
                <span className="field-label">Severity</span>
                <select value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })}>
                  {SEVERITIES.map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="field-label">Base confidence (0–1)</span>
                <input type="number" min="0" max="1" step="0.05" value={form.confidence} onChange={(e) => setForm({ ...form, confidence: Number(e.target.value) })} />
              </label>
            </div>
            <label className="field">
              <span className="field-label">Title</span>
              <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
            </label>
            <label className="field">
              <span className="field-label">Explanation template</span>
              <textarea value={form.explanation} onChange={(e) => setForm({ ...form, explanation: e.target.value })} />
              <span className="field-hint">Placeholders in braces (e.g. {'{value}'}, {'{raw}'}) are filled from the check's evidence.</span>
            </label>
            <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => save(form)}>
              {busy ? 'Saving…' : 'Save as new version'}
            </button>
          </td>
        </tr>
      )}
    </>
  )
}
