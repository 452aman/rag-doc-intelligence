import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, FileText, Loader2, RotateCcw, ShieldAlert, Trash2, UploadCloud } from 'lucide-react'
import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, errMsg, sevCls } from '../api'
import type { Doc } from '../types'

const kindLabel: Record<string, string> = { nda: 'NDA', msa: 'Services agreement', employment: 'Employment', lease: 'Lease', sale: 'Sale', other: 'Document' }

export default function Documents() {
  const qc = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [drag, setDrag] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const { data: docs = [] } = useQuery({
    queryKey: ['docs'], queryFn: async () => (await api.get<Doc[]>('/documents')).data,
    refetchInterval: (q) => (q.state.data?.some((d) => d.status === 'queued' || d.status === 'processing') ? 1500 : false),
  })
  const refresh = () => { qc.invalidateQueries({ queryKey: ['docs'] }); qc.invalidateQueries({ queryKey: ['stats'] }) }
  const upload = useMutation({
    mutationFn: async (files: File[]) => { const dups: string[] = []; for (const f of files) { const fd = new FormData(); fd.append('file', f); const r = await api.post('/documents', fd); if (r.data.duplicate) dups.push(f.name) } return dups },
    onSuccess: (dups) => { refresh(); if (dups?.length) setNotice(`${dups.join(', ')} ${dups.length > 1 ? 'were' : 'was'} already uploaded, so nothing new was added.`) }, onError: (e) => setError(errMsg(e)),
  })
  const samples = useMutation({ mutationFn: async () => api.post('/documents/load-samples'), onSuccess: refresh })
  const retry = useMutation({ mutationFn: async (id: number) => api.post(`/documents/${id}/retry`), onSuccess: refresh, onError: (e) => setError(errMsg(e)) })
  const remove = useMutation({ mutationFn: async (id: number) => api.delete(`/documents/${id}`), onSuccess: refresh })
  const drop = (e: React.DragEvent) => { e.preventDefault(); setDrag(false); setError(''); upload.mutate([...e.dataTransfer.files]) }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h1 className="text-2xl font-semibold">Documents</h1><p className="text-sm text-slate-400">Upload contracts. Each is chunked by clause, embedded, and mapped into a knowledge graph.</p></div>
        <button className="btn-gold" onClick={() => samples.mutate()} disabled={samples.isPending}>Load sample contracts</button>
      </div>
      <div onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)} onDrop={drop} onClick={() => input.current?.click()}
        className={`flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed p-8 text-center transition ${drag ? 'border-gold bg-amber-400/10' : 'border-white/15 bg-white/[0.04] hover:bg-white/[0.07]'}`}>
        <UploadCloud className="text-gold" size={30} />
        <div className="font-medium">{upload.isPending ? 'Uploading…' : 'Drop PDF, DOCX, TXT or MD files here, or click to browse'}</div>
        <input ref={input} type="file" multiple hidden accept=".pdf,.docx,.txt,.md" onChange={(e) => { setError(''); upload.mutate([...(e.target.files ?? [])]) }} />
      </div>
      {notice && <p className="rounded-lg bg-sky-400/10 px-3 py-2 text-sm text-sky-300">{notice}</p>}
      {error && <p className="rounded-lg bg-rose-400/10 px-3 py-2 text-sm text-rose-300">{error}</p>}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {docs.map((d) => (
          <div key={d.id} className="card flex flex-col gap-3 p-5">
            <div className="flex items-start gap-3">
              <FileText className="mt-0.5 shrink-0 text-gold" />
              <div className="min-w-0 flex-1">
                {d.status === 'ready' ? <Link to={`/documents/${d.id}`} className="block truncate font-medium hover:underline">{d.name}</Link> : <div className="truncate font-medium">{d.name}</div>}
                <div className="text-xs text-slate-400">{kindLabel[d.kind] ?? d.kind}{d.status === 'ready' && ` · ${d.chunk_count} clauses · ${d.entity_count} entities`}</div>
              </div>
              <button className="text-slate-500 hover:text-rose-400" onClick={() => confirm(`Delete ${d.name}?`) && remove.mutate(d.id)} aria-label="Delete"><Trash2 size={16} /></button>
            </div>
            {(d.status === 'queued' || d.status === 'processing') && (
              <div><div className="mb-1 flex items-center gap-2 text-xs text-slate-400"><Loader2 size={12} className="animate-spin" />{d.stage}</div>
                <div className="h-1.5 rounded bg-white/[0.07]"><div className="h-1.5 rounded bg-gold transition-all" style={{ width: `${d.progress}%` }} /></div></div>)}
            {d.status === 'failed' && <div className="space-y-2"><p className="flex items-start gap-1 text-xs text-rose-400"><AlertTriangle size={12} className="mt-0.5 shrink-0" />{d.error}</p><button className="btn-ghost" disabled={retry.isPending} onClick={() => retry.mutate(d.id)}><RotateCcw size={13} />Retry</button></div>}
            {d.status === 'ready' && (
              <div className="flex gap-1.5">{(['high', 'medium', 'low', 'info'] as const).filter((s) => d.risk_counts[s] > 0).map((s) => (
                <span key={s} className={`rounded px-2 py-0.5 text-xs font-medium ring-1 ${sevCls[s]}`}>{d.risk_counts[s]} {s}</span>))}
                {d.suspicious_chunks > 0 && <span title="Instruction-like text found. It is fenced as data and never obeyed." className="flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium text-amber-300 ring-1 ring-amber-400/40"><ShieldAlert size={12} />{d.suspicious_chunks} flagged</span>}</div>)}
          </div>
        ))}
      </div>
      {docs.length === 0 && <p className="py-10 text-center text-slate-400">No documents yet. Load the samples to try it out.</p>}
    </div>
  )
}
