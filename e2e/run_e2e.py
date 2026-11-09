"""End-to-end test Stamp Bojot lewat UI (Playwright + Chrome).

Jalankan backend dulu (mock DB agar bersih):
  USE_MOCK_DB=true ENABLE_SCHEDULER=false RATE_LIMIT_IP_PER_MIN=100000 RATE_LIMIT_PHONE_PER_MIN=100000 \
    uvicorn app.main:app --port 8000   (dari folder backend, setelah `npm run build` di frontend)
Lalu:  python e2e/run_e2e.py [--base http://localhost:8000] [--chrome /usr/bin/google-chrome] [--shots e2e/shots]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
import uuid

import httpx
from playwright.async_api import async_playwright, expect

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, note: str = ""):
    RESULTS.append((name, ok, note))
    print(("PASS " if ok else "FAIL ") + name + (f" — {note}" if note else ""))


CURRENT_PAGE = {"admin": None}


async def step(name, coro):
    try:
        await coro
        record(name, True)
    except Exception as e:  # noqa: BLE001
        record(name, False, str(e).splitlines()[0][:160])
        pg = CURRENT_PAGE.get("admin")
        if pg is not None:
            try:  # tutup modal/overlay yang mungkin tertinggal agar langkah berikutnya tidak terdampak
                await pg.keyboard.press("Escape")
                await pg.reload()
                await pg.wait_for_load_state()
            except Exception:  # noqa: BLE001
                pass


async def main(base: str, chrome: str, shots: str):
    os.makedirs(shots, exist_ok=True)
    api = httpx.AsyncClient(base_url=base, timeout=20)
    tok = (await api.post("/api/admin/login", json={"name": "Admin", "pin": "1234"})).json()["token"]
    H = {"Authorization": f"Bearer {tok}"}
    seed = await api.post("/api/admin/seed", headers=H)
    outs = seed.json()["outlets"] if seed.status_code == 200 else (await api.get("/api/admin/outlets", headers=H)).json()
    await api.put("/api/admin/settings", headers=H, json={"minMinutesBetweenStamps": 0, "rewardRedeemAfterDays": 0})

    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=chrome or None, args=["--no-sandbox"])
        errors: list[str] = []

        # ============ ADMIN ============
        actx = await browser.new_context(viewport={"width": 1280, "height": 900})
        ad = await actx.new_page()
        CURRENT_PAGE["admin"] = ad
        ad.set_default_timeout(10000)
        ad.on("pageerror", lambda e: errors.append("admin: " + str(e)))

        async def admin_login(name, pin):
            await ad.goto(f"{base}/admin")
            await ad.wait_for_selector("select")
            await ad.select_option("select", name)
            await ad.fill("input[type=password]", pin)
            await ad.click('button:has-text("Masuk")')
            await ad.wait_for_selector("text=Stamp Bojot · Dashboard")

        async def admin_logout():
            await ad.click('button:has-text("Keluar")')
            await ad.wait_for_selector("select")

        async def t_admin_login():
            await admin_login("Admin", "1234")
            await ad.wait_for_selector("text=Member aktif 30D")
            await ad.screenshot(path=f"{shots}/a01_ringkasan.png")
        await step("Admin: login Manager & Ringkasan tampil", t_admin_login())

        async def t_settings():
            await ad.click('a:has-text("Pengaturan")')
            await ad.wait_for_selector("text=Program stamp")
            await ad.fill('label:has-text("Kuota penukaran") input', "10")
            await ad.click('button:has-text("Simpan pengaturan")')
            await ad.wait_for_selector("text=Pengaturan tersimpan")
        await step("Admin: ubah & simpan pengaturan", t_settings())

        async def t_users():
            for name, role, pin, area in [("Lead CRM", "CRM Lead", "2222", None), ("Area Bdg", "Area", "3333", "Bandung"), ("Viewer", "Viewer", "4444", None)]:
                await ad.click('button:has-text("+ Admin")')
                await ad.fill('label:has-text("Nama") input', name)
                await ad.select_option('label:has-text("Role") select', role)
                if area:
                    await ad.click(f'form button:has-text("{area}")')
                await ad.fill('label:has-text("PIN") input', pin)
                await ad.click('button:text-is("Simpan")')
                await ad.wait_for_selector("text=User tersimpan")
                await ad.wait_for_timeout(300)
            await expect(ad.locator("text=Lead CRM").first).to_be_visible()
            await ad.screenshot(path=f"{shots}/a02_admins.png", full_page=True)
        await step("Admin: buat akun CRM Lead, Area Bandung, Viewer", t_users())

        async def t_outlet_create():
            await ad.click('a:has-text("Outlet & QR")')
            await ad.wait_for_selector("text=BDG-BRG-01")
            await ad.click('button:has-text("+ Outlet")')
            await ad.fill('input[placeholder="BDG-BRG-01"]', "BDG-E2E-01")
            await ad.fill('input[placeholder="Gerobak AA – Braga"]', "Gerobak AA – E2E")
            await ad.fill('input[placeholder="-6.9175"]', "-6.9")
            await ad.fill('input[placeholder="107.6098"]', "107.6")
            await ad.click('button:text-is("Simpan")')
            await ad.wait_for_selector("text=Outlet tersimpan")
            await expect(ad.locator("text=BDG-E2E-01").first).to_be_visible()
        await step("Admin: tambah outlet lewat form", t_outlet_create())

        async def t_outlet_detail_tx():
            await ad.click("text=Gerobak AA – Braga")
            await ad.wait_for_selector("text=Heatmap hari × jam")
            await ad.fill('label:has-text("Transaksi (POS)") input', "70")
            await ad.fill('label:has-text("Hadiah gratis keluar") input', "2")
            await ad.click('button:has-text("Simpan laporan hari ini")')
            await ad.wait_for_selector("text=Transaksi tersimpan")
            await ad.screenshot(path=f"{shots}/a03_outlet_detail.png", full_page=True)
            await ad.click('button:has-text("Tutup")')
        await step("Admin: detail outlet, isi transaksi & hadiah keluar", t_outlet_detail_tx())

        async def t_sticker():
            async with ad.expect_popup() as pop:
                await ad.locator('tr:has-text("BDG-BRG-01") button:has-text("Stiker A6")').click()
            pdf = await pop.value
            await pdf.wait_for_load_state()
            assert pdf.url.startswith("blob:"), pdf.url
        await step("Admin: stiker A6 terbuka (PDF)", t_sticker())

        rotated_old = outs[3]["qrToken"]

        async def t_rotate():
            ad.once("dialog", lambda d: asyncio.ensure_future(d.accept()))
            await ad.locator('tr:has-text("BDG-DGO-01") button:has-text("Ganti QR")').click()
            await ad.wait_for_selector("text=QR diganti")
        await step("Admin: ganti QR outlet Dago", t_rotate())

        async def t_staff():
            await ad.click('a:has-text("Anti-fraud")')
            await ad.wait_for_selector("text=Nomor crew & keluarga")
            await ad.fill('input[placeholder="08…"]', "0899 0000 111")
            await ad.fill('input[placeholder="BDG-BRG-01"]', "BDG-BRG-01")
            await ad.click('button:text-is("Tambah")')
            await ad.wait_for_selector("text=Nomor crew ditambahkan")
            await expect(ad.locator("text=08990000111").first).to_be_visible()
        await step("Admin: tambah nomor crew", t_staff())

        async def t_campaign():
            await ad.click('a:has-text("Voucher")')
            await ad.wait_for_selector('button:has-text("+ Campaign voucher")')
            await ad.click('button:has-text("+ Campaign voucher")')
            await ad.fill('input[placeholder="BACK-03"]', "E2E-01")
            await ad.fill('input[placeholder="Balik Lagi: potongan 3.000"]', "Voucher E2E: potongan 2.000")
            await ad.click('button:text-is("Terbitkan")')
            await ad.wait_for_selector("text=Campaign E2E-01")
        await step("Admin: terbitkan campaign voucher (segmen semua)", t_campaign())

        # ============ CUSTOMER ============
        cctx = await browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                                         geolocation={"latitude": -6.9175, "longitude": 107.6098}, permissions=["geolocation"])
        pg = await cctx.new_page()
        pg.on("pageerror", lambda e: errors.append("customer: " + str(e)))
        qr1, qr2, qr3 = outs[0]["qrToken"], outs[1]["qrToken"], outs[2]["qrToken"]

        async def t_register():
            await pg.goto(f"{base}/s/{qr1}")
            await pg.wait_for_selector("#name")
            await pg.fill("#name", "Dina")
            await pg.fill("#phone", "+62 812-3456-7890")
            assert await pg.input_value("#phone") == "081234567890"
            await pg.click('button:has-text("Ambil stamp")')
            await pg.wait_for_selector("text=Stamp pertama dapet")
            await expect(pg.locator("text=Voucher Balik Lagi").first).to_be_visible()
            await expect(pg.locator("text=Udah dilayani?").first).to_be_visible()
            assert await pg.locator("text=rasanya gimana").count() == 0
            await pg.screenshot(path=f"{shots}/c01_register.png", full_page=True)
        await step("Customer: daftar (nama + nomor 08), stamp 1, voucher Balik Lagi terjadwal, tanpa tanya rasa", t_register())

        async def t_service_today_optional():
            await pg.click('button[aria-label^="Udah dilayani?"][aria-label*="Puas banget"]')
            await pg.wait_for_selector("text=Cepat dilayani")
            await pg.click('button:has-text("Crew ramah")')
            await pg.wait_for_selector("text=Tersimpan, makasih")
        await step("Customer: rating pelayanan hari ini (opsional) tersimpan", t_service_today_optional())

        async def t_already_today():
            await pg.reload()
            await pg.wait_for_selector("text=udah masuk")
        await step("Customer: scan ulang outlet sama → 'stamp hari ini udah masuk'", t_already_today())

        async def t_visit2_review_gate():
            m = (await api.get("/api/admin/members?q=081234567890", headers=H)).json()["items"][0]
            await api.post(f"/api/admin/members/{m['id']}/adjust-stamps", headers=H, json={"delta": 3, "reason": "e2e"})
            await pg.goto(f"{base}/s/{qr2}")
            await pg.wait_for_selector("text=stamp penuh")
            await expect(pg.locator("text=rasanya gimana").first).to_be_visible()
            assert await pg.locator("text=Pelayanan crew di Gerobak AA – Braga").count() == 0, "pelayanan kunjungan 1 sudah dinilai, tidak boleh ditanya lagi"
            btn = pg.locator('button:has-text("Tukar sekarang di gerobak")').first
            assert await btn.is_disabled()
            await pg.screenshot(path=f"{shots}/c02_visit2_gate.png", full_page=True)
            await pg.click('button[aria-label^="Cimol dari"][aria-label*="Kurang (2"]')
            await pg.wait_for_selector("text=Lainnya, tulis sendiri")
            await pg.click('button:has-text("Kurang panas")')
            await pg.click('button:has-text("Lainnya, tulis sendiri")')
            await pg.fill('input[placeholder^="Contoh: cimolnya"]', "agak alot")
            await pg.click('button:has-text("Simpan")')
            await pg.wait_for_timeout(500)
            assert not await btn.is_disabled()
        await step("Customer: kunjungan 2 → stamp ke-5 reward, wajib nilai rasa kunjungan 1 (tag + tulis sendiri), tombol tukar terbuka", t_visit2_review_gate())

        redeem_code = {}

        async def t_redeem_green():
            await pg.locator('button:has-text("Tukar sekarang di gerobak")').first.click()
            await pg.wait_for_selector("text=Tunjukkan layar ini")
            await pg.click('button:text-is("Tukar")')
            await pg.wait_for_selector("text=Voucher ditukar")
            await expect(pg.locator("text=Crew: Berikan Cimol Bojot kecil gratis").first).to_be_visible()
            code = (await pg.locator("div.tracking-\\[0\\.3em\\]").inner_text()).strip()
            assert len(code) == 4, code
            redeem_code["v"] = code
            await pg.screenshot(path=f"{shots}/c03_green.png")
            await pg.click('button:has-text("Selesai")')
        await step("Customer: tukar reward → layar hijau + instruksi crew + kode 4 huruf", t_redeem_green())

        async def t_me_page():
            await pg.goto(f"{base}/saya")
            await pg.wait_for_selector("text=Hai, Dina")
            await expect(pg.locator("text=rasanya gimana").first).to_be_visible()  # rasa kunjungan 2 tertunda
            await pg.click('button:has-text("Riwayat kunjungan")')
            await expect(pg.locator("text=Ditukar").first).to_be_visible()
            await pg.screenshot(path=f"{shots}/c04_me.png", full_page=True)
        await step("Customer: halaman saya — sapaan nama, rasa tertunda, riwayat voucher ditukar", t_me_page())

        async def t_switch_device():
            ctx2 = await browser.new_context(viewport={"width": 390, "height": 844})
            p2 = await ctx2.new_page()
            await p2.goto(f"{base}/saya")
            await p2.wait_for_selector("#phone")
            await p2.fill("#phone", "081234567890")
            await p2.click('button:has-text("Lanjutkan")')
            await p2.wait_for_selector("text=Hai, Dina")
            await ctx2.close()
        await step("Customer: HP baru → masuk dengan nomor, akun sama", t_switch_device())

        async def t_staff_scan():
            ctx3 = await browser.new_context(viewport={"width": 390, "height": 844})
            p3 = await ctx3.new_page()
            await p3.goto(f"{base}/s/{qr3}")
            await p3.wait_for_selector("#name")
            await p3.fill("#name", "Crew")
            await p3.fill("#phone", "08990000111")
            await p3.click('button:has-text("Ambil stamp")')
            await p3.wait_for_selector("text=terdaftar sebagai crew")
            assert await p3.locator("text=Voucher Balik Lagi").count() == 0
            await ctx3.close()
        await step("Customer (crew): stamp tercatat tanpa voucher", t_staff_scan())

        async def t_rotated_qr():
            ctx4 = await browser.new_context(viewport={"width": 390, "height": 844})
            p4 = await ctx4.new_page()
            await p4.goto(f"{base}/s/{rotated_old}")
            await p4.wait_for_selector("text=sudah diganti")
            await ctx4.close()
        await step("Customer: QR lama setelah 'Ganti QR' → pesan stiker baru", t_rotated_qr())

        # ============ ADMIN: verifikasi data customer & role ============
        async def t_admin_sees_data():
            await ad.click('a:has-text("Member")')
            await ad.fill('input[placeholder="0812… atau nama"]', "0812")
            await ad.wait_for_selector("text=081234567890")
            await ad.click("text=081234567890")
            await ad.wait_for_selector("text=Alasan tindakan")
            await expect(ad.locator("text=Cimol Bojot kecil gratis").first).to_be_visible()
            await ad.fill('label:has-text("Alasan tindakan") input', "e2e kompensasi")
            await ad.click('button:has-text("Voucher manual")')
            await ad.wait_for_selector("text=Tersimpan")
            await ad.screenshot(path=f"{shots}/a04_member_detail.png", full_page=True)
            await ad.click('button:has-text("Tutup")')
            await ad.click('a:has-text("Rating")')
            await ad.wait_for_selector("text=Pelayanan crew")
            await expect(ad.locator("text=agak alot").first).to_be_visible()
            await ad.click('a:has-text("Anti-fraud")')
            await ad.wait_for_selector("text=Rekonsiliasi hadiah")
            await expect(ad.locator("text=Hadiah keluar > voucher").first).to_be_visible()
            await ad.screenshot(path=f"{shots}/a05_antifraud.png", full_page=True)
        await step("Admin: data customer tampil (member, voucher manual, catatan rasa, rekonsiliasi selisih)", t_admin_sees_data())

        async def t_viewer_role():
            await admin_logout()
            await admin_login("Viewer", "4444")
            await ad.click('a:has-text("Member")')
            await ad.wait_for_selector("text=****")
            assert await ad.locator('a:has-text("Pengaturan")').count() == 0
            assert await ad.locator('button:has-text("Ekspor CSV")').count() == 0
        await step("Admin (Viewer): nomor dimasker, tanpa Pengaturan & ekspor", t_viewer_role())

        async def t_area_role():
            await admin_logout()
            await admin_login("Area Bdg", "3333")
            await ad.click('a:has-text("Outlet & QR")')
            await ad.wait_for_selector("text=BDG-BRG-01")
            assert await ad.locator("text=JKT-MGD-01").count() == 0, "outlet Depok tidak boleh terlihat"
        await step("Admin (Area Bandung): hanya outlet Bandung", t_area_role())

        async def t_lead_role():
            await admin_logout()
            await admin_login("Lead CRM", "2222")
            await ad.click('a:has-text("Pengaturan")')
            await ad.wait_for_selector("text=Program stamp")
            assert await ad.locator('button:has-text("+ Admin")').count() == 0
            await expect(ad.locator("text=Hanya Manager yang bisa").first).to_be_visible()
        await step("Admin (CRM Lead): pengaturan bisa, kelola admin tidak", t_lead_role())

        async def t_pin_lock():
            await admin_logout()
            for _ in range(5):
                await ad.select_option("select", "Viewer")
                await ad.fill("input[type=password]", "0000")
                await ad.click('button:has-text("Masuk")')
                await ad.wait_for_timeout(250)
            await expect(ad.locator("text=terkunci").first).to_be_visible()
        await step("Admin: 5× PIN salah → akun terkunci", t_pin_lock())

        await browser.close()
        if errors:
            record("Tidak ada error JavaScript di browser", False, "; ".join(errors)[:200])
        else:
            record("Tidak ada error JavaScript di browser", True)

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} skenario lulus")
    return passed == len(RESULTS)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--chrome", default=os.environ.get("CHROME_PATH", "/usr/bin/google-chrome"))
    ap.add_argument("--shots", default="e2e/shots")
    a = ap.parse_args()
    ok = asyncio.run(main(a.base, a.chrome if os.path.exists(a.chrome) else "", a.shots))
    sys.exit(0 if ok else 1)
