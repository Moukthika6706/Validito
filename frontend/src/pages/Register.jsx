import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { Alert, Field } from '../components/ui'
import { useAuth } from '../context/AuthContext'

export default function Register() {
  const { user, register } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({ full_name: '', email: '', password: '' })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to="/" replace />

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await register(form)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err.detail || err.message)
    } finally {
      setBusy(false)
    }
  }
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  return (
    <div className="auth">
      <form className="card" onSubmit={submit}>
        <h1>Create account</h1>
        <p className="muted">New accounts are analysts. An admin can promote you to reviewer.</p>
        {error && <Alert tone="danger">{error}</Alert>}
        <Field label="Full name">
          <input value={form.full_name} onChange={set('full_name')} required autoFocus />
        </Field>
        <Field label="Email">
          <input type="email" value={form.email} onChange={set('email')} required autoComplete="username" />
        </Field>
        <Field label="Password" hint="At least 8 characters">
          <input type="password" value={form.password} onChange={set('password')} minLength={8} required autoComplete="new-password" />
        </Field>
        <button className="btn btn-primary" disabled={busy} style={{ width: '100%' }}>
          {busy ? 'Creating…' : 'Create account'}
        </button>
        <p className="muted small" style={{ marginTop: 12 }}>
          Already registered? <Link to="/login">Sign in</Link>
        </p>
      </form>
    </div>
  )
}
