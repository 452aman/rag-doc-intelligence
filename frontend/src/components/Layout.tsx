import { useQuery } from '@tanstack/react-query'
import { BarChart3, FileText, GitCompare, LogOut, MessageSquare, Network } from 'lucide-react'
import { useAuth } from '../auth'
import Logo from './Logo'
import { NavLink, Outlet } from 'react-router-dom'
import { api } from '../api'

const cls = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-2 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium ${isActive ? 'bg-white/10 text-white' : 'text-slate-300 hover:bg-white/5'}`

export default function Layout() {
  const { user, logout } = useAuth()
  const { data: s } = useQuery({ queryKey: ['stats'], queryFn: async () => (await api.get('/stats')).data, refetchInterval: 6000 })
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-white/10 bg-[#070a14]/70 backdrop-blur-xl">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-5 gap-y-2 px-4 py-3 lg:flex-nowrap">
          <div className="flex shrink-0 items-center gap-2 whitespace-nowrap text-lg font-semibold text-white"><Logo />Legal Document Intelligence</div>
          <nav className="flex gap-0.5">
            <NavLink to="/" end className={cls}><FileText size={16} />Documents</NavLink>
            <NavLink to="/chat" className={cls}><MessageSquare size={16} />Ask</NavLink>
            <NavLink to="/compare" className={cls}><GitCompare size={16} />Compare</NavLink>
            <NavLink to="/graph" className={cls}><Network size={16} />Knowledge graph</NavLink>
            <NavLink to="/evaluation" className={cls}><BarChart3 size={16} />Evaluation</NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-4">
            {s && <div className="hidden items-center gap-3 whitespace-nowrap text-xs text-slate-500 min-[1600px]:flex">
              <span>{s.documents} docs</span><span>{s.chunks} clauses</span><span>{s.entities} entities</span>
              <span className={s.llm ? 'text-emerald-400' : 'text-amber-400'}>{s.llm ? 'LLM online' : 'extractive mode'}</span></div>}
            <div className="flex items-center gap-1 whitespace-nowrap text-sm text-slate-300">{user?.name}<button onClick={logout} className="rounded-lg p-2 hover:bg-white/10" aria-label="Log out"><LogOut size={16} /></button></div>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6"><Outlet /></main>
    </div>
  )
}
