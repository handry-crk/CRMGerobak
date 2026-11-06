import { useEffect, useState } from 'react'
import { api, fmtRp, fmtTanggal } from '../api.js'

export function Header({ title, subtitle }) {
  return (
    <header className="flex items-center gap-3 px-4 pt-4 pb-2">
      <div className="w-10 h-10 rounded-xl bg-brand grid place-items-center shrink-0" aria-hidden>
        <div className="w-5 h-5 rounded-full bg-white grid place-items-center"><div className="w-2 h-2 rounded-full bg-brand" /></div>
      </div>
      <div className="min-w-0">
        <div className="text-xs font-bold text-deep uppercase tracking-wide">Cimol Bojot AA</div>
        <div className="font-extrabold truncate">{title}</div>
        {subtitle && <div className="text-xs text-charcoal/60 truncate">{subtitle}</div>}
      </div>
    </header>
  )
}

export function Dots({ active, total, pop }) {
  return (
    <div className="dots" aria-label={`${active} dari ${total} stamp`}>
      {Array.from({ length: total }).map((_, i) => (
        <div key={i} className={`dot ${i < active ? 'on' : ''} ${pop && i === active - 1 ? 'stamp-pop' : ''}`} />
      ))}
    </div>
  )
}

export function Confetti() {
  const colors = ['#D7191F', '#F7D4D5', '#B32E26', '#FFC857', '#1E8E3E']
  return (
    <div className="confetti pointer-events-none absolute inset-x-0 top-0 h-64 overflow-hidden" aria-hidden>
      {Array.from({ length: 24 }).map((_, i) => (
        <span key={i} style={{ left: `${(i * 37) % 100}%`, background: colors[i % colors.length], animationDelay: `${(i % 6) * 0.08}s` }} />
      ))}
    </div>
  )
}

export function VoucherCard({ v, canRedeem, onRedeem, hint }) {
  const scheduled = v.status === 'scheduled'
  return (
    <div className={`card ${v.status === 'active' ? 'border-brand bg-tint/40' : ''}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-extrabold leading-tight">{v.title}</div>
          <div className="text-xs text-charcoal/70 mt-1">
            {scheduled ? `Berlaku ${fmtTanggal(v.validFrom, { year: undefined })}–${fmtTanggal(v.validTo)}` : `Berlaku sampai ${fmtTanggal(v.validTo)}`}
            {v.description ? ` · ${v.description}` : ''}
          </div>
        </div>
        {v.valueRp > 0 && <div className="text-brand font-extrabold whitespace-nowrap">Rp{fmtRp(v.valueRp)}</div>}
      </div>
      {v.status === 'active' && (
        <div className="mt-3">
          <button className="btn-primary w-full" disabled={!canRedeem} onClick={() => onRedeem(v)}>Tukar sekarang di gerobak</button>
          {!canRedeem && <div className="text-xs text-center mt-2 text-charcoal/70">{hint || 'Scan QR gerobak dulu ya, Kak.'}</div>}
        </div>
      )}
      {scheduled && <div className="text-xs mt-2 text-deep font-bold">Kita ingetin pas udah bisa dipakai.</div>}
      {v.status === 'used' && <div className="text-xs mt-2 text-charcoal/60">Sudah ditukar {v.usedOutletName ? `di ${v.usedOutletName}` : ''} · {fmtTanggal(v.usedAt)}</div>}
    </div>
  )
}

/** Bottom sheet konfirmasi + layar hijau penukaran. Crew hanya melihat, tidak menyentuh perangkat. */
export function RedeemFlow({ voucher, qrToken, outletName, countdownSec = 180, onClose, onUsed }) {
  const [step, setStep] = useState('confirm') // confirm | busy | green | done | error
  const [err, setErr] = useState('')
  const [data, setData] = useState(null)
  const [left, setLeft] = useState(countdownSec)
  const [clock, setClock] = useState('')

  useEffect(() => {
    if (step !== 'green') return
    const end = Date.now() + countdownSec * 1000
    const t = setInterval(() => {
      const s = Math.max(0, Math.round((end - Date.now()) / 1000))
      setLeft(s)
      setClock(new Date().toLocaleTimeString('id-ID', { timeZone: 'Asia/Jakarta', hour12: false }))
      if (s <= 0) { clearInterval(t); setStep('done') }
    }, 250)
    return () => clearInterval(t)
  }, [step, countdownSec])

  async function doRedeem() {
    setStep('busy')
    try {
      const d = await api(`/api/voucher/${voucher.id}/redeem`, { method: 'POST', body: { qrToken } })
      setData(d)
      onUsed?.(d)
      setStep('green')
    } catch (e) {
      setErr(e.message)
      setStep('error')
    }
  }

  if (step === 'confirm' || step === 'busy' || step === 'error') {
    return (
      <div className="fixed inset-0 z-50 bg-black/50 flex items-end" onClick={onClose}>
        <div className="bg-white w-full rounded-t-3xl p-5 pb-8" onClick={(e) => e.stopPropagation()}>
          <div className="font-extrabold text-lg">{voucher.title}</div>
          <p className="mt-2 text-sm">Tunjukkan layar ini ke crew, lalu tekan <b>Tukar</b>. Voucher hangus setelah ditekan, ya.</p>
          {step === 'error' && <div className="mt-3 text-sm text-brand font-bold">{err}</div>}
          <div className="mt-4 grid grid-cols-2 gap-3">
            <button className="btn-ghost" onClick={onClose}>Nanti dulu</button>
            <button className="btn-primary" disabled={step === 'busy'} onClick={doRedeem}>{step === 'busy' ? 'Sebentar…' : 'Tukar'}</button>
          </div>
        </div>
      </div>
    )
  }

  const pct = Math.round((left / countdownSec) * 100)
  const green = step === 'green'
  return (
    <div className={`fixed inset-0 z-50 flex flex-col text-white ${green ? 'bg-okgreen stripes' : 'bg-neutral-500'}`}>
      <div className="flex-1 flex flex-col items-center justify-center px-6 text-center">
        <div className="text-sm font-bold uppercase tracking-widest opacity-90">{green ? 'Voucher ditukar' : 'Sudah ditukar'}</div>
        <div className="mt-3 text-4xl font-extrabold leading-tight">{voucher.title}</div>
        <div className="mt-6 text-lg font-bold">{outletName || data?.usedOutletName}</div>
        {green ? (
          <>
            <div className="mt-1 text-5xl font-extrabold tabular-nums">{clock}</div>
            <div className="mt-6 text-6xl font-extrabold tracking-[0.3em]">{data?.redeemCode}</div>
            <div className="mt-8 w-full max-w-xs h-3 rounded-full bg-white/30 overflow-hidden"><div className="h-full bg-white transition-all" style={{ width: `${pct}%` }} /></div>
            <div className="mt-2 text-sm opacity-90">Berlaku {left} detik lagi</div>
          </>
        ) : (
          <div className="mt-4 text-lg">Sudah ditukar {data?.usedAt ? fmtTanggal(data.usedAt) : ''}</div>
        )}
      </div>
      <div className="p-5">
        <button className="btn w-full bg-white/20 text-white" onClick={onClose}>{green ? 'Selesai, hadiah sudah diterima' : 'Tutup'}</button>
      </div>
    </div>
  )
}

/** Nomor diseragamkan ke 08xxxxxxxx: hanya angka, +62/62 di depan otomatis jadi 0. */
export function tidyPhone(raw) {
  let d = (raw || '').replace(/\D/g, '')
  if (d.startsWith('62')) d = '0' + d.slice(2)
  else if (d.startsWith('8')) d = '0' + d
  return d.slice(0, 13)
}
export const phoneOk = (p) => /^08\d{8,11}$/.test(p)

export function PhoneForm({ onSubmit, busy, error, headline, sub, requireName = false, submitLabel = 'Ambil stamp' }) {
  const [phone, setPhone] = useState('')
  const [name, setName] = useState('')
  const [optIn, setOptIn] = useState(true)
  const ready = phoneOk(phone) && (!requireName || name.trim().length >= 2)
  return (
    <form className="px-4 pt-2" onSubmit={(e) => { e.preventDefault(); if (ready) onSubmit(phone, optIn, name.trim()) }}>
      <h1 className="text-2xl font-extrabold leading-tight">{headline || 'Scan, dapet stamp.'}</h1>
      <p className="mt-1 text-charcoal/80">{sub}</p>
      {requireName && (
        <>
          <label className="block mt-5 text-sm font-bold" htmlFor="name">Nama panggilan</label>
          <input id="name" className="input mt-1" autoComplete="given-name" placeholder="Contoh: Dina" maxLength={40} value={name}
            onChange={(e) => setName(e.target.value)} autoFocus required />
        </>
      )}
      <label className={`block ${requireName ? 'mt-3' : 'mt-5'} text-sm font-bold`} htmlFor="phone">No. WhatsApp</label>
      <input id="phone" className="input mt-1" inputMode="numeric" autoComplete="tel-national" placeholder="081234567890" value={phone}
        onChange={(e) => setPhone(tidyPhone(e.target.value))} autoFocus={!requireName} required />
      {phone && !phoneOk(phone) && <div className="mt-1 text-xs text-charcoal/60">Tulis mulai 08, 10–13 angka.</div>}
      {error && <div className="mt-2 text-sm text-brand font-bold">{error}</div>}
      <button className="btn-primary w-full mt-4" disabled={busy || !ready}>{busy ? 'Sebentar…' : submitLabel}</button>
      <p className="mt-3 text-xs text-charcoal/70">Nomor cuma dipakai buat info promo &amp; voucher. Nggak ada spam.</p>
      <label className="mt-2 flex items-center gap-2 text-xs"><input type="checkbox" checked={optIn} onChange={(e) => setOptIn(e.target.checked)} /> Boleh kirim info promo via WA</label>
    </form>
  )
}
