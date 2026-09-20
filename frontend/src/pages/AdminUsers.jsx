import { useState } from 'react'
import { users } from '../api/endpoints'
import { Alert, ErrorState, Field, Loading } from '../components/ui'
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
      setNotice({ tone: 'success', text: 'User updated.' })
      list.reload(true)
    } catch (e) {
      setNotice({ tone: 'danger', text: e.detail || e.message })
    }
  }

  const create = async (e) => {
    e.preventDefault()
    setBusy(true)
    try {
      await users.create(form)
      setForm({ full_name: '', email: '', password: '', role: 'analyst' })
      setNotice({ tone: 'success', text: 'User created.' })
      list.reload(true)
    } catch (err) {
      setNotice({ tone: 'danger', text: err.detail || err.message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Users</h1>
          <p>Analysts see their own uploads. Reviewers work the queue and see every document. Admins also manage rule packs and users.</p>
        </div>
      </div>
      {notice && <Alert tone={notice.tone}>{notice.text}</Alert>}
      <form className="card inline-form" onSubmit={create}>
        <Field label="Full name">
          <input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} required />
        </Field>
        <Field label="Email">
          <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
        </Field>
        <Field label="Password">
          <input type="password" value={form.password} minLength={8} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
        </Field>
        <Field label="Role">
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
            {ROLES.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </Field>
        <button className="btn btn-primary" disabled={busy}>
          Add user
        </button>
      </form>
      <div className="card">
        {list.loading && !list.data && <Loading />}
        {list.error && <ErrorState error={list.error} onRetry={list.reload} />}
        {list.data && (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Role</th>
                <th>Active</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((u) => (
                <tr key={u.id}>
                  <td>
                    {u.full_name} {u.id === me.id && <span className="badge badge-outline">you</span>}
                  </td>
                  <td>{u.email}</td>
                  <td>
                    <select value={u.role} disabled={u.id === me.id} onChange={(e) => update(u.id, { role: e.target.value })}>
                      {ROLES.map((r) => (
                        <option key={r}>{r}</option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input type="checkbox" checked={u.is_active} disabled={u.id === me.id} onChange={(e) => update(u.id, { is_active: e.target.checked })} />
                  </td>
                  <td className="muted">{fmtDate(u.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
