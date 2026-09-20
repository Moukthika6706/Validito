import { useState } from 'react'
import { users } from '../api/endpoints'
import Button from '../components/Button'
import DataTable from '../components/DataTable'
import { Field, Notice } from '../components/States'
import { RolePill } from '../components/StatusPill'
import { useAuth } from '../context/AuthContext'
import { useAsync } from '../hooks/useAsync'
import { fmtDate } from '../utils/format'

const ROLES = ['analyst', 'reviewer', 'admin']

export default function AdminUsers() {
  const { user: me } = useAuth()
  const list = useAsync(() => users.list(), [])
  const [notice, setNotice] = useState(null)
  const [form, setForm] = useState({ full_name: '', email: '', password: '', role: 'analyst' })
  const [busy, setBusy] = useState(false)

  const update = async (id, patch) => {
    try {
      await users.update(id, patch)
      setNotice({ tone: 'ok', text: 'User updated.' })
      list.reload(true)
    } catch (e) {
      setNotice({ tone: 'bad', text: e.detail || e.message })
    }
  }
  const create = async (e) => {
    e.preventDefault()
    setBusy(true)
    try {
      await users.create(form)
      setForm({ full_name: '', email: '', password: '', role: 'analyst' })
      setNotice({ tone: 'ok', text: 'User created.' })
      list.reload(true)
    } catch (err) {
      setNotice({ tone: 'bad', text: err.detail || err.message })
    } finally {
      setBusy(false)
    }
  }

  const columns = [
    { key: 'full_name', label: 'Name', sortValue: (r) => r.full_name, render: (r) => <span>{r.full_name} {r.id === me.id && <span className="pill pill-plain">you</span>}</span> },
    { key: 'email', label: 'Email', sortValue: (r) => r.email },
    {
      key: 'role', label: 'Role', width: 150,
      render: (r) => r.id === me.id ? <RolePill role={r.role} /> : (
        <select value={r.role} style={{ padding: '6px 10px' }} onChange={(e) => update(r.id, { role: e.target.value })}>
          {ROLES.map((x) => <option key={x}>{x}</option>)}
        </select>
      ),
    },
    { key: 'is_active', label: 'Active', width: 80, render: (r) => <input type="checkbox" style={{ width: 'auto' }} checked={r.is_active} disabled={r.id === me.id} onChange={(e) => update(r.id, { is_active: e.target.checked })} /> },
    { key: 'created_at', label: 'Created', width: 170, sortValue: (r) => r.created_at, render: (r) => <span className="muted">{fmtDate(r.created_at)}</span> },
  ]

  return (
    <div className="page page-dense">
      <div className="page-head" style={{ marginBottom: 24 }}>
        <div>
          <p className="eyebrow">Admin</p>
          <h1 className="display display-h1">Users</h1>
          <p className="lede small" style={{ marginTop: 8 }}>Analysts see their own uploads. Reviewers work the queue across all documents. Admins also manage rule packs and users.</p>
        </div>
      </div>
      {notice && <Notice tone={notice.tone}>{notice.text}</Notice>}
      <form className="card card-quiet card-tight" style={{ marginBottom: 16 }} onSubmit={create}>
        <div className="filters">
          <Field label="Full name"><input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} required /></Field>
          <Field label="Email"><input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required /></Field>
          <Field label="Password"><input type="password" minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required /></Field>
          <Field label="Role">
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select>
          </Field>
          <Button size="sm" loading={busy}>Add user</Button>
        </div>
      </form>
      <div className="card card-solid card-tight">
        <DataTable columns={columns} rows={list.data || null} loading={list.loading} error={list.error} onRetry={list.reload} defaultSort={{ key: 'full_name', dir: 'asc' }} />
      </div>
    </div>
  )
}
