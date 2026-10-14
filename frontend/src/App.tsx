import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Chat from './pages/Chat'
import DocumentDetail from './pages/DocumentDetail'
import Documents from './pages/Documents'
import Evaluation from './pages/Evaluation'

const GraphPage = lazy(() => import('./pages/GraphPage')) // force-graph is heavy; load on demand

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Documents />} />
        <Route path="documents/:id" element={<DocumentDetail />} />
        <Route path="chat" element={<Chat />} />
        <Route path="graph" element={<Suspense fallback={<p className="text-slate-500">Loading graph…</p>}><GraphPage /></Suspense>} />
        <Route path="evaluation" element={<Evaluation />} />
      </Route>
    </Routes>
  )
}
