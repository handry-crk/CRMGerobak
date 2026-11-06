import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, getDevice, rememberQr, requestId, setDevice } from '../api.js'
import { Confetti, Dots, Header, PhoneForm, RedeemFlow, VoucherCard } from '../components/Shared.jsx'

const FALLBACK_SCALE = [
  { value: 1, emoji: '😖', label: 'Kecewa' }, { value: 2, emoji: '😕', label: 'Kurang' }, { value: 3, emoji: '🙂', label: 'Biasa aja' },
  { value: 4, emoji: '😄', label: 'Puas' }, { value: 5, emoji: '🤩', label: 'Puas banget' },
]

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
  const [meta, setMeta] = useState({ productTagsByGroup: {}, serviceTagsByGroup: {}, ratingScale: FALLBACK_SCALE })
  const [rating, setRating] = useState(0)
  const [service, setService] = useState(0)
  const [tags, setTags] = useState([])
  const [comment, setComment] = useState('')
  const [productNote, setProductNote] = useState('')
  const [serviceNote, setServiceNote] = useState('')
  const [fbSaved, setFbSaved] = useState(false)
  const [fbDone, setFbDone] = useState(false)
  const groupOf = (v) => (v <= 2 ? 'tidak_puas' : v === 3 ? 'biasa' : 'puas')
  const productOpts = rating ? meta.productTagsByGroup[groupOf(rating)] || [] : []
  const serviceOpts = service ? meta.serviceTagsByGroup[groupOf(service)] || [] : []
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
    api('/api/meta', { device: false }).then((m) => { setMeta(m); setSources(m.sources) }).catch(() => {})
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

  // Simpan setiap tap (rasa dulu, pelayanan, lalu tag) — "complete" saat keduanya terisi
  async function sendFeedback(next = {}) {
    const r = next.rating ?? rating, sv = next.service ?? service, c = next.comment ?? comment
    let tg = next.tags ?? tags
    if (next.rating !== undefined || next.service !== undefined) {
      const ok = new Set([...(r ? meta.productTagsByGroup[groupOf(r)] || [] : []), ...(sv ? meta.serviceTagsByGroup[groupOf(sv)] || [] : [])])
      tg = tg.filter((t) => ok.has(t))
    }
    if (next.rating !== undefined) setRating(r)
    if (next.service !== undefined) setService(sv)
    setTags(tg)
    if (!r) return
    try {
      const pn = next.productNote ?? productNote, sn = next.serviceNote ?? serviceNote
      const d = await api('/api/feedback', { method: 'POST', body: { qrToken: token, stampId: state.res?.stampId, rating: r, service: sv || null, tags: tg, comment: c || null, productNote: pn || null, serviceNote: sn || null } })
      setFbSaved(true)
      if (d.complete) setFbDone(true)
    } catch { /* abaikan; akan dicoba lagi di tap berikutnya */ }
  }
  const toggleTag = (t) => sendFeedback({ tags: tags.includes(t) ? tags.filter((x) => x !== t) : [...tags, t].slice(0, 4) })

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
  const gate = !!res.feedbackRequired && !fbDone // rating rasa + pelayanan wajib sebelum lanjut
  const canRedeem = !gate // sesi outlet aktif karena baru saja scan di sini
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
          <div className={`card ${gate ? 'border-brand' : ''}`}>
            {gate && <div className="text-xs font-bold text-deep mb-2">Isi dua rating ini dulu ya, Kak (10 detik) — voucher langsung bisa dipakai setelahnya.</div>}
            <RatingRow title="Rasa cimolnya gimana?" value={rating} scale={meta.ratingScale} onPick={(v) => sendFeedback({ rating: v })} />
            {rating > 0 && <TagRow options={productOpts} tags={tags} onToggle={toggleTag}
              other={rating <= 2 ? { value: productNote, set: setProductNote, save: () => sendFeedback({ productNote }), placeholder: 'Contoh: cimolnya alot, bumbunya beda' } : null} />}
            <div className="mt-4" />
            <RatingRow title="Pelayanan crew-nya?" value={service} scale={meta.ratingScale} onPick={(v) => sendFeedback({ service: v })} />
            {service > 0 && <TagRow options={serviceOpts} tags={tags} onToggle={toggleTag}
              other={service <= 2 ? { value: serviceNote, set: setServiceNote, save: () => sendFeedback({ serviceNote }), placeholder: 'Contoh: crew main HP, kembalian kurang' } : null} />}
            {fbDone && <div className="mt-3 text-sm text-okgreen font-bold">Makasih, Kak! Masukannya nyampe ke tim.</div>}
            {!fbDone && fbSaved && <div className="mt-2 text-xs text-charcoal/60">Satu lagi ya, Kak.</div>}
          </div>
        </section>
      )}

      {!gate && res.granted && outlet.promoCode && outlet.promoQuestion && (
        <section className="px-4 mt-4">
          <button className={`chip w-full justify-center ${promoOn ? 'chip-on' : ''}`} onClick={togglePromo}>{promoOn ? '✓ ' : ''}{outlet.promoQuestion}</button>
        </section>
      )}

      {!gate && res.askProfile && !profileDone && (
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
          {activeVouchers.map((v) => <VoucherCard key={v.id} v={v} canRedeem={canRedeem} onRedeem={setRedeem} hint="Isi rating di atas dulu ya, Kak." />)}
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

function RatingRow({ title, value, scale, onPick }) {
  return (
    <div>
      <div className="font-bold text-sm">{title}</div>
      <div className="mt-2 grid grid-cols-5 gap-1">
        {scale.map((o) => (
          <button key={o.value} aria-label={`${title} ${o.label} (${o.value} dari 5)`} onClick={() => onPick(o.value)}
            className={`flex flex-col items-center justify-center min-h-[64px] rounded-xl px-1 ${value === o.value ? 'bg-tint ring-2 ring-brand' : 'bg-white'}`}>
            <span className="text-2xl leading-none">{o.emoji}</span>
            <span className="text-[10px] font-bold mt-1 leading-tight text-center">{o.label}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

function TagRow({ options, tags, onToggle, other }) {
  const [open, setOpen] = useState(!!other?.value)
  const [saved, setSaved] = useState(false)
  return (
    <div className="mt-2">
      <div className="flex flex-wrap gap-2">
        {options.map((t) => <button key={t} className={`chip min-h-[40px] ${tags.includes(t) ? 'chip-on' : ''}`} onClick={() => onToggle(t)}>{t}</button>)}
        {other && <button className={`chip min-h-[40px] ${open ? 'chip-on' : ''}`} onClick={() => setOpen(!open)}>Lainnya, tulis sendiri…</button>}
      </div>
      {other && open && (
        <div className="mt-2 flex gap-2">
          <input className="input" maxLength={140} placeholder={other.placeholder} value={other.value}
            onChange={(e) => { other.set(e.target.value); setSaved(false) }} onBlur={() => { if (other.value.trim()) { other.save(); setSaved(true) } }} />
          <button className="btn-ghost" onClick={() => { other.save(); setSaved(true) }}>{saved ? 'Tersimpan' : 'Simpan'}</button>
        </div>
      )}
    </div>
  )
}
