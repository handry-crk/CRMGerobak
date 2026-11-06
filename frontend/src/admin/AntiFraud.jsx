import { useEffect, useState } from 'react'
import { fmtTanggal } from '../api.js'
import { adminApi, daysAgo, today } from './adminApi.js'
import { Field, RangePicker, Table, Tile } from './ui.jsx'

const STATUS = {
  cocok: 'Cocok', hadiah_lebih: 'Hadiah keluar > voucher (crew bagi-bagi?)', voucher_lebih: 'Voucher > hadiah keluar (akun fiktif?)', belum_lapor: 'Ops belum lapor',
}

export default function AntiFraud({ ctx }) {
  const [from, setFrom] = useState(daysAgo(13))
  const [to, setTo] = useState(today())
  const [rec, setRec] = useState(null)
  const [staff, setStaff] = useState([])
  const [form, setForm] = useState({ phone: '', name: '', outletCode: '', note: '' })

  const load = () => {
    adminApi(`/api/admin/reconciliation?from=${from}&to=${to}`).then(setRec).catch((e) => ctx.notify(e.message))
    if (ctx.privileged) adminApi('/api/admin/staff').then(setStaff).catch(() => {})
  }
  useEffect(() => { load() }, [from, to])

  async function addStaff(e) {
    e.preventDefault()
    try { await adminApi('/api/admin/staff', { method: 'POST', body: form }); ctx.notify('Nomor crew ditambahkan'); setForm({ phone: '', name: '', outletCode: '', note: '' }); load() } catch (e) { ctx.notify(e.message) }
  }
  async function removeStaff(s) {
    if (!confirm(`Hapus ${s.phone} dari daftar crew?`)) return
    try { await adminApi(`/api/admin/staff/${s.id}`, { method: 'DELETE' }); load() } catch (e) { ctx.notify(e.message) }
  }

  if (!rec) return <div className="text-sm">Memuat…</div>
  return (
    <div className="space-y-6">
      <div className="card text-sm space-y-1">
        <div className="font-extrabold">Pengaman yang aktif</div>
        <ul className="list-disc pl-5 text-charcoal/80">
          <li>1 stamp per nomor per gerobak per hari · maks 2 per hari · jeda 20 menit (ubah di Pengaturan).</li>
          <li>Voucher reward baru bisa ditukar <b>H+1</b>; kuota penukaran per gerobak per hari (Pengaturan).</li>
          <li>Nomor crew & keluarga: stamp tercatat, <b>tanpa voucher</b>, tidak masuk KPI.</li>
          <li>Rekonsiliasi: hadiah gratis yang benar-benar keluar (laporan Ops per hari) vs voucher yang ditukar di sistem.</li>
        </ul>
      </div>

      <RangePicker from={from} to={to} setFrom={setFrom} setTo={setTo} />
      <div className="grid grid-cols-3 gap-3">
        <Tile label="Outlet-hari tidak cocok" value={rec.mismatch.length} />
        <Tile label="Belum dilaporkan Ops" value={rec.unreported} sub="Isi 'Hadiah keluar' di detail outlet" />
        <Tile label="Kuota penukaran tercapai" value={rec.alerts.filter((a) => a.type === 'redeem_quota').length} />
      </div>

      <div className="card">
        <div className="text-sm font-bold mb-2">Rekonsiliasi hadiah per outlet-hari</div>
        <Table
          cols={[
            { key: 'day', label: 'Tanggal' }, { key: 'outlet', label: 'Outlet' },
            { key: 'redeemed', label: 'Voucher ditukar', align: 'right' },
            { key: 'rewardsGiven', label: 'Hadiah keluar (Ops)', align: 'right', render: (r) => r.rewardsGiven ?? '–' },
            { key: 'diff', label: 'Selisih', align: 'right', render: (r) => (r.diff === null ? '–' : (r.diff > 0 ? '+' : '') + r.diff) },
            { key: 'status', label: 'Status', render: (r) => <span className={r.status === 'cocok' ? 'text-okgreen' : r.status === 'belum_lapor' ? 'text-charcoal/60' : 'text-brand font-bold'}>{STATUS[r.status]}</span> },
          ]}
          rows={rec.rows}
          empty="Belum ada penukaran maupun laporan hadiah pada periode ini"
        />
      </div>

      {rec.alerts.length > 0 && (
        <div className="card">
          <div className="text-sm font-bold mb-2">Alert</div>
          {rec.alerts.map((a) => <div key={a.id} className="text-sm border-b border-line py-1">{fmtTanggal(a.at, { hour: '2-digit', minute: '2-digit' })} · {a.outletCode} · {a.note}</div>)}
        </div>
      )}

      {ctx.privileged && (
        <div className="card space-y-3">
          <div className="text-sm font-bold">Nomor crew & keluarga</div>
          <p className="text-xs text-charcoal/60">Minta daftar dari HR/Ops. Nomor di sini tetap bisa scan (agar crew tidak merasa dicurigai) tapi tidak pernah mendapat voucher dan tidak dihitung di KPI.</p>
          {ctx.lead && (
            <form onSubmit={addStaff} className="flex flex-wrap gap-2 items-end">
              <Field label="No. WA"><input className="input" required inputMode="tel" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} placeholder="08…" /></Field>
              <Field label="Nama"><input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
              <Field label="Kode outlet"><input className="input" value={form.outletCode} onChange={(e) => setForm({ ...form, outletCode: e.target.value })} placeholder="BDG-BRG-01" /></Field>
              <Field label="Catatan"><input className="input" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} placeholder="crew / istri crew / …" /></Field>
              <button className="btn-primary">Tambah</button>
            </form>
          )}
          <Table cols={[{ key: 'phone', label: 'Nomor' }, { key: 'name', label: 'Nama' }, { key: 'outletCode', label: 'Outlet' }, { key: 'note', label: 'Catatan' }, { key: 'addedBy', label: 'Ditambah oleh' },
            { key: 'x', label: '', render: (s) => ctx.lead && <button className="underline text-brand" onClick={() => removeStaff(s)}>Hapus</button> }]} rows={staff} empty="Belum ada nomor crew" />
        </div>
      )}
    </div>
  )
}
