import axios from 'axios'

export const api = axios.create({ baseURL: '/api/v1' })
export const errMsg = (e: unknown): string => {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof d === 'string' ? d : 'Something went wrong'
}
export const sevCls: Record<string, string> = {
  high: 'bg-rose-400/15 text-rose-300 ring-rose-400/30', medium: 'bg-amber-400/15 text-amber-200 ring-amber-400/30',
  low: 'bg-sky-400/15 text-sky-300 ring-sky-400/30', info: 'bg-white/[0.07] text-stone-600 ring-white/10',
}
export const typeColor: Record<string, string> = {
  PARTY: '#1d4ed8', PERSON: '#7c3aed', DATE: '#0d9488', AMOUNT: '#b8893b', DURATION: '#0891b2', JURISDICTION: '#dc2626',
  TERM: '#64748b', DOCUMENT: '#f1f5f9', CLAUSE: '#a8a29e', OBLIGATION: '#ea580c',
}
