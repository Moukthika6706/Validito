import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { review } from '../api/endpoints'
import { useAuth } from '../context/AuthContext'
import { useAsync } from '../hooks/useAsync'

export default function Layout() {
  const { user, logout, isReviewer, isAdmin } = useAuth()
  const navigate = useNavigate()
  const queue = useAsync(() => (isReviewer ? review.queue({ limit: 1 }) : Promise.resolve(null)), [isReviewer], { interval: 15000 })
  const pending = queue.data?.total ?? 0

  return (
    <div className="shell">
      <header className="nav">
        <NavLink to="/" className="wordmark">
          Validito
        </NavLink>
        <nav className="nav-links">
          <NavLink to="/" end>
            Home
          </NavLink>
          <NavLink to="/upload">Upload</NavLink>
          {isReviewer && (
            <NavLink to="/queue">
              Queue {pending > 0 && <span className="count-pill">{pending}</span>}
            </NavLink>
          )}
          <NavLink to="/audit">Audit</NavLink>
          {isAdmin && <NavLink to="/admin/rules">Rules</NavLink>}
          {isAdmin && <NavLink to="/admin/users">Users</NavLink>}
        </nav>
        <div className="nav-right">
          <span title={user?.email}>
            {user?.full_name} · {user?.role}
          </span>
          <button
            className="link"
            onClick={() => {
              logout()
              navigate('/login')
            }}
          >
            Sign out
          </button>
        </div>
      </header>
      <Outlet />
    </div>
  )
}
