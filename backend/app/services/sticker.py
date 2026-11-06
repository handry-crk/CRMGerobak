"""Stiker QR A6 siap cetak (PDF) per gerobak, plus tent card A5 dengan kalimat crew."""
from __future__ import annotations

import io

import qrcode
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A5, A6, landscape
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

RED = HexColor("#D7191F")
DEEP = HexColor("#B32E26")
CHARCOAL = HexColor("#1F1A1A")
TINT = HexColor("#F7D4D5")

CREW_LINE = "Kak, scan QR-nya ya — 5 kali beli, gratis satu."


def _qr_image(url: str) -> ImageReader:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=1)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1F1A1A", back_color="white").convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


def _draw_sticker(c: canvas.Canvas, w: float, h: float, outlet: dict, url: str, settings: dict) -> None:
    # Bingkai merah
    c.setStrokeColor(RED)
    c.setLineWidth(4)
    c.roundRect(4 * mm, 4 * mm, w - 8 * mm, h - 8 * mm, 6 * mm, stroke=1, fill=0)

    # Header merah
    c.setFillColor(RED)
    c.roundRect(4 * mm, h - 30 * mm, w - 8 * mm, 26 * mm, 6 * mm, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(w / 2, h - 16 * mm, "CIMOL BOJOT AA")
    c.setFont("Helvetica", 11)
    c.drawCentredString(w / 2, h - 24 * mm, "Stamp Bojot")

    # Headline
    per = settings.get("stampsPerReward", 5)
    reward = settings.get("rewardTitle", "Cimol Bojot kecil gratis")
    c.setFillColor(CHARCOAL)
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(w / 2, h - 40 * mm, "Scan, dapet stamp.")
    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(DEEP)
    c.drawCentredString(w / 2, h - 47 * mm, f"{per} stamp = {reward}.")

    # QR
    size = min(w, h) * 0.52
    x = (w - size) / 2
    y = h - 52 * mm - size
    c.drawImage(_qr_image(url), x, y, size, size)

    # Footer
    c.setFillColor(CHARCOAL)
    c.setFont("Helvetica", 9)
    c.drawCentredString(w / 2, y - 6 * mm, "Buka kamera HP, arahkan ke QR. Tanpa install aplikasi.")
    c.setFont("Helvetica", 7)
    c.setFillColor(HexColor("#8A7B7B"))
    c.drawCentredString(w / 2, 7 * mm, f"{outlet['code']} · {outlet['name']}")


def sticker_pdf(outlet: dict, url: str, settings: dict) -> bytes:
    buf = io.BytesIO()
    w, h = A6
    c = canvas.Canvas(buf, pagesize=A6)
    _draw_sticker(c, w, h, outlet, url, settings)
    c.showPage()
    c.save()
    return buf.getvalue()


def tentcard_pdf(outlet: dict, url: str, settings: dict) -> bytes:
    """A5 landscape dilipat dua: sisi customer (stiker) + sisi crew (kalimat ajakan, ciri layar hijau)."""
    buf = io.BytesIO()
    w, h = landscape(A5)
    c = canvas.Canvas(buf, pagesize=landscape(A5))
    half = w / 2
    # Sisi customer (kiri)
    c.saveState()
    _draw_sticker(c, half, h, outlet, url, settings)
    c.restoreState()
    # Sisi crew (kanan)
    c.saveState()
    c.translate(half, 0)
    c.setFillColor(TINT)
    c.rect(0, 0, half, h, stroke=0, fill=1)
    c.setFillColor(CHARCOAL)
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(half / 2, h - 18 * mm, "UNTUK CREW")
    c.setFont("Helvetica", 10)
    lines = [
        "Satu kalimat saat customer menunggu:",
        f"“{CREW_LINE}”",
        "",
        "Penukaran voucher:",
        "• Customer menunjukkan LAYAR HIJAU penuh",
        "• Ada nama gerobak ini, jam berjalan,",
        "  kode 4 huruf, dan garis hitung mundur 3 menit",
        "• Serahkan hadiah sesuai judul di layar",
        "• Tidak perlu mencatat apa pun",
        "",
        "Layar abu-abu 'Sudah ditukar' = voucher sudah dipakai.",
    ]
    y = h - 30 * mm
    for ln in lines:
        c.drawString(10 * mm, y, ln)
        y -= 6.5 * mm
    c.restoreState()
    c.showPage()
    c.save()
    return buf.getvalue()
