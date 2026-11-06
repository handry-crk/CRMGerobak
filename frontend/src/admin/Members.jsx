import { useEffect, useState } from 'react'
import { fmtTanggal } from '../api.js'
import { adminApi, downloadWithAuth } from './adminApi.js'
import { Field, Table } from './ui.jsx'

export default function Members({ ctx }) {
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState({ items: [], total: 0 })
  const [detail, setDetail] = useState(null)
  const [reason, setReason] = useState('')

  const load = () => adminApi(`/api/admin/members?q=${encodeURIComponent(q)}&page=${page}`).then(setData).catch((e) => ctx.notify(e.message))
  useEffect(() => { load() }, [q, page])

  async function open(m) { try { setDetail(await adminApi(`/api/admin/members/${m.id}`)) } catch (e) { ctx.notify(e.message) } }

  async function act(path, body, method = 'POST') {
    if (!reason || reason.length < 3) return ctx.notify('Isi alasan dulu (min. 3 huruf) — dicatat di audit log.')
    try {
      await adminApi(path, { method, body: body ? { ...body, reason } : undefined })
      ctx.notify('Tersimpan'); open(detail.member); load()
    } catch (e) { ctx.notify(e.message) }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2 items-end">
        <Field label="Cari nomor / nama"><input className="input" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} placeholder="0812… atau nama" /></Field>
        <div className="text-sm text-charcoal/60 pb-3">{data.total} member</div>
        {ctx.privileged && <button className="btn-ghost" onClick={() => downloadWithAuth('/api/admin/export/members.csv', 'members.csv')}>Ekspor CSV</button>}
      </div>
      <Table
        cols={[
          { key: 'phone', label: 'Nomor' }, { key: 'name', label: 'Nama' }, { key: 'city', label: 'Kota' },
          { key: 'joinedDay', label: 'Gabung' }, { key: 'visits', label: 'Kunjungan', align: 'right' },
          { key: 'stampsActive', label: 'Stamp aktif', align: 'right' }, { key: 'lastVisitAt', label: 'Terakhir', render: (m) => fmtTanggal(m.lastVisitAt) },
          { key: 'blocked', label: 'Status', render: (m) => (m.blocked ? 'Diblokir' : m.optIn ? 'Aktif' : 'Opt-out') },
        ]}
        rows={data.items}
        onRow={open}
      />
      <div className="flex gap-2 justify-center text-sm">
        <button className="btn-ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>‹</button>
        <span className="py-3">Hal. {page}</span>
        <button className="btn-ghost" disabled={page * 50 >= data.total} onClick={() => setPage(page + 1)}>›</button>
      </div>

      {detail && (
        <div className="fixed inset-0 bg-black/40 z-40 grid place-items-center p-4" onClick={() => setDetail(null)}>
          <div className="card w-full max-w-2xl space-y-3 max-h-[90vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between items-start">
              <div><div className="font-extrabold text-lg">{detail.member.name || 'Tanpa nama'} · {detail.member.phone}</div>
                <div className="text-xs text-charcoal/60">Gabung {fmtTanggal(detail.member.joinedAt)} · {detail.member.visits} kunjungan · {detail.member.stampsTotal} stamp total · {detail.member.rewardsEarned} reward · sumber: {detail.member.source || '–'} · {detail.member.devices} perangkat</div></div>
              <button className="btn-ghost" onClick={() => setDetail(null)}>Tutup</button>
            </div>
            {ctx.lead && (
              <div className="card bg-tint/40 space-y-2">
                <Field label="Alasan tindakan (wajib, masuk audit log)"><input className="input" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
                <div className="flex flex-wrap gap-2 text-sm">
                  <button className="btn-ghost" onClick={() => act(`/api/admin/members/${detail.member.id}/adjust-stamps`, { delta: 1 })}>+1 stamp</button>
                  <button className="btn-ghost" onClick={() => act(`/api/admin/members/${detail.member.id}/adjust-stamps`, { delta: -1 })}>−1 stamp</button>
                  <button className="btn-ghost" onClick={() => act(`/api/admin/members/${detail.member.id}/voucher`, { title: 'Voucher permintaan maaf: Cimol Bojot kecil gratis', valueRp: 6000, minSpendRp: 0, validDays: 14 })}>Voucher manual</button>
                  <button className="btn-ghost" onClick={() => act(`/api/admin/members/${detail.member.id}/block`, {})}>{detail.member.blocked ? 'Buka blokir' : 'Blokir'}</button>
                  <button className="btn-ghost text-brand" onClick={() => confirm('Hapus & anonimkan member ini?') && act(`/api/admin/members/${detail.member.id}?reason=${encodeURIComponent(reason)}`, null, 'DELETE')}>Hapus (anonimkan)</button>
                </div>
              </div>
            )}
            <div className="grid md:grid-cols-2 gap-3 text-sm">
              <div><div className="font-bold mb-1">Stamp</div>
                {detail.stamps.map((s, i) => <div key={i} className="border-b border-line py-1 flex justify-between gap-2"><span>{fmtTanggal(s.at)} · {s.outlet}</span><span className={s.granted ? 'text-okgreen' : 'text-charcoal/50'}>{s.granted ? '✓' : s.reason}{s.flags?.length ? ` · ${s.flags.join(',')}` : ''}{s.promoCode ? ` · ${s.promoCode}` : ''}</span></div>)}
              </div>
              <div><div className="font-bold mb-1">Voucher</div>
                {detail.vouchers.map((v) => <div key={v.id} className="border-b border-line py-1 flex justify-between gap-2"><span>{v.title}</span><span className="text-charcoal/60">{v.status}{v.usedOutletName ? ` · ${v.usedOutletName}` : ''}</span></div>)}
                {detail.vouchers.length === 0 && <div className="text-charcoal/60">Belum ada.</div>}
                <div className="font-bold mt-3 mb-1">Feedback</div>
                {detail.feedback.map((f, i) => <div key={i} className="border-b border-line py-1">{'★'.repeat(f.rating)} {f.outlet} {f.tag || ''} {f.comment ? `— “${f.comment}”` : ''}</div>)}
                {detail.feedback.length === 0 && <div className="text-charcoal/60">Belum ada.</div>}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
