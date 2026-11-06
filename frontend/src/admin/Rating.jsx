import { useEffect, useState } from 'react'
import { fmtTanggal } from '../api.js'
import { adminApi, daysAgo, downloadWithAuth, today } from './adminApi.js'
import { Bars, RangePicker, Table } from './ui.jsx'

export default function Rating({ ctx }) {
  const [from, setFrom] = useState(daysAgo(29))
  const [to, setTo] = useState(today())
  const [low, setLow] = useState(false)
  const [data, setData] = useState(null)

  useEffect(() => {
    adminApi(`/api/admin/feedback?from=${from}&to=${to}${low ? '&max_rating=2' : ''}`).then(setData).catch((e) => ctx.notify(e.message))
  }, [from, to, low])

  if (!data) return <div className="text-sm">Memuat…</div>
  const dist = Object.entries(data.distribution).map(([r, n]) => ({ r: `${r}★`, n }))
  const tags = Object.entries(data.tags).sort((a, b) => b[1] - a[1])
  const total = dist.reduce((a, d) => a + d.n, 0)
  const avg = total ? (Object.entries(data.distribution).reduce((a, [r, n]) => a + r * n, 0) / total).toFixed(2) : '–'

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2 items-end">
        <RangePicker from={from} to={to} setFrom={setFrom} setTo={setTo} />
        <label className="flex items-center gap-2 text-sm pb-3"><input type="checkbox" checked={low} onChange={(e) => setLow(e.target.checked)} /> Hanya ≤ 2★</label>
        {ctx.privileged && <button className="btn-ghost" onClick={() => downloadWithAuth(`/api/admin/export/feedback.csv?from=${from}&to=${to}`, 'feedback.csv')}>Ekspor CSV</button>}
      </div>
      <div className="grid md:grid-cols-3 gap-4">
        <div className="card"><div className="text-xs text-charcoal/60 font-bold">Rating rata-rata</div><div className="text-3xl font-extrabold text-brand">{avg}</div><div className="text-xs text-charcoal/60">{total} rating</div></div>
        <div className="card"><Bars data={dist} xKey="r" yKey="n" label="Distribusi" height={90} /></div>
        <div className="card"><div className="text-sm font-bold mb-2">Tag terbanyak</div>{tags.length === 0 && <div className="text-sm text-charcoal/60">Belum ada.</div>}{tags.map(([t, n]) => <div key={t} className="flex justify-between text-sm py-0.5"><span>{t}</span><b>{n}</b></div>)}</div>
      </div>
      <div className="card"><div className="text-sm font-bold mb-2">Per outlet</div>
        <Table cols={[{ key: 'outlet', label: 'Outlet' }, { key: 'n', label: 'Rating', align: 'right' }, { key: 'avg', label: 'Rata-rata', align: 'right' }]} rows={data.perOutlet} /></div>
      <div className="card"><div className="text-sm font-bold mb-2">Komentar & rating terbaru</div>
        <Table cols={[{ key: 'at', label: 'Waktu', render: (f) => fmtTanggal(f.at, { hour: '2-digit', minute: '2-digit' }) }, { key: 'outlet', label: 'Outlet' }, { key: 'rating', label: '★', render: (f) => '★'.repeat(f.rating) }, { key: 'tag', label: 'Tag' }, { key: 'comment', label: 'Komentar' }]} rows={data.items} /></div>
      <p className="text-xs text-charcoal/60">Data rating tersedia untuk Service Excellence Dashboard lewat <code>GET /api/public-metrics/ratings</code> (header <code>X-Api-Key</code>).</p>
    </div>
  )
}
