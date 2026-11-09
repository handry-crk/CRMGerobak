import { useEffect, useState } from 'react'
import { adminApi } from './adminApi.js'
import { Field, Table } from './ui.jsx'

const NUM = ['stampsPerReward', 'rewardValueRp', 'maxStampsPerOutletPerDay', 'maxStampsPerDay', 'minMinutesBetweenStamps', 'geofenceM', 'rewardVoucherValidDays', 'redeemCountdownSec', 'rewardRedeemAfterDays', 'maxRedemptionsPerOutletPerDay']

export default function Settings({ ctx }) {
  const [s, setS] = useState(null)
  const [users, setUsers] = useState([])
  const [u, setU] = useState(null)
  const [audit, setAudit] = useState([])
  const [jobOut, setJobOut] = useState('')

  const load = () => {
    adminApi('/api/admin/settings').then(setS).catch((e) => ctx.notify(e.message))
    adminApi('/api/admin/users').then(setUsers).catch(() => {})
    adminApi('/api/admin/audit').then(setAudit).catch(() => {})
  }
  useEffect(() => { load() }, [])

  async function save(e) {
    e.preventDefault()
    const body = { ...s }
    NUM.forEach((k) => (body[k] = Number(body[k])))
    body.welcomeVoucher = { ...s.welcomeVoucher, valueRp: Number(s.welcomeVoucher.valueRp), minSpendRp: Number(s.welcomeVoucher.minSpendRp), startAfterDays: Number(s.welcomeVoucher.startAfterDays), validDays: Number(s.welcomeVoucher.validDays) }
    try { setS(await adminApi('/api/admin/settings', { method: 'PUT', body })); ctx.notify('Pengaturan tersimpan') } catch (e) { ctx.notify(e.message) }
  }

  async function saveUser(e) {
    e.preventDefault()
    try {
      if (u.id) await adminApi(`/api/admin/users/${u.id}`, { method: 'PUT', body: u })
      else await adminApi('/api/admin/users', { method: 'POST', body: u })
      ctx.notify('User tersimpan'); setU(null); load()
    } catch (e) { ctx.notify(e.message) }
  }

  async function runJob(j) {
    try { const r = await adminApi(`/api/admin/jobs/${j}/run`, { method: 'POST' }); setJobOut(JSON.stringify(r)); ctx.notify(`Job ${j} dijalankan`) } catch (e) { ctx.notify(e.message) }
  }

  async function seed() {
    try { await adminApi('/api/admin/seed', { method: 'POST' }); ctx.notify('Outlet contoh dibuat') } catch (e) { ctx.notify(e.message) }
  }

  if (!s) return <div className="text-sm">Memuat…</div>
  const ro = !ctx.lead
  const set = (k) => (e) => setS({ ...s, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const setW = (k) => (e) => setS({ ...s, welcomeVoucher: { ...s.welcomeVoucher, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value } })

  return (
    <div className="space-y-6">
      <form onSubmit={save} className="card space-y-3">
        <div className="font-extrabold">Program stamp</div>
        <div className="grid md:grid-cols-4 gap-3">
          <Field label="Stamp per reward"><input className="input" disabled={ro} value={s.stampsPerReward} onChange={set('stampsPerReward')} /></Field>
          <Field label="Judul reward"><input className="input" disabled={ro} value={s.rewardTitle} onChange={set('rewardTitle')} /></Field>
          <Field label="Nilai reward (Rp)"><input className="input" disabled={ro} value={s.rewardValueRp} onChange={set('rewardValueRp')} /></Field>
          <Field label="Voucher reward berlaku (hari)"><input className="input" disabled={ro} value={s.rewardVoucherValidDays} onChange={set('rewardVoucherValidDays')} /></Field>
        </div>
        <div className="font-extrabold pt-2">Anti-abuse</div>
        <div className="grid md:grid-cols-4 gap-3">
          <Field label="Maks. stamp / outlet / hari"><input className="input" disabled={ro} value={s.maxStampsPerOutletPerDay} onChange={set('maxStampsPerOutletPerDay')} /></Field>
          <Field label="Maks. stamp / hari"><input className="input" disabled={ro} value={s.maxStampsPerDay} onChange={set('maxStampsPerDay')} /></Field>
          <Field label="Jeda minimal (menit)"><input className="input" disabled={ro} value={s.minMinutesBetweenStamps} onChange={set('minMinutesBetweenStamps')} /></Field>
          <Field label="Geofence (m, hanya flag)"><input className="input" disabled={ro} value={s.geofenceM} onChange={set('geofenceM')} /></Field>
          <Field label="Reward bisa ditukar H+ (hari)"><input className="input" disabled={ro} value={s.rewardRedeemAfterDays} onChange={set('rewardRedeemAfterDays')} /></Field>
          <Field label="Kuota penukaran / gerobak / hari (0 = tanpa batas)"><input className="input" disabled={ro} value={s.maxRedemptionsPerOutletPerDay} onChange={set('maxRedemptionsPerOutletPerDay')} /></Field>
        </div>
        <div className="font-extrabold pt-2">Voucher Balik Lagi (member baru)</div>
        <div className="grid md:grid-cols-5 gap-3">
          <label className="flex items-center gap-2 text-sm pt-6"><input type="checkbox" disabled={ro} checked={s.welcomeVoucher.enabled} onChange={setW('enabled')} /> Aktif</label>
          <Field label="Judul"><input className="input" disabled={ro} value={s.welcomeVoucher.title} onChange={setW('title')} /></Field>
          <Field label="Nilai (Rp)"><input className="input" disabled={ro} value={s.welcomeVoucher.valueRp} onChange={setW('valueRp')} /></Field>
          <Field label="Min. belanja"><input className="input" disabled={ro} value={s.welcomeVoucher.minSpendRp} onChange={setW('minSpendRp')} /></Field>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Mulai H+"><input className="input" disabled={ro} value={s.welcomeVoucher.startAfterDays} onChange={setW('startAfterDays')} /></Field>
            <Field label="Berlaku (hari)"><input className="input" disabled={ro} value={s.welcomeVoucher.validDays} onChange={setW('validDays')} /></Field>
          </div>
        </div>
        <div className="font-extrabold pt-2">Halaman customer</div>
        <div className="grid md:grid-cols-4 gap-3">
          <Field label="Hitung mundur tukar (detik)"><input className="input" disabled={ro} value={s.redeemCountdownSec} onChange={set('redeemCountdownSec')} /></Field>
          <label className="flex items-center gap-2 text-sm pt-6"><input type="checkbox" disabled={ro} checked={s.feedbackPrompt} onChange={set('feedbackPrompt')} /> Tanya rating</label>
          <label className="flex items-center gap-2 text-sm pt-6"><input type="checkbox" disabled={ro} checked={s.feedbackRequired} onChange={set('feedbackRequired')} /> Rating wajib sebelum voucher bisa ditukar</label>
          <Field label="Kode promo aktif"><input className="input" disabled={ro} value={s.activePromoCode || ''} onChange={set('activePromoCode')} placeholder="MOZZA-DUO" /></Field>
          <Field label="Pertanyaan promo"><input className="input" disabled={ro} value={s.activePromoQuestion || ''} onChange={set('activePromoQuestion')} placeholder="Beli Mozza Duo hari ini?" /></Field>
        </div>
        <Field label="Email digest/rekap"><input className="input" disabled={ro} value={s.adminEmail || ''} onChange={set('adminEmail')} /></Field>
        {!ro && <button className="btn-primary">Simpan pengaturan</button>}
      </form>

      <div className="card space-y-3">
        <div className="font-extrabold">Admin</div>
        <Table cols={[{ key: 'name', label: 'Nama' }, { key: 'role', label: 'Role' }, { key: 'areas', label: 'Area', render: (x) => x.areas?.join(', ') || '–' }, { key: 'email', label: 'Email' }, { key: 'active', label: 'Status', render: (x) => (x.active ? 'Aktif' : 'Nonaktif') },
          { key: 'act', label: '', render: (x) => ctx.lead && <span className="flex gap-2"><button className="underline text-deep" onClick={() => setU({ ...x, pin: '' })}>Edit / reset PIN</button>
            {x.id !== ctx.user.id && <button className="underline text-brand" onClick={async () => { await adminApi(`/api/admin/users/${x.id}/toggle-active`, { method: 'POST' }); load() }}>{x.active ? 'Nonaktifkan' : 'Aktifkan'}</button>}</span> }]} rows={users} />
        {ctx.lead && <button className="btn-ghost" onClick={() => setU({ name: '', role: 'Viewer', areas: [], pin: '', email: '' })}>+ Admin</button>}
      </div>

      {ctx.lead && (
        <div className="card space-y-3">
          <div className="font-extrabold">Job & data</div>
          <div className="flex flex-wrap gap-2">
            {['activate', 'expire', 'digest', 'weekly', 'backup'].map((j) => <button key={j} className="btn-ghost" onClick={() => runJob(j)}>Jalankan {j}</button>)}
            <button className="btn-ghost" onClick={seed}>Isi outlet contoh</button>
          </div>
          {jobOut && <pre className="text-xs bg-tint/40 p-2 rounded-lg overflow-auto">{jobOut}</pre>}
        </div>
      )}

      <div className="card">
        <div className="font-extrabold mb-2">Audit log (200 terakhir)</div>
        <Table cols={[{ key: 'at', label: 'Waktu' }, { key: 'who', label: 'Siapa' }, { key: 'action', label: 'Aksi' }, { key: 'target', label: 'Target' }, { key: 'detail', label: 'Detail', render: (a) => JSON.stringify(a.detail) }]} rows={audit} />
      </div>

      {u && (
        <div className="fixed inset-0 bg-black/40 z-40 grid place-items-center p-4" onClick={() => setU(null)}>
          <form className="card w-full max-w-md space-y-3" onClick={(e) => e.stopPropagation()} onSubmit={saveUser}>
            <div className="font-extrabold">{u.id ? 'Edit admin' : 'Admin baru'}</div>
            <Field label="Nama"><input className="input" required value={u.name} onChange={(e) => setU({ ...u, name: e.target.value })} /></Field>
            <Field label="Role"><select className="input" value={u.role} onChange={(e) => setU({ ...u, role: e.target.value })}>{ctx.meta.roles.map((r) => <option key={r}>{r}</option>)}</select></Field>
            {u.role === 'Area' && u.areas.length === 0 && <div className="text-xs text-brand font-bold">Role Area wajib memilih minimal satu area.</div>}
            {u.role === 'Area' && <Field label="Area"><div className="flex flex-wrap gap-2">{ctx.meta.areas.map((a) => <button type="button" key={a} className={`chip ${u.areas.includes(a) ? 'chip-on' : ''}`} onClick={() => setU({ ...u, areas: u.areas.includes(a) ? u.areas.filter((x) => x !== a) : [...u.areas, a] })}>{a}</button>)}</div></Field>}
            <Field label="Email (untuk digest)"><input className="input" value={u.email || ''} onChange={(e) => setU({ ...u, email: e.target.value })} /></Field>
            <Field label={u.id ? 'PIN baru (kosongkan bila tidak diganti)' : 'PIN (4–6 angka)'}><input className="input" inputMode="numeric" maxLength={6} value={u.pin} onChange={(e) => setU({ ...u, pin: e.target.value })} /></Field>
            <div className="grid grid-cols-2 gap-2"><button type="button" className="btn-ghost" onClick={() => setU(null)}>Batal</button><button className="btn-primary" disabled={u.role === 'Area' && u.areas.length === 0}>Simpan</button></div>
          </form>
        </div>
      )}
    </div>
  )
}
