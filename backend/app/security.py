"""Autentikasi admin (nama + PIN), token sesi, rate limit sederhana, device token member."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import timedelta

from fastapi import Depends, Header, HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorDatabase

from .db import get_db
from .utils import hash_pin, iso, new_token, now_utc, parse_iso, verify_pin

MAX_PIN_ATTEMPTS = 5
LOCK_MINUTES = 15
SESSION_HOURS = 12


class RateLimiter:
    """Sliding window in-memory; cukup untuk satu instance. Ganti Redis bila multi-instance."""

    def __init__(self) -> None:
        self.buckets: dict[str, deque] = defaultdict(deque)

    def hit(self, key: str, limit: int, window_sec: int = 60) -> bool:
        now = time.monotonic()
        q = self.buckets[key]
        while q and now - q[0] > window_sec:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


rate_limiter = RateLimiter()


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce_rate(key: str, limit: int, window_sec: int = 60) -> None:
    if not rate_limiter.hit(key, limit, window_sec):
        raise HTTPException(429, {"code": "rate_limited", "message": "Coba lagi sebentar ya, Kak."})


# ---------- Admin ----------

async def admin_login(db: AsyncIOMotorDatabase, name: str, pin: str) -> dict:
    user = await db.admin_users.find_one({"name": name, "active": True})
    if not user:
        raise HTTPException(401, {"code": "bad_login", "message": "Nama atau PIN salah."})
    locked = user.get("lockedUntil")
    if locked and parse_iso(locked) > now_utc():
        sisa = int((parse_iso(locked) - now_utc()).total_seconds() // 60) + 1
        raise HTTPException(423, {"code": "locked", "message": f"Akun terkunci. Coba lagi {sisa} menit."})
    if not verify_pin(pin, user["pinHash"]):
        attempts = int(user.get("failedAttempts", 0)) + 1
        upd: dict = {"failedAttempts": attempts}
        if attempts >= MAX_PIN_ATTEMPTS:
            upd["lockedUntil"] = iso(now_utc() + timedelta(minutes=LOCK_MINUTES))
            upd["failedAttempts"] = 0
            await db.admin_users.update_one({"_id": user["_id"]}, {"$set": upd})
            raise HTTPException(423, {"code": "locked", "message": f"PIN salah {MAX_PIN_ATTEMPTS}×. Akun terkunci {LOCK_MINUTES} menit."})
        await db.admin_users.update_one({"_id": user["_id"]}, {"$set": upd})
        sisa = MAX_PIN_ATTEMPTS - attempts
        raise HTTPException(401, {"code": "bad_login", "message": f"PIN salah. Sisa {sisa} percobaan."})
    await db.admin_users.update_one({"_id": user["_id"]}, {"$set": {"failedAttempts": 0, "lockedUntil": None}})
    token = new_token(48)
    await db.admin_sessions.insert_one(
        {"token": token, "userId": user["_id"], "createdAt": iso(now_utc()),
         "expiresAt": iso(now_utc() + timedelta(hours=SESSION_HOURS))}
    )
    return {"token": token, "user": admin_public(user)}


def admin_public(u: dict) -> dict:
    return {"id": u["_id"], "name": u["name"], "role": u["role"], "areas": u.get("areas", []), "active": u.get("active", True)}


async def current_admin(
    authorization: str | None = Header(default=None), db: AsyncIOMotorDatabase = Depends(get_db)
) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, {"code": "no_token", "message": "Silakan login dulu."})
    token = authorization.split(" ", 1)[1].strip()
    sess = await db.admin_sessions.find_one({"token": token})
    if not sess or parse_iso(sess["expiresAt"]) < now_utc():
        raise HTTPException(401, {"code": "expired", "message": "Sesi habis, login lagi ya."})
    user = await db.admin_users.find_one({"_id": sess["userId"], "active": True})
    if not user:
        raise HTTPException(401, {"code": "inactive", "message": "Akun tidak aktif."})
    return user


def require_roles(*roles: str):
    async def dep(user: dict = Depends(current_admin)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(403, {"code": "forbidden", "message": "Role Anda tidak punya akses ke fitur ini."})
        return user
    return dep


def area_filter(user: dict) -> dict:
    """Role Area hanya melihat area yang ditugaskan."""
    if user["role"] == "Area":
        return {"area": {"$in": user.get("areas") or ["__none__"]}}
    return {}


def can_see_full_phone(user: dict) -> bool:
    return user["role"] in ("CRM Lead", "Manager")


def new_pin_hash(pin: str) -> str:
    if not pin.isdigit() or not 4 <= len(pin) <= 6:
        raise HTTPException(422, {"code": "bad_pin", "message": "PIN harus 4–6 angka."})
    return hash_pin(pin)


# ---------- Member (device token) ----------

async def current_member(
    x_device_token: str | None = Header(default=None), db: AsyncIOMotorDatabase = Depends(get_db)
) -> dict:
    if not x_device_token:
        raise HTTPException(401, {"code": "no_device", "message": "Masukkan nomor WhatsApp dulu ya, Kak."})
    member = await db.members.find_one({"deviceTokens": x_device_token})
    if not member:
        raise HTTPException(401, {"code": "unknown_device", "message": "Masukkan nomor WhatsApp dulu ya, Kak."})
    return member
