import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, getDevice, rememberQr, requestId, setDevice } from '../api.js'
import { Confetti, Dots, Header, PhoneForm, RedeemFlow, VoucherCard } from '../components/Shared.jsx'

const EMOJI = ['😖', '😕', '🙂', '😄', '🤩']

function getPosition(timeoutMs = 1500) {
  return new Promise((resolve) => {
    if (!('geolocation' in navigator)) return resolve(null)
    const t = setTimeout(() => resolve(null), timeoutMs)
    navigator.geolocation.getCurrentPosition(
      (p) => { clearTimeout(t); resolve({ lat: p.coords.latitude, lng: p.coords.longitude }) },
      () => { clearTimeout(t); resolve(null) },
      { maximumAge: 120000, timeout: timeoutMs, enableHighAccuracy: false },
    )
  })
}

export default function Scan() {
  const { token } = useParams()
  const [state, setState] = useState({ phase: 'loading' }) // loading | phone | result | error
  const [outlet, setOutlet] = useState(null)
  const [busy, setBusy] = useState(false)
  const [formErr, setFormErr] = useState('')
  const [tags, setTags] = useState([])
  const [rating, setRating] = useState(0)
  const [tag, setTag] = useState('')
  const [comment, setComment] = useState('')
  const [fbSaved, setFbSaved] = useState(false)
  const [promoOn, setPromoOn] = useState(false)
  const [profile, setProfile] = useState({ name: '', source: '' })
  const [profileDone, setProfileDone] = useState(false)
  const [sources, setSources] = useState([])
  const [redeem, setRedeem] = useState(null)
  const reqId = useRef(requestId())

  useEffect(() => {
    rememberQr(token)
    let alive = true
    ;(async () => {
      const dev = getDevice()
      try {
        if (!dev) {
          const o = await api(`/api/outlet/${token}`, { device: false })
          if (!alive) return
          setOutlet(o)
          setState({ phase: 'phone' })
          return
        }
        const pos = await getPosition()
        const res = await api('/api/stamp', { method: 'POST', device: false, body: { qrToken: token, requestId: reqId.current, deviceToken: dev, ...(pos || {}) } })
        if (!alive) return
        if (res.needPhone) { setDevice(null); setOutlet(res.outlet); setState({ phase: 'phone' }); return }
        apply(res)
      } catch (e) {
        if (alive) setState({ phase: 'error', message: e.message, code: e.code })
      }
    })()
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  useEffect(() => {
    api('/api/meta', { device: false }).then((m) => { setTags(m.feedbackTags); setSources(m.sources) }).catch(() => {})
  }, [])

  function apply(res) {
    if (res.deviceToken) setDevice(res.deviceToken)
    setOutlet(res.outlet)
    setState({ phase: 'result', res })
  }

  async function submitPhone(phone, optIn, name) {
    setBusy(true); setFormErr('')
    try {
      const pos = await getPosition(1000)
      const res = await api('/api/stamp', { method: 'POST', device: false, body: { qrToken: token, requestId: reqId.current, phone, name, optIn, deviceToken: getDevice(), ...(pos || {}) } })
      apply(res)
    } catch (e) {
      setFormErr(e.message)
    } finally { setBusy(false) }
  }

  async function sendFeedback(r, t = tag, c = comment) {
    setRating(r)
    try {
      await api('/api/feedback', { method: 'POST', body: { qrToken: token, stampId: state.res?.stampId, rating: r, tag: t || null, comment: c || null } })
      setFbSaved(true)
    } catch { /* diam saja; feedback opsional */ }
  }

  async function togglePromo() {
    const next = !promoOn
    setPromoOn(next)
    try {
      // Kirim ulang stamp dengan requestId yang sama → idempoten; promoCode dicatat di stamp yang ada
      await api('/api/stamp', { method: 'POST', device: false, body: { qrToken: token, requestId: reqId.current, deviceToken: getDevice(), promoCode: next ? outlet.promoCode : '' } })
    } catch { /* abaikan */ }
  }

  async function saveProfile(skip = false) {
    try {
      await api('/api/profile', { method: 'POST', body: skip ? { skipped: true } : { name: profile.name || null, source: profile.source || null } })
    } catch { /* abaikan */ }
    setProfileDone(true)
  }

  function onUsed(d) {
    setState((s) => ({ ...s, res: { ...s.res, vouchers: s.res.vouchers.map((v) => (v.id === d.id ? d : v)) } }))
  }

  if (state.phase === 'loading') {
    return (
      <main className="max-w-[420px] mx-auto min-h-screen">
        <Header title="Stamp Bojot" />
        <div className="px-4 pt-10 text-center">
          <div className="dots"><div className="dot" /><div className="dot" /><div className="dot" /><div className="dot" /><div className="dot" /></div>
          <div className="mt-4 text-sm text-charcoal/60">Ngecek stamp Kakak…</div>
        </div>
      </main>
    )
  }

  if (state.phase === 'error') {
    return (
      <main className="max-w-[420px] mx-auto min-h-screen">
        <Header title="Stamp Bojot" />
        <div className="px-4 pt-6">
          <div className="card border-brand"><div className="font-extrabold">Hmm, ada yang kurang pas.</div><p className="mt-1 text-sm">{state.message}</p></div>
          {state.code !== 'qr_replaced' && <button className="btn-ghost w-full mt-4" onClick={() => location.reload()}>Coba lagi</button>}
          <Link to="/saya" className="block text-center text-sm mt-4 text-deep font-bold">Lihat stamp &amp; voucher saya</Link>
        </div>
      </main>
    )
  }

  if (state.phase === 'phone') {
    return (
      <main className="max-w-[420px] mx-auto min-h-screen pb-10">
        <Header title={outlet?.name || 'Gerobak AA'} subtitle={outlet?.area} />
        <PhoneForm onSubmit={submitPhone} busy={busy} error={formErr} requireName
          sub={`${outlet?.stampsPerReward || 5} stamp = ${outlet?.rewardTitle || 'Cimol Bojot kecil gratis'}.`} />
        <div className="px-4 mt-6 text-xs text-charcoal/60">Udah pernah gabung tapi ganti HP? <Link className="text-deep font-bold" to="/saya">Masukkan nomor di sini</Link>.</div>
      </main>
    )
  }

  const { res } = state
  const canRedeem = true // sesi outlet aktif karena baru saja scan di sini
  const activeVouchers = res.vouchers.filter((v) => v.status === 'active')
  const otherVouchers = res.vouchers.filter((v) => v.status !== 'active')

  return (
    <main className="max-w-[420px] mx-auto min-h-screen pb-10 relative overflow-hidden">
      {res.rewardIssued && <Confetti />}
      <Header title={outlet.name} subtitle={outlet.area} />

      <section className="px-4 pt-4 text-center">
        <Dots active={res.rewardIssued ? res.stampsPerReward : res.stampsActive} total={res.stampsPerReward} pop={res.granted} />
        <h1 className="mt-4 text-2xl font-extrabold leading-tight">{res.headline}</h1>
        {res.isNewMember && res.welcomeVoucher && (
          <div className="mt-4 text-left"><VoucherCard v={res.welcomeVoucher} canRedeem={false} /></div>
        )}
      </section>

      {res.askFeedback && outlet.feedbackPrompt && (
        <section className="px-4 mt-6">
          <div className="card">
            <div className="font-bold text-sm">Gimana cimolnya hari ini?</div>
            <div className="mt-2 flex justify-between">
              {EMOJI.map((e, i) => (
                <button key={i} aria-label={`${i + 1} dari 5`} onClick={() => sendFeedback(i + 1)}
                  className={`w-12 h-12 text-2xl rounded-xl ${rating === i + 1 ? 'bg-tint ring-2 ring-brand' : 'bg-white'}`}>{e}</button>
              ))}
            </div>
            {rating > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {tags.map((t) => (
                  <button key={t} className={`chip ${tag === t ? 'chip-on' : ''}`} onClick={() => { setTag(t); sendFeedback(rating, t) }}>{t}</button>
                ))}
              </div>
            )}
            {rating > 0 && rating <= 2 && (
              <div className="mt-3 flex gap-2">
                <input className="input" maxLength={140} placeholder="Boleh cerita sedikit? (opsional)" value={comment} onChange={(e) => setComment(e.target.value)} />
                <button className="btn-ghost" onClick={() => sendFeedback(rating, tag, comment)}>Kirim</button>
              </div>
            )}
            {fbSaved && <div className="mt-2 text-xs text-okgreen font-bold">Makasih, Kak! Masukannya nyampe.</div>}
          </div>
        </section>
      )}

      {res.granted && outlet.promoCode && outlet.promoQuestion && (
        <section className="px-4 mt-4">
          <button className={`chip w-full justify-center ${promoOn ? 'chip-on' : ''}`} onClick={togglePromo}>{promoOn ? '✓ ' : ''}{outlet.promoQuestion}</button>
        </section>
      )}

      {res.askProfile && !profileDone && (
        <section className="px-4 mt-4">
          <div className="card">
            {!res.member.name && (
              <>
                <div className="font-bold text-sm">Boleh tahu nama panggilannya?</div>
                <input className="input mt-2 mb-3" maxLength={40} placeholder="Nama panggilan" value={profile.name} onChange={(e) => setProfile({ ...profile, name: e.target.value })} />
              </>
            )}
            <div className="font-bold text-sm">Tahu Cimol Bojot AA dari mana?</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {sources.map((s) => <button key={s} className={`chip ${profile.source === s ? 'chip-on' : ''}`} onClick={() => setProfile({ ...profile, source: s })}>{s}</button>)}
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <button className="btn-ghost" onClick={() => saveProfile(true)}>Lewati</button>
              <button className="btn-primary" onClick={() => saveProfile(false)} disabled={!profile.name && !profile.source}>Simpan</button>
            </div>
          </div>
        </section>
      )}

      {activeVouchers.length > 0 && (
        <section className="px-4 mt-6 space-y-3">
          <div className="font-extrabold">Voucher Kakak</div>
          {activeVouchers.map((v) => <VoucherCard key={v.id} v={v} canRedeem={canRedeem} onRedeem={setRedeem} />)}
        </section>
      )}
      {otherVouchers.filter((v) => v.status === 'scheduled' && !(res.isNewMember && res.welcomeVoucher?.id === v.id)).length > 0 && (
        <section className="px-4 mt-4 space-y-3">
          {otherVouchers.filter((v) => v.status === 'scheduled' && !(res.isNewMember && res.welcomeVoucher?.id === v.id)).map((v) => <VoucherCard key={v.id} v={v} canRedeem={false} />)}
        </section>
      )}

      <div className="px-4 mt-8 text-center text-sm">
        <Link to="/saya" className="text-deep font-bold">Lihat stamp &amp; voucher saya</Link>
      </div>

      {redeem && (
        <RedeemFlow voucher={redeem} qrToken={token} outletName={outlet.name} countdownSec={outlet.redeemCountdownSec}
          onClose={() => setRedeem(null)} onUsed={onUsed} />
      )}
    </main>
  )
}
