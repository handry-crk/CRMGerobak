import { useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { api } from '../api.js'
import { adminApi, getAdmin, setAdmin } from './adminApi.js'
import Ringkasan from './Ringkasan.jsx'
import Outlets from './Outlets.jsx'
import Members from './Members.jsx'
import Vouchers from './Vouchers.jsx'
import Rating from './Rating.jsx'
import Settings from './Settings.jsx'
import AntiFraud from './AntiFraud.jsx'
import { Toast } from './ui.jsx'

function Login({ onLogin }) {
  const [names, setNames] = useState([])
  const [name, setName] = useState('')
  const [pin, setPin] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { api('/api/admin/login/names', { device: false }).then(setNames).catch(() => {}) }, [])
  async function submit(e) {
    e.preventDefault(); setBusy(true); setErr('')
    try {
      const r = await api('/api/admin/login', { method: 'POST', device: false, body: { name, pin } })
      setAdmin({ token: r.token, user: r.user })
      onLogin(r.user)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <main className="min-h-screen grid place-items-center p-4">
      <form onSubmit={submit} className="card w-full max-w-sm">
        <div className="bg-brand text-white rounded-xl p-4 -m-4 mb-4"><div className="text-xs font-bold uppercase opacity-80">Cimol Bojot AA</div><div className="text-xl font-extrabold">Stamp Bojot · Admin</div></div>
        <label className="block text-sm font-bold">Nama</label>
        <select className="input mt-1" value={name} onChange={(e) => setName(e.target.value)} required>
          <option value="">Pilih nama…</option>
          {names.map((n) => <option key={n}>{n}</option>)}
        </select>
        <label className="block text-sm font-bold mt-3">PIN</label>
        <input className="input mt-1" type="password" inputMode="numeric" maxLength={6} value={pin} onChange={(e) => setPin(e.target.value)} required />
        {err && <div className="text-sm text-brand font-bold mt-2">{err}</div>}
        <button className="btn-primary w-full mt-4" disabled={busy}>Masuk</button>
      </form>
    </main>
  )
}

const NAV = [
  ['', 'Ringkasan'], ['outlet', 'Outlet & QR'], ['member', 'Member'], ['voucher', 'Voucher'], ['rating', 'Rating'], ['antifraud', 'Anti-fraud'], ['pengaturan', 'Pengaturan'],
]

export default function Admin() {
  const [user, setUser] = useState(getAdmin()?.user || null)
  const [meta, setMeta] = useState({ areas: [], roles: [] })
  const [toast, setToast] = useState('')

  useEffect(() => {
    if (!user) return
    adminApi('/api/admin/me').then(setUser).catch(() => { setAdmin(null); setUser(null) })
    adminApi('/api/admin/meta').then(setMeta).catch(() => {})
  }, [user?.id])

  function notify(msg) { setToast(msg); setTimeout(() => setToast(''), 2500) }

  if (!user) return <Login onLogin={setUser} />
  const privileged = ['CRM Lead', 'Manager'].includes(user.role)
  const ctx = { user, meta, notify, privileged, lead: user.role === 'CRM Lead' }

  return (
    <div className="min-h-screen bg-[#FAF7F7]">
      <header className="bg-brand text-white">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between gap-3">
          <div><div className="text-[10px] font-bold uppercase opacity-80">Cimol Bojot AA</div><div className="font-extrabold">Stamp Bojot · Dashboard</div></div>
          <div className="text-right text-xs"><div className="font-bold">{user.name}</div><div className="opacity-80">{user.role}{user.areas?.length ? ` · ${user.areas.join(', ')}` : ''}</div>
            <button className="underline mt-0.5" onClick={() => { setAdmin(null); setUser(null) }}>Keluar</button></div>
        </div>
        <nav className="max-w-6xl mx-auto px-2 flex gap-1 overflow-x-auto no-scrollbar">
          {NAV.filter(([p]) => p !== 'pengaturan' || privileged).map(([p, label]) => (
            <NavLink key={p} to={`/admin/${p}`} end={p === ''} className={({ isActive }) => `whitespace-nowrap px-3 py-2 text-sm font-bold rounded-t-lg ${isActive ? 'bg-white text-brand' : 'text-white/90'}`}>{label}</NavLink>
          ))}
        </nav>
      </header>
      <main className="max-w-6xl mx-auto p-4">
        <Routes>
          <Route index element={<Ringkasan ctx={ctx} />} />
          <Route path="outlet" element={<Outlets ctx={ctx} />} />
          <Route path="member" element={<Members ctx={ctx} />} />
          <Route path="voucher" element={<Vouchers ctx={ctx} />} />
          <Route path="rating" element={<Rating ctx={ctx} />} />
          <Route path="antifraud" element={<AntiFraud ctx={ctx} />} />
          <Route path="pengaturan" element={privileged ? <Settings ctx={ctx} /> : <Navigate to="/admin" replace />} />
          <Route path="*" element={<Navigate to="/admin" replace />} />
        </Routes>
      </main>
      <Toast msg={toast} />
    </div>
  )
}
