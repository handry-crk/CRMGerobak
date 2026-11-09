"""Voucher: welcome (Balik Lagi), reward 5 stamp, campaign; aktivasi & kedaluwarsa."""
from __future__ import annotations

from datetime import timedelta

from motor.motor_asyncio import AsyncIOMotorDatabase

from ..utils import add_days, format_rp, format_tanggal, iso, new_id, new_redeem_code, now_utc, today_wib


def voucher_public(v: dict, settings: dict | None = None) -> dict:
    return {
        "id": v["_id"],
        "type": v["type"],
        "title": v["title"],
        "valueRp": v.get("valueRp", 0),
        "minSpendRp": v.get("minSpendRp", 0),
        "validFrom": v["validFrom"],
        "validTo": v["validTo"],
        "validFromText": format_tanggal(v["validFrom"]),
        "validToText": format_tanggal(v["validTo"]),
        "status": v["status"],
        "usedAt": v.get("usedAt"),
        "usedOutletName": v.get("usedOutletName"),
        "redeemCode": v.get("redeemCode"),
        "redeemExpiresAt": v.get("redeemExpiresAt"),
        "campaignCode": v.get("campaignCode"),
        "description": (
            f"Minimal belanja {format_rp(v['minSpendRp'])}" if v.get("minSpendRp") else ""
        ),
    }


async def create_welcome_voucher(db: AsyncIOMotorDatabase, member_id: str, settings: dict) -> dict | None:
    cfg = settings["welcomeVoucher"]
    if not cfg.get("enabled"):
        return None
    today = today_wib()
    valid_from = add_days(today, int(cfg["startAfterDays"]))
    valid_to = add_days(valid_from, int(cfg["validDays"]))
    doc = {
        "_id": new_id("vch"),
        "memberId": member_id,
        "type": "balik_lagi",
        "title": f"Voucher Balik Lagi: {cfg['title']}",
        "valueRp": int(cfg["valueRp"]),
        "minSpendRp": int(cfg["minSpendRp"]),
        "validFrom": valid_from,
        "validTo": valid_to,
        "status": "active" if valid_from <= today else "scheduled",
        "createdAt": iso(now_utc()),
    }
    await db.vouchers.insert_one(doc)
    return doc


async def create_reward_voucher(db: AsyncIOMotorDatabase, member_id: str, settings: dict) -> dict:
    today = today_wib()
    valid_from = add_days(today, int(settings.get("rewardRedeemAfterDays", 0)))
    doc = {
        "_id": new_id("vch"),
        "memberId": member_id,
        "type": "stamp_reward",
        "title": settings["rewardTitle"],
        "valueRp": int(settings["rewardValueRp"]),
        "minSpendRp": 0,
        "validFrom": valid_from,
        "validTo": add_days(valid_from, int(settings["rewardVoucherValidDays"])),
        "status": "active" if valid_from <= today else "scheduled",
        "createdAt": iso(now_utc()),
    }
    await db.vouchers.insert_one(doc)
    return doc


async def create_campaign_vouchers(db: AsyncIOMotorDatabase, campaign: dict, member_ids: list[str]) -> int:
    today = today_wib()
    docs = []
    for mid in member_ids:
        docs.append(
            {
                "_id": new_id("vch"),
                "memberId": mid,
                "type": "campaign",
                "title": campaign["title"],
                "valueRp": int(campaign.get("valueRp", 0)),
                "minSpendRp": int(campaign.get("minSpendRp", 0)),
                "validFrom": campaign["validFrom"],
                "validTo": campaign["validTo"],
                "status": "active" if campaign["validFrom"] <= today else "scheduled",
                "campaignCode": campaign["code"],
                "createdAt": iso(now_utc()),
            }
        )
    if docs:
        await db.vouchers.insert_many(docs)
    return len(docs)


async def member_vouchers(db: AsyncIOMotorDatabase, member_id: str, include_history: bool = False) -> list[dict]:
    q: dict = {"memberId": member_id}
    if not include_history:
        q["status"] = {"$in": ["active", "scheduled"]}
    cur = db.vouchers.find(q).sort("createdAt", -1)
    return [voucher_public(v) async for v in cur]


async def activate_due_vouchers(db: AsyncIOMotorDatabase) -> int:
    today = today_wib()
    res = await db.vouchers.update_many(
        {"status": "scheduled", "validFrom": {"$lte": today}}, {"$set": {"status": "active"}}
    )
    return res.modified_count


async def expire_vouchers(db: AsyncIOMotorDatabase) -> int:
    today = today_wib()
    res = await db.vouchers.update_many(
        {"status": {"$in": ["active", "scheduled"]}, "validTo": {"$lt": today}},
        {"$set": {"status": "expired"}},
    )
    return res.modified_count


class RedeemError(Exception):
    def __init__(self, message: str, code: str = "redeem_failed"):
        super().__init__(message)
        self.message = message
        self.code = code


async def redeem_voucher(
    db: AsyncIOMotorDatabase, member: dict, voucher_id: str, qr_token: str, settings: dict
) -> dict:
    """Penukaran: voucher aktif + member sedang di gerobak (ada scan ≤ outletSessionMinutes lalu)."""
    voucher = await db.vouchers.find_one({"_id": voucher_id, "memberId": member["_id"]})
    if not voucher:
        raise RedeemError("Voucher tidak ditemukan.", "not_found")
    today = today_wib()
    if voucher["status"] == "used":
        raise RedeemError("Voucher ini sudah ditukar.", "used")
    if voucher["status"] == "expired" or voucher["validTo"] < today:
        raise RedeemError("Voucher sudah lewat masa berlakunya.", "expired")
    if voucher["status"] == "scheduled" or voucher["validFrom"] > today:
        raise RedeemError(f"Voucher baru bisa dipakai mulai {format_tanggal(voucher['validFrom'])}.", "not_yet")

    outlet = await db.outlets.find_one({"qrToken": qr_token, "active": True})
    if not outlet:
        raise RedeemError("Scan QR gerobak dulu ya, Kak.", "no_outlet")
    since = iso(now_utc() - timedelta(minutes=int(settings.get("outletSessionMinutes", 60))))
    recent = await db.stamps.find_one(
        {"memberId": member["_id"], "outletId": outlet["_id"], "at": {"$gte": since}}
    )
    if not recent:
        raise RedeemError("Scan QR gerobak dulu ya, Kak.", "no_outlet")

    if settings.get("feedbackRequired", True) and recent.get("granted") and not member.get("isStaff"):
        fb = await db.feedback.find_one({"stampId": recent["_id"], "complete": True})
        if not fb:
            raise RedeemError("Isi rating pelayanan dulu ya, Kak, baru voucher bisa ditukar.", "need_feedback")
        from .stamp import pending_taste
        if await pending_taste(db, member["_id"], exclude_stamp_id=recent["_id"]):
            raise RedeemError("Kasih nilai rasa cimol kunjungan sebelumnya dulu ya, Kak.", "need_taste")

    # Lapis 1: kuota penukaran per gerobak per hari
    quota = int(settings.get("maxRedemptionsPerOutletPerDay", 0) or 0)
    if quota:
        used_today = await db.vouchers.count_documents(
            {"status": "used", "usedOutletId": outlet["_id"], "usedAt": {"$gte": today, "$lte": today + "T23:59:59Z"}}
        )
        if used_today >= quota:
            await db.alerts.insert_one({
                "_id": new_id("alr"), "type": "redeem_quota", "outletId": outlet["_id"], "outletCode": outlet["code"], "memberId": member["_id"],
                "day": today, "at": iso(now_utc()), "note": f"Kuota {quota} penukaran/hari tercapai",
            })
            raise RedeemError("Penukaran di gerobak ini hari ini sudah penuh, Kak. Voucher tetap aman, coba besok ya.", "quota")

    now = now_utc()
    code = new_redeem_code()
    expires = iso(now + timedelta(seconds=int(settings.get("redeemCountdownSec", 180))))
    await db.vouchers.update_one(
        {"_id": voucher_id, "status": "active"},
        {
            "$set": {
                "status": "used",
                "usedAt": iso(now),
                "usedOutletId": outlet["_id"],
                "usedOutletName": outlet["name"],
                "redeemCode": code,
                "redeemExpiresAt": expires,
            }
        },
    )
    fresh = await db.vouchers.find_one({"_id": voucher_id})
    if fresh.get("status") != "used" or fresh.get("redeemCode") != code:
        raise RedeemError("Voucher ini sudah ditukar.", "used")
    return voucher_public(fresh)
