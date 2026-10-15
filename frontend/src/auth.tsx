import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, type ReactNode } from 'react'
import { api, tokens } from './api'

export interface User { id: number; name: string; email: string }
interface Ctx { user: User | null; loading: boolean; login: (email: string, password: string) => Promise<void>; register: (name: string, email: string, password: string) => Promise<void>; logout: () => void }
const AuthCtx = createContext<Ctx>(null!)
export const useAuth = () => useContext(AuthCtx)

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const { data: user, isLoading } = useQuery({ queryKey: ['me'], queryFn: async () => (await api.get<User>('/auth/me')).data, enabled: !!tokens.access, retry: false })

  const login = async (email: string, password: string) => {
    const r = await api.post('/auth/login', new URLSearchParams({ username: email, password }))
    tokens.set(r.data.access_token, r.data.refresh_token)
    qc.setQueryData(['me'], (await api.get<User>('/auth/me')).data)   // seed the cache: the query was disabled until a token existed
  }
  const register = async (name: string, email: string, password: string) => { await api.post('/auth/register', { name, email, password }); await login(email, password) }
  const logout = () => { tokens.clear(); qc.clear(); window.location.href = '/login' }
  return <AuthCtx.Provider value={{ user: user ?? null, loading: !!tokens.access && isLoading, login, register, logout }}>{children}</AuthCtx.Provider>
}
