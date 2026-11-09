import { useEffect, useState } from 'react'
import { api } from '../api.js'

const FALLBACK_SCALE = [
  { value: 1, emoji: '😖', label: 'Kecewa' }, { value: 2, emoji: '😕', label: 'Kurang' }, { value: 3, emoji: '🙂', label: 'Biasa aja' },
  { value: 4, emoji: '😄', label: 'Puas' }, { value: 5, emoji: '🤩', label: 'Puas banget' },
]
const groupOf = (v) => (v <= 2 ? 'tidak_puas' : v === 3 ? 'biasa' : 'puas')

export function useFeedbackMeta() {
  const [meta, setMeta] = useState({ productTagsByGroup: {}, serviceTagsByGroup: {}, ratingScale: FALLBACK_SCALE, sources: [] })
  useEffect(() => { api('/api/meta', { device: false }).then((m) => setMeta((x) => ({ ...x, ...m }))).catch(() => {}) }, [])
  return meta
}

export function RatingRow({ title, value, scale, onPick }) {
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

export function TagRow({ options, tags, onToggle, other }) {
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

/**
 * Satu blok penilaian untuk satu kunjungan (stampId).
 * kind="service" → pelayanan crew (dinilai saat scan, baru beli)
 * kind="taste"   → rasa cimol (dinilai setelah dimakan: kunjungan berikutnya / halaman saya)
 */
export function FeedbackBlock({ kind, stampId, title, meta, onDone }) {
  const [value, setValue] = useState(0)
  const [tags, setTags] = useState([])
  const [note, setNote] = useState('')
  const [done, setDone] = useState(false)
  const byGroup = kind === 'taste' ? meta.productTagsByGroup : meta.serviceTagsByGroup
  const opts = value ? byGroup[groupOf(value)] || [] : []

  async function send(next = {}) {
    const v = next.value ?? value
    let tg = next.tags ?? tags
    if (next.value !== undefined) { setValue(v); tg = tg.filter((t) => (byGroup[groupOf(v)] || []).includes(t)) }
    setTags(tg)
    if (!v) return
    const body = { stampId, tags: tg }
    if (kind === 'taste') { body.rating = v; body.productNote = (next.note ?? note) || null } else { body.service = v; body.serviceNote = (next.note ?? note) || null }
    try {
      await api('/api/feedback', { method: 'POST', body })
      if (!done) { setDone(true); onDone?.() }
    } catch { /* dicoba lagi di tap berikutnya */ }
  }
  const toggle = (t) => send({ tags: tags.includes(t) ? tags.filter((x) => x !== t) : [...tags, t].slice(0, 4) })
  return (
    <div>
      <RatingRow title={title} value={value} scale={meta.ratingScale} onPick={(v) => send({ value: v })} />
      {value > 0 && (
        <TagRow options={opts} tags={tags} onToggle={toggle}
          other={value <= 2 ? { value: note, set: setNote, save: () => send({ note }), placeholder: kind === 'taste' ? 'Contoh: cimolnya alot, bumbunya beda' : 'Contoh: crew main HP, kembalian kurang' } : null} />
      )}
      {done && <div className="mt-2 text-xs text-okgreen font-bold">Tersimpan, makasih Kak!</div>}
    </div>
  )
}
