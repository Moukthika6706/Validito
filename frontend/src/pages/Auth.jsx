import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import Button from '../components/Button'
import GlowBackground from '../components/GlowBackground'
import { Field, Notice } from '../components/States'
import { useAuth } from '../context/AuthContext'

const ROLES = [
  { value: 'analyst', label: 'Analyst', hint: 'Upload and track your own term sheets' },
  { value: 'reviewer', label: 'Reviewer', hint: 'Work the review queue across all documents' },
  { value: 'admin', label: 'Admin', hint: 'Everything, plus rule packs and users' },
]

export default function Auth({ mode: initialMode = 'login' }) {
  const { user, login, register } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [mode, setMode] = useState(initialMode)
  const [form, setForm] = useState({ full_name: '', email: '', password: '', confirm: '', role: 'analyst' })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [forgot, setForgot] = useState(false)

  if (user) return <Navigate to={location.state?.from?.pathname || '/'} replace />

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const dest = location.state?.from?.pathname || '/'

  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    if (mode === 'signup' && form.password !== form.confirm) return setError('Passwords do not match.')
    setBusy(true)
    try {
      if (mode === 'signup') {
        await register({ full_name: form.full_name || form.email.split('@')[0], email: form.email, password: form.password, role: form.role })
      } else {
        await login(form.email, form.password)
      }
      navigate(dest, { replace: true })
    } catch (err) {
      setError(err.detail || err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth">
      <GlowBackground position="corner" />
      <div className="auth-top">
        <span className="wordmark">Validito</span>
      </div>
      <div className="auth-body">
        <div>
          <h1 className="display display-hero">
            Validate smarter.
            <br />
            Catch risk faster.
          </h1>
          <p className="lede">
            Validito reads ISDA and LMA term sheets, checks every clause against your rule packs and an anomaly model, explains
            each flag it raises, and sends only the ambiguous ones to a human — with a tamper-evident audit trail.
          </p>
        </div>

        <form className="card auth-card" onSubmit={submit}>
          <div className="segmented" style={{ marginBottom: 20 }}>
            <button type="button" className={mode === 'login' ? 'active' : ''} onClick={() => { setMode('login'); setError(null) }}>
              Log in
            </button>
            <button type="button" className={mode === 'signup' ? 'active' : ''} onClick={() => { setMode('signup'); setError(null) }}>
              Sign up
            </button>
          </div>

          {error && <Notice tone="bad">{error}</Notice>}
          {forgot && (
            <Notice tone="info">
              Password resets are handled by your admin in this build — ask them to set a new password from the Users screen.
            </Notice>
          )}

          {mode === 'signup' && (
            <Field label="Full name">
              <input value={form.full_name} onChange={set('full_name')} autoFocus autoComplete="name" placeholder="Jane Analyst" />
            </Field>
          )}
          <Field label="Email">
            <input type="email" value={form.email} onChange={set('email')} required autoComplete="username" autoFocus={mode === 'login'} placeholder="you@bank.com" />
          </Field>
          <Field label="Password" hint={mode === 'signup' ? 'At least 8 characters' : undefined}>
            <input type="password" value={form.password} onChange={set('password')} required minLength={8} autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} />
          </Field>
          {mode === 'signup' && (
            <>
              <Field label="Confirm password">
                <input type="password" value={form.confirm} onChange={set('confirm')} required minLength={8} autoComplete="new-password" />
              </Field>
              <Field label="Role" hint={ROLES.find((r) => r.value === form.role)?.hint}>
                <div className="segmented">
                  {ROLES.map((r) => (
                    <button type="button" key={r.value} className={form.role === r.value ? 'active' : ''} onClick={() => setForm((f) => ({ ...f, role: r.value }))}>
                      {r.label}
                    </button>
                  ))}
                </div>
              </Field>
            </>
          )}

          <Button block size="lg" loading={busy} style={{ marginTop: 8 }}>
            {mode === 'signup' ? 'Create account' : 'Log in'}
          </Button>

          <div className="auth-switch spread">
            {mode === 'login' ? (
              <>
                <span>
                  New here?{' '}
                  <button type="button" className="link" onClick={() => setMode('signup')}>
                    Create an account
                  </button>
                </span>
                <button type="button" className="link" onClick={() => setForgot(true)}>
                  Forgot password?
                </button>
              </>
            ) : (
              <span>
                Already have an account?{' '}
                <button type="button" className="link" onClick={() => setMode('login')}>
                  Log in
                </button>
              </span>
            )}
          </div>
        </form>
      </div>
    </div>
  )
}
