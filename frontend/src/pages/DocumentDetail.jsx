import { Navigate, useParams } from 'react-router-dom'

// The review screen serves both analysts (read-only) and reviewers; /documents/:id is kept
// as a stable link target.
export default function DocumentDetail() {
  const { id } = useParams()
  return <Navigate to={`/review/${id}`} replace />
}
