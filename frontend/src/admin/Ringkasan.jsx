import { useEffect, useState } from 'react'
import { adminApi, daysAgo, today } from './adminApi.js'
import { Bars, RangePicker, StackedBars, Table, Tile } from './ui.jsx'

function insightPerHour(perHour) {
  const top = [...perHour].sort((a, b) => b.stamps - a.stamps).slice(0, 2).filter((h) => h.stamps > 0)
  if (!top.length) return 'Belum ada stamp pada periode ini.'
  return `Jam paling ramai: ${top.map((h) => `${String(h.hour).padStart(2, '0')}.00`).join(' dan ')} WIB.`
}

export default function Ringkasan({ ctx }) {
  const [from, setFrom] = useState(daysAgo(29))
  const [to, setTo] = useState(today())
  const [area, setArea] = useState('')
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    adminApi(`/api/admin/summary?from=${from}&to=${to}${area ? `&area=${area}` : ''}`).then(setData).catch((e) => setErr(e.message))
  }, [from, to, area])

  if (err) return <div className="card text-brand">{err}</div>
  if (!data) return <div className="text-sm">Memuat…</div>
  const k = data.kpi
  const perDay = data.charts.perDay
  const total = perDay.reduce((a, d) => a + d.stamps, 0)
  const best = perDay.reduce((a, d) => (d.stamps > (a?.stamps ?? -1) ? d : a), null)

  return (
    <div className="space-y-4">
      <RangePicker from={from} to={to} setFrom={setFrom} setTo={setTo} area={area} setArea={setArea} areas={ctx.user.role === 'Area' ? ctx.user.areas : ctx.meta.areas} />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Tile label="Member baru" value={k.newMembers} />
        <Tile label="Member aktif 30D" value={k.activeMembers30d} sub="≥ 1 stamp dalam 30 hari" />
        <Tile label="Stamp" value={k.stamps} sub={`${k.uniqueMembers} member unik`} />
        <Tile label="Scan rate" value={k.scanRatePct} suffix="%" sub={k.transactions ? `${k.transactions} transaksi (input manual)` : 'Isi transaksi per outlet-day di tab Outlet'} />
        <Tile label="Repeat 30D" value={k.repeat30d.pct} suffix="%" sub={k.repeat30d.cohort ? `${k.repeat30d.repeat} dari ${k.repeat30d.cohort} member` : 'Kohort belum berumur 30 hari'} />
        <Tile label="Redemption reward" value={k.redemptionPct} suffix="%" sub={`${k.rewardUsed} dari ${k.rewardIssued} voucher`} />
        <Tile label="Balik Lagi dipakai" value={k.balikLagiPct} suffix="%" sub={`${k.balikLagiUsed} dari ${k.balikLagiIssued} voucher`} />
        <Tile label="Rating" value={k.avgRating} sub={`${k.ratings} rating`} />
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <div className="card">
          <Bars data={perDay} xKey="day" yKey="stamps" label="Stamp per hari" formatX={(d) => d.slice(5)} />
          <p className="text-xs text-charcoal/70 mt-2">{total ? `Total ${total} stamp; hari tertinggi ${best.day} (${best.stamps}).` : 'Belum ada stamp pada periode ini.'}</p>
        </div>
        <div className="card">
          <Bars data={data.charts.perHour} xKey="hour" yKey="stamps" label="Stamp per jam (WIB)" color="#B32E26" formatX={(h) => `${String(h).padStart(2, '0')}.00`} />
          <p className="text-xs text-charcoal/70 mt-2">{insightPerHour(data.charts.perHour)}</p>
        </div>
        <div className="card">
          <StackedBars data={data.charts.weekly} label="Member baru vs kembali per minggu" />
        </div>
        <div className="card">
          <div className="text-sm font-bold mb-2">Perlu dicek</div>
          {data.flagged.length === 0 && data.velocity.length === 0 && <div className="text-sm text-charcoal/60">Tidak ada anomali.</div>}
          {data.flagged.map((f) => <div key={f.id} className="text-sm py-1 border-b border-line">{f.phone} {f.name ? `(${f.name})` : ''} — jauh {f.jauh7d}×, perangkat baru {f.device7d}× (7 hari){f.blocked ? ' · DIBLOKIR' : ''}</div>)}
          {data.velocity.map((v) => <div key={v.outletId} className="text-sm py-1 border-b border-line text-brand font-bold">Lonjakan: {v.outlet} — {v.last10min} stamp / 10 menit</div>)}
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <div className="card"><div className="text-sm font-bold mb-2">Top 10 outlet</div>
          <Table cols={[{ key: 'name', label: 'Outlet' }, { key: 'stamps', label: 'Stamp', align: 'right' }, { key: 'members', label: 'Member', align: 'right' }, { key: 'perOpenDay', label: '/hari buka', align: 'right' }]} rows={data.charts.topOutlets} /></div>
        <div className="card"><div className="text-sm font-bold mb-2">Bottom 10 outlet</div>
          <Table cols={[{ key: 'name', label: 'Outlet' }, { key: 'stamps', label: 'Stamp', align: 'right' }, { key: 'members', label: 'Member', align: 'right' }]} rows={data.charts.bottomOutlets} /></div>
      </div>
    </div>
  )
}
