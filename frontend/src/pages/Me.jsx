import { useEffect, useState } from 'react'
import { api, fmtTanggal, getDevice, lastQr, setDevice } from '../api.js'
import { Dots, Header, PhoneForm, RedeemFlow, VoucherCard } from '../components/Shared.jsx'
import { FeedbackBlock, useFeedbackMeta } from '../components/Feedback.jsx'

export default function Me() {
  const [data, setData] = useState(null)
  const [phase, setPhase] = useState(getDevice() ? 'loading' : 'phone')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [redeem, setRedeem] = useState(null)
  const [showHistory, setShowHistory] = useState(false)
  const qr = lastQr()
  const meta = useFeedbackMeta()

  async function load() {
    try {
      const d = await api('/api/me')
      setData(d)
      setPhase('ok')
    } catch (e) {
      if (e.status === 401) { setDevice(null); setPhase('phone') } else setErr(e.message)
    }
  }
  useEffect(() => { if (phase === 'loading') load() }, [phase])

  async function switchDevice(phone) {
    setBusy(true); setErr('')
    try {
      const r = await api('/api/me/switch-device', { method: 'POST', device: false, body: { phone } })
      setDevice(r.deviceToken)
      setPhase('loading')
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  async function toggleOptIn() {
    const r = await api('/api/me/opt-out', { method: 'POST' })
    setData((d) => ({ ...d, member: { ...d.member, optIn: r.optIn } }))
  }

  if (phase === 'phone') {
    return (
      <main className="max-w-[420px] mx-auto min-h-screen pb-10">
        <Header title="Stamp Bojot" subtitle="Stamp & voucher saya" />
        <PhoneForm onSubmit={switchDevice} busy={busy} error={err} headline="Lanjutin stamp di HP ini" sub="Masukkan nomor WhatsApp yang dipakai saat gabung." submitLabel="Lanjutkan" />
        <p className="px-4 mt-4 text-xs text-charcoal/60">Belum pernah gabung? Scan QR di gerobak Cimol Bojot AA terdekat ya, Kak.</p>
      </main>
    )
  }
  if (phase === 'loading') return <main className="max-w-[420px] mx-auto p-6 text-center text-sm">Memuat…</main>

  const { member, vouchers, history, stampsPerReward, rewardTitle } = data
  const active = vouchers.filter((v) => v.status === 'active')
  const scheduled = vouchers.filter((v) => v.status === 'scheduled')
  const past = vouchers.filter((v) => ['used', 'expired'].includes(v.status))
  return (
    <main className="max-w-[420px] mx-auto min-h-screen pb-10">
      <Header title={member.name ? `Hai, ${member.name}!` : 'Stamp Bojot'} subtitle={member.maskedPhone} />
      <section className="px-4 pt-4 text-center">
        <Dots active={member.stampsActive} total={stampsPerReward} />
        <div className="mt-3 font-extrabold">{stampsPerReward - member.stampsActive} stamp lagi {rewardTitle.toLowerCase()}</div>
        <div className="text-xs text-charcoal/60 mt-1">{member.visits} kunjungan · gabung {fmtTanggal(member.joinedAt)}</div>
      </section>

      {data.pendingTaste && (
        <section className="px-4 mt-6">
          <div className="card border-brand">
            <FeedbackBlock kind="taste" stampId={data.pendingTaste.stampId} meta={meta} onDone={() => setTimeout(load, 1500)}
              title={`Cimol dari ${data.pendingTaste.outletName} ${data.pendingTaste.whenText}, rasanya gimana?`} />
          </div>
        </section>
      )}
      {active.length > 0 && (
        <section className="px-4 mt-6 space-y-3">
          <div className="font-extrabold">Voucher aktif</div>
          {active.map((v) => <VoucherCard key={v.id} v={v} canRedeem={!!qr} onRedeem={setRedeem} hint="Scan QR gerobak dulu ya, Kak." />)}
        </section>
      )}
      {scheduled.length > 0 && (
        <section className="px-4 mt-4 space-y-3">
          <div className="font-extrabold">Segera berlaku</div>
          {scheduled.map((v) => <VoucherCard key={v.id} v={v} canRedeem={false} />)}
        </section>
      )}
      {active.length === 0 && scheduled.length === 0 && (
        <section className="px-4 mt-6"><div className="card text-sm text-charcoal/70">Belum ada voucher. Kumpulin stamp dulu ya, Kak!</div></section>
      )}

      <section className="px-4 mt-6">
        <button className="btn-ghost w-full" onClick={() => setShowHistory(!showHistory)}>{showHistory ? 'Tutup riwayat' : 'Riwayat kunjungan & voucher'}</button>
        {showHistory && (
          <div className="mt-3 space-y-2 text-sm">
            {history.map((h, i) => <div key={i} className="flex justify-between border-b border-line py-2"><span>{h.outletName}</span><span className="text-charcoal/60">{fmtTanggal(h.at)}</span></div>)}
            {past.map((v) => <div key={v.id} className="flex justify-between border-b border-line py-2 text-charcoal/60"><span>{v.title}</span><span>{v.status === 'used' ? 'Ditukar' : 'Hangus'}</span></div>)}
            {history.length === 0 && past.length === 0 && <div className="text-charcoal/60">Belum ada riwayat.</div>}
          </div>
        )}
      </section>

      <section className="px-4 mt-6 space-y-3 text-sm">
        <label className="flex items-center justify-between card">
          <span>Terima info promo via WA</span>
          <input type="checkbox" checked={member.optIn} onChange={toggleOptIn} className="w-5 h-5" />
        </label>
        <button className="text-deep font-bold" onClick={() => { setDevice(null); setPhase('phone') }}>Ganti nomor / pakai HP lain</button>
      </section>

      {redeem && qr && (
        <RedeemFlow voucher={redeem} qrToken={qr} countdownSec={180} onClose={() => { setRedeem(null); load() }} />
      )}
    </main>
  )
}
