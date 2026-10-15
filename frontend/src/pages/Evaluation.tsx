import { useMutation } from '@tanstack/react-query'
import { Play } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, errMsg } from '../api'
import type { EvalResult } from '../types'

const LABEL: Record<string, string> = { dense: 'Dense (FAISS)', bm25: 'BM25', hybrid: 'Hybrid (RRF)', 'hybrid+graph': 'Hybrid + graph', full: 'Hybrid + graph + rerank' }

export default function Evaluation() {
  const run = useMutation({ mutationFn: async () => (await api.post<EvalResult>('/evaluation/run')).data })
  const d = run.data
  const rows = d ? Object.entries(d.modes).map(([k, v]) => ({ mode: LABEL[k], 'hit@1': v['hit@1'], 'hit@3': v['hit@3'], 'hit@5': v['hit@5'], MRR: v.mrr })) : []
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h1 className="text-2xl font-semibold">Retrieval evaluation</h1>
          <p className="max-w-2xl text-sm text-slate-400">Runs every retrieval strategy over a fixed question set against the loaded sample contracts. A chunk counts as a hit when it contains the gold answer text. Measured, not assumed.</p></div>
        <button className="btn-gold" onClick={() => run.mutate()} disabled={run.isPending}><Play size={14} />{run.isPending ? 'Running…' : 'Run benchmark'}</button>
      </div>
      {run.isError && <p className="rounded-lg bg-rose-400/10 px-3 py-2 text-sm text-rose-300">{errMsg(run.error)}</p>}
      {d && (<>
        <div className="grid gap-4 sm:grid-cols-3">
          <div className="card p-5"><div className="label">Questions</div><div className="text-3xl font-semibold">{d.questions}</div></div>
          <div className="card p-5"><div className="label">Context tokens saved vs. full corpus</div><div className="text-3xl font-semibold">{Math.round(d.token_reduction_vs_full_corpus * 100)}%</div><div className="text-xs text-slate-500">top-{d.k} clauses vs. all {d.corpus_tokens.toLocaleString()} tokens</div></div>
          <div className="card p-5"><div className="label">Best MRR</div><div className="text-3xl font-semibold">{Math.max(...Object.values(d.modes).map((m) => m.mrr)).toFixed(2)}</div></div>
        </div>
        <div className="card p-5"><ResponsiveContainer width="100%" height={300}>
          <BarChart data={rows}><CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.10)" /><XAxis dataKey="mode" fontSize={12} /><YAxis domain={[0, 1]} fontSize={12} /><Tooltip /><Legend />
            <Bar dataKey="hit@1" fill="#60a5fa" /><Bar dataKey="hit@5" fill="#b8893b" /><Bar dataKey="MRR" fill="#0d9488" /></BarChart></ResponsiveContainer></div>
        <div className="card overflow-x-auto"><table className="w-full text-left text-sm"><thead className="border-b border-white/10 text-xs uppercase text-slate-400"><tr><th className="p-3">Strategy</th><th>hit@1</th><th>hit@3</th><th>hit@5</th><th>MRR</th><th>Latency</th><th>Context tokens</th></tr></thead>
          <tbody className="divide-y divide-white/10">{Object.entries(d.modes).map(([k, v]) => <tr key={k}><td className="p-3 font-medium">{LABEL[k]}</td><td>{v['hit@1']}</td><td>{v['hit@3']}</td><td>{v['hit@5']}</td><td>{v.mrr}</td><td>{v.avg_latency_ms} ms</td><td>{v.avg_context_tokens}</td></tr>)}</tbody></table></div>
      </>)}
    </div>
  )
}
