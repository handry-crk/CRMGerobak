import { api } from '../api.js'

const KEY = 'sb_admin'
export function getAdmin() { try { return JSON.parse(localStorage.getItem(KEY) || 'null') } catch { return null } }
export function setAdmin(v) { try { v ? localStorage.setItem(KEY, JSON.stringify(v)) : localStorage.removeItem(KEY) } catch { /* ignore */ } }

export function adminApi(path, opts = {}) {
  const a = getAdmin()
  return api(path, { ...opts, device: false, headers: { ...(opts.headers || {}), ...(a ? { Authorization: `Bearer ${a.token}` } : {}) } })
}

export async function downloadWithAuth(path, filename) {
  const a = getAdmin()
  const res = await fetch(path, { headers: { Authorization: `Bearer ${a.token}` } })
  if (!res.ok) throw new Error('Gagal mengunduh')
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const el = document.createElement('a')
  el.href = url; el.download = filename; el.click()
  setTimeout(() => URL.revokeObjectURL(url), 5000)
}

export async function openWithAuth(path) {
  const a = getAdmin()
  const res = await fetch(path, { headers: { Authorization: `Bearer ${a.token}` } })
  const blob = await res.blob()
  window.open(URL.createObjectURL(blob), '_blank')
}

export const today = () => new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Jakarta' })
export const daysAgo = (n) => { const d = new Date(Date.now() - n * 86400000); return d.toLocaleDateString('sv-SE', { timeZone: 'Asia/Jakarta' }) }
