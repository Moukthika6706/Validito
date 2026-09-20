import { useState } from 'react'
import { rulePacks } from '../api/endpoints'
import Button from '../components/Button'
import DataTable from '../components/DataTable'
import { ErrorState, Field, JsonDetails, Loading, Notice } from '../components/States'
import { SeverityPill } from '../components/StatusPill'
import { useAsync } from '../hooks/useAsync'
import { fmtConfidence, fmtDate } from '../utils/format'

const SEVERITIES = ['info', 'warning', 'error', 'critical']

export default function AdminRulePacks() {
  const packs = useAsync(() => rulePacks.list({ include_inactive: true }), [])
  const [key, setKey] = useState(null)
  const [notice, setNotice] = useState(null)
  const active = (packs.data || []).filter((p) => p.is_active)
  const selectedKey = key || active[0]?.key
  const pack = useAsync(() => (selectedKey ? rulePacks.get(selectedKey) : Promise.resolve(null)), [selectedKey, packs.data])
  const versions = (packs.data || []).filter((p) => p.key === selectedKey)

  const changed = (msg) => {
    setNotice(msg)
    packs.reload(true)
  }
  const activate = async (id) => {
    try {
      await rulePacks.activate(id)
      changed({ tone: 'ok', text: 'Version activated. New validations use it; existing flags keep their snapshot.' })
    } catch (e) {
      setNotice({ tone: 'bad', text: e.detail || e.message })
    }
  }

  return (
    <div className="page page-dense">
      <div className="page-head" style={{ marginBottom: 24 }}>
        <div>
          <p className="eyebrow">Admin</p>
          <h1 className="display display-h1">Rule packs</h1>
          <p className="lede small" style={{ marginTop: 8 }}>
            Packs are versioned. Editing a rule cuts a new patch version and activates it; older versions stay for audit and can be re-activated.
          </p>
        </div>
        <div className="segmented">
          {active.map((p) => (
            <button key={p.key} className={p.key === selectedKey ? 'active' : ''} onClick={() => setKey(p.key)}>
              {p.key.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {notice && <Notice tone={notice.tone}>{notice.text}</Notice>}
      {packs.error && <ErrorState error={packs.error} onRetry={packs.reload} />}
      {pack.loading && !pack.data && <Loading label="Loading pack" />}

      {pack.data && (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 280px', gap: 16, alignItems: 'start' }}>
          <div className="stack">
            <div className="card card-solid card-tight">
              <div className="spread">
                <div>
                  <strong>{pack.data.name}</strong> <span className="pill pill-plain">v{pack.data.version}</span>
                  <div className="small muted">{pack.data.description}</div>
                </div>
                <dl className="kv small" style={{ gridTemplateColumns: '150px 1fr', minWidth: 360 }}>
                  <dt>Auto-approve threshold</dt>
                  <dd>{fmtConfidence(pack.data.config.routing.auto_approve_confidence)}</dd>
                  <dt>Blocking severities</dt>
                  <dd>{pack.data.config.routing.block_severities.join(', ')}</dd>
                  <dt>ML anomaly</dt>
                  <dd>{pack.data.config.ml.enabled ? `on · threshold ${pack.data.config.ml.anomaly_threshold}` : 'off'}</dd>
                </dl>
              </div>
            </div>
            <RuleTable title="Rules" packKey={pack.data.key} rules={pack.data.config.rules} onChanged={changed} />
            <RuleTable title="Cross-document rules" packKey={pack.data.key} rules={pack.data.config.cross_document_rules} onChanged={changed} />
          </div>
          <div className="stack">
            <div className="card card-solid card-tight">
              <p className="card-title">Versions</p>
              {versions.map((v) => (
                <div key={v.id} className="spread" style={{ padding: '8px 0', borderBottom: '1px solid var(--line)' }}>
                  <div>
                    <strong>v{v.version}</strong> {v.is_active && <span className="pill pill-ok">active</span>}
                    <div className="micro muted">{fmtDate(v.created_at)} · {v.rule_count} rules</div>
                  </div>
                  {!v.is_active && (
                    <Button variant="secondary" size="sm" onClick={() => activate(v.id)}>
                      Activate
                    </Button>
                  )}
                </div>
              ))}
            </div>
            <div className="card card-solid card-tight">
              <p className="card-title">Config</p>
              <JsonDetails value={pack.data.config} label="Full pack JSON" />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function RuleTable({ title, packKey, rules, onChanged }) {
  const [editing, setEditing] = useState(null)
  if (!rules.length) return null
  const columns = [
    {
      key: 'title',
      label: 'Rule',
      render: (r) => (
        <div style={{ opacity: r.enabled ? 1 : 0.5 }}>
          <div style={{ fontWeight: 600 }}>{r.title}</div>
          <div className="mono muted micro">{r.id}</div>
        </div>
      ),
    },
    {
      key: 'check',
      label: 'Check',
      width: 200,
      render: (r) => (
        <div className="micro">
          <span className="mono">{r.check}</span>
          {r.field && <div className="muted">field: {r.field}</div>}
        </div>
      ),
    },
    { key: 'severity', label: 'Severity', width: 110, render: (r) => <SeverityPill severity={r.severity} /> },
    { key: 'confidence', label: 'Confidence', width: 100, render: (r) => fmtConfidence(r.confidence) },
    { key: 'enabled', label: 'Active', width: 70, render: (r) => <Toggle rule={r} packKey={packKey} onChanged={onChanged} /> },
    { key: 'edit', label: '', width: 80, render: (r) => <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); setEditing(editing === r.id ? null : r.id) }}>{editing === r.id ? 'Close' : 'Edit'}</Button> },
  ]
  return (
    <div className="card card-solid card-tight">
      <p className="card-title">{title} · {rules.length}</p>
      <DataTable dense columns={columns} rows={rules} rowKey={(r) => r.id} />
      {editing && <RuleEditor rule={rules.find((r) => r.id === editing)} packKey={packKey} onDone={(m) => { setEditing(null); onChanged(m) }} onCancel={() => setEditing(null)} />}
    </div>
  )
}

function Toggle({ rule, packKey, onChanged }) {
  const [busy, setBusy] = useState(false)
  return (
    <input
      type="checkbox"
      checked={rule.enabled}
      disabled={busy}
      style={{ width: 'auto' }}
      onClick={(e) => e.stopPropagation()}
      onChange={async (e) => {
        setBusy(true)
        try {
          const res = await rulePacks.patchRule(packKey, rule.id, { enabled: e.target.checked })
          onChanged({ tone: 'ok', text: `${rule.id} ${e.target.checked ? 'enabled' : 'disabled'} — pack is now v${res.version}.` })
        } catch (err) {
          onChanged({ tone: 'bad', text: err.detail || err.message })
        } finally {
          setBusy(false)
        }
      }}
    />
  )
}

function RuleEditor({ rule, packKey, onDone, onCancel }) {
  const [form, setForm] = useState({ severity: rule.severity, confidence: rule.confidence, title: rule.title, explanation: rule.explanation })
  const [busy, setBusy] = useState(false)
  const save = async () => {
    setBusy(true)
    try {
      const res = await rulePacks.patchRule(packKey, rule.id, form)
      onDone({ tone: 'ok', text: `Saved ${rule.id} — pack is now v${res.version}.` })
    } catch (e) {
      onDone({ tone: 'bad', text: e.detail || e.message })
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="card card-quiet card-tight" style={{ marginTop: 12 }}>
      <p className="card-title">Editing {rule.id}</p>
      <div className="field-row">
        <Field label="Severity">
          <select value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })}>
            {SEVERITIES.map((s) => <option key={s}>{s}</option>)}
          </select>
        </Field>
        <Field label="Base confidence (0–1)">
          <input type="number" min="0" max="1" step="0.05" value={form.confidence} onChange={(e) => setForm({ ...form, confidence: Number(e.target.value) })} />
        </Field>
      </div>
      <Field label="Title">
        <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
      </Field>
      <Field label="Explanation template" hint="Braces are filled from the check's evidence, e.g. {value}, {raw}, {min}, {max}.">
        <textarea value={form.explanation} onChange={(e) => setForm({ ...form, explanation: e.target.value })} />
      </Field>
      <div className="row">
        <Button size="sm" loading={busy} onClick={save}>Save as new version</Button>
        <Button variant="ghost" size="sm" onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  )
}
