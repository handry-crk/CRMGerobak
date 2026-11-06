import { useEffect, useState } from 'react'
import { adminApi, daysAgo, downloadWithAuth, openWithAuth, today } from './adminApi.js'
import { Field, Table } from './ui.jsx'

const EMPTY = { code: '', name: '', area: 'Bandung', city: '', address: '', lat: '', lng: '', priceZone: 'bandung', active: true }

export default function Outlets({ ctx }) {
  const [list, setList] = useState([])
  const [editing, setEditing] = useState(null)
  const [detail, setDetail] = useState(null)
  const [tx, setTx] = useState({ day: today(), transactions: '', revenue: '' })
  const [filterArea, setFilterArea] = useState('')
  const [q, setQ] = useState('')

  const load = () => adminApi('/api/admin/outlets').then(setList).catch((e) => ctx.notify(e.message))
  useEffect(() => { load() }, [])

  async function save(e) {
    e.preventDefault()
    const body = { ...editing, lat: editing.lat === '' ? null : Number(editing.lat), lng: editing.lng === '' ? null : Number(editing.lng) }
    try {
      if (editing.id) await adminApi(`/api/admin/outlets/${editing.id}`, { method: 'PUT', body })
      else await adminApi('/api/admin/outlets', { method: 'POST', body })
      ctx.notify('Outlet tersimpan'); setEditing(null); load()
    } catch (e) { ctx.notify(e.message) }
  }

  async function openDetail(o) {
    try { setDetail(await adminApi(`/api/admin/outlets/${o.id}?from=${daysAgo(29)}&to=${today()}`)) } catch (e) { ctx.notify(e.message) }
  }

  async function rotate(o) {
    if (!confirm(`Ganti QR ${o.name}? Stiker lama berhenti berfungsi dan harus dicetak ulang.`)) return
    try { await adminApi(`/api/admin/outlets/${o.id}/rotate-qr`, { method: 'POST' }); ctx.notify('QR diganti; cetak stiker baru'); load(); if (detail) openDetail(o) } catch (e) { ctx.notify(e.message) }
  }

  async function saveTx(e) {
    e.preventDefault()
    try {
      await adminApi(`/api/admin/outlets/${detail.outlet.id}/transactions`, { method: 'POST', body: { day: tx.day, transactions: Number(tx.transactions || 0), revenue: Number(tx.revenue || 0) } })
      ctx.notify('Transaksi tersimpan'); openDetail(detail.outlet)
    } catch (e) { ctx.notify(e.message) }
  }

  async function importCsv(file) {
    const fd = new FormData(); fd.append('file', file)
    const a = JSON.parse(localStorage.getItem('sb_admin'))
    const res = await fetch('/api/admin/outlets/import', { method: 'POST', body: fd, headers: { Authorization: `Bearer ${a.token}` } })
    const d = await res.json()
    if (!res.ok) return ctx.notify(d.detail?.message || 'Gagal impor')
    ctx.notify(`Impor: ${d.created} baru, ${d.updated} diperbarui${d.errors.length ? `, ${d.errors.length} error` : ''}`)
    load()
  }

  const rows = list.filter((o) => (!filterArea || o.area === filterArea) && (!q || `${o.code} ${o.name}`.toLowerCase().includes(q.toLowerCase())))

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2 items-end">
        <Field label="Cari"><input className="input" placeholder="Kode / nama" value={q} onChange={(e) => setQ(e.target.value)} /></Field>
        <Field label="Area"><select className="input" value={filterArea} onChange={(e) => setFilterArea(e.target.value)}><option value="">Semua</option>{(ctx.user.role === 'Area' ? ctx.user.areas : ctx.meta.areas).map((a) => <option key={a}>{a}</option>)}</select></Field>
        {ctx.privileged && <button className="btn-primary" onClick={() => setEditing({ ...EMPTY })}>+ Outlet</button>}
        {ctx.privileged && <label className="btn-ghost cursor-pointer">Impor CSV<input type="file" accept=".csv" hidden onChange={(e) => e.target.files[0] && importCsv(e.target.files[0])} /></label>}
        <button className="btn-ghost" onClick={() => downloadWithAuth(`/api/admin/stickers.zip${filterArea ? `?area=${filterArea}` : ''}`, `stiker-${filterArea || 'semua'}.zip`)}>Unduh semua stiker (ZIP)</button>
      </div>
      {ctx.privileged && <p className="text-xs text-charcoal/60">Format CSV impor: <code>code;name;area;city;address;lat;lng;priceZone</code> (pemisah koma atau titik koma). Kode yang sudah ada akan diperbarui.</p>}

      <Table
        cols={[
          { key: 'code', label: 'Kode' }, { key: 'name', label: 'Nama' }, { key: 'area', label: 'Area' },
          { key: 'active', label: 'Status', render: (o) => (o.active ? 'Aktif' : 'Nonaktif') },
          { key: 'url', label: 'QR', render: (o) => <span className="flex gap-2 flex-wrap">
            <button className="text-deep font-bold underline" onClick={(e) => { e.stopPropagation(); openWithAuth(`/api/admin/outlets/${o.id}/sticker.pdf`) }}>Stiker A6</button>
            <button className="text-deep font-bold underline" onClick={(e) => { e.stopPropagation(); openWithAuth(`/api/admin/outlets/${o.id}/sticker.pdf?variant=tent`) }}>Tent card</button>
            {ctx.privileged && <button className="text-brand font-bold underline" onClick={(e) => { e.stopPropagation(); rotate(o) }}>Ganti QR</button>}
          </span> },
        ]}
        rows={rows}
        onRow={openDetail}
      />

      {editing && (
        <div className="fixed inset-0 bg-black/40 z-40 grid place-items-center p-4" onClick={() => setEditing(null)}>
          <form className="card w-full max-w-lg space-y-3 max-h-[90vh] overflow-auto" onClick={(e) => e.stopPropagation()} onSubmit={save}>
            <div className="font-extrabold">{editing.id ? 'Edit outlet' : 'Outlet baru'}</div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Kode"><input className="input" required value={editing.code} onChange={(e) => setEditing({ ...editing, code: e.target.value })} placeholder="BDG-BRG-01" /></Field>
              <Field label="Area"><select className="input" value={editing.area} onChange={(e) => setEditing({ ...editing, area: e.target.value, priceZone: e.target.value === 'Bandung' ? 'bandung' : 'jabodetabek' })}>{ctx.meta.areas.map((a) => <option key={a}>{a}</option>)}</select></Field>
            </div>
            <Field label="Nama"><input className="input" required value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} placeholder="Gerobak AA – Braga" /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Kota"><input className="input" value={editing.city || ''} onChange={(e) => setEditing({ ...editing, city: e.target.value })} /></Field>
              <Field label="Zona harga"><select className="input" value={editing.priceZone} onChange={(e) => setEditing({ ...editing, priceZone: e.target.value })}><option value="bandung">Bandung</option><option value="jabodetabek">Jabodetabek</option></select></Field>
            </div>
            <Field label="Alamat / patokan"><input className="input" value={editing.address || ''} onChange={(e) => setEditing({ ...editing, address: e.target.value })} /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Lat"><input className="input" value={editing.lat ?? ''} onChange={(e) => setEditing({ ...editing, lat: e.target.value })} placeholder="-6.9175" /></Field>
              <Field label="Lng"><input className="input" value={editing.lng ?? ''} onChange={(e) => setEditing({ ...editing, lng: e.target.value })} placeholder="107.6098" /></Field>
            </div>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={editing.active} onChange={(e) => setEditing({ ...editing, active: e.target.checked })} /> Aktif</label>
            <div className="grid grid-cols-2 gap-2"><button type="button" className="btn-ghost" onClick={() => setEditing(null)}>Batal</button><button className="btn-primary">Simpan</button></div>
          </form>
        </div>
      )}

      {detail && (
        <div className="fixed inset-0 bg-black/40 z-40 grid place-items-center p-4" onClick={() => setDetail(null)}>
          <div className="card w-full max-w-2xl space-y-3 max-h-[90vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between items-start gap-3">
              <div><div className="font-extrabold text-lg">{detail.outlet.name}</div><div className="text-xs text-charcoal/60">{detail.outlet.code} · {detail.outlet.area} · 30 hari terakhir</div>
                <div className="text-xs mt-1 break-all">URL QR: <code>{detail.outlet.url}</code></div></div>
              <div className="flex gap-2">
                {ctx.privileged && <button className="btn-ghost" onClick={() => { setEditing({ ...detail.outlet }); setDetail(null) }}>Edit</button>}
                <button className="btn-ghost" onClick={() => setDetail(null)}>Tutup</button>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2 text-center">
              <div className="card"><div className="text-xs text-charcoal/60">Stamp</div><div className="text-xl font-extrabold text-brand">{detail.stamps}</div></div>
              <div className="card"><div className="text-xs text-charcoal/60">Member unik</div><div className="text-xl font-extrabold text-brand">{detail.members}</div></div>
              <div className="card"><div className="text-xs text-charcoal/60">Rating</div><div className="text-xl font-extrabold text-brand">{detail.avgRating ?? '–'}</div></div>
            </div>
            <div>
              <div className="text-sm font-bold mb-1">Heatmap hari × jam</div>
              <div className="overflow-x-auto"><table className="text-[10px]"><tbody>
                {detail.heatmap.map((r) => <tr key={r.day}><td className="pr-2 whitespace-nowrap">{r.day.slice(5)}</td>{r.hours.map((n, h) => <td key={h} title={`${h}.00: ${n}`} style={{ background: n ? `rgba(215,25,31,${Math.min(1, 0.15 + n / 10)})` : '#F3EEEE' }} className="w-4 h-4 border border-white" />)}</tr>)}
                {detail.heatmap.length === 0 && <tr><td className="text-charcoal/60">Belum ada stamp.</td></tr>}
              </tbody></table></div>
            </div>
            {ctx.user.role !== 'Viewer' && (
              <form onSubmit={saveTx} className="flex flex-wrap gap-2 items-end">
                <Field label="Tanggal"><input type="date" className="input" value={tx.day} onChange={(e) => setTx({ ...tx, day: e.target.value })} /></Field>
                <Field label="Transaksi (POS)"><input className="input" inputMode="numeric" value={tx.transactions} onChange={(e) => setTx({ ...tx, transactions: e.target.value })} /></Field>
                <Field label="Revenue (Rp)"><input className="input" inputMode="numeric" value={tx.revenue} onChange={(e) => setTx({ ...tx, revenue: e.target.value })} /></Field>
                <button className="btn-primary">Simpan transaksi</button>
              </form>
            )}
            {detail.transactions.length > 0 && <div className="text-xs text-charcoal/70">Transaksi tercatat: {detail.transactions.map((t) => `${t.day.slice(5)}: ${t.transactions}`).join(' · ')}</div>}
            <div>
              <div className="text-sm font-bold mb-1">Feedback terbaru</div>
              {detail.feedback.length === 0 && <div className="text-sm text-charcoal/60">Belum ada.</div>}
              {detail.feedback.slice(0, 10).map((f, i) => <div key={i} className="text-sm border-b border-line py-1">{'★'.repeat(f.rating)}{'☆'.repeat(5 - f.rating)} {f.tag || ''} {f.comment ? `— “${f.comment}”` : ''}</div>)}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
