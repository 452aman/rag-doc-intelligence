import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { errMsg } from '../api'
import { useAuth } from '../auth'
import Logo from '../components/Logo'

export default function Auth({ mode }: { mode: 'login' | 'register' }) {
  const { user, login, register } = useAuth()
  const navigate = useNavigate()
  const [f, setF] = useState({ name: '', email: '', password: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  if (user) return <Navigate to="/" replace />
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value })
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setError('')
    try { mode === 'register' ? await register(f.name, f.email, f.password) : await login(f.email, f.password); navigate('/') }
    catch (err) { setError(errMsg(err)) } finally { setBusy(false) }
  }
  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={submit} className="card w-full max-w-sm space-y-4 p-8">
        <div className="flex items-center gap-2 text-xl font-semibold"><Logo className="h-8 w-8" />Legal Document Intelligence</div>
        <p className="text-sm text-slate-400">{mode === 'login' ? 'Sign in to your private contract workspace.' : 'Create an account. Your contracts stay private to you.'}</p>
        {mode === 'register' && <div><label className="label">Name</label><input className="input" required minLength={2} value={f.name} onChange={set('name')} /></div>}
        <div><label className="label">Email</label><input className="input" type="email" required value={f.email} onChange={set('email')} /></div>
        <div><label className="label">Password</label><input className="input" type="password" required minLength={mode === 'register' ? 8 : 1} value={f.password} onChange={set('password')} /></div>
        {error && <p className="rounded-lg bg-rose-400/10 px-3 py-2 text-sm text-rose-300">{error}</p>}
        <button className="btn-gold w-full" disabled={busy}>{busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}</button>
        <p className="text-center text-sm text-slate-400">{mode === 'login' ? <>New here? <Link className="text-gold hover:underline" to="/register">Create an account</Link></> : <>Have an account? <Link className="text-gold hover:underline" to="/login">Sign in</Link></>}</p>
      </form>
    </div>
  )
}
