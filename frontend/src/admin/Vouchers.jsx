import { useEffect, useState } from 'react'
import { fmtRp } from '../api.js'
import { adminApi, daysAgo, downloadWithAuth, today } from './adminApi.js'
import { Field, Table, Tile } from './ui.jsx'

const TYPE_LABEL = { balik_lagi: 'Balik Lagi (welcome)', stamp_reward: 'Reward 5 stamp', campaign: 'Campaign / manual', welcome: 'Welcome' }
const EMPTY = { code: '', title: '', valueRp: 3000, minSpendRp: 15000, validFrom: today(), validTo: daysAgo(-14), segment: 'semua', area: '', minVisits: 3, maxIssue: '', phones: '' }

export default function Vouchers({ ctx }) {
  const [stats, setStats] = useState(null)
  const [form, setForm] = useState(null)

  const load = () => adminApi('/api/admin/vouchers/stats').then(setStats).catch((e) => ctx.notify(e.message))
  useEffect(() => { load() }, [])

  async function submit(e) {
    e.preventDefault()
    try {
      const c = await adminApi('/api/admin/campaigns', { method: 'POST', body: { ...form, valueRp: Number(form.valueRp), minSpendRp: Number(form.minSpendRp), minVisits: Number(form.minVisits), maxIssue: form.maxIssue ? Number(form.maxIssue) : null } })
      ctx.notify(`Campaign ${c.code}: ${c.issued} voucher diterbitkan${c.notFound?.length ? ` · ${c.notFound.length} nomor belum jadi member` : ''}`); setForm(null); load()
    } catch (e) { ctx.notify(e.message) }
  }

  if (!stats) return <div className="text-sm">Memuat…</div>
  const types = Object.entries(stats.byType)
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        {types.map(([t, s]) => {
          const issued = Object.values(s).reduce((a, b) => a + b, 0)
          const pct = issued ? Math.round(((s.used || 0) / issued) * 100) : 0
          return (
            <div key={t} className="card">
              <div className="text-xs text-charcoal/60 font-bold">{TYPE_LABEL[t] || t}</div>
              <div className="mt-1 flex items-baseline gap-2"><span className="text-2xl font-extrabold text-brand">{s.used || 0}</span><span className="text-sm font-bold">ditukar</span><span className="text-xs text-charcoal/60">({pct}%)</span></div>
              <div className="mt-2 grid grid-cols-4 gap-1 text-center text-xs">
                <div><div className="font-extrabold">{issued}</div><div className="text-charcoal/60">terbit</div></div>
                <div><div className="font-extrabold text-okgreen">{s.active || 0}</div><div className="text-charcoal/60">aktif</div></div>
                <div><div className="font-extrabold">{s.scheduled || 0}</div><div className="text-charcoal/60">terjadwal</div></div>
                <div><div className="font-extrabold text-charcoal/50">{s.expired || 0}</div><div className="text-charcoal/60">hangus</div></div>
              </div>
            </div>
          )
        })}
        {types.length === 0 && <div className="card text-sm text-charcoal/60 col-span-full">Belum ada voucher.</div>}
      </div>

      <div className="flex gap-2 flex-wrap">
        {ctx.privileged && <button className="btn-primary" onClick={() => setForm({ ...EMPTY })}>+ Campaign voucher</button>}
        {ctx.privileged && <button className="btn-ghost" onClick={() => downloadWithAuth('/api/admin/export/vouchers.csv', 'vouchers.csv')}>Ekspor CSV</button>}
      </div>
      <p className="text-xs text-charcoal/60">Notifikasi WA untuk voucher campaign menyusul di Iterasi 1 (Fonnte). Saat ini voucher tampil di halaman “Stamp & voucher saya” member.</p>

      <Table
        cols={[
          { key: 'code', label: 'Kode' }, { key: 'title', label: 'Judul' }, { key: 'valueRp', label: 'Nilai', render: (c) => `Rp${fmtRp(c.valueRp)}`, align: 'right' },
          { key: 'segment', label: 'Segmen', render: (c) => c.segment + (c.area ? ` (${c.area})` : '') + (c.segment === 'minVisits' ? ` (≥${c.minVisits})` : '') + (c.maxIssue ? ` · maks ${c.maxIssue}` : '') },
          { key: 'validFrom', label: 'Berlaku', render: (c) => `${c.validFrom} – ${c.validTo}` },
          { key: 'issued', label: 'Terbit', align: 'right' }, { key: 'used', label: 'Ditukar', align: 'right' },
        ]}
        rows={stats.campaigns}
        empty="Belum ada campaign"
      />

      {form && (
        <div className="fixed inset-0 bg-black/40 z-40 grid place-items-center p-4" onClick={() => setForm(null)}>
          <form className="card w-full max-w-lg space-y-3" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
            <div className="font-extrabold">Campaign voucher</div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Kode"><input className="input" required value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="BACK-03" /></Field>
              <Field label="Nilai (Rp)"><input className="input" inputMode="numeric" value={form.valueRp} onChange={(e) => setForm({ ...form, valueRp: e.target.value })} /></Field>
            </div>
            <Field label="Judul (tampil ke member)"><input className="input" required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Balik Lagi: potongan 3.000" /></Field>
            <div className="grid grid-cols-3 gap-3">
              <Field label="Min. belanja"><input className="input" inputMode="numeric" value={form.minSpendRp} onChange={(e) => setForm({ ...form, minSpendRp: e.target.value })} /></Field>
              <Field label="Mulai"><input type="date" className="input" value={form.validFrom} onChange={(e) => setForm({ ...form, validFrom: e.target.value })} /></Field>
              <Field label="Sampai"><input type="date" className="input" value={form.validTo} onChange={(e) => setForm({ ...form, validTo: e.target.value })} /></Field>
            </div>
            <Field label="Segmen">
              <select className="input" value={form.segment} onChange={(e) => setForm({ ...form, segment: e.target.value })}>
                <option value="semua">Semua member (opt-in)</option>
                <option value="area">Per area</option>
                <option value="dorman30">Member dorman ≥ 30 hari</option>
                <option value="minVisits">Member dengan ≥ N kunjungan</option>
                <option value="nomor">Nomor tertentu (internal / tes)</option>
              </select>
            </Field>
            {form.segment !== 'nomor' && <Field label="Batas jumlah terbit (kosong = semua yang cocok; member terakhir berkunjung didahulukan)"><input className="input" inputMode="numeric" value={form.maxIssue} onChange={(e) => setForm({ ...form, maxIssue: e.target.value })} placeholder="mis. 50" /></Field>}
            {form.segment === 'nomor' && <Field label="Daftar nomor WA (pisahkan baris/koma; harus sudah jadi member)"><textarea className="input min-h-[96px] py-2" value={form.phones} onChange={(e) => setForm({ ...form, phones: e.target.value })} placeholder={'081234567890\n081298765432'} /></Field>}
            {form.segment === 'area' && <Field label="Area"><select className="input" value={form.area} onChange={(e) => setForm({ ...form, area: e.target.value })}><option value="">Pilih…</option>{ctx.meta.areas.map((a) => <option key={a}>{a}</option>)}</select></Field>}
            {form.segment === 'minVisits' && <Field label="N kunjungan"><input className="input" inputMode="numeric" value={form.minVisits} onChange={(e) => setForm({ ...form, minVisits: e.target.value })} /></Field>}
            <div className="grid grid-cols-2 gap-2"><button type="button" className="btn-ghost" onClick={() => setForm(null)}>Batal</button><button className="btn-primary">Terbitkan</button></div>
          </form>
        </div>
      )}
    </div>
  )
}
