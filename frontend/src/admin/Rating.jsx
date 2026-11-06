import { useEffect, useState } from 'react'
import { fmtTanggal } from '../api.js'
import { adminApi, daysAgo, downloadWithAuth, today } from './adminApi.js'
import { RangePicker, Table } from './ui.jsx'

function Dist({ title, dist, scale, groups, labels }) {
  const total = Object.values(dist).reduce((a, b) => a + b, 0)
  const avg = total ? (Object.entries(dist).reduce((a, [r, n]) => a + r * n, 0) / total).toFixed(2) : '–'
  const pct = (n) => (total ? Math.round((n / total) * 100) : 0)
  return (
    <div className="card">
      <div className="flex items-baseline justify-between"><div className="text-sm font-bold">{title}</div><div className="text-xs text-charcoal/60">{total} rating · rata-rata <b className="text-brand">{avg}</b></div></div>
      <div className="mt-3 flex h-4 rounded-full overflow-hidden text-[10px] font-bold text-white">
        <div style={{ width: `${pct(groups.puas)}%`, background: '#1E8E3E' }} title={`${labels.puas} ${pct(groups.puas)}%`} />
        <div style={{ width: `${pct(groups.biasa)}%`, background: '#E0A800' }} title={`${labels.biasa} ${pct(groups.biasa)}%`} />
        <div style={{ width: `${pct(groups.tidak_puas)}%`, background: '#D7191F' }} title={`${labels.tidak_puas} ${pct(groups.tidak_puas)}%`} />
      </div>
      <div className="mt-1 flex justify-between text-xs"><span className="text-okgreen font-bold">Puas {pct(groups.puas)}%</span><span className="text-amber-600 font-bold">Biasa {pct(groups.biasa)}%</span><span className="text-brand font-bold">Tidak puas {pct(groups.tidak_puas)}%</span></div>
      <div className="mt-3 space-y-1">
        {[...scale].reverse().map((o) => (
          <div key={o.value} className="flex items-center gap-2 text-sm">
            <span className="w-6 text-lg">{o.emoji}</span><span className="w-24 text-xs">{o.label}</span>
            <div className="flex-1 h-3 bg-tint/60 rounded"><div className="h-full rounded" style={{ width: `${pct(dist[o.value] || 0)}%`, background: o.value >= 4 ? '#1E8E3E' : o.value === 3 ? '#E0A800' : '#D7191F' }} /></div>
            <span className="w-8 text-right text-xs tabular-nums">{dist[o.value] || 0}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function Rating({ ctx }) {
  const [from, setFrom] = useState(daysAgo(29))
  const [to, setTo] = useState(today())
  const [low, setLow] = useState(false)
  const [data, setData] = useState(null)

  useEffect(() => {
    adminApi(`/api/admin/feedback?from=${from}&to=${to}${low ? '&max_rating=2' : ''}`).then(setData).catch((e) => ctx.notify(e.message))
  }, [from, to, low])

  if (!data) return <div className="text-sm">Memuat…</div>
  const tags = Object.entries(data.tags).sort((a, b) => b[1] - a[1])
  const emoji = (v) => data.scale.find((o) => o.value === v)?.emoji || '–'
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2 items-end">
        <RangePicker from={from} to={to} setFrom={setFrom} setTo={setTo} />
        <label className="flex items-center gap-2 text-sm pb-3"><input type="checkbox" checked={low} onChange={(e) => setLow(e.target.checked)} /> Hanya rasa ≤ Kurang</label>
        {ctx.privileged && <button className="btn-ghost" onClick={() => downloadWithAuth(`/api/admin/export/feedback.csv?from=${from}&to=${to}`, 'feedback.csv')}>Ekspor CSV</button>}
      </div>
      <div className="grid md:grid-cols-2 gap-4">
        <Dist title="Rasa cimol" dist={data.distribution} scale={data.scale} groups={data.groups} labels={data.groupLabels} />
        <Dist title="Pelayanan crew" dist={data.distributionService} scale={data.scale} groups={data.groupsService} labels={data.groupLabels} />
      </div>
      <div className="grid md:grid-cols-3 gap-4">
        <div className="card"><div className="text-sm font-bold mb-2">Tag terbanyak</div>{tags.length === 0 && <div className="text-sm text-charcoal/60">Belum ada.</div>}{tags.map(([t, n]) => <div key={t} className="flex justify-between text-sm py-0.5"><span>{t}</span><b>{n}</b></div>)}</div>
        <div className="card md:col-span-2"><div className="text-sm font-bold mb-2">Per outlet</div>
          <Table cols={[{ key: 'outlet', label: 'Outlet' }, { key: 'n', label: 'Rating', align: 'right' }, { key: 'avg', label: 'Rasa', align: 'right' }, { key: 'avgService', label: 'Pelayanan', align: 'right', render: (r) => r.avgService ?? '–' }, { key: 'csatPct', label: '% Puas', align: 'right', render: (r) => `${r.csatPct}%` }]} rows={data.perOutlet} /></div>
      </div>
      <div className="card"><div className="text-sm font-bold mb-2">Rating & komentar terbaru</div>
        <Table cols={[{ key: 'at', label: 'Waktu', render: (f) => fmtTanggal(f.at, { hour: '2-digit', minute: '2-digit' }) }, { key: 'outlet', label: 'Outlet' },
          { key: 'rating', label: 'Rasa', render: (f) => `${emoji(f.rating)} ${f.rating}` }, { key: 'service', label: 'Pelayanan', render: (f) => (f.service ? `${emoji(f.service)} ${f.service}` : '–') },
          { key: 'tags', label: 'Tag', render: (f) => f.tags.join(', ') || '–' }, { key: 'comment', label: 'Ditulis sendiri' }]} rows={data.items} /></div>
      <p className="text-xs text-charcoal/60">Skala: 😖 Kecewa · 😕 Kurang · 🙂 Biasa aja · 😄 Puas · 🤩 Puas banget. Kelompok: Tidak puas (1–2), Biasa (3), Puas (4–5). Data tersedia untuk Service Excellence Dashboard lewat <code>GET /api/public-metrics/ratings</code>.</p>
    </div>
  )
}
