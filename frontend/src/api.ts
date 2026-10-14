import axios from 'axios'

export const api = axios.create({ baseURL: '/api/v1' })
export const errMsg = (e: unknown): string => {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof d === 'string' ? d : 'Something went wrong'
}
export const sevCls: Record<string, string> = {
  high: 'bg-rose-100 text-rose-700 ring-rose-200', medium: 'bg-amber-100 text-amber-800 ring-amber-200',
  low: 'bg-sky-100 text-sky-700 ring-sky-200', info: 'bg-stone-100 text-stone-600 ring-stone-200',
}
export const typeColor: Record<string, string> = {
  PARTY: '#1d4ed8', PERSON: '#7c3aed', DATE: '#0d9488', AMOUNT: '#b8893b', DURATION: '#0891b2', JURISDICTION: '#dc2626',
  TERM: '#64748b', DOCUMENT: '#0a1226', CLAUSE: '#a8a29e', OBLIGATION: '#ea580c',
}
