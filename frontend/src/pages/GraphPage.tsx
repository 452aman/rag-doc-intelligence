import { useQuery } from '@tanstack/react-query'
import { useMemo, useRef, useState } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { api, typeColor } from '../api'
import type { Doc, GraphData } from '../types'

interface N { id: number; name: string; type: string; degree: number; docs: number[]; x?: number; y?: number }

export default function GraphPage() {
  const [docId, setDocId] = useState<number | ''>('')
  const [hidden, setHidden] = useState<string[]>(['CLAUSE', 'TERM'])
  const [sel, setSel] = useState<N | null>(null)
  const box = useRef<HTMLDivElement>(null)
  const { data: docs = [] } = useQuery({ queryKey: ['docs'], queryFn: async () => (await api.get<Doc[]>('/documents')).data })
  const { data } = useQuery({ queryKey: ['graph', docId], queryFn: async () => (await api.get<GraphData>('/graph', { params: { doc_id: docId || undefined, max_nodes: 150 } })).data })
  const graph = useMemo(() => {
    if (!data) return { nodes: [] as N[], links: [] as { source: number; target: number; label: string }[] }
    const nodes = data.nodes.filter((n) => !hidden.includes(n.type)).map((n) => ({ ...n }))
    const ids = new Set(nodes.map((n) => n.id))
    return { nodes, links: data.links.filter((l) => ids.has(l.source) && ids.has(l.target)).map((l) => ({ ...l })) }
  }, [data, hidden])
  const neighbours = useMemo(() => sel ? graph.links.filter((l) => (l.source as unknown as N).id === sel.id || (l.target as unknown as N).id === sel.id || l.source === sel.id || l.target === sel.id) : [], [graph, sel])
  const types = [...new Set(data?.nodes.map((n) => n.type) ?? [])]
  const nameOf = (v: unknown) => (typeof v === 'object' ? (v as N).name : graph.nodes.find((n) => n.id === v)?.name)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-4">
        <div><h1 className="text-2xl font-semibold">Knowledge graph</h1><p className="text-sm text-slate-400">Entities and relations extracted from your contracts. Shared entities connect documents.</p></div>
        <select className="input ml-auto w-auto" value={docId} onChange={(e) => setDocId(e.target.value ? +e.target.value : '')}><option value="">All documents</option>{docs.filter((d) => d.status === 'ready').map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select>
      </div>
      <div className="flex flex-wrap gap-2">{types.map((t) => (
        <button key={t} onClick={() => setHidden(hidden.includes(t) ? hidden.filter((x) => x !== t) : [...hidden, t])}
          className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium ${hidden.includes(t) ? 'border-white/10 text-slate-500 line-through' : 'border-white/15 bg-white/[0.04]'}`}>
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: typeColor[t] ?? '#999' }} />{t}</button>))}</div>
      <div className="grid gap-4 lg:grid-cols-[1fr_280px]">
        <div ref={box} className="card overflow-hidden" style={{ height: 600 }}>
          {graph.nodes.length === 0 ? <p className="p-10 text-center text-slate-400">No graph yet. Load documents first.</p> : (
            <ForceGraph2D graphData={graph} width={box.current?.clientWidth ?? 800} height={600} nodeRelSize={4} cooldownTicks={120}
              nodeColor={(n) => typeColor[(n as N).type] ?? '#999'} nodeVal={(n) => 1 + Math.sqrt((n as N).degree)}
              linkColor={() => 'rgba(148,163,184,0.35)'} onNodeClick={(n) => setSel(n as N)}
              nodeCanvasObjectMode={() => 'after'}
              nodeCanvasObject={(n, ctx, scale) => { const node = n as N; if (scale < 1.6 && node.degree < 4 && sel?.id !== node.id) return
                ctx.font = `${11 / scale}px Inter, sans-serif`; ctx.fillStyle = '#e2e8f0'; ctx.textAlign = 'center'; ctx.fillText(node.name.slice(0, 26), node.x ?? 0, (node.y ?? 0) + 9 / scale + 3) }} />)}
        </div>
        <aside className="card h-fit p-4 text-sm">
          {!sel ? <p className="text-slate-400">Click a node to inspect it.</p> : (
            <div className="space-y-3"><div><div className="font-semibold">{sel.name}</div><span className="text-xs" style={{ color: typeColor[sel.type] }}>{sel.type}</span> <span className="text-xs text-slate-500">· in {sel.docs.length} doc(s)</span></div>
              <div><div className="label">Connections</div><ul className="space-y-1">{neighbours.slice(0, 14).map((l, i) => {
                const other = nameOf(l.source) === sel.name ? nameOf(l.target) : nameOf(l.source)
                return <li key={i} className="text-xs text-slate-300"><span className="text-slate-500">{l.label}</span> {other}</li> })}</ul></div></div>)}
        </aside>
      </div>
    </div>
  )
}
