"""Inti CRM: identifikasi member, pemberian stamp, aturan anti-abuse, respons halaman customer."""
from __future__ import annotations

from datetime import timedelta

from motor.motor_asyncio import AsyncIOMotorDatabase

from ..utils import (
    day_str, haversine_m, hour_wib, iso, mask_phone, new_id, new_token, normalize_phone, now_utc,
    parse_iso, today_wib,
)
from .voucher import create_reward_voucher, create_welcome_voucher, member_vouchers


class StampError(Exception):
    def __init__(self, message: str, code: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


def member_public(m: dict) -> dict:
    return {
        "id": m["_id"],
        "maskedPhone": mask_phone(m["phone"]),
        "name": m.get("name"),
        "stampsActive": m.get("stampsActive", 0),
        "stampsTotal": m.get("stampsTotal", 0),
        "visits": m.get("visits", 0),
        "joinedAt": m.get("joinedAt"),
        "optIn": m.get("optIn", True),
        "isStaff": bool(m.get("isStaff")),
        "profileDone": bool(m.get("name")) and bool(m.get("source")),
    }


async def outlet_by_token(db: AsyncIOMotorDatabase, qr_token: str) -> dict:
    outlet = await db.outlets.find_one({"qrToken": qr_token})
    if outlet and outlet.get("active", True):
        return outlet
    replaced = await db.outlets.find_one({"oldTokens": qr_token})
    if replaced or (outlet and not outlet.get("active", True)):
        raise StampError(
            "QR gerobak ini sudah diganti. Minta crew tunjukkan stiker yang baru ya, Kak.", "qr_replaced", 410
        )
    raise StampError("QR tidak dikenal.", "qr_unknown", 404)


def outlet_public(o: dict, settings: dict) -> dict:
    return {
        "id": o["_id"],
        "code": o["code"],
        "name": o["name"],
        "area": o["area"],
        "city": o.get("city"),
        "stampsPerReward": settings["stampsPerReward"],
        "rewardTitle": settings["rewardTitle"],
        "promoCode": settings.get("activePromoCode") or None,
        "promoQuestion": settings.get("activePromoQuestion") or None,
        "feedbackPrompt": settings.get("feedbackPrompt", True),
        "redeemCountdownSec": settings.get("redeemCountdownSec", 180),
        "welcomeVoucher": settings["welcomeVoucher"],
    }


async def find_member_by_device(db: AsyncIOMotorDatabase, device_token: str | None) -> dict | None:
    if not device_token:
        return None
    return await db.members.find_one({"deviceTokens": device_token})


async def find_or_create_member(
    db: AsyncIOMotorDatabase, phone_raw: str, outlet: dict, settings: dict, opt_in: bool | None = None,
    name: str | None = None,
) -> tuple[dict, bool, dict | None]:
    phone = normalize_phone(phone_raw)
    if not phone:
        raise StampError("Nomor WhatsApp-nya belum pas, Kak. Tulis mulai 08, contoh 081234567890.", "bad_phone", 422)
    member = await db.members.find_one({"phone": phone})
    if member:
        return member, False, None
    name = (name or "").strip()[:40]
    if not name:
        raise StampError("Nama panggilannya diisi dulu ya, Kak.", "need_name", 422)
    now = now_utc()
    is_staff = await db.staff_numbers.find_one({"phone": phone}) is not None
    member = {
        "isStaff": is_staff,
        "_id": new_id("mbr"),
        "phone": phone,
        "name": name,
        "city": outlet.get("city") or outlet.get("area"),
        "joinedAt": iso(now),
        "joinedDay": today_wib(),
        "firstOutletId": outlet["_id"],
        "source": None,
        "profileSkips": 0,
        "optIn": True if opt_in is None else bool(opt_in),
        "stampsActive": 0,
        "stampsTotal": 0,
        "visits": 0,
        "lastVisitAt": None,
        "lastOutletId": None,
        "deviceTokens": [],
        "blocked": False,
        "createdAt": iso(now),
    }
    try:
        await db.members.insert_one(member)
    except Exception:
        # Balapan: nomor sama baru saja dibuat oleh request lain
        existing = await db.members.find_one({"phone": phone})
        if existing:
            return existing, False, None
        raise
    welcome = None if is_staff else await create_welcome_voucher(db, member["_id"], settings)
    return member, True, welcome


async def attach_device(db: AsyncIOMotorDatabase, member: dict, device_token: str | None) -> tuple[str, bool]:
    """Pastikan perangkat tercatat; kembalikan (token, perangkat_baru)."""
    tokens = member.get("deviceTokens") or []
    if device_token and device_token in tokens:
        return device_token, False
    token = device_token or new_token()
    # Maksimal 5 perangkat terakhir per member
    new_tokens = (tokens + [token])[-5:]
    await db.members.update_one({"_id": member["_id"]}, {"$set": {"deviceTokens": new_tokens}})
    member["deviceTokens"] = new_tokens
    return token, bool(tokens)  # perangkat "baru" hanya bila sebelumnya sudah ada perangkat lain


async def evaluate_rules(db: AsyncIOMotorDatabase, member: dict, outlet: dict, settings: dict) -> tuple[bool, str | None, str | None]:
    """Kembalikan (granted, reason_code, friendly_message)."""
    if member.get("blocked"):
        return False, "blocked", "Akun ini sedang ditinjau. Hubungi kami via WA ya, Kak."
    today = today_wib()
    today_granted = [s async for s in db.stamps.find({"memberId": member["_id"], "day": today, "granted": True})]
    per_outlet = sum(1 for s in today_granted if s["outletId"] == outlet["_id"])
    if per_outlet >= int(settings["maxStampsPerOutletPerDay"]):
        return False, "already_today", "Stamp hari ini di gerobak ini udah masuk, Kak. Besok mampir lagi ya 😄"
    if len(today_granted) >= int(settings["maxStampsPerDay"]):
        return False, "over_limit", "Stamp hari ini udah maksimal, Kak. Besok lanjut lagi ya!"
    last = await db.stamps.find_one({"memberId": member["_id"], "granted": True}, sort=[("at", -1)])
    if last:
        gap = now_utc() - parse_iso(last["at"])
        min_gap = timedelta(minutes=int(settings["minMinutesBetweenStamps"]))
        if gap < min_gap:
            sisa = max(1, int((min_gap - gap).total_seconds() // 60) + 1)
            return False, "too_fast", f"Stamp berikutnya bisa diambil {sisa} menit lagi ya, Kak."
    return True, None, None


async def process_stamp(
    db: AsyncIOMotorDatabase,
    settings: dict,
    qr_token: str,
    request_id: str,
    phone: str | None = None,
    device_token: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    promo_code: str | None = None,
    ip: str | None = None,
    opt_in: bool | None = None,
    name: str | None = None,
) -> dict:
    outlet = await outlet_by_token(db, qr_token)

    member = await find_member_by_device(db, device_token)
    is_new = False
    welcome = None
    if member is None:
        if not phone:
            return {
                "needPhone": True,
                "outlet": outlet_public(outlet, settings),
            }
        member, is_new, welcome = await find_or_create_member(db, phone, outlet, settings, opt_in, name)
    elif phone:
        # Perangkat dikenal tapi nomor yang diketik berbeda → pindah ke akun nomor tersebut
        other = normalize_phone(phone)
        if other and other != member["phone"]:
            member, is_new, welcome = await find_or_create_member(db, phone, outlet, settings, opt_in, name)

    # Idempotensi: requestId sama dalam 5 menit → hasil yang sama
    if request_id:
        since = iso(now_utc() - timedelta(minutes=5))
        dup = await db.stamps.find_one({"requestId": request_id, "memberId": member["_id"], "at": {"$gte": since}})
        if dup:
            if promo_code is not None:
                # Toggle promo dari halaman hasil: catat/hapus kode promo pada stamp yang sama
                active_promo = (settings.get("activePromoCode") or "").upper()
                code = promo_code.strip().upper() or None
                dup["promoCode"] = code if code and code == active_promo else None
                await db.stamps.update_one({"_id": dup["_id"]}, {"$set": {"promoCode": dup["promoCode"]}})
            fresh = await db.members.find_one({"_id": member["_id"]})
            return await build_response(db, settings, outlet, fresh, dup, is_new=False, welcome=None,
                                        device_token=device_token or (fresh.get("deviceTokens") or [None])[-1])

    token, device_new = await attach_device(db, member, device_token)
    granted, reason, message = await evaluate_rules(db, member, outlet, settings)

    flags: list[str] = []
    distance = None
    if lat is not None and lng is not None and outlet.get("lat") is not None and outlet.get("lng") is not None:
        distance = round(haversine_m(lat, lng, float(outlet["lat"]), float(outlet["lng"])))
        if distance > int(settings["geofenceM"]):
            flags.append("jauh")
    if device_new:
        flags.append("device_baru")
    if reason == "too_fast":
        flags.append("cepat")
    if reason == "over_limit":
        flags.append("over_limit")

    now = now_utc()
    promo = (promo_code or "").strip().upper() or None
    active_promo = (settings.get("activePromoCode") or "").upper()
    if promo and promo != active_promo:
        promo = None
    stamp = {
        "_id": new_id("stp"),
        "memberId": member["_id"],
        "outletId": outlet["_id"],
        "outletCode": outlet["code"],
        "area": outlet["area"],
        "at": iso(now),
        "day": day_str(now),
        "hour": hour_wib(now),
        "promoCode": promo,
        "distanceM": distance,
        "flags": flags,
        "granted": granted,
        "reason": reason,
        "message": message,
        "requestId": request_id,
        "ip": ip,
        "isNewMember": is_new,
        "isStaff": bool(member.get("isStaff")),
    }
    await db.stamps.insert_one(stamp)

    reward = None
    update: dict = {"$set": {"lastVisitAt": iso(now), "lastOutletId": outlet["_id"]}}
    if granted:
        stamps_active = int(member.get("stampsActive", 0)) + 1
        inc = {"stampsTotal": 1, "visits": 1}
        if stamps_active >= int(settings["stampsPerReward"]):
            stamps_active = 0
            if member.get("isStaff"):
                inc["rewardsSkippedStaff"] = 1  # Lapis 3: crew/keluarga tidak dapat voucher
            else:
                reward = await create_reward_voucher(db, member["_id"], settings)
                inc["rewardsEarned"] = 1
        update["$set"]["stampsActive"] = stamps_active
        update["$inc"] = inc
    await db.members.update_one({"_id": member["_id"]}, update)
    fresh = await db.members.find_one({"_id": member["_id"]})
    return await build_response(db, settings, outlet, fresh, stamp, is_new, welcome, token, reward)


async def build_response(
    db, settings, outlet, member, stamp, is_new, welcome, device_token, reward=None
) -> dict:
    vouchers = await member_vouchers(db, member["_id"])
    per_reward = int(settings["stampsPerReward"])
    active = int(member.get("stampsActive", 0))
    sisa = per_reward - active
    if stamp["granted"] and member.get("isStaff"):
        headline = "Stamp tercatat. Nomor ini terdaftar sebagai crew, jadi tanpa voucher ya."
    elif stamp["granted"]:
        if reward:
            headline = f"{per_reward} stamp penuh! {settings['rewardTitle']} buat Kakak."
            if reward.get("status") == "scheduled":
                headline += " Bisa ditukar mulai besok ya."
        elif is_new:
            headline = "Stamp pertama dapet, Kak! Makasih udah gabung."
        else:
            headline = f"Stamp ke-{active} dapet, Kak! {sisa} lagi {settings['rewardTitle'].lower()}."
    else:
        headline = stamp.get("message") or "Stamp belum bisa diambil sekarang."

    ask_profile = (
        int(member.get("visits", 0)) >= 2
        and not member.get("source")
        and int(member.get("profileSkips", 0)) < 2
    )
    return {
        "needPhone": False,
        "granted": stamp["granted"],
        "reason": stamp.get("reason"),
        "headline": headline,
        "isNewMember": is_new,
        "rewardIssued": bool(reward),
        "stampId": stamp["_id"],
        "stampsActive": active,
        "stampsPerReward": per_reward,
        "stampsTotal": int(member.get("stampsTotal", 0)),
        "deviceToken": device_token,
        "member": member_public(member),
        "outlet": outlet_public(outlet, settings),
        "vouchers": vouchers,
        "welcomeVoucher": next((v for v in vouchers if v["type"] == "balik_lagi"), None) if is_new else None,
        "askProfile": ask_profile,
        "askFeedback": bool(settings.get("feedbackPrompt", True)) and stamp["granted"] and not member.get("isStaff"),
    }
