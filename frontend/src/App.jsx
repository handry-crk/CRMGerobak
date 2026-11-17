import { Suspense, lazy } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

// Alamat utama: browser yang pernah login admin diarahkan ke dashboard, lainnya ke halaman customer
function Home() {
  let isAdmin = false
  try { isAdmin = !!localStorage.getItem('sb_admin') } catch { /* ignore */ }
  return <Navigate to={isAdmin ? '/admin' : '/saya'} replace />
}
import Scan from './pages/Scan.jsx'
import Me from './pages/Me.jsx'

// Admin dimuat terpisah agar halaman customer tetap ringan
const Admin = lazy(() => import('./admin/Admin.jsx'))

export default function App() {
  return (
    <Routes>
      <Route path="/s/:token" element={<Scan />} />
      <Route path="/saya" element={<Me />} />
      <Route
        path="/admin/*"
        element={
          <Suspense fallback={<div className="p-6 text-center text-sm">Memuat dashboard…</div>}>
            <Admin />
          </Suspense>
        }
      />
      <Route path="/" element={<Home />} />
      <Route path="*" element={<Navigate to="/saya" replace />} />
    </Routes>
  )
}
