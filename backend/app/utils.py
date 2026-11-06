"""Utilitas umum: waktu WIB, normalisasi nomor, hash PIN, token, jarak."""
from __future__ import annotations

import hashlib
import hmac
import math
import os
import re
import secrets
import string
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

WIB = ZoneInfo("Asia/Jakarta")

ID_MOBILE_RE = re.compile(r"^\+628\d{8,11}$")
HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
BULAN = [
    "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_wib() -> datetime:
    return datetime.now(WIB)


def today_wib() -> str:
    return now_wib().strftime("%Y-%m-%d")


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def day_str(dt: datetime) -> str:
    return dt.astimezone(WIB).strftime("%Y-%m-%d")


def hour_wib(dt: datetime) -> int:
    return dt.astimezone(WIB).hour


def add_days(day: str, n: int) -> str:
    d = datetime.strptime(day, "%Y-%m-%d") + timedelta(days=n)
    return d.strftime("%Y-%m-%d")


def format_tanggal(day: str, with_hari: bool = False) -> str:
    d = datetime.strptime(day, "%Y-%m-%d")
    s = f"{d.day} {BULAN[d.month - 1]} {d.year}"
    if with_hari:
        s = f"{HARI[d.weekday()]}, {s}"
    return s


def format_rp(n: int | float) -> str:
    return f"{int(round(n)):,}".replace(",", ".")


def normalize_phone(raw: str) -> str | None:
    """08xx / 62xx / +62xx → +62xx. None bila bukan nomor seluler Indonesia."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    elif digits.startswith("8"):
        digits = "62" + digits
    phone = "+" + digits
    return phone if ID_MOBILE_RE.match(phone) else None


def mask_phone(phone: str) -> str:
    if not phone or len(phone) < 8:
        return phone
    return phone[:6] + "****" + phone[-3:]


def hash_pin(pin: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 120_000).hex()
    return f"{salt}${digest}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$", 1)
    except ValueError:
        return False
    return hmac.compare_digest(hash_pin(pin, salt), stored)


def new_token(n: int = 32) -> str:
    return secrets.token_hex(n // 2)


def new_qr_token() -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(10))


def new_redeem_code() -> str:
    # Tanpa huruf yang mudah tertukar (I, O, Q)
    alphabet = "ABCDEFGHJKLMNPRSTUVWXYZ"
    return "".join(secrets.choice(alphabet) for _ in range(4))


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.strip().lower()).strip("-")
    return s or "x"


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path
