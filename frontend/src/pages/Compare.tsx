import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, GitCompare } from 'lucide-react'
import { useState } from 'react'
import { api, authFetch, readSSE } from '../api'
import type { Citation, Doc } from '../types'

const TOPICS = ['Termination and notice', 'Limitation of liability', 'Governing law and disputes', 'Payment and fees', 'Confidentiality', 'Intellectual property']
interface Side { doc_id: number; name: string; clauses: Citation[] }

// Turn [A1] / [B2] markers into chips and **bold** into <strong>.
function Summary({ text, streaming }: { text: string; streaming: boolean }) {
  const parts = text.split(/(\[[AB]\d\]|\*\*[^*]+\*\*)/g)
  return (
    <div className="whitespace-pre-wrap leading-relaxed text-slate-200">
      {parts.map((p, i) => {
        const c = p.match(/^\[([AB])(\d)\]$/)
        if (c) return <span key={i} className={`mx-0.5 rounded px-1.5 text-xs font-semibold ${c[1] === 'A' ? 'bg-sky-400/20 text-sky-300' : 'bg-amber-400/20 text-amber-300'}`}>{c[1]}{c[2]}</span>
        const b = p.match(/^\*\*(.+)\*\*$/)
        return b ? <strong key={i}>{b[1]}</strong> : <span key={i}>{p}</span>
      })}
      {streaming && <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-gold align-middle" />}
    </div>
  )
}

function Column({ tag, side, tone }: { tag: string; side: Side; tone: string }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2"><span className={`rounded px-2 py-0.5 text-xs font-bold ${tone}`}>{tag}</span><span className="truncate font-medium">{side.name}</span></div>
      {side.clauses.length === 0 && <p className="card p-4 text-sm text-slate-400">No relevant clause found.</p>}
      {side.clauses.map((c) => (
        <div key={c.chunk_id} className="card p-4 text-sm">
          <div className="mb-1 flex items-center gap-2 text-xs text-slate-400"><span className={`rounded px-1.5 font-semibold ${tone}`}>{tag}{c.n}</span><span className="truncate">{c.section}</span>
            {c.suspicious && <span className="ml-auto flex items-center gap-1 text-amber-300"><AlertTriangle size={12} />flagged</span>}</div>
          <p className="whitespace-pre-wrap text-slate-300">{c.text}</p>
        </div>))}
    </div>
  )
}

export default function Compare() {
  const { data: docs = [] } = useQuery({ queryKey: ['docs'], queryFn: async () => (await api.get<Doc[]>('/documents')).data })
  const ready = docs.filter((d) => d.status === 'ready')
  const [a, setA] = useState<number | ''>('')
  const [b, setB] = useState<number | ''>('')
  const [topic, setTopic] = useState('')
  const [sides, setSides] = useState<{ a: Side; b: Side } | null>(null)
  const [summary, setSummary] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const run = async (t = topic) => {
    if (!a || !b || a === b || t.trim().length < 3) return
    setBusy(true); setError(''); setSummary(''); setNote(''); setSides(null); setTopic(t)
    try {
      const res = await authFetch('/api/v1/compare', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ doc_a: a, doc_b: b, topic: t }) })
      await readSSE(res, (ev) => {
        if (ev.type === 'retrieval') setSides({ a: ev.a, b: ev.b })
        else if (ev.type === 'token') setSummary((s) => s + ev.text)
        else if (ev.type === 'done') { if (ev.answer && !ev.answer.trim()) setNote(ev.meta?.note ?? ''); else if (ev.meta?.note) setNote(ev.meta.note) }
        else if (ev.type === 'error') setError(ev.message)
      })
    } catch (e) { setError((e as Error).message) }
    setBusy(false)
  }
  const pick = (v: string, set: (n: number | '') => void) => set(v ? +v : '')

  return (
    <div className="space-y-6">
      <div><h1 className="text-2xl font-semibold">Compare contracts</h1><p className="text-sm text-slate-400">Pick two contracts and a topic. You get the matching clauses side by side and a cited summary of the differences.</p></div>
      <div className="card grid gap-3 p-4 md:grid-cols-[1fr_1fr_1.4fr_auto]">
        <div><label className="label">Contract A</label><select className="input" value={a} onChange={(e) => pick(e.target.value, setA)}><option value="">Select…</option>{ready.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></div>
        <div><label className="label">Contract B</label><select className="input" value={b} onChange={(e) => pick(e.target.value, setB)}><option value="">Select…</option>{ready.filter((d) => d.id !== a).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></div>
        <div><label className="label">Topic</label><input className="input" placeholder="e.g. termination notice" value={topic} onChange={(e) => setTopic(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && run()} /></div>
        <div className="flex items-end"><button className="btn-gold w-full" disabled={busy || !a || !b || topic.trim().length < 3} onClick={() => run()}><GitCompare size={15} />{busy ? 'Comparing…' : 'Compare'}</button></div>
      </div>
      <div className="flex flex-wrap gap-2">{TOPICS.map((t) => <button key={t} disabled={busy || !a || !b} onClick={() => run(t)} className="rounded-full border border-white/15 px-3 py-1 text-xs text-slate-300 hover:border-gold hover:text-gold disabled:opacity-40">{t}</button>)}</div>
      {ready.length < 2 && <p className="card p-6 text-center text-sm text-slate-400">You need at least two processed contracts. Load the samples on the Documents page.</p>}
      {error && <p className="rounded-lg bg-rose-400/10 px-3 py-2 text-sm text-rose-300">{error}</p>}
      {sides && (<>
        {(summary || busy) && <div className="card p-5"><h2 className="mb-2 font-semibold">Summary of differences</h2><Summary text={summary} streaming={busy} /><p className="mt-3 text-xs text-slate-500">Information to help you read faster, not legal advice.</p></div>}
        {note && <p className="rounded-lg bg-amber-400/10 px-3 py-2 text-sm text-amber-200">{note}</p>}
        <div className="grid gap-5 lg:grid-cols-2"><Column tag="A" side={sides.a} tone="bg-sky-400/20 text-sky-300" /><Column tag="B" side={sides.b} tone="bg-amber-400/20 text-amber-300" /></div>
      </>)}
    </div>
  )
}
