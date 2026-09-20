import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useAsync } from '../hooks/useAsync'
import { review } from '../api/endpoints'

export default function Layout() {
  const { user, logout, isReviewer, isAdmin } = useAuth()
  const navigate = useNavigate()
  const queue = useAsync(() => (isReviewer ? review.queue({ limit: 1 }) : Promise.resolve(null)), [isReviewer], { interval: 15000 })
  const pending = queue.data?.total ?? 0

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">V</span>
          <span>
            Validito
            <small>Term sheet validation</small>
          </span>
        </div>
        <nav>
          <NavLink to="/" end>
            Dashboard
          </NavLink>
          <NavLink to="/documents">Documents</NavLink>
          <NavLink to="/documents/new" className="nav-sub">
            + Upload
          </NavLink>
          {isReviewer && (
            <NavLink to="/review">
              Review queue {pending > 0 && <span className="pill">{pending}</span>}
            </NavLink>
          )}
          <NavLink to="/audit">Audit trail</NavLink>
          {isAdmin && (
            <>
              <div className="nav-section">Admin</div>
              <NavLink to="/admin/rule-packs">Rule packs</NavLink>
              <NavLink to="/admin/users">Users</NavLink>
            </>
          )}
        </nav>
        <div className="sidebar-footer">
          <div>
            <strong>{user?.full_name}</strong>
            <small className="muted">{user?.email}</small>
            <span className={`badge badge-role role-${user?.role}`}>{user?.role}</span>
          </div>
          <button
            className="btn btn-sm"
            onClick={() => {
              logout()
              navigate('/login')
            }}
          >
            Sign out
          </button>
        </div>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}
