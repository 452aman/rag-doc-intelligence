export interface Doc {
  id: number; name: string; kind: string; status: 'queued' | 'processing' | 'ready' | 'failed'; stage: string; progress: number
  pages: number; chunk_count: number; entity_count: number; est_tokens: number; error: string | null; created_at: string
  risk_counts: { high: number; medium: number; low: number; info: number }
}
export interface Risk { topic: string; severity: 'high' | 'medium' | 'low' | 'info'; why: string; section: string; chunk_id: number | null; quote: string }
export interface DocDetail extends Doc {
  key_facts: { parties: string[]; dates: string[]; amounts: string[]; durations: string[]; jurisdictions: string[] }
  risks: Risk[]
  chunks: { id: number; idx: number; section: string; page: number; text: string }[]
}
export interface Citation { n: number; chunk_id: number; doc_id: number; doc_name: string; section: string; page: number; text: string; score: number; via: string[] }
export interface AnswerMeta {
  latency_ms: number; retrieval_ms: number; prompt_tokens: number; corpus_tokens: number; token_reduction: number | null
  mode: string; uncited?: boolean; cited?: number[]; entities?: string[]; graph_facts?: string[]; query?: string
}
export interface ChatMessage { id?: number; role: 'user' | 'assistant'; content: string; citations?: Citation[]; meta?: AnswerMeta; streaming?: boolean; error?: string }
export interface Conversation { id: number; title: string }
export interface GraphData { nodes: { id: number; name: string; type: string; degree: number; docs: number[] }[]; links: { source: number; target: number; label: string }[] }
export interface EvalMode { 'hit@1': number; 'hit@3': number; 'hit@5': number; mrr: number; avg_latency_ms: number; avg_context_tokens: number; failed: string[] }
export interface EvalResult { questions: number; k: number; corpus_tokens: number; token_reduction_vs_full_corpus: number; modes: Record<string, EvalMode> }
