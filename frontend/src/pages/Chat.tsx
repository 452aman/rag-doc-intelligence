import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Gauge, Plus, Send, Sparkles, Zap } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { AnswerMeta, ChatMessage, Citation, Conversation, Doc } from '../types'

const MODES: [string, string][] = [['full', 'Hybrid + graph + rerank'], ['hybrid+graph', 'Hybrid + graph'], ['hybrid', 'Hybrid (BM25 + dense)'], ['dense', 'Dense only'], ['bm25', 'BM25 only']]
const SUGGESTIONS = ['How long do confidentiality obligations last after the NDA ends?', "If the vendor goes down for a day, what do we get back, and is that our only remedy?", 'What does the employee agree not to do after leaving?', 'Which contracts renew automatically?']

function Answer({ m, onCite }: { m: ChatMessage; onCite: (n: number) => void }) {
  // Turn [1] / 【1】 markers into clickable chips and **bold** into <strong>.
  const parts = m.content.split(/([\[【]\d+[\]】]|\*\*[^*]+\*\*)/g)
  return (
    <div className="whitespace-pre-wrap leading-relaxed">
      {parts.map((p, i) => {
        const c = p.match(/^[\[【](\d+)[\]】]$/)
        if (c) return <button key={i} onClick={() => onCite(+c[1])} className="mx-0.5 rounded bg-amber-400/15 px-1.5 text-xs font-semibold text-gold-dark hover:bg-amber-400/25">{c[1]}</button>
        const b = p.match(/^\*\*(.+)\*\*$/)
        return b ? <strong key={i}>{b[1]}</strong> : <span key={i}>{p}</span>
      })}
      {m.streaming && <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-gold align-middle" />}
    </div>
  )
}

const Meta = ({ m }: { m: AnswerMeta }) => (
  <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-slate-400">
    <span className="flex items-center gap-1 rounded bg-white/[0.07] px-2 py-0.5"><Zap size={11} />{(m.latency_ms / 1000).toFixed(1)}s total · {m.retrieval_ms}ms retrieval</span>
    <span className="flex items-center gap-1 rounded bg-white/[0.07] px-2 py-0.5"><Gauge size={11} />{m.prompt_tokens} / {m.corpus_tokens} tokens{m.token_reduction != null && ` (${Math.round(m.token_reduction * 100)}% saved)`}</span>
    {m.entities && m.entities.length > 0 && <span className="rounded bg-blue-400/10 px-2 py-0.5 text-blue-300">graph: {m.entities.join(', ')}</span>}
    {m.uncited && <span className="rounded bg-amber-400/10 px-2 py-0.5 text-amber-300">no citations in answer: verify</span>}
  </div>
)

export default function Chat() {
  const qc = useQueryClient()
  const [msgs, setMsgs] = useState<ChatMessage[]>([])
  const [convId, setConvId] = useState<number | null>(null)
  const [input, setInput] = useState('')
  const [mode, setMode] = useState('full')
  const [scope, setScope] = useState<number[]>([])
  const [busy, setBusy] = useState(false)
  const [active, setActive] = useState<Citation | null>(null)
  const bottom = useRef<HTMLDivElement>(null)
  const { data: docs = [] } = useQuery({ queryKey: ['docs'], queryFn: async () => (await api.get<Doc[]>('/documents')).data })
  const { data: convs = [] } = useQuery({ queryKey: ['convs'], queryFn: async () => (await api.get<Conversation[]>('/conversations')).data })
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs])

  const open = async (id: number) => {
    const r = await api.get(`/conversations/${id}`)
    setConvId(id); setMsgs(r.data.messages); setActive(null)
  }
  const reset = () => { setConvId(null); setMsgs([]); setActive(null) }

  const ask = async (question: string) => {
    if (!question.trim() || busy) return
    setBusy(true); setInput(''); setActive(null)
    setMsgs((m) => [...m, { role: 'user', content: question }, { role: 'assistant', content: '', streaming: true }])
    const patch = (fn: (m: ChatMessage) => ChatMessage) => setMsgs((all) => all.map((m, i) => (i === all.length - 1 ? fn(m) : m)))
    try {
      const res = await fetch('/api/v1/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, conversation_id: convId, doc_ids: scope.length ? scope : null, mode }) })
      if (!res.ok || !res.body) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`)
      const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = ''
      for (;;) {
        const { done, value } = await reader.read(); if (done) break
        buf += dec.decode(value, { stream: true })
        const lines = buf.split('\n\n'); buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const ev = JSON.parse(line.slice(6))
          if (ev.type === 'conversation') setConvId(ev.id)
          else if (ev.type === 'retrieval') patch((m) => ({ ...m, citations: ev.citations, meta: { ...(m.meta as AnswerMeta), entities: ev.entities } as AnswerMeta }))
          else if (ev.type === 'token') patch((m) => ({ ...m, content: m.content + ev.text }))
          else if (ev.type === 'done') patch((m) => ({ ...m, content: ev.answer, streaming: false, meta: { ...ev.meta, entities: m.meta?.entities, cited: ev.cited } }))
          else if (ev.type === 'error') patch((m) => ({ ...m, streaming: false, error: ev.message }))
        }
      }
    } catch (e) { patch((m) => ({ ...m, streaming: false, error: (e as Error).message })) }
    setBusy(false); qc.invalidateQueries({ queryKey: ['convs'] })
  }
  const lastCites = [...msgs].reverse().find((m) => m.role === 'assistant')?.citations ?? []
  const showCite = (m: ChatMessage, n: number) => setActive(m.citations?.find((c) => c.n === n) ?? null)

  return (
    <div className="grid gap-4 lg:grid-cols-[220px_1fr_340px]">
      <aside className="card h-fit space-y-3 p-3">
        <button className="btn w-full" onClick={reset}><Plus size={14} />New chat</button>
        <ul className="max-h-72 space-y-1 overflow-y-auto">{convs.map((c) => <li key={c.id}><button onClick={() => open(c.id)} className={`w-full truncate rounded-lg px-2 py-1.5 text-left text-sm hover:bg-white/10 ${c.id === convId ? 'bg-white/[0.07] font-medium' : ''}`}>{c.title}</button></li>)}</ul>
        <div className="border-t border-white/10 pt-3"><div className="label">Search scope</div>
          {docs.filter((d) => d.status === 'ready').map((d) => (
            <label key={d.id} className="flex items-center gap-2 py-0.5 text-xs"><input type="checkbox" checked={scope.includes(d.id)} onChange={(e) => setScope(e.target.checked ? [...scope, d.id] : scope.filter((x) => x !== d.id))} /><span className="truncate">{d.name}</span></label>))}
          <p className="mt-1 text-[11px] text-slate-500">{scope.length ? `${scope.length} selected` : 'All documents'}</p></div>
        <div><div className="label">Retrieval mode</div><select className="input py-1 text-xs" value={mode} onChange={(e) => setMode(e.target.value)}>{MODES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></div>
      </aside>

      <section className="card flex h-[calc(100vh-150px)] min-h-[520px] flex-col">
        <div className="flex-1 space-y-5 overflow-y-auto p-5">
          {msgs.length === 0 && (
            <div className="mx-auto max-w-lg space-y-3 pt-8 text-center"><Sparkles className="mx-auto text-gold" /><h2 className="text-lg font-semibold">Ask your contracts anything</h2>
              <p className="text-sm text-slate-400">Answers cite the exact clauses they come from.</p>
              <div className="grid gap-2 pt-2">{SUGGESTIONS.map((s) => <button key={s} onClick={() => ask(s)} className="rounded-lg border border-white/10 px-3 py-2 text-left text-sm hover:bg-white/[0.07]">{s}</button>)}</div></div>)}
          {msgs.map((m, i) => m.role === 'user'
            ? <div key={i} className="ml-auto max-w-[80%] rounded-2xl rounded-br-sm bg-navy-900 px-4 py-2.5 text-sm text-white">{m.content}</div>
            : <div key={i} className="max-w-[92%] text-sm">
                {m.content || m.streaming ? <Answer m={m} onCite={(n) => showCite(m, n)} /> : null}
                {m.error && <p className="rounded-lg bg-rose-400/10 px-3 py-2 text-rose-300">{m.error}</p>}
                {m.meta && !m.streaming && <Meta m={m.meta} />}
              </div>)}
          <div ref={bottom} />
        </div>
        <form className="flex gap-2 border-t border-white/10 p-3" onSubmit={(e) => { e.preventDefault(); ask(input) }}>
          <input className="input" placeholder="Ask about termination, liability, fees…" value={input} onChange={(e) => setInput(e.target.value)} disabled={busy} />
          <button className="btn-gold" disabled={busy || !input.trim()}><Send size={16} /></button>
        </form>
      </section>

      <aside className="card h-fit max-h-[calc(100vh-150px)] space-y-3 overflow-y-auto p-4">
        <h2 className="font-semibold">Sources</h2>
        {(active ? [active] : lastCites).length === 0 && <p className="text-sm text-slate-400">Cited clauses appear here.</p>}
        {active && <button className="text-xs text-gold-dark hover:underline" onClick={() => setActive(null)}>Show all retrieved</button>}
        {(active ? [active] : lastCites).map((c) => (
          <div key={c.chunk_id} className={`rounded-lg border p-3 text-sm ${active ? 'border-gold bg-amber-400/10' : 'border-white/10'}`}>
            <div className="flex items-center gap-2"><span className="rounded bg-amber-400/15 px-1.5 text-xs font-semibold text-gold-dark">{c.n}</span><span className="truncate text-xs font-medium">{c.doc_name}</span></div>
            <div className="mt-1 text-xs text-slate-500">{c.section} · p.{c.page} · {c.via.join(' + ') || 'rerank'}</div>
            <p className="mt-2 whitespace-pre-wrap text-slate-300">{c.text}</p>
          </div>))}
      </aside>
    </div>
  )
}
