import { useQuery } from '@tanstack/react-query'
import { BarChart3, FileText, MessageSquare, Network, Scale } from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'
import { api } from '../api'

const cls = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium ${isActive ? 'bg-white/10 text-white' : 'text-slate-300 hover:bg-white/5'}`

export default function Layout() {
  const { data: s } = useQuery({ queryKey: ['stats'], queryFn: async () => (await api.get('/stats')).data, refetchInterval: 6000 })
  return (
    <div className="min-h-screen">
      <header className="bg-navy-950">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-6 px-4 py-3">
          <div className="flex items-center gap-2 text-lg font-semibold text-white"><Scale className="text-gold" size={22} />Legal Document Intelligence</div>
          <nav className="flex gap-1">
            <NavLink to="/" end className={cls}><FileText size={16} />Documents</NavLink>
            <NavLink to="/chat" className={cls}><MessageSquare size={16} />Ask</NavLink>
            <NavLink to="/graph" className={cls}><Network size={16} />Knowledge graph</NavLink>
            <NavLink to="/evaluation" className={cls}><BarChart3 size={16} />Evaluation</NavLink>
          </nav>
          {s && <div className="ml-auto flex gap-4 text-xs text-slate-400">
            <span>{s.documents} docs</span><span>{s.chunks} clauses</span><span>{s.entities} entities</span>
            <span className={s.llm ? 'text-emerald-400' : 'text-amber-400'}>{s.llm ? 'LLM online' : 'extractive mode'}</span></div>}
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6"><Outlet /></main>
    </div>
  )
}
