import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import Layout from './components/Layout'
import { Loading } from './components/ui'
import { useAuth } from './context/AuthContext'
import AdminRulePacks from './pages/AdminRulePacks'
import AdminUsers from './pages/AdminUsers'
import AuditTrail from './pages/AuditTrail'
import Dashboard from './pages/Dashboard'
import DocumentDetail from './pages/DocumentDetail'
import Documents from './pages/Documents'
import Login from './pages/Login'
import Register from './pages/Register'
import ReviewDocument from './pages/ReviewDocument'
import ReviewQueue from './pages/ReviewQueue'
import UploadDocument from './pages/UploadDocument'

function RequireAuth({ children, role }) {
  const { user, loading, isReviewer, isAdmin } = useAuth()
  const location = useLocation()
  if (loading) return <Loading label="Restoring session…" />
  if (!user) return <Navigate to="/login" state={{ from: location }} replace />
  if (role === 'reviewer' && !isReviewer) return <Navigate to="/" replace />
  if (role === 'admin' && !isAdmin) return <Navigate to="/" replace />
  return children
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="documents" element={<Documents />} />
        <Route path="documents/new" element={<UploadDocument />} />
        <Route path="documents/:id" element={<DocumentDetail />} />
        <Route
          path="review"
          element={
            <RequireAuth role="reviewer">
              <ReviewQueue />
            </RequireAuth>
          }
        />
        <Route
          path="review/:id"
          element={
            <RequireAuth role="reviewer">
              <ReviewDocument />
            </RequireAuth>
          }
        />
        <Route path="audit" element={<AuditTrail />} />
        <Route
          path="admin/rule-packs"
          element={
            <RequireAuth role="admin">
              <AdminRulePacks />
            </RequireAuth>
          }
        />
        <Route
          path="admin/users"
          element={
            <RequireAuth role="admin">
              <AdminUsers />
            </RequireAuth>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
