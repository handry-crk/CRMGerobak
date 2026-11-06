// Klien API ringan. Device token member disimpan di localStorage (dibungkus try/catch).
const DEVICE_KEY = 'sb_device'
const LAST_QR_KEY = 'sb_last_qr'

export function getDevice() {
  try { return localStorage.getItem(DEVICE_KEY) || null } catch { return null }
}
export function setDevice(tok) {
  try { tok ? localStorage.setItem(DEVICE_KEY, tok) : localStorage.removeItem(DEVICE_KEY) } catch { /* ignore */ }
}
export function rememberQr(token) {
  try { sessionStorage.setItem(LAST_QR_KEY, JSON.stringify({ token, at: Date.now() })) } catch { /* ignore */ }
}
export function lastQr(maxAgeMin = 60) {
  try {
    const v = JSON.parse(sessionStorage.getItem(LAST_QR_KEY) || 'null')
    if (v && Date.now() - v.at < maxAgeMin * 60000) return v.token
  } catch { /* ignore */ }
  return null
}

export function requestId() {
  return Math.random().toString(36).slice(2) + Date.now().toString(36)
}

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail?.message || 'Terjadi kesalahan')
    this.status = status
    this.code = detail?.code
  }
}

export async function api(path, { method = 'GET', body, headers = {}, device = true, raw = false } = {}) {
  const h = { ...headers }
  if (body) h['Content-Type'] = 'application/json'
  const dev = device ? getDevice() : null
  if (dev) h['X-Device-Token'] = dev
  const res = await fetch(path, { method, headers: h, body: body ? JSON.stringify(body) : undefined })
  if (raw) return res
  let data = null
  try { data = await res.json() } catch { /* empty */ }
  if (!res.ok) throw new ApiError(res.status, data?.detail || { message: res.statusText })
  return data
}

export const fmtRp = (n) => new Intl.NumberFormat('id-ID').format(Math.round(n || 0))
export const fmtTanggal = (iso, opts = {}) => {
  if (!iso) return '–'
  const d = new Date(iso.length === 10 ? iso + 'T00:00:00+07:00' : iso)
  return d.toLocaleDateString('id-ID', { timeZone: 'Asia/Jakarta', day: 'numeric', month: 'long', year: 'numeric', ...opts })
}
export const fmtJam = (iso) => new Date(iso).toLocaleTimeString('id-ID', { timeZone: 'Asia/Jakarta', hour: '2-digit', minute: '2-digit' })
