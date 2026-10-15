import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth'
import Layout from './components/Layout'
import Auth from './pages/Auth'
import Chat from './pages/Chat'
import Compare from './pages/Compare'
import DocumentDetail from './pages/DocumentDetail'
import Documents from './pages/Documents'
import Evaluation from './pages/Evaluation'

const GraphPage = lazy(() => import('./pages/GraphPage')) // force-graph is heavy; load on demand

function Protected() {
  const { user, loading } = useAuth()
  if (loading) return <p className="p-8 text-slate-400">Loading…</p>
  return user ? <Layout /> : <Navigate to="/login" replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Auth mode="login" />} />
      <Route path="/register" element={<Auth mode="register" />} />
      <Route element={<Protected />}>
        <Route index element={<Documents />} />
        <Route path="documents/:id" element={<DocumentDetail />} />
        <Route path="chat" element={<Chat />} />
        <Route path="compare" element={<Compare />} />
        <Route path="graph" element={<Suspense fallback={<p className="text-slate-400">Loading graph…</p>}><GraphPage /></Suspense>} />
        <Route path="evaluation" element={<Evaluation />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
