import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ArrowLeft } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { api, sevCls } from '../api'
import type { DocDetail } from '../types'

const Facts = ({ label, items }: { label: string; items: string[] }) => items.length ? (
  <div><div className="label">{label}</div><div className="flex flex-wrap gap-1.5">{items.map((i) => <span key={i} className="rounded-full bg-white/[0.07] px-2.5 py-0.5 text-xs">{i}</span>)}</div></div>) : null

export default function DocumentDetail() {
  const { id } = useParams()
  const { data: d } = useQuery({ queryKey: ['doc', id], queryFn: async () => (await api.get<DocDetail>(`/documents/${id}`)).data })
  if (!d) return <p className="text-slate-400">Loading…</p>
  const f = d.key_facts
  return (
    <div className="space-y-6">
      <Link to="/" className="flex items-center gap-1 text-sm text-slate-400 hover:text-slate-100"><ArrowLeft size={14} />All documents</Link>
      <div><h1 className="text-2xl font-semibold">{d.name}</h1><p className="text-sm text-slate-400">{d.chunk_count} clauses · {d.entity_count} entities · ~{d.est_tokens.toLocaleString()} tokens</p></div>
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <section className="card space-y-4 p-5"><h2 className="font-semibold">Key facts</h2>
            <div className="grid gap-4 sm:grid-cols-2"><Facts label="Parties" items={f.parties} /><Facts label="Dates" items={f.dates} /><Facts label="Amounts" items={f.amounts} />
              <Facts label="Periods" items={f.durations} /><Facts label="Jurisdictions" items={f.jurisdictions} /></div></section>
          <section className="card p-5"><h2 className="mb-3 font-semibold">Clause risk flags</h2>
            {d.risks.length === 0 && <p className="text-sm text-slate-400">Nothing unusual detected.</p>}
            <ul className="space-y-3">{d.risks.map((r, i) => (
              <li key={i} className="rounded-lg border border-white/10 p-3">
                <div className="flex items-center gap-2"><span className={`rounded px-2 py-0.5 text-xs font-semibold uppercase ring-1 ${sevCls[r.severity]}`}>{r.severity}</span><span className="font-medium">{r.topic}</span><span className="ml-auto truncate text-xs text-slate-500">{r.section}</span></div>
                <p className="mt-1.5 text-sm text-slate-300">{r.why}</p>
                {r.quote && <blockquote className="mt-2 border-l-2 border-gold pl-3 text-sm italic text-slate-400">{r.quote}</blockquote>}
              </li>))}</ul>
            <p className="mt-3 text-xs text-slate-500">Rule-based screening to help you read faster. Not legal advice.</p></section>
        </div>
        <section className="card h-fit p-5"><h2 className="mb-3 font-semibold">Clauses</h2>
          <ol className="max-h-[640px] space-y-3 overflow-y-auto pr-1">{d.chunks.map((c) => (
            <li key={c.id} className={`text-sm ${c.suspicious ? 'rounded-lg border border-amber-400/40 bg-amber-400/5 p-2' : ''}`}><div className="text-xs font-semibold text-gold-dark">{c.section}</div>
              {c.suspicious && <div className="mt-0.5 flex items-start gap-1 text-xs text-amber-300"><AlertTriangle size={12} className="mt-0.5 shrink-0" /><span>Instruction-like text: {(c.injection_phrases ?? []).map((p) => `“${p}”`).join(', ')}. It is treated as data and never obeyed.</span></div>}<p className="mt-0.5 line-clamp-4 text-slate-300">{c.text}</p></li>))}</ol></section>
      </div>
    </div>
  )
}
