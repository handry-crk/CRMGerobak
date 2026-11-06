import { fmtRp } from '../api.js'

export function Tile({ label, value, sub, suffix = '' }) {
  const show = value === null || value === undefined ? '–' : typeof value === 'number' ? fmtRp(value) + suffix : value
  return (
    <div className="card">
      <div className="text-xs text-charcoal/60 font-bold">{label}</div>
      <div className="text-2xl font-extrabold text-brand mt-1">{show}</div>
      {sub && <div className="text-xs text-charcoal/60 mt-1">{sub}</div>}
    </div>
  )
}

export function Bars({ data, xKey, yKey, label, height = 120, color = '#D7191F', formatX = (x) => x }) {
  const max = Math.max(1, ...data.map((d) => d[yKey] || 0))
  return (
    <div>
      {label && <div className="text-sm font-bold mb-2">{label}</div>}
      <div className="flex items-end gap-[2px]" style={{ height }}>
        {data.map((d, i) => (
          <div key={i} className="flex-1 flex flex-col items-center justify-end h-full" title={`${formatX(d[xKey])}: ${d[yKey]}`}>
            <div className="w-full rounded-t" style={{ height: `${((d[yKey] || 0) / max) * 100}%`, background: color, minHeight: d[yKey] ? 2 : 0 }} />
          </div>
        ))}
      </div>
      <div className="flex justify-between text-[10px] text-charcoal/60 mt-1">
        <span>{data.length ? formatX(data[0][xKey]) : ''}</span><span>{data.length ? formatX(data[data.length - 1][xKey]) : ''}</span>
      </div>
    </div>
  )
}

export function StackedBars({ data, label }) {
  const max = Math.max(1, ...data.map((d) => d.new + d.returning))
  return (
    <div>
      {label && <div className="text-sm font-bold mb-2">{label}</div>}
      <div className="flex items-end gap-1 h-[120px]">
        {data.map((d) => (
          <div key={d.week} className="flex-1 flex flex-col justify-end h-full" title={`${d.week}: baru ${d.new}, kembali ${d.returning}`}>
            <div style={{ height: `${(d.returning / max) * 100}%`, background: '#B32E26' }} />
            <div style={{ height: `${(d.new / max) * 100}%`, background: '#F7D4D5' }} />
          </div>
        ))}
      </div>
      <div className="flex gap-3 text-[10px] text-charcoal/60 mt-1"><span><i className="inline-block w-2 h-2 bg-tint mr-1" />Member baru</span><span><i className="inline-block w-2 h-2 bg-deep mr-1" />Member kembali</span></div>
    </div>
  )
}

export function Table({ cols, rows, empty = 'Belum ada data', onRow }) {
  return (
    <>
      <div className="hidden md:block overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="bg-deep text-white">{cols.map((c) => <th key={c.key} className={`px-3 py-2 text-left font-bold ${c.align === 'right' ? 'text-right' : ''}`}>{c.label}</th>)}</tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.id || i} className={`border-b border-line ${onRow ? 'cursor-pointer hover:bg-tint/40' : ''}`} onClick={() => onRow?.(r)}>
                {cols.map((c) => <td key={c.key} className={`px-3 py-2 ${c.align === 'right' ? 'text-right tabular-nums' : ''}`}>{c.render ? c.render(r) : r[c.key] ?? '–'}</td>)}
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={cols.length} className="px-3 py-6 text-center text-charcoal/60">{empty}</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="md:hidden space-y-2">
        {rows.map((r, i) => (
          <div key={r.id || i} className="card text-sm" onClick={() => onRow?.(r)}>
            {cols.map((c) => <div key={c.key} className="flex justify-between gap-3 py-0.5"><span className="text-charcoal/60">{c.label}</span><span className="font-bold text-right">{c.render ? c.render(r) : r[c.key] ?? '–'}</span></div>)}
          </div>
        ))}
        {rows.length === 0 && <div className="card text-center text-charcoal/60 text-sm">{empty}</div>}
      </div>
    </>
  )
}

export function Field({ label, children }) {
  return <label className="block text-sm"><span className="font-bold">{label}</span><div className="mt-1">{children}</div></label>
}

export function Toast({ msg }) {
  if (!msg) return null
  return <div className="fixed bottom-4 inset-x-0 flex justify-center z-50 px-4"><div className="bg-charcoal text-white text-sm px-4 py-3 rounded-xl shadow-lg">{msg}</div></div>
}

export function RangePicker({ from, to, setFrom, setTo, area, setArea, areas }) {
  return (
    <div className="flex flex-wrap gap-2 items-end">
      <Field label="Dari"><input type="date" className="input" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
      <Field label="Sampai"><input type="date" className="input" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
      {areas && (
        <Field label="Area">
          <select className="input" value={area} onChange={(e) => setArea(e.target.value)}>
            <option value="">Semua area</option>
            {areas.map((a) => <option key={a}>{a}</option>)}
          </select>
        </Field>
      )}
    </div>
  )
}
