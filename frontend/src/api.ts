import axios from 'axios'

const ACCESS = 'ldi_access'
const REFRESH = 'ldi_refresh'
const read = (k: string) => { try { return localStorage.getItem(k) } catch { return null } }
const write = (k: string, v: string | null) => { try { v ? localStorage.setItem(k, v) : localStorage.removeItem(k) } catch { /* storage unavailable */ } }

export const tokens = {
  get access() { return read(ACCESS) },
  get refresh() { return read(REFRESH) },
  set(a: string, r: string) { write(ACCESS, a); write(REFRESH, r) },
  clear() { write(ACCESS, null); write(REFRESH, null) },
}

export const api = axios.create({ baseURL: '/api/v1' })
api.interceptors.request.use((cfg) => { if (tokens.access) cfg.headers.Authorization = `Bearer ${tokens.access}`; return cfg })

// One shared refresh for every request that gets a 401 at the same moment.
let refreshing: Promise<boolean> | null = null
export function refreshTokens(): Promise<boolean> {
  refreshing ??= axios.post('/api/v1/auth/refresh', { refresh_token: tokens.refresh })
    .then((r) => { tokens.set(r.data.access_token, r.data.refresh_token); return true })
    .catch(() => { tokens.clear(); return false })
    .finally(() => { refreshing = null })
  return refreshing
}

api.interceptors.response.use((r) => r, async (error) => {
  const cfg = error.config
  if (error.response?.status === 401 && tokens.refresh && !cfg._retried && !cfg.url?.includes('/auth/')) {
    cfg._retried = true
    if (await refreshTokens()) { cfg.headers.Authorization = `Bearer ${tokens.access}`; return api(cfg) }
    window.location.href = '/login'
  }
  return Promise.reject(error)
})

/** fetch() with the bearer token and one refresh-and-retry: used for streaming (SSE) endpoints axios can't stream. */
export async function authFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const go = () => fetch(url, { ...init, headers: { ...(init.headers as Record<string, string>), ...(tokens.access ? { Authorization: `Bearer ${tokens.access}` } : {}) } })
  let res = await go()
  if (res.status === 401 && tokens.refresh && (await refreshTokens())) res = await go()
  return res
}

/** Read a server-sent-events response, calling `onEvent` for each JSON payload. */
export async function readSSE(res: Response, onEvent: (ev: any) => void): Promise<void> {  // eslint-disable-line @typescript-eslint/no-explicit-any
  if (!res.ok || !res.body) throw new Error((await res.json().catch(() => ({}))).detail ?? `HTTP ${res.status}`)
  const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = ''
  for (;;) {
    const { done, value } = await reader.read(); if (done) break
    buf += dec.decode(value, { stream: true })
    const parts = buf.split('\n\n'); buf = parts.pop() ?? ''
    for (const part of parts) if (part.startsWith('data: ')) onEvent(JSON.parse(part.slice(6)))
  }
}

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
